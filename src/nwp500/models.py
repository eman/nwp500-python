"""Data models for Navien NWP500 water heater communication.

This module defines data classes for representing data structures
used in the Navien NWP500 water heater communication protocol.

These models are based on the MQTT message formats and API responses.
"""

import logging
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .enums import (
    CurrentOperationMode,
    DeviceType,
    DhwOperationSetting,
    DREvent,
    ErrorCode,
    HeatSource,
    TemperatureType,
    TempFormulaType,
    UnitType,
)

_logger = logging.getLogger(__name__)


# ============================================================================
# Conversion Helpers & Validators
# ============================================================================


def _device_bool_validator(v: Any) -> bool:
    """Convert device boolean (2=True, 0/1=False)."""
    return bool(v == 2)


def _capability_flag_validator(v: Any) -> bool:
    """Convert capability flag (2=True/supported, 1=False/not supported).

    Uses same pattern as OnOffFlag: 1=OFF/not supported, 2=ON/supported.
    """
    return bool(v == 2)


def _div_10_validator(v: Any) -> float:
    """Divide by 10."""
    if isinstance(v, (int, float)):
        return float(v) / 10.0
    return float(v)


def _half_celsius_to_fahrenheit(v: Any) -> float:
    """Convert half-degrees Celsius to Fahrenheit."""
    if isinstance(v, (int, float)):
        celsius = float(v) / 2.0
        return (celsius * 9 / 5) + 32
    return float(v)


def fahrenheit_to_half_celsius(fahrenheit: float) -> int:
    """Convert Fahrenheit to half-degrees Celsius (for device commands).

    This is the inverse of the HalfCelsiusToF conversion used for reading.
    Use this when sending temperature values to the device (e.g., reservations).

    Args:
        fahrenheit: Temperature in Fahrenheit (e.g., 140.0)

    Returns:
        Integer value in half-degrees Celsius for device param field

    Examples:
        >>> fahrenheit_to_half_celsius(140.0)
        120
        >>> fahrenheit_to_half_celsius(120.0)
        98
        >>> fahrenheit_to_half_celsius(95.0)
        70
    """
    celsius = (fahrenheit - 32) * 5 / 9
    return round(celsius * 2)


def _deci_celsius_to_fahrenheit(v: Any) -> float:
    """Convert decicelsius (tenths of Celsius) to Fahrenheit."""
    if isinstance(v, (int, float)):
        celsius = float(v) / 10.0
        return (celsius * 9 / 5) + 32
    return float(v)


def _tou_status_validator(v: Any) -> bool:
    """Convert TOU status (0=False/disabled, 1=True/enabled)."""
    return bool(v == 1)


def _tou_override_validator(v: Any) -> bool:
    """Convert TOU override status (1=True/override active, 2=False/normal).

    Note: This field uses OnOffFlag pattern (1=OFF, 2=ON) but represents
    whether TOU schedule operation is enabled, not whether override is active.
    So: 2 (ON) = TOU operating normally = override NOT active = False
        1 (OFF) = TOU not operating = override IS active = True
    """
    return bool(v == 1)


# Reusable Annotated types for conversions
DeviceBool = Annotated[bool, BeforeValidator(_device_bool_validator)]
CapabilityFlag = Annotated[bool, BeforeValidator(_capability_flag_validator)]
Div10 = Annotated[float, BeforeValidator(_div_10_validator)]
HalfCelsiusToF = Annotated[float, BeforeValidator(_half_celsius_to_fahrenheit)]
DeciCelsiusToF = Annotated[float, BeforeValidator(_deci_celsius_to_fahrenheit)]
TouStatus = Annotated[bool, BeforeValidator(_tou_status_validator)]
TouOverride = Annotated[bool, BeforeValidator(_tou_override_validator)]


