"""The heater's firmware, as a state machine.

Every rule that decides when this heater's compressor and elements start
and stop, which mode is in force and which setpoint, is a transition
here: ``transition(state, event, settings, params)`` gives the state
after an event and the actions the heater takes, and nothing else. It
performs no I/O, reads no clock and keeps no state between calls. The
engine (``sim/engine.py``) is the event walk: it finds the next
event, moves the tank to it with the physics, applies ``transition``
and carries out the actions.

**The state** (``State``):

- the compressor (``Compressor.phase``): ``idle``; ``locked_out`` for
  the restart lockout after a stop; ``holding`` its start's hold;
  ``heating``; ``capped``, stopped short of its target by the TOU cap
  until the window closes. A start waiting out its lag or the lockout
  is ``pending``;
- the elements (``Element.phase``): ``off``; ``dead_time`` from an
  upper element's on-edge; ``heating``, in the ``upper`` or ``lower``
  zone;
- the mode (``ModeState``): the one in force, the one last written,
  and a write ``held`` until its window closes;
- the setpoint in force.

The timed phases (the lockout, the start's hold, an element's dead
time) end at their instants; ``transition`` moves them on at the first
event at or after it, which is how they are observed.

**The events** (``Event``): the walk begins (``Begins``,
``ElementWasOn``); a reservation entry fires (``EntryFires``); a direct
setpoint or mode write (``RawWrites``, ``SetpointWrite``,
``ModeWrite``); a TOU window opens or closes (``WindowOpens``,
``WindowCloses``); the heater's own trigger, the lower zone through
``hp_lower_on`` or the upper zone short at a window
(``HeaterTrigger``, and ``TriggerDeferred`` for one inside the
lockout); the upper zone at ``he_upper_on`` (``UpperRead``,
``UpperOnCrossed``); a recovery or an element run reaching its target
(``RecoveryDone``, ``ElementCheck``); a start coming due
(``StartDue``); the lockout, the start's hold or the dead time ending
(``LockoutEnds``, ``StartHoldEnds``, ``DeadTimeEnds``); the walk's end
(``Horizon``).

**The rules**, each a function below named for it, with its measurement:

- **Its own triggers** (``sim/tou_triggers.py``): the lower zone
  reaching ``hp_lower_on``, held over a TOU window to its close, and the
  upper zone far short of the setpoint inside a window. In
  ``heat_pump`` the lower trigger waits while the upper zone is at or
  above the setpoint (a device test, 2026-10-03). A trigger inside the
  restart lockout starts the compressor when the lockout ends.
- **Starts caused by writes.** Outside a TOU window, a setpoint
  write leaving the upper zone below the new setpoint started the
  compressor in 118 of 120 writes, ``write_start_lag_s`` later
  (``ControllerParams``); mode writes by rules of their own.
- **Reservation entries** fire in their minute whatever runs,
  setting the setpoint, then the mode; skipped in Vacation. Powered
  off, one fires and turns the heater on (a device test, 2026-09-24),
  judged as a mode write out of power-off. On a heater that is on, one
  repeating its state starts nothing.
- **The TOU cap**, judged at the recovery's end
  (``judge_cap``): one ending inside a window stops ``tou_cap_f``
  short of its target.
- **Mode writes** are held inside a TOU window (an entry's,
  whatever the mode; a direct write's, an element mode's), landing at
  the window's end unless withdrawn, and charged a start; a running
  element mode is dropped at a window's start.
- **The elements:** on entry to a mode at the mode's deficit, later in
  a stint as the upper zone reaches Energy Saver's ``he_upper_on`` or
  falls High Demand's re-engagement short of the setpoint, and on a
  setpoint raise; each runs to its off point (Energy Saver's upper
  element 1.62 °F short of the setpoint), Electric's lower element
  after its upper.

How the tank moves between events, and how far a recovery or an element
lifts it, is the physics': the controller reads the tank at each event
(``Tank``) and the predicted path where a rule is judged along it
(``trigger_ahead``, ``upper_on_crossing``, ``judge_cap``).
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from itertools import pairwise
from types import MappingProxyType
from typing import Any, Final, Literal

from nwp500.sim.decay import Impulse
from nwp500.sim.params import ControllerParams, ElementParams
from nwp500.sim.physics.element import (
    DEVICE_MODE,
    ElementMode,
    HeaterMode,
    entry_bracket_f,
    entry_deficit_f,
    upper_off_deficit_f,
)
from nwp500.sim.tank_physics import Point, point_at
from nwp500.sim.tou_triggers import (
    LOWER_TRIGGER_HELD,
    Trigger,
    Window,
    heater_start,
)

# ── Vocabulary ──────────────────────────────────────────────────────

#: The heater's modes, by the names the simulation speaks.
HEAT_PUMP: Final = "heat_pump"
ENERGY_SAVER: Final = "energy_saver"
HIGH_DEMAND: Final = "high_demand"
ELECTRIC: Final = "electric"
ELEMENT_MODES: frozenset[str] = frozenset({ENERGY_SAVER, HIGH_DEMAND, ELECTRIC})
COMPRESSOR_MODES: frozenset[str] = frozenset(
    {HEAT_PUMP, ENERGY_SAVER, HIGH_DEMAND}
)
#: A write into these out of ``electric`` started the compressor
#: whatever the tank (4 of 4; flagged, the sample is small;
#: ``ControllerParams``).
ELECTRIC_EXIT: frozenset[str] = frozenset({ENERGY_SAVER, HIGH_DEMAND})

#: An element whose zone is this close to its target has finished: the
#: walk does not chase the last fraction of a degree a coast's loss
#: leaves.
ELEMENT_DONE_F = 0.05

#: The reason a recovery capped short of its target carries.
TOU_CAP_PROJECTED = "tou_cap_projected"
#: A reservation entry turned a powered-off heater on: seen in two device
#: runs, with what follows judged as a mode write (``_entry_fires``).
POWERED_ON_BY_ENTRY = "powered_on_by_entry"

StartCause = Literal["heater", "write", "running"]
Source = Literal["compressor", "element"]
#: What started an element, when the heater did: Energy Saver's upper
#: zone reaching ``he_upper_on`` later in a stint; High Demand's upper
#: zone falling ``upper_reengages_below_setpoint_f`` short later in a
#: stint; Electric's lower element taking over from the upper; a
#: dropped element mode's re-evaluation (a compressor start).
ElementTrigger = Literal[
    "energy_saver_upper_on",
    "high_demand_upper_short",
    "electric_lower_after_upper",
    "mode_dropped",
]
StopReason = Literal["target", "cap", "write", "mode", "horizon"]
#: How a mode interval ended: a write, the heater dropping the mode at a
#: window, or the horizon.
ModeEnd = Literal["write", "dropped", "horizon"]
#: Who made a write: the entries under evaluation (``plan``), or ``raw``
#: for a write replayed as made.
Owner = Literal["plan", "raw"]
Zone = Literal["upper", "lower"]
CompressorPhase = Literal["idle", "locked_out", "holding", "heating", "capped"]
ElementPhase = Literal["off", "dead_time", "heating"]


@dataclass(frozen=True)
class Start:
    at: datetime
    cause: StartCause
    #: The heater's own trigger, when ``cause`` is ``heater``.
    trigger: Trigger | ElementTrigger | None = None
    #: The entry or raw write whose write caused it (its ``id``),
    #: when ``cause`` is ``write``.
    serves: str | None = None
    #: What started: the compressor or an element.
    source: Source = "compressor"


@dataclass(frozen=True)
class Tank:
    """The probes at an event: the upper and the lower zone, °F."""

    upper_f: float
    lower_f: float


# ── State ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Compressor:
    phase: CompressorPhase = "idle"
    #: The start of the run in progress; None while it is off.
    start: Start | None = None
    #: When the start's hold ends (``holding``): the firmware's clock,
    #: from the start. Draws that hold the climb longer are the
    #: physics' (the recovery's path), not a state of the firmware.
    hold_until: datetime | None = None
    #: When it last stopped, which the restart lockout counts from.
    last_stop: datetime | None = None
    #: When a recovery last reached its end: a trigger cannot read the
    #: tank it left at that same instant.
    finished_at: datetime | None = None
    #: The close of the window a capped stop came in (``capped``).
    capped_until: datetime | None = None
    #: A start waiting out its lag or the lockout.
    pending: Start | None = None

    @property
    def running(self) -> bool:
        return self.start is not None


@dataclass(frozen=True)
class Element:
    phase: ElementPhase = "off"
    zone: Zone | None = None
    #: When its zone starts to rise: the on-edge plus the dead time for
    #: an upper element; the on-edge itself for the lower element.
    live_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self.phase != "off"


@dataclass(frozen=True)
class Held:
    """A mode write held inside a TOU window."""

    mode: HeaterMode
    serves: str | None
    #: The window's close, where it lands unless withdrawn.
    until: datetime
    #: Its place among the mode writes recorded (``RecordModeWrite``).
    ref: int


@dataclass(frozen=True)
class ModeState:
    #: The mode in force.
    in_force: HeaterMode
    #: The one last written, which a held write makes differ from it.
    commanded: HeaterMode
    held: Held | None = None
    #: How many mode writes were recorded: the next one's ``ref``.
    recorded: int = 0


@dataclass(frozen=True)
class State:
    setpoint_f: float
    mode: ModeState
    compressor: Compressor = field(default_factory=Compressor)
    element: Element = field(default_factory=Element)
    #: A powered-off heater an entry has turned on (``_entry_fires``).
    powered_on: bool = False


@dataclass(frozen=True)
class Settings:
    """The heater's own settings and what the caller supplies of it."""

    #: The lower zone's turn-on setting; None when unreadable, which
    #: disables the lower trigger.
    hp_lower_on_f: float | None
    #: The TOU windows in force: the device's, while its switch is on.
    tou_windows: tuple[Window, ...] = ()
    #: VACATION or POWER_OFF: nothing starts. In Vacation the device
    #: skips each entry as its minute passes, and does not run it late
    #: (a device test, 2026-09-24); powered off (``powered_off``) an
    #: entry fires and turns the heater on (the same test, two runs).
    heating_disabled: bool = False
    #: The heater is powered off, which is why heating is disabled.
    powered_off: bool = False
    #: The elements' thresholds and dead time.
    element: ElementParams = field(default_factory=ElementParams)
    #: The hold a compressor start begins with, minutes, by the minutes
    #: since it last stopped (None when not known): a fitted function
    #: the caller supplies. None holds none.
    start_hold: Callable[[float | None], float] | None = None


