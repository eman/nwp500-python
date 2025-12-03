"""
Encoding and decoding utilities for Navien API data structures.

This module provides functions for encoding and decoding bitfields,
prices, and building payload structures for reservations and TOU schedules.
These utilities are used by both the API client and MQTT client.
"""

from collections.abc import Iterable
from numbers import Real
from typing import Union

from .exceptions import ParameterValidationError, RangeValidationError

# Weekday constants
WEEKDAY_ORDER = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]

# Pre-computed lookup tables for performance
WEEKDAY_NAME_TO_BIT = {
    name.lower(): 1 << idx for idx, name in enumerate(WEEKDAY_ORDER)
}
MONTH_TO_BIT = {month: 1 << (month - 1) for month in range(1, 13)}


# ============================================================================
# Week Bitfield Encoding/Decoding
# ============================================================================


def encode_week_bitfield(days: Iterable[Union[str, int]]) -> int:
    """
    Convert a collection of day names or indices into a reservation bitfield.

    Args:
        days: Collection of weekday names (case-insensitive) or indices (0-6 or
        1-7)

    Returns:
        Integer bitfield where each bit represents a day (Sunday=bit 0,
        Monday=bit 1, etc.)

    Raises:
        ParameterValidationError: If day name is unknown/invalid
        RangeValidationError: If day index is out of range (not 0-7)
        TypeError: If day value is neither string nor integer

    Examples:
        >>> encode_week_bitfield(["Monday", "Wednesday", "Friday"])
        42  # 0b101010

        >>> encode_week_bitfield([1, 3, 5])  # 0-indexed
        42

        >>> encode_week_bitfield([0, 6])  # Sunday and Saturday
        65  # 0b1000001
    """
    bitfield = 0
    for value in days:
        if isinstance(value, str):
            key = value.strip().lower()
            if key not in WEEKDAY_NAME_TO_BIT:
                raise ParameterValidationError(
                    f"Unknown weekday: {value}",
                    parameter="weekday",
                    value=value,
                )
            bitfield |= WEEKDAY_NAME_TO_BIT[key]
        elif isinstance(value, int):
            if 0 <= value <= 6:
                bitfield |= 1 << value
            elif 1 <= value <= 7:
                # Support 1-7 indexing (Monday=1, Sunday=7)
                bitfield |= 1 << (value - 1)
            else:
                raise RangeValidationError(
                    "Day index must be between 0-6 or 1-7",
                    field="day_index",
                    value=value,
                    min_value=0,
                    max_value=7,
                )
        else:
            raise TypeError("Weekday values must be strings or integers")
    return bitfield


def decode_week_bitfield(bitfield: int) -> list[str]:
    """
    Decode a reservation bitfield back into a list of weekday names.

    Args:
        bitfield: Integer bitfield where each bit represents a day

    Returns:
        List of weekday names in order (Sunday through Saturday)

    Examples:
        >>> decode_week_bitfield(42)
        ['Monday', 'Wednesday', 'Friday']

        >>> decode_week_bitfield(127)  # All days
        ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
        'Saturday']

        >>> decode_week_bitfield(65)
        ['Sunday', 'Saturday']
    """
    days: list[str] = []
    for idx, name in enumerate(WEEKDAY_ORDER):
        if bitfield & (1 << idx):
            days.append(name)
    return days


# ============================================================================
# Season Bitfield Encoding/Decoding (TOU)
# ============================================================================


def encode_season_bitfield(months: Iterable[int]) -> int:
    """
    Encode a collection of month numbers (1-12) into a TOU season bitfield.

    Args:
        months: Collection of month numbers (1=January, 12=December)

    Returns:
        Integer bitfield where each bit represents a month (January=bit 0, etc.)

    Raises:
        ValueError: If month number is not in range 1-12

    Examples:
        >>> encode_season_bitfield([6, 7, 8])  # Summer: June, July, August
        448  # 0b111000000

        >>> encode_season_bitfield([12, 1, 2])  # Winter: Dec, Jan, Feb
        4099  # 0b1000000000011
    """
    bitfield = 0
    for month in months:
        if month not in MONTH_TO_BIT:
            raise RangeValidationError(
                "Month values must be in the range 1-12",
                field="month",
                value=month,
                min_value=1,
                max_value=12,
            )
        bitfield |= MONTH_TO_BIT[month]
    return bitfield


