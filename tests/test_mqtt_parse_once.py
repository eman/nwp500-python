"""Each message is parsed and announced once, however many callbacks."""

import asyncio
import concurrent.futures
import json
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from nwp500.models import Device, DeviceStatus
from nwp500.mqtt.subscriptions import MqttSubscriptionManager
from nwp500.mqtt_events import MqttClientEvents


def _resolved(value: Any) -> concurrent.futures.Future[Any]:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    future.set_result(value)
    return future


@pytest.mark.asyncio
async def test_two_status_callbacks_share_one_parse_and_one_event(
    device_status_dict: dict[str, Any],
) -> None:
    connection = MagicMock()

    def subscribe(
        topic: str, qos: Any, callback: Any
    ) -> tuple[concurrent.futures.Future[Any], int]:
        return _resolved({"topic": topic, "qos": qos}), 1

    connection.subscribe.side_effect = subscribe
    emitter = MagicMock()
    scheduled: list[Any] = []

    def schedule(coro: Any) -> None:
        scheduled.append(coro)
        coro.close()

    manager = MqttSubscriptionManager(
        connection=connection,
        client_id="test-client",
        event_emitter=emitter,
        schedule_coroutine=schedule,
    )
    device = MagicMock()
    device.device_info.mac_address = "04786332fca0"
    device.device_info.device_type = 52
    got_a: list[DeviceStatus] = []
    got_b: list[DeviceStatus] = []
    await manager.subscribe_device_status(cast(Device, device), got_a.append)
    await manager.subscribe_device_status(cast(Device, device), got_b.append)

    message = {"response": {"status": device_status_dict}}
    real_validate = DeviceStatus.model_validate
    with patch.object(
        DeviceStatus, "model_validate", side_effect=real_validate
    ) as validate:
        await manager._dispatch_message(
            "cmd/52/navilink-04786332fca0/st", json.dumps(message).encode()
        )

    assert validate.call_count == 1
    assert len(got_a) == len(got_b) == 1
    assert got_a[0] is got_b[0]
    status_emits = [
        c
        for c in emitter.emit.call_args_list
        if c.args[0] == MqttClientEvents.STATUS_RECEIVED
    ]
    assert len(status_emits) == 1


@pytest.mark.asyncio
async def test_unacknowledged_unsubscribe_resubscribes_next_time() -> None:
    """A lost UNSUBACK must not leave the topic marked subscribed."""
    connection = MagicMock()

    def subscribe(
        topic: str, qos: Any, callback: Any
    ) -> tuple[concurrent.futures.Future[Any], int]:
        return _resolved({"topic": topic, "qos": qos}), 1

    connection.subscribe.side_effect = subscribe
    never: concurrent.futures.Future[Any] = concurrent.futures.Future()
    connection.unsubscribe.return_value = (never, 2)
    manager = MqttSubscriptionManager(
        connection=connection,
        client_id="test-client",
        event_emitter=MagicMock(),
        schedule_coroutine=lambda coro: coro.close(),
    )
    manager._operation_timeout = 0.01
    device = MagicMock()
    device.device_info.mac_address = "04786332fca0"
    device.device_info.device_type = 52

    def first(status: DeviceStatus) -> None: ...

    def second(status: DeviceStatus) -> None: ...

    await manager.subscribe_device_status(cast(Device, device), first)
    with pytest.raises(TimeoutError):
        await manager.unsubscribe_device_status(cast(Device, device), first)
    await manager.subscribe_device_status(cast(Device, device), second)

    assert connection.subscribe.call_count == 2


@pytest.mark.asyncio
async def test_subscribe_during_pending_unsuback_sends_subscribe() -> None:
    """A handler added while UNSUBACK is pending gets its own SUBSCRIBE."""
    connection = MagicMock()

    def subscribe(
        topic: str, qos: Any, callback: Any
    ) -> tuple[concurrent.futures.Future[Any], int]:
        return _resolved({"topic": topic, "qos": qos}), 1

    connection.subscribe.side_effect = subscribe
    unsuback: concurrent.futures.Future[Any] = concurrent.futures.Future()
    connection.unsubscribe.return_value = (unsuback, 2)
    manager = MqttSubscriptionManager(
        connection=connection,
        client_id="test-client",
        event_emitter=MagicMock(),
        schedule_coroutine=lambda coro: coro.close(),
    )
    device = MagicMock()
    device.device_info.mac_address = "04786332fca0"
    device.device_info.device_type = 52
    topic = "cmd/52/navilink-04786332fca0/#"

    def first(status: DeviceStatus) -> None: ...

    def second(status: DeviceStatus) -> None: ...

    await manager.subscribe_device_status(cast(Device, device), first)
    pending = asyncio.create_task(
        manager.unsubscribe_device_status(cast(Device, device), first)
    )
    await asyncio.sleep(0)
    joining = asyncio.create_task(
        manager.subscribe_device_status(cast(Device, device), second)
    )
    await asyncio.sleep(0)
    unsuback.set_result({})
    await pending
    await joining

    assert connection.subscribe.call_count == 2
    assert topic in manager._subscriptions
    assert len(manager._message_handlers[topic]) == 1


