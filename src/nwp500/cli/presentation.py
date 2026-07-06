"""Presentation-neutral intermediate representation for CLI output.

This module owns the *data-shaping* concerns shared by every CLI output
mode (Rich tables, CSV, JSON): which fields are shown, their labels, units,
ordering and value-to-string formatting. Both the CSV/JSON renderer in
:mod:`.output_formatters` and the Rich renderer in :mod:`.rich_output`
consume the neutral structures produced here, so a field or command only
needs to be described once.

The structures are deliberately free of any rendering technology (no colors,
Rich objects or fixed-width layout). Renderers decide how to present them.
"""

from calendar import month_name
from dataclasses import dataclass, field
from typing import Any

from nwp500 import DeviceFeature, DeviceStatus

# A single labeled row within a titled section:
# ``(section, label, value)`` where ``value`` is already formatted to a string.
StatusRow = tuple[str, str, str]


def _format_number(value: Any) -> str:
    """Format number to one decimal place if float, otherwise return as-is."""
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _get_unit_suffix(
    field_name: str,
    model_class: Any = DeviceStatus,
    instance: Any = None,
) -> str:
    """Extract unit suffix from model field metadata.

    For dynamic fields (temperature, flow_rate, water), use the instance's
    get_field_unit() method to get the correct unit based on device preferences.

    Args:
        field_name: Name of the field to get unit for
        model_class: The Pydantic model class (default: DeviceStatus)
        instance: Optional instance of the model for dynamic unit resolution

    Returns:
        Unit string (e.g., "°F", "°C", "GPM", "Wh") or empty string if not found
    """
    # Use instance's method if available for dynamic unit resolution
    if instance and hasattr(instance, "get_field_unit"):
        return instance.get_field_unit(field_name)

    # Fallback to static unit from schema
    if not hasattr(model_class, "model_fields"):
        return ""

    model_fields = model_class.model_fields
    if field_name not in model_fields:
        return ""

    field_info = model_fields[field_name]
    if not hasattr(field_info, "json_schema_extra"):
        return ""

    extra = field_info.json_schema_extra
    if isinstance(extra, dict) and "unit_of_measurement" in extra:
        unit_val = extra["unit_of_measurement"]
        unit: str = unit_val if unit_val is not None else ""
        return f" {unit}" if unit else ""

    return ""


def _add_numeric_item(
    items: list[StatusRow],
    device_status: Any,
    field_name: str,
    category: str,
    label: str,
) -> None:
    """Add a numeric field with unit to items list, extracting unit from model.

    Args:
        items: List to append to
        device_status: DeviceStatus object
        field_name: Name of the field to display
        category: Category section in the output
        label: Display label for the field
    """
    if hasattr(device_status, field_name):
        value = getattr(device_status, field_name)
        unit = _get_unit_suffix(field_name, instance=device_status)
        formatted = f"{_format_number(value)}{unit}"
        items.append((category, label, formatted))


