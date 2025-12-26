"""Tests for device data converter validators.

Tests cover:
- device_bool_to_python (device 1=False, 2=True)
- tou_override_to_python (TOU override status encoding)
- div_10 (divide by 10 converter)
- enum_validator (enum validation and conversion)

Note: touStatus field uses built-in bool() for standard 0/1 encoding
"""

import pytest

from nwp500.converters import (
    device_bool_to_python,
    div_10,
    enum_validator,
    tou_override_to_python,
)
from nwp500.enums import DhwOperationSetting, OnOffFlag


class TestDeviceBoolConverter:
    """Test device_bool_to_python converter.

    Device encoding: 1 = OFF (False), 2 = ON (True)
    This is the standard boolean encoding for Navien devices.
    NOTE: Uses comparison `value == 2`, so string "2" does NOT equal int 2.
    """

    def test_off_value(self):
        """Device value 1 converts to False."""
        assert device_bool_to_python(1) is False

    def test_on_value(self):
        """Device value 2 converts to True."""
        assert device_bool_to_python(2) is True

    def test_string_off(self):
        """String '1' is not equal to int 2, so returns False."""
        assert device_bool_to_python("1") is False

    def test_string_on(self):
        """String '2' is not equal to int 2, so returns False."""
        # String "2" != int 2 in Python, so result is False
        assert device_bool_to_python("2") is False

    def test_int_off(self):
        """Integer 1 converts to False."""
        result = device_bool_to_python(1)
        assert result is False

    def test_int_on(self):
        """Integer 2 converts to True."""
        result = device_bool_to_python(2)
        assert result is True

    def test_float_off(self):
        """Float 1.0 is not equal to 2."""
        assert device_bool_to_python(1.0) is False

    def test_float_on(self):
        """Float 2.0 equals int 2 in Python."""
        assert device_bool_to_python(2.0) is True

    def test_invalid_value_zero(self):
        """Invalid value 0 returns False (0 != 2)."""
        result = device_bool_to_python(0)
        assert result is False

    def test_invalid_value_three(self):
        """Invalid value 3 returns False (3 != 2)."""
        result = device_bool_to_python(3)
        assert result is False

    def test_invalid_value_negative(self):
        """Invalid value -1 returns False (-1 != 2)."""
        result = device_bool_to_python(-1)
        assert result is False

    @pytest.mark.parametrize("on_value", [2, 2.0])
    def test_on_value_variations(self, on_value):
        """Test various representations that equal 2."""
        # Numeric 2 and float 2.0 equal int 2
        assert device_bool_to_python(on_value) is True

    @pytest.mark.parametrize("off_value", [1, "1", 1.0, 0, 3, -1, "2"])
    def test_off_value_variations(self, off_value):
        """Test various representations of False value."""
        assert device_bool_to_python(off_value) is False


class TestBuiltinBoolForTouStatus:
    """Test built-in bool() for TOU status field (0/1 encoding).

    The touStatus field uses standard 0/1 encoding, so Python's built-in
    bool() is sufficient - no custom converter needed.
    """

    def test_enabled_state(self):
        """TOU enabled: 1 = True."""
        assert bool(1) is True

    def test_disabled_state(self):
        """TOU disabled: 0 = False."""
        assert bool(0) is False

    def test_nonzero_is_true(self):
        """Any non-zero value is truthy."""
        assert bool(2) is True
        assert bool(99) is True
        assert bool(-1) is True

    @pytest.mark.parametrize("value", [0, 0.0, "", [], {}, None])
    def test_falsy_values(self, value):
        """Test various falsy values."""
        assert bool(value) is False

    @pytest.mark.parametrize("value", [1, 2, -1, "text", [1], {1: 1}])
    def test_truthy_values(self, value):
        """Test various truthy values."""
        assert bool(value) is True


class TestTouOverrideConverter:
    """Test tou_override_to_python converter.

    TOU override status encoding converts override state to boolean.
    Device: 1 = Override Active (True), anything else = False
    NOTE: String values are NOT converted to int before comparison.
    """

    def test_override_active(self):
        """Override active state: 1 = True."""
        result = tou_override_to_python(1)
        assert isinstance(result, bool)
        assert result is True

    def test_override_inactive(self):
        """Override inactive state: 2 = False."""
        result = tou_override_to_python(2)
        assert isinstance(result, bool)
        assert result is False

    def test_string_active(self):
        """String '1' is not equal to int 1, so returns False."""
        # tou_override_to_python uses: bool(value == 1)
        # String "1" != int 1, so result is False
        assert tou_override_to_python("1") is False

    def test_string_inactive(self):
        """String '2' is not equal to int 1, so returns False."""
        result = tou_override_to_python("2")
        assert isinstance(result, bool)
        assert result is False

    def test_zero_value(self):
        """Value 0 is not equal to 1."""
        result = tou_override_to_python(0)
        assert isinstance(result, bool)
        assert result is False

    def test_other_value(self):
        """Other non-1 values are False."""
        result = tou_override_to_python(99)
        assert isinstance(result, bool)
        assert result is False

    @pytest.mark.parametrize("active_value", [1, 1.0])
    def test_active_variations(self, active_value):
        """Test numeric variations of active (value == 1)."""
        # Only numeric 1 and float 1.0 equal int 1
        assert tou_override_to_python(active_value) is True

    @pytest.mark.parametrize("inactive_value", [2, "2", 2.0, 0, 3, -1, "1"])
    def test_inactive_variations(self, inactive_value):
        """Test various representations of inactive (value != 1)."""
        assert tou_override_to_python(inactive_value) is False


