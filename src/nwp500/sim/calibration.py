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
  report held until the next, for the power fits;
- ``energy_to_setpoint_wh``: the heater's own deficit to its setpoint
  (``DeviceStatus.energy_to_setpoint``), to tell a recovery cut short
  from one that finished;
- ``heater_air_f``: the heater's own air reading while its compressor
  runs, NaN otherwise (``sim_adapters.location_air_reading``);
- ``air_f``: the air where the heater stands throughout, for the
  standby loss: a sensor's, or ``location_air``'s projection;
- optionally ``humidity_pct`` (the air's, for the evaporator; 50
  without) and ``drawing``, ``circulating`` (a meter's draws and the
  circulation's runs, ``sim.circulation``; with them, the quiet test needs no
  ``dhw_in_use``).

Each fit reports what it saw and what it left out
(``StandbyFit``, ``CompressorFit``), and only replaces the base
parameters' values when it had the evidence to.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeResult, minimize, minimize_scalar

from nwp500.sim.book import Booked, house_gpm
from nwp500.sim.book import Step as BookStep
from nwp500.sim.heating_trajectory import path_cop
from nwp500.sim.params import (
    UA_MIN_DELTA_T_F,
    UA_REF_DELTA_T_F,
    BookParams,
    CirculationParams,
    CompressorParams,
    HeaterParams,
    LossParams,
)
from nwp500.sim.physics.compressor import PhysicsPath, predict_physics_detailed
from nwp500.sim.units import BTU_PER_WH, WATER_BTU_PER_GAL_F

#: An interval: its start and its end.
Interval = tuple[datetime, datetime]

# ── standby: quiet windows, the loss law, the gap's time constant ────

#: How long after heating, a draw or a circulation run the tank is still
#: settling and is not fitted. At one installation, 0 -> 45 min took the
#: fitted UA's spread from 5.63 ± 3.32 to 4.88 ± 1.15 over 24 windows.
SETTLE_MINUTES = 45.0
#: The shortest quiet window fitted, hours.
MIN_QUIET_HOURS = 3.0
#: A window's UA fit is kept only when it tracks the probes this well, °F.
MAX_WINDOW_RMSE_F = 2.0
#: The UA a window's fit may land in, BTU/h/°F.
UA_SEARCH_BOUNDS = (0.5, 30.0)
#: The UA law's exponent bounds: 0 is constant UA; 0.25-0.33 is free
#: convection; past about 0.5 something other than the jacket drives it.
UA_EXPONENT_BOUNDS = (0.0, 0.75)
#: The evidence the law needs before an exponent is fitted.
_MIN_WINDOWS_FOR_LAW = 4
_MIN_BANDS_FOR_LAW = 2
_BAND_WIDTH_F = 20.0
#: A window enters the gap fit only if it starts with a gap worth
#: relaxing, °F, and the gap's constant is fitted only on this many.
MIN_GAP_FIT_START_F = 2.0
MIN_GAP_FIT_WINDOWS = 20
GAP_TAU_BOUNDS_HOURS = (1.0, 2000.0)


def _instants(frame: pd.DataFrame) -> list[datetime]:
    """The frame's index as instants."""
    # A history's index holds no NaT: each row is a sample's instant.
    return [
        cast(datetime, pd.Timestamp(t).to_pydatetime()) for t in frame.index
    ]


def _on_intervals(when: list[datetime], on: np.ndarray) -> list[Interval]:
    """The spans a state sampled at ``when`` is on: from a sample that
    reads on to the next that reads off (to the last sample, if open)."""
    out: list[Interval] = []
    start: datetime | None = None
    for t, v in zip(when, on, strict=True):
        if v and start is None:
            start = t
        elif not v and start is not None:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, when[-1]))
    return out


def _merge(intervals: list[Interval]) -> list[Interval]:
    """Overlapping intervals merged, sorted."""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def busy_intervals(
    history: pd.DataFrame, settle_minutes: float = SETTLE_MINUTES
) -> list[Interval]:
    """The spans the tank is not quiet: heating (``compressor_on``,
    ``element_on``), water moving (``drawing``, ``circulating`` where
    recorded, else ``dhw_in_use``), each extended forward by
    ``settle_minutes`` while the tank settles. Merged, sorted."""
    when = _instants(history)
    columns = ["compressor_on", "element_on"]
    tier1 = [c for c in ("drawing", "circulating") if c in history.columns]
    columns += tier1 or ["dhw_in_use"]
    settle = timedelta(minutes=settle_minutes)
    spans: list[Interval] = []
    for column in columns:
        on = history[column].fillna(False).astype(bool).to_numpy()
        spans += [(a, b + settle) for a, b in _on_intervals(when, on)]
    return _merge(spans)


def quiet_windows(
    history: pd.DataFrame,
    min_hours: float = MIN_QUIET_HOURS,
    settle_minutes: float = SETTLE_MINUTES,
) -> list[Interval]:
    """The complement of ``busy_intervals`` within the history, keeping
    the windows of at least ``min_hours``."""
    if history.empty:
        return []
    when = _instants(history)
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


@dataclass(frozen=True)
class StandbyWindow:
    """One quiet window's fit: the UA that decays the tank's mean as
    the probes did against the air, and what it was fitted on."""

    start: datetime
    end: datetime
    ua_btu_hr_f: float
    rmse_f: float
    delta_t_mean_f: float
    duration_hours: float
    #: The upper-minus-lower gap, and hours since the window's start:
    #: the stratification fit's input.
    gap_hours: np.ndarray = field(repr=False)
    gap_f: np.ndarray = field(repr=False)


def fit_window(
    history: pd.DataFrame,
    window: Interval,
    thermal_mass_btu_f: float,
) -> StandbyWindow | None:
    """The UA of one quiet ``window``: the tank's mean on a 5-minute
    grid, Euler-integrated as ``dT/dt = -(UA / mass)(T - air)`` from its
    first value, the UA minimising the squared error. None with under an
    hour of usable samples or no air."""
    start, end = window
    if "air_f" not in history.columns:
        return None
    index = pd.DatetimeIndex(history.index)
    rows = history.loc[
        (index >= start) & (index < end), ["upper_f", "lower_f", "air_f"]
    ]
    if rows.empty:
        return None
    wide = (
        rows.astype(float)
        .resample("5min")
        .mean()
        .interpolate(method="time", limit=6)
        .dropna()
    )
    if len(wide) < 12:
        return None
    tank = ((wide["upper_f"] + wide["lower_f"]) / 2.0).to_numpy(dtype=float)
    air = wide["air_f"].to_numpy(dtype=float)
    seconds = (wide.index - wide.index[0]).total_seconds()
    dt_h = np.diff(np.asarray(seconds, dtype=float)) / 3600.0

    def walk(ua: float) -> np.ndarray:
        out = np.zeros(len(tank))
        out[0] = tank[0]
        rate = ua / thermal_mass_btu_f
        for i in range(len(dt_h)):
            out[i + 1] = out[i] - rate * (out[i] - air[i]) * dt_h[i]
        return out

    def sse(ua: float) -> float:
        return float(np.sum((walk(ua) - tank) ** 2))

    found = cast(
        OptimizeResult,
        minimize_scalar(
            sse,
            bounds=UA_SEARCH_BOUNDS,
            method="bounded",
        ),
    )
    if not found.success:
        return None
    ua = float(found.x)
    rmse = float(np.sqrt(np.mean((walk(ua) - tank) ** 2)))
    return StandbyWindow(
        start=start,
        end=end,
        ua_btu_hr_f=ua,
        rmse_f=rmse,
        delta_t_mean_f=float(np.mean(tank - air)),
        duration_hours=(end - start).total_seconds() / 3600.0,
        gap_hours=np.concatenate(([0.0], np.cumsum(dt_h))),
        gap_f=(wide["upper_f"] - wide["lower_f"]).to_numpy(dtype=float),
    )


