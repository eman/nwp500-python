"""The stratified tank fitted to a history (``sim.tank_fit``): a record
read from a frame, events started from the layers its history leaves,
and the terms of a tank that wrote a history found again from it."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from nwp500 import sim_score as ss
from nwp500.sim import default_params
from nwp500.sim import tank_fit as tf
from nwp500.sim.defaults import site_example_params
from nwp500.sim.physics import stratified as S

T0 = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)
AIR = 66.0
#: The tank that writes the history: the defaults with the terms moved
#: from their priors.
TRUE = tf.with_terms(
    replace(default_params(), circulation=site_example_params().circulation),
    (2.0, 3.0, 1.5, 0.6, 0.3, 4.0, 0.5, 0.8, 3.0, 4.0),
)
#: Draws through the history: (hours in, delivered gallons).
DRAWS = ((7.2, 12.0), (17.0, 4.0), (31.0, 20.0), (44.4, 2.5))
#: The compressor on, and an element run, in hours.
COMPRESSOR = ((20.0, 23.0),)
ELEMENT = ((32.0, 32.4),)


def _at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def _history(
    params=TRUE, hours: float = 54.0
) -> tuple[pd.DataFrame, list[tuple[datetime, float]], list[tuple]]:
    """A history ``params``' tank writes: the probes every minute, the
    flags, the draws, and the tank's own path."""
    lay = S.layout(params)
    record_draws = [(_at(h), g) for h, g in DRAWS]
    state = S.mix(S.estimate(lay, 135.0, 128.0))
    rows: list[dict[str, object]] = []
    path: list[tuple[datetime, S.TankState]] = [(T0, state)]
    for m in range(int(hours * 60)):
        a, b = _at(m / 60), _at((m + 1) / 60)
        h = m / 60
        comp = next(
            (
                S.Compressor(
                    params=params.compressor,
                    on_at=_at(x),
                    heats_at=_at(x)
                    + timedelta(minutes=params.compressor.start_hold_min[-1]),
                    off_at=_at(y),
                )
                for x, y in COMPRESSOR
                if x <= h < y
            ),
            None,
        )
        lag = timedelta(minutes=params.element.upper_dead_time_min)
        elements = tuple(
            S.Element(
                zone="upper",
                watts=params.element.element_w,
                on_at=_at(x),
                off_at=_at(y),
                lag=lag,
            )
            for x, y in ELEMENT
            if _at(x) < b and a < _at(y) + lag
        )
        d = params.draw
        w = S.walk(
            lay,
            state,
            a,
            b,
            air_f=lambda _: AIR,
            heating=S.Heating(compressor=comp, elements=elements),
            draws=[
                S.Delivered(at=t, gal=g, inflow_f=d.inlet_temp_f)
                for t, g in record_draws
                if a <= t < b
            ],
            valve=(d.delivery_intercept_f, d.delivery_slope),
        )
        state = w.state
        path.append((b, state))
        u, lo = S.observe(lay, state)
        rows.append(
            {
                "at": b,
                "upper_f": u,
                "lower_f": lo,
                "air_f": AIR,
                "compressor_on": any(
                    x <= (m + 1) / 60 < y for x, y in COMPRESSOR
                ),
                "element_on": any(x <= (m + 1) / 60 < y for x, y in ELEMENT),
                "circulating": False,
            }
        )
    frame = pd.DataFrame(rows).set_index("at")
    return frame, record_draws, path


@pytest.fixture(scope="module")
def history() -> tuple[pd.DataFrame, list[tuple[datetime, float]], list]:
    return _history()


@pytest.fixture(scope="module")
def record(history) -> tf.TankRecord:
    frame, draws, _ = history
    return tf.tank_record(frame, draws)


def _observed(
    path: list[tuple[datetime, S.TankState]], a: float, b: float
) -> tuple[tuple[datetime, float, float], ...]:
    lay = S.layout(TRUE)
    out = []
    for t, s in path:
        if _at(a) < t <= _at(b) and t.minute % 10 == 0:
            u, lo = S.observe(lay, s)
            out.append((t, u, lo))
    return tuple(out)


def _coasts(path) -> list[tf.Coast]:
    """The quiet stretches and the hours after the draws."""
    lay = S.layout(TRUE)
    out = []
    quiet = ((10.0, 16.5, None), (36.0, 44.0, None))
    after = tuple((h, h + 1.0, g) for h, g in DRAWS if h > 13.0)
    for a, b, gal in (*quiet, *after):
        state = min(path, key=lambda p: abs(p[0] - _at(a)))[1]
        u, lo = S.observe(lay, state)
        out.append(
            tf.Coast(
                start=_at(a),
                end=_at(b),
                upper_f=u,
                lower_f=lo,
                air=((_at(a), AIR),),
                observed=_observed(path, a, b),
                draws=() if gal is None else ((_at(a), gal),),
            )
        )
    return out


