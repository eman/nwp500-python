"""A hot-water meter's flow from its volume and rate reports
(``nwp500.sim.meter``)."""

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("numpy")

from nwp500.sim import meter

T0 = datetime(2026, 10, 18, 7, tzinfo=UTC)


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def steady(gpm: float, minutes: float, *, every_s: float = 30.0, sign=1):
    """Volume reports for a steady draw, each the volume since the last."""
    n = int(minutes * 60 / every_s)
    gal = gpm * every_s / 60.0
    return [(_at(every_s * (i + 1)), sign * gal) for i in range(n)]


def _value(flow, seconds: float) -> float:
    return dict(flow)[_at(seconds)]


class TestTheNetVolume:
    def test_a_steady_draw_reads_its_flow(self):
        flow = meter.flow_gpm(steady(2.0, 15), [], T0, _at(20 * 60))
        assert _value(flow, 5 * 60) == pytest.approx(2.0)
        assert _value(flow, 14 * 60) == pytest.approx(2.0)
        # Silent once the last report leaves the window.
        assert _value(flow, 18 * 60) == 0.0

    def test_the_sign_is_ignored(self):
        backwards = meter.flow_gpm(
            steady(2.0, 15, sign=-1), [], T0, _at(20 * 60)
        )
        assert _value(backwards, 5 * 60) == pytest.approx(2.0)

    def test_a_sustained_run_counts_from_its_first_step(self):
        flow = meter.flow_gpm(steady(2.0, 15), [], T0, _at(20 * 60))
        moving = [t for t, v in flow if v >= meter.DRAW_GPM]
        assert moving[0] == _at(30)
        live = meter.flow_gpm(
            steady(2.0, 15), [], T0, _at(20 * 60), backfill=False
        )
        first_live = next(t for t, v in live if v >= meter.DRAW_GPM)
        assert first_live == _at(30 + 120)

    def test_a_blip_is_not_sustained(self):
        # 60 s of flow: the net holds above the line for under 120 s.
        flow = meter.flow_gpm(steady(2.0, 1), [], T0, _at(10 * 60))
        assert all(v == 0.0 for _, v in flow)

    def test_the_grid(self):
        flow = meter.flow_gpm([], [], T0, _at(60))
        assert [t for t, _ in flow] == [_at(s) for s in range(0, 61, 10)]
        assert meter.flow_gpm([], [], _at(60), T0) == []


class TestTheForwardRate:
    def test_it_holds_for_a_minute(self):
        flow = meter.flow_gpm([], [(_at(0), 1.5)], T0, _at(120))
        assert _value(flow, 60) == 1.5
        assert _value(flow, 70) == 0.0

    def test_a_rate_at_the_line_is_not_water_moving(self):
        flow = meter.flow_gpm([], [(_at(0), meter.DRAW_GPM)], T0, _at(30))
        assert all(v == 0.0 for _, v in flow)

    def test_the_net_wins_inside_a_sustained_run(self):
        flow = meter.flow_gpm(
            steady(2.0, 15), [(_at(4 * 60), 5.0)], T0, _at(20 * 60)
        )
        assert _value(flow, 4 * 60) == pytest.approx(2.0)
