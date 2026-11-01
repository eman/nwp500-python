"""A slower draw's cold side, some of it from the tank as well
(``DrawParams.undiluted_share``): each delivered gallon takes
``s + undiluted_share · (1 − s)`` of the tank's water, ``s`` the valve's
share."""

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest
from sim_cases import T0

from nwp500 import sim
from nwp500.sim import Draw, Loads, delivery
from nwp500.sim import tank_fit as tf
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


def test_an_instant_draw_in_the_engine_takes_more() -> None:
    """A draw at an instant while the compressor runs, taken through
    ``TankPhysics.draw``: the valve's share and a quarter of the cold
    side's."""

    def low(params: sim.HeaterParams) -> float:
        s = sim.Scenario(
            start=T0,
            horizon=timedelta(hours=1),
            tz="UTC",
            state=sim.HeaterState(upper_f=132.0, lower_f=105.0),
            settings=sim.Settings(setpoint_f=132.0, hp_lower_on_f=111.0),
            history=sim.History(compressor_stopped_at=T0 - timedelta(hours=3)),
            environment=sim.Environment(ambient_f=65.0, inlet_f=60.0),
            loads=Loads(
                draws=(Draw(at=T0 + timedelta(minutes=10), gallons=12.0),)
            ),
        )
        got = sim.simulate(s, params)
        assert got.heating[0].start.at == T0
        at = T0 + timedelta(minutes=10)
        return [p.lower_f for p in got.points if p.at == at][-1]

    assert low(SITE) < low(VALVED)


def test_the_resolution_judges_the_same_gallons() -> None:
    """26 gal from 118 and 100 degF: short of what the valve's share
    delivers, out of a probe's reach of what the site's does."""
    site = delivery.deliverable(SITE, 118.0, 100.0, inlet_f=60.0).gal
    valved = delivery.deliverable(VALVED, 118.0, 100.0, inlet_f=60.0).gal
    assert site < 26.0 < valved
    assert not delivery.within_resolution(
        SITE, 118.0, 100.0, None, 26.0, inlet_f=60.0
    )
    assert delivery.within_resolution(
        VALVED, 118.0, 100.0, None, 26.0, inlet_f=60.0
    )


def test_the_tank_fit_walks_it() -> None:
    """The coasts the fit scores and the replay it starts them from both
    take the share."""
    coast = tf.Coast(
        start=T0,
        end=T0 + timedelta(hours=1),
        upper_f=132.0,
        lower_f=131.0,
        air=((T0, 65.0),),
        observed=((T0 + timedelta(hours=1), 130.0, 120.0),),
        draws=((T0 + timedelta(minutes=10), 12.0),),
    )
    (_,), (site,) = tf.errors(SITE, None, coast)
    (_,), (valved,) = tf.errors(VALVED, None, coast)
    assert site < valved
    n = 600
    record = tf.TankRecord(
        start=T0,
        upper_f=np.full(n, 132.0),
        lower_f=np.full(n, 131.0),
        air_f=np.full(n, 65.0),
        compressor=(),
        element=(),
        circulating=(),
        draws=((T0 + timedelta(minutes=300), 12.0),),
    )
    at = T0 + timedelta(minutes=330)
    lows = []
    for p in (SITE, VALVED):
        lay = st.layout(p)
        state = tf.replay(lay, p, record, at, gain=0.0)
        assert state is not None
        lows.append(st.observe(lay, state)[1])
    assert lows[0] < lows[1]


def test_all_of_the_cold_side_is_the_tank_water_whole() -> None:
    """With the whole cold side from the tank, the gallons the tap gets
    are the tank's own down to the tank water the valve delivers the
    line from: through the plug and the inlet zone alike."""
    lay = st.layout(SITE)
    a, b = SITE.draw.delivery_intercept_f, SITE.draw.delivery_slope
    line = 105.0
    for upper, lower in ((140.0, 139.0), (132.0, 118.0), (125.0, 104.0)):
        state = st.mix(st.estimate(lay, upper, lower))
        whole = st.deliverable_gal(lay, state, line, 60.0, (a, b), 1.0)
        own = st.deliverable_gal(
            lay, state, max(line, (line - a) / b), 60.0, st.NO_VALVE
        )
        assert whole == pytest.approx(own)
        assert whole < st.deliverable_gal(lay, state, line, 60.0, (a, b), 0.25)
