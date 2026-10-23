"""The heat book's terms and the circulation loop's book circuit volume
from the book's re-anchors (``sim_calibrate.fit_book``).

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
from nwp500.sim.params import BookParams, HeaterParams
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


#: The loop's flow during a run, gal/min.
RUN_GPM = 2.0
#: The circuit volume the runs are walked with, gal: each run takes its
#: first 4 gal at the tank less the air.
CIRCUIT = 4.0


def no_pump(params: HeaterParams, cycles: int, **kw: Any) -> dict[str, Any]:
    """A history with no circulation: no runs, nothing taken by them."""
    return history(params, cycles, 0.0, **kw) | {"runs": []}


def history(
    params: HeaterParams,
    cycles: int,
    circuit: float,
    *,
    late_circuit: float | None = None,
    late_from: int = 0,
    tap_gpm: float = 0.0,
    draw_at_h: float | None = None,
    truth: BookParams | None = None,
    air_f: float | None = None,
    tied: bool = False,
    run_every: int = 1,
    runs_in: int | None = None,
    run_min: int | None = None,
    same: bool = False,
) -> dict[str, Any]:
    """A history of ``cycles`` six-hour cycles walked by the book's own
    balance (``truth``, else ``params``' book), each run taking its
    first ``circuit`` gallons at the tank less the air
    (``late_circuit`` from cycle ``late_from`` on), the air at
    ``air_f`` throughout or else varying by cycle, and what ``fit_book``
    takes: the draws, and the runs with their flow. ``tied`` makes each
    run a quarter of its cycle's recovery, so the runs' gallons follow
    the compressor's hours."""

    def runs_to(cycle: int) -> int:
        if same:
            return RUN[1]
        if run_min is not None:
            return RUN[0] + run_min
        if tied:
            return RUN[0] + (recovers_to(cycle) - RECOVERY[0]) // 4
        return run_end(cycle)

    def recovers_to(cycle: int) -> int:
        if same:
            return RECOVERY[1]
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
    run_gal = 0.0
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
        # A tap open for the run's first minute.
        tap = tap_gpm if minute == RUN[0] else 0.0
        if draw_at_h is not None and 0 <= (i * 10 / 3600 - draw_at_h) < 5 / 60:
            # A five-minute draw at 2 gal/min.
            tap = 2.0
        if running and minute == RUN[0] and i % 6 == 0:
            runs.append((t, t + timedelta(minutes=runs_to(cycle) - RUN[0])))
        probe.append((t, temp))
        comp.append((t, heating))
        flow.append((t, tap))
        volume = (
            circuit
            if late_circuit is None or cycle < late_from
            else late_circuit
        )
        circulated = RUN_GPM * per_step if running else 0.0
        priced = min(run_gal + circulated, volume) - min(run_gal, volume)
        run_gal = run_gal + circulated if running else 0.0
        e = (
            heating * (p.hp_btu_per_h + p.hp_btu_per_h_per_f * (air - 65.0)) * h
            - priced * WATER_BTU_PER_GAL_F * max(temp - air, 0.0)
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


def fit(
    params: HeaterParams, h: dict[str, Any], **kw: Any
) -> sim_calibrate.BookTermsFit:
    return sim_calibrate.fit_book(
        h["rows"],
        h["observed"],
        params,
        flow=h["flow"],
        runs=h["runs"],
        circulation_flow=h.get(
            "circulation_flow", sa.run_flow(h["runs"], RUN_GPM)
        ),
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
        assert got.loss_btu_per_gal is None
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
        # The base's error on the held-out pairs.
        assert got.error_btu is not None
        assert math.isfinite(got.error_btu)

    def test_no_meter_keeps_the_base(self) -> None:
        h = history(NO_BASE, 16, CIRCUIT)
        got = fit(NO_BASE, h | {"flow": []})
        assert got.kept == "base"
        assert "no draws" in got.why

    def test_the_book_round_trips(self) -> None:
        from nwp500.sim.params import params_from_document, params_to_document

        got = fit(SITE, history(SITE, 16, CIRCUIT, truth=OTHER))
        assert got.book_circuit_gal is not None
        loop = replace(SITE_CIRCULATION, book_circuit_gal=got.book_circuit_gal)
        params = replace(SITE, book=got.book, circulation=loop)
        assert params_from_document(params_to_document(params)) == params


class TestTheLoop:
    def test_it_finds_the_circuit_the_runs_took(self) -> None:
        """Runs that took their first 4 gal, with no base: the volume is
        found."""
        got = fit(NO_BASE, history(NO_BASE, 16, CIRCUIT, truth=OTHER))
        assert got.kept == "refit", got.why
        assert got.book_circuit_gal == pytest.approx(CIRCUIT, abs=0.05)
        assert_book(got.book, OTHER)
        # An anchor after the opening recovery and after each cycle's.
        assert (got.pairs, got.run_pairs) == (16, 16)
        assert got.error_btu == pytest.approx(0.0, abs=50.0)

    def test_a_draw_during_a_run_is_a_draw(self) -> None:
        """A tap open for a minute of each run is booked as a draw, not
        as the run's loss."""
        got = fit(SITE, history(SITE, 16, CIRCUIT, tap_gpm=2.0))
        assert got.book_circuit_gal == pytest.approx(CIRCUIT, abs=0.05)

    def test_a_missing_draws_reading_is_none(self) -> None:
        h = history(SITE, 16, CIRCUIT)
        flow: list[Any] = [*h["flow"], (T0 + timedelta(seconds=5), None)]
        got = fit(SITE, h | {"flow": sorted(flow, key=lambda r: r[0])})
        assert got.book_circuit_gal == pytest.approx(CIRCUIT, abs=0.05)

    def test_an_outage_after_the_history_changes_nothing(self) -> None:
        """Heard until 80 h, the draws and the pump read on: an outage
        at 90 h doesn't book the unheard 10 h."""
        h = history(SITE, 16, CIRCUIT)
        end = T0 + timedelta(hours=80)
        h["observed"] = [t for t in h["observed"] if t <= end]
        rows = replace(
            h["rows"],
            outages=((end + timedelta(hours=10), end + timedelta(hours=11)),),
        )
        want = fit(SITE, h)
        got = fit(SITE, h | {"rows": rows})
        assert got.pairs == want.pairs

    def test_a_gap_in_the_draws_breaks_the_book(self) -> None:
        """A draw missing from the draws, between two anchors with a
        run: no pair spans the gap."""
        h = history(SITE, 16, CIRCUIT, draw_at_h=44.0)
        whole = fit(SITE, h)
        gap = (T0 + timedelta(hours=43.5), T0 + timedelta(hours=44.7))
        flow = [r for r in h["flow"] if not gap[0] < r[0] < gap[1]]
        got = fit(SITE, h | {"flow": flow})
        assert got.pairs == whole.pairs - 1

    def test_a_better_base_is_kept(self) -> None:
        """The held-out runs took 2.5 gal, the earlier 4: a base at 2.5
        books them better than the refit."""
        base = replace(SITE_CIRCULATION, book_circuit_gal=2.5)
        params = replace(NO_BASE, circulation=base)
        got = fit(
            params,
            history(params, 16, CIRCUIT, late_circuit=2.5, late_from=13),
        )
        assert got.kept == "base"
        assert got.book_circuit_gal == 2.5
        assert got.book == params.book

    def test_a_volume_on_its_bound_holds_the_bases(self) -> None:
        """Runs that took nothing: the volume falls on its bound of 0,
        which is no fit of the loop, so the base's is held."""
        got = fit(SITE, history(SITE, 16, 0.0))
        assert got.book_circuit_gal == SITE_CIRCULATION.book_circuit_gal
        assert "the book's circuit volume on its bound" in got.why

    def test_a_silence_breaks_the_book(self) -> None:
        h = history(SITE, 16, CIRCUIT)
        gap = (T0 + timedelta(hours=40), T0 + timedelta(hours=44))
        whole = fit(SITE, h)
        h["observed"] = [t for t in h["observed"] if not gap[0] < t < gap[1]]
        got = fit(SITE, h)
        assert got.pairs < whole.pairs

    def test_the_document(self) -> None:
        got = fit(SITE, history(SITE, 16, CIRCUIT))
        doc = got.as_document()
        assert doc["loss_btu_per_gal"] == got.loss_btu_per_gal
        assert doc["book_circuit_gal"] == got.book_circuit_gal
        assert BookParams(**doc["book"]) == got.book
        assert doc["kept"] == "refit"
        assert doc["run_pairs"] == got.run_pairs
        assert np.isfinite(doc["error_btu"])

    def test_a_volume_past_its_bound_is_no_fit(self) -> None:
        """Runs walked at 45 gal, more than any run pumps: the fit
        reaches the volume's bound of 30, which says the book misses
        something, not what a run takes."""
        got = fit(SITE, history(SITE, 16, 45.0))
        assert got.kept == "base"
        assert got.book_circuit_gal == SITE_CIRCULATION.book_circuit_gal
        assert "bound" in got.why
        got = fit(NO_BASE, history(NO_BASE, 16, 45.0))
        assert (got.kept, got.book_circuit_gal) == ("base", None)

    def test_a_first_fit_needs_pairs_to_judge_it_by(self) -> None:
        """12 runs over 3 days, but the heater unheard for a day: too
        few pairs to hold any out, so nothing is adopted."""
        h = history(SITE, 12, CIRCUIT)
        h["observed"] = [
            t
            for t in h["observed"]
            if not T0 + timedelta(hours=6) < t < T0 + timedelta(hours=40)
        ]
        got = fit(SITE, h)
        assert got.pairs < 10
        assert got.kept == "base"
        assert got.book_circuit_gal == SITE_CIRCULATION.book_circuit_gal
        assert "10 needed" in got.why


def test_the_pairs_errors_are_linear_in_the_terms() -> None:
    """``RecordedBook.pair_terms`` gives each pair's error as the book
    books it, for any terms."""
    from nwp500.sim import calibration as cal

    h = history(SITE, 6, CIRCUIT, truth=OTHER)
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
    kc, xc = book.pair_terms(p, pairs, CIRCUIT)
    for hp, slope, ua, loss in ((4000, 50, 2, 100), (5000, -10, 6, 300)):
        q = replace(
            p, hp_btu_per_h=hp, hp_btu_per_h_per_f=slope, ua_btu_per_h_f=ua
        )
        assert k + x @ np.array([hp, slope, ua, loss]) == pytest.approx(
            book.errors(q, loss, pairs)
        )
        # At a circuit volume, the loss column is none of it.
        assert kc + xc @ np.array([hp, slope, ua, loss]) == pytest.approx(
            book.errors(q, 0.0, pairs, CIRCUIT)
        )


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


def test_runs_that_follow_the_recoveries_still_fit() -> None:
    """Each run a quarter of its cycle's recovery: a loss per gallon
    would follow the compressor's hours, but each run's first gallons
    don't, so the volume is still told from the heat rate."""
    h = history(SITE, 16, CIRCUIT, tied=True)
    got = fit(SITE, h)
    assert got.book_circuit_gal == pytest.approx(CIRCUIT, abs=0.05)


def test_a_late_probe_starts_the_book_where_both_read() -> None:
    """The lower probe's history starts 3 h late, and runs come every
    other cycle: each pair's instants are its own, so the pairs with a
    run are told from those without and the loss is found."""
    h = history(SITE, 24, CIRCUIT, run_every=2)
    late = T0 + timedelta(hours=3)
    rows = replace(
        h["rows"], lower_f=[r for r in h["rows"].lower_f if r[0] >= late]
    )
    got = fit(SITE, h | {"rows": rows})
    assert got.book_circuit_gal == pytest.approx(CIRCUIT, abs=0.05)
    # Readings before then that are none: the same.
    unread: list[Any] = [(T0, None), (T0 + timedelta(hours=1), math.nan)]
    rows = replace(rows, lower_f=[*unread, *rows.lower_f])
    got = fit(SITE, h | {"rows": rows})
    assert got.book_circuit_gal == pytest.approx(CIRCUIT, abs=0.05)
    assert_book(got.book, SITE.book)


def test_runs_without_terms_still_break_the_quiet() -> None:
    """Runs in the first 9 of 24 cycles, with no base to price them:
    each run still breaks the quiet before it, so every pair across one
    has a run in it and is left out, and the book is refitted on the 15
    without."""
    h = history(NO_BASE, 24, CIRCUIT, runs_in=9, truth=OTHER)
    got = fit(NO_BASE, h)
    assert got.loss_btu_per_gal is None
    assert (got.pairs, got.run_pairs) == (15, 0)
    assert got.kept == "refit", got.why
    assert_book(got.book, OTHER)


def test_a_probe_gap_breaks_the_book() -> None:
    """The lower probe unread from 2 h to 5 h, runs every other cycle:
    no pair crosses the gap, and the steps after it keep their own
    instants, so the loss is found."""
    h = history(SITE, 24, CIRCUIT, run_every=2)
    gap = (T0 + timedelta(hours=2), T0 + timedelta(hours=5))
    lower: list[Any] = [
        *(r for r in h["rows"].lower_f if r[0] < gap[0]),
        (gap[0], None),
        *(r for r in h["rows"].lower_f if r[0] >= gap[1]),
    ]
    got = fit(SITE, h | {"rows": replace(h["rows"], lower_f=lower)})
    assert got.book_circuit_gal == pytest.approx(CIRCUIT, abs=0.05)
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
        h = history(SITE, 16, CIRCUIT)
        naive = replace(
            h["rows"],
            upper_f=[(t.replace(tzinfo=None), v) for t, v in h["rows"].upper_f],
            lower_f=[(t.replace(tzinfo=None), v) for t, v in h["rows"].lower_f],
        )
        assert fit(SITE, h | {"rows": naive}) == fit(SITE, h)
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

    h = history(SITE, 6, CIRCUIT, tap_gpm=2.0)
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
    circuit = terms.book_circuit_gal
    assert book.errors(
        p, terms.loss_btu_per_gal, pairs, circuit
    ) == pytest.approx(want)
    k, x = book.pair_terms(p, pairs, circuit)
    got = k + x @ np.array(
        [
            p.hp_btu_per_h,
            p.hp_btu_per_h_per_f,
            p.ua_btu_per_h_f,
            terms.loss_btu_per_gal,
        ]
    )
    assert got == pytest.approx(want)


def test_too_few_run_pairs_hold_the_bases_loss() -> None:
    """Runs in 12 cycles, but a silence leaves 8 pairs with a run, too
    few to fit the loop's loss on: the base's is held, and the book is
    refitted."""
    h = history(SITE, 24, CIRCUIT, runs_in=12, truth=OTHER)
    h["observed"] = [
        t
        for t in h["observed"]
        if not T0 + timedelta(hours=6) < t < T0 + timedelta(hours=24)
    ]
    got = fit(SITE, h)
    assert got.run_pairs < sim_calibrate.MIN_RUN_PAIRS
    assert "needed to fit the loop's circuit volume" in got.why
    assert got.book_circuit_gal == SITE_CIRCULATION.book_circuit_gal


def test_the_draws_hold_no_circulation() -> None:
    """A base whose meter share says a meter sees its runs, and a tap
    open in each run: the draws hold none of the runs' water, so the
    tap is all a draw, and the fit is the same as with no share."""
    h = history(SITE, 16, CIRCUIT, tap_gpm=2.0)
    for share in (0.0, 1.0):
        loop = replace(SITE_CIRCULATION, meter_share=share)
        got = fit(replace(SITE, circulation=loop), h)
        assert got.book_circuit_gal == pytest.approx(CIRCUIT, abs=0.05)


def test_a_run_without_its_flow_leaves_its_pairs_out() -> None:
    """Runs with no flow reading can't be priced: every pair with one
    is left out, and the loss is the base's."""
    h = history(SITE, 24, CIRCUIT, run_every=2, truth=OTHER)
    got = fit(SITE, h | {"circulation_flow": []})
    assert got.run_pairs == 0
    assert got.pairs == fit(SITE, h).pairs - fit(SITE, h).run_pairs
    assert got.book_circuit_gal == SITE_CIRCULATION.book_circuit_gal
    assert got.kept == "refit", got.why
    assert_book(got.book, OTHER)


def test_a_runs_first_reading_late_in_it_holds_from_its_start() -> None:
    """Each run's flow first read halfway through it: the run is booked
    at that flow from its start, as if read all through it."""
    h = history(SITE, 16, CIRCUIT)
    late = [(a + (b - a) / 2, RUN_GPM) for a, b in h["runs"]]
    got = fit(SITE, h | {"circulation_flow": late})
    assert got == fit(SITE, h)
    assert got.book_circuit_gal == pytest.approx(CIRCUIT, abs=0.05)


def test_readings_outside_the_runs_are_none_of_theirs() -> None:
    """The loop's flow read as 0 just before each run and never in it:
    the runs are unpriced, as with no readings at all, and still break
    the quiet anchors."""
    h = history(SITE, 24, CIRCUIT, run_every=2, truth=OTHER)
    zeros = [(a - timedelta(seconds=5), 0.0) for a, _ in h["runs"]]
    got = fit(SITE, h | {"circulation_flow": zeros})
    assert got == fit(SITE, h | {"circulation_flow": []})
    assert got.run_pairs == 0


def test_booking_takes_the_runs_flow_as_the_fit_does() -> None:
    """Runs at 2 and 1.5 gal/min, each first read halfway through it,
    with a 0 read before each: through ``run_readings`` the book takes
    each run at its own flow from its start, as if read all through
    it."""
    a = T0 + timedelta(minutes=30)
    runs = [
        (a, a + timedelta(minutes=15)),
        (a + timedelta(minutes=60), a + timedelta(minutes=75)),
    ]
    gpm = [2.0, 1.5]
    late: list[tuple[datetime, float | None]] = []
    for (x, y), v in zip(runs, gpm, strict=True):
        late += [(x - timedelta(seconds=5), 0.0), (x + (y - x) / 2, v)]
    full = [
        r
        for (x, y), v in zip(runs, gpm, strict=True)
        for r in sa.run_flow([(x, y)], v)
    ]

    def book(flow: list[tuple[datetime, float]]) -> list[Any]:
        return sa.book_steps_from_changes(
            sa.ChangeRows(upper_f=[(T0, 120.0)], lower_f=[(T0, 120.0)]),
            start=T0,
            end=T0 + timedelta(hours=2),
            flow=[(T0, 0.0)],
            circulation=runs,
            circulation_flow=flow,
            params=SITE,
        )

    assert book(sa.run_readings(runs, late)) == book(full)
    per_min = STEP.total_seconds() / 60
    gal = sum(
        s.circulation_gpm * per_min
        for s in book(sa.run_readings(runs, late))
        if s.circulating
    )
    assert gal == pytest.approx(15 * 2.0 + 15 * 1.5)


def test_a_volume_past_every_run_is_no_fit() -> None:
    """One-minute runs, 2 gal each, walked at a 4 gal circuit: every
    volume from 2 gal books them the same, so none is fitted and the
    base's is held."""
    got = fit(SITE, history(SITE, 16, CIRCUIT, run_min=1))
    assert got.book_circuit_gal == SITE_CIRCULATION.book_circuit_gal
    assert "past the most a run circulated" in got.why


def test_an_empty_window_books_nothing() -> None:
    runs = [(T0, T0 + timedelta(minutes=5))]
    steps = sa.book_steps_from_changes(
        sa.ChangeRows(upper_f=[(T0, 140.0)], lower_f=[(T0, 140.0)]),
        start=T0 + timedelta(minutes=2),
        end=T0 + timedelta(minutes=2),
        flow=[(T0, 0.0)],
        circulation=runs,
        circulation_flow=sa.run_flow(runs, 1.0),
        params=SITE,
    )
    assert steps == []


def test_a_long_run_outside_the_pairs_is_no_support() -> None:
    """The same one-minute runs, and one long run after the last anchor,
    in no pair: it can't say what the pairs can't."""
    h = history(SITE, 16, CIRCUIT, run_min=1)
    end = h["observed"][-1]
    h["runs"] = [*h["runs"], (end - timedelta(minutes=30), end)]
    got = fit(SITE, h)
    assert got.book_circuit_gal == SITE_CIRCULATION.book_circuit_gal
    assert "past the most a run circulated" in got.why


def test_the_same_cycle_every_time_is_no_fit() -> None:
    """Every cycle the same run after the same recovery, at one air:
    the heat rate can take up any volume, so none is fitted."""
    h = history(SITE, 16, CIRCUIT, same=True, air_f=AIR_F)
    got = fit(SITE, h)
    assert got.book_circuit_gal == SITE_CIRCULATION.book_circuit_gal
    assert "can't be told from the book's terms" in got.why
