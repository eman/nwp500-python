"""How near a walk came to the heat pump's own start triggers.

A walk calls a start where its probe crosses a trigger, and misses one
it passes by a fraction of a degree, with the same confidence; its
probes after a day of draws can be several degrees off
(``docs/explanation/simulator.rst``, "Accuracy"). ``start_margins``
says, for each stretch the walk coasts, how near it came to each
trigger, so a caller can weigh a start it did not call by how nearly
it called it.

On the site's 29 held-out days (day starts 2026-09-18 to 10-25,
measured 2026-11-03 on the parameters in use, the draws as metered),
the walk placed all but 11 of the record's compressor starts within
30 minutes; 3 of the 11 fell on coasts the walk did not start, the
rest on coasts it started at another time. By trigger: inside the
windows 2 of 23 such coasts, on 10-18 at the smallest upper margin,
1.8 °F, and 10-24 at the fourth, 7.8; for the lower trigger 1 of 24,
10-20 at the second smallest, 7.0. A coast's lower margin is mostly
read at its end (23 of the 24 at the walk's end), where the walk stops
rather than where the record started. Three misses rank the margin; they
do not fix a threshold.

The triggers are the heat pump's (``tou_triggers.heater_start``):
the lower zone falling to its trigger (``hp_lower_on``, no nearer the
setpoint than the setpoint itself, ``controller.lower_trigger_f``),
held in the modes that hold it while the upper zone is at or above the
setpoint, and in Energy Saver released by a draw's drop; inside a TOU
window it waits for the close, so a crossing there starts the heater
at the close. And inside a window, the upper zone more than
``UPPER_DEFICIT_F`` below the setpoint. The points are the walk's: a
draw's drop between two of them is read where the next one stands, so
a drop the walk never took to a start reads at the next point. The
elements' own triggers (``ELECTRIC``, or the heat pump outside its
range, which the points do not mark) are not read, nor any point with
heating disabled (Vacation, or powered off).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from nwp500.sim.controller import COMPRESSOR_MODES
from nwp500.sim.engine import PathPoint
from nwp500.sim.inputs import Draw
from nwp500.sim.tou_triggers import (
    DROP_STARTS_MODE,
    LOWER_HOLD_MODES,
    UPPER_DEFICIT_F,
    in_window,
)

#: The trigger a margin is read against.
MarginTrigger = Literal["lower", "upper_at_tou_open"]


@dataclass(frozen=True)
class StartMargin:
    """A coast's nearest approach to one trigger."""

    #: The coast: its first and last points not heating.
    start: datetime
    end: datetime
    trigger: MarginTrigger
    #: Where it came nearest, and how far its probe stood above the
    #: trigger there, °F: 0 or less where it reached it. A coast its
    #: own trigger ended stands at or under 0: near it at a crossing
    #: (to the path's step), under it where a draw's drop or a window's
    #: opening took the probe past.
    at: datetime
    margin_f: float
    #: The coast ended in a start of any cause (the next point heats:
    #: a trigger, or a write), not at the walk's end.
    started: bool


def _coasts(points: Sequence[PathPoint]) -> Iterable[tuple[int, int, int]]:
    """The runs of points not heating, ``[i, j)``, and the end of what
    is read of each, ``k``: past ``j`` by the state just after a draw
    at a start's instant (the engine writes it at the last point's
    instant, heating, ``_step_point``), which is what reached the
    trigger."""
    i = 0
    n = len(points)
    while i < n:
        if points[i].heating:
            i += 1
            continue
        j = i
        while j < n and not points[j].heating:
            j += 1
        k = j + 1 if j < n and points[j].at == points[j - 1].at else j
        yield i, j, k
        i = j


def _mode(point: PathPoint) -> str:
    return str(point.mode)


def _released(
    prev: PathPoint | None, p: PathPoint, onsets: Sequence[datetime]
) -> bool:
    """A draw's drop reached ``p`` (its onset in ``(prev, p]``), which in
    Energy Saver releases the held lower trigger."""
    if _mode(p) != DROP_STARTS_MODE:
        return False
    lo = prev.at if prev is not None else p.at
    return any(lo < t <= p.at or t == p.at for t in onsets)


def _lower_margin(
    prev: PathPoint | None,
    p: PathPoint,
    hp_lower_on_f: float | None,
    onsets: Sequence[datetime],
) -> float | None:
    if hp_lower_on_f is None:
        return None
    held = _mode(p) in LOWER_HOLD_MODES and p.upper_f >= p.setpoint_f
    if held and not _released(prev, p, onsets):
        return None
    return p.lower_f - min(hp_lower_on_f, p.setpoint_f)


def _upper_margin(p: PathPoint) -> float:
    return p.upper_f - (p.setpoint_f - UPPER_DEFICIT_F)


def start_margins(
    points: Sequence[PathPoint],
    hp_lower_on_f: float | None,
    tou_windows: Sequence[tuple[datetime, datetime]] = (),
    draws: Iterable[Draw] = (),
) -> tuple[StartMargin, ...]:
    """Each coast of ``points`` (``SimulationResult.points``) and its
    nearest approach to each heat-pump trigger it was in force for, in
    order: the lower one, and inside ``tou_windows`` (the windows the
    walk was given, ``simulate(tou_windows_in_force=...)``) the upper
    one. ``draws`` are the walk's (``Scenario.loads.draws``): in Energy
    Saver a draw's drop releases the held lower trigger. A point in a
    mode without the compressor, or with heating disabled, counts for
    neither."""
    onsets = sorted(d.at for d in draws)
    out: list[StartMargin] = []
    for i, j, k in _coasts(points):
        best: dict[MarginTrigger, tuple[float, datetime]] = {}
        for n in range(i, k):
            p = points[n]
            if p.heating_disabled or _mode(p) not in COMPRESSOR_MODES:
                continue
            prev = points[n - 1] if n > 0 else None
            found: list[tuple[MarginTrigger, float | None]] = [
                ("lower", _lower_margin(prev, p, hp_lower_on_f, onsets))
            ]
            if in_window(p.at, tou_windows):
                found.append(("upper_at_tou_open", _upper_margin(p)))
            for trigger, margin in found:
                if margin is None:
                    continue
                if trigger not in best or margin < best[trigger][0]:
                    best[trigger] = (margin, p.at)
        for trigger in ("lower", "upper_at_tou_open"):
            if trigger in best:
                margin, at = best[trigger]
                out.append(
                    StartMargin(
                        start=points[i].at,
                        end=points[j - 1].at,
                        trigger=trigger,
                        at=at,
                        margin_f=margin,
                        started=j < len(points),
                    )
                )
    return tuple(out)
