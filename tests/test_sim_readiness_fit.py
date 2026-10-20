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
    def test_a_settled_draw(self) -> None:
        (d,) = cal.clean_draws(a_draw())
        assert d.start == T0 + GRID * 100
        assert d.gal == pytest.approx(10.0)
        assert (d.u0, d.l0, d.gpm, d.hp) == (135.0, 130.0, 2.0, False)

    def test_too_small_or_unsettled_or_circulating_is_not_clean(self) -> None:
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

    def test_a_crossing_is_credited_back_by_the_probes_lag(self) -> None:
        up = np.full(400, 135.0)
        up[150:] = 100.0
        (d,) = cal.clean_draws(a_draw(upper_f=up))
        got, crossed = cal.crossing(d, 105.0)
        lag = cal.DRAW_TAIL_S // cal.DRAW_GRID_S
        assert crossed
        assert got == pytest.approx(d.vd[50 - lag])
        assert cal.demonstrated(d) == got


class TestTheEvidence:
    def test_the_frontier_drops_what_another_beats(self) -> None:
        points = [
            (130.0, 120.0, 10.0),
            (135.0, 125.0, 9.0),
            (128.0, 110.0, 12.0),
        ]
        ev = cal.frontier(points)
        assert (135.0, 125.0, 9.0) not in ev
        assert cal.capacity(136.0, 126.0, ev) == 12.0
        assert cal.capacity(120.0, 100.0, ev) == 0.0

    def test_the_cap_after_a_cold_lower_zone(self) -> None:
        up = np.full(400, 135.0)
        up[140:] = 109.0
        cold = cal.clean_draws(a_draw(upper_f=up, lower_f=np.full(400, 95.0)))
        cap = cal.cold_lower_cap(cold, 100.0)
        assert cap is not None and cap == np.floor(cap * 2) / 2
        assert cal.cold_lower_cap(cold, 90.0) is None


class TestTheBooksTerms:
    def test_re_anchors_need_an_hour_between(self) -> None:
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


class TestTheDrawResponseFits:
    """Each fit, given probes its own model made, finds the values that
    made them; ``long_draws`` joins short gaps."""

    def _frame(self, n_draws: int = 8) -> pd.DataFrame:
        rows = []
        for k in range(n_draws):
            ev = T0 + timedelta(days=k)
            cold = 0.0
            for i in range(60):
                cold += 0.8
                rows.append(
                    (ev, f"{ev:%Y-%m-%d}", 130.0 - 0.02 * i, 120.0, cold, 70.0)
                )
        f = pd.DataFrame(
            rows, columns=["ev", "day", "up", "lo", "cold_gal", "cold_f"]
        )
        f["held"] = [e >= T0 + timedelta(days=6) for e in f.ev]
        return f

    def test_the_front_finds_its_place_and_width(self) -> None:
        f = self._frame()
        f["pl"] = cal._front_run(f, 24.0, 32.0)
        fit = cal.fit_front(f, n_boot=20)
        assert (fit.lower_probe_gal, fit.front_width_gal) == (24.0, 32)
        assert fit.mae_train == 0.0

    def test_the_front_keeps_a_rise_and_floors_at_the_cold(self) -> None:
        f = self._frame(1)
        f.loc[f.index[30:], "lo"] = 125.0  # heat: a rise
        out = cal._front_run(f, 24.0, 32.0)
        assert out[30] > out[29]
        assert (out >= 70.0).all()

    def test_the_mixing_finds_its_pair(self) -> None:
        rows = [
            (ev, f"{ev:%Y-%m-%d}", 1.5 * i, 135.0, 30.0 - 1.5 * i)
            for ev in (T0 + timedelta(days=k) for k in range(8))
            for i in range(20)
        ]
        f = pd.DataFrame(rows, columns=["ev", "day", "gal", "up", "left_z"])
        f["dg"] = f.groupby("ev").gal.diff().fillna(0.0)
        f["held"] = [e >= T0 + timedelta(days=6) for e in f.ev]
        f["up"] = cal._mix_run(f, 1.25, 14, line_f=105.0, fall=2.0)
        fit = cal.fit_zone_mix(f, n_boot=20)
        assert (fit.zone_mix_f_per_gal, fit.zone_mix_gal) == (1.25, 14.0)

    def test_the_settling_finds_its_time_constant(self) -> None:
        tails = []
        for k in range(10):
            hrs = np.arange(0, 6, 1 / 12)
            t = {
                "ev": T0 + timedelta(days=k),
                "day": f"{T0 + timedelta(days=k):%Y-%m-%d}",
                "held": k >= 8,
                "hrs": hrs,
                "drift": 0.01 * hrs,
                "front": 110.0,
                "phys": 100.0,
            }
            t["pl"] = cal._settle_model(t, 120)
            tails.append(t)
        fit = cal.fit_front_settle(tails, n_boot=20)
        assert fit.front_settle_min == 120.0
        assert fit.mae_train == 0.0

    def test_long_draws_join_short_gaps(self) -> None:
        t = [T0 + timedelta(seconds=10 * i) for i in range(200)]
        hgal = np.zeros(200)
        hgal[10:40] = 0.3  # 9 gal
        hgal[44:60] = 0.3  # 40 s later: the same draw
        hgal[100:110] = 0.3  # 3 gal: too small
        walk = pd.DataFrame({"t": t, "hgal": hgal})
        (draw,) = cal.long_draws(walk)
        assert draw[0] == t[10] and draw[1] == t[59]
        assert draw[2] == pytest.approx(13.8)


