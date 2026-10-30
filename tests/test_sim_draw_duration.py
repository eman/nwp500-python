"""A draw over time: taken a minute at a time over its duration, so the
heating meets it between its minutes, as a meter's per-minute draws."""

import json
import math
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sim_cases import T0

from nwp500 import sim
from nwp500.sim import Draw, Loads, codec
from nwp500.sim.inputs import DRAW_STEP
from nwp500.sim.physics.stratified import ACTIVE_STEP

PARAMS = sim.site_example_params()
SHOWER = Draw(at=T0 + timedelta(minutes=10), gallons=60.0, duration_s=1800.0)
#: The same shower as a meter counts it, 2 gal each minute.
METERED = tuple(
    Draw(at=T0 + timedelta(minutes=10 + i), gallons=2.0) for i in range(30)
)


def _scenario(draws: tuple[Draw, ...], mode: int) -> sim.Scenario:
    return sim.Scenario(
        start=T0,
        horizon=timedelta(hours=3),
        tz="UTC",
        state=sim.HeaterState(upper_f=130.0, lower_f=128.0),
        settings=sim.Settings(setpoint_f=130.0, hp_lower_on_f=111.0, mode=mode),
        history=sim.History(compressor_stopped_at=T0 - timedelta(hours=3)),
        environment=sim.Environment(ambient_f=65.0, inlet_f=58.0),
        loads=Loads(draws=draws),
    )


def test_its_pieces_fall_on_the_walks_minutes() -> None:
    """At its onset and each whole minute before its end, each the
    gallons of its span, summing to the draw."""
    assert DRAW_STEP == ACTIVE_STEP
    d = Draw(
        at=T0 + timedelta(minutes=10, seconds=20),
        gallons=15.0,
        duration_s=450.0,
    )
    pieces = d.pieces()
    assert [(at - T0).total_seconds() for at, _ in pieces] == [
        620,
        660,
        720,
        780,
        840,
        900,
        960,
        1020,
    ]
    assert [g for _, g in pieces] == pytest.approx(
        [40 / 30, 2, 2, 2, 2, 2, 2, 50 / 30]
    )
    assert sum(g for _, g in pieces) == 15.0
    assert Draw(at=T0, gallons=3.0).pieces() == ((T0, 3.0),)


@pytest.mark.parametrize("mode", [1, 3, 4])
def test_a_draw_over_time_walks_as_its_minutes(mode: int) -> None:
    """A 60 gal shower over 30 min heats as the meter's 2 gal a minute
    does, not as 60 gal at once: the compressor starts 12 min later and
    High Demand's upper element 17 min later than at once."""
    over = sim.simulate(_scenario((SHOWER,), mode), PARAMS)
    metered = sim.simulate(_scenario(METERED, mode), PARAMS)
    assert over.points == metered.points
    assert over.simulation.heating == metered.simulation.heating
    assert over.delivery == metered.delivery
    at_once = sim.simulate(
        _scenario((SHOWER.model_copy(update={"duration_s": 0.0}),), mode),
        PARAMS,
    )
    first = {
        (h.source, h.zone): (h.start.at - T0) / timedelta(minutes=1)
        for h in reversed(over.simulation.heating)
    }
    once = {
        (h.source, h.zone): (h.start.at - T0) / timedelta(minutes=1)
        for h in reversed(at_once.simulation.heating)
    }
    assert first[("compressor", None)] == once[("compressor", None)] + 12
    if mode == 4:
        assert first[("element", "upper")] == once[("element", "upper")] + 17


def test_standby_takes_it_as_its_minutes() -> None:
    def coast(draws: tuple[Draw, ...]) -> sim.Trace:
        s = _scenario(draws, 3)
        return sim.standby(
            s.state,
            s.environment,
            s.loads,
            PARAMS,
            start=T0,
            until=T0 + timedelta(hours=1),
            settings=s.settings,
        )

    over, metered = coast((SHOWER,)), coast(METERED)
    assert over.points == metered.points
    assert (over.starts_at, over.trigger) == (
        metered.starts_at,
        metered.trigger,
    )


def test_a_scenario_cut_through_it_chains_to_the_whole() -> None:
    """Cut halfway through the shower and resumed from the first part's
    end state, the draw given to both: the second takes the rest, and
    the two heat as one scenario does."""
    s = _scenario((SHOWER,), 1)
    whole = sim.simulate(s, PARAMS)
    cut = T0 + timedelta(minutes=25)
    first = sim.simulate(s.model_copy(update={"horizon": cut - T0}), PARAMS)
    later, _ = codec.scenario_from_document(
        json.loads(
            json.dumps(
                codec.scenario_to_document(
                    s.model_copy(
                        update={
                            "start": cut,
                            "horizon": s.until - cut,
                            "state": first.end_state,
                            "history": first.end_history,
                            "settings": first.end_settings,
                        }
                    )
                )
            )
        )
    )
    second = sim.simulate(later, PARAMS)
    assert [h.start.at for h in second.simulation.heating] == [
        h.start.at for h in whole.simulation.heating
    ]
    end, ends = whole.points[-1], second.points[-1]
    assert (ends.upper_f, ends.lower_f) == pytest.approx(
        (end.upper_f, end.lower_f)
    )


def test_next_recovery_takes_the_rest_of_the_draw_at_its_start() -> None:
    """The recovery forecast takes no draws, so the shower's rest past
    the trigger is taken where the recovery starts: as its first
    12 minutes over time and the other 36 gal at that instant."""
    split = (
        Draw(at=SHOWER.at, gallons=24.0, duration_s=720.0),
        Draw(at=SHOWER.at + timedelta(minutes=12), gallons=36.0),
    )
    over = sim.next_recovery(_scenario((SHOWER,), 1), PARAMS)
    assert over.outcome == "ok"
    assert over.start_minute == 22.0
    assert over.points == sim.next_recovery(_scenario(split, 1), PARAMS).points


@pytest.mark.parametrize("seconds", [math.inf, math.nan, 86400.5, -1.0])
def test_a_draw_runs_a_day_at_most(seconds: float) -> None:
    with pytest.raises(ValidationError):
        Draw(at=T0, gallons=1.0, duration_s=seconds)


def test_a_running_recovery_takes_the_rest_of_a_draw_under_way() -> None:
    """Ten minutes into the shower with the compressor running, the
    recovery goes on from the tank its other 40 gal leave."""
    s = _scenario((SHOWER,), 1)
    s = s.model_copy(
        update={
            "start": SHOWER.at + timedelta(minutes=10),
            "state": sim.HeaterState(
                upper_f=125.0, lower_f=100.0, compressor_running=True
            ),
        }
    )
    rest = s.model_copy(
        update={"loads": Loads(draws=(Draw(at=s.start, gallons=40.0),))}
    )
    none = s.model_copy(update={"loads": Loads()})
    under_way = sim.next_recovery(s, PARAMS)
    assert under_way.points == sim.next_recovery(rest, PARAMS).points
    assert (
        under_way.points[-1][0] > sim.next_recovery(none, PARAMS).points[-1][0]
    )
