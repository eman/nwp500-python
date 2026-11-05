"""How near a walk came to the heat pump's own start triggers.

A walk calls a start where its probe crosses a trigger, and misses one
it passes by a fraction of a degree, with the same confidence; its
probes after a day of draws can be several degrees off
(``docs/explanation/simulator.rst``, "Accuracy"). ``start_margins``
says, for each stretch the walk coasts, how near it came to each
trigger, so a caller can weigh a start it did not call by how nearly it
called it.

On the site's 29 held-out days (day starts 2026-09-18 to 10-25, measured
2026-11-03 on the parameters in use, the draws as metered), the walk
placed all but 11 of the record's compressor starts within 30 minutes; 3
of the 11 fell on coasts the walk did not start, 5 on coasts it started
at another time, and 3 while it was heating. By trigger: inside the
windows 2 of 23 such coasts, on 10-18 at the smallest upper margin, 1.8
°F, and 10-24 at the fourth, 7.8; for the lower trigger 1 of 24, 10-20
at the second smallest, 7.0. A coast's lower margin is mostly read at
its end (23 of the 24 at the walk's end), where the walk stops rather
than where the record started. Three misses rank the margin; they do not
fix a threshold.

A lower margin read within the hour after a large draw is the least
sure. On the 28 clean compressor-off draws of 8 gal or more held out
from 2026-09-18 (measured 2026-11-04 at ``DrawParams.meter_reads``
0.85), the walk's lower probe fell at once, a median 12.8 °F under the
record's a minute after, which took about ten minutes more to come half
way; an hour after it was right on median, but 3.4 to 16.5 °F off,
either way, on the 9 it missed by 3 °F or more
(``docs/explanation/simulator.rst``, "Accuracy"). Each margin carries
the gallons drawn in the hour up to where it was read (``drawn_gal``)
and whether they came to 8 or more (``after_large_draw``): the hour's
draws summed, where those figures are of one draw each.

The triggers are the heat pump's (``tou_triggers.heater_start``): the
lower zone falling to its trigger (``hp_lower_on``, no nearer the
setpoint than the setpoint itself, ``controller.lower_trigger_f``), held
in the modes that hold it while the upper zone is at or above the
setpoint, and in Energy Saver released by a drop (a draw's, or the
circulation's); inside a TOU window it waits for the close, so a
crossing there starts the heater at the close. And inside a window, the
upper zone more than ``UPPER_DEFICIT_F`` below the setpoint. The points
are the walk's: a draw's drop between two of them is read where the next
one stands, so a drop the walk never took to a start reads at the next
point. The elements' own triggers (``ELECTRIC``, or the heat pump
outside its range, which the points do not mark) are not read, nor any
point with heating disabled (Vacation, or powered off).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from nwp500.sim.circulation import RUN_GAP, Circulation
from nwp500.sim.controller import COMPRESSOR_MODES
from nwp500.sim.engine import PathPoint
from nwp500.sim.inputs import Loads
from nwp500.sim.params import HeaterParams
from nwp500.sim.tou_triggers import (
    DROP_STARTS_MODE,
    LOWER_HOLD_MODES,
    UPPER_DEFICIT_F,
    in_window,
)

#: How far back from a margin's point the draws counted in its
#: ``drawn_gal`` reach, inclusive: the hour the lower probe's error
#: after a large draw was measured over.
DRAWN_SPAN = timedelta(hours=1)

#: The metered gallons in ``DRAWN_SPAN`` from which a margin is read
#: after a large draw (``StartMargin.after_large_draw``): the draws the
#: lower probe's error after one was measured on.
LARGE_DRAW_GAL = 8.0

#: A span a drop can come in: a draw's piece (an instant) or a
#: circulation run.
_Span = tuple[datetime, datetime]

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
    #: The gallons drawn in the ``DRAWN_SPAN`` up to ``at``, as the
    #: loads give them (the meter's), each draw by the pieces the walk
    #: takes it in; None without the loads.
    drawn_gal: float | None = None

    @property
    def after_large_draw(self) -> bool:
        """Read within ``DRAWN_SPAN`` after ``LARGE_DRAW_GAL`` or more
        drawn: for the lower trigger, the walk's lower probe there is
        the least sure (the module's account)."""
        return self.drawn_gal is not None and self.drawn_gal >= LARGE_DRAW_GAL


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
    prev: PathPoint | None, p: PathPoint, drops: Sequence[_Span]
) -> bool:
    """A drop reached ``p``, which in Energy Saver releases the held
    lower trigger (``tou_triggers.heater_start``, ``drop_starts``): the
    lower zone fell from ``prev`` to ``p`` over a step a draw's piece
    (``Draw.pieces``) or a circulation run fell in, as the engine reads
    a drop (``TankPhysics``: a draw's, or a step the circulation took
    heat over with the lower probe falling)."""
    if _mode(p) != DROP_STARTS_MODE or prev is None:
        return False
    if p.lower_f >= prev.lower_f:
        return False
    # A drop at ``p``'s own instant counts: the state just after a
    # draw is written at the draw's instant, after the one before it.
    return any(a <= p.at and (b > prev.at or a == p.at) for a, b in drops)


