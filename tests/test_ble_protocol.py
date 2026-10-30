"""Framing and client tests for nwp500.ble (no hardware, no bleak)."""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from nwp500.ble import (
    ADVERTISED_NAME_FRAGMENT,
    DEFAULT_READ_LENGTHS,
    NWP500_RESPONDING_CLASSES,
    NWP500_WRITABLE_CLASSES,
    TOU_PLAN_SLOTS,
    TOU_RECORD_SIZE,
    ClassCode,
    Command,
    ControllerSerials,
    CrcMismatchError,
    DeviceInfoBlock,
    NavienBleClient,
    SubStatus,
    TouWriteError,
    answers_class_codes,
    best_heater,
    build_packet,
    build_read,
    build_session_command,
    build_tou_read,
    build_tou_write,
    crc16,
    encode_tou_record,
    parse_packet,
    parse_tou_record,
    parse_tou_records,
)
from nwp500.models import TOUPeriod


def test_crc16_is_modbus() -> None:
    assert crc16(b"123456789") == 0x4B37


def test_crc16_matches_app_table_algorithm() -> None:
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


def test_build_read_did_matches_app_bytes() -> None:
    # NaviLink: new SendPacket(3, ClassCode.CODE_DID, new byte[]{58})
    pkt = build_read(ClassCode.DID)
    assert pkt[:9] == bytes([0xF7, 0x20, 0x01, 0x03, 3, 3, 240, 0, 58])
    crc = crc16(pkt[:9])
    assert pkt[9:] == bytes([crc & 0xFF, crc >> 8])


def test_round_trip_narrow_address() -> None:
    pkt = build_packet(Command.WRITE, ClassCode.SPD, bytes(range(59)))
    parsed = parse_packet(pkt)
    assert parsed.command == Command.WRITE
    assert parsed.class_code == ClassCode.SPD
    assert parsed.address == 0
    assert parsed.data == bytes(range(59))
    assert parsed.crc_ok
    assert parsed.class_name == "SPD"
    assert not parsed.is_reply


def test_round_trip_wide_address_firmware_classes() -> None:
    pkt = build_packet(
        Command.WRITE, ClassCode.SFBD, b"\xaa\xbb", address=0x01020304
    )
    assert pkt[5] == 2 + 5
    assert pkt[7:11] == bytes([4, 3, 2, 1])
    parsed = parse_packet(pkt)
    assert parsed.address == 0x01020304
    assert parsed.data == b"\xaa\xbb"
    assert parsed.crc_ok


def test_parse_detects_bad_crc_and_short_packets() -> None:
    pkt = bytearray(build_read(ClassCode.MSCD))
    pkt[-1] ^= 0xFF
    assert parse_packet(bytes(pkt)).crc_ok is False
    with pytest.raises(ValueError):
        parse_packet(b"\xf7\x20\x01")
    with pytest.raises(ValueError):
        parse_packet(b"\x00" * 12)


def test_build_read_requires_length_for_unknown_class() -> None:
    with pytest.raises(ValueError):
        build_read(ClassCode.SDOD)
    assert build_read(ClassCode.SDOD, 10)[8] == 10


def test_device_info_parse() -> None:
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
    info = DeviceInfoBlock.parse(bytes(data))
    assert (info.version, info.version_sub) == (10, 2)
    assert (info.dhw_temperature_max_raw, info.dhw_temperature_min_raw) == (
        131,
        70,
    )
    assert info.model_type_code == 240
    assert info.country_code == 7
    assert (
        info.manufacturing_year,
        info.manufacturing_month,
        info.manufacturing_day,
    ) == (25, 6, 30)
    assert (info.toolkit_version, info.toolkit_version_sub) == (3, 1)
    with pytest.raises(ValueError):
        DeviceInfoBlock.parse(b"\x00" * 10)


def test_controller_serials_parse() -> None:
    data = bytearray(40)
    data[0:14] = b"56496061BT2223"
    data[20:32] = b"PCB-123456AB"
    cs = ControllerSerials.parse(bytes(data))
    assert cs.controller_serial_number == "56496061BT2223"
    assert cs.pcb_serial == "PCB-123456AB"


