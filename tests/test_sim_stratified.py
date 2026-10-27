"""The stratified tank (``sim.physics.stratified``): its operators keep
the energy and the second law, the probes read what an estimate was
built from, and a walk is the same however it is cut."""

import dataclasses
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nwp500.sim import default_params
from nwp500.sim.params import params_from_document, params_to_document
from nwp500.sim.physics import stratified as S
from nwp500.sim.units import BTU_PER_WH, WATER_BTU_PER_GAL_F

P = default_params()
L = S.layout(P)
T0 = datetime(2026, 1, 10, 6, 3, 17, tzinfo=UTC)
SITE_VALVE = (53.56, 0.485)

temps = st.floats(40.0, 160.0)
profiles = st.lists(temps, min_size=12, max_size=12).map(
    lambda t: S.TankState(tuple(t))
)
stable = profiles.map(S.mix)
airs = st.floats(30.0, 110.0)
inflows = st.floats(35.0, 90.0)
valves = st.sampled_from([S.NO_VALVE, SITE_VALVE])
#: A layout whose probes feel the water around them, the lower one
#: reading high, and whose top loses heat too.
SPREAD = replace(
    L,
    upper_probe_spread_gal=6.0,
    lower_probe_spread_gal=4.0,
    lower_probe_offset_f=0.7,
    ua_top_btu_hr_f=1.8,
)
layouts = st.sampled_from([L, SPREAD])


def _air(_: datetime) -> float:
    return 65.0


def _energy(state: S.TankState) -> float:
    return S.energy_btu(L, state)


def _monotone(state: S.TankState) -> bool:
    t = state.layers_f
    return all(a <= b + 1e-9 for a, b in pairwise(t))


