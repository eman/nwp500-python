"""The entry points around readiness: ``time_to_ready``,
``next_recovery``, standby's start answer, ``element_mode``, the draw
range and the setpoint range.

The answer's assembly is held to its source in ``test_sim_ready``; these
hold the entry points to the core they compose.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nwp500.sim import (
    Commands,
    Draw,
    Environment,
    HeaterParams,
    HeaterState,
    History,
    Loads,
    ReservationEntry,
    Scenario,
    Schedules,
    Settings,
    TouPeriod,
    Write,
    element_mode,
    next_recovery,
    simulate,
    site_example_params,
    standby,
    time_to_ready,
)
from nwp500.sim.physics.element import mode_plan

T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
EVERY_DAY = 254
#: ``hp_upper_on`` at rest (no TOU window) and raised (one in force).
RESTING, RAISED = 104.0, 139.5
#: A heater whose marker is not known: counted as in a TOU window.
UNMARKED = Settings(setpoint_f=140.9, hp_lower_on_f=105.0)


def at(h: float) -> datetime:
    return T0 + timedelta(hours=h)


@pytest.fixture(scope="module")
def params() -> HeaterParams:
    """One installation's parameters, its mixing valve included: the
    numbers below are that site's."""
    return site_example_params()


def _scenario(**kw: Any) -> Scenario:
    base: dict[str, Any] = {
        "start": T0,
        "horizon": timedelta(hours=12),
        "tz": "UTC",
        "state": HeaterState(upper_f=111.0, lower_f=107.0),
        "settings": Settings(
            setpoint_f=140.9, hp_lower_on_f=105.0, hp_upper_on_f=RESTING
        ),
        "history": History(compressor_stopped_at=at(-2.0)),
        "environment": Environment(ambient_f=68.0, humidity=48.0),
    }
    base.update(kw)
    return Scenario(**base)


def _peak_now() -> Schedules:
    """TOU on, with its peak from 18:00 to 23:00 UTC (in force at T0)."""
    periods = (
        TouPeriod(
            season=4095,
            week=EVERY_DAY,
            start_hour=0,
            start_minute=0,
            end_hour=17,
            end_minute=59,
            price_max=1,
        ),
        TouPeriod(
            season=4095,
            week=EVERY_DAY,
            start_hour=18,
            start_minute=0,
            end_hour=22,
            end_minute=59,
            price_max=5,
        ),
        TouPeriod(
            season=4095,
            week=EVERY_DAY,
            start_hour=23,
            start_minute=0,
            end_hour=23,
            end_minute=59,
            price_max=1,
        ),
    )
    return Schedules(tou_periods=periods, tou_enabled=True)


