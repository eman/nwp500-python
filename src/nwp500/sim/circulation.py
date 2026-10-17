"""Hot water circulated through an installation's plumbing on a
schedule: its runs as the core's flowing draws, and its loss to the
heat book.

Some installations circulate hot water from the tank around their
plumbing and back, so a tap runs hot sooner. A run takes heat only
while it runs: the water returning to the bottom of the tank has cooled
in the pipe, and once the first ``CirculationParams.displaced_gal`` of
it has come back, hot water is circulating and the zones are charged
nothing more. With no runs given, nothing is charged.

The runs are the caller's: a weekly schedule laid out as instants
(``sim_adapters.circulation``), a record of when it ran, or a run asked
for on demand. ``Circulation.known_until`` says how far they are known:
a span starting after it is not known, which charges nothing, while an
empty set of runs is a known-quiet circuit.

Two terms, kept apart on purpose:

- **To the zones** (``CirculationDraws``, the core's ``FlowingDraws``):
  each run a flowing draw of ``min(flow x minutes, displaced_gal)``
  gallons from its start, at ``flow_gpm``, its inflow at the air where
  the heater stands, so it stops flowing once it has displaced the
  circuit. Runs closer than ``RUN_GAP`` are one run: a restart displaces
  water the last run warmed, and ``displaced_gal`` is fitted on runs
  merged that way.
- **To the book** (``CirculationLoss``, a ``book.SpanLoss``):
  ``loss_btu_per_gal`` for every gallon circulated while a run is on,
  unsaturated: the pipe's own loss while circulating. A span with a run
  on is not quiet, so the book does not re-anchor across it.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from nwp500.sim.decay import Draw

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


def merge_runs(runs: Iterable[Run], gap: timedelta = RUN_GAP) -> list[Run]:
    """``runs`` closer than ``gap`` joined into one, sorted."""
    merged: list[Run] = []
    for start, end in sorted(runs, key=lambda r: r[0]):
        if merged and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def run_draws(
    runs: Iterable[Run],
    start: datetime,
    end: datetime,
    displaced: float,
    flow_gpm: float,
    return_f: Callable[[datetime], float],
) -> list[Draw]:
    """The merged ``runs`` overlapping ``[start, end)`` as the core's
    flowing draws, in start order: each run whole, not clipped to the
    span (the core charges a run already under way from its own start),
    ``displaced_gal`` of its length in gallons at ``flow_gpm`` from its
    start to its end, its inflow ``return_f`` at each instant."""
    if displaced <= 0.0 or flow_gpm <= 0.0:
        return []
    draws: list[Draw] = []
    for run_start, run_end in sorted(
        (r for r in runs if r[1] > start and r[0] < end),
        key=lambda r: r[0],
    ):
        minutes = (run_end - run_start).total_seconds() / 60.0
        gallons = displaced_gal(minutes, displaced, flow_gpm)
        if gallons <= 0.0:
            continue
        draws.append(
            Draw(
                run_start,
                gallons,
                inflow_f=return_f,
                until=run_end,
                gpm=flow_gpm,
            )
        )
    return draws


@dataclass(frozen=True)
class Circulation:
    """The runs, and how far they are known: a span starting after
    ``known_until`` is not known (None: known throughout)."""

    runs: tuple[Run, ...] = ()
    known_until: datetime | None = None

    def over(self, start: datetime, end: datetime) -> list[Run] | None:
        """The runs overlapping ``[start, end)``, unclipped, in the order
        given; None when they are not known there."""
        if self.known_until is not None and start > self.known_until:
            return None
        if end <= start:
            return []
        return [r for r in self.runs if r[1] > start and r[0] < end]


@dataclass
class CirculationDraws:
    """The runs over each coast as flowing draws, for ``TankPhysics``'s
    ``flowing_draws``: the whole schedule merged first, then each merged
    run that overlaps a coast handed over whole, so a run is one run
    whichever coasts it spans (the core charges each coast its share, on
    the run's own clock). ``minutes`` adds up the on-time of every coast
    asked, for whether a run was charged."""

    circulation: Circulation
    displaced: float
    flow_gpm: float
    #: The return's temperature at an instant: the air at the heater.
    return_f: Callable[[datetime], float]
    minutes: float = 0.0

    def __call__(self, start: datetime, end: datetime) -> list[Draw]:
        if self.displaced <= 0.0:
            return []
        runs = self.circulation.over(start, end)
        if runs is None:
            return []
        if end > start:
            for run_start, run_end in runs:
                overlap = min(end, run_end) - max(start, run_start)
                self.minutes += max(0.0, overlap.total_seconds() / 60.0)
        # Merged over the whole schedule, not this coast's share of it:
        # two runs a coast boundary falls between are still one run, and
        # one displaced volume.
        return run_draws(
            merge_runs(self.circulation.runs),
            start,
            end,
            self.displaced,
            self.flow_gpm,
            self.return_f,
        )


@dataclass(frozen=True)
class CirculationLoss:
    """The runs' pipe loss to the heat book (``book.SpanLoss``):
    ``loss_btu_per_gal`` per gallon circulated, over each span a run is
    on at the start of."""

    runs: Sequence[Run]
    flow_gpm: float
    loss_btu_per_gal: float

    def edges(self, start: datetime, end: datetime) -> list[datetime]:
        return [x for run in self.runs for x in run if start < x < end]

    def loss(self, start: datetime, end: datetime) -> tuple[float, bool]:
        on = any(r0 <= start < r1 for r0, r1 in self.runs)
        if not on:
            return 0.0, False
        hours = (end - start).total_seconds() / 3600.0
        # As the book's loss was fitted: per gallon, flow x minutes.
        return self.loss_btu_per_gal * (self.flow_gpm * hours * 60.0), True

    def bound(self, start: datetime, end: datetime) -> float:
        minutes = sum(
            max(0.0, (min(r1, end) - max(r0, start)).total_seconds() / 60.0)
            for r0, r1 in self.runs
        )
        return self.loss_btu_per_gal * (max(self.flow_gpm, 0.0) * minutes)