def _lower_margin(
    prev: PathPoint | None,
    p: PathPoint,
    hp_lower_on_f: float | None,
    drops: Sequence[_Span],
) -> float | None:
    if hp_lower_on_f is None:
        return None
    held = _mode(p) in LOWER_HOLD_MODES and p.upper_f >= p.setpoint_f
    if held and not _released(prev, p, drops):
        return None
    return p.lower_f - min(hp_lower_on_f, p.setpoint_f)


def _upper_margin(p: PathPoint) -> float:
    return p.upper_f - (p.setpoint_f - UPPER_DEFICIT_F)


def _drawn(
    pieces: Sequence[tuple[datetime, float]] | None, at: datetime
) -> float | None:
    """The gallons of ``pieces`` in the ``DRAWN_SPAN`` up to ``at``,
    both ends included: a piece is stamped at the start of the water it
    draws, and one at ``at`` itself is read there."""
    if pieces is None:
        return None
    return sum(g for t, g in pieces if at - DRAWN_SPAN <= t <= at)


def start_margins(
    points: Sequence[PathPoint],
    hp_lower_on_f: float | None,
    tou_windows: Sequence[tuple[datetime, datetime]] = (),
    loads: Loads | None = None,
    params: HeaterParams | None = None,
    *,
    until: datetime | None = None,
) -> tuple[StartMargin, ...]:
    """Each coast of ``points`` (``SimulationResult.points``) and its
    nearest approach to each heat-pump trigger it was in force for, in
    order: the lower one, and inside ``tou_windows`` (the windows the
    walk was given, ``simulate(tou_windows_in_force=...)``) the upper
    one. ``loads`` are the walk's (``Scenario.loads``): in Energy Saver
    a drop, a draw's or the circulation's, releases the held lower
    trigger; ``params`` the walk's, for the gap its circulation runs are
    merged within (``CirculationParams.run_gap_min``; without them, the
    default gap), and each margin the gallons the draws put in the hour
    up to it (``StartMargin.drawn_gal``), from the walk's first point on,
    as the engine takes them, and before ``until`` where it is given
    (the walk's end, which the engine takes no draw at). A point in a
    mode without the
    compressor, or with heating disabled, counts for neither."""
    drops: list[_Span] = []
    pieces: list[tuple[datetime, float]] | None = None
    if loads is not None:
        # A draw over several minutes lands at each of its pieces; those
        # before the walk's first point it never took.
        first = points[0].at if points else None
        pieces = [
            p
            for d in loads.draws
            for p in d.pieces()
            if (first is None or p[0] >= first)
            and (until is None or p[0] < until)
        ]
        drops += [(t, t) for t, _ in pieces]
        if loads.circulation is not None:
            # The runs as the walk takes them: merged within the
            # circulation's gap, those after ``circulation_known_until``
            # left out (``api._circulation``).
            gap = (
                RUN_GAP
                if params is None or params.circulation is None
                else timedelta(minutes=params.circulation.run_gap_min)
            )
            drops += Circulation(
                tuple((r.start, r.end) for r in loads.circulation),
                loads.circulation_known_until,
                gap,
            ).runs
    out: list[StartMargin] = []
    for i, j, k in _coasts(points):
        best: dict[MarginTrigger, tuple[float, datetime]] = {}
        for n in range(i, k):
            p = points[n]
            if p.heating_disabled or _mode(p) not in COMPRESSOR_MODES:
                continue
            prev = points[n - 1] if n > 0 else None
            found: list[tuple[MarginTrigger, float | None]] = [
                ("lower", _lower_margin(prev, p, hp_lower_on_f, drops))
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
                        drawn_gal=_drawn(pieces, at),
                    )
                )
    return tuple(out)
