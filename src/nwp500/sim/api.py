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

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from nwp500.sim.book import (
    Booked,
    BookedHeatLedger,
    hp_btu_per_h,
    standby_btu,
)
from nwp500.sim.circulation import (
    Circulation,
    CirculationDraws,
    CirculationLoss,
)
from nwp500.sim.decay import AmbientSampler
from nwp500.sim.defaults import SITE_CIRCULATION
from nwp500.sim.delivery import (
    Deliverable,
    _state_before,  # pyright: ignore[reportPrivateUsage]
    booked_deliverable,
    deliverable,
    delivery_along,
    draw_domain_judgement,
    draw_windows,
)
from nwp500.sim.engine import (
    HEATER_SETPOINT_MAX_F,
    HEATER_SETPOINT_MIN_F,
    Entry,
    Heater,
    RawWrite,
    SimulationError,
)
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
from nwp500.sim.physics.element import (
    DEVICE_MODE,
    ElementMode,
    HeaterMode,
    mode_plan,
)
from nwp500.sim.ready import (
    Readiness,
    Recovery,
    TankNow,
    assess,
    typed,
)
from nwp500.sim.result import (
    ElementModeResult,
    RecoveryResult,
    SimulationResult,
    Trace,
)
from nwp500.sim.schedules import (
    half_c_to_f,
    reservation_firings,
    tou_windows,
)
from nwp500.sim.tank_physics import TankPhysics
from nwp500.sim.tou_triggers import heater_start, in_window

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


def _circulation(loads: Loads) -> Circulation | None:
    """The scenario's circulation as the core's, or None."""
    if loads.circulation is None:
        return None
    return Circulation(
        tuple((r.start, r.end) for r in loads.circulation),
        loads.circulation_known_until,
    )


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
    frame = _ambient_frame(environment, start, until)
    flowing: CirculationDraws | None = None
    if circulation is not None:
        terms = params.circulation
        if terms is None:
            raise ValueError(
                "circulation runs need HeaterParams.circulation: what each "
                "run displaces, its flow and the book's loss per gallon"
            )
        if terms == SITE_CIRCULATION:
            defaults.append(
                "circulation=one installation's (CirculationParams)"
            )
        flowing = CirculationDraws(
            circulation,
            terms.displaced_gal,
            terms.flow_gpm,
            # The return comes back at the air where the heater stands.
            AmbientSampler(frame).at,
        )
    return TankPhysics(
        params,
        frame,
        environment.humidity,
        draws_on=draws_on,
        flowing_draws=flowing,
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


def _check_setpoints(scenario: Scenario) -> None:
    """Refuse a write or a written reservation whose setpoint is outside
    the range the simulation can run (``HEATER_SETPOINT_MIN_F`` to
    ``_MAX_F``); the device's own limits are its feature's."""
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
        if (
            not HEATER_SETPOINT_MIN_F - 1e-6
            <= f
            <= HEATER_SETPOINT_MAX_F + 1e-6
        ):
            raise ValueError(
                f"{what}: setpoint {f:.1f} °F is outside the range the "
                f"simulation runs, {HEATER_SETPOINT_MIN_F}-"
                f"{HEATER_SETPOINT_MAX_F} °F"
            )


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
    book: Booked | None = None,
    ledger: HeatLedger | None = None,
) -> SimulationResult:
    """Walk ``scenario`` from its start to its end on ``params``.

    ``recovery`` replaces the physics duration of each heat-pump
    recovery with its own (``extensions.RecoveryModel``).

    ``book`` is the tank's booked heat at the start (``sim.book``): from
    the caller's own record, or ``book.full_tank_book`` when they know
    the tank has been quiet since a recovery ended. With it, the walk
    carries the book (``book.BookedHeatLedger``): a draw that spends the
    booked heat takes the upper zone down, the lower zone follows the
    cold front, and the delivery and the draw windows read the book.
    Without it the zones take each draw's calibrated response and the
    delivery is the upper zone's, and ``reasons`` says
    ``no_heat_book``. ``ledger`` is any other ``extensions.HeatLedger``
    in its place.

    Raises ``engine.SimulationError`` when the walk cannot be completed.
    """
    s = scenario
    _check_setpoints(s)
    tz = ZoneInfo(s.tz)
    reasons: list[str] = []
    defaults: list[str] = []
    circulation = _circulation(s.loads)
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
    if ledger is None and book is not None:
        terms = params.circulation
        ledger = BookedHeatLedger(
            book,
            physics.ambient.at,
            params.book_terms(),
            line_f=params.readiness.line_f,
            fall_f_per_gal=params.readiness.fall_f_per_gal,
            extra=(
                CirculationLoss(
                    circulation.runs, terms.flow_gpm, terms.loss_btu_per_gal
                )
                if circulation is not None and terms is not None
                else None
            ),
        )
    if ledger is None:
        reasons.append("no_heat_book")
    elif book is not None and book.aged(params.book_terms()):
        reasons.append("heat_book_aged")
    draws = [(d.at, d.gallons) for d in s.loads.draws]
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
        draws=draws,
        # A window's edges, so its onset and its end are read exactly
        # rather than across the coast's 10-minute grid.
        marks=[at for w in s.loads.windows for at in (w.start, w.end)],
        startup_wh=params.power.startup_wh,
        element_running=s.state.element_running,
        element_running_since=s.state.element_running_since,
        raw_writes=raw,
        stopped_at=s.history.compressor_stopped_at,
        heated_at=s.history.heated_at,
        ledger=ledger,
        controller=params.controller,
    )
    walked = (
        ledger.walk(sim.points, sim.heating, draws)
        if isinstance(ledger, BookedHeatLedger)
        else None
    )
    delivery = delivery_along(
        sim.points, draws, walked, params.readiness, params.book_terms()
    )
    out_of_domain_at: datetime | None = None
    if draws:
        any_out, out_of_domain_at = draw_domain_judgement(
            params.draw,
            [(p.at, p.upper_f) for p in sim.points],
            max(g for _, g in draws),
        )
        if any_out:
            reasons.append("draw_out_of_domain")
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
                booked=walked,
                band_btu=(
                    book.error_band_btu(params.book_terms())
                    if book is not None and book.aged(params.book_terms())
                    else 0.0
                ),
                p=params.readiness,
                ep=params.book_terms(),
            )
        ),
        booked=walked,
        draw_out_of_domain_at=out_of_domain_at,
    )


