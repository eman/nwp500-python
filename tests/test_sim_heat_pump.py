"""The heat pump as a performance map (``sim.physics.heat_pump``) and
the run-on past the target."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from nwp500 import sim
from nwp500.sim import heat_pump_fit as hpf
from nwp500.sim.params import CompressorParams, ControllerParams
from nwp500.sim.physics import heat_pump as hp
from nwp500.sim.units import BTU_PER_WH

C = CompressorParams()
GRID = [(a, w) for a in (48.0, 60.0, 75.0, 89.0) for w in (70.0, 110.0, 150.0)]


class TestTheMap:
    @pytest.mark.parametrize(("air", "water"), GRID)
    def test_the_condenser_gives_what_the_air_and_the_meter_put_in(
        self, air: float, water: float
    ) -> None:
        assert hp.evaporator_btu_h(C, air, water) + hp.power_w(
            C, air, water
        ) * BTU_PER_WH == pytest.approx(hp.heat_btu_h(C, air, water))

    def test_it_is_read_along_its_plane_past_its_domain(self) -> None:
        # 41 °F air is 20 under the heat's fitted span, and 80 °F water
        # 34 under it.
        assert hp.heat_btu_h(C, 41.0, 120.0) == pytest.approx(
            C.heat_btu_h - 24.0 * C.heat_btu_h_per_air_f
        )
        assert hp.heat_btu_h(C, 65.0, 80.0) == pytest.approx(
            C.heat_btu_h - 40.0 * C.heat_btu_h_per_water_f
        )
        assert hp.power_w(C, 65.0, 149.0) == pytest.approx(
            C.power_w + 29.0 * C.power_w_per_water_f
        )

    def test_it_is_quoted_at_its_reference(self) -> None:
        assert hp.heat_btu_h(C, 65.0, 120.0) == C.heat_btu_h
        assert hp.power_w(C, 65.0, 120.0) == C.power_w
        assert hp.cop(C, 65.0, 120.0) == pytest.approx(
            C.heat_btu_h / (C.power_w * BTU_PER_WH)
        )

    def test_warmer_air_heats_faster_and_warmer_water_slower(self) -> None:
        assert hp.heat_btu_h(C, 80.0, 120.0) > hp.heat_btu_h(C, 50.0, 120.0)
        assert hp.heat_btu_h(C, 65.0, 140.0) < hp.heat_btu_h(C, 65.0, 100.0)
        assert hp.cop(C, 65.0, 140.0) < hp.cop(C, 65.0, 100.0)

    def test_the_defaults_claim_nothing_no_heat_pump_does(self) -> None:
        assert hpf.violations(C) == ()
        assert hpf.violations(sim.site_example_params().compressor) == ()

    def test_a_claim_past_the_domains_is_found(self) -> None:
        # Within the heat's span (61-89 °F air) the plane takes heat
        # from the air; carried to the envelope's 41 °F it gives some.
        c = replace(C, heat_btu_h_per_air_f=150.0)
        assert hp.evaporator_btu_h(c, 61.0, 149.0) > 0.0
        assert hp.evaporator_btu_h(c, 41.0, 149.0) < 0.0
        assert "evaporator_heat_negative" in hpf.violations(c)
        assert "evaporator_heat_negative" not in hpf.violations(
            c, (61.0, 113.0)
        )

    def test_carnot_bounds_the_lift(self) -> None:
        assert hp.carnot_cop(65.0, 120.0) == pytest.approx(579.67 / 55.0)
        assert hp.carnot_cop(80.0, 75.0) == float("inf")

    def test_the_bound_is_the_refrigerants(self) -> None:
        # The coil runs EVAPORATOR_APPROACH_F under the air, so the lift
        # the cycle makes is that much more than the air's to the water.
        assert hp.refrigerant_carnot_cop(65.0, 120.0) == pytest.approx(
            579.67 / (55.0 + hp.EVAPORATOR_APPROACH_F)
        )
        assert hp.refrigerant_carnot_cop(65.0, 120.0) < hp.carnot_cop(
            65.0, 120.0
        )

    def test_a_cop_over_the_refrigerants_bound_is_found(self) -> None:
        # The heat flat at 15 % over the map's: at the envelope's coldest
        # air and hottest water, under 0.6 of the ideal heat pump between
        # the air and the water, but over it between the coil and the
        # water.
        c = replace(
            C,
            heat_btu_h=1.15 * C.heat_btu_h,
            heat_btu_h_per_air_f=0.0,
            heat_btu_h_per_water_f=0.0,
        )
        air, water = 41.0, 149.0
        assert hp.cop(c, air, water) < 0.6 * hp.carnot_cop(air, water)
        assert hp.cop(c, air, water) > 0.6 * hp.refrigerant_carnot_cop(
            air, water
        )
        assert "cop_over_carnot" in hpf.violations(c)


class TestTheHold:
    @pytest.mark.parametrize(
        ("off", "hold"),
        [
            (0.0, 0.0),
            (14.99, 0.0),
            (15.0, 5.0),
            (59.0, 5.0),
            (60.0, 10.0),
            (180.0, 18.0),
            (720.0, 22.0),
            (5000.0, 22.0),
            (None, 22.0),
        ],
    )
    def test_by_the_minutes_off(self, off: float | None, hold: float) -> None:
        held = replace(C, start_hold_min=(0.0, 5.0, 10.0, 18.0, 22.0))
        assert hp.start_hold_min(held, off) == hold

    def test_none_is_imposed_by_default(self) -> None:
        # The hold is the layers' own (``stratified.stir``).
        assert all(v == 0.0 for v in C.start_hold_min)
        assert hp.start_hold_min(C, None) == 0.0
        assert hp.start_hold_min(sim.default_params().compressor, 800.0) == 0.0

    def test_its_bands_are_checked(self) -> None:
        with pytest.raises(ValueError, match="one more value"):
            CompressorParams(start_hold_min=(1.0, 2.0))
        for edges in ((60.0, 15.0, 180.0, 720.0), (15.0, 15.0, 180.0, 720.0)):
            with pytest.raises(ValueError, match="ascending"):
                CompressorParams(start_hold_after_min=edges)
        with pytest.raises(ValueError, match="negative"):
            CompressorParams(start_hold_min=(0.0, -1.0, 10.0, 18.0, 22.0))
        with pytest.raises(ValueError, match="low, high"):
            CompressorParams(heat_domain_air_f=(89.0, 48.0))
        with pytest.raises(ValueError, match="negative"):
            ControllerParams(hp_stop_overshoot_f=-0.1)

    def test_neither_map_bends_at_its_domains_edge(self) -> None:
        # The heat was fitted on a mixed tank from 114 °F, the power on
        # the condenser's water from 73 °F: each moves as much per °F
        # either side of its edge.
        heat = [hp.heat_btu_h(C, 65.0, w) for w in (110.0, 114.0, 118.0)]
        power = [hp.power_w(C, 65.0, w) for w in (69.0, 73.0, 77.0)]
        for read in (heat, power):
            steps = [b - a for a, b in pairwise(read)]
            assert steps[0] == pytest.approx(steps[1])
            assert steps[0] != 0.0


T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _recovery(params: sim.HeaterParams) -> sim.SimulationResult:
    return sim.simulate(
        sim.Scenario(
            start=T0,
            horizon=timedelta(hours=8),
            tz="UTC",
            state=sim.HeaterState(
                upper_f=130.0, lower_f=118.0, compressor_running=True
            ),
            settings=sim.Settings(setpoint_f=140.0, hp_lower_off_f=140.0),
            history=sim.History(compressor_stopped_at=T0 - timedelta(hours=3)),
            environment=sim.Environment(ambient_f=65.0),
        ),
        params,
    )


class TestTheRunOn:
    def test_it_stops_its_overshoot_past_the_target(self) -> None:
        params = sim.site_example_params()
        r = _recovery(params)
        run = r.heating[0]
        assert run.stop == "target"
        stop = sim.tank_physics.point_at(r.points, run.end)  # type: ignore[attr-defined]
        # Within the integrator's 10-second step of it.
        assert stop.lower_f == pytest.approx(
            140.0 + params.controller.hp_stop_overshoot_f, abs=0.03
        )

    def test_a_larger_overshoot_runs_longer_and_uses_more(self) -> None:
        params = sim.site_example_params()
        more = replace(
            params,
            controller=replace(params.controller, hp_stop_overshoot_f=2.0),
        )
        short, long = _recovery(params).heating[0], _recovery(more).heating[0]
        assert long.end > short.end
        assert long.input_wh is not None and short.input_wh is not None
        assert long.input_wh > short.input_wh
