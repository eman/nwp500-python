"""Tests for control failure (``res/ctrl-fail``) handling.

The NaviLink app (2.04.00) subscribes to
``cmd/{deviceType}/navilink-{mac}/res/ctrl-fail`` and parses
``ControlFailData``; the only ``failCode`` it interprets is 2, "DHW control
interval exceeded". The library parses the same shape, delivers it to typed
callbacks and emits the ``control_failed`` client event for every device
subscription.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nwp500.events import EventEmitter
from nwp500.models.mqtt_models import (
    ControlFailCode,
    ControlFailDetail,
    ControlFailResponse,
)
from nwp500.mqtt._device_subscriptions import DeviceSubscriptionsMixin
from nwp500.mqtt.subscriptions import MqttSubscriptionManager
from nwp500.mqtt_events import ControlFailedEvent, MqttClientEvents
from nwp500.topic_builder import MqttTopicBuilder

MAC = "04786332fca0"
WILDCARD = f"cmd/52/navilink-{MAC}/#"
CTRL_FAIL_TOPIC = f"cmd/52/navilink-{MAC}/res/ctrl-fail"


def _ctrl_fail_message(
    fail_code: int = 2, client_id: str = "test-client"
) -> dict[str, Any]:
    """A ``ControlFailData`` message as the app's model lays it out."""
    return {
        "clientID": client_id,
        "protocolVersion": 2,
        "requestTopic": f"cmd/52/navilink-{MAC}/ctrl",
        "sessionID": "session-1",
        "response": {
            "deviceType": 52,
            "macAddress": MAC,
            "additionalValue": "5322",
            "failCode": fail_code,
            "swVersion": 1234,
        },
    }


def _device(mac: str = MAC) -> MagicMock:
    device = MagicMock()
    device.device_info.mac_address = mac
    device.device_info.device_type = 52
    device.device_info.additional_value = "5322"
    device.device_info.home_seq = 25004
    return device


def _resolved(value: Any) -> concurrent.futures.Future[Any]:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    future.set_result(value)
    return future


def _manager(
    emitter: EventEmitter | MagicMock | None = None,
    schedule: Any = None,
) -> MqttSubscriptionManager:
    """Manager over a fake connection whose subscribe acks immediately."""
    connection = MagicMock()
    connection.subscribe.side_effect = lambda topic, qos, callback: (
        _resolved({"topic": topic, "qos": qos}),
        1,
    )
    connection.unsubscribe.side_effect = lambda topic: (
        _resolved({"topic": topic}),
        2,
    )
    return MqttSubscriptionManager(
        connection=connection,
        client_id="test-client",
        event_emitter=emitter if emitter is not None else MagicMock(),
        schedule_coroutine=schedule if schedule is not None else MagicMock(),
    )


async def _deliver(
    manager: MqttSubscriptionManager, topic: str, message: dict[str, Any]
) -> None:
    await manager._dispatch_message(topic, json.dumps(message).encode())


class TestTopicBuilder:
    def test_control_fail_response_topic(self):
        assert (
            MqttTopicBuilder.control_fail_response_topic("52", MAC)
            == CTRL_FAIL_TOPIC
        )

    def test_wildcard_covers_control_fail_topic(self):
        from nwp500.mqtt.utils import topic_matches_pattern

        assert topic_matches_pattern(CTRL_FAIL_TOPIC, WILDCARD)


class TestControlFailModel:
    def test_parses_the_apps_shape(self):
        parsed = ControlFailResponse.model_validate(_ctrl_fail_message())

        assert parsed.client_id == "test-client"
        assert parsed.session_id == "session-1"
        assert parsed.request_topic == f"cmd/52/navilink-{MAC}/ctrl"
        assert parsed.protocol_version == 2
        assert parsed.response.device_type == 52
        assert parsed.response.mac_address == MAC
        assert parsed.response.additional_value == "5322"
        assert parsed.response.sw_version == 1234

    def test_known_fail_code_is_an_enum(self):
        parsed = ControlFailResponse.model_validate(_ctrl_fail_message(2))

        assert parsed.fail_code is ControlFailCode.DHW_CONTROL_INTERVAL_EXCEEDED
        assert parsed.fail_code == 2
        assert parsed.reason == "DHW control interval exceeded"
        assert parsed.mac_address == MAC

    def test_unknown_fail_code_stays_an_int(self):
        parsed = ControlFailResponse.model_validate(_ctrl_fail_message(7))

        assert parsed.fail_code == 7
        assert not isinstance(parsed.fail_code, ControlFailCode)
        assert parsed.reason == "unknown failure code 7"

    def test_envelope_fields_are_optional(self):
        """Only ``response`` is required: a future sender might omit the
        envelope and the failure should still be understood."""
        parsed = ControlFailResponse.model_validate(
            {"response": {"deviceType": 52, "macAddress": MAC, "failCode": 2}}
        )

        assert parsed.client_id is None
        assert parsed.response.sw_version is None
        assert parsed.fail_code is ControlFailCode.DHW_CONTROL_INTERVAL_EXCEEDED

    def test_detail_requires_fail_code(self):
        with pytest.raises(ValueError):
            ControlFailDetail.model_validate(
                {"deviceType": 52, "macAddress": MAC}
            )