def decode_season_bitfield(bitfield: int) -> list[int]:
    """
    Decode a TOU season bitfield into the corresponding month numbers.

    Args:
        bitfield: Integer bitfield where each bit represents a month

    Returns:
        Sorted list of month numbers (1-12)

    Examples:
        >>> decode_season_bitfield(448)
        [6, 7, 8]

        >>> decode_season_bitfield(4095)  # All months
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    """
    months: list[int] = []
    for month, mask in MONTH_TO_BIT.items():
        if bitfield & mask:
            months.append(month)
    return sorted(months)


# ============================================================================
# Price Encoding/Decoding
# ============================================================================


def encode_price(value: Real, decimal_point: int) -> int:
    """
    Encode a price into the integer representation expected by the device.

    The device stores prices as integers with a separate decimal point
    indicator.
    For example, $12.34 with decimal_point=2 is stored as 1234.

    Args:
        value: Price value (float or Decimal)
        decimal_point: Number of decimal places (0-10, typically 2-5)

    Returns:
        Integer representation of the price

    Raises:
        RangeValidationError: If decimal_point is not in range 0-10

    Examples:
        >>> encode_price(12.34, 2)
        1234

        >>> encode_price(0.5, 3)
        500

        >>> encode_price(100, 0)
        100
    """
    if not 0 <= decimal_point <= 10:
        raise RangeValidationError(
            "decimal_point must be between 0 and 10",
            field="decimal_point",
            value=decimal_point,
            min_value=0,
            max_value=10,
        )
    scale = 10**decimal_point
    return int(round(float(value) * scale))


def decode_price(value: int, decimal_point: int) -> float:
    """
    Decode an integer price value using the provided decimal point.

    Args:
        value: Integer price value from device
        decimal_point: Number of decimal places (0-10, typically 2-5)

    Returns:
        Floating-point price value

    Raises:
        RangeValidationError: If decimal_point is not in range 0-10

    Examples:
        >>> decode_price(1234, 2)
        12.34

        >>> decode_price(500, 3)
        0.5

        >>> decode_price(100, 0)
        100.0
    """
    if not 0 <= decimal_point <= 10:
        raise RangeValidationError(
            "decimal_point must be between 0 and 10",
            field="decimal_point",
            value=decimal_point,
            min_value=0,
            max_value=10,
        )
    scale = 10**decimal_point
    return value / scale if scale else float(value)


# ============================================================================
# Payload Builders
# ============================================================================


def decode_reservation_hex(hex_string: str) -> list[dict[str, int]]:
    """
    Decode a hex-encoded reservation string into structured reservation entries.

    The reservation data is encoded as 6 bytes per entry:
    - Byte 0: enable (1=enabled, 2=disabled)
    - Byte 1: week bitfield (days of week)
    - Byte 2: hour (0-23)
    - Byte 3: minute (0-59)
    - Byte 4: mode (operation mode ID)
    - Byte 5: param (temperature offset by 20°F)

    Args:
        hex_string: Hexadecimal string representing reservation data

    Returns:
        List of reservation entry dictionaries

    Examples:
        >>> decode_reservation_hex("013e061e0478")
        [{'enable': 1, 'week': 62, 'hour': 6, 'minute': 30, 'mode': 4, 'param':
        120}]
    """
    data = bytes.fromhex(hex_string)
    reservations = []

    # Process 6 bytes at a time
    for i in range(0, len(data), 6):
        chunk = data[i : i + 6]

        # Skip empty entries (all zeros)
        if all(b == 0 for b in chunk):
            continue

        # Ensure we have a full 6-byte entry
        if len(chunk) != 6:
            break

        reservations.append(
            {
                "enable": chunk[0],
                "week": chunk[1],
                "hour": chunk[2],
                "min": chunk[3],
                "mode": chunk[4],
                "param": chunk[5],
            }
        )

    return reservations


