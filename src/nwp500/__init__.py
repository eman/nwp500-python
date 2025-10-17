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
    OperationMode,  # Deprecated - use DhwOperationSetting or CurrentOperationMode
    TemperatureUnit,
    TOUInfo,
    TOUSchedule,
    enable_deprecation_warnings,
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
    "OperationMode",  # Deprecated - use DhwOperationSetting or CurrentOperationMode
    "DhwOperationSetting",  # New: User-configured mode preferences
    "CurrentOperationMode",  # New: Real-time operational states
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
    # Migration helpers
    "migrate_operation_mode_usage",
    "enable_deprecation_warnings",
]


# Migration helper for backward compatibility
def migrate_operation_mode_usage():
    """
    Helper function to guide migration from OperationMode to specific enums.

    This function provides guidance on migrating from the deprecated OperationMode
    enum to the new DhwOperationSetting and CurrentOperationMode enums.

    Returns:
        dict: Migration guidance with examples
    """
    return {
        "deprecated": "OperationMode",
        "replacements": {
            "dhw_operation_setting": "DhwOperationSetting",
            "operation_mode": "CurrentOperationMode",
        },
        "migration_examples": {
            "dhw_setting_comparison": {
                "old": "status.dhwOperationSetting == OperationMode.ENERGY_SAVER",
                "new": "status.dhwOperationSetting == DhwOperationSetting.ENERGY_SAVER",
            },
            "operation_mode_comparison": {
                "old": "status.operationMode == OperationMode.STANDBY",
                "new": "status.operationMode == CurrentOperationMode.STANDBY",
            },
            "imports": {
                "old": "from nwp500 import OperationMode",
                "new": "from nwp500 import DhwOperationSetting, CurrentOperationMode",
            },
        },
        "value_mappings": {
            "DhwOperationSetting": {
                "HEAT_PUMP": 1,
                "ELECTRIC": 2,
                "ENERGY_SAVER": 3,
                "HIGH_DEMAND": 4,
                "VACATION": 5,
                "POWER_OFF": 6,
            },
            "CurrentOperationMode": {
                "STANDBY": 0,
                "HEAT_PUMP_MODE": 32,
                "HYBRID_EFFICIENCY_MODE": 64,
                "HYBRID_BOOST_MODE": 96,
            },
        },
    }
