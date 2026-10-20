"""A past scenario from the statuses the heater reported
(``sim_adapters.replay``), and the TOU switch's recorded changes.

The derivations are held to their source by the parity check run with
the port; these hold their rules.
"""

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("pandas")

from nwp500 import sim_adapters as sa
from nwp500.models import DeviceStatus
from nwp500.sim import Schedules, TouPeriod, default_params, simulate
from nwp500.sim.codec import scenario_from_document, scenario_to_document

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
ON, OFF = 2, 1


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
def record(device_status_dict: dict[str, Any]) -> Any:
    """A status every 5 minutes for 6 hours; ``set(m, **fields)``
    changes the statuses from minute ``m`` on."""

    class Record:
        def __init__(self) -> None:
            self.fields: list[dict[str, Any]] = [
                {
                    "compUse": OFF,
                    "heatUpperUse": OFF,
                    "heatLowerUse": OFF,
                    # Heat Pump, and the upper threshold at rest.
                    "dhwOperationSetting": 1,
                    "hpUpperOnTempSetting": 81,
                }
                for _ in range(73)
            ]

        def set(self, minute: int, **kw: Any) -> None:
            for d in self.fields[minute // 5 :]:
                d.update(kw)

        def readings(self) -> list[tuple[datetime, DeviceStatus]]:
            return [
                (at(5 * i), DeviceStatus.model_validate(device_status_dict | d))
                for i, d in enumerate(self.fields)
            ]

    return Record()


def _replay(
    record: Any, minute: float, until: float = 300, **kw: Any
) -> sa.Replay:
    return sa.replay(
        record.readings(),
        at=at(minute),
        until=at(until),
        tz="UTC",
        environment=sa.environment(ambient=65.0),
        **kw,
    )


class TestTheStateThen:
    def test_the_last_status_at_or_before(self, record: Any) -> None:
        record.set(100, tankUpperTemperature=500)
        s = _replay(record, 102).scenario
        assert s.start == at(102)
        assert s.state.upper_f == pytest.approx(122.0)

    def test_a_stale_tank_is_refused(self, record: Any) -> None:
        with pytest.raises(ValueError, match="no status"):
            sa.replay(
                record.readings()[:2],
                at=at(200),
                until=at(300),
                tz="UTC",
            )

    def test_the_compressors_stop_and_the_last_heating(
        self, record: Any
    ) -> None:
        record.set(60, compUse=ON)
        record.set(120, compUse=OFF)
        s = _replay(record, 150).scenario
        assert not s.state.compressor_running
        assert s.history.compressor_stopped_at == at(120)
        assert s.history.heated_at == at(120)

    def test_an_element_run_after_it_is_the_last_heating(
        self, record: Any
    ) -> None:
        record.set(60, compUse=ON)
        record.set(120, compUse=OFF)
        record.set(130, heatUpperUse=ON)
        record.set(140, heatUpperUse=OFF)
        assert _replay(record, 150).scenario.history.heated_at == at(140)

    def test_running_heats_now_and_says_since_when(self, record: Any) -> None:
        record.set(60, compUse=ON, heatUpperUse=ON)
        s = _replay(record, 92).scenario
        assert s.state.compressor_running
        assert s.history.heated_at == at(92)
        assert s.history.compressor_stopped_at is None
        assert s.state.element_running_since == at(60)

    def test_a_day_without_a_stop_has_none(self, record: Any) -> None:
        assert (
            _replay(record, 150).scenario.history.compressor_stopped_at is None
        )


class TestOverTheSpan:
    def test_setpoint_and_mode_changes_are_writes(self, record: Any) -> None:
        record.set(200, dhwTemperatureSetting=116)
        record.set(230, dhwOperationSetting=3)
        writes = _replay(record, 150).scenario.commands.writes
        assert [(w.at, w.setpoint_f, w.mode) for w in writes] == [
            (at(200), pytest.approx(136.4), None),
            (at(230), None, 3),
        ]

    def test_none_when_asked_not_to(self, record: Any) -> None:
        record.set(200, dhwTemperatureSetting=116)
        assert _replay(record, 150, writes=False).scenario.commands.writes == ()

    def test_the_heaters_own_drop_at_a_window_is_no_write(
        self, record: Any
    ) -> None:
        record.set(160, dhwOperationSetting=3)
        record.set(200, dhwOperationSetting=1, hpUpperOnTempSetting=120)
        modes = [w.mode for w in _replay(record, 150).scenario.commands.writes]
        assert modes == [3]

    def test_vacation_is_not_modelled(self, record: Any) -> None:
        record.set(200, dhwOperationSetting=5)
        r = _replay(record, 150)
        assert r.scenario.commands.writes == ()
        assert r.reasons == ("recorded_write_not_modelled",)

    def test_the_tou_switchs_changes(self, record: Any) -> None:
        record.set(0, touStatus=1)
        record.set(200, touStatus=0)
        record.set(250, touStatus=1)
        s = _replay(record, 150).scenario
        assert s.schedules.tou_enabled
        assert s.schedules.tou_switches == ((at(200), False), (at(250), True))
        doc = scenario_to_document(s)
        assert scenario_from_document(doc)[0] == s


class TestTheSwitchInTheWalk:
    def test_switched_off_a_window_no_longer_caps(self) -> None:
        """A recovery running inside a window 18:00-23:00 UTC is capped;
        with TOU switched off a minute in, it is not."""
        from nwp500.sim import Environment, HeaterState, Scenario, Settings

        def period(h0: int, h1: int, price: int) -> TouPeriod:
            return TouPeriod(
                season=4095,
                week=254,
                start_hour=h0,
                start_minute=0,
                end_hour=h1,
                end_minute=59,
                price_max=price,
            )

        # The window is the dearer period (off-peak either side).
        base = Schedules(
            tou_periods=(
                period(0, 17, 1),
                period(18, 22, 5),
                period(23, 23, 1),
            ),
            tou_enabled=True,
        )
        start = T0 + timedelta(hours=7)
        s = Scenario(
            start=start,
            horizon=timedelta(hours=6),
            tz="UTC",
            state=HeaterState(
                upper_f=128.0, lower_f=100.0, compressor_running=True
            ),
            settings=Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
            environment=Environment(ambient_f=65.0),
            schedules=base,
        )
        off = s.model_copy(
            update={
                "schedules": base.model_copy(
                    update={
                        "tou_switches": ((start + timedelta(minutes=1), False),)
                    }
                )
            }
        )
        p = default_params()
        assert simulate(s, p).heating[0].capped
        assert not simulate(off, p).heating[0].capped


class TestTheAir:
    def _replay(self, record: Any, **kw: Any) -> sa.Replay:
        return sa.replay(
            record.readings(), at=at(30), until=at(300), tz="UTC", **kw
        )

    def test_the_recorded_air_as_ten_minute_means(self, record: Any) -> None:
        air = [(at(m), 60.0 + (m % 20) / 10) for m in range(-400, 400, 2)]
        env = self._replay(record, air=air, humidity=45.0).scenario.environment
        assert isinstance(env.ambient_f, tuple)
        stamps = [t for t, _ in env.ambient_f]
        assert stamps[0] >= at(30) - sa.CLIMATE_LOOKBACK - timedelta(minutes=10)
        steps = {b - a for a, b in itertools.pairwise(stamps)}
        assert steps == {timedelta(minutes=10)}
        assert env.humidity == 45.0

    def test_without_it_the_heaters_own_reading(self, record: Any) -> None:
        env = self._replay(record).scenario.environment
        assert isinstance(env.ambient_f, float)
