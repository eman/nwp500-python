"""Framing and client tests for nwp500.ble (no hardware, no bleak)."""

from __future__ import annotations

import asyncio

import pytest

from nwp500.ble import (
    DEFAULT_READ_LENGTHS,
    NWP500_RESPONDING_CLASSES,
    ClassCode,
    Command,
    ControllerSerials,
    CrcMismatchError,
    DeviceInfo,
    NavienBleClient,
    TouRecord,
    build_packet,
    build_read,
    crc16,
    parse_packet,
    parse_tou_records,
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


class CorruptTransport(FakeTransport):
    """Delivers each reply with its CRC bytes flipped."""

    async def write(self, data: bytes):
        self.written.append(data)
        req = parse_packet(data)
        if req.class_code in self.replies:
            reply = bytearray(
                build_packet(
                    Command.READ_RESPONSE,
                    req.class_code,
                    self.replies[req.class_code],
                )
            )
            reply[-1] ^= 0xFF
            asyncio.get_running_loop().call_soon(self._cb, bytes(reply))


@pytest.mark.asyncio
async def test_decoding_readers_refuse_a_bad_crc():
    transport = CorruptTransport(
        {
            ClassCode.DID: bytes(58),
            ClassCode.MSCD: bytes(40),
            ClassCode.SPID: bytes(8),
        }
    )
    async with NavienBleClient(transport=transport) as ble:
        # The raw read still returns the packet, flagged, for diagnosis.
        pkt = await ble.read(ClassCode.DID)
        assert pkt.crc_ok is False
        with pytest.raises(CrcMismatchError):
            await ble.read_device_info()
        with pytest.raises(CrcMismatchError):
            await ble.read_controller_serials()
        with pytest.raises(CrcMismatchError):
            await ble.read_parameter_blocks()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [RuntimeError("gatt"), asyncio.CancelledError()]
)
async def test_failed_subscribe_disconnects(error: BaseException):
    class FailingNotify(FakeTransport):
        async def start_notify(self, callback):
            raise error

    transport = FailingNotify({})
    with pytest.raises(type(error)):
        async with NavienBleClient(transport=transport):
            pass  # pragma: no cover - never entered
    assert not transport.connected


@pytest.mark.asyncio
async def test_failed_subscribe_keeps_its_error_if_disconnect_fails():
    class Broken(FakeTransport):
        async def start_notify(self, callback):
            raise RuntimeError("subscribe failed")

        async def disconnect(self):
            raise RuntimeError("disconnect failed")

    with pytest.raises(RuntimeError, match="subscribe failed"):
        await NavienBleClient(transport=Broken({})).connect()


# --- python -m nwp500.ble read ---------------------------------------


def _run_read(monkeypatch, transport, argv):
    from nwp500.ble import __main__ as cli

    monkeypatch.setattr(
        cli,
        "NavienBleClient",
        lambda address: NavienBleClient(
            transport=transport, reply_timeout=0.05
        ),
    )
    return cli.main(["read", "--address", "AA:BB", *argv])


def test_cli_read_defaults_to_the_classes_the_heater_answers(monkeypatch):
    transport = FakeTransport(
        {c: bytes(DEFAULT_READ_LENGTHS[c]) for c in NWP500_RESPONDING_CLASSES}
    )
    assert _run_read(monkeypatch, transport, []) == 0
    asked = [parse_packet(w).class_code for w in transport.written]
    assert asked == sorted(NWP500_RESPONDING_CLASSES)
    assert not {51, 52, 53, 54} & set(asked)


def test_cli_read_fails_when_nothing_answers(monkeypatch, tmp_path):
    out = tmp_path / "blocks.json"
    transport = FakeTransport({})
    status = _run_read(monkeypatch, transport, ["--out", str(out), "SPID"])
    assert status == 1
    assert not out.exists()


def test_cli_read_succeeds_on_a_partial_dump(monkeypatch, tmp_path):
    out = tmp_path / "blocks.json"
    transport = FakeTransport({ClassCode.DID: bytes(58)})
    status = _run_read(
        monkeypatch, transport, ["--out", str(out), "DID", "SPID"]
    )
    assert status == 0
    assert '"name": "DID"' in out.read_text()


def test_every_default_cli_class_has_a_read_length():
    assert NWP500_RESPONDING_CLASSES <= set(DEFAULT_READ_LENGTHS)


@pytest.mark.asyncio
async def test_scan_without_bleak_gives_the_install_hint(monkeypatch):
    import sys

    from nwp500.ble import scan

    monkeypatch.setitem(sys.modules, "bleak", None)
    with pytest.raises(RuntimeError, match=r"nwp500-python\[ble\]"):
        await scan(0)


def test_transport_without_bleak_gives_the_install_hint(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "bleak", None)
    with pytest.raises(RuntimeError, match=r"nwp500-python\[ble\]"):
        NavienBleClient("AA:BB")


# --- TOU_PLAN ---------------------------------------------------------

