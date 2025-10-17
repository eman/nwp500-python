"""
MQTT Client for Navien Smart Control.

This module provides an MQTT client for real-time communication with Navien
devices using AWS IoT Core. It handles connection, subscriptions, and message
publishing for device control and monitoring.

The client uses WebSocket connections with AWS credentials obtained from
the authentication flow.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from awscrt import mqtt
from awscrt.exceptions import AwsCrtError
from awsiot import mqtt_connection_builder

from .auth import NavienAuthClient
from .config import AWS_IOT_ENDPOINT, AWS_REGION
from .constants import (
    CMD_ANTI_LEGIONELLA_DISABLE,
    CMD_ANTI_LEGIONELLA_ENABLE,
    CMD_DEVICE_INFO_REQUEST,
    CMD_DHW_MODE,
    CMD_DHW_TEMPERATURE,
    CMD_ENERGY_USAGE_QUERY,
    CMD_POWER_OFF,
    CMD_POWER_ON,
    CMD_RESERVATION_MANAGEMENT,
    CMD_STATUS_REQUEST,
    CMD_TOU_DISABLE,
    CMD_TOU_ENABLE,
    CMD_TOU_SETTINGS,
)
from .events import EventEmitter
from .models import (
    Device,
    DeviceFeature,
    DeviceStatus,
    EnergyUsageResponse,
    OperationMode,
)

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


def _redact(obj, keys_to_redact=None):
    """Return a redacted copy of obj with sensitive keys masked.

    This is a lightweight sanitizer for log messages to avoid emitting
    secrets such as access keys, session tokens, passwords, emails,
    clientIDs and sessionIDs.
    """
    if keys_to_redact is None:
        keys_to_redact = {
            "access_key_id",
            "secret_access_key",
            "secret_key",
            "session_token",
            "sessionToken",
            "sessionID",
            "clientID",
            "clientId",
            "client_id",
            "password",
            "pushToken",
            "push_token",
            "token",
            "auth",
            "macAddress",
            "mac_address",
            "email",
        }

    # Primitive types: return as-is
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        # avoid printing long secret-like strings fully
        if len(obj) > 256:
            return obj[:64] + "...<redacted>..." + obj[-64:]
        return obj

    # dicts: redact sensitive keys recursively
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            if str(k) in keys_to_redact:
                redacted[k] = "<REDACTED>"
            else:
                redacted[k] = _redact(v, keys_to_redact)
        return redacted

    # lists / tuples: redact elements
    if isinstance(obj, (list, tuple)):
        return type(obj)(_redact(v, keys_to_redact) for v in obj)

    # fallback: represent object as string but avoid huge dumps
    try:
        s = str(obj)
        if len(s) > 512:
            return s[:256] + "...<redacted>..."
        return s
    except Exception:
        return "<UNREPRABLE>"


def _redact_topic(topic: str) -> str:
    """
    Redact sensitive information from MQTT topic strings.

    Topics often contain MAC addresses or device unique identifiers, e.g.:
    - cmd/52/navilink-04786332fca0/st/did
    - cmd/52/navilink-04786332fca0/ctrl
    - cmd/52/04786332fca0/ctrl
    - or with colons/hyphens (04:78:63:32:fc:a0 or 04-78-63-32-fc-a0)

    Args:
        topic: MQTT topic string

    Returns:
        Topic with MAC addresses redacted
    """
    import re

    # Redact navilink-<mac>
    topic = re.sub(r"(navilink-)[0-9a-fA-F]{12}", r"\1REDACTED", topic)
    # Redact bare 12-hex MACs (lower/upper)
    topic = re.sub(r"\b[0-9a-fA-F]{12}\b", "REDACTED", topic)
    # Redact colon-delimited MAC format (e.g., 04:78:63:32:fc:a0)
    topic = re.sub(r"\b([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b", "REDACTED", topic)
    # Redact hyphen-delimited MAC format (e.g., 04-78-63-32-fc-a0)
    topic = re.sub(r"\b([0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}\b", "REDACTED", topic)
    return topic


@dataclass
class MqttConnectionConfig:
    """Configuration for MQTT connection."""

    endpoint: str = AWS_IOT_ENDPOINT
    region: str = AWS_REGION
    client_id: Optional[str] = None
    clean_session: bool = True
    keep_alive_secs: int = 1200

    # Reconnection settings
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 10
    initial_reconnect_delay: float = 1.0  # seconds
    max_reconnect_delay: float = 120.0  # seconds
    reconnect_backoff_multiplier: float = 2.0

    # Command queue settings
    enable_command_queue: bool = True
    max_queued_commands: int = 100

    def __post_init__(self):
        """Generate client ID if not provided."""
        if not self.client_id:
            self.client_id = f"navien-client-{uuid.uuid4().hex[:8]}"


@dataclass
class QueuedCommand:
    """Represents a command that is queued for sending when reconnected."""

    topic: str
    payload: dict[str, Any]
    qos: mqtt.QoS
    timestamp: datetime


class PeriodicRequestType(Enum):
    """Types of periodic requests that can be sent."""

    DEVICE_INFO = "device_info"
    DEVICE_STATUS = "device_status"


class NavienMqttClient(EventEmitter):
    """
    Async MQTT client for Navien device communication over AWS IoT.

    This client establishes WebSocket connections to AWS IoT Core using
    temporary AWS credentials from the authentication API. It handles:
    - Connection management with automatic reconnection and exponential backoff
    - Topic subscriptions for device events and responses
    - Command publishing for device control
    - Message routing and callbacks
    - Command queuing when disconnected (sends when reconnected)
    - Event-driven architecture with state change detection

    The client extends EventEmitter to provide an event-driven architecture:
    - Multiple listeners per event
    - State change detection (temperature_changed, mode_changed, etc.)
    - Async handler support
    - Priority-based execution

    The client automatically reconnects when the connection is interrupted,
    using exponential backoff (default: 1s, 2s, 4s, 8s, ... up to 120s).
    Reconnection behavior can be customized via MqttConnectionConfig.

    When enabled, the command queue stores commands sent while disconnected
    and automatically sends them when the connection is restored. This ensures
    commands are not lost during temporary network interruptions.

    Example (Traditional Callbacks)::

        >>> async with NavienAuthClient(email, password) as auth_client:
        ...     mqtt_client = NavienMqttClient(auth_client)
        ...     await mqtt_client.connect()
        ...
        ...     # Traditional callback style
        ...     await mqtt_client.subscribe_device_status(device, on_status)

    Example (Event Emitter)::

        >>> mqtt_client = NavienMqttClient(auth_client)
        ...
        ... # Register multiple listeners
        ... mqtt_client.on('temperature_changed', log_temperature)
        ... mqtt_client.on('temperature_changed', update_ui)
        ... mqtt_client.on('mode_changed', handle_mode_change)
        ...
        ... # One-time listener
        ... mqtt_client.once('device_ready', initialize)
        ...
        ... await mqtt_client.connect()

    Events Emitted:
        - status_received: Raw status update (DeviceStatus)
        - feature_received: Device feature/info (DeviceFeature)
        - temperature_changed: Temperature changed (old_temp, new_temp)
        - mode_changed: Operation mode changed (old_mode, new_mode)
        - power_changed: Power consumption changed (old_power, new_power)
        - heating_started: Device started heating (status)
        - heating_stopped: Device stopped heating (status)
        - error_detected: Error code detected (error_code, status)
        - error_cleared: Error code cleared (error_code)
        - connection_interrupted: Connection lost (error)
        - connection_resumed: Connection restored (return_code, session_present)
        - reconnection_failed: Reconnection permanently failed after max attempts (attempt_count)
    """

    def __init__(
        self,
        auth_client: NavienAuthClient,
        config: Optional[MqttConnectionConfig] = None,
        on_connection_interrupted: Optional[Callable] = None,
        on_connection_resumed: Optional[Callable] = None,
    ):
        """
        Initialize the MQTT client.

        Args:
            auth_client: Authentication client with valid tokens
            config: Optional connection configuration
            on_connection_interrupted: Callback for connection interruption
            on_connection_resumed: Callback for connection resumption

        Raises:
            ValueError: If auth client is not authenticated or AWS credentials are not available
        """
        if not auth_client.is_authenticated:
            raise ValueError(
                "Authentication client must be authenticated before creating MQTT client. "
                "Call auth_client.sign_in() first."
            )

        if not auth_client.current_tokens:
            raise ValueError("No tokens available from auth client")

        auth_tokens = auth_client.current_tokens
        if not auth_tokens.access_key_id or not auth_tokens.secret_key:
            raise ValueError(
                "AWS credentials not available in auth tokens. "
                "Ensure authentication provides AWS IoT credentials."
            )

        # Initialize EventEmitter
        super().__init__()

        self._auth_client = auth_client
        self.config = config or MqttConnectionConfig()

        self._connection: Optional[mqtt.Connection] = None
        self._connected = False
        self._subscriptions: dict[str, int] = {}  # topic -> qos
        self._message_handlers: dict[str, list[Callable]] = {}  # topic -> [callbacks]

        # Session tracking
        self._session_id = uuid.uuid4().hex

        # Periodic request tasks
        self._periodic_tasks: dict[str, asyncio.Task] = {}  # task_name -> task

        # Reconnection state
        self._reconnect_attempts = 0
        self._reconnect_task: Optional[asyncio.Task] = None
        self._manual_disconnect = False

        # Command queue
        self._command_queue: deque[QueuedCommand] = deque(maxlen=self.config.max_queued_commands)

        # State tracking for change detection
        self._previous_status: Optional[DeviceStatus] = None
        self._previous_feature: Optional[DeviceFeature] = None

        # User-provided callbacks
        self._on_connection_interrupted = on_connection_interrupted
        self._on_connection_resumed = on_connection_resumed

        # Store event loop reference for thread-safe coroutine scheduling
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        _logger.info(f"Initialized MQTT client with ID: {self.config.client_id}")

    def _schedule_coroutine(self, coro):
        """
        Schedule a coroutine to run in the event loop from any thread.

        This method is thread-safe and handles scheduling coroutines from
        MQTT callback threads that don't have their own event loop.

        Args:
            coro: Coroutine to schedule
        """
        if self._loop is None:
            # Try to get the current loop as fallback
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                _logger.warning("No event loop available to schedule coroutine")
                return

        # Schedule the coroutine in the stored loop using thread-safe method
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except Exception as e:
            _logger.error(f"Failed to schedule coroutine: {e}", exc_info=True)

    def _on_connection_interrupted_internal(self, connection, error, **kwargs):
        """Internal handler for connection interruption."""
        _logger.warning(f"Connection interrupted: {error}")
        self._connected = False

        # Emit event
        self._schedule_coroutine(self.emit("connection_interrupted", error))

        # Call user callback
        if self._on_connection_interrupted:
            self._on_connection_interrupted(error)

        # Start automatic reconnection if enabled and not manually disconnected
        if (
            self.config.auto_reconnect
            and not self._manual_disconnect
            and (not self._reconnect_task or self._reconnect_task.done())
        ):
            _logger.info("Starting automatic reconnection...")
            self._schedule_coroutine(self._start_reconnect_task())

    def _on_connection_resumed_internal(self, connection, return_code, session_present, **kwargs):
        """Internal handler for connection resumption."""
        _logger.info(
            f"Connection resumed: return_code={return_code}, session_present={session_present}"
        )
        self._connected = True
        self._reconnect_attempts = 0  # Reset reconnection attempts on successful connection

        # Cancel any pending reconnection task
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None

        # Emit event
        self._schedule_coroutine(self.emit("connection_resumed", return_code, session_present))

        # Call user callback
        if self._on_connection_resumed:
            self._on_connection_resumed(return_code, session_present)

        # Send any queued commands
        if self.config.enable_command_queue:
            self._schedule_coroutine(self._send_queued_commands())

    async def _start_reconnect_task(self):
        """
        Start the reconnect task within the event loop.

        This is a helper method to create the reconnect task from within
        a coroutine that's scheduled via _schedule_coroutine.
        """
        if not self._reconnect_task or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_with_backoff())

    async def _reconnect_with_backoff(self):
        """
        Attempt to reconnect with exponential backoff.

        This method is called automatically when connection is interrupted
        if auto_reconnect is enabled.
        """
        while (
            not self._connected
            and not self._manual_disconnect
            and self._reconnect_attempts < self.config.max_reconnect_attempts
        ):
            self._reconnect_attempts += 1

            # Calculate delay with exponential backoff
            delay = min(
                self.config.initial_reconnect_delay
                * (self.config.reconnect_backoff_multiplier ** (self._reconnect_attempts - 1)),
                self.config.max_reconnect_delay,
            )

            _logger.info(
                "Reconnection attempt %d/%d in %.1f seconds...",
                self._reconnect_attempts,
                self.config.max_reconnect_attempts,
                delay,
            )

            try:
                await asyncio.sleep(delay)

                if self._manual_disconnect:
                    _logger.info("Reconnection cancelled due to manual disconnect")
                    break

                # AWS IoT SDK will handle the actual reconnection automatically
                # We just need to wait and monitor the connection state
                _logger.debug("Waiting for AWS IoT SDK automatic reconnection...")

            except asyncio.CancelledError:
                _logger.info("Reconnection task cancelled")
                break
            except Exception as e:
                _logger.error(f"Error during reconnection attempt: {e}")

        if self._reconnect_attempts >= self.config.max_reconnect_attempts:
            _logger.error(
                f"Failed to reconnect after {self.config.max_reconnect_attempts} attempts. "
                "Manual reconnection required."
            )
            # Stop all periodic tasks to reduce log noise
            await self._stop_all_periodic_tasks()
            # Emit event so users can take action
            self._schedule_coroutine(self.emit("reconnection_failed", self._reconnect_attempts))

    async def _send_queued_commands(self):
        """
        Send all queued commands after reconnection.

        This is called automatically when connection is restored.
        """
        if not self._command_queue:
            return

        queue_size = len(self._command_queue)
        _logger.info(f"Sending {queue_size} queued command(s)...")

        sent_count = 0
        failed_count = 0

        while self._command_queue and self._connected:
            command = self._command_queue.popleft()

            try:
                # Publish the queued command
                await self.publish(
                    topic=command.topic,
                    payload=command.payload,
                    qos=command.qos,
                )
                sent_count += 1
                _logger.debug(
                    f"Sent queued command to '{command.topic}' "
                    f"(queued at {command.timestamp.isoformat()})"
                )
            except Exception as e:
                failed_count += 1
                _logger.error(
                    f"Failed to send queued command to '{_redact_topic(command.topic)}': {e}"
                )
                # Re-queue if there's room
                if len(self._command_queue) < self.config.max_queued_commands:
                    self._command_queue.append(command)
                    _logger.warning("Re-queued failed command")
                break  # Stop processing on error to avoid cascade failures

        if sent_count > 0:
            _logger.info(
                f"Sent {sent_count} queued command(s)"
                + (f", {failed_count} failed" if failed_count > 0 else "")
            )

    def _queue_command(self, topic: str, payload: dict[str, Any], qos: mqtt.QoS) -> None:
        """
        Add a command to the queue.

        Args:
            topic: MQTT topic
            payload: Command payload
            qos: Quality of Service level
        """
        if not self.config.enable_command_queue:
            _logger.warning(
                f"Command queue disabled, dropping command to '{topic}'. "
                "Enable command queue in config to queue commands when disconnected."
            )
            return

        command = QueuedCommand(topic=topic, payload=payload, qos=qos, timestamp=datetime.utcnow())

        # If queue is full, oldest command will be dropped automatically (deque with maxlen)
        if len(self._command_queue) >= self.config.max_queued_commands:
            _logger.warning(
                f"Command queue full ({self.config.max_queued_commands}), dropping oldest command"
            )

        self._command_queue.append(command)
        _logger.info(f"Queued command (queue size: {len(self._command_queue)})")

    async def connect(self) -> bool:
        """
        Establish connection to AWS IoT Core.

        Ensures tokens are valid before connecting and refreshes if necessary.

        Returns:
            True if connection successful

        Raises:
            Exception: If connection fails
        """
        if self._connected:
            _logger.warning("Already connected")
            return True

        # Capture the event loop for thread-safe coroutine scheduling
        self._loop = asyncio.get_running_loop()

        # Mark as not a manual disconnect
        self._manual_disconnect = False

        # Ensure we have valid tokens before connecting
        await self._auth_client.ensure_valid_token()

        _logger.info(f"Connecting to AWS IoT endpoint: {self.config.endpoint}")
        _logger.debug(f"Client ID: {self.config.client_id}")
        _logger.debug(f"Region: {self.config.region}")

        try:
            # Build WebSocket MQTT connection with AWS credentials
            self._connection = mqtt_connection_builder.websockets_with_default_aws_signing(
                endpoint=self.config.endpoint,
                region=self.config.region,
                credentials_provider=self._create_credentials_provider(),
                client_id=self.config.client_id,
                clean_session=self.config.clean_session,
                keep_alive_secs=self.config.keep_alive_secs,
                on_connection_interrupted=self._on_connection_interrupted_internal,
                on_connection_resumed=self._on_connection_resumed_internal,
            )

            # Connect
            _logger.info("Establishing MQTT connection...")

            # Convert concurrent.futures.Future to asyncio.Future and await
            connect_future = self._connection.connect()
            connect_result = await asyncio.wrap_future(connect_future)

            self._connected = True
            self._reconnect_attempts = 0  # Reset on successful connection
            _logger.info(
                f"Connected successfully: session_present={connect_result['session_present']}"
            )

            return True

        except Exception as e:
            _logger.error(f"Failed to connect: {e}")
            raise

    def _create_credentials_provider(self):
        """Create AWS credentials provider from auth tokens."""
        from awscrt.auth import AwsCredentialsProvider

        # Get current tokens from auth client
        auth_tokens = self._auth_client.current_tokens
        if not auth_tokens:
            raise ValueError("No tokens available from auth client")

        return AwsCredentialsProvider.new_static(
            access_key_id=auth_tokens.access_key_id,
            secret_access_key=auth_tokens.secret_key,
            session_token=auth_tokens.session_token,
        )

    async def disconnect(self):
        """Disconnect from AWS IoT Core and stop all periodic tasks."""
        if not self._connected or not self._connection:
            _logger.warning("Not connected")
            return

        _logger.info("Disconnecting from AWS IoT...")

        # Mark as manual disconnect to prevent automatic reconnection
        self._manual_disconnect = True

        # Cancel any pending reconnection task
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

        # Stop all periodic tasks first
        await self.stop_all_periodic_tasks()

        try:
            # Convert concurrent.futures.Future to asyncio.Future and await
            disconnect_future = self._connection.disconnect()
            await asyncio.wrap_future(disconnect_future)

            self._connected = False
            self._connection = None
            _logger.info("Disconnected successfully")
        except Exception as e:
            _logger.error(f"Error during disconnect: {e}")
            raise

    def _on_message_received(self, topic: str, payload: bytes, **kwargs):
        """Internal callback for received messages."""
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
        """Check if a topic matches a subscription pattern with wildcards."""
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
                if pattern_parts[i] != "+" and topic_parts[i] != pattern_parts[i]:
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
        callback: Callable[[str, dict], None],
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
            Exception: If subscription fails
        """
        if not self._connected:
            raise RuntimeError("Not connected to MQTT broker")

        _logger.info(f"Subscribing to topic: {topic}")

        try:
            # Convert concurrent.futures.Future to asyncio.Future and await
            subscribe_future, packet_id = self._connection.subscribe(
                topic=topic, qos=qos, callback=self._on_message_received
            )
            subscribe_result = await asyncio.wrap_future(subscribe_future)

            _logger.info(f"Subscribed to '{topic}' with QoS {subscribe_result['qos']}")

            # Store subscription and handler
            self._subscriptions[topic] = qos
            if topic not in self._message_handlers:
                self._message_handlers[topic] = []
            self._message_handlers[topic].append(callback)

            return packet_id

        except Exception as e:
            _logger.error(f"Failed to subscribe to '{_redact_topic(topic)}': {e}")
            raise

    async def unsubscribe(self, topic: str) -> int:
        """
        Unsubscribe from an MQTT topic.

        Args:
            topic: MQTT topic to unsubscribe from

        Returns:
            Unsubscribe packet ID

        Raises:
            Exception: If unsubscribe fails
        """
        if not self._connected:
            raise RuntimeError("Not connected to MQTT broker")

        _logger.info(f"Unsubscribing from topic: {topic}")

        try:
            # Convert concurrent.futures.Future to asyncio.Future and await
            unsubscribe_future, packet_id = self._connection.unsubscribe(topic)
            await asyncio.wrap_future(unsubscribe_future)

            # Remove from tracking
            self._subscriptions.pop(topic, None)
            self._message_handlers.pop(topic, None)

            _logger.info(f"Unsubscribed from '{topic}'")

            return packet_id

        except Exception as e:
            _logger.error(f"Failed to unsubscribe from '{_redact_topic(topic)}': {e}")
            raise

    async def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE,
    ) -> int:
        """
        Publish a message to an MQTT topic.

        If not connected and command queue is enabled, the command will be
        queued and sent automatically when the connection is restored.

        Args:
            topic: MQTT topic to publish to
            payload: Message payload (will be JSON-encoded)
            qos: Quality of Service level

        Returns:
            Publish packet ID (or 0 if queued)

        Raises:
            RuntimeError: If not connected and command queue is disabled
        """
        if not self._connected:
            if self.config.enable_command_queue:
                _logger.debug(f"Not connected, queuing command to topic: {topic}")
                self._queue_command(topic, payload, qos)
                return 0  # Return 0 to indicate command was queued
            else:
                raise RuntimeError("Not connected to MQTT broker")

        _logger.debug(f"Publishing to topic: {topic}")

        try:
            # Serialize to JSON
            payload_json = json.dumps(payload)

            # Convert concurrent.futures.Future to asyncio.Future and await
            publish_future, packet_id = self._connection.publish(
                topic=topic, payload=payload_json, qos=qos
            )
            await asyncio.wrap_future(publish_future)

            _logger.debug(f"Published to '{topic}' with packet_id {packet_id}")

            return packet_id

        except Exception as e:
            # Handle clean session cancellation gracefully
            # Check exception type and name attribute for proper error identification
            if (
                isinstance(e, AwsCrtError)
                and e.name == "AWS_ERROR_MQTT_CANCELLED_FOR_CLEAN_SESSION"
            ):
                _logger.warning(
                    "Publish cancelled due to clean session. This is expected during reconnection."
                )
                # Queue the command if queue is enabled
                if self.config.enable_command_queue:
                    _logger.debug("Queuing command due to clean session cancellation")
                    self._queue_command(topic, payload, qos)
                    return 0  # Return 0 to indicate command was queued
                # Otherwise, raise an error so the caller can handle the failure
                raise RuntimeError(
                    "Publish cancelled due to clean session and command queue is disabled"
                )

            _logger.error(f"Failed to publish to '{_redact_topic(topic)}': {e}")
            raise

    # Navien-specific convenience methods

    def _build_command(
        self,
        device_type: int,
        device_id: str,
        command: int,
        additional_value: str = "",
        **kwargs,
    ) -> dict[str, Any]:
        """Build a Navien MQTT command structure."""
        request = {
            "command": command,
            "deviceType": device_type,
            "macAddress": device_id,
            "additionalValue": additional_value,
            **kwargs,
        }

        # Use navilink- prefix for device ID in topics (from reference implementation)
        device_topic = f"navilink-{device_id}"

        return {
            "clientID": self.config.client_id,
            "sessionID": self._session_id,
            "protocolVersion": 2,
            "request": request,
            "requestTopic": f"cmd/{device_type}/{device_topic}",
            "responseTopic": f"cmd/{device_type}/{device_topic}/{self.config.client_id}/res",
        }

    async def subscribe_device(self, device: Device, callback: Callable[[str, dict], None]) -> int:
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
            >>> mqtt_client.on('heating_stopped', lambda s: print("Heating OFF"))
            >>>
            >>> # Subscribe to start receiving events
            >>> await mqtt_client.subscribe_device_status(device, lambda s: None)
        """

        def status_message_handler(topic: str, message: dict):
            """Parse status messages and invoke user callback."""
            try:
                # Log all messages received for debugging
                _logger.debug(f"Status handler received message on topic: {topic}")
                _logger.debug(f"Message keys: {list(message.keys())}")

                # Check if message contains status data
                if "response" not in message:
                    _logger.debug(
                        "Message does not contain 'response' key, skipping. Keys: %s",
                        list(message.keys()),
                    )
                    return

                response = message["response"]
                _logger.debug(f"Response keys: {list(response.keys())}")

                if "status" not in response:
                    _logger.debug(
                        "Response does not contain 'status' key, skipping. Keys: %s",
                        list(response.keys()),
                    )
                    return

                # Parse status into DeviceStatus object
                _logger.info(f"Parsing device status message from topic: {topic}")
                status_data = response["status"]
                device_status = DeviceStatus.from_dict(status_data)

                # Emit raw status event
                self._schedule_coroutine(self.emit("status_received", device_status))

                # Detect and emit state changes
                self._schedule_coroutine(self._detect_state_changes(device_status))

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
                _logger.warning(f"Invalid value in status message: {e}", exc_info=True)
            except Exception as e:
                _logger.error(f"Error parsing device status: {e}", exc_info=True)

        # Subscribe using the internal handler
        return await self.subscribe_device(device=device, callback=status_message_handler)

    async def _detect_state_changes(self, status: DeviceStatus):
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
                await self.emit(
                    "temperature_changed",
                    prev.dhwTemperature,
                    status.dhwTemperature,
                )
                _logger.debug(
                    f"Temperature changed: {prev.dhwTemperature}°F → {status.dhwTemperature}°F"
                )

            # Operation mode change
            if status.operationMode != prev.operationMode:
                await self.emit(
                    "mode_changed",
                    prev.operationMode,
                    status.operationMode,
                )
                _logger.debug(f"Mode changed: {prev.operationMode} → {status.operationMode}")

            # Power consumption change
            if status.currentInstPower != prev.currentInstPower:
                await self.emit(
                    "power_changed",
                    prev.currentInstPower,
                    status.currentInstPower,
                )
                _logger.debug(
                    f"Power changed: {prev.currentInstPower}W → {status.currentInstPower}W"
                )

            # Heating started/stopped
            prev_heating = prev.currentInstPower > 0
            curr_heating = status.currentInstPower > 0

            if curr_heating and not prev_heating:
                await self.emit("heating_started", status)
                _logger.debug("Heating started")

            if not curr_heating and prev_heating:
                await self.emit("heating_stopped", status)
                _logger.debug("Heating stopped")

            # Error detection
            if status.errorCode and not prev.errorCode:
                await self.emit("error_detected", status.errorCode, status)
                _logger.info(f"Error detected: {status.errorCode}")

            if not status.errorCode and prev.errorCode:
                await self.emit("error_cleared", prev.errorCode)
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
            ...     print(f"Temp Range: {feature.dhwTemperatureMin}-{feature.dhwTemperatureMax}°F")
            >>>
            >>> await mqtt_client.subscribe_device_feature(device, on_feature)

            >>> # Or use event emitter
            >>> mqtt_client.on('feature_received', lambda f: print(f"FW: {f.controllerSwVersion}"))
            >>> await mqtt_client.subscribe_device_feature(device, lambda f: None)
        """

        def feature_message_handler(topic: str, message: dict):
            """Parse feature messages and invoke user callback."""
            try:
                # Log all messages received for debugging
                _logger.debug(f"Feature handler received message on topic: {topic}")
                _logger.debug(f"Message keys: {list(message.keys())}")

                # Check if message contains feature data
                if "response" not in message:
                    _logger.debug(
                        "Message does not contain 'response' key, skipping. Keys: %s",
                        list(message.keys()),
                    )
                    return

                response = message["response"]
                _logger.debug(f"Response keys: {list(response.keys())}")

                if "feature" not in response:
                    _logger.debug(
                        "Response does not contain 'feature' key, skipping. Keys: %s",
                        list(response.keys()),
                    )
                    return

                # Parse feature into DeviceFeature object
                _logger.info(f"Parsing device feature message from topic: {topic}")
                feature_data = response["feature"]
                device_feature = DeviceFeature.from_dict(feature_data)

                # Emit feature received event
                self._schedule_coroutine(self.emit("feature_received", device_feature))

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
                _logger.warning(f"Invalid value in feature message: {e}", exc_info=True)
            except Exception as e:
                _logger.error(f"Error parsing device feature: {e}", exc_info=True)

        # Subscribe using the internal handler
        return await self.subscribe_device(device=device, callback=feature_message_handler)

    async def request_device_status(self, device: Device) -> int:
        """
        Request general device status.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value

        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/st"
        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_STATUS_REQUEST,  # Status request command
            additional_value=additional_value,
        )
        command["requestTopic"] = topic

        return await self.publish(topic, command)

    async def request_device_info(self, device: Device) -> int:
        """
        Request device information.

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value

        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/st/did"
        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_DEVICE_INFO_REQUEST,  # Device info command
            additional_value=additional_value,
        )
        command["requestTopic"] = topic

        return await self.publish(topic, command)

    async def set_power(self, device: Device, power_on: bool) -> int:
        """
        Turn device on or off.

        Args:
            device: Device object
            power_on: True to turn on, False to turn off
            device_type: Device type (52 for NWP500)
            additional_value: Additional value from device info

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"
        mode = "power-on" if power_on else "power-off"
        # Command codes: 33554434 for power-on, 33554433 for power-off
        command_code = CMD_POWER_ON if power_on else CMD_POWER_OFF

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=command_code,
            additional_value=additional_value,
            mode=mode,
            param=[],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self.publish(topic, command)

    async def set_dhw_mode(
        self,
        device: Device,
        mode_id: int,
        vacation_days: Optional[int] = None,
    ) -> int:
        """
        Set DHW (Domestic Hot Water) operation mode.

        Args:
            device: Device object
            mode_id: Mode ID (1=Heat Pump Only, 2=Electric Only, 3=Energy Saver,
                4=High Demand, 5=Vacation)
            vacation_days: Number of vacation days (required when mode_id == 5)

        Returns:
            Publish packet ID

        Note:
            Valid selectable mode IDs are 1, 2, 3, 4, and 5 (vacation).
            Additional modes may appear in status responses:
            - 0: Standby (device in idle state)
            - 6: Power Off (device is powered off)

            Mode descriptions:
            - 1: Heat Pump Only (most efficient, slowest recovery)
            - 2: Electric Only (least efficient, fastest recovery)
            - 3: Energy Saver (balanced, good default)
            - 4: High Demand (maximum heating capacity)
            - 5: Vacation Mode (requires vacation_days parameter)
        """
        if mode_id == OperationMode.VACATION.value:
            if vacation_days is None:
                raise ValueError("Vacation mode requires vacation_days (1-30)")
            if not 1 <= vacation_days <= 30:
                raise ValueError("vacation_days must be between 1 and 30")
            param = [mode_id, vacation_days]
        else:
            if vacation_days is not None:
                raise ValueError("vacation_days is only valid for vacation mode (mode 5)")
            param = [mode_id]

        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_DHW_MODE,  # DHW mode control command (different from power commands)
            additional_value=additional_value,
            mode="dhw-mode",
            param=param,
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self.publish(topic, command)

    async def enable_anti_legionella(self, device: Device, period_days: int) -> int:
        """Enable Anti-Legionella disinfection with a 1-30 day cycle.

        This command has been confirmed through HAR analysis of the official Navien app.
        When sent, the device responds with antiLegionellaUse=2 (enabled) and
        antiLegionellaPeriod set to the specified value.

        See docs/MQTT_MESSAGES.rst "Anti-Legionella Control" for the authoritative
        command code (33554472) and expected payload format:
        {"mode": "anti-leg-on", "param": [<period_days>], "paramStr": ""}

        Args:
            device: The device to control
            period_days: Days between disinfection cycles (1-30)

        Returns:
            The message ID of the published command

        Raises:
            ValueError: If period_days is not in the valid range [1, 30]
        """
        if not 1 <= period_days <= 30:
            raise ValueError("period_days must be between 1 and 30")

        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_ANTI_LEGIONELLA_ENABLE,
            additional_value=additional_value,
            mode="anti-leg-on",
            param=[period_days],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self.publish(topic, command)

    async def disable_anti_legionella(self, device: Device) -> int:
        """Disable the Anti-Legionella disinfection cycle.

        This command has been confirmed through HAR analysis of the official Navien app.
        When sent, the device responds with antiLegionellaUse=1 (disabled) while
        antiLegionellaPeriod retains its previous value.

        The correct command code is 33554471 (not 33554473 as previously assumed).

        See docs/MQTT_MESSAGES.rst "Anti-Legionella Control" section for details.

        Returns:
            The message ID of the published command
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_ANTI_LEGIONELLA_DISABLE,
            additional_value=additional_value,
            mode="anti-leg-off",
            param=[],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self.publish(topic, command)

    async def set_dhw_temperature(self, device: Device, temperature: int) -> int:
        """
        Set DHW target temperature.

        IMPORTANT: The temperature value sent in the message is 20 degrees LOWER
        than what displays on the device/app. For example:
        - Send 121°F → Device displays 141°F
        - Send 131°F → Device displays 151°F (capped at 150°F max)

        Valid range: approximately 95-131°F (message value)
        Display range: approximately 115-151°F (display value, max 150°F)

        Args:
            device: Device object
            temperature: Target temperature in Fahrenheit (message value, NOT display value)

        Returns:
            Publish packet ID

        Example:
            # To set display temperature to 140°F, send 120°F
            await client.set_dhw_temperature(device, 120)
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_DHW_TEMPERATURE,  # DHW temperature control command
            additional_value=additional_value,
            mode="dhw-temperature",
            param=[temperature],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self.publish(topic, command)

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_DHW_TEMPERATURE,  # DHW temperature control command
            additional_value=additional_value,
            mode="dhw-temperature",
            param=[temperature],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self.publish(topic, command)

    async def set_dhw_temperature_display(self, device: Device, display_temperature: int) -> int:
        """
        Set DHW target temperature using the DISPLAY value (what you see on device/app).

        This is a convenience method that automatically converts display temperature
        to the message value by subtracting 20 degrees.

        Args:
            device: Device object
            display_temperature: Target temperature as shown on display/app (Fahrenheit)

        Returns:
            Publish packet ID

        Example:
            # To set display temperature to 140°F
            await client.set_dhw_temperature_display(device, 140)
            # This sends 120°F in the message
        """
        message_temperature = display_temperature - 20
        return await self.set_dhw_temperature(device, message_temperature)

    async def update_reservations(
        self,
        device: Device,
        reservations: Sequence[dict[str, Any]],
        *,
        enabled: bool = True,
    ) -> int:
        """Update programmed reservations for temperature/mode changes."""
        # See docs/MQTT_MESSAGES.rst "Reservation Management" for the
        # command code (16777226) and the reservation object fields
        # (enable, week, hour, min, mode, param).
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl/rsv/rd"

        reservation_use = 1 if enabled else 2
        reservation_payload = [dict(entry) for entry in reservations]

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_RESERVATION_MANAGEMENT,
            additional_value=additional_value,
            reservationUse=reservation_use,
            reservation=reservation_payload,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = f"cmd/{device_type}/{self.config.client_id}/res/rsv/rd"

        return await self.publish(topic, command)

    async def request_reservations(self, device: Device) -> int:
        """Request the current reservation program from the device."""
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl/rsv/rd"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_RESERVATION_MANAGEMENT,
            additional_value=additional_value,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = f"cmd/{device_type}/{self.config.client_id}/res/rsv/rd"

        return await self.publish(topic, command)

    async def configure_tou_schedule(
        self,
        device: Device,
        controller_serial_number: str,
        periods: Sequence[dict[str, Any]],
        *,
        enabled: bool = True,
    ) -> int:
        """Configure Time-of-Use pricing schedule via MQTT."""
        # See docs/MQTT_MESSAGES.rst "TOU (Time of Use) Settings" for
        # the command code (33554439) and TOU period fields
        # (season, week, startHour, startMinute, endHour, endMinute,
        #  priceMin, priceMax, decimalPoint).
        if not controller_serial_number:
            raise ValueError("controller_serial_number is required")
        if not periods:
            raise ValueError("At least one TOU period must be provided")

        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl/tou/rd"

        reservation_use = 1 if enabled else 2
        reservation_payload = [dict(period) for period in periods]

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_TOU_SETTINGS,
            additional_value=additional_value,
            controllerSerialNumber=controller_serial_number,
            reservationUse=reservation_use,
            reservation=reservation_payload,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = f"cmd/{device_type}/{self.config.client_id}/res/tou/rd"

        return await self.publish(topic, command)

    async def request_tou_settings(
        self,
        device: Device,
        controller_serial_number: str,
    ) -> int:
        """Request current Time-of-Use schedule from the device."""
        if not controller_serial_number:
            raise ValueError("controller_serial_number is required")

        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl/tou/rd"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_TOU_SETTINGS,
            additional_value=additional_value,
            controllerSerialNumber=controller_serial_number,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = f"cmd/{device_type}/{self.config.client_id}/res/tou/rd"

        return await self.publish(topic, command)

    async def set_tou_enabled(self, device: Device, enabled: bool) -> int:
        """Quickly toggle Time-of-Use functionality without modifying the schedule."""
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command_code = CMD_TOU_ENABLE if enabled else CMD_TOU_DISABLE
        mode = "tou-on" if enabled else "tou-off"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=command_code,
            additional_value=additional_value,
            mode=mode,
            param=[],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self.publish(topic, command)

    async def request_energy_usage(self, device: Device, year: int, months: list[int]) -> int:
        """
        Request daily energy usage data for specified month(s).

        This retrieves historical energy usage data showing heat pump and
        electric heating element consumption broken down by day. The response
        includes both energy usage (Wh) and operating time (hours) for each
        component.

        Args:
            device: Device object
            year: Year to query (e.g., 2025)
            months: List of months to query (1-12). Can request multiple months.

        Returns:
            Publish packet ID

        Example::

            # Request energy usage for September 2025
            await mqtt_client.request_energy_usage(
                device,
                year=2025,
                months=[9]
            )

            # Request multiple months
            await mqtt_client.request_energy_usage(
                device,
                year=2025,
                months=[7, 8, 9]
            )
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value

        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/st/energy-usage-daily-query/rd"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CMD_ENERGY_USAGE_QUERY,  # Energy usage query command
            additional_value=additional_value,
            month=months,
            year=year,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = (
            f"cmd/{device_type}/{self.config.client_id}/res/energy-usage-daily-query/rd"
        )

        return await self.publish(topic, command)

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
            callback: Callback function that receives EnergyUsageResponse objects

        Returns:
            Subscription packet ID

        Example:
            >>> def on_energy_usage(energy: EnergyUsageResponse):
            ...     print(f"Total Usage: {energy.total.total_usage} Wh")
            ...     print(f"Heat Pump: {energy.total.heat_pump_percentage:.1f}%")
            ...     print(f"Electric: {energy.total.heat_element_percentage:.1f}%")
            >>>
            >>> await mqtt_client.subscribe_energy_usage(device, on_energy_usage)
            >>> await mqtt_client.request_energy_usage(device, 2025, [9])
        """

        device_type = device.device_info.device_type

        def energy_message_handler(topic: str, message: dict):
            """Internal handler to parse energy usage responses."""
            try:
                _logger.debug("Energy handler received message on topic: %s", topic)
                _logger.debug("Message keys: %s", list(message.keys()))

                if "response" not in message:
                    _logger.debug(
                        "Message does not contain 'response' key, skipping. Keys: %s",
                        list(message.keys()),
                    )
                    return

                response_data = message["response"]
                _logger.debug("Response keys: %s", list(response_data.keys()))

                if "typeOfUsage" not in response_data:
                    _logger.debug(
                        "Response does not contain 'typeOfUsage' key, skipping. Keys: %s",
                        list(response_data.keys()),
                    )
                    return

                _logger.info("Parsing energy usage response from topic: %s", topic)
                energy_response = EnergyUsageResponse.from_dict(response_data)

                _logger.info("Invoking user callback with parsed EnergyUsageResponse")
                callback(energy_response)
                _logger.debug("User callback completed successfully")

            except KeyError as e:
                _logger.warning("Failed to parse energy usage message - missing key: %s", e)
            except Exception as e:
                _logger.error("Error in energy usage message handler: %s", e, exc_info=True)

        response_topic = (
            f"cmd/{device_type}/{self.config.client_id}/res/energy-usage-daily-query/rd"
        )

        return await self.subscribe(response_topic, energy_message_handler)

    async def signal_app_connection(self, device: Device) -> int:
        """
        Signal that the app has connected.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        device_topic = f"navilink-{device_id}"
        topic = f"evt/{device_type}/{device_topic}/app-connection"
        message = {
            "clientID": self.config.client_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        return await self.publish(topic, message)

    async def start_periodic_requests(
        self,
        device: Device,
        request_type: PeriodicRequestType = PeriodicRequestType.DEVICE_STATUS,
        period_seconds: float = 300.0,
    ) -> None:
        """
        Start sending periodic requests for device information or status.

        This optional helper continuously sends requests at a specified interval.
        It can be used to keep device information or status up-to-date.

        Args:
            device: Device object
            request_type: Type of request (DEVICE_INFO or DEVICE_STATUS)
            period_seconds: Time between requests in seconds (default: 300 = 5 minutes)

        Example:
            >>> # Start periodic status requests (default)
            >>> await mqtt_client.start_periodic_requests(device)
            >>>
            >>> # Start periodic device info requests
            >>> await mqtt_client.start_periodic_requests(
            ...     device,
            ...     request_type=PeriodicRequestType.DEVICE_INFO
            ... )
            >>>
            >>> # Custom period: request every 60 seconds
            >>> await mqtt_client.start_periodic_requests(
            ...     device,
            ...     period_seconds=60
            ... )

        Note:
            - Only one periodic task per request type per device
            - Call stop_periodic_requests() to stop a task
            - All tasks automatically stop when client disconnects
        """
        device_id = device.device_info.mac_address
        # Do not log MAC address; use a generic placeholder to avoid leaking sensitive information
        redacted_device_id = "DEVICE_ID_REDACTED"
        task_name = f"periodic_{request_type.value}_{device_id}"

        # Stop existing task for this device/type if any
        if task_name in self._periodic_tasks:
            _logger.info(f"Stopping existing periodic {request_type.value} task")
            await self.stop_periodic_requests(device, request_type)

        async def periodic_request():
            """Internal coroutine for periodic requests."""
            _logger.info(
                f"Started periodic {request_type.value} requests for {redacted_device_id} "
                f"(every {period_seconds}s)"
            )

            # Track consecutive skips for throttled logging
            consecutive_skips = 0

            while True:
                try:
                    if not self._connected:
                        consecutive_skips += 1
                        # Log warning only on first skip and then every 10th skip to reduce noise
                        if consecutive_skips == 1 or consecutive_skips % 10 == 0:
                            _logger.warning(
                                "Not connected, skipping %s request for %s (skipped %d time%s)",
                                request_type.value,
                                redacted_device_id,
                                consecutive_skips,
                                "s" if consecutive_skips > 1 else "",
                            )
                        else:
                            _logger.debug(
                                "Not connected, skipping %s request for %s",
                                request_type.value,
                                redacted_device_id,
                            )
                    else:
                        # Reset skip counter when connected
                        if consecutive_skips > 0:
                            _logger.info(
                                "Reconnected, resuming %s requests for %s (had skipped %d)",
                                request_type.value,
                                redacted_device_id,
                                consecutive_skips,
                            )
                            consecutive_skips = 0

                        # Send appropriate request type
                        if request_type == PeriodicRequestType.DEVICE_INFO:
                            await self.request_device_info(device)
                        elif request_type == PeriodicRequestType.DEVICE_STATUS:
                            await self.request_device_status(device)

                        _logger.debug(
                            "Sent periodic %s request for %s",
                            request_type.value,
                            redacted_device_id,
                        )

                    # Wait for the specified period
                    await asyncio.sleep(period_seconds)

                except asyncio.CancelledError:
                    _logger.info(
                        f"Periodic {request_type.value} requests cancelled for {redacted_device_id}"
                    )
                    break
                except Exception as e:
                    # Handle clean session cancellation gracefully (expected during reconnection)
                    # Check exception type and name attribute for proper error identification
                    if (
                        isinstance(e, AwsCrtError)
                        and e.name == "AWS_ERROR_MQTT_CANCELLED_FOR_CLEAN_SESSION"
                    ):
                        _logger.debug(
                            "Periodic %s request cancelled due to clean session for %s. "
                            "This is expected during reconnection.",
                            request_type.value,
                            redacted_device_id,
                        )
                    else:
                        _logger.error(
                            "Error in periodic %s request for %s: %s",
                            request_type.value,
                            redacted_device_id,
                            e,
                            exc_info=True,
                        )
                    # Continue despite errors
                    await asyncio.sleep(period_seconds)

        # Create and store the task
        task = asyncio.create_task(periodic_request())
        self._periodic_tasks[task_name] = task

        _logger.info(
            f"Started periodic {request_type.value} task for {redacted_device_id} "
            f"with period {period_seconds}s"
        )

    async def stop_periodic_requests(
        self,
        device: Device,
        request_type: Optional[PeriodicRequestType] = None,
    ) -> None:
        """
        Stop sending periodic requests for a device.

        Args:
            device: Device object
            request_type: Type of request to stop. If None, stops all types
                          for this device.

        Example:
            >>> # Stop specific request type
            >>> await mqtt_client.stop_periodic_requests(
            ...     device,
            ...     PeriodicRequestType.DEVICE_STATUS
            ... )
            >>>
            >>> # Stop all periodic requests for device
            >>> await mqtt_client.stop_periodic_requests(device)
        """
        device_id = device.device_info.mac_address

        if request_type is None:
            # Stop all request types for this device
            types_to_stop = [
                PeriodicRequestType.DEVICE_INFO,
                PeriodicRequestType.DEVICE_STATUS,
            ]
        else:
            types_to_stop = [request_type]

        stopped_count = 0
        for req_type in types_to_stop:
            task_name = f"periodic_{req_type.value}_{device_id}"

            if task_name in self._periodic_tasks:
                task = self._periodic_tasks[task_name]
                task.cancel()

                with contextlib.suppress(asyncio.CancelledError):
                    await task

                del self._periodic_tasks[task_name]
                stopped_count += 1
                # Redact all but last 4 chars of MAC (if format expected), else just redact

        if stopped_count == 0:
            _logger.debug(
                f"No periodic tasks found for {device_id}"
                + (f" (type={request_type.value})" if request_type else "")
            )

    async def _stop_all_periodic_tasks(self) -> None:
        """
        Stop all periodic tasks.

        This is called internally when reconnection fails permanently
        to reduce log noise from tasks trying to send requests while disconnected.
        """
        # Delegate to public method with specific reason
        await self.stop_all_periodic_tasks(_reason="connection failure")

    # Convenience methods
    async def start_periodic_device_info_requests(
        self, device: Device, period_seconds: float = 300.0
    ) -> None:
        """
        Start sending periodic device info requests.

        This is a convenience wrapper around start_periodic_requests().

        Args:
            device: Device object
            period_seconds: Time between requests in seconds (default: 300 = 5 minutes)
        """
        await self.start_periodic_requests(
            device=device,
            request_type=PeriodicRequestType.DEVICE_INFO,
            period_seconds=period_seconds,
        )

    async def start_periodic_device_status_requests(
        self, device: Device, period_seconds: float = 300.0
    ) -> None:
        """
        Start sending periodic device status requests.

        This is a convenience wrapper around start_periodic_requests().

        Args:
            device: Device object
            period_seconds: Time between requests in seconds (default: 300 = 5 minutes)
        """
        await self.start_periodic_requests(
            device=device,
            request_type=PeriodicRequestType.DEVICE_STATUS,
            period_seconds=period_seconds,
        )

    async def stop_periodic_device_info_requests(self, device: Device) -> None:
        """
        Stop sending periodic device info requests for a device.

        This is a convenience wrapper around stop_periodic_requests().

        Args:
            device: Device object
        """
        await self.stop_periodic_requests(device, PeriodicRequestType.DEVICE_INFO)

    async def stop_periodic_device_status_requests(self, device: Device) -> None:
        """
        Stop sending periodic device status requests for a device.

        This is a convenience wrapper around stop_periodic_requests().

        Args:
            device: Device object
        """
        await self.stop_periodic_requests(device, PeriodicRequestType.DEVICE_STATUS)

    async def stop_all_periodic_tasks(self, _reason: Optional[str] = None) -> None:
        """
        Stop all periodic request tasks.

        This is automatically called when disconnecting.

        Args:
            _reason: Internal parameter for logging context (e.g., "connection failure")

        Example:
            >>> await mqtt_client.stop_all_periodic_tasks()
        """
        if not self._periodic_tasks:
            return

        task_count = len(self._periodic_tasks)
        reason_msg = f" due to {_reason}" if _reason else ""
        _logger.info(f"Stopping {task_count} periodic task(s){reason_msg}")

        # Cancel all tasks
        for task in self._periodic_tasks.values():
            task.cancel()

        # Wait for all to complete
        await asyncio.gather(*self._periodic_tasks.values(), return_exceptions=True)

        self._periodic_tasks.clear()
        _logger.info("All periodic tasks stopped")

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    @property
    def is_reconnecting(self) -> bool:
        """Check if client is currently attempting to reconnect."""
        return self._reconnect_task is not None and not self._reconnect_task.done()

    @property
    def reconnect_attempts(self) -> int:
        """Get the number of reconnection attempts made."""
        return self._reconnect_attempts

    @property
    def queued_commands_count(self) -> int:
        """Get the number of commands currently queued."""
        return len(self._command_queue)

    @property
    def client_id(self) -> str:
        """Get client ID."""
        return self.config.client_id

    @property
    def session_id(self) -> str:
        """Get session ID."""
        return self._session_id

    def clear_command_queue(self) -> int:
        """
        Clear all queued commands.

        Returns:
            Number of commands that were cleared
        """
        count = len(self._command_queue)
        if count > 0:
            self._command_queue.clear()
            _logger.info(f"Cleared {count} queued command(s)")
        return count

    async def reset_reconnect(self) -> None:
        """
        Reset reconnection state and trigger a new reconnection attempt.

        This method resets the reconnection attempt counter and initiates
        a new reconnection cycle. Useful for implementing custom recovery
        logic after max reconnection attempts have been exhausted.

        Example:
            >>> # In a reconnection_failed event handler
            >>> await mqtt_client.reset_reconnect()

        Note:
            This should typically only be called after a reconnection_failed
            event, not during normal operation.
        """
        self._reconnect_attempts = 0
        self._manual_disconnect = False
        await self._start_reconnect_task()
        count = len(self._command_queue)
        if count > 0:
            self._command_queue.clear()
            _logger.info(f"Cleared {count} queued command(s)")
        return count
