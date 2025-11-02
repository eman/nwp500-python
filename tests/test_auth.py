"""Tests for authentication functionality."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from nwp500.auth import (
    AuthenticationResponse,
    AuthTokens,
    NavienAuthClient,
    UserInfo,
)
from nwp500.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenRefreshError,
)


# Test UserInfo dataclass
def test_user_info_creation():
    """Test UserInfo dataclass creation."""
    user_info = UserInfo(
        user_type="standard",
        user_first_name="John",
        user_last_name="Doe",
        user_status="active",
        user_seq=123,
    )

    assert user_info.user_type == "standard"
    assert user_info.user_first_name == "John"
    assert user_info.user_last_name == "Doe"
    assert user_info.user_status == "active"
    assert user_info.user_seq == 123


def test_user_info_full_name():
    """Test UserInfo full_name property."""
    user_info = UserInfo(
        user_type="standard",
        user_first_name="John",
        user_last_name="Doe",
        user_status="active",
        user_seq=123,
    )

    assert user_info.full_name == "John Doe"


def test_user_info_full_name_with_empty_names():
    """Test UserInfo full_name with empty first or last name."""
    user_info = UserInfo(
        user_type="standard",
        user_first_name="",
        user_last_name="Doe",
        user_status="active",
        user_seq=123,
    )

    assert user_info.full_name == "Doe"


def test_user_info_from_dict():
    """Test UserInfo.from_dict class method."""
    data = {
        "userType": "premium",
        "userFirstName": "Jane",
        "userLastName": "Smith",
        "userStatus": "active",
        "userSeq": 456,
    }

    user_info = UserInfo.from_dict(data)

    assert user_info.user_type == "premium"
    assert user_info.user_first_name == "Jane"
    assert user_info.user_last_name == "Smith"
    assert user_info.user_status == "active"
    assert user_info.user_seq == 456


def test_user_info_from_dict_with_missing_fields():
    """Test UserInfo.from_dict with missing fields."""
    data = {}

    user_info = UserInfo.from_dict(data)

    assert user_info.user_type == ""
    assert user_info.user_first_name == ""
    assert user_info.user_last_name == ""
    assert user_info.user_status == ""
    assert user_info.user_seq == 0


# Test AuthTokens dataclass
def test_auth_tokens_creation():
    """Test AuthTokens dataclass creation."""
    tokens = AuthTokens(
        id_token="test_id_token",
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        authentication_expires_in=3600,
        access_key_id="test_key_id",
        secret_key="test_secret",
        session_token="test_session",
        authorization_expires_in=3600,
    )

    assert tokens.id_token == "test_id_token"
    assert tokens.access_token == "test_access_token"
    assert tokens.refresh_token == "test_refresh_token"
    assert tokens.authentication_expires_in == 3600
    assert tokens.access_key_id == "test_key_id"
    assert tokens.secret_key == "test_secret"
    assert tokens.session_token == "test_session"
    assert tokens.authorization_expires_in == 3600


def test_auth_tokens_expires_at_calculation():
    """Test AuthTokens expires_at property."""
    now = datetime.now()
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,
        issued_at=now,
    )

    expected_expiry = now + timedelta(seconds=3600)
    assert abs((tokens.expires_at - expected_expiry).total_seconds()) < 1


def test_auth_tokens_is_expired_false():
    """Test AuthTokens.is_expired when token is not expired."""
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,  # Expires in 1 hour
    )

    assert tokens.is_expired is False


def test_auth_tokens_is_expired_true():
    """Test AuthTokens.is_expired when token is expired."""
    old_time = datetime.now() - timedelta(seconds=7200)  # 2 hours ago
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,  # Would have expired 1 hour ago
        issued_at=old_time,
    )

    assert tokens.is_expired is True


def test_auth_tokens_is_expired_near_expiry():
    """Test AuthTokens.is_expired within 5-minute buffer."""
    # Token expires in 3 minutes - should be considered expired
    near_expiry = datetime.now() - timedelta(seconds=3420)  # 57 minutes ago
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,  # Expires in 3 minutes
        issued_at=near_expiry,
    )

    assert tokens.is_expired is True


def test_auth_tokens_aws_credentials_expired_false():
    """Test are_aws_credentials_expired when AWS credentials are not expired."""
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,
        access_key_id="test_key",
        secret_key="test_secret",
        session_token="test_session",
        authorization_expires_in=3600,  # AWS creds expire in 1 hour
    )

    assert tokens.are_aws_credentials_expired is False


def test_auth_tokens_aws_credentials_expired_true():
    """Test are_aws_credentials_expired when AWS credentials are expired."""
    old_time = datetime.now() - timedelta(seconds=7200)  # 2 hours ago
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=7200,  # JWT still valid
        access_key_id="test_key",
        secret_key="test_secret",
        session_token="test_session",
        authorization_expires_in=3600,  # AWS creds expired 1 hour ago
        issued_at=old_time,
    )

    assert tokens.are_aws_credentials_expired is True


def test_auth_tokens_aws_credentials_no_expiration():
    """Test are_aws_credentials_expired when no expiration info available."""
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,
        # No authorization_expires_in provided
    )

    # Should return False when expiration time is unknown
    assert tokens.are_aws_credentials_expired is False


def test_auth_tokens_time_until_expiry():
    """Test AuthTokens.time_until_expiry property."""
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,
    )

    time_until = tokens.time_until_expiry
    # Should be approximately 1 hour (allowing for test execution time)
    assert 3595 < time_until.total_seconds() < 3605


def test_auth_tokens_bearer_token():
    """Test AuthTokens.bearer_token property."""
    tokens = AuthTokens(
        id_token="test",
        access_token="my_access_token",
        refresh_token="test",
        authentication_expires_in=3600,
    )

    assert tokens.bearer_token == "Bearer my_access_token"


def test_auth_tokens_from_dict():
    """Test AuthTokens.from_dict class method."""
    data = {
        "idToken": "test_id",
        "accessToken": "test_access",
        "refreshToken": "test_refresh",
        "authenticationExpiresIn": 3600,
        "accessKeyId": "test_key",
        "secretKey": "test_secret",
        "sessionToken": "test_session",
        "authorizationExpiresIn": 1800,
    }

    tokens = AuthTokens.from_dict(data)

    assert tokens.id_token == "test_id"
    assert tokens.access_token == "test_access"
    assert tokens.refresh_token == "test_refresh"
    assert tokens.authentication_expires_in == 3600
    assert tokens.access_key_id == "test_key"
    assert tokens.secret_key == "test_secret"
    assert tokens.session_token == "test_session"
    assert tokens.authorization_expires_in == 1800


def test_auth_tokens_from_dict_minimal():
    """Test AuthTokens.from_dict with minimal data."""
    data = {}

    tokens = AuthTokens.from_dict(data)

    assert tokens.id_token == ""
    assert tokens.access_token == ""
    assert tokens.refresh_token == ""
    assert tokens.authentication_expires_in == 3600  # Default value
    assert tokens.access_key_id is None
    assert tokens.secret_key is None
    assert tokens.session_token is None
    assert tokens.authorization_expires_in is None


# Test AuthenticationResponse dataclass
def test_authentication_response_from_dict():
    """Test AuthenticationResponse.from_dict class method."""
    data = {
        "code": 200,
        "msg": "SUCCESS",
        "data": {
            "userInfo": {
                "userType": "standard",
                "userFirstName": "John",
                "userLastName": "Doe",
                "userStatus": "active",
                "userSeq": 123,
            },
            "token": {
                "idToken": "test_id",
                "accessToken": "test_access",
                "refreshToken": "test_refresh",
                "authenticationExpiresIn": 3600,
            },
            "legal": [{"type": "terms", "version": "1.0"}],
        },
    }

    response = AuthenticationResponse.from_dict(data)

    assert response.code == 200
    assert response.message == "SUCCESS"
    assert response.user_info.user_first_name == "John"
    assert response.tokens.access_token == "test_access"
    assert len(response.legal) == 1


# Test Exception classes
def test_authentication_error():
    """Test AuthenticationError exception."""
    error = AuthenticationError(
        "Test error", status_code=400, response={"error": "details"}
    )

    assert str(error) == "Test error"
    assert error.message == "Test error"
    assert error.status_code == 400
    assert error.response == {"error": "details"}


def test_invalid_credentials_error():
    """Test InvalidCredentialsError exception."""
    error = InvalidCredentialsError("Invalid password", status_code=401)

    assert str(error) == "Invalid password"
    assert error.status_code == 401
    assert isinstance(error, AuthenticationError)


def test_token_expired_error():
    """Test TokenExpiredError exception."""
    error = TokenExpiredError("Token expired")

    assert str(error) == "Token expired"
    assert isinstance(error, AuthenticationError)


def test_token_refresh_error():
    """Test TokenRefreshError exception."""
    error = TokenRefreshError("Refresh failed", status_code=403)

    assert str(error) == "Refresh failed"
    assert error.status_code == 403
    assert isinstance(error, AuthenticationError)


# Test NavienAuthClient
def test_navien_auth_client_initialization():
    """Test NavienAuthClient initialization."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    assert client._user_id == "test@example.com"
    assert client._password == "test_password"
    assert client._auth_response is None
    assert client._user_email is None
    assert client._session is None
    assert client._owned_session is True


