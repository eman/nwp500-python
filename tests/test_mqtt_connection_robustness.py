"""Resubscribe, stale callbacks, credentials and periodic task failures."""

import asyncio
import concurrent.futures
import logging
from collections.abc import Coroutine
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from awscrt.mqtt import SubscribeError

from nwp500.auth import (
    AuthenticationResponse,
    AuthTokens,
    NavienAuthClient,
    UserInfo,
)
from nwp500.models import Device
from nwp500.mqtt import NavienMqttClient
from nwp500.mqtt.connection import MqttConnection
from nwp500.mqtt.periodic import MqttPeriodicRequestManager
from nwp500.mqtt.subscriptions import MqttSubscriptionManager
from nwp500.mqtt.utils import MqttConnectionConfig, QoS


def _future(
    value: Any = None, error: BaseException | None = None
) -> concurrent.futures.Future[Any]:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(value)
    return future


def _manager(failures: dict[str, BaseException]) -> MqttSubscriptionManager:
    """Manager whose subscribe fails for the topics in ``failures``."""
    connection = MagicMock()

    def subscribe(topic: str, qos: Any, callback: Any) -> Any:
        if topic in failures:
            return _future(error=failures[topic]), 1
        return _future({"topic": topic, "qos": qos}), 1

    connection.subscribe.side_effect = subscribe
    return MqttSubscriptionManager(
        connection=connection,
        client_id="test-client",
        event_emitter=MagicMock(),
        schedule_coroutine=MagicMock(),
    )


def _handler(topic: str, message: dict[str, Any]) -> None:
    del topic, message


TOPICS = ["cmd/52/a/#", "cmd/52/b/#", "cmd/52/c/#"]


class TestResubscribeAll:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error", [TimeoutError(), SubscribeError("cmd/52/a/#"), ValueError()]
    )
    async def test_failure_keeps_every_topic_not_restored(
        self, error: BaseException
    ) -> None:
        manager = _manager({})
        for topic in TOPICS:
            await manager.subscribe(topic, _handler)

        manager._connection = _manager({"cmd/52/a/#": error})._connection
        await manager.resubscribe_all()

        assert set(manager._subscriptions) == set(TOPICS)
        assert all(manager._message_handlers[t] == [_handler] for t in TOPICS)

    @pytest.mark.asyncio
    async def test_cancel_keeps_every_topic_not_restored(self) -> None:
        manager = _manager({})
        for topic in TOPICS:
            await manager.subscribe(topic, _handler)

        never: concurrent.futures.Future[Any] = concurrent.futures.Future()
        stuck = MagicMock()
        stuck.subscribe.return_value = (never, 1)
        manager._connection = stuck

        task = asyncio.create_task(manager.resubscribe_all())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert set(manager._subscriptions) == set(TOPICS)


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_rejected_suback_removes_the_handler(self) -> None:
        manager = _manager({"cmd/52/a/#": SubscribeError("cmd/52/a/#")})
        with pytest.raises(SubscribeError):
            await manager.subscribe("cmd/52/a/#", _handler, QoS.AT_LEAST_ONCE)
        assert manager._message_handlers.get("cmd/52/a/#") == []
        assert "cmd/52/a/#" not in manager._subscriptions


@pytest.fixture
def auth_client() -> NavienAuthClient:
    client = NavienAuthClient("test@example.com", "password")
    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="Test", user_last_name="User"),
        tokens=AuthTokens(
            id_token="id",
            access_token="access",
            refresh_token="refresh",
            authentication_expires_in=3600,
            access_key_id="key-1",
            secret_key="secret-1",
            session_token="session-1",
            authorization_expires_in=3600,
        ),
    )
    return client


class TestStaleConnectionCallbacks:
    def test_callbacks_from_a_replaced_connection_are_ignored(
        self, auth_client: NavienAuthClient
    ) -> None:
        client = NavienMqttClient(auth_client)
        current, old = MagicMock(), MagicMock()
        manager = MagicMock()
        manager.connection = current
        client._connection_manager = manager
        client._connected = True

        client._on_connection_interrupted_internal(old, RuntimeError("x"))
        assert client._connected is True

        client._connected = False
        client._on_connection_resumed_internal(old, 0, True)
        assert client._connected is False

    def test_callbacks_from_the_current_connection_apply(
        self, auth_client: NavienAuthClient
    ) -> None:
        client = NavienMqttClient(auth_client)

        def close(coro: Coroutine[Any, Any, Any]) -> None:
            coro.close()

        client._schedule_coroutine = MagicMock(  # type: ignore[method-assign]
            side_effect=close
        )
        current = MagicMock()
        manager = MagicMock()
        manager.connection = current
        client._connection_manager = manager
        client._connected = True

        client._on_connection_interrupted_internal(current, RuntimeError("x"))
        assert client._connected is False


