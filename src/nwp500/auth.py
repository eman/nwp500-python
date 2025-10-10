"""
Authentication module for Navien Smart Control API.

This module provides authentication functionality for the Navien Smart Control
REST API, including sign-in, token management, and token refresh capabilities.

The API uses JWT (JSON Web Tokens) for authentication with the following flow:
1. Sign in with email and password
2. Receive idToken, accessToken, and refreshToken
3. Use accessToken as Bearer token in subsequent requests
4. Refresh tokens when accessToken expires
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp

from .config import API_BASE_URL, REFRESH_ENDPOINT, SIGN_IN_ENDPOINT

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


@dataclass
class UserInfo:
    """User information returned from authentication."""

    user_type: str
    user_first_name: str
    user_last_name: str
    user_status: str
    user_seq: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserInfo":
        """Create UserInfo from API response dictionary."""
        return cls(
            user_type=data.get("userType", ""),
            user_first_name=data.get("userFirstName", ""),
            user_last_name=data.get("userLastName", ""),
            user_status=data.get("userStatus", ""),
            user_seq=data.get("userSeq", 0),
        )

    @property
    def full_name(self) -> str:
        """Return the user's full name."""
        return f"{self.user_first_name} {self.user_last_name}".strip()


@dataclass
class AuthTokens:
    """Authentication tokens and AWS credentials returned from the API."""

    id_token: str
    access_token: str
    refresh_token: str
    authentication_expires_in: int
    access_key_id: Optional[str] = None
    secret_key: Optional[str] = None
    session_token: Optional[str] = None
    authorization_expires_in: Optional[int] = None

    # Calculated fields
    issued_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthTokens":
        """Create AuthTokens from API response dictionary."""
        return cls(
            id_token=data.get("idToken", ""),
            access_token=data.get("accessToken", ""),
            refresh_token=data.get("refreshToken", ""),
            authentication_expires_in=data.get("authenticationExpiresIn", 3600),
            access_key_id=data.get("accessKeyId"),
            secret_key=data.get("secretKey"),
            session_token=data.get("sessionToken"),
            authorization_expires_in=data.get("authorizationExpiresIn"),
        )

    @property
    def expires_at(self) -> datetime:
        """Calculate when the access token expires."""
        return self.issued_at + timedelta(seconds=self.authentication_expires_in)

    @property
    def is_expired(self) -> bool:
        """Check if the access token has expired."""
        # Consider expired if within 5 minutes of expiration
        return datetime.now() >= (self.expires_at - timedelta(minutes=5))

    @property
    def time_until_expiry(self) -> timedelta:
        """Get the time remaining until token expiration."""
        return self.expires_at - datetime.now()

    @property
    def bearer_token(self) -> str:
        """Get the formatted Bearer token for Authorization header."""
        return f"Bearer {self.access_token}"


@dataclass
class AuthenticationResponse:
    """Complete authentication response including user info and tokens."""

    user_info: UserInfo
    tokens: AuthTokens
    legal: list[dict[str, Any]] = field(default_factory=list)
    code: int = 200
    message: str = "SUCCESS"

    @classmethod
    def from_dict(cls, response_data: dict[str, Any]) -> "AuthenticationResponse":
        """Create AuthenticationResponse from API response."""
        code = response_data.get("code", 200)
        message = response_data.get("msg", "SUCCESS")
        data = response_data.get("data", {})

        user_info = UserInfo.from_dict(data.get("userInfo", {}))
        tokens = AuthTokens.from_dict(data.get("token", {}))
        legal = data.get("legal", [])

        return cls(
            user_info=user_info,
            tokens=tokens,
            legal=legal,
            code=code,
            message=message,
        )


class AuthenticationError(Exception):
    """Base exception for authentication errors."""

    def __init__(
        self,
        message: str,
        code: Optional[int] = None,
        response: Optional[dict] = None,
    ):
        self.message = message
        self.code = code
        self.response = response
        super().__init__(self.message)


class InvalidCredentialsError(AuthenticationError):
    """Raised when credentials are invalid."""

    pass


class TokenExpiredError(AuthenticationError):
    """Raised when a token has expired."""

    pass


class TokenRefreshError(AuthenticationError):
    """Raised when token refresh fails."""

    pass


