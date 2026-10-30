"""A walk that goes on from where another ended answers as the two
walked as one.

A scheduler that stands the simulator in for a heater calls it once a
step, each call from where the last left the heater: the engine's
``Simulation.resume`` (``simulate(resume=...)``), and the public
``SimulationResult.end_state``, ``end_history`` and ``end_settings``.
Chained at a mark of the clock's grid, a step's end, the calls are the
walk whole with marks at the cuts, which stop the walk and read the
tank there and change nothing else.
"""

import dataclasses
import json
import math
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from sim_cases import days_of_draws, walk_case

from nwp500 import sim
from nwp500.sim import (
    Commands,
    History,
    Loads,
    ReservationEntry,
    Schedules,
    TouPeriod,
    codec,
    engine,
)
from nwp500.sim.controller import TOU_CAP_PROJECTED
from nwp500.sim.engine import RESUME_DROPPED, RESUME_VERSION, Resume, Write
from nwp500.sim.heat_pump_recovery import ModelDuration, RecoveryContext
from nwp500.sim.inputs import Write as CommandWrite
from nwp500.sim.params import HeaterParams

#: Cases of ``walk_case`` across the modes, among them ones a cut once
#: moved: a start triggered on a call's end (2), an element in the heat
#: pump's place as the air stays out of its range (24), the heat pump
#: back in range on a call's end (137), and the upper element's later
#: start on a recovery's path (9).
SEEDS = (1, 2, 3, 8, 9, 24, 44, 47, 50, 75, 137)


def _fires(e: engine.Entry) -> datetime:
    return Write(
        e.at, e.setpoint_f, e.mode, "plan", "entry", e.id, e.written_at
    ).fires_at


def _cuts(kw: dict[str, Any], every: timedelta) -> list[datetime]:
    """Instants on the clock's 10-minute grid, ``every`` apart, inside
    the walk."""
    t0, until = kw["start"], kw["until"]
    at = t0.replace(minute=t0.minute - t0.minute % 10, second=0) + timedelta(
        minutes=10
    )
    out: list[datetime] = []
    while at < until:
        out.append(at)
        at += every
    return out


def _chained(
    kw: dict[str, Any], cuts: list[datetime], *, via_json: bool
) -> list[engine.Simulation]:
    """The walk, one call per span between ``cuts``, each from the
    tank, the setpoint, the mode and the resume the last left."""
    edges = [kw["start"], *cuts, kw["until"]]
    out: list[engine.Simulation] = []
    resume: Resume | None = None
    for a, b in pairwise(edges):
        part: dict[str, Any] = {
            **kw,
            "start": a,
            "until": b,
            "entries": [e for e in kw["entries"] if a <= _fires(e) < b],
        }
        if resume is not None:
            last = out[-1].points[-1]
            assert last.layers_f is not None
            part |= {
                "upper_f": last.upper_f,
                "lower_f": last.lower_f,
                "state": kw["physics"].layers(list(last.layers_f)),
                "setpoint_f": resume.controller.setpoint_f,
                "heater": dataclasses.replace(
                    kw["heater"], mode=resume.controller.mode.commanded
                ),
                "resume": resume,
            }
        got = engine.simulate(**part)
        out.append(got)
        resume = got.resume
        assert resume is not None
        if via_json:
            resume = Resume.from_document(
                json.loads(json.dumps(resume.to_document()))
            )
    return out


def _joined(
    calls: list[engine.Simulation],
) -> tuple[list[engine.PathPoint], list[engine.HeatingInterval]]:
    """The calls' paths end to end, and their intervals with each one a
    call ended carried on into the next made one again."""
    points: list[engine.PathPoint] = []
    heating: list[engine.HeatingInterval] = []
    for call in calls:
        at = call.points[0].at
        points += call.points[1:] if points else call.points
        for h in call.heating:
            j = next(
                (
                    j
                    for j in range(len(heating) - 1, -1, -1)
                    if h.start.at < at
                    and heating[j].start == h.start
                    and heating[j].source == h.source
                    and heating[j].stop == "horizon"
                    and heating[j].end == at
                ),
                None,
            )
            if j is None:
                heating.append(h)
                continue
            before = heating[j].input_wh
            heating[j] = dataclasses.replace(
                h,
                input_wh=None
                if before is None or h.input_wh is None
                else before + h.input_wh,
            )
    return points, heating