class TestCredentialsProvider:
    def test_provider_reads_the_current_tokens(
        self, auth_client: NavienAuthClient
    ) -> None:
        conn = MqttConnection(MqttConnectionConfig(client_id="c"), auth_client)
        conn._create_credentials_provider()
        first = conn._current_credentials()
        assert first.access_key_id == "key-1"

        response = auth_client._auth_response
        assert response is not None
        response.tokens = response.tokens.model_copy(
            update={"access_key_id": "key-2", "secret_key": "secret-2"}
        )
        second = conn._current_credentials()
        assert second.access_key_id == "key-2"
        assert second.secret_access_key == "secret-2"


class TestPeriodicTaskStop:
    @pytest.mark.asyncio
    async def test_unhandled_error_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def request(device: Device) -> int:
            raise ValueError("boom")

        manager = MqttPeriodicRequestManager(
            is_connected_func=lambda: True,
            request_device_info_func=request,
            request_device_status_func=request,
        )
        device = MagicMock()
        device.device_info.mac_address = "04786332fca0"
        caplog.set_level(logging.ERROR, logger="nwp500.mqtt.periodic")

        await manager.start_periodic_requests(
            cast(Device, device), period_seconds=0.01
        )
        for _ in range(20):
            await asyncio.sleep(0)

        assert any(
            "stopped" in r.getMessage() and "boom" in r.getMessage()
            for r in caplog.records
        )


class TestNoCurrentConnection:
    def test_callbacks_without_a_current_connection_are_ignored(
        self, auth_client: NavienAuthClient
    ) -> None:
        client = NavienMqttClient(auth_client)
        manager = MagicMock()
        manager.connection = None
        client._connection_manager = manager
        client._connected = False

        client._on_connection_resumed_internal(MagicMock(), 0, True)
        assert client._connected is False


