"""Draws sampled from a weekly draw forecast (``sim.draw_ensemble``):
members drawn as the forecast publishes them, and candidates weighed
on the same members."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from nwp500.sim import (
    Draw,
    DrawWindow,
    Environment,
    HeaterState,
    Loads,
    Scenario,
    Settings,
    site_example_params,
)
from nwp500.sim import draw_ensemble as E
from nwp500.sim import draw_forecast as F

T0 = datetime(2026, 10, 5, tzinfo=UTC)
#: Evening slots, 18:00 to 21:00, where the long draws come.
EVENING = range(18 * 6, 21 * 6)


def issue(long_rate: float = 0.25) -> list[F.ForecastSlot]:
    """A week of slots: short draws at 0.1 a slot, long ones at
    ``long_rate`` a slot over each evening."""
    return [
        F.ForecastSlot(
            valid_at=T0 + F.SLOT * k,
            long_rate=long_rate if k % 144 in EVENING else 0.0,
            long_min_s=240.0,
            long_duration_mean_s=600.0,
            long_duration_p90_s=900.0,
            long_volume_mean_gal=15.0,
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


DAY = (T0, T0 + timedelta(days=1))


def scenario(setpoint_f: float = 120.0) -> Scenario:
    return Scenario(
        start=DAY[0],
        horizon=DAY[1] - DAY[0],
        tz="UTC",
        state=HeaterState(upper_f=setpoint_f, lower_f=setpoint_f - 2.0),
        settings=Settings(
            setpoint_f=setpoint_f,
            hp_lower_on_f=setpoint_f - 9.0,
            hp_lower_off_f=setpoint_f,
        ),
        environment=Environment(ambient_f=65.0),
        loads=Loads(),
    )


class TestMembers:
    def test_a_seed_gives_the_same_members_whatever_their_number(
        self,
    ) -> None:
        few = E.members(issue(), *DAY, count=3, seed=7)
        many = E.members(issue(), *DAY, count=10, seed=7)
        assert few == many[:3]
        assert E.members(issue(), *DAY, count=3, seed=8) != few

    def test_members_draw_what_the_forecast_expects(self) -> None:
        slots = issue()
        profile = F.draw_profile(slots, *DAY)
        expected = {
            c: sum(d.volume_gal for d in profile.draws if d.draw_class == c)
            for c in ("long", "short")
        }
        ensemble = E.members(slots, *DAY, count=400)
        long_gal = [
            sum(
                d.gallons
                for d in m.loads.draws
                if any(a == d.at for a, _ in m.long_draws)
            )
            for m in ensemble
        ]
        all_gal = [sum(d.gallons for d in m.loads.draws) for m in ensemble]
        short_gal = [a - b for a, b in zip(all_gal, long_gal, strict=True)]
        # The means within a few standard errors of the expectation.
        for got, want in (
            (long_gal, expected["long"]),
            (short_gal, expected["short"]),
        ):
            err = 4.0 * float(np.std(got)) / np.sqrt(len(got))
            assert abs(float(np.mean(got)) - want) < err

    def test_a_long_draw_has_the_published_floor_and_spread(self) -> None:
        ensemble = E.members(issue(), *DAY, count=300)
        seconds = np.array(
            [(b - a).total_seconds() for m in ensemble for a, b in m.long_draws]
        )
        assert seconds.min() >= 240.0
        assert float(np.mean(seconds)) == pytest.approx(600.0, rel=0.05)
        assert float(np.quantile(seconds, 0.9)) == pytest.approx(
            900.0, rel=0.06
        )
        # Its volume goes with its duration, at the slot's mean flow.
        for m in ensemble[:20]:
            for d in m.loads.draws:
                if any(a == d.at for a, _ in m.long_draws):
                    assert d.gallons == pytest.approx(
                        15.0 * d.duration_s / 600.0
                    )
                    assert d.per_draw_gal == d.gallons

    def test_a_short_draw_is_its_slots_means(self) -> None:
        (m,) = E.members(issue(long_rate=0.0), *DAY, count=1)
        assert m.long_draws == ()
        assert m.loads.draws
        assert {(d.gallons, d.duration_s) for d in m.loads.draws} == {
            (0.5, 30.0)
        }

    def test_with_no_spread_published_a_long_draw_is_the_mean(self) -> None:
        slots = [replace(s, long_duration_p90_s=None) for s in issue()]
        ensemble = E.members(slots, *DAY, count=20)
        assert {
            (b - a).total_seconds() for m in ensemble for a, b in m.long_draws
        } == {600.0}

    def test_every_member_keeps_the_forecasts_windows(self) -> None:
        slots = issue()
        windows = F.forecast_loads(F.draw_profile(slots, *DAY), DAY[0])[
            0
        ].windows
        assert windows
        assert all(
            m.loads.windows == windows for m in E.members(slots, *DAY, count=5)
        )

    def test_a_draw_runs_at_most_a_day_at_the_slots_flow(self) -> None:
        slots = [
            replace(s, long_duration_mean_s=20000.0, long_duration_p90_s=1e7)
            for s in issue()
        ]
        ensemble = E.members(slots, *DAY, count=50)
        longs = [
            d
            for m in ensemble
            for d in m.loads.draws
            if any(a == d.at for a, _ in m.long_draws)
        ]
        assert max(d.duration_s for d in longs) == E.MAX_DRAW_S
        for d in longs:
            assert d.gallons == pytest.approx(15.0 * d.duration_s / 20000.0)

    def test_a_span_ending_inside_a_slot_draws_inside_it(self) -> None:
        end = T0 + timedelta(hours=20, minutes=55)
        for m in E.members(issue(), T0, end, count=200):
            assert all(T0 <= d.at < end for d in m.loads.draws)

    def test_a_slot_the_span_cuts_draws_for_the_part_inside(self) -> None:
        # Half of each of two slots: one slot's worth of short draws.
        start = T0 + timedelta(minutes=5)
        end = T0 + timedelta(minutes=15)
        slots = issue(long_rate=0.0)
        ensemble = E.members(slots, start, end, count=4000)
        assert all(start <= d.at < end for m in ensemble for d in m.loads.draws)
        counts = np.array([len(m.loads.draws) for m in ensemble])
        assert float(counts.mean()) == pytest.approx(
            0.1, abs=4 * 0.1**0.5 / 4000**0.5
        )

    def test_a_ninetieth_percentile_out_of_reach_lowers_the_floor(self) -> None:
        # No lognormal above 240 s has mean 600 s and p90 1200 s: the
        # floor comes down to where one does.
        slots = [
            replace(s, long_duration_p90_s=1200.0) for s in issue(long_rate=0.5)
        ]
        seconds = np.array(
            [
                (b - a).total_seconds()
                for m in E.members(slots, *DAY, count=400)
                for a, b in m.long_draws
            ]
        )
        assert float(seconds.mean()) == pytest.approx(600.0, rel=0.03)
        assert float(np.quantile(seconds, 0.9)) == pytest.approx(
            1200.0, rel=0.04
        )
        floor, sigma = E._shape(600.0, 240.0, 1200.0)
        assert 0.0 < floor < 240.0
        assert sigma == pytest.approx(1.2815515655446004)
        assert seconds.min() >= floor

    def test_a_ninetieth_percentile_not_finite_is_not_published(self) -> None:
        slots = [replace(s, long_duration_p90_s=float("nan")) for s in issue()]
        assert {
            (b - a).total_seconds()
            for m in E.members(slots, *DAY, count=20)
            for a, b in m.long_draws
        } == {600.0}

    def test_a_slot_whose_expectation_runs_past_a_day_is_sampled(
        self,
    ) -> None:
        # Rate 5 at a 20,000 s mean: its expected draw would run 100,000 s.
        slots = [
            replace(s, long_rate=5.0, long_duration_mean_s=20000.0)
            for s in issue()
        ]
        (m,) = E.members(slots, *DAY, count=1)
        assert m.long_draws and m.loads.windows

    def test_a_local_span_across_the_repeated_hour_draws_inside_it(
        self,
    ) -> None:
        # 2026-11-01 01:00 to 02:00 PDT then PST in Los Angeles: a span
        # starting in the repeated hour's second pass.
        la = ZoneInfo("America/Los_Angeles")
        t0 = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
        slots = [
            replace(s, valid_at=t0 + F.SLOT * k) for k, s in enumerate(issue())
        ]
        start = datetime(2026, 11, 1, 1, 10, tzinfo=la, fold=1)
        # A fold=1 instant compares unequal across zones (PEP 495).
        utc = start.astimezone(UTC)
        assert utc == datetime(2026, 11, 1, 9, 10, tzinfo=UTC)
        end = utc + timedelta(hours=2)
        for m in E.members(slots, start, end, count=200):
            assert all(utc <= d.at < end for d in m.loads.draws)
            assert m.start == utc and m.start.tzinfo is UTC

    def test_a_span_the_issue_does_not_cover_is_refused(self) -> None:
        late = T0 + timedelta(days=7)
        with pytest.raises(ValueError, match="no_covering_issue"):
            E.members(
                issue(), late - timedelta(hours=1), late + timedelta(hours=1)
            )
        with pytest.raises(ValueError):
            E.members(issue(), *DAY, count=0)


class TestWeigh:
    def test_every_candidate_meets_the_same_households(self) -> None:
        ensemble = E.members(issue(), *DAY, count=6)
        low, high = E.weigh(
            [scenario(120.0), scenario(140.0)], ensemble, site_example_params()
        )
        for a, b, m in zip(low.walks, high.walks, ensemble, strict=True):
            assert a.member is m and b.member is m
        assert len(low.input_wh) == len(ensemble)

    def test_a_hotter_tank_runs_cold_less_often(self) -> None:
        params = site_example_params()
        ensemble = E.members(issue(long_rate=0.1), *DAY, count=20)
        low, high = E.weigh(
            [scenario(110.0), scenario(140.0)], ensemble, params
        )
        assert low.cold_share > high.cold_share
        for a, b in zip(low.walks, high.walks, strict=True):
            if not a.member.long_draws:
                assert a.long_min_f is None and not a.cold
                continue
            assert a.long_min_f is not None and b.long_min_f is not None
            assert b.long_min_f >= a.long_min_f - 1e-9
            assert a.cold == (a.long_min_f < params.readiness.line_f)

    def test_a_difference_on_the_same_households_is_less_noisy(self) -> None:
        ensemble = E.members(issue(long_rate=0.1), *DAY, count=20)
        low, high = E.weigh(
            [scenario(120.0), scenario(135.0)], ensemble, site_example_params()
        )
        a = np.array(low.input_wh, dtype=float)
        b = np.array(high.input_wh, dtype=float)
        # Against the same two walked on independent households, whose
        # difference's spread is both spreads together.
        assert a.std() > 0.0
        assert (b - a).std() < 0.5 * np.hypot(a.std(), b.std())

    def test_the_mean_is_none_when_a_member_is_unpriced(self) -> None:
        ensemble = E.members(issue(), *DAY, count=3)
        (w,) = E.weigh([scenario()], ensemble, site_example_params())
        assert w.mean(lambda r: r.input_wh) == pytest.approx(
            sum(v for v in w.input_wh if v is not None) / 3
        )
        assert w.mean(lambda r: None) is None

    def test_a_long_draw_of_no_length_is_judged_through_its_step(self) -> None:
        at = T0 + timedelta(hours=19)
        for when in (at, T0):
            member = E.Member(
                loads=Loads(draws=(Draw(at=when, gallons=60.0),)),
                long_draws=((when, when),),
                start=DAY[0],
                end=DAY[1],
            )
            params = site_example_params()
            (w,) = E.weigh([scenario(120.0)], [member], params)
            (walk,) = w.walks
            assert walk.long_min_f is not None
            assert walk.long_min_f < params.readiness.line_f
            assert walk.cold

    def test_a_scenario_reaching_outside_the_members_is_refused(self) -> None:
        ensemble = E.members(issue(), *DAY, count=2)
        longer = scenario().model_copy(update={"horizon": timedelta(days=2)})
        with pytest.raises(ValueError, match="reaches outside"):
            E.weigh([longer], ensemble, site_example_params())
        shorter = scenario().model_copy(update={"horizon": timedelta(hours=6)})
        E.weigh([shorter], ensemble, site_example_params(), running_hold=5.0)

    def test_a_shorter_walk_meets_only_its_part_of_the_member(self) -> None:
        start, until = T0 + timedelta(hours=6), T0 + timedelta(hours=12)
        across = Draw(
            at=start - timedelta(seconds=90), gallons=6.0, duration_s=300
        )
        late = Draw(at=T0 + timedelta(hours=19), gallons=80.0, duration_s=600)
        member = E.Member(
            loads=Loads(
                draws=(across, late),
                windows=(
                    DrawWindow(
                        start=T0 + timedelta(hours=1),
                        end=T0 + timedelta(hours=2),
                    ),
                    DrawWindow(
                        start=start - timedelta(minutes=10),
                        end=start + timedelta(minutes=10),
                        draws_until=start - timedelta(minutes=10),
                    ),
                ),
            ),
            long_draws=(),
            start=DAY[0],
            end=DAY[1],
        )
        tiny = Draw(at=start + timedelta(hours=1), gallons=3.0, duration_s=4e-7)
        assert E._draws_in([tiny], start, until) == (tiny,)
        (cut,) = E._draws_in(member.loads.draws, start, until)
        assert cut.at == start and cut.duration_s == 210.0
        assert cut.gallons == pytest.approx(6.0 * 210 / 300)
        assert cut.per_draw_gal == 6.0
        (w,) = E._windows_in(member.loads.windows, start, until)
        assert w.draws_until == start
        shorter = scenario().model_copy(
            update={"start": start, "horizon": until - start}
        )
        (weighed,) = E.weigh([shorter], [member], site_example_params())
        (walk,) = weighed.walks
        assert [x.start for x in walk.walk.windows] == [w.start]

    def test_a_long_draw_past_the_walks_end_is_counted_cut_short(self) -> None:
        end = DAY[1]
        member = E.Member(
            loads=Loads(
                draws=(
                    Draw(
                        at=end - timedelta(minutes=2),
                        gallons=15.0,
                        duration_s=600,
                    ),
                )
            ),
            long_draws=(
                (end - timedelta(minutes=2), end + timedelta(minutes=8)),
            ),
            start=DAY[0],
            end=DAY[1],
        )
        (w,) = E.weigh([scenario()], [member], site_example_params())
        assert w.walks[0].cut_short == 1

    def test_an_empty_ensemble_is_refused(self) -> None:
        with pytest.raises(ValueError):
            E.weigh([scenario()], (), site_example_params())
