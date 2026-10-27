"""Time to ready: when the tank can run a bath, and how many showers it
is ready for, by heating mode (``sim.ready``).

``sim.delivery`` knows how many gallons a tank state can deliver. This
turns that into the answer: the bath and shower answers, the time to
bath-ready along the next heat-pump recovery and in each element mode,
and the reasons that say what the numbers rest on.

The recovery it scores (``Recovery``) is the one the heater runs next:
from now if the compressor runs, else from the heater's own trigger on
the coast to it, with the TOU cap judged where it ends. The heat it adds
to the book is the book's own compressor term, by the air now. The
element modes are the element model's (``physics.element.mode_recovery``).
Every mode is scored by the same deliverable rule on a one-minute grid.
"""

import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal

from nwp500.sim.book import (
    BTU_PER_WH,
    Booked,
    delivery_f,
)
from nwp500.sim.delivery import (
    Deliverable,
    booked_deliverable,
    deliverable,
)
from nwp500.sim.params import BookParams, ElementParams, ReadinessParams
from nwp500.sim.physics.element import (
    DEVICE_MODE,
    ElementMode,
    HeaterMode,
    mode_recovery,
    upper_rise_f,
)
from nwp500.sim.units import WATER_BTU_PER_GAL_F

#: Present on every answer while the model and the line are provisional:
#: the outlet lag rests on one measurement, the line is a choice, and the
#: upper probe stands in for the outlet.
ALWAYS: tuple[str, ...] = (
    "readiness_model_provisional",
    "depletion_threshold_provisional",
    "upper_probe_stand_in",
)

TrajectoryOutcome = Literal["ok", "not_scheduled", "unavailable", "idle"]


@dataclass(frozen=True)
class TankNow:
    """The live state readiness is computed from."""

    upper_f: float
    lower_f: float
    drawing: bool
    element_on: bool
    tou_window: bool
    #: The air the tank stands in, °F; None when it is not known.
    ambient_f: float | None = None
    compressor_on: bool = False


@dataclass(frozen=True)
class Recovery:
    """The heat-pump recovery from the tank now (``next_recovery``).

    ``points`` are ``(at, t_upper_f, t_lower_f)``; empty unless
    ``outcome`` is ``ok``. ``input_wh`` is the heat pump's electrical
    input over the interval ending at each point, where known.
    ``tou_capped`` says the recovery was projected only to the TOU
    window's reduced target, because the device heats no further until
    the window ends.
    """

    outcome: TrajectoryOutcome
    points: Sequence[tuple[datetime, float, float]] = ()
    tou_capped: bool = False
    input_wh: Sequence[float] = ()
    #: Minutes from now until the heat pump starts: 0 if it is running,
    #: else when the heater's own trigger fires.
    start_minute: float = 0.0
    #: Heat the tank loses before then to standby, in the book's frame;
    #: taken off pro rata over the coast.
    coast_btu: float = 0.0
    #: The draws before then, delivered gallons, taken the same way: the
    #: book takes their heat (``book.Booked.drawn``).
    coast_draw_gal: float = 0.0
    #: The book's compressor heat rate, by the air now. The recovery
    #: adds heat at this rate from its start to its end: the book's own
    #: term, not the physics' apparent-frame stored energy.
    hp_btu_per_h: float = 0.0
    #: The recovery as ``forecast`` gives it, each point with its
    #: electricity, stored heat and COP over the interval ending there
    #: (``heating_trajectory.HeatingPoint``): a projection's heating
    #: curve.
    trajectory: Sequence[Any] = ()
    #: The heat pump is outside its operating range (``unavailable``):
    #: every mode heats with the elements, as Electric does.
    hp_unavailable: bool = False


def recovery_as_of(rec: Recovery, then: datetime, now: datetime) -> Recovery:
    """``rec``, computed at ``then``, as seen from ``now``: for a
    caller that keeps a recovery and reuses it. ``points`` are absolute
    instants, but ``start_minute``, ``coast_btu`` and ``coast_draw_gal``
    run from the instant it was computed. Reused unchanged, the start
    comes ``now - then`` minutes late and the whole coast is charged
    again, though the book at ``now`` already holds what has happened:
    time to ready runs late by up to the age of the copy kept. The
    remaining coast keeps its pro-rata share."""
    elapsed = (now - then).total_seconds() / 60.0
    if rec.outcome != "ok" or elapsed <= 0.0 or rec.start_minute <= 0.0:
        return rec
    remaining = max(0.0, rec.start_minute - elapsed)
    return replace(
        rec,
        start_minute=remaining,
        coast_btu=rec.coast_btu * remaining / rec.start_minute,
        coast_draw_gal=rec.coast_draw_gal * remaining / rec.start_minute,
    )


