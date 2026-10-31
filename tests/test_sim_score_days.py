"""``sim_score``'s days: whole recorded days walked from their start and
scored on the electricity, its timing, the starts and the tank."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from nwp500 import sim
from nwp500 import sim_score as ss
from nwp500.sim import tank_fit
from nwp500.sim.inputs import ENERGY_SAVER, HEAT_PUMP, VACATION
from nwp500.sim.record import Record
from nwp500.sim_calibrate import Prepared

T0 = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)
DAY = timedelta(days=1)
MINUTE = timedelta(minutes=1)
AIR = 65.0
BEFORE = T0 - DAY


def _draws() -> tuple[sim.Draw, ...]:
    return tuple(
        sim.Draw(at=T0 + timedelta(days=d, hours=h), gallons=g)
        for d in range(2)
        for h, g in ((7.0, 12.0), (7.5, 10.0), (19.0, 15.0))
    )


def _scenario() -> sim.Scenario:
    return sim.Scenario(
        start=T0,
        horizon=2 * DAY,
        tz="UTC",
        state=sim.HeaterState(upper_f=125.0, lower_f=118.0),
        settings=sim.Settings(
            setpoint_f=125.0,
            mode=HEAT_PUMP,
            hp_lower_on_f=111.0,
            hp_lower_off_f=125.0,
            hp_upper_on_f=104.9,
        ),
        history=sim.History(compressor_stopped_at=T0 - timedelta(hours=3)),
        environment=sim.Environment(ambient_f=AIR, inlet_f=58.0),
        loads=sim.Loads(draws=_draws()),
        commands=sim.Commands(
            writes=(
                sim.Write(at=T0 + DAY + timedelta(hours=13), setpoint_f=135.0),
                sim.Write(at=T0 + DAY + timedelta(hours=21), setpoint_f=125.0),
            )
        ),
    )


def _flags(
    runs: list[tuple[datetime, datetime]],
) -> tuple[tuple[datetime, float], ...]:
    rows = [(BEFORE, 0.0)]
    for a, b in runs:
        rows += [(a, 1.0), (b, 0.0)]
    return tuple(rows)


class Walked:
    """Two days the model walks, as a heater's record of them."""

    def __init__(self, params: sim.HeaterParams) -> None:
        result = sim.simulate(_scenario(), params)
        self.result = result
        grid = pd.date_range(T0, T0 + 2 * DAY, freq="1min", inclusive="left")
        at = [t.to_pydatetime() for t in grid]
        points = [
            sim.tank_physics.point_at(result.points, t)  # type: ignore[attr-defined]
            for t in at
        ]
        heating = [h for h in result.heating if h.input_wh is not None]
        compressor = [
            (h.start.at, h.end) for h in heating if h.source == "compressor"
        ]
        element = [
            (h.start.at, h.end) for h in heating if h.source == "element"
        ]
        on = np.zeros(len(at), dtype=bool)
        for a, b in compressor:
            on |= (grid >= a) & (grid < b)
        # Each run's power its own mean, so the meter is the walk's.
        power: list[tuple[datetime, float]] = [(BEFORE, 0.0)]
        for h in sorted(heating, key=lambda h: h.start.at):
            hours = (h.end - h.start.at).total_seconds() / 3600.0
            assert h.input_wh is not None
            power += [(h.start.at, h.input_wh / hours), (h.end, 0.0)]
        # The meter reports its value at least hourly, as a polled one
        # does (``observed.POWER_HOLD``).
        hourly = [BEFORE + timedelta(hours=k) for k in range(3 * 24)]
        power = sorted(
            power
            + [
                (t, next(v for a, v in reversed(power) if a <= t))
                for t in hourly
            ]
        )
        setpoints = [(BEFORE, 125.0)] + [
            (w.at, w.setpoint_f) for w in result.writes if w.setpoint_f
        ]
        self.record = Record(
            compressor=_flags(compressor),
            upper_element=_flags(element),
            lower_element=_flags([]),
            power_w=tuple(power),
            mode=((BEFORE, float(HEAT_PUMP)),),
            setpoint_f=tuple(setpoints),
            upper_f=tuple((t, p.upper_f) for t, p in zip(at, points)),
            lower_f=tuple((t, p.lower_f) for t, p in zip(at, points)),
            hp_lower_on_f=((BEFORE, 111.0),),
            # The device's stop threshold follows its setpoint.
            hp_lower_off_f=tuple(setpoints),
            hp_upper_on_f=((BEFORE, 104.9),),
            tou=((BEFORE, 0.0),),
        )
        frame = pd.DataFrame(
            {
                "upper_f": [p.upper_f for p in points],
                "lower_f": [p.lower_f for p in points],
                "compressor_on": on,
                "element_on": False,
                "dhw_in_use": False,
                "target_f": 125.0,
                "excluded": False,
                "power_w": 0.0,
                "energy_to_setpoint_wh": np.nan,
                "air_f": AIR,
                "humidity_pct": 50.0,
                "setpoint_f": 125.0,
            },
            index=grid,
        )
        self.ready = Prepared(
            frame, "constant", "air_f", timedelta(minutes=5), 0, ()
        )
        self.draws = [(d.at, d.gallons) for d in _draws()]
        self.tank = tank_fit.tank_record(frame, self.draws)


