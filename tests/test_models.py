from typing import ClassVar

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


class TestTriStateFlags:
    """Status flags the device may decline to report.

    The device encodes these as 0 = UNKNOWN, 1 = OFF, 2 = ON. The vendor's
    own client decodes exactly this set through ``KDEnum.MgppOnOFFFlag``,
    declared ``UNKNOWN(0), OFF(1), ON(2)``, so 0 must not become False.
    """

    #: Fields the NaviLink app decodes through its on/off enum. Kept here so
    #: the evidenced set is asserted rather than assumed.
    TRISTATE_FIELDS = (
        "operation_busy",
        "comp_use",
        "anti_legionella_use",
        "anti_legionella_operation_busy",
        "heat_upper_use",
        "heat_lower_use",
        "air_filter_alarm_use",
        "recirc_reservation_use",
    )

    ALIASES: ClassVar[dict[str, str]] = {
        "operation_busy": "operationBusy",
        "comp_use": "compUse",
        "anti_legionella_use": "antiLegionellaUse",
        "anti_legionella_operation_busy": "antiLegionellaOperationBusy",
        "heat_upper_use": "heatUpperUse",
        "heat_lower_use": "heatLowerUse",
        "air_filter_alarm_use": "airFilterAlarmUse",
        "recirc_reservation_use": "recircReservationUse",
    }

    @pytest.mark.parametrize("field", TRISTATE_FIELDS)
    def test_zero_becomes_none(self, default_status_data, field):
        """0 surfaces as None rather than a fabricated OFF."""
        data = dict(default_status_data)
        data[self.ALIASES[field]] = 0
        assert getattr(DeviceStatus(**data), field) is None

    @pytest.mark.parametrize("field", TRISTATE_FIELDS)
    def test_one_is_off(self, default_status_data, field):
        """1 is a real OFF and stays False."""
        data = dict(default_status_data)
        data[self.ALIASES[field]] = 1
        assert getattr(DeviceStatus(**data), field) is False

    @pytest.mark.parametrize("field", TRISTATE_FIELDS)
    def test_two_is_on(self, default_status_data, field):
        """2 is a real ON and stays True."""
        data = dict(default_status_data)
        data[self.ALIASES[field]] = 2
        assert getattr(DeviceStatus(**data), field) is True

    def test_unknown_is_falsy_but_distinguishable(self, default_status_data):
        """None is falsy, so naive `if flag:` keeps its old behaviour.

        The migration risk is the opposite check: `if not flag` and
        `flag is False` no longer mean the same thing.
        """
        data = dict(default_status_data)
        data["compUse"] = 0
        status = DeviceStatus(**data)
        assert not status.comp_use
        assert status.comp_use is not False

    def test_capability_flags_are_unaffected(self, default_status_data):
        """Plain DeviceBool status fields still collapse 0 to False."""
        data = dict(default_status_data)
        data["dhwUse"] = 0
        assert DeviceStatus(**data).dhw_use is False


class TestEnergyFields:
    """The energy capacity fields were misnamed and mis-scaled.

    See docs/explanation/tank-energy.rst: availableEnergyCapacity is a
    heating deficit, not available energy, and the device quantum is
    4 Wh/count rather than the 10 Wh assumed before 10.0.
    """

    def test_wire_aliases_still_parse(self, device_status_dict):
        """The protocol field names are unchanged on the wire."""
        status = DeviceStatus(**device_status_dict)
        assert status.full_recovery_energy == pytest.approx(6320.0)
        assert status.energy_to_setpoint == pytest.approx(4664.0)

    def test_old_names_are_gone(self, device_status_dict):
        """The misleading names are removed, not aliased.

        Per the project's backward compatibility policy, renamed fields
        are removed outright rather than kept as shims.
        """
        status = DeviceStatus(**device_status_dict)
        assert not hasattr(status, "total_energy_capacity")
        assert not hasattr(status, "available_energy_capacity")

    def test_deficit_is_smaller_than_full_recovery(self, device_status_dict):
        """A partly charged tank needs less than a full recovery costs."""
        status = DeviceStatus(**device_status_dict)
        assert status.energy_to_setpoint < status.full_recovery_energy

    def test_protocol_dump_uses_wire_names(self, device_status_dict):
        """Renaming the Python fields must not change what is sent."""
        status = DeviceStatus(**device_status_dict)
        dumped = status.to_protocol_dict()
        assert "totalEnergyCapacity" in dumped
        assert "availableEnergyCapacity" in dumped
        assert "full_recovery_energy" not in dumped


