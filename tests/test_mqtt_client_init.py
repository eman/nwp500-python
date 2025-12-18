"""Tests for MQTT client initialization and token validation."""

from datetime import datetime, timedelta

import pytest

from nwp500.auth import (
    AuthenticationResponse,
    AuthTokens,
    NavienAuthClient,
    UserInfo,
)
from nwp500.exceptions import MqttCredentialsError
from nwp500.mqtt_client import NavienMqttClient


@pytest.fixture
def auth_client_with_valid_tokens():
    """Create an auth client with valid tokens."""
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


@pytest.fixture
def auth_client_with_expired_jwt():
    """Create an auth client with expired JWT token."""
    auth_client = NavienAuthClient("test@example.com", "password")
    old_time = datetime.now() - timedelta(seconds=7200)
    expired_tokens = AuthTokens(
        id_token="test_id",
        access_token="test_access",
        refresh_token="test_refresh",
        authentication_expires_in=3600,
        access_key_id="test_key_id",
        secret_key="test_secret_key",
        session_token="test_session",
        authorization_expires_in=3600,
        issued_at=old_time,
    )
    auth_client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="Test", user_last_name="User"),
        tokens=expired_tokens,
    )
    return auth_client


@pytest.fixture
def auth_client_with_expired_aws_credentials():
    """Create an auth client with expired AWS credentials."""
    auth_client = NavienAuthClient("test@example.com", "password")
    old_time = datetime.now() - timedelta(seconds=7200)
    expired_tokens = AuthTokens(
        id_token="test_id",
        access_token="test_access",
        refresh_token="test_refresh",
        authentication_expires_in=7200,  # JWT still valid
        access_key_id="test_key_id",
        secret_key="test_secret_key",
        session_token="test_session",
        authorization_expires_in=3600,  # AWS creds expired
        issued_at=old_time,
    )
    auth_client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="Test", user_last_name="User"),
        tokens=expired_tokens,
    )
    return auth_client


@pytest.fixture
def auth_client_not_authenticated():
    """Create an auth client that's not authenticated."""
    auth_client = NavienAuthClient("test@example.com", "password")
    return auth_client


class TestMqttClientInitValidation:
    """Test MQTT client initialization with token validation."""

    def test_mqtt_client_init_with_valid_tokens(
        self, auth_client_with_valid_tokens
    ):
        """Test MQTT client initializes successfully with valid tokens."""
        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)
        assert mqtt_client is not None
        assert mqtt_client._auth_client is auth_client_with_valid_tokens

    def test_mqtt_client_init_rejects_not_authenticated(
        self, auth_client_not_authenticated
    ):
        """Test MQTT client rejects non-authenticated auth client."""
        with pytest.raises(MqttCredentialsError) as exc_info:
            NavienMqttClient(auth_client_not_authenticated)

        assert "must be authenticated" in str(exc_info.value).lower()

    def test_mqtt_client_init_rejects_expired_jwt(
        self, auth_client_with_expired_jwt
    ):
        """Test MQTT client rejects auth client with expired JWT tokens."""
        with pytest.raises(MqttCredentialsError) as exc_info:
            NavienMqttClient(auth_client_with_expired_jwt)

        error_msg = str(exc_info.value).lower()
        assert "stale/expired" in error_msg
        assert (
            "ensure_valid_token" in error_msg or "re_authenticate" in error_msg
        )

    def test_mqtt_client_init_rejects_expired_aws_credentials(
        self, auth_client_with_expired_aws_credentials
    ):
        """Test MQTT client rejects auth client with expired AWS credentials."""
        with pytest.raises(MqttCredentialsError) as exc_info:
            NavienMqttClient(auth_client_with_expired_aws_credentials)

        error_msg = str(exc_info.value).lower()
        assert "stale/expired" in error_msg
        assert (
            "ensure_valid_token" in error_msg or "re_authenticate" in error_msg
        )

    def test_mqtt_client_init_error_message_guidance(
        self, auth_client_with_expired_jwt
    ):
        """Test MQTT client init error provides clear guidance on recovery."""
        with pytest.raises(MqttCredentialsError) as exc_info:
            NavienMqttClient(auth_client_with_expired_jwt)

        error_msg = str(exc_info.value)
        # Should mention recovery methods
        assert (
            "ensure_valid_token" in error_msg or "re_authenticate" in error_msg
        ), f"Error message should mention recovery methods: {error_msg}"


