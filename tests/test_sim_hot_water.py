"""Hot water at the tap through the API: the delivery along a
simulation, draw windows, and ``readiness``, from the tank's layers.

The functions they call are held to the layered tank in
``test_sim_readiness``.
"""

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from nwp500 import sim_adapters as sa
from nwp500.sim import (
    Draw,
    DrawWindow,
    Environment,
    HeaterState,
    History,
    Loads,
    Scenario,
    Settings,
    readiness,
    simulate,
    site_example_params,
)
from nwp500.sim.circulation import Circulation
from nwp500.sim.codec import (
    result_to_document,
    scenario_from_document,
    scenario_to_document,
)
from nwp500.sim.delivery import deliverable, delivery_along
from nwp500.sim.engine import Heater
from nwp500.sim.engine import simulate as walk
from nwp500.sim.params import (
    CirculationParams,
    HeaterParams,
    LossParams,
    params_from_document,
    params_to_document,
    unknown_fields,
)
from nwp500.sim.physics.heat_pump import start_hold_min
from nwp500.sim.tank_physics import TankPhysics, TankState
from nwp500.unit_system import reset_unit_system, set_unit_system

FIXTURES = Path(__file__).with_name("fixtures") / "sim"
T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
FULL = (140.5, 139.6)


def at(h: float) -> datetime:
    return T0 + timedelta(hours=h)


#: 100 delivered gallons over 40 minutes from 19:30, in 2.5 gal minutes:
#: more than the full tank delivers through the site's valve.
BIG = tuple(
    Draw(at=at(0.5) + timedelta(minutes=i), gallons=2.5) for i in range(40)
)
BIG_WINDOW = DrawWindow(start=at(0.5), end=at(1.25), expected_gal=100.0)


@pytest.fixture(scope="module")
def params() -> HeaterParams:
    """One installation's parameters, its mixing valve included: the
    numbers below are that site's."""
    return site_example_params()


@pytest.fixture(autouse=True)
def _units() -> Iterator[None]:
    yield
    reset_unit_system()


def _scenario(**kw: Any) -> Scenario:
    base: dict[str, Any] = {
        "start": T0,
        "horizon": timedelta(hours=6),
        "tz": "UTC",
        "state": HeaterState(upper_f=FULL[0], lower_f=FULL[1]),
        "settings": Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
        "history": History(compressor_stopped_at=at(-1.0)),
        "environment": Environment(ambient_f=68.0, humidity=48.0),
        "loads": Loads(draws=BIG, windows=(BIG_WINDOW,)),
    }
    base.update(kw)
    return Scenario(**base)


def _by_hand(params: HeaterParams, s: Scenario) -> Any:
    """The engine called directly, with the windows' edges marked, on a
    flat ambient."""
    stamps = pd.date_range(at(-2), s.until + timedelta(hours=24), freq="1h")
    frame = pd.DataFrame({"ambient_f": [68.0] * len(stamps)}, index=stamps)
    physics = TankPhysics(
        params,
        frame,
        s.environment.humidity,
        draws_on=True,
        draw_inlet_temp_f=params.draw.mains_on(s.start),
    )
    return walk(
        start=s.start,
        upper_f=s.state.upper_f,
        lower_f=s.state.lower_f,
        running=False,
        until=s.until,
        setpoint_f=s.settings.setpoint_f,
        heater=Heater(hp_lower_on_f=105.0, element=params.element),
        physics=physics,
        draws=[(d.at, d.gallons, False) for d in s.loads.draws],
        marks=[x for w in s.loads.windows for x in (w.start, w.end)],
        stopped_at=s.history.compressor_stopped_at,
        start_hold=lambda off: start_hold_min(params.compressor, off),
        controller=params.controller,
    )


