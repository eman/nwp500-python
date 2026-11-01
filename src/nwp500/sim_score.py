"""A heater's parameters scored on recorded events they were not fitted
on.

``sim_calibrate`` fits each group of terms on its own evidence and
judges it by its own fit's error. That cannot compare two models whose
terms differ: a two-zone tank and a layered one share no gap constant,
and a refrigerant cycle and a performance map share no compressor
constant. This scores what every model answers, through the public
simulator (``sim.simulate``, ``sim.standby``, ``sim.readiness``), on
events taken from the record without any model:

- **recoveries**: each heat-pump recovery ``sim.calibration.snapshots``
  keeps, from its recorded start, asked how long it runs and what it
  uses; one with water in use only with a meter's draws, which it is
  predicted with;
- **quiet windows** (``sim.calibration.quiet_windows``): the tank
  coasting, against both probes every ``OBSERVE_EVERY``;
- **draws**: each metered draw with nothing else moving or heating
  around it, against both probes for ``DRAW_FOLLOW`` after;
- **deliveries**: each clean metered draw (``sim.calibration.
  clean_draws``) with the compressor off: one that took the upper
  probe below the line against the gallons it delivered before it did,
  one that did not as a floor the prediction should not fall under.

The events are fixed by the record alone, so two parameter sets scored
on the same history are scored on the same events (``Score.events``,
``compare``). An event the simulator cannot answer, or a recovery still
running at its horizon, is left out of the metrics and named
(``Score.failed_events``): two scores that left out different events
are not on the same events. Split a history in time
(``holdout_start``), fit on the part before, and score on the part
after.

Each metric carries how many events it rests on and a 90 % interval
from a bootstrap of local days: one day's events share a tank and the
air, and are not independent.

The stratified tank (``sim.physics.stratified``) is not yet the one
the simulator runs; ``score_layers`` scores it on the same quiet
windows and draws, each started from the layers the record's history
leaves (``sim.tank_fit.replay``), with the same metrics, and
``fit_layers`` fits its terms on a history's events.

Nothing here reads a file, the network or the clock: the caller reads
the history (``sim_calibrate.prepare``, ``prepare_changes``) and the
metered draws.
"""

import hashlib
import json
import math
from bisect import bisect_left
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from nwp500 import sim
from nwp500.sim import calibration as cal
from nwp500.sim import observed as obs
from nwp500.sim import record as rec
from nwp500.sim import tank_fit as tf
from nwp500.sim.engine import SimulationError
from nwp500.sim.inputs import POWER_OFF, VACATION
from nwp500.sim.params import HeaterParams, params_to_document
from nwp500.sim.physics import stratified as st
from nwp500.sim.physics.heat_pump import start_hold_min
from nwp500.sim.tank_physics import point_at

if TYPE_CHECKING:
    from nwp500.sim_calibrate import Prepared

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

#: The score document's schema.
SCHEMA = "sim-score/1"

#: How often a coast's probes are compared, and the air laid out.
OBSERVE_EVERY = timedelta(minutes=10)
#: How long the probes are followed after a draw.
DRAW_FOLLOW = timedelta(minutes=60)
#: No heating, circulation or other draw this long before a draw, so
#: the tank it starts from is settled.
DRAW_CLEAR = timedelta(minutes=30)
#: A quiet window is scored over at most this much of it.
MAX_WINDOW = timedelta(hours=24)
#: A recovery is walked this long past its recorded end, so a slow
#: prediction still ends inside the walk.
RECOVERY_SLACK = timedelta(hours=8)
#: The latest share of a history's days held out, and the fewest.
HOLDOUT_FRACTION = 0.20
MIN_HOLDOUT_DAYS = 3
#: The line a delivery is read at, °F (``ReadinessParams.line_f``'s
#: default).
LINE_F = 105.0
#: A predicted probe this far under the coldest air of a coast that
#: started above it breaks the second law: counted as ``below_air``.
BELOW_AIR_F = 0.05
#: A recorded start is placed by a predicted start of its source this
#: near it, each prediction placing one start at most.
START_MATCH = timedelta(minutes=30)
#: The slots a day's energy is laid out on, to read when it was used,
#: and the clock's grid the prediction's is read on first.
DAY_SLOT = timedelta(hours=1)
DAY_GRID = timedelta(minutes=5)
#: The heater's signals a scored day holds with no gap
#: (``sim.observed``): what ran, its power, and what it was told.
DAY_SIGNALS = frozenset({"compressor", "power", "mode", "setpoint", "elements"})
#: How far a day's lower stop threshold may sit from its setpoint (the
#: device's half-degree Celsius rounding) for the walk, which heats to
#: the setpoint, to be the heater's.
STOP_AT_SETPOINT_F = 0.5
#: How long after the setpoint the stop threshold may be reported, the
#: two arriving apart: each of the site installation's 105 setpoint
#: changes from 2026-09-18 to 2026-10-26 met by its stop threshold
#: within 15.1 s.
STOP_FOLLOWS = timedelta(minutes=1)
#: Bootstrap draws for each metric's interval, and its seed.
N_BOOT = 2000
SEED = 252

Reading = tuple[datetime, float]
Observed = tuple[datetime, float, float]


@dataclass(frozen=True)
class Recovery:
    """A recorded heat-pump recovery, from its compressor start."""

    start: datetime
    end: datetime
    upper_f: float
    lower_f: float
    #: The lower probe's stop threshold in force at the start.
    target_f: float
    setpoint_f: float
    air: tuple[Reading, ...]
    humidity: float
    #: No water in use from ``sim.calibration.DRAW_LEAD`` before it to
    #: its end.
    draw_free: bool
    #: The meter's energy over the run, Wh; None without a meter.
    metered_wh: float | None
    #: When the compressor last stopped before it; None when not seen.
    stopped_at: datetime | None
    #: The metered draws inside it, ``(instant, delivered gallons)``.
    draws: tuple[tuple[datetime, float], ...] = ()
    #: The setpoint's changes inside it, ``(instant, °F)``: the walk
    #: takes each as a write, as the heater did.
    setpoints: tuple[tuple[datetime, float], ...] = ()


@dataclass(frozen=True)
class Window:
    """A recorded quiet coast: nothing heating, no water moving."""

    start: datetime
    end: datetime
    upper_f: float
    lower_f: float
    air: tuple[Reading, ...]
    observed: tuple[Observed, ...]


@dataclass(frozen=True)
class DrawEvent:
    """A recorded draw with nothing else moving or heating around it."""

    at: datetime
    gallons: float
    upper_f: float
    lower_f: float
    air: tuple[Reading, ...]
    observed: tuple[Observed, ...]


@dataclass(frozen=True)
class Delivery:
    """A clean draw with the compressor off, and what it delivered."""

    at: datetime
    upper_f: float
    lower_f: float
    setpoint_f: float
    #: It took the upper probe below the line.
    crossed: bool
    #: Delivered gallons before the upper probe crossed the line; with
    #: ``crossed`` False, the whole draw's: what the tank held at least.
    delivered_gal: float


@dataclass(frozen=True)
class Day:
    """A recorded local day: what the heater was told over it, and what
    it did."""

    start: datetime
    end: datetime
    #: The day as the simulator takes it: the probes and what ran at
    #: its start, the settings and the restart lockout in force then,
    #: the TOU switch and its changes, the recorded setpoint and mode
    #: writes, the air and the metered draws. The layers and the
    #: circulation are the record's replay's, added when it is scored.
    scenario: sim.Scenario
    #: The TOU windows the heater marked over the day, its upper start
    #: threshold raised (``Record.upper_on_edges``).
    windows: tuple[tuple[datetime, datetime], ...]
    #: The heater's metered electricity over the day, Wh, and per
    #: ``DAY_SLOT`` from the day's start.
    metered_wh: float
    slots_wh: tuple[float, ...]
    #: The day's starts by source, one running at its start left out.
    compressor_starts: tuple[datetime, ...]
    element_starts: tuple[datetime, ...]
    #: The upper probe's lowest reading over the day, and both probes
    #: at its end.
    min_upper_f: float
    end_upper_f: float
    end_lower_f: float
    #: With the compressor running at the day's start: when that run
    #: began (its hold, by the time off before it, may not be over).
    compressor_on_since: datetime | None = None


