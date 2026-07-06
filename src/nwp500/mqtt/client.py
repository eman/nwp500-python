"""
MQTT Client for Navien Smart Control.

This module provides an MQTT client for real-time communication with Navien
devices using AWS IoT Core. It handles connection, subscriptions, and message
publishing for device control and monitoring.

The client uses WebSocket connections with AWS credentials obtained from
the authentication flow.
"""

import asyncio
import concurrent.futures
import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from awscrt.exceptions import AwsCrtError

from ..auth import NavienAuthClient
from ..events import EventEmitter
from ..exceptions import (
    AuthenticationError,
    MqttConnectionError,
    MqttCredentialsError,
    MqttNotConnectedError,
    MqttPublishError,
    TokenRefreshError,
)
from ..mqtt_events import (
    ConnectionInterruptedEvent,
    ConnectionResumedEvent,
    MqttClientEvents,
)
from ..unit_system import UnitSystemType
from ._control_commands import DeviceControlCommandsMixin
from ._device_subscriptions import DeviceSubscriptionsMixin
from .command_queue import MqttCommandQueue
from .connection import MqttConnection
from .control import MqttDeviceController
from .diagnostics import MqttDiagnosticsCollector
from .periodic import MqttPeriodicRequestManager
from .reconnection import MqttReconnectionHandler
from .subscriptions import MqttSubscriptionManager
from .types import MqttConnectionHandle, QoS
from .utils import (
    MqttConnectionConfig,
    PeriodicRequestType,
)

if TYPE_CHECKING:
    from ..models import (
        Device,
        DeviceFeature,
    )

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


def _log_scheduled_coroutine_result(
    future: concurrent.futures.Future[Any],
) -> None:
    """Surface exceptions from scheduled coroutines.

    Attached to futures returned by ``run_coroutine_threadsafe``.
    Without this callback the returned future is discarded and any
    exception (e.g. resubscribe failure after a clean-session resume) is
    silently swallowed.
    """
    if future.cancelled():
        return
    exc = future.exception()
    if exc is not None:
        # Pass an explicit (type, value, traceback) tuple: a bare
        # exception instance is treated by logging as a truthy flag,
        # which would log the *current* exception context (empty in a
        # done-callback) instead of the coroutine's traceback.
        _logger.error(
            "Scheduled coroutine failed: %s",
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )


