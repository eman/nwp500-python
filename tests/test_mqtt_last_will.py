"""Tests for the app-connection message and the MQTT Last-Will.

The NaviLink app (2.04.00, ``NavilinkApplication``) registers a Last-Will
on ``evt/{deviceType}/navilink-{mac}/app-connection`` with its
``RequestLastWill`` shape and ``event.connection.status`` 0. The library
publishes the same shape with status 1 from ``signal_app_connection()``,
registers the will through ``MqttConnectionConfig.last_will_device``, and
parses incoming messages into ``AppConnectionEvent``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from awscrt import mqtt as awscrt_mqtt

from nwp500.auth import AuthenticationResponse, AuthTokens, UserInfo
from nwp500.events import EventEmitter
from nwp500.models.mqtt_models import (
    APP_CONNECTION_OS,
    AppConnectionEvent,
)
from nwp500.mqtt import NavienMqttClient
from nwp500.mqtt._device_subscriptions import DeviceSubscriptionsMixin
from nwp500.mqtt.connection import MqttConnection
from nwp500.mqtt.control import MqttDeviceController
from nwp500.mqtt.subscriptions import MqttSubscriptionManager
from nwp500.mqtt.types import MqttWill, QoS, to_awscrt_will
from nwp500.mqtt.utils import MqttConnectionConfig
from nwp500.mqtt_events import AppConnectionReceivedEvent, MqttClientEvents
from nwp500.topic_builder import MqttTopicBuilder

MAC = "04786332fca0"
TOPIC = f"evt/52/navilink-{MAC}/app-connection"


def _device(mac: str = MAC) -> MagicMock:
    device = MagicMock()
    device.device_info.mac_address = mac
    device.device_info.device_type = 52
    device.device_info.additional_value = "5322"
    device.device_info.model_type_code = 49
    device.device_info.home_seq = 25004
    return device


def _app_message(status: int, client_id: str = "navilink-phone") -> dict:
    """A ``RequestLastWill`` message as the app's Gson serializes it."""
    return {
        "clientID": client_id,
        "event": {
            "additionalValue": "5322",
            "connection": {"os": "A", "status": status},
            "deviceType": 52,
            "macAddress": MAC,
            "modelTypeCode": 49,
        },
        "protocolVersion": 1,
        "requestTopic": TOPIC,
        "sessionID": "1760000000000",
    }


def _auth_client():
    from nwp500.auth import NavienAuthClient

    client = NavienAuthClient("test@example.com", "password")
    client._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="T", user_last_name="U"),
        tokens=AuthTokens(
            id_token="id",
            access_token="acc",
            refresh_token="ref",
            authentication_expires_in=3600,
            access_key_id="key",
            secret_key="secret",
            session_token="sess",
            authorization_expires_in=3600,
        ),
    )
    return client


class TestTopicBuilder:
    def test_app_connection_topic(self) -> None:
        assert MqttTopicBuilder.app_connection_topic("52", MAC) == TOPIC