@dataclass(frozen=True)
class Events:
    """The events a history is scored on."""

    recoveries: tuple[Recovery, ...] = ()
    windows: tuple[Window, ...] = ()
    draws: tuple[DrawEvent, ...] = ()
    deliveries: tuple[Delivery, ...] = ()
    #: Whole recorded days (``day_events``): none unless asked for.
    days: tuple[Day, ...] = ()

    def keys(self) -> dict[str, list[str]]:
        """Each kind's events by their instants, as a score document
        carries them; ``days`` only when there are some, so a score
        without them reads as one made before they were scored."""
        out = {
            "recoveries": [_iso(e.start) for e in self.recoveries],
            "windows": [_iso(e.start) for e in self.windows],
            "draws": [_iso(e.at) for e in self.draws],
            "deliveries": [_iso(e.at) for e in self.deliveries],
        }
        if self.days:
            out["days"] = [_iso(e.start) for e in self.days]
        return out


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


# ── the split ──────────────────────────────────────────────────────


def holdout_start(
    instants: Iterable[datetime],
    *,
    tz: str = "UTC",
    fraction: float = HOLDOUT_FRACTION,
    min_days: int = MIN_HOLDOUT_DAYS,
) -> datetime | None:
    """The local midnight the held-out days start at: the latest
    ``fraction`` of the days ``instants`` cover, at least ``min_days``.
    None when that would leave no day to fit on."""
    zone = ZoneInfo(tz)
    days = sorted({t.astimezone(zone).date() for t in instants})
    held = max(min_days, round(len(days) * fraction))
    if held >= len(days):
        return None
    return datetime.combine(days[-held], time(), tzinfo=zone).astimezone(UTC)


# ── the events ─────────────────────────────────────────────────────


def _seconds(frame: pd.DataFrame) -> np.ndarray:
    index = pd.DatetimeIndex(frame.index)
    return index.as_unit("ns").asi8 / 1e9


def _asof(
    values: np.ndarray, seconds: np.ndarray, at: datetime
) -> float | None:
    """The last finite value at or before ``at``."""
    k = int(np.searchsorted(seconds, at.timestamp(), side="right"))
    while k > 0:
        v = float(values[k - 1])
        if math.isfinite(v):
            return v
        k -= 1
    return None


def _changes(
    values: np.ndarray, seconds: np.ndarray, start: datetime, end: datetime
) -> tuple[tuple[datetime, float], ...]:
    """Each finite value after ``start`` and before ``end`` that differs
    from the last before it (the one in force at ``start`` first)."""
    lo = int(np.searchsorted(seconds, start.timestamp(), side="right"))
    hi = int(np.searchsorted(seconds, end.timestamp(), side="left"))
    last = _asof(values, seconds, start)
    out: list[tuple[datetime, float]] = []
    for k in range(lo, hi):
        v = float(values[k])
        if math.isfinite(v) and v != last:
            out.append((datetime.fromtimestamp(float(seconds[k]), UTC), v))
            last = v
    return tuple(out)


def _grid(start: datetime, end: datetime) -> list[datetime]:
    """``OBSERVE_EVERY`` from ``start`` to ``end``, both included."""
    out = [start]
    while out[-1] + OBSERVE_EVERY < end:
        out.append(out[-1] + OBSERVE_EVERY)
    if out[-1] < end:
        out.append(end)
    return out


def _readings(
    values: np.ndarray, seconds: np.ndarray, at: Sequence[datetime]
) -> tuple[Reading, ...] | None:
    """``values`` as of each of ``at``; None when any is unknown."""
    out: list[Reading] = []
    for t in at:
        v = _asof(values, seconds, t)
        if v is None:
            return None
        out.append((t, v))
    return tuple(out)


def _observed(
    upper: np.ndarray,
    lower: np.ndarray,
    seconds: np.ndarray,
    at: Sequence[datetime],
) -> tuple[Observed, ...] | None:
    out: list[Observed] = []
    for t in at:
        u, lo = _asof(upper, seconds, t), _asof(lower, seconds, t)
        if u is None or lo is None:
            return None
        out.append((t, u, lo))
    return tuple(out)


