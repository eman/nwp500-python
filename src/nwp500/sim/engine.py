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
returns. What it keeps is the walk: where to stop, the physics between
stops, the withheld draw windows and the draws.

The heater takes ``entries``, each a minute, a mode and a setpoint, and
when it was written: it fires each in its minute, at the minute's start,
or at once when written during it (``Write.fires_at``). An entry that
cannot fire in the walk (its minute over when written, or before the
walk's start) is the caller's error. The engine knows no plan: what
writes the entries, and why, is the caller's (a caller may write one
per segment of an intent, at its start minute, as given). A plan's
``tou`` command sets the switch at its adoption, the walk's start: the
caller passes the windows it leaves (none for ``tou`` off).

**The tank is the physics' state.** The physics is injected
(``Physics``) so the walk can be tested on its own; the caller supplies
the core's calibrated tank (``sim.tank_physics.TankPhysics``). The
engine carries the tank as the physics gives it and reads only its
probes. Every segment walks it forward from where it is, under what
runs then: the compressor (from its start, heating after its hold, its
heat scaled by a recovery model's answer), an element (its heat a dead
time behind it, so it still heats that long after it stops), and
neither's heat inside a withheld draw window, where both are charged.
A recovery is that walk until the lower probe reaches its stop, an
element's until its zone reaches its off point: nothing is predicted
and placed, so a draw, a pause or an element in a recovery moves the
tank it acts on.

The engine owns the draws: it hands each coast the ones whose onsets it
spans and takes the others at their instants inside a recovery, so
every draw is taken exactly once whichever kind of segment it falls in.

