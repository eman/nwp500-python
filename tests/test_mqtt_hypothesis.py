import pytest

from hypothesis import given, strategies as st
from nwp500.enums import TemperatureType
from nwp500.models import DeviceStatus

# Base payload matching required fields in DeviceStatus
BASE_PAYLOAD = {
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
    "dhwOperationBusy": 0,
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


@given(
    temperature_type_int=st.sampled_from([1, 2]),
    dhw_temp_raw=st.integers(min_value=0, max_value=200),  # 0 to 100°C
    tank_temp_raw=st.integers(min_value=0, max_value=1000),  # 0 to 100°C (deci)
    flow_rate_raw=st.integers(min_value=0, max_value=500),  # 0 to 50 LPM
)
def test_device_status_fuzzing(
    temperature_type_int, dhw_temp_raw, tank_temp_raw, flow_rate_raw
):
    """
    Fuzz test parsing of DeviceStatus with varying temperature types and values.
    """
    # Create a copy of the base payload
    payload = BASE_PAYLOAD.copy()

    # Update with fuzzed values
    payload["temperatureType"] = temperature_type_int
    payload["dhwTemperature"] = dhw_temp_raw
    payload["tankUpperTemperature"] = tank_temp_raw
    payload["currentDhwFlowRate"] = flow_rate_raw

    # Parse the model
    status = DeviceStatus.model_validate(payload)

    # Assertions based on temperature type
    is_celsius = temperature_type_int == 1  # 1=Celsius, 2=Fahrenheit

    # 1. Check Temperature Type parsing
    if is_celsius:
        assert status.temperature_type == TemperatureType.CELSIUS
    else:
        assert status.temperature_type == TemperatureType.FAHRENHEIT

    # 2. Check DHW Temperature (HalfCelsius)
    # Raw value is half-celsius.
    celsius_val = dhw_temp_raw / 2.0
    if is_celsius:
        assert status.dhw_temperature == pytest.approx(celsius_val)
    else:
        fahrenheit_val = (celsius_val * 9 / 5) + 32
        assert status.dhw_temperature == pytest.approx(fahrenheit_val)

    # 3. Check Tank Temperature (DeciCelsius)
    # Raw value is deci-celsius.
    tank_celsius_val = tank_temp_raw / 10.0
    if is_celsius:
        assert status.tank_upper_temperature == pytest.approx(tank_celsius_val)
    else:
        tank_fahrenheit_val = (tank_celsius_val * 9 / 5) + 32
        # Note: DeciCelsiusToPreferred in models calls DeciCelsius(raw).to_preferred(
        # is_celsius) to_preferred -> to_fahrenheit -> standard conversion
        # We need to match the exact logic if there's rounding involved, but simple
        # math should match approx.
        assert status.tank_upper_temperature == pytest.approx(
            tank_fahrenheit_val
        )

    # 4. Check Flow Rate (LPM * 10)
    lpm_val = flow_rate_raw / 10.0
    if is_celsius:
        assert status.current_dhw_flow_rate == pytest.approx(lpm_val)
    else:
        # Imperial: LPM to GPM
        gpm_val = round(lpm_val * 0.264172, 2)
        assert status.current_dhw_flow_rate == pytest.approx(gpm_val)
