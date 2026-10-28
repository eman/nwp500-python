"""Fitting a heater's own parameters from its history.

``default_params`` are one NWP500-65's, fitted at one installation. This
fits the parts a heater's own telemetry can: what any owner can record
with this library (the probes, what is heating, its own flags), plus the
air where the heater stands (``sim.location_air``), and, where an owner
has them, a meter's draws and the circulation's runs. No I/O: the caller
records the history and hands it in.

**The history** is a ``pandas.DataFrame`` indexed by UTC instants, sorted,
at whatever rate the samples came (``sim_adapters.history`` builds one
from ``DeviceStatus`` readings). Each state holds until the next sample.
Its columns, °F where a temperature:

- ``upper_f``, ``lower_f``: the probes;
- ``compressor_on``, ``element_on``: what is heating (an element by
  either element's flag or the reported heat source);
- ``dhw_in_use``: the heater's own "hot water in use" flag, the quiet
  test without a meter (it fires on circulation, too);
- ``target_f``: the lower probe's compressor stop threshold
  (``hp_lower_off_temp_setting``), what a recovery heats to;
- ``excluded``: a sample no heat-pump recovery may span (a hybrid
  mode, an anti-legionella cycle, an error);
- ``power_w``: what the heater draws (``current_inst_power``), each
  report held until the next, for the power map;
- ``energy_to_setpoint_wh``: the heater's own deficit to its setpoint
  (``DeviceStatus.energy_to_setpoint``), to tell a recovery cut short
  from one that finished;
- ``heater_air_f``: the heater's own air reading while its compressor
  runs, NaN otherwise (``sim_adapters.location_air_reading``);
- ``heater_cabinet_f``: the same reading while the compressor is idle,
  the cabinet's, NaN otherwise;
- ``air_f``: the air where the heater stands throughout, for the
  tank's losses: a sensor's, or ``location_air``'s projection;
- optionally ``humidity_pct`` (the air's) and ``drawing``,
  ``circulating`` (a meter's draws and the circulation's runs,
  ``sim.circulation``; with them, the quiet test needs no
  ``dhw_in_use``).

Each fit reports what it saw and what it left out
(``heat_pump_fit.HeatPumpFit``), and only replaces the base parameters'
values when it had the evidence to.
"""

import bisect
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.optimize import (
    OptimizeResult,
    minimize,
    minimize_scalar,
)

from nwp500.sim import history_frame as hf
from nwp500.sim.circulation import RUN_GAP, cooled_share, merge_runs
from nwp500.sim.circulation import displaced_gal as circulation_displaced_gal
from nwp500.sim.history_frame import Interval
from nwp500.sim.inputs import ELECTRIC, ENERGY_SAVER, HIGH_DEMAND
from nwp500.sim.params import (
    UNFITTED_TERMS,
    HeaterParams,
)
from nwp500.sim.record import Record
from nwp500.sim.units import WATER_BTU_PER_GAL_F

if TYPE_CHECKING:
    from nwp500.sim.heat_pump_fit import HeatPumpFit

# ── quiet windows ───────────────────────────────────────────────────

#: How long after heating, a draw or a circulation run the tank is still
#: settling and is not fitted. At one installation, 0 -> 45 min took the
#: fitted UA's spread from 5.63 ± 3.32 to 4.88 ± 1.15 over 24 windows;
#: over February to October 2026, ``ua_ref`` was 4.44-4.48 at 30, 45, 60
#: and 90 min (``docs/explanation/standby-loss.rst``).
SETTLE_MINUTES = 45.0
#: The shortest quiet window fitted, hours.
MIN_QUIET_HOURS = 3.0


def busy_intervals(
    history: pd.DataFrame, settle_minutes: float = SETTLE_MINUTES
) -> list[Interval]:
    """The spans the tank is not quiet: heating (``compressor_on``,
    ``element_on``), water moving (``drawing``, ``circulating`` where
    recorded, else ``dhw_in_use``, which fires on both), each extended
    forward by ``settle_minutes`` while the tank settles. Merged,
    sorted. One recorded and not the other: the heater's flag stands in
    for the other. Where a caller marks ``air_unobserved`` (no reading
    of the air), the tank is not quiet either: a fit there would stand
    on air nobody read."""
    when = hf.instants(history)
    columns = ["compressor_on", "element_on"]
    if "air_unobserved" in history.columns:
        columns.append("air_unobserved")
    tier1 = [c for c in ("drawing", "circulating") if c in history.columns]
    columns += tier1
    if len(tier1) < 2 and "dhw_in_use" in history.columns:
        columns.append("dhw_in_use")
    settle = timedelta(minutes=settle_minutes)
    spans: list[Interval] = []
    for column in columns:
        on = history[column].fillna(False).astype(bool).to_numpy()
        spans += [(a, b + settle) for a, b in hf.on_intervals(when, on)]
    return hf.merge(spans)


def quiet_windows(
    history: pd.DataFrame,
    min_hours: float = MIN_QUIET_HOURS,
    settle_minutes: float = SETTLE_MINUTES,
) -> list[Interval]:
    """The complement of ``busy_intervals`` within the history, keeping
    the windows of at least ``min_hours``."""
    if history.empty:
        return []
    when = hf.instants(history)
    since, until = when[0], when[-1]
    gap = timedelta(hours=min_hours)
    out: list[Interval] = []
    cursor = since
    for start, end in busy_intervals(history, settle_minutes):
        if start - cursor >= gap:
            out.append((cursor, start))
        cursor = max(cursor, end)
    if until - cursor >= gap:
        out.append((cursor, until))
    return out


# ── holding out the latest ───────────────────────────────────────

#: With this many of a fit's items, the latest ``HELDOUT_FRACTION`` (at
#: least ``MIN_HELDOUT``) are held out to judge it
#: (``sim_calibrate.keep_better``).
MIN_RECOVERIES_FOR_SPLIT = 10
HELDOUT_FRACTION = 0.20
MIN_HELDOUT = 2


# ── the heat pump's recoveries ───────────────────────────────────────

#: How far before a compressor start a disqualifying state still counts:
#: a mode change is reported seconds before the compressor.
PRE_RECOVERY_LOOKBACK = timedelta(minutes=10)
#: The lower probe has reached its target within this, °F.
REACHED_TOLERANCE_F = 0.05
#: A recovery ending with more than this still to heat was cut short,
#: Wh, read from 2 minutes before its end to 1 after.
INTERRUPTED_WH = 500.0
INTERRUPTED_WINDOW = (timedelta(minutes=-2), timedelta(minutes=1))
#: The rates a recovery may imply, minutes per °F of the lower zone's
#: rise: faster than the heat pump can heat is a mislabelled cycle,
#: slower an undetected interruption; and an absolute backstop, minutes.
#: At one installation (February to October 2026) the kept ran 3.8-18.7;
#: the upper bound dropped 12, each a rise of 0.2-6.3 °F near the
#: setpoint, and fitting with them moved the compressor constant 0.2 %
#: and the held-out error 0.1 min.
MIN_MINUTES_PER_F = 2.0
MAX_MINUTES_PER_F = 20.0
MAX_RECOVERY_LABEL_MINUTES = 600.0
#: A recovery is read every ``SNAPSHOT_EVERY`` while at least
#: ``SNAPSHOT_MIN_REMAINING`` of it remains, and fitted from the reading
#: with the coldest lower probe, timed from there.
SNAPSHOT_EVERY = timedelta(minutes=30)
SNAPSHOT_MIN_REMAINING = timedelta(minutes=15)


def _snapshots(start: datetime, end: datetime) -> list[datetime]:
    """Where a recovery is read from: its start, then every
    ``SNAPSHOT_EVERY`` while at least ``SNAPSHOT_MIN_REMAINING`` of it
    remains (none for a shorter one)."""
    out: list[datetime] = []
    offset = timedelta(0)
    while end - (start + offset) >= SNAPSHOT_MIN_REMAINING:
        out.append(start + offset)
        offset += SNAPSHOT_EVERY
    return out


