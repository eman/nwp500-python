"""Bluetooth LE access to the NWP500's controller (installer-side data).

The heater must be in Bluetooth pairing mode (hold Back and Power for five
seconds). Install the ``ble`` extra for the transport::

    pip install 'nwp500-python[ble]'
    python -m nwp500.ble scan
    python -m nwp500.ble read
"""

from .client import BleakTransport, BleTransport, NavienBleClient, scan
from .mqtt_adapter import (
    BleDeviceFeature,
    BleMqttAdapter,
    BleUnsupportedError,
    device_feature_from_blocks,
)
from .protocol import (
    ADVERTISED_NAME_FRAGMENT,
    DEFAULT_READ_LENGTHS,
    NOTIFY_CHAR_UUID,
    NWP500_RESPONDING_CLASSES,
    NWP500_WRITABLE_CLASSES,
    SERVICE_UUID,
    TOU_RECORD_SIZE,
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
    crc16,
    parse_packet,
    parse_tou_record,
    parse_tou_records,
)

__all__ = [
    "ADVERTISED_NAME_FRAGMENT",
    "DEFAULT_READ_LENGTHS",
    "NOTIFY_CHAR_UUID",
    "NWP500_RESPONDING_CLASSES",
    "NWP500_WRITABLE_CLASSES",
    "SERVICE_UUID",
    "TOU_RECORD_SIZE",
    "WRITE_CHAR_UUID",
    "BleDeviceFeature",
    "BleMqttAdapter",
    "BleTransport",
    "BleUnsupportedError",
    "BleakTransport",
    "ClassCode",
    "Command",
    "ControllerSerials",
    "CrcMismatchError",
    "DeviceInfoBlock",
    "NavienBleClient",
    "Packet",
    "SoftwareInfoBlock",
    "SubStatus",
    "build_packet",
    "build_read",
    "crc16",
    "device_feature_from_blocks",
    "parse_packet",
    "parse_tou_record",
    "parse_tou_records",
    "scan",
]
