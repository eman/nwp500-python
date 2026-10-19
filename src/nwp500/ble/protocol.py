"""Framing for the NWP500's Bluetooth LE service.

The water heater exposes a GATT service that carries the controller's
native class-code protocol: one request packet is written to the write
characteristic and one reply packet arrives as a notification. The framing
below mirrors what the NaviLink app sends to the heater when it is in
Bluetooth pairing mode (hold Back and Power for five seconds; the heater
then advertises a name containing ``HPWH1``).

Packet layout (all single bytes unless noted)::

    header   0xF7
    system   0x20
    source   0x01   (the app)
    dest     0x03   (the controller)
    command  3 = read, 16 = write; replies are 131 and 144
    length   payload length + 2 (+5 for the firmware classes 210/211,
             whose address is four bytes little-endian)
    class    see :class:`ClassCode`
    address  one byte (four for classes 210/211)
    payload
    crc      CRC-16/MODBUS over everything before it, low byte first

A read request's payload is a single byte: the number of data bytes the
caller expects back.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ..models.tou import TOUPeriod
from ..temperature import HalfCelsius
from ..unit_system import get_unit_system

SERVICE_UUID = "237339a3-b40d-4283-a629-f89bb838d85a"
WRITE_CHAR_UUID = "237339a3-b40d-4283-a629-f89bb838d85c"
NOTIFY_CHAR_UUID = "237339a3-b40d-4283-a629-f89bb838d85b"
ADVERTISED_NAME_FRAGMENT = "HPWH1"
MTU = 247

HEADER = 0xF7
SYSTEM_ID = 0x20
SOURCE_ID = 0x01
DESTINATION_ID = 0x03

_WIDE_ADDRESS_CLASSES = frozenset({210, 211})


class Command(IntEnum):
    """Packet command byte."""

    READ = 3
    READ_RESPONSE = 131
    WRITE = 16
    WRITE_RESPONSE = 144


class ClassCode(IntEnum):
    """Data classes the controller serves over Bluetooth.

    Names are the app's abbreviations. The parameter blocks 51-54 are what
    the Navien service app reads before showing installer parameters and
    writes back (class 54) after a change.
    """

    SSD = 17  # status data
    EHD = 32  # error history
    TSD = 38  # diagnostics: status counters
    TCD = 39  # diagnostics: component counters
    TDD = 40  # diagnostics: DHW usage
    TAD = 41  # diagnostics: accumulated
    RTMD = 48  # real-time monitoring
    SAPID = 49  # Wi-Fi access point id
    SAPCD = 50  # Wi-Fi access point credential
    SPID = 51  # parameter block: id (8 bytes)
    SPLD = 52  # parameter block: low grade (59 bytes)
    SPHD = 53  # parameter block: high grade (59 bytes)
    SPD = 54  # parameter block: settings (59 bytes); written as a whole
    SDOD = 164
    TOU_PLAN = 170  # time-of-use plan (written by NaviLink)
    SFHD = 210  # firmware: header
    SFBD = 211  # firmware: block
    SFDD = 212  # firmware: done
    DID = 240  # device info (58 bytes)
    MSCD = 243  # controller serial numbers (40 bytes)
    MSWD = 244


#: Expected reply length sent with each read request. The first six are
#: what the apps send; the rest were confirmed to answer on an NWP500
#: (the device returns its real block size regardless, e.g. 192 bytes for
#: ``TOU_PLAN``).
DEFAULT_READ_LENGTHS: dict[int, int] = {
    ClassCode.DID: 58,
    ClassCode.MSCD: 40,
    ClassCode.SPID: 8,
    ClassCode.SPLD: 59,
    ClassCode.SPHD: 59,
    ClassCode.SPD: 59,
    ClassCode.SSD: 59,
    ClassCode.EHD: 59,
    ClassCode.TSD: 59,
    ClassCode.TCD: 59,
    ClassCode.TDD: 59,
    ClassCode.TAD: 59,
    ClassCode.TOU_PLAN: 59,
    ClassCode.SFHD: 59,
    ClassCode.MSWD: 59,
}

#: Classes an NWP500 answered over Bluetooth (checked 2026-10-16). The
#: parameter classes 51-54 did not answer with any length or address, so
#: the heat pump keeps its installer parameters elsewhere.
NWP500_RESPONDING_CLASSES: frozenset[int] = frozenset(
    {17, 32, 38, 39, 40, 41, 170, 210, 240, 243, 244}
)

#: Of the classes an NWP500 answers, which accept a write (command 16).
#: Checked 2026-10-16 by writing each block's own bytes back and reading the
#: reply code: every readable class echoes a *read* response, so none is
#: writable over this interface. The boiler parameter classes 51-54 do not
#: respond to reads or writes at all on this controller. The writable
#: parameter class is selected from the per-model table the service app
#: downloads from Navien's server; it is not one of the classes below and
#: cannot be found by safe probing.
NWP500_WRITABLE_CLASSES: frozenset[int] = frozenset()


class CrcMismatchError(ValueError):
    """A reply's checksum did not match, so its bytes cannot be trusted."""


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS: reflected polynomial 0xA001, initial value 0xFFFF.

    Identical to the table-driven ``CRC16Checker`` in the NaviLink app.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_packet(
    command: int, class_code: int, payload: bytes = b"", address: int = 0
) -> bytes:
    """Frame one request.

    Args:
        command: :attr:`Command.READ` or :attr:`Command.WRITE`.
        class_code: Data class (:class:`ClassCode` or raw int).
        payload: Request data. For a read, one byte: the expected length.
        address: Block address; 0 for every class the apps use except the
            firmware classes, which take a byte offset.
    """
    wide = class_code in _WIDE_ADDRESS_CLASSES
    length = len(payload) + (5 if wide else 2)
    if length > 0xFF:
        raise ValueError("payload too long for one packet")
    body = bytes(
        [
            HEADER,
            SYSTEM_ID,
            SOURCE_ID,
            DESTINATION_ID,
            command,
            length,
            class_code,
        ]
    )
    if wide:
        body += address.to_bytes(4, "little")
    else:
        if not 0 <= address <= 0xFF:
            raise ValueError("address must fit in one byte for this class")
        body += bytes([address])
    body += payload
    crc = crc16(body)
    return body + bytes([crc & 0xFF, crc >> 8])


