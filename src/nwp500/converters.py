"""Protocol-specific converters for Navien device communication.

This module handles conversion of device-specific data formats to Python types.
The Navien device uses non-standard representations for boolean and numeric
values.

See docs/protocol/quick_reference.rst for comprehensive protocol details.
"""

from collections.abc import Callable
from typing import Any

__all__ = [
    "device_bool_to_python",
    "device_bool_from_python",
    "tou_override_to_python",
    "div_10",
    "energy_count_to_wh",
    "WH_PER_ENERGY_COUNT",
    "enum_validator",
]

#: Watt-hours represented by one raw device energy count.
#:
#: The device reports ``totalEnergyCapacity`` and ``availableEnergyCapacity``
#: as small integers in a fixed energy quantum, not in Watt-hours.
#:
#: ``totalEnergyCapacity`` is a whole-tank quantity, so regressing it against
#: the setpoint measures the quantum with no stratification assumption. On a
#: 65-gallon NWP500 that slope is 70.25 raw counts per Kelvin of whole-tank
#: rise. The field is bimodal - at a fixed setpoint it takes one of two
#: values 2 degC apart - but both branches give the same slope to within
#: 0.2%, so the quantum is unaffected.
#:
#: Converting to Watt-hours needs a water mass, and a "65 gallon" tank does
#: not hold 65 gallons. Assuming instead that the quantum is round - as every
#: other conversion in this protocol is - 4 Wh/count is the only candidate
#: implying a water volume below the nameplate (241.7 L / 63.9 gal); 1/240
#: kWh and 15 kJ both imply more water than the tank holds.
#:
#: Confirmed twice over:
#:
#: * 183 individual heating recoveries give 4.11 Wh/count (p10 3.47,
#:   p90 4.45), agreeing to within 2% by a noisier route
#: * the same recoveries imply a heat pump COP of 2.89 at 4 Wh/count
#:
#: Library versions before 10.0 used 10 Wh/count, which overstated reported
#: tank energy by 2.5x and implied a physically impossible COP of 7.0.
#:
#: See ``docs/explanation/tank-energy.rst`` for the full derivation.
WH_PER_ENERGY_COUNT = 4.0


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
    return float(value) / 10.0


def energy_count_to_wh(value: Any) -> float:
    """Convert a raw device energy count to Watt-hours.

    The device reports tank energy in a fixed quantum of
    :data:`WH_PER_ENERGY_COUNT` Watt-hours per count, not in Watt-hours
    directly. See that constant for how the quantum was measured.

    Args:
        value: Raw device energy count.

    Returns:
        Energy in Watt-hours.

    Example:
        >>> energy_count_to_wh(1580)
        6320.0
        >>> energy_count_to_wh(0)
        0.0
    """
    return float(value) * WH_PER_ENERGY_COUNT


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
