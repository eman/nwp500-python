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

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import cast

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeResult, minimize, minimize_scalar

from nwp500.sim.params import (
    UA_MIN_DELTA_T_F,
    UA_REF_DELTA_T_F,
    CompressorParams,
    HeaterParams,
    LossParams,
)
from nwp500.sim.physics.compressor import predict_physics_detailed

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


def recoveries(
    history: pd.DataFrame, *, air: str = "heater_air_f"
) -> pd.DataFrame:
    """The history's heat-pump recoveries, as ``fit_compressor`` takes
    them: each compressor run with no element, no hybrid mode, no
    anti-legionella cycle and no error from ``PRE_RECOVERY_LOOKBACK``
    before it to its end, a target above the lower probe at its start,
    not cut short (``INTERRUPTED_WH``), and a plausible rate
    (``MIN_MINUTES_PER_F`` to ``MAX_MINUTES_PER_F``, at most
    ``MAX_RECOVERY_LABEL_MINUTES``).

    Each row: ``start_time``, ``end_time``, ``duration_minutes`` (the
    compressor's run), ``t_start_lower``, ``t_start_upper`` and
    ``stratification_gap`` at the start, ``delta_t_lower`` (the target
    less the lower probe), ``t_amb_mean`` (the mean of the ``air``
    column over the run: the heater's own reading by default, a sensor's
    with ``air="air_f"``), ``h_amb_start`` where the history has
    humidity, and ``reached`` (the lower probe came within
    ``REACHED_TOLERANCE_F`` of the target before the run ended).
    Only reached recoveries teach a duration: the heater stops some
    short by design, and those never reach the instant the fit models.
    """
    columns = [
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
    ]
    if history.empty:
        return pd.DataFrame(columns=columns)
    when = _instants(history)
    index = pd.DatetimeIndex(history.index)
    seconds = np.array([t.timestamp() for t in when])
    lower_f, upper_f = _floats(history, "lower_f"), _floats(history, "upper_f")
    target_f, air_f = _floats(history, "target_f"), _floats(history, air)
    humidity_pct = _floats(history, "humidity_pct")
    energy_wh = _floats(history, "energy_to_setpoint_wh")
    on = history["compressor_on"].fillna(False).astype(bool).to_numpy()
    element = history["element_on"].fillna(False).astype(bool).to_numpy()
    excluded = (
        history["excluded"].fillna(False).astype(bool).to_numpy()
        if "excluded" in history.columns
        else np.zeros(len(history), dtype=bool)
    )
    rows: list[dict[str, object]] = []
    for start, end in _on_intervals(when, on):
        span = (index >= start - PRE_RECOVERY_LOOKBACK) & (index <= end)
        if element[span].any() or excluded[span].any():
            continue
        lower = _asof(lower_f, seconds, start)
        upper = _asof(upper_f, seconds, start)
        target = _asof(target_f, seconds, start)
        if lower is None or upper is None or target is None:
            continue
        if target - lower <= 0.0:
            continue
        minutes = (end - start).total_seconds() / 60.0
        if not (
            MIN_MINUTES_PER_F <= minutes / (target - lower) <= MAX_MINUTES_PER_F
            and minutes <= MAX_RECOVERY_LABEL_MINUTES
        ):
            continue
        before, after = INTERRUPTED_WINDOW
        at_end = energy_wh[(index >= end + before) & (index <= end + after)]
        at_end = at_end[np.isfinite(at_end)]
        if len(at_end) and at_end[-1] > INTERRUPTED_WH:
            continue
        inside = (index >= start) & (index <= end)
        air_in = air_f[inside][np.isfinite(air_f[inside])]
        air_mean = float(np.mean(air_in)) if len(air_in) else float("nan")
        humidity = _asof(humidity_pct, seconds, start)
        probe = lower_f[inside]
        rows.append(
            {
                "start_time": start,
                "end_time": end,
                "duration_minutes": minutes,
                "t_start_lower": lower,
                "t_start_upper": upper,
                "stratification_gap": upper - lower,
                "delta_t_lower": target - lower,
                "t_amb_mean": air_mean,
                "h_amb_start": 50.0 if humidity is None else humidity,
                "reached": bool(np.any(probe >= target - REACHED_TOLERANCE_F)),
            }
        )
    return pd.DataFrame(rows, columns=columns)


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


@dataclass(frozen=True)
class Calibration:
    """A heater's calibration: the parameters, and the fits behind them
    (None where a fit had too little to go on)."""

    params: HeaterParams
    standby: StandbyFit
    compressor: CompressorFit | None
    #: The recoveries found, reached or not.
    recoveries: pd.DataFrame = field(repr=False)


def calibrate(
    history: pd.DataFrame,
    base: HeaterParams,
    *,
    recovery_air: str = "heater_air_f",
) -> Calibration:
    """``base`` refitted on ``history``: the standby loss law and the
    gap's time constant from its quiet windows, then the compressor on
    its reached recoveries, against the loss just fitted (as the
    simulation will run it). A part without the evidence keeps
    ``base``'s value; a compressor fit pinned on a bound is reported but
    not applied."""
    standby = fit_standby(history, base.tank.thermal_mass_btu_f)
    params = with_standby(base, standby)
    found = recoveries(history, air=recovery_air)
    reached = found.loc[found["reached"].astype(bool)]
    compressor = fit_compressor(reached, params.compressor, params.loss)
    if compressor is not None:
        params = with_compressor(params, compressor)
    return Calibration(params, standby, compressor, found)