def fit_ua_law(
    delta_t: Sequence[float],
    ua: Sequence[float],
    weights: Sequence[float] | None = None,
    ref_delta_t: float = UA_REF_DELTA_T_F,
) -> tuple[float, float]:
    """``(ua_ref, exponent)`` of ``UA(dT) = ua_ref (dT / ref)^exponent``
    from per-window fits: weighted least squares in log space; the
    weighted mean and 0 (constant UA) when the windows do not span two
    20 °F bands, or the exponent clamps to 0."""
    dt = np.asarray(delta_t, dtype=float)
    u = np.asarray(ua, dtype=float)
    w = np.ones_like(dt) if weights is None else np.asarray(weights, float)
    if dt.shape != u.shape or dt.shape != w.shape:
        raise ValueError("delta_t, ua and weights must be the same length")
    usable = (u > 0.0) & (dt > 0.0) & (w > 0.0)
    dt, u, w = dt[usable], u[usable], w[usable]
    if len(dt) == 0:
        raise ValueError("no usable windows to fit a UA law from")
    mean = float(np.average(u, weights=w))
    bands = np.floor(dt / _BAND_WIDTH_F)
    if len(dt) < _MIN_WINDOWS_FOR_LAW or len(np.unique(bands)) < (
        _MIN_BANDS_FOR_LAW
    ):
        return mean, 0.0
    x = np.log(np.maximum(dt, UA_MIN_DELTA_T_F) / ref_delta_t)
    y = np.log(u)
    slope, intercept = np.polyfit(x, y, deg=1, w=np.sqrt(w))
    exponent = float(slope)
    lo, hi = UA_EXPONENT_BOUNDS
    if not lo <= exponent <= hi:
        exponent = float(np.clip(exponent, lo, hi))
        if exponent == 0.0:
            return mean, 0.0
        intercept = float(np.average(y - exponent * x, weights=w))
    return float(np.exp(intercept)), exponent


def fit_gap_tau(
    windows: Sequence[tuple[np.ndarray, np.ndarray]],
    min_start_gap_f: float = MIN_GAP_FIT_START_F,
    min_windows: int = MIN_GAP_FIT_WINDOWS,
) -> tuple[float | None, int]:
    """The time constant the stratification gap relaxes on, hours: one
    constant minimising the squared gap error of ``gap_0 exp(-t/tau)``
    pooled over every sample of every window starting with a gap of at
    least ``min_start_gap_f``. ``(None, n)`` with fewer than
    ``min_windows``."""
    used = [
        (t, g)
        for t, g in windows
        if len(g) >= 2 and np.isfinite(g).all() and g[0] >= min_start_gap_f
    ]
    if len(used) < min_windows:
        return None, len(used)

    def sse(log_tau: float) -> float:
        tau = float(np.exp(log_tau))
        return sum(
            float(np.sum((g - g[0] * np.exp(-t / tau)) ** 2)) for t, g in used
        )

    low, high = GAP_TAU_BOUNDS_HOURS
    found = cast(
        OptimizeResult,
        minimize_scalar(
            sse, bounds=(np.log(low), np.log(high)), method="bounded"
        ),
    )
    return float(np.exp(found.x)), len(used)


@dataclass(frozen=True)
class StandbyFit:
    """The standby fits: the windows kept, the law, the gap's constant,
    and what each rests on."""

    windows: tuple[StandbyWindow, ...]
    #: Windows found quiet, and those whose fit was dropped (too short,
    #: no air, or a poor fit).
    n_quiet: int
    n_dropped: int
    ua_ref: float | None
    ua_exponent: float | None
    tau_gap_hours: float | None
    n_gap_windows: int
    #: The quiet test: ``meter`` with draws and circulation recorded,
    #: ``dhw_in_use`` without them.
    quiet_by: str


def fit_standby(
    history: pd.DataFrame,
    thermal_mass_btu_f: float,
    *,
    min_quiet_hours: float = MIN_QUIET_HOURS,
    settle_minutes: float = SETTLE_MINUTES,
) -> StandbyFit:
    """The standby loss law and the gap's time constant from the
    history's quiet windows."""
    quiet = quiet_windows(history, min_quiet_hours, settle_minutes)
    kept: list[StandbyWindow] = []
    for window in quiet:
        fit = fit_window(history, window, thermal_mass_btu_f)
        if fit is not None and fit.rmse_f < MAX_WINDOW_RMSE_F:
            kept.append(fit)
    ua_ref = exponent = None
    if kept:
        ua_ref, exponent = fit_ua_law(
            [w.delta_t_mean_f for w in kept],
            [w.ua_btu_hr_f for w in kept],
            # A long cold soak constrains the decay far better than a
            # short window.
            [w.duration_hours for w in kept],
        )
    tau, n_gap = fit_gap_tau([(w.gap_hours, w.gap_f) for w in kept])
    tier1 = any(c in history.columns for c in ("drawing", "circulating"))
    return StandbyFit(
        windows=tuple(kept),
        n_quiet=len(quiet),
        n_dropped=len(quiet) - len(kept),
        ua_ref=ua_ref,
        ua_exponent=exponent,
        tau_gap_hours=tau,
        n_gap_windows=n_gap,
        quiet_by="meter" if tier1 else "dhw_in_use",
    )


# ── the compressor: constant and evaporator approach ─────────────────

#: Starting point and bounds of the compressor fit: an unbounded fit on
#: a mixed-season corpus collapsed the approach toward 0 °F to absorb
#: model error, so a fit on a bound is reported, not trusted.
INITIAL_K = 0.05
INITIAL_APPROACH_F = 12.0
K_BOUNDS = (0.02, 0.3)
APPROACH_BOUNDS = (4.0, 20.0)
_BOUND_HIT_RTOL = 0.01
#: The recoveries fitted, by duration, minutes.
MIN_RECOVERY_MINUTES = 15.0
MAX_RECOVERY_MINUTES = 480.0
#: Fewer recoveries than this and nothing is fitted.
MIN_RECOVERIES = 5
#: With this many, the latest ``HELDOUT_FRACTION`` (at least
#: ``MIN_HELDOUT``) are held out to score the fit.
MIN_RECOVERIES_FOR_SPLIT = 10
HELDOUT_FRACTION = 0.20
MIN_HELDOUT = 2


@dataclass(frozen=True)
class CompressorFit:
    """The compressor fit, and how well it scores: the mean absolute
    error on the recoveries fitted and on those held out."""

    compressor_constant: float
    evap_approach_f: float
    mae_minutes: float
    heldout_mae_minutes: float | None
    n_fitted: int
    n_heldout: int
    #: The fit landed on a bound: the model could not fit the corpus,
    #: and the values are pinned, not converged.
    hit_bounds: bool
    two_zone: bool