#: The modes time to ready is reported for (``BathReady.by_mode``), in
#: this order.
MODES: tuple[HeaterMode, ...] = (
    "heat_pump",
    "energy_saver",
    "high_demand",
    "electric",
)

ELEMENT_MODES: tuple[HeaterMode, ...] = MODES[1:]

#: One-minute grid for every mode, so none looks faster for its spacing.
_GRID_MIN = 1.0


def showers_ready_for(deliverable_gal: float, shower_gal: float) -> float:
    """Showers the tank is ready for, two decimals."""
    if shower_gal <= 0:
        raise ValueError("shower_gal must be positive")
    return round(deliverable_gal / shower_gal, 2)


def whole_showers(ready_for: float) -> int:
    """``floor``: a shower the tank cannot finish is not one it is ready
    for. The epsilon keeps 2.00 from flooring to 1 on a float that came
    back as 1.9999999."""
    return max(0, math.floor(ready_for + 1e-9))


def assess(
    now: datetime,
    tank: TankNow,
    recovery: Recovery,
    *,
    bath_gal: float,
    bath_source: Literal["configured", "request"],
    shower_gal: float,
    shower_source: Literal["weekly_forecast", "default", "request"],
    valid_s: float,
    setpoint_f: float | None = None,
    booked: Booked | None = None,
    inlet_measured: bool = False,
    params: ReadinessParams | None = None,
    element_params: ElementParams | None = None,
    book_params: BookParams | None = None,
) -> dict[str, Any]:
    """The readiness answer as a mapping (``time_to_ready`` types it).

    Its keys: ``generated_at`` (``now``), ``valid_until`` (``now`` plus
    ``valid_s``), ``status`` (``low_confidence`` with any reason, else
    ``ok``), ``reasons``, ``line_f`` (``ReadinessParams.line_f``),
    ``tank_upper_f`` and ``tank_lower_f`` (two decimals),
    ``deliverable_gal``; ``bath``: ``volume_gal``, ``volume_source``
    (``bath_source``), ``ready``, ``margin_gal``, ``ready_in_minutes``,
    ``ready_at`` and ``by_mode`` (one row per ``MODES``: ``mode``,
    ``reachable_now``, ``ready_in_minutes``, ``ready_at``,
    ``energy_kwh``, ``reasons``); ``showers``: ``volume_gal``,
    ``volume_source`` (``shower_source``), ``ready_for`` and
    ``ready_for_whole``.

    ``reasons`` begins with ``ALWAYS``, then, as they apply:
    ``no_heat_book`` or ``heat_book_aged``; ``inlet_temp_modelled``
    (a book, and ``inlet_measured`` False); ``bath_volume_inferred``
    (``bath_source`` ``configured``); ``shower_volume_default``;
    ``capped_at_observed_volume``; ``bath_ready_within_estimate_error``
    (a book's error band) or ``bath_ready_within_probe_resolution``
    (without one); ``draw_in_progress``; ``element_running``;
    ``tou_window_in_force``; and, the bath not ready,
    ``heating_not_scheduled``, ``time_to_ready_unavailable``,
    ``heating_not_triggered``, ``bath_waits_for_tou_window_end`` or
    ``bath_not_reached_by_full_recovery``."""
    p = params or ReadinessParams()
    bp = book_params or BookParams()
    score = _scorer(booked, tank, p, bp)
    d = score(tank.upper_f, tank.lower_f, NOTHING_ADDED)
    bath_gal = round(bath_gal, 1)  # compared as it is reported
    reasons = list(ALWAYS)
    if booked is None:
        reasons.append("no_heat_book")
    elif booked.aged(bp):
        reasons.append("heat_book_aged")
    if booked is not None and not inlet_measured:
        reasons.append("inlet_temp_modelled")
    if bath_source == "configured":
        reasons.append("bath_volume_inferred")
    if shower_source == "default":
        reasons.append("shower_volume_default")
    if d.at_observed_max:
        reasons.append("capped_at_observed_volume")

    ready = d.gal >= bath_gal
    if booked is not None:
        # The book's own error, not the probe's, is what decides a close
        # call here: its 90th percentile, in gallons at this tank.
        per_gal = WATER_BTU_PER_GAL_F * max(
            1.0, delivery_f(tank.upper_f, bp) - booked.inlet_f
        )
        # An aged book's band is wider (``aged_error_btu``).
        if abs(d.gal - bath_gal) < booked.error_band_btu(bp) / per_gal:
            reasons.append("bath_ready_within_estimate_error")
    elif _flips_within_resolution(tank, bath_gal, ready, p, score):
        reasons.append("bath_ready_within_probe_resolution")
    if tank.drawing:
        reasons.append("draw_in_progress")
    if tank.element_on:
        reasons.append("element_running")
    if tank.tou_window:
        reasons.append("tou_window_in_force")

    by_mode = _by_mode(
        now,
        tank,
        recovery,
        bath_gal,
        ready,
        setpoint_f,
        score,
        element_params or ElementParams(),
    )
    ready_in = by_mode[0]["ready_in_minutes"]
    if not ready:
        if recovery.outcome == "not_scheduled":
            reasons.append("heating_not_scheduled")
        elif recovery.outcome == "unavailable" and not recovery.hp_unavailable:
            reasons.append("time_to_ready_unavailable")
        elif recovery.outcome == "idle":
            reasons.append("heating_not_triggered")
        elif ready_in is None:
            reasons.append(
                "bath_waits_for_tou_window_end"
                if recovery.tou_capped
                else "bath_not_reached_by_full_recovery"
            )

    ready_for = showers_ready_for(d.gal, shower_gal)
    return {
        "generated_at": now,
        "valid_until": now + timedelta(seconds=valid_s),
        "status": "low_confidence" if reasons else "ok",
        "reasons": reasons,
        "line_f": p.line_f,
        "tank_upper_f": round(tank.upper_f, 2),
        "tank_lower_f": round(tank.lower_f, 2),
        "deliverable_gal": d.gal,
        "bath": {
            "volume_gal": bath_gal,
            "volume_source": bath_source,
            "ready": ready,
            "margin_gal": round(d.gal - bath_gal, 1),
            "ready_in_minutes": ready_in,
            "ready_at": (
                None if ready_in is None else now + timedelta(minutes=ready_in)
            ),
            "by_mode": by_mode,
        },
        "showers": {
            "volume_gal": round(shower_gal, 2),
            "volume_source": shower_source,
            "ready_for": ready_for,
            "ready_for_whole": whole_showers(ready_for),
        },
    }


