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
from typing import TYPE_CHECKING, Any, cast

from awscrt import mqtt
from awscrt.exceptions import AwsCrtError
from pydantic import ValidationError

from ..events import EventEmitter
from ..exceptions import MqttNotConnectedError
from ..models import (
    Device,
    DeviceFeature,
    DeviceStatus,
    EnergyUsageResponse,
    RecirculationSchedule,
    ReservationSchedule,
    WeeklyReservationSchedule,
)
from ..mqtt_events import FeatureReceivedEvent, StatusReceivedEvent
from ..topic_builder import MqttTopicBuilder
from .state_tracker import DeviceStateTracker
from .utils import get_response_data, redact_topic, topic_matches_pattern

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

        # Per-device state change detection
        self._state_tracker = DeviceStateTracker(event_emitter)

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
            _logger.debug("Received message on topic: %s", redact_topic(topic))

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

        # Track handler first
        if topic not in self._message_handlers:
            self._message_handlers[topic] = []
        if callback not in self._message_handlers[topic]:
            self._message_handlers[topic].append(callback)

        # Check if already subscribed to this topic at the broker level
        if topic in self._subscriptions:
            # Already subscribed. If requested QoS is higher than current,
            # we should upgrade, but standard practice is to just return.
            # Most brokers handle multiple overlapping subscriptions.
            # Return a synthetic packet ID (0) as we didn't send a request.
            return 0

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

            # Store subscription
            self._subscriptions[topic] = qos

            return int(packet_id)

        except (AwsCrtError, RuntimeError) as e:
            # Clean up handler on failure if this was the first one
            if (h := self._message_handlers.get(topic)) and callback in h:
                h.remove(callback)
            _logger.error(
                f"Failed to subscribe to '{redact_topic(topic)}': {e}"
            )
            raise

    async def unsubscribe(
        self,
        topic: str,
        callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> int:
        """
        Unsubscribe from an MQTT topic.

        If a callback is provided, only that specific handler is removed.
        The underlying MQTT unsubscribe from the broker is only performed
        if no handlers remain for the topic.

        If no callback is provided, all handlers are removed and the broker
        is unsubscribed immediately.

        Args:
            topic: MQTT topic to unsubscribe from
            callback: Optional specific handler to remove

        Returns:
            Unsubscribe packet ID (or 0 if no broker call was made)

        Raises:
            RuntimeError: If not connected to MQTT broker
            Exception: If unsubscribe fails
        """
        if not self._connection:
            raise MqttNotConnectedError("Not connected to MQTT broker")

        if topic not in self._message_handlers:
            return 0

        if callback is not None:
            # Remove specific handler
            if callback in self._message_handlers[topic]:
                self._message_handlers[topic].remove(callback)

            # If handlers still exist, don't unsubscribe from broker yet
            if self._message_handlers[topic]:
                return 0

        # No callback provided or no handlers left: unsubscribe from broker
        _logger.info("Unsubscribing from topic (redacted)")

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
                    "Unsubscribe from topic (redacted) was "
                    "cancelled but will complete in background"
                )
                raise

            # Remove from tracking
            self._subscriptions.pop(topic, None)
            self._message_handlers.pop(topic, None)

            _logger.info("Unsubscribed from topic (redacted)")

            return int(packet_id)

        except (AwsCrtError, RuntimeError) as e:
            _logger.error(f"Failed to unsubscribe from topic (redacted): {e}")
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

        # Re-establish each subscription — one network call per topic,
        # regardless of how many handlers are registered for it.
        failed_subscriptions: set[str] = set()
        for topic, qos in subscriptions_to_restore:
            handlers = handlers_to_restore.get(topic, [])
            if not handlers:
                continue
            try:
                # One network subscribe for the first handler
                await self.subscribe(topic, handlers[0], qos)
            except (AwsCrtError, RuntimeError) as e:
                _logger.error(
                    f"Failed to re-subscribe to '{redact_topic(topic)}': {e}"
                )
                failed_subscriptions.add(topic)
                continue

            # Register remaining handlers without extra network calls
            for handler in handlers[1:]:
                if handler not in self._message_handlers[topic]:
                    self._message_handlers[topic].append(handler)

        if failed_subscriptions:
            # Restore failed subscriptions to internal state so they can be
            # retried on the next reconnection cycle.
            qos_map = dict(subscriptions_to_restore)
            for topic in failed_subscriptions:
                self._subscriptions[topic] = qos_map.get(
                    topic, mqtt.QoS.AT_LEAST_ONCE
                )
                self._message_handlers[topic] = handlers_to_restore.get(
                    topic, []
                )
            _logger.warning(
                f"Failed to restore {len(failed_subscriptions)} "
                "subscription(s); will retry on next reconnection"
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
        device_mac = device.device_info.mac_address

        def post_parse(status: DeviceStatus) -> None:
            self._schedule_coroutine(
                self._event_emitter.emit(
                    "status_received",
                    StatusReceivedEvent(status=status),
                )
            )
            self._schedule_coroutine(
                self._state_tracker.process(device_mac, status)
            )

        handler = self._make_handler(
            DeviceStatus, callback, "status", post_parse
        )
        return await self.subscribe_device(device=device, callback=handler)

    async def unsubscribe_device_status(
        self, device: Device, callback: Callable[[DeviceStatus], None]
    ) -> None:
        """Unsubscribe a specific device status callback."""
        device_id = device.device_info.mac_address
        device_type = str(device.device_info.device_type)
        topic = MqttTopicBuilder.command_topic(device_type, device_id, "#")

        target_handler = None
        if topic in self._message_handlers:
            for h in self._message_handlers[topic]:
                if getattr(h, "_original_callback", None) == callback:
                    target_handler = h
                    break

        if target_handler:
            await self.unsubscribe(topic, target_handler)

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
                data = get_response_data(message, key)
                if not data:
                    return

                parsed = model.model_validate(data)
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

        cast(Any, handler)._original_callback = callback
        return handler

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
                self._event_emitter.emit(
                    "feature_received",
                    FeatureReceivedEvent(feature=feature),
                )
            )

        handler = self._make_handler(
            DeviceFeature, callback, "feature", post_parse
        )
        return await self.subscribe_device(device=device, callback=handler)

    async def unsubscribe_device_feature(
        self, device: Device, callback: Callable[[DeviceFeature], None]
    ) -> None:
        """Unsubscribe a specific device feature callback."""
        device_id = device.device_info.mac_address
        device_type = str(device.device_info.device_type)
        topic = MqttTopicBuilder.command_topic(device_type, device_id, "#")

        if topic not in self._message_handlers:
            return

        # Find the specific internal handler that wraps this callback
        target_handler = None
        for h in self._message_handlers[topic]:
            if getattr(h, "_original_callback", None) == callback:
                target_handler = h
                break

        if target_handler:
            await self.unsubscribe(topic, target_handler)

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

    async def unsubscribe_energy_usage(
        self,
        device: Device,
        callback: Callable[[EnergyUsageResponse], None],
    ) -> None:
        """Unsubscribe a specific energy usage callback."""
        topic = MqttTopicBuilder.response_topic(
            str(device.device_info.device_type),
            self._client_id,
            "energy-usage-daily-query/rd",
        )

        target_handler = None
        if topic in self._message_handlers:
            for h in self._message_handlers[topic]:
                if getattr(h, "_original_callback", None) == callback:
                    target_handler = h
                    break

        if target_handler:
            await self.unsubscribe(topic, target_handler)

    async def subscribe_reservation_response(
        self,
        device: Device,
        callback: Callable[[ReservationSchedule], None],
    ) -> int:
        """Subscribe to reservation read responses with automatic parsing.

        Subscribes to the ``rsv/rd`` response topic for the given device.
        The callback receives a fully-parsed
        :class:`~nwp500.models.ReservationSchedule` whenever the device
        responds to a reservation read request.

        Args:
            device: Device whose reservation responses to receive.
            callback: Called with the parsed schedule on each response.

        Returns:
            Publish packet ID from the MQTT subscribe call.
        """
        handler = self._make_handler(ReservationSchedule, callback)
        topic = MqttTopicBuilder.response_topic(
            str(device.device_info.device_type),
            self._client_id,
            "rsv/rd",
        )
        return await self.subscribe(topic, handler)

    async def unsubscribe_reservation_response(
        self,
        device: Device,
        callback: Callable[[ReservationSchedule], None],
    ) -> None:
        """Unsubscribe a specific reservation response callback."""
        topic = MqttTopicBuilder.response_topic(
            str(device.device_info.device_type),
            self._client_id,
            "rsv/rd",
        )

        target_handler = None
        if topic in self._message_handlers:
            for h in self._message_handlers[topic]:
                if getattr(h, "_original_callback", None) == callback:
                    target_handler = h
                    break

        if target_handler:
            await self.unsubscribe(topic, target_handler)

    async def subscribe_weekly_reservation_response(
        self,
        device: Device,
        callback: Callable[[WeeklyReservationSchedule], None],
    ) -> int:
        """Subscribe to weekly reservation read responses.

        Subscribes to the ``rsv-weekly/rd`` response topic for the given
        device. The callback receives a
        :class:`~nwp500.models.WeeklyReservationSchedule`
        whenever the device responds to a weekly reservation read request.

        Args:
            device: Device whose weekly reservation responses to receive.
            callback: Called with the parsed schedule on each response.

        Returns:
            Publish packet ID from the MQTT subscribe call.
        """
        handler = self._make_handler(WeeklyReservationSchedule, callback)
        topic = MqttTopicBuilder.response_topic(
            str(device.device_info.device_type),
            self._client_id,
            "rsv-weekly/rd",
        )
        return await self.subscribe(topic, handler)

    async def unsubscribe_weekly_reservation_response(
        self,
        device: Device,
        callback: Callable[[WeeklyReservationSchedule], None],
    ) -> None:
        """Unsubscribe a specific weekly reservation callback."""
        topic = MqttTopicBuilder.response_topic(
            str(device.device_info.device_type),
            self._client_id,
            "rsv-weekly/rd",
        )

        target_handler = None
        if topic in self._message_handlers:
            for h in self._message_handlers[topic]:
                if getattr(h, "_original_callback", None) == callback:
                    target_handler = h
                    break

        if target_handler:
            await self.unsubscribe(topic, target_handler)

    async def subscribe_recirculation_schedule_response(
        self,
        device: Device,
        callback: Callable[[RecirculationSchedule], None],
    ) -> int:
        """Subscribe to recirculation schedule read responses.

        Subscribes to the ``recirc-rsv/rd`` response topic for the given device.
        The callback receives a :class:`~nwp500.models.RecirculationSchedule`
        whenever the device responds to a recirculation schedule read request.

        Args:
            device: Device whose recirculation schedule responses to receive.
            callback: Called with the parsed schedule on each response.

        Returns:
            Publish packet ID from the MQTT subscribe call.
        """
        handler = self._make_handler(RecirculationSchedule, callback)
        topic = MqttTopicBuilder.response_topic(
            str(device.device_info.device_type),
            self._client_id,
            "recirc-rsv/rd",
        )
        return await self.subscribe(topic, handler)

    async def unsubscribe_recirculation_schedule_response(
        self,
        device: Device,
        callback: Callable[[RecirculationSchedule], None],
    ) -> None:
        """Unsubscribe a specific recirculation schedule callback."""
        topic = MqttTopicBuilder.response_topic(
            str(device.device_info.device_type),
            self._client_id,
            "recirc-rsv/rd",
        )

        target_handler = None
        if topic in self._message_handlers:
            for h in self._message_handlers[topic]:
                if getattr(h, "_original_callback", None) == callback:
                    target_handler = h
                    break

        if target_handler:
            await self.unsubscribe(topic, target_handler)

    def clear_subscriptions(self) -> None:
        """Clear all subscription tracking (called on disconnect)."""
        self._subscriptions.clear()
        self._message_handlers.clear()
        self._state_tracker.clear()