def initial_state(
    *,
    at: datetime,
    setpoint_f: float,
    mode: HeaterMode,
    running: bool,
    stopped_at: datetime | None,
    params: ControllerParams,
) -> State:
    """The heater at the walk's start. The compressor's last stop is the
    record's off-edge before the start (one stopped a minute before is
    still locked out); one running has no stop in force. A running
    compressor starts with ``Begins``."""
    last = (
        None if running or stopped_at is None or stopped_at > at else stopped_at
    )
    c = Compressor(last_stop=last)
    return State(
        setpoint_f,
        ModeState(mode, mode),
        replace(c, phase=_off_phase(c, at, params)),
        Element(),
    )


# ── Events ──────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class Event:
    at: datetime
    #: The probes at ``at``; the engine fills it for an event it is
    #: handed back (``Then``).
    tank: Tank | None = None


@dataclass(frozen=True, kw_only=True)
class Begins(Event):
    """The walk begins: the compressor running, and what is left of its
    start's hold, minutes."""

    running: bool = False
    running_hold: float = 0.0


@dataclass(frozen=True, kw_only=True)
class ElementWasOn(Event):
    """An element was on at the walk's start; ``since`` its on-edge,
    when known."""

    since: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class EntryFires(Event):
    """A reservation entry fires in its minute. ``ref`` is the
    caller's handle for it, carried to ``EntryFired``/``EntrySkipped``."""

    setpoint_f: float | None
    mode: HeaterMode | None
    serves: str | None = None
    ref: int = 0


@dataclass(frozen=True)
class Written:
    """A direct write as it was made: a setpoint, a mode, or both."""

    setpoint_f: float | None
    mode: HeaterMode | None
    serves: str | None = None


@dataclass(frozen=True, kw_only=True)
class RawWrites(Event):
    """Every direct write made at one instant."""

    writes: tuple[Written, ...]


@dataclass(frozen=True, kw_only=True)
class SetpointWrite(Event):
    """A direct setpoint write. ``mode_follows``: a mode write at the
    same instant changes the mode, whose own rules then decide the
    elements. ``mode`` is what the write carried, for its record."""

    setpoint_f: float
    serves: str | None = None
    mode_follows: bool = False
    mode: HeaterMode | None = None


@dataclass(frozen=True, kw_only=True)
class ModeWrite(Event):
    mode: HeaterMode
    owner: Owner
    serves: str | None = None


