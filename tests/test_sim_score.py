"""``sim_score``: parameters scored on recorded events they were not
fitted on."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nwp500 import sim
from nwp500 import sim_score as ss
from nwp500.sim_calibrate import Prepared

T0 = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)
AIR = 65.0
MINUTE = timedelta(minutes=1)


def _sample(points: Any, start: datetime, end: datetime) -> list[tuple]:
    """``points`` (a walk's path) a sample a minute over ``[start,
    end)``: ``(at, upper, lower)``."""
    out = []
    t = start
    while t < end:
        p = sim.tank_physics.point_at(points, t)  # type: ignore[attr-defined]
        out.append((t, p.upper_f, p.lower_f))
        t += MINUTE
    return out


def _coast(
    params: sim.HeaterParams, at: datetime, upper: float, lower: float, h: float
) -> list[tuple]:
    trace = sim.standby(
        sim.HeaterState(upper_f=upper, lower_f=lower),
        sim.Environment(ambient_f=AIR),
        sim.Loads(),
        params,
        start=at,
        until=at + timedelta(hours=h),
    )
    return _sample(trace.points, at, at + timedelta(hours=h))


def model_history(params: sim.HeaterParams) -> tuple[Prepared, datetime]:
    """A day the model itself walks: a quiet coast, a heat-pump
    recovery from where it left the tank, and a coast after; a sample a
    minute, the compressor's power as the model prices it. The frame
    as ``sim_calibrate.prepare`` leaves one, and the recovery's start."""
    first = _coast(params, T0, 130.0, 110.0, 8.0)
    start, upper, lower = first[-1][0] + MINUTE, first[-1][1], first[-1][2]
    result = sim.simulate(
        sim.Scenario(
            start=start,
            horizon=timedelta(hours=12),
            tz="UTC",
            state=sim.HeaterState(
                upper_f=upper, lower_f=lower, compressor_running=True
            ),
            settings=sim.Settings(setpoint_f=140.0, hp_lower_off_f=140.0),
            environment=sim.Environment(ambient_f=AIR),
        ),
        params,
    )
    run = result.heating[0]
    assert run.input_wh is not None
    hours = (run.end - start).total_seconds() / 3600.0
    heating = _sample(result.points, start, run.end)
    p = sim.tank_physics.point_at(result.points, run.end)  # type: ignore[attr-defined]
    after = _coast(params, run.end, p.upper_f, p.lower_f, 6.0)
    rows = first + heating + after
    on = [False] * len(first) + [True] * len(heating) + [False] * len(after)
    frame = pd.DataFrame(
        {
            "upper_f": [u for _, u, _ in rows],
            "lower_f": [lo for _, _, lo in rows],
            "compressor_on": on,
            "element_on": False,
            "dhw_in_use": False,
            "target_f": 140.0,
            "excluded": False,
            "power_w": np.where(on, run.input_wh / hours, 0.0),
            "energy_to_setpoint_wh": np.nan,
            "air_f": AIR,
            "humidity_pct": 50.0,
            "setpoint_f": 140.0,
        },
        index=pd.DatetimeIndex([t for t, _, _ in rows]),
    )
    ready = Prepared(frame, "constant", "air_f", timedelta(minutes=5), 0, ())
    return ready, start


@pytest.fixture(scope="module")
def site() -> sim.HeaterParams:
    return sim.site_example_params()


@pytest.fixture(scope="module")
def history(site: sim.HeaterParams) -> tuple[Prepared, datetime]:
    return model_history(site)


class TestTheEvents:
    def test_a_day_holds_its_recovery_and_its_quiet_windows(
        self, history: tuple[Prepared, datetime]
    ) -> None:
        ready, start = history
        found = ss.events(ready)
        assert [r.start for r in found.recoveries] == [start]
        assert found.recoveries[0].draw_free
        assert len(found.windows) == 2
        assert found.windows[0].start == T0

    def test_the_span_asked_for_only(
        self, history: tuple[Prepared, datetime]
    ) -> None:
        ready, start = history
        found = ss.events(ready, since=start + MINUTE)
        assert found.recoveries == ()
        assert len(found.windows) == 1

    def test_a_draw_with_the_compressor_near_it_is_not_one(
        self, history: tuple[Prepared, datetime]
    ) -> None:
        ready, start = history
        found = ss.events(
            ready,
            draws=[
                (T0 + timedelta(hours=2), 10.0),
                (start - timedelta(minutes=10), 10.0),
            ],
        )
        assert [d.at for d in found.draws] == [T0 + timedelta(hours=2)]
        assert len(found.draws[0].observed) == 6

    def test_two_draws_close_together_are_neither(
        self, history: tuple[Prepared, datetime]
    ) -> None:
        ready, _ = history
        at = T0 + timedelta(hours=2)
        found = ss.events(
            ready, draws=[(at, 10.0), (at + timedelta(minutes=20), 5.0)]
        )
        assert found.draws == ()


