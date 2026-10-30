"""Electric heats again later in a stint.

Electric's later starts are not measured (one mid-stint start on the
record), so they follow the elements in the heat pump's place: the
heater's own triggers start them by Electric's entry rule, and the upper
element starts again as High Demand's does, 4.1 °F short of the
setpoint. Each answer says so (``electric_later_starts_unverified``).
"""

import json
from datetime import timedelta
from typing import Any

import pandas as pd
import pytest
from sim_cases import PARAMS, T0, days_of_draws

from nwp500 import sim
from nwp500.sim import Loads
from nwp500.sim.controller import ELECTRIC_LATER_STARTS_UNVERIFIED
from nwp500.sim.engine import Heater, Resume, simulate
from nwp500.sim.tank_physics import TankPhysics

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


def _walk(**over: Any) -> dict[str, Any]:
    """Two hours in Electric, the lower zone just over the heater's
    threshold and the upper at the setpoint, a draw 10 minutes in that
    takes both down."""
    until = T0 + timedelta(hours=2)
    air = pd.DataFrame(
        {"ambient_f": 68.0},
        index=pd.date_range(
            T0 - timedelta(hours=1), until + timedelta(hours=20), freq="10min"
        ),
    )
    walk: dict[str, Any] = {
        "start": T0,
        "until": until,
        "setpoint_f": 130.0,
        "upper_f": 129.7,
        "lower_f": 111.6,
        "running": False,
        "heater": Heater(hp_lower_on_f=111.0, mode="electric"),
        "physics": TankPhysics(
            PARAMS, air, 55.0, draws_on=True, low_confidence_floor=0.6
        ),
        "draws": [(T0 + timedelta(minutes=10), 6.0)],
        "stopped_at": T0 - timedelta(hours=3),
    }
    return walk | over


def test_a_draw_firing_the_trigger_is_met_from_the_tank_it_leaves() -> None:
    """A draw that takes the lower zone past the heater's threshold
    leaves the upper zone 2 °F short: the elements answer that tank,
    the upper element first."""
    got = simulate(**_walk())
    first, then = got.heating[:2]
    assert first.start.at == T0 + timedelta(minutes=10)
    assert (first.zone, first.start.trigger) == ("upper", "lower")
    assert (then.zone, then.start.trigger) == (
        "lower",
        "electric_lower_after_upper",
    )


@pytest.mark.parametrize("zone", ["upper", "lower"])
def test_a_resume_keeps_what_the_restart_rests_on(zone: str) -> None:
    """A walk going on while an element Electric's later rules started
    is heating, the upper or the lower after it, says those rules are
    unverified."""
    kw = _walk()
    run = next(h for h in simulate(**kw).heating if h.zone == zone)
    cut = run.start.at + (run.end - run.start.at) / 2
    to_cut: dict[str, Any] = {**kw, "until": cut}
    head = simulate(**to_cut)
    assert head.resume is not None
    resume = Resume.from_document(
        json.loads(json.dumps(head.resume.to_document()))
    )
    last = head.points[-1]
    assert last.layers_f is not None
    part: dict[str, Any] = {
        **kw,
        "start": cut,
        "upper_f": last.upper_f,
        "lower_f": last.lower_f,
        "state": kw["physics"].layers(list(last.layers_f)),
        "draws": [],
        "resume": resume,
    }
    tail = simulate(**part)
    assert tail.heating[0].zone == zone
    assert ELECTRIC_LATER_STARTS_UNVERIFIED in tail.reasons


def test_a_mark_at_the_draw_moves_nothing() -> None:
    """A mark where a draw fires the trigger: the elements answer the
    tank the draw leaves, as in the walk without it."""
    kw = _walk()
    with_mark: dict[str, Any] = {**kw, "marks": [T0 + timedelta(minutes=10)]}
    marked = simulate(**with_mark)
    plain = simulate(**kw)
    assert marked.heating[0].zone == "upper"
    assert [(h.zone, h.start.at, h.end) for h in marked.heating] == [
        (h.zone, h.start.at, h.end) for h in plain.heating
    ]


