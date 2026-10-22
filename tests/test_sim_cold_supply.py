"""The mains from an inlet probe's long-draw plateaus
(``sim.cold_supply``).

Held to its source by the parity check run with the port; these hold
its rules.
"""

from datetime import UTC, datetime, timedelta

from nwp500 import sim_adapters as sa
from nwp500.sim.book import full_tank_book
from nwp500.sim.cold_supply import (
    ColdSupply,
    ColdSupplyParams,
    on_the_mains,
    plateau_t_cold,
)
from nwp500.sim.params import BookParams

T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


Span = tuple[datetime, datetime]


def a_draw(
    minutes: int, at: datetime = T0, mains: float = 72.0
) -> tuple[list[tuple[datetime, float]], list[Span]]:
    """A draw of ``minutes``, the probe read every 10 s and settling
    from 77 degF to the mains after 5 minutes."""
    ticks = [at + timedelta(seconds=s) for s in range(0, 60 * minutes, 10)]
    probe = [
        (t, 77.0 if (t - at).total_seconds() < 300 else mains) for t in ticks
    ]
    return probe, [(at, at + timedelta(minutes=minutes))]


class TestThePlateau:
    def test_a_long_draw_reads_the_mains(self) -> None:
        probe, draws = a_draw(15)
        got = plateau_t_cold(probe, draws, [], T0 + timedelta(hours=1))
        assert (got.t_cold_f, got.draws) == (72.0, 1)

    def test_a_short_draw_or_one_with_circulation_has_none(self) -> None:
        probe, draws = a_draw(9)
        at = T0 + timedelta(hours=1)
        assert plateau_t_cold(probe, draws, [], at).t_cold_f is None
        probe, draws = a_draw(15)
        run = [(T0 + timedelta(minutes=3), T0 + timedelta(minutes=6))]
        assert plateau_t_cold(probe, draws, run, at).t_cold_f is None

    def test_unrecorded_is_not_idle(self) -> None:
        probe, draws = a_draw(15)
        at = T0 + timedelta(hours=1)
        assert plateau_t_cold(probe, draws, None, at).t_cold_f is None
        assert plateau_t_cold(probe, [], [], at).t_cold_f is None

    def test_old_or_implausible_draws_do_not_count(self) -> None:
        probe, draws = a_draw(15)
        late = T0 + timedelta(hours=80)
        assert plateau_t_cold(probe, draws, [], late).t_cold_f is None
        probe, draws = a_draw(15, mains=95.0)
        at = T0 + timedelta(hours=1)
        assert plateau_t_cold(probe, draws, [], at).t_cold_f is None

    def test_a_draw_still_running_ends_at_the_instant(self) -> None:
        """Nothing after ``at`` is read: a draw running at ``at`` is
        read to ``at``, and has a plateau once it has run long enough."""
        probe, draws = a_draw(15)
        assert (
            plateau_t_cold(probe, draws, [], T0 + timedelta(minutes=12))
        ).t_cold_f == 72.0
        assert (
            plateau_t_cold(probe, draws, [], T0 + timedelta(minutes=10))
        ).t_cold_f is None

    def test_the_adapter_reads_the_preferred_units(self) -> None:
        probe, draws = a_draw(15)
        got = sa.cold_supply(probe, at=T0 + timedelta(hours=1), draws=draws)
        assert got.t_cold_f == 72.0


class TestWhatTheReadingsAre:
    def test_a_missing_reading_is_left_out(self) -> None:
        probe, draws = a_draw(15)
        tail = T0 + timedelta(minutes=14)
        probe = [*probe, (tail + timedelta(seconds=5), float("nan"))]
        at = T0 + timedelta(hours=1)
        assert plateau_t_cold(probe, draws, [], at).t_cold_f == 72.0
        assert sa.cold_supply(probe, at=at, draws=draws).t_cold_f == 72.0

    def test_runs_closer_than_the_gap_are_one(self) -> None:
        """Runs closer than the gap are one run: a draw between them is a
        draw with circulation on."""
        probe, draws = a_draw(15)
        runs = [
            (T0 - timedelta(minutes=3), T0 - timedelta(minutes=1)),
            (T0 + timedelta(minutes=16), T0 + timedelta(minutes=17)),
        ]
        at = T0 + timedelta(hours=1)
        apart = plateau_t_cold(probe, draws, runs, at)
        assert apart.t_cold_f == 72.0
        wide = ColdSupplyParams(run_gap_s=1200.0)
        joined = plateau_t_cold(probe, draws, runs, at, wide)
        assert joined.t_cold_f is None

    def test_unrecorded_circulation_gives_no_estimate(self) -> None:
        probe, draws = a_draw(15)
        at = T0 + timedelta(hours=1)
        assert (
            sa.cold_supply(probe, at=at, draws=draws, circulation=None).t_cold_f
            is None
        )


def test_on_the_mains() -> None:
    book = full_tank_book(140.0, 139.5, BookParams())
    moved, measured = on_the_mains(book, ColdSupply(71.5, 3))
    assert moved is not None and moved.inlet_f == 71.5 and measured
    same, measured = on_the_mains(book, ColdSupply(None))
    assert same == book and not measured
    assert on_the_mains(None, ColdSupply(71.5, 3)) == (None, False)