def build_device_status_rows(device_status: Any) -> list[StatusRow]:
    """Build presentation-neutral rows for a device status object.

    Units are automatically extracted from the DeviceStatus model metadata.

    Args:
        device_status: DeviceStatus object

    Returns:
        List of ``(section, label, value)`` rows in display order.
    """
    all_items: list[StatusRow] = []

    # Operation Status
    if hasattr(device_status, "operation_mode"):
        mode = getattr(
            device_status.operation_mode, "name", device_status.operation_mode
        )
        all_items.append(("OPERATION STATUS", "Mode", mode))
    if hasattr(device_status, "operation_busy"):
        all_items.append(
            (
                "OPERATION STATUS",
                "Busy",
                "Yes" if device_status.operation_busy else "No",
            )
        )
    if hasattr(device_status, "current_statenum"):
        all_items.append(
            ("OPERATION STATUS", "State", device_status.current_statenum)
        )
    _add_numeric_item(
        all_items,
        device_status,
        "current_inst_power",
        "OPERATION STATUS",
        "Current Power",
    )

    # Water Temperatures
    _add_numeric_item(
        all_items,
        device_status,
        "dhw_temperature",
        "WATER TEMPERATURES",
        "DHW Current",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "dhw_target_temperature_setting",
        "WATER TEMPERATURES",
        "DHW Target",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "tank_upper_temperature",
        "WATER TEMPERATURES",
        "Tank Upper",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "tank_lower_temperature",
        "WATER TEMPERATURES",
        "Tank Lower",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "current_inlet_temperature",
        "WATER TEMPERATURES",
        "Inlet Temp",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "current_dhw_flow_rate",
        "WATER TEMPERATURES",
        "DHW Flow Rate",
    )

    # Ambient Temperatures
    _add_numeric_item(
        all_items,
        device_status,
        "outside_temperature",
        "AMBIENT TEMPERATURES",
        "Outside",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "ambient_temperature",
        "AMBIENT TEMPERATURES",
        "Ambient",
    )

    # System Temperatures
    _add_numeric_item(
        all_items,
        device_status,
        "discharge_temperature",
        "SYSTEM TEMPERATURES",
        "Discharge",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "suction_temperature",
        "SYSTEM TEMPERATURES",
        "Suction",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "evaporator_temperature",
        "SYSTEM TEMPERATURES",
        "Evaporator",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "target_super_heat",
        "SYSTEM TEMPERATURES",
        "Target SuperHeat",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "current_super_heat",
        "SYSTEM TEMPERATURES",
        "Current SuperHeat",
    )

    # Heat Pump Settings
    _add_numeric_item(
        all_items,
        device_status,
        "hp_upper_on_temp_setting",
        "HEAT PUMP SETTINGS",
        "Upper On",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "hp_upper_on_diff_temp_setting",
        "HEAT PUMP SETTINGS",
        "Upper On Diff",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "hp_upper_off_temp_setting",
        "HEAT PUMP SETTINGS",
        "Upper Off",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "hp_upper_off_diff_temp_setting",
        "HEAT PUMP SETTINGS",
        "Upper Off Diff",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "hp_lower_on_temp_setting",
        "HEAT PUMP SETTINGS",
        "Lower On",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "hp_lower_on_diff_temp_setting",
        "HEAT PUMP SETTINGS",
        "Lower On Diff",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "hp_lower_off_temp_setting",
        "HEAT PUMP SETTINGS",
        "Lower Off",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "hp_lower_off_diff_temp_setting",
        "HEAT PUMP SETTINGS",
        "Lower Off Diff",
    )

    # Heat Element Settings
    _add_numeric_item(
        all_items,
        device_status,
        "he_upper_on_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Upper On",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "he_upper_on_diff_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Upper On Diff",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "he_upper_off_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Upper Off",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "he_upper_off_diff_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Upper Off Diff",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "he_lower_on_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Lower On",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "he_lower_on_diff_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Lower On Diff",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "he_lower_off_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Lower Off",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "he_lower_off_diff_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Lower Off Diff",
    )

    # Power & Energy
    if hasattr(device_status, "wh_total_power_consumption"):
        all_items.append(
            (
                "POWER & ENERGY",
                "Total Consumption",
                f"{_format_number(device_status.wh_total_power_consumption)}Wh",
            )
        )
    if hasattr(device_status, "wh_heat_pump_power"):
        all_items.append(
            (
                "POWER & ENERGY",
                "Heat Pump Power",
                f"{_format_number(device_status.wh_heat_pump_power)}Wh",
            )
        )
    if hasattr(device_status, "wh_electric_heater_power"):
        all_items.append(
            (
                "POWER & ENERGY",
                "Electric Heater Power",
                f"{_format_number(device_status.wh_electric_heater_power)}Wh",
            )
        )
    _add_numeric_item(
        all_items,
        device_status,
        "total_energy_capacity",
        "POWER & ENERGY",
        "Total Capacity",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "available_energy_capacity",
        "POWER & ENERGY",
        "Available Capacity",
    )

    # Fan Control
    _add_numeric_item(
        all_items, device_status, "target_fan_rpm", "FAN CONTROL", "Target RPM"
    )
    _add_numeric_item(
        all_items,
        device_status,
        "current_fan_rpm",
        "FAN CONTROL",
        "Current RPM",
    )
    if hasattr(device_status, "fan_pwm"):
        pwm_pct = f"{_format_number(device_status.fan_pwm)}%"
        all_items.append(("FAN CONTROL", "PWM", pwm_pct))
    _add_numeric_item(
        all_items,
        device_status,
        "cumulated_op_time_eva_fan",
        "FAN CONTROL",
        "Eva Fan Time",
    )

    # Compressor & Valve
    if hasattr(device_status, "mixing_rate"):
        mixing = f"{_format_number(device_status.mixing_rate)}%"
        all_items.append(("COMPRESSOR & VALVE", "Mixing Rate", mixing))
    if hasattr(device_status, "eev_step"):
        eev = f"{_format_number(device_status.eev_step)} steps"
        all_items.append(("COMPRESSOR & VALVE", "EEV Step", eev))
    _add_numeric_item(
        all_items,
        device_status,
        "target_super_heat",
        "COMPRESSOR & VALVE",
        "Target SuperHeat",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "current_super_heat",
        "COMPRESSOR & VALVE",
        "Current SuperHeat",
    )

    # Recirculation
    if hasattr(device_status, "recirc_operation_mode"):
        all_items.append(
            (
                "RECIRCULATION",
                "Operation Mode",
                device_status.recirc_operation_mode,
            )
        )
    if hasattr(device_status, "recirc_pump_operation_status"):
        all_items.append(
            (
                "RECIRCULATION",
                "Pump Status",
                device_status.recirc_pump_operation_status,
            )
        )
    _add_numeric_item(
        all_items,
        device_status,
        "recirc_temperature",
        "RECIRCULATION",
        "Temperature",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "recirc_faucet_temperature",
        "RECIRCULATION",
        "Faucet Temp",
    )

    # Status & Alerts
    if hasattr(device_status, "error_code"):
        all_items.append(
            ("STATUS & ALERTS", "Error Code", device_status.error_code)
        )
    if hasattr(device_status, "sub_error_code"):
        all_items.append(
            ("STATUS & ALERTS", "Sub Error Code", device_status.sub_error_code)
        )
    if hasattr(device_status, "fault_status1"):
        all_items.append(
            ("STATUS & ALERTS", "Fault Status 1", device_status.fault_status1)
        )
    if hasattr(device_status, "fault_status2"):
        all_items.append(
            ("STATUS & ALERTS", "Fault Status 2", device_status.fault_status2)
        )
    if hasattr(device_status, "error_buzzer_use"):
        all_items.append(
            (
                "STATUS & ALERTS",
                "Error Buzzer",
                "Yes" if device_status.error_buzzer_use else "No",
            )
        )

    # Vacation Mode
    _add_numeric_item(
        all_items,
        device_status,
        "vacation_day_setting",
        "VACATION MODE",
        "Days Set",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "vacation_day_elapsed",
        "VACATION MODE",
        "Days Elapsed",
    )

    # Air Filter
    _add_numeric_item(
        all_items,
        device_status,
        "air_filter_alarm_period",
        "AIR FILTER",
        "Alarm Period",
    )
    _add_numeric_item(
        all_items,
        device_status,
        "air_filter_alarm_elapsed",
        "AIR FILTER",
        "Alarm Elapsed",
    )

    # WiFi & Network
    _add_numeric_item(
        all_items, device_status, "wifi_rssi", "WiFi & NETWORK", "RSSI"
    )

    # Demand Response & TOU
    if hasattr(device_status, "dr_event_status"):
        all_items.append(
            (
                "DEMAND RESPONSE & TOU",
                "DR Event Status",
                device_status.dr_event_status,
            )
        )
    _add_numeric_item(
        all_items,
        device_status,
        "dr_override_status",
        "DEMAND RESPONSE & TOU",
        "DR Override Status",
    )
    if hasattr(device_status, "tou_status"):
        all_items.append(
            ("DEMAND RESPONSE & TOU", "TOU Status", device_status.tou_status)
        )
    if hasattr(device_status, "tou_override_status"):
        all_items.append(
            (
                "DEMAND RESPONSE & TOU",
                "TOU Override Status",
                device_status.tou_override_status,
            )
        )

    # Anti-Legionella
    _add_numeric_item(
        all_items,
        device_status,
        "anti_legionella_period",
        "ANTI-LEGIONELLA",
        "Period",
    )
    if hasattr(device_status, "anti_legionella_operation_busy"):
        all_items.append(
            (
                "ANTI-LEGIONELLA",
                "Operation Busy",
                "Yes" if device_status.anti_legionella_operation_busy else "No",
            )
        )

    return all_items