# Read from an NWP500 at address 0 (2026-10-16): twelve records, the first
# twelve intervals of its PG&E plan as the cloud's get_tou_info() returns it.
TOU_PLAN_PAGE = bytes.fromhex(
    "1f007c00000e3b05346f0000346f00001f007c0f000f3b059e7400009e740000"
    "1f007c1000143b053f7d00003f7d00001f007c1500173b059e7400009e740000"
    "e0017c00000e3b054e8200004e820000e0017c0f000f3b057298000072980000"
    "e0017c1000143b05aed70000aed70000e0017c1500173b057298000072980000"
    "e0018200000e3b054e8200004e820000e001820f000f3b057298000072980000"
    "e001821000143b05aed70000aed70000e001821500173b057298000072980000"
)

# (season, week, start, end, price) of the cloud's first twelve intervals
CLOUD_INTERVALS = [
    (0x01F, 0x7C, (0, 0), (14, 59), 28468),
    (0x01F, 0x7C, (15, 0), (15, 59), 29854),
    (0x01F, 0x7C, (16, 0), (20, 59), 32063),
    (0x01F, 0x7C, (21, 0), (23, 59), 29854),
    (0x1E0, 0x7C, (0, 0), (14, 59), 33358),
    (0x1E0, 0x7C, (15, 0), (15, 59), 39026),
    (0x1E0, 0x7C, (16, 0), (20, 59), 55214),
    (0x1E0, 0x7C, (21, 0), (23, 59), 39026),
    (0x1E0, 0x82, (0, 0), (14, 59), 33358),
    (0x1E0, 0x82, (15, 0), (15, 59), 39026),
    (0x1E0, 0x82, (16, 0), (20, 59), 55214),
    (0x1E0, 0x82, (21, 0), (23, 59), 39026),
]


def test_tou_records_match_the_cloud_plan():
    records = parse_tou_records(TOU_PLAN_PAGE)
    assert [
        (
            r.season,
            r.week,
            (r.start_hour, r.start_minute),
            (r.end_hour, r.end_minute),
            r.price_min,
        )
        for r in records
    ] == CLOUD_INTERVALS
    assert all(r.decimal_point == 5 for r in records)
    assert all(r.price_max == r.price_min for r in records)
    assert records[6].decoded_price_max == pytest.approx(0.55214)


def test_tou_record_field_positions():
    raw = (
        bytes([0x34, 0x12, 0x82, 1, 2, 3, 4, 2])
        + (1000).to_bytes(4, "little")
        + (250).to_bytes(4, "little")
    )
    r = TouRecord.parse(raw)
    assert (r.season, r.week) == (0x1234, 0x82)
    assert (r.start_hour, r.start_minute, r.end_hour, r.end_minute) == (
        1,
        2,
        3,
        4,
    )
    assert (r.price_max, r.price_min, r.decimal_point) == (1000, 250, 2)
    assert r.decoded_price_min == pytest.approx(2.5)


def test_tou_record_as_period_validates_as_tou_period():
    from nwp500.models import TOUPeriod

    record = parse_tou_records(TOU_PLAN_PAGE)[2]
    period = TOUPeriod.model_validate(record.as_period())
    assert (period.season, period.week) == (0x01F, 0x7C)
    assert (period.start_hour, period.end_hour, period.end_min) == (
        16,
        20,
        59,
    )
    assert period.decoded_price_min == pytest.approx(0.32063)


def test_parse_tou_records_drops_empty_slots_and_rejects_partial_records():
    padded = TOU_PLAN_PAGE[:32] + bytes(48)
    assert len(parse_tou_records(padded)) == 2
    assert parse_tou_records(b"") == []
    with pytest.raises(ValueError):
        parse_tou_records(TOU_PLAN_PAGE[:20])
    with pytest.raises(ValueError):
        TouRecord.parse(bytes(15))


@pytest.mark.asyncio
async def test_client_reads_tou_records_at_an_address():
    transport = FakeTransport({ClassCode.TOU_PLAN: TOU_PLAN_PAGE[64:]})
    async with NavienBleClient(transport=transport) as ble:
        records = await ble.read_tou_records(4)
    assert len(records) == 8
    assert records[0].season == 0x1E0
    request = parse_packet(transport.written[0])
    assert (request.class_code, request.address) == (ClassCode.TOU_PLAN, 4)


@pytest.mark.asyncio
async def test_client_refuses_a_tou_reply_with_a_bad_crc():
    transport = CorruptTransport({ClassCode.TOU_PLAN: TOU_PLAN_PAGE})
    async with NavienBleClient(transport=transport) as ble:
        with pytest.raises(CrcMismatchError):
            await ble.read_tou_records()


def test_build_read_carries_the_address():
    assert parse_packet(build_read(ClassCode.TOU_PLAN, None, 15)).address == 15


def test_cli_read_prints_decoded_tou_records(monkeypatch, capsys):
    transport = FakeTransport({ClassCode.TOU_PLAN: TOU_PLAN_PAGE})
    assert _run_read(monkeypatch, transport, ["TOU_PLAN"]) == 0
    out = capsys.readouterr().out
    assert "season=0x01f week=0x7c 00:00-14:59 price=0.28468-0.28468" in out
    assert out.count("season=") == 12
