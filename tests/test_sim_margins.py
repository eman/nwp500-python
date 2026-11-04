"""How near a walk came to the heat pump's start triggers
(``nwp500.sim.margins``)."""

from datetime import UTC, datetime, timedelta

import pytest
from test_sim_api import WINDOW, _peak, _scenario, at

from nwp500.sim import (
    CirculationRun,
    Draw,
    HeaterState,
    Loads,
    Schedules,
    Settings,
    default_params,
    simulate,
)
from nwp500.sim.engine import PathPoint
from nwp500.sim.margins import start_margins
from nwp500.sim.physics.element import HeaterMode
from nwp500.sim.tou_triggers import UPPER_DEFICIT_F

T0 = datetime(2026, 10, 18, 7, 0, tzinfo=UTC)
SETPOINT = 141.8


def _p(
    minutes: float,
    upper: float,
    lower: float,
    *,
    heating: bool = False,
    mode: HeaterMode = "heat_pump",
    setpoint: float = SETPOINT,
    disabled: bool = False,
) -> PathPoint:
    return PathPoint(
        at=T0 + timedelta(minutes=minutes),
        upper_f=upper,
        lower_f=lower,
        setpoint_f=setpoint,
        heating=heating,
        input_wh=None,
        mode=mode,
        heating_disabled=disabled,
    )


def test_each_coast_its_nearest_approach_to_the_lower_trigger() -> None:
    points = [
        _p(0, 135.0, 120.0),
        _p(10, 134.0, 110.0),
        _p(20, 133.0, 115.0),
        _p(30, 133.0, 104.0, heating=True),
        _p(40, 140.0, 140.0),
        _p(50, 139.0, 130.0),
    ]
    got = start_margins(points, 104.9)
    assert [(m.trigger, m.started) for m in got] == [
        ("lower", True),
        ("lower", False),
    ]
    first, second = got
    assert (first.start, first.end) == (points[0].at, points[2].at)
    assert first.at == points[1].at
    assert first.margin_f == pytest.approx(110.0 - 104.9)
    assert second.margin_f == pytest.approx(130.0 - 104.9)


def test_the_lower_trigger_held_while_the_upper_zone_is_at_the_setpoint() -> (
    None
):
    # Heat Pump holds it; the point at the setpoint does not count.
    points = [_p(0, SETPOINT, 100.0), _p(10, 138.0, 108.0)]
    (m,) = start_margins(points, 104.9)
    assert m.margin_f == pytest.approx(108.0 - 104.9)
    # High Demand does not hold it.
    held = [_p(0, SETPOINT, 100.0, mode="high_demand")]
    (m,) = start_margins(held, 104.9)
    assert m.margin_f == pytest.approx(100.0 - 104.9)


def test_inside_a_window_the_upper_deficit_and_the_lower_crossing() -> None:
    # The lower trigger reads inside the window too: a crossing there
    # starts the heater at the close.
    window = ((T0 + timedelta(minutes=10), T0 + timedelta(minutes=30)),)
    points = [
        _p(0, 135.0, 112.0),
        _p(10, 130.0, 100.0),
        _p(20, 129.0, 99.0),
        _p(30, 128.5, 101.0),
    ]
    lower, upper = start_margins(points, 104.9, window)
    assert (lower.trigger, upper.trigger) == ("lower", "upper_at_tou_open")
    assert upper.at == points[2].at
    assert upper.margin_f == pytest.approx(129.0 - (SETPOINT - UPPER_DEFICIT_F))
    assert lower.at == points[2].at
    assert lower.margin_f == pytest.approx(99.0 - 104.9)


def test_the_lower_trigger_no_nearer_than_the_setpoint() -> None:
    # A low setpoint under hp_lower_on: the compressor's trigger is the
    # setpoint (controller.lower_trigger_f).
    points = [_p(0, 100.0, 104.0, mode="high_demand", setpoint=102.5)]
    (m,) = start_margins(points, 118.0)
    assert m.margin_f == pytest.approx(104.0 - 102.5)


def test_energy_saver_a_draw_releases_the_held_lower_trigger() -> None:
    points = [
        _p(0, SETPOINT + 5.0, 110.0, mode="energy_saver"),
        _p(10, SETPOINT + 4.0, 96.0, mode="energy_saver"),
        _p(20, SETPOINT + 3.0, 95.0, mode="energy_saver"),
    ]
    assert start_margins(points, 104.9) == ()
    drew = (Draw(at=T0 + timedelta(minutes=5), gallons=8.0),)
    (m,) = start_margins(points, 104.9, loads=Loads(draws=drew))
    assert m.at == points[1].at
    assert m.margin_f == pytest.approx(96.0 - 104.9)


