"""An installation's circulation (``nwp500.sim.circulation``): its runs
as water through the tank, through the API.

The terms are held to their source by the parity check run with the
port; these hold the API to the core and the runs to their schedule.
"""

import bisect
import json
import math
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
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
    calibration,
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
    steady_share,
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
from nwp500.sim.physics import stratified as st
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

    def test_its_own_water_comes_back_at_its_steady_share(self) -> None:
        terms = replace(TERMS, pipe_ua_btu_hr_f=40.0)
        (_, own) = circulation_flows(
            Circulation(((at(0), at(1)),)), terms, lambda _: 68.0, at(0), at(2)
        )
        assert own.inflow_f is None and own.rest_f == 70.0
        assert own.share == pytest.approx(math.exp(-40.0 / (1.5 * 60 * 8.34)))
        assert steady_share(0.0, 1.5) == 1.0
        assert steady_share(40.0, 0.0) == 0.0

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


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "sim"
    / "circulation_run_2026-10-29.json"
)


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@pytest.fixture(scope="module")
def measured_run() -> dict[str, Any]:
    """The 2026-10-29 run: each reading's change rows, and the run's
    start and end."""
    doc = json.loads(FIXTURE.read_text())
    return {
        "start": _instant(doc["run"]["start"]),
        "end": _instant(doc["run"]["end"]),
        **{
            k: [(_instant(t), float(v)) for t, v in rows]
            for k, rows in doc["series"].items()
        },
    }


class TestThePipe:
    """The pipe measured on the return line of a run after a rest
    (``calibration.measure_pipe``), and what it prices."""

    def test_the_measured_run_gives_its_volume_and_loss(
        self, measured_run: dict[str, Any]
    ) -> None:
        r = measured_run
        got = calibration.measure_pipe(
            r["start"],
            r["end"],
            flow=r["flow_gpm"],
            return_f=r["return_f"],
            upper_f=r["upper_f"],
        )
        assert got is not None
        # Half way up its front at 6.9 gal; steady 1.6 degF under the
        # upper probe at 1.08 gal/min.
        assert got.volume_gal == pytest.approx(6.86, abs=0.01)
        assert got.ua_btu_hr_f == pytest.approx(14.6, abs=0.1)
        assert got.flow_gpm == pytest.approx(1.078, abs=0.001)
        assert got.rest_f == pytest.approx(68.84, abs=0.01)

    def test_a_run_cut_before_its_return_settles_says_nothing(
        self, measured_run: dict[str, Any]
    ) -> None:
        r = measured_run
        end = r["start"] + timedelta(minutes=12)
        rows = {k: r[k] for k in ("flow_gpm", "return_f", "upper_f")}
        cut = calibration.measure_pipe(
            r["start"],
            end,
            flow=rows["flow_gpm"],
            return_f=[x for x in rows["return_f"] if x[0] <= end],
            upper_f=rows["upper_f"],
        )
        assert cut is None
        no_rest = calibration.measure_pipe(
            r["start"],
            r["end"],
            flow=rows["flow_gpm"],
            return_f=[x for x in rows["return_f"] if x[0] > r["start"]],
            upper_f=rows["upper_f"],
        )
        assert no_rest is None

    def test_a_run_held_from_before_its_start_is_measured(
        self, measured_run: dict[str, Any]
    ) -> None:
        """A flow read once before the run and held through it is the
        same run as one read at its start."""
        r = measured_run

        def measured(at_t: datetime) -> calibration.Pipe | None:
            return calibration.measure_pipe(
                r["start"],
                r["end"],
                flow=[(at_t, 1.078)],
                return_f=r["return_f"],
                upper_f=r["upper_f"],
            )

        before = measured(r["start"] - timedelta(seconds=30))
        assert before is not None
        assert before.flow_gpm == 1.078
        assert before == measured(r["start"])

    def test_a_short_run_takes_the_cooled_gallons_the_walk_returns(
        self,
    ) -> None:
        """Half cooled, a 6 gal pipe returns 3 gal at its rest: a run of
        3 gal is all of it, as the walk moves it."""
        rest = 0.5 * math.log(2.0)
        heat = calibration.run_heat_btu(
            2.0, 130.0, 60.0, 6.0, 1.5, rest_h=rest, cool_tau_h=0.5
        )
        assert heat == pytest.approx(3.0 * 8.34 * 70.0)
        terms = replace(TERMS, displaced_gal=6.0, return_cool_tau_h=0.5)
        first = (
            at(0) - timedelta(hours=rest + 0.1),
            at(0) - timedelta(hours=rest),
        )
        (cooled, *_) = circulation_flows(
            Circulation((first, (at(0), at(0) + MIN * 2))),
            terms,
            lambda _: 68.0,
            at(0),
            at(1),
        )
        assert (cooled.end - cooled.start) / MIN * 1.5 == pytest.approx(3.0)

    def test_past_its_volume_a_run_takes_the_pipes_loss(self) -> None:
        lift = 130.0 - 60.0 - 5.0

        def heat(minutes: float, ua: float = 0.0) -> float:
            return calibration.run_heat_btu(
                minutes,
                130.0,
                60.0,
                6.0,
                1.5,
                rest_offset_f=5.0,
                pipe_ua_btu_hr_f=ua,
            )

        # Within the volume, the pipe's water at its rest alone.
        assert heat(2.0) == pytest.approx(3.0 * 8.34 * lift)
        assert heat(2.0, 30.0) == pytest.approx(heat(2.0))
        # Past it, nothing without a loss; with one, its share.
        assert heat(10.0) == pytest.approx(heat(4.0))
        lost = 1.0 - steady_share(30.0, 1.5)
        assert heat(10.0, 30.0) == pytest.approx(
            (6.0 + lost * 9.0) * 8.34 * lift
        )

    def test_the_rest_and_the_cooling_are_found_again(self) -> None:
        def run(k: int) -> calibration.MeasuredRun:
            minutes = (3.0, 4.5, 6.0, 9.0)[k % 4]
            rest = (0.2, 0.6, 1.5, 6.0, 20.0)[k % 5]
            up, air = 120.0 + k % 7, 60.0 + k % 9
            return calibration.MeasuredRun(
                start=T0 + timedelta(hours=k),
                end=T0 + timedelta(hours=k, minutes=minutes),
                minutes=minutes,
                btu=calibration.run_heat_btu(
                    minutes,
                    up,
                    air,
                    6.0,
                    1.3,
                    rest_offset_f=4.0,
                    rest_h=rest,
                    cool_tau_h=0.5,
                    pipe_ua_btu_hr_f=15.0,
                ),
                flow_gpm=1.3,
                upper_f=float(up),
                air_f=float(air),
                rest_h=rest,
            )

        runs = [run(k) for k in range(40)]
        got = calibration.fit_return(runs, 6.0, 15.0)
        assert got is not None
        assert got[0] == pytest.approx(4.0, abs=0.05)
        assert got[1] == pytest.approx(0.5, abs=0.01)
        assert calibration.fit_return(runs[:10], 6.0, 15.0) is None
        # With no rest known the cooling is not seen.
        unrested = [replace(r, rest_h=None) for r in runs]
        assert calibration.fit_return(unrested, 6.0, 15.0) is None


