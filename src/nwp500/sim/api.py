"""The simulator's entry points: ``simulate``, ``recovery`` and
``standby``.

Each takes values and returns values. A scenario's parts become the
engine's inputs here: the ambient as a frame on a 10-minute grid, the
TOU periods as windows and the reservations as firings
(``sim.schedules``), the modes as the engine names them, and the
parameters as the core's ``TankPhysics``. What could not be modelled is
named in the result's ``reasons``, and every default used in its
``defaults_used``.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from nwp500.sim.decay import AmbientSampler
from nwp500.sim.engine import Entry, Heater, RawWrite
from nwp500.sim.engine import simulate as walk
from nwp500.sim.extensions import HeatLedger, RecoveryModel
from nwp500.sim.inputs import (
    ELECTRIC,
    ENERGY_SAVER,
    HEAT_PUMP,
    HIGH_DEMAND,
    Environment,
    HeaterState,
    History,
    Loads,
    Scenario,
    Schedules,
    Settings,
)
from nwp500.sim.params import HeaterParams
from nwp500.sim.physics.element import HeaterMode
from nwp500.sim.result import RecoveryResult, SimulationResult, Trace
from nwp500.sim.schedules import (
    half_c_to_f,
    reservation_firings,
    tou_windows,
)
from nwp500.sim.tank_physics import TankPhysics

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


def _ambient_frame(
    environment: Environment, start: datetime, until: datetime
) -> pd.DataFrame:
    """The ambient as the core reads it: a frame on a 10-minute grid
    from an hour before ``start`` to 12 hours past ``until``, the
    readings interpolated onto it and held past their ends."""
    t0 = pd.Timestamp(start - AMBIENT_BEFORE).floor(AMBIENT_STEP)
    stamps = pd.date_range(t0, until + AMBIENT_AFTER, freq=AMBIENT_STEP)
    a = environment.ambient_f
    if isinstance(a, tuple):
        sampler = AmbientSampler(
            pd.DataFrame(
                {"ambient_f": [v for _, v in a]},
                index=pd.DatetimeIndex([t for t, _ in a]),
            )
        )
        values = [sampler.at(t.to_pydatetime()) for t in stamps]
    else:
        values = [float(a)] * len(stamps)
    return pd.DataFrame({"ambient_f": values}, index=stamps)


def _physics(
    params: HeaterParams,
    environment: Environment,
    start: datetime,
    until: datetime,
    *,
    draws_on: bool,
    model: RecoveryModel | None,
    defaults: list[str],
) -> TankPhysics:
    tau = params.tank.stratification_gap_tau_h
    if tau is None:
        raise ValueError(
            "params.tank.stratification_gap_tau_h is required "
            "(default_params() carries one)"
        )
    if "humidity" not in environment.model_fields_set:
        defaults.append(f"humidity={environment.humidity}")
    if environment.inlet_f is None:
        defaults.append(f"inlet_f={params.draw.inlet_temp_f}")
    return TankPhysics(
        params,
        _ambient_frame(environment, start, until),
        environment.humidity,
        draws_on=draws_on,
        tau_gap_hours=tau,
        draw_inlet_temp_f=environment.inlet_f,
        recovery_model=model,
    )


def _engine_mode(mode: int) -> tuple[HeaterMode, bool]:
    """The engine's mode for a device mode, and whether heating is
    disabled (Vacation, Power Off)."""
    named = ENGINE_MODE.get(mode)
    return (named, False) if named is not None else ("heat_pump", True)


def _history_defaults(
    state: HeaterState, history: History, defaults: list[str]
) -> None:
    if history.compressor_stopped_at is None and not state.compressor_running:
        defaults.append("compressor_stopped_at=None (no lockout at the start)")
    if history.heated_at is None:
        defaults.append("heated_at=None")
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


def _raw_writes(scenario: Scenario, reasons: list[str]) -> list[RawWrite]:
    out: list[RawWrite] = []
    for w in scenario.commands.writes:
        mode: HeaterMode | None = None
        if w.mode is not None:
            mode = ENGINE_MODE.get(w.mode)
            if mode is None:
                reasons.append("write_mode_not_modelled")
                if w.setpoint_f is None:
                    continue
        out.append(RawWrite(w.at, setpoint_f=w.setpoint_f, mode=mode, id=w.id))
    return out


def simulate(
    scenario: Scenario,
    params: HeaterParams,
    *,
    recovery: RecoveryModel | None = None,
    ledger: HeatLedger | None = None,
) -> SimulationResult:
    """Walk ``scenario`` from its start to its end on ``params``.

    ``recovery`` replaces the physics duration of each heat-pump
    recovery with its own (``extensions.RecoveryModel``); ``ledger``
    tracks booked heat along the path (``extensions.HeatLedger``). With
    neither, the physics alone is served.

    Raises ``engine.SimulationError`` when the walk cannot be completed.
    """
    s = scenario
    tz = ZoneInfo(s.tz)
    reasons: list[str] = []
    defaults: list[str] = []
    physics = _physics(
        params,
        s.environment,
        s.start,
        s.until,
        draws_on=bool(s.loads.draws),
        model=recovery,
        defaults=defaults,
    )
    tou_on = (
        s.commands.tou_enabled
        if s.commands.tou_enabled is not None
        else s.schedules.tou_enabled
    )
    windows = (
        tou_windows(s.schedules.tou_periods, tz, s.start, s.until)
        if tou_on
        else ()
    )
    mode, disabled = _engine_mode(s.settings.mode)
    if s.settings.hp_lower_on_f is None:
        defaults.append("hp_lower_on_f=None (no lower-zone start)")
    _history_defaults(s.state, s.history, defaults)
    entries = _entries(s, tz, reasons)
    raw = _raw_writes(s, reasons)
    sim = walk(
        start=s.start,
        upper_f=s.state.upper_f,
        lower_f=s.state.lower_f,
        running=s.state.compressor_running,
        until=s.until,
        setpoint_f=s.settings.setpoint_f,
        heater=Heater(
            hp_lower_on_f=s.settings.hp_lower_on_f,
            tou_windows=windows,
            heating_disabled=disabled,
            mode=mode,
            element=params.element,
        ),
        physics=physics,
        entries=entries,
        draws=[(d.at, d.gallons) for d in s.loads.draws],
        startup_wh=params.power.startup_wh,
        element_running=s.state.element_running,
        element_running_since=s.state.element_running_since,
        raw_writes=raw,
        stopped_at=s.history.compressor_stopped_at,
        heated_at=s.history.heated_at,
        ledger=ledger,
        controller=params.controller,
    )
    return SimulationResult(
        start=s.start,
        until=s.until,
        simulation=sim,
        reasons=(*_unique(reasons), *_unique(sim.reasons)),
        defaults_used=tuple(defaults),
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
        reasons.append("no_recovery_within_horizon")
        path = tuple(result.points)
    else:
        path = tuple(p for p in result.points if p.at <= first.end)
    return RecoveryResult(
        at=at,
        interval=first,
        path=path,
        reasons=tuple(reasons),
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
) -> Trace:
    """The tank coasting from ``start`` to ``until`` with no heating:
    jacket loss and the draws in ``loads``."""
    if until <= start:
        raise ValueError("until must be after start")
    history = history if history is not None else History()
    defaults: list[str] = []
    if history.heated_at is None:
        defaults.append("heated_at=None")
    physics = _physics(
        params,
        environment,
        start,
        until,
        draws_on=bool(loads.draws),
        model=None,
        defaults=defaults,
    )
    coast = physics.coast(
        start,
        state.upper_f,
        state.lower_f,
        until,
        [(d.at, d.gallons) for d in loads.draws if start <= d.at < until],
        heated_at=history.heated_at,
    )
    return Trace(points=tuple(coast.points), defaults_used=tuple(defaults))
