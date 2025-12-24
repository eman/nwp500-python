"""Tests for device capability checking."""

from unittest.mock import Mock

import pytest

from nwp500.device_capabilities import MqttDeviceCapabilityChecker
from nwp500.enums import DHWControlTypeFlag
from nwp500.exceptions import DeviceCapabilityError


class TestMqttDeviceCapabilityChecker:
    """Tests for MqttDeviceCapabilityChecker."""

    def test_supports_true_feature(self) -> None:
        """Test supports with feature that returns True."""
        mock_feature = Mock()
        mock_feature.power_use = True
        assert MqttDeviceCapabilityChecker.supports("power_use", mock_feature)

    def test_supports_false_feature(self) -> None:
        """Test supports with feature that returns False."""
        mock_feature = Mock()
        mock_feature.power_use = False
        assert not MqttDeviceCapabilityChecker.supports(
            "power_use", mock_feature
        )

    def test_supports_unknown_feature_raises_value_error(self) -> None:
        """Test that unknown feature raises ValueError."""
        mock_feature = Mock()
        with pytest.raises(ValueError, match="Unknown controllable feature"):
            MqttDeviceCapabilityChecker.supports(
                "unknown_feature", mock_feature
            )

    def test_assert_supported_success(self) -> None:
        """Test assert_supported with supported feature."""
        mock_feature = Mock()
        mock_feature.power_use = True
        # Should not raise
        MqttDeviceCapabilityChecker.assert_supported("power_use", mock_feature)

    def test_assert_supported_failure(self) -> None:
        """Test assert_supported with unsupported feature."""
        mock_feature = Mock()
        mock_feature.power_use = False
        with pytest.raises(DeviceCapabilityError):
            MqttDeviceCapabilityChecker.assert_supported(
                "power_use", mock_feature
            )

    def test_dhw_temperature_control_enabled(self) -> None:
        """Test DHW temperature control detection when enabled."""
        mock_feature = Mock()
        mock_feature.dhw_temperature_setting_use = (
            DHWControlTypeFlag.ENABLE_1_DEGREE
        )
        assert MqttDeviceCapabilityChecker.supports(
            "dhw_temperature_setting_use", mock_feature
        )

    def test_dhw_temperature_control_disabled(self) -> None:
        """Test DHW temperature control detection when disabled."""
        mock_feature = Mock()
        mock_feature.dhw_temperature_setting_use = DHWControlTypeFlag.DISABLE
        assert not MqttDeviceCapabilityChecker.supports(
            "dhw_temperature_setting_use", mock_feature
        )

    def test_dhw_temperature_control_unknown(self) -> None:
        """Test DHW temperature control detection when UNKNOWN."""
        mock_feature = Mock()
        mock_feature.dhw_temperature_setting_use = DHWControlTypeFlag.UNKNOWN
        assert not MqttDeviceCapabilityChecker.supports(
            "dhw_temperature_setting_use", mock_feature
        )

    def test_get_available_controls(self) -> None:
        """Test get_available_controls returns all feature statuses."""
        mock_feature = Mock()
        mock_feature.power_use = True
        mock_feature.dhw_use = False
        mock_feature.dhw_temperature_setting_use = (
            DHWControlTypeFlag.ENABLE_1_DEGREE
        )
        mock_feature.holiday_use = True
        mock_feature.program_reservation_use = False
        mock_feature.recirculation_use = True
        mock_feature.recirc_reservation_use = False
        mock_feature.anti_legionella_setting_use = True

        controls = MqttDeviceCapabilityChecker.get_available_controls(
            mock_feature
        )

        assert controls["power_use"] is True
        assert controls["dhw_use"] is False
        assert controls["dhw_temperature_setting_use"] is True
        assert controls["holiday_use"] is True
        assert controls["program_reservation_use"] is False
        assert controls["recirculation_use"] is True
        assert controls["recirc_reservation_use"] is False
        assert controls["anti_legionella_setting_use"] is True
        assert len(controls) == 8

    def test_register_capability(self) -> None:
        """Test custom capability registration."""
        mock_feature = Mock()
        custom_check = lambda f: True  # noqa: E731

        MqttDeviceCapabilityChecker.register_capability(
            "custom_feature", custom_check
        )

        try:
            assert MqttDeviceCapabilityChecker.supports(
                "custom_feature", mock_feature
            )
        finally:
            # Clean up
            del MqttDeviceCapabilityChecker._CAPABILITY_MAP["custom_feature"]

    def test_register_capability_override(self) -> None:
        """Test overriding an existing capability."""
        original = MqttDeviceCapabilityChecker._CAPABILITY_MAP["power_use"]
        mock_feature = Mock()

        try:
            # Override to always return False
            MqttDeviceCapabilityChecker.register_capability(
                "power_use", lambda f: False
            )
            mock_feature.power_use = True
            assert not MqttDeviceCapabilityChecker.supports(
                "power_use", mock_feature
            )
        finally:
            # Restore original
            MqttDeviceCapabilityChecker._CAPABILITY_MAP["power_use"] = original