class TestTypedSubscription:
    @pytest.mark.asyncio
    async def test_callback_receives_parsed_message(self):
        manager = _manager()
        received: list[ControlFailResponse] = []

        packet = await manager.subscribe_control_fail_response(
            _device(), received.append
        )
        await _deliver(manager, CTRL_FAIL_TOPIC, _ctrl_fail_message())

        assert packet == 1
        assert len(received) == 1
        assert received[0].fail_code == 2
        assert received[0].client_id == "test-client"

    @pytest.mark.asyncio
    async def test_registers_under_the_device_wildcard(self):
        """No new broker subscription: the device wildcard carries it."""
        manager = _manager()

        await manager.subscribe_control_fail_response(_device(), lambda r: None)

        assert list(manager.subscriptions) == [WILDCARD]
        manager._connection.subscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_other_device_messages_are_ignored(self):
        manager = _manager()
        received: list[ControlFailResponse] = []

        await manager.subscribe_control_fail_response(
            _device(), received.append
        )
        await _deliver(
            manager,
            f"cmd/52/navilink-{MAC}/res/dl-sw-info",
            {"response": {"downloadSwInfo": []}},
        )
        await _deliver(
            manager,
            f"cmd/52/navilink-{MAC}/test-client/res",
            {"response": {"status": {"command": 1}}},
        )

        assert received == []

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_only_that_callback(self):
        manager = _manager()
        device = _device()
        failures: list[ControlFailResponse] = []
        statuses: list[Any] = []

        await manager.subscribe_device_status(device, statuses.append)
        await manager.subscribe_control_fail_response(device, failures.append)
        await manager.unsubscribe_control_fail_response(device, failures.append)

        kinds = [
            getattr(h, "_subscription_kind", None)
            for h in manager._message_handlers[WILDCARD]
        ]
        assert kinds == ["device_status"]
        await _deliver(manager, CTRL_FAIL_TOPIC, _ctrl_fail_message())
        assert failures == []

    @pytest.mark.asyncio
    async def test_unparseable_message_is_logged_not_raised(self, caplog):
        manager = _manager()
        received: list[ControlFailResponse] = []

        await manager.subscribe_control_fail_response(
            _device(), received.append
        )
        with caplog.at_level(
            logging.WARNING, logger="nwp500.mqtt.subscriptions"
        ):
            await _deliver(
                manager, CTRL_FAIL_TOPIC, {"response": {"deviceType": 52}}
            )

        assert received == []
        assert any(
            "ControlFailResponse" in r.getMessage() for r in caplog.records
        )


