"""The live sources against fake MQTT and REST clients, and compose."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from nwp500 import sim, sim_live
from nwp500.exceptions import APIError
from nwp500.models import (
    Device,
    DeviceFeature,
    DeviceInfo,
    DeviceStatus,
    Location,
    ReservationSchedule,
    TOUInfo,
    TOUPeriod,
)

FEATURE: dict[str, Any] = {
    "countryCode": 3,
    "modelTypeCode": 240,
    "controlTypeCode": 1,
    "volumeCode": 3,
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

RESERVATIONS: dict[str, Any] = {
    "reservationUse": 2,
    "reservation": [
        {
            "enable": 2,
            "week": 124,
            "hour": 6,
            "min": 30,
            "mode": 4,
            "param": 124,
        }
    ],
}

TOU: dict[str, Any] = {
    "touInfo": {
        "schedule": [
            {
                "season": 4095,
                "interval": [
                    {
                        "week": 124,
                        "startHour": 16,
                        "startMinute": 0,
                        "endHour": 20,
                        "endMinute": 59,
                        "priceMin": 50000,
                        "priceMax": 50000,
                        "decimalPoint": 5,
                    }
                ],
            }
        ]
    }
}

START = datetime(2026, 10, 18, 14, tzinfo=UTC)
FAST = 0.05

pytestmark = pytest.mark.asyncio


class FakeMqtt:
    """Replies to each request through the subscriptions, as the client
    does; a reply left None never arrives."""

    def __init__(
        self,
        status: DeviceStatus | None = None,
        feature: DeviceFeature | None = None,
        reservations: ReservationSchedule | None = None,
    ) -> None:
        self.replies: dict[str, Any] = {
            "status": status,
            "feature": feature,
            "reservations": reservations,
        }
        self.subscribed: dict[str, list[Any]] = {k: [] for k in self.replies}
        self.requests: list[str] = []

    def _reply(self, kind: str) -> int:
        self.requests.append(kind)
        reply = self.replies[kind]
        if reply is not None:
            loop = asyncio.get_running_loop()
            for callback in list(self.subscribed[kind]):
                loop.call_soon(callback, reply)
        return len(self.requests)

    async def subscribe_device_status(
        self,
        device: Any,
        cb: Any,
    ) -> int:
        self.subscribed["status"].append(cb)
        return 1

    async def unsubscribe_device_status(
        self,
        device: Any,
        cb: Any,
    ) -> None:
        self.subscribed["status"].remove(cb)

    async def request_device_status(
        self,
        device: Any,
    ) -> int:
        return self._reply("status")

    async def subscribe_device_feature(
        self,
        device: Any,
        cb: Any,
    ) -> int:
        self.subscribed["feature"].append(cb)
        return 1

    async def unsubscribe_device_feature(
        self,
        device: Any,
        cb: Any,
    ) -> None:
        self.subscribed["feature"].remove(cb)

    async def request_device_info(
        self,
        device: Any,
    ) -> int:
        return self._reply("feature")

    async def subscribe_reservation_response(
        self,
        device: Any,
        cb: Any,
    ) -> int:
        self.subscribed["reservations"].append(cb)
        return 1

    async def unsubscribe_reservation_response(
        self,
        device: Any,
        cb: Any,
    ) -> None:
        self.subscribed["reservations"].remove(cb)

    async def request_reservations(
        self,
        device: Any,
    ) -> int:
        return self._reply("reservations")


@pytest.fixture
def device() -> Device:
    return Device(
        device_info=DeviceInfo(mac_address="mac", additional_value="extra"),
        location=Location(),
    )


@pytest.fixture
def status(device_status_dict: dict[str, Any]) -> DeviceStatus:
    return DeviceStatus.model_validate(
        device_status_dict
        | {
            "tankUpperTemperature": 586,  # 58.6 degC
            "tankLowerTemperature": 431,  # 43.1 degC
            "dhwTemperatureSetting": 121,  # 60.5 degC
            "ambientTemperature": 200,  # 20.0 degC
        }
    )


@pytest.fixture
def feature() -> DeviceFeature:
    return DeviceFeature.model_validate(FEATURE)


@pytest.fixture
def reservations() -> ReservationSchedule:
    return ReservationSchedule.model_validate(RESERVATIONS)


def _api(tou: Any = None) -> Any:
    api = AsyncMock()
    if isinstance(tou, Exception):
        api.get_tou_info.side_effect = tou
    else:
        api.get_tou_info.return_value = TOUInfo.model_validate(tou or TOU)
    return api


def _tou_on(status: DeviceStatus) -> DeviceStatus:
    return status.model_copy(update={"tou_status": True})


class TestTheHeater:
    async def test_state_settings_air_and_tank_size(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
    ) -> None:
        mqtt = FakeMqtt(status=status, feature=feature)
        reading = await sim_live.LiveHeaterSource(mqtt, device).read()  # type: ignore[arg-type]  # fake mqtt client
        assert reading.state.upper_f == pytest.approx(137.48)
        assert reading.state.lower_f == pytest.approx(109.58)
        assert reading.settings.setpoint_f == pytest.approx(140.9)
        # Idle, the 68.0 °F reading is the cabinet's, less its warmth.
        assert reading.environment.ambient_f == pytest.approx(61.8)
        assert reading.params == sim.default_params(3)
        assert reading.status is status
        assert reading.feature is feature

    async def test_it_leaves_no_subscription_behind(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
    ) -> None:
        mqtt = FakeMqtt(status=status, feature=feature)
        await sim_live.LiveHeaterSource(mqtt, device).read()  # type: ignore[arg-type]  # fake mqtt client
        assert all(not subs for subs in mqtt.subscribed.values())

    async def test_no_status_is_an_error(
        self,
        device: Device,
        feature: DeviceFeature,
    ) -> None:
        mqtt = FakeMqtt(feature=feature)
        source = sim_live.LiveHeaterSource(mqtt, device, timeout=FAST)  # type: ignore[arg-type]  # fake mqtt client
        with pytest.raises(sim_live.LiveReadError, match="no device status"):
            await source.read()
        assert not mqtt.subscribed["status"]

    async def test_no_feature_leaves_the_tank_size_unknown(
        self,
        device: Device,
        status: DeviceStatus,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mqtt = FakeMqtt(status=status)
        source = sim_live.LiveHeaterSource(mqtt, device, timeout=FAST)  # type: ignore[arg-type]  # fake mqtt client
        reading = await source.read()
        assert reading.params is None
        assert reading.feature is None
        assert reading.state.upper_f == pytest.approx(137.48)
        assert "tank size is unknown" in caplog.text


class TestFromWhatWasRead:
    """``heater_reading`` and ``live_schedules``: the sources' answers
    from a status, a feature info, the reservations and the TOU periods
    read any way."""

    async def test_the_heater_reading_is_the_sources(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
    ) -> None:
        mqtt = FakeMqtt(status=status, feature=feature)
        read = await sim_live.LiveHeaterSource(mqtt, device).read()  # type: ignore[arg-type]  # fake mqtt client
        assert sim_live.heater_reading(status, feature) == read
        assert sim_live.heater_reading(status, None).params is None

    async def test_the_schedules_are_the_sources(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
        reservations: ReservationSchedule,
    ) -> None:
        on = _tou_on(status)
        mqtt = FakeMqtt(on, feature, reservations)
        read = await sim_live.LiveScheduleSource(mqtt, _api(), device).read()  # type: ignore[arg-type]  # fake mqtt client
        tou = TOUInfo.model_validate(TOU)
        assert sim_live.live_schedules(on, reservations, tou) == read
        # The periods alone, as a caller that keeps them flat holds them.
        periods = [
            TOUPeriod.model_validate({"season": day.season, **raw})
            for day in tou.schedule
            for raw in day.intervals
        ]
        assert sim_live.live_schedules(on, reservations, periods) == read

    async def test_tou_on_without_its_periods_is_an_error(
        self, status: DeviceStatus, reservations: ReservationSchedule
    ) -> None:
        with pytest.raises(sim_live.LiveReadError, match="TOU is on"):
            sim_live.live_schedules(_tou_on(status), reservations, None)
        off = sim_live.live_schedules(status, reservations, None)
        assert off.tou_enabled is False
        assert off.tou_periods == ()


class TestTheSchedules:
    async def test_reservations_tou_periods_and_switch(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
        reservations: ReservationSchedule,
    ) -> None:
        mqtt = FakeMqtt(_tou_on(status), feature, reservations)
        api = _api()
        schedules = await sim_live.LiveScheduleSource(mqtt, api, device).read()  # type: ignore[arg-type]  # fake mqtt client
        assert schedules.tou_enabled is True
        assert schedules.reservations_enabled is True
        (entry,) = schedules.reservations
        assert (entry.week, entry.hour, entry.minute) == (124, 6, 30)
        (period,) = schedules.tou_periods
        assert (period.season, period.start_hour, period.end_hour) == (
            4095,
            16,
            20,
        )
        api.get_tou_info.assert_awaited_once_with(
            mac_address="mac",
            additional_value="extra",
            controller_id="ABC123",
        )

    async def test_no_reservation_reply_is_an_error(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
    ) -> None:
        mqtt = FakeMqtt(status, feature)
        source = sim_live.LiveScheduleSource(mqtt, _api(), device, timeout=FAST)  # type: ignore[arg-type]  # fake mqtt client
        with pytest.raises(sim_live.LiveReadError, match="reservation"):
            await source.read()

    async def test_no_feature_with_tou_on_is_an_error(
        self,
        device: Device,
        status: DeviceStatus,
        reservations: ReservationSchedule,
    ) -> None:
        mqtt = FakeMqtt(_tou_on(status), None, reservations)
        api = _api()
        source = sim_live.LiveScheduleSource(mqtt, api, device, timeout=FAST)  # type: ignore[arg-type]  # fake mqtt client
        with pytest.raises(sim_live.LiveReadError, match="TOU is on"):
            await source.read()
        api.get_tou_info.assert_not_awaited()

    async def test_no_feature_with_tou_off_reads_no_periods(
        self,
        device: Device,
        status: DeviceStatus,
        reservations: ReservationSchedule,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mqtt = FakeMqtt(status, None, reservations)
        source = sim_live.LiveScheduleSource(mqtt, _api(), device, timeout=FAST)  # type: ignore[arg-type]  # fake mqtt client
        schedules = await source.read()
        assert schedules.tou_enabled is False
        assert schedules.tou_periods == ()
        assert len(schedules.reservations) == 1
        assert "TOU periods not read" in caplog.text

    async def test_a_failed_tou_read_with_tou_on_is_an_error(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
        reservations: ReservationSchedule,
    ) -> None:
        mqtt = FakeMqtt(_tou_on(status), feature, reservations)
        source = sim_live.LiveScheduleSource(
            mqtt,  # type: ignore[arg-type]  # fake mqtt client
            _api(APIError("no TOU")),
            device,
        )
        with pytest.raises(sim_live.LiveReadError, match="no TOU"):
            await source.read()

    @pytest.mark.parametrize(
        "error",
        [APIError("no TOU"), TimeoutError(), ValueError("not a TOU document")],
        ids=["rest", "timeout", "bad reply"],
    )
    async def test_a_failed_tou_read_with_tou_off_reads_no_periods(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
        reservations: ReservationSchedule,
        error: Exception,
    ) -> None:
        mqtt = FakeMqtt(status, feature, reservations)
        source = sim_live.LiveScheduleSource(mqtt, _api(error), device)  # type: ignore[arg-type]  # fake mqtt client
        assert (await source.read()).tou_periods == ()

    @pytest.mark.parametrize(
        "error",
        [TimeoutError(), ValueError("not a TOU document")],
        ids=["timeout", "bad reply"],
    )
    async def test_a_timed_out_or_bad_tou_reply_with_tou_on_is_an_error(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
        reservations: ReservationSchedule,
        error: Exception,
    ) -> None:
        mqtt = FakeMqtt(_tou_on(status), feature, reservations)
        source = sim_live.LiveScheduleSource(mqtt, _api(error), device)  # type: ignore[arg-type]  # fake mqtt client
        with pytest.raises(sim_live.LiveReadError, match="TOU read failed"):
            await source.read()


class TestCompose:
    async def _compose(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
        **kw: Any,
    ) -> sim_live.Composed:
        mqtt = FakeMqtt(status, feature, None)
        return await sim_live.compose(
            start=START,
            horizon=timedelta(hours=6),
            tz="America/Los_Angeles",
            heater=sim_live.LiveHeaterSource(mqtt, device),  # type: ignore[arg-type]  # fake mqtt client
            **kw,
        )

    async def test_the_heater_alone(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
    ) -> None:
        composed = await self._compose(device, status, feature)
        s = composed.scenario
        assert (s.start, s.horizon, s.tz) == (
            START,
            timedelta(hours=6),
            "America/Los_Angeles",
        )
        assert s.state == composed.heater.state
        assert s.environment == composed.heater.environment
        assert s.schedules == sim.Schedules()
        assert s.loads == sim.Loads()
        assert s.commands == sim.Commands()
        assert composed.params == sim.default_params(3)

    async def test_history_is_left_unknown(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
    ) -> None:
        composed = await self._compose(device, status, feature)
        assert "history" not in composed.scenario.model_fields_set
        result = sim.simulate(composed.scenario, composed.params)  # type: ignore[arg-type]  # feature sets params
        assert any(
            d.startswith("compressor_stopped_at=") for d in result.defaults_used
        )

    async def test_given_sources_take_their_parts(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
    ) -> None:
        env = sim.Environment(ambient_f=55.0, inlet_f=50.0)
        loads = sim.Loads(draws=(sim.Draw(at=START, gallons=10.0),))
        commands = sim.Commands(tou_enabled=True)
        composed = await self._compose(
            device,
            status,
            feature,
            schedules=sim_live.Given(sim.Schedules(tou_enabled=True)),
            environment=sim_live.Given(env),
            loads=sim_live.Given(loads),
            commands=commands,
        )
        s = composed.scenario
        assert s.environment == env
        assert s.loads == loads
        assert s.commands == commands
        assert s.schedules.tou_enabled is True

    async def test_an_override_is_a_model_copy(
        self,
        device: Device,
        status: DeviceStatus,
        feature: DeviceFeature,
    ) -> None:
        composed = await self._compose(device, status, feature)
        hotter = composed.scenario.model_copy(
            update={"settings": sim.Settings(setpoint_f=120.0)}
        )
        assert hotter.settings.setpoint_f == 120.0
        assert hotter.state == composed.scenario.state


class TestTheCabinetAir:
    """The heater's idle reading is its cabinet's: an answer run at it
    says so, and one run at air given in its place doesn't."""

    async def test_an_idle_status_is_flagged(self, status: Any) -> None:
        from nwp500 import sim_adapters as sa

        idle = status.model_copy(update={"comp_use": False})
        running = status.model_copy(update={"comp_use": True})
        assert sa.environment(idle).ambient_cabinet
        assert not sa.environment(running).ambient_cabinet
        assert not sa.environment(idle, ambient=60.0).ambient_cabinet

    async def test_an_idle_reading_loses_the_cabinets_warmth(
        self, status: Any
    ) -> None:
        """Idle, the reading is the cabinet's, a mean 6.2 °F above the
        air beside the heater (2026-02-14 to 10-24)."""
        from nwp500 import sim_adapters as sa

        idle = status.model_copy(update={"comp_use": False})
        running = status.model_copy(update={"comp_use": True})
        unknown = status.model_copy(update={"comp_use": None})
        air = cast(float, sa.environment(running).ambient_f)
        assert sa.environment(idle).ambient_f == pytest.approx(
            air - sa.IDLE_CABINET_WARM_F
        )
        assert sa.environment(unknown).ambient_f == pytest.approx(air)
        assert not sa.environment(unknown).ambient_cabinet

    async def test_the_reason_is_given(self, status: Any) -> None:
        from nwp500.sim.api import AMBIENT_FROM_CABINET, _ambient_reasons
        from nwp500.sim.inputs import Environment

        assert _ambient_reasons(
            Environment(ambient_f=70.0, ambient_cabinet=True)
        ) == [AMBIENT_FROM_CABINET]
        assert _ambient_reasons(Environment(ambient_f=70.0)) == []
