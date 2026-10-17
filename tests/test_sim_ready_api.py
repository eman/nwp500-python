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

pytest.importorskip("pandas")

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
    full_tank_book,
    next_recovery,
    simulate,
    site_example_params,
    standby,
    time_to_ready,
)
from nwp500.sim.physics.element import mode_plan

T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
EVERY_DAY = 254


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
        "state": HeaterState(upper_f=128.0, lower_f=112.0),
        "settings": Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
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
    def test_a_running_compressor_recovers_from_now(self, params):
        s = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            )
        )
        r = next_recovery(s, params)
        assert r.outcome == "ok"
        assert r.start_minute == 0.0
        assert r.points[0][0] == T0

    def test_an_idle_tank_recovers_from_the_heaters_own_trigger(self, params):
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
        assert r.coast_btu > 0.0

    def test_draws_before_the_start_are_the_coasts(self, params):
        draws = tuple(
            Draw(at=at(0.5) + timedelta(minutes=i), gallons=1.6)
            for i in range(8)
        )
        r = next_recovery(_scenario(loads=Loads(draws=draws)), params)
        start = T0 + timedelta(minutes=r.start_minute)
        before = sum(d.gallons for d in draws if d.at < start)
        # The shower itself takes the lower zone to the trigger.
        assert 0.0 < before < 12.8
        assert r.coast_draw_gal == pytest.approx(before)

    def test_no_trigger_within_a_day_is_idle(self, params):
        s = _scenario(
            state=HeaterState(upper_f=140.0, lower_f=139.0),
            settings=Settings(setpoint_f=140.9, hp_lower_on_f=None),
        )
        assert next_recovery(s, params).outcome == "idle"

    def test_vacation_is_not_scheduled(self, params):
        s = _scenario(settings=Settings(setpoint_f=140.9, mode=5))
        assert next_recovery(s, params).outcome == "not_scheduled"

    def test_inside_a_tou_window_the_recovery_is_capped(self, params):
        s = _scenario(
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            ),
            schedules=_peak_now(),
        )
        r = next_recovery(s, params)
        assert r.outcome == "ok" and r.tou_capped


class TestTimeToReady:
    def test_a_full_tank_at_its_setpoint_is_ready_in_every_mode(self, params):
        s = _scenario(
            state=HeaterState(upper_f=140.5, lower_f=139.6),
            history=History(compressor_stopped_at=at(-1.0)),
        )
        r = time_to_ready(s, params)
        assert r.bath.ready
        assert {m.ready_in_minutes for m in r.bath.by_mode} == {0.0}
        assert r.defaults_used == ("bath_gal=28.7", "shower_gal=12.0")
        assert r.showers.ready_for_whole == 3

    def test_a_short_tank_has_a_time_in_each_mode(self, params):
        r = time_to_ready(_scenario(), params, bath_gal=20.0)
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

    def test_with_a_book_the_booked_heat_answers(self, params):
        s = _scenario(state=HeaterState(upper_f=140.5, lower_f=139.6))
        book = full_tank_book(140.5, 139.6, params.book)
        r = time_to_ready(s, params, book=book)
        assert "no_heat_book" not in r.reasons
        assert r.deliverable_gal == pytest.approx(53.1, abs=0.05)

    def test_standing_and_sourcing_reasons_are_left_out(self, params):
        r = time_to_ready(_scenario(), params)
        assert "readiness_model_provisional" not in r.reasons
        assert "bath_volume_inferred" not in r.reasons
        assert "no_heat_book" in r.reasons

    def test_vacation_reaches_nothing(self, params):
        r = time_to_ready(
            _scenario(settings=Settings(setpoint_f=140.9, mode=5)), params
        )
        assert "heating_not_scheduled" in r.reasons
        assert not any(m.reachable_now for m in r.bath.by_mode)

    def test_inside_a_tou_window_only_the_heat_pump_is_reachable(self, params):
        r = time_to_ready(_scenario(schedules=_peak_now()), params)
        rows = {m.mode: m for m in r.bath.by_mode}
        assert rows["heat_pump"].reachable_now
        assert not rows["electric"].reachable_now
        assert "tou_window_in_force" in r.reasons


class TestStandbysStart:
    def test_without_settings_there_is_no_start_answer(self, params):
        s = _scenario()
        t = standby(
            s.state, s.environment, Loads(), params, start=T0, until=at(12.0)
        )
        assert t.starts_at is None and t.lower_margin_f is None

    def test_the_lower_trigger_and_the_margin(self, params):
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

    def test_vacation_never_starts(self, params):
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
    def test_it_is_the_element_models_plan(self, params):
        state = HeaterState(upper_f=125.0, lower_f=110.0)
        settings = Settings(setpoint_f=141.8)
        r = element_mode(state, settings, params, mode=4, at=T0)
        assert r.plan == mode_plan(
            "HIGH_DEMAND", 125.0, 110.0, 141.8, params=params.element
        )
        assert r.reachable and r.unreachable_reason is None

    def test_not_reachable_inside_a_tou_window_or_on_vacation(self, params):
        state = HeaterState(upper_f=125.0, lower_f=110.0)
        r = element_mode(
            state,
            Settings(setpoint_f=141.8),
            params,
            mode=2,
            at=T0,
            schedules=_peak_now(),
        )
        assert r.unreachable_reason == "tou_window_in_force"
        v = element_mode(
            state, Settings(setpoint_f=141.8, mode=5), params, mode=3, at=T0
        )
        assert v.unreachable_reason == "heating_disabled"

    @pytest.mark.parametrize("mode", [1, 5, 6])
    def test_a_mode_without_an_element_is_refused(self, params, mode):
        with pytest.raises(ValueError, match="no element"):
            element_mode(
                HeaterState(upper_f=125.0, lower_f=110.0),
                Settings(setpoint_f=141.8),
                params,
                mode=mode,
                at=T0,
            )


class TestTheDrawRange:
    def test_a_draw_beyond_the_fitted_volume_says_so(self, params):
        big = Loads(draws=(Draw(at=at(1.0), gallons=45.0),))
        r = simulate(_scenario(loads=big), params)
        assert "draw_out_of_domain" in r.reasons

    def test_one_inside_it_does_not(self, params):
        small = Loads(draws=(Draw(at=at(1.0), gallons=10.0),))
        s = _scenario(
            state=HeaterState(upper_f=140.0, lower_f=139.0),
            horizon=timedelta(hours=3),
        )
        r = simulate(s.model_copy(update={"loads": small}), params)
        assert "draw_out_of_domain" not in r.reasons
        assert r.draw_out_of_domain_at is None

    def test_a_range_of_none_is_not_judged(self, params):
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
    def test_a_write_outside_it_is_refused(self, params):
        s = _scenario(
            commands=Commands(writes=(Write(at=at(1.0), setpoint_f=155.0),))
        )
        with pytest.raises(ValueError, match="outside the range"):
            simulate(s, params)

    def test_a_written_reservation_outside_it_is_refused(self, params):
        entry = ReservationEntry(
            week=124, hour=6, minute=0, mode=1, setpoint_half_c=70
        )
        s = _scenario(commands=Commands(reservations=(entry,)))
        with pytest.raises(ValueError, match="reservation 0"):
            simulate(s, params)

    def test_the_ends_of_it_run(self, params):
        for f in (104.9, 149.9):
            s = _scenario(
                commands=Commands(writes=(Write(at=at(1.0), setpoint_f=f),))
            )
            assert simulate(s, params).simulation.points


class TestWithoutALowerThreshold:
    def test_the_upper_trigger_at_a_tou_opening_still_starts_it(self, params):
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