def _same_heating(
    a: list[engine.HeatingInterval], b: list[engine.HeatingInterval]
) -> bool:
    """Equal intervals, their energy to rounding (summed by call)."""
    return len(a) == len(b) and all(
        dataclasses.replace(x, input_wh=None)
        == dataclasses.replace(y, input_wh=None)
        and (x.input_wh is None) == (y.input_wh is None)
        and (
            x.input_wh is None
            or y.input_wh is None
            or math.isclose(x.input_wh, y.input_wh, rel_tol=1e-9, abs_tol=1e-6)
        )
        for x, y in zip(a, b, strict=True)
    )


def _marked(kw: dict[str, Any], cuts: list[datetime]) -> dict[str, Any]:
    """``kw`` with a mark at each of ``cuts`` too."""
    return {**kw, "marks": sorted({*kw["marks"], *cuts})}


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("via_json", [False, True], ids=["object", "json"])
def test_calls_chained_are_the_walk_whole(seed: int, via_json: bool) -> None:
    kw = walk_case(seed)
    cuts = _cuts(kw, timedelta(hours=1))
    whole = engine.simulate(**_marked(kw, cuts))
    calls = _chained(walk_case(seed), cuts, via_json=via_json)
    points, heating = _joined(calls)
    assert points == whole.points
    assert _same_heating(heating, whole.heating)


#: Cases a mark moved when the upper element's later start was read
#: only at the walk's events, not along a recovery's path.
CROSSED = (9, 14, 80, 89, 103)


@pytest.mark.parametrize("seed", CROSSED)
def test_a_mark_does_not_move_the_upper_elements_later_start(
    seed: int,
) -> None:
    """A mark stops the walk and reads the tank there: the upper
    element's later start is the same without it, found where the upper
    zone reaches it on a recovery's path as on a coast's."""
    kw = walk_case(seed)
    marked = engine.simulate(**_marked(kw, _cuts(kw, timedelta(hours=1))))
    plain = engine.simulate(**walk_case(seed))
    assert _same_heating(plain.heating, marked.heating)


def test_a_resume_from_another_instant_is_refused() -> None:
    kw = walk_case(1)
    first = engine.simulate(**kw)
    assert first.resume is not None
    later: dict[str, Any] = {
        **kw,
        "start": kw["until"] + timedelta(minutes=10),
        "until": kw["until"] + timedelta(hours=1),
        "resume": first.resume,
    }
    with pytest.raises(ValueError, match="cannot go on"):
        engine.simulate(**later)


def test_a_resume_from_another_instant_is_refused_even_dropped() -> None:
    """A scenario that starts elsewhere than its resume ended is refused,
    into Vacation too, where the resume would be dropped."""
    params = sim.site_example_params()
    base = days_of_draws(1).model_copy(
        update={"horizon": timedelta(hours=1), "loads": Loads()}
    )
    first = sim.simulate(base, params)
    assert first.end_settings is not None
    for mode in (1, 5):
        later = base.model_copy(
            update={
                "start": first.until + timedelta(hours=3),
                "state": first.end_state,
                "history": first.end_history,
                "settings": first.end_settings.model_copy(
                    update={"mode": mode}
                ),
            }
        )
        with pytest.raises(ValueError, match="cannot go on"):
            sim.simulate(later, params)


def test_a_resume_of_another_version_is_refused() -> None:
    first = engine.simulate(**walk_case(1))
    assert first.resume is not None
    doc = first.resume.to_document()
    assert doc["version"] == RESUME_VERSION
    with pytest.raises(ValueError, match="resume version"):
        Resume.from_document({**doc, "version": RESUME_VERSION + 1})


def _settings_in(base: sim.Scenario, mode: int) -> sim.Scenario:
    return base.model_copy(
        update={"settings": base.settings.model_copy(update={"mode": mode})}
    )


def _api_chained(
    base: sim.Scenario,
    params: HeaterParams,
    cuts: list[datetime],
    **kw: Any,
) -> list[sim.SimulationResult]:
    """``base`` as one scenario per span between ``cuts``, each from the
    last's ``end_state``, ``end_history`` and ``end_settings``, through
    the scenario's document."""
    out: list[sim.SimulationResult] = []
    s = base
    for a, b in pairwise([base.start, *cuts, base.until]):
        part = s.model_copy(
            update={
                "start": a,
                "horizon": b - a,
                "loads": Loads(
                    draws=tuple(d for d in base.loads.draws if a <= d.at < b)
                ),
                "commands": base.commands.model_copy(
                    update={
                        "writes": tuple(
                            w for w in base.commands.writes if a <= w.at < b
                        )
                    }
                ),
            }
        )
        part, _ = codec.scenario_from_document(
            json.loads(json.dumps(codec.scenario_to_document(part)))
        )
        got = sim.simulate(part, params, **kw)
        out.append(got)
        s = s.model_copy(
            update={
                "state": got.end_state,
                "history": got.end_history,
                "settings": got.end_settings,
            }
        )
    return out


