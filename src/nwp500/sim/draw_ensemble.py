"""Draws sampled from a weekly draw forecast, and candidates weighed on
the same samples.

One walk on a forecast's expected draws (``draw_forecast``) is one
trace of a household that draws a fraction of a shower in each slot. It
is right for the heat drawn over a day, and wrong for running out: a
tank empties on the evening two showers come close together, and an
expectation has none. A set of **members**, each a household's day
drawn from what the forecaster publishes, gives the chance of running
cold and the spread of the cost.

**A member** draws, in each slot and class, a count of draws from a
Poisson distribution at the slot's rate, each starting at a uniform
instant in the slot; a slot the span cuts, over the part inside it at
its rate for that part. A long draw's duration is the slot's minimum
(``long_min_s``) and a lognormal part matched to the published mean and
90th percentile above it; where no lognormal above the minimum reaches
that 90th percentile, above a lower floor that matches both; with no
90th percentile above the mean it is the mean. Its volume goes with
its duration at the slot's mean flow (``volume_mean /
duration_mean``), so the expected volume is the
published one; a draw longer than a day is cut to a day at that flow
(``MAX_DRAW_S``), so a slot whose durations reach past a day draws
less than it publishes. A short draw, whose spread is not published, is its
slot's means. Each member is seeded on its own (``seed`` and its
index), so a member is the same whatever the number asked for.

**The same members for every candidate** (common random numbers): two
candidates walked on the same households differ by what they change,
not by the draws each happened to meet, so their difference is far
less noisy than between two ensembles drawn apart. ``weigh`` walks
each candidate on each member; compare candidates member by member.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import numpy as np

from nwp500.sim.api import simulate
from nwp500.sim.delivery import delivery_along, depletion
from nwp500.sim.draw_forecast import (
    SLOT,
    ForecastSlot,
    draw_profile,
)
from nwp500.sim.extensions import RecoveryModel
from nwp500.sim.inputs import Draw, DrawWindow, Loads, Scenario
from nwp500.sim.params import HeaterParams
from nwp500.sim.result import SimulationResult

#: The longest draw, s (``Draw.duration_s``).
MAX_DRAW_S = 86400.0
#: The standard normal's 90th percentile.
_Z90 = 1.2815515655446004


@dataclass(frozen=True)
class Member:
    """One household's draws over a span, sampled from a forecast."""

    #: The draws, each its own volume and duration, and the forecast's
    #: draw windows (the same in every member).
    loads: Loads
    #: Each long draw's span: what a shower asks of the tank.
    long_draws: tuple[tuple[datetime, datetime], ...]
    #: The span sampled, ``[start, end)``.
    start: datetime
    end: datetime


def members(
    slots: Sequence[ForecastSlot],
    start: datetime,
    end: datetime,
    *,
    count: int = 50,
    seed: int = 0,
) -> tuple[Member, ...]:
    """``count`` members over ``[start, end)`` from an issue
    (``draw_forecast.check_issue``'s, the span included). A span the
    issue does not cover is a ``ValueError``, as for
    ``draw_forecast.draw_profile``."""
    if count < 1:
        raise ValueError("an ensemble has at least one member")
    # In UTC: offsets and durations added to a local instant are the
    # wall clock's, which an hour repeated or skipped by daylight saving
    # moves; the windows made from the same slots.
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    slots = [replace(s, valid_at=s.valid_at.astimezone(UTC)) for s in slots]
    profile = draw_profile(slots, start, end)
    # The windows as ``forecast_loads`` makes them, without its expected
    # draws, which a valid slot can make longer than a ``Draw`` runs.
    windows = tuple(
        DrawWindow(
            start=w.start,
            end=w.end,
            expected_gal=w.volume_mean_gal,
            expected_count=w.expected_count,
            draws_until=max(w.start, start),
        )
        for w in profile.windows
    )
    overlapping = [
        s for s in slots if s.valid_at < end and s.valid_at + SLOT > start
    ]
    return tuple(
        _member(
            overlapping, windows, start, end, np.random.default_rng([seed, k])
        )
        for k in range(count)
    )