@pytest.fixture(scope="module")
def site() -> sim.HeaterParams:
    return sim.site_example_params()


@pytest.fixture(scope="module")
def walked(site: sim.HeaterParams) -> Walked:
    return Walked(site)


def _days(w: Walked, record: Record | None = None) -> tuple[ss.Day, ...]:
    return ss.day_events(
        w.ready, w.record if record is None else record, w.tank, tz="UTC"
    )


class TestTheDays:
    def test_each_whole_day_the_record_covers(self, walked: Walked) -> None:
        assert [d.start for d in _days(walked)] == [T0, T0 + DAY]

    def test_a_day_carries_what_the_heater_was_told(
        self, walked: Walked
    ) -> None:
        second = _days(walked)[1]
        # As they landed, on the device's half-degree Celsius.
        assert [w.setpoint_f for w in second.scenario.commands.writes] == [
            pytest.approx(134.6, abs=0.05),
            pytest.approx(124.7, abs=0.05),
        ]
        assert second.scenario.settings.hp_lower_on_f == 111.0
        assert second.scenario.settings.hp_lower_off_f == 125.0
        assert len(second.scenario.loads.draws) == 3

    def test_and_what_it_did(self, walked: Walked) -> None:
        second = _days(walked)[1]
        walked_starts = [
            h.start.at
            for h in walked.result.heating
            if h.source == "compressor" and T0 + DAY < h.start.at < T0 + 2 * DAY
        ]
        assert list(second.compressor_starts) == walked_starts
        assert len(second.slots_wh) == 24
        assert second.metered_wh == pytest.approx(sum(second.slots_wh))

    def test_a_setting_set_long_before_still_holds(
        self, walked: Walked
    ) -> None:
        long_ago = T0 - timedelta(days=200)
        old = replace(
            walked.record,
            hp_lower_on_f=((long_ago, 111.0),),
            mode=((long_ago, float(HEAT_PUMP)),),
        )
        first = _days(walked, old)[0]
        assert first.scenario.settings.hp_lower_on_f == 111.0

    def test_a_day_with_a_threshold_unknown_is_not_one(
        self, walked: Walked
    ) -> None:
        for name in ("hp_lower_on_f", "hp_lower_off_f", "hp_upper_on_f", "tou"):
            assert _days(walked, replace(walked.record, **{name: ()})) == ()

    def test_an_outage_from_the_next_midnight_is_the_next_days(
        self, walked: Walked
    ) -> None:
        frame = walked.ready.frame.copy()
        frame["heater_unobserved"] = frame.index >= T0 + DAY
        dark = replace(walked.ready, frame=frame)
        got = ss.day_events(dark, walked.record, walked.tank, tz="UTC")
        assert [d.start for d in got] == [T0]

    def test_the_days_lowest_holds_its_end(self, walked: Walked) -> None:
        frame = walked.ready.frame.copy()
        frame.loc[T0 + DAY, "upper_f"] = 100.0
        low = replace(walked.ready, frame=frame)
        first = ss.day_events(low, walked.record, walked.tank, tz="UTC")[0]
        assert first.min_upper_f == 100.0
        assert first.end_upper_f == 100.0

    def test_the_span_asked_for_only(self, walked: Walked) -> None:
        got = ss.day_events(
            walked.ready, walked.record, walked.tank, tz="UTC", since=T0 + DAY
        )
        assert [d.start for d in got] == [T0 + DAY]

    def test_a_day_the_meter_is_silent_is_not_one(self, walked: Walked) -> None:
        silent = replace(
            walked.record,
            power_w=tuple(
                (t, v) for t, v in walked.record.power_w if t < T0 + DAY
            ),
        )
        # The last value holds past its hold (``observed.POWER_HOLD``) only.
        far = ss.day_events(
            walked.ready,
            replace(silent, power_w=((BEFORE - 3 * DAY, 0.0),)),
            walked.tank,
            tz="UTC",
        )
        assert far == ()

    def test_a_day_with_a_write_into_vacation_is_not_one(
        self, walked: Walked
    ) -> None:
        away = replace(
            walked.record,
            mode=(
                (BEFORE, float(HEAT_PUMP)),
                (T0 + DAY + timedelta(hours=9), float(VACATION)),
            ),
        )
        assert [d.start for d in _days(walked, away)] == [T0]

    def test_a_marked_window_is_the_days(self, walked: Walked) -> None:
        marked = replace(
            walked.record,
            hp_upper_on_f=(
                (BEFORE, 104.9),
                (T0 + timedelta(hours=16), 124.0),
                (T0 + timedelta(hours=21), 104.9),
                (T0 + DAY + timedelta(hours=23), 124.0),
                (T0 + 2 * DAY + timedelta(hours=2), 104.9),
            ),
        )
        first, second = _days(walked, marked)
        assert first.windows == (
            (T0 + timedelta(hours=16), T0 + timedelta(hours=21)),
        )
        # One open at the day's end runs to its close.
        assert second.windows == (
            (T0 + DAY + timedelta(hours=23), T0 + 2 * DAY + timedelta(hours=2)),
        )

    def test_a_window_open_at_midnight_keeps_its_opening(
        self, walked: Walked
    ) -> None:
        marked = replace(
            walked.record,
            hp_upper_on_f=(
                (BEFORE, 104.9),
                (T0 + DAY - timedelta(hours=2), 124.0),
                (T0 + DAY + timedelta(hours=1), 104.9),
            ),
        )
        second = _days(walked, marked)[1]
        assert second.windows == (
            (T0 + DAY - timedelta(hours=2), T0 + DAY + timedelta(hours=1)),
        )

    def test_a_write_at_midnight_is_the_days(
        self, walked: Walked, site: sim.HeaterParams
    ) -> None:
        raised = [(BEFORE, 125.0), (T0 + DAY, 130.1)]
        told = replace(
            walked.record,
            setpoint_f=tuple(raised),
            hp_lower_off_f=tuple(raised),
        )
        second = _days(walked, told)[1]
        assert second.scenario.settings.setpoint_f == 125.0
        [write] = second.scenario.commands.writes
        assert write.at == T0 + DAY
        assert write.setpoint_f == pytest.approx(130.1, abs=0.05)
        got = ss.score(ss.Events(days=(second,)), site, inlet_f=58.0)
        assert got.failed["days"] == 0

    def test_a_stop_short_of_the_setpoint_is_not_walked(
        self, walked: Walked
    ) -> None:
        short = replace(
            walked.record,
            hp_lower_off_f=(
                *walked.record.hp_lower_off_f,
                (T0 + DAY + timedelta(hours=3), 120.2),
            ),
        )
        assert [d.start for d in _days(walked, short)] == [T0]

    def test_a_stop_reported_after_its_setpoint_follows_it(
        self, walked: Walked
    ) -> None:
        late = replace(
            walked.record,
            hp_lower_off_f=tuple(
                (t + timedelta(seconds=2), v)
                for t, v in walked.record.hp_lower_off_f
            ),
        )
        assert [d.start for d in _days(walked, late)] == [T0, T0 + DAY]

    def test_a_setpoint_changed_just_before_midnight(
        self, walked: Walked
    ) -> None:
        raised = (
            *walked.record.setpoint_f,
            (T0 + DAY - timedelta(seconds=10), 130.1),
        )
        late = replace(
            walked.record,
            setpoint_f=tuple(sorted(raised)),
            hp_lower_off_f=tuple(
                sorted(
                    (
                        *walked.record.hp_lower_off_f,
                        (T0 + DAY + timedelta(seconds=5), 130.1),
                    )
                )
            ),
        )
        assert [d.start for d in _days(walked, late)] == [T0, T0 + DAY]

    def test_a_drop_for_a_window_opened_before_midnight(
        self, walked: Walked
    ) -> None:
        dropped = replace(
            walked.record,
            mode=(
                (BEFORE, float(ENERGY_SAVER)),
                (T0 + DAY + timedelta(seconds=2), float(HEAT_PUMP)),
            ),
            hp_upper_on_f=(
                (BEFORE, 104.9),
                (T0 + DAY - timedelta(seconds=2), 124.0),
                (T0 + DAY + timedelta(hours=1), 104.9),
            ),
        )
        second = _days(walked, dropped)[1]
        assert second.scenario.settings.mode == ENERGY_SAVER
        assert [w.mode for w in second.scenario.commands.writes][:1] == [
            HEAT_PUMP
        ]

    def test_a_drop_for_a_window_opened_after_midnight(
        self, walked: Walked
    ) -> None:
        dropped = replace(
            walked.record,
            mode=(
                (BEFORE, float(ENERGY_SAVER)),
                (T0 + DAY + timedelta(seconds=2), float(HEAT_PUMP)),
            ),
            hp_upper_on_f=(
                (BEFORE, 104.9),
                (T0 + DAY + timedelta(seconds=4), 124.0),
                (T0 + DAY + timedelta(hours=1), 104.9),
            ),
        )
        second = _days(walked, dropped)[1]
        # The walk drops it itself, where the window opens.
        assert HEAT_PUMP not in [
            w.mode for w in second.scenario.commands.writes
        ]

    def test_a_recorder_gap_is_not_observed(self, walked: Walked) -> None:
        frame = walked.ready.frame.copy()
        frame["unrecorded"] = (frame.index >= T0 + timedelta(hours=5)) & (
            frame.index < T0 + timedelta(hours=7)
        )
        gap = replace(walked.ready, frame=frame)
        got = ss.day_events(gap, walked.record, walked.tank, tz="UTC")
        assert [d.start for d in got] == [T0 + DAY]