class TestDiv10Converter:
    """Test div_10 converter (divide by 10).

    Used for fields that need precision of 0.1 units.
    Only divides numeric types (int, float), returns float(value) for others.
    """

    def test_zero(self):
        """0 / 10 = 0.0."""
        assert div_10(0) == 0.0

    def test_positive_value(self):
        """100 / 10 = 10.0."""
        assert div_10(100) == 10.0

    def test_negative_value(self):
        """-50 / 10 = -5.0."""
        assert div_10(-50) == -5.0

    def test_single_digit(self):
        """5 / 10 = 0.5."""
        assert div_10(5) == 0.5

    def test_float_input(self):
        """50.5 / 10 = 5.05."""
        assert div_10(50.5) == pytest.approx(5.05)

    def test_string_numeric(self):
        """String '100' is converted to float without division."""
        # div_10 converts non-numeric to float but doesn't divide
        result = div_10("100")
        assert result == pytest.approx(100.0)

    def test_large_value(self):
        """1000 / 10 = 100.0."""
        assert div_10(1000) == 100.0

    def test_very_small_value(self):
        """0.1 / 10 = 0.01."""
        assert div_10(0.1) == pytest.approx(0.01)

    def test_negative_small_value(self):
        """-0.5 / 10 = -0.05."""
        assert div_10(-0.5) == pytest.approx(-0.05)

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            (0, 0.0),
            (10, 1.0),
            (50, 5.0),
            (100, 10.0),
            (1000, 100.0),
            (-100, -10.0),
            (1.5, 0.15),
            (99.9, 9.99),
        ],
    )
    def test_known_values(self, input_value, expected):
        """Test known div_10 conversions for numeric types."""
        result = div_10(input_value)
        assert result == pytest.approx(expected, abs=0.001)


class TestEnumValidator:
    """Test enum_validator factory function.

    Creates validators that convert integer device values to enum values.
    """

    def test_validator_creation(self):
        """Enum validator can be created."""
        validator = enum_validator(OnOffFlag)
        assert callable(validator)

    def test_onoff_flag_off(self):
        """OnOffFlag: 1 = OFF."""
        validator = enum_validator(OnOffFlag)
        result = validator(OnOffFlag.OFF)
        assert result == OnOffFlag.OFF

    def test_onoff_flag_on(self):
        """OnOffFlag: 2 = ON."""
        validator = enum_validator(OnOffFlag)
        result = validator(OnOffFlag.ON)
        assert result == OnOffFlag.ON

    def test_onoff_flag_by_value_off(self):
        """Convert enum value 1 to OFF."""
        validator = enum_validator(OnOffFlag)
        result = validator(1)
        assert result == OnOffFlag.OFF

    def test_onoff_flag_by_value_on(self):
        """Convert enum value 2 to ON."""
        validator = enum_validator(OnOffFlag)
        result = validator(2)
        assert result == OnOffFlag.ON

    def test_dhw_operation_setting(self):
        """Test DhwOperationSetting enum validator."""
        validator = enum_validator(DhwOperationSetting)
        result = validator(DhwOperationSetting.HEAT_PUMP)
        assert result == DhwOperationSetting.HEAT_PUMP

    def test_dhw_all_values(self):
        """Test all DhwOperationSetting values."""
        validator = enum_validator(DhwOperationSetting)

        hp = DhwOperationSetting.HEAT_PUMP
        assert validator(hp) == hp
        elec = DhwOperationSetting.ELECTRIC
        assert validator(elec) == elec
        es = DhwOperationSetting.ENERGY_SAVER
        assert validator(es) == es
        hd = DhwOperationSetting.HIGH_DEMAND
        assert validator(hd) == hd
        vac = DhwOperationSetting.VACATION
        assert validator(vac) == vac

    def test_invalid_enum_value(self):
        """Invalid enum value should raise."""
        validator = enum_validator(OnOffFlag)
        with pytest.raises((ValueError, KeyError)):
            validator(99)

    def test_enum_pass_through(self):
        """Passing enum object returns same enum."""
        validator = enum_validator(OnOffFlag)
        enum_obj = OnOffFlag.ON
        result = validator(enum_obj)
        assert result is enum_obj

    @pytest.mark.parametrize(
        "input_val,expected_enum",
        [
            (1, OnOffFlag.OFF),
            (2, OnOffFlag.ON),
            (OnOffFlag.OFF, OnOffFlag.OFF),
            (OnOffFlag.ON, OnOffFlag.ON),
        ],
    )
    def test_onoff_conversions(self, input_val, expected_enum):
        """Test various input formats for OnOffFlag."""
        validator = enum_validator(OnOffFlag)
        result = validator(input_val)
        assert result == expected_enum

    def test_multiple_validators_independent(self):
        """Multiple validators are independent."""
        onoff_validator = enum_validator(OnOffFlag)
        dhw_validator = enum_validator(DhwOperationSetting)

        assert onoff_validator(1) == OnOffFlag.OFF
        assert dhw_validator(1) == DhwOperationSetting.HEAT_PUMP

    def test_validator_consistency(self):
        """Validator gives consistent results."""
        validator = enum_validator(OnOffFlag)
        result1 = validator(2)
        result2 = validator(2)
        assert result1 == result2
        assert result1 is result2

    def test_string_integer_conversion(self):
        """String integers are converted to enum."""
        validator = enum_validator(OnOffFlag)
        result = validator("1")
        assert result == OnOffFlag.OFF