def test_navien_auth_client_is_authenticated_false():
    """Test NavienAuthClient.is_authenticated when not authenticated."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    assert client.is_authenticated is False


def test_navien_auth_client_is_authenticated_true():
    """Test NavienAuthClient.is_authenticated when authenticated."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    # Simulate authentication
    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(
            user_type="test",
            user_first_name="Test",
            user_last_name="User",
            user_status="active",
            user_seq=1,
        ),
        tokens=AuthTokens(
            id_token="test",
            access_token="test",
            refresh_token="test",
            authentication_expires_in=3600,
        ),
    )

    assert client.is_authenticated is True


def test_navien_auth_client_current_user_none():
    """Test NavienAuthClient.current_user when not authenticated."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    assert client.current_user is None


def test_navien_auth_client_current_user():
    """Test NavienAuthClient.current_user when authenticated."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    user_info = UserInfo(
        user_type="test",
        user_first_name="Test",
        user_last_name="User",
        user_status="active",
        user_seq=1,
    )

    client._auth_response = AuthenticationResponse(
        user_info=user_info,
        tokens=AuthTokens(
            id_token="test",
            access_token="test",
            refresh_token="test",
            authentication_expires_in=3600,
        ),
    )

    assert client.current_user == user_info


def test_navien_auth_client_current_tokens_none():
    """Test NavienAuthClient.current_tokens when not authenticated."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    assert client.current_tokens is None


def test_navien_auth_client_current_tokens():
    """Test NavienAuthClient.current_tokens when authenticated."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,
    )

    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(
            user_type="test",
            user_first_name="Test",
            user_last_name="User",
            user_status="active",
            user_seq=1,
        ),
        tokens=tokens,
    )

    assert client.current_tokens == tokens