def fit_compressor(
    recoveries: pd.DataFrame,
    compressor: CompressorParams,
    loss: LossParams,
    *,
    two_zone: bool = True,
) -> CompressorFit | None:
    """``compressor_constant`` and ``evap_approach_f`` minimising the
    squared error of the physics' durations against recorded ones.

    ``recoveries``: one row per heat-pump recovery, with
    ``t_start_lower``, ``delta_t_lower`` (the lower zone's rise to its
    target), ``t_amb_mean`` (the air over it, °F) and
    ``duration_minutes``; optionally ``h_amb_start`` (%RH; 50 without),
    ``stratification_gap`` (upper minus lower at the start; without it
    the fit falls back to the one-zone integrator, so the constant stays
    the one the simulation will use) and ``start_time`` (to hold out the
    latest). None with fewer than ``MIN_RECOVERIES`` usable.
    """
    need = ["t_start_lower", "delta_t_lower", "t_amb_mean", "duration_minutes"]
    if any(c not in recoveries.columns for c in need):
        return None
    df = recoveries.dropna(subset=need)
    minutes = df["duration_minutes"]
    df = df.loc[
        (minutes >= MIN_RECOVERY_MINUTES) & (minutes <= MAX_RECOVERY_MINUTES)
    ].copy()
    if len(df) < MIN_RECOVERIES:
        return None
    if "start_time" in df.columns:
        df = df.sort_values("start_time").reset_index(drop=True)
    n = len(df)
    n_held = (
        max(MIN_HELDOUT, round(n * HELDOUT_FRACTION))
        if n >= MIN_RECOVERIES_FOR_SPLIT
        else 0
    )
    fit_df, held_df = df.iloc[: n - n_held], df.iloc[n - n_held :]
    has_gaps = "stratification_gap" in df.columns and bool(
        df["stratification_gap"].notna().all()
    )
    two_zone = two_zone and has_gaps

    def columns(frame: pd.DataFrame) -> tuple[np.ndarray, ...]:
        rows = len(frame)
        return (
            np.asarray(frame["t_start_lower"], dtype=float),
            np.asarray(
                frame["t_start_lower"] + frame["delta_t_lower"], dtype=float
            ),
            np.asarray(frame["t_amb_mean"], dtype=float),
            np.asarray(
                frame["h_amb_start"]
                if "h_amb_start" in frame.columns
                else np.full(rows, 50.0),
                dtype=float,
            ),
            np.asarray(
                frame["stratification_gap"] if has_gaps else np.zeros(rows),
                dtype=float,
            ),
            np.asarray(frame["duration_minutes"], dtype=float),
        )

    def predicted(cols: tuple[np.ndarray, ...], k: float, approach: float):
        start, target, air, humidity, gap, _ = cols
        return np.array(
            [
                predict_physics_detailed(
                    t_start_lower=float(start[i]),
                    hp_lower_off=float(target[i]),
                    t_amb_mean=float(air[i]),
                    compressor_constant=k,
                    evap_approach_f=approach,
                    compressor=compressor,
                    loss=loss,
                    h_amb_start=float(humidity[i]),
                    ua_btu_hr_f=loss.ua_btu_hr_f,
                    ua_exponent=loss.ua_exponent,
                    ua_ref_delta_t=loss.ua_ref_delta_t_f,
                    stratification_gap=float(gap[i]),
                    two_zone=two_zone,
                ).minutes
                for i in range(len(start))
            ]
        )

    fit_cols = columns(fit_df)

    def objective(x: np.ndarray) -> float:
        k, approach = float(x[0]), float(x[1])
        if not (
            K_BOUNDS[0] <= k <= K_BOUNDS[1]
            and APPROACH_BOUNDS[0] <= approach <= APPROACH_BOUNDS[1]
        ):
            return 1e12
        return float(
            np.sum((predicted(fit_cols, k, approach) - fit_cols[5]) ** 2)
        )

    found = minimize(
        objective,
        x0=np.array([INITIAL_K, INITIAL_APPROACH_F]),
        method="Nelder-Mead",
        bounds=[K_BOUNDS, APPROACH_BOUNDS],
        options={"xatol": 1e-5, "fatol": 1.0, "maxiter": 2000},
    )
    k, approach = float(found.x[0]), float(found.x[1])
    hit = any(
        abs(value - bound) <= _BOUND_HIT_RTOL * max(abs(bound), 1e-9)
        for value, bounds in ((k, K_BOUNDS), (approach, APPROACH_BOUNDS))
        for bound in bounds
    )
    mae = float(np.mean(np.abs(predicted(fit_cols, k, approach) - fit_cols[5])))
    held_mae = None
    if n_held:
        held_cols = columns(held_df)
        held_mae = float(
            np.mean(np.abs(predicted(held_cols, k, approach) - held_cols[5]))
        )
    return CompressorFit(
        compressor_constant=k,
        evap_approach_f=approach,
        mae_minutes=mae,
        heldout_mae_minutes=held_mae,
        n_fitted=len(fit_df),
        n_heldout=n_held,
        hit_bounds=hit,
        two_zone=two_zone,
    )


# ── the recoveries a compressor fit learns from ──────────────────────

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
MIN_MINUTES_PER_F = 2.0
MAX_MINUTES_PER_F = 20.0
MAX_RECOVERY_LABEL_MINUTES = 600.0
#: A recovery is read every ``SNAPSHOT_EVERY`` while at least
#: ``SNAPSHOT_MIN_REMAINING`` of it remains, and fitted from the reading
#: with the coldest lower probe, timed from there.
SNAPSHOT_EVERY = timedelta(minutes=30)
SNAPSHOT_MIN_REMAINING = timedelta(minutes=15)


def _asof(
    values: np.ndarray, seconds: np.ndarray, at: datetime
) -> float | None:
    """The last finite value at or before ``at`` (``seconds`` its
    instants, sorted); the first if ``at`` precedes them; None if there
    is none."""
    ok = np.isfinite(values)
    if not ok.any():
        return None
    finite, stamps = values[ok], seconds[ok]
    pos = int(np.searchsorted(stamps, at.timestamp(), side="right")) - 1
    return float(finite[max(pos, 0)])


def _floats(history: pd.DataFrame, name: str) -> np.ndarray:
    """A column as floats, NaN throughout when the history lacks it."""
    if name not in history.columns:
        return np.full(len(history), np.nan)
    return history[name].to_numpy(dtype=float, na_value=np.nan)


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


#: Draws this long before a recovery leave its start reading short of
#: their cold water: a cycle is draw-free only with none from this long
#: before it to its end.
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
)


def _energy_wh(
    watts: np.ndarray, seconds: np.ndarray, start: datetime, end: datetime
) -> float | None:
    """A power series' step integral over ``[start, end]``, Wh, each
    reading held until the next; with none in force at ``start``, the
    first after it back-filled to it (the compressor's first report).
    None with no reading, which is not zero energy."""
    ok = np.isfinite(watts)
    w, t = watts[ok], seconds[ok]
    a, b = start.timestamp(), end.timestamp()
    if b <= a or not len(w):
        return None
    before = t <= a
    inside = (t > a) & (t < b)
    if before.any():
        first = float(w[before][-1])
        times, values = t[inside], w[inside]
    elif inside.any():
        first = float(w[inside][0])
        times, values = t[inside][1:], w[inside][1:]
    else:
        return None
    edges = np.concatenate(([a], times, [b]))
    levels = np.concatenate(([first], values))
    return float(np.sum(levels * np.diff(edges)) / 3600.0)