class TestTheLayout:
    def test_it_is_the_parameters(self) -> None:
        assert L.layers == 12
        assert L.layer_gal * 12 == pytest.approx(63.2)
        assert sum(L.condenser_weights) == pytest.approx(1.0)
        # The condenser wraps the bottom 0.45: layers 0 to 5, the last
        # in part.
        assert [w > 0.0 for w in L.condenser_weights] == [True] * 6 + [
            False
        ] * 6
        assert L.element_layer("upper") == 8
        assert L.element_layer("lower") == 1

    def test_the_conductance_closes_the_gap_on_its_prior(self) -> None:
        """Twelve layers, 10.7 BTU/hr·°F between each pair: the plan's
        prior, from a two-zone gap closing on 60 h."""
        per_pair = L.conductance_btu_hr_f * L.layers
        assert per_pair == pytest.approx(10.7, abs=0.05)

    @pytest.mark.parametrize(
        "change",
        [
            {"layers": 1},
            {"lower_probe": 0.9},
            {"upper_element": 1.2},
            {"condenser_span": (0.5, 0.5)},
            {"ua_btu_hr_f": -1.0},
            {"volume_gal": math.nan},
            {"inlet_mix_gal": math.nan},
            # Both probes in the same end layer.
            {"lower_probe": 0.01, "upper_probe": 0.04},
            {"lower_probe": 0.96, "upper_probe": 0.99},
            {"ua_top_btu_hr_f": -1.0},
            {"lower_probe_spread_gal": -1.0},
            {"upper_probe_spread_gal": math.inf},
            {"lower_probe_offset_f": math.nan},
            {"lower_probe_spread_gal": 70.0},
        ],
    )
    def test_nonsense_is_refused(self, change: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            replace(L, **change)  # type: ignore[arg-type]

    def test_a_document_carries_it(self) -> None:
        doc = params_to_document(P)
        assert doc["tank"]["condenser_span"] == [0.0, 0.45]
        assert params_from_document(doc) == P

    @pytest.mark.parametrize("layers", [12.5, "12", True])
    def test_a_document_holds_whole_layers(self, layers: object) -> None:
        doc = params_to_document(P)
        doc["tank"]["layers"] = layers
        with pytest.raises(ValueError):
            params_from_document(doc)

    def test_a_state_of_another_size_is_refused(self) -> None:
        with pytest.raises(ValueError):
            S.observe(L, S.TankState.uniform(10, 120.0))


class TestMix:
    @given(profiles)
    def test_it_rises_from_the_bottom_with_the_same_heat(
        self, state: S.TankState
    ) -> None:
        mixed = S.mix(state)
        assert _monotone(mixed)
        assert _energy(mixed) == pytest.approx(_energy(state), abs=1e-6)
        assert S.mix(mixed) == mixed

    @given(stable)
    def test_a_stable_tank_is_left_as_it_is(self, state: S.TankState) -> None:
        assert S.mix(state) is state

    def test_an_inversion_pools_to_its_mean(self) -> None:
        state = S.TankState((130.0, 110.0, *([140.0] * 10)))
        assert S.mix(state).layers_f[:2] == (120.0, 120.0)


class TestLose:
    @given(profiles, airs, st.floats(0.0, 72.0))
    def test_no_layer_passes_the_air(
        self, state: S.TankState, air: float, hours: float
    ) -> None:
        after, lost = S.lose(L, state, air, hours)
        for t0, t1 in zip(state.layers_f, after.layers_f, strict=True):
            assert min(t0, air) - 1e-9 <= t1 <= max(t0, air) + 1e-9
        assert _energy(state) - _energy(after) == pytest.approx(lost, abs=1e-6)

    def test_a_month_brings_it_to_the_air(self) -> None:
        w = S.walk(
            L,
            S.TankState.uniform(12, 140.0),
            T0,
            T0 + timedelta(days=30),
            air_f=_air,
        )
        assert all(abs(t - 65.0) < 0.1 for t in w.state.layers_f)
        assert all(t >= 65.0 - 1e-9 for _, s in w.path for t in s.layers_f)

    def test_the_bottom_loses_through_the_bottom(self) -> None:
        after, _ = S.lose(L, S.TankState.uniform(12, 140.0), 65.0, 1.0)
        bottom, *rest = after.layers_f
        assert bottom < min(rest)
        assert len(set(rest)) == 1

    @given(profiles, airs, st.floats(0.0, 72.0))
    def test_the_top_keeps_the_law(
        self, state: S.TankState, air: float, hours: float
    ) -> None:
        after, lost = S.lose(SPREAD, state, air, hours)
        for t0, t1 in zip(state.layers_f, after.layers_f, strict=True):
            assert min(t0, air) - 1e-9 <= t1 <= max(t0, air) + 1e-9
        assert S.energy_btu(SPREAD, state) - S.energy_btu(
            SPREAD, after
        ) == pytest.approx(lost, abs=1e-6)

    def test_the_top_loses_through_the_top(self) -> None:
        lay = replace(SPREAD, ua_bottom_btu_hr_f=0.0)
        after, lost = S.lose(lay, S.TankState.uniform(12, 140.0), 65.0, 1.0)
        *rest, top = after.layers_f
        assert top < min(rest)
        assert len(set(rest)) == 1
        side, _ = S.lose(
            replace(lay, ua_top_btu_hr_f=0.0),
            S.TankState.uniform(12, 140.0),
            65.0,
            1.0,
        )
        assert lost > S.energy_btu(lay, S.TankState.uniform(12, 140.0)) - (
            S.energy_btu(lay, side)
        )


class TestConduct:
    @given(profiles, st.floats(0.0, 500.0))
    def test_it_keeps_the_heat_and_passes_no_neighbour(
        self, state: S.TankState, hours: float
    ) -> None:
        after = S.conduct(L, state, hours)
        assert _energy(after) == pytest.approx(_energy(state), abs=1e-6)
        assert min(state.layers_f) - 1e-9 <= min(after.layers_f)
        assert max(after.layers_f) <= max(state.layers_f) + 1e-9

    def test_it_closes_a_gap_on_its_time_constant(self) -> None:
        """The column's slowest mode decays on mass / (π² · C)."""
        n = L.layers
        state = S.TankState(
            tuple(
                100.0 + 10.0 * math.cos(math.pi * (i + 0.5) / n)
                for i in range(n)
            )
        )
        tau = L.layer_btu_f * n / (math.pi**2 * L.conductance_btu_hr_f)
        after = S.conduct(L, state, tau)
        ratio = (after.layers_f[0] - 100.0) / (state.layers_f[0] - 100.0)
        assert ratio == pytest.approx(math.exp(-1.0), rel=0.02)


class TestHeat:
    @given(stable, st.lists(st.floats(0.0, 5000.0), min_size=12, max_size=12))
    def test_what_goes_in_is_kept(
        self, state: S.TankState, btu: list[float]
    ) -> None:
        after = S.add_heat(L, state, btu)
        assert _energy(after) == pytest.approx(
            _energy(state) + sum(btu), abs=1e-6
        )
        assert _monotone(after)

    def test_an_element_heats_the_water_above_it(self) -> None:
        state = S.TankState(tuple(100.0 + i for i in range(12)))
        after = S.add_heat(L, state, S.element_heat(L, "upper", 2000.0))
        assert after.layers_f[:8] == state.layers_f[:8]
        assert _monotone(after)

    def test_the_condenser_reads_its_span(self) -> None:
        state = S.TankState(tuple(float(i) for i in range(12)))
        w = L.condenser_weights
        assert S.condenser_water_f(L, state) == pytest.approx(
            sum(i * x for i, x in enumerate(w))
        )


class TestFlow:
    @given(profiles, st.floats(0.0, 250.0), inflows)
    def test_what_leaves_is_the_top_of_the_column(
        self, state: S.TankState, gal: float, inflow: float
    ) -> None:
        """The remap keeps the heat: what the tank loses is the water
        that left the top, read off the column before (the plug's, then
        what the inlet zone passed up), less what came in."""
        out = S.flow(L, state, gal, inflow)
        col = S._Column(L, state.layers_f, inflow)
        top, plug = L.volume_gal, col.plug_gal
        if gal <= plug:
            left = col.integral(top) - col.integral(top - gal)
        else:
            left = col.integral(top) - col.integral(col.mix_gal)
            left += col.mix_out(0.0, gal - plug)
        want = (left - gal * inflow) * WATER_BTU_PER_GAL_F
        assert out.heat_btu == pytest.approx(want, abs=1e-6, rel=1e-9)

    @given(stable, inflows)
    def test_a_vanishing_flow_moves_nothing(
        self, state: S.TankState, inflow: float
    ) -> None:
        out = S.flow(L, state, 1e-9, inflow).state
        for x, y in zip(out.layers_f, state.layers_f, strict=True):
            assert x == pytest.approx(y, abs=1e-6)

    def test_many_small_flows_are_one(self) -> None:
        """The inlet zone mixes as the water comes, however it comes:
        cut finer, a flow converges, and to the whole but for the grid's
        remap of each piece (0.15 °F of it with no inlet zone at all)."""
        state = S.mix(
            S.TankState((70.0, 85.0, 100.0, 110.0, 118.0, *([124.0] * 7)))
        )

        def pieces(k: int) -> tuple[float, float]:
            s = state
            for _ in range(k):
                s = S.flow(L, s, 1.0 / k, 60.0).state
            return S.observe(L, s)

        whole, hundred, thousand = pieces(1), pieces(100), pieces(1000)
        for x, y, z in zip(whole, hundred, thousand, strict=True):
            assert y == pytest.approx(z, abs=0.01)
            assert x == pytest.approx(y, abs=0.3)

    @given(stable, st.floats(0.0, 250.0))
    def test_cold_in_stays_stratified_and_in_bounds(
        self, state: S.TankState, gal: float
    ) -> None:
        inflow = min(state.layers_f) - 5.0
        out = S.flow(L, state, gal, inflow).state
        assert _monotone(out)
        assert min(out.layers_f) >= inflow - 1e-9
        assert max(out.layers_f) <= max(state.layers_f) + 1e-9

    def test_three_tank_volumes_bring_the_probes_to_the_inlet(self) -> None:
        state = S.TankState.uniform(12, 140.0)
        out = S.draw(L, state, 3 * 63.2, 55.0)
        assert out.withdrawn_gal == pytest.approx(3 * 63.2)
        u, lo = S.observe(L, out.state)
        assert u == pytest.approx(55.0, abs=0.01)
        assert lo == pytest.approx(55.0, abs=0.01)

    def test_a_hundred_gallons_an_hour_empties_the_top(self) -> None:
        """The two-zone model left the upper probe at 124 °F."""
        draws = [
            S.Delivered(at=T0 + timedelta(seconds=36 * i), gal=1.0, inflow_f=55)
            for i in range(100)
        ]
        w = S.walk(
            L,
            S.TankState.uniform(12, 140.0),
            T0,
            T0 + timedelta(hours=1),
            air_f=_air,
            draws=draws,
        )
        assert w.books.withdrawn_gal == pytest.approx(100.0)
        assert S.observe(L, w.state)[0] < 70.0


class TestDraw:
    @given(stable, st.floats(0.0, 120.0), inflows, valves)
    def test_the_valve_takes_no_more_than_is_delivered(
        self,
        state: S.TankState,
        gal: float,
        inflow: float,
        valve: tuple[float, float],
    ) -> None:
        out = S.draw(L, state, gal, inflow, valve)
        assert 0.0 <= out.withdrawn_gal <= gal + 1e-9
        if valve == S.NO_VALVE:
            assert out.withdrawn_gal == pytest.approx(gal)
        assert out.state == S.flow(L, state, out.withdrawn_gal, inflow).state

    @given(
        temps,
        st.floats(0.0, 40.0),
        st.floats(0.5, 40.0),
        st.floats(0.5, 40.0),
        st.floats(0.0, 1.0),
    )
    def test_split_is_whole_but_for_the_grid(
        self, lower: float, gap: float, a: float, b: float, cold: float
    ) -> None:
        """Two draws are one of both but for the remap of what the first
        left: a front inside a layer moves on as the layer's line, not
        as the front. Within 2 °F at the probes, 1 % of the heat drawn,
        on the profiles ``estimate`` builds, with the mains under the
        tank."""
        state = S.estimate(L, lower + gap, lower)
        inflow = 35.0 + cold * (lower - 35.0)
        whole = S.draw(L, state, a + b, inflow)
        first = S.draw(L, state, a, inflow)
        split = S.draw(L, first.state, b, inflow)
        assert first.withdrawn_gal + split.withdrawn_gal == pytest.approx(
            whole.withdrawn_gal
        )
        assert first.heat_btu + split.heat_btu == pytest.approx(
            whole.heat_btu, rel=0.01, abs=1e-6
        )
        for x, y in zip(
            S.observe(L, whole.state), S.observe(L, split.state), strict=True
        ):
            assert x == pytest.approx(y, abs=2.0)

    @pytest.mark.parametrize("valve", [S.NO_VALVE, SITE_VALVE])
    @pytest.mark.parametrize(
        "profile",
        [
            S.TankState.uniform(12, 140.0),
            S.TankState(tuple(90.0 + 4.5 * i for i in range(12))),
        ],
    )
    def test_the_deliverable_gallons_are_the_draw_down(
        self, profile: S.TankState, valve: tuple[float, float]
    ) -> None:
        """Drawn a quarter gallon at a time, the tap runs under the line
        where ``deliverable_gal`` says."""
        line = 105.0
        want = S.deliverable_gal(L, profile, line, 55.0, valve)
        state, delivered = profile, 0.0
        intercept, slope = valve
        while True:
            out = S.draw(L, state, 0.25, 55.0, valve)
            if min(out.last_f, intercept + slope * out.last_f) < line:
                break
            state, delivered = out.state, delivered + 0.25
        assert delivered == pytest.approx(want, abs=max(1.0, 0.03 * want))

    def test_warm_mains_do_not_hide_a_cold_bottom(self) -> None:
        """The inlet zone's water passes up under the line before the
        mains' does."""
        state = S.TankState((60.0, *([140.0] * 11)))
        got = S.deliverable_gal(L, state, 105.0, 110.0)
        assert got == pytest.approx(S.deliverable_gal(L, state, 105.0, 104.9))
        assert math.isfinite(got)

    def test_mains_at_the_line_never_run_under(self) -> None:
        state = S.TankState.uniform(12, 140.0)
        assert S.deliverable_gal(L, state, 105.0, 110.0) == math.inf

    def test_a_tank_under_the_line_delivers_none(self) -> None:
        state = S.TankState.uniform(12, 100.0)
        assert S.deliverable_gal(L, state, 105.0, 55.0) == 0.0

    def test_the_valve_stretches_the_tank(self) -> None:
        state = S.TankState.uniform(12, 140.0)
        bare = S.deliverable_gal(L, state, 105.0, 55.0)
        valved = S.deliverable_gal(L, state, 105.0, 55.0, SITE_VALVE)
        assert valved > bare > 50.0


class TestTheProbes:
    @given(layouts, st.floats(40.0, 160.0), st.floats(40.0, 160.0))
    def test_an_estimate_reads_as_it_was_built(
        self, lay: S.Layout, upper: float, lower: float
    ) -> None:
        u, lo = S.observe(lay, S.estimate(lay, upper, lower))
        assert u == pytest.approx(upper, abs=1e-9)
        assert lo == pytest.approx(lower, abs=1e-9)

    @given(st.floats(40.0, 160.0), st.floats(0.0, 60.0))
    def test_an_estimate_rises_from_the_bottom(
        self, lower: float, gap: float
    ) -> None:
        assert _monotone(S.estimate(L, lower + gap, lower))

    @given(layouts, profiles, temps, temps, st.floats(0.0, 1.0))
    def test_assimilating_moves_the_reading_by_the_gain(
        self,
        lay: S.Layout,
        state: S.TankState,
        upper: float,
        lower: float,
        gain: float,
    ) -> None:
        u0, l0 = S.observe(lay, state)
        u1, l1 = S.observe(lay, S.assimilate(lay, state, upper, lower, gain))
        assert u1 == pytest.approx(u0 + gain * (upper - u0), abs=1e-9)
        assert l1 == pytest.approx(l0 + gain * (lower - l0), abs=1e-9)

    @given(layouts)
    def test_the_weights_are_shares(self, lay: S.Layout) -> None:
        for w in (lay.upper_weights, lay.lower_weights):
            assert all(x >= 0.0 for x in w)
            assert sum(w) == pytest.approx(1.0, abs=1e-12)

    def test_a_vanishing_spread_reads_the_point(self) -> None:
        for spread in (1e-9, 1e-3):
            near = replace(L, lower_probe_spread_gal=spread)
            for a, b in zip(near.lower_weights, L.lower_weights, strict=True):
                assert a == pytest.approx(b, abs=1e-6)

    def test_a_spread_feels_the_water_below(self) -> None:
        """A cold bottom the lower probe's point does not reach moves a
        probe that feels the water around it."""
        state = S.TankState((70.0, *([140.0] * 11)))
        assert S.observe(L, state)[1] == 140.0
        assert (
            S.observe(replace(L, lower_probe_spread_gal=6.0), state)[1] < 139.0
        )

    def test_the_offset_reads_above_the_water(self) -> None:
        state = S.TankState.uniform(12, 130.0)
        assert S.observe(SPREAD, state) == pytest.approx((130.0, 130.7))


def _heating(at: datetime) -> S.Heating:
    return S.Heating(
        compressor=S.Compressor(
            params=P.compressor,
            on_at=at + timedelta(hours=2),
            heats_at=at + timedelta(hours=2, minutes=10),
            off_at=at + timedelta(hours=4),
        ),
        elements=(
            S.Element(
                zone="upper",
                watts=P.element.element_w,
                on_at=at + timedelta(hours=6),
                off_at=at + timedelta(hours=6, minutes=12),
                lag=timedelta(minutes=P.element.upper_dead_time_min),
            ),
        ),
    )


def _day(state: S.TankState, **kw: object) -> S.Walked:
    """A day of everything: heat pump, element, draws, a flow."""
    args: dict[str, object] = {
        "air_f": lambda t: 60.0 + 10.0 * (t.hour / 24.0),
        "heating": _heating(T0),
        "draws": [
            S.Delivered(at=T0 + timedelta(hours=h), gal=g, inflow_f=58.0)
            for h, g in ((1.3, 12.0), (9.1, 25.0), (15.0, 3.0))
        ],
        "flowing": [
            S.Flowing(
                start=T0 + timedelta(hours=12),
                end=T0 + timedelta(hours=12, minutes=4),
                gpm=1.4,
                inflow_f=80.0,
            )
        ],
        "valve": SITE_VALVE,
    }
    args.update(kw)
    end = args.pop("end", T0 + timedelta(hours=24))
    start = args.pop("start", T0)
    return S.walk(L, state, start, end, **args)  # type: ignore[arg-type]


class TestTheWalk:
    @settings(max_examples=25, deadline=None)
    @given(stable)
    def test_its_books_close(self, state: S.TankState) -> None:
        w = _day(state)
        assert _energy(w.state) - _energy(state) == pytest.approx(
            w.books.net_btu, abs=1e-6
        )
        assert _monotone(w.state)

    def test_its_steps_are_its_books(self) -> None:
        w = _day(S.estimate(L, 125.0, 100.0))
        assert len(w.steps) == len(w.path) - 1
        total = sum(w.steps, S.Books())
        for f in dataclasses.fields(S.Books):
            assert getattr(total, f.name) == pytest.approx(
                getattr(w.books, f.name), abs=1e-6
            )

    def test_uncredited_heat_is_charged_and_not_given(self) -> None:
        start = S.estimate(L, 125.0, 100.0)
        heating = _heating(T0)
        withheld = _day(
            start, heating=dataclasses.replace(heating, credited=False)
        )
        none = _day(start, heating=S.Heating())
        # Alike but for the grid: a walk steps finer while something
        # runs.
        assert withheld.state.layers_f == pytest.approx(
            none.state.layers_f, abs=0.2
        )
        assert withheld.books.compressor_btu == 0.0
        assert withheld.books.element_btu == 0.0
        assert withheld.books.compressor_wh > 0.0
        assert withheld.books.element_wh == pytest.approx(
            P.element.element_w * 12 / 60
        )

    def test_a_compressors_heat_scales(self) -> None:
        start = S.estimate(L, 125.0, 100.0)
        c = _heating(T0).compressor
        assert c is not None
        one = _day(start, heating=S.Heating(compressor=c), draws=(), flowing=())
        half = _day(
            start,
            heating=S.Heating(compressor=dataclasses.replace(c, scale=0.5)),
            draws=(),
            flowing=(),
        )
        assert half.books.compressor_wh == pytest.approx(
            one.books.compressor_wh, rel=0.05
        )
        assert half.books.compressor_btu < 0.6 * one.books.compressor_btu

    def test_an_elements_heat_is_its_electricity(self) -> None:
        w = _day(S.estimate(L, 125.0, 100.0), draws=(), flowing=())
        assert w.books.element_wh == pytest.approx(
            P.element.element_w * 12 / 60
        )
        assert w.books.element_btu == pytest.approx(
            w.books.element_wh * BTU_PER_WH
        )

    def test_the_heat_pump_heats_by_its_map(self) -> None:
        w = _day(S.estimate(L, 125.0, 100.0), draws=(), flowing=())
        cop = w.books.compressor_btu / (w.books.compressor_wh * BTU_PER_WH)
        assert 2.5 < cop < 4.5

    @settings(max_examples=15, deadline=None)
    @given(stable, st.integers(1, 143))
    def test_split_on_the_grid_is_whole(
        self, state: S.TankState, k: int
    ) -> None:
        whole = _day(state)
        cut = S._grid_after(T0, S.IDLE_STEP) + S.IDLE_STEP * (k - 1)
        first = _day(state, end=cut)
        rest = _day(first.state, start=cut)
        assert rest.state == whole.state
        assert (first.books + rest.books).net_btu == pytest.approx(
            whole.books.net_btu, abs=1e-6
        )

    def test_it_is_deterministic(self) -> None:
        state = S.estimate(L, 125.0, 100.0)
        assert _day(state) == _day(state)

    @pytest.mark.parametrize(
        ("flowing", "within"),
        [((), 0.02), (None, 0.05)],
    )
    def test_halving_the_step_moves_the_probes_little(
        self, flowing: tuple[S.Flowing, ...] | None, within: float
    ) -> None:
        """Over a day, 0.02 °F; a flow is remapped once a step, so its
        front smears a little more on the finer steps."""
        state = S.estimate(L, 125.0, 100.0)
        kw: dict[str, object] = {} if flowing is None else {"flowing": ()}
        coarse = _day(state, **kw)
        fine = _day(
            state,
            idle_step=timedelta(minutes=5),
            active_step=timedelta(seconds=30),
            **kw,
        )
        for x, y in zip(
            S.observe(L, coarse.state), S.observe(L, fine.state), strict=True
        ):
            assert x == pytest.approx(y, abs=within)

    def test_it_stops_where_the_stop_holds(self) -> None:
        state = S.estimate(L, 125.0, 100.0)

        def hot(s: S.TankState) -> bool:
            return S.observe(L, s)[1] >= 110.0

        w = _day(state, draws=(), flowing=(), stop=hot)
        assert w.stopped and hot(w.state)
        before = _day(state, draws=(), flowing=(), end=w.end - S.CUT_RESOLUTION)
        assert not hot(before.state)
        assert w.path[-1] == (w.end, w.state)

    def test_a_draw_that_meets_the_stop_ends_it_there(self) -> None:
        state = S.TankState.uniform(12, 140.0)
        at = T0 + timedelta(hours=1)
        w = S.walk(
            L,
            state,
            T0,
            T0 + timedelta(hours=3),
            air_f=_air,
            draws=[S.Delivered(at=at, gal=40.0, inflow_f=55.0)],
            stop=lambda s: S.observe(L, s)[1] < 105.0,
        )
        assert w.stopped and w.end == at
        assert w.books.withdrawn_gal == pytest.approx(40.0)

    def test_steps_follow_the_clock(self) -> None:
        w = S.walk(
            L,
            S.TankState.uniform(12, 120.0),
            T0,
            T0 + timedelta(hours=1),
            air_f=_air,
        )
        ends = [t for t, _ in w.path[1:-1]]
        assert all(t.minute % 10 == 0 and t.second == 0 for t in ends)

    @pytest.mark.parametrize("step", [timedelta(0), timedelta(minutes=-10)])
    def test_steps_are_positive(self, step: timedelta) -> None:
        with pytest.raises(ValueError):
            S.walk(
                L,
                S.TankState.uniform(12, 120.0),
                T0,
                T0 + timedelta(hours=1),
                air_f=_air,
                idle_step=step,
            )

    def test_naive_instants_are_refused(self) -> None:
        with pytest.raises(ValueError):
            S.walk(
                L,
                S.TankState.uniform(12, 120.0),
                T0.replace(tzinfo=None),
                T0.replace(tzinfo=None) + timedelta(hours=1),
                air_f=_air,
            )