class FakeTransport:
    """Echoes a canned reply for each class it is asked to read."""

    def __init__(self, replies: dict[int, bytes]) -> None:
        self.replies = replies
        self.written: list[bytes] = []
        self._cb: Callable[[bytes], None] | None = None
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def start_notify(self, callback: Callable[[bytes], None]) -> None:
        self._cb = callback

    async def write(self, data: bytes) -> None:
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
            cb = cast(Callable[[bytes], None], self._cb)
            asyncio.get_running_loop().call_soon(cb, reply)


@pytest.mark.asyncio
async def test_client_reads_and_parses_blocks() -> None:
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
        assert serials.controller_serial_number == "SERIA"
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
    assert all(  # type: ignore[unreachable]  # __aexit__ disconnects
        parse_packet(w).command == Command.READ for w in transport.written
    )
    assert parse_packet(transport.written[0]).data == bytes([58])


@pytest.mark.asyncio
async def test_client_times_out_without_reply() -> None:
    transport = FakeTransport({})
    async with NavienBleClient(transport=transport, reply_timeout=0.05) as ble:
        with pytest.raises(TimeoutError):
            await ble.read(ClassCode.DID)


@pytest.mark.asyncio
async def test_client_ignores_replies_for_other_classes() -> None:
    class Noisy(FakeTransport):
        async def write(self, data: bytes) -> None:
            # an unrelated status packet arrives first, then the real reply
            cb = cast(Callable[[bytes], None], self._cb)
            cb(build_packet(Command.READ_RESPONSE, ClassCode.SSD, bytes(59)))
            await super().write(data)

    transport = Noisy({ClassCode.DID: bytes(58)})
    async with NavienBleClient(transport=transport) as ble:
        pkt = await ble.read(ClassCode.DID)
        assert pkt.class_code == ClassCode.DID


@pytest.mark.asyncio
async def test_write_block_sends_write_command() -> None:
    transport = FakeTransport({ClassCode.SPD: b"\x01"})
    async with NavienBleClient(transport=transport) as ble:
        reply = await ble.write_block(ClassCode.SPD, bytes(59))
        assert reply.command == Command.WRITE_RESPONSE
    assert parse_packet(transport.written[0]).command == Command.WRITE


def test_client_requires_address_or_transport() -> None:
    with pytest.raises(ValueError):
        NavienBleClient()


def test_device_info_min_operation_temperature() -> None:
    # DID byte 17 = Min Operation Temp in half-degrees C; 81 -> 40.5C / 104.9F
    data = bytearray(58)
    data[21] = 240  # model type (HPWH)
    data[17] = 81
    info = DeviceInfoBlock.parse(bytes(data))
    assert info.min_operation_temperature_raw == 81
    assert round(info.min_operation_temperature(celsius=True), 1) == 40.5
    assert round(info.min_operation_temperature(), 1) == 104.9


class CorruptTransport(FakeTransport):
    """Delivers each reply with its CRC bytes flipped."""

    async def write(self, data: bytes) -> None:
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
            cb = cast(Callable[[bytes], None], self._cb)
            asyncio.get_running_loop().call_soon(cb, bytes(reply))


@pytest.mark.asyncio
async def test_decoding_readers_refuse_a_bad_crc() -> None:
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
async def test_failed_subscribe_disconnects(error: BaseException) -> None:
    class FailingNotify(FakeTransport):
        async def start_notify(self, callback: Callable[[bytes], None]) -> None:
            raise error

    transport = FailingNotify({})
    with pytest.raises(type(error)):
        async with NavienBleClient(transport=transport):
            pass  # pragma: no cover - never entered
    assert not transport.connected


@pytest.mark.asyncio
async def test_failed_subscribe_keeps_its_error_if_disconnect_fails() -> None:
    class Broken(FakeTransport):
        async def start_notify(self, callback: Callable[[bytes], None]) -> None:
            raise RuntimeError("subscribe failed")

        async def disconnect(self) -> None:
            raise RuntimeError("disconnect failed")

    with pytest.raises(RuntimeError, match="subscribe failed"):
        await NavienBleClient(transport=Broken({})).connect()


