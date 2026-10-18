"""The live sources against fake MQTT and REST clients, and compose."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("pandas")

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

    async def subscribe_device_status(self, device: Any, cb: Any) -> int:
        self.subscribed["status"].append(cb)
        return 1

    async def unsubscribe_device_status(self, device: Any, cb: Any) -> None:
        self.subscribed["status"].remove(cb)

    async def request_device_status(self, device: Any) -> int:
        return self._reply("status")

    async def subscribe_device_feature(self, device: Any, cb: Any) -> int:
        self.subscribed["feature"].append(cb)
        return 1

    async def unsubscribe_device_feature(self, device: Any, cb: Any) -> None:
        self.subscribed["feature"].remove(cb)

    async def request_device_info(self, device: Any) -> int:
        return self._reply("feature")

    async def subscribe_reservation_response(self, device: Any, cb: Any) -> int:
        self.subscribed["reservations"].append(cb)
        return 1

    async def unsubscribe_reservation_response(
        self, device: Any, cb: Any
    ) -> None:
        self.subscribed["reservations"].remove(cb)

    async def request_reservations(self, device: Any) -> int:
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
        self, device, status, feature
    ):
        mqtt = FakeMqtt(status=status, feature=feature)
        reading = await sim_live.LiveHeaterSource(mqtt, device).read()
        assert reading.state.upper_f == pytest.approx(137.48)
        assert reading.state.lower_f == pytest.approx(109.58)
        assert reading.settings.setpoint_f == pytest.approx(140.9)
        assert reading.environment.ambient_f == pytest.approx(68.0)
        assert reading.params == sim.default_params(3)
        assert reading.status is status
        assert reading.feature is feature

    async def test_it_leaves_no_subscription_behind(
        self, device, status, feature
    ):
        mqtt = FakeMqtt(status=status, feature=feature)
        await sim_live.LiveHeaterSource(mqtt, device).read()
        assert all(not subs for subs in mqtt.subscribed.values())

    async def test_no_status_is_an_error(self, device, feature):
        mqtt = FakeMqtt(feature=feature)
        source = sim_live.LiveHeaterSource(mqtt, device, timeout=FAST)
        with pytest.raises(sim_live.LiveReadError, match="no device status"):
            await source.read()
        assert not mqtt.subscribed["status"]

    async def test_no_feature_leaves_the_tank_size_unknown(
        self, device, status, caplog
    ):
        mqtt = FakeMqtt(status=status)
        source = sim_live.LiveHeaterSource(mqtt, device, timeout=FAST)
        reading = await source.read()
        assert reading.params is None
        assert reading.feature is None
        assert reading.state.upper_f == pytest.approx(137.48)
        assert "tank size is unknown" in caplog.text


class TestTheSchedules:
    async def test_reservations_tou_periods_and_switch(
        self, device, status, feature, reservations
    ):
        mqtt = FakeMqtt(_tou_on(status), feature, reservations)
        api = _api()
        schedules = await sim_live.LiveScheduleSource(mqtt, api, device).read()
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
        self, device, status, feature
    ):
        mqtt = FakeMqtt(status, feature)
        source = sim_live.LiveScheduleSource(mqtt, _api(), device, timeout=FAST)
        with pytest.raises(sim_live.LiveReadError, match="reservation"):
            await source.read()

    async def test_no_feature_with_tou_on_is_an_error(
        self, device, status, reservations
    ):
        mqtt = FakeMqtt(_tou_on(status), None, reservations)
        api = _api()
        source = sim_live.LiveScheduleSource(mqtt, api, device, timeout=FAST)
        with pytest.raises(sim_live.LiveReadError, match="TOU is on"):
            await source.read()
        api.get_tou_info.assert_not_awaited()

    async def test_no_feature_with_tou_off_reads_no_periods(
        self, device, status, reservations, caplog
    ):
        mqtt = FakeMqtt(status, None, reservations)
        source = sim_live.LiveScheduleSource(mqtt, _api(), device, timeout=FAST)
        schedules = await source.read()
        assert schedules.tou_enabled is False
        assert schedules.tou_periods == ()
        assert len(schedules.reservations) == 1
        assert "TOU periods not read" in caplog.text

    async def test_a_failed_tou_read_with_tou_on_is_an_error(
        self, device, status, feature, reservations
    ):
        mqtt = FakeMqtt(_tou_on(status), feature, reservations)
        source = sim_live.LiveScheduleSource(
            mqtt, _api(APIError("no TOU")), device
        )
        with pytest.raises(sim_live.LiveReadError, match="no TOU"):
            await source.read()

    @pytest.mark.parametrize(
        "error",
        [APIError("no TOU"), TimeoutError(), ValueError("not a TOU document")],
        ids=["rest", "timeout", "bad reply"],
    )
    async def test_a_failed_tou_read_with_tou_off_reads_no_periods(
        self, device, status, feature, reservations, error
    ):
        mqtt = FakeMqtt(status, feature, reservations)
        source = sim_live.LiveScheduleSource(mqtt, _api(error), device)
        assert (await source.read()).tou_periods == ()

    @pytest.mark.parametrize(
        "error",
        [TimeoutError(), ValueError("not a TOU document")],
        ids=["timeout", "bad reply"],
    )
    async def test_a_timed_out_or_bad_tou_reply_with_tou_on_is_an_error(
        self, device, status, feature, reservations, error
    ):
        mqtt = FakeMqtt(_tou_on(status), feature, reservations)
        source = sim_live.LiveScheduleSource(mqtt, _api(error), device)
        with pytest.raises(sim_live.LiveReadError, match="TOU read failed"):
            await source.read()


class TestCompose:
    async def _compose(self, device, status, feature, **kw: Any):
        mqtt = FakeMqtt(status, feature, None)
        return await sim_live.compose(
            start=START,
            horizon=timedelta(hours=6),
            tz="America/Los_Angeles",
            heater=sim_live.LiveHeaterSource(mqtt, device),
            **kw,
        )

    async def test_the_heater_alone(self, device, status, feature):
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

    async def test_history_is_left_unknown(self, device, status, feature):
        composed = await self._compose(device, status, feature)
        assert "history" not in composed.scenario.model_fields_set
        result = sim.simulate(composed.scenario, composed.params)
        assert any(
            d.startswith("compressor_stopped_at=") for d in result.defaults_used
        )

    async def test_given_sources_take_their_parts(
        self, device, status, feature
    ):
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

    async def test_an_override_is_a_model_copy(self, device, status, feature):
        composed = await self._compose(device, status, feature)
        hotter = composed.scenario.model_copy(
            update={"settings": sim.Settings(setpoint_f=120.0)}
        )
        assert hotter.settings.setpoint_f == 120.0
        assert hotter.state == composed.scenario.state
