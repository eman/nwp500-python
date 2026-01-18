"""Tests for dynamic temperature unit switching in models."""

from typing import Any

import pytest

from nwp500.enums import TemperatureType
from nwp500.models import DeviceStatus


def test_device_status_converts_to_fahrenheit_by_default(
    device_status_dict: dict[str, Any],
):
    """Test temperatures convert to Fahrenheit when default."""
    data = device_status_dict.copy()
    # 120 (raw) / 2 = 60°C -> 140°F
    data["dhwTemperature"] = 120
    # 350 (raw) / 10 = 35.0°C -> 95°F
    data["tankUpperTemperature"] = 350
    data["temperatureType"] = 2  # Explicitly Fahrenheit or Default

    status = DeviceStatus.model_validate(data)

    # Verify Fahrenheit (default)
    assert status.temperature_type == TemperatureType.FAHRENHEIT
    assert status.dhw_temperature == 140.0
    assert status.tank_upper_temperature == 95.0


def test_device_status_respects_celsius_type(
    device_status_dict: dict[str, Any],
):
    """Test temperatures stay in Celsius when temperature_type is CELSIUS."""
    data = device_status_dict.copy()
    data["temperatureType"] = 1  # CELSIUS
    # 120 (raw) / 2 = 60°C
    data["dhwTemperature"] = 120
    # 350 (raw) / 10 = 35.0°C
    data["tankUpperTemperature"] = 350

    status = DeviceStatus.model_validate(data)

    assert status.temperature_type == TemperatureType.CELSIUS
    assert status.dhw_temperature == 60.0
    assert status.tank_upper_temperature == 35.0


def test_device_status_respects_fahrenheit_explicit(
    device_status_dict: dict[str, Any],
):
    """Test temperatures convert to Fahrenheit when explicitly FAHRENHEIT."""
    data = device_status_dict.copy()
    data["temperatureType"] = 2  # FAHRENHEIT
    # 100 (raw) / 2 = 50°C -> 122°F
    data["dhwTemperature"] = 100

    status = DeviceStatus.model_validate(data)

    assert status.temperature_type == TemperatureType.FAHRENHEIT
    assert status.dhw_temperature == 122.0


def test_celsius_conversion_edge_cases(device_status_dict: dict[str, Any]):
    """Test precision handling for Celsius conversions."""
    # Test HalfCelsius precision (0.5 steps)
    half_c_data = device_status_dict.copy()
    half_c_data["temperatureType"] = 1
    half_c_data["dhwTemperature"] = 121  # 60.5°C

    status = DeviceStatus.model_validate(half_c_data)
    assert status.dhw_temperature == 60.5

    # Test DeciCelsius precision (0.1 steps)
    deci_c_data = device_status_dict.copy()
    deci_c_data["temperatureType"] = 1
    deci_c_data["tankUpperTemperature"] = 355  # 35.5°C

    status = DeviceStatus.model_validate(deci_c_data)
    assert status.tank_upper_temperature == 35.5


def test_missing_temperature_type_defaults_to_fahrenheit(
    device_status_dict: dict[str, Any],
):
    """Test missing temperature_type field results in Fahrenheit conversion."""
    data = device_status_dict.copy()
    if "temperatureType" in data:
        del data["temperatureType"]

    data["dhwTemperature"] = 100  # 50°C -> 122°F

    # Should not raise validation error and default to F
    status = DeviceStatus.model_validate(data)
    assert status.temperature_type == TemperatureType.FAHRENHEIT
    assert status.dhw_temperature == 122.0


def test_flow_rate_conversion(device_status_dict: dict[str, Any]):
    """Test flow rate conversion (LPM <-> GPM)."""
    # Case 1: Fahrenheit (Imperial) -> GPM
    # Raw value is LPM * 10
    # Let's say raw is 100 -> 10.0 LPM
    # 10.0 LPM * 0.264172 = 2.64172 GPM
    f_data = device_status_dict.copy()
    f_data["temperatureType"] = 2  # FAHRENHEIT
    f_data["currentDhwFlowRate"] = 100  # 10.0 LPM

    status_f = DeviceStatus.model_validate(f_data)
    assert status_f.temperature_type == TemperatureType.FAHRENHEIT
    # Should be GPM (rounded to 2 decimals)
    assert status_f.current_dhw_flow_rate == 2.64

    # Case 2: Celsius (Metric) -> LPM
    c_data = device_status_dict.copy()
    c_data["temperatureType"] = 1  # CELSIUS
    c_data["currentDhwFlowRate"] = 100  # 10.0 LPM

    status_c = DeviceStatus.model_validate(c_data)
    assert status_c.temperature_type == TemperatureType.CELSIUS
    assert status_c.current_dhw_flow_rate == 10.0  # Should be LPM


