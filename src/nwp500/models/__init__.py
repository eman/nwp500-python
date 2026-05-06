"""Data models for Navien NWP500 water heater communication.

This module defines data classes for representing data structures
used in the Navien NWP500 water heater communication protocol.

These models are based on the MQTT message formats and API responses.
"""

from __future__ import annotations

from .._base import NavienBaseModel
from ._converters import (
    fahrenheit_to_half_celsius,
    preferred_to_half_celsius,
    reservation_param_to_preferred,
)
from .device import (
    ConnectionStatusField,
    Device,
    DeviceInfo,
    FirmwareInfo,
    Location,
)
from .energy import (
    EnergyUsageBase,
    EnergyUsageDay,
    EnergyUsageResponse,
    EnergyUsageTotal,
    MonthlyEnergyData,
)
from .feature import CapabilityFlag, DeviceFeature, VolumeCodeField
from .mqtt_models import MqttCommand, MqttRequest
from .schedule import (
    OtaCommitPayload,
    RecirculationSchedule,
    RecirculationScheduleEntry,
    ReservationEntry,
    ReservationSchedule,
    WeeklyReservationEntry,
    WeeklyReservationSchedule,
)
from .status import (
    DeviceBool,
    DeviceStatus,
    Div10,
    TenWhToWh,
    TouOverride,
    TouStatus,
)
from .tou import ConvertedTOUPlan, TOUInfo, TOUSchedule

__all__ = [
    "NavienBaseModel",
    "DeviceBool",
    "CapabilityFlag",
    "Div10",
    "TenWhToWh",
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
    "FirmwareInfo",
    "TOUSchedule",
    "ConvertedTOUPlan",
    "TOUInfo",
    "ReservationEntry",
    "ReservationSchedule",
    "WeeklyReservationEntry",
    "WeeklyReservationSchedule",
    "RecirculationScheduleEntry",
    "RecirculationSchedule",
    "OtaCommitPayload",
    "DeviceStatus",
    "DeviceFeature",
    "MqttRequest",
    "MqttCommand",
    "EnergyUsageBase",
    "EnergyUsageTotal",
    "EnergyUsageDay",
    "MonthlyEnergyData",
    "EnergyUsageResponse",
]
