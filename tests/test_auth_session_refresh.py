"""Tests for AWS credential renewal without a password.

Covers:
- refresh_session() (POST /auth/session/refresh): success, partial
  responses, error mapping, request shape
- secured_sign_in() (POST /user/secured-sign-in): success, error mapping,
  request shape (no password)
- Fallback order in ensure_valid_token(): session refresh, then secured
  sign-in, then password sign-in
- User-Agent on sign-in and refresh requests
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from nwp500.auth import (
    AuthenticationResponse,
    AuthTokens,
    NavienAuthClient,
    UserInfo,
    __version__,
)
from nwp500.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    TokenRefreshError,
)

EMAIL = "test@example.com"
PASSWORD = "password"


def _tokens(**overrides) -> AuthTokens:
    defaults = {
        "id_token": "id",
        "access_token": "access",
        "refresh_token": "refresh",
        "authentication_expires_in": 3600,
        "access_key_id": "old_key",
        "secret_key": "old_secret",
        "session_token": "old_session",
        "authorization_expires_in": 3600,
    }
    defaults.update(overrides)
    return AuthTokens(**defaults)


def _aws_expired_tokens(**overrides) -> AuthTokens:
    """AWS credentials expired, JWT still valid."""
    old_time = datetime.now(UTC) - timedelta(seconds=3900)
    overrides.setdefault("authentication_expires_in", 7200)
    overrides.setdefault("authorization_expires_in", 3600)
    return _tokens(issued_at=old_time, **overrides)


def _both_expired_tokens(**overrides) -> AuthTokens:
    old_time = datetime.now(UTC) - timedelta(seconds=7200)
    overrides.setdefault("authentication_expires_in", 3600)
    overrides.setdefault("authorization_expires_in", 3600)
    return _tokens(issued_at=old_time, **overrides)


def _client(tokens: AuthTokens | None, password: str = PASSWORD):
    client = NavienAuthClient(EMAIL, password)
    if tokens is not None:
        client._auth_response = AuthenticationResponse(
            user_info=UserInfo(user_first_name="Test", user_last_name="User"),
            tokens=tokens,
        )
        client._user_email = EMAIL
    return client


def _mock_post(client: NavienAuthClient, payload, status=200, ok=True):
    """Attach a mocked aiohttp session whose post() yields `payload`."""
    mock_resp = MagicMock()
    mock_resp.ok = ok
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=payload)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    client._session = mock_session
    client._owned_session = False
    return mock_session


def _sign_in_payload(**token_overrides):
    token = {
        "idToken": "new_id",
        "accessToken": "new_access",
        "refreshToken": "new_refresh",
        "authenticationExpiresIn": 3600,
        "accessKeyId": "new_key",
        "secretKey": "new_secret",
        "sessionToken": "new_session",
        "authorizationExpiresIn": 3600,
    }
    token.update(token_overrides)
    return {
        "code": 200,
        "msg": "SUCCESS",
        "data": {
            "userInfo": {
                "userType": "O",
                "userFirstName": "Jane",
                "userLastName": "Doe",
                "userStatus": "NORMAL",
                "userSeq": 42,
            },
            "token": token,
            "legal": [],
        },
    }


class TestRefreshSession:
    @pytest.mark.asyncio
    async def test_success_updates_only_aws_fields(self):
        client = _client(_aws_expired_tokens())
        old = client.current_tokens
        session = _mock_post(
            client,
            {
                "code": 200,
                "msg": "SUCCESS",
                "data": {
                    "accessKeyId": "new_key",
                    "secretKey": "new_secret",
                    "sessionToken": "new_session",
                    "authorizationExpiresIn": 1800,
                },
            },
        )

        new = await client.refresh_session()

        assert new.access_key_id == "new_key"
        assert new.secret_key == "new_secret"
        assert new.session_token == "new_session"
        assert new.authorization_expires_in == 1800
        # JWT fields and their expiry are untouched
        assert new.access_token == old.access_token
        assert new.refresh_token == old.refresh_token
        assert new.id_token == old.id_token
        assert new.issued_at == old.issued_at
        assert new.expires_at == old.expires_at
        # AWS expiry re-stamped from now
        assert not new.are_aws_credentials_expired
        assert new.aws_credentials_issued_at is not None
        assert (
            datetime.now(UTC) - new.aws_credentials_issued_at
        ).total_seconds() < 5
        # Stored as the current tokens
        assert client.current_tokens is new

        # Request shape: endpoint, body, raw token in lowercase header
        args, kwargs = session.post.call_args
        assert args[0].endswith("/auth/session/refresh")
        assert kwargs["json"] == {"userId": EMAIL}
        assert kwargs["headers"]["authorization"] == old.access_token
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["headers"]["User-Agent"] == f"nwp500-python/{__version__}"
        assert "password" not in kwargs["json"]

    @pytest.mark.asyncio
    async def test_partial_response_preserves_missing_keys(self):
        client = _client(_aws_expired_tokens())
        _mock_post(
            client,
            {
                "code": 200,
                "msg": "SUCCESS",
                "data": {
                    "accessKeyId": "new_key",
                    "secretKey": "new_secret",
                    # sessionToken and authorizationExpiresIn omitted
                },
            },
        )

        new = await client.refresh_session()

        assert new.access_key_id == "new_key"
        assert new.secret_key == "new_secret"
        assert new.session_token == "old_session"
        assert new.authorization_expires_in == 3600
        # Re-stamped with the previous lifetime
        assert not new.are_aws_credentials_expired

    @pytest.mark.asyncio
    async def test_survives_serialization_roundtrip(self):
        """A restored token keeps the renewed AWS expiry, not the JWT's."""
        client = _client(_aws_expired_tokens())
        _mock_post(
            client,
            {
                "code": 200,
                "data": {
                    "accessKeyId": "k",
                    "secretKey": "s",
                    "sessionToken": "t",
                    "authorizationExpiresIn": 3600,
                },
            },
        )
        new = await client.refresh_session()

        restored = AuthTokens.model_validate(new.to_dict())

        assert not restored.are_aws_credentials_expired
        assert (
            restored.aws_credentials_issued_at == new.aws_credentials_issued_at
        )
        assert restored.issued_at == new.issued_at

    @pytest.mark.asyncio
    async def test_response_without_credentials_raises(self):
        client = _client(_aws_expired_tokens())
        _mock_post(client, {"code": 200, "msg": "SUCCESS", "data": {}})

        with pytest.raises(TokenRefreshError, match="no AWS credentials"):
            await client.refresh_session()

        # Stored tokens untouched
        assert client.current_tokens.access_key_id == "old_key"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_http_error_maps_to_token_refresh_error(self, status):
        client = _client(_aws_expired_tokens())
        _mock_post(
            client,
            {"code": status, "msg": "Unauthorized"},
            status=status,
            ok=False,
        )

        with pytest.raises(TokenRefreshError) as excinfo:
            await client.refresh_session()

        assert excinfo.value.status_code == status
        assert isinstance(excinfo.value, AuthenticationError)
        assert not isinstance(excinfo.value, InvalidCredentialsError)
        assert client.current_tokens.access_key_id == "old_key"

    @pytest.mark.asyncio
    async def test_network_error_is_retriable(self):
        client = _client(_aws_expired_tokens())
        session = MagicMock()
        session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
        client._session = session
        client._owned_session = False

        with pytest.raises(TokenRefreshError) as excinfo:
            await client.refresh_session()
        assert excinfo.value.retriable

    @pytest.mark.asyncio
    async def test_requires_access_token(self):
        client = _client(None)
        with pytest.raises(AuthenticationError, match="No access token"):
            await client.refresh_session()

        client = _client(_tokens(access_token=""))
        with pytest.raises(AuthenticationError, match="No access token"):
            await client.refresh_session()


