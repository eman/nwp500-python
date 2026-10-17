"""Scenarios and results as JSON documents (``nwp500.sim.codec``)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("pandas")

from nwp500.sim import (
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
    simulate,
)
from nwp500.sim.codec import (
    SCHEMA_VERSION,
    result_to_document,
    scenario_from_document,
    scenario_to_document,
)

T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)


def _scenario() -> Scenario:
    return Scenario(
        start=T0,
        horizon=timedelta(hours=10),
        tz="America/Los_Angeles",
        state=HeaterState(
            upper_f=126.8, lower_f=101.3, compressor_running=True
        ),
        settings=Settings(setpoint_f=140.9, mode=3, hp_lower_on_f=105.0),
        history=History(compressor_stopped_at=T0 - timedelta(hours=5)),
        schedules=Schedules(
            reservations=(
                ReservationEntry(
                    week=124, hour=6, minute=30, mode=4, setpoint_half_c=124
                ),
            ),
            tou_periods=(
                TouPeriod(
                    season=4095,
                    week=254,
                    start_hour=16,
                    start_minute=0,
                    end_hour=20,
                    end_minute=59,
                    price_max=5,
                ),
            ),
            tou_enabled=True,
        ),
        environment=Environment(
            ambient_f=((T0, 66.0), (T0 + timedelta(hours=10), 71.5)),
            humidity=48.0,
        ),
        loads=Loads(draws=(Draw(at=T0 + timedelta(hours=1), gallons=12.0),)),
        commands=Commands(
            writes=(Write(at=T0 + timedelta(hours=2), mode=1, id="hp"),),
            tou_enabled=False,
        ),
    )


def test_a_scenario_round_trips():
    s = _scenario()
    doc = scenario_to_document(s)
    assert doc["schema_version"] == SCHEMA_VERSION
    back, params = scenario_from_document(json.dumps(doc))
    assert back == s
    assert params is None


def test_a_scenario_with_its_parameters_round_trips():
    s, p = _scenario(), default_params(3)
    back, params = scenario_from_document(scenario_to_document(s, p))
    assert back == s
    assert params == p


def test_the_document_is_plain_json():
    doc = scenario_to_document(_scenario(), default_params())
    text = json.dumps(doc)
    assert json.loads(text) == doc
    assert doc["scenario"]["start"] == "2026-10-04T19:00:00Z"


def test_another_schema_version_is_refused():
    doc = scenario_to_document(_scenario()) | {"schema_version": 2}
    with pytest.raises(ValueError, match="schema_version"):
        scenario_from_document(doc)


def test_an_unknown_field_is_refused():
    doc = scenario_to_document(_scenario())
    doc["scenario"]["state"]["middle_f"] = 120.0
    with pytest.raises(ValueError, match="middle_f"):
        scenario_from_document(doc)


def test_a_result_is_plain_json():
    result = simulate(_scenario(), default_params())
    doc = result_to_document(result)
    assert json.loads(json.dumps(doc)) == doc
    assert len(doc["points"]) == len(result.points)
    assert doc["points"][0]["at"] == result.points[0].at.isoformat()
    assert doc["points"][-1]["upper_f"] == result.points[-1].upper_f
    assert [h["stop"] for h in doc["heating"]] == [
        h.stop for h in result.heating
    ]
    assert doc["defaults_used"] == list(result.defaults_used)