def build_read(
    class_code: int, expected_length: int | None = None, address: int = 0
) -> bytes:
    """Frame a read request for ``class_code`` at ``address``.

    ``expected_length`` defaults to the length the apps use for that class
    (:data:`DEFAULT_READ_LENGTHS`) and must be given for other classes.
    """
    if expected_length is None:
        try:
            expected_length = DEFAULT_READ_LENGTHS[class_code]
        except KeyError:
            raise ValueError(
                f"no default read length for class {class_code}; pass one"
            ) from None
    return build_packet(
        Command.READ, class_code, bytes([expected_length]), address
    )


@dataclass(frozen=True)
class Packet:
    """A decoded packet."""

    command: int
    class_code: int
    address: int
    data: bytes
    crc_ok: bool
    raw: bytes

    @property
    def class_name(self) -> str:
        try:
            return ClassCode(self.class_code).name
        except ValueError:
            return str(self.class_code)

    @property
    def is_reply(self) -> bool:
        return self.command in (Command.READ_RESPONSE, Command.WRITE_RESPONSE)


def parse_packet(raw: bytes) -> Packet:
    """Decode a packet; ``crc_ok`` says whether its checksum matched.

    Raises:
        ValueError: If the bytes are too short or the header is wrong.
    """
    if len(raw) < 10 or raw[0] != HEADER:
        raise ValueError("not a controller packet")
    class_code = raw[6]
    wide = class_code in _WIDE_ADDRESS_CLASSES
    header_len = 11 if wide else 8
    data_len = raw[5] - (5 if wide else 2)
    if data_len < 0 or len(raw) < header_len + data_len + 2:
        raise ValueError("packet shorter than its declared length")
    address = int.from_bytes(raw[7:11], "little") if wide else raw[7]
    data = bytes(raw[header_len : header_len + data_len])
    end = header_len + data_len
    crc_ok = crc16(raw[:end]) == (raw[end] | (raw[end + 1] << 8))
    return Packet(raw[4], class_code, address, data, crc_ok, bytes(raw))


