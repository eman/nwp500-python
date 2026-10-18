"""What the heater did over a past range, from its record
(``sim.record.Record``), in the simulation's terms: the mode in force
and whether the heat source the heater reported shows it in effect,
when each source ran, the compressor's starts with their attribution
(``sim.attribution``) and whether each counts, the energy per slot from
the heater's own power, the delivered temperature (the upper zone), and
where a signal's record was missing.

Nothing is resampled: every interval runs between rows, so a 16 s
element run is a 16 s interval.

**Rows and gaps.** A value holds until the next row, so a missing
signal shows only as no value in force: none within the signal's
lookback before a time (``no_record``), or, for the power and the
delivered temperature, a last reading older than their hold
(``hold_exceeded``). An outage that ends on the value it began with is
not seen. Time after ``now`` is a gap of every signal
(``not_yet_recorded``). An element flag the power cannot corroborate
because the power has a gap over its run is an ``elements`` gap
(``uncorroborated``), never a run and never its absence.

**``counted``**: one continuous series of compressor on-edges, an edge
less than ``MERGE_STARTS`` after the last counted one not counted, read
from ``MERGE_CONTEXT`` before ``frm``. Where it begins, as after any
``compressor`` gap, ``counted`` is None until the first edge at least
``MERGE_STARTS`` after both that point and every edge since it.

**``cause``** is None for a start whose attribution lookback
(``ATTRIBUTION_LOOKBACK``) reaches into a ``mode`` or ``setpoint`` gap: a
write made there could own it, and the record does not show it.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Literal

from nwp500.sim.attribution import RESTART_LOCKOUT, WRITE_EVIDENCE, attribute
from nwp500.sim.profile import HeaterProfile, heater_profile
from nwp500.sim.record import (
    ELEMENT_POWER_SLACK,
    Record,
    Recorded,
    Rows,
    corroborator,
    last,
)

#: The energy is laid out on slots this long.
SLOT = timedelta(minutes=10)
#: An on-edge less than this after the last counted start is not
#: counted (start to start).
MERGE_STARTS = timedelta(minutes=30)
#: How far before ``frm`` the compressor's series is read, so the
#: counted start an edge just after ``frm`` merges with is known.
MERGE_CONTEXT = timedelta(days=1)
#: How far before a start a write is read: the evidence window, and the
#: restart lockout a write made inside it waits out.
ATTRIBUTION_LOOKBACK = WRITE_EVIDENCE + RESTART_LOCKOUT
#: How far back a change-only state's value in force is looked for: a
#: setting can stand for months.
STATE_LOOKBACK = timedelta(days=730)
#: How far back the tank's readings are looked for, and how long one
#: holds.
TANK_LOOKBACK = timedelta(hours=6)
#: The longest a power value holds with no row after it.
POWER_HOLD = timedelta(hours=26)

Signal = Literal[
    "compressor",
    "power",
    "mode",
    "setpoint",
    "elements",
    "heat_source",
    "delivery",
]
SIGNALS: tuple[Signal, ...] = (
    "compressor",
    "power",
    "mode",
    "setpoint",
    "elements",
    "heat_source",
    "delivery",
)
NO_RECORD = "no_record"
HOLD_EXCEEDED = "hold_exceeded"
UNCORROBORATED = "uncorroborated"
NOT_YET = "not_yet_recorded"

Span = tuple[datetime, datetime]


def reported_sources(heat_source: int | None) -> frozenset[str] | None:
    """The sources a reported heat source names (``HeatSource``: 1 the
    heat pump, 2 an element, 3 both); None when it names neither
    (idle)."""
    if heat_source is None:
        return None
    found = frozenset(
        s
        for s, bit in (("compressor", 1), ("element", 2))
        if int(heat_source) & bit
    )
    return found or None


def effective(name: str, reported: frozenset[str] | None) -> bool | None:
    """Whether the reported heat source shows mode ``name`` in effect,
    by the simulation's own profile (``HeaterProfile.effective``)."""
    return heater_profile().effective(name, reported)