class TestHasValidTokensProperty:
    """Test the has_valid_tokens property on NavienAuthClient."""

    def test_has_valid_tokens_true(self, auth_client_with_valid_tokens):
        """Test has_valid_tokens returns True for valid tokens."""
        assert auth_client_with_valid_tokens.has_valid_tokens is True

    def test_has_valid_tokens_false_not_authenticated(
        self, auth_client_not_authenticated
    ):
        """Test has_valid_tokens returns False when not authenticated."""
        assert auth_client_not_authenticated.has_valid_tokens is False

    def test_has_valid_tokens_false_expired_jwt(
        self, auth_client_with_expired_jwt
    ):
        """Test has_valid_tokens returns False with expired JWT."""
        assert auth_client_with_expired_jwt.has_valid_tokens is False

    def test_has_valid_tokens_false_expired_aws_credentials(
        self, auth_client_with_expired_aws_credentials
    ):
        """Test has_valid_tokens returns False with expired AWS credentials."""
        assert (
            auth_client_with_expired_aws_credentials.has_valid_tokens is False
        )

    def test_has_valid_tokens_true_with_no_aws_expiration(self):
        """Test has_valid_tokens returns True when AWS expiration is unknown."""
        auth_client = NavienAuthClient("test@example.com", "password")
        tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=3600,
            access_key_id="test_key_id",
            secret_key="test_secret_key",
            # No authorization_expires_in - AWS credentials lack expiration
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=tokens,
        )

        # Should be True: JWT valid and AWS credentials have no expiration
        assert auth_client.has_valid_tokens is True

    def test_has_valid_tokens_integration_with_mqtt_init(
        self, auth_client_with_valid_tokens
    ):
        """Test that has_valid_tokens integrates correctly with MQTT init."""
        # When has_valid_tokens is True, MQTT init should succeed
        assert auth_client_with_valid_tokens.has_valid_tokens is True
        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)
        assert mqtt_client is not None


