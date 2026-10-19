"""Bluetooth LE client for the NWP500's class-code service.

Requires the ``ble`` extra (``pip install nwp500-python[ble]``), which
pulls in `bleak <https://github.com/hbldh/bleak>`_. The transport is
injectable so the client is testable without hardware.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, Protocol

from ..models.tou import TOUPeriod
from .protocol import (
    ADVERTISED_NAME_FRAGMENT,
    DEFAULT_READ_LENGTHS,
    NOTIFY_CHAR_UUID,
    SERVICE_UUID,
    WRITE_CHAR_UUID,
    ClassCode,
    Command,
    ControllerSerials,
    CrcMismatchError,
    DeviceInfoBlock,
    Packet,
    SoftwareInfoBlock,
    SubStatus,
    build_packet,
    build_read,
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

    A heater advertises only while in Bluetooth pairing mode.

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
        self._replies.put_nowait(packet)

    async def request(self, packet: bytes, class_code: int) -> Packet:
        """Send one packet and wait for the reply of the same class."""
        async with self._lock:
            while not self._replies.empty():
                self._replies.get_nowait()
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
        return await self.request(
            build_read(class_code, expected_length, address), class_code
        )

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

    async def read_tou_records(self, address: int = 0) -> list[TOUPeriod]:
        """Read the stored TOU plan from record ``address`` on.

        Each interval decodes into :class:`~nwp500.models.TOUPeriod`, the
        model the MQTT client and REST API use, so the plan compares
        directly with the cloud's (e.g. with ``TOUPeriod.canonical()``).

        The address is a record index, and one reply runs from it to the
        end of a page, empty slots dropped. On an NWP500 the first page is
        records 0-11, so the default read returns up to the first twelve
        intervals, which is the whole plan when it has no more. The next
        page ends at record 27, and its first records did not come back:
        starting at 12 returned an empty reply, and 13 and 14 none. Reads
        from 15 onward return the rest. A plan of more than twelve
        intervals therefore cannot yet be read whole over Bluetooth;
        :meth:`nwp500.NavienAPIClient.get_tou_info` returns all of it.

        Raises:
            CrcMismatchError: The reply failed its checksum.
            ValueError: The reply is not a whole number of records.
        """
        return parse_tou_records(
            await self._read_checked(ClassCode.TOU_PLAN, None, address)
        )

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


__all__ = ["BleTransport", "BleakTransport", "NavienBleClient", "scan"]
