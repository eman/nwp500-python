"""The simulator's entry points: ``simulate``, ``recovery`` and
``standby``.

A scenario's parts become the engine's inputs here: the ambient as a
frame on a 10-minute grid, the TOU periods as windows and the
reservations as firings (``sim.schedules``), the modes as the engine
names them, and the parameters as the core's ``TankPhysics``. What
could not be modelled is named in the result's ``reasons``, and every
default used in its ``defaults_used``.
"""

import dataclasses
import itertools
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd

from nwp500.sim.book import (
    Booked,
    BookedHeatLedger,
    hp_btu_per_h,
    standby_btu,
)
from nwp500.sim.circulation import (
    RUN_GAP,
    Circulation,
    CirculationDraws,
    CirculationLoss,
)
from nwp500.sim.decay import AmbientSampler, compute_start_time
from nwp500.sim.defaults import SITE_CIRCULATION
from nwp500.sim.delivery import (
    Deliverable,
    booked_deliverable,
    deliverable,
    delivery_along,
    draw_domain_judgement,
    draw_windows,
)
from nwp500.sim.engine import (
    DRAW_LEAD,
    HEATER_SETPOINT_MAX_F,
    HEATER_SETPOINT_MIN_F,
    Entry,
    Heater,
    HeatingInterval,
    RawWrite,
    SimulationError,
    quantise,
)
from nwp500.sim.engine import simulate as walk
from nwp500.sim.extensions import HeatLedger, RecoveryModel
from nwp500.sim.heat_pump_recovery import (
    PHYSICS_TRUNCATED,
    PhysicsRecovery,
    RecoveryContext,
    physics_recovery,
)
from nwp500.sim.heat_pump_recovery import recovery as serve_recovery
from nwp500.sim.heating_trajectory import HeatingPoint, build_heating_trajectory
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
)
from nwp500.sim.params import TAU_GAP_PRIOR_H, HeaterParams
from nwp500.sim.physics.compressor import MAX_MINUTES, predict_physics_detailed
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
    ActiveCycle,
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
    REFINE_TOL_MINUTES,
    Point,
    TankPhysics,
    ambient_window_mean,
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
        values = [float(a) if math.isfinite(a) else DEFAULT_AMBIENT_F] * len(
            stamps
        )
    return pd.DataFrame({"ambient_f": values}, index=stamps)