def test_volume_conversion(device_status_dict: dict[str, Any]):
    """Test volume conversion (Liters <-> Gallons)."""
    # Case 1: Fahrenheit (Imperial) -> Gallons
    # Assumption: Raw value is in Liters (Metric Native)
    # 100 Liters * 0.264172 = 26.4172 Gallons
    f_data = device_status_dict.copy()
    f_data["temperatureType"] = 2  # FAHRENHEIT
    f_data["cumulatedDhwFlowRate"] = 100.0  # 100 Liters

    status_f = DeviceStatus.model_validate(f_data)
    assert status_f.temperature_type == TemperatureType.FAHRENHEIT
    # We expect this to be converted to Gallons
    assert status_f.cumulated_dhw_flow_rate == 26.42

    # Case 2: Celsius (Metric) -> Liters
    c_data = device_status_dict.copy()
    c_data["temperatureType"] = 1  # CELSIUS
    c_data["cumulatedDhwFlowRate"] = 100.0  # 100 Liters

    status_c = DeviceStatus.model_validate(c_data)
    assert status_c.temperature_type == TemperatureType.CELSIUS
    # We expect this to stay in Liters
    assert status_c.cumulated_dhw_flow_rate == 100.0


def test_device_feature_celsius_temperature_ranges():
    """Test that DeviceFeature respects CELSIUS for temperature ranges."""
    from nwp500.models import DeviceFeature

    # Create a DeviceFeature with CELSIUS configuration
    # Raw values in half-Celsius: 81 -> 40.5°C, 131 -> 65.5°C, etc.
    feature_data = {
        "temperatureType": 1,  # CELSIUS
        "countryCode": 3,
        "modelTypeCode": 513,
        "controlTypeCode": 100,
        "volumeCode": 1,
        "controllerSwVersion": 1,
        "panelSwVersion": 1,
        "wifiSwVersion": 1,
        "controllerSwCode": 1,
        "panelSwCode": 1,
        "wifiSwCode": 1,
        "recircSwVersion": 1,
        "recircModelTypeCode": 0,
        "controllerSerialNumber": "ABC123",
        "dhwTemperatureSettingUse": 2,
        "tempFormulaType": 1,
        "dhwTemperatureMin": 81,  # 40.5°C
        "dhwTemperatureMax": 131,  # 65.5°C
        "freezeProtectionTempMin": 12,  # 6.0°C
        "freezeProtectionTempMax": 20,  # 10.0°C
        "recircTemperatureMin": 81,  # 40.5°C
        "recircTemperatureMax": 120,  # 60.0°C
    }

    feature = DeviceFeature.model_validate(feature_data)

    # Verify temperature_type is CELSIUS
    assert feature.temperature_type == TemperatureType.CELSIUS

    # Verify conversions are in Celsius
    assert feature.dhw_temperature_min == 40.5
    assert feature.dhw_temperature_max == 65.5
    assert feature.freeze_protection_temp_min == 6.0
    assert feature.freeze_protection_temp_max == 10.0
    assert feature.recirc_temperature_min == 40.5
    assert feature.recirc_temperature_max == 60.0

    # Verify get_field_unit returns °C
    assert feature.get_field_unit("dhw_temperature_min") == " °C"
    assert feature.get_field_unit("freeze_protection_temp_min") == " °C"
    assert feature.get_field_unit("recirc_temperature_min") == " °C"