@pytest.mark.asyncio
async def test_late_suback_does_not_mark_an_unsubscribed_topic() -> None:
    """An unsubscribe waits for an in-flight SUBSCRIBE, then removes it."""
    connection = MagicMock()
    suback: concurrent.futures.Future[Any] = concurrent.futures.Future()
    connection.subscribe.return_value = (suback, 1)
    connection.unsubscribe.return_value = (_resolved({}), 2)
    manager = MqttSubscriptionManager(
        connection=connection,
        client_id="test-client",
        event_emitter=MagicMock(),
        schedule_coroutine=lambda coro: coro.close(),
    )
    device = MagicMock()
    device.device_info.mac_address = "04786332fca0"
    device.device_info.device_type = 52
    topic = "cmd/52/navilink-04786332fca0/#"

    def first(status: DeviceStatus) -> None: ...

    subscribing = asyncio.create_task(
        manager.subscribe_device_status(cast(Device, device), first)
    )
    await asyncio.sleep(0)
    leaving = asyncio.create_task(
        manager.unsubscribe_device_status(cast(Device, device), first)
    )
    await asyncio.sleep(0)
    suback.set_result({"topic": topic, "qos": 1})
    await subscribing
    await leaving

    assert connection.unsubscribe.call_count == 1
    assert topic not in manager._subscriptions
    assert topic not in manager._message_handlers


@pytest.mark.asyncio
async def test_unsubscribe_while_offline_removes_the_callback() -> None:
    """Offline, the callback is removed without a broker call."""
    connection = MagicMock()

    def subscribe(
        topic: str, qos: Any, callback: Any
    ) -> tuple[concurrent.futures.Future[Any], int]:
        return _resolved({"topic": topic, "qos": qos}), 1

    connection.subscribe.side_effect = subscribe
    online = [True]
    manager = MqttSubscriptionManager(
        connection=connection,
        client_id="test-client",
        event_emitter=MagicMock(),
        schedule_coroutine=lambda coro: coro.close(),
        is_online=lambda: online[0],
    )
    device = MagicMock()
    device.device_info.mac_address = "04786332fca0"
    device.device_info.device_type = 52
    topic = "cmd/52/navilink-04786332fca0/#"

    def first(status: DeviceStatus) -> None: ...

    await manager.subscribe_device_status(cast(Device, device), first)
    online[0] = False
    await manager.unsubscribe_device_status(cast(Device, device), first)

    connection.unsubscribe.assert_not_called()
    assert topic not in manager._message_handlers
    assert topic not in manager._subscriptions
    # Nothing is left for the next reconnect to restore.
    online[0] = True
    await manager.resubscribe_all()
    assert connection.subscribe.call_count == 1


def _manager(connection: Any, **kw: Any) -> MqttSubscriptionManager:
    return MqttSubscriptionManager(
        connection=connection,
        client_id="test-client",
        event_emitter=MagicMock(),
        schedule_coroutine=lambda coro: coro.close(),
        **kw,
    )


def _granted(
    topic: str, qos: Any, callback: Any
) -> tuple[concurrent.futures.Future[Any], int]:
    return _resolved({"topic": topic, "qos": qos}), 1


def _noop(topic: str, message: dict[str, Any]) -> None:
    del topic, message


@pytest.mark.asyncio
async def test_reconnect_keeps_a_subscriber_joining_during_unsuback() -> None:
    """Pending UNSUBACK, a joining subscriber and another active topic."""
    connection = MagicMock()
    connection.subscribe.side_effect = _granted
    unsuback: concurrent.futures.Future[Any] = concurrent.futures.Future()
    connection.unsubscribe.return_value = (unsuback, 2)
    manager = _manager(connection)
    await manager.subscribe("cmd/52/a/#", _noop)
    await manager.subscribe("cmd/52/b/#", _noop)

    def joiner(topic: str, message: dict[str, Any]) -> None:
        del topic, message

    leaving = asyncio.create_task(manager.unsubscribe("cmd/52/a/#", _noop))
    await asyncio.sleep(0)
    joining = asyncio.create_task(manager.subscribe("cmd/52/a/#", joiner))
    await asyncio.sleep(0)
    # Reconnect while the UNSUBACK is pending; b is still active.
    await manager.resubscribe_all()
    unsuback.set_result({})
    await leaving
    await joining

    assert manager._message_handlers["cmd/52/a/#"] == [joiner]
    assert "cmd/52/a/#" in manager._subscriptions