# --- python -m nwp500.ble read ---------------------------------------


def _run_read(
    monkeypatch: pytest.MonkeyPatch,
    transport: FakeTransport,
    argv: list[str],
) -> int:
    from nwp500.ble import __main__ as cli

    def make_client(address: str) -> NavienBleClient:
        return NavienBleClient(transport=transport, reply_timeout=0.05)

    monkeypatch.setattr(cli, "NavienBleClient", make_client)
    return cli.main(["read", "--address", "AA:BB", *argv])


def test_cli_read_defaults_to_the_classes_the_heater_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTransport(
        {c: bytes(DEFAULT_READ_LENGTHS[c]) for c in NWP500_RESPONDING_CLASSES}
    )
    assert _run_read(monkeypatch, transport, []) == 0
    # TOU_PLAN is also read whole, after its block, to decode the plan.
    asked = [parse_packet(w).class_code for w in transport.written]
    assert list(dict.fromkeys(asked)) == sorted(NWP500_RESPONDING_CLASSES)
    assert not {51, 52, 53, 54} & set(asked)


def test_cli_read_fails_when_nothing_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "blocks.json"
    transport = FakeTransport({})
    status = _run_read(monkeypatch, transport, ["--out", str(out), "SPID"])
    assert status == 1
    assert not out.exists()


def test_cli_read_succeeds_on_a_partial_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "blocks.json"
    transport = FakeTransport({ClassCode.DID: bytes(58)})
    status = _run_read(
        monkeypatch, transport, ["--out", str(out), "DID", "SPID"]
    )
    assert status == 0
    assert '"name": "DID"' in out.read_text()


def test_every_default_cli_class_has_a_read_length() -> None:
    assert NWP500_RESPONDING_CLASSES <= set(DEFAULT_READ_LENGTHS)


@pytest.mark.asyncio
async def test_scan_without_bleak_gives_the_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from nwp500.ble import scan

    monkeypatch.setitem(sys.modules, "bleak", None)
    with pytest.raises(RuntimeError, match=r"nwp500-python\[ble\]"):
        await scan(0)


def test_transport_without_bleak_gives_the_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def _cloud_period(
    season: int,
    week: int,
    start: tuple[int, int],
    end: tuple[int, int],
    price: int,
) -> TOUPeriod:
    """A TOUPeriod as the MQTT client and REST API build it."""
    return TOUPeriod.model_validate(
        {
            "season": season,
            "week": week,
            "startHour": start[0],
            "startMinute": start[1],
            "endHour": end[0],
            "endMinute": end[1],
            "priceMin": price,
            "priceMax": price,
            "decimalPoint": 5,
        }
    )


def test_tou_records_equal_the_cloud_periods() -> None:
    records = parse_tou_records(TOU_PLAN_PAGE)
    assert all(isinstance(r, TOUPeriod) for r in records)
    assert records == [_cloud_period(*iv) for iv in CLOUD_INTERVALS]
    assert records[6].decoded_price_max == pytest.approx(0.55214)


def test_tou_record_field_positions() -> None:
    raw = (
        bytes([0x34, 0x12, 0x82, 1, 2, 3, 4, 2])
        + (1000).to_bytes(4, "little")
        + (250).to_bytes(4, "little")
    )
    r = parse_tou_record(raw)
    assert (r.season, r.week) == (0x1234, 0x82)
    assert (r.start_hour, r.start_min, r.end_hour, r.end_min) == (1, 2, 3, 4)
    assert (r.price_max, r.price_min, r.decimal_point) == (1000, 250, 2)
    assert r.decoded_price_min == pytest.approx(2.5)


def test_parse_tou_records_drops_empty_slots_and_rejects_partial_records() -> (
    None
):
    padded = TOU_PLAN_PAGE[:32] + bytes(48)
    assert len(parse_tou_records(padded)) == 2
    assert parse_tou_records(b"") == []
    with pytest.raises(ValueError):
        parse_tou_records(TOU_PLAN_PAGE[:20])
    with pytest.raises(ValueError):
        parse_tou_record(bytes(15))
    assert TOU_RECORD_SIZE == 16


