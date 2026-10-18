"""A heater's record: what it reported, as change rows per signal.

Each signal holds ``(instant, value)`` rows, oldest first, a row only
where the value changed: a value holds until the next row
(``sim_adapters.record`` builds one from polled ``DeviceStatus``
readings). What is read from it here is what the model read from its
own record: the recorded writes and the heater's own drops
(``writes``), the TOU switch's changes, the window's edges the upper
start threshold shows, and the starts, an element's only where the
heater's power shows it running (``starts``).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from nwp500.sim.inputs import ELECTRIC, ENERGY_SAVER, HEAT_PUMP, HIGH_DEMAND

#: A setpoint change smaller than this is no write, °F.
SAME_F = 0.05
#: A drop to Heat Pump within this of TOU switching on or a window
#: opening is the heater's own, not a write.
DROP_WITHIN = timedelta(seconds=5)
#: The upper start threshold at rest; raised above this (the setting's
#: half-degree step on top), a TOU window is in force.
RESTING_UPPER_ON_F = 104.9
RAISED_ABOVE_F = RESTING_UPPER_ON_F + 0.9
#: A metered sample at or above this is an element running: one element
#: is about 5 kW, the compressor alone well under 1.
ELEMENT_W = 3000.0
#: The power is sampled about every 30 s, so a run's can land just
#: after its flag falls.
ELEMENT_POWER_SLACK = timedelta(seconds=60)
#: How far back a setting's value in force is looked for.
SETTING_LOOKBACK = timedelta(days=30)
#: How far back an on/off state's value in force is looked for.
STATUS_LOOKBACK = timedelta(days=7)

_ELEMENT_MODES = frozenset({ELECTRIC, ENERGY_SAVER, HIGH_DEMAND})

Rows = tuple[tuple[datetime, float], ...]


@dataclass(frozen=True)
class RecordedWrite:
    """A recorded change of the setpoint or of the mode (a
    ``DhwOperationSetting`` value), at the instant it was recorded.
    ``dropped``: the heater's own drop to Heat Pump at a window, not a
    write."""

    at: datetime
    setpoint_f: float | None = None
    mode: int | None = None
    dropped: bool = False


@dataclass(frozen=True)
class Recorded:
    """A recorded start: its instant, what started, and whether it was
    already on when the span began."""

    at: datetime
    source: Literal["compressor", "element"]
    zone: Literal["upper", "lower"] | None = None
    running: bool = False


@dataclass(frozen=True)
class RecordedStarts:
    starts: list[Recorded]
    #: The compressor's off-edges, for the restart lockout.
    stops: list[datetime]
    #: Element flag runs no metered power corroborated.
    uncorroborated: int = 0


def last(
    rows: Rows, at: datetime, lookback: timedelta
) -> tuple[datetime, float] | None:
    """The last row at or before ``at`` within ``lookback``."""
    found = None
    for t, v in rows:
        if t > at:
            break
        if t >= at - lookback:
            found = (t, v)
    return found


def between(rows: Rows, start: datetime, end: datetime) -> Rows:
    """The rows in ``[start, end]``."""
    return tuple((t, v) for t, v in rows if start <= t <= end)


def corroborator(
    watts: Rows, element_ons: Sequence[datetime]
) -> Callable[[datetime, datetime], bool]:
    """Whether a metered element's power is in the run ``[on, off]``: a
    sample of ``ELEMENT_W`` or more from its on-edge to
    ``ELEMENT_POWER_SLACK`` after its off-edge, but not from the next
    element run's on-edge (``element_ons``, either element's), whose
    power it would be. The value in force at the on-edge counts too,
    if its row is at most ``ELEMENT_POWER_SLACK`` old: power records
    on change, so a handoff between the elements at one wattage
    leaves no row in the second run."""

    def powered(on: datetime, off: datetime) -> bool:
        hi = off + ELEMENT_POWER_SLACK
        nxt = next((a for a in element_ons if a > on), None)
        held: tuple[datetime, float] | None = None
        for t, v in watts:
            if t >= on:
                break
            held = (t, v)
        if (
            held is not None
            and on - held[0] <= ELEMENT_POWER_SLACK
            and held[1] >= ELEMENT_W
        ):
            return True
        return any(
            v >= ELEMENT_W
            for t, v in watts
            if on <= t <= hi and (nxt is None or t < nxt)
        )

    return powered


@dataclass(frozen=True)
class Record:
    """Each signal's change rows, oldest first: on/off states as 1.0 and
    0.0, temperatures °F, the mode a ``DhwOperationSetting`` value, the
    heat source a ``HeatSource`` value, the power W."""

    compressor: Rows = ()
    upper_element: Rows = ()
    lower_element: Rows = ()
    power_w: Rows = ()
    mode: Rows = ()
    setpoint_f: Rows = ()
    heat_source: Rows = ()
    upper_f: Rows = ()
    lower_f: Rows = ()
    hp_lower_on_f: Rows = ()
    hp_upper_on_f: Rows = ()
    tou: Rows = ()
    #: How far back a setting's value in force (the TOU switch, the
    #: upper start threshold, the mode and setpoint a write is judged
    #: against) is looked for: settings record only on change and
    #: legitimately hold for months.
    setting_lookback: timedelta = SETTING_LOOKBACK

    def tou_switches(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, bool]]:
        """Every change of the TOU switch in ``(start, end)``, judged
        against the state in force before it."""
        prior = last(self.tou, start, self.setting_lookback)
        state = None if prior is None else prior[1] >= 0.5
        out: list[tuple[datetime, bool]] = []
        for at, v in between(self.tou, start, end):
            on = v >= 0.5
            if on != state and start < at < end:
                out.append((at, on))
            state = on
        return out

    def upper_on_edges(
        self, start: datetime, end: datetime
    ) -> tuple[list[datetime], list[datetime]]:
        """The instants in ``[start, end]`` the upper start threshold
        rose above rest (a window opening) and fell back (a close)."""
        before = last(
            self.hp_upper_on_f,
            start - timedelta(microseconds=1),
            self.setting_lookback,
        )
        raised = before is not None and before[1] > RAISED_ABOVE_F
        openings: list[datetime] = []
        closings: list[datetime] = []
        for at, value in between(self.hp_upper_on_f, start, end):
            up = value > RAISED_ABOVE_F
            if up and not raised:
                openings.append(at)
            elif raised and not up:
                closings.append(at)
            raised = up
        return openings, closings

    def _window_starts(self, start: datetime, end: datetime) -> list[datetime]:
        switched = [at for at, on in self.tou_switches(start, end) if on]
        openings, _ = self.upper_on_edges(start, end)
        return [*switched, *openings]

    def writes(
        self,
        start: datetime,
        end: datetime,
        lookback: timedelta | None = None,
    ) -> list[RecordedWrite]:
        """Every change of the setpoint and of the mode in ``(start,
        end)``, in time order, a mode before a setpoint at one instant,
        each judged against the value in force before it. A change to
        Heat Pump out of an element mode within ``DROP_WITHIN`` of TOU
        switching on or a window opening is the heater's, ``dropped``."""
        out: list[tuple[datetime, int, RecordedWrite]] = []
        lookback = self.setting_lookback if lookback is None else lookback
        prior = last(self.setpoint_f, start, lookback)
        value = None if prior is None else prior[1]
        for at, v in between(self.setpoint_f, start, end):
            if value is not None and abs(v - value) <= SAME_F:
                continue
            if value is not None and start < at < end:
                out.append((at, 1, RecordedWrite(at, setpoint_f=v)))
            value = v
        edges = self._window_starts(start - DROP_WITHIN, end + DROP_WITHIN)
        mode_prior = last(self.mode, start, lookback)
        mode = None if mode_prior is None else int(mode_prior[1])
        for at, v in between(self.mode, start, end):
            m = int(v)
            if m == mode:
                continue
            if mode is not None and start < at < end:
                dropped = (
                    m == HEAT_PUMP
                    and mode in _ELEMENT_MODES
                    and any(abs(e - at) <= DROP_WITHIN for e in edges)
                )
                out.append((at, 0, RecordedWrite(at, mode=m, dropped=dropped)))
            mode = m
        return [w for _, _, w in sorted(out, key=lambda x: (x[0], x[1]))]

    def starts(self, start: datetime, end: datetime) -> RecordedStarts:
        """Every compressor and corroborated element start in
        ``[start, end)``, one already on at ``start`` as ``running``,
        and the compressor's stops from a day before (for the lockout).
        An element run counts only where the heater's power shows it
        (``corroborator``); one already on at ``start`` is judged over
        its whole run. An off-edge at ``start`` is in force at it, so
        a run that stopped there is not running; an on-edge there is a
        new start."""
        day = timedelta(days=1)
        series = {
            "compressor": self.compressor,
            "upper": self.upper_element,
            "lower": self.lower_element,
        }
        found: dict[str, tuple[bool, list[tuple[datetime, bool]]]] = {}
        for name, rows in series.items():
            prior = last(rows, start - day, STATUS_LOOKBACK)
            state: bool | None = None if prior is None else prior[1] >= 0.5
            edges: list[tuple[datetime, bool]] = []
            for t, v in between(rows, start - day, end):
                on = v >= 0.5
                if on != state:
                    edges.append((t, on))
                state = on
            found[name] = (prior is not None and prior[1] >= 0.5, edges)
        element_ons = sorted(
            at for name in ("upper", "lower") for at, on in found[name][1] if on
        )
        powered = corroborator(
            between(self.power_w, start - day, end + ELEMENT_POWER_SLACK),
            element_ons,
        )
        starts: list[Recorded] = []
        stops: list[datetime] = []
        uncorroborated = 0
        for name, (on_at_start, edges) in found.items():
            source: Literal["compressor", "element"] = (
                "compressor" if name == "compressor" else "element"
            )
            zone: Literal["upper", "lower"] | None = (
                None if source == "compressor" else name  # type: ignore[assignment]
            )
            since = start - day
            for at, on in edges:
                if at < start or (at == start and not on):
                    on_at_start = on
                    since = at
            if on_at_start:
                off = next((a for a, o in edges if a >= start and not o), end)
                if source == "element" and not powered(since, off):
                    uncorroborated += 1
                else:
                    starts.append(Recorded(start, source, zone, running=True))
            for i, (at, on) in enumerate(edges):
                if not on:
                    if source == "compressor":
                        stops.append(at)
                    continue
                if not start <= at < end:
                    continue
                if source == "element":
                    off = next((a for a, o in edges[i + 1 :] if not o), end)
                    if not powered(at, off):
                        uncorroborated += 1
                        continue
                starts.append(Recorded(at, source, zone))
        return RecordedStarts(
            starts=sorted(starts, key=lambda s: s.at),
            stops=sorted(stops),
            uncorroborated=uncorroborated,
        )
