"""Typed event definitions for NavienMqttClient.

This module provides a centralized registry of all events emitted by the
NavienMqttClient, with full type information and documentation. This enables:

- IDE autocomplete for event names
- Type-safe event handlers
- Clear contracts for event data
- Programmatic event discovery

Example::

    from nwp500.mqtt_events import MqttClientEvents
    from nwp500.unit_system import get_unit_system

    # Type-safe event listening with autocomplete
    def on_temperature_changed(event):
        unit = "°C" if get_unit_system() == "metric" else "°F"
        print(
            f"Temp: {event.old_temperature}{unit} → "
            f"{event.new_temperature}{unit}"
        )

    mqtt_client.on(MqttClientEvents.TEMPERATURE_CHANGED, on_temperature_changed)

    # List all available events
    for event_name in MqttClientEvents.get_all_events():
        print(event_name)
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .enums import CurrentOperationMode, ErrorCode
    from .models import DeviceFeature, DeviceStatus


@dataclass(frozen=True, slots=True)
class ConnectionInterruptedEvent:
    """Emitted when MQTT connection is interrupted.

    Attributes:
        error: The error that caused the interruption
    """

    error: Exception


@dataclass(frozen=True, slots=True)
class ConnectionResumedEvent:
    """Emitted when MQTT connection is resumed after interruption.

    Attributes:
        return_code: MQTT return code (0 = success)
        session_present: Whether session state was preserved
    """

    return_code: int
    session_present: bool


@dataclass(frozen=True, slots=True)
class StatusReceivedEvent:
    """Emitted when a device status message is received.

    Attributes:
        device_mac: MAC address of the origin device
        status: The current device status snapshot
    """

    device_mac: str
    status: DeviceStatus


@dataclass(frozen=True, slots=True)
class TemperatureChangedEvent:
    """Emitted when the DHW temperature changes.

    Attributes:
        device_mac: MAC address of the origin device
        old_temperature: Previous DHW temperature in user's preferred unit
            (Celsius or Fahrenheit based on unit system context)
        new_temperature: New DHW temperature in user's preferred unit
            (Celsius or Fahrenheit based on unit system context)
    """

    device_mac: str
    old_temperature: float
    new_temperature: float


@dataclass(frozen=True, slots=True)
class ModeChangedEvent:
    """Emitted when the device operation mode changes.

    Attributes:
        device_mac: MAC address of the origin device
        old_mode: Previous operation mode
        new_mode: New operation mode
    """

    device_mac: str
    old_mode: CurrentOperationMode
    new_mode: CurrentOperationMode


@dataclass(frozen=True, slots=True)
class PowerChangedEvent:
    """Emitted when instantaneous power consumption changes.

    Attributes:
        device_mac: MAC address of the origin device
        old_power: Previous power consumption in watts
        new_power: New power consumption in watts
    """

    device_mac: str
    old_power: float
    new_power: float


@dataclass(frozen=True, slots=True)
class HeatingStartedEvent:
    """Emitted when device transitions from idle to heating.

    Attributes:
        device_mac: MAC address of the origin device
        status: Device status when heating started
    """

    device_mac: str
    status: DeviceStatus


@dataclass(frozen=True, slots=True)
class HeatingStoppedEvent:
    """Emitted when device transitions from heating to idle.

    Attributes:
        device_mac: MAC address of the origin device
        status: Device status when heating stopped
    """

    device_mac: str
    status: DeviceStatus


@dataclass(frozen=True, slots=True)
class ErrorDetectedEvent:
    """Emitted when a device error is first detected.

    Attributes:
        device_mac: MAC address of the origin device
        error_code: The error code that occurred
        status: Device status when error was detected
    """

    device_mac: str
    error_code: ErrorCode
    status: DeviceStatus


@dataclass(frozen=True, slots=True)
class ErrorClearedEvent:
    """Emitted when a device error is resolved.

    Attributes:
        device_mac: MAC address of the origin device
        error_code: The error code that was cleared
    """

    device_mac: str
    error_code: ErrorCode


@dataclass(frozen=True, slots=True)
class FeatureReceivedEvent:
    """Emitted when device feature information is received.

    Attributes:
        device_mac: MAC address of the origin device
        feature: The device feature information
    """

    device_mac: str
    feature: DeviceFeature


class MqttClientEvents:
    """Registry of all NavienMqttClient events.

    This class provides string constants for all events emitted by
    NavienMqttClient, with associated event data types documented in
    their dataclass definitions.

    Usage::

        mqtt_client.on(
            MqttClientEvents.TEMPERATURE_CHANGED,
            lambda event: update_display(event.new_temperature)
        )

        # Wait for a specific event
        args, _ = await mqtt_client.wait_for(
            MqttClientEvents.CONNECTION_RESUMED
        )
        connection_event = args[0]

        # List all available events
        events = ', '.join(MqttClientEvents.get_all_events())
        print(f"Available events: {events}")

    See Also:
        :doc:`../guides/event_system` - Comprehensive event handling guide
    """

    # Connection lifecycle events
    CONNECTION_INTERRUPTED = "connection_interrupted"
    """Emitted: MQTT connection interrupted with error.

    Args:
        event (ConnectionInterruptedEvent): Event object with the error field.

    See: :class:`ConnectionInterruptedEvent`
    """

    CONNECTION_RESUMED = "connection_resumed"
    """Emitted: MQTT connection resumed after interruption.

    Args:
        event (ConnectionResumedEvent): Event object with return_code and
            session_present fields.

    See: :class:`ConnectionResumedEvent`
    """

    # Device status events
    STATUS_RECEIVED = "status_received"
    """Emitted: Device status message received.

    Args:
        event (StatusReceivedEvent): Event object with the status field.

    See: :class:`StatusReceivedEvent`
    """

    TEMPERATURE_CHANGED = "temperature_changed"
    """Emitted: DHW temperature changed.

    Args:
        event (TemperatureChangedEvent): Event object with old_temperature
            and new_temperature fields.

    See: :class:`TemperatureChangedEvent`
    """

    MODE_CHANGED = "mode_changed"
    """Emitted: Device operation mode changed.

    Args:
        event (ModeChangedEvent): Event object with old_mode and new_mode
            fields.

    See: :class:`ModeChangedEvent`
    """

    POWER_CHANGED = "power_changed"
    """Emitted: Instantaneous power consumption changed.

    Args:
        event (PowerChangedEvent): Event object with old_power and new_power
            fields.

    See: :class:`PowerChangedEvent`
    """

    # Heating events
    HEATING_STARTED = "heating_started"
    """Emitted: Device started heating.

    Args:
        event (HeatingStartedEvent): Event object with the status field.

    See: :class:`HeatingStartedEvent`
    """

    HEATING_STOPPED = "heating_stopped"
    """Emitted: Device stopped heating.

    Args:
        event (HeatingStoppedEvent): Event object with the status field.

    See: :class:`HeatingStoppedEvent`
    """

    # Error events
    ERROR_DETECTED = "error_detected"
    """Emitted: Device error detected.

    Args:
        event (ErrorDetectedEvent): Event object with error_code and status
            fields.

    See: :class:`ErrorDetectedEvent`
    """

    ERROR_CLEARED = "error_cleared"
    """Emitted: Device error cleared.

    Args:
        event (ErrorClearedEvent): Event object with the error_code field.

    See: :class:`ErrorClearedEvent`
    """

    # Feature events
    FEATURE_RECEIVED = "feature_received"
    """Emitted: Device feature information received.

    Args:
        event (FeatureReceivedEvent): Event object with the feature field.

    See: :class:`FeatureReceivedEvent`
    """

    @classmethod
    def get_all_events(cls) -> list[str]:
        """Get list of all available event names.

        Returns:
            List of event constant names (not including metadata strings)

        Example::

            for event_name in MqttClientEvents.get_all_events():
                print(f"- {event_name}")

            # Output:
            # - CONNECTION_INTERRUPTED
            # - CONNECTION_RESUMED
            # - STATUS_RECEIVED
            # - TEMPERATURE_CHANGED
            # - ...
        """
        return [
            attr
            for attr in dir(cls)
            if not attr.startswith("_")
            and attr.isupper()
            and isinstance(getattr(cls, attr), str)
        ]

    @classmethod
    def get_event_value(cls, event_name: str) -> str:
        """Get the string value of an event constant.

        Args:
            event_name: Event constant name (e.g., "TEMPERATURE_CHANGED")

        Returns:
            Event string value (e.g., "temperature_changed")

        Raises:
            AttributeError: If event_name does not exist

        Example::

            value = MqttClientEvents.get_event_value("TEMPERATURE_CHANGED")
            print(value)  # Output: "temperature_changed"
        """
        return cast(str, getattr(cls, event_name))