# Slots 12-19 of the same heater's table (2026-10-20): the rest of its plan.
TOU_PLAN_REST = bytes.fromhex(
    "000e7c00000e3b05346f0000346f0000000e7c0f000f3b059e7400009e740000"
    "000e7c1000143b054e8200004e820000000e7c1500173b059e7400009e740000"
    "1f0e8200000e3b05346f0000346f00001f0e820f000f3b059e7400009e740000"
    "1f0e821000143b053f7d00003f7d00001f0e821500173b059e7400009e740000"
)


class TouTableTransport(FakeTransport):
    """The heater's TOU table, as it behaved on an NWP500 (2026-10-20).

    A read's address is the first slot and its payload byte the last; the
    reply's byte count wraps at 256, and more than 224 bytes is never
    sent. Slots past the table hold other data. A write is stored at
    address 0 only, up to twelve records with none all zero; any other
    address is answered with 04 and clears the table.
    """

    def __init__(self, table: bytes = b"", accept: bool = True) -> None:
        super().__init__({})
        size = TOU_RECORD_SIZE * TOU_PLAN_SLOTS
        self.table = bytearray(table.ljust(size, b"\0"))
        self.after = bytes.fromhex("01000001ff002410011a000000000000") * 4
        self.accept = accept

    def _reply(self, command: int, data: bytes) -> None:
        packet = build_packet(command, ClassCode.TOU_PLAN, data)
        cb = cast(Callable[[bytes], None], self._cb)
        asyncio.get_running_loop().call_soon(cb, packet)

    async def write(self, data: bytes) -> None:
        self.written.append(data)
        req = parse_packet(data)
        if req.command == Command.READ:
            count = TOU_RECORD_SIZE * (req.data[0] - req.address + 1) & 0xFF
            if count <= 224:
                start = TOU_RECORD_SIZE * req.address
                memory = bytes(self.table) + self.after
                self._reply(Command.READ_RESPONSE, memory[start:][:count])
            return
        records = req.data[8:]
        if req.address != 0:
            self.table[:] = bytes(len(self.table))
            self._reply(Command.WRITE_RESPONSE, b"\x04")
            return
        slots = [records[o : o + 16] for o in range(0, len(records), 16)]
        if len(records) % 16 or len(slots) > 12 or not all(map(any, slots)):
            return
        if self.accept:
            self.table[: len(records)] = records
        self._reply(Command.WRITE_RESPONSE, b"\x01")


def test_build_tou_read_sends_the_last_slot_as_the_payload() -> None:
    request = parse_packet(build_tou_read(14, 27))
    assert (request.class_code, request.address) == (ClassCode.TOU_PLAN, 14)
    assert request.data == bytes([27])
    for first, last in ((5, 4), (0, 14), (30, 40), (-1, 3)):
        with pytest.raises(ValueError):
            build_tou_read(first, last)


def test_tou_record_encodes_back_to_the_bytes_read() -> None:
    page = TOU_PLAN_PAGE + TOU_PLAN_REST
    for o in range(0, len(page), 16):
        raw = page[o : o + 16]
        assert encode_tou_record(parse_tou_record(raw)) == raw


def test_tou_record_encoding_rejects_empty_and_oversized_fields() -> None:
    with pytest.raises(ValueError, match="empty slot"):
        encode_tou_record(TOUPeriod(decimal_point=0))  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="season"):
        encode_tou_record(TOUPeriod(season=0x10000, week=0x7C))
    with pytest.raises(ValueError, match="price_min"):
        encode_tou_record(
            TOUPeriod(season=1, price_min=-1)  # type: ignore[call-arg]
        )


def test_build_tou_write_puts_the_clock_header_before_the_records() -> None:
    periods = parse_tou_records(TOU_PLAN_PAGE[:48])
    # A Monday: java.util.Calendar numbers it 2 (Sunday = 1).
    now = datetime.datetime(2026, 10, 19, 17, 5, 9, tzinfo=datetime.UTC)
    request = parse_packet(build_tou_write(periods, now))
    assert (request.command, request.class_code) == (
        Command.WRITE,
        ClassCode.TOU_PLAN,
    )
    assert request.address == 0
    assert request.data[:8] == bytes([0xEA, 0x07, 10, 19, 2, 17, 5, 9])
    assert request.data[8:] == TOU_PLAN_PAGE[:48]
    sunday = parse_packet(build_tou_write(periods, now.replace(day=18)))
    assert sunday.data[4] == 1


