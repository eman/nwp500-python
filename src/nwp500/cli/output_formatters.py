"""CSV and JSON renderers plus human-output dispatch for the CLI.

Data-shaping (which fields, labels, units, ordering, aggregation) lives in
:mod:`.presentation`; human-readable rendering is delegated to the Rich
renderer in :mod:`.rich_output`, which consumes the same neutral structures.
This module additionally handles the genuinely different CSV and JSON outputs.
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
    build_daily_energy_report,
    build_device_info_rows,
    build_device_status_rows,
    build_energy_report,
)
from .rich_output import get_formatter

_logger = logging.getLogger(__name__)


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


def print_energy_usage(energy_response: Any) -> None:
    """Print energy usage data (summary + monthly breakdown) via Rich.

    Args:
        energy_response: EnergyUsageResponse object
    """
    report = build_energy_report(energy_response)
    get_formatter().print_energy_table(report)


def print_daily_energy_usage(
    energy_response: Any, year: int, month: int
) -> None:
    """Print daily energy usage for a specific month via Rich.

    Args:
        energy_response: EnergyUsageResponse object
        year: Year to filter for (e.g., 2025)
        month: Month to filter for (1-12)
    """
    report = build_daily_energy_report(energy_response, year, month)
    formatter = get_formatter()
    if report is None:
        formatter.print_info(
            f"No daily energy data available for {month}/{year}"
        )
        return
    formatter.print_daily_energy_table(report)


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
