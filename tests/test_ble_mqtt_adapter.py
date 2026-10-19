"""BleMqttAdapter and nwp-cli --backend ble (no hardware, no bleak)."""

from __future__ import annotations

import asyncio
import sys

import pytest

from nwp500.ble import (
    BleMqttAdapter,
    BleUnsupportedError,
    ClassCode,
    Command,
    ControllerSerials,
    DeviceInfo,
    NavienBleClient,
    build_packet,
    device_feature_from_blocks,
    parse_packet,
)
from nwp500.exceptions import Nwp500Error

# Read from an NWP500 on 2026-10-16. Its MQTT device-info report on
# 2026-10-19 had controllerSerialNumber 56496061BT22230408,
# dhwTemperatureMin 81, dhwTemperatureMax 131, modelTypeCode 240 and
# countryCode 3.
DID = bytes.fromhex(
    "050ba1000000033b00000000000000008351000000f00100030100000000141a"
    "030ab51475050000000000000000000010d20000000000000000"
)
MSCD = bytes.fromhex(
    "3536343936303631425432323233303430380000"
    "3536343936303631425432323233303430380000"
)


class FakeTransport:
    """Answers reads of the classes it was given, like the heater."""

    def __init__(self, replies: dict[int, bytes]):
        self.replies = replies
        self.written: list[bytes] = []
        self.connected = False
        self._cb = None

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def start_notify(self, callback):
        self._cb = callback

    async def write(self, data: bytes):
        self.written.append(data)
        req = parse_packet(data)
        if req.class_code in self.replies:
            reply = build_packet(
                Command.READ_RESPONSE,
                req.class_code,
                self.replies[req.class_code],
            )
            asyncio.get_running_loop().call_soon(self._cb, reply)


def _heater() -> FakeTransport:
    return FakeTransport({ClassCode.DID: DID, ClassCode.MSCD: MSCD})


def test_feature_carries_only_the_fields_checked_against_mqtt():
    feature = device_feature_from_blocks(
        DeviceInfo.parse(DID), ControllerSerials.parse(MSCD)
    )
    assert feature.controller_serial_number == "56496061BT22230408"
    assert feature.dhw_temperature_min_raw == 81
    assert feature.dhw_temperature_max_raw == 131
    assert feature.model_type_code == 240
    assert feature.country_code == 3
    # fields Bluetooth does not carry are absent, not defaulted
    with pytest.raises(AttributeError):
        feature.hpwh_use  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_adapter_answers_a_device_feature_request():
    transport = _heater()
    got = []
    async with BleMqttAdapter(NavienBleClient(transport=transport)) as mqtt:
        assert transport.connected
        await mqtt.subscribe_device_feature(None, got.append)
        assert await mqtt.request_device_info(None) == 0
    assert not transport.connected
    assert [f.controller_serial_number for f in got] == ["56496061BT22230408"]
    assert mqtt.device_info is not None and mqtt.device_info.raw == DID
    asked = [parse_packet(w).class_code for w in transport.written]
    assert asked == [ClassCode.DID, ClassCode.MSCD]


@pytest.mark.asyncio
async def test_controller_serial_helper_runs_unchanged_over_bluetooth():
    pytest.importorskip("click")
    from nwp500.cli.handlers import get_controller_serial_number

    async with BleMqttAdapter(NavienBleClient(transport=_heater())) as mqtt:
        serial = await get_controller_serial_number(mqtt, None)  # type: ignore[arg-type]
    assert serial == "56496061BT22230408"


@pytest.mark.parametrize(
    "name", ["request_device_status", "set_power", "control", "client_id"]
)
def test_other_mqtt_attributes_raise_a_clear_error(name: str):
    mqtt = BleMqttAdapter(NavienBleClient(transport=_heater()))
    with pytest.raises(
        BleUnsupportedError, match="not available over Bluetooth"
    ):
        getattr(mqtt, name)


