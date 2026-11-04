"""How near a walk came to the heat pump's own start triggers.

A walk calls a start where its probe crosses a trigger, and misses one
it passes by a fraction of a degree, with the same confidence; its
probes after a day of draws can be several degrees off
(``docs/explanation/simulator.rst``, "Accuracy"). ``start_margins``
says, for each stretch the walk coasts, how near it came to each
trigger, so a caller can weigh a start it did not call by how nearly
it called it.

On the site's 29 held-out days (2026-09-18 to 10-25, measured
2026-11-03 on the parameters in use), the walk coasted without a start
24 times outside the TOU windows; the three of those the record started
in and the walk did not place came at lower margins of 7.0, 8.2 and
9.0 °F, among the five smallest (5.6-9.0); none of the 19 over 9.0 °F
did. That ranks the margin; it does not fix a threshold, which these
days would fit on what they score.

The triggers are the heat pump's (``tou_triggers``): outside a TOU
window, the lower zone falling to ``hp_lower_on`` (held, in the modes
that hold it, while the upper zone is at or above the setpoint);
inside one, the upper zone more than ``UPPER_DEFICIT_F`` below the
setpoint. At the window's close the lower trigger reads again, so the
first point at or after the close counts for it. The elements' own
triggers (``ELECTRIC``) are not read here.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from nwp500.sim.controller import COMPRESSOR_MODES
from nwp500.sim.engine import PathPoint
from nwp500.sim.tou_triggers import (
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
    #: own trigger ended stands near 0 (the crossing, to the path's
    #: step), or below it where a window's opening or close found the
    #: probe already past.
    at: datetime
    margin_f: float
    #: The coast ended in a start of any cause (the next point heats:
    #: a trigger, or a write), not at the walk's end.
    started: bool


def _coasts(points: Sequence[PathPoint]) -> Iterable[tuple[int, int]]:
    """The runs of points not heating, ``[i, j)``."""
    i = 0
    n = len(points)
    while i < n:
        if points[i].heating:
            i += 1
            continue
        j = i
        while j < n and not points[j].heating:
            j += 1
        yield i, j
        i = j


def _mode(point: PathPoint) -> str:
    return str(point.mode)


def _lower_margin(p: PathPoint, hp_lower_on_f: float | None) -> float | None:
    if hp_lower_on_f is None:
        return None
    if _mode(p) in LOWER_HOLD_MODES and p.upper_f >= p.setpoint_f:
        return None
    return p.lower_f - hp_lower_on_f


def _upper_margin(p: PathPoint) -> float:
    return p.upper_f - (p.setpoint_f - UPPER_DEFICIT_F)


def start_margins(
    points: Sequence[PathPoint],
    hp_lower_on_f: float | None,
    tou_windows: Sequence[tuple[datetime, datetime]] = (),
) -> tuple[StartMargin, ...]:
    """Each coast of ``points`` (``SimulationResult.points``) and its
    nearest approach to each heat-pump trigger it was in force for, in
    order: the lower one outside ``tou_windows`` (the windows the walk
    was given, ``simulate(tou_windows_in_force=...)``), the upper one
    inside them. A point in ``ELECTRIC``, or a mode with no compressor,
    counts for neither."""
    out: list[StartMargin] = []
    for i, j in _coasts(points):
        best: dict[MarginTrigger, tuple[float, datetime]] = {}
        for p in points[i:j]:
            if _mode(p) not in COMPRESSOR_MODES:
                continue
            if in_window(p.at, tou_windows):
                got: tuple[MarginTrigger, float | None] = (
                    "upper_at_tou_open",
                    _upper_margin(p),
                )
            else:
                got = ("lower", _lower_margin(p, hp_lower_on_f))
            trigger, margin = got
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
