"""
MQTT connection management for Navien Smart Control.

This module handles establishing and maintaining the MQTT connection to AWS IoT
Core,
including credential management and connection state tracking.
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from awscrt import mqtt
from awscrt.exceptions import AwsCrtError
from awsiot import mqtt_connection_builder

from .exceptions import (
    MqttConnectionError,
    MqttCredentialsError,
    MqttNotConnectedError,
)

if TYPE_CHECKING:
    from .auth import NavienAuthClient
    from .mqtt_utils import MqttConnectionConfig

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


class MqttConnection:
    """
    Manages MQTT connection lifecycle to AWS IoT Core.

    Handles:
    - Connection establishment with AWS credentials
    - Disconnection with cleanup
    - Connection state tracking
    - AWS credentials provider creation
    """

    def __init__(
        self,
        config: "MqttConnectionConfig",
        auth_client: "NavienAuthClient",
        on_connection_interrupted: Optional[
            Callable[[mqtt.Connection, Exception], None]
        ] = None,
        on_connection_resumed: Optional[Callable[[Any, Any], None]] = None,
    ):
        """
        Initialize connection manager.

        Args:
            config: MQTT connection configuration
            auth_client: Authenticated Navien auth client with AWS credentials
            on_connection_interrupted: Callback for connection interruption
            on_connection_resumed: Callback for connection resumption

        Raises:
            ValueError: If auth client not authenticated or missing AWS
            credentials
        """
        if not auth_client.is_authenticated:
            raise ValueError(
                "Authentication client must be authenticated before "
                "creating connection manager."
            )

        if not auth_client.current_tokens:
            raise MqttCredentialsError("No tokens available from auth client")

        auth_tokens = auth_client.current_tokens
        if not auth_tokens.access_key_id or not auth_tokens.secret_key:
            raise ValueError(
                "AWS credentials not available in auth tokens. "
                "Ensure authentication provides AWS IoT credentials."
            )

        self.config = config
        self._auth_client = auth_client
        self._connection: Optional[mqtt.Connection] = None
        self._connected = False
        self._on_connection_interrupted = on_connection_interrupted
        self._on_connection_resumed = on_connection_resumed

        _logger.info(
            f"Initialized connection manager with client ID: {config.client_id}"
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

        # Ensure we have valid tokens before connecting
        await self._auth_client.ensure_valid_token()

        _logger.info(f"Connecting to AWS IoT endpoint: {self.config.endpoint}")
        _logger.debug(f"Client ID: {self.config.client_id}")
        _logger.debug(f"Region: {self.config.region}")

        try:
            # Build WebSocket MQTT connection with AWS credentials
            # Run blocking operations in a thread to avoid blocking the event
            # loop
            # The AWS IoT SDK performs synchronous file I/O operations during
            # connection setup
            credentials_provider = await asyncio.to_thread(
                self._create_credentials_provider
            )
            self._connection = await asyncio.to_thread(
                mqtt_connection_builder.websockets_with_default_aws_signing,
                endpoint=self.config.endpoint,
                region=self.config.region,
                credentials_provider=credentials_provider,
                client_id=self.config.client_id,
                clean_session=self.config.clean_session,
                keep_alive_secs=self.config.keep_alive_secs,
                on_connection_interrupted=self._on_connection_interrupted,
                on_connection_resumed=self._on_connection_resumed,
            )

            # Connect
            _logger.info("Establishing MQTT connection...")

            # Convert concurrent.futures.Future to asyncio.Future and await
            # Use shield to prevent cancellation from propagating to
            # underlying future
            if self._connection is not None:
                connect_future = self._connection.connect()
                try:
                    connect_result = await asyncio.shield(
                        asyncio.wrap_future(connect_future)
                    )
                except asyncio.CancelledError:
                    # Shield was cancelled - the underlying connect will
                    # complete independently, preventing InvalidStateError
                    # in AWS CRT callbacks
                    _logger.debug(
                        "Connect operation was cancelled but will complete "
                        "in background"
                    )
                    raise
            else:
                raise MqttConnectionError("Connection not initialized")

            self._connected = True
            _logger.info(
                f"Connected successfully: "
                f"session_present={connect_result['session_present']}"
            )

            return True

        except (AwsCrtError, RuntimeError, ValueError) as e:
            _logger.error(f"Failed to connect: {e}")
            raise

    def _create_credentials_provider(self) -> Any:
        """
        Create AWS credentials provider from auth tokens.

        Returns:
            AWS credentials provider for MQTT connection

        Raises:
            ValueError: If tokens are not available
        """
        from awscrt.auth import AwsCredentialsProvider

        # Get current tokens from auth client
        auth_tokens = self._auth_client.current_tokens
        if not auth_tokens:
            raise MqttCredentialsError("No tokens available from auth client")

        return AwsCredentialsProvider.new_static(
            access_key_id=auth_tokens.access_key_id,
            secret_access_key=auth_tokens.secret_key,
            session_token=auth_tokens.session_token,
        )

    async def disconnect(self) -> None:
        """
        Disconnect from AWS IoT Core.

        Raises:
            Exception: If disconnect fails
        """
        if not self._connected or not self._connection:
            _logger.warning("Not connected")
            return

        _logger.info("Disconnecting from AWS IoT...")

        try:
            # Convert concurrent.futures.Future to asyncio.Future and await
            # Use shield to prevent cancellation from propagating to
            # underlying future
            disconnect_future = self._connection.disconnect()
            try:
                await asyncio.shield(asyncio.wrap_future(disconnect_future))
            except asyncio.CancelledError:
                # Shield was cancelled - the underlying disconnect will
                # complete independently, preventing InvalidStateError
                # in AWS CRT callbacks
                _logger.debug(
                    "Disconnect operation was cancelled but will complete "
                    "in background"
                )
                raise

            self._connected = False
            self._connection = None
            _logger.info("Disconnected successfully")
        except (AwsCrtError, RuntimeError) as e:
            _logger.error(f"Error during disconnect: {e}")
            raise

    async def subscribe(
        self,
        topic: str,
        qos: mqtt.QoS,
        callback: Optional[Callable[..., None]] = None,
    ) -> tuple[Any, int]:
        """
        Subscribe to an MQTT topic.

        Args:
            topic: Topic pattern to subscribe to (supports wildcards)
            qos: Quality of Service level
            callback: Optional callback for received messages

        Returns:
            Tuple of (subscribe_future, packet_id)

        Raises:
            RuntimeError: If not connected
        """
        if not self._connected or not self._connection:
            raise MqttNotConnectedError("Not connected to MQTT broker")

        _logger.debug(f"Subscribing to topic: {topic}")

        # Convert concurrent.futures.Future to asyncio.Future and await
        # Use shield to prevent cancellation from propagating to
        # underlying future
        subscribe_future, packet_id = self._connection.subscribe(
            topic=topic, qos=qos, callback=callback
        )
        try:
            await asyncio.shield(asyncio.wrap_future(subscribe_future))
        except asyncio.CancelledError:
            # Shield was cancelled - the underlying subscribe will
            # complete independently, preventing InvalidStateError
            # in AWS CRT callbacks
            _logger.debug(
                f"Subscribe to '{topic}' was cancelled but will complete "
                "in background"
            )
            raise

        _logger.info(f"Subscribed to '{topic}' with packet_id {packet_id}")
        return (subscribe_future, packet_id)

    async def unsubscribe(self, topic: str) -> int:
        """
        Unsubscribe from an MQTT topic.

        Args:
            topic: Topic to unsubscribe from

        Returns:
            Packet ID

        Raises:
            RuntimeError: If not connected
        """
        if not self._connected or not self._connection:
            raise MqttNotConnectedError("Not connected to MQTT broker")

        _logger.debug(f"Unsubscribing from topic: {topic}")

        # Convert concurrent.futures.Future to asyncio.Future and await
        # Use shield to prevent cancellation from propagating to
        # underlying future
        unsubscribe_future, packet_id = self._connection.unsubscribe(
            topic=topic
        )
        try:
            await asyncio.shield(asyncio.wrap_future(unsubscribe_future))
        except asyncio.CancelledError:
            # Shield was cancelled - the underlying unsubscribe will
            # complete independently, preventing InvalidStateError
            # in AWS CRT callbacks
            _logger.debug(
                f"Unsubscribe from '{topic}' was cancelled but will "
                "complete in background"
            )
            raise

        _logger.info(f"Unsubscribed from '{topic}' with packet_id {packet_id}")
        return int(packet_id)

    async def publish(
        self,
        topic: str,
        payload: Union[str, dict[str, Any], Any],
        qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE,
    ) -> int:
        """
        Publish a message to an MQTT topic.

        Args:
            topic: MQTT topic to publish to
            payload: Message payload (dict, JSON string, or bytes)
            qos: Quality of Service level

        Returns:
            Publish packet ID

        Raises:
            RuntimeError: If not connected
            asyncio.CancelledError: If operation cancelled during disconnect
        """
        if not self._connected or not self._connection:
            raise MqttNotConnectedError("Not connected to MQTT broker")

        _logger.debug(f"Publishing to topic: {topic}")

        # Convert payload to bytes if needed
        if isinstance(payload, dict):
            payload_bytes = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        elif isinstance(payload, bytes):
            payload_bytes = payload
        else:
            # Try to JSON encode other types
            payload_bytes = json.dumps(payload).encode("utf-8")

        # Publish and get the concurrent.futures.Future
        publish_future, packet_id = self._connection.publish(
            topic=topic, payload=payload_bytes, qos=qos
        )

        # Shield the operation to prevent cancellation from propagating to
        # the underlying concurrent.futures.Future. This avoids
        # InvalidStateError when AWS CRT tries to set exception on a
        # cancelled future.
        try:
            await asyncio.shield(asyncio.wrap_future(publish_future))
        except asyncio.CancelledError:
            # Shield was cancelled - the underlying publish will complete
            # independently, preventing InvalidStateError in AWS CRT
            # callbacks
            _logger.debug(
                f"Publish to '{topic}' was cancelled but will complete "
                "in background"
            )
            raise
        except AwsCrtError as e:
            # Handle connection destruction during publish
            # This can happen when AWS IoT Core disconnects (e.g., 24-hour
            # timeout)
            error_name = getattr(e, "name", None)
            if error_name == "AWS_ERROR_MQTT_CONNECTION_DESTROYED":
                _logger.warning(
                    f"MQTT connection destroyed during publish to '{topic}'. "
                    "This can occur during AWS-initiated disconnections. "
                    "Reconnection will be attempted automatically."
                )
                # Mark as disconnected so reconnection handler can take over
                self._connected = False
            raise

        _logger.debug(f"Published to '{topic}' with packet_id {packet_id}")
        return int(packet_id)

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._connected

    @property
    def connection(self) -> Optional[mqtt.Connection]:
        """Get the underlying MQTT connection.

        Returns:
            The MQTT connection object, or None if not connected

        Note:
            This property is provided for advanced usage. Most operations
            should use the higher-level methods provided by this class.
        """
        return self._connection
