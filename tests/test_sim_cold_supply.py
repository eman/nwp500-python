"""The mains from an inlet probe's long-draw plateaus
(``sim.cold_supply``).

Held to its source by the parity check run with the port; these hold
its rules.
"""

from datetime import UTC, datetime, timedelta

from nwp500 import sim_adapters as sa
from nwp500.sim.book import full_tank_book
from nwp500.sim.cold_supply import ColdSupply, on_the_mains, plateau_t_cold
from nwp500.sim.params import BookParams

T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def a_draw(minutes: int, at: datetime = T0, mains: float = 72.0):
    """A draw of ``minutes`` at 2 gal/min, the probe settling from 77
    degF to the mains after 5 minutes."""
    ticks = [at + timedelta(seconds=s) for s in range(0, 60 * minutes, 10)]
    flow = [(t, 2.0) for t in ticks] + [
        (ticks[-1] + timedelta(seconds=10), 0.0)
    ]
    probe = [
        (t, 77.0 if (t - at).total_seconds() < 300 else mains) for t in ticks
    ]
    return probe, ticks, flow


class TestThePlateau:
    def test_a_long_draw_reads_the_mains(self):
        probe, ticks, flow = a_draw(15)
        got = plateau_t_cold(
            probe, ticks, [], T0 + timedelta(hours=1), flow=flow
        )
        assert (got.t_cold_f, got.draws) == (72.0, 1)

    def test_a_short_draw_or_one_with_circulation_has_none(self):
        probe, ticks, flow = a_draw(9)
        assert (
            plateau_t_cold(
                probe, ticks, [], T0 + timedelta(hours=1), flow=flow
            ).t_cold_f
            is None
        )
        probe, ticks, flow = a_draw(15)
        run = [(T0 + timedelta(minutes=3), T0 + timedelta(minutes=6))]
        assert (
            plateau_t_cold(
                probe, ticks, run, T0 + timedelta(hours=1), flow=flow
            ).t_cold_f
            is None
        )

    def test_unrecorded_is_not_idle(self):
        probe, ticks, flow = a_draw(15)
        at = T0 + timedelta(hours=1)
        assert (
            plateau_t_cold(probe, ticks, None, at, flow=flow).t_cold_f is None
        )
        assert plateau_t_cold(probe, ticks, [], at, flow=None).t_cold_f is None

    def test_old_or_implausible_draws_do_not_count(self):
        probe, ticks, flow = a_draw(15)
        late = T0 + timedelta(hours=80)
        assert (
            plateau_t_cold(probe, ticks, [], late, flow=flow).t_cold_f is None
        )
        probe, ticks, flow = a_draw(15, mains=95.0)
        assert (
            plateau_t_cold(
                probe, ticks, [], T0 + timedelta(hours=1), flow=flow
            ).t_cold_f
            is None
        )

    def test_the_adapter_reads_the_preferred_units(self):
        probe, _, flow = a_draw(15)
        got = sa.cold_supply(probe, at=T0 + timedelta(hours=1), flow=flow)
        assert got.t_cold_f == 72.0


def test_on_the_mains():
    book = full_tank_book(140.0, 139.5, BookParams())
    moved, measured = on_the_mains(book, ColdSupply(71.5, 3))
    assert moved is not None and moved.inlet_f == 71.5 and measured
    same, measured = on_the_mains(book, ColdSupply(None))
    assert same == book and not measured
    assert on_the_mains(None, ColdSupply(71.5, 3)) == (None, False)