@dataclass(frozen=True)
class ModeInterval:
    start: datetime
    end: datetime
    name: str | None
    effective: bool | None


@dataclass(frozen=True)
class SetpointInterval:
    start: datetime
    end: datetime
    f: float


@dataclass(frozen=True)
class SourceInterval:
    start: datetime
    end: datetime
    source: Literal["compressor", "element"]


@dataclass(frozen=True)
class Start:
    at: datetime
    counted: bool | None
    cause: Literal["heater", "write"] | None
    trigger: str | None
    write_at: datetime | None
    source: Literal["compressor"] = "compressor"


@dataclass(frozen=True)
class Slot:
    start: datetime
    energy_wh: float | None
    partial: bool
    covered_s: float


@dataclass(frozen=True)
class Gap:
    start: datetime
    end: datetime
    signal: Signal
    reason: str


@dataclass(frozen=True)
class Observed:
    modes: list[ModeInterval]
    sources: list[SourceInterval]
    starts: list[Start]
    running_at_from: dict[str, bool | None]
    slots: list[Slot]
    delivery_f: list[tuple[datetime, float]]
    gaps: list[Gap] = field(default_factory=list)
    setpoints: list[SetpointInterval] = field(default_factory=list)


@dataclass(frozen=True)
class _Series:
    """A signal's rows from ``start``: the last before it within the
    lookback (the seed, at its own time), then each row, by time."""

    start: datetime
    points: list[tuple[datetime, float]]

    def pieces(
        self, a: datetime, b: datetime, hold: timedelta | None = None
    ) -> list[tuple[datetime, datetime, float]]:
        """``[lo, hi)`` inside ``[a, b)`` where a value is in force,
        with it: each row holds until the next, no longer than
        ``hold``."""
        out: list[tuple[datetime, datetime, float]] = []
        for i, (t, v) in enumerate(self.points):
            nxt = self.points[i + 1][0] if i + 1 < len(self.points) else b
            stop = nxt if hold is None else min(nxt, t + hold)
            lo, hi = max(t, a), min(stop, b)
            if hi > lo:
                out.append((lo, hi, v))
        return out

    def at(self, t: datetime, hold: timedelta | None = None) -> float | None:
        for lo, hi, v in self.pieces(t, t + timedelta(microseconds=1), hold):
            if lo <= t < hi:
                return v
        return None


def _read(
    rows: Rows, start: datetime, end: datetime, lookback: timedelta
) -> _Series:
    """The seed and the rows of ``[start, end)``."""
    seed = last(rows, start, lookback)
    points: list[tuple[datetime, float]] = []
    if seed is not None:
        points.append(seed)
    for at, v in rows:
        if at < start or at >= end or (points and at <= points[0][0]):
            continue
        points.append((at, v))
    return _Series(start, points)


def _complement(spans: Sequence[Span], a: datetime, b: datetime) -> list[Span]:
    out: list[Span] = []
    cursor = a
    for lo, hi in sorted(spans):
        if lo > cursor:
            out.append((cursor, min(lo, b)))
        cursor = max(cursor, hi)
        if cursor >= b:
            break
    if cursor < b:
        out.append((cursor, b))
    return [(lo, hi) for lo, hi in out if hi > lo]


def _overlaps(spans: Sequence[Span], a: datetime, b: datetime) -> bool:
    return any(lo < b and a < hi for lo, hi in spans)


def _clip(spans: Sequence[Span], a: datetime, b: datetime) -> list[Span]:
    return [(max(lo, a), min(hi, b)) for lo, hi in spans if lo < b and a < hi]


