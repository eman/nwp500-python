"""Hot water circulated through an installation's plumbing on a
schedule: its runs as water through the tank, and its loss to the heat
book.

Some installations circulate hot water from the tank around their
plumbing and back, so a tap runs hot sooner. A run takes heat only
while it runs: the water returning to the bottom of the tank has cooled
in the pipe, and once the first ``CirculationParams.displaced_gal`` of
it has come back the tank loses nothing more to it, though the run still
carries hot water from the top to the bottom. The volume is an
effective one: at one installation a run kept taking heat as long as it
ran, and the fitted volume is above the typical run. With no runs
given, nothing is charged.

The runs are the caller's: a weekly schedule laid out as instants
(``sim_adapters.circulation``), a record of when it ran, or a run asked
for on demand. ``Circulation.known_until`` says how far they are known:
a span starting after it is not known, which charges nothing, while an
empty set of runs is a known-quiet circuit.

Two terms, kept apart on purpose:

- **To the tank** (``tank_physics.circulation_flows``): each run
  water through the tank at ``flow_gpm``, leaving the top and coming
  back at the bottom. The first of it comes back at the air where the
  heater stands plus ``CirculationParams.return_rest_offset_f``, where
  the return rests between runs: ``displaced_gal`` of it, scaled by the
  share that has cooled since the last run ended (``cooled_share``, on
  ``CirculationParams.return_cool_tau_h``); the rest comes back as hot
  as it left. Runs closer than ``RUN_GAP`` are one run: a restart
  displaces water the last run warmed, and ``displaced_gal`` is fitted
  on runs merged that way.
- **To the book** (``CirculationLoss``, a ``book.SpanLoss``): with
  ``CirculationParams.book_circuit_gal``, each run's gallons up to that
  volume from its start, each at the tank's upper probe less the air;
  without it, ``loss_btu_per_gal`` for every gallon circulated while a
  run is on, unsaturated. A span with a run on is not quiet, so the book
  does not re-anchor across it.
"""

import math
from collections.abc import Callable, Iterable, Sequence
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
    input, so the zone draws and the book's loss see the same runs
    wherever a walk is cut."""

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


#: The coldest air ``CirculationLoss.bound`` allows for, °F: the book's
#: own bound on the walk (``book.loss_ceiling_btu``) takes the same.
_COLDEST_AIR_F = -20.0


@dataclass(frozen=True)
class CirculationLoss:
    """The runs' pipe loss to the heat book (``book.SpanLoss``), over
    each span a run is on at the start of: with ``circuit_gal``
    (``CirculationParams.book_circuit_gal``), the gallons circulated since
    the start of its group (runs closer than ``gap``, ``merge_runs``)
    up to that volume, each at ``upper_f`` less ``air_at`` while they
    flow (the tank's upper zone is taken at ``upper_f`` throughout);
    without it, ``loss_btu_per_gal`` per gallon circulated. ``runs`` are
    the runs as given, not merged: a gap between two circulates
    nothing."""

    runs: Sequence[Run]
    flow_gpm: float
    loss_btu_per_gal: float
    circuit_gal: float | None = None
    upper_f: float = 0.0
    air_at: Callable[[datetime], float] | None = None
    gap: timedelta = RUN_GAP

    def __post_init__(self) -> None:
        # Runs that overlap or touch are one span of on-time: what both
        # cover circulates once.
        object.__setattr__(
            self, "runs", tuple(merge_runs(self.runs, timedelta(0)))
        )

    def edges(self, start: datetime, end: datetime) -> list[datetime]:
        return [x for run in self.runs for x in run if start < x < end]

    def _running(self, a: datetime, b: datetime) -> float:
        """Minutes a run was on over ``[a, b)``."""
        return sum(
            max(0.0, (min(r1, b) - max(r0, a)).total_seconds() / 60.0)
            for r0, r1 in self.runs
        )

    def _charged(
        self, start: datetime, end: datetime
    ) -> tuple[float, datetime] | None:
        """The gallons over ``[start, end)``, with a run on from
        ``start``, within its group's first ``circuit_gal``, and the
        middle of the time they flow; None with none."""
        if self.circuit_gal is None:
            return None
        group = next(
            (
                g
                for g in merge_runs(self.runs, self.gap)
                if g[0] <= start < g[1]
            ),
            None,
        )
        flow = max(self.flow_gpm, 0.0)
        if group is None or flow <= 0.0:
            return None
        before = flow * self._running(group[0], start)
        gal = flow * self._running(start, end)
        cap = self.circuit_gal
        priced = max(0.0, min(before + gal, cap) - min(before, cap))
        if priced <= 0.0:
            return None
        # The span starts with a run on, and its edges are the runs':
        # the charged gallons flow from its start.
        return priced, start + timedelta(minutes=priced / flow / 2.0)

    def loss(self, start: datetime, end: datetime) -> tuple[float, bool]:
        on = any(r0 <= start < r1 for r0, r1 in self.runs)
        if not on:
            return 0.0, False
        if self.circuit_gal is not None:
            charged = self._charged(start, end)
            if charged is None:
                return 0.0, True
            gal, mid = charged
            air = self.air_at(mid) if self.air_at is not None else 65.0
            return gal * WATER_BTU_PER_GAL_F * max(
                0.0, self.upper_f - air
            ), True
        hours = (end - start).total_seconds() / 3600.0
        # As the book's loss was fitted: per gallon, flow x minutes.
        return self.loss_btu_per_gal * (self.flow_gpm * hours * 60.0), True

    def bound(self, start: datetime, end: datetime) -> float:
        if self.circuit_gal is not None:
            flow = max(self.flow_gpm, 0.0)
            gal = 0.0
            for group in merge_runs(self.runs, self.gap):
                a, b = max(start, group[0]), min(end, group[1])
                if b <= a:
                    continue
                before = flow * self._running(group[0], a)
                cap = self.circuit_gal
                gal += max(
                    0.0,
                    min(before + flow * self._running(a, b), cap)
                    - min(before, cap),
                )
            return (
                gal
                * WATER_BTU_PER_GAL_F
                * max(0.0, self.upper_f - _COLDEST_AIR_F)
            )
        minutes = sum(
            max(0.0, (min(r1, end) - max(r0, start)).total_seconds() / 60.0)
            for r0, r1 in self.runs
        )
        return self.loss_btu_per_gal * (max(self.flow_gpm, 0.0) * minutes)