**Raw writes (calibration only).** ``raw_writes`` replays recorded
setpoint and mode writes as they were made, at their instants and values,
not as entries: no quantisation.
The heater's response to each is the same as to an entry (the start it
causes, the TOU cap, a mode held in a window), which is what a
reconciliation against the record tests.
"""

from __future__ import annotations

import dataclasses
import math
import types
import typing
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any, Literal

from nwp500.sim import controller as ctl
from nwp500.sim.controller import (
    ELEMENT_DONE_F,
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
from nwp500.sim.params import ControllerParams, ElementParams
from nwp500.sim.physics.element import HeaterMode
from nwp500.sim.physics.stratified import IDLE_STEP
from nwp500.sim.tank_physics import (
    CompressorRun,
    Delivered,
    ElementRun,
    Physics,
    Point,
    Running,
    Stop,
    Stretch,
    TankState,
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
#: How far ahead a recovery is walked to judge the TOU cap on it.
RECOVERY_AHEAD = timedelta(hours=16)
#: How far a coast walks ahead before it first looks for the heater's
#: own start, to the clock's ``IDLE_STEP`` grid at or before it, each
#: later piece twice the last: the start is found on the walk and the
#: walk is taken again to there, so a coast walked whole to a distant
#: event would cost the horizon at every start. A split on the grid is
#: a step's end, so the tank walked in pieces is the tank walked whole
#: (``_coast_stretch``).
_COAST_AHEAD = timedelta(hours=2)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
#: A walk that has not reached the horizon after this many steps is a
#: bug, not a long simulation (a week of 10-minute events is ~1,000).
_MAX_STEPS = 20_000

#: The ``id`` of the write a walk going on from another makes of the
#: settings it is given where they differ from where that one ended.
_SETTINGS_WRITE = "settings"

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

# ``Point``, ``Stretch``, ``Running`` and the ``Physics`` protocol are
# the core's (``sim.tank_physics``), imported above: the caller supplies
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
    #: The tank's layers here, °F, the bottom first, for a physics whose
    #: state has them (``physics.stratified``); None otherwise.
    layers_f: tuple[float, ...] | None = field(default=None, compare=False)


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
    #: The heater where the walk ended, for a walk from there to go on
    #: from (``simulate(resume=...)``).
    resume: Resume | None = field(default=None, compare=False)

    @property
    def starts(self) -> list[Start]:
        return sorted((h.start for h in self.heating), key=lambda s: s.at)


class SimulationError(Exception):
    """A walk the engine could not finish."""


#: ``Resume.to_document``'s format.
RESUME_VERSION = 1
#: A resume not carried on: heating disabled or enabled since it ended
#: (``Resume.disabled``), by a write the simulation holds no rule for.
RESUME_DROPPED = "resume_dropped_heating_disabled_changed"


@dataclass(frozen=True)
class Resume:
    """The heater where a walk ended, ``at``: the firmware's state and
    what the engine keeps beside it (the recovery running, the element,
    heat still on its way from one that stopped, a mode write held in
    a window). A walk from ``at`` given it (``simulate(resume=...)``)
    goes on as the walk would have past ``at`` unbroken. The tank is
    the caller's: the walk goes on from the one it is handed.

    Opaque to a caller, who keeps it as ``to_document`` writes it."""

    at: datetime
    controller: ctl.State
    setpoint_f: float
    mode: HeaterMode
    cycle: _Cycle | None = None
    element: _Element | None = None
    cooling: tuple[ElementRun, ...] = ()
    #: The tank was below the heat pump's water range with no element
    #: since to heat it past (``_Engine._cold``).
    cold: bool = False
    #: The mode write ``controller``'s held write is (its ``ref``).
    held_write: ModeWrite | None = None
    #: Heating was disabled (``controller.disabled``): Vacation, or
    #: powered off with no entry having turned the heater on.
    disabled: bool = False

    def check_from(self, start: datetime) -> None:
        """Refuse a walk from ``start`` that is not where this ended:
        whether it is gone on from or dropped (``carries``)."""
        if self.at != start:
            raise ValueError(
                f"a walk from {start.isoformat()} cannot go on from one "
                f"that ended at {self.at.isoformat()}"
            )

    def carries(self, *, heating_disabled: bool, powered_off: bool) -> bool:
        """Whether a walk in these settings goes on from it: not into or
        out of Vacation or Power Off since (``disabled``), a write the
        simulation holds no rule for."""
        now = ctl.disabled(
            self.controller,
            ctl.Settings(
                hp_lower_on_f=None,
                heating_disabled=heating_disabled,
                powered_off=powered_off,
            ),
        )
        return now == self.disabled

    def to_document(self) -> dict[str, Any]:
        """The resume as a JSON-compatible document: instants as ISO
        8601 strings, floats as they are."""
        return {"version": RESUME_VERSION, **_encode(self)}

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> Resume:
        """The resume ``doc`` holds (``to_document``); a ``version``
        other than ``RESUME_VERSION`` is a ``ValueError``."""
        if doc.get("version") != RESUME_VERSION:
            raise ValueError(
                f"resume version {doc.get('version')!r}, not "
                f"{RESUME_VERSION}: run the walk again from its start"
            )
        body = {k: v for k, v in doc.items() if k != "version"}
        return _decode(body, cls)


def _encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _encode(getattr(value, f.name))
            for f in dataclasses.fields(value)
            if f.init
        }
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_encode(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def _decode(value: Any, hint: Any) -> Any:
    """``value`` (``_encode``'s) as the type ``hint`` names."""
    if value is None:
        return None
    origin = typing.get_origin(hint)
    if origin in (typing.Union, types.UnionType):
        options = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(options) == 1:
            return _decode(value, options[0])
        if isinstance(value, dict):
            (cls,) = [a for a in options if dataclasses.is_dataclass(a)]
            return _decode(value, cls)
        return value
    if origin is tuple:
        (item, *_) = typing.get_args(hint)
        return tuple(_decode(v, item) for v in value)
    if hint is datetime:
        return datetime.fromisoformat(value)
    if isinstance(hint, type) and dataclasses.is_dataclass(hint):
        hints = typing.get_type_hints(hint)
        return hint(
            **{
                f.name: _decode(value[f.name], hints[f.name])
                for f in dataclasses.fields(hint)
                if f.init and f.name in value
            }
        )
    return value


# ── Helpers ─────────────────────────────────────────────────────────


def _layers_of(state: object) -> tuple[float, ...] | None:
    """The layers of a physics state that has them
    (``physics.stratified.TankState``); None for any other, or none."""
    layers = getattr(state, "layers_f", None)
    return None if layers is None else tuple(float(t) for t in layers)


#: The heater's setpoint resolution, °C: the NWP500 holds a setpoint in
#: half degrees Celsius, so 146 °F is held as 146.3 (2026-09-20).
SETPOINT_RESOLUTION_C = 0.5


def _onset(draw: Draw) -> datetime:
    return draw[0]


def _overlapping(windows: Sequence[Window]) -> bool:
    """Whether any two of ``windows`` overlap."""
    ordered = sorted(windows)
    return any(b[0] < a[1] for a, b in pairwise(ordered))


def quantise(f: float, resolution_c: float = SETPOINT_RESOLUTION_C) -> float:
    """``f`` as the device will hold it: to the nearest ``resolution_c``
    in °C. 146 °F is held as 146.3, as the device did on
    2026-09-20."""
    if resolution_c <= 0.0:
        return f
    c = (f - 32.0) / 1.8 / resolution_c
    return round(math.floor(c + 0.5) * resolution_c * 1.8 + 32.0, 2)


def floor_minute(at: datetime) -> datetime:
    """``at`` truncated to its minute: a reservation entry's minute."""
    return at.replace(second=0, microsecond=0)


# ── The engine ──────────────────────────────────────────────────────


@dataclass
class _Cycle:
    """The recovery running now: the compressor on from ``start``,
    heating from ``heats_at`` (its start's hold over), its heat scaled
    by ``scale``, to where it stops: the lower probe at ``stop_level``
    or, the TOU cap stopping it as a window opens, ``stop_at``. Both are
    judged again (``_position``) wherever the tank or the setpoint
    moves."""

    start: Start
    #: The setpoint whose recovery this is.
    setpoint_f: float
    heats_at: datetime
    stop_level: float
    capped: bool
    stop_at: datetime | None = None
    scale: float = 1.0
    input_wh: float | None = 0.0
    confidence: float = 1.0
    #: Why its pace may be less than it seems, from the start's model
    #: (``TankPhysics.scale``).
    why: tuple[str, ...] = ()
    #: Its heating begins at ``heats_at``, with the start's stir; False
    #: for a run under way at the walk's start with no hold left.
    stirs: bool = True
    #: Its entry in ``heating``.
    interval: HeatingInterval | None = None
    #: The hours its heat went in so far, and the probes' mean times
    #: them (``Stretch.heating_h``): its water judged where it stops.
    heating_h: float = 0.0
    heating_mean_f_h: float = 0.0


@dataclass
class _Element:
    """An element running now, on from ``on_at`` (its on-edge), its
    heat reaching the water from ``live_at``, to its off point
    (``controller.ElementRetarget``) once set."""

    zone: Literal["upper", "lower"]
    interval: HeatingInterval
    on_at: datetime
    live_at: datetime
    off: float | None = None


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
        start_hold: Callable[[float | None], float] | None = None,
        running_hold: float = 0.0,
        running_starts: bool = False,
        controller: ControllerParams | None = None,
        state: TankState | None = None,
        resume: Resume | None = None,
    ) -> None:
        if resume is not None:
            resume.check_from(start)
        #: A resume these settings do not go on from: the walk starts
        #: afresh (``Resume.carries``).
        self.resume_dropped = resume is not None and not resume.carries(
            heating_disabled=heater.heating_disabled,
            powered_off=heater.powered_off,
        )
        if self.resume_dropped:
            resume = None
        #: The walk goes on from one that ended at its start.
        self.resumed = resume
        if resume is not None:
            running = resume.cycle is not None
            element_running = False
        self.t = start
        #: The rest of a running compressor's hold at the start, minutes.
        self.running_hold = running_hold if running else 0.0
        #: The running compressor starts at the start: its heating
        #: begins after ``running_hold``, with the start's stir.
        self.running_starts = running and running_starts
        #: The tank, as the physics carries it (``_set``), and its
        #: probes, which everything else reads.
        self.tank_state: TankState = (
            physics.estimate(upper_f, lower_f) if state is None else state
        )
        # The probes as read: the state made of them observes them to
        # within rounding.
        self.probes = (
            (upper_f, lower_f)
            if state is None
            else physics.observe(self.tank_state)
        )
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
        #: the physics' air; none from a physics that cannot say. Read
        #: to just past the end, so a span the end cuts does not end
        #: there: the heat pump is not back in range at the end.
        outside = getattr(physics, "air_outside", None)
        self.air_out: list[Window] = (
            []
            if outside is None
            else outside(start, until + _INSTANT, *self.params.hp_air_range_f)
        )
        self.physics = physics
        available = self._available(start)
        #: The tank was below the heat pump's water range with no element
        #: since to heat it past: one heating it runs to its off point.
        self._cold = self.probes[1] < self.params.hp_water_range_f[0]
        self.state = ctl.initial_state(
            at=start,
            setpoint_f=setpoint_f,
            mode=heater.mode,
            running=running,
            stopped_at=stopped_at,
            params=self.params,
            hp_available=available,
        )
        self.reasons: set[str] = (
            {RESUME_DROPPED} if self.resume_dropped else set()
        )
        if (
            resume is None
            and not available
            and heater.mode in ctl.COMPRESSOR_MODES
            and not (heater.heating_disabled or heater.powered_off)
        ):
            self.reasons.add(ctl.HEAT_PUMP_UNAVAILABLE)
        #: The setpoint and the mode in force as the path records them,
        #: moved by the controller's actions as they are carried out.
        self.sp = setpoint_f
        self.mode: HeaterMode = heater.mode
        self.mode_writes: list[ModeWrite] = []
        self.cycle: _Cycle | None = None
        self.element: _Element | None = None
        #: Elements that have stopped, whose heat is still on its way to
        #: the water (``ElementParams.upper_dead_time_min``).
        self.cooling: list[ElementRun] = []
        #: The intervals running at the start, carried on from a walk
        #: that ended there.
        carried: list[HeatingInterval] = []
        if resume is not None:
            self._restore(resume, carried)
        self.modes: list[ModeInterval] = [ModeInterval(start, until, self.mode)]
        #: Draws not yet taken, onset order. Each is removed as a coast
        #: or a recovery takes it.
        self.draws = sorted(d for d in draws if start <= d[0] < until)
        self.withheld = sorted(withheld_windows)
        self.path: list[PathPoint] = [
            PathPoint(
                start,
                self.upper,
                self.lower,
                self.sp,
                running,
                0.0,
                mode=self.mode,
                layers_f=_layers_of(self.tank_state),
            )
        ]
        self.heating: list[HeatingInterval] = carried
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
        if resume is not None:
            # Settings that differ from where the walk ended were written
            # at its start.
            moved = setpoint_f != resume.controller.setpoint_f
            mode_moved = heater.mode != resume.controller.mode.commanded
            if moved or mode_moved:
                self.raw.insert(
                    0,
                    RawWrite(
                        start,
                        setpoint_f=setpoint_f if moved else None,
                        mode=heater.mode if mode_moved else None,
                        id=_SETTINGS_WRITE,
                    ),
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

    def _restore(self, resume: Resume, carried: list[HeatingInterval]) -> None:
        """The heater as a walk that ended at the start left it: its
        intervals running then carried on, each charged from here."""
        held = resume.controller.mode.held
        self.state = replace(
            resume.controller,
            mode=replace(
                resume.controller.mode,
                held=None if held is None else replace(held, ref=0),
                recorded=0 if held is None else 1,
            ),
        )
        if held is not None:
            assert resume.held_write is not None
            self.mode_writes.append(replace(resume.held_write))
        self.sp = resume.setpoint_f
        self.mode = resume.mode
        if resume.cycle is not None:
            assert resume.cycle.interval is not None
            interval = replace(
                resume.cycle.interval,
                end=self.t,
                input_wh=None if resume.cycle.input_wh is None else 0.0,
            )
            self.cycle = replace(
                resume.cycle, input_wh=interval.input_wh, interval=interval
            )
            carried.append(interval)
        if resume.element is not None:
            interval = replace(
                resume.element.interval, end=self.t, input_wh=0.0
            )
            self.element = replace(resume.element, interval=interval)
            carried.append(interval)
        self.cooling = list(resume.cooling)
        self._cold = resume.cold
        # What the heating carried on rests on, as where it began says.
        if self.cycle is not None:
            self.reasons.update(self.cycle.why)
        el = self.state.element
        if el.running and el.zone is not None:
            self.reasons.update(
                ctl.element_notes(el.zone, el.in_place, el.later)
            )
        if held is not None:
            assert resume.held_write is not None
            self.reasons.update(
                ctl.held_notes(
                    held.mode, entry=resume.held_write.owner != "raw"
                )
            )

    def _resume(self) -> Resume:
        """The heater now, for a walk from here to go on from."""
        held = self.state.mode.held
        cycle = self.cycle
        el = self.element
        return Resume(
            at=self.t,
            controller=self.state,
            setpoint_f=self.sp,
            mode=self.mode,
            cycle=None
            if cycle is None
            else replace(
                cycle,
                interval=None
                if cycle.interval is None
                else replace(cycle.interval),
            ),
            element=None
            if el is None
            else replace(el, interval=replace(el.interval)),
            cooling=tuple(
                e for e in self.cooling if self._heats_until(e) > self.t
            ),
            cold=self._cold,
            held_write=None
            if held is None
            else replace(self.mode_writes[held.ref]),
            disabled=ctl.disabled(self.state, self.settings),
        )

    # ── the tank ──

    @property
    def upper(self) -> float:
        """The upper probe on the tank now."""
        return self.probes[0]

    @property
    def lower(self) -> float:
        """The lower probe on the tank now."""
        return self.probes[1]

    def _set(self, state: TankState) -> None:
        """The tank is now ``state``."""
        self.tank_state = state
        self.probes = self.physics.observe(state)

    def _adopt(self, point: Point) -> None:
        """The tank is now the one at ``point``: its state, or where the
        engine made the point, the physics' estimate from its probes."""
        self._set(
            point.state
            if point.state is not None
            else self.physics.estimate(point.upper_f, point.lower_f)
        )

    def _running(self, at: datetime) -> Running:
        """What heats the tank from ``at``: the recovery's compressor,
        the element, and the elements whose heat is still on its way;
        credited none of it inside a withheld draw window."""
        cycle = self.cycle
        el = self.element
        return Running(
            compressor=None
            if cycle is None
            else CompressorRun(
                on_at=cycle.start.at,
                heats_at=cycle.heats_at,
                scale=cycle.scale,
                stirs=cycle.stirs,
            ),
            elements=(
                *(e for e in self.cooling if self._heats_until(e) > at),
                *(
                    ()
                    if el is None
                    else (ElementRun(zone=el.zone, on_at=el.on_at),)
                ),
            ),
            credited=self._withheld_at(at) is None,
        )

    def _heats_until(self, e: ElementRun) -> datetime:
        """When a stopped element's last heat reaches the water."""
        assert e.off_at is not None
        return e.off_at + self._lag(e.zone)

    def _advance(
        self,
        end: datetime,
        draws: Sequence[Draw] = (),
        stop: Stop | None = None,
    ) -> Stretch:
        """The tank walked from now to ``end`` under what runs now."""
        self.cooling = [
            e for e in self.cooling if self._heats_until(e) > self.t
        ]
        return self.physics.advance(
            self.t,
            self.tank_state,
            end,
            draws,
            running=self._running(self.t),
            stop=stop,
        )

    def _ahead(self, end: datetime, stop: Stop) -> Stretch:
        """The tank walked from now toward ``end`` under what runs now,
        credited or not on each side of the withheld windows' edges, to
        where ``stop`` holds. Nothing is drawn: a look ahead, not the
        walk."""
        edges = sorted(
            {x for w in self.withheld for x in w if self.t < x < end}
        )
        t, state = self.t, self.tank_state
        points: list[Point] = []
        for b in (*edges, end):
            part = self.physics.advance(
                t, state, b, running=self._running(t), stop=stop
            )
            points += part.points[1:] if points else part.points
            if part.stopped:
                return Stretch(points, stopped=True)
            t, state = part.end, part.state
        return Stretch(points)

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

    def _element_done(self, upper: float, lower: float) -> bool:
        """Whether the running element's zone is at its off point."""
        el = self.element
        if el is None or el.off is None:
            return False
        z = upper if el.zone == "upper" else lower
        return z >= el.off - ELEMENT_DONE_F

    def _stop(self) -> Stop:
        """Where a walk from now stops for the walk to look: the
        recovery at its stop level, the element at its off point, or,
        with nothing heating, the lower probe crossing an edge of the
        heat pump's water range, where its availability changes."""
        cycle = self.cycle
        level = None if cycle is None else cycle.stop_level
        water = (
            None
            if cycle is not None or self.element is not None
            else self._water_ok(self.lower)
        )

        def stop(upper: float, lower: float) -> bool:
            if level is not None and lower >= level:
                return True
            if self._element_done(upper, lower):
                return True
            return water is not None and self._water_ok(lower) != water

        return stop

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
            case ctl.StartElement(start, zone, live_at, _):
                self._begin_element(start, zone, live_at)
            case ctl.ElementRetarget(off):
                self._element_end(off)
            case ctl.StopElement(at, reason, _):
                self._stop_element(at, reason)
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

    def _append(self, points: Sequence[Point], heating: bool) -> None:
        """Extend the path with a walk's ``points``, charge their
        electricity (the compressor's to the recovery, the elements' to
        the one running), and take the tank where they end."""
        for k, p in enumerate(points):
            # The walk's start is where the path stands; two elements at
            # one instant later on are a draw's step, before and after.
            if p.at < self.path[-1].at or (k == 0 and p.at == self.path[-1].at):
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
                    _layers_of(p.state),
                )
            )
        cycle = self.cycle
        if cycle is not None and cycle.input_wh is not None:
            wh = [p.input_wh for p in points[1:]]
            cycle.input_wh = (
                None
                if any(x is None for x in wh)
                else cycle.input_wh + sum(x for x in wh if x is not None)
            )
        if self.element is not None:
            el = self.element.interval
            el.input_wh = (el.input_wh or 0.0) + sum(
                p.element_wh for p in points[1:]
            )
        self._adopt(points[-1])

    def _draws_in(self, start: datetime, end: datetime) -> slice:
        """Where the draws with onsets in ``[start, end)`` sit."""
        return slice(
            bisect_left(self.draws, start, key=_onset),
            bisect_left(self.draws, end, key=_onset),
        )

    def _take_draws(self, start: datetime, end: datetime) -> list[Draw]:
        """Remove and return the draws with onsets in ``[start, end)``."""
        at = self._draws_in(start, end)
        taken = self.draws[at]
        del self.draws[at]
        return taken

    def _peek_draws(self, end: datetime) -> list[Draw]:
        return self.draws[self._draws_in(self.t, end)]

    def _next_draw_after(self, at: datetime) -> datetime | None:
        """The first draw's onset after ``at``, if any is left."""
        k = bisect_right(self.draws, at, key=_onset)
        return self.draws[k][0] if k < len(self.draws) else None

    def _lag(self, zone: Literal["upper", "lower"]) -> timedelta:
        """How long an element's heat takes to reach the water."""
        return timedelta(
            minutes=self.ep.upper_dead_time_min if zone == "upper" else 0.0
        )

    # ── heating ──

    def _withheld_at(self, at: datetime) -> Window | None:
        return window_at(at, self.withheld)

    def _position(self) -> None:
        """Where the running recovery stops, from the tank now: the
        lower probe ``hp_stop_overshoot_f`` over its target, at most at
        the top of the heat pump's water range, unless the TOU cap stops
        it first (``controller.judge_cap``), judged on the walk to that
        stop from here.

        A recovery stops at the first instant it is inside a window with
        the lower probe at the cap's level (the target less
        ``tou_cap_f``). Reaching the level before the window opens, it
        runs on toward its stop and stops as the window opens; reaching
        it inside the window, it stops there (``controller.cap_outcome``).
        """
        cycle = self.cycle
        assert cycle is not None
        target = cycle.setpoint_f
        level = min(
            target + self.params.hp_stop_overshoot_f,
            self.params.hp_water_range_f[1],
        )
        cycle.stop_level, cycle.stop_at, cycle.capped = level, None, False
        if self.lower >= level:
            cycle.stop_at = self.t
            return
        ahead = self.t + RECOVERY_AHEAD
        if not any(w0 < ahead and self.t < w1 for w0, w1 in self.windows):
            return
        full = self._ahead(ahead, lambda _, lower: lower >= level)
        cap = judge_cap(
            full.points,
            at=self.t,
            lower_f=self.lower,
            target_f=target,
            windows=self.windows,
            params=self.params,
        )
        if cap.kind == "none":
            return
        window = cap.window
        assert window is not None
        if cap.kind == "at_level":
            # Already at the level inside the window: it does not heat.
            cycle.stop_at, cycle.capped = self.t, True
        else:
            reaches: datetime | None = None
            if self.lower < cap.level:
                walked = self._ahead(ahead, lambda _, lower: lower >= cap.level)
                reaches = walked.end if walked.stopped else ahead
            outcome = ctl.cap_outcome(reaches, window)
            if outcome == "until_open":
                cycle.stop_at, cycle.capped = window[0], True
            elif outcome == "to_level":
                cycle.stop_level, cycle.capped = cap.level, True

    def _begin(self, start: Start, *, hold: float) -> None:
        """The compressor starts (``controller.StartCompressor``),
        heating after ``hold`` minutes, at the pace a recovery model
        gives it (``TankPhysics.scale``)."""
        level = min(
            self.sp + self.params.hp_stop_overshoot_f,
            self.params.hp_water_range_f[1],
        )
        scale, confidence = 1.0, 1.0
        why: tuple[str, ...] = ()
        under_way = start.cause == "running" and not self.running_starts
        scaled = getattr(self.physics, "scale", None)
        if scaled is not None:
            got = scaled(
                self.t,
                self.tank_state,
                level,
                hold_minutes=hold,
                under_way=under_way,
            )
            scale, confidence = got.scale, got.confidence
            why = tuple(got.reasons)
            self.reasons.update(why)
        self.cycle = _Cycle(
            start=start,
            setpoint_f=self.sp,
            heats_at=self.t + timedelta(minutes=hold),
            stop_level=level,
            capped=False,
            scale=scale,
            confidence=confidence,
            why=why,
            stirs=not under_way or hold > 0.0,
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
        if interval.capped:
            # Said where the cap stops it, in the walk it stops in: not
            # one the walk ends before, nor a projection a draw undoes.
            self.reasons.add(TOU_CAP_PROJECTED)
        interval.input_wh = cycle.input_wh
        interval.confidence = cycle.confidence
        interval.final_target_f = cycle.setpoint_f
        # The heat map's water, judged over the whole run, as one walk
        # or a chain of them heats it: not each stretch an event cuts.
        judge = getattr(self.physics, "heating_reasons", None)
        if judge is not None:
            self.reasons.update(judge(cycle.heating_h, cycle.heating_mean_f_h))
        # A write that ends a recovery because the lower zone is already
        # at the new setpoint ends it at that target too.
        at_target = stop in ("target", "cap") or (
            stop == "write" and self.lower >= cycle.setpoint_f - 0.01
        )
        if at_target:
            self.reached.append((at, cycle.setpoint_f))
        self.cycle = None

    def _heat_until(self, end: datetime) -> None:
        """Run the cycle to ``end`` or to its own finish: the tank
        walked under the compressor to the cycle's stop, cut at each
        draw (taken at its instant, and the stop judged again from the
        tank it leaves), at each withheld window's edges, and where the
        upper zone reaches the element's later start
        (``controller.upper_on_crossing``)."""
        while self.cycle is not None and self.t < end:
            cycle = self.cycle
            now = self._take_draws(self.t, self.t + _INSTANT)
            if now:
                for _, gal in now:
                    self._set(self.physics.draw(self.t, self.tank_state, gal))
                self._step_point()
                # A draw can take the lower zone out of the heat pump's
                # range, which stops it.
                if self._check_availability():
                    continue
                self._position()
                self._element_trigger()
                continue
            if cycle.stop_at is not None and cycle.stop_at <= self.t:
                self._recovery_done()
                continue
            nxt = end if cycle.stop_at is None else min(end, cycle.stop_at)
            draw = self._next_draw_after(self.t)
            later = [] if draw is None or draw >= nxt else [draw]
            later += [x for w in self.withheld for x in w if self.t < x < nxt]
            nxt = min([nxt, *later])
            stretch = self._advance(nxt, stop=self._stop())
            element_at = upper_on_crossing(
                self.state, self.settings, stretch.points
            )
            if element_at is not None and element_at < stretch.end:
                # The upper zone reaches the element's later start on
                # the way: it starts there, as on a coast.
                upto = self._advance(element_at, stop=self._stop())
                self._append(upto.points, heating=True)
                self.reasons.update(upto.reasons)
                self._heated(cycle, upto)
                self.t = upto.end
                self._dispatch(ctl.UpperOnCrossed(at=self.t, tank=self._tank()))
                continue
            self._append(stretch.points, heating=True)
            self.reasons.update(stretch.reasons)
            self._heated(cycle, stretch)
            self.t = stretch.end
            self._element_boundary()
            if self.cycle is cycle and (
                self.lower >= cycle.stop_level
                or (cycle.stop_at is not None and self.t >= cycle.stop_at)
            ):
                self._recovery_done()

    @staticmethod
    def _heated(cycle: _Cycle, stretch: Stretch) -> None:
        cycle.heating_h += stretch.heating_h
        cycle.heating_mean_f_h += stretch.heating_mean_f_h

    def _recovery_done(self) -> None:
        """The running recovery is at its stop. Short of its target at
        the top of the heat pump's range, the elements finish it."""
        cycle = self.cycle
        assert cycle is not None
        short = self.lower < cycle.setpoint_f and not self._water_ok(self.lower)
        if not (short and self._check_availability()):
            self._dispatch(
                ctl.RecoveryDone(
                    at=self.t, tank=self._tank(), capped=cycle.capped
                )
            )

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
                layers_f=_layers_of(self.tank_state),
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
        """A TOU window closing at ``at``, then one opening there. A
        mode write held to ``at`` is to a window's close: one the walk
        resumed at, which its windows begin past."""
        held = self.state.mode.held
        if any(w[1] == at for w in self.windows) or (
            held is not None and held.until == at
        ):
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
    ) -> None:
        """An element starts (``controller.StartElement``): its heat
        reaches the water from ``live_at``, its dead time after its
        on-edge."""
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
        self.element = _Element(
            zone, interval, on_at=live_at - self._lag(zone), live_at=live_at
        )

    def _element_boundary(self) -> None:
        """At every boundary the running element's zone is read: at its
        off point it stops, otherwise it runs on (``_element_end``). Not
        at the walk's end, which takes nothing at its instant: a walk
        going on from there reads it first (``run``)."""
        if self.t >= self.until:
            return
        if self.element is not None:
            # An element ending as the heat pump returns hands over to it.
            self._check_availability()
        if self.element is not None:
            self._dispatch(ctl.ElementCheck(at=self.t, tank=self._tank()))

    def _element_end(self, off: float) -> None:
        """The running element runs to ``off`` in its zone: the walk
        stops there (``_stop``)."""
        el = self.element
        assert el is not None
        el.off = off

    def _stop_element(self, at: datetime, stop: StopReason) -> None:
        """An element stops (``controller.StopElement``). Its heat still
        on its way reaches the water over its dead time."""
        el = self.element
        assert el is not None
        self.element = None
        if self._lag(el.zone) > timedelta(0):
            self.cooling.append(
                ElementRun(zone=el.zone, on_at=el.on_at, off_at=at)
            )
        el.interval.end = at
        el.interval.stop = stop
        el.interval.final_target_f = self.sp

    # ── the walk ──

    def run(self) -> Simulation:
        if self.resumed is not None:
            # Going on from a walk that ended here, whose own end took
            # nothing at this instant: it is any later one, met at the
            # end of a segment (``_element_boundary``, ``_at_event``).
            self._element_boundary()
            self._at_event(self.t)
        else:
            self._begin_walk()
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
        resume = self._resume()
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
            resume,
        )

    def _begin_walk(self) -> None:
        """The walk's start, from the heater as the caller gives it."""
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

    def _upcoming(self) -> set[datetime]:
        """Every instant the walk must stop at next: the controller's
        (``controller.wake_times``), and the walk's own."""
        upcoming = set(self.marks)
        upcoming.update(fires for fires, _ in self.queue)
        upcoming |= wake_times(self.state, self.settings)
        if self.element is not None or any(
            self._heats_until(e) > self.t for e in self.cooling
        ):
            # Inside a withheld window an element's heat, running or on
            # its way, is credited none.
            for w0, w1 in self.withheld:
                upcoming.update((w0, w1))
        if self.raw:
            upcoming.add(self.raw[0].at)
        for a, b in self.air_out:
            upcoming.update((a, b))
        return {t for t in upcoming if t > self.t}

    def _trigger_ahead(self, stretch: Stretch) -> ctl.Ahead | None:
        """The heater's own start on ``stretch``
        (``controller.trigger_ahead``)."""
        ahead, notes = trigger_ahead(
            self.state,
            self.settings,
            self.params,
            [(p.at, p.upper_f, p.lower_f) for p in stretch.points],
            stretch.impulses,
            self.t,
        )
        self.reasons.update(notes)
        return ahead

    def _coast_until(self, end: datetime) -> None:
        """The tank with no recovery running, to ``end``, or to where
        the heater starts itself, an element's later start reads its
        zone, the running element reaches its off point, or the water
        leaves or enters the heat pump's range, whichever is first."""
        stretch = self._coast_stretch(end)
        at: datetime | None = None
        own = self._trigger_ahead(stretch)
        if own is not None:
            if own.starts_at >= stretch.end:
                # Inside the restart lockout, starting past this
                # segment: carried to it as a pending start, the instant
                # it is due at, since a later segment's coast may begin
                # outside the window it fired in.
                self._dispatch(
                    ctl.TriggerDeferred(
                        at=self.t,
                        starts_at=own.starts_at,
                        trigger=own.trigger,
                    )
                )
            else:
                at = own.starts_at
        element_at = upper_on_crossing(
            self.state, self.settings, stretch.points
        )
        if (
            element_at is not None
            and element_at < stretch.end
            and (at is None or element_at < at)
        ):
            self._coast_to(element_at)
            if any(d[0] == element_at for d in self.draws):
                # The crossing is the draw's there: the element answers
                # the tank it leaves.
                self._coast_draw()
            self._dispatch(ctl.UpperOnCrossed(at=element_at, tank=self._tank()))
            return
        if at is not None:
            assert own is not None
            self._coast_to(at)
            if ctl.heats_as(self.state) == ctl.ELECTRIC and any(
                d[0] <= at for d in self.draws
            ):
                # The elements answer from the tank a draw landing here
                # leaves (``controller.electric_entry``), which may be
                # back in the heat pump's range.
                self._coast_draw()
                self._check_availability()
                if ctl.heats_as(self.state) != ctl.ELECTRIC:
                    # Back in range: the trigger is the heat pump's, with
                    # its lockout, found afresh from here.
                    return
            self._dispatch(
                ctl.HeaterTrigger(at=at, tank=self._tank(), trigger=own.trigger)
            )
            return
        # A stop a draw met ends the walk on the draw's step: it is taken.
        points = stretch.points
        taken = (
            stretch.stopped and len(points) > 1 and points[-2].at == stretch.end
        )
        self._take_draws(
            self.t, stretch.end + (_INSTANT if taken else timedelta(0))
        )
        self._append(stretch.points, heating=False)
        self.t = stretch.end

    def _coast_stretch(self, end: datetime) -> Stretch:
        """The tank walked from now toward ``end`` under what runs now,
        to where the coast's stop holds, as ``_advance`` walks it: in
        pieces to a mark of the clock's grid, which are the walk whole,
        the first ``_COAST_AHEAD`` and each later twice the last, and no
        further than the piece the heater's own start is triggered in.

        Each of its rules finds its instant from the tank up to it, so a
        start triggered short of a piece's end, and starting short of it,
        is the one the walk to ``end`` finds; but not with a draw on the
        piece's end, which the rules read with the step before it. With
        TOU windows that overlap, the upper zone's start at one's opening
        needs the whole walk. With only an element's later start found,
        the walk goes on to ``end``: the coast plans the heater's own
        start too where the whole walk finds one, past the element's."""
        self.cooling = [
            e for e in self.cooling if self._heats_until(e) > self.t
        ]
        running = self._running(self.t)
        stop = self._stop()
        t, state = self.t, self.tank_state
        points: list[Point] = []
        trajectory: list[tuple[datetime, float, float]] = []
        impulses: list[Impulse] = []
        ahead = _COAST_AHEAD
        while True:
            upto = min(
                end,
                _EPOCH
                + IDLE_STEP * math.floor((t + ahead - _EPOCH) / IDLE_STEP),
            )
            # Each piece twice the last, so the rules' searches over the
            # walk so far cost the walk once over.
            ahead *= 2
            part = self.physics.advance(
                t,
                state,
                upto,
                self.draws[self._draws_in(t, upto)],
                running=running,
                stop=stop,
                walk_from=self.t,
            )
            new = part.points[1:] if points else part.points
            points += new
            trajectory += [(p.at, p.upper_f, p.lower_f) for p in new]
            # At the instant pieces meet, the draws there (the new
            # piece's) come before the flow's drop over the step ending
            # there (the last piece's), as one walk orders them.
            at_t = [i for i in impulses if i.at == t]
            impulses = [i for i in impulses if i.at < t] + [
                *(i for i in part.impulses if i.at == t),
                *at_t,
                *(i for i in part.impulses if i.at > t),
            ]
            stretch = Stretch(points, stopped=part.stopped, impulses=impulses)
            if part.stopped or part.end >= end:
                return stretch
            own, _ = trigger_ahead(
                self.state,
                self.settings,
                self.params,
                trajectory,
                impulses,
                self.t,
            )
            if (
                own is not None
                and own.trigger_at < upto
                and own.starts_at < upto
                and not self.draws[self._draws_in(upto, upto + _INSTANT)]
                and not (
                    own.trigger == "upper_at_tou_open"
                    and _overlapping(self.settings.tou_windows)
                )
            ):
                # A draw at the piece's end is the next piece's, but the
                # rules read the drops at a step's end with the step.
                # Overlapping windows: the upper zone's start is the
                # first window's that it crosses in, which may cross
                # past the piece after a later window opened in it.
                return stretch
            t, state = part.end, part.state

    def _coast_draw(self) -> None:
        """The draws at this instant, taken here: the path has the tank
        before and after."""
        for _, gal in self._take_draws(self.t, self.t + _INSTANT):
            self._set(self.physics.draw(self.t, self.tank_state, gal))
        self.path.append(
            PathPoint(
                self.t,
                self.upper,
                self.lower,
                self.sp,
                self.element is not None,
                0.0,
                mode=self.mode,
                layers_f=_layers_of(self.tank_state),
            )
        )

    def _coast_to(self, at: datetime) -> None:
        """The tank walked to ``at`` exactly, taking the draws before
        it."""
        if at > self.t:
            upto = self._advance(at, self._take_draws(self.t, at))
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
    start_hold: Callable[[float | None], float] | None = None,
    running_hold: float = 0.0,
    running_starts: bool = False,
    controller: ControllerParams | None = None,
    state: TankState | None = None,
    resume: Resume | None = None,
) -> Simulation:
    """Walk the heater from ``start`` to ``until``, its reservation
    list holding ``entries``, from the tank ``state``, or with none,
    the one ``physics`` makes of the probes ``upper_f`` and ``lower_f``
    (``Physics.estimate``).

    ``draws`` are the scenario's draws (delivered gallons at their
    onsets). A coast takes the ones it spans; a recovery takes each of
    the others at its onset and walks on from the tank it leaves.
    ``withheld_windows`` are the forecast draw windows over which a
    recovery or an element is credited no heat: it runs and is charged,
    and the tank coasts. ``marks`` are instants the path must carry an
    element at, so the tank there is read exactly rather than
    interpolated across a step. ``element_running``: an element is on at
    the start (in an element mode, ``heater.mode``);
    ``element_running_since`` its on-edge, when known, which leaves it
    the rest of its dead time (unknown: past it). ``raw_writes`` are
    replayed as made (calibration only): a caller never passes them
    with entries.
    ``stopped_at`` is the compressor's last stop before ``start``, which
    seeds the restart lockout. ``start_hold`` is the hold a compressor
    start begins with, minutes, by the minutes since the compressor last
    stopped (None when not known); None holds none. A compressor already
    ``running`` holds for ``running_hold``, what is left of its own
    start's hold (0.0: none); its heating has begun, its layers stirred,
    unless some of that hold is left or ``running_starts`` (it starts at
    ``start``, as a recorded start replayed). ``controller`` holds the
    numbers of the firmware's rules (``sim/controller.py``); None, the
    measured defaults.

    ``resume`` (``Simulation.resume`` of a walk that ended at ``start``)
    goes on from where that walk left the heater, as if it had not
    ended: ``running``, ``element_running`` and its since, ``stopped_at``
    and ``running_hold`` are its, not the caller's. A ``setpoint_f`` or
    a ``heater.mode`` other than the one it left is written at the start
    (a raw write, ``id`` ``"settings"``). The tank is ``state``'s, or the
    probes', as for any walk.
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
        start_hold=start_hold,
        running_hold=running_hold,
        running_starts=running_starts,
        controller=controller,
        state=state,
        resume=resume,
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
