"""
MQTT connection management for Navien Smart Control.

This module handles establishing and maintaining the MQTT connection to AWS IoT
Core,
including credential management and connection state tracking.
"""

import asyncio
import concurrent.futures
import functools
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import awscrt.auth
import awscrt.io
import awscrt.mqtt
from awscrt.exceptions import AwsCrtError

from ..exceptions import (
    MqttCredentialsError,
    MqttNotConnectedError,
)
from .types import (
    MqttConnectionHandle,
    MqttWill,
    QoS,
    to_awscrt_qos,
    to_awscrt_will,
)
from .utils import log_payload, redact_topic

if TYPE_CHECKING:
    from ..auth import NavienAuthClient
    from .utils import MqttConnectionConfig

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"


# AWS IoT signs the websocket upgrade with SigV4 for this service.
_IOT_SIGNING_SERVICE = "iotdevicegateway"


def _sign_websocket_handshake(
    region: str,
    credentials_provider: awscrt.auth.AwsCredentialsProvider,
    transform_args: Any,
    **kwargs: Any,
) -> None:
    """Sign the websocket upgrade request; awscrt waits on ``set_done``."""
    try:
        signing_config = awscrt.auth.AwsSigningConfig(
            algorithm=awscrt.auth.AwsSigningAlgorithm.V4,
            signature_type=(
                awscrt.auth.AwsSignatureType.HTTP_REQUEST_QUERY_PARAMS
            ),
            credentials_provider=credentials_provider,
            region=region,
            service=_IOT_SIGNING_SERVICE,
            # AWS IoT expects X-Amz-Security-Token outside the signature.
            omit_session_token=True,
        )
        future = awscrt.auth.aws_sign_request(
            transform_args.http_request, signing_config
        )

        def _done(done: concurrent.futures.Future[Any]) -> None:
            transform_args.set_done(done.exception())

        future.add_done_callback(_done)
    except Exception as e:
        transform_args.set_done(e)


