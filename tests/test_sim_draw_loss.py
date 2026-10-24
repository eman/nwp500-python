"""The delivered-to-withdrawn conversion and how the probes move through
a delivered draw."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nwp500.sim.params import TankParams
from nwp500.sim.physics.draw import (
    DEFAULT_INLET_TEMP_F,
    DEFAULT_OBSERVABILITY,
    DEFAULT_REACH_GAL,
    DEFAULT_REACH_GATE_F,
    DEFAULT_REACH_OFFSET_F,
    DEFAULT_TMV_DELIVERY_INTERCEPT_F,
    DEFAULT_TMV_DELIVERY_SLOPE,
    DEFAULT_UPPER_F_PER_GAL,
    delivery_temp_f,
    draw_energy_btu,
    hot_fraction,
    probes_after_draw,
    withdrawn_gal,
)
from nwp500.sim.units import WATER_BTU_PER_GAL_F

DELIVERY = 128.0
#: The installation's mixing valve the delivery line was measured at.
SITE = (DEFAULT_TMV_DELIVERY_INTERCEPT_F, DEFAULT_TMV_DELIVERY_SLOPE)
COLD = 60.0
#: A draw calibration through that valve, as ``sim.decay`` takes it.
CALIBRATED: dict[str, float] = {
    "draw_observability": DEFAULT_OBSERVABILITY,
    "tmv_delivery_intercept_f": SITE[0],
    "tmv_delivery_slope": SITE[1],
}


class TestHotFraction:
    def test_a_hotter_tank_gives_up_less_water(self) -> None:
        """The valve blends more cold in, so the same shower costs the
        tank fewer gallons."""
        assert hot_fraction(140.0, DELIVERY, COLD) < hot_fraction(
            132.0, DELIVERY, COLD
        )

    def test_at_the_setpoint_the_valve_stops_blending(self) -> None:
        assert hot_fraction(DELIVERY, DELIVERY, COLD) == 1.0
        assert hot_fraction(DELIVERY - 10, DELIVERY, COLD) == 1.0

    def test_it_matches_the_mixing_identity(self) -> None:
        """V_hot·T_up + V_cold·T_cold = V_del·T_del, checked rather
        than asserted from the rearranged form the module uses."""
        t_upper = 145.0
        frac = hot_fraction(t_upper, DELIVERY, COLD)
        delivered = frac * t_upper + (1 - frac) * COLD
        assert delivered == pytest.approx(DELIVERY)

    def test_a_tank_at_or_below_the_inlet_delivers_nothing(self) -> None:
        assert hot_fraction(COLD, DELIVERY, COLD) == 0.0
        assert hot_fraction(COLD - 5, DELIVERY, COLD) == 0.0


class TestDrawEnergy:
    def test_observability_scales_the_whole_term(self) -> None:
        """It is a multiplier on apparent energy, nothing subtler —
        so a calibration without it (0.0) removes no heat at all."""
        full = draw_energy_btu(9.5, 140.0, DELIVERY, COLD, 1.0)
        half = draw_energy_btu(9.5, 140.0, DELIVERY, COLD, 0.5)
        assert half == pytest.approx(full / 2)
        assert draw_energy_btu(9.5, 140.0, DELIVERY, COLD, 0.0) == 0.0

    def test_the_tank_temperature_cancels_while_the_valve_mixes(self) -> None:
        """The result that makes this term cheap to trust: a hotter
        tank gives up proportionally less water for the same delivered
        shower, and the two effects are exactly inverse.
        """
        hot = draw_energy_btu(9.5, 145.0, DELIVERY, COLD)
        hotter = draw_energy_btu(9.5, 155.0, DELIVERY, COLD)
        assert hot == pytest.approx(hotter)
        assert hot == pytest.approx(9.5 * WATER_BTU_PER_GAL_F * (128.0 - 60.0))

    def test_below_the_setpoint_a_colder_tank_loses_less(self) -> None:
        """Once the valve has nothing to blend with, tank temperature
        re-enters and the draw becomes a smaller loss."""
        warm = draw_energy_btu(9.5, 120.0, DELIVERY, COLD)
        cold = draw_energy_btu(9.5, 100.0, DELIVERY, COLD)
        assert cold < warm
        assert cold == pytest.approx(9.5 * WATER_BTU_PER_GAL_F * (100.0 - 60.0))

    def test_the_two_regimes_meet_at_the_setpoint(self) -> None:
        """No step at the boundary: the mixing branch and the
        pass-through branch agree where they meet."""
        just_above = draw_energy_btu(9.5, DELIVERY + 1e-9, DELIVERY, COLD)
        just_below = draw_energy_btu(9.5, DELIVERY - 1e-9, DELIVERY, COLD)
        assert just_above == pytest.approx(just_below, abs=1e-6)

    def test_a_tank_below_the_inlet_never_gains_heat(self) -> None:
        assert draw_energy_btu(9.5, 55.0, DELIVERY, COLD) == 0.0

    def test_no_volume_is_no_heat(self) -> None:
        assert draw_energy_btu(0.0, 140.0, DELIVERY, COLD) == 0.0

    def test_energy_and_withdrawal_agree(self) -> None:
        """The collapsed form must equal the long one it came from,
        or the module is quietly using two different physics."""
        for t_upper in (100.0, 128.0, 135.0, 150.0):
            v_hot = withdrawn_gal(9.5, t_upper, DELIVERY, COLD)
            long_form = v_hot * WATER_BTU_PER_GAL_F * (t_upper - COLD)
            assert draw_energy_btu(
                9.5, t_upper, DELIVERY, COLD
            ) == pytest.approx(long_form)


class TestCalibration:
    """The fitted constants, and the one relationship between them.

    Values and intervals come from the 2026-09 draw calibration;
    these pin the ones that ship and the fact that two of them are a
    pair.
    """

    def test_the_fitted_values_are_the_ones_the_report_publishes(self) -> None:
        assert pytest.approx(0.633) == DEFAULT_OBSERVABILITY
        assert pytest.approx(30.0) == DEFAULT_REACH_GATE_F
        assert pytest.approx(1.5) == DEFAULT_REACH_OFFSET_F
        assert pytest.approx(9.0) == DEFAULT_REACH_GAL
        assert pytest.approx(0.05) == DEFAULT_UPPER_F_PER_GAL
        assert pytest.approx(72.4) == DEFAULT_INLET_TEMP_F
        assert pytest.approx(53.56) == DEFAULT_TMV_DELIVERY_INTERCEPT_F
        assert pytest.approx(0.485) == DEFAULT_TMV_DELIVERY_SLOPE

    def test_observability_is_the_first_fit_rescaled_twice(self) -> None:
        """0.454 against 128 °F and 60 °F, times the ×1.113 the
        measured delivery line (2026-09) moves the fit by, times the
        ×1.254 the measured inlet does. A value that is not that
        product is a different fit and needs a report."""
        assert pytest.approx(0.454 * 1.113 * 1.254, abs=0.001) == (
            DEFAULT_OBSERVABILITY
        )

    def test_the_probes_inlet_keeps_the_calibration(self) -> None:
        """Served the probe's measured inlet, the refitted `k` gives
        the per-gallon heat the corpus shows. The `k` fitted against
        60 °F, served the same inlet, would cut a draw's heat by a
        fifth: that is why a calibration's `k` and its inlet move
        together."""
        probe = 72.4
        t_del = delivery_temp_f(139.0, *SITE)
        heat = draw_energy_btu(1.0, 139.0, t_del, probe, DEFAULT_OBSERVABILITY)
        assert heat == pytest.approx(257.0, rel=0.02)
        # And the swap without the refit, for the record.
        assert draw_energy_btu(1.0, 139.0, t_del, probe, 0.505) < 0.82 * heat

    def test_the_line_reproduces_the_gauge_plateaus(self) -> None:
        """The five full draw plateaus from the gauge cam, each
        within the dial's ±1.5 °F."""
        for t_upper, plateau in (
            (123.8, 114.2),
            (125.8, 114.6),
            (130.5, 115.6),
            (139.5, 121.8),
            (138.2, 120.4),
        ):
            assert delivery_temp_f(t_upper, *SITE) == pytest.approx(
                plateau, abs=1.5
            )

    def test_the_pair_reproduces_the_measured_per_gallon_response(self) -> None:
        """The observability is fitted *against a reference inlet*,
        so only their product is identified. Changing either alone
        silently changes the model:
        this pins the product at the 257 apparent BTU per delivered
        gallon the corpus actually shows.
        """
        # At the corpus's typical 139 °F tank the new line and the
        # new k must still give the per-gallon response the data shows:
        # the refit moves the split between k and delivery, not their
        # product.
        measured = draw_energy_btu(
            1.0,
            139.0,
            delivery_temp_f(139.0, *SITE),
            DEFAULT_INLET_TEMP_F,
            DEFAULT_OBSERVABILITY,
        )
        assert measured == pytest.approx(257.0, rel=0.02)


