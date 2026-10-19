"""Data models for Navien NWP500 water heater communication.

This module defines data classes for representing data structures
used in the Navien NWP500 water heater communication protocol.

These models are based on the MQTT message formats and API responses.
"""

from .._base import NavienBaseModel
from ._converters import (
    fahrenheit_to_half_celsius,
    preferred_to_half_celsius,
    reservation_param_to_preferred,
)
from .account import AppVersionInfo, UserProfile
from .device import (
    ConnectionStatusField,
    DescalingInfo,
    Device,
    DeviceErrorHistoryEntry,
    DeviceErrorSummary,
    DeviceInfo,
    DeviceInstaller,
    DisplayPreferences,
    FirmwareDetail,
    FirmwareDeviceGroup,
    FirmwareInfo,
    Location,
    PushFlag,
    PushSettings,
    SimpleDevice,
)
from .diagnostics import (
    DeviceDiagnostics,
    DiagnosticsComponentCounters,
    DiagnosticsDhwUsage,
    DiagnosticsEventCounters,
)
from .energy import (
    EnergyUsageBase,
    EnergyUsageDay,
    EnergyUsageResponse,
    EnergyUsageTotal,
    MonthlyEnergyData,
)
from .feature import CapabilityFlag, DeviceFeature, VolumeCodeField
from .firmware import FirmwareDownloadEntry, FirmwareDownloadInfo
from .maintenance import MaintenanceHistoryEntry, format_maintenance_date
from .mqtt_models import (
    APP_CONNECTION_OS,
    AppConnectionEvent,
    AppConnectionInfo,
    AppConnectionStatus,
    ControlFailCode,
    ControlFailDetail,
    ControlFailResponse,
    MqttCommand,
    MqttRequest,
)
from .schedule import (
    OtaCommitPayload,
    RecirculationSchedule,
    RecirculationScheduleEntry,
    ReservationEntry,
    ReservationSchedule,
)
from .status import (
    DeviceBool,
    DeviceStatus,
    Div10,
    EnergyCountToWh,
    TouOverride,
    TouStatus,
)
from .tou import (
    ConvertedTOUPlan,
    TOUInfo,
    TOUPeriod,
    TOUReservationSchedule,
    TOUSchedule,
)

__all__ = [
    "NavienBaseModel",
    "DeviceBool",
    "CapabilityFlag",
    "Div10",
    "EnergyCountToWh",
    "TouStatus",
    "TouOverride",
    "VolumeCodeField",
    "ConnectionStatusField",
    "fahrenheit_to_half_celsius",
    "preferred_to_half_celsius",
    "reservation_param_to_preferred",
    "DeviceInfo",
    "Location",
    "Device",
    "DeviceErrorSummary",
    "DescalingInfo",
    "DeviceInstaller",
    "PushFlag",
    "PushSettings",
    "FirmwareInfo",
    "FirmwareDeviceGroup",
    "FirmwareDetail",
    "DisplayPreferences",
    "SimpleDevice",
    "DeviceErrorHistoryEntry",
    "MaintenanceHistoryEntry",
    "format_maintenance_date",
    "UserProfile",
    "AppVersionInfo",
    "TOUSchedule",
    "ConvertedTOUPlan",
    "TOUInfo",
    "TOUPeriod",
    "TOUReservationSchedule",
    "ReservationEntry",
    "ReservationSchedule",
    "RecirculationScheduleEntry",
    "RecirculationSchedule",
    "OtaCommitPayload",
    "DeviceDiagnostics",
    "DiagnosticsComponentCounters",
    "DiagnosticsDhwUsage",
    "DiagnosticsEventCounters",
    "FirmwareDownloadEntry",
    "FirmwareDownloadInfo",
    "DeviceStatus",
    "DeviceFeature",
    "MqttRequest",
    "MqttCommand",
    "ControlFailCode",
    "ControlFailDetail",
    "ControlFailResponse",
    "AppConnectionEvent",
    "AppConnectionInfo",
    "AppConnectionStatus",
    "APP_CONNECTION_OS",
    "EnergyUsageBase",
    "EnergyUsageTotal",
    "EnergyUsageDay",
    "MonthlyEnergyData",
    "EnergyUsageResponse",
]
