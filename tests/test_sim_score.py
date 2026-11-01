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
from nwp500.sim import tank_fit
from nwp500.sim.physics import stratified
from nwp500.sim.physics.heat_pump import start_hold_min
from nwp500.sim_calibrate import Prepared

T0 = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)
AIR = 65.0
MINUTE = timedelta(minutes=1)


def _sample(
    points: Any, start: datetime, end: datetime
) -> list[tuple[datetime, float, float]]:
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
) -> list[tuple[datetime, float, float]]:
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
    recovery from where it left the tank, holding as the model holds a
    start after a stop it has not seen, and a coast after; a sample a
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
        running_hold=start_hold_min(params.compressor, None),
        running_starts=True,
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

    def test_a_draw_too_near_the_end_to_follow_is_not_one(
        self, history: tuple[Prepared, datetime]
    ) -> None:
        ready, _ = history
        last = ready.frame.index[-1].to_pydatetime()
        found = ss.events(ready, draws=[(last - timedelta(minutes=20), 5.0)])
        assert found.draws == ()

    def test_a_window_is_scored_after_its_start(
        self, history: tuple[Prepared, datetime]
    ) -> None:
        ready, _ = history
        w = ss.events(ready).windows[0]
        assert w.observed[0][0] > w.start

    def test_a_recovery_with_water_in_use_needs_the_meter(
        self, history: tuple[Prepared, datetime]
    ) -> None:
        ready, start = history
        frame = ready.frame.copy()
        frame.loc[frame.index > start + timedelta(minutes=30), "dhw_in_use"] = (
            True
        )
        wet = replace(ready, frame=frame)
        assert ss.events(wet).recoveries == ()
        metered = ss.events(wet, draws=[(start + timedelta(minutes=31), 3.0)])
        assert [r.draw_free for r in metered.recoveries] == [False]

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
    def test_a_recorded_start_is_walked_as_a_start(
        self,
        history: tuple[Prepared, datetime],
        site: sim.HeaterParams,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Seeded running from the layers before it, the start's stir is
        # its own (``running_starts``), as a start the engine makes.
        ready, _ = history
        seen: list[Any] = []
        walk = sim.simulate

        def spy(*args: Any, **kw: Any) -> Any:
            seen.append(kw.get("running_starts"))
            return walk(*args, **kw)

        monkeypatch.setattr(sim, "simulate", spy)
        record = tank_fit.tank_record(ready.frame, [])
        ss.score(
            ss.Events(recoveries=ss.events(ready).recoveries),
            site,
            record=record,
        )
        assert seen == [True]

    def test_with_the_record_each_event_starts_from_its_replay(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        found = ss.events(ready)
        record = tank_fit.tank_record(ready.frame, [])
        replayed = ss.score(found, site, record=record)
        assert replayed.failed == ss.score(found, site).failed
        assert replayed.metrics != ss.score(found, site).metrics
        w = found.windows[0]
        lay = stratified.layout(site)
        state = ss._state(site, record, w.start, w.upper_f, w.lower_f)  # pyright: ignore[reportPrivateUsage]
        assert (
            state.layers_f
            == tank_fit.start_state(
                lay, site, record, w.start, w.upper_f, w.lower_f
            ).layers_f
        )

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
        # A window starts from the layers its probes stand for, not the
        # ones the walk left there: the lower probe drifts apart by a
        # tenth of a degree.
        assert m["standby_lower_rmse_f"].value < 0.15
        assert got.failed == {
            "recoveries": 0,
            "windows": 0,
            "draws": 0,
            "deliveries": 0,
        }

    def test_another_model_scores_worse(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        found = ss.events(ready)
        leaky = replace(
            site,
            loss=replace(
                site.loss, ua_side_btu_hr_f=3 * site.loss.ua_side_btu_hr_f
            ),
        )
        own = ss.score(found, site).metrics["standby_lower_rmse_f"].value
        other = ss.score(found, leaky).metrics["standby_lower_rmse_f"].value
        assert other > own + 0.5

    def test_both_are_scored_on_the_same_events(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        leaky = replace(site, loss=replace(site.loss, ua_side_btu_hr_f=9.0))
        a = ss.score(ss.events(ready), site).document()
        b = ss.score(ss.events(ready), leaky).document()
        assert a["events"] == b["events"]
        assert a["params_sha256"] != b["params_sha256"]
        assert ss.compare(a, b).same_events

    def test_a_run_past_the_horizon_is_unanswered(
        self,
        history: tuple[Prepared, datetime],
        site: sim.HeaterParams,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ready, start = history
        found = ss.events(ready)
        (r,) = found.recoveries
        short = replace(
            found, recoveries=(replace(r, end=start + 20 * MINUTE),)
        )
        monkeypatch.setattr(ss, "RECOVERY_SLACK", timedelta(0))
        got = ss.score(short, site)
        assert got.failed["recoveries"] == 1
        assert got.failed_events["recoveries"] == [ss._iso(start)]  # pyright: ignore[reportPrivateUsage]
        assert "recovery_minutes_abs.all" not in got.metrics
        whole = ss.score(found, site).document()
        assert not ss.compare(whole, got.document()).same_events

    def test_a_document_is_plain_json(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        import json

        ready, _ = history
        doc = ss.score(ss.events(ready), site).document()
        assert json.loads(json.dumps(doc)) == doc
        assert doc["schema"] == ss.SCHEMA


class TestTheDeliveries:
    def _delivery(self, crossed: bool, gal: float) -> ss.Delivery:
        return ss.Delivery(T0, 140.0, 138.0, 140.0, crossed, gal)

    def _score(self, e: ss.Delivery, site: sim.HeaterParams) -> ss.Score:
        return ss.score(ss.Events(deliveries=(e,)), site)

    def test_a_draw_that_never_crossed_is_a_floor(
        self, site: sim.HeaterParams
    ) -> None:
        small = self._score(self._delivery(False, 5.0), site)
        assert small.metrics["deliverable_short_gal"].value == 0.0
        assert small.metrics["deliverable_under_share"].value == 0.0
        assert "deliverable_abs_gal" not in small.metrics
        large = self._score(self._delivery(False, 500.0), site)
        assert large.metrics["deliverable_short_gal"].value > 400.0
        assert large.metrics["deliverable_under_share"].value == 1.0
        assert large.over_promised == 0

    def test_a_crossing_is_scored_both_ways(
        self, site: sim.HeaterParams
    ) -> None:
        got = self._score(self._delivery(True, 5.0), site)
        promised = got.metrics["deliverable_bias_gal"].value
        assert promised > 0.0
        assert got.metrics["deliverable_abs_gal"].value == promised
        assert got.over_promised == 1


class TestADeliverysOwnDraw:
    """A delivery starts on the meter's clock, its draw's onset on the
    detector's: seconds earlier, and in the minute before."""

    AT = T0 + timedelta(hours=2, seconds=5)

    def _record(
        self, ready: Prepared, draws: list[tuple[datetime, float]]
    ) -> tank_fit.TankRecord:
        return tank_fit.tank_record(ready.frame, draws)

    def test_its_onset_is_left_out_of_the_replay(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        own = (self.AT - timedelta(seconds=10), 15.0)
        record = self._record(ready, [own])
        kept = ss._without_own_draw(record, self.AT)  # pyright: ignore[reportPrivateUsage]
        assert kept.draws == ()

        def layers(r: tank_fit.TankRecord) -> tuple[float, ...] | None:
            return ss._state(site, r, self.AT, 140.0, 138.0).layers_f  # pyright: ignore[reportPrivateUsage]

        assert layers(kept) == layers(self._record(ready, []))
        assert layers(record) != layers(kept)

    def test_an_earlier_draw_is_kept(
        self, history: tuple[Prepared, datetime]
    ) -> None:
        ready, _ = history
        earlier = (self.AT - timedelta(minutes=30), 5.0)
        own = (self.AT - timedelta(seconds=10), 15.0)
        record = self._record(ready, [earlier, own])
        kept = ss._without_own_draw(record, self.AT)  # pyright: ignore[reportPrivateUsage]
        assert kept.draws == (earlier,)

    def test_it_is_scored_as_if_it_had_not_happened(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        e = ss.Delivery(self.AT, 140.0, 138.0, 140.0, True, 5.0)
        found = ss.Events(deliveries=(e,))
        own = (self.AT - timedelta(seconds=10), 15.0)
        with_own = ss.score(found, site, record=self._record(ready, [own]))
        without = ss.score(found, site, record=self._record(ready, []))
        assert with_own.metrics == without.metrics


class TestADrawJustBeforeARecovery:
    """A recovery starts at a compressor edge, any second of a minute,
    and its replay stops at that minute's start."""

    def test_is_replayed_as_one_in_the_minute_before(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        (r,) = ss.events(ready).recoveries
        r = replace(r, start=r.start + timedelta(seconds=40))

        def bias(seconds: float | None) -> float:
            draws = (
                []
                if seconds is None
                else [(r.start - timedelta(seconds=seconds), 10.0)]
            )
            record = tank_fit.tank_record(ready.frame, draws)
            return (
                ss.score(ss.Events(recoveries=(r,)), site, record=record)
                .metrics["recovery_minutes_bias.all"]
                .value
            )

        # 8 s before, in the start's minute; 41 s before, in the one
        # before it.
        assert bias(8.0) == pytest.approx(bias(41.0), abs=0.5)
        assert bias(8.0) != bias(None)

    def test_is_not_walked_again(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        (r,) = ss.events(ready).recoveries
        at = r.start + timedelta(seconds=40)
        record = tank_fit.tank_record(
            ready.frame, [(at - timedelta(seconds=8), 10.0)]
        )
        moved = ss._replayable(record, at)  # pyright: ignore[reportPrivateUsage]
        edge = record.instant(record.minute(at))
        assert [t for t, _ in moved.draws] == [edge - timedelta(microseconds=1)]


class TestASetpointChangedInsideARecovery:
    def test_is_read_from_the_history(
        self, history: tuple[Prepared, datetime]
    ) -> None:
        ready, start = history
        frame = ready.frame.copy()
        at = start + timedelta(minutes=20)
        frame.loc[frame.index >= at, "setpoint_f"] = 145.0
        (r,) = ss.events(replace(ready, frame=frame)).recoveries
        assert r.setpoint_f == 140.0
        assert r.setpoints == ((at, 145.0),)
        (unchanged,) = ss.events(ready).recoveries
        assert unchanged.setpoints == ()

    def test_is_walked_as_a_write(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        ready, _ = history
        (r,) = ss.events(ready).recoveries

        def bias(e: ss.Recovery) -> float:
            return (
                ss.score(ss.Events(recoveries=(e,)), site)
                .metrics["recovery_minutes_bias.all"]
                .value
            )

        raised = replace(
            r, setpoints=((r.start + timedelta(minutes=20), 145.0),)
        )
        assert bias(r) == pytest.approx(0.0, abs=1.0)
        assert bias(raised) > bias(r) + 5.0

    def test_lowered_and_raised_back_is_one_run(
        self, history: tuple[Prepared, datetime], site: sim.HeaterParams
    ) -> None:
        """A setpoint dipped below the upper probe for seconds stops
        the walk's compressor and starts it again: the record's run went
        on through it, and the chain is scored as that run."""

        def bias(e: ss.Recovery) -> float:
            return (
                ss.score(ss.Events(recoveries=(e,)), site)
                .metrics["recovery_minutes_bias.all"]
                .value
            )

        def energy(e: ss.Recovery) -> tuple[float, float]:
            got = ss.score(ss.Events(recoveries=(e,)), site).metrics
            return (
                got["recovery_energy_bias_pct"].value,
                got["recovery_energy_abs_pct"].value,
            )

        ready, _ = history
        (r,) = ss.events(ready).recoveries
        at = r.start + timedelta(minutes=20)
        dipped = replace(
            r, setpoints=((at, 121.0), (at + timedelta(seconds=5), 140.0))
        )
        got = ss.score(ss.Events(recoveries=(dipped,)), site).metrics
        assert got["recovery_minutes_bias.all"].value == pytest.approx(
            0.0, abs=15.0
        )
        # Restored after the lockout has passed: still the same run.
        held = replace(
            r, setpoints=((at, 121.0), (at + timedelta(minutes=7), 140.0))
        )
        got = ss.score(ss.Events(recoveries=(held,)), site).metrics
        assert got["recovery_minutes_bias.all"].value == pytest.approx(
            0.0, abs=15.0
        )
        # Raised after the walk reached the setpoint in force (at 106.5
        # of the record's 179.2 min from 130 degF): the raise's restart
        # is the same run, scored +19.4 min against -72.7 without it.
        low = replace(r, setpoint_f=130.0)
        assert bias(low) < -60.0
        later = replace(
            low, setpoints=((r.start + timedelta(minutes=116.5), 140.0),)
        )
        assert abs(bias(later)) < abs(bias(low)) - 40.0
        # Its electricity is both runs': +5.0 % against the meter's whole
        # run, -42.7 % with the first alone.
        first, _ = energy(low)
        both, both_abs = energy(later)
        assert first < -40.0
        assert both == pytest.approx(5.0, abs=3.0)
        assert both_abs == pytest.approx(abs(both))
        # One just before the recorded end: a restart past it is not the
        # recorded run's.
        at = r.end - timedelta(seconds=20)
        late = replace(
            r, setpoints=((at, 121.0), (at + timedelta(seconds=5), 140.0))
        )
        got = ss.score(ss.Events(recoveries=(late,)), site).metrics
        assert got["recovery_minutes_bias.all"].value == pytest.approx(
            0.0, abs=2.0
        )
        # Nor its electricity: -0.2 % against the meter, where the
        # restart's would add 7 %.
        late_bias, late_abs = energy(late)
        assert late_bias == pytest.approx(0.0, abs=1.0)
        assert late_abs == pytest.approx(abs(late_bias))

    def test_only_its_changes_inside_count(self) -> None:
        seconds = np.array([0.0, 60.0, 120.0, 180.0, 240.0, 300.0])
        values = np.array([140.0, 140.0, np.nan, 145.0, 145.0, 150.0])
        at = datetime.fromtimestamp(0.0, UTC)
        got = ss._changes(  # pyright: ignore[reportPrivateUsage]
            values, seconds, at, at + timedelta(seconds=300)
        )
        assert got == ((at + timedelta(seconds=180), 145.0),)


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

    def test_other_failures_are_other_events(self) -> None:
        a = self._doc(10, 8, 12)
        b = {**self._doc(5, 4, 6), "failed_events": {"recoveries": ["a"]}}
        assert not ss.compare(a, b).same_events
        empty = {**a, "failed_events": {"recoveries": []}}
        assert ss.compare(a, empty).same_events

    def test_another_schema_is_refused(self) -> None:
        with pytest.raises(ValueError, match="sim-score"):
            ss.compare({"schema": "x"}, self._doc(1, 1, 1))
