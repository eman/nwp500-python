"""When the heater starts itself, under its TOU windows.

Measured on every heat-pump start from 2026-04-08 to 2026-09-22 (1-minute
grid; starts under 30 min apart merged), the heater starts on its own in
three ways, and the TOU window decides which applies:

- **Outside the window**, when the lower tank falls to ``hp_lower_on``
  (104.9 °F), the trigger a projection always modelled. It also
  requires the upper tank below the setpoint, waiting while it is at or
  above it (``heater_start``; a device test, 2026-10-03).
- **Inside the window**, when the upper tank is more than
  ``UPPER_DEFICIT_F`` below the setpoint: at the opening, or later as it
  cools or a draw takes it there. The trigger keeps its name,
  ``upper_at_tou_open``, from when it was tested at the opening alone.
- **At the window's close**, when the lower tank crossed ``hp_lower_on``
  inside it. The lower trigger waits out the window: 9 of 9 closes with
  the lower tank below it started at once. Of 19 in-window crossings
  with the compressor off (raw rows, 2026-04-08 to 10-01), none started
  on the lower trigger before the close; the six that started early
  were the upper trigger (04-13, 07-28), mode writes ending a vacation
  (08-11, 08-12) and device tests (09-29, 09-30).

Nothing else starts it inside the window. Setpoint writes also start
it, but those are commands, not something a projection can foresee.

These are the firmware's own triggers, so they are the simulator
core's (``sim/controller.py`` applies them). The windows themselves,
the device's schedule and the span learned from ``hp_upper_on``'s
history, are read by the caller and come here as instants.
"""

import itertools
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from nwp500.sim.decay import Impulse, threshold_crossing

#: A TOU window: its opening and its close (exclusive), aware instants.
Window = tuple[datetime, datetime]

Trigger = Literal["lower", "upper_at_tou_open", "lower_at_tou_close"]

#: Inside the window, with the compressor off, the heater starts when the
#: upper tank is more than this far below the setpoint: at the opening,
#: or at any instant after it before the close. 8 °C.
#:
#: Measured on 89 window-days, 2026-06-01 to 10-01, raw rows. At the
#: opening, 17 of 17 openings 15.48 °F or more short started 25-34 s
#: later and none of 38 at 11.88 °F or less did. Mid-window the upper
#: tank reached 13.86 and 14.22 °F short without a start, and on
#: 2026-07-28 the heater started 33 s after the probe read 14.76 short,
#: the openings' own lag. One threshold for both lies in (14.22, 15.48];
#: on that timing in (14.22, 14.76], where 8 °C is. The held-out fit is
#: 14.85, which scores the same on these days (18/18 precision and
#: recall) but sits above the 07-28 timing. The rule was first
#: tested only at the opening, at 13.7 °F, the midpoint of the openings'
#: gap; that missed 07-28 and would fire on 06-14 and 07-31.
UPPER_DEFICIT_F = 14.4

#: The tank probes' reporting step, °F (0.1 °C).
PROBE_STEP_F = 0.18

#: The smallest step: a projection's last instant, included in a search
#: whose end is exclusive.
_INSTANT = timedelta(microseconds=1)


def while_enabled(
    windows: Iterable[tuple[datetime, datetime]],
    enabled_at_start: bool,
    switches: Iterable[tuple[datetime, bool]],
) -> list[tuple[datetime, datetime]]:
    """``windows`` less the spans the TOU switch was off.

    ``switches`` are the switch's recorded changes, ``(at, on)``. A
    window is in force only while TOU is on: switching it off ends one
    (the heater drops ``hp_upper_on`` to rest at once), and switching it
    back on inside the schedule's span begins one again. With no switch
    the windows are returned as they are, one already open at the start
    included."""
    spans: list[tuple[datetime, datetime]] = []
    since: datetime | None = (
        datetime.min.replace(tzinfo=UTC) if enabled_at_start else None
    )
    for at, on in sorted(switches):
        if on and since is None:
            since = at
        elif not on and since is not None:
            spans.append((since, at))
            since = None
    if since is not None:
        spans.append((since, datetime.max.replace(tzinfo=UTC)))
    out = [
        (max(a, s), min(b, e))
        for a, b in windows
        for s, e in spans
        if max(a, s) < min(b, e)
    ]
    return sorted(out)


