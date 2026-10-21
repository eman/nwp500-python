"""Building the simulator's inputs from the library's models
(``nwp500.sim_adapters``)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
from nwp500.sim import (
    Environment,
    HeaterState,
    Loads,
    Scenario,
    Settings,
    default_params,
    simulate,
    standby,
)
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
def _units() -> Iterator[None]:
    yield
    reset_unit_system()


class TestTheHeater:
    def test_the_tank_in_fahrenheit_from_the_raw_fields(
        self, status: DeviceStatus
    ) -> None:
        state = sa.heater_state(status)
        assert state.upper_f == pytest.approx(58.6 * 9 / 5 + 32)
        assert state.lower_f == pytest.approx(43.1 * 9 / 5 + 32)
        assert state.compressor_running is True
        assert state.element_running is False

    def test_the_settings(self, status: DeviceStatus) -> None:
        s = sa.settings(status)
        assert s.setpoint_f == pytest.approx(140.9)
        assert s.hp_lower_on_f == pytest.approx(104.9)
        assert s.mode == 3

    def test_a_standby_status_is_refused(self, status: DeviceStatus) -> None:
        standby_status = status.model_copy(update={"dhw_operation_setting": 0})
        with pytest.raises(ValueError, match="Standby"):
            sa.settings(standby_status)

    @pytest.mark.parametrize("units", ["metric", "us_customary", None])
    def test_the_unit_preference_changes_nothing(
        self, status: DeviceStatus, units: Any
    ) -> None:
        set_unit_system(units)
        assert sa.heater_state(status).upper_f == pytest.approx(
            58.6 * 9 / 5 + 32
        )
        assert sa.settings(status).setpoint_f == pytest.approx(140.9)

    def test_an_element_running(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        s = DeviceStatus.model_validate(
            device_status_dict | {"heatLowerUse": 2, "compUse": 1}
        )
        state = sa.heater_state(s)
        assert state.element_running and not state.compressor_running

    @pytest.mark.parametrize(("code", "gal"), [(1, 50), (2, 65), (3, 80)])
    def test_the_parameters_follow_the_tank_size(
        self, code: int, gal: int
    ) -> None:
        p = sa.params(
            DeviceFeature.model_validate(FEATURE | {"volumeCode": code})
        )
        assert p == default_params(code)
        assert p.tank.volume_gal == pytest.approx(63.2 * gal / 65)


class TestTheSchedules:
    def test_reservations_keep_the_devices_terms(self) -> None:
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

    def test_entries_in_any_stored_mode_are_read(self) -> None:
        sched = ReservationSchedule.model_validate(
            {
                "reservationUse": 2,
                "reservation": [
                    {
                        "enable": 2,
                        "week": 124,
                        "hour": 6,
                        "min": 0,
                        "mode": mode,
                        "param": 120,
                    }
                    for mode in (0, 5, 6)
                ],
            }
        )
        modes = [e.mode for e in sa.schedules(reservations=sched).reservations]
        assert modes == [0, 5, 6]

    def test_a_switched_off_reservation_schedule(self) -> None:
        sched = ReservationSchedule.model_validate(
            {"reservationUse": 1, "reservation": []}
        )
        assert sa.schedules(reservations=sched).reservations_enabled is False

    def test_tou_from_the_rest_read(self) -> None:
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

    def test_tou_from_the_mqtt_confirmation_carries_its_switch(self) -> None:
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


T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)


class TestThePreferredUnits:
    """What a caller supplies, and what it reads back, is in the
    library's preferred units; the scenario is the same either way."""

    def _metric(self) -> tuple[Any, ...]:
        set_unit_system("metric")
        return (
            sa.environment(
                ambient=((T0, 20.0), (T0 + timedelta(hours=6), 15.0)),
                humidity=40.0,
                inlet=10.0,
            ),
            sa.loads([(T0, 37.85411784)]),
            sa.write(T0, setpoint=60.0, mode=3, id="w"),
            sa.reservation_entry(
                days=["Monday"], hour=6, minute=0, mode=4, temperature=60.0
            ),
        )

    def _us(self) -> tuple[Any, ...]:
        set_unit_system("us_customary")
        return (
            sa.environment(
                ambient=((T0, 68.0), (T0 + timedelta(hours=6), 59.0)),
                humidity=40.0,
                inlet=50.0,
            ),
            sa.loads([(T0, 10.0)]),
            sa.write(T0, setpoint=140.0, mode=3, id="w"),
            sa.reservation_entry(
                days=["Monday"], hour=6, minute=0, mode=4, temperature=140.0
            ),
        )

    def test_metric_and_us_inputs_build_the_same_parts(self) -> None:
        metric, us = self._metric(), self._us()
        env_m, env_u = metric[0], us[0]
        assert [v for _, v in env_m.ambient_f] == pytest.approx(
            [v for _, v in env_u.ambient_f]
        )
        assert env_m.inlet_f == pytest.approx(env_u.inlet_f)
        assert env_m.humidity == env_u.humidity == 40.0
        assert metric[1].draws[0].gallons == pytest.approx(10.0)
        assert us[1].draws[0].gallons == 10.0
        assert metric[2].setpoint_f == pytest.approx(us[2].setpoint_f)
        assert metric[3] == us[3]
        assert metric[3].week == 64
        assert metric[3].setpoint_half_c == 120

    def test_with_no_preference_inputs_are_fahrenheit(self) -> None:
        set_unit_system(None)
        assert sa.write(T0, setpoint=140.0).setpoint_f == 140.0
        assert sa.temperature_unit() == "°F"
        assert sa.volume_unit() == "gal"

    def test_the_ambient_from_the_status_ignores_the_preference(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        s = DeviceStatus.model_validate(
            device_status_dict | {"ambientTemperature": 200}  # 20.0 degC
        )
        for units in ("metric", "us_customary", None):
            set_unit_system(units)
            assert sa.environment(s).ambient_f == pytest.approx(68.0)

    def test_an_ambient_or_a_status_is_needed(self) -> None:
        with pytest.raises(ValueError, match="ambient"):
            sa.environment()

    def test_left_out_is_the_simulators_default(self) -> None:
        env = sa.environment(ambient=20.0)
        assert "humidity" not in env.model_fields_set
        assert env.inlet_f is None

    @pytest.mark.parametrize(
        ("units", "temp", "vol", "symbols"),
        [
            ("metric", 60.0, 37.85411784, ("°C", "L")),
            ("us_customary", 140.0, 10.0, ("°F", "gal")),
        ],
    )
    def test_results_come_back_in_the_preferred_units(
        self, units: Any, temp: float, vol: float, symbols: tuple[str, str]
    ) -> None:
        set_unit_system(units)
        assert sa.temperature(140.0) == pytest.approx(temp)
        assert sa.volume(10.0) == pytest.approx(vol)
        assert (sa.temperature_unit(), sa.volume_unit()) == symbols

    def test_the_path_in_the_preferred_units(self) -> None:
        state = HeaterState(upper_f=131.0, lower_f=113.0)
        env = Environment(ambient_f=68.0)
        params = default_params()
        result = simulate(
            Scenario(
                start=T0,
                horizon=timedelta(hours=2),
                tz="UTC",
                state=state,
                settings=Settings(setpoint_f=140.0, hp_lower_on_f=105.0),
                environment=env,
            ),
            params,
        )
        trace = standby(
            state, env, Loads(), params, start=T0, until=T0 + timedelta(hours=2)
        )
        set_unit_system("metric")
        first = sa.path(result)[0]
        assert (first.upper, first.lower) == pytest.approx((55.0, 45.0))
        assert first.setpoint == pytest.approx(60.0)
        assert len(sa.path(result)) == len(result.points)
        assert sa.path(trace)[0].setpoint is None
        assert sa.path(trace)[0].upper == pytest.approx(55.0)


class TestSpansBetweenSamples:
    def test_a_span_between_two_samples_marks_the_first(self) -> None:
        import pandas as pd

        t0 = datetime(2026, 1, 5, tzinfo=UTC)
        index = pd.DatetimeIndex([t0, t0 + timedelta(seconds=120)])
        between = [(t0 + timedelta(seconds=10), t0 + timedelta(seconds=100))]
        assert sa._interval_column(index, between).tolist() == [True, False]
        assert sa._interval_column(index, []).tolist() == [False, False]
        last = [(t0 + timedelta(seconds=120), t0 + timedelta(seconds=130))]
        assert sa._interval_column(index, last).tolist() == [False, True]

    def test_every_overlap_is_marked(self) -> None:
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(7)
        t0 = datetime(2026, 1, 5, tzinfo=UTC)

        def at(n: Any) -> datetime:
            return t0 + timedelta(seconds=int(n))

        # Repeated instants and spans of no length or backwards too.
        times = sorted(at(n) for n in rng.integers(0, 60, 40))
        spans = [
            (at(a), at(b)) for a, b in rng.integers(-5, 65, (15, 2)).tolist()
        ]
        index = pd.DatetimeIndex(times)
        expected = [
            any(
                a <= t < b
                if i + 1 == len(times)
                else a < times[i + 1] and b > t
                for a, b in spans
            )
            for i, t in enumerate(times)
        ]
        assert sa._interval_column(index, spans).tolist() == expected