class TestSecuredSignIn:
    @pytest.mark.asyncio
    async def test_waits_for_an_in_flight_session_refresh(self):
        """Secured sign-in takes the refresh lock, so it cannot interleave
        with a session refresh and have that refresh merge stale tokens
        over the newly issued ones."""
        client = _client(_aws_expired_tokens())
        release = asyncio.Event()
        order: list[str] = []

        async def slow_refresh():
            order.append("refresh-start")
            await release.wait()
            order.append("refresh-end")
            return client.current_tokens

        async def secured():
            order.append("secured")
            return MagicMock(tokens=client.current_tokens)

        with (
            patch.object(client, "_refresh_session_unlocked", new=slow_refresh),
            patch.object(client, "_secured_sign_in_unlocked", new=secured),
        ):
            refresh_task = asyncio.create_task(client.refresh_session())
            await asyncio.sleep(0)
            assert order == ["refresh-start"]

            secured_task = asyncio.create_task(client.secured_sign_in())
            await asyncio.sleep(0)
            assert "secured" not in order  # blocked on the refresh lock

            release.set()
            await asyncio.gather(refresh_task, secured_task)

        assert order == ["refresh-start", "refresh-end", "secured"]

    @pytest.mark.asyncio
    async def test_success_replaces_auth_response(self):
        client = _client(_aws_expired_tokens())
        old_access = client.current_tokens.access_token
        session = _mock_post(client, _sign_in_payload())

        response = await client.secured_sign_in()

        assert client.auth_response is response
        assert response.user_info.full_name == "Jane Doe"
        assert response.tokens.access_token == "new_access"
        assert response.tokens.refresh_token == "new_refresh"
        assert response.tokens.access_key_id == "new_key"
        assert not response.tokens.is_expired
        assert not response.tokens.are_aws_credentials_expired
        assert client.user_email == EMAIL

        args, kwargs = session.post.call_args
        assert args[0].endswith("/user/secured-sign-in")
        assert kwargs["json"] == {"userId": EMAIL}
        assert "password" not in kwargs["json"]
        assert PASSWORD not in str(kwargs)
        assert kwargs["headers"]["authorization"] == old_access
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["headers"]["User-Agent"] == f"nwp500-python/{__version__}"

    @pytest.mark.asyncio
    async def test_live_shape_keeps_jwt_and_refresh_token(self):
        """The cloud's secured-sign-in ``token`` object carries only the AWS
        credentials (observed live 2026-10-16). The JWT access and refresh
        tokens must survive, or every later REST call gets a 401 with no
        way to refresh."""
        current = _aws_expired_tokens()
        client = _client(current)
        _mock_post(
            client,
            {
                "code": 200,
                "msg": "SUCCESS",
                "data": {
                    "userInfo": {
                        "userType": "O",
                        "userFirstName": "Jane",
                        "userLastName": "Doe",
                        "userStatus": "ACTIVE",
                        "userSeq": 1,
                    },
                    "legal": [{"legalType": "TS", "version": "1.0.0"}],
                    "token": {
                        "accessKeyId": "new_key",
                        "secretKey": "new_secret",
                        "sessionToken": "new_session",
                        "authorizationExpiresIn": 3600,
                    },
                },
            },
        )

        response = await client.secured_sign_in()

        tokens = response.tokens
        assert tokens.access_token == current.access_token
        assert tokens.refresh_token == current.refresh_token
        assert tokens.id_token == current.id_token
        assert tokens.issued_at == current.issued_at
        assert tokens.access_key_id == "new_key"
        assert tokens.session_token == "new_session"
        assert tokens.aws_credentials_issued_at is not None
        assert not tokens.are_aws_credentials_expired
        assert response.user_info.full_name == "Jane Doe"
        assert len(response.legal) == 1
        assert client.current_tokens is tokens

    @pytest.mark.asyncio
    async def test_response_without_tokens_raises(self):
        client = _client(_aws_expired_tokens())
        _mock_post(
            client,
            {
                "code": 200,
                "msg": "SUCCESS",
                "data": {"userInfo": {}, "token": {}},
            },
        )
        with pytest.raises(AuthenticationError, match="no tokens"):
            await client.secured_sign_in()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_http_error_maps_to_authentication_error(self, status):
        client = _client(_aws_expired_tokens())
        _mock_post(
            client,
            {"code": status, "msg": "Unauthorized"},
            status=status,
            ok=False,
        )

        with pytest.raises(AuthenticationError) as excinfo:
            await client.secured_sign_in()

        assert excinfo.value.status_code == status
        # A rejected token is not a wrong password
        assert not isinstance(excinfo.value, InvalidCredentialsError)
        assert client.current_tokens.access_token == "access"

    @pytest.mark.asyncio
    async def test_malformed_response_raises(self):
        client = _client(_aws_expired_tokens())
        _mock_post(
            client,
            {"code": 200, "msg": "SUCCESS", "data": {"token": "not-an-object"}},
        )

        with pytest.raises(AuthenticationError, match="Invalid response"):
            await client.secured_sign_in()

    @pytest.mark.asyncio
    async def test_requires_access_token(self):
        client = _client(None)
        with pytest.raises(AuthenticationError, match="No access token"):
            await client.secured_sign_in()


