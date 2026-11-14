"""Tests for per-command sessionIDs and the MQTT payload logger."""

import json
import logging
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nwp500.models import Device
from nwp500.mqtt.control import MqttDeviceController
from nwp500.mqtt.utils import log_payload

MAC = "04786332fca0"


@pytest.fixture
def device() -> Device:
    dev = MagicMock()
    dev.device_info.mac_address = MAC
    dev.device_info.device_type = 52
    dev.device_info.additional_value = "5322"
    return cast(Device, dev)


def _controller() -> tuple[MqttDeviceController, AsyncMock]:
    publish = AsyncMock(return_value=1)
    controller = MqttDeviceController(
        client_id="navien-client-1996271a",
        session_id="connection-session",
        publish_func=publish,
    )
    controller._get_device_features = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock()
    )
    return controller, publish


class TestCommandSessionId:
    @pytest.mark.asyncio
    async def test_each_command_gets_its_own_session_id(
        self, device: Device
    ) -> None:
        controller, publish = _controller()
        with patch("nwp500.mqtt.control.time.time_ns", return_value=0):
            # The clock stands still, so the ids must still differ.
            await controller.set_tou_enabled(device, True)
            await controller.set_tou_enabled(device, True)

        ids = [c.args[1]["sessionID"] for c in publish.await_args_list]
        assert ids == ["1", "2"]

    @pytest.mark.asyncio
    async def test_session_id_is_send_time_in_ms(self, device: Device) -> None:
        controller, publish = _controller()
        ns = 1_763_116_258_162_123_456
        with patch("nwp500.mqtt.control.time.time_ns", return_value=ns):
            await controller.set_tou_enabled(device, True)

        assert publish.await_args is not None
        assert publish.await_args.args[1]["sessionID"] == "1763116258162"

    def test_app_connection_keeps_client_session_id(
        self, device: Device
    ) -> None:
        controller, _ = _controller()
        _, payload = controller.build_app_connection(device, connected=True)
        assert payload["sessionID"] == "connection-session"


class TestLogPayload:
    def _line(self, caplog: pytest.LogCaptureFixture) -> str:
        records = [
            r for r in caplog.records if r.name == "nwp500.mqtt.payloads"
        ]
        assert len(records) == 1
        return records[0].getMessage()

    def test_send_line_keeps_ids_and_hides_mac(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="nwp500.mqtt.payloads")
        payload = {
            "clientID": "navien-client-1996271a",
            "sessionID": "1763116258162",
            "requestTopic": f"cmd/52/navilink-{MAC}/ctrl",
            "request": {"macAddress": MAC, "mode": "tou-on"},
        }
        log_payload("send", f"cmd/52/navilink-{MAC}/ctrl", payload, 1910)

        line = self._line(caplog)
        assert line.startswith("send #1910 cmd/52/navilink-REDACTED/ctrl ")
        assert MAC not in line
        body = json.loads(line.split(" ", 3)[3])
        assert body["clientID"] == "navien-client-1996271a"
        assert body["sessionID"] == "1763116258162"
        assert body["requestTopic"] == "cmd/52/navilink-REDACTED/ctrl"
        assert body["request"]["mode"] == "tou-on"

    def test_recv_line_parses_string_payload(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="nwp500.mqtt.payloads")
        log_payload(
            "recv",
            "cmd/52/navien-client-1996271a/res",
            json.dumps({"response": {"status": {"touStatus": 2}}}),
        )
        line = self._line(caplog)
        assert line == (
            "recv cmd/52/navien-client-1996271a/res "
            '{"response":{"status":{"touStatus":2}}}'
        )

    def test_silent_above_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="nwp500.mqtt.payloads")
        log_payload("send", "cmd/52/x/ctrl", {"a": 1})
        assert not [
            r for r in caplog.records if r.name == "nwp500.mqtt.payloads"
        ]


