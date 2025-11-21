"""Output formatting utilities for CLI (CSV, JSON)."""

import csv
import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from nwp500 import DeviceStatus

_logger = logging.getLogger(__name__)


def _json_default_serializer(obj: Any) -> Any:
    """Serialize objects not serializable by default json code.

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable representation of the object

    Raises:
        TypeError: If object cannot be serialized
    """
    if isinstance(obj, Enum):
        return obj.name
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def write_status_to_csv(file_path: str, status: DeviceStatus) -> None:
    """
    Append device status to a CSV file.

    Args:
        file_path: Path to the CSV file
        status: DeviceStatus object to write
    """
    try:
        # Convert the entire dataclass to a dictionary to capture all fields
        status_dict = status.model_dump()

        # Add a timestamp to the beginning of the data
        status_dict["timestamp"] = datetime.now().isoformat()

        # Convert Enum values to their names
        for key, value in status_dict.items():
            if isinstance(value, Enum):
                status_dict[key] = value.name

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
    Print data as formatted JSON.

    Args:
        data: Data to print
        indent: Number of spaces for indentation (default: 2)
    """
    print(format_json_output(data, indent))
