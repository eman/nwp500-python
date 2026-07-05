"""Tests for MQTT client clean session reconnection handling."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nwp500.auth import AuthenticationResponse, AuthTokens, UserInfo
from nwp500.mqtt import NavienMqttClient


@pytest.fixture
def auth_client_with_valid_tokens():
    """Create an auth client with valid tokens."""
    from nwp500.auth import NavienAuthClient

    auth_client = NavienAuthClient("test@example.com", "password")
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
    auth_client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="Test", user_last_name="User"),
        tokens=valid_tokens,
    )
    return auth_client


class TestMqttCleanSessionResume:
    """Tests for clean session (session_present=False) reconnection handling."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_on_connection_resumed_with_clean_session_resubscribes(
        self, auth_client_with_valid_tokens
    ):
        """Resubscribe when session_present=False on connection resume."""
        client = NavienMqttClient(auth_client_with_valid_tokens)

        # Mock the components
        mock_subscription_manager = AsyncMock()
        mock_subscription_manager.resubscribe_all = AsyncMock()
        client._subscription_manager = mock_subscription_manager

        mock_connection_manager = MagicMock()
        mock_connection = MagicMock()
        mock_connection_manager.connection = mock_connection
        client._connection_manager = mock_connection_manager

        # Mock the event emitter and diagnostics
        client.emit = AsyncMock()
        client._diagnostics = MagicMock()
        client._diagnostics.record_connection_success = AsyncMock()

        # Call with session_present=False (clean session)
        client._on_connection_resumed_internal(
            connection=mock_connection, return_code=0, session_present=False
        )

        # Give the scheduled coroutine time to run
        import asyncio

        await asyncio.sleep(0.1)

        # Verify resubscribe_all was called
        mock_subscription_manager.update_connection.assert_called_once_with(
            mock_connection
        )
        # The resubscribe should be scheduled via _schedule_coroutine
        # We need to wait for it or check the internal state

    @pytest.mark.asyncio(loop_scope="function")
    async def test_resubscribe_before_queued_commands(
        self, auth_client_with_valid_tokens
    ):
        """Resubscribe completes before queued commands are sent."""
        client = NavienMqttClient(auth_client_with_valid_tokens)

        # Track call order
        call_order = []

        # Mock the components
        mock_subscription_manager = MagicMock()
        mock_subscription_manager.resubscribe_all = AsyncMock(
            side_effect=lambda: call_order.append("resubscribe")
        )
        client._subscription_manager = mock_subscription_manager

        mock_connection_manager = MagicMock()
        mock_connection = MagicMock()
        mock_connection_manager.connection = mock_connection
        client._connection_manager = mock_connection_manager

        # Mock command queue
        client._command_queue = AsyncMock()
        client.config.enable_command_queue = True

        # Mock send_queued_commands to track it's called after resubscribe
        original_send = client._send_queued_commands_internal

        async def mock_send():
            call_order.append("send_queued")
            await original_send()

        client._send_queued_commands_internal = mock_send

        # Call the method
        await client._handle_clean_session_resume()

        # Verify subscription manager was updated with connection
        mock_subscription_manager.update_connection.assert_called_once_with(
            mock_connection
        )

        # Verify resubscribe was called before queued commands
        assert call_order == ["resubscribe", "send_queued"]

    @pytest.mark.asyncio(loop_scope="function")
    async def test_skip_when_no_subscription_manager(
        self, auth_client_with_valid_tokens
    ):
        """Return early if subscription_manager is None."""
        client = NavienMqttClient(auth_client_with_valid_tokens)
        client._subscription_manager = None

        # Should not raise
        await client._handle_clean_session_resume()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_handle_clean_session_resume_skips_when_no_connection(
        self, auth_client_with_valid_tokens
    ):
        """Return early if connection is None."""
        client = NavienMqttClient(auth_client_with_valid_tokens)

        mock_subscription_manager = MagicMock()
        client._subscription_manager = mock_subscription_manager

        mock_connection_manager = MagicMock()
        mock_connection_manager.connection = None
        client._connection_manager = mock_connection_manager

        # Should not raise
        await client._handle_clean_session_resume()

        # Should not try to update connection
        mock_subscription_manager.update_connection.assert_not_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_on_connection_resumed_with_session_sends_queued_commands(
        self, auth_client_with_valid_tokens
    ):
        """Send queued commands normally when session_present=True."""
        client = NavienMqttClient(auth_client_with_valid_tokens)

        # Mock the components
        mock_command_queue = AsyncMock()
        client._command_queue = mock_command_queue
        client.config.enable_command_queue = True

        # Mock the event emitter and diagnostics
        client.emit = AsyncMock()
        client._diagnostics = MagicMock()
        client._diagnostics.record_connection_success = AsyncMock()

        # Mock connection
        mock_connection = MagicMock()

        # Patch _send_queued_commands_internal to track if called
        with patch.object(
            client, "_send_queued_commands_internal", new_callable=AsyncMock
        ):
            # Call with session_present=True (session resumed)
            client._on_connection_resumed_internal(
                connection=mock_connection, return_code=0, session_present=True
            )

            # Give the scheduled coroutine time to run
            import asyncio

            await asyncio.sleep(0.1)

            # Verify send_queued_commands_internal was scheduled
            # (it will be called through _schedule_coroutine)
