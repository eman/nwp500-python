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
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from sim_cases import days_of_draws, walk_case

from nwp500 import sim
from nwp500.sim import Loads, codec, engine
from nwp500.sim.engine import RESUME_VERSION, Resume, Write

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


@pytest.mark.parametrize("mode", [1, 2, 3, 4])
def test_scenarios_chained_by_their_end_state_are_one(mode: int) -> None:
    """Two days of draws, one scenario an hour, each from the last's
    ``end_state``, ``end_history`` and ``end_settings`` through its
    document: the same heating and the same tank at the end as one
    scenario over the two days."""
    base = _settings_in(days_of_draws(2), mode)
    params = sim.site_example_params()
    whole = sim.simulate(base, params)
    step = timedelta(hours=1)
    s, t = base, base.start
    calls: list[engine.Simulation] = []
    last: sim.SimulationResult | None = None
    while t < base.until:
        part = s.model_copy(
            update={
                "start": t,
                "horizon": step,
                "loads": Loads(
                    draws=tuple(
                        d for d in base.loads.draws if t <= d.at < t + step
                    )
                ),
            }
        )
        part, _ = codec.scenario_from_document(
            json.loads(json.dumps(codec.scenario_to_document(part)))
        )
        last = sim.simulate(part, params)
        calls.append(last.simulation)
        s = s.model_copy(
            update={
                "state": last.end_state,
                "history": last.end_history,
                "settings": last.end_settings,
            }
        )
        t += step
    assert last is not None
    _, heating = _joined(calls)
    assert _same_heating(heating, whole.heating)
    end, ends = whole.points[-1], last.points[-1]
    assert (ends.upper_f, ends.lower_f) == (end.upper_f, end.lower_f)


def test_settings_given_otherwise_are_written_at_the_start() -> None:
    """A setpoint other than the one the last call left is a write at
    the next one's start, as an app would make it between the two."""
    base = days_of_draws(1)
    params = sim.site_example_params()
    first = sim.simulate(
        base.model_copy(update={"horizon": timedelta(hours=2)}), params
    )
    assert first.end_settings is not None
    raised = first.end_settings.model_copy(update={"setpoint_f": 140.0})
    then = sim.simulate(
        base.model_copy(
            update={
                "start": first.until,
                "horizon": timedelta(hours=2),
                "state": first.end_state,
                "history": first.end_history,
                "settings": raised,
                "loads": Loads(),
            }
        ),
        params,
    )
    (write,) = [w for w in then.writes if w.serves == "settings"]
    assert (write.at, write.setpoint_f) == (first.until, 140.0)
    assert then.end_settings == raised
    same = sim.simulate(
        base.model_copy(
            update={
                "start": first.until,
                "horizon": timedelta(hours=2),
                "state": first.end_state,
                "history": first.end_history,
                "settings": first.end_settings,
                "loads": Loads(),
            }
        ),
        params,
    )
    assert not [w for w in same.writes if w.serves == "settings"]


def test_the_result_document_carries_the_end_state() -> None:
    result = sim.simulate(days_of_draws(1), sim.site_example_params())
    doc = codec.result_to_document(result)
    assert result.end_state is not None
    assert doc["end_state"]["resume"] == result.end_state.resume
    assert doc["end_history"] == (
        None
        if result.end_history is None
        else result.end_history.model_dump(mode="json")
    )
    assert sim.HeaterState.model_validate(doc["end_state"]) == result.end_state