def build_device_info_rows(device_feature: Any) -> list[StatusRow]:
    """Build presentation-neutral rows for a device feature object.

    Args:
        device_feature: DeviceFeature object

    Returns:
        List of ``(section, label, value)`` rows in display order.
    """
    # Serialize to dict to get enum names from model_dump()
    if hasattr(device_feature, "model_dump"):
        device_dict = device_feature.model_dump()
    else:
        device_dict = device_feature

    all_items: list[StatusRow] = []

    # Device Identity
    if "controller_serial_number" in device_dict:
        all_items.append(
            (
                "DEVICE IDENTITY",
                "Serial Number",
                device_dict["controller_serial_number"],
            )
        )
    if "country_code" in device_dict:
        all_items.append(
            ("DEVICE IDENTITY", "Country Code", device_dict["country_code"])
        )
    if "model_type_code" in device_dict:
        all_items.append(
            ("DEVICE IDENTITY", "Model Type", device_dict["model_type_code"])
        )
    if "control_type_code" in device_dict:
        all_items.append(
            (
                "DEVICE IDENTITY",
                "Control Type",
                device_dict["control_type_code"],
            )
        )
    if "volume_code" in device_dict:
        all_items.append(
            ("DEVICE IDENTITY", "Volume Code", device_dict["volume_code"])
        )

    # Firmware Versions
    if "controller_sw_version" in device_dict:
        all_items.append(
            (
                "FIRMWARE VERSIONS",
                "Controller Version",
                f"v{device_dict['controller_sw_version']}",
            )
        )
    if "controller_sw_code" in device_dict:
        all_items.append(
            (
                "FIRMWARE VERSIONS",
                "Controller Code",
                device_dict["controller_sw_code"],
            )
        )
    if "panel_sw_version" in device_dict:
        all_items.append(
            (
                "FIRMWARE VERSIONS",
                "Panel Version",
                f"v{device_dict['panel_sw_version']}",
            )
        )
    if "panel_sw_code" in device_dict:
        all_items.append(
            ("FIRMWARE VERSIONS", "Panel Code", device_dict["panel_sw_code"])
        )
    if "wifi_sw_version" in device_dict:
        all_items.append(
            (
                "FIRMWARE VERSIONS",
                "WiFi Version",
                f"v{device_dict['wifi_sw_version']}",
            )
        )
    if "wifi_sw_code" in device_dict:
        all_items.append(
            ("FIRMWARE VERSIONS", "WiFi Code", device_dict["wifi_sw_code"])
        )
    if (
        hasattr(device_feature, "recirc_sw_version")
        and device_dict["recirc_sw_version"] > 0
    ):
        all_items.append(
            (
                "FIRMWARE VERSIONS",
                "Recirculation Version",
                f"v{device_dict['recirc_sw_version']}",
            )
        )
    if "recirc_model_type_code" in device_dict:
        all_items.append(
            (
                "FIRMWARE VERSIONS",
                "Recirculation Model",
                device_dict["recirc_model_type_code"],
            )
        )

    # Configuration
    if "temperature_type" in device_dict:
        temp_type = getattr(
            device_dict["temperature_type"],
            "name",
            device_dict["temperature_type"],
        )
        all_items.append(("CONFIGURATION", "Temperature Unit", temp_type))
    if "temp_formula_type" in device_dict:
        all_items.append(
            (
                "CONFIGURATION",
                "Temperature Formula",
                device_dict["temp_formula_type"],
            )
        )
    if "dhw_temperature_min" in device_dict:
        unit_suffix = (
            _get_unit_suffix(
                "dhw_temperature_min", DeviceFeature, device_feature
            )
            if hasattr(device_feature, "get_field_unit")
            else " °F"
        )
        all_items.append(
            (
                "CONFIGURATION",
                "DHW Temp Range",
                f"{device_dict['dhw_temperature_min']}{unit_suffix} - {device_dict['dhw_temperature_max']}{unit_suffix}",  # noqa: E501
            )
        )
    if "freeze_protection_temp_min" in device_dict:
        unit_suffix = (
            _get_unit_suffix(
                "freeze_protection_temp_min", DeviceFeature, device_feature
            )
            if hasattr(device_feature, "get_field_unit")
            else " °F"
        )
        all_items.append(
            (
                "CONFIGURATION",
                "Freeze Protection Range",
                f"{device_dict['freeze_protection_temp_min']}{unit_suffix} - {device_dict['freeze_protection_temp_max']}{unit_suffix}",  # noqa: E501
            )
        )
    if "recirc_temperature_min" in device_dict:
        unit_suffix = (
            _get_unit_suffix(
                "recirc_temperature_min", DeviceFeature, device_feature
            )
            if hasattr(device_feature, "get_field_unit")
            else " °F"
        )
        all_items.append(
            (
                "CONFIGURATION",
                "Recirculation Temp Range",
                f"{device_dict['recirc_temperature_min']}{unit_suffix} - {device_dict['recirc_temperature_max']}{unit_suffix}",  # noqa: E501
            )
        )

    # Supported Features
    features_list = [
        ("Power Control", "power_use"),
        ("DHW Control", "dhw_use"),
        ("Heat Pump Mode", "heatpump_use"),
        ("Electric Mode", "electric_use"),
        ("Energy Saver", "energy_saver_use"),
        ("High Demand", "high_demand_use"),
        ("Eco Mode", "eco_use"),
        ("Holiday Mode", "holiday_use"),
        ("Program Reservation", "program_reservation_use"),
        ("Recirculation", "recirculation_use"),
        ("Recirculation Reservation", "recirc_reservation_use"),
        ("Smart Diagnostic", "smart_diagnostic_use"),
        ("WiFi RSSI", "wifi_rssi_use"),
        ("Energy Usage", "energy_usage_use"),
        ("Freeze Protection", "freeze_protection_use"),
        ("Mixing Valve", "mixing_valve_use"),
        ("DR Settings", "dr_setting_use"),
        ("Anti-Legionella", "anti_legionella_setting_use"),
        ("HPWH", "hpwh_use"),
        ("DHW Refill", "dhw_refill_use"),
        ("Title 24", "title24_use"),
    ]

    for label, attr in features_list:
        if hasattr(device_feature, attr):
            value = getattr(device_feature, attr)
            status = "Yes" if value else "No"
            all_items.append(("SUPPORTED FEATURES", label, status))

    return all_items


