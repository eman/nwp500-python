"""The default parameters by tank size (``nwp500.sim.default_params``)."""

from dataclasses import replace

import pytest

from nwp500.sim.defaults import default_params
from nwp500.sim.params import (
    DEFAULT,
    FITTED,
    MEASURED,
    params_from_document,
    params_to_document,
    provenance_of,
)


def test_the_65_round_trips_as_a_document():
    p = default_params()
    assert params_from_document(params_to_document(p)) == p


@pytest.mark.parametrize(("code", "gal"), [(1, 50.0), (3, 80.0)])
def test_other_sizes_scale_the_tank_volume_only(code: int, gal: float):
    base, other = default_params(2), default_params(code)
    assert other.tank.volume_gal == pytest.approx(63.2 * gal / 65.0)
    assert replace(other, tank=base.tank) == base


def test_an_unknown_size_is_refused():
    with pytest.raises(ValueError, match="volume_code"):
        default_params(4)


def test_the_constants_say_where_they_came_from():
    p = default_params()
    assert provenance_of(p.compressor, "compressor_constant") == FITTED
    assert provenance_of(p.controller, "restart_lockout_s") == MEASURED
    assert provenance_of(p.compressor, "polytropic_exp") == DEFAULT
    assert p.controller.restart_lockout_s == 330.0
    assert p.controller.tou_cap_f == 3.6


def test_the_65_is_ready_to_simulate():
    p = default_params()
    assert p.tank.stratification_gap_tau_h is not None
    assert p.compressor.compressor_constant > 0.0
    assert p.loss.ua_btu_hr_f is not None
