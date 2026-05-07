from __future__ import annotations

import warnings
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, computed_field

from .._base import NavienBaseModel
from ..converters import (
    device_bool_to_python,
    div_10,
    mul_10,
    tou_override_to_python,
)
from ..enums import (
    CurrentOperationMode,
    DhwOperationSetting,
    DREvent,
    ErrorCode,
    HeatSource,
    RecirculationMode,
    TemperatureType,
    TempFormulaType,
)
from ..field_factory import signal_strength_field, temperature_field
from ..temperature import (
    DeciCelsius,
    DeciCelsiusDelta,
    HalfCelsius,
    RawCelsius,
)
from ..unit_system import get_unit_system

DeviceBool = Annotated[bool, BeforeValidator(device_bool_to_python)]
Div10 = Annotated[float, BeforeValidator(div_10)]
TenWhToWh = Annotated[float, BeforeValidator(mul_10)]
TouStatus = Annotated[bool, BeforeValidator(bool)]
TouOverride = Annotated[bool, BeforeValidator(tou_override_to_python)]


class DeviceStatus(NavienBaseModel):
    """Represents the status of the Navien water heater device."""

    # CRITICAL: temperature_type must remain the first field so computed
    # temperature properties can fall back to the device's native unit setting.
    temperature_type: TemperatureType = Field(
        default=TemperatureType.FAHRENHEIT,
        description=(
            "Type of temperature unit (1=Celsius, 2=Fahrenheit). "
            "Controls all unit conversions."
        ),
    )

    # Basic status fields
    command: int = Field(
        description="The command that triggered this status update"
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
    outside_temperature_raw: int = temperature_field(
        "Outdoor/ambient temperature", alias="outsideTemperature"
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
    cumulated_dhw_flow_rate_raw: int = Field(
        alias="cumulatedDhwFlowRate",
        description=(
            "Cumulative DHW flow - "
            "total volume of hot water delivered since installation"
        ),
        json_schema_extra={
            "unit_of_measurement": "gal",
            "device_class": "water",
        },
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
    total_energy_capacity: TenWhToWh = Field(
        description="Total energy capacity of the tank in Watt-hours",
        json_schema_extra={
            "unit_of_measurement": "Wh",
            "device_class": "energy",
        },
    )
    available_energy_capacity: TenWhToWh = Field(
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
            "Electric heater activates when tank water falls below threshold"
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

    # Raw temperature, flow, and volume fields
    dhw_temperature_raw: int = temperature_field(
        "Current Domestic Hot Water (DHW) outlet temperature",
        alias="dhwTemperature",
    )
    dhw_temperature_setting_raw: int = temperature_field(
        "User-configured target DHW temperature",
        alias="dhwTemperatureSetting",
    )
    dhw_target_temperature_setting_raw: int = temperature_field(
        "Duplicate of dhw_temperature_setting for legacy API compatibility",
        alias="dhwTargetTemperatureSetting",
    )
    freeze_protection_temperature_raw: int = temperature_field(
        "Freeze protection temperature setpoint. "
        "Prevents tank from freezing in cold environments",
        alias="freezeProtectionTemperature",
    )
    dhw_temperature2_raw: int = temperature_field(
        "Second DHW temperature reading",
        alias="dhwTemperature2",
    )
    hp_upper_on_temp_setting_raw: int = temperature_field(
        "Heat pump upper on temperature setting",
        alias="hpUpperOnTempSetting",
    )
    hp_upper_off_temp_setting_raw: int = temperature_field(
        "Heat pump upper off temperature setting",
        alias="hpUpperOffTempSetting",
    )
    hp_lower_on_temp_setting_raw: int = temperature_field(
        "Heat pump lower on temperature setting",
        alias="hpLowerOnTempSetting",
    )
    hp_lower_off_temp_setting_raw: int = temperature_field(
        "Heat pump lower off temperature setting",
        alias="hpLowerOffTempSetting",
    )
    he_upper_on_temp_setting_raw: int = temperature_field(
        "Heater element upper on temperature setting",
        alias="heUpperOnTempSetting",
    )
    he_upper_off_temp_setting_raw: int = temperature_field(
        "Heater element upper off temperature setting",
        alias="heUpperOffTempSetting",
    )
    he_lower_on_temp_setting_raw: int = temperature_field(
        "Heater element lower on temperature setting",
        alias="heLowerOnTempSetting",
    )
    he_lower_off_temp_setting_raw: int = temperature_field(
        "Heater element lower off temperature setting",
        alias="heLowerOffTempSetting",
    )
    heat_min_op_temperature_raw: int = temperature_field(
        "Minimum heat pump operation temperature. "
        "Lowest tank setpoint allowed for heat pump operation",
        alias="heatMinOpTemperature",
    )
    recirc_temp_setting_raw: int = temperature_field(
        "Recirculation temperature setting",
        alias="recircTempSetting",
    )
    recirc_temperature_raw: int = temperature_field(
        "Recirculation temperature",
        alias="recircTemperature",
    )
    recirc_faucet_temperature_raw: int = temperature_field(
        "Recirculation faucet temperature",
        alias="recircFaucetTemperature",
    )
    current_inlet_temperature_raw: int = temperature_field(
        "Cold water inlet temperature",
        alias="currentInletTemperature",
    )
    current_dhw_flow_rate_raw: int = Field(
        alias="currentDhwFlowRate",
        description="Current DHW flow rate",
        json_schema_extra={
            "unit_of_measurement": "GPM",
            "device_class": "flow_rate",
        },
    )
    hp_upper_on_diff_temp_setting_raw: int = Field(
        alias="hpUpperOnDiffTempSetting",
        description="Heat pump upper on differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_upper_off_diff_temp_setting_raw: int = Field(
        alias="hpUpperOffDiffTempSetting",
        description="Heat pump upper off differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_lower_on_diff_temp_setting_raw: int = Field(
        alias="hpLowerOnDiffTempSetting",
        description="Heat pump lower on differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    hp_lower_off_diff_temp_setting_raw: int = Field(
        alias="hpLowerOffDiffTempSetting",
        description="Heat pump lower off differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_upper_on_diff_temp_setting_raw: int = Field(
        alias="heUpperOnDiffTempSetting",
        description="Heater element upper on differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_upper_off_diff_temp_setting_raw: int = Field(
        alias="heUpperOffDiffTempSetting",
        description="Heater element upper off differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    he_lower_on_diff_temp_setting_raw: int = Field(
        alias="heLowerOnTDiffempSetting",
        description="Heater element lower on differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )  # Handle API typo: heLowerOnTDiffempSetting -> heLowerOnDiffTempSetting
    he_lower_off_diff_temp_setting_raw: int = Field(
        alias="heLowerOffDiffTempSetting",
        description="Heater element lower off differential temperature setting",
        json_schema_extra={
            "unit_of_measurement": "°F",
            "device_class": "temperature",
        },
    )
    recirc_dhw_flow_rate_raw: int = Field(
        alias="recircDhwFlowRate",
        description="Recirculation DHW flow rate (dynamic units: LPM/GPM)",
        json_schema_extra={
            "device_class": "flow_rate",
        },
    )
    tank_upper_temperature_raw: int = temperature_field(
        "Temperature of the upper part of the tank",
        alias="tankUpperTemperature",
    )
    tank_lower_temperature_raw: int = temperature_field(
        "Temperature of the lower part of the tank",
        alias="tankLowerTemperature",
    )
    discharge_temperature_raw: int = temperature_field(
        "Compressor discharge temperature - "
        "temperature of refrigerant leaving the compressor",
        alias="dischargeTemperature",
    )
    suction_temperature_raw: int = temperature_field(
        "Compressor suction temperature - "
        "temperature of refrigerant entering the compressor",
        alias="suctionTemperature",
    )
    evaporator_temperature_raw: int = temperature_field(
        "Evaporator temperature - "
        "temperature where heat is absorbed from ambient air",
        alias="evaporatorTemperature",
    )
    ambient_temperature_raw: int = temperature_field(
        "Ambient air temperature measured at the heat pump air intake",
        alias="ambientTemperature",
    )
    target_super_heat_raw: int = temperature_field(
        "Target superheat value - desired temperature difference "
        "ensuring complete refrigerant vaporization",
        alias="targetSuperHeat",
    )
    current_super_heat_raw: int = temperature_field(
        "Current superheat value - actual temperature difference "
        "between suction and evaporator temperatures",
        alias="currentSuperHeat",
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
    freeze_protection_temp_min_raw: int = temperature_field(
        "Active freeze protection lower limit",
        alias="freezeProtectionTempMin",
        default=43,
    )
    freeze_protection_temp_max_raw: int = temperature_field(
        "Active freeze protection upper limit",
        alias="freezeProtectionTempMax",
        default=65,
    )

    def _is_celsius(self) -> bool:
        """Return True if metric/Celsius units should be used."""
        unit_system = get_unit_system()
        if unit_system is not None:
            return unit_system == "metric"
        return self.temperature_type == TemperatureType.CELSIUS

    @computed_field  # type: ignore[prop-decorator]
    @property
    def outside_temperature(self) -> float:
        raw = RawCelsius(self.outside_temperature_raw)
        if self._is_celsius():
            return raw.to_celsius()
        return raw.to_fahrenheit_with_formula(self.temp_formula_type)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dhw_temperature(self) -> float:
        return HalfCelsius(self.dhw_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dhw_temperature_setting(self) -> float:
        return HalfCelsius(self.dhw_temperature_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dhw_target_temperature_setting(self) -> float:
        return HalfCelsius(
            self.dhw_target_temperature_setting_raw
        ).to_preferred(self._is_celsius())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def freeze_protection_temperature(self) -> float:
        return HalfCelsius(self.freeze_protection_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dhw_temperature2(self) -> float:
        return HalfCelsius(self.dhw_temperature2_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hp_upper_on_temp_setting(self) -> float:
        return HalfCelsius(self.hp_upper_on_temp_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hp_upper_off_temp_setting(self) -> float:
        return HalfCelsius(self.hp_upper_off_temp_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hp_lower_on_temp_setting(self) -> float:
        return HalfCelsius(self.hp_lower_on_temp_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hp_lower_off_temp_setting(self) -> float:
        return HalfCelsius(self.hp_lower_off_temp_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def he_upper_on_temp_setting(self) -> float:
        return HalfCelsius(self.he_upper_on_temp_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def he_upper_off_temp_setting(self) -> float:
        return HalfCelsius(self.he_upper_off_temp_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def he_lower_on_temp_setting(self) -> float:
        return HalfCelsius(self.he_lower_on_temp_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def he_lower_off_temp_setting(self) -> float:
        return HalfCelsius(self.he_lower_off_temp_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def heat_min_op_temperature(self) -> float:
        return HalfCelsius(self.heat_min_op_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recirc_temp_setting(self) -> float:
        return HalfCelsius(self.recirc_temp_setting_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recirc_temperature(self) -> float:
        return HalfCelsius(self.recirc_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recirc_faucet_temperature(self) -> float:
        return HalfCelsius(self.recirc_faucet_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def current_inlet_temperature(self) -> float:
        return HalfCelsius(self.current_inlet_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def current_dhw_flow_rate(self) -> float:
        lpm = self.current_dhw_flow_rate_raw / 10.0
        if self._is_celsius():
            return lpm
        return round(lpm * 0.264172, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hp_upper_on_diff_temp_setting(self) -> float:
        return DeciCelsiusDelta(
            self.hp_upper_on_diff_temp_setting_raw
        ).to_preferred(self._is_celsius())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hp_upper_off_diff_temp_setting(self) -> float:
        return DeciCelsiusDelta(
            self.hp_upper_off_diff_temp_setting_raw
        ).to_preferred(self._is_celsius())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hp_lower_on_diff_temp_setting(self) -> float:
        return DeciCelsiusDelta(
            self.hp_lower_on_diff_temp_setting_raw
        ).to_preferred(self._is_celsius())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hp_lower_off_diff_temp_setting(self) -> float:
        return DeciCelsiusDelta(
            self.hp_lower_off_diff_temp_setting_raw
        ).to_preferred(self._is_celsius())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def he_upper_on_diff_temp_setting(self) -> float:
        return DeciCelsiusDelta(
            self.he_upper_on_diff_temp_setting_raw
        ).to_preferred(self._is_celsius())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def he_upper_off_diff_temp_setting(self) -> float:
        return DeciCelsiusDelta(
            self.he_upper_off_diff_temp_setting_raw
        ).to_preferred(self._is_celsius())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def he_lower_on_diff_temp_setting(self) -> float:
        return DeciCelsiusDelta(
            self.he_lower_on_diff_temp_setting_raw
        ).to_preferred(self._is_celsius())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def he_lower_off_diff_temp_setting(self) -> float:
        return DeciCelsiusDelta(
            self.he_lower_off_diff_temp_setting_raw
        ).to_preferred(self._is_celsius())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recirc_dhw_flow_rate(self) -> float:
        lpm = self.recirc_dhw_flow_rate_raw / 10.0
        if self._is_celsius():
            return lpm
        return round(lpm * 0.264172, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tank_upper_temperature(self) -> float:
        return DeciCelsius(self.tank_upper_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tank_lower_temperature(self) -> float:
        return DeciCelsius(self.tank_lower_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def discharge_temperature(self) -> float:
        return DeciCelsius(self.discharge_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def suction_temperature(self) -> float:
        return DeciCelsius(self.suction_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evaporator_temperature(self) -> float:
        return DeciCelsius(self.evaporator_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ambient_temperature(self) -> float:
        return DeciCelsius(self.ambient_temperature_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def target_super_heat(self) -> float:
        return DeciCelsius(self.target_super_heat_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def current_super_heat(self) -> float:
        return DeciCelsius(self.current_super_heat_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cumulated_dhw_flow_rate(self) -> float:
        liters = float(self.cumulated_dhw_flow_rate_raw)
        if self._is_celsius():
            return liters
        return round(liters * 0.264172, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def freeze_protection_temp_min(self) -> float:
        return HalfCelsius(self.freeze_protection_temp_min_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def freeze_protection_temp_max(self) -> float:
        return HalfCelsius(self.freeze_protection_temp_max_raw).to_preferred(
            self._is_celsius()
        )

    def get_field_unit(self, field_name: str) -> str:
        """Get the correct unit suffix based on temperature preference.

        Resolves dynamic units for temperature, flow rate, and volume fields
        that change based on unit system context override or the device's
        temperature_type setting (Celsius or Fahrenheit).

        Args:
            field_name: Name of the field to get the unit for

        Returns:
            Unit string (e.g., " °C", " LPM", " L") or empty if field not found
        """
        model_fields = self.__class__.model_fields
        lookup_name = (
            field_name if field_name in model_fields else f"{field_name}_raw"
        )
        if lookup_name not in model_fields:
            return ""

        field_info = model_fields[lookup_name]
        if not hasattr(field_info, "json_schema_extra"):
            return ""

        extra = field_info.json_schema_extra
        if not isinstance(extra, dict):
            return ""

        is_celsius = self._is_celsius()

        device_class = extra.get("device_class")

        # Handle temperature units
        if device_class == "temperature":
            return " °C" if is_celsius else " °F"

        # Handle flow rate units
        if device_class == "flow_rate":
            return " LPM" if is_celsius else " GPM"

        # Handle volume units
        if device_class == "water":
            return " L" if is_celsius else " gal"

        # Fallback to static unit_of_measurement if present
        if "unit_of_measurement" in extra:
            unit_val = extra["unit_of_measurement"]
            unit: str = str(unit_val) if unit_val is not None else ""
            return f" {unit}" if unit else ""

        return ""
