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
from nwp500.sim.params import (
    LossParams,
    TankParams,
    params_from_document,
    params_to_document,
)
from nwp500.sim.physics import stratified as S
from nwp500.sim.units import BTU_PER_WH, WATER_BTU_PER_GAL_F

#: The layered tank's priors: the operators' tests are the physics',
#: not one heater's fit.
P = replace(default_params(), tank=TankParams(), loss=LossParams())
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

    @staticmethod
    def _upper_climb(height: float) -> float:
        """The upper probe's climb under the upper element from a mixed
        120 °F tank, °F/min, the element's height ``height``."""
        lay = S.layout(
            replace(P, tank=replace(P.tank, upper_element_height=height))
        )
        on = S.Element(
            zone="upper",
            watts=P.element.element_w,
            on_at=T0,
            off_at=T0 + timedelta(minutes=10),
        )
        w = S.walk(
            lay,
            S.TankState.uniform(L.layers, 120.0),
            T0,
            T0 + timedelta(minutes=10),
            air_f=_air,
            heating=S.Heating(elements=(on,)),
        )
        return (S.observe(lay, w.state)[0] - 120.0) / 10.0

    def test_an_elements_height_acts_in_whole_layers(self) -> None:
        # Its heat turns its layer over into the ones above: anywhere in
        # a layer heats the same water.
        assert self._upper_climb(0.68) == self._upper_climb(0.74)
        assert self._upper_climb(0.76) == self._upper_climb(0.82)
        # A layer higher, 5.3 gal less water to heat.
        assert self._upper_climb(0.76) > 1.2 * self._upper_climb(0.74)

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