@dataclass(frozen=True, kw_only=True)
class WindowOpens(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class WindowCloses(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class HeaterTrigger(Event):
    """The heater's own trigger starts the compressor now: found
    on the coast by ``trigger_ahead``, the lockout already waited."""

    trigger: Trigger | None


@dataclass(frozen=True, kw_only=True)
class TriggerDeferred(Event):
    """A trigger on the coast ahead falls in the restart lockout, and
    its start, at ``starts_at``, beyond where this coast stops: it waits
    as a pending start, unless it is at or past ``horizon``."""

    starts_at: datetime
    trigger: Trigger | None
    horizon: datetime


@dataclass(frozen=True, kw_only=True)
class StartDue(Event):
    """A pending start's instant."""


@dataclass(frozen=True, kw_only=True)
class UpperRead(Event):
    """The upper zone read at an instant, for a later element start in
    Energy Saver or High Demand."""


@dataclass(frozen=True, kw_only=True)
class UpperOnCrossed(Event):
    """A coast took the upper zone down to where the mode's element
    starts later in a stint (found by ``upper_on_crossing``)."""


@dataclass(frozen=True, kw_only=True)
class ElementCheck(Event):
    """The running element's zone read: at its off point, it stops."""


@dataclass(frozen=True, kw_only=True)
class RecoveryDone(Event):
    """A recovery reached the end of its path: its target, or the cap's
    level (``capped``, judged by ``judge_cap``)."""

    capped: bool = False


@dataclass(frozen=True, kw_only=True)
class LockoutEnds(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class StartHoldEnds(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class DeadTimeEnds(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class Horizon(Event):
    """The walk's end: whatever runs is cut there."""


# ── Actions ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Note:
    """A reason the projection carries."""

    reason: str


@dataclass(frozen=True)
class SetpointSet:
    at: datetime
    setpoint_f: float


@dataclass(frozen=True)
class StartCompressor:
    start: Start
    #: A start from off, charged its start-up; False for one running at
    #: the walk's start.
    startup: bool
    #: Its hold, minutes.
    hold_min: float


@dataclass(frozen=True)
class StopCompressor:
    at: datetime
    reason: StopReason


@dataclass(frozen=True)
class Retarget:
    """The running recovery's target moved: place it again."""

    at: datetime


@dataclass(frozen=True)
class StartElement:
    start: Start
    zone: Zone
    live_at: datetime
    #: Minutes it has run by ``start.at``, from its on-edge.
    credited_min: float


@dataclass(frozen=True)
class ElementRetarget:
    """The running element runs on to ``off_f`` in its zone."""

    off_f: float


@dataclass(frozen=True)
class StopElement:
    at: datetime
    reason: StopReason
    #: The mode whose upper element stopped short of the setpoint, so
    #: its zone coasts on with the heat in transit; None when it does
    #: not.
    coast_mode: ElementMode | None = None


@dataclass(frozen=True)
class ModeSet:
    at: datetime
    mode: HeaterMode
    ended_by: ModeEnd


@dataclass(frozen=True)
class RecordModeWrite:
    at: datetime
    mode: HeaterMode
    owner: Owner
    serves: str | None


@dataclass(frozen=True)
class ModeHeld:
    ref: int


@dataclass(frozen=True)
class ModeTook:
    ref: int
    at: datetime


@dataclass(frozen=True)
class ModeWithdrawn:
    ref: int
    at: datetime


@dataclass(frozen=True)
class Dropped:
    at: datetime
    mode: HeaterMode


@dataclass(frozen=True)
class EntryFired:
    ref: int


@dataclass(frozen=True)
class EntrySkipped:
    ref: int


@dataclass(frozen=True)
class RecordWrite:
    """A direct setpoint write that applied."""

    at: datetime
    setpoint_f: float
    mode: HeaterMode | None
    serves: str | None


@dataclass(frozen=True)
class Then:
    """Hand ``event`` back once the actions before it are carried out,
    with the tank as they leave it."""

    event: Event


Action = (
    Note
    | SetpointSet
    | StartCompressor
    | StopCompressor
    | Retarget
    | StartElement
    | ElementRetarget
    | StopElement
    | ModeSet
    | RecordModeWrite
    | ModeHeld
    | ModeTook
    | ModeWithdrawn
    | Dropped
    | EntryFired
    | EntrySkipped
    | RecordWrite
    | Then
)


# ── The transition ──────────────────────────────────────────────────


def disabled(state: State, settings: Settings) -> bool:
    """Whether heating is disabled now: Vacation, or powered off with no
    entry having turned the heater on."""
    return settings.heating_disabled and not (
        settings.powered_off and state.powered_on
    )


class _Step:
    """One transition under way: the state as the rules move it, and
    the actions they take, in order."""

    def __init__(
        self,
        state: State,
        event: Event,
        settings: Settings,
        params: ControllerParams,
    ) -> None:
        self.state = state
        self.at = event.at
        self.tank = event.tank
        self.settings = settings
        self.params = params
        self.actions: list[Action] = []

    @property
    def upper(self) -> float:
        assert self.tank is not None
        return self.tank.upper_f

    @property
    def lower(self) -> float:
        assert self.tank is not None
        return self.tank.lower_f

    @property
    def sp(self) -> float:
        return self.state.setpoint_f

    @property
    def mode(self) -> HeaterMode:
        return self.state.mode.in_force

    @property
    def disabled(self) -> bool:
        return disabled(self.state, self.settings)

    def act(self, action: Action) -> None:
        self.actions.append(action)

    def note(self, reason: str) -> None:
        self.actions.append(Note(reason))

    def compressor(self, **kw: Any) -> None:
        self.state = replace(
            self.state, compressor=replace(self.state.compressor, **kw)
        )

    def modes(self, **kw: Any) -> None:
        self.state = replace(self.state, mode=replace(self.state.mode, **kw))

    def pend(self, start: Start | None) -> None:
        self.compressor(pending=start)

    def in_tou(self) -> bool:
        return window_at(self.at, self.settings.tou_windows) is not None


def transition(
    state: State,
    event: Event,
    settings: Settings,
    params: ControllerParams,
) -> tuple[State, tuple[Action, ...]]:
    """The heater's state after ``event``, and the actions it takes, in
    the order it takes them."""
    s = _Step(_advance(state, event.at, params), event, settings, params)
    _HANDLERS[type(event)](s, event)
    return s.state, tuple(s.actions)


def _advance(state: State, at: datetime, params: ControllerParams) -> State:
    """The timed phases at ``at``: the lockout over, the start's hold
    over, the window a capped stop came in closed, the dead time
    over."""
    c = state.compressor
    if c.running:
        if (
            c.phase == "holding"
            and c.hold_until is not None
            and at >= c.hold_until
        ):
            c = replace(c, phase="heating")
    else:
        c = replace(c, phase=_off_phase(c, at, params))
    e = state.element
    if e.phase == "dead_time" and e.live_at is not None and at >= e.live_at:
        e = replace(e, phase="heating")
    if c is state.compressor and e is state.element:
        return state
    return replace(state, compressor=c, element=e)


def _off_phase(
    c: Compressor, at: datetime, params: ControllerParams
) -> CompressorPhase:
    if c.capped_until is not None and at < c.capped_until:
        return "capped"
    if c.last_stop is not None and at < c.last_stop + params.restart_lockout:
        return "locked_out"
    return "idle"


# ── The compressor ──


def not_before(
    state: State, params: ControllerParams, at: datetime
) -> datetime:
    """``at``, or the end of the restart lockout if that is later: after
    it stops, the compressor does not start again for
    ``restart_lockout_s`` (two device-run restarts on 2026-09-23 came
    5 min 28 s and 5 min 31 s after the stop)."""
    last = state.compressor.last_stop
    if last is None:
        return at
    return max(at, last + params.restart_lockout)


def _start_compressor(
    s: _Step,
    start: Start,
    *,
    startup: bool = True,
    hold: float | None = None,
) -> None:
    """The compressor starts. A start holds before the lower zone
    climbs, the longer the longer the compressor was off;
    one already running at the walk's start holds for what is left of
    its own. Then the element's later start reads the upper zone, as at
    any instant of a stint (``_read_upper``); not for one running at the
    walk's start, which the walk reads once an element on then is
    restored (``ElementWasOn``)."""
    c = s.state.compressor
    if hold is None:
        hold = 0.0
    if startup and s.settings.start_hold is not None:
        gap = (
            None
            if c.last_stop is None
            else (s.at - c.last_stop).total_seconds() / 60.0
        )
        hold = s.settings.start_hold(gap)
    s.compressor(
        phase="holding" if hold > 0.0 else "heating",
        start=start,
        hold_until=s.at + timedelta(minutes=hold),
        capped_until=None,
    )
    s.act(StartCompressor(start, startup, hold))
    if start.cause != "running":
        _read_upper(s)


def _stop_compressor(s: _Step, reason: StopReason) -> None:
    """The compressor stops, and the restart lockout counts from here;
    stopped by the cap, it is ``capped`` until the window closes."""
    window = (
        window_at(s.at, s.settings.tou_windows) if reason == "cap" else None
    )
    c = replace(
        s.state.compressor,
        start=None,
        hold_until=None,
        last_stop=s.at,
        finished_at=s.at,
        capped_until=None if window is None else window[1],
    )
    s.state = replace(
        s.state, compressor=replace(c, phase=_off_phase(c, s.at, s.params))
    )
    s.act(StopCompressor(s.at, reason))


def _would_stop(s: _Step, value: float, previous: float) -> bool:
    """Whether a setpoint of ``value``, replacing ``previous``, ends the
    running recovery. A lowering to at or below the upper zone ends the
    call for heat (19 of 25 on the record, and both device runs of
    2026-09-23). A raise does not: the recovery was running with the
    setpoint lower still, so the call was the lower zone's, which a
    raise does not end. And the lower zone already at the new setpoint,
    which is the cap's level inside a TOU window, is a finished
    recovery."""
    cap = s.params.tou_cap_f if s.in_tou() else 0.0
    lowered = value < previous and value <= s.upper
    return lowered or s.lower >= value - cap


def _write_starts(s: _Step, value: float, previous: float) -> bool:
    """Whether a write of ``value`` over ``previous`` starts the
    compressor: outside a TOU window when it leaves the upper zone
    short of the new setpoint (118 of 120); inside one when it leaves it
    more than ``window_write_starts_f`` short (16 of 17). The cases the
    record is thin on are flagged: outside a window a raise that leaves
    the tank at or above the setpoint (n = 1, and it started), and
    inside one a write 0-4 °F short (3 of 15). A lowering that leaves
    the tank at or above the setpoint is not flagged: 0 of 15 started
    (the hold-off of the 2026-10-03 device test among them)."""
    if s.disabled or s.mode == ELECTRIC:
        return False
    short = value - s.upper
    if not s.in_tou():
        if short <= 0 and value >= previous:
            s.note("write_start_uncertain")
        return short > 0
    if 0 < short <= s.params.window_write_starts_f:
        s.note("write_start_uncertain")
    return short > s.params.window_write_starts_f


def _write_start(s: _Step, serves: str | None) -> Start:
    """A write's start: ``write_start_lag_s`` after it (a median 30 s),
    or when the lockout ends."""
    return Start(
        not_before(s.state, s.params, s.at + s.params.write_start_lag),
        "write",
        serves=serves,
    )


def _mode_write_starts(s: _Step, mode: str, previous: str) -> bool:
    """Whether ``mode`` taking effect, out of ``previous``, starts the
    compressor (``ControllerParams``' record of 91 mode writes).
    Inside a window a change to ``heat_pump`` (a dropped element mode)
    is judged as a setpoint write is there (``window_write_starts_f``):
    the one device run, a drop 9.5 °F short, started it 21-32 s later
    (2026-09-20 01:35 UTC). A lower zone short of the setpoint
    (``mode_write_lower_starts_f``) starts it out of an element mode,
    whatever the upper zone, and otherwise only with the upper zone
    short too: Energy Saver landing out of ``heat_pump`` at a window's
    close, the upper zone 18.7 °F above the setpoint and the lower
    20.9 °F under it, started nothing (2026-09-21 04:00 UTC). The thin
    cases are flagged."""
    if s.disabled or mode not in COMPRESSOR_MODES:
        return False
    p = s.params
    short = s.sp - s.upper
    if s.in_tou():
        if short <= p.window_write_starts_f:
            s.note("write_start_uncertain")
        return short > p.window_write_starts_f
    lower_short = s.sp - s.lower >= p.mode_write_lower_starts_f - 1e-9
    if lower_short and (short > 0.0 or previous in ELEMENT_MODES):
        return True
    if mode == HEAT_PUMP:
        if short <= p.mode_write_starts_f:
            s.note("write_start_uncertain")
        return short > p.mode_write_starts_f
    if (
        short < p.energy_saver_write_seen_f
        or mode == HIGH_DEMAND
        or previous == ELECTRIC
    ):
        s.note("write_start_uncertain")
    return short > 0.0 or (previous == ELECTRIC and mode in ELECTRIC_EXIT)


# ── The elements ──


def _off_deficit(s: _Step, zone: Zone | None) -> float:
    """How far short of the setpoint an element in ``zone`` switches
    off: Energy Saver's upper element ``upper_off_deficit_f`` (1.62 °F,
    n = 21 off-edges on 15 days), else 0."""
    if zone == "upper" and s.mode in ELEMENT_MODES:
        mode: ElementMode = DEVICE_MODE[s.mode]  # type: ignore[assignment]
        return upper_off_deficit_f(mode, s.settings.element)
    return 0.0


def _start_element(
    s: _Step,
    start: Start,
    zone: Zone,
    since: datetime | None = None,
) -> None:
    """An element starts. The upper zone does not move for the dead
    time after an on-edge (1.21 min, 2026-10-02); the lower
    zone's rate spans its own. One already running at the walk's start
    has the rest of its dead time left when its on-edge (``since``) is
    known, and is taken to be past it, with a whole dead time's heat in
    transit, when it is not. A zone already at its off point stops it at
    once (``_check_element``)."""
    ep = s.settings.element
    dead = ep.upper_dead_time_min if zone == "upper" else 0.0
    on_edge = start.at
    if start.cause == "running":
        on_edge = (
            since
            if since is not None and since <= start.at
            else start.at - timedelta(minutes=dead)
        )
    live_at = on_edge + timedelta(minutes=dead)
    s.state = replace(
        s.state,
        element=Element(
            "dead_time" if live_at > s.at else "heating", zone, live_at
        ),
    )
    s.act(
        StartElement(
            start, zone, live_at, (start.at - on_edge).total_seconds() / 60.0
        )
    )
    s.note("element_model_small_n")
    if zone == "lower":
        s.note("lower_element_nine_runs")
        s.note("upper_zone_dips_during_the_lower_phase")
    _check_element(s)


def _check_element(s: _Step) -> None:
    """A running element that has reached its off point stops; otherwise
    it runs on to it."""
    e = s.state.element
    if not e.running:
        return
    temp = s.upper if e.zone == "upper" else s.lower
    off = s.sp - _off_deficit(s, e.zone)
    if temp >= off - ELEMENT_DONE_F:
        _stop_element(s, "target")
    else:
        s.act(ElementRetarget(off))


def _stop_element(s: _Step, reason: StopReason) -> None:
    """An element stops. At its off point short of the setpoint (Energy
    Saver's upper element), the element's own or one a lowered setpoint
    brought to the zone, the zone coasts on with the heat in transit.
    In Electric the upper element hands over to the lower."""
    zone = s.state.element.zone
    coast: ElementMode | None = None
    if reason in ("target", "write") and _off_deficit(s, zone) > 0.0:
        coast = DEVICE_MODE[s.mode]  # type: ignore[assignment]
    s.state = replace(s.state, element=Element())
    s.act(StopElement(s.at, reason, coast))
    if (
        reason == "target"
        and zone == "upper"
        and s.mode == ELECTRIC
        and s.lower < s.sp - ELEMENT_DONE_F
    ):
        _start_element(
            s,
            Start(
                s.at,
                "heater",
                trigger="electric_lower_after_upper",
                source="element",
            ),
            "lower",
        )


def later_upper_on(
    mode: HeaterMode, setpoint_f: float, element: ElementParams
) -> tuple[float, ElementTrigger] | None:
    """Where the upper element starts later in a stint, and why: in
    Energy Saver as the upper zone reaches ``he_upper_on``, an absolute
    104.9 °F (23 mid-stint starts a median 0.36 °F below it; a device run
    of 2026-09-21 13:54 UTC at a 107.6 °F setpoint engaged at 103.64,
    where a setpoint-relative rule said 71.6); in High Demand as it falls
    ``upper_reengages_below_setpoint_f`` short of the setpoint (4.1 °F,
    12 starts; the four of 2026-04-26/27 at 3.78-4.14). None in the other
    modes: Electric's is not measured."""
    if mode == ENERGY_SAVER:
        return element.energy_saver_reengages_at_f, "energy_saver_upper_on"
    if mode == HIGH_DEMAND:
        return (
            setpoint_f - element.upper_reengages_below_setpoint_f,
            "high_demand_upper_short",
        )
    return None


def _read_upper(s: _Step) -> None:
    """The upper element later in a stint (``later_upper_on``): on with
    the upper zone at or under the mode's level."""
    later = later_upper_on(s.mode, s.sp, s.settings.element)
    if (
        later is None
        or s.disabled
        or s.state.element.running
        or s.upper >= s.sp - ELEMENT_DONE_F
        or s.upper > later[0]
    ):
        return
    _start_element(
        s,
        Start(s.at, "heater", trigger=later[1], source="element"),
        "upper",
    )


def _element_entry(s: _Step, start: Start) -> None:
    """A mode taking effect: its upper element starts at once when the
    upper zone is at least the mode's entry deficit short (device runs
    of 2026-09-20/21: Energy Saver 1.8 °F, High Demand 0.72, Electric
    0.54, each bracketed on both sides); Electric's lower element when
    the upper has nothing to do (``sim/physics/element.py``)."""
    if s.disabled or s.mode not in ELEMENT_MODES or s.state.element.running:
        return
    mode: ElementMode = DEVICE_MODE[s.mode]  # type: ignore[assignment]
    ep = s.settings.element
    need = entry_deficit_f(mode, ep)
    low, high = entry_bracket_f(mode, ep)
    deficit = s.sp - s.upper
    if low < deficit < high:
        s.note("deficit_inside_the_start_threshold_bracket")
    if deficit > 0.0 and deficit >= need - 1e-9:
        _start_element(s, start, "upper")
    elif s.mode == ELECTRIC and s.lower < s.sp - ELEMENT_DONE_F:
        _start_element(s, start, "lower")


# ── Writes ──


def _setpoint(
    s: _Step, value: float, serves: str | None, *, mode_follows: bool
) -> None:
    """The setpoint becomes ``value``, whoever wrote it, and the heater
    responds.

    A running element's off point follows the setpoint, and it stops
    once that is at or below its zone. In Energy Saver a raise leaving
    the upper zone the entry deficit short starts the element (n = 1),
    unless a mode write at the same instant changes the mode: the new
    mode's entry rule decides then.

    A running recovery moves its target or stops (``_would_stop``);
    otherwise the write may start one (``_write_starts``). Each write
    decides afresh: a later one that does not start the heater cancels
    a start an earlier write had set going. The heater's own, waiting
    out the lockout, stands."""
    previous = s.sp
    s.state = replace(s.state, setpoint_f=value)
    s.act(SetpointSet(s.at, value))
    e = s.state.element
    if e.running:
        temp = s.upper if e.zone == "upper" else s.lower
        if temp >= value - _off_deficit(s, e.zone) - ELEMENT_DONE_F:
            _stop_element(s, "write")
        else:
            s.act(ElementRetarget(s.sp - _off_deficit(s, e.zone)))
    elif (
        s.mode == ENERGY_SAVER
        and value > previous
        and not mode_follows
        and not s.disabled
        and s.upper
        <= value - entry_deficit_f("ENERGY_SAVER", s.settings.element) + 1e-9
    ):
        s.note("element_start_on_setpoint_raise_n1")
        _start_element(
            s, Start(s.at, "write", serves=serves, source="element"), "upper"
        )
    if s.state.compressor.running:
        if _would_stop(s, value, previous):
            _stop_compressor(s, "write")
        else:
            s.act(Retarget(s.at))
        return
    pending = s.state.compressor.pending
    if _write_starts(s, value, previous):
        s.pend(_write_start(s, serves))
    elif pending is not None and pending.cause == "write":
        s.pend(None)


def _mode_write(
    s: _Step,
    mode: HeaterMode,
    owner: Owner,
    serves: str | None,
    *,
    afresh: bool = False,
) -> None:
    """``mode`` is written to the heater: an entry's, or a direct write.

    A write over a held one withdraws it (a device run, 2026-09-21
    23:24 UTC). Inside a TOU window a mode that is not the one in force
    is **held** (landing at the window's end unless withdrawn: a device
    run of 2026-09-20 02:15 UTC, and a device test whose entry landed as
    its window ended) when

    - **an entry** writes it, whatever the mode
      (``docs/how-to/schedule-operation.rst``: an entry's mode does not
      take effect while a TOU window is in force; only its temperature
      does). The device test measured an element mode's entry only, so
      a held ``heat_pump`` entry rests on that documented rule and is
      flagged ``heat_pump_entry_held_spec_only``;
    - **a direct write** names an element mode: four in-window direct
      writes of Energy Saver did not take (device runs of 2026-09-20 at
      01:17, 01:26 and 02:15 UTC and 2026-09-21 at 23:24 UTC). A direct
      ``heat_pump`` takes at once: on 2026-04-16 21:23-22:14 UTC, TOU on
      and inside a window, five direct Electric to Heat Pump writes each
      took at once (the in-window High Demand or Electric to Heat Pump
      case of a write-response measurement: 1 of 1).

    A held write into a mode that heats with the compressor starts it as
    a write inside a window does (``window_write_starts_f``): two held
    Energy Saver writes with the compressor off, one leaving the upper
    zone 27.5 °F above the setpoint and one 2.4 °F short of it, started
    nothing for hours (2026-09-21 00:48 and 23:24 UTC).

    In Vacation or powered off the simulation holds no rule for a write
    that leaves them: it is recorded, and takes nothing. ``afresh`` is
    an entry turning a powered-off heater on: the heater re-evaluates
    even in the mode it had (out of ``power_off`` it starts afresh,
    ``ControllerParams``)."""
    ref = s.state.mode.recorded
    s.modes(recorded=ref + 1)
    s.act(RecordModeWrite(s.at, mode, owner, serves))
    if s.disabled:
        return
    held = s.state.mode.held
    s.modes(commanded=mode, held=None)
    if held is not None:
        s.act(ModeWithdrawn(held.ref, s.at))
    entry = owner != "raw"
    if mode != s.mode and (entry or mode in ELEMENT_MODES) and s.in_tou():
        s.act(ModeHeld(ref))
        if entry and mode == HEAT_PUMP:
            s.note("heat_pump_entry_held_spec_only")
        window = window_at(s.at, s.settings.tou_windows)
        assert window is not None
        s.modes(held=Held(mode, serves, window[1], ref))
        s.note("mode_write_held_projected")
        if (
            not s.state.compressor.running
            and s.mode != ELECTRIC
            and _mode_write_starts(s, mode, s.mode)
        ):
            s.note("mode_write_start_projected")
            s.pend(_write_start(s, serves))
        return
    _apply_mode(s, ref, mode, serves, afresh=afresh)


def _apply_mode(
    s: _Step,
    ref: int,
    mode: HeaterMode,
    serves: str | None,
    *,
    afresh: bool = False,
) -> None:
    """A written mode takes effect: the heater re-evaluates, and an
    element mode's entry rule runs. Electric runs no heat pump (0 of 6),
    so it ends a recovery."""
    s.act(ModeTook(ref, s.at))
    previous = s.mode
    if mode == previous and not afresh:
        return
    if mode != previous:
        _set_mode(s, mode, "write")
    if s.state.compressor.running:
        if mode == ELECTRIC:
            _stop_compressor(s, "mode")
    elif _mode_write_starts(s, mode, previous):
        s.pend(_write_start(s, serves))
    _element_entry(s, Start(s.at, "write", serves=serves, source="element"))


def _set_mode(s: _Step, mode: HeaterMode, ended_by: ModeEnd) -> None:
    s.modes(in_force=mode)
    s.act(ModeSet(s.at, mode, ended_by))
    if mode == ELECTRIC:
        # No heat pump in Electric: a start a write set going is off.
        s.pend(None)
    if s.state.element.running and mode not in ELEMENT_MODES:
        _stop_element(s, "mode")
    if mode == ELECTRIC:
        # The model is the entry; what starts Electric's element later
        # in a stint is not measured.
        s.note("element_later_starts_not_modelled")


# ── Handlers, one per event ──


def _begins(s: _Step, ev: Begins) -> None:
    """The walk begins. A compressor running then, outside Electric and
    with heating enabled, runs on, holding for what is left of its
    start's hold."""
    if s.mode == ELECTRIC and not s.disabled:
        s.note("element_later_starts_not_modelled")
    if ev.running and not s.disabled and s.mode != ELECTRIC:
        _start_compressor(
            s, Start(s.at, "running"), startup=False, hold=ev.running_hold
        )


def _element_was_on(s: _Step, ev: ElementWasOn) -> None:
    """An element on at the walk's start runs on, in an element mode:
    the upper while the upper zone is short, else the lower."""
    if s.disabled or s.mode not in ELEMENT_MODES or s.state.element.running:
        return
    zone: Zone = "upper" if s.upper < s.sp - ELEMENT_DONE_F else "lower"
    _start_element(
        s, Start(s.at, "running", source="element"), zone, since=ev.since
    )


def _entry_fires(s: _Step, ev: EntryFires) -> None:
    """The device fires an entry in its minute, whatever runs, setting its
    whole state: the setpoint first, so the mode's own rules judge the
    new setpoint, then the mode. On a heater that is on, a setpoint or
    mode equal to the heater's is no change and starts nothing
    (measured: 0 of 4, a device test). In Vacation the device skips it,
    and does not run it late (a device test, 2026-09-24). Powered off it
    fires and turns the heater on, in the entry's mode (the same test,
    two runs): a mode write out of ``power_off``, the entry's or, with
    none, the heater's, judged by the mode write's rules. What a
    powered-off heater does with an entry that names no mode, or inside
    a TOU window, is unobserved."""
    powering_on = s.disabled and s.settings.powered_off
    if s.disabled and not powering_on:
        s.act(EntrySkipped(ev.ref))
        return
    s.act(EntryFired(ev.ref))
    if powering_on:
        s.state = replace(s.state, powered_on=True)
        s.note(POWERED_ON_BY_ENTRY)
    changes_mode = powering_on or (
        ev.mode is not None and ev.mode != s.state.mode.commanded
    )
    value = ev.setpoint_f
    if value is not None and abs(value - s.sp) > 1e-6:
        _setpoint(s, value, ev.serves, mode_follows=changes_mode)
    if changes_mode:
        _mode_write(
            s,
            ev.mode or s.state.mode.commanded,
            "plan",
            ev.serves,
            afresh=powering_on,
        )


def _raw_writes(s: _Step, ev: RawWrites) -> None:
    """Direct writes made at one instant, each answered as an entry's
    is: every setpoint first, then every mode, whether one write carries
    both or they were listed apart in any order (the entry's order). The
    device's own order at one instant is unmeasured (no mode and
    setpoint write on the record share an instant; the three pairs
    17-67 ms apart come in either order)."""
    follows = any(
        w.mode is not None and w.mode != s.state.mode.commanded
        for w in ev.writes
    )
    for w in ev.writes:
        if w.setpoint_f is not None:
            s.act(
                Then(
                    SetpointWrite(
                        at=s.at,
                        setpoint_f=w.setpoint_f,
                        serves=w.serves,
                        mode_follows=follows,
                        mode=w.mode,
                    )
                )
            )
    for w in ev.writes:
        if w.mode is not None:
            s.act(
                Then(
                    ModeWrite(
                        at=s.at, mode=w.mode, owner="raw", serves=w.serves
                    )
                )
            )


def _setpoint_write(s: _Step, ev: SetpointWrite) -> None:
    """A direct setpoint write. One repeating the setpoint in force is
    no write."""
    if abs(ev.setpoint_f - s.sp) <= 1e-6:
        return
    s.act(RecordWrite(s.at, ev.setpoint_f, ev.mode, ev.serves))
    _setpoint(s, ev.setpoint_f, ev.serves, mode_follows=ev.mode_follows)


def _mode_write_event(s: _Step, ev: ModeWrite) -> None:
    _mode_write(s, ev.mode, ev.owner, ev.serves)


def _window_opens(s: _Step, ev: WindowOpens) -> None:
    """The heater drops a running element mode at a window's start:
    back to the heat pump, as it did within 11 s of TOU being switched
    on in-window (a device run, 2026-09-20 01:35 UTC). At a window's
    start it is *assumed* to do the same; crossing a price-band boundary
    is untested. It re-evaluates, as that run's compressor start
    21-32 s later shows. The mode returns only when a later write sets
    it again."""
    if s.mode not in ELEMENT_MODES:
        return
    s.note("element_mode_dropped_projected")
    previous = s.mode
    s.act(Dropped(s.at, previous))
    _set_mode(s, HEAT_PUMP, "dropped")
    s.modes(commanded=HEAT_PUMP)
    if not s.state.compressor.running and _mode_write_starts(
        s, HEAT_PUMP, previous
    ):
        s.pend(
            Start(
                not_before(s.state, s.params, s.at + s.params.write_start_lag),
                "heater",
                trigger="mode_dropped",
            )
        )


def _window_closes(s: _Step, ev: WindowCloses) -> None:
    """A mode write held in the window lands as it closes (a device
    test's entry landed as its window ended)."""
    held = s.state.mode.held
    if held is None or s.at != held.until:
        return
    s.modes(held=None)
    _apply_mode(s, held.ref, held.mode, held.serves)


def _heater_trigger(s: _Step, ev: HeaterTrigger) -> None:
    """The heater's own trigger starts the compressor; whatever
    start was pending is its."""
    s.pend(None)
    _start_compressor(s, Start(s.at, "heater", trigger=ev.trigger))


def _trigger_deferred(s: _Step, ev: TriggerDeferred) -> None:
    """A trigger inside the restart lockout starts the compressor when
    the lockout ends (the 2026-09-23 restarts, 5 min 28 s and 5 min 31 s
    after the stop): carried as a pending start, the earliest kept."""
    pending = s.state.compressor.pending
    if ev.starts_at < ev.horizon and (
        pending is None or ev.starts_at < pending.at
    ):
        s.pend(Start(ev.starts_at, "heater", trigger=ev.trigger))


def _start_due(s: _Step, ev: StartDue) -> None:
    """A pending start comes due: the compressor starts, unless it is
    running already."""
    start = s.state.compressor.pending
    s.pend(None)
    if start is not None and not s.state.compressor.running:
        _start_compressor(s, start)


def _upper_read(s: _Step, ev: UpperRead) -> None:
    _read_upper(s)


def _upper_on_crossed(s: _Step, ev: UpperOnCrossed) -> None:
    """A coast took the upper zone to the mode's later start
    (``later_upper_on``): the element starts there (``_read_upper``'s
    rule, met on the path)."""
    later = later_upper_on(s.mode, s.sp, s.settings.element)
    if later is None:
        return
    _start_element(
        s,
        Start(s.at, "heater", trigger=later[1], source="element"),
        "upper",
    )


def _element_check(s: _Step, ev: ElementCheck) -> None:
    _check_element(s)


def _recovery_done(s: _Step, ev: RecoveryDone) -> None:
    """A recovery reaches its end: its target, or the TOU cap's level
    short of it, judged at its end."""
    if s.state.compressor.running:
        _stop_compressor(s, "cap" if ev.capped else "target")


def _timer(s: _Step, ev: Event) -> None:
    """The lockout, the start's hold or the dead time ends
    (``_advance``)."""


def _horizon(s: _Step, ev: Horizon) -> None:
    if s.state.compressor.running:
        _stop_compressor(s, "horizon")
    if s.state.element.running:
        _stop_element(s, "horizon")


#: Read-only: the core holds no mutable module state.
_HANDLERS: Final[Mapping[type[Event], Callable[[_Step, Event], None]]] = (
    MappingProxyType(
        {
            Begins: _begins,  # type: ignore[dict-item]
            ElementWasOn: _element_was_on,  # type: ignore[dict-item]
            EntryFires: _entry_fires,  # type: ignore[dict-item]
            RawWrites: _raw_writes,  # type: ignore[dict-item]
            SetpointWrite: _setpoint_write,  # type: ignore[dict-item]
            ModeWrite: _mode_write_event,  # type: ignore[dict-item]
            WindowOpens: _window_opens,  # type: ignore[dict-item]
            WindowCloses: _window_closes,  # type: ignore[dict-item]
            HeaterTrigger: _heater_trigger,  # type: ignore[dict-item]
            TriggerDeferred: _trigger_deferred,  # type: ignore[dict-item]
            StartDue: _start_due,  # type: ignore[dict-item]
            UpperRead: _upper_read,  # type: ignore[dict-item]
            UpperOnCrossed: _upper_on_crossed,  # type: ignore[dict-item]
            ElementCheck: _element_check,  # type: ignore[dict-item]
            RecoveryDone: _recovery_done,  # type: ignore[dict-item]
            LockoutEnds: _timer,
            StartHoldEnds: _timer,
            DeadTimeEnds: _timer,
            Horizon: _horizon,  # type: ignore[dict-item]
        }
    )
)


# ── Judged along the path ───────────────────────────────────────────


def window_at(at: datetime, windows: Sequence[Window]) -> Window | None:
    return next((w for w in windows if w[0] <= at < w[1]), None)


def wake_times(state: State, settings: Settings) -> set[datetime]:
    """The instants the controller acts at next with nothing else
    happening: a pending start, an element's dead time ending, a held
    mode landing, and a window opening while an element mode is in
    force (to drop it)."""
    out: set[datetime] = set()
    if state.compressor.pending is not None:
        out.add(state.compressor.pending.at)
    if state.element.running and state.element.live_at is not None:
        out.add(state.element.live_at)
    if state.mode.in_force in ELEMENT_MODES:
        out.update(w[0] for w in settings.tou_windows)
    if state.mode.held is not None:
        out.add(state.mode.held.until)
    return out


@dataclass(frozen=True)
class Ahead:
    """The heater's own start on a coast: its trigger's instant, and
    when the compressor starts for it, the lockout waited."""

    trigger_at: datetime
    starts_at: datetime
    trigger: Trigger | None


def trigger_ahead(
    state: State,
    settings: Settings,
    params: ControllerParams,
    trajectory: Sequence[tuple[datetime, float, float]],
    impulses: Sequence[Impulse],
    now: datetime,
) -> tuple[Ahead | None, tuple[str, ...]]:
    """Where on a coast, from ``now``, the heater starts itself
    (``tou_triggers.heater_start``), and the reasons the search carries.

    Not at ``now`` on the lower trigger when a write's start is pending:
    a raise that releases a held lower trigger is answered as a write,
    as the 2026-10-03 device test's closing entry was (31.6 s after it
    landed, the lower zone 5.4 °F under the setting). Nor at the instant
    a recovery ended: the trigger reads the tank it left at its target.
    A trigger inside the restart lockout starts when the lockout ends."""
    if disabled(state, settings) or state.mode.in_force == ELECTRIC:
        return None, ()
    # No lower threshold disables the lower trigger alone: the upper
    # zone's at a TOU window's opening does not read it.
    on = settings.hp_lower_on_f
    at, trigger, held = heater_start(
        trajectory,
        -math.inf if on is None else on,
        impulses,
        windows=settings.tou_windows,
        setpoint_f=state.setpoint_f,
        mode=state.mode.in_force,
    )
    # The lower trigger held by an upper zone at or above the setpoint
    # rests on one device run.
    notes = (LOWER_TRIGGER_HELD,) if held else ()
    pending = state.compressor.pending
    if (
        at is not None
        and at == now
        and trigger == "lower"
        and pending is not None
        and pending.cause == "write"
    ):
        at = None
    if at is not None and at == now and state.compressor.finished_at == now:
        at = None
    if at is None:
        return None, notes
    return Ahead(at, not_before(state, params, at), trigger), notes


def upper_on_crossing(
    state: State, settings: Settings, points: Sequence[Point]
) -> datetime | None:
    """Where a coast takes the upper zone down to the mode's later
    element start (``later_upper_on``) with no element running
    (``_read_upper``); None when it does not."""
    later = later_upper_on(
        state.mode.in_force, state.setpoint_f, settings.element
    )
    if later is None or disabled(state, settings) or state.element.running:
        return None
    on = later[0]
    for p0, p1 in pairwise(points):
        if p0.upper_f > on >= p1.upper_f and p1.upper_f < state.setpoint_f:
            f = (p0.upper_f - on) / (p0.upper_f - p1.upper_f)
            return p0.at + (p1.at - p0.at) * f
    return None


def cap_stop(
    points: Sequence[Point], level: float, windows: Sequence[Window]
) -> datetime | None:
    """The first instant on ``points`` inside a TOU window with the
    lower zone at ``level`` or above; None when there is none."""
    end = points[-1].at
    found: list[datetime] = []
    for w0, w1 in windows:
        lo = max(points[0].at, w0)
        if lo >= w1 or lo > end:
            continue
        if point_at(points, lo).lower_f >= level:
            found.append(lo)
            continue
        for p0, p1 in pairwise(points):
            if p1.at <= lo or p0.at >= w1:
                continue
            if p1.lower_f >= level > p0.lower_f:
                span = p1.lower_f - p0.lower_f
                at = p0.at + (p1.at - p0.at) * ((level - p0.lower_f) / span)
                if lo <= at < w1:
                    found.append(at)
                break
    return min(found) if found else None


@dataclass(frozen=True)
class Cap:
    """The TOU cap's judgement of a recovery's path: ``none``, it
    runs to its target; ``at_level``, it is at the cap's level inside
    the window already and does not heat; ``to_level``, ``cap_outcome``
    decides from the path to ``level``."""

    kind: Literal["none", "at_level", "to_level"]
    level: float = 0.0
    window: Window | None = None


def judge_cap(
    full: Sequence[Point],
    *,
    at: datetime,
    lower_f: float,
    target_f: float,
    windows: Sequence[Window],
    params: ControllerParams,
) -> Cap:
    """The TOU cap, judged at the recovery's end: a recovery
    stops at the first instant it is inside a window with the lower
    zone at the cap's level, the target less ``tou_cap_f``. Judging at
    the start caught 17 of 59 capped cycles against 43 at the end
    (``docs/explanation/tou-recovery-cap.rst``). ``full`` is its path
    to the target from ``at``."""
    level = target_f - params.tou_cap_f
    stop = cap_stop(full, level, windows)
    if stop is None:
        return Cap("none")
    window = window_at(stop, windows)
    assert window is not None
    if at >= window[0] and lower_f >= level:
        return Cap("at_level", level, window)
    return Cap("to_level", level, window)


def cap_outcome(
    reaches_level_at: datetime | None, window: Window
) -> Literal["until_open", "to_level", "full"]:
    """Where a recovery the cap may stop ends, from when its path
    reaches the cap's level (None: it is there now): at the level before
    the window opens, it runs on toward the full target and stops as the
    window opens; at the level inside the window, it stops there; only
    after the window closes, the full target applies again."""
    if reaches_level_at is None or reaches_level_at < window[0]:
        return "until_open"
    if reaches_level_at < window[1]:
        return "to_level"
    return "full"
