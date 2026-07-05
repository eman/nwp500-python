"""Regression tests for MQTT threading model and event emitter fixes.

Covers:
- MQTT message dispatch marshaled from the AWS CRT thread to the event loop
- Handler registry mutation during dispatch (snapshot iteration)
- One raising handler not aborting delivery to remaining handlers
- Unit system preference visible across tasks and threads
- Once-listeners removed even when their callback raises
- Concurrent emits not double-firing once-listeners
- wait_for() cleaning up its listener on cancellation
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from nwp500.events import EventEmitter
from nwp500.mqtt.subscriptions import MqttSubscriptionManager
from nwp500.unit_system import (
    get_unit_system,
    reset_unit_system,
    set_unit_system,
)


@pytest.fixture(autouse=True)
def _reset_units():
    yield
    reset_unit_system()


def _make_manager(loop: asyncio.AbstractEventLoop) -> MqttSubscriptionManager:
    def schedule(coro):
        asyncio.run_coroutine_threadsafe(coro, loop)

    return MqttSubscriptionManager(
        connection=object(),
        client_id="test-client",
        event_emitter=EventEmitter(),
        schedule_coroutine=schedule,
    )


class TestDispatchThreading:
    """Message parse/dispatch must run on the event loop, not the CRT
    thread."""

    @pytest.mark.asyncio
    async def test_message_from_foreign_thread_dispatches_on_loop(self):
        """Regression: JSON decode, model validation, and user callbacks
        all ran on the AWS CRT network thread — blocking callbacks
        stalled MQTT processing and shared state was touched off-loop."""
        loop = asyncio.get_running_loop()
        manager = _make_manager(loop)

        received = asyncio.Event()
        seen: dict = {}

        def handler(topic, message):
            seen["thread"] = threading.get_ident()
            seen["message"] = message
            loop.call_soon(received.set)

        manager._message_handlers["cmd/52/+/st"] = [handler]

        payload = json.dumps({"key": "value"}).encode()

        # Simulate the awscrt callback arriving on a foreign thread
        crt_thread = threading.Thread(
            target=manager._on_message_received,
            args=("cmd/52/navilink-test/st", payload),
        )
        crt_thread.start()
        crt_thread.join()

        await asyncio.wait_for(received.wait(), timeout=2.0)

        assert seen["message"] == {"key": "value"}
        assert seen["thread"] == threading.get_ident()  # event loop thread

    @pytest.mark.asyncio
    async def test_handler_mutating_registry_during_dispatch(self):
        """Regression: dispatch iterated the live handler dict; a
        subscribe/unsubscribe during delivery raised 'dictionary changed
        size during iteration' and dropped the message."""
        loop = asyncio.get_running_loop()
        manager = _make_manager(loop)

        calls = []

        def mutating_handler(topic, message):
            calls.append("mutating")
            # Mutate both registries mid-dispatch
            manager._message_handlers["cmd/52/other/topic"] = [
                lambda t, m: None
            ]
            manager._message_handlers.pop("cmd/52/+/st", None)

        def second_handler(topic, message):
            calls.append("second")

        manager._message_handlers["cmd/52/+/st"] = [
            mutating_handler,
            second_handler,
        ]

        await manager._dispatch_message(
            "cmd/52/navilink-test/st", json.dumps({}).encode()
        )

        assert calls == ["mutating", "second"]

    @pytest.mark.asyncio
    async def test_raising_handler_does_not_block_others(self):
        """Regression: only (TypeError, AttributeError, KeyError) were
        caught; a handler raising ValueError escaped into the awscrt
        callback machinery and aborted delivery to remaining handlers."""
        loop = asyncio.get_running_loop()
        manager = _make_manager(loop)

        calls = []

        def bad_handler(topic, message):
            raise ValueError("boom")

        def good_handler(topic, message):
            calls.append("good")

        manager._message_handlers["cmd/52/+/st"] = [bad_handler, good_handler]

        await manager._dispatch_message(
            "cmd/52/navilink-test/st", json.dumps({}).encode()
        )

        assert calls == ["good"]

    @pytest.mark.asyncio
    async def test_invalid_json_is_logged_not_raised(self, caplog):
        loop = asyncio.get_running_loop()
        manager = _make_manager(loop)
        manager._message_handlers["t"] = [lambda t, m: None]

        # Must not raise
        await manager._dispatch_message("t", b"{not json")

        assert "Failed to parse message payload" in caplog.text