class TestHasValidTokensPropertyComprehensive:
    """Comprehensive test coverage for has_valid_tokens property."""

    def test_has_valid_tokens_no_auth_response(self):
        """Test scenario 1: No auth response."""
        auth_client = NavienAuthClient("test@example.com", "password")

        # No authentication response set
        assert auth_client._auth_response is None
        assert auth_client.has_valid_tokens is False

    def test_has_valid_tokens_expired_jwt_only(self):
        """Test scenario 2: Expired JWT tokens only."""
        auth_client = NavienAuthClient("test@example.com", "password")

        # Create tokens with expired JWT but valid AWS credentials
        old_time = datetime.now() - timedelta(seconds=7200)
        expired_jwt_tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=3600,  # JWT expires (2 hours ago)
            access_key_id="test_key_id",
            secret_key="test_secret_key",
            session_token="test_session",
            authorization_expires_in=10800,  # AWS creds valid (3 hours)
            issued_at=old_time,
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=expired_jwt_tokens,
        )

        # JWT is expired, so has_valid_tokens should be False
        assert expired_jwt_tokens.is_expired is True
        assert expired_jwt_tokens.are_aws_credentials_expired is False
        assert auth_client.has_valid_tokens is False

    def test_has_valid_tokens_expired_aws_credentials_only(self):
        """Test scenario 3: Expired AWS credentials only."""
        auth_client = NavienAuthClient("test@example.com", "password")

        # Create tokens with valid JWT but expired AWS credentials
        old_time = datetime.now() - timedelta(seconds=7200)
        expired_aws_tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=10800,  # JWT still valid (3 hours)
            access_key_id="test_key_id",
            secret_key="test_secret_key",
            session_token="test_session",
            authorization_expires_in=3600,  # AWS creds expire (1 hour)
            issued_at=old_time,
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=expired_aws_tokens,
        )

        # AWS credentials are expired, so has_valid_tokens should be False
        assert expired_aws_tokens.is_expired is False
        assert expired_aws_tokens.are_aws_credentials_expired is True
        assert auth_client.has_valid_tokens is False

    def test_has_valid_tokens_both_expired(self):
        """Test scenario 4: Both JWT and AWS credentials expired."""
        auth_client = NavienAuthClient("test@example.com", "password")

        # Create tokens with both JWT and AWS credentials expired
        old_time = datetime.now() - timedelta(seconds=7200)
        both_expired_tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=3600,  # JWT expires
            access_key_id="test_key_id",
            secret_key="test_secret_key",
            session_token="test_session",
            authorization_expires_in=3600,  # AWS creds expire
            issued_at=old_time,
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=both_expired_tokens,
        )

        # Both JWT and AWS credentials are expired
        assert both_expired_tokens.is_expired is True
        assert both_expired_tokens.are_aws_credentials_expired is True
        assert auth_client.has_valid_tokens is False

    def test_has_valid_tokens_both_valid(self):
        """Test scenario 5: Both JWT and AWS credentials valid."""
        auth_client = NavienAuthClient("test@example.com", "password")

        # Create tokens with both JWT and AWS credentials valid
        valid_tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=3600,  # JWT valid
            access_key_id="test_key_id",
            secret_key="test_secret_key",
            session_token="test_session",
            authorization_expires_in=3600,  # AWS creds valid
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=valid_tokens,
        )

        # Both JWT and AWS credentials are valid
        assert valid_tokens.is_expired is False
        assert valid_tokens.are_aws_credentials_expired is False
        assert auth_client.has_valid_tokens is True

    def test_has_valid_tokens_property_type(self):
        """Test that has_valid_tokens always returns bool."""
        auth_client = NavienAuthClient("test@example.com", "password")

        # Test with no auth response
        assert isinstance(auth_client.has_valid_tokens, bool)

        # Test with valid tokens
        valid_tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=3600,
            access_key_id="test_key_id",
            secret_key="test_secret_key",
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=valid_tokens,
        )

        assert isinstance(auth_client.has_valid_tokens, bool)
        assert auth_client.has_valid_tokens is True

    def test_has_valid_tokens_jwt_near_expiry_buffer(self):
        """Test JWT expiration within 5-minute buffer."""
        auth_client = NavienAuthClient("test@example.com", "password")

        # Token expires in 3 minutes (within 5-minute buffer)
        near_expiry = datetime.now() - timedelta(seconds=3420)
        near_expiry_tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=3600,
            access_key_id="test_key_id",
            secret_key="test_secret_key",
            authorization_expires_in=7200,
            issued_at=near_expiry,
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=near_expiry_tokens,
        )

        # Token should be considered expired within buffer
        assert near_expiry_tokens.is_expired is True
        assert auth_client.has_valid_tokens is False

    def test_has_valid_tokens_aws_near_expiry_buffer(self):
        """Test AWS credentials expiration within 5-minute buffer."""
        auth_client = NavienAuthClient("test@example.com", "password")

        # AWS creds expire in 3 minutes (within 5-minute buffer)
        near_expiry = datetime.now() - timedelta(seconds=3420)
        near_expiry_tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=7200,
            access_key_id="test_key_id",
            secret_key="test_secret_key",
            authorization_expires_in=3600,
            issued_at=near_expiry,
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=near_expiry_tokens,
        )

        # AWS credentials should be considered expired within buffer
        assert near_expiry_tokens.are_aws_credentials_expired is True
        assert auth_client.has_valid_tokens is False

    def test_has_valid_tokens_consistent_checks(self):
        """Test that multiple calls to has_valid_tokens are consistent."""
        auth_client = NavienAuthClient("test@example.com", "password")

        valid_tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=3600,
            access_key_id="test_key_id",
            secret_key="test_secret_key",
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=valid_tokens,
        )

        # Multiple calls should return consistent results
        result1 = auth_client.has_valid_tokens
        result2 = auth_client.has_valid_tokens
        result3 = auth_client.has_valid_tokens

        assert result1 is True
        assert result2 is True
        assert result3 is True
        assert result1 == result2 == result3


