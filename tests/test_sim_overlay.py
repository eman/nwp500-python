"""``sim_live.overlay``: a scenario document laid over the heater's
live scenario, and ``sim.codec.merge``."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("pandas")

from nwp500 import sim, sim_live
from nwp500.sim.codec import merge, scenario_to_document
from nwp500.sim.params import params_to_document

NOW = datetime(2026, 10, 18, 14, tzinfo=UTC)
TZ = "America/Los_Angeles"


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
            ({"schema_version": 2, "scenario": {}}, "schema_version"),
            ({"schema_version": 1}, "scenario object"),
            (_doc({}, params={}), "scenario's params"),
            (_doc({"tz": TZ}), "do not make a scenario"),
        ],
    )
    def test_a_document_it_cannot_read(
        self, doc: dict[str, Any], match: str
    ) -> None:
        live = None if "params" not in doc else _live()
        with pytest.raises(ValueError, match=match):
            sim_live.overlay(live, doc, now=NOW)
