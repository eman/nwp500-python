"""The evaporator's temperature against the air
(``physics.compressor.evaporator_f``)."""

from dataclasses import replace

import pytest

from nwp500.sim.defaults import site_example_params
from nwp500.sim.physics.compressor import (
    EVAP_REF_AIR_F,
    evaporator_f,
    predict_physics_detailed,
)

P = site_example_params()


def test_at_the_reference_air_it_is_the_approach_below() -> None:
    assert EVAP_REF_AIR_F == 65.0
    assert evaporator_f(65.0, 18.0, 0.596) == pytest.approx(47.0)


def test_it_moves_the_slope_per_degree_of_air() -> None:
    assert evaporator_f(85.0, 18.0, 0.596) == pytest.approx(47.0 + 0.596 * 20)
    assert evaporator_f(45.0, 18.0, 0.596) == pytest.approx(47.0 - 0.596 * 20)


def test_a_slope_of_one_is_a_fixed_approach() -> None:
    for air in (40.0, 65.0, 90.0):
        assert evaporator_f(air, 18.0, 1.0) == pytest.approx(air - 18.0)


def _minutes(air: float, slope: float, coil: float | None = None) -> float:
    c = replace(P.compressor, evap_air_slope=slope)
    return predict_physics_detailed(
        t_start_lower=100.0,
        hp_lower_off=135.0,
        t_amb_mean=air,
        compressor_constant=c.compressor_constant,
        evap_approach_f=c.evap_approach_f,
        compressor=c,
        loss=P.loss,
        t_evap_override=coil,
        tank=P.tank,
    ).minutes


def test_the_integrator_uses_the_slope() -> None:
    """Off the reference air the slope changes the duration; at it, it
    does not."""
    assert _minutes(85.0, 0.596) != pytest.approx(_minutes(85.0, 1.0))
    assert _minutes(45.0, 0.596) < _minutes(45.0, 1.0)
    assert _minutes(65.0, 0.596) == pytest.approx(_minutes(65.0, 1.0))


def test_a_live_coil_reading_bypasses_it() -> None:
    assert _minutes(85.0, 0.596, coil=50.0) == pytest.approx(
        _minutes(85.0, 1.0, coil=50.0)
    )
