from typing import Annotated

from pydantic import BeforeValidator, Field, computed_field

from .._base import NavienBaseModel
from ..converters import device_bool_to_python, enum_validator
from ..enums import (
    DHWControlTypeFlag,
    TemperatureType,
    TempFormulaType,
    UnitType,
    VolumeCode,
)
from ..field_factory import temperature_field
from ..temperature import HalfCelsius
from ..unit_system import get_unit_system

CapabilityFlag = Annotated[bool, BeforeValidator(device_bool_to_python)]
VolumeCodeField = Annotated[
    VolumeCode, BeforeValidator(enum_validator(VolumeCode))
]


class DeviceFeature(NavienBaseModel):
    """Device capabilities, configuration, and firmware info.

    Unit-aware note:
        Temperature computed fields (e.g. ``dhw_temperature_min``,
        ``dhw_temperature_max``, ``recirc_temperature_min``) read the
        *process-wide* unit-system preference via
        :func:`nwp500.unit_system.get_unit_system` at access time, not at
        construction time. Changing the preference with
        :func:`nwp500.unit_system.set_unit_system` therefore affects values
        read from already-constructed instances, and the preference is shared
        across every async task and thread rather than being context-local
        (see issue #103).
    """

    # IMPORTANT: temperature_type must remain the first field so computed
    # temperature properties can fall back to the device's native unit setting.
    temperature_type: TemperatureType = Field(
        default=TemperatureType.FAHRENHEIT,
        description=(
            "Default temperature unit preference - "
            "factory set to Fahrenheit for USA"
        ),
    )

    mac_address: str | None = Field(
        default=None,
        description="MAC address of the origin device",
    )

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

    # Raw temperature limit fields with half-degree Celsius scaling
    dhw_temperature_min_raw: int = temperature_field(
        "Minimum DHW temperature setting - safety and efficiency lower limit",
        alias="dhwTemperatureMin",
    )
    dhw_temperature_max_raw: int = temperature_field(
        "Maximum DHW temperature setting - scald protection upper limit",
        alias="dhwTemperatureMax",
    )
    freeze_protection_temp_min_raw: int = temperature_field(
        "Minimum freeze protection threshold - "
        "factory default activation temperature",
        alias="freezeProtectionTempMin",
    )
    freeze_protection_temp_max_raw: int = temperature_field(
        "Maximum freeze protection threshold - user-adjustable upper limit",
        alias="freezeProtectionTempMax",
    )
    recirc_temperature_min_raw: int = temperature_field(
        "Minimum recirculation temperature setting - "
        "lower limit for recirculation loop temperature control",
        alias="recircTemperatureMin",
    )
    recirc_temperature_max_raw: int = temperature_field(
        "Maximum recirculation temperature setting - "
        "upper limit for recirculation loop temperature control",
        alias="recircTemperatureMax",
    )

    def _is_celsius(self) -> bool:
        """Return True if metric/Celsius units should be used.

        Reads the process-wide unit-system preference at call time and falls
        back to the device's native ``temperature_type`` when no preference is
        set. Every unit-aware computed property routes through this helper, so
        they all reflect the current global preference.
        """
        unit_system = get_unit_system()
        if unit_system is not None:
            return unit_system == "metric"
        return self.temperature_type == TemperatureType.CELSIUS

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dhw_temperature_min(self) -> float:
        return HalfCelsius(self.dhw_temperature_min_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dhw_temperature_max(self) -> float:
        return HalfCelsius(self.dhw_temperature_max_raw).to_preferred(
            self._is_celsius()
        )

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recirc_temperature_min(self) -> float:
        return HalfCelsius(self.recirc_temperature_min_raw).to_preferred(
            self._is_celsius()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recirc_temperature_max(self) -> float:
        return HalfCelsius(self.recirc_temperature_max_raw).to_preferred(
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
