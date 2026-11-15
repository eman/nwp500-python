"""A resumed session's replay: what the broker kept while the client was
away is dropped when the cloud stamped it before the connection."""

import asyncio
import concurrent.futures
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nwp500.auth import (
    AuthenticationResponse,
    AuthTokens,
    NavienAuthClient,
    UserInfo,
)
from nwp500.mqtt import NavienMqttClient
from nwp500.mqtt.connection import MqttConnection
from nwp500.mqtt.subscriptions import MqttSubscriptionManager
from nwp500.mqtt.utils import MqttConnectionConfig

TOPIC = "cmd/52/navilink-04786332fca0/res/rsv/rd"
RESUMED = 1_794_728_122.8


def _ms(at: float) -> int:
    return round(at * 1000)


def _manager(resumed: float | None) -> MqttSubscriptionManager:
    def schedule(coro: Any) -> None:
        coro.close()

    return MqttSubscriptionManager(
        connection=MagicMock(),
        client_id="navien-ha-1",
        event_emitter=MagicMock(),
        schedule_coroutine=schedule,
        resumed_session_at=lambda: resumed,
    )


def _delivered(
    manager: MqttSubscriptionManager, message: dict[str, Any]
) -> list[dict[str, Any]]:
    got: list[dict[str, Any]] = []

    def handler(topic: str, received: dict[str, Any]) -> None:
        got.append(received)

    manager._message_handlers["cmd/52/navilink-04786332fca0/#"] = [handler]
    asyncio.run(manager._dispatch_message(TOPIC, json.dumps(message).encode()))
    return got


def _list_reply(made_at: float) -> dict[str, Any]:
    return {
        "clientID": f"response-reservation-{_ms(made_at)}",
        "sessionID": "2",
        "response": {"reservation": []},
    }


def test_a_list_made_before_a_resumed_connection_is_dropped() -> None:
    # The replay in the report: a list made 20 minutes before.
    assert _delivered(_manager(RESUMED), _list_reply(RESUMED - 1203)) == []


def test_a_relayed_request_made_before_a_resumed_connection_is_dropped() -> (
    None
):
    echo = {"clientID": "navien-client-1", "registerAt": _ms(RESUMED - 600)}
    assert _delivered(_manager(RESUMED), echo) == []


@pytest.mark.parametrize(
    "made_at",
    [RESUMED + 5.0, RESUMED - 9.0],
    ids=["after", "within-the-allowance"],
)
def test_a_list_made_after_a_resumed_connection_is_delivered(
    made_at: float,
) -> None:
    reply = _list_reply(made_at)
    assert _delivered(_manager(RESUMED), reply) == [reply]


def test_a_message_without_a_stamp_is_delivered() -> None:
    status = {
        "clientID": "navilink-04786332fca0",
        "sessionID": "9",
        "response": {"status": {}},
    }
    assert _delivered(_manager(RESUMED), status) == [status]


def test_a_clean_session_delivers_any_list() -> None:
    reply = _list_reply(RESUMED - 1203)
    assert _delivered(_manager(None), reply) == [reply]


def _auth_client() -> NavienAuthClient:
    auth_client = NavienAuthClient("test@example.com", "password")
    auth_client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="Test", user_last_name="User"),
        tokens=AuthTokens(
            id_token="id",
            access_token="access",
            refresh_token="refresh",
            authentication_expires_in=3600,
            access_key_id="key",
            secret_key="secret",
            session_token="session",
            authorization_expires_in=3600,
        ),
    )
    return auth_client


@pytest.mark.parametrize("present", [True, False])
def test_the_connection_keeps_whether_it_resumed_a_session(
    present: bool,
) -> None:
    connection = MqttConnection(
        config=MqttConnectionConfig(client_id="c", clean_session=False),
        auth_client=_auth_client(),
    )
    fake = MagicMock()
    fake.connect.return_value = concurrent.futures.Future()
    fake.connect.return_value.set_result({"session_present": present})

    async def run() -> None:
        with patch(
            "nwp500.mqtt.connection._build_connection",
            MagicMock(return_value=fake),
        ):
            assert await connection.connect()

    asyncio.run(run())
    assert connection.session_present is present


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("present", [True, False])
async def test_a_resume_records_whether_it_resumed_a_session(
    present: bool,
) -> None:
    client = NavienMqttClient(_auth_client())
    connection = MagicMock()
    manager = MagicMock()
    manager.connection = connection
    client._connection_manager = manager
    subscriptions = MagicMock()
    subscriptions.resubscribe_all = AsyncMock()
    client._subscription_manager = subscriptions
    client.emit = AsyncMock()  # type: ignore[method-assign]
    client._diagnostics = MagicMock()
    client._diagnostics.record_connection_success = AsyncMock()

    before = time.time()
    client._on_connection_resumed_internal(
        connection=connection, return_code=0, session_present=present
    )
    await asyncio.sleep(0)

    if present:
        assert client._resumed_session_at is not None
        assert client._resumed_session_at >= before
    else:
        assert client._resumed_session_at is None


@pytest.mark.asyncio(loop_scope="function")
async def test_the_first_connect_hands_the_session_to_the_subscriptions() -> (
    None
):
    client = NavienMqttClient(
        _auth_client(), config=MqttConnectionConfig(clean_session=False)
    )
    connection_manager = MagicMock()
    connection_manager.connect = AsyncMock(return_value=True)
    connection_manager.session_present = True
    built: dict[str, Any] = {}

    def subscriptions(**kwargs: Any) -> MagicMock:
        built.update(kwargs)
        return MagicMock()

    with (
        patch.object(
            client,
            "_create_connection_manager",
            return_value=connection_manager,
        ),
        patch(
            "nwp500.mqtt.client.MqttSubscriptionManager",
            side_effect=subscriptions,
        ),
        patch("nwp500.mqtt.client.MqttReconnectionHandler"),
    ):
        assert await client.connect()

    resumed = built["resumed_session_at"]()
    assert resumed is not None
    assert resumed == client._resumed_session_at
    client._note_session(False)
    assert built["resumed_session_at"]() is None
