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

The draws are the caller's: the spans the household drew hot water,
with the circulation's water not among them. A draw counts when it ran
``settle_s + tail_s`` or more with circulation off throughout; its
plateau is the median probe reading over its last ``tail_s``,
none earlier than ``settle_s`` after its onset, kept within
``plausible_f``. The estimate is the median plateau of the counted
draws that ended within ``window_s`` before the instant asked about;
none without one, and the caller keeps its own inlet rather than the
raw series.

Without a probe, the mains come from the installation's climate
(``mains_f``): Burch and Christensen's correlation of the water a
utility delivers with the year's outdoor air, as the Building America
House Simulation Protocols and EnergyPlus use it. ``climate_of`` reads
that climate off a year of outdoor readings.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import fmean, median

from nwp500.sim.circulation import merge_runs


@dataclass(frozen=True)
class ColdSupplyParams:
    """How a plateau is read; one installation's probe's, measured."""

    #: Flow before the plateau: the stagnant indoor run passes first,
    #: and the reading settles from above until about minute 9, s.
    settle_s: float = 540.0
    #: The stretch at a draw's end the plateau is read over, s.
    tail_s: float = 120.0
    #: How far back a draw may have ended and still count, s.
    window_s: float = 72.0 * 3600.0
    #: The band a plateau must lie in to be the mains, degF: below is a
    #: probe in ice or a frozen pipe, above is air, not water.
    plausible_f: tuple[float, float] = (40.0, 85.0)
    #: Readings a plateau needs.
    min_readings: int = 3
    #: Circulation runs closer than this are one run, s, as the walk
    #: merges them (``circulation.merge_runs``).
    run_gap_s: float = 600.0


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


def plateau_t_cold(
    probe: Readings,
    draws: Sequence[tuple[datetime, datetime]],
    circulation: Sequence[tuple[datetime, datetime]] | None,
    at: datetime,
    p: ColdSupplyParams = ColdSupplyParams(),
) -> ColdSupply:
    """The mains as of ``at`` from the plateaus of recent long draws.

    ``probe`` is the inlet probe's readings, ``draws`` the spans the
    household drew hot water and ``circulation`` the circulation's runs.
    Nothing after ``at`` is read. None for ``circulation`` is
    unrecorded, which is not idle: no estimate."""
    if circulation is None or not probe or not draws:
        return ColdSupply(None)
    since = at - timedelta(seconds=p.window_s)
    # A missing reading (NaN) is one not taken, never a number.
    probe = sorted((t, v) for t, v in probe if t <= at and math.isfinite(v))
    circulation = merge_runs(circulation, timedelta(seconds=p.run_gap_s))
    settle = timedelta(seconds=p.settle_s)
    tail = timedelta(seconds=p.tail_s)
    plateaus: list[float] = []
    newest: datetime | None = None
    for onset, ended in sorted(draws):
        end = min(ended, at)
        if end < since or end - onset < settle + tail:
            continue
        if any(a < end and b > onset for a, b in circulation):
            continue
        tail_from = max(onset + settle, end - tail)
        readings = [v for t, v in probe if tail_from <= t <= end]
        if len(readings) < p.min_readings:
            continue
        plateau = float(median(readings))
        if not p.plausible_f[0] <= plateau <= p.plausible_f[1]:
            continue
        plateaus.append(plateau)
        newest = end if newest is None else max(newest, end)
    if not plateaus:
        return ColdSupply(None)
    return ColdSupply(float(median(plateaus)), len(plateaus), newest)


#: Burch and Christensen's mains, above the year's mean air, degF.
MAINS_OFFSET_F = 6.0
#: The air the correlation's ratio and lag are measured from, degF.
MAINS_REFERENCE_AIR_F = 44.0
#: Days a whole month needs readings on to count toward a climate.
CLIMATE_MONTH_DAYS = 20


def mains_f(annual_mean_f: float, swing_f: float, day: date) -> float:
    """The mains on ``day``, degF, from the climate (Burch and
    Christensen, NREL 2007): ``annual_mean_f``, the year's mean outdoor
    air, and ``swing_f``, its warmest monthly mean less its coldest. The
    water runs ``MAINS_OFFSET_F`` above the mean air and swings with it,
    damped and lagging more the colder the climate. A northern
    hemisphere's year, as the correlation was fitted on.

    At one installation (a year's mean air 61.3 degF, swing 19.9 degF),
    it read a mean 1.5 degF under the plateaus of an inlet probe at the
    heater over 25 days of 2026-09-20..10-28 (0.1-3.9), the probe's
    indoor pipe run included, and 0.8 degF under from 10-20 on."""
    ratio = 0.4 + 0.01 * (annual_mean_f - MAINS_REFERENCE_AIR_F)
    lag_d = 35.0 - (annual_mean_f - MAINS_REFERENCE_AIR_F)
    n = day.timetuple().tm_yday
    phase = math.radians(0.986 * (n - 15.0 - lag_d) - 90.0)
    return (
        annual_mean_f + MAINS_OFFSET_F + ratio * swing_f / 2.0 * math.sin(phase)
    )


def climate_of(air: Readings) -> tuple[float, float] | None:
    """``mains_f``'s climate, ``(annual_mean_f, swing_f)``, from the
    outdoor ``air`` readings, degF: the mean and the range of the monthly
    means over the latest twelve whole months (by the readings' own
    calendar), a month whole with readings on ``CLIMATE_MONTH_DAYS``
    days or more and the twelve consecutive. None without such a year.
    A reading that is not a number is left out."""
    days: dict[tuple[int, int], dict[date, list[float]]] = {}
    for t, v in air:
        if math.isfinite(v):
            month = days.setdefault((t.year, t.month), {})
            month.setdefault(t.date(), []).append(v)
    whole = sorted(m for m, d in days.items() if len(d) >= CLIMATE_MONTH_DAYS)
    if len(whole) < 12:
        return None
    year = whole[-12:]
    first, last = year[0], year[-1]
    if (last[0] - first[0]) * 12 + last[1] - first[1] != 11:
        return None
    means = [fmean(fmean(v) for v in days[m].values()) for m in year]
    return fmean(means), max(means) - min(means)