def snapshots(
    history: pd.DataFrame, *, air: str = "heater_air_f"
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
    ``air="air_f"``); ``h_amb_start`` (50 without humidity); ``reached``
    (the lower probe came within ``REACHED_TOLERANCE_F`` of the target
    before the run ended); ``metered_input_wh`` (``power_w`` integrated
    from the snapshot to the end, None without it); ``t_lower_end``,
    ``t_upper_end`` (the probes at the end); and ``draw_free`` (no water
    in use from ``DRAW_LEAD`` before the start to the end).
    """
    if history.empty:
        return pd.DataFrame(columns=list(_SNAPSHOT_COLUMNS))
    when = _instants(history)
    index = pd.DatetimeIndex(history.index)
    seconds = np.array([t.timestamp() for t in when])
    lower_f, upper_f = _floats(history, "lower_f"), _floats(history, "upper_f")
    target_f, air_f = _floats(history, "target_f"), _floats(history, air)
    humidity_pct = _floats(history, "humidity_pct")
    energy_wh = _floats(history, "energy_to_setpoint_wh")
    power_w = _floats(history, "power_w")
    on = history["compressor_on"].fillna(False).astype(bool).to_numpy()
    element = history["element_on"].fillna(False).astype(bool).to_numpy()
    excluded = (
        history["excluded"].fillna(False).astype(bool).to_numpy()
        if "excluded" in history.columns
        else np.zeros(len(history), dtype=bool)
    )
    tier1 = [c for c in ("drawing", "circulating") if c in history.columns]
    water = np.zeros(len(history), dtype=bool)
    for column in tier1 or ["dhw_in_use"]:
        if column in history.columns:
            water |= history[column].fillna(False).astype(bool).to_numpy()
    rows: list[dict[str, object]] = []
    for n, (start, end) in enumerate(_on_intervals(when, on)):
        span = (index >= start - PRE_RECOVERY_LOOKBACK) & (index <= end)
        if element[span].any() or excluded[span].any():
            continue
        target = _asof(target_f, seconds, start)
        if target is None:
            continue
        before, after = INTERRUPTED_WINDOW
        at_end = energy_wh[(index >= end + before) & (index <= end + after)]
        at_end = at_end[np.isfinite(at_end)]
        if len(at_end) and at_end[-1] > INTERRUPTED_WH:
            continue
        inside = (index >= start) & (index <= end)
        reached = bool(np.any(lower_f[inside] >= target - REACHED_TOLERANCE_F))
        cycle = (index >= start) & (index < end)
        if not cycle.any():
            continue
        c_seconds, c_air = seconds[cycle], air_f[cycle]
        lower_end = _asof(lower_f[cycle], c_seconds, end)
        upper_end = _asof(upper_f[cycle], c_seconds, end)
        lead = (index >= start - DRAW_LEAD) & (index <= end)
        draw_free = not water[lead].any()
        for at in _snapshots(start, end):
            lower = _asof(lower_f[cycle], c_seconds, at)
            upper = _asof(upper_f[cycle], c_seconds, at)
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
                else _asof(c_air, c_seconds, at)
            )
            if air_mean is None:
                continue
            humidity = _asof(humidity_pct[cycle], c_seconds, at)
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
                    "h_amb_start": 50.0 if humidity is None else humidity,
                    "reached": reached,
                    "metered_input_wh": _energy_wh(
                        power_w[cycle], c_seconds, at, end
                    ),
                    "t_lower_end": lower_end,
                    "t_upper_end": upper_end,
                    "draw_free": draw_free,
                }
            )
    return pd.DataFrame(rows, columns=list(_SNAPSHOT_COLUMNS))


def recoveries(
    history: pd.DataFrame, *, air: str = "heater_air_f"
) -> pd.DataFrame:
    """One row per recovery, as ``fit_compressor`` takes them: of a
    cycle's ``snapshots``, the one with the coldest lower probe (the
    earliest of equals), timed from there. A draw that takes the probe
    below where it started moves the row to after the draw; without a
    dip it is the start. Only reached recoveries teach a duration: the
    heater stops some short by design, and those never reach the
    instant the fit models."""
    rows = snapshots(history, air=air)
    if rows.empty:
        return rows
    order = rows.sort_values(
        ["cycle", "t_start_lower", "offset_minutes"], kind="stable"
    )
    return order.groupby("cycle", sort=True).head(1).reset_index(drop=True)


def with_standby(params: HeaterParams, fit: StandbyFit) -> HeaterParams:
    """``params`` with the standby fit's values where it had them."""
    loss, tank = params.loss, params.tank
    if fit.ua_ref is not None and fit.ua_exponent is not None:
        loss = replace(
            loss, ua_btu_hr_f=fit.ua_ref, ua_exponent=fit.ua_exponent
        )
    if fit.tau_gap_hours is not None:
        tank = replace(tank, stratification_gap_tau_h=fit.tau_gap_hours)
    return replace(params, loss=loss, tank=tank)


def with_compressor(params: HeaterParams, fit: CompressorFit) -> HeaterParams:
    """``params`` with the compressor fit's values, unless it is pinned
    on a bound."""
    if fit.hit_bounds:
        return params
    return replace(
        params,
        compressor=replace(
            params.compressor,
            compressor_constant=fit.compressor_constant,
            evap_approach_f=fit.evap_approach_f,
            two_zone=fit.two_zone,
        ),
    )


# ── power and COP, against the heater's own power readings ───────────

#: Fewer cycles than this and neither power fit is made.
MIN_POWER_EVENTS = 10
#: Shorter cycles are the meter's resolution, Wh.
MIN_COP_METERED_WH = 300.0
#: The lift (tank mean less the air, °F) the COP's lift term is
#: referred to, and the coefficients tried, per °F.
COP_LIFT_REF_F = 62.0
COP_LIFT_GRID = tuple(i * 0.0005 for i in range(61))


def _starts(rows: pd.DataFrame) -> pd.DataFrame:
    """Each cycle's first snapshot: the power fits read a cycle whole."""
    if rows.empty:
        return rows
    first = rows.loc[rows["offset_minutes"] == 0.0]
    return first.drop_duplicates(subset=["cycle"])


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """A frame's rows as plain mappings."""
    return cast(list[dict[str, Any]], frame.to_dict("records"))


def path_to_end(
    row: Mapping[str, Any], params: HeaterParams
) -> PhysicsPath | None:
    """The integrator's path over the lift a cycle made: to where its
    lower probe got (``t_lower_end``), not its target, so a cycle cut
    short is compared over the heating it did. None when nothing was
    heated or the walk did not finish."""
    start = float(row["t_start_lower"])
    target = start + float(row["delta_t_lower"])
    end = row.get("t_lower_end")
    if end is not None and not pd.isna(end):
        if float(end) <= start:
            return None
        target = min(target, float(end))
    gap = row.get("stratification_gap")
    result = predict_physics_detailed(
        t_start_lower=start,
        hp_lower_off=target,
        t_amb_mean=float(row["t_amb_mean"]),
        compressor_constant=params.compressor.compressor_constant,
        evap_approach_f=params.compressor.evap_approach_f,
        compressor=params.compressor,
        loss=params.loss,
        h_amb_start=float(row.get("h_amb_start", 50.0)),
        ua_btu_hr_f=params.loss.ua_btu_hr_f,
        ua_exponent=params.loss.ua_exponent,
        ua_ref_delta_t=params.loss.ua_ref_delta_t_f,
        stratification_gap=0.0 if gap is None else float(gap),
        two_zone=params.compressor.two_zone,
        record_path=True,
    )
    if not result.converged or result.path is None or result.minutes <= 0.0:
        return None
    return result.path


