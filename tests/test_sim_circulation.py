"""An installation's circulation (``nwp500.sim.circulation``): its runs
as flowing draws and its loss to the book, through the API.

The terms are held to their source by the parity check run with the
port; these hold the API to the core and the runs to their schedule.
"""

import json
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
    full_tank_book,
    simulate,
    site_example_params,
    standby,
)
from nwp500.sim.circulation import (
    RUN_GAP,
    Circulation,
    CirculationDraws,
    CirculationLoss,
    merge_runs,
    run_draws,
)
from nwp500.sim.codec import (
    scenario_from_document,
    scenario_to_document,
)
from nwp500.sim.defaults import SITE_CIRCULATION
from nwp500.sim.params import (
    CirculationParams,
    params_from_document,
    params_to_document,
)
from nwp500.sim.schedules import weekly_runs

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


class TestTheRuns:
    def test_runs_closer_than_the_gap_are_one(self) -> None:
        a, b = at(0.0), at(0.1)
        near = (b + RUN_GAP, b + RUN_GAP + timedelta(minutes=5))
        far = (near[1] + RUN_GAP + timedelta(seconds=1), at(2.0))
        assert merge_runs([(a, b), near, far]) == [(a, near[1]), far]

    def test_a_run_stops_charging_once_it_has_displaced_its_volume(
        self,
    ) -> None:
        (d,) = run_draws(
            [(at(0), at(1))], at(0), at(2), 6.0, 1.5, lambda _: 68.0
        )
        assert d.gallons == 6.0 and d.gpm == 1.5 and d.until == at(1)
        (short,) = run_draws(
            [(at(0), at(0) + timedelta(minutes=2))],
            at(0),
            at(2),
            6.0,
            1.5,
            lambda _: 68.0,
        )
        assert short.gallons == pytest.approx(3.0)

    def test_a_run_under_way_is_charged_whole(self) -> None:
        (d,) = run_draws(
            [(at(0), at(1))], at(0.5), at(2), 6.0, 1.5, lambda _: 68.0
        )
        assert d.at == at(0)

    def test_unknown_after_known_until_and_quiet_when_empty(self) -> None:
        c = Circulation(RUNS, known_until=at(2.0))
        assert c.over(at(0), at(1.2)) == list(RUNS[:2])
        assert c.over(at(3), at(5)) is None
        assert Circulation(()).over(at(0), at(1)) == []

    def test_the_books_loss_is_per_gallon_circulated(self) -> None:
        loss = CirculationLoss(RUNS, 1.4, 159.0)
        btu, disturbed = loss.loss(at(1.0), at(1.25))
        assert disturbed and btu == pytest.approx(159.0 * 1.4 * 15.0)
        assert loss.loss(at(2.0), at(3.0)) == (0.0, False)
        assert loss.bound(at(0), at(2)) == pytest.approx(159.0 * 1.4 * 36.0)
        assert at(1.0) in loss.edges(at(0), at(2))


