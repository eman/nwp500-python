"""The simulator's entry points: ``simulate``, ``recovery`` and
``standby``.

A scenario's parts become the engine's inputs here: the ambient as a
frame on a 10-minute grid, the TOU periods as windows and the
reservations as firings (``sim.schedules``), the modes as the engine
names them, and the parameters as the core's ``TankPhysics``. What
could not be modelled is named in the result's ``reasons``, and every
default used in its ``defaults_used``.
"""

import contextlib
import dataclasses
import itertools
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd

from nwp500.sim.circulation import RUN_GAP, Circulation
from nwp500.sim.controller import (
    ELEMENT_DONE_F,
    HEAT_PUMP_UNAVAILABLE,
    lower_trigger_f,
)
from nwp500.sim.decay import AmbientSampler, compute_start_time
from nwp500.sim.defaults import SITE_CIRCULATION
from nwp500.sim.delivery import (
    Deliverable,
    deliverable,
    delivery_along,
    draw_domain_judgement,
    draw_windows,
    within_resolution,
)
from nwp500.sim.engine import (
    HEATER_SETPOINT_MAX_F,
    HEATER_SETPOINT_MIN_F,
    RECOVERY_AHEAD,
    RESUME_DROPPED,
    Entry,
    Heater,
    HeatingInterval,
    PathPoint,
    RawWrite,
    Resume,
    Simulation,
    SimulationError,
    quantise,
)
from nwp500.sim.engine import simulate as walk
from nwp500.sim.extensions import RecoveryModel
from nwp500.sim.heating_trajectory import HeatingPoint
from nwp500.sim.inputs import (
    ELECTRIC,
    ENERGY_SAVER,
    HEAT_PUMP,
    HIGH_DEMAND,
    POWER_OFF,
    Draw,
    Environment,
    HeaterState,
    History,
    Loads,
    Scenario,
    Schedules,
    Settings,
    Write,
)
from nwp500.sim.params import HeaterParams
from nwp500.sim.physics.element import BASE_REASONS, HeaterMode
from nwp500.sim.physics.heat_pump import (
    HEAT_MAP_OUT_OF_DOMAIN,
    heat_air_outside,
    start_hold_min,
)
from nwp500.sim.ready import (
    MODES,
    ModeRun,
    Readiness,
    Recovery,
    TankNow,
    assess,
    typed,
)
from nwp500.sim.result import (
    ActiveCycle,
    ElementInterval,
    ElementModeResult,
    Forecast,
    RecoveryResult,
    SimulationResult,
    Trace,
)
from nwp500.sim.schedules import (
    half_c_to_f,
    reservation_firings,
    tou_windows,
)
from nwp500.sim.tank_physics import (
    RECOVERY_BOUND,
    Recovered,
    TankPhysics,
)
from nwp500.sim.tou_triggers import (
    LOWER_TRIGGER_HELD,
    heater_start,
    in_window,
    while_enabled,
)
from nwp500.sim.units import BTU_PER_WH, DEFAULT_AMBIENT_F

#: The engine's name for each mode it models.
ENGINE_MODE: Mapping[int, HeaterMode] = MappingProxyType(
    {
        HEAT_PUMP: "heat_pump",
        ELECTRIC: "electric",
        ENERGY_SAVER: "energy_saver",
        HIGH_DEMAND: "high_demand",
    }
)

#: The ambient grid's spacing, and how far it reaches either side of
#: the span (a recovery that starts near the end runs past it).
AMBIENT_STEP = "10min"
AMBIENT_BEFORE = timedelta(hours=1)
AMBIENT_AFTER = timedelta(hours=12)

#: How far ``recovery`` looks for a heating interval.
RECOVERY_HORIZON = timedelta(hours=24)

#: How far ahead ``time_to_ready`` looks for the heater's own trigger;
#: beyond it the heat pump's time is None (``heating_not_triggered``).
TRIGGER_HORIZON = timedelta(hours=24)
#: Room for a recovery after its start: past the integrator's 30 h bound.
_RECOVERY_ROOM = timedelta(hours=31)


def _air_readings(environment: Environment) -> pd.DataFrame | None:
    """The air readings given, as a frame; None for one value."""
    a = environment.ambient_f
    if not isinstance(a, tuple):
        return None
    return pd.DataFrame(
        {"ambient_f": [v for _, v in a]},
        index=pd.DatetimeIndex([t for t, _ in a]),
    )


def _ambient_frame(
    environment: Environment, start: datetime, until: datetime
) -> pd.DataFrame:
    """The ambient as the core reads it: a frame on a 10-minute grid
    from an hour before ``start`` to 12 hours past ``until``, the
    readings interpolated onto it and held past their ends."""
    t0 = pd.Timestamp(start - AMBIENT_BEFORE).floor(AMBIENT_STEP)
    stamps = pd.date_range(t0, until + AMBIENT_AFTER, freq=AMBIENT_STEP)
    readings = _air_readings(environment)
    if readings is not None:
        sampler = AmbientSampler(readings)
        values = [sampler.at(t.to_pydatetime()) for t in stamps]
    else:
        a = environment.ambient_f
        assert not isinstance(a, tuple)
        values = [float(a) if math.isfinite(a) else DEFAULT_AMBIENT_F] * len(
            stamps
        )
    return pd.DataFrame({"ambient_f": values}, index=stamps)


#: No usable air reading was given: the answer ran at the default air.
AMBIENT_DEFAULTED = "ambient_defaulted"
#: The air is the heater's idle cabinet reading, about 6 °F warm
#: (``Environment.ambient_cabinet``).
AMBIENT_FROM_CABINET = "ambient_from_idle_cabinet"


def _ambient_reasons(environment: Environment) -> list[str]:
    """``ambient_defaulted`` when the air the answer ran at is the
    default, not a reading (``Environment.ambient_defaulted``), and
    ``ambient_from_idle_cabinet`` when it is the heater's idle cabinet
    reading (``Environment.ambient_cabinet``)."""
    if environment.ambient_defaulted:
        return [AMBIENT_DEFAULTED]
    return [AMBIENT_FROM_CABINET] if environment.ambient_cabinet else []


def _circulation(loads: Loads, params: HeaterParams) -> Circulation | None:
    """The scenario's circulation as the core's, or None: its runs
    merged once, over the whole input, at the circulation's own gap
    (``CirculationParams.run_gap_min``), so the tank sees the same runs
    wherever a walk is cut."""
    if loads.circulation is None:
        return None
    gap = (
        RUN_GAP
        if params.circulation is None
        else timedelta(minutes=params.circulation.run_gap_min)
    )
    return Circulation(
        tuple((r.start, r.end) for r in loads.circulation),
        loads.circulation_known_until,
        gap,
    )


#: The installation has circulation, and its runs are not known over
#: the span (none given, or not past ``Loads.circulation_known_until``):
#: nothing is charged there, which is not the same as none ran.
CIRCULATION_UNKNOWN = "circulation_unknown"


def _circulation_unknown(
    params: HeaterParams, loads: Loads, until: datetime
) -> bool:
    # Runs given to params without terms are an installation that
    # circulates, priced at the example terms (``_physics``).
    if params.circulation is None and loads.circulation is None:
        return False
    return loads.circulation is None or (
        loads.circulation_known_until is not None
        and loads.circulation_known_until < until
    )


#: A served recovery less confident than this says
#: ``recovery_low_confidence``: only a ``RecoveryModel``'s can be, the
#: physics alone answering with full confidence.
LOW_CONFIDENCE_FLOOR = 0.6
#: ``Settings.hp_lower_on_f`` was not known: the heater's lower-zone
#: start was never searched (the TOU-opening start still was), so an
#: answer may miss a start the heater makes.
HP_LOWER_ON_UNKNOWN = "hp_lower_on_unknown"
#: The tank's layers were made of its two probes, not walked from its
#: history (``TankPhysics.estimate``).
TANK_PROFILE_ESTIMATED = "tank_profile_estimated"


def _mains(
    environment: Environment, params: HeaterParams, at: datetime
) -> float:
    """The mains at ``at``: the environment's own
    (``Environment.inlet_f``), else the parameters' on that day
    (``DrawParams.mains_on``)."""
    if environment.inlet_f is not None:
        return environment.inlet_f
    return params.draw.mains_on(at.date())


def _inlet_f(
    s: Scenario, params: HeaterParams, at: datetime | None = None
) -> float:
    """The scenario's mains at ``at``, its start by default
    (``_mains``): a draw meets its own day's."""
    return _mains(s.environment, params, s.start if at is None else at)


def _physics(
    params: HeaterParams,
    environment: Environment,
    start: datetime,
    until: datetime,
    *,
    draws_on: bool,
    model: RecoveryModel | None,
    defaults: list[str],
    circulation: Circulation | None = None,
) -> TankPhysics:
    """The physics over ``start`` to ``until``: each draw meets the
    environment's inlet, else the parameters' mains on its own day."""
    if "humidity" not in environment.model_fields_set:
        defaults.append(f"humidity={environment.humidity}")
    inlet_f = _mains(environment, params, start)
    if environment.inlet_f is None:
        defaults.append(
            f"inlet_f={inlet_f:.1f}"
            + (" (the climate's mains)" if params.draw.climate_f else "")
        )
    if (
        circulation is not None
        and (params.circulation or SITE_CIRCULATION) == SITE_CIRCULATION
    ):
        # Without terms of its own, the runs take one installation's.
        defaults.append("circulation=one installation's (CirculationParams)")
    return TankPhysics(
        params,
        _ambient_frame(environment, start, until),
        environment.humidity,
        draws_on=draws_on,
        circulation=circulation,
        circulation_terms=SITE_CIRCULATION,
        draw_inlet_temp_f=inlet_f,
        draw_inlet_on=None
        if environment.inlet_f is not None
        else params.draw.mains_on,
        recovery_model=model,
        low_confidence_floor=LOW_CONFIDENCE_FLOOR,
        # Where the air leaves the heat pump's range, on the readings
        # themselves, not the grid.
        air_readings=_air_readings(environment),
    )


