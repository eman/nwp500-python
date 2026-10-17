"""The heater's schedules laid out as instants: its TOU windows and its
reservations' firings.

**TOU windows.** The heater holds its recoveries in the window its TOU
schedule prices highest (``docs/explanation/tou-recovery-cap.rst``).
For each group of periods sharing a season and week mask, every run of
contiguous periods at the group's highest price (each price decoded at
its own ``decimal_point``) is a window on each date both masks select.
A group with one price has no window. The dated windows are then
joined where one ends as the next begins, so a peak across midnight is
one window only when the masks select both dates: Friday's weekday
peak does not run into Saturday morning, nor Monday morning's begin on
a Sunday night. Whether
TOU is on is a switch of its own (``Schedules.tou_enabled``), not part
of the periods.

**Reservations.** An enabled entry fires at its local hour and minute
on each day its week mask selects, as long as the schedule's switch is
on. A local time the clock skips at a daylight-saving change is taken
at its standard-time reading, an hour later on the wall clock; a local
time the clock repeats fires once, at its first occurrence. The
device's own behaviour at those changes has not been measured.

Day masks are the device's: Sunday bit 7, Monday bit 6, ... Saturday
bit 1 (so 124 is Monday to Friday and 130 the weekend). Season masks:
bit 0 January ... bit 11 December.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nwp500.sim.inputs import ReservationEntry, TouPeriod

#: A window: when it opens and when it closes (exclusive), UTC.
Window = tuple[datetime, datetime]


def week_bit(day: date) -> int:
    """The device's week-mask bit for ``day`` (Sunday bit 7 ...
    Saturday bit 1)."""
    # weekday(): Monday 0 ... Sunday 6.
    return 1 << (6 - day.weekday() if day.weekday() < 6 else 7)


def month_bit(day: date) -> int:
    """The device's season-mask bit for ``day``'s month."""
    return 1 << (day.month - 1)


@dataclass(frozen=True)
class TouRule:
    """A daily window on the days both masks select: from ``opens`` to
    ``closes`` (exclusive), local, within the day; a ``closes`` of 00:00
    is the day's end."""

    season_mask: int
    week_mask: int
    opens: time
    closes: time


def _start(p: TouPeriod) -> int:
    return p.start_hour * 60 + p.start_minute


def _end(p: TouPeriod) -> int:
    return p.end_hour * 60 + p.end_minute


def tou_rules(periods: Iterable[TouPeriod]) -> tuple[TouRule, ...]:
    """The windows ``periods`` define, as daily rules."""
    groups: dict[tuple[int, int], list[TouPeriod]] = {}
    for p in periods:
        groups.setdefault((p.season, p.week), []).append(p)
    rules: list[TouRule] = []
    for (season, week), group in groups.items():
        group = sorted(group, key=_start)
        # Decoded, each at its own scale: 1000 at 4 places is 0.10.
        prices = [p.price_max / 10**p.decimal_point for p in group]
        top = max(prices)
        if top == min(prices):
            continue
        runs: list[tuple[int, int]] = []  # [first, last] period indexes
        for k, price in enumerate(prices):
            if price != top:
                continue
            contiguous = (
                runs
                and runs[-1][1] == k - 1
                and _start(group[k]) == _end(group[k - 1]) + 1
            )
            if contiguous:
                runs[-1] = (runs[-1][0], k)
            else:
                runs.append((k, k))
        spans = [(_start(group[a]), _end(group[b]) + 1) for a, b in runs]
        rules.extend(
            TouRule(
                season,
                week,
                time(opens // 60, opens % 60),
                time((closes // 60) % 24, closes % 60),
            )
            for opens, closes in spans
        )
    return tuple(rules)


def _spans_on(rules: Sequence[TouRule], day: date) -> list[tuple[time, time]]:
    """Every window opening on ``day``, in opening order. Overlapping
    rules all apply; a span two rules share is listed once."""
    found = {
        (r.opens, r.closes)
        for r in rules
        if r.season_mask & month_bit(day) and r.week_mask & week_bit(day)
    }
    return sorted(found)


def tou_windows(
    periods: Iterable[TouPeriod],
    tz: ZoneInfo,
    start: datetime,
    end: datetime,
) -> tuple[Window, ...]:
    """The TOU windows ``periods`` define that overlap ``[start, end]``,
    as UTC instants, with the local times in ``tz``: each rule laid out
    on the dates its masks select, from a day before ``start`` to a day
    after ``end`` so a window across either edge is whole, and then
    joined where one ends as the next begins."""
    rules = tou_rules(periods)
    dated: list[Window] = []
    day = start.astimezone(tz).date() - timedelta(days=1)
    last = end.astimezone(tz).date() + timedelta(days=1)
    while day <= last:
        for opens_at, closes_at in _spans_on(rules, day):
            opens = datetime.combine(day, opens_at, tz)
            close_day = (
                day + timedelta(days=1) if closes_at <= opens_at else day
            )
            closes = datetime.combine(close_day, closes_at, tz)
            dated.append((opens.astimezone(UTC), closes.astimezone(UTC)))
        day += timedelta(days=1)
    joined: list[Window] = []
    for opens, closes in sorted(dated):
        if joined and opens <= joined[-1][1]:
            joined[-1] = (joined[-1][0], max(joined[-1][1], closes))
        else:
            joined.append((opens, closes))
    return tuple(w for w in joined if w[1] > start and w[0] <= end)


@dataclass(frozen=True)
class Firing:
    """A reservation entry firing at an instant (UTC)."""

    at: datetime
    entry: ReservationEntry
    #: The entry's index in the schedule.
    index: int


def reservation_firings(
    entries: Sequence[ReservationEntry],
    tz: ZoneInfo,
    start: datetime,
    end: datetime,
) -> tuple[Firing, ...]:
    """Every firing of the enabled ``entries`` in ``[start, end)``, in
    time order (two at one instant in the schedule's order), with the
    local times in ``tz``."""
    out: list[Firing] = []
    day = start.astimezone(tz).date() - timedelta(days=1)
    last = end.astimezone(tz).date()
    while day <= last:
        for i, e in enumerate(entries):
            if not e.enabled or not e.week & week_bit(day):
                continue
            local = datetime.combine(day, time(e.hour, e.minute), tz)
            at = local.astimezone(UTC)
            if start <= at < end:
                out.append(Firing(at, e, i))
        day += timedelta(days=1)
    return tuple(sorted(out, key=lambda f: (f.at, f.index)))


def half_c_to_f(half_c: int) -> float:
    """A device setpoint in half-degrees Celsius, in °F."""
    return half_c / 2.0 * 9 / 5 + 32