class TestControlFailedEvent:
    """``control_failed`` fires for any device subscription."""

    @staticmethod
    def _emitting_manager() -> tuple[MqttSubscriptionManager, list[Any]]:
        emitter = EventEmitter()
        events: list[Any] = []
        emitter.on(MqttClientEvents.CONTROL_FAILED, events.append)

        def run(coro: Any) -> None:
            # Run scheduled coroutines inline for the test.
            import asyncio

            asyncio.get_running_loop().create_task(coro)

        return _manager(emitter, run), events

    @pytest.mark.asyncio
    async def test_emitted_from_a_status_subscription(self):
        import asyncio

        manager, events = self._emitting_manager()
        await manager.subscribe_device_status(_device(), lambda s: None)

        await _deliver(manager, CTRL_FAIL_TOPIC, _ctrl_fail_message())
        await asyncio.sleep(0)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, ControlFailedEvent)
        assert event.device_mac == MAC
        assert event.fail_code is ControlFailCode.DHW_CONTROL_INTERVAL_EXCEEDED
        assert event.reason == "DHW control interval exceeded"
        assert event.own_command is True
        assert event.response.session_id == "session-1"

    @pytest.mark.asyncio
    async def test_other_clients_failure_is_not_own(self):
        import asyncio

        manager, events = self._emitting_manager()
        await manager.subscribe_device_status(_device(), lambda s: None)

        await _deliver(
            manager,
            CTRL_FAIL_TOPIC,
            _ctrl_fail_message(client_id="navilink-phone"),
        )
        await asyncio.sleep(0)

        assert events[0].own_command is False

    @pytest.mark.asyncio
    async def test_emitted_once_regardless_of_handler_count(self):
        """The event comes from dispatch, not from each handler."""
        import asyncio

        manager, events = self._emitting_manager()
        device = _device()
        await manager.subscribe_device_status(device, lambda s: None)
        await manager.subscribe_device_feature(device, lambda f: None)
        await manager.subscribe_control_fail_response(device, lambda r: None)

        await _deliver(manager, CTRL_FAIL_TOPIC, _ctrl_fail_message())
        await asyncio.sleep(0)

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_not_emitted_for_other_topics(self):
        import asyncio

        manager, events = self._emitting_manager()
        await manager.subscribe_device_status(_device(), lambda s: None)

        await _deliver(
            manager,
            f"cmd/52/navilink-{MAC}/res/dl-sw-info",
            {"response": {"downloadSwInfo": []}},
        )
        await asyncio.sleep(0)

        assert events == []

    @pytest.mark.asyncio
    async def test_unparseable_failure_logs_and_skips_event(self, caplog):
        import asyncio

        manager, events = self._emitting_manager()
        await manager.subscribe_device_status(_device(), lambda s: None)

        with caplog.at_level(
            logging.WARNING, logger="nwp500.mqtt.subscriptions"
        ):
            await _deliver(manager, CTRL_FAIL_TOPIC, {"response": {}})
        await asyncio.sleep(0)

        assert events == []
        assert any(
            "Unparseable control failure" in r.getMessage()
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_failure_is_logged_with_reason(self, caplog):
        import asyncio

        manager, _events = self._emitting_manager()
        await manager.subscribe_device_status(_device(), lambda s: None)

        with caplog.at_level(
            logging.WARNING, logger="nwp500.mqtt.subscriptions"
        ):
            await _deliver(manager, CTRL_FAIL_TOPIC, _ctrl_fail_message())
        await asyncio.sleep(0)

        messages = [r.getMessage() for r in caplog.records]
        assert any("DHW control interval exceeded" in m for m in messages)
        assert not any(MAC in m for m in messages), "MAC must be redacted"


class TestClientMixin:
    """The client proxies delegate to the manager and respect state."""

    @staticmethod
    def _client(connected: bool = True) -> Any:
        client = DeviceSubscriptionsMixin()
        client._connected = connected
        client._subscription_manager = MagicMock()
        client._subscription_manager.subscribe_control_fail_response = (
            AsyncMock(return_value=7)
        )
        client._subscription_manager.unsubscribe_control_fail_response = (
            AsyncMock()
        )
        return client

    @pytest.mark.asyncio
    async def test_subscribe_delegates(self):
        client = self._client()
        device = _device()
        callback = MagicMock()

        assert await client.subscribe_control_fail_response(device, callback)
        manager = client._subscription_manager
        manager.subscribe_control_fail_response.assert_awaited_once_with(
            device, callback
        )

    @pytest.mark.asyncio
    async def test_subscribe_requires_connection(self):
        from nwp500.exceptions import MqttNotConnectedError

        client = self._client(connected=False)
        with pytest.raises(MqttNotConnectedError):
            await client.subscribe_control_fail_response(_device(), MagicMock())

    @pytest.mark.asyncio
    async def test_unsubscribe_delegates_and_tolerates_disconnect(self):
        client = self._client()
        device = _device()
        callback = MagicMock()

        await client.unsubscribe_control_fail_response(device, callback)
        manager = client._subscription_manager
        manager.unsubscribe_control_fail_response.assert_awaited_once_with(
            device, callback
        )

        client._connected = False
        await client.unsubscribe_control_fail_response(device, callback)
        assert manager.unsubscribe_control_fail_response.await_count == 1
