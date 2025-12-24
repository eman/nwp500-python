"""Temperature conversion utilities for different device representations.

The Navien NWP500 uses different temperature precision formats:
- HalfCelsius: 0.5°C precision (value / 2.0)
- DeciCelsius: 0.1°C precision (value / 10.0)

All values are converted to Fahrenheit for API responses and user interaction.
"""

from abc import ABC, abstractmethod
from typing import Any


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

    @classmethod
    def from_fahrenheit(cls, fahrenheit: float) -> "Temperature":
        """Create instance from Fahrenheit value (for commands).

        Args:
            fahrenheit: Temperature in Fahrenheit.

        Returns:
            Instance with raw value set for device command.
        """
        raise NotImplementedError(
            f"{cls.__name__} does not support creation from Fahrenheit"
        )


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
    def from_fahrenheit(cls, fahrenheit: float) -> "HalfCelsius":
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
    def from_fahrenheit(cls, fahrenheit: float) -> "DeciCelsius":
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
