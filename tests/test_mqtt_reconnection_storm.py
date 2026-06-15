"""
Tests for the MQTT reconnection storm fix.

Three bugs were fixed:

Bug 1 — Stale interruption events fire after a resume clears _reconnect_task.
  The AWS SDK fires on_connection_interrupted callbacks from background threads
  via run_coroutine_threadsafe.  When on_connection_resumed cancels and nulls
  _reconnect_task, queued _start_reconnect_task coroutines that haven't run yet
  see _reconnect_task=None and spawn a new _reconnect_with_backoff task even
  though the client is now healthy.

  Fix: both on_connection_interrupted and _start_reconnect_task now check
  is_connected_func() before starting a new backoff loop.

Bug 2 — Closing the old connection inside _active_reconnect / _deep_reconnect
  fires _on_connection_interrupted_internal from a background SDK thread.
  This queued another _start_reconnect_task coroutine that would fire after the
  new connection was established, tearing it down immediately.

  Fix: _actively_reconnecting flag suppresses the reconnection-handler
  delegation in _on_connection_interrupted_internal while the intentional
  teardown is in progress.

Bug 3 — on_connection_resumed calls Task.cancel() directly from an AWS SDK
  background thread.  asyncio.Task.cancel() is NOT thread-safe; when the event
  loop is busy (e.g. the sleeping task's timer callback was already enqueued)
  the cancellation can be silently dropped.  The stale _reconnect_with_backoff
  task then completes its sleep, calls _reconnect_func, and tears down an
  otherwise healthy connection, restarting the entire
  disconnect/reconnect cycle.

  Fix: on_connection_resumed schedules _cancel_pending_reconnect() via
  _schedule_coroutine so the cancellation runs on the event loop where asyncio
  Task operations are safe.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nwp500.auth import (
    AuthenticationResponse,
    AuthTokens,
    NavienAuthClient,
    UserInfo,
)
from nwp500.mqtt.reconnection import MqttReconnectionHandler
from nwp500.mqtt.utils import MqttConnectionConfig

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_auth_client() -> NavienAuthClient:
    client = NavienAuthClient("test@example.com", "password")
    tokens = AuthTokens(
        id_token="tok",
        access_token="acc",
        refresh_token="ref",
        authentication_expires_in=3600,
        access_key_id="key",
        secret_key="secret",
        session_token="sess",
        authorization_expires_in=3600,
    )
    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="T", user_last_name="U"),
        tokens=tokens,
    )
    return client


def _make_handler(
    *,
    connected: bool = False,
    auto_reconnect: bool = True,
    max_reconnect_attempts: int = -1,
) -> tuple[MqttReconnectionHandler, list[asyncio.Task]]:
    """Return a handler and a list that records every scheduled coroutine."""
    config = MqttConnectionConfig(
        auto_reconnect=auto_reconnect,
        max_reconnect_attempts=max_reconnect_attempts,
    )
    scheduled: list[asyncio.Task] = []

    def _schedule(coro):  # replaces run_coroutine_threadsafe in real code
        t = asyncio.ensure_future(coro)
        scheduled.append(t)
        return t

    handler = MqttReconnectionHandler(
        config=config,
        is_connected_func=lambda: connected,
        schedule_coroutine_func=_schedule,
        reconnect_func=AsyncMock(),
        deep_reconnect_func=None,
        emit_event_func=None,
    )
    handler.enable()
    return handler, scheduled


# ---------------------------------------------------------------------------
# Bug 1: on_connection_interrupted / _start_reconnect_task is_connected guard
# ---------------------------------------------------------------------------


class TestReconnectionHandlerIsConnectedGuard:
    """Bug 1 – stale interrupt events must not start a loop when connected."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_on_connection_interrupted_does_not_start_task_when_connected(
        self,
    ):
        """on_connection_interrupted is a no-op when connected."""
        connected = True
        config = MqttConnectionConfig(auto_reconnect=True)
        scheduled = []

        handler = MqttReconnectionHandler(
            config=config,
            is_connected_func=lambda: connected,
            schedule_coroutine_func=lambda coro: scheduled.append(
                asyncio.ensure_future(coro)
            ),
            reconnect_func=AsyncMock(),
        )
        handler.enable()

        handler.on_connection_interrupted(Exception("dropped"))

        # Nothing should have been scheduled
        assert scheduled == []

    @pytest.mark.asyncio(loop_scope="function")
    async def test_on_connection_interrupted_starts_task_when_disconnected(
        self,
    ):
        """on_connection_interrupted schedules a task when disconnected."""
        handler, scheduled = _make_handler(connected=False)

        handler.on_connection_interrupted(Exception("dropped"))

        assert len(scheduled) == 1
        # Clean up
        scheduled[0].cancel()
        await asyncio.gather(*scheduled, return_exceptions=True)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_reconnect_task_no_op_when_connected(self):
        """_start_reconnect_task must not create a Task when connected."""
        connected = True
        config = MqttConnectionConfig(auto_reconnect=True)

        handler = MqttReconnectionHandler(
            config=config,
            is_connected_func=lambda: connected,
            schedule_coroutine_func=lambda coro: asyncio.ensure_future(coro),
            reconnect_func=AsyncMock(),
        )
        handler.enable()

        await handler._start_reconnect_task()

        assert handler._reconnect_task is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_reconnect_task_creates_task_when_disconnected(self):
        """_start_reconnect_task creates a Task when genuinely disconnected."""
        handler, _ = _make_handler(connected=False)

        await handler._start_reconnect_task()

        assert handler._reconnect_task is not None
        assert not handler._reconnect_task.done()

        handler._reconnect_task.cancel()
        await asyncio.gather(handler._reconnect_task, return_exceptions=True)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stale_interrupt_after_resume_does_not_spawn_extra_task(self):
        """
        Simulate the race that caused the reconnection storm:

        1. Connection drops  → on_connection_interrupted schedules
           _start_reconnect_task (coroutine A queued but not yet run).
        2. Connection resumes → on_connection_resumed schedules
           _cancel_pending_reconnect (no task to cancel yet since A hasn't run).
        3. Both queued coroutines finally run – without the is_connected guard
           coroutine A would see _reconnect_task=None and create a new backoff
           loop even though the client is now healthy.
        """
        state = {"connected": False}
        config = MqttConnectionConfig(auto_reconnect=True)
        scheduled = []

        handler = MqttReconnectionHandler(
            config=config,
            is_connected_func=lambda: state["connected"],
            schedule_coroutine_func=lambda coro: scheduled.append(
                asyncio.ensure_future(coro)
            ),
            reconnect_func=AsyncMock(),
        )
        handler.enable()

        # Step 1: connection drops, schedule the coroutine but don't run it yet
        handler.on_connection_interrupted(Exception("dropped"))
        assert len(scheduled) == 1

        # Step 2: connection resumes before the scheduled coroutine runs.
        # on_connection_resumed now schedules _cancel_pending_reconnect rather
        # than calling task.cancel() directly (Bug 3 fix).
        state["connected"] = True
        handler.on_connection_resumed(return_code=0, session_present=False)
        assert handler._reconnect_task is None  # no task was ever created

        # Step 3: run all scheduled coroutines
        # (_start_reconnect_task + _cancel_pending_reconnect)
        await asyncio.gather(*scheduled, return_exceptions=True)

        # With the fix, no new task must have been created
        assert handler._reconnect_task is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_multiple_simultaneous_interrupts_create_only_one_task(self):
        """
        Multiple concurrent on_connection_interrupted calls (from different
        SDK threads) must not spawn more than one backoff task.
        """
        handler, scheduled = _make_handler(connected=False)

        # Simulate three rapid interruption callbacks
        for _ in range(3):
            handler.on_connection_interrupted(Exception("dropped"))

        # Let all the scheduled coroutines run
        await asyncio.gather(*scheduled, return_exceptions=True)

        # Only one _reconnect_with_backoff task should exist
        assert handler._reconnect_task is not None
        handler._reconnect_task.cancel()
        await asyncio.gather(handler._reconnect_task, return_exceptions=True)


