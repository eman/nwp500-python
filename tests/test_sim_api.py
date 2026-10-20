"""The simulator's entry points (``nwp500.sim.simulate``, ``recovery``
and ``standby``).

``simulate`` is held to the engine: each scenario below walks exactly as
the engine does when called by hand with the inputs the scenario stands
for (the TOU windows its periods define, its reservations as entries,
its modes by the engine's names), so the facade adds nothing to the
walk but the translation.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from nwp500.sim import (  # noqa: E402
    Commands,
    Draw,
    Environment,
    HeaterState,
    History,
    Loads,
    ReservationEntry,
    Scenario,
    Schedules,
    Settings,
    TouPeriod,
    Write,
    default_params,
    recovery,
    simulate,
    standby,
)
from nwp500.sim.api import LOW_CONFIDENCE_FLOOR  # noqa: E402
from nwp500.sim.engine import (  # noqa: E402
    Entry,
    Heater,
    RawWrite,
    SimulationError,
)
from nwp500.sim.engine import simulate as walk  # noqa: E402
from nwp500.sim.extensions import RecoveryModel  # noqa: E402
from nwp500.sim.heat_pump_recovery import (  # noqa: E402
    ModelDuration,
    RecoveryContext,
)
from nwp500.sim.params import HeaterParams  # noqa: E402
from nwp500.sim.tank_physics import TankPhysics  # noqa: E402

T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
AMBIENT_F = 68.0
EVERY_DAY = 254


def at(h: float) -> datetime:
    return T0 + timedelta(hours=h)


def _peak(opens: int, closes: int) -> tuple[TouPeriod, ...]:
    """TOU periods whose peak runs ``opens``:00 to ``closes``:00 UTC,
    across midnight."""
    return (
        TouPeriod(
            season=4095,
            week=EVERY_DAY,
            start_hour=0,
            start_minute=0,
            end_hour=closes - 1,
            end_minute=59,
            price_max=5,
        ),
        TouPeriod(
            season=4095,
            week=EVERY_DAY,
            start_hour=closes,
            start_minute=0,
            end_hour=opens - 1,
            end_minute=59,
            price_max=1,
        ),
        TouPeriod(
            season=4095,
            week=EVERY_DAY,
            start_hour=opens,
            start_minute=0,
            end_hour=23,
            end_minute=59,
            price_max=5,
        ),
    )


#: The window ``_peak(23, 4)`` defines over the walks below.
WINDOW = ((at(4.0), at(9.0)),)


def _scenario(**kw: Any) -> Scenario:
    base: dict[str, Any] = {
        "start": T0,
        "horizon": timedelta(hours=12),
        "tz": "UTC",
        "state": HeaterState(upper_f=128.0, lower_f=112.0),
        "settings": Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
        "history": History(compressor_stopped_at=at(-2.0), heated_at=at(-2.0)),
        "environment": Environment(ambient_f=AMBIENT_F, humidity=48.0),
    }
    base.update(kw)
    return Scenario(**base)


def _by_hand(
    params: HeaterParams,
    s: Scenario,
    *,
    model: RecoveryModel | None = None,
    physics_usable: bool | None = None,
    draws_on: bool | None = None,
    **kw: Any,
) -> Any:
    """The engine called directly with what ``s`` stands for: a flat
    ambient on an hourly grid (any grid gives a flat ambient)."""
    stamps = pd.date_range(at(-2), s.until + timedelta(hours=24), freq="1h")
    frame = pd.DataFrame({"ambient_f": [AMBIENT_F] * len(stamps)}, index=stamps)
    physics = TankPhysics(
        params,
        frame,
        s.environment.humidity,
        draws_on=bool(s.loads.draws) if draws_on is None else draws_on,
        tau_gap_hours=params.tank.stratification_gap_tau_h,  # type: ignore[arg-type]
        physics_usable=physics_usable,
        recovery_model=model,
        low_confidence_floor=LOW_CONFIDENCE_FLOOR,
    )
    heater = kw.pop(
        "heater",
        Heater(hp_lower_on_f=105.0, element=params.element),
    )
    return walk(
        start=s.start,
        upper_f=s.state.upper_f,
        lower_f=s.state.lower_f,
        running=s.state.compressor_running,
        until=s.until,
        setpoint_f=s.settings.setpoint_f,
        heater=heater,
        physics=physics,
        startup_wh=params.power.startup_wh,
        stopped_at=s.history.compressor_stopped_at,
        heated_at=s.history.heated_at,
        controller=params.controller,
        **kw,
    )


@pytest.fixture(scope="module")
def params() -> HeaterParams:
    return default_params()


class TestSimulateIsTheEngine:
    def test_a_coast_into_the_tou_window(self, params: HeaterParams) -> None:
        s = _scenario(
            state=HeaterState(upper_f=125.0, lower_f=118.6),
            schedules=Schedules(tou_periods=_peak(23, 4), tou_enabled=True),
        )
        got = simulate(s, params).simulation
        want = _by_hand(
            params,
            s,
            heater=Heater(
                hp_lower_on_f=105.0, tou_windows=WINDOW, element=params.element
            ),
        )
        assert got == want
        assert got.heating

    def test_tou_off_has_no_window(self, params: HeaterParams) -> None:
        s = _scenario(schedules=Schedules(tou_periods=_peak(23, 4)))
        assert simulate(s, params).simulation == _by_hand(params, s)

    def test_the_commands_switch_tou_on(self, params: HeaterParams) -> None:
        s = _scenario(
            schedules=Schedules(tou_periods=_peak(23, 4)),
            commands=Commands(tou_enabled=True),
        )
        want = _by_hand(
            params,
            s,
            heater=Heater(
                hp_lower_on_f=105.0, tou_windows=WINDOW, element=params.element
            ),
        )
        assert simulate(s, params).simulation == want

    def test_reservations_through_every_mode(
        self, params: HeaterParams
    ) -> None:
        # (hour, minute, device mode, setpoint in half-degrees C)
        rows = [(19, 30, 3, 124), (20, 30, 4, 124), (21, 30, 2, 124)]
        rows += [(22, 30, 1, 121)]
        s = _scenario(
            schedules=Schedules(
                reservations=tuple(
                    ReservationEntry(
                        week=EVERY_DAY,
                        hour=h,
                        minute=m,
                        mode=mode,
                        setpoint_half_c=sp,
                    )
                    for h, m, mode, sp in rows
                )
            )
        )
        names = {1: "heat_pump", 2: "electric", 3: "energy_saver"}
        names[4] = "high_demand"
        fahrenheit = {124: 62.0 * 9 / 5 + 32, 121: 60.5 * 9 / 5 + 32}
        entries = [
            Entry(
                T0.replace(hour=h, minute=m),
                names[mode],  # type: ignore[arg-type]
                fahrenheit[sp],
                T0,
                f"reservation-{i}",
            )
            for i, (h, m, mode, sp) in enumerate(rows)
        ]
        got = simulate(s, params)
        assert got.simulation == _by_hand(params, s, entries=entries)
        assert {m.mode for m in got.modes} == {
            "heat_pump",
            "energy_saver",
            "high_demand",
            "electric",
        }

    def test_an_entry_turns_a_powered_off_heater_on(
        self, params: HeaterParams
    ) -> None:
        """Powered off, an entry fires and the heater heats after it (two
        device runs, 2026-09-24); in Vacation the same entry is skipped."""
        e = ReservationEntry(
            week=EVERY_DAY, hour=20, minute=0, mode=1, setpoint_half_c=124
        )

        def run(mode: int) -> Any:
            return simulate(
                _scenario(
                    state=HeaterState(upper_f=110.0, lower_f=95.0),
                    settings=Settings(
                        setpoint_f=140.9, mode=mode, hp_lower_on_f=105.0
                    ),
                    schedules=Schedules(reservations=(e,)),
                ),
                params,
            )

        off = run(6)
        assert off.heating
        assert off.heating[0].start.at >= T0.replace(hour=20)
        assert "powered_on_by_entry" in off.reasons
        assert not run(5).heating

    @pytest.mark.parametrize("mode", [0, 5, 6])
    def test_an_entry_outside_1_to_4_is_not_modelled(
        self, params: HeaterParams, mode: int
    ) -> None:
        """Entry modes are ``ReservationMode`` ids: 5 is Power Off and 0 an
        unused slot; 6 is what earlier library versions wrote for Power
        Off. None is modelled, and each says so."""
        e = ReservationEntry(
            week=EVERY_DAY, hour=20, minute=0, mode=mode, setpoint_half_c=124
        )
        s = _scenario(schedules=Schedules(reservations=(e,)))
        got = simulate(s, params)
        assert "reservation_mode_not_modelled" in got.reasons
        assert got.simulation == _by_hand(params, s)

    def test_a_disabled_reservation_schedule_is_not_walked(
        self, params: HeaterParams
    ) -> None:
        e = ReservationEntry(
            week=EVERY_DAY, hour=20, minute=0, mode=3, setpoint_half_c=124
        )
        s = _scenario(
            schedules=Schedules(reservations=(e,), reservations_enabled=False)
        )
        assert simulate(s, params).simulation == _by_hand(params, s)

    def test_writes_and_an_element_running(self, params: HeaterParams) -> None:
        s = _scenario(
            state=HeaterState(
                upper_f=103.9,
                lower_f=98.0,
                element_running=True,
                element_running_since=at(-0.05),
            ),
            settings=Settings(setpoint_f=140.9, mode=3, hp_lower_on_f=105.0),
            history=History(compressor_stopped_at=at(-1.0)),
            commands=Commands(
                writes=(
                    Write(at=at(0.75), setpoint_f=137.3, id="lower"),
                    Write(at=at(1.5), mode=4, id="hd"),
                    Write(at=at(4.5), mode=1, setpoint_f=140.9, id="back"),
                )
            ),
        )
        want = _by_hand(
            params,
            s,
            heater=Heater(
                hp_lower_on_f=105.0, mode="energy_saver", element=params.element
            ),
            element_running=True,
            element_running_since=at(-0.05),
            raw_writes=[
                RawWrite(at(0.75), setpoint_f=137.3, id="lower"),
                RawWrite(at(1.5), mode="high_demand", id="hd"),
                RawWrite(
                    at(4.5), mode="heat_pump", setpoint_f=140.9, id="back"
                ),
            ],
        )
        got = simulate(s, params).simulation
        assert got == want
        assert "element" in {h.source for h in got.heating}

    def test_draws(self, params: HeaterParams) -> None:
        showers = tuple(
            Draw(at=at(0.4) + timedelta(minutes=i), gallons=1.6)
            for i in range(8)
        )
        s = _scenario(loads=Loads(draws=showers))
        want = _by_hand(params, s, draws=[(d.at, d.gallons) for d in showers])
        assert simulate(s, params).simulation == want

    def test_vacation_starts_no_heating(self, params: HeaterParams) -> None:
        s = _scenario(
            state=HeaterState(upper_f=110.0, lower_f=95.0),
            settings=Settings(setpoint_f=140.9, mode=5, hp_lower_on_f=105.0),
        )
        got = simulate(s, params)
        want = _by_hand(
            params,
            s,
            heater=Heater(
                hp_lower_on_f=105.0,
                heating_disabled=True,
                element=params.element,
            ),
        )
        assert got.simulation == want
        assert not got.heating


class _Model:
    """A model that uses what it is given: the physics' minutes, longer
    by half again per unit of draw load, plus the start's hold. It keeps
    every context it was asked about."""

    def __init__(self) -> None:
        self.asked: list[RecoveryContext] = []

    def duration(self, ctx: RecoveryContext) -> ModelDuration:
        self.asked.append(ctx)
        hold = ctx.start_hold_minutes
        return ModelDuration(
            minutes=ctx.physics.minutes * (1.0 + 0.5 * ctx.draw_load) + hold,
            start_hold_minutes=hold,
            confidence=0.9,
            reasons=() if ctx.physics.estimate is not None else ("unusable",),
        )


def _hold(gap: float | None) -> float:
    """A start's hold, minutes: a sixth of the gap since the last stop,
    at most 30 (unknown: 30)."""
    return 30.0 if gap is None else min(gap / 6.0, 30.0)


#: A tank whose lower zone is below the start threshold: a start at T0.
COLD = HeaterState(upper_f=128.0, lower_f=100.0)
#: Two draws in the ``DRAW_LEAD`` before T0, and one before it.
LEAD = (Draw(at=at(-0.25), gallons=6.0), Draw(at=at(-0.1), gallons=4.0))
EARLY = Draw(at=at(-1.0), gallons=8.0)


class TestAModelsInputs:
    """Each of a model's inputs reaches the engine as given: the walk is
    the engine's called by hand with it, and differs from the walk
    without it."""

    def _both(
        self, params: HeaterParams, s: Scenario, **kw: Any
    ) -> tuple[Any, Any, _Model]:
        model = _Model()
        got = simulate(s, params, recovery=model, **kw).simulation
        usable = kw.pop("physics_usable", None)
        lead = kw.pop("lead_draws", ())
        want = _by_hand(
            params,
            s,
            model=_Model(),
            physics_usable=usable,
            draws_on=bool(s.loads.draws or lead),
            lead_draws=[(d.at, d.gallons) for d in lead],
            draws=[(d.at, d.gallons) for d in s.loads.draws],
            **kw,
        )
        return got, want, model

    def test_none_given_is_the_engines_defaults(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(state=COLD)
        got, want, model = self._both(params, s)
        assert got == want
        assert model.asked
        assert all(c.start_hold_minutes == 0.0 for c in model.asked)
        assert all(c.draw_load == 0.0 for c in model.asked)

    def test_the_start_hold(self, params: HeaterParams) -> None:
        s = _scenario(state=COLD)
        got, want, model = self._both(params, s, start_hold=_hold)
        assert got == want
        # Stopped two hours before: a 20-minute hold.
        assert model.asked[0].start_hold_minutes == pytest.approx(20.0)
        assert got != simulate(s, params, recovery=_Model()).simulation

    def test_a_running_compressors_hold(self, params: HeaterParams) -> None:
        s = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            )
        )
        got, want, _ = self._both(params, s, running_hold=15.0)
        assert got == want
        assert got != simulate(s, params, recovery=_Model()).simulation

    def test_lead_draws_are_the_first_recoverys_load(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(state=COLD)
        got, want, model = self._both(
            params, s, lead_draws=(EARLY, *LEAD), draw_hold_factor=0.5
        )
        assert got == want
        assert model.asked[0].draw_load > 0.0
        # Without the draw before the lead, the same load.
        alone = _Model()
        simulate(
            s, params, recovery=alone, lead_draws=LEAD, draw_hold_factor=0.5
        )
        assert alone.asked[0].draw_load == model.asked[0].draw_load

    def test_lead_draws_need_a_hold_factor(self, params: HeaterParams) -> None:
        s = _scenario(state=COLD)
        got, want, model = self._both(params, s, lead_draws=LEAD)
        assert got == want
        assert model.asked[0].draw_load == 0.0

    def test_the_draw_hold_factor(self, params: HeaterParams) -> None:
        s = _scenario(
            state=COLD,
            loads=Loads(draws=(Draw(at=at(0.5), gallons=10.0),)),
        )
        got, want, _ = self._both(params, s, draw_hold_factor=0.5)
        assert got == want
        assert got != simulate(s, params, recovery=_Model()).simulation
        # The physics alone holds for the draw too.
        alone = simulate(s, params, draw_hold_factor=0.5).simulation
        assert alone != simulate(s, params).simulation

    def test_with_no_model_the_holds_change_nothing(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(state=COLD)
        plain = simulate(s, params).simulation
        assert simulate(s, params, start_hold=_hold).simulation == plain
        running = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            )
        )
        assert (
            simulate(running, params, running_hold=15.0).simulation
            == simulate(running, params).simulation
        )

    def test_physics_not_usable(self, params: HeaterParams) -> None:
        s = _scenario(state=COLD)
        got, want, model = self._both(params, s, physics_usable=False)
        assert got == want
        assert all(c.physics.estimate is None for c in model.asked)
        assert "unusable" in got.reasons

    def test_lead_draws_read_carry_the_draw_reasons(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(state=COLD)
        got = simulate(
            s, params, recovery=_Model(), lead_draws=LEAD, draw_hold_factor=0.5
        ).reasons
        assert "draw_uncalibrated" in got
        assert "inlet_temp_modelled" in got
        measured = simulate(
            s,
            params,
            recovery=_Model(),
            lead_draws=LEAD,
            draw_hold_factor=0.5,
            inlet_measured=True,
        ).reasons
        assert "inlet_temp_modelled" not in measured

    @pytest.mark.parametrize(
        "kw",
        [
            # No hold factor: the draws are not read.
            {"recovery": _Model(), "lead_draws": LEAD},
            # No model: nothing reads them.
            {"lead_draws": LEAD, "draw_hold_factor": 0.5},
            # Before the lead: the recovery does not reach back to it.
            {
                "recovery": _Model(),
                "lead_draws": (EARLY,),
                "draw_hold_factor": 0.5,
            },
        ],
    )
    def test_lead_draws_not_read_carry_none(
        self, params: HeaterParams, kw: dict[str, Any]
    ) -> None:
        got = simulate(_scenario(state=COLD), params, **kw).reasons
        assert "draw_uncalibrated" not in got
        assert "inlet_temp_modelled" not in got

    def test_lead_draws_need_a_draw_response(
        self, params: HeaterParams
    ) -> None:
        bare = replace(params, draw=replace(params.draw, observability=None))
        with pytest.raises(SimulationError, match="draw_model_unsupported"):
            simulate(_scenario(state=COLD), bare, lead_draws=LEAD)


class TestWhatTheResultSays:
    def test_defaults_are_named(self, params: HeaterParams) -> None:
        s = _scenario(
            history=History(),
            environment=Environment(ambient_f=AMBIENT_F),
            settings=Settings(setpoint_f=140.9),
        )
        used = simulate(s, params).defaults_used
        assert "humidity=50.0" in used
        assert "inlet_f=72.4" in used
        assert "heated_at=None" in used
        assert any(d.startswith("compressor_stopped_at=None") for d in used)
        assert any(d.startswith("hp_lower_on_f=None") for d in used)

    def test_given_inputs_are_not_defaults(self, params: HeaterParams) -> None:
        s = _scenario(
            environment=Environment(
                ambient_f=AMBIENT_F, humidity=50.0, inlet_f=60.0
            )
        )
        used = simulate(s, params).defaults_used
        assert not [d for d in used if d.startswith(("humidity", "inlet_f"))]

    def test_a_mode_the_engine_does_not_model_is_a_reason(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(
            commands=Commands(writes=(Write(at=at(1.0), mode=6),)),
        )
        assert "write_mode_not_modelled" in simulate(s, params).reasons

    def test_a_write_into_vacation_is_dropped_whole(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(
            commands=Commands(
                writes=(Write(at=at(1.0), mode=5, setpoint_f=120.0),)
            ),
        )
        r = simulate(s, params)
        assert "write_mode_not_modelled" in r.reasons
        assert not r.simulation.writes

    def test_a_truncated_recovery_is_refused_by_name(
        self, params: HeaterParams
    ) -> None:
        weak = replace(
            params,
            compressor=replace(params.compressor, compressor_constant=0.02),
        )
        s = _scenario(
            state=HeaterState(
                upper_f=110.0, lower_f=100.0, compressor_running=True
            ),
            environment=Environment(ambient_f=40.0),
        )
        with pytest.raises(SimulationError, match="1800-min bound"):
            simulate(s, weak)

    def test_no_gap_constant_takes_the_prior_and_says_so(
        self, params: HeaterParams
    ) -> None:
        bare = replace(
            params, tank=replace(params.tank, stratification_gap_tau_h=None)
        )
        quiet = simulate(_scenario(), bare)
        assert "stratification_gap_tau_h=60.0 (prior)" in quiet.defaults_used
        assert "tau_gap_prior" not in quiet.reasons
        drawn = simulate(
            _scenario(loads=Loads(draws=(Draw(at=at(1.0), gallons=10.0),))),
            bare,
        )
        assert "tau_gap_prior" in drawn.reasons

    def test_an_unmeasured_inlet_with_draws_says_so(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(loads=Loads(draws=(Draw(at=at(1.0), gallons=10.0),)))
        assert "inlet_temp_modelled" in simulate(s, params).reasons
        measured = simulate(s, params, inlet_measured=True)
        assert "inlet_temp_modelled" not in measured.reasons
        assert (
            "inlet_temp_modelled" not in simulate(_scenario(), params).reasons
        )

    def test_standby_says_when_no_tou_schedule_was_laid_out(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        t = standby(
            s.state,
            s.environment,
            Loads(),
            params,
            start=s.start,
            until=s.until,
            settings=s.settings,
        )
        assert "tou_schedule_unknown" in t.reasons
        known = standby(
            s.state,
            s.environment,
            Loads(),
            params,
            start=s.start,
            until=s.until,
            settings=s.settings,
            schedules=Schedules(),
        )
        assert "tou_schedule_unknown" not in known.reasons

    def test_draws_without_a_draw_response_are_refused(
        self, params: HeaterParams
    ) -> None:
        bare = replace(params, draw=replace(params.draw, observability=None))
        s = _scenario(loads=Loads(draws=(Draw(at=at(1.0), gallons=30.0),)))
        with pytest.raises(SimulationError, match="draw_model_unsupported"):
            simulate(s, bare)
        with pytest.raises(SimulationError, match="draw_model_unsupported"):
            standby(
                s.state,
                s.environment,
                s.loads,
                bare,
                start=s.start,
                until=s.until,
            )

    def test_a_written_setpoint_is_held_as_the_device_holds_it(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(
            commands=Commands(writes=(Write(at=at(1.0), setpoint_f=146.0),)),
        )
        (w,) = simulate(s, params).simulation.writes
        assert w.setpoint_f == 146.3

    @pytest.mark.parametrize("slot", [timedelta(0), timedelta(minutes=-10)])
    def test_a_slot_must_be_positive(self, params: HeaterParams, slot) -> None:
        """Copilot's review of #162: a negative slot walked backwards
        forever, and a zero one divided by zero."""
        r = simulate(
            _scenario(state=HeaterState(upper_f=110.0, lower_f=100.0)), params
        )
        with pytest.raises(ValueError, match="positive"):
            r.energy_by_slot(slot)
        with pytest.raises(ValueError, match="positive"):
            r.energy_by_source(slot)

    def test_energy_adds_up(self, params: HeaterParams) -> None:
        r = simulate(
            _scenario(state=HeaterState(upper_f=110.0, lower_f=100.0)), params
        )
        assert r.input_wh is not None and r.input_wh > 0
        slots = r.energy_by_slot()
        assert sum(wh for _, wh in slots if wh is not None) == pytest.approx(
            r.input_wh
        )
        for (a, total), (b, comp, element) in zip(
            slots, r.energy_by_source(), strict=True
        ):
            assert a == b
            assert total == pytest.approx((comp or 0.0) + element)

    def test_ambient_readings_are_used(self, params: HeaterParams) -> None:
        cold = _scenario(
            state=HeaterState(upper_f=110.0, lower_f=100.0),
            environment=Environment(
                ambient_f=((at(-1), 45.0), (at(12), 45.0)), humidity=48.0
            ),
        )
        warm = cold.model_copy(
            update={"environment": Environment(ambient_f=75.0, humidity=48.0)}
        )
        first_cold = simulate(cold, params).heating[0]
        first_warm = simulate(warm, params).heating[0]
        assert first_cold.end > first_warm.end


class TestRecoveryAndStandby:
    def test_recovery_is_the_first_heating_interval(
        self, params: HeaterParams
    ) -> None:
        state = HeaterState(upper_f=110.0, lower_f=100.0)
        settings = Settings(setpoint_f=140.9, hp_lower_on_f=105.0)
        env = Environment(ambient_f=AMBIENT_F, humidity=48.0)
        r = recovery(state, settings, env, params, at=T0)
        whole = simulate(
            Scenario(
                start=T0,
                horizon=timedelta(hours=24),
                tz="UTC",
                state=state,
                settings=settings,
                environment=env,
            ),
            params,
        )
        assert r.interval == whole.heating[0]
        assert r.ready_at == whole.heating[0].end
        assert r.minutes == pytest.approx(
            (r.ready_at - T0).total_seconds() / 60  # type: ignore[operator]
        )
        assert r.path[-1].at <= r.ready_at  # type: ignore[operator]

    def test_a_full_tank_has_no_recovery(self, params: HeaterParams) -> None:
        r = recovery(
            HeaterState(upper_f=141.0, lower_f=140.5),
            Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
            Environment(ambient_f=AMBIENT_F),
            params,
            at=T0,
            horizon=timedelta(hours=1),
        )
        assert r.interval is None and r.ready_at is None
        assert "no_recovery_within_horizon" in r.reasons

    def test_tou_caps_a_recovery(self, params: HeaterParams) -> None:
        state = HeaterState(upper_f=110.0, lower_f=100.0)
        settings = Settings(setpoint_f=140.9, hp_lower_on_f=105.0)
        env = Environment(ambient_f=AMBIENT_F, humidity=48.0)
        # A window open from the start: far short, the heater starts at
        # once, and the recovery stops short of the setpoint.
        sched = Schedules(tou_periods=_peak(18, 4), tou_enabled=True)
        held = recovery(state, settings, env, params, at=T0, schedules=sched)
        free = recovery(state, settings, env, params, at=T0)
        assert held.interval is not None and free.interval is not None
        assert held.interval.capped and held.interval.stop == "cap"
        assert not free.interval.capped and free.interval.stop == "target"
        assert held.ready_at < free.ready_at  # type: ignore[operator]
        cap = params.controller.tou_cap_f
        assert held.path[-1].lower_f == pytest.approx(140.9 - cap, abs=0.1)

    def test_standby_cools_and_draws_take_heat(
        self, params: HeaterParams
    ) -> None:
        state = HeaterState(upper_f=140.0, lower_f=138.0)
        env = Environment(ambient_f=AMBIENT_F)
        quiet = standby(state, env, Loads(), params, start=T0, until=at(6.0))
        drawn = standby(
            state,
            env,
            Loads(draws=(Draw(at=at(1.0), gallons=15.0),)),
            params,
            start=T0,
            until=at(6.0),
        )
        assert quiet.points[0].at == T0 and quiet.points[-1].at == at(6.0)
        assert quiet.points[-1].upper_f < 140.0
        assert drawn.points[-1].lower_f < quiet.points[-1].lower_f
