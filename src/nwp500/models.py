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
    return v == 2


def _add_20_validator(v: Any) -> float:
    """Add 20 to the value (temperature offset)."""
    if isinstance(v, (int, float)):
        return float(v) + 20.0
    return float(v)


def _div_10_validator(v: Any) -> float:
    """Divide by 10."""
    if isinstance(v, (int, float)):
        return float(v) / 10.0
    return float(v)


def _decicelsius_to_fahrenheit(v: Any) -> float:
    """Convert decicelsius (tenths of Celsius) to Fahrenheit."""
    if isinstance(v, (int, float)):
        celsius = float(v) / 10.0
        return (celsius * 9 / 5) + 32
    return float(v)


# Reusable Annotated types for conversions
DeviceBool = Annotated[bool, BeforeValidator(_device_bool_validator)]
Add20 = Annotated[float, BeforeValidator(_add_20_validator)]
Div10 = Annotated[float, BeforeValidator(_div_10_validator)]
DeciCelsiusToF = Annotated[float, BeforeValidator(_decicelsius_to_fahrenheit)]


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
    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[dict[str, Any]] = None,
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
    command: int
    outside_temperature: float
    special_function_status: int
    error_code: int
    sub_error_code: int
    smart_diagnostic: int
    fault_status1: int
    fault_status2: int
    wifi_rssi: int
    dhw_charge_per: float
    dr_event_status: int
    vacation_day_setting: int
    vacation_day_elapsed: int
    anti_legionella_period: int
    program_reservation_type: int
    temp_formula_type: str
    current_statenum: int
    target_fan_rpm: int
    current_fan_rpm: int
    fan_pwm: int
    mixing_rate: float
    eev_step: int
    air_filter_alarm_period: int
    air_filter_alarm_elapsed: int
    cumulated_op_time_eva_fan: int
    cumulated_dhw_flow_rate: float
    tou_status: int
    dr_override_status: int
    tou_override_status: int
    total_energy_capacity: float
    available_energy_capacity: float
    recirc_operation_mode: int
    recirc_pump_operation_status: int
    recirc_hot_btn_ready: int
    recirc_operation_reason: int
    recirc_error_status: int
    current_inst_power: float

    # Boolean fields with device-specific encoding
    did_reload: DeviceBool
    operation_busy: DeviceBool
    freeze_protection_use: DeviceBool
    dhw_use: DeviceBool
    dhw_use_sustained: DeviceBool
    program_reservation_use: DeviceBool
    eco_use: DeviceBool
    comp_use: DeviceBool
    eev_use: DeviceBool
    eva_fan_use: DeviceBool
    shut_off_valve_use: DeviceBool
    con_ovr_sensor_use: DeviceBool
    wtr_ovr_sensor_use: DeviceBool
    anti_legionella_use: DeviceBool
    anti_legionella_operation_busy: DeviceBool
    error_buzzer_use: DeviceBool
    current_heat_use: DeviceBool
    heat_upper_use: DeviceBool
    heat_lower_use: DeviceBool
    scald_use: DeviceBool
    air_filter_alarm_use: DeviceBool
    recirc_operation_busy: DeviceBool
    recirc_reservation_use: DeviceBool

    # Temperature fields with offset (raw + 20)
    dhw_temperature: Add20
    dhw_temperature_setting: Add20
    dhw_target_temperature_setting: Add20
    freeze_protection_temperature: Add20
    dhw_temperature2: Add20
    hp_upper_on_temp_setting: Add20
    hp_upper_off_temp_setting: Add20
    hp_lower_on_temp_setting: Add20
    hp_lower_off_temp_setting: Add20
    he_upper_on_temp_setting: Add20
    he_upper_off_temp_setting: Add20
    he_lower_on_temp_setting: Add20
    he_lower_off_temp_setting: Add20
    heat_min_op_temperature: Add20
    recirc_temp_setting: Add20
    recirc_temperature: Add20
    recirc_faucet_temperature: Add20

    # Fields with scale division (raw / 10.0)
    current_inlet_temperature: Div10
    current_dhw_flow_rate: Div10
    hp_upper_on_diff_temp_setting: Div10
    hp_upper_off_diff_temp_setting: Div10
    hp_lower_on_diff_temp_setting: Div10
    hp_lower_off_diff_temp_setting: Div10
    he_upper_on_diff_temp_setting: Div10
    he_upper_off_diff_temp_setting: Div10
    he_lower_on_diff_temp_setting: Div10 = Field(
        alias="heLowerOnTDiffempSetting"
    )  # Handle API typo: heLowerOnTDiffempSetting -> heLowerOnDiffTempSetting
    he_lower_off_diff_temp_setting: Div10
    recirc_dhw_flow_rate: Div10

    # Temperature fields with decicelsius to Fahrenheit conversion
    tank_upper_temperature: DeciCelsiusToF
    tank_lower_temperature: DeciCelsiusToF
    discharge_temperature: DeciCelsiusToF
    suction_temperature: DeciCelsiusToF
    evaporator_temperature: DeciCelsiusToF
    ambient_temperature: DeciCelsiusToF
    target_super_heat: DeciCelsiusToF
    current_super_heat: DeciCelsiusToF

    # Enum fields
    operation_mode: CurrentOperationMode = Field(
        default=CurrentOperationMode.STANDBY
    )
    dhw_operation_setting: DhwOperationSetting = Field(
        default=DhwOperationSetting.ENERGY_SAVER
    )
    temperature_type: TemperatureUnit = Field(
        default=TemperatureUnit.FAHRENHEIT
    )
    freeze_protection_temp_min: Add20 = 43.0
    freeze_protection_temp_max: Add20 = 65.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceStatus":
        """Compatibility method for existing code."""
        return cls.model_validate(data)


class DeviceFeature(NavienBaseModel):
    """Device capabilities, configuration, and firmware info."""

    country_code: int
    model_type_code: int
    control_type_code: int
    volume_code: int
    controller_sw_version: int
    panel_sw_version: int
    wifi_sw_version: int
    controller_sw_code: int
    panel_sw_code: int
    wifi_sw_code: int
    controller_serial_number: str
    power_use: int
    holiday_use: int
    program_reservation_use: int
    dhw_use: int
    dhw_temperature_setting_use: int
    smart_diagnostic_use: int
    wifi_rssi_use: int
    temp_formula_type: int
    energy_usage_use: int
    freeze_protection_use: int
    mixing_value_use: int
    dr_setting_use: int
    anti_legionella_setting_use: int
    hpwh_use: int
    dhw_refill_use: int
    eco_use: int
    electric_use: int
    heatpump_use: int
    energy_saver_use: int
    high_demand_use: int

    # Temperature limit fields with offset (raw + 20)
    dhw_temperature_min: Add20
    dhw_temperature_max: Add20
    freeze_protection_temp_min: Add20
    freeze_protection_temp_max: Add20

    # Enum field
    temperature_type: TemperatureUnit = Field(
        default=TemperatureUnit.FAHRENHEIT
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

    total_usage: int
    heat_pump_usage: int
    heat_element_usage: int

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


class EnergyUsageDay(NavienBaseModel):
    """Daily energy usage data."""

    day: int
    total_usage: int
    heat_pump_usage: int
    heat_element_usage: int
    heat_pump_time: int
    heat_element_time: int


class EnergyUsageResponse(NavienBaseModel):
    """Response for energy usage query."""

    total: EnergyUsageTotal
    daily: list[EnergyUsageDay]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnergyUsageResponse":
        """Compatibility method."""
        return cls.model_validate(data)