def _flag(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        return np.zeros(len(frame), dtype=bool)
    return frame[name].fillna(False).astype(bool).to_numpy()


def _any_in(
    on: np.ndarray, seconds: np.ndarray, start: datetime, end: datetime
) -> bool:
    """Whether ``on`` holds over any part of ``[start, end]``: a row's
    value holds to the next row, so the row in force at ``start``
    counts."""
    a = max(
        int(np.searchsorted(seconds, start.timestamp(), side="right")) - 1, 0
    )
    b = int(np.searchsorted(seconds, end.timestamp(), side="right"))
    return bool(on[a:b].any())


def _in_range(
    at: datetime, since: datetime | None, until: datetime | None
) -> bool:
    return (since is None or at >= since) and (until is None or at < until)


def _stops(frame: pd.DataFrame) -> list[datetime]:
    """The compressor's off-edges."""
    on = _flag(frame, "compressor_on")
    index = pd.DatetimeIndex(frame.index)
    edges = np.flatnonzero(~on[1:] & on[:-1]) + 1
    return [cast(datetime, index[i].to_pydatetime()) for i in edges]


def _recoveries(
    ready: Prepared,
    draws: Sequence[tuple[datetime, float]],
    since: datetime | None,
    until: datetime | None,
) -> list[Recovery]:
    frame = ready.frame
    rows = cal.snapshots(
        frame, air=ready.recovery_air, draws=list(draws) or None
    )
    if rows.empty:
        return []
    # Each recovery from its start: its first snapshot.
    rows = cast(pd.DataFrame, rows.loc[rows["offset_minutes"] == 0.0])
    seconds = _seconds(frame)
    air_v = (
        frame[ready.recovery_air].to_numpy(dtype=float)
        if ready.recovery_air in frame.columns
        else np.full(len(frame), np.nan)
    )
    setpoint_v = (
        frame["setpoint_f"].to_numpy(dtype=float)
        if "setpoint_f" in frame.columns
        else np.full(len(frame), np.nan)
    )
    humidity_v = (
        frame["humidity_pct"].to_numpy(dtype=float)
        if "humidity_pct" in frame.columns
        else np.full(len(frame), np.nan)
    )
    stops = _stops(frame)

    def column(name: str) -> np.ndarray:
        return rows[name].to_numpy(dtype=float)

    def instants(name: str) -> list[datetime]:
        return [
            cast(datetime, pd.Timestamp(t).to_pydatetime()) for t in rows[name]
        ]

    starts, ends = instants("start_time"), instants("end_time")
    upper, lower = column("t_start_upper"), column("t_start_lower")
    # ``delta_t_lower`` is the target in force less the lower probe.
    target = lower + column("delta_t_lower")
    mean_air = column("t_amb_mean")
    metered = rows["metered_input_wh"].to_numpy(dtype=float, na_value=np.nan)
    draw_free = rows["draw_free"].to_numpy(dtype=bool)
    reached = rows["reached"].to_numpy(dtype=bool)
    out: list[Recovery] = []
    for k, (start, end) in enumerate(zip(starts, ends, strict=True)):
        # One stopped short of its target says nothing of how long it
        # takes: the compressor's fit leaves it out too.
        if not reached[k] or not _in_range(start, since, until):
            continue
        # One with water in use is predicted with the meter's draws;
        # without a meter, what it drew is unknown.
        if not draw_free[k] and not draws:
            continue
        # The air the run met, as the fits read it; the last reading
        # holds past its end, where the walk may run on.
        air: list[Reading] = []
        for t in _grid(start, end):
            v = _asof(air_v, seconds, t)
            if v is not None:
                air.append((t, v))
        if not air:
            air = [(start, float(mean_air[k]))]
        setpoint = _asof(setpoint_v, seconds, start)
        humidity = _asof(humidity_v, seconds, start)
        before = [t for t in stops if t <= start]
        wh = float(metered[k])
        out.append(
            Recovery(
                start=start,
                end=end,
                upper_f=float(upper[k]),
                lower_f=float(lower[k]),
                target_f=float(target[k]),
                setpoint_f=float(target[k]) if setpoint is None else setpoint,
                air=tuple(air),
                humidity=50.0 if humidity is None else humidity,
                draw_free=bool(draw_free[k]),
                metered_wh=wh if math.isfinite(wh) else None,
                stopped_at=before[-1] if before else None,
                draws=tuple((t, g) for t, g in draws if start <= t < end),
                setpoints=_changes(setpoint_v, seconds, start, end),
            )
        )
    return out


def _standby_air(frame: pd.DataFrame) -> np.ndarray | None:
    """The air a coast is walked in: the frame's ``air_f``, which the
    standby fit reads (a sensor's, or the cabinet's less its warmth)."""
    if "air_f" not in frame.columns:
        return None
    return frame["air_f"].to_numpy(dtype=float)


def _windows(
    ready: Prepared, since: datetime | None, until: datetime | None
) -> list[Window]:
    frame = ready.frame
    air_v = _standby_air(frame)
    if air_v is None:
        return []
    seconds = _seconds(frame)
    upper = frame["upper_f"].to_numpy(dtype=float)
    lower = frame["lower_f"].to_numpy(dtype=float)
    unobserved = _flag(frame, "heater_unobserved") | _flag(
        frame, "air_unobserved"
    )
    out: list[Window] = []
    shortest = timedelta(hours=cal.MIN_QUIET_HOURS)
    for start, end in cal.quiet_windows(frame):
        # A window across the split is scored on its part inside.
        start = start if since is None else max(start, since)
        end = end if until is None else min(end, until)
        if end - start < shortest:
            continue
        end = min(end, start + MAX_WINDOW)
        if _any_in(unobserved, seconds, start, end):
            continue
        at = _grid(start, end)
        air = _readings(air_v, seconds, at)
        # The start is the coast's own state, scored from the next
        # reading on, as a draw's hour is.
        seen = _observed(upper, lower, seconds, at)
        if air is None or seen is None or len(seen) < 2:
            continue
        out.append(Window(start, end, seen[0][1], seen[0][2], air, seen[1:]))
    return out


def _draw_events(
    ready: Prepared,
    draws: Sequence[tuple[datetime, float]],
    since: datetime | None,
    until: datetime | None,
) -> list[DrawEvent]:
    frame = ready.frame
    air_v = _standby_air(frame)
    if air_v is None or not draws:
        return []
    seconds = _seconds(frame)
    upper = frame["upper_f"].to_numpy(dtype=float)
    lower = frame["lower_f"].to_numpy(dtype=float)
    busy = (
        _flag(frame, "compressor_on")
        | _flag(frame, "element_on")
        | _flag(frame, "circulating")
        | _flag(frame, "heater_unobserved")
        | _flag(frame, "excluded")
    )
    ordered = sorted(draws)
    last = cast(datetime, pd.Timestamp(frame.index[-1]).to_pydatetime())
    out: list[DrawEvent] = []
    for k, (at, gal) in enumerate(ordered):
        if gal <= 0.0 or not _in_range(at, since, until):
            continue
        a, b = at - DRAW_CLEAR, at + DRAW_FOLLOW
        # The hour after it is read from the history, not held past it.
        if b > last:
            continue
        others = [t for j, (t, _) in enumerate(ordered) if j != k and a < t < b]
        if others or _any_in(busy, seconds, a, b):
            continue
        # The tank just before the draw: its probes' last reading.
        u0 = _asof(upper, seconds, at - timedelta(seconds=1))
        l0 = _asof(lower, seconds, at - timedelta(seconds=1))
        grid = _grid(at, b)
        air = _readings(air_v, seconds, grid)
        seen = _observed(upper, lower, seconds, grid[1:])
        if u0 is None or l0 is None or air is None or seen is None:
            continue
        out.append(DrawEvent(at, gal, u0, l0, air, seen))
    return out


def _deliveries(
    flow: pd.DataFrame | None,
    setpoint_of: Callable[[datetime], float | None],
    line_f: float,
    since: datetime | None,
    until: datetime | None,
) -> list[Delivery]:
    if flow is None or flow.empty:
        return []
    out: list[Delivery] = []
    for d in cal.clean_draws(flow):
        # The compressor's heat would be credited to the tank, as the
        # evidence fit leaves it out too.
        if d.hp or not _in_range(d.start, since, until):
            continue
        gal, crossed = cal.crossing(d, line_f - 1e-9)
        setpoint = setpoint_of(d.start)
        out.append(
            Delivery(
                at=d.start,
                upper_f=d.u0,
                lower_f=d.l0,
                setpoint_f=d.u0 if setpoint is None else setpoint,
                crossed=crossed,
                delivered_gal=gal,
            )
        )
    return out


def events(
    ready: Prepared,
    *,
    draws: Sequence[tuple[datetime, float]] = (),
    flow: pd.DataFrame | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    line_f: float = LINE_F,
) -> Events:
    """The events ``ready``'s history holds that start in ``[since,
    until)``. ``draws`` are a meter's, ``(instant, delivered gallons)``
    at each draw's onset; ``flow`` is the meter on
    ``sim.calibration.clean_draws``' grid, for the deliveries. Without
    either, those kinds are empty."""
    frame = ready.frame
    seconds = _seconds(frame)
    setpoint_v = (
        frame["setpoint_f"].to_numpy(dtype=float)
        if "setpoint_f" in frame.columns
        else np.full(len(frame), np.nan)
    )
    return Events(
        recoveries=tuple(_recoveries(ready, draws, since, until)),
        windows=tuple(_windows(ready, since, until)),
        draws=tuple(_draw_events(ready, draws, since, until)),
        deliveries=tuple(
            _deliveries(
                flow,
                lambda t: _asof(setpoint_v, seconds, t),
                line_f,
                since,
                until,
            )
        ),
    )


# ── the days ───────────────────────────────────────────────────────


def _at(rows: rec.Rows, at: datetime, heater: rec.Record) -> float | None:
    got = rec.last(rows, at, heater.setting_lookback)
    return None if got is None else got[1]


def _on_since(rows: rec.Rows, at: datetime) -> datetime | None:
    """When an on/off series last turned on at or before ``at``, if it
    is on then."""
    since = None
    for t, v in rows:
        if t > at:
            break
        on = v >= 0.5
        since = (since or t) if on else None
    return since


def _mode(value: float) -> int:
    """A recorded ``DhwOperationSetting`` as the simulator's mode: the
    status-only Standby is Power Off, as ``sim_adapters.settings``
    reads it."""
    return POWER_OFF if int(value) == 0 else int(value)


def _marked(
    heater: rec.Record, start: datetime, end: datetime
) -> tuple[tuple[datetime, datetime], ...]:
    """The windows the heater marked over ``[start, end]``: one open at
    the start from its opening within the day before (the walk judges
    an opening where the window opens, not where the day does), else
    from the start; one open at the end to its close within the next
    day, or the end."""
    opens, closes = heater.upper_on_edges(start, end)
    prior = rec.last(
        heater.hp_upper_on_f,
        start - timedelta(microseconds=1),
        heater.setting_lookback,
    )
    line = heater.resting_upper_on_f + rec.RAISED_BY_F
    opened = None
    if prior is not None and prior[1] > line:
        before, _ = heater.upper_on_edges(
            start - timedelta(days=1), start - timedelta(microseconds=1)
        )
        opened = before[-1] if before else start
    out: list[tuple[datetime, datetime]] = []
    for t, up in sorted(
        [(t, True) for t in opens] + [(t, False) for t in closes]
    ):
        if up and opened is None:
            opened = t
        elif not up and opened is not None:
            out.append((opened, t))
            opened = None
    if opened is not None:
        _, later = heater.upper_on_edges(end, end + timedelta(days=1))
        out.append((opened, later[0] if later else end))
    return tuple(out)


def _stops_at_setpoint(
    heater: rec.Record, before: datetime, end: datetime
) -> bool:
    """Whether the lower stop threshold sat on the setpoint (within
    ``STOP_AT_SETPOINT_F``) from ``before`` to ``end``, read wherever
    both had settled: at ``before`` and ``STOP_FOLLOWS`` after each
    change of either, each read with no change in the ``STOP_FOLLOWS``
    before it (one reported apart from the other follows it), and none
    read past ``end``, the next day's."""
    changes = sorted(
        {
            t
            for series in (heater.hp_lower_off_f, heater.setpoint_f)
            for t, _ in rec.between(series, before - STOP_FOLLOWS, end)
        }
    )
    reads = [before, *(t + STOP_FOLLOWS for t in changes)]
    settled = [
        r
        for r in reads
        if r < end and not any(r - STOP_FOLLOWS < c <= r for c in changes)
    ]
    for t in settled:
        off = _at(heater.hp_lower_off_f, t, heater)
        setpoint = _at(heater.setpoint_f, t, heater)
        if off is None or setpoint is None:
            return False
        if abs(off - setpoint) > STOP_AT_SETPOINT_F:
            return False
    return True


def _one_day(
    heater: rec.Record,
    record: tf.TankRecord,
    frame: pd.DataFrame,
    unobserved: np.ndarray,
    start: datetime,
    end: datetime,
    tz: str,
) -> Day | None:
    """The day ``[start, end)``, or None when the record cannot say
    what the heater was told or did over all of it. The probes are the
    frame's, as every event's are: read where the heater was heard."""
    seconds = _seconds(frame)
    before = start - timedelta(microseconds=1)
    if _any_in(unobserved, seconds, start, end - timedelta(microseconds=1)):
        return None
    if record.minute(start) < 0 or record.minute(end) > len(record):
        return None
    seen = obs.observe(heater, start, end, now=end)
    if any(g.signal in DAY_SIGNALS for g in seen.gaps):
        return None
    if any(s.energy_wh is None or s.partial for s in seen.slots):
        return None
    upper_v = frame["upper_f"].to_numpy(dtype=float)
    lower_v = frame["lower_f"].to_numpy(dtype=float)
    upper, lower = (
        _asof(upper_v, seconds, start),
        _asof(lower_v, seconds, start),
    )
    setpoint, mode = (
        _at(heater.setpoint_f, before, heater),
        _at(heater.mode, before, heater),
    )
    end_upper, end_lower = (
        _asof(upper_v, seconds, end),
        _asof(lower_v, seconds, end),
    )
    if (
        upper is None
        or lower is None
        or setpoint is None
        or mode is None
        or end_upper is None
        or end_lower is None
    ):
        return None
    # No rule for what a write into or out of these does.
    if _mode(mode) in (VACATION, POWER_OFF):
        return None
    writes: list[sim.Write] = []
    # A write at the day's first instant is the day's, replayed against
    # what was in force before it.
    for w in heater.writes(before, end):
        # The walk drops an element mode where a window opens; one the
        # heater dropped for a window opened before the day began, the
        # walk cannot, so it is replayed.
        if w.dropped and (w.dropped_for is None or w.dropped_for >= start):
            continue
        if w.mode is not None:
            if _mode(w.mode) in (VACATION, POWER_OFF):
                return None
            writes.append(sim.Write(at=w.at, mode=_mode(w.mode)))
        if w.setpoint_f is not None:
            writes.append(sim.Write(at=w.at, setpoint_f=w.setpoint_f))
    starts = heater.starts(start, end)
    running = {(s.source, s.zone) for s in starts.starts if s.running}
    stops = [t for t in starts.stops if t <= start]
    compressor = ("compressor", None) in running
    on_since = _on_since(heater.compressor, start) if compressor else None
    off_before = (
        None
        if on_since is None
        else max((t for t in starts.stops if t < on_since), default=None)
    )
    upper_since = _on_since(heater.upper_element, start)
    lower_since = _on_since(heater.lower_element, start)
    element_since = upper_since if upper_since is not None else lower_since
    element = any(src == "element" for src, _ in running)
    tou = _at(heater.tou, before, heater)
    lower_on = _at(heater.hp_lower_on_f, before, heater)
    lower_off = _at(heater.hp_lower_off_f, before, heater)
    upper_on = _at(heater.hp_upper_on_f, before, heater)
    # Without them the walk starts no lower-zone recovery, aims at the
    # setpoint, or keeps no TOU window: not the heater's day.
    if tou is None or lower_on is None or lower_off is None or upper_on is None:
        return None
    # The walk heats a recovery to the setpoint (``simulate`` reads no
    # stop threshold): a heater told to stop short of it is not walked.
    if not _stops_at_setpoint(heater, before, end):
        return None
    draws = tuple(
        sim.Draw(at=t, gallons=g)
        for t, g in record.draws
        if start <= t < end and g > 0.0
    )
    scenario = sim.Scenario(
        start=start,
        horizon=end - start,
        tz=tz,
        state=sim.HeaterState(
            upper_f=upper,
            lower_f=lower,
            compressor_running=compressor,
            element_running=element,
            element_running_since=element_since if element else None,
        ),
        settings=sim.Settings(
            setpoint_f=setpoint,
            mode=_mode(mode),
            hp_lower_on_f=lower_on,
            hp_lower_off_f=lower_off,
            hp_upper_on_f=upper_on,
        ),
        history=sim.History(
            compressor_stopped_at=off_before
            if compressor
            else (stops[-1] if stops else None)
        ),
        schedules=sim.Schedules(
            tou_enabled=tou >= 0.5,
            tou_switches=tuple(heater.tou_switches(before, end)),
        ),
        environment=sim.Environment(
            ambient_f=tuple((t, record.air_at(t)) for t in _grid(start, end))
        ),
        loads=sim.Loads(draws=draws),
        commands=sim.Commands(writes=tuple(writes)),
    )
    n = math.ceil((end - start) / DAY_SLOT)
    slots = [0.0] * n
    for s in seen.slots:
        slots[int((s.start - start) / DAY_SLOT)] += float(s.energy_wh or 0.0)
    a = int(np.searchsorted(seconds, start.timestamp(), side="right"))
    # To the reading at the day's end, which the walk's lowest and the
    # day's end probes both hold.
    b = int(np.searchsorted(seconds, end.timestamp(), side="right"))
    inside = upper_v[a:b]
    uppers = [upper, *(float(v) for v in inside[np.isfinite(inside)])]
    return Day(
        start=start,
        end=end,
        scenario=scenario,
        windows=_marked(heater, start, end),
        metered_wh=sum(slots),
        slots_wh=tuple(slots),
        compressor_starts=tuple(
            s.at
            for s in starts.starts
            if s.source == "compressor" and not s.running
        ),
        element_starts=tuple(
            s.at
            for s in starts.starts
            if s.source == "element" and not s.running
        ),
        min_upper_f=min(uppers),
        end_upper_f=end_upper,
        end_lower_f=end_lower,
        compressor_on_since=on_since,
    )


def day_events(
    ready: Prepared,
    heater: rec.Record,
    record: tf.TankRecord,
    *,
    tz: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[Day, ...]:
    """The whole local days in ``tz`` that start in ``[since, until)``
    and that ``ready``'s history observed throughout: the heater heard
    and the air read (its frame's ``heater_unobserved``,
    ``air_unobserved`` and ``unrecorded``), what ran, its power and
    what it was told recorded in ``heater`` with no gap
    (``DAY_SIGNALS``), the lower probe's thresholds, the upper's start
    threshold and the TOU switch known at its start, and the tank's
    ``record`` (``tank_fit.tank_record``) covering it, its metered
    draws the day's. A day with a write into or out of Vacation or
    Power Off, or spent in either, is left out: the simulator holds no
    rule for such a write. So is one whose lower stop threshold sits
    off the setpoint (by more than ``STOP_AT_SETPOINT_F``): the walk
    heats a recovery to the setpoint. A write at the day's first
    instant is the day's, replayed against what was in force before
    it; a TOU window open at midnight keeps the opening the heater
    marked the day before.

    ``heater`` carries what ``ready``'s frame does not: the mode, the
    lower probe's start and stop thresholds, the upper's start
    threshold (whose rise marks a TOU window in force) and the TOU
    switch, each read as far back as
    ``sim.observed`` reads a setting (``STATE_LOOKBACK``): one set once
    holds until it changes. A day is predicted with the
    windows the heater marked, not a schedule's: its TOU schedule over
    the past is not recorded."""
    zone = ZoneInfo(tz)
    # A setting is recorded only when it changes, and may hold for
    # longer than the record's own lookback: read as ``observe`` reads.
    heater = replace(heater, setting_lookback=obs.STATE_LOOKBACK)
    frame = ready.frame
    # ``unrecorded``: a recorder's silence (``sim_adapters.add_inputs``),
    # over which ``observe`` would hold the heater's last values.
    unobserved = (
        _flag(frame, "heater_unobserved")
        | _flag(frame, "air_unobserved")
        | _flag(frame, "unrecorded")
    )
    first = record.instant(0)
    last = record.instant(len(record) - 1) + timedelta(minutes=1)
    out: list[Day] = []
    d = first.astimezone(zone).date()
    while True:
        start = datetime.combine(d, time(), tzinfo=zone).astimezone(UTC)
        end = datetime.combine(
            d + timedelta(days=1), time(), tzinfo=zone
        ).astimezone(UTC)
        d += timedelta(days=1)
        if end > last or (until is not None and start >= until):
            break
        if start < first or (since is not None and start < since):
            continue
        day = _one_day(heater, record, frame, unobserved, start, end, tz)
        if day is not None:
            out.append(day)
    return tuple(out)


# ── the predictions ────────────────────────────────────────────────


@dataclass
class _Tally:
    """Each event's errors, by metric, with the local day it fell on."""

    values: dict[str, list[float]] = field(default_factory=dict)
    days: dict[str, list[int]] = field(default_factory=dict)

    def add(self, name: str, value: float, day: int) -> None:
        if math.isfinite(value):
            self.values.setdefault(name, []).append(value)
            self.days.setdefault(name, []).append(day)


def _day(at: datetime, tz: ZoneInfo) -> int:
    return at.astimezone(tz).date().toordinal()


def _environment(
    air: Sequence[Reading], humidity: float, inlet_f: float | None
) -> sim.Environment:
    return sim.Environment(
        ambient_f=tuple(air),
        humidity=min(100.0, max(0.0, humidity)),
        inlet_f=inlet_f,
    )


def _state(
    params: HeaterParams,
    record: tf.TankRecord | None,
    at: datetime,
    upper_f: float,
    lower_f: float,
    **kw: Any,
) -> sim.HeaterState:
    """The heater at an event's start: its probes, and with a
    ``record``, the layers its replay leaves (``tank_fit.start_state``)."""
    layers = None
    if record is not None:
        lay = st.layout(params)
        layers = tf.start_state(
            lay, params, _replayable(record, at), at, upper_f, lower_f
        ).layers_f
    return sim.HeaterState(
        upper_f=upper_f, lower_f=lower_f, layers_f=layers, **kw
    )


def _without_own_draw(record: tf.TankRecord, at: datetime) -> tf.TankRecord:
    """``record`` up to a delivery at ``at`` (``TankRecord.before``),
    without the draws whose onset falls in the settle before it: the
    meter saw no flow there (``calibration.DRAW_SETTLE_S``), so a draw
    another clock places there is the delivery's own, which the replay
    would otherwise take from the tank it starts."""
    part = record.before(at)
    settle = at - timedelta(seconds=cal.DRAW_SETTLE_S)
    return replace(
        part, draws=tuple(d for d in part.draws if not settle <= d[0] <= at)
    )


def _replayable(record: tf.TankRecord, at: datetime) -> tf.TankRecord:
    """``record`` up to an event at ``at`` (``TankRecord.before``), its
    draws in the minute ``at`` falls in, before it, moved to a
    microsecond before that minute's start. The replay to ``at`` stops
    at that start, its last span taking what comes before it
    (``tank_fit.replay``), and an event's own draws start at ``at`` (a
    delivery's is left out first, ``_without_own_draw``): so every draw
    before an event is replayed, then corrected to the probes it starts
    from, which were read after it."""
    part = record.before(at)
    cut = part.instant(part.minute(at))
    lo = bisect_left(part.draws, (cut, -math.inf))
    hi = bisect_left(part.draws, (at, -math.inf))
    if lo == hi:
        return part
    edge = cut - timedelta(microseconds=1)
    moved = tuple((edge, g) for _, g in part.draws[lo:hi])
    return replace(part, draws=part.draws[:lo] + moved + part.draws[hi:])


def _loads(
    record: tf.TankRecord | None,
    start: datetime,
    end: datetime,
    draws: tuple[sim.Draw, ...] = (),
    params: HeaterParams | None = None,
) -> sim.Loads:
    """An event's loads: its ``draws`` (``_timed``), and with a
    ``record``, the circulation runs it recorded from ``start`` to
    ``end`` (an event with none is known to have had none)."""
    if record is None:
        return sim.Loads(draws=draws)
    if params is not None:
        draws = _timed(draws, record, params)
    i, j = record.minute(start), record.minute(end) + 1
    runs = tuple(
        sim.CirculationRun(start=record.instant(a), end=record.instant(b))
        for a, b in record.circulating
        if a < j and b > i
    )
    return sim.Loads(draws=draws, circulation=runs, circulation_known_until=end)


def _timed(
    draws: tuple[sim.Draw, ...], record: tf.TankRecord, params: HeaterParams
) -> tuple[sim.Draw, ...]:
    """``draws`` as the score walks them: one the record's draw detector
    times (``TankRecord.draw_seconds``) at ``params.draw.undiluted_gpm``
    or faster over its span, which it takes the tank's water whole
    through; every other all at its onset, where the meter sizes it
    (timing them all scored worse: ``simulator-tried``)."""
    out: list[sim.Draw] = []
    for d in draws:
        seconds = record.draw_seconds.get(d.at, 0.0)
        if (
            d.duration_s == 0.0
            and seconds > 0.0
            and params.draw.undiluted(d.gallons / (seconds / 60.0))
        ):
            d = d.model_copy(update={"duration_s": seconds})
        out.append(d)
    return tuple(out)


def _recovery_score(
    e: Recovery,
    params: HeaterParams,
    inlet_f: float | None,
    tally: _Tally,
    day: int,
    record: tf.TankRecord | None = None,
) -> bool:
    """The recovery predicted from its recorded start, started there
    (``running_starts``: its stir taken), with the hold
    ``params`` give a start after the time off it had; False when the
    simulator could not answer."""
    horizon = (e.end - e.start) + RECOVERY_SLACK
    draws = tuple(sim.Draw(at=t, gallons=g) for t, g in e.draws)
    hold = start_hold_min(
        params.compressor,
        None
        if e.stopped_at is None
        else (e.start - e.stopped_at).total_seconds() / 60.0,
    )
    try:
        result = sim.simulate(
            sim.Scenario(
                start=e.start,
                horizon=horizon,
                tz="UTC",
                state=_state(
                    params,
                    record,
                    e.start,
                    e.upper_f,
                    e.lower_f,
                    compressor_running=True,
                ),
                settings=sim.Settings(
                    setpoint_f=e.setpoint_f, hp_lower_off_f=e.target_f
                ),
                history=sim.History(compressor_stopped_at=e.stopped_at),
                environment=_environment(e.air, e.humidity, inlet_f),
                loads=_loads(record, e.start, e.start + horizon, draws, params),
                commands=sim.Commands(
                    writes=tuple(
                        sim.Write(at=t, setpoint_f=v) for t, v in e.setpoints
                    )
                ),
            ),
            params,
            running_hold=hold,
            running_starts=True,
        )
    except SimulationError, ValueError:
        return False
    runs = sorted(
        (h for h in result.heating if h.source == "compressor"),
        key=lambda h: h.start.at,
    )
    if not runs:
        return False
    # A setpoint lowered and raised back stops the walk's compressor and
    # starts it again once the write's lag and the lockout allow, and a
    # raise after the walk reached the setpoint in force starts it
    # again: the writes are the recorded run's own, which went on through
    # them, so the chain is the run, up to a restart after it ended.
    first, last = runs[0], runs[0]
    input_wh = first.input_wh
    for h in runs[1:]:
        if not (
            last.stop in ("write", "target")
            and h.start.cause == "write"
            and h.start.at < e.end
        ):
            break
        last = h
        input_wh = (
            None
            if input_wh is None or h.input_wh is None
            else input_wh + h.input_wh
        )
    # Still running at the horizon: its end, and so its error, unknown.
    if last.stop == "horizon":
        return False
    minutes = (last.end - first.start.at).total_seconds() / 60.0
    actual = (e.end - e.start).total_seconds() / 60.0
    kind = "draw_free" if e.draw_free else "with_draws"
    for which in ("all", kind):
        tally.add(f"recovery_minutes_abs.{which}", abs(minutes - actual), day)
        tally.add(f"recovery_minutes_bias.{which}", minutes - actual, day)
    if e.draw_free and e.metered_wh and input_wh is not None:
        tally.add(
            "recovery_energy_abs_pct",
            100.0 * abs(input_wh - e.metered_wh) / e.metered_wh,
            day,
        )
        tally.add(
            "recovery_energy_bias_pct",
            100.0 * (input_wh - e.metered_wh) / e.metered_wh,
            day,
        )
    return True


def _coast_errors(
    points: Sequence[Any], observed: Sequence[Observed]
) -> tuple[float, float, float, float]:
    """The coast's RMSE on each probe, its mean's end error and its
    gap's end error against ``observed``."""
    du: list[float] = []
    dl: list[float] = []
    for t, u, lo in observed:
        p = point_at(points, t)
        du.append(p.upper_f - u)
        dl.append(p.lower_f - lo)
    end_mean = (du[-1] + dl[-1]) / 2.0
    end_gap = du[-1] - dl[-1]
    return (
        float(np.sqrt(np.mean(np.square(du)))),
        float(np.sqrt(np.mean(np.square(dl)))),
        end_mean,
        end_gap,
    )


def _below_air(
    points: Sequence[Any], air: Sequence[Reading], upper: float, lower: float
) -> bool:
    """Whether a coast that started above all its air took a probe
    below it: heat flowing from cold to hot."""
    coldest = min(v for _, v in air)
    if min(upper, lower) < max(v for _, v in air):
        return False
    return any(
        min(p.upper_f, p.lower_f) < coldest - BELOW_AIR_F for p in points
    )


def _window_score(
    e: Window,
    params: HeaterParams,
    inlet_f: float | None,
    tally: _Tally,
    day: int,
    breaks: dict[str, int],
    record: tf.TankRecord | None = None,
) -> bool:
    try:
        trace = sim.standby(
            _state(params, record, e.start, e.upper_f, e.lower_f),
            _environment(e.air, 50.0, inlet_f),
            _loads(record, e.start, e.end),
            params,
            start=e.start,
            until=e.end,
        )
    except SimulationError, ValueError:
        return False
    ru, rl, mean, gap = _coast_errors(trace.points, e.observed)
    hours = (e.end - e.start).total_seconds() / 3600.0
    tally.add("standby_upper_rmse_f", ru, day)
    tally.add("standby_lower_rmse_f", rl, day)
    tally.add("standby_fall_abs_f_h", abs(mean) / hours, day)
    tally.add("standby_gap_sq_f2", gap * gap, day)
    if _below_air(trace.points, e.air, e.upper_f, e.lower_f):
        breaks["below_air"] += 1
    return True


def _draw_score(
    e: DrawEvent,
    params: HeaterParams,
    inlet_f: float | None,
    tally: _Tally,
    day: int,
    record: tf.TankRecord | None = None,
) -> bool:
    try:
        trace = sim.standby(
            _state(params, record, e.at, e.upper_f, e.lower_f),
            _environment(e.air, 50.0, inlet_f),
            _loads(
                record,
                e.at,
                e.at + DRAW_FOLLOW,
                (sim.Draw(at=e.at, gallons=e.gallons),),
                params,
            ),
            params,
            start=e.at,
            until=e.at + DRAW_FOLLOW,
        )
    except SimulationError, ValueError:
        return False
    ru, rl, _, _ = _coast_errors(trace.points, e.observed)
    tally.add("draw_upper_rmse_f", ru, day)
    tally.add("draw_lower_rmse_f", rl, day)
    return True


def _delivery_score(
    e: Delivery,
    params: HeaterParams,
    inlet_f: float | None,
    tally: _Tally,
    day: int,
    record: tf.TankRecord | None = None,
) -> tuple[bool, bool]:
    """Scored, and whether it promised more than a crossing delivered.
    A draw that did not cross delivered at least its gallons: only a
    prediction under them is an error, an under-promise."""
    if record is not None:
        record = _without_own_draw(record, e.at)
    try:
        got = sim.readiness(
            _state(params, record, e.at, e.upper_f, e.lower_f),
            sim.Settings(setpoint_f=e.setpoint_f),
            params,
            inlet_f=inlet_f,
            on=e.at,
        )
    except SimulationError, ValueError:
        return False, False
    error = got.gal - e.delivered_gal
    if not e.crossed:
        tally.add("deliverable_short_gal", max(0.0, -error), day)
        tally.add("deliverable_under_share", float(error < 0.0), day)
        return True, False
    tally.add("deliverable_abs_gal", abs(error), day)
    tally.add("deliverable_bias_gal", error, day)
    return True, error > 0.0


def _placed(recorded: Sequence[datetime], predicted: Sequence[datetime]) -> int:
    """How many ``recorded`` starts a ``predicted`` one places, within
    ``START_MATCH``, each prediction placing one at most: the most such
    pairs. In time order, each start takes the earliest free prediction
    near enough; one too early for it is too early for every later
    start."""
    free = sorted(predicted)
    placed = i = 0
    for t in sorted(recorded):
        while i < len(free) and free[i] < t - START_MATCH:
            i += 1
        if i < len(free) and free[i] <= t + START_MATCH:
            placed += 1
            i += 1
    return placed


def _hours(result: Any, start: datetime, n: int) -> list[float]:
    """A walk's electricity in each ``DAY_SLOT`` from ``start``, Wh:
    read on the clock's ``DAY_GRID``, which a local midnight is on in
    every zone (each is offset by whole quarter hours), and laid out
    from ``start`` as the meter's slots are."""
    out = [0.0] * n
    for at, wh in result.energy_by_slot(DAY_GRID):
        k = math.floor((at - start) / DAY_SLOT)
        if 0 <= k < n and wh is not None:
            out[k] += wh
    return out


def _hold_left(e: Day, params: HeaterParams) -> float:
    """What is left at the day's start of the hold of a compressor
    start before it, minutes (``start_hold_min``, by its time off)."""
    since = e.compressor_on_since
    if since is None or not e.scenario.state.compressor_running:
        return 0.0
    stopped = e.scenario.history.compressor_stopped_at
    off = None if stopped is None else (since - stopped).total_seconds() / 60.0
    ran = (e.start - since).total_seconds() / 60.0
    return max(0.0, start_hold_min(params.compressor, off) - ran)


def _day_score(
    e: Day,
    params: HeaterParams,
    inlet_f: float | None,
    tally: _Tally,
    day: int,
    record: tf.TankRecord | None = None,
    line_f: float = LINE_F,
) -> float | None:
    """The day predicted from its start and scored; its predicted
    electricity, Wh, or None when the simulator could not answer."""
    s = e.scenario
    state = _state(
        params,
        record,
        e.start,
        s.state.upper_f,
        s.state.lower_f,
        compressor_running=s.state.compressor_running,
        element_running=s.state.element_running,
        element_running_since=s.state.element_running_since,
    )
    try:
        result = sim.simulate(
            s.model_copy(
                update={
                    "state": state,
                    "environment": s.environment.model_copy(
                        update={"inlet_f": inlet_f}
                    ),
                    "loads": _loads(
                        record, e.start, e.end, s.loads.draws, params
                    ),
                }
            ),
            params,
            tou_windows_in_force=e.windows,
            running_hold=_hold_left(e, params),
        )
    except SimulationError, ValueError:
        return None
    wh = result.input_wh
    end = result.end_state
    if wh is None or end is None:
        return None
    if e.metered_wh > 0.0:
        tally.add(
            "day_energy_abs_pct",
            100.0 * abs(wh - e.metered_wh) / e.metered_wh,
            day,
        )
        tally.add(
            "day_energy_bias_pct",
            100.0 * (wh - e.metered_wh) / e.metered_wh,
            day,
        )
    # When in the day it was used, whatever the day's total: half the
    # summed difference of each slot's share of its own day's energy.
    predicted = _hours(result, e.start, len(e.slots_wh))
    if wh > 0.0 and e.metered_wh > 0.0:
        tally.add(
            "day_energy_misplaced_share",
            0.5
            * sum(
                abs(p / wh - m / e.metered_wh)
                for p, m in zip(predicted, e.slots_wh, strict=True)
            ),
            day,
        )
    starts = {
        source: [
            h.start.at
            for h in result.heating
            # One running at the day's start is not a start; one the
            # walk makes at its first instant is.
            if h.source == source
            and h.start.cause != "running"
            and h.start.at < e.end
        ]
        for source in ("compressor", "element")
    }
    got = starts["compressor"]
    tally.add(
        "day_compressor_starts_bias",
        float(len(got) - len(e.compressor_starts)),
        day,
    )
    placed = _placed(e.compressor_starts, got)
    if e.compressor_starts:
        tally.add(
            "day_compressor_starts_placed_share",
            placed / len(e.compressor_starts),
            day,
        )
    tally.add("day_compressor_starts_false", float(len(got) - placed), day)
    tally.add(
        "day_compressor_starts_missed",
        float(len(e.compressor_starts) - placed),
        day,
    )
    tally.add(
        "day_element_starts_bias",
        float(len(starts["element"]) - len(e.element_starts)),
        day,
    )
    low = min(p.upper_f for p in result.points)
    tally.add("day_min_upper_abs_f", abs(low - e.min_upper_f), day)
    tally.add("day_min_upper_bias_f", low - e.min_upper_f, day)
    tally.add(
        "day_line_disagree_share",
        float((low < line_f) != (e.min_upper_f < line_f)),
        day,
    )
    tally.add(
        "day_end_mean_abs_f",
        abs(
            (end.upper_f + end.lower_f) / 2.0
            - (e.end_upper_f + e.end_lower_f) / 2.0
        ),
        day,
    )
    return wh


def _concordance(
    predicted: Sequence[float] | np.ndarray,
    metered: Sequence[float] | np.ndarray,
) -> float:
    """The share of pairs of days the prediction orders as the meter
    does (more electricity or less); a pair the meter ties, a day and
    itself among them, is left out. NaN with no such pair."""
    p = np.asarray(predicted, dtype=float)
    m = np.asarray(metered, dtype=float)
    dm = m[:, None] - m[None, :]
    upper = np.triu(np.ones_like(dm, dtype=bool), k=1) & (dm != 0.0)
    total = int(upper.sum())
    if not total:
        return math.nan
    agree = ((p[:, None] - p[None, :]) * dm > 0.0) & upper
    return float(agree.sum()) / total


def _concordance_stat(
    predicted: Sequence[float], metered: Sequence[float]
) -> Stat:
    """``_concordance`` over the days, and its 90 % interval from a
    bootstrap of them, the pairs drawn afresh in each: a day is in as
    many pairs as there are other days, so its pairs are not apart."""
    p = np.asarray(predicted, dtype=float)
    m = np.asarray(metered, dtype=float)
    rng = np.random.default_rng(SEED)
    boot = [
        _concordance(p[pick], m[pick])
        for pick in (rng.integers(0, len(p), len(p)) for _ in range(N_BOOT))
    ]
    finite = [b for b in boot if math.isfinite(b)]
    value = _concordance(p, m)
    return Stat(
        n=len(p),
        value=value,
        lo=float(np.quantile(finite, 0.05)) if finite else math.nan,
        hi=float(np.quantile(finite, 0.95)) if finite else math.nan,
    )


# ── the score ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Stat:
    """A metric over its events: their mean (``day_energy_concordance``:
    its share of pairs of days) and its 90 % interval from a bootstrap
    of local days."""

    n: int
    value: float
    lo: float
    hi: float

    def document(self) -> dict[str, float | int]:
        return {"n": self.n, "value": self.value, "lo": self.lo, "hi": self.hi}


def _stat(values: Sequence[float], days: Sequence[int]) -> Stat:
    x = np.asarray(values, dtype=float)
    d = np.asarray(days)
    unique = np.unique(d)
    rng = np.random.default_rng(SEED)
    groups = [x[d == k] for k in unique]
    boot = [
        float(np.mean(np.concatenate([groups[i] for i in pick])))
        for pick in (
            rng.integers(0, len(groups), len(groups)) for _ in range(N_BOOT)
        )
    ]
    return Stat(
        n=len(x),
        value=float(np.mean(x)),
        lo=float(np.quantile(boot, 0.05)),
        hi=float(np.quantile(boot, 0.95)),
    )


@dataclass(frozen=True)
class Score:
    """``params`` scored on ``events``."""

    events: dict[str, list[str]]
    metrics: dict[str, Stat]
    #: Events the simulator could not answer, by kind.
    failed: dict[str, int]
    #: Each of them, as ``events`` names it.
    failed_events: dict[str, list[str]]
    #: Physics broken along the predictions, by law: ``below_air``.
    breaks: dict[str, int]
    #: Crossing deliveries whose prediction promised more than was
    #: delivered.
    over_promised: int
    params_sha256: str

    def document(self) -> dict[str, Any]:
        """The score as plain JSON values (``SCHEMA``)."""
        return {
            "schema": SCHEMA,
            "params_sha256": self.params_sha256,
            "events": self.events,
            "failed": self.failed,
            "failed_events": self.failed_events,
            "breaks": self.breaks,
            "over_promised": self.over_promised,
            "metrics": {k: v.document() for k, v in self.metrics.items()},
        }


def params_digest(params: HeaterParams) -> str:
    """A digest of ``params``' document, naming the set a score is of."""
    text = json.dumps(params_to_document(params), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def score(
    found: Events,
    params: HeaterParams,
    *,
    inlet_f: float | None = None,
    tz: str = "UTC",
    record: tf.TankRecord | None = None,
) -> Score:
    """``params`` scored on ``found``: each event predicted by the
    public simulator, its error against the record, and each metric
    over its events (``Stat``, days in ``tz``). ``inlet_f`` is the mains
    the draws meet; None, the parameters'. With the ``record``
    (``tank_fit.tank_record``), each event starts from the layers its
    replay leaves (``HeaterState.layers_f``), every draw before its
    start replayed and a delivery's own left out; with none, from the
    two probes.

    The metrics, lower is better unless a bias:

    - ``recovery_minutes_abs`` and ``_bias`` (``.all``, ``.draw_free``,
      ``.with_draws``): the recovery's predicted run against its
      recorded one, minutes;
    - ``recovery_energy_abs_pct`` and ``_bias_pct``: its electricity
      against the meter's, draw-free recoveries;
    - ``standby_upper_rmse_f``, ``standby_lower_rmse_f``: each probe
      over a quiet window; ``standby_fall_abs_f_h``: the probes' mean
      at the window's end, per hour of it; ``standby_gap_sq_f2``: the
      gap at its end, squared;
    - ``draw_upper_rmse_f``, ``draw_lower_rmse_f``: each probe over the
      hour after a draw;
    - ``deliverable_abs_gal`` and ``_bias_gal``: the gallons promised
      at a delivery's start against those it delivered before the top
      crossed the line; ``deliverable_short_gal``: for one that never
      crossed, how far the promise fell under what it delivered, and
      ``deliverable_under_share`` how often it did;
    - with ``days`` (``day_events``), each day walked whole from its
      start: ``day_energy_abs_pct`` and ``_bias_pct``, its electricity
      against the meter's; ``day_energy_misplaced_share``, the share of
      its electricity predicted in another ``DAY_SLOT`` than the meter
      put it in (0 to 1, whatever the total); ``day_energy_concordance``
      (higher is better), the share of pairs of days it orders, more
      electricity or less, as the meter does (its interval from pairs
      drawn afresh in each resample of days);
      ``day_compressor_starts_bias``, the predicted starts less the
      recorded, ``_placed_share`` the share of a day's recorded starts
      a prediction places within ``START_MATCH`` (days with none left
      out), ``_missed`` the recorded starts no prediction places and
      ``_false`` the predicted starts that place none, each a day;
      ``day_element_starts_bias``; ``day_min_upper_abs_f`` and
      ``_bias_f``, the upper probe's lowest over the day;
      ``day_line_disagree_share``, how often the prediction and the
      record disagree on whether it fell below the line; and
      ``day_end_mean_abs_f``, the probes' mean at the day's end.
    """
    zone = ZoneInfo(tz)
    tally = _Tally()
    failed: dict[str, list[str]] = {
        "recoveries": [],
        "windows": [],
        "draws": [],
        "deliveries": [],
    }
    if found.days:
        failed["days"] = []
    breaks = {"below_air": 0}
    over = 0
    for r in found.recoveries:
        if not _recovery_score(
            r, params, inlet_f, tally, _day(r.start, zone), record
        ):
            failed["recoveries"].append(_iso(r.start))
    for w in found.windows:
        if not _window_score(
            w, params, inlet_f, tally, _day(w.start, zone), breaks, record
        ):
            failed["windows"].append(_iso(w.start))
    for d in found.draws:
        if not _draw_score(d, params, inlet_f, tally, _day(d.at, zone), record):
            failed["draws"].append(_iso(d.at))
    for c in found.deliveries:
        done, promised = _delivery_score(
            c, params, inlet_f, tally, _day(c.at, zone), record
        )
        if not done:
            failed["deliveries"].append(_iso(c.at))
        over += promised
    scored: list[tuple[Day, float]] = []
    for e in found.days:
        wh = _day_score(e, params, inlet_f, tally, _day(e.start, zone), record)
        if wh is None:
            failed["days"].append(_iso(e.start))
        else:
            scored.append((e, wh))
    metrics = {
        name: _stat(values, tally.days[name])
        for name, values in sorted(tally.values.items())
    }
    concordance = _concordance_stat(
        [wh for _, wh in scored], [e.metered_wh for e, _ in scored]
    )
    # Left out, as a metric with no events is, when no pair says.
    if math.isfinite(concordance.value):
        metrics["day_energy_concordance"] = concordance
        metrics = dict(sorted(metrics.items()))
    return Score(
        events=found.keys(),
        metrics=metrics,
        failed={k: len(v) for k, v in failed.items()},
        failed_events=failed,
        breaks=breaks,
        over_promised=over,
        params_sha256=params_digest(params),
    )


# ── the stratified tank ───────────────────────────────────────────


def layer_coasts(found: Events) -> tuple[list[tf.Coast], list[tf.Coast]]:
    """``found``'s quiet windows and draws as the stratified tank's
    events (``sim.tank_fit.Coast``)."""
    windows = [
        tf.Coast(e.start, e.end, e.upper_f, e.lower_f, e.air, e.observed)
        for e in found.windows
    ]
    draws = [
        tf.Coast(
            e.at,
            e.observed[-1][0],
            e.upper_f,
            e.lower_f,
            e.air,
            e.observed,
            ((e.at, e.gallons),),
        )
        for e in found.draws
    ]
    return windows, draws


#: How often a recovery's probes are compared, as the stratified
#: tank's event (``layer_recoveries``).
RECOVERY_EVERY = timedelta(minutes=5)


def layer_recoveries(
    found: Events, params: HeaterParams, record: tf.TankRecord
) -> list[tf.Coast]:
    """``found``'s recoveries as the stratified tank's events: the
    compressor from its start, holding by its time off
    (``start_hold_min``), to its stop, the circulation the ``record``
    has through it, and the probes it recorded every
    ``RECOVERY_EVERY``."""
    out: list[tf.Coast] = []
    for e in found.recoveries:
        off = (
            None
            if e.stopped_at is None
            else (e.start - e.stopped_at).total_seconds() / 60.0
        )
        hold = timedelta(minutes=start_hold_min(params.compressor, off))
        observed: list[tf.Observed] = []
        t = e.start + RECOVERY_EVERY
        while t <= e.end:
            m = record.minute(t)
            if 0 <= m < len(record):
                u, lo = float(record.upper_f[m]), float(record.lower_f[m])
                if math.isfinite(u) and math.isfinite(lo):
                    observed.append((t, u, lo))
            t += RECOVERY_EVERY
        if not observed:
            continue
        out.append(
            tf.Coast(
                e.start,
                e.end,
                e.upper_f,
                e.lower_f,
                e.air,
                tuple(observed),
                e.draws,
                compressor=(e.start, e.start + hold, e.end),
                flowing=tuple(tf.flows(params, record, e.start, e.end)),
            )
        )
    return out


def _layer_errors(
    params: HeaterParams, record: tf.TankRecord | None, coast: tf.Coast
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    try:
        return tf.errors(params, record, coast)
    except ValueError:
        return None


def score_layers(
    found: Events,
    params: HeaterParams,
    record: tf.TankRecord | None,
    *,
    tz: str = "UTC",
    map_: Callable[..., Iterable[Any]] = map,
) -> Score:
    """The stratified tank ``params`` describe scored on ``found``'s
    quiet windows and draws (``score``'s metrics of them), each started
    from the ``record``'s replay (``sim.tank_fit.start_state``).
    ``map_(function, a, b, c)`` maps over the events."""
    zone = ZoneInfo(tz)
    tally = _Tally()
    windows, draws = layer_coasts(found)
    failed: dict[str, list[str]] = {"windows": [], "draws": []}
    breaks = {"below_air": 0}
    for kind, coasts in (("windows", windows), ("draws", draws)):
        n = len(coasts)
        parts = [
            None if record is None else record.before(c.start) for c in coasts
        ]
        got = map_(_layer_errors, [params] * n, parts, coasts)
        for c, e in zip(coasts, got, strict=True):
            if e is None:
                failed[kind].append(_iso(c.start))
                continue
            du, dl = e
            day = _day(c.start, zone)
            name = "standby" if kind == "windows" else "draw"
            tally.add(f"{name}_upper_rmse_f", tf.rmse(du), day)
            tally.add(f"{name}_lower_rmse_f", tf.rmse(dl), day)
            if kind == "draws":
                continue
            hours = (c.end - c.start).total_seconds() / 3600.0
            tally.add(
                "standby_fall_abs_f_h", abs(du[-1] + dl[-1]) / 2.0 / hours, day
            )
            tally.add("standby_gap_sq_f2", (du[-1] - dl[-1]) ** 2, day)
            coldest = min(v for _, v in c.air)
            if min(c.upper_f, c.lower_f) >= max(v for _, v in c.air) and any(
                min(u + a, lo + b) < coldest - BELOW_AIR_F
                for (_, u, lo), a, b in zip(c.observed, du, dl, strict=True)
            ):
                breaks["below_air"] += 1
    return Score(
        events={
            "windows": [_iso(e.start) for e in found.windows],
            "draws": [_iso(e.at) for e in found.draws],
        },
        metrics={
            name: _stat(values, tally.days[name])
            for name, values in sorted(tally.values.items())
        },
        failed={k: len(v) for k, v in failed.items()},
        failed_events=failed,
        breaks=breaks,
        over_promised=0,
        params_sha256=params_digest(params),
    )


def fit_layers(
    found: Events,
    params: HeaterParams,
    record: tf.TankRecord | None,
    *,
    map_: Callable[..., Iterable[Any]] = map,
    max_evaluations: int = 300,
) -> tf.TankFit:
    """The stratified tank's terms fitted from ``params``' values
    (``sim.tank_fit.fit``) on ``found``'s quiet windows and draws, and
    with a ``record``, on its recoveries too, where the condenser heats
    (``CONDENSER_TERMS``) fitted with the rest: the condenser places
    the heat the replay starts each window from, so fitted apart, the
    span that times the recoveries leaves the windows' bottom wrong."""
    windows, draws = layer_coasts(found)
    climbs = [] if record is None else layer_recoveries(found, params, record)
    return tf.fit(
        params,
        record,
        windows + draws + climbs,
        terms=tf.TERMS + tf.CONDENSER_TERMS if climbs else tf.TERMS,
        map_=map_,
        max_evaluations=max_evaluations,
    )


# ── comparing two scores ──────────────────────────────────────────


@dataclass(frozen=True)
class Change:
    """One metric in two scores: its values, and whether the second's
    interval clears the first's value either way."""

    metric: str
    before: float | None
    after: float | None
    #: ``after - before``; None when either is missing.
    delta: float | None
    #: The second's interval lies wholly above or below the first's
    #: value.
    clear: bool


@dataclass(frozen=True)
class Comparison:
    """Two score documents side by side."""

    #: Whether both were scored on the same events, and the simulator
    #: answered the same of them: otherwise their metrics answer
    #: different questions.
    same_events: bool
    changes: tuple[Change, ...]


def _failures(doc: Mapping[str, Any], kinds: set[str]) -> dict[str, list[str]]:
    """A document's unanswered events of ``kinds``, those with any."""
    named = cast(Mapping[str, list[str]], doc.get("failed_events") or {})
    return {k: v for k, v in named.items() if v and k in kinds}


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> Comparison:
    """Two score documents (``Score.document``) compared metric by
    metric, on the kinds of event both carry (``score_layers`` scores
    only the windows and the draws). Raises ``ValueError`` for a
    document of another schema."""
    for doc in (before, after):
        if doc.get("schema") != SCHEMA:
            raise ValueError(f"not a {SCHEMA} document")
    a = cast(Mapping[str, Mapping[str, float]], before["metrics"])
    b = cast(Mapping[str, Mapping[str, float]], after["metrics"])
    rows: list[Change] = []
    for name in sorted({*a, *b}):
        x = a.get(name)
        y = b.get(name)
        xv = None if x is None else float(x["value"])
        yv = None if y is None else float(y["value"])
        clear = (
            xv is not None
            and y is not None
            and (float(y["lo"]) > xv or float(y["hi"]) < xv)
        )
        rows.append(
            Change(
                name,
                xv,
                yv,
                None if xv is None or yv is None else yv - xv,
                clear,
            )
        )
    ea = cast(Mapping[str, list[str]], before.get("events") or {})
    eb = cast(Mapping[str, list[str]], after.get("events") or {})
    kinds = set(ea) & set(eb)
    return Comparison(
        same_events=all(ea[k] == eb[k] for k in kinds)
        and _failures(before, kinds) == _failures(after, kinds),
        changes=tuple(rows),
    )