@pytest.mark.parametrize(
    ("setpoint", "lower_on"), [(104.0, 104.9), (110.0, 111.0)]
)
def test_a_setpoint_at_the_lower_threshold_does_not_cycle(
    setpoint: float, lower_on: float
) -> None:
    """The elements stop at the setpoint: with the heater's lower
    threshold at or over it they answer it no nearer than the upper
    element's restart, so two days of standby start them a few times,
    not every few minutes."""
    s = days_of_draws(2).model_copy(
        update={
            "state": sim.HeaterState(
                upper_f=setpoint - 2, lower_f=setpoint - 12
            ),
            "settings": sim.Settings(
                setpoint_f=setpoint, mode=2, hp_lower_on_f=lower_on
            ),
            "loads": Loads(),
        }
    )
    got = sim.simulate(s, sim.site_example_params())
    assert len(got.heating) <= 12
    assert min(h.end - h.start.at for h in got.heating) > timedelta(minutes=1)


def test_a_draw_from_a_full_tank_starts_the_elements_at_once() -> None:
    """Both zones at the setpoint, a draw takes the lower one far past the
    heater's threshold: nothing was short before it, so the elements
    start on the tank it leaves, at its instant, not at the coast's
    next reading."""
    draw = T0 + timedelta(minutes=10)
    got = simulate(**_walk(upper_f=130.2, lower_f=130.1, draws=[(draw, 15.0)]))
    first = got.heating[0]
    assert (first.start.at, first.zone) == (draw, "lower")


def test_standby_reads_the_lower_trigger_where_the_walk_does() -> None:
    """A setpoint under the heater's lower threshold in Electric: the
    standby forecast reads the trigger at the elements' restart, as the
    walk does, not at once."""
    s = days_of_draws(1).model_copy(
        update={
            "state": sim.HeaterState(upper_f=109.8, lower_f=109.5),
            "settings": sim.Settings(
                setpoint_f=110.0, mode=2, hp_lower_on_f=111.0
            ),
            "loads": Loads(),
        }
    )
    trace = sim.standby(
        s.state,
        s.environment,
        s.loads,
        sim.site_example_params(),
        start=s.start,
        until=s.start + timedelta(hours=24),
        settings=s.settings,
    )
    assert trace.starts_at is not None
    assert trace.starts_at > s.start
    assert trace.lower_margin_f == pytest.approx(
        trace.points[-1].lower_f - (110.0 - 4.1)
    )


def test_standby_reads_the_fallbacks_lower_trigger_where_the_walk_does() -> (
    None
):
    """Heat Pump mode with the air out of the heat pump's range and a
    setpoint under the lower threshold: the elements answer the trigger,
    and the standby forecast reads it where the walk does."""
    s = days_of_draws(1).model_copy(
        update={
            "state": sim.HeaterState(upper_f=109.8, lower_f=109.5),
            "settings": sim.Settings(setpoint_f=110.0, hp_lower_on_f=111.0),
            "environment": sim.Environment(ambient_f=20.0, inlet_f=60.0),
            "loads": Loads(),
        }
    )
    params = sim.site_example_params()
    trace = sim.standby(
        s.state,
        s.environment,
        s.loads,
        params,
        start=s.start,
        until=s.start + timedelta(hours=24),
        settings=s.settings,
    )
    walk = sim.simulate(
        s.model_copy(update={"horizon": timedelta(hours=24)}), params
    )
    assert trace.starts_at is not None
    assert trace.starts_at > s.start
    assert walk.heating[0].start.at == pytest.approx(
        trace.starts_at, abs=timedelta(minutes=10)
    )
    assert trace.lower_margin_f == pytest.approx(
        trace.points[-1].lower_f - (110.0 - 4.1)
    )
