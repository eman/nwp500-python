"""Comprehensive tests for temperature conversion utilities.

Tests cover:
- HalfCelsius conversion from device values to Fahrenheit
- DeciCelsius conversion from device values to Fahrenheit
- Reverse conversions (Fahrenheit to device values)
- Edge cases and boundary conditions
- Known temperature reference points
"""

import pytest

from nwp500.temperature import DeciCelsius, HalfCelsius


class TestHalfCelsius:
    """Test HalfCelsius temperature conversion (0.5°C precision).

    HalfCelsius format: raw_value / 2.0 = Celsius
    Example: raw_value=120 → 60°C → 140°F
    """

    def test_zero_celsius(self):
        """0°C = 32°F."""
        temp = HalfCelsius(0)
        assert temp.to_fahrenheit() == 32.0

    def test_freezing_point(self):
        """0°C = 32°F (freezing point of water)."""
        temp = HalfCelsius(0)
        assert temp.to_celsius() == 0.0
        assert temp.to_fahrenheit() == 32.0

    def test_boiling_point(self):
        """100°C = 212°F (boiling point of water)."""
        temp = HalfCelsius(200)  # 200 half-degrees = 100°C
        assert temp.to_celsius() == 100.0
        assert temp.to_fahrenheit() == pytest.approx(212.0)

    def test_body_temperature(self):
        """37°C ≈ 98.6°F (normal body temperature)."""
        temp = HalfCelsius(74)  # 74 half-degrees = 37°C
        assert temp.to_celsius() == pytest.approx(37.0)
        assert temp.to_fahrenheit() == pytest.approx(98.6)

    def test_room_temperature(self):
        """20°C = 68°F (typical room temperature)."""
        temp = HalfCelsius(40)  # 40 half-degrees = 20°C
        assert temp.to_celsius() == 20.0
        assert temp.to_fahrenheit() == pytest.approx(68.0)

    def test_typical_dhw_temperature(self):
        """60°C = 140°F (typical DHW temperature)."""
        temp = HalfCelsius(120)  # 120 half-degrees = 60°C
        assert temp.to_celsius() == 60.0
        assert temp.to_fahrenheit() == pytest.approx(140.0)

    def test_high_dhw_temperature(self):
        """80°C = 176°F (high DHW temperature)."""
        temp = HalfCelsius(160)  # 160 half-degrees = 80°C
        assert temp.to_celsius() == 80.0
        assert temp.to_fahrenheit() == pytest.approx(176.0)

    def test_negative_temperature(self):
        """-10°C = 14°F (freezing outdoor temp)."""
        temp = HalfCelsius(-20)  # -20 half-degrees = -10°C
        assert temp.to_celsius() == -10.0
        assert temp.to_fahrenheit() == pytest.approx(14.0)

    @pytest.mark.parametrize(
        "raw_value,expected_celsius,expected_fahrenheit",
        [
            (0, 0.0, 32.0),
            (10, 5.0, 41.0),
            (20, 10.0, 50.0),
            (40, 20.0, 68.0),
            (74, 37.0, 98.6),
            (100, 50.0, 122.0),
            (120, 60.0, 140.0),
            (140, 70.0, 158.0),
            (160, 80.0, 176.0),
            (200, 100.0, 212.0),
            (-20, -10.0, 14.0),
            (-40, -20.0, -4.0),
        ],
    )
    def test_known_conversions(
        self, raw_value, expected_celsius, expected_fahrenheit
    ):
        """Test known temperature conversion points."""
        temp = HalfCelsius(raw_value)
        assert temp.to_celsius() == pytest.approx(expected_celsius, abs=0.01)
        assert temp.to_fahrenheit() == pytest.approx(
            expected_fahrenheit, abs=0.1
        )

    def test_from_fahrenheit_zero(self):
        """32°F = 0°C = 0 in HalfCelsius."""
        temp = HalfCelsius.from_fahrenheit(32.0)
        assert temp.raw_value == 0
        assert temp.to_celsius() == pytest.approx(0.0)

    def test_from_fahrenheit_room_temp(self):
        """68°F ≈ 20°C ≈ 40 in HalfCelsius."""
        temp = HalfCelsius.from_fahrenheit(68.0)
        assert temp.raw_value == pytest.approx(40, abs=1)
        assert temp.to_fahrenheit() == pytest.approx(68.0, abs=0.1)

    def test_from_fahrenheit_typical_dhw(self):
        """140°F ≈ 60°C ≈ 120 in HalfCelsius."""
        temp = HalfCelsius.from_fahrenheit(140.0)
        assert temp.raw_value == pytest.approx(120, abs=1)
        assert temp.to_fahrenheit() == pytest.approx(140.0, abs=0.1)

    @pytest.mark.parametrize(
        "fahrenheit,expected_raw",
        [
            (32.0, 0),
            (50.0, 20),
            (68.0, 40),
            (86.0, 60),
            (104.0, 80),
            (122.0, 100),
            (140.0, 120),
            (158.0, 140),
            (176.0, 160),
            (212.0, 200),
            (14.0, -20),
            (-4.0, -40),
        ],
    )
    def test_from_fahrenheit_known_points(self, fahrenheit, expected_raw):
        """Test reverse conversion from Fahrenheit to raw value."""
        temp = HalfCelsius.from_fahrenheit(fahrenheit)
        # Allow some rounding tolerance
        assert temp.raw_value == pytest.approx(expected_raw, abs=1)

    def test_roundtrip_conversion(self):
        """Test roundtrip: raw → Celsius → Fahrenheit → raw."""
        original_raw = 120
        temp = HalfCelsius(original_raw)
        fahrenheit = temp.to_fahrenheit()

        temp2 = HalfCelsius.from_fahrenheit(fahrenheit)
        assert temp2.raw_value == pytest.approx(original_raw, abs=1)

    def test_float_raw_value(self):
        """Test handling of float raw values."""
        temp = HalfCelsius(120.5)
        assert temp.raw_value == 120.5
        assert temp.to_celsius() == pytest.approx(60.25)
        assert temp.to_fahrenheit() == pytest.approx(140.45)

    def test_very_large_value(self):
        """Test handling of very large temperature values."""
        temp = HalfCelsius(10000)  # 5000°C
        assert temp.to_celsius() == 5000.0
        assert temp.to_fahrenheit() == pytest.approx(9032.0)

    def test_very_small_value(self):
        """Test handling of very small temperature values."""
        temp = HalfCelsius(-10000)  # -5000°C
        assert temp.to_celsius() == -5000.0
        assert temp.to_fahrenheit() == pytest.approx(-8968.0)