def _u8(data: bytes, i: int) -> int:
    return data[i]


def prefers_celsius() -> bool:
    """Whether converted temperatures are in Celsius.

    The unit-system preference decides, as for the cloud models. These
    blocks do not carry the heater's own display unit (the cloud's
    ``temperatureType``), so without a preference it is Fahrenheit, the
    cloud models' default.
    """
    return get_unit_system() == "metric"


def temperature_unit() -> str:
    return " °C" if prefers_celsius() else " °F"


@dataclass(frozen=True)
class DeviceInfoBlock:
    """The 58-byte ``DID`` block.

    Fields checked against the same heater's MQTT device-info report
    (:class:`~nwp500.models.DeviceFeature`) carry that model's names and
    raw encodings: ``dhw_temperature_max_raw`` and
    ``dhw_temperature_min_raw`` (bytes 16 and 17, half-degrees Celsius),
    ``model_type_code`` (byte 21) and ``country_code`` (byte 24). The
    others keep the names of the NaviLink app's ``DeviceInfo`` class, which
    was written for boilers. Unlisted bytes are kept in ``raw``. Not to be
    confused with :class:`nwp500.models.DeviceInfo`, the cloud's device
    record.
    """

    version: int
    version_sub: int
    characteristic: int
    characteristic_sub: int
    display_and_data_type: int
    heating_control_type: int
    hot_water_control_type: int
    special: int
    dhw_temperature_max_raw: int
    dhw_temperature_min_raw: int
    hot_water_temp_step_max: int
    hot_water_temp_step_min: int
    model_type_code: int
    model_characteristic: int
    model_capacity: int
    country_code: int
    manufacturing_year: int
    manufacturing_month: int
    manufacturing_day: int
    toolkit_version: int
    toolkit_version_sub: int
    raw: bytes

    LENGTH = 58

    @property
    def min_operation_temperature_raw(self) -> int:
        """Minimum heat-pump operation temperature, half-degrees Celsius.

        DID byte 17, the lower end of the setpoint range. Verified on an
        NWP500 to equal the device's ``heatMinOpTemperature`` as reported
        over MQTT (both 81 = 40.5 C = 104.9 F on 2026-10-16). The installer
        range is 95-113 F (35-45 C). This block is read-only over
        Bluetooth; writing it back is echoed as a read, so this field can
        be read here but not set here.
        """
        return self.dhw_temperature_min_raw

    @property
    def dhw_temperature_min(self) -> float:
        """As ``DeviceFeature.dhw_temperature_min``: in the preferred unit."""
        return HalfCelsius(self.dhw_temperature_min_raw).to_preferred(
            prefers_celsius()
        )

    @property
    def dhw_temperature_max(self) -> float:
        """As ``DeviceFeature.dhw_temperature_max``: in the preferred unit."""
        return HalfCelsius(self.dhw_temperature_max_raw).to_preferred(
            prefers_celsius()
        )

    def min_operation_temperature(self, celsius: bool | None = None) -> float:
        """Minimum operation temperature, converted as the cloud models do.

        ``celsius`` picks the unit; left out, the unit-system preference
        (:func:`nwp500.set_unit_system`) decides, and Fahrenheit without
        one. Equal to ``DeviceFeature.dhw_temperature_min`` for the same
        heater.
        """
        is_celsius = prefers_celsius() if celsius is None else celsius
        return HalfCelsius(self.min_operation_temperature_raw).to_preferred(
            is_celsius
        )

    @classmethod
    def parse(cls, data: bytes) -> DeviceInfoBlock:
        if len(data) != cls.LENGTH:
            raise ValueError(
                f"DID block must be {cls.LENGTH} bytes, got {len(data)}"
            )
        return cls(
            version=_u8(data, 1),
            version_sub=_u8(data, 0),
            characteristic=_u8(data, 2),
            characteristic_sub=_u8(data, 3),
            display_and_data_type=_u8(data, 4),
            heating_control_type=_u8(data, 5),
            hot_water_control_type=_u8(data, 6),
            special=_u8(data, 7),
            dhw_temperature_max_raw=_u8(data, 16),
            dhw_temperature_min_raw=_u8(data, 17),
            hot_water_temp_step_max=_u8(data, 18),
            hot_water_temp_step_min=_u8(data, 19),
            model_type_code=_u8(data, 21),
            model_characteristic=_u8(data, 22),
            model_capacity=_u8(data, 23),
            country_code=_u8(data, 24),
            manufacturing_year=_u8(data, 26),
            manufacturing_month=_u8(data, 27),
            manufacturing_day=_u8(data, 28),
            toolkit_version=_u8(data, 45),
            toolkit_version_sub=_u8(data, 44),
            raw=bytes(data),
        )


