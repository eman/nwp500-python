"""Navien NWP500 water heater control library.

This package provides Python bindings for Navien Smart Control API and MQTT
communication for NWP500 heat pump water heaters.
"""

from collections.abc import Mapping
from importlib import import_module
from importlib.metadata import (
    PackageNotFoundError,
    version,
)  # pragma: no cover
from importlib.util import find_spec
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

try:
    # Change here if project is renamed and does not equal the package name
    dist_name = "nwp500-python"
    __version__ = version(dist_name)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"
finally:
    del version, PackageNotFoundError

# The exports load on first use (PEP 562), so a part of the library
# imports without the others' dependencies: ``nwp500.sim`` needs neither
# aiohttp nor awsiotsdk, which the clients load.
if TYPE_CHECKING:
    from nwp500.api_client import (
        NavienAPIClient,
    )
    from nwp500.auth import (
        AuthenticationResponse,
        AuthTokens,
        NavienAuthClient,
        UserInfo,
        authenticate,
        refresh_access_token,
    )
    from nwp500.enums import (
        CommandCode,
        CurrentOperationMode,
        DhwOperationSetting,
        DREvent,
        ErrorCode,
        FilterChange,
        HeatSource,
        InstallType,
        OnOffFlag,
        Operation,
        RecirculationMode,
        TemperatureType,
        TempFormulaType,
        TouRateType,
        TouWeekType,
        UnitType,
        VolumeCode,
    )
    from nwp500.events import (
        EventEmitter,
        EventListener,
    )
    from nwp500.exceptions import (
        APIError,
        AuthenticationError,
        DeviceCapabilityError,
        DeviceError,
        InvalidCredentialsError,
        MqttConnectionError,
        MqttCredentialsError,
        MqttError,
        MqttNotConnectedError,
        MqttPublishError,
        Nwp500Error,
        ParameterValidationError,
        RangeValidationError,
        TokenRefreshError,
        ValidationError,
    )
    from nwp500.factory import (
        create_navien_clients,
    )
    from nwp500.models import (
        ConvertedTOUPlan,
        DescalingInfo,
        Device,
        DeviceDiagnostics,
        DeviceErrorSummary,
        DeviceFeature,
        DeviceInfo,
        DeviceStatus,
        DiagnosticsComponentCounters,
        DiagnosticsDhwUsage,
        DiagnosticsEventCounters,
        EnergyUsageDay,
        EnergyUsageResponse,
        EnergyUsageTotal,
        FirmwareDownloadEntry,
        FirmwareDownloadInfo,
        FirmwareInfo,
        Location,
        MonthlyEnergyData,
        MqttCommand,
        MqttRequest,
        OtaCommitPayload,
        RecirculationSchedule,
        RecirculationScheduleEntry,
        ReservationEntry,
        ReservationSchedule,
        TOUInfo,
        TOUPeriod,
        TOUReservationSchedule,
        TOUSchedule,
        fahrenheit_to_half_celsius,
        preferred_to_half_celsius,
        reservation_param_to_preferred,
    )
    from nwp500.mqtt import (
        ConnectionDropEvent,
        ConnectionEvent,
        MqttConnectionConfig,
        MqttDiagnosticsCollector,
        MqttMetrics,
        NavienMqttClient,
        PeriodicRequestType,
        QoS,
    )
    from nwp500.mqtt_events import (
        MqttClientEvents,
    )
    from nwp500.openei import (
        OpenEIClient,
    )
    from nwp500.reservations import (
        add_reservation,
        delete_reservation,
        fetch_reservations,
        update_reservation,
        update_reservations_confirmed,
    )
    from nwp500.tou_schedule import (
        configure_tou_schedule_confirmed,
    )
    from nwp500.unit_system import (
        get_unit_system,
        reset_unit_system,
        set_unit_system,
    )