class TestUnitSystemVisibility:
    """The unit system preference must be process-wide."""

    @pytest.mark.asyncio
    async def test_visible_in_task_scheduled_from_foreign_thread(self):
        """Regression: the preference was a ContextVar set in the main
        task; tasks scheduled via run_coroutine_threadsafe from the CRT
        thread never inherited it, so --unit-system was silently ignored
        for all MQTT-delivered data."""
        loop = asyncio.get_running_loop()
        set_unit_system("metric")

        result: dict = {}
        done = asyncio.Event()

        async def read_preference():
            result["unit_system"] = get_unit_system()
            done.set()

        def foreign_thread():
            asyncio.run_coroutine_threadsafe(read_preference(), loop)

        thread = threading.Thread(target=foreign_thread)
        thread.start()
        thread.join()

        await asyncio.wait_for(done.wait(), timeout=2.0)
        assert result["unit_system"] == "metric"

    def test_visible_across_plain_threads(self):
        set_unit_system("us_customary")
        seen = {}

        def reader():
            seen["value"] = get_unit_system()

        thread = threading.Thread(target=reader)
        thread.start()
        thread.join()

        assert seen["value"] == "us_customary"

    def test_reset_restores_auto_detect(self):
        set_unit_system("metric")
        reset_unit_system()
        assert get_unit_system() is None


class TestOnceListeners:
    """Once-listeners must fire exactly once, no matter what."""

    @pytest.mark.asyncio
    async def test_raising_once_listener_is_still_removed(self):
        """Regression: removal happened after the callback inside the
        try block; a raising callback skipped removal and fired on every
        subsequent emit."""
        emitter = EventEmitter()
        calls = []

        def bad_handler():
            calls.append(1)
            raise ValueError("boom")

        emitter.once("evt", bad_handler)

        await emitter.emit("evt")
        await emitter.emit("evt")

        assert len(calls) == 1
        assert emitter.listener_count("evt") == 0

    @pytest.mark.asyncio
    async def test_concurrent_emits_fire_once_listener_once(self):
        """Regression: removal was deferred until after the (awaited)
        iteration; overlapping emits each snapshotted the listener list
        before either removed, double-firing once-listeners."""
        emitter = EventEmitter()
        calls = []

        async def slow_handler():
            calls.append(1)
            await asyncio.sleep(0.01)

        emitter.once("evt", slow_handler)

        await asyncio.gather(emitter.emit("evt"), emitter.emit("evt"))

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_regular_listeners_survive_emit(self):
        emitter = EventEmitter()
        calls = []
        emitter.on("evt", lambda: calls.append(1))

        await emitter.emit("evt")
        await emitter.emit("evt")

        assert len(calls) == 2
        assert emitter.listener_count("evt") == 1


class TestWaitForCleanup:
    """wait_for() must never leak its listener."""

    @pytest.mark.asyncio
    async def test_cancellation_removes_listener(self):
        """Regression: only TimeoutError removed the listener; a
        cancelled waiter left it registered until the event next fired,
        setting a result on a dead future."""
        emitter = EventEmitter()

        task = asyncio.create_task(emitter.wait_for("evt"))
        await asyncio.sleep(0.01)  # let the listener register
        assert emitter.listener_count("evt") == 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert emitter.listener_count("evt") == 0
        # A later emit must not blow up on the dead future
        await emitter.emit("evt")

    @pytest.mark.asyncio
    async def test_timeout_removes_listener(self):
        emitter = EventEmitter()

        with pytest.raises(TimeoutError):
            await emitter.wait_for("evt", timeout=0.01)

        assert emitter.listener_count("evt") == 0

    @pytest.mark.asyncio
    async def test_successful_wait_returns_args(self):
        emitter = EventEmitter()

        async def fire():
            await asyncio.sleep(0.01)
            await emitter.emit("evt", "payload")

        fire_task = asyncio.create_task(fire())
        args = await emitter.wait_for("evt", timeout=1.0)
        await fire_task

        assert args == ("payload",)
        assert emitter.listener_count("evt") == 0