@dataclass(frozen=True)
class PowerFit:
    """Input power and apparent COP against the heater's own readings.

    ``power_scale``: metered energy over the integrator's mean power for
    each cycle's real duration, a ratio of sums. ``cop_scale``,
    ``startup_wh`` and ``cop_lift_coeff``: ``metered = startup + heat /
    (scale x COP x exp(-coeff (lift - COP_LIFT_REF_F)))``, the heat what
    the tank kept. None where too few cycles carried the figures.
    """

    power_scale: float | None
    n_power: int
    cop_scale: float | None
    startup_wh: float | None
    cop_lift_coeff: float | None
    lead_share: float | None
    n_cop: int


def fit_power_scale(
    rows: pd.DataFrame, params: HeaterParams
) -> tuple[float | None, int]:
    """``(metered / modelled, cycles)``: each cycle charged at the
    integrator's own mean power for its real duration, so both sides
    are energy over the same clock. ``(None, n)`` with fewer than
    ``MIN_POWER_EVENTS``."""
    metered_total = modelled_total = 0.0
    n = 0
    for row in _records(_starts(rows)):
        raw = row["metered_input_wh"]
        if raw is None or pd.isna(raw):
            continue
        metered = float(raw)
        if not math.isfinite(metered) or metered <= 0.0:
            continue
        path = path_to_end(row, params)
        real_minutes = float(row["duration_minutes"])
        if path is None or not real_minutes > 0.0:
            continue
        physics_minutes = path.elapsed_s[-1] / 60.0
        power_w = path.input_btu[-1] / BTU_PER_WH / (physics_minutes / 60)
        modelled = power_w * real_minutes / 60
        if not math.isfinite(modelled) or modelled <= 0.0:
            continue
        metered_total += metered
        modelled_total += modelled
        n += 1
    if n < MIN_POWER_EVENTS or modelled_total <= 0.0:
        return None, n
    return metered_total / modelled_total, n


def solve_cop_scale(
    heat_wh: np.ndarray,
    modelled_cop: np.ndarray,
    metered_wh: np.ndarray,
    lead_wh: np.ndarray | None = None,
) -> tuple[float, float, float] | None:
    """``(scale, startup_wh, lead_share)`` for ``metered = startup +
    (heat + lead_share x lead) / (scale x COP)``, by least squares
    weighted ``1 / metered``; ``startup`` at least 0, ``lead_share`` in
    [0, 1]."""
    h, c, e = (
        np.asarray(v, dtype=float) for v in (heat_wh, modelled_cop, metered_wh)
    )
    x_lead = np.zeros_like(h) if lead_wh is None else np.asarray(lead_wh, float)
    w = np.sqrt(1.0 / e)

    def solve(
        intercept: bool, share: float | None
    ) -> tuple[float, float, float] | None:
        # share None: fitted; a number: held there.
        heat = h + (0.0 if share is None else share) * x_lead
        cols = [heat / c]
        if share is None:
            cols.append(x_lead / c)
        if intercept:
            cols.insert(0, np.ones_like(h))
        coef, *_ = np.linalg.lstsq(
            np.column_stack(cols) * w[:, None], e * w, rcond=None
        )
        startup = float(coef[0]) if intercept else 0.0
        inv = float(coef[1 if intercept else 0])
        if not inv > 0.0:
            return None
        got = share if share is not None else float(coef[-1]) / inv
        return 1.0 / inv, startup, got

    fits_lead = bool(np.any(x_lead > 0.0))
    for intercept in (True, False):
        solved = solve(intercept, None if fits_lead else 0.0)
        if solved is None:
            return None
        if fits_lead and not 0.0 <= solved[2] <= 1.0:
            solved = solve(intercept, min(1.0, max(0.0, solved[2])))
            if solved is None:
                return None
        if solved[1] >= 0.0:
            return solved
    return None


def solve_cop_fit(
    heat_wh: Sequence[float],
    modelled_cop: Sequence[float],
    metered_wh: Sequence[float],
    lead_wh: Sequence[float] | None,
    lift_f: Sequence[float],
) -> tuple[float, float, float, float] | None:
    """``(scale, startup_wh, lead_share, lift_coeff)``: ``solve_cop_scale``
    at each ``COP_LIFT_GRID`` coefficient, the least weighted squared
    error in the meter kept."""
    c0 = np.asarray(modelled_cop, dtype=float)
    lift = np.asarray(lift_f, dtype=float)
    e = np.asarray(metered_wh, dtype=float)
    h = np.asarray(heat_wh, dtype=float)
    x_lead = np.zeros_like(h) if lead_wh is None else np.asarray(lead_wh, float)
    best: tuple[float, tuple[float, float, float, float]] | None = None
    for gamma in COP_LIFT_GRID:
        c = c0 * np.exp(-gamma * (lift - COP_LIFT_REF_F))
        solved = solve_cop_scale(h, c, e, x_lead)
        if solved is None:
            continue
        a, startup, share = solved
        pred = startup + (h + share * x_lead) / (a * c)
        sse = float((((pred - e) ** 2) / e).sum())
        if best is None or sse < best[0]:
            best = (sse, (a, startup, share, gamma))
    return None if best is None else best[1]


#: The heat a cycle's draws and circulation took, Wh: None when it is
#: not known, which rules the cycle out (an unknown withdrawal is not a
#: zero one).
Withdrawn = Callable[[Mapping[str, Any]], float | None]


def draw_free_withdrawn(row: Mapping[str, Any]) -> float | None:
    """Without a meter: nothing withdrawn from a cycle with no water in
    use from ``DRAW_LEAD`` before it to its end, and unknown otherwise."""
    return 0.0 if bool(row.get("draw_free")) else None