class NavienAuthClient:
    """
    Asynchronous client for Navien Smart Control API authentication.

    This client handles:
    - User authentication with email/password
    - Token management and automatic refresh
    - Session management
    - AWS credentials (if provided by API)

    Authentication is performed automatically when entering the async context manager.

    Example:
        >>> async with NavienAuthClient(user_id="user@example.com", password="password") as client:
        ...     print(f"Welcome {client.current_user.full_name}")
        ...     print(f"Access token: {client.current_tokens.access_token}")
        ...
        ...     # Use the token in API requests
        ...     headers = client.get_auth_headers()
        ...
        ...     # Refresh when needed
        ...     if client.current_tokens.is_expired:
        ...         new_tokens = await client.refresh_token(client.current_tokens.refresh_token)
    """

    def __init__(
        self,
        user_id: str,
        password: str,
        base_url: str = API_BASE_URL,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: int = 30,
    ):
        """
        Initialize the authentication client.

        Args:
            user_id: User email address
            password: User password
            base_url: Base URL for the API (default: official Navien API)
            session: Optional aiohttp ClientSession to use
            timeout: Request timeout in seconds

        Note:
            Authentication is performed automatically when entering the
            async context manager (using async with statement).
        """
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._owned_session = session is None
        self.timeout = aiohttp.ClientTimeout(total=timeout)

        # Store credentials for automatic authentication
        self._user_id = user_id
        self._password = password

        # Current authentication state
        self._auth_response: Optional[AuthenticationResponse] = None
        self._user_email: Optional[str] = None

    async def __aenter__(self):
        """Async context manager entry."""
        if self._owned_session:
            self._session = aiohttp.ClientSession(timeout=self.timeout)

        # Automatically authenticate
        await self.sign_in(self._user_id, self._password)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._owned_session and self._session:
            await self._session.close()

    async def _ensure_session(self):
        """Ensure we have an active session."""
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
            self._owned_session = True

    async def sign_in(self, user_id: str, password: str) -> AuthenticationResponse:
        """
        Authenticate user and obtain tokens.

        Args:
            user_id: User email address
            password: User password

        Returns:
            AuthenticationResponse containing user info and tokens

        Raises:
            InvalidCredentialsError: If credentials are invalid
            AuthenticationError: If authentication fails for other reasons
        """
        await self._ensure_session()

        url = f"{self.base_url}{SIGN_IN_ENDPOINT}"
        payload = {"userId": user_id, "password": password}

        _logger.info(f"Attempting sign-in for user: {user_id}")

        try:
            async with self._session.post(url, json=payload) as response:
                response_data = await response.json()

                # Check for error responses
                code = response_data.get("code", response.status)
                msg = response_data.get("msg", "")

                if code != 200 or not response.ok:
                    _logger.error(f"Sign-in failed: {code} - {msg}")
                    if code == 401 or "invalid" in msg.lower() or "unauthorized" in msg.lower():
                        raise InvalidCredentialsError(
                            f"Invalid credentials: {msg}",
                            code=code,
                            response=response_data,
                        )
                    raise AuthenticationError(
                        f"Authentication failed: {msg}",
                        code=code,
                        response=response_data,
                    )

                # Parse successful response
                auth_response = AuthenticationResponse.from_dict(response_data)
                self._auth_response = auth_response
                self._user_email = user_id  # Store the email for later use

                _logger.info(
                    f"Successfully authenticated user: {auth_response.user_info.full_name}"
                )
                _logger.debug(f"Token expires in: {auth_response.tokens.time_until_expiry}")

                return auth_response

        except aiohttp.ClientError as e:
            _logger.error(f"Network error during sign-in: {e}")
            raise AuthenticationError(f"Network error: {str(e)}")
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            _logger.error(f"Failed to parse authentication response: {e}")
            raise AuthenticationError(f"Invalid response format: {str(e)}")

    async def refresh_token(self, refresh_token: str) -> AuthTokens:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token: The refresh token obtained from sign-in

        Returns:
            New AuthTokens with refreshed access token

        Raises:
            TokenRefreshError: If token refresh fails
        """
        await self._ensure_session()

        url = f"{self.base_url}{REFRESH_ENDPOINT}"
        payload = {"refreshToken": refresh_token}

        _logger.info("Attempting to refresh access token")

        try:
            async with self._session.post(url, json=payload) as response:
                response_data = await response.json()

                code = response_data.get("code", response.status)
                msg = response_data.get("msg", "")

                if code != 200 or not response.ok:
                    _logger.error(f"Token refresh failed: {code} - {msg}")
                    raise TokenRefreshError(
                        f"Failed to refresh token: {msg}",
                        code=code,
                        response=response_data,
                    )

                # Parse new tokens
                data = response_data.get("data", {})
                new_tokens = AuthTokens.from_dict(data)

                # Update stored auth response if we have one
                if self._auth_response:
                    self._auth_response.tokens = new_tokens

                _logger.info("Successfully refreshed access token")
                _logger.debug(f"New token expires in: {new_tokens.time_until_expiry}")

                return new_tokens

        except aiohttp.ClientError as e:
            _logger.error(f"Network error during token refresh: {e}")
            raise TokenRefreshError(f"Network error: {str(e)}")
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            _logger.error(f"Failed to parse refresh response: {e}")
            raise TokenRefreshError(f"Invalid response format: {str(e)}")

    async def ensure_valid_token(self) -> Optional[AuthTokens]:
        """
        Ensure we have a valid access token, refreshing if necessary.

        Returns:
            Valid AuthTokens or None if not authenticated

        Raises:
            TokenRefreshError: If token refresh fails
        """
        if not self._auth_response:
            _logger.warning("No authentication response available")
            return None

        if self._auth_response.tokens.is_expired:
            _logger.info("Token expired, refreshing...")
            return await self.refresh_token(self._auth_response.tokens.refresh_token)

        return self._auth_response.tokens

    @property
    def is_authenticated(self) -> bool:
        """Check if client is currently authenticated."""
        return self._auth_response is not None

    @property
    def current_user(self) -> Optional[UserInfo]:
        """Get current authenticated user info."""
        return self._auth_response.user_info if self._auth_response else None

    @property
    def current_tokens(self) -> Optional[AuthTokens]:
        """Get current authentication tokens."""
        return self._auth_response.tokens if self._auth_response else None

    @property
    def user_email(self) -> Optional[str]:
        """Get the email address of the authenticated user."""
        return self._user_email

    async def close(self):
        """Close the client session."""
        if self._owned_session and self._session:
            await self._session.close()
            self._session = None

    def get_auth_headers(self) -> dict[str, str]:
        """
        Get headers for authenticated requests.

        Returns:
            Dictionary of headers to include in requests

        Note:
            Based on HAR analysis of actual API traffic, the authorization
            header uses the raw token without 'Bearer ' prefix (lowercase 'authorization').
            This is different from standard Bearer token authentication.
        """
        headers = {
            "User-Agent": "NaviLink-Python/1.0.0",
            "Content-Type": "application/json",
        }

        # IMPORTANT: Use lowercase 'authorization' and raw token (no 'Bearer ' prefix)
        # This matches the actual API behavior from HAR analysis in working implementation
        if self._auth_response and self._auth_response.tokens.access_token:
            headers["authorization"] = self._auth_response.tokens.access_token

        return headers


# Convenience functions for one-off authentication


async def authenticate(user_id: str, password: str) -> AuthenticationResponse:
    """
    Convenience function to authenticate and get tokens.

    Args:
        user_id: User email address
        password: User password

    Returns:
        AuthenticationResponse with user info and tokens

    Example:
        >>> response = await authenticate("user@example.com", "password")
        >>> print(response.tokens.bearer_token)
    """
    async with NavienAuthClient(user_id, password) as client:
        return client._auth_response


async def refresh_access_token(refresh_token: str) -> AuthTokens:
    """
    Convenience function to refresh an access token.

    Args:
        refresh_token: The refresh token

    Returns:
        New AuthTokens

    Example:
        >>> new_tokens = await refresh_access_token(old_tokens.refresh_token)

    Note:
        This function creates a temporary client without authentication to
        perform the token refresh operation.
    """
    url = f"{API_BASE_URL}{REFRESH_ENDPOINT}"
    payload = {"refreshToken": refresh_token}

    async with (
        aiohttp.ClientSession() as session,
        session.post(url, json=payload) as response,
    ):
        response_data = await response.json()

        code = response_data.get("code", response.status)
        msg = response_data.get("msg", "")

        if code != 200 or not response.ok:
            raise TokenRefreshError(
                f"Failed to refresh token: {msg}",
                code=code,
                response=response_data,
            )

        data = response_data.get("data", {})
        return AuthTokens.from_dict(data)