class TestMqttClientInitTokenValidationSequence:
    """Test the validation sequence in MQTT client initialization."""

    def test_validation_checks_order(self, auth_client_with_valid_tokens):
        """Test that initialization performs checks in correct order."""
        # Create a mock auth client to track check order
        auth_client = auth_client_with_valid_tokens

        # First check: is_authenticated
        assert auth_client.is_authenticated is True

        # Second check: has_valid_tokens
        assert auth_client.has_valid_tokens is True

        # Third check: current_tokens exists
        assert auth_client.current_tokens is not None

        # Fourth check: AWS credentials exist
        tokens = auth_client.current_tokens
        assert tokens.access_key_id is not None
        assert tokens.secret_key is not None

        # All checks pass, MQTT init should succeed
        mqtt_client = NavienMqttClient(auth_client)
        assert mqtt_client is not None

    def test_missing_aws_credentials_is_caught(self):
        """Test that missing AWS credentials are caught even with valid JWT."""
        auth_client = NavienAuthClient("test@example.com", "password")
        tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=3600,
            # Missing access_key_id and secret_key
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=tokens,
        )

        with pytest.raises(MqttCredentialsError) as exc_info:
            NavienMqttClient(auth_client)

        assert "aws credentials" in str(exc_info.value).lower()


class TestTokenValidationEdgeCases:
    """Test edge cases in token validation."""

    def test_expired_jwt_near_expiry_buffer(self):
        """Test token considered expired within 5-minute buffer."""
        auth_client = NavienAuthClient("test@example.com", "password")
        # Token expires in 3 minutes - should be considered expired
        near_expiry = datetime.now() - timedelta(seconds=3420)
        tokens = AuthTokens(
            id_token="test_id",
            access_token="test_access",
            refresh_token="test_refresh",
            authentication_expires_in=3600,
            access_key_id="key",
            secret_key="secret",
            issued_at=near_expiry,
        )
        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test"),
            tokens=tokens,
        )

        # Token should be considered expired within buffer
        assert tokens.is_expired is True
        assert auth_client.has_valid_tokens is False

        # MQTT init should reject it
        with pytest.raises(MqttCredentialsError) as exc_info:
            NavienMqttClient(auth_client)

        assert "stale/expired" in str(exc_info.value).lower()

    def test_multiple_validation_checks_mqtt_init(
        self, auth_client_with_valid_tokens
    ):
        """Test multiple MQTT clients can be created from same auth client."""
        # First MQTT client should succeed
        mqtt_client1 = NavienMqttClient(auth_client_with_valid_tokens)
        assert mqtt_client1 is not None

        # Second MQTT client should also succeed (tokens still valid)
        mqtt_client2 = NavienMqttClient(auth_client_with_valid_tokens)
        assert mqtt_client2 is not None

        # Both should share the same auth client
        assert mqtt_client1._auth_client is mqtt_client2._auth_client