class NavienBaseModel(BaseModel):
    """Base model for all Navien models.

    Note: use_enum_values=False keeps enums as objects during validation.
    Serialization to names happens in model_dump() method.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",  # Ignore unknown fields by default
        use_enum_values=False,  # Keep enums as objects during validation
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Dump model to dict with enums as names by default."""
        # Default to 'name' mode for enums unless explicitly overridden
        if "mode" not in kwargs:
            kwargs["mode"] = "python"
        result = super().model_dump(**kwargs)
        # Convert enums to their names
        converted: dict[str, Any] = self._convert_enums_to_names(result)
        return converted

    @staticmethod
    def _convert_enums_to_names(
        data: Any, visited: set[int | None] = None
    ) -> Any:
        """Recursively convert Enum values to their names.

        Args:
            data: Data to convert
            visited: Set of visited object ids to detect cycles

        Returns:
            Data with enums converted to their names
        """
        from enum import Enum

        if visited is None:
            visited = set()

        if isinstance(data, Enum):
            return data.name
        elif isinstance(data, dict):
            # Check for circular reference
            data_id = id(data)
            if data_id in visited:
                return data
            visited.add(data_id)
            result: dict[Any, Any] = {
                key: NavienBaseModel._convert_enums_to_names(value, visited)
                for key, value in data.items()
            }
            visited.discard(data_id)
            return result
        elif isinstance(data, (list, tuple)):
            # Check for circular reference
            data_id = id(data)
            if data_id in visited:
                return data
            visited.add(data_id)
            converted = [
                NavienBaseModel._convert_enums_to_names(item, visited)
                for item in data
            ]
            visited.discard(data_id)
            return type(data)(converted)
        return data


class DeviceInfo(NavienBaseModel):
    """Device information from API."""

    home_seq: int = 0
    mac_address: str = ""
    additional_value: str = ""
    device_type: DeviceType | int = DeviceType.NPF700_WIFI
    device_name: str = "Unknown"
    connected: int = 0
    install_type: str | None = None


class Location(NavienBaseModel):
    """Location information for a device."""

    state: str | None = None
    city: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None


class Device(NavienBaseModel):
    """Complete device information including location."""

    device_info: DeviceInfo
    location: Location


class FirmwareInfo(NavienBaseModel):
    """Firmware information for a device."""

    mac_address: str = ""
    additional_value: str = ""
    device_type: DeviceType | int = DeviceType.NPF700_WIFI
    cur_sw_code: int = 0
    cur_version: int = 0
    downloaded_version: int | None = None
    device_group: str | None = None


class TOUSchedule(NavienBaseModel):
    """Time of Use schedule information."""

    season: int = 0
    intervals: list[dict[str, Any]] = Field(
        default_factory=list, alias="interval"
    )


class TOUInfo(NavienBaseModel):
    """Time of Use information."""

    register_path: str = ""
    source_type: str = ""
    controller_id: str = ""
    manufacture_id: str = ""
    name: str = ""
    utility: str = ""
    zip_code: int = 0
    schedule: list[TOUSchedule] = Field(default_factory=list)

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        from_attributes: bool | None = None,
        context: dict[str, Any | None] = None,
        **kwargs: Any,
    ) -> "TOUInfo":
        # Handle nested structure where fields are in 'touInfo'
        if isinstance(obj, dict):
            data = obj.copy()
            if "touInfo" in data:
                tou_data = data.pop("touInfo")
                data.update(tou_data)
            return super().model_validate(
                data,
                strict=strict,
                from_attributes=from_attributes,
                context=context,
            )
        return super().model_validate(
            obj,
            strict=strict,
            from_attributes=from_attributes,
            context=context,
        )


