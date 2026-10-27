"""Hot water at the tap through the API: the heat book in a simulation,
the delivery along it, draw windows, and ``readiness``.

``simulate`` with a book is held to the engine called by hand with the
book's ledger, as ``test_sim_api`` holds it without one; the functions
it calls are held to their source in ``test_sim_readiness`` and
``test_sim_book``.
"""

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from nwp500 import sim_adapters as sa
from nwp500.sim import (
    Draw,
    DrawWindow,
    Environment,
    HeaterState,
    History,
    Loads,
    Scenario,
    Settings,
    full_tank_book,
    readiness,
    simulate,
    site_example_params,
)
from nwp500.sim.book import (
    BookedHeatLedger,
    deliverable_from_heat,
    full_tank,
)
from nwp500.sim.codec import (
    result_to_document,
    scenario_from_document,
    scenario_to_document,
)
from nwp500.sim.decay import Draw as DecayDraw
from nwp500.sim.delivery import (
    EXAMPLE_EVIDENCE,
    booked_deliverable,
    deliverable,
    delivery_along,
    probes_gal,
    with_example_evidence,
)
from nwp500.sim.engine import Heater
from nwp500.sim.engine import simulate as walk
from nwp500.sim.params import (
    HeaterParams,
    ReadinessParams,
    params_from_document,
    params_to_document,
    unknown_fields,
)
from nwp500.sim.physics.heat_pump import start_hold_min
from nwp500.sim.tank_physics import TankPhysics
from nwp500.unit_system import reset_unit_system, set_unit_system

T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
FULL = (140.5, 139.6)


def at(h: float) -> datetime:
    return T0 + timedelta(hours=h)


#: 75 delivered gallons over half an hour from 19:30, in 2.5 gal minutes.
BIG = tuple(
    Draw(at=at(0.5) + timedelta(minutes=i), gallons=2.5) for i in range(30)
)
BIG_WINDOW = DrawWindow(start=at(0.5), end=at(1.0), expected_gal=75.0)


@pytest.fixture(scope="module")
def params() -> HeaterParams:
    """One installation's parameters, its mixing valve included: the
    numbers below are that site's."""
    return site_example_params()


def _no_evidence(p: HeaterParams) -> HeaterParams:
    return replace(p, readiness=replace(p.readiness, evidence=()))


@pytest.fixture(autouse=True)
def _units() -> Iterator[None]:
    yield
    reset_unit_system()


def _scenario(**kw: Any) -> Scenario:
    base: dict[str, Any] = {
        "start": T0,
        "horizon": timedelta(hours=6),
        "tz": "UTC",
        "state": HeaterState(upper_f=FULL[0], lower_f=FULL[1]),
        "settings": Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
        "history": History(compressor_stopped_at=at(-1.0), heated_at=at(-1.0)),
        "environment": Environment(ambient_f=68.0, humidity=48.0),
        "loads": Loads(draws=BIG, windows=(BIG_WINDOW,)),
    }
    base.update(kw)
    return Scenario(**base)


def _by_hand(params: HeaterParams, s: Scenario, book: Any) -> Any:
    """The engine called directly, with the book's ledger and the
    windows' edges marked, on a flat ambient."""
    stamps = pd.date_range(at(-2), s.until + timedelta(hours=24), freq="1h")
    frame = pd.DataFrame({"ambient_f": [68.0] * len(stamps)}, index=stamps)
    physics = TankPhysics(
        params,
        frame,
        s.environment.humidity,
        draws_on=True,
        tau_gap_hours=params.tank.stratification_gap_tau_h,  # type: ignore[arg-type]
    )
    return walk(
        start=s.start,
        upper_f=s.state.upper_f,
        lower_f=s.state.lower_f,
        running=False,
        until=s.until,
        setpoint_f=s.settings.setpoint_f,
        heater=Heater(hp_lower_on_f=105.0, element=params.element),
        physics=physics,
        draws=[(d.at, d.gallons) for d in s.loads.draws],
        marks=[x for w in s.loads.windows for x in (w.start, w.end)],
        stopped_at=s.history.compressor_stopped_at,
        heated_at=s.history.heated_at,
        start_hold=lambda off: start_hold_min(params.compressor, off),
        controller=params.controller,
        ledger=BookedHeatLedger(book, physics.ambient.at, params.book_terms()),
    )


