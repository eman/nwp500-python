"""How much hot water the tank can deliver, and the delivered
temperature, from its layers (``nwp500.sim.delivery``)."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from nwp500.sim import HeaterParams, default_params, site_example_params
from nwp500.sim import delivery as rd
from nwp500.sim.engine import PathPoint
from nwp500.sim.physics import stratified as st

#: No mixing valve: the tap gets the tank's water.
P = default_params()
#: One installation's mixing valve.
SITE = site_example_params()
LAY = st.layout(P)
LINE = P.readiness.line_f


def _uniform(temp_f: float) -> tuple[float, ...]:
    return (temp_f,) * LAY.layers


def _drawn(
    gal: float, top_f: float = 140.0, inlet_f: float = 60.0
) -> tuple[float, ...]:
    """A uniform ``top_f`` tank after a draw of ``gal`` at the tap."""
    out = st.draw(LAY, st.TankState(_uniform(top_f)), gal, inlet_f)
    return out.state.layers_f


class TestDeliverable:
    def test_from_the_probes_it_says_so(self) -> None:
        got = rd.deliverable(P, 140.0, 138.0)
        assert got.basis == "probes"
        want = st.deliverable_gal(
            LAY,
            st.mix(st.estimate(LAY, 140.0, 138.0)),
            LINE,
            P.draw.inlet_temp_f,
        )
        assert got.gal == round(want, 1)

    def test_from_the_layers_it_says_so(self) -> None:
        layers = _uniform(140.0)
        got = rd.deliverable(P, 140.0, 140.0, layers, inlet_f=60.0)
        assert got.basis == "layers"
        want = st.deliverable_gal(LAY, st.TankState(layers), LINE, 60.0)
        assert got.gal == round(want, 1)

    def test_a_uniform_tank_delivers_all_of_it(self) -> None:
        """With no valve the tap takes the tank's water: a whole tank
        at 140 °F gives about its volume before the inlet's arrives."""
        got = rd.deliverable(P, 140.0, 140.0, _uniform(140.0), inlet_f=60.0)
        assert 0.8 * P.tank.volume_gal < got.gal <= P.tank.volume_gal

    def test_the_layers_know_a_draw_the_probes_cannot(self) -> None:
        """After a draw the bottom is the inlet's. The probes read close
        to a tank that coasted, so the profile they stand for promises
        more than the layers hold."""
        layers = _drawn(20.0)
        upper, lower = st.observe(LAY, st.TankState(layers))
        by_layers = rd.deliverable(P, upper, lower, layers, inlet_f=60.0)
        by_probes = rd.deliverable(P, upper, lower, inlet_f=60.0)
        assert by_layers.gal < by_probes.gal

    def test_the_draw_comes_off_the_promise(self) -> None:
        full = rd.deliverable(P, 140.0, 140.0, _uniform(140.0), inlet_f=60.0)
        after = rd.deliverable(P, 140.0, 140.0, _drawn(20.0), inlet_f=60.0)
        assert full.gal - after.gal == pytest.approx(20.0, abs=0.5)

    def test_below_the_line_nothing_is_deliverable(self) -> None:
        cold = _uniform(LINE - 0.5)
        assert rd.deliverable(P, LINE - 0.5, LINE - 0.5, cold).gal == 0.0
        assert rd.deliverable(P, LINE - 5.0, LINE - 10.0).gal == 0.0

    def test_the_water_above_the_probe_is_deliverable(self) -> None:
        """The outlet is above the upper probe: a probe just under the
        line leaves the warmer water above it, no more than the tank
        holds above the probe."""
        got = rd.deliverable(P, LINE - 0.5, LINE - 5.0).gal
        above = (1.0 - P.tank.upper_probe_height) * P.tank.volume_gal
        assert 0.0 < got < 1.5 * above

    def test_the_valve_stretches_the_tank(self) -> None:
        """Through the valve each tank gallon is blended with the
        inlet's: more delivered gallons than the tank holds."""
        layers = _uniform(140.0)
        valved = rd.deliverable(SITE, 140.0, 140.0, layers, inlet_f=60.0)
        bare = rd.deliverable(P, 140.0, 140.0, layers, inlet_f=60.0)
        assert valved.gal > bare.gal

    def test_a_warmer_inlet_stretches_it_further(self) -> None:
        layers = _uniform(140.0)
        cold = rd.deliverable(SITE, 140.0, 140.0, layers, inlet_f=50.0)
        warm = rd.deliverable(SITE, 140.0, 140.0, layers, inlet_f=70.0)
        assert warm.gal > cold.gal

    def test_without_an_inlet_it_is_the_draw_terms(self) -> None:
        layers = _drawn(10.0)
        assert rd.deliverable(SITE, 140.0, 120.0, layers) == rd.deliverable(
            SITE, 140.0, 120.0, layers, inlet_f=SITE.draw.inlet_temp_f
        )

    def test_an_inlet_at_the_line_never_runs_out(self) -> None:
        got = rd.deliverable(P, 140.0, 140.0, inlet_f=LINE + 1.0)
        assert math.isinf(got.gal)

    @pytest.mark.parametrize("p", [P, SITE], ids=["bare", "valve"])
    def test_a_warmer_layer_never_delivers_less(self, p: HeaterParams) -> None:
        layers = _drawn(25.0)
        base = rd.deliverable(p, 140.0, 120.0, layers, inlet_f=60.0).gal
        for k in range(len(layers)):
            warmer = list(layers)
            warmer[k] += 3.0
            got = rd.deliverable(p, 140.0, 120.0, warmer, inlet_f=60.0).gal
            assert got >= base, k

    @pytest.mark.parametrize("upper", [110.0, 125.0, 140.0])
    def test_a_warmer_lower_probe_never_delivers_less(
        self, upper: float
    ) -> None:
        temps = [100.0 + 2.0 * i for i in range(26)]
        got = [rd.deliverable(P, upper, lo).gal for lo in temps]
        assert got == sorted(got)

    def test_the_layers_must_be_the_parameters(self) -> None:
        with pytest.raises(ValueError, match="layers given"):
            rd.deliverable(P, 140.0, 140.0, (140.0,) * (LAY.layers - 1))


