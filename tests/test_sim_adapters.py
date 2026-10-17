"""Building the simulator's inputs from the library's models
(``nwp500.sim_adapters``)."""

from typing import Any

import pytest

pytest.importorskip("pandas")

from nwp500 import sim_adapters as sa
from nwp500.models import (
    DeviceFeature,
    DeviceStatus,
    ReservationSchedule,
    TOUInfo,
    TOUReservationSchedule,
)
from nwp500.sim import default_params
from nwp500.unit_system import reset_unit_system, set_unit_system

FEATURE: dict[str, Any] = {
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


@pytest.fixture
def status(device_status_dict: dict[str, Any]) -> DeviceStatus:
    return DeviceStatus.model_validate(
        device_status_dict
        | {
            "tankUpperTemperature": 586,  # 58.6 degC
            "tankLowerTemperature": 431,  # 43.1 degC
            "dhwTemperatureSetting": 121,  # 60.5 degC
            "hpLowerOnTempSetting": 81,  # 40.5 degC
            "dhwOperationSetting": 3,
            "compUse": 2,
            "heatUpperUse": 1,
            "heatLowerUse": 1,
        }
    )


@pytest.fixture(autouse=True)
def _units():
    yield
    reset_unit_system()


class TestTheHeater:
    def test_the_tank_in_fahrenheit_from_the_raw_fields(
        self, status: DeviceStatus
    ):
        state = sa.heater_state(status)
        assert state.upper_f == pytest.approx(58.6 * 9 / 5 + 32)
        assert state.lower_f == pytest.approx(43.1 * 9 / 5 + 32)
        assert state.compressor_running is True
        assert state.element_running is False

    def test_the_settings(self, status: DeviceStatus):
        s = sa.settings(status)
        assert s.setpoint_f == pytest.approx(140.9)
        assert s.hp_lower_on_f == pytest.approx(104.9)
        assert s.mode == 3

    @pytest.mark.parametrize("units", ["metric", "us_customary", None])
    def test_the_unit_preference_changes_nothing(
        self, status: DeviceStatus, units: Any
    ):
        set_unit_system(units)
        assert sa.heater_state(status).upper_f == pytest.approx(
            58.6 * 9 / 5 + 32
        )
        assert sa.settings(status).setpoint_f == pytest.approx(140.9)

    def test_an_element_running(self, device_status_dict: dict[str, Any]):
        s = DeviceStatus.model_validate(
            device_status_dict | {"heatLowerUse": 2, "compUse": 1}
        )
        state = sa.heater_state(s)
        assert state.element_running and not state.compressor_running

    @pytest.mark.parametrize(("code", "gal"), [(1, 50), (2, 65), (3, 80)])
    def test_the_parameters_follow_the_tank_size(self, code: int, gal: int):
        p = sa.params(
            DeviceFeature.model_validate(FEATURE | {"volumeCode": code})
        )
        assert p == default_params(code)
        assert p.tank.volume_gal == pytest.approx(63.2 * gal / 65)


class TestTheSchedules:
    def test_reservations_keep_the_devices_terms(self):
        sched = ReservationSchedule.model_validate(
            {
                "reservationUse": 2,
                "reservation": [
                    {
                        "enable": 2,
                        "week": 124,
                        "hour": 6,
                        "min": 30,
                        "mode": 4,
                        "param": 124,
                    },
                    {
                        "enable": 1,
                        "week": 130,
                        "hour": 22,
                        "min": 0,
                        "mode": 1,
                        "param": 110,
                    },
                ],
            }
        )
        s = sa.schedules(reservations=sched)
        assert s.reservations_enabled is True
        first, second = s.reservations
        assert (first.week, first.hour, first.minute) == (124, 6, 30)
        assert (first.mode, first.setpoint_half_c, first.enabled) == (
            4,
            124,
            True,
        )
        assert second.enabled is False

    def test_a_switched_off_reservation_schedule(self):
        sched = ReservationSchedule.model_validate(
            {"reservationUse": 1, "reservation": []}
        )
        assert sa.schedules(reservations=sched).reservations_enabled is False

    def test_tou_from_the_rest_read(self):
        info = TOUInfo.model_validate(
            {
                "touInfo": {
                    "schedule": [
                        {
                            "season": 3087,
                            "interval": [
                                {
                                    "week": 124,
                                    "startHour": 0,
                                    "startMinute": 0,
                                    "endHour": 15,
                                    "endMinute": 59,
                                    "priceMin": 30000,
                                    "priceMax": 30000,
                                    "decimalPoint": 5,
                                },
                                {
                                    "week": 124,
                                    "startHour": 16,
                                    "startMinute": 0,
                                    "endHour": 20,
                                    "endMinute": 59,
                                    "priceMin": 50000,
                                    "priceMax": 50000,
                                    "decimalPoint": 5,
                                },
                            ],
                        }
                    ]
                }
            }
        )
        s = sa.schedules(tou=info, tou_enabled=True)
        assert s.tou_enabled is True
        assert [
            (p.season, p.week, p.start_hour, p.end_hour) for p in s.tou_periods
        ] == [
            (3087, 124, 0, 15),
            (3087, 124, 16, 20),
        ]
        assert s.tou_periods[1].price_max == 50000

    def test_tou_from_the_mqtt_confirmation_carries_its_switch(self):
        conf = TOUReservationSchedule.model_validate(
            {
                "reservationUse": 2,
                "reservation": [
                    {
                        "season": 4095,
                        "week": 254,
                        "startHour": 16,
                        "startMinute": 0,
                        "endHour": 20,
                        "endMinute": 59,
                        "priceMin": 10,
                        "priceMax": 25,
                        "decimalPoint": 2,
                    }
                ],
            }
        )
        s = sa.schedules(tou=conf)
        assert s.tou_enabled is True
        (p,) = s.tou_periods
        assert (p.start_hour, p.start_minute, p.end_hour, p.end_minute) == (
            16,
            0,
            20,
            59,
        )