class TestTheRecord:
    def test_it_reads_the_frame(self, history, record) -> None:
        frame, draws, _ = history
        assert record.start == frame.index[0].to_pydatetime()
        assert len(record) == len(frame)
        assert record.compressor == ((20 * 60 - 1, 23 * 60 - 1),)
        assert record.element == ((32 * 60 - 1, round(32.4 * 60) - 1),)
        assert record.circulating == ()
        assert record.draws == tuple(draws)
        with pytest.raises(ValueError):
            record.upper_f[0] = 1.0

    def test_the_air_holds_through_its_gaps(self, history) -> None:
        frame, draws, _ = history
        gappy = frame.copy()
        gappy.iloc[:30, gappy.columns.get_loc("air_f")] = math.nan
        gappy.iloc[100:200, gappy.columns.get_loc("air_f")] = math.nan
        r = tf.tank_record(gappy, draws)
        assert np.isfinite(r.air_f).all()

    def test_nothing_drawn_is_no_draw(self, history) -> None:
        frame, draws, _ = history
        r = tf.tank_record(frame, [*draws, (_at(1.0), 0.0)])
        assert r.draws == tuple(draws)

    def test_an_events_part_replays_as_the_whole(self, history, record) -> None:
        _, _, path = history
        for c in _coasts(path):
            part = record.before(c.start)
            assert len(part) <= tf.REPLAY / tf.MINUTE + 20
            assert tf.errors(TRUE, part, c) == tf.errors(TRUE, record, c)

    def test_a_frame_without_the_air_is_refused(self, history) -> None:
        frame, draws, _ = history
        with pytest.raises(ValueError):
            tf.tank_record(frame.drop(columns="air_f"), draws)


class TestTheReplay:
    def test_it_reads_the_probes_it_was_corrected_to(self, record) -> None:
        lay = S.layout(TRUE)
        at = _at(30.0)
        state = tf.replay(lay, TRUE, record, at)
        assert state is not None
        i = record.minute(at)
        u, lo = S.observe(lay, state)
        assert u == pytest.approx(record.upper_f[i], abs=0.3)
        assert lo == pytest.approx(record.lower_f[i], abs=0.3)

    def test_it_finds_the_hidden_layers(self, history, record) -> None:
        """The layers below the lower probe, which the probes do not
        say, come back from the history: closer to the tank's own than
        the estimate from the probes."""
        _, _, path = history
        lay = S.layout(TRUE)
        at = _at(31.5)
        truth = min(path, key=lambda p: abs(p[0] - at))[1]
        u, lo = S.observe(lay, truth)
        replayed = tf.start_state(lay, TRUE, record, at, u, lo)
        estimated = tf.start_state(lay, TRUE, None, at, u, lo)

        def miss(s: S.TankState) -> float:
            return max(
                abs(a - b)
                for a, b in zip(s.layers_f, truth.layers_f, strict=True)
            )

        assert miss(replayed) < miss(estimated) / 3

    def test_before_the_record_there_is_none(self, record) -> None:
        lay = S.layout(TRUE)
        assert tf.replay(lay, TRUE, record, T0 - timedelta(hours=1)) is None
        assert tf.replay(lay, TRUE, record, _at(500.0)) is None

    def test_an_event_starts_where_its_probes_read(self, record) -> None:
        lay = S.layout(TRUE)
        state = tf.start_state(lay, TRUE, record, _at(30.0), 131.0, 124.0)
        u, lo = S.observe(lay, state)
        assert u == pytest.approx(131.0, abs=0.05)
        assert lo == pytest.approx(124.0, abs=0.05)

    def test_it_is_on_the_clock(self, record) -> None:
        """An event at any second of a minute starts from the same
        replay as a walk on the clock's grid would give."""
        lay = S.layout(TRUE)
        a = tf.replay(lay, TRUE, record, _at(30.0))
        b = tf.replay(lay, TRUE, record, _at(30.0) + timedelta(seconds=1))
        assert a is not None and b is not None
        assert a.layers_f == pytest.approx(b.layers_f, abs=0.05)


