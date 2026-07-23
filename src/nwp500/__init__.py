"""Navien NWP500 water heater control library.

This package provides Python bindings for Navien Smart Control API and MQTT
communication for NWP500 heat pump water heaters.
"""

from importlib.metadata import (
    PackageNotFoundError,
    version,
)  # pragma: no cover

try:
    # Change here if project is renamed and does not equal the package name
    dist_name = "nwp500-python"
    __version__ = version(dist_name)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"
finally:
    del version, PackageNotFoundError

# Export main components
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
    Device,
    DeviceFeature,
    DeviceInfo,
    DeviceStatus,
    EnergyUsageDay,
    EnergyUsageResponse,
    EnergyUsageTotal,
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
    WeeklyReservationEntry,
    WeeklyReservationSchedule,
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
    "FirmwareInfo",
    "ReservationEntry",
    "ReservationSchedule",
    "WeeklyReservationEntry",
    "WeeklyReservationSchedule",
    "RecirculationScheduleEntry",
    "RecirculationSchedule",
    "OtaCommitPayload",
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
