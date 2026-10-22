"""The heat book's terms and the circulation's from the book's
re-anchors (``sim_calibrate.fit_book``).

The histories are walked by the book's own heat balance, so the terms
they were made with are the ones a fit should find.
"""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("scipy")

import numpy as np

from nwp500 import sim_adapters as sa
from nwp500 import sim_calibrate
from nwp500.sim import site_example_params
from nwp500.sim.defaults import SITE_CIRCULATION
from nwp500.sim.params import BookParams, CirculationParams, HeaterParams
from nwp500.sim.units import WATER_BTU_PER_GAL_F

T0 = datetime(2026, 1, 5, tzinfo=UTC)
STEP = timedelta(seconds=sa.BOOK_GRID_S)
#: One cycle: quiet, a run, quiet, a recovery, quiet; minutes. The
#: run's end and the recovery's vary by cycle, and the air, so that each
#: of the book's terms moves the pairs differently.
RUN = (60, 75)
RECOVERY = (150, 210)
CYCLE = 360
AIR_F = 65.0
AIR_SWING_F = (-8.0, 0.0, 6.0, -3.0)


def run_end(cycle: int) -> int:
    return RUN[1] + 5 * (cycle % 3)


def recovery_end(cycle: int) -> int:
    return RECOVERY[1] + 10 * (cycle % 2)


def air_at(cycle: int) -> float:
    return AIR_F + AIR_SWING_F[cycle % len(AIR_SWING_F)]


#: The meter's reading during a run, gal/min.
RUN_GPM = 1.0


def no_pump(params: HeaterParams, cycles: int, **kw: Any) -> dict[str, Any]:
    """A history with no circulation: no runs, nothing taken by them."""
    return history(params, cycles, 0.0, meter_sees=False, **kw) | {"runs": []}