class TestEnsureValidTokenFallbackOrder:
    """AWS credentials expired: session refresh, secured sign-in, password."""

    def _patch_chain(self, client, *, refresh, secured, sign_in):
        return (
            patch.object(client, "_refresh_session_unlocked", new=refresh),
            patch.object(client, "_secured_sign_in_unlocked", new=secured),
            patch.object(client, "sign_in", new=sign_in),
        )

    @pytest.mark.asyncio
    async def test_session_refresh_succeeds_first(self):
        client = _client(_aws_expired_tokens())
        fresh = _tokens()

        async def fake_refresh():
            client._auth_response.tokens = fresh
            return fresh

        refresh = AsyncMock(side_effect=fake_refresh)
        secured = AsyncMock()
        sign_in = AsyncMock()
        p1, p2, p3 = self._patch_chain(
            client, refresh=refresh, secured=secured, sign_in=sign_in
        )
        with p1, p2, p3:
            result = await client.ensure_valid_token()

        assert result is fresh
        refresh.assert_awaited_once()
        secured.assert_not_awaited()
        sign_in.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_secured_sign_in(self):
        client = _client(_aws_expired_tokens())
        fresh = AuthenticationResponse(user_info=UserInfo(), tokens=_tokens())

        async def fake_secured():
            client._auth_response = fresh
            return fresh

        refresh = AsyncMock(side_effect=TokenRefreshError("rejected"))
        secured = AsyncMock(side_effect=fake_secured)
        sign_in = AsyncMock()
        p1, p2, p3 = self._patch_chain(
            client, refresh=refresh, secured=secured, sign_in=sign_in
        )
        with p1, p2, p3:
            result = await client.ensure_valid_token()

        assert result is fresh.tokens
        refresh.assert_awaited_once()
        secured.assert_awaited_once()
        sign_in.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_password_last(self):
        client = _client(_aws_expired_tokens())
        fresh = AuthenticationResponse(user_info=UserInfo(), tokens=_tokens())

        async def fake_sign_in(user_id, password):
            client._auth_response = fresh
            return fresh

        refresh = AsyncMock(side_effect=TokenRefreshError("rejected"))
        secured = AsyncMock(side_effect=AuthenticationError("rejected"))
        sign_in = AsyncMock(side_effect=fake_sign_in)
        p1, p2, p3 = self._patch_chain(
            client, refresh=refresh, secured=secured, sign_in=sign_in
        )
        with p1, p2, p3:
            result = await client.ensure_valid_token()

        assert result is fresh.tokens
        refresh.assert_awaited_once()
        secured.assert_awaited_once()
        sign_in.assert_awaited_once_with(EMAIL, PASSWORD)

    @pytest.mark.asyncio
    async def test_no_password_reraises_last_error(self):
        client = _client(_aws_expired_tokens(), password="")

        refresh = AsyncMock(side_effect=TokenRefreshError("rejected"))
        secured = AsyncMock(side_effect=AuthenticationError("token rejected"))
        sign_in = AsyncMock()
        p1, p2, p3 = self._patch_chain(
            client, refresh=refresh, secured=secured, sign_in=sign_in
        )
        with p1, p2, p3, pytest.raises(AuthenticationError, match="rejected"):
            await client.ensure_valid_token()

        sign_in.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expired_jwt_is_refreshed_before_session_refresh(self):
        """Both endpoints need a live access token, so an expired JWT is
        refreshed first (keeping the old AWS credentials), then the
        session refresh runs with the new token."""
        client = _client(_both_expired_tokens())
        order: list[str] = []

        async def fake_jwt_refresh(refresh_token=None):
            order.append("jwt")
            new = _tokens(
                access_token="fresh_access",
                aws_credentials_issued_at=client.current_tokens.issued_at,
            )
            client._auth_response.tokens = new
            return new

        async def fake_session_refresh():
            order.append("session")
            assert client.current_tokens.access_token == "fresh_access"
            fresh = _tokens(access_token="fresh_access")
            client._auth_response.tokens = fresh
            return fresh

        with (
            patch.object(
                client,
                "_refresh_token_unlocked",
                new=AsyncMock(side_effect=fake_jwt_refresh),
            ),
            patch.object(
                client,
                "_refresh_session_unlocked",
                new=AsyncMock(side_effect=fake_session_refresh),
            ),
            patch.object(client, "sign_in", new=AsyncMock()) as sign_in,
        ):
            result = await client.ensure_valid_token()

        assert order == ["jwt", "session"]
        assert result.access_token == "fresh_access"
        sign_in.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_jwt_refresh_goes_to_password(self):
        """With the JWT expired and its refresh rejected, neither token
        endpoint can succeed, so neither is called."""
        client = _client(_both_expired_tokens())
        fresh = AuthenticationResponse(user_info=UserInfo(), tokens=_tokens())

        with (
            patch.object(
                client,
                "_refresh_token_unlocked",
                new=AsyncMock(side_effect=TokenRefreshError("expired")),
            ),
            patch.object(
                client, "_refresh_session_unlocked", new=AsyncMock()
            ) as session_refresh,
            patch.object(
                client, "_secured_sign_in_unlocked", new=AsyncMock()
            ) as secured,
            patch.object(
                client, "sign_in", new=AsyncMock(return_value=fresh)
            ) as sign_in,
        ):
            await client.ensure_valid_token()

        session_refresh.assert_not_awaited()
        secured.assert_not_awaited()
        sign_in.assert_awaited_once_with(EMAIL, PASSWORD)

    @pytest.mark.asyncio
    async def test_failed_jwt_refresh_without_password_reraises(self):
        client = _client(_both_expired_tokens(), password="")

        with (
            patch.object(
                client,
                "_refresh_token_unlocked",
                new=AsyncMock(side_effect=TokenRefreshError("expired")),
            ),
            pytest.raises(TokenRefreshError, match="expired"),
        ):
            await client.ensure_valid_token()

    @pytest.mark.asyncio
    async def test_no_tokens_returns_none(self):
        """Existing behaviour: nothing stored means nothing to renew."""
        client = _client(None)
        assert await client.ensure_valid_token() is None

    @pytest.mark.asyncio
    async def test_concurrent_callers_single_renewal(self):
        """The renewal chain runs once under the refresh lock."""
        import asyncio

        client = _client(_aws_expired_tokens())
        calls = 0

        async def fake_refresh():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            fresh = _tokens()
            client._auth_response.tokens = fresh
            return fresh

        with patch.object(
            client,
            "_refresh_session_unlocked",
            new=AsyncMock(side_effect=fake_refresh),
        ):
            results = await asyncio.gather(
                *(client.ensure_valid_token() for _ in range(5))
            )

        assert calls == 1
        assert all(not r.are_aws_credentials_expired for r in results)


