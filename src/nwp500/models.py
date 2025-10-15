"""
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


class OperationMode(Enum):
    """Enumeration for the operation modes of the device.

    The first set of modes (0-6) are used when commanding the device or appear
    in dhwOperationSetting, while the second set (32, 64, 96) are observed in
    the operationMode status field.

    Command mode IDs (based on MQTT protocol):
    - 0: Standby (device in idle state)
    - 1: Heat Pump Only (most efficient, slowest recovery)
    - 2: Electric Only (least efficient, fastest recovery)
    - 3: Energy Saver (balanced, good default)
    - 4: High Demand (maximum heating capacity)
    - 5: Vacation mode
    - 6: Power Off (device is powered off - appears in dhwOperationSetting only)
    """

    # Commanded modes
    STANDBY = 0
    HEAT_PUMP = 1  # Heat Pump Only
    ELECTRIC = 2  # Electric Only
    ENERGY_SAVER = 3  # Energy Saver
    HIGH_DEMAND = 4  # High Demand
    VACATION = 5
    POWER_OFF = 6  # Power Off (appears in dhwOperationSetting when device is off)

    # Status modes (operationMode field only)
    HEAT_PUMP_MODE = 32
    HYBRID_EFFICIENCY_MODE = 64
    HYBRID_BOOST_MODE = 96


class TemperatureUnit(Enum):
    """Enumeration for temperature units."""

    CELSIUS = 1
    FAHRENHEIT = 2


@dataclass
class DeviceInfo:
    """Device information from API."""

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
    """Location information for a device."""

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
    """Complete device information including location."""

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
    """Firmware information for a device."""

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
    """Time of Use schedule information."""

    season: int
    intervals: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TOUSchedule":
        """Create TOUSchedule from API response dictionary."""
        return cls(season=data.get("season", 0), intervals=data.get("interval", []))


@dataclass
class TOUInfo:
    """Time of Use information."""

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
    """

    command: int
    outsideTemperature: float
    specialFunctionStatus: int
    didReload: bool
    errorCode: int
    subErrorCode: int
    operationMode: OperationMode
    operationBusy: bool
    freezeProtectionUse: bool
    dhwUse: bool
    dhwUseSustained: bool
    dhwTemperature: float
    dhwTemperatureSetting: float
    programReservationUse: bool
    smartDiagnostic: int
    faultStatus1: int
    faultStatus2: int
    wifiRssi: int
    ecoUse: bool
    dhwTargetTemperatureSetting: float
    tankUpperTemperature: float
    tankLowerTemperature: float
    dischargeTemperature: float
    suctionTemperature: float
    evaporatorTemperature: float
    ambientTemperature: float
    targetSuperHeat: float
    compUse: bool
    eevUse: bool
    evaFanUse: bool
    currentInstPower: float
    shutOffValveUse: bool
    conOvrSensorUse: bool
    wtrOvrSensorUse: bool
    dhwChargePer: float
    drEventStatus: int
    vacationDaySetting: int
    vacationDayElapsed: int
    freezeProtectionTemperature: float
    antiLegionellaUse: bool
    antiLegionellaPeriod: int
    antiLegionellaOperationBusy: bool
    programReservationType: int
    dhwOperationSetting: OperationMode  # User's configured mode preference (command modes: 1-6)
    temperatureType: TemperatureUnit
    tempFormulaType: str
    errorBuzzerUse: bool
    currentHeatUse: bool
    currentInletTemperature: float
    currentStatenum: int
    targetFanRpm: int
    currentFanRpm: int
    fanPwm: int
    dhwTemperature2: float
    currentDhwFlowRate: float
    mixingRate: float
    eevStep: int
    currentSuperHeat: float
    heatUpperUse: bool
    heatLowerUse: bool
    scaldUse: bool
    airFilterAlarmUse: bool
    airFilterAlarmPeriod: int
    airFilterAlarmElapsed: int
    cumulatedOpTimeEvaFan: int
    cumulatedDhwFlowRate: float
    touStatus: int
    hpUpperOnTempSetting: float
    hpUpperOffTempSetting: float
    hpLowerOnTempSetting: float
    hpLowerOffTempSetting: float
    heUpperOnTempSetting: float
    heUpperOffTempSetting: float
    heLowerOnTempSetting: float
    heLowerOffTempSetting: float
    hpUpperOnDiffTempSetting: float
    hpUpperOffDiffTempSetting: float
    hpLowerOnDiffTempSetting: float
    hpLowerOffDiffTempSetting: float
    heUpperOnDiffTempSetting: float
    heUpperOffDiffTempSetting: float
    heLowerOnDiffTempSetting: float
    heLowerOffDiffTempSetting: float
    heatMinOpTemperature: float
    drOverrideStatus: int
    touOverrideStatus: int
    totalEnergyCapacity: float
    availableEnergyCapacity: float
    recircOperationBusy: bool
    recircReservationUse: bool
    recircOperationMode: int
    recircTempSetting: float
    recircTemperature: float
    recircPumpOperationStatus: int
    recircFaucetTemperature: float
    recircHotBtnReady: int
    recircOperationReason: int
    recircDhwFlowRate: float
    recircErrorStatus: int

    @classmethod
    def from_dict(cls, data: dict):
        """
        Creates a DeviceStatus object from a raw dictionary, applying
        conversions.
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

        # Convert integer-based booleans
        # The device uses a non-standard encoding for boolean values:
        #   0 = Not applicable/disabled (rarely used)
        #   1 = OFF/Inactive/False
        #   2 = ON/Active/True
        # This applies to ALL boolean fields in the device status
        bool_fields = [
            "didReload",
            "operationBusy",
            "freezeProtectionUse",
            "dhwUse",
            "dhwUseSustained",
            "programReservationUse",
            "ecoUse",
            "compUse",
            "eevUse",
            "evaFanUse",
            "shutOffValveUse",
            "conOvrSensorUse",
            "wtrOvrSensorUse",
            "antiLegionellaUse",
            "antiLegionellaOperationBusy",
            "errorBuzzerUse",
            "currentHeatUse",
            "heatUpperUse",
            "heatLowerUse",
            "scaldUse",
            "airFilterAlarmUse",
            "recircOperationBusy",
            "recircReservationUse",
        ]

        # Convert using the device's encoding: 0 or 1=false, 2=true
        for field_name in bool_fields:
            if field_name in converted_data:
                converted_data[field_name] = converted_data[field_name] == 2

        # Convert temperatures with 'raw + 20' formula
        add_20_fields = [
            "dhwTemperature",
            "dhwTemperatureSetting",
            "dhwTargetTemperatureSetting",
            "freezeProtectionTemperature",
            "dhwTemperature2",
            "hpUpperOnTempSetting",
            "hpUpperOffTempSetting",
            "hpLowerOnTempSetting",
            "hpLowerOffTempSetting",
            "heUpperOnTempSetting",
            "heUpperOffTempSetting",
            "heLowerOnTempSetting",
            "heLowerOffTempSetting",
            "heatMinOpTemperature",
            "recircTempSetting",
            "recircTemperature",
            "recircFaucetTemperature",
        ]
        for field_name in add_20_fields:
            if field_name in converted_data:
                converted_data[field_name] += 20

        # Convert fields with 'raw / 10.0' formula (non-temperature fields)
        div_10_fields = [
            "currentInletTemperature",
            "currentDhwFlowRate",
            "hpUpperOnDiffTempSetting",
            "hpUpperOffDiffTempSetting",
            "hpLowerOnDiffTempSetting",
            "hpLowerOffDiffTempSetting",
            "heUpperOnDiffTempSetting",
            "heUpperOffDiffTempSetting",
            "heLowerOnDiffTempSetting",
            "heLowerOffDiffTempSetting",
            "recircDhwFlowRate",
        ]
        for field_name in div_10_fields:
            if field_name in converted_data:
                converted_data[field_name] /= 10.0

        # Special conversion for tank temperatures (decicelsius to Fahrenheit)
        tank_temp_fields = ["tankUpperTemperature", "tankLowerTemperature"]
        for field_name in tank_temp_fields:
            if field_name in converted_data:
                converted_data[field_name] = _decicelsius_to_fahrenheit(converted_data[field_name])

        # Special conversion for dischargeTemperature (decicelsius to Fahrenheit)
        if "dischargeTemperature" in converted_data:
            converted_data["dischargeTemperature"] = _decicelsius_to_fahrenheit(
                converted_data["dischargeTemperature"]
            )

        # Special conversion for heat pump temperatures (decicelsius to Fahrenheit)
        heat_pump_temp_fields = [
            "suctionTemperature",
            "evaporatorTemperature",
            "ambientTemperature",
            "currentSuperHeat",
            "targetSuperHeat",
        ]
        for field_name in heat_pump_temp_fields:
            if field_name in converted_data:
                converted_data[field_name] = _decicelsius_to_fahrenheit(converted_data[field_name])

        # Convert enum fields with error handling for unknown values
        if "operationMode" in converted_data:
            try:
                converted_data["operationMode"] = OperationMode(converted_data["operationMode"])
            except ValueError:
                _logger.warning(
                    "Unknown operationMode: %s. Defaulting to STANDBY.",
                    converted_data["operationMode"],
                )
                # Default to a safe enum value so callers can rely on .name
                converted_data["operationMode"] = OperationMode.STANDBY

        if "dhwOperationSetting" in converted_data:
            try:
                converted_data["dhwOperationSetting"] = OperationMode(
                    converted_data["dhwOperationSetting"]
                )
            except ValueError:
                _logger.warning(
                    "Unknown dhwOperationSetting: %s. Defaulting to ENERGY_SAVER.",
                    converted_data["dhwOperationSetting"],
                )
                # Default to ENERGY_SAVER as a safe default
                converted_data["dhwOperationSetting"] = OperationMode.ENERGY_SAVER

        if "temperatureType" in converted_data:
            try:
                converted_data["temperatureType"] = TemperatureUnit(
                    converted_data["temperatureType"]
                )
            except ValueError:
                _logger.warning(
                    "Unknown temperatureType: %s. Defaulting to FAHRENHEIT.",
                    converted_data["temperatureType"],
                )
                # Default to FAHRENHEIT for unknown temperature types
                converted_data["temperatureType"] = TemperatureUnit.FAHRENHEIT

        # Filter out any unknown fields not defined in the dataclass
        # This handles new fields added by firmware updates gracefully
        unknown_fields = set(converted_data.keys()) - valid_fields
        if unknown_fields:
            # Check if any unknown fields are documented in constants
            known_firmware_fields = set(constants.KNOWN_FIRMWARE_FIELD_CHANGES.keys())
            known_new_fields = unknown_fields & known_firmware_fields
            truly_unknown = unknown_fields - known_firmware_fields

            if known_new_fields:
                _logger.info(
                    "Ignoring known new fields from recent firmware: %s. "
                    "These fields are documented but not yet implemented in DeviceStatus. "
                    "Please report this with your firmware version to help us track field changes.",
                    known_new_fields,
                )

            if truly_unknown:
                _logger.warning(
                    "Discovered new unknown fields from device status: %s. "
                    "This may indicate a firmware update. Please report this issue with your "
                    "device firmware version (controllerSwVersion, panelSwVersion, wifiSwVersion) "
                    "so we can update the library. See constants.KNOWN_FIRMWARE_FIELD_CHANGES.",
                    truly_unknown,
                )

            converted_data = {k: v for k, v in converted_data.items() if k in valid_fields}

        return cls(**converted_data)


@dataclass
class DeviceFeature:
    """
    Represents device capabilities, configuration, and firmware information.

    This data is found in the 'feature' object of MQTT response messages,
    typically received in response to device info requests. It contains
    device model information, firmware versions, capabilities, and limits.
    """

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
    dhwTemperatureMin: int
    dhwTemperatureMax: int
    smartDiagnosticUse: int
    wifiRssiUse: int
    temperatureType: TemperatureUnit
    tempFormulaType: int
    energyUsageUse: int
    freezeProtectionUse: int
    freezeProtectionTempMin: int
    freezeProtectionTempMax: int
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

    @classmethod
    def from_dict(cls, data: dict):
        """
        Creates a DeviceFeature object from a raw dictionary.

        Handles enum conversion for temperatureType field and applies
        temperature conversions using the same formulas as DeviceStatus.
        """
        # Copy data to avoid modifying the original dictionary
        converted_data = data.copy()

        # Get valid field names for this class
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}

        # Convert temperature fields with 'raw + 20' formula (same as DeviceStatus)
        temp_add_20_fields = [
            "dhwTemperatureMin",
            "dhwTemperatureMax",
            "freezeProtectionTempMin",
            "freezeProtectionTempMax",
        ]
        for field_name in temp_add_20_fields:
            if field_name in converted_data:
                converted_data[field_name] += 20

        # Convert temperatureType to enum
        if "temperatureType" in converted_data:
            try:
                converted_data["temperatureType"] = TemperatureUnit(
                    converted_data["temperatureType"]
                )
            except ValueError:
                _logger.warning(
                    "Unknown temperatureType: %s. Defaulting to FAHRENHEIT.",
                    converted_data["temperatureType"],
                )
                # Default to FAHRENHEIT for unknown temperature types
                converted_data["temperatureType"] = TemperatureUnit.FAHRENHEIT

        # Filter out any unknown fields (similar to DeviceStatus)
        unknown_fields = set(converted_data.keys()) - valid_fields
        if unknown_fields:
            _logger.info(
                "Ignoring unknown fields from device feature: %s. "
                "This may indicate new device capabilities from a firmware update.",
                unknown_fields,
            )
            converted_data = {k: v for k, v in converted_data.items() if k in valid_fields}

        return cls(**converted_data)


@dataclass
class MqttRequest:
    """
    Represents the 'request' object within an MQTT command payload.

    This is a flexible structure that can accommodate various commands.
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
    """
    Represents the overall structure of an MQTT command message sent to a
    Navien device.
    """

    clientID: str
    sessionID: str
    requestTopic: str
    responseTopic: str
    request: MqttRequest
    protocolVersion: int = 2