def _tank(physics: TankPhysics, state: HeaterState) -> tuple[Any, list[str]]:
    """The tank at the start: its layers as given, or the physics' of
    the probes, which says ``tank_profile_estimated``."""
    if state.layers_f is not None:
        return physics.layers(state.layers_f), []
    return physics.estimate(state.upper_f, state.lower_f), [
        TANK_PROFILE_ESTIMATED
    ]


def _engine_mode(mode: int) -> tuple[HeaterMode, bool]:
    """The engine's mode for a device mode, and whether heating is
    disabled (Vacation, Power Off)."""
    named = ENGINE_MODE.get(mode)
    return (named, False) if named is not None else ("heat_pump", True)


def _history_defaults(
    state: HeaterState, history: History, defaults: list[str]
) -> None:
    if history.compressor_stopped_at is None and not state.compressor_running:
        defaults.append(
            "compressor_stopped_at=None (no lockout at the start, and the "
            "longest start hold)"
        )
    if state.element_running and state.element_running_since is None:
        defaults.append("element_running_since=None")


def _entries(
    scenario: Scenario, tz: ZoneInfo, reasons: list[str]
) -> list[Entry]:
    """The reservations' firings over the span, as the engine's
    entries: the commands' schedule if they write one, else the
    heater's."""
    written = scenario.commands.reservations
    if written is not None:
        schedule = written
    elif scenario.schedules.reservations_enabled:
        schedule = scenario.schedules.reservations
    else:
        schedule = ()
    out: list[Entry] = []
    for f in reservation_firings(schedule, tz, scenario.start, scenario.until):
        mode = ENGINE_MODE.get(f.entry.mode)
        if mode is None:
            reasons.append("reservation_mode_not_modelled")
            continue
        out.append(
            Entry(
                f.at,
                mode,
                half_c_to_f(f.entry.setpoint_half_c),
                scenario.start,
                f"reservation-{f.index}",
            )
        )
    return out


def _check_setpoint(what: str, f: float) -> None:
    """Refuse a setpoint outside the range the simulation can run
    (``HEATER_SETPOINT_MIN_F`` to ``_MAX_F``)."""
    if not HEATER_SETPOINT_MIN_F - 1e-6 <= f <= HEATER_SETPOINT_MAX_F + 1e-6:
        raise ValueError(
            f"{what}: setpoint {f:.1f} °F is outside the range the "
            f"simulation runs, {HEATER_SETPOINT_MIN_F}-"
            f"{HEATER_SETPOINT_MAX_F} °F"
        )


def _check_setpoints(scenario: Scenario) -> None:
    """Refuse a write or a written reservation whose setpoint is outside
    the range the simulation can run (``_check_setpoint``); the device's
    own limits are its feature's."""
    asked = [
        (f"write at {w.at.isoformat()}", w.setpoint_f)
        for w in scenario.commands.writes
        if w.setpoint_f is not None
    ]
    asked += [
        (f"reservation {i}", half_c_to_f(e.setpoint_half_c))
        for i, e in enumerate(scenario.commands.reservations or ())
    ]
    for what, f in asked:
        _check_setpoint(what, f)


def _raw_writes(scenario: Scenario, reasons: list[str]) -> list[RawWrite]:
    """The commands' writes as the engine takes them: each setpoint as
    the device will hold it (``engine.quantise``, half degrees Celsius),
    and a write into Vacation or Power Off dropped whole, setpoint and
    all, since the simulation holds no rule for what it does."""
    out: list[RawWrite] = []
    for w in scenario.commands.writes:
        mode: HeaterMode | None = None
        if w.mode is not None:
            mode = ENGINE_MODE.get(w.mode)
            if mode is None:
                reasons.append("write_mode_not_modelled")
                continue
        setpoint = None if w.setpoint_f is None else quantise(w.setpoint_f)
        out.append(RawWrite(w.at, setpoint_f=setpoint, mode=mode, id=w.id))
    return out


def simulate(
    scenario: Scenario,
    params: HeaterParams,
    *,
    recovery: RecoveryModel | None = None,
    tou_windows_in_force: Sequence[tuple[datetime, datetime]] | None = None,
    withheld_windows: Sequence[tuple[datetime, datetime]] = (),
    inlet_measured: bool = False,
    start_hold: Callable[[float | None], float] | None = None,
    running_hold: float = 0.0,
    running_starts: bool = False,
) -> SimulationResult:
    """Walk ``scenario`` from its start to its end on ``params``.

    The tank starts from its layers (``HeaterState.layers_f``), or as
    the physics makes it of the probes (``TankPhysics.estimate``;
    ``tank_profile_estimated``). The delivery and the draw windows read
    the layers along the path (``sim.delivery``).

    ``recovery`` paces each heat-pump recovery by its own duration
    (``extensions.RecoveryModel``, served as a scale on the heat pump's
    heat, ``heat_pump_recovery.rate_scale``). The two inputs after it
    are what such a model was trained with:

    - ``start_hold``: how long a compressor start holds before it
      heats, minutes, by the minutes since the compressor last stopped
      (None when not known); None, the parameters' own
      (``physics.heat_pump.start_hold_min``);
    - ``running_hold``: what is left at the start of a running
      compressor's own start's hold, minutes; ignored when it is not
      running.

    A running compressor's heating has begun, its start's stir behind
    it, unless some of ``running_hold`` is left or ``running_starts``:
    it starts at the scenario's start (a recorded start replayed, as
    ``sim_score`` does), its heating beginning after ``running_hold``.

    ``inlet_measured``: the scenario's inlet (``Environment.inlet_f``) is
    the mains as measured (``cold_supply``); without it, a scenario with
    draws says ``inlet_temp_modelled``.

    ``withheld_windows`` are spans over which a recovery is credited no
    heat, as the worst case of a draw window's long draws coming first
    (``draw_forecast.draws_first``): the engine runs a recovery out
    uncredited over them.

    ``tou_windows_in_force`` are the TOU windows the heater keeps, in
    place of the schedule's (``marked_windows``: the heater's own marker
    over a recovery running now). With TOU on and no periods to lay out,
    ``reasons`` says ``tou_schedule_unknown`` and no window is kept.

    Raises ``engine.SimulationError`` when the walk cannot be completed.
    """
    s = scenario
    _check_setpoints(s)
    resume = (
        None
        if s.state.resume is None
        else Resume.from_document(json.loads(s.state.resume))
    )
    reasons: list[str] = []
    mode, disabled = _engine_mode(s.settings.mode)
    if resume is not None:
        resume.check_from(s.start)
    if resume is not None and not resume.carries(
        heating_disabled=disabled, powered_off=s.settings.mode == POWER_OFF
    ):
        # Starts afresh from the tank and the history, as the engine
        # would.
        resume = None
        reasons.append(RESUME_DROPPED)
    setpoint_f = s.settings.setpoint_f
    if resume is not None and setpoint_f != resume.controller.setpoint_f:
        # Moved since the walk ended: written at the start, as an app
        # writes one.
        _check_setpoint(f"settings at {s.start.isoformat()}", setpoint_f)
        setpoint_f = quantise(setpoint_f)
    tz = ZoneInfo(s.tz)
    defaults: list[str] = []
    if s.loads.draws and not inlet_measured:
        # Each draw's cold water is priced at an inlet nobody measured
        # at the mains (``cold_supply``).
        reasons.append("inlet_temp_modelled")
    circulation = _circulation(s.loads, params)
    if _circulation_unknown(params, s.loads, s.until):
        reasons.append(CIRCULATION_UNKNOWN)
    physics = _physics(
        params,
        s.environment,
        s.start,
        s.until,
        draws_on=bool(s.loads.draws),
        model=recovery,
        defaults=defaults,
        circulation=circulation,
    )
    tou_on = (
        s.commands.tou_enabled
        if s.commands.tou_enabled is not None
        else s.schedules.tou_enabled
    )
    switches = s.schedules.tou_switches
    # To as far past the end as a recovery judges its cap, so one
    # running at the end is judged as in a walk going on past it.
    windows: tuple[tuple[datetime, datetime], ...] = (
        tuple(
            while_enabled(
                tou_windows(
                    s.schedules.tou_periods,
                    tz,
                    s.start,
                    s.until + RECOVERY_AHEAD,
                ),
                tou_on,
                switches,
            )
        )
        if tou_on or any(on for _, on in switches)
        else ()
    )
    if tou_windows_in_force is not None:
        windows = tuple(tou_windows_in_force)
    elif (tou_on or any(on for _, on in switches)) and not (
        s.schedules.tou_periods
    ):
        reasons.append("tou_schedule_unknown")
    if s.settings.hp_lower_on_f is None:
        defaults.append("hp_lower_on_f=None (no lower-zone start)")
        # The lower trigger was never searched; the TOU-opening one was.
        reasons.append(HP_LOWER_ON_UNKNOWN)
    if resume is None:
        _history_defaults(s.state, s.history, defaults)
    entries = _entries(s, tz, reasons)
    raw = _raw_writes(s, reasons)
    draws = [(d.at, d.gallons) for d in s.loads.draws]
    tank, estimated = _tank(physics, s.state)
    reasons += estimated
    sim = walk(
        # Made of the probes, the engine makes it, and keeps them as read.
        state=None if estimated else tank,
        start=s.start,
        upper_f=s.state.upper_f,
        lower_f=s.state.lower_f,
        running=s.state.compressor_running,
        until=s.until,
        setpoint_f=setpoint_f,
        heater=Heater(
            hp_lower_on_f=s.settings.hp_lower_on_f,
            tou_windows=windows,
            heating_disabled=disabled,
            powered_off=s.settings.mode == POWER_OFF,
            mode=mode,
            element=params.element,
        ),
        physics=physics,
        entries=entries,
        draws=draws,
        # A window's edges, so its onset and its end are read exactly
        # rather than across the coast's 10-minute grid.
        marks=[at for w in s.loads.windows for at in (w.start, w.end)],
        element_running=s.state.element_running,
        element_running_since=s.state.element_running_since,
        raw_writes=raw,
        stopped_at=s.history.compressor_stopped_at,
        controller=params.controller,
        withheld_windows=sorted(withheld_windows),
        start_hold=(
            start_hold
            if start_hold is not None
            else lambda off: start_hold_min(params.compressor, off)
        ),
        running_hold=running_hold,
        running_starts=running_starts,
        resume=resume,
    )
    delivery = delivery_along(sim.points, params)
    out_of_domain_at: datetime | None = None
    if draws:
        any_out, out_of_domain_at = draw_domain_judgement(
            params.draw,
            [(p.at, p.upper_f) for p in sim.points],
            _largest_draw(s.loads.draws),
        )
        if any_out:
            reasons.append("draw_out_of_domain")
    reasons += _unfitted(params, "tank")
    if s.loads.draws:
        reasons += _unfitted(params, "draw")
    if any(h.source == "compressor" for h in sim.heating):
        reasons += _unfitted(params, "compressor", "power")
    reasons += _ambient_reasons(s.environment)
    return SimulationResult(
        start=s.start,
        until=s.until,
        simulation=sim,
        reasons=(*_unique(reasons), *_unique(sim.reasons)),
        defaults_used=tuple(defaults),
        delivery=tuple(delivery),
        windows=tuple(
            draw_windows(
                sim,
                [(w.start, w.end, w.expected_gal) for w in s.loads.windows],
                delivery,
                params,
                inlet_on=lambda at: _inlet_f(s, params, at),
                forecast=[
                    (w.expected_count, w.draws_until) for w in s.loads.windows
                ],
            )
        ),
        draw_out_of_domain_at=out_of_domain_at,
        **_end(s, sim),
    )