class TestTheDeliveryInASimulation:
    def test_simulate_is_the_engine_alone(self, params: HeaterParams) -> None:
        """The delivery reads the walk; it does not move the tank."""
        s = _scenario()
        assert simulate(s, params).simulation == _by_hand(params, s)

    def test_energy_saver_starts_on_a_draw(self, params: HeaterParams) -> None:
        """The draw is taken at its instant; its drop releases Energy
        Saver's held lower trigger (2026-09-21: the upper tank over the
        setpoint, the lower under its setting, a draw started it)."""
        held: dict[str, Any] = {
            "state": HeaterState(upper_f=126.0, lower_f=87.0),
            "settings": Settings(setpoint_f=107.6, hp_lower_on_f=104.9, mode=3),
            "history": History(compressor_stopped_at=at(-8.0)),
        }
        s = _scenario(
            **held, loads=Loads(draws=(Draw(at=at(1.0), gallons=5.0),))
        )
        heating = simulate(s, params).simulation.heating
        assert heating and heating[0].start.at == at(1.0)
        quiet = _scenario(**held, loads=Loads())
        assert simulate(quiet, params).simulation.heating == []

    def test_a_release_the_lockout_defers_survives_the_next_draw(
        self, params: HeaterParams
    ) -> None:
        """A draw releases Energy Saver's held lower trigger inside the
        restart lockout; the next draw, a minute on, leaves the lower
        zone over its setting. The start still comes when the lockout
        ends."""
        stop = at(1.0) - timedelta(minutes=2)
        second = at(1.0) + timedelta(minutes=1)

        class SecondLeavesItWarm(TankPhysics):
            def draw(
                self,
                at: datetime,
                state: TankState,
                gal: float,
                undiluted: bool = False,
            ) -> Any:
                got = super().draw(at, state, gal, undiluted)
                if at != second:
                    return got
                return self.estimate(self.observe(got)[0], 106.0)

        stamps = pd.date_range(at(-2), at(30), freq="1h")
        frame = pd.DataFrame({"ambient_f": [68.0] * len(stamps)}, index=stamps)
        physics = SecondLeavesItWarm(params, frame, 48.0, draws_on=True)
        sim = walk(
            start=stop + timedelta(minutes=1),
            upper_f=126.0,
            lower_f=87.0,
            running=False,
            until=at(3.0),
            setpoint_f=107.6,
            heater=Heater(
                hp_lower_on_f=104.9, mode="energy_saver", element=params.element
            ),
            physics=physics,
            draws=[(at(1.0), 5.0, False), (second, 1.0, False)],
            stopped_at=stop,
            controller=params.controller,
        )
        lockout = timedelta(seconds=params.controller.restart_lockout_s)
        assert sim.heating and sim.heating[0].start.at == stop + lockout

    def test_a_release_by_circulation_in_the_lockout_survives_a_draw(
        self, params: HeaterParams
    ) -> None:
        """A circulation run releases Energy Saver's held lower trigger
        inside the restart lockout, and a draw after it leaves the lower
        zone over its setting: the start still comes when the lockout
        ends."""
        stop = at(1.0) - timedelta(minutes=2)
        draw = at(1.0) + timedelta(minutes=3)
        run = (at(1.0), at(1.0) + timedelta(minutes=2))

        class DrawLeavesItWarm(TankPhysics):
            def draw(
                self,
                at: datetime,
                state: TankState,
                gal: float,
                undiluted: bool = False,
            ) -> Any:
                got = super().draw(at, state, gal, undiluted)
                return self.estimate(self.observe(got)[0], 106.0)

        stamps = pd.date_range(at(-2), at(30), freq="1h")
        frame = pd.DataFrame({"ambient_f": [68.0] * len(stamps)}, index=stamps)
        physics = DrawLeavesItWarm(
            params,
            frame,
            48.0,
            draws_on=True,
            circulation=Circulation((run,)),
            # Two gallons of the pipe's water back at 70 °F.
            circulation_terms=CirculationParams(
                displaced_gal=2.0,
                flow_gpm=1.0,
                return_rest_offset_f=2.0,
                return_cool_tau_h=0.0,
            ),
        )
        sim = walk(
            start=stop + timedelta(minutes=1),
            upper_f=126.0,
            lower_f=87.0,
            running=False,
            until=at(3.0),
            setpoint_f=107.6,
            heater=Heater(
                hp_lower_on_f=104.9, mode="energy_saver", element=params.element
            ),
            physics=physics,
            draws=[(draw, 1.0, False)],
            stopped_at=stop,
            controller=params.controller,
        )
        lockout = timedelta(seconds=params.controller.restart_lockout_s)
        assert sim.heating and sim.heating[0].start.at == stop + lockout

    def test_a_draw_moves_the_lower_probe_at_once(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(loads=Loads(draws=(Draw(at=at(0.5), gallons=20.0),)))
        points = simulate(s, params).points
        before, after = [p for p in points if p.at == at(0.5)]
        assert after.lower_f < before.lower_f - 1.0

    def test_the_delivery_is_the_layers(self, params: HeaterParams) -> None:
        r = simulate(_scenario(), params)
        assert list(r.delivery) == delivery_along(r.points, params)
        assert len(r.delivery) == len(r.points)
        assert all(p.layers_f is not None for p in r.points)

    def test_the_book_is_gone_from_the_reasons(
        self, params: HeaterParams
    ) -> None:
        r = simulate(_scenario(), params)
        assert not {"no_heat_book", "heat_book_aged"} & set(r.reasons)


class TestDrawWindows:
    def test_a_window_the_tank_cannot_supply_runs_cold(
        self, params: HeaterParams
    ) -> None:
        (w,) = simulate(_scenario(), params).windows
        assert w.depleted
        assert w.delivery_min_f < params.readiness.line_f
        assert w.margin_gal is not None and w.margin_gal < 0.0
        # Half an hour's standby from the full tank's, at the day's
        # mains.
        mains = params.draw.mains_on(T0)
        full = deliverable(params, *FULL, inlet_f=mains).gal
        assert full - 1.0 < w.deliverable_gal < full

    def test_a_window_the_tank_can_supply_does_not(
        self, params: HeaterParams
    ) -> None:
        small = tuple(
            Draw(at=at(0.5) + timedelta(minutes=i), gallons=1.6)
            for i in range(8)
        )
        window = DrawWindow(start=at(0.5), end=at(0.75), expected_gal=12.8)
        s = _scenario(loads=Loads(draws=small, windows=(window,)))
        (w,) = simulate(s, params).windows
        assert not w.depleted
        assert w.margin_gal is not None and w.margin_gal > 20.0

    def test_the_margin_and_the_delivery_agree(
        self, params: HeaterParams
    ) -> None:
        """With nothing heating, a window drawing a little less than the
        tank delivers at its onset does not run cold, and one drawing a
        little more does: the gallons and the delivery read the same
        layers."""
        off = Settings(setpoint_f=140.9, mode=6)

        def window(drawn: float) -> Any:
            n = 40
            draws = tuple(
                Draw(at=at(0.5) + timedelta(minutes=i), gallons=drawn / n)
                for i in range(n)
            )
            w = DrawWindow(start=at(0.5), end=at(1.25), expected_gal=drawn)
            loads = Loads(draws=draws, windows=(w,))
            s = _scenario(settings=off, loads=loads)
            return simulate(s, params).windows[0]

        gal = window(1.0).deliverable_gal
        short, over = window(gal - 2.0), window(gal + 2.0)
        assert not short.depleted
        assert short.margin_gal == pytest.approx(2.0, abs=0.05)
        assert over.depleted
        assert over.margin_gal == pytest.approx(-2.0, abs=0.05)

    def test_a_windows_edges_are_on_the_path(
        self, params: HeaterParams
    ) -> None:
        r = simulate(_scenario(), params)
        instants = {p.at for p in r.points}
        assert BIG_WINDOW.start in instants and BIG_WINDOW.end in instants

    def test_a_window_must_end_after_it_starts(self) -> None:
        with pytest.raises(ValueError, match="ends after"):
            DrawWindow(start=at(1.0), end=at(1.0))


class TestReadiness:
    def test_without_layers_the_probes_answer(
        self, params: HeaterParams
    ) -> None:
        d = readiness(
            HeaterState(upper_f=FULL[0], lower_f=FULL[1]),
            Settings(setpoint_f=140.9),
            params,
        )
        assert d.basis == "probes"
        assert d == deliverable(params, *FULL)

    def test_with_layers_they_answer(self, params: HeaterParams) -> None:
        layers = (120.0,) * 6 + (140.5,) * 6
        d = readiness(
            HeaterState(upper_f=FULL[0], lower_f=FULL[1], layers_f=layers),
            Settings(setpoint_f=140.9),
            params,
        )
        assert d.basis == "layers"
        assert d == deliverable(params, *FULL, layers)

    def test_at_the_scenarios_inlet(self, params: HeaterParams) -> None:
        state = HeaterState(upper_f=FULL[0], lower_f=FULL[1])
        settings = Settings(setpoint_f=140.9)
        cold = readiness(state, settings, params, inlet_f=45.0)
        warm = readiness(state, settings, params, inlet_f=75.0)
        assert cold.gal < warm.gal

    @pytest.mark.parametrize(
        "running", [{"compressor_running": True}, {"element_running": True}]
    )
    def test_a_running_heater_reads_the_same(
        self, params: HeaterParams, running: dict[str, bool]
    ) -> None:
        settings = Settings(setpoint_f=140.9)
        for upper, lower in (FULL, (136.4, 111.4), (128.0, 95.0)):
            heating = readiness(
                HeaterState.model_validate(
                    {"upper_f": upper, "lower_f": lower, **running}
                ),
                settings,
                params,
            )
            idle = readiness(
                HeaterState(upper_f=upper, lower_f=lower), settings, params
            )
            assert heating == idle

    def test_the_line_moves_the_answer(self, params: HeaterParams) -> None:
        state = HeaterState(upper_f=112.0, lower_f=100.0)
        settings = Settings(setpoint_f=140.9)
        higher = replace(
            params, readiness=replace(params.readiness, line_f=125.0)
        )
        assert readiness(state, settings, params).gal > 0.0
        assert readiness(state, settings, higher).gal == 0.0


class TestTheParameters:
    def test_readiness_round_trips_as_a_document(
        self, params: HeaterParams
    ) -> None:
        doc = json.loads(json.dumps(params_to_document(params)))
        assert params_from_document(doc) == params
        assert set(doc["readiness"]) == {
            "line_f",
            "probe_resolution_f",
            "bath_gal",
            "shower_gal",
        }
        assert "book" not in doc

    def test_the_books_and_the_evidences_terms_are_read_past(
        self, params: HeaterParams
    ) -> None:
        """A document fitted with the heat book reads: its book part,
        its readiness evidence and the retired names in ``unfitted``
        are named and left out."""
        doc = json.loads(json.dumps(params_to_document(params)))
        doc["book"] = {"tank_gal": 63.2, "empty_btu": 16000.0}
        doc["readiness"]["evidence"] = [[140.0, 139.0, 40.0]]
        doc["readiness"]["delivered_lag_gal"] = 5.0
        doc["unfitted"] = ["book", "readiness"]
        assert unknown_fields(doc) == [
            "book",
            "readiness.evidence",
            "readiness.delivered_lag_gal",
        ]
        assert params_from_document(doc) == params

    def test_the_books_draw_flow_is_the_draws(
        self, params: HeaterParams
    ) -> None:
        doc = json.loads(json.dumps(params_to_document(params)))
        del doc["draw"]["draw_gpm"]
        doc["book"] = {"draw_gpm": 0.5}
        assert params_from_document(doc).draw.draw_gpm == 0.5
        doc["draw"]["draw_gpm"] = 0.4
        assert params_from_document(doc).draw.draw_gpm == 0.4

    def test_a_document_without_readiness_takes_the_defaults(
        self, params: HeaterParams
    ) -> None:
        doc = params_to_document(params)
        del doc["readiness"]
        assert params_from_document(doc) == replace(
            params, readiness=type(params.readiness)()
        )

    def test_a_document_from_before_the_map_is_refused(
        self, params: HeaterParams
    ) -> None:
        """A ``heater-params/1`` document ran the refrigerant cycle: it
        is refitted, not read."""
        doc = {**params_to_document(params), "schema": "heater-params/1"}
        with pytest.raises(ValueError, match="calibrate again"):
            params_from_document(doc)

    @pytest.mark.parametrize(
        "two_zone",
        [
            {"loss": {"ua_btu_hr_f": 4.48, "bottom_loss_btu_hr": 90.8}},
            {"unfitted": ["standby", "gap_tau"]},
        ],
    )
    def test_a_two_zone_document_reads_with_the_tank_unfitted(
        self, params: HeaterParams, two_zone: dict[str, Any]
    ) -> None:
        """Its tank's terms are the two zones', which the layers do not
        read: the tank is the priors', and says so."""
        doc = {**params_to_document(params), **two_zone}
        read = params_from_document(doc)
        assert "tank" in read.unfitted
        assert not {"standby", "gap_tau"} & set(read.unfitted)
        if "loss" in two_zone:
            assert read.loss == LossParams()

    def test_a_document_the_two_zone_code_wrote_reads(self) -> None:
        """The site example as the two-zone code wrote it: its sides'
        loss null, its tank and draw response the zones'."""
        doc = json.loads((FIXTURES / "heater_params_two_zone.json").read_text())
        read = params_from_document(doc)
        assert read.unfitted == ("tank",)
        assert read.loss == LossParams()
        assert read.tank.volume_gal == 63.2

    @pytest.mark.parametrize(
        ("part", "name", "value", "match"),
        [
            (None, "unfitted", None, "unfitted is None, not a list"),
            (None, "unfitted", 5, "unfitted is 5, not a list"),
            (None, "unfitted", "tank", "not a list"),
            ("draw", "domain_upper_f", 5, "domain_upper_f is 5, not a list"),
            ("draw", "domain_upper_f", [1.0], "has 1 values, not 2"),
            ("readiness", "line_f", "105", "line_f is '105', not a number"),
            ("tank", "volume_gal", "65", "volume_gal is '65', not a number"),
            ("tank", "volume_gal", None, "not a number"),
            ("tank", "volume_gal", True, "not a number"),
        ],
    )
    def test_a_value_of_the_wrong_type_is_a_value_error(
        self,
        params: HeaterParams,
        part: str | None,
        name: str,
        value: object,
        match: str,
    ) -> None:
        doc = params_to_document(params)
        (doc if part is None else doc[part])[name] = value
        with pytest.raises(ValueError, match=match):
            params_from_document(doc)

    def test_a_newer_field_is_named_and_read_past(
        self, params: HeaterParams
    ) -> None:
        doc = json.loads(json.dumps(params_to_document(params)))
        doc["readiness"]["newer_f"] = 1.0
        assert unknown_fields(doc) == ["readiness.newer_f"]
        assert params_from_document(doc) == params

    def test_a_part_that_is_not_an_object_has_no_unknown_fields(
        self, params: HeaterParams
    ) -> None:
        doc = {**params_to_document(params), "tank": 5}
        assert unknown_fields(doc) == []
        with pytest.raises(ValueError, match="part 'tank' is not an object"):
            params_from_document(doc)

    def test_a_null_range_and_a_whole_number_are_read(
        self, params: HeaterParams
    ) -> None:
        doc = params_to_document(params)
        doc["draw"]["domain_upper_f"] = None
        doc["tank"]["volume_gal"] = 50
        got = params_from_document(doc)
        assert got.draw.domain_upper_f is None
        assert got.tank.volume_gal == 50


class TestTheAdaptersAndTheCodec:
    def test_windows_in_the_preferred_units(self) -> None:
        set_unit_system("metric")
        loads = sa.loads(
            [(at(0.5), 37.85411784)], windows=[(at(0.5), at(1.0), 75.70823568)]
        )
        assert loads.draws[0].gallons == pytest.approx(10.0)
        assert loads.windows[0].expected_gal == pytest.approx(20.0)

    def test_the_path_carries_the_delivery(self, params: HeaterParams) -> None:
        r = simulate(_scenario(), params)
        set_unit_system("metric")
        path = sa.path(r)
        assert path[-1].delivery == pytest.approx(
            (r.delivery[-1] - 32.0) * 5.0 / 9.0
        )

    def test_a_scenario_with_windows_round_trips(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        back, _ = scenario_from_document(json.dumps(scenario_to_document(s)))
        assert back == s

    def test_a_result_document_holds_the_delivery_and_the_windows(
        self, params: HeaterParams
    ) -> None:
        r = simulate(_scenario(), params)
        doc = result_to_document(r)
        assert json.loads(json.dumps(doc)) == doc
        assert doc["delivery"] == list(r.delivery)
        assert doc["windows"][0]["depleted"] is True

    def test_a_tap_that_never_runs_cold_is_null_in_a_document(
        self, params: HeaterParams
    ) -> None:
        """A mains at or above the line never takes the tap under it:
        unbounded gallons, which JSON holds as null."""
        hot = Environment(ambient_f=68.0, humidity=48.0, inlet_f=110.0)
        r = simulate(_scenario(environment=hot), params)
        assert r.windows[0].deliverable_gal == float("inf")
        doc = result_to_document(r)
        assert doc["windows"][0]["deliverable_gal"] is None
        json.dumps(doc, allow_nan=False)
