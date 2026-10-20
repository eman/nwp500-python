"""The air where the heater stands, from an outdoor forecast
(``nwp500.sim.location_air``), and its adapters.

The projection is held to its source by the parity check run with the
port; these hold its anchoring, the fit and the units.
"""

import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("numpy")

from nwp500 import sim_adapters as sa
from nwp500.models import DeviceStatus
from nwp500.sim.location_air import (
    SITE_LOCATION_AIR,
    LocationAirModel,
    fit,
    project,
)
from nwp500.unit_system import reset_unit_system, set_unit_system

T0 = datetime(2026, 10, 4, 0, 0, tzinfo=UTC)


def _outdoor(hours: int = 48) -> list[tuple[datetime, float]]:
    """A day's swing, 50-70 °F, peaking mid-afternoon UTC."""
    return [
        (
            T0 + timedelta(hours=h),
            60.0 + 10.0 * math.sin(2 * math.pi * (h - 9) / 24),
        )
        for h in range(hours)
    ]


@pytest.fixture(autouse=True)
def _units() -> Iterator[None]:
    yield
    reset_unit_system()


class TestTheProjection:
    def test_it_is_the_damped_lagged_outdoor_air(self) -> None:
        model = LocationAirModel(0.5, timedelta(hours=2), 30.0)
        out = dict(_outdoor())
        air = project(
            model, _outdoor(), T0 + timedelta(hours=4), T0 + timedelta(hours=6)
        )
        assert air[0][1] == pytest.approx(
            0.5 * out[T0 + timedelta(hours=2)] + 30.0
        )
        assert len(air) == 13

    def test_no_forecast_is_no_projection(self) -> None:
        assert project(SITE_LOCATION_AIR, [], T0, T0 + timedelta(hours=1)) == ()

    def test_it_holds_past_the_forecasts_ends(self) -> None:
        model = LocationAirModel(1.0, timedelta(0), 0.0)
        out = _outdoor(6)
        late = project(
            model, out, T0 + timedelta(hours=10), T0 + timedelta(hours=11)
        )
        assert {v for _, v in late} == {out[-1][1]}

    def test_an_anchor_moves_it_through_the_reading_at_its_own_instant(
        self,
    ) -> None:
        reading = (T0 + timedelta(hours=7), 66.0)
        air = project(
            SITE_LOCATION_AIR,
            _outdoor(),
            T0 + timedelta(hours=8),
            T0 + timedelta(hours=20),
            anchor=reading,
        )
        unanchored = project(
            SITE_LOCATION_AIR, _outdoor(), reading[0], reading[0]
        )[0][1]
        shift = reading[1] - unanchored
        plain = project(
            SITE_LOCATION_AIR,
            _outdoor(),
            T0 + timedelta(hours=8),
            T0 + timedelta(hours=20),
        )
        assert [v for _, v in air] == pytest.approx(
            [v + shift for _, v in plain]
        )


class TestTheFit:
    def test_it_recovers_a_known_model(self) -> None:
        truth = LocationAirModel(0.6, timedelta(hours=2), 25.0)
        when = [T0 + timedelta(hours=6, minutes=10 * k) for k in range(150)]
        readings = list(zip(when, truth.at(_outdoor(), when), strict=True))
        got = fit(readings, _outdoor())
        assert got.model.lag == timedelta(hours=2)
        assert got.model.damping == pytest.approx(0.6)
        assert got.model.offset_f == pytest.approx(25.0)
        assert got.r == pytest.approx(1.0)

    def test_it_needs_readings(self) -> None:
        with pytest.raises(ValueError, match="three"):
            fit([], _outdoor())


