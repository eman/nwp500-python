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
    await manager.subscribe_device_status(cast(Device, device), second)
    unsuback.set_result({})
    await pending

    assert connection.subscribe.call_count == 2
    assert topic in manager._subscriptions
    assert len(manager._message_handlers[topic]) == 1