class TestStir:
    """A compressor's start pools the water the condenser wraps with the
    water below it: the same heat, the lower probe dipping to the pool."""

    @given(stable)
    def test_it_keeps_the_heat_and_rises_from_the_bottom(
        self, state: S.TankState
    ) -> None:
        after = S.stir(L, state)
        assert _energy(after) == pytest.approx(_energy(state), abs=1e-6)
        assert _monotone(after)
        still = [i for i, w in enumerate(L.stir_weights) if w == 0.0]
        for i in still:
            assert after.layers_f[i] == pytest.approx(
                state.layers_f[i], abs=1e-9
            )

    def test_it_reaches_the_top_of_the_condenser(self) -> None:
        # Whole layers below the condenser's top, the share of the one
        # its top lies in, none above: continuous in the span.
        low, high = L.condenser_span
        w = L.stir_weights
        top = int(high * L.layers)
        assert w[:top] == (1.0,) * top
        assert w[top] == pytest.approx(high * L.layers - top)
        assert w[top + 1 :] == (0.0,) * (L.layers - top - 1)
        to_bottom = replace(L, condenser_span=(0.0, high))
        assert to_bottom.stir_weights == w
        higher = replace(L, condenser_span=(low, 0.75))
        assert higher.stir_weights == (1.0,) * 9 + (0.0,) * 3

    def test_a_cold_bottom_dips_the_lower_probe_and_holds_it(self) -> None:
        # A tank that stood 12 hours: its bottom has cooled through the
        # bottom's loss. The compressor's start stirs that cold up to
        # the lower probe, which then climbs back only once the
        # condenser has heated the pool past its reading.
        lay = replace(L, ua_bottom_btu_hr_f=3.0)
        stood = S.walk(
            lay,
            S.TankState.uniform(12, 135.0),
            T0,
            T0 + timedelta(hours=12),
            air_f=_air,
        ).state
        before = S.observe(lay, stood)[1]
        assert stood.layers_f[0] < before - 5.0
        stirred = S.stir(lay, stood)
        assert S.observe(lay, stirred)[1] < before - 1.0
        start = T0 + timedelta(hours=12)
        w = S.walk(
            lay,
            stood,
            start,
            start + timedelta(hours=3),
            air_f=_air,
            heating=S.Heating(
                compressor=S.Compressor(
                    params=P.compressor, on_at=start, heats_at=start
                )
            ),
        )
        # The first step's end reads the dip; the probe is back above
        # its reading from before the start minutes later, not at once.
        assert w.path[1][0] <= start + timedelta(minutes=1)
        assert S.observe(lay, w.path[1][1])[1] < before
        back = next(
            (t - start) / timedelta(minutes=1)
            for t, s in w.path
            if t > start and S.observe(lay, s)[1] > before
        )
        assert 3.0 <= back <= 40.0
        assert _energy(w.state) - _energy(stood) == pytest.approx(
            w.books.net_btu, abs=1e-6
        )

    def test_a_mixed_tank_is_left_as_it_is(self) -> None:
        state = S.TankState.uniform(12, 130.0)
        assert S.stir(L, state) == state

    def test_it_happens_once_where_the_heating_begins(self) -> None:
        start = S.estimate(L, 130.0, 110.0)
        on = T0 + timedelta(minutes=30)
        heats = on + timedelta(minutes=10)

        def walk(a: datetime, b: datetime, state: S.TankState) -> S.Walked:
            return S.walk(
                L,
                state,
                a,
                b,
                air_f=_air,
                heating=S.Heating(
                    compressor=S.Compressor(
                        params=P.compressor, on_at=on, heats_at=heats
                    )
                ),
            )

        whole = walk(T0, T0 + timedelta(hours=2), start)
        # Through the hold the tank coasts as it was; the stir lands as
        # the heating begins.
        at = dict(whole.path)
        pooled = next(s for t, s in whole.path if t > heats)
        assert max(at[heats].layers_f[:5]) - min(at[heats].layers_f[:5]) > 2.0
        assert max(pooled.layers_f[:5]) - min(pooled.layers_f[:5]) < 0.5
        # Split at the heating's start, the walk is the walk whole: the
        # stir is the later part's first step's, once.
        first = walk(T0, heats, start)
        rest = walk(heats, T0 + timedelta(hours=2), first.state)
        assert rest.state.layers_f == pytest.approx(
            whole.state.layers_f, abs=1e-9
        )
        # Uncredited, the compressor stirs nothing either.
        held = S.walk(
            L,
            start,
            T0,
            T0 + timedelta(hours=2),
            air_f=_air,
            heating=S.Heating(
                compressor=S.Compressor(
                    params=P.compressor, on_at=on, heats_at=heats
                ),
                credited=False,
            ),
        )
        coast = S.walk(L, start, T0, T0 + timedelta(hours=2), air_f=_air)
        assert held.state.layers_f == pytest.approx(
            coast.state.layers_f, abs=0.2
        )

    def test_a_run_under_way_is_not_stirred_again(self) -> None:
        # Its heating began before the walk: the walk is that of a run
        # begun earlier, whose start it never steps over.
        start = S.estimate(L, 130.0, 110.0)
        earlier = T0 - timedelta(hours=1)

        def first(c: S.Compressor) -> tuple[float, ...]:
            w = S.walk(
                L,
                start,
                T0,
                T0 + timedelta(hours=1),
                air_f=_air,
                heating=S.Heating(compressor=c),
            )
            return w.path[1][1].layers_f

        going = first(
            S.Compressor(
                params=P.compressor, on_at=T0, heats_at=T0, stirs=False
            )
        )
        begun = first(
            S.Compressor(params=P.compressor, on_at=earlier, heats_at=earlier)
        )
        fresh = first(S.Compressor(params=P.compressor, on_at=T0, heats_at=T0))
        assert going == pytest.approx(begun, abs=1e-9)
        assert max(abs(x - y) for x, y in zip(going, fresh, strict=True)) > 1.0

    def test_a_run_stopped_before_its_heating_stirs_nothing(self) -> None:
        # A hold a caller imposes that outlasts the run: no heating
        # begins, so nothing is pooled.
        start = S.estimate(L, 130.0, 110.0)
        on = T0 + timedelta(minutes=30)
        heats = on + timedelta(minutes=10)

        def walk(off: datetime, *, stirs: bool) -> S.Walked:
            return S.walk(
                L,
                start,
                T0,
                T0 + timedelta(hours=2),
                air_f=_air,
                heating=S.Heating(
                    compressor=S.Compressor(
                        params=P.compressor,
                        on_at=on,
                        heats_at=heats,
                        off_at=off,
                        stirs=stirs,
                    )
                ),
            )

        for off in (heats, heats - timedelta(minutes=5)):
            got = walk(off, stirs=True)
            assert got.books.compressor_btu == 0.0
            assert got.state.layers_f == pytest.approx(
                walk(off, stirs=False).state.layers_f, abs=1e-9
            )