def _merge(spans: Sequence[Span]) -> list[Span]:
    out: list[Span] = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def count_starts(
    edges: Sequence[datetime], resyncs: Sequence[datetime]
) -> list[bool | None]:
    """Whether each on-edge counts (module docstring): ``resyncs`` are
    where the series begins and every ``compressor`` gap's end. After
    one, an edge is None until the first at least ``MERGE_STARTS`` after
    it and after every edge since; that edge counts, and the rule holds
    again from it."""
    events = sorted(
        [(t, 0) for t in resyncs] + [(t, 1) for t in edges],
        key=lambda e: (e[0], e[1]),
    )
    out: dict[datetime, bool | None] = {}
    synced = False
    anchor: datetime | None = None
    last_edge: datetime | None = None
    last_counted: datetime | None = None
    for t, kind in events:
        if kind == 0:
            synced, anchor, last_edge = False, t, None
            continue
        if synced:
            assert last_counted is not None
            if t - last_counted >= MERGE_STARTS:
                out[t], last_counted = True, t
            else:
                out[t] = False
            continue
        if (anchor is None or t - anchor >= MERGE_STARTS) and (
            last_edge is None or t - last_edge >= MERGE_STARTS
        ):
            out[t], last_counted, synced = True, t, True
        else:
            out[t] = None
            last_edge = t
    return [out[t] for t in edges]


def _runs(
    series: _Series, a: datetime, b: datetime
) -> list[tuple[datetime, datetime | None]]:
    out: list[tuple[datetime, datetime | None]] = []
    since: datetime | None = None
    for t, v in series.points:
        if t >= b:
            break
        if v and since is None:
            since = t
        elif not v and since is not None:
            if t > a:
                out.append((since, t))
            since = None
    if since is not None:
        out.append((since, None))
    return out


def _edges(series: _Series) -> tuple[list[datetime], list[datetime]]:
    ons: list[datetime] = []
    offs: list[datetime] = []
    prev: float | None = None
    for t, v in series.points:
        if prev is not None and v != prev:
            (ons if v else offs).append(t)
        prev = v
    return ons, offs


def _known_gaps(
    series: _Series, a: datetime, b: datetime, hold: timedelta | None = None
) -> list[Span]:
    return _complement(
        [(lo, hi) for lo, hi, _ in series.pieces(a, b, hold)], a, b
    )


