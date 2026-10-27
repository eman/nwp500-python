"""What the heater does under a candidate plan.

The water heater scheduler proposes plans and scores what this module
says each one does. It holds no heater behaviour of its own.

**The engine is the event walk.** Every rule that decides when this
heater starts, stops, which mode is in force and which setpoint is the
firmware's, and lives in the core's state machine,
``sim/controller.py``: its own triggers (``sim/tou_triggers.py``),
starts caused by writes, reservation entries, the TOU cap judged at a
recovery's end, mode writes held in a window and an element mode
dropped at one, the elements, the restart lockout and a start's hold.
The engine finds the next event, moves the tank to it with the physics,
hands it to ``controller.transition`` and carries out the actions it
returns. What it keeps is the walk: where to
stop, the physics between stops, how far a recovery and an element lift
the tank, the withheld draw windows, the draws, and the booked heat
(below).

The heater takes ``entries``, each a minute, a mode and a setpoint, and
when it was written: it fires each in its minute, at the minute's start,
or at once when written during it (``Write.fires_at``). An entry that
cannot fire in the walk (its minute over when written, or before the
walk's start) is the caller's error. The engine knows no plan: what
writes the entries, and why, is the caller's (a caller may write one
per segment of an intent, at its start minute, as given). A plan's
``tou`` command sets the switch at its adoption, the walk's start: the
caller passes the windows it leaves (none for ``tou`` off).

The physics is injected (``Physics``) so the walk can be tested on its
own; the caller supplies the core's calibrated coast and recovery
(``sim.tank_physics.TankPhysics``). The
engine owns the draws: it hands each coast the ones whose onsets it
spans and splits a recovery at the others, so every draw is taken
exactly once whichever kind of segment it falls in. The element is the
engine's own arithmetic (constant rates, from ``ElementParams``), laid
over whichever segment it runs in.

**The booked heat at a draw (2026-10-03).** A draw's calibrated
response barely moves the upper zone, as the probe barely moves on an
ordinary draw; when the cold front reaches the probe it falls tens of
degrees, and nothing reading the zone (the triggers) saw it. With
a ``ledger`` (``sim.extensions.HeatLedger``: the tank's heat by
bookkeeping, walked along the path so far), each draw also asks it
(``after_draw``): where the booked heat the draw leaves is near or past
the zone's empty point, the zone goes down to the ledger's. A coast
stops at such a draw to take it at its instant, so the step is a point
on the path; a recovery it lands in is predicted afresh from the zone it
leaves. Without a ledger, every draw is its own response, as before.
*(Later that day: before the point the zone also mixes down, faster the
less booked heat is left; so every draw with a ledger that mixes
(``LedgerZones.mixes``) may move it, and no bound skips the walk.)*

**The lower zone at a draw.** Every draw takes the lower zone by its
calibrated response at its onset, with a ledger or without one: the
lower probe falls on every draw at once, by about the response, and
neither rebounds nor keeps falling after it. The ledger has no say over
the lower zone.

**Raw writes (calibration only).** ``raw_writes`` replays recorded
setpoint and mode writes as they were made, at their instants and values,
not as entries: no quantisation.
The heater's response to each is the same as to an entry (the start it
causes, the TOU cap, a mode held in a window), which is what a
reconciliation against the record tests.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Literal

from nwp500.sim import controller as ctl
from nwp500.sim.controller import (
    HEAT_PUMP,
    TOU_CAP_PROJECTED,
    ModeEnd,
    Owner,
    Source,
    Start,
    StopReason,
    Tank,
    judge_cap,
    trigger_ahead,
    upper_on_crossing,
    wake_times,
    window_at,
)
from nwp500.sim.decay import Impulse
from nwp500.sim.extensions import (
    DrawsAhead,
    DrawTaken,
    HeatLedger,
    Stand,
    ZoneBound,
)
from nwp500.sim.params import ControllerParams, ElementParams
from nwp500.sim.physics.compressor import MAX_MINUTES
from nwp500.sim.physics.element import ElementMode, HeaterMode
from nwp500.sim.physics.element import coast_f as earned_coast_f
from nwp500.sim.tank_physics import (
    Coast,
    Delivered,
    Heat,
    Physics,
    Point,
    point_at,
)
from nwp500.sim.tou_triggers import Window

#: A draw the engine walks: delivered at the inlet, its onset and its
#: delivered gallons (the core's ``Draw(at, gallons)``).
Draw = Delivered

#: The heater's setpoint range as the model knows it: the NWP500's
#: 104.9-149.9 °F. No plan declaration carries its own bounds; the
#: heater and this library enforce the device's real limits. A caller
#: rejects a plan with a setpoint outside it: the simulation cannot run
#: it.
HEATER_SETPOINT_MIN_F = 104.9
HEATER_SETPOINT_MAX_F = 149.9

#: The smallest step the engine takes: "at this instant", for draws.
_INSTANT = timedelta(microseconds=1)
#: An entry's minute: the span it fires in.
_ENTRY_MINUTE = timedelta(minutes=1)
#: Draws this long before a recovery's start are the recovery model's
#: ``draw_load``: its lead window for draws.
DRAW_LEAD = timedelta(minutes=30)
#: The deficit ``draw_load`` is divided by is floored here, °F, as the
#: recovery model's fit does.
_MIN_LOAD_DEFICIT_F = 1.0
#: A walk that has not reached the horizon after this many steps is a
#: bug, not a long simulation (a week of 10-minute events is ~1,000).
_MAX_STEPS = 20_000

#: What a write is: a reservation entry, or a direct write replayed.
Purpose = Literal["entry", "raw"]
#: What the heater did with an entry: ``fired`` in its minute;
#: ``skipped`` (its minute came in Vacation or powered off); ``pending``
#: (it fires at or after the walk's end).
EntryOutcome = Literal["fired", "pending", "skipped"]

# ── Inputs ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Entry:
    """A reservation entry on the heater's list: at its minute it sets
    the mode and the setpoint, both (the device's schedule, in the
    feature's mode names). ``written_at`` is when it was written to the
    device: the heater fires it in its minute (``Write.fires_at``); one
    that could not fire in the walk is refused. ``id`` is carried to
    what it causes as ``serves``."""

    at: datetime
    mode: HeaterMode
    setpoint_f: float
    written_at: datetime
    id: str | None = None


@dataclass(frozen=True)
class RawWrite:
    """A write replayed as it was made (calibration only): a
    setpoint, a mode (the feature's names), or both at one instant. At
    one instant every setpoint applies before every mode, whichever
    write carries it, as an entry's do (``controller.RawWrites``). ``id``
    is carried to what it causes as ``serves``."""

    at: datetime
    setpoint_f: float | None = None
    mode: HeaterMode | None = None
    id: str | None = None


@dataclass(frozen=True)
class Heater:
    """The device's own settings and schedule, as read now
    (``controller.Settings``, with the mode at the start). How far short
    a recovery ending in a window stops is ``ControllerParams.tou_cap_f``."""

    #: The lower zone's turn-on setting; None when unreadable, which
    #: disables the lower trigger.
    hp_lower_on_f: float | None
    #: TOU windows over the horizon, from the device's schedule.
    tou_windows: tuple[Window, ...] = ()
    #: VACATION or POWER_OFF: nothing starts. In Vacation no entry
    #: fires: the device skips each as its minute passes, and does not
    #: run it late; powered off (``powered_off``) an entry fires and
    #: turns the heater on (a device test, 2026-09-24).
    heating_disabled: bool = False
    #: The heater is powered off, which is why heating is disabled.
    powered_off: bool = False
    #: The mode the heater is in at the start, in the feature's names.
    mode: HeaterMode = HEAT_PUMP
    #: The element model (``sim/physics/element.py``).
    element: ElementParams = field(default_factory=ElementParams)


# ── Physics, injected ───────────────────────────────────────────────

# ``Point``, ``Coast``, ``Heat`` and the ``Physics`` protocol are the
# core's (``sim.tank_physics``), imported above: the caller supplies
# the core's ``TankPhysics``.


# ── Outputs ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PathPoint:
    at: datetime
    upper_f: float
    lower_f: float
    setpoint_f: float
    heating: bool
    #: The compressor's electricity over the interval ending here.
    input_wh: float | None
    #: The element's over the same interval.
    element_wh: float = 0.0
    #: The mode in force over the interval, in the feature's names.
    mode: HeaterMode = HEAT_PUMP


@dataclass
class HeatingInterval:
    start: Start
    end: datetime
    #: The setpoint in force when it started: what it set out to reach.
    #: A write during it can move or end it; ``stop`` says which.
    target_f: float
    capped: bool
    stop: StopReason
    #: Electricity over the interval, the start's hold and the run-on
    #: included (the compressor's performance map, or the element's
    #: rating); None when a recovery could not price it.
    input_wh: float | None
    #: Lowest confidence of the recoveries it was built from; None for an
    #: element, whose model carries ``element_model_small_n`` instead.
    confidence: float | None
    #: The setpoint in force when it ended, which a write may have moved.
    final_target_f: float = 0.0
    #: What heated: the compressor, or an element.
    source: Source = "compressor"
    #: An element's zone, ``upper`` or ``lower``.
    zone: Literal["upper", "lower"] | None = None


@dataclass
class Write:
    """An entry on the heater's list, or a raw write. An entry carries
    the whole state, mode and setpoint; a raw write what it set
    (``setpoint_f`` None when it left the setpoint alone)."""

    #: When it fires: the entry's minute, or the raw write's instant.
    at: datetime
    setpoint_f: float | None
    mode: HeaterMode | None
    owner: Owner
    purpose: Purpose
    #: The entry's ``id``, or the raw write's.
    serves: str | None
    #: When it was written to the device.
    written_at: datetime
    #: What the heater did with it (``EntryOutcome``).
    outcome: EntryOutcome = "pending"

    @property
    def fires_at(self) -> datetime:
        """When the heater fires it: an entry in its minute, at the
        minute's start or, written during the minute, as it is written
        (the device fires an entry on its first poll in the minute,
        02:08:02 on 2026-09-20's reservation run; a write during the
        minute firing at once is *assumed*); a raw write at its instant.
        A property, not a field: the held engine outputs stay as they
        were."""
        return max(self.at, self.written_at)


@dataclass
class ModeWrite:
    """A mode written to the heater, and what became of it."""

    at: datetime
    mode: HeaterMode
    owner: Owner
    serves: str | None
    #: When it took effect: at once, at the window's end if it was held,
    #: or never (None).
    took_at: datetime | None = None
    #: Written inside a TOU window and not taken there.
    held: bool = False
    #: A later mode write withdrew it while it was held.
    withdrawn_at: datetime | None = None


@dataclass
class ModeInterval:
    """The mode in force from ``start`` to ``end``."""

    start: datetime
    end: datetime
    mode: HeaterMode
    #: How it ended: ``write``, ``dropped`` (the heater's own), or
    #: ``horizon``.
    ended_by: ModeEnd = "horizon"


@dataclass
class Simulation:
    points: list[PathPoint]
    heating: list[HeatingInterval]
    writes: list[Write]
    reasons: list[str]
    mode_writes: list[ModeWrite] = field(default_factory=list)
    modes: list[ModeInterval] = field(default_factory=list)
    #: Each compressor recovery that reached its target, or the cap
    #: short of it: when, and the setpoint it heated to. A write ending
    #: a recovery with the lower zone already at the new setpoint
    #: reaches that one.
    reached: list[tuple[datetime, float]] = field(default_factory=list)
    #: Each element mode the heater dropped at a window: when, and
    #: the mode. One dropped at the walk's start leaves no interval in
    #: ``modes``, so it is listed here.
    drops: list[tuple[datetime, HeaterMode]] = field(default_factory=list)

    @property
    def starts(self) -> list[Start]:
        return sorted((h.start for h in self.heating), key=lambda s: s.at)


class SimulationError(Exception):
    """A recovery the physics could not give."""


# ── Helpers ─────────────────────────────────────────────────────────

#: The heater's setpoint resolution, °C: the NWP500 holds a setpoint in
#: half degrees Celsius, so 146 °F is held as 146.3 (2026-09-20).
SETPOINT_RESOLUTION_C = 0.5


def quantise(f: float, resolution_c: float = SETPOINT_RESOLUTION_C) -> float:
    """``f`` as the device will hold it: to the nearest ``resolution_c``
    in °C. 146 °F is held as 146.3, as the device did on
    2026-09-20."""
    if resolution_c <= 0.0:
        return f
    c = (f - 32.0) / 1.8 / resolution_c
    return round(math.floor(c + 0.5) * resolution_c * 1.8 + 32.0, 2)


def _slice(points: Sequence[Point], a: datetime, b: datetime) -> list[Point]:
    """The path from ``a`` to ``b``: the state at ``a`` (no energy), the
    elements between, and the state at ``b``. An interval cut by ``a``
    or ``b`` keeps only its share of energy, in proportion to time, so
    consecutive slices never count an interval twice."""
    out = [replace(point_at(points, a), input_wh=0.0)]
    for p0, p1 in pairwise(points):
        lo, hi = max(p0.at, a), min(p1.at, b)
        if hi <= lo:
            continue
        span = (p1.at - p0.at).total_seconds()
        share = (hi - lo).total_seconds() / span
        state = p1 if hi == p1.at else point_at(points, hi)
        out.append(
            Point(
                hi,
                state.upper_f,
                state.lower_f,
                None if p1.input_wh is None else p1.input_wh * share,
            )
        )
    return out


def _energy(points: Sequence[Point]) -> float | None:
    total = 0.0
    for p in points[1:]:
        if p.input_wh is None:
            return None
        total += p.input_wh
    return total


def _power(points: Sequence[Point]) -> float | None:
    """Mean electrical power over a path's last interval, W."""
    for p0, p1 in zip(points[-2::-1], points[::-1], strict=False):
        hours = (p1.at - p0.at).total_seconds() / 3600.0
        if hours > 0:
            return None if p1.input_wh is None else p1.input_wh / hours
    return None


def floor_minute(at: datetime) -> datetime:
    """``at`` truncated to its minute: a reservation entry's minute."""
    return at.replace(second=0, microsecond=0)


# ── The engine ──────────────────────────────────────────────────────


@dataclass
class _Cycle:
    """The recovery running now.

    Its recovery is predicted **once**, from where the cycle began (the
    origin), to each target it is asked for. A draw, a pause or a write
    that moves the tank does not re-predict: the tank is placed back on
    that one served path at the instant its lower zone matches, and the
    path continues from there. Re-predicting from mid-recovery states
    stretched a 130-minute recovery to 155 minutes when split every ten
    minutes, because the recovery model is fitted on whole cycles. Only
    a tank colder than the origin needs a new origin.
    """

    start: Start
    #: The setpoint whose recovery this is.
    setpoint_f: float
    origin: tuple[datetime, float, float]
    #: The origin's served path to each target asked for, unshifted.
    bases: dict[float, Heat]
    #: The path from now to where this recovery ends.
    heat: Heat
    capped: bool
    input_wh: float | None = 0.0
    confidence: float = 1.0
    #: Paused over a withheld draw window until this instant.
    paused_until: datetime | None = None
    #: Running power, for charging a pause, W.
    power_w: float | None = None
    #: Its entry in ``heating``.
    interval: HeatingInterval | None = None
    #: The hold its start began with, and what was left of
    #: it at the origin: a recovery predicted afresh after a draw keeps
    #: only the rest of it.
    hold_total: float = 0.0
    hold_minutes: float = 0.0
    #: The recovery model's ``draw_load`` for the draws recorded before
    #: the start, while the origin is the recorded tank; 0.0 once
    #: it is predicted afresh, or for a recovery the walk started.
    lead_load: float = 0.0


@dataclass
class _Element:
    """An element running now: the engine's arithmetic at the fitted
    rate, laid over whichever segment it runs in."""

    zone: Literal["upper", "lower"]
    interval: HeatingInterval
    #: °F per minute in its zone.
    rate: float
    #: When it reaches its off point at that rate (the setpoint, or
    #: Energy Saver's upper element's short of it), from the tank now;
    #: recomputed at every boundary, as draws and writes move it.
    end: datetime
    #: When its zone starts to rise: its on-edge plus the dead time
    #: for an upper element (``ElementParams.upper_dead_time_min``);
    #: it is charged from the on-edge. The on-edge itself for the lower
    #: element.
    live_at: datetime
    #: Minutes it has run outside a withheld window, from its on-edge,
    #: the dead time's included: the heat in transit when it stops is
    #: at most its last dead time's worth of them (``coast_f``).
    credited_min: float = 0.0
    #: Its off point (``controller.ElementRetarget``), once set.
    off: float | None = None


def _at_lower(points: Sequence[Point], lower: float) -> datetime | None:
    """The instant on ``points`` at which the lower zone rises past
    ``lower``: where the path leaves it, not where it first reaches it.
    On a path that holds a temperature for a while (a recovery model
    whose path begins with dead time) the two differ, and placing a tank at
    the first would replay the hold at every draw. None when the path
    never rises past it."""
    found: datetime | None = None
    for p0, p1 in pairwise(points):
        if p0.lower_f <= lower < p1.lower_f:
            f = (lower - p0.lower_f) / (p1.lower_f - p0.lower_f)
            found = p0.at + (p1.at - p0.at) * f
    return found


def _shift(points: Sequence[Point], by: timedelta) -> list[Point]:
    return [replace(p, at=p.at + by) for p in points]


class _Engine:
    def __init__(
        self,
        *,
        start: datetime,
        upper_f: float,
        lower_f: float,
        running: bool,
        until: datetime,
        setpoint_f: float,
        entries: Sequence[Entry],
        heater: Heater,
        physics: Physics,
        draws: Sequence[Draw],
        withheld_windows: Sequence[Window],
        marks: Sequence[datetime] = (),
        element_running: bool = False,
        element_running_since: datetime | None = None,
        raw_writes: Sequence[RawWrite] = (),
        stopped_at: datetime | None = None,
        heated_at: datetime | None = None,
        start_hold: Callable[[float | None], float] | None = None,
        running_hold: float = 0.0,
        lead_draws: Sequence[Draw] = (),
        ledger: HeatLedger | None = None,
        controller: ControllerParams | None = None,
    ) -> None:
        self.t = start
        #: The booked heat along the path so far, which takes the upper
        #: zone through a draw that spends it (``_follow_ledger``); None,
        #: the draw's own response alone.
        self.ledger = ledger
        #: Where the ledger's walk stood at the clock when last walked:
        #: each walk resumes there, so a day is walked once.
        self.ledger_carry: Stand | None = None
        #: Whether a draw's upper zone mixes down above the front: then
        #: no bound shows a draw cannot move it, since the draw's own
        #: response is not bounded below.
        self._mixing = ledger is not None and ledger.zones.mixes
        #: The drop of the draws ``_coast_draw`` last took at their
        #: instant: the coast after them starts below it, so the trigger
        #: search there is handed it (Energy Saver's release).
        self._drop: Impulse | None = None
        #: Every draw taken so far, onset order: what the ledger prices.
        self.taken: list[Draw] = []
        #: Draws recorded before the start, for the first recovery if it
        #: begins within ``DRAW_LEAD`` of them: the recovery model's
        #: input, since the recorded tank is what its training rows read.
        self.recorded_lead: list[Draw] = [d for d in lead_draws if d[0] < start]
        #: The rest of a running compressor's hold at the start, minutes.
        self.running_hold = running_hold if running else 0.0
        self.upper = upper_f
        self.lower = lower_f
        self.running = running
        self.element_running = element_running
        self.element_running_since = element_running_since
        self.until = until
        self.ep = heater.element
        #: The windows TOU enforces: the device's, while the switch is
        #: on (the caller passes none for a plan's ``tou`` off).
        self.windows: tuple[Window, ...] = tuple(heater.tou_windows)
        #: The firmware (``sim/controller.py``): its numbers, the
        #: heater's settings, and its state, which only
        #: ``controller.transition`` moves (``_dispatch``).
        self.params = (
            controller if controller is not None else (ControllerParams())
        )
        self.settings = ctl.Settings(
            hp_lower_on_f=heater.hp_lower_on_f,
            tou_windows=self.windows,
            heating_disabled=heater.heating_disabled,
            powered_off=heater.powered_off,
            element=heater.element,
            start_hold=start_hold,
        )
        #: Where the air at the heater is outside the heat pump's
        #: operating range (``ControllerParams.hp_air_range_f``), from
        #: the physics' air; none from a physics that cannot say.
        outside = getattr(physics, "air_outside", None)
        self.air_out: list[Window] = (
            []
            if outside is None
            else outside(start, until, *self.params.hp_air_range_f)
        )
        available = self._available(start)
        #: The tank was below the heat pump's water range with no element
        #: since to heat it past: one heating it runs to its off point.
        self._cold = lower_f < self.params.hp_water_range_f[0]
        self.state = ctl.initial_state(
            at=start,
            setpoint_f=setpoint_f,
            mode=heater.mode,
            running=running,
            stopped_at=stopped_at,
            params=self.params,
            hp_available=available,
        )
        self.reasons: set[str] = set()
        if (
            not available
            and heater.mode in ctl.COMPRESSOR_MODES
            and not (heater.heating_disabled or heater.powered_off)
        ):
            self.reasons.add(ctl.HEAT_PUMP_UNAVAILABLE)
        #: The setpoint and the mode in force as the path records them,
        #: moved by the controller's actions as they are carried out.
        self.sp = setpoint_f
        self.mode: HeaterMode = heater.mode
        self.mode_writes: list[ModeWrite] = []
        self.modes: list[ModeInterval] = [ModeInterval(start, until, self.mode)]
        self.element: _Element | None = None
        #: An element has heated the upper zone in the running compressor
        #: cycle: its gain is kept against the cycle's own path.
        self.hold_upper = False
        #: °F the upper zone still coasts up, uncharged, at
        #: ``coast_rate`` after an element that switches off short of the
        #: setpoint has stopped at its off point (Energy Saver's upper
        #: element): at most the off deficit, 1.62 °F, and at most what
        #: the run itself put in (``sim.physics.element.coast_f``). Inside a
        #: withheld draw window it runs out uncredited, as the element's
        #: and the compressor's heat does there.
        self.coast_f = 0.0
        self.coast_rate = 0.0
        #: When that coast is done: a boundary, so the path has a point
        #: where the zone reaches the setpoint.
        self.coast_end: datetime | None = None
        self.physics = physics
        #: Draws not yet taken, onset order. Each is removed as a coast
        #: or a recovery takes it.
        self.draws = sorted(d for d in draws if start <= d[0] < until)
        self.withheld = sorted(withheld_windows)
        self.path: list[PathPoint] = [
            PathPoint(
                start,
                upper_f,
                lower_f,
                setpoint_f,
                running,
                0.0,
                mode=heater.mode,
            )
        ]
        self.heating: list[HeatingInterval] = []
        self.cycle: _Cycle | None = None
        #: Instants the path must carry an element at, exactly (the
        #: forecast's draw windows): not the feature's events, only stops.
        self.marks = {m for m in marks if start < m < until}
        #: Writes replayed as made, in time order; each is removed as it
        #: lands, and those at one instant land together, setpoints
        #: first.
        self.raw: list[RawWrite] = sorted(
            (w for w in raw_writes if start <= w.at < until),
            key=lambda w: w.at,
        )
        #: When the tank last heated, by the compressor or an element,
        #: which a run's standby pool counts from: the given
        #: instant, else the compressor's last stop in force at the
        #: start, then the simulation's own stops of either.
        self.last_heated: datetime | None = (
            heated_at
            if heated_at is not None
            else self.state.compressor.last_stop
        )

        #: Each compressor recovery's arrival at its target (``reached``),
        #: and each mode the heater dropped (``drops``).
        self.reached: list[tuple[datetime, float]] = []
        self.drops: list[tuple[datetime, HeaterMode]] = []
        #: Every entry, in time order, and those still to fire, each
        #: with the instant it fires (``Write.fires_at``) and its place
        #: in ``writes``.
        self.writes: list[Write] = []
        self.queue: list[tuple[datetime, int]] = []
        for e in sorted(entries, key=lambda e: e.at):
            w = Write(
                e.at,
                e.setpoint_f,
                e.mode,
                "plan",
                "entry",
                e.id,
                e.written_at,
            )
            fires = w.fires_at
            if fires >= e.at + _ENTRY_MINUTE or fires < start:
                raise ValueError(
                    f"entry {e.id!r} at {e.at.isoformat()} cannot fire in a "
                    f"walk from {start.isoformat()}: its minute is over"
                )
            self.queue.append((fires, len(self.writes)))
            self.writes.append(w)

    # ── the controller ──

    def _tank(self) -> Tank:
        return Tank(self.upper, self.lower)

    def _water_ok(self, lower: float) -> bool:
        low, high = self.params.hp_water_range_f
        return low <= lower < high

    def _available(self, at: datetime) -> bool:
        """Whether the heat pump is inside its operating range at ``at``
        with the lower zone as it is now."""
        if any(a <= at < b for a, b in self.air_out):
            return False
        return self._water_ok(self.lower)

    def _check_availability(self) -> bool:
        """Tell the controller when the heat pump has left or re-entered
        its operating range (``controller.HeatPumpAvailability``);
        whether it has left it here."""
        available = self._available(self.t)
        if self.lower < self.params.hp_water_range_f[0]:
            self._cold = True
        elif self.element is None or self.state.hp_available:
            self._cold = False
        if (
            available
            and not self.state.hp_available
            and self._cold
            and self.element is not None
        ):
            # The water came up past the range's bottom under an element:
            # it runs to its off point first, whatever the air did.
            available = False
        if available != self.state.hp_available:
            self._dispatch(
                ctl.HeatPumpAvailability(
                    at=self.t, tank=self._tank(), available=available
                )
            )
            return not available
        return False

    def _water_crossing(self, points: Sequence[Point]) -> datetime | None:
        """The first point of a coast past a bound of the heat pump's
        water range, where its availability changes (at most a coast
        step after the crossing, and on its far side); None when the
        coast crosses none, or an element runs (its rise is laid over
        the coast, and its end is a boundary)."""
        if self.element is not None:
            return None
        for p0, p1 in pairwise(points):
            if self._water_ok(p0.lower_f) != self._water_ok(p1.lower_f):
                return p1.at
        return None

    def _element_done(
        self, points: Sequence[Point], *, heat_path: bool = False
    ) -> datetime | None:
        """Where the running element's zone, as ``_overlay`` lifts it on
        ``points``, first reaches the element's off point: before the end
        its rate alone gives (``_element_end``) where something else lifts
        the zone too, the compressor on a cycle's served path, a closing
        gap the lower zone, an inverted tank's mix the upper
        (``decay.project_decay``). Linear between the points but for a
        coast's mix, taken at once. None when it does not."""
        el = self.element
        if el is None or el.off is None:
            return None
        upper = el.zone == "upper"
        credited = self._withheld_at(points[0].at) is None
        z = self.upper if upper else self.lower
        for p0, p1 in pairwise(points):
            if z >= el.off:
                return p0.at
            span = p1.at - p0.at
            live = (
                max(0.0, (p1.at - max(p0.at, el.live_at)).total_seconds())
                / 60.0
            )
            gain = el.rate * live if credited else 0.0
            if upper and heat_path:
                # The path a floor, the element the faster rise.
                own = min(self.sp, z + gain)
                if max(p1.upper_f, own) >= el.off:
                    fs = [(el.off - z) / gain] if own >= el.off else []
                    if p1.upper_f >= el.off:
                        rise = p1.upper_f - p0.upper_f
                        fs.append(
                            (el.off - p0.upper_f) / rise if rise > 0 else 0.0
                        )
                    return p0.at + span * max(0.0, min(fs))
                z = max(p1.upper_f, own)
                continue
            dz = p1.upper_f - p0.upper_f if upper else p1.lower_f - p0.lower_f
            if z + dz + gain >= el.off:
                if (
                    not heat_path
                    and p0.lower_f > p0.upper_f
                    and z + dz < el.off
                ):
                    # An inverted tank turns over at once; the coast
                    # shows the mix only at its step's end, wherever the
                    # walk cut it.
                    f = (el.off - z - dz) / gain
                else:
                    f = (el.off - z) / (dz + gain)
                return p0.at + (p1.at - p0.at) * f
            z = z + dz if z + dz >= self.sp else min(self.sp, z + dz + gain)
        return None

    def _dispatch(self, event: ctl.Event) -> None:
        """Hand ``event`` to the firmware (``controller.transition``) and
        carry out what it does, in order."""
        self.state, actions = ctl.transition(
            self.state, event, self.settings, self.params
        )
        for action in actions:
            self._do(action)

    def _do(self, action: ctl.Action) -> None:
        """Carry out one of the controller's actions on the walk."""
        match action:
            case ctl.Note(reason):
                self.reasons.add(reason)
            case ctl.SetpointSet(_, value):
                self.sp = value
                if self.cycle is not None:
                    self.cycle.setpoint_f = value
            case ctl.StartCompressor(start, _, hold):
                self._begin(start, hold=hold)
            case ctl.StopCompressor(at, reason):
                self._finish(at, reason)
            case ctl.Retarget():
                self._position()
            case ctl.StartElement(start, zone, live_at, credited):
                self._begin_element(start, zone, live_at, credited)
            case ctl.ElementRetarget(off):
                self._element_end(off)
            case ctl.StopElement(at, reason, coast_mode):
                self._stop_element(at, reason, coast_mode)
            case ctl.ModeSet(at, mode, ended_by):
                self._set_mode(at, mode, ended_by)
            case ctl.RecordModeWrite(at, mode, owner, serves):
                self.mode_writes.append(ModeWrite(at, mode, owner, serves))
            case ctl.ModeHeld(ref):
                self.mode_writes[ref].held = True
            case ctl.ModeTook(ref, at):
                self.mode_writes[ref].took_at = at
            case ctl.ModeWithdrawn(ref, at):
                self.mode_writes[ref].withdrawn_at = at
            case ctl.Dropped(at, mode):
                self.drops.append((at, mode))
            case ctl.EntryFired(ref):
                self.writes[ref].outcome = "fired"
            case ctl.EntrySkipped(ref):
                self.writes[ref].outcome = "skipped"
            case ctl.RecordWrite(at, value, mode, serves):
                self.writes.append(
                    Write(at, value, mode, "raw", "raw", serves, at, "fired")
                )
            case ctl.Then(event):
                self._dispatch(replace(event, tank=self._tank()))

    # ── path ──

    def _append(
        self,
        points: Sequence[Point],
        heating: bool,
        *,
        heat_path: bool = False,
    ) -> None:
        """Extend the path with ``points``: a coast's, or with
        ``heat_path`` the running cycle's served recovery."""
        if self.element is not None or self.hold_upper or self.coast_f:
            points = self._overlay(points, heat_path=heat_path)
        for p in points:
            if p.at <= self.path[-1].at:
                continue
            self.path.append(
                PathPoint(
                    p.at,
                    p.upper_f,
                    p.lower_f,
                    self.sp,
                    heating or p.element_wh > 0.0,
                    p.input_wh,
                    p.element_wh,
                    self.mode,
                )
            )
        self.upper, self.lower = points[-1].upper_f, points[-1].lower_f

    def _overlay(
        self, points: Sequence[Point], *, heat_path: bool
    ) -> list[Point]:
        """``points`` with the running element laid over them.

        The element lifts its zone at its fitted rate toward the setpoint
        and draws its fitted power (``ElementParams``), and the segment is
        cut at its end, so it runs over the whole of any segment it is in.
        An upper element draws from its on-edge and lifts nothing for its
        dead time (``upper_dead_time_min``), whose end is a boundary.
        It ends at its off point; where that is short of the setpoint
        (Energy Saver's upper element) the zone then coasts on at the
        element's rate with no input, by no more than the off deficit
        and the heat in transit (``coast_f``), and none of it inside a
        withheld window.
        On a cycle's served path the path is a floor for the upper zone,
        the element the faster rise, the higher of the two holding;
        in a coast (a pause's included) the element's gain rides on the
        coast's losses and draws. Once an element has run in a cycle, its
        gain is kept to the cycle's end: held against the path, and
        carried through a coast's losses. Inside a withheld
        draw window the element is charged and credited no heat,
        as the compressor is.
        """
        el = self.element
        credited = self._withheld_at(points[0].at) is None
        u, lo = self.upper, self.lower
        out = [replace(points[0], upper_f=u, lower_f=lo, element_wh=0.0)]
        for p0, p1 in pairwise(points):
            minutes = (p1.at - p0.at).total_seconds() / 60.0
            du = p1.upper_f - p0.upper_f
            dl = p1.lower_f - p0.lower_f
            wh = 0.0
            if el is None:
                u = max(p1.upper_f, u) if heat_path else u + du
                lo = p1.lower_f
                if self.coast_f > 0.0:
                    g = min(self.coast_f, self.coast_rate * minutes)
                    self.coast_f = (
                        0.0 if g >= self.coast_f else (self.coast_f - g)
                    )
                    if credited:
                        u = max(u, min(self.sp, u + g))
            else:
                wh = self.ep.element_w * minutes / 60.0
                # Charged from the on-edge; its zone rises only after
                # the dead time.
                live = (
                    max(0.0, (p1.at - max(p0.at, el.live_at)).total_seconds())
                    / 60.0
                )
                gain = el.rate * live if credited else 0.0
                el.credited_min += minutes if credited else 0.0
                if el.zone == "lower":
                    u = u + du
                    lo = (
                        lo + dl
                        if lo + dl >= self.sp
                        else min(self.sp, lo + dl + gain)
                    )
                elif heat_path:
                    u = max(
                        p1.upper_f,
                        u if u >= self.sp else min(self.sp, u + gain),
                    )
                    lo = p1.lower_f
                else:
                    u = (
                        u + du
                        if u + du >= self.sp
                        else min(self.sp, u + du + gain)
                    )
                    lo = p1.lower_f
            out.append(Point(p1.at, u, lo, p1.input_wh, wh))
        if el is not None:
            el.interval.input_wh = (el.interval.input_wh or 0.0) + sum(
                p.element_wh for p in out
            )
        return out

    def _take_draws(self, start: datetime, end: datetime) -> list[Draw]:
        """Remove and return the draws with onsets in ``[start, end)``."""
        taken = [d for d in self.draws if start <= d[0] < end]
        self.draws = [d for d in self.draws if not start <= d[0] < end]
        self.taken.extend(taken)
        return taken

    def _coast(self, end: datetime) -> Coast:
        return self._physics_coast(end, self._peek_draws(end))

    def _physics_coast(self, end: datetime, draws: list[Draw]) -> Coast:
        """The calibrated coast from now to ``end`` over ``draws``."""
        return self.physics.coast(
            self.t,
            self.upper,
            self.lower,
            end,
            draws,
            heated_at=self._heated_at(),
        )

    def _heated_at(self) -> datetime | None:
        """When the tank last heated, which a run's standby pool counts
        from: now while the compressor or an element runs, whose
        pool is empty as the live read has it, else the end of the last
        heating by either, as the pool was fitted."""
        if self.cycle is not None or self.element is not None:
            return self.t
        return self.last_heated

    def _peek_draws(self, end: datetime) -> list[Draw]:
        return [d for d in self.draws if self.t <= d[0] < end]

    # ── heating ──

    def _base(self, cycle: _Cycle, target: float) -> Heat:
        """The origin's served path to ``target``, predicted once."""
        if target not in cycle.bases:
            t0, up, lo = cycle.origin
            kw: dict[str, float] = {}
            if cycle.hold_minutes > 0.0:
                kw["hold_minutes"] = cycle.hold_minutes
            if cycle.lead_load > 0.0:
                kw["draw_load"] = cycle.lead_load
            truncated = getattr(self.physics, "truncated_recoveries", 0)
            heat = self.physics.heat(t0, up, lo, target, **kw)
            if heat is None:
                if getattr(self.physics, "truncated_recoveries", 0) > truncated:
                    # A weak fit or very cold air, not missing physics.
                    raise SimulationError(
                        "recovery unavailable: the physics integration hit "
                        f"its {MAX_MINUTES:.0f}-min bound short of the target"
                    )
                raise SimulationError("recovery unavailable")
            self._note(heat)
            cycle.confidence = min(cycle.confidence, heat.confidence)
            cycle.bases[target] = heat
        return cycle.bases[target]

    def _placed(self, cycle: _Cycle, target: float) -> list[Point] | None:
        """The origin's path to ``target``, moved in time so the tank now
        sits on it, from now to its end; None when the tank is already at
        the target."""
        base = self._base(cycle, target)
        if self.lower >= base.points[-1].lower_f:
            return None
        # At the origin itself the path starts where it starts; placing
        # it by temperature there would skip a hold at its start.
        into = self.t - cycle.origin[0]
        if self.t == cycle.origin[0]:
            at: datetime | None = base.points[0].at
        elif (
            into < timedelta(minutes=cycle.hold_minutes)
            and self.lower <= cycle.origin[2] + 1e-9
        ):
            # Still in the start's hold, where the path is flat: placed
            # by the clock, or a write would skip the rest of it.
            at = base.points[0].at + into
        else:
            at = _at_lower(base.points, self.lower)
        if at is None:  # colder than the origin: ``_position`` renews it
            at = base.points[0].at
        shifted = _shift(base.points, self.t - at)
        placed = _slice(shifted, self.t, shifted[-1].at)
        # It starts from the tank as it is, which a draw or a pause may
        # have left a little off the path's upper zone.
        placed[0] = Point(self.t, self.upper, self.lower, 0.0)
        return placed

    def _lead_load(self) -> float:
        """The recovery model's ``draw_load`` for the draws recorded in
        the ``DRAW_LEAD`` before now, for a recovery beginning now: their
        registered heat over the deficit's, as the model was fitted. They
        are consumed by the first recovery."""
        lead = [
            d for d in self.recorded_lead if self.t - DRAW_LEAD <= d[0] < self.t
        ]
        self.recorded_lead = []
        if not lead:
            return 0.0
        drop = 0.0
        for at, gal in lead:
            up, lo = self.physics.draw(at, self.upper, self.lower, gal)
            drop += (self.upper + self.lower - up - lo) / 2.0
        return drop / max(self.sp - self.lower, _MIN_LOAD_DEFICIT_F)

    def _position(self, *, renew: bool = False) -> None:
        """Place the running recovery on its path from the tank now, with
        the TOU cap applied where the device applies it
        (``controller.judge_cap``).

        A recovery stops at the first instant it is inside a window with
        the lower zone at the cap's level (the target less ``tou_cap_f``).
        The level's timing is the path to that level from the origin: a
        capped recovery is predicted as a recovery to the level. One the
        cap does not stop runs on past its target to
        ``hp_stop_overshoot_f`` over it. ``renew`` predicts it afresh
        from the tank now, as a colder tank does.
        """
        cycle = self.cycle
        assert cycle is not None
        if renew or self.lower < cycle.origin[2] - 1e-9:
            # Colder than where the cycle began: no point of its path
            # matches, so the recovery is predicted afresh from here.
            cycle.origin = (self.t, self.upper, self.lower)
            cycle.bases = {}
            cycle.lead_load = 0.0
            gone = (self.t - cycle.start.at).total_seconds() / 60.0
            cycle.hold_minutes = max(0.0, cycle.hold_total - gone)
        target = cycle.setpoint_f
        empty = Heat([Point(self.t, self.upper, self.lower, 0.0)], 1.0)
        # The heat pump stops at the top of its water range.
        stop = min(
            target + self.params.hp_stop_overshoot_f,
            self.params.hp_water_range_f[1],
        )
        full = self._placed(cycle, stop)
        if full is None:
            cycle.heat, cycle.capped = empty, False
            return
        cap = judge_cap(
            full,
            at=self.t,
            lower_f=self.lower,
            target_f=target,
            windows=self.windows,
            params=self.params,
        )
        if cap.kind == "none":
            cycle.heat, cycle.capped = Heat(full, cycle.confidence), False
            return
        window = cap.window
        assert window is not None
        if cap.kind == "at_level":
            # Already at the level inside the window: it does not heat.
            # Before the opening it heats off-peak until then (below).
            cycle.heat, cycle.capped = empty, True
            return
        capped = self._placed(cycle, cap.level)
        outcome = ctl.cap_outcome(
            None if capped is None else capped[-1].at, window
        )
        if outcome == "until_open":
            cycle.heat = Heat(_slice(full, self.t, window[0]), cycle.confidence)
            cycle.capped = True
        elif outcome == "to_level":
            assert capped is not None
            cycle.heat, cycle.capped = Heat(capped, cycle.confidence), True
        else:
            cycle.heat, cycle.capped = Heat(full, cycle.confidence), False
        if cycle.capped:
            self.reasons.add(TOU_CAP_PROJECTED)

    def _note(self, heat: Heat) -> None:
        self.reasons.update(heat.reasons)
        if heat.linear:
            self.reasons.add("recovery_path_linear")

    def _begin(self, start: Start, *, hold: float) -> None:
        """The compressor starts (``controller.StartCompressor``): its
        recovery, from the tank now, holding ``hold`` minutes before it
        climbs."""
        self.cycle = _Cycle(
            start=start,
            setpoint_f=self.sp,
            origin=(self.t, self.upper, self.lower),
            bases={},
            heat=Heat([Point(self.t, self.upper, self.lower, 0.0)], 1.0),
            capped=False,
            hold_total=hold,
            hold_minutes=hold,
            lead_load=self._lead_load(),
        )
        self._position()
        cycle = self.cycle
        cycle.interval = HeatingInterval(
            start=start,
            end=start.at,
            target_f=self.sp,
            capped=cycle.capped,
            stop="horizon",
            input_wh=0.0,
            confidence=cycle.confidence,
            final_target_f=self.sp,
        )
        self.heating.append(cycle.interval)

    def _finish(self, at: datetime, stop: StopReason) -> None:
        """The compressor stops (``controller.StopCompressor``)."""
        cycle = self.cycle
        assert cycle is not None
        interval = cycle.interval
        assert interval is not None
        interval.end = at
        interval.stop = stop
        interval.capped = stop == "cap"
        interval.input_wh = cycle.input_wh
        interval.confidence = cycle.confidence
        interval.final_target_f = cycle.setpoint_f
        # A write that ends a recovery because the lower zone is already
        # at the new setpoint ends it at that target too.
        at_target = stop in ("target", "cap") or (
            stop == "write" and self.lower >= cycle.setpoint_f - 0.01
        )
        if at_target:
            self.reached.append((at, cycle.setpoint_f))
        self.cycle = None
        self.last_heated = at
        self.hold_upper = False

    def _account(self, points: Sequence[Point]) -> None:
        cycle = self.cycle
        assert cycle is not None
        wh = _energy(points)
        cycle.input_wh = (
            None
            if wh is None or cycle.input_wh is None
            else cycle.input_wh + wh
        )

    def _withheld_at(self, at: datetime) -> Window | None:
        return window_at(at, self.withheld)

    def _heat_until(self, end: datetime) -> None:
        """Run the cycle to ``end`` or to its own finish."""
        while self.cycle is not None and self.t < end:
            cycle = self.cycle
            # A draw at this very instant: the coast before took the
            # ones before it, and this segment starts here.
            now = self._take_draws(self.t, self.t + _INSTANT)
            if now:
                upper, lower = self.upper, self.lower
                for _, gal in now:
                    self.upper, self.lower = self.physics.draw(
                        self.t, self.upper, self.lower, gal
                    )
                moved = self._follow_ledger(upper, lower)
                self._step_point()
                # A draw can take the lower zone out of the heat pump's
                # range, which stops it.
                if self._check_availability():
                    continue
                # A zone the book took down is off the recovery's path,
                # which holds the upper zone where it began: predicted
                # afresh from here.
                self._position(renew=moved)
                self._element_trigger()
                continue
            if cycle.paused_until is None:
                w = self._withheld_at(self.t)
                if w is not None:
                    if cycle.power_w is None:
                        cycle.power_w = _power(cycle.heat.points[:2])
                    cycle.paused_until = min(w[1], self.until)
            if cycle.paused_until is not None:
                self._pause(min(end, cycle.paused_until))
                continue
            path = cycle.heat.points
            finish = path[-1].at
            nxt = min(end, finish)
            later = [d[0] for d in self.draws if self.t < d[0] < nxt]
            later += [w[0] for w in self.withheld if self.t < w[0] < nxt]
            if self.element is not None:
                later += [
                    x
                    for x in (self.element.end, self.element.live_at)
                    if self.t < x < nxt
                ]
            nxt = min([nxt, *later])
            piece = _slice(path, self.t, nxt)
            done_at = self._element_done(piece, heat_path=True)
            if done_at is not None and self.t < done_at < nxt:
                # The running element reaches its off point first: the
                # walk reads its zone there.
                nxt = done_at
                piece = _slice(path, self.t, nxt)
            self._account(piece)
            power = _power(piece)
            if power is not None:
                cycle.power_w = power
            self._append(piece, heating=True, heat_path=True)
            self.t = nxt
            self._element_boundary()
            if nxt >= finish:
                # Stopped short of its target at the top of its range:
                # the elements finish it.
                short = self.lower < cycle.setpoint_f and not self._water_ok(
                    self.lower
                )
                if not (short and self._check_availability()):
                    self._dispatch(
                        ctl.RecoveryDone(
                            at=nxt, tank=self._tank(), capped=cycle.capped
                        )
                    )

    def _pause(self, stop: datetime) -> None:
        """Coast over a withheld window with the compressor charged at
        its running power: it runs, and is credited no heat."""
        cycle = self.cycle
        assert cycle is not None
        if self.ledger is not None and self._peek_draws(stop):
            # A draw the book takes the upper zone through stops the
            # pause at its instant, as it stops a coast (``_upper_cut``).
            ahead = self._coast(stop)
            cut = self._upper_cut(ahead.points, stop)
            if cut is not None and cut > self.t:
                stop = cut
        coast = self._physics_coast(stop, self._take_draws(self.t, stop))
        points = list(coast.points)
        for i in range(1, len(points)):
            hours = (points[i].at - points[i - 1].at).total_seconds() / 3600
            power = cycle.power_w
            points[i] = replace(
                points[i], input_wh=None if power is None else power * hours
            )
        self._account(points)
        self._append(points, heating=True)
        self.t = stop
        if stop == cycle.paused_until:
            cycle.paused_until = None
            if stop < self.until:
                self._position()

    def _step_point(self) -> None:
        """The state just after a draw, at the draw's instant, so the
        path shows the step rather than a slide into it."""
        self.path.append(
            PathPoint(
                self.t,
                self.upper,
                self.lower,
                self.sp,
                True,
                0.0,
                mode=self.mode,
            )
        )

    # ── entries, raw writes and the heater's mode events ──

    def _fire_due(self, at: datetime) -> None:
        """The entries due at ``at``, each handed to the controller in
        turn with the tank as the one before it left it."""
        due = [i for fires, i in self.queue if fires == at]
        if not due:
            return
        self.queue = [(f, i) for f, i in self.queue if f != at]
        for i in due:
            w = self.writes[i]
            self._dispatch(
                ctl.EntryFires(
                    at=at,
                    tank=self._tank(),
                    setpoint_f=w.setpoint_f,
                    mode=w.mode,
                    serves=w.serves,
                    ref=i,
                )
            )

    def _raw_writes(self, at: datetime) -> None:
        """Every raw write due by ``at``, as it was made."""
        due: list[RawWrite] = []
        while self.raw and self.raw[0].at <= at:
            due.append(self.raw.pop(0))
        if due:
            self._dispatch(
                ctl.RawWrites(
                    at=at,
                    tank=self._tank(),
                    writes=tuple(
                        ctl.Written(w.setpoint_f, w.mode, w.id) for w in due
                    ),
                )
            )

    def _mode_events(self, at: datetime) -> None:
        """A TOU window closing at ``at``, then one opening there."""
        if any(w[1] == at for w in self.windows):
            self._dispatch(ctl.WindowCloses(at=at, tank=self._tank()))
        if any(w[0] == at for w in self.windows):
            self._dispatch(ctl.WindowOpens(at=at, tank=self._tank()))

    def _set_mode(
        self, at: datetime, mode: HeaterMode, ended_by: ModeEnd
    ) -> None:
        """The mode in force changes (``controller.ModeSet``)."""
        last = self.modes[-1]
        last.end, last.ended_by = at, ended_by
        self.modes.append(ModeInterval(at, self.until, mode))
        self.mode = mode

    # ── elements ──

    def _element_trigger(self) -> None:
        """The element's later start reads the upper zone now
        (``controller.later_upper_on``)."""
        self._dispatch(ctl.UpperRead(at=self.t, tank=self._tank()))

    def _begin_element(
        self,
        start: Start,
        zone: Literal["upper", "lower"],
        live_at: datetime,
        credited_min: float,
    ) -> None:
        """An element starts (``controller.StartElement``): it lifts its
        zone from ``live_at`` at the fitted rate."""
        interval = HeatingInterval(
            start=start,
            end=start.at,
            target_f=self.sp,
            capped=False,
            stop="horizon",
            input_wh=0.0,
            confidence=None,
            final_target_f=self.sp,
            source="element",
            zone=zone,
        )
        self.heating.append(interval)
        # A new run's own rise takes over from any coast still owed.
        self.coast_f = 0.0
        rate = (
            self.ep.upper_f_per_min
            if zone == "upper"
            else self.ep.lower_f_per_min
        )
        self.element = _Element(
            zone,
            interval,
            rate,
            self.t,
            live_at=live_at,
            credited_min=credited_min,
        )

    def _element_boundary(self) -> None:
        """At every boundary the running element's zone is read: at its
        off point it stops, otherwise it runs on (``_element_end``)."""
        if self.element is not None:
            # An element ending as the heat pump returns hands over to it.
            self._check_availability()
        if self.element is not None:
            self._dispatch(ctl.ElementCheck(at=self.t, tank=self._tank()))

    def _element_end(self, off: float) -> None:
        """When the running element reaches ``off`` from the tank now (a
        draw or a write moves it): what is left of its dead time, then
        its rise. Inside a withheld window it is credited no heat, so it
        runs on to the window's end."""
        el = self.element
        assert el is not None
        el.off = off
        if self._withheld_at(self.t) is not None:
            el.end = self.until
            return
        temp = self.upper if el.zone == "upper" else self.lower
        el.end = max(self.t, el.live_at) + timedelta(
            minutes=(off - temp) / el.rate
        )

    def _stop_element(
        self, at: datetime, stop: StopReason, coast_mode: ElementMode | None
    ) -> None:
        """An element stops (``controller.StopElement``). Off at an off
        point short of the setpoint (``coast_mode``), the zone coasts on,
        toward the setpoint in force and by no more than the heat in
        transit: what the run was charged for over its last dead time and
        has not shown."""
        el = self.element
        assert el is not None
        if coast_mode is not None:
            self.coast_f = min(
                max(0.0, self.sp - self.upper),
                earned_coast_f(coast_mode, self.ep, el.credited_min),
            )
            self.coast_rate = el.rate
            self.coast_end = at + timedelta(minutes=self.coast_f / el.rate)
        self.element = None
        self.last_heated = at
        el.interval.end = at
        el.interval.stop = stop
        el.interval.final_target_f = self.sp
        if self.cycle is not None and el.zone == "upper":
            self.hold_upper = True

    # ── the walk ──

    def run(self) -> Simulation:
        self._dispatch(
            ctl.Begins(
                at=self.t,
                tank=self._tank(),
                running=self.running,
                running_hold=self.running_hold,
                element_on=self.element_running,
            )
        )
        # The start's own instant is ordered as any later one's
        # (``_at_event``): an entry due there (its minute the start's),
        # a raw write, then the heater's own, a window opening there
        # dropping a running element mode. All before an element
        # the drop would stop at once is begun.
        self._fire_due(self.t)
        self._raw_writes(self.t)
        self._mode_events(self.t)
        if self.element_running:
            self._dispatch(
                ctl.ElementWasOn(
                    at=self.t,
                    tank=self._tank(),
                    since=self.element_running_since,
                )
            )
        steps = 0
        while self.t < self.until:
            steps += 1
            # Each edge of the air's range is a step or two of its own.
            if steps > _MAX_STEPS + 4 * len(self.air_out):
                raise SimulationError("the walk did not advance")
            self._check_availability()
            self._element_trigger()
            nxt = min([*self._upcoming(), self.until])
            if self.cycle is not None:
                self._heat_until(nxt)
            else:
                self._coast_until(nxt)
                self._element_boundary()
            if self.t < nxt:
                # A recovery ended, or the heater started itself, before
                # the event: what comes next may have changed (a write
                # its end released can start the heater again).
                continue
            self._at_event(nxt)
        self._dispatch(ctl.Horizon(at=self.until, tank=self._tank()))
        return Simulation(
            self.path,
            self.heating,
            sorted(self.writes, key=lambda w: (w.at, w.written_at)),
            sorted(self.reasons),
            self.mode_writes,
            [m for m in self.modes if m.end > m.start],
            self.reached,
            self.drops,
        )

    def _upcoming(self) -> set[datetime]:
        """Every instant the walk must stop at next: the controller's
        (``controller.wake_times``), and the walk's own."""
        upcoming = set(self.marks)
        upcoming.update(fires for fires, _ in self.queue)
        upcoming |= wake_times(self.state, self.settings)
        if self.element is not None:
            upcoming.add(self.element.end)
            for w0, w1 in self.withheld:
                upcoming.update((w0, w1))
        if self.coast_f and self.coast_end is not None:
            upcoming.add(self.coast_end)
            for w0, w1 in self.withheld:
                upcoming.update((w0, w1))
        if self.raw:
            upcoming.add(self.raw[0].at)
        for a, b in self.air_out:
            upcoming.update((a, b))
        return {t for t in upcoming if t > self.t}

    def _trigger_ahead(self, coast: Coast) -> ctl.Ahead | None:
        """The heater's own start on ``coast``
        (``controller.trigger_ahead``)."""
        drop = self._drop
        impulses = coast.impulses
        if drop is not None and drop.at == self.t:
            impulses = [drop, *impulses]
        ahead, notes = trigger_ahead(
            self.state,
            self.settings,
            self.params,
            [(p.at, p.upper_f, p.lower_f) for p in coast.points],
            impulses,
            self.t,
        )
        self.reasons.update(notes)
        return ahead

    def _coast_until(self, end: datetime) -> None:
        if self._mixing:
            # Any draw with a book may mix the upper zone down
            # (``zone_mixed_f``), so the next is where the coast may
            # stop: try it first, rather than a coast to ``end`` built
            # again after every draw.
            nxt = min((d[0] for d in self._peek_draws(end)), default=None)
            if nxt == self.t:
                # A draw at this instant is taken before anything else
                # (the cut below would win every tie).
                self._coast_draw()
                return
            if nxt is not None:
                ahead = self._nothing_before(nxt)
                if ahead is not None:
                    # Nothing before it: coast to it and take it there,
                    # without a coast to ``end`` that the draw would
                    # make stale.
                    self._take_draws(self.t, nxt)
                    self._append(ahead.points, heating=False)
                    self.t = nxt
                    self._coast_draw()
                    return
        coast = self._coast(end)
        at: datetime | None = None
        own = self._trigger_ahead(coast)
        if own is not None:
            if own.starts_at >= end:
                # Inside the restart lockout, starting past this
                # segment: carried to it as a pending start, the instant
                # it is due at, since a later segment's coast may begin
                # outside the window it fired in.
                self._dispatch(
                    ctl.TriggerDeferred(
                        at=self.t,
                        starts_at=own.starts_at,
                        trigger=own.trigger,
                        horizon=self.until,
                    )
                )
            else:
                at = own.starts_at
        element_at = upper_on_crossing(self.state, self.settings, coast.points)
        water_at = self._water_crossing(coast.points)
        if water_at is not None and all(
            x is None or water_at < x for x in (element_at, at)
        ):
            # The heat pump's availability changes before anything else
            # happens: the walk takes it up there.
            element_at = at = None
            end = min(end, water_at)
            coast = self._coast(end)
        done_at = self._element_done(coast.points)
        if done_at is not None and not self.t < done_at < end:
            done_at = None
        cut = self._upper_cut(
            coast.points,
            end,
            # Only a draw before anything else happens is taken here.
            min(x for x in (element_at, at, done_at, end) if x is not None),
        )
        if cut is not None and all(
            x is None or cut <= x for x in (element_at, at, done_at)
        ):
            # The book takes the zones through a draw before anything
            # else happens: coast to it, and take it at its instant.
            self._coast_to(cut)
            self._coast_draw()
            return
        if done_at is not None and all(
            x is None or done_at < x for x in (element_at, at)
        ):
            # The running element reaches its off point first: the walk
            # reads its zone there.
            self._coast_to(done_at)
            self._element_boundary()
            return
        if (
            element_at is not None
            and element_at < end
            and (at is None or element_at < at)
        ):
            self._coast_to(element_at)
            self._dispatch(ctl.UpperOnCrossed(at=element_at, tank=self._tank()))
            return
        if at is not None and at < end:
            assert own is not None
            self._coast_to(at)
            if not self.state.hp_available and any(
                d[0] <= at for d in self.draws
            ):
                # The elements answer from the tank a draw landing here
                # leaves (``controller.electric_entry``), which may be
                # back in the heat pump's range.
                self._coast_draw()
                self._check_availability()
                if self.state.hp_available:
                    # Back in range: the trigger is the heat pump's, with
                    # its lockout, found afresh from here.
                    return
            self._dispatch(
                ctl.HeaterTrigger(at=at, tank=self._tank(), trigger=own.trigger)
            )
            return
        self._take_draws(self.t, end)
        self._append(coast.points, heating=False)
        self.t = end

    def _nothing_before(self, limit: datetime) -> Coast | None:
        """The coast from now to ``limit`` when nothing on it acts before
        ``limit``: no start of the heater's own (``heater_start``, after
        ``_coast_until``'s own exceptions and the restart lockout), no
        later element start, and no draw the book takes the upper zone
        through (``_upper_cut``). None when something does: the caller
        then coasts as it always did. A trigger of its own on the coast
        that the lockout puts at or past ``limit`` is carried as a
        pending start."""
        coast = self._coast(limit)
        ahead = self._trigger_ahead(coast)
        if ahead is not None and ahead.starts_at < limit:
            return None
        element_at = upper_on_crossing(self.state, self.settings, coast.points)
        if element_at is not None and element_at < limit:
            return None
        water_at = self._water_crossing(coast.points)
        if water_at is not None and water_at < limit:
            return None
        if self._upper_cut(coast.points, limit) is not None:
            return None
        if ahead is not None and ahead.trigger_at <= limit:
            # A trigger by ``limit`` that the restart lockout puts at or
            # past it waits as a pending start, as ``_coast_until``
            # carries one: the drop that set it (a flowing draw's, at
            # the coast's end) is not on the coast from ``limit``.
            self._dispatch(
                ctl.TriggerDeferred(
                    at=self.t,
                    starts_at=ahead.starts_at,
                    trigger=ahead.trigger,
                    horizon=self.until,
                )
            )
        return coast

    def _coast_draw(self) -> None:
        """The draws at this instant outside a recovery, taken here and
        not inside a coast because the book may take the upper zone
        through one of them (``_upper_cut``): the path has the tank before and
        after, so whatever reads the zone sees the step at its instant
        rather than across a coast's grid."""
        upper, lower = self.upper, self.lower
        for _, gal in self._take_draws(self.t, self.t + _INSTANT):
            self.upper, self.lower = self.physics.draw(
                self.t, self.upper, self.lower, gal
            )
        if self.lower < lower:
            self._drop = Impulse(self.t, lower, self.lower)
        self._follow_ledger(upper, lower)
        self.path.append(
            PathPoint(
                self.t,
                self.upper,
                self.lower,
                self.sp,
                self.element is not None,
                0.0,
                mode=self.mode,
            )
        )
        if self._drop is not None and self._drop.at == self.t:
            self._carry_release()

    def _carry_release(self) -> None:
        """A start the drop just taken calls for, inside the restart
        lockout, waits as a pending start from now: the walk may next
        stop at another draw, where this one's drop is no longer seen."""
        ahead = self._trigger_ahead(
            Coast([Point(self.t, self.upper, self.lower)])
        )
        if (
            ahead is not None
            and ahead.trigger_at == self.t
            and ahead.starts_at > self.t
        ):
            self._dispatch(
                ctl.TriggerDeferred(
                    at=self.t,
                    starts_at=ahead.starts_at,
                    trigger=ahead.trigger,
                    horizon=self.until,
                )
            )

    def _heating_now(self, until: datetime) -> list[HeatingInterval]:
        """``heating`` with the recovery and the element running now
        taken to run to ``until`` (the element no further than its own
        end): the book prices their heat to there."""
        running: dict[int, datetime] = {}
        if self.cycle is not None and self.cycle.interval is not None:
            running[id(self.cycle.interval)] = until
        if self.element is not None:
            running[id(self.element.interval)] = min(
                until, max(self.element.end, self.t)
            )
        return [
            replace(h, end=running[id(h)]) if id(h) in running else h
            for h in self.heating
        ]

    def _follow_ledger(self, upper: float, lower: float) -> bool:
        """The ledger's say over the upper zone after the draws just
        taken at this instant, ``upper`` and ``lower`` the tank before
        them (*The booked heat at a draw*, in the module docstring;
        ``HeatLedger.after_draw``): it goes down to the ledger's when
        that is below the draw's own response. Whether it did."""
        if self.ledger is None:
            return False
        gal = 0.0
        for at, g in reversed(self.taken):
            if at != self.t:
                break
            gal += g
        path = [p for p in self._path_since_carry() if p.at < self.t]
        path.append(
            PathPoint(self.t, upper, lower, self.sp, False, 0.0, mode=self.mode)
        )
        taken = [d for d in self._taken_since_carry() if d[0] <= self.t]
        said = self.ledger.after_draw(
            DrawTaken(
                at=self.t,
                gallons=gal,
                upper_f=upper,
                lower_f=lower,
                drawn_upper_f=self.upper,
                drawn_lower_f=self.lower,
                path=path,
                intervals=self._heating_now(self.t),
                draws=taken,
                drawn_gal=sum(g for _, g in taken),
                stand=self.ledger_carry,
                bound=self._zone_bound(upper, lower),
            )
        )
        self._stood(said.stand)
        if said.upper_f is None:
            return False
        self.upper = said.upper_f
        return True

    def _zone_bound(self, upper: float, lower: float) -> ZoneBound | None:
        """What the ledger needs to show, without walking, that the
        draws just taken at this instant cannot move the upper zone:
        the most standby and draws can take from it since its stand
        (``loss_bound``), and the zone's range over the span. None
        where no bound can: before a stand, with a ledger that mixes,
        or across a heating that has stopped since the stand (a
        re-anchor is no floor)."""
        carry = self.ledger_carry
        if carry is None or self.ledger is None or self._mixing:
            return None
        running = {
            id(x.interval): x.interval.start.at
            for x in (self.cycle, self.element)
            if x is not None and x.interval is not None
        }
        if any(
            carry.at < h.end <= self.t
            for h in self.heating
            if id(h) not in running
        ):
            return None
        since = [p for p in self._path_since_carry() if p.at <= self.t]
        uppers = [upper, *(p.upper_f for p in since)]
        warmest = max(upper, lower, *(max(p.upper_f, p.lower_f) for p in since))
        return ZoneBound(
            lost_btu=self.ledger.loss_bound(carry.at, self.t, warmest),
            upper_lo_f=self.upper,
            upper_hi_f=max(*uppers, self.upper),
            running_since=tuple(running.values()),
        )

    def _stood(self, stand: Stand | None) -> None:
        """Where the ledger's walk now stands: each walk stands again at
        the clock, the path before it written, so nothing a later walk
        sees can change there."""
        if stand is not None:
            self.ledger_carry = stand

    def _path_since_carry(self) -> list[PathPoint]:
        carry = self.ledger_carry
        if carry is None:
            return list(self.path)
        i = bisect_left(self.path, carry.at, key=lambda p: p.at)
        return self.path[i:]

    def _taken_since_carry(self) -> list[Draw]:
        carry = self.ledger_carry
        if carry is None:
            return list(self.taken)
        i = bisect_left(self.taken, carry.at, key=lambda d: d[0])
        return self.taken[i:]

    def _upper_cut(
        self,
        points: Sequence[Point],
        end: datetime,
        horizon: datetime | None = None,
    ) -> datetime | None:
        """The first draw onset in ``[t, end)``, and no later than
        ``horizon``, at which the ledger would
        take the upper zone below the draw's own response, read along
        ``points``, a coast from now to ``end``
        (``HeatLedger.upper_moves_at``). The coast stops there to take
        the draw at its instant (``_coast_draw``). None without a
        ledger, or with no such draw.

        In a coast with nothing heating, the ledger is walked only to
        the first draw: after it nothing re-anchors (a draw disturbs the
        tank and nothing heats), so a bound decides the rest when the
        ledger is far from the zone's empty point, and the coast is
        walked through only when it is not."""
        if self.ledger is None:
            return None
        pending = [
            d
            for d in self._peek_draws(end)
            if horizon is None or d[0] <= horizon
        ]
        if not pending:
            return None
        onsets = sorted({at for at, _ in pending})
        first = onsets[0]
        last = self.path[-1].at
        since = self._path_since_carry()
        ahead = [
            PathPoint(
                p.at, p.upper_f, p.lower_f, self.sp, False, 0.0, mode=self.mode
            )
            for p in points
            if p.at > last
        ]
        quiet = (
            not self._mixing
            and self.cycle is None
            and self.element is None
            and len(onsets) > 1
        )
        head: list[PathPoint] | None = None
        bound: ZoneBound | None = None
        if quiet:
            head = [p for p in ahead if p.at < first]
            if first > last:
                there = point_at(points, first)
                head.append(
                    PathPoint(
                        first,
                        there.upper_f,
                        there.lower_f,
                        self.sp,
                        False,
                        0.0,
                        mode=self.mode,
                    )
                )
            head = [*since, *head]
            uppers = [p.upper_f for p in points if p.at >= first]
            hi = max(uppers) + 2.0
            # Standby runs on the zones' mean.
            warmest = (
                max(max(p.upper_f, p.lower_f) for p in points if p.at >= first)
                + 2.0
            )
            bound = ZoneBound(
                lost_btu=self.ledger.loss_bound(first, onsets[-1], warmest),
                # A draw's own response takes the zone a little under
                # the coast's line, an element's coast a little over it.
                upper_lo_f=min(uppers) - 2.0,
                upper_hi_f=hi,
            )
        said = self.ledger.upper_moves_at(
            DrawsAhead(
                at=self.t,
                path=[*since, *ahead],
                head=head,
                intervals=self._heating_now(end),
                taken=self._taken_since_carry(),
                pending=pending,
                onsets=onsets,
                points=points,
                respond=self.physics.draw,
                stand=self.ledger_carry,
                bound=bound,
            )
        )
        self._stood(said.stand)
        return said.at

    def _coast_to(self, at: datetime) -> None:
        """Coast to ``at`` exactly. Cutting a longer coast would
        interpolate across a step whose draw it had already taken at its
        onset, charging part of a later draw before ``at`` and all of it
        again after."""
        if at > self.t:
            upto = self._physics_coast(at, self._take_draws(self.t, at))
            self._append(upto.points, heating=False)
        self.t = at

    def _at_event(self, at: datetime) -> None:
        # The heat pump's range first: whatever lands at the instant it
        # leaves or re-enters it is answered by the heater as it is now.
        if at < self.until:
            self._check_availability()
        pending = self.state.compressor.pending
        if pending is not None and pending.at == at and at < self.until:
            self._dispatch(ctl.StartDue(at=at, tank=self._tank()))
        if at >= self.until:
            return
        # The device's entries, then raw writes, then the heater's own:
        # at an instant both act, an entry (a mode withdrawing a held
        # one) comes first.
        self._fire_due(at)
        self._raw_writes(at)
        self._mode_events(at)


def simulate(
    *,
    start: datetime,
    upper_f: float,
    lower_f: float,
    running: bool,
    until: datetime,
    setpoint_f: float,
    heater: Heater,
    physics: Physics,
    entries: Sequence[Entry] = (),
    draws: Sequence[Draw] = (),
    withheld_windows: Sequence[Window] = (),
    marks: Sequence[datetime] = (),
    element_running: bool = False,
    element_running_since: datetime | None = None,
    raw_writes: Sequence[RawWrite] = (),
    stopped_at: datetime | None = None,
    heated_at: datetime | None = None,
    start_hold: Callable[[float | None], float] | None = None,
    running_hold: float = 0.0,
    lead_draws: Sequence[Draw] = (),
    ledger: HeatLedger | None = None,
    controller: ControllerParams | None = None,
) -> Simulation:
    """Walk the heater from ``start`` to ``until``, its reservation
    list holding ``entries``.

    ``draws`` are the scenario's draws (delivered gallons at their
    onsets). A coast takes the ones it spans; a recovery takes each of
    the others at its onset and resumes from the colder tank, placed back
    on its one served path (``_Cycle``). ``withheld_windows`` are the
    forecast draw windows over which a recovery is credited no heat:
    the compressor runs and is charged, and the tank coasts.
    ``marks`` are instants the path must carry an
    element at, so the tank there is read exactly rather than
    interpolated across a step. ``element_running``: an element is on at
    the start (in an element mode, ``heater.mode``);
    ``element_running_since`` its on-edge, when known, which leaves it
    the rest of its dead time (unknown: past it). ``raw_writes`` are
    replayed as made (calibration only): a caller never passes them
    with entries.
    ``stopped_at`` is the compressor's last stop before ``start``, which
    seeds the restart lockout. ``heated_at`` is when the tank last heated
    by any source before ``start``, which a run's standby pool counts
    from; None counts it from ``stopped_at``. ``start_hold`` is the hold
    a compressor start begins with, minutes, by the minutes since the
    compressor last stopped (None when not known), which a start's
    recovery holds for before it climbs; None holds none.
    A compressor already ``running`` holds for ``running_hold``, what is
    left of its own start's hold (0.0: none).
    ``lead_draws`` are draws recorded before ``start``: those within
    ``DRAW_LEAD`` of the first recovery's start, one running at
    ``start`` included, are the recovery model's ``draw_load`` for it,
    as its training rows read them from the recorded tank. They are not
    taken again.
    ``ledger`` walks the booked heat along the path so far (*The booked
    heat at a draw*, in the module docstring;
    ``sim.extensions.HeatLedger``): with it, a
    draw that spends the heat takes the upper zone down
    (``_follow_ledger``); every draw takes the lower zone by its own
    calibrated response either way. ``controller`` holds the numbers
    of the firmware's rules (``sim/controller.py``); None, the measured
    defaults.
    """
    return _Engine(
        start=start,
        upper_f=upper_f,
        lower_f=lower_f,
        running=running,
        until=until,
        setpoint_f=setpoint_f,
        entries=entries,
        heater=heater,
        physics=physics,
        draws=draws,
        withheld_windows=withheld_windows,
        marks=marks,
        element_running=element_running,
        element_running_since=element_running_since,
        raw_writes=raw_writes,
        stopped_at=stopped_at,
        heated_at=heated_at,
        start_hold=start_hold,
        running_hold=running_hold,
        lead_draws=lead_draws,
        ledger=ledger,
        controller=controller,
    ).run()


def energy_by_slot(
    sim: Simulation, slot: timedelta
) -> list[tuple[datetime, float | None]]:
    """Electricity per clock-aligned slot, Wh, both sources together:
    each interval's energy spread evenly over its time. A slot an
    unpriced interval touches is None."""
    return [
        (at, None if comp is None else comp + element)
        for at, comp, element in energy_by_source(sim, slot)
    ]


def energy_by_source(
    sim: Simulation, slot: timedelta
) -> list[tuple[datetime, float | None, float]]:
    """``energy_by_slot`` by source: ``(slot start, compressor Wh,
    element Wh)``. The compressor's is None where an unpriced
    interval touches the slot; the element's is always priced (its
    fitted power, ``ElementParams.element_w``)."""
    if slot <= timedelta(0):
        raise ValueError(f"slot must be positive, not {slot}")
    if len(sim.points) < 2:
        return []
    step = slot.total_seconds()
    epoch = datetime(1970, 1, 1, tzinfo=UTC)

    def floor(at: datetime) -> datetime:
        s = (at - epoch).total_seconds()
        return epoch + timedelta(seconds=math.floor(s / step) * step)

    comp: dict[datetime, float | None] = {}
    element: dict[datetime, float] = {}
    at = floor(sim.points[0].at)
    while at < sim.points[-1].at:
        comp[at] = 0.0
        element[at] = 0.0
        at += slot

    def add(key: datetime, wh: float | None) -> None:
        if key in comp:
            current = comp[key]
            comp[key] = None if current is None or wh is None else current + wh

    for p0, p1 in pairwise(sim.points):
        span = (p1.at - p0.at).total_seconds()
        if span <= 0 or (p1.input_wh == 0.0 and p1.element_wh == 0.0):
            continue
        cur = p0.at
        while cur < p1.at:
            edge = min(floor(cur) + slot, p1.at)
            share = (edge - cur).total_seconds() / span
            key = floor(cur)
            if p1.input_wh != 0.0:
                add(key, None if p1.input_wh is None else p1.input_wh * share)
            if key in element:
                element[key] += p1.element_wh * share
            cur = edge
    return [(at, comp[at], element[at]) for at in sorted(comp)]