class TestReAuthenticate:
    @pytest.mark.asyncio
    async def test_prefers_secured_sign_in_with_live_token(self):
        client = _client(_tokens())
        fresh = AuthenticationResponse(user_info=UserInfo(), tokens=_tokens())
        secured = AsyncMock(return_value=fresh)
        sign_in = AsyncMock()

        with (
            patch.object(client, "_secured_sign_in_unlocked", new=secured),
            patch.object(client, "sign_in", new=sign_in),
        ):
            result = await client.re_authenticate()

        assert result is fresh
        sign_in.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_password_when_token_rejected(self):
        client = _client(_tokens())
        fresh = AuthenticationResponse(user_info=UserInfo(), tokens=_tokens())
        secured = AsyncMock(side_effect=AuthenticationError("rejected"))
        sign_in = AsyncMock(return_value=fresh)

        with (
            patch.object(client, "_secured_sign_in_unlocked", new=secured),
            patch.object(client, "sign_in", new=sign_in),
        ):
            result = await client.re_authenticate()

        assert result is fresh
        sign_in.assert_awaited_once_with(EMAIL, PASSWORD)

    @pytest.mark.asyncio
    async def test_skips_secured_sign_in_with_expired_jwt(self):
        client = _client(_both_expired_tokens())
        fresh = AuthenticationResponse(user_info=UserInfo(), tokens=_tokens())
        secured = AsyncMock()
        sign_in = AsyncMock(return_value=fresh)

        with (
            patch.object(client, "_secured_sign_in_unlocked", new=secured),
            patch.object(client, "sign_in", new=sign_in),
        ):
            await client.re_authenticate()

        secured.assert_not_awaited()
        sign_in.assert_awaited_once_with(EMAIL, PASSWORD)

    @pytest.mark.asyncio
    async def test_requires_stored_credentials(self):
        client = _client(_both_expired_tokens(), password="")
        with pytest.raises(ValueError, match="No stored credentials"):
            await client.re_authenticate()

    @pytest.mark.asyncio
    async def test_token_only_client_uses_secured_sign_in(self):
        client = _client(_tokens(), password="")
        fresh = AuthenticationResponse(user_info=UserInfo(), tokens=_tokens())
        secured = AsyncMock(return_value=fresh)

        with patch.object(client, "_secured_sign_in_unlocked", new=secured):
            result = await client.re_authenticate()

        assert result is fresh

    @pytest.mark.asyncio
    async def test_token_only_client_raises_secured_sign_in_error(self):
        client = _client(_tokens(), password="")
        secured = AsyncMock(side_effect=AuthenticationError("rejected"))

        with (
            patch.object(client, "_secured_sign_in_unlocked", new=secured),
            pytest.raises(AuthenticationError, match="rejected"),
        ):
            await client.re_authenticate()


