"""The heat book from a recorded history (``sim.book.book_steps``,
``sim_adapters.book_from_history``).

The book and its gridding are held to their source by the parity
checks run with the port; these hold the anchor's rules and the
adapter's.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("pandas")

from nwp500 import sim_adapters as sa
from nwp500.models import DeviceStatus
from nwp500.sim import site_example_params
from nwp500.sim.book import Step, book_steps, house_gpm
from nwp500.sim.params import BookParams, CirculationParams

T0 = datetime(2026, 10, 5, tzinfo=UTC)
P = BookParams()
LOOP = CirculationParams(
    displaced_gal=6.0, flow_gpm=1.4, loss_btu_per_gal=159.0, meter_share=0.81
)


def step(**kw: Any) -> Step:
    base: dict[str, Any] = {
        "seconds": 10.0,
        "upper_f": 140.0,
        "lower_f": 139.5,
        "flow_gpm": 0.0,
        "compressor_on": False,
        "element_on": False,
        "ambient_f": 65.0,
        "inlet_f": 68.0,
    }
    return Step(**(base | kw))


def recovery_then(after: list[Step]) -> list[Step]:
    """A recovery, then ``after``."""
    heating = [step(compressor_on=True, lower_f=120.0 + i) for i in range(20)]
    return heating + after


class TestTheAnchor:
    def test_a_quiet_full_tank_re_anchors_until_disturbed(self):
        """The anchor is the latest quiet full step after a clean
        recovery: a tank left alone stays anchored now."""
        b = book_steps(recovery_then([step()] * 30), P)
        assert b is not None
        assert b.anchor_age_h == 0.0 and not b.aged(P)

    def test_no_recovery_is_no_anchor(self):
        assert book_steps([step()] * 100, P) is None

    def test_a_draw_after_the_anchor_takes_its_heat(self):
        quiet = book_steps(recovery_then([step()] * 60), P)
        drawn = book_steps(
            recovery_then([step()] * 30 + [step(flow_gpm=2.0)] * 30), P
        )
        assert quiet is not None and drawn is not None
        # 10 gal at 2 gal/min for 5 minutes.
        assert drawn.heat_btu < quiet.heat_btu - 3000

    def test_a_draw_through_the_recoverys_end_anchors_there(self):
        """A short wash spanning the compressor's stop: the full tank
        it stopped at still anchors, the wash booked from its start."""
        heating = [step(compressor_on=True)] * 20
        wash = [step(compressor_on=True, flow_gpm=1.0)] * 3 + [
            step(flow_gpm=1.0)
        ] * 3
        b = book_steps(heating + wash + [step()] * 10, P)
        assert b is not None
        quiet = book_steps(heating + [step()] * 16, P)
        assert quiet is not None and b.heat_btu < quiet.heat_btu

    def test_the_quiet_after_a_draw_is_no_anchor(self):
        steps = (
            recovery_then([step()] * 5)
            + [step(flow_gpm=2.0)] * 30
            + [step()] * 30
        )
        b = book_steps(steps, P)
        assert b is not None
        # Anchored just before the draw, not on the full-looking quiet
        # after it.
        assert b.anchor_age_h == pytest.approx(60 * 10 / 3600)

    def test_past_the_history_none_and_past_the_fresh_age_aged(self):
        p = replace(P, history_h=1.0, max_anchor_age_h=0.5)
        hour = int(3600 / 10)

        def since_a_draw(quiet: int) -> list[Step]:
            return recovery_then(
                [step(), step(flow_gpm=2.0)] + [step()] * quiet
            )

        assert book_steps(since_a_draw(hour + 5), p) is None
        aged = book_steps(since_a_draw(int(hour * 0.75)), p)
        assert aged is not None and aged.aged(p)

    def test_the_inlet_is_the_median_of_the_measured(self):
        """Since the anchor (fixed by a draw): the measured readings'
        median, not the last one."""
        after = [step(), step(flow_gpm=2.0)] + [
            step(inlet_f=60.0 + i % 3, inlet_measured=True) for i in range(31)
        ]
        b = book_steps(recovery_then(after), P)
        assert b is not None
        assert b.inlet_f == 61.0
        assert b.inlet_measured_share == pytest.approx(31 / 33)


class TestTheHouseholdsFlow:
    def test_the_meter_less_circulations_share(self):
        s = step(flow_gpm=1.5, circulating=True, circulation_gpm=1.4)
        assert house_gpm(s, LOOP) == pytest.approx(1.5 - 0.81 * 1.4)
        # A meter circulation does not pass reads it all as draws.
        assert house_gpm(s, replace(LOOP, meter_share=0.0)) == 1.5
        assert house_gpm(step(flow_gpm=0.4), LOOP) == 0.4

    def test_circulating_disturbs_the_anchor(self):
        steps = recovery_then(
            [step(circulating=True, circulation_gpm=1.4)] * 30
        )
        b = book_steps(steps, P, LOOP)
        assert b is not None
        # Anchored at the recovery's end: circulating since, not quiet.
        assert b.anchor_age_h == pytest.approx(29 * 10 / 3600)


@pytest.fixture
def heater(device_status_dict):
    def readings(hours: float, recovery_at: float) -> list[Any]:
        out = []
        t = T0 - timedelta(hours=hours)
        while t <= T0:
            heating = (
                T0 - timedelta(hours=recovery_at)
                <= t
                < T0 - timedelta(hours=recovery_at - 0.5)
            )
            out.append(
                (
                    t,
                    DeviceStatus.model_validate(
                        device_status_dict
                        | {
                            "tankUpperTemperature": 600,
                            "tankLowerTemperature": 598,
                            "compUse": 2 if heating else 1,
                            "heatUpperUse": 1,
                            "heatLowerUse": 1,
                        }
                    ),
                )
            )
            t += timedelta(minutes=1)
        return out

    return readings


def meter(hours: float, every: timedelta = timedelta(seconds=30)) -> list[Any]:
    out = []
    t = T0 - timedelta(hours=hours)
    while t <= T0:
        out.append((t, 0.0))
        t += every
    return out


def with_a_draw(rows: list[Any], hours_ago: float) -> list[Any]:
    """``rows`` with 2 gal/min for five minutes ``hours_ago``."""
    at = T0 - timedelta(hours=hours_ago)
    return sorted(
        [
            (t, 2.0 if at <= t < at + timedelta(minutes=5) else v)
            for t, v in rows
        ]
    )


class TestFromTheHistory:
    def test_it_books_from_the_recovery(self, heater):
        p = site_example_params()
        b = sa.book_from_history(
            heater(20, recovery_at=4),
            p,
            at=T0,
            flow=with_a_draw(meter(20), 2.0),
        )
        assert b is not None
        # Anchored just before the draw two hours ago.
        assert b.anchor_age_h == pytest.approx(2.0, abs=0.01)
        assert not b.aged(p.book_terms())

    def test_past_the_fresh_window_it_reads_the_long_one(self, heater):
        p = site_example_params()
        b = sa.book_from_history(
            heater(72, recovery_at=30),
            p,
            at=T0,
            flow=with_a_draw(meter(72), 25.0),
        )
        assert b is not None and b.aged(p.book_terms())

    def test_a_silent_meter_is_refused(self, heater):
        p = site_example_params()
        gappy = [
            r for r in meter(20) if not T0 - timedelta(hours=8) < r[0] < T0
        ]
        with pytest.raises(ValueError, match="silent"):
            sa.book_from_history(
                heater(20, recovery_at=4), p, at=T0, flow=gappy
            )

    def test_a_missing_meter_reading_is_no_reading(self, heater):
        """A NaN in the meter's flow is a reading not taken: the anchor
        and the booked heat are what they are without it."""
        p = site_example_params()
        flow = with_a_draw(meter(20), 2.0)
        holed = sorted(
            [*flow, (T0 - timedelta(hours=1, seconds=15), float("nan"))]
        )
        clean = sa.book_from_history(
            heater(20, recovery_at=4), p, at=T0, flow=flow
        )
        got = sa.book_from_history(
            heater(20, recovery_at=4), p, at=T0, flow=holed
        )
        assert clean is not None and got is not None
        assert got.heat_btu == pytest.approx(clean.heat_btu)
        assert got.anchor_age_h == clean.anchor_age_h