@dataclass(frozen=True)
class Added:
    """What a projection does to the booked state from now (``sim.book``):
    heat in from the compressor and the elements, heat out to standby,
    and delivered gallons drawn."""

    heat_btu: float = 0.0
    lost_btu: float = 0.0
    drawn_gal: float = 0.0

    def __add__(self, other: Added) -> Added:
        return Added(
            self.heat_btu + other.heat_btu,
            self.lost_btu + other.lost_btu,
            self.drawn_gal + other.drawn_gal,
        )

    def scaled(self, f: float) -> Added:
        return Added(
            self.heat_btu * f,
            self.lost_btu * f,
            self.drawn_gal * f,
        )


NOTHING_ADDED = Added()

#: Deliverable volume at ``(upper, lower, added)`` (``_scorer``).
Scorer = Callable[[float, float, Added], Deliverable]


def _scorer(
    booked: Booked | None,
    tank: TankNow,
    p: ReadinessParams,
    ep: BookParams | None = None,
) -> Scorer:
    """Deliverable volume at a tank state ``added`` has moved the booked
    state to since now: from the booked state when there is one, else
    from the probes and the evidence (which cannot use added heat, and
    do not need to: they read the state). The draws are drawn first:
    they are the coast's, which comes before any heating."""

    def score(upper: float, lower: float, added: Added) -> Deliverable:
        if booked is None:
            return deliverable(upper, lower, p, ep=ep)
        state = (
            booked.drawn(added.drawn_gal, tank.upper_f, ep)
            .heated(added.heat_btu)
            .lost(added.lost_btu)
        )
        return booked_deliverable(state, upper, lower, p, ep)

    return score


