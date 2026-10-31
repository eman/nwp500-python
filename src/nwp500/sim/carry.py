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

from nwp500.sim.api import simulate
from nwp500.sim.engine import Resume
from nwp500.sim.extensions import RecoveryModel
from nwp500.sim.inputs import HEAT_PUMP, Commands, Loads, Scenario, Write
from nwp500.sim.params import HeaterParams
from nwp500.sim.physics.stratified import TankState, energy_btu, layout
from nwp500.sim.result import SimulationResult
from nwp500.sim.schedules import reservation_firings
from nwp500.sim.units import BTU_PER_WH

#: How near, °F in every layer, a tail's end must come to the first
#: walk's tail's for the two to count as settled (``Carried.settled``).
SETTLED_F = 0.5
#: How far past the last instant still due at the tails' ends (a
#: hold's end, a pending start, a lockout's release, an element's heat
#: reaching the water) each tail is walked on to see it go on.
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
    #: walked on with no draw past every instant still due at either's
    #: end (a start's hold ending, a start pending, the restart lockout
    #: releasing, an element's heat reaching the water) and
    #: ``GO_ON_PAST`` more, spending the same electricity, within
    #: ``GO_ON_WH``. Heating under way in one and not the other is heat
    #: one is still to pay for; a lockout with no start wanted in it is
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
    an entry of the tail's fires at its start). An element mode held
    stays held to the walk's window's close, as a direct write of it
    inside a window would be. A walk that ends in, or a tail that starts
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
    tails: list[SimulationResult] = []
    for walk in walks:
        if walk.until != tail.start:
            raise ValueError(
                f"a walk ends at {walk.until.isoformat()}, the tail "
                f"starts at {tail.start.isoformat()}"
            )
        if walk.end_state is None or walk.end_history is None:
            raise ValueError("a walk carries no end to go on from")
        tails.append(
            simulate(
                tail.model_copy(
                    update={
                        "state": walk.end_state,
                        "history": walk.end_history,
                        "commands": _over_a_hold(walk, tail),
                    }
                ),
                params,
                **options,
            )
        )
    lay = layout(params)
    ends = [_layers(t) for t in tails]
    gone_on = _go_on(tails, tail, params, options)
    first = ends[0]
    first_wh = energy_btu(lay, TankState(first)) / BTU_PER_WH
    return tuple(
        Carried(
            walk=walk,
            tail=t,
            residual_wh=energy_btu(lay, TankState(end)) / BTU_PER_WH - first_wh,
            residual_f=max(abs(a - b) for a, b in zip(end, first, strict=True)),
            heating_alike=_alike(wh, gone_on[0]),
        )
        for walk, t, end, wh in zip(walks, tails, ends, gone_on, strict=True)
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
    An element mode held is left held: a direct write of one inside a
    window is held again."""
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
        f.at == tail.start
        for f in reservation_firings(
            schedule, ZoneInfo(tail.tz), tail.start, tail.until
        )
    )


def _go_on(
    tails: Sequence[SimulationResult],
    tail: Scenario,
    params: HeaterParams,
    options: dict[str, Any],
) -> list[float | None]:
    """Each tail's electricity walked on from its end with no draw,
    past every instant still due at any tail's end and ``GO_ON_PAST``
    more, Wh (None, unpriced)."""
    until = tail.until
    due = [t for r in tails for t in _due(r, params)]
    span = max([until, *due]) - until + GO_ON_PAST
    out: list[float | None] = []
    for r in tails:
        assert r.end_state is not None and r.end_history is not None
        on = simulate(
            tail.model_copy(
                update={
                    "start": until,
                    "horizon": span,
                    "state": r.end_state,
                    "history": r.end_history,
                    "loads": Loads(),
                    "commands": Commands(),
                }
            ),
            params,
            **options,
        )
        out.append(on.input_wh)
    return out


def _due(result: SimulationResult, params: HeaterParams) -> list[datetime]:
    """The instants still due at ``result``'s end: its compressor
    start's hold ending, a start pending, the restart lockout
    releasing, an element's heat reaching the water."""
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
    if resume.element is not None:
        out.append(resume.element.live_at)
    lag = timedelta(minutes=params.element.upper_dead_time_min)
    out += [e.off_at + lag for e in resume.cooling if e.off_at is not None]
    return out


def _alike(wh: float | None, first: float | None) -> bool:
    return wh is not None and first is not None and abs(wh - first) <= GO_ON_WH


def _layers(result: SimulationResult) -> tuple[float, ...]:
    end = result.end_state
    if end is None or end.layers_f is None:
        raise ValueError("a tail carries no layers at its end")
    return tuple(end.layers_f)