class TestAppConnectionModel:
    def test_parses_the_apps_last_will(self) -> None:
        parsed = AppConnectionEvent.model_validate(_app_message(0))

        assert parsed.client_id == "navilink-phone"
        assert parsed.session_id == "1760000000000"
        assert parsed.protocol_version == 1
        assert parsed.request_topic == TOPIC
        assert parsed.mac_address == MAC
        assert parsed.event.device_type == 52
        assert parsed.event.model_type_code == 49
        assert parsed.event.connection.os == "A"
        assert parsed.event.connection.status == 0
        assert parsed.connected is False

    @pytest.mark.parametrize(
        ("status", "connected"), [(1, True), (0, False), (-1, False)]
    )
    def test_connected_follows_the_apps_threshold(
        self, status, connected
    ) -> None:
        """The app treats ``status <= 0`` as disconnected."""
        parsed = AppConnectionEvent.model_validate(_app_message(status))
        assert parsed.connected is connected

    def test_parses_the_apps_event_status_shape(self) -> None:
        """Screens parse the topic with ``EventStatus``, whose connection
        has ``sessionNumber`` and no ``os``; both must be accepted."""
        parsed = AppConnectionEvent.model_validate(
            {
                "clientID": "x",
                "event": {
                    "macAddress": MAC,
                    "deviceType": 52,
                    "connection": {"sessionNumber": 3, "status": 1},
                },
            }
        )
        assert parsed.event.connection.session_number == 3
        assert parsed.event.connection.os is None
        assert parsed.connected is True

    def test_build_renders_the_apps_shape(self) -> None:
        event = AppConnectionEvent.build(
            client_id="navien-client-1",
            session_id="s1",
            topic=TOPIC,
            mac_address=MAC,
            device_type=52,
            additional_value="5322",
            model_type_code=49,
            connected=False,
        )

        assert event.to_payload() == {
            "clientID": "navien-client-1",
            "sessionID": "s1",
            "protocolVersion": 1,
            "requestTopic": TOPIC,
            "event": {
                "macAddress": MAC,
                "deviceType": 52,
                "additionalValue": "5322",
                "modelTypeCode": 49,
                "connection": {"status": 0, "os": APP_CONNECTION_OS},
            },
        }

    def test_build_omits_unknown_model_type_code(self) -> None:
        event = AppConnectionEvent.build(
            client_id="c",
            session_id="s",
            topic=TOPIC,
            mac_address=MAC,
            device_type=52,
            connected=True,
        )
        payload = event.to_payload()

        assert "modelTypeCode" not in payload["event"]
        assert "sessionNumber" not in payload["event"]["connection"]
        assert payload["event"]["connection"]["status"] == 1

    def test_payload_round_trips(self) -> None:
        event = AppConnectionEvent.build(
            client_id="c",
            session_id="s",
            topic=TOPIC,
            mac_address=MAC,
            device_type=52,
            connected=True,
        )
        parsed = AppConnectionEvent.model_validate(
            json.loads(json.dumps(event.to_payload()))
        )
        assert parsed == event


class TestSignalAppConnection:
    @staticmethod
    def _controller() -> tuple[MqttDeviceController, AsyncMock]:
        publish = AsyncMock(return_value=1)
        controller = MqttDeviceController(
            client_id="navien-client-1",
            session_id="session-1",
            publish_func=publish,
        )
        return controller, publish

    @pytest.mark.asyncio
    async def test_publishes_connected_announcement(self) -> None:
        controller, publish = self._controller()

        await controller.signal_app_connection(_device())

        publish.assert_awaited_once()
        topic, payload = publish.await_args.args[:2]
        assert topic == TOPIC
        assert payload == {
            "clientID": "navien-client-1",
            "sessionID": "session-1",
            "protocolVersion": 1,
            "requestTopic": TOPIC,
            "event": {
                "macAddress": MAC,
                "deviceType": 52,
                "additionalValue": "5322",
                "modelTypeCode": 49,
                "connection": {"status": 1, "os": APP_CONNECTION_OS},
            },
        }
        assert "timestamp" not in payload

    def test_build_app_connection_for_the_will(self) -> None:
        controller, _publish = self._controller()

        topic, payload = controller.build_app_connection(
            _device(), connected=False
        )

        assert topic == TOPIC
        assert payload["event"]["connection"]["status"] == 0
        assert payload["clientID"] == "navien-client-1"


class TestWillTypes:
    def test_to_awscrt_will(self) -> None:
        will = MqttWill(topic=TOPIC, payload={"a": 1}, qos=QoS.AT_LEAST_ONCE)

        converted = to_awscrt_will(will)

        assert isinstance(converted, awscrt_mqtt.Will)
        assert converted.topic == TOPIC
        assert converted.qos == awscrt_mqtt.QoS.AT_LEAST_ONCE
        assert json.loads(converted.payload) == {"a": 1}
        assert converted.retain is False