class TestTheScore:
    def test_a_model_scores_near_zero_on_its_own_walk(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        got = ss.score(ss.events(ready), site)
        m = got.metrics
        assert m["recovery_minutes_abs.all"].value <= 1.0
        assert m["recovery_minutes_abs.draw_free"].n == 1
        assert m["recovery_energy_abs_pct"].value < 1.0
        assert m["standby_upper_rmse_f"].value < 0.05
        assert m["standby_lower_rmse_f"].value < 0.05
        assert got.failed == {
            "recoveries": 0,
            "windows": 0,
            "draws": 0,
            "crossings": 0,
        }

    def test_another_model_scores_worse(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        found = ss.events(ready)
        leaky = replace(
            site, loss=replace(site.loss, ua_btu_hr_f=3 * site.loss.ua_btu_hr_f)
        )
        own = ss.score(found, site).metrics["standby_lower_rmse_f"].value
        other = ss.score(found, leaky).metrics["standby_lower_rmse_f"].value
        assert other > own + 0.5

    def test_both_are_scored_on_the_same_events(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        found = ss.events(ready)
        leaky = replace(site, loss=replace(site.loss, ua_btu_hr_f=9.0))
        a = ss.score(found, site).document()
        b = ss.score(found, leaky).document()
        assert a["events"] == b["events"]
        assert a["params_sha256"] != b["params_sha256"]
        assert ss.compare(a, b).same_events

    def test_a_document_is_plain_json(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        import json

        ready, _ = history
        doc = ss.score(ss.events(ready), site).document()
        assert json.loads(json.dumps(doc)) == doc
        assert doc["schema"] == ss.SCHEMA


class TestTheInterval:
    def test_one_day_has_no_spread(self) -> None:
        s = ss._stat([1.0, 3.0], [5, 5])  # pyright: ignore[reportPrivateUsage]
        assert (s.n, s.value, s.lo, s.hi) == (2, 2.0, 2.0, 2.0)

    def test_days_are_resampled_whole(self) -> None:
        s = ss._stat([0.0, 0.0, 10.0], [1, 1, 2])  # pyright: ignore[reportPrivateUsage]
        assert s.value == pytest.approx(10.0 / 3.0)
        assert s.lo == 0.0
        assert s.hi == 10.0


class TestBelowTheAir:
    def test_a_probe_under_the_air_from_above_it_is_a_break(self) -> None:
        air = ((T0, 65.0), (T0 + timedelta(hours=1), 65.0))
        point = sim.tank_physics.Point(T0, 65.0, 64.0)  # type: ignore[attr-defined]
        assert ss._below_air([point], air, 65.0, 65.0)  # pyright: ignore[reportPrivateUsage]

    def test_a_tank_starting_under_the_air_is_not(self) -> None:
        air = ((T0, 65.0),)
        point = sim.tank_physics.Point(T0, 64.0, 60.0)  # type: ignore[attr-defined]
        assert not ss._below_air([point], air, 64.0, 63.0)  # pyright: ignore[reportPrivateUsage]


class TestTheSplit:
    def test_the_latest_fifth_of_the_days(self) -> None:
        instants = [T0 + timedelta(hours=6 * i) for i in range(4 * 20)]
        assert ss.holdout_start(instants) == T0 + timedelta(days=16)

    def test_at_least_three_days(self) -> None:
        instants = [T0 + timedelta(days=i) for i in range(8)]
        assert ss.holdout_start(instants) == T0 + timedelta(days=5)

    def test_the_days_are_local(self) -> None:
        instants = [T0 + timedelta(days=i) for i in range(10)]
        got = ss.holdout_start(instants, tz="America/Los_Angeles")
        assert got is not None
        assert got.astimezone(UTC).hour == 8

    def test_too_few_days_to_split(self) -> None:
        instants = [T0 + timedelta(days=i) for i in range(3)]
        assert ss.holdout_start(instants) is None


class TestTheComparison:
    def _doc(self, value: float, lo: float, hi: float) -> dict[str, Any]:
        return {
            "schema": ss.SCHEMA,
            "events": {"recoveries": ["a"]},
            "metrics": {"m": {"n": 3, "value": value, "lo": lo, "hi": hi}},
        }

    def test_a_clear_change(self) -> None:
        got = ss.compare(self._doc(10, 8, 12), self._doc(5, 4, 6))
        (change,) = got.changes
        assert change.delta == -5
        assert change.clear

    def test_inside_the_interval_is_not_clear(self) -> None:
        got = ss.compare(self._doc(10, 8, 12), self._doc(9, 7, 11))
        assert not got.changes[0].clear

    def test_another_schema_is_refused(self) -> None:
        with pytest.raises(ValueError, match="sim-score"):
            ss.compare({"schema": "x"}, self._doc(1, 1, 1))