class TestNextRecovery:
    def test_it_ends_at_the_heaters_stop_threshold(
        self, params: HeaterParams
    ) -> None:
        running = HeaterState(
            upper_f=128.0, lower_f=100.0, compressor_running=True
        )
        stop = Settings(
            setpoint_f=140.9,
            hp_lower_on_f=105.0,
            hp_lower_off_f=136.4,
            hp_upper_on_f=RESTING,
        )
        r = next_recovery(_scenario(state=running, settings=stop), params)
        assert r.outcome == "ok"
        # And on past it by the run-on, where the heater stops.
        assert r.points[-1][2] == pytest.approx(
            136.4 + params.controller.hp_stop_overshoot_f, abs=0.2
        )

    def test_electric_still_has_a_heat_pump_recovery(
        self, params: HeaterParams
    ) -> None:
        electric = Settings(
            setpoint_f=140.9, mode=2, hp_lower_on_f=105.0, hp_upper_on_f=RESTING
        )
        r = next_recovery(
            _scenario(
                state=HeaterState(upper_f=120.0, lower_f=106.0),
                settings=electric,
                horizon=timedelta(hours=24),
            ),
            params,
        )
        assert r.outcome == "ok" and r.start_minute > 0

    def test_a_running_compressor_recovers_from_now(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            )
        )
        r = next_recovery(s, params)
        assert r.outcome == "ok"
        assert r.start_minute == 0.0
        assert r.points[0][0] == T0

    def test_an_idle_tank_recovers_from_the_heaters_own_trigger(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        r = next_recovery(s, params)
        coast = standby(
            s.state,
            s.environment,
            s.loads,
            params,
            start=T0,
            until=at(24.0),
            history=s.history,
            settings=s.settings,
        )
        assert r.outcome == "ok"
        assert coast.starts_at is not None
        assert r.start_minute == pytest.approx(
            (coast.starts_at - T0).total_seconds() / 60.0, abs=10.0
        )

    def test_draws_before_the_start_are_the_coasts(
        self, params: HeaterParams
    ) -> None:
        draws = tuple(
            Draw(at=at(0.5) + timedelta(minutes=i), gallons=4.0)
            for i in range(8)
        )
        r = next_recovery(_scenario(loads=Loads(draws=draws)), params)
        start = r.points[0][0]
        # The bath itself takes the lower zone to the trigger: the draw
        # that trips it is the coast's too.
        assert any(d.at == start for d in draws)
        before = sum(d.gallons for d in draws if d.at <= start)
        assert 0.0 < before < 32.0

    def test_a_draw_on_the_trigger_is_the_coasts(
        self, params: HeaterParams
    ) -> None:
        """The draw that trips the trigger is taken before the recovery
        starts: its tank and its gallons, a second either side alike."""
        got = []
        for shift in (-1, 0, 1):
            when = at(0.5) + timedelta(seconds=shift)
            r = next_recovery(
                _scenario(loads=Loads(draws=(Draw(at=when, gallons=20.0),))),
                params,
            )
            assert r.outcome == "ok"
            assert r.points[0][0] == when
            got.append(r.points[0][1:])
        for upper, lower in got[1:]:
            assert upper == pytest.approx(got[0][0], abs=0.01)
            assert lower == pytest.approx(got[0][1], abs=0.01)
        assert got[1][1] < 105.0

    def test_no_trigger_within_a_day_is_idle(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(
            state=HeaterState(upper_f=140.0, lower_f=139.0),
            settings=Settings(setpoint_f=140.9, hp_lower_on_f=None),
        )
        assert next_recovery(s, params).outcome == "idle"

    def test_vacation_is_not_scheduled(self, params: HeaterParams) -> None:
        s = _scenario(settings=Settings(setpoint_f=140.9, mode=5))
        assert next_recovery(s, params).outcome == "not_scheduled"

    def test_inside_a_tou_window_the_recovery_is_capped(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            ),
            schedules=_peak_now(),
            settings=UNMARKED,
        )
        r = next_recovery(s, params)
        assert r.outcome == "ok" and r.tou_capped


class TestTimeToReady:
    def test_a_full_tank_is_ready_in_every_mode(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(
            state=HeaterState(upper_f=140.5, lower_f=139.6),
            history=History(compressor_stopped_at=at(-1.0)),
        )
        r = time_to_ready(s, params)
        assert r.bath.ready
        assert {m.ready_in_minutes for m in r.bath.by_mode} == {0.0}
        assert r.defaults_used == ("bath_gal=28.7", "shower_gal=12.0")
        assert r.showers.ready_for_whole == int(r.deliverable_gal // 12.0)

    def test_a_short_tank_has_a_time_in_each_mode(
        self, params: HeaterParams
    ) -> None:
        r = time_to_ready(_scenario(), params, bath_gal=40.0)
        assert not r.bath.ready
        rows = {m.mode: m for m in r.bath.by_mode}
        assert r.bath.ready_in_minutes == rows["heat_pump"].ready_in_minutes
        assert rows["heat_pump"].ready_in_minutes is not None
        assert rows["electric"].ready_in_minutes is not None
        assert (
            rows["electric"].ready_in_minutes
            < rows["heat_pump"].ready_in_minutes
        )
        assert r.recovery.outcome == "ok"
        assert r.defaults_used == ("shower_gal=12.0",)

    def test_an_unknown_tou_marker_counts_as_in_force(
        self, params: HeaterParams
    ) -> None:
        r = time_to_ready(_scenario(settings=UNMARKED), params, bath_gal=20.0)
        assert "tou_window=in_force (hp_upper_on_f unknown)" in r.defaults_used
        rows = {m.mode: m for m in r.bath.by_mode}
        assert not rows["electric"].reachable_now
        assert "tou_window_in_force" in r.reasons

    def test_the_layers_answer_and_the_probes_say_so(
        self, params: HeaterParams
    ) -> None:
        """Layers that remember a draw promise less than the profile two
        probes reading the same stand for."""
        from nwp500.sim.physics import stratified as st

        lay = st.layout(params)
        full = st.TankState((140.5,) * lay.layers)
        valve = (
            params.draw.delivery_intercept_f,
            params.draw.delivery_slope,
        )
        drawn = st.draw(lay, full, 15.0, 60.0, valve).state
        upper, lower = st.observe(lay, drawn)
        probes = time_to_ready(
            _scenario(state=HeaterState(upper_f=upper, lower_f=lower)),
            params,
        )
        layered = time_to_ready(
            _scenario(
                state=HeaterState(
                    upper_f=upper, lower_f=lower, layers_f=drawn.layers_f
                )
            ),
            params,
        )
        assert "tank_profile_estimated" in probes.reasons
        assert "tank_profile_estimated" not in layered.reasons
        assert layered.deliverable_gal < probes.deliverable_gal

    def test_a_modelled_inlet_says_so(self, params: HeaterParams) -> None:
        s = _scenario(state=HeaterState(upper_f=140.5, lower_f=139.6))
        assert "inlet_temp_modelled" in time_to_ready(s, params).reasons
        measured = time_to_ready(s, params, inlet_measured=True)
        assert "inlet_temp_modelled" not in measured.reasons

    def test_a_colder_inlet_is_fewer_gallons(
        self, params: HeaterParams
    ) -> None:
        def at_inlet(inlet: float) -> float:
            s = _scenario(
                state=HeaterState(upper_f=140.5, lower_f=139.6),
                environment=Environment(
                    ambient_f=68.0, humidity=48.0, inlet_f=inlet
                ),
            )
            return time_to_ready(s, params).deliverable_gal

        assert at_inlet(50.0) < at_inlet(60.0) < at_inlet(70.0)

    def test_each_mode_is_its_own_walk(self, params: HeaterParams) -> None:
        """Each row is the scenario walked with that mode written at its
        start to the first instant its layers deliver the bath."""
        s = _scenario()
        r = time_to_ready(s, params, bath_gal=40.0)
        rows = {m.mode: m for m in r.bath.by_mode}
        electric = s.model_copy(
            update={
                "commands": Commands(writes=(Write(at=T0, mode=2),)),
                "horizon": timedelta(hours=24),
            }
        )
        walk = simulate(electric, params).simulation
        minutes = rows["electric"].ready_in_minutes
        assert minutes is not None
        then = T0 + timedelta(minutes=minutes)
        point = next(p for p in walk.points if p.at == then)
        from nwp500.sim.delivery import deliverable

        mains = params.draw.mains_on(s.start)

        def gal(p: Any) -> float:
            return deliverable(
                params, p.upper_f, p.lower_f, p.layers_f, inlet_f=mains
            ).gal

        assert gal(point) >= 40.0
        # The first: no earlier instant of the walk delivers it.
        assert all(gal(p) < 40.0 for p in walk.points if p.at < then)
        wh = sum(
            (p.input_wh or 0.0) + p.element_wh
            for p in walk.points
            if p.at <= then
        )
        assert rows["electric"].energy_kwh == pytest.approx(
            wh / 1000.0, abs=0.01
        )
        # Its element's caveats are its own row's.
        assert "element_model_small_n" in rows["electric"].reasons
        assert rows["heat_pump"].reasons == ()

    def test_a_scenarios_own_mode_write_does_not_set_every_row(
        self, params: HeaterParams
    ) -> None:
        """Each row's own mode replaces the scenario's write at the
        start: the heat pump's row is the heat pump's."""
        own = time_to_ready(_scenario(), params, bath_gal=40.0)
        written = time_to_ready(
            _scenario(commands=Commands(writes=(Write(at=T0, mode=2),))),
            params,
            bath_gal=40.0,
        )
        rows = {m.mode: m for m in written.bath.by_mode}
        assert written.bath.by_mode == own.bath.by_mode
        assert (
            rows["heat_pump"].ready_in_minutes
            != rows["electric"].ready_in_minutes
        )

    def test_an_unknown_marker_and_schedule_hold_the_element_writes(
        self, params: HeaterParams
    ) -> None:
        """TOU on with neither its periods nor the heater's marker known:
        in force, so no element mode's write takes and every row is the
        heat pump's."""
        s = _scenario(settings=UNMARKED, schedules=Schedules(tou_enabled=True))
        r = time_to_ready(s, params, bath_gal=40.0)
        times = {m.ready_in_minutes for m in r.bath.by_mode}
        assert len(times) == 1
        assert not any(
            m.reachable_now for m in r.bath.by_mode if m.mode != "heat_pump"
        )
        assert "tou_schedule_unknown" in r.reasons

    def test_a_bath_out_of_reach_has_no_time(
        self, params: HeaterParams
    ) -> None:
        r = time_to_ready(_scenario(), params, bath_gal=500.0)
        assert all(m.ready_in_minutes is None for m in r.bath.by_mode)
        assert "bath_not_reached_by_full_recovery" in r.reasons

    def test_standing_and_sourcing_reasons_are_left_out(
        self, params: HeaterParams
    ) -> None:
        r = time_to_ready(_scenario(), params)
        assert "readiness_model_provisional" not in r.reasons
        assert "bath_volume_inferred" not in r.reasons
        assert "tank_profile_estimated" in r.reasons

    def test_vacation_reaches_nothing(self, params: HeaterParams) -> None:
        r = time_to_ready(
            _scenario(settings=Settings(setpoint_f=140.9, mode=5)),
            params,
            bath_gal=40.0,
        )
        assert "heating_not_scheduled" in r.reasons
        assert not any(m.reachable_now for m in r.bath.by_mode)

    def test_inside_a_tou_window_only_the_heat_pump_is_reachable(
        self, params: HeaterParams
    ) -> None:
        r = time_to_ready(
            _scenario(schedules=_peak_now(), settings=UNMARKED), params
        )
        rows = {m.mode: m for m in r.bath.by_mode}
        assert rows["heat_pump"].reachable_now
        assert not rows["electric"].reachable_now
        assert "tou_window_in_force" in r.reasons


class TestStandbysStart:
    def test_without_settings_there_is_no_start_answer(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        t = standby(
            s.state, s.environment, Loads(), params, start=T0, until=at(12.0)
        )
        assert t.starts_at is None and t.lower_margin_f is None

    def test_the_lower_trigger_and_the_margin(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        t = standby(
            s.state,
            s.environment,
            Loads(),
            params,
            start=T0,
            until=at(24.0),
            settings=s.settings,
        )
        assert t.trigger == "lower"
        assert t.starts_at is not None and T0 < t.starts_at < at(24.0)
        last = t.points[-1]
        assert t.lower_margin_f == pytest.approx(last.lower_f - 105.0)

    def test_vacation_never_starts(self, params: HeaterParams) -> None:
        s = _scenario(settings=Settings(setpoint_f=140.9, mode=5))
        t = standby(
            s.state,
            s.environment,
            Loads(),
            params,
            start=T0,
            until=at(24.0),
            settings=Settings(setpoint_f=140.9, mode=5, hp_lower_on_f=105.0),
        )
        assert t.starts_at is None


class TestElementMode:
    def test_it_is_the_element_models_plan(self, params: HeaterParams) -> None:
        state = HeaterState(upper_f=125.0, lower_f=110.0)
        settings = Settings(setpoint_f=141.8, hp_upper_on_f=RESTING)
        r = element_mode(state, settings, params, mode=4, at=T0)
        assert r.plan == mode_plan(
            "HIGH_DEMAND", 125.0, 110.0, 141.8, params=params.element
        )
        assert r.reachable and r.unreachable_reason is None

    def test_not_reachable_inside_a_tou_window_or_on_vacation(
        self, params: HeaterParams
    ) -> None:
        state = HeaterState(upper_f=125.0, lower_f=110.0)
        r = element_mode(
            state,
            Settings(setpoint_f=141.8, hp_upper_on_f=RAISED),
            params,
            mode=2,
            at=T0,
        )
        assert r.unreachable_reason == "tou_window_in_force"
        unknown = element_mode(
            state, Settings(setpoint_f=141.8), params, mode=2, at=T0
        )
        assert unknown.unreachable_reason == "tou_window_in_force"
        v = element_mode(
            state, Settings(setpoint_f=141.8, mode=5), params, mode=3, at=T0
        )
        assert v.unreachable_reason == "heating_disabled"

    def test_a_what_if_setpoint_does_not_move_the_window_test(
        self, params: HeaterParams
    ) -> None:
        # A resting heater (hp_upper_on at the device minimum) asked about
        # 108 °F: the window test is the device's setpoint's.
        r = element_mode(
            HeaterState(upper_f=100.0, lower_f=95.0),
            Settings(setpoint_f=140.9, hp_upper_on_f=RESTING),
            params,
            mode=2,
            at=T0,
            setpoint_f=108.0,
        )
        assert r.reachable
        assert r.plan == mode_plan(
            "ELECTRIC", 100.0, 95.0, 108.0, params=params.element
        )

    @pytest.mark.parametrize("mode", [1, 5, 6])
    def test_a_mode_without_an_element_is_refused(
        self, params: HeaterParams, mode: int
    ) -> None:
        with pytest.raises(ValueError, match="no element"):
            element_mode(
                HeaterState(upper_f=125.0, lower_f=110.0),
                Settings(setpoint_f=141.8),
                params,
                mode=mode,
                at=T0,
            )


class TestTheDrawRange:
    def test_a_draw_beyond_the_fitted_volume_says_so(
        self, params: HeaterParams
    ) -> None:
        big = Loads(draws=(Draw(at=at(1.0), gallons=45.0),))
        r = simulate(_scenario(loads=big), params)
        assert "draw_out_of_domain" in r.reasons

    def test_one_inside_it_does_not(self, params: HeaterParams) -> None:
        small = Loads(draws=(Draw(at=at(1.0), gallons=10.0),))
        s = _scenario(
            state=HeaterState(upper_f=140.0, lower_f=139.0),
            horizon=timedelta(hours=3),
        )
        r = simulate(s.model_copy(update={"loads": small}), params)
        assert "draw_out_of_domain" not in r.reasons
        assert r.draw_out_of_domain_at is None

    def test_a_range_of_none_is_not_judged(self, params: HeaterParams) -> None:
        p = replace(
            params,
            draw=replace(
                params.draw, domain_upper_f=None, domain_volume_gal=None
            ),
        )
        big = Loads(draws=(Draw(at=at(1.0), gallons=45.0),))
        assert (
            "draw_out_of_domain"
            not in simulate(_scenario(loads=big), p).reasons
        )


class TestTheSetpointRange:
    def test_a_write_outside_it_is_refused(self, params: HeaterParams) -> None:
        s = _scenario(
            commands=Commands(writes=(Write(at=at(1.0), setpoint_f=155.0),))
        )
        with pytest.raises(ValueError, match="outside the range"):
            simulate(s, params)

    def test_a_written_reservation_outside_it_is_refused(
        self, params: HeaterParams
    ) -> None:
        entry = ReservationEntry(
            week=124, hour=6, minute=0, mode=1, setpoint_half_c=70
        )
        s = _scenario(commands=Commands(reservations=(entry,)))
        with pytest.raises(ValueError, match="reservation 0"):
            simulate(s, params)

    def test_the_ends_of_it_run(self, params: HeaterParams) -> None:
        for f in (104.9, 149.9):
            s = _scenario(
                commands=Commands(writes=(Write(at=at(1.0), setpoint_f=f),))
            )
            assert simulate(s, params).simulation.points


class TestWithoutALowerThreshold:
    def test_the_upper_trigger_at_a_tou_opening_still_starts_it(
        self, params: HeaterParams
    ) -> None:
        """No ``hp_lower_on`` disables the lower trigger only: a tank far
        short at a window's opening still starts on its own."""
        s = _scenario(
            state=HeaterState(upper_f=120.0, lower_f=115.0),
            settings=Settings(setpoint_f=140.9, hp_lower_on_f=None),
            schedules=_peak_now(),
        )
        r = simulate(s, params)
        assert r.heating
        assert r.heating[0].start.trigger == "upper_at_tou_open"
        t = standby(
            s.state,
            s.environment,
            Loads(),
            params,
            start=T0,
            until=at(3.0),
            settings=s.settings,
            schedules=s.schedules,
        )
        assert t.trigger == "upper_at_tou_open"
        assert t.lower_margin_f is None
        # Each says it never searched the lower trigger.
        assert "hp_lower_on_unknown" in r.reasons
        assert "hp_lower_on_unknown" in t.reasons


class _Fixed:
    """A recovery model that serves a fixed duration."""

    def __init__(self, minutes: float, confidence: float = 1.0) -> None:
        self.minutes = minutes
        self.confidence = confidence

    def duration(self, ctx: Any) -> Any:
        from nwp500.sim.heat_pump_recovery import ModelDuration

        return ModelDuration(
            minutes=self.minutes,
            start_hold_minutes=0.0,
            confidence=self.confidence,
        )


class TestARecoveryModel:
    def test_a_low_confidence_answer_says_so(
        self, params: HeaterParams
    ) -> None:
        """The source flagged a served recovery under 0.6; the port's
        floor was 0, so nothing could."""
        s = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=112.0, compressor_running=True
            )
        )
        sure = simulate(s, params, recovery=_Fixed(90.0))
        unsure = simulate(s, params, recovery=_Fixed(90.0, confidence=0.4))
        assert "recovery_low_confidence" in unsure.reasons
        assert "recovery_low_confidence" not in sure.reasons

    def test_it_serves_the_next_recoverys_duration(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            )
        )
        r = next_recovery(s, params, recovery=_Fixed(90.0))
        end = r.points[-1][0]
        # The model paces the heat pump, to within a step's cut.
        assert (end - T0).total_seconds() / 60.0 == pytest.approx(90.0, abs=0.5)

    def test_time_to_ready_follows_it(self, params: HeaterParams) -> None:
        s = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            )
        )
        fast = time_to_ready(s, params, bath_gal=40.0, recovery=_Fixed(60.0))
        slow = time_to_ready(s, params, bath_gal=40.0, recovery=_Fixed(240.0))
        assert fast.bath.ready_in_minutes is not None
        assert slow.bath.ready_in_minutes is not None
        assert fast.bath.ready_in_minutes < slow.bath.ready_in_minutes


