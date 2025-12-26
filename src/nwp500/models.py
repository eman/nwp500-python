"""Data models for Navien NWP500 water heater communication.

This module defines data classes for representing data structures
used in the Navien NWP500 water heater communication protocol.

These models are based on the MQTT message formats and API responses.
"""

import logging
from typing import Annotated, Any, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .converters import (
    device_bool_to_python,
    div_10,
    enum_validator,
    tou_override_to_python,
)
from .enums import (
    ConnectionStatus,
    CurrentOperationMode,
    DeviceType,
    DHWControlTypeFlag,
    DhwOperationSetting,
    DREvent,
    ErrorCode,
    HeatSource,
    RecirculationMode,
    TemperatureType,
    TempFormulaType,
    UnitType,
    VolumeCode,
)
from .field_factory import (
    signal_strength_field,
    temperature_field,
)
from .temperature import (
    HalfCelsius,
    deci_celsius_to_fahrenheit,
    half_celsius_to_fahrenheit,
)

_logger = logging.getLogger(__name__)


# ============================================================================
# Conversion Helpers & Validators
# ============================================================================

# Reusable Annotated types for conversions
DeviceBool = Annotated[bool, BeforeValidator(device_bool_to_python)]
CapabilityFlag = Annotated[bool, BeforeValidator(device_bool_to_python)]
Div10 = Annotated[float, BeforeValidator(div_10)]
HalfCelsiusToF = Annotated[float, BeforeValidator(half_celsius_to_fahrenheit)]
DeciCelsiusToF = Annotated[float, BeforeValidator(deci_celsius_to_fahrenheit)]
TouStatus = Annotated[bool, BeforeValidator(bool)]
TouOverride = Annotated[bool, BeforeValidator(tou_override_to_python)]
VolumeCodeField = Annotated[
    VolumeCode, BeforeValidator(enum_validator(VolumeCode))
]
ConnectionStatusField = Annotated[
    ConnectionStatus, BeforeValidator(enum_validator(ConnectionStatus))
]


def fahrenheit_to_half_celsius(fahrenheit: float) -> int:
    """Convert Fahrenheit to half-degrees Celsius (for device commands).

    Args:
        fahrenheit: Temperature in Fahrenheit.

    Returns:
        Raw device value in half-Celsius format.

    Example:
        >>> fahrenheit_to_half_celsius(140.0)
        120
    """
    return int(HalfCelsius.from_fahrenheit(fahrenheit).raw_value)


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
        data: Any, visited: set[int] | None = None
    ) -> Any:
        """Recursively convert Enum values to their names.

        Args:
            data: The data structure to convert.
            visited: Set of object IDs already visited to prevent infinite
                     recursion. None indicates uninitialized/first call.
        """
        from enum import Enum

        if isinstance(data, Enum):
            return data.name
        if not isinstance(data, (dict, list, tuple)):
            return data

        visited = visited or set()
        if id(data) in visited:
            return data
        visited.add(id(data))

        if isinstance(data, dict):
            res: dict[Any, Any] | list[Any] | tuple[Any, ...] = {
                k: NavienBaseModel._convert_enums_to_names(v, visited)
                for k, v in data.items()
            }
        else:
            res = type(data)(
                [
                    NavienBaseModel._convert_enums_to_names(i, visited)
                    for i in data
                ]
            )

        visited.discard(id(data))
        return res


