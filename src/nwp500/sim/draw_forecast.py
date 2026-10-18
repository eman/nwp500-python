"""Draws from a weekly draw forecast: the expected draws a forecast
issue's slots imply, the heater's draw windows, and the worst case of
each window's long draws coming first.

A forecaster learned from an installation's meter publishes, for each
10-minute slot of a week, how many long and short draws are expected
to **start** in it (``*_rate``, additive over slots) and how long and
how large one is given that it does (``*_duration_mean_s``,
``*_volume_mean_gal``, delivered gallons past the mixing valve).
Only a mean may be multiplied by a rate to get an expectation: a median
sits below the mean of a right-skewed duration.

**An expected draw is fractional.** A slot expecting 0.4 showers gives
four-tenths of one shower's water: right for the tank's heat over a
window, wrong for the shape of a stratification front. Each draw keeps
the slot's per-draw volume (``Draw.per_draw_gal``), which is what a
draw's domain is judged against, never the fractional one.

**Absent is not empty.** An issue missing a family, or not a whole
week of consecutive slots, has no profile (``check_issue`` says why),
never an empty one standing in for a failure.
"""

import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from itertools import accumulate, pairwise
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nwp500.sim.inputs import Loads

#: A slot's length, and a whole issue's span from its first slot to its
#: last (a week less one slot: 1008 consecutive slots).
SLOT = timedelta(minutes=10)
WEEKLY_ISSUE_SPAN = timedelta(days=7) - SLOT
#: The heater's draw windows: a slot qualifies when the long draws
#: expected to start within ``HEATER_DRAW_REACH`` of it come to
#: ``HEATER_DRAW_RATE``; qualifying slots ``HEATER_DRAW_GAP`` apart
#: are one window, cut into pieces of ``HEATER_DRAW_LONGEST`` (the worst
#: case asks the tank for a window's whole volume at its onset, which an
#: uncut diffuse day could not meet).
HEATER_DRAW_RATE = 0.05
HEATER_DRAW_REACH = timedelta(minutes=60)
HEATER_DRAW_GAP = timedelta(minutes=30)
HEATER_DRAW_LONGEST: timedelta | None = timedelta(hours=2)
#: Below this effective count a slot's published value is mostly its
#: prior: a window resting on one is ``low_confidence``.
DRAW_SUPPORT_FLOOR = 5
_RATE_EPS = 1e-9

#: The fields a profile reads, by the family that publishes them: a
#: NULL, a non-finite or a negative value in any voids the issue.
REQUIRED_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "long rate": ("long_rate", "long_min_s"),
        "long duration": ("long_duration_mean_s", "long_duration_support"),
        "long volume": ("long_volume_mean_gal", "long_volume_support"),
        "short rate": ("short_rate",),
        "short duration": ("short_duration_mean_s", "short_duration_support"),
        "short volume": ("short_volume_mean_gal", "short_volume_support"),
    }
)
NO_COVERING_ISSUE = "no_covering_issue"
SHIFTED_ISSUE_UNCOVERED = "shifted_issue_uncovered"
#: An issue older than this answers nothing: a newer one should have
#: been published.
MAX_ISSUE_AGE = timedelta(hours=36)
FAMILY_NULL = "family_null"
INCOMPLETE_ISSUE = "incomplete_issue"


@dataclass(frozen=True)
class ForecastSlot:
    """One slot of a weekly draw-forecast issue (UTC). ``None`` is a
    value the forecaster did not publish, never zero."""

    valid_at: datetime
    long_rate: float | None = None
    long_min_s: float | None = None
    long_duration_mean_s: float | None = None
    long_duration_p90_s: float | None = None
    long_volume_mean_gal: float | None = None
    long_duration_support: float | None = None
    long_volume_support: float | None = None
    short_rate: float | None = None
    short_duration_mean_s: float | None = None
    short_duration_support: float | None = None
    short_volume_mean_gal: float | None = None
    short_volume_support: float | None = None


@dataclass(frozen=True)
class ExpectedDraw:
    """One aggregate draw per class per slot: ``volume_gal`` is the
    expected delivered volume (rate x mean), ``per_draw_gal`` the
    slot's own per-draw mean, ``duration_s`` the expected time drawing
    (rate x mean)."""

    onset: datetime
    duration_s: float
    volume_gal: float
    draw_class: str
    per_draw_gal: float = 0.0