class TestTheDayScore:
    def test_the_model_scores_its_own_days(
        self, walked: Walked, site: sim.HeaterParams
    ) -> None:
        found = ss.Events(days=_days(walked))
        got = ss.score(found, site, inlet_f=58.0, record=walked.tank)
        assert got.failed["days"] == 0
        m = got.metrics
        assert m["day_energy_abs_pct"].n == 2
        # Started from the replay, not the walk's own layers.
        assert m["day_energy_abs_pct"].value < 10.0
        assert m["day_compressor_starts_placed_share"].value == 1.0
        assert m["day_compressor_starts_false"].value == 0.0
        assert m["day_line_disagree_share"].value == 0.0
        assert m["day_min_upper_abs_f"].value < 2.0
        assert m["day_energy_misplaced_share"].value < 0.1
        assert "day_energy_concordance" in m

    def test_a_start_at_the_days_first_instant_is_one(
        self, walked: Walked, site: sim.HeaterParams
    ) -> None:
        first = _days(walked)[0]
        cold = replace(
            first,
            scenario=first.scenario.model_copy(
                update={"state": sim.HeaterState(upper_f=95.0, lower_f=90.0)}
            ),
            compressor_starts=(T0 + timedelta(seconds=20),),
        )
        got = ss.score(ss.Events(days=(cold,)), site, inlet_f=58.0).metrics
        assert got["day_compressor_starts_placed_share"].value == 1.0
        assert got["day_compressor_starts_missed"].value == 0.0

    def test_a_day_in_a_quarter_hour_zone(self, walked: Walked) -> None:
        days = ss.day_events(
            walked.ready, walked.record, walked.tank, tz="Asia/Kathmandu"
        )
        assert [d.start.minute for d in days] == [15]

    def test_days_are_a_kind_of_their_own(
        self, walked: Walked, site: sim.HeaterParams
    ) -> None:
        with_days = ss.Events(days=_days(walked))
        assert with_days.keys()["days"] == [
            T0.isoformat(),
            (T0 + DAY).isoformat(),
        ]
        assert "days" not in ss.Events().keys()
        a = ss.score(ss.Events(), site).document()
        b = ss.score(with_days, site, record=walked.tank).document()
        assert "days" not in a["failed"]
        # A score without days compares with one with them on the kinds
        # both carry.
        assert ss.compare(a, b).same_events


