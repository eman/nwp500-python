"""The heat book walked along a simulation (``nwp500.sim.book``).

The walk only schedules ``Booked``'s operations: these check it charges
each thing the simulation did once, at the book's terms, and places it
where the book places it.
"""

import itertools
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import pytest

pytest.importorskip("pandas")

from _sim_site import (  # type: ignore[import-not-found]  # test helper
    EP,
    Booked,
    BookedHeatLedger,
    compressor_btu,
    loss_ceiling_btu,
    standby_btu,
    walk_booked,
)

from nwp500.sim.book import BookedPath, Step, book_steps, full_tank
from nwp500.sim.controller import Source, Start, StopReason
from nwp500.sim.engine import Draw, HeatingInterval, PathPoint

T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
#: After a bath: 30 gal of inlet water at the bottom, 10 gal drawable.
PER_GAL = 8.34 * (53.56 + 0.485 * 130.0 - 70.0)
AFTER_BATH = Booked(
    heat_btu=EP.empty_btu + 10.0 * PER_GAL,
    anchor_age_h=3.0,
    inlet_f=70.0,
    cold_gal=30.0,
    cold_f=70.0,
)


def m(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def flat(
    *minutes: float, upper: float = 130.0, lower: float = 100.0
) -> list[PathPoint]:
    return [PathPoint(m(x), upper, lower, 140.0, False, 0.0) for x in minutes]


def heating(
    a: float,
    b: float,
    source: Source = "compressor",
    zone: Literal["upper", "lower"] | None = None,
    stop: StopReason = "write",
) -> HeatingInterval:
    return HeatingInterval(
        Start(m(a), "heater", source=source),
        m(b),
        140.0,
        False,
        stop,
        0.0,
        None,
        None,
        source=source,
        zone=zone,
    )


def walk(
    points: Sequence[PathPoint],
    *,
    heat: Sequence[HeatingInterval] = (),
    draws: Sequence[Draw] = (),
    start: Booked = AFTER_BATH,
) -> BookedPath:
    return cast(
        BookedPath,
        walk_booked(start, points, list(heat), list(draws), lambda _: 65.0),
    )


def standby(
    minutes: float,
    upper: float = 130.0,
    lower: float = 100.0,
    ambient: float = 65.0,
) -> float:
    return cast(
        float,
        EP.ua_btu_per_h_f * ((upper + lower) / 2 - ambient) * minutes / 60,
    )


class TestTheWalk:
    def test_standby_alone_is_the_books_standby(self) -> None:
        path = walk(flat(0, 30, 60))
        assert path.states[0] == AFTER_BATH
        assert AFTER_BATH.heat_btu - path.states[-1].heat_btu == (
            pytest.approx(standby(60))
        )

    def test_a_recovery_is_the_books_heat_minute_by_minute(self) -> None:
        """One implementation: an hour of compressor walked here moves
        the state exactly as the book's own terms, a minute at a time."""
        path = walk(flat(0, 30, 60), heat=[heating(0, 60)])
        steps = AFTER_BATH
        for _ in range(60):
            steps = steps.heated(compressor_btu(1 / 60, 65.0, EP)).lost(
                standby_btu(1 / 60, 130.0, 100.0, 65.0, EP)
            )
        assert path.states[-1].heat_btu == pytest.approx(steps.heat_btu)
        assert path.states[-1].cold_f == pytest.approx(steps.cold_f)

    def test_compressor_heat_lands_in_the_cold_bottom(self) -> None:
        path = walk(flat(0, 60), heat=[heating(0, 60)])
        end = path.states[-1]
        assert end.heat_btu > AFTER_BATH.heat_btu + 3000.0
        assert end.deliverable_gal(130.0) < AFTER_BATH.deliverable_gal(130.0)

    def test_the_upper_elements_heat_is_drawable(self) -> None:
        path = walk(flat(0, 10), heat=[heating(0, 10, "element", "upper")])
        gained = path.states[-1].deliverable_gal(130.0) - (
            AFTER_BATH.deliverable_gal(130.0)
        )
        heat = EP.element_w * 3.412 / 6.0 - standby(10)
        assert gained == pytest.approx(heat / PER_GAL, abs=0.01)

    def test_the_lower_elements_is_not(self) -> None:
        path = walk(flat(0, 10), heat=[heating(0, 10, "element", "lower")])
        assert path.states[-1].deliverable_gal(130.0) < (
            AFTER_BATH.deliverable_gal(130.0)
        )

    def test_a_draw_is_taken_at_its_instant_between_its_two_elements(
        self,
    ) -> None:
        points = [*flat(0, 30), *flat(30, 60, upper=129.0)]
        path = walk(points, draws=[(m(30), 6.0)])
        before, after = path.states[1], path.states[2]
        assert before.cold_gal == AFTER_BATH.cold_gal
        assert before.deliverable_gal(130.0) - after.deliverable_gal(
            130.0
        ) == pytest.approx(6.0, abs=0.01)
        assert path.before(m(30)) == before

    def test_a_draw_between_elements_is_still_taken(self) -> None:
        path = walk(flat(0, 60), draws=[(m(17), 4.0)])
        assert AFTER_BATH.deliverable_gal(130.0) - path.states[
            -1
        ].deliverable_gal(130.0) == pytest.approx(
            4.0 + standby(60) / PER_GAL, abs=0.01
        )

    def test_the_walk_does_not_release_on_the_modelled_lower_zone(self) -> None:
        """The modelled lower zone reads warm and fired mid-draw; a walk
        release turned 2026-09-21's forecast depletion into a miss. A
        seen region stays, whatever the modelled lower zone reads."""
        seen = replace(AFTER_BATH, cold_seen=True)
        end = walk(flat(0, 30, 60, lower=110.0), start=seen).states[-1]
        assert end.cold_gal == AFTER_BATH.cold_gal

    def test_a_recovery_lifting_the_lower_zone_releases_a_seen_region(
        self,
    ) -> None:
        """Through the same function as the book's own release: while
        the compressor heats and nothing has
        been drawn, the lower zone reaching the line releases a region
        the probe saw; one it never saw stays."""
        seen = replace(AFTER_BATH, cold_seen=True)
        points = [*flat(0, 30, lower=90.0), *flat(60, 90, lower=101.0)]
        path = walk(points, heat=[heating(0, 90)], start=seen)
        assert [s.cold_gal for s in path.states] == [30.0, 30.0, 0.0, 0.0]
        unseen = walk(points, heat=[heating(0, 90)]).states[-1]
        assert unseen.cold_gal > 0.0

    def test_not_after_a_draw_in_the_walk(self) -> None:
        """After a modelled draw the modelled lower zone reads warm where
        the probe would read the cold front: no release on it."""
        seen = replace(AFTER_BATH, cold_seen=True)
        points = [*flat(0, 30, lower=90.0), *flat(60, 90, lower=101.0)]
        path = walk(
            points, heat=[heating(0, 90)], draws=[(m(30), 2.0)], start=seen
        )
        assert path.states[-1].cold_gal > 0.0

    def test_a_recovery_that_ends_full_re_anchors_as_the_book_does(
        self,
    ) -> None:
        """Where the simulated recovery ends with both zones in the
        book's uniform band and nothing moves after, the tank is full:
        its heat is what the zones say, and the cold region is gone."""
        points = [*flat(0, 60), *flat(90, 120, upper=140.0, lower=139.5)]
        path = walk(points, heat=[heating(0, 90)])
        end = path.states[-1]
        assert end.cold_gal == 0.0
        assert end.heat_btu == pytest.approx(
            8.34 * EP.tank_gal * (139.75 - 70.0)
        )

    def test_not_while_a_draw_has_moved_it_since(self) -> None:
        points = [*flat(0, 60), *flat(90, 120, upper=140.0, lower=139.5)]
        end = walk(points, heat=[heating(0, 90)], draws=[(m(90), 1.0)]).states[
            -1
        ]
        assert end.cold_gal > 0.0

    def test_nor_a_tank_the_recovery_left_stratified(self) -> None:
        points = [*flat(0, 60), *flat(90, 120, upper=140.0, lower=130.0)]
        assert walk(points, heat=[heating(0, 90)]).states[-1].cold_gal > 0.0

    def test_a_recovery_the_heater_ended_itself_re_anchors_stratified(
        self,
    ) -> None:
        """The heater's own stop (its target, or the TOU cap) is the event
        the book anchors on in the record: the tank is full by the
        heater's rule. The modelled zones may still show a gap then (the
        two-zone shape); the anchor is their mean, and the cold
        region is gone."""
        points = [*flat(0, 60), *flat(90, 120, upper=146.0, lower=120.0)]
        for stop in ("target", "cap"):
            path = walk(points, heat=[heating(0, 90, stop=stop)])
            at_end = path.states[2]
            assert at_end.cold_gal == 0.0, stop
            assert at_end.heat_btu == pytest.approx(
                8.34 * EP.tank_gal * (133.0 - 70.0)
            )

    def test_one_a_write_ended_stratified_does_not(self) -> None:
        """A write, a mode or the horizon stops a recovery the heater had
        not finished: 2026-03-31's 03:08 write left the zones 146/113 and
        the probes read 137/100 twenty minutes later. Only the book's own
        test, both zones within 1.5 °F, anchors there."""
        points = [*flat(0, 60), *flat(90, 120, upper=146.0, lower=113.0)]
        for stop in ("write", "mode", "horizon"):
            end = walk(points, heat=[heating(0, 90, stop=stop)]).states[-1]
            assert end.cold_gal > 0.0, stop

    def test_the_upper_elements_target_is_not_a_full_tank(self) -> None:
        points = [*flat(0, 10), *flat(15, 30, upper=146.0, lower=100.0)]
        path = walk(points, heat=[heating(0, 15, "element", "upper", "target")])
        assert path.states[-1].cold_gal > 0.0


def busy_day() -> tuple[list[PathPoint], list[HeatingInterval], list[Draw]]:
    """A day of the walk's every term: a seen cold bottom, recoveries
    the heater ended itself and ones a write ended, both elements,
    twenty draws (some inside recoveries), and stretches where the
    zones are within the band, so it anchors and releases."""
    points: list[PathPoint] = []
    upper, lower = 130.0, 95.0
    heat = [
        heating(40, 160, stop="target"),
        heating(300, 330, "element", "upper", stop="target"),
        heating(420, 560, stop="write"),
        heating(700, 760, "element", "lower", stop="target"),
        heating(900, 1100, stop="target"),
    ]
    draws: list[Draw] = [
        (m(minute), 2.0 + (k % 5) * 3.0)
        for k, minute in enumerate(range(20, 1440, 70))
    ]
    for minute in range(0, 1441, 10):
        heating_now = any(h.start.at <= m(minute) < h.end for h in heat)
        if heating_now:
            lower = min(upper, lower + 2.2)
            upper = max(upper, lower)
        else:
            upper -= 0.05
            lower -= 0.05
        if any(at == m(minute) for at, _ in draws):
            points.append(
                PathPoint(m(minute), upper, lower, 140.0, heating_now, 0.0)
            )
            lower -= 4.0
            upper -= 0.3
        points.append(
            PathPoint(m(minute), upper, lower, 140.0, heating_now, 0.0)
        )
    return points, heat, draws


class TestTheWalkResumes:
    """The engine walks the book at each draw, resuming
    where the last walk stood rather than from the start; a resumed walk
    is the whole walk from there on, element for element."""

    def test_resumed_at_every_instant_it_is_the_whole_walk(self) -> None:
        points, heat, draws = busy_day()
        start = replace(AFTER_BATH, cold_seen=True)
        whole = walk(points, heat=heat, draws=draws, start=start)
        # It anchors and it releases somewhere in the day.
        assert any(x.anchor_age_h == 0.0 for x in whole.states)
        assert any(
            a.cold_gal > 0.0 and b.cold_gal == 0.0
            for a, b in itertools.pairwise(whole.states)
        )
        carry = None
        for i, pt in enumerate(points):
            prefix = [p for p in points if p.at <= pt.at]
            first = walk_booked(
                start,
                prefix,
                heat,
                [d for d in draws if d[0] <= pt.at],
                lambda _: 65.0,
                carry=carry,
                keep=pt.at,
            )
            assert first.carry is not None
            assert first.carry.at == pt.at
            carry = first.carry
            rest = walk_booked(
                start, points, heat, draws, lambda _: 65.0, carry=carry
            )
            j = next(k for k, p in enumerate(points) if p.at == pt.at)
            assert rest.states == whole.states[j:], i

    def test_without_a_carry_or_keep_it_is_the_walk_it_was(self) -> None:
        points, heat, draws = busy_day()
        a = walk(points, heat=heat, draws=draws)
        b = walk_booked(
            AFTER_BATH, points, heat, draws, lambda _: 65.0, keep=None
        )
        assert a == b
        assert a.carry is None


#: Both zones within the book's band, the compressor mixing the tank.
FULL: dict[str, float] = {"upper": 133.0, "lower": 132.3}


def anchored(b: Booked) -> bool:
    return b.anchor_age_h == 0.0 and b.cold_gal == 0.0


class TestTheCompressorAnchors:
    """A full tank anchors as the compressor runs alone, once it has run
    ``anchor_run_min`` since a draw booked after the last anchor."""

    def test_a_full_tank_anchors_once_it_has_run_the_hold(self) -> None:
        path = walk(flat(0, 10, 14, 15, 30, **FULL), heat=[heating(0, 60)])
        assert not anchored(path.before(m(14)))
        assert anchored(path.before(m(15)))

    def test_with_no_draw_booked_there_is_no_hold(self) -> None:
        start = replace(AFTER_BATH, cold_gal=0.0)
        path = walk(flat(0, 10, 30, **FULL), heat=[heating(0, 60)], start=start)
        assert not anchored(path.before(m(0)))
        assert anchored(path.before(m(10)))

    def test_a_draw_holds_it_again(self) -> None:
        start = replace(AFTER_BATH, cold_gal=0.0)
        path = walk(
            flat(0, 10, 20, 30, 34, 35, 50, **FULL),
            heat=[heating(0, 60)],
            draws=[(m(20), 1.0)],
            start=start,
        )
        full = full_tank(133.0, 132.3, 70.0, EP).heat_btu
        assert path.before(m(10)).heat_btu == pytest.approx(full)
        assert path.before(m(34)).heat_btu != pytest.approx(full)
        assert path.before(m(35)).heat_btu == pytest.approx(full)

    def test_the_hold_is_compressor_time_not_wall_time(self) -> None:
        points = [
            *flat(0, 5, 39, upper=133.0, lower=120.0),
            *flat(40, 49, 50, 55, **FULL),
        ]
        path = walk(points, heat=[heating(0, 5), heating(40, 60)])
        assert not anchored(path.before(m(49)))
        assert anchored(path.before(m(50)))

    @pytest.mark.parametrize(
        "heat",
        [
            [heating(0, 60, source="element", zone="lower")],
            [heating(0, 60), heating(0, 60, source="element", zone="upper")],
        ],
        ids=["lower_element", "with_the_upper_element"],
    )
    def test_an_element_does_not_anchor(
        self, heat: list[HeatingInterval]
    ) -> None:
        path = walk(flat(0, 20, 40, 50, **FULL), heat=heat)
        assert not any(anchored(path.before(m(x))) for x in (20, 40))

    def test_a_disturbed_span_does_not_anchor(self) -> None:
        path = walk_with(
            flat(0, 20, 40, 50, **FULL),
            Circulation([(m(0), m(60))]),
            heat=[heating(0, 60)],
        )
        assert not any(anchored(path.before(m(x))) for x in (20, 40))

    def test_resumed_at_every_instant_it_is_the_whole_walk(self) -> None:
        points = flat(0, 5, 12, 20, 26, 27, 28, 40, **FULL)
        heat = [heating(0, 50)]
        draws: list[Draw] = [(m(12), 1.0)]
        whole = walk(points, heat=heat, draws=draws)
        assert anchored(whole.before(m(27)))
        carry = None
        for pt in points:
            first = walk_booked(
                AFTER_BATH,
                [p for p in points if p.at <= pt.at],
                heat,
                [d for d in draws if d[0] <= pt.at],
                lambda _: 65.0,
                carry=carry,
                keep=pt.at,
            )
            carry = first.carry
            rest = walk_booked(
                AFTER_BATH, points, heat, draws, lambda _: 65.0, carry=carry
            )
            j = next(k for k, p in enumerate(points) if p.at == pt.at)
            assert rest.states == whole.states[j:]

    @pytest.mark.parametrize(
        "rise_f", [0.5, 0.02], ids=["held", "uniform_late"]
    )
    def test_recorded_and_simulated_anchor_at_the_same_step(
        self, rise_f: float
    ) -> None:
        """One recovery, recorded (``book_steps``) and simulated
        (``walk_booked``), the lower probe rising into the band: the
        first anchor is at the same step, the hold binding or not."""
        lowers = [min(132.5, 125.0 + rise_f * i) for i in range(400)]
        steps = [
            Step(10.0, 133.0, lo, 0.0, True, False, 65.0, 70.0) for lo in lowers
        ]
        recorded = next(
            j for j in range(len(steps)) if book_steps(steps[: j + 1], EP)
        )
        at = [T0 + timedelta(seconds=10 * (i + 1)) for i in range(len(steps))]
        points = [
            PathPoint(T0, 133.0, 125.0, 140.0, False, 0.0),
            *(
                PathPoint(x, 133.0, lo, 140.0, False, 0.0)
                for x, lo in zip(at, lowers, strict=True)
            ),
        ]
        path = walk(points, heat=[heating(0, 70)])
        simulated = next(
            i for i, x in enumerate(at) if anchored(path.before(x))
        )
        assert simulated == recorded


class TestAWithheldWindow:
    """Over a withheld window a recovery runs and is credited no heat,
    in the book as in the zones."""

    def test_no_heat_is_booked_inside_it(self) -> None:
        points = flat(0, 30, 60, 90)
        heat = [heating(0, 90)]
        credited = walk(points, heat=heat).states[-1].heat_btu
        withheld = (
            walk_booked(
                AFTER_BATH,
                points,
                heat,
                [],
                lambda _: 65.0,
                withheld=[(m(30), m(60))],
            )
            .states[-1]
            .heat_btu
        )
        assert credited - withheld == pytest.approx(
            compressor_btu(0.5, 65.0, EP)
        )

    def test_it_is_not_quiet_there(self) -> None:
        """A heater running in a withheld window has not ended its
        recovery: a uniform tank there is no anchor."""
        points = flat(0, 30, 60, 90, upper=130.0, lower=129.5)
        heat = [heating(0, 90, stop="write")]
        path = walk_booked(
            AFTER_BATH,
            points,
            heat,
            [],
            lambda _: 65.0,
            withheld=[(m(0), m(60))],
        )
        for at in (m(30), m(45), m(60)):
            assert path.before(at).anchor_age_h == AFTER_BATH.anchor_age_h


class Circulation:
    """A client's own loss (``SpanLoss``): ``btu_per_min`` while a run
    is on, which disturbs the tank."""

    def __init__(
        self,
        runs: Sequence[tuple[datetime, datetime]],
        btu_per_min: float = 318.0,
    ) -> None:
        self.runs = list(runs)
        self.rate = btu_per_min

    def edges(self, start: datetime, end: datetime) -> list[datetime]:
        return [x for r in self.runs for x in r]

    def loss(self, a: datetime, b: datetime) -> tuple[float, bool]:
        on = any(r0 <= a < r1 for r0, r1 in self.runs)
        minutes = (b - a).total_seconds() / 60.0
        return (self.rate * minutes if on else 0.0, on)

    def bound(self, a: datetime, b: datetime) -> float:
        return self.rate * sum(
            max(0.0, (min(r1, b) - max(r0, a)).total_seconds() / 60.0)
            for r0, r1 in self.runs
        )


def walk_with(
    points: Sequence[PathPoint], extra: object, **kw: Any
) -> BookedPath:
    return cast(
        BookedPath,
        walk_booked(
            kw.pop("start", AFTER_BATH),
            points,
            list(kw.pop("heat", ())),
            list(kw.pop("draws", ())),
            lambda _: 65.0,
            extra=extra,
        ),
    )


class TestAClientsOwnLoss:
    """The book charges a loss it does not model through ``SpanLoss``:
    over each span, a disturbed span is not quiet, and the bound adds
    it."""

    def test_its_heat_is_charged_over_its_spans(self) -> None:
        quiet = walk(flat(0, 60)).states[-1].heat_btu
        run = Circulation([(m(10), m(20))])
        charged = walk_with(flat(0, 60), run).states[-1].heat_btu
        assert quiet - charged == pytest.approx(318.0 * 10)

    def test_a_disturbed_span_does_not_re_anchor(self) -> None:
        points = [*flat(0, 60), *flat(90, 120, upper=140.0, lower=139.5)]
        end = walk_with(
            points, Circulation([(m(85), m(94))]), heat=[heating(0, 90)]
        ).states[-1]
        assert end.cold_gal > 0.0

    def test_it_anchors_as_the_heating_ends_before_a_later_run(self) -> None:
        """The book anchors on the first quiet step after a recovery; a
        run starting ten minutes later does not undo it."""
        points = [*flat(0, 60), *flat(90, 120, upper=140.0, lower=139.5)]
        path = walk_with(
            points, Circulation([(m(100), m(110))]), heat=[heating(0, 90)]
        )
        assert path.states[2].cold_gal == 0.0
        assert path.states[2].heat_btu == pytest.approx(
            8.34 * EP.tank_gal * (139.75 - 70.0)
        )

    def test_the_bound_adds_it(self) -> None:
        run = Circulation([(m(10), m(20)), (m(50), m(70))])
        standby = loss_ceiling_btu(m(0), m(60), 140.0)
        assert loss_ceiling_btu(m(0), m(60), 140.0, extra=run) == pytest.approx(
            standby + 318.0 * 20
        )
        ledger = BookedHeatLedger(AFTER_BATH, lambda _: 65.0, extra=run)
        assert ledger.loss_bound(m(0), m(60), 140.0) == pytest.approx(
            standby + 318.0 * 20
        )

    def test_resumed_at_every_instant_it_is_still_the_whole_walk(self) -> None:
        points, heat, draws = busy_day()
        run = Circulation([(m(a), m(a + 6)) for a in (100, 380, 610, 880)])
        start = replace(AFTER_BATH, cold_seen=True)
        whole = walk_with(points, run, heat=heat, draws=draws, start=start)
        carry = None
        for pt in points[::7]:
            prefix = [p for p in points if p.at <= pt.at]
            first = walk_booked(
                start,
                prefix,
                heat,
                [d for d in draws if d[0] <= pt.at],
                lambda _: 65.0,
                carry=carry,
                keep=pt.at,
                extra=run,
            )
            carry = first.carry
            rest = walk_booked(
                start,
                points,
                heat,
                draws,
                lambda _: 65.0,
                carry=carry,
                extra=run,
            )
            j = next(k for k, p in enumerate(points) if p.at == pt.at)
            assert rest.states == whole.states[j:]