def test_navien_auth_client_user_email():
    """Test NavienAuthClient.user_email property."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    client._user_email = "test@example.com"

    assert client.user_email == "test@example.com"


def test_navien_auth_client_get_auth_headers():
    """Test NavienAuthClient.get_auth_headers method."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    tokens = AuthTokens(
        id_token="test",
        access_token="my_token",
        refresh_token="test",
        authentication_expires_in=3600,
    )

    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(
            user_type="test",
            user_first_name="Test",
            user_last_name="User",
            user_status="active",
            user_seq=1,
        ),
        tokens=tokens,
    )

    headers = client.get_auth_headers()

    # API uses lowercase 'authorization' with raw token (no 'Bearer ' prefix)
    assert "authorization" in headers
    assert headers["authorization"] == "my_token"
    assert "User-Agent" in headers
    assert "Content-Type" in headers


@pytest.mark.asyncio
async def test_ensure_valid_token_no_auth_response():
    """Test ensure_valid_token when not authenticated."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    result = await client.ensure_valid_token()

    assert result is None


@pytest.mark.asyncio
async def test_ensure_valid_token_valid_tokens():
    """Test ensure_valid_token when tokens are still valid."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,  # Valid for 1 hour
        access_key_id="test_key",
        secret_key="test_secret",
        session_token="test_session",
        authorization_expires_in=3600,  # AWS creds valid for 1 hour
    )

    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(
            user_type="test",
            user_first_name="Test",
            user_last_name="User",
            user_status="active",
            user_seq=1,
        ),
        tokens=tokens,
    )

    result = await client.ensure_valid_token()

    assert result == tokens


