"""A slower draw's cold side, some of it from the tank as well
(``DrawParams.undiluted_share``): each delivered gallon takes
``s + undiluted_share · (1 − s)`` of the tank's water, ``s`` the valve's
share."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sim_cases import T0

from nwp500 import sim
from nwp500.sim import Draw, Loads, delivery
from nwp500.sim.history import Step, drawn_gal
from nwp500.sim.physics import stratified as st
from nwp500.sim.physics.draw import hot_fraction, withdrawn_gal

SITE = sim.site_example_params()
VALVED = replace(SITE, draw=replace(SITE.draw, undiluted_share=0.0))
#: A shower at 1.1 gal/min: slower than ``undiluted_gpm``.
SLOW = Draw(at=T0 + timedelta(minutes=10), gallons=12.0, duration_s=655.0)


def _end(params: sim.HeaterParams) -> tuple[float, float]:
    trace = sim.standby(
        sim.HeaterState(upper_f=132.0, lower_f=131.0),
        sim.Environment(ambient_f=65.0, inlet_f=60.0),
        Loads(draws=(SLOW,)),
        params,
        start=T0,
        until=T0 + timedelta(hours=1),
    )
    last = trace.points[-1]
    return last.upper_f, last.lower_f


def test_the_share_moves_toward_the_tank_by_its_part() -> None:
    s = hot_fraction(130.0, 116.6, 60.0)
    assert hot_fraction(130.0, 116.6, 60.0, 0.25) == pytest.approx(
        s + 0.25 * (1.0 - s)
    )
    assert hot_fraction(130.0, 116.6, 60.0, 1.0) == pytest.approx(1.0)
    # Nothing the valve passes whole or takes none of changes.
    assert hot_fraction(110.0, 116.6, 60.0, 0.25) == 1.0
    assert hot_fraction(55.0, 116.6, 60.0, 0.25) == 0.0
    assert withdrawn_gal(10.0, 130.0, 116.6, 60.0, 0.25) == pytest.approx(
        10.0 * (s + 0.25 * (1.0 - s))
    )


def test_the_site_takes_a_quarter() -> None:
    assert SITE.draw.undiluted_share == sim.SITE_UNDILUTED_SHARE == 0.25
    # With no valve every gallon is the tank's already.
    d = sim.default_params()
    none = replace(d, draw=replace(d.draw, undiluted_share=0.0))
    assert delivery.deliverable(d, 132.0, 131.0).gal == (
        delivery.deliverable(none, 132.0, 131.0).gal
    )
    for bad in (-0.1, 1.1, float("nan")):
        with pytest.raises(ValueError, match="undiluted_share"):
            replace(SITE.draw, undiluted_share=bad)


def test_a_slow_draw_takes_more_of_the_tank() -> None:
    """Its cold reaches the lower probe further, between the valve's
    share and the tank's water whole."""
    upper, lower = _end(SITE)
    v_upper, v_lower = _end(VALVED)
    _, w_lower = _end(sim.with_valve(VALVED, sim.NO_VALVE))
    assert w_lower < lower < v_lower
    assert upper <= v_upper


def test_the_tank_gives_it_in_the_layers() -> None:
    lay = st.layout(SITE)
    state = st.estimate(lay, 132.0, 131.0)
    valve = (SITE.draw.delivery_intercept_f, SITE.draw.delivery_slope)
    valved = st.draw(lay, state, 10.0, 60.0, valve)
    more = st.draw(lay, state, 10.0, 60.0, valve, 0.25)
    whole = st.draw(lay, state, 10.0, 60.0, st.NO_VALVE)
    assert valved.withdrawn_gal < more.withdrawn_gal < whole.withdrawn_gal
    assert more.heat_btu > valved.heat_btu


def test_less_is_deliverable() -> None:
    """Each delivered gallon takes more of the tank: fewer of them
    before the tap runs under the line."""
    got = delivery.deliverable(SITE, 132.0, 131.0, inlet_f=60.0).gal
    valved = delivery.deliverable(VALVED, 132.0, 131.0, inlet_f=60.0).gal
    assert got < valved


def test_a_tank_gallon_delivers_less() -> None:
    """The history's tank gallons are the valve's delivery of them."""
    step = Step(
        seconds=60.0,
        upper_f=130.0,
        lower_f=128.0,
        flow_gpm=2.0,
        compressor_on=False,
        element_on=False,
        ambient_f=65.0,
        inlet_f=60.0,
        flow_volume="tank",
        at=T0,
    )
    assert drawn_gal(step, SITE) < drawn_gal(step, VALVED)
