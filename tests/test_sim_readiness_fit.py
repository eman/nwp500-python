"""The readiness evidence and the heat book's own terms, fitted from a
metered record (``sim.calibration``).

The fits are held to their source by the parity check run with the
port; these hold their rules.
"""

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("pandas")
pytest.importorskip("scipy")

import numpy as np
import pandas as pd

from nwp500.sim import calibration as cal
from nwp500.sim.book import Step
from nwp500.sim.params import BookParams

T0 = datetime(2026, 3, 1, tzinfo=UTC)
GRID = timedelta(seconds=cal.DRAW_GRID_S)


def frame(n: int, **cols) -> pd.DataFrame:
    """``n`` draw-grid steps of a quiet full tank, ``cols`` laid over."""
    base = {
        "flow_gpm": np.zeros(n),
        "circulating": np.zeros(n, dtype=bool),
        "upper_f": np.full(n, 135.0),
        "lower_f": np.full(n, 130.0),
        "compressor_on": np.zeros(n, dtype=bool),
        "element_on": np.zeros(n, dtype=bool),
    }
    base.update(cols)
    return pd.DataFrame(
        base, index=pd.DatetimeIndex([T0 + GRID * i for i in range(n)])
    )


def a_draw(n=400, at=100, steps=60, gpm=2.0, **kw) -> pd.DataFrame:
    flow = np.zeros(n)
    flow[at : at + steps] = gpm
    return frame(n, flow_gpm=flow, **kw)


class TestCleanDraws:
    def test_a_settled_draw(self):
        (d,) = cal.clean_draws(a_draw())
        assert d.start == T0 + GRID * 100
        assert d.gal == pytest.approx(10.0)
        assert (d.u0, d.l0, d.gpm, d.hp) == (135.0, 130.0, 2.0, False)

    def test_too_small_or_unsettled_or_circulating_is_not_clean(self):
        assert cal.clean_draws(a_draw(steps=20)) == []  # under 5 gal
        circ = np.zeros(400, dtype=bool)
        circ[120] = True
        assert cal.clean_draws(a_draw(circulating=circ)) == []
        flow = np.zeros(400)
        flow[90] = 1.0  # a draw in the settle before it: one draw
        flow[100:160] = 2.0
        (d,) = cal.clean_draws(frame(400, flow_gpm=flow))
        assert d.start == T0 + GRID * 90
        el = np.zeros(400, dtype=bool)
        el[80] = True
        assert cal.clean_draws(a_draw(element_on=el)) == []

    def test_a_crossing_is_credited_back_by_the_probes_lag(self):
        up = np.full(400, 135.0)
        up[150:] = 100.0
        (d,) = cal.clean_draws(a_draw(upper_f=up))
        got, crossed = cal.crossing(d, 105.0)
        lag = cal.DRAW_TAIL_S // cal.DRAW_GRID_S
        assert crossed
        assert got == pytest.approx(d.vd[50 - lag])
        assert cal.demonstrated(d) == got


class TestTheEvidence:
    def test_the_frontier_drops_what_another_beats(self):
        points = [
            (130.0, 120.0, 10.0),
            (135.0, 125.0, 9.0),
            (128.0, 110.0, 12.0),
        ]
        ev = cal.frontier(points)
        assert (135.0, 125.0, 9.0) not in ev
        assert cal.capacity(136.0, 126.0, ev) == 12.0
        assert cal.capacity(120.0, 100.0, ev) == 0.0

    def test_the_cap_after_a_cold_lower_zone(self):
        up = np.full(400, 135.0)
        up[140:] = 109.0
        cold = cal.clean_draws(a_draw(upper_f=up, lower_f=np.full(400, 95.0)))
        cap = cal.cold_lower_cap(cold, 100.0)
        assert cap is not None and cap == np.floor(cap * 2) / 2
        assert cal.cold_lower_cap(cold, 90.0) is None


class TestTheBooksTerms:
    def test_re_anchors_need_an_hour_between(self):
        p = BookParams()

        def s(**kw) -> Step:
            d = {
                "seconds": 10.0,
                "upper_f": 140.0,
                "lower_f": 139.5,
                "flow_gpm": 0.0,
                "compressor_on": False,
                "element_on": False,
                "ambient_f": 65.0,
                "inlet_f": 68.0,
            }
            return Step(**(d | kw))

        hour = 360
        recovery = [s(compressor_on=True, lower_f=120.0)] * 10
        steps = (
            recovery
            + [s()] * 5
            + [s(flow_gpm=2.0)] * 30
            + [s(lower_f=110.0)] * (2 * hour)
            + recovery
            + [s()] * 5
        )
        book = cal.RecordedBook(steps, p, start=T0)
        (pair,) = book.reanchors()
        assert pair[1] - pair[0] > hour
        (err,) = book.errors(p, 0.0, [pair])
        assert np.isfinite(err)
        fresh, aged = cal.book_error_btu(book, p, 0.0)
        # One pair two hours apart: the fresh band is its error, rounded
        # up to 100 BTU; no pair is 18-24 h old.
        assert fresh == np.ceil(abs(err) / 100) * 100
        assert aged is None