def _at_the_inlet(
    book: Booked | None, environment: Environment
) -> Booked | None:
    """``book`` converting heat to gallons at the scenario's inlet
    (``Environment.inlet_f``) where one is given, as the walk's draws
    take it (``cold_supply.on_the_mains`` for a plateau): the book's own
    inlet is a probe's median over hours, which at rest reads the air
    around the pipe."""
    if book is None or environment.inlet_f is None:
        return book
    return dataclasses.replace(book, inlet_f=environment.inlet_f)


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
    (``CirculationParams.run_gap_min``), so the zone draws and the book's
    loss see the same runs wherever a walk is cut."""
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
#: Draws opened a gap that closes on that prior, not a fitted constant:
#: under no draws it only shapes how an existing gap closes.
TAU_GAP_PRIOR = "tau_gap_prior"


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
    physics_usable: bool | None = None,
) -> TankPhysics:
    tau = params.tank.stratification_gap_tau_h
    if tau is None:
        tau = TAU_GAP_PRIOR_H
        defaults.append(f"stratification_gap_tau_h={tau} (prior)")
    if "humidity" not in environment.model_fields_set:
        defaults.append(f"humidity={environment.humidity}")
    if environment.inlet_f is None:
        defaults.append(f"inlet_f={params.draw.inlet_temp_f}")
    frame = _ambient_frame(environment, start, until)
    flowing: CirculationDraws | None = None
    if circulation is not None:
        # Without terms of its own, the runs take one installation's.
        terms = params.circulation or SITE_CIRCULATION
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
        physics_usable=physics_usable,
        recovery_model=model,
        low_confidence_floor=LOW_CONFIDENCE_FLOOR,
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
    book: Booked | None = None,
    ledger: HeatLedger | None = None,
    tou_windows_in_force: Sequence[tuple[datetime, datetime]] | None = None,
    withheld_windows: Sequence[tuple[datetime, datetime]] = (),
    inlet_measured: bool = False,
    start_hold: Callable[[float | None], float] | None = None,
    running_hold: float = 0.0,
    lead_draws: Sequence[Draw] = (),
    physics_usable: bool | None = None,
) -> SimulationResult:
    """Walk ``scenario`` from its start to its end on ``params``.

    ``recovery`` replaces the physics duration of each heat-pump
    recovery with its own (``extensions.RecoveryModel``). The four
    inputs after it are what such a model was trained with:

    - ``start_hold``: how long a compressor start holds before the lower
      zone climbs, minutes, by the minutes since the compressor last
      stopped (None when not known); None holds none;
    - ``running_hold``: what is left at the start of a running
      compressor's own start's hold, minutes; ignored when it is not
      running;
    - ``lead_draws``: draws recorded before the start, which a
      draw-free model reads as the first recovery's ``draw_load`` when
      it begins within ``engine.DRAW_LEAD`` of them. Like the
      scenario's draws, they need a fitted draw response
      (``draw_model_unsupported``), and those the model reads carry the
      draw and inlet reasons (``draw_uncalibrated``,
      ``inlet_temp_modelled``);
    - ``physics_usable``: whether the physics duration may be served;
      None, when the compressor is calibrated (a positive constant).

    With no model, or one that declines, the served duration adds no
    start hold and the lead draws are not read. The holds still mark
    where the lower zone starts to climb, which placing a recovery again
    after a draw counts from.

    ``book`` is the tank's booked heat at the start (``sim.book``): from
    the caller's own record, or ``book.full_tank_book`` when they know
    the tank has been quiet since a recovery ended. With it, the walk
    carries the book (``book.BookedHeatLedger``): a draw that spends the
    booked heat takes the upper zone below its calibrated response, and
    the delivery and the draw windows read the book. The lower zone
    takes each draw's calibrated response either way. Without it the
    upper zone does too, the delivery is the upper zone's, and
    ``reasons`` says ``no_heat_book``. ``ledger`` is any other
    ``extensions.HeatLedger`` in its place.

    ``inlet_measured``: the scenario's inlet (``Environment.inlet_f``) is
    the mains as measured (``cold_supply``); without it, a scenario with
    draws says ``inlet_temp_modelled``.

    ``withheld_windows`` are spans over which a recovery is credited no
    heat, as the worst case of a draw window's long draws coming first
    (``draw_forecast.draws_first``): the engine runs a recovery out
    uncredited over them, and the book holds them back.

    ``tou_windows_in_force`` are the TOU windows the heater keeps, in
    place of the schedule's (``marked_windows``: the heater's own marker
    over a recovery running now). With TOU on and no periods to lay out,
    ``reasons`` says ``tou_schedule_unknown`` and no window is kept.

    Raises ``engine.SimulationError`` when the walk cannot be completed,
    and for draws, the scenario's or ``lead_draws``, on parameters with
    no fitted draw response (``draw_model_unsupported``).
    """
    s = scenario
    _check_setpoints(s)
    _check_draws(params, [*s.loads.draws, *lead_draws])
    book = _at_the_inlet(book, s.environment)
    tz = ZoneInfo(s.tz)
    reasons: list[str] = []
    defaults: list[str] = []
    if s.loads.draws and _gap_prior(params):
        reasons.append(TAU_GAP_PRIOR)
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
        # Recorded draws before the start move the tank as the
        # scenario's own do: the model's load is what they took off it.
        draws_on=bool(s.loads.draws or lead_draws),
        model=recovery,
        defaults=defaults,
        circulation=circulation,
        physics_usable=physics_usable,
    )
    tou_on = (
        s.commands.tou_enabled
        if s.commands.tou_enabled is not None
        else s.schedules.tou_enabled
    )
    switches = s.schedules.tou_switches
    windows: tuple[tuple[datetime, datetime], ...] = (
        tuple(
            while_enabled(
                tou_windows(s.schedules.tou_periods, tz, s.start, s.until),
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
    mode, disabled = _engine_mode(s.settings.mode)
    if s.settings.hp_lower_on_f is None:
        defaults.append("hp_lower_on_f=None (no lower-zone start)")
        # The lower trigger was never searched; the TOU-opening one was.
        reasons.append(HP_LOWER_ON_UNKNOWN)
    _history_defaults(s.state, s.history, defaults)
    entries = _entries(s, tz, reasons)
    raw = _raw_writes(s, reasons)
    if ledger is None and book is not None:
        # As the walk's runs take them (``_physics``).
        terms = params.circulation or SITE_CIRCULATION
        ledger = BookedHeatLedger(
            book,
            physics.ambient.at,
            params.book_terms(),
            line_f=params.readiness.line_f,
            fall_f_per_gal=params.readiness.fall_f_per_gal,
            withheld=sorted(withheld_windows),
            extra=(
                CirculationLoss(
                    # The runs as given: a gap merged into a run
                    # circulates nothing.
                    [(r.start, r.end) for r in s.loads.circulation or ()],
                    terms.flow_gpm,
                    terms.loss_btu_per_gal,
                    circuit_gal=terms.book_circuit_gal,
                    # The tank's upper zone over the projection, as the
                    # heater holds it.
                    upper_f=s.settings.setpoint_f,
                    air_at=physics.ambient.at,
                    gap=circulation.gap,
                )
                if circulation is not None
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
        # A start-up's energy is the COP fit's: without one, none.
        startup_wh=(
            params.power.startup_wh
            if params.power.cop_scale is not None
            else None
        ),
        element_running=s.state.element_running,
        element_running_since=s.state.element_running_since,
        raw_writes=raw,
        stopped_at=s.history.compressor_stopped_at,
        heated_at=s.history.heated_at,
        ledger=ledger,
        controller=params.controller,
        withheld_windows=sorted(withheld_windows),
        start_hold=start_hold,
        running_hold=running_hold,
        lead_draws=[(d.at, d.gallons) for d in lead_draws],
    )
    walked = (
        ledger.walk(sim.points, sim.heating, draws)
        if isinstance(ledger, BookedHeatLedger)
        else None
    )
    delivery = delivery_along(
        sim.points, draws, walked, params.readiness, params.book_terms()
    )
    # Lead draws the model read are priced as the scenario's own are.
    lead_read = recovery is not None and _lead_read(
        sim.heating, lead_draws, s.start
    )
    if lead_read and not s.loads.draws and not inlet_measured:
        reasons.append("inlet_temp_modelled")
    out_of_domain_at: datetime | None = None
    if draws:
        any_out, out_of_domain_at = draw_domain_judgement(
            params.draw,
            [(p.at, p.upper_f) for p in sim.points],
            _largest_draw(s.loads.draws),
        )
        if any_out:
            reasons.append("draw_out_of_domain")
    reasons += _unfitted(params, "standby")
    if s.loads.draws or lead_read:
        reasons += _unfitted(params, "draw")
    if s.loads.windows:
        reasons += _unfitted(params, "book", "readiness")
    if physics.failed_recoveries:
        # The integrator raised on a recovery the walk then went without.
        reasons.append("physics_failed")
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
                booked=walked,
                band_btu=(
                    book.error_band_btu(params.book_terms())
                    if book is not None and book.aged(params.book_terms())
                    else 0.0
                ),
                p=params.readiness,
                ep=params.book_terms(),
                forecast=[
                    (w.expected_count, w.draws_until) for w in s.loads.windows
                ],
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
    Without it, the tank's heat as its two probes place it
    (``delivery.probes_gal``, ``probes``), or the evidence in
    ``params.readiness.evidence`` (none by default) where it shows more
    (``evidence``).
    """
    if book is not None:
        return booked_deliverable(
            book,
            state.upper_f,
            state.lower_f,
            params.readiness,
            params.book_terms(),
        )
    return deliverable(
        state.upper_f, state.lower_f, params.readiness, ep=params.book_terms()
    )