def fit_cop_scale(
    rows: pd.DataFrame,
    params: HeaterParams,
    *,
    withdrawn: Withdrawn = draw_free_withdrawn,
    lead: Withdrawn | None = None,
) -> tuple[tuple[float, float, float, float] | None, int]:
    """``((scale, startup_wh, lead_share, lift_coeff), cycles)`` for the
    apparent COP, the heat a cycle stored (the full tank's mass times
    the rise of the probes' mean) plus what ``withdrawn`` says draws
    took during it, and ``lead`` those just before it, whose cold water
    the start reading had not yet seen. ``(None, n)`` with fewer than
    ``MIN_POWER_EVENTS``.

    Without a meter the default keeps only the cycles no water was
    drawn around: the heat drawn during a cycle is otherwise missing
    from its heat and pulls the scale low.
    """
    needed = [
        "metered_input_wh",
        "t_start_lower",
        "t_start_upper",
        "t_lower_end",
        "t_upper_end",
    ]
    if not set(needed) <= set(rows.columns):
        return None, 0
    wh_per_f = params.tank.thermal_mass_btu_f / BTU_PER_WH
    heat: list[float] = []
    before: list[float] = []
    cop: list[float] = []
    metered_wh: list[float] = []
    lift: list[float] = []
    for row in _records(_starts(rows)):
        if any(row[c] is None or pd.isna(row[c]) for c in needed):
            continue
        metered = float(row["metered_input_wh"])
        if metered < MIN_COP_METERED_WH:
            continue
        stored = wh_per_f * (
            (float(row["t_lower_end"]) + float(row["t_upper_end"])) / 2
            - (float(row["t_start_lower"]) + float(row["t_start_upper"])) / 2
        )
        # No screen on what was stored: that would select on the outcome
        # being fitted.
        took = withdrawn(row)
        if took is None or not math.isfinite(took):
            continue
        lead_wh = 0.0 if lead is None else lead(row)
        if lead_wh is None or not math.isfinite(lead_wh):
            continue
        path = path_to_end(row, params)
        if path is None:
            continue
        modelled = path_cop(
            path,
            0.0,
            path.elapsed_s[-1],
            params.compressor.two_zone,
            float(row["t_start_upper"]),
        )
        if modelled is None or not math.isfinite(modelled) or modelled <= 0:
            continue
        air = row.get("t_amb_mean")
        if air is None or pd.isna(air):
            continue
        mean = (
            float(row["t_lower_end"])
            + float(row["t_upper_end"])
            + float(row["t_start_lower"])
            + float(row["t_start_upper"])
        ) / 4
        heat.append(stored + took)
        before.append(lead_wh)
        cop.append(modelled)
        metered_wh.append(metered)
        lift.append(mean - float(air))
    n = len(heat)
    if n < MIN_POWER_EVENTS:
        return None, n
    return solve_cop_fit(heat, cop, metered_wh, before, lift), n


def fit_power(
    rows: pd.DataFrame,
    params: HeaterParams,
    *,
    withdrawn: Withdrawn = draw_free_withdrawn,
    lead: Withdrawn | None = None,
) -> PowerFit:
    """Both power fits on ``snapshots`` rows, every cycle whether or not
    it reached its target (a capped cycle is as good a sample of heat
    per Wh as any), on ``params``' compressor and loss."""
    scale, n_power = fit_power_scale(rows, params)
    cop, n_cop = fit_cop_scale(rows, params, withdrawn=withdrawn, lead=lead)
    return PowerFit(
        power_scale=scale,
        n_power=n_power,
        cop_scale=None if cop is None else cop[0],
        startup_wh=None if cop is None else cop[1],
        cop_lift_coeff=None if cop is None else cop[3],
        lead_share=None if cop is None else cop[2],
        n_cop=n_cop,
    )


def with_power(params: HeaterParams, fit: PowerFit) -> HeaterParams:
    """``params`` with the power fit's values where it had them."""
    power = params.power
    if fit.power_scale is not None:
        power = replace(power, power_scale=fit.power_scale)
    if fit.cop_scale is not None:
        power = replace(
            power,
            cop_scale=fit.cop_scale,
            startup_wh=cast(float, fit.startup_wh),
            cop_lift_coeff=cast(float, fit.cop_lift_coeff),
            cop_lift_ref_f=COP_LIFT_REF_F,
        )
    return replace(params, power=power)


@dataclass(frozen=True)
class Calibration:
    """A heater's calibration: the parameters, and the fits behind them
    (None where a fit had too little to go on)."""

    params: HeaterParams
    standby: StandbyFit
    compressor: CompressorFit | None
    #: None when the compressor was not fitted or is pinned on a bound:
    #: power is scaled against the compressor the simulation will run.
    power: PowerFit | None
    #: The recoveries found, reached or not.
    recoveries: pd.DataFrame = field(repr=False)


def calibrate(
    history: pd.DataFrame,
    base: HeaterParams,
    *,
    recovery_air: str = "heater_air_f",
    withdrawn: Withdrawn = draw_free_withdrawn,
    lead: Withdrawn | None = None,
) -> Calibration:
    """``base`` refitted on ``history``: the standby loss law and the
    gap's time constant from its quiet windows, then the compressor on
    its reached recoveries, against the loss just fitted (as the
    simulation will run it), then input power and COP against the
    ``power_w`` readings, on that compressor. A part without the
    evidence keeps ``base``'s value; a compressor fit pinned on a bound
    is reported but not applied, and no power is fitted on it.
    ``withdrawn`` and ``lead`` give the COP fit the heat a meter saw
    drawn (``fit_cop_scale``); without them it keeps draw-free
    cycles."""
    standby = fit_standby(history, base.tank.thermal_mass_btu_f)
    params = with_standby(base, standby)
    rows = snapshots(history, air=recovery_air)
    found = recoveries(history, air=recovery_air)
    reached = found.loc[found["reached"].astype(bool)] if len(found) else found
    compressor = fit_compressor(reached, params.compressor, params.loss)
    power = None
    if compressor is not None and not compressor.hit_bounds:
        params = with_compressor(params, compressor)
        power = fit_power(rows, params, withdrawn=withdrawn, lead=lead)
        params = with_power(params, power)
    return Calibration(params, standby, compressor, power, found)


# ── readiness evidence, from metered draws ─────────────────────────

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
    when = _instants(frame)
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


Evidence = tuple[tuple[float, float, float], ...]


def frontier(points: Sequence[tuple[float, float, float]]) -> Evidence:
    """``(upper, lower, gallons)`` points less every one another beats
    from a no-better state: it can never be the answer, since the other
    always qualifies too. Sorted."""
    keep = []
    for i, (u, lo, g) in enumerate(points):
        beaten = any(
            j != i
            and u2 <= u
            and l2 <= lo
            and g2 >= g
            and (u2, l2, g2) != (u, lo, g)
            for j, (u2, l2, g2) in enumerate(points)
        )
        if not beaten:
            keep.append((u, lo, g))
    return tuple(sorted(set(keep)))


def capacity(u: float, lo: float, evidence: Evidence) -> float:
    """The most a no-better state in ``evidence`` delivered."""
    return max(
        (g for u2, l2, g in evidence if u2 <= u and l2 <= lo), default=0.0
    )


@dataclass(frozen=True)
class EvidenceFit:
    """The readiness evidence from metered draws, and how it holds up:
    built from the first 70 % of the heat-pump-off draws, how many of
    the rest crossed the line before the volume it promised them."""

    evidence: Evidence
    n_draws: int
    n_quiet: int
    held_out_crossed: int
    held_out_over: int


def held_out(
    draws: Sequence[CleanDraw], line_f: float = 105.0
) -> tuple[int, int, list[float]]:
    """Evidence from the first 70 % of ``draws``; of the rest, how many
    crossed ``line_f``, how many crossed before the volume promised them,
    and by how much."""
    n = int(len(draws) * 0.7)
    early = tuple(
        (d.u0, d.l0, crossing(d, line_f - 1e-9)[0]) for d in draws[:n]
    )
    crossed = over = 0
    excess: list[float] = []
    for d in draws[n:]:
        got, did = crossing(d, line_f - 1e-9)
        if not did:
            continue
        crossed += 1
        promised = capacity(d.u0, d.l0, early)
        if got < promised:
            over += 1
            excess.append(promised - got)
    return crossed, over, excess


