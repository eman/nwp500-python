"""Temperature conversion utilities for different device representations.

The Navien NWP500 uses different temperature precision formats:
- HalfCelsius: 0.5°C precision (value / 2.0)
- DeciCelsius: 0.1°C precision (value / 10.0)

All values are converted to preferred unit based on device preference.
"""

import math
from typing import ClassVar, Self

from .enums import TempFormulaType


class Temperature:
    """Base class for temperature conversions with device protocol support.

    Subclasses set ``_scale`` (raw device units per degree Celsius) and
    inherit all conversions; only formats with special rounding or delta
    semantics override the Fahrenheit conversions.
    """

    #: Raw device units per degree Celsius (2 = half-degrees, 10 = deci).
    _scale: ClassVar[float] = 1.0

    def __init__(self, raw_value: int | float):
        """Initialize with raw device value.

        Args:
            raw_value: The raw value from the device in its native format.
        """
        self.raw_value = float(raw_value)

    def to_celsius(self) -> float:
        """Convert to Celsius.

        Returns:
            Temperature in Celsius.
        """
        return self.raw_value / self._scale

    def to_fahrenheit(self) -> float:
        """Convert to Fahrenheit.

        Returns:
            Temperature in Fahrenheit.
        """
        return self.to_celsius() * 9 / 5 + 32

    def to_preferred(self, is_celsius: bool = False) -> float:
        """Convert to preferred unit (Celsius or Fahrenheit).

        Args:
            is_celsius: Whether the preferred unit is Celsius.

        Returns:
            Temperature in Celsius if is_celsius is True, else Fahrenheit.
        """
        return self.to_celsius() if is_celsius else self.to_fahrenheit()

    @classmethod
    def from_fahrenheit(cls, fahrenheit: float) -> Self:
        """Create instance from Fahrenheit value (for device commands).

        Args:
            fahrenheit: Temperature in Fahrenheit.

        Returns:
            Instance with raw value set for device command.
        """
        celsius = (fahrenheit - 32) * 5 / 9
        return cls(round(celsius * cls._scale))

    @classmethod
    def from_celsius(cls, celsius: float) -> Self:
        """Create instance from Celsius value (for device commands).

        Args:
            celsius: Temperature in Celsius.

        Returns:
            Instance with raw value set for device command.
        """
        return cls(round(celsius * cls._scale))

    @classmethod
    def from_preferred(cls, value: float, is_celsius: bool = False) -> Self:
        """Create instance from preferred unit (C or F).

        Args:
            value: Temperature value in preferred unit.
            is_celsius: Whether the input value is in Celsius.

        Returns:
            Instance with raw value set for device command.
        """
        match is_celsius:
            case True:
                return cls.from_celsius(value)
            case False:
                return cls.from_fahrenheit(value)


class HalfCelsius(Temperature):
    """Temperature in half-degree Celsius (0.5°C precision).

    Used for DHW (domestic hot water) temperatures in device status.
    Formula: raw_value / 2.0 converts to Celsius.

    Example:
        >>> temp = HalfCelsius(120)  # Raw device value 120
        >>> temp.to_celsius()
        60.0
        >>> temp.to_fahrenheit()
        140.0
        >>> HalfCelsius.from_fahrenheit(140.0).raw_value
        120.0
        >>> HalfCelsius.from_celsius(60.0).raw_value
        120.0
    """

    _scale: ClassVar[float] = 2.0


class DeciCelsius(Temperature):
    """Temperature in decicelsius (0.1°C precision).

    Used for high-precision temperature measurements.
    Formula: raw_value / 10.0 converts to Celsius.

    Example:
        >>> temp = DeciCelsius(600)  # Raw device value 600
        >>> temp.to_celsius()
        60.0
        >>> temp.to_fahrenheit()
        140.0
        >>> DeciCelsius.from_fahrenheit(140.0).raw_value
        600.0
        >>> DeciCelsius.from_celsius(60.0).raw_value
        600.0
    """

    _scale: ClassVar[float] = 10.0


class RawCelsius(Temperature):
    """Temperature in raw halves of Celsius (0.5°C precision).

    Used for outdoor/ambient temperature measurements that require
    formula-specific rounding for Fahrenheit conversion.
    Formula: raw_value / 2.0 converts to Celsius.

    The Fahrenheit conversion supports two formula types:
    - Type 0 (Asymmetric Rounding): Uses floor/ceil based on remainder
    - Type 1 (Standard Rounding): Uses standard math rounding

    Example:
        >>> temp = RawCelsius(120)  # Raw device value 120
        >>> temp.to_celsius()
        60.0
        >>> temp.to_fahrenheit()
        140.0
    """

    _scale: ClassVar[float] = 2.0

    def to_fahrenheit(self) -> float:
        """Convert to Fahrenheit using standard rounding.

        Returns:
            Temperature in Fahrenheit (rounded to a whole degree, but
            returned as float for consistency with the base class API).
        """
        return float(round(super().to_fahrenheit()))

    def to_fahrenheit_with_formula(
        self, formula_type: TempFormulaType
    ) -> float:
        """Convert to Fahrenheit using formula-specific rounding.

        Args:
            formula_type: Temperature formula type (ASYMMETRIC or STANDARD)

        Returns:
            Temperature in Fahrenheit.
        """
        fahrenheit_value = self.to_celsius() * 9 / 5 + 32

        match formula_type:
            case TempFormulaType.ASYMMETRIC:
                # Asymmetric Rounding: check remainder of raw value.
                # Use the truncated remainder (like the firmware/app's
                # Java % operator), NOT Python's floored modulo: for
                # negative raw values Python's % is always non-negative
                # (-11 % 10 == 9), which would apply floor where the
                # firmware applies ceil, giving off-by-one Fahrenheit
                # values for sub-zero temperatures.
                remainder = int(math.fmod(int(self.raw_value), 10))
                match remainder:
                    case 9:
                        return float(math.floor(fahrenheit_value))
                    case _:
                        return float(math.ceil(fahrenheit_value))
            case _:
                # Standard Rounding (default for STANDARD and any future types)
                return round(fahrenheit_value)


class DeciCelsiusDelta(Temperature):
    """Temperature delta in decicelsius (0.1°C precision).

    Represents a temperature difference/delta, NOT an absolute temperature.
    Used for differential temperature settings (e.g., heat pump on/off Diff).
    Formula: raw_value / 10.0 converts to Celsius delta.

    Key difference from DeciCelsius: When converting to Fahrenheit, we apply
    the scale factor (9/5) but NOT the offset (+32), since this is a delta not
    an absolute temperature.

    Example:
        >>> temp = DeciCelsiusDelta(5)  # Raw device value 5
        >>> temp.to_celsius()
        0.5
        >>> temp.to_fahrenheit()
        0.9
        >>> DeciCelsiusDelta.from_fahrenheit(0.9).raw_value
        5.0
        >>> DeciCelsiusDelta.from_celsius(0.5).raw_value
        5.0
    """

    _scale: ClassVar[float] = 10.0

    def to_fahrenheit(self) -> float:
        """Convert to Fahrenheit delta (without +32 offset).

        Returns:
            Temperature delta in Fahrenheit.
        """
        return self.to_celsius() * 9 / 5

    @classmethod
    def from_fahrenheit(cls, fahrenheit: float) -> Self:
        """Create DeciCelsiusDelta from Fahrenheit delta (no -32 offset).

        Args:
            fahrenheit: Temperature delta in Fahrenheit.

        Returns:
            DeciCelsiusDelta instance with raw value for device.
        """
        celsius = fahrenheit * 5 / 9
        return cls(round(celsius * cls._scale))