class TestLogPayloadKeepsData:
    def _body(self, caplog: pytest.LogCaptureFixture, payload: object) -> str:
        caplog.set_level(logging.DEBUG, logger="nwp500.mqtt.payloads")
        log_payload("recv", "cmd/52/navien-client-1996271a/res", payload)
        records = [
            r for r in caplog.records if r.name == "nwp500.mqtt.payloads"
        ]
        assert len(records) == 1
        return records[0].getMessage().split(" ", 2)[2]

    def test_one_entry_reservation_hex_is_kept(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        body = self._body(
            caplog,
            {"response": {"macAddress": MAC, "reservation": "013e061e0478"}},
        )
        assert json.loads(body)["response"] == {
            "macAddress": "<REDACTED>",
            "reservation": "013e061e0478",
        }

    def test_long_strings_are_not_cut(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        blob = "ab" * 200
        assert json.loads(self._body(caplog, {"blob": blob}))["blob"] == blob

    def test_named_mac_is_redacted_wherever_it_appears(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        body = self._body(
            caplog,
            {
                "requestTopic": f"cmd/52/{MAC.upper()}/ctrl",
                "response": {"macAddress": MAC},
            },
        )
        assert MAC not in body.lower()
        assert json.loads(body)["requestTopic"] == "cmd/52/REDACTED/ctrl"

    def test_raw_text_is_logged_when_not_json(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        body = self._body(caplog, b"\xffnot json navilink-" + MAC.encode())
        assert body == "�not json navilink-REDACTED"


class TestPayloadLogWiring:
    @pytest.mark.asyncio
    async def test_publish_logs_with_packet_id(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from concurrent.futures import Future

        from nwp500.mqtt.connection import MqttConnection
        from nwp500.mqtt.utils import MqttConnectionConfig

        conn = MqttConnection(
            MqttConnectionConfig(client_id="test-client"), MagicMock()
        )
        done: Future[object] = Future()
        done.set_result(None)
        conn._connection = MagicMock()
        conn._connection.publish.return_value = (done, 1910)
        conn._connected = True

        caplog.set_level(logging.DEBUG, logger="nwp500.mqtt.payloads")
        await conn.publish("cmd/52/navilink-x/ctrl", {"sessionID": "1"})

        lines = [
            r.getMessage()
            for r in caplog.records
            if r.name == "nwp500.mqtt.payloads"
        ]
        assert lines == ['send #1910 cmd/52/navilink-x/ctrl {"sessionID":"1"}']

    @pytest.mark.asyncio
    async def test_dispatch_logs_parsed_and_unparsed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from nwp500.mqtt.subscriptions import MqttSubscriptionManager

        manager = MqttSubscriptionManager(
            connection=MagicMock(),
            client_id="test-client",
            event_emitter=MagicMock(),
            schedule_coroutine=MagicMock(),
        )
        caplog.set_level(logging.DEBUG, logger="nwp500.mqtt.payloads")
        await manager._dispatch_message("cmd/52/test-client/res", b'{"a":1}')
        await manager._dispatch_message("cmd/52/test-client/res", b"{bad")

        lines = [
            r.getMessage()
            for r in caplog.records
            if r.name == "nwp500.mqtt.payloads"
        ]
        assert lines == [
            'recv cmd/52/test-client/res {"a":1}',
            "recv cmd/52/test-client/res {bad",
        ]


class TestLogPayloadTopicMacs:
    def _line(
        self, caplog: pytest.LogCaptureFixture, topic: str, payload: object
    ) -> str:
        caplog.set_level(logging.DEBUG, logger="nwp500.mqtt.payloads")
        log_payload("recv", topic, payload)
        records = [
            r for r in caplog.records if r.name == "nwp500.mqtt.payloads"
        ]
        assert len(records) == 1
        return records[0].getMessage()

    def test_mac_named_by_topic_segment_is_redacted_in_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        line = self._line(
            caplog,
            f"cmd/52/{MAC}/navien-client-x/res",
            {
                "clientID": f"navilink-{MAC}",
                "responseTopic": f"cmd/52/{MAC}/navien-client-x/res",
                "reservation": "013e061e0478",
            },
        )
        assert MAC not in line
        assert '"reservation":"013e061e0478"' in line

    def test_mac_in_body_topic_value_is_redacted(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        line = self._line(
            caplog,
            "cmd/52/navien-client-x/res",
            {"requestTopic": f"cmd/52/{MAC}/ctrl", "list": [f"x {MAC}"]},
        )
        assert MAC not in line

    def test_unparsed_message_uses_topic_mac(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        line = self._line(
            caplog, f"cmd/52/navilink-{MAC}/res", f"garbage {MAC}".encode()
        )
        assert line == "recv cmd/52/navilink-REDACTED/res garbage REDACTED"