def observe(
    record: Record,
    frm: datetime,
    to: datetime,
    *,
    now: datetime,
    profile: HeaterProfile | None = None,
    revision_since: datetime | None = None,
) -> Observed:
    """What the heater did over ``[frm, to)``, both on the ``SLOT``
    grid; nothing after ``now`` is claimed (module docstring). A
    setting's value in force is looked for as far back as a state's
    (``STATE_LOOKBACK``).

    Modes are named, and judged in effect, by ``profile`` (the
    simulation's own, ``heater_profile()``, by default); a mode it does
    not list is an interval with no name. ``revision_since``: when
    ``profile``'s revision took effect, before which no mode is named
    (None: always in effect)."""
    profile = heater_profile() if profile is None else profile
    record = replace(record, setting_lookback=STATE_LOOKBACK)
    cut = max(frm, min(to, now))
    ctx = frm - MERGE_CONTEXT
    gaps: dict[Signal, list[tuple[datetime, datetime, str]]] = {
        s: [] for s in SIGNALS
    }

    def gap(signal: Signal, spans: Sequence[Span], reason: str) -> None:
        for lo, hi in _clip(spans, frm, to):
            gaps[signal].append((lo, hi, reason))

    compressor = _read(record.compressor, ctx, cut, STATE_LOOKBACK)
    compressor_gaps = _known_gaps(compressor, ctx, cut)
    gap("compressor", compressor_gaps, NO_RECORD)
    ons, offs = _edges(compressor)
    resyncs = [ctx, *(hi for _, hi in compressor_gaps if hi < cut)]
    counted = count_starts(ons, sorted(set(resyncs)))

    mode_series = _read(record.mode, ctx, cut, STATE_LOOKBACK)
    setpoint_series = _read(record.setpoint_f, ctx, cut, STATE_LOOKBACK)
    mode_gaps = _known_gaps(mode_series, ctx, cut)
    setpoint_gaps = _known_gaps(setpoint_series, ctx, cut)
    gap("mode", mode_gaps, NO_RECORD)
    gap("setpoint", setpoint_gaps, NO_RECORD)
    blind = [*mode_gaps, *setpoint_gaps]
    writes = record.writes(ctx, cut, STATE_LOOKBACK)
    openings, closings = record.upper_on_edges(ctx, cut)
    lower = [
        (t, v)
        for t, v in record.lower_f
        if frm - timedelta(hours=1) <= t <= cut
    ]
    lower_on = _read(record.hp_lower_on_f, ctx, cut, STATE_LOOKBACK)
    upper_rows = _read(
        record.upper_f, frm - timedelta(hours=1), cut, TANK_LOOKBACK
    )

    def lower_at(at: datetime) -> float | None:
        before = [v for t, v in lower if t <= at]
        return before[-1] if before else None

    def upper_short_at(at: datetime) -> float | None:
        sp, up = setpoint_series.at(at), upper_rows.at(at)
        if sp is not None and up is not None:
            return sp - up
        return None

    starts: list[Start] = []
    for at, n in zip(ons, counted, strict=True):
        if not frm <= at < cut:
            continue
        if _overlaps(
            blind, at - ATTRIBUTION_LOOKBACK, at + timedelta(microseconds=1)
        ):
            starts.append(Start(at, n, None, None, None))
            continue
        (a,) = attribute(
            [Recorded(at, "compressor")],
            sorted({w.at for w in writes if not w.dropped}),
            drops=sorted({w.at for w in writes if w.dropped}),
            stops=offs,
            openings=openings,
            closings=closings,
            lower_at=lower_at,
            hp_lower_on_f=lower_on.at(at),
            upper_short_at=upper_short_at,
        )
        cause: Literal["heater", "write"] = (
            "write" if a.cause == "write" else "heater"
        )
        starts.append(Start(at, n, cause, a.trigger, a.write_at))

    sources: list[SourceInterval] = [
        SourceInterval(lo, hi, "compressor")
        for lo, hi in _merge(
            [(lo, hi) for lo, hi, on in compressor.pieces(frm, cut) if on]
        )
    ]
    elements = [
        _read(rows, ctx, cut, STATE_LOOKBACK)
        for rows in (record.upper_element, record.lower_element)
    ]
    element_gaps = _merge(
        [g for series in elements for g in _known_gaps(series, ctx, cut)]
    )
    gap("elements", element_gaps, NO_RECORD)
    runs = [r for series in elements for r in _runs(series, frm, cut)]
    element_ons = sorted(on for on, _ in runs)

    earliest = min([frm, *element_ons])
    power = _read(
        record.power_w, earliest, cut + ELEMENT_POWER_SLACK, POWER_HOLD
    )
    power_pieces = power.pieces(frm, cut, POWER_HOLD)
    for lo, hi in _complement([(a, b) for a, b, _ in power_pieces], frm, cut):
        held = any(t < lo for t, _ in power.points)
        gap("power", [(lo, hi)], HOLD_EXCEEDED if held else NO_RECORD)
    slots: list[Slot] = []
    s = frm
    while s < to:
        e = s + SLOT
        covered = timedelta(0)
        wh = 0.0
        for lo, hi, w in power_pieces:
            a_, b_ = max(lo, s), min(hi, e)
            if b_ > a_:
                covered += b_ - a_
                wh += w * (b_ - a_).total_seconds() / 3600.0
        slots.append(
            Slot(
                start=s,
                energy_wh=round(wh, 2) if covered else None,
                partial=covered < e - s,
                covered_s=round(covered.total_seconds(), 3),
            )
        )
        s = e
    meter_gaps = _known_gaps(power, earliest, cut, POWER_HOLD)
    powered = corroborator(tuple(power.points), element_ons)
    element_runs: list[Span] = []
    for on, off in runs:
        end = cut if off is None else off
        if powered(on, end):
            element_runs.append((on, end))
            lo, hi = max(on, frm), min(end, cut)
            if hi > lo:
                sources.append(SourceInterval(lo, hi, "element"))
        elif (
            _overlaps(meter_gaps, on, end + ELEMENT_POWER_SLACK)
            or end + ELEMENT_POWER_SLACK > now
        ):
            gap("elements", [(on, end)], UNCORROBORATED)
    sources.sort(key=lambda x: (x.start, x.source))

    heat_source = _read(record.heat_source, frm, cut, STATE_LOOKBACK)
    gap("heat_source", _known_gaps(heat_source, frm, cut), NO_RECORD)
    cuts = {frm, cut}
    if revision_since is not None:
        cuts.add(max(frm, min(revision_since, cut)))
    for lo, hi, _ in [
        *mode_series.pieces(frm, cut),
        *heat_source.pieces(frm, cut),
    ]:
        cuts |= {lo, hi}
    modes: list[ModeInterval] = []
    for lo, hi in pairwise(sorted(cuts)):
        mode = mode_series.at(lo)
        if mode is None:
            continue
        named = revision_since is None or lo >= revision_since
        name = profile.name_of(mode) if named else None
        eff = None
        if name is not None:
            hs = heat_source.at(lo)
            eff = profile.effective(
                name, None if hs is None else reported_sources(int(hs))
            )
        prev = modes[-1] if modes else None
        if (
            prev is not None
            and prev.end == lo
            and (prev.name, prev.effective) == (name, eff)
        ):
            modes[-1] = ModeInterval(prev.start, hi, name, eff)
        else:
            modes.append(ModeInterval(lo, hi, name, eff))

    setpoints: list[SetpointInterval] = []
    for lo, hi, f in setpoint_series.pieces(frm, cut):
        prev_sp = setpoints[-1] if setpoints else None
        if prev_sp is not None and prev_sp.end == lo and prev_sp.f == f:
            setpoints[-1] = SetpointInterval(prev_sp.start, hi, f)
        else:
            setpoints.append(SetpointInterval(lo, hi, f))

    upper = _read(record.upper_f, frm, cut, TANK_LOOKBACK)
    upper_pieces = upper.pieces(frm, cut, TANK_LOOKBACK)
    delivery = [(lo, f) for lo, _, f in upper_pieces]
    for lo, hi in _complement([(a, b) for a, b, _ in upper_pieces], frm, cut):
        held = any(t < lo for t, _ in upper.points)
        gap("delivery", [(lo, hi)], HOLD_EXCEEDED if held else NO_RECORD)

    running: dict[str, bool | None] = {"compressor": None, "element": None}
    if frm < cut:
        state = compressor.at(frm)
        running["compressor"] = None if state is None else bool(state)
        if not any(lo <= frm < hi for lo, hi, _ in gaps["elements"]):
            running["element"] = any(a <= frm < b for a, b in element_runs)

    if cut < to:
        for signal in SIGNALS:
            gaps[signal].append((cut, to, NOT_YET))
    return Observed(
        modes=modes,
        sources=sources,
        starts=starts,
        running_at_from=running,
        slots=slots,
        delivery_f=delivery,
        setpoints=setpoints,
        gaps=sorted(
            (
                Gap(lo, hi, signal, reason)
                for signal, items in gaps.items()
                for lo, hi, reason in _merge_reasons(items)
            ),
            key=lambda g: (g.start, SIGNALS.index(g.signal)),
        ),
    )


def _merge_reasons(
    items: Sequence[tuple[datetime, datetime, str]],
) -> list[tuple[datetime, datetime, str]]:
    out: list[tuple[datetime, datetime, str]] = []
    for reason in sorted({r for _, _, r in items}):
        for lo, hi in _merge([(a, b) for a, b, r in items if r == reason]):
            out.append((lo, hi, reason))
    return out