def test_build_tou_write_limits_the_plan_to_twelve_intervals() -> None:
    periods = parse_tou_records(TOU_PLAN_PAGE + TOU_PLAN_REST)
    assert len(parse_packet(build_tou_write(periods[:12])).data) == 8 + 192
    for count in (0, 13):
        with pytest.raises(ValueError):
            build_tou_write(periods[:count])


def test_tou_plan_is_the_only_class_written_so_far() -> None:
    assert NWP500_WRITABLE_CLASSES == {ClassCode.TOU_PLAN}


@pytest.mark.asyncio
async def test_client_reads_the_whole_tou_table() -> None:
    transport = TouTableTransport(TOU_PLAN_PAGE + TOU_PLAN_REST)
    async with NavienBleClient(transport=transport) as ble:
        records = await ble.read_tou_records()
    assert len(records) == 20
    assert records == parse_tou_records(TOU_PLAN_PAGE + TOU_PLAN_REST)
    spans = [
        (r.address, r.data[0]) for r in map(parse_packet, transport.written)
    ]
    assert spans == [(0, 13), (14, 27), (28, 39)]


@pytest.mark.asyncio
async def test_client_writes_a_tou_plan_and_checks_it() -> None:
    periods = parse_tou_records(TOU_PLAN_PAGE)
    transport = TouTableTransport(TOU_PLAN_PAGE[:64])
    async with NavienBleClient(transport=transport) as ble:
        await ble.write_tou_records(periods)
        assert await ble.read_tou_records() == periods
    writes = [
        p
        for p in map(parse_packet, transport.written)
        if p.command == Command.WRITE
    ]
    assert len(writes) == 1
    assert writes[0].address == 0


@pytest.mark.asyncio
async def test_client_refuses_to_leave_a_longer_plan_behind() -> None:
    transport = TouTableTransport(TOU_PLAN_PAGE + TOU_PLAN_REST)
    async with NavienBleClient(transport=transport) as ble:
        with pytest.raises(TouWriteError, match="cloud"):
            await ble.write_tou_records(parse_tou_records(TOU_PLAN_PAGE))
    assert all(
        parse_packet(w).command == Command.READ for w in transport.written
    )


@pytest.mark.asyncio
async def test_client_reports_a_refused_or_unstored_tou_write() -> None:
    periods = parse_tou_records(TOU_PLAN_PAGE[:32])

    class Refusing(TouTableTransport):
        async def write(self, data: bytes) -> None:
            if parse_packet(data).command == Command.WRITE:
                self.written.append(data)
                self._reply(Command.WRITE_RESPONSE, b"\x04")
                return
            await super().write(data)

    async with NavienBleClient(transport=Refusing()) as ble:
        with pytest.raises(TouWriteError, match="refused"):
            await ble.write_tou_records(periods)
    async with NavienBleClient(
        transport=TouTableTransport(accept=False)
    ) as ble:
        with pytest.raises(TouWriteError, match="differs"):
            await ble.write_tou_records(periods)


@pytest.mark.asyncio
async def test_client_retries_a_read_the_heater_did_not_answer() -> None:
    class DropsFirst(FakeTransport):
        async def write(self, data: bytes) -> None:
            if not self.written:
                self.written.append(data)
                return
            await super().write(data)

    transport = DropsFirst({ClassCode.DID: bytes(58)})
    async with NavienBleClient(transport=transport, reply_timeout=0.05) as ble:
        info = await ble.read_device_info()
    assert info.raw == bytes(58)
    assert len(transport.written) == 2


@pytest.mark.asyncio
async def test_client_refuses_a_tou_reply_with_a_bad_crc() -> None:
    transport = CorruptTransport({ClassCode.TOU_PLAN: TOU_PLAN_PAGE})
    async with NavienBleClient(transport=transport) as ble:
        with pytest.raises(CrcMismatchError):
            await ble.read_tou_records()


