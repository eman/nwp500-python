"""The mains temperature a draw meets, from an inlet probe's readings
over long draws.

A probe strapped to the cold supply reads the mains only while water
moves: with no flow the pipe stagnates and the probe tracks the air
around it, about 1.3 degF warm and 15-30 min behind. So the estimate is
taken from long draws, never from the series itself. At one
installation, on every draw of 8 gal or more with circulation off, the
probe responded within about 50 s, passed the stagnant water of the
indoor run as a dip and a bump over the first 4 min, and then settled
from above for several more: a window from minute 9 read at most
0.22 degF above everything after it. So a plateau is read from minute 9
on, and only a draw of 11 min or more has one.

A draw counts when it ran ``settle_s + tail_s`` or more with
circulation off throughout and the meter reading water moving over its
tail; its plateau is the median probe reading over its last ``tail_s``,
none earlier than ``settle_s`` after its onset, kept within
``plausible_f``. The estimate is the median plateau of the counted
draws that ended within ``window_s`` before the instant asked about;
none without one, and the caller keeps its own inlet rather than the
raw series.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from statistics import median

from nwp500.sim.book import Booked


@dataclass(frozen=True)
class ColdSupplyParams:
    """How a plateau is read; one installation's probe's, measured."""

    #: Flow before the plateau: the stagnant indoor run passes first,
    #: and the reading settles from above until about minute 9, s.
    settle_s: float = 540.0
    #: The stretch at a draw's end the plateau is read over, s.
    tail_s: float = 120.0
    #: Draw instants further apart than this are two draws, s.
    tick_gap_s: float = 30.0
    #: How long the interval a draw instant closes is, s.
    tick_s: float = 10.0
    #: How far back a draw may have ended and still count, s.
    window_s: float = 72.0 * 3600.0
    #: The band a plateau must lie in to be the mains, degF: below is a
    #: probe in ice or a frozen pipe, above is air, not water.
    plausible_f: tuple[float, float] = (40.0, 85.0)
    #: Readings a plateau needs.
    min_readings: int = 3
    #: The meter's flow that is water moving, gal/min.
    draw_gpm: float = 0.3


@dataclass(frozen=True)
class ColdSupply:
    """The estimate, and what it rests on."""

    #: Median plateau, degF; None when no draw counted.
    t_cold_f: float | None
    #: Draws the median is over.
    draws: int = 0
    #: When the newest counted draw ended.
    newest_at: datetime | None = None


Readings = Sequence[tuple[datetime, float]]


def _runs(
    ticks: Sequence[datetime], gap: timedelta
) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for t in sorted(ticks):
        if out and t - out[-1][1] <= gap:
            out[-1] = (out[-1][0], t)
        else:
            out.append((t, t))
    return out


def _metered(
    flow: Readings, start: datetime, end: datetime, gpm: float
) -> bool:
    """Whether the meter read water moving over ``[start, end)``: the
    median of the reading in force at ``start`` and every one after it
    before ``end`` at or above ``gpm`` (a median: the meter reports the
    close as it ramps down, seconds before the last draw instant)."""
    before = [v for t, v in flow if t <= start]
    if not before:
        return False
    held = [before[-1], *(v for t, v in flow if start < t < end)]
    return float(median(held)) >= gpm


def plateau_t_cold(
    probe: Readings,
    ticks: Sequence[datetime],
    circulation: Sequence[tuple[datetime, datetime]] | None,
    at: datetime,
    p: ColdSupplyParams = ColdSupplyParams(),
    *,
    flow: Readings | None,
) -> ColdSupply:
    """The mains as of ``at`` from the plateaus of recent long draws.

    ``probe`` is the inlet probe's readings, ``ticks`` the instants the
    meter or a detector saw water drawn (each closes ``tick_s``),
    ``circulation`` the circulation's runs and ``flow`` the meter's
    flow, gal/min. Nothing after ``at`` is read. None for
    ``circulation`` or ``flow`` is unrecorded, which is not idle: no
    estimate."""
    if circulation is None or not flow or not probe or not ticks:
        return ColdSupply(None)
    since = at - timedelta(seconds=p.window_s)
    flow = sorted((t, v) for t, v in flow if t <= at)
    ticks = [t for t in ticks if since <= t <= at]
    probe = sorted((t, v) for t, v in probe if t <= at)
    settle = timedelta(seconds=p.settle_s)
    tail = timedelta(seconds=p.tail_s)
    plateaus: list[float] = []
    newest: datetime | None = None
    for onset, last_tick in _runs(ticks, timedelta(seconds=p.tick_gap_s)):
        end = min(last_tick + timedelta(seconds=p.tick_s), at)
        if end - onset < settle + tail:
            continue
        if any(a < end and b > onset for a, b in circulation):
            continue
        tail_from = max(onset + settle, end - tail)
        readings = [v for t, v in probe if tail_from <= t <= end]
        if len(readings) < p.min_readings:
            continue
        if not _metered(flow, tail_from, end, p.draw_gpm):
            continue
        plateau = float(median(readings))
        if not p.plausible_f[0] <= plateau <= p.plausible_f[1]:
            continue
        plateaus.append(plateau)
        newest = end if newest is None else max(newest, end)
    if not plateaus:
        return ColdSupply(None)
    return ColdSupply(float(median(plateaus)), len(plateaus), newest)


def on_the_mains(
    book: Booked | None, cold: ColdSupply
) -> tuple[Booked | None, bool]:
    """``book`` converting heat to gallons at the mains (``cold``'s
    plateau), and whether it does: a book's own inlet is a probe's
    median over hours, which at rest reads the air around the pipe, not
    the mains (a 10-20 % swing in the gallons at one installation).
    Unchanged with no plateau or no book. Pass the flag to
    ``time_to_ready``'s ``inlet_measured``."""
    if book is None:
        return None, False
    if cold.t_cold_f is None:
        return book, False
    return replace(book, inlet_f=cold.t_cold_f), True