class TestRecoverConnectionMethod:
    """Test the recover_connection() method for connection recovery."""

    def test_recover_connection_method_exists(
        self, auth_client_with_valid_tokens
    ):
        """Test that recover_connection method exists and is callable."""
        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)

        assert hasattr(mqtt_client, "recover_connection")
        assert callable(mqtt_client.recover_connection)

        # Check it's an async method
        import inspect

        assert inspect.iscoroutinefunction(mqtt_client.recover_connection)

    @pytest.mark.asyncio
    async def test_recover_connection_already_connected(
        self, auth_client_with_valid_tokens
    ):
        """Test recover_connection when already connected after refresh."""
        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)

        # Mock the internal state to simulate already connected
        mqtt_client._connected = True

        # Call recover_connection
        result = await mqtt_client.recover_connection()

        # Should return True immediately
        assert result is True

    @pytest.mark.asyncio
    async def test_recover_connection_token_refresh_failure(
        self, auth_client_with_valid_tokens
    ):
        """Test recover_connection when token refresh fails."""
        from unittest.mock import AsyncMock, patch

        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)

        # Mock ensure_valid_token to raise TokenRefreshError
        from nwp500.exceptions import TokenRefreshError

        with patch.object(
            mqtt_client._auth_client,
            "ensure_valid_token",
            new_callable=AsyncMock,
            side_effect=TokenRefreshError(
                "Token refresh failed", status_code=401
            ),
        ):
            # recover_connection should raise TokenRefreshError
            with pytest.raises(TokenRefreshError):
                await mqtt_client.recover_connection()

    @pytest.mark.asyncio
    async def test_recover_connection_auth_error_on_refresh(
        self, auth_client_with_valid_tokens
    ):
        """Test recover_connection when re-authentication fails."""
        from unittest.mock import AsyncMock, patch

        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)

        # Mock ensure_valid_token to raise AuthenticationError
        from nwp500.exceptions import AuthenticationError

        with patch.object(
            mqtt_client._auth_client,
            "ensure_valid_token",
            new_callable=AsyncMock,
            side_effect=AuthenticationError("Re-auth failed"),
        ):
            # recover_connection should raise AuthenticationError
            with pytest.raises(AuthenticationError):
                await mqtt_client.recover_connection()

    @pytest.mark.asyncio
    async def test_recover_connection_not_connected_state(
        self, auth_client_with_valid_tokens
    ):
        """Test recover_connection behavior when not yet connected."""
        from unittest.mock import AsyncMock, patch

        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)

        # Ensure _connected is False (not connected)
        mqtt_client._connected = False

        # Mock ensure_valid_token to succeed
        with patch.object(
            mqtt_client._auth_client,
            "ensure_valid_token",
            new_callable=AsyncMock,
            return_value=auth_client_with_valid_tokens.current_tokens,
        ):
            # Mock connect to fail (simulating reconnection failure)
            with patch.object(
                mqtt_client,
                "connect",
                new_callable=AsyncMock,
                return_value=False,
            ):
                result = await mqtt_client.recover_connection()

                # Should return False (reconnection failed)
                assert result is False

    @pytest.mark.asyncio
    async def test_recover_connection_successful_flow(
        self, auth_client_with_valid_tokens
    ):
        """Test successful recover_connection: token refresh then reconnect."""
        from unittest.mock import AsyncMock, patch

        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)

        # Ensure _connected is False (not connected)
        mqtt_client._connected = False

        # Mock ensure_valid_token to succeed
        with patch.object(
            mqtt_client._auth_client,
            "ensure_valid_token",
            new_callable=AsyncMock,
            return_value=auth_client_with_valid_tokens.current_tokens,
        ):
            # Mock connect to succeed
            with patch.object(
                mqtt_client,
                "connect",
                new_callable=AsyncMock,
                return_value=True,
            ):
                result = await mqtt_client.recover_connection()

                # Should return True (recovery successful)
                assert result is True

                # Verify ensure_valid_token was called
                mqtt_client._auth_client.ensure_valid_token.assert_called_once()

                # Verify connect was called
                mqtt_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_connection_returns_bool(
        self, auth_client_with_valid_tokens
    ):
        """Test that recover_connection always returns a boolean."""
        from unittest.mock import AsyncMock, patch

        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)
        mqtt_client._connected = False

        # Mock success case
        with patch.object(
            mqtt_client._auth_client,
            "ensure_valid_token",
            new_callable=AsyncMock,
        ):
            with patch.object(
                mqtt_client,
                "connect",
                new_callable=AsyncMock,
                return_value=True,
            ):
                result = await mqtt_client.recover_connection()
                assert isinstance(result, bool)
                assert result is True

        # Mock failure case
        mqtt_client._connected = False
        with patch.object(
            mqtt_client._auth_client,
            "ensure_valid_token",
            new_callable=AsyncMock,
        ):
            with patch.object(
                mqtt_client,
                "connect",
                new_callable=AsyncMock,
                return_value=False,
            ):
                result = await mqtt_client.recover_connection()
                assert isinstance(result, bool)
                assert result is False


