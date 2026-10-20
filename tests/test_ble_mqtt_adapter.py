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
    DeviceInfoBlock,
    NavienBleClient,
    RealTimeStatus,
    SoftwareInfoBlock,
    build_packet,
    device_feature_from_blocks,
    parse_packet,
)
from nwp500.enums import CurrentOperationMode
from nwp500.exceptions import Nwp500Error

# Read from an NWP500 on 2026-10-16. Its MQTT device-info report on
# 2026-10-19 had controllerSerialNumber 56496061BT22230408,
# dhwTemperatureMin 81, dhwTemperatureMax 131, modelTypeCode 240 and
# countryCode 3.
DID = bytes.fromhex(
    "050ba1000000033b00000000000000008351000000f00100030100000000141a"
    "030ab51475050000000000000000000010d20000000000000000"
)
# Read on 2026-10-16; controllerSwCode in that MQTT report was
# 33556241 = 0x02000711.
MSWD = bytes.fromhex(
    "110700020b05000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000"
)
MSCD = bytes.fromhex(
    "3536343936303631425432323233303430380000"
    "3536343936303631425432323233303430380000"
)

# Pushed by the same NWP500 on 2026-10-19 after the class-50 session
# command 200. RTMD is a steady block, taken while the MQTT status report
# had currentStatenum 20, dhwTemperature 110, dhwTemperatureSetting 122,
# tankUpperTemperature 553, tankLowerTemperature 510, dischargeTemperature
# 401, suctionTemperature 238, evaporatorTemperature 276,
# ambientTemperature 242, currentSuperHeat -16 and eevStep 480.
# RTMD_STALE is the first block after the command, which held values from
# earlier (its tank upper reads 58.4 degC against 55.3).
RTMD = bytes.fromhex(
    "001400000000000000000000000000002602e401000000000000000000008100"
    "0000007a0000000000001d04f2038503e2020803e6020000c800000000000800"
    "0000f401f40101003800f80000000000e001000000000000e001010000000000"
    "0000000000000000000000000000002002000000000000000400040000000000"
    "00000000000000000000000000000000000000000000000000000000"
)
RTMD_STALE = bytes.fromhex(
    "2032000026021f029e050000000000002602ea01000000000000000000000100"
    "0000007b0000000000003c042f0430046d028e0207030000c800000000000000"
    "0000f401f401b301c906fb0000000000c800000000000000c800010000000000"
    "0000000000000000000000000000003702000001000000000400040000000000"
    "00000000000000000000000000000000000000000000000000000000"
)


class FakeTransport:
    """Answers reads of the classes it was given, like the heater.

    Like the heater, the session command 200 starts a status stream: the
    blocks in ``stream`` are pushed. A read is answered and ends the
    stream.
    """

    def __init__(
        self,
        replies: dict[int, bytes],
        stream: tuple[bytes, ...] = (RTMD_STALE, RTMD),
    ) -> None:
        self.replies = replies
        self.stream = stream
        self.streaming = False
        self.written: list[bytes] = []
        self.connected = False
        self._cb = None

    def push(self, block: bytes) -> None:
        """Push one status block, as the heater does while streaming."""
        packet = build_packet(Command.WRITE, ClassCode.RTMD, block)
        assert self._cb is not None, "push before start_notify"
        asyncio.get_running_loop().call_soon(self._cb, packet)

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def start_notify(self, callback) -> None:
        self._cb = callback

    async def write(self, data: bytes) -> None:
        self.written.append(data)
        req = parse_packet(data)
        if req.class_code == ClassCode.SAPCD and req.data[:1] == b"\xc8":
            self.streaming = True
            for block in self.stream:
                self.push(block)
        elif req.class_code in self.replies:
            self.streaming = False
            reply = build_packet(
                Command.READ_RESPONSE,
                req.class_code,
                self.replies[req.class_code],
            )
            asyncio.get_running_loop().call_soon(self._cb, reply)


def _heater() -> FakeTransport:
    return FakeTransport(
        {ClassCode.DID: DID, ClassCode.MSCD: MSCD, ClassCode.MSWD: MSWD}
    )


