"""
MQTT Subscription Management for Navien devices.

This module handles all subscription-related operations including:
- Low-level subscribe/unsubscribe operations
- Topic pattern matching with MQTT wildcards
- Message routing and handler management
- Typed subscriptions (status, feature, energy)
- State change detection and event emission
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from awscrt import mqtt
from awscrt.exceptions import AwsCrtError
from pydantic import ValidationError

from ..events import EventEmitter
from ..exceptions import MqttNotConnectedError
from ..models import Device, DeviceFeature, DeviceStatus, EnergyUsageResponse
from ..topic_builder import MqttTopicBuilder
from .utils import redact_topic, topic_matches_pattern

if TYPE_CHECKING:
    from ..device_info_cache import MqttDeviceInfoCache

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
        device_info_cache: MqttDeviceInfoCache | None = None,
    ):
        """
        Initialize subscription manager.

        Args:
            connection: MQTT connection object
            client_id: Client ID for response topics
            event_emitter: Event emitter for state changes
            schedule_coroutine: Function to schedule async tasks
            device_info_cache: Optional MqttDeviceInfoCache for caching device
                features
        """
        self._connection = connection
        self._client_id = client_id
        self._event_emitter = event_emitter
        self._schedule_coroutine = schedule_coroutine
        self._device_info_cache = device_info_cache

        # Track subscriptions and handlers
        self._subscriptions: dict[str, mqtt.QoS] = {}
        self._message_handlers: dict[
            str, list[Callable[[str, dict[str, Any]], None]]
        ] = {}

        # Track previous state for change detection
        self._previous_status: DeviceStatus | None = None

    @property
    def subscriptions(self) -> dict[str, mqtt.QoS]:
        """Get current subscriptions."""
        return self._subscriptions.copy()

    def update_connection(self, connection: Any) -> None:
        """
        Update the MQTT connection reference.

        This is used when the connection is recreated (e.g., after reconnection)
        to update the internal reference while preserving subscriptions.

        Args:
            connection: New MQTT connection object

        Note:
            This does not re-establish subscriptions. Call the appropriate
            subscribe methods to re-register subscriptions with the new
            connection if needed.
        """
        self._connection = connection
        _logger.debug("Updated subscription manager connection reference")

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
                if topic_matches_pattern(topic, subscription_pattern):
                    for handler in handlers:
                        try:
                            handler(topic, message)
                        except (TypeError, AttributeError, KeyError) as e:
                            _logger.error(f"Error in message handler: {e}")

        except json.JSONDecodeError as e:
            _logger.error(f"Failed to parse message payload: {e}")
        except (AttributeError, KeyError, TypeError) as e:
            _logger.error(f"Error processing message: {e}")

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
            raise MqttNotConnectedError("Not connected to MQTT broker")

        _logger.info(f"Subscribing to topic: {redact_topic(topic)}")

        try:
            # Convert concurrent.futures.Future to asyncio.Future and await
            # Use shield to prevent cancellation from propagating to
            # underlying future
            subscribe_future, packet_id = self._connection.subscribe(
                topic=topic, qos=qos, callback=self._on_message_received
            )
            try:
                subscribe_result = await asyncio.shield(
                    asyncio.wrap_future(subscribe_future)
                )
            except asyncio.CancelledError:
                # Shield was cancelled - the underlying subscribe will
                # complete independently, preventing InvalidStateError
                # in AWS CRT callbacks
                _logger.debug(
                    f"Subscribe to '{redact_topic(topic)}' was cancelled "
                    "but will complete in background"
                )
                raise

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

        except (AwsCrtError, RuntimeError) as e:
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
            raise MqttNotConnectedError("Not connected to MQTT broker")

        _logger.info(f"Unsubscribing from topic: {redact_topic(topic)}")

        try:
            # Convert concurrent.futures.Future to asyncio.Future and await
            # Use shield to prevent cancellation from propagating to
            # underlying future
            unsubscribe_future, packet_id = self._connection.unsubscribe(topic)
            try:
                await asyncio.shield(asyncio.wrap_future(unsubscribe_future))
            except asyncio.CancelledError:
                # Shield was cancelled - the underlying unsubscribe will
                # complete independently, preventing InvalidStateError
                # in AWS CRT callbacks
                _logger.debug(
                    f"Unsubscribe from '{redact_topic(topic)}' was "
                    "cancelled but will complete in background"
                )
                raise

            # Remove from tracking
            self._subscriptions.pop(topic, None)
            self._message_handlers.pop(topic, None)

            _logger.info(f"Unsubscribed from '{topic}'")

            return int(packet_id)

        except (AwsCrtError, RuntimeError) as e:
            _logger.error(
                f"Failed to unsubscribe from '{redact_topic(topic)}': {e}"
            )
            raise

    async def resubscribe_all(self) -> None:
        """
        Re-establish all subscriptions after a connection rebuild.

        This method is called after a deep reconnection to restore all
        active subscriptions. It uses the stored subscription information
        to re-subscribe to all topics with their original QoS settings
        and handlers.

        Note:
            This is typically called automatically during deep reconnection
            and should not need to be called manually.

        Raises:
            RuntimeError: If not connected to MQTT broker
            Exception: If any subscription fails
        """
        if not self._connection:
            raise MqttNotConnectedError("Not connected to MQTT broker")

        if not self._subscriptions:
            _logger.debug("No subscriptions to restore")
            return

        subscription_count = len(self._subscriptions)
        _logger.info(f"Re-establishing {subscription_count} subscription(s)...")

        # Store subscriptions to re-establish (avoid modifying dict during
        # iteration)
        subscriptions_to_restore = list(self._subscriptions.items())
        handlers_to_restore = {
            topic: handlers.copy()
            for topic, handlers in self._message_handlers.items()
        }

        # Clear current subscriptions (will be re-added by subscribe())
        self._subscriptions.clear()
        self._message_handlers.clear()

        # Re-establish each subscription
        failed_subscriptions = set()
        for topic, qos in subscriptions_to_restore:
            handlers = handlers_to_restore.get(topic, [])
            for handler in handlers:
                try:
                    await self.subscribe(topic, handler, qos)
                except (AwsCrtError, RuntimeError) as e:
                    _logger.error(
                        f"Failed to re-subscribe to "
                        f"'{redact_topic(topic)}': {e}"
                    )
                    # Mark topic as failed and skip remaining handlers
                    # since they will fail for the same reason
                    failed_subscriptions.add(topic)
                    break  # Exit handler loop, move to next topic

        if failed_subscriptions:
            _logger.warning(
                f"Failed to restore {len(failed_subscriptions)} subscription(s)"
            )
        else:
            _logger.info("All subscriptions re-established successfully")

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
        device_type = str(device.device_info.device_type)
        response_topic = MqttTopicBuilder.command_topic(
            device_type, device_id, "#"
        )
        return await self.subscribe(response_topic, callback)

    async def subscribe_device_status(
        self, device: Device, callback: Callable[[DeviceStatus], None]
    ) -> int:
        """Subscribe to device status messages with automatic parsing."""

        def post_parse(status: DeviceStatus) -> None:
            self._schedule_coroutine(
                self._event_emitter.emit("status_received", status)
            )
            self._schedule_coroutine(self._detect_state_changes(status))

        handler = self._make_handler(
            DeviceStatus, callback, "status", post_parse
        )
        return await self.subscribe_device(device=device, callback=handler)

    def _make_handler(
        self,
        model: Any,
        callback: Callable[[Any], None],
        key: str | None = None,
        post_parse: Callable[[Any], None] | None = None,
    ) -> Callable[[str, dict[str, Any]], None]:
        """Generic factory for MQTT message handlers."""

        def handler(topic: str, message: dict[str, Any]) -> None:
            try:
                res = message.get("response", {})
                # Try nested response field, then fallback to top-level
                data = (res.get(key) if key else res) or (
                    message.get(key) if key else None
                )
                if not data:
                    return

                parsed = model.from_dict(data)
                if post_parse:
                    post_parse(parsed)
                callback(parsed)
            except (
                ValidationError,
                KeyError,
                ValueError,
                TypeError,
                AttributeError,
            ) as e:
                _logger.warning(
                    f"Error parsing {model.__name__} on {topic}: {e}"
                )

        return handler

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
            if status.dhw_temperature != prev.dhw_temperature:
                await self._event_emitter.emit(
                    "temperature_changed",
                    prev.dhw_temperature,
                    status.dhw_temperature,
                )
                _logger.debug(
                    f"Temperature changed: {prev.dhw_temperature}°F → "
                    f"{status.dhw_temperature}°F"
                )

            # Operation mode change
            if status.operation_mode != prev.operation_mode:
                await self._event_emitter.emit(
                    "mode_changed",
                    prev.operation_mode,
                    status.operation_mode,
                )
                _logger.debug(
                    f"Mode changed: {prev.operation_mode} → "
                    f"{status.operation_mode}"
                )

            # Power consumption change
            if status.current_inst_power != prev.current_inst_power:
                await self._event_emitter.emit(
                    "power_changed",
                    prev.current_inst_power,
                    status.current_inst_power,
                )
                _logger.debug(
                    f"Power changed: {prev.current_inst_power}W → "
                    f"{status.current_inst_power}W"
                )

            # Heating started/stopped
            prev_heating = prev.current_inst_power > 0
            curr_heating = status.current_inst_power > 0

            if curr_heating and not prev_heating:
                await self._event_emitter.emit("heating_started", status)
                _logger.debug("Heating started")

            if not curr_heating and prev_heating:
                await self._event_emitter.emit("heating_stopped", status)
                _logger.debug("Heating stopped")

            # Error detection
            if status.error_code and not prev.error_code:
                await self._event_emitter.emit(
                    "error_detected", status.error_code, status
                )
                _logger.info(f"Error detected: {status.error_code}")

            if not status.error_code and prev.error_code:
                await self._event_emitter.emit("error_cleared", prev.error_code)
                _logger.info(f"Error cleared: {prev.error_code}")

        except (TypeError, AttributeError, RuntimeError) as e:
            _logger.error(f"Error detecting state changes: {e}", exc_info=True)
        finally:
            # Always update previous status
            self._previous_status = status

    async def subscribe_device_feature(
        self, device: Device, callback: Callable[[DeviceFeature], None]
    ) -> int:
        """Subscribe to device feature/info messages with automatic parsing."""

        def post_parse(feature: DeviceFeature) -> None:
            if self._device_info_cache:
                self._schedule_coroutine(
                    self._device_info_cache.set(
                        device.device_info.mac_address, feature
                    )
                )
            self._schedule_coroutine(
                self._event_emitter.emit("feature_received", feature)
            )

        handler = self._make_handler(
            DeviceFeature, callback, "feature", post_parse
        )
        return await self.subscribe_device(device=device, callback=handler)

    async def subscribe_energy_usage(
        self,
        device: Device,
        callback: Callable[[EnergyUsageResponse], None],
    ) -> int:
        """Subscribe to energy usage responses with automatic parsing."""
        handler = self._make_handler(EnergyUsageResponse, callback)
        topic = MqttTopicBuilder.response_topic(
            str(device.device_info.device_type),
            self._client_id,
            "energy-usage-daily-query/rd",
        )
        return await self.subscribe(topic, handler)

    def clear_subscriptions(self) -> None:
        """Clear all subscription tracking (called on disconnect)."""
        self._subscriptions.clear()
        self._message_handlers.clear()
        self._previous_status = None