#: The reason each unfitted term group (``HeaterParams.unfitted``) adds
#: to an answer it reaches: a failed fit never reads as a fitted one.
UNFITTED_REASONS: Mapping[str, str] = MappingProxyType(
    {
        "compressor": "physics_uncalibrated",
        "power": "energy_uncalibrated",
        "standby": "standby_uncalibrated",
        "book": "book_uncalibrated",
        "readiness": "readiness_uncalibrated",
        "draw": "draw_uncalibrated",
    }
)


def _unfitted(params: HeaterParams, *terms: str) -> list[str]:
    """The reasons for those of ``terms`` the parameters did not fit."""
    return [UNFITTED_REASONS[t] for t in params.unfitted if t in terms]


def _lead_read(
    heating: Sequence[HeatingInterval],
    lead_draws: Sequence[Draw],
    start: datetime,
) -> bool:
    """Whether the walk's first heat-pump recovery read any of
    ``lead_draws`` as its draw load: one before ``start`` and within
    ``DRAW_LEAD`` of the recovery's start (``engine._lead_load``)."""
    first = next(
        (h.start.at for h in heating if h.source == "compressor"), None
    )
    return first is not None and any(
        first - DRAW_LEAD <= d.at < start for d in lead_draws
    )


def _gap_prior(params: HeaterParams) -> bool:
    """Whether the gap constant is a prior, not this heater's fit."""
    return (
        params.tank.stratification_gap_tau_h is None
        or "gap_tau" in params.unfitted
    )