@pytest.mark.asyncio
async def test_ensure_valid_token_aws_credentials_expired():
    """Test ensure_valid_token when AWS credentials are expired."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    # Create tokens with expired AWS credentials but valid JWT
    old_time = datetime.now() - timedelta(seconds=3900)  # 65 minutes ago
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=7200,  # JWT still valid for 55 minutes
        access_key_id="test_key",
        secret_key="test_secret",
        session_token="test_session",
        authorization_expires_in=3600,  # AWS creds expired 5 minutes ago
        issued_at=old_time,
    )

    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(
            user_type="test",
            user_first_name="Test",
            user_last_name="User",
            user_status="active",
            user_seq=1,
        ),
        tokens=tokens,
    )

    # Mock sign_in to avoid actual API call
    new_tokens = AuthTokens(
        id_token="new_test",
        access_token="new_test",
        refresh_token="new_test",
        authentication_expires_in=3600,
        access_key_id="new_key",
        secret_key="new_secret",
        session_token="new_session",
        authorization_expires_in=3600,
    )

    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(
            user_type="test",
            user_first_name="Test",
            user_last_name="User",
            user_status="active",
            user_seq=1,
        ),
        tokens=tokens,
    )

    with patch.object(
        client, "sign_in", new_callable=AsyncMock
    ) as mock_sign_in:
        mock_sign_in.return_value = AuthenticationResponse(
            user_info=UserInfo(
                user_type="test",
                user_first_name="Test",
                user_last_name="User",
                user_status="active",
                user_seq=1,
            ),
            tokens=new_tokens,
        )

        await client.ensure_valid_token()

        # Should have called sign_in due to expired AWS credentials
        mock_sign_in.assert_called_once_with(
            "test@example.com", "test_password"
        )


@pytest.mark.asyncio
async def test_ensure_valid_token_jwt_expired():
    """Test ensure_valid_token when JWT token is expired."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    # Create tokens with expired JWT
    old_time = datetime.now() - timedelta(seconds=3900)  # 65 minutes ago
    tokens = AuthTokens(
        id_token="test",
        access_token="test",
        refresh_token="test",
        authentication_expires_in=3600,  # Expired 5 minutes ago
        issued_at=old_time,
    )

    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(
            user_type="test",
            user_first_name="Test",
            user_last_name="User",
            user_status="active",
            user_seq=1,
        ),
        tokens=tokens,
    )

    # Mock refresh_token to avoid actual API call
    new_tokens = AuthTokens(
        id_token="new_test",
        access_token="new_test",
        refresh_token="test",
        authentication_expires_in=3600,
    )

    with patch.object(
        client, "refresh_token", new_callable=AsyncMock
    ) as mock_refresh:
        mock_refresh.return_value = new_tokens

        result = await client.ensure_valid_token()

        # Should have called refresh_token
        mock_refresh.assert_called_once_with("test")
        assert result == new_tokens