class NavienMqttClient(
    DeviceControlCommandsMixin, DeviceSubscriptionsMixin, EventEmitter
):
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

        >>> from nwp500.mqtt_events import MqttClientEvents
        >>> mqtt_client = NavienMqttClient(auth_client)
        ...
        ... # Type-safe event listeners with IDE autocomplete
        ... mqtt_client.on(
        ...     MqttClientEvents.TEMPERATURE_CHANGED,
        ...     lambda event: log_temperature(event.new_temperature),
        ... )
        ... mqtt_client.on(MqttClientEvents.TEMPERATURE_CHANGED, update_ui)
        ... mqtt_client.on(
        ...     MqttClientEvents.MODE_CHANGED, handle_mode_change
        ... )
        ...
        ... # One-time listener
        ... mqtt_client.once(MqttClientEvents.STATUS_RECEIVED, initialize)
        ...
        ... await mqtt_client.connect()

    Events Emitted:
        See :class:`nwp500.mqtt_events.MqttClientEvents` for a complete,
        type-safe registry of all events with full documentation.

        Key events include:
        - status_received: Raw status update
        - feature_received: Device feature/capability information
        - temperature_changed: DHW temperature changed
        - mode_changed: Operation mode changed
        - power_changed: Power consumption changed
        - heating_started: Device started heating
        - heating_stopped: Device stopped heating
        - error_detected: Device error occurred
        - error_cleared: Device error resolved
        - connection_interrupted: Connection lost
        - connection_resumed: Connection restored
    """

    def __init__(
        self,
        auth_client: NavienAuthClient,
        config: MqttConnectionConfig | None = None,
        unit_system: UnitSystemType = None,
    ):
        """
        Initialize the MQTT client.

        Args:
            auth_client: Authentication client with valid tokens
            config: Optional connection configuration
            unit_system: Preferred unit system:
                - "metric": Celsius, LPM, Liters
                - "us_customary": Fahrenheit, GPM, Gallons

                - None: Auto-detect from device (default)

        Raises:
            MqttCredentialsError: If auth client is not authenticated or AWS
                credentials are not available
        """
        if not auth_client.is_authenticated:
            raise MqttCredentialsError(
                "Authentication client must be authenticated before "
                "creating MQTT client. Call auth_client.sign_in() first."
            )

        # Token validity is checked in connect() which also refreshes stale
        # tokens automatically. This allows creating MQTT clients with
        # restored tokens that may have expired between sessions. Token
        # validation and refresh are deferred until connect() is called; if
        # connect() is never called, tokens are not revalidated/refreshed
        # and no MQTT connection is established.

        if not auth_client.current_tokens:
            raise MqttCredentialsError("No tokens available from auth client")

        auth_tokens = auth_client.current_tokens
        if not auth_tokens.access_key_id or not auth_tokens.secret_key:
            raise MqttCredentialsError(
                "AWS credentials not available in auth tokens. "
                "Ensure authentication provides AWS IoT credentials."
            )

        # Initialize EventEmitter
        super().__init__()

        self._auth_client = auth_client
        self._unit_system: UnitSystemType = unit_system
        self.config = config or MqttConnectionConfig()

        # Session tracking
        self._session_id = uuid.uuid4().hex

        # Store event loop reference for thread-safe coroutine scheduling
        self._loop: asyncio.AbstractEventLoop | None = None

        # Initialize specialized components
        # Command queue (independent, can be created immediately)
        self._command_queue = MqttCommandQueue(config=self.config)

        # Device controller (independent of connection status,
        # uses client.publish for queuing)
        self._device_controller = MqttDeviceController(
            client_id=self.config.client_id or "",
            session_id=self._session_id,
            publish_func=self.publish,
        )

        # Components that depend on connection (initialized in connect())
        self._connection_manager: MqttConnection | None = None
        self._reconnection_handler: MqttReconnectionHandler | None = None
        self._subscription_manager: MqttSubscriptionManager | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._periodic_manager: MqttPeriodicRequestManager | None = None

        # Diagnostics collector
        self._diagnostics = MqttDiagnosticsCollector()

        # Connection state (simpler than checking _connection_manager)
        self._connection: MqttConnectionHandle | None = None
        self._connected = False
        # Guards _active_reconnect / _deep_reconnect against re-entrancy.
        # While True, _on_connection_interrupted_internal will not forward
        # events to the reconnection handler, preventing the intentional
        # teardown of the old connection from spawning a competing backoff loop.
        self._actively_reconnecting = False

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
                # Close the never-scheduled coroutine to avoid a
                # "coroutine was never awaited" warning and release any
                # resources it holds.
                coro.close()
                return

        # Schedule the coroutine in the stored loop using thread-safe method
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError as e:
            # Event loop is closed or not running
            _logger.error(f"Failed to schedule coroutine: {e}", exc_info=True)
            coro.close()
        else:
            # Never drop the future: exceptions from scheduled coroutines
            # (e.g. a failed resubscribe after a clean-session resume) would
            # otherwise be stored on the discarded future and vanish.
            future.add_done_callback(_log_scheduled_coroutine_result)

    def _on_connection_interrupted_internal(
        self, connection: MqttConnectionHandle, error: Exception, **kwargs: Any
    ) -> None:
        """Internal handler for connection interruption.

        Args:
            connection: MQTT connection that was interrupted
            error: Error that caused the interruption
            **kwargs: Forward-compatibility kwargs from AWS SDK
        """
        self._connected = False

        # Emit event
        self._schedule_coroutine(
            self.emit(
                MqttClientEvents.CONNECTION_INTERRUPTED,
                ConnectionInterruptedEvent(error=error),
            )
        )

        # Delegate to reconnection handler if available.
        # Skip while _actively_reconnecting: the interruption was caused by
        # _active_reconnect / _deep_reconnect intentionally closing the old
        # connection.  Forwarding it would queue a _start_reconnect_task
        # coroutine that could fire after the new connection is up and the
        # existing backoff task has been cancelled, spawning a competing loop.
        if (
            self._reconnection_handler
            and self.config.auto_reconnect
            and not self._actively_reconnecting
        ):
            self._reconnection_handler.on_connection_interrupted(error)

        # Record diagnostic event
        active_subs = 0
        if self._subscription_manager:
            # Access subscription count for diagnostics
            active_subs = len(self._subscription_manager.subscriptions)

        # Record drop asynchronously
        self._schedule_coroutine(
            self._diagnostics.record_connection_drop(
                error=error,
                reconnect_attempt=(
                    self._reconnection_handler.attempt_count
                    if self._reconnection_handler
                    else 0
                ),
                active_subscriptions=active_subs,
                queued_commands=(
                    self._command_queue.count if self._command_queue else 0
                ),
            )
        )

    def _on_connection_resumed_internal(
        self,
        connection: MqttConnectionHandle,
        return_code: Any,
        session_present: Any,
        **kwargs: Any,
    ) -> None:
        """Internal handler for connection resumption.

        Args:
            connection: MQTT connection that was resumed
            return_code: MQTT return code from the resumed connection
            session_present: Whether the previous session was present
            **kwargs: Forward-compatibility kwargs from AWS SDK
        """
        _logger.info(
            f"Connection resumed: return_code={return_code}, "
            f"session_present={session_present}"
        )
        self._connected = True

        # Emit event
        self._schedule_coroutine(
            self.emit(
                MqttClientEvents.CONNECTION_RESUMED,
                ConnectionResumedEvent(
                    return_code=return_code,
                    session_present=session_present,
                ),
            )
        )

        # Delegate to reconnection handler to reset state
        if self._reconnection_handler:
            self._reconnection_handler.on_connection_resumed(
                return_code, session_present
            )

        # Record diagnostic event
        self._schedule_coroutine(
            self._diagnostics.record_connection_success(
                event_type="resumed",
                session_present=session_present,
                return_code=return_code,
                attempt_number=0,  # Reset on success
            )
        )

        # When the broker starts a clean session (session_present=False), all
        # previous subscriptions have been dropped server-side.  We must
        # re-establish them before any device data can flow.  This covers the
        # common case where the AWS IoT SDK auto-reconnects internally before
        # the MqttReconnectionHandler fires its own reconnect path — in that
        # scenario the reconnect handler sees _connected==True and exits early,
        # so resubscribe_all() would never be called without this block.
        #
        # When session_present=False, we must resubscribe before sending queued
        # commands to ensure subscriptions are restored before device responses
        # are processed. Use a composite coroutine to enforce ordering.
        if not session_present and self._subscription_manager:
            self._schedule_coroutine(self._handle_clean_session_resume())
        elif self.config.enable_command_queue and self._command_queue:
            self._schedule_coroutine(self._send_queued_commands_internal())

    async def _send_queued_commands_internal(self) -> None:
        """Send all queued commands using the command queue component."""
        if not self._command_queue or not self._connection_manager:
            return

        await self._command_queue.send_all(
            self._connection_manager.publish, lambda: self._connected
        )

    async def _handle_clean_session_resume(self) -> None:
        """
        Handle clean session reconnection with ordered resubscription.

        When session_present=False (clean session), the broker has dropped all
        subscriptions. This method ensures subscriptions are restored BEFORE
        sending any queued commands, preventing commands from being processed
        before their subscriptions are re-established.
        """
        if not self._subscription_manager or not self._connection_manager:
            return

        if not self._connection_manager.connection:
            return

        self._subscription_manager.update_connection(
            self._connection_manager.connection
        )
        await self._subscription_manager.resubscribe_all()

        if self.config.enable_command_queue and self._command_queue:
            await self._send_queued_commands_internal()

    async def _active_reconnect(self) -> None:
        """
        Actively trigger a reconnection attempt.

        This method is called by the reconnection handler to actively
        reconnect instead of passively waiting for AWS IoT SDK.

        Note: This creates a new connection while preserving subscriptions
        and configuration. The old connection is closed first to prevent
        its SDK auto-reconnect from creating a competing connection with
        the same client ID (which causes the broker to kick one off,
        leading to an infinite connect/disconnect loop).
        """
        if self._connected:
            _logger.debug("Already connected, skipping reconnection")
            return

        if self._actively_reconnecting:
            _logger.debug("Active reconnection already in progress, skipping")
            return

        _logger.info("Attempting active reconnection...")

        self._actively_reconnecting = True
        try:
            # Ensure tokens are still valid
            await self._auth_client.ensure_valid_token()

            # If we have a connection manager, try to reconnect using it
            if self._connection_manager:
                # Close old connection to stop SDK auto-reconnect and
                # prevent two connections with the same client ID.
                # _actively_reconnecting suppresses the
                # on_connection_interrupted callback that closing triggers,
                # preventing a competing backoff loop from being spawned.
                _logger.debug("Recreating MQTT connection...")
                try:
                    await self._connection_manager.close()
                except (AwsCrtError, RuntimeError) as e:
                    _logger.debug(f"Old connection cleanup (benign): {e}")

                # Create a new connection manager with same config
                self._connection_manager = MqttConnection(
                    config=self.config,
                    auth_client=self._auth_client,
                    on_connection_interrupted=self._on_connection_interrupted_internal,
                    on_connection_resumed=self._on_connection_resumed_internal,
                )

                # Try to connect
                success = await self._connection_manager.connect()

                if success:
                    # Update connection references
                    self._connection = self._connection_manager.connection
                    self._connected = True

                    # Update subscription manager with new connection
                    if self._subscription_manager and self._connection:
                        self._subscription_manager.update_connection(
                            self._connection
                        )
                        await self._subscription_manager.resubscribe_all()

                    # A brand-new connection never fires the SDK's
                    # on_connection_resumed callback, so queued commands
                    # must be flushed here or they would be lost.
                    if self.config.enable_command_queue and self._command_queue:
                        await self._send_queued_commands_internal()

                    _logger.info("Active reconnection successful")
                else:
                    _logger.warning("Active reconnection failed")
            else:
                _logger.warning(
                    "No connection manager available for reconnection"
                )

        except (AwsCrtError, AuthenticationError, RuntimeError) as e:
            _logger.error(
                f"Error during active reconnection: {e}", exc_info=True
            )
            raise
        finally:
            self._actively_reconnecting = False

    async def _deep_reconnect(self) -> None:
        """
        Perform a deep reconnection by completely rebuilding the connection.

        This method is called after multiple quick reconnection failures.
        It performs a full teardown and rebuild:
        - Disconnects existing connection
        - Refreshes authentication tokens
        - Creates new connection manager
        - Re-establishes all subscriptions

        This is more expensive but can recover from issues that a simple
        reconnection cannot fix (e.g., stale credentials, corrupted state).
        """
        if self._connected:
            _logger.debug("Already connected, skipping deep reconnection")
            return

        if self._actively_reconnecting:
            _logger.debug("Active reconnection already in progress, skipping")
            return

        _logger.warning(
            "Performing deep reconnection (full rebuild)... "
            "This may take longer."
        )

        self._actively_reconnecting = True
        try:
            # Step 1: Clean up existing connection if any.
            # _actively_reconnecting suppresses the on_connection_interrupted
            # callback that closing triggers, preventing a competing backoff
            # loop from being spawned.
            if self._connection_manager:
                _logger.debug("Cleaning up old connection...")
                try:
                    await self._connection_manager.close()
                except (AwsCrtError, RuntimeError) as e:
                    # Expected: connection already dead or in bad state
                    _logger.debug(f"Error during cleanup: {e} (expected)")

            # Step 2: Force token refresh to get fresh AWS credentials
            _logger.debug("Refreshing authentication tokens...")
            try:
                # Use the stored refresh token from current tokens
                current_tokens = self._auth_client.current_tokens
                if current_tokens and current_tokens.refresh_token:
                    await self._auth_client.refresh_token(
                        current_tokens.refresh_token
                    )
                else:
                    _logger.warning("No refresh token available")
                    raise MqttCredentialsError(
                        "No refresh token available for refresh"
                    )
            except (TokenRefreshError, ValueError, AuthenticationError) as e:
                # If refresh fails, try full re-authentication with stored
                # credentials
                if self._auth_client.has_stored_credentials:
                    _logger.warning(
                        f"Token refresh failed: {e}. Attempting full "
                        "re-authentication..."
                    )
                    await self._auth_client.re_authenticate()
                else:
                    _logger.error(
                        "Cannot re-authenticate: no stored credentials"
                    )
                    raise

            # Step 3: Create completely new connection manager
            _logger.debug("Creating new connection manager...")
            self._connection_manager = MqttConnection(
                config=self.config,
                auth_client=self._auth_client,
                on_connection_interrupted=self._on_connection_interrupted_internal,
                on_connection_resumed=self._on_connection_resumed_internal,
            )

            # Step 4: Attempt connection
            success = await self._connection_manager.connect()

            if success:
                # Update connection references
                self._connection = self._connection_manager.connection
                self._connected = True

                # Step 5: Re-establish subscriptions
                if self._subscription_manager and self._connection:
                    _logger.debug("Re-establishing subscriptions...")
                    self._subscription_manager.update_connection(
                        self._connection
                    )
                    await self._subscription_manager.resubscribe_all()

                # A brand-new connection never fires the SDK's
                # on_connection_resumed callback, so queued commands must
                # be flushed here or they would be lost.
                if self.config.enable_command_queue and self._command_queue:
                    await self._send_queued_commands_internal()

                _logger.info(
                    "Deep reconnection successful - fully rebuilt connection"
                )
            else:
                _logger.error("Deep reconnection failed to connect")

        except (
            AwsCrtError,
            AuthenticationError,
            RuntimeError,
            ValueError,
        ) as e:
            _logger.error(f"Error during deep reconnection: {e}", exc_info=True)
            raise
        finally:
            self._actively_reconnecting = False

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
                # Update connection state
                self._connection = self._connection_manager.connection
                self._connected = True

                # Initialize reconnection handler
                self._reconnection_handler = MqttReconnectionHandler(
                    config=self.config,
                    is_connected_func=lambda: self._connected,
                    schedule_coroutine_func=self._schedule_coroutine,
                    reconnect_func=self._active_reconnect,
                    deep_reconnect_func=self._deep_reconnect,
                    emit_event_func=self.emit,
                )
                self._reconnection_handler.enable()

                # Initialize shared device info cache and client_id
                from ..device_info_cache import MqttDeviceInfoCache

                client_id = self.config.client_id or ""
                device_info_cache = MqttDeviceInfoCache(
                    update_interval_minutes=30
                )

                # Initialize subscription manager with cache
                self._subscription_manager = MqttSubscriptionManager(
                    connection=self._connection,
                    client_id=client_id,
                    event_emitter=self,
                    schedule_coroutine=self._schedule_coroutine,
                    device_info_cache=device_info_cache,
                    operation_timeout=self.config.operation_timeout,
                )

                # Update device controller cache
                self._device_controller.device_info_cache = device_info_cache

                # Set the auto-request callback on the controller
                # Wrap ensure_device_info_cached to match callback signature
                async def ensure_callback(device: Device) -> bool:
                    return await self.ensure_device_info_cached(device)

                self._device_controller.set_ensure_device_info_callback(
                    ensure_callback
                )
                # Note: These will be implemented later when we
                # delegate device control methods
                self._periodic_manager = MqttPeriodicRequestManager(
                    is_connected_func=lambda: self._connected,
                    request_device_info_func=self._device_controller.request_device_info,
                    request_device_status_func=self._device_controller.request_device_status,
                )

                _logger.info("All components initialized successfully")

                # Record diagnostic event
                self._schedule_coroutine(
                    self._diagnostics.record_connection_success(
                        event_type="connected",
                        session_present=False,  # Initial connect
                        attempt_number=0,
                    )
                )

                return True

            return False

        except (
            AwsCrtError,
            AuthenticationError,
            RuntimeError,
            ValueError,
        ) as e:
            _logger.error(f"Failed to connect: {e}")
            raise

    async def recover_connection(self) -> bool:
        """Recover from authentication-related connection failures.

        This method is useful when MQTT connection fails due to stale/expired
        authentication tokens. It refreshes the tokens and attempts to reconnect
        the MQTT client.

        Returns:
            True if recovery was successful and MQTT is reconnected, False
            otherwise

        Raises:
            TokenRefreshError: If token refresh fails
            AuthenticationError: If re-authentication fails

        Example:
            >>> mqtt_client = NavienMqttClient(auth_client)
            >>> try:
            ...     await mqtt_client.connect()
            ... except MqttConnectionError:
            ...     # Connection may have failed due to stale tokens
            ...     if await mqtt_client.recover_connection():
            ...         print("Successfully recovered connection")
            ...     else:
            ...         print("Recovery failed, check logs")
        """
        _logger.info(
            "Attempting to recover MQTT connection by refreshing tokens"
        )

        try:
            # Step 1: Refresh authentication tokens
            await self._auth_client.ensure_valid_token()
            _logger.debug("Authentication tokens refreshed")

            # Step 2: Attempt to reconnect
            if self._connected:
                _logger.info("Already connected after token refresh")
                return True

            # If not connected, try to reconnect
            success = await self.connect()
            if success:
                _logger.info("MQTT connection successfully recovered")
                return True
            else:
                _logger.error("MQTT reconnection failed despite valid tokens")
                return False

        except (TokenRefreshError, AuthenticationError) as e:
            _logger.error(f"Failed to recover connection: {e}")
            raise

    def _create_credentials_provider(self) -> Any:
        """Create AWS credentials provider from auth tokens."""
        from awscrt.auth import (
            AwsCredentialsProvider,
        )

        # Get current tokens from auth client
        auth_tokens = self._auth_client.current_tokens
        if (
            not auth_tokens
            or not auth_tokens.access_key_id
            or not auth_tokens.secret_key
        ):
            raise MqttCredentialsError("AWS credentials not available")

        return AwsCredentialsProvider.new_static(
            access_key_id=auth_tokens.access_key_id,
            secret_access_key=auth_tokens.secret_key,
            session_token=auth_tokens.session_token,
        )

    async def disconnect(self) -> None:
        """Disconnect from AWS IoT Core and stop all periodic tasks.

        Safe to call in any state. Even when the connection is currently
        interrupted (``_connected`` is False with a reconnection loop
        running), this method disables automatic reconnection and stops
        periodic tasks so a backoff loop cannot resurrect the connection
        after the application has shut the client down.
        """
        # Always disable automatic reconnection first, regardless of the
        # current connection state.
        if self._reconnection_handler:
            self._reconnection_handler.disable()
            await self._reconnection_handler.cancel()

        # Stop all periodic tasks
        if self._periodic_manager:
            await self._periodic_manager.stop_all_periodic_tasks()

        if not self._connection_manager:
            _logger.warning("Not connected")
            return

        _logger.info("Disconnecting from AWS IoT...")

        try:
            if self._connected:
                # Delegate graceful disconnection to connection manager
                await self._connection_manager.disconnect()
            else:
                # Interrupted state: no broker session to end gracefully,
                # but the SDK connection object must still be torn down so
                # its auto-reconnect cannot fire after shutdown.
                await self._connection_manager.close()

            # Clear connection state
            self._connected = False
            self._connection = None

            _logger.info("Disconnected successfully")
        except (AwsCrtError, RuntimeError, TimeoutError) as e:
            _logger.error(f"Error during disconnect: {e}")
            raise

    async def subscribe(
        self,
        topic: str,
        callback: Callable[[str, dict[str, Any]], None],
        qos: QoS = QoS.AT_LEAST_ONCE,
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
            raise MqttNotConnectedError("Not connected to MQTT broker")

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
            raise MqttNotConnectedError("Not connected to MQTT broker")

        # Delegate to subscription manager
        return await self._subscription_manager.unsubscribe(topic)

    async def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        qos: QoS = QoS.AT_LEAST_ONCE,
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
                raise MqttNotConnectedError("Not connected to MQTT broker")

        # Delegate to connection manager
        if not self._connection_manager:
            raise MqttConnectionError("Connection manager not initialized")

        try:
            return await self._connection_manager.publish(topic, payload, qos)
        except AwsCrtError as e:
            # Handle clean session cancellation gracefully
            # Safely check e.name attribute (may not exist or be None)
            if (
                hasattr(e, "name")
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
                raise MqttPublishError(
                    "Publish cancelled due to clean session and "
                    "command queue is disabled",
                    retriable=True,
                ) from e

            # Other AWS CRT errors: wrap so awscrt exceptions never leak out
            # of the public publish() boundary.
            _logger.error(f"Failed to publish to topic: {e}")
            raise MqttPublishError(
                f"Failed to publish to MQTT topic: {e}",
                retriable=True,
            ) from e

    async def ensure_device_info_cached(
        self, device: Device, timeout: float = 30.0
    ) -> bool:
        """
        Ensure device info is cached, requesting if necessary.

        Called by control commands and CLI to ensure device
        capabilities are available before execution.

        Args:
            device: Device to ensure info for
            timeout: Maximum time to wait for response (default: 30 seconds)

        Returns:
            True if device info was successfully cached, False on timeout

        Raises:
            MqttNotConnectedError: If not connected
        """
        if not self._connected or not self._device_controller:
            raise MqttNotConnectedError("Not connected to MQTT broker")

        from .utils import redact_mac

        mac = device.device_info.mac_address
        redacted_mac = redact_mac(mac)
        cached = await self._device_controller.device_info_cache.get(mac)
        if cached is not None:
            return True

        # Not cached, request and wait
        loop = asyncio.get_running_loop()
        future: asyncio.Future[DeviceFeature] = loop.create_future()

        def on_feature(feature: DeviceFeature) -> None:
            # Called from AWS SDK thread — schedule onto the event loop
            # thread-safely. The done() check is inside the scheduled
            # callback so it runs on the event loop thread, eliminating
            # the race between the check and set_result.
            def _set_result() -> None:
                if not future.done():
                    _logger.info(f"Device feature received for {redacted_mac}")
                    future.set_result(feature)

            loop.call_soon_threadsafe(_set_result)

        _logger.info(f"Ensuring device info cached for {redacted_mac}")
        await self.subscribe_device_feature(device, on_feature)
        try:
            _logger.info(f"Requesting device info from {redacted_mac}")
            await self._device_controller.request_device_info(device)
            _logger.info(f"Waiting for device feature (timeout={timeout}s)")
            feature = await asyncio.wait_for(future, timeout=timeout)
            # Cache the feature immediately
            await self._device_controller.device_info_cache.set(mac, feature)
            return True
        except TimeoutError:
            _logger.error(
                f"Timed out waiting for device info after {timeout}s for "
                f"{redacted_mac}"
            )
            return False
        finally:
            # Unsubscribe using the specific callback to avoid leaking resources
            await self.unsubscribe_device_feature(device, on_feature)

    @property
    def _control(self) -> MqttDeviceController:
        """
        Get the internal device controller for sending commands.

        Note:
            This property is now internal. Use the delegated methods on
            NavienMqttClient directly for device control.
        """
        return self._device_controller

    async def start_periodic_requests(
        self,
        device: Device,
        request_type: PeriodicRequestType = PeriodicRequestType.DEVICE_STATUS,
        period_seconds: float = 300.0,
    ) -> None:
        """
        Start sending periodic requests for device information or status.
        ...
        """
        if not self._periodic_manager:
            raise MqttConnectionError(
                "Periodic request manager not initialized"
            )

        await self._periodic_manager.start_periodic_requests(
            device, request_type, period_seconds
        )

    async def stop_periodic_requests(
        self,
        device: Device,
        request_type: PeriodicRequestType | None = None,
    ) -> None:
        """
        Stop sending periodic requests for a device.
        ...
        """
        if not self._periodic_manager:
            raise MqttConnectionError(
                "Periodic request manager not initialized"
            )

        await self._periodic_manager.stop_periodic_requests(
            device, request_type
        )

    async def _stop_all_periodic_tasks(self) -> None:
        """
        Stop all periodic tasks.
        ...
        """
        # Delegate to public method with specific reason
        await self.stop_all_periodic_tasks(_reason="connection failure")

    async def stop_all_periodic_tasks(self, _reason: str | None = None) -> None:
        """
        Stop all periodic request tasks.
        ...
        """
        if not self._periodic_manager:
            raise MqttConnectionError(
                "Periodic request manager not initialized"
            )

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
        ...
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
        ...
        """
        if self._reconnection_handler:
            self._reconnection_handler.reset()

    @property
    def diagnostics(self) -> MqttDiagnosticsCollector:
        """Get the diagnostics collector instance."""
        return self._diagnostics