class TestTheErrors:
    def test_the_tank_that_wrote_it_tracks_it(self, history, record) -> None:
        _, _, path = history
        for c in _coasts(path):
            du, dl = tf.errors(TRUE, record, c)
            assert tf.rmse(du) < 0.3
            assert tf.rmse(dl) < 0.6

    def test_another_tank_does_not(self, history, record) -> None:
        _, _, path = history
        other = tf.with_terms(
            TRUE, (8.0, 0.0, 0.0, 3.0, 0.2, 0.0, 0.0, 0.85, 0.0, 9.0)
        )
        worse = [tf.rmse(tf.errors(other, record, c)[1]) for c in _coasts(path)]
        same = [tf.rmse(tf.errors(TRUE, record, c)[1]) for c in _coasts(path)]
        assert sum(worse) > 3 * sum(same)

    def test_a_coast_needs_its_air_and_observations(self) -> None:
        with pytest.raises(ValueError):
            tf.Coast(_at(0), _at(1), 130.0, 120.0, (), ((_at(1), 1.0, 1.0),))
        with pytest.raises(ValueError):
            tf.Coast(_at(0), _at(1), 130.0, 120.0, ((_at(0), AIR),), ())


class TestTheTerms:
    def test_they_round_trip(self) -> None:
        values = tf.term_values(TRUE)
        assert tf.term_values(tf.with_terms(default_params(), values)) == (
            pytest.approx(values)
        )

    def test_unset_sides_are_the_jackets(self) -> None:
        p = default_params()
        assert p.loss.ua_side_btu_hr_f is None
        assert tf.term_values(p)[0] == S.layout(p).ua_btu_hr_f

    def test_they_are_counted(self) -> None:
        with pytest.raises(ValueError):
            tf.with_terms(TRUE, (1.0,))


class TestTheFit:
    def test_it_finds_the_tank_again(self, history, record) -> None:
        _, _, path = history
        start = replace(
            default_params(), circulation=site_example_params().circulation
        )
        got = tf.fit(start, record, _coasts(path), max_evaluations=60)
        assert got.rmse_after < 0.25 * got.rmse_before
        assert got.rmse_after < 0.3
        assert got.params == tf.with_terms(start, tuple(got.terms.values()))
        names = {t[1] for t in tf.TERMS}
        assert set(got.on_bound) <= names
        for (_, name, lo, hi, _), v in zip(
            tf.TERMS, got.terms.values(), strict=True
        ):
            assert lo <= v <= hi, name

    def test_it_keeps_the_tank_that_wrote_it(self, history, record) -> None:
        _, _, path = history
        got = tf.fit(TRUE, record, _coasts(path), max_evaluations=20)
        assert got.rmse_before < 0.2
        assert got.rmse_after <= got.rmse_before + 1e-9

    def test_it_needs_events(self, record) -> None:
        with pytest.raises(ValueError):
            tf.fit(TRUE, record, [])


class TestTheScore:
    def _events(self, path) -> ss.Events:
        coasts = _coasts(path)
        windows = tuple(
            ss.Window(c.start, c.end, c.upper_f, c.lower_f, c.air, c.observed)
            for c in coasts
            if not c.draws
        )
        draws = tuple(
            ss.DrawEvent(
                c.start, c.draws[0][1], c.upper_f, c.lower_f, c.air, c.observed
            )
            for c in coasts
            if c.draws
        )
        return ss.Events(windows=windows, draws=draws)

    def test_the_tank_that_wrote_it_scores_near_nothing(
        self, history, record
    ) -> None:
        _, _, path = history
        got = ss.score_layers(self._events(path), TRUE, record)
        assert set(got.metrics) == {
            "standby_upper_rmse_f",
            "standby_lower_rmse_f",
            "standby_fall_abs_f_h",
            "standby_gap_sq_f2",
            "draw_upper_rmse_f",
            "draw_lower_rmse_f",
        }
        assert got.metrics["standby_lower_rmse_f"].value < 0.3
        assert got.metrics["draw_lower_rmse_f"].value < 0.6
        assert got.breaks == {"below_air": 0}
        assert got.failed == {"windows": 0, "draws": 0}

    def test_its_document_compares_with_the_simulators(
        self, history, record
    ) -> None:
        _, _, path = history
        found = self._events(path)
        a = ss.score_layers(found, TRUE, record).document()
        b = ss.score_layers(found, default_params(), record).document()
        changes = {c.metric: c for c in ss.compare(a, b).changes}
        assert changes["draw_lower_rmse_f"].delta is not None
        assert ss.compare(a, b).same_events