def _member(
    slots: Sequence[ForecastSlot],
    windows: Sequence[DrawWindow],
    start: datetime,
    end: datetime,
    rng: np.random.Generator,
) -> Member:
    draws: list[Draw] = []
    long_draws: list[tuple[datetime, datetime]] = []
    for s in slots:
        for draw_class in ("long", "short"):
            rate = float(getattr(s, f"{draw_class}_rate") or 0.0)
            volume = float(getattr(s, f"{draw_class}_volume_mean_gal") or 0.0)
            mean_s = float(getattr(s, f"{draw_class}_duration_mean_s") or 0.0)
            if rate <= 0.0 or volume <= 0.0:
                continue
            # A slot the span cuts is drawn over the part inside it, at
            # its rate for that part.
            a = max(s.valid_at, start)
            b = min(s.valid_at + SLOT, end)
            share = (b - a) / SLOT
            n = int(rng.poisson(rate * share))
            if n == 0:
                continue
            offsets = rng.uniform(0.0, (b - a).total_seconds(), n)
            if draw_class == "long":
                seconds = _long_seconds(s, mean_s, rng, n)
            else:
                seconds = np.full(n, mean_s)
            for off, sec in zip(offsets, seconds, strict=True):
                # A draw runs at most a day (``Draw.duration_s``), at the
                # slot's flow.
                duration = float(min(max(sec, 0.0), MAX_DRAW_S))
                gal = volume * duration / mean_s if mean_s > 0.0 else volume
                if gal <= 0.0:
                    continue
                at = a + timedelta(seconds=float(off))
                draws.append(
                    Draw(
                        at=at,
                        gallons=gal,
                        per_draw_gal=gal,
                        duration_s=duration,
                    )
                )
                if draw_class == "long":
                    long_draws.append((at, at + timedelta(seconds=duration)))
    draws.sort(key=lambda d: d.at)
    return Member(
        loads=Loads(draws=tuple(draws), windows=tuple(windows)),
        long_draws=tuple(sorted(long_draws)),
        start=start,
        end=end,
    )


def _long_seconds(
    s: ForecastSlot, mean_s: float, rng: np.random.Generator, n: int
) -> np.ndarray:
    """``n`` long draws' durations: the slot's minimum and a lognormal
    part with the mean and the 90th percentile above it (``_shape``);
    the mean when the spread is not known."""
    floor, sigma = _shape(mean_s, s.long_min_s, s.long_duration_p90_s)
    m = mean_s - floor
    if m <= 0.0 or sigma <= 0.0:
        return np.full(n, mean_s)
    mu = math.log(m) - sigma * sigma / 2.0
    return floor + rng.lognormal(mu, sigma, n)


def _shape(
    mean: float, minimum: float | None, p90: float | None
) -> tuple[float, float]:
    """The floor and the sigma of a lognormal above it with ``mean``
    and 90th percentile ``p90``: the smaller root of
    ``z90 sigma - sigma^2 / 2 = ln((p90 - floor) / (mean - floor))``.
    The floor is ``minimum``, or lower where no lognormal above it
    reaches ``p90`` (the ratio past ``z90^2 / 2``): there the floor at
    which sigma is ``z90`` and both match, or 0 and sigma ``z90``, the
    nearest it comes, when even no floor reaches it. Sigma 0 with no
    90th percentile above the mean, or one not finite."""
    floor = min(max(float(minimum or 0.0), 0.0), mean)
    if p90 is None or not math.isfinite(p90) or mean <= 0.0 or p90 <= mean:
        return floor, 0.0
    widest = math.exp(_Z90 * _Z90 / 2.0)
    if (p90 - floor) > widest * (mean - floor):
        floor = max(0.0, (widest * mean - p90) / (widest - 1.0))
        if (p90 - floor) >= widest * (mean - floor):
            return floor, _Z90
    r = math.log((p90 - floor) / (mean - floor))
    return floor, _Z90 - math.sqrt(max(_Z90 * _Z90 - 2.0 * r, 0.0))


@dataclass(frozen=True)
class MemberWalk:
    """A candidate walked on one member."""

    member: Member
    walk: SimulationResult
    #: The lowest delivery over the member's long draws, °F; None with
    #: no long draw.
    long_min_f: float | None
    #: Whether a long draw's delivery fell below the line
    #: (``ReadinessParams.line_f``).
    cold: bool
    #: The long draws running past the walk's start or end, judged only
    #: over the walk: one judged warm may yet run cold past it.
    cut_short: int = 0


@dataclass(frozen=True)
class Weighed:
    """A candidate walked on every member, in the members' order."""

    walks: tuple[MemberWalk, ...]

    @property
    def cold_share(self) -> float:
        """The share of members in which a long draw ran cold."""
        return sum(w.cold for w in self.walks) / len(self.walks)

    @property
    def input_wh(self) -> tuple[float | None, ...]:
        """Each member's electricity, Wh (None, unpriced)."""
        return tuple(w.walk.input_wh for w in self.walks)

    def mean(
        self, value: Callable[[SimulationResult], float | None]
    ) -> float | None:
        """The mean over the members of ``value`` (a cost from
        ``energy_by_slot``, say); None when any member's is None."""
        values = [value(w.walk) for w in self.walks]
        if any(v is None for v in values):
            return None
        return sum(v for v in values if v is not None) / len(values)


