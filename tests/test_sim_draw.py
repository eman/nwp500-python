"""The mixing valve: what it delivers, and the share of a delivered
gallon the tank gives up."""

import pytest

from nwp500.sim.physics.draw import (
    DEFAULT_TMV_DELIVERY_INTERCEPT_F,
    DEFAULT_TMV_DELIVERY_SLOPE,
    delivery_temp_f,
    hot_fraction,
    withdrawn_gal,
)
from nwp500.sim.physics.water import heat_f

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
        """V_hot·h(T_up) + V_cold·h(T_cold) = V_del·h(T_del), the heat
        each gallon holds (``physics.water``), checked rather than
        asserted from the rearranged form the module uses: a hot gallon
        holds less, so it takes a little more of the tank than the
        temperatures alone say."""
        t_upper = 145.0
        frac = hot_fraction(t_upper, DELIVERY, COLD)
        delivered = frac * heat_f(t_upper) + (1 - frac) * heat_f(COLD)
        assert delivered == pytest.approx(heat_f(DELIVERY))
        assert frac > (DELIVERY - COLD) / (t_upper - COLD)

    def test_a_tank_at_or_below_the_inlet_delivers_nothing(self) -> None:
        assert hot_fraction(COLD, DELIVERY, COLD) == 0.0
        assert hot_fraction(COLD - 5, DELIVERY, COLD) == 0.0

    def test_the_withdrawn_gallons_are_the_hot_share(self) -> None:
        assert withdrawn_gal(10.0, 140.0, DELIVERY, COLD) == pytest.approx(
            10.0 * hot_fraction(140.0, DELIVERY, COLD)
        )
        assert withdrawn_gal(0.0, 140.0, DELIVERY, COLD) == 0.0


class TestTheValve:
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

    def test_no_valve_delivers_the_tank(self) -> None:
        assert delivery_temp_f(131.0) == 131.0
