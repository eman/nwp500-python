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
from nwp500.events import (
    EventEmitter,
    EventListener,
)
from nwp500.models import (
    Device,
    DeviceFeature,
    DeviceInfo,
    DeviceStatus,
    EnergyUsageData,
    EnergyUsageResponse,
    EnergyUsageTotal,
    FirmwareInfo,
    Location,
    MonthlyEnergyData,
    MqttCommand,
    MqttRequest,
    OperationMode,
    TemperatureUnit,
    TOUInfo,
    TOUSchedule,
)
from nwp500.mqtt_client import (
    MqttConnectionConfig,
    NavienMqttClient,
    PeriodicRequestType,
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
    "OperationMode",
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
]
