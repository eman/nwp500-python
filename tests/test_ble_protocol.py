"""Framing and client tests for nwp500.ble (no hardware, no bleak)."""

from __future__ import annotations

import asyncio

import pytest

from nwp500.ble import (
    ClassCode,
    Command,
    ControllerSerials,
    DeviceInfo,
    NavienBleClient,
    build_packet,
    build_read,
    crc16,
    parse_packet,
)


def test_crc16_is_modbus():
    assert crc16(b"123456789") == 0x4B37


def test_crc16_matches_app_table_algorithm():
    # The NaviLink app's CRC16Checker table is the CRC-16/ARC table used
    # with an 0xFFFF seed; this reproduces that computation independently.
    tab = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
        tab.append(c)

    def app_crc(data: bytes) -> int:
        s = 0xFFFF
        for b in data:
            s = tab[(b ^ s) & 0xFF] ^ (s >> 8)
        return s

    for sample in (b"", b"\x00", bytes(range(50)), b"HPWH1"):
        assert crc16(sample) == app_crc(sample)


def test_build_read_did_matches_app_bytes():
    # NaviLink: new SendPacket(3, ClassCode.CODE_DID, new byte[]{58})
    pkt = build_read(ClassCode.DID)
    assert pkt[:9] == bytes([0xF7, 0x20, 0x01, 0x03, 3, 3, 240, 0, 58])
    crc = crc16(pkt[:9])
    assert pkt[9:] == bytes([crc & 0xFF, crc >> 8])


def test_round_trip_narrow_address():
    pkt = build_packet(Command.WRITE, ClassCode.SPD, bytes(range(59)))
    parsed = parse_packet(pkt)
    assert parsed.command == Command.WRITE
    assert parsed.class_code == ClassCode.SPD
    assert parsed.address == 0
    assert parsed.data == bytes(range(59))
    assert parsed.crc_ok
    assert parsed.class_name == "SPD"
    assert not parsed.is_reply


def test_round_trip_wide_address_firmware_classes():
    pkt = build_packet(
        Command.WRITE, ClassCode.SFBD, b"\xaa\xbb", address=0x01020304
    )
    assert pkt[5] == 2 + 5
    assert pkt[7:11] == bytes([4, 3, 2, 1])
    parsed = parse_packet(pkt)
    assert parsed.address == 0x01020304
    assert parsed.data == b"\xaa\xbb"
    assert parsed.crc_ok


def test_parse_detects_bad_crc_and_short_packets():
    pkt = bytearray(build_read(ClassCode.MSCD))
    pkt[-1] ^= 0xFF
    assert parse_packet(bytes(pkt)).crc_ok is False
    with pytest.raises(ValueError):
        parse_packet(b"\xf7\x20\x01")
    with pytest.raises(ValueError):
        parse_packet(b"\x00" * 12)


def test_build_read_requires_length_for_unknown_class():
    with pytest.raises(ValueError):
        build_read(ClassCode.SDOD)
    assert build_read(ClassCode.SDOD, 10)[8] == 10


def test_device_info_parse():
    data = bytearray(58)
    data[0], data[1] = 2, 10  # version 10.2
    data[16], data[17] = (
        131,
        70,
    )  # hot water max/min (half-degrees C style values)
    data[21] = 240
    data[24] = 7
    data[26], data[27], data[28] = 25, 6, 30
    data[44], data[45] = 1, 3
    info = DeviceInfo.parse(bytes(data))
    assert (info.version, info.version_sub) == (10, 2)
    assert (info.hot_water_temp_max, info.hot_water_temp_min) == (131, 70)
    assert info.model_type == 240
    assert info.country_code == 7
    assert (
        info.manufacturing_year,
        info.manufacturing_month,
        info.manufacturing_day,
    ) == (25, 6, 30)
    assert (info.toolkit_version, info.toolkit_version_sub) == (3, 1)
    with pytest.raises(ValueError):
        DeviceInfo.parse(b"\x00" * 10)


