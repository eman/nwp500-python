"""Output formatting utilities for CLI (CSV, JSON)."""

import csv
import json
import logging
from calendar import month_name
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from nwp500 import DeviceStatus

from .rich_output import get_formatter

_logger = logging.getLogger(__name__)


def _format_number(value: Any) -> str:
    """Format number to one decimal place if float, otherwise return as-is."""
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _get_unit_suffix(field_name: str, model_class: Any = DeviceStatus) -> str:
    """Extract unit suffix from model field metadata.

    Args:
        field_name: Name of the field to get unit for
        model_class: The Pydantic model class (default: DeviceStatus)

    Returns:
        Unit string (e.g., "°F", "GPM", "Wh") or empty string if not found
    """
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
        unit = extra["unit_of_measurement"]
        return f" {unit}" if unit else ""

    return ""


def _add_numeric_item(
    items: list[tuple[str, str, str]],
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
        unit = _get_unit_suffix(field_name)
        formatted = f"{_format_number(value)}{unit}"
        items.append((category, label, formatted))


def _json_default_serializer(obj: Any) -> Any:
    """Serialize objects not serializable by default json code.

    Note: Enums are handled by model.model_dump() which converts them to names.
    This function handles any remaining non-JSON-serializable types that might
    appear in raw MQTT messages.

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable representation of the object

    Raises:
        TypeError: If object cannot be serialized
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.name  # Fallback for any enums not in model output
    # Handle Pydantic models
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"Type {type(obj)} not serializable")


def format_energy_usage(energy_response: Any) -> str:
    """
    Format energy usage response as a human-readable table.

    Args:
        energy_response: EnergyUsageResponse object

    Returns:
        Formatted string with energy usage data in tabular form
    """
    lines = []

    # Add header
    lines.append("=" * 90)
    lines.append("ENERGY USAGE REPORT")
    lines.append("=" * 90)

    # Total summary
    total = energy_response.total
    total_usage_wh = total.total_usage
    total_time_hours = total.total_time

    lines.append("")
    lines.append("TOTAL SUMMARY")
    lines.append("-" * 90)
    lines.append(
        f"Total Energy Used:        {total_usage_wh:,} Wh ({total_usage_wh / 1000:.2f} kWh)"  # noqa: E501
    )
    lines.append(
        f"  Heat Pump:              {total.heat_pump_usage:,} Wh ({total.heat_pump_percentage:.1f}%)"  # noqa: E501
    )
    lines.append(
        f"  Heat Element:           {total.heat_element_usage:,} Wh ({total.heat_element_percentage:.1f}%)"  # noqa: E501
    )
    lines.append(f"Total Time Running:       {total_time_hours} hours")
    lines.append(f"  Heat Pump:              {total.heat_pump_time} hours")
    lines.append(f"  Heat Element:           {total.heat_element_time} hours")

    # Monthly data
    if energy_response.usage:
        lines.append("")
        lines.append("MONTHLY BREAKDOWN")
        lines.append("-" * 90)
        lines.append(
            f"{'Month':<20} {'Energy (Wh)':<18} {'HP (Wh)':<15} {'HE (Wh)':<15} {'HP Time (h)':<15}"  # noqa: E501
        )
        lines.append("-" * 90)

        for month_data in energy_response.usage:
            month_name_str = (
                f"{month_name[month_data.month]} {month_data.year}"
                if 1 <= month_data.month <= 12
                else f"Month {month_data.month} {month_data.year}"
            )
            total_wh = sum(
                d.heat_pump_usage + d.heat_element_usage
                for d in month_data.data
            )
            hp_wh = sum(d.heat_pump_usage for d in month_data.data)
            he_wh = sum(d.heat_element_usage for d in month_data.data)
            hp_time = sum(d.heat_pump_time for d in month_data.data)

            lines.append(
                f"{month_name_str:<20} {total_wh:>16,} {hp_wh:>13,} {he_wh:>13,} {hp_time:>13}"  # noqa: E501
            )

    lines.append("=" * 90)
    return "\n".join(lines)


def print_energy_usage(energy_response: Any) -> None:
    """
    Print energy usage data in human-readable tabular format.

    Uses Rich formatting when available, falls back to plain text otherwise.

    Args:
        energy_response: EnergyUsageResponse object
    """
    # First, print the plain text summary (always works)
    print(format_energy_usage(energy_response))

    # Also prepare and print rich table if available
    months_data = []

    if energy_response.usage:
        for month_data in energy_response.usage:
            month_name_str = (
                f"{month_name[month_data.month]} {month_data.year}"
                if 1 <= month_data.month <= 12
                else f"Month {month_data.month} {month_data.year}"
            )
            total_wh = sum(
                d.heat_pump_usage + d.heat_element_usage
                for d in month_data.data
            )
            hp_wh = sum(d.heat_pump_usage for d in month_data.data)
            he_wh = sum(d.heat_element_usage for d in month_data.data)
            hp_pct = (hp_wh / total_wh * 100) if total_wh > 0 else 0
            he_pct = (he_wh / total_wh * 100) if total_wh > 0 else 0

            months_data.append(
                {
                    "month_str": month_name_str,
                    "total_kwh": total_wh / 1000,
                    "hp_kwh": hp_wh / 1000,
                    "hp_pct": hp_pct,
                    "he_kwh": he_wh / 1000,
                    "he_pct": he_pct,
                }
            )

        # Print rich energy table if available
        formatter = get_formatter()
        formatter.print_energy_table(months_data)


def write_status_to_csv(file_path: str, status: DeviceStatus) -> None:
    """
    Append device status to a CSV file.

    Args:
        file_path: Path to the CSV file
        status: DeviceStatus object to write
    """
    try:
        # Convert status to dict (enums are already converted to names)
        status_dict = status.model_dump()

        # Add a timestamp to the beginning of the data
        status_dict["timestamp"] = datetime.now().isoformat()

        # Check if file exists to determine if we need to write the header
        file_exists = Path(file_path).exists()

        with open(file_path, "a", newline="") as csvfile:
            # Get the field names from the dict keys
            fieldnames = list(status_dict.keys())
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            # Write header only if this is a new file
            if not file_exists:
                writer.writeheader()

            writer.writerow(status_dict)

        _logger.debug(f"Status written to {file_path}")

    except OSError as e:
        _logger.error(f"Failed to write to CSV: {e}")


def format_json_output(data: Any, indent: int = 2) -> str:
    """
    Format data as JSON string with custom serialization.

    Args:
        data: Data to format
        indent: Number of spaces for indentation (default: 2)

    Returns:
        JSON-formatted string
    """
    return json.dumps(data, indent=indent, default=_json_default_serializer)


def print_json(data: Any, indent: int = 2) -> None:
    """
    Print data as formatted JSON with optional syntax highlighting.

    Uses Rich highlighting when available, falls back to plain JSON otherwise.

    Args:
        data: Data to print
        indent: Number of spaces for indentation (default: 2)
    """
    json_str = format_json_output(data, indent)
    formatter = get_formatter()
    formatter.print_json_highlighted(json.loads(json_str))


def print_device_status(device_status: Any) -> None:
    """
    Print device status with aligned columns and dynamic width calculation.

    Units are automatically extracted from the DeviceStatus model metadata.

    Args:
        device_status: DeviceStatus object
    """
    # Collect all items with their categories
    all_items = []

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
        "hp_upper_off_temp_setting",
        "HEAT PUMP SETTINGS",
        "Upper Off",
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
        "hp_lower_off_temp_setting",
        "HEAT PUMP SETTINGS",
        "Lower Off",
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
        "he_upper_off_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Upper Off",
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
        "he_lower_off_temp_setting",
        "HEAT ELEMENT SETTINGS",
        "Lower Off",
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

    # Calculate widths dynamically
    max_label_len = max((len(label) for _, label, _ in all_items), default=20)
    max_value_len = max(
        (len(str(value)) for _, _, value in all_items), default=20
    )
    _line_width = max_label_len + max_value_len + 4  # +4 for padding

    # Use rich formatter for output
    formatter = get_formatter()
    formatter.print_status_table(all_items)


def print_device_info(device_feature: Any) -> None:
    """
    Print device information with aligned columns and dynamic width calculation.

    Args:
        device_feature: DeviceFeature object
    """
    # Serialize to dict to get enum names from model_dump()
    if hasattr(device_feature, "model_dump"):
        device_dict = device_feature.model_dump()
    else:
        device_dict = device_feature

    # Collect all items with their categories
    all_items = []

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
        all_items.append(
            (
                "CONFIGURATION",
                "DHW Temp Range",
                f"{device_dict['dhw_temperature_min']}°F - {device_dict['dhw_temperature_max']}°F",  # noqa: E501
            )
        )
    if "freeze_protection_temp_min" in device_dict:
        all_items.append(
            (
                "CONFIGURATION",
                "Freeze Protection Range",
                f"{device_dict['freeze_protection_temp_min']}°F - {device_dict['freeze_protection_temp_max']}°F",  # noqa: E501
            )
        )
    if "recirc_temperature_min" in device_dict:
        all_items.append(
            (
                "CONFIGURATION",
                "Recirculation Temp Range",
                f"{device_dict['recirc_temperature_min']}°F - {device_dict['recirc_temperature_max']}°F",  # noqa: E501
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

    # Calculate widths dynamically
    max_label_len = max((len(label) for _, label, _ in all_items), default=20)
    max_value_len = max(
        (len(str(value)) for _, _, value in all_items), default=20
    )
    _line_width = max_label_len + max_value_len + 4  # +4 for padding

    # Use rich formatter for output
    formatter = get_formatter()
    formatter.print_status_table(all_items)
