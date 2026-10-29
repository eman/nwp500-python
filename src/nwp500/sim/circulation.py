"""Hot water circulated through an installation's plumbing on a
schedule: its runs as water through the tank.

Some installations circulate hot water from the tank around their
plumbing and back, so a tap runs hot sooner. A run takes heat only
while it runs. The water first coming back to the tank is the pipe's,
cooled where it rested: ``CirculationParams.displaced_gal`` of it, the
pipe's volume. After it the tank's own water comes back, cooler by
what the pipe loses on the way round (``steady_share``, on
``CirculationParams.pipe_ua_btu_hr_f``). With no runs given, nothing
is charged.

The runs are the caller's: a weekly schedule laid out as instants
(``sim_adapters.circulation``), a record of when it ran, or a run asked
for on demand. ``Circulation.known_until`` says how far they are known:
a span starting after it is not known, which charges nothing, while an
empty set of runs is a known-quiet circuit.

**Through the tank** (``tank_physics.circulation_flows``): each run is
water through the tank at ``flow_gpm``, leaving the top and coming back
at the bottom. The first of it comes back at the air where the heater
stands plus ``CirculationParams.return_rest_offset_f``, where the return
rests between runs: ``displaced_gal`` of it, scaled by the share that
has cooled since the last run ended (``cooled_share``, on
``CirculationParams.return_cool_tau_h``); the rest comes back at the
rest plus ``steady_share`` of the top's lift over it. Water warmer than
the tank's bottom rises to its own level there
(``physics.stratified.flow``). Runs closer than ``RUN_GAP`` are one
run: a restart displaces water the last run warmed, and the return's
rest and cooling are fitted on runs merged that way.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from nwp500.sim.units import WATER_BTU_PER_GAL_F

#: A run: when it starts and when it ends.
Run = tuple[datetime, datetime]

#: Runs closer than this are one run.
RUN_GAP = timedelta(minutes=10)


def displaced_gal(minutes: float, displaced: float, flow_gpm: float) -> float:
    """Gallons a run has displaced after ``minutes`` of its own time:
    ``min(flow x minutes, displaced)``; 0 with no circuit or no flow."""
    if displaced <= 0.0 or minutes <= 0.0 or flow_gpm <= 0.0:
        return 0.0
    return min(flow_gpm * minutes, displaced)


def cooled_share(rest_hours: float | None, cool_tau_h: float) -> float:
    """The share of a run's displaced water that has cooled to the
    return's rest, after ``rest_hours`` since the last run ended: the
    pipe the last run warmed cools toward rest on ``cool_tau_h``. 1 with
    no earlier run known, or no time constant (cooled at once)."""
    if rest_hours is None or cool_tau_h <= 0.0:
        return 1.0
    return 1.0 - math.exp(-max(rest_hours, 0.0) / cool_tau_h)


def steady_share(ua_btu_hr_f: float, flow_gpm: float) -> float:
    """The share of the tank's lift over the return's rest that the
    tank's own water keeps on its way round the pipe, at ``flow_gpm``:
    ``exp(−UA / (ṁ·c))``, the pipe a heat exchanger with surroundings
    at the rest. 1 with no loss; 0 with no flow."""
    if ua_btu_hr_f <= 0.0:
        return 1.0
    if flow_gpm <= 0.0:
        return 0.0
    return math.exp(-ua_btu_hr_f / (flow_gpm * 60.0 * WATER_BTU_PER_GAL_F))


def merge_runs(runs: Iterable[Run], gap: timedelta = RUN_GAP) -> list[Run]:
    """``runs`` closer than ``gap`` joined into one, sorted."""
    merged: list[Run] = []
    for start, end in sorted(runs, key=lambda r: r[0]):
        if merged and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


@dataclass(frozen=True)
class Circulation:
    """The runs, and how far they are known: a span starting after
    ``known_until`` is not known (None: known throughout). The runs are
    held merged within ``gap`` (``merge_runs``), once, over the whole
    input, so the tank sees the same runs wherever a walk is cut."""

    runs: tuple[Run, ...] = ()
    known_until: datetime | None = None
    gap: timedelta = RUN_GAP

    def __post_init__(self) -> None:
        object.__setattr__(self, "runs", tuple(merge_runs(self.runs, self.gap)))

    def over(self, start: datetime, end: datetime) -> list[Run] | None:
        """The runs overlapping ``[start, end)``, unclipped, in the order
        given; None when they are not known there."""
        if self.known_until is not None and start > self.known_until:
            return None
        if end <= start:
            return []
        return [r for r in self.runs if r[1] > start and r[0] < end]