#: The device's mode for each of the engine's.
_DEVICE_MODE: Mapping[HeaterMode, int] = MappingProxyType(
    {named: mode for mode, named in ENGINE_MODE.items()}
)


def _end(s: Scenario, sim: Simulation) -> dict[str, Any]:
    """The heater where ``sim`` ended, as the state, the history and the
    settings of a scenario from there (``SimulationResult.end_state``)."""
    r = sim.resume
    assert r is not None
    last = sim.points[-1]
    el = r.element
    commanded = r.controller.mode.commanded
    # The mode in force at the start unless a write moved it: Vacation
    # and Power Off are the engine's Heat Pump, with heating disabled,
    # and an entry that turns the heater on leaves Power Off.
    powered_on = s.settings.mode == POWER_OFF and r.controller.powered_on
    mode = (
        s.settings.mode
        if commanded == _engine_mode(s.settings.mode)[0] and not powered_on
        else _DEVICE_MODE[commanded]
    )
    if powered_on:
        # Out of Power Off as the settings say: Power Off given again is
        # the heater turned off, not the entry's turning on.
        r = dataclasses.replace(
            r, controller=dataclasses.replace(r.controller, powered_on=False)
        )
    return {
        "end_state": HeaterState(
            upper_f=last.upper_f,
            lower_f=last.lower_f,
            layers_f=last.layers_f,
            compressor_running=r.cycle is not None,
            element_running=el is not None,
            element_running_since=None if el is None else el.on_at,
            resume=json.dumps(r.to_document(), sort_keys=True),
        ),
        "end_history": History(
            compressor_stopped_at=r.controller.compressor.last_stop
        ),
        "end_settings": s.settings.model_copy(
            update={"setpoint_f": r.controller.setpoint_f, "mode": mode}
        ),
    }


def readiness(
    state: HeaterState,
    settings: Settings,
    params: HeaterParams,
    *,
    inlet_f: float | None = None,
    on: date | None = None,
) -> Deliverable:
    """How much hot water the tank can deliver now, in delivered gallons
    at the line (``ReadinessParams.line_f``), and what the answer rests
    on (``sim.delivery``): the tank's layers (``HeaterState.layers_f``,
    ``basis`` ``layers``), else the profile its two probes stand for
    (``probes``). The mains is ``inlet_f``, else the parameters' on the
    day ``on`` (``DrawParams.mains_on``), else
    ``DrawParams.inlet_temp_f``."""
    if inlet_f is None and on is not None:
        inlet_f = params.draw.mains_on(on)
    return deliverable(
        params, state.upper_f, state.lower_f, state.layers_f, inlet_f=inlet_f
    )


#: The reason each unfitted term group (``HeaterParams.unfitted``) adds
#: to an answer it reaches: a failed fit never reads as a fitted one.
UNFITTED_REASONS: Mapping[str, str] = MappingProxyType(
    {
        "compressor": "physics_uncalibrated",
        "power": "energy_uncalibrated",
        "tank": "tank_uncalibrated",
        "draw": "draw_uncalibrated",
    }
)


def _out_of_range(
    params: HeaterParams, airs: Sequence[float], lower_f: float
) -> bool:
    """Whether the heat pump is outside its operating range at any of
    ``airs`` with the lower zone at ``lower_f``
    (``ControllerParams.hp_air_range_f``, ``hp_water_range_f``)."""
    a_lo, a_hi = params.controller.hp_air_range_f
    w_lo, w_hi = params.controller.hp_water_range_f
    return any(not a_lo <= a < a_hi for a in airs) or not (
        w_lo <= lower_f < w_hi
    )


def _range_reasons(
    params: HeaterParams,
    airs: Sequence[float],
    lower_f: float,
    stop_f: float,
) -> list[str]:
    """What a heat-pump answer at ``airs`` and ``lower_f`` says of the
    heat pump's range: ``heat_pump_unavailable`` outside its operating
    range, where the heater heats with its elements and no heat-pump
    recovery runs, or with the recovery's stop (``stop_f``, its target
    and run-on) over its top, which the elements finish;
    ``heat_map_out_of_domain`` with the air outside the span its heat
    was fitted on."""
    out: list[str] = []
    if (
        _out_of_range(params, airs, lower_f)
        or stop_f > params.controller.hp_water_range_f[1]
    ):
        out.append(HEAT_PUMP_UNAVAILABLE)
    if any(heat_air_outside(params.compressor, a) for a in airs):
        out.append(HEAT_MAP_OUT_OF_DOMAIN)
    return out


def _unfitted(params: HeaterParams, *terms: str) -> list[str]:
    """The reasons for those of ``terms`` the parameters did not fit."""
    return [UNFITTED_REASONS[t] for t in params.unfitted if t in terms]


def _on_clock(
    trajectory: tuple[HeatingPoint, ...], ready_at: datetime
) -> tuple[HeatingPoint, ...]:
    """``trajectory``'s instants stretched from its start so it ends at
    ``ready_at``."""
    start, end = trajectory[0].at, trajectory[-1].at
    if end <= start or end == ready_at:
        return trajectory
    f = (ready_at - start) / (end - start)
    return tuple(replace(p, at=start + (p.at - start) * f) for p in trajectory)


def _refusal(served: Recovered) -> SimulationError:
    """Why a recovery could not be served: the heat pump short of the
    target after ``RECOVERY_BOUND`` (a weak fit, or very cold air)."""
    hours = RECOVERY_BOUND.total_seconds() / 3600.0
    return SimulationError(
        "the recovery could not be computed: the heat pump falls short "
        f"of the target after {hours:.0f} h"
    )


def _largest_draw(draws: Sequence[Draw]) -> float:
    """The largest draw a domain is judged against: each one's own
    per-draw volume where it is an expected draw, else its gallons."""
    return max(
        d.per_draw_gal if d.per_draw_gal is not None else d.gallons
        for d in draws
    )


def _unique(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))


def recovery(
    state: HeaterState,
    settings: Settings,
    environment: Environment,
    params: HeaterParams,
    *,
    at: datetime,
    model: RecoveryModel | None = None,
    history: History | None = None,
    schedules: Schedules | None = None,
    tz: str = "UTC",
    horizon: timedelta = RECOVERY_HORIZON,
) -> RecoveryResult:
    """The first heating interval from ``at``: the one running now, or
    the next the heater starts within ``horizon``, with no draws.

    ``schedules`` brings the TOU windows (which hold and cap a
    recovery) and the reservations into it, their local times in
    ``tz``.
    """
    kw: dict[str, Any] = {}
    if history is not None:
        kw["history"] = history
    if schedules is not None:
        kw["schedules"] = schedules
    result = simulate(
        Scenario(
            start=at,
            horizon=horizon,
            tz=tz,
            state=state,
            settings=settings,
            environment=environment,
            **kw,
        ),
        params,
        recovery=model,
    )
    first = result.heating[0] if result.heating else None
    reasons = list(result.reasons)
    if first is None:
        # Heating disabled (Vacation, Power Off) is why, when it is.
        _, disabled = _engine_mode(settings.mode)
        reasons.append(
            "not_scheduled" if disabled else "no_recovery_within_horizon"
        )
        path = tuple(result.points)
    else:
        path = tuple(p for p in result.points if p.at <= first.end)
    return RecoveryResult(
        at=at,
        interval=first,
        path=path,
        reasons=tuple(_unique([*reasons, *_ambient_reasons(environment)])),
        defaults_used=result.defaults_used,
    )


