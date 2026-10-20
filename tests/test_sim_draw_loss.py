"""The delivered-to-withdrawn conversion and the front it opens."""

import pytest

from nwp500.sim.physics.draw import (
    DEFAULT_GAP_OPEN_F_PER_GAL,
    DEFAULT_INLET_TEMP_F,
    DEFAULT_OBSERVABILITY,
    DEFAULT_TMV_DELIVERY_INTERCEPT_F,
    DEFAULT_TMV_DELIVERY_SLOPE,
    delivery_temp_f,
    draw_energy_btu,
    gap_opened_f,
    hot_fraction,
    withdrawn_gal,
)
from nwp500.sim.units import WATER_BTU_PER_GAL_F

DELIVERY = 128.0
#: The installation's mixing valve the delivery line was measured at.
SITE = (DEFAULT_TMV_DELIVERY_INTERCEPT_F, DEFAULT_TMV_DELIVERY_SLOPE)
COLD = 60.0


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
        assert pytest.approx(1.235) == DEFAULT_GAP_OPEN_F_PER_GAL
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
        """Served the probe's measured inlet, the refitted pair gives
        the per-gallon heat and the front the corpus shows. The
        pair fitted against 60 °F, served the same inlet, would cut a
        draw's heat by a fifth: that is why a calibration's `k` and its
        inlet move together."""
        probe = 72.4
        t_del = delivery_temp_f(139.0, *SITE)
        heat = draw_energy_btu(1.0, 139.0, t_del, probe, DEFAULT_OBSERVABILITY)
        assert heat == pytest.approx(257.0, rel=0.02)
        front = DEFAULT_GAP_OPEN_F_PER_GAL * withdrawn_gal(
            1.0, 139.0, t_del, probe
        )
        # 1.167 °F per withdrawn gallon at the 60 °F hot fraction.
        assert front == pytest.approx(
            1.167 * withdrawn_gal(1.0, 139.0, t_del, 60.0), rel=0.01
        )
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


class TestFront:
    #: A bulk drop large enough that the no-warming cap is not what
    #: binds, so each test below exercises the bound it names.
    ROOMY = 50.0

    def test_it_scales_with_the_cold_admitted(self) -> None:
        small = gap_opened_f(2.0, 1.5, self.ROOMY, 135.0, COLD)
        large = gap_opened_f(6.0, 1.5, self.ROOMY, 135.0, COLD)
        assert large > small

    def test_a_zero_coefficient_disables_it(self) -> None:
        """What a calibration fitted before the front existed
        carries."""
        assert gap_opened_f(9.5, 0.0, self.ROOMY, 135.0, COLD) == 0.0

    def test_a_draw_cannot_warm_the_upper_zone(self) -> None:
        """The gap is split evenly about the bulk, so an opening
        wider than twice the bulk drop raises the top of the tank.
        No draw does that. With the fitted coefficient it is not a
        corner case — it happened below about 122 °F.
        """
        drop = 2.0
        opened = gap_opened_f(9.5, 1.043, drop, 135.0, COLD)
        assert opened <= 2.0 * drop + 1e-9
        # The upper zone's move is `opened/2 - drop`, which must not
        # be positive.
        assert opened / 2.0 - drop <= 1e-9

    def test_the_lower_zone_cannot_be_driven_below_the_inlet(self) -> None:
        """Bounds the *gap half* only — the bulk drop is applied
        separately and is not bounded here, which the docstring now
        says rather than claiming more.

        Asserted as an equality where the cap binds, not as an
        inequality. The gap splits evenly about the bulk, so the room
        the lower zone has is *twice* its distance above the inlet;
        a one-sided bound is satisfied by any smaller factor too, and
        a cap at half the real headroom would refuse openings that
        are physically fine.
        """
        opened = gap_opened_f(50.0, 5.0, self.ROOMY, 65.0, COLD)
        assert opened == pytest.approx(2.0 * (65.0 - COLD))
        assert 65.0 - opened / 2.0 == pytest.approx(COLD)

    def test_no_withdrawal_opens_nothing(self) -> None:
        assert gap_opened_f(0.0, 1.5, self.ROOMY, 135.0, COLD) == 0.0
