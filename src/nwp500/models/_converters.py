from __future__ import annotations

from ..temperature import HalfCelsius
from ..unit_system import get_unit_system


def fahrenheit_to_half_celsius(fahrenheit: float) -> int:
    """Convert Fahrenheit to half-degrees Celsius (for device commands).

    Args:
        fahrenheit: Temperature in Fahrenheit.

    Returns:
        Raw device value in half-Celsius format.

    Example:
        >>> fahrenheit_to_half_celsius(140.0)
        120
    """
    return int(HalfCelsius.from_fahrenheit(fahrenheit).raw_value)


def preferred_to_half_celsius(temperature: float) -> int:
    """Convert temperature from preferred unit to half-degrees Celsius.

    Converts temperature from the user's preferred unit (Celsius or Fahrenheit,
    based on global unit system context) to the half-Celsius format used by
    the device for commands and reservations.

    Args:
        temperature: Temperature in user's preferred unit
            (Celsius or Fahrenheit).

    Returns:
        Raw device value in half-Celsius format.

    Example:
        >>> # With us_customary unit system
        >>> preferred_to_half_celsius(140.0)  # 140°F
        120
        >>> # With metric unit system
        >>> preferred_to_half_celsius(60.0)  # 60°C
        120
    """
    if get_unit_system() == "metric":
        # User prefers Celsius, input is in Celsius
        return int(HalfCelsius.from_celsius(temperature).raw_value)
    else:
        # User prefers Fahrenheit (or no preference), input is in Fahrenheit
        return fahrenheit_to_half_celsius(temperature)


def reservation_param_to_preferred(param: int) -> float:
    """Convert reservation param to user's preferred temperature unit.

    Device returns reservation temperatures as half-degrees Celsius (param).
    This converts them to the user's preferred unit (Celsius or Fahrenheit)
    based on the global unit system context.

    Args:
        param: Raw device value in half-Celsius format.

    Returns:
        Temperature in user's preferred unit (Celsius or Fahrenheit).

    Example:
        >>> # With metric (Celsius) unit system
        >>> reservation_param_to_preferred(120)
        60.0
        >>> # With us_customary (Fahrenheit) unit system
        >>> reservation_param_to_preferred(120)
        140.0
    """
    half_celsius = HalfCelsius(param)
    if get_unit_system() == "metric":
        return round(half_celsius.to_celsius(), 1)
    return round(half_celsius.to_fahrenheit(), 1)
