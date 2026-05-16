"""Tests for MQTT reconnection: old connection cleanup."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from nwp500.auth import AuthenticationResponse, AuthTokens, UserInfo
from nwp500.mqtt.connection import MqttConnection
from nwp500.mqtt.utils import MqttConnectionConfig


@pytest.fixture
def mock_auth_client():
    """Create a mock auth client with valid tokens."""
    from nwp500.auth import NavienAuthClient

    client = NavienAuthClient("test@example.com", "password")
    valid_tokens = AuthTokens(
        id_token="test_id",
        access_token="test_access",
        refresh_token="test_refresh",
        authentication_expires_in=3600,
        access_key_id="test_key_id",
        secret_key="test_secret_key",
        session_token="test_session",
        authorization_expires_in=3600,
    )
    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="Test", user_last_name="User"),
        tokens=valid_tokens,
    )
    return client


@pytest.fixture
def config():
    return MqttConnectionConfig(client_id="test-client")


class TestMqttConnectionClose:
    """Tests for MqttConnection.close() method."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_on_none_connection(self, config, mock_auth_client):
        """close() should be safe to call when _connection is None."""
        conn = MqttConnection(config, mock_auth_client)
        assert conn._connection is None
        # Should not raise
        await conn.close()
        assert conn._connected is False
        assert conn._connection is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_clears_state(self, config, mock_auth_client):
        """close() should clear _connection and _connected regardless."""
        conn = MqttConnection(config, mock_auth_client)
        # Simulate a connection that was interrupted (_connected=False
        # but _connection still exists)
        mock_sdk_conn = MagicMock()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.set_result(None)
        mock_sdk_conn.disconnect.return_value = future
        conn._connection = mock_sdk_conn
        conn._connected = False  # Interrupted state

        await conn.close()

        assert conn._connection is None
        assert conn._connected is False
        mock_sdk_conn.disconnect.assert_called_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_disconnect_skips_when_not_connected(
        self, config, mock_auth_client
    ):
        """disconnect() should skip when _connected is False."""
        conn = MqttConnection(config, mock_auth_client)
        mock_sdk_conn = MagicMock()
        conn._connection = mock_sdk_conn
        conn._connected = False  # Interrupted state

        await conn.disconnect()

        # disconnect() should NOT call the SDK disconnect
        mock_sdk_conn.disconnect.assert_not_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_handles_already_dead_connection(
        self, config, mock_auth_client
    ):
        """close() should handle errors from SDK disconnect gracefully."""
        from awscrt.exceptions import AwsCrtError

        conn = MqttConnection(config, mock_auth_client)
        mock_sdk_conn = MagicMock()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.set_exception(
            AwsCrtError(
                code=0,
                name="AWS_ERROR_MQTT_CONNECTION_DESTROYED",
                message="Connection destroyed",
            )
        )
        mock_sdk_conn.disconnect.return_value = future
        conn._connection = mock_sdk_conn
        conn._connected = False

        # Should not raise
        await conn.close()
        assert conn._connection is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_idempotent(self, config, mock_auth_client):
        """close() should be safe to call multiple times."""
        conn = MqttConnection(config, mock_auth_client)
        # Call twice - should not raise
        await conn.close()
        await conn.close()
        assert conn._connection is None
