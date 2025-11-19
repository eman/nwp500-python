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
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator
from pydantic.alias_generators import to_camel

from . import __version__
from .config import API_BASE_URL, REFRESH_ENDPOINT, SIGN_IN_ENDPOINT
from .exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    TokenRefreshError,
)

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


class NavienBaseModel(BaseModel):
    """Base model for Navien authentication models."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="ignore"
    )


class UserInfo(NavienBaseModel):
    """User information returned from authentication."""

    user_type: str = ""
    user_first_name: str = ""
    user_last_name: str = ""
    user_status: str = ""
    user_seq: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserInfo":
        """Create UserInfo from API response dictionary (compatibility)."""
        return cls.model_validate(data)

    @property
    def full_name(self) -> str:
        """Return the user's full name."""
        return f"{self.user_first_name} {self.user_last_name}".strip()


class AuthTokens(NavienBaseModel):
    """Authentication tokens and AWS credentials returned from the API."""

    id_token: str = ""
    access_token: str = ""
    refresh_token: str = ""
    authentication_expires_in: int = 3600
    access_key_id: Optional[str] = None
    secret_key: Optional[str] = None
    session_token: Optional[str] = None
    authorization_expires_in: Optional[int] = None

    # Calculated fields
    issued_at: datetime = Field(default_factory=datetime.now)

    _expires_at: datetime = PrivateAttr()
    _aws_expires_at: Optional[datetime] = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def handle_empty_aliases(cls, data: Any) -> Any:
        """Handle empty camelCase aliases with snake_case fallbacks."""
        if isinstance(data, dict):
            # Fields to check for fallback
            fields_to_check = [
                ("accessToken", "access_token"),
                ("accessKeyId", "access_key_id"),
                ("secretKey", "secret_key"),
                ("refreshToken", "refresh_token"),
                ("sessionToken", "session_token"),
                ("authenticationExpiresIn", "authentication_expires_in"),
                ("authorizationExpiresIn", "authorization_expires_in"),
                ("idToken", "id_token"),
            ]

            for camel, snake in fields_to_check:
                # If camel exists but is empty/None, and snake exists, use snake
                if camel in data and not data[camel] and snake in data:
                    data[camel] = data[snake]
        return data

    def model_post_init(self, __context: Any) -> None:
        """Cache the expiration timestamp after initialization."""
        # Pre-calculate and cache the expiration time
        self._expires_at = self.issued_at + timedelta(
            seconds=self.authentication_expires_in
        )
        # Calculate AWS credentials expiration if available
        if self.authorization_expires_in:
            self._aws_expires_at = self.issued_at + timedelta(
                seconds=self.authorization_expires_in
            )
        else:
            self._aws_expires_at = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthTokens":
        """Create AuthTokens from API response dictionary or stored data.

        Args:
            data: Dictionary containing token data. Can be from API response
                 (using camelCase keys) or from stored data (using snake_case
                 keys from to_dict()).

        Returns:
            AuthTokens instance
        """
        # Pydantic with populate_by_name=True handles both snake_case (stored)
        # and camelCase (API alias) automatically.
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Convert AuthTokens to a dictionary for storage.

        Returns:
            Dictionary with snake_case keys suitable for JSON serialization.
            DateTime fields are serialized to ISO 8601 format strings
            (e.g., "2025-11-19T08:51:00") for backward compatibility.
        """
        return self.model_dump(mode="json")

    @property
    def expires_at(self) -> datetime:
        """Get the cached expiration timestamp."""
        return self._expires_at

    @property
    def is_expired(self) -> bool:
        """Check if the access token has expired (cached calculation)."""
        # Consider expired if within 5 minutes of expiration
        return datetime.now() >= (self._expires_at - timedelta(minutes=5))

    @property
    def are_aws_credentials_expired(self) -> bool:
        """Check if AWS credentials have expired.

        AWS credentials have a separate expiration time from JWT tokens.
        If AWS credentials are expired, a full re-authentication is needed
        since the token refresh endpoint doesn't provide new AWS credentials.

        Returns:
            True if AWS credentials are expired, False if expiration time is
            unknown or credentials are still valid
        """
        if not self._aws_expires_at:
            # If we don't know when AWS credentials expire, consider them valid
            # This handles cases where authorization_expires_in wasn't provided
            return False
        # Consider expired if within 5 minutes of expiration
        return datetime.now() >= (self._aws_expires_at - timedelta(minutes=5))

    @property
    def time_until_expiry(self) -> timedelta:
        """Get time remaining until token expiration.

        Uses cached expiration time for efficiency.
        """
        return self._expires_at - datetime.now()

    @property
    def bearer_token(self) -> str:
        """Get the formatted Bearer token for Authorization header."""
        return f"Bearer {self.access_token}"


class AuthenticationResponse(NavienBaseModel):
    """Complete authentication response including user info and tokens."""

    user_info: UserInfo
    tokens: AuthTokens
    legal: list[dict[str, Any]] = Field(default_factory=list)
    code: int = 200
    message: str = Field(default="SUCCESS", alias="msg")

    @classmethod
    def from_dict(
        cls, response_data: dict[str, Any]
    ) -> "AuthenticationResponse":
        """Create AuthenticationResponse from API response."""
        # Map nested API response to flat model structure
        # API response: { "code": ..., "msg": ..., "data": { ... } }
        data = response_data.get("data", {})

        # Construct a dict that matches the model structure
        model_data = {
            "code": response_data.get("code", 200),
            "msg": response_data.get("msg", "SUCCESS"),
            "userInfo": data.get("userInfo", {}),
            "tokens": data.get("token", {}),
            "legal": data.get("legal", []),
        }

        return cls.model_validate(model_data)


__all__ = [
    "UserInfo",
    "AuthTokens",
    "AuthenticationResponse",
    "NavienAuthClient",
    "authenticate",
    "refresh_access_token",
]


class NavienAuthClient:
    """
    Asynchronous client for Navien Smart Control API authentication.

    This client handles:
    - User authentication with email/password
    - Token management and automatic refresh
    - Session management
    - AWS credentials (if provided by API)

    Authentication is performed automatically when entering the async context
    manager, unless valid stored tokens are provided.

    Example:
        >>> async with NavienAuthClient(user_id="user@example.com",
        password="password") as client:
        ...     print(f"Welcome {client.current_user.full_name}")
        ...     print(f"Access token: {client.current_tokens.access_token}")
        ...
        ...     # Use the token in API requests
        ...     headers = client.get_auth_headers()
        ...
        ...     # Refresh when needed
        ...     if client.current_tokens.is_expired:
        ...         new_tokens = await
        client.refresh_token(client.current_tokens.refresh_token)

        Restore session from stored tokens:
        >>> stored_tokens = AuthTokens.from_dict(saved_data)
        >>> async with NavienAuthClient(
        ...     user_id="user@example.com",
        ...     password="password",
        ...     stored_tokens=stored_tokens
        ... ) as client:
        ...     # Authentication skipped if tokens are still valid
        ...     print(f"Access token: {client.current_tokens.access_token}")
    """

    def __init__(
        self,
        user_id: str,
        password: str,
        base_url: str = API_BASE_URL,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: int = 30,
        stored_tokens: Optional[AuthTokens] = None,
    ):
        """
        Initialize the authentication client.

        Args:
            user_id: User email address
            password: User password
            base_url: Base URL for the API (default: official Navien API)
            session: Optional aiohttp ClientSession to use
            timeout: Request timeout in seconds
            stored_tokens: Previously saved tokens to restore session.
                          If provided and valid, skips initial sign_in.

        Note:
            Authentication is performed automatically when entering the
            async context manager (using async with statement), unless
            valid stored_tokens are provided.
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

        # Restore tokens if provided
        if stored_tokens:
            # Create a minimal AuthenticationResponse with stored tokens
            # UserInfo will be populated on first API call if needed
            self._auth_response = AuthenticationResponse(
                user_info=UserInfo(),
                tokens=stored_tokens,
            )
            self._user_email = user_id

    async def __aenter__(self) -> "NavienAuthClient":
        """Async context manager entry."""
        if self._owned_session:
            self._session = self._create_session()

        # Check if we have valid stored tokens
        if self._auth_response and self._auth_response.tokens:
            tokens = self._auth_response.tokens
            # If tokens are expired, refresh or re-authenticate
            if tokens.are_aws_credentials_expired:
                _logger.info(
                    "Stored AWS credentials expired, re-authenticating..."
                )
                await self.sign_in(self._user_id, self._password)
            elif tokens.is_expired:
                _logger.info("Stored JWT token expired, refreshing...")
                await self.refresh_token(tokens.refresh_token)
            else:
                _logger.info("Using stored tokens, skipping authentication")
        else:
            # No stored tokens, perform full authentication
            await self.sign_in(self._user_id, self._password)

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._owned_session and self._session:
            await self._session.close()

    def _create_session(self) -> aiohttp.ClientSession:
        """Create an aiohttp ClientSession with ThreadedResolver.

        ThreadedResolver uses Python's built-in socket module for DNS
        resolution, avoiding dependency on c-ares which can fail in
        containerized environments.

        Returns:
            aiohttp.ClientSession configured with ThreadedResolver
        """
        resolver = aiohttp.ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=resolver)
        return aiohttp.ClientSession(connector=connector, timeout=self.timeout)

    async def _ensure_session(self) -> None:
        """Ensure we have an active session."""
        if self._session is None:
            self._session = self._create_session()
            self._owned_session = True

    async def sign_in(
        self, user_id: str, password: str
    ) -> AuthenticationResponse:
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

        if self._session is None:
            raise AuthenticationError("Session not initialized")

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
                    if (
                        code == 401
                        or "invalid" in msg.lower()
                        or "unauthorized" in msg.lower()
                    ):
                        raise InvalidCredentialsError(
                            f"Invalid credentials: {msg}",
                            status_code=code,
                            response=response_data,
                        )
                    raise AuthenticationError(
                        f"Authentication failed: {msg}",
                        status_code=code,
                        response=response_data,
                    )

                # Parse successful response
                auth_response = AuthenticationResponse.from_dict(response_data)
                self._auth_response = auth_response
                self._user_email = user_id  # Store the email for later use

                _logger.info(
                    "Successfully authenticated user: %s",
                    auth_response.user_info.full_name,
                )
                _logger.debug(
                    "Token expires in: %s",
                    auth_response.tokens.time_until_expiry,
                )

                return auth_response

        except aiohttp.ClientError as e:
            _logger.error(f"Network error during sign-in: {e}")
            raise AuthenticationError(f"Network error: {str(e)}") from e
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            _logger.error(f"Failed to parse authentication response: {e}")
            raise AuthenticationError(
                f"Invalid response format: {str(e)}"
            ) from e

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

        if self._session is None:
            raise AuthenticationError("Session not initialized")

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
                        status_code=code,
                        response=response_data,
                    )

                # Parse new tokens
                data = response_data.get("data", {})
                new_tokens = AuthTokens.from_dict(data)

                # Preserve AWS credentials from old tokens if not in refresh
                # response
                if self._auth_response and self._auth_response.tokens:
                    old_tokens = self._auth_response.tokens
                    if (
                        not new_tokens.access_key_id
                        and old_tokens.access_key_id
                    ):
                        new_tokens.access_key_id = old_tokens.access_key_id
                    if not new_tokens.secret_key and old_tokens.secret_key:
                        new_tokens.secret_key = old_tokens.secret_key
                    if (
                        not new_tokens.session_token
                        and old_tokens.session_token
                    ):
                        new_tokens.session_token = old_tokens.session_token
                    if (
                        not new_tokens.authorization_expires_in
                        and old_tokens.authorization_expires_in
                    ):
                        new_tokens.authorization_expires_in = (
                            old_tokens.authorization_expires_in
                        )
                        # Also preserve the AWS expiration timestamp
                        new_tokens._aws_expires_at = old_tokens._aws_expires_at

                # Update stored auth response if we have one
                if self._auth_response:
                    self._auth_response.tokens = new_tokens

                _logger.info("Successfully refreshed access token")
                _logger.debug(
                    f"New token expires in: {new_tokens.time_until_expiry}"
                )

                return new_tokens

        except aiohttp.ClientError as e:
            _logger.error(f"Network error during token refresh: {e}")
            raise TokenRefreshError(f"Network error: {str(e)}") from e
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            _logger.error(f"Failed to parse refresh response: {e}")
            raise TokenRefreshError(f"Invalid response format: {str(e)}") from e

    async def re_authenticate(self) -> AuthenticationResponse:
        """
        Re-authenticate using stored credentials.

        This is a convenience method that uses the stored user_id and password
        from initialization to perform a fresh sign-in. Useful for recovering
        from expired tokens or connection issues.

        Returns:
            AuthenticationResponse with fresh tokens and user info

        Raises:
            ValueError: If stored credentials are not available
            AuthenticationError: If authentication fails

        Example:
            >>> client = NavienAuthClient(email, password)
            >>> await client.re_authenticate()  # Uses stored credentials
        """
        if not self.has_stored_credentials:
            raise ValueError(
                "No stored credentials available for re-authentication. "
                "Credentials must be provided during initialization."
            )

        _logger.info("Re-authenticating with stored credentials")
        return await self.sign_in(self._user_id, self._password)

    async def ensure_valid_token(self) -> Optional[AuthTokens]:
        """
        Ensure we have a valid access token, refreshing if necessary.

        This method checks both JWT token and AWS credentials expiration.
        If AWS credentials are expired, it triggers a full re-authentication
        since the token refresh endpoint doesn't provide new AWS credentials.

        Returns:
            Valid AuthTokens or None if not authenticated

        Raises:
            TokenRefreshError: If token refresh fails
            AuthenticationError: If re-authentication fails
        """
        if not self._auth_response:
            _logger.warning("No authentication response available")
            return None

        tokens = self._auth_response.tokens

        # Check if AWS credentials have expired
        if tokens.are_aws_credentials_expired:
            _logger.info("AWS credentials expired, re-authenticating...")
            # Re-authenticate to get fresh AWS credentials
            await self.sign_in(self._user_id, self._password)
            return self._auth_response.tokens if self._auth_response else None

        # Check if JWT token has expired
        if tokens.is_expired:
            _logger.info("Token expired, refreshing...")
            return await self.refresh_token(tokens.refresh_token)

        return tokens

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

    @property
    def has_stored_credentials(self) -> bool:
        """Check if user credentials are stored for re-authentication.

        Returns:
            True if both user_id and password are available for re-auth
        """
        return bool(self._user_id and self._password)

    async def close(self) -> None:
        """Close the aiohttp session if we own it."""
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
            header uses the raw token without 'Bearer ' prefix (lowercase
            'authorization').
            This is different from standard Bearer token authentication.
        """
        headers = {
            "User-Agent": f"nwp500-python/{__version__}",
            "Content-Type": "application/json",
        }

        # IMPORTANT: Use lowercase 'authorization' and raw token (no 'Bearer '
        # prefix)
        # This matches the actual API behavior from HAR analysis in working
        # implementation
        if self._auth_response and self._auth_response.tokens.access_token:
            headers["authorization"] = self._auth_response.tokens.access_token

        return headers


# Convenience functions for one-off authentication


async def authenticate(user_id: str, password: str) -> AuthenticationResponse:
    """Authenticate user and obtain tokens.

    This is a convenience function that creates a temporary auth client,
    authenticates, and returns the response.

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
        if client._auth_response is None:
            raise AuthenticationError(
                "Authentication failed: no response received"
            )
        return client._auth_response


async def refresh_access_token(refresh_token: str) -> AuthTokens:
    """Refresh an access token using a refresh token.

    This is a convenience function that creates a temporary session to
    perform the token refresh operation without requiring full authentication.

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

    # Use ThreadedResolver for reliable DNS in containerized environments
    resolver = aiohttp.ThreadedResolver()
    connector = aiohttp.TCPConnector(resolver=resolver)
    async with (
        aiohttp.ClientSession(connector=connector) as session,
        session.post(url, json=payload) as response,
    ):
        response_data = await response.json()

        code = response_data.get("code", response.status)
        msg = response_data.get("msg", "")

        if code != 200 or not response.ok:
            raise TokenRefreshError(
                f"Failed to refresh token: {msg}",
                status_code=code,
                response=response_data,
            )

        data = response_data.get("data", {})
        return AuthTokens.from_dict(data)