def format_month_label(year: int, month: int) -> str:
    """Return a display label for a year/month pair."""
    if 1 <= month <= 12:
        return f"{month_name[month]} {year}"
    return f"Month {month} {year}"


@dataclass
class EnergyTotals:
    """Presentation-neutral aggregated energy totals."""

    total_usage_wh: int
    heat_pump_usage_wh: int
    heat_pump_percentage: float
    heat_element_usage_wh: int
    heat_element_percentage: float
    total_time_hours: int
    heat_pump_time_hours: int
    heat_element_time_hours: int


@dataclass
class EnergyPeriodRow:
    """A single aggregated energy period (a month or a day).

    ``label`` identifies the period ("June 2025" for a month, ``"1"`` for a
    day). All usage values are in watt-hours; percentages are of total usage.
    """

    label: str
    total_wh: int
    heat_pump_wh: int
    heat_element_wh: int
    heat_pump_time: int
    heat_element_time: int
    heat_pump_percentage: float
    heat_element_percentage: float


@dataclass
class EnergyReport:
    """Aggregated energy usage grouped by month."""

    totals: EnergyTotals
    months: list[EnergyPeriodRow] = field(default_factory=list)


@dataclass
class DailyEnergyReport:
    """Aggregated daily energy usage for a single month."""

    year: int
    month: int
    totals: EnergyTotals
    days: list[EnergyPeriodRow] = field(default_factory=list)