class TestDeciCelsius:
    """Test DeciCelsius temperature conversion (0.1°C precision).

    DeciCelsius format: raw_value / 10.0 = Celsius
    Example: raw_value=600 → 60°C → 140°F
    """

    def test_zero_celsius(self):
        """0°C = 32°F."""
        temp = DeciCelsius(0)
        assert temp.to_fahrenheit() == 32.0

    def test_freezing_point(self):
        """0°C = 32°F (freezing point)."""
        temp = DeciCelsius(0)
        assert temp.to_celsius() == 0.0
        assert temp.to_fahrenheit() == 32.0

    def test_boiling_point(self):
        """100°C = 212°F (boiling point)."""
        temp = DeciCelsius(1000)  # 1000 deci-degrees = 100°C
        assert temp.to_celsius() == 100.0
        assert temp.to_fahrenheit() == pytest.approx(212.0)

    def test_body_temperature(self):
        """37°C ≈ 98.6°F (normal body temperature)."""
        temp = DeciCelsius(370)  # 370 deci-degrees = 37°C
        assert temp.to_celsius() == pytest.approx(37.0)
        assert temp.to_fahrenheit() == pytest.approx(98.6)

    def test_room_temperature(self):
        """20°C = 68°F (typical room temperature)."""
        temp = DeciCelsius(200)  # 200 deci-degrees = 20°C
        assert temp.to_celsius() == 20.0
        assert temp.to_fahrenheit() == pytest.approx(68.0)

    def test_typical_dhw_temperature(self):
        """60°C = 140°F (typical DHW temperature)."""
        temp = DeciCelsius(600)  # 600 deci-degrees = 60°C
        assert temp.to_celsius() == 60.0
        assert temp.to_fahrenheit() == pytest.approx(140.0)

    def test_high_precision_value(self):
        """60.5°C = 140.9°F (tests 0.1°C precision)."""
        temp = DeciCelsius(605)  # 605 deci-degrees = 60.5°C
        assert temp.to_celsius() == 60.5
        assert temp.to_fahrenheit() == pytest.approx(140.9)

    def test_negative_temperature(self):
        """-10°C = 14°F (freezing outdoor temp)."""
        temp = DeciCelsius(-100)  # -100 deci-degrees = -10°C
        assert temp.to_celsius() == -10.0
        assert temp.to_fahrenheit() == pytest.approx(14.0)

    @pytest.mark.parametrize(
        "raw_value,expected_celsius,expected_fahrenheit",
        [
            (0, 0.0, 32.0),
            (50, 5.0, 41.0),
            (100, 10.0, 50.0),
            (200, 20.0, 68.0),
            (370, 37.0, 98.6),
            (500, 50.0, 122.0),
            (600, 60.0, 140.0),
            (700, 70.0, 158.0),
            (800, 80.0, 176.0),
            (1000, 100.0, 212.0),
            (-100, -10.0, 14.0),
            (-200, -20.0, -4.0),
        ],
    )
    def test_known_conversions(
        self, raw_value, expected_celsius, expected_fahrenheit
    ):
        """Test known temperature conversion points."""
        temp = DeciCelsius(raw_value)
        assert temp.to_celsius() == pytest.approx(expected_celsius, abs=0.01)
        assert temp.to_fahrenheit() == pytest.approx(
            expected_fahrenheit, abs=0.1
        )

    def test_from_fahrenheit_zero(self):
        """32°F = 0°C = 0 in DeciCelsius."""
        temp = DeciCelsius.from_fahrenheit(32.0)
        assert temp.raw_value == 0
        assert temp.to_celsius() == pytest.approx(0.0)

    def test_from_fahrenheit_room_temp(self):
        """68°F ≈ 20°C ≈ 200 in DeciCelsius."""
        temp = DeciCelsius.from_fahrenheit(68.0)
        assert temp.raw_value == pytest.approx(200, abs=1)
        assert temp.to_fahrenheit() == pytest.approx(68.0, abs=0.1)

    def test_from_fahrenheit_typical_dhw(self):
        """140°F ≈ 60°C ≈ 600 in DeciCelsius."""
        temp = DeciCelsius.from_fahrenheit(140.0)
        assert temp.raw_value == pytest.approx(600, abs=1)
        assert temp.to_fahrenheit() == pytest.approx(140.0, abs=0.1)

    @pytest.mark.parametrize(
        "fahrenheit,expected_raw",
        [
            (32.0, 0),
            (50.0, 100),
            (68.0, 200),
            (86.0, 300),
            (104.0, 400),
            (122.0, 500),
            (140.0, 600),
            (158.0, 700),
            (176.0, 800),
            (212.0, 1000),
            (14.0, -100),
            (-4.0, -200),
        ],
    )
    def test_from_fahrenheit_known_points(self, fahrenheit, expected_raw):
        """Test reverse conversion from Fahrenheit to raw value."""
        temp = DeciCelsius.from_fahrenheit(fahrenheit)
        assert temp.raw_value == pytest.approx(expected_raw, abs=1)

    def test_roundtrip_conversion(self):
        """Test roundtrip: raw → Celsius → Fahrenheit → raw."""
        original_raw = 600
        temp = DeciCelsius(original_raw)
        fahrenheit = temp.to_fahrenheit()

        temp2 = DeciCelsius.from_fahrenheit(fahrenheit)
        assert temp2.raw_value == pytest.approx(original_raw, abs=1)

    def test_float_raw_value(self):
        """Test handling of float raw values."""
        temp = DeciCelsius(600.5)
        assert temp.raw_value == 600.5
        assert temp.to_celsius() == pytest.approx(60.05)
        assert temp.to_fahrenheit() == pytest.approx(140.09)

    def test_very_large_value(self):
        """Test handling of very large temperature values."""
        temp = DeciCelsius(100000)  # 10000°C
        assert temp.to_celsius() == 10000.0
        assert temp.to_fahrenheit() == pytest.approx(18032.0)

    def test_very_small_value(self):
        """Test handling of very small temperature values."""
        temp = DeciCelsius(-100000)  # -10000°C
        assert temp.to_celsius() == -10000.0
        assert temp.to_fahrenheit() == pytest.approx(-17968.0)


