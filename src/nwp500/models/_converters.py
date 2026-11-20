from collections.abc import Mapping

from pydantic.fields import FieldInfo

from ..enums import TemperatureType
from ..temperature import HalfCelsius
from ..unit_system import get_unit_system


def prefers_celsius(temperature_type: TemperatureType) -> bool:
    """Whether a model's readings are in Celsius.

    The process-wide unit-system preference decides when one is set;
    otherwise the device's own ``temperature_type`` does.
    """
    unit_system = get_unit_system()
    if unit_system is not None:
        return unit_system == "metric"
    return temperature_type == TemperatureType.CELSIUS


def field_unit(
    model_fields: Mapping[str, FieldInfo], field_name: str, is_celsius: bool
) -> str:
    """The unit suffix of a model field, as ``get_field_unit`` returns it.

    ``field_name`` may name the field or the computed reading of its
    ``_raw`` field. Temperature, flow rate and volume fields follow
    ``is_celsius``; others carry a static ``unit_of_measurement``.
    """
    lookup_name = (
        field_name if field_name in model_fields else f"{field_name}_raw"
    )
    if lookup_name not in model_fields:
        return ""

    field_info = model_fields[lookup_name]
    if not hasattr(field_info, "json_schema_extra"):
        return ""

    extra = field_info.json_schema_extra
    if not isinstance(extra, dict):
        return ""

    device_class = extra.get("device_class")

    # Handle temperature units
    if device_class == "temperature":
        return " °C" if is_celsius else " °F"

    # Handle flow rate units
    if device_class == "flow_rate":
        return " LPM" if is_celsius else " GPM"

    # Handle volume units
    if device_class == "water":
        return " L" if is_celsius else " gal"

    # Fallback to static unit_of_measurement if present
    if "unit_of_measurement" in extra:
        unit_val = extra["unit_of_measurement"]
        unit: str = str(unit_val) if unit_val is not None else ""
        return f" {unit}" if unit else ""

    return ""


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