def _hourly(base: sim.Scenario) -> list[datetime]:
    return [
        base.start + timedelta(hours=h)
        for h in range(1, int(base.horizon / timedelta(hours=1)))
    ]


def _peak(opens: int, closes: int) -> Schedules:
    """TOU on, a peak from ``opens``:00 to ``closes``:00 UTC: across
    midnight when it closes earlier in the day than it opens."""

    def period(h0: int, m0: int, h1: int, m1: int, price: int) -> TouPeriod:
        return TouPeriod(
            season=0xFFF,
            week=0xFE,
            start_hour=h0,
            start_minute=m0,
            end_hour=h1,
            end_minute=m1,
            price_max=price,
        )

    if closes < opens:
        periods = (
            period(0, 0, closes - 1, 59, 5),
            period(closes, 0, opens - 1, 59, 1),
            period(opens, 0, 23, 59, 5),
        )
    else:
        periods = (
            period(0, 0, opens - 1, 59, 1),
            period(opens, 0, closes - 1, 59, 5),
            period(closes, 0, 23, 59, 1),
        )
    return Schedules(tou_enabled=True, tou_periods=periods)


@pytest.mark.parametrize("tou", [False, True], ids=["no-tou", "tou"])
@pytest.mark.parametrize("mode", [1, 2, 3, 4])
def test_scenarios_chained_by_their_end_state_are_one(
    mode: int, tou: bool
) -> None:
    """Two days of draws, one scenario an hour: the same heating and the
    same tank at the end as one scenario over the two days. With TOU, a
    recovery running at a call's end is capped by a window opening past
    it as one walk caps it."""
    base = _settings_in(days_of_draws(2), mode)
    if tou:
        base = base.model_copy(update={"schedules": _peak(14, 2)})
    params = sim.site_example_params()
    whole = sim.simulate(base, params)
    calls = _api_chained(base, params, _hourly(base))
    _, heating = _joined([c.simulation for c in calls])
    assert _same_heating(heating, whole.heating)
    end, ends = whole.points[-1], calls[-1].points[-1]
    assert (ends.upper_f, ends.lower_f) == (end.upper_f, end.lower_f)


def test_a_held_mode_lands_at_its_windows_close_when_resumed_there() -> None:
    """High Demand written inside a TOU window is held to its close, and
    a call that begins there lands it, though its windows begin past
    the close."""
    t0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
    base = days_of_draws(1).model_copy(
        update={
            "start": t0,
            "horizon": timedelta(hours=6),
            "state": sim.HeaterState(upper_f=110.0, lower_f=105.0),
            "settings": sim.Settings(
                setpoint_f=120.0, hp_lower_on_f=105.0, mode=3
            ),
            "schedules": _peak(11, 14),
            "commands": Commands(
                writes=(CommandWrite(at=t0 + timedelta(minutes=5), mode=4),)
            ),
            "loads": Loads(),
        }
    )
    params = sim.site_example_params()
    whole = sim.simulate(base, params)
    close = t0 + timedelta(hours=2)
    calls = _api_chained(base, params, [close])
    assert (close, "high_demand") in [(m.start, m.mode) for m in whole.modes]
    assert [(m.start, m.mode) for m in calls[1].modes] == [
        (close, "high_demand")
    ]
    assert calls[1].end_settings is not None
    assert calls[1].end_settings.mode == 4
    assert whole.end_settings is not None and whole.end_settings.mode == 4
    _, heating = _joined([c.simulation for c in calls])
    assert _same_heating(heating, whole.heating)


