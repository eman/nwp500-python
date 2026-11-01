"""A fast draw (``DrawParams.undiluted_gpm``): at that flow or faster it
takes as much of the tank's water as it delivers, not the valve's share
of it."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sim_cases import T0

import nwp500.sim.carry as carry
from nwp500 import sim
from nwp500.sim import Draw, Loads

SITE = sim.site_example_params()
VALVED = replace(SITE, draw=replace(SITE.draw, undiluted_gpm=None))
#: A bath at 2.5 gal/min, and the same over twice as long.
FAST = Draw(at=T0 + timedelta(minutes=10), gallons=30.0, duration_s=720.0)
SLOW = FAST.model_copy(update={"duration_s": 1440.0})


def _coast(draw: Draw, params: sim.HeaterParams) -> sim.Trace:
    return sim.standby(
        sim.HeaterState(upper_f=135.0, lower_f=134.0),
        sim.Environment(ambient_f=65.0, inlet_f=58.0),
        Loads(draws=(draw,)),
        params,
        start=T0,
        until=T0 + timedelta(hours=1),
    )


def _end(trace: sim.Trace) -> tuple[float, float]:
    last = trace.points[-1]
    return last.upper_f, last.lower_f


def test_its_flow_is_its_gallons_over_its_time() -> None:
    assert FAST.flow_gpm == pytest.approx(2.5)
    assert Draw(at=T0, gallons=3.0).flow_gpm is None
    # An expected draw's rate cancels: its per-draw volume over its
    # per-draw time.
    expected = Draw(at=T0, gallons=0.5, per_draw_gal=25.0, duration_s=12.0)
    assert expected.flow_gpm == pytest.approx(2.5)


def test_the_threshold_is_a_positive_flow() -> None:
    assert SITE.draw.undiluted_gpm == sim.SITE_UNDILUTED_GPM == 2.0
    assert SITE.draw.undiluted(2.0)
    assert not SITE.draw.undiluted(1.9)
    assert not SITE.draw.undiluted(None)
    assert not VALVED.draw.undiluted(9.0)
    for bad in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError, match="undiluted_gpm"):
            replace(SITE.draw, undiluted_gpm=bad)


def test_a_fast_draw_takes_the_tank_water_whole() -> None:
    """Over the threshold the tank gives the 30 gal it delivers, not
    the valve's share: its cold reaches further up."""
    upper, lower = _end(_coast(FAST, SITE))
    v_upper, v_lower = _end(_coast(FAST, VALVED))
    assert lower < v_lower - 5.0
    assert upper <= v_upper
    no_valve = sim.with_valve(VALVED, sim.NO_VALVE)
    assert _end(_coast(FAST, no_valve)) == pytest.approx((upper, lower))


def test_a_slower_draw_goes_through_the_valve() -> None:
    assert _end(_coast(SLOW, SITE)) == _end(_coast(SLOW, VALVED))


def test_a_draw_all_at_once_has_no_flow_to_judge() -> None:
    once = FAST.model_copy(update={"duration_s": 0.0})
    assert _end(_coast(once, SITE)) == _end(_coast(once, VALVED))


def test_one_cut_by_the_carry_keeps_its_flow() -> None:
    """The draw's pieces before a cut stay as fast as the draw, each
    over its own span."""
    until = FAST.at + timedelta(minutes=5, seconds=30)
    kept = carry._drawn_by(Loads(draws=(FAST,)), until, SITE)  # pyright: ignore[reportPrivateUsage]
    assert [d.at for d in kept.draws] == [
        FAST.at + timedelta(minutes=k) for k in range(6)
    ]
    assert [d.flow_gpm for d in kept.draws] == pytest.approx([2.5] * 6)
    assert sum(d.gallons for d in kept.draws) == pytest.approx(15.0)


def test_a_recovery_under_way_takes_the_rest_whole() -> None:
    """``next_recovery`` from inside the draw takes the rest of it at
    its start as the walk would, the tank's water whole."""

    def rest(params: sim.HeaterParams) -> object:
        s = sim.Scenario(
            start=FAST.at + timedelta(minutes=2),
            horizon=timedelta(hours=3),
            tz="UTC",
            state=sim.HeaterState(upper_f=135.0, lower_f=134.0),
            settings=sim.Settings(setpoint_f=135.0, hp_lower_on_f=111.0),
            history=sim.History(compressor_stopped_at=T0 - timedelta(hours=3)),
            environment=sim.Environment(ambient_f=65.0, inlet_f=58.0),
            loads=Loads(draws=(FAST,)),
        )
        return sim.next_recovery(s, params).points

    assert rest(SITE) == rest(sim.with_valve(VALVED, sim.NO_VALVE))
    assert rest(SITE) != rest(VALVED)