def fit_evidence(
    draws: Sequence[CleanDraw],
    *,
    line_f: float = 105.0,
) -> EvidenceFit:
    """The evidence from ``clean_draws``: the frontier of the
    heat-pump-off draws' demonstrated volumes (``ReadinessParams.
    evidence``) and its held-out check. A bath's volume is measured (a
    fill to the household's level, at the hot side's meter), not
    fitted: ``ReadinessParams.bath_gal``."""
    quiet = [d for d in draws if not d.hp]
    points = [(d.u0, d.l0, demonstrated(d, line_f)) for d in quiet]
    crossed, over, _ = held_out(quiet, line_f)
    return EvidenceFit(
        evidence=frontier(points),
        n_draws=len(draws),
        n_quiet=len(quiet),
        held_out_crossed=crossed,
        held_out_over=over,
    )


def cold_lower_cap(
    draws: Sequence[CleanDraw],
    cutoff_f: float,
    *,
    near_f: float = 110.0,
    from_f: float = 115.0,
) -> float | None:
    """The evidence's cap after a cold lower zone
    (``ReadinessParams.cold_lower_cap_gal``): of the draws from a lower
    probe at or below ``cutoff_f`` that started at ``from_f`` or more and
    took the upper probe to ``near_f``, the smallest volume credited
    before it did, rounded down to half a gallon. None without one.
    ``cutoff_f`` itself (``cold_lower_cutoff_f``) is read off the drops by
    lower-probe band, a judgement, not a fit."""
    hits = [
        crossing(d, near_f)[0]
        for d in draws
        if d.l0 <= cutoff_f and d.u0 >= from_f and crossing(d, near_f)[1]
    ]
    return math.floor(min(hits) * 2) / 2 if hits else None


# ── the heat book's own terms, from re-anchors on full tanks ────────


class RecordedBook:
    """A recorded history booked from each of its quiet anchors, for
    fitting the book's terms (``fit_book_terms``): ``steps`` on a
    contiguous ``sim_adapters.BOOK_GRID_S`` grid. Its anchors are the
    quiet ones only (a full tank, nothing heating, after a clean
    recovery): a recovery ending mid-draw is no place to check the book
    against the probes. Draws are priced at the book's reference, the
    inlet assumed rather than fitted."""

    def __init__(
        self,
        steps: Sequence[BookStep],
        p: BookParams,
        circulation: CirculationParams | None = None,
        *,
        start: datetime,
    ) -> None:
        self.steps = list(steps)
        #: The first step's instant: the grid is contiguous from it.
        self.start = start
        self.p = p
        self.circulation = circulation
        self.seconds = self.steps[0].seconds if self.steps else 10.0
        per_step = self.seconds / 60.0
        self.u = np.array([s.upper_f for s in self.steps])
        self.l = np.array([s.lower_f for s in self.steps])
        self.air = np.array([s.ambient_f for s in self.steps])
        house = np.array([house_gpm(s, circulation) for s in self.steps])
        self.draw = np.where(house > p.draw_gpm, house * per_step, 0.0)
        self.circulated = np.array(
            [
                s.circulation_gpm * per_step if s.circulating else 0.0
                for s in self.steps
            ]
        )
        self.comp = np.array([s.compressor_on for s in self.steps], dtype=bool)
        self.el = np.array([s.element_on for s in self.steps], dtype=bool)
        heating = self.comp | self.el
        disturbed = (self.draw > 0) | (self.circulated > 0)
        clean = np.zeros(len(self.steps), dtype=bool)
        c = was = False
        for i in range(len(self.steps)):
            if heating[i]:
                c = False
            elif was:
                c = True
            if disturbed[i]:
                c = False
            clean[i] = c
            was = bool(heating[i])
        self.anchors = np.where(
            clean & ~heating & (np.abs(self.u - self.l) <= p.uniform_band_f)
        )[0]
        last = np.full(len(self.steps), np.nan)
        last[self.anchors] = self.anchors
        self.last = pd.Series(last).ffill().to_numpy()

    def cum(self, p: BookParams, loss_btu_per_gal: float) -> np.ndarray:
        """The booked heat's running sum from the first step, BTU."""
        h = self.seconds / 3600.0
        delivered = np.minimum(
            self.u, p.delivery_intercept_f + p.delivery_slope * self.u
        )
        e = (
            self.comp
            * (p.hp_btu_per_h + p.hp_btu_per_h_per_f * (self.air - 65.0))
            * h
            + self.el * p.element_w * BTU_PER_WH_BOOK * h
            - self.draw
            * WATER_BTU_PER_GAL_F
            * np.clip(delivered - p.reference_f, 0, None)
            - loss_btu_per_gal * self.circulated
            - p.ua_btu_per_h_f
            * np.clip((self.u + self.l) / 2 - self.air, 0, None)
            * h
        )
        return np.concatenate([[0.0], np.cumsum(np.nan_to_num(e))])

    def at(self, i: int) -> datetime:
        """Step ``i``'s instant."""
        return self.start + timedelta(seconds=i * self.seconds)

    def probe_heat(self, p: BookParams) -> np.ndarray:
        """The heat the probes read, BTU above the reference."""
        return (
            WATER_BTU_PER_GAL_F
            * p.tank_gal
            * ((self.u + self.l) / 2 - p.reference_f)
        )

    def heat(
        self, p: BookParams, loss_btu_per_gal: float
    ) -> tuple[np.ndarray, np.ndarray]:
        """The booked heat at every step from its latest quiet anchor,
        and that anchor's age, hours; NaN before the first."""
        cum, ep = self.cum(p, loss_btu_per_gal), self.probe_heat(p)
        ok = ~np.isnan(self.last)
        la = np.where(ok, self.last, 0).astype(int)
        n = np.arange(len(self.steps))
        e = np.where(ok, ep[la] + cum[n] - cum[la], np.nan)
        return e, np.where(ok, (n - la) * self.seconds / 3600.0, np.nan)

    def reanchors(self, max_h: float = 24.0) -> list[tuple[int, int]]:
        """Pairs of anchors an hour or more apart and at most ``max_h``:
        where the book can be checked against the probes."""
        hour = int(3600 / self.seconds)
        if not len(self.anchors):
            return []
        a = self.anchors[np.r_[True, np.diff(self.anchors) > hour]]
        out = []
        for x in a[1:]:
            prev = self.last[x - 1]
            if not np.isnan(prev) and (
                1 <= (x - prev) * self.seconds / 3600 <= max_h
            ):
                out.append((int(prev), int(x)))
        return out

    def errors(
        self,
        p: BookParams,
        loss_btu_per_gal: float,
        pairs: Sequence[tuple[int, int]],
    ) -> np.ndarray:
        """The book less the probes at each pair's second anchor, BTU."""
        cum, ep = self.cum(p, loss_btu_per_gal), self.probe_heat(p)
        return np.array(
            [ep[a0] + cum[a1] - cum[a0] - ep[a1] for a0, a1 in pairs]
        )


#: BTU per Wh, at the rounding the book was fitted with.
BTU_PER_WH_BOOK = 3.412