def _flips_within_resolution(
    tank: TankNow,
    bath_gal: float,
    ready: bool,
    p: ReadinessParams,
    score: Scorer,
) -> bool:
    """Whether a probe error of ``probe_resolution_f`` either way, on
    each probe on its own, would flip ``bath.ready``: near an evidence
    step, or with the bath that close to the probes' gallons
    (``delivery.probes_gal``), less than the probe can resolve decides
    the answer."""
    r = p.probe_resolution_f
    for up, low in itertools.product((-r, 0.0, r), repeat=2):
        if up == low == 0.0:
            continue
        other = score(tank.upper_f + up, tank.lower_f + low, NOTHING_ADDED)
        if (other.gal >= bath_gal) != ready:
            return True
    return False


#: ``(minute, upper, lower, cumulative input Wh, heat-pump heat BTU)``.
Path = list[tuple[float, float, float, float, float]]


def _coast_share(t: float, recovery: Recovery) -> Added:
    """What the coast has taken by minute ``t``, pro rata."""
    if recovery.coast_btu <= 0.0 and recovery.coast_draw_gal <= 0.0:
        return NOTHING_ADDED
    f = (
        1.0
        if recovery.start_minute <= 0.0
        else min(1.0, t / recovery.start_minute)
    )
    return Added(
        lost_btu=recovery.coast_btu * f,
        drawn_gal=recovery.coast_draw_gal * f,
    )


def _hp_path(now: datetime, tank: TankNow, recovery: Recovery) -> Path:
    """The heat-pump recovery as ``(minute, upper, lower, cumulative
    input Wh, heat-pump heat BTU)`` from now. It starts from the live
    state at minute 0, so a trajectory whose first point is later never
    reads as ready now. The heat is the book's: compressor heat from the
    recovery's start to its end."""
    out = [(0.0, tank.upper_f, tank.lower_f, 0.0, 0.0)]
    n = len(recovery.points)
    wh = list(recovery.input_wh) or [0.0] * n
    start = recovery.start_minute
    cum_in = 0.0
    for (at, u, lo), e in zip(recovery.points, wh, strict=False):
        cum_in += e
        minute = (at - now).total_seconds() / 60.0
        if minute <= 0.0:
            continue
        heated = recovery.hp_btu_per_h * max(0.0, minute - start) / 60.0
        out.append((minute, u, lo, cum_in, heated))
    return out


def _at(path: Path, t: float) -> tuple[float, float, float, float]:
    """``(upper, lower, input Wh, heat-pump heat BTU)`` at minute ``t``,
    linear between points; held at the end once the recovery is over
    and the tank stays where it finished."""
    if t <= path[0][0]:
        return path[0][1:]
    for a, b in itertools.pairwise(path):
        if a[0] <= t <= b[0]:
            f = 0.0 if b[0] == a[0] else (t - a[0]) / (b[0] - a[0])
            return tuple(  # type: ignore[return-value]
                x + (y - x) * f for x, y in zip(a[1:], b[1:], strict=True)
            )
    return path[-1][1:]


