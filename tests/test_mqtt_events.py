"""Tests for typed MQTT event payloads and the event-name registry.

These tests lock in the contract between :mod:`nwp500.events` (the
:class:`EventEmitter` delivery mechanism) and :mod:`nwp500.mqtt_events` (the
event-name registry and typed dataclass payloads): subscribing with a
``MqttClientEvents`` constant delivers the matching typed payload.
"""

import dataclasses

import pytest

from nwp500.events import EventEmitter
from nwp500.mqtt_events import (
    ConnectionInterruptedEvent,
    ConnectionResumedEvent,
    ErrorClearedEvent,
    ModeChangedEvent,
    MqttClientEvents,
    PowerChangedEvent,
    TemperatureChangedEvent,
)


def test_registry_lists_all_event_names():
    """get_all_events returns every declared event constant name."""
    events = MqttClientEvents.get_all_events()

    expected = {
        "CONNECTION_INTERRUPTED",
        "CONNECTION_RESUMED",
        "STATUS_RECEIVED",
        "TEMPERATURE_CHANGED",
        "MODE_CHANGED",
        "POWER_CHANGED",
        "HEATING_STARTED",
        "HEATING_STOPPED",
        "ERROR_DETECTED",
        "ERROR_CLEARED",
        "FEATURE_RECEIVED",
    }
    assert set(events) == expected


def test_get_event_value_returns_string_constant():
    """get_event_value resolves a constant name to its wire string."""
    assert (
        MqttClientEvents.get_event_value("TEMPERATURE_CHANGED")
        == "temperature_changed"
    )
    assert MqttClientEvents.TEMPERATURE_CHANGED == "temperature_changed"


def test_get_event_value_unknown_raises():
    """Unknown event names raise AttributeError."""
    with pytest.raises(AttributeError):
        MqttClientEvents.get_event_value("DOES_NOT_EXIST")


@pytest.mark.parametrize(
    "event_name, payload",
    [
        (
            MqttClientEvents.CONNECTION_INTERRUPTED,
            ConnectionInterruptedEvent(error=RuntimeError("boom")),
        ),
        (
            MqttClientEvents.CONNECTION_RESUMED,
            ConnectionResumedEvent(return_code=0, session_present=True),
        ),
        (
            MqttClientEvents.TEMPERATURE_CHANGED,
            TemperatureChangedEvent(
                device_mac="aabbccddeeff",
                old_temperature=48.0,
                new_temperature=50.0,
            ),
        ),
        (
            MqttClientEvents.MODE_CHANGED,
            ModeChangedEvent(device_mac="aabbccddeeff", old_mode=1, new_mode=2),
        ),
        (
            MqttClientEvents.POWER_CHANGED,
            PowerChangedEvent(
                device_mac="aabbccddeeff", old_power=0, new_power=1200
            ),
        ),
        (
            MqttClientEvents.ERROR_CLEARED,
            ErrorClearedEvent(device_mac="aabbccddeeff", error_code=799),
        ),
    ],
)
@pytest.mark.asyncio
async def test_typed_payload_delivered_via_registry_constant(
    event_name, payload
):
    """Subscribing with a registry constant delivers the typed payload."""
    emitter = EventEmitter()
    received: list[object] = []

    emitter.on(event_name, received.append)

    delivered = await emitter.emit(event_name, payload)

    assert delivered == 1
    assert received == [payload]
    assert received[0] is payload


def test_event_payloads_are_frozen():
    """Typed event payloads are immutable (frozen dataclasses)."""
    event = TemperatureChangedEvent(
        device_mac="aabbccddeeff",
        old_temperature=48.0,
        new_temperature=50.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.new_temperature = 60.0  # type: ignore[misc]
