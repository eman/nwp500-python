"""The heat pump's operating range (``ControllerParams.hp_air_range_f``,
``hp_water_range_f``): outside it the compressor does not run and the
elements heat the tank (the user's manual, 3.13.1 and 3.13.4)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from nwp500 import sim
from nwp500.sim import controller as ctl
from nwp500.sim.decay import AmbientSampler
from nwp500.sim.params import ControllerParams
from nwp500.sim.physics import stratified as st
from nwp500.sim.physics.heat_pump import HEAT_MAP_OUT_OF_DOMAIN

T0 = datetime(2026, 1, 10, 6, 0, tzinfo=UTC)


def at(h: float) -> datetime:
    return T0 + timedelta(hours=h)


def _run(
    air: float | tuple[tuple[datetime, float], ...],
    *,
    upper: float = 118.0,
    lower: float = 100.0,
    running: bool = False,
    setpoint: float = 140.0,
    hours: float = 8.0,
    params: sim.HeaterParams | None = None,
    mode: int = 1,
    on: float = 105.0,
    element_running: bool = False,
    **scenario: Any,
) -> sim.SimulationResult:
    return sim.simulate(
        sim.Scenario(
            start=T0,
            horizon=timedelta(hours=hours),
            tz="UTC",
            state=sim.HeaterState(
                upper_f=upper,
                lower_f=lower,
                compressor_running=running,
                element_running=element_running,
            ),
            settings=sim.Settings(
                setpoint_f=setpoint,
                hp_lower_off_f=setpoint,
                hp_lower_on_f=on,
                mode=mode,
            ),
            **{
                "history": sim.History(compressor_stopped_at=at(-3)),
                "environment": sim.Environment(ambient_f=air),
                **scenario,
            },
        ),
        params if params is not None else sim.site_example_params(),
    )


def _sources(r: sim.SimulationResult) -> list[tuple[str, str | None, str]]:
    return [(h.source, h.zone, h.stop) for h in r.heating]


class TestTheAir:
    def test_inside_it_the_heat_pump_heats(self) -> None:
        r = _run(60.0)
        assert _sources(r)[0] == ("compressor", None, "target")
        assert ctl.HEAT_PUMP_UNAVAILABLE not in r.reasons

    @pytest.mark.parametrize("air", [35.0, 113.0, 120.0])
    def test_outside_it_the_elements_heat(self, air: float) -> None:
        r = _run(air)
        assert r.heating
        assert all(h.source == "element" for h in r.heating)
        # Electric's rule: the upper element, then the lower.
        assert [h.zone for h in r.heating[:2]] == ["upper", "lower"]
        assert ctl.HEAT_PUMP_UNAVAILABLE in r.reasons
        assert ctl.ENVELOPE_FALLBACK_UNVERIFIED in r.reasons
        # The tank is heated to the setpoint all the same.
        assert max(p.lower_f for p in r.points) == pytest.approx(140.0, abs=0.1)

    def test_a_compressor_running_into_the_cold_stops(self) -> None:
        # The air falls through 41 °F two hours in.
        air = ((at(0), 50.0), (at(2), 41.0), (at(3), 35.0))
        r = _run(air, lower=95.0, running=True)
        first = r.heating[0]
        assert (first.source, first.stop) == ("compressor", "envelope")
        assert first.end == pytest.approx(at(2), abs=timedelta(seconds=1))
        assert r.heating[1].source == "element"
        assert r.heating[1].start.at == first.end

    def test_back_in_range_the_heat_pump_takes_over(self) -> None:
        # Cold for the first 12 minutes, while the upper element runs,
        # then warm.
        air = ((at(0), 35.0), (at(0.2), 35.0), (at(0.21), 60.0))
        r = _run(air, upper=110.0, lower=95.0)
        assert (r.heating[0].source, r.heating[0].zone) == ("element", "upper")
        back = [h for h in r.heating if h.source == "compressor"]
        assert back and back[0].start.at >= at(0.2)
        # The element the cold started stops as the heat pump returns,
        # and the compressor carries the recovery on from there.
        assert r.heating[0].stop == "heat_pump"
        assert back[0].start.at == r.heating[0].end
        assert back[0].start.trigger == "heat_pump_available"

    @pytest.mark.parametrize("mode", [1, 3, 4])
    def test_one_heat_source_on_the_lower_zone(self, mode: int) -> None:
        # Cold for the first half hour, then warm: Electric's lower
        # element, which no other mode runs, hands over to the
        # compressor.
        air = ((at(0), 35.0), (at(0.5), 35.0), (at(0.51), 60.0))
        r = _run(air, upper=138.0, lower=60.0, mode=mode, hours=4)
        lower = [h for h in r.heating if h.zone == "lower"]
        hp = [h for h in r.heating if h.source == "compressor"]
        assert lower and hp
        assert lower[0].stop == "heat_pump"
        assert all(e.end <= c.start.at for e in lower for c in hp)

    def test_nothing_restarts_a_finished_tank(self) -> None:
        # Out of range with nothing heating, the return starts nothing:
        # the heater's own trigger decides, and the tank is above it.
        air = ((at(0), 35.0), (at(0.5), 35.0), (at(0.51), 60.0))
        r = _run(air, upper=139.0, lower=120.0, hours=3)
        assert not r.heating

    def test_short_dips_are_seen(self) -> None:
        # Eight minutes below 41 °F, inside one 10-minute air step.
        air = (
            (at(0), 60.0),
            (at(1.0), 60.0),
            (at(1.01), 35.0),
            (at(1.13), 35.0),
            (at(1.14), 60.0),
        )
        r = _run(air, upper=140.0, lower=139.5, hours=3)
        assert ctl.HEAT_PUMP_UNAVAILABLE in r.reasons

    def test_a_trigger_at_the_setpoint_does_not_stall(self) -> None:
        # The lower trigger fires where Electric's rule starts nothing.
        r = _run(35.0, upper=139.0, lower=141.0, on=140.0, hours=4)
        assert all(h.source == "element" for h in r.heating)

    @pytest.mark.parametrize("mode", [2, 5])
    def test_not_said_where_the_heat_pump_never_runs(self, mode: int) -> None:
        r = _run(35.0, upper=125.0, lower=100.0, mode=mode, hours=3)
        assert ctl.HEAT_PUMP_UNAVAILABLE not in r.reasons

    def test_an_element_on_at_the_start_runs_on(self) -> None:
        r = _run(
            35.0,
            upper=125.0,
            lower=100.0,
            running=True,
            element_running=True,
            mode=3,
            hours=3,
        )
        first = r.heating[0]
        assert (first.source, first.zone) == ("element", "upper")
        assert first.start.cause == "running"
        assert not [h for h in r.heating if h.source == "compressor"]


class TestTheWater:
    def test_the_heat_pump_stops_at_the_top_of_its_water_range(self) -> None:
        r = _run(65.0, upper=140.0, lower=130.0, setpoint=149.9, running=True)
        first = r.heating[0]
        assert first.source == "compressor"
        stop = next(p for p in r.points if p.at >= first.end)
        # Within the integrator's 10-second step of it.
        assert stop.lower_f == pytest.approx(149.0, abs=0.03)

    def test_short_of_a_setpoint_over_it_the_elements_finish(self) -> None:
        r = _run(65.0, upper=145.0, lower=140.0, setpoint=150.0, running=True)
        first = r.heating[0]
        assert (first.source, first.stop) == ("compressor", "envelope")
        assert [h.source for h in r.heating[1:]] == ["element", "element"]
        assert max(p.lower_f for p in r.points) == pytest.approx(150.0, abs=0.1)

    def test_a_draw_below_it_stops_the_heat_pump(self) -> None:
        r = _run(
            65.0,
            upper=60.0,
            lower=55.0,
            running=True,
            hours=3,
            loads=sim.Loads(draws=(sim.Draw(at=at(0.5), gallons=60.0),)),
            environment=sim.Environment(ambient_f=65.0, inlet_f=40.0),
        )
        first = r.heating[0]
        assert (first.source, first.stop) == ("compressor", "envelope")
        assert first.end == at(0.5)
        assert r.heating[1].source == "element"

    def test_the_handover_rests_on_no_other_event(self) -> None:
        # An element heats a tank below 50 °F to its off point; a
        # setpoint write while it runs changes nothing of that.
        quiet = _run(65.0, upper=141.0, lower=45.0, hours=6)
        written = _run(
            65.0,
            upper=141.0,
            lower=45.0,
            hours=6,
            commands=sim.Commands(
                writes=(sim.Write(at=at(1.0), setpoint_f=141.0),)
            ),
        )
        for r in (quiet, written):
            assert [h.source for h in r.heating] == ["element"]
            assert r.heating[0].stop == "target"

    def test_a_tank_below_it_heats_with_the_elements(self) -> None:
        r = _run(65.0, upper=48.0, lower=45.0, hours=12.0)
        assert r.heating[0].source == "element"
        assert ctl.HEAT_PUMP_UNAVAILABLE in r.reasons


class TestTheRange:
    def test_a_range_of_its_own(self) -> None:
        base = sim.site_example_params()
        wide = replace(
            base,
            controller=replace(base.controller, hp_air_range_f=(30.0, 120.0)),
        )
        r = _run(35.0, params=wide)
        assert r.heating[0].source == "compressor"

    def test_it_is_checked(self) -> None:
        with pytest.raises(ValueError, match="low, high"):
            ControllerParams(hp_air_range_f=(113.0, 41.0))


class TestTheAirSpans:
    def _sampler(self, points: list[tuple[datetime, float]]) -> AmbientSampler:
        return AmbientSampler(
            pd.DataFrame(
                {"ambient_f": [v for _, v in points]},
                index=pd.DatetimeIndex([t for t, _ in points]),
            )
        )

    def test_exact_on_the_interpolated_air(self) -> None:
        s = self._sampler([(at(0), 45.0), (at(4), 37.0), (at(8), 45.0)])
        # Below 41 from hour 2 to hour 6.
        assert s.outside(at(0), at(8), 41.0, 113.0) == [(at(2), at(6))]

    def test_held_flat_past_its_ends(self) -> None:
        s = self._sampler([(at(0), 120.0), (at(1), 100.0)])
        out = s.outside(at(-1), at(3), 41.0, 113.0)
        assert out == [(at(-1), at(0) + timedelta(minutes=21))]

    def test_the_high_bound_is_outside(self) -> None:
        s = self._sampler([(at(0), 113.0), (at(1), 113.0)])
        assert s.outside(at(0), at(1), 41.0, 113.0) == [(at(0), at(1))]


class TestTheAnswers:
    """A heat-pump answer says when the heat pump cannot run, or runs
    where its heat was not fitted."""

    SETTINGS = sim.Settings(
        setpoint_f=140.0, hp_lower_off_f=140.0, hp_lower_on_f=105.0
    )

    def test_a_forecast_in_the_cold(self) -> None:
        params = sim.site_example_params()
        state = sim.HeaterState(upper_f=125.0, lower_f=100.0)
        cold = sim.forecast(
            state,
            self.SETTINGS,
            sim.Environment(ambient_f=35.0),
            params,
            at=T0,
            target_time=at(8),
        )
        assert ctl.HEAT_PUMP_UNAVAILABLE in cold.reasons
        cool = sim.forecast(
            state,
            self.SETTINGS,
            sim.Environment(ambient_f=55.0),
            params,
            at=T0,
            target_time=at(8),
        )
        assert ctl.HEAT_PUMP_UNAVAILABLE not in cool.reasons
        # Below the 61 °F the site's heat was fitted from.
        assert HEAT_MAP_OUT_OF_DOMAIN in cool.reasons

    def test_a_running_cycle_in_the_cold(self) -> None:
        a = sim.active_cycle(
            sim.HeaterState(
                upper_f=125.0, lower_f=120.0, compressor_running=True
            ),
            self.SETTINGS,
            sim.Environment(ambient_f=120.0),
            sim.site_example_params(),
            at=T0,
        )
        assert ctl.HEAT_PUMP_UNAVAILABLE in a.reasons

    def test_no_heat_pump_recovery_comes_in_the_cold(self) -> None:
        def scenario(air: float) -> sim.Scenario:
            return sim.Scenario(
                start=T0,
                horizon=timedelta(hours=12),
                tz="UTC",
                state=sim.HeaterState(
                    upper_f=125.0, lower_f=100.0, compressor_running=True
                ),
                settings=self.SETTINGS,
                history=sim.History(compressor_stopped_at=at(-3)),
                environment=sim.Environment(ambient_f=air),
            )

        params = sim.site_example_params()
        assert sim.next_recovery(scenario(65.0), params).outcome == "ok"
        assert sim.next_recovery(scenario(35.0), params).outcome == (
            "unavailable"
        )
        ready = sim.time_to_ready(scenario(35.0), params, bath_gal=60.0)
        assert ctl.HEAT_PUMP_UNAVAILABLE in ready.reasons
        assert "time_to_ready_unavailable" not in ready.reasons
        # Every mode heats as Electric does.
        by_mode = {m.mode: m.ready_in_minutes for m in ready.bath.by_mode}
        assert by_mode["electric"] is not None
        assert set(by_mode.values()) == {by_mode["electric"]}


class TestAtTheEdges:
    """What lands at, or across, an edge of the range."""

    @pytest.mark.parametrize("mode", [1, 3, 4])
    def test_a_pending_start_takes_the_recovery_back(self, mode: int) -> None:
        # A setpoint write pends a start; the air returns before it.
        back = at(0) + timedelta(minutes=10, seconds=15)
        air = ((at(0), 30.0), (back, 30.0), (back + timedelta(seconds=2), 50.0))
        r = _run(
            air,
            upper=139.8,
            lower=95.0,
            mode=mode,
            hours=3,
            commands=sim.Commands(
                writes=(
                    sim.Write(
                        at=at(0) + timedelta(minutes=10), setpoint_f=145.0
                    ),
                )
            ),
        )
        lower = [h for h in r.heating if h.zone == "lower"]
        hp = [h for h in r.heating if h.source == "compressor"]
        assert lower and hp
        assert all(e.end <= c.start.at for e in lower for c in hp)

    def test_the_air_leaving_as_the_lockout_ends(self) -> None:
        # The air leaves at the instant the lockout ends: the elements
        # take the start, with no compressor run of no length.
        out = at(0) + timedelta(minutes=4, seconds=30)
        back = out + timedelta(minutes=2)
        air = (
            (at(0), 50.0),
            (out, 41.0),
            (out + timedelta(seconds=1), 35.0),
            (back - timedelta(seconds=1), 35.0),
            (back, 41.0),
            (back + timedelta(seconds=1), 50.0),
        )
        r = _run(
            air,
            upper=120.0,
            lower=95.0,
            hours=3,
            history=sim.History(compressor_stopped_at=at(-1 / 60)),
        )
        assert all(h.end > h.start.at for h in r.heating)
        assert r.heating[0].source == "element"
        assert r.heating[1].source == "compressor"
        assert r.heating[1].start.at == back

    def test_a_draw_at_the_trigger_is_read_first(self) -> None:
        # The draw leaves the upper zone short: Electric's rule starts
        # the upper element first.
        r = _run(
            30.0,
            upper=140.6,
            lower=140.0,
            hours=3,
            loads=sim.Loads(
                draws=(sim.Draw(at=at(1) + timedelta(minutes=3), gallons=40.0),)
            ),
        )
        assert [h.zone for h in r.heating[:2]] == ["upper", "lower"]

    @pytest.mark.parametrize(
        ("mode", "write"),
        [(2, sim.Write(at=at(1), mode=1)), (1, sim.Write(at=at(1), mode=3))],
    )
    def test_a_write_out_of_range_says_so(
        self, mode: int, write: sim.Write
    ) -> None:
        r = _run(
            30.0,
            upper=139.5,
            lower=139.5,
            mode=mode,
            hours=3,
            commands=sim.Commands(writes=(write,)),
        )
        assert r.heating and r.heating[0].source == "element"
        assert ctl.ENVELOPE_FALLBACK_UNVERIFIED in r.reasons

    def test_a_draw_from_the_top_hands_back(self) -> None:
        # Over 149 °F the elements heat; a draw takes the tank back into
        # range with plenty to do, and the heat pump does it. The upper
        # starts over the setpoint, not at it, so the lower trigger's
        # hold while the upper is not short does not rest on a tie.
        r = _run(
            65.0,
            upper=150.0,
            lower=149.3,
            setpoint=149.9,
            on=149.5,
            hours=3,
            loads=sim.Loads(
                draws=(
                    sim.Draw(at=at(0) + timedelta(seconds=20), gallons=45.0),
                )
            ),
        )
        assert [h.source for h in r.heating] == ["compressor"]
        assert all(h.end > h.start.at for h in r.heating)

    def test_a_step_at_one_instant(self) -> None:
        step = at(0.5)
        air = ((at(0), 50.0), (step, 50.0), (step, 30.0), (at(2), 30.0))
        r = _run(air, upper=120.0, lower=100.0, hours=3)
        first = r.heating[0]
        assert (first.source, first.stop) == ("compressor", "envelope")
        assert first.end == step

    def test_more_readings_on_the_same_line_change_nothing(self) -> None:
        def line(t: datetime) -> float:
            return 62.0 + 26.0 * (t - T0).total_seconds() / (4 * 3600)

        two = ((at(0), 62.0), (at(4), 88.0))
        dense = tuple(
            sorted(
                {
                    *two,
                    *(
                        (
                            at(0) + timedelta(seconds=10 * k),
                            line(at(0) + timedelta(seconds=10 * k)),
                        )
                        for k in range(1, 120)
                    ),
                }
            )
        )
        a, b = (
            _run(air, upper=130.0, lower=110.0, on=125.0, hours=5)
            for air in (two, dense)
        )
        assert [(h.end, h.input_wh) for h in a.heating] == [
            (h.end, h.input_wh) for h in b.heating
        ]


class TestTheAnswersAtTheEdges:
    SETTINGS = sim.Settings(
        setpoint_f=140.0, hp_lower_off_f=140.0, hp_lower_on_f=95.0
    )

    def test_the_heat_pump_mode_waits_for_its_trigger(self) -> None:
        s = sim.Scenario(
            start=T0,
            horizon=timedelta(hours=12),
            tz="UTC",
            state=sim.HeaterState(upper_f=112.0, lower_f=100.0),
            settings=self.SETTINGS,
            history=sim.History(compressor_stopped_at=at(-3)),
            environment=sim.Environment(ambient_f=30.0),
        )
        params = sim.site_example_params()
        nxt = sim.next_recovery(s, params)
        assert nxt.hp_unavailable and nxt.start_minute > 60.0
        ready = sim.time_to_ready(s, params, bath_gal=30.0)
        by_mode = {m.mode: m.ready_in_minutes for m in ready.bath.by_mode}
        assert by_mode["heat_pump"] is not None
        assert by_mode["electric"] is not None
        # The elements in Heat Pump mode start at the heater's trigger;
        # a write to an element mode starts them now.
        assert by_mode["heat_pump"] >= nxt.start_minute
        assert by_mode["electric"] < nxt.start_minute

    def test_a_target_over_the_top(self) -> None:
        a = sim.active_cycle(
            sim.HeaterState(
                upper_f=125.0, lower_f=120.0, compressor_running=True
            ),
            sim.Settings(
                setpoint_f=149.9, hp_lower_off_f=149.9, hp_lower_on_f=105.0
            ),
            sim.Environment(ambient_f=65.0),
            sim.site_example_params(),
            at=T0,
        )
        assert ctl.HEAT_PUMP_UNAVAILABLE in a.reasons


def _secs(n: float) -> datetime:
    return T0 + timedelta(seconds=n)


class TestTheHandOver:
    """Who heats across a return, and what it says."""

    @pytest.mark.parametrize("to", [3, 4])
    def test_in_range_an_electric_element_runs_on(self, to: int) -> None:
        # Nothing heats in the heat pump's place here: a write out of
        # Electric leaves its lower element to its target, as before.
        r = _run(
            60.0,
            upper=141.0,
            lower=100.0,
            mode=2,
            hours=3,
            element_running=True,
            commands=sim.Commands(writes=(sim.Write(at=at(1 / 6), mode=to),)),
        )
        lower = [h for h in r.heating if h.zone == "lower"]
        assert lower[0].stop == "target"

    def test_a_draw_back_into_range_waits_out_the_lockout(self) -> None:
        r = _run(
            70.0,
            upper=150.0,
            lower=149.5,
            setpoint=150.0,
            hours=2,
            history=sim.History(compressor_stopped_at=at(-1 / 60)),
            loads=sim.Loads(draws=(sim.Draw(at=at(1 / 60), gallons=45.0),)),
        )
        hp = [h for h in r.heating if h.source == "compressor"]
        lockout = sim.site_example_params().controller.restart_lockout
        assert hp and hp[0].start.at >= at(-1 / 60) + lockout

    def test_an_air_dip_keeps_the_cold_tank_hold(self) -> None:
        air = (
            (at(0), 70.0),
            (at(10 / 60), 70.0),
            (at(10 / 60) + timedelta(seconds=1), 30.0),
            (at(12 / 60), 30.0),
            (at(12 / 60) + timedelta(seconds=1), 70.0),
        )
        r = _run(air, upper=140.0, lower=45.0, hours=3)
        assert [h.source for h in r.heating] == ["element"]
        assert r.heating[0].stop == "target"

    def test_too_little_room_with_a_start_pending(self) -> None:
        # A write pends a start; the air returns with the lower zone too
        # near the top for the heat pump, and the elements finish.
        air = ((at(0), 30.0), (_secs(40), 30.0), (_secs(41), 70.0))
        r = _run(
            air,
            upper=146.0,
            lower=146.5,
            setpoint=149.0,
            hours=3,
            element_running=True,
            commands=sim.Commands(
                writes=(sim.Write(at=_secs(30), setpoint_f=149.9),)
            ),
        )
        assert all(h.source == "element" for h in r.heating)

    def test_a_return_is_not_a_write(self) -> None:
        air = ((at(0), 30.0), (_secs(20), 30.0), (_secs(21), 70.0))
        r = _run(
            air,
            upper=138.0,
            lower=138.5,
            hours=2,
            element_running=True,
        )
        assert "write_start_uncertain" not in r.reasons


class TestTheAnswersOverTheTop:
    def test_a_stop_past_the_top_is_flagged(self) -> None:
        # The target is under 149 °F; its run-on is not.
        a = sim.active_cycle(
            sim.HeaterState(
                upper_f=140.0, lower_f=130.0, compressor_running=True
            ),
            sim.Settings(
                setpoint_f=148.5, hp_lower_off_f=148.5, hp_lower_on_f=105.0
            ),
            sim.Environment(ambient_f=70.0),
            sim.site_example_params(),
            at=T0,
        )
        assert ctl.HEAT_PUMP_UNAVAILABLE in a.reasons

    def test_time_to_ready_over_the_top(self) -> None:
        s = sim.Scenario(
            start=T0,
            horizon=timedelta(hours=12),
            tz="UTC",
            state=sim.HeaterState(
                upper_f=120.0, lower_f=100.0, compressor_running=True
            ),
            settings=sim.Settings(
                setpoint_f=150.0,
                hp_lower_off_f=150.0,
                hp_lower_on_f=105.0,
                # Resting: outside a TOU window.
                hp_upper_on_f=104.9,
            ),
            history=sim.History(compressor_stopped_at=at(-3)),
            environment=sim.Environment(ambient_f=70.0),
        )
        ready = sim.time_to_ready(s, sim.site_example_params(), bath_gal=60.0)
        assert ctl.HEAT_PUMP_UNAVAILABLE in ready.reasons

    def test_heat_pump_mode_heats_from_the_coasted_tank(self) -> None:
        s = sim.Scenario(
            start=T0,
            horizon=timedelta(hours=12),
            tz="UTC",
            state=sim.HeaterState(upper_f=112.0, lower_f=100.0),
            settings=sim.Settings(
                setpoint_f=140.0, hp_lower_off_f=140.0, hp_lower_on_f=95.0
            ),
            history=sim.History(compressor_stopped_at=at(-3)),
            environment=sim.Environment(ambient_f=30.0),
        )
        params = sim.site_example_params()
        nxt = sim.next_recovery(s, params)
        ready = sim.time_to_ready(s, params, bath_gal=30.0)
        by_mode = {m.mode: m.ready_in_minutes for m in ready.bath.by_mode}
        hp, electric = by_mode["heat_pump"], by_mode["electric"]
        assert hp is not None and electric is not None
        # As Electric from the tank the coast leaves at the trigger: its
        # layers as the walk carries them.
        (when, upper, lower), *_ = nxt.points
        walk = sim.simulate(
            s.model_copy(update={"horizon": timedelta(hours=24)}), params
        ).simulation
        layers = next(p.layers_f for p in walk.points if p.at >= when)
        then = sim.time_to_ready(
            s.model_copy(
                update={
                    "start": when,
                    "state": sim.HeaterState(
                        upper_f=upper, lower_f=lower, layers_f=layers
                    ),
                }
            ),
            params,
            bath_gal=30.0,
        )
        from_there = {m.mode: m.ready_in_minutes for m in then.bath.by_mode}
        assert from_there["electric"] is not None
        assert hp == pytest.approx(
            nxt.start_minute + from_there["electric"], abs=1.0
        )
        assert hp > nxt.start_minute + electric


class TestInThePlaceOfTheHeatPump:
    """Which elements heat in the heat pump's place, across mode
    changes, and are handed back to it."""

    AIR = (
        (at(0), 30.0),
        (at(0.5), 30.0),
        (at(0.5) + timedelta(seconds=1), 70.0),
    )

    def test_a_write_out_of_electric_puts_its_element_in_place(self) -> None:
        r = _run(
            self.AIR,
            upper=120.0,
            lower=100.0,
            mode=2,
            hours=4,
            element_running=True,
            commands=sim.Commands(writes=(sim.Write(at=at(0.25), mode=1),)),
        )
        lower = [h for h in r.heating if h.zone == "lower"]
        hp = [h for h in r.heating if h.source == "compressor"]
        assert lower and hp
        assert all(e.end <= c.start.at for e in lower for c in hp)

    def test_a_write_into_electric_makes_it_electrics_own(self) -> None:
        # An element starts in the heat pump's place; a write to
        # Electric makes it Electric's, which a later write's start
        # leaves running, as it does an element Electric started.
        writes = (
            sim.Write(at=at(5 / 60), mode=2),
            sim.Write(at=at(35 / 60), mode=3),
        )
        r = _run(
            self.AIR,
            upper=139.0,
            lower=90.0,
            hours=4,
            commands=sim.Commands(writes=writes),
        )
        lower = [h for h in r.heating if h.zone == "lower"]
        assert lower and lower[-1].stop == "target"

    def test_a_write_into_the_heat_pump_out_of_range_says_so(self) -> None:
        r = _run(
            30.0,
            upper=141.0,
            lower=140.5,
            mode=2,
            hours=2,
            commands=sim.Commands(writes=(sim.Write(at=at(0.25), mode=1),)),
        )
        assert ctl.HEAT_PUMP_UNAVAILABLE in r.reasons

    @pytest.mark.parametrize("mode", [3, 4])
    def test_a_dip_hands_back_nothing_it_did_not_take(self, mode: int) -> None:
        # The mode's own element, running before a 5-second dip, is not
        # a recovery the heat pump owes.
        s1 = timedelta(seconds=1)
        air = (
            (at(0), 70.0),
            (at(2 / 60), 70.0),
            (at(2 / 60) + s1, 30.0),
            (at(2 / 60) + 5 * s1, 30.0),
            (at(2 / 60) + 6 * s1, 70.0),
        )
        r = _run(
            air,
            upper=110.0,
            lower=135.0,
            mode=mode,
            hours=3,
            element_running=True,
        )
        assert not [h for h in r.heating if h.source == "compressor"]

    def test_a_capped_recovery_is_not_over_the_top(self) -> None:
        peak = sim.TouPeriod(
            season=0xFFF,
            week=0xFE,
            start_hour=0,
            start_minute=0,
            end_hour=23,
            end_minute=58,
            price_max=5,
        )
        s = sim.Scenario(
            start=T0,
            horizon=timedelta(hours=12),
            tz="UTC",
            state=sim.HeaterState(
                upper_f=120.0, lower_f=100.0, compressor_running=True
            ),
            settings=sim.Settings(
                setpoint_f=149.0, hp_lower_off_f=149.0, hp_lower_on_f=105.0
            ),
            history=sim.History(compressor_stopped_at=at(-3)),
            environment=sim.Environment(ambient_f=70.0),
            schedules=sim.Schedules(tou_enabled=True, tou_periods=(peak,)),
        )
        params = sim.site_example_params()
        assert sim.next_recovery(s, params).tou_capped
        ready = sim.time_to_ready(s, params, bath_gal=60.0)
        assert ctl.HEAT_PUMP_UNAVAILABLE not in ready.reasons


class TestTheHeatMapsWater:
    """The heat's map was fitted on mixed climbs against the probes'
    mean, 114 to 144 °F on the site's record: a recovery with the mean
    outside that span reads the plane past its evidence and says so,
    the air in its span or not."""

    SETTINGS = sim.Settings(setpoint_f=130.0, hp_lower_on_f=111.0, mode=1)

    def _walk(self, upper: float, lower: float) -> sim.SimulationResult:
        return sim.simulate(
            sim.Scenario(
                start=T0,
                horizon=timedelta(hours=12),
                tz="UTC",
                state=sim.HeaterState(upper_f=upper, lower_f=lower),
                settings=self.SETTINGS,
                environment=sim.Environment(ambient_f=67.5, inlet_f=58.0),
            ),
            sim.site_example_params(),
        )

    def test_a_cold_tank_says_so(self) -> None:
        cold = self._walk(58.0, 58.0)
        assert any(h.source == "compressor" for h in cold.heating)
        assert HEAT_MAP_OUT_OF_DOMAIN in cold.reasons

    def test_a_tank_at_its_trigger_does_not(self) -> None:
        """The lower probe at the trigger, the upper near the setpoint:
        the mean is in the span, though the condenser's water the map is
        read at is under it."""
        warm = self._walk(125.0, 110.9)
        assert any(h.source == "compressor" for h in warm.heating)
        assert HEAT_MAP_OUT_OF_DOMAIN not in warm.reasons

    def test_a_forecast_from_a_cold_tank_says_so(self) -> None:
        params = sim.site_example_params()
        for state, flagged in (
            (sim.HeaterState(upper_f=60.0, lower_f=58.0), True),
            (sim.HeaterState(upper_f=128.0, lower_f=110.0), False),
        ):
            got = sim.forecast(
                state,
                self.SETTINGS,
                sim.Environment(ambient_f=67.5),
                params,
                at=T0,
                target_time=at(10),
            )
            assert (HEAT_MAP_OUT_OF_DOMAIN in got.reasons) is flagged

    def test_the_walk_books_the_hours(self) -> None:
        """Its books count the compressor's hours with the mean outside
        the span, and none inside it."""
        params = sim.site_example_params()
        lay = st.layout(params)
        books: dict[str, st.Books] = {}
        for name, (upper, lower) in (
            ("cold", (60.0, 58.0)),
            ("warm", (128.0, 120.0)),
        ):
            walked = st.walk(
                lay,
                st.estimate(lay, upper, lower),
                T0,
                T0 + timedelta(hours=1),
                air_f=lambda _: 67.5,
                heating=st.Heating(
                    compressor=st.Compressor(
                        params=params.compressor, on_at=T0, heats_at=T0
                    )
                ),
            )
            books[name] = walked.books
        assert books["cold"].compressor_outside_water_h == pytest.approx(
            books["cold"].compressor_h
        )
        assert books["warm"].compressor_outside_water_h == 0.0
