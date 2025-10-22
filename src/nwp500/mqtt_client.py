"""
MQTT Client for Navien Smart Control.

This module provides an MQTT client for real-time communication with Navien
devices using AWS IoT Core. It handles connection, subscriptions, and message
publishing for device control and monitoring.

The client uses WebSocket connections with AWS credentials obtained from
the authentication flow.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Sequence
from typing import Any, Callable, Optional

from awscrt import mqtt
from awscrt.exceptions import AwsCrtError

from .auth import NavienAuthClient
from .events import EventEmitter
from .models import (
    Device,
    DeviceFeature,
    DeviceStatus,
    EnergyUsageResponse,
)
from .mqtt_command_queue import MqttCommandQueue
from .mqtt_connection import MqttConnection
from .mqtt_device_control import MqttDeviceController
from .mqtt_periodic import MqttPeriodicRequestManager
from .mqtt_reconnection import MqttReconnectionHandler
from .mqtt_subscriptions import MqttSubscriptionManager
from .mqtt_utils import (
    MqttConnectionConfig,
    PeriodicRequestType,
)

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


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
        - connection_resumed: Connection restored (return_code,
          session_present)
        - reconnection_failed: Reconnection permanently failed after max
          attempts (attempt_count)
    """

    def __init__(
        self,
        auth_client: NavienAuthClient,
        config: Optional[MqttConnectionConfig] = None,
        on_connection_interrupted: Optional[Callable[[Exception], None]] = None,
        on_connection_resumed: Optional[Callable[[Any, Any], None]] = None,
    ):
        """
        Initialize the MQTT client.

        Args:
            auth_client: Authentication client with valid tokens
            config: Optional connection configuration
            on_connection_interrupted: Callback for connection interruption
            on_connection_resumed: Callback for connection resumption

        Raises:
            ValueError: If auth client is not authenticated or AWS
                credentials are not available
        """
        if not auth_client.is_authenticated:
            raise ValueError(
                "Authentication client must be authenticated before "
                "creating MQTT client. Call auth_client.sign_in() first."
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

        # Session tracking
        self._session_id = uuid.uuid4().hex

        # Store event loop reference for thread-safe coroutine scheduling
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Initialize specialized components
        # Command queue (independent, can be created immediately)
        self._command_queue = MqttCommandQueue(config=self.config)

        # Components that depend on connection (initialized in connect())
        self._connection_manager: Optional[MqttConnection] = None
        self._reconnection_handler: Optional[MqttReconnectionHandler] = None
        self._subscription_manager: Optional[MqttSubscriptionManager] = None
        self._device_controller: Optional[MqttDeviceController] = None
        self._reconnect_task: Optional[asyncio.Task[None]] = None
        self._periodic_manager: Optional[MqttPeriodicRequestManager] = None

        # Legacy state (kept for backward compatibility during transition)
        self._connection: Optional[mqtt.Connection] = None
        self._connected = False

        # User-provided callbacks
        self._on_connection_interrupted = on_connection_interrupted
        self._on_connection_resumed = on_connection_resumed

        _logger.info(
            f"Initialized MQTT client with ID: {self.config.client_id}"
        )

    def _schedule_coroutine(self, coro: Any) -> None:
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

    def _on_connection_interrupted_internal(
        self, connection: mqtt.Connection, error: AwsCrtError, **kwargs: Any
    ) -> None:
        """Internal handler for connection interruption.

        Args:
            connection: MQTT connection that was interrupted
            error: Error that caused the interruption
            **kwargs: Forward-compatibility kwargs from AWS SDK
        """
        _logger.warning(f"Connection interrupted: {error}")
        self._connected = False

        # Emit event
        self._schedule_coroutine(self.emit("connection_interrupted", error))

        # Call user callback if provided
        if self._on_connection_interrupted:
            try:
                self._on_connection_interrupted(error)
            except TypeError:
                # Fallback for callbacks expecting no arguments
                try:
                    self._on_connection_interrupted()  # type: ignore
                except Exception as e:
                    _logger.error(
                        f"Error in connection_interrupted callback: {e}"
                    )

        # Delegate to reconnection handler if available
        if self._reconnection_handler and self.config.auto_reconnect:
            self._reconnection_handler.on_connection_interrupted(error)

    def _on_connection_resumed_internal(
        self, return_code: Any, session_present: Any
    ) -> None:
        """Internal handler for connection resumption."""
        _logger.info(
            f"Connection resumed: return_code={return_code}, "
            f"session_present={session_present}"
        )
        self._connected = True

        # Emit event
        self._schedule_coroutine(
            self.emit("connection_resumed", return_code, session_present)
        )

        # Call user callback
        if self._on_connection_resumed:
            self._on_connection_resumed(return_code, session_present)

        # Delegate to reconnection handler to reset state
        if self._reconnection_handler:
            self._reconnection_handler.on_connection_resumed(
                return_code, session_present
            )

        # Send any queued commands
        if self.config.enable_command_queue and self._command_queue:
            self._schedule_coroutine(self._send_queued_commands_internal())

    async def _send_queued_commands_internal(self) -> None:
        """Send all queued commands using the command queue component."""
        if not self._command_queue or not self._connection_manager:
            return

        await self._command_queue.send_all(
            self._connection_manager.publish, lambda: self._connected
        )

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

        # Ensure we have valid tokens before connecting
        await self._auth_client.ensure_valid_token()

        _logger.info(f"Connecting to AWS IoT endpoint: {self.config.endpoint}")
        _logger.debug(f"Client ID: {self.config.client_id}")
        _logger.debug(f"Region: {self.config.region}")

        try:
            # Initialize connection manager with internal callbacks
            self._connection_manager = MqttConnection(
                config=self.config,
                auth_client=self._auth_client,
                on_connection_interrupted=self._on_connection_interrupted_internal,
                on_connection_resumed=self._on_connection_resumed_internal,
            )

            # Delegate connection to connection manager
            success = await self._connection_manager.connect()

            if success:
                # Update legacy state for backward compatibility
                self._connection = self._connection_manager.connection
                self._connected = True

                # Initialize reconnection handler
                self._reconnection_handler = MqttReconnectionHandler(
                    config=self.config,
                    is_connected_func=lambda: self._connected,
                    schedule_coroutine_func=self._schedule_coroutine,
                )
                self._reconnection_handler.enable()

                # Initialize subscription manager
                client_id = self.config.client_id or ""
                self._subscription_manager = MqttSubscriptionManager(
                    connection=self._connection,
                    client_id=client_id,
                    event_emitter=self,
                    schedule_coroutine=self._schedule_coroutine,
                )

                # Initialize device controller
                self._device_controller = MqttDeviceController(
                    client_id=client_id,
                    session_id=self._session_id,
                    publish_func=self._connection_manager.publish,
                )

                # Initialize periodic request manager
                # Note: These will be implemented later when we
                # delegate device control methods
                self._periodic_manager = MqttPeriodicRequestManager(
                    is_connected_func=lambda: self._connected,
                    request_device_info_func=self._device_controller.request_device_info,
                    request_device_status_func=self._device_controller.request_device_status,
                )

                _logger.info("All components initialized successfully")
                return True

            return False

        except Exception as e:
            _logger.error(f"Failed to connect: {e}")
            raise

    def _create_credentials_provider(self) -> Any:
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

    async def disconnect(self) -> None:
        """Disconnect from AWS IoT Core and stop all periodic tasks."""
        if not self._connected or not self._connection_manager:
            _logger.warning("Not connected")
            return

        _logger.info("Disconnecting from AWS IoT...")

        # Disable automatic reconnection
        if self._reconnection_handler:
            self._reconnection_handler.disable()
            await self._reconnection_handler.cancel()

        # Stop all periodic tasks first
        if self._periodic_manager:
            await self._periodic_manager.stop_all_periodic_tasks()

        try:
            # Delegate disconnection to connection manager
            await self._connection_manager.disconnect()

            # Update legacy state
            self._connected = False
            self._connection = None

            _logger.info("Disconnected successfully")
        except Exception as e:
            _logger.error(f"Error during disconnect: {e}")
            raise

    def _on_message_received(
        self, topic: str, payload: bytes, **kwargs: Any
    ) -> None:
        """Internal callback for received messages."""
        try:
            # Parse JSON payload and delegate to subscription manager
            _logger.debug("Received message on topic: %s", topic)

            # Call registered handlers via subscription manager
            if self._subscription_manager:
                # The subscription manager will handle matching
                # and calling handlers
                pass  # Subscription manager handles this internally

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
            Exception: If subscription fails
        """
        if not self._connected or not self._subscription_manager:
            raise RuntimeError("Not connected to MQTT broker")

        # Delegate to subscription manager
        return await self._subscription_manager.subscribe(topic, callback, qos)

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
        if not self._connected or not self._subscription_manager:
            raise RuntimeError("Not connected to MQTT broker")

        # Delegate to subscription manager
        return await self._subscription_manager.unsubscribe(topic)

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
                _logger.debug(
                    f"Not connected, queuing command to topic: {topic}"
                )
                self._command_queue.enqueue(topic, payload, qos)
                return 0  # Return 0 to indicate command was queued
            else:
                raise RuntimeError("Not connected to MQTT broker")

        # Delegate to connection manager
        if not self._connection_manager:
            raise RuntimeError("Connection manager not initialized")

        try:
            return await self._connection_manager.publish(topic, payload, qos)
        except Exception as e:
            # Handle clean session cancellation gracefully
            # Check exception type and name attribute for proper
            # error identification
            if (
                isinstance(e, AwsCrtError)
                and e.name == "AWS_ERROR_MQTT_CANCELLED_FOR_CLEAN_SESSION"
            ):
                _logger.warning(
                    "Publish cancelled due to clean session. This is "
                    "expected during reconnection."
                )
                # Queue the command if queue is enabled
                if self.config.enable_command_queue:
                    _logger.debug(
                        "Queuing command due to clean session cancellation"
                    )
                    self._command_queue.enqueue(topic, payload, qos)
                    return 0  # Return 0 to indicate command was queued
                # Otherwise, raise an error so the caller can handle the failure
                raise RuntimeError(
                    "Publish cancelled due to clean session and "
                    "command queue is disabled"
                )

            # Note: redact_topic is already used elsewhere in the file
            _logger.error(f"Failed to publish to topic: {e}")
            raise

    # Navien-specific convenience methods

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
        if not self._connected or not self._subscription_manager:
            raise RuntimeError("Not connected to MQTT broker")

        # Delegate to subscription manager
        return await self._subscription_manager.subscribe_device(
            device, callback
        )

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
            >>> mqtt_client.on(
            ...     'heating_stopped', lambda s: print("Heating OFF")
            ... )
            >>>
            >>> # Subscribe to start receiving events
            >>> await mqtt_client.subscribe_device_status(
            ...     device, lambda s: None
            ... )
        """
        if not self._connected or not self._subscription_manager:
            raise RuntimeError("Not connected to MQTT broker")

        # Delegate to subscription manager (it handles state change
        # detection and events)
        return await self._subscription_manager.subscribe_device_status(
            device, callback
        )

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
            ...     print(
            ...         f"Temp Range: {feature.dhwTemperatureMin}-"
            ...         f"{feature.dhwTemperatureMax}°F"
            ...     )
            >>>
            >>> await mqtt_client.subscribe_device_feature(device, on_feature)

            >>> # Or use event emitter
            >>> mqtt_client.on(
            ...     'feature_received',
            ...     lambda f: print(f"FW: {f.controllerSwVersion}")
            ... )
            >>> await mqtt_client.subscribe_device_feature(
            ...     device, lambda f: None
            ... )
        """
        if not self._connected or not self._subscription_manager:
            raise RuntimeError("Not connected to MQTT broker")

        # Delegate to subscription manager
        return await self._subscription_manager.subscribe_device_feature(
            device, callback
        )

    async def request_device_status(self, device: Device) -> int:
        """
        Request general device status.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.request_device_status(device)

    async def request_device_info(self, device: Device) -> int:
        """
        Request device information.

        Returns:
            Publish packet ID
        """
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.request_device_info(device)

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
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.set_power(device, power_on)

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
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.set_dhw_mode(
            device, mode_id, vacation_days
        )

    async def enable_anti_legionella(
        self, device: Device, period_days: int
    ) -> int:
        """Enable Anti-Legionella disinfection with a 1-30 day cycle.

        This command has been confirmed through HAR analysis of the
        official Navien app.
        When sent, the device responds with antiLegionellaUse=2 (enabled) and
        antiLegionellaPeriod set to the specified value.

        See docs/MQTT_MESSAGES.rst "Anti-Legionella Control" for the
        authoritative
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
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.enable_anti_legionella(
            device, period_days
        )

    async def disable_anti_legionella(self, device: Device) -> int:
        """Disable the Anti-Legionella disinfection cycle.

        This command has been confirmed through HAR analysis of the
        official Navien app.
        When sent, the device responds with antiLegionellaUse=1 (disabled) while
        antiLegionellaPeriod retains its previous value.

        The correct command code is 33554471 (not 33554473 as
        previously assumed).

        See docs/MQTT_MESSAGES.rst "Anti-Legionella Control" section
        for details.

        Returns:
            The message ID of the published command
        """
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.disable_anti_legionella(device)

    async def set_dhw_temperature(
        self, device: Device, temperature: int
    ) -> int:
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
            temperature: Target temperature in Fahrenheit (message
                value, NOT display value)

        Returns:
            Publish packet ID

        Example:
            # To set display temperature to 140°F, send 120°F
            await client.set_dhw_temperature(device, 120)
        """
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.set_dhw_temperature(
            device, temperature
        )

    async def set_dhw_temperature_display(
        self, device: Device, display_temperature: int
    ) -> int:
        """
        Set DHW target temperature using the DISPLAY value (what you
        see on device/app).

        This is a convenience method that automatically converts
        display temperature
        to the message value by subtracting 20 degrees.

        Args:
            device: Device object
            display_temperature: Target temperature as shown on
                display/app (Fahrenheit)

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
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.update_reservations(
            device, reservations, enabled=enabled
        )

    async def request_reservations(self, device: Device) -> int:
        """Request the current reservation program from the device."""
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.request_reservations(device)

    async def configure_tou_schedule(
        self,
        device: Device,
        controller_serial_number: str,
        periods: Sequence[dict[str, Any]],
        *,
        enabled: bool = True,
    ) -> int:
        """Configure Time-of-Use pricing schedule via MQTT."""
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.configure_tou_schedule(
            device, controller_serial_number, periods, enabled=enabled
        )

    async def request_tou_settings(
        self,
        device: Device,
        controller_serial_number: str,
    ) -> int:
        """Request current Time-of-Use schedule from the device."""
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.request_tou_settings(
            device, controller_serial_number
        )

    async def set_tou_enabled(self, device: Device, enabled: bool) -> int:
        """Quickly toggle Time-of-Use functionality without
        modifying the schedule."""
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.set_tou_enabled(device, enabled)

    async def request_energy_usage(
        self, device: Device, year: int, months: list[int]
    ) -> int:
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
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.request_energy_usage(
            device, year, months
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
            callback: Callback function that receives
                EnergyUsageResponse objects

        Returns:
            Subscription packet ID

        Example:
            >>> def on_energy_usage(energy: EnergyUsageResponse):
            ...     print(f"Total Usage: {energy.total.total_usage} Wh")
            ...     print(
            ...         f"Heat Pump: "
            ...         f"{energy.total.heat_pump_percentage:.1f}%"
            ...     )
            ...     print(
            ...         f"Electric: "
            ...         f"{energy.total.heat_element_percentage:.1f}%"
            ...     )
            >>>
            >>> await mqtt_client.subscribe_energy_usage(
            ...     device, on_energy_usage
            ... )
            >>> await mqtt_client.request_energy_usage(device, 2025, [9])
        """
        if not self._connected or not self._subscription_manager:
            raise RuntimeError("Not connected to MQTT broker")

        # Delegate to subscription manager
        return await self._subscription_manager.subscribe_energy_usage(
            device, callback
        )

    async def signal_app_connection(self, device: Device) -> int:
        """
        Signal that the app has connected.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        if not self._connected or not self._device_controller:
            raise RuntimeError("Not connected to MQTT broker")

        return await self._device_controller.signal_app_connection(device)

    async def start_periodic_requests(
        self,
        device: Device,
        request_type: PeriodicRequestType = PeriodicRequestType.DEVICE_STATUS,
        period_seconds: float = 300.0,
    ) -> None:
        """
        Start sending periodic requests for device information or status.

        This optional helper continuously sends requests at a
        specified interval.
        It can be used to keep device information or status up-to-date.

        Args:
            device: Device object
            request_type: Type of request (DEVICE_INFO or DEVICE_STATUS)
            period_seconds: Time between requests in seconds
                (default: 300 = 5 minutes)

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
        if not self._periodic_manager:
            raise RuntimeError("Periodic request manager not initialized")

        await self._periodic_manager.start_periodic_requests(
            device, request_type, period_seconds
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
        if not self._periodic_manager:
            raise RuntimeError("Periodic request manager not initialized")

        await self._periodic_manager.stop_periodic_requests(
            device, request_type
        )

    async def _stop_all_periodic_tasks(self) -> None:
        """
        Stop all periodic tasks.

        This is called internally when reconnection fails permanently
        to reduce log noise from tasks trying to send requests while
        disconnected.
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
            period_seconds: Time between requests in seconds
                (default: 300 = 5 minutes)
        """
        if not self._periodic_manager:
            raise RuntimeError("Periodic request manager not initialized")

        await self._periodic_manager.start_periodic_device_info_requests(
            device, period_seconds
        )

    async def start_periodic_device_status_requests(
        self, device: Device, period_seconds: float = 300.0
    ) -> None:
        """
        Start sending periodic device status requests.

        This is a convenience wrapper around start_periodic_requests().

        Args:
            device: Device object
            period_seconds: Time between requests in seconds
                (default: 300 = 5 minutes)
        """
        if not self._periodic_manager:
            raise RuntimeError("Periodic request manager not initialized")

        await self._periodic_manager.start_periodic_device_status_requests(
            device, period_seconds
        )

    async def stop_periodic_device_info_requests(self, device: Device) -> None:
        """
        Stop sending periodic device info requests for a device.

        This is a convenience wrapper around stop_periodic_requests().

        Args:
            device: Device object
        """
        if not self._periodic_manager:
            raise RuntimeError("Periodic request manager not initialized")

        await self._periodic_manager.stop_periodic_device_info_requests(device)

    async def stop_periodic_device_status_requests(
        self, device: Device
    ) -> None:
        """
        Stop sending periodic device status requests for a device.

        This is a convenience wrapper around stop_periodic_requests().

        Args:
            device: Device object
        """
        if not self._periodic_manager:
            raise RuntimeError("Periodic request manager not initialized")

        await self._periodic_manager.stop_periodic_device_status_requests(
            device
        )

    async def stop_all_periodic_tasks(
        self, _reason: Optional[str] = None
    ) -> None:
        """
        Stop all periodic request tasks.

        This is automatically called when disconnecting.

        Args:
            _reason: Internal parameter for logging context
                (e.g., "connection failure")

        Example:
            >>> await mqtt_client.stop_all_periodic_tasks()
        """
        if not self._periodic_manager:
            raise RuntimeError("Periodic request manager not initialized")

        await self._periodic_manager.stop_all_periodic_tasks(_reason)

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    @property
    def is_reconnecting(self) -> bool:
        """Check if client is currently attempting to reconnect."""
        if self._reconnection_handler:
            return self._reconnection_handler.is_reconnecting
        return False

    @property
    def reconnect_attempts(self) -> int:
        """Get the number of reconnection attempts made."""
        if self._reconnection_handler:
            return self._reconnection_handler.attempt_count
        return 0

    @property
    def queued_commands_count(self) -> int:
        """Get the number of commands currently queued."""
        if self._command_queue:
            return self._command_queue.count
        return 0

    @property
    def client_id(self) -> str:
        """Get client ID."""
        return self.config.client_id or ""

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
        if self._command_queue:
            count = self._command_queue.count
            if count > 0:
                self._command_queue.clear()
                _logger.info(f"Cleared {count} queued command(s)")
                return count
        return 0

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
        if self._reconnection_handler:
            self._reconnection_handler.reset()
