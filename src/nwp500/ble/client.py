"""Bluetooth LE client for the NWP500's class-code service.

Requires the ``ble`` extra (``pip install nwp500-python[ble]``), which
pulls in `bleak <https://github.com/hbldh/bleak>`_. The transport is
injectable so the client is testable without hardware.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from ..exceptions import Nwp500Error
from ..models.tou import TOUPeriod
from .protocol import (
    ADVERTISED_NAME_FRAGMENT,
    DEFAULT_READ_LENGTHS,
    NOTIFY_CHAR_UUID,
    SERVICE_UUID,
    START_STATUS_STREAM,
    TOU_PLAN_SLOTS,
    TOU_READ_MAX_RECORDS,
    TOU_RECORD_SIZE,
    TOU_WRITE_ACCEPTED,
    WRITE_CHAR_UUID,
    ClassCode,
    Command,
    ControllerSerials,
    CrcMismatchError,
    DeviceInfoBlock,
    Packet,
    RealTimeStatus,
    SoftwareInfoBlock,
    SubStatus,
    build_packet,
    build_read,
    build_session_command,
    build_tou_read,
    build_tou_write,
    parse_packet,
    parse_tou_records,
)

_logger = logging.getLogger(__name__)

NotifyCallback = Callable[[bytes], None]

_NEEDS_EXTRA = (
    "Bluetooth support needs the 'ble' extra: pip install 'nwp500-python[ble]'"
)


class BleTransport(Protocol):
    """What the client needs from a GATT connection."""

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def start_notify(self, callback: NotifyCallback) -> None: ...
    async def write(self, data: bytes) -> None: ...


class BleakTransport:
    """GATT transport on top of bleak."""

    def __init__(self, address: str, timeout: float = 30.0) -> None:
        try:
            from bleak import BleakClient
        except ImportError as e:
            raise RuntimeError(_NEEDS_EXTRA) from e
        self._client = BleakClient(address, timeout=timeout)

    async def connect(self) -> None:
        await self._client.connect()

    async def disconnect(self) -> None:
        await self._client.disconnect()

    async def start_notify(self, callback: NotifyCallback) -> None:
        def _on(_handle: Any, data: bytearray) -> None:
            callback(bytes(data))

        await self._client.start_notify(NOTIFY_CHAR_UUID, _on)

    async def write(self, data: bytes) -> None:
        await self._client.write_gatt_char(WRITE_CHAR_UUID, data, response=True)


async def scan(timeout: float = 10.0) -> list[tuple[str, str, int]]:
    """Return ``(address, name, rssi)`` for heaters advertising nearby.

    A heater advertises in Bluetooth pairing mode (with the heater off,
    hold Back and Power for five seconds) as ``HPWH1…``, and in its Wi-Fi
    setup mode as ``HPWH4610``, which answers nothing. Both names match;
    :func:`best_heater` picks one that answers.

    Raises:
        RuntimeError: The ``ble`` extra (bleak) is not installed.
    """
    try:
        from bleak import BleakScanner
    except ImportError as e:
        raise RuntimeError(_NEEDS_EXTRA) from e

    found: dict[str, tuple[str, int]] = {}

    def _cb(device: Any, adv: Any) -> None:
        name = adv.local_name or device.name or ""
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        if ADVERTISED_NAME_FRAGMENT in name.upper() or SERVICE_UUID in uuids:
            found[device.address] = (name, adv.rssi)

    async with BleakScanner(_cb):
        await asyncio.sleep(timeout)
    return [(a, n, r) for a, (n, r) in found.items()]


#: The advertised name of a heater that answers the class-code protocol.
_ANSWERING_NAME_PREFIX = "HPWH1"

#: Printed when a scan finds no heater, or none that answers.
NOT_ADVERTISING_HINT = (
    "No heater advertising as HPWH1. With the heater off, hold Back + Power "
    "for 5 s to enter Bluetooth pairing mode. (HPWH4610 is the Wi-Fi setup "
    "mode, which answers nothing.)"
)

#: How long :meth:`NavienBleClient.read_status` waits for a block. The
#: first block has taken more than five seconds to arrive.
STATUS_TIMEOUT = 15.0


class TouWriteError(Nwp500Error):
    """The heater did not store a time-of-use plan as written."""


def answers_class_codes(name: str) -> bool:
    """Whether a heater advertising ``name`` answers the protocol."""
    return name.upper().startswith(_ANSWERING_NAME_PREFIX)


def best_heater(
    found: list[tuple[str, str, int]],
) -> tuple[str, str, int] | None:
    """The strongest of :func:`scan`'s heaters that answers, if any."""
    answering = [t for t in found if answers_class_codes(t[1])]
    return max(answering, key=lambda t: t[2]) if answering else None


