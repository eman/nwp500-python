"""Protocol-specific converters for Navien device communication.

This module handles conversion of device-specific data formats to Python types.
The Navien device uses non-standard representations for boolean and numeric
values.

See docs/protocol/quick_reference.rst for comprehensive protocol details.
"""

from collections.abc import Callable
from typing import Any

from pydantic import ValidationInfo, ValidatorFunctionWrapHandler

from .enums import TemperatureType
from .temperature import DeciCelsius, HalfCelsius

__all__ = [
    "device_bool_to_python",
    "device_bool_from_python",
    "tou_override_to_python",
    "div_10",
    "enum_validator",
    "str_enum_validator",
    "half_celsius_to_preferred",
    "deci_celsius_to_preferred",
    "flow_rate_to_preferred",
]


def device_bool_to_python(value: Any) -> bool:
    """Convert device boolean representation to Python bool.

    Device protocol uses: 1 = OFF/False, 2 = ON/True

    This design (using 1 and 2 instead of 0 and 1) is likely due to:
    - 0 being reserved for null/uninitialized state
    - 1 representing "off" in legacy firmware
    - 2 representing "on" state

    Args:
        value: Device value (typically 1 or 2).

    Returns:
        Python boolean (1→False, 2→True).

    Example:
        >>> device_bool_to_python(2)
        True
        >>> device_bool_to_python(1)
        False
    """
    return bool(value == 2)


def device_bool_from_python(value: bool) -> int:
    """Convert Python bool to device boolean representation.

    Args:
        value: Python boolean.

    Returns:
        Device value (True→2, False→1).

    Example:
        >>> device_bool_from_python(True)
        2
        >>> device_bool_from_python(False)
        1
    """
    return 2 if value else 1


def tou_override_to_python(value: Any) -> bool:
    """Convert TOU override status to Python bool.

    Device representation: 1 = Override Active, 2 = Override Inactive

    Args:
        value: Device TOU override status value.

    Returns:
        Python boolean.

    Example:
        >>> tou_override_to_python(1)
        True
        >>> tou_override_to_python(2)
        False
    """
    return bool(value == 1)


def div_10(value: Any) -> float:
    """Divide numeric value by 10.0.

    Used for fields that need 0.1 precision conversion.

    Args:
        value: Numeric value to divide.

    Returns:
        Value divided by 10.0.

    Example:
        >>> div_10(150)
        15.0
        >>> div_10(25.5)
        2.55
    """
    if isinstance(value, (int, float)):
        return float(value) / 10.0
    return float(value)


def enum_validator(enum_class: type[Any]) -> Callable[[Any], Any]:
    """Create a validator for converting int/value to Enum.

    Args:
        enum_class: The Enum class to validate against.

    Returns:
        A validator function compatible with Pydantic BeforeValidator.

    Example:
        >>> from enum import Enum
        >>> class Color(Enum):
        ...     RED = 1
        ...     BLUE = 2
        >>> validator = enum_validator(Color)
        >>> validator(1)
        <Color.RED: 1>
    """

    def validate(value: Any) -> Any:
        """Validate and convert value to enum."""
        if isinstance(value, enum_class):
            return value
        if isinstance(value, int):
            return enum_class(value)
        return enum_class(int(value))

    return validate


def str_enum_validator(enum_class: type[Any]) -> Callable[[Any], Any]:
    """Create a validator for converting string to str-based Enum.

    Args:
        enum_class: The str Enum class to validate against.

    Returns:
        A validator function compatible with Pydantic BeforeValidator.

    Example:
        >>> from enum import Enum
        >>> class Status(str, Enum):
        ...     ACTIVE = "A"
        ...     INACTIVE = "I"
        >>> validator = str_enum_validator(Status)
        >>> validator("A")
        <Status.ACTIVE: 'A'>
    """

    def validate(value: Any) -> Any:
        """Validate and convert value to enum."""
        if isinstance(value, enum_class):
            return value
        if isinstance(value, str):
            return enum_class(value)
        return enum_class(str(value))

    return validate


def _get_temperature_preference(info: ValidationInfo) -> bool:
    """Determine if Celsius is preferred based on validation context.

    Checks 'temperature_type' or 'temperatureType' in the validation data.

    Args:
        info: Pydantic ValidationInfo context.

    Returns:
        True if Celsius is preferred, False otherwise (defaults to Fahrenheit).
    """
    if not info.data:
        return False

    temp_type = info.data.get("temperature_type")
    
    if temp_type is None:
        # Try looking for the alias if model is not populating by name
        temp_type = info.data.get("temperatureType")

    if temp_type is None:
        return False

    # Handle both raw int values and Enum instances
    if isinstance(temp_type, TemperatureType):
        return temp_type == TemperatureType.CELSIUS

    try:
        return int(temp_type) == TemperatureType.CELSIUS
    except (ValueError, TypeError):
        return False


def half_celsius_to_preferred(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> float:
    """Convert half-degrees Celsius to preferred unit (C or F).

    Args:
        value: Raw device value in half-Celsius format.
        handler: Pydantic next validator handler (unused for simple conversion).
        info: Pydantic validation context containing sibling fields.

    Returns:
        Temperature in preferred unit.
    """
    is_celsius = _get_temperature_preference(info)
    if isinstance(value, (int, float)):
        return HalfCelsius(value).to_preferred(is_celsius)
    return float(value)


def deci_celsius_to_preferred(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> float:
    """Convert decicelsius to preferred unit (C or F).

    Args:
        value: Raw device value in decicelsius format.
        handler: Pydantic next validator handler (unused for simple conversion).
        info: Pydantic validation context containing sibling fields.

    Returns:
        Temperature in preferred unit.
    """
    is_celsius = _get_temperature_preference(info)
    if isinstance(value, (int, float)):
        return DeciCelsius(value).to_preferred(is_celsius)
    return float(value)


def flow_rate_to_preferred(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> float:
    """Convert flow rate (LPM * 10) to preferred unit (LPM or GPM).
    
    Raw value from device is LPM * 10 (Metric native).
    - If Metric (Celsius) mode: Return LPM (value / 10.0)
    - If Imperial (Fahrenheit) mode: Convert to GPM (1 LPM ≈ 0.264172 GPM)

    Args:
        value: Raw device value (LPM * 10).
        handler: Pydantic next validator handler (unused).
        info: Pydantic validation context.

    Returns:
        Flow rate in preferred unit (LPM or GPM).
    """
    is_celsius = _get_temperature_preference(info)
    lpm = div_10(value)
    
    if is_celsius:
        return lpm
    
    # Convert LPM to GPM
    return round(lpm * 0.264172, 2)