class TestTheAdapters:
    def _status(
        self, device_status_dict: dict[str, Any], **kw: Any
    ) -> DeviceStatus:
        return DeviceStatus.model_validate(
            device_status_dict | {"ambientTemperature": 200} | kw
        )

    def test_the_heaters_reading_only_while_the_compressor_runs(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        running = self._status(device_status_dict, compUse=2)
        idle = self._status(device_status_dict, compUse=1)
        assert sa.location_air_reading(running) == pytest.approx(68.0)
        assert sa.location_air_reading(idle) is None

    def test_the_projection_in_the_preferred_unit(self) -> None:
        set_unit_system("metric")
        outdoor_c = [(t, (v - 32) * 5 / 9) for t, v in _outdoor()]
        air = sa.location_air(
            outdoor_c,
            start=T0 + timedelta(hours=8),
            until=T0 + timedelta(hours=9),
            anchor=(T0 + timedelta(hours=7), 20.0),
        )
        set_unit_system("us_customary")
        air_f = sa.location_air(
            _outdoor(),
            start=T0 + timedelta(hours=8),
            until=T0 + timedelta(hours=9),
            anchor=(T0 + timedelta(hours=7), 68.0),
        )
        assert [(v * 9 / 5 + 32) for _, v in air] == pytest.approx(
            [v for _, v in air_f]
        )
        env = sa.environment(ambient=air_f)
        assert env.ambient_f[0][1] == pytest.approx(air_f[0][1])  # type: ignore[index]


LA = __import__("zoneinfo").ZoneInfo("America/Los_Angeles")


class TestElapsedTime:
    """The second review of #162: the grid and the lag in elapsed time,
    so local and UTC instants are the same projection."""

    @pytest.mark.parametrize("step", [timedelta(0), timedelta(minutes=-10)])
    def test_a_step_must_be_positive(self, step: timedelta) -> None:
        with pytest.raises(ValueError, match="positive"):
            project(
                SITE_LOCATION_AIR,
                _outdoor(),
                T0,
                T0 + timedelta(hours=1),
                step=step,
            )

    @pytest.mark.parametrize(
        ("start", "end"),
        [
            # Fall back: the 01:00 hour happens twice.
            (
                datetime(2026, 11, 1, 0, 0, tzinfo=LA),
                datetime(2026, 11, 1, 3, 0, tzinfo=LA),
            ),
            # Spring forward: 02:00-03:00 never happens.
            (
                datetime(2026, 3, 8, 0, 0, tzinfo=LA),
                datetime(2026, 3, 8, 4, 0, tzinfo=LA),
            ),
        ],
    )
    def test_a_local_span_is_its_utc_span(
        self, start: datetime, end: datetime
    ) -> None:
        outdoor = [
            (start.astimezone(UTC) + timedelta(hours=h), 50.0 + h)
            for h in range(-4, 8)
        ]
        local = project(SITE_LOCATION_AIR, outdoor, start, end)
        utc = project(
            SITE_LOCATION_AIR,
            outdoor,
            start.astimezone(UTC),
            end.astimezone(UTC),
        )
        assert local == utc
        span = (end.astimezone(UTC) - start.astimezone(UTC)) / timedelta(
            minutes=10
        )
        assert len(local) == int(span) + 1

    def test_a_repeated_hours_readings_sort_by_instant(self) -> None:
        """The third review of #162: 01:45 PDT comes before 01:15 PST
        but sorts after it by wall clock; local readings must be the
        same series as their UTC instants."""
        first = datetime(2026, 11, 1, 1, 45, tzinfo=LA)
        second = datetime(2026, 11, 1, 1, 15, fold=1, tzinfo=LA)
        assert first.astimezone(UTC) < second.astimezone(UTC)
        local = [(first, 50.0), (second, 60.0)]
        utc = [(t.astimezone(UTC), v) for t, v in local]
        model = LocationAirModel(1.0, timedelta(0), 0.0)
        when = [first.astimezone(UTC) + timedelta(minutes=15)]
        assert model.at(local, when) == model.at(utc, when)
        assert model.at(local, when)[0] == pytest.approx(55.0)

    def test_the_lag_is_elapsed_time(self) -> None:
        when = datetime(2026, 11, 1, 2, 0, tzinfo=LA)
        outdoor = [
            (when.astimezone(UTC) + timedelta(hours=h), 50.0 + h)
            for h in range(-4, 4)
        ]
        assert SITE_LOCATION_AIR.at(outdoor, [when]) == SITE_LOCATION_AIR.at(
            outdoor, [when.astimezone(UTC)]
        )
