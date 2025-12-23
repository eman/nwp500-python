"""Field factory for creating typed Pydantic fields with metadata templates.

This module provides convenience functions for creating Pydantic fields with
standard metadata (device_class, unit_of_measurement, etc.) pre-configured,
reducing boilerplate in models while maintaining type safety.

Each factory function creates a Pydantic Field with metadata for Home Assistant
integration:
- temperature_field: Adds unit_of_measurement, device_class='temperature',
  suggested_display_precision
- signal_strength_field: Adds unit_of_measurement,
  device_class='signal_strength'
- energy_field: Adds unit_of_measurement, device_class='energy'
- power_field: Adds unit_of_measurement, device_class='power'

Example:
    >>> from nwp500.field_factory import temperature_field
    >>> class MyModel(BaseModel):
    ...     temp: float = temperature_field("DHW Temperature", unit="°F")
"""

from typing import Any, cast

from pydantic import Field

__all__ = [
    "temperature_field",
    "signal_strength_field",
    "energy_field",
    "power_field",
]


def temperature_field(
    description: str,
    *,
    unit: str = "°F",
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """Create a temperature field with standard Home Assistant metadata.

    Args:
        description: Field description
        unit: Temperature unit (default: °F)
        default: Default value or Pydantic default
        **kwargs: Additional Pydantic Field arguments

    Returns:
        Pydantic Field with temperature metadata
    """
    json_schema_extra: dict[str, Any] = {
        "unit_of_measurement": unit,
        "device_class": "temperature",
        "suggested_display_precision": 1,
    }
    if "json_schema_extra" in kwargs:
        extra = kwargs.pop("json_schema_extra")
        if isinstance(extra, dict):
            json_schema_extra.update(extra)

    return Field(
        default=default,
        description=description,
        json_schema_extra=cast(Any, json_schema_extra),
        **kwargs,
    )


def signal_strength_field(
    description: str,
    *,
    unit: str = "dBm",
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """Create a signal strength field with standard Home Assistant metadata.

    Args:
        description: Field description
        unit: Signal unit (default: dBm)
        default: Default value or Pydantic default
        **kwargs: Additional Pydantic Field arguments

    Returns:
        Pydantic Field with signal strength metadata
    """
    json_schema_extra: dict[str, Any] = {
        "unit_of_measurement": unit,
        "device_class": "signal_strength",
    }
    if "json_schema_extra" in kwargs:
        extra = kwargs.pop("json_schema_extra")
        if isinstance(extra, dict):
            json_schema_extra.update(extra)

    return Field(
        default=default,
        description=description,
        json_schema_extra=cast(Any, json_schema_extra),
        **kwargs,
    )


def energy_field(
    description: str,
    *,
    unit: str = "kWh",
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """Create an energy field with standard Home Assistant metadata.

    Args:
        description: Field description
        unit: Energy unit (default: kWh)
        default: Default value or Pydantic default
        **kwargs: Additional Pydantic Field arguments

    Returns:
        Pydantic Field with energy metadata
    """
    json_schema_extra: dict[str, Any] = {
        "unit_of_measurement": unit,
        "device_class": "energy",
    }
    if "json_schema_extra" in kwargs:
        extra = kwargs.pop("json_schema_extra")
        if isinstance(extra, dict):
            json_schema_extra.update(extra)

    return Field(
        default=default,
        description=description,
        json_schema_extra=cast(Any, json_schema_extra),
        **kwargs,
    )


def power_field(
    description: str,
    *,
    unit: str = "W",
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """Create a power field with standard Home Assistant metadata.

    Args:
        description: Field description
        unit: Power unit (default: W)
        default: Default value or Pydantic default
        **kwargs: Additional Pydantic Field arguments

    Returns:
        Pydantic Field with power metadata
    """
    json_schema_extra: dict[str, Any] = {
        "unit_of_measurement": unit,
        "device_class": "power",
    }
    if "json_schema_extra" in kwargs:
        extra = kwargs.pop("json_schema_extra")
        if isinstance(extra, dict):
            json_schema_extra.update(extra)

    return Field(
        default=default,
        description=description,
        json_schema_extra=cast(Any, json_schema_extra),
        **kwargs,
    )