class TestTheBookInASimulation:
    def test_simulate_with_a_book_is_the_engine_with_its_ledger(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        book = full_tank_book(*FULL, params.book)
        assert simulate(s, params, book=book).simulation == _by_hand(
            params, s, book
        )

    def test_the_book_takes_the_upper_zone_down_through_a_big_draw(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        with_book = simulate(s, params, book=full_tank_book(*FULL, params.book))
        without = simulate(s, params)
        assert min(p.upper_f for p in with_book.points) < 105.0
        assert min(p.upper_f for p in without.points) > 130.0

    def test_energy_saver_starts_on_a_draw_with_a_book(
        self, params: HeaterParams
    ) -> None:
        """With a book the draw is taken at its instant, outside a
        coast; its drop still releases Energy Saver's held lower trigger
        (2026-09-21: the upper tank over the setpoint, the lower under
        its setting, a draw started it)."""
        held: dict[str, Any] = {
            "state": HeaterState(upper_f=126.0, lower_f=87.0),
            "settings": Settings(setpoint_f=107.6, hp_lower_on_f=104.9, mode=3),
            "history": History(
                compressor_stopped_at=at(-8.0), heated_at=at(-8.0)
            ),
        }
        s = _scenario(
            **held, loads=Loads(draws=(Draw(at=at(1.0), gallons=5.0),))
        )
        book = full_tank_book(126.0, 87.0, params.book)
        for b in (None, book):
            heating = simulate(s, params, book=b).simulation.heating
            assert heating and heating[0].start.at == at(1.0)
        quiet = _scenario(**held, loads=Loads())
        assert simulate(quiet, params, book=book).simulation.heating == []

    def test_a_release_the_lockout_defers_survives_the_next_draw(
        self, params: HeaterParams
    ) -> None:
        """A draw releases Energy Saver's held lower trigger inside the
        restart lockout; the next draw, a minute on, leaves the lower
        zone over its setting. The start still comes when the lockout
        ends."""
        stop = at(1.0) - timedelta(minutes=2)
        second = at(1.0) + timedelta(minutes=1)

        class SecondLeavesItWarm(TankPhysics):
            def draw(
                self, at: datetime, upper_f: float, lower_f: float, gal: float
            ) -> tuple[float, float]:
                upper, lower = super().draw(at, upper_f, lower_f, gal)
                return (upper, 106.0) if at == second else (upper, lower)

        stamps = pd.date_range(at(-2), at(30), freq="1h")
        frame = pd.DataFrame({"ambient_f": [68.0] * len(stamps)}, index=stamps)
        physics = SecondLeavesItWarm(
            params,
            frame,
            48.0,
            draws_on=True,
            tau_gap_hours=params.tank.stratification_gap_tau_h,  # type: ignore[arg-type]
        )
        book = full_tank_book(126.0, 87.0, params.book)
        sim = walk(
            start=stop + timedelta(minutes=1),
            upper_f=126.0,
            lower_f=87.0,
            running=False,
            until=at(3.0),
            setpoint_f=107.6,
            heater=Heater(
                hp_lower_on_f=104.9, mode="energy_saver", element=params.element
            ),
            physics=physics,
            draws=[(at(1.0), 5.0), (second, 1.0)],
            stopped_at=stop,
            heated_at=at(-8.0),
            controller=params.controller,
            ledger=BookedHeatLedger(
                book, physics.ambient.at, params.book_terms()
            ),
        )
        lockout = timedelta(seconds=params.controller.restart_lockout_s)
        assert sim.heating and sim.heating[0].start.at == stop + lockout

    def test_a_release_by_circulation_in_the_lockout_survives_a_draw(
        self, params: HeaterParams
    ) -> None:
        """A circulation run releases Energy Saver's held lower trigger
        inside the restart lockout, and a draw after it leaves the lower
        zone over its setting: the start still comes when the lockout
        ends."""
        stop = at(1.0) - timedelta(minutes=2)
        draw = at(1.0) + timedelta(minutes=3)
        runs = [
            DecayDraw(
                at=at(1.0),
                gallons=2.0,
                inflow_f=70.0,
                until=at(1.0) + timedelta(minutes=2),
                gpm=1.0,
            )
        ]

        class DrawLeavesItWarm(TankPhysics):
            def draw(
                self, at: datetime, upper_f: float, lower_f: float, gal: float
            ) -> tuple[float, float]:
                upper, _ = super().draw(at, upper_f, lower_f, gal)
                return upper, 106.0

        stamps = pd.date_range(at(-2), at(30), freq="1h")
        frame = pd.DataFrame({"ambient_f": [68.0] * len(stamps)}, index=stamps)
        physics = DrawLeavesItWarm(
            params,
            frame,
            48.0,
            draws_on=True,
            tau_gap_hours=params.tank.stratification_gap_tau_h,  # type: ignore[arg-type]
            flowing_draws=lambda a, b: [
                r for r in runs if r.at < b and (r.until or r.at) > a
            ],
        )
        book = full_tank_book(126.0, 87.0, params.book)
        sim = walk(
            start=stop + timedelta(minutes=1),
            upper_f=126.0,
            lower_f=87.0,
            running=False,
            until=at(3.0),
            setpoint_f=107.6,
            heater=Heater(
                hp_lower_on_f=104.9, mode="energy_saver", element=params.element
            ),
            physics=physics,
            draws=[(draw, 1.0)],
            stopped_at=stop,
            heated_at=at(-8.0),
            controller=params.controller,
            ledger=BookedHeatLedger(
                book, physics.ambient.at, params.book_terms()
            ),
        )
        lockout = timedelta(seconds=params.controller.restart_lockout_s)
        assert sim.heating and sim.heating[0].start.at == stop + lockout

    def test_a_draw_moves_the_lower_zone_at_once_as_without_one(
        self, params: HeaterParams
    ) -> None:
        """A draw of a few gallons takes the lower zone down at its
        onset by its calibrated response, with a book as without one."""
        s = _scenario(loads=Loads(draws=(Draw(at=at(0.5), gallons=5.0),)))
        book = full_tank_book(*FULL, params.book)
        booked = simulate(s, params, book=book).points
        plain = {p.at: p.lower_f for p in simulate(s, params).points}
        before, after = [p for p in booked if p.at == at(0.5)]
        assert after.lower_f < before.lower_f - 1.0
        later = [p for p in booked if p.at > at(0.5)]
        assert later
        for p in later:
            assert p.lower_f == pytest.approx(plain[p.at], abs=1e-9)

    def test_without_a_book_the_result_says_so(
        self, params: HeaterParams
    ) -> None:
        r = simulate(_scenario(), params)
        assert "no_heat_book" in r.reasons
        assert r.booked is None
        with_book = simulate(
            _scenario(), params, book=full_tank_book(*FULL, params.book)
        )
        assert "no_heat_book" not in with_book.reasons
        assert with_book.booked is not None

    def test_an_aged_book_says_so(self, params: HeaterParams) -> None:
        book = replace(full_tank_book(*FULL, params.book), anchor_age_h=20.0)
        assert (
            "heat_book_aged" in simulate(_scenario(), params, book=book).reasons
        )

    def test_the_delivery_is_the_books_or_the_zones(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        draws = [(d.at, d.gallons) for d in s.loads.draws]
        r = simulate(s, params)
        assert list(r.delivery) == delivery_along(
            r.points, draws, None, params.readiness, params.book_terms()
        )
        b = simulate(s, params, book=full_tank_book(*FULL, params.book))
        assert list(b.delivery) == delivery_along(
            b.points, draws, b.booked, params.readiness, params.book_terms()
        )
        assert len(b.delivery) == len(b.points)


class TestDrawWindows:
    def test_a_window_the_tank_cannot_supply_runs_cold_with_a_book(
        self, params: HeaterParams
    ) -> None:
        r = simulate(
            _scenario(), params, book=full_tank_book(*FULL, params.book)
        )
        (w,) = r.windows
        assert w.depleted
        assert w.delivery_min_f < params.readiness.line_f
        assert w.margin_gal is not None and w.margin_gal < 0.0
        assert w.deliverable_gal == pytest.approx(53.0, abs=1.0)

    def test_without_one_the_margin_still_says_it_is_short(
        self, params: HeaterParams
    ) -> None:
        """The zones alone hold the upper zone up through the draw, so
        the delivery does not fall; the probes' heat still prices the
        window short."""
        (w,) = simulate(_scenario(), params).windows
        assert not w.depleted
        assert w.margin_gal is not None and w.margin_gal < -20.0

    def test_a_window_the_tank_can_supply_does_not(
        self, params: HeaterParams
    ) -> None:
        small = tuple(
            Draw(at=at(0.5) + timedelta(minutes=i), gallons=1.6)
            for i in range(8)
        )
        window = DrawWindow(start=at(0.5), end=at(0.75), expected_gal=12.8)
        s = _scenario(loads=Loads(draws=small, windows=(window,)))
        (w,) = simulate(
            s, params, book=full_tank_book(*FULL, params.book)
        ).windows
        assert not w.depleted
        assert w.margin_gal is not None and w.margin_gal > 20.0

    def test_a_windows_edges_are_on_the_path(
        self, params: HeaterParams
    ) -> None:
        r = simulate(_scenario(), params)
        instants = {p.at for p in r.points}
        assert BIG_WINDOW.start in instants and BIG_WINDOW.end in instants

    def test_a_window_must_end_after_it_starts(self) -> None:
        with pytest.raises(ValueError, match="ends after"):
            DrawWindow(start=at(1.0), end=at(1.0))


class TestReadiness:
    def test_with_a_book_the_booked_heat_answers(
        self, params: HeaterParams
    ) -> None:
        d = readiness(
            HeaterState(upper_f=FULL[0], lower_f=FULL[1]),
            Settings(setpoint_f=140.9),
            params,
            book=full_tank_book(*FULL, params.book),
        )
        assert d.basis == "energy"
        assert d.gal == pytest.approx(53.1, abs=0.05)

    def test_without_one_a_full_tank_reads_as_its_book(
        self, params: HeaterParams
    ) -> None:
        """The probes' heat is the book's anchor: nothing taken off."""
        d = readiness(
            HeaterState(upper_f=FULL[0], lower_f=FULL[1]),
            Settings(setpoint_f=140.9),
            params,
        )
        assert d.basis == "evidence"
        assert d.gal == pytest.approx(53.1, abs=0.05)

    @pytest.mark.parametrize(
        "running", [{"compressor_running": True}, {"element_running": True}]
    )
    def test_a_running_heater_reads_the_same(
        self, params: HeaterParams, running: dict[str, bool]
    ) -> None:
        """Heating only adds heat: the probes answer as they read."""
        settings = Settings(setpoint_f=140.9)
        bare = _no_evidence(params)
        for upper, lower in (FULL, (136.4, 111.4), (128.0, 95.0)):
            heating = readiness(
                HeaterState(upper_f=upper, lower_f=lower, **running),
                settings,
                bare,
            )
            idle = readiness(
                HeaterState(upper_f=upper, lower_f=lower), settings, bare
            )
            assert heating.gal == idle.gal > params.readiness.delivered_lag_gal
            assert heating.basis == "probes"

    def test_any_state_reads_its_probes(self, params: HeaterParams) -> None:
        state = HeaterState(upper_f=135.86, lower_f=135.5)
        settings = Settings(setpoint_f=140.9)
        bare = _no_evidence(params)
        lag = params.readiness.delivered_lag_gal
        ep = params.book_terms()
        for upper, lower in ((135.86, 135.5), (135.86, 104.0)):
            d = readiness(
                HeaterState(upper_f=upper, lower_f=lower), settings, bare
            )
            gal = probes_gal(upper, lower, params.readiness, ep)
            assert d.basis == "probes"
            assert d.gal == pytest.approx(gal + lag, abs=0.05)
        # The evidence answers only where it shows more: 23.6 gal here,
        # under the probes' 44.7.
        given = replace(bare, readiness=with_example_evidence(bare.readiness))
        assert given == params
        assert readiness(state, settings, given).gal == pytest.approx(
            probes_gal(135.86, 135.5, params.readiness, ep) + lag, abs=0.05
        )

    def test_the_lag_is_the_installations(self, params: HeaterParams) -> None:
        state = HeaterState(upper_f=FULL[0], lower_f=FULL[1])
        settings = Settings(setpoint_f=140.9)
        none = replace(
            params, readiness=replace(params.readiness, delivered_lag_gal=0.0)
        )
        assert readiness(state, settings, params).gal - readiness(
            state, settings, none
        ).gal == pytest.approx(params.readiness.delivered_lag_gal)


class TestFromTheProbes:
    """No book: the tank's heat as its two probes place it, with the lag
    on it. On one installation's book terms."""

    EP = site_example_params().book_terms()
    P = ReadinessParams()

    def answer(self, upper: float, lower: float, **kw: Any) -> Any:
        return deliverable(upper, lower, self.P, ep=self.EP, **kw)

    def test_a_stratified_tank_reads_its_probes_heat(self) -> None:
        """A drawdown from 136.4/111.4 °F delivered 31.1 gal."""
        d = self.answer(136.4, 111.4)
        assert d.basis == "probes"
        assert d.gal == pytest.approx(34.5, abs=0.05)

    def test_a_uniform_full_tank_reads_all_its_heat(self) -> None:
        """Nothing taken off: the same answer as a book anchored on the
        same probes."""
        inlet = self.EP.inlet_default_f
        heat = full_tank(141.8, 141.5, inlet, self.EP).heat_btu
        d = self.answer(141.8, 141.5)
        assert d.gal == pytest.approx(
            deliverable_from_heat(heat, 141.8, inlet, self.EP)
            + self.P.delivered_lag_gal,
            abs=0.05,
        )
        book = full_tank_book(141.8, 141.5, self.EP)
        assert (
            d.gal == booked_deliverable(book, 141.8, 141.5, self.P, self.EP).gal
        )

    def test_a_cold_lower_probe_is_not_capped(self) -> None:
        d = self.answer(141.26, 89.6)
        gal = probes_gal(141.26, 89.6, self.P, self.EP)
        assert gal > 6.5
        assert d.gal == pytest.approx(gal + self.P.delivered_lag_gal, abs=0.05)

    def test_from_the_line_down(self) -> None:
        line = self.P.line_f
        assert probes_gal(line, 95.0, self.P, self.EP) == 0.0
        assert self.answer(line, 95.0).gal == self.P.delivered_lag_gal
        assert self.answer(line - 0.1, 104.0).gal == 0.0
        assert probes_gal(line - 0.1, 150.0, self.P, self.EP) == 0.0

    def test_evidence_answers_where_it_shows_more(self) -> None:
        more = replace(self.P, evidence=((110.0, 100.0, 40.0),))
        d = deliverable(116.6, 109.6, more, ep=self.EP)
        assert d.basis == "evidence"
        assert d.gal == 40.0 + self.P.delivered_lag_gal
        given = with_example_evidence(self.P)
        d = deliverable(116.6, 109.6, given, ep=self.EP)
        assert d.basis == "evidence"
        assert d.gal == self.answer(116.6, 109.6).gal


class TestTheParameters:
    def test_readiness_and_the_book_round_trip_as_a_document(
        self, params: HeaterParams
    ) -> None:
        p = replace(params, readiness=with_example_evidence(params.readiness))
        doc = json.loads(json.dumps(params_to_document(p)))
        assert params_from_document(doc) == p
        assert doc["readiness"]["evidence"][0] == list(EXAMPLE_EVIDENCE[0])

    def test_a_document_without_them_takes_the_defaults(
        self, params: HeaterParams
    ) -> None:
        doc = params_to_document(params)
        del doc["readiness"], doc["book"]
        assert params_from_document(doc) == replace(
            params, readiness=ReadinessParams(), book=params.book
        )

    def test_a_document_from_before_the_map_is_refused(
        self, params: HeaterParams
    ) -> None:
        """A ``heater-params/1`` document ran the refrigerant cycle: it
        is refitted, not read."""
        doc = {**params_to_document(params), "schema": "heater-params/1"}
        with pytest.raises(ValueError, match="calibrate again"):
            params_from_document(doc)

    @pytest.mark.parametrize(
        ("part", "name", "value", "match"),
        [
            (None, "unfitted", None, "unfitted is None, not a list"),
            (None, "unfitted", 5, "unfitted is 5, not a list"),
            (None, "unfitted", "book", "not a list"),
            ("draw", "domain_upper_f", 5, "domain_upper_f is 5, not a list"),
            ("draw", "domain_upper_f", [1.0], "has 1 values, not 2"),
            ("readiness", "evidence", 5, "evidence is 5, not a list"),
            ("readiness", "evidence", [1.0], r"evidence\[0\] is 1.0"),
            ("tank", "volume_gal", "65", "volume_gal is '65', not a number"),
            ("tank", "volume_gal", None, "not a number"),
            ("tank", "volume_gal", True, "not a number"),
        ],
    )
    def test_a_value_of_the_wrong_type_is_a_value_error(
        self,
        params: HeaterParams,
        part: str | None,
        name: str,
        value: object,
        match: str,
    ) -> None:
        doc = params_to_document(params)
        (doc if part is None else doc[part])[name] = value
        with pytest.raises(ValueError, match=match):
            params_from_document(doc)

    def test_a_newer_field_is_named_and_read_past(
        self, params: HeaterParams
    ) -> None:
        doc = json.loads(json.dumps(params_to_document(params)))
        doc["readiness"]["newer_f"] = 1.0
        assert unknown_fields(doc) == ["readiness.newer_f"]
        assert params_from_document(doc) == params

    def test_a_part_that_is_not_an_object_has_no_unknown_fields(
        self, params: HeaterParams
    ) -> None:
        doc = {**params_to_document(params), "tank": 5}
        assert unknown_fields(doc) == []
        with pytest.raises(ValueError, match="part 'tank' is not an object"):
            params_from_document(doc)

    def test_a_null_range_and_a_whole_number_are_read(
        self, params: HeaterParams
    ) -> None:
        doc = params_to_document(params)
        doc["draw"]["domain_upper_f"] = None
        doc["tank"]["volume_gal"] = 50
        got = params_from_document(doc)
        assert got.draw.domain_upper_f is None
        assert got.tank.volume_gal == 50

    def test_the_example_evidence_is_refused_at_another_line(self) -> None:
        with pytest.raises(ValueError, match="105"):
            with_example_evidence(ReadinessParams(line_f=110.0))

    def test_the_line_moves_the_answer(self, params: HeaterParams) -> None:
        state = HeaterState(upper_f=108.0, lower_f=100.0)
        settings = Settings(setpoint_f=140.9)
        p = replace(params, readiness=with_example_evidence(params.readiness))
        higher = replace(p, readiness=replace(p.readiness, line_f=110.0))
        assert readiness(state, settings, higher).gal == 0.0


class TestTheAdaptersAndTheCodec:
    def test_windows_in_the_preferred_units(self) -> None:
        set_unit_system("metric")
        loads = sa.loads(
            [(at(0.5), 37.85411784)], windows=[(at(0.5), at(1.0), 75.70823568)]
        )
        assert loads.draws[0].gallons == pytest.approx(10.0)
        assert loads.windows[0].expected_gal == pytest.approx(20.0)

    def test_the_path_carries_the_delivery(self, params: HeaterParams) -> None:
        r = simulate(
            _scenario(), params, book=full_tank_book(*FULL, params.book)
        )
        set_unit_system("metric")
        path = sa.path(r)
        assert path[-1].delivery == pytest.approx(
            (r.delivery[-1] - 32.0) * 5.0 / 9.0
        )

    def test_a_scenario_with_windows_round_trips(
        self, params: HeaterParams
    ) -> None:
        s = _scenario()
        back, _ = scenario_from_document(json.dumps(scenario_to_document(s)))
        assert back == s

    def test_a_result_document_holds_the_delivery_and_the_windows(
        self, params: HeaterParams
    ) -> None:
        r = simulate(
            _scenario(), params, book=full_tank_book(*FULL, params.book)
        )
        doc = result_to_document(r)
        assert json.loads(json.dumps(doc)) == doc
        assert doc["delivery"] == list(r.delivery)
        assert doc["windows"][0]["depleted"] is True
