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
- **To the book** (``CirculationLoss``, a ``book.SpanLoss``): with
  ``CirculationParams.book_circuit_gal``, each run's gallons up to that
  volume from its start, each at the tank's upper probe less the air;
  without it, ``loss_btu_per_gal`` for every gallon circulated while a
  run is on, unsaturated. A span with a run on is not quiet, so the book
  does not re-anchor across it.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from nwp500.sim.decay import Draw
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
        # The whole schedule's runs, merged once before any coast (the
        # caller's, ``api._circulation``): two runs a coast boundary
        # falls between are still one run, and one displaced volume.
        return run_draws(
            self.circulation.runs,
            start,
            end,
            self.displaced,
            self.flow_gpm,
            self.return_f,
        )


#: The coldest air ``CirculationLoss.bound`` allows for, °F: the book's
#: own bound on the walk (``book.loss_ceiling_btu``) takes the same.
_COLDEST_AIR_F = -20.0


@dataclass(frozen=True)
class CirculationLoss:
    """The runs' pipe loss to the heat book (``book.SpanLoss``), over
    each span a run is on at the start of: with ``circuit_gal``
    (``CirculationParams.book_circuit_gal``), the run's gallons up to
    that volume from its start, each at ``upper_f`` less ``air_at`` (the
    tank's upper zone is taken at ``upper_f`` throughout); without it,
    ``loss_btu_per_gal`` per gallon circulated."""

    runs: Sequence[Run]
    flow_gpm: float
    loss_btu_per_gal: float
    circuit_gal: float | None = None
    upper_f: float = 0.0
    air_at: Callable[[datetime], float] | None = None

    def edges(self, start: datetime, end: datetime) -> list[datetime]:
        return [x for run in self.runs for x in run if start < x < end]

    def _priced_gal(self, run: Run, start: datetime, end: datetime) -> float:
        """The run's gallons over ``[start, end)`` within its first
        ``circuit_gal``."""
        flow = max(self.flow_gpm, 0.0)
        a, b = max(start, run[0]), min(end, run[1])
        if b <= a or self.circuit_gal is None:
            return 0.0
        before = flow * (a - run[0]).total_seconds() / 60.0
        gal = flow * (b - a).total_seconds() / 60.0
        cap = self.circuit_gal
        return max(0.0, min(before + gal, cap) - min(before, cap))

    def loss(self, start: datetime, end: datetime) -> tuple[float, bool]:
        run = next((r for r in self.runs if r[0] <= start < r[1]), None)
        if run is None:
            return 0.0, False
        if self.circuit_gal is not None:
            mid = start + (end - start) / 2
            air = self.air_at(mid) if self.air_at is not None else 65.0
            gal = self._priced_gal(run, start, end)
            return gal * WATER_BTU_PER_GAL_F * max(
                0.0, self.upper_f - air
            ), True
        hours = (end - start).total_seconds() / 3600.0
        # As the book's loss was fitted: per gallon, flow x minutes.
        return self.loss_btu_per_gal * (self.flow_gpm * hours * 60.0), True

    def bound(self, start: datetime, end: datetime) -> float:
        if self.circuit_gal is not None:
            gal = sum(self._priced_gal(r, start, end) for r in self.runs)
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