class TestTheMeasuredRunThroughTheTank:
    def test_the_return_rises_past_the_cold_it_brought(
        self, measured_run: dict[str, Any], params: HeaterParams
    ) -> None:
        """The run walked with its own flow and return as the inflow:
        the warm return goes in above the pipe's cold water rather than
        lifting it through the column, so the top stays as hot as the
        upper probe read (0.8 degF RMS, against 2.0 with every inflow a
        plug), and the tank gives up the heat the return line measured
        (4,589 BTU) but 3.2 %. The lower probe, at its fitted height, does
        not see the cold the run left below it: it fell to 105.8 degF,
        which no stable column with the probe that high can read on the
        heat that had left."""
        r = measured_run
        lay = st.layout(params)

        def held(key: str, t: datetime) -> float:
            rows = r[key]
            return rows[bisect.bisect_right([x[0] for x in rows], t) - 1][1]

        step = timedelta(seconds=10)
        flows, t = [], r["start"]
        while t < r["end"]:
            e = min(t + step, r["end"])
            flows.append(
                st.Flowing(
                    start=t,
                    end=e,
                    gpm=held("flow_gpm", t),
                    inflow_f=held("return_f", t),
                )
            )
            t = e
        start = st.estimate(
            lay, held("upper_f", r["start"]), held("lower_f", r["start"])
        )
        w = st.walk(
            lay,
            start,
            r["start"],
            r["end"],
            air_f=lambda _: 63.8,
            flowing=flows,
        )
        times = [p for p, _ in w.path]
        errors = [
            st.observe(lay, w.path[bisect.bisect_right(times, at) - 1][1])[0]
            - v
            for at, v in r["upper_f"]
            if r["start"] < at <= r["end"]
        ]
        assert math.sqrt(sum(e * e for e in errors) / len(errors)) < 1.0
        assert w.books.flowing_btu == pytest.approx(4589.0, rel=0.04)
