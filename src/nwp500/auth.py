"""
Authentication module for Navien Smart Control API.

This module provides authentication functionality for the Navien Smart Control
REST API, including sign-in, token management, and token refresh capabilities.

The API uses JWT (JSON Web Tokens) for authentication with the following flow:

1. Sign in with email and password
2. Receive idToken, accessToken, refreshToken and AWS (SigV4) credentials
3. Send the raw accessToken in the ``authorization`` header
4. Refresh the JWT with ``/auth/refresh`` when accessToken expires
5. Renew the AWS credentials with ``/auth/session/refresh`` (or, failing
   that, ``/user/secured-sign-in``) when they expire, so a password
   sign-in is only needed as a last resort
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from typing import Any, Self, cast

import aiohttp
from pydantic import (
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from ._base import NavienBaseModel
from .config import (
    API_BASE_URL,
    REFRESH_ENDPOINT,
    SECURED_SIGN_IN_ENDPOINT,
    SESSION_REFRESH_ENDPOINT,
    SIGN_IN_ENDPOINT,
)
from .exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    TokenRefreshError,
)
from .unit_system import UnitSystemType

# Resolve the package version directly from distribution metadata instead
# of importing it from the package __init__ (which imports this module,
# making `from . import __version__` an order-dependent near-circular
# import).
try:
    __version__ = _dist_version("nwp500-python")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


class UserInfo(NavienBaseModel):
    """User information returned from authentication."""

    user_type: str = ""
    user_first_name: str = ""
    user_last_name: str = ""
    user_status: str = ""
    user_seq: int = 0

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
    access_key_id: str | None = None
    secret_key: str | None = None
    session_token: str | None = None
    authorization_expires_in: int | None = None

    # Calculated fields
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Set when the AWS credentials were renewed separately from the JWT
    # (``/auth/session/refresh``), so their expiry is not computed from
    # the JWT's ``issued_at``. ``None`` means they share ``issued_at``.
    aws_credentials_issued_at: datetime | None = None

    _expires_at: datetime = PrivateAttr()
    _aws_expires_at: datetime | None = PrivateAttr(default=None)

    @field_validator("issued_at", "aws_credentials_issued_at", mode="before")
    @classmethod
    def _normalize_issued_at_tz(cls, v: Any) -> Any:
        """Assume UTC for timezone-naive datetimes.

        Handles old stored tokens that may not have timezone info,
        whether provided as a datetime object or an ISO 8601 string.
        """
        if v is None:
            return None
        if isinstance(v, str) and not v.endswith("Z"):
            # Check for a timezone offset (+HH:MM or -HH:MM) in the time
            # portion only (after the 'T' separator), so that date-part hyphens
            # like "2026-02-17" are not mistaken for a negative offset.
            t_pos = v.find("T")
            time_part = v[t_pos + 1 :] if t_pos >= 0 else v
            if "+" not in time_part and "-" not in time_part:
                return v + "+00:00"
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    @model_validator(mode="before")
    @classmethod
    def handle_empty_aliases(cls, data: Any) -> Any:
        """Handle empty camelCase aliases with snake_case fallbacks."""
        if isinstance(data, dict):
            # Explicitly type data as dict for clarity and type safety
            d = cast(dict[str, Any], data)
            # Fields to check for fallback
            fields_to_check: list[tuple[str, str]] = [
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
                if camel in d and not d[camel] and snake in d:
                    d[camel] = d[snake]
            return d
        return data

    def model_post_init(self, __context: Any) -> None:
        """Cache the expiration timestamp after initialization."""
        # Pre-calculate and cache the expiration time
        self._expires_at = self.issued_at + timedelta(
            seconds=self.authentication_expires_in
        )
        # Calculate AWS credentials expiration if available
        if self.authorization_expires_in:
            aws_issued_at = self.aws_credentials_issued_at or self.issued_at
            self._aws_expires_at = aws_issued_at + timedelta(
                seconds=self.authorization_expires_in
            )
        else:
            self._aws_expires_at = None

    @property
    def expires_at(self) -> datetime:
        """Get the cached expiration timestamp."""
        return self._expires_at

    @property
    def is_expired(self) -> bool:
        """Check if the access token has expired (cached calculation)."""
        # Consider expired if within 5 minutes of expiration
        return datetime.now(UTC) >= (self._expires_at - timedelta(minutes=5))

    @property
    def are_aws_credentials_expired(self) -> bool:
        """Check if AWS credentials have expired.

        AWS credentials have a separate expiration time from JWT tokens.
        The JWT refresh endpoint doesn't provide new AWS credentials; they
        are renewed with ``NavienAuthClient.refresh_session()`` (or a
        secured/password sign-in).

        Returns:
            True if AWS credentials are expired, False if expiration time is
            unknown or credentials are still valid
        """
        if not self._aws_expires_at:
            # If we don't know when AWS credentials expire, consider them valid
            # This handles cases where authorization_expires_in wasn't provided
            return False
        # Consider expired if within 5 minutes of expiration
        return datetime.now(UTC) >= (
            self._aws_expires_at - timedelta(minutes=5)
        )

    @property
    def time_until_expiry(self) -> timedelta:
        """Get time remaining until token expiration.

        Uses cached expiration time for efficiency.
        """
        return self._expires_at - datetime.now(UTC)

    @property
    def bearer_token(self) -> str:
        """Get the formatted Bearer token for Authorization header."""
        return f"Bearer {self.access_token}"

    def to_dict(self) -> dict[str, Any]:
        """Convert tokens to a dictionary for serialization.

        This includes the calculated issued_at timestamp, which is needed
        to maintain the correct expiration time when restoring tokens.
        """
        data = self.model_dump()
        # Ensure timestamps are serialized in a format that model_validate
        # can parse
        for key in ("issued_at", "aws_credentials_issued_at"):
            if isinstance(data.get(key), datetime):
                data[key] = data[key].strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        return data


class AuthenticationResponse(NavienBaseModel):
    """Complete authentication response including user info and tokens."""

    user_info: UserInfo
    tokens: AuthTokens
    legal: list[Any] = Field(default_factory=list)
    code: int = 200
    message: str = Field(default="SUCCESS", alias="msg")

    @model_validator(mode="before")
    @classmethod
    def wrap_api_response(cls, data: Any) -> Any:
        """Handle nested 'data' wrapper in API responses."""
        if isinstance(data, dict) and "data" in data:
            # Lift fields from 'data' into the top level for validation
            # while preserving top-level code/msg
            response_data = data.get("data", {})
            if isinstance(response_data, dict):
                merged = {**data, **response_data}
                # Handle 'token' vs 'tokens' inconsistency in API
                if "token" in response_data and "tokens" not in response_data:
                    merged["tokens"] = response_data["token"]
                return merged
        return data


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
    - Session management via aiohttp ClientSession
    - AWS credentials (if provided by API)

    Session and Context Manager
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~

    The auth client manages an aiohttp session that is shared with other
    clients (API, MQTT). The session is created when entering the context
    manager and closed when exiting.

    Authentication is performed automatically when entering the async context
    manager, unless valid stored tokens are provided.

    **Important:** All API and MQTT clients must be created and used within
    the context manager. Once the context manager exits, the session is closed
    and clients can no longer be used.

    Example:
        >>> async with NavienAuthClient(user_id="user@example.com",
        password="password") as client:
        ...     print(f"Welcome {client.current_user.full_name}")
        ...     # Token is securely stored and not printed in production
        ...
        ...     # Create other clients within the context
        ...     api_client = NavienAPIClient(auth_client=client)
        ...     mqtt_client = NavienMqttClient(auth_client=client)
        ...
        ...     # Use the clients
        ...     devices = await api_client.list_devices()
        ...     await mqtt_client.connect()

        Restore session from stored tokens:
        >>> stored_tokens = AuthTokens.model_validate(saved_data)
        >>> async with NavienAuthClient(
        ...     user_id="user@example.com",
        ...     password="password",
        ...     stored_tokens=stored_tokens
        ... ) as client:
        ...     # Authentication skipped if tokens are still valid
        ...     print(f"Welcome {client.current_user.full_name}")
    """

    def __init__(
        self,
        user_id: str,
        password: str,
        base_url: str = API_BASE_URL,
        session: aiohttp.ClientSession | None = None,
        timeout: int = 30,
        stored_tokens: AuthTokens | None = None,
        unit_system: UnitSystemType = None,
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
            unit_system: Preferred unit system:
                - "metric": Celsius, LPM, Liters
                - "us_customary": Fahrenheit, GPM, Gallons

                - None: Auto-detect from device (default)

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
        self._unit_system: UnitSystemType = unit_system

        # Current authentication state
        self._auth_response: AuthenticationResponse | None = None
        self._user_email: str | None = None

        # Serializes token refresh / re-authentication so concurrent
        # callers (API 401 retry, MQTT reconnect, periodic requests)
        # cannot stampede the refresh endpoint and invalidate each
        # other's tokens.
        self._refresh_lock = asyncio.Lock()

        # Restore tokens if provided
        if stored_tokens:
            # Create a minimal AuthenticationResponse with stored tokens
            # UserInfo will be populated on first API call if needed
            self._auth_response = AuthenticationResponse(
                user_info=UserInfo(),
                tokens=stored_tokens,
            )
            self._user_email = user_id

    async def __aenter__(self) -> Self:
        """Async context manager entry.

        Idempotent with respect to session creation: entering an
        already-entered client reuses the existing session instead of
        creating (and orphaning) a new one.

        If authentication fails, the owned session is closed before the
        exception propagates, because ``__aexit__`` is never called when
        ``__aenter__`` raises.
        """
        if self._owned_session and self._session is None:
            self._session = self._create_session()

        try:
            # Check if we have valid stored tokens
            if self._auth_response and self._auth_response.tokens:
                tokens = self._auth_response.tokens
                # If tokens are expired, refresh or re-authenticate
                if tokens.are_aws_credentials_expired:
                    _logger.info("Stored AWS credentials expired, renewing...")
                    async with self._refresh_lock:
                        await self._renew_aws_credentials_unlocked()
                elif tokens.is_expired:
                    _logger.info("Stored JWT token expired, refreshing...")
                    try:
                        await self.refresh_token(tokens.refresh_token)
                    except TokenRefreshError as e:
                        if not self.has_stored_credentials:
                            raise
                        _logger.warning(
                            "Stored token refresh failed: %s. Falling back "
                            "to full sign-in...",
                            e,
                        )
                        await self.sign_in(self._user_id, self._password)
                else:
                    _logger.info("Using stored tokens, skipping authentication")
            else:
                # No stored tokens, perform full authentication
                await self.sign_in(self._user_id, self._password)
        except BaseException:
            # __aexit__ won't run; don't leak the owned session.
            if self._owned_session and self._session:
                await self._session.close()
                self._session = None
            raise

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._owned_session and self._session:
            await self._session.close()
            self._session = None

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
            async with self._session.post(
                url, json=payload, headers=self._default_headers()
            ) as response:
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
                auth_response = AuthenticationResponse.model_validate(
                    response_data
                )
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
            raise AuthenticationError(
                f"Network error: {e!s}",
                retriable=True,
            ) from e
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            _logger.error(f"Failed to parse authentication response: {e}")
            raise AuthenticationError(f"Invalid response format: {e!s}") from e

    async def refresh_token(
        self, refresh_token: str | None = None
    ) -> AuthTokens:
        """
        Refresh access token using refresh token.

        Refreshes are serialized: if another task is already refreshing,
        this call waits for it and, when no explicit ``refresh_token``
        was given and the stored tokens are now valid, returns the
        already-refreshed tokens instead of issuing a duplicate request.

        Args:
            refresh_token: The refresh token obtained from sign-in.
                If not provided, uses the stored refresh token.

        Returns:
            New AuthTokens with refreshed access token

        Raises:
            TokenRefreshError: If token refresh fails or no token available
        """
        async with self._refresh_lock:
            current = self.current_tokens
            # Another task may have refreshed while we waited for the
            # lock; don't hit the endpoint again with valid tokens. An
            # explicit refresh_token equal to the stored one is a forced
            # refresh and proceeds; a differing one is stale (rotated by
            # the concurrent refresh) and would be rejected anyway.
            if (
                current
                and not current.is_expired
                and refresh_token != current.refresh_token
            ):
                return current
            return await self._refresh_token_unlocked(refresh_token)

    async def _refresh_token_unlocked(
        self, refresh_token: str | None = None
    ) -> AuthTokens:
        """Perform the actual token refresh. Caller must hold _refresh_lock."""
        if refresh_token is None:
            if self._auth_response and self._auth_response.tokens.refresh_token:
                refresh_token = self._auth_response.tokens.refresh_token
            else:
                raise TokenRefreshError("No refresh token available")
        await self._ensure_session()

        if self._session is None:
            raise AuthenticationError("Session not initialized")

        url = f"{self.base_url}{REFRESH_ENDPOINT}"
        payload = {"refreshToken": refresh_token}

        _logger.info("Attempting to refresh access token")

        try:
            async with self._session.post(
                url, json=payload, headers=self._default_headers()
            ) as response:
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
                new_tokens = AuthTokens.model_validate(data)

                # Preserve fields the refresh response may omit. The
                # refresh endpoint does not return AWS credentials, and it
                # may not echo the refresh token itself. Without this,
                # new_tokens.refresh_token would be "" and every
                # subsequent refresh would fail.
                if self._auth_response and self._auth_response.tokens:
                    old_tokens = self._auth_response.tokens
                    if (
                        not new_tokens.refresh_token
                        and old_tokens.refresh_token
                    ):
                        new_tokens.refresh_token = old_tokens.refresh_token
                    if not new_tokens.id_token and old_tokens.id_token:
                        new_tokens.id_token = old_tokens.id_token
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
                        # Also preserve the AWS expiration timestamp. The
                        # issued_at field survives serialization, so a
                        # restored token keeps the right AWS expiry too.
                        new_tokens.aws_credentials_issued_at = (
                            old_tokens.aws_credentials_issued_at
                            or old_tokens.issued_at
                        )
                        cast(Any, new_tokens)._aws_expires_at = cast(
                            Any, old_tokens
                        )._aws_expires_at

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
            raise TokenRefreshError(
                f"Network error: {e!s}",
                retriable=True,
            ) from e
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            _logger.error(f"Failed to parse refresh response: {e}")
            raise TokenRefreshError(f"Invalid response format: {e!s}") from e

    async def refresh_session(self) -> AuthTokens:
        """
        Renew the AWS (SigV4) credentials without a full sign-in.

        Posts the current access token to ``/auth/session/refresh``. The
        response carries only the AWS credential fields (``accessKeyId``,
        ``secretKey``, ``sessionToken``, ``authorizationExpiresIn``); any
        field the server omits keeps its stored value, as the NaviLink app
        does. The JWT tokens are untouched.

        Serialized with ``refresh_token()`` on the same lock so concurrent
        callers cannot stampede the endpoint.

        Returns:
            The updated AuthTokens (also stored as the current tokens)

        Raises:
            AuthenticationError: If there is no access token to send
            TokenRefreshError: If the server rejects the request or the
                response contains no credentials
        """
        async with self._refresh_lock:
            return await self._refresh_session_unlocked()

    _TOKEN_KEYS: tuple[tuple[str, str], ...] = (
        ("idToken", "id_token"),
        ("accessToken", "access_token"),
        ("refreshToken", "refresh_token"),
        ("authenticationExpiresIn", "authentication_expires_in"),
        ("accessKeyId", "access_key_id"),
        ("secretKey", "secret_key"),
        ("sessionToken", "session_token"),
        ("authorizationExpiresIn", "authorization_expires_in"),
    )
    _AWS_KEYS = frozenset({"access_key_id", "secret_key", "session_token"})

    @classmethod
    def _merge_token_fields(
        cls, current: AuthTokens, data: dict[str, Any]
    ) -> tuple[AuthTokens, set[str]]:
        """Overlay the token fields the server sent onto ``current``.

        Only keys present and non-empty in ``data`` are overwritten, as
        the app does. A renewed access token re-stamps ``issued_at``;
        renewed AWS credentials re-stamp ``aws_credentials_issued_at``
        without touching the JWT's expiry.

        Returns:
            The merged tokens and the set of snake-case fields updated.
        """
        updates: dict[str, Any] = {}
        for camel, snake in cls._TOKEN_KEYS:
            if camel in data and data[camel] not in (None, ""):
                updates[snake] = data[camel]
        merged = current.model_dump()
        merged.update(updates)
        now = datetime.now(UTC)
        if "access_token" in updates:
            merged["issued_at"] = now
        if updates.keys() & cls._AWS_KEYS:
            merged["aws_credentials_issued_at"] = now
        return AuthTokens.model_validate(merged), set(updates)

    async def _refresh_session_unlocked(self) -> AuthTokens:
        """Perform the session refresh. Caller must hold _refresh_lock."""
        current = self.current_tokens
        if not current or not current.access_token:
            raise AuthenticationError(
                "No access token available for session refresh"
            )
        await self._ensure_session()

        if self._session is None:
            raise AuthenticationError("Session not initialized")

        url = f"{self.base_url}{SESSION_REFRESH_ENDPOINT}"
        payload = {"userId": self._user_email or self._user_id}

        _logger.info("Attempting to refresh AWS session credentials")

        try:
            async with self._session.post(
                url, json=payload, headers=self.get_auth_headers()
            ) as response:
                response_data = await response.json()

                code = response_data.get("code", response.status)
                msg = response_data.get("msg", "")

                if code != 200 or not response.ok:
                    _logger.error(f"Session refresh failed: {code} - {msg}")
                    raise TokenRefreshError(
                        f"Failed to refresh session: {msg}",
                        status_code=code,
                        response=response_data,
                    )

                data = response_data.get("data") or {}
                if not isinstance(data, dict):
                    raise ValueError("'data' is not an object")

                # Overwrite only the keys the server sent (mirrors the app).
                new_tokens, updated = self._merge_token_fields(current, data)
                if not updated & self._AWS_KEYS:
                    raise TokenRefreshError(
                        "Session refresh response contained no AWS credentials",
                        status_code=code,
                        response=response_data,
                    )

                if self._auth_response:
                    self._auth_response.tokens = new_tokens

                _logger.info("Successfully refreshed AWS session credentials")
                return new_tokens

        except aiohttp.ClientError as e:
            _logger.error(f"Network error during session refresh: {e}")
            raise TokenRefreshError(
                f"Network error: {e!s}",
                retriable=True,
            ) from e
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            _logger.error(f"Failed to parse session refresh response: {e}")
            raise TokenRefreshError(f"Invalid response format: {e!s}") from e

    async def secured_sign_in(self) -> AuthenticationResponse:
        """
        Sign in again with the stored access token instead of the password.

        Posts to ``/user/secured-sign-in`` with the current access token in
        the ``authorization`` header and ``{"userId": <email>}`` as the body.
        The response carries user info, legal notices and a ``token``
        object. Only the token fields the server sends are overwritten;
        in practice that is the AWS credentials, so the current JWT access
        and refresh tokens are kept. The app uses this on auto-login and
        falls back to the password only if it fails.

        Serialized with ``refresh_token()`` and ``refresh_session()`` by the
        refresh lock, so an in-flight refresh cannot merge stale tokens over
        the ones this call receives.

        Returns:
            AuthenticationResponse containing user info and tokens

        Raises:
            AuthenticationError: If there is no access token, the server
                rejects the token, or the response cannot be parsed
        """
        async with self._refresh_lock:
            return await self._secured_sign_in_unlocked()

    async def _secured_sign_in_unlocked(self) -> AuthenticationResponse:
        """Perform the secured sign-in. Caller must hold _refresh_lock."""
        current = self.current_tokens
        if not current or not current.access_token:
            raise AuthenticationError(
                "No access token available for secured sign-in"
            )
        await self._ensure_session()

        if self._session is None:
            raise AuthenticationError("Session not initialized")

        user_id = self._user_email or self._user_id
        url = f"{self.base_url}{SECURED_SIGN_IN_ENDPOINT}"
        payload = {"userId": user_id}

        _logger.info(f"Attempting secured sign-in for user: {user_id}")

        try:
            async with self._session.post(
                url, json=payload, headers=self.get_auth_headers()
            ) as response:
                response_data = await response.json()

                code = response_data.get("code", response.status)
                msg = response_data.get("msg", "")

                if code != 200 or not response.ok:
                    _logger.error(f"Secured sign-in failed: {code} - {msg}")
                    raise AuthenticationError(
                        f"Secured sign-in failed: {msg}",
                        status_code=code,
                        response=response_data,
                    )

                data = response_data.get("data") or {}
                if not isinstance(data, dict):
                    raise ValueError("'data' is not an object")
                token_data = data.get("token") or data.get("tokens") or {}
                if not isinstance(token_data, dict):
                    raise ValueError("'token' is not an object")

                new_tokens, updated = self._merge_token_fields(
                    current, token_data
                )
                if not updated:
                    raise AuthenticationError(
                        "Secured sign-in response contained no tokens",
                        status_code=code,
                        response=response_data,
                    )

                auth_response = AuthenticationResponse(
                    user_info=UserInfo.model_validate(
                        data.get("userInfo") or {}
                    ),
                    tokens=new_tokens,
                    legal=list(data.get("legal") or []),
                    code=code,
                    msg=msg or "SUCCESS",
                )
                self._auth_response = auth_response
                self._user_email = user_id

                _logger.info(
                    "Successfully re-authenticated user via secured "
                    "sign-in: %s",
                    auth_response.user_info.full_name,
                )
                _logger.debug(
                    "Token expires in: %s",
                    auth_response.tokens.time_until_expiry,
                )

                return auth_response

        except aiohttp.ClientError as e:
            _logger.error(f"Network error during secured sign-in: {e}")
            raise AuthenticationError(
                f"Network error: {e!s}",
                retriable=True,
            ) from e
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            _logger.error(f"Failed to parse secured sign-in response: {e}")
            raise AuthenticationError(f"Invalid response format: {e!s}") from e

    async def _renew_aws_credentials_unlocked(self) -> AuthTokens:
        """Obtain fresh AWS credentials. Caller must hold _refresh_lock.

        Tries, in order, the cheapest renewal that can succeed:

        1. ``/auth/session/refresh`` with the current access token
           (refreshing the JWT first if it has expired)
        2. ``/user/secured-sign-in`` with the current access token
        3. ``/user/sign-in`` with the stored password (last resort)

        Steps 1 and 2 are skipped when there is no access token. Step 3
        is skipped when no password is stored; the last error is then
        re-raised.
        """
        last_error: AuthenticationError | None = None
        tokens = self.current_tokens

        if tokens and tokens.access_token:
            if tokens.is_expired and tokens.refresh_token:
                # Both endpoints need a live access token.
                try:
                    tokens = await self._refresh_token_unlocked()
                except TokenRefreshError as e:
                    last_error = e
                    _logger.warning(
                        "JWT refresh before session refresh failed: %s", e
                    )

            try:
                return await self._refresh_session_unlocked()
            except AuthenticationError as e:
                last_error = e
                _logger.warning(
                    "Session refresh failed: %s. Trying secured sign-in...", e
                )

            try:
                return (await self._secured_sign_in_unlocked()).tokens
            except AuthenticationError as e:
                last_error = e
                _logger.warning("Secured sign-in failed: %s", e)

        if not self.has_stored_credentials:
            if last_error is not None:
                raise last_error
            raise AuthenticationError(
                "Cannot renew AWS credentials: no access token and no "
                "stored credentials"
            )

        _logger.info("Falling back to password sign-in for AWS credentials")
        return (await self.sign_in(self._user_id, self._password)).tokens

    async def re_authenticate(self) -> AuthenticationResponse:
        """
        Re-authenticate using the stored access token or credentials.

        Tries ``secured_sign_in()`` first when a non-expired access token
        is held, so the password is only sent if the token is rejected.
        Falls back to a fresh password sign-in using the user_id and
        password from initialization. Useful for recovering from expired
        tokens or connection issues.

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

        tokens = self.current_tokens
        if tokens and tokens.access_token and not tokens.is_expired:
            try:
                _logger.info("Re-authenticating with stored access token")
                return await self.secured_sign_in()
            except AuthenticationError as e:
                _logger.warning(
                    "Secured sign-in failed: %s. Falling back to password "
                    "sign-in...",
                    e,
                )

        _logger.info("Re-authenticating with stored credentials")
        return await self.sign_in(self._user_id, self._password)

    async def ensure_valid_token(self) -> AuthTokens | None:
        """
        Ensure we have a valid access token, refreshing if necessary.

        This method checks both JWT token and AWS credentials expiration.
        An expired JWT is refreshed with ``refresh_token()``. Expired AWS
        credentials are renewed with ``refresh_session()``, then
        ``secured_sign_in()``, and only as a last resort a password
        ``sign_in()``.

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
            async with self._refresh_lock:
                # Re-check after acquiring the lock: another task may have
                # re-authenticated while we waited.
                if not self._auth_response:
                    return None
                tokens = self._auth_response.tokens
                if tokens.are_aws_credentials_expired:
                    _logger.info("AWS credentials expired, renewing...")
                    await self._renew_aws_credentials_unlocked()
                return (
                    self._auth_response.tokens if self._auth_response else None
                )

        # Check if JWT token has expired. refresh_token() serializes
        # concurrent refreshes and returns the already-refreshed tokens
        # to callers that lost the race.
        if tokens.is_expired:
            _logger.info("Token expired, refreshing...")
            return await self.refresh_token()

        return tokens

    @property
    def session(self) -> aiohttp.ClientSession | None:
        """Get the active aiohttp session."""
        return self._session

    @property
    def is_authenticated(self) -> bool:
        """Check if client is currently authenticated."""
        return self._auth_response is not None

    @property
    def current_user(self) -> UserInfo | None:
        """Get current authenticated user info."""
        return self._auth_response.user_info if self._auth_response else None

    @property
    def current_tokens(self) -> AuthTokens | None:
        """Get current authentication tokens."""
        return self._auth_response.tokens if self._auth_response else None

    @property
    def auth_response(self) -> AuthenticationResponse | None:
        """Get the complete authentication response."""
        return self._auth_response

    @property
    def user_email(self) -> str | None:
        """Get the email address of the authenticated user."""
        return self._user_email

    @property
    def has_stored_credentials(self) -> bool:
        """Check if user credentials are stored for re-authentication.

        Returns:
            True if both user_id and password are available for re-auth
        """
        return bool(self._user_id and self._password)

    @property
    def has_valid_tokens(self) -> bool:
        """Check if both JWT and AWS credentials are valid and not expired.

        Returns True only if tokens exist AND neither JWT tokens nor AWS
        credentials have expired. This is useful for pre-flight checks before
        operations that require valid credentials (e.g., MQTT connection).

        Returns:
            True if tokens exist AND not expired (JWT + AWS creds), False
            otherwise
        """
        if not self._auth_response:
            return False
        tokens = self._auth_response.tokens
        return not tokens.is_expired and not tokens.are_aws_credentials_expired

    async def close(self) -> None:
        """Close the aiohttp session if we own it."""
        if self._owned_session and self._session:
            await self._session.close()
            self._session = None

    @staticmethod
    def _default_headers() -> dict[str, str]:
        """Headers sent on every request, authenticated or not.

        The NaviLink app sends its User-Agent on sign-in and refresh calls
        too, so the library identifies itself on those as well.
        """
        return {
            "User-Agent": f"nwp500-python/{__version__}",
            "Content-Type": "application/json",
        }

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
        headers = self._default_headers()

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
        >>> print(f"Welcome {response.user.full_name}")
        >>> # Use the bearer token for API requests
        >>> # Do not print tokens in production code
    """
    async with NavienAuthClient(user_id, password) as client:
        auth_response = client.auth_response
        if auth_response is None:
            raise AuthenticationError(
                "Authentication failed: no response received"
            )
        return auth_response


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
    timeout = aiohttp.ClientTimeout(total=30)
    async with (
        aiohttp.ClientSession(connector=connector, timeout=timeout) as session,
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
        return AuthTokens.model_validate(data)