@pytest.mark.parametrize("mode", [5, 6])
def test_into_vacation_or_power_off_the_walk_starts_afresh(mode: int) -> None:
    """A recovery running at a call's end, the next call in Vacation or
    Power Off: a write the simulation holds no rule for, so it starts
    from the tank and the history, not the resume, and says so."""
    params = sim.site_example_params()
    base = days_of_draws(1).model_copy(
        update={
            "horizon": timedelta(hours=1),
            "state": sim.HeaterState(upper_f=110.0, lower_f=95.0),
            "settings": sim.Settings(setpoint_f=140.0, hp_lower_on_f=105.0),
            "loads": Loads(),
        }
    )
    first = sim.simulate(base, params)
    assert first.end_state is not None and first.end_settings is not None
    assert first.end_state.compressor_running
    off = first.end_settings.model_copy(update={"mode": mode})
    then = base.model_copy(
        update={
            "start": first.until,
            "state": first.end_state,
            "history": first.end_history,
            "settings": off,
        }
    )
    got = sim.simulate(then, params)
    assert RESUME_DROPPED in got.reasons
    fresh = then.model_copy(
        update={"state": first.end_state.model_copy(update={"resume": None})}
    )
    assert got.simulation.heating == sim.simulate(fresh, params).heating


def test_an_entry_that_turns_the_heater_on_leaves_power_off() -> None:
    """Powered off, an entry turns the heater on in Heat Pump: the call
    ends in Heat Pump, and the next goes on from there."""
    params = sim.site_example_params()
    t0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
    entry = ReservationEntry(
        week=0xFE, hour=20, minute=0, mode=1, setpoint_half_c=124
    )
    base = days_of_draws(1).model_copy(
        update={
            "start": t0,
            "horizon": timedelta(hours=4),
            "state": sim.HeaterState(upper_f=110.0, lower_f=95.0),
            "settings": sim.Settings(
                setpoint_f=140.9, mode=6, hp_lower_on_f=105.0
            ),
            "schedules": Schedules(reservations=(entry,)),
            "loads": Loads(),
        }
    )
    whole = sim.simulate(base, params)
    assert "powered_on_by_entry" in whole.reasons
    assert whole.end_settings is not None and whole.end_settings.mode == 1
    calls = _api_chained(base, params, _hourly(base))
    assert all(RESUME_DROPPED not in c.reasons for c in calls)
    _, heating = _joined([c.simulation for c in calls])
    assert _same_heating(heating, whole.heating)


def test_power_off_given_again_turns_the_heater_off() -> None:
    """Powered off, an entry turns the heater on; the next call given
    Power Off again is the heater turned off, not still on by the
    entry."""
    params = sim.site_example_params()
    t0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
    entry = ReservationEntry(
        week=0xFE, hour=20, minute=0, mode=1, setpoint_half_c=124
    )
    base = days_of_draws(1).model_copy(
        update={
            "start": t0,
            "horizon": timedelta(hours=2),
            "state": sim.HeaterState(upper_f=110.0, lower_f=95.0),
            "settings": sim.Settings(
                setpoint_f=140.9, mode=6, hp_lower_on_f=105.0
            ),
            "schedules": Schedules(reservations=(entry,)),
            "loads": Loads(),
        }
    )
    first = sim.simulate(base, params)
    assert first.end_settings is not None and first.end_settings.mode == 1
    off = first.end_settings.model_copy(update={"mode": 6})
    then = sim.simulate(
        base.model_copy(
            update={
                "start": first.until,
                "state": first.end_state,
                "history": first.end_history,
                "settings": off,
                "schedules": Schedules(),
            }
        ),
        params,
    )
    assert RESUME_DROPPED in then.reasons
    assert then.end_settings is not None and then.end_settings.mode == 6


class _Model:
    """A recovery model that says why on every recovery."""

    def duration(self, ctx: RecoveryContext) -> ModelDuration:
        return ModelDuration(
            minutes=ctx.physics.minutes * 1.2,
            start_hold_minutes=ctx.start_hold_minutes,
            confidence=0.9,
            reasons=("model_says_so",),
        )


def test_a_recovery_carried_on_keeps_what_its_pace_rests_on() -> None:
    """A recovery a model paces, running at a call's end: the next call,
    whose heating it carries on, keeps the model's reasons."""
    params = sim.site_example_params()
    base = days_of_draws(1).model_copy(
        update={
            "horizon": timedelta(hours=2),
            "state": sim.HeaterState(upper_f=110.0, lower_f=95.0),
            "settings": sim.Settings(setpoint_f=140.0, hp_lower_on_f=105.0),
            "loads": Loads(),
        }
    )
    calls = _api_chained(
        base, params, [base.start + timedelta(minutes=30)], recovery=_Model()
    )
    assert calls[0].end_state is not None
    assert calls[0].end_state.compressor_running
    assert "model_says_so" in calls[0].reasons
    assert "model_says_so" in calls[1].reasons