@dataclass(frozen=True)
class ForecastWindow:
    """A heater draw window and the long draws expected in it:
    ``expected_count`` and ``volume_mean_gal`` summed over its slots,
    ``duration_mean_s`` rate-weighted, ``duration_p90_s`` the largest
    slot's (an envelope, not the window's p90), the supports the
    weakest slot's. ``low_confidence`` when any of it is missing or
    rests on a prior."""

    start: datetime
    end: datetime
    expected_count: float
    volume_mean_gal: float | None
    duration_mean_s: float | None
    duration_p90_s: float | None
    duration_support: float | None
    volume_support: float | None
    low_confidence: bool


@dataclass(frozen=True)
class DrawProfile:
    """The draws one issue expects in a window, and its draw windows
    overlapping it. ``expected_onsets`` is the sum of the rates, the
    expected number of draws, fractional."""

    expected_onsets: float
    draws: list[ExpectedDraw] = field(default_factory=list)
    windows: list[ForecastWindow] = field(default_factory=list)


def covers(
    coverage_start: datetime,
    coverage_end: datetime,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    """Whether ``[coverage_start, coverage_end)`` contains a window (a
    window of no length: its instant)."""
    if coverage_start > window_start:
        return False
    if window_end > window_start:
        return coverage_end >= window_end
    return coverage_end > window_start


def shifted(slots: Sequence[ForecastSlot], by: timedelta) -> list[ForecastSlot]:
    """``slots`` moved ``by`` in time: an issue replayed on another week,
    whose coverage ``check_issue`` then judges as moved
    (``SHIFTED_ISSUE_UNCOVERED``)."""
    return [replace(s, valid_at=s.valid_at + by) for s in slots]


def check_issue(
    slots: Sequence[ForecastSlot],
    start: datetime | None = None,
    end: datetime | None = None,
    *,
    issued_at: datetime | None = None,
    now: datetime | None = None,
    shift: timedelta | None = None,
) -> str | None:
    """Why an issue cannot answer, or None: no slots
    (``NO_COVERING_ISSUE``); a family missing, non-finite or negative
    in any slot (``FAMILY_NULL``); or not seven consecutive days of
    slots (``INCOMPLETE_ISSUE``). With a window ``[start, end]``, also
    one the issue's slots do not cover whole (``NO_COVERING_ISSUE``,
    ``SHIFTED_ISSUE_UNCOVERED`` for an issue moved by ``shift``); with
    ``issued_at`` and ``now``, one issued more than ``MAX_ISSUE_AGE``
    before ``now`` or after it (``NO_COVERING_ISSUE``)."""
    if not slots:
        return NO_COVERING_ISSUE
    if (
        issued_at is not None
        and now is not None
        and not (timedelta(0) <= now - issued_at <= MAX_ISSUE_AGE)
    ):
        return NO_COVERING_ISSUE
    if start is not None:
        stamps = [s.valid_at for s in slots]
        if not covers(min(stamps), max(stamps) + SLOT, start, end or start):
            return SHIFTED_ISSUE_UNCOVERED if shift else NO_COVERING_ISSUE
    for columns in REQUIRED_FIELDS.values():
        for column in columns:
            for s in slots:
                v = getattr(s, column)
                if v is None or not math.isfinite(v) or v < 0.0:
                    return FAMILY_NULL
    stamps = sorted(s.valid_at for s in slots)
    steps = {b - a for a, b in pairwise(stamps)}
    if stamps[-1] - stamps[0] != WEEKLY_ISSUE_SPAN or steps != {SLOT}:
        return INCOMPLETE_ISSUE
    return None


def _rate(s: ForecastSlot) -> float | None:
    v = s.long_rate
    return None if v is None or math.isnan(v) else float(v)


def _collect(run: Sequence[ForecastSlot], attr: str) -> list[float] | None:
    out = []
    for s in run:
        v = getattr(s, attr)
        if v is None:
            return None
        out.append(float(v))
    return out


def _window(
    slots: Sequence[ForecastSlot], start: datetime, end: datetime
) -> ForecastWindow:
    run = [s for s in slots if start <= s.valid_at < end]
    raw = [_rate(s) for s in run]
    rated = all(v is not None for v in raw)
    present = [float(v) for v in raw if v is not None]
    expected = float(sum(present))
    volumes = _collect(run, "long_volume_mean_gal")
    volume_mean = (
        None
        if volumes is None or not rated
        else float(sum(r * v for r, v in zip(present, volumes, strict=True)))
    )
    durations = _collect(run, "long_duration_mean_s")
    duration_mean = (
        None
        if durations is None or not rated or expected <= 0.0
        else float(
            sum(r * d for r, d in zip(present, durations, strict=True))
            / expected
        )
    )
    p90s = _collect(run, "long_duration_p90_s")
    dur_sup = _collect(run, "long_duration_support")
    vol_sup = _collect(run, "long_volume_support")
    duration_support = None if dur_sup is None else float(min(dur_sup))
    volume_support = None if vol_sup is None else float(min(vol_sup))
    low = (
        not rated
        or expected == 0.0
        or duration_support is None
        or duration_support < DRAW_SUPPORT_FLOOR
        or volume_support is None
        or volume_support < DRAW_SUPPORT_FLOOR
    )
    return ForecastWindow(
        start=start,
        end=end,
        expected_count=expected,
        volume_mean_gal=volume_mean,
        duration_mean_s=duration_mean,
        duration_p90_s=None if p90s is None else float(max(p90s)),
        duration_support=duration_support,
        volume_support=volume_support,
        low_confidence=low,
    )


def _pieces(
    start: datetime, end: datetime, longest: timedelta | None
) -> list[tuple[datetime, datetime]]:
    if longest is None or end - start <= longest:
        return [(start, end)]
    out = []
    while start < end:
        out.append((start, min(end, start + longest)))
        start += longest
    return out


def heater_draw_windows(
    slots: Sequence[ForecastSlot],
    rate: float = HEATER_DRAW_RATE,
    reach: timedelta = HEATER_DRAW_REACH,
    max_gap: timedelta = HEATER_DRAW_GAP,
    longest: timedelta | None = HEATER_DRAW_LONGEST,
) -> list[ForecastWindow]:
    """The heater's draw windows: every likely long draw (module
    constants). A window opens up to ``reach`` before its first
    expected draw, a draw can come that much earlier than any the
    forecast has seen, and takes in every slot with a rate within
    ``reach`` of either end; overlapping windows merge, and a long one
    is cut into ``longest`` pieces (a last piece expecting no draw
    joins the one before). None of the long rates published: no
    windows, which is unknown, not none."""
    if not any(_rate(s) is not None for s in slots):
        return []
    slots = sorted(slots, key=lambda s: s.valid_at)
    times = [s.valid_at for s in slots]
    rates = [_rate(s) or 0.0 for s in slots]
    sums = [0.0, *accumulate(rates)]

    def within(a: datetime, b: datetime) -> tuple[int, int]:
        return bisect_left(times, a), bisect_right(times, b)

    qualifying = []
    for i, s in enumerate(slots):
        lo, hi = within(s.valid_at - reach, s.valid_at + reach)
        if sums[hi] - sums[lo] >= rate - _RATE_EPS:
            qualifying.append(i)
    runs: list[list[int]] = []
    for i in qualifying:
        if runs and times[i] - times[runs[-1][-1]] <= max_gap:
            runs[-1].append(i)
        else:
            runs.append([i])
    spans: list[tuple[datetime, datetime]] = []
    for run in runs:
        lo, _ = within(times[run[0]] - reach, times[run[0]])
        _, hi = within(times[run[-1]], times[run[-1]] + reach)
        bearing = [j for j in range(lo, hi) if rates[j] > 0.0]
        start = min([times[run[0]], *(times[j] for j in bearing)])
        last = max([times[run[-1]], *(times[j] for j in bearing)])
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], last + SLOT))
        else:
            spans.append((start, last + SLOT))
    out: list[ForecastWindow] = []
    for a, b in spans:
        pieces = [_window(slots, c, d) for c, d in _pieces(a, b, longest)]
        if len(pieces) > 1 and pieces[-1].expected_count == 0.0:
            pieces[-2:] = [_window(slots, pieces[-2].start, b)]
        out += pieces
    return out


