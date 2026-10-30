"""Electric heats again later in a stint.

Electric's later starts are not measured (one mid-stint start on the
record), so they follow the elements in the heat pump's place: the
heater's own triggers start them by Electric's entry rule, and the upper
element starts again as High Demand's does, 4.1 °F short of the
setpoint. Each answer says so (``electric_later_starts_unverified``).
"""

from datetime import timedelta

import pytest
from sim_cases import days_of_draws

from nwp500 import sim
from nwp500.sim import Loads
from nwp500.sim.controller import ELECTRIC_LATER_STARTS_UNVERIFIED

SETPOINT = 130.0
#: Where the upper element starts again (``upper_reengages_below_setpoint_f``).
RESTARTS_AT = SETPOINT - 4.1


def _electric(*, draws: bool) -> sim.Scenario:
    base = days_of_draws(2)
    return base.model_copy(
        update={
            "state": sim.HeaterState(upper_f=128.0, lower_f=118.0),
            "settings": sim.Settings(
                setpoint_f=SETPOINT, mode=2, hp_lower_on_f=111.0
            ),
            **({} if draws else {"loads": Loads()}),
        }
    )


@pytest.mark.parametrize("draws", [False, True], ids=["standby", "draws"])
def test_two_days_in_electric_keep_the_upper_zone_in_its_band(
    draws: bool,
) -> None:
    """Two days in Electric: the elements heat again and again, the
    upper zone kept between where the upper element starts and the
    setpoint, the lower zone no lower than the heater's threshold."""
    got = sim.simulate(_electric(draws=draws), sim.site_example_params())
    later = [
        h for h in got.heating if h.start.trigger == "electric_upper_short"
    ]
    assert len(later) >= 4
    assert all(h.source == "element" for h in got.heating)
    # Past the first stint, the band holds to the probe's step.
    settled = got.points[len(got.points) // 4 :]
    assert min(p.upper_f for p in settled) >= RESTARTS_AT - 0.1
    assert max(p.upper_f for p in settled) <= SETPOINT + 2.5
    assert min(p.lower_f for p in settled) >= 111.0 - 0.1
    assert ELECTRIC_LATER_STARTS_UNVERIFIED in got.reasons
    assert "element_later_starts_not_modelled" not in got.reasons


def test_the_heat_pumps_place_keeps_to_its_triggers() -> None:
    """Heat Pump with the air out of the heat pump's range, a day's
    draws: the elements answer the heater's own triggers only, not
    Electric's upper rule."""
    params = sim.site_example_params()
    base = days_of_draws(1).model_copy(
        update={
            "horizon": timedelta(hours=12),
            "state": sim.HeaterState(upper_f=128.0, lower_f=118.0),
            "settings": sim.Settings(setpoint_f=SETPOINT, hp_lower_on_f=111.0),
            "environment": sim.Environment(ambient_f=20.0, inlet_f=60.0),
        }
    )
    got = sim.simulate(base, params)
    assert [
        h
        for h in got.heating
        if h.source == "element" and h.start.trigger == "lower"
    ], "the elements answer the heater's lower trigger"
    assert not [
        h for h in got.heating if h.start.trigger == "electric_upper_short"
    ]
    assert ELECTRIC_LATER_STARTS_UNVERIFIED not in got.reasons
