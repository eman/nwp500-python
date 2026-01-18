"""Tests for dynamic temperature unit switching in models."""
from typing import Any

from nwp500.enums import TemperatureType
from nwp500.models import DeviceStatus


def test_device_status_converts_to_fahrenheit_by_default(device_status_dict: dict[str, Any]):
    """Test that temperatures convert to Fahrenheit when temperature_type is default (Fahrenheit)."""
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


def test_device_status_respects_celsius_type(device_status_dict: dict[str, Any]):
    """Test that temperatures stay in Celsius when temperature_type is CELSIUS."""
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


def test_device_status_respects_fahrenheit_explicit(device_status_dict: dict[str, Any]):
    """Test that temperatures convert to Fahrenheit when temperature_type is explicitly FAHRENHEIT."""
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


def test_missing_temperature_type_defaults_to_fahrenheit(device_status_dict: dict[str, Any]):
    """Test that missing temperature_type field results in Fahrenheit conversion."""
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
    assert status_f.current_dhw_flow_rate == 2.64  # Should be GPM (rounded to 2 decimals)

    # Case 2: Celsius (Metric) -> LPM
    c_data = device_status_dict.copy()
    c_data["temperatureType"] = 1  # CELSIUS
    c_data["currentDhwFlowRate"] = 100  # 10.0 LPM
    
    status_c = DeviceStatus.model_validate(c_data)
    assert status_c.temperature_type == TemperatureType.CELSIUS
    assert status_c.current_dhw_flow_rate == 10.0  # Should be LPM