class DeviceInfo(NavienBaseModel):
    """Device information from API."""

    home_seq: int = 0
    mac_address: str = ""
    additional_value: str = ""
    device_type: DeviceType | int = DeviceType.NPF700_WIFI
    device_name: str = "Unknown"
    connected: ConnectionStatusField = ConnectionStatus.DISCONNECTED
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

    def with_info(self, info: DeviceInfo) -> Self:
        """Return a new Device instance with updated DeviceInfo."""
        return self.model_copy(update={"device_info": info})


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
        context: dict[str, Any | None] | None = None,
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
    outside_temperature: float = temperature_field(
        "The outdoor/ambient temperature measured by the heat pump"
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
    wifi_rssi: int = signal_strength_field(
        "WiFi signal strength in dBm. "
        "Typical values: -30 (excellent) to -90 (poor)"
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
    recirc_operation_mode: RecirculationMode = Field(
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
    dhw_operation_busy: DeviceBool = Field(
        default=False,
        description=(
            "DHW operation busy status - "
            "indicates if the device is currently heating water to meet demand"
        ),
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
    dhw_temperature: HalfCelsiusToF = temperature_field(
        "Current Domestic Hot Water (DHW) outlet temperature"
    )
    dhw_temperature_setting: HalfCelsiusToF = temperature_field(
        "User-configured target DHW temperature. "
        "Range: 95°F (35°C) to 150°F (65.5°C). Default: 120°F (49°C)"
    )
    dhw_target_temperature_setting: HalfCelsiusToF = temperature_field(
        "Duplicate of dhw_temperature_setting for legacy API compatibility"
    )
    freeze_protection_temperature: HalfCelsiusToF = temperature_field(
        "Freeze protection temperature setpoint. "
        "Range: 43-50°F (6-10°C), Default: 43°F"
    )
    dhw_temperature2: HalfCelsiusToF = temperature_field(
        "Second DHW temperature reading"
    )
    hp_upper_on_temp_setting: HalfCelsiusToF = temperature_field(
        "Heat pump upper on temperature setting"
    )
    hp_upper_off_temp_setting: HalfCelsiusToF = temperature_field(
        "Heat pump upper off temperature setting"
    )
    hp_lower_on_temp_setting: HalfCelsiusToF = temperature_field(
        "Heat pump lower on temperature setting"
    )
    hp_lower_off_temp_setting: HalfCelsiusToF = temperature_field(
        "Heat pump lower off temperature setting"
    )
    he_upper_on_temp_setting: HalfCelsiusToF = temperature_field(
        "Heater element upper on temperature setting"
    )
    he_upper_off_temp_setting: HalfCelsiusToF = temperature_field(
        "Heater element upper off temperature setting"
    )
    he_lower_on_temp_setting: HalfCelsiusToF = temperature_field(
        "Heater element lower on temperature setting"
    )
    he_lower_off_temp_setting: HalfCelsiusToF = temperature_field(
        "Heater element lower off temperature setting"
    )
    heat_min_op_temperature: HalfCelsiusToF = temperature_field(
        "Minimum heat pump operation temperature. "
        "Lowest tank setpoint allowed (95-113°F, default 95°F)"
    )
    recirc_temp_setting: HalfCelsiusToF = temperature_field(
        "Recirculation temperature setting"
    )
    recirc_temperature: HalfCelsiusToF = temperature_field(
        "Recirculation temperature"
    )
    recirc_faucet_temperature: HalfCelsiusToF = temperature_field(
        "Recirculation faucet temperature"
    )

    # Fields with scale division (raw / 10.0)
    current_inlet_temperature: HalfCelsiusToF = temperature_field(
        "Cold water inlet temperature"
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
    tank_upper_temperature: DeciCelsiusToF = temperature_field(
        "Temperature of the upper part of the tank"
    )
    tank_lower_temperature: DeciCelsiusToF = temperature_field(
        "Temperature of the lower part of the tank"
    )
    discharge_temperature: DeciCelsiusToF = temperature_field(
        "Compressor discharge temperature - "
        "temperature of refrigerant leaving the compressor"
    )
    suction_temperature: DeciCelsiusToF = temperature_field(
        "Compressor suction temperature - "
        "temperature of refrigerant entering the compressor"
    )
    evaporator_temperature: DeciCelsiusToF = temperature_field(
        "Evaporator temperature - "
        "temperature where heat is absorbed from ambient air"
    )
    ambient_temperature: DeciCelsiusToF = temperature_field(
        "Ambient air temperature measured at the heat pump air intake"
    )
    target_super_heat: DeciCelsiusToF = temperature_field(
        "Target superheat value - desired temperature difference "
        "ensuring complete refrigerant vaporization"
    )
    current_super_heat: DeciCelsiusToF = temperature_field(
        "Current superheat value - actual temperature difference "
        "between suction and evaporator temperatures"
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
    freeze_protection_temp_min: HalfCelsiusToF = temperature_field(
        "Active freeze protection lower limit. Default: 43°F (6°C)",
        default=43.0,
    )
    freeze_protection_temp_max: HalfCelsiusToF = temperature_field(
        "Active freeze protection upper limit. Default: 65°F", default=65.0
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceStatus":
        """Compatibility method for existing code."""
        return cls.model_validate(data)


class DeviceFeature(NavienBaseModel):
    """Device capabilities, configuration, and firmware info."""

    country_code: int = Field(
        description=(
            "Country/region code where device is certified for operation. "
            "Device-specific code defined by Navien. "
            "Example: USA devices report code 3. Earlier project "
            "documentation incorrectly listed code 1 for USA; field "
            "observations of production devices confirm that code 3 is "
            "the correct value."
        )
    )
    model_type_code: UnitType | int = Field(
        description=(
            "Model type identifier: Maps to UnitType enum "
            "(e.g., NPF=513 for heat pump water heater). "
            "Identifies the device family and available capabilities"
        )
    )
    control_type_code: int = Field(
        description=(
            "Control system type identifier: Specifies the version of the "
            "digital control system (LCD display, WiFi, firmware variant). "
            "Device-specific numeric code"
        )
    )
    volume_code: VolumeCodeField = Field(
        description=(
            "Tank nominal capacity: 50 gallons (code 1), 65 gallons (code 2), "
            "or 80 gallons (code 3)"
        ),
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
    recirc_sw_version: int = Field(
        description=(
            "Recirculation module firmware version - "
            "controls recirculation pump operation and temperature loop"
        )
    )
    recirc_model_type_code: int = Field(
        description=(
            "Recirculation module model identifier: Specifies the type and "
            "capabilities of the installed recirculation system. "
            "Device-specific numeric code (0 if recirculation not installed)"
        )
    )
    controller_serial_number: str = Field(
        description=(
            "Unique serial number of the main controller board "
            "for warranty and service identification"
        )
    )
    power_use: CapabilityFlag = Field(
        default=False,
        description=("Power control capability (2=supported, 1=not supported)"),
    )
    holiday_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Vacation mode support (2=supported, 1=not supported) - "
            "energy-saving mode for 0-99 days"
        ),
    )
    program_reservation_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Scheduled operation support (2=supported, 1=not supported) - "
            "programmable heating schedules"
        ),
    )
    dhw_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Domestic hot water functionality (2=supported, 1=not supported) - "
            "primary function of water heater"
        ),
    )
    dhw_temperature_setting_use: DHWControlTypeFlag = Field(
        description=(
            "DHW temperature control precision setting: "
            "granularity of temperature adjustments available for DHW control"
        )
    )
    smart_diagnostic_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Self-diagnostic capability (2=supported, 1=not supported) - "
            "10-minute startup diagnostic, error code system"
        ),
    )
    wifi_rssi_use: CapabilityFlag = Field(
        default=False,
        description=(
            "WiFi signal monitoring (2=supported, 1=not supported) - "
            "reports signal strength in dBm"
        ),
    )
    temp_formula_type: TempFormulaType = Field(
        default=TempFormulaType.ASYMMETRIC,
        description=(
            "Temperature calculation method identifier "
            "for internal sensor calibration"
        ),
    )
    energy_usage_use: CapabilityFlag = Field(
        default=False,
        description=("Energy monitoring support (2=supp, 1=not) - tracks kWh"),
    )
    freeze_protection_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Freeze protection capability (2=supported, 1=not supported) - "
            "automatic heating when tank drops below threshold"
        ),
    )
    mixing_valve_use: CapabilityFlag = Field(
        alias="mixingValveUse",
        default=False,
        description=("Thermostatic mixing valve support (2=supp, 1=not)"),
    )
    dr_setting_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Demand Response support (2=supported, 1=not supported) - "
            "CTA-2045 compliance for utility load management"
        ),
    )
    anti_legionella_setting_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Anti-Legionella function (2=supported, 1=not supported) - "
            "periodic heating to 140°F (60°C) to prevent bacteria"
        ),
    )
    hpwh_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Heat Pump Water Heater mode (2=supported, 1=not supported) - "
            "primary efficient heating using refrigeration cycle"
        ),
    )
    dhw_refill_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Tank refill detection (2=supported, 1=not supported) - "
            "monitors for dry fire conditions during refill"
        ),
    )
    eco_use: CapabilityFlag = Field(
        default=False,
        description=(
            "ECO safety switch capability (2=supported, 1=not supported) - "
            "Energy Cut Off high-temperature limit protection"
        ),
    )
    electric_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Electric-only mode (2=supported, 1=not supported) - "
            "heating element only for maximum recovery speed"
        ),
    )
    heatpump_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Heat pump only mode (2=supported, 1=not supported) - "
            "most efficient operation using only refrigeration cycle"
        ),
    )
    energy_saver_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Energy Saver mode (2=supported, 1=not supported) - "
            "hybrid efficiency mode balancing speed and efficiency (default)"
        ),
    )
    high_demand_use: CapabilityFlag = Field(
        default=False,
        description=(
            "High Demand mode (2=supported, 1=not supported) - "
            "hybrid boost mode prioritizing fast recovery"
        ),
    )
    recirculation_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Recirculation pump support (2=supported, 1=not supported) - "
            "instant hot water delivery via dedicated loop"
        ),
    )
    recirc_reservation_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Recirculation schedule support (2=supported, 1=not supported) - "
            "programmable recirculation on specified schedule"
        ),
    )
    title24_use: CapabilityFlag = Field(
        default=False,
        description=(
            "Title 24 compliance (2=supported, 1=not supported) - "
            "California energy code compliance for recirculation systems"
        ),
    )

    # Temperature limit fields with half-degree Celsius scaling
    dhw_temperature_min: HalfCelsiusToF = temperature_field(
        "Minimum DHW temperature setting: 95°F (35°C) - "
        "safety and efficiency lower limit"
    )
    dhw_temperature_max: HalfCelsiusToF = temperature_field(
        "Maximum DHW temperature setting: 150°F (65.5°C) - "
        "scald protection upper limit"
    )
    freeze_protection_temp_min: HalfCelsiusToF = temperature_field(
        "Minimum freeze protection threshold: 43°F (6°C) - "
        "factory default activation temperature"
    )
    freeze_protection_temp_max: HalfCelsiusToF = temperature_field(
        "Maximum freeze protection threshold: 65°F - "
        "user-adjustable upper limit"
    )
    recirc_temperature_min: HalfCelsiusToF = temperature_field(
        "Minimum recirculation temperature setting - "
        "lower limit for recirculation loop temperature control"
    )
    recirc_temperature_max: HalfCelsiusToF = temperature_field(
        "Maximum recirculation temperature setting - "
        "upper limit for recirculation loop temperature control"
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


class EnergyUsageBase(NavienBaseModel):
    """Base energy usage fields common to daily and total responses."""

    heat_pump_usage: int = Field(default=0, alias="hpUsage")
    heat_element_usage: int = Field(default=0, alias="heUsage")
    heat_pump_time: int = Field(default=0, alias="hpTime")
    heat_element_time: int = Field(default=0, alias="heTime")

    @property
    def total_usage(self) -> int:
        return self.heat_pump_usage + self.heat_element_usage


class EnergyUsageTotal(EnergyUsageBase):
    """Total energy usage data."""

    @property
    def heat_pump_percentage(self) -> float:
        return (
            (self.heat_pump_usage / self.total_usage * 100.0)
            if self.total_usage > 0
            else 0.0
        )

    @property
    def heat_element_percentage(self) -> float:
        return (
            (self.heat_element_usage / self.total_usage * 100.0)
            if self.total_usage > 0
            else 0.0
        )

    @property
    def total_time(self) -> int:
        return self.heat_pump_time + self.heat_element_time


class EnergyUsageDay(EnergyUsageBase):
    """Daily energy usage data."""

    pass


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
