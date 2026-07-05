"""Tests for previously untested utility modules.

Covers topic_builder, field_factory, and models/_converters.
"""

import pytest
from pydantic import BaseModel

from nwp500.field_factory import (
    energy_field,
    power_field,
    signal_strength_field,
    temperature_field,
)
from nwp500.models._converters import (
    fahrenheit_to_half_celsius,
    preferred_to_half_celsius,
    reservation_param_to_preferred,
)
from nwp500.topic_builder import MqttTopicBuilder
from nwp500.unit_system import reset_unit_system, set_unit_system

MAC = "aa:bb:cc:dd:ee:ff"


@pytest.fixture(autouse=True)
def _reset_units():
    yield
    reset_unit_system()


class TestMqttTopicBuilder:
    def test_device_topic(self):
        assert MqttTopicBuilder.device_topic(MAC) == f"navilink-{MAC}"

    def test_command_topic_default_suffix(self):
        assert (
            MqttTopicBuilder.command_topic("52", MAC)
            == f"cmd/52/navilink-{MAC}/ctrl"
        )

    def test_command_topic_custom_suffix(self):
        assert (
            MqttTopicBuilder.command_topic("52", MAC, "ctrl/rsv/rd")
            == f"cmd/52/navilink-{MAC}/ctrl/rsv/rd"
        )

    def test_command_topic_wildcard(self):
        assert (
            MqttTopicBuilder.command_topic("52", MAC, "#")
            == f"cmd/52/navilink-{MAC}/#"
        )

    def test_response_ack_topic(self):
        assert (
            MqttTopicBuilder.response_ack_topic("52", MAC, "client-1")
            == f"cmd/52/navilink-{MAC}/client-1/res"
        )

    def test_response_topic(self):
        assert (
            MqttTopicBuilder.response_topic("52", "client-1", "rsv/rd")
            == "cmd/52/client-1/res/rsv/rd"
        )

    def test_event_topic(self):
        assert (
            MqttTopicBuilder.event_topic("52", MAC, "st")
            == f"evt/52/navilink-{MAC}/st"
        )


class TestFieldFactory:
    def test_temperature_field_metadata(self):
        class Model(BaseModel):
            temp: float = temperature_field("DHW temperature", default=0.0)

        extra = Model.model_fields["temp"].json_schema_extra
        assert extra == {
            "unit_of_measurement": "°F",
            "device_class": "temperature",
            "suggested_display_precision": 1,
        }
        assert Model.model_fields["temp"].description == "DHW temperature"

    def test_temperature_field_custom_unit(self):
        class Model(BaseModel):
            temp: float = temperature_field("t", unit="°C", default=0.0)

        extra = Model.model_fields["temp"].json_schema_extra
        assert extra["unit_of_measurement"] == "°C"

    def test_caller_json_schema_extra_merged(self):
        class Model(BaseModel):
            temp: float = temperature_field(
                "t",
                default=0.0,
                json_schema_extra={"custom": True, "device_class": "override"},
            )

        extra = Model.model_fields["temp"].json_schema_extra
        assert extra["custom"] is True
        assert extra["device_class"] == "override"  # caller wins
        assert extra["unit_of_measurement"] == "°F"  # base preserved

    @pytest.mark.parametrize(
        ("factory", "device_class", "unit"),
        [
            (signal_strength_field, "signal_strength", "dBm"),
            (energy_field, "energy", "kWh"),
            (power_field, "power", "W"),
        ],
    )
    def test_other_factories_metadata(self, factory, device_class, unit):
        class Model(BaseModel):
            value: float = factory("desc", default=0.0)

        extra = Model.model_fields["value"].json_schema_extra
        assert extra["device_class"] == device_class
        assert extra["unit_of_measurement"] == unit


class TestModelConverters:
    def test_fahrenheit_to_half_celsius(self):
        assert fahrenheit_to_half_celsius(140.0) == 120

    def test_preferred_to_half_celsius_us_customary(self):
        set_unit_system("us_customary")
        assert preferred_to_half_celsius(140.0) == 120

    def test_preferred_to_half_celsius_metric(self):
        set_unit_system("metric")
        assert preferred_to_half_celsius(60.0) == 120

    def test_reservation_param_to_preferred_metric(self):
        set_unit_system("metric")
        assert reservation_param_to_preferred(120) == 60.0

    def test_reservation_param_to_preferred_us_customary(self):
        set_unit_system("us_customary")
        assert reservation_param_to_preferred(120) == 140.0

    def test_roundtrip_us_customary(self):
        set_unit_system("us_customary")
        for temp in (100.0, 120.0, 130.0, 140.0, 150.0):
            param = preferred_to_half_celsius(temp)
            assert reservation_param_to_preferred(param) == pytest.approx(
                temp, abs=1.0
            )
