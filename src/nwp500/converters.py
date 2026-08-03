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
    "device_tristate_to_python",
    "tou_override_to_python",
    "div_10",
    "mul_10",
    "enum_validator",
]


def device_bool_to_python(value: Any) -> bool:
    """Convert device boolean representation to Python bool.

    Device protocol uses: 1 = OFF/False, 2 = ON/True, 0 = unknown/absent.

    The 1/2 encoding is not arbitrary. The vendor's own client decodes these
    fields through an enum declared ``UNKNOWN(0), OFF(1), ON(2)``, so 0 is a
    reserved sentinel rather than a value.

    This converter collapses 0 to ``False``, which is correct for **capability
    flags** (:data:`~nwp500.models.feature.CapabilityFlag`): the NaviLink app
    hides a feature's entire UI when its ``Use`` flag reads 0, so 0 there means
    "this device does not have the feature" and ``False`` is faithful.

    For **status flags**, where 0 means "the device is not reporting this right
    now", collapsing to ``False`` invents an OFF the device never claimed. Use
    :func:`device_tristate_to_python` for those.

    Args:
        value: Device value (typically 1 or 2).

    Returns:
        Python boolean (1→False, 2→True, 0→False).

    Example:
        >>> device_bool_to_python(2)
        True
        >>> device_bool_to_python(1)
        False
        >>> device_bool_to_python(0)
        False
    """
    return bool(value == 2)


def device_tristate_to_python(value: Any) -> bool | None:
    """Convert a device on/off flag, preserving the device's unknown state.

    Identical to :func:`device_bool_to_python` except that the protocol's
    reserved 0 maps to ``None`` instead of being flattened into ``False``.

    The device distinguishes three states and the library should not throw one
    away. The NaviLink app decodes the affected status fields through
    ``KDEnum.MgppOnOFFFlag``, which is declared ``UNKNOWN(0), OFF(1), ON(2)``;
    two of the app's sibling enums render their zero as ``"-"`` and
    ``"Not Applied"`` rather than as an off state.

    ``None`` is the right shape for the downstream consumer too: Home Assistant
    renders it as "Unknown" instead of recording a fabricated OFF into the
    history database.

    Note this applies only to flags the vendor itself decodes as an on/off
    enum. It is **not** a general rule about zero - see
    :func:`device_bool_to_python` for capability flags, and note that
    temperature fields carry no sentinel at all.

    Args:
        value: Device value (0, 1 or 2).

    Returns:
        ``None`` when the device reports 0, otherwise 1→False, 2→True.

    Example:
        >>> device_tristate_to_python(2)
        True
        >>> device_tristate_to_python(1)
        False
        >>> device_tristate_to_python(0) is None
        True
    """
    if value is None:
        return None
    try:
        if int(value) == 0:
            return None
    except TypeError, ValueError:
        return bool(value == 2)
    return bool(int(value) == 2)


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