class TestConnectionBuilderWill:
    """The will reaches the awsiot connection builder as a CONNECT option."""

    @staticmethod
    def _connect_with(will: MqttWill | None) -> dict[str, Any]:
        connection = MqttConnection(
            config=MqttConnectionConfig(client_id="c"),
            auth_client=_auth_client(),
            will=will,
        )
        fake = MagicMock()
        fake.connect.return_value = concurrent.futures.Future()
        fake.connect.return_value.set_result({"session_present": False})
        builder = MagicMock(return_value=fake)

        async def run() -> None:
            with patch(
                "nwp500.mqtt.connection.mqtt_connection_builder."
                "websockets_with_default_aws_signing",
                builder,
            ):
                assert await connection.connect()

        asyncio.run(run())
        return builder.call_args.kwargs

    def test_will_is_passed_to_the_builder(self) -> None:
        will = MqttWill(topic=TOPIC, payload={"event": {}})

        kwargs = self._connect_with(will)

        assert isinstance(kwargs["will"], awscrt_mqtt.Will)
        assert kwargs["will"].topic == TOPIC
        assert kwargs["will"].qos == awscrt_mqtt.QoS.AT_LEAST_ONCE
        assert json.loads(kwargs["will"].payload) == {"event": {}}

    def test_no_will_without_a_device(self) -> None:
        kwargs = self._connect_with(None)

        assert "will" not in kwargs

    def test_will_property(self) -> None:
        will = MqttWill(topic=TOPIC)
        connection = MqttConnection(
            config=MqttConnectionConfig(client_id="c"),
            auth_client=_auth_client(),
            will=will,
        )
        assert connection.will is will


class TestClientWill:
    """``NavienMqttClient`` derives the will from the configured device."""

    def test_will_from_last_will_device(self) -> None:
        client = NavienMqttClient(
            _auth_client(),
            MqttConnectionConfig(
                client_id="navien-client-1", last_will_device=_device()
            ),
        )

        will = client._build_will()

        assert will is not None
        assert will.topic == TOPIC
        assert will.qos == QoS.AT_LEAST_ONCE
        assert will.payload["clientID"] == "navien-client-1"
        assert will.payload["sessionID"] == client.session_id
        assert will.payload["event"]["connection"] == {
            "status": 0,
            "os": APP_CONNECTION_OS,
        }

    def test_no_will_by_default(self) -> None:
        client = NavienMqttClient(_auth_client())

        assert client._build_will() is None
        assert client._create_connection_manager().will is None

    @pytest.mark.asyncio
    async def test_every_connection_manager_carries_the_will(self) -> None:
        """First connect and rebuilds all go through one factory, so a
        reconnected session registers the will again."""
        client = NavienMqttClient(
            _auth_client(),
            MqttConnectionConfig(client_id="c", last_will_device=_device()),
        )
        client._loop = asyncio.get_running_loop()
        created: list[Any] = []

        def fake_manager(**kwargs: Any) -> MagicMock:
            created.append(kwargs)
            manager = MagicMock()
            manager.connect = AsyncMock(return_value=True)
            manager.connection = MagicMock()
            manager.close = AsyncMock()
            return manager

        with (
            patch(
                "nwp500.mqtt.client.MqttConnection", side_effect=fake_manager
            ),
            patch.object(
                client._auth_client, "ensure_valid_token", AsyncMock()
            ),
            patch.object(client._auth_client, "refresh_token", AsyncMock()),
            patch.object(client._auth_client, "refresh_session", AsyncMock()),
        ):
            await client.connect()
            client._connected = False
            await client._active_reconnect()
            client._connected = False
            await client._deep_reconnect()

        assert len(created) == 3
        for kwargs in created:
            assert kwargs["will"].topic == TOPIC
            assert kwargs["will"].payload["event"]["connection"]["status"] == 0


def _manager(emitter: Any, schedule: Any) -> MqttSubscriptionManager:
    connection = MagicMock()

    def resolved(value: Any) -> concurrent.futures.Future[Any]:
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        future.set_result(value)
        return future

    connection.subscribe.side_effect = lambda topic, qos, callback: (
        resolved({"topic": topic, "qos": qos}),
        1,
    )
    connection.unsubscribe.side_effect = lambda topic: (
        resolved({"topic": topic}),
        2,
    )
    return MqttSubscriptionManager(
        connection=connection,
        client_id="navien-client-1",
        event_emitter=emitter,
        schedule_coroutine=schedule,
    )