def test_energy_saver_released_only_by_a_drop() -> None:
    # A draw that leaves the lower zone where it was does not release
    # the hold; a circulation run that takes it down does.
    es: HeaterMode = "energy_saver"
    points = [
        _p(0, SETPOINT + 5.0, 98.0, mode=es),
        _p(10, SETPOINT + 4.0, 98.0, mode=es),
        _p(20, SETPOINT + 3.0, 96.0, mode=es),
    ]
    flat = Loads(draws=(Draw(at=T0 + timedelta(minutes=5), gallons=0.5),))
    assert start_margins(points, 104.9, loads=flat) == ()
    run = CirculationRun(
        start=T0 + timedelta(minutes=12), end=T0 + timedelta(minutes=18)
    )
    (m,) = start_margins(points, 104.9, loads=Loads(circulation=(run,)))
    assert m.at == points[2].at
    assert m.margin_f == pytest.approx(96.0 - 104.9)


def test_energy_saver_circulation_as_the_walk_takes_it() -> None:
    # Two runs 6 min apart, neither in the step from 0 to 5 min, merge
    # within the default gap into one that is: the drop over the step
    # releases the hold. A run past circulation_known_until is not taken
    # and releases nothing.
    es: HeaterMode = "energy_saver"
    points = [
        _p(0, SETPOINT + 5.0, 98.0, mode=es),
        _p(5, SETPOINT + 4.0, 97.0, mode=es),
    ]
    runs = (
        CirculationRun(start=T0 - timedelta(minutes=6), end=T0),
        CirculationRun(
            start=T0 + timedelta(minutes=6), end=T0 + timedelta(minutes=10)
        ),
    )
    (m,) = start_margins(points, 104.9, loads=Loads(circulation=runs))
    assert m.at == points[1].at
    late = (
        CirculationRun(
            start=T0 + timedelta(minutes=2), end=T0 + timedelta(minutes=4)
        ),
    )
    unknown = Loads(circulation=late, circulation_known_until=T0)
    assert start_margins(points, 104.9, loads=unknown) == ()
    assert start_margins(points, 104.9, loads=Loads(circulation=late))


def test_energy_saver_a_draw_over_minutes_releases_at_each_piece() -> None:
    # Held in Energy Saver, the upper zone over the setpoint: the
    # engine starts at the draw's piece that takes the lower zone under
    # its trigger, minutes after the draw's onset.
    s = _scenario(
        state=HeaterState(upper_f=135.0, lower_f=110.0),
        settings=Settings(setpoint_f=118.0, mode=3, hp_lower_on_f=105.0),
        loads=Loads(draws=(Draw(at=at(1), gallons=15.0, duration_s=900.0),)),
    )
    result = simulate(s, default_params())
    (start,) = [h.start for h in result.heating][:1]
    assert start.trigger == "lower"
    assert start.at > at(1)
    got = start_margins(result.points, 105.0, loads=s.loads)
    lower = next(m for m in got if m.started)
    assert lower.end == start.at
    assert lower.margin_f <= 0.0


def test_heating_disabled_counts_for_neither() -> None:
    points = [_p(0, 120.0, 100.0, disabled=True), _p(10, 119.0, 99.0)]
    (m,) = start_margins(points, 104.9)
    assert m.at == points[1].at


def test_no_points_no_margins() -> None:
    assert start_margins([], 104.9) == ()


def test_a_draw_s_start_reads_the_state_after_the_drop() -> None:
    # The engine writes the state just after a draw at a start's instant,
    # heating, at the last coast point's instant: that is what crossed.
    s = _scenario(loads=Loads(draws=(Draw(at=at(1), gallons=20.0),)))
    result = simulate(s, default_params())
    (start,) = [h.start for h in result.heating]
    assert (start.at, start.trigger) == (at(1), "lower")
    lower = next(m for m in start_margins(result.points, 105.0) if m.started)
    assert lower.end == start.at
    assert lower.margin_f < 0.0


def test_a_vacation_walk_has_no_margins() -> None:
    s = _scenario(
        settings=Settings(setpoint_f=140.9, mode=5, hp_lower_on_f=105.0),
        loads=Loads(draws=(Draw(at=at(1), gallons=20.0),)),
    )
    result = simulate(s, default_params())
    assert result.heating == []
    assert start_margins(result.points, 105.0) == ()


def test_electric_and_no_lower_setting_count_for_neither() -> None:
    points = [_p(0, 120.0, 100.0, mode="electric")]
    assert start_margins(points, 104.9) == ()
    assert start_margins([_p(0, 130.0, 100.0)], None) == ()


def test_a_walk_s_start_at_a_window_opening_reached_its_trigger() -> None:
    s = _scenario(
        schedules=Schedules(tou_enabled=True, tou_periods=_peak(23, 4)),
        loads=Loads(draws=(Draw(at=at(1), gallons=6.0),)),
    )
    result = simulate(s, default_params(), tou_windows_in_force=WINDOW)
    (start,) = [h.start for h in result.heating]
    assert start.trigger == "upper_at_tou_open"
    got = start_margins(result.points, 105.0, WINDOW)
    upper = next(
        m for m in got if m.trigger == "upper_at_tou_open" and m.end == start.at
    )
    assert upper.started
    assert upper.margin_f <= 0.0
    # The coast after the recovery, to the walk's end, starts nothing.
    assert all(m.margin_f > 0.0 for m in got if not m.started)