class _Steady:
    """A walk drawing 12 Wh an hour from ``start``, on the clock's
    grid as ``SimulationResult.energy_by_slot`` lays it out."""

    def __init__(self, start: datetime, hours: int) -> None:
        self.start, self.end = start, start + timedelta(hours=hours)

    def energy_by_slot(
        self, slot: timedelta
    ) -> list[tuple[datetime, float | None]]:
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        at = epoch + (self.start - epoch) // slot * slot
        out: list[tuple[datetime, float | None]] = []
        while at < self.end:
            on = min(at + slot, self.end) - max(at, self.start)
            out.append((at, 12.0 * on / timedelta(hours=1)))
            at += slot
        return out


class TestTheHours:
    def test_laid_out_from_a_quarter_past_midnight(self) -> None:
        # Kathmandu's midnight, 18:15 UTC: no slot straddles its hours.
        start = datetime(2026, 3, 2, 18, 15, tzinfo=UTC)
        got = ss._hours(_Steady(start, 2), start, 2)
        assert got == [pytest.approx(12.0), pytest.approx(12.0)]


class TestTheHoldLeft:
    def test_a_start_before_midnight_holds_on_past_it(
        self, walked: Walked, site: sim.HeaterParams
    ) -> None:
        first = _days(walked)[0]
        held = replace(
            site,
            compressor=replace(
                site.compressor,
                start_hold_after_min=(),
                start_hold_min=(12.0,),
            ),
        )
        running = replace(
            first,
            scenario=first.scenario.model_copy(
                update={
                    "state": first.scenario.state.model_copy(
                        update={"compressor_running": True}
                    )
                }
            ),
            compressor_on_since=T0 - timedelta(minutes=5),
        )
        assert ss._hold_left(running, held) == pytest.approx(7.0)
        assert ss._hold_left(first, held) == 0.0