class TestUserAgentOnUnauthenticatedCalls:
    @pytest.mark.asyncio
    async def test_sign_in_sends_user_agent(self):
        client = _client(None)
        session = _mock_post(client, _sign_in_payload())

        await client.sign_in(EMAIL, PASSWORD)

        _, kwargs = session.post.call_args
        assert kwargs["headers"]["User-Agent"] == f"nwp500-python/{__version__}"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert "authorization" not in kwargs["headers"]

    @pytest.mark.asyncio
    async def test_refresh_token_sends_user_agent(self):
        client = _client(_tokens())
        session = _mock_post(
            client,
            {
                "code": 200,
                "data": {
                    "accessToken": "new_access",
                    "authenticationExpiresIn": 3600,
                },
            },
        )

        await client.refresh_token("refresh")

        _, kwargs = session.post.call_args
        assert kwargs["headers"]["User-Agent"] == f"nwp500-python/{__version__}"
        assert "authorization" not in kwargs["headers"]


class TestMergeTokenFields:
    def test_new_access_token_alone_keeps_aws_expiry(self):
        """A renewed JWT without AWS keys must not make the kept AWS
        credentials look freshly issued."""
        issued = datetime.now(UTC) - timedelta(minutes=50)
        current = _tokens(issued_at=issued)
        before = current.time_until_expiry
        aws_left = current._aws_expires_at - datetime.now(UTC)

        merged, updated = NavienAuthClient._merge_token_fields(
            current, {"accessToken": "renewed"}
        )

        assert updated == {"access_token"}
        assert merged.access_token == "renewed"
        assert merged.time_until_expiry > before
        assert merged.aws_credentials_issued_at == issued
        merged_left = merged._aws_expires_at - datetime.now(UTC)
        assert abs(merged_left - aws_left) < timedelta(seconds=5)

        restored = AuthTokens.model_validate(merged.to_dict())
        assert restored._aws_expires_at == merged._aws_expires_at

    def test_new_access_token_keeps_earlier_aws_issue_time(self):
        jwt_issued = datetime.now(UTC) - timedelta(minutes=10)
        aws_issued = datetime.now(UTC) - timedelta(minutes=40)
        current = _tokens(
            issued_at=jwt_issued, aws_credentials_issued_at=aws_issued
        )

        merged, _ = NavienAuthClient._merge_token_fields(
            current, {"accessToken": "renewed"}
        )

        assert merged.aws_credentials_issued_at == aws_issued

    def test_new_aws_keys_restamp_their_issue_time(self):
        issued = datetime.now(UTC) - timedelta(minutes=50)
        current = _tokens(issued_at=issued)

        merged, _ = NavienAuthClient._merge_token_fields(
            current, {"accessToken": "renewed", "accessKeyId": "new_key"}
        )

        assert merged.aws_credentials_issued_at > issued
        assert not merged.are_aws_credentials_expired