class TestCirculationFits:
    def _runs(self, displaced: float, n: int = 30) -> list:
        rng = np.random.default_rng(4)
        out = []
        for k in range(n):
            minutes = float(rng.uniform(1, 12))
            flow = float(rng.uniform(1.0, 2.2))
            upper, air = 130.0, 65.0
            start = T0 + timedelta(hours=6 * k)
            out.append(
                cal.MeasuredRun(
                    start=start,
                    end=start + timedelta(minutes=minutes),
                    minutes=minutes,
                    btu=cal.run_heat_btu(minutes, upper, air, displaced, flow),
                    flow_gpm=flow,
                    upper_f=upper,
                    air_f=air,
                )
            )
        return out

    def test_the_displaced_volume_is_found(self) -> None:
        assert cal.fit_displaced_gal(self._runs(6.0)) == pytest.approx(
            6.0, abs=0.05
        )

    def test_too_few_runs_or_a_pinned_fit_is_none(self) -> None:
        assert cal.fit_displaced_gal(self._runs(6.0, n=10)) is None
        # Every run saturated far past the bounds: unconstrained.
        assert cal.fit_displaced_gal(self._runs(40.0)) is None

    def test_the_recent_flow_and_the_lookup(self) -> None:
        runs = self._runs(6.0)
        until = runs[-1].start
        flows = sorted(
            r.flow_gpm for r in runs if until - timedelta(days=14) <= r.start
        )
        assert cal.recent_flow_gpm(runs, until) == pytest.approx(
            float(np.median(flows))
        )
        at = runs[3].start + timedelta(minutes=20)
        assert cal.flow_lookup(runs)(at) == runs[3].flow_gpm
        assert cal.flow_lookup(runs)(at + timedelta(days=30)) is None

    def test_a_run_is_measured_from_its_samples(self) -> None:
        a = T0
        running = [a + timedelta(seconds=30 * i) for i in range(21)]
        run = cal.measure_runs(
            running,
            flow=[(t, 2.0) for t in running],
            return_f=[(t, 115.0) for t in running],
            upper_f=[(a - timedelta(minutes=1), 130.0)],
            air_f=[(a + timedelta(minutes=2), 66.0)],
        )
        (r,) = run
        assert r.minutes == 10.0
        assert r.btu == pytest.approx(2.0 * 60 * 8.34 * 15.0 * 10 / 60)
        assert (r.flow_gpm, r.air_f) == (2.0, 66.0)
        assert r.upper_f is None  # no upper reading inside the run
        assert (
            cal.measure_runs(
                running,
                flow=[],
                return_f=[],
                upper_f=[],
                compressor=[(a, a + timedelta(minutes=1))],
            )
            == []
        )