def history(
    params: HeaterParams,
    cycles: int,
    loss: float,
    *,
    meter_sees: bool = True,
    late_loss: float | None = None,
    late_from: int = 0,
    tap_gpm: float = 0.0,
    draw_at_h: float | None = None,
    reported: bool = False,
    after_gpm: float = 0.0,
    truth: BookParams | None = None,
    air_f: float | None = None,
    tied: bool = False,
    run_every: int = 1,
    runs_in: int | None = None,
    run_min: int | None = None,
) -> dict[str, Any]:
    """A history of ``cycles`` six-hour cycles walked by the book's own
    balance (``truth``, else ``params``' book), each run taking ``loss``
    per gallon (``late_loss`` from cycle ``late_from`` on), the air at
    ``air_f`` throughout or else varying by cycle, and what ``fit_book``
    takes. ``tied`` makes each run a quarter of its cycle's recovery,
    so the runs' gallons follow the compressor's hours."""

    def runs_to(cycle: int) -> int:
        if run_min is not None:
            return RUN[0] + run_min
        if tied:
            return RUN[0] + (recovers_to(cycle) - RECOVERY[0]) // 4
        return run_end(cycle)

    def recovers_to(cycle: int) -> int:
        if tied:
            return RECOVERY[1] + 20 * (cycle % 2)
        return recovery_end(cycle)

    p = truth if truth is not None else params.book_terms()
    mass = WATER_BTU_PER_GAL_F * p.tank_gal
    h = sa.BOOK_GRID_S / 3600.0
    per_step = sa.BOOK_GRID_S / 60.0
    n = cycles * CYCLE * 6
    temp = 125.0
    probe: list[tuple[datetime, float]] = []
    comp: list[tuple[datetime, bool]] = []
    flow: list[tuple[datetime, float]] = []
    runs: list[tuple[datetime, datetime]] = []
    # A recovery first, so there is an anchor before the first run.
    first = (0, 30)
    for i in range(n):
        t = T0 + i * STEP
        minute = (i // 6) % CYCLE
        cycle = i // (6 * CYCLE)
        air = air_at(cycle) if air_f is None else air_f
        heating = RECOVERY[0] <= minute < recovers_to(cycle) or (
            cycle == 0 and first[0] <= minute < first[1]
        )
        running = (
            RUN[0] <= minute < runs_to(cycle)
            and cycle % run_every == 0
            and (runs_in is None or cycle < runs_in)
        )
        # A tap open for the run's first minute, and one for the minute
        # after it.
        tap = tap_gpm if minute == RUN[0] else 0.0
        if minute == runs_to(cycle):
            tap += after_gpm
        if draw_at_h is not None and 0 <= (i * 10 / 3600 - draw_at_h) < 5 / 60:
            # A five-minute draw at 2 gal/min.
            tap = 2.0
        if running and minute == RUN[0] and i % 6 == 0:
            runs.append((t, t + timedelta(minutes=runs_to(cycle) - RUN[0])))
        probe.append((t, temp))
        comp.append((t, heating))
        flow.append((t, (RUN_GPM if running and meter_sees else 0.0) + tap))
        per_gal = loss if late_loss is None or cycle < late_from else late_loss
        circulated = RUN_GPM * per_step if running else 0.0
        e = (
            heating * (p.hp_btu_per_h + p.hp_btu_per_h_per_f * (air - 65.0)) * h
            - per_gal * circulated
            - p.ua_btu_per_h_f * max(temp - air, 0.0) * h
        )
        if tap > p.draw_gpm:
            delivered = min(
                temp, p.delivery_intercept_f + p.delivery_slope * temp
            )
            e -= (
                tap
                * per_step
                * WATER_BTU_PER_GAL_F
                * max(delivered - p.reference_f, 0.0)
            )
        temp += e / mass
    rows = sa.ChangeRows(upper_f=probe, lower_f=probe, compressor_on=comp)
    if reported:
        flow = reports(flow)
    return {
        "rows": rows,
        "observed": [t for t, _ in probe[::3]],
        "flow": flow,
        "runs": runs,
        "air": [
            (
                T0 + timedelta(minutes=CYCLE * c),
                air_at(c) if air_f is None else air_f,
            )
            for c in range(cycles)
        ],
    }


def reports(flow: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    """``flow`` as a meter reporting its volume every 30 s, 15 s off the
    minute, each report's volume spread evenly back over the 30 s it
    closes, in the book's 10 s steps (as ``read_water_use``'s
    ``book_flow`` does): a run's water reaches into the steps either
    side of it."""
    # The flow in 5 s halves of each step, each report closing six.
    halves = [v for _, v in flow for _ in range(2)]
    spread = [0.0] * len(halves)
    for end in range(3, len(halves) + 1, 6):
        lo = max(end - 6, 0)
        mean = sum(halves[lo:end]) / 6
        for i in range(lo, end):
            spread[i] = mean
    return [
        (t, (spread[2 * i] + spread[2 * i + 1]) / 2)
        for i, (t, _) in enumerate(flow)
    ]


def fit(
    params: HeaterParams, h: dict[str, Any], **kw: Any
) -> sim_calibrate.BookTermsFit:
    return sim_calibrate.fit_book(
        h["rows"],
        h["observed"],
        params,
        flow=h["flow"],
        runs=h["runs"],
        air=h["air"],
        **kw,
    )


SITE = site_example_params()
NO_BASE = replace(SITE, circulation=None)
#: Book terms other than the site's: a refit should find them.
OTHER = replace(
    SITE.book_terms(),
    hp_btu_per_h=4600.0,
    hp_btu_per_h_per_f=40.0,
    ua_btu_per_h_f=3.6,
)


def assert_book(got: BookParams, want: BookParams) -> None:
    assert got.hp_btu_per_h == pytest.approx(want.hp_btu_per_h, rel=0.01)
    assert got.hp_btu_per_h_per_f == pytest.approx(
        want.hp_btu_per_h_per_f, abs=2.0
    )
    assert got.ua_btu_per_h_f == pytest.approx(want.ua_btu_per_h_f, abs=0.05)


class TestTheBook:
    def test_it_finds_the_books_terms(self) -> None:
        """No pump: the compressor's rate and its slope with the air,
        and the standby UA, walked apart from the base's."""
        h = no_pump(NO_BASE, 16, truth=OTHER)
        got = fit(NO_BASE, h)
        assert got.kept == "refit", got.why
        assert_book(got.book, OTHER)
        assert got.circulation is None
        assert got.run_pairs == 0
        # The fields the book doesn't fit are the base's.
        assert got.book.draw_gpm == SITE.book.draw_gpm
        assert got.book.max_anchor_age_h == SITE.book.max_anchor_age_h

    def test_the_air_never_moving_holds_the_slope(self) -> None:
        h = no_pump(NO_BASE, 16, truth=OTHER)
        # Read as if the air never left 65 °F: the slope is the base's.
        got = fit(NO_BASE, h | {"air": [(T0, AIR_F)]})
        assert got.book.hp_btu_per_h_per_f == SITE.book.hp_btu_per_h_per_f

    def test_too_few_pairs_keeps_the_base(self) -> None:
        h = no_pump(NO_BASE, 8, truth=OTHER)
        got = fit(NO_BASE, h)
        assert got.kept == "base"
        assert got.book == NO_BASE.book
        assert got.error_btu is None
        assert "10 needed" in got.why

    def test_a_term_on_its_bound_is_no_fit(self) -> None:
        """Walked with a UA of 30, past its bound of 20: the book
        misses something the UA can't take, so the base is kept."""
        truth = replace(OTHER, ua_btu_per_h_f=30.0)
        h = no_pump(NO_BASE, 16, truth=truth)
        got = fit(NO_BASE, h)
        assert got.kept == "base"
        assert "ua_btu_per_h_f" in got.why
        assert "bound" in got.why

    def test_no_meter_keeps_the_base(self) -> None:
        h = history(NO_BASE, 16, 150.0)
        got = fit(NO_BASE, h | {"flow": []})
        assert got.kept == "base"
        assert "no meter flow" in got.why

    def test_the_book_round_trips(self) -> None:
        from nwp500.sim.params import params_from_document, params_to_document

        got = fit(SITE, history(SITE, 16, 150.0, truth=OTHER))
        params = replace(SITE, book=got.book, circulation=got.circulation)
        assert params_from_document(params_to_document(params)) == params


class TestTheLoop:
    def test_it_finds_the_loss_the_runs_took(self) -> None:
        got = fit(NO_BASE, history(NO_BASE, 16, 150.0, truth=OTHER))
        assert got.kept == "refit", got.why
        assert got.circulation is not None
        assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
        assert_book(got.book, OTHER)
        assert got.circulation.meter_share == 1.0
        assert got.circulation.flow_gpm == pytest.approx(RUN_GPM)
        assert got.circulation.displaced_gal == SITE_CIRCULATION.displaced_gal
        assert got.runs == 16
        # An anchor after the opening recovery and after each cycle's.
        assert (got.pairs, got.run_pairs) == (16, 16)
        assert got.error_btu == pytest.approx(0.0, abs=50.0)
        assert "one installation's" in got.why

    def test_a_meter_that_misses_the_runs_prices_them_nominally(
        self,
    ) -> None:
        """With the meter reading nothing, each run is priced at the
        nominal flow: the loss per minute is what the book reads."""
        got = fit(NO_BASE, history(NO_BASE, 16, 150.0, meter_sees=False))
        assert got.circulation is not None
        assert got.circulation.meter_share == 0.0
        assert got.circulation.flow_gpm == sim_calibrate.NOMINAL_CIRCULATION_GPM
        # Walked at 1 gal/min, the nominal flow.
        assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
        assert "doesn't see" in got.why

    def test_a_draw_during_a_run_is_a_draw(self) -> None:
        """A tap open for a minute of each run reads over the run's own
        flow: not the run's flow, and booked as a draw, not as the
        run's loss."""
        got = fit(NO_BASE, history(NO_BASE, 16, 150.0, tap_gpm=2.0))
        assert got.circulation is not None
        assert got.circulation.flow_gpm == pytest.approx(RUN_GPM)
        assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)

    def test_a_missing_meter_reading_is_none(self) -> None:
        h = history(NO_BASE, 16, 150.0)
        flow: list[Any] = [*h["flow"], (T0 + timedelta(seconds=5), None)]
        got = fit(NO_BASE, h | {"flow": sorted(flow, key=lambda r: r[0])})
        assert got.circulation is not None
        assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)

    def test_an_outage_after_the_history_changes_nothing(self) -> None:
        """Heard until 80 h, the meter and the pump read on: an outage
        at 90 h doesn't book the unheard 10 h."""
        h = history(NO_BASE, 16, 150.0)
        end = T0 + timedelta(hours=80)
        h["observed"] = [t for t in h["observed"] if t <= end]
        rows = replace(
            h["rows"],
            outages=((end + timedelta(hours=10), end + timedelta(hours=11)),),
        )
        want = fit(NO_BASE, h)
        got = fit(NO_BASE, h | {"rows": rows})
        assert got.pairs == want.pairs

    def test_a_meter_gap_breaks_the_book(self) -> None:
        """A draw the meter missed, between two anchors with a run: no
        pair spans the gap."""
        h = history(NO_BASE, 16, 150.0, draw_at_h=44.0)
        whole = fit(NO_BASE, h)
        gap = (T0 + timedelta(hours=43.5), T0 + timedelta(hours=44.7))
        flow = [r for r in h["flow"] if not gap[0] < r[0] < gap[1]]
        got = fit(NO_BASE, h | {"flow": flow})
        assert got.pairs == whole.pairs - 1

    def test_the_refit_replaces_a_worse_base(self) -> None:
        got = fit(SITE, history(SITE, 16, 150.0))
        assert got.kept == "refit"
        assert got.circulation is not None
        assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
        # The base's own volume and gap are kept.
        assert got.circulation.displaced_gal == SITE_CIRCULATION.displaced_gal
        assert "kept from the base" in got.why

    def test_a_better_base_is_kept(self) -> None:
        """The held-out runs took 100 BTU/gal, the earlier 150: a base
        at 100 books them better than the refit."""
        base = CirculationParams(
            displaced_gal=5.0,
            flow_gpm=RUN_GPM,
            loss_btu_per_gal=100.0,
            meter_share=1.0,
        )
        params = replace(NO_BASE, circulation=base)
        got = fit(
            params,
            history(params, 16, 150.0, late_loss=100.0, late_from=13),
        )
        assert got.kept == "base"
        assert got.circulation == base
        assert got.book == params.book

    def test_too_few_days_holds_the_bases_loop(self) -> None:
        """8 runs over 2 days: the loop isn't read, its terms are the
        base's, and too few pairs keep the book's too."""
        got = fit(SITE, history(SITE, 8, 150.0))
        assert got.kept == "base"
        assert got.circulation == SITE.circulation
        assert "8 clean runs over 2 days" in got.why

    def test_too_few_run_pairs_leaves_the_loss(self) -> None:
        """10 runs over 5 days, two of them between the same anchors:
        the loop's flow is read, but 9 pairs with a run are too few to
        fit its loss on. With no base to price them, those pairs are
        left out, and the book is refitted on the rest."""
        h = history(NO_BASE, 24, 0.0, truth=OTHER, meter_sees=False)
        # Runs the meter doesn't see and that take nothing.
        runs = h["runs"][::2][:9]
        a = runs[0][0] + timedelta(minutes=40)
        runs = sorted([*runs, (a, a + timedelta(minutes=10))])
        got = fit(NO_BASE, h | {"runs": runs})
        assert got.circulation is None
        assert got.run_pairs == 0
        assert "9 pairs with a run: 10 needed" in got.why
        assert got.kept == "refit", got.why
        assert_book(got.book, OTHER)

    def test_a_loss_on_its_bound_leaves_the_book_refitted(self) -> None:
        """Ten runs that took nothing: the loss falls on its bound of 0,
        which is no fit of the loop, but the book is refitted on the
        pairs without a run."""
        h = history(NO_BASE, 24, 0.0, truth=OTHER, meter_sees=False)
        got = fit(NO_BASE, h | {"runs": h["runs"][::2][:10]})
        assert got.circulation is None
        assert "the loop's loss on its bound" in got.why
        assert got.kept == "refit", got.why
        assert_book(got.book, OTHER)

    def test_a_silence_breaks_the_book(self) -> None:
        h = history(NO_BASE, 16, 150.0)
        gap = (T0 + timedelta(hours=40), T0 + timedelta(hours=44))
        whole = fit(NO_BASE, h)
        h["observed"] = [t for t in h["observed"] if not gap[0] < t < gap[1]]
        got = fit(NO_BASE, h)
        assert got.pairs < whole.pairs

    def test_the_document(self) -> None:
        got = fit(NO_BASE, history(NO_BASE, 16, 150.0))
        doc = got.as_document()
        assert CirculationParams(**doc["circulation"]) == got.circulation
        assert BookParams(**doc["book"]) == got.book
        assert doc["kept"] == "refit"
        assert doc["run_pairs"] == got.run_pairs
        assert np.isfinite(doc["error_btu"])

    def test_a_loss_on_its_bound_is_no_fit(self) -> None:
        """Runs walked at 800 BTU/gal: the fit reaches the loss's bound
        of 500, which says the book misses something, not what a run
        takes."""
        got = fit(SITE, history(SITE, 16, 800.0))
        assert got.kept == "base"
        assert got.circulation == SITE.circulation
        assert "bound" in got.why
        got = fit(NO_BASE, history(NO_BASE, 16, 800.0))
        assert (got.kept, got.circulation) == ("base", None)

    def test_a_first_fit_needs_pairs_to_judge_it_by(self) -> None:
        """12 clean runs over 3 days, but the heater unheard for a day:
        too few pairs to hold any out, so nothing is adopted."""
        h = history(NO_BASE, 12, 150.0)
        h["observed"] = [
            t
            for t in h["observed"]
            if not T0 + timedelta(hours=6) < t < T0 + timedelta(hours=40)
        ]
        got = fit(NO_BASE, h)
        assert got.runs == 12
        assert got.pairs < 10
        assert (got.kept, got.circulation) == ("base", None)
        assert "10 needed" in got.why

    def test_a_reporting_meter_carries_runs_into_its_reports(self) -> None:
        """A meter reporting volumes every 30 s, off the runs' minutes:
        the reports either side of a run carry its water, which isn't a
        draw within ``METER_LAG`` of it."""
        h = history(NO_BASE, 16, 150.0, reported=True)
        got = fit(NO_BASE, h)
        assert got.circulation is not None
        assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
        assert_book(got.book, SITE.book)
        # Without it, the runs' water either side reads as draws, and
        # the standby UA takes their heat.
        unlagged = fit(NO_BASE, h, meter_lag=timedelta(0))
        assert unlagged.book.ua_btu_per_h_f < SITE.book.ua_btu_per_h_f - 0.3

    def test_a_tap_just_after_a_run_keeps_its_water(self) -> None:
        """A 2 gal/min tap for the minute after each run, on a meter
        reporting volumes: only the run's own water past its edge is
        circulation, and the tap is booked as a draw. The report over the
        edge spreads 0.04 gal of the tap into the run's last step under
        the draw line, which the book can't see: the UA takes it, about
        0.13 BTU/h/°F."""
        h = history(NO_BASE, 16, 150.0, reported=True, after_gpm=2.0)
        got = fit(NO_BASE, h)
        assert got.circulation is not None
        assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
        assert got.book.ua_btu_per_h_f == pytest.approx(
            SITE.book.ua_btu_per_h_f, abs=0.15
        )


