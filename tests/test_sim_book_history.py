"""The heat book from a recorded history (``sim.book.book_steps``,
``sim_adapters.book_from_history``).

The book and its gridding are held to their source by the parity
checks run with the port; these hold the anchor's rules and the
adapter's.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("pandas")

from nwp500 import sim_adapters as sa
from nwp500.enums import HeatSource
from nwp500.models import DeviceStatus
from nwp500.sim import site_example_params
from nwp500.sim.book import Step, book_steps, house_gpm
from nwp500.sim.params import BookParams, CirculationParams
from nwp500.unit_system import reset_unit_system, set_unit_system

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
    def test_a_quiet_full_tank_re_anchors_until_disturbed(self) -> None:
        """The anchor is the latest quiet full step after a clean
        recovery: a tank left alone stays anchored now."""
        b = book_steps(recovery_then([step()] * 30), P)
        assert b is not None
        assert b.anchor_age_h == 0.0 and not b.aged(P)

    def test_no_recovery_is_no_anchor(self) -> None:
        assert book_steps([step()] * 100, P) is None

    def test_a_draw_after_the_anchor_takes_its_heat(self) -> None:
        quiet = book_steps(recovery_then([step()] * 60), P)
        drawn = book_steps(
            recovery_then([step()] * 30 + [step(flow_gpm=2.0)] * 30), P
        )
        assert quiet is not None and drawn is not None
        # 10 gal at 2 gal/min for 5 minutes.
        assert drawn.heat_btu < quiet.heat_btu - 3000

    def test_a_draw_through_the_recoverys_end_anchors_there(self) -> None:
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

    def test_the_quiet_after_a_draw_is_no_anchor(self) -> None:
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

    def test_past_the_history_none_and_past_the_fresh_age_aged(self) -> None:
        p = replace(P, history_h=1.0, max_anchor_age_h=0.5)
        hour = int(3600 / 10)

        def since_a_draw(quiet: int) -> list[Step]:
            return recovery_then(
                [step(), step(flow_gpm=2.0)] + [step()] * quiet
            )

        assert book_steps(since_a_draw(hour + 5), p) is None
        aged = book_steps(since_a_draw(int(hour * 0.75)), p)
        assert aged is not None and aged.aged(p)

    def test_the_inlet_is_the_median_of_the_measured(self) -> None:
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
    def test_the_meter_less_circulations_share(self) -> None:
        s = step(flow_gpm=1.5, circulating=True, circulation_gpm=1.4)
        assert house_gpm(s, LOOP) == pytest.approx(1.5 - 0.81 * 1.4)
        # A meter circulation does not pass reads it all as draws.
        assert house_gpm(s, replace(LOOP, meter_share=0.0)) == 1.5
        assert house_gpm(step(flow_gpm=0.4), LOOP) == 0.4

    def test_circulating_disturbs_the_anchor(self) -> None:
        steps = recovery_then(
            [step(circulating=True, circulation_gpm=1.4)] * 30
        )
        b = book_steps(steps, P, LOOP)
        assert b is not None
        # Anchored at the recovery's end: circulating since, not quiet.
        assert b.anchor_age_h == pytest.approx(29 * 10 / 3600)


@pytest.fixture
def heater(
    device_status_dict: dict[str, Any],
) -> Callable[..., list[Any]]:
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
    def test_it_books_from_the_recovery(
        self, heater: Callable[..., list[Any]]
    ) -> None:
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

    def test_past_the_fresh_window_it_reads_the_long_one(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        b = sa.book_from_history(
            heater(72, recovery_at=30),
            p,
            at=T0,
            flow=with_a_draw(meter(72), 25.0),
        )
        assert b is not None and b.aged(p.book_terms())

    def test_a_silent_meter_is_refused(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        gappy = [
            r for r in meter(20) if not T0 - timedelta(hours=8) < r[0] < T0
        ]
        with pytest.raises(ValueError, match="silent"):
            sa.book_from_history(
                heater(20, recovery_at=4), p, at=T0, flow=gappy
            )

    def test_a_silence_of_missing_readings_is_refused(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        """NaNs reported through a gap are no readings: the meter was
        silent over it."""
        p = site_example_params()
        holed = [
            (t, float("nan")) if T0 - timedelta(hours=8) < t < T0 else (t, v)
            for t, v in meter(20)
        ]
        readings = heater(20, recovery_at=4)
        with pytest.raises(ValueError, match="silent"):
            sa.book_from_history(readings, p, at=T0, flow=holed)

    def test_a_missing_meter_reading_is_no_reading(
        self, heater: Callable[..., list[Any]]
    ) -> None:
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


def as_changes(readings: list[Any]) -> tuple[sa.ChangeRows, list[datetime]]:
    """``readings`` (statuses) as their values' changes and the instants
    heard from, as a recorder of entity changes keeps them."""
    rec = sa.record(readings)
    rows = sa.ChangeRows(
        upper_f=rec.upper_f,
        lower_f=rec.lower_f,
        compressor_on=rec.compressor,
        upper_element_on=rec.upper_element,
        lower_element_on=rec.lower_element,
        heater_air_f=tuple((t, s.ambient_temperature) for t, s in readings),
    )
    return rows, [t for t, _ in readings]


def unheard(observed: list[datetime], a: float, b: float) -> list[datetime]:
    """``observed`` without the instants from ``a`` to ``b`` hours ago."""
    return [
        t
        for t in observed
        if not T0 - timedelta(hours=a) < t < T0 - timedelta(hours=b)
    ]


class TestFromTheChanges:
    @pytest.mark.parametrize(
        ("hours", "recovery_at", "draw_at"), [(20, 4, 2.0), (72, 30, 25.0)]
    )
    def test_it_books_as_the_statuses_do(
        self,
        heater: Callable[..., list[Any]],
        hours: int,
        recovery_at: float,
        draw_at: float,
    ) -> None:
        p = site_example_params()
        readings = heater(hours, recovery_at=recovery_at)
        flow = with_a_draw(meter(hours), draw_at)
        rows, observed = as_changes(readings)
        want = sa.book_from_history(readings, p, at=T0, flow=flow)
        got = sa.book_from_changes(rows, observed, p, at=T0, flow=flow)
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)
        assert got.anchor_age_h == pytest.approx(want.anchor_age_h)

    def test_its_inputs_are_the_simulators_units(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        """gal/min and °F whatever the preferred units: a metric
        preference books the same from the same inputs."""
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        flow = with_a_draw(meter(20), 2.0)
        air = [(T0 - timedelta(hours=20), 60.0)]
        want = sa.book_from_changes(
            rows, observed, p, at=T0, flow=flow, air=air
        )
        set_unit_system("metric")
        try:
            got = sa.book_from_changes(
                rows, observed, p, at=T0, flow=flow, air=air
            )
        finally:
            reset_unit_system()
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)

    def test_the_heat_source_stands_in_for_the_compressor(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        readings = heater(20, recovery_at=4)
        flow = with_a_draw(meter(20), 2.0)
        rows, observed = as_changes(readings)
        source = tuple(
            (t, int(HeatSource.HEATPUMP if on else HeatSource.UNKNOWN))
            for t, on in rows.compressor_on
        )
        by_source = replace(rows, compressor_on=(), heat_source=source)
        want = sa.book_from_changes(rows, observed, p, at=T0, flow=flow)
        got = sa.book_from_changes(by_source, observed, p, at=T0, flow=flow)
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)
        assert got.anchor_age_h == pytest.approx(want.anchor_age_h)

    def test_an_anchor_before_a_silence_does_not_count(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        """Unheard from 3 h to 2.5 h ago, after the only recovery: the
        heat that left meanwhile is unknown, so there is no book."""
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        flow = with_a_draw(meter(20), 2.0)
        assert (
            sa.book_from_changes(
                rows, unheard(observed, 3, 2.5), p, at=T0, flow=flow
            )
            is None
        )

    def test_a_silence_before_the_anchor_changes_nothing(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        flow = with_a_draw(meter(20), 2.0)
        want = sa.book_from_changes(rows, observed, p, at=T0, flow=flow)
        got = sa.book_from_changes(
            rows, unheard(observed, 10, 9), p, at=T0, flow=flow
        )
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)

    def test_an_outage_is_a_silence(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        flow = with_a_draw(meter(20), 2.0)
        out = replace(
            rows,
            outages=((T0 - timedelta(hours=3), T0 - timedelta(hours=2.5)),),
        )
        assert sa.book_from_changes(out, observed, p, at=T0, flow=flow) is None

    def test_a_heater_not_heard_now_has_no_book(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        flow = with_a_draw(meter(20), 2.0)
        assert (
            sa.book_from_changes(
                rows, unheard(observed, 1, -1), p, at=T0, flow=flow
            )
            is None
        )
        down = replace(rows, outages=((T0 - timedelta(minutes=30), T0),))
        assert sa.book_from_changes(down, observed, p, at=T0, flow=flow) is None
        # Unavailable from the instant booked: unknown then too.
        now_down = replace(rows, outages=((T0, T0 + timedelta(hours=1)),))
        assert (
            sa.book_from_changes(now_down, observed, p, at=T0, flow=flow)
            is None
        )
        assert sa.book_from_changes(rows, [], p, at=T0, flow=flow) is None

    def test_a_flow_holds_until_its_next_change(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        """A history of changes writes a row only when the flow changes:
        a five-minute draw is two rows, and hours at 0 none."""
        p = site_example_params()
        readings = heater(20, recovery_at=4)
        rows, observed = as_changes(readings)
        sampled = with_a_draw(meter(20), 2.0)
        draw = T0 - timedelta(hours=2)
        changes = [
            (T0 - timedelta(hours=20), 0.0),
            (draw, 2.0),
            (draw + timedelta(minutes=5), 0.0),
        ]
        want = sa.book_from_changes(rows, observed, p, at=T0, flow=sampled)
        got = sa.book_from_changes(rows, observed, p, at=T0, flow=changes)
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)

    def test_the_book_starts_at_the_flows_first_reading(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        """Before the flow's first reading its draws are unknown: the
        book anchors after it, not nowhere."""
        p = site_example_params()
        late = [(T0 - timedelta(hours=1), 0.0)]
        # A recovery 4 h ago is before it: no anchor.
        rows, observed = as_changes(heater(20, recovery_at=4))
        assert sa.book_from_changes(rows, observed, p, at=T0, flow=late) is None
        # One 45 minutes ago is after it.
        rows, observed = as_changes(heater(20, recovery_at=0.75))
        got = sa.book_from_changes(rows, observed, p, at=T0, flow=late)
        assert got is not None
        assert got.anchor_age_h <= 1.0
        with pytest.raises(ValueError, match="no flow reading"):
            sa.book_from_changes(rows, observed, p, at=T0, flow=[])

    def test_a_flow_outage_is_as_the_heater_unheard(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        """No anchor before the flow was unknown counts: the recovery 4 h
        ago is before a half-hour outage 3 h ago, so there is no book."""
        p = site_example_params()
        readings = heater(20, recovery_at=4)
        rows, observed = as_changes(readings)
        flow = [(T0 - timedelta(hours=20), 0.0), (T0 - timedelta(hours=3), 0.0)]
        out = (T0 - timedelta(hours=3, minutes=30), T0 - timedelta(hours=3))
        assert sa.book_from_changes(rows, observed, p, at=T0, flow=flow)
        assert (
            sa.book_from_changes(
                rows, observed, p, at=T0, flow=flow, flow_outages=[out]
            )
            is None
        )

    def test_an_inlet_holds_but_not_through_its_outage(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        flow = [(T0 - timedelta(hours=20), 0.0)]
        inlet = [(T0 - timedelta(hours=10), 55.0)]
        held = sa.book_from_changes(
            rows, observed, p, at=T0, flow=flow, inlet=inlet
        )
        assert held is not None and held.inlet_measured_share == 1.0
        gap = (T0 - timedelta(hours=2), T0)
        cut = sa.book_from_changes(
            rows,
            observed,
            p,
            at=T0,
            flow=flow,
            inlet=inlet,
            inlet_outages=[gap],
        )
        assert cut is not None and cut.inlet_measured_share < 1.0


def ago(h: float = 0, m: float = 0, s: float = 0) -> datetime:
    return T0 - timedelta(hours=h, minutes=m, seconds=s)


class TestARestartGap:
    """A short span the heater or the flow was unknown, as a Home
    Assistant restart leaves, is walked across (``BRIDGE_MAX``). The
    history: a recovery 4 h to 3.5 h ago, a 2 gal/min draw 2 h ago for
    five minutes."""

    P = site_example_params()

    def book(
        self, rows: sa.ChangeRows, observed: list[datetime], **kw: Any
    ) -> Any:
        flow = kw.pop("flow", None) or with_a_draw(meter(20), 2.0)
        return sa.book_from_changes(
            rows, observed, self.P, at=T0, flow=flow, **kw
        )

    @pytest.fixture
    def record(
        self, heater: Callable[..., list[Any]]
    ) -> tuple[sa.ChangeRows, list[datetime]]:
        return as_changes(heater(20, recovery_at=4))

    def test_a_quiet_gap_books_as_none_did(self, record: Any) -> None:
        rows, observed = record
        gap = (ago(1, 3), ago(1))
        want = self.book(rows, observed)
        got = self.book(replace(rows, outages=(gap,)), observed)
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)
        assert got.bridged == (gap,)
        assert want.bridged == ()

    def test_a_silence_is_walked_across_too(self, record: Any) -> None:
        rows, observed = record
        want = self.book(rows, observed)
        got = self.book(rows, unheard(observed, 1.1, 1.0))
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)
        assert len(got.bridged) == 1

    def test_the_flow_unknown_alone(self, record: Any) -> None:
        rows, observed = record
        want = self.book(rows, observed)
        got = self.book(rows, observed, flow_outages=[(ago(1, 3), ago(1))])
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)

    def test_a_compressor_running_at_both_edges(self, record: Any) -> None:
        rows, observed = record
        want = self.book(rows, observed)
        got = self.book(
            replace(rows, outages=((ago(3, 50), ago(3, 47)),)), observed
        )
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)
        assert got.anchor_age_h == pytest.approx(want.anchor_age_h)

    def test_an_element_on_at_both_edges(self, record: Any) -> None:
        rows, observed = record
        element = replace(
            rows,
            upper_element_on=(
                (ago(20), False),
                (ago(1, 10), True),
                (ago(0, 50), False),
            ),
        )
        want = self.book(element, observed)
        got = self.book(
            replace(element, outages=((ago(1, 3), ago(1)),)), observed
        )
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)
        # Off by the far edge: the heating across it is unknown.
        stopped = replace(
            element,
            upper_element_on=(
                (ago(20), False),
                (ago(1, 10), True),
                (ago(1, 1), False),
            ),
            outages=((ago(1, 3), ago(1)),),
        )
        assert self.book(stopped, observed) is None

    def test_heating_that_changes_across_it_breaks(self, record: Any) -> None:
        """The recovery ends inside the gap: on at one edge, off at the
        other."""
        rows, observed = record
        out = replace(rows, outages=((ago(3, 32), ago(3, 28)),))
        assert self.book(out, observed) is None

    @pytest.mark.parametrize(
        "gap", [(ago(2, 1), ago(1, 58)), (ago(1, 57), ago(1, 54))]
    )
    def test_a_draw_at_an_edge_breaks(
        self, record: Any, gap: tuple[datetime, datetime]
    ) -> None:
        rows, observed = record
        assert self.book(replace(rows, outages=(gap,)), observed) is None

    def test_the_bound(self, record: Any) -> None:
        rows, observed = record
        at_bound = (ago(1) - sa.BRIDGE_MAX, ago(1))
        got = self.book(replace(rows, outages=(at_bound,)), observed)
        assert got is not None and got.bridged == (at_bound,)
        past = (at_bound[0] - timedelta(seconds=10), ago(1))
        assert self.book(replace(rows, outages=(past,)), observed) is None
        # A wider bound of the caller's own carries it.
        assert (
            self.book(
                replace(rows, outages=(past,)),
                observed,
                bridge_max=timedelta(minutes=20),
            )
            is not None
        )

    def test_each_flap_is_its_own_gap(self, record: Any) -> None:
        rows, observed = record
        flaps = tuple((ago(m=58 - 5 * k), ago(m=57 - 5 * k)) for k in range(12))
        want = self.book(rows, observed)
        got = self.book(replace(rows, outages=flaps), observed)
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)
        assert got.bridged == flaps

    def test_overlapping_unknowns_are_one_gap(self, record: Any) -> None:
        """The heater back at 1 h ago, the flow two minutes later: one
        gap, from the first going to the last coming back."""
        rows, observed = record
        got = self.book(
            replace(rows, outages=((ago(1, 3), ago(1)),)),
            observed,
            flow_outages=[(ago(1, 2), ago(0, 58))],
        )
        assert got is not None and got.bridged == ((ago(1, 3), ago(0, 58)),)

    def test_a_gap_between_grid_points_anchors_nothing(
        self, record: Any
    ) -> None:
        """Four seconds unknown between two of the book's 10 s steps: the
        step it falls in is not heard, so the quiet full tank after it
        does not anchor and the gap stays named."""
        rows, observed = record
        quiet = [(ago(20), 0.0)]
        gap = (ago(1, 0, 15), ago(1, 0, 11))
        got = self.book(replace(rows, outages=(gap,)), observed, flow=quiet)
        assert got is not None and got.bridged == (gap,)
        assert got.anchor_age_h >= 1.0

    def test_a_gap_before_the_anchor_is_not_named(self, record: Any) -> None:
        rows, observed = record
        got = self.book(
            replace(rows, outages=((ago(10, 3), ago(10)),)), observed
        )
        assert got is not None and got.bridged == ()

    def test_a_draw_inside_it_is_not_booked(self, record: Any) -> None:
        """The documented cost: 1.5 gal drawn while the flow was unknown
        is not booked, and the book over-reads by it until the next
        anchor."""
        rows, observed = record
        quiet = [(ago(20), 0.0), (ago(2), 2.0), (ago(1, 55), 0.0)]
        drawn = [*quiet, (ago(1, 2), 1.5), (ago(1, 1), 0.0)]
        truth = self.book(rows, observed, flow=drawn)
        bridged = self.book(
            rows, observed, flow=quiet, flow_outages=[(ago(1, 3), ago(1))]
        )
        unseen = self.book(rows, observed, flow=quiet)
        assert truth is not None and bridged is not None and unseen is not None
        assert bridged.heat_btu == pytest.approx(unseen.heat_btu)
        assert bridged.heat_btu > truth.heat_btu


class TestNoAnchorAcrossAGap:
    def test_the_book_carries_from_the_anchor_before_it(self) -> None:
        """A recovery that ends inside a gap anchors nothing there, nor
        do the quiet steps after it: the book carries from the anchor
        before the gap."""
        after = (
            [step()] * 10
            + [step(compressor_on=True, heard=False)] * 5
            + [step(heard=False)] * 3
            + [step()] * 10
        )
        b = book_steps(recovery_then(after), P)
        assert b is not None
        assert b.anchor_age_h == pytest.approx(18 * 10 / 3600)
        heard = [replace(s, heard=True) for s in after]
        whole = book_steps(recovery_then(heard), P)
        assert whole is not None and whole.anchor_age_h == 0.0

    def test_a_recovery_ending_in_its_last_step_anchors_nothing(
        self,
    ) -> None:
        """Heating in the gap's last step and idle in the first heard
        one: the recovery's end was not seen, so the quiet steps after
        it do not anchor."""
        after = (
            [step()] * 10
            + [step(heard=False)] * 2
            + [step(compressor_on=True, heard=False)]
            + [step()] * 10
        )
        b = book_steps(recovery_then(after), P)
        assert b is not None
        assert b.anchor_age_h == pytest.approx(13 * 10 / 3600)

    def test_a_recovery_after_it_anchors(self) -> None:
        after = (
            [step(heard=False)] * 3
            + [step(compressor_on=True)] * 5
            + [step()] * 4
        )
        b = book_steps(recovery_then(after), P)
        assert b is not None and b.anchor_age_h == 0.0


class TestTheSilences:
    def test_spans_longer_than_the_gap(self) -> None:
        at = [T0 + timedelta(minutes=m) for m in (0, 1, 2, 3, 20, 21, 22)]
        assert sa.max_gap(at) == sa.MIN_GAP
        assert sa.silences(at) == [(at[3], at[4])]
        assert sa.silences(at, timedelta(hours=1)) == []


def _read(rows: sa.ChangeRows, start: datetime, end: datetime) -> sa.ChangeRows:
    """``rows`` as a read from ``start`` to ``end`` gives them: the value
    in force at ``start`` stamped at it, then the changes up to ``end``."""
    from dataclasses import fields

    out: dict[str, Any] = {}
    for f in fields(rows):
        if f.name == "outages":
            continue
        series = list(getattr(rows, f.name))
        before = [v for t, v in series if t < start]
        within = [(t, v) for t, v in series if start <= t <= end]
        out[f.name] = ([(start, before[-1])] if before else []) + within
    return sa.ChangeRows(**out)


class TestAHistoryKeptCurrent:
    """A caller that reads only what is new extends what it holds."""

    def test_two_reads_book_as_one(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        readings = heater(20, recovery_at=4)
        rows, observed = as_changes(readings)
        flow = with_a_draw(meter(20), 2.0)
        whole = sa.book_from_changes(rows, observed, p, at=T0, flow=flow)
        split = T0 - timedelta(hours=1)
        first = _read(rows, T0 - timedelta(hours=20), split)
        later = _read(rows, split, T0)
        joined = first.extended(later)
        got = sa.book_from_changes(joined, observed, p, at=T0, flow=flow)
        assert whole is not None and got is not None
        assert got.heat_btu == pytest.approx(whole.heat_btu)
        assert got.anchor_age_h == pytest.approx(whole.anchor_age_h)

    def test_trimmed_it_books_the_same(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        flow = with_a_draw(meter(20), 2.0)
        whole = sa.book_from_changes(rows, observed, p, at=T0, flow=flow)
        cut = T0 - timedelta(hours=10)
        trimmed = rows.since(cut)
        got = sa.book_from_changes(
            trimmed, [t for t in observed if t >= cut], p, at=T0, flow=flow
        )
        assert whole is not None and got is not None
        assert got.heat_btu == pytest.approx(whole.heat_btu)

    def test_a_split_flow_books_as_the_full_one(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        """A draw split by the reads books the same gallons."""
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        draw = T0 - timedelta(hours=2)
        full = with_a_draw(meter(20), 2.0)
        # A read from mid-draw opens with the flow in force there.
        split = draw + timedelta(minutes=2, seconds=45)
        first = [r for r in full if r[0] < split]
        later = [(split, 2.0), *(r for r in full if r[0] >= split)]
        merged = sa.merge_changes(first, later)
        want = sa.book_from_changes(rows, observed, p, at=T0, flow=full)
        got = sa.book_from_changes(rows, observed, p, at=T0, flow=merged)
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)

    def test_change_only_reads_book_as_one(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        """A draw as changes, split mid-way by the reads, and a recovery
        after an outage: the opening row repeats the value in force and
        changes nothing, the recovery is kept."""
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        draw = T0 - timedelta(hours=2)
        full = [
            (T0 - timedelta(hours=20), 0.0),
            (draw, 2.0),
            (draw + timedelta(minutes=10), 0.0),
        ]
        split = draw + timedelta(minutes=5)
        merged = sa.merge_changes(full[:2], [(split, 2.0), full[2]])
        want = sa.book_from_changes(rows, observed, p, at=T0, flow=full)
        got = sa.book_from_changes(rows, observed, p, at=T0, flow=merged)
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)
        gap = (draw + timedelta(minutes=2), draw + timedelta(minutes=10))
        rec = [*full[:2], (gap[1], 2.0), (draw + timedelta(minutes=20), 0.0)]
        joined = sa.merge_changes(rec[:2], rec[2:])
        assert joined == rec

    def test_the_later_read_wins_at_a_shared_instant(self) -> None:
        a = [(T0, 1.0), (T0 + timedelta(minutes=5), 2.0)]
        b = [(T0 + timedelta(minutes=5), 3.0), (T0 + timedelta(minutes=9), 4.0)]
        assert sa.merge_changes(a, b) == [
            (T0, 1.0),
            (T0 + timedelta(minutes=5), 3.0),
            (T0 + timedelta(minutes=9), 4.0),
        ]

    def test_since_keeps_the_value_in_force(self) -> None:
        rows = [(T0, 1.0), (T0 + timedelta(minutes=5), 2.0)]
        assert sa.changes_since(rows, T0 + timedelta(minutes=3)) == rows
        assert sa.changes_since(rows, T0 + timedelta(minutes=6)) == rows[1:]

    def test_outages_join_and_cut(self) -> None:
        a = [(T0, T0 + timedelta(minutes=10))]
        b = [(T0 + timedelta(minutes=10), T0 + timedelta(minutes=20))]
        joined = sa.join_spans(a, b)
        assert joined == [(T0, T0 + timedelta(minutes=20))]
        assert sa.spans_since(joined, T0 + timedelta(minutes=15)) == [
            (T0 + timedelta(minutes=15), T0 + timedelta(minutes=20))
        ]
        assert sa.spans_since(joined, T0 + timedelta(minutes=25)) == []


class TestHeardSpans:
    """A record with no instant per response says when the heater was
    heard as spans (``heard=``)."""

    H20 = T0 - timedelta(hours=20)

    def test_one_span_books_as_the_instants_do(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        rows, observed = as_changes(heater(20, recovery_at=4))
        flow = with_a_draw(meter(20), 2.0)
        want = sa.book_from_changes(rows, observed, p, at=T0, flow=flow)
        got = sa.book_from_changes(
            rows, [], p, at=T0, flow=flow, heard=[(self.H20, T0)]
        )
        assert want is not None and got is not None
        assert got.heat_btu == pytest.approx(want.heat_btu)
        assert got.anchor_age_h == pytest.approx(want.anchor_age_h)

    def test_a_gap_between_spans_breaks_the_book(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        rows, _ = as_changes(heater(20, recovery_at=4))
        flow = with_a_draw(meter(20), 2.0)
        # Unheard after the recovery's anchor: none before it counts.
        gap = (T0 - timedelta(hours=3), T0 - timedelta(hours=2.5))
        spans = [(self.H20, gap[0]), (gap[1], T0)]
        assert (
            sa.book_from_changes(rows, [], p, at=T0, flow=flow, heard=spans)
            is None
        )
        # Touching spans are one.
        whole = [(self.H20, gap[0]), (gap[0], T0)]
        assert (
            sa.book_from_changes(rows, [], p, at=T0, flow=flow, heard=whole)
            is not None
        )

    def test_not_heard_at_the_instant_is_no_book(
        self, heater: Callable[..., list[Any]]
    ) -> None:
        p = site_example_params()
        rows, _ = as_changes(heater(20, recovery_at=4))
        flow = with_a_draw(meter(20), 2.0)
        early = [(self.H20, T0 - timedelta(minutes=1))]
        assert (
            sa.book_from_changes(rows, [], p, at=T0, flow=flow, heard=early)
            is None
        )
        assert (
            sa.book_from_changes(rows, [], p, at=T0, flow=flow, heard=[])
            is None
        )


class TestTheHeatersOwnAir:
    def test_it_reads_only_after_the_run_settles(self) -> None:
        m = timedelta(minutes=1)
        t0 = T0 - timedelta(hours=1)
        compressor = [(t0, False), (t0 + 2 * m, True), (t0 + 12 * m, False)]
        # Idle at 80, 70 for the run's first 5 minutes, 50 after.
        air = [(t0, 80.0), (t0 + 2 * m, 70.0), (t0 + 7 * m, 50.0)]
        air.append((t0 + 12 * m, 80.0))
        got = sa.settled_air(compressor, air, until=T0)
        assert got == [(t0 + 7 * m, 50.0)]

    def test_the_reading_in_force_when_it_settles(self) -> None:
        """A recorder of changes writes no row while the air holds."""
        m = timedelta(minutes=1)
        t0 = T0 - timedelta(hours=1)
        compressor = [(t0, True), (t0 + 20 * m, False)]
        got = sa.settled_air(compressor, [(t0, 55.0)], until=T0)
        assert got == [(t0 + 5 * m, 55.0)]

    def test_a_run_unheard_restarts_its_clock(self) -> None:
        m = timedelta(minutes=1)
        t0 = T0 - timedelta(hours=1)
        compressor = [(t0, True), (t0 + 30 * m, False)]
        air = [(t0, 70.0), (t0 + 6 * m, 60.0), (t0 + 9 * m, 52.0)]
        # Unheard from 1 to 5 minutes into the run: heard again at 5, it
        # settles at 10, not at 5.
        got = sa.settled_air(
            compressor, air, until=T0, unheard=[(t0 + m, t0 + 5 * m)]
        )
        assert got == [(t0 + 10 * m, 52.0)]

    def test_a_heater_outage_restarts_the_clock(self) -> None:
        """A run across an outage of the heater's own record: from the
        changes alone, its warm reading after the outage is no air."""
        m = timedelta(minutes=1)
        t0 = T0 - timedelta(hours=2)
        rows = sa.ChangeRows(
            upper_f=((t0, 140.0),),
            lower_f=((t0, 139.0),),
            compressor_on=((t0, 1.0), (t0 + 12 * m, 0.0)),
            heater_air_f=((t0, 70.0), (t0 + 10 * m, 75.0)),
            outages=((t0 + m, t0 + 10 * m),),
        )
        steps = sa.book_steps_from_changes(
            rows, start=t0, end=T0, flow=[(t0, 0.0)]
        )
        assert {s.ambient_f for s in steps} == {65.0}

    def test_overlapping_unheard_spans_are_one(self) -> None:
        m = timedelta(minutes=1)
        t0 = T0 - timedelta(hours=1)
        compressor = [(t0, True), (t0 + 22 * m, False)]
        air = [(t0, 70.0), (t0 + 15 * m, 60.0), (t0 + 20 * m, 52.0)]
        unheard = [(t0 + m, t0 + 10 * m), (t0 + 5 * m, t0 + 20 * m)]
        # Heard again at 20 only: no 5 minutes heard before the run ends.
        assert sa.settled_air(compressor, air, until=T0, unheard=unheard) == []

    def _readings(
        self, device_status_dict: dict[str, Any], hours: float
    ) -> list[Any]:
        out = []
        t = T0 - timedelta(hours=hours)
        recovery = T0 - timedelta(hours=4)
        while t <= T0:
            heating = recovery <= t < recovery + timedelta(minutes=30)
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
                            # 50 °F running, the cabinet's 80 idle.
                            "ambientTemperature": 100 if heating else 267,
                        }
                    ),
                )
            )
            t += timedelta(minutes=1)
        return out

    def test_without_an_air_reading_the_book_takes_it(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        p = site_example_params()
        readings = self._readings(device_status_dict, 20)
        flow = with_a_draw(meter(20), 2.0)
        start = T0 - timedelta(hours=20)
        own = sa.book_from_history(readings, p, at=T0, flow=flow)
        at_50 = sa.book_from_history(
            readings, p, at=T0, flow=flow, air=[(start, 50.0)]
        )
        at_65 = sa.book_from_history(
            readings, p, at=T0, flow=flow, air=[(start, 65.0)]
        )
        assert own is not None and at_50 is not None and at_65 is not None
        assert own.heat_btu == pytest.approx(at_50.heat_btu)
        assert own.heat_btu != pytest.approx(at_65.heat_btu)
        # And from the changes, as from the statuses.
        rows, observed = as_changes(readings)
        changed = sa.book_from_changes(rows, observed, p, at=T0, flow=flow)
        assert changed is not None
        assert changed.heat_btu == pytest.approx(own.heat_btu)

    def test_a_run_before_the_window_still_gives_its_air(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        """The run ends 4 h before ``T0``: a window from 3 h holds its
        air, not the default."""
        readings = self._readings(device_status_dict, 20)
        start = T0 - timedelta(hours=3)
        flow = meter(20)
        steps = sa.book_steps_from_history(
            readings, start=start, end=T0, flow=flow
        )
        assert {s.ambient_f for s in steps} == {50.0}
        rows, _ = as_changes(readings)
        changed = sa.book_steps_from_changes(
            rows, start=start, end=T0, flow=flow
        )
        assert {s.ambient_f for s in changed} == {50.0}


class TestARunsGallonsForTheCircuit:
    def _steps(
        self, runs: list[tuple[datetime, datetime]], start: datetime
    ) -> list[Any]:
        from nwp500.sim import site_example_params

        return sa.book_steps_from_changes(
            sa.ChangeRows(
                upper_f=[(T0 - timedelta(hours=3), 140.0)],
                lower_f=[(T0 - timedelta(hours=3), 140.0)],
            ),
            start=start,
            end=T0,
            flow=[(T0 - timedelta(hours=3), 0.0)],
            circulation=runs,
            circulation_flow=sa.run_flow(runs, 1.2),
            params=site_example_params(),
        )

    def test_runs_within_the_gap_are_one(self) -> None:
        m = timedelta(minutes=1)
        a = T0 - timedelta(hours=2)
        near = [(a, a + 5 * m), (a + 10 * m, a + 15 * m)]
        steps = self._steps(near, a)
        second = next(
            s for s in steps if s.circulating and s.run_gal_before > 5.9
        )
        assert second.run_gal_before == pytest.approx(6.0)
        far = [(a, a + 5 * m), (a + 30 * m, a + 35 * m)]
        firsts = [
            s.run_gal_before
            for s, prev in zip(self._steps(far, a)[1:], self._steps(far, a))
            if s.circulating and not prev.circulating
        ]
        assert firsts == [0.0]

    def test_a_run_under_way_at_the_start_counts_what_it_ran(self) -> None:
        m = timedelta(minutes=1)
        a = T0 - timedelta(hours=2)
        steps = self._steps([(a, a + 10 * m)], a + 4 * m)
        assert steps[0].circulating
        assert steps[0].run_gal_before == pytest.approx(4 * 1.2)

    def test_a_window_mid_run_takes_the_earlier_flow(self) -> None:
        """0.2 gal/min for the run's first 4 minutes, then 1.2: a window
        from the change has 0.8 gal behind it, as the whole history
        does there."""
        from nwp500.sim import site_example_params

        m = timedelta(minutes=1)
        a = T0 - timedelta(hours=2)
        runs = [(a, a + 10 * m)]
        flow = [(a, 0.2), (a + 4 * m, 1.2)]

        def steps(start: datetime) -> list[Any]:
            return sa.book_steps_from_changes(
                sa.ChangeRows(
                    upper_f=[(a - timedelta(hours=1), 140.0)],
                    lower_f=[(a - timedelta(hours=1), 140.0)],
                ),
                start=start,
                end=T0,
                flow=[(a - timedelta(hours=1), 0.0)],
                circulation=runs,
                circulation_flow=flow,
                params=site_example_params(),
            )

        sliced = steps(a + 4 * m)[0]
        whole = next(s for s in steps(a) if s.circulation_gpm == 1.2)
        assert sliced.run_gal_before == pytest.approx(0.8)
        assert sliced.run_gal_before == pytest.approx(whole.run_gal_before)

    def test_a_window_in_a_gap_keeps_the_groups_gallons(self) -> None:
        """One-minute runs at minutes 0 and 6, 1.2 gal/min: a window
        from minute 2 has the first run's 1.2 gal behind the second, as
        the whole history does."""
        m = timedelta(minutes=1)
        a = T0 - timedelta(hours=2)
        runs = [(a, a + m), (a + 6 * m, a + 7 * m)]
        second = a + 6 * m

        def first_of_second(start: datetime) -> float:
            steps = self._steps(runs, start)
            k = next(
                i
                for i, s in enumerate(steps)
                if s.circulating
                and start + i * timedelta(seconds=sa.BOOK_GRID_S) >= second
            )
            return float(steps[k].run_gal_before)

        assert first_of_second(a + 2 * m) == pytest.approx(1.2)
        assert first_of_second(a + 2 * m) == pytest.approx(first_of_second(a))

    def test_a_window_carries_an_earlier_runs_flow(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        """Runs at minutes 0-1 and 20-30, the flow read 0.2 at minute 0
        and 1.2 at 24: from the statuses, a window from minute 24 has
        the 0.8 gal the whole history has there, the first run's
        reading carried past its hold."""
        from nwp500.sim import site_example_params

        m = timedelta(minutes=1)
        a = T0 - timedelta(hours=1)
        status = DeviceStatus.model_validate(
            device_status_dict
            | {"tankUpperTemperature": 600, "tankLowerTemperature": 598}
        )
        readings = [(a + k * m, status) for k in range(61)]
        runs = [(a, a + m), (a + 20 * m, a + 30 * m)]

        def at_24(start: datetime) -> float:
            steps = sa.book_steps_from_history(
                readings,
                start=start,
                end=a + 60 * m,
                flow=[(a + k * m, 0.0) for k in range(61)],
                circulation=runs,
                circulation_flow=[(a, 0.2), (a + 24 * m, 1.2)],
                params=site_example_params(),
            )
            k = int((a + 24 * m - start) / timedelta(seconds=sa.BOOK_GRID_S))
            return float(steps[k].run_gal_before)

        assert at_24(a + 24 * m) == pytest.approx(0.8)
        assert at_24(a + 24 * m) == pytest.approx(at_24(a))

    def test_a_probe_unread_still_counts_the_runs_gallons(self) -> None:
        """A run from minute 1 at 1.2 gal/min, the lower probe first
        read at minute 4: its first step has 3.6 gal behind it."""
        m = timedelta(minutes=1)
        a = T0 - timedelta(hours=1)
        runs = [(a + m, a + 20 * m)]
        from nwp500.sim import site_example_params

        steps = sa.book_steps_from_changes(
            sa.ChangeRows(upper_f=[(a, 140.0)], lower_f=[(a + 4 * m, 140.0)]),
            start=a,
            end=a + 30 * m,
            flow=[(a, 0.0)],
            circulation=runs,
            circulation_flow=sa.run_flow(runs, 1.2),
            params=site_example_params(),
        )
        assert steps[0].circulating
        assert steps[0].run_gal_before == pytest.approx(3 * 1.2)
