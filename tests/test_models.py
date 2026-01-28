import pytest

from nwp500.models import DeviceStatus, fahrenheit_to_half_celsius


@pytest.fixture
def default_status_data():
    """Provides a default dictionary for DeviceStatus model."""
    return {
        "command": 0,
        "outsideTemperature": 0.0,
        "specialFunctionStatus": 0,
        "errorCode": 0,
        "subErrorCode": 0,
        "smartDiagnostic": 0,
        "faultStatus1": 0,
        "faultStatus2": 0,
        "wifiRssi": 0,
        "dhwChargePer": 0.0,
        "drEventStatus": 0,
        "vacationDaySetting": 0,
        "vacationDayElapsed": 0,
        "antiLegionellaPeriod": 0,
        "programReservationType": 0,
        "tempFormulaType": 0,
        "currentStatenum": 0,
        "targetFanRpm": 0,
        "currentFanRpm": 0,
        "fanPwm": 0,
        "mixingRate": 0.0,
        "eevStep": 0,
        "airFilterAlarmPeriod": 0,
        "airFilterAlarmElapsed": 0,
        "cumulatedOpTimeEvaFan": 0,
        "cumulatedDhwFlowRate": 0.0,
        "touStatus": 0,
        "drOverrideStatus": 0,
        "touOverrideStatus": 0,
        "totalEnergyCapacity": 0.0,
        "availableEnergyCapacity": 0.0,
        "recircOperationMode": 0,
        "recircPumpOperationStatus": 0,
        "recircHotBtnReady": 0,
        "recircOperationReason": 0,
        "recircErrorStatus": 0,
        "currentInstPower": 0.0,
        "didReload": 0,
        "operationBusy": 0,
        "freezeProtectionUse": 0,
        "dhwUse": 0,
        "dhwUseSustained": 0,
        "programReservationUse": 0,
        "ecoUse": 0,
        "compUse": 0,
        "eevUse": 0,
        "evaFanUse": 0,
        "shutOffValveUse": 0,
        "conOvrSensorUse": 0,
        "wtrOvrSensorUse": 0,
        "antiLegionellaUse": 0,
        "antiLegionellaOperationBusy": 0,
        "errorBuzzerUse": 0,
        "currentHeatUse": 0,
        "heatUpperUse": 0,
        "heatLowerUse": 0,
        "scaldUse": 0,
        "airFilterAlarmUse": 0,
        "recircOperationBusy": 0,
        "recircReservationUse": 0,
        "dhwTemperature": 0,
        "dhwTemperatureSetting": 0,
        "dhwTargetTemperatureSetting": 0,
        "freezeProtectionTemperature": 0,
        "dhwTemperature2": 0,
        "hpUpperOnTempSetting": 0,
        "hpUpperOffTempSetting": 0,
        "hpLowerOnTempSetting": 0,
        "hpLowerOffTempSetting": 0,
        "heUpperOnTempSetting": 0,
        "heUpperOffTempSetting": 0,
        "heLowerOnTempSetting": 0,
        "heLowerOffTempSetting": 0,
        "heatMinOpTemperature": 0,
        "recircTempSetting": 0,
        "recircTemperature": 0,
        "recircFaucetTemperature": 0,
        "currentInletTemperature": 0,
        "currentDhwFlowRate": 0,
        "hpUpperOnDiffTempSetting": 0,
        "hpUpperOffDiffTempSetting": 0,
        "hpLowerOnDiffTempSetting": 0,
        "hpLowerOffDiffTempSetting": 0,
        "heUpperOnDiffTempSetting": 0,
        "heUpperOffDiffTempSetting": 0,
        "heLowerOnTDiffempSetting": 0,
        "heLowerOffDiffTempSetting": 0,
        "recircDhwFlowRate": 0,
        "tankUpperTemperature": 0,
        "tankLowerTemperature": 0,
        "dischargeTemperature": 0,
        "suctionTemperature": 0,
        "evaporatorTemperature": 0,
        "ambientTemperature": 0,
        "targetSuperHeat": 0,
        "currentSuperHeat": 0,
        "operationMode": 0,
        "dhwOperationSetting": 3,
        "temperatureType": 2,
        "freezeProtectionTempMin": 43.0,
        "freezeProtectionTempMax": 65.0,
    }


def test_device_status_half_celsius_to_fahrenheit(default_status_data):
    """Test HalfCelsiusToF conversion."""
    default_status_data["dhwTemperature"] = 122
    status = DeviceStatus.model_validate(default_status_data)
    assert status.dhw_temperature == pytest.approx(141.8)


def test_device_status_deci_celsius_to_fahrenheit(default_status_data):
    """Test DeciCelsiusToF conversion."""
    default_status_data["tankUpperTemperature"] = 489
    status = DeviceStatus.model_validate(default_status_data)
    assert status.tank_upper_temperature == pytest.approx(120.0, abs=0.1)


def test_device_status_div10(default_status_data):
    """Test currentInletTemperature HalfCelsiusToF conversion."""
    # Raw value 100 = 50°C = (50 * 1.8) + 32 = 122°F
    default_status_data["currentInletTemperature"] = 100
    status = DeviceStatus.model_validate(default_status_data)
    assert status.current_inlet_temperature == 122.0