#: Each export and the module it is loaded from.
_EXPORTS: Mapping[str, str] = MappingProxyType(
    {
        name: module
        for module, names in {
            "nwp500.api_client": ("NavienAPIClient",),
            "nwp500.auth": (
                "AuthenticationResponse",
                "AuthTokens",
                "NavienAuthClient",
                "UserInfo",
                "authenticate",
                "refresh_access_token",
            ),
            "nwp500.enums": (
                "CommandCode",
                "CurrentOperationMode",
                "DhwOperationSetting",
                "DREvent",
                "ErrorCode",
                "FilterChange",
                "HeatSource",
                "InstallType",
                "OnOffFlag",
                "Operation",
                "RecirculationMode",
                "TemperatureType",
                "TempFormulaType",
                "TouRateType",
                "TouWeekType",
                "UnitType",
                "VolumeCode",
            ),
            "nwp500.events": (
                "EventEmitter",
                "EventListener",
            ),
            "nwp500.exceptions": (
                "APIError",
                "AuthenticationError",
                "DeviceCapabilityError",
                "DeviceError",
                "InvalidCredentialsError",
                "MqttConnectionError",
                "MqttCredentialsError",
                "MqttError",
                "MqttNotConnectedError",
                "MqttPublishError",
                "Nwp500Error",
                "ParameterValidationError",
                "RangeValidationError",
                "TokenRefreshError",
                "ValidationError",
            ),
            "nwp500.factory": ("create_navien_clients",),
            "nwp500.models": (
                "ConvertedTOUPlan",
                "DescalingInfo",
                "Device",
                "DeviceDiagnostics",
                "DeviceErrorSummary",
                "DeviceFeature",
                "DeviceInfo",
                "DeviceStatus",
                "DiagnosticsComponentCounters",
                "DiagnosticsDhwUsage",
                "DiagnosticsEventCounters",
                "EnergyUsageDay",
                "EnergyUsageResponse",
                "EnergyUsageTotal",
                "FirmwareDownloadEntry",
                "FirmwareDownloadInfo",
                "FirmwareInfo",
                "Location",
                "MonthlyEnergyData",
                "MqttCommand",
                "MqttRequest",
                "OtaCommitPayload",
                "RecirculationSchedule",
                "RecirculationScheduleEntry",
                "ReservationEntry",
                "ReservationSchedule",
                "TOUInfo",
                "TOUPeriod",
                "TOUReservationSchedule",
                "TOUSchedule",
                "fahrenheit_to_half_celsius",
                "preferred_to_half_celsius",
                "reservation_param_to_preferred",
            ),
            "nwp500.mqtt": (
                "ConnectionDropEvent",
                "ConnectionEvent",
                "MqttConnectionConfig",
                "MqttDiagnosticsCollector",
                "MqttMetrics",
                "NavienMqttClient",
                "PeriodicRequestType",
                "QoS",
            ),
            "nwp500.mqtt_events": ("MqttClientEvents",),
            "nwp500.openei": ("OpenEIClient",),
            "nwp500.reservations": (
                "add_reservation",
                "delete_reservation",
                "fetch_reservations",
                "update_reservation",
                "update_reservations_confirmed",
            ),
            "nwp500.tou_schedule": ("configure_tou_schedule_confirmed",),
            "nwp500.unit_system": (
                "get_unit_system",
                "reset_unit_system",
                "set_unit_system",
            ),
        }.items()
        for name in names
    }
)


def __getattr__(name: str) -> Any:
    """An export, imported on first use and kept; a submodule by its
    name (``nwp500.mqtt``), as the eager imports once left it bound."""
    module = _EXPORTS.get(name)
    if module is not None:
        value = getattr(import_module(module), name)
    elif find_spec(f"{__name__}.{name}") is not None:
        value = import_module(f"{__name__}.{name}")
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})


__all__ = [
    "__version__",
    # Device Capabilities
    "DeviceCapabilityError",
    # Factory functions
    "create_navien_clients",
    # Models
    "ConvertedTOUPlan",
    "DeviceStatus",
    "DeviceFeature",
    "DeviceInfo",
    "Location",
    "Device",
    "DeviceErrorSummary",
    "DescalingInfo",
    "FirmwareInfo",
    "ReservationEntry",
    "ReservationSchedule",
    "RecirculationScheduleEntry",
    "RecirculationSchedule",
    "OtaCommitPayload",
    "DeviceDiagnostics",
    "DiagnosticsEventCounters",
    "DiagnosticsDhwUsage",
    "DiagnosticsComponentCounters",
    "FirmwareDownloadEntry",
    "FirmwareDownloadInfo",
    "TOUSchedule",
    "TOUInfo",
    "TOUPeriod",
    "TOUReservationSchedule",
    "MqttRequest",
    "MqttCommand",
    "EnergyUsageTotal",
    "EnergyUsageDay",
    "MonthlyEnergyData",
    "EnergyUsageResponse",
    # Enumerations
    "CommandCode",
    "CurrentOperationMode",
    "DhwOperationSetting",
    "DREvent",
    "ErrorCode",
    "FilterChange",
    "HeatSource",
    "InstallType",
    "OnOffFlag",
    "Operation",
    "RecirculationMode",
    "TemperatureType",
    "TempFormulaType",
    "TouRateType",
    "TouWeekType",
    "UnitType",
    "VolumeCode",
    # Conversion utilities
    "fahrenheit_to_half_celsius",
    "preferred_to_half_celsius",
    "reservation_param_to_preferred",
    # Authentication
    "NavienAuthClient",
    "AuthenticationResponse",
    "AuthTokens",
    "UserInfo",
    "authenticate",
    "refresh_access_token",
    # Exceptions (all in one place)
    "Nwp500Error",
    "AuthenticationError",
    "InvalidCredentialsError",
    "TokenRefreshError",
    "APIError",
    "MqttError",
    "MqttConnectionError",
    "MqttNotConnectedError",
    "MqttPublishError",
    "MqttCredentialsError",
    "ValidationError",
    "ParameterValidationError",
    "RangeValidationError",
    "DeviceError",
    # API Client
    "NavienAPIClient",
    # OpenEI Client
    "OpenEIClient",
    # Reservation helpers
    "fetch_reservations",
    "add_reservation",
    "delete_reservation",
    "update_reservation",
    "update_reservations_confirmed",
    # TOU schedule helpers
    "configure_tou_schedule_confirmed",
    # MQTT Client
    "NavienMqttClient",
    "MqttConnectionConfig",
    "PeriodicRequestType",
    "MqttDiagnosticsCollector",
    "MqttMetrics",
    "ConnectionDropEvent",
    "ConnectionEvent",
    "QoS",
    # Event Emitter
    "EventEmitter",
    "EventListener",
    "MqttClientEvents",
    # Unit system management
    "set_unit_system",
    "get_unit_system",
    "reset_unit_system",
]