@dataclass(frozen=True)
class BookFit:
    """The book's terms fitted on re-anchors, and how well they hold."""

    hp_btu_per_h: float
    hp_btu_per_h_per_f: float
    ua_btu_per_h_f: float
    loss_btu_per_gal: float
    n_pairs: int
    mae_btu: float
    mean_btu: float


def fit_book_terms(
    book: RecordedBook,
    pairs: Sequence[tuple[int, int]],
    base: BookParams,
    loss_btu_per_gal: float = 0.0,
) -> BookFit:
    """The compressor's heat rate and its slope with the air, the
    standby UA and circulation's loss per gallon minimising the mean
    absolute error at ``pairs`` (Nelder-Mead from three starts, within
    plausible bounds)."""

    def terms(x: np.ndarray) -> BookParams:
        return replace(
            base,
            hp_btu_per_h=float(x[0]),
            hp_btu_per_h_per_f=float(x[1]),
            ua_btu_per_h_f=float(x[2]),
        )

    def loss(x: np.ndarray) -> float:
        if not (2000 < x[0] < 9000 and -50 <= x[1] <= 200):
            return 1e12
        if not (0 <= x[2] <= 20 and 0 <= x[3] <= 500):
            return 1e12
        return float(np.mean(np.abs(book.errors(terms(x), float(x[3]), pairs))))

    best = None
    for x0 in ([4300, 130, 4, 50], [3800, 80, 5, 150], [4800, 0, 3, 0]):
        r = minimize(loss, x0, method="Nelder-Mead", options={"maxiter": 3000})
        if best is None or r.fun < best.fun:
            best = r
    assert best is not None
    x = best.x
    err = book.errors(terms(x), float(x[3]), pairs)
    return BookFit(
        hp_btu_per_h=float(x[0]),
        hp_btu_per_h_per_f=float(x[1]),
        ua_btu_per_h_f=float(x[2]),
        loss_btu_per_gal=float(x[3]),
        n_pairs=len(pairs),
        mae_btu=float(np.mean(np.abs(err))) if len(err) else float("nan"),
        mean_btu=float(np.mean(err)) if len(err) else float("nan"),
    )


#: The anchor-age bands the book's error is read in, hours.
ERROR_BANDS_H = ((1, 6), (6, 12), (12, 18), (18, 24), (24, 36), (36, 72))


def book_error_bands(
    book: RecordedBook,
    p: BookParams,
    loss_btu_per_gal: float,
) -> list[tuple[tuple[int, int], int, float, float, float]]:
    """The book's error on re-anchors up to ``history_h`` apart, by
    anchor age: ``((lo, hi), n, MAE, mean, p90 of |error|)``. Long pairs
    are quiet spans by construction (no full tank between), so their
    error reads low."""
    pairs = book.reanchors(p.history_h)
    err = book.errors(p, loss_btu_per_gal, pairs)
    age = np.array([(b - a) * book.seconds / 3600 for a, b in pairs])
    out = []
    for lo_, hi_ in ERROR_BANDS_H:
        m = (age >= lo_) & (age < hi_)
        if not m.any():
            continue
        out.append(
            (
                (lo_, hi_),
                int(m.sum()),
                float(np.mean(np.abs(err[m]))),
                float(np.mean(err[m])),
                float(np.percentile(np.abs(err[m]), 90)),
            )
        )
    return out


def empty_point(
    book: RecordedBook,
    p: BookParams,
    loss_btu_per_gal: float,
    *,
    line_f: float = 105.0,
    core_h: float = 12.0,
) -> tuple[float | None, list[tuple[datetime, float, float]]]:
    """The heat left when a drawdown first takes the upper probe below
    ``line_f``: each such crossing with a draw in the 10 minutes before
    it, an anchor within 24 h, and an hour since the last; the median of
    those with an anchor within ``core_h`` (``BookParams.empty_btu``),
    and every crossing as ``(when, anchor age h, heat BTU)``."""
    heat, age = book.heat(p, loss_btu_per_gal)
    below = book.u < line_f
    lead = int(600 / book.seconds)
    events: list[tuple[datetime, int, float, float]] = []
    for s_ in np.where(below[1:] & ~below[:-1])[0] + 1:
        if np.isnan(heat[s_]) or age[s_] > 24:
            continue
        if book.draw[max(0, s_ - lead) : s_ + 1].sum() == 0:
            continue
        at = book.at(int(s_))
        if events and (at - events[-1][0]).total_seconds() < 3600:
            continue
        events.append((at, int(s_), float(age[s_]), float(heat[s_])))
    core = [e[3] for e in events if e[2] <= core_h]
    return (
        float(np.median(core)) if core else None,
        [(t, a, h) for t, _, a, h in events],
    )


def book_error_btu(
    book: RecordedBook, p: BookParams, loss_btu_per_gal: float
) -> tuple[float | None, float | None]:
    """``(error_btu, aged_error_btu)``, each rounded up to 100 BTU: the
    90th percentile of the book's error pooled over every re-anchor
    pair from an hour to ``max_anchor_age_h`` old, the error being flat
    over that span; and the 18-24 h band's (``book_error_bands``), past
    it. None where there are no pairs."""

    def up(x: float) -> float:
        return math.ceil(x / 100.0) * 100.0

    pairs = book.reanchors(p.history_h)
    age = np.array([(b - a) * book.seconds / 3600 for a, b in pairs])
    err = np.abs(book.errors(p, loss_btu_per_gal, pairs))
    fresh = err[(age >= 1) & (age <= p.max_anchor_age_h)] if len(err) else err
    aged = err[(age >= 18) & (age < 24)] if len(err) else err
    return (
        up(float(np.percentile(fresh, 90))) if len(fresh) else None,
        up(float(np.percentile(aged, 90))) if len(aged) else None,
    )


def withheld_btu(
    book: RecordedBook, p: BookParams, inlet_f: float | None = None
) -> np.ndarray:
    """The cold region's withheld heat at every step: ``Booked.step``
    walked from each quiet anchor, as a served book walks it."""
    anchor = np.zeros(len(book.steps), dtype=bool)
    anchor[book.anchors] = True
    ref = p.reference_f if inlet_f is None else inlet_f
    out = np.zeros(len(book.steps))
    b = Booked(0.0, 0.0, ref, cold_f=p.reference_f)
    for i, st in enumerate(book.steps):
        if anchor[i]:
            b = Booked(0.0, 0.0, ref, cold_f=p.reference_f)
        if math.isnan(st.upper_f) or math.isnan(st.lower_f):
            out[i] = out[i - 1] if i else 0.0
            continue
        b = b.step(replace(st, inlet_f=ref), p, book.circulation)
        out[i] = b.withheld_btu(p)
    return out


def zone_empty_point(
    book: RecordedBook,
    p: BookParams,
    loss_btu_per_gal: float,
    *,
    line_f: float = 105.0,
    core_h: float = 12.0,
) -> float | None:
    """``empty_point`` in the drawable frame (``BookParams.
    zone_empty_btu``): the median, at the same core crossings, of the
    booked heat less what the cold region withholds."""
    _, events = empty_point(book, p, loss_btu_per_gal, line_f=line_f)
    heat, _ = book.heat(p, loss_btu_per_gal)
    placed = heat - withheld_btu(book, p)
    core = [
        placed[int((t - book.start).total_seconds() / book.seconds)]
        for t, a, _ in events
        if a <= core_h
    ]
    return float(np.median(core)) if core else None
