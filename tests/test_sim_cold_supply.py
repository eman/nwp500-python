"""The mains from an inlet probe's long-draw plateaus, and from the
climate where there is none (``sim.cold_supply``).

Held to its source by the parity check run with the port; these hold
its rules.
"""

import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from nwp500 import sim_adapters as sa
from nwp500.sim import Environment, Scenario, simulate
from nwp500.sim.cold_supply import (
    MAINS_OFFSET_F,
    ColdSupplyParams,
    climate_of,
    mains_f,
    plateau_t_cold,
)
from nwp500.sim.defaults import site_example_params
from nwp500.sim.params import (
    DrawParams,
    params_from_document,
    params_to_document,
)

T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


Span = tuple[datetime, datetime]


def a_draw(
    minutes: int, at: datetime = T0, mains: float = 72.0
) -> tuple[list[tuple[datetime, float]], list[Span]]:
    """A draw of ``minutes``, the probe read every 10 s and settling
    from 77 degF to the mains after 5 minutes."""
    ticks = [at + timedelta(seconds=s) for s in range(0, 60 * minutes, 10)]
    probe = [
        (t, 77.0 if (t - at).total_seconds() < 300 else mains) for t in ticks
    ]
    return probe, [(at, at + timedelta(minutes=minutes))]


class TestThePlateau:
    def test_a_long_draw_reads_the_mains(self) -> None:
        probe, draws = a_draw(15)
        got = plateau_t_cold(probe, draws, [], T0 + timedelta(hours=1))
        assert (got.t_cold_f, got.draws) == (72.0, 1)

    def test_a_short_draw_or_one_with_circulation_has_none(self) -> None:
        probe, draws = a_draw(9)
        at = T0 + timedelta(hours=1)
        assert plateau_t_cold(probe, draws, [], at).t_cold_f is None
        probe, draws = a_draw(15)
        run = [(T0 + timedelta(minutes=3), T0 + timedelta(minutes=6))]
        assert plateau_t_cold(probe, draws, run, at).t_cold_f is None

    def test_unrecorded_is_not_idle(self) -> None:
        probe, draws = a_draw(15)
        at = T0 + timedelta(hours=1)
        assert plateau_t_cold(probe, draws, None, at).t_cold_f is None
        assert plateau_t_cold(probe, [], [], at).t_cold_f is None

    def test_old_or_implausible_draws_do_not_count(self) -> None:
        probe, draws = a_draw(15)
        late = T0 + timedelta(hours=80)
        assert plateau_t_cold(probe, draws, [], late).t_cold_f is None
        probe, draws = a_draw(15, mains=95.0)
        at = T0 + timedelta(hours=1)
        assert plateau_t_cold(probe, draws, [], at).t_cold_f is None

    def test_a_draw_still_running_ends_at_the_instant(self) -> None:
        """Nothing after ``at`` is read: a draw running at ``at`` is
        read to ``at``, and has a plateau once it has run long enough."""
        probe, draws = a_draw(15)
        assert (
            plateau_t_cold(probe, draws, [], T0 + timedelta(minutes=12))
        ).t_cold_f == 72.0
        assert (
            plateau_t_cold(probe, draws, [], T0 + timedelta(minutes=10))
        ).t_cold_f is None

    def test_the_adapter_reads_the_preferred_units(self) -> None:
        probe, draws = a_draw(15)
        got = sa.cold_supply(probe, at=T0 + timedelta(hours=1), draws=draws)
        assert got.t_cold_f == 72.0


class TestWhatTheReadingsAre:
    def test_a_missing_reading_is_left_out(self) -> None:
        probe, draws = a_draw(15)
        tail = T0 + timedelta(minutes=14)
        probe = [*probe, (tail + timedelta(seconds=5), float("nan"))]
        at = T0 + timedelta(hours=1)
        assert plateau_t_cold(probe, draws, [], at).t_cold_f == 72.0
        assert sa.cold_supply(probe, at=at, draws=draws).t_cold_f == 72.0

    def test_runs_closer_than_the_gap_are_one(self) -> None:
        """Runs closer than the gap are one run: a draw between them is a
        draw with circulation on."""
        probe, draws = a_draw(15)
        runs = [
            (T0 - timedelta(minutes=3), T0 - timedelta(minutes=1)),
            (T0 + timedelta(minutes=16), T0 + timedelta(minutes=17)),
        ]
        at = T0 + timedelta(hours=1)
        apart = plateau_t_cold(probe, draws, runs, at)
        assert apart.t_cold_f == 72.0
        wide = ColdSupplyParams(run_gap_s=1200.0)
        joined = plateau_t_cold(probe, draws, runs, at, wide)
        assert joined.t_cold_f is None

    def test_unrecorded_circulation_gives_no_estimate(self) -> None:
        probe, draws = a_draw(15)
        at = T0 + timedelta(hours=1)
        assert (
            sa.cold_supply(probe, at=at, draws=draws, circulation=None).t_cold_f
            is None
        )


def _year(mean_f: float, swing_f: float) -> list[date]:
    days = [date(2026, 1, 1) + timedelta(days=k) for k in range(365)]
    return sorted(days, key=lambda d: mains_f(mean_f, swing_f, d))