def test_an_element_carried_on_keeps_what_it_rests_on() -> None:
    """High Demand's upper element running at a call's end: the next
    call, whose heating it carries on, keeps the element model's
    reasons."""
    params = sim.site_example_params()
    base = days_of_draws(1).model_copy(
        update={
            "horizon": timedelta(hours=2),
            "state": sim.HeaterState(upper_f=100.0, lower_f=90.0),
            "settings": sim.Settings(
                setpoint_f=140.0, mode=4, hp_lower_on_f=105.0
            ),
            "loads": Loads(),
        }
    )
    calls = _api_chained(base, params, [base.start + timedelta(minutes=10)])
    assert calls[0].end_state is not None
    assert calls[0].end_state.element_running
    assert "element_model_small_n" in calls[1].reasons


def _then(
    first: sim.SimulationResult,
    base: sim.Scenario,
    settings: sim.Settings | None = None,
) -> sim.Scenario:
    """Two hours from where ``first`` ended, in ``settings`` (else the
    ones it left)."""
    return base.model_copy(
        update={
            "start": first.until,
            "horizon": timedelta(hours=2),
            "state": first.end_state,
            "history": first.end_history,
            "settings": settings or first.end_settings,
            "loads": Loads(),
        }
    )


@pytest.mark.parametrize(("asked", "written"), [(140.0, 140.0), (145.0, 145.4)])
def test_settings_given_otherwise_are_written_at_the_start(
    asked: float, written: float
) -> None:
    """A setpoint other than the one the last call left is a write at
    the next one's start, held as the device holds an app's (half
    degrees Celsius); the ones it left write nothing."""
    base = days_of_draws(1)
    params = sim.site_example_params()
    first = sim.simulate(
        base.model_copy(update={"horizon": timedelta(hours=2)}), params
    )
    assert first.end_settings is not None
    raised = first.end_settings.model_copy(update={"setpoint_f": asked})
    then = sim.simulate(_then(first, base, raised), params)
    (write,) = [w for w in then.writes if w.serves == "settings"]
    assert (write.at, write.setpoint_f) == (first.until, written)
    assert then.end_settings is not None
    assert then.end_settings.setpoint_f == written
    same = sim.simulate(_then(first, base), params)
    assert not [w for w in same.writes if w.serves == "settings"]


def test_a_mode_given_otherwise_is_written_at_the_start() -> None:
    base = days_of_draws(1)
    params = sim.site_example_params()
    first = sim.simulate(
        base.model_copy(update={"horizon": timedelta(hours=2)}), params
    )
    assert first.end_settings is not None
    then = sim.simulate(
        _then(first, base, first.end_settings.model_copy(update={"mode": 4})),
        params,
    )
    (write,) = [
        w for w in then.simulation.mode_writes if w.serves == "settings"
    ]
    assert (write.at, write.mode, write.took_at) == (
        first.until,
        "high_demand",
        first.until,
    )


def test_a_setpoint_given_out_of_range_is_refused() -> None:
    base = days_of_draws(1)
    params = sim.site_example_params()
    first = sim.simulate(
        base.model_copy(update={"horizon": timedelta(hours=2)}), params
    )
    assert first.end_settings is not None
    hot = first.end_settings.model_copy(update={"setpoint_f": 200.0})
    with pytest.raises(ValueError, match="outside the range"):
        sim.simulate(_then(first, base, hot), params)


def test_calls_across_midnight_keep_the_first_days_mains() -> None:
    """With no inlet given, the mains is the climate's on the walk's
    first day: a call after midnight that goes on from it keeps that
    day's, as the walk whole does."""
    base = days_of_draws(2)
    base = base.model_copy(
        update={"environment": sim.Environment(ambient_f=65.0)}
    )
    params = sim.site_example_params()
    assert params.draw.climate_f is not None
    whole = sim.simulate(base, params)
    calls = _api_chained(base, params, _hourly(base))
    _, heating = _joined([c.simulation for c in calls])
    assert _same_heating(heating, whole.heating)
    end, ends = whole.points[-1], calls[-1].points[-1]
    assert (ends.upper_f, ends.lower_f) == (end.upper_f, end.lower_f)