def test_the_pairs_errors_are_linear_in_the_terms() -> None:
    """``RecordedBook.pair_terms`` gives each pair's error as the book
    books it, for any terms."""
    from nwp500.sim import calibration as cal

    h = history(SITE, 6, 150.0, truth=OTHER)
    terms = SITE.circulation
    assert terms is not None
    steps = sa.book_steps_from_changes(
        h["rows"],
        start=T0,
        end=h["observed"][-1],
        flow=h["flow"],
        circulation=h["runs"],
        circulation_flow=sa.run_flow(h["runs"], terms.flow_gpm),
        air=h["air"],
        params=SITE,
    )
    p = SITE.book_terms()
    book = cal.RecordedBook(steps, p, terms, start=T0)
    pairs = book.reanchors(p.max_anchor_age_h)
    k, x = book.pair_terms(p, pairs)
    for hp, slope, ua, loss in ((4000, 50, 2, 100), (5000, -10, 6, 300)):
        q = replace(
            p, hp_btu_per_h=hp, hp_btu_per_h_per_f=slope, ua_btu_per_h_f=ua
        )
        assert k + x @ np.array([hp, slope, ua, loss]) == pytest.approx(
            book.errors(q, loss, pairs)
        )


def test_a_short_runs_water_past_both_edges_is_circulation() -> None:
    """A 60 s run at 1 gal/min, on 30 s volume reports 15 s off it, with
    a 90 s lag: the run's water either side of it is all circulation,
    none of it a draw."""
    from nwp500.sim.book import house_gpm

    terms = SITE.circulation
    assert terms is not None
    a = T0 + timedelta(minutes=30)
    run = (a, a + timedelta(minutes=1))
    n = 6 * 60
    truth = [
        (T0 + i * STEP, 1.0 if run[0] <= T0 + i * STEP < run[1] else 0.0)
        for i in range(n)
    ]
    steps = sa.book_steps_from_changes(
        sa.ChangeRows(upper_f=[(T0, 120.0)], lower_f=[(T0, 120.0)]),
        start=T0,
        end=T0 + n * STEP,
        flow=reports(truth),
        circulation=[run],
        circulation_flow=sa.run_flow([run], terms.flow_gpm),
        meter_lag=timedelta(seconds=90),
        params=SITE,
    )
    house = sum(house_gpm(s, terms) * s.seconds / 60 for s in steps)
    assert house == pytest.approx(0.0, abs=1e-9)


