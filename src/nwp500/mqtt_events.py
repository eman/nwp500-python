"""Typed event definitions for NavienMqttClient.

This module provides a centralized registry of all events emitted by the
NavienMqttClient, with full type information and documentation. This enables:

- IDE autocomplete for event names
- Type-safe event handlers
- Clear contracts for event data
- Programmatic event discovery

Example::

    from nwp500.mqtt_events import MqttClientEvents

    # Type-safe event listening with autocomplete
    mqtt_client.on(
        MqttClientEvents.TEMPERATURE_CHANGED,
        lambda old_temp, new_temp: print(f"Temp: {old_temp}°F → {new_temp}°F")
    )

    # List all available events
    for event_name in MqttClientEvents.get_all_events():
        print(event_name)
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .enums import CurrentOperationMode, ErrorCode
    from .models import DeviceFeature, DeviceStatus


@dataclass(frozen=True)
class ConnectionInterruptedEvent:
    """Emitted when MQTT connection is interrupted.

    Attributes:
        error: The error that caused the interruption
    """

    error: Exception


@dataclass(frozen=True)
class ConnectionResumedEvent:
    """Emitted when MQTT connection is resumed after interruption.

    Attributes:
        return_code: MQTT return code (0 = success)
        session_present: Whether session state was preserved
    """

    return_code: int
    session_present: bool


@dataclass(frozen=True)
class StatusReceivedEvent:
    """Emitted when a device status message is received.

    Attributes:
        status: The current device status snapshot
    """

    status: "DeviceStatus"


@dataclass(frozen=True)
class TemperatureChangedEvent:
    """Emitted when the DHW temperature changes.

    Attributes:
        old_temperature: Previous DHW temperature in °F
        new_temperature: New DHW temperature in °F
    """

    old_temperature: float
    new_temperature: float


@dataclass(frozen=True)
class ModeChangedEvent:
    """Emitted when the device operation mode changes.

    Attributes:
        old_mode: Previous operation mode
        new_mode: New operation mode
    """

    old_mode: "CurrentOperationMode"
    new_mode: "CurrentOperationMode"


@dataclass(frozen=True)
class PowerChangedEvent:
    """Emitted when instantaneous power consumption changes.

    Attributes:
        old_power: Previous power consumption in watts
        new_power: New power consumption in watts
    """

    old_power: float
    new_power: float


@dataclass(frozen=True)
class HeatingStartedEvent:
    """Emitted when device transitions from idle to heating.

    Attributes:
        status: Device status when heating started
    """

    status: "DeviceStatus"


@dataclass(frozen=True)
class HeatingStoppedEvent:
    """Emitted when device transitions from heating to idle.

    Attributes:
        status: Device status when heating stopped
    """

    status: "DeviceStatus"


@dataclass(frozen=True)
class ErrorDetectedEvent:
    """Emitted when a device error is first detected.

    Attributes:
        error_code: The error code that occurred
        status: Device status when error was detected
    """

    error_code: "ErrorCode"
    status: "DeviceStatus"


@dataclass(frozen=True)
class ErrorClearedEvent:
    """Emitted when a device error is resolved.

    Attributes:
        error_code: The error code that was cleared
    """

    error_code: "ErrorCode"


@dataclass(frozen=True)
class FeatureReceivedEvent:
    """Emitted when device feature information is received.

    Attributes:
        feature: The device feature information
    """

    feature: "DeviceFeature"


class MqttClientEvents:
    """Registry of all NavienMqttClient events.

    This class provides string constants for all events emitted by
    NavienMqttClient, with associated event data types documented in
    their dataclass definitions.

    Usage::

        mqtt_client.on(
            MqttClientEvents.TEMPERATURE_CHANGED,
            lambda old_temp, new_temp: update_display(new_temp)
        )

        # Wait for a specific event
        await mqtt_client.wait_for(MqttClientEvents.CONNECTION_RESUMED)

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
        error (Exception): The error that caused the interruption

    See: :class:`ConnectionInterruptedEvent`
    """

    CONNECTION_RESUMED = "connection_resumed"
    """Emitted: MQTT connection resumed after interruption.

    Args:
        return_code (int): MQTT return code (0 = success)
        session_present (bool): Whether session state was preserved

    See: :class:`ConnectionResumedEvent`
    """

    # Device status events
    STATUS_RECEIVED = "status_received"
    """Emitted: Device status message received.

    Args:
        status (DeviceStatus): Current device status snapshot

    See: :class:`StatusReceivedEvent`
    """

    TEMPERATURE_CHANGED = "temperature_changed"
    """Emitted: DHW temperature changed.

    Args:
        old_temperature (float): Previous DHW temperature (°F)
        new_temperature (float): New DHW temperature (°F)

    See: :class:`TemperatureChangedEvent`
    """

    MODE_CHANGED = "mode_changed"
    """Emitted: Device operation mode changed.

    Args:
        old_mode (CurrentOperationMode): Previous mode
        new_mode (CurrentOperationMode): New mode

    See: :class:`ModeChangedEvent`
    """

    POWER_CHANGED = "power_changed"
    """Emitted: Instantaneous power consumption changed.

    Args:
        old_power (float): Previous power consumption (W)
        new_power (float): New power consumption (W)

    See: :class:`PowerChangedEvent`
    """

    # Heating events
    HEATING_STARTED = "heating_started"
    """Emitted: Device started heating.

    Args:
        status (DeviceStatus): Device status when heating started

    See: :class:`HeatingStartedEvent`
    """

    HEATING_STOPPED = "heating_stopped"
    """Emitted: Device stopped heating.

    Args:
        status (DeviceStatus): Device status when heating stopped

    See: :class:`HeatingStoppedEvent`
    """

    # Error events
    ERROR_DETECTED = "error_detected"
    """Emitted: Device error detected.

    Args:
        error_code (ErrorCode): The error code
        status (DeviceStatus): Status when error was detected

    See: :class:`ErrorDetectedEvent`
    """

    ERROR_CLEARED = "error_cleared"
    """Emitted: Device error cleared.

    Args:
        error_code (ErrorCode): The error code that was cleared

    See: :class:`ErrorClearedEvent`
    """

    # Feature events
    FEATURE_RECEIVED = "feature_received"
    """Emitted: Device feature information received.

    Args:
        feature (DeviceFeature): Device feature information

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
