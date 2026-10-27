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
        assert r.heating[0].stop == "mode"
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
        assert lower[0].stop == "mode"
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
        ready = sim.time_to_ready(scenario(35.0), params, bath_gal=25.0)
        assert ctl.HEAT_PUMP_UNAVAILABLE in ready.reasons
        assert "time_to_ready_unavailable" not in ready.reasons
        # Every mode heats as Electric does.
        by_mode = {m.mode: m.ready_in_minutes for m in ready.bath.by_mode}
        assert by_mode["electric"] is not None
        assert set(by_mode.values()) == {by_mode["electric"]}
