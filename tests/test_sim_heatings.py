"""A walk's heatings (``SimulationResult.heatings``) and when the tank
is first at temperature (``SimulationResult.fully_heated_at``)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sim_cases import days_of_draws

from nwp500 import sim
from nwp500.sim import Loads
from nwp500.sim.codec import result_to_document
from nwp500.sim.controller import Start, StopReason
from nwp500.sim.engine import HeatingInterval, Simulation
from nwp500.sim.result import (
    CHAINED,
    at_temperature,
    fully_heated_at,
    heatings,
)

T0 = datetime(2026, 11, 9, 1, 30, tzinfo=UTC)


def _interval(
    start: float,
    end: float,
    stop: StopReason,
    *,
    source: str = "compressor",
    input_wh: float | None = 100.0,
) -> HeatingInterval:
    return HeatingInterval(
        start=Start(at=T0 + timedelta(minutes=start), cause="heater"),
        end=T0 + timedelta(minutes=end),
        target_f=140.0,
        capped=stop == "cap",
        stop=stop,
        input_wh=input_wh,
        confidence=None,
        source=source,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    )


def _walk(
    *intervals: HeatingInterval,
    reached: tuple[tuple[datetime, float], ...] = (),
) -> Simulation:
    return Simulation(
        points=[],
        heating=list(intervals),
        writes=[],
        reasons=[],
        reached=list(reached),
    )


def test_the_first_heating_that_reaches_its_target_is_fully_heated() -> None:
    """Not the first heating when a mode change stops it short."""
    stopped = _interval(0, 100, "mode")
    # Electric's chained lower element ends the second heating.
    upper = _interval(210, 260, "target", source="element")
    lower = _interval(260, 300, "target", source="element")
    walk = _walk(stopped, upper, lower)

    got = heatings(walk)

    assert [h.last for h in got] == [stopped, lower]
    assert [h.intervals for h in got] == [(stopped,), (upper, lower)]
    assert [h.at_temperature for h in got] == [False, True]
    assert fully_heated_at(walk) == lower.end
    assert fully_heated_at(_walk(stopped)) is None
    assert fully_heated_at(_walk()) is None


def test_a_tou_capped_heating_is_fully_heated() -> None:
    """Inside a TOU period the heater's target is its cap short."""
    capped = _interval(0, 100, "cap")
    assert fully_heated_at(_walk(capped)) == capped.end


def test_a_write_ending_a_heating_at_its_new_setpoint_is_at_temperature() -> (
    None
):
    write = _interval(0, 100, "write")
    reached = _walk(write, reached=((write.end, 140.0),))
    short = _walk(write)

    # The walk counts it reached: the tank was at the new setpoint.
    assert at_temperature(reached, write)
    assert not at_temperature(short, write)
    assert not at_temperature(reached, replace(write, stop="mode"))
    assert at_temperature(short, replace(write, stop="cap"))
    assert fully_heated_at(reached) == write.end
    assert fully_heated_at(short) is None


def test_an_element_inside_a_longer_compressor_run_ends_nothing() -> None:
    """The element's end is not the heating's: the compressor runs on,
    and the run that starts within a minute of its end joins it."""
    compressor = _interval(0, 120, "target", input_wh=1000.0)
    element = _interval(30, 50, "mode", source="element", input_wh=500.0)
    later = _interval(119, 130, "cap", input_wh=100.0)
    apart = _interval(130 + 1.5, 140, "target")

    first, second = heatings(_walk(compressor, element, later, apart))

    assert first.intervals == (compressor, element, later)
    assert first.last is later
    assert first.start == compressor.start.at
    assert first.end == later.end
    assert first.stop == "cap"
    assert first.at_temperature
    assert first.input_wh == pytest.approx(1600.0)
    assert second.intervals == (apart,)


def test_a_heating_starting_within_a_minute_joins_the_one_before() -> None:
    first = _interval(0, 10, "target")
    joined = _interval(10 + CHAINED.total_seconds() / 60.0, 20, "target")
    assert len(heatings(_walk(first, joined))) == 1
    late = _interval(10 + CHAINED.total_seconds() / 60.0 + 0.01, 20, "target")
    assert len(heatings(_walk(first, late))) == 2


def test_a_heating_with_an_unpriced_interval_has_no_energy() -> None:
    (h,) = heatings(
        _walk(
            _interval(0, 10, "target"),
            _interval(10, 20, "target", input_wh=None),
        )
    )
    assert h.input_wh is None


def test_electrics_upper_then_lower_element_is_one_heating() -> None:
    """Electric from a cool tank: the upper element to its target, the
    lower element at once after it, one heating that ends at the lower
    element's target."""
    scenario = days_of_draws(1).model_copy(
        update={
            "state": sim.HeaterState(upper_f=110.0, lower_f=100.0),
            "settings": sim.Settings(
                setpoint_f=130.0, mode=2, hp_lower_on_f=111.0
            ),
            "loads": Loads(),
        }
    )
    result = sim.simulate(scenario, sim.default_params())
    upper, lower = result.heating[:2]
    assert (upper.zone, lower.zone) == ("upper", "lower")

    first = result.heatings[0]

    assert first.intervals[:2] == (upper, lower)
    assert first.start == upper.start.at
    assert first.end > upper.end
    assert first.at_temperature
    assert result.fully_heated_at == first.end
    assert result_to_document(result)["fully_heated_at"] == (
        first.end.isoformat()
    )
