"""Temperature conversion utilities for different device representations.

The Navien NWP500 uses different temperature precision formats:
- HalfCelsius: 0.5°C precision (value / 2.0)
- DeciCelsius: 0.1°C precision (value / 10.0)

All values are converted to preferred unit based on device preference.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any

from .enums import TempFormulaType


class Temperature(ABC):
    """Base class for temperature conversions with device protocol support."""

    def __init__(self, raw_value: int | float):
        """Initialize with raw device value.

        Args:
            raw_value: The raw value from the device in its native format.
        """
        self.raw_value = float(raw_value)

    @abstractmethod
    def to_celsius(self) -> float:
        """Convert to Celsius.

        Returns:
            Temperature in Celsius.
        """

    @abstractmethod
    def to_fahrenheit(self) -> float:
        """Convert to Fahrenheit.

        Returns:
            Temperature in Fahrenheit.
        """

    def to_preferred(self, is_celsius: bool = False) -> float:
        """Convert to preferred unit (Celsius or Fahrenheit).

        Args:
            is_celsius: Whether the preferred unit is Celsius.

        Returns:
            Temperature in Celsius if is_celsius is True, else Fahrenheit.
        """
        return self.to_celsius() if is_celsius else self.to_fahrenheit()

    @classmethod
    def from_fahrenheit(cls, fahrenheit: float) -> Temperature:
        """Create instance from Fahrenheit value (for commands).

        Args:
            fahrenheit: Temperature in Fahrenheit.

        Returns:
            Instance with raw value set for device command.
        """
        raise NotImplementedError(
            f"{cls.__name__} does not support creation from Fahrenheit"
        )

    @classmethod
    def from_celsius(cls, celsius: float) -> Temperature:
        """Create instance from Celsius value (for commands).

        Args:
            celsius: Temperature in Celsius.

        Returns:
            Instance with raw value set for device command.
        """
        raise NotImplementedError(
            f"{cls.__name__} does not support creation from Celsius"
        )

    @classmethod
    def from_preferred(
        cls, value: float, is_celsius: bool = False
    ) -> Temperature:
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
    """

    def to_celsius(self) -> float:
        """Convert to Celsius.

        Returns:
            Temperature in Celsius.
        """
        return self.raw_value / 2.0

    def to_fahrenheit(self) -> float:
        """Convert to Fahrenheit.

        Returns:
            Temperature in Fahrenheit.
        """
        celsius = self.to_celsius()
        return celsius * 9 / 5 + 32

    @classmethod
    def from_fahrenheit(cls, fahrenheit: float) -> HalfCelsius:
        """Create HalfCelsius from Fahrenheit (for device commands).

        Args:
            fahrenheit: Temperature in Fahrenheit.

        Returns:
            HalfCelsius instance with raw value for device.

        Example:
            >>> temp = HalfCelsius.from_fahrenheit(140.0)
            >>> temp.raw_value
            120
        """
        celsius = (fahrenheit - 32) * 5 / 9
        raw_value = round(celsius * 2)
        return cls(raw_value)

    @classmethod
    def from_celsius(cls, celsius: float) -> HalfCelsius:
        """Create HalfCelsius from Celsius (for device commands).

        Args:
            celsius: Temperature in Celsius.

        Returns:
            HalfCelsius instance with raw value for device.

        Example:
            >>> temp = HalfCelsius.from_celsius(60.0)
            >>> temp.raw_value
            120
        """
        raw_value = round(celsius * 2)
        return cls(raw_value)


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
    """

    def to_celsius(self) -> float:
        """Convert to Celsius.

        Returns:
            Temperature in Celsius.
        """
        return self.raw_value / 10.0

    def to_fahrenheit(self) -> float:
        """Convert to Fahrenheit.

        Returns:
            Temperature in Fahrenheit.
        """
        celsius = self.to_celsius()
        return celsius * 9 / 5 + 32

    @classmethod
    def from_fahrenheit(cls, fahrenheit: float) -> DeciCelsius:
        """Create DeciCelsius from Fahrenheit (for device commands).

        Args:
            fahrenheit: Temperature in Fahrenheit.

        Returns:
            DeciCelsius instance with raw value for device.

        Example:
            >>> temp = DeciCelsius.from_fahrenheit(140.0)
            >>> temp.raw_value
            600
        """
        celsius = (fahrenheit - 32) * 5 / 9
        raw_value = round(celsius * 10)
        return cls(raw_value)

    @classmethod
    def from_celsius(cls, celsius: float) -> DeciCelsius:
        """Create DeciCelsius from Celsius (for device commands).

        Args:
            celsius: Temperature in Celsius.

        Returns:
            DeciCelsius instance with raw value for device.

        Example:
            >>> temp = DeciCelsius.from_celsius(60.0)
            >>> temp.raw_value
            600
        """
        raw_value = round(celsius * 10)
        return cls(raw_value)


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

    def to_celsius(self) -> float:
        """Convert to Celsius.

        Returns:
            Temperature in Celsius.
        """
        return self.raw_value / 2.0

    def to_fahrenheit(self) -> float:
        """Convert to Fahrenheit using standard rounding.

        Returns:
            Temperature in Fahrenheit.
        """
        celsius = self.to_celsius()
        return round((celsius * 9 / 5) + 32)

    def to_fahrenheit_with_formula(
        self, formula_type: TempFormulaType
    ) -> float:
        """Convert to Fahrenheit using formula-specific rounding.

        Args:
            formula_type: Temperature formula type (ASYMMETRIC or STANDARD)

        Returns:
            Temperature in Fahrenheit.
        """
        celsius = self.to_celsius()
        fahrenheit_value = (celsius * 9 / 5) + 32

        match formula_type:
            case TempFormulaType.ASYMMETRIC:
                # Asymmetric Rounding: check remainder of raw value
                remainder = int(self.raw_value) % 10
                match remainder:
                    case 9:
                        return float(math.floor(fahrenheit_value))
                    case _:
                        return float(math.ceil(fahrenheit_value))
            case TempFormulaType.STANDARD:
                # Standard Rounding (default)
                return round(fahrenheit_value)

    @classmethod
    def from_fahrenheit(cls, fahrenheit: float) -> RawCelsius:
        """Create RawCelsius from Fahrenheit (for device commands).

        Args:
            fahrenheit: Temperature in Fahrenheit.

        Returns:
            RawCelsius instance with raw value for device.

        Example:
            >>> temp = RawCelsius.from_fahrenheit(140.0)
            >>> temp.raw_value
            120
        """
        celsius = (fahrenheit - 32) * 5 / 9
        raw_value = round(celsius * 2)
        return cls(raw_value)

    @classmethod
    def from_celsius(cls, celsius: float) -> RawCelsius:
        """Create RawCelsius from Celsius (for device commands).

        Args:
            celsius: Temperature in Celsius.

        Returns:
            RawCelsius instance with raw value for device.

        Example:
            >>> temp = RawCelsius.from_celsius(60.0)
            >>> temp.raw_value
            120
        """
        raw_value = round(celsius * 2)
        return cls(raw_value)


def half_celsius_to_fahrenheit(value: Any) -> float:
    """Convert half-degrees Celsius to Fahrenheit.

    Validator function for Pydantic fields using HalfCelsius format.

    Args:
        value: Raw device value in half-Celsius format.

    Returns:
        Temperature in Fahrenheit.
    """
    if isinstance(value, (int, float)):
        return HalfCelsius(value).to_fahrenheit()
    return float(value)


def deci_celsius_to_fahrenheit(value: Any) -> float:
    """Convert decicelsius to Fahrenheit.

    Validator function for Pydantic fields using DeciCelsius format.

    Args:
        value: Raw device value in decicelsius format.

    Returns:
        Temperature in Fahrenheit.
    """
    if isinstance(value, (int, float)):
        return DeciCelsius(value).to_fahrenheit()
    return float(value)


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
        0.9  # 0.5°C * 9/5 = 0.9°F, no +32 offset
    """

    def to_celsius(self) -> float:
        """Convert to Celsius delta.

        Returns:
            Temperature delta in Celsius.
        """
        return self.raw_value / 10.0

    def to_fahrenheit(self) -> float:
        """Convert to Fahrenheit delta (without +32 offset).

        Returns:
            Temperature delta in Fahrenheit.
        """
        celsius = self.to_celsius()
        return celsius * 9 / 5

    @classmethod
    def from_fahrenheit(cls, fahrenheit: float) -> DeciCelsiusDelta:
        """Create DeciCelsiusDelta from Fahrenheit delta (for device commands).

        Args:
            fahrenheit: Temperature delta in Fahrenheit.

        Returns:
            DeciCelsiusDelta instance with raw value for device.

        Example:
            >>> temp = DeciCelsiusDelta.from_fahrenheit(0.9)
            >>> temp.raw_value
            5
        """
        celsius = fahrenheit * 5 / 9
        raw_value = round(celsius * 10)
        return cls(raw_value)

    @classmethod
    def from_celsius(cls, celsius: float) -> DeciCelsiusDelta:
        """Create DeciCelsiusDelta from Celsius delta (for device commands).

        Args:
            celsius: Temperature delta in Celsius.

        Returns:
            DeciCelsiusDelta instance with raw value for device.

        Example:
            >>> temp = DeciCelsiusDelta.from_celsius(0.5)
            >>> temp.raw_value
            5
        """
        raw_value = round(celsius * 10)
        return cls(raw_value)
