"""Plain-text, CSV and JSON renderers for CLI output.

Data-shaping (which fields, labels, units, ordering, aggregation) lives in
:mod:`.presentation`; this module only renders those neutral structures as
plain text / CSV / JSON. The Rich renderer in :mod:`.rich_output` consumes
the same neutral structures.
"""

import csv
import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from nwp500 import DeviceStatus

from .presentation import (
    EnergyTotals,
    build_daily_energy_report,
    build_device_info_rows,
    build_device_status_rows,
    build_energy_report,
    format_month_label,
)
from .rich_output import get_formatter

_logger = logging.getLogger(__name__)


def _format_total_summary(totals: EnergyTotals, width: int) -> list[str]:
    """Render the shared energy 'TOTAL SUMMARY' block as plain-text lines."""
    return [
        "TOTAL SUMMARY",
        "-" * width,
        f"Total Energy Used:        {totals.total_usage_wh:,} Wh ({totals.total_usage_wh / 1000:.2f} kWh)",  # noqa: E501
        f"  Heat Pump:              {totals.heat_pump_usage_wh:,} Wh ({totals.heat_pump_percentage:.1f}%)",  # noqa: E501
        f"  Heat Element:           {totals.heat_element_usage_wh:,} Wh ({totals.heat_element_percentage:.1f}%)",  # noqa: E501
        f"Total Time Running:       {totals.total_time_hours} hours",
        f"  Heat Pump:              {totals.heat_pump_time_hours} hours",
        f"  Heat Element:           {totals.heat_element_time_hours} hours",
    ]


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
    lines: list[str] = []

    report = build_energy_report(energy_response)

    # Add header
    lines.append("=" * 90)
    lines.append("ENERGY USAGE REPORT")
    lines.append("=" * 90)

    # Total summary
    lines.append("")
    lines.extend(_format_total_summary(report.totals, 90))

    # Monthly data
    if report.months:
        lines.append("")
        lines.append("MONTHLY BREAKDOWN")
        lines.append("-" * 90)
        lines.append(
            f"{'Month':<20} {'Energy (Wh)':<18} {'HP (Wh)':<15} {'HE (Wh)':<15} {'HP Time (h)':<15}"  # noqa: E501
        )
        lines.append("-" * 90)

        lines.extend(
            f"{month.label:<20} {month.total_wh:>16,} {month.heat_pump_wh:>13,} {month.heat_element_wh:>13,} {month.heat_pump_time:>13}"  # noqa: E501
            for month in report.months
        )

    lines.append("=" * 90)
    return "\n".join(lines)


def _month_rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    """Adapt neutral monthly rows to the dict shape the Rich table consumes."""
    return [
        {
            "month_str": row.label,
            "total_kwh": row.total_wh / 1000,
            "hp_kwh": row.heat_pump_wh / 1000,
            "hp_pct": row.heat_pump_percentage,
            "he_kwh": row.heat_element_wh / 1000,
            "he_pct": row.heat_element_percentage,
        }
        for row in rows
    ]


def _day_rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    """Adapt neutral daily rows to the dict shape the Rich table consumes."""
    return [
        {
            "day": int(row.label),
            "total_kwh": row.total_wh / 1000,
            "hp_kwh": row.heat_pump_wh / 1000,
            "hp_pct": row.heat_pump_percentage,
            "he_kwh": row.heat_element_wh / 1000,
            "he_pct": row.heat_element_percentage,
        }
        for row in rows
    ]


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
    report = build_energy_report(energy_response)
    if report.months:
        formatter = get_formatter()
        formatter.print_energy_table(_month_rows_to_dicts(report.months))


def format_daily_energy_usage(
    energy_response: Any, year: int, month: int
) -> str:
    """
    Format daily energy usage for a specific month as a human-readable table.

    Args:
        energy_response: EnergyUsageResponse object
        year: Year to filter for (e.g., 2025)
        month: Month to filter for (1-12)

    Returns:
        Formatted string with daily energy usage data in tabular form
    """
    lines: list[str] = []

    report = build_daily_energy_report(energy_response, year, month)

    # Add header
    lines.append("=" * 100)
    month_str = format_month_label(year, month)
    lines.append(f"DAILY ENERGY USAGE - {month_str}")
    lines.append("=" * 100)

    if report is None:
        lines.append("No data available for this month")
        lines.append("=" * 100)
        return "\n".join(lines)

    # Total summary for the month
    lines.append("")
    lines.extend(_format_total_summary(report.totals, 100))

    # Daily breakdown
    lines.append("")
    lines.append("DAILY BREAKDOWN")
    lines.append("-" * 100)
    lines.append(
        f"{'Day':<5} {'Energy (Wh)':<18} {'HP (Wh)':<15} {'HE (Wh)':<15} {'HP Time':<12} {'HE Time':<12}"  # noqa: E501
    )
    lines.append("-" * 100)

    lines.extend(
        f"{int(day.label):<5} {day.total_wh:>16,} {day.heat_pump_wh:>13,} {day.heat_element_wh:>13,} {day.heat_pump_time:>10} {day.heat_element_time:>10}"  # noqa: E501
        for day in report.days
    )

    lines.append("=" * 100)
    return "\n".join(lines)


def print_daily_energy_usage(
    energy_response: Any, year: int, month: int
) -> None:
    """
    Print daily energy usage data in human-readable tabular format.

    Uses Rich formatting when available, falls back to plain text otherwise.

    Args:
        energy_response: EnergyUsageResponse object
        year: Year to filter for (e.g., 2025)
        month: Month to filter for (1-12)
    """
    # First, print the plain text summary (always works)
    print(format_daily_energy_usage(energy_response, year, month))

    # Also prepare and print rich table if available
    report = build_daily_energy_report(energy_response, year, month)
    if report is None:
        return

    formatter = get_formatter()
    formatter.print_daily_energy_table(
        _day_rows_to_dicts(report.days), year, month
    )


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

        # Add a timestamp to the beginning of the data (timezone-aware,
        # in the local timezone)
        status_dict["timestamp"] = datetime.now().astimezone().isoformat()

        # Check if file exists to determine if we need to write the header
        file_exists = Path(file_path).exists()

        with Path(file_path).open("a", newline="") as csvfile:
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
    formatter = get_formatter()
    formatter.print_status_table(build_device_status_rows(device_status))


def print_device_info(device_feature: Any) -> None:
    """
    Print device information with aligned columns and dynamic width calculation.

    Args:
        device_feature: DeviceFeature object
    """
    formatter = get_formatter()
    formatter.print_status_table(build_device_info_rows(device_feature))
