"""Protocol-specific converters for Navien device communication.

This module handles conversion of device-specific data formats to Python types.
The Navien device uses non-standard representations for boolean and numeric
values.

See docs/protocol/quick_reference.rst for comprehensive protocol details.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

from pydantic import ValidationInfo, ValidatorFunctionWrapHandler

from .enums import TemperatureType, TempFormulaType
from .temperature import DeciCelsius, DeciCelsiusDelta, HalfCelsius, RawCelsius
from .unit_system import get_unit_system

_logger = logging.getLogger(__name__)

__all__ = [
    "device_bool_to_python",
    "device_bool_from_python",
    "tou_override_to_python",
    "div_10",
    "mul_10",
    "enum_validator",
    "str_enum_validator",
    "half_celsius_to_preferred",
    "deci_celsius_to_preferred",
    "raw_celsius_to_preferred",
    "flow_rate_to_preferred",
    "volume_to_preferred",
    "div_10_celsius_to_preferred",
    "div_10_celsius_delta_to_preferred",
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
    return float(value) / 10.0


def mul_10(value: Any) -> float:
    """Multiply numeric value by 10.0.

    Used for energy capacity fields where the device reports in 10Wh units,
    but we want to store standard Wh.

    Args:
        value: Numeric value to multiply.

    Returns:
        Value multiplied by 10.0.

    Example:
        >>> mul_10(150)
        1500.0
        >>> mul_10(25.5)
        255.0
    """
    if isinstance(value, (int, float)):
        return float(value) * 10.0
    return float(value) * 10.0


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
    """Determine if Celsius is preferred based on unit system context.

    Checks for an explicit unit system override from context first, then falls
    back to 'temperature_type' or 'temperatureType' in the validation data.

    Args:
        info: Pydantic ValidationInfo context.

    Returns:
        True if Celsius is preferred, False otherwise (defaults to Fahrenheit).
    """
    # Check if unit system override is set in context
    unit_system = get_unit_system()
    if unit_system is not None:
        is_celsius = unit_system == "metric"
        unit_str = "Celsius" if is_celsius else "Fahrenheit"
        _logger.debug(
            f"Using explicit unit system override from context: {unit_system}, "
            f"using {unit_str}"
        )
        return is_celsius

    # Fall back to device's temperature_type setting
    if not info.data:
        _logger.debug("No validation data available, defaulting to Fahrenheit")
        return False

    temp_type = info.data.get("temperature_type")

    if temp_type is None:
        # Try looking for the alias if model is not populating by name
        temp_type = info.data.get("temperatureType")

    if temp_type is None:
        _logger.debug(
            "temperature_type not found in validation data, "
            "defaulting to Fahrenheit"
        )
        return False

    # Handle both raw int values and Enum instances
    match temp_type:
        case TemperatureType.CELSIUS:
            _logger.debug(
                f"Detected temperature_type from Enum: {temp_type.name}, "
                "using Celsius"
            )
            return True
        case TemperatureType.FAHRENHEIT:
            _logger.debug(
                f"Detected temperature_type from Enum: {temp_type.name}, "
                "using Fahrenheit"
            )
            return False
        case int():
            try:
                is_celsius = int(temp_type) == TemperatureType.CELSIUS.value
                unit_str = "Celsius" if is_celsius else "Fahrenheit"
                _logger.debug(
                    f"Detected temperature_type from int: {temp_type}, "
                    f"using {unit_str}"
                )
                return is_celsius
            except (ValueError, TypeError) as e:
                msg = f"Could not parse temperature_type: {e}"
                _logger.warning(f"{msg}, defaulting to Fahrenheit")
                return False
        case _:
            _logger.warning(
                "Could not parse temperature_type, defaulting to Fahrenheit"
            )
            return False


def half_celsius_to_preferred(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> float:
    """Convert half-degrees Celsius to preferred unit (C or F).

    Uses WrapValidator instead of BeforeValidator to access ValidationInfo.data,
    which contains sibling fields needed to determine the device's temperature
    preference (Celsius or Fahrenheit).

    Args:
        value: Raw device value in half-degrees Celsius format.
        handler: Pydantic next validator handler. Not invoked as we bypass the
            validation chain to directly convert using the device's temperature
            preference. WrapValidator is required for access to ValidationInfo.
        info: Pydantic validation context containing sibling fields, used to
            retrieve the device's temperature_type preference.

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

    Uses WrapValidator instead of BeforeValidator to access ValidationInfo.data,
    which contains sibling fields needed to determine the device's temperature
    preference (Celsius or Fahrenheit).

    Args:
        value: Raw device value in decicelsius format (0.1 °C per unit).
        handler: Pydantic next validator handler. Not invoked as we bypass the
            validation chain to directly convert using the device's temperature
            preference. WrapValidator is required for access to ValidationInfo.
        info: Pydantic validation context containing sibling fields, used to
            retrieve the device's temperature_type preference.

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

    Uses WrapValidator instead of BeforeValidator to access ValidationInfo.data,
    which contains sibling fields needed to determine the device's temperature
    preference (Celsius or Fahrenheit), which determines the flow rate unit.

    Args:
        value: Raw device value (LPM * 10).
        handler: Pydantic next validator handler. Not invoked as we bypass the
            validation chain to directly convert using the device's temperature
            preference. WrapValidator is required for access to ValidationInfo.
        info: Pydantic validation context containing sibling fields, used to
            retrieve the device's temperature_type preference.

    Returns:
        Flow rate in preferred unit (LPM or GPM).
    """
    is_celsius = _get_temperature_preference(info)
    lpm = div_10(value)

    if is_celsius:
        return lpm

    # Convert LPM to GPM
    return round(lpm * 0.264172, 2)


def volume_to_preferred(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> float:
    """Convert volume (Liters) to preferred unit (Liters or Gallons).

    Raw value from device is assumed to be in Liters (Metric native).
    - If Metric (Celsius) mode: Return Liters
    - If Imperial (Fahrenheit) mode: Convert to Gallons (1 L ≈ 0.264172 Gal)

    Uses WrapValidator instead of BeforeValidator to access ValidationInfo.data,
    which contains sibling fields needed to determine the device's temperature
    preference (Celsius or Fahrenheit), which determines the volume unit.

    Args:
        value: Raw device value in Liters.
        handler: Pydantic next validator handler. Not invoked as we bypass the
            validation chain to directly convert using the device's temperature
            preference. WrapValidator is required for access to ValidationInfo.
        info: Pydantic validation context containing sibling fields, used to
            retrieve the device's temperature_type preference.

    Returns:
        Volume in preferred unit.
    """
    is_celsius = _get_temperature_preference(info)

    # Handle incoming value
    if isinstance(value, (int, float)):
        liters = float(value)
    else:
        try:
            liters = float(value)
        except (ValueError, TypeError):
            return 0.0

    if is_celsius:
        return liters

    # Convert Liters to Gallons
    return round(liters * 0.264172, 2)


def raw_celsius_to_preferred(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> float:
    """Convert raw halves-of-Celsius to preferred unit (C or F).

    Raw device values are in halves of Celsius (0.5°C precision).
    Used for outdoor/ambient temperature measurements.
    - If Metric (Celsius) mode: Return Celsius (value / 2.0)
    - If Imperial (Fahrenheit) mode: Convert to Fahrenheit using
      formula-specific rounding based on temp_formula_type.

    Uses WrapValidator instead of BeforeValidator to access ValidationInfo.data,
    which contains sibling fields needed to determine the device's temperature
    preference (Celsius or Fahrenheit) and the temperature formula type.

    Args:
        value: Raw device value (halves of Celsius).
        handler: Pydantic next validator handler. Not invoked as we bypass the
            validation chain to directly convert using the device's temperature
            preference. WrapValidator is required for access to ValidationInfo.
        info: Pydantic validation context containing sibling fields, used to
            retrieve the device's temperature_type preference and formula type.

    Returns:
        Temperature in preferred unit (Celsius or Fahrenheit).
    """
    is_celsius = _get_temperature_preference(info)

    if isinstance(value, (int, float)):
        raw_temp = RawCelsius(value)
    else:
        try:
            raw_temp = RawCelsius(float(value))
        except (ValueError, TypeError):
            return 0.0

    if is_celsius:
        return raw_temp.to_celsius()

    # For Fahrenheit, check if temp_formula_type is available
    formula_type = TempFormulaType.STANDARD  # Default to standard rounding
    if info.data:
        temp_formula = info.data.get("temp_formula_type")
        if temp_formula is not None:
            with contextlib.suppress(ValueError, TypeError):
                # Convert to TempFormulaType enum
                if isinstance(temp_formula, TempFormulaType):
                    formula_type = temp_formula
                else:
                    formula_type = TempFormulaType(int(temp_formula))

    return raw_temp.to_fahrenheit_with_formula(formula_type)


def div_10_celsius_to_preferred(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> float:
    """Convert decicelsius value (raw / 10) to preferred unit (C or F).

    Raw device values are in tenths of Celsius (0.1°C per unit).
    - If Metric (Celsius) mode: Return Celsius (value / 10.0)
    - If Imperial (Fahrenheit) mode: Convert to Fahrenheit

    Uses WrapValidator instead of BeforeValidator to access ValidationInfo.data,
    which contains sibling fields needed to determine the device's temperature
    preference (Celsius or Fahrenheit).

    Args:
        value: Raw device value (tenths of Celsius).
        handler: Pydantic next validator handler. Not invoked as we bypass the
            validation chain to directly convert using the device's temperature
            preference. WrapValidator is required for access to ValidationInfo.
        info: Pydantic validation context containing sibling fields, used to
            retrieve the device's temperature_type preference.

    Returns:
        Temperature in preferred unit (Celsius or Fahrenheit).
    """
    is_celsius = _get_temperature_preference(info)

    if isinstance(value, (int, float)):
        celsius = float(value) / 10.0
    else:
        try:
            celsius = float(value) / 10.0
        except (ValueError, TypeError):
            return 0.0

    if is_celsius:
        return celsius

    # Convert Celsius to Fahrenheit
    return round(celsius * 9 / 5 + 32, 1)


def div_10_celsius_delta_to_preferred(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> float:
    """Convert decicelsius delta value (raw / 10) to preferred unit (C or F).

    Raw device values are in tenths of Celsius (0.1°C per unit).
    This represents a temperature DELTA (difference), not an absolute
    temperature.

    Key difference from div_10_celsius_to_preferred: For deltas, we apply the
    scale factor but NOT the +32 offset.

    - If Metric (Celsius) mode: Return Celsius delta (value / 10.0)
    - If Imperial (Fahrenheit) mode: Convert to Fahrenheit delta (no +32)

    Uses WrapValidator instead of BeforeValidator to access ValidationInfo.data,
    which contains sibling fields needed to determine the device's temperature
    preference (Celsius or Fahrenheit).

    Args:
        value: Raw device value (tenths of Celsius delta).
        handler: Pydantic next validator handler. Not invoked as we bypass the
            validation chain to directly convert using the device's temperature
            preference. WrapValidator is required for access to ValidationInfo.
        info: Pydantic validation context containing sibling fields, used to
            retrieve the device's temperature_type preference.

    Returns:
        Temperature delta in preferred unit (Celsius or Fahrenheit).
    """
    is_celsius = _get_temperature_preference(info)

    if isinstance(value, (int, float)):
        return DeciCelsiusDelta(value).to_preferred(is_celsius)
    return float(value)