class TestResubscribeRetry:
    @pytest.mark.asyncio
    async def test_a_failed_topic_is_retried_before_returning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import nwp500.mqtt.subscriptions as subscriptions

        monkeypatch.setattr(subscriptions, "_RESUBSCRIBE_DELAYS", (0, 0, 0))
        manager = _manager({})
        for topic in TOPICS:
            await manager.subscribe(topic, _handler)

        calls: dict[str, int] = {}
        flaky = MagicMock()

        def subscribe(topic: str, qos: Any, callback: Any) -> Any:
            calls[topic] = calls.get(topic, 0) + 1
            if topic == "cmd/52/a/#" and calls[topic] == 1:
                return _future(error=TimeoutError()), 1
            return _future({"topic": topic, "qos": qos}), 1

        flaky.subscribe.side_effect = subscribe
        manager._connection = flaky

        assert await manager.resubscribe_all() is True
        assert calls["cmd/52/a/#"] == 2
        assert set(manager._subscriptions) == set(TOPICS)

    @pytest.mark.asyncio
    async def test_returns_false_when_a_topic_stays_unrestored(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import nwp500.mqtt.subscriptions as subscriptions

        monkeypatch.setattr(subscriptions, "_RESUBSCRIBE_DELAYS", (0, 0, 0))
        manager = _manager({})
        await manager.subscribe("cmd/52/navilink-04786332fca0/#", _handler)
        manager._connection = _manager(
            {
                "cmd/52/navilink-04786332fca0/#": SubscribeError(
                    "cmd/52/navilink-04786332fca0/#"
                )
            }
        )._connection
        caplog.set_level(logging.ERROR, logger="nwp500.mqtt.subscriptions")

        assert await manager.resubscribe_all() is False
        assert "04786332fca0" not in caplog.text

    @pytest.mark.asyncio
    async def test_unsubscribe_during_backoff_is_not_undone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import nwp500.mqtt.subscriptions as subscriptions

        monkeypatch.setattr(subscriptions, "_RESUBSCRIBE_DELAYS", (0, 0, 0))
        manager = _manager({})
        await manager.subscribe("cmd/52/a/#", _handler)

        calls: list[str] = []
        flaky = MagicMock()

        def subscribe(topic: str, qos: Any, callback: Any) -> Any:
            calls.append(topic)
            return _future(error=TimeoutError()), 1

        flaky.subscribe.side_effect = subscribe
        flaky.unsubscribe.return_value = (_future({}), 2)
        manager._connection = flaky

        real_sleep = asyncio.sleep

        async def sleep_then_unsubscribe(delay: float) -> None:
            # The caller removes its callback while the retry waits.
            await manager.unsubscribe("cmd/52/a/#", _handler)
            await real_sleep(0)

        monkeypatch.setattr(
            subscriptions.asyncio, "sleep", sleep_then_unsubscribe
        )

        assert await manager.resubscribe_all() is True
        assert calls == ["cmd/52/a/#"]
        assert "cmd/52/a/#" not in manager._subscriptions
        assert "cmd/52/a/#" not in manager._message_handlers


class TestRegistrationRaces:
    @pytest.mark.asyncio
    async def test_failed_reregistration_keeps_the_existing_callback(
        self,
    ) -> None:
        manager = _manager({})
        await manager.subscribe("cmd/52/a/#", _handler)
        # The broker forgot the topic; a re-registration of the same
        # callback is rejected.
        manager._subscriptions.clear()
        manager._connection = _manager(
            {"cmd/52/a/#": SubscribeError("cmd/52/a/#")}
        )._connection

        with pytest.raises(SubscribeError):
            await manager.subscribe("cmd/52/a/#", _handler)

        assert manager._message_handlers["cmd/52/a/#"] == [_handler]

    @pytest.mark.asyncio
    async def test_unsubscribe_during_pending_suback_leaves_topic_unmarked(
        self,
    ) -> None:
        manager = _manager({})
        suback: concurrent.futures.Future[Any] = concurrent.futures.Future()
        connection = MagicMock()
        connection.subscribe.return_value = (suback, 1)
        connection.unsubscribe.return_value = (_future({}), 2)
        manager._connection = connection

        subscribing = asyncio.create_task(
            manager.subscribe("cmd/52/a/#", _handler)
        )
        await asyncio.sleep(0)
        # The unsubscribe waits for the in-flight SUBSCRIBE, then sends
        # UNSUBSCRIBE.
        leaving = asyncio.create_task(
            manager.unsubscribe("cmd/52/a/#", _handler)
        )
        await asyncio.sleep(0)
        suback.set_result({"topic": "cmd/52/a/#", "qos": 1})
        await subscribing
        await leaving

        assert "cmd/52/a/#" not in manager._subscriptions

    @pytest.mark.asyncio
    async def test_restore_skips_a_topic_whose_unsubscribe_is_pending(
        self,
    ) -> None:
        manager = _manager({})
        await manager.subscribe("cmd/52/a/#", _handler)
        unsuback: concurrent.futures.Future[Any] = concurrent.futures.Future()
        connection = MagicMock()
        connection.unsubscribe.return_value = (unsuback, 2)
        connection.subscribe.return_value = (_future({"qos": 1}), 1)
        manager._connection = connection

        leaving = asyncio.create_task(manager.unsubscribe("cmd/52/a/#"))
        await asyncio.sleep(0)
        await manager.resubscribe_all()
        unsuback.set_result({})
        await leaving

        connection.subscribe.assert_not_called()
        assert "cmd/52/a/#" not in manager._message_handlers


class TestAbandonedAckLog:
    def test_late_rejection_logs_only_the_error_type(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        future.set_exception(SubscribeError("cmd/52/navilink-04786332fca0/#"))
        caplog.set_level(logging.DEBUG, logger="nwp500.mqtt.connection")

        MqttConnection._consume_abandoned_future(  # pyright: ignore[reportPrivateUsage]
            cast(Any, future), "Subscribe"
        )

        assert "SubscribeError" in caplog.text
        assert "04786332fca0" not in caplog.text

    @pytest.mark.asyncio
    async def test_synchronous_unsubscribe_rejection_keeps_handlers(
        self,
    ) -> None:
        manager = _manager({})
        await manager.subscribe("cmd/52/a/#", _handler)
        connection = MagicMock()
        connection.unsubscribe.side_effect = RuntimeError("not connected")
        manager._connection = connection

        with pytest.raises(RuntimeError):
            await manager.unsubscribe("cmd/52/a/#")

        assert manager._message_handlers["cmd/52/a/#"] == [_handler]
        assert "cmd/52/a/#" in manager._subscriptions