class TestFlow:
    @given(profiles, st.floats(0.0, 250.0), inflows)
    def test_what_leaves_is_the_top_of_the_column(
        self, state: S.TankState, gal: float, inflow: float
    ) -> None:
        """The remap keeps the heat: what the tank loses is the water
        that left the top, read off the column before (the plug's, then
        what the inlet zone passed up; or, for water warmer than the
        inlet zone, the column above where it settles, then itself),
        less what came in."""
        out = S.flow(L, state, gal, inflow)
        col = S._Column(L, state.layers_f, inflow)
        top, plug = L.volume_gal, col.plug_gal
        if inflow > col.mix_start_f:
            g = min(gal, top - S._settles_at(col))
            left = col.integral(top) - col.integral(top - g)
            left += (gal - g) * inflow
        elif gal <= plug:
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

    @given(stable, st.floats(0.0, 250.0))
    def test_water_warmer_than_the_inlet_zone_rises_past_it(
        self, state: S.TankState, gal: float
    ) -> None:
        """It settles where the column is as warm: the water below that
        stays as it was, and none of the tank is pushed out from under
        it."""
        col = S._Column(L, state.layers_f, 0.0)
        warm = max(state.layers_f)
        inflow = col.mix_start_f + 0.5 * (warm - col.mix_start_f) + 0.1
        foot = S._settles_at(S._Column(L, state.layers_f, inflow))
        out = S.flow(L, state, gal, inflow).state
        assert _monotone(out)
        assert max(out.layers_f) <= max(warm, inflow) + 1e-9
        for i in range(int(foot // L.layer_gal)):
            assert out.layers_f[i] == pytest.approx(state.layers_f[i], abs=1e-9)

    def test_a_draw_keeps_to_the_plug_its_outlet_is_solved_on(self) -> None:
        """Mains warmer than a cold bottom: the tank the draw leaves is
        the plug's, as the water it delivered was read off."""
        state = S.mix(S.TankState((60.0, 70.0, *([125.0] * 10))))
        out = S.draw(L, state, 4.0, 90.0)
        plug = S.flow(L, state, out.withdrawn_gal, 90.0, rises=False)
        risen = S.flow(L, state, out.withdrawn_gal, 90.0)
        assert out.state.layers_f == pytest.approx(plug.state.layers_f)
        assert risen.state.layers_f != pytest.approx(plug.state.layers_f)

    def test_a_warm_return_leaves_a_cold_bottom_cold(self) -> None:
        """A run's own water after the pipe's: the cold the pipe's water
        brought stays at the bottom, and the warm water goes in above
        it, where a plug would have lifted the cold through the
        column."""
        state = S.TankState.uniform(12, 128.0)
        cold = S.flow(L, state, 6.0, 68.0).state
        warm = S.flow(L, cold, 20.0, 125.0).state
        assert warm.layers_f[0] == pytest.approx(cold.layers_f[0], abs=1e-9)
        assert S.observe(L, warm)[0] > 127.0

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
        plug = S.flow(L, state, out.withdrawn_gal, inflow, rises=False)
        assert out.state == plug.state

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
        as the front. Within 2.5 % of the step from the mains to the
        hottest water at the probes (a draw is affine in temperature,
        so its error scales with the step: up to 1.96 % on a scan of
        these), 1 % of the heat drawn, on the profiles ``estimate``
        builds, with the mains under the tank."""
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
        step = max(state.layers_f) - inflow
        for x, y in zip(
            S.observe(L, whole.state), S.observe(L, split.state), strict=True
        ):
            assert x == pytest.approx(y, abs=0.025 * step)

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

    def test_its_power_is_read_at_the_condenser_water(self) -> None:
        # Each step's water is the condenser's as the map reads it, after
        # the start's stir, weighted by the hours the compressor ran.
        start = S.estimate(L, 125.0, 100.0)
        on = T0 + timedelta(minutes=30)
        w = S.walk(
            L,
            start,
            T0,
            T0 + timedelta(hours=2),
            air_f=_air,
            heating=S.Heating(
                compressor=S.Compressor(
                    params=P.compressor, on_at=on, heats_at=on
                )
            ),
        )
        assert w.books.compressor_h == pytest.approx(1.5)
        k = next(i for i, (t, _) in enumerate(w.path) if t == on)
        first = w.steps[k]
        hours = (w.path[k + 1][0] - on).total_seconds() / 3600.0
        assert first.compressor_h == pytest.approx(hours)
        stirred = S.condenser_water_f(L, S.stir(L, w.path[k][1]))
        assert first.compressor_water_f_h == pytest.approx(stirred * hours)
        assert w.steps[0].compressor_h == 0.0

    def test_a_cold_bottom_reads_the_map_at_the_envelopes_edge(
        self,
    ) -> None:
        # The controller judges the water at the lower probe; a cold
        # bottom can leave the condenser's colder than the envelope it
        # allows the heat pump (50 °F) while the compressor runs. A map
        # checked over the envelope, whose power is negative at 35 °F
        # water, still draws its power at 50 °F there.
        c = replace(
            P.compressor,
            heat_btu_h=2000.0,
            heat_btu_h_per_air_f=0.0,
            heat_btu_h_per_water_f=0.0,
            power_w=420.0,
            power_w_per_air_f=0.0,
            power_w_per_water_f=5.0,
        )
        assert S.power_w(c, 65.0, 35.0) < 0.0
        assert L.map_water_f == P.controller.hp_water_range_f
        cold = S.TankState(tuple([35.0] * 6 + [125.0] * (L.layers - 6)))
        assert S.condenser_water_f(L, cold) < 40.0
        w = S.walk(
            L,
            cold,
            T0,
            T0 + timedelta(minutes=10),
            air_f=_air,
            heating=S.Heating(
                compressor=S.Compressor(
                    params=c, on_at=T0, heats_at=T0, stirs=False
                )
            ),
        )
        assert w.books.compressor_wh == pytest.approx(
            S.power_w(c, 65.0, 50.0) * w.books.compressor_h
        )
        assert w.books.compressor_water_f_h == pytest.approx(
            50.0 * w.books.compressor_h
        )
        free = S.walk(
            dataclasses.replace(L, map_water_f=None),
            cold,
            T0,
            T0 + timedelta(minutes=10),
            air_f=_air,
            heating=S.Heating(
                compressor=S.Compressor(
                    params=c, on_at=T0, heats_at=T0, stirs=False
                )
            ),
        )
        assert free.books.compressor_wh < 0.0

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


class TestTheWalksWater:
    def test_water_back_from_the_top_takes_no_heat(self) -> None:
        """A run's own water leaves the top and comes straight back:
        it stirs the tank and takes nothing from it."""
        state = S.mix(S.estimate(L, 135.0, 110.0))
        end = T0 + timedelta(minutes=20)
        w = S.walk(
            L,
            state,
            T0,
            end,
            air_f=_air,
            flowing=[S.Flowing(start=T0, end=end, gpm=2.0, inflow_f=None)],
        )
        assert w.books.flowing_btu == pytest.approx(0.0, abs=1e-6)
        assert S.observe(L, w.state)[1] > S.observe(L, state)[1]
        assert S.energy_btu(L, w.state) == pytest.approx(
            S.energy_btu(L, state) - w.books.loss_btu, abs=1e-6
        )

    def test_its_drops_are_the_tank_either_side_of_a_draw(self) -> None:
        state = S.TankState.uniform(12, 140.0)
        at = T0 + timedelta(minutes=13)
        w = S.walk(
            L,
            state,
            T0,
            T0 + timedelta(hours=1),
            air_f=_air,
            draws=[S.Delivered(at=at, gal=20.0, inflow_f=55.0)],
        )
        ((t, before, after),) = w.drops
        assert t == at
        assert (at, before) in w.path
        assert S.energy_btu(L, after) < S.energy_btu(L, before)
        assert S.observe(L, after)[1] < S.observe(L, before)[1]


_flow_runs = st.lists(
    st.tuples(st.integers(-120, 600), st.integers(1, 300)), max_size=12
)


class TestFlowsOver:
    @given(_flow_runs, st.integers(-180, 720), st.integers(0, 60))
    def test_it_finds_what_a_pass_over_every_flow_finds(
        self, runs: list[tuple[int, int]], a_min: int, span_min: int
    ) -> None:
        """The flows that may run in a span, found by bisection: every
        one a pass over all of them gives water in it, in their order."""
        flowing = tuple(
            S.Flowing(
                start=T0 + timedelta(minutes=s),
                end=T0 + timedelta(minutes=s + n),
                gpm=1.0,
                inflow_f=60.0,
            )
            for s, n in runs
        )
        w = S._Walk(  # pyright: ignore[reportPrivateUsage]
            L, lambda _: 60.0, S.Heating(), flowing, (), S.NO_VALVE
        )
        a = T0 + timedelta(minutes=a_min)
        b = a + timedelta(minutes=span_min)
        found = w.flows_over(a, b)
        assert [f for f in flowing if f in found] == found
        wet = [
            f
            for f in flowing
            if S._overlap_h(a, b, f.start, f.end) > 0.0  # pyright: ignore[reportPrivateUsage]
        ]
        assert all(f in found for f in wet)
        running = [f for f in flowing if f.start <= a < f.end]
        assert [f for f in w.flows_over(a, a) if f.start <= a] == running
