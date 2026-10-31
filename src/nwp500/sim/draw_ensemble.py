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
instant in the slot. A long draw's duration is the slot's minimum
(``long_min_s``) and a lognormal part matched to the published mean and
90th percentile above it; with no 90th percentile above the mean it is
the mean. Its volume goes with its duration at the slot's mean flow
(``volume_mean / duration_mean``), so the expected volume is the
published one. A short draw, whose spread is not published, is its
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
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from nwp500.sim.api import simulate
from nwp500.sim.delivery import delivery_along, depletion
from nwp500.sim.draw_forecast import (
    SLOT,
    ForecastSlot,
    draw_profile,
    forecast_loads,
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
    profile = draw_profile(slots, start, end)
    windows = forecast_loads(profile, start)[0].windows
    inside = [s for s in slots if start <= s.valid_at < end]
    return tuple(
        _member(inside, windows, end, np.random.default_rng([seed, k]))
        for k in range(count)
    )


def _member(
    slots: Sequence[ForecastSlot],
    windows: Sequence[DrawWindow],
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
            n = int(rng.poisson(rate))
            if n == 0:
                continue
            # Inside the span: a last slot cut short by ``end`` counts
            # whole, as ``draw_profile`` counts it, its draws in it.
            reach = min(SLOT, end - s.valid_at).total_seconds()
            offsets = rng.uniform(0.0, reach, n)
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
                at = s.valid_at + timedelta(seconds=float(off))
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
    )


def _long_seconds(
    s: ForecastSlot, mean_s: float, rng: np.random.Generator, n: int
) -> np.ndarray:
    """``n`` long draws' durations: the slot's minimum and a lognormal
    part with the mean and the 90th percentile above it; the mean when
    the spread is not known."""
    floor = float(s.long_min_s or 0.0)
    floor = min(floor, mean_s)
    m = mean_s - floor
    p90 = s.long_duration_p90_s
    sigma = _sigma(m, None if p90 is None else float(p90) - floor)
    if m <= 0.0 or sigma <= 0.0:
        return np.full(n, mean_s)
    mu = math.log(m) - sigma * sigma / 2.0
    return floor + rng.lognormal(mu, sigma, n)


def _sigma(mean: float, p90: float | None) -> float:
    """The lognormal's sigma with ``mean`` and 90th percentile ``p90``
    (both above the floor): the smaller root of
    ``z90 sigma - sigma^2 / 2 = ln(p90 / mean)``, at most ``z90``; 0
    with no 90th percentile above the mean."""
    if p90 is None or mean <= 0.0 or p90 <= mean:
        return 0.0
    r = math.log(p90 / mean)
    disc = _Z90 * _Z90 - 2.0 * r
    return _Z90 if disc <= 0.0 else _Z90 - math.sqrt(disc)


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
) -> tuple[Weighed, ...]:
    """Each of ``scenarios`` walked on every member of ``ensemble``:
    its draws and draw windows the member's, its circulation and all
    else its own. The keyword inputs are ``simulate``'s, the same for
    every walk. Raises ``ValueError`` for an empty ensemble."""
    if not ensemble:
        raise ValueError("an ensemble has at least one member")
    out: list[Weighed] = []
    for scenario in scenarios:
        walks: list[MemberWalk] = []
        for member in ensemble:
            walk = simulate(
                scenario.model_copy(
                    update={
                        "loads": scenario.loads.model_copy(
                            update={
                                "draws": member.loads.draws,
                                "windows": member.loads.windows,
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
            )
            walks.append(_judged(member, walk, params))
        out.append(Weighed(walks=tuple(walks)))
    return tuple(out)


def _judged(
    member: Member, walk: SimulationResult, params: HeaterParams
) -> MemberWalk:
    points = walk.points
    delivery = list(walk.delivery) or delivery_along(points, params)
    lows: list[float] = []
    cold = False
    for a, b in member.long_draws:
        if a >= walk.until or b < walk.start or (b == walk.start and a < b):
            continue
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
    )
