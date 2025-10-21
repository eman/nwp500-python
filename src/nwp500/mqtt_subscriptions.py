"""
MQTT Subscription Management for Navien devices.

This module handles all subscription-related operations including:
- Low-level subscribe/unsubscribe operations
- Topic pattern matching with MQTT wildcards
- Message routing and handler management
- Typed subscriptions (status, feature, energy)
- State change detection and event emission
"""

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from awscrt import mqtt

from .events import EventEmitter
from .models import Device, DeviceFeature, DeviceStatus, EnergyUsageResponse
from .mqtt_utils import redact_topic

__author__ = "Emmanuel Levijarvi"

_logger = logging.getLogger(__name__)


class MqttSubscriptionManager:
    """
    Manages MQTT subscriptions, topic matching, and message routing.

    Handles:
    - Subscribe/unsubscribe to MQTT topics
    - Topic pattern matching with wildcards (+ and #)
    - Message handler registration and invocation
    - Typed subscriptions with automatic parsing
    - State change detection and event emission
    """

    def __init__(
        self,
        connection: Any,  # awsiot.mqtt_connection.Connection
        client_id: str,
        event_emitter: EventEmitter,
        schedule_coroutine: Callable[[Any], None],
    ):
        """
        Initialize subscription manager.

        Args:
            connection: MQTT connection object
            client_id: Client ID for response topics
            event_emitter: Event emitter for state changes
            schedule_coroutine: Function to schedule async tasks
        """
        self._connection = connection
        self._client_id = client_id
        self._event_emitter = event_emitter
        self._schedule_coroutine = schedule_coroutine

        # Track subscriptions and handlers
        self._subscriptions: dict[str, mqtt.QoS] = {}
        self._message_handlers: dict[
            str, list[Callable[[str, dict[str, Any]], None]]
        ] = {}

        # Track previous state for change detection
        self._previous_status: Optional[DeviceStatus] = None

    @property
    def subscriptions(self) -> dict[str, mqtt.QoS]:
        """Get current subscriptions."""
        return self._subscriptions.copy()

    def _on_message_received(
        self, topic: str, payload: bytes, **kwargs: Any
    ) -> None:
        """Handle received MQTT messages.

        Parses JSON payload and routes to registered handlers.

        Args:
            topic: MQTT topic the message was received on
            payload: Raw message payload (JSON bytes)
            **kwargs: Additional MQTT metadata
        """
        try:
            # Parse JSON payload
            message = json.loads(payload.decode("utf-8"))
            _logger.debug("Received message on topic: %s", topic)

            # Call registered handlers that match this topic
            # Need to match against subscription patterns with wildcards
            for (
                subscription_pattern,
                handlers,
            ) in self._message_handlers.items():
                if self._topic_matches_pattern(topic, subscription_pattern):
                    for handler in handlers:
                        try:
                            handler(topic, message)
                        except Exception as e:
                            _logger.error(f"Error in message handler: {e}")

        except json.JSONDecodeError as e:
            _logger.error(f"Failed to parse message payload: {e}")
        except Exception as e:
            _logger.error(f"Error processing message: {e}")

    def _topic_matches_pattern(self, topic: str, pattern: str) -> bool:
        """
        Check if a topic matches a subscription pattern with wildcards.

        Supports MQTT wildcards:
        - '+' matches a single level
        - '#' matches multiple levels (must be at end)

        Args:
            topic: Actual topic (e.g., "cmd/52/navilink-ABC/status")
            pattern: Pattern with wildcards (e.g., "cmd/52/+/#")

        Returns:
            True if topic matches pattern

        Examples:
            >>> _topic_matches_pattern("cmd/52/device1/status",
            "cmd/52/+/status")
            True
            >>> _topic_matches_pattern("cmd/52/device1/status/extra",
            "cmd/52/device1/#")
            True
        """
        # Handle exact match
        if topic == pattern:
            return True

        # Handle wildcards
        topic_parts = topic.split("/")
        pattern_parts = pattern.split("/")

        # Multi-level wildcard # matches everything after
        if "#" in pattern_parts:
            hash_idx = pattern_parts.index("#")
            # Must be at the end
            if hash_idx != len(pattern_parts) - 1:
                return False
            # Topic must have at least as many parts as before the #
            if len(topic_parts) < hash_idx:
                return False
            # Check parts before # with + wildcard support
            for i in range(hash_idx):
                if (
                    pattern_parts[i] != "+"
                    and topic_parts[i] != pattern_parts[i]
                ):
                    return False
            return True

        # Single-level wildcard + matches one level
        if len(topic_parts) != len(pattern_parts):
            return False

        for topic_part, pattern_part in zip(topic_parts, pattern_parts):
            if pattern_part != "+" and topic_part != pattern_part:
                return False

        return True

    async def subscribe(
        self,
        topic: str,
        callback: Callable[[str, dict[str, Any]], None],
        qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE,
    ) -> int:
        """
        Subscribe to an MQTT topic.

        Args:
            topic: MQTT topic to subscribe to (can include wildcards)
            callback: Function to call when messages arrive (topic, message)
            qos: Quality of Service level

        Returns:
            Subscription packet ID

        Raises:
            RuntimeError: If not connected to MQTT broker
            Exception: If subscription fails
        """
        if not self._connection:
            raise RuntimeError("Not connected to MQTT broker")

        _logger.info(f"Subscribing to topic: {redact_topic(topic)}")

        try:
            # Convert concurrent.futures.Future to asyncio.Future and await
            subscribe_future, packet_id = self._connection.subscribe(
                topic=topic, qos=qos, callback=self._on_message_received
            )
            subscribe_result = await asyncio.wrap_future(subscribe_future)

            _logger.info(
                f"Subscription succeeded (topic redacted) with QoS "
                f"{subscribe_result['qos']}"
            )

            # Store subscription and handler
            self._subscriptions[topic] = qos
            if topic not in self._message_handlers:
                self._message_handlers[topic] = []
            self._message_handlers[topic].append(callback)

            return int(packet_id)

        except Exception as e:
            _logger.error(
                f"Failed to subscribe to '{redact_topic(topic)}': {e}"
            )
            raise

    async def unsubscribe(self, topic: str) -> int:
        """
        Unsubscribe from an MQTT topic.

        Args:
            topic: MQTT topic to unsubscribe from

        Returns:
            Unsubscribe packet ID

        Raises:
            RuntimeError: If not connected to MQTT broker
            Exception: If unsubscribe fails
        """
        if not self._connection:
            raise RuntimeError("Not connected to MQTT broker")

        _logger.info(f"Unsubscribing from topic: {redact_topic(topic)}")

        try:
            # Convert concurrent.futures.Future to asyncio.Future and await
            unsubscribe_future, packet_id = self._connection.unsubscribe(topic)
            await asyncio.wrap_future(unsubscribe_future)

            # Remove from tracking
            self._subscriptions.pop(topic, None)
            self._message_handlers.pop(topic, None)

            _logger.info(f"Unsubscribed from '{topic}'")

            return int(packet_id)

        except Exception as e:
            _logger.error(
                f"Failed to unsubscribe from '{redact_topic(topic)}': {e}"
            )
            raise

    async def subscribe_device(
        self, device: Device, callback: Callable[[str, dict[str, Any]], None]
    ) -> int:
        """
        Subscribe to all messages from a specific device.

        Args:
            device: Device object
            callback: Message handler

        Returns:
            Subscription packet ID
        """
        # Subscribe to all command responses from device (broader pattern)
        # Device responses come on cmd/{device_type}/navilink-{device_id}/#
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        device_topic = f"navilink-{device_id}"
        response_topic = f"cmd/{device_type}/{device_topic}/#"
        return await self.subscribe(response_topic, callback)

    async def subscribe_device_status(
        self, device: Device, callback: Callable[[DeviceStatus], None]
    ) -> int:
        """
        Subscribe to device status messages with automatic parsing.

        This method wraps the standard subscription with automatic parsing
        of status messages into DeviceStatus objects. The callback will only
        be invoked when a status message is received and successfully parsed.

        Additionally, the client emits granular events for state changes:
        - 'status_received': Every status update (DeviceStatus)
        - 'temperature_changed': Temperature changed (old_temp, new_temp)
        - 'mode_changed': Operation mode changed (old_mode, new_mode)
        - 'power_changed': Power consumption changed (old_power, new_power)
        - 'heating_started': Device started heating (status)
        - 'heating_stopped': Device stopped heating (status)
        - 'error_detected': Error code detected (error_code, status)
        - 'error_cleared': Error code cleared (error_code)

        Args:
            device: Device object
            callback: Callback function that receives DeviceStatus objects

        Returns:
            Subscription packet ID

        Example (Traditional Callback)::

            >>> def on_status(status: DeviceStatus):
            ...     print(f"Temperature: {status.dhwTemperature}°F")
            ...     print(f"Mode: {status.operationMode}")
            >>>
            >>> await mqtt_client.subscribe_device_status(device, on_status)

        Example (Event Emitter)::

            >>> # Multiple handlers for same event
            >>> mqtt_client.on('temperature_changed', log_temperature)
            >>> mqtt_client.on('temperature_changed', update_ui)
            >>>
            >>> # State change events
            >>> mqtt_client.on('heating_started', lambda s: print("Heating ON"))
            >>> mqtt_client.on('heating_stopped', lambda s: print("Heating
            OFF"))
            >>>
            >>> # Subscribe to start receiving events
            >>> await mqtt_client.subscribe_device_status(device, lambda s:
            None)
        """

        def status_message_handler(topic: str, message: dict[str, Any]) -> None:
            """Parse status messages and invoke user callback."""
            try:
                # Log all messages received for debugging
                _logger.debug(
                    f"Status handler received message on topic: {topic}"
                )
                _logger.debug(f"Message keys: {list(message.keys())}")

                if "response" not in message:
                    _logger.debug(
                        "Message does not contain 'response' key, skipping. "
                        "Keys: %s",
                        list(message.keys()),
                    )
                    return

                response = message["response"]
                _logger.debug(f"Response keys: {list(response.keys())}")

                if "status" not in response:
                    _logger.debug(
                        "Response does not contain 'status' key, skipping. "
                        "Keys: %s",
                        list(response.keys()),
                    )
                    return

                # Parse status into DeviceStatus object
                _logger.info(
                    f"Parsing device status message from topic: {topic}"
                )
                status_data = response["status"]
                device_status = DeviceStatus.from_dict(status_data)

                # Emit raw status event
                self._schedule_coroutine(
                    self._event_emitter.emit("status_received", device_status)
                )

                # Detect and emit state changes
                self._schedule_coroutine(
                    self._detect_state_changes(device_status)
                )

                # Invoke user callback with parsed status
                _logger.info("Invoking user callback with parsed DeviceStatus")
                callback(device_status)
                _logger.debug("User callback completed successfully")

            except KeyError as e:
                _logger.warning(
                    f"Missing required field in status message: {e}",
                    exc_info=True,
                )
            except ValueError as e:
                _logger.warning(
                    f"Invalid value in status message: {e}", exc_info=True
                )
            except Exception as e:
                _logger.error(
                    f"Error parsing device status: {e}", exc_info=True
                )

        # Subscribe using the internal handler
        return await self.subscribe_device(
            device=device, callback=status_message_handler
        )

    async def _detect_state_changes(self, status: DeviceStatus) -> None:
        """
        Detect state changes and emit granular events.

        This method compares the current status with the previous status
        and emits events for any detected changes.

        Args:
            status: Current device status
        """
        if self._previous_status is None:
            # First status received, just store it
            self._previous_status = status
            return

        prev = self._previous_status

        try:
            # Temperature change
            if status.dhwTemperature != prev.dhwTemperature:
                await self._event_emitter.emit(
                    "temperature_changed",
                    prev.dhwTemperature,
                    status.dhwTemperature,
                )
                _logger.debug(
                    f"Temperature changed: {prev.dhwTemperature}°F → "
                    f"{status.dhwTemperature}°F"
                )

            # Operation mode change
            if status.operationMode != prev.operationMode:
                await self._event_emitter.emit(
                    "mode_changed",
                    prev.operationMode,
                    status.operationMode,
                )
                _logger.debug(
                    f"Mode changed: {prev.operationMode} → "
                    f"{status.operationMode}"
                )

            # Power consumption change
            if status.currentInstPower != prev.currentInstPower:
                await self._event_emitter.emit(
                    "power_changed",
                    prev.currentInstPower,
                    status.currentInstPower,
                )
                _logger.debug(
                    f"Power changed: {prev.currentInstPower}W → "
                    f"{status.currentInstPower}W"
                )

            # Heating started/stopped
            prev_heating = prev.currentInstPower > 0
            curr_heating = status.currentInstPower > 0

            if curr_heating and not prev_heating:
                await self._event_emitter.emit("heating_started", status)
                _logger.debug("Heating started")

            if not curr_heating and prev_heating:
                await self._event_emitter.emit("heating_stopped", status)
                _logger.debug("Heating stopped")

            # Error detection
            if status.errorCode and not prev.errorCode:
                await self._event_emitter.emit(
                    "error_detected", status.errorCode, status
                )
                _logger.info(f"Error detected: {status.errorCode}")

            if not status.errorCode and prev.errorCode:
                await self._event_emitter.emit("error_cleared", prev.errorCode)
                _logger.info(f"Error cleared: {prev.errorCode}")

        except Exception as e:
            _logger.error(f"Error detecting state changes: {e}", exc_info=True)
        finally:
            # Always update previous status
            self._previous_status = status

    async def subscribe_device_feature(
        self, device: Device, callback: Callable[[DeviceFeature], None]
    ) -> int:
        """
        Subscribe to device feature/info messages with automatic parsing.

        This method wraps the standard subscription with automatic parsing
        of feature messages into DeviceFeature objects. The callback will only
        be invoked when a feature message is received and successfully parsed.

        Feature messages contain device capabilities, firmware versions,
        serial numbers, and configuration limits.

        Additionally emits: 'feature_received' event with DeviceFeature object.

        Args:
            device: Device object
            callback: Callback function that receives DeviceFeature objects

        Returns:
            Subscription packet ID

        Example::

            >>> def on_feature(feature: DeviceFeature):
            ...     print(f"Serial: {feature.controllerSerialNumber}")
            ...     print(f"FW Version: {feature.controllerSwVersion}")
            ...     print(f"Temp Range:
            {feature.dhwTemperatureMin}-{feature.dhwTemperatureMax}°F")
            >>>
            >>> await mqtt_client.subscribe_device_feature(device, on_feature)

            >>> # Or use event emitter
            >>> mqtt_client.on('feature_received', lambda f: print(f"FW:
            {f.controllerSwVersion}"))
            >>> await mqtt_client.subscribe_device_feature(device, lambda f:
            None)
        """

        def feature_message_handler(
            topic: str, message: dict[str, Any]
        ) -> None:
            """Parse feature messages and invoke user callback."""
            try:
                # Log all messages received for debugging
                _logger.debug(
                    f"Feature handler received message on topic: {topic}"
                )
                _logger.debug(f"Message keys: {list(message.keys())}")

                # Check if message contains feature data
                if "response" not in message:
                    _logger.debug(
                        "Message does not contain 'response' key, "
                        "skipping. Keys: %s",
                        list(message.keys()),
                    )
                    return

                response = message["response"]
                _logger.debug(f"Response keys: {list(response.keys())}")

                if "feature" not in response:
                    _logger.debug(
                        "Response does not contain 'feature' key, "
                        "skipping. Keys: %s",
                        list(response.keys()),
                    )
                    return

                # Parse feature into DeviceFeature object
                _logger.info(
                    f"Parsing device feature message from topic: {topic}"
                )
                feature_data = response["feature"]
                device_feature = DeviceFeature.from_dict(feature_data)

                # Emit feature received event
                self._schedule_coroutine(
                    self._event_emitter.emit("feature_received", device_feature)
                )

                # Invoke user callback with parsed feature
                _logger.info("Invoking user callback with parsed DeviceFeature")
                callback(device_feature)
                _logger.debug("User callback completed successfully")

            except KeyError as e:
                _logger.warning(
                    f"Missing required field in feature message: {e}",
                    exc_info=True,
                )
            except ValueError as e:
                _logger.warning(
                    f"Invalid value in feature message: {e}", exc_info=True
                )
            except Exception as e:
                _logger.error(
                    f"Error parsing device feature: {e}", exc_info=True
                )

        # Subscribe using the internal handler
        return await self.subscribe_device(
            device=device, callback=feature_message_handler
        )

    async def subscribe_energy_usage(
        self,
        device: Device,
        callback: Callable[[EnergyUsageResponse], None],
    ) -> int:
        """
        Subscribe to energy usage query responses with automatic parsing.

        This method wraps the standard subscription with automatic parsing
        of energy usage responses into EnergyUsageResponse objects.

        Args:
            device: Device object
            callback: Callback function that receives EnergyUsageResponse
            objects

        Returns:
            Subscription packet ID

        Example:
            >>> def on_energy_usage(energy: EnergyUsageResponse):
            ...     print(f"Total Usage: {energy.total.total_usage} Wh")
            ...     print(f"Heat Pump:
            {energy.total.heat_pump_percentage:.1f}%")
            ...     print(f"Electric:
            {energy.total.heat_element_percentage:.1f}%")
            >>>
            >>> await mqtt_client.subscribe_energy_usage(device,
            on_energy_usage)
            >>> await mqtt_client.request_energy_usage(device, 2025, [9])
        """
        device_type = device.device_info.device_type

        def energy_message_handler(topic: str, message: dict[str, Any]) -> None:
            """Parse and route energy usage responses to user callback.

            Args:
                topic: MQTT topic the message was received on
                message: Parsed message dictionary
            """
            try:
                _logger.debug(
                    "Energy handler received message on topic: %s", topic
                )
                _logger.debug("Message keys: %s", list(message.keys()))

                if "response" not in message:
                    _logger.debug(
                        "Message does not contain 'response' key, "
                        "skipping. Keys: %s",
                        list(message.keys()),
                    )
                    return

                response_data = message["response"]
                _logger.debug("Response keys: %s", list(response_data.keys()))

                if "typeOfUsage" not in response_data:
                    _logger.debug(
                        "Response does not contain 'typeOfUsage' key, "
                        "skipping. Keys: %s",
                        list(response_data.keys()),
                    )
                    return

                _logger.info(
                    "Parsing energy usage response from topic: %s", topic
                )
                energy_response = EnergyUsageResponse.from_dict(response_data)

                _logger.info(
                    "Invoking user callback with parsed EnergyUsageResponse"
                )
                callback(energy_response)
                _logger.debug("User callback completed successfully")

            except KeyError as e:
                _logger.warning(
                    "Failed to parse energy usage message - missing key: %s", e
                )
            except Exception as e:
                _logger.error(
                    "Error in energy usage message handler: %s",
                    e,
                    exc_info=True,
                )

        response_topic = (
            f"cmd/{device_type}/{self._client_id}/res/"
            f"energy-usage-daily-query/rd"
        )

        return await self.subscribe(response_topic, energy_message_handler)

    def clear_subscriptions(self) -> None:
        """Clear all subscription tracking (called on disconnect)."""
        self._subscriptions.clear()
        self._message_handlers.clear()
        self._previous_status = None