def test_the_air_at_one_temperature_holds_the_slope() -> None:
    """The air always at 70 °F: the slope only rescales the heat rate,
    so it is held at the base, and the heat rate takes the rest."""
    got = fit(NO_BASE, no_pump(NO_BASE, 16, truth=OTHER, air_f=70.0))
    assert got.kept == "refit", got.why
    assert got.book.hp_btu_per_h_per_f == SITE.book.hp_btu_per_h_per_f
    want = OTHER.hp_btu_per_h + 5 * OTHER.hp_btu_per_h_per_f
    rate = got.book.hp_btu_per_h + 5 * got.book.hp_btu_per_h_per_f
    assert rate == pytest.approx(want, rel=0.001)
    assert got.book.ua_btu_per_h_f == pytest.approx(OTHER.ua_btu_per_h_f)


def test_a_loss_the_pairs_cant_tell_apart_is_no_fit() -> None:
    """Each run a quarter of its cycle's recovery: the runs' gallons
    follow the compressor's hours, so the loss can't be told from the
    heat rate. It is no fit, and the book is refitted without the runs'
    pairs rather than with a loss of 0."""
    h = history(NO_BASE, 16, 150.0, tied=True)
    got = fit(NO_BASE, h)
    assert got.circulation is None
    assert "can't be told from the book's terms" in got.why