def test_unsupported_error_is_a_library_error():
    assert issubclass(BleUnsupportedError, Nwp500Error)
    assert BleUnsupportedError("set_power").operation == "set_power"


def test_private_attributes_are_plain_attribute_errors():
    mqtt = BleMqttAdapter(NavienBleClient(transport=_heater()))
    assert not hasattr(mqtt, "_not_there")


# --- nwp-cli --backend ble ---------------------------------------------


@pytest.fixture
def cli_with_fake_heater(monkeypatch):
    pytest.importorskip("click")
    from nwp500.cli import ble_backend

    transport = _heater()
    monkeypatch.setattr(
        ble_backend,
        "NavienBleClient",
        lambda address: NavienBleClient(transport=transport, reply_timeout=0.5),
    )
    from click.testing import CliRunner

    from nwp500.cli.__main__ import cli

    def invoke(*args: str):
        return CliRunner().invoke(
            cli, ["--backend", "ble", "--ble-address", "AA:BB", *args]
        )

    invoke.transport = transport  # type: ignore[attr-defined]
    return invoke


def test_cli_serial_over_bluetooth(cli_with_fake_heater):
    result = cli_with_fake_heater("serial")
    assert result.exit_code == 0, result.output
    assert "56496061BT22230408" in result.output


def test_cli_info_over_bluetooth_shows_only_block_fields(cli_with_fake_heater):
    result = cli_with_fake_heater("info")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Controller serial" in out and "56496061BT22230408" in out
    assert "104.9 - 149.9 °F (40.5 - 65.5 °C)" in out
    # nothing the blocks do not carry, such as firmware or capability flags
    assert "firmware" not in out.lower() and "supported" not in out.lower()


def test_cli_info_raw_over_bluetooth(cli_with_fake_heater):
    result = cli_with_fake_heater("info", "--raw")
    assert result.exit_code == 0, result.output
    assert DID.hex() in result.output and MSCD.hex() in result.output


@pytest.mark.parametrize(
    "args", [["status"], ["power", "on"], ["reservations", "get"]]
)
def test_cli_refuses_other_commands_before_connecting(
    cli_with_fake_heater, args
):
    result = cli_with_fake_heater(*args)
    assert result.exit_code == 2
    assert "not available over Bluetooth" in result.output
    assert cli_with_fake_heater.transport.written == []


def test_cli_mqtt_backend_does_not_load_bluetooth(monkeypatch):
    pytest.importorskip("click")
    from click.testing import CliRunner

    for mod in [m for m in sys.modules if m.startswith("nwp500.ble")]:
        monkeypatch.delitem(sys.modules, mod)
    monkeypatch.delitem(sys.modules, "nwp500.cli.ble_backend", raising=False)
    from nwp500.cli.__main__ import cli

    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "--backend" in result.output
    assert not any(m.startswith("nwp500.ble") for m in sys.modules)


@pytest.mark.parametrize("backend", [[], ["--backend", "mqtt"]])
def test_cli_without_ble_backend_takes_the_cloud_path(monkeypatch, backend):
    pytest.importorskip("click")
    from click.testing import CliRunner

    for mod in [m for m in sys.modules if m.startswith("nwp500.ble")]:
        monkeypatch.delitem(sys.modules, mod)
    monkeypatch.delitem(sys.modules, "nwp500.cli.ble_backend", raising=False)
    from nwp500.cli import __main__ as main

    monkeypatch.setattr(main, "load_tokens", lambda: (None, None))
    result = CliRunner(env={"NAVIEN_EMAIL": "", "NAVIEN_PASSWORD": ""}).invoke(
        main.cli, [*backend, "serial"]
    )
    # the existing sign-in path: no credentials, so it stops there
    assert result.exit_code == 1
    assert not any(m.startswith("nwp500.ble") for m in sys.modules)
    assert "nwp500.cli.ble_backend" not in sys.modules