class TestSubscribeAppConnection:
    @staticmethod
    def _emitting_manager() -> tuple[MqttSubscriptionManager, list[Any]]:
        emitter = EventEmitter()
        events: list[Any] = []
        emitter.on(MqttClientEvents.APP_CONNECTION_RECEIVED, events.append)
        return (
            _manager(
                emitter,
                lambda coro: asyncio.get_running_loop().create_task(coro),
            ),
            events,
        )

    @pytest.mark.asyncio
    async def test_subscribes_to_the_event_topic(self) -> None:
        manager, _events = self._emitting_manager()

        packet = await manager.subscribe_app_connection(
            _device(), lambda e: None
        )

        assert packet == 1
        assert list(manager.subscriptions) == [TOPIC]

    @pytest.mark.asyncio
    async def test_callback_and_event_on_a_last_will(self) -> None:
        manager, events = self._emitting_manager()
        received: list[AppConnectionEvent] = []
        await manager.subscribe_app_connection(_device(), received.append)

        await manager._dispatch_message(
            TOPIC, json.dumps(_app_message(0)).encode()
        )
        await asyncio.sleep(0)

        assert len(received) == 1
        assert received[0].connected is False
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AppConnectionReceivedEvent)
        assert event.device_mac == MAC
        assert event.client_id == "navilink-phone"
        assert event.connected is False
        assert event.event == received[0]

    @pytest.mark.asyncio
    async def test_two_callbacks_emit_the_event_once(self) -> None:
        manager, events = self._emitting_manager()
        first: list[AppConnectionEvent] = []
        second: list[AppConnectionEvent] = []
        await manager.subscribe_app_connection(_device(), first.append)
        await manager.subscribe_app_connection(_device(), second.append)

        await manager._dispatch_message(
            TOPIC, json.dumps(_app_message(0)).encode()
        )
        await asyncio.sleep(0)

        assert len(first) == 1
        assert len(second) == 1
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_own_announcement_is_delivered_with_client_id(self) -> None:
        manager, events = self._emitting_manager()
        await manager.subscribe_app_connection(_device(), lambda e: None)

        await manager._dispatch_message(
            TOPIC,
            json.dumps(_app_message(1, client_id="navien-client-1")).encode(),
        )
        await asyncio.sleep(0)

        assert events[0].connected is True
        assert events[0].client_id == "navien-client-1"

    @pytest.mark.asyncio
    async def test_does_not_record_a_device_session(self) -> None:
        """Watching presence is not a device session: no st/end for it."""
        manager, _events = self._emitting_manager()

        await manager.subscribe_app_connection(_device(), lambda e: None)

        assert manager.subscribed_devices == []

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        manager, _events = self._emitting_manager()
        received: list[AppConnectionEvent] = []
        await manager.subscribe_app_connection(_device(), received.append)

        await manager.unsubscribe_app_connection(_device(), received.append)
        await manager._dispatch_message(
            TOPIC, json.dumps(_app_message(0)).encode()
        )
        await asyncio.sleep(0)

        assert received == []
        assert TOPIC not in manager.subscriptions

    @pytest.mark.asyncio
    async def test_mixin_delegates(self) -> None:
        client: Any = DeviceSubscriptionsMixin()
        client._connected = True
        client._subscription_manager = MagicMock()
        client._subscription_manager.subscribe_app_connection = AsyncMock(
            return_value=3
        )
        client._subscription_manager.unsubscribe_app_connection = AsyncMock()
        device = _device()
        callback = MagicMock()

        assert await client.subscribe_app_connection(device, callback) == 3
        await client.unsubscribe_app_connection(device, callback)

        manager = client._subscription_manager
        manager.subscribe_app_connection.assert_awaited_once_with(
            device, callback
        )
        manager.unsubscribe_app_connection.assert_awaited_once_with(
            device, callback
        )
