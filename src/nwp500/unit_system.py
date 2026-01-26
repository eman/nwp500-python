"""Unit system management for temperature, flow rate, and volume conversions.

This module provides context-based unit system management, allowing applications
to override the device's temperature_type setting and specify a preferred
measurement system (Metric or Imperial).

The unit system preference can be set at library initialization and is used
during model validation to convert device values to the user's preferred units.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Literal

from .enums import TemperatureType

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

# Context variable to store the preferred unit system
# None means auto-detect from device
# "metric" means Celsius, "us_customary" means Fahrenheit (also accepts "imperial" for compatibility)
_unit_system_context: contextvars.ContextVar[
    Literal["metric", "us_customary", "imperial"] | None
] = contextvars.ContextVar("unit_system", default=None)


def set_unit_system(
    unit_system: Literal["metric", "us_customary", "imperial"] | None,
) -> None:
    """Set preferred unit system for temperature, flow, and volume conversions.

    This setting overrides the device's temperature_type setting and applies to
    all subsequent model validation operations in the current async context.

    Args:
        unit_system: Preferred unit system:
            - "metric": Use Celsius, LPM, and Liters
            - "us_customary": Use Fahrenheit, GPM, and Gallons
            - "imperial": Use Fahrenheit, GPM, and Gallons
            - None: Auto-detect from device's temperature_type (default)

    Example:
        >>> from nwp500 import set_unit_system
        >>> set_unit_system("us_customary")
        >>> # All values now in F, GPM, Gallons
        >>> set_unit_system(None)  # Reset to auto-detect

    Note:
        This is context-aware and works with async code. Each async task
        maintains its own unit system preference.
        "imperial" is supported for backward compatibility but "us_customary"
        is the official Home Assistant term.
    """
    # Map "imperial" to "us_customary" for consistency with Home Assistant
    if unit_system == "imperial":
        unit_system = "us_customary"
    _unit_system_context.set(unit_system)


def get_unit_system() -> Literal["metric", "us_customary"] | None:
    """Get the currently configured unit system preference.

    Returns:
        The current unit system preference:
            - "metric": Celsius, LPM, Liters
            - "us_customary": Fahrenheit, GPM, Gallons
            - None: Auto-detect from device (default)
    """
    return _unit_system_context.get()


def reset_unit_system() -> None:
    """Reset unit system preference to auto-detect (None).

    This is useful for tests or when switching between different
    device configurations.
    """
    _unit_system_context.set(None)


def unit_system_to_temperature_type(
    unit_system: Literal["metric", "us_customary", "imperial"] | None,
) -> TemperatureType | None:
    """Convert unit system preference to TemperatureType enum.

    Args:
        unit_system: Unit system preference ("metric", "us_customary", "imperial", or None)

    Returns:
        - TemperatureType.CELSIUS for "metric"
        - TemperatureType.FAHRENHEIT for "us_customary" or "imperial"
        - None for None (auto-detect)
    """
    match unit_system:
        case "metric":
            return TemperatureType.CELSIUS
        case "us_customary" | "imperial":
            return TemperatureType.FAHRENHEIT
        case None:
            return None


def is_metric_preferred(
    override: Literal["metric", "us_customary", "imperial"] | None = None,
) -> bool:
    """Check if metric (Celsius) is preferred.

    Checks the override first, then falls back to the context-configured
    unit system. Used during validation to determine preferred units.

    Args:
        override: Optional override value. If provided, this takes precedence
            over the context-configured unit system.

    Returns:
        True if metric (Celsius) is preferred, False if us_customary (Fahrenheit).
    """
    # If override is provided, use it
    if override is not None:
        return override == "metric"

    # Otherwise check context
    unit_system = get_unit_system()
    if unit_system is not None:
        return unit_system == "metric"

    # If neither override nor context is set, return None (auto-detect)
    return None  # type: ignore[return-value]