class TestWithinResolution:
    def test_at_the_answer_it_is_within(self) -> None:
        for layers in (None, _drawn(15.0)):
            upper, lower = (
                (140.0, 120.0)
                if layers is None
                else st.observe(LAY, st.TankState(layers))
            )
            gal = rd.deliverable(P, upper, lower, layers, inlet_f=60.0).gal
            assert rd.within_resolution(
                P, upper, lower, layers, gal, inlet_f=60.0
            )

    def test_far_from_it_it_is_not(self) -> None:
        layers = _drawn(15.0)
        upper, lower = st.observe(LAY, st.TankState(layers))
        gal = rd.deliverable(P, upper, lower, layers, inlet_f=60.0).gal
        for asked in (gal - 15.0, gal + 15.0):
            assert not rd.within_resolution(
                P, upper, lower, layers, asked, inlet_f=60.0
            )


class TestTheDelivery:
    def test_without_a_valve_it_is_the_top(self) -> None:
        layers = _drawn(10.0)
        assert rd.delivery_f(P, 120.0, layers) == layers[-1]

    def test_without_layers_it_is_the_upper_probe(self) -> None:
        assert rd.delivery_f(P, 120.0) == 120.0

    def test_through_the_valve_it_is_tempered_and_never_warmer(self) -> None:
        d = SITE.draw
        hot = rd.delivery_f(SITE, 140.0)
        assert hot == pytest.approx(
            d.delivery_intercept_f + d.delivery_slope * 140.0
        )
        assert hot < 140.0
        # Under the valve's own setting the tank's water passes as it is.
        assert rd.delivery_f(SITE, 100.0) == 100.0

    @pytest.mark.parametrize("p", [P, SITE], ids=["bare", "valve"])
    def test_it_agrees_with_the_gallons_on_running_out(
        self, p: HeaterParams
    ) -> None:
        """Drawn down a gallon at a time, the delivery falls under the
        line exactly when nothing more is deliverable."""
        lay = st.layout(p)
        d = p.draw
        valve = (d.delivery_intercept_f, d.delivery_slope)
        state = st.TankState(_uniform(140.0))
        for _ in range(150):
            layers = state.layers_f
            gal = st.deliverable_gal(lay, state, LINE, 60.0, valve)
            below = rd.delivery_f(p, layers[-1], layers) < LINE
            assert below == (gal == 0.0)
            state = st.draw(lay, state, 1.0, 60.0, valve).state

    def test_along_a_path_it_reads_each_points_layers(self) -> None:
        t0 = datetime(2026, 10, 4, 19, tzinfo=UTC)
        layers = _drawn(10.0)
        points = [
            PathPoint(t0, 130.0, 120.0, 140.0, False, 0.0, layers_f=layers),
            PathPoint(
                t0 + timedelta(minutes=1), 125.0, 120.0, 140.0, False, 0.0
            ),
        ]
        assert rd.delivery_along(points, P) == [layers[-1], 125.0]


class TestTheReviewOfDepletion:
    def test_a_draw_at_the_windows_onset_counts_its_cold_side(self) -> None:
        """110 °F before the onset, 100 °F just after a draw there, 110
        °F at the window's end: the dip is the window's."""
        t0 = datetime(2026, 10, 4, 19, tzinfo=UTC)
        points = [
            PathPoint(t0, 110.0, 100.0, 140.0, False, 0.0),
            PathPoint(t0, 100.0, 95.0, 140.0, False, 0.0),
            PathPoint(
                t0 + timedelta(minutes=5), 110.0, 100.0, 140.0, False, 0.0
            ),
        ]
        judged = rd.depletion(
            points,
            t0,
            t0 + timedelta(minutes=5),
            [p.upper_f for p in points],
            P.readiness,
        )
        assert judged.min_f == 100.0
        assert judged.depleted

    def test_any_fall_below_the_line_runs_cold(self) -> None:
        """A degree below the line for a minute is cold: no draw on the
        record dips and recovers, so nothing is excused."""
        t0 = datetime(2026, 10, 4, 19, tzinfo=UTC)
        points = [
            PathPoint(t0, LINE + 5.0, 100.0, 140.0, False, 0.0),
            PathPoint(
                t0 + timedelta(minutes=1), LINE - 1.0, 100.0, 140.0, False, 0.0
            ),
            PathPoint(
                t0 + timedelta(minutes=2), LINE + 5.0, 100.0, 140.0, False, 0.0
            ),
        ]
        judged = rd.depletion(
            points,
            t0,
            t0 + timedelta(minutes=2),
            [p.upper_f for p in points],
            P.readiness,
        )
        assert judged.depleted
        assert judged.min_f == LINE - 1.0