#: A cycle is draw-free only with no water in use from this long before
#: it to its end.
DRAW_LEAD = timedelta(minutes=30)

_SNAPSHOT_COLUMNS = (
    "cycle",
    "offset_minutes",
    "start_time",
    "end_time",
    "duration_minutes",
    "t_start_lower",
    "t_start_upper",
    "stratification_gap",
    "delta_t_lower",
    "t_amb_mean",
    "h_amb_start",
    "reached",
    "metered_input_wh",
    "t_lower_end",
    "t_upper_end",
    "draw_free",
    "draw_gal",
    "draw_t_upper",
    "circulation_runs",
)

#: Circulation runs closer than this in a cycle are one run, as the
#: circulation's displaced volume was fitted (``circulation.RUN_GAP``).
_RUN_GAP = timedelta(minutes=10)


#: A recovery's lower-zone target when the history records no stop
#: threshold (``target_f``), °F.
UNRECORDED_TARGET_F = 140.0


def _in_cycle(
    draws: Sequence[tuple[datetime, float]] | None,
    circulation: Sequence[tuple[datetime, datetime]] | None,
    upper: np.ndarray,
    seconds: np.ndarray,
    at: datetime,
    end: datetime,
) -> dict[str, object]:
    """A snapshot's metered draws and circulation runs: the delivered
    gallons from ``at`` to ``end`` and the volume-weighted upper zone
    they left at, and each run over the span (merged within
    ``_RUN_GAP``) as ``(minutes in the span, the upper zone where the
    span takes it up, hours since the run before it ended, minutes it had
    run before the span)``, the hours None for the first run given. None
    for what was not given: an unrecorded meter or circulation is not an
    idle one."""
    out: dict[str, object] = {
        "draw_gal": None,
        "draw_t_upper": None,
        "circulation_runs": None,
    }

    def upper_at(t: datetime) -> float | None:
        return hf.asof(upper, seconds, t)

    if draws is not None:
        window = [(t, g) for t, g in draws if at <= t <= end]
        gal = float(sum(g for _, g in window))
        out["draw_gal"] = gal
        if gal > 0.0:
            weighted = [(upper_at(t), g) for t, g in window]
            out["draw_t_upper"] = (
                sum(u * g for u, g in weighted if u is not None) / gal
            )
    if circulation is not None:
        merged = merge_runs(circulation, _RUN_GAP)
        found: list[tuple[float, float, float | None, float]] = []
        for i, (a0, b0) in enumerate(merged):
            a, b = max(a0, at), min(b0, end)
            if b <= a or (u := upper_at(a)) is None:
                continue
            rest = (
                (a0 - merged[i - 1][1]).total_seconds() / 3600.0 if i else None
            )
            found.append(
                (
                    (b - a).total_seconds() / 60.0,
                    u,
                    rest,
                    (a - a0).total_seconds() / 60.0,
                )
            )
        out["circulation_runs"] = tuple(found)
    return out


@dataclass(frozen=True)
class HeatPumpCycle:
    """A compressor run a heat-pump recovery may be read from
    (``heat_pump_cycles``): the ``n``-th run in the history, ``[start,
    end)``; the lower probe's stop threshold in force at its start;
    whether the lower probe reached it; whether no water was in use from
    ``DRAW_LEAD`` before it to its end; and when the run before it
    stopped (None for the history's first)."""

    n: int
    start: datetime
    end: datetime
    target_f: float
    reached: bool
    draw_free: bool
    stopped_at: datetime | None