def test_a_late_probe_starts_the_book_where_both_read() -> None:
    """The lower probe's history starts 3 h late, and runs come every
    other cycle: each pair's instants are its own, so the pairs with a
    run are told from those without and the loss is found."""
    h = history(NO_BASE, 24, 150.0, run_every=2)
    late = T0 + timedelta(hours=3)
    rows = replace(
        h["rows"], lower_f=[r for r in h["rows"].lower_f if r[0] >= late]
    )
    got = fit(NO_BASE, h | {"rows": rows})
    assert got.circulation is not None, got.why
    assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
    # Readings before then that are none: the same.
    unread: list[Any] = [(T0, None), (T0 + timedelta(hours=1), math.nan)]
    rows = replace(rows, lower_f=[*unread, *rows.lower_f])
    got = fit(NO_BASE, h | {"rows": rows})
    assert got.circulation is not None, got.why
    assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
    assert_book(got.book, SITE.book)


def test_runs_without_terms_still_break_the_quiet() -> None:
    """Runs in the first 9 of 24 cycles, unseen by the meter and too
    few to read the loop by, with no base: each run still breaks the
    quiet before it, so every pair across one has a run in it and is
    left out, and the book is refitted on the 15 without."""
    h = history(NO_BASE, 24, 150.0, meter_sees=False, runs_in=9, truth=OTHER)
    got = fit(NO_BASE, h)
    assert got.circulation is None
    assert (got.pairs, got.run_pairs) == (15, 0)
    assert got.kept == "refit", got.why
    assert_book(got.book, OTHER)


