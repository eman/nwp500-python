"""Each message is parsed and announced once, however many callbacks."""

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
    connection.subscribe.side_effect = lambda topic, qos, callback: (
        _resolved({"topic": topic, "qos": qos}),
        1,
    )
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
