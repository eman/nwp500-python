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
    APIError,
    NavienAPIClient,
)
from nwp500.auth import (
    AuthenticationError,
    AuthenticationResponse,
    AuthTokens,
    InvalidCredentialsError,
    NavienAuthClient,
    TokenExpiredError,
    TokenRefreshError,
    UserInfo,
    authenticate,
    refresh_access_token,
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
from nwp500.events import (
    EventEmitter,
    EventListener,
)
from nwp500.models import (
    CurrentOperationMode,
    Device,
    DeviceFeature,
    DeviceInfo,
    DeviceStatus,
    DhwOperationSetting,
    EnergyUsageData,
    EnergyUsageResponse,
    EnergyUsageTotal,
    FirmwareInfo,
    Location,
    MonthlyEnergyData,
    MqttCommand,
    MqttRequest,
    TemperatureUnit,
    TOUInfo,
    TOUSchedule,
)
from nwp500.mqtt_client import NavienMqttClient
from nwp500.mqtt_utils import MqttConnectionConfig, PeriodicRequestType
from nwp500.utils import (
    log_performance,
)

__all__ = [
    "__version__",
    # Models
    "DeviceStatus",
    "DeviceFeature",
    "DeviceInfo",
    "Location",
    "Device",
    "FirmwareInfo",
    "TOUSchedule",
    "TOUInfo",
    "DhwOperationSetting",
    "CurrentOperationMode",
    "TemperatureUnit",
    "MqttRequest",
    "MqttCommand",
    "EnergyUsageData",
    "MonthlyEnergyData",
    "EnergyUsageTotal",
    "EnergyUsageResponse",
    # Authentication
    "NavienAuthClient",
    "AuthenticationResponse",
    "AuthTokens",
    "UserInfo",
    "AuthenticationError",
    "InvalidCredentialsError",
    "TokenExpiredError",
    "TokenRefreshError",
    "authenticate",
    "refresh_access_token",
    # Constants
    "constants",
    # API Client
    "NavienAPIClient",
    "APIError",
    # MQTT Client
    "NavienMqttClient",
    "MqttConnectionConfig",
    "PeriodicRequestType",
    # Event Emitter
    "EventEmitter",
    "EventListener",
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
