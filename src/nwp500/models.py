"""Data models for Navien NWP500 water heater communication.

This module defines data classes for representing data structures
used in the Navien NWP500 water heater communication protocol.

These models are based on the MQTT message formats and API responses.
"""

import logging
from enum import Enum
from typing import Annotated, Any, Optional, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel

_logger = logging.getLogger(__name__)


# ============================================================================
# Conversion Helpers & Validators
# ============================================================================


def _device_bool_validator(v: Any) -> bool:
    """Convert device boolean (2=True, 0/1=False)."""
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


def _deci_celsius_to_fahrenheit(v: Any) -> float:
    """Convert decicelsius (tenths of Celsius) to Fahrenheit."""
    if isinstance(v, (int, float)):
        celsius = float(v) / 10.0
        return (celsius * 9 / 5) + 32
    return float(v)


# Reusable Annotated types for conversions
DeviceBool = Annotated[bool, BeforeValidator(_device_bool_validator)]
Div10 = Annotated[float, BeforeValidator(_div_10_validator)]
HalfCelsiusToF = Annotated[float, BeforeValidator(_half_celsius_to_fahrenheit)]
DeciCelsiusToF = Annotated[float, BeforeValidator(_deci_celsius_to_fahrenheit)]


class NavienBaseModel(BaseModel):
    """Base model for all Navien models."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",  # Ignore unknown fields by default
    )


class DhwOperationSetting(Enum):
    """DHW operation setting modes (user-configured heating preferences)."""

    HEAT_PUMP = 1
    ELECTRIC = 2
    ENERGY_SAVER = 3
    HIGH_DEMAND = 4
    VACATION = 5
    POWER_OFF = 6


class CurrentOperationMode(Enum):
    """Current operation mode (real-time operational state)."""

    STANDBY = 0
    HEAT_PUMP_MODE = 32
    HYBRID_EFFICIENCY_MODE = 64
    HYBRID_BOOST_MODE = 96


class TemperatureUnit(Enum):
    """Temperature unit enumeration."""

    CELSIUS = 1
    FAHRENHEIT = 2


class DeviceInfo(NavienBaseModel):
    """Device information from API."""

    home_seq: int = 0
    mac_address: str = ""
    additional_value: str = ""
    device_type: int = 52
    device_name: str = "Unknown"
    connected: int = 0
    install_type: Optional[str] = None


class Location(NavienBaseModel):
    """Location information for a device."""

    state: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None


class Device(NavienBaseModel):
    """Complete device information including location."""

    device_info: DeviceInfo
    location: Location


class FirmwareInfo(NavienBaseModel):
    """Firmware information for a device."""

    mac_address: str = ""
    additional_value: str = ""
    device_type: int = 52
    cur_sw_code: int = 0
    cur_version: int = 0
    downloaded_version: Optional[int] = None
    device_group: Optional[str] = None


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
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[dict[str, Any]] = None,
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
    error_code: int = Field(description="Error code if any fault is detected")
    sub_error_code: int = Field(
        description="Sub error code providing additional error details"
    )
    smart_diagnostic: int = Field(
        description="Smart diagnostic status for system health monitoring"
    )
    fault_status1: int = Field(description="Fault status register 1")
    fault_status2: int = Field(description="Fault status register 2")
    wifi_rssi: int = Field(
        description="WiFi signal strength",
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
    dr_event_status: int = Field(
        description="Demand Response (DR) event status"
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
        description="Anti-legionella cycle interval",
        json_schema_extra={"unit_of_measurement": "days"},
    )
    program_reservation_type: int = Field(
        description="Type of program reservation"
    )
    temp_formula_type: Union[int, str] = Field(
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
        description="Mixing valve rate percentage",
        json_schema_extra={"unit_of_measurement": "%"},
    )
    eev_step: int = Field(
        description="Electronic Expansion Valve (EEV) step position"
    )
    air_filter_alarm_period: int = Field(
        description="Air filter maintenance cycle interval",
        json_schema_extra={"unit_of_measurement": "h"},
    )
    air_filter_alarm_elapsed: int = Field(
        description="Hours elapsed since last air filter maintenance reset",
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
    tou_status: int = Field(description="Time of Use (TOU) status")
    dr_override_status: int = Field(
        description="Demand Response override status"
    )
    tou_override_status: int = Field(description="Time of Use override status")
    total_energy_capacity: float = Field(
        description="Total energy capacity of the tank",
        json_schema_extra={
            "unit_of_measurement": "Wh",
            "device_class": "energy",
        },
    )
    available_energy_capacity: float = Field(
        description=(
            "Available energy capacity - remaining hot water energy available"
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
        description="Current instantaneous power consumption",
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
        description="Whether freeze protection is active"
    )
    dhw_use: DeviceBool = Field(
        description="Domestic Hot Water (DHW) usage status"
    )
    dhw_use_sustained: DeviceBool = Field(
        description="Sustained DHW usage status"
    )
    program_reservation_use: DeviceBool = Field(
        description="Whether a program reservation is in use"
    )
    eco_use: DeviceBool = Field(
        description=(
            "Whether ECO (Energy Cut Off) safety feature has been triggered"
        )
    )
    comp_use: DeviceBool = Field(description="Compressor usage status")
    eev_use: DeviceBool = Field(
        description="Electronic Expansion Valve (EEV) usage status"
    )
    eva_fan_use: DeviceBool = Field(description="Evaporator fan usage status")
    shut_off_valve_use: DeviceBool = Field(
        description="Shut-off valve usage status"
    )
    con_ovr_sensor_use: DeviceBool = Field(
        description="Condensate overflow sensor usage status"
    )
    wtr_ovr_sensor_use: DeviceBool = Field(
        description="Water overflow/leak sensor usage status"
    )
    anti_legionella_use: DeviceBool = Field(
        description="Whether anti-legionella function is enabled"
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
    current_heat_use: DeviceBool = Field(description="Current heat usage")
    heat_upper_use: DeviceBool = Field(
        description="Upper electric heating element usage status"
    )
    heat_lower_use: DeviceBool = Field(
        description="Lower electric heating element usage status"
    )
    scald_use: DeviceBool = Field(description="Scald protection active status")
    air_filter_alarm_use: DeviceBool = Field(
        description="Air filter maintenance reminder enabled flag"
    )
    recirc_operation_busy: DeviceBool = Field(
        description="Recirculation operation busy status"
    )
    recirc_reservation_use: DeviceBool = Field(
        description="Recirculation reservation usage status"
    )

    # Temperature fields with offset (raw + 20)
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
        description="Freeze protection temperature setpoint",
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
        description="Minimum heat pump operation temperature",
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
    current_inlet_temperature: Div10 = Field(
        description="Current inlet temperature",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    current_dhw_flow_rate: Div10 = Field(
        description="Current DHW flow rate",
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
        description="Compressor discharge temperature",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    suction_temperature: DeciCelsiusToF = Field(
        description="Compressor suction temperature",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    evaporator_temperature: DeciCelsiusToF = Field(
        description="Evaporator temperature",
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
        description="Target superheat value",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    current_super_heat: DeciCelsiusToF = Field(
        description="Current superheat value",
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
    temperature_type: TemperatureUnit = Field(
        default=TemperatureUnit.FAHRENHEIT,
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
            "Country/region code where device is certified for operation"
        )
    )
    model_type_code: int = Field(description="Model type identifier")
    control_type_code: int = Field(description="Control system type")
    volume_code: int = Field(
        description="Tank nominal capacity",
        json_schema_extra={"unit_of_measurement": "gal"},
    )
    controller_sw_version: int = Field(
        description="Main controller firmware version"
    )
    panel_sw_version: int = Field(
        description="Front panel display firmware version"
    )
    wifi_sw_version: int = Field(description="WiFi module firmware version")
    controller_sw_code: int = Field(
        description="Controller firmware variant/branch identifier"
    )
    panel_sw_code: int = Field(
        description="Panel firmware variant/branch identifier"
    )
    wifi_sw_code: int = Field(
        description="WiFi firmware variant/branch identifier"
    )
    controller_serial_number: str = Field(
        description="Unique serial number of the main controller board"
    )
    power_use: int = Field(description="Power control capability")
    holiday_use: int = Field(description="Vacation mode support")
    program_reservation_use: int = Field(
        description="Scheduled operation support"
    )
    dhw_use: int = Field(description="Domestic hot water functionality")
    dhw_temperature_setting_use: int = Field(
        description="Temperature adjustment capability"
    )
    smart_diagnostic_use: int = Field(description="Self-diagnostic capability")
    wifi_rssi_use: int = Field(description="WiFi signal monitoring")
    temp_formula_type: int = Field(
        description="Temperature calculation method identifier"
    )
    energy_usage_use: int = Field(description="Energy monitoring support")
    freeze_protection_use: int = Field(
        description="Freeze protection capability"
    )
    mixing_value_use: int = Field(
        description="Thermostatic mixing valve support"
    )
    dr_setting_use: int = Field(description="Demand Response support")
    anti_legionella_setting_use: int = Field(
        description="Anti-Legionella function"
    )
    hpwh_use: int = Field(description="Heat Pump Water Heater mode")
    dhw_refill_use: int = Field(description="Tank refill detection")
    eco_use: int = Field(description="ECO safety switch")
    electric_use: int = Field(description="Electric-only mode")
    heatpump_use: int = Field(description="Heat pump only mode")
    energy_saver_use: int = Field(description="Energy Saver mode")
    high_demand_use: int = Field(description="High Demand mode")

    # Temperature limit fields with half-degree Celsius scaling
    dhw_temperature_min: HalfCelsiusToF = Field(
        description="Minimum DHW temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    dhw_temperature_max: HalfCelsiusToF = Field(
        description="Maximum DHW temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    freeze_protection_temp_min: HalfCelsiusToF = Field(
        description="Minimum configurable freeze protection limit (43°F)",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    freeze_protection_temp_max: HalfCelsiusToF = Field(
        description="Maximum configurable freeze protection limit (65°F)",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )

    # Enum field
    temperature_type: TemperatureUnit = Field(
        default=TemperatureUnit.FAHRENHEIT,
        description="Default temperature unit preference",
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceFeature":
        """Compatibility method."""
        return cls.model_validate(data)


class MqttRequest(NavienBaseModel):
    """MQTT command request payload."""

    command: int
    device_type: int
    mac_address: str
    additional_value: str = "..."
    mode: Optional[str] = None
    param: list[Union[int, float]] = Field(default_factory=list)
    param_str: str = ""
    month: Optional[list[int]] = None
    year: Optional[int] = None


class MqttCommand(NavienBaseModel):
    """Represents an MQTT command message."""

    client_id: str = Field(alias="clientID")
    session_id: str = Field(alias="sessionID")
    request_topic: str
    response_topic: str
    request: Union[MqttRequest, dict[str, Any]]
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

    def get_month_data(
        self, year: int, month: int
    ) -> Optional[MonthlyEnergyData]:
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