def draw_profile(
    slots: Sequence[ForecastSlot], start: datetime, end: datetime
) -> DrawProfile:
    """The draws an issue (``check_issue``'s, the window included)
    expects in ``[start, end)``: per slot and class, ``rate x mean
    volume`` delivered from the slot's start over ``rate x mean
    duration``, the per-draw volume kept; the expected onsets (the
    rates' sum, a slot with no volume counting toward it); and the
    issue's draw windows overlapping the span, laid out over the whole
    issue so a window open before ``start`` keeps its geometry. A
    window the issue does not cover is a ``ValueError``: past its end
    the draws are unknown, not none."""
    if not covers(
        min(s.valid_at for s in slots),
        max(s.valid_at for s in slots) + SLOT,
        start,
        end,
    ):
        # Past the issue's end the draws are unknown, not none.
        raise ValueError(
            f"{NO_COVERING_ISSUE}: the issue does not cover "
            f"{start.isoformat()} to {end.isoformat()}"
        )
    draws: list[ExpectedDraw] = []
    onsets = 0.0
    for s in slots:
        if not start <= s.valid_at < end:
            continue
        for draw_class in ("long", "short"):
            rate = float(getattr(s, f"{draw_class}_rate") or 0.0)
            per = float(getattr(s, f"{draw_class}_volume_mean_gal") or 0.0)
            mean_s = float(getattr(s, f"{draw_class}_duration_mean_s") or 0.0)
            onsets += rate
            volume = rate * per
            if rate <= 0.0 or volume <= 0.0:
                continue
            draws.append(
                ExpectedDraw(
                    onset=s.valid_at,
                    duration_s=rate * mean_s,
                    volume_gal=volume,
                    draw_class=draw_class,
                    per_draw_gal=per,
                )
            )
    windows = [
        w for w in heater_draw_windows(slots) if w.end > start and w.start < end
    ]
    return DrawProfile(
        expected_onsets=onsets,
        draws=sorted(draws, key=lambda d: (d.onset, d.draw_class)),
        windows=windows,
    )


