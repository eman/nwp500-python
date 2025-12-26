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
from nwp500.command_decorators import (
    requires_capability,
)
from nwp500.device_capabilities import (
    MqttDeviceCapabilityChecker,
)
from nwp500.device_info_cache import (
    MqttDeviceInfoCache,
)
from nwp500.encoding import (
    build_reservation_entry,
    build_tou_period,
    decode_price,
    decode_season_bitfield,
    decode_week_bitfield,
    encode_price,
    encode_season_bitfield,
    encode_week_bitfield,
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
    DeviceNotFoundError,
    DeviceOfflineError,
    DeviceOperationError,
    InvalidCredentialsError,
    MqttConnectionError,
    MqttCredentialsError,
    MqttError,
    MqttNotConnectedError,
    MqttPublishError,
    MqttSubscriptionError,
    Nwp500Error,
    ParameterValidationError,
    RangeValidationError,
    TokenExpiredError,
    TokenRefreshError,
    ValidationError,
)
from nwp500.factory import (
    create_navien_clients,
)
from nwp500.models import (
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
    TOUInfo,
    TOUSchedule,
    fahrenheit_to_half_celsius,
)
from nwp500.mqtt import (
    ConnectionDropEvent,
    ConnectionEvent,
    MqttConnectionConfig,
    MqttDiagnosticsCollector,
    MqttMetrics,
    NavienMqttClient,
    PeriodicRequestType,
)
from nwp500.mqtt_events import (
    MqttClientEvents,
)
from nwp500.utils import (
    log_performance,
)

__all__ = [
    "__version__",
    # Device Capabilities & Caching
    "MqttDeviceCapabilityChecker",
    "DeviceCapabilityError",
    "MqttDeviceInfoCache",
    "requires_capability",
    # Factory functions
    "create_navien_clients",
    # Models
    "DeviceStatus",
    "DeviceFeature",
    "DeviceInfo",
    "Location",
    "Device",
    "FirmwareInfo",
    "TOUSchedule",
    "TOUInfo",
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
    "TokenExpiredError",
    "TokenRefreshError",
    "APIError",
    "MqttError",
    "MqttConnectionError",
    "MqttNotConnectedError",
    "MqttPublishError",
    "MqttSubscriptionError",
    "MqttCredentialsError",
    "ValidationError",
    "ParameterValidationError",
    "RangeValidationError",
    "DeviceError",
    "DeviceNotFoundError",
    "DeviceOfflineError",
    "DeviceOperationError",
    # API Client
    "NavienAPIClient",
    # MQTT Client
    "NavienMqttClient",
    "MqttConnectionConfig",
    "PeriodicRequestType",
    "MqttDiagnosticsCollector",
    "MqttMetrics",
    "ConnectionDropEvent",
    "ConnectionEvent",
    # Event Emitter
    "EventEmitter",
    "EventListener",
    "MqttClientEvents",
    # Encoding utilities
    "encode_week_bitfield",
    "decode_week_bitfield",
    "encode_season_bitfield",
    "decode_season_bitfield",
    "encode_price",
    "decode_price",
    "build_reservation_entry",
    "build_tou_period",
    # Utilities
    "log_performance",
]
