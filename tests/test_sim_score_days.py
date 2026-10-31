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
from nwp500.sim.inputs import HEAT_PUMP, VACATION
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
            hp_lower_off_f=((BEFORE, 125.0),),
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
        assert ss._concordance([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == [
            1.0,
            1.0,
            1.0,
        ]

    def test_against_it(self) -> None:
        got = ss._concordance([3.0, 2.0, 1.0], [10.0, 20.0, 30.0])
        assert got == [0.0, 0.0, 0.0]

    def test_a_tie_on_the_meter_says_nothing(self) -> None:
        got = ss._concordance([1.0, 2.0], [10.0, 10.0])
        assert all(np.isnan(got))