def water_in_use(history: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    """The water-moving columns read (a meter's and the circulation's,
    else the heater's own flag) and the samples any of them is on."""
    tier1 = [c for c in ("drawing", "circulating") if c in history.columns]
    water = np.zeros(len(history), dtype=bool)
    for column in tier1 or ["dhw_in_use"]:
        if column in history.columns:
            water |= history[column].fillna(False).astype(bool).to_numpy()
    return tier1, water


def water_over(
    index: pd.DatetimeIndex,
    water: np.ndarray,
    tier1: Sequence[str],
    start: datetime,
    end: datetime,
) -> bool:
    """Whether water was in use from ``start`` to ``end``
    (``water_in_use``'s columns and samples). A meter's or the
    circulation's flag marks a sample's interval, to the next sample
    (``sim_adapters.history``): the sample at ``end`` is the interval
    after, and the one before the first inside can hold water moving
    inside it. The heater's own flag is read at its instants."""
    inside = (index >= start) & ((index < end) if tier1 else (index <= end))
    if water[inside].any():
        return True
    first = int(np.argmax(inside)) if inside.any() else len(inside)
    return (
        bool(tier1)
        and 0 < first < len(inside)
        and bool(index[first] > start)
        and bool(water[first - 1])
    )


def heat_pump_cycles(history: pd.DataFrame) -> list[HeatPumpCycle]:
    """The history's compressor runs with no element, no hybrid mode, no
    anti-legionella cycle and no error from ``PRE_RECOVERY_LOOKBACK``
    before them to their end, not cut short (``INTERRUPTED_WH``), and
    with a sample inside them, and seen from start to stop (a run on at
    the history's first sample or still on at its last is not): the
    recoveries ``snapshots`` reads and ``sim.heat_pump_fit`` measures. A
    run's target is the stop threshold (``target_f``) in force at its
    start, else ``UNRECORDED_TARGET_F``. Its ``stopped_at`` is None when
    the heater went unrecorded since the run before it
    (``unrecorded``, ``heater_unobserved``): a run may have gone
    unseen."""
    if history.empty:
        return []
    when = hf.instants(history)
    index = pd.DatetimeIndex(history.index)
    seconds = np.array([t.timestamp() for t in when])
    lower_f = hf.floats(history, "lower_f")
    target_f = hf.floats(history, "target_f")
    energy_wh = hf.floats(history, "energy_to_setpoint_wh")
    on = history["compressor_on"].fillna(False).astype(bool).to_numpy()
    element = history["element_on"].fillna(False).astype(bool).to_numpy()
    excluded = (
        history["excluded"].fillna(False).astype(bool).to_numpy()
        if "excluded" in history.columns
        else np.zeros(len(history), dtype=bool)
    )
    tier1, water = water_in_use(history)
    unseen = np.zeros(len(history), dtype=bool)
    for name in ("unrecorded", "heater_unobserved"):
        if name in history.columns:
            unseen |= history[name].fillna(False).astype(bool).to_numpy()
    runs = hf.on_intervals(when, on)
    out: list[HeatPumpCycle] = []
    for n, (start, end) in enumerate(runs):
        # Not seen to start, or to stop.
        if (on[0] and start == when[0]) or (on[-1] and end == when[-1]):
            continue
        span = (index >= start - PRE_RECOVERY_LOOKBACK) & (index <= end)
        if element[span].any() or excluded[span].any():
            continue
        target = hf.asof(target_f, seconds, start)
        if target is None:
            # The stop threshold not recorded: the device's usual one, as
            # the model's fit took it.
            target = UNRECORDED_TARGET_F
        before, after = INTERRUPTED_WINDOW
        at_end = energy_wh[(index >= end + before) & (index <= end + after)]
        at_end = at_end[np.isfinite(at_end)]
        if len(at_end) and at_end[-1] > INTERRUPTED_WH:
            continue
        inside = (index >= start) & (index <= end)
        reached = bool(np.any(lower_f[inside] >= target - REACHED_TOLERANCE_F))
        if not ((index >= start) & (index < end)).any():
            continue
        draw_free = not water_over(index, water, tier1, start - DRAW_LEAD, end)
        stopped_at = runs[n - 1][1] if n else None
        if (
            stopped_at is not None
            and unseen[(index >= stopped_at) & (index <= start)].any()
        ):
            stopped_at = None
        out.append(
            HeatPumpCycle(n, start, end, target, reached, draw_free, stopped_at)
        )
    return out


def snapshots(
    history: pd.DataFrame,
    *,
    air: str = "heater_air_f",
    draws: Sequence[tuple[datetime, float]] | None = None,
    circulation: Sequence[tuple[datetime, datetime]] | None = None,
) -> pd.DataFrame:
    """The history's heat-pump recoveries, each read from snapshots: its
    start, then every ``SNAPSHOT_EVERY`` while ``SNAPSHOT_MIN_REMAINING``
    of it remains. The fits take their rows from here.

    A recovery is each compressor run with no element, no hybrid mode,
    no anti-legionella cycle and no error from ``PRE_RECOVERY_LOOKBACK``
    before it to its end, and not cut short (``INTERRUPTED_WH``). A
    snapshot is kept with a target above its lower probe, a plausible
    rate (``MIN_MINUTES_PER_F`` to ``MAX_MINUTES_PER_F``, at most
    ``MAX_RECOVERY_LABEL_MINUTES``) and the air somewhere in its cycle.

    Each row reads the cycle's own samples, ``[start, end)``: the last
    at or before the snapshot, else the cycle's first. Its columns:
    ``cycle`` and ``offset_minutes``; ``start_time`` (the snapshot's),
    ``end_time``, ``duration_minutes`` (the compressor's run from the
    snapshot); ``t_start_lower``, ``t_start_upper`` and
    ``stratification_gap`` at the snapshot; ``delta_t_lower`` (the target
    in force at the start less the lower probe); ``t_amb_mean`` (the
    ``air`` column's mean from the snapshot to the end, else its reading
    at the snapshot: the heater's own by default, a sensor's with
    ``air="air_f"``); ``h_amb_start`` (NaN without humidity); ``reached``
    (the lower probe came within ``REACHED_TOLERANCE_F`` of the target
    before the run ended); ``metered_input_wh`` (``power_w`` integrated
    from the snapshot to the end, None without it); ``t_lower_end``,
    ``t_upper_end`` (the probes at the end); ``draw_free`` (no water
    in use from ``DRAW_LEAD`` before the start to the end); and, with a
    meter's ``draws`` (``(instant, delivered gallons)``) and
    ``circulation``'s runs, what was drawn and circulated over the
    snapshot (``_in_cycle``).
    """
    if history.empty:
        return pd.DataFrame(columns=list(_SNAPSHOT_COLUMNS))
    when = hf.instants(history)
    index = pd.DatetimeIndex(history.index)
    seconds = np.array([t.timestamp() for t in when])
    lower_f = hf.floats(history, "lower_f")
    upper_f = hf.floats(history, "upper_f")
    air_f = hf.floats(history, air)
    humidity_pct = hf.floats(history, "humidity_pct")
    power_w = hf.floats(history, "power_w")
    rows: list[dict[str, object]] = []
    for c in heat_pump_cycles(history):
        n, start, end, target = c.n, c.start, c.end, c.target_f
        reached, draw_free = c.reached, c.draw_free
        cycle = (index >= start) & (index < end)
        c_seconds, c_air = seconds[cycle], air_f[cycle]
        lower_end = hf.asof(lower_f[cycle], c_seconds, end)
        upper_end = hf.asof(upper_f[cycle], c_seconds, end)
        for at in _snapshots(start, end):
            lower = hf.asof(lower_f[cycle], c_seconds, at)
            upper = hf.asof(upper_f[cycle], c_seconds, at)
            if lower is None or upper is None or target - lower <= 0.0:
                continue
            minutes = (end - at).total_seconds() / 60.0
            if not (
                MIN_MINUTES_PER_F
                <= minutes / (target - lower)
                <= MAX_MINUTES_PER_F
                and minutes <= MAX_RECOVERY_LABEL_MINUTES
            ):
                continue
            # The air from the snapshot to the end, else at the snapshot.
            tail = c_air[c_seconds >= at.timestamp()]
            tail = tail[np.isfinite(tail)]
            air_mean = (
                float(np.mean(tail))
                if len(tail)
                else hf.asof(c_air, c_seconds, at)
            )
            if air_mean is None:
                continue
            humidity = hf.asof(humidity_pct[cycle], c_seconds, at)
            rows.append(
                {
                    "cycle": n,
                    "offset_minutes": (at - start).total_seconds() / 60.0,
                    "start_time": at,
                    "end_time": end,
                    "duration_minutes": minutes,
                    "t_start_lower": lower,
                    "t_start_upper": upper,
                    "stratification_gap": upper - lower,
                    "delta_t_lower": target - lower,
                    "t_amb_mean": air_mean,
                    # Unrecorded humidity is passed on unknown, as the
                    # model's fit read it, not as an assumed 50 %.
                    "h_amb_start": math.nan if humidity is None else humidity,
                    "reached": reached,
                    "metered_input_wh": hf.energy_wh(
                        power_w[cycle], c_seconds, at, end
                    ),
                    "t_lower_end": lower_end,
                    "t_upper_end": upper_end,
                    "draw_free": draw_free,
                    **_in_cycle(
                        draws,
                        circulation,
                        upper_f[cycle],
                        c_seconds,
                        at,
                        end,
                    ),
                }
            )
    return pd.DataFrame(rows, columns=list(_SNAPSHOT_COLUMNS))


def recoveries(
    history: pd.DataFrame, *, air: str = "heater_air_f"
) -> pd.DataFrame:
    """One row per recovery: of a cycle's ``snapshots``, the one with
    the coldest lower probe (the earliest of equals), timed from there.
    A draw that takes the probe below where it started moves the row to
    after the draw; without a dip it is the start. ``reached`` says
    which reached their target: the heater stops some short by
    design."""
    rows = snapshots(history, air=air)
    if rows.empty:
        return rows
    order = rows.sort_values(
        ["cycle", "t_start_lower", "offset_minutes"], kind="stable"
    )
    return order.groupby("cycle", sort=True).head(1).reset_index(drop=True)


@dataclass(frozen=True)
class Calibration:
    """A heater's calibration: the parameters, and the fits behind them."""

    params: HeaterParams
    #: The heat pump's (``heat_pump_fit.fit_heat_pump``).
    heat_pump: HeatPumpFit
    #: The recoveries found, reached or not.
    recoveries: pd.DataFrame = field(repr=False)


def calibrate(
    history: pd.DataFrame,
    base: HeaterParams,
    *,
    recovery_air: str = "heater_air_f",
) -> Calibration:
    """``base``'s heat pump refitted on ``history``: its performance
    map, the hold at its starts and the overshoot at its stops from its
    recoveries (``heat_pump_fit.fit_heat_pump``), the heat priced
    against the loss of the tank ``base`` lays out, the air read from
    ``recovery_air``. The tank's own terms are fitted on the history's
    events (``sim_calibrate``, ``sim.tank_fit``): fit them first.

    What could not be fitted keeps ``base``'s value, the best prior
    there is for the same product, and is named in the result's
    ``HeaterParams.unfitted``, so a failed fit never reads as a fitted
    one: no heat map leaves ``compressor``, no power map ``power``.
    ``base``'s record of every other group is kept."""
    # ``heat_pump_fit`` measures on this module's recoveries.
    from nwp500.sim import heat_pump_fit as hpf

    found = recoveries(history, air=recovery_air)
    hp_fit = hpf.fit_heat_pump(
        hpf.evidence(history, base, air=recovery_air), base.compressor
    )
    params = hpf.with_heat_pump(base, hp_fit)
    unfitted = [t for t in base.unfitted if t not in ("compressor", "power")]
    if hp_fit.heat is None or hp_fit.violations:
        unfitted.append("compressor")
    if hp_fit.power is None or hp_fit.violations:
        unfitted.append("power")
    params = replace(
        params, unfitted=tuple(t for t in UNFITTED_TERMS if t in unfitted)
    )
    return Calibration(params, hp_fit, found)


# ── metered draws, and where the upper probe crossed ───────────────

#: The grid the metered draws are read on, seconds.
DRAW_GRID_S = 5
#: Flow gaps shorter than this are one draw, seconds.
DRAW_JOIN_S = 60
#: A draw is followed this long for the lagging upper probe, which is
#: also how far a crossing is credited back, seconds.
DRAW_TAIL_S = 90
#: No flow, no circulation and no element this long before a draw, or
#: its starting state is still moving, seconds.
DRAW_SETTLE_S = 120
#: The smallest draw kept, delivered gallons.
MIN_DRAW_GAL = 5.0


@dataclass(frozen=True)
class CleanDraw:
    """One metered draw with circulation and both elements off through
    it and a settled start: the tank before it, and the upper probe
    against the gallons delivered (``vd``, cumulative, per grid step)."""

    start: datetime
    u0: float
    l0: float
    gal: float
    #: The median flow while drawing, gal/min.
    gpm: float
    #: The compressor ran through it or the settle before it.
    hp: bool
    u: np.ndarray = field(repr=False)
    vd: np.ndarray = field(repr=False)


def clean_draws(
    frame: pd.DataFrame, *, draw_gpm: float = 0.3
) -> list[CleanDraw]:
    """The clean draws in ``frame``: a ``DRAW_GRID_S`` grid with
    ``flow_gpm`` (the household meter's), ``circulating``, ``upper_f``,
    ``lower_f``, ``compressor_on`` and ``element_on``.

    A draw is a run of steps above ``draw_gpm``, gaps under
    ``DRAW_JOIN_S`` joined; kept with ``MIN_DRAW_GAL`` or more, no
    circulation through it, no element through it or the
    ``DRAW_SETTLE_S`` before it, no flow or circulation in that settle,
    and both probes known. Each is followed ``DRAW_TAIL_S`` for the
    lagging probe, stopping at the next draw and carrying none of its
    flow."""
    if frame.empty:
        return []
    flow = frame["flow_gpm"].to_numpy(dtype=float)
    circ = frame["circulating"].fillna(False).astype(bool).to_numpy()
    up = frame["upper_f"].to_numpy(dtype=float)
    lo = frame["lower_f"].to_numpy(dtype=float)
    comp = frame["compressor_on"].fillna(False).astype(bool).to_numpy()
    elem = frame["element_on"].fillna(False).astype(bool).to_numpy()
    when = hf.instants(frame)
    wet = np.where(flow > draw_gpm)[0]
    if not len(wet):
        return []
    breaks = np.where(np.diff(wet) > DRAW_JOIN_S // DRAW_GRID_S)[0]
    starts = np.r_[wet[0], wet[breaks + 1]]
    ends = np.r_[wet[breaks], wet[-1]]
    settle = DRAW_SETTLE_S // DRAW_GRID_S
    tail = DRAW_TAIL_S // DRAW_GRID_S
    out: list[CleanDraw] = []
    for k, (s, e) in enumerate(zip(starts, ends, strict=True)):
        if s < settle:
            continue
        nxt = starts[k + 1] if k + 1 < len(starts) else len(frame)
        w = slice(s, min(e + 1 + tail, nxt))
        pre = slice(s - settle, s)
        flow_w = flow[w].copy()
        flow_w[e + 1 - s :] = 0.0  # the tail is this draw's, not the next
        gal_step = flow_w * DRAW_GRID_S / 60.0
        if gal_step.sum() < MIN_DRAW_GAL or circ[s : e + 1].any():
            continue
        if elem[w].any() or elem[pre].any() or np.isnan(up[w]).any():
            continue
        if (flow[pre] > draw_gpm).any() or circ[pre].any():
            continue
        body = flow[s : e + 1]
        out.append(
            CleanDraw(
                start=when[s],
                u0=float(up[pre][-1]),
                l0=float(lo[pre][-1]),
                gal=float(gal_step.sum()),
                gpm=float(np.median(body[body > draw_gpm])),
                hp=bool(comp[w].any() or comp[pre].any()),
                u=up[w],
                vd=np.cumsum(gal_step),
            )
        )
    return out


def crossing(d: CleanDraw, below: float) -> tuple[float, bool]:
    """Gallons credited before the upper probe fell to ``below``, and
    whether it did: credited back by the probe's lag
    (``DRAW_TAIL_S``); a draw that never crossed is credited whole."""
    idx = np.where(d.u <= below)[0]
    if not len(idx):
        return d.gal, False
    j = idx[0] - DRAW_TAIL_S // DRAW_GRID_S
    return (float(d.vd[j]) if j >= 0 else 0.0), True


def demonstrated(d: CleanDraw, line_f: float = 105.0) -> float:
    """Delivered gallons credited before the upper probe crossed
    ``line_f`` (strictly below it)."""
    return crossing(d, line_f - 1e-9)[0]


# ── circulation: what each run took, and the volume it displaces ────

#: A reading of the circulation's flow or its return line older than
#: this at a running sample is no reading of it.
RETURN_MAX_AGE = timedelta(minutes=5)
#: Fewer runs than this and no displaced volume is fitted.
MIN_RUNS_TO_FIT = 20
#: Physically admissible displaced volumes, gallons, and the grid that
#: brackets the fit before it is refined (about 0.1 gal a step).
DISPLACED_BOUNDS = (0.5, 25.0)
DISPLACED_GRID_POINTS = 250
#: How far back the circulation's recent flow is measured, and how many
#: runs in that window it needs.
RECENT_FLOW_WINDOW = timedelta(days=14)
MIN_RUNS_FOR_FLOW = 5
#: How far from a measured run its flow still prices another run.
RUN_FLOW_WITHIN = timedelta(days=1)


@dataclass(frozen=True)
class MeasuredRun:
    """One circulation run with the compressor off, and the heat it took
    measured: its flow times the drop from the upper zone to the return
    line, the median over its running samples, times its minutes; and
    the hours since the run before it ended (None for the first)."""

    start: datetime
    end: datetime
    minutes: float
    btu: float | None
    flow_gpm: float | None
    upper_f: float | None
    air_f: float | None
    rest_h: float | None = None


def _held_at(
    rows: Sequence[tuple[datetime, float]],
    at: Sequence[datetime],
    max_age: timedelta | None = None,
) -> list[float | None]:
    """The reading in force at each of ``at`` (the last at or before
    it), none past ``max_age``."""
    times = [t for t, _ in rows]
    out: list[float | None] = []
    for t in at:
        i = bisect.bisect_right(times, t) - 1
        if i < 0 or (max_age is not None and t - times[i] > max_age):
            out.append(None)
        else:
            out.append(rows[i][1])
    return out


def measure_runs(
    running: Sequence[datetime],
    *,
    flow: Sequence[tuple[datetime, float]],
    return_f: Sequence[tuple[datetime, float]],
    upper_f: Sequence[tuple[datetime, float]],
    air_f: Sequence[tuple[datetime, float]] = (),
    compressor: Sequence[tuple[datetime, datetime]] = (),
) -> list[MeasuredRun]:
    """Each circulation run, from the instants a sample read it running
    (``running``) clustered within ``circulation.RUN_GAP``, and those that
    overlap a compressor run (``compressor``) left out. Its heat: the
    flow (gal/min) and the return line (degF), each fresh within
    ``RETURN_MAX_AGE`` of a running sample, against the upper zone in
    force then; its upper zone the first reading in it, its air the
    median of those in it, its rest the hours since the run before it
    ended, a run left out included."""
    on = sorted(running)
    clusters: list[list[datetime]] = []
    for t in on:
        if clusters and t - clusters[-1][1] <= RUN_GAP:
            clusters[-1][1] = t
        else:
            clusters.append([t, t])
    flow, return_f = sorted(flow), sorted(return_f)
    upper_f, air_f = sorted(upper_f), sorted(air_f)
    out: list[MeasuredRun] = []
    last_end: datetime | None = None
    for a, b in ((c[0], c[1]) for c in clusters):
        rest = (
            None
            if last_end is None
            else (a - last_end).total_seconds() / 3600.0
        )
        # A run of one sample is not measured, but it ran.
        last_end = b
        if b <= a or any(not (b <= s or e <= a) for s, e in compressor):
            continue
        samples = [t for t in on if a <= t <= b]
        ups = _held_at(upper_f, samples)
        rets = _held_at(return_f, samples, RETURN_MAX_AGE)
        flows = _held_at(flow, samples, RETURN_MAX_AGE)
        q = [
            f * 60.0 * WATER_BTU_PER_GAL_F * (u - r)
            for u, r, f in zip(ups, rets, flows, strict=True)
            if u is not None and r is not None and f is not None
        ]
        fresh_flow = [
            f
            for u, r, f in zip(ups, rets, flows, strict=True)
            if u is not None and r is not None and f is not None
        ]
        minutes = (b - a).total_seconds() / 60.0
        q_median = float(np.median(q)) if q else None
        first_up = next((v for t, v in upper_f if a <= t <= b), None)
        airs = [v for t, v in air_f if a <= t <= b]
        out.append(
            MeasuredRun(
                start=a,
                end=b,
                minutes=minutes,
                btu=None if q_median is None else q_median * minutes / 60.0,
                flow_gpm=float(np.median(fresh_flow)) if fresh_flow else None,
                upper_f=first_up,
                air_f=float(np.median(airs)) if airs else None,
                rest_h=rest,
            )
        )
    return out


def run_heat_btu(
    minutes: float,
    upper_f: float,
    air_f: float,
    displaced: float,
    flow_gpm: float,
    *,
    rest_offset_f: float = 0.0,
    rest_h: float | None = None,
    cool_tau_h: float = 0.0,
    before_min: float = 0.0,
) -> float:
    """The heat a run takes for its displaced volume over ``minutes``
    of it, after ``before_min`` it had already run: the gallons it
    displaces in them (``circulation.displaced_gal``), times the share
    cooled since the run before (``circulation.cooled_share``), at the
    upper zone less the return's rest (the air plus ``rest_offset_f``),
    never negative."""
    if displaced <= 0.0 or minutes <= 0.0 or flow_gpm <= 0.0:
        return 0.0
    gal = (
        circulation_displaced_gal(before_min + minutes, displaced, flow_gpm)
        - circulation_displaced_gal(before_min, displaced, flow_gpm)
    ) * cooled_share(rest_h, cool_tau_h)
    return max(
        0.0, gal * WATER_BTU_PER_GAL_F * (upper_f - air_f - rest_offset_f)
    )


#: Physically admissible rest offsets, °F, and cooling time constants,
#: hours, for ``fit_return``.
REST_OFFSET_BOUNDS = (-20.0, 30.0)
COOL_TAU_BOUNDS = (0.02, 24.0)
#: The least ratio of the smallest to the largest singular value of the
#: fitted heat's sensitivities to ``fit_return``'s three terms, each
#: scaled by its bounds, for the runs to tell the terms apart. The
#: record's runs give about 0.03; runs that cannot tell them apart (no
#: rest known, none longer than the volume, one rest and one tank-to-air
#: difference throughout) give 1e-14 or less.
MIN_TERM_INDEPENDENCE = 1e-6


def fit_return(
    runs: Sequence[MeasuredRun],
) -> tuple[float, float, float] | None:
    """``CirculationParams``' ``(displaced_gal, return_rest_offset_f,
    return_cool_tau_h)`` together: the three minimising the mean absolute
    error of ``run_heat_btu`` against each run's measured heat, at its
    own flow and rest. None with fewer than ``MIN_RUNS_TO_FIT`` usable
    runs, a fit pinned on a bound, or runs that cannot tell the three
    apart (``MIN_TERM_INDEPENDENCE``): with no rest known the cooling is
    not seen, with no run longer than the volume the volume is not, and
    with one rest and one tank-to-air difference throughout the offset
    and the cooling trade off."""
    usable = [
        (r.minutes, r.upper_f, r.air_f, r.flow_gpm, r.btu, r.rest_h)
        for r in runs
        if r.minutes > 0
        and r.flow_gpm
        and r.btu
        and r.btu > 0
        and r.upper_f is not None
        and r.air_f is not None
        and r.upper_f > r.air_f
    ]
    if len(usable) < MIN_RUNS_TO_FIT:
        return None
    bounds = (DISPLACED_BOUNDS, REST_OFFSET_BOUNDS, COOL_TAU_BOUNDS)

    def heat(x: Sequence[float]) -> np.ndarray:
        volume, offset, tau = x
        return np.array(
            [
                run_heat_btu(
                    m,
                    up,
                    air,
                    volume,
                    f,
                    rest_offset_f=offset,
                    rest_h=rest,
                    cool_tau_h=tau,
                )
                for m, up, air, f, _, rest in usable
            ]
        )

    measured = np.array([u[4] for u in usable])

    def mae(x: np.ndarray) -> float:
        return float(np.mean(np.abs(heat([float(v) for v in x]) - measured)))

    # The objective has flat stretches, so several starts.
    tries = [
        cast(
            OptimizeResult,
            minimize(
                mae,
                np.array(x0),
                method="Nelder-Mead",
                bounds=bounds,
                options={"xatol": 1e-4, "fatol": 0.1, "maxiter": 4000},
            ),
        )
        for x0 in ((6.0, 0.0, 1.0), (8.0, 5.0, 1.0), (12.0, 8.0, 2.0))
    ]
    found = tries[int(np.argmin([float(r.fun) for r in tries]))]
    x = [float(v) for v in found.x]
    # Within a thousandth of the range of a bound is on it.
    if any(
        not lo + (hi - lo) / 1000 < v < hi - (hi - lo) / 1000
        for v, (lo, hi) in zip(x, bounds, strict=True)
    ):
        return None
    # Each term's effect on the fitted heat, by central difference.
    columns = []
    for k, (lo, hi) in enumerate(bounds):
        step = (hi - lo) * 1e-4
        up, down = list(x), list(x)
        up[k] += step
        down[k] -= step
        columns.append((heat(up) - heat(down)) / 2 * 1e4)
    sv = np.linalg.svd(np.column_stack(columns), compute_uv=False)
    if not sv[0] > 0.0 or sv[-1] / sv[0] < MIN_TERM_INDEPENDENCE:
        return None
    return x[0], x[1], x[2]


def fit_displaced_gal(runs: Sequence[MeasuredRun]) -> float | None:
    """``CirculationParams.displaced_gal``: the volume minimising the
    mean absolute error of ``run_heat_btu`` against each run's measured
    heat, at its own flow. The objective goes flat past the largest
    displaced volume in the runs, so it is bracketed on a grid over
    ``DISPLACED_BOUNDS`` first and refined inside the winning interval.
    None with fewer than ``MIN_RUNS_TO_FIT`` usable runs, or a fit pinned
    on a bound (the runs do not constrain it)."""
    usable = [
        (
            r.minutes,
            r.upper_f or 0.0,
            r.air_f or 0.0,
            r.flow_gpm or 0.0,
            r.btu or 0.0,
        )
        for r in runs
    ]
    usable = [
        u for u in usable if u[0] > 0 and u[3] > 0 and u[4] > 0 and u[1] > u[2]
    ]
    if len(usable) < MIN_RUNS_TO_FIT:
        return None

    def mae(volume: float) -> float:
        return sum(
            abs(run_heat_btu(m, up, air, volume, f) - measured)
            for m, up, air, f, measured in usable
        ) / len(usable)

    lo, hi = DISPLACED_BOUNDS
    grid = np.linspace(lo, hi, DISPLACED_GRID_POINTS)
    scores = [mae(float(v)) for v in grid]
    best = int(np.argmin(scores))
    found = cast(
        OptimizeResult,
        minimize_scalar(
            mae,
            bounds=(
                float(grid[max(best - 1, 0)]),
                float(grid[min(best + 1, len(grid) - 1)]),
            ),
            method="bounded",
        ),
    )
    volume = float(found.x)
    if mae(float(grid[best])) < mae(volume):
        volume = float(grid[best])
    if not lo * 1.01 < volume < hi * 0.99:
        return None
    return volume


def recent_flow_gpm(
    runs: Sequence[MeasuredRun],
    until: datetime,
    window: timedelta = RECENT_FLOW_WINDOW,
) -> float | None:
    """``CirculationParams.flow_gpm``: the median of the runs' own
    median flows over the ``window`` before ``until``, the flow being a
    setting that moves in steps. None with fewer than
    ``MIN_RUNS_FOR_FLOW``."""
    flows = sorted(
        r.flow_gpm
        for r in runs
        if r.flow_gpm is not None
        and r.flow_gpm > 0.0
        and until - window <= r.start <= until
    )
    if len(flows) < MIN_RUNS_FOR_FLOW:
        return None
    mid = len(flows) // 2
    if len(flows) % 2:
        return flows[mid]
    return (flows[mid - 1] + flows[mid]) / 2.0


def flow_lookup(
    runs: Sequence[MeasuredRun], within: timedelta = RUN_FLOW_WITHIN
) -> Callable[[datetime], float | None]:
    """The flow a past run ran at: the measured run nearest it in time,
    within ``within``; None when none is near enough."""
    known = sorted(
        (r.start, r.flow_gpm)
        for r in runs
        if r.flow_gpm is not None and r.flow_gpm > 0.0
    )
    starts = [t for t, _ in known]

    def flow_at(at: datetime) -> float | None:
        i = bisect.bisect_left(starts, at)
        near = [known[j] for j in (i - 1, i) if 0 <= j < len(known)]
        best = min(near, key=lambda r: abs(r[0] - at), default=None)
        if best is None or abs(best[0] - at) > within:
            return None
        return best[1]

    return flow_at


# ── the elements: their lag, rate, off point and power ──────────────
#
# As the element terms were measured, from raw rows (the change rows of
# ``sim.record.Record``), never a one-minute grid, which moves an edge
# by up to a minute and is the size of what is measured.

#: The probe's step and how long a stint must run, °F and s.
PROBE_STEP_F = 0.18
MIN_STINT_S = 60.0
#: No draw or circulation from this long before a stint to its rise.
STINT_DRAW_GUARD = timedelta(minutes=5)
#: A probe read more than this before an edge was still moving, s.
FRESH_READ_S = 6.0
#: A stint metered for power runs at least this long, s.
MIN_POWER_STINT_S = 90.0
_ELEMENT_FIT_MODES = (ENERGY_SAVER, HIGH_DEMAND, ELECTRIC)


def _stints(
    rows: Sequence[tuple[datetime, float]],
) -> list[tuple[datetime, datetime]]:
    """An on/off signal's runs ``(on, off)``, from its change rows."""
    out: list[tuple[datetime, datetime]] = []
    on: datetime | None = None
    prev: bool | None = None
    for t, v in rows:
        cur = v > 0
        if cur == prev:
            continue
        prev = cur
        if cur and on is None:
            on = t
        elif not cur and on is not None:
            out.append((on, t))
            on = None
    return out


def _asof_row(
    rows: Sequence[tuple[datetime, float]], t: datetime
) -> float | None:
    times = [x for x, _ in rows]
    i = bisect.bisect_right(times, t) - 1
    return rows[i][1] if i >= 0 else None


def _changes(rows: Sequence[tuple[datetime, float]]) -> list[datetime]:
    """When a signal changed (its rows after the first that differ)."""
    return [
        rows[i][0] for i in range(1, len(rows)) if rows[i][1] != rows[i - 1][1]
    ]


def _local_day(t: datetime, tz: str) -> str:
    return f"{t.astimezone(ZoneInfo(tz)):%Y-%m-%d}"


def element_stints(
    record: Record,
    *,
    draws: Sequence[tuple[datetime, datetime]] | None = None,
    circulation: Sequence[tuple[datetime, datetime]] = (),
    tz: str = "UTC",
    held_out_from: datetime | None = None,
) -> pd.DataFrame:
    """Every upper-element stint, read from raw rows: the probe as of
    its on-edge, the first rise at least a probe step above it that the
    probe holds to the off-edge (``lat_s``), less the probe's reporting
    cadence while rising (``dead_min``), its run, rise and coast after
    the off-edge, and what screens it:

    - ``start_clean``: a run of ``MIN_STINT_S`` or more, a held rise,
      and neither the mode nor the setpoint changed before the rise;
    - ``end_clean``: the mode it started in at the off-edge, no mode
      change to 30 s past it, and a probe read within ``FRESH_READ_S``
      of it;
    - ``draw``: a meter's draw (``draws``) or a circulation run within
      ``STINT_DRAW_GUARD`` before it to its rise; ``draw_known`` from
      the meter's first draw (no ``draws``: never known).

    ``day`` is the local day in ``tz``; ``held_out`` from
    ``held_out_from``."""
    up = list(record.upper_f)
    ut = [t for t, _ in up]
    uv = np.array([v for _, v in up])
    mode_ch, sp_ch = _changes(record.mode), _changes(record.setpoint_f)
    known_from = min((a for a, _ in draws), default=None) if draws else None
    rows: list[dict[str, Any]] = []
    for on, off in _stints(record.upper_element):
        i0 = bisect.bisect_right(ut, on) - 1
        if i0 < 0:
            continue
        u_on = float(uv[i0])
        horizon = max(off, on + timedelta(minutes=3))
        lo, hi = bisect.bisect_right(ut, on), bisect.bisect_right(ut, horizon)
        t_in, v_in = ut[lo:hi], uv[lo:hi]
        first = held = None
        for k in range(len(t_in)):
            if v_in[k] < u_on + PROBE_STEP_F - 0.01:
                continue
            first = first if first is not None else t_in[k]
            later = [
                v for t, v in zip(t_in[k:], v_in[k:], strict=True) if t <= off
            ]
            if all(v > u_on + 0.01 for v in later):
                held = t_in[k]
                break
        until = held if held is not None else horizon
        rising = [t for t in ut if until <= t <= off]
        gaps = (
            np.diff([t.timestamp() for t in rising])
            if len(rising) > 1
            else np.array([])
        )
        gaps = gaps[gaps > 1.0]
        guard = on - STINT_DRAW_GUARD
        circulated = any(a < until and b > guard for a, b in circulation)
        drawn = draws is not None and any(
            a < until and b > guard for a, b in draws
        )
        i_off = bisect.bisect_right(ut, off) - 1
        after = [v for t, v in up if off < t <= off + timedelta(minutes=5)]
        mode_on = _asof_row(record.mode, on)
        rows.append(
            {
                "on": on,
                "off": off,
                "mode": None if mode_on is None else int(mode_on),
                "run_min": (off - on).total_seconds() / 60,
                "u_on": u_on,
                "lat_s": (held - on).total_seconds()
                if held is not None
                else np.nan,
                "cad_s": float(np.median(gaps)) if len(gaps) >= 2 else np.nan,
                "start_clean": bool(
                    (off - on).total_seconds() >= MIN_STINT_S
                    and held is not None
                    and not any(on < c <= until for c in mode_ch)
                    and not any(on < c <= until for c in sp_ch)
                ),
                "draw_known": known_from is not None and on >= known_from,
                "draw": bool(circulated or drawn),
                "end_clean": bool(
                    mode_on == _asof_row(record.mode, off)
                    and not any(
                        on < c < off + timedelta(seconds=30) for c in mode_ch
                    )
                    and (off - ut[i_off]).total_seconds() <= FRESH_READ_S
                ),
                "u_off": float(uv[i_off]),
                "peak": max(after) if after else np.nan,
            }
        )
    r = pd.DataFrame(rows)
    if r.empty:
        return r
    month = [f"{t:%Y-%m}" for t in r["on"]]
    r["cad_s"] = r["cad_s"].fillna(
        r.groupby(month)["cad_s"].transform("median")
    )
    r["dead_min"] = (r["lat_s"] - r["cad_s"]) / 60
    r["rise"] = r["u_off"] - r["u_on"]
    r["coast"] = r["peak"] - r["u_off"]
    r["day"] = [_local_day(t, tz) for t in r["on"]]
    r["held_out"] = [
        held_out_from is not None and t >= held_out_from for t in r["on"]
    ]
    return r


def _theil_sen(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Intercept and slope; pairs closer than 0.5 °F in rise left out,
    their slopes being mostly the probe's step."""
    i, j = np.triu_indices(len(x), 1)
    far = np.abs(x[j] - x[i]) > 0.5
    slope = float(np.median((y[j] - y[i])[far] / (x[j] - x[i])[far]))
    return float(np.median(y - slope * x)), slope


@dataclass(frozen=True)
class ElementLagFit:
    """``ElementParams.upper_dead_time_min`` and ``upper_f_per_min``:
    run minutes = lag + rise / rate, a Theil-Sen line over the stints
    that started and ended clean with no draw recorded, and 90 % day
    bootstrap intervals."""

    upper_dead_time_min: float
    upper_f_per_min: float
    lag_interval: tuple[float, float]
    rate_interval: tuple[float, float]
    n: int


def fit_element_lag(
    stints: pd.DataFrame, *, n_boot: int = 2000, seed: int = 252
) -> ElementLagFit | None:
    """The upper element's lag and rate from ``element_stints``: those
    clean at both ends, rising, without a recorded draw, the held-out
    ones left out. None with fewer than four distinct rises."""
    if stints.empty:
        return None
    ran = stints[
        stints["start_clean"]
        & stints["end_clean"]
        & (stints["rise"] > 0)
        & ~(stints["draw_known"] & stints["draw"])
    ]
    q = ran[~ran["held_out"]]
    x = np.asarray(q["rise"], dtype=float)
    y = np.asarray(q["run_min"], dtype=float)
    if len(np.unique(x)) < 4:
        return None
    lag, slope = _theil_sen(x, y)
    rng = np.random.default_rng(seed)
    days = np.asarray(q["day"])
    uniq = np.unique(days)
    lags, rates = [], []
    for _ in range(n_boot):
        pick = np.concatenate(
            [np.flatnonzero(days == k) for k in rng.choice(uniq, len(uniq))]
        )
        if len(np.unique(x[pick])) < 4:
            continue
        a, b = _theil_sen(x[pick], y[pick])
        lags.append(a)
        rates.append(1 / b)
    return ElementLagFit(
        upper_dead_time_min=lag,
        upper_f_per_min=1 / slope,
        lag_interval=tuple(np.quantile(lags, [0.05, 0.95])),
        rate_interval=tuple(np.quantile(rates, [0.05, 0.95])),
        n=len(q),
    )


def element_off_points(record: Record, *, tz: str = "UTC") -> pd.DataFrame:
    """Every element off-edge: the zone's probe and the setpoint as of
    it (``deficit``, setpoint less probe), how old the probe's read was
    (``age_s``), the coast (its peak in 5 min less the setpoint), and
    ``clean``: no mode change from 90 s before to 30 s after the edge,
    the mode it started in, and no setpoint change during it."""
    mode_ch, sp_ch = _changes(record.mode), _changes(record.setpoint_f)
    rows: list[dict[str, Any]] = []
    for which, flags, probe in (
        ("upper", record.upper_element, list(record.upper_f)),
        ("lower", record.lower_element, list(record.lower_f)),
    ):
        for on, off in _stints(flags):
            pre = [(t, v) for t, v in probe if t <= off]
            after = [
                v for t, v in probe if off < t <= off + timedelta(minutes=5)
            ]
            sp = _asof_row(record.setpoint_f, off)
            mode_on = _asof_row(record.mode, on)
            mode_off = _asof_row(record.mode, off)
            near_off = any(
                off - timedelta(seconds=90) < c < off + timedelta(seconds=30)
                for c in mode_ch
            )
            sp_moved = any(on < c < off + timedelta(seconds=30) for c in sp_ch)
            rows.append(
                {
                    "which": which,
                    "on": on,
                    "off": off,
                    "mode": None if mode_on is None else int(mode_on),
                    "setpoint": np.nan if sp is None else sp,
                    "probe_off": pre[-1][1] if pre else np.nan,
                    "age_s": (off - pre[-1][0]).total_seconds()
                    if pre
                    else np.nan,
                    "peak5": max(after) if after else np.nan,
                    "clean": bool(
                        mode_on == mode_off and not near_off and not sp_moved
                    ),
                }
            )
    r = pd.DataFrame(rows)
    if r.empty:
        return r
    r["deficit"] = r["setpoint"] - r["probe_off"]
    r["coast"] = r["peak5"] - r["setpoint"]
    r["day"] = [_local_day(t, tz) for t in r["on"]]
    return r


def day_ci(
    x: np.ndarray, days: np.ndarray, *, n_boot: int = 4000, seed: int = 252
) -> tuple[float, float, float]:
    """The median and its 90 % interval over a bootstrap of local
    days (stints on one day share a tank and often a test)."""
    rng = np.random.default_rng(seed)
    u = np.unique(days)
    b = [
        np.median(np.concatenate([x[days == k] for k in rng.choice(u, len(u))]))
        for _ in range(n_boot)
    ]
    return (
        float(np.median(x)),
        float(np.quantile(b, 0.05)),
        float(np.quantile(b, 0.95)),
    )


def element_power(record: Record, off_points: pd.DataFrame) -> pd.DataFrame:
    """Each metered stint's mean power (``off_points``' stints of
    ``MIN_POWER_STINT_S`` or more with the other element off), the power
    held between reports and back-filled to the on-edge from its first
    inside, on a 1 s clock: ``net_w`` less the compressor's share where
    it co-ran (its median report with the compressor on and no element
    in the 10 min after), ``alone_w`` over the compressor-off seconds
    (a minute of them or more)."""
    w = list(record.power_w)
    rows: list[dict[str, Any]] = []
    for _, s in off_points.iterrows():
        on, off = cast(datetime, s["on"]), cast(datetime, s["off"])
        if (off - on).total_seconds() < MIN_POWER_STINT_S:
            continue
        first = math.ceil(on.timestamp())
        clock = [
            datetime.fromtimestamp(x, tz=on.tzinfo)
            for x in range(first, math.floor(off.timestamp()) + 1)
        ]
        other = (
            record.lower_element
            if str(s["which"]) == "upper"
            else record.upper_element
        )
        if any(
            (v := _asof_row(other, t)) is not None and bool(v > 0)
            for t in clock
        ):
            continue
        inside = [(t, v) for t, v in w if on <= t < off]
        if len(inside) < 2:
            continue
        pw = np.array(
            [
                inside[0][1] if t < inside[0][0] else (_asof_row(w, t) or 0.0)
                for t in clock
            ]
        )
        comp = np.array(
            [
                (v := _asof_row(record.compressor, t)) is not None and v > 0
                for t in clock
            ]
        )
        after = [(t, v) for t, v in w if off < t <= off + timedelta(minutes=10)]
        quiet = [
            v
            for t, v in after
            if ((c := _asof_row(record.compressor, t)) is not None and c > 0)
            and not (
                (
                    (u := _asof_row(record.upper_element, t)) is not None
                    and u > 0
                )
                or (
                    (lo := _asof_row(record.lower_element, t)) is not None
                    and lo > 0
                )
            )
        ]
        comp_w = float(np.median(quiet)) if quiet else float("nan")
        if comp.any() and not comp_w < 1000:
            continue
        net = pw - np.where(comp, comp_w if comp.any() else 0.0, 0.0)
        alone = pw[~comp]
        rows.append(
            {
                "on": on,
                "which": s["which"],
                "net_w": float(net.mean()),
                "alone_w": float(alone.mean()) if len(alone) >= 60 else np.nan,
                "day": s["day"],
            }
        )
    return pd.DataFrame(rows)


def element_grid(
    record: Record, *, draws: Sequence[tuple[datetime, datetime]] | None = None
) -> pd.DataFrame:
    """The record held on a one-minute grid, from the later of the
    power's and the mode's first rows to the power's last: which element
    is on (``which``, the upper first), the compressor, the probes, the
    setpoint, the mode, the power within 5 min, and ``draw`` (a minute a
    metered draw touched, its start floored and its end ceiled) with
    ``draw_known`` from the first draw's minute (no ``draws``: never)."""
    if not record.power_w or not record.mode:
        return pd.DataFrame()
    first = max(record.power_w[0][0], record.mode[0][0])
    t0 = math.ceil(first.timestamp() / 60) * 60
    t1 = math.floor(record.power_w[-1][0].timestamp() / 60) * 60
    tz = first.tzinfo
    grid = [datetime.fromtimestamp(x, tz=tz) for x in range(t0, t1 + 1, 60)]

    def held(rows: Sequence[tuple[datetime, float]]) -> list[float]:
        return [
            np.nan if (v := _asof_row(rows, t)) is None else v for t in grid
        ]

    power_times = [t for t, _ in record.power_w]

    def power_at(t: datetime) -> float:
        i = bisect.bisect_right(power_times, t) - 1
        if i < 0 or t - power_times[i] > timedelta(minutes=5):
            return np.nan
        return record.power_w[i][1]

    g = pd.DataFrame(
        {
            "mode": held(record.mode),
            "C": [v > 0 for v in held(record.compressor)],
            "U": [v > 0 for v in held(record.upper_element)],
            "L": [v > 0 for v in held(record.lower_element)],
            "upper": held(record.upper_f),
            "lower": held(record.lower_f),
            "setpoint": held(record.setpoint_f),
            "W": [power_at(t) for t in grid],
        },
        index=pd.DatetimeIndex(grid),
    )
    drawn = np.zeros(len(grid), dtype=bool)
    stamps = np.array([t.timestamp() for t in grid])
    for a, b in draws or ():
        lo = math.floor(a.timestamp() / 60) * 60
        hi = math.ceil(b.timestamp() / 60) * 60
        drawn |= (stamps >= lo) & (stamps <= hi)
    g["draw"] = drawn
    g["draw_known"] = (
        stamps >= math.floor(min(a for a, _ in draws).timestamp() / 60) * 60
        if draws
        else np.zeros(len(grid), dtype=bool)
    )
    g["which"] = np.where(g["U"], "upper", np.where(g["L"], "lower", "-"))
    return g


def element_runs(
    grid: pd.DataFrame,
    modes: tuple[int, ...] = _ELEMENT_FIT_MODES,
) -> pd.DataFrame:
    """One row per run of a single element on ``element_grid``: three
    grid minutes or more in one of ``modes``, its zone's rise over its
    **elapsed** minutes (n samples span n - 1), and ``draw`` (None
    where draws were not yet known). Grouped on which element is on,
    so an Electric sequence's upper then lower runs are two."""
    which = grid["which"]
    on = which != "-"
    rid = (which != which.shift()).cumsum()
    rows: list[dict[str, Any]] = []
    for _, d in grid[on].groupby(rid[on]):
        col = {k: list(d[k]) for k in d.columns}
        mode = col["mode"][0]
        if len(d) < 3 or mode not in modes:
            continue
        zone = "upper" if col["which"][0] == "upper" else "lower"
        index = cast(pd.DatetimeIndex, d.index)
        rows.append(
            {
                "start": index[0],
                "mode": int(mode),
                "which": col["which"][0],
                "elapsed_min": (
                    cast(pd.Timestamp, index[-1]) - cast(pd.Timestamp, index[0])
                ).total_seconds()
                / 60.0,
                "rise": col[zone][-1] - col[zone][0],
                "start_probe": col[zone][0],
                "setpoint": col["setpoint"][0],
                "draw": any(col["draw"]) if all(col["draw_known"]) else None,
            }
        )
    r = pd.DataFrame(rows)
    if r.empty:
        return r
    r["rate"] = r["rise"] / r["elapsed_min"]
    r["deficit"] = r["setpoint"] - r["start_probe"]
    return r


@dataclass(frozen=True)
class ElementRateFit:
    """``ElementParams.element_w`` (the median power with an element and
    no compressor on, in High Demand or Electric), ``upper_f_per_min``
    and ``lower_f_per_min`` (each zone's median run rate, every mode
    pooled, runs with a known draw left out), and their 90 % bootstrap
    intervals. A rate is None without a run."""

    element_w: float | None
    upper_f_per_min: float | None
    lower_f_per_min: float | None
    element_w_interval: tuple[float, float] | None
    upper_interval: tuple[float, float] | None
    lower_interval: tuple[float, float] | None
    runs: int


def fit_element_rates(
    grid: pd.DataFrame, *, n_boot: int = 2000, seed: int = 252
) -> ElementRateFit:
    """The element's power and the zones' rates from ``element_grid``
    (see ``ElementRateFit``). The upper rate measured end to end on the
    grid sits below ``fit_element_lag``'s, its lag counted in it."""
    rng = np.random.default_rng(seed)

    def ci(values: np.ndarray) -> tuple[float, tuple[float, float]]:
        boots = [
            np.median(rng.choice(values, size=len(values), replace=True))
            for _ in range(n_boot)
        ]
        return float(np.median(values)), (
            float(np.quantile(boots, 0.05)),
            float(np.quantile(boots, 0.95)),
        )

    w = w_ci = None
    if not grid.empty:
        alone = grid.loc[
            (grid["U"] | grid["L"])
            & ~grid["C"]
            & grid["mode"].isin([HIGH_DEMAND, ELECTRIC]),
            "W",
        ].dropna()
        if len(alone):
            w, w_ci = ci(np.asarray(alone, dtype=float))
    r = element_runs(grid) if not grid.empty else pd.DataFrame()
    out: dict[str, tuple[float, tuple[float, float]] | None] = {}
    for which in ("upper", "lower"):
        x = (
            np.asarray(
                r.loc[(r["draw"] != True) & (r["which"] == which), "rate"],  # noqa: E712
                dtype=float,
            )
            if not r.empty
            else np.array([])
        )
        out[which] = ci(x) if len(x) else None
    up, lo = out["upper"], out["lower"]
    return ElementRateFit(
        element_w=w,
        upper_f_per_min=None if up is None else up[0],
        lower_f_per_min=None if lo is None else lo[0],
        element_w_interval=w_ci,
        upper_interval=None if up is None else up[1],
        lower_interval=None if lo is None else lo[1],
        runs=len(r),
    )


def energy_saver_off_deficit(
    off_points: pd.DataFrame, *, n_boot: int = 4000, seed: int = 252
) -> tuple[float, float, float] | None:
    """``ElementParams.energy_saver_upper_off_below_setpoint_f``: how far
    short of the setpoint Energy Saver's upper element stops, the median
    deficit over ``element_off_points``' clean upper off-edges in that
    mode with the probe read within ``FRESH_READ_S`` of the edge (an
    older read was still rising), with its 90 % day-bootstrap interval.
    None without one."""
    if off_points.empty:
        return None
    deficit = np.asarray(off_points["deficit"], dtype=float)
    keep = (
        np.asarray(off_points["clean"], dtype=bool)
        & (np.asarray(off_points["which"]) == "upper")
        & (np.asarray(off_points["mode"], dtype=float) == ENERGY_SAVER)
        & (np.asarray(off_points["age_s"], dtype=float) <= FRESH_READ_S)
        & np.isfinite(deficit)
    )
    if not keep.any():
        return None
    return day_ci(
        deficit[keep],
        np.asarray(off_points["day"])[keep],
        n_boot=n_boot,
        seed=seed,
    )


def upper_start_edge(runs: pd.DataFrame) -> dict[str, float] | None:
    """How far below the setpoint the upper element starts, as an edge
    (``element_runs``' upper runs with no known draw): the smallest
    deficit seen, and among the starts within 8 °F of the setpoint how
    many, the smallest, the 10th percentile and the median. The edge is
    the smallest deficit that still starts it, not the middle of the
    starts. None without an upper run."""
    if runs.empty:
        return None
    drawn = [d is True for d in runs["draw"]]
    upper = np.asarray(runs["which"]) == "upper"
    deficit = np.asarray(runs["deficit"], dtype=float)[upper & ~np.array(drawn)]
    if not len(deficit):
        return None
    close = deficit[deficit < 8]
    some = bool(len(close))
    return {
        "smallest_f": float(deficit.min()),
        "close_n": float(len(close)),
        "close_min_f": float(close.min()) if some else math.nan,
        "close_p10_f": float(np.quantile(close, 0.1)) if some else math.nan,
        "close_median_f": float(np.median(close)) if some else math.nan,
    }