@dataclass(frozen=True)
class ControllerSerials:
    """The 40-byte ``MSCD`` block: two NUL-padded ASCII serial numbers.

    The first is the cloud's ``controllerSerialNumber``
    (``DeviceFeature.controller_serial_number``), checked on an NWP500;
    there the second, ``pcb_serial``, held the same number.
    """

    controller_serial_number: str
    pcb_serial: str
    raw: bytes

    LENGTH = 40

    @classmethod
    def parse(cls, data: bytes) -> ControllerSerials:
        if len(data) != cls.LENGTH:
            raise ValueError(
                f"MSCD block must be {cls.LENGTH} bytes, got {len(data)}"
            )

        def text(chunk: bytes) -> str:
            return bytes(b for b in chunk if b).decode("ascii", "replace")

        return cls(text(data[0:18]), text(data[20:38]), bytes(data))


@dataclass(frozen=True)
class SoftwareInfoBlock:
    """The ``MSWD`` block (class 244): controller software identity.

    ``controller_sw_code`` is bytes 0-3, little-endian, under the
    ``DeviceFeature`` name: on an NWP500 it equalled the MQTT report's
    ``controllerSwCode`` (``0x02000711``; 2026-10-19). Bytes 4-5 held
    ``0b 05``, which matches ``controllerSwVersion`` (``0x0B050000``) only
    read big-endian, so with one sample that field is not decoded. The
    whole block is kept in ``raw``.
    """

    controller_sw_code: int
    raw: bytes

    MIN_LENGTH = 4

    @classmethod
    def parse(cls, data: bytes) -> SoftwareInfoBlock:
        if len(data) < cls.MIN_LENGTH:
            raise ValueError(
                f"MSWD block must be at least {cls.MIN_LENGTH} bytes, "
                f"got {len(data)}"
            )
        return cls(
            controller_sw_code=int.from_bytes(data[0:4], "little"),
            raw=bytes(data),
        )