def _refusal(physics: PhysicsRecovery) -> SimulationError:
    """Why a recovery could not be served: the integration hitting its
    bound (a weak fit, or very cold air) is told apart from no usable
    physics at all."""
    if physics.truncated:
        return SimulationError(
            "the recovery could not be computed: the physics integration "
            f"hit its {MAX_MINUTES:.0f}-min bound short of the target"
        )
    return SimulationError("the recovery could not be computed")


def _check_draws(params: HeaterParams, draws: Sequence[Draw]) -> None:
    """Refuse draws the parameters cannot move the tank for: without a
    fitted draw response (``DrawParams.observability``) a draw would
    leave the tank as it was, an answer that looks like one."""
    if draws and params.draw.observability is None:
        raise SimulationError(
            "draw_model_unsupported: draws were given, and the "
            "parameters have no fitted draw response "
            "(DrawParams.observability)"
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
    Draws with no fitted draw response raise ``engine.SimulationError``
    (``draw_model_unsupported``)."""
    start, until = _instant(start), _instant(until)
    if until <= start:
        raise ValueError("until must be after start")
    _check_draws(params, [d for d in loads.draws if start <= d.at < until])
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
        circulation=_circulation(loads, params),
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
            _largest_draw([d for d in loads.draws if start <= d.at < until]),
        )
        if any_out:
            reasons.append("draw_out_of_domain")
        if _gap_prior(params):
            reasons.append(TAU_GAP_PRIOR)
    starts_at = trigger = None
    held = False
    margin: float | None = None
    if settings is not None:
        on = settings.hp_lower_on_f
        if on is None:
            reasons.append(HP_LOWER_ON_UNKNOWN)
        last = coast.points[-1]
        margin = None if on is None else last.lower_f - on
        mode, disabled = _engine_mode(settings.mode)
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
                -math.inf if on is None else on,
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
    reasons += _unfitted(params, "standby")
    if any(start <= d.at < until for d in loads.draws):
        reasons += _unfitted(params, "draw")
    if _circulation_unknown(params, loads, until):
        reasons.append(CIRCULATION_UNKNOWN)
    flowing = physics.flowing_draws
    circulating = isinstance(flowing, CirculationDraws)
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
            flowing.minutes if isinstance(flowing, CirculationDraws) else None
        ),
        circulation_heat_wh=(
            coast.flowing_heat_btu / BTU_PER_WH if circulating else None
        ),
        ambient_mean_f=coast.ambient_mean_f,
        hours=(until - start).total_seconds() / 3600.0,
    )


def element_mode(
    state: HeaterState,
    settings: Settings,
    params: HeaterParams,
    *,
    mode: int,
    at: datetime,
    setpoint_f: float | None = None,
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

    ``setpoint_f`` is a setpoint to project to instead of the heater's
    (``settings.setpoint_f``), which still decides the TOU-window test:
    a what-if setpoint of 108 °F must not make a resting heater read as
    inside a window.

    ``ready_upper_f`` is an upper-zone temperature that counts as ready;
    ``hp_lower_minutes``, in High Demand and Energy Saver, the
    heat pump's minutes for the lower zone (``recovery`` gives them);
    ``switch_back_after_minutes`` ends the stint early. ``reachable``
    says whether a mode write can take at ``at``: not while heating is
    disabled, nor inside a TOU window, by the heater's own marker
    (``tou_marked``). An unknown marker counts as in force: the
    conservative direction is "do not count on it"."""
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
        settings.setpoint_f if setpoint_f is None else setpoint_f,
        ready_upper_f=ready_upper_f,
        hp_lower_minutes=hp_lower_minutes,
        switch_back_after_minutes=switch_back_after_minutes,
        slot_minutes=slot_minutes,
        params=params.element,
    )
    _, disabled = _engine_mode(settings.mode)
    reason: str | None = None
    # The heater's own marker decides, at its own setpoint; unknown
    # counts as in force.
    if disabled:
        reason = "heating_disabled"
    elif tou_marked(settings) is not False:
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
        return float(a) if math.isfinite(a) else DEFAULT_AMBIENT_F
    sampler = AmbientSampler(
        pd.DataFrame(
            {"ambient_f": [v for _, v in a]},
            index=pd.DatetimeIndex([t for t, _ in a]),
        )
    )
    return sampler.at(at)


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