def _build_connection(
    *,
    endpoint: str,
    region: str,
    credentials_provider: awscrt.auth.AwsCredentialsProvider,
    client_id: str,
    clean_session: bool,
    keep_alive_secs: int,
    on_connection_interrupted: Callable[..., None] | None,
    on_connection_resumed: Callable[..., None] | None,
    will: awscrt.mqtt.Will | None = None,
) -> awscrt.mqtt.Connection:
    """Build an MQTT 3.1.1 connection over a SigV4-signed websocket."""
    tls_options = awscrt.io.TlsContextOptions()
    if awscrt.io.is_alpn_available():
        tls_options.alpn_list = ["http/1.1"]
    socket_options = awscrt.io.SocketOptions()
    socket_options.connect_timeout_ms = 5000
    client = awscrt.mqtt.Client(
        awscrt.io.ClientBootstrap.get_or_create_static_default(),
        awscrt.io.ClientTlsContext(tls_options),
    )
    return awscrt.mqtt.Connection(
        client=client,
        host_name=endpoint,
        port=443,
        client_id=client_id,
        clean_session=clean_session,
        on_connection_interrupted=on_connection_interrupted,
        on_connection_resumed=on_connection_resumed,
        keep_alive_secs=keep_alive_secs,
        will=will,
        socket_options=socket_options,
        use_websockets=True,
        websocket_handshake_transform=functools.partial(
            _sign_websocket_handshake, region, credentials_provider
        ),
        disable_metrics=True,
    )


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
        config: MqttConnectionConfig,
        auth_client: NavienAuthClient,
        on_connection_interrupted: (
            Callable[[MqttConnectionHandle, Exception], None] | None
        ) = None,
        on_connection_resumed: (
            Callable[[MqttConnectionHandle, Any, Any | None], None] | None
        ) = None,
        will: MqttWill | None = None,
    ):
        """
        Initialize connection manager.

        Args:
            config: MQTT connection configuration
            auth_client: Authenticated Navien auth client with AWS credentials
            on_connection_interrupted: Callback for connection interruption
            on_connection_resumed: Callback for connection resumption
            will: Optional Last-Will the broker publishes if this
                connection is lost without a DISCONNECT. Sent with the
                CONNECT packet, so it must be known before :meth:`connect`.

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
        self._connection: MqttConnectionHandle | None = None
        self._connected = False
        #: Whether the last connect resumed the broker's stored session.
        self.session_present = False
        self._on_connection_interrupted = on_connection_interrupted
        self._on_connection_resumed = on_connection_resumed
        self._will = will

        _logger.info(
            f"Initialized connection manager with client ID: {config.client_id}"
        )

    @property
    def will(self) -> MqttWill | None:
        """The Last-Will registered with the CONNECT packet, if any."""
        return self._will

    @staticmethod
    def _consume_abandoned_future(
        future: asyncio.Future[Any], operation: str
    ) -> None:
        """Retrieve the eventual result of an abandoned acknowledgement future.

        When ``_await_ack`` is cancelled or times out, the shielded future
        keeps running in the background. If nobody retrieves its eventual
        exception, asyncio logs a "Future exception was never retrieved"
        warning at garbage-collection time. This callback consumes that
        result/exception so the warning is never emitted, logging benign
        errors (e.g. ``AwsCrtError`` from clean-session cancellation during
        reconnect) at debug level instead.
        """
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:
            # The type only: a late SubscribeError's text is the topic.
            _logger.debug(
                "%s completed with exception after being abandoned: %s",
                operation,
                type(exc).__name__,
            )

    async def _await_ack(
        self,
        future: concurrent.futures.Future[Any] | asyncio.Future[Any],
        operation: str,
    ) -> Any:
        """Await a broker acknowledgement future with a timeout.

        The awscrt future is shielded so cancellation (or a timeout) never
        propagates into the SDK future: the underlying operation completes
        independently, preventing InvalidStateError in AWS CRT callbacks.

        A timeout guards against half-open TCP connections where the
        acknowledgement never arrives; without it callers can hang until
        the keep-alive expires (20+ minutes).

        If the awaiting task is cancelled or times out before the shielded
        future completes, a done callback is attached so its eventual
        result/exception is still retrieved, preventing asyncio's "Future
        exception was never retrieved" warnings.

        Args:
            future: Acknowledgement future: the
                ``concurrent.futures.Future`` returned by the AWS CRT SDK
                (wrapped via ``asyncio.wrap_future``), or an already
                loop-bound ``asyncio.Future``
            operation: Human-readable operation name for error messages

        Returns:
            The acknowledgement result

        Raises:
            TimeoutError: If no acknowledgement within
                config.operation_timeout seconds
            asyncio.CancelledError: If the awaiting task is cancelled
        """
        awaitable_future: asyncio.Future[Any] = (
            asyncio.wrap_future(future)
            if isinstance(future, concurrent.futures.Future)
            else future
        )
        try:
            return await asyncio.wait_for(
                asyncio.shield(awaitable_future),
                timeout=self.config.operation_timeout,
            )
        except asyncio.CancelledError:
            _logger.debug(
                "%s was cancelled but will complete in background", operation
            )
            awaitable_future.add_done_callback(
                functools.partial(
                    self._consume_abandoned_future, operation=operation
                )
            )
            raise
        except TimeoutError:
            _logger.error(
                "%s not acknowledged within %.1fs",
                operation,
                self.config.operation_timeout,
            )
            awaitable_future.add_done_callback(
                functools.partial(
                    self._consume_abandoned_future, operation=operation
                )
            )
            raise

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
            # Build the websocket MQTT connection off the event loop: the
            # TLS context loads the system trust store synchronously.
            credentials_provider = await asyncio.to_thread(
                self._create_credentials_provider
            )
            client_id = self.config.client_id
            if client_id is None:
                # MqttConnectionConfig fills it in when it is built.
                raise RuntimeError("MQTT client ID is not set")
            builder_kwargs: dict[str, Any] = {}
            if self._will is not None:
                builder_kwargs["will"] = to_awscrt_will(self._will)
                _logger.debug(
                    "Registering Last-Will on %s",
                    redact_topic(self._will.topic),
                )
            self._connection = await asyncio.to_thread(
                _build_connection,
                endpoint=self.config.endpoint,
                region=self.config.region,
                credentials_provider=credentials_provider,
                client_id=client_id,
                clean_session=self.config.clean_session,
                keep_alive_secs=self.config.keep_alive_secs,
                on_connection_interrupted=self._on_connection_interrupted,
                on_connection_resumed=self._on_connection_resumed,
                **builder_kwargs,
            )

            # Connect
            _logger.info("Establishing MQTT connection...")

            # Convert concurrent.futures.Future to asyncio.Future and await
            # Use shield to prevent cancellation from propagating to
            # underlying future
            if not self._connection:
                raise RuntimeError("Connection not initialized")
            connect_future = self._connection.connect()
            connect_result = await self._await_ack(connect_future, "Connect")

            self._connected = True
            self.session_present = bool(connect_result["session_present"])
            _logger.info(
                f"Connected successfully: "
                f"session_present={connect_result['session_present']}"
            )

            return True

        except (AwsCrtError, RuntimeError, ValueError) as e:
            _logger.error(f"Failed to connect: {e}")
            raise

    def _create_credentials_provider(self) -> Any:
        """Create the AWS credentials provider for the connection.

        The provider reads the auth client's current tokens each time the
        connection signs a handshake, so a reconnect after the tokens are
        refreshed signs with the new ones.

        Returns:
            AWS credentials provider for MQTT connection

        Raises:
            MqttCredentialsError: If tokens are not available
        """
        from awscrt.auth import AwsCredentialsProvider

        self._current_credentials()
        return AwsCredentialsProvider.new_delegate(self._current_credentials)

    def _current_credentials(self) -> Any:
        """The auth client's current AWS credentials.

        Raises:
            MqttCredentialsError: If tokens are not available
        """
        from awscrt.auth import AwsCredentials

        auth_tokens = self._auth_client.current_tokens
        if (
            not auth_tokens
            or not auth_tokens.access_key_id
            or not auth_tokens.secret_key
        ):
            raise MqttCredentialsError("AWS credentials not available")
        return AwsCredentials(
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
            await self._await_ack(disconnect_future, "Disconnect")

            self._connected = False
            self._connection = None
            _logger.info("Disconnected successfully")
        except (AwsCrtError, RuntimeError) as e:
            _logger.error(f"Error during disconnect: {e}")
            raise

    async def close(self) -> None:
        """Unconditionally close the underlying SDK connection.

        Unlike :meth:`disconnect`, this method closes the connection
        regardless of the ``_connected`` flag.  After a connection
        interruption, ``_connected`` is ``False`` but the SDK connection
        object is still alive and its built-in auto-reconnect can still
        fire.  Calling ``close()`` fully tears the SDK connection
        down so its callbacks and auto-reconnect cannot interfere
        with a replacement connection.

        This method is safe to call multiple times or on already-closed
        connections.
        """
        connection = self._connection
        self._connection = None
        self._connected = False

        if connection is None:
            return

        _logger.debug("Closing underlying SDK connection...")
        try:
            disconnect_future = connection.disconnect()
            await self._await_ack(disconnect_future, "Close")
            _logger.debug("SDK connection closed")
        except (AwsCrtError, RuntimeError, TimeoutError) as e:
            # Expected when connection is already dead or in bad state
            _logger.debug(f"SDK connection close (benign): {e}")
        except asyncio.CancelledError:
            _logger.debug(
                "Close operation cancelled but SDK disconnect "
                "will complete in background"
            )
            raise

    async def subscribe(
        self,
        topic: str,
        qos: QoS,
        callback: Callable[..., None] | None = None,
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

        _logger.debug(f"Subscribing to topic: {redact_topic(topic)}")

        # Convert concurrent.futures.Future to asyncio.Future and await
        # Use shield to prevent cancellation from propagating to
        # underlying future
        subscribe_future_raw, packet_id_raw = self._connection.subscribe(
            topic=topic, qos=to_awscrt_qos(qos), callback=callback
        )
        subscribe_future = subscribe_future_raw
        packet_id = packet_id_raw

        await self._await_ack(
            subscribe_future, f"Subscribe to '{redact_topic(topic)}'"
        )

        _logger.info(
            f"Subscribed to '{redact_topic(topic)}' with packet_id {packet_id}"
        )
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

        _logger.debug(f"Unsubscribing from topic: {redact_topic(topic)}")

        # Convert concurrent.futures.Future to asyncio.Future and await
        # Use shield to prevent cancellation from propagating to
        # underlying future
        unsubscribe_future_raw, packet_id_raw = self._connection.unsubscribe(
            topic=topic
        )
        unsubscribe_future = unsubscribe_future_raw
        packet_id = int(packet_id_raw)

        await self._await_ack(
            unsubscribe_future, f"Unsubscribe from '{redact_topic(topic)}'"
        )

        _logger.info(
            "Unsubscribed from '%s' with packet_id %s",
            redact_topic(topic),
            packet_id,
        )
        return packet_id

    async def publish(
        self,
        topic: str,
        payload: str | dict[str, Any],
        qos: QoS = QoS.AT_LEAST_ONCE,
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

        _logger.debug(f"Publishing to topic: {redact_topic(topic)}")

        # Convert payload to bytes if needed
        if isinstance(payload, dict):
            payload_bytes = json.dumps(payload).encode("utf-8")
        else:
            # payload is str
            payload_bytes = payload.encode("utf-8")

        # Publish and get the concurrent.futures.Future
        publish_future_raw, packet_id_raw = self._connection.publish(
            topic=topic, payload=payload_bytes, qos=to_awscrt_qos(qos)
        )
        publish_future = publish_future_raw
        packet_id = int(packet_id_raw)
        log_payload("send", topic, payload, packet_id)

        # Shield the operation to prevent cancellation from propagating to
        # the underlying concurrent.futures.Future. This avoids
        # InvalidStateError when AWS CRT tries to set exception on a
        # cancelled future.
        try:
            await self._await_ack(
                publish_future, f"Publish to '{redact_topic(topic)}'"
            )
        except AwsCrtError as e:
            # Handle connection destruction during publish
            # This can happen when AWS IoT Core disconnects (e.g., 24-hour
            # timeout)
            error_name = getattr(e, "name", None)
            if error_name == "AWS_ERROR_MQTT_CONNECTION_DESTROYED":
                _logger.warning(
                    "MQTT connection destroyed during publish to '%s'. "
                    "This can occur during AWS-initiated disconnections. "
                    "Reconnection will be attempted automatically.",
                    redact_topic(topic),
                )
                # Mark as disconnected so reconnection handler can take over
                self._connected = False
            raise

        _logger.debug(
            f"Published to '{redact_topic(topic)}' with packet_id {packet_id}"
        )
        return packet_id

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._connected

    @property
    def connection(self) -> MqttConnectionHandle | None:
        """Get the underlying MQTT connection.

        Returns:
            The MQTT connection object, or None if not connected

        Note:
            This property is provided for advanced usage. Most operations
            should use the higher-level methods provided by this class.
        """
        return self._connection
