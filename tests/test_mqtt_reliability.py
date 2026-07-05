"""Regression tests for MQTT reliability fixes.

Covers:
- Reconnection backoff loop surviving auth/library exceptions
- InvalidCredentialsError stopping reconnection with reconnection_failed
- CancelledError propagation (tasks are actually marked cancelled)
- disconnect() during an interruption disabling reconnection/periodic tasks
- Command queue flush after active/deep reconnect
- Periodic loop surviving MqttError
- Scheduled-coroutine exceptions being logged instead of dropped
- MQTT operation acknowledgement timeouts
- Backoff jitter staying within the configured maximum delay
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from awscrt import mqtt

from nwp500.auth import AuthenticationResponse, AuthTokens, UserInfo
from nwp500.exceptions import (
    InvalidCredentialsError,
    MqttNotConnectedError,
    TokenRefreshError,
)
from nwp500.mqtt.connection import MqttConnection
from nwp500.mqtt.periodic import MqttPeriodicRequestManager
from nwp500.mqtt.reconnection import MqttReconnectionHandler
from nwp500.mqtt.utils import MqttConnectionConfig, PeriodicRequestType


@pytest.fixture
def mock_auth_client():
    """Create a mock auth client with valid tokens."""
    from nwp500.auth import NavienAuthClient

    client = NavienAuthClient("test@example.com", "password")
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
    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="Test", user_last_name="User"),
        tokens=valid_tokens,
    )
    return client


def _fast_config(**overrides):
    defaults = {
        "client_id": "test-client",
        "initial_reconnect_delay": 0.001,
        "max_reconnect_delay": 0.005,
        "max_reconnect_attempts": 3,
    }
    defaults.update(overrides)
    return MqttConnectionConfig(**defaults)


def _make_handler(config, is_connected, reconnect_func, **kwargs):
    return MqttReconnectionHandler(
        config=config,
        is_connected_func=is_connected,
        schedule_coroutine_func=lambda coro: None,
        reconnect_func=reconnect_func,
        **kwargs,
    )


class TestReconnectLoopExceptionHandling:
    """The backoff loop must not be killed by library exceptions."""

    @pytest.mark.asyncio
    async def test_auth_error_counts_as_failed_attempt_and_retries(self):
        """Regression: TokenRefreshError escaped the loop's except clauses
        (it is not a RuntimeError), killing the backoff task silently."""
        attempts = []
        connected = False

        async def failing_reconnect():
            attempts.append(1)
            if len(attempts) >= 2:
                nonlocal connected
                connected = True
                return
            raise TokenRefreshError("transient network error during refresh")

        handler = _make_handler(
            _fast_config(), lambda: connected, failing_reconnect
        )
        handler.enable()

        await handler._reconnect_with_backoff()

        # First attempt raised, second succeeded — the loop survived
        assert len(attempts) == 2
        assert connected

    @pytest.mark.asyncio
    async def test_mqtt_error_counts_as_failed_attempt_and_retries(self):
        """MqttError subclasses (Nwp500Error, not RuntimeError) must be
        retried too."""
        attempts = []
        connected = False

        async def failing_reconnect():
            attempts.append(1)
            if len(attempts) >= 2:
                nonlocal connected
                connected = True
                return
            raise MqttNotConnectedError("not connected")

        handler = _make_handler(
            _fast_config(), lambda: connected, failing_reconnect
        )
        handler.enable()

        await handler._reconnect_with_backoff()

        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_invalid_credentials_stops_loop_and_emits_failed(self):
        """Rejected credentials can never succeed: stop retrying and emit
        reconnection_failed even with unlimited retries."""
        attempts = []
        events = []

        async def failing_reconnect():
            attempts.append(1)
            raise InvalidCredentialsError("bad password")

        async def emit(event, *args):
            events.append((event, args))

        handler = _make_handler(
            _fast_config(max_reconnect_attempts=-1),
            lambda: False,
            failing_reconnect,
            emit_event_func=emit,
        )
        handler.enable()

        await handler._reconnect_with_backoff()

        assert len(attempts) == 1  # no retry
        assert events and events[0][0] == "reconnection_failed"

    @pytest.mark.asyncio
    async def test_cancelled_task_is_marked_cancelled(self):
        """Regression: CancelledError was swallowed with `break`, so the
        task ended 'successfully' and could emit reconnection_failed
        during a manual disconnect."""
        started = asyncio.Event()

        async def never_reconnect():
            raise MqttNotConnectedError("still down")

        events = []

        async def emit(event, *args):
            events.append(event)

        config = _fast_config(
            initial_reconnect_delay=5.0,
            max_reconnect_delay=10.0,
            max_reconnect_attempts=2,
        )
        handler = _make_handler(
            config, lambda: False, never_reconnect, emit_event_func=emit
        )
        handler.enable()

        async def run():
            started.set()
            await handler._reconnect_with_backoff()

        task = asyncio.create_task(run())
        await started.wait()
        await asyncio.sleep(0.01)  # let it enter the backoff sleep
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()
        assert events == []  # no reconnection_failed on cancellation

    @pytest.mark.asyncio
    async def test_backoff_delay_never_exceeds_max(self):
        """Jitter must stay within max_reconnect_delay."""
        sleeps = []
        connected = False

        async def failing_reconnect():
            raise MqttNotConnectedError("down")

        config = _fast_config(
            initial_reconnect_delay=1.0,
            max_reconnect_delay=2.0,
            reconnect_backoff_multiplier=10.0,
            max_reconnect_attempts=4,
        )
        handler = _make_handler(config, lambda: connected, failing_reconnect)
        handler.enable()

        real_sleep = asyncio.sleep

        async def fake_sleep(delay):
            sleeps.append(delay)
            await real_sleep(0)

        with patch(
            "nwp500.mqtt.reconnection.asyncio.sleep", side_effect=fake_sleep
        ):
            await handler._reconnect_with_backoff()

        assert len(sleeps) == 4
        assert all(d <= config.max_reconnect_delay for d in sleeps)
        assert all(d > 0 for d in sleeps)


class TestDisconnectDuringInterruption:
    """disconnect() must fully shut down even when not connected."""

    @pytest.mark.asyncio
    async def test_disconnect_while_interrupted_stops_everything(
        self, mock_auth_client
    ):
        """Regression: disconnect() returned early when _connected was
        False, leaving the reconnect loop and periodic tasks running to
        resurrect the connection after shutdown."""
        from nwp500.mqtt import NavienMqttClient

        client = NavienMqttClient(mock_auth_client)

        client._reconnection_handler = MagicMock()
        client._reconnection_handler.disable = MagicMock()
        client._reconnection_handler.cancel = AsyncMock()
        client._periodic_manager = MagicMock()
        client._periodic_manager.stop_all_periodic_tasks = AsyncMock()
        client._connection_manager = MagicMock()
        client._connection_manager.disconnect = AsyncMock()
        client._connection_manager.close = AsyncMock()

        client._connected = False  # interrupted state

        await client.disconnect()

        client._reconnection_handler.disable.assert_called_once()
        client._reconnection_handler.cancel.assert_awaited_once()
        periodic = client._periodic_manager
        periodic.stop_all_periodic_tasks.assert_awaited_once()
        # No broker session to end, but the SDK connection is torn down
        client._connection_manager.close.assert_awaited_once()
        client._connection_manager.disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disconnect_while_connected_uses_graceful_path(
        self, mock_auth_client
    ):
        from nwp500.mqtt import NavienMqttClient

        client = NavienMqttClient(mock_auth_client)

        client._reconnection_handler = MagicMock()
        client._reconnection_handler.disable = MagicMock()
        client._reconnection_handler.cancel = AsyncMock()
        client._periodic_manager = None
        client._connection_manager = MagicMock()
        client._connection_manager.disconnect = AsyncMock()
        client._connection_manager.close = AsyncMock()

        client._connected = True

        await client.disconnect()

        client._connection_manager.disconnect.assert_awaited_once()
        client._connection_manager.close.assert_not_awaited()
        assert client._connected is False


class TestQueueFlushAfterReconnect:
    """Queued commands must be sent after active/deep reconnects."""

    @pytest.mark.asyncio
    async def test_active_reconnect_flushes_command_queue(
        self, mock_auth_client
    ):
        """Regression: a rebuilt connection never fires the SDK's
        on_connection_resumed callback, so queued commands were only sent
        on SDK auto-resume — never after an active reconnect."""
        from nwp500.mqtt import NavienMqttClient

        client = NavienMqttClient(mock_auth_client)
        client._connected = False
        client._loop = asyncio.get_running_loop()

        flushed = []

        async def fake_send_all(publish_func, is_connected):
            flushed.append(1)

        client._command_queue = MagicMock()
        client._command_queue.send_all = AsyncMock(side_effect=fake_send_all)
        client._subscription_manager = MagicMock()
        client._subscription_manager.update_connection = MagicMock()
        client._subscription_manager.resubscribe_all = AsyncMock()

        old_manager = MagicMock()
        old_manager.close = AsyncMock()
        client._connection_manager = old_manager

        new_manager = MagicMock()
        new_manager.connect = AsyncMock(return_value=True)
        new_manager.connection = MagicMock()

        with (
            patch.object(
                mock_auth_client, "ensure_valid_token", new=AsyncMock()
            ),
            patch(
                "nwp500.mqtt.client.MqttConnection",
                return_value=new_manager,
            ),
        ):
            await client._active_reconnect()

        assert client._connected is True
        sub_manager = client._subscription_manager
        sub_manager.resubscribe_all.assert_awaited_once()
        client._command_queue.send_all.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deep_reconnect_flushes_command_queue(self, mock_auth_client):
        from nwp500.mqtt import NavienMqttClient

        client = NavienMqttClient(mock_auth_client)
        client._connected = False
        client._loop = asyncio.get_running_loop()

        client._command_queue = MagicMock()
        client._command_queue.send_all = AsyncMock()
        client._subscription_manager = MagicMock()
        client._subscription_manager.update_connection = MagicMock()
        client._subscription_manager.resubscribe_all = AsyncMock()

        old_manager = MagicMock()
        old_manager.close = AsyncMock()
        client._connection_manager = old_manager

        new_manager = MagicMock()
        new_manager.connect = AsyncMock(return_value=True)
        new_manager.connection = MagicMock()

        with (
            patch.object(
                mock_auth_client,
                "refresh_token",
                new=AsyncMock(),
            ),
            patch(
                "nwp500.mqtt.client.MqttConnection",
                return_value=new_manager,
            ),
        ):
            await client._deep_reconnect()

        assert client._connected is True
        client._command_queue.send_all.assert_awaited_once()


class TestPeriodicLoopResilience:
    """The periodic request loop must survive library errors."""

    @pytest.mark.asyncio
    async def test_periodic_task_survives_mqtt_error(self):
        """Regression: MqttNotConnectedError (Nwp500Error, not
        RuntimeError) escaped the loop's except clause and permanently,
        silently killed the periodic task."""
        calls = []

        async def request_status(device):
            calls.append(1)
            if len(calls) == 1:
                raise MqttNotConnectedError("connection dropped mid-loop")

        manager = MqttPeriodicRequestManager(
            is_connected_func=lambda: True,
            request_device_info_func=AsyncMock(),
            request_device_status_func=request_status,
        )

        device = MagicMock()
        device.device_info.mac_address = "aa:bb:cc:dd:ee:ff"

        await manager.start_periodic_requests(
            device,
            period_seconds=0.01,
            request_type=PeriodicRequestType.DEVICE_STATUS,
        )
        # Give the loop time for several iterations, including the failure
        await asyncio.sleep(0.06)
        await manager.stop_all_periodic_tasks()

        # The loop continued after the first (failing) request
        assert len(calls) >= 2

    @pytest.mark.asyncio
    async def test_periodic_task_cancellation_marks_task_cancelled(self):
        manager = MqttPeriodicRequestManager(
            is_connected_func=lambda: True,
            request_device_info_func=AsyncMock(),
            request_device_status_func=AsyncMock(),
        )

        device = MagicMock()
        device.device_info.mac_address = "aa:bb:cc:dd:ee:ff"

        await manager.start_periodic_requests(
            device,
            period_seconds=10.0,
            request_type=PeriodicRequestType.DEVICE_STATUS,
        )
        await asyncio.sleep(0.01)

        task = next(iter(manager._periodic_tasks.values()))
        await manager.stop_all_periodic_tasks()

        assert task.cancelled()


class TestScheduledCoroutineExceptions:
    """Exceptions from scheduled coroutines must be logged, not dropped."""

    def test_failed_future_is_logged(self, caplog):
        from nwp500.mqtt.client import _log_scheduled_coroutine_result

        future = concurrent.futures.Future()
        future.set_exception(MqttNotConnectedError("resubscribe failed"))

        with caplog.at_level(logging.ERROR, logger="nwp500.mqtt.client"):
            _log_scheduled_coroutine_result(future)

        assert "Scheduled coroutine failed" in caplog.text
        assert "resubscribe failed" in caplog.text

    def test_cancelled_future_is_silent(self, caplog):
        from nwp500.mqtt.client import _log_scheduled_coroutine_result

        future = concurrent.futures.Future()
        future.cancel()

        with caplog.at_level(logging.ERROR, logger="nwp500.mqtt.client"):
            _log_scheduled_coroutine_result(future)

        assert caplog.text == ""

    @pytest.mark.asyncio
    async def test_schedule_coroutine_attaches_done_callback(
        self, mock_auth_client, caplog
    ):
        """End-to-end: a scheduled coroutine that raises produces a log."""
        from nwp500.mqtt import NavienMqttClient

        client = NavienMqttClient(mock_auth_client)
        client._loop = asyncio.get_running_loop()

        async def boom():
            raise MqttNotConnectedError("scheduled failure")

        with caplog.at_level(logging.ERROR, logger="nwp500.mqtt.client"):
            client._schedule_coroutine(boom())
            # Let the scheduled coroutine and its callback run
            for _ in range(5):
                await asyncio.sleep(0)

        assert "Scheduled coroutine failed" in caplog.text


class TestOperationTimeouts:
    """MQTT operations must not hang forever on half-open connections."""

    @pytest.mark.asyncio
    async def test_publish_times_out_without_ack(self, mock_auth_client):
        config = MqttConnectionConfig(
            client_id="test-client", operation_timeout=0.05
        )
        conn = MqttConnection(config, mock_auth_client)

        never_acked = concurrent.futures.Future()  # never resolves
        sdk_conn = MagicMock()
        sdk_conn.publish.return_value = (never_acked, 42)
        conn._connection = sdk_conn
        conn._connected = True

        with pytest.raises(TimeoutError):
            await conn.publish("test/topic", {"key": "value"})

    @pytest.mark.asyncio
    async def test_subscribe_times_out_without_ack(self, mock_auth_client):
        config = MqttConnectionConfig(
            client_id="test-client", operation_timeout=0.05
        )
        conn = MqttConnection(config, mock_auth_client)

        never_acked = concurrent.futures.Future()
        sdk_conn = MagicMock()
        sdk_conn.subscribe.return_value = (never_acked, 7)
        conn._connection = sdk_conn
        conn._connected = True

        with pytest.raises(TimeoutError):
            await conn.subscribe("test/topic", qos=mqtt.QoS.AT_LEAST_ONCE)

    @pytest.mark.asyncio
    async def test_publish_resolves_before_timeout(self, mock_auth_client):
        config = MqttConnectionConfig(
            client_id="test-client", operation_timeout=1.0
        )
        conn = MqttConnection(config, mock_auth_client)

        acked = concurrent.futures.Future()
        acked.set_result({"packet_id": 42})
        sdk_conn = MagicMock()
        sdk_conn.publish.return_value = (acked, 42)
        conn._connection = sdk_conn
        conn._connected = True

        packet_id = await conn.publish("test/topic", {"key": "value"})
        assert packet_id == 42