def _coast_loss(
    s: Scenario, params: HeaterParams, start: datetime, air: float
) -> tuple[float, float]:
    """What the tank loses coasting from now to ``start``, in the book's
    frame: standby to the air now (the book's own term), the heat
    circulation's runs take over exactly the coast, and the delivered
    gallons drawn on it, which the book takes through the valve and puts
    back cold."""
    now = s.start
    if start <= now:
        return 0.0, 0.0
    hours = (start - now).total_seconds() / 3600.0
    lost = standby_btu(
        hours, s.state.upper_f, s.state.lower_f, air, params.book_terms()
    )
    to_start = standby(
        s.state,
        s.environment,
        s.loads,
        params,
        start=now,
        until=start,
        history=s.history,
    )
    circulated = (to_start.circulation_heat_wh or 0.0) * BTU_PER_WH
    return lost + circulated, to_start.draw_volume_gal or 0.0


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
    from the tank there (``forecast``: to the heater's stop threshold),
    with the TOU cap judged where it ends (``_tou_capped``).
    ``recovery`` serves its duration (``extensions.RecoveryModel``).
    ``not_scheduled`` while heating is disabled; ``unavailable`` when
    it cannot be computed.

    The coast's loss, in the book's frame, is standby to the air now,
    the heat circulation takes over the coast, and the draws before the
    start; the recovery's heat into the book is the book's compressor
    term by the air now."""
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
            # The household's expected draws cool the tank to its
            # trigger; quiet only when they cannot be modelled.
            loads = (
                s.loads
                if params.draw.observability is not None
                else s.loads.model_copy(update={"draws": ()})
            )
            coast = standby(
                s.state,
                s.environment,
                loads,
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
            state = _coast_state(s.state, now, coast.points, start)
            if state is None:
                return Recovery("unavailable")
            upper, lower = state
            coast_btu, coast_gal = _coast_loss(
                s.model_copy(update={"loads": loads}), params, start, air
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
        coast_btu=coast_btu,
        coast_draw_gal=coast_gal,
        hp_btu_per_h=hp_btu_per_h(air, bp),
        trajectory=tuple(trajectory),
        startup_energy_wh=answer.startup_energy_wh,
    )


def _coast_state(
    state: HeaterState,
    now: datetime,
    points: Sequence[Point],
    at: datetime,
) -> tuple[float, float] | None:
    """The tank at ``at`` along a coast from ``state`` at ``now``,
    linear between its points."""
    path = [(now, state.upper_f, state.lower_f)] + [
        (p.at, p.upper_f, p.lower_f) for p in points
    ]
    for (t0, u0, l0), (t1, u1, l1) in itertools.pairwise(path):
        if t0 <= at <= t1:
            span = (t1 - t0).total_seconds()
            f = 0.0 if span <= 0 else (at - t0).total_seconds() / span
            return u0 + (u1 - u0) * f, l0 + (l1 - l0) * f
    if at <= path[0][0]:
        return path[0][1], path[0][2]
    return None


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


#: The share of a book's steps that measured the inlet for its
#: conversion to count as measured.
INLET_MEASURED_SHARE = 0.9


def time_to_ready(
    scenario: Scenario,
    params: HeaterParams,
    *,
    book: Booked | None = None,
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

    ``book`` is the tank's booked heat now, as for ``simulate``;
    without it the answer is the probes' or the evidence's.
    ``bath_gal`` and ``shower_gal`` default to
    ``ReadinessParams.bath_gal`` and ``shower_gal``, named in
    ``defaults_used`` and in ``reasons`` (``bath_volume_inferred``,
    ``shower_volume_default``). ``shower_from_forecast``: the
    ``shower_gal`` given is a draw forecast's
    (``draw_forecast.shower_gal``). ``drawing``: water is being drawn
    now.
    ``inlet_measured``: the book converts heat to gallons at an inlet
    measured at the mains (a probe's plateau over a long draw); without
    it, or a book whose steps measured the inlet at least
    ``INLET_MEASURED_SHARE`` of the time, a booked answer says
    ``inlet_temp_modelled``. The
    recovery is the next one (``next_recovery``), its duration served
    by ``recovery`` when given (``extensions.RecoveryModel``) and by
    physics alone otherwise, which runs short on long recoveries (the
    simulator explanation's *Accuracy*).
    """
    s = scenario
    p = params.readiness
    book = _at_the_inlet(book, s.environment)
    defaults: list[str] = []
    bath_source: Literal["configured", "request"] = "request"
    if bath_gal is None:
        bath_gal = p.bath_gal
        bath_source = "configured"
        defaults.append(f"bath_gal={bath_gal}")
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
    now_gal = (
        booked_deliverable(
            book, tank.upper_f, tank.lower_f, p, params.book_terms()
        )
        if book is not None
        else deliverable(tank.upper_f, tank.lower_f, p, ep=params.book_terms())
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
        bath_source=bath_source,
        shower_gal=shower_gal,
        shower_source=shower_source,
        valid_s=0.0,
        setpoint_f=s.settings.setpoint_f,
        booked=book,
        inlet_measured=book is not None
        and (
            inlet_measured
            # The book's own measured share, only while its own inlet
            # converts: a scenario's inlet replaces it (``_at_the_inlet``).
            or (
                s.environment.inlet_f is None
                and book.inlet_measured_share >= INLET_MEASURED_SHARE
            )
        ),
        params=p,
        element_params=params.element,
        book_params=params.book_terms(),
    )
    # The gallons now rest on the book's and readiness's terms whether
    # or not a recovery was needed; the rest only on the recovery.
    answer["reasons"] = _unique(
        [
            *answer["reasons"],
            *_unfitted(params, "book", "readiness"),
            *_ambient_reasons(s.environment),
        ]
    )
    if nxt.outcome == "ok":
        answer["reasons"] = _unique(
            [
                *answer["reasons"],
                *_unfitted(params, "compressor", "power", "standby"),
                *(_unfitted(params, "draw") if s.loads.draws else []),
                *(
                    [CIRCULATION_UNKNOWN]
                    if _circulation_unknown(
                        params, s.loads, s.start + TRIGGER_HORIZON
                    )
                    else []
                ),
            ]
        )
    return typed(answer, s.start, nxt, defaults)


# ── ready by a time ─────────────────────────────────────────────────

#: How far ahead a forecast's target may be: the coast walks 10-minute
#: steps to it.
FORECAST_HORIZON = timedelta(hours=168)
#: The fixed point's passes, start against the coast to it.
_FORECAST_PASSES = 3
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
    the recovery runs from there to the lower zone's target, and the
    start is refined to ``target_time`` less that duration, to a fixed
    point, the tank at the start projected to exactly it.

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
            startup_energy_wh=None,
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

    def coast_to(when: datetime) -> tuple[float, float, float | None]:
        """The tank coasted to ``when``, and the mean air over it."""
        coast = physics.coast(
            origin,
            state.upper_f,
            state.lower_f,
            when,
            [],
            heated_at=history.heated_at,
        )
        last = coast.points[-1]
        return last.upper_f, last.lower_f, coast.ambient_mean_f

    def predict(when: datetime, heat_minutes: float) -> Any:
        upper, lower, coast_air = coast_to(when)
        amb = physics.ambient.at(when)
        mean = ambient_window_mean(
            physics.series, when, when + timedelta(minutes=heat_minutes)
        )
        # No air sample inside the recovery's window (the first pass's
        # is an instant): the coast's mean, as the forecast's was.
        fallback = coast_air if coast_air is not None else amb
        t_amb_mean = mean if mean is not None else fallback
        ctx = RecoveryContext(
            t_start_lower=lower,
            t_start_upper=upper,
            target_f=goal,
            t_amb_start=amb,
            t_amb_mean=t_amb_mean,
            h_amb_start=environment.humidity,
            start_hold_minutes=0.0,
            draw_load=0.0,
            physics=physics_recovery(
                t_start_lower=lower,
                t_start_upper=upper,
                target_f=goal,
                t_amb_mean=t_amb_mean,
                h_amb_start=environment.humidity,
                compressor=params.compressor,
                loss=params.loss,
                usable=physics.physics_usable,
                record_path=True,
                tank=params.tank,
            ),
        )
        return serve_recovery(ctx, model=model), (upper, lower), ctx.physics

    served, tank, integrated = predict(target, 0.0)
    if served is None:
        raise _refusal(integrated)
    decayed_to = target
    for _ in range(_FORECAST_PASSES):
        when = max(compute_start_time(target, served.minutes), origin)
        if when >= target:
            break
        refined, refined_tank, _ = predict(when, served.minutes)
        if refined is None:
            break
        converged = abs(refined.minutes - served.minutes) <= REFINE_TOL_MINUTES
        served, tank, decayed_to = refined, refined_tank, when
        if converged:
            break
    start_at = compute_start_time(target, served.minutes)
    feasible = start_at >= origin
    shortfall: float | None = None
    ready_at = target
    if not feasible:
        shortfall = (origin - start_at).total_seconds() / 60.0
        start_at = origin
        ready_at = origin + timedelta(minutes=served.minutes)
    if decayed_to != start_at:
        tank = coast_to(start_at)[:2]
    upper_s, lower_s = tank
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
    power = params.power
    trajectory: tuple[HeatingPoint, ...] | None = None
    if scheduled_start is not None and served.path is not None:
        trajectory = tuple(
            build_heating_trajectory(
                served.path,
                served_minutes=served.minutes,
                start_at=scheduled_start,
                t_upper_start=upper_s,
                t_lower_start=lower_s,
                two_zone=params.compressor.two_zone,
                power_scale=power.power_scale,
                cop_scale=power.cop_scale,
                cop_lift_coeff=power.cop_lift_coeff,
                cop_lift_ref_f=power.cop_lift_ref_f,
                t_amb=served.context.t_amb_mean,
                hold_minutes=served.start_hold_minutes,
                tank=params.tank,
            )
        )
    startup: float | None = None
    if trajectory is not None and power.cop_scale is not None:
        startup = power.startup_wh
        if scheduled_start is not None and (
            scheduled_start <= origin and state.compressor_running
        ):
            startup = 0.0
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
        startup_energy_wh=startup,
        reasons=tuple(
            _unique(
                [
                    *served.reasons,
                    *_unfitted(params, "compressor", "power", "standby"),
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
    evaporator_f: float | None = None,
    model: RecoveryModel | None = None,
) -> ActiveCycle:
    """What is left of the recovery the compressor is running at
    ``at``: the lower zone from where it is to its target
    (``Settings.hp_lower_off_f``, else the setpoint), at the air now,
    served by ``model`` when given. Beside it, the integrator's own
    remaining time, with ``evaporator_f`` (the coil's live reading,
    ``sim_adapters.evaporator_f``) in place of its approach estimate:
    the coil is cooled by the running refrigerant, so it is the
    operating point. A truncated integration says
    ``physics_truncated``. A lower zone already at its target has
    nothing left: 0 minutes, ready now."""
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
    # As the core's: a positive compressor constant is calibrated.
    usable = params.compressor.compressor_constant > 0.0
    if state.lower_f >= goal:
        # The cycle is at its end: the lower zone has reached the target
        # and the compressor is about to stop. Nothing is left, as the
        # integrator says (0 minutes).
        return ActiveCycle(
            status="heating",
            ready_at=at,
            remaining_minutes=0.0,
            physics_remaining_minutes=0.0 if usable else None,
            lower_f=state.lower_f,
            target_f=goal,
            confidence=1.0,
            defaults_used=tuple(defaults),
        )
    ctx = RecoveryContext(
        t_start_lower=state.lower_f,
        t_start_upper=state.upper_f,
        target_f=goal,
        t_amb_start=air,
        # The cycle is under way: the air now stands for its mean.
        t_amb_mean=air,
        h_amb_start=environment.humidity,
        start_hold_minutes=0.0,
        draw_load=0.0,
        physics=physics_recovery(
            t_start_lower=state.lower_f,
            t_start_upper=state.upper_f,
            target_f=goal,
            t_amb_mean=air,
            h_amb_start=environment.humidity,
            compressor=params.compressor,
            loss=params.loss,
            usable=usable,
            tank=params.tank,
        ),
    )
    served = serve_recovery(ctx, model=model)
    if served is None:
        raise _refusal(ctx.physics)
    reasons = list(served.reasons)
    physics_minutes: float | None = None
    if usable:
        try:
            result = predict_physics_detailed(
                t_start_lower=state.lower_f,
                hp_lower_off=goal,
                t_amb_mean=air,
                compressor_constant=params.compressor.compressor_constant,
                evap_approach_f=params.compressor.evap_approach_f,
                compressor=params.compressor,
                loss=params.loss,
                h_amb_start=environment.humidity,
                t_evap_override=evaporator_f,
                ua_btu_hr_f=params.loss.ua_btu_hr_f,
                ua_exponent=params.loss.ua_exponent,
                ua_ref_delta_t=params.loss.ua_ref_delta_t_f,
                stratification_gap=state.upper_f - state.lower_f,
                two_zone=params.compressor.two_zone,
                tank=params.tank,
            )
            if not math.isnan(result.minutes):
                physics_minutes = result.minutes
            if not result.converged:
                reasons.append(PHYSICS_TRUNCATED)
        except Exception:
            physics_minutes = None
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
                    *_unfitted(params, "compressor", "standby"),
                    *_ambient_reasons(environment),
                ]
            )
        ),
        defaults_used=tuple(defaults),
    )