def _mode_state(
    mode: str,
    t: float,
    tank: TankNow,
    hp: Path | None,
    setpoint: float | None,
    upper_min: float | None,
    ep: ElementParams,
    recovery: Recovery | None = None,
    top: float | None = None,
    delay: float = 0.0,
) -> tuple[float, float, float, Added] | None:
    """Tank state, input energy (Wh) and what has been added to the
    booked state ``t`` minutes into ``mode``.

    Heat pump: its trajectory and its heat. Energy Saver and High
    Demand: the upper element heats the upper zone at its measured
    rate, while the heat pump carries the lower zone along its
    trajectory. Electric: the upper element, then the lower, and no
    heat pump.
    ``upper_min`` is when the upper element stops (None: it does not
    start), which in Energy Saver is short of the setpoint: its input
    ends there while the zone coasts on at the same rate to ``top``,
    the setpoint or, after a short run, below it (2026-10-02).
    The element's input starts at ``t`` = 0 and the upper zone's rise
    only after the dead time (``upper_rise_f``, 2026-10-02).
    None when the mode cannot be projected here.
    """
    coast = _coast_share(t, recovery) if recovery is not None else NOTHING_ADDED
    # Heating starts ``delay`` minutes in; the coast runs until then.
    t = max(0.0, t - delay)
    if mode == "heat_pump":
        if hp is None:
            return None
        u, lo, wh, heat = _at(hp, t)
        return u, lo, wh, coast + Added(heat_btu=heat)
    if setpoint is None:
        return None
    el_w = ep.element_w
    if mode == "electric":
        up_done = 0.0 if upper_min is None else upper_min
        if t <= up_done:
            u = min(setpoint, tank.upper_f + upper_rise_f(ep, t))
            wh = el_w * t / 60.0
            return u, tank.lower_f, wh, coast + Added(heat_btu=wh * BTU_PER_WH)
        lo_t = t - up_done
        lo_need = max(0.0, setpoint - tank.lower_f) / ep.lower_f_per_min
        lo_on = min(lo_t, lo_need)
        lo = min(setpoint, tank.lower_f + ep.lower_f_per_min * lo_t)
        u = setpoint if upper_min is not None else tank.upper_f
        top_wh = el_w * up_done / 60.0
        low_wh = el_w * lo_on / 60.0
        return (
            u,
            lo,
            top_wh + low_wh,
            coast + Added(heat_btu=(top_wh + low_wh) * BTU_PER_WH),
        )
    if hp is None:
        return None
    hu, hl, hwh, heat = _at(hp, t)
    added = coast + Added(heat_btu=heat)
    if upper_min is None:
        return hu, hl, hwh, added
    ceiling = setpoint if top is None else min(setpoint, top)
    eu = min(ceiling, tank.upper_f + upper_rise_f(ep, t))
    el_wh = el_w * min(t, upper_min) / 60.0
    return (
        max(hu, eu),
        hl,
        hwh + el_wh,
        added + Added(heat_btu=el_wh * BTU_PER_WH),
    )