def _upper_at(
    trajectory: Sequence[tuple[datetime, float, float]],
    at: datetime,
    impulses: Sequence[Impulse],
) -> float | None:
    """The upper tank at ``at``: the last trajectory point at or before
    it, or the next one if a draw lands between them. Not interpolated:
    a draw after ``at`` must not reach back before it, and one before
    ``at`` must count."""
    for (t0, u0, _), (t1, u1, _) in itertools.pairwise(trajectory):
        if t0 <= at <= t1:
            if at == t1:
                return u1
            drawn = any(t0 < i.at <= at for i in impulses)
            return u1 if drawn else u0
    if trajectory and at == trajectory[0][0]:
        return trajectory[0][1]
    return None


def _upper_crossing(
    trajectory: Sequence[tuple[datetime, float, float]],
    line: float,
    impulses: Sequence[Impulse],
    start: datetime,
    end: datetime,
    *,
    already_past_by: float = 0.0,
) -> datetime | None:
    """The first instant in ``[start, end)`` the upper tank is below
    ``line``.

    At ``start`` it is ``_upper_at``'s reading, which must be more than
    ``already_past_by`` below the line to start there; one past the line
    by less is held to a coast that reaches ``line - already_past_by``.
    After ``start``, a coast step's crossing is linearly interpolated.
    In a step with a draw it is at the step's first draw at or after
    ``start``. ``_upper_at`` holds the tank at the step's first value
    until a draw, so the crossing is never before that draw. The
    trajectory does not say which of several draws took it across, so
    with more than one the instant can be early by at most the step."""
    first = _upper_at(trajectory, start, impulses)
    if first is not None and first < line - already_past_by:
        return start
    if first is not None and first < line:
        line -= already_past_by
    for (t0, u0, _), (t1, u1, _) in itertools.pairwise(trajectory):
        if t1 <= start or t0 >= end or u1 >= line:
            continue
        drawn = [i.at for i in impulses if t0 < i.at <= t1 and i.at >= start]
        if drawn:
            at = min(drawn)
        elif u0 > u1:
            at = t0 + (t1 - t0) * ((u0 - line) / (u0 - u1))
        else:
            at = t1
        at = max(at, start)
        return at if at < end else None
    return None