@dataclass
class EnergyUsageData:
    """
    Represents daily or monthly energy usage data for a single day/month.

    This data shows the energy consumption and operating time for both
    the heat pump and electric heating elements.
    """

    heUsage: int  # Heat Element usage in Watt-hours (Wh)
    hpUsage: int  # Heat Pump usage in Watt-hours (Wh)
    heTime: int  # Heat Element operating time in hours
    hpTime: int  # Heat Pump operating time in hours

    @property
    def total_usage(self) -> int:
        """Total energy usage (heat element + heat pump) in Wh."""
        return self.heUsage + self.hpUsage

    @property
    def total_time(self) -> int:
        """Total operating time (heat element + heat pump) in hours."""
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
    def from_dict(cls, data: dict):
        """Create MonthlyEnergyData from a raw dictionary."""
        converted_data = data.copy()

        # Convert list of dictionaries to EnergyUsageData objects
        if "data" in converted_data:
            converted_data["data"] = [
                EnergyUsageData(**day_data) for day_data in converted_data["data"]
            ]

        return cls(**converted_data)


@dataclass
class EnergyUsageTotal:
    """
    Represents total energy usage across the queried period.
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

    def get_month_data(self, year: int, month: int) -> Optional[MonthlyEnergyData]:
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
    def from_dict(cls, data: dict):
        """Create EnergyUsageResponse from a raw dictionary."""
        converted_data = data.copy()

        # Convert total to EnergyUsageTotal
        if "total" in converted_data:
            converted_data["total"] = EnergyUsageTotal(**converted_data["total"])

        # Convert usage list to MonthlyEnergyData objects
        if "usage" in converted_data:
            converted_data["usage"] = [
                MonthlyEnergyData.from_dict(month_data) for month_data in converted_data["usage"]
            ]

        return cls(**converted_data)
