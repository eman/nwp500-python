"""The tank's layers a recorded history leaves (``sim.history``)."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from nwp500 import sim_adapters as sa
from nwp500.sim import default_params, site_example_params
from nwp500.sim import history as hist
from nwp500.sim import tank_fit as tf
from nwp500.sim.physics import stratified as st

T0 = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
STEP_S = 10.0
P = default_params()


def _steps(
    hours: float,
    *,
    upper_f: float = 128.0,
    lower_f: float = 126.0,
    draw: tuple[float, float, float] | None = None,
    compressor: tuple[float, float] | None = None,
    volume: hist.FlowVolume = "delivered",
) -> list[hist.Step]:
    """``hours`` of a quiet tank on 10 s steps from ``T0``: with
    ``draw`` (from, to hours, gal/min) a draw, with ``compressor``
    (from, to hours) a run, the lower probe at 100 °F after the draw
    until the run ends."""
    out = []
    n = round(hours * 3600 / STEP_S)
    for k in range(n):
        h = k * STEP_S / 3600
        drawing = draw is not None and draw[0] <= h < draw[1]
        running = compressor is not None and compressor[0] <= h < compressor[1]
        after = draw is not None and h >= draw[0]
        settled = compressor is not None and h >= compressor[1]
        out.append(
            hist.Step(
                seconds=STEP_S,
                upper_f=upper_f,
                lower_f=100.0 if after and not settled else lower_f,
                flow_gpm=draw[2] if drawing and draw is not None else 0.0,
                compressor_on=running,
                element_on=False,
                ambient_f=62.0,
                inlet_f=60.0,
                flow_volume=volume,
                at=T0 + timedelta(seconds=k * STEP_S),
            )
        )
    return out


class TestTheRecord:
    def test_it_is_on_the_minutes(self) -> None:
        steps = _steps(2.0, draw=(1.0, 1.25, 2.0), compressor=(1.5, 1.75))
        rec = hist.record(steps, P)
        assert rec.start == T0
        assert len(rec) == 120
        assert rec.compressor == ((90, 105),)
        assert rec.element == ()
        assert rec.lower_f[59] == 126.0 and rec.lower_f[60] == 100.0
        assert sum(g for _, g in rec.draws) == pytest.approx(30.0)
        assert len(rec.draws) == 15
        assert rec.draws[0][0] == T0 + timedelta(hours=1)

    def test_a_step_off_the_minute_starts_the_next(self) -> None:
        steps = _steps(1.0)
        late = [replace(s, at=s.at + timedelta(seconds=25)) for s in steps]
        rec = hist.record(late, P)
        assert rec.start == T0 + timedelta(minutes=1)
        assert len(rec) == 59

    def test_a_gap_is_unknown_and_the_air_holds(self) -> None:
        steps = _steps(1.0)
        kept = [s for s in steps if not 600 <= (s.at - T0).seconds < 1200]
        rec = hist.record(kept, P)
        assert len(rec) == 60
        assert math.isnan(rec.upper_f[12]) and math.isnan(rec.lower_f[12])
        assert rec.air_f[12] == 62.0
        assert rec.upper_f[20] == 128.0

    def test_a_flow_under_a_draw_is_none(self) -> None:
        under = P.book.draw_gpm * 0.5
        rec = hist.record(_steps(1.0, draw=(0.0, 1.0, under)), P)
        assert rec.draws == ()

    def test_tank_gallons_are_the_valves_delivery_of_them(self) -> None:
        """A gallon of tank water at 128 °F is more than one delivered
        through the valve, which blends it with the inlet's."""
        p = site_example_params()
        assert p.draw.delivery_slope != 1.0
        tank = hist.record(_steps(1.0, draw=(0.0, 0.5, 2.0), volume="tank"), p)
        delivered = hist.record(_steps(1.0, draw=(0.0, 0.5, 2.0)), p)
        got = sum(g for _, g in tank.draws)
        assert got > sum(g for _, g in delivered.draws) == pytest.approx(60.0)

    def test_steps_say_when_they_start(self) -> None:
        steps = [replace(s, at=None) for s in _steps(0.5)]
        with pytest.raises(ValueError, match="when it starts"):
            hist.record(steps, P)

    def test_steps_are_in_time_order(self) -> None:
        with pytest.raises(ValueError, match="time order"):
            hist.record(list(reversed(_steps(0.5))), P)


