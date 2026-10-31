"""What a walk leaves behind: walks carried on through one tail.

A walk's electricity over its own span says nothing of the tank it
leaves. A change that heats late, or not at all, can come out cheapest
over its day and owe the difference the next: a tank left 30 °F short
is heated again, at whatever the hour of that reheat costs. Two
changes (``Commands``) are weighed on an equal footing only when each
walk is carried on until what they left no longer differs.

``carry_on`` walks every walk's end through the same ``tail``: the
heater in its standing settings (written at the tail's start over
whatever a walk left in force), the same draws, air and schedules.
Tails that end alike, the same layers with the same heating under way,
leave nothing between the walks unvalued, so a walk's electricity and
its tail's, priced at any tariff, are the whole of what the change
costs. How alike the tails end is given (``Carried.residual_f``,
``Carried.residual_wh``, ``Carried.heating_alike``): a tail too short
to settle them leaves that much out.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nwp500.sim.api import ENGINE_MODE, simulate
from nwp500.sim.circulation import RUN_GAP, Circulation
from nwp500.sim.engine import RECOVERY_AHEAD, Resume
from nwp500.sim.extensions import RecoveryModel
from nwp500.sim.inputs import (
    HEAT_PUMP,
    CirculationRun,
    Commands,
    Draw,
    Loads,
    Scenario,
    Write,
)
from nwp500.sim.params import HeaterParams
from nwp500.sim.physics.stratified import TankState, energy_btu, layout
from nwp500.sim.result import SimulationResult
from nwp500.sim.schedules import reservation_firings, tou_windows
from nwp500.sim.tou_triggers import while_enabled
from nwp500.sim.units import BTU_PER_WH

#: How near, °F in every layer, a tail's end must come to the first
#: walk's tail's for the two to count as settled (``Carried.settled``).
SETTLED_F = 0.5
#: How far past the last instant still due at the tails' ends (a
#: hold's end, a pending start, a lockout's release, an element's heat
#: reaching the water, a held mode landing, a capped stop's window
#: closing, the close of a TOU window in force or opening on the way)
#: each tail is walked on to see it go on, up to ``RECOVERY_AHEAD``.
GO_ON_PAST = timedelta(minutes=1)
#: How near, Wh, the electricity of a tail walked on must come to the
#: first walk's tail's for the two to go on alike.
GO_ON_WH = 1.0


@dataclass(frozen=True)
class Carried:
    """A walk and the tail walked on from where it ended."""

    walk: SimulationResult
    tail: SimulationResult
    #: The heat the tail ends with less the first walk's tail's, Wh:
    #: what this walk leaves that the tail did not value (positive,
    #: more heat left).
    residual_wh: float
    #: The largest difference of a layer at the tail's end from the
    #: first walk's tail's, °F.
    residual_f: float
    #: Whether the tail goes on as the first walk's tail does: each
    #: tail's scenario walked on, with no water drawn and no
    #: circulation starting past its end, past every instant still due
    #: at any tail's end (a start's hold ending, a start pending, the
    #: restart lockout releasing, an element's heat reaching the water,
    #: a held mode landing, a capped stop's window closing) and every
    #: TOU window open on the way, up to
    #: ``RECOVERY_AHEAD``, and ``GO_ON_PAST`` more, spending the same
    #: electricity past the end, within ``GO_ON_WH``, and ending with
    #: the same layers, within ``SETTLED_F`` (an element's heat still
    #: on its way is in the water by then). Heating under way, or a
    #: start a window holds off, in one and not the other is heat one
    #: is still to pay for; a lockout with no start wanted in it is
    #: none.
    heating_alike: bool

    @property
    def settled(self) -> bool:
        """Whether the tail ends as the first walk's tail does: within
        ``SETTLED_F`` in every layer, and going on as it does
        (``heating_alike``)."""
        return self.residual_f <= SETTLED_F and self.heating_alike

    @property
    def input_wh(self) -> float | None:
        """The electricity of the walk and its tail, Wh. None when an
        interval of either could not be priced."""
        walk, tail = self.walk.input_wh, self.tail.input_wh
        return None if walk is None or tail is None else walk + tail

    def energy_by_slot(
        self, slot: timedelta = timedelta(hours=1)
    ) -> list[tuple[datetime, float | None]]:
        """The walk's and its tail's electricity per clock-aligned
        ``slot``, Wh, as ``SimulationResult.energy_by_slot`` gives it: a
        slot the two share holds both."""
        out: dict[datetime, float | None] = {}
        for at, wh in [
            *self.walk.energy_by_slot(slot),
            *self.tail.energy_by_slot(slot),
        ]:
            if at not in out:
                out[at] = wh
            else:
                held = out[at]
                out[at] = None if held is None or wh is None else held + wh
        return sorted(out.items())


def carry_on(
    walks: Sequence[SimulationResult],
    tail: Scenario,
    params: HeaterParams,
    *,
    recovery: RecoveryModel | None = None,
    tou_windows_in_force: Sequence[tuple[datetime, datetime]] | None = None,
    withheld_windows: Sequence[tuple[datetime, datetime]] = (),
    inlet_measured: bool = False,
    start_hold: Callable[[float | None], float] | None = None,
) -> tuple[Carried, ...]:
    """Each of ``walks`` walked on through ``tail`` from where it ended,
    in their order, each tail's end set beside the first's.

    ``tail`` is the span after the walks: its settings the heater's
    standing ones, its loads, environment and schedules what follows.
    Its ``state`` and ``history`` are each walk's end
    (``SimulationResult.end_state``, ``end_history``); its settings are
    written at its start over what the walk left. Every walk must end
    where ``tail`` starts. A tail long enough to take each tank through
    the recovery the heater makes anyway ends them alike
    (``Carried.settled``). A walk that ends with a Heat Pump write held
    in a window, carried into a tail standing in Heat Pump, has
    Heat Pump written at the tail's start, ahead of its own commands,
    so the hold is withdrawn as a direct write withdraws one (not when
    an entry of the tail's fires at its start). An element mode held,
    carried into a tail standing in that mode, stays held to the walk's
    window's close, as a direct write of it inside a window would be;
    into one standing in another mode, the tail's settings write it
    over the hold. A walk that ends in, or a tail that starts
    in, Vacation or Power Off with the other not is carried on afresh
    from the walk's layers and history, as ``simulate`` goes on from
    any (``resume_dropped_*`` in the tail's ``reasons``).

    The keyword inputs are ``simulate``'s, the same for every tail.
    ``recovery``, ``start_hold`` and ``inlet_measured`` go on as the
    walks had them: a walk made with a recovery model is carried on
    with it. ``tou_windows_in_force`` and ``withheld_windows`` are the
    tail's own, over its span: a walk's, before the tail starts, leave
    it with none.

    Raises ``ValueError`` when ``walks`` is empty, or a walk does not
    end where ``tail`` starts or carries no end, and
    ``engine.SimulationError`` when a walk cannot be completed.
    """
    if not walks:
        raise ValueError("no walks to carry on")
    options: dict[str, Any] = {
        "recovery": recovery,
        "tou_windows_in_force": tou_windows_in_force,
        "withheld_windows": withheld_windows,
        "inlet_measured": inlet_measured,
        "start_hold": start_hold,
    }
    scenarios: list[Scenario] = []
    tails: list[SimulationResult] = []
    for walk in walks:
        if walk.until != tail.start:
            raise ValueError(
                f"a walk ends at {walk.until.isoformat()}, the tail "
                f"starts at {tail.start.isoformat()}"
            )
        if walk.end_state is None or walk.end_history is None:
            raise ValueError("a walk carries no end to go on from")
        scenario = tail.model_copy(
            update={
                "state": walk.end_state,
                "history": walk.end_history,
                "commands": _over_a_hold(walk, tail),
            }
        )
        scenarios.append(scenario)
        tails.append(simulate(scenario, params, **options))
    lay = layout(params)
    ends = [_layers(t) for t in tails]
    gone_on = _go_on(scenarios, tails, params, options)
    first = ends[0]
    first_wh = energy_btu(lay, TankState(first)) / BTU_PER_WH
    return tuple(
        Carried(
            walk=walk,
            tail=t,
            residual_wh=energy_btu(lay, TankState(end)) / BTU_PER_WH - first_wh,
            residual_f=max(abs(a - b) for a, b in zip(end, first, strict=True)),
            heating_alike=_alike(gone, gone_on[0]),
        )
        for walk, t, end, gone in zip(walks, tails, ends, gone_on, strict=True)
    )


def _resume(result: SimulationResult) -> Resume | None:
    end = result.end_state
    if end is None or end.resume is None:
        return None
    return Resume.from_document(json.loads(end.resume))


def _over_a_hold(walk: SimulationResult, tail: Scenario) -> Commands:
    """The tail's commands, with Heat Pump written at its start first
    when the walk ended with a Heat Pump write held in a window and the
    tail stands in Heat Pump: settings naming the mode already
    commanded write nothing (``simulate`` goes on from them), so the
    hold would stand to the walk's window's close, where a direct
    Heat Pump write takes at once and withdraws it. Not when an entry of the
    tail's fires at its start, which decides the mode there itself.
    A tail standing in an element mode is left as it is: a direct
    write of one inside a window is held again. One standing in
    Heat Pump over a held element mode differs from what is commanded, and
    ``simulate`` writes it itself."""
    resume = _resume(walk)
    if (
        resume is None
        or resume.controller.mode.held is None
        or resume.controller.mode.commanded != "heat_pump"
        or tail.settings.mode != HEAT_PUMP
        or _entry_at_start(tail)
    ):
        return tail.commands
    return tail.commands.model_copy(
        update={
            "writes": (
                Write(at=tail.start, mode=HEAT_PUMP),
                *tail.commands.writes,
            )
        }
    )


def _entry_at_start(tail: Scenario) -> bool:
    written = tail.commands.reservations
    if written is not None:
        schedule = written
    elif tail.schedules.reservations_enabled:
        schedule = tail.schedules.reservations
    else:
        return False
    return any(
        f.at == tail.start and f.entry.mode in ENGINE_MODE
        for f in reservation_firings(
            schedule, ZoneInfo(tail.tz), tail.start, tail.until
        )
    )


def _go_on(
    scenarios: Sequence[Scenario],
    tails: Sequence[SimulationResult],
    params: HeaterParams,
    options: dict[str, Any],
) -> list[tuple[float | None, tuple[float, ...]]]:
    """Each tail walked on past its end: its scenario again, longer by
    ``GO_ON_PAST`` past every instant still due at any tail's end
    (``_due``) and the close of every TOU window open on the way, up to
    ``RECOVERY_AHEAD``, so its settings, writes and schedules go on as
    they would, with no water drawn and no circulation starting past
    the end (``_drawn_by``). The electricity it spends past the end, Wh
    (None, unpriced), and the layers it ends with."""
    until = scenarios[0].until
    given = options.get("tou_windows_in_force")
    due = [t for r in tails for t in _due(r, params)]
    span = max([until, *due]) - until + GO_ON_PAST
    while span < RECOVERY_AHEAD:
        end = until + span
        closes = [
            b
            for a, b in _windows(scenarios[0], given, end)
            if a < end and b > until
        ]
        grown = max([until, *due, *closes]) - until + GO_ON_PAST
        if grown <= span:
            break
        span = grown
    span = min(span, RECOVERY_AHEAD)
    out: list[tuple[float | None, tuple[float, ...]]] = []
    for scenario, r in zip(scenarios, tails, strict=True):
        on = simulate(
            scenario.model_copy(
                update={
                    "horizon": scenario.horizon + span,
                    "loads": _drawn_by(scenario.loads, until, params),
                }
            ),
            params,
            **options,
        )
        wh = (
            None
            if on.input_wh is None or r.input_wh is None
            else on.input_wh - r.input_wh
        )
        out.append((wh, _layers(on)))
    return out


def _drawn_by(loads: Loads, until: datetime, params: HeaterParams) -> Loads:
    """``loads`` with only the water drawn and the circulation started
    before ``until``. A draw running past it is kept as the pieces the
    walk took before it, each at its instant with the draw's own
    per-draw volume. The runs are merged first, as ``simulate`` merges
    them over the whole input (``CirculationParams.run_gap_min``), and
    those starting before ``until`` kept: one under way there, runs
    past it merged in, goes on whole as the tail ran it."""
    draws: list[Draw] = []
    for d in loads.draws:
        pieces = [(at, g) for at, g in d.pieces() if at < until]
        if len(pieces) == len(d.pieces()):
            draws.append(d)
            continue
        per_draw = d.per_draw_gal if d.per_draw_gal is not None else d.gallons
        draws += [
            Draw(at=at, gallons=g, per_draw_gal=per_draw)
            for at, g in pieces
            if g > 0.0
        ]
    if loads.circulation is None:
        return loads.model_copy(update={"draws": tuple(draws)})
    gap = (
        RUN_GAP
        if params.circulation is None
        else timedelta(minutes=params.circulation.run_gap_min)
    )
    known = loads.circulation_known_until
    merged = Circulation(
        tuple((r.start, r.end) for r in loads.circulation), known, gap
    ).runs
    return loads.model_copy(
        update={
            "draws": tuple(draws),
            "circulation": tuple(
                CirculationRun(start=a, end=b) for a, b in merged if a < until
            ),
            "circulation_known_until": until
            if known is None
            else min(known, until),
        }
    )


def _windows(
    tail: Scenario,
    given: Sequence[tuple[datetime, datetime]] | None,
    end: datetime,
) -> Sequence[tuple[datetime, datetime]]:
    """The TOU windows of ``tail`` walked on to ``end``: the given ones,
    else its schedule's, laid out as ``simulate`` lays them out."""
    if given is None:
        tou_on = (
            tail.commands.tou_enabled
            if tail.commands.tou_enabled is not None
            else tail.schedules.tou_enabled
        )
        switches = tail.schedules.tou_switches
        given = (
            while_enabled(
                tou_windows(
                    tail.schedules.tou_periods,
                    ZoneInfo(tail.tz),
                    tail.start,
                    end + RECOVERY_AHEAD,
                ),
                tou_on,
                switches,
            )
            if tou_on or any(on for _, on in switches)
            else ()
        )
    return given


def _due(result: SimulationResult, params: HeaterParams) -> list[datetime]:
    """The instants still due at ``result``'s end: its compressor
    start's hold ending, a start pending, the restart lockout
    releasing, an element's heat reaching the water, a held mode
    landing, the window a capped stop came in closing."""
    resume = _resume(result)
    if resume is None:
        return []
    out: list[datetime] = []
    c = resume.controller.compressor
    if resume.cycle is not None:
        out.append(resume.cycle.heats_at)
    if c.pending is not None:
        out.append(c.pending.at)
    if c.last_stop is not None:
        out.append(c.last_stop + params.controller.restart_lockout)
    if c.capped_until is not None:
        out.append(c.capped_until)
    if resume.controller.mode.held is not None:
        out.append(resume.controller.mode.held.until)
    if resume.element is not None:
        out.append(resume.element.live_at)
    lag = timedelta(minutes=params.element.upper_dead_time_min)
    out += [e.off_at + lag for e in resume.cooling if e.off_at is not None]
    return out


def _alike(
    gone: tuple[float | None, tuple[float, ...]],
    first: tuple[float | None, tuple[float, ...]],
) -> bool:
    (wh, layers), (first_wh, first_layers) = gone, first
    return (
        wh is not None
        and first_wh is not None
        and abs(wh - first_wh) <= GO_ON_WH
        and all(
            abs(a - b) <= SETTLED_F
            for a, b in zip(layers, first_layers, strict=True)
        )
    )


def _layers(result: SimulationResult) -> tuple[float, ...]:
    end = result.end_state
    if end is None or end.layers_f is None:
        raise ValueError("a tail carries no layers at its end")
    return tuple(end.layers_f)
