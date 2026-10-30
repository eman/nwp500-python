"""Draws from a weekly draw forecast (``sim.draw_forecast``) and their
use in a walk: expected draws judged by their per-draw volume, and the
worst case's withheld windows.

Held to its source by the parity check run with the port; these hold
its rules.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from nwp500.sim import (
    Draw,
    Environment,
    HeaterState,
    Loads,
    Scenario,
    Settings,
    simulate,
    site_example_params,
)
from nwp500.sim import draw_forecast as F

T0 = datetime(2026, 10, 5, tzinfo=UTC)


def issue(long_at: dict[int, float] | None = None) -> list[F.ForecastSlot]:
    """A week of slots expecting short draws at 0.1 a slot and long ones
    only where ``long_at`` says (slot index: rate)."""
    long_at = long_at or {}
    return [
        F.ForecastSlot(
            valid_at=T0 + F.SLOT * k,
            long_rate=long_at.get(k, 0.0),
            long_min_s=240.0,
            long_duration_mean_s=600.0,
            long_duration_p90_s=900.0,
            long_volume_mean_gal=20.0,
            long_duration_support=10.0,
            long_volume_support=10.0,
            short_rate=0.1,
            short_duration_mean_s=30.0,
            short_duration_support=10.0,
            short_volume_mean_gal=0.5,
            short_volume_support=10.0,
        )
        for k in range(1008)
    ]


class TestTheIssue:
    def test_a_whole_week_answers(self) -> None:
        assert F.check_issue(issue()) is None

    def test_a_missing_family_or_slot_does_not(self) -> None:
        slots = issue()
        slots[3] = replace(slots[3], short_volume_support=None)
        assert F.check_issue(slots) == F.FAMILY_NULL
        assert F.check_issue(issue()[:-1]) == F.INCOMPLETE_ISSUE
        assert F.check_issue([]) == F.NO_COVERING_ISSUE


class TestTheWindow:
    def test_an_issue_answers_only_the_window_it_covers(self) -> None:
        slots = issue()
        week_end = T0 + timedelta(days=7)
        assert F.check_issue(slots, T0, week_end) is None
        late = F.check_issue(
            slots, week_end - timedelta(hours=6), week_end + timedelta(hours=1)
        )
        assert late == F.NO_COVERING_ISSUE
        with pytest.raises(ValueError, match="no_covering_issue"):
            F.draw_profile(
                slots,
                week_end - timedelta(hours=24),
                week_end + timedelta(hours=24),
            )

    def test_an_old_issue_answers_nothing(self) -> None:
        slots = issue()
        assert (
            F.check_issue(slots, issued_at=T0, now=T0 + timedelta(hours=36))
            is None
        )
        old = F.check_issue(slots, issued_at=T0, now=T0 + timedelta(hours=37))
        assert old == F.NO_COVERING_ISSUE

    def test_a_shifted_issue_is_judged_where_it_was_moved(self) -> None:
        moved = F.shifted(issue(), timedelta(days=7))
        assert F.check_issue(
            moved, T0, T0 + timedelta(hours=1), shift=timedelta(days=7)
        ) == (F.SHIFTED_ISSUE_UNCOVERED)


class TestTheProfile:
    def test_expected_draws_are_fractional_with_their_per_draw_volume(
        self,
    ) -> None:
        p = F.draw_profile(issue({60: 0.4}), T0, T0 + timedelta(hours=12))
        (shower,) = [d for d in p.draws if d.draw_class == "long"]
        assert shower.volume_gal == pytest.approx(8.0)
        assert shower.per_draw_gal == 20.0
        assert shower.duration_s == pytest.approx(240.0)
        assert p.expected_onsets == pytest.approx(72 * 0.1 + 0.4)

    def test_a_window_reaches_an_hour_before_its_draw(self) -> None:
        (w,) = F.draw_profile(
            issue({60: 0.4}), T0, T0 + timedelta(hours=24)
        ).windows
        assert w.start == T0 + F.SLOT * 54
        assert w.expected_count == pytest.approx(0.4)
        assert w.volume_mean_gal == pytest.approx(8.0)

    def test_the_worst_case_draws_first(self) -> None:
        p = F.draw_profile(issue({60: 0.4}), T0, T0 + timedelta(hours=24))
        draws, (span,) = F.draws_first(p, T0)
        (w,) = p.windows
        assert span == (w.start, w.start + timedelta(seconds=240))
        assert (w.start, 8.0, 20.0, 240.0) in draws


class TestTheShower:
    def test_it_is_the_rate_weighted_long_draw(self) -> None:
        slots = issue({60: 0.4, 80: 0.1})
        slots[80] = replace(slots[80], long_volume_mean_gal=10.0)
        p = F.draw_profile(slots, T0, T0 + timedelta(hours=24))
        # (0.4 x 20 + 0.1 x 10) / 0.5
        assert F.shower_gal(p) == pytest.approx(18.0)
        none = F.draw_profile(issue(), T0, T0 + timedelta(hours=24))
        assert F.shower_gal(none) is None


class TestInAWalk:
    def _scenario(self, draws: tuple[Draw, ...]) -> Scenario:
        return Scenario(
            start=T0,
            horizon=timedelta(hours=6),
            tz="UTC",
            state=HeaterState(upper_f=135.0, lower_f=130.0),
            settings=Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
            environment=Environment(ambient_f=65.0),
            loads=Loads(draws=draws),
        )

    def test_an_expected_draw_is_judged_by_its_per_draw_volume(self) -> None:
        p = site_example_params()
        small = (Draw(at=T0 + timedelta(hours=1), gallons=0.3),)
        expected = (
            Draw(at=T0 + timedelta(hours=1), gallons=0.3, per_draw_gal=12.0),
        )
        assert (
            "draw_out_of_domain" in simulate(self._scenario(small), p).reasons
        )
        assert "draw_out_of_domain" not in (
            simulate(self._scenario(expected), p).reasons
        )

    def test_the_forecast_as_loads_and_withheld_windows(self) -> None:
        p = F.draw_profile(issue({60: 0.4}), T0, T0 + timedelta(hours=24))
        loads, withheld = F.forecast_loads(p, T0, worst_case=True)
        assert withheld and loads.windows
        assert any(
            (d.per_draw_gal, d.duration_s) == (20.0, 240.0) for d in loads.draws
        )
        s = self._scenario(()).model_copy(
            update={"loads": loads, "horizon": timedelta(hours=24)}
        )
        r = simulate(s, site_example_params(), withheld_windows=withheld)
        assert r.windows
        (w,) = r.windows
        assert w.expected_count == pytest.approx(0.4)
        assert w.draws_until == withheld[0][1]