def build_reservation_entry(
    *,
    enabled: Union[bool, int],
    days: Iterable[Union[str, int]],
    hour: int,
    minute: int,
    mode_id: int,
    temperature_f: float,
) -> dict[str, int]:
    """
    Build a reservation payload entry matching the documented MQTT format.

    Args:
        enabled: Enable flag (True/False or 1=enabled/2=disabled)
        days: Collection of weekday names or indices
        hour: Hour (0-23)
        minute: Minute (0-59)
        mode_id: DHW operation mode ID (1-6, see DhwOperationSetting)
        temperature_f: Target temperature in Fahrenheit (95-150°F).
            Automatically converted to half-degrees Celsius for the device.

    Returns:
        Dictionary with reservation entry fields

    Raises:
        RangeValidationError: If hour, minute, mode_id, or temperature is out
            of range
        ParameterValidationError: If enabled type is invalid

    Examples:
        >>> build_reservation_entry(
        ...     enabled=True,
        ...     days=["Monday", "Wednesday", "Friday"],
        ...     hour=6,
        ...     minute=30,
        ...     mode_id=3,
        ...     temperature_f=140.0
        ... )
        {'enable': 1, 'week': 42, 'hour': 6, 'min': 30, 'mode': 3, 'param': 120}
    """
    # Import here to avoid circular import
    from .models import fahrenheit_to_half_celsius

    if not 0 <= hour <= 23:
        raise RangeValidationError(
            "hour must be between 0 and 23",
            field="hour",
            value=hour,
            min_value=0,
            max_value=23,
        )
    if not 0 <= minute <= 59:
        raise RangeValidationError(
            "minute must be between 0 and 59",
            field="minute",
            value=minute,
            min_value=0,
            max_value=59,
        )
    if not 1 <= mode_id <= 6:
        raise RangeValidationError(
            "mode_id must be between 1 and 6 (see DhwOperationSetting)",
            field="mode_id",
            value=mode_id,
            min_value=1,
            max_value=6,
        )
    if not 95 <= temperature_f <= 150:
        raise RangeValidationError(
            "temperature_f must be between 95 and 150°F",
            field="temperature_f",
            value=temperature_f,
            min_value=95,
            max_value=150,
        )

    if isinstance(enabled, bool):
        enable_flag = 1 if enabled else 2
    elif enabled in (1, 2):
        enable_flag = int(enabled)
    else:
        raise ParameterValidationError(
            "enabled must be True/False or 1/2",
            parameter="enabled",
            value=enabled,
        )

    week_bitfield = encode_week_bitfield(days)
    param = fahrenheit_to_half_celsius(temperature_f)

    return {
        "enable": enable_flag,
        "week": week_bitfield,
        "hour": hour,
        "min": minute,
        "mode": mode_id,
        "param": param,
    }


def build_tou_period(
    *,
    season_months: Iterable[int],
    week_days: Iterable[Union[str, int]],
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    price_min: Union[int, Real],
    price_max: Union[int, Real],
    decimal_point: int,
) -> dict[str, int]:
    """Build a TOU (Time of Use) period entry.

    Consistent with MQTT command requirements.

    Args:
        season_months: Collection of month numbers (1-12) for this period
        week_days: Collection of weekday names or indices
        start_hour: Starting hour (0-23)
        start_minute: Starting minute (0-59)
        end_hour: Ending hour (0-23)
        end_minute: Ending minute (0-59)
        price_min: Minimum price (float or pre-encoded int)
        price_max: Maximum price (float or pre-encoded int)
        decimal_point: Number of decimal places for prices

    Returns:
        Dictionary with TOU period fields

    Raises:
        ValueError: If any parameter is out of valid range

    Examples:
        >>> build_tou_period(
        ...     season_months=[6, 7, 8],
        ...     week_days=["Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday"],
        ...     start_hour=9,
        ...     start_minute=0,
        ...     end_hour=17,
        ...     end_minute=0,
        ...     price_min=0.10,
        ...     price_max=0.25,
        ...     decimal_point=2
        ... )
        {'season': 448, 'week': 62, 'startHour': 9, 'startMinute': 0, ...}
    """
    # Validate time parameters
    for label, value, upper in (
        ("start_hour", start_hour, 23),
        ("end_hour", end_hour, 23),
    ):
        if not 0 <= value <= upper:
            raise RangeValidationError(
                f"{label} must be between 0 and {upper}",
                field=label,
                value=value,
                min_value=0,
                max_value=upper,
            )

    for label, value in (
        ("start_minute", start_minute),
        ("end_minute", end_minute),
    ):
        if not 0 <= value <= 59:
            raise RangeValidationError(
                f"{label} must be between 0 and 59",
                field=label,
                value=value,
                min_value=0,
                max_value=59,
            )

    # Encode bitfields
    week_bitfield = encode_week_bitfield(week_days)
    season_bitfield = encode_season_bitfield(season_months)

    # Encode prices if they're Real numbers (not already encoded integers)
    if not isinstance(price_min, int):
        encoded_min = encode_price(price_min, decimal_point)
    else:
        encoded_min = price_min

    if not isinstance(price_max, int):
        encoded_max = encode_price(price_max, decimal_point)
    else:
        encoded_max = price_max

    return {
        "season": season_bitfield,
        "week": week_bitfield,
        "startHour": start_hour,
        "startMinute": start_minute,
        "endHour": end_hour,
        "endMinute": end_minute,
        "priceMin": encoded_min,
        "priceMax": encoded_max,
        "decimalPoint": decimal_point,
    }
