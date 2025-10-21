"""Data models for Navien NWP500 water heater communication.

This module defines data classes for representing data structures
used in the Navien NWP500 water heater communication protocol.

These models are based on the MQTT message formats and API responses.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union

from . import constants

_logger = logging.getLogger(__name__)


# ============================================================================
# Field Conversion Helpers
# ============================================================================


def meta(**kwargs: Any) -> dict[str, Any]:
    """
    Create metadata for dataclass fields with conversion information.

    Args:
        conversion: Conversion type ('device_bool', 'add_20', 'div_10',
                   'decicelsius_to_f', 'enum')
        enum_class: For enum conversions, the enum class to use
        default_value: For enum conversions, the default value on error

    Returns:
        Metadata dict for use with field(metadata=...)
    """
    return kwargs


def apply_field_conversions(
    cls: type[Any], data: dict[str, Any]
) -> dict[str, Any]:
    """
    Apply conversions to data based on field metadata.

    This function reads conversion metadata from dataclass fields and applies
    the appropriate transformations. This eliminates duplicate field lists and
    makes conversion logic self-documenting.

    Args:
        cls: The dataclass with field metadata
        data: Raw data dictionary to convert

    Returns:
        Converted data dictionary
    """
    converted_data = data.copy()

    # Iterate through all fields and apply conversions based on metadata
    for field_info in cls.__dataclass_fields__.values():
        field_name = field_info.name
        if field_name not in converted_data:
            continue

        metadata = field_info.metadata
        conversion = metadata.get("conversion")

        if not conversion:
            continue

        value = converted_data[field_name]

        # Apply the appropriate conversion
        if conversion == "device_bool":
            # Device encoding: 0 or 1 = false, 2 = true
            converted_data[field_name] = value == 2

        elif conversion == "add_20":
            # Temperature offset conversion
            converted_data[field_name] = value + 20

        elif conversion == "div_10":
            # Scale down by factor of 10
            converted_data[field_name] = value / 10.0

        elif conversion == "decicelsius_to_f":
            # Convert decicelsius (tenths of Celsius) to Fahrenheit
            converted_data[field_name] = _decicelsius_to_fahrenheit(value)

        elif conversion == "enum":
            # Convert to enum with error handling
            enum_class = metadata.get("enum_class")
            default_value = metadata.get("default_value")

            if enum_class:
                try:
                    converted_data[field_name] = enum_class(value)
                except ValueError:
                    if default_value is not None:
                        _logger.warning(
                            "Unknown %s value: %s. Defaulting to %s.",
                            field_name,
                            value,
                            default_value.name
                            if hasattr(default_value, "name")
                            else default_value,
                        )
                        converted_data[field_name] = default_value
                    else:
                        # Re-raise if no default provided
                        raise

    return converted_data


def _decicelsius_to_fahrenheit(raw_value: float) -> float:
    """
    Convert a raw decicelsius value to Fahrenheit.

    Args:
        raw_value: Raw value in decicelsius (tenths of degrees Celsius)

    Returns:
        Temperature in Fahrenheit

    Example:
        >>> _decicelsius_to_fahrenheit(250)  # 25.0°C
        77.0
    """
    celsius = raw_value / 10.0
    return (celsius * 9 / 5) + 32


class DhwOperationSetting(Enum):
    """DHW operation setting modes (user-configured heating preferences).

    This enum represents the user's configured mode preference - what heating
    mode
    the device should use when it needs to heat water. These values appear in
    the
    dhwOperationSetting field and are set via user commands.

    These modes balance energy efficiency and recovery time based on user needs:
    - Higher efficiency = longer recovery time, lower operating costs
    - Lower efficiency = faster recovery time, higher operating costs

    Values are based on the MQTT protocol dhw-mode command parameter as
    documented
    in MQTT_MESSAGES.rst.

    Attributes:
        HEAT_PUMP: Heat Pump Only - most efficient, slowest recovery
        ELECTRIC: Electric Only - least efficient, fastest recovery
        ENERGY_SAVER: Hybrid: Efficiency - balanced, good default
        HIGH_DEMAND: Hybrid: Boost - maximum heating capacity
        VACATION: Vacation mode - suspends heating to save energy
        POWER_OFF: Device powered off - appears when device is turned off
    """

    HEAT_PUMP = 1  # Heat Pump Only - most efficient, slowest recovery
    ELECTRIC = 2  # Electric Only - least efficient, fastest recovery
    ENERGY_SAVER = 3  # Hybrid: Efficiency - balanced, good default
    HIGH_DEMAND = 4  # Hybrid: Boost - maximum heating capacity
    VACATION = 5  # Vacation mode - suspends heating to save energy
    POWER_OFF = 6  # Device powered off - appears when device is turned off


class CurrentOperationMode(Enum):
    """Current operation mode (real-time operational state).

    This enum represents the device's current actual operational state - what
    the device is doing RIGHT NOW. These values appear in the operationMode
    field and change automatically based on heating demand.

    Unlike DhwOperationSetting (user preference), this reflects real-time
    operation and changes dynamically as the device starts/stops heating.

    Values are based on device status responses in MQTT messages as documented
    in DEVICE_STATUS_FIELDS.rst.

    Attributes:
        STANDBY: Device is idle, not actively heating
        HEAT_PUMP_MODE: Heat pump is actively running to heat water
        HYBRID_EFFICIENCY_MODE: Device actively heating in Energy Saver mode
        HYBRID_BOOST_MODE: Device actively heating in High Demand mode
    """

    STANDBY = 0  # Device is idle, not actively heating
    HEAT_PUMP_MODE = 32  # Heat pump is actively running to heat water
    HYBRID_EFFICIENCY_MODE = 64  # Device actively heating in Energy Saver mode
    HYBRID_BOOST_MODE = 96  # Device actively heating in High Demand mode


class TemperatureUnit(Enum):
    """Temperature unit enumeration.

    Attributes:
        CELSIUS: Celsius temperature scale (°C)
        FAHRENHEIT: Fahrenheit temperature scale (°F)
    """

    CELSIUS = 1
    FAHRENHEIT = 2


@dataclass
class DeviceInfo:
    """Device information from API.

    Contains basic device identification and network status information
    retrieved from the Navien Smart Control REST API.

    Attributes:
        home_seq: Home sequence identifier
        mac_address: Device MAC address (unique identifier)
        additional_value: Additional device identifier value
        device_type: Device type code (52 for NWP500)
        device_name: User-assigned device name
        connected: Connection status (1=offline, 2=online)
        install_type: Installation type (optional)
    """

    home_seq: int
    mac_address: str
    additional_value: str
    device_type: int
    device_name: str
    connected: int
    install_type: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceInfo":
        """Create DeviceInfo from API response dictionary."""
        return cls(
            home_seq=data.get("homeSeq", 0),
            mac_address=data.get("macAddress", ""),
            additional_value=data.get("additionalValue", ""),
            device_type=data.get("deviceType", 52),
            device_name=data.get("deviceName", "Unknown"),
            connected=data.get("connected", 0),
            install_type=data.get("installType"),
        )


@dataclass
class Location:
    """Location information for a device.

    Contains geographic and address information for a Navien device.

    Attributes:
        state: State or province
        city: City name
        address: Street address
        latitude: GPS latitude coordinate
        longitude: GPS longitude coordinate
        altitude: Altitude/elevation
    """

    state: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Location":
        """Create Location from API response dictionary."""
        return cls(
            state=data.get("state"),
            city=data.get("city"),
            address=data.get("address"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            altitude=data.get("altitude"),
        )


@dataclass
class Device:
    """Complete device information including location.

    Represents a complete Navien device with both identification/status
    information and geographic location data.

    Attributes:
        device_info: Device identification and status
        location: Geographic location information
    """

    device_info: DeviceInfo
    location: Location

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Device":
        """Create Device from API response dictionary."""
        device_info_data = data.get("deviceInfo", {})
        location_data = data.get("location", {})

        return cls(
            device_info=DeviceInfo.from_dict(device_info_data),
            location=Location.from_dict(location_data),
        )


@dataclass
class FirmwareInfo:
    """Firmware information for a device.

    Contains version and update information for device firmware.
    See FIRMWARE_TRACKING.rst for details on firmware version tracking.

    Attributes:
        mac_address: Device MAC address
        additional_value: Additional device identifier
        device_type: Device type code
        cur_sw_code: Current software code
        cur_version: Current firmware version
        downloaded_version: Downloaded firmware version (if available)
        device_group: Device group identifier (optional)
    """

    mac_address: str
    additional_value: str
    device_type: int
    cur_sw_code: int
    cur_version: int
    downloaded_version: Optional[int] = None
    device_group: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FirmwareInfo":
        """Create FirmwareInfo from API response dictionary."""
        return cls(
            mac_address=data.get("macAddress", ""),
            additional_value=data.get("additionalValue", ""),
            device_type=data.get("deviceType", 52),
            cur_sw_code=data.get("curSwCode", 0),
            cur_version=data.get("curVersion", 0),
            downloaded_version=data.get("downloadedVersion"),
            device_group=data.get("deviceGroup"),
        )


@dataclass
class TOUSchedule:
    """Time of Use schedule information.

    Represents a Time-of-Use (TOU) pricing schedule for energy optimization.
    See TIME_OF_USE.rst for detailed information about TOU configuration.

    Attributes:
        season: Season bitfield (months when schedule applies)
        intervals: List of time intervals with pricing information
    """

    season: int
    intervals: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TOUSchedule":
        """Create TOUSchedule from API response dictionary."""
        return cls(
            season=data.get("season", 0), intervals=data.get("interval", [])
        )


@dataclass
class TOUInfo:
    """Time of Use information.

    Contains complete Time-of-Use (TOU) configuration including utility
    information and pricing schedules. See TIME_OF_USE.rst for details
    on configuring TOU optimization.

    Attributes:
        register_path: Registration path
        source_type: Source type identifier
        controller_id: Controller identifier
        manufacture_id: Manufacturer identifier
        name: TOU schedule name
        utility: Utility company name
        zip_code: ZIP code for utility area
        schedule: List of TOU schedules by season
    """

    register_path: str
    source_type: str
    controller_id: str
    manufacture_id: str
    name: str
    utility: str
    zip_code: int
    schedule: list[TOUSchedule]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TOUInfo":
        """Create TOUInfo from API response dictionary."""
        tou_info_data = data.get("touInfo", {})
        schedule_data = tou_info_data.get("schedule", [])

        return cls(
            register_path=data.get("registerPath", ""),
            source_type=data.get("sourceType", ""),
            controller_id=tou_info_data.get("controllerId", ""),
            manufacture_id=tou_info_data.get("manufactureId", ""),
            name=tou_info_data.get("name", ""),
            utility=tou_info_data.get("utility", ""),
            zip_code=tou_info_data.get("zipCode", 0),
            schedule=[TOUSchedule.from_dict(s) for s in schedule_data],
        )


@dataclass
class DeviceStatus:
    """
    Represents the status of the Navien water heater device.

    This data is typically found in the 'status' object of MQTT response
    messages. This class provides a factory method `from_dict` to
    create an instance from a raw dictionary, applying necessary data
    conversions.

    Field metadata indicates conversion types:
    - device_bool: Device-specific boolean encoding (0/1=false, 2=true)
    - add_20: Temperature offset conversion (raw + 20)
    - div_10: Scale division (raw / 10.0)
    - decicelsius_to_f: Decicelsius to Fahrenheit conversion
    - enum: Enum conversion with default fallback
    """

    # Basic status fields (no conversion needed)
    command: int
    outsideTemperature: float
    specialFunctionStatus: int
    errorCode: int
    subErrorCode: int
    smartDiagnostic: int
    faultStatus1: int
    faultStatus2: int
    wifiRssi: int
    dhwChargePer: float
    drEventStatus: int
    vacationDaySetting: int
    vacationDayElapsed: int
    antiLegionellaPeriod: int
    programReservationType: int
    tempFormulaType: str
    currentStatenum: int
    targetFanRpm: int
    currentFanRpm: int
    fanPwm: int
    mixingRate: float
    eevStep: int
    airFilterAlarmPeriod: int
    airFilterAlarmElapsed: int
    cumulatedOpTimeEvaFan: int
    cumulatedDhwFlowRate: float
    touStatus: int
    drOverrideStatus: int
    touOverrideStatus: int
    totalEnergyCapacity: float
    availableEnergyCapacity: float
    recircOperationMode: int
    recircPumpOperationStatus: int
    recircHotBtnReady: int
    recircOperationReason: int
    recircErrorStatus: int
    currentInstPower: float

    # Boolean fields with device-specific encoding (0/1=false, 2=true)
    didReload: bool = field(metadata=meta(conversion="device_bool"))
    operationBusy: bool = field(metadata=meta(conversion="device_bool"))
    freezeProtectionUse: bool = field(metadata=meta(conversion="device_bool"))
    dhwUse: bool = field(metadata=meta(conversion="device_bool"))
    dhwUseSustained: bool = field(metadata=meta(conversion="device_bool"))
    programReservationUse: bool = field(metadata=meta(conversion="device_bool"))
    ecoUse: bool = field(metadata=meta(conversion="device_bool"))
    compUse: bool = field(metadata=meta(conversion="device_bool"))
    eevUse: bool = field(metadata=meta(conversion="device_bool"))
    evaFanUse: bool = field(metadata=meta(conversion="device_bool"))
    shutOffValveUse: bool = field(metadata=meta(conversion="device_bool"))
    conOvrSensorUse: bool = field(metadata=meta(conversion="device_bool"))
    wtrOvrSensorUse: bool = field(metadata=meta(conversion="device_bool"))
    antiLegionellaUse: bool = field(metadata=meta(conversion="device_bool"))
    antiLegionellaOperationBusy: bool = field(
        metadata=meta(conversion="device_bool")
    )
    errorBuzzerUse: bool = field(metadata=meta(conversion="device_bool"))
    currentHeatUse: bool = field(metadata=meta(conversion="device_bool"))
    heatUpperUse: bool = field(metadata=meta(conversion="device_bool"))
    heatLowerUse: bool = field(metadata=meta(conversion="device_bool"))
    scaldUse: bool = field(metadata=meta(conversion="device_bool"))
    airFilterAlarmUse: bool = field(metadata=meta(conversion="device_bool"))
    recircOperationBusy: bool = field(metadata=meta(conversion="device_bool"))
    recircReservationUse: bool = field(metadata=meta(conversion="device_bool"))

    # Temperature fields with offset (raw + 20)
    dhwTemperature: float = field(metadata=meta(conversion="add_20"))
    dhwTemperatureSetting: float = field(metadata=meta(conversion="add_20"))
    dhwTargetTemperatureSetting: float = field(
        metadata=meta(conversion="add_20")
    )
    freezeProtectionTemperature: float = field(
        metadata=meta(conversion="add_20")
    )
    dhwTemperature2: float = field(metadata=meta(conversion="add_20"))
    hpUpperOnTempSetting: float = field(metadata=meta(conversion="add_20"))
    hpUpperOffTempSetting: float = field(metadata=meta(conversion="add_20"))
    hpLowerOnTempSetting: float = field(metadata=meta(conversion="add_20"))
    hpLowerOffTempSetting: float = field(metadata=meta(conversion="add_20"))
    heUpperOnTempSetting: float = field(metadata=meta(conversion="add_20"))
    heUpperOffTempSetting: float = field(metadata=meta(conversion="add_20"))
    heLowerOnTempSetting: float = field(metadata=meta(conversion="add_20"))
    heLowerOffTempSetting: float = field(metadata=meta(conversion="add_20"))
    heatMinOpTemperature: float = field(metadata=meta(conversion="add_20"))
    recircTempSetting: float = field(metadata=meta(conversion="add_20"))
    recircTemperature: float = field(metadata=meta(conversion="add_20"))
    recircFaucetTemperature: float = field(metadata=meta(conversion="add_20"))

    # Fields with scale division (raw / 10.0)
    currentInletTemperature: float = field(metadata=meta(conversion="div_10"))
    currentDhwFlowRate: float = field(metadata=meta(conversion="div_10"))
    hpUpperOnDiffTempSetting: float = field(metadata=meta(conversion="div_10"))
    hpUpperOffDiffTempSetting: float = field(metadata=meta(conversion="div_10"))
    hpLowerOnDiffTempSetting: float = field(metadata=meta(conversion="div_10"))
    hpLowerOffDiffTempSetting: float = field(metadata=meta(conversion="div_10"))
    heUpperOnDiffTempSetting: float = field(metadata=meta(conversion="div_10"))
    heUpperOffDiffTempSetting: float = field(metadata=meta(conversion="div_10"))
    heLowerOnDiffTempSetting: float = field(metadata=meta(conversion="div_10"))
    heLowerOffDiffTempSetting: float = field(metadata=meta(conversion="div_10"))
    recircDhwFlowRate: float = field(metadata=meta(conversion="div_10"))

    # Temperature fields with decicelsius to Fahrenheit conversion
    tankUpperTemperature: float = field(
        metadata=meta(conversion="decicelsius_to_f")
    )
    tankLowerTemperature: float = field(
        metadata=meta(conversion="decicelsius_to_f")
    )
    dischargeTemperature: float = field(
        metadata=meta(conversion="decicelsius_to_f")
    )
    suctionTemperature: float = field(
        metadata=meta(conversion="decicelsius_to_f")
    )
    evaporatorTemperature: float = field(
        metadata=meta(conversion="decicelsius_to_f")
    )
    ambientTemperature: float = field(
        metadata=meta(conversion="decicelsius_to_f")
    )
    targetSuperHeat: float = field(metadata=meta(conversion="decicelsius_to_f"))
    currentSuperHeat: float = field(
        metadata=meta(conversion="decicelsius_to_f")
    )

    # Enum fields with default fallbacks
    operationMode: CurrentOperationMode = field(
        metadata=meta(
            conversion="enum",
            enum_class=CurrentOperationMode,
            default_value=CurrentOperationMode.STANDBY,
        )
    )
    dhwOperationSetting: DhwOperationSetting = field(
        metadata=meta(
            conversion="enum",
            enum_class=DhwOperationSetting,
            default_value=DhwOperationSetting.ENERGY_SAVER,
        )
    )
    temperatureType: TemperatureUnit = field(
        metadata=meta(
            conversion="enum",
            enum_class=TemperatureUnit,
            default_value=TemperatureUnit.FAHRENHEIT,
        )
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceStatus":
        """Create a DeviceStatus object from a raw dictionary.

        Applies conversions based on field metadata, eliminating duplicate
        field lists and making the code more maintainable.

        Args:
            data: Raw status dictionary from MQTT or API response

        Returns:
            DeviceStatus object with all conversions applied
        """
        # Copy data to avoid modifying the original dictionary
        converted_data = data.copy()

        # Get valid field names for this class
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}

        # Handle key typo from documentation/API
        if "heLowerOnTDiffempSetting" in converted_data:
            converted_data["heLowerOnDiffTempSetting"] = converted_data.pop(
                "heLowerOnTDiffempSetting"
            )

        # Apply all conversions based on field metadata
        converted_data = apply_field_conversions(cls, converted_data)

        # Filter out any unknown fields not defined in the dataclass
        # This handles new fields added by firmware updates gracefully
        unknown_fields = set(converted_data.keys()) - valid_fields
        if unknown_fields:
            # Check if any unknown fields are documented in constants
            known_firmware_fields = set(
                constants.KNOWN_FIRMWARE_FIELD_CHANGES.keys()
            )
            known_new_fields = unknown_fields & known_firmware_fields
            truly_unknown = unknown_fields - known_firmware_fields

            if known_new_fields:
                _logger.info(
                    "Ignoring known new fields from recent firmware: %s. "
                    "These fields are documented but not yet implemented "
                    "in DeviceStatus. Please report this with your "
                    "firmware version to help us track field changes.",
                    known_new_fields,
                )

            if truly_unknown:
                _logger.warning(
                    "Discovered new unknown fields from device status: %s. "
                    "This may indicate a firmware update. Please report "
                    "this issue with your device firmware version "
                    "(controllerSwVersion, panelSwVersion, wifiSwVersion) "
                    "so we can update the library. See "
                    "constants.KNOWN_FIRMWARE_FIELD_CHANGES.",
                    truly_unknown,
                )

            converted_data = {
                k: v for k, v in converted_data.items() if k in valid_fields
            }

        return cls(**converted_data)


@dataclass
class DeviceFeature:
    """
    Represents device capabilities, configuration, and firmware information.

    This data is found in the 'feature' object of MQTT response messages,
    typically received in response to device info requests. It contains
    device model information, firmware versions, capabilities, and limits.

    Field metadata indicates conversion types (same as DeviceStatus).
    """

    # Basic feature fields (no conversion needed)
    countryCode: int
    modelTypeCode: int
    controlTypeCode: int
    volumeCode: int
    controllerSwVersion: int
    panelSwVersion: int
    wifiSwVersion: int
    controllerSwCode: int
    panelSwCode: int
    wifiSwCode: int
    controllerSerialNumber: str
    powerUse: int
    holidayUse: int
    programReservationUse: int
    dhwUse: int
    dhwTemperatureSettingUse: int
    smartDiagnosticUse: int
    wifiRssiUse: int
    tempFormulaType: int
    energyUsageUse: int
    freezeProtectionUse: int
    mixingValueUse: int
    drSettingUse: int
    antiLegionellaSettingUse: int
    hpwhUse: int
    dhwRefillUse: int
    ecoUse: int
    electricUse: int
    heatpumpUse: int
    energySaverUse: int
    highDemandUse: int

    # Temperature limit fields with offset (raw + 20)
    dhwTemperatureMin: int = field(metadata=meta(conversion="add_20"))
    dhwTemperatureMax: int = field(metadata=meta(conversion="add_20"))
    freezeProtectionTempMin: int = field(metadata=meta(conversion="add_20"))
    freezeProtectionTempMax: int = field(metadata=meta(conversion="add_20"))

    # Enum field with default fallback
    temperatureType: TemperatureUnit = field(
        metadata=meta(
            conversion="enum",
            enum_class=TemperatureUnit,
            default_value=TemperatureUnit.FAHRENHEIT,
        )
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceFeature":
        """Create a DeviceFeature object from a raw dictionary.

        Applies conversions based on field metadata.

        Args:
            data: Raw feature dictionary from MQTT or API response

        Returns:
            DeviceFeature object with all conversions applied
        """
        # Copy data to avoid modifying the original dictionary
        converted_data = data.copy()

        # Get valid field names for this class
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}

        # Apply all conversions based on field metadata
        converted_data = apply_field_conversions(cls, converted_data)

        # Filter out any unknown fields (similar to DeviceStatus)
        unknown_fields = set(converted_data.keys()) - valid_fields
        if unknown_fields:
            _logger.info(
                "Ignoring unknown fields from device feature: %s. "
                "This may indicate new device capabilities from a "
                "firmware update.",
                unknown_fields,
            )
            converted_data = {
                k: v for k, v in converted_data.items() if k in valid_fields
            }

        return cls(**converted_data)


@dataclass
class MqttRequest:
    """MQTT command request payload.

    Represents the 'request' object within an MQTT command payload. This is a
    flexible structure that accommodates various command types including status
    requests, control commands, and queries.

    See MQTT_MESSAGES.rst for detailed documentation of all command types
    and their required fields.

    Attributes:
        command: Command code (from CommandCode enum)
        deviceType: Device type code (52 for NWP500)
        macAddress: Device MAC address
        additionalValue: Additional device identifier
        mode: Operation mode for control commands
        param: Parameter list for control commands
        paramStr: Parameter string for control commands
        month: Month list for energy usage queries
        year: Year for energy usage queries
    """

    command: int
    deviceType: int
    macAddress: str
    additionalValue: str = "..."
    # Fields for control commands
    mode: Optional[str] = None
    param: list[Union[int, float]] = field(default_factory=list)
    paramStr: str = ""
    # Fields for energy usage query
    month: Optional[list[int]] = None
    year: Optional[int] = None


@dataclass
class MqttCommand:
    """Represents an MQTT command message sent to a Navien device.

    This class structures the complete MQTT message including routing
    information (topics), session tracking, and the actual command request.

    Attributes:
        clientID: MQTT client identifier
        sessionID: Session identifier for tracking requests/responses
        requestTopic: MQTT topic to publish the command to
        responseTopic: MQTT topic to subscribe for responses
        request: The actual command request payload
        protocolVersion: MQTT protocol version (default: 2)
    """

    clientID: str
    sessionID: str
    requestTopic: str
    responseTopic: str
    request: MqttRequest
    protocolVersion: int = 2


@dataclass
class EnergyUsageData:
    """Daily or monthly energy usage data for a single period.

    This data shows the energy consumption and operating time for both
    the heat pump and electric heating elements. See ENERGY_MONITORING.rst
    for details on querying and interpreting energy usage data.

    Attributes:
        heUsage: Heat Element usage in Watt-hours (Wh)
        hpUsage: Heat Pump usage in Watt-hours (Wh)
        heTime: Heat Element operating time in hours
        hpTime: Heat Pump operating time in hours
    """

    heUsage: int  # Heat Element usage in Watt-hours (Wh)
    hpUsage: int  # Heat Pump usage in Watt-hours (Wh)
    heTime: int  # Heat Element operating time in hours
    hpTime: int  # Heat Pump operating time in hours

    @property
    def total_usage(self) -> int:
        """Calculate total energy usage.

        Returns:
            Total energy usage (heat element + heat pump) in Watt-hours
        """
        return self.heUsage + self.hpUsage

    @property
    def total_time(self) -> int:
        """Calculate total operating time.

        Returns:
            Total operating time (heat element + heat pump) in hours
        """
        return self.heTime + self.hpTime


@dataclass
class MonthlyEnergyData:
    """
    Represents energy usage data for a specific month.

    Contains daily breakdown of energy usage with one entry per day.
    Days are indexed starting from 0 (day 1 is index 0).
    """

    year: int
    month: int
    data: list[EnergyUsageData]

    def get_day_usage(self, day: int) -> Optional[EnergyUsageData]:
        """
        Get energy usage for a specific day of the month.

        Args:
            day: Day of the month (1-31)

        Returns:
            EnergyUsageData for that day, or None if invalid day
        """
        if 1 <= day <= len(self.data):
            return self.data[day - 1]
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonthlyEnergyData":
        """Create MonthlyEnergyData from a raw dictionary."""
        converted_data = data.copy()

        # Convert list of dictionaries to EnergyUsageData objects
        if "data" in converted_data:
            converted_data["data"] = [
                EnergyUsageData(**day_data)
                for day_data in converted_data["data"]
            ]

        return cls(**converted_data)


@dataclass
class EnergyUsageTotal:
    """Represents total energy usage across the queried period.

    Attributes:
        heUsage: Total Heat Element usage in Watt-hours (Wh)
        hpUsage: Total Heat Pump usage in Watt-hours (Wh)
    """

    heUsage: int  # Total Heat Element usage in Watt-hours (Wh)
    hpUsage: int  # Total Heat Pump usage in Watt-hours (Wh)
    heTime: int  # Total Heat Element operating time in hours
    hpTime: int  # Total Heat Pump operating time in hours

    @property
    def total_usage(self) -> int:
        """Total energy usage (heat element + heat pump) in Wh."""
        return self.heUsage + self.hpUsage

    @property
    def total_time(self) -> int:
        """Total operating time (heat element + heat pump) in hours."""
        return self.heTime + self.hpTime

    @property
    def heat_pump_percentage(self) -> float:
        """Percentage of energy from heat pump (0-100)."""
        if self.total_usage == 0:
            return 0.0
        return (self.hpUsage / self.total_usage) * 100

    @property
    def heat_element_percentage(self) -> float:
        """Percentage of energy from electric heating elements (0-100)."""
        if self.total_usage == 0:
            return 0.0
        return (self.heUsage / self.total_usage) * 100


@dataclass
class EnergyUsageResponse:
    """
    Represents the response to an energy usage query.

    This contains historical energy usage data broken down by day
    for the requested month(s), plus totals for the entire period.
    """

    deviceType: int
    macAddress: str
    additionalValue: str
    typeOfUsage: int  # 1 for daily data
    total: EnergyUsageTotal
    usage: list[MonthlyEnergyData]

    def get_month_data(
        self, year: int, month: int
    ) -> Optional[MonthlyEnergyData]:
        """
        Get energy usage data for a specific month.

        Args:
            year: Year (e.g., 2025)
            month: Month (1-12)

        Returns:
            MonthlyEnergyData for that month, or None if not found
        """
        for monthly_data in self.usage:
            if monthly_data.year == year and monthly_data.month == month:
                return monthly_data
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnergyUsageResponse":
        """Create EnergyUsageResponse from a raw dictionary."""
        converted_data = data.copy()

        # Convert total to EnergyUsageTotal
        if "total" in converted_data:
            converted_data["total"] = EnergyUsageTotal(
                **converted_data["total"]
            )

        # Convert usage list to MonthlyEnergyData objects
        if "usage" in converted_data:
            converted_data["usage"] = [
                MonthlyEnergyData.from_dict(month_data)
                for month_data in converted_data["usage"]
            ]

        return cls(**converted_data)