class TestTemperatureComparison:
    """Compare HalfCelsius and DeciCelsius for same temperature."""

    def test_same_temperature_different_precision(self):
        """HalfCelsius(120) and DeciCelsius(600) represent same 60°C."""
        half_temp = HalfCelsius(120)
        deci_temp = DeciCelsius(600)

        assert half_temp.to_celsius() == pytest.approx(deci_temp.to_celsius())
        assert half_temp.to_fahrenheit() == pytest.approx(
            deci_temp.to_fahrenheit()
        )

    @pytest.mark.parametrize(
        "half_raw,deci_raw,celsius",
        [
            # For equivalence: half_raw/2 = deci_raw/10
            # So: deci_raw = half_raw * 5
            (0, 0, 0.0),
            (10, 50, 5.0),
            (20, 100, 10.0),
            (40, 200, 20.0),
            (100, 500, 50.0),
            (120, 600, 60.0),
            (200, 1000, 100.0),
        ],
    )
    def test_equivalent_temperatures(self, half_raw, deci_raw, celsius):
        """Test that half and deci celsius represent same actual temp."""
        # HalfCelsius: raw/2 = celsius
        # DeciCelsius: raw/10 = celsius
        # For same temp: half_raw/2 = deci_raw/10
        # Therefore: deci_raw = half_raw * 5
        half = HalfCelsius(half_raw)
        deci = DeciCelsius(deci_raw)

        # HalfCelsius: raw/2 = celsius
        half_celsius = half_raw / 2.0
        # DeciCelsius: raw/10 = celsius
        deci_celsius = deci_raw / 10.0

        assert half_celsius == pytest.approx(celsius)
        assert deci_celsius == pytest.approx(celsius)
        assert half.to_fahrenheit() == pytest.approx(deci.to_fahrenheit())