def _build_totals(total: Any) -> EnergyTotals:
    """Build neutral totals from an EnergyUsageTotal model."""
    return EnergyTotals(
        total_usage_wh=total.total_usage,
        heat_pump_usage_wh=total.heat_pump_usage,
        heat_pump_percentage=total.heat_pump_percentage,
        heat_element_usage_wh=total.heat_element_usage,
        heat_element_percentage=total.heat_element_percentage,
        total_time_hours=total.total_time,
        heat_pump_time_hours=total.heat_pump_time,
        heat_element_time_hours=total.heat_element_time,
    )


def _percentages(hp_wh: int, he_wh: int, total_wh: int) -> tuple[float, float]:
    """Return heat-pump/heat-element share of total usage as percentages."""
    hp_pct = (hp_wh / total_wh * 100) if total_wh > 0 else 0.0
    he_pct = (he_wh / total_wh * 100) if total_wh > 0 else 0.0
    return hp_pct, he_pct


def build_energy_report(energy_response: Any) -> EnergyReport:
    """Aggregate an energy response into neutral monthly rows.

    Args:
        energy_response: EnergyUsageResponse object

    Returns:
        EnergyReport with totals and one row per month.
    """
    months: list[EnergyPeriodRow] = []
    for month_data in energy_response.usage:
        label = format_month_label(month_data.year, month_data.month)
        total_wh = sum(
            d.heat_pump_usage + d.heat_element_usage for d in month_data.data
        )
        hp_wh = sum(d.heat_pump_usage for d in month_data.data)
        he_wh = sum(d.heat_element_usage for d in month_data.data)
        hp_time = sum(d.heat_pump_time for d in month_data.data)
        he_time = sum(d.heat_element_time for d in month_data.data)
        hp_pct, he_pct = _percentages(hp_wh, he_wh, total_wh)
        months.append(
            EnergyPeriodRow(
                label=label,
                total_wh=total_wh,
                heat_pump_wh=hp_wh,
                heat_element_wh=he_wh,
                heat_pump_time=hp_time,
                heat_element_time=he_time,
                heat_pump_percentage=hp_pct,
                heat_element_percentage=he_pct,
            )
        )
    return EnergyReport(
        totals=_build_totals(energy_response.total), months=months
    )


