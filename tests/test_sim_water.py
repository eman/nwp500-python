"""Water's heat per gallon by temperature (``nwp500.sim.physics.water``)."""

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nwp500.sim.physics.water import btu_per_gal_f, heat_f, temp_f
from nwp500.sim.units import WATER_BTU_PER_GAL_F

temps = st.floats(-40.0, 260.0)


def test_a_gallon_holds_less_heat_hot() -> None:
    """8.34 BTU per °F at the mains, 8.20 at 140 °F: 1.6 % lighter."""
    assert btu_per_gal_f(58.0) == pytest.approx(WATER_BTU_PER_GAL_F, abs=0.01)
    assert btu_per_gal_f(140.0) == pytest.approx(8.20, abs=0.005)
    assert btu_per_gal_f(212.0) == pytest.approx(8.05, abs=0.005)


def test_it_falls_over_the_tank_span() -> None:
    values = [btu_per_gal_f(t) for t in range(32, 213)]
    assert all(a > b for a, b in pairwise(values))


def test_the_heat_is_the_temperature_at_its_reference() -> None:
    assert heat_f(60.0) == pytest.approx(60.0, abs=1e-12)
    # Hot water's heat reads under its temperature.
    assert heat_f(140.0) == pytest.approx(139.35, abs=0.01)


@given(temps)
def test_the_heat_and_the_temperature_round_trip(t: float) -> None:
    assert temp_f(heat_f(t)) == pytest.approx(t, abs=1e-9)


@given(temps, temps)
def test_the_heat_is_the_heat_per_gallon_integrated(a: float, b: float) -> None:
    """Between two temperatures a gallon takes ``∫ c dT``, here by
    Simpson's rule, near exact on the quartic."""
    pieces = 200
    dt = (b - a) / pieces
    weights = [
        1 if k in (0, pieces) else 4 if k % 2 else 2 for k in range(pieces + 1)
    ]
    btu = (
        sum(w * btu_per_gal_f(a + k * dt) for k, w in enumerate(weights))
        * dt
        / 3.0
    )
    assert (heat_f(b) - heat_f(a)) * WATER_BTU_PER_GAL_F == pytest.approx(
        btu, abs=1e-6
    )
