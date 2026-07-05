"""Unit system management for temperature, flow rate, and volume conversions.

This module provides process-wide unit system management, allowing
applications to override the device's temperature_type setting and specify a
preferred measurement system (Metric or Imperial).

The unit system preference can be set at library initialization and is used
during model validation to convert device values to the user's preferred
units. The preference is a process-wide setting: it is visible from every
task and thread, including model validation triggered by MQTT callbacks that
run outside the task that configured it.
"""

import logging
from typing import Literal

from .enums import TemperatureType

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

# Type alias for unit system preference
UnitSystemType = Literal["metric", "us_customary"] | None

# Process-wide preferred unit system.
# None means auto-detect from device
# "metric" means Celsius, "us_customary" means Fahrenheit
#
# This is intentionally NOT a contextvars.ContextVar: MQTT message handling
# runs in tasks scheduled from AWS CRT callback threads whose context never
# inherits from the application task, so a context-local preference silently
# reverted to auto-detect for all real-time data.
_unit_system: Literal["metric", "us_customary"] | None = None


def set_unit_system(
    unit_system: Literal["metric", "us_customary"] | None,
) -> None:
    """Set preferred unit system for temperature, flow, and volume conversions.

    This setting overrides the device's temperature_type setting and applies
    process-wide to all subsequent model validation operations, including
    those triggered by MQTT callbacks running in other tasks or threads.

    Args:
        unit_system: Preferred unit system:
            - "metric": Use Celsius, LPM, and Liters
            - "us_customary": Use Fahrenheit, GPM, and Gallons
            - None: Auto-detect from device's temperature_type (default)

    Example:
        >>> from nwp500 import set_unit_system
        >>> set_unit_system("us_customary")
        >>> # All values now in F, GPM, Gallons
        >>> set_unit_system(None)  # Reset to auto-detect
    """
    global _unit_system
    _unit_system = unit_system


def get_unit_system() -> Literal["metric", "us_customary"] | None:
    """Get the currently configured unit system preference.

    Returns:
        The current unit system preference:
            - "metric": Celsius, LPM, Liters
            - "us_customary": Fahrenheit, GPM, Gallons
            - None: Auto-detect from device (default)
    """
    return _unit_system


def reset_unit_system() -> None:
    """Reset unit system preference to auto-detect (None).

    This is useful for tests or when switching between different
    device configurations.
    """
    set_unit_system(None)


def unit_system_to_temperature_type(
    unit_system: Literal["metric", "us_customary"] | None,
) -> TemperatureType | None:
    """Convert unit system preference to TemperatureType enum.

    Args:
        unit_system: Unit system preference ("metric", "us_customary", or None)

    Returns:
        - TemperatureType.CELSIUS for "metric"
        - TemperatureType.FAHRENHEIT for "us_customary"
        - None for None (auto-detect)
    """
    match unit_system:
        case "metric":
            return TemperatureType.CELSIUS
        case "us_customary":
            return TemperatureType.FAHRENHEIT
        case None:
            return None


def is_metric_preferred(
    override: Literal["metric", "us_customary"] | None = None,
) -> bool:
    """Check if metric (Celsius) is preferred.

    Checks the override first, then falls back to the configured unit
    system. Used during validation to determine preferred units.

    Args:
        override: Optional override value. If provided, this takes precedence
            over the context-configured unit system.

    Returns:
        True if metric (Celsius) is preferred, False if us_customary
        (Fahrenheit).
    """
    # If override is provided, use it
    if override is not None:
        return override == "metric"

    # Otherwise check the configured preference
    unit_system = get_unit_system()
    if unit_system is not None:
        return unit_system == "metric"

    # If neither override nor context is set, default to Fahrenheit (US)
    return False
