"""The core's extension points.

Each is a ``Protocol`` that receives values and returns values. No
extension is called for I/O: a client that fetches does so before it
builds one.

- ``RecoveryModel``: a learned correction to the physics recovery,
  such as a model fitted to a heater's own recoveries. With none, the
  core serves the physics alone.
- ``HeatLedger``: the tank's heat by bookkeeping, walked along the
  engine's path. A book kept from metered draws is one. With none,
  every draw is its own calibrated response.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from nwp500.sim.recovery import ModelDuration, RecoveryContext

if TYPE_CHECKING:
    from nwp500.sim.engine import Draw, HeatingInterval, PathPoint
    from nwp500.sim.tank_physics import Point


class RecoveryModel(Protocol):
    """A recovery's duration given the physics (``sim.recovery``)."""

    def duration(self, ctx: RecoveryContext) -> ModelDuration | None:
        """The served duration for ``ctx``, the start's hold included,
        with its confidence and reasons. ``ctx.physics`` is the
        integrator's duration, which the model may scale or replace.
        None declines: the physics is served alone."""
        ...


# ── The heat ledger ─────────────────────────────────────────────────


class Stand(Protocol):
    """Where a ledger's walk stood on reaching an instant: enough for it
    to resume there. The engine reads only the instant; the rest is the
    ledger's, handed back to it unread."""

    @property
    def at(self) -> datetime: ...


@dataclass(frozen=True)
class LedgerZones:
    """What the engine's lower-zone settling reads of a ledger's tank
    model (``sim.physics.draw.settled_lower_f``, ``unsettled_after_f``).

    The lower zone reads the ledger's front after a draw, and settles
    from there toward the colder of the front and its calibrated level
    on one time constant, never below the inlet."""

    #: The settling's time constant, minutes.
    settle_min: float
    #: The inlet the zone settles no lower than, until a walk says.
    inlet_f: float
    #: Whether every draw may mix the upper zone down (the ledger's
    #: rate is not zero): then no bound shows a draw cannot move it.
    mixes: bool


@dataclass(frozen=True)
class ZoneBound:
    """What a ledger needs to show, without walking, that the draws
    since its stand cannot take the upper zone through: the most
    standby and flowing draws can take over the span (``loss_bound``;
    a delivered draw is charged on its own) and the
    zone's range over it."""

    lost_btu: float
    upper_lo_f: float
    upper_hi_f: float
    #: When each heating running now began.
    running_since: tuple[datetime, ...] = ()


@dataclass(frozen=True)
class DrawTaken:
    """The draws taken at one instant, for ``HeatLedger.after_draw``."""

    at: datetime
    #: Their gallons together.
    gallons: float
    #: The tank before them.
    upper_f: float
    lower_f: float
    #: Their calibrated response from it (``Physics.draw``).
    drawn_upper_f: float
    drawn_lower_f: float
    #: A compressor recovery or an element run is under way.
    heating: bool
    #: The path since the stand, to ``at`` with the tank before them.
    path: Sequence[PathPoint]
    #: Every heating so far, those running taken to ``at``.
    intervals: Sequence[HeatingInterval]
    #: Every draw taken since the stand, these included.
    draws: Sequence[Draw]
    #: Their gallons together.
    drawn_gal: float
    stand: Stand | None
    #: None when the engine can already rule a bound out.
    bound: ZoneBound | None = None


@dataclass(frozen=True)
class AfterDraw:
    """A ledger's say over the zones after the draws at an instant."""

    #: The lower zone's reading: the front's, which the engine settles
    #: from (``LedgerZones``).
    lower_f: float
    #: The upper zone, where the ledger takes it below the draws' own
    #: response; None leaves their response.
    upper_f: float | None = None
    #: Taken past the zone's empty point, not mixed down only: the
    #: draws' heat is then the zone's.
    spent: bool = False
    #: Where its walk now stands, and the inlet it stood on; None for
    #: either: unchanged.
    stand: Stand | None = None
    inlet_f: float | None = None


@dataclass(frozen=True)
class DrawsAhead:
    """The draws ahead on a coast, for ``HeatLedger.upper_moves_at``."""

    #: The stand's instant now: where a walk stands for the next.
    at: datetime
    #: The path since the stand, then the coast's points past it.
    path: Sequence[PathPoint]
    #: Only to the first onset, when a bound may decide the rest;
    #: None: the whole path is walked.
    head: Sequence[PathPoint] | None
    intervals: Sequence[HeatingInterval]
    #: Every draw taken since the stand.
    taken: Sequence[Draw]
    #: The draws ahead, onset order, and their onsets.
    pending: Sequence[Draw]
    onsets: Sequence[datetime]
    #: The coast from now, and the tank's own response to a draw on it
    #: (``Physics.draw``).
    points: Sequence[Point]
    respond: Callable[[datetime, float, float, float], tuple[float, float]]
    stand: Stand | None
    #: For the draws after the first, with ``head``.
    bound: ZoneBound | None = None


@dataclass(frozen=True)
class UpperAhead:
    """The first onset ahead at which the ledger takes the upper zone
    below the draw's own response (None: none), and where its walk
    stands after looking."""

    at: datetime | None
    stand: Stand | None = None
    inlet_f: float | None = None


class HeatLedger(Protocol):
    """The tank's heat by bookkeeping: how much is left and where
    it lies, walked along the engine's path. A tank's two probes read
    a draw's cold water only once it reaches them; the ledger sees it
    from the onset.

    The engine asks it five things, all pure:

    - ``after_draw``: the tank after a draw, given the booked heat. At
      the clock (the zones' new readings), and ahead of it, where a
      coast must stop to take a draw at its instant: the lower zone
      (``front_moves_at``) and the upper (``upper_moves_at``);
    - ``loss_bound``: the most standby and draws can take from it over
      a span, which lets the engine skip a walk a bound decides.

    It holds nothing between calls: where its walk stood comes back as a
    ``Stand``, which the engine hands to the next call.
    """

    @property
    def zones(self) -> LedgerZones: ...

    def after_draw(self, q: DrawTaken) -> AfterDraw:
        """The zones after the draws at ``q.at``."""
        ...

    def front_moves_at(
        self, stand: Stand, drawn_gal: float, pending: Sequence[Draw]
    ) -> datetime | None:
        """The first onset in ``pending`` at which a bound cannot show
        the front still below the lower probe, from ``stand`` through
        ``drawn_gal`` gallons since and the pending draws to there."""
        ...

    def upper_moves_at(self, q: DrawsAhead) -> UpperAhead:
        """The first onset ahead at which the upper zone is taken below
        the draw's own response."""
        ...

    def loss_bound(
        self, start: datetime, end: datetime, upper_f: float
    ) -> float:
        """The most standby and flowing draws can take from the booked heat
        over ``[start, end]`` with no zone hotter than ``upper_f``, BTU. A
        delivered draw is charged on its own, not here."""
        ...