def build_daily_energy_report(
    energy_response: Any, year: int, month: int
) -> DailyEnergyReport | None:
    """Aggregate a single month's daily energy into neutral rows.

    Args:
        energy_response: EnergyUsageResponse object
        year: Year to filter for (e.g., 2025)
        month: Month to filter for (1-12)

    Returns:
        DailyEnergyReport, or ``None`` if the month has no data.
    """
    month_data = energy_response.get_month_data(year, month)
    if not month_data or not month_data.data:
        return None

    days: list[EnergyPeriodRow] = []
    for day_num, day_data in enumerate(month_data.data, start=1):
        total_wh = day_data.total_usage
        hp_wh = day_data.heat_pump_usage
        he_wh = day_data.heat_element_usage
        hp_pct, he_pct = _percentages(hp_wh, he_wh, total_wh)
        days.append(
            EnergyPeriodRow(
                label=str(day_num),
                total_wh=total_wh,
                heat_pump_wh=hp_wh,
                heat_element_wh=he_wh,
                heat_pump_time=day_data.heat_pump_time,
                heat_element_time=day_data.heat_element_time,
                heat_pump_percentage=hp_pct,
                heat_element_percentage=he_pct,
            )
        )
    return DailyEnergyReport(
        year=year,
        month=month,
        totals=_build_totals(energy_response.total),
        days=days,
    )