class DeviceStatus(NavienBaseModel):
    """Represents the status of the Navien water heater device."""

    # Basic status fields
    command: int = Field(
        description="The command that triggered this status update"
    )
    outside_temperature: float = Field(
        description="The outdoor/ambient temperature measured by the heat pump",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    special_function_status: int = Field(
        description=(
            "Status of special functions "
            "(e.g., freeze protection, anti-seize operations)"
        )
    )
    error_code: ErrorCode = Field(
        default=ErrorCode.NO_ERROR,
        description="Error code if any fault is detected",
    )
    sub_error_code: int = Field(
        description="Sub error code providing additional error details"
    )
    smart_diagnostic: int = Field(
        description=(
            "Smart diagnostic status code for system health monitoring. "
            "0 = no diagnostic conditions. "
            "Non-zero = diagnostic condition detected. "
            "Specific diagnostic codes are device firmware dependent."
        )
    )
    fault_status1: int = Field(description="Fault status register 1")
    fault_status2: int = Field(description="Fault status register 2")
    wifi_rssi: int = Field(
        description=(
            "WiFi signal strength in dBm. "
            "Typical values: -30 (excellent) to -90 (poor)"
        ),
        json_schema_extra={
            "unit_of_measurement": "dBm",
            "device_class": "signal_strength",
        },
    )
    dhw_charge_per: float = Field(
        description=(
            "DHW charge percentage - "
            "estimated percentage of hot water capacity available"
        ),
        json_schema_extra={"unit_of_measurement": "%"},
    )
    dr_event_status: DREvent = Field(
        default=DREvent.UNKNOWN,
        description=(
            "Demand Response (DR) event status from utility (CTA-2045). "
            "0=UNKNOWN (No event), 1=RUN_NORMAL, 2=SHED (reduce power), "
            "3=LOADUP (pre-heat), 4=LOADUP_ADV (advanced pre-heat), "
            "5=CPE (customer peak event/grid emergency)"
        ),
    )
    vacation_day_setting: int = Field(
        description="Vacation day setting",
        json_schema_extra={"unit_of_measurement": "days"},
    )
    vacation_day_elapsed: int = Field(
        description="Elapsed vacation days",
        json_schema_extra={"unit_of_measurement": "days"},
    )
    anti_legionella_period: int = Field(
        description=(
            "Anti-legionella cycle interval. Range: 1-30 days, Default: 7 days"
        ),
        json_schema_extra={"unit_of_measurement": "days"},
    )
    program_reservation_type: int = Field(
        description="Type of program reservation"
    )
    temp_formula_type: TempFormulaType = Field(
        description="Temperature formula type"
    )
    current_statenum: int = Field(description="Current state number")
    target_fan_rpm: int = Field(
        description="Target fan RPM",
        json_schema_extra={"unit_of_measurement": "RPM"},
    )
    current_fan_rpm: int = Field(
        description="Current fan RPM",
        json_schema_extra={"unit_of_measurement": "RPM"},
    )
    fan_pwm: int = Field(description="Fan PWM value")
    mixing_rate: float = Field(
        description=(
            "Mixing valve rate percentage (0-100%). "
            "Controls mixing of hot tank water with cold inlet water"
        ),
        json_schema_extra={"unit_of_measurement": "%"},
    )
    eev_step: int = Field(
        description=(
            "Electronic Expansion Valve (EEV) step position. "
            "Valve opening rate expressed as step count"
        )
    )
    air_filter_alarm_period: int = Field(
        description=(
            "Air filter maintenance cycle interval. "
            "Range: Off or 1,000-10,000 hours, Default: 1,000 hours"
        ),
        json_schema_extra={"unit_of_measurement": "h"},
    )
    air_filter_alarm_elapsed: int = Field(
        description=(
            "Operating hours elapsed since last air filter maintenance reset. "
            "Track this to schedule preventative replacement"
        ),
        json_schema_extra={"unit_of_measurement": "h"},
    )
    cumulated_op_time_eva_fan: int = Field(
        description=(
            "Cumulative operation time of the evaporator fan since installation"
        ),
        json_schema_extra={"unit_of_measurement": "h"},
    )
    cumulated_dhw_flow_rate: float = Field(
        description=(
            "Cumulative DHW flow - "
            "total gallons of hot water delivered since installation"
        ),
        json_schema_extra={"unit_of_measurement": "gal"},
    )
    tou_status: TouStatus = Field(
        description=(
            "Time of Use (TOU) scheduling enabled. "
            "True = TOU is active/enabled, False = TOU is disabled"
        )
    )
    dr_override_status: int = Field(
        description=(
            "Demand Response override status in hours. "
            "0 = no override active. "
            "Non-zero (1-72) = override active with specified remaining hours. "
            "User can override DR commands for up to 72 hours."
        ),
        json_schema_extra={"unit_of_measurement": "hours"},
    )
    tou_override_status: TouOverride = Field(
        description=(
            "TOU override status. "
            "True = user has overridden TOU to force immediate heating, "
            "False = device follows TOU schedule normally"
        )
    )
    total_energy_capacity: float = Field(
        description="Total energy capacity of the tank in Watt-hours",
        json_schema_extra={
            "unit_of_measurement": "Wh",
            "device_class": "energy",
        },
    )
    available_energy_capacity: float = Field(
        description=(
            "Available energy capacity - "
            "remaining hot water energy available in Watt-hours"
        ),
        json_schema_extra={
            "unit_of_measurement": "Wh",
            "device_class": "energy",
        },
    )
    recirc_operation_mode: int = Field(
        description="Recirculation operation mode"
    )
    recirc_pump_operation_status: int = Field(
        description="Recirculation pump operation status"
    )
    recirc_hot_btn_ready: int = Field(
        description="Recirculation HotButton ready status"
    )
    recirc_operation_reason: int = Field(
        description="Recirculation operation reason"
    )
    recirc_error_status: int = Field(description="Recirculation error status")
    current_inst_power: float = Field(
        description=(
            "Current instantaneous power consumption in Watts. "
            "Does not include heating element power when active"
        ),
        json_schema_extra={
            "unit_of_measurement": "W",
            "device_class": "power",
        },
    )

    # Boolean fields with device-specific encoding
    did_reload: DeviceBool = Field(
        description="Indicates if the device has recently reloaded or restarted"
    )
    operation_busy: DeviceBool = Field(
        description=(
            "Indicates if the device is currently performing heating operations"
        )
    )
    freeze_protection_use: DeviceBool = Field(
        description=(
            "Whether freeze protection is active. "
            "Electric heater activates when tank water falls below 43°F (6°C)"
        )
    )
    dhw_use: DeviceBool = Field(
        description=(
            "Domestic Hot Water (DHW) usage status - "
            "indicates if hot water is currently being drawn from the tank"
        )
    )
    dhw_use_sustained: DeviceBool = Field(
        description=(
            "Sustained DHW usage status - indicates prolonged hot water usage"
        )
    )
    program_reservation_use: DeviceBool = Field(
        description=(
            "Whether a program reservation (scheduled operation) is in use"
        )
    )
    eco_use: DeviceBool = Field(
        description=(
            "Whether ECO (Energy Cut Off) high-temp safety limit is triggered"
        )
    )
    comp_use: DeviceBool = Field(
        description=(
            "Compressor usage status (True=On, False=Off). "
            "The compressor is the main component of the heat pump"
        )
    )
    eev_use: DeviceBool = Field(
        description=(
            "Electronic Expansion Valve (EEV) usage status. "
            "The EEV controls refrigerant flow"
        )
    )
    eva_fan_use: DeviceBool = Field(
        description=(
            "Evaporator fan usage status. "
            "The fan pulls ambient air through the evaporator coil"
        )
    )
    shut_off_valve_use: DeviceBool = Field(
        description=(
            "Shut-off valve usage status. "
            "The valve controls refrigerant flow in the system"
        )
    )
    con_ovr_sensor_use: DeviceBool = Field(
        description="Condensate overflow sensor usage status"
    )
    wtr_ovr_sensor_use: DeviceBool = Field(
        description=(
            "Water overflow/leak sensor usage status. "
            "Triggers error E799 if leak detected"
        )
    )
    anti_legionella_use: DeviceBool = Field(
        description=(
            "Whether anti-legionella function is enabled. "
            "Device periodically heats tank to prevent Legionella bacteria"
        )
    )
    anti_legionella_operation_busy: DeviceBool = Field(
        description=(
            "Whether the anti-legionella disinfection cycle "
            "is currently running"
        )
    )
    error_buzzer_use: DeviceBool = Field(
        description="Whether the error buzzer is enabled"
    )
    current_heat_use: HeatSource = Field(
        description=(
            "Currently active heat source. Indicates which heating "
            "component(s) are actively running: 0=Unknown/not heating, "
            "1=Heat Pump, 2=Electric Element, 3=Both simultaneously"
        )
    )
    heat_upper_use: DeviceBool = Field(
        description=(
            "Upper electric heating element usage status. "
            "Power: 3,755W @ 208V or 5,000W @ 240V"
        )
    )
    heat_lower_use: DeviceBool = Field(
        description=(
            "Lower electric heating element usage status. "
            "Power: 3,755W @ 208V or 5,000W @ 240V"
        )
    )
    scald_use: DeviceBool = Field(
        description=(
            "Scald protection active status. "
            "Warning when water reaches potentially hazardous levels"
        )
    )
    air_filter_alarm_use: DeviceBool = Field(
        description=(
            "Air filter maintenance reminder enabled flag. "
            "Triggers alerts based on operating hours. Default: On"
        )
    )
    recirc_operation_busy: DeviceBool = Field(
        description="Recirculation operation busy status"
    )
    recirc_reservation_use: DeviceBool = Field(
        description="Recirculation reservation usage status"
    )

    # Temperature fields - encoded in half-degrees Celsius
    dhw_temperature: HalfCelsiusToF = Field(
        description="Current Domestic Hot Water (DHW) outlet temperature",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    dhw_temperature_setting: HalfCelsiusToF = Field(
        description=(
            "User-configured target DHW temperature. "
            "Range: 95°F (35°C) to 150°F (65.5°C). Default: 120°F (49°C)"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    dhw_target_temperature_setting: HalfCelsiusToF = Field(
        description=(
            "Duplicate of dhw_temperature_setting for legacy API compatibility"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    freeze_protection_temperature: HalfCelsiusToF = Field(
        description=(
            "Freeze protection temperature setpoint. "
            "Range: 43-50°F (6-10°C), Default: 43°F"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    dhw_temperature2: HalfCelsiusToF = Field(
        description="Second DHW temperature reading",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_upper_on_temp_setting: HalfCelsiusToF = Field(
        description="Heat pump upper on temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_upper_off_temp_setting: HalfCelsiusToF = Field(
        description="Heat pump upper off temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_lower_on_temp_setting: HalfCelsiusToF = Field(
        description="Heat pump lower on temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_lower_off_temp_setting: HalfCelsiusToF = Field(
        description="Heat pump lower off temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_upper_on_temp_setting: HalfCelsiusToF = Field(
        description="Heater element upper on temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_upper_off_temp_setting: HalfCelsiusToF = Field(
        description="Heater element upper off temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_lower_on_temp_setting: HalfCelsiusToF = Field(
        description="Heater element lower on temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_lower_off_temp_setting: HalfCelsiusToF = Field(
        description="Heater element lower off temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    heat_min_op_temperature: HalfCelsiusToF = Field(
        description=(
            "Minimum heat pump operation temperature. "
            "Lowest tank setpoint allowed (95-113°F, default 95°F)"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    recirc_temp_setting: HalfCelsiusToF = Field(
        description="Recirculation temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    recirc_temperature: HalfCelsiusToF = Field(
        description="Recirculation temperature",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    recirc_faucet_temperature: HalfCelsiusToF = Field(
        description="Recirculation faucet temperature",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )

    # Fields with scale division (raw / 10.0)
    current_inlet_temperature: HalfCelsiusToF = Field(
        description="Cold water inlet temperature",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    current_dhw_flow_rate: Div10 = Field(
        description="Current DHW flow rate in Gallons Per Minute",
        json_schema_extra={"unit_of_measurement": "GPM"},
    )
    hp_upper_on_diff_temp_setting: Div10 = Field(
        description="Heat pump upper on differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_upper_off_diff_temp_setting: Div10 = Field(
        description="Heat pump upper off differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_lower_on_diff_temp_setting: Div10 = Field(
        description="Heat pump lower on differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_lower_off_diff_temp_setting: Div10 = Field(
        description="Heat pump lower off differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_upper_on_diff_temp_setting: Div10 = Field(
        description="Heater element upper on differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_upper_off_diff_temp_setting: Div10 = Field(
        description="Heater element upper off differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_lower_on_diff_temp_setting: Div10 = Field(
        alias="heLowerOnTDiffempSetting",
        description="Heater element lower on differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )  # Handle API typo: heLowerOnTDiffempSetting -> heLowerOnDiffTempSetting
    he_lower_off_diff_temp_setting: Div10 = Field(
        description="Heater element lower off differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    recirc_dhw_flow_rate: Div10 = Field(
        description="Recirculation DHW flow rate",
        json_schema_extra={"unit_of_measurement": "GPM"},
    )

    # Temperature fields with decicelsius to Fahrenheit conversion
    tank_upper_temperature: DeciCelsiusToF = Field(
        description="Temperature of the upper part of the tank",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    tank_lower_temperature: DeciCelsiusToF = Field(
        description="Temperature of the lower part of the tank",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    discharge_temperature: DeciCelsiusToF = Field(
        description=(
            "Compressor discharge temperature - "
            "temperature of refrigerant leaving the compressor"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    suction_temperature: DeciCelsiusToF = Field(
        description=(
            "Compressor suction temperature - "
            "temperature of refrigerant entering the compressor"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    evaporator_temperature: DeciCelsiusToF = Field(
        description=(
            "Evaporator temperature - "
            "temperature where heat is absorbed from ambient air"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    ambient_temperature: DeciCelsiusToF = Field(
        description=(
            "Ambient air temperature measured at the heat pump air intake"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    target_super_heat: DeciCelsiusToF = Field(
        description=(
            "Target superheat value - desired temperature difference "
            "ensuring complete refrigerant vaporization"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    current_super_heat: DeciCelsiusToF = Field(
        description=(
            "Current superheat value - actual temperature difference "
            "between suction and evaporator temperatures"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )

    # Enum fields
    operation_mode: CurrentOperationMode = Field(
        default=CurrentOperationMode.STANDBY,
        description="The current actual operational state of the device",
    )
    dhw_operation_setting: DhwOperationSetting = Field(
        default=DhwOperationSetting.ENERGY_SAVER,
        description="User's configured DHW operation mode preference",
    )
    temperature_type: TemperatureType = Field(
        default=TemperatureType.FAHRENHEIT,
        description="Type of temperature unit",
    )
    freeze_protection_temp_min: HalfCelsiusToF = Field(
        default=43.0,
        description="Active freeze protection lower limit. Default: 43°F (6°C)",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    freeze_protection_temp_max: HalfCelsiusToF = Field(
        default=65.0,
        description="Active freeze protection upper limit. Default: 65°F",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceStatus":
        """Compatibility method for existing code."""
        return cls.model_validate(data)


class DeviceFeature(NavienBaseModel):
    """Device capabilities, configuration, and firmware info."""

    country_code: int = Field(
        description=(
            "Country/region code where device is certified for operation "
            "(1=USA, complies with FCC Part 15 Class B)"
        )
    )
    model_type_code: UnitType | int = Field(
        description="Model type identifier: NWP500 series model variant"
    )
    control_type_code: int = Field(
        description=(
            "Control system type: "
            "Advanced digital control with LCD display and WiFi"
        )
    )
    volume_code: int = Field(
        description="Tank nominal capacity: 50, 65, or 80 gallons",
        json_schema_extra={"unit_of_measurement": "gal"},
    )
    controller_sw_version: int = Field(
        description=(
            "Main controller firmware version - "
            "controls heat pump, heating elements, and system logic"
        )
    )
    panel_sw_version: int = Field(
        description=(
            "Front panel display firmware version - "
            "manages LCD display and user interface"
        )
    )
    wifi_sw_version: int = Field(
        description=(
            "WiFi module firmware version - "
            "handles app connectivity and cloud communication"
        )
    )
    controller_sw_code: int = Field(
        description=(
            "Controller firmware variant/branch identifier "
            "for support and compatibility"
        )
    )
    panel_sw_code: int = Field(
        description=(
            "Panel firmware variant/branch identifier "
            "for display features and UI capabilities"
        )
    )
    wifi_sw_code: int = Field(
        description=(
            "WiFi firmware variant/branch identifier "
            "for communication protocol version"
        )
    )
    controller_serial_number: str = Field(
        description=(
            "Unique serial number of the main controller board "
            "for warranty and service identification"
        )
    )
    power_use: CapabilityFlag = Field(
        description=("Power control capability (2=supported, 1=not supported)")
    )
    holiday_use: CapabilityFlag = Field(
        description=(
            "Vacation mode support (2=supported, 1=not supported) - "
            "energy-saving mode for 0-99 days"
        )
    )
    program_reservation_use: CapabilityFlag = Field(
        description=(
            "Scheduled operation support (2=supported, 1=not supported) - "
            "programmable heating schedules"
        )
    )
    dhw_use: CapabilityFlag = Field(
        description=(
            "Domestic hot water functionality (2=supported, 1=not supported) - "
            "primary function of water heater"
        )
    )
    dhw_temperature_setting_use: CapabilityFlag = Field(
        description=(
            "Temperature adjustment capability "
            "(2=supported, 1=not supported) - "
            "user can modify target temperature"
        )
    )
    smart_diagnostic_use: CapabilityFlag = Field(
        description=(
            "Self-diagnostic capability (2=supported, 1=not supported) - "
            "10-minute startup diagnostic, error code system"
        )
    )
    wifi_rssi_use: CapabilityFlag = Field(
        description=(
            "WiFi signal monitoring (2=supported, 1=not supported) - "
            "reports signal strength in dBm"
        )
    )
    temp_formula_type: TempFormulaType = Field(
        description=(
            "Temperature calculation method identifier "
            "for internal sensor calibration"
        )
    )
    energy_usage_use: CapabilityFlag = Field(
        description=(
            "Energy monitoring support (1=available) - tracks kWh consumption"
        )
    )
    freeze_protection_use: CapabilityFlag = Field(
        description=(
            "Freeze protection capability (1=available) - "
            "automatic heating when tank drops below threshold"
        )
    )
    mixing_value_use: CapabilityFlag = Field(
        description=(
            "Thermostatic mixing valve support (1=available) - "
            "for temperature limiting at point of use"
        )
    )
    dr_setting_use: CapabilityFlag = Field(
        description=(
            "Demand Response support (1=available) - "
            "CTA-2045 compliance for utility load management"
        )
    )
    anti_legionella_setting_use: CapabilityFlag = Field(
        description=(
            "Anti-Legionella function (1=available) - "
            "periodic heating to 140°F (60°C) to prevent bacteria"
        )
    )
    hpwh_use: CapabilityFlag = Field(
        description=(
            "Heat Pump Water Heater mode (1=supported) - "
            "primary efficient heating using refrigeration cycle"
        )
    )
    dhw_refill_use: CapabilityFlag = Field(
        description=(
            "Tank refill detection (1=supported) - "
            "monitors for dry fire conditions during refill"
        )
    )
    eco_use: CapabilityFlag = Field(
        description=(
            "ECO safety switch capability (1=available) - "
            "Energy Cut Off high-temperature limit protection"
        )
    )
    electric_use: CapabilityFlag = Field(
        description=(
            "Electric-only mode (1=supported) - "
            "heating element only for maximum recovery speed"
        )
    )
    heatpump_use: CapabilityFlag = Field(
        description=(
            "Heat pump only mode (1=supported) - "
            "most efficient operation using only refrigeration cycle"
        )
    )
    energy_saver_use: CapabilityFlag = Field(
        description=(
            "Energy Saver mode (1=supported) - "
            "hybrid efficiency mode balancing speed and efficiency (default)"
        )
    )
    high_demand_use: CapabilityFlag = Field(
        description=(
            "High Demand mode (1=supported) - "
            "hybrid boost mode prioritizing fast recovery"
        )
    )

    # Temperature limit fields with half-degree Celsius scaling
    dhw_temperature_min: HalfCelsiusToF = Field(
        description=(
            "Minimum DHW temperature setting: 95°F (35°C) - "
            "safety and efficiency lower limit"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    dhw_temperature_max: HalfCelsiusToF = Field(
        description=(
            "Maximum DHW temperature setting: 150°F (65.5°C) - "
            "scald protection upper limit"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    freeze_protection_temp_min: HalfCelsiusToF = Field(
        description=(
            "Minimum freeze protection threshold: 43°F (6°C) - "
            "factory default activation temperature"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    freeze_protection_temp_max: HalfCelsiusToF = Field(
        description=(
            "Maximum freeze protection threshold: 65°F - "
            "user-adjustable upper limit"
        ),
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )

    # Enum field
    temperature_type: TemperatureType = Field(
        default=TemperatureType.FAHRENHEIT,
        description=(
            "Default temperature unit preference - "
            "factory set to Fahrenheit for USA"
        ),
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceFeature":
        """Compatibility method."""
        return cls.model_validate(data)


class MqttRequest(NavienBaseModel):
    """MQTT command request payload."""

    command: int
    device_type: DeviceType | int
    mac_address: str
    additional_value: str = "..."
    mode: str | None = None
    param: list[int | float] = Field(default_factory=list)
    param_str: str = ""
    month: list[int] | None = None
    year: int | None = None


class MqttCommand(NavienBaseModel):
    """Represents an MQTT command message."""

    client_id: str = Field(alias="clientID")
    session_id: str = Field(alias="sessionID")
    request_topic: str
    response_topic: str
    request: MqttRequest | dict[str, Any]
    protocol_version: int = 2


class EnergyUsageTotal(NavienBaseModel):
    """Total energy usage data."""

    heat_pump_usage: int = Field(default=0, alias="hpUsage")
    heat_element_usage: int = Field(default=0, alias="heUsage")
    heat_pump_time: int = Field(default=0, alias="hpTime")
    heat_element_time: int = Field(default=0, alias="heTime")

    @property
    def total_usage(self) -> int:
        """Total energy usage (heat pump + heat element)."""
        return self.heat_pump_usage + self.heat_element_usage

    @property
    def heat_pump_percentage(self) -> float:
        if self.total_usage == 0:
            return 0.0
        return (self.heat_pump_usage / self.total_usage) * 100.0

    @property
    def heat_element_percentage(self) -> float:
        if self.total_usage == 0:
            return 0.0
        return (self.heat_element_usage / self.total_usage) * 100.0

    @property
    def total_time(self) -> int:
        """Total operating time (heat pump + heat element)."""
        return self.heat_pump_time + self.heat_element_time


class EnergyUsageDay(NavienBaseModel):
    """Daily energy usage data.

    Note: The API returns a fixed-length array (30 elements) for each month,
    with unused days having all zeros. The day number is implicit from the
    array index (0-based).
    """

    heat_pump_usage: int = Field(alias="hpUsage")
    heat_element_usage: int = Field(alias="heUsage")
    heat_pump_time: int = Field(alias="hpTime")
    heat_element_time: int = Field(alias="heTime")

    @property
    def total_usage(self) -> int:
        """Total energy usage (heat pump + heat element)."""
        return self.heat_pump_usage + self.heat_element_usage


class MonthlyEnergyData(NavienBaseModel):
    """Monthly energy usage data grouping."""

    year: int
    month: int
    data: list[EnergyUsageDay]


class EnergyUsageResponse(NavienBaseModel):
    """Response for energy usage query."""

    total: EnergyUsageTotal
    usage: list[MonthlyEnergyData]

    def get_month_data(self, year: int, month: int) -> MonthlyEnergyData | None:
        """Get energy usage data for a specific month.

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
        """Compatibility method."""
        return cls.model_validate(data)