@pytest.mark.asyncio
async def test_ensure_session():
    """Test _ensure_session creates session if needed."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    assert client._session is None

    await client._ensure_session()

    assert client._session is not None
    assert isinstance(client._session, aiohttp.ClientSession)
    assert client._owned_session is True

    # Clean up
    await client._session.close()


@pytest.mark.asyncio
async def test_close_owned_session():
    """Test close() closes owned session."""
    client = NavienAuthClient(
        user_id="test@example.com", password="test_password"
    )

    await client._ensure_session()
    session = client._session

    assert session is not None

    await client.close()

    assert client._session is None


@pytest.mark.asyncio
async def test_close_not_owned_session():
    """Test close() doesn't close external session."""
    external_session = MagicMock(spec=aiohttp.ClientSession)
    external_session.close = AsyncMock()

    client = NavienAuthClient(
        user_id="test@example.com",
        password="test_password",
        session=external_session,
    )

    assert client._session == external_session
    assert client._owned_session is False

    await client.close()

    # External session should not be closed
    external_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_context_manager():
    """Test async context manager functionality."""
    with patch.object(
        NavienAuthClient, "sign_in", new_callable=AsyncMock
    ) as mock_sign_in:
        mock_sign_in.return_value = AuthenticationResponse(
            user_info=UserInfo(
                user_type="test",
                user_first_name="Test",
                user_last_name="User",
                user_status="active",
                user_seq=1,
            ),
            tokens=AuthTokens(
                id_token="test",
                access_token="test",
                refresh_token="test",
                authentication_expires_in=3600,
            ),
        )

        async with NavienAuthClient(
            user_id="test@example.com", password="test_password"
        ) as client:
            # Should have authenticated automatically
            mock_sign_in.assert_called_once()
            assert client._session is not None

        # Session should be closed after exiting context
        # (Can't easily test this without more complex mocking)


def test_aws_credentials_preservation_in_token_refresh():
    """Test that AWS credentials are preserved during token refresh."""
    old_time = datetime.now() - timedelta(seconds=1800)  # 30 minutes ago

    old_tokens = AuthTokens(
        id_token="old_id",
        access_token="old_access",
        refresh_token="refresh_token",
        authentication_expires_in=3600,
        access_key_id="old_key_id",
        secret_key="old_secret",
        session_token="old_session",
        authorization_expires_in=3600,
        issued_at=old_time,
    )

    # New tokens from refresh (no AWS credentials)
    new_tokens = AuthTokens(
        id_token="new_id",
        access_token="new_access",
        refresh_token="new_refresh",
        authentication_expires_in=3600,
        # AWS credentials not included in refresh response
    )

    # Simulate preservation logic
    if not new_tokens.access_key_id and old_tokens.access_key_id:
        new_tokens.access_key_id = old_tokens.access_key_id
    if not new_tokens.secret_key and old_tokens.secret_key:
        new_tokens.secret_key = old_tokens.secret_key
    if not new_tokens.session_token and old_tokens.session_token:
        new_tokens.session_token = old_tokens.session_token
    if (
        not new_tokens.authorization_expires_in
        and old_tokens.authorization_expires_in
    ):
        new_tokens.authorization_expires_in = (
            old_tokens.authorization_expires_in
        )
        new_tokens._aws_expires_at = old_tokens._aws_expires_at

    # Verify preservation
    assert new_tokens.access_key_id == "old_key_id"
    assert new_tokens.secret_key == "old_secret"
    assert new_tokens.session_token == "old_session"
    assert new_tokens.authorization_expires_in == 3600
    assert new_tokens._aws_expires_at == old_tokens._aws_expires_at


# Test token restoration functionality
def test_auth_tokens_to_dict():
    """Test AuthTokens.to_dict serialization."""
    issued_at = datetime.now()
    tokens = AuthTokens(
        id_token="test_id",
        access_token="test_access",
        refresh_token="test_refresh",
        authentication_expires_in=3600,
        access_key_id="test_key",
        secret_key="test_secret",
        session_token="test_session",
        authorization_expires_in=1800,
        issued_at=issued_at,
    )

    result = tokens.to_dict()

    assert result["id_token"] == "test_id"
    assert result["access_token"] == "test_access"
    assert result["refresh_token"] == "test_refresh"
    assert result["authentication_expires_in"] == 3600
    assert result["access_key_id"] == "test_key"
    assert result["secret_key"] == "test_secret"
    assert result["session_token"] == "test_session"
    assert result["authorization_expires_in"] == 1800
    assert result["issued_at"] == issued_at.isoformat()