def test_controller_serials_parse():
    data = bytearray(40)
    data[0:14] = b"56496061BT2223"
    data[20:32] = b"PCB-123456AB"
    cs = ControllerSerials.parse(bytes(data))
    assert cs.product_serial == "56496061BT2223"
    assert cs.pcb_serial == "PCB-123456AB"


class FakeTransport:
    """Echoes a canned reply for each class it is asked to read."""

    def __init__(self, replies: dict[int, bytes]):
        self.replies = replies
        self.written: list[bytes] = []
        self._cb = None
        self.connected = False

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
            body = self.replies[req.class_code]
            reply = build_packet(
                Command.READ_RESPONSE
                if req.command == Command.READ
                else Command.WRITE_RESPONSE,
                req.class_code,
                body,
            )
            # deliver asynchronously, like a GATT notification
            asyncio.get_running_loop().call_soon(self._cb, reply)


@pytest.mark.asyncio
async def test_client_reads_and_parses_blocks():
    did = bytes(58)
    mscd = bytearray(40)
    mscd[0:5] = b"SERIAL"[:5]
    spd = bytes(range(59))
    transport = FakeTransport(
        {
            ClassCode.DID: did,
            ClassCode.MSCD: bytes(mscd),
            ClassCode.SPD: spd,
            ClassCode.SPID: bytes(8),
            ClassCode.SPLD: bytes(59),
            ClassCode.SPHD: bytes(59),
        }
    )
    async with NavienBleClient(transport=transport) as ble:
        assert transport.connected
        info = await ble.read_device_info()
        assert info.raw == did
        serials = await ble.read_controller_serials()
        assert serials.product_serial == "SERIA"
        blocks = await ble.read_parameter_blocks()
        assert blocks[ClassCode.SPD] == spd
        assert set(blocks) == {
            ClassCode.SPID,
            ClassCode.SPLD,
            ClassCode.SPHD,
            ClassCode.SPD,
        }
    assert not transport.connected
    # every request was a read with the app's expected-length byte
    assert all(
        parse_packet(w).command == Command.READ for w in transport.written
    )
    assert parse_packet(transport.written[0]).data == bytes([58])


@pytest.mark.asyncio
async def test_client_times_out_without_reply():
    transport = FakeTransport({})
    async with NavienBleClient(transport=transport, reply_timeout=0.05) as ble:
        with pytest.raises(TimeoutError):
            await ble.read(ClassCode.DID)


@pytest.mark.asyncio
async def test_client_ignores_replies_for_other_classes():
    class Noisy(FakeTransport):
        async def write(self, data: bytes):
            # an unrelated status packet arrives first, then the real reply
            self._cb(
                build_packet(Command.READ_RESPONSE, ClassCode.SSD, bytes(59))
            )
            await super().write(data)

    transport = Noisy({ClassCode.DID: bytes(58)})
    async with NavienBleClient(transport=transport) as ble:
        pkt = await ble.read(ClassCode.DID)
        assert pkt.class_code == ClassCode.DID


@pytest.mark.asyncio
async def test_write_block_sends_write_command():
    transport = FakeTransport({ClassCode.SPD: b"\x01"})
    async with NavienBleClient(transport=transport) as ble:
        reply = await ble.write_block(ClassCode.SPD, bytes(59))
        assert reply.command == Command.WRITE_RESPONSE
    assert parse_packet(transport.written[0]).command == Command.WRITE


def test_client_requires_address_or_transport():
    with pytest.raises(ValueError):
        NavienBleClient()


def test_device_info_min_operation_temperature():
    # DID byte 17 = Min Operation Temp in half-degrees C; 81 -> 40.5C / 104.9F
    data = bytearray(58)
    data[21] = 240  # model type (HPWH)
    data[17] = 81
    info = DeviceInfo.parse(bytes(data))
    assert info.min_operation_temperature_raw == 81
    assert round(info.min_operation_temperature(celsius=True), 1) == 40.5
    assert round(info.min_operation_temperature(), 1) == 104.9
