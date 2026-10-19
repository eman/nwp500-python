"""Bluetooth LE access to the NWP500's controller (installer-side data).

The heater must be in Bluetooth pairing mode (hold Back and Power for five
seconds). Install the ``ble`` extra for the transport::

    pip install 'nwp500-python[ble]'
    python -m nwp500.ble scan
    python -m nwp500.ble read
"""

from .client import BleakTransport, BleTransport, NavienBleClient, scan
from .protocol import (
    ADVERTISED_NAME_FRAGMENT,
    DEFAULT_READ_LENGTHS,
    NOTIFY_CHAR_UUID,
    NWP500_RESPONDING_CLASSES,
    NWP500_WRITABLE_CLASSES,
    SERVICE_UUID,
    WRITE_CHAR_UUID,
    ClassCode,
    Command,
    ControllerSerials,
    CrcMismatchError,
    DeviceInfo,
    Packet,
    TouRecord,
    build_packet,
    build_read,
    crc16,
    parse_packet,
    parse_tou_records,
)

__all__ = [
    "ADVERTISED_NAME_FRAGMENT",
    "DEFAULT_READ_LENGTHS",
    "NOTIFY_CHAR_UUID",
    "NWP500_RESPONDING_CLASSES",
    "NWP500_WRITABLE_CLASSES",
    "SERVICE_UUID",
    "WRITE_CHAR_UUID",
    "BleTransport",
    "BleakTransport",
    "ClassCode",
    "Command",
    "ControllerSerials",
    "CrcMismatchError",
    "DeviceInfo",
    "NavienBleClient",
    "Packet",
    "TouRecord",
    "build_packet",
    "build_read",
    "crc16",
    "parse_packet",
    "parse_tou_records",
    "scan",
]
