"""Time to ready: when the tank can run a bath, and how many showers it
is ready for, by heating mode (``sim.ready``).

``sim.delivery`` knows how many gallons the tank's layers deliver. This
turns that into the answer: the bath and shower answers, the time to
bath-ready in each mode, and the reasons that say what the numbers rest
on. Each mode's time is the simulator's own walk in that mode from now
(``api.time_to_ready``, ``ModeRun``): the first instant its layers
deliver the bath, and the electricity to then.

The recovery it reports (``Recovery``) is the heat-pump recovery the
heater runs next: from now if the compressor runs, else from the
heater's own trigger on the coast to it, with the TOU cap judged where
it ends. Its outcome says why a bath is not reached.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal

from nwp500.sim.delivery import Deliverable
from nwp500.sim.params import ReadinessParams
from nwp500.sim.physics.element import HeaterMode

#: Present on every answer while the model and the line are provisional:
#: the deliverable volume rests on the layered tank's draws, checked on
#: few drawdowns, and the line is a choice.
ALWAYS: tuple[str, ...] = (
    "readiness_model_provisional",
    "depletion_threshold_provisional",
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
    ``outcome`` is ``ok``, or, with ``hp_unavailable``, the tank at the
    heater's own start alone. ``input_wh`` is the heat pump's electrical
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
    instants, but ``start_minute`` runs from the instant it was
    computed: reused unchanged, the start comes ``now - then`` minutes
    late."""
    elapsed = (now - then).total_seconds() / 60.0
    if rec.outcome != "ok" or elapsed <= 0.0 or rec.start_minute <= 0.0:
        return rec
    return replace(rec, start_minute=max(0.0, rec.start_minute - elapsed))


#: The modes time to ready is reported for (``BathReady.by_mode``), in
#: this order.
MODES: tuple[HeaterMode, ...] = (
    "heat_pump",
    "energy_saver",
    "high_demand",
    "electric",
)

ELEMENT_MODES: tuple[HeaterMode, ...] = MODES[1:]


def showers_ready_for(deliverable_gal: float, shower_gal: float) -> float:
    """Showers the tank is ready for, two decimals."""
    if shower_gal <= 0:
        raise ValueError("shower_gal must be positive")
    return round(deliverable_gal / shower_gal, 2)


def whole_showers(ready_for: float) -> int:
    """``floor``: a shower the tank cannot finish is not one it is ready
    for. The epsilon keeps 2.00 from flooring to 1 on a float that came
    back as 1.9999999."""
    # Mains at the line never runs the tap under it: no end to count to.
    return max(0, math.floor(min(ready_for, 1e9) + 1e-9))


@dataclass(frozen=True)
class ModeRun:
    """A mode's walk from now (``api.time_to_ready``): minutes until its
    layers deliver the bath and the electricity to then, kWh; None for
    both when it does not get there within the walk."""

    mode: HeaterMode
    ready_in_minutes: float | None
    energy_kwh: float | None
    reasons: tuple[str, ...] = ()


def assess(
    now: datetime,
    tank: TankNow,
    recovery: Recovery,
    now_gal: Deliverable,
    runs: Sequence[ModeRun],
    *,
    bath_gal: float,
    bath_source: Literal["configured", "request"],
    shower_gal: float,
    shower_source: Literal["weekly_forecast", "default", "request"],
    valid_s: float,
    within_resolution: bool = False,
    params: ReadinessParams | None = None,
) -> dict[str, Any]:
    """The readiness answer as a mapping (``time_to_ready`` types it):
    ``now_gal`` the deliverable gallons now, ``runs`` each mode's walk
    (``ModeRun``, by ``MODES``; none needed with the bath ready now),
    ``within_resolution`` whether a probe error would flip the bath's
    answer (``delivery.within_resolution``).

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
    ``tank_profile_estimated`` (the gallons from the two probes alone);
    ``bath_volume_inferred`` (``bath_source`` ``configured``);
    ``shower_volume_default``; ``bath_ready_within_probe_resolution``;
    ``draw_in_progress``; ``element_running``; ``tou_window_in_force``;
    and, the bath not ready, ``heating_not_scheduled``,
    ``time_to_ready_unavailable``, ``heating_not_triggered``,
    ``bath_waits_for_tou_window_end`` or
    ``bath_not_reached_by_full_recovery``."""
    p = params or ReadinessParams()
    bath_gal = round(bath_gal, 1)  # compared as it is reported
    reasons = list(ALWAYS)
    if now_gal.basis == "probes":
        reasons.append("tank_profile_estimated")
    if bath_source == "configured":
        reasons.append("bath_volume_inferred")
    if shower_source == "default":
        reasons.append("shower_volume_default")
    ready = now_gal.gal >= bath_gal
    if within_resolution:
        reasons.append("bath_ready_within_probe_resolution")
    if tank.drawing:
        reasons.append("draw_in_progress")
    if tank.element_on:
        reasons.append("element_running")
    if tank.tou_window:
        reasons.append("tou_window_in_force")

    not_heating = recovery.outcome == "not_scheduled"
    by_run = {r.mode: r for r in runs}
    by_mode: list[dict[str, Any]] = []
    for mode in MODES:
        # A mode write inside a TOU window may not take, and nothing is
        # entered while the appliance is not heating.
        reachable = not not_heating and (
            mode == "heat_pump" or not tank.tou_window
        )
        run = by_run.get(mode)
        minutes = 0.0 if ready else None
        energy = 0.0 if ready else None
        if not ready and not not_heating and run is not None:
            minutes, energy = run.ready_in_minutes, run.energy_kwh
        by_mode.append(
            {
                "mode": mode,
                "reachable_now": reachable,
                "ready_in_minutes": minutes,
                "ready_at": (
                    None
                    if minutes is None
                    else now + timedelta(minutes=minutes)
                ),
                "energy_kwh": energy,
                "reasons": [] if run is None or ready else list(run.reasons),
            }
        )
    ready_in = by_mode[0]["ready_in_minutes"]
    if not ready:
        if recovery.outcome == "not_scheduled":
            reasons.append("heating_not_scheduled")
        elif recovery.outcome == "unavailable" and not recovery.hp_unavailable:
            reasons.append("time_to_ready_unavailable")
        elif recovery.outcome == "idle" and ready_in is None:
            reasons.append("heating_not_triggered")
        elif ready_in is None:
            reasons.append(
                "bath_waits_for_tou_window_end"
                if recovery.tou_capped
                else "bath_not_reached_by_full_recovery"
            )

    ready_for = showers_ready_for(now_gal.gal, shower_gal)
    return {
        "generated_at": now,
        "valid_until": now + timedelta(seconds=valid_s),
        "status": "low_confidence" if reasons else "ok",
        "reasons": reasons,
        "line_f": p.line_f,
        "tank_upper_f": round(tank.upper_f, 2),
        "tank_lower_f": round(tank.lower_f, 2),
        "deliverable_gal": now_gal.gal,
        "bath": {
            "volume_gal": bath_gal,
            "volume_source": bath_source,
            "ready": ready,
            "margin_gal": round(now_gal.gal - bath_gal, 1),
            "ready_in_minutes": ready_in,
            "ready_at": by_mode[0]["ready_at"],
            "by_mode": by_mode,
        },
        "showers": {
            "volume_gal": round(shower_gal, 2),
            "volume_source": shower_source,
            "ready_for": ready_for,
            "ready_for_whole": whole_showers(ready_for),
        },
    }


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