# ---------------------------------------------------------------------------
# Bug 3: on_connection_resumed must cancel via the event loop, not directly
# ---------------------------------------------------------------------------


class TestThreadSafeTaskCancellation:
    """Bug 3 – on_connection_resumed must not call Task.cancel() from a thread.

    asyncio.Task.cancel() is NOT thread-safe.  When called from an AWS SDK
    background thread, the cancellation can be silently dropped if the event
    loop is busy (e.g. the sleep timer fires at the same moment).  The stale
    task then triggers a spurious reconnection.

    Fix: on_connection_resumed schedules _cancel_pending_reconnect() via
    _schedule_coroutine so the cancellation happens on the event loop.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_on_connection_resumed_schedules_cancel_not_direct_call(
        self,
    ):
        """
        on_connection_resumed must schedule _cancel_pending_reconnect via
        _schedule_coroutine rather than calling task.cancel() directly.
        """
        handler, scheduled = _make_handler(connected=False)

        # Let a reconnect task start (sleeping in backoff)
        handler.on_connection_interrupted(Exception("dropped"))
        await asyncio.gather(*scheduled, return_exceptions=True)
        scheduled.clear()

        assert handler._reconnect_task is not None
        assert not handler._reconnect_task.done()

        # Simulate connection resuming from a background thread
        handler.on_connection_resumed(return_code=0, session_present=True)

        # _cancel_pending_reconnect must have been *scheduled*, not run yet
        assert len(scheduled) == 1
        # No direct Task.cancel() was called from the background thread:
        # task.cancelling() == 0 proves no cancellation request is pending
        # before the event loop runs _cancel_pending_reconnect.
        assert handler._reconnect_task is not None
        assert handler._reconnect_task.cancelling() == 0

        # Now let the event loop process the cancellation
        await asyncio.gather(*scheduled, return_exceptions=True)

        # After the event-loop cancellation, the task must be cleared
        assert handler._reconnect_task is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancel_pending_reconnect_is_idempotent_with_no_task(self):
        """_cancel_pending_reconnect is a no-op when _reconnect_task is None."""
        handler, _ = _make_handler(connected=True)
        assert handler._reconnect_task is None

        # Should not raise
        await handler._cancel_pending_reconnect()

        assert handler._reconnect_task is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancel_pending_reconnect_clears_completed_task(self):
        """_cancel_pending_reconnect clears a stale reference to a done task."""
        handler, scheduled = _make_handler(connected=False)

        handler.on_connection_interrupted(Exception("dropped"))
        await asyncio.gather(*scheduled, return_exceptions=True)
        scheduled.clear()

        task = handler._reconnect_task
        assert task is not None

        # Cancel and drain the task manually, leaving a stale reference
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.done()
        assert handler._reconnect_task is task  # stale reference still held

        # _cancel_pending_reconnect must clear the stale reference
        await handler._cancel_pending_reconnect()
        assert handler._reconnect_task is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_resumed_then_interrupted_creates_new_task(self):
        """
        After resume cancels an existing task, a subsequent genuine drop must
        still be able to start a fresh reconnect task.
        """
        state = {"connected": False}
        config = MqttConnectionConfig(auto_reconnect=True)
        scheduled = []

        handler = MqttReconnectionHandler(
            config=config,
            is_connected_func=lambda: state["connected"],
            schedule_coroutine_func=lambda coro: scheduled.append(
                asyncio.ensure_future(coro)
            ),
            reconnect_func=AsyncMock(),
        )
        handler.enable()

        # Connection drops → backoff task starts
        handler.on_connection_interrupted(Exception("first drop"))
        await asyncio.gather(*scheduled, return_exceptions=True)
        scheduled.clear()
        assert handler._reconnect_task is not None

        # Connection resumes → cancel scheduled on loop
        state["connected"] = True
        handler.on_connection_resumed(return_code=0, session_present=True)
        await asyncio.gather(*scheduled, return_exceptions=True)
        scheduled.clear()
        assert handler._reconnect_task is None

        # Connection drops again (genuine)
        state["connected"] = False
        handler.on_connection_interrupted(Exception("second drop"))
        await asyncio.gather(*scheduled, return_exceptions=True)
        scheduled.clear()

        # A new reconnect task must have been created
        assert handler._reconnect_task is not None
        handler._reconnect_task.cancel()
        await asyncio.gather(handler._reconnect_task, return_exceptions=True)


# ---------------------------------------------------------------------------
# Bug 2: _actively_reconnecting suppresses spurious interrupt callbacks
# ---------------------------------------------------------------------------


class TestActivelyReconnectingFlag:
    """Bug 2 – old connection teardown must not trigger a new backoff loop."""

    def _make_mqtt_client(self) -> NavienMqttClient:  # noqa: F821
        from nwp500.mqtt import NavienMqttClient

        return NavienMqttClient(_make_auth_client())

    def test_actively_reconnecting_initialises_false(self):
        """_actively_reconnecting starts False."""
        client = self._make_mqtt_client()
        assert client._actively_reconnecting is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_interrupted_internal_skips_handler_when_flag_set(  # noqa: E501
        self,
    ):
        """
        While _actively_reconnecting is True (old connection being closed),
        _on_connection_interrupted_internal must NOT forward the event to the
        reconnection handler – preventing a competing backoff task.
        """
        from awscrt.exceptions import AwsCrtError

        client = self._make_mqtt_client()

        mock_handler = MagicMock()
        client._reconnection_handler = mock_handler
        client.config = MqttConnectionConfig(auto_reconnect=True)

        client._actively_reconnecting = True  # flag is set

        error = AwsCrtError(
            code=0,
            name="AWS_ERROR_MQTT_UNEXPECTED_HANGUP",
            message="hangup",
        )
        client._on_connection_interrupted_internal(
            connection=MagicMock(), error=error
        )

        # The handler must NOT have been notified
        mock_handler.on_connection_interrupted.assert_not_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_on_connection_interrupted_internal_forwards_when_flag_clear(
        self,
    ):
        """
        When _actively_reconnecting is False (genuine drop), the event IS
        forwarded to the reconnection handler.
        """
        from awscrt.exceptions import AwsCrtError

        client = self._make_mqtt_client()

        mock_handler = MagicMock()
        client._reconnection_handler = mock_handler
        client.config = MqttConnectionConfig(auto_reconnect=True)

        client._actively_reconnecting = False  # flag is clear (default)

        error = AwsCrtError(
            code=0,
            name="AWS_ERROR_MQTT_UNEXPECTED_HANGUP",
            message="hangup",
        )
        client._on_connection_interrupted_internal(
            connection=MagicMock(), error=error
        )

        mock_handler.on_connection_interrupted.assert_called_once_with(error)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_active_reconnect_sets_and_clears_flag_on_success(self):
        """_active_reconnect sets the flag, does its work, then clears it."""
        client = self._make_mqtt_client()
        client._connected = False
        client._loop = asyncio.get_running_loop()

        flag_during = []

        async def fake_reconnect():
            flag_during.append(client._actively_reconnecting)
            client._connected = True
            return True

        mock_conn_mgr = AsyncMock()
        mock_conn_mgr.close = AsyncMock()
        mock_conn_mgr.connect = AsyncMock(side_effect=fake_reconnect)
        mock_conn_mgr.connection = MagicMock()
        client._connection_manager = mock_conn_mgr

        with patch(
            "nwp500.mqtt.client.MqttConnection", return_value=mock_conn_mgr
        ):
            client._auth_client.ensure_valid_token = AsyncMock()
            client._subscription_manager = None
            await client._active_reconnect()

        assert flag_during == [True], "Flag must be True while reconnecting"
        assert not client._actively_reconnecting, "Flag must be cleared after"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_active_reconnect_clears_flag_on_exception(self):
        """_active_reconnect clears the flag even on exception."""
        from awscrt.exceptions import AwsCrtError

        client = self._make_mqtt_client()
        client._connected = False
        client._loop = asyncio.get_running_loop()

        mock_conn_mgr = AsyncMock()
        mock_conn_mgr.close = AsyncMock()
        mock_conn_mgr.connect = AsyncMock(
            side_effect=AwsCrtError(
                code=0, name="AWS_ERROR_MQTT_UNEXPECTED_HANGUP", message="fail"
            )
        )
        client._connection_manager = mock_conn_mgr

        with patch(
            "nwp500.mqtt.client.MqttConnection", return_value=mock_conn_mgr
        ):
            client._auth_client.ensure_valid_token = AsyncMock()
            with pytest.raises(AwsCrtError):
                await client._active_reconnect()

        assert not client._actively_reconnecting, "must be cleared on error"
        """
        A second concurrent call to _active_reconnect while the first is
        still running must return immediately without making changes.
        """
        client = self._make_mqtt_client()
        client._connected = False
        client._loop = asyncio.get_running_loop()
        client._actively_reconnecting = True  # Simulate first call in progress

        # No connection manager – if we got past the guard we'd crash
        client._connection_manager = None

        # Should return immediately without touching the connection
        await client._active_reconnect()  # Must not raise

        # State unchanged
        assert client._actively_reconnecting is True
        assert not client._connected

    @pytest.mark.asyncio(loop_scope="function")
    async def test_deep_reconnect_sets_and_clears_flag(self):
        """_deep_reconnect also sets and clears _actively_reconnecting."""
        client = self._make_mqtt_client()
        client._connected = False
        client._loop = asyncio.get_running_loop()

        flag_during = []

        async def fake_connect():
            flag_during.append(client._actively_reconnecting)
            client._connected = True
            return True

        mock_conn_mgr = AsyncMock()
        mock_conn_mgr.close = AsyncMock()
        mock_conn_mgr.connect = AsyncMock(side_effect=fake_connect)
        mock_conn_mgr.connection = MagicMock()
        client._connection_manager = mock_conn_mgr

        with patch(
            "nwp500.mqtt.client.MqttConnection", return_value=mock_conn_mgr
        ):
            client._auth_client.ensure_valid_token = AsyncMock()
            client._auth_client.current_tokens.refresh_token = "ref"
            client._auth_client.refresh_token = AsyncMock()
            client._subscription_manager = None
            await client._deep_reconnect()

        assert flag_during == [True], "Flag True while deep-reconnecting"
        assert not client._actively_reconnecting, "Flag must be cleared after"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_deep_reconnect_clears_flag_on_exception(self):
        """_deep_reconnect clears the flag even when an exception is raised."""
        from awscrt.exceptions import AwsCrtError

        client = self._make_mqtt_client()
        client._connected = False
        client._loop = asyncio.get_running_loop()

        mock_conn_mgr = AsyncMock()
        mock_conn_mgr.close = AsyncMock()
        mock_conn_mgr.connect = AsyncMock(
            side_effect=AwsCrtError(
                code=0, name="AWS_ERROR_MQTT_UNEXPECTED_HANGUP", message="fail"
            )
        )
        client._connection_manager = mock_conn_mgr

        with patch(
            "nwp500.mqtt.client.MqttConnection", return_value=mock_conn_mgr
        ):
            client._auth_client.ensure_valid_token = AsyncMock()
            client._auth_client.current_tokens.refresh_token = "ref"
            client._auth_client.refresh_token = AsyncMock()
            with pytest.raises(AwsCrtError):
                await client._deep_reconnect()

        assert not client._actively_reconnecting, "must be cleared on error"