def test_feature_carries_only_the_fields_checked_against_mqtt() -> None:
    feature = device_feature_from_blocks(
        DeviceInfoBlock.parse(DID),
        ControllerSerials.parse(MSCD),
        SoftwareInfoBlock.parse(MSWD),
    )
    assert feature.controller_serial_number == "56496061BT22230408"
    assert feature.dhw_temperature_min_raw == 81
    assert feature.dhw_temperature_max_raw == 131
    assert feature.model_type_code == 240
    assert feature.country_code == 3
    assert feature.controller_sw_code == 33556241
    # fields Bluetooth does not carry are absent, not defaulted
    with pytest.raises(AttributeError):
        feature.hpwh_use  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_adapter_answers_a_device_feature_request() -> None:
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
    assert asked == [ClassCode.DID, ClassCode.MSCD, ClassCode.MSWD]


@pytest.mark.asyncio
async def test_controller_serial_helper_runs_unchanged_over_bluetooth() -> None:
    pytest.importorskip("click")
    from nwp500.cli.handlers import get_controller_serial_number

    async with BleMqttAdapter(NavienBleClient(transport=_heater())) as mqtt:
        serial = await get_controller_serial_number(mqtt, None)  # type: ignore[arg-type]
    assert serial == "56496061BT22230408"


@pytest.mark.parametrize(
    "name", ["set_dhw_temperature", "set_power", "control", "client_id"]
)
def test_other_mqtt_attributes_raise_a_clear_error(name: str) -> None:
    mqtt = BleMqttAdapter(NavienBleClient(transport=_heater()))
    with pytest.raises(
        BleUnsupportedError, match="not available over Bluetooth"
    ):
        getattr(mqtt, name)


def test_unsupported_error_is_a_library_error() -> None:
    assert issubclass(BleUnsupportedError, Nwp500Error)
    assert BleUnsupportedError("set_power").operation == "set_power"


def test_private_attributes_are_plain_attribute_errors() -> None:
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

    def invoke(*args: str, options: tuple[str, ...] = ()):
        return CliRunner().invoke(
            cli,
            [*options, "--backend", "ble", "--ble-address", "AA:BB", *args],
        )

    invoke.transport = transport  # type: ignore[attr-defined]
    return invoke


def test_cli_serial_over_bluetooth(cli_with_fake_heater) -> None:
    result = cli_with_fake_heater("serial")
    assert result.exit_code == 0, result.output
    assert "56496061BT22230408" in result.output


def test_cli_info_over_bluetooth_shows_only_block_fields(
    cli_with_fake_heater,
) -> None:
    result = cli_with_fake_heater("info")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Controller serial" in out and "56496061BT22230408" in out
    assert "Controller SW code  0x02000711" in out
    assert "104.9 - 149.9 °F" in out
    assert "Min operation temp  104.9 °F" in out
    # nothing the blocks do not carry, such as firmware or capability flags
    assert "firmware" not in out.lower() and "supported" not in out.lower()


def test_cli_info_raw_over_bluetooth(cli_with_fake_heater) -> None:
    result = cli_with_fake_heater("info", "--raw")
    assert result.exit_code == 0, result.output
    for block in (DID, MSCD, MSWD):
        assert block.hex() in result.output


@pytest.mark.parametrize(
    "args", [["power", "on"], ["temp", "120"], ["reservations", "get"]]
)
def test_cli_refuses_other_commands_before_connecting(
    cli_with_fake_heater, args
) -> None:
    result = cli_with_fake_heater(*args)
    assert result.exit_code == 2
    assert "not available over Bluetooth" in result.output
    assert cli_with_fake_heater.transport.written == []


def test_cli_mqtt_backend_does_not_load_bluetooth(monkeypatch) -> None:
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
def test_cli_without_ble_backend_takes_the_cloud_path(
    monkeypatch, backend
) -> None:
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


@pytest.fixture
def unit_system():
    from nwp500.unit_system import reset_unit_system, set_unit_system

    yield set_unit_system
    reset_unit_system()