def test_runs_too_short_to_read_clear_of_their_edges() -> None:
    """Minute-long runs on a meter reporting every 30 s: every reading
    in a run is within a lag of an edge, carrying water from outside
    it, so none reads the run's flow, and no run is clean."""
    got = fit(NO_BASE, history(NO_BASE, 16, 150.0, reported=True, run_min=1))
    assert got.runs == 0
    assert got.circulation is None
    assert "0 clean runs" in got.why


def test_a_probe_gap_breaks_the_book() -> None:
    """The lower probe unread from 2 h to 5 h, runs every other cycle:
    no pair crosses the gap, and the steps after it keep their own
    instants, so the loss is found."""
    h = history(NO_BASE, 24, 150.0, run_every=2)
    gap = (T0 + timedelta(hours=2), T0 + timedelta(hours=5))
    lower: list[Any] = [
        *(r for r in h["rows"].lower_f if r[0] < gap[0]),
        (gap[0], None),
        *(r for r in h["rows"].lower_f if r[0] >= gap[1]),
    ]
    got = fit(NO_BASE, h | {"rows": replace(h["rows"], lower_f=lower)})
    assert got.circulation is not None, got.why
    assert got.circulation.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
    assert_book(got.book, SITE.book)


def test_naive_probe_instants_are_read_as_the_adapters_read_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe instants without a zone, read in the local zone as the
    book's adapters read them: here UTC, so the fit is the zoned one."""
    import time

    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        h = history(NO_BASE, 16, 150.0)
        naive = replace(
            h["rows"],
            upper_f=[(t.replace(tzinfo=None), v) for t, v in h["rows"].upper_f],
            lower_f=[(t.replace(tzinfo=None), v) for t, v in h["rows"].lower_f],
        )
        assert fit(NO_BASE, h | {"rows": naive}) == fit(NO_BASE, h)
    finally:
        monkeypatch.undo()
        time.tzset()


def test_whole_number_base_terms_fit_fractional_ones() -> None:
    """A base whose book terms and loop loss are whole numbers: the
    refit's UA of 3.6 stays 3.6."""
    book = replace(
        SITE.book,
        hp_btu_per_h=4252,
        hp_btu_per_h_per_f=76,
        ua_btu_per_h_f=3,
    )
    assert SITE.circulation is not None
    loop = replace(SITE.circulation, loss_btu_per_gal=100)
    params = replace(SITE, book=book, circulation=loop)
    got = fit(params, no_pump(params, 16, truth=OTHER))
    assert got.kept == "refit", got.why
    assert_book(got.book, OTHER)


