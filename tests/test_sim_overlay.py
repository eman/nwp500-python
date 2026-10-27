"""``sim_live.overlay``: a scenario document laid over the heater's
live scenario, and ``sim.codec.merge``."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nwp500 import sim, sim_live
from nwp500.sim.codec import merge, scenario_to_document
from nwp500.sim.params import params_to_document

NOW = datetime(2026, 10, 18, 14, tzinfo=UTC)
TZ = "America/Los_Angeles"
P65 = sim.default_params()


def _doc(scenario: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "scenario": scenario, **extra}


def _live() -> sim_live.Composed:
    scenario = sim.Scenario(
        start=NOW,
        horizon=timedelta(hours=24),
        tz=TZ,
        state=sim.HeaterState(upper_f=134.0, lower_f=133.0),
        settings=sim.Settings(setpoint_f=140.0, hp_lower_on_f=105.0),
        schedules=sim.Schedules(tou_enabled=True),
        environment=sim.Environment(ambient_f=74.0, inlet_f=60.0),
    )
    reading = sim_live.HeaterReading(
        state=scenario.state,
        settings=scenario.settings,
        environment=scenario.environment,
        params=sim.default_params(2),
        status=None,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        feature=None,
    )
    return sim_live.Composed(scenario, sim.default_params(2), reading)


def _standalone() -> dict[str, Any]:
    """A scenario document with no start, horizon or zone."""
    doc = scenario_to_document(_live().scenario)
    for key in ("start", "horizon", "tz"):
        del doc["scenario"][key]
    return doc


class TestMerge:
    def test_objects_merge_and_other_values_replace(self) -> None:
        base = {"a": {"x": 1, "y": 2}, "b": [1, 2], "c": 1}
        over = {"a": {"y": 3}, "b": [9], "d": 4}
        assert merge(base, over) == {
            "a": {"x": 1, "y": 3},
            "b": [9],
            "c": 1,
            "d": 4,
        }
        assert base["a"] == {"x": 1, "y": 2}


class TestOverlay:
    def test_live_alone_is_the_live_scenario(self) -> None:
        live = _live()
        built = sim_live.overlay(live, now=NOW)
        assert built.scenario == live.scenario
        assert built.params == live.params
        assert built.notes == ()

    def test_the_document_wins_where_it_speaks(self) -> None:
        live = _live()
        doc = _doc({"settings": {"setpoint_f": 120.0}, "horizon": "PT6H"})
        s = sim_live.overlay(live, doc, now=NOW).scenario
        assert s.settings.setpoint_f == 120.0
        assert s.settings.hp_lower_on_f == 105.0
        assert s.horizon == timedelta(hours=6)
        assert s.state == live.scenario.state
        assert s.schedules == live.scenario.schedules
        assert s.environment == live.scenario.environment

    def test_without_a_start_or_horizon_now_and_a_day(self) -> None:
        s = sim_live.overlay(None, _standalone(), now=NOW, tz=TZ).scenario
        assert (s.start, s.horizon, s.tz) == (
            NOW,
            sim_live.DEFAULT_HORIZON,
            TZ,
        )

    def test_the_scenarios_zone_wins_over_the_default(self) -> None:
        doc = _standalone()
        doc["scenario"]["tz"] = "UTC"
        assert sim_live.overlay(None, doc, now=NOW, tz=TZ).scenario.tz == "UTC"

    def test_no_zone_anywhere_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="no time zone"):
            sim_live.overlay(None, _standalone(), now=NOW)

    def test_an_unknown_zone_is_an_error(self) -> None:
        doc = _standalone()
        doc["scenario"]["tz"] = "Mars/Base"
        with pytest.raises(ValueError, match="unknown time zone"):
            sim_live.overlay(None, doc, now=NOW)

    def test_replace_then_over(self) -> None:
        """``replace``'s environment stands in whole for the live one;
        ``over`` is laid on it."""
        s = sim_live.overlay(
            _live(),
            now=NOW,
            replace={"environment": {"ambient_f": 40.0}},
            over={"environment": {"inlet_f": 55.0}},
        ).scenario
        assert s.environment == sim.Environment(ambient_f=40.0, inlet_f=55.0)

    def test_the_parameters_given_then_the_documents_then_the_heaters(
        self,
    ) -> None:
        p80, p50 = sim.default_params(3), sim.default_params(1)
        doc = _doc({}, params=params_to_document(p50))
        live = _live()
        assert sim_live.overlay(live, doc, now=NOW, params=p80).params == p80
        assert sim_live.overlay(live, doc, now=NOW).params == p50
        assert sim_live.overlay(live, now=NOW).params == live.params

    def test_without_parameters_the_defaults_with_a_note(self) -> None:
        built = sim_live.overlay(None, _standalone(), now=NOW, tz=TZ)
        assert built.params == sim.default_params()
        assert "65 gal defaults" in built.notes[0]

    @pytest.mark.parametrize(
        ("doc", "match"),
        [
            ([], "is an object"),
            ("{}", "is an object"),
            (1, "is an object"),
            ({"schema_version": 2, "scenario": {}}, "schema_version"),
            ({"schema_version": 1}, "scenario object"),
            (_doc({}, params={}), "scenario's params"),
            (_doc({}, params=[]), "scenario's params"),
            (_doc({}, params="65 gal"), "scenario's params"),
            (
                _doc({}, params={**params_to_document(P65), "unfitted": None}),
                "scenario's params.*unfitted",
            ),
            (
                _doc(
                    {},
                    params=merge(
                        params_to_document(P65),
                        {"compressor": {"heat_btu_h": None}},
                    ),
                ),
                "compressor.heat_btu_h is None, not a number",
            ),
            (_doc({"tz": TZ}), "do not make a scenario"),
        ],
    )
    def test_a_document_it_cannot_read(self, doc: Any, match: str) -> None:
        live = _live() if isinstance(doc, dict) and "params" in doc else None
        with pytest.raises(ValueError, match=match):
            sim_live.overlay(live, doc, now=NOW)


class TestTheCabinetFlag:
    def _cabinet_live(self) -> sim_live.Composed:
        live = _live()
        env = live.scenario.environment.model_copy(
            update={"ambient_cabinet": True}
        )
        return sim_live.Composed(
            live.scenario.model_copy(update={"environment": env}),
            live.params,
            live.heater,
        )

    def test_it_stands_while_the_air_does(self) -> None:
        live = self._cabinet_live()
        s = sim_live.overlay(live, now=NOW).scenario
        assert s.environment.ambient_cabinet

    def test_air_given_in_its_place_clears_it(self) -> None:
        live = self._cabinet_live()
        s = sim_live.overlay(
            live, now=NOW, over={"environment": {"ambient_f": 60.0}}
        ).scenario
        assert s.environment.ambient_f == 60.0
        assert not s.environment.ambient_cabinet

    def test_the_same_air_given_clears_it_too(self) -> None:
        """Given, the air is the caller's, whatever its value."""
        live = self._cabinet_live()
        same = live.scenario.environment.ambient_f
        by_option = sim_live.overlay(
            live, now=NOW, over={"environment": {"ambient_f": same}}
        ).scenario
        by_document = sim_live.overlay(
            live, _doc({"environment": {"ambient_f": same}}), now=NOW
        ).scenario
        for s in (by_option, by_document):
            assert s.environment.ambient_f == same
            assert not s.environment.ambient_cabinet

    def test_a_snapshot_keeps_its_own_flag(self) -> None:
        """A document that gives the air with its source keeps it: a
        snapshot of an idle heater replays as the cabinet's air."""
        live = self._cabinet_live()
        snapshot = scenario_to_document(live.scenario)
        assert snapshot["scenario"]["environment"]["ambient_cabinet"] is True
        replayed = sim_live.overlay(None, snapshot, now=NOW).scenario
        assert replayed.environment.ambient_cabinet
        over_live = sim_live.overlay(live, snapshot, now=NOW).scenario
        assert over_live.environment.ambient_cabinet