class TestUsableEnergy:
    """Drawable energy, derived by cancelling the setpoint."""

    def test_is_the_difference(self, device_status_dict):
        """Usable energy is full recovery minus the remaining deficit."""
        status = DeviceStatus(**device_status_dict)
        assert status.usable_energy == pytest.approx(
            status.full_recovery_energy - status.energy_to_setpoint
        )

    def test_known_value(self, device_status_dict):
        """1580 and 1166 raw counts at 4 Wh give 6320 - 4664 Wh."""
        status = DeviceStatus(**device_status_dict)
        assert status.usable_energy == pytest.approx(1656.0)

    def test_zero_when_tank_at_reference(self, device_status_dict):
        """A tank at the reference temperature has nothing drawable."""
        d = dict(device_status_dict)
        d["availableEnergyCapacity"] = d["totalEnergyCapacity"]
        assert DeviceStatus(**d).usable_energy == 0.0

    def test_clamped_below_reference(self, device_status_dict):
        """Below the reference the result clamps rather than going negative."""
        d = dict(device_status_dict)
        d["availableEnergyCapacity"] = d["totalEnergyCapacity"] + 500
        assert DeviceStatus(**d).usable_energy == 0.0

    def test_independent_of_setpoint(self, device_status_dict):
        """The setpoint cancels, so raising it must not change the result.

        This is the property that makes usable_energy a state of charge
        while the two raw fields are not: raising the setpoint inflates
        both of them by the same amount.
        """
        base = DeviceStatus(**device_status_dict)
        d = dict(device_status_dict)
        bump = 200  # raw counts of extra setpoint headroom
        d["totalEnergyCapacity"] += bump
        d["availableEnergyCapacity"] += bump
        assert DeviceStatus(**d).usable_energy == pytest.approx(
            base.usable_energy
        )

    def test_excluded_from_protocol_dump(self, device_status_dict):
        """Computed fields must never be sent back to the device."""
        status = DeviceStatus(**device_status_dict)
        assert "usable_energy" not in status.to_protocol_dict()


class TestDeviceFeatureWireAliases:
    """Aliases must match the keys the device actually sends."""

    #: Only the fields DeviceFeature requires; capability flags are optional.
    MINIMAL_FEATURE: ClassVar[dict] = {
        "countryCode": 3,
        "modelTypeCode": 240,
        "controlTypeCode": 1,
        "volumeCode": 2,
        "controllerSwVersion": 184877056,
        "panelSwVersion": 0,
        "wifiSwVersion": 34013184,
        "controllerSwCode": 33556241,
        "panelSwCode": 0,
        "wifiSwCode": 268435985,
        "recircSwVersion": 0,
        "recircModelTypeCode": 0,
        "controllerSerialNumber": "ABC123",
        "dhwTemperatureSettingUse": 2,
    }

    def test_mixing_valve_reads_the_devices_misspelled_key(self):
        """The device sends ``mixingValueUse`` (sic), not ``mixingValveUse``."""
        from nwp500.models import DeviceFeature

        feature = DeviceFeature.model_validate(
            self.MINIMAL_FEATURE | {"mixingValueUse": 2}
        )

        assert feature.mixing_valve_use is True

    def test_mixing_valve_ignores_the_corrected_spelling(self):
        """``mixingValveUse`` is not a key the device ever sends."""
        from nwp500.models import DeviceFeature

        feature = DeviceFeature.model_validate(
            self.MINIMAL_FEATURE | {"mixingValveUse": 2}
        )

        assert feature.mixing_valve_use is False

    def test_mixing_valve_defaults_when_absent(self):
        from nwp500.models import DeviceFeature

        feature = DeviceFeature.model_validate(self.MINIMAL_FEATURE)

        assert feature.mixing_valve_use is False