class TestThroughTheAPI:
    def test_it_cools_the_tank_only_while_it_runs(
        self, params: HeaterParams
    ) -> None:
        quiet = simulate(_scenario(loads=Loads()), params)
        circulated = simulate(_scenario(), params)
        before = [p for p in circulated.points if p.at <= at(0.2)]
        assert [p.lower_f for p in before] == [
            p.lower_f for p in quiet.points if p.at <= at(0.2)
        ]
        assert circulated.points[-1].lower_f < quiet.points[-1].lower_f

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
        at 30 minutes, which displaces its volume once."""
        runs = ((at(0.2), at(0.3)), (at(0.633), at(0.733)))
        apart = simulate(_scenario(loads=_loads(runs)), params)
        wide = replace(
            params,
            circulation=replace(
                cast(CirculationParams, params.circulation),
                run_gap_min=30.0,
            ),
        )
        joined = simulate(_scenario(loads=_loads(runs)), wide)
        assert joined.points[-1].lower_f > apart.points[-1].lower_f

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

    def test_with_a_book_the_runs_are_its_loss(
        self, params: HeaterParams
    ) -> None:
        book = full_tank_book(139.0, 138.5, params.book_terms())
        quiet = simulate(_scenario(loads=Loads()), params, book=book)
        circulated = simulate(_scenario(), params, book=book)
        assert circulated.booked is not None and quiet.booked is not None
        # After the first run, before the runs' heat brings on a
        # recovery.
        runs = _loads().circulation
        assert runs is not None
        after = runs[0].end

        def heat_at(walk: Any) -> float:
            k = next(i for i, t in enumerate(walk.instants) if t >= after)
            return float(walk.states[k].heat_btu)

        assert heat_at(circulated.booked) < heat_at(quiet.booked)

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
        """The API's runs are the core's flowing draws: the same walk
        as ``TankPhysics`` with ``CirculationDraws`` by hand."""
        from nwp500.sim.decay import AmbientSampler
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
        c = params.circulation
        assert c is not None
        flowing = CirculationDraws(
            Circulation(RUNS),
            c.displaced_gal,
            c.flow_gpm,
            AmbientSampler(frame).at,
        )
        physics = TankPhysics(
            params,
            frame,
            48.0,
            draws_on=False,
            flowing_draws=flowing,
            tau_gap_hours=params.tank.stratification_gap_tau_h,  # type: ignore[arg-type]
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
            startup_wh=params.power.startup_wh,
            stopped_at=at(-1.0),
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

    def test_each_coast_gets_the_merged_run(self) -> None:
        draws = CirculationDraws(
            Circulation(self.RUNS), 6.0, 1.5, lambda _: 68.0
        )
        cut = at(0.0) + timedelta(minutes=8)
        (first,) = draws(at(0.0), cut)
        (second,) = draws(cut, at(1.0))
        assert first == second
        assert first.at == at(0.0) and first.gallons == 6.0
        assert first.until == self.RUNS[1][1]

    def test_one_coast_or_two_cool_the_tank_alike(
        self, params: HeaterParams
    ) -> None:
        from nwp500.sim.tank_physics import TankPhysics

        stamps = pd.date_range(at(-1), at(4), freq="10min")
        frame = pd.DataFrame({"ambient_f": [68.0] * len(stamps)}, index=stamps)

        def physics() -> TankPhysics:
            return TankPhysics(
                params,
                frame,
                48.0,
                draws_on=False,
                flowing_draws=CirculationDraws(
                    Circulation(self.RUNS), 6.0, 1.5, lambda _: 68.0
                ),
                tau_gap_hours=params.tank.stratification_gap_tau_h,  # type: ignore[arg-type]
            )

        whole = physics().coast(
            at(0), 139.0, 132.0, at(1), [], heated_at=at(-1)
        )
        p = physics()
        cut = at(0.0) + timedelta(minutes=8)
        a = p.coast(at(0), 139.0, 132.0, cut, [], heated_at=at(-1))
        mid = a.points[-1]
        b = p.coast(cut, mid.upper_f, mid.lower_f, at(1), [], heated_at=at(-1))
        end, split = whole.points[-1], b.points[-1]
        assert split.lower_f == pytest.approx(end.lower_f, abs=0.05)
        assert split.upper_f == pytest.approx(end.upper_f, abs=0.05)


class TestTheBooksCircuitVolume:
    TERMS = replace(SITE_CIRCULATION, book_circuit_gal=1.5)

    def test_a_run_takes_its_first_gallons_at_the_tank_less_the_air(
        self,
    ) -> None:
        from nwp500.sim.book import circulated_btu

        def take(gal: float, before: float) -> float:
            return circulated_btu(
                gal,
                self.TERMS,
                before_gal=before,
                upper_f=140.0,
                ambient_f=65.0,
            )

        assert take(1.0, 0.0) == pytest.approx(1.0 * 8.34 * 75.0)
        # Only the half gallon left before the circuit is hot.
        assert take(1.0, 1.0) == pytest.approx(0.5 * 8.34 * 75.0)
        assert take(1.0, 2.0) == 0.0
        # Without the volume, the loss per gallon.
        flat = replace(self.TERMS, book_circuit_gal=None)
        assert circulated_btu(1.0, flat) == SITE_CIRCULATION.loss_btu_per_gal

    def test_the_ledger_prices_projected_runs_so(self) -> None:
        from nwp500.sim.circulation import CirculationLoss

        run = (at(0.0), at(1.0))
        loss = CirculationLoss(
            [run],
            flow_gpm=1.0,
            loss_btu_per_gal=159.0,
            circuit_gal=1.5,
            upper_f=140.0,
            air_at=lambda _: 65.0,
        )
        first, on = loss.loss(at(0.0), at(0.0) + timedelta(minutes=1))
        assert on and first == pytest.approx(1.0 * 8.34 * 75.0)
        later, on = loss.loss(at(0.5), at(0.6))
        assert on and later == 0.0
        whole = loss.bound(at(0.0), at(1.0))
        assert whole == pytest.approx(1.5 * 8.34 * (140.0 + 20.0))

    def test_runs_in_a_group_share_the_circuit(self) -> None:
        """Two one-minute runs at 1 gal/min, 5 minutes apart, one group:
        the first takes 1 gal of the 1.5 gal circuit, the second the
        half left, and the gap between them circulates nothing."""
        from nwp500.sim.circulation import CirculationLoss

        a = at(0.0)
        m = timedelta(minutes=1)
        runs = [(a, a + m), (a + 6 * m, a + 7 * m)]
        loss = CirculationLoss(
            runs,
            flow_gpm=1.0,
            loss_btu_per_gal=159.0,
            circuit_gal=1.5,
            upper_f=140.0,
            air_at=lambda _: 65.0,
        )
        assert loss.loss(a + m, a + 6 * m) == (0.0, False)
        got = [loss.loss(r0, r1)[0] for r0, r1 in runs]
        assert got == pytest.approx([1.0 * 8.34 * 75.0, 0.5 * 8.34 * 75.0])

    def test_the_air_is_the_charged_gallons(self) -> None:
        """A 10 minute run at 1 gal/min, a 1 gal circuit, the air rising
        from 50 to 70 °F: the gallon flows in the first minute, at its
        51 °F."""
        from nwp500.sim.circulation import CirculationLoss

        a = at(0.0)
        loss = CirculationLoss(
            [(a, a + timedelta(minutes=10))],
            flow_gpm=1.0,
            loss_btu_per_gal=159.0,
            circuit_gal=1.0,
            upper_f=140.0,
            air_at=lambda t: 50.0 + 2.0 * (t - a).total_seconds() / 60.0,
        )
        got, on = loss.loss(a, a + timedelta(minutes=10))
        assert on and got == pytest.approx(1.0 * 8.34 * 89.0)

    def test_overlapping_runs_circulate_once(self) -> None:
        from nwp500.sim.circulation import CirculationLoss

        a = at(0.0)
        s30 = timedelta(seconds=30)

        def total(runs: list[tuple[datetime, datetime]]) -> float:
            loss = CirculationLoss(
                runs,
                flow_gpm=1.0,
                loss_btu_per_gal=159.0,
                circuit_gal=5.0,
                upper_f=140.0,
                air_at=lambda _: 65.0,
            )
            return loss.loss(a, a + 3 * s30)[0]

        both = total([(a, a + 2 * s30), (a + s30, a + 3 * s30)])
        assert both == pytest.approx(total([(a, a + 3 * s30)]))
        assert both == pytest.approx(1.5 * 8.34 * 75.0)