def test_runs_mixing_zoned_and_naive_instants() -> None:
    """``run_flow`` takes runs as the book does: a naive instant in the
    local zone, sorted with zoned ones by the instant it names."""
    a = T0 + timedelta(hours=2)
    naive = (a.astimezone().replace(tzinfo=None), a + timedelta(minutes=1))
    zoned = (T0, T0 + timedelta(minutes=1))
    got = sa.run_flow([naive, zoned], 1.0)
    assert [t for t, _ in got] == sorted(t for t, _ in got)
    assert got[0][0] == T0
    assert got[-1][0] == a + timedelta(seconds=50)


def test_a_probe_gap_across_the_repeated_hour() -> None:
    """Across a clock set back, an unread reading at 01:50 EDT and the
    next at 01:10 EST, 20 minutes later: the gap is those 20 minutes,
    whatever the wall clock says."""
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    before = datetime(2026, 11, 1, 1, 0, tzinfo=ny)
    gone = datetime(2026, 11, 1, 1, 50, tzinfo=ny)
    back = datetime(2026, 11, 1, 1, 10, fold=1, tzinfo=ny)
    end = datetime(2026, 11, 2, tzinfo=UTC)
    got = sim_calibrate._unread_spans(  # pyright: ignore[reportPrivateUsage]
        [(before, 120.0), (gone, None), (back, 121.0)], end
    )
    assert got == [(gone.astimezone(UTC), back.astimezone(UTC))]
    assert got[0][1] - got[0][0] == timedelta(minutes=20)


def test_a_probe_gap_mixing_zoned_and_naive_instants() -> None:
    a = T0 + timedelta(hours=1)
    naive = (a.astimezone().replace(tzinfo=None), math.nan)
    got = sim_calibrate._unread_spans(  # pyright: ignore[reportPrivateUsage]
        [(T0, 120.0), naive, (a + timedelta(minutes=5), 121.0)],
        T0 + timedelta(hours=2),
    )
    assert got == [(a, a + timedelta(minutes=5))]


def test_the_fits_balance_is_the_books() -> None:
    """With an inlet of 50 °F, off the book's 70 °F reference, and a
    tap open in each run: each pair's error is the book's own heat
    (``step_heat_btu``) between its anchors less the probes'."""
    from nwp500.sim import calibration as cal
    from nwp500.sim.book import step_heat_btu

    h = history(SITE, 6, 150.0, tap_gpm=2.0)
    terms = SITE.circulation
    assert terms is not None
    steps = sa.book_steps_from_changes(
        h["rows"],
        start=T0,
        end=h["observed"][-1],
        flow=h["flow"],
        circulation=h["runs"],
        circulation_flow=sa.run_flow(h["runs"], terms.flow_gpm),
        inlet=[(T0, 50.0)],
        air=h["air"],
        params=SITE,
    )
    p = replace(SITE.book_terms(), element_w=0.0)
    book = cal.RecordedBook(steps, p, terms, start=T0)
    pairs = book.reanchors(p.max_anchor_age_h)
    assert pairs
    assert any(book.draw[a0:a1].sum() > 0 for a0, a1 in pairs)
    heat = book.probe_heat(p)
    want = [
        heat[a0]
        + sum(step_heat_btu(s, p, terms) for s in steps[a0:a1])
        - heat[a1]
        for a0, a1 in pairs
    ]
    assert book.errors(p, terms.loss_btu_per_gal, pairs) == pytest.approx(want)
    k, x = book.pair_terms(p, pairs)
    got = k + x @ np.array(
        [
            p.hp_btu_per_h,
            p.hp_btu_per_h_per_f,
            p.ua_btu_per_h_f,
            terms.loss_btu_per_gal,
        ]
    )
    assert got == pytest.approx(want)


def test_two_close_runs_share_the_water_between_them() -> None:
    """Two 80 s runs at 2 gal/min, 10 s apart, on 30 s volume reports
    15 s off them, with a 90 s lag: their water either side, and in the
    gap, is all circulation, none of it a draw."""
    from nwp500.sim.book import house_gpm

    assert SITE.circulation is not None
    terms = replace(SITE.circulation, flow_gpm=2.0, meter_share=1.0)
    params = replace(SITE, circulation=terms)
    a = T0 + timedelta(minutes=30)
    runs = [
        (a, a + timedelta(seconds=80)),
        (a + timedelta(seconds=90), a + timedelta(seconds=170)),
    ]
    n = 6 * 60
    truth = [
        (
            T0 + i * STEP,
            2.0 if any(x <= T0 + i * STEP < y for x, y in runs) else 0.0,
        )
        for i in range(n)
    ]
    steps = sa.book_steps_from_changes(
        sa.ChangeRows(upper_f=[(T0, 120.0)], lower_f=[(T0, 120.0)]),
        start=T0,
        end=T0 + n * STEP,
        flow=reports(truth),
        circulation=runs,
        circulation_flow=sa.run_flow(runs, terms.flow_gpm),
        meter_lag=timedelta(seconds=90),
        params=params,
    )
    house = sum(house_gpm(s, terms) * s.seconds / 60 for s in steps)
    assert house == pytest.approx(0.0, abs=1e-9)