class TestProbesAfterDraw:
    """``probes_after_draw``: the lower probe's response follows the
    gap at the draw."""

    INFLOW = DEFAULT_INLET_TEMP_F

    def after(
        self, upper: float, lower: float, gal: float, inflow: float = INFLOW
    ) -> tuple[float, float]:
        return probes_after_draw(
            upper,
            lower,
            gal,
            inflow,
            intercept_f=DEFAULT_TMV_DELIVERY_INTERCEPT_F,
            slope=DEFAULT_TMV_DELIVERY_SLOPE,
        )

    def test_a_mixed_tank_moves_the_lower_probe_less(self) -> None:
        """The same draw from the same upper zone: the lower probe
        falls further the wider the gap it finds."""
        _, mixed = self.after(135.0, 134.0, 10.0)
        _, stratified = self.after(135.0, 115.0, 10.0)
        assert 134.0 - mixed < 115.0 - stratified
        assert 115.0 - stratified > 2.0 * (134.0 - mixed)

    @pytest.mark.parametrize("gal", [0.6, 3.0, 12.0, 40.0])
    @pytest.mark.parametrize("lower", [133.0, 110.0, 85.0])
    def test_a_draw_split_into_parts_moves_the_zones_as_one(
        self, gal: float, lower: float
    ) -> None:
        whole = self.after(135.0, lower, gal)
        upper, low = 135.0, lower
        for part in (0.3 * gal, 0.07 * gal, 0.63 * gal):
            upper, low = self.after(upper, low, part)
        assert upper == pytest.approx(whole[0], abs=0.05)
        assert low == pytest.approx(whole[1], abs=0.05)

    @pytest.mark.parametrize(
        ("upper", "lower"),
        [(140.0, 139.0), (135.0, 100.0), (110.0, 80.0), (120.0, 125.0)],
    )
    def test_no_zone_warms(self, upper: float, lower: float) -> None:
        for gal in (0.1, 2.0, 15.0, 80.0):
            u, lo = self.after(upper, lower, gal)
            assert u <= upper
            assert lo <= lower

    def test_the_lower_zone_stops_at_the_inflow(self) -> None:
        """However large the draw, and with a reach that takes the
        whole lower zone in one piece."""
        _, lower = self.after(130.0, 75.0, 500.0)
        assert lower >= self.INFLOW
        _, lower = probes_after_draw(
            130.0, 100.0, 20.0, self.INFLOW, gate_f=0.01, reach_gal=0.01
        )
        assert lower == pytest.approx(self.INFLOW)

    def test_the_upper_zone_stops_at_the_lower(self) -> None:
        upper, lower = probes_after_draw(
            100.0, 99.0, 50.0, self.INFLOW, upper_f_per_gal=5.0
        )
        assert upper == pytest.approx(lower)

    def test_the_upper_zone_falls_per_delivered_gallon(self) -> None:
        upper, _ = self.after(140.0, 139.0, 10.0)
        assert upper == pytest.approx(140.0 - 10.0 * DEFAULT_UPPER_F_PER_GAL)

    def test_a_tank_at_the_inflow_does_not_move(self) -> None:
        assert self.after(70.0, 70.0, 10.0, inflow=72.4) == (70.0, 70.0)

    def test_no_draw_moves_nothing(self) -> None:
        assert self.after(135.0, 120.0, 0.0) == (135.0, 120.0)


