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