class NavienBleClient:
    """Request/reply client for one connected heater.

    Example::

        async with NavienBleClient(address) as ble:
            info = await ble.read_device_info()
            plan = await ble.read_tou_records()

    Reads are safe. :meth:`read` returns the reply as received, with
    ``crc_ok`` set; the readers that decode a block
    (:meth:`read_device_info`, :meth:`read_controller_serials`,
    :meth:`read_sub_status`, :meth:`read_tou_records`,
    :meth:`read_parameter_blocks`) raise
    :class:`CrcMismatchError` instead of decoding bytes that failed their
    checksum.

    :meth:`read_status` starts the heater's live status stream. A read
    ends the stream, and the next :meth:`read_status` starts it again.

    :meth:`write_tou_records` stores a time-of-use plan of up to twelve
    intervals and checks it by reading it back.

    :meth:`write_block` sends a write and is marked experimental: the
    parameter block layouts are not yet mapped, so only write bytes you
    obtained from a read of the same class and changed deliberately.
    """

    def __init__(
        self,
        address: str | None = None,
        *,
        transport: BleTransport | None = None,
        reply_timeout: float = 5.0,
    ) -> None:
        if transport is None:
            if address is None:
                raise ValueError("address or transport is required")
            transport = BleakTransport(address)
        self._transport = transport
        self._reply_timeout = reply_timeout
        self._replies: asyncio.Queue[Packet] = asyncio.Queue()
        self._status_frames: asyncio.Queue[Packet] = asyncio.Queue()
        self._streaming = False
        self._lock = asyncio.Lock()
        self._unparsed: list[bytes] = []

    async def __aenter__(self) -> NavienBleClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        """Connect and subscribe to replies.

        If the subscription fails or is cancelled, the connection is
        closed again before the error propagates: ``__aexit__`` does not
        run when ``__aenter__`` raises, and an open GATT connection keeps
        other clients from connecting.
        """
        await self._transport.connect()
        try:
            await self._transport.start_notify(self._on_notify)
        except BaseException:
            try:
                await self._transport.disconnect()
            except Exception:
                _logger.debug(
                    "Disconnect after a failed subscribe failed", exc_info=True
                )
            raise

    async def disconnect(self) -> None:
        await self._transport.disconnect()
        # The heater ends the status stream when the connection closes.
        self._streaming = False

    @property
    def unparsed_notifications(self) -> list[bytes]:
        """Raw notifications that were not valid packets (for diagnosis)."""
        return list(self._unparsed)

    def _on_notify(self, data: bytes) -> None:
        try:
            packet = parse_packet(data)
        except ValueError:
            _logger.debug("Unparsed BLE notification: %s", data.hex())
            self._unparsed.append(data)
            return
        if not packet.crc_ok:
            _logger.warning(
                "BLE reply for class %s failed its CRC", packet.class_name
            )
        if (
            packet.class_code == ClassCode.RTMD
            and packet.command == Command.WRITE
        ):
            # Pushed status, not a reply to a request.
            self._status_frames.put_nowait(packet)
            return
        self._replies.put_nowait(packet)

    async def request(self, packet: bytes, class_code: int) -> Packet:
        """Send one packet and wait for the reply of the same class."""
        async with self._lock:
            while not self._replies.empty():
                self._replies.get_nowait()
            # The heater answers a request sent during the status stream
            # and stops pushing blocks (checked 2026-10-20), so the next
            # read_status() starts the stream again.
            self._streaming = False
            await self._transport.write(packet)
            deadline = asyncio.get_running_loop().time() + self._reply_timeout
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError(
                        f"no reply for class {class_code} within "
                        f"{self._reply_timeout}s"
                    )
                reply = await asyncio.wait_for(self._replies.get(), remaining)
                if reply.class_code == class_code and reply.is_reply:
                    return reply
                _logger.debug("Ignoring BLE packet %s", reply)

    async def read(
        self,
        class_code: int,
        expected_length: int | None = None,
        address: int = 0,
    ) -> Packet:
        """Read one data class.

        ``address`` selects within a class; only ``TOU_PLAN`` uses it on
        an NWP500 (see :meth:`read_tou_records`).
        """
        return await self._request_read(
            build_read(class_code, expected_length, address), class_code
        )

    async def _request_read(self, packet: bytes, class_code: int) -> Packet:
        """:meth:`request`, sent once more if no reply came.

        On an NWP500 the first request on a new connection has gone
        unanswered a few times in a dozen connections, and the same request
        sent again was answered. Only reads are retried; they change
        nothing.
        """
        try:
            return await self.request(packet, class_code)
        except TimeoutError:
            _logger.debug("No reply for class %s; retrying once", class_code)
            return await self.request(packet, class_code)

    async def _read_checked(
        self,
        class_code: int,
        expected_length: int | None = None,
        address: int = 0,
    ) -> bytes:
        """A block's bytes, refused if the reply failed its CRC."""
        packet = await self.read(class_code, expected_length, address)
        if not packet.crc_ok:
            raise CrcMismatchError(
                f"reply for class {packet.class_name} failed its CRC"
            )
        return packet.data

    async def read_device_info(self) -> DeviceInfoBlock:
        """Read and decode the device info block (``DID``).

        Raises:
            CrcMismatchError: The reply failed its checksum.
        """
        return DeviceInfoBlock.parse(await self._read_checked(ClassCode.DID))

    async def read_controller_serials(self) -> ControllerSerials:
        """Read and decode the controller serial numbers (``MSCD``).

        Raises:
            CrcMismatchError: The reply failed its checksum.
        """
        return ControllerSerials.parse(await self._read_checked(ClassCode.MSCD))

    async def read_software_info(self) -> SoftwareInfoBlock:
        """Read and decode the controller software block (``MSWD``).

        Raises:
            CrcMismatchError: The reply failed its checksum.
        """
        return SoftwareInfoBlock.parse(await self._read_checked(ClassCode.MSWD))

    async def read_sub_status(self) -> SubStatus:
        """Read and decode the ``SSD`` block: two DIP-switch settings.

        The layout is from Navien's boiler service toolkit and is
        unconfirmed on the NWP500; see :class:`SubStatus`.

        Raises:
            CrcMismatchError: The reply failed its checksum.
        """
        return SubStatus.parse(await self._read_checked(ClassCode.SSD))

    async def read_tou_records(self) -> list[TOUPeriod]:
        """Read the stored TOU plan: every interval, in slot order.

        Each interval decodes into :class:`~nwp500.models.TOUPeriod`, the
        model the MQTT client and REST API use, so the plan compares
        directly with the cloud's (e.g. with ``TOUPeriod.canonical()``).
        The controller's table has :data:`~nwp500.ble.protocol.TOU_PLAN_SLOTS`
        slots, read in three requests (see
        :func:`~nwp500.ble.protocol.build_tou_read`); empty slots are
        dropped.

        Raises:
            CrcMismatchError: A reply failed its checksum.
            ValueError: A reply did not hold the records asked for.
        """
        return parse_tou_records(await self._read_tou_slots())

    async def _read_tou_slots(self) -> bytes:
        """The whole ``TOU_PLAN`` table, empty slots included."""
        data = b""
        for first in range(0, TOU_PLAN_SLOTS, TOU_READ_MAX_RECORDS):
            last = min(first + TOU_READ_MAX_RECORDS, TOU_PLAN_SLOTS) - 1
            packet = await self._request_read(
                build_tou_read(first, last), ClassCode.TOU_PLAN
            )
            if not packet.crc_ok:
                raise CrcMismatchError(
                    "reply for class TOU_PLAN failed its CRC"
                )
            want = TOU_RECORD_SIZE * (last - first + 1)
            if len(packet.data) != want:
                raise ValueError(
                    f"TOU records {first}-{last}: expected {want} bytes, "
                    f"got {len(packet.data)}"
                )
            data += packet.data
        return data

    async def write_tou_records(self, periods: Sequence[TOUPeriod]) -> None:
        """Store a time-of-use plan of up to twelve intervals.

        The heater takes one write into slots 0 onward, of at most
        :data:`~nwp500.ble.protocol.TOU_WRITE_MAX_RECORDS` intervals (see
        :func:`~nwp500.ble.protocol.build_tou_write`), and leaves the slots
        after it as they were. Nothing written over Bluetooth empties a
        slot: a record of zeros makes the heater drop the whole write. So
        this reads the table first and refuses a plan shorter than the one
        stored, which would leave the old plan's last intervals running.
        After the write it reads the table back and checks that it holds
        exactly ``periods``.

        A longer plan, or a shorter one replacing it, needs the cloud:
        :meth:`nwp500.NavienMqttClient.configure_tou_schedule` replaces the
        whole plan. The heater does not report a Bluetooth write to the
        cloud, whose copy (:meth:`nwp500.NavienAPIClient.get_tou_info`)
        stays as it was. On the unit checked, a write into an empty table
        also turned TOU scheduling on (``tou_status``).

        Raises:
            ValueError: ``periods`` is empty, too long, or does not encode.
            TouWriteError: A longer plan is stored, the heater refused the
                write, or the table read back differs from ``periods``.
            TimeoutError: The heater did not answer. It drops a write it
                cannot take without answering or changing the table.
            CrcMismatchError: A reply failed its checksum.
        """
        packet = build_tou_write(periods)
        stored = await self._read_tou_slots()
        tail = stored[TOU_RECORD_SIZE * len(periods) :]
        if any(tail):
            raise TouWriteError(
                f"the heater holds a plan of more than {len(periods)} "
                "intervals, whose extra intervals a Bluetooth write would "
                "leave in place; use the cloud to replace it"
            )
        reply = await self.request(packet, ClassCode.TOU_PLAN)
        if reply.command != Command.WRITE_RESPONSE or reply.data != bytes(
            [TOU_WRITE_ACCEPTED]
        ):
            raise TouWriteError(
                f"the heater refused the TOU write (reply {reply.data.hex()})"
            )
        stored_after = parse_tou_records(await self._read_tou_slots())
        if [p.canonical_key() for p in stored_after] != [
            p.canonical_key() for p in periods
        ]:
            raise TouWriteError("the TOU plan read back differs from the write")

    async def read_parameter_blocks(self) -> dict[ClassCode, bytes]:
        """Read the four boiler parameter blocks (classes 51-54).

        These are the blocks Navien's service app reads on boilers. An
        NWP500 did not answer them (see
        :data:`~nwp500.ble.NWP500_RESPONDING_CLASSES`), so on the heat
        pump expect a :class:`TimeoutError`; the classes it does answer
        can be read with :meth:`read`.

        Raises:
            CrcMismatchError: A reply failed its checksum.
        """
        out: dict[ClassCode, bytes] = {}
        for cc in (
            ClassCode.SPID,
            ClassCode.SPLD,
            ClassCode.SPHD,
            ClassCode.SPD,
        ):
            out[cc] = await self._read_checked(cc, DEFAULT_READ_LENGTHS[cc])
        return out

    async def read_status(
        self, timeout: float = STATUS_TIMEOUT
    ) -> RealTimeStatus:
        """The next live status block (``RTMD``) the heater pushes.

        The first call starts the stream with the
        :data:`~nwp500.ble.protocol.START_STATUS_STREAM` session command
        and drops the first block that follows: on an NWP500 that block
        held values from earlier, with temperatures 3 degC away from the
        blocks after it and from the MQTT report. The heater then pushes a
        block about every 300 ms, and later calls return the newest one
        that has arrived, or wait for the next. A read or write ends the
        stream: the heater answers it and pushes no more blocks. The next
        call then starts the stream again, dropping its first block once
        more.

        Args:
            timeout: Seconds to wait for each block. Longer than the reply
                timeout, since the first block can take several seconds.

        Raises:
            CrcMismatchError: The block failed its checksum.
            TimeoutError: No block arrived within ``timeout``.
        """
        async with self._lock:
            if not self._streaming:
                while not self._status_frames.empty():
                    self._status_frames.get_nowait()
                await self._transport.write(
                    build_session_command(START_STATUS_STREAM)
                )
                await self._next_status_frame(timeout)
                self._streaming = True
            packet: Packet | None = None
            while not self._status_frames.empty():
                packet = self._status_frames.get_nowait()
            if packet is None:
                packet = await self._next_status_frame(timeout)
        if not packet.crc_ok:
            raise CrcMismatchError("RTMD block failed its CRC")
        return RealTimeStatus.parse(packet.data)

    async def _next_status_frame(self, timeout: float) -> Packet:
        try:
            return await asyncio.wait_for(self._status_frames.get(), timeout)
        except TimeoutError:
            raise TimeoutError(f"no status block within {timeout}s") from None

    async def write_block(
        self, class_code: int, data: bytes, address: int = 0
    ) -> Packet:
        """EXPERIMENTAL: write a whole block and return the device's reply.

        The service app writes installer parameters as a full class-54
        block. Only send bytes read from the same class with a deliberate
        change; an unknown layout written blindly can misconfigure the
        heater.
        """
        _logger.warning(
            "Writing %d bytes to BLE class %s (experimental)",
            len(data),
            class_code,
        )
        return await self.request(
            build_packet(Command.WRITE, class_code, data, address), class_code
        )


__all__ = [
    "NOT_ADVERTISING_HINT",
    "STATUS_TIMEOUT",
    "BleTransport",
    "BleakTransport",
    "NavienBleClient",
    "TouWriteError",
    "answers_class_codes",
    "best_heater",
    "scan",
]