def test_the_result_document_carries_the_end_state() -> None:
    result = sim.simulate(days_of_draws(1), sim.site_example_params())
    doc = codec.result_to_document(result)
    assert result.end_state is not None and result.end_history is not None
    assert result.end_state.resume is not None
    assert doc["end_state"]["resume"] == result.end_state.resume
    stopped = result.end_history.compressor_stopped_at
    assert stopped is not None
    assert doc["end_history"]["compressor_stopped_at"] == (
        stopped.isoformat().replace("+00:00", "Z")
    )
    assert sim.HeaterState.model_validate(doc["end_state"]) == result.end_state
    # A state that carries a resume is a value like any other.
    assert hash(result.end_state) == hash(
        sim.HeaterState.model_validate(doc["end_state"])
    )


def _peak_afternoon(start: datetime, hours: float) -> sim.Scenario:
    """A recovery under way from 11:00, a peak 14:00 to 18:00."""
    return days_of_draws(1).model_copy(
        update={
            "start": start,
            "horizon": timedelta(hours=hours),
            "state": sim.HeaterState(upper_f=110.0, lower_f=95.0),
            "settings": sim.Settings(setpoint_f=140.0, hp_lower_on_f=105.0),
            "schedules": _peak(14, 18),
            "loads": Loads(),
        }
    )


def test_the_cap_is_said_in_the_call_it_stops_a_recovery_in() -> None:
    """A recovery the peak will cap: a walk that ends before it does not
    say the cap stopped it; of calls chained hourly, the one the cap
    stops it in says so."""
    params = sim.site_example_params()
    start = datetime(2026, 10, 4, 11, 0, tzinfo=UTC)
    short = sim.simulate(_peak_afternoon(start, 1.0), params)
    assert not any(h.capped for h in short.heating)
    assert TOU_CAP_PROJECTED not in short.reasons
    base = _peak_afternoon(start, 5.0)
    whole = sim.simulate(base, params)
    assert any(h.stop == "cap" for h in whole.heating)
    assert TOU_CAP_PROJECTED in whole.reasons
    calls = _api_chained(base, params, _hourly(base))
    said = [TOU_CAP_PROJECTED in c.reasons for c in calls]
    capped = [any(h.stop == "cap" for h in c.heating) for c in calls]
    assert said == capped and any(capped)


def test_a_held_heat_pump_entry_landing_later_says_its_rule() -> None:
    """A Heat Pump entry held in a window, landing in a later call:
    that call says the hold rests on the documented rule alone."""
    params = sim.site_example_params()
    t0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
    entry = ReservationEntry(
        week=0xFE, hour=12, minute=5, mode=1, setpoint_half_c=110
    )
    base = days_of_draws(1).model_copy(
        update={
            "start": t0,
            "horizon": timedelta(hours=4),
            "state": sim.HeaterState(upper_f=110.0, lower_f=105.0),
            "settings": sim.Settings(
                setpoint_f=120.0, hp_lower_on_f=105.0, mode=3
            ),
            "schedules": _peak(11, 14).model_copy(
                update={"reservations": (entry,)}
            ),
            "loads": Loads(),
        }
    )
    whole = sim.simulate(base, params)
    assert "heat_pump_entry_held_spec_only" in whole.reasons
    calls = _api_chained(base, params, [t0 + timedelta(hours=1)])
    assert "heat_pump_entry_held_spec_only" in calls[1].reasons


def test_a_dropped_resume_is_a_fresh_start() -> None:
    """Into Vacation, the call is the one made without the resume: the
    same defaults named, the same answer."""
    params = sim.site_example_params()
    base = days_of_draws(1).model_copy(
        update={
            "horizon": timedelta(hours=1),
            "state": sim.HeaterState(upper_f=110.0, lower_f=95.0),
            "settings": sim.Settings(setpoint_f=140.0, hp_lower_on_f=105.0),
            "loads": Loads(),
        }
    )
    first = sim.simulate(base, params)
    assert first.end_state is not None and first.end_settings is not None
    then = base.model_copy(
        update={
            "start": first.until,
            "state": first.end_state,
            "history": History(),
            "settings": first.end_settings.model_copy(
                update={"mode": 5, "setpoint_f": 133.3}
            ),
        }
    )
    got = sim.simulate(then, params)
    fresh = sim.simulate(
        then.model_copy(
            update={
                "state": first.end_state.model_copy(update={"resume": None})
            }
        ),
        params,
    )
    assert got.reasons == (RESUME_DROPPED, *fresh.reasons)
    assert got.defaults_used == fresh.defaults_used
    assert got.simulation == fresh.simulation