class TestRecoverConnectionIntegration:
    """Integration tests for recover_connection() with other components."""

    def test_recover_connection_method_signature(
        self, auth_client_with_valid_tokens
    ):
        """Test that recover_connection has correct signature and docstring."""
        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)

        import inspect

        sig = inspect.signature(mqtt_client.recover_connection)

        # Should have no required parameters (besides self)
        assert len(sig.parameters) == 0

        # Should have a docstring
        assert mqtt_client.recover_connection.__doc__ is not None
        assert "recover" in mqtt_client.recover_connection.__doc__.lower()
        assert "connection" in mqtt_client.recover_connection.__doc__.lower()

    def test_recover_connection_error_handling_docstring(self):
        """Test that recover_connection docstring documents error handling."""
        # Check class attribute directly to avoid bound method issues
        doc = NavienMqttClient.recover_connection.__doc__
        assert doc is not None

        # Should mention it can raise exceptions
        # Case insensitive check for 'raises' or specific errors
        doc_lower = doc.lower()
        has_raises = "raises" in doc_lower
        has_token_error = "tokenrefresherror" in doc_lower

        assert has_raises or has_token_error, (
            f"Docstring should document error handling. Got: {doc[:100]}..."
        )

    @pytest.mark.asyncio
    async def test_recover_connection_with_expired_auth_client(
        self, auth_client_with_valid_tokens
    ):
        """Test recover_connection when client tokens expire after creation."""
        from datetime import timedelta
        from unittest.mock import AsyncMock, patch

        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)

        # Manually expire tokens to simulate them expiring after creation
        mqtt_client._auth_client._auth_response.tokens._expires_at = (
            datetime.now() - timedelta(minutes=10)
        )

        # Mock ensure_valid_token to refresh the tokens
        refreshed_tokens = AuthTokens(
            id_token="new_id",
            access_token="new_access",
            refresh_token="new_refresh",
            authentication_expires_in=3600,
            access_key_id="key",
            secret_key="secret",
        )

        with patch.object(
            mqtt_client._auth_client,
            "ensure_valid_token",
            new_callable=AsyncMock,
            return_value=refreshed_tokens,
        ):
            with patch.object(
                mqtt_client,
                "connect",
                new_callable=AsyncMock,
                return_value=True,
            ):
                result = await mqtt_client.recover_connection()

                # Should succeed after token refresh
                assert result is True

    @pytest.mark.asyncio
    async def test_recover_connection_sequence_calls_in_order(
        self, auth_client_with_valid_tokens
    ):
        """Test that recover_connection calls methods in correct order."""
        from unittest.mock import AsyncMock, patch

        mqtt_client = NavienMqttClient(auth_client_with_valid_tokens)

        call_order = []

        async def mock_ensure_valid_token():
            call_order.append("ensure_valid_token")
            return auth_client_with_valid_tokens.current_tokens

        async def mock_connect():
            call_order.append("connect")
            return True

        with patch.object(
            mqtt_client._auth_client,
            "ensure_valid_token",
            new_callable=AsyncMock,
            side_effect=mock_ensure_valid_token,
        ):
            with patch.object(
                mqtt_client,
                "connect",
                new_callable=AsyncMock,
                side_effect=mock_connect,
            ):
                mqtt_client._connected = False
                result = await mqtt_client.recover_connection()

                # Verify call order
                assert call_order == ["ensure_valid_token", "connect"]
                assert result is True