class TestTheMainsByTheDay:
    def test_the_water_swings_damped_about_the_air(self) -> None:
        """A 50 degF year swinging 40 degF: the mains run 6 degF over the
        mean air, swinging 0.46 of the air's half-swing either way."""
        coldest, *_, warmest = _year(50.0, 40.0)
        assert mains_f(50.0, 40.0, warmest) == pytest.approx(65.2, abs=0.01)
        assert mains_f(50.0, 40.0, coldest) == pytest.approx(46.8, abs=0.01)
        year = [mains_f(50.0, 40.0, d) for d in _year(50.0, 40.0)]
        assert sum(year) / len(year) == pytest.approx(
            50.0 + MAINS_OFFSET_F, abs=0.05
        )

    def test_a_colder_climate_lags_its_air_more(self) -> None:
        """The warmest water comes 29 days after mid-July's air at 50 degF
        mean, and 9 days after at 70."""
        assert _year(50.0, 40.0)[-1] == date(2026, 8, 15)
        assert _year(70.0, 40.0)[-1] == date(2026, 7, 26)

    def test_with_no_swing_the_mains_hold(self) -> None:
        days = (date(2026, 2, 1), date(2026, 8, 1))
        assert {mains_f(60.0, 0.0, d) for d in days} == {66.0}


def _daily(
    means: list[float], first: date, days: int = 28
) -> list[tuple[datetime, float]]:
    """A reading a day, ``days`` days of each month from ``first``'s,
    each month at its own of ``means``."""
    out: list[tuple[datetime, float]] = []
    y, m = first.year, first.month
    for v in means:
        out += [(datetime(y, m, d + 1, 12, tzinfo=UTC), v) for d in range(days)]
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class TestTheClimateOfAYear:
    def test_the_mean_and_swing_of_the_monthly_means(self) -> None:
        means = [
            50.0,
            52.0,
            56.0,
            60.0,
            64.0,
            68.0,
            70.0,
            69.0,
            65.0,
            60.0,
            55.0,
            51.0,
        ]
        mean, swing = climate_of(_daily(means, date(2025, 1, 1)))
        assert mean == pytest.approx(sum(means) / 12)
        assert swing == pytest.approx(20.0)

    def test_the_latest_twelve_whole_months(self) -> None:
        """A partial month (under 20 days) is not one; the twelve before
        it are the year."""
        air = _daily([40.0] + [60.0] * 12, date(2025, 1, 1))
        air += [(datetime(2026, 2, d, tzinfo=UTC), 99.0) for d in (1, 2)]
        assert climate_of(air) == (60.0, 0.0)

    def test_without_a_whole_year_there_is_none(self) -> None:
        assert climate_of(_daily([60.0] * 11, date(2025, 1, 1))) is None
        gap = _daily([60.0] * 6, date(2025, 1, 1)) + _daily(
            [60.0] * 6, date(2025, 8, 1)
        )
        assert climate_of(gap) is None

    def test_a_missing_reading_is_none_taken(self) -> None:
        air = _daily([60.0] * 12, date(2025, 1, 1))
        assert climate_of([*air, (air[0][0], math.nan)]) == (60.0, 0.0)


class TestTheParametersMains:
    def test_no_climate_is_the_inlet_all_year(self) -> None:
        d = replace(site_example_params().draw, climate_f=None)
        assert d.mains_on(date(2026, 2, 1)) == d.inlet_temp_f

    def test_a_climate_places_the_mains_by_the_day(self) -> None:
        d = site_example_params().draw
        assert d.climate_f is not None
        day = date(2026, 2, 1)
        assert d.mains_on(day) == mains_f(*d.climate_f, day)

    def test_a_negative_swing_is_refused(self) -> None:
        d = site_example_params().draw
        with pytest.raises(ValueError, match="swing"):
            DrawParams(
                delivery_intercept_f=d.delivery_intercept_f,
                delivery_slope=d.delivery_slope,
                inlet_temp_f=d.inlet_temp_f,
                inlet_from_probe=False,
                climate_f=(60.0, -1.0),
            )

    def test_a_document_carries_the_climate(self) -> None:
        params = site_example_params()
        assert params_from_document(params_to_document(params)) == params

    def test_a_scenario_without_an_inlet_takes_the_days_mains(self) -> None:
        """The walk is the one given that day's mains, and names the
        default."""
        params = site_example_params()
        start = datetime(2026, 2, 1, 18, tzinfo=UTC)
        mains = params.draw.mains_on(start)
        base = {
            "start": start,
            "horizon": timedelta(hours=6),
            "tz": "UTC",
            "state": {"upper_f": 135.0, "lower_f": 110.0},
            "settings": {"setpoint_f": 140.0},
            "loads": {
                "draws": [{"at": start + timedelta(hours=1), "gallons": 20.0}]
            },
        }
        modelled = simulate(
            Scenario(**base, environment=Environment(ambient_f=65.0)), params
        )
        given = simulate(
            Scenario(
                **base, environment=Environment(ambient_f=65.0, inlet_f=mains)
            ),
            params,
        )
        assert modelled.simulation == given.simulation
        assert f"inlet_f={mains:.1f} (the climate's mains)" in (
            modelled.defaults_used
        )
        assert not any(d.startswith("inlet_f") for d in given.defaults_used)