def _by_mode(
    now: datetime,
    tank: TankNow,
    recovery: Recovery,
    bath_gal: float,
    ready: bool,
    setpoint: float | None,
    score: Scorer,
    ep: ElementParams,
) -> list[dict[str, Any]]:
    """Time to bath-ready and the energy to get there, per heating mode,
    all scored by the same deliverable rule."""
    not_heating = recovery.outcome == "not_scheduled"
    hp = _hp_path(now, tank, recovery) if recovery.outcome == "ok" else None
    horizon = 0.0
    if hp:
        horizon = hp[-1][0]
    rows = []
    for mode in MODES:
        # A mode write inside a TOU window may not take, and nothing is
        # entered while the appliance is not heating.
        reachable = not not_heating and (
            mode == "heat_pump" or not tank.tou_window
        )
        row: dict[str, Any] = {
            "mode": mode,
            "reachable_now": reachable,
            "ready_in_minutes": 0.0 if ready else None,
            "ready_at": now if ready else None,
            "energy_kwh": 0.0 if ready else None,
            "reasons": [],
        }
        rows.append(row)
        if ready or not_heating:
            continue
        upper_min = None
        top: float | None = None
        end = horizon
        # Outside the heat pump's range every mode heats as Electric: a
        # write to an element mode at once, Heat Pump from the heater's
        # own start.
        heats: HeaterMode = "electric" if recovery.hp_unavailable else mode
        delay = (
            recovery.start_minute
            if recovery.hp_unavailable and mode == "heat_pump"
            else 0.0
        )
        if heats != "heat_pump" and setpoint is not None:
            device: ElementMode = DEVICE_MODE[heats]  # type: ignore[assignment]
            rec = mode_recovery(
                device,
                tank.upper_f,
                tank.lower_f,
                setpoint,
                params=ep,
            )
            # When the upper element stops; the zone itself ends at
            # `upper_end_f`, by coasting the last stretch in Energy Saver,
            # the setpoint unless less than that is in transit.
            upper_min = rec.upper_element_minutes
            top = rec.upper_end_f
            # The element model's own caveats.
            row["reasons"] = list(rec.confidence_reasons)
            if heats == "electric":
                end = delay + (rec.full_minutes or 0.0)
            else:
                end = max(horizon, rec.upper_end_minutes or 0.0)
        # The grid, and always the projection's own end: a recovery that
        # finishes between two grid points must still be scored at its
        # finished state.
        steps = int(end // _GRID_MIN) + 1
        for t in [k * _GRID_MIN for k in range(steps)] + [end]:
            state = _mode_state(
                heats,
                t,
                tank,
                hp,
                setpoint,
                upper_min,
                ep,
                recovery,
                top,
                delay,
            )
            if state is None:
                break
            u, lo, wh, added = state
            if score(u, lo, added).gal >= bath_gal:
                row["ready_in_minutes"] = round(t, 1)
                row["ready_at"] = now + timedelta(minutes=t)
                row["energy_kwh"] = round(wh / 1000.0, 2)
                break
    return rows


# ── The answer, typed ───────────────────────────────────────────────


@dataclass(frozen=True)
class ModeReady:
    """Time to bath-ready in one heating mode."""

    #: ``heat_pump``, ``energy_saver``, ``high_demand`` or ``electric``.
    mode: HeaterMode
    #: Whether a write to it can take now: not while heating is disabled,
    #: nor, for an element mode, inside a TOU window.
    reachable_now: bool
    #: Minutes from now, and the instant; None when the mode does not get
    #: there (``reasons``, and the answer's).
    ready_in_minutes: float | None
    ready_at: datetime | None
    #: Electricity to get there, kWh.
    energy_kwh: float | None
    #: The element model's caveats, for an element mode.
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BathReady:
    """The bath: ready now, the margin, and the time to ready."""

    volume_gal: float
    ready: bool
    #: Deliverable gallons less the bath's.
    margin_gal: float
    #: The heat pump's (the mode the heater runs on its own).
    ready_in_minutes: float | None
    ready_at: datetime | None
    by_mode: tuple[ModeReady, ...]


@dataclass(frozen=True)
class ShowersReady:
    volume_gal: float
    #: Deliverable gallons over a shower's, two decimals.
    ready_for: float
    #: Whole showers: one the tank cannot finish is not counted.
    ready_for_whole: int


@dataclass(frozen=True)
class Readiness:
    """Hot water now and ahead (``sim.ready``)."""

    at: datetime
    upper_f: float
    lower_f: float
    #: Deliverable gallons now, at the delivered line.
    deliverable_gal: float
    bath: BathReady
    showers: ShowersReady
    #: What the numbers rest on (the module's and ``sim.delivery``'s).
    reasons: tuple[str, ...]
    #: Each default the answer used, as ``name=value``.
    defaults_used: tuple[str, ...]
    #: The recovery the heater runs next, as scored.
    recovery: Recovery


#: The reasons a typed answer leaves out: standing ones (``ALWAYS``),
#: and the volumes' sources, which ``defaults_used`` names.
_LEFT_OUT = frozenset(
    {*ALWAYS, "bath_volume_inferred", "shower_volume_default"}
)


def typed(
    answer: dict[str, Any],
    at: datetime,
    recovery: Recovery,
    defaults_used: Sequence[str] = (),
) -> Readiness:
    """``assess``'s mapping as a ``Readiness``."""
    bath = answer["bath"]
    showers = answer["showers"]
    return Readiness(
        at=at,
        upper_f=answer["tank_upper_f"],
        lower_f=answer["tank_lower_f"],
        deliverable_gal=answer["deliverable_gal"],
        bath=BathReady(
            volume_gal=bath["volume_gal"],
            ready=bath["ready"],
            margin_gal=bath["margin_gal"],
            ready_in_minutes=bath["ready_in_minutes"],
            ready_at=bath["ready_at"],
            by_mode=tuple(
                ModeReady(
                    mode=row["mode"],
                    reachable_now=row["reachable_now"],
                    ready_in_minutes=row["ready_in_minutes"],
                    ready_at=row["ready_at"],
                    energy_kwh=row["energy_kwh"],
                    reasons=tuple(row["reasons"]),
                )
                for row in bath["by_mode"]
            ),
        ),
        showers=ShowersReady(
            volume_gal=showers["volume_gal"],
            ready_for=showers["ready_for"],
            ready_for_whole=showers["ready_for_whole"],
        ),
        reasons=tuple(r for r in answer["reasons"] if r not in _LEFT_OUT),
        defaults_used=tuple(defaults_used),
        recovery=recovery,
    )
