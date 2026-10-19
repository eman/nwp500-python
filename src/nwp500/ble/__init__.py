"""Bluetooth LE access to the NWP500's controller (installer-side data).

The heater must be advertising as ``HPWH1…``; in its Wi-Fi setup mode it
advertises as ``HPWH4610`` and answers nothing. Install the ``ble`` extra
for the transport::

    pip install 'nwp500-python[ble]'
    python -m nwp500.ble scan
    python -m nwp500.ble read
"""

from .client import (
    NOT_ADVERTISING_HINT,
    BleakTransport,
    BleTransport,
    NavienBleClient,
    answers_class_codes,
    best_heater,
    scan,
)
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
    START_STATUS_STREAM,
    TOU_RECORD_SIZE,
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
    crc16,
    parse_packet,
    parse_tou_record,
    parse_tou_records,
)

__all__ = [
    "ADVERTISED_NAME_FRAGMENT",
    "DEFAULT_READ_LENGTHS",
    "NOTIFY_CHAR_UUID",
    "NOT_ADVERTISING_HINT",
    "NWP500_RESPONDING_CLASSES",
    "NWP500_WRITABLE_CLASSES",
    "SERVICE_UUID",
    "START_STATUS_STREAM",
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
    "RealTimeStatus",
    "SoftwareInfoBlock",
    "SubStatus",
    "answers_class_codes",
    "best_heater",
    "build_packet",
    "build_read",
    "build_session_command",
    "crc16",
    "device_feature_from_blocks",
    "parse_packet",
    "parse_tou_record",
    "parse_tou_records",
    "scan",
]