class TestPlacing:
    def test_each_prediction_places_one_start(self) -> None:
        t = T0 + timedelta(hours=6)
        assert ss._placed([t, t + timedelta(minutes=10)], [t]) == 1

    def test_the_nearest(self) -> None:
        t = T0 + timedelta(hours=6)
        a, b = t, t + timedelta(minutes=25)
        # The prediction 5 min from b is b's; a's is 20 min from it.
        assert ss._placed([a, b], [t + timedelta(minutes=20), b - MINUTE]) == 2

    def test_the_most_pairs(self) -> None:
        t = T0 + timedelta(hours=6)
        # The nearest to 0 is +20, which leaves +50 nothing; -25 and +20
        # place both.
        recorded = [t, t + timedelta(minutes=50)]
        predicted = [t - timedelta(minutes=25), t + timedelta(minutes=20)]
        assert ss._placed(recorded, predicted) == 2

    def test_not_past_the_match(self) -> None:
        t = T0 + timedelta(hours=6)
        assert ss._placed([t], [t + ss.START_MATCH + MINUTE]) == 0


class TestConcordance:
    def test_days_ordered_as_the_meter_orders_them(self) -> None:
        assert ss._concordance([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == 1.0

    def test_against_it(self) -> None:
        assert ss._concordance([3.0, 2.0, 1.0], [10.0, 20.0, 30.0]) == 0.0

    def test_a_tie_on_the_meter_says_nothing(self) -> None:
        assert np.isnan(ss._concordance([1.0, 2.0], [10.0, 10.0]))
        assert ss._concordance([1.0, 2.0, 0.0], [10.0, 10.0, 5.0]) == 1.0

    def test_no_pair_says_nothing(self) -> None:
        assert np.isnan(ss._concordance_stat([], []).value)
        assert np.isnan(ss._concordance_stat([1.0, 2.0], [5.0, 5.0]).value)

    def test_its_interval_draws_the_pairs_afresh(self) -> None:
        # One day out of order among ten: 9 of 45 pairs.
        metered = [float(k) for k in range(10)]
        predicted = [*metered[1:], -1.0]
        got = ss._concordance_stat(predicted, metered)
        assert got.value == pytest.approx(36 / 45)
        assert got.n == 10
        assert got.lo < got.value < got.hi