def _frame(steps: list[hist.Step]) -> pd.DataFrame:
    index = pd.DatetimeIndex([s.at for s in steps])
    return pd.DataFrame(
        {
            "upper_f": [s.upper_f for s in steps],
            "lower_f": [s.lower_f for s in steps],
            "air_f": [s.ambient_f for s in steps],
            "compressor_on": [s.compressor_on for s in steps],
            "element_on": [s.element_on for s in steps],
            "circulating": [s.circulating for s in steps],
        },
        index=index,
    )


class TestTheReplay:
    def test_it_replays_as_the_fit_does(self) -> None:
        """The steps' record replays as a history frame's does
        (``tank_fit.tank_record``), the draws the same."""
        steps = _steps(26.0, draw=(23.0, 23.25, 2.0), compressor=(24.0, 25.0))
        rec = hist.record(steps, P)
        frame = tf.tank_record(_frame(steps), rec.draws)
        lay = st.layout(P)
        end = rec.instant(len(rec))
        want = tf.replay(lay, P, frame, end)
        got = hist.replay(steps, P)
        assert want is not None and got is not None
        last = steps[-1]
        want = st.mix(st.assimilate(lay, want, last.upper_f, last.lower_f))
        assert got.layers_f == pytest.approx(want.layers_f)

    def test_the_probes_read_as_given(self) -> None:
        steps = _steps(3.0)
        lay = st.layout(P)
        got = hist.replay(steps, P)
        assert got is not None
        assert st.observe(lay, got) == pytest.approx((128.0, 126.0), abs=0.05)
        given = hist.replay(steps, P, probes=(124.0, 110.0))
        assert given is not None
        assert st.observe(lay, given) == pytest.approx((124.0, 110.0), abs=0.05)

    def test_a_draw_leaves_the_bottom_cold(self) -> None:
        """After a draw the probes read alike, the inlet's water under
        the lower one; two probes alone know nothing of it."""
        drawn = hist.replay(_steps(3.0, draw=(2.0, 2.5, 2.0)), P)
        quiet = hist.replay(_steps(3.0), P)
        assert drawn is not None and quiet is not None
        assert drawn.layers_f[0] < quiet.layers_f[0] - 10.0

    def test_no_reading_of_the_probes_is_none(self) -> None:
        steps = [
            replace(s, upper_f=math.nan, lower_f=math.nan) for s in _steps(1.0)
        ]
        assert hist.replay(steps, P) is None
        assert hist.replay([], P) is None

    def test_it_reaches_back_a_replays_span(self) -> None:
        """What came before the span is forgotten: a draw 30 h ago
        leaves what a quiet history does."""
        old = hist.replay(
            _steps(31.0, draw=(1.0, 1.5, 2.0), compressor=(2.0, 3.0)), P
        )
        quiet = hist.replay(_steps(31.0), P)
        assert old is not None and quiet is not None
        assert old.layers_f == pytest.approx(quiet.layers_f)


class TestFromTheChanges:
    def _rows(self) -> tuple[sa.ChangeRows, list[datetime], datetime]:
        steps = _steps(6.0, draw=(4.0, 4.5, 2.0))
        at = T0 + timedelta(hours=6)
        rows = sa.ChangeRows(
            upper_f=[(T0, 128.0)],
            lower_f=[(T0, 126.0), (T0 + timedelta(hours=4), 100.0)],
            compressor_on=[(T0, False)],
            heater_air_f=[(T0, 62.0)],
        )
        heard = [s.at for s in steps if s.at is not None]
        return rows, heard, at

    def test_it_replays_the_draws(self) -> None:
        rows, heard, at = self._rows()
        flow = [
            (T0, 0.0),
            (T0 + timedelta(hours=4), 2.0),
            (T0 + timedelta(hours=4.5), 0.0),
        ]
        got = sa.layers_from_changes(rows, heard, P, at=at, flow=flow)
        quiet = sa.layers_from_changes(rows, heard, P, at=at, flow=[(T0, 0.0)])
        assert got is not None and quiet is not None
        assert len(got) == P.tank.layers
        assert got[0] < quiet[0]

    def test_unheard_now_is_none(self) -> None:
        rows, heard, at = self._rows()
        early = [t for t in heard if t < at - timedelta(hours=1)]
        assert sa.layers_from_changes(rows, early, P, at=at, flow=[]) is None

    def test_the_flow_unknown_now_is_none(self) -> None:
        rows, heard, at = self._rows()
        out = [(at - timedelta(minutes=5), at + timedelta(minutes=5))]
        got = sa.layers_from_changes(
            rows, heard, P, at=at, flow=[(T0, 0.0)], flow_outages=out
        )
        assert got is None