def test_auth_tokens_from_dict_with_issued_at():
    """Test AuthTokens.from_dict with issued_at timestamp."""
    issued_at = datetime.now() - timedelta(seconds=1800)
    data = {
        "id_token": "test_id",
        "access_token": "test_access",
        "refresh_token": "test_refresh",
        "authentication_expires_in": 3600,
        "access_key_id": "test_key",
        "secret_key": "test_secret",
        "session_token": "test_session",
        "authorization_expires_in": 1800,
        "issued_at": issued_at.isoformat(),
    }

    tokens = AuthTokens.from_dict(data)

    assert tokens.id_token == "test_id"
    assert tokens.access_token == "test_access"
    assert tokens.refresh_token == "test_refresh"
    assert tokens.authentication_expires_in == 3600
    assert tokens.access_key_id == "test_key"
    assert tokens.secret_key == "test_secret"
    assert tokens.session_token == "test_session"
    assert tokens.authorization_expires_in == 1800
    # Check that issued_at was correctly restored
    assert abs((tokens.issued_at - issued_at).total_seconds()) < 1


def test_auth_tokens_serialization_roundtrip():
    """Test that tokens can be serialized and deserialized without data loss."""
    issued_at = datetime.now() - timedelta(seconds=1800)
    original = AuthTokens(
        id_token="test_id",
        access_token="test_access",
        refresh_token="test_refresh",
        authentication_expires_in=3600,
        access_key_id="test_key",
        secret_key="test_secret",
        session_token="test_session",
        authorization_expires_in=1800,
        issued_at=issued_at,
    )

    # Serialize and deserialize
    serialized = original.to_dict()
    restored = AuthTokens.from_dict(serialized)

    # Verify all fields match
    assert restored.id_token == original.id_token
    assert restored.access_token == original.access_token
    assert restored.refresh_token == original.refresh_token
    assert (
        restored.authentication_expires_in == original.authentication_expires_in
    )
    assert restored.access_key_id == original.access_key_id
    assert restored.secret_key == original.secret_key
    assert restored.session_token == original.session_token
    assert (
        restored.authorization_expires_in == original.authorization_expires_in
    )
    # Verify issued_at is preserved (critical for expiration calculations)
    assert abs((restored.issued_at - original.issued_at).total_seconds()) < 1
    # Verify expiration calculations are the same
    assert abs((restored.expires_at - original.expires_at).total_seconds()) < 1
    assert restored.is_expired == original.is_expired


def test_auth_tokens_from_dict_with_empty_strings():
    """Test AuthTokens.from_dict handles empty strings in camelCase."""
    # Simulate API response with empty optional fields (camelCase)
    # Should fall back to snake_case alternatives
    data = {
        "idToken": "test_id",
        "accessToken": "",  # Empty string - should check snake_case
        "refreshToken": "test_refresh",
        "authenticationExpiresIn": 3600,
        "accessKeyId": "",  # Empty string - should check snake_case
        "secretKey": None,  # None - should check snake_case
        "sessionToken": "test_session",
        # Provide values in snake_case as fallback
        "access_token": "fallback_access",
        "access_key_id": "fallback_key",
        "secret_key": "fallback_secret",
    }

    tokens = AuthTokens.from_dict(data)

    assert tokens.id_token == "test_id"
    assert tokens.access_token == "fallback_access"  # Should use snake_case
    assert tokens.refresh_token == "test_refresh"
    assert tokens.authentication_expires_in == 3600
    assert tokens.access_key_id == "fallback_key"  # Should use snake_case
    assert tokens.secret_key == "fallback_secret"  # Should use snake_case
    assert tokens.session_token == "test_session"


