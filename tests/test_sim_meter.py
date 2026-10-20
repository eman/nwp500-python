"""A hot-water meter's flow from its volume and rate reports
(``nwp500.sim.meter``)."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

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
    def test_a_steady_draw_reads_its_flow(self) -> None:
        flow = meter.flow_gpm(steady(2.0, 15), [], T0, _at(20 * 60))
        assert _value(flow, 5 * 60) == pytest.approx(2.0)
        assert _value(flow, 14 * 60) == pytest.approx(2.0)
        # Silent once the last report leaves the window.
        assert _value(flow, 18 * 60) == 0.0

    def test_the_sign_is_ignored(self) -> None:
        backwards = meter.flow_gpm(
            steady(2.0, 15, sign=-1), [], T0, _at(20 * 60)
        )
        assert _value(backwards, 5 * 60) == pytest.approx(2.0)

    def test_a_sustained_run_counts_from_its_first_step(self) -> None:
        flow = meter.flow_gpm(steady(2.0, 15), [], T0, _at(20 * 60))
        moving = [t for t, v in flow if v >= meter.DRAW_GPM]
        assert moving[0] == _at(30)
        live = meter.flow_gpm(
            steady(2.0, 15), [], T0, _at(20 * 60), backfill=False
        )
        first_live = next(t for t, v in live if v >= meter.DRAW_GPM)
        assert first_live == _at(30 + 120)

    def test_a_blip_is_not_sustained(self) -> None:
        # 60 s of flow: the net holds above the line for under 120 s.
        flow = meter.flow_gpm(steady(2.0, 1), [], T0, _at(10 * 60))
        assert all(v == 0.0 for _, v in flow)

    def test_the_grid(self) -> None:
        flow = meter.flow_gpm([], [], T0, _at(60))
        assert [t for t, _ in flow] == [_at(s) for s in range(0, 61, 10)]
        assert meter.flow_gpm([], [], _at(60), T0) == []

    def test_the_grid_is_on_whole_steps(self) -> None:
        # Read from any instant, the steps (and so a draw's edges) fall
        # on the same marks.
        flow = meter.flow_gpm([], [], _at(6.4), _at(40))
        assert [t for t, _ in flow] == [_at(s) for s in (10, 20, 30, 40)]
        a = meter.flow_gpm(steady(2.0, 15), [], T0, _at(20 * 60))
        b = meter.flow_gpm(steady(2.0, 15), [], _at(3), _at(20 * 60))
        assert dict(b).items() <= dict(a).items()


class TestTheForwardRate:
    def test_it_holds_for_a_minute(self) -> None:
        flow = meter.flow_gpm([], [(_at(0), 1.5)], T0, _at(120))
        assert _value(flow, 60) == 1.5
        assert _value(flow, 70) == 0.0

    def test_a_rate_at_the_line_is_not_water_moving(self) -> None:
        flow = meter.flow_gpm([], [(_at(0), meter.DRAW_GPM)], T0, _at(30))
        assert all(v == 0.0 for _, v in flow)

    def test_the_net_wins_inside_a_sustained_run(self) -> None:
        flow = meter.flow_gpm(
            steady(2.0, 15), [(_at(4 * 60), 5.0)], T0, _at(20 * 60)
        )
        assert _value(flow, 4 * 60) == pytest.approx(2.0)


class TestSustainRoundsUp:
    def test_a_run_never_counts_before_sustain(self) -> None:
        # One report per step, a 10 s window: 13 steps at the line, a
        # run 120 s long.
        reports = [(_at(10 * (i + 1)), 1.0) for i in range(13)]

        def moving(sustain_s: float) -> bool:
            flow = meter.flow_gpm(
                reports,
                [],
                T0,
                _at(300),
                window=timedelta(seconds=10),
                sustain=timedelta(seconds=sustain_s),
            )
            return any(v > 0 for _, v in flow)

        assert moving(120)
        assert not moving(125)


class TestZones:
    @pytest.mark.parametrize(
        ("zone", "start", "end"),
        [
            # Clocks forward, back, and a fixed half-hour offset.
            ("America/New_York", (2026, 3, 8, 1, 55), (2026, 3, 8, 3, 5)),
            (
                "America/Los_Angeles",
                (2026, 11, 1, 1, 50, 0),
                (2026, 11, 1, 1, 10, 1),
            ),
            ("Asia/Kolkata", (2026, 10, 18, 7, 3), (2026, 10, 18, 8, 3)),
        ],
    )
    def test_local_instants_read_as_utc(self, zone, start, end) -> None:
        from zoneinfo import ZoneInfo

        z = ZoneInfo(zone)
        a = datetime(*start[:5], tzinfo=z)
        b = datetime(*end[:5], tzinfo=z, fold=end[5] if len(end) > 5 else 0)
        reports = [
            (a + timedelta(seconds=30 * (i + 1)), 1.0) for i in range(20)
        ]
        local = meter.flow_gpm(reports, [], a, b)
        utc = meter.flow_gpm(
            [(t.astimezone(UTC), v) for t, v in reports],
            [],
            a.astimezone(UTC),
            b.astimezone(UTC),
        )
        assert local == utc
        elapsed = b.astimezone(UTC) - a.astimezone(UTC)
        assert len(local) == pytest.approx(elapsed / meter.STEP, abs=1)
        steps = [t for t, _ in local]
        assert all(y - x == meter.STEP for x, y in pairwise(steps))