def weigh(
    scenarios: Sequence[Scenario],
    ensemble: Sequence[Member],
    params: HeaterParams,
    *,
    recovery: RecoveryModel | None = None,
    tou_windows_in_force: Sequence[tuple[datetime, datetime]] | None = None,
    withheld_windows: Sequence[tuple[datetime, datetime]] = (),
    inlet_measured: bool = False,
    start_hold: Callable[[float | None], float] | None = None,
    running_hold: float = 0.0,
    running_starts: bool = False,
) -> tuple[Weighed, ...]:
    """Each of ``scenarios`` walked on every member of ``ensemble``:
    its draws and draw windows the member's inside its span
    (``_draws_in``, ``_windows_in``), its circulation and all else its
    own. The keyword inputs are ``simulate``'s, the same for
    every walk. Raises ``ValueError`` for an empty ensemble, or a
    scenario reaching outside a member's span: past it the draws are
    unknown, not none."""
    if not ensemble:
        raise ValueError("an ensemble has at least one member")
    for scenario in scenarios:
        for member in ensemble:
            if scenario.start < member.start or scenario.until > member.end:
                raise ValueError(
                    f"a scenario from {scenario.start.isoformat()} to "
                    f"{scenario.until.isoformat()} reaches outside the "
                    f"members' {member.start.isoformat()} to "
                    f"{member.end.isoformat()}"
                )
    out: list[Weighed] = []
    for scenario in scenarios:
        walks: list[MemberWalk] = []
        for member in ensemble:
            walk = simulate(
                scenario.model_copy(
                    update={
                        "loads": scenario.loads.model_copy(
                            update={
                                "draws": _draws_in(
                                    member.loads.draws,
                                    scenario.start,
                                    scenario.until,
                                ),
                                "windows": _windows_in(
                                    member.loads.windows,
                                    scenario.start,
                                    scenario.until,
                                ),
                            }
                        )
                    }
                ),
                params,
                recovery=recovery,
                tou_windows_in_force=tou_windows_in_force,
                withheld_windows=withheld_windows,
                inlet_measured=inlet_measured,
                start_hold=start_hold,
                running_hold=running_hold,
                running_starts=running_starts,
            )
            walks.append(_judged(member, walk, params))
        out.append(Weighed(walks=tuple(walks)))
    return tuple(out)


def _draws_in(
    draws: Sequence[Draw], start: datetime, until: datetime
) -> tuple[Draw, ...]:
    """The draws drawn in ``[start, until)``, one running across an edge
    cut to it at its own flow and per-draw volume: a shorter walk meets
    only its part of the member, and its domain only those draws."""
    out: list[Draw] = []
    for d in draws:
        end = d.at + timedelta(seconds=d.duration_s)
        # One shorter than the clock's resolution is all at ``at``.
        if d.duration_s <= 0.0 or end == d.at:
            if start <= d.at < until:
                out.append(d)
            continue
        a, b = max(d.at, start), min(end, until)
        if b <= a:
            continue
        if (a, b) == (d.at, end):
            out.append(d)
            continue
        sec = (b - a).total_seconds()
        out.append(
            Draw(
                at=a,
                gallons=d.gallons * sec / d.duration_s,
                per_draw_gal=(
                    d.per_draw_gal if d.per_draw_gal is not None else d.gallons
                ),
                duration_s=sec,
            )
        )
    return tuple(out)


def _windows_in(
    windows: Sequence[DrawWindow], start: datetime, until: datetime
) -> tuple[DrawWindow, ...]:
    """The windows overlapping ``[start, until)``, as ``draw_profile``
    keeps them for its span; one already open at ``start`` expects its
    draws from there."""
    return tuple(
        w
        if w.draws_until is None or w.draws_until >= start
        else w.model_copy(update={"draws_until": start})
        for w in windows
        if w.end > start and w.start < until
    )


def _judged(
    member: Member, walk: SimulationResult, params: HeaterParams
) -> MemberWalk:
    points = walk.points
    delivery = list(walk.delivery) or delivery_along(points, params)
    lows: list[float] = []
    cold = False
    cut = 0
    for a, b in member.long_draws:
        if a >= walk.until or b < walk.start or (b == walk.start and a < b):
            continue
        cut += a < walk.start or b > walk.until
        a, b = max(a, walk.start), min(b, walk.until)
        # A draw of no length is a step at its instant: judged through it.
        b = max(b, a + timedelta(microseconds=1))
        d = depletion(points, a, b, delivery, params.readiness)
        lows.append(d.min_f)
        cold = cold or d.depleted
    return MemberWalk(
        member=member,
        walk=walk,
        long_min_f=min(lows) if lows else None,
        cold=cold,
        cut_short=cut,
    )