def test_cli_info_over_bluetooth_honours_unit_system(
    cli_with_fake_heater, unit_system
) -> None:
    result = cli_with_fake_heater("info", options=("--unit-system", "metric"))
    assert result.exit_code == 0, result.output
    assert "40.5 - 65.5 °C" in result.output
    assert "Min operation temp  40.5 °C" in result.output


def test_ble_feature_converts_like_device_feature(unit_system) -> None:
    from nwp500.models import DeviceFeature

    ble = device_feature_from_blocks(
        DeviceInfoBlock.parse(DID),
        ControllerSerials.parse(MSCD),
        SoftwareInfoBlock.parse(MSWD),
    )
    # the cloud model with the same raw values (its other required fields
    # are irrelevant to the conversion)
    cloud = DeviceFeature.model_construct(
        dhw_temperature_min_raw=81, dhw_temperature_max_raw=131
    )
    for system in (None, "us_customary", "metric"):
        unit_system(system)
        assert (ble.dhw_temperature_min, ble.dhw_temperature_max) == (
            cloud.dhw_temperature_min,
            cloud.dhw_temperature_max,
        )
        assert ble.get_field_unit("dhw_temperature_min") == (
            cloud.get_field_unit("dhw_temperature_min")
        )
    assert ble.get_field_unit("country_code") == ""


def test_min_operation_temperature_follows_unit_system(unit_system) -> None:
    info = DeviceInfoBlock.parse(DID)
    assert info.min_operation_temperature() == pytest.approx(104.9)
    unit_system("metric")
    assert info.min_operation_temperature() == pytest.approx(40.5)
    # an explicit unit still wins
    assert info.min_operation_temperature(celsius=False) == pytest.approx(104.9)


# --- live status (RTMD) ------------------------------------------------


def test_rtmd_decodes_the_fields_checked_against_mqtt() -> None:
    status = RealTimeStatus.parse(RTMD)
    assert status.operation_mode is CurrentOperationMode.STANDBY
    assert status.current_statenum == 20
    assert status.dhw_temperature_raw == 110
    assert status.dhw_temperature_setting_raw == 122
    assert status.tank_upper_temperature_raw == 553
    assert status.tank_lower_temperature_raw == 510
    assert status.discharge_temperature_raw == 401
    assert status.suction_temperature_raw == 238
    assert status.evaporator_temperature_raw == 276
    assert status.ambient_temperature_raw == 242
    assert status.current_super_heat_raw == -16
    assert status.eev_step == 480
    assert status.raw == RTMD
    # fields not decoded are absent, not defaulted
    with pytest.raises(AttributeError):
        status.comp_use  # type: ignore[attr-defined]


def test_rtmd_operation_mode_while_heating_and_unknown() -> None:
    # MQTT reported operationMode 32 and currentStatenum 50 while heating
    heating = RealTimeStatus.parse(RTMD_STALE)
    assert heating.operation_mode is CurrentOperationMode.HEAT_PUMP_MODE
    assert heating.current_statenum == 50
    unknown = RealTimeStatus.parse(bytes([7]) + RTMD[1:])
    assert unknown.operation_mode == 7


def test_rtmd_rejects_a_block_of_the_wrong_length() -> None:
    with pytest.raises(ValueError, match="156 bytes"):
        RealTimeStatus.parse(RTMD[:-1])


def test_rtmd_converts_like_device_status(unit_system) -> None:
    from nwp500.models import DeviceStatus

    ble = RealTimeStatus.parse(RTMD)
    names = [
        "dhw_temperature",
        "dhw_temperature_setting",
        "tank_upper_temperature",
        "tank_lower_temperature",
        "discharge_temperature",
        "suction_temperature",
        "evaporator_temperature",
        "ambient_temperature",
        "current_super_heat",
    ]
    # the cloud model with the same raw values (its other required fields
    # are irrelevant to the conversion)
    cloud = DeviceStatus.model_construct(
        **{f"{n}_raw": getattr(ble, f"{n}_raw") for n in names}
    )
    for system in ("us_customary", "metric"):
        unit_system(system)
        for name in names:
            assert getattr(ble, name) == getattr(cloud, name), name
            assert ble.get_field_unit(name) == cloud.get_field_unit(name)
    assert ble.get_field_unit("eev_step") == ""


