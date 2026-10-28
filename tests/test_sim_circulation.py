"""An installation's circulation (``nwp500.sim.circulation``): its runs
as water through the tank, through the API.

The terms are held to their source by the parity check run with the
port; these hold the API to the core and the runs to their schedule.
"""

import json
import math
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from nwp500 import sim_adapters as sa
from nwp500.sim import (
    CirculationRun,
    Draw,
    Environment,
    HeaterParams,
    HeaterState,
    History,
    Loads,
    Scenario,
    Settings,
    default_params,
    simulate,
    site_example_params,
    standby,
)
from nwp500.sim.circulation import (
    RUN_GAP,
    Circulation,
    cooled_share,
    merge_runs,
)
from nwp500.sim.codec import (
    scenario_from_document,
    scenario_to_document,
)
from nwp500.sim.params import (
    CirculationParams,
    params_from_document,
    params_to_document,
)
from nwp500.sim.physics.heat_pump import start_hold_min
from nwp500.sim.schedules import weekly_runs
from nwp500.sim.tank_physics import circulation_flows, point_at

T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
LA = ZoneInfo("America/Los_Angeles")


def at(h: float) -> datetime:
    return T0 + timedelta(hours=h)


RUNS = ((at(0.2), at(0.3)), (at(1.0), at(1.5)), (at(4.0), at(4.05)))


def _loads(
    runs: Iterable[tuple[datetime, datetime]] = RUNS, **kw: Any
) -> Loads:
    return Loads(
        circulation=tuple(CirculationRun(start=a, end=b) for a, b in runs),
        **kw,
    )


def _scenario(**kw: Any) -> Scenario:
    base: dict[str, Any] = {
        "start": T0,
        "horizon": timedelta(hours=8),
        "tz": "UTC",
        "state": HeaterState(upper_f=139.0, lower_f=132.0),
        "settings": Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
        "history": History(compressor_stopped_at=at(-1.0)),
        "environment": Environment(ambient_f=68.0, humidity=48.0),
        "loads": _loads(),
    }
    base.update(kw)
    return Scenario(**base)


@pytest.fixture(scope="module")
def params() -> HeaterParams:
    return site_example_params()


MIN = timedelta(minutes=1)
TERMS = CirculationParams(
    displaced_gal=6.0,
    flow_gpm=1.5,
    return_rest_offset_f=2.0,
    return_cool_tau_h=0.0,
)


def _flows(
    runs: list[tuple[datetime, datetime]],
    start: datetime,
    end: datetime,
    *,
    tau: float = 0.0,
) -> list[Any]:
    """The runs through the tank in 68 °F air, on ``TERMS`` with the pipe
    cooling on ``tau``."""
    terms = replace(TERMS, return_cool_tau_h=tau)
    return circulation_flows(
        Circulation(tuple(runs)), terms, lambda _: 68.0, start, end
    )


class TestTheRuns:
    def test_runs_closer_than_the_gap_are_one(self) -> None:
        a, b = at(0.0), at(0.1)
        near = (b + RUN_GAP, b + RUN_GAP + timedelta(minutes=5))
        far = (near[1] + RUN_GAP + timedelta(seconds=1), at(2.0))
        assert merge_runs([(a, b), near, far]) == [(a, near[1]), far]

    def test_a_run_returns_the_cooled_pipe_then_its_own_water(
        self,
    ) -> None:
        (cooled, own) = _flows([(at(0), at(1))], at(0), at(2))
        assert (cooled.start, cooled.end) == (at(0), at(0) + MIN * 4)
        assert cooled.gpm == 1.5 and cooled.inflow_f == 68.0 + 2.0
        assert (own.start, own.end, own.inflow_f) == (
            at(0) + MIN * 4,
            at(1),
            None,
        )
        # A run shorter than its pipe returns cooled water throughout.
        (short,) = _flows([(at(0), at(0) + MIN * 2)], at(0), at(2))
        assert short.end == at(0) + MIN * 2 and short.inflow_f == 70.0

    def test_a_run_soon_after_another_finds_the_pipe_warm(self) -> None:
        assert cooled_share(None, 0.5) == 1.0
        assert cooled_share(0.5, 0.0) == 1.0
        assert cooled_share(0.5, 0.5) == pytest.approx(1 - math.exp(-1))
        first = (at(0), at(0) + MIN * 10)
        second = (at(0.5), at(0.5) + MIN * 10)
        got = _flows([first, second], at(0), at(2), tau=0.5)
        assert got[0].end - got[0].start == MIN * 4
        # The rest runs from the first run's end.
        rest = (second[0] - first[1]).total_seconds() / 3600
        warm = got[2]
        assert warm.start == second[0]
        assert (warm.end - warm.start) / MIN == pytest.approx(
            4.0 * cooled_share(rest, 0.5)
        )
        # A span holding the second alone still finds the first.
        assert _flows([first, second], at(0.4), at(2), tau=0.5)[0] == warm

    def test_a_run_under_way_is_returned_whole(self) -> None:
        (cooled, _) = _flows([(at(0), at(1))], at(0.5), at(2))
        assert cooled.start == at(0)

    def test_unknown_after_known_until_and_quiet_when_empty(self) -> None:
        c = Circulation(RUNS, known_until=at(2.0))
        assert c.over(at(0), at(1.2)) == list(RUNS[:2])
        assert c.over(at(3), at(5)) is None
        assert Circulation(()).over(at(0), at(1)) == []