def readiness(
    state: HeaterState,
    settings: Settings,
    params: HeaterParams,
    *,
    book: Booked | None = None,
) -> Deliverable:
    """How much hot water the tank can deliver now, in delivered gallons
    at the line (``ReadinessParams.line_f``), and what the answer rests
    on (``sim.delivery``).

    With ``book``, the tank's booked heat answers (``basis`` ``energy``).
    Without it, the evidence in ``params.readiness.evidence`` (none by
    default) and the full-tank floor answer (``evidence``): a tank at
    its setpoint and not heating has the floor; any other state needs
    evidence, and reads 0 with ``colder_than_evidence`` without it.
    """
    heating = state.compressor_running or state.element_running
    if book is not None:
        return booked_deliverable(
            book,
            state.upper_f,
            state.lower_f,
            params.readiness,
            params.book_terms(),
        )
    return deliverable(
        state.upper_f,
        state.lower_f,
        params.readiness,
        ep=params.book_terms(),
        setpoint_f=settings.setpoint_f,
        heating=heating,
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
    ``schedules`` brings the TOU windows, their local times in ``tz``."""
    start, until = _instant(start), _instant(until)
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
        circulation=_circulation(loads),
    )
    draws = [(d.at, d.gallons) for d in loads.draws if start <= d.at < until]
    coast = physics.coast(
        start,
        state.upper_f,
        state.lower_f,
        until,
        draws,
        heated_at=history.heated_at,
    )
    reasons: list[str] = []
    out_of_domain_at: datetime | None = None
    if draws:
        any_out, out_of_domain_at = draw_domain_judgement(
            params.draw,
            [(start, state.upper_f)]
            + [(p.at, p.upper_f) for p in coast.points],
            max(g for _, g in draws),
        )
        if any_out:
            reasons.append("draw_out_of_domain")
    starts_at = trigger = None
    held = False
    margin: float | None = None
    if settings is not None:
        on = settings.hp_lower_on_f
        last = coast.points[-1]
        margin = None if on is None else last.lower_f - on
        mode, disabled = _engine_mode(settings.mode)
        windows = (
            tou_windows(schedules.tou_periods, ZoneInfo(tz), start, until)
            if schedules is not None and schedules.tou_enabled
            else ()
        )
        if not disabled:
            starts_at, trigger, held = heater_start(
                [(p.at, p.upper_f, p.lower_f) for p in coast.points],
                # None: no lower trigger, the TOU-opening one still.
                -math.inf if on is None else on,
                coast.impulses,
                windows=windows,
                setpoint_f=settings.setpoint_f,
                mode=mode,
            )
    return Trace(
        points=tuple(coast.points),
        defaults_used=tuple(defaults),
        starts_at=starts_at,
        trigger=trigger,
        start_held=held,
        lower_margin_f=margin,
        reasons=tuple(reasons),
        draw_out_of_domain_at=out_of_domain_at,
    )


def element_mode(
    state: HeaterState,
    settings: Settings,
    params: HeaterParams,
    *,
    mode: int,
    at: datetime,
    schedules: Schedules | None = None,
    tz: str = "UTC",
    ready_upper_f: float | None = None,
    hp_lower_minutes: float | None = None,
    switch_back_after_minutes: float | None = None,
    slot_minutes: float = 10.0,
) -> ElementModeResult:
    """A recovery in an element mode from ``at``: "what if I switch to
    Energy Saver, High Demand or Electric?", how fast, at what energy,
    and the tank when the mode is switched back
    (``physics.element.mode_plan``). ``mode`` is a ``DhwOperationSetting``
    value, 2, 3 or 4.

    ``ready_upper_f`` is an upper-zone temperature that counts as ready;
    ``hp_lower_minutes``, in High Demand and Energy Saver, the
    heat pump's minutes for the lower zone (``recovery`` gives them);
    ``switch_back_after_minutes`` ends the stint early. ``reachable``
    says whether a mode write can take at ``at``: not while heating is
    disabled, nor inside a TOU window (``schedules``, in ``tz``)."""
    at = _instant(at)
    named = ENGINE_MODE.get(mode)
    if named is None or named == "heat_pump":
        raise ValueError(
            f"mode {mode} runs no element: 2 Electric, 3 Energy Saver or "
            "4 High Demand"
        )
    device: ElementMode = DEVICE_MODE[named]  # type: ignore[assignment]
    plan = mode_plan(
        device,
        state.upper_f,
        state.lower_f,
        settings.setpoint_f,
        ready_upper_f=ready_upper_f,
        hp_lower_minutes=hp_lower_minutes,
        switch_back_after_minutes=switch_back_after_minutes,
        slot_minutes=slot_minutes,
        params=params.element,
    )
    _, disabled = _engine_mode(settings.mode)
    reason: str | None = None
    if disabled:
        reason = "heating_disabled"
    elif (
        schedules is not None
        and schedules.tou_enabled
        and in_window(
            at,
            tou_windows(
                schedules.tou_periods,
                ZoneInfo(tz),
                at,
                at + timedelta(minutes=1),
            ),
        )
    ):
        reason = "tou_window_in_force"
    return ElementModeResult(
        starts_at=at,
        plan=plan,
        reachable=reason is None,
        unreachable_reason=reason,
    )


def _instant(at: datetime) -> datetime:
    """``at`` in UTC, as the scenario's instants are held; a naive one is
    refused."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError(f"{at.isoformat()} has no time zone")
    return at.astimezone(UTC)


def _ambient_at(environment: Environment, at: datetime) -> float:
    """The air at the heater at ``at``, °F, from ``environment``."""
    a = environment.ambient_f
    if not isinstance(a, tuple):
        return float(a)
    sampler = AmbientSampler(
        pd.DataFrame(
            {"ambient_f": [v for _, v in a]},
            index=pd.DatetimeIndex([t for t, _ in a]),
        )
    )
    return sampler.at(at)


def next_recovery(
    scenario: Scenario,
    params: HeaterParams,
    *,
    recovery: RecoveryModel | None = None,
) -> Recovery:
    """The heat-pump recovery the heater runs next, as ``time_to_ready``
    scores it: from now if the compressor runs; else the tank coasts,
    under the scenario's draws, to the heater's own first compressor
    start within ``TRIGGER_HORIZON`` (``idle`` without one), and the
    recovery runs from the tank there, draw-free, in Heat Pump, with
    the TOU cap judged where it ends. ``recovery`` serves that
    recovery's duration (``extensions.RecoveryModel``); the trigger is
    the coast's alone. ``not_scheduled`` while heating is disabled;
    ``unavailable`` when the walk cannot be completed.

    The coast's loss, in the book's frame, is standby to the air now and
    the draws before the start; the recovery's heat into the book is the
    book's compressor term by the air now."""
    s = scenario
    _, disabled = _engine_mode(s.settings.mode)
    if disabled:
        return Recovery("not_scheduled")
    now = s.start
    air = _ambient_at(s.environment, now)
    bp = params.book_terms()
    start, upper, lower = now, s.state.upper_f, s.state.lower_f
    coast_btu = coast_gal = 0.0
    try:
        if not s.state.compressor_running:
            coast = simulate(
                s.model_copy(update={"horizon": TRIGGER_HORIZON}), params
            )
            first = next(
                (h for h in coast.heating if h.source == "compressor"), None
            )
            if first is None:
                return Recovery("idle")
            start = first.start.at
            state = _state_before(coast.points, start)
            if state is None:
                return Recovery("unavailable")
            upper, lower = state
            hours = (start - now).total_seconds() / 3600.0
            coast_btu = standby_btu(
                hours, s.state.upper_f, s.state.lower_f, air, bp
            )
            coast_gal = sum(
                d.gallons for d in s.loads.draws if now <= d.at < start
            )
        heat = simulate(
            s.model_copy(
                update={
                    "start": start,
                    "horizon": _RECOVERY_ROOM,
                    "state": HeaterState(
                        upper_f=upper, lower_f=lower, compressor_running=True
                    ),
                    "settings": s.settings.model_copy(
                        update={"mode": HEAT_PUMP}
                    ),
                    "history": History(),
                    "loads": Loads(),
                    "commands": s.commands.model_copy(update={"writes": ()}),
                }
            ),
            params,
            recovery=recovery,
        )
    except SimulationError:
        return Recovery("unavailable")
    if not heat.heating:
        return Recovery("unavailable")
    h = heat.heating[0]
    points = [p for p in heat.points if p.at <= h.end]
    return Recovery(
        "ok",
        [(p.at, p.upper_f, p.lower_f) for p in points],
        tou_capped=h.capped,
        input_wh=[p.input_wh or 0.0 for p in points],
        start_minute=(start - now).total_seconds() / 60.0,
        coast_btu=coast_btu,
        coast_draw_gal=coast_gal,
        hp_btu_per_h=hp_btu_per_h(air, bp),
    )


def time_to_ready(
    scenario: Scenario,
    params: HeaterParams,
    *,
    book: Booked | None = None,
    bath_gal: float | None = None,
    shower_gal: float | None = None,
    drawing: bool = False,
    recovery: RecoveryModel | None = None,
) -> Readiness:
    """Hot water at ``scenario.start`` and ahead: deliverable gallons
    now, whether the tank can run a bath of ``bath_gal`` and when it
    can, in the heat pump and in each element mode, with the energy to
    get there, and how many showers of ``shower_gal`` it is ready for
    (``sim.ready``).

    ``book`` is the tank's booked heat now, as for ``simulate``;
    without it the answer is the full-tank floor's or the evidence's.
    ``bath_gal`` and ``shower_gal`` default to
    ``ReadinessParams.bath_gal`` and ``shower_gal``, named in
    ``defaults_used``. ``drawing``: water is being drawn now. The
    recovery is the next one (``next_recovery``), its duration served
    by ``recovery`` when given (``extensions.RecoveryModel``) and by
    physics alone otherwise, which runs short on long recoveries (the
    simulator explanation's *Accuracy*).
    """
    s = scenario
    p = params.readiness
    defaults: list[str] = []
    if bath_gal is None:
        bath_gal = p.bath_gal
        defaults.append(f"bath_gal={bath_gal}")
    if shower_gal is None:
        shower_gal = p.shower_gal
        defaults.append(f"shower_gal={shower_gal}")
    tz = ZoneInfo(s.tz)
    windows = (
        tou_windows(s.schedules.tou_periods, tz, s.start, s.start)
        if (
            s.commands.tou_enabled
            if s.commands.tou_enabled is not None
            else s.schedules.tou_enabled
        )
        else ()
    )
    tank = TankNow(
        upper_f=s.state.upper_f,
        lower_f=s.state.lower_f,
        drawing=drawing,
        element_on=s.state.element_running,
        tou_window=in_window(s.start, windows),
        ambient_f=_ambient_at(s.environment, s.start),
        compressor_on=s.state.compressor_running,
    )
    now_gal = (
        booked_deliverable(
            book, tank.upper_f, tank.lower_f, p, params.book_terms()
        )
        if book is not None
        else deliverable(
            tank.upper_f,
            tank.lower_f,
            p,
            ep=params.book_terms(),
            setpoint_f=s.settings.setpoint_f,
            heating=tank.heating,
        )
    )
    # The recovery is only needed when the bath is not ready now.
    nxt = Recovery("unavailable")
    if now_gal.gal < round(bath_gal, 1):
        nxt = next_recovery(s, params, recovery=recovery)
    answer = assess(
        s.start,
        tank,
        nxt,
        bath_gal=round(bath_gal, 1),
        bath_source="configured",
        shower_gal=shower_gal,
        shower_source="default",
        valid_s=0.0,
        setpoint_f=s.settings.setpoint_f,
        booked=book,
        inlet_measured=True,
        params=p,
        element_params=params.element,
        book_params=params.book_terms(),
    )
    return typed(answer, s.start, nxt, defaults)