@pytest.mark.asyncio
async def test_read_status_starts_stream_once_and_skips_stale_block() -> None:
    transport = _heater()
    async with NavienBleClient(transport=transport) as ble:
        first = await ble.read_status()
        assert first.raw == RTMD
        transport.push(RTMD_STALE[:1] + RTMD[1:])
        await asyncio.sleep(0)
        second = await ble.read_status()
    assert second.raw[0] == 0x20  # the newest block, not a resend
    commands = [parse_packet(w) for w in transport.written]
    assert [(c.command, c.class_code) for c in commands] == [
        (Command.WRITE, ClassCode.SAPCD)
    ]
    assert commands[0].data == bytes([200]) + bytes(29)


@pytest.mark.asyncio
async def test_read_status_restarts_the_stream_after_a_reconnect() -> None:
    transport = _heater()
    ble = NavienBleClient(transport=transport)
    for _ in range(2):
        async with ble:
            assert (await ble.read_status()).raw == RTMD
    assert len(transport.written) == 2


@pytest.mark.asyncio
async def test_read_status_times_out_when_nothing_is_pushed() -> None:
    transport = FakeTransport({}, stream=())
    async with NavienBleClient(transport=transport) as ble:
        with pytest.raises(TimeoutError, match="no status block"):
            await ble.read_status(timeout=0.05)


def test_status_waits_longer_than_a_reply() -> None:
    from nwp500.ble import STATUS_TIMEOUT

    assert STATUS_TIMEOUT > NavienBleClient(transport=_heater())._reply_timeout


@pytest.mark.asyncio
async def test_status_blocks_do_not_answer_a_read() -> None:
    transport = _heater()
    async with NavienBleClient(transport=transport, reply_timeout=0.1) as ble:
        await ble.read_status()
        # the blocks the heater pushes are not taken for the reply
        transport.push(RTMD)
        with pytest.raises(TimeoutError):
            await ble.read(ClassCode.RTMD, 156)


@pytest.mark.asyncio
async def test_read_status_restarts_the_stream_a_read_ended() -> None:
    transport = _heater()
    async with NavienBleClient(transport=transport) as ble:
        assert (await ble.read_status()).raw == RTMD
        info = await ble.read_device_info()
        assert not transport.streaming
        assert (await ble.read_status()).raw == RTMD
    assert info.raw == DID
    starts = [
        w
        for w in map(parse_packet, transport.written)
        if w.class_code == ClassCode.SAPCD
    ]
    assert len(starts) == 2


@pytest.mark.asyncio
async def test_adapter_answers_a_device_status_request() -> None:
    got: list[RealTimeStatus] = []
    async with BleMqttAdapter(NavienBleClient(transport=_heater())) as mqtt:
        await mqtt.subscribe_device_status(None, got.append)
        assert await mqtt.request_device_status(None) == 0
    assert [s.tank_upper_temperature_raw for s in got] == [553]


def test_cli_status_over_bluetooth(cli_with_fake_heater, unit_system) -> None:
    result = cli_with_fake_heater("status")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Operation mode   STANDBY" in out
    assert "State number     20" in out
    assert "DHW temperature  131.0 °F" in out
    assert "DHW setpoint     141.8 °F" in out
    assert "Tank upper       131.5 °F" in out
    assert "Ambient          75.6 °F" in out
    assert "EEV step         480" in out


def test_cli_status_over_bluetooth_honours_unit_system(
    cli_with_fake_heater, unit_system
) -> None:
    result = cli_with_fake_heater("status", options=("--unit-system", "metric"))
    assert result.exit_code == 0, result.output
    assert "Tank upper       55.3 °C" in result.output
    assert "Superheat        -1.6 °C" in result.output


def test_cli_status_raw_over_bluetooth(cli_with_fake_heater) -> None:
    result = cli_with_fake_heater("status", "--raw")
    assert result.exit_code == 0, result.output
    assert RTMD.hex() in result.output