def _decay() -> Any:
    """``sim.decay``, which needs pandas."""
    pytest.importorskip("pandas")
    from nwp500.sim import decay

    return decay


class TestTheCoastsDraw:
    """``project_decay`` charges a delivered draw as ``draw_step``
    does, and the bulk's fall is the draw's apparent heat."""

    T0 = datetime(2026, 3, 2, 7, 0, tzinfo=UTC)

    def coast(
        self, upper: float, lower: float, draws: list[tuple[datetime, float]]
    ) -> Any:
        import pandas as pd

        end = self.T0 + timedelta(minutes=1)
        air = pd.DataFrame(
            {"ambient_f": [65.0, 65.0]},
            index=pd.DatetimeIndex([self.T0, end + timedelta(hours=1)]),
        )
        return _decay().project_decay(
            upper, lower, air, 0.0, 1e9, end, self.T0, draws=draws, **CALIBRATED
        )

    @pytest.mark.parametrize("lower", [134.0, 112.0])
    def test_it_is_draw_steps(self, lower: float) -> None:
        out = self.coast(135.0, lower, [(self.T0, 12.0)])
        upper, low = _decay().draw_step(135.0, lower, 12.0, **CALIBRATED)
        assert out.t_upper == pytest.approx(upper, abs=1e-6)
        assert out.t_lower == pytest.approx(low, abs=1e-6)

    def test_a_draw_in_parts_moves_the_tank_as_one(self) -> None:
        whole = self.coast(135.0, 118.0, [(self.T0, 10.0)])
        parts = self.coast(135.0, 118.0, [(self.T0, 4.0), (self.T0, 6.0)])
        assert parts.t_upper == pytest.approx(whole.t_upper, abs=0.05)
        assert parts.t_lower == pytest.approx(whole.t_lower, abs=0.05)

    def test_the_heat_is_the_bulks_fall(self) -> None:
        out = self.coast(135.0, 118.0, [(self.T0, 10.0)])
        fall = (135.0 + 118.0) / 2.0 - (out.t_upper + out.t_lower) / 2.0
        assert out.draw_heat_btu == pytest.approx(
            fall * TankParams().thermal_mass_btu_f
        )
        (impulse,) = out.impulses
        assert impulse.lower_after == pytest.approx(out.t_lower)

    def test_without_a_calibration_no_draw_moves_the_tank(self) -> None:
        assert _decay().draw_step(
            135.0, 118.0, 10.0, draw_observability=None
        ) == (135.0, 118.0)
