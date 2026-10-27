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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from nwp500 import sim
from nwp500.sim import calibration as cal
from nwp500.sim import tank_fit as tf
from nwp500.sim.engine import SimulationError
from nwp500.sim.params import HeaterParams, params_to_document
from nwp500.sim.physics.heat_pump import start_hold_min
from nwp500.sim.tank_physics import point_at
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
class Events:
    """The events a history is scored on."""

    recoveries: tuple[Recovery, ...] = ()
    windows: tuple[Window, ...] = ()
    draws: tuple[DrawEvent, ...] = ()
    deliveries: tuple[Delivery, ...] = ()

    def keys(self) -> dict[str, list[str]]:
        """Each kind's events by their instants, as a score document
        carries them."""
        return {
            "recoveries": [_iso(e.start) for e in self.recoveries],
            "windows": [_iso(e.start) for e in self.windows],
            "draws": [_iso(e.at) for e in self.draws],
            "deliveries": [_iso(e.at) for e in self.deliveries],
        }


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


def _recovery_score(
    e: Recovery,
    params: HeaterParams,
    inlet_f: float | None,
    tally: _Tally,
    day: int,
) -> bool:
    """The recovery predicted from its recorded start, with the hold
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
                state=sim.HeaterState(
                    upper_f=e.upper_f,
                    lower_f=e.lower_f,
                    compressor_running=True,
                ),
                settings=sim.Settings(
                    setpoint_f=e.setpoint_f, hp_lower_off_f=e.target_f
                ),
                history=sim.History(compressor_stopped_at=e.stopped_at),
                environment=_environment(e.air, e.humidity, inlet_f),
                loads=sim.Loads(draws=draws),
            ),
            params,
            running_hold=hold,
        )
    except SimulationError, ValueError:
        return False
    first = next((h for h in result.heating if h.source == "compressor"), None)
    # Still running at the horizon: its end, and so its error, unknown.
    if first is None or first.stop == "horizon":
        return False
    minutes = (first.end - first.start.at).total_seconds() / 60.0
    actual = (e.end - e.start).total_seconds() / 60.0
    kind = "draw_free" if e.draw_free else "with_draws"
    for which in ("all", kind):
        tally.add(f"recovery_minutes_abs.{which}", abs(minutes - actual), day)
        tally.add(f"recovery_minutes_bias.{which}", minutes - actual, day)
    if e.draw_free and e.metered_wh and first.input_wh is not None:
        tally.add(
            "recovery_energy_abs_pct",
            100.0 * abs(first.input_wh - e.metered_wh) / e.metered_wh,
            day,
        )
        tally.add(
            "recovery_energy_bias_pct",
            100.0 * (first.input_wh - e.metered_wh) / e.metered_wh,
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
) -> bool:
    try:
        trace = sim.standby(
            sim.HeaterState(upper_f=e.upper_f, lower_f=e.lower_f),
            _environment(e.air, 50.0, inlet_f),
            sim.Loads(),
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
) -> bool:
    try:
        trace = sim.standby(
            sim.HeaterState(upper_f=e.upper_f, lower_f=e.lower_f),
            _environment(e.air, 50.0, inlet_f),
            sim.Loads(draws=(sim.Draw(at=e.at, gallons=e.gallons),)),
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
    e: Delivery, params: HeaterParams, tally: _Tally, day: int
) -> tuple[bool, bool]:
    """Scored, and whether it promised more than a crossing delivered.
    A draw that did not cross delivered at least its gallons: only a
    prediction under them is an error, an under-promise."""
    try:
        got = sim.readiness(
            sim.HeaterState(upper_f=e.upper_f, lower_f=e.lower_f),
            sim.Settings(setpoint_f=e.setpoint_f),
            params,
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


# ── the score ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Stat:
    """A metric over its events: their mean and its 90 % interval from
    a bootstrap of local days."""

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
) -> Score:
    """``params`` scored on ``found``: each event predicted by the
    public simulator, its error against the record, and each metric
    over its events (``Stat``, days in ``tz``). ``inlet_f`` is the mains
    the draws meet; None, the parameters'.

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
      ``deliverable_under_share`` how often it did.
    """
    zone = ZoneInfo(tz)
    tally = _Tally()
    failed: dict[str, list[str]] = {
        "recoveries": [],
        "windows": [],
        "draws": [],
        "deliveries": [],
    }
    breaks = {"below_air": 0}
    over = 0
    for r in found.recoveries:
        if not _recovery_score(r, params, inlet_f, tally, _day(r.start, zone)):
            failed["recoveries"].append(_iso(r.start))
    for w in found.windows:
        if not _window_score(
            w, params, inlet_f, tally, _day(w.start, zone), breaks
        ):
            failed["windows"].append(_iso(w.start))
    for d in found.draws:
        if not _draw_score(d, params, inlet_f, tally, _day(d.at, zone)):
            failed["draws"].append(_iso(d.at))
    for c in found.deliveries:
        done, promised = _delivery_score(c, params, tally, _day(c.at, zone))
        if not done:
            failed["deliveries"].append(_iso(c.at))
        over += promised
    metrics = {
        name: _stat(values, tally.days[name])
        for name, values in sorted(tally.values.items())
    }
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
    max_evaluations: int = 200,
) -> tf.TankFit:
    """The stratified tank's terms fitted from ``params``' values
    (``sim.tank_fit.fit``): ``TERMS`` on ``found``'s quiet windows and
    draws, then, with a ``record``, where the condenser heats
    (``CONDENSER_TERMS``) on its recoveries. Its terms are both
    blocks', its RMSE the first's."""
    windows, draws = layer_coasts(found)
    done = tf.fit(
        params,
        record,
        windows + draws,
        map_=map_,
        max_evaluations=max_evaluations,
    )
    climbs = (
        [] if record is None else layer_recoveries(found, done.params, record)
    )
    if not climbs:
        return done
    heats = tf.fit(
        done.params,
        record,
        climbs,
        terms=tf.CONDENSER_TERMS,
        map_=map_,
        max_evaluations=max_evaluations,
    )
    return replace(
        done,
        params=heats.params,
        terms={**done.terms, **heats.terms},
        on_bound=done.on_bound + heats.on_bound,
        evaluations=done.evaluations + heats.evaluations,
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