@dataclass(frozen=True)
class SubStatus:
    """The ``SSD`` block (class 17): two DIP-switch settings.

    This is not live status; an NWP500 reports that over MQTT only. The
    layout comes from Navien's UK service toolkit, which names the block
    "DeviceSubStatusInfo" and reads two little-endian 16-bit words from
    it, labelled DIP switch 1 (bytes 16-17) and DIP switch 2 (bytes
    18-19). That toolkit was written for boilers and expects a 60-byte
    block, while an NWP500 sends 59, so on the heat pump the layout is
    unconfirmed and what each bit means is not known. On the unit
    checked (2026-10-16) the words were 0x0004 and 0x0000; every other
    byte was zero. The NWP500 does have DIP switches (error E593,
    "Abnormal DIP switch settings"). The whole block is kept in ``raw``.
    """

    dip_switch_1: int
    dip_switch_2: int
    raw: bytes

    MIN_LENGTH = 20

    @classmethod
    def parse(cls, data: bytes) -> SubStatus:
        if len(data) < cls.MIN_LENGTH:
            raise ValueError(
                f"SSD block must be at least {cls.MIN_LENGTH} bytes, "
                f"got {len(data)}"
            )
        return cls(
            dip_switch_1=int.from_bytes(data[16:18], "little"),
            dip_switch_2=int.from_bytes(data[18:20], "little"),
            raw=bytes(data),
        )


#: Bytes per interval in the ``TOU_PLAN`` block.
TOU_RECORD_SIZE = 16


def parse_tou_record(data: bytes) -> TOUPeriod:
    """Decode one 16-byte ``TOU_PLAN`` interval into a :class:`TOUPeriod`.

    The interval has the fields of a cloud TOU period, so it decodes into
    the model the MQTT client and REST API use: ``season`` has bit N-1 set
    for month N, ``week`` has Sunday in bit 7 down to Saturday in bit 1,
    and prices are integers scaled by ``10 ** decimal_point``. Layout,
    with multi-byte fields little-endian::

        0-1    season
        2      week
        3-4    start hour, start minute
        5-6    end hour, end minute
        7      decimal point
        8-11   price max
        12-15  price min

    This is the layout the NaviLink app writes. Checked on an NWP500
    (2026-10-16): the twelve intervals read at address 0 equal the first
    twelve of the plan the cloud holds for that heater, field for field.
    Price max and min were equal in every interval checked, so their order
    is taken from the app.

    Raises:
        ValueError: If ``data`` is not 16 bytes.
    """
    if len(data) != TOU_RECORD_SIZE:
        raise ValueError(
            f"TOU record must be {TOU_RECORD_SIZE} bytes, got {len(data)}"
        )
    return TOUPeriod.model_validate(
        {
            "season": int.from_bytes(data[0:2], "little"),
            "week": data[2],
            "startHour": data[3],
            "startMinute": data[4],
            "endHour": data[5],
            "endMinute": data[6],
            "decimalPoint": data[7],
            "priceMax": int.from_bytes(data[8:12], "little"),
            "priceMin": int.from_bytes(data[12:16], "little"),
        }
    )


def parse_tou_records(data: bytes) -> list[TOUPeriod]:
    """Split a ``TOU_PLAN`` reply into :class:`TOUPeriod` intervals.

    Empty slots are dropped: an empty slot is sixteen zero bytes, which
    the controller pads its pages with after the last interval.

    Raises:
        ValueError: If ``data`` is not a whole number of records.
    """
    size = TOU_RECORD_SIZE
    if len(data) % size:
        raise ValueError(
            f"TOU_PLAN data must be a multiple of {size} bytes, got {len(data)}"
        )
    return [
        parse_tou_record(data[o : o + size])
        for o in range(0, len(data), size)
        if any(data[o : o + size])
    ]


__all__ = [
    "SERVICE_UUID",
    "WRITE_CHAR_UUID",
    "NOTIFY_CHAR_UUID",
    "ADVERTISED_NAME_FRAGMENT",
    "MTU",
    "Command",
    "ClassCode",
    "DEFAULT_READ_LENGTHS",
    "TOU_RECORD_SIZE",
    "crc16",
    "build_packet",
    "build_read",
    "Packet",
    "parse_packet",
    "DeviceInfoBlock",
    "ControllerSerials",
    "SoftwareInfoBlock",
    "SubStatus",
    "parse_tou_record",
    "parse_tou_records",
]