def standby(
    state: HeaterState,
    environment: Environment,
    loads: Loads,
    params: HeaterParams,
    *,
    start: datetime,
    until: datetime,
    history: History | None = None,
    settings: Settings | None = None,
    schedules: Schedules | None = None,
    tz: str = "UTC",
) -> Trace:
    """The tank coasting from ``start`` to ``until`` with no heating:
    jacket loss and the draws in ``loads``.

    With ``settings``, also when the heater would start itself on that
    coast (``tou_triggers.heater_start``: the lower zone reaching
    ``hp_lower_on``, or the upper zone far short at a TOU window's
    opening, with the lower trigger held as the heater holds it), and
    how far above ``hp_lower_on`` the coast leaves the lower zone.
    ``schedules`` brings the TOU windows, their local times in ``tz``.
    """
    start, until = _instant(start), _instant(until)
    if until <= start:
        raise ValueError("until must be after start")
    defaults: list[str] = []
    circulation = _circulation(loads, params)
    physics = _physics(
        params,
        environment,
        start,
        until,
        draws_on=bool(loads.draws),
        model=None,
        defaults=defaults,
        circulation=circulation,
    )
    draws = [(d.at, d.gallons) for d in loads.draws if start <= d.at < until]
    first, reasons = _tank(physics, state)
    coast = physics.advance(start, first, until, draws)
    out_of_domain_at: datetime | None = None
    if draws:
        any_out, out_of_domain_at = draw_domain_judgement(
            params.draw,
            [(start, state.upper_f)]
            + [(p.at, p.upper_f) for p in coast.points],
            _largest_draw([d for d in loads.draws if start <= d.at < until]),
        )
        if any_out:
            reasons.append("draw_out_of_domain")
    starts_at = trigger = None
    held = False
    margin: float | None = None
    if settings is not None:
        mode, disabled = _engine_mode(settings.mode)
        if settings.hp_lower_on_f is None:
            reasons.append(HP_LOWER_ON_UNKNOWN)
        # Where the simulation reads it: Electric's elements answer it no
        # nearer the setpoint than their restart.
        on = lower_trigger_f(
            settings.hp_lower_on_f,
            settings.setpoint_f,
            params.element,
            elements=mode == ENGINE_MODE[ELECTRIC],
        )
        last = coast.points[-1]
        margin = None if math.isinf(on) else last.lower_f - on
        windows = (
            while_enabled(
                tou_windows(schedules.tou_periods, ZoneInfo(tz), start, until),
                schedules.tou_enabled,
                schedules.tou_switches,
            )
            if schedules is not None
            and (
                schedules.tou_enabled
                or any(on for _, on in schedules.tou_switches)
            )
            else ()
        )
        if not disabled:
            starts_at, trigger, held = heater_start(
                [(p.at, p.upper_f, p.lower_f) for p in coast.points],
                # None: no lower trigger, the TOU-opening one still.
                on,
                coast.impulses,
                windows=windows,
                setpoint_f=settings.setpoint_f,
                mode=mode,
            )
            if held:
                reasons.append(LOWER_TRIGGER_HELD)
        if schedules is None or (
            schedules.tou_enabled and not schedules.tou_periods
        ):
            # A TOU opening could start it, or hold its lower trigger,
            # and no window was laid out to judge either.
            reasons.append("tou_schedule_unknown")
    reasons += _unfitted(params, "tank")
    if any(start <= d.at < until for d in loads.draws):
        reasons += _unfitted(params, "draw")
    if _circulation_unknown(params, loads, until):
        reasons.append(CIRCULATION_UNKNOWN)
    runs = None if circulation is None else circulation.over(start, until)
    return Trace(
        points=tuple(coast.points),
        defaults_used=tuple(defaults),
        starts_at=starts_at,
        trigger=trigger,
        start_held=held,
        lower_margin_f=margin,
        reasons=tuple(_unique([*reasons, *_ambient_reasons(environment)])),
        draw_out_of_domain_at=out_of_domain_at,
        draw_volume_gal=coast.draw_volume_gal if draws else None,
        draw_heat_wh=coast.draw_heat_btu / BTU_PER_WH if draws else None,
        circulation_minutes=(
            None
            if circulation is None
            else sum(
                (min(b, until) - max(a, start)).total_seconds() / 60.0
                for a, b in runs or ()
            )
        ),
        circulation_heat_wh=(
            None if circulation is None else coast.flowing_heat_btu / BTU_PER_WH
        ),
        ambient_mean_f=coast.ambient_mean_f,
        hours=(until - start).total_seconds() / 3600.0,
    )


#: Most slots one ``element_mode`` profile may carry: a slot narrower
#: than the walk's own minute over a day's stint is a list nobody reads.
MAX_PROFILE_SLOTS = 2000


def _stint_end(
    simulation: Simulation, start: datetime, opens: timedelta
) -> tuple[datetime, datetime | None] | None:
    """When the recovery a mode write at ``start`` sets off ends: the
    heating that begins within ``opens`` of it (the write's lag and the
    compressor's lockout), and all that begins before that has ended (an
    element handing over, the heat pump alongside); and the first instant
    after ``start`` a run in it stopped short of its target (``_cut``).
    ``start`` when none begins; None when it is still heating at the
    walk's end."""
    end: datetime = start
    cut: datetime | None = None
    for h in sorted(simulation.heating, key=lambda h: h.start.at):
        if h.start.at > max(end, start + opens):
            break
        if h.stop == "horizon":
            return None
        end = max(end, h.end)
        if (
            h.end > start
            and _cut(simulation, h)
            and (cut is None or h.end < cut)
        ):
            cut = h.end
    return end, cut


def _cut(simulation: Simulation, h: HeatingInterval) -> bool:
    """Whether ``h`` stopped short of its target: on the mode changing
    then (a write, or the heater dropping it at a window), not on the
    heat pump taking over from an element standing in for it (``stop``
    "heat_pump"); or, the compressor, on a setpoint write with the lower
    zone short of the new setpoint (the engine's own ``reached``). An
    element stops on a setpoint write only at its new off point."""
    if h.stop == "mode":
        return any(
            m.end == h.end and m.ended_by != "horizon" for m in simulation.modes
        ) or any(at == h.end for at, _ in simulation.drops)
    if h.stop == "write" and h.source == "compressor":
        return not any(at == h.end for at, _ in simulation.reached)
    return False


def _first_reach(
    points: Sequence[PathPoint],
    start: datetime,
    level: float,
    zone: Callable[[PathPoint], float],
) -> datetime | None:
    """The first instant the path's ``zone`` reaches ``level``, between
    its points; None when it does not."""
    prev: PathPoint | None = None
    for p in points:
        v = zone(p)
        if v >= level:
            if prev is None or zone(prev) >= level or p.at <= prev.at:
                return max(p.at, start)
            share = (level - zone(prev)) / (v - zone(prev))
            return prev.at + (p.at - prev.at) * share
        prev = p
    return None