class TestThroughTheAPI:
    def test_it_cools_the_tank_only_while_it_runs(
        self, params: HeaterParams
    ) -> None:
        quiet = simulate(_scenario(loads=Loads()), params)
        circulated = simulate(_scenario(), params)
        lower = {p.at: p.lower_f for p in circulated.points}
        before = [p for p in quiet.points if p.at <= at(0.2)]
        assert [lower[p.at] for p in before] == [p.lower_f for p in before]

        def after_first(sim: Any) -> float:
            return next(p.lower_f for p in sim.points if p.at >= at(0.5))

        assert after_first(circulated) < after_first(quiet)

    def test_unknown_runs_say_so_and_quiet_ones_do_not(
        self, params: HeaterParams
    ) -> None:
        unknown = simulate(_scenario(loads=Loads()), params)
        assert "circulation_unknown" in unknown.reasons
        quiet = simulate(_scenario(loads=_loads(())), params)
        assert "circulation_unknown" not in quiet.reasons
        known = simulate(_scenario(), params)
        assert "circulation_unknown" not in known.reasons
        partly = simulate(
            _scenario(
                loads=_loads().model_copy(
                    update={"circulation_known_until": at(2.0)}
                )
            ),
            params,
        )
        assert "circulation_unknown" in partly.reasons
        t = standby(
            HeaterState(upper_f=139.0, lower_f=132.0),
            Environment(ambient_f=68.0),
            Loads(),
            params,
            start=T0,
            until=at(4.0),
        )
        assert "circulation_unknown" in t.reasons
        # An installation without circulation has nothing unknown.
        bare = simulate(_scenario(loads=Loads()), default_params())
        assert "circulation_unknown" not in bare.reasons

    def test_the_merge_gap_is_the_installations(
        self, params: HeaterParams
    ) -> None:
        """Runs 20 minutes apart are two runs at the default gap and one
        at 30 minutes, which displaces its volume once: a small volume,
        the pipe cooled at once."""
        small = replace(
            params,
            circulation=replace(
                cast(CirculationParams, params.circulation),
                displaced_gal=6.0,
                return_cool_tau_h=0.0,
            ),
        )
        runs = ((at(0.2), at(0.3)), (at(0.633), at(0.733)))
        apart = simulate(_scenario(loads=_loads(runs)), small)
        wide = replace(
            small,
            circulation=replace(
                cast(CirculationParams, small.circulation),
                run_gap_min=30.0,
            ),
        )
        joined = simulate(_scenario(loads=_loads(runs)), wide)

        def after(sim: Any) -> float:
            # Past both runs, before any recovery they bring on.
            return point_at(sim.points, at(0.8)).lower_f

        assert after(joined) > after(apart)

    def test_runs_without_terms_take_the_example_terms(
        self, params: HeaterParams
    ) -> None:
        """Params with no circulation terms price the runs at one
        installation's and say so, rather than refusing."""
        got = simulate(_scenario(), default_params())
        assert any(d.startswith("circulation=") for d in got.defaults_used)

    def test_the_site_terms_are_named(self, params: HeaterParams) -> None:
        assert any(
            d.startswith("circulation=")
            for d in simulate(_scenario(), params).defaults_used
        )

    def test_standby_charges_them_too(self, params: HeaterParams) -> None:
        s = _scenario()
        args = (s.state, s.environment)
        quiet = standby(*args, Loads(), params, start=T0, until=at(6))
        circulated = standby(*args, s.loads, params, start=T0, until=at(6))
        assert circulated.points[-1].lower_f < quiet.points[-1].lower_f

    def test_standby_reports_what_they_and_the_draws_took(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        args = (s.state, s.environment)
        quiet = standby(*args, Loads(), params, start=T0, until=at(6))
        assert quiet.circulation_minutes is None
        assert quiet.draw_volume_gal is None and quiet.hours == 6.0
        assert quiet.ambient_mean_f == pytest.approx(68.0)
        loads = s.loads.model_copy(
            update={"draws": (Draw(at=at(2), gallons=3.0),)}
        )
        both = standby(*args, loads, params, start=T0, until=at(6))
        assert both.circulation_minutes is not None
        assert both.circulation_minutes > 0
        assert both.circulation_heat_wh is not None
        assert both.circulation_heat_wh > 0
        assert both.draw_volume_gal == pytest.approx(3.0)
        assert both.draw_heat_wh is not None and both.draw_heat_wh > 0

    def test_it_is_the_core_walked_with_the_runs(
        self, params: HeaterParams
    ) -> None:
        """The API's runs are the core's: the same walk as
        ``TankPhysics`` given the runs by hand."""
        from nwp500.sim.engine import Heater
        from nwp500.sim.engine import simulate as walk
        from nwp500.sim.tank_physics import TankPhysics

        s = _scenario(environment=Environment(ambient_f=68.0, humidity=48.0))
        stamps = pd.date_range(
            T0 - timedelta(hours=1),
            s.until + timedelta(hours=12),
            freq="10min",
        )
        frame = pd.DataFrame({"ambient_f": [68.0] * len(stamps)}, index=stamps)
        physics = TankPhysics(
            params,
            frame,
            48.0,
            draws_on=False,
            circulation=Circulation(RUNS),
        )
        by_hand = walk(
            start=T0,
            upper_f=139.0,
            lower_f=132.0,
            running=False,
            until=s.until,
            setpoint_f=140.9,
            heater=Heater(hp_lower_on_f=105.0, element=params.element),
            physics=physics,
            stopped_at=at(-1.0),
            start_hold=lambda off: start_hold_min(params.compressor, off),
            controller=params.controller,
        )
        assert simulate(s, params).simulation == by_hand


class TestTheSchedule:
    def test_weekly_runs_on_the_days_selected_across_midnight(self) -> None:
        # Monday-Friday 06:00-06:30, and the weekend 23:30-00:15.
        runs = weekly_runs(
            [(124, time(6, 0), time(6, 30)), (130, time(23, 30), time(0, 15))],
            LA,
            datetime(2026, 10, 5, tzinfo=LA),
            datetime(2026, 10, 12, tzinfo=LA),
        )
        local = [(a.astimezone(LA), b.astimezone(LA)) for a, b in runs]
        assert (
            datetime(2026, 10, 5, 6, 0, tzinfo=LA),
            datetime(2026, 10, 5, 6, 30, tzinfo=LA),
        ) in local
        assert (
            datetime(2026, 10, 10, 23, 30, tzinfo=LA),
            datetime(2026, 10, 11, 0, 15, tzinfo=LA),
        ) in local
        assert len([r for r in local if r[0].hour == 6]) == 5

    def test_the_adapter_takes_day_names_and_local_times(self) -> None:
        runs = sa.circulation(
            [(["Monday"], "06:00", "06:30")],
            tz="America/Los_Angeles",
            start=datetime(2026, 10, 5, tzinfo=UTC),
            until=datetime(2026, 10, 13, tzinfo=UTC),
        )
        assert [r.start.astimezone(LA).weekday() for r in runs] == [0, 0]
        assert all(r.end - r.start == timedelta(minutes=30) for r in runs)


class TestDocuments:
    def test_a_scenario_with_circulation_round_trips(self) -> None:
        s = _scenario(loads=_loads(circulation_known_until=at(6.0)))
        back, _ = scenario_from_document(json.dumps(scenario_to_document(s)))
        assert back == s

    def test_the_parameters_round_trip_with_and_without_it(
        self, params: HeaterParams
    ) -> None:
        for p in (params, replace(params, circulation=None)):
            doc = json.loads(json.dumps(params_to_document(p)))
            assert params_from_document(doc) == p
        assert "circulation" not in params_to_document(default_params())


class TestASplitCoast:
    """The second review of #162: runs within the gap are one run even
    when a coast boundary falls between them."""

    RUNS = (
        (at(0.0), at(0.0) + timedelta(minutes=5)),
        (at(0.0) + timedelta(minutes=10), at(0.0) + timedelta(minutes=15)),
    )

    def test_each_walk_gets_the_merged_run(self) -> None:
        cut = at(0.0) + timedelta(minutes=8)
        first = _flows(list(self.RUNS), at(0.0), cut)
        second = _flows(list(self.RUNS), cut, at(1.0))
        assert first == second
        assert first[0].start == at(0.0)
        assert first[-1].end == self.RUNS[1][1]

    def test_one_walk_or_two_cool_the_tank_alike(
        self, params: HeaterParams
    ) -> None:
        from nwp500.sim.tank_physics import TankPhysics

        stamps = pd.date_range(at(-1), at(4), freq="10min")
        frame = pd.DataFrame({"ambient_f": [68.0] * len(stamps)}, index=stamps)
        p = TankPhysics(
            params,
            frame,
            48.0,
            draws_on=False,
            circulation=Circulation(self.RUNS),
        )
        start = p.estimate(139.0, 132.0)
        whole = p.advance(at(0), start, at(1))
        cut = at(0.0) + timedelta(minutes=8)
        a = p.advance(at(0), start, cut)
        b = p.advance(cut, a.state, at(1))
        end, split = whole.points[-1], b.points[-1]
        assert split.lower_f == pytest.approx(end.lower_f, abs=0.05)
        assert split.upper_f == pytest.approx(end.upper_f, abs=0.05)
