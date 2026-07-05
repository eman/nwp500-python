"""Regression tests for auth/session lifecycle fixes.

Covers:
- Concurrent token refresh serialization (no stampede)
- refresh_token preservation when the refresh response omits it
- Owned session closed when __aenter__ fails
- __aenter__ idempotency (factory double-enter must not orphan sessions)
- Fallback to full sign-in when stored-token refresh fails
- API client resolving the auth session per request (no pinning)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nwp500.api_client import NavienAPIClient
from nwp500.auth import (
    AuthenticationResponse,
    AuthTokens,
    NavienAuthClient,
    UserInfo,
)
from nwp500.exceptions import AuthenticationError, TokenRefreshError


def _valid_tokens(**overrides) -> AuthTokens:
    defaults = {
        "id_token": "id",
        "access_token": "access",
        "refresh_token": "refresh",
        "authentication_expires_in": 3600,
        "access_key_id": "key_id",
        "secret_key": "secret",
        "session_token": "session",
        "authorization_expires_in": 3600,
    }
    defaults.update(overrides)
    return AuthTokens(**defaults)


def _expired_jwt_tokens(**overrides) -> AuthTokens:
    """JWT expired, AWS credentials still valid (refresh path)."""
    old_time = datetime.now(UTC) - timedelta(seconds=7200)
    overrides.setdefault("authorization_expires_in", 100000)
    return _valid_tokens(issued_at=old_time, **overrides)


def _client_with_tokens(tokens: AuthTokens) -> NavienAuthClient:
    client = NavienAuthClient("test@example.com", "password")
    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="Test", user_last_name="User"),
        tokens=tokens,
    )
    return client


class TestConcurrentRefresh:
    """Token refresh must be serialized across concurrent callers."""

    @pytest.mark.asyncio
    async def test_concurrent_ensure_valid_token_single_refresh(self):
        """Regression: N concurrent callers at token expiry fired N
        parallel refresh requests; with rotation the losers held
        invalidated tokens."""
        client = _client_with_tokens(_expired_jwt_tokens())
        refresh_calls = 0

        async def fake_refresh(refresh_token=None):
            nonlocal refresh_calls
            refresh_calls += 1
            await asyncio.sleep(0.01)  # let other callers pile up
            new_tokens = _valid_tokens(refresh_token="rotated")
            client._auth_response.tokens = new_tokens
            return new_tokens

        with patch.object(
            client, "_refresh_token_unlocked", side_effect=fake_refresh
        ):
            results = await asyncio.gather(
                *(client.ensure_valid_token() for _ in range(5))
            )

        assert refresh_calls == 1
        assert all(r is not None and not r.is_expired for r in results)

    @pytest.mark.asyncio
    async def test_stale_explicit_token_gets_fresh_tokens(self):
        """A 401-retry caller holding a pre-rotation refresh token must
        receive the already-refreshed tokens, not refresh with a stale
        token."""
        fresh = _valid_tokens(refresh_token="rotated")
        client = _client_with_tokens(fresh)

        unlocked = AsyncMock()
        with patch.object(client, "_refresh_token_unlocked", unlocked):
            result = await client.refresh_token("old-stale-token")

        unlocked.assert_not_awaited()
        assert result is fresh

    @pytest.mark.asyncio
    async def test_forced_refresh_with_current_token_proceeds(self):
        """Explicitly refreshing with the current refresh token is a
        forced refresh (used by deep reconnect) and must not be skipped."""
        tokens = _valid_tokens()
        client = _client_with_tokens(tokens)

        unlocked = AsyncMock(return_value=_valid_tokens())
        with patch.object(client, "_refresh_token_unlocked", unlocked):
            await client.refresh_token(tokens.refresh_token)

        unlocked.assert_awaited_once_with(tokens.refresh_token)


class TestRefreshTokenPreservation:
    """Fields omitted from the refresh response must be preserved."""

    @pytest.mark.asyncio
    async def test_refresh_response_without_refresh_token(self):
        """Regression: the merge preserved AWS fields but not
        refresh_token/id_token; a response omitting them wiped the stored
        refresh token so every subsequent refresh posted ''."""
        client = _client_with_tokens(_expired_jwt_tokens())

        # Refresh response echoing neither refreshToken nor AWS fields
        response_payload = {
            "code": 200,
            "msg": "SUCCESS",
            "data": {
                "accessToken": "new_access",
                "authenticationExpiresIn": 3600,
            },
        }

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=response_payload)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        client._session = mock_session
        client._owned_session = False

        new_tokens = await client.refresh_token("refresh")

        assert new_tokens.access_token == "new_access"
        # Preserved from the old tokens:
        assert new_tokens.refresh_token == "refresh"
        assert new_tokens.id_token == "id"
        assert new_tokens.access_key_id == "key_id"
        assert new_tokens.secret_key == "secret"


class TestAenterLifecycle:
    """__aenter__ must not leak sessions and must be idempotent."""

    @pytest.mark.asyncio
    async def test_owned_session_closed_when_aenter_fails(self):
        """Regression: __aexit__ is never called when __aenter__ raises,
        leaking the owned ClientSession on bad credentials."""
        client = NavienAuthClient("test@example.com", "wrong-password")

        created_sessions = []
        real_create = client._create_session

        def tracking_create():
            session = real_create()
            created_sessions.append(session)
            return session

        with (
            patch.object(client, "_create_session", tracking_create),
            patch.object(
                client,
                "sign_in",
                new=AsyncMock(
                    side_effect=AuthenticationError("bad credentials")
                ),
            ),
        ):
            with pytest.raises(AuthenticationError):
                await client.__aenter__()

        assert len(created_sessions) == 1
        assert created_sessions[0].closed
        assert client._session is None

    @pytest.mark.asyncio
    async def test_aenter_is_idempotent_for_owned_session(self):
        """Regression: the factory pre-enters the context and its
        docstring tells users to enter again; the second __aenter__
        created a new session and orphaned the first."""
        client = _client_with_tokens(_valid_tokens())

        await client.__aenter__()
        first_session = client._session
        assert first_session is not None

        await client.__aenter__()
        assert client._session is first_session

        await client.__aexit__(None, None, None)
        assert first_session.closed
        assert client._session is None

    @pytest.mark.asyncio
    async def test_stored_token_refresh_failure_falls_back_to_sign_in(self):
        """Regression: restoring week-old tokens raised TokenRefreshError
        even though credentials for a full sign-in were stored."""
        client = _client_with_tokens(_expired_jwt_tokens())

        sign_in = AsyncMock()
        with (
            patch.object(
                client,
                "refresh_token",
                new=AsyncMock(
                    side_effect=TokenRefreshError("refresh token expired")
                ),
            ),
            patch.object(client, "sign_in", sign_in),
        ):
            await client.__aenter__()

        sign_in.assert_awaited_once_with("test@example.com", "password")
        await client.__aexit__(None, None, None)


class TestApiClientSessionResolution:
    """The API client must not pin the auth client's session."""

    @pytest.mark.asyncio
    async def test_uses_recreated_auth_session(self):
        """Regression: the session was captured at construction; if the
        auth client recreated its session, the API client kept issuing
        requests on the closed one."""
        client = _client_with_tokens(_valid_tokens())
        first_session = MagicMock()
        client._session = first_session
        client._owned_session = False

        api = NavienAPIClient(auth_client=client)
        assert api._session is first_session

        # Auth client recreates its session (close() + _ensure_session())
        second_session = MagicMock()
        client._session = second_session

        assert api._session is second_session

    @pytest.mark.asyncio
    async def test_explicit_session_override_wins(self):
        client = _client_with_tokens(_valid_tokens())
        client._session = MagicMock()
        client._owned_session = False

        override = MagicMock()
        api = NavienAPIClient(auth_client=client, session=override)

        client._session = MagicMock()
        assert api._session is override

    def test_construction_requires_some_session(self):
        client = _client_with_tokens(_valid_tokens())
        client._session = None

        with pytest.raises(ValueError, match="active session"):
            NavienAPIClient(auth_client=client)