def _profile(
    points: Sequence[PathPoint], start: datetime, slot_minutes: float
) -> tuple[ElementInterval, ...]:
    """The path's electricity in ``slot_minutes`` slots from ``start``:
    each point's, over the interval ending at it, shared out by time."""
    span = (points[-1].at - start).total_seconds() / 60.0 if points else 0.0
    if span / slot_minutes > MAX_PROFILE_SLOTS:
        raise ValueError(
            f"a {span:.0f}-minute stint in {slot_minutes}-minute slots is "
            f"{span / slot_minutes:.0f} intervals, over the "
            f"{MAX_PROFILE_SLOTS} cap; widen slot_minutes"
        )
    n = max(1, math.ceil(span / slot_minutes - 1e-9)) if span > 0 else 0
    element = [0.0] * n
    heat_pump = [0.0] * n
    for p0, p1 in itertools.pairwise(points):
        a = (p0.at - start).total_seconds() / 60.0
        b = (p1.at - start).total_seconds() / 60.0
        if b <= a:
            continue
        last = min(n, math.ceil(b / slot_minutes))
        for i in range(int(a // slot_minutes), last):
            lo, hi = i * slot_minutes, (i + 1) * slot_minutes
            share = max(0.0, min(b, hi) - max(a, lo)) / (b - a)
            element[i] += p1.element_wh * share
            heat_pump[i] += (p1.input_wh or 0.0) * share
    return tuple(
        ElementInterval(
            end_minute=round(min(span, (i + 1) * slot_minutes), 3),
            element_wh=round(element[i], 2),
            heat_pump_wh=round(heat_pump[i], 2),
        )
        for i in range(n)
    )


def element_mode(
    scenario: Scenario,
    params: HeaterParams,
    *,
    mode: int,
    setpoint_f: float | None = None,
    ready_upper_f: float | None = None,
    switch_back_after_minutes: float | None = None,
    slot_minutes: float = 10.0,
    recovery: RecoveryModel | None = None,
) -> ElementModeResult:
    """A stint in an element mode from ``scenario.start``: "what if I
    switch to Energy Saver, High Demand or Electric?", how fast, at what
    energy, and the tank when it ends. ``mode`` is a
    ``DhwOperationSetting`` value, 2, 3 or 4.

    The stint is the scenario walked with ``mode`` written at its start
    (``simulate``; the scenario's later writes still take), under the
    TOU windows the heater keeps (``marked_windows``: an unknown marker
    counts as in force), its heat pump's recovery served by ``recovery``
    when given. It ends when the recovery the write sets off does (every
    element and the heat pump stopped), within ``READY_HORIZON``, or at
    the switch-back, whichever is first. A recovery part of which a
    later mode write or the heater dropping the mode at a window stops,
    or whose compressor a setpoint write stops short of the new
    setpoint, within the stint, has no ``full_minutes``
    (``recovery_cut_short``); a write of the mode already in force
    changes nothing, and the stint is what the heater does in it anyway
    (``mode_already_in_force``). The ready level and the setpoint are
    the setpoint in force once the start's writes and reservation entries
    have fired.

    ``setpoint_f`` is a setpoint written with the mode instead of the
    heater's (``settings.setpoint_f``), which still decides the
    TOU-window test: a what-if setpoint of 108 °F must not make a
    resting heater read as inside a window.

    ``ready_upper_f`` is an upper-zone temperature that counts as ready,
    the setpoint by default. ``switch_back_after_minutes`` ends the
    stint that long after the start: a time it does not reach first is
    None. ``reachable``
    says whether a mode write can take at the start: not while heating
    is disabled, nor inside a TOU window, by the heater's own marker
    (``tou_marked``). An unknown marker counts as in force: the
    conservative direction is "do not count on it".

    Raises ``ValueError`` for a mode that runs no element, and for a
    setpoint written outside the heater's range, and
    ``SimulationError`` for a walk it cannot price, as ``simulate``
    does.
    """
    s = scenario
    named = ENGINE_MODE.get(mode)
    if named is None or named == "heat_pump":
        raise ValueError(
            f"mode {mode} runs no element: 2 Electric, 3 Energy Saver or "
            "4 High Demand"
        )
    if not (math.isfinite(slot_minutes) and slot_minutes > 0.0):
        raise ValueError("slot_minutes must be positive")
    if switch_back_after_minutes is not None and not (
        math.isfinite(switch_back_after_minutes)
        and switch_back_after_minutes >= 0.0
    ):
        raise ValueError("switch_back_after_minutes must not be negative")
    windows, schedule_unknown = _windows(s, s.start + READY_HORIZON)

    def stint_walk(horizon: timedelta) -> SimulationResult:
        return _mode_walk(
            s, params, named, horizon, windows, recovery, setpoint_f=setpoint_f
        )

    # The mode's own recovery, to its end or the walk's: where the
    # switch-back, if any, falls against it.
    walked = stint_walk(READY_HORIZON)
    # The setpoint in force once the start's writes and entries have
    # fired, as the device holds it.
    target = s.settings.setpoint_f
    for w in sorted(walked.simulation.writes, key=lambda w: w.fires_at):
        if w.fires_at > s.start:
            break
        if w.outcome == "fired" and w.setpoint_f is not None:
            target = w.setpoint_f
    c = params.controller
    opens = c.write_start_lag + c.restart_lockout
    found = _stint_end(walked.simulation, s.start, opens)
    done, cut_at = (None, None) if found is None else found
    end = walked.until if done is None else done
    truncated = False
    if switch_back_after_minutes is not None:
        back = s.start + timedelta(minutes=switch_back_after_minutes)
        truncated = back < end
        end = min(end, back)
    reasons = list(BASE_REASONS)
    # The stint itself, its times, energy and end all from the one
    # walk; one with nothing to heat is walked for a second, for what
    # the entry decision at the start rests on.
    stint = stint_walk(end - s.start if end > s.start else timedelta(seconds=1))
    reasons += [
        r for r in stint.reasons if r != "element_mode_dropped_projected"
    ]
    # The heater dropping the mode at a window: the first walk's, which
    # also sees one that opens as the stint ends.
    if any(at <= end for at, _ in walked.simulation.drops):
        reasons.append("element_mode_dropped_projected")
    sim = stint.simulation
    path = sim.points if end > s.start else []
    heating = sim.heating if end > s.start else []
    if s.settings.mode == _MODE_SETTING[named]:
        # A write of the mode in force changes nothing: the stint is
        # what the heater does in it anyway.
        reasons.append("mode_already_in_force")
    if s.state.upper_f < target - ELEMENT_DONE_F and not any(
        h.source == "element" and h.start.at <= s.start + opens
        for h in walked.simulation.heating
    ):
        reasons.append("upper_element_does_not_start")
    if truncated:
        reasons.append("truncated_by_switch_back")
    if schedule_unknown:
        reasons.append("tou_schedule_unknown")
    # The recovery ends with every element and the heat pump stopped,
    # not cut by a write or the heater's drop; read off the stint's own
    # walk, whose last stop may land a little sooner than the first's.
    cut = cut_at is not None and cut_at <= end
    full: float | None = None
    if not truncated and done is not None and not cut:
        again = _stint_end(sim, s.start, opens) if path else None
        full = _minutes(s.start, end if again is None else again[0])
    if cut:
        reasons.append("recovery_cut_short")

    def upper_at(level: float) -> float | None:
        return _minutes(
            s.start,
            _first_reach(
                path or sim.points[:1], s.start, level, lambda p: p.upper_f
            ),
        )

    # Reached as the elements reach their off point (``ELEMENT_DONE_F``).
    to_setpoint = upper_at(target - ELEMENT_DONE_F)
    ready = to_setpoint
    if ready_upper_f is not None:
        ready = upper_at(ready_upper_f)
        if ready is None and ready_upper_f > target:
            reasons.append("ready_target_above_setpoint")
    last = path[-1] if path else None
    unpriced = any(
        h.source == "compressor" and h.input_wh is None for h in heating
    )
    _, disabled = _engine_mode(s.settings.mode)
    reason: str | None = None
    # The heater's own marker decides, at its own setpoint; unknown
    # counts as in force.
    if disabled:
        reason = "heating_disabled"
    elif tou_marked(s.settings) is not False:
        reason = "tou_window_in_force"
    return ElementModeResult(
        starts_at=s.start,
        mode=named,
        reachable=reason is None,
        unreachable_reason=reason,
        upper_ready_minutes=ready,
        upper_setpoint_minutes=to_setpoint,
        full_minutes=full,
        end_minute=round((end - s.start).total_seconds() / 60.0, 3),
        end_upper_f=round(s.state.upper_f if last is None else last.upper_f, 2),
        end_lower_f=round(s.state.lower_f if last is None else last.lower_f, 2),
        end_layers_f=s.state.layers_f if last is None else last.layers_f,
        element_minutes=round(
            sum(
                (min(h.end, end) - max(h.start.at, s.start)).total_seconds()
                for h in heating
                if h.source == "element"
            )
            / 60.0,
            3,
        ),
        element_kwh=round(sum(p.element_wh for p in path) / 1000.0, 4),
        heat_pump_kwh=None
        if unpriced
        else round(sum(p.input_wh or 0.0 for p in path) / 1000.0, 4),
        profile=_profile(path, s.start, slot_minutes),
        reasons=tuple(_unique(reasons)),
    )


def _minutes(start: datetime, when: datetime | None) -> float | None:
    """``when`` as minutes from ``start``, to 0.01; None for None."""
    if when is None:
        return None
    return round((when - start).total_seconds() / 60.0, 2)


def _instant(at: datetime) -> datetime:
    """``at`` in UTC, as the scenario's instants are held; a naive one is
    refused."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError(f"{at.isoformat()} has no time zone")
    return at.astimezone(UTC)


def _ambient_at(environment: Environment, at: datetime) -> float:
    """The air at the heater at ``at``, °F, from ``environment``."""
    a = environment.ambient_f
    readings = _air_readings(environment)
    if readings is None:
        assert not isinstance(a, tuple)
        return float(a) if math.isfinite(a) else DEFAULT_AMBIENT_F
    return AmbientSampler(readings).at(at)


def _scheduled(
    s: Scenario, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]] | None:
    """The schedule's TOU windows over ``[start, end]``: none with TOU
    off; None, not known, with it on and no periods to lay out."""
    on = (
        s.commands.tou_enabled
        if s.commands.tou_enabled is not None
        else s.schedules.tou_enabled
    )
    switches = s.schedules.tou_switches
    if not on and not any(sw for _, sw in switches):
        return []
    if not s.schedules.tou_periods:
        return None
    return while_enabled(
        tou_windows(s.schedules.tou_periods, ZoneInfo(s.tz), start, end),
        on,
        switches,
    )


def _to_start(
    s: Scenario, params: HeaterParams, start: datetime
) -> tuple[float, float]:
    """The probes of the tank the heater's own start at ``start`` heats
    from, coasting from now under ``s.loads``. A draw at ``start``
    itself, the one that trips the trigger, is taken before the
    recovery: its tank is the one the draw leaves."""
    now = s.start
    upper, lower = s.state.upper_f, s.state.lower_f
    if start > now:
        to_start = standby(
            s.state,
            s.environment,
            s.loads,
            params,
            start=now,
            until=start,
            history=s.history,
        )
        if to_start.points:
            upper, lower = (
                to_start.points[-1].upper_f,
                to_start.points[-1].lower_f,
            )
    at_start = sorted(d.gallons for d in s.loads.draws if d.at == start)
    if at_start:
        physics = _physics(
            params,
            s.environment,
            now,
            start + TRIGGER_HORIZON,
            draws_on=True,
            model=None,
            defaults=[],
            circulation=_circulation(s.loads, params),
        )
        for g in at_start:
            upper, lower = physics.observe(
                physics.draw(start, physics.estimate(upper, lower), g)
            )
    return upper, lower


def next_recovery(
    scenario: Scenario,
    params: HeaterParams,
    *,
    recovery: RecoveryModel | None = None,
) -> Recovery:
    """The heat-pump recovery the heater runs next, as ``time_to_ready``
    scores it: from now if the compressor runs; else the tank coasts
    (``standby``), under the scenario's draws (none when the draw terms
    are not calibrated), to the heater's own trigger within
    ``TRIGGER_HORIZON`` (``idle`` without one), and the recovery runs
    from the tank there (``forecast``: to the heater's stop threshold
    and on past it by the run-on), with the TOU cap judged where it ends
    (``_tou_capped``). A running compressor whose lower zone is already
    at the threshold has nothing left here (``forecast`` asks when the
    tank is ready); ``active_cycle`` gives its run-on.
    ``recovery`` serves its duration (``extensions.RecoveryModel``).
    ``not_scheduled`` while heating is disabled; ``unavailable`` when
    it cannot be computed."""
    s = scenario
    mode, disabled = _engine_mode(s.settings.mode)
    if disabled:
        return Recovery("not_scheduled")
    now = s.start
    start, upper, lower = now, s.state.upper_f, s.state.lower_f
    try:
        if not s.state.compressor_running:
            # The household's expected draws cool the tank to its
            # trigger.
            coast = standby(
                s.state,
                s.environment,
                s.loads,
                params,
                start=now,
                until=now + TRIGGER_HORIZON,
                history=s.history,
                settings=s.settings,
                schedules=s.schedules,
                tz=s.tz,
            )
            if not coast.points:
                return Recovery("unavailable")
            if coast.starts_at is None:
                return Recovery("idle")
            start = max(now, coast.starts_at)
            upper, lower = _to_start(s, params, start)
        if mode != "electric" and _out_of_range(
            params, [_ambient_at(s.environment, start)], lower
        ):
            # No heat-pump recovery runs: the elements heat the tank,
            # from the heater's own start.
            return Recovery(
                "unavailable",
                [(start, upper, lower)],
                start_minute=(start - now).total_seconds() / 60.0,
                hp_unavailable=True,
            )
        starting = HeaterState(
            upper_f=upper,
            lower_f=lower,
            compressor_running=s.state.compressor_running,
        )
        circulating = Loads(circulation=s.loads.circulation)
        answer = forecast(
            starting,
            s.settings,
            s.environment,
            params,
            at=start,
            target_time=start,
            loads=circulating,
            history=s.history,
            model=recovery,
        )
        if answer.status == "not_scheduled":
            return Recovery("not_scheduled")
        if not answer.trajectory:
            return Recovery("unavailable")
        trajectory, capped = _tou_capped(
            s,
            params,
            start,
            lower,
            s.settings.setpoint_f - params.controller.tou_cap_f,
            list(answer.trajectory),
            starting,
            circulating,
            recovery,
        )
    except SimulationError:
        return Recovery("unavailable")
    return Recovery(
        "ok",
        [(pt.at, pt.t_upper_f, pt.t_lower_f) for pt in trajectory],
        tou_capped=capped,
        input_wh=[pt.input_energy_wh or 0.0 for pt in trajectory],
        start_minute=(start - now).total_seconds() / 60.0,
        trajectory=tuple(trajectory),
    )


def _tou_capped(
    s: Scenario,
    params: HeaterParams,
    start: datetime,
    lower: float,
    level: float,
    full: list[HeatingPoint],
    starting: HeaterState,
    loads: Loads,
    model: RecoveryModel | None,
) -> tuple[list[HeatingPoint], bool]:
    """The recovery the heater runs under the TOU cap, judged where it
    ends rather than where it starts: the device stops a recovery at
    the first instant it is inside a window with the lower zone at
    ``level`` (the setpoint less the cap), so one that starts off-peak
    and runs into a window is still capped.

    - Already at the level inside the window: it does not heat.
    - At the level before the window opens: it runs on toward the full
      target and stops as the window opens, a compressor already
      running above the level included.
    - At the level inside the window: it stops there.
    - At the level only after the window closes: the full target
      applies again, uncapped."""
    now = s.start
    # An unknown marker counts as in force: the conservative direction
    # is "it may not heat".
    windows = marked_windows(
        now,
        tou_marked(s.settings) is not False,
        start,
        full[-1].at,
        _scheduled(s, start, full[-1].at),
    )
    stop = _cap_stop(full, level, windows)
    if stop is None:
        return full, False
    w0, w1 = next(w for w in windows if w[0] <= stop < w[1])
    capped = forecast(
        starting,
        s.settings,
        s.environment,
        params,
        at=start,
        target_time=start,
        target_lower_f=level,
        loads=loads,
        history=s.history,
        model=model,
    )
    cut: list[HeatingPoint] = list(capped.trajectory or ())
    if start >= w0 and lower >= level:
        return cut, True
    reached = capped.ready_at or (cut[-1].at if cut else None)
    if reached is None:
        return full, False
    if reached < w0:
        return _until(full, w0), True
    if reached < w1:
        return cut, True
    return full, False


def _cap_stop(
    points: Sequence[HeatingPoint],
    level: float,
    windows: Sequence[tuple[datetime, datetime]],
) -> datetime | None:
    """The first instant on ``points`` inside one of ``windows`` with the
    lower zone at ``level`` or above; None when there is none."""
    end = points[-1].at
    found: list[datetime] = []
    path = [(p.at, p.t_upper_f, p.t_lower_f) for p in points]
    for w0, w1 in windows:
        lo = max(points[0].at, w0)
        if lo >= w1 or lo > end:
            continue
        state = _heating_state(path, lo)
        if state is not None and state[1] >= level:
            found.append(lo)
            continue
        for p0, p1 in itertools.pairwise(points):
            if p1.at <= lo or p0.at >= w1:
                continue
            if p1.t_lower_f >= level > p0.t_lower_f:
                f = (level - p0.t_lower_f) / (p1.t_lower_f - p0.t_lower_f)
                at = p0.at + (p1.at - p0.at) * f
                if lo <= at < w1:
                    found.append(at)
                break
    return min(found) if found else None


def _heating_state(
    path: Sequence[tuple[datetime, float, float]], at: datetime
) -> tuple[float, float] | None:
    for (t0, u0, l0), (t1, u1, l1) in itertools.pairwise(path):
        if t0 <= at <= t1:
            span = (t1 - t0).total_seconds()
            f = 0.0 if span <= 0 else (at - t0).total_seconds() / span
            return u0 + (u1 - u0) * f, l0 + (l1 - l0) * f
    if path and at <= path[0][0]:
        return path[0][1], path[0][2]
    return None


def _until(points: list[HeatingPoint], at: datetime) -> list[HeatingPoint]:
    """``points`` cut off at ``at``: the recovery the window's opening
    stops before its target. The interval ``at`` cuts keeps its share
    of energy, in proportion to time."""
    kept = [p for p in points if p.at <= at]
    if kept and kept[-1].at < at and len(kept) < len(points):
        p0, p1 = kept[-1], points[len(kept)]
        share = (at - p0.at).total_seconds() / (p1.at - p0.at).total_seconds()
        kept.append(
            dataclasses.replace(
                p1,
                at=at,
                t_upper_f=p0.t_upper_f + (p1.t_upper_f - p0.t_upper_f) * share,
                t_lower_f=p0.t_lower_f + (p1.t_lower_f - p0.t_lower_f) * share,
                input_energy_wh=None
                if p1.input_energy_wh is None
                else p1.input_energy_wh * share,
                stored_energy_wh=p1.stored_energy_wh * share,
            )
        )
    return kept


#: How far ahead ``time_to_ready`` walks each mode for the bath.
READY_HORIZON = timedelta(hours=24)

#: Each mode ``time_to_ready`` walks, by the setting that selects it.
_MODE_SETTING: Mapping[HeaterMode, int] = MappingProxyType(
    {name: code for code, name in ENGINE_MODE.items()}
)


def _windows(
    s: Scenario, end: datetime
) -> tuple[list[tuple[datetime, datetime]], bool]:
    """The TOU windows the heater keeps from ``s.start`` to ``end``
    (``marked_windows``), and whether its schedule is unknown. TOU on
    with neither its periods nor the heater's marker known is in force,
    as for the counter test."""
    scheduled = _scheduled(s, s.start, end)
    marker = tou_marked(s.settings)
    if marker is None and scheduled is None:
        marker = True
    return (
        marked_windows(s.start, marker, s.start, end, scheduled),
        scheduled is None,
    )


def _mode_walk(
    s: Scenario,
    params: HeaterParams,
    mode: HeaterMode,
    horizon: timedelta,
    windows: Sequence[tuple[datetime, datetime]],
    recovery: RecoveryModel | None,
    *,
    setpoint_f: float | None = None,
) -> SimulationResult:
    """``s`` walked for ``horizon`` with ``mode`` written at its start:
    in place of a mode the scenario writes there (its setpoint kept, or
    ``setpoint_f`` written with the mode), and before its later writes,
    which still take."""
    write = Write(at=s.start, mode=_MODE_SETTING[mode], setpoint_f=setpoint_f)
    early = [w for w in s.commands.writes if w.at <= s.start]
    at_start = [
        w.model_copy(update={"mode": None})
        for w in early
        if w.setpoint_f is not None
    ]
    later = [w for w in s.commands.writes if w.at > s.start]
    commands = s.commands.model_copy(
        update={"writes": (*at_start, write, *later)}
    )
    walked = s.model_copy(update={"commands": commands, "horizon": horizon})
    return simulate(
        walked, params, recovery=recovery, tou_windows_in_force=windows
    )


def _mode_run(
    s: Scenario,
    params: HeaterParams,
    mode: HeaterMode,
    bath_gal: float,
    windows: Sequence[tuple[datetime, datetime]],
    recovery: RecoveryModel | None,
) -> ModeRun:
    """The scenario walked with ``mode`` written at its start (the mode's
    entry rule run, as the heater runs it on a write) to the first
    instant its layers deliver ``bath_gal`` (``delivery.deliverable``),
    within ``READY_HORIZON``, under the TOU ``windows``. Its reasons are
    the walk's to that instant, or over the whole horizon when it does
    not get there."""
    try:
        result = _mode_walk(s, params, mode, READY_HORIZON, windows, recovery)
    except SimulationError:
        return ModeRun(mode, None, None, ("time_to_ready_unavailable",))
    wh = 0.0
    for pt in result.simulation.points:
        wh += (pt.input_wh or 0.0) + pt.element_wh
        got = deliverable(
            params,
            pt.upper_f,
            pt.lower_f,
            pt.layers_f,
            inlet_f=_inlet_f(s, params, pt.at),
        )
        if got.gal < bath_gal:
            continue
        span = pt.at - s.start
        reasons = result.reasons
        if span > timedelta(0):
            # What the walk rests on up to the bath, not past it.
            with contextlib.suppress(SimulationError):
                reasons = _mode_walk(
                    s, params, mode, span, windows, recovery
                ).reasons
        return ModeRun(
            mode,
            round(span.total_seconds() / 60.0, 1),
            round(wh / 1000.0, 2),
            tuple(reasons),
        )
    return ModeRun(mode, None, None, tuple(result.reasons))


def time_to_ready(
    scenario: Scenario,
    params: HeaterParams,
    *,
    bath_gal: float | None = None,
    shower_gal: float | None = None,
    shower_from_forecast: bool = False,
    drawing: bool = False,
    inlet_measured: bool = False,
    recovery: RecoveryModel | None = None,
) -> Readiness:
    """Hot water at ``scenario.start`` and ahead: deliverable gallons
    now, whether the tank can run a bath of ``bath_gal`` and when it
    can, in the heat pump and in each element mode, with the energy to
    get there, and how many showers of ``shower_gal`` it is ready for
    (``sim.ready``).

    The gallons are the tank's layers' (``HeaterState.layers_f``, else
    the profile the probes stand for: ``tank_profile_estimated``) at the
    scenario's inlet (``sim.delivery``). Each mode's time is the
    scenario walked with that mode written at its start (``simulate``;
    the scenario's later writes still take) to the first instant its
    layers deliver the bath, within ``READY_HORIZON``, under the TOU
    windows the heater keeps (``marked_windows``: an unknown marker
    counts as in force); its recovery's duration served by ``recovery``
    when given (``extensions.RecoveryModel``) and by physics alone
    otherwise, which runs short on long recoveries (the simulator
    explanation's *Accuracy*). The heat pump's walk's reasons, to the
    bath, are the answer's; an element mode's row says what its own walk
    adds to them.

    ``bath_gal`` and ``shower_gal`` default to
    ``ReadinessParams.bath_gal`` and ``shower_gal``, named in
    ``defaults_used``. ``shower_from_forecast``: the
    ``shower_gal`` given is a draw forecast's
    (``draw_forecast.shower_gal``). ``drawing``: water is being drawn
    now. ``inlet_measured``: the scenario's inlet is the mains as
    measured; without it the answer says ``inlet_temp_modelled``.

    Raises ``ValueError`` for a setpoint written outside the heater's
    range, as ``simulate`` does.
    """
    s = scenario
    _check_setpoints(s)
    p = params.readiness
    defaults: list[str] = []
    bath_source: Literal["configured", "request"] = "request"
    if bath_gal is None:
        bath_gal = p.bath_gal
        bath_source = "configured"
        defaults.append(f"bath_gal={bath_gal}")
    bath_gal = round(bath_gal, 1)
    shower_source: Literal["weekly_forecast", "default", "request"] = (
        "weekly_forecast" if shower_from_forecast else "request"
    )
    if shower_gal is None:
        shower_gal = p.shower_gal
        shower_source = "default"
        defaults.append(f"shower_gal={shower_gal}")
    # In a TOU window now: the heater's own marker. Unknown counts as in
    # force, as for the counter test and for ``element_mode``: the
    # conservative direction is "it may not heat".
    marked = tou_marked(s.settings)
    if marked is None:
        defaults.append("tou_window=in_force (hp_upper_on_f unknown)")
        marked = True
    tank = TankNow(
        upper_f=s.state.upper_f,
        lower_f=s.state.lower_f,
        drawing=drawing,
        element_on=s.state.element_running,
        tou_window=marked,
        ambient_f=_ambient_at(s.environment, s.start),
        compressor_on=s.state.compressor_running,
    )
    inlet = _inlet_f(s, params)
    now_gal = deliverable(
        params, tank.upper_f, tank.lower_f, s.state.layers_f, inlet_f=inlet
    )
    # The recovery and the modes' walks are only needed when the bath is
    # not ready now.
    nxt = Recovery("unavailable")
    runs: list[ModeRun] = []
    hp_reasons: tuple[str, ...] = ()
    schedule_unknown = False
    if now_gal.gal < bath_gal:
        nxt = next_recovery(s, params, recovery=recovery)
        if nxt.outcome != "not_scheduled":
            windows, schedule_unknown = _windows(s, s.start + READY_HORIZON)
            walked = [
                _mode_run(s, params, mode, bath_gal, windows, recovery)
                for mode in MODES
            ]
            # The heat pump's walk's reasons are the answer's; each
            # element mode's row says what its own walk adds to them.
            hp_reasons = walked[0].reasons
            runs = [
                replace(
                    r,
                    reasons=(
                        tuple(
                            x
                            for x in r.reasons
                            if x == "time_to_ready_unavailable"
                        )
                        if r.mode == "heat_pump"
                        else tuple(x for x in r.reasons if x not in hp_reasons)
                    ),
                )
                for r in walked
            ]
    answer = assess(
        s.start,
        tank,
        nxt,
        now_gal,
        runs,
        bath_gal=bath_gal,
        bath_source=bath_source,
        shower_gal=shower_gal,
        shower_source=shower_source,
        valid_s=0.0,
        within_resolution=within_resolution(
            params,
            tank.upper_f,
            tank.lower_f,
            s.state.layers_f,
            bath_gal,
            inlet_f=inlet,
        ),
        params=p,
    )
    answer["reasons"] = _unique(
        [
            *answer["reasons"],
            *([] if inlet_measured else ["inlet_temp_modelled"]),
            *_unfitted(params, "tank", "draw"),
            *_ambient_reasons(s.environment),
            *(
                [HEAT_PUMP_UNAVAILABLE]
                if nxt.hp_unavailable
                # A heat-pump recovery past the range's top, which the
                # elements finish (a capped one stops short of it).
                or (
                    nxt.outcome == "ok"
                    and bool(nxt.points)
                    and nxt.points[-1][2]
                    > params.controller.hp_water_range_f[1]
                )
                else []
            ),
        ]
    )
    if runs:
        answer["reasons"] = _unique(
            [
                *answer["reasons"],
                *hp_reasons,
                *(["tou_schedule_unknown"] if schedule_unknown else []),
                *_unfitted(params, "compressor", "power"),
                *(
                    [CIRCULATION_UNKNOWN]
                    if _circulation_unknown(
                        params, s.loads, s.start + READY_HORIZON
                    )
                    else []
                ),
            ]
        )
    # A mode's row says only what the answer does not.
    for row in answer["bath"]["by_mode"]:
        row["reasons"] = [
            r for r in row["reasons"] if r not in answer["reasons"]
        ]
    return typed(answer, s.start, nxt, defaults)


# ── ready by a time ─────────────────────────────────────────────────

#: How far ahead a forecast's target may be: the coast walks 10-minute
#: steps to it.
FORECAST_HORIZON = timedelta(hours=168)
#: The fixed point's passes, start against the coast to it.
_FORECAST_PASSES = 3
#: A forecast's refinement stops when its duration moves no more than
#: this, minutes.
_REFINE_MINUTES = 2.0
#: The device's minimum setpoint (40.5 °C): its upper start threshold
#: rests here except while a TOU window raises it to about the setpoint.
DEVICE_REFERENCE_F = 104.9
#: Half a degree C: the threshold is reported in 0.5 °C steps.
_REFERENCE_SLACK_F = 0.9
#: A raised upper threshold also sits at least this far above resting.
_RAISED_MARGIN_F = 5.0


def counter_measures_to_setpoint(
    hp_upper_on_f: float | None, target_f: float
) -> bool:
    """Whether the heater's energy count (``energy_to_setpoint``) is
    measured to ``target_f``: only while its upper start threshold
    rests (no TOU window raising it), when a zero count agrees with the
    probes. Inside a window the heater counts to its TOU cap, about
    2 °C lower, and an unknown threshold is taken as raised, so the
    probes decide."""
    return (
        hp_upper_on_f is not None
        and hp_upper_on_f <= DEVICE_REFERENCE_F + _REFERENCE_SLACK_F
        and hp_upper_on_f <= target_f - _RAISED_MARGIN_F
    )


#: How long the heater's own TOU marker may trail a scheduled edge: its
#: upper threshold moved 1-18 s after the window's edges at one
#: installation.
TOU_MARKER_LAG = timedelta(seconds=60)


def tou_marked(settings: Settings) -> bool | None:
    """Whether the heater itself marks a TOU window in force now: its
    upper start threshold raised to about the setpoint
    (``Settings.hp_upper_on_f``). It sees what the schedule cannot (an
    override, a window it skipped). None when the threshold is not
    known."""
    if settings.hp_upper_on_f is None:
        return None
    return not counter_measures_to_setpoint(
        settings.hp_upper_on_f, settings.setpoint_f
    )


def marked_windows(
    now: datetime,
    marked: bool | None,
    start: datetime,
    end: datetime,
    scheduled: Sequence[tuple[datetime, datetime]] | None,
) -> list[tuple[datetime, datetime]]:
    """The TOU windows over a recovery ``[start, end]``: the schedule's
    (None: not known), with the heater's own marker (``tou_marked``)
    overriding it only for a recovery running now and away from a
    scheduled edge, which the marker trails (``TOU_MARKER_LAG``): a
    scheduled window the heater does not mark is dropped, and one it
    marks that the schedule lacks covers the recovery. A later recovery
    is the schedule's alone. With no schedule, the window marked now
    stands in."""
    cover = (min(now, start), end + timedelta(minutes=1))
    if scheduled is None:
        return [cover] if marked else []
    windows = list(scheduled)
    if (
        marked is None
        or start > now
        or any(abs(now - edge) <= TOU_MARKER_LAG for w in windows for edge in w)
    ):
        return windows
    if marked and not in_window(now, windows):
        return sorted([*windows, (now, end + timedelta(minutes=1))])
    if not marked:
        return [w for w in windows if not w[0] <= now < w[1]]
    return windows


def forecast(
    state: HeaterState,
    settings: Settings,
    environment: Environment,
    params: HeaterParams,
    *,
    at: datetime,
    target_time: datetime,
    target_f: float | None = None,
    target_lower_f: float | None = None,
    loads: Loads | None = None,
    history: History | None = None,
    model: RecoveryModel | None = None,
) -> Forecast:
    """When a heat-pump recovery must start for the tank to be ready at
    ``target_time``, from ``state`` at ``at``: the tank coasts to the
    start (jacket loss, and circulation's runs in ``loads``; no draws),
    the recovery runs from there to the lower zone's target (and, at
    the heater's own threshold, on past it to where the heater stops,
    ``ControllerParams.hp_stop_overshoot_f``, as ``simulate``'s does),
    and the start is refined to ``target_time`` less that duration, to a
    fixed point, the tank at the start projected to exactly it.

    The target is ``target_lower_f`` (a partial charge), else
    ``target_f``, else the heater's own stop threshold
    (``Settings.hp_lower_off_f``), else the setpoint, named in
    ``defaults_used``. With no target asked for, a zero energy count
    (``HeaterState.energy_to_setpoint_wh``) outside a TOU window, or a
    lower zone already at the target, needs no heating; a zero count
    inside one marks the recovery ``tou_capped``. ``model`` serves the
    duration (``extensions.RecoveryModel``); physics alone otherwise.
    """
    origin, target = _instant(at), _instant(target_time)
    if target > origin + FORECAST_HORIZON:
        raise ValueError(
            "target_time is more than "
            f"{FORECAST_HORIZON.total_seconds() / 3600:.0f} h ahead"
        )
    history = history if history is not None else History()
    loads = loads if loads is not None else Loads()
    defaults: list[str] = []
    partial = target_lower_f is not None
    override = target_f is not None or partial
    if target_lower_f is not None:
        goal = target_lower_f
    elif target_f is not None:
        goal = target_f
    elif settings.hp_lower_off_f is not None:
        goal = settings.hp_lower_off_f
    else:
        goal = settings.setpoint_f
        defaults.append("hp_lower_off_f=setpoint_f")
    energy = state.energy_to_setpoint_wh
    counted = (
        energy is not None
        and energy <= 0
        and counter_measures_to_setpoint(settings.hp_upper_on_f, goal)
    )
    tou_capped = (
        not override and energy is not None and energy <= 0 and not counted
    )
    _, disabled = _engine_mode(settings.mode)
    if (not override and counted) or state.lower_f >= goal:
        return Forecast(
            status="no_heating_required",
            start_at=origin,
            ready_at=origin,
            duration_minutes=0.0,
            confidence=1.0,
            target_f=goal,
            feasible=True,
            shortfall_minutes=None,
            physics_estimate_minutes=None,
            estimator="no_heating_required",
            upper_f_at_start=state.upper_f,
            lower_f_at_start=state.lower_f,
            energy_to_setpoint_wh=energy,
            tou_capped=False,
            trajectory=(
                HeatingPoint(origin, state.upper_f, state.lower_f, 0.0, 0.0),
            ),
            reasons=tuple(_ambient_reasons(environment)),
            defaults_used=tuple(defaults),
        )
    physics = _physics(
        params,
        environment,
        origin,
        max(target, origin) + timedelta(hours=6),
        draws_on=False,
        model=model,
        defaults=defaults,
        circulation=_circulation(loads, params),
    )

    # The heater stops past its own threshold: the recovery's own end.
    # A caller's target (a partial charge, or a TOU cap's level) is
    # where it is asked to end.
    stop = goal + (0.0 if override else params.controller.hp_stop_overshoot_f)
    if history.compressor_stopped_at is None and not state.compressor_running:
        defaults.append("compressor_stopped_at=None (the longest start hold)")

    first, estimated = _tank(physics, state)

    def coast_to(when: datetime) -> Any:
        """The tank coasted to ``when``."""
        return physics.advance(origin, first, when).state

    def under_way(when: datetime) -> bool:
        """The start at ``when`` is the compressor running now."""
        return state.compressor_running and when <= origin

    def hold_at(when: datetime) -> float:
        """The hold of a start at ``when``: none for the compressor
        running now, else by the minutes since it last stopped. A
        compressor running now stops no earlier than now, so a later
        start counts its time off from now at most."""
        if under_way(when):
            return 0.0
        stopped = (
            origin
            if state.compressor_running
            else history.compressor_stopped_at
        )
        return start_hold_min(
            params.compressor,
            None
            if stopped is None
            else (when - _instant(stopped)).total_seconds() / 60.0,
        )

    def predict(when: datetime) -> tuple[Recovered, Any]:
        tank = coast_to(when)
        return physics.recover(
            when,
            tank,
            stop,
            hold_minutes=hold_at(when),
            under_way=under_way(when),
        ), tank

    served, tank = predict(target)
    served_at = target
    if not served.reached:
        raise _refusal(served)
    for _ in range(_FORECAST_PASSES):
        when = max(compute_start_time(target, served.minutes), origin)
        if when >= target:
            break
        refined, refined_tank = predict(when)
        if not refined.reached:
            break
        converged = abs(refined.minutes - served.minutes) <= _REFINE_MINUTES
        served, tank, served_at = refined, refined_tank, when
        if converged:
            break
    if state.compressor_running:
        # Put off, the run now stops and starts again with a start's
        # stir, which the run going on now has had: a later start is
        # taken where it is ready by the target from there, and
        # otherwise the run goes on now, ready early. Between the two
        # the refinement alternates.
        later = compute_start_time(target, served.minutes)
        if under_way(served_at) and later > origin:
            again, _ = predict(later)
            if again.reached:
                served, served_at = again, later
        if not under_way(served_at) and (
            compute_start_time(target, served.minutes) < origin
        ):
            now, _ = predict(origin)
            if now.reached:
                served, served_at = now, origin
    start_at = compute_start_time(target, served.minutes)
    feasible = start_at >= origin
    shortfall: float | None = None
    ready_at = target
    if not feasible:
        shortfall = (origin - start_at).total_seconds() / 60.0
    if not feasible or under_way(served_at):
        start_at = origin
        ready_at = origin + timedelta(minutes=served.minutes)
    tank = coast_to(start_at)
    upper_s, lower_s = physics.observe(tank)
    status = "partial_charge" if partial else "ok"
    if not feasible:
        status = "infeasible"
    elif not partial and served.confidence < LOW_CONFIDENCE_FLOOR:
        status = "low_confidence"
    scheduled_start: datetime | None = start_at
    scheduled_ready: datetime | None = ready_at
    if disabled:
        status = "not_scheduled"
        scheduled_start = scheduled_ready = None
        shortfall = None
        feasible = False
    trajectory: tuple[HeatingPoint, ...] | None = None
    if scheduled_start is not None and scheduled_ready is not None:
        # The recovery from where the tank is at its start, on the
        # served clock: its duration is within the refinement's
        # tolerance of the one served.
        trajectory = _on_clock(
            physics.recover(
                scheduled_start,
                tank,
                stop,
                hold_minutes=hold_at(scheduled_start),
                under_way=under_way(scheduled_start),
            ).trajectory,
            scheduled_ready,
        )
    return Forecast(
        status=status,
        start_at=scheduled_start,
        ready_at=scheduled_ready,
        duration_minutes=served.minutes,
        confidence=served.confidence,
        target_f=goal,
        feasible=feasible,
        shortfall_minutes=shortfall,
        physics_estimate_minutes=served.physics.estimate,
        estimator="physics" if served.model is None else "model",
        upper_f_at_start=upper_s,
        lower_f_at_start=lower_s,
        energy_to_setpoint_wh=energy,
        tou_capped=tou_capped,
        trajectory=trajectory,
        reasons=tuple(
            _unique(
                [
                    *estimated,
                    *served.reasons,
                    *_range_reasons(
                        params,
                        [served.ambient_start_f, served.ambient_mean_f],
                        lower_s,
                        stop,
                    ),
                    *_unfitted(params, "compressor", "power", "tank"),
                    *(_unfitted(params, "draw") if loads.draws else []),
                    *_ambient_reasons(environment),
                    *(
                        [CIRCULATION_UNKNOWN]
                        if _circulation_unknown(params, loads, target)
                        else []
                    ),
                ]
            )
        ),
        defaults_used=tuple(defaults),
    )


def active_cycle(
    state: HeaterState,
    settings: Settings,
    environment: Environment,
    params: HeaterParams,
    *,
    at: datetime,
    model: RecoveryModel | None = None,
) -> ActiveCycle:
    """What is left of the recovery the compressor is running at
    ``at``: the lower zone from where it is to its target
    (``Settings.hp_lower_off_f``, else the setpoint) and on to where the
    heater stops past it (``ControllerParams.hp_stop_overshoot_f``), at
    the air now,
    served by ``model`` when given, the start's hold taken as over.
    Beside it, the integrator's own remaining climb. A climb short of
    its target after ``tank_physics.RECOVERY_BOUND`` is refused
    (``SimulationError``). ``ready_at`` is when the
    compressor stops: a lower zone at its target has the run-on left,
    and one past it by the run-on has nothing left (0 minutes, ready
    now). ``forecast`` asks a different question, when the tank reaches
    its target, and finds no heating required from the target on."""
    at = _instant(at)
    if not state.compressor_running:
        return ActiveCycle(status="not_heating")
    defaults: list[str] = []
    if settings.hp_lower_off_f is not None:
        goal = settings.hp_lower_off_f
    else:
        goal = settings.setpoint_f
        defaults.append("hp_lower_off_f=setpoint_f")
    if "humidity" not in environment.model_fields_set:
        defaults.append(f"humidity={environment.humidity}")
    air = _ambient_at(environment, at)
    stop = goal + params.controller.hp_stop_overshoot_f
    if state.lower_f >= stop:
        # The cycle is at its end: the lower zone is past the target by
        # the run-on, and the compressor is about to stop. Nothing is
        # left, as the integrator says (0 minutes).
        return ActiveCycle(
            status="heating",
            ready_at=at,
            remaining_minutes=0.0,
            physics_remaining_minutes=0.0,
            lower_f=state.lower_f,
            target_f=goal,
            confidence=1.0,
            defaults_used=tuple(defaults),
        )
    physics = _physics(
        params,
        environment,
        at,
        at + RECOVERY_BOUND,
        draws_on=False,
        model=model,
        # Its defaults are said above: the air and the humidity.
        defaults=[],
    )
    # The cycle is under way: its hold is over and its layers stirred.
    tank, estimated = _tank(physics, state)
    served = physics.recover(at, tank, stop, under_way=True)
    if not served.reached:
        raise _refusal(served)
    reasons = [*estimated, *served.reasons]
    physics_minutes = served.physics.estimate
    return ActiveCycle(
        status="heating",
        ready_at=at + timedelta(minutes=served.minutes),
        remaining_minutes=served.minutes,
        physics_remaining_minutes=physics_minutes,
        lower_f=state.lower_f,
        target_f=goal,
        confidence=served.confidence,
        reasons=tuple(
            _unique(
                [
                    *reasons,
                    *_range_reasons(params, [air], state.lower_f, stop),
                    *_unfitted(params, "compressor", "tank"),
                    *_ambient_reasons(environment),
                ]
            )
        ),
        defaults_used=tuple(defaults),
    )
