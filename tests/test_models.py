import pytest

from nwp500.models import (
    DeviceStatus,
    ReservationEntry,
    ReservationSchedule,
    fahrenheit_to_half_celsius,
)
from nwp500.unit_system import reset_unit_system, set_unit_system


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


class TestReservationEntry:
    """Tests for ReservationEntry pydantic model."""

    def setup_method(self):
        reset_unit_system()

    def teardown_method(self):
        reset_unit_system()

    def test_from_raw_dict(self):
        entry = ReservationEntry(
            enable=2, week=62, hour=6, min=30, mode=4, param=120
        )
        assert entry.enabled is True
        assert entry.days == [
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
        ]
        assert entry.time == "06:30"
        assert entry.mode_name == "High Demand"

    def test_temperature_fahrenheit(self):
        set_unit_system("us_customary")
        entry = ReservationEntry(param=120)
        assert entry.temperature == 140.0
        assert entry.unit == "°F"

    def test_temperature_celsius(self):
        set_unit_system("metric")
        entry = ReservationEntry(param=120)
        assert entry.temperature == 60.0
        assert entry.unit == "°C"

    def test_disabled_entry(self):
        entry = ReservationEntry(enable=1)
        assert entry.enabled is False

    def test_model_dump_includes_computed(self):
        set_unit_system("metric")
        entry = ReservationEntry(
            enable=1, week=64, hour=8, min=0, mode=3, param=100
        )
        d = entry.model_dump()
        assert "enabled" in d
        assert "days" in d
        assert "time" in d
        assert "temperature" in d
        assert "unit" in d
        assert "mode_name" in d
        assert d["days"] == ["Monday"]
        assert d["time"] == "08:00"

    def test_raw_fields_only(self):
        entry = ReservationEntry(
            enable=1, week=62, hour=6, min=30, mode=4, param=120
        )
        raw = entry.model_dump(
            include={"enable", "week", "hour", "min", "mode", "param"}
        )
        assert raw == {
            "enable": 1,
            "week": 62,
            "hour": 6,
            "min": 30,
            "mode": 4,
            "param": 120,
        }


class TestReservationSchedule:
    """Tests for ReservationSchedule pydantic model."""

    def setup_method(self):
        reset_unit_system()

    def teardown_method(self):
        reset_unit_system()

    def test_from_hex_string(self):
        set_unit_system("metric")
        # Hex: 02=enabled, 3e=week62, 06=hour6, 1e=min30, 04=mode4, 78=param120
        schedule = ReservationSchedule(
            reservationUse=2, reservation="023e061e0478"
        )
        assert schedule.enabled is True
        assert len(schedule.reservation) == 1
        entry = schedule.reservation[0]
        assert entry.enabled is True
        assert entry.temperature == 60.0

    def test_from_entry_list(self):
        schedule = ReservationSchedule(
            reservationUse=1,
            reservation=[
                {
                    "enable": 1,
                    "week": 1,
                    "hour": 7,
                    "min": 0,
                    "mode": 3,
                    "param": 100,
                },
            ],
        )
        assert schedule.enabled is False
        assert len(schedule.reservation) == 1
        assert schedule.reservation[0].hour == 7

    def test_empty_schedule(self):
        schedule = ReservationSchedule(reservationUse=0, reservation="")
        assert schedule.enabled is False
        assert len(schedule.reservation) == 0

    def test_skips_empty_entries(self):
        # 12 hex chars of zeros = one empty 6-byte entry
        schedule = ReservationSchedule(
            reservationUse=1,
            reservation="000000000000013e061e0478",
        )
        assert len(schedule.reservation) == 1
        assert schedule.reservation[0].week == 62