def autonomous_start(
    trajectory: Sequence[tuple[datetime, float, float]],
    hp_lower_on: float,
    impulses: Iterable[Impulse] | None = None,
    *,
    windows: Sequence[tuple[datetime, datetime]] = (),
    setpoint_f: float | None = None,
    lower_waits_for_upper_short: bool = False,
) -> tuple[datetime | None, Trigger | None]:
    """The first instant the heater would start itself, and why.

    The lower crossing is ``threshold_crossing``'s; one inside a window
    waits for its close, and is dropped if the close lies beyond the
    projection. Inside each window, from its opening or the projection's
    start if later, the heater starts at the first instant the upper
    tank is more than ``UPPER_DEFICIT_F`` below ``setpoint_f``
    (``upper_at_tou_open``; the trajectory is a coast, so the compressor
    is off). A projection that begins inside a window already past that
    line starts at once only ``PROBE_STEP_F`` past it. The earliest
    wins. Without windows this is the lower
    crossing alone.

    With ``lower_waits_for_upper_short`` (``heater_start``'s, from a
    device test on 2026-10-03), the lower crossing counts only once the
    upper tank is also below ``setpoint_f``: with
    the upper tank at or above it, the lower trigger waits for it to
    fall below, and is dropped if it does not within the projection.
    Outside a window, 104 of 104 crossings in ``HEAT_PUMP`` that reached
    two probe steps under ``hp_lower_on`` started within 30 s, every one
    with the upper tank 1.26-23.04 °F short of the setpoint; the one
    with the upper tank above it, the test's hold-off (+14.04 °F at
    120.2 °F, 2026-10-03), fell to 99.5 °F and started nothing in the
    15 min before its closing entry (measured to 2026-10-03 21:30 UTC).
    That the start then follows the upper tank's fall below the setpoint
    is *assumed*: nothing has measured the release.
    """
    if not trajectory:
        return None, None
    drops = list(impulses or ())
    begin, end = trajectory[0][0], trajectory[-1][0]
    found: list[tuple[datetime, Trigger]] = []
    lower_at = threshold_crossing(list(trajectory), hp_lower_on, drops)
    if (
        lower_at is not None
        and lower_waits_for_upper_short
        and setpoint_f is not None
        and math.isfinite(setpoint_f)
    ):
        # In a coast the lower tank only falls, so it is still under
        # the setting when the upper tank falls below the setpoint.
        lower_at = _upper_crossing(
            trajectory, setpoint_f, drops, lower_at, end + _INSTANT
        )
    if lower_at is not None:
        inside = next((w for w in windows if w[0] <= lower_at < w[1]), None)
        if inside is None:
            found.append((lower_at, "lower"))
        elif inside[1] <= end:
            found.append((inside[1], "lower_at_tou_close"))
    if setpoint_f is not None and math.isfinite(setpoint_f):
        line = setpoint_f - UPPER_DEFICIT_F
        for opens, closes in sorted(windows):
            lo = max(opens, begin)
            if lo > end or closes <= lo:
                continue
            # A projection that begins inside a window, already past the
            # line, starts at once only a probe step past it: the heater
            # starts ~30 s after a crossing, so one barely past
            # the line now is not one it has already acted on.
            at = _upper_crossing(
                trajectory,
                line,
                drops,
                lo,
                closes,
                already_past_by=PROBE_STEP_F if lo > opens else 0.0,
            )
            if at is not None:
                found.append((at, "upper_at_tou_open"))
                break
    if not found:
        return None, None
    return min(found, key=lambda f: f[0])


#: The reason a projection carries when the lower trigger's hold (the
#: upper tank at or above the setpoint) moved or dropped a start: it
#: rests on one device run (2026-10-03).
LOWER_TRIGGER_HELD = "lower_trigger_held_uncertain"


#: The one mode the hold rests on: ``heat_pump`` (the heater profile's
#: default mode). The 104 crossings and the device test
#: were all in it. Energy Saver is not held: on 2026-09-21 it started
#: with the upper tank about 9 °F above a 107.6 °F setpoint.
LOWER_HOLD_MODE = "heat_pump"


def heater_start(
    trajectory: Sequence[tuple[datetime, float, float]],
    hp_lower_on: float,
    impulses: Iterable[Impulse] | None = None,
    *,
    windows: Sequence[tuple[datetime, datetime]] = (),
    setpoint_f: float | None = None,
    mode: str | None = None,
) -> tuple[datetime | None, Trigger | None, bool]:
    """When the heater would start itself, as both a standby forecast
    and a simulation project it: the ``autonomous_start`` rules, with
    the lower trigger held while the upper tank is at or above
    ``setpoint_f`` (``lower_waits_for_upper_short``) in
    ``LOWER_HOLD_MODE`` only.
    ``mode`` is the mode in force; None, a mode
    that could not be read, is taken as normal operation, the default
    ``heat_pump``, as every reader of the mode does. The third value
    says whether the hold moved or dropped the start, which is when a
    projection carries ``LOWER_TRIGGER_HELD``. One function, so the two
    cannot drift apart."""
    drops = list(impulses or ())
    unheld = autonomous_start(
        trajectory,
        hp_lower_on,
        drops,
        windows=windows,
        setpoint_f=setpoint_f,
    )
    if mode is not None and mode != LOWER_HOLD_MODE:
        return unheld[0], unheld[1], False
    at, trigger = autonomous_start(
        trajectory,
        hp_lower_on,
        drops,
        windows=windows,
        setpoint_f=setpoint_f,
        lower_waits_for_upper_short=True,
    )
    return at, trigger, (at, trigger) != unheld


def in_window(
    at: datetime, windows: Sequence[tuple[datetime, datetime]]
) -> bool:
    """Whether ``at`` falls inside one of ``windows`` (opening included)."""
    return any(w[0] <= at < w[1] for w in windows)