def draws_first(
    profile: DrawProfile, start: datetime
) -> tuple[
    list[tuple[datetime, float, float]], list[tuple[datetime, datetime] | None]
]:
    """The worst case for each draw window: its long draws come first,
    back to back from its onset (or ``start``, for a window already
    open), before any recovery. The profile's draws so placed, as
    ``(at, gallons, per-draw gallons)`` (short ones and those outside
    every window where the profile put them), and per window the span
    they occupy, never past its end, where no heat is credited (None
    for a window expecting no long draw; the whole window when its
    durations are unknown, its draws left in place)."""
    spans: list[tuple[datetime, datetime] | None] = []
    moved: dict[int, datetime] = {}
    for w in profile.windows:
        inside = [
            (i, d)
            for i, d in enumerate(profile.draws)
            if d.draw_class == "long" and w.start <= d.onset < w.end
        ]
        if w.duration_mean_s is None:
            spans.append((w.start, w.end))
            continue
        if not inside:
            spans.append(None)
            continue
        opens = max(w.start, start)
        at = opens
        for i, d in sorted(inside, key=lambda x: x[1].onset):
            if at >= w.end:
                break
            moved[i] = at
            at += timedelta(seconds=d.duration_s)
        spans.append((opens, min(w.end, at)) if at > opens else None)
    draws = sorted(
        (moved.get(i, d.onset), d.volume_gal, d.per_draw_gal)
        for i, d in enumerate(profile.draws)
    )
    return draws, spans


def forecast_loads(
    profile: DrawProfile,
    start: datetime,
    *,
    worst_case: bool = False,
) -> tuple[Loads, list[tuple[datetime, datetime]]]:
    """The profile as a scenario's ``Loads`` (each expected draw a
    ``Draw`` carrying its per-draw volume, each window a ``DrawWindow``
    expecting its long draws' volume) and the spans to withhold heat
    over (``simulate``'s ``withheld_windows``): none, or with
    ``worst_case`` each window's long draws first (``draws_first``)."""
    from nwp500.sim.inputs import Draw, DrawWindow, Loads

    if worst_case:
        placed, spans = draws_first(profile, start)
        withheld = [x for x in spans if x is not None]
    else:
        placed = [
            (d.onset, d.volume_gal, d.per_draw_gal) for d in profile.draws
        ]
        withheld = []
    loads = Loads(
        draws=tuple(
            Draw(at=at, gallons=g, per_draw_gal=per or None)
            for at, g, per in placed
            if g > 0.0
        ),
        windows=tuple(
            DrawWindow(start=w.start, end=w.end, expected_gal=w.volume_mean_gal)
            for w in profile.windows
        ),
    )
    return loads, withheld
