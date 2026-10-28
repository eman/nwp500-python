"""The tank's coast read for the instants it crosses a threshold, and
the air at the heater as a function of the clock.

``threshold_crossing`` finds where the lower zone first falls below a
threshold on a walked path, its draws' drops landing at their own
instants (``Impulse``); ``AmbientSampler`` reads the air where the
heater stands at any instant. Every input arrives as a value.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import NamedTuple

import numpy as np
import pandas as pd

from nwp500.sim.units import DEFAULT_AMBIENT_F


class Impulse(NamedTuple):
    """A step change in the lower zone: an extraction's drop.

    ``at`` is the instant the drop is accounted at: a flowing draw's
    is the end of the integration step that charged it, a delivered
    draw's is its onset, which is in general *not* a trajectory
    instant.  ``lower_before`` is the lower zone just before the drop,
    ``lower_after`` just after; ``None`` means the trajectory's own
    value at ``at``, which is only meaningful for a drop that sits on
    a trajectory instant.
    """

    at: datetime
    lower_before: float
    lower_after: float | None = None


def threshold_crossing(
    trajectory: list[tuple[datetime, float, float]],
    threshold: float,
    impulses: Iterable[Impulse] | None = None,
) -> datetime | None:
    """When ``t_lower`` first falls below ``threshold``.

    Linearly interpolated inside the coast segment that contains the
    crossing, so the answer is not quantised to the trajectory's
    sample interval. Without that it could run a whole step late,
    which is more than the scheduler's use of it can absorb.

    **The curve between two trajectory points is a slide with drops in
    it.**  The tank coasts continuously, and each extraction lands as a
    step change at its own instant (a flowing draw's at the end of the
    step that charged it, a delivered draw's at its onset), so the path is
    coast, drop, coast, drop, coast.  The walk follows it in that
    order: a crossing that lies on a coast segment is interpolated
    over that segment, between the drops on either side of it, and a
    crossing a drop caused is reported at the drop and nowhere else.
    Interpolating through a drop would report a crossing minutes
    before anything happened; rounding a coast crossing up to the
    next grid point would report it up to a step late, which the
    scheduler cannot absorb.

    A start already below the threshold returns the starting instant,
    which is also what makes the degenerate single-point projection
    answer correctly rather than returning ``None``.

    Returns ``None`` when the tank stays above the threshold for the
    whole projection.
    """
    if not trajectory:
        return None
    if trajectory[0][2] < threshold:
        return trajectory[0][0]

    drops = sorted(impulses or (), key=lambda i: i.at)

    def interpolate(
        t0: datetime, lower0: float, t1: datetime, lower1: float
    ) -> datetime:
        span = lower0 - lower1
        if span <= 0:
            return t1
        return t0 + (t1 - t0) * ((lower0 - threshold) / span)

    for (t0, _, lower0), (t1, _, lower1) in pairwise(trajectory):
        cur_t, cur_lower = t0, lower0
        # A drop on the segment's start instant belongs to it (a draw
        # at a grid point is charged before the coast that follows),
        # and one on its end instant is the flowing accounting boundary.
        # A drop already walked from the previous segment's end is
        # seen again here with nothing left to cross, harmlessly.
        for drop in drops:
            if not t0 <= drop.at <= t1:
                continue
            if drop.lower_before < threshold:
                return interpolate(cur_t, cur_lower, drop.at, drop.lower_before)
            after = drop.lower_after
            if after is None:
                after = lower1 if drop.at == t1 else drop.lower_before
            if after < threshold:
                return drop.at
            cur_t, cur_lower = drop.at, after
        if lower1 < threshold:
            return interpolate(cur_t, cur_lower, t1, lower1)
    return None


class AmbientSampler:
    """Ambient temperature (the air at the heater) as a function of
    the clock.

    Built once per projection: the index is validated, cleaned and
    converted to seconds a single time, and every lookup after that is
    one `searchsorted`.  The per-call form, `_get_t_amb`, used to do
    all of that on every step, which was affordable at one lookup a
    step and is not at one per flowing draw's sub-step.

    **Ambient is a function of the clock, not of the step grid.**  The
    lookup used to return the *nearest* sample, and the step grid is
    anchored to the projection's own ``now``, so cutting a chain at a
    different instant moved every step start, moved which sample each
    step snapped to, and moved the answer.  That lookup was the
    dominant term in the chained-versus-single disagreement, ahead of
    the flowing charge.  Interpolating makes a split invisible to
    ambient for the same reason elapsed-portion pricing made it
    invisible to the flowing term.

    Ends are **clamped, never extrapolated**: a projection reaching past
    the last sample holds it flat rather than running a 26 °F daily
    swing off the end of the data, which is the failure mode that would
    matter and the one no test would catch at a flat ambient.
    """

    __slots__ = ("_base", "_stamps", "_values")

    def __init__(self, series: pd.DataFrame) -> None:
        self._stamps: np.ndarray | None = None
        # An absent column is a caller's mistake, not a missing reading:
        # it would coast every projection at the default air unannounced.
        if "ambient_f" not in series.columns:
            raise ValueError(
                "the ambient series has no 'ambient_f' column: pass the "
                "air at the heater, °F, or an empty frame with the column"
            )
        if series.empty:
            return

        # DatetimeIndex, not the bare Index the attribute is typed as:
        # subtracting a datetime from the latter has no defined result
        # type. Indexing one returns the bare type again, hence the
        # rewraps below.
        idx = pd.DatetimeIndex(series.index)
        values = series["ambient_f"].to_numpy(dtype=float)

        # Drop unusable rows rather than interpolating through them.  A
        # single NaN sample used to poison one nearest-neighbour cell;
        # it would now poison *both* bracketing intervals, and `nan`
        # flows straight through `t_bulk` into the trajectory and out
        # of the end state, and past any downstream guard whose `<=`
        # and `>=` are both False against it, so duration caps
        # silently stop arming.  `NaT` in the index does the same
        # through `searchsorted`.
        usable = np.isfinite(values) & ~pd.isna(idx)
        if not usable.all():
            idx, values = pd.DatetimeIndex(idx[usable]), values[usable]
            if len(idx) == 0:
                return

        if idx.tz is None:
            # Assumed UTC, matching every reader of these series.
            # Earlier this raised instead, so a caller handing back
            # *local* naive timestamps now reads ambient up to eight
            # hours out of phase (several °F on a 26 °F swing),
            # silently rather than loudly.  Guarded below rather than
            # left implicit.
            idx = idx.tz_localize(UTC)

        # `searchsorted` is only meaningful on a sorted index, and a
        # reader that changes its sort order would otherwise silently
        # corrupt every lookup rather than failing.
        if not idx.is_monotonic_increasing:
            # Stable, so duplicate timestamps keep their input order
            # and the tie below resolves the same way twice.
            order = np.argsort(idx.to_numpy(), kind="stable")
            idx, values = pd.DatetimeIndex(idx[order]), values[order]

        # Seconds from the first sample, never raw integer timestamps.
        # `DatetimeIndex.asi8` is *resolution-dependent*: pandas 2
        # gives a `datetime64[us]` index here and `Timestamp.value` is
        # always nanoseconds, so mixing them is a silent factor of 1000
        # that clamps every lookup to the last sample.  Subtraction
        # carries the units for us.
        # A plain datetime, not a Timestamp: `at` subtracts from it on
        # every call and that is now the projection's hot path.
        self._base = idx[0].to_pydatetime()  # pyright: ignore[reportAttributeAccessIssue]
        self._stamps = np.asarray(
            (idx - idx[0]) / pd.Timedelta(seconds=1), dtype=float
        )
        self._values = values

    @property
    def defaulted(self) -> bool:
        """Whether no usable reading was given (none, or all missing),
        so every lookup is ``DEFAULT_AMBIENT_F``."""
        return self._stamps is None

    def at(self, target: datetime) -> float:
        """Ambient temperature at ``target``, linearly interpolated."""
        if self._stamps is None:
            # Fallback to a reasonable ambient default
            return DEFAULT_AMBIENT_F
        stamps, values = self._stamps, self._values

        # Ensure target is tz-aware
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        want = (target - self._base).total_seconds()

        pos = int(np.searchsorted(stamps, want))
        if pos <= 0:
            return float(values[0])
        if pos >= len(stamps):
            return float(values[-1])

        lo, hi = pos - 1, pos
        span = stamps[hi] - stamps[lo]
        if span <= 0:  # duplicate timestamps
            return float(values[hi])
        weight = (want - stamps[lo]) / span
        return float(values[lo] + weight * (values[hi] - values[lo]))

    def outside(
        self, start: datetime, end: datetime, low: float, high: float
    ) -> list[tuple[datetime, datetime]]:
        """The spans of ``[start, end)`` with the air below ``low`` or at
        ``high`` and above, in time order: exact on the interpolated
        series, which is linear between its samples and flat past its
        ends."""
        if end <= start:
            return []
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        cuts = [start, end]
        if self._stamps is not None:
            for x in self._stamps:
                at = self._base + timedelta(seconds=float(x))
                if start < at < end:
                    cuts.append(at)
        cuts.sort()
        out: list[tuple[datetime, datetime]] = []

        def add(a: datetime, b: datetime) -> None:
            if b <= a:
                return
            if out and out[-1][1] == a:
                out[-1] = (out[-1][0], b)
            else:
                out.append((a, b))

        for a, b in pairwise(cuts):
            va, vb = self.at(a), self.at(b)
            pieces = [a, b]
            for level in (low, high):
                if (va - level) * (vb - level) < 0.0:
                    f = (level - va) / (vb - va)
                    pieces.append(a + (b - a) * f)
            pieces.sort()
            for p0, p1 in pairwise(pieces):
                mid = self.at(p0 + (p1 - p0) / 2)
                if mid < low or mid >= high:
                    add(p0, p1)
        return out


def compute_start_time(
    target_time: datetime,
    duration_minutes: float,
) -> datetime:
    """Compute when the compressor must start.

    start_at = target_time − duration_minutes.
    """
    return target_time - timedelta(minutes=duration_minutes)