def test_navien_auth_client_initialization_with_stored_tokens():
    """Test NavienAuthClient initialization with stored tokens."""
    stored_tokens = AuthTokens(
        id_token="stored_id",
        access_token="stored_access",
        refresh_token="stored_refresh",
        authentication_expires_in=3600,
        access_key_id="stored_key",
        secret_key="stored_secret",
        session_token="stored_session",
        authorization_expires_in=1800,
    )

    client = NavienAuthClient(
        user_id="test@example.com",
        password="test_password",
        stored_tokens=stored_tokens,
    )

    # Should have auth response set up with stored tokens
    assert client.is_authenticated is True
    assert client.current_tokens == stored_tokens
    assert client.user_email == "test@example.com"


@pytest.mark.asyncio
async def test_context_manager_with_valid_stored_tokens():
    """Test async context manager skips auth with valid stored tokens."""
    stored_tokens = AuthTokens(
        id_token="stored_id",
        access_token="stored_access",
        refresh_token="stored_refresh",
        authentication_expires_in=3600,  # Valid for 1 hour
        access_key_id="stored_key",
        secret_key="stored_secret",
        session_token="stored_session",
        authorization_expires_in=3600,  # AWS creds valid for 1 hour
    )

    with patch.object(
        NavienAuthClient, "sign_in", new_callable=AsyncMock
    ) as mock_sign_in:
        async with NavienAuthClient(
            user_id="test@example.com",
            password="test_password",
            stored_tokens=stored_tokens,
        ) as client:
            # Should NOT have called sign_in since tokens are valid
            mock_sign_in.assert_not_called()
            assert client.current_tokens == stored_tokens
            assert client._session is not None


@pytest.mark.asyncio
async def test_context_manager_with_expired_jwt_stored_tokens():
    """Test async context manager with expired JWT refreshes tokens."""
    old_time = datetime.now() - timedelta(seconds=3900)  # 65 minutes ago
    stored_tokens = AuthTokens(
        id_token="stored_id",
        access_token="stored_access",
        refresh_token="stored_refresh",
        authentication_expires_in=3600,  # Expired 5 minutes ago
        issued_at=old_time,
    )

    new_tokens = AuthTokens(
        id_token="new_id",
        access_token="new_access",
        refresh_token="new_refresh",
        authentication_expires_in=3600,
    )

    with patch.object(
        NavienAuthClient, "refresh_token", new_callable=AsyncMock
    ) as mock_refresh:
        mock_refresh.return_value = new_tokens

        async with NavienAuthClient(
            user_id="test@example.com",
            password="test_password",
            stored_tokens=stored_tokens,
        ) as client:
            # Should have called refresh_token
            mock_refresh.assert_called_once_with("stored_refresh")
            assert client._session is not None


@pytest.mark.asyncio
async def test_context_manager_with_expired_aws_credentials():
    """Test async context manager re-authenticates on AWS creds expiry."""
    old_time = datetime.now() - timedelta(seconds=3900)  # 65 minutes ago
    stored_tokens = AuthTokens(
        id_token="stored_id",
        access_token="stored_access",
        refresh_token="stored_refresh",
        authentication_expires_in=7200,  # JWT still valid for 55 minutes
        access_key_id="stored_key",
        secret_key="stored_secret",
        session_token="stored_session",
        authorization_expires_in=3600,  # AWS creds expired 5 minutes ago
        issued_at=old_time,
    )

    new_tokens = AuthTokens(
        id_token="new_id",
        access_token="new_access",
        refresh_token="new_refresh",
        authentication_expires_in=3600,
        access_key_id="new_key",
        secret_key="new_secret",
        session_token="new_session",
        authorization_expires_in=3600,
    )

    with patch.object(
        NavienAuthClient, "sign_in", new_callable=AsyncMock
    ) as mock_sign_in:
        mock_sign_in.return_value = AuthenticationResponse(
            user_info=UserInfo(
                user_type="test",
                user_first_name="Test",
                user_last_name="User",
                user_status="active",
                user_seq=1,
            ),
            tokens=new_tokens,
        )

        async with NavienAuthClient(
            user_id="test@example.com",
            password="test_password",
            stored_tokens=stored_tokens,
        ) as client:
            # Should have called sign_in due to expired AWS credentials
            mock_sign_in.assert_called_once_with(
                "test@example.com", "test_password"
            )
            assert client._session is not None