@pytest.mark.asyncio
async def test_late_suback_after_offline_removal_leaves_no_mark() -> None:
    """Offline removal of the last callback; the SUBACK lands later."""
    connection = MagicMock()
    suback: concurrent.futures.Future[Any] = concurrent.futures.Future()
    connection.subscribe.return_value = (suback, 1)
    online = [True]
    manager = _manager(connection, is_online=lambda: online[0])

    subscribing = asyncio.create_task(manager.subscribe("cmd/52/a/#", _noop))
    await asyncio.sleep(0)
    online[0] = False
    await manager.unsubscribe("cmd/52/a/#", _noop)
    suback.set_result({"topic": "cmd/52/a/#", "qos": 1})
    await subscribing

    assert "cmd/52/a/#" not in manager._subscriptions
    # On the rebuilt connection the next subscriber sends SUBSCRIBE.
    online[0] = True
    connection.subscribe.reset_mock()
    connection.subscribe.side_effect = _granted
    await manager.subscribe("cmd/52/a/#", _noop)
    connection.subscribe.assert_called_once()


@pytest.mark.asyncio
async def test_remove_all_keeps_a_callback_added_while_it_waited() -> None:
    """SUBACK pending, then unsubscribe(topic), then a new subscribe()."""
    connection = MagicMock()
    suback: concurrent.futures.Future[Any] = concurrent.futures.Future()
    connection.subscribe.return_value = (suback, 1)
    connection.unsubscribe.return_value = (_resolved({}), 2)
    manager = _manager(connection)

    def newcomer(topic: str, message: dict[str, Any]) -> None:
        del topic, message

    subscribing = asyncio.create_task(manager.subscribe("cmd/52/a/#", _noop))
    await asyncio.sleep(0)
    leaving = asyncio.create_task(manager.unsubscribe("cmd/52/a/#"))
    await asyncio.sleep(0)
    joining = asyncio.create_task(manager.subscribe("cmd/52/a/#", newcomer))
    await asyncio.sleep(0)
    suback.set_result({"topic": "cmd/52/a/#", "qos": 1})
    await subscribing
    await leaving
    await joining

    assert manager._message_handlers["cmd/52/a/#"] == [newcomer]
    assert "cmd/52/a/#" in manager._subscriptions
    connection.unsubscribe.assert_not_called()


@pytest.mark.asyncio
async def test_suback_from_a_replaced_connection_resubscribes() -> None:
    old = MagicMock()
    suback: concurrent.futures.Future[Any] = concurrent.futures.Future()
    old.subscribe.return_value = (suback, 1)
    manager = _manager(old)

    subscribing = asyncio.create_task(manager.subscribe("cmd/52/a/#", _noop))
    await asyncio.sleep(0)
    new = MagicMock()
    new.subscribe.side_effect = _granted
    manager.update_connection(new)
    suback.set_result({"topic": "cmd/52/a/#", "qos": 1})
    await subscribing

    # The pending subscribe is redone on the new connection, with no
    # other caller subscribing.
    new.subscribe.assert_called_once()
    assert "cmd/52/a/#" in manager._subscriptions
    assert manager._message_handlers["cmd/52/a/#"] == [_noop]


@pytest.mark.asyncio
async def test_resubscribing_a_callback_during_remove_all_keeps_it() -> None:
    """unsubscribe(topic) waiting, then subscribe() of the same callback."""
    connection = MagicMock()
    suback: concurrent.futures.Future[Any] = concurrent.futures.Future()
    connection.subscribe.return_value = (suback, 1)
    connection.unsubscribe.return_value = (_resolved({}), 2)
    manager = _manager(connection)

    first = asyncio.create_task(manager.subscribe("cmd/52/a/#", _noop))
    await asyncio.sleep(0)
    leaving = asyncio.create_task(manager.unsubscribe("cmd/52/a/#"))
    await asyncio.sleep(0)
    again = asyncio.create_task(manager.subscribe("cmd/52/a/#", _noop))
    await asyncio.sleep(0)
    suback.set_result({"topic": "cmd/52/a/#", "qos": 1})
    await first
    await leaving
    connection.subscribe.return_value = (_resolved({"qos": 1}), 3)
    await again

    # The later subscribe wins: the callback stays and the subscription
    # is kept, with no UNSUBSCRIBE and no second SUBSCRIBE.
    assert manager._message_handlers["cmd/52/a/#"] == [_noop]
    assert "cmd/52/a/#" in manager._subscriptions
    connection.unsubscribe.assert_not_called()
    assert connection.subscribe.call_count == 1


@pytest.mark.asyncio
async def test_unsubscribe_during_a_queued_subscribe_is_kept() -> None:
    """A's SUBACK pending; subscribe(B) queues; unsubscribe(B) returns."""
    connection = MagicMock()
    suback: concurrent.futures.Future[Any] = concurrent.futures.Future()
    connection.subscribe.return_value = (suback, 1)
    manager = _manager(connection)

    def other(topic: str, message: dict[str, Any]) -> None:
        del topic, message

    first = asyncio.create_task(manager.subscribe("cmd/52/a/#", _noop))
    await asyncio.sleep(0)
    queued = asyncio.create_task(manager.subscribe("cmd/52/a/#", other))
    await asyncio.sleep(0)
    await manager.unsubscribe("cmd/52/a/#", other)
    suback.set_result({"topic": "cmd/52/a/#", "qos": 1})
    await first
    await queued

    assert manager._message_handlers["cmd/52/a/#"] == [_noop]
    assert other not in manager._registered_at.get("cmd/52/a/#", {})
