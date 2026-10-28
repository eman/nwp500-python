"""``sim.codec.to_document``: the simulator's answers as documents."""

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nwp500 import sim
from nwp500.sim import codec
from nwp500.sim.profile import heater_profile

T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
STATE = sim.HeaterState(upper_f=128.0, lower_f=112.0)
SETTINGS = sim.Settings(setpoint_f=140.9, hp_lower_on_f=105.0)
AIR = sim.Environment(ambient_f=68.0, humidity=48.0)


@pytest.fixture(scope="module")
def params() -> sim.HeaterParams:
    return sim.site_example_params()


def _scenario() -> sim.Scenario:
    return sim.Scenario(
        start=T0,
        horizon=timedelta(hours=12),
        tz="UTC",
        state=STATE,
        settings=SETTINGS,
        history=sim.History(compressor_stopped_at=T0 - timedelta(hours=2)),
        environment=AIR,
    )


def _answers(params: sim.HeaterParams) -> dict[str, Any]:
    """One of each answer, by the kind its document names."""
    return {
        "readiness": sim.time_to_ready(_scenario(), params),
        "recovery": sim.next_recovery(_scenario(), params),
        "recovery_result": sim.recovery(STATE, SETTINGS, AIR, params, at=T0),
        "forecast": sim.forecast(
            STATE,
            SETTINGS,
            AIR,
            params,
            at=T0,
            target_time=T0 + timedelta(hours=3),
        ),
        "active_cycle": sim.active_cycle(STATE, SETTINGS, AIR, params, at=T0),
        "element_mode_result": sim.element_mode(
            STATE, SETTINGS, params, mode=4, at=T0
        ),
        "deliverable": sim.readiness(STATE, SETTINGS, params),
        "trace": sim.standby(
            STATE,
            AIR,
            sim.Loads(),
            params,
            start=T0,
            until=T0 + timedelta(hours=2),
        ),
        "heater_profile": heater_profile(),
    }


def _nested(doc: Any) -> list[Any]:
    """Every value in ``doc``, at any depth."""
    if isinstance(doc, dict):
        return [doc, *(v for x in doc.values() for v in _nested(x))]
    if isinstance(doc, list):
        return [doc, *(v for x in doc for v in _nested(x))]
    return [doc]


class TestToDocument:
    def test_each_answer_is_a_json_document_of_its_kind(
        self, params: sim.HeaterParams
    ) -> None:
        answers = _answers(params)
        assert set(answers) == set(codec.DOCUMENT_KINDS.values())
        for kind, answer in answers.items():
            doc = codec.to_document(answer)
            assert doc["schema_version"] == codec.SCHEMA_VERSION
            assert doc["kind"] == kind
            # Strict JSON: no NaN or infinity.
            assert json.loads(json.dumps(doc, allow_nan=False)) == doc

    def test_instants_are_iso_and_nested_answers_objects(
        self, params: sim.HeaterParams
    ) -> None:
        doc = codec.to_document(sim.time_to_ready(_scenario(), params))
        assert datetime.fromisoformat(doc["at"]) == T0
        assert isinstance(doc["bath"], dict)
        assert isinstance(doc["recovery"], dict)
        assert doc["recovery"]["outcome"] in {
            "ok",
            "not_scheduled",
            "unavailable",
            "idle",
        }

    def test_a_number_that_is_not_finite_is_null(self) -> None:
        deliverable = sim.Deliverable(gal=math.nan, basis="layers")
        assert codec.to_document(deliverable)["gal"] is None

    def test_no_value_is_left_unconverted(
        self, params: sim.HeaterParams
    ) -> None:
        for answer in _answers(params).values():
            for value in _nested(codec.to_document(answer)):
                assert isinstance(
                    value, dict | list | str | int | float | bool | None
                )

    def test_another_value_is_a_type_error(self) -> None:
        with pytest.raises(TypeError, match="no document kind"):
            codec.to_document(STATE)