class TestTheHeatersOwnTouMarker:
    """The heater raises its upper start threshold to about the setpoint
    while a TOU window is in force; the model read that before the
    schedule."""

    def test_raised_is_in_force(self) -> None:
        from nwp500.sim.api import tou_marked

        assert tou_marked(Settings(setpoint_f=140.9, hp_upper_on_f=RAISED))
        assert not tou_marked(Settings(setpoint_f=140.9, hp_upper_on_f=RESTING))
        assert tou_marked(Settings(setpoint_f=140.9)) is None

    def test_it_caps_a_running_recovery_the_schedule_misses(
        self, params: HeaterParams
    ) -> None:
        running = HeaterState(
            upper_f=128.0, lower_f=100.0, compressor_running=True
        )
        plain = next_recovery(_scenario(state=running), params)
        marked = next_recovery(
            _scenario(
                state=running,
                settings=Settings(
                    setpoint_f=140.9, hp_lower_on_f=105.0, hp_upper_on_f=RAISED
                ),
            ),
            params,
        )
        assert not plain.tou_capped and marked.tou_capped

    def test_resting_lifts_a_scheduled_window_off_it(
        self, params: HeaterParams
    ) -> None:
        """An override: the schedule says peak, the heater does not."""
        s = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            ),
            schedules=_peak_now(),
            settings=Settings(
                setpoint_f=140.9, hp_lower_on_f=105.0, hp_upper_on_f=RESTING
            ),
        )
        assert not next_recovery(s, params).tou_capped

    def test_readiness_and_the_element_modes_follow_it(
        self, params: HeaterParams
    ) -> None:
        raised = Settings(
            setpoint_f=140.9, hp_lower_on_f=105.0, hp_upper_on_f=RAISED
        )
        r = time_to_ready(_scenario(settings=raised), params)
        assert not any(d.startswith("tou_window=") for d in r.defaults_used)
        e = element_mode(
            HeaterState(upper_f=120.0, lower_f=100.0),
            raised,
            params,
            mode=3,
            at=T0,
        )
        assert e.unreachable_reason == "tou_window_in_force"

    def test_tou_on_with_no_periods_is_unknown(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(schedules=Schedules(tou_enabled=True))
        assert "tou_schedule_unknown" in simulate(s, params).reasons
        assert (
            "tou_schedule_unknown" not in simulate(_scenario(), params).reasons
        )


class TestOneInstallationsTerms:
    """Under ``default_params`` the draw terms are another
    installation's, and the answers they reach say so; the site's own
    example is its fit."""

    def test_readiness_says_its_terms_are_not_this_heaters(
        self, params: HeaterParams
    ) -> None:
        from nwp500.sim import default_params

        mine = time_to_ready(_scenario(), default_params(), bath_gal=20.0)
        assert "draw_uncalibrated" in mine.reasons
        assert not {"book_uncalibrated", "readiness_uncalibrated"} & set(
            mine.reasons
        )
        site = time_to_ready(_scenario(), params, bath_gal=20.0)
        assert "draw_uncalibrated" not in site.reasons

    def test_a_draw_says_its_response_is_not_this_heaters(self) -> None:
        from nwp500.sim import default_params

        s = _scenario(loads=Loads(draws=(Draw(at=at(1), gallons=5.0),)))
        assert "draw_uncalibrated" in simulate(s, default_params()).reasons
        quiet = simulate(_scenario(), default_params())
        assert "draw_uncalibrated" not in quiet.reasons

    def test_a_ready_bath_still_says_its_terms(self) -> None:
        """The re-check of the replacement review: the gallons a ready
        tank reports rest on the same terms."""
        from nwp500.sim import default_params

        s = _scenario(
            state=HeaterState(upper_f=140.5, lower_f=139.6),
            history=History(compressor_stopped_at=at(-1.0)),
        )
        r = time_to_ready(s, default_params(), bath_gal=20.0)
        assert r.bath.ready
        assert "draw_uncalibrated" in r.reasons


NAN = float("nan")


class TestTheDefaultAir:
    """The re-check of the replacement review: an air reading missing
    throughout runs at the default air, and every answer says so."""

    @pytest.mark.parametrize(
        "missing",
        [
            Environment(ambient_f=NAN, humidity=48.0),
            Environment(ambient_f=((at(0), NAN), (at(6), NAN)), humidity=48.0),
        ],
    )
    def test_each_answer_says_its_air_was_the_default(
        self, params: HeaterParams, missing: Environment
    ) -> None:
        from nwp500.sim import forecast, standby
        from nwp500.sim.units import DEFAULT_AMBIENT_F

        assert missing.ambient_defaulted
        given = Environment(ambient_f=DEFAULT_AMBIENT_F, humidity=48.0)
        assert not given.ambient_defaulted
        s, g = _scenario(environment=missing), _scenario(environment=given)

        sim = simulate(s, params)
        assert "ambient_defaulted" in sim.reasons
        assert sim.simulation.points == simulate(g, params).simulation.points
        assert "ambient_defaulted" not in simulate(g, params).reasons

        coast = standby(
            s.state, missing, Loads(), params, start=T0, until=at(6)
        )
        assert "ambient_defaulted" in coast.reasons
        assert (
            coast.points
            == standby(
                s.state, given, Loads(), params, start=T0, until=at(6)
            ).points
        )

        ahead = forecast(
            s.state, s.settings, missing, params, at=T0, target_time=at(6)
        )
        assert "ambient_defaulted" in ahead.reasons

        ready = time_to_ready(s, params, bath_gal=20.0)
        assert "ambient_defaulted" in ready.reasons
        assert (
            "ambient_defaulted"
            not in time_to_ready(g, params, bath_gal=20.0).reasons
        )


class TestTheScenariosInlet:
    """The delivered water meets the scenario's inlet where one is
    given, as the walk's draws take it."""

    def test_the_delivered_water_follows_the_inlet(self) -> None:
        from nwp500.sim import Draw, DrawWindow, default_params

        params = default_params()
        loads = Loads(
            draws=tuple(
                Draw(at=at(1) + timedelta(minutes=i), gallons=2.5)
                for i in range(16)
            ),
            windows=(
                DrawWindow(
                    start=at(1),
                    end=at(1) + timedelta(minutes=20),
                    expected_gal=40.0,
                ),
            ),
        )

        def coldest(inlet: float) -> float:
            s = _scenario(
                state=HeaterState(upper_f=140.9, lower_f=140.0),
                environment=Environment(ambient_f=65.0, inlet_f=inlet),
                loads=loads,
            )
            window = simulate(s, params).windows[0]
            assert window.delivery_min_f is not None
            return window.delivery_min_f

        assert coldest(40.0) < coldest(72.4)


class TestHeaterOnlyReadiness:
    """With the default parameters and no layers: the probes'
    profile."""

    def _ready(
        self, upper: float, lower: float, code: int = 2, **state: Any
    ) -> Any:
        from nwp500.sim import HeaterState, default_params

        return time_to_ready(
            _scenario(state=HeaterState(upper_f=upper, lower_f=lower, **state)),
            default_params(code),
        )

    def test_a_uniform_tank_reads_from_its_probes(self) -> None:
        for code in (1, 2, 3):
            r = self._ready(140.9, 140.0, code)
            assert r.deliverable_gal > 0.0

    def test_bigger_tanks_hold_more(self) -> None:
        gal = [
            self._ready(140.9, 140.0, code).deliverable_gal
            for code in (1, 2, 3)
        ]
        assert gal[0] < gal[1] < gal[2]

    @pytest.mark.parametrize(
        ("upper", "lower"), [(140.0, 125.0), (140.0, 104.0), (118.0, 95.0)]
    )
    def test_any_state_reads_its_probes_profile(
        self, upper: float, lower: float
    ) -> None:
        from nwp500.sim import default_params
        from nwp500.sim.delivery import deliverable

        p = default_params()
        r = self._ready(upper, lower)
        gal = deliverable(p, upper, lower).gal
        assert gal > 0.0
        assert r.deliverable_gal == gal
        assert "tank_profile_estimated" in r.reasons

    def test_a_running_heater_reads_the_same(self) -> None:
        idle = self._ready(130.0, 112.0)
        for running in (
            {"compressor_running": True},
            {"element_running": True},
        ):
            r = self._ready(130.0, 112.0, **running)
            assert r.deliverable_gal == idle.deliverable_gal > 0.0


class TestTheProbesResolution:
    def test_the_line_edge_is_within_probe_resolution(self) -> None:
        from nwp500.sim import HeaterState, default_params

        # A bath of just what the tank delivers: a probe error either
        # way decides it.
        p = default_params()
        state = HeaterState(upper_f=112.0, lower_f=100.0)
        gal = time_to_ready(_scenario(state=state), p).deliverable_gal
        r = time_to_ready(_scenario(state=state), p, bath_gal=gal)
        assert r.bath.ready
        assert "bath_ready_within_probe_resolution" in r.reasons


class TestCirculationWithoutItsTerms:
    """Runs given to params with no circulation terms take one
    installation's, and say so, rather than refusing."""

    def test_the_runs_take_the_example_terms(self) -> None:
        from nwp500.sim import CirculationRun, default_params, simulate
        from nwp500.sim.defaults import SITE_CIRCULATION

        bare = default_params()
        assert bare.circulation is None
        runs = (CirculationRun(start=at(0.5), end=at(1.5)),)
        s = _scenario(loads=Loads(circulation=runs))
        got = simulate(s, bare)
        want = simulate(s, replace(bare, circulation=SITE_CIRCULATION))
        assert got.simulation == want.simulation
        assert (
            "circulation=one installation's (CirculationParams)"
            in got.defaults_used
        )
        # And they cost heat: not the same as no runs.
        quiet = simulate(_scenario(), bare)
        assert got.simulation != quiet.simulation

    def test_runs_known_only_partway_say_so(self) -> None:
        from nwp500.sim import CirculationRun, default_params, simulate

        runs = (CirculationRun(start=at(0.5), end=at(1.5)),)
        s = _scenario(
            loads=Loads(circulation=runs, circulation_known_until=at(2.0))
        )
        assert "circulation_unknown" in simulate(s, default_params()).reasons