def test_fahrenheit_to_half_celsius():
    """Test fahrenheit_to_half_celsius conversion for device commands."""
    # Standard temperature conversions
    assert fahrenheit_to_half_celsius(140.0) == 120  # 60°C × 2
    assert fahrenheit_to_half_celsius(120.0) == 98  # ~48.9°C × 2
    assert fahrenheit_to_half_celsius(95.0) == 70  # 35°C × 2
    assert fahrenheit_to_half_celsius(150.0) == 131  # ~65.6°C × 2
    assert fahrenheit_to_half_celsius(130.0) == 109  # ~54.4°C × 2


def test_temperature_zero_values_are_none(default_status_data):
    """Test that zero temperature values are converted to None (N/A)."""
    # Test HalfCelsiusToPreferred with 0
    default_status_data["dhwTemperature"] = 0
    default_status_data["currentInletTemperature"] = 0
    status = DeviceStatus.model_validate(default_status_data)
    assert status.dhw_temperature is None
    assert status.current_inlet_temperature is None

    # Test DeciCelsiusToPreferred with 0
    default_status_data["tankUpperTemperature"] = 0
    default_status_data["ambientTemperature"] = 0
    status = DeviceStatus.model_validate(default_status_data)
    assert status.tank_upper_temperature is None
    assert status.ambient_temperature is None

    # Test RawCelsiusToPreferred with 0
    default_status_data["outsideTemperature"] = 0
    status = DeviceStatus.model_validate(default_status_data)
    assert status.outside_temperature is None


def test_temperature_non_zero_values_are_converted(default_status_data):
    """Test that non-zero temperature values are properly converted."""
    # Test HalfCelsiusToPreferred with non-zero value
    default_status_data["dhwTemperature"] = 122
    status = DeviceStatus.model_validate(default_status_data)
    assert status.dhw_temperature == pytest.approx(141.8)

    # Test DeciCelsiusToPreferred with non-zero value
    default_status_data["tankUpperTemperature"] = 489
    status = DeviceStatus.model_validate(default_status_data)
    assert status.tank_upper_temperature == pytest.approx(120.0, abs=0.1)

    # Test RawCelsiusToPreferred with non-zero value
    default_status_data["outsideTemperature"] = 50  # 25°C = 77°F
    status = DeviceStatus.model_validate(default_status_data)
    assert status.outside_temperature == pytest.approx(77.0, abs=1.0)


def test_mixing_rate_zero_is_none(default_status_data):
    """Test that mixing_rate of 0 is treated as None (feature not available)."""
    default_status_data["mixingRate"] = 0
    status = DeviceStatus.model_validate(default_status_data)
    assert status.mixing_rate is None


def test_mixing_rate_non_zero_is_preserved(default_status_data):
    """Test that non-zero mixing_rate values are preserved."""
    default_status_data["mixingRate"] = 50.5
    status = DeviceStatus.model_validate(default_status_data)
    assert status.mixing_rate == 50.5


def test_he_lower_temp_settings_zero_is_none(default_status_data):
    """Test heating element lower temp settings with 0 are None."""
    default_status_data["heLowerOnTempSetting"] = 0
    default_status_data["heLowerOffTempSetting"] = 0
    status = DeviceStatus.model_validate(default_status_data)
    assert status.he_lower_on_temp_setting is None
    assert status.he_lower_off_temp_setting is None


def test_he_lower_temp_settings_non_zero_are_converted(default_status_data):
    """Test non-zero heating element lower temps are converted."""
    # 122 half-celsius = 61°C = 141.8°F
    default_status_data["heLowerOnTempSetting"] = 122
    default_status_data["heLowerOffTempSetting"] = 100
    status = DeviceStatus.model_validate(default_status_data)
    assert status.he_lower_on_temp_setting == pytest.approx(141.8)
    assert status.he_lower_off_temp_setting == pytest.approx(122.0)


def test_recirc_status_fields_zero_is_none(default_status_data):
    """Test recirculation status fields with 0 are None."""
    default_status_data["recircOperationMode"] = 0
    default_status_data["recircPumpOperationStatus"] = 0
    default_status_data["recircHotBtnReady"] = 0
    default_status_data["recircOperationReason"] = 0
    default_status_data["recircErrorStatus"] = 0
    default_status_data["recircOperationBusy"] = 0
    default_status_data["recircReservationUse"] = 0
    status = DeviceStatus.model_validate(default_status_data)
    assert status.recirc_operation_mode is None
    assert status.recirc_pump_operation_status is None
    assert status.recirc_hot_btn_ready is None
    assert status.recirc_operation_reason is None
    assert status.recirc_error_status is None
    assert status.recirc_operation_busy is None
    assert status.recirc_reservation_use is None


def test_recirc_status_fields_non_zero_are_preserved(default_status_data):
    """Test that non-zero recirculation status fields are properly preserved."""
    from nwp500.enums import RecirculationMode

    default_status_data["recircOperationMode"] = 2  # BUTTON mode
    default_status_data["recircPumpOperationStatus"] = 1
    default_status_data["recircHotBtnReady"] = 5
    default_status_data["recircOperationReason"] = 3
    default_status_data["recircErrorStatus"] = 0  # 0 will become None
    default_status_data["recircOperationBusy"] = 2  # ON (True)
    default_status_data["recircReservationUse"] = 1  # OFF (False)
    status = DeviceStatus.model_validate(default_status_data)
    assert status.recirc_operation_mode == RecirculationMode.BUTTON
    assert status.recirc_pump_operation_status == 1
    assert status.recirc_hot_btn_ready == 5
    assert status.recirc_operation_reason == 3
    assert status.recirc_error_status is None
    assert status.recirc_operation_busy is True
    assert status.recirc_reservation_use is False