def every(
    flow: list[tuple[datetime, float]], period_s: int, offset_s: int = 0
) -> list[tuple[datetime, float]]:
    """``flow`` as a meter reporting its volume every ``period_s`` (a
    multiple of 5 s), the reports ``offset_s`` after the first step,
    each spread evenly back over the period it closes in the book's
    10 s steps."""
    halves = [v for _, v in flow for _ in range(2)]
    spread = [0.0] * len(halves)
    k = period_s // 5
    for end in range(offset_s // 5 or k, len(halves) + 1, k):
        lo = max(end - k, 0)
        mean = sum(halves[lo:end]) / k
        for i in range(lo, end):
            spread[i] = mean
    return [
        (t, (spread[2 * i] + spread[2 * i + 1]) / 2)
        for i, (t, _) in enumerate(flow)
    ]


@pytest.mark.parametrize("tap", ["before", "after", None])
def test_close_runs_leave_a_tap_its_water(tap: str | None) -> None:
    """Two 15 min runs at 2 gal/min, 100 s apart, on 90 s volume
    reports aligned with the first, and a 2 gal/min tap for 30 s just
    before the first or after the second: the tap's gallon is the only
    household water, each edge taking back only its own run's."""
    from nwp500.sim.book import house_gpm

    assert SITE.circulation is not None
    terms = replace(SITE.circulation, flow_gpm=2.0, meter_share=1.0)
    params = replace(SITE, circulation=terms)
    a = T0 + timedelta(minutes=30)
    runs = [
        (a, a + timedelta(minutes=15)),
        (
            a + timedelta(minutes=15, seconds=100),
            a + timedelta(minutes=30, seconds=100),
        ),
    ]
    taps = {
        "before": (a - timedelta(seconds=30), a),
        "after": (runs[1][1], runs[1][1] + timedelta(seconds=30)),
    }
    n = 6 * 90

    def at(t: datetime) -> float:
        pump = 2.0 if any(x <= t < y for x, y in runs) else 0.0
        tapped = tap is not None and taps[tap][0] <= t < taps[tap][1]
        return pump + (2.0 if tapped else 0.0)

    truth = [(T0 + i * STEP, at(T0 + i * STEP)) for i in range(n)]
    steps = sa.book_steps_from_changes(
        sa.ChangeRows(upper_f=[(T0, 120.0)], lower_f=[(T0, 120.0)]),
        start=T0,
        end=T0 + n * STEP,
        flow=every(truth, 90),
        circulation=runs,
        circulation_flow=sa.run_flow(runs, terms.flow_gpm),
        meter_lag=timedelta(seconds=90),
        params=params,
    )
    # Where the household water is: before the first run, after the
    # last, or anywhere else.
    where = {"before": 0.0, "after": 0.0, None: 0.0}
    for i, s in enumerate(steps):
        t = T0 + i * STEP
        side = (
            "before" if t < runs[0][0] else "after" if t >= runs[1][1] else None
        )
        where[side] += house_gpm(s, terms) * s.seconds / 60
    want = {"before": 0.0, "after": 0.0, None: 0.0}
    if tap is not None:
        want[tap] = 1.0
    assert where == pytest.approx(want, abs=1e-9)


def test_too_few_run_pairs_keep_the_loops_measured_flow() -> None:
    """12 clean runs read the loop at 1 gal/min, seen by the meter,
    but a silence leaves 8 pairs with a run, too few to fit its loss:
    the loss is the base's, and the flow and share are the runs'."""
    base = CirculationParams(
        displaced_gal=5.0, flow_gpm=0.5, loss_btu_per_gal=150.0, meter_share=0.0
    )
    params = replace(NO_BASE, circulation=base)
    h = history(params, 24, 150.0, runs_in=12, truth=OTHER)
    h["observed"] = [
        t
        for t in h["observed"]
        if not T0 + timedelta(hours=6) < t < T0 + timedelta(hours=24)
    ]
    got = fit(params, h)
    assert got.run_pairs < sim_calibrate.MIN_RUN_PAIRS
    assert got.kept == "refit", got.why
    assert got.circulation == replace(base, flow_gpm=RUN_GPM, meter_share=1.0)
    assert_book(got.book, OTHER)