def test_device_feature_fahrenheit_temperature_ranges():
    """Test that DeviceFeature respects FAHRENHEIT for temperature ranges."""
    from nwp500.models import DeviceFeature

    # Create a DeviceFeature with FAHRENHEIT configuration
    # Raw values: 81 (half-Celsius) = 40.5°C = 104.9°F when converted
    feature_data = {
        "temperatureType": 2,  # FAHRENHEIT
        "countryCode": 3,
        "modelTypeCode": 513,
        "controlTypeCode": 100,
        "volumeCode": 1,
        "controllerSwVersion": 1,
        "panelSwVersion": 1,
        "wifiSwVersion": 1,
        "controllerSwCode": 1,
        "panelSwCode": 1,
        "wifiSwCode": 1,
        "recircSwVersion": 1,
        "recircModelTypeCode": 0,
        "controllerSerialNumber": "ABC123",
        "dhwTemperatureSettingUse": 2,
        "tempFormulaType": 1,
        "dhwTemperatureMin": 81,  # 40.5°C -> 104.9°F
        "dhwTemperatureMax": 131,  # 65.5°C -> 149.9°F
        "freezeProtectionTempMin": 12,  # 6.0°C -> 42.8°F
        "freezeProtectionTempMax": 20,  # 10.0°C -> 50.0°F
        "recircTemperatureMin": 81,  # 40.5°C -> 104.9°F
        "recircTemperatureMax": 120,  # 60.0°C -> 140.0°F
    }

    feature = DeviceFeature.model_validate(feature_data)

    # Verify temperature_type is FAHRENHEIT
    assert feature.temperature_type == TemperatureType.FAHRENHEIT

    # Verify conversions are in Fahrenheit
    assert feature.dhw_temperature_min == 104.9
    assert feature.dhw_temperature_max == 149.9
    assert feature.freeze_protection_temp_min == 42.8
    assert feature.freeze_protection_temp_max == 50.0
    assert feature.recirc_temperature_min == 104.9
    assert feature.recirc_temperature_max == 140.0

    # Verify get_field_unit returns °F
    assert feature.get_field_unit("dhw_temperature_min") == " °F"
    assert feature.get_field_unit("freeze_protection_temp_min") == " °F"
    assert feature.get_field_unit("recirc_temperature_min") == " °F"


def test_device_feature_cli_output_celsius():
    """Test that CLI formatter correctly displays Celsius for DeviceFeature."""
    from contextlib import redirect_stdout
    from io import StringIO

    try:
        from nwp500.cli.output_formatters import print_device_info
        from nwp500.models import DeviceFeature
    except ImportError as e:
        pytest.skip(f"CLI not installed: {e}")

    # Create a DeviceFeature with CELSIUS configuration
    feature_data = {
        "temperatureType": 1,  # CELSIUS
        "countryCode": 3,
        "modelTypeCode": 513,
        "controlTypeCode": 100,
        "volumeCode": 1,
        "controllerSwVersion": 1,
        "panelSwVersion": 1,
        "wifiSwVersion": 1,
        "controllerSwCode": 1,
        "panelSwCode": 1,
        "wifiSwCode": 1,
        "recircSwVersion": 1,
        "recircModelTypeCode": 0,
        "controllerSerialNumber": "ABC123",
        "dhwTemperatureSettingUse": 2,
        "tempFormulaType": 1,
        "dhwTemperatureMin": 81,  # 40.5°C
        "dhwTemperatureMax": 131,  # 65.5°C
        "freezeProtectionTempMin": 12,  # 6.0°C
        "freezeProtectionTempMax": 20,  # 10.0°C
        "recircTemperatureMin": 81,  # 40.5°C
        "recircTemperatureMax": 120,  # 60.0°C
    }

    feature = DeviceFeature.model_validate(feature_data)

    # Capture CLI output
    output_buffer = StringIO()
    with redirect_stdout(output_buffer):
        print_device_info(feature)

    output = output_buffer.getvalue()

    # Verify that the output shows CELSIUS
    assert "CELSIUS" in output, "Output should contain CELSIUS"

    # Verify temperature ranges are displayed in Celsius with °C symbol
    assert "40.5 °C" in output, "DHW min should be 40.5 °C"
    assert "65.5 °C" in output, "DHW max should be 65.5 °C"
    assert "6.0 °C" in output, "Freeze protection min should be 6.0 °C"
    assert "10.0 °C" in output, "Freeze protection max should be 10.0 °C"
    assert "40.5 °C" in output, "Recirc min should be 40.5 °C"
    assert "60.0 °C" in output, "Recirc max should be 60.0 °C"

    # Verify Fahrenheit is NOT displayed
    assert "°F" not in output, (
        "Output should NOT contain °F when device is in CELSIUS mode"
    )