def test_build_read_carries_the_address() -> None:
    assert parse_packet(build_read(ClassCode.TOU_PLAN, None, 15)).address == 15


def test_cli_read_prints_the_whole_tou_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = TouTableTransport(TOU_PLAN_PAGE + TOU_PLAN_REST)
    assert _run_read(monkeypatch, transport, ["TOU_PLAN"]) == 0
    out = capsys.readouterr().out
    assert "season=0x01f week=0x7c 00:00-14:59 price=0.28468-0.28468" in out
    assert "season=0xe1f week=0x82 21:00-23:59" in out
    assert out.count("season=") == 20


# --- SSD ---------------------------------------------------------------

# Read from an NWP500 (2026-10-16): 59 bytes, only byte 16 set.
SSD_BLOCK = bytes.fromhex(
    "000000000000000000000000000000000400000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000"
)


def test_sub_status_reads_the_toolkit_dip_switch_words() -> None:
    assert len(SSD_BLOCK) == 59
    ssd = SubStatus.parse(SSD_BLOCK)
    assert (ssd.dip_switch_1, ssd.dip_switch_2) == (0x0004, 0x0000)
    assert ssd.raw == SSD_BLOCK


def test_sub_status_words_are_little_endian() -> None:
    data = bytearray(60)  # the boiler block length the toolkit expects
    data[16:20] = bytes([0x01, 0x80, 0x34, 0x12])
    ssd = SubStatus.parse(bytes(data))
    assert (ssd.dip_switch_1, ssd.dip_switch_2) == (0x8001, 0x1234)


def test_sub_status_rejects_a_short_block() -> None:
    with pytest.raises(ValueError):
        SubStatus.parse(bytes(19))


@pytest.mark.asyncio
async def test_client_reads_sub_status() -> None:
    transport = FakeTransport({ClassCode.SSD: SSD_BLOCK})
    async with NavienBleClient(transport=transport) as ble:
        assert (await ble.read_sub_status()).dip_switch_1 == 4


@pytest.mark.asyncio
async def test_client_refuses_an_ssd_reply_with_a_bad_crc() -> None:
    transport = CorruptTransport({ClassCode.SSD: SSD_BLOCK})
    async with NavienBleClient(transport=transport) as ble:
        with pytest.raises(CrcMismatchError):
            await ble.read_sub_status()


def test_cli_read_prints_decoded_sub_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport({ClassCode.SSD: SSD_BLOCK})
    assert _run_read(monkeypatch, transport, ["SSD"]) == 0
    assert "dip_switch_1=0x0004 dip_switch_2=0x0000" in capsys.readouterr().out


def test_software_info_block_reads_the_controller_sw_code() -> None:
    from nwp500.ble import SoftwareInfoBlock

    sw = SoftwareInfoBlock.parse(bytes.fromhex("110700020b05") + bytes(53))
    assert sw.controller_sw_code == 0x02000711
    with pytest.raises(ValueError):
        SoftwareInfoBlock.parse(bytes(3))


def test_session_command_is_a_30_byte_class_50_write() -> None:
    packet = parse_packet(build_session_command(200))
    assert packet.crc_ok
    assert (packet.command, packet.class_code) == (Command.WRITE, 50)
    assert packet.data == bytes([200]) + bytes(29)
    with pytest.raises(ValueError):
        build_session_command(256)


def test_scan_filter_matches_both_advertised_names() -> None:
    for name in ("HPWH1A2B", "HPWH4610"):
        assert ADVERTISED_NAME_FRAGMENT in name
    assert answers_class_codes("hpwh1a2b")
    assert not answers_class_codes("HPWH4610")


def test_best_heater_skips_the_wifi_setup_mode() -> None:
    setup = ("AA", "HPWH4610", -30)
    weak, strong = ("BB", "HPWH1X", -80), ("CC", "HPWH1Y", -50)
    assert best_heater([setup, weak, strong]) == strong
    assert best_heater([setup]) is None
    assert best_heater([]) is None
