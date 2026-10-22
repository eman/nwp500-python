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

import bisect
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.optimize import (
    OptimizeResult,
    least_squares,
    linprog,
    minimize,
    minimize_scalar,
)

from nwp500.sim.book import Booked, full_tank, house_gpm, is_full
from nwp500.sim.book import Step as BookStep
from nwp500.sim.circulation import RUN_GAP
from nwp500.sim.circulation import displaced_gal as circulation_displaced_gal
from nwp500.sim.decay import draw_step
from nwp500.sim.heating_trajectory import path_cop
from nwp500.sim.inputs import ELECTRIC, ENERGY_SAVER, HIGH_DEMAND
from nwp500.sim.params import (
    INSTALLATION_TERMS,
    TAU_GAP_PRIOR_H,
    UA_MIN_DELTA_T_F,
    UA_REF_DELTA_T_F,
    UNFITTED_TERMS,
    BookParams,
    CirculationParams,
    CompressorParams,
    HeaterParams,
    LossParams,
    TankParams,
)
from nwp500.sim.physics.compressor import PhysicsPath, predict_physics_detailed
from nwp500.sim.physics.draw import delivery_temp_f, draw_energy_btu
from nwp500.sim.physics.tank import ua_at
from nwp500.sim.record import Record
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
#: The loss law is fitted on windows opening with a gap of at most
#: this, °F: a wider one is a draw's front closing, the gap's constant's
#: regime, not the standby loss's.
MAX_LOSS_FIT_GAP_F = 10.0
#: A window opening with at least this gap, °F, shows the bottom loss
#: (``physics.tank``); the bottom loss is fitted only on this many.
MIN_BOTTOM_FIT_GAP_F = 1.0
MIN_BOTTOM_FIT_WINDOWS = 10
#: Bounds of the bottom loss, BTU/hr, and of its gate, °F.
BOTTOM_LOSS_BOUNDS = (0.0, 1000.0)
BOTTOM_GATE_BOUNDS = (0.05, 30.0)
#: The joint fit's soft_l1 scale, °F/h·√h: a window's end error
#: per hour, weighted by the root of its hours, past which a residual
#: counts linearly (``scipy.optimize.least_squares``' ``soft_l1``).
_LOSS_FIT_SCALE = 0.05
#: The gap's constant and the loss are fitted in turn
#: (``fit_standby``) until the constant moves less than this share, or
#: this many rounds.
_STANDBY_ROUNDS_RTOL = 0.005
_MAX_STANDBY_ROUNDS = 20


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
    recorded, else ``dhw_in_use``, which fires on both), each extended
    forward by ``settle_minutes`` while the tank settles. Merged,
    sorted. One recorded and not the other: the heater's flag stands in
    for the other. Where a caller marks ``air_unobserved`` (no reading
    of the air), the tank is not quiet either: a fit there would stand
    on air nobody read."""
    when = _instants(history)
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


def _no_series() -> np.ndarray:
    """An empty series: a window made without its probes."""
    return np.zeros(0)


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
    #: The probes and the air on ``gap_hours``' grid, °F: the loss law's
    #: input (``fit_loss``). Empty, a window made without them, is not
    #: fitted on.
    upper_f: np.ndarray = field(default_factory=_no_series, repr=False)
    lower_f: np.ndarray = field(default_factory=_no_series, repr=False)
    air_f: np.ndarray = field(default_factory=_no_series, repr=False)


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
        upper_f=wide["upper_f"].to_numpy(dtype=float),
        lower_f=wide["lower_f"].to_numpy(dtype=float),
        air_f=air,
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


def gap_paths(
    windows: Sequence[tuple[np.ndarray, np.ndarray]],
    tau_gap_hours: float,
    loss: LossParams | None = None,
    tank: TankParams = TankParams(),
) -> list[np.ndarray]:
    """Each window's gap, ``(hours, gap)``, as the standby walk takes it
    from its first value: relaxing on ``tau_gap_hours``, and opened by
    ``loss``' bottom loss (``physics.tank``) where it has one. Without
    one, the closed form ``gap_0 exp(-t / tau)``."""
    if loss is None or loss.bottom_loss_btu_hr <= 0.0:
        return [g[0] * np.exp(-t / tau_gap_hours) for t, g in windows]
    q, gate = loss.bottom_loss_btu_hr, loss.bottom_gate_f
    lower_mass = tank.lower_zone_thermal_mass_btu_f
    n = len(windows)
    if n == 0:
        return []
    steps = max(len(g) for _, g in windows) - 1
    dt = np.zeros((n, max(steps, 0)))
    for i, (t, _) in enumerate(windows):
        dt[i, : len(t) - 1] = np.diff(np.asarray(t, dtype=float))
    gap = np.maximum(np.array([g[0] for _, g in windows], dtype=float), 0.0)
    path = np.zeros((n, steps + 1))
    path[:, 0] = gap
    for j in range(steps):
        step = dt[:, j]
        if gate > 0.0:
            # The bottom loss at the step's start, as the walk charges it.
            gap = gap + q * (1.0 - np.exp(-gap / gate)) * step / lower_mass
        gap = gap * np.exp(-step / tau_gap_hours)
        path[:, j + 1] = gap
    return [path[i, : len(g)] for i, (_, g) in enumerate(windows)]


def fit_gap_tau(
    windows: Sequence[tuple[np.ndarray, np.ndarray]],
    min_start_gap_f: float = MIN_GAP_FIT_START_F,
    min_windows: int = MIN_GAP_FIT_WINDOWS,
    *,
    loss: LossParams | None = None,
    tank: TankParams = TankParams(),
) -> tuple[float | None, int]:
    """The time constant the stratification gap relaxes on, hours: one
    constant minimising the squared gap error of ``gap_paths`` (with no
    bottom loss, ``gap_0 exp(-t/tau)``) pooled over every sample of
    every window starting with a gap of at least ``min_start_gap_f``.
    ``loss``' bottom loss opens the gaps it relaxes, as the walk does,
    so a gap it widens is not read as one relaxing slowly. ``(None, n)``
    with fewer than ``min_windows``."""
    used = [
        (t, g)
        for t, g in windows
        if len(g) >= 2 and np.isfinite(g).all() and g[0] >= min_start_gap_f
    ]
    if len(used) < min_windows:
        return None, len(used)

    def sse(log_tau: float) -> float:
        paths = gap_paths(used, float(np.exp(log_tau)), loss, tank)
        return sum(
            float(np.sum((g - path) ** 2))
            for (_, g), path in zip(used, paths, strict=True)
        )

    low, high = GAP_TAU_BOUNDS_HOURS
    found = cast(
        OptimizeResult,
        minimize_scalar(
            sse, bounds=(np.log(low), np.log(high)), method="bounded"
        ),
    )
    return float(np.exp(found.x)), len(used)


def gap_error(
    windows: Sequence[StandbyWindow],
    tau_gap_hours: float | None,
    loss: LossParams | None = None,
    tank: TankParams = TankParams(),
) -> float | None:
    """The gap's mean squared error on ``windows``, °F², as
    ``gap_paths`` takes it. None with no window or no constant."""
    if not windows or tau_gap_hours is None or not tau_gap_hours > 0.0:
        return None
    pairs = [(w.gap_hours, w.gap_f) for w in windows]
    paths = gap_paths(pairs, tau_gap_hours, loss, tank)
    squared = [
        (g - path) ** 2 for (_, g), path in zip(pairs, paths, strict=True)
    ]
    return float(np.mean(np.concatenate(squared)))


def walk_tau(tank: TankParams, tau: float | None = None) -> float:
    """The gap's constant the standby loss is walked on, hours: ``tau``,
    else ``tank``'s, else ``TAU_GAP_PRIOR_H``, as the simulation serves
    an unfitted one."""
    if tau is not None:
        return tau
    if tank.stratification_gap_tau_h is not None:
        return tank.stratification_gap_tau_h
    return TAU_GAP_PRIOR_H


def loss_windows(
    windows: Sequence[StandbyWindow],
) -> list[StandbyWindow]:
    """The windows ``fit_loss`` fits on: with their probes and air,
    opening with a gap of at most ``MAX_LOSS_FIT_GAP_F``, and a UA, a
    ΔT and hours above zero (``fit_ua_law``'s own test)."""
    return [
        w
        for w in windows
        if len(w.upper_f) >= 2
        and len(w.upper_f) == len(w.lower_f) == len(w.air_f)
        and len(w.gap_hours) == len(w.upper_f)
        and bool(np.isfinite(w.upper_f).all())
        and bool(np.isfinite(w.lower_f).all())
        and bool(np.isfinite(w.air_f).all())
        and w.upper_f[0] - w.lower_f[0] <= MAX_LOSS_FIT_GAP_F
        and w.ua_btu_hr_f > 0.0
        and w.delta_t_mean_f > 0.0
        and w.duration_hours > 0.0
    ]


def standby_ends(
    windows: Sequence[StandbyWindow],
    loss: LossParams,
    tau_gap_hours: float,
    tank: TankParams = TankParams(),
) -> tuple[np.ndarray, np.ndarray]:
    """Each window's upper and lower probe at its end, °F, as the
    standby walk (``decay.project_decay``) takes them there from its
    first reading on ``loss``: the UA law on the bulk, the bottom loss
    on the lower zone, the gap relaxing on ``tau_gap_hours``. Windows
    from ``loss_windows``; a UA of None is ``ua_baseline_btu_hr_f``."""
    n = len(windows)
    if n == 0:
        return np.zeros(0), np.zeros(0)
    steps = max(len(w.upper_f) for w in windows) - 1
    dt = np.zeros((n, steps))
    air = np.zeros((n, steps))
    for i, w in enumerate(windows):
        k = len(w.upper_f) - 1
        dt[i, :k] = np.diff(np.asarray(w.gap_hours, dtype=float))
        air[i, :k] = w.air_f[:k]
    ua_ref = (
        loss.ua_baseline_btu_hr_f
        if loss.ua_btu_hr_f is None
        else loss.ua_btu_hr_f
    )
    mass = tank.thermal_mass_btu_f
    lower_mass = tank.lower_zone_thermal_mass_btu_f
    upper0 = np.array([w.upper_f[0] for w in windows], dtype=float)
    lower0 = np.array([w.lower_f[0] for w in windows], dtype=float)
    bulk = (upper0 + lower0) / 2.0
    gap = np.maximum(upper0 - lower0, 0.0)
    q, gate = loss.bottom_loss_btu_hr, loss.bottom_gate_f
    for j in range(steps):
        step = dt[:, j]
        if q > 0.0 and gate > 0.0:
            # At the step's start, as the walk charges it.
            drop = q * (1.0 - np.exp(-gap / gate)) * step / lower_mass
            bulk = bulk - drop / 2.0
            gap = gap + drop
        delta = bulk - air[:, j]
        if loss.ua_exponent == 0.0:
            ua = np.full(n, ua_ref)
        else:
            scaled = (
                np.maximum(np.abs(delta), UA_MIN_DELTA_T_F)
                / loss.ua_ref_delta_t_f
            )
            ua = ua_ref * scaled**loss.ua_exponent
        bulk = bulk - ua / mass * delta * step
        gap = gap * np.exp(-step / tau_gap_hours)
    return bulk + gap / 2.0, bulk - gap / 2.0


def standby_error(
    windows: Sequence[StandbyWindow],
    loss: LossParams,
    tau_gap_hours: float,
    tank: TankParams = TankParams(),
) -> float | None:
    """The probes' mean absolute error in each window's fall, °F/h:
    ``standby_ends`` against each window's last readings, both probes
    alike. None with no window."""
    if not windows:
        return None
    upper, lower = standby_ends(windows, loss, tau_gap_hours, tank)
    hours = np.array([w.duration_hours for w in windows], dtype=float)
    seen_u = np.array([w.upper_f[-1] for w in windows], dtype=float)
    seen_l = np.array([w.lower_f[-1] for w in windows], dtype=float)
    errors = np.concatenate(
        [np.abs(upper - seen_u) / hours, np.abs(lower - seen_l) / hours]
    )
    return float(np.mean(errors))


@dataclass(frozen=True)
class LossFit:
    """The loss law ``fit_loss`` found: the UA law's pair, the bottom
    loss and its gate (0.0 and None without the evidence for them), and
    the windows it stood on, and of those, the stratified ones."""

    ua_ref: float
    ua_exponent: float
    bottom_loss_btu_hr: float
    bottom_gate_f: float | None
    n_windows: int
    n_stratified: int


def fit_loss(
    windows: Sequence[StandbyWindow],
    tau_gap_hours: float,
    tank: TankParams = TankParams(),
) -> LossFit | None:
    """The standby loss on ``windows`` (``loss_windows`` of them).

    With ``MIN_BOTTOM_FIT_WINDOWS`` opening with a gap of at least
    ``MIN_BOTTOM_FIT_GAP_F``, the UA law and the bottom loss are fitted
    together through the standby walk (``standby_ends``): each window's
    upper and lower probe at its end against what it read, per hour,
    weighted by the root of its hours, ``soft_l1``. A mixed window
    holds the UA law; a stratified one, the bottom loss and its gate
    (``physics.tank``). The exponent is fitted only where ``fit_ua_law``
    would fit one. Without that evidence, ``fit_ua_law``'s law and no
    bottom loss. None with no window."""
    used = loss_windows(windows)
    if not used:
        return None
    ua_ref, exponent = fit_ua_law(
        [w.delta_t_mean_f for w in used],
        [w.ua_btu_hr_f for w in used],
        [w.duration_hours for w in used],
    )
    stratified = [
        w for w in used if w.upper_f[0] - w.lower_f[0] >= MIN_BOTTOM_FIT_GAP_F
    ]
    if len(stratified) < MIN_BOTTOM_FIT_WINDOWS:
        return LossFit(ua_ref, exponent, 0.0, None, len(used), len(stratified))
    bands = np.floor(np.array([w.delta_t_mean_f for w in used]) / _BAND_WIDTH_F)
    with_exponent = (
        len(used) >= _MIN_WINDOWS_FOR_LAW
        and len(np.unique(bands)) >= _MIN_BANDS_FOR_LAW
    )
    hours = np.array([w.duration_hours for w in used], dtype=float)
    seen_u = np.array([w.upper_f[-1] for w in used], dtype=float)
    seen_l = np.array([w.lower_f[-1] for w in used], dtype=float)
    weight = np.sqrt(hours) / hours

    def law(x: np.ndarray) -> LossParams:
        return LossParams(
            ua_btu_hr_f=float(x[0]),
            ua_exponent=float(x[3]) if with_exponent else 0.0,
            bottom_loss_btu_hr=float(x[1]),
            bottom_gate_f=float(x[2]),
        )

    def residuals(x: np.ndarray) -> np.ndarray:
        upper, lower = standby_ends(used, law(x), tau_gap_hours, tank)
        return np.concatenate(
            [(upper - seen_u) * weight, (lower - seen_l) * weight]
        )

    lo = [UA_SEARCH_BOUNDS[0], BOTTOM_LOSS_BOUNDS[0], BOTTOM_GATE_BOUNDS[0]]
    hi = [UA_SEARCH_BOUNDS[1], BOTTOM_LOSS_BOUNDS[1], BOTTOM_GATE_BOUNDS[1]]
    x0 = [ua_ref, 50.0, 1.0]
    if with_exponent:
        lo.append(UA_EXPONENT_BOUNDS[0])
        hi.append(UA_EXPONENT_BOUNDS[1])
        x0.append(min(max(exponent, 0.05), UA_EXPONENT_BOUNDS[1] - 0.05))
    x0[0] = min(max(x0[0], lo[0] + 1e-6), hi[0] - 1e-6)
    found = least_squares(
        residuals,
        np.array(x0, dtype=float),
        bounds=(np.array(lo), np.array(hi)),
        loss="soft_l1",
        f_scale=_LOSS_FIT_SCALE,
    )
    fitted = law(found.x)
    return LossFit(
        cast(float, fitted.ua_btu_hr_f),
        fitted.ua_exponent,
        fitted.bottom_loss_btu_hr,
        fitted.bottom_gate_f,
        len(used),
        len(stratified),
    )


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
    #: ``dhw_in_use`` without them, ``meter+dhw_in_use`` with one.
    quiet_by: str
    #: The bottom loss and its gate (``fit_loss``): 0.0 and None
    #: without the stratified windows to fit them on, and how many
    #: there were.
    bottom_loss_btu_hr: float = 0.0
    bottom_gate_f: float | None = None
    n_stratified: int = 0


def fit_standby(
    history: pd.DataFrame,
    thermal_mass_btu_f: float,
    *,
    min_quiet_hours: float = MIN_QUIET_HOURS,
    settle_minutes: float = SETTLE_MINUTES,
    tank: TankParams | None = None,
    loss: LossParams | None = None,
) -> StandbyFit:
    """The standby loss and the gap's time constant from the history's
    quiet windows: the gap's constant first, then the loss
    (``fit_loss``) walked on it, or on ``tank``'s where too few windows
    open with a gap to fit one. ``tank`` (default the default tank of
    ``thermal_mass_btu_f``'s mass) is the walk's lower zone. ``loss``
    is the loss the parameters hold: where no loss is fitted (no window
    the loss can use), its bottom loss opens the gaps the constant is
    fitted on, as the simulation will run them."""
    if tank is None:
        tank = replace(
            TankParams(),
            volume_gal=thermal_mass_btu_f / WATER_BTU_PER_GAL_F,
        )
    quiet = quiet_windows(history, min_quiet_hours, settle_minutes)
    kept: list[StandbyWindow] = []
    for window in quiet:
        fit = fit_window(history, window, thermal_mass_btu_f)
        if fit is not None and fit.rmse_f < MAX_WINDOW_RMSE_F:
            kept.append(fit)
    # The gap's constant and the bottom loss each shape the other's
    # evidence: the loss is walked on the constant, and the bottom loss
    # opens the gaps the constant relaxes. Fitted in turn, the constant
    # first on the gaps alone, until the constant settles.
    gaps = [(w.gap_hours, w.gap_f) for w in kept]
    tau, n_gap = fit_gap_tau(gaps)
    found = fit_loss(kept, walk_tau(tank, tau), tank)
    if found is None and loss is not None and loss.bottom_loss_btu_hr > 0.0:
        # No loss to fit: the parameters keep theirs, so the constant is
        # fitted on the gaps their bottom loss opens.
        tau, n_gap = fit_gap_tau(gaps, loss=loss, tank=tank)
    for _ in range(_MAX_STANDBY_ROUNDS):
        if found is None or found.bottom_gate_f is None or tau is None:
            break
        opened = LossParams(
            bottom_loss_btu_hr=found.bottom_loss_btu_hr,
            bottom_gate_f=found.bottom_gate_f,
        )
        before = tau
        tau, n_gap = fit_gap_tau(gaps, loss=opened, tank=tank)
        found = fit_loss(kept, walk_tau(tank, tau), tank)
        if tau is None or abs(tau - before) <= _STANDBY_ROUNDS_RTOL * before:
            break
    tier1 = [c for c in ("drawing", "circulating") if c in history.columns]
    return StandbyFit(
        windows=tuple(kept),
        n_quiet=len(quiet),
        n_dropped=len(quiet) - len(kept),
        ua_ref=None if found is None else found.ua_ref,
        ua_exponent=None if found is None else found.ua_exponent,
        tau_gap_hours=tau,
        n_gap_windows=n_gap,
        bottom_loss_btu_hr=0.0 if found is None else found.bottom_loss_btu_hr,
        bottom_gate_f=None if found is None else found.bottom_gate_f,
        n_stratified=0 if found is None else found.n_stratified,
        quiet_by=(
            "meter"
            if len(tier1) == 2
            else "meter+dhw_in_use"
            if tier1
            else "dhw_in_use"
        ),
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


_RECOVERY_NEED = (
    "t_start_lower",
    "delta_t_lower",
    "t_amb_mean",
    "duration_minutes",
)


def split_recoveries(
    recoveries: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(fitted, held_out)``: the recoveries a compressor fit uses, in
    time order where ``start_time`` says, the latest ``HELDOUT_FRACTION``
    (at least ``MIN_HELDOUT``) held out once there are
    ``MIN_RECOVERIES_FOR_SPLIT``. Usable: the figures known and a
    duration from ``MIN_RECOVERY_MINUTES`` to ``MAX_RECOVERY_MINUTES``."""
    if any(c not in recoveries.columns for c in _RECOVERY_NEED):
        empty = recoveries.iloc[0:0]
        return empty, empty
    df = recoveries.dropna(subset=list(_RECOVERY_NEED))
    minutes = df["duration_minutes"]
    df = df.loc[
        (minutes >= MIN_RECOVERY_MINUTES) & (minutes <= MAX_RECOVERY_MINUTES)
    ].copy()
    if "start_time" in df.columns:
        df = df.sort_values("start_time").reset_index(drop=True)
    n = len(df)
    n_held = (
        max(MIN_HELDOUT, round(n * HELDOUT_FRACTION))
        if n >= MIN_RECOVERIES_FOR_SPLIT
        else 0
    )
    return df.iloc[: n - n_held], df.iloc[n - n_held :]


def recovery_minutes(
    recoveries: pd.DataFrame,
    compressor_constant: float,
    evap_approach_f: float,
    *,
    compressor: CompressorParams,
    loss: LossParams,
    tank: TankParams,
    two_zone: bool,
    gaps: bool,
) -> np.ndarray:
    """Each recovery's duration as the physics predicts it, minutes, on
    ``fit_compressor``'s columns; ``gaps`` uses its
    ``stratification_gap``, else none."""
    rows = len(recoveries)
    start = np.asarray(recoveries["t_start_lower"], dtype=float)
    target = start + np.asarray(recoveries["delta_t_lower"], dtype=float)
    air = np.asarray(recoveries["t_amb_mean"], dtype=float)
    humidity = np.asarray(
        recoveries["h_amb_start"]
        if "h_amb_start" in recoveries.columns
        else np.full(rows, 50.0),
        dtype=float,
    )
    gap = np.asarray(
        recoveries["stratification_gap"] if gaps else np.zeros(rows),
        dtype=float,
    )
    return np.array(
        [
            predict_physics_detailed(
                t_start_lower=float(start[i]),
                hp_lower_off=float(target[i]),
                t_amb_mean=float(air[i]),
                compressor_constant=compressor_constant,
                evap_approach_f=evap_approach_f,
                compressor=compressor,
                loss=loss,
                h_amb_start=float(humidity[i]),
                ua_btu_hr_f=loss.ua_btu_hr_f,
                ua_exponent=loss.ua_exponent,
                ua_ref_delta_t=loss.ua_ref_delta_t_f,
                stratification_gap=float(gap[i]),
                two_zone=two_zone,
                tank=tank,
            ).minutes
            for i in range(rows)
        ]
    )


def fit_compressor(
    recoveries: pd.DataFrame,
    compressor: CompressorParams,
    loss: LossParams,
    *,
    two_zone: bool = True,
    tank: TankParams = TankParams(),
) -> CompressorFit | None:
    """``compressor_constant`` and ``evap_approach_f`` minimising the
    squared error of the physics' durations against recorded ones, each
    integrated on ``tank`` (the heater's own: pass ``HeaterParams.tank``).

    ``recoveries``: exactly one row per heat-pump recovery (a recovery
    read twice, from overlapping windows say, is weighted twice and
    moves the fit; keep one row for each), with
    ``t_start_lower``, ``delta_t_lower`` (the lower zone's rise to its
    target), ``t_amb_mean`` (the air over it, °F) and
    ``duration_minutes``; optionally ``h_amb_start`` (%RH; 50 without),
    ``stratification_gap`` (upper minus lower at the start; without it
    the fit falls back to the one-zone integrator, so the constant stays
    the one the simulation will use) and ``start_time`` (to hold out the
    latest, ``split_recoveries``). None with fewer than
    ``MIN_RECOVERIES`` usable.
    """
    fit_df, held_df = split_recoveries(recoveries)
    if len(fit_df) + len(held_df) < MIN_RECOVERIES:
        return None
    n_held = len(held_df)
    # Usable gaps are judged on the rows fitted, as the model's fit did:
    # a gap the fit has not got cannot be the mass model's.
    has_gaps = "stratification_gap" in fit_df.columns and bool(
        fit_df["stratification_gap"].notna().all()
    )
    two_zone = two_zone and has_gaps

    def predicted(
        frame: pd.DataFrame, k: float, approach: float, gaps: bool = has_gaps
    ) -> np.ndarray:
        return recovery_minutes(
            frame,
            k,
            approach,
            compressor=compressor,
            loss=loss,
            tank=tank,
            two_zone=two_zone,
            gaps=gaps,
        )

    actual = np.asarray(fit_df["duration_minutes"], dtype=float)

    def objective(x: np.ndarray) -> float:
        k, approach = float(x[0]), float(x[1])
        if not (
            K_BOUNDS[0] <= k <= K_BOUNDS[1]
            and APPROACH_BOUNDS[0] <= approach <= APPROACH_BOUNDS[1]
        ):
            return 1e12
        return float(np.sum((predicted(fit_df, k, approach) - actual) ** 2))

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
    mae = float(np.mean(np.abs(predicted(fit_df, k, approach) - actual)))
    held_mae = None
    if n_held:
        # The held-out rows' gaps as recorded, wherever the column is.
        held_mae = float(
            np.mean(
                np.abs(
                    predicted(
                        held_df,
                        k,
                        approach,
                        gaps="stratification_gap" in held_df.columns,
                    )
                    - np.asarray(held_df["duration_minutes"], dtype=float)
                )
            )
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
    return np.asarray(history[name].to_numpy(dtype=float, na_value=np.nan))


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
    "draw_gal",
    "draw_t_upper",
    "draw_lead_gal",
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
    they left at, those in the ``DRAW_LEAD`` before ``at``, and each run
    over the span (merged within ``_RUN_GAP``) as ``(minutes, the upper
    zone at its start)``. None for what was not given: an unrecorded
    meter or circulation is not an idle one."""
    out: dict[str, object] = {
        "draw_gal": None,
        "draw_t_upper": None,
        "draw_lead_gal": None,
        "circulation_runs": None,
    }

    def upper_at(t: datetime) -> float | None:
        return _asof(upper, seconds, t)

    if draws is not None:
        window = [(t, g) for t, g in draws if at <= t <= end]
        gal = float(sum(g for _, g in window))
        out["draw_gal"] = gal
        if gal > 0.0:
            weighted = [(upper_at(t), g) for t, g in window]
            out["draw_t_upper"] = (
                sum(u * g for u, g in weighted if u is not None) / gal
            )
        out["draw_lead_gal"] = float(
            sum(g for t, g in draws if at - DRAW_LEAD <= t < at)
        )
    if circulation is not None:
        runs = sorted(
            (max(a, at), min(b, end))
            for a, b in circulation
            if a < end and b > at
        )
        merged: list[tuple[datetime, datetime]] = []
        for a, b in runs:
            if merged and a - merged[-1][1] <= _RUN_GAP:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        out["circulation_runs"] = tuple(
            ((b - a).total_seconds() / 60.0, u)
            for a, b in merged
            if b > a and (u := upper_at(a)) is not None
        )
    return out


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
    snapshot (``_in_cycle``), which ``metered_withdrawn`` prices.
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
    # A meter's or the circulation's flag marks a sample's interval, to the next
    # sample (``sim_adapters.history``): the sample before a lead's first
    # can hold water moving inside it.
    interval_water = water if tier1 else np.zeros(len(history), dtype=bool)
    rows: list[dict[str, object]] = []
    for n, (start, end) in enumerate(_on_intervals(when, on)):
        span = (index >= start - PRE_RECOVERY_LOOKBACK) & (index <= end)
        if element[span].any() or excluded[span].any():
            continue
        target = _asof(target_f, seconds, start)
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
        cycle = (index >= start) & (index < end)
        if not cycle.any():
            continue
        c_seconds, c_air = seconds[cycle], air_f[cycle]
        lower_end = _asof(lower_f[cycle], c_seconds, end)
        upper_end = _asof(upper_f[cycle], c_seconds, end)
        # A source flag on the sample at ``end`` is the interval after
        # the recovery; the heater's own flag is read at its instant.
        lead = (index >= start - DRAW_LEAD) & (
            (index < end) if tier1 else (index <= end)
        )
        draw_free = not water[lead].any()
        first = int(np.argmax(lead)) if lead.any() else len(lead)
        if (
            0 < first < len(lead)
            and bool(index[first] > start - DRAW_LEAD)
            and bool(interval_water[first - 1])
        ):
            draw_free = False
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
                    # Unrecorded humidity is passed on unknown, as the
                    # model's fit read it, not as an assumed 50 %.
                    "h_amb_start": math.nan if humidity is None else humidity,
                    "reached": reached,
                    "metered_input_wh": _energy_wh(
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
        # Quoted at the ΔT ``fit_standby``'s law was fitted at, not
        # whatever ``params`` held. The bottom loss goes with it: a law
        # fitted without one has the bottom's heat in its UA, so the
        # parameters' own would count it twice.
        loss = replace(
            loss,
            ua_btu_hr_f=fit.ua_ref,
            ua_exponent=fit.ua_exponent,
            ua_ref_delta_t_f=UA_REF_DELTA_T_F,
            bottom_loss_btu_hr=fit.bottom_loss_btu_hr,
            bottom_gate_f=(
                loss.bottom_gate_f
                if fit.bottom_gate_f is None
                else fit.bottom_gate_f
            ),
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
        tank=params.tank,
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


def power_cycles(
    rows: pd.DataFrame, params: HeaterParams
) -> list[tuple[datetime | None, float, float]]:
    """Each cycle's ``(start, metered, modelled)`` Wh for the power scale
    (``start`` None where the rows carry no ``start_time``):
    the integrator's own mean power over the cycle's real duration, so
    both sides are energy over the same clock."""
    out: list[tuple[datetime | None, float, float]] = []
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
        out.append((row.get("start_time"), metered, modelled))
    return out


def fit_power_scale(
    rows: pd.DataFrame, params: HeaterParams
) -> tuple[float | None, int]:
    """``(metered / modelled, cycles)`` over ``power_cycles``, a ratio
    of sums. ``(None, n)`` with fewer than ``MIN_POWER_EVENTS``."""
    cycles = power_cycles(rows, params)
    metered_total = sum(m for _, m, _ in cycles)
    modelled_total = sum(e for _, _, e in cycles)
    n = len(cycles)
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


def metered_withdrawn(
    params: HeaterParams,
    *,
    flow_at: Callable[[datetime], float | None] | None = None,
) -> Withdrawn:
    """With a meter: the apparent heat a cycle's draws and circulation
    took (``snapshots``' ``draw_gal`` and ``circulation_runs``), Wh.
    Draws through the calibrated draw term at their volume-weighted
    upper zone; each run through the circulation's displaced volume at
    the upper zone at its start, less the air, times
    ``DrawParams.ungated_observability`` (the probes' share of the
    circulation's heat). None when either record is missing, when draws
    happened and the draw term is off, or when circulation ran and the
    installation has no circulation terms: an unknown withdrawal is not
    a zero one. ``flow_at`` prices a cycle's runs at the flow the
    circulation ran at then, by the cycle's ``start_time``
    (``flow_lookup``), ``CirculationParams.flow_gpm`` where it has none:
    the flow moves run to run, and today's priced months of runs
    wrongly."""
    d, c = params.draw, params.circulation

    def withdrawn(row: Mapping[str, Any]) -> float | None:
        gal, runs = row.get("draw_gal"), row.get("circulation_runs")
        if gal is None or runs is None or pd.isna(gal):
            return None
        btu = 0.0
        if runs:
            if c is None or c.displaced_gal <= 0.0:
                return None
            air = row.get("t_amb_mean")
            if air is None or pd.isna(air):
                return None
            flow = c.flow_gpm
            at = row.get("start_time")
            if flow_at is not None and at is not None and not pd.isna(at):
                then = flow_at(cast(datetime, pd.Timestamp(at).to_pydatetime()))
                flow = then if then is not None else c.flow_gpm
            for minutes, upper in runs:
                displaced = circulation_displaced_gal(
                    minutes, c.displaced_gal, flow
                )
                btu += d.ungated_observability * max(
                    0.0, displaced * WATER_BTU_PER_GAL_F * (upper - float(air))
                )
        if float(gal) > 0.0:
            upper = row.get("draw_t_upper")
            if d.observability is None or upper is None or pd.isna(upper):
                return None
            btu += draw_energy_btu(
                float(gal),
                float(upper),
                delivery_temp_f(
                    float(upper), d.delivery_intercept_f, d.delivery_slope
                ),
                d.inlet_temp_f,
                d.observability,
            )
        return btu / BTU_PER_WH

    return withdrawn


def metered_lead(params: HeaterParams) -> Withdrawn:
    """With a meter: the apparent heat of the draws in the ``DRAW_LEAD``
    before a cycle, Wh, at the upper zone at its start, whose cold water
    the start reading had not yet seen. None when the record is missing,
    or when draws happened and the draw term is off."""
    d = params.draw

    def lead(row: Mapping[str, Any]) -> float | None:
        gal = row.get("draw_lead_gal")
        if gal is None or pd.isna(gal):
            return None
        if float(gal) <= 0.0:
            return 0.0
        upper = row.get("t_start_upper")
        if d.observability is None or upper is None or pd.isna(upper):
            return None
        return (
            draw_energy_btu(
                float(gal),
                float(upper),
                delivery_temp_f(
                    float(upper), d.delivery_intercept_f, d.delivery_slope
                ),
                d.inlet_temp_f,
                d.observability,
            )
            / BTU_PER_WH
        )

    return lead


def draw_free_withdrawn(row: Mapping[str, Any]) -> float | None:
    """Without a meter: nothing withdrawn from a cycle with no water in
    use from ``DRAW_LEAD`` before it to its end, and unknown otherwise."""
    return 0.0 if bool(row.get("draw_free")) else None


@dataclass(frozen=True)
class CopCycle:
    """One cycle's figures for the apparent COP: when it started, the
    heat it stored plus what draws took, the lead draws' heat, the
    integrator's COP, the metered energy (Wh) and the lift (°F).
    ``start`` is None where the rows carry no ``start_time``."""

    start: datetime | None
    heat_wh: float
    lead_wh: float
    modelled_cop: float
    metered_wh: float
    lift_f: float


def cop_cycles(
    rows: pd.DataFrame,
    params: HeaterParams,
    *,
    withdrawn: Withdrawn = draw_free_withdrawn,
    lead: Withdrawn | None = None,
) -> list[CopCycle]:
    """The cycles ``fit_cop_scale`` fits on, and their figures."""
    needed = [
        "metered_input_wh",
        "t_start_lower",
        "t_start_upper",
        "t_lower_end",
        "t_upper_end",
    ]
    if not set(needed) <= set(rows.columns):
        return []
    wh_per_f = params.tank.thermal_mass_btu_f / BTU_PER_WH
    out: list[CopCycle] = []
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
            tank=params.tank,
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
        out.append(
            CopCycle(
                start=row.get("start_time"),
                heat_wh=stored + took,
                lead_wh=lead_wh,
                modelled_cop=modelled,
                metered_wh=metered,
                lift_f=mean - float(air),
            )
        )
    return out


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
    the start reading had not yet seen (``cop_cycles``). ``(None, n)``
    with fewer than ``MIN_POWER_EVENTS``.

    Without a meter the default keeps only the cycles no water was
    drawn around: the heat drawn during a cycle is otherwise missing
    from its heat and pulls the scale low.
    """
    cycles = cop_cycles(rows, params, withdrawn=withdrawn, lead=lead)
    n = len(cycles)
    if n < MIN_POWER_EVENTS:
        return None, n
    return (
        solve_cop_fit(
            [c.heat_wh for c in cycles],
            [c.modelled_cop for c in cycles],
            [c.metered_wh for c in cycles],
            [c.lead_wh for c in cycles],
            [c.lift_f for c in cycles],
        ),
        n,
    )


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
    withdrawn: Withdrawn | None = None,
    lead: Withdrawn | None = None,
    draws: Sequence[tuple[datetime, float]] | None = None,
    circulation: Sequence[tuple[datetime, datetime]] | None = None,
    circulation_flow_at: Callable[[datetime], float | None] | None = None,
) -> Calibration:
    """``base`` refitted on ``history``: the standby loss law and the
    gap's time constant from its quiet windows, then the compressor on
    its reached recoveries, against the loss just fitted (as the
    simulation will run it), then input power and COP against the
    ``power_w`` readings, on that compressor. A part without the
    evidence keeps ``base``'s value; a compressor fit pinned on a bound
    is reported but not applied, and no power is fitted on it.
    With a meter's ``draws`` (``(instant, delivered gallons)``) and
    ``circulation``'s runs (an empty list for none), the COP fit prices
    the heat each cycle's draws and runs took (``metered_withdrawn``,
    ``metered_lead``), each run at the flow it ran at when
    ``circulation_flow_at`` says (``flow_lookup`` over ``measure_runs``);
    without them it keeps draw-free cycles.
    ``withdrawn`` and ``lead`` replace either.

    What could not be fitted keeps ``base``'s value, the best prior
    there is for the same product, and is named in the result's
    ``HeaterParams.unfitted``, so a failed fit never reads as a fitted
    one: a compressor not fitted (too few recoveries, or pinned on a
    bound) leaves ``compressor`` and ``power``, power or COP not fitted
    ``power``, no quiet window ``standby`` and no gap constant
    ``gap_tau``. ``base``'s record of the installation's terms
    (``INSTALLATION_TERMS``) is kept: they are fitted apart, and a
    caller applying its own fits drops each from ``unfitted``."""
    standby = fit_standby(
        history, base.tank.thermal_mass_btu_f, tank=base.tank, loss=base.loss
    )
    params = with_standby(base, standby)
    rows = snapshots(
        history, air=recovery_air, draws=draws, circulation=circulation
    )
    found = recoveries(history, air=recovery_air)
    reached = found.loc[found["reached"].astype(bool)] if len(found) else found
    compressor = fit_compressor(
        reached, params.compressor, params.loss, tank=params.tank
    )
    power = None
    if compressor is not None and not compressor.hit_bounds:
        params = with_compressor(params, compressor)
        metered = draws is not None and circulation is not None
        if withdrawn is None:
            withdrawn = (
                metered_withdrawn(params, flow_at=circulation_flow_at)
                if metered
                else draw_free_withdrawn
            )
        if lead is None and metered:
            lead = metered_lead(params)
        power = fit_power(rows, params, withdrawn=withdrawn, lead=lead)
        params = with_power(params, power)
    # The installation's terms are fitted apart (``fit_book_terms``,
    # ``fit_evidence``, ``fit_front``): ``base``'s record of them holds.
    unfitted = [t for t in base.unfitted if t in INSTALLATION_TERMS]
    if compressor is None or compressor.hit_bounds:
        unfitted += ["compressor", "power"]
    elif power is None or power.power_scale is None or power.cop_scale is None:
        unfitted.append("power")
    if standby.ua_ref is None or standby.ua_exponent is None:
        unfitted.append("standby")
    if standby.tau_gap_hours is None:
        unfitted.append("gap_tau")
    params = replace(
        params, unfitted=tuple(t for t in UNFITTED_TERMS if t in unfitted)
    )
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
    against the probes. Draws are priced against each step's inlet, as
    the book prices them (``book.step_heat_btu``)."""

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
        self.inlet = np.array([s.inlet_f for s in self.steps])
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
            * np.clip(delivered - self.inlet, 0, None)
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
        return np.asarray(
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

    def pair_terms(
        self, p: BookParams, pairs: Sequence[tuple[int, int]]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Each pair's error (``errors``) as ``k + x @ terms``, linear
        in the fitted terms (``BOOK_TERMS``: the compressor's heat rate,
        its slope with the air, the standby UA and circulation's loss
        per gallon), with ``p``'s others held: ``k`` per pair, BTU, and
        ``x`` a row per pair."""
        h = self.seconds / 3600.0
        delivered = np.minimum(
            self.u, p.delivery_intercept_f + p.delivery_slope * self.u
        )
        fixed = self.el * p.element_w * BTU_PER_WH_BOOK * h - (
            self.draw
            * WATER_BTU_PER_GAL_F
            * np.clip(delivered - self.inlet, 0, None)
        )
        columns = [
            self.comp * h,
            self.comp * (self.air - 65.0) * h,
            -np.clip((self.u + self.l) / 2 - self.air, 0, None) * h,
            -self.circulated,
        ]

        def cum(e: np.ndarray) -> np.ndarray:
            return np.concatenate([[0.0], np.cumsum(np.nan_to_num(e))])

        ep, f = self.probe_heat(p), cum(fixed)
        cs = [cum(c) for c in columns]
        k = np.array([ep[a0] - ep[a1] + f[a1] - f[a0] for a0, a1 in pairs])
        x = np.array([[c[a1] - c[a0] for c in cs] for a0, a1 in pairs]).reshape(
            len(pairs), len(cs)
        )
        return k, x

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

#: The book's fitted terms, in ``RecordedBook.pair_terms``' order, and
#: the plausible bounds each is fitted within: the compressor's heat
#: rate (BTU/h) and its slope with the air (BTU/h/°F), the standby UA
#: (BTU/h/°F) and circulation's loss per gallon (BTU/gal).
BOOK_TERMS = (
    "hp_btu_per_h",
    "hp_btu_per_h_per_f",
    "ua_btu_per_h_f",
    "loss_btu_per_gal",
)
BOOK_TERM_BOUNDS = ((2000.0, 9000.0), (-50.0, 200.0), (0.0, 20.0), (0.0, 500.0))


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
        bounded = zip(x, BOOK_TERM_BOUNDS, strict=True)
        if not all(lo <= v <= hi for v, (lo, hi) in bounded):
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


def fit_terms_l1(
    k: np.ndarray,
    x: np.ndarray,
    bounds: Sequence[tuple[float, float]],
) -> np.ndarray:
    """The terms minimising ``sum |k + x @ terms|`` within ``bounds``,
    exactly (a linear program): ``RecordedBook.pair_terms``' errors
    fitted for the least mean absolute error."""
    n, m = x.shape
    # Variables: the terms, then each pair's |error|.
    cost = np.concatenate([np.zeros(m), np.ones(n)])
    eye = np.eye(n)
    a_ub = np.block([[x, -eye], [-x, -eye]])
    b_ub = np.concatenate([-k, k])
    r = linprog(
        cost,
        A_ub=a_ub,
        b_ub=b_ub,
        bounds=[*bounds, *([(0.0, None)] * n)],
        method="highs",
    )
    if not r.success:
        raise ValueError(f"the book's terms could not be fitted: {r.message}")
    return np.asarray(r.x[:m])


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


# ── the book's response to a draw: the front and the zones' mixing ──
#
# Fitted as they were in the analyses behind the shipped values (their
# scripts, recovered), on frames built from the library's own pieces.
# Two stand-ins, named where they act: the long draws are the record's
# own runs of household flow (the list they were drawn from is not
# recovered), and the front fit's base lower zone is the calibrated
# draw response chained from each draw's onset probes, in place of a
# full replay's.

#: A long draw: household flow above the book's draw line, gaps under
#: ``LONG_DRAW_JOIN_S`` joined, ``MIN_LONG_DRAW_GAL`` or more.
LONG_DRAW_JOIN_S = 60
MIN_LONG_DRAW_GAL = 5.0
#: The mixing fit takes draws this long or more, delivered gallons.
MIN_MIX_DRAW_GAL = 15.0
#: The zones' own rate below the mixing, °F per delivered gallon.
OWN_RATE_F_PER_GAL = 0.03
#: The grids the fits search.
ZONE_MIX_GRID = tuple(
    (s, lam)
    for s in (0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 1.8)
    for lam in (8, 10, 12, 14, 16, 18, 20, 23, 26, 30)
)
FRONT_GRID = tuple(
    (float(vp), w)
    for vp in range(16, 35)
    for w in (16, 20, 24, 28, 32, 36, 40, 48)
)
SETTLE_TAUS = (5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360, 600)
SETTLE_TAUS_FINE = (
    3,
    5,
    7,
    10,
    15,
    20,
    25,
    30,
    40,
    50,
    60,
    75,
    90,
    120,
    150,
    180,
    240,
    300,
    360,
    480,
    600,
)
#: The finer grid the settling constant was read from, minutes.
SETTLE_TAUS_READ = (200, 240, 270, 300, 330, 360, 420)
#: The settle fit's line for a draw, gal/min, and its tails: from the
#: draw's last flowing step to the first heating, circulation or draw,
#: at most ``SETTLE_TAIL``, scored every ``SETTLE_EVERY`` steps.
SETTLE_DRAW_GPM = 0.5
SETTLE_TAIL = timedelta(hours=6)
SETTLE_EVERY = 30


def book_walk(
    book: RecordedBook, zone_empty_btu: float | None = None
) -> pd.DataFrame:
    """The record's book walked continuously over its steps, re-anchoring
    as ``book_steps`` does: per step the probes, the household flow,
    circulation, heating, the air, the book before the step (``heat``,
    ``withheld``, ``cold_gal``, ``cold_f``, ``age_h``; NaN without an
    anchor within ``history_h``) and the cold region after it
    (``cold_gal_after``, ``cold_f_after``). With ``zone_empty_btu``,
    also ``left_z``: the booked gallons left before it, at the upper
    probe and the inlet (the measured inlet's trailing 3 h median, else
    70 degF), and ``hgal``, the gallons drawn in the step."""
    p, circ = book.p, book.circulation
    steps = book.steps
    heating = book.comp | book.el
    disturbed = (book.draw > 0) | (book.circulated > 0)
    was_h = was_d = clean = False
    moving = 0
    b: Booked | None = None
    anchor_i: int | None = None
    rows: list[tuple[Any, ...]] = []
    nan = float("nan")
    for i, s in enumerate(steps):
        age = (
            None
            if anchor_i is None
            else (i - anchor_i - 1) * book.seconds / 3600
        )
        ok = b is not None and age is not None and age <= p.history_h
        before = (
            (b.heat_btu, b.withheld_btu(p), b.cold_gal, b.cold_f, age)
            if ok and b is not None
            else (nan, nan, nan, nan, nan)
        )
        full = is_full(s.upper_f, s.lower_f, p)
        new = None
        if disturbed[i] and not was_d:
            moving = i
        if heating[i]:
            clean = False
        elif was_h:
            clean = True
            if disturbed[i] and full:
                new = (i, moving)
        if disturbed[i]:
            clean = False
        was_h, was_d = bool(heating[i]), bool(disturbed[i])
        if clean and not heating[i] and full:
            new = (i, i + 1)
        if new is not None:
            a, bf = new
            st = steps[a]
            b = full_tank(st.upper_f, st.lower_f, p.inlet_default_f, p)
            for x in steps[bf:a]:
                b = b.step(
                    replace(x, compressor_on=False, element_on=False), p, circ
                )
            for x in steps[max(bf, a) : i + 1]:
                b = b.step(x, p, circ)
            anchor_i = a
        elif b is not None:
            b = b.step(s, p, circ)
        after = (b.cold_gal, b.cold_f) if b is not None else (nan, nan)
        rows.append(
            (
                book.at(i),
                s.upper_f,
                s.lower_f,
                house_gpm(s, circ),
                s.circulating,
                bool(s.compressor_on),
                bool(s.element_on),
                s.ambient_f,
                s.inlet_f,
                s.inlet_measured,
                *before,
                *after,
            )
        )
    d = pd.DataFrame(
        rows,
        columns=[
            "t",
            "up",
            "lo",
            "house",
            "circulating",
            "comp",
            "elem",
            "air",
            "inlet",
            "inlet_meas",
            "heat",
            "withheld",
            "cold_gal",
            "cold_f",
            "age_h",
            "cold_gal_after",
            "cold_f_after",
        ],
    )
    per_step = book.seconds / 60.0
    d["hgal"] = np.where(d.house > p.draw_gpm, d.house * per_step, 0.0)
    if zone_empty_btu is not None:
        window = int(3 * 3600 / book.seconds)
        inlet = d.inlet.where(d.inlet_meas.astype(bool))
        inlet3h = inlet.rolling(window, min_periods=1).median().fillna(70.0)
        delivered = np.minimum(
            d.up, p.delivery_intercept_f + p.delivery_slope * d.up
        )
        per_gal = WATER_BTU_PER_GAL_F * (delivered - inlet3h)
        top = np.maximum(d.up, d.lo)
        cap = WATER_BTU_PER_GAL_F * p.tank_gal * (top - p.reference_f)
        d["left_z"] = (
            np.minimum(d.heat, cap) - d.withheld - zone_empty_btu
        ) / per_gal
    return d


def _epochs(walk: pd.DataFrame) -> np.ndarray:
    """A walk's instants as epoch seconds, for searching."""
    return np.array([cast(datetime, x).timestamp() for x in walk.t])


def long_draws(
    walk: pd.DataFrame, *, min_gal: float = MIN_LONG_DRAW_GAL
) -> list[tuple[datetime, datetime, float]]:
    """The record's long draws ``(onset, end, gallons)``: runs of steps
    drawing (``hgal``), gaps under ``LONG_DRAW_JOIN_S`` joined, of
    ``min_gal`` or more. A stand-in for the meter's own episode list."""
    t = list(walk.t)
    gal = walk.hgal.to_numpy()
    wet = np.flatnonzero(gal > 0)
    if not len(wet):
        return []
    seconds = (t[1] - t[0]).total_seconds() if len(t) > 1 else 10.0
    breaks = np.flatnonzero(np.diff(wet) > LONG_DRAW_JOIN_S / seconds)
    starts = np.r_[wet[0], wet[breaks + 1]]
    ends = np.r_[wet[breaks], wet[-1]]
    out = []
    for a, b in zip(starts, ends, strict=True):
        g = float(gal[a : b + 1].sum())
        if g >= min_gal:
            out.append((t[a], t[b], g))
    return out


def mixing_frame(
    walk: pd.DataFrame,
    draws: Sequence[tuple[datetime, datetime, float]],
    *,
    split: datetime,
    min_gal: float = MIN_MIX_DRAW_GAL,
) -> pd.DataFrame:
    """The upper probe through every long draw of ``min_gal`` or more
    with a book at its onset, each minute: the gallons drawn so far,
    the probe, the booked gallons left (``left_z``, from ``book_walk``
    with ``zone_empty_btu``), the day and whether it is held out (an
    onset at or after ``split``)."""
    t = _epochs(walk)
    rows = []
    per_minute = (
        max(1, int(60 / ((walk.t.iloc[1] - walk.t.iloc[0]).total_seconds())))
        if len(walk) > 1
        else 6
    )
    for a, b, g in draws:
        if g < min_gal:
            continue
        i = int(np.searchsorted(t, a.timestamp()))
        j = int(np.searchsorted(t, b.timestamp()))
        w = walk.iloc[i : j + 1]
        if len(w) < 10 or np.isnan(w.heat.iloc[0]):
            continue
        gal = w.hgal.cumsum().to_numpy()
        if gal[-1] < min_gal * 0.8:
            continue
        for k in range(0, len(w), per_minute):
            r = w.iloc[k]
            rows.append(
                (
                    a,
                    pd.Timestamp(a).strftime("%Y-%m-%d"),
                    gal[k],
                    r.up,
                    r.left_z,
                )
            )
    f = pd.DataFrame(rows, columns=["ev", "day", "gal", "up", "left_z"])
    if f.empty:
        return f.assign(dg=[], held=[])
    f = f.sort_values(["ev", "gal"], kind="stable").reset_index(drop=True)
    f["dg"] = f.groupby("ev").gal.diff().fillna(0.0).clip(lower=0)
    f["held"] = [pd.Timestamp(e) >= pd.Timestamp(split) for e in f.ev]
    return f


@dataclass(frozen=True)
class ZoneMixFit:
    """The upper zone's mixing through a long draw
    (``BookParams.zone_mix_f_per_gal``, ``zone_mix_gal``): the rate
    ``s exp(-left / lam)`` °F per gallon, the best on the training days,
    its errors, and the day bootstrap's 2.5 / 50 / 97.5 percentiles."""

    zone_mix_f_per_gal: float
    zone_mix_gal: float
    mae_train: float
    mae_held: float
    s_interval: tuple[float, float, float]
    lam_interval: tuple[float, float, float]


def _mix_run(
    f: pd.DataFrame, s: float, lam: float, *, line_f: float, fall: float
) -> np.ndarray:
    up0 = f.groupby("ev").up.transform("first").to_numpy()
    L = f.left_z.to_numpy()
    dg = f.dg.to_numpy()
    out = np.empty(len(f))
    for _, g in f.groupby("ev", sort=False):
        ii = g.index.to_numpy()
        z = up0[ii[0]]
        for i in ii:
            rate = (
                s * np.exp(-max(L[i], 0.0) / lam)
                if np.isfinite(L[i])
                else OWN_RATE_F_PER_GAL
            )
            z = z - max(OWN_RATE_F_PER_GAL, rate) * dg[i]
            if np.isfinite(L[i]):
                z = min(z, line_f + fall * L[i])
            out[i] = z
    return out


def fit_zone_mix(
    frame: pd.DataFrame,
    *,
    line_f: float = 105.0,
    fall_f_per_gal: float = 2.0,
    grid: Sequence[tuple[float, float]] = ZONE_MIX_GRID,
    n_boot: int = 2000,
    seed: int = 0,
) -> ZoneMixFit:
    """The mixing pair minimising the mean absolute error against the
    upper probe on the training days (``mixing_frame``), integrated
    from the probe at each onset; then a day bootstrap: ``n_boot``
    weighted resamples of the training days, each's best kept."""
    probe = frame.up.to_numpy()
    tr = ~frame.held.to_numpy(dtype=bool)
    days = frame.day.to_numpy()
    keys = np.unique(days[tr])
    kidx = {k: i for i, k in enumerate(keys)}
    di = np.array([kidx.get(d, -1) for d in days])
    sums = np.zeros((len(grid), len(keys)))
    cnt = np.zeros(len(keys))
    errs = []
    for gi, (s, lam) in enumerate(grid):
        e = np.abs(
            _mix_run(frame, s, lam, line_f=line_f, fall=fall_f_per_gal) - probe
        )
        errs.append(e)
        np.add.at(sums[gi], di[tr], e[tr])
    np.add.at(cnt, di[tr], 1)
    rng = np.random.default_rng(seed)
    picks = []
    for _ in range(n_boot):
        w = np.bincount(
            rng.integers(0, len(keys), len(keys)), minlength=len(keys)
        )
        picks.append(grid[int(np.argmin((sums * w).sum(1) / (cnt * w).sum()))])
    pk = np.array(picks, dtype=float)
    best = int(np.argmin(sums.sum(1) / cnt.sum()))
    s, lam = grid[best]
    e = errs[best]
    return ZoneMixFit(
        zone_mix_f_per_gal=float(s),
        zone_mix_gal=float(lam),
        mae_train=float(e[tr].mean()),
        mae_held=float(e[~tr].mean()) if (~tr).any() else float("nan"),
        s_interval=tuple(np.percentile(pk[:, 0], [2.5, 50, 97.5])),
        lam_interval=tuple(np.percentile(pk[:, 1], [2.5, 50, 97.5])),
    )


def _draw_kw(params: HeaterParams) -> dict[str, Any]:
    d = params.draw
    return {
        "draw_observability": d.observability
        if d.observability is not None
        else 1.0,
        "draw_inlet_temp_f": d.inlet_temp_f,
        "tmv_delivery_intercept_f": d.delivery_intercept_f,
        "tmv_delivery_slope": d.delivery_slope,
        "draw_gap_open_f_per_gal": d.gap_open_f_per_gal,
        "tank": params.tank,
    }


def front_frame(
    walk: pd.DataFrame,
    draws: Sequence[tuple[datetime, datetime, float]],
    params: HeaterParams,
    *,
    split: datetime,
) -> pd.DataFrame:
    """Every step of each long draw from its onset to its end: the base
    zones (``up``, ``lo``: the calibrated draw response chained from the
    onset probes, a stand-in for a full replay's), the lower probe
    (``pl``), the book's cold region after the step, the day and whether
    it is held out."""
    t = _epochs(walk)
    per_step = (
        (walk.t.iloc[1] - walk.t.iloc[0]).total_seconds() / 60.0
        if len(walk) > 1
        else 10 / 60
    )
    kw = _draw_kw(params)
    rows = []
    for a, b, _ in draws:
        i = int(np.searchsorted(t, a.timestamp()))
        j = int(np.searchsorted(t, b.timestamp()))
        w = walk.iloc[i : j + 1]
        if w.empty:
            continue
        pu, plo = float(w.up.iloc[0]), float(w.lo.iloc[0])
        for k in range(len(w)):
            r = w.iloc[k]
            if k > 0 and r.house > params.book.draw_gpm:
                pu, plo = draw_step(pu, plo, r.house * per_step, **kw)
            rows.append(
                (
                    a,
                    pd.Timestamp(a).strftime("%Y-%m-%d"),
                    r.t,
                    pu,
                    plo,
                    r.lo,
                    r.cold_gal_after,
                    r.cold_f_after,
                )
            )
    f = pd.DataFrame(
        rows, columns=["ev", "day", "t", "up", "lo", "pl", "cold_gal", "cold_f"]
    )
    f = cast(
        pd.DataFrame,
        f.loc[np.isfinite(f.cold_gal) & np.isfinite(f.pl)].reset_index(
            drop=True
        ),
    )
    f["held"] = [pd.Timestamp(e) >= pd.Timestamp(split) for e in f.ev]
    return f


@dataclass(frozen=True)
class FrontFit:
    """Where the lower probe sits in the cold front and how wide the
    front is (``BookParams.lower_probe_gal``, ``front_width_gal``): the
    best on the training draws, its errors, and the day bootstrap's
    2.5 / 50 / 97.5 percentiles."""

    lower_probe_gal: float
    front_width_gal: float
    mae_train: float
    mae_held: float
    place_interval: tuple[float, float, float]
    width_interval: tuple[float, float, float]


def _front_run(f: pd.DataFrame, vp: float, w: float) -> np.ndarray:
    """The lower zone through each draw: the base's rise kept (heat, or
    the gap closing), each fall the front's passage over the probe band
    instead, floored at the cold region."""
    lo, up = f.lo.to_numpy(), f.up.to_numpy()
    cg, cf = f.cold_gal.to_numpy(), f.cold_f.to_numpy()
    ev = f.ev.to_numpy()
    starts = np.r_[True, ev[1:] != ev[:-1]]
    th = np.clip(0.5 - (cg - vp) / w, 0.0, 1.0)
    out = np.empty_like(lo)
    for i in range(len(lo)):
        if starts[i]:
            out[i] = lo[i]
            continue
        dphys = lo[i] - lo[i - 1]
        dfront = min(-(th[i - 1] - th[i]) * (up[i] - cf[i]), 0.0)
        step = dphys + dfront if dphys >= 0.0 else dfront
        out[i] = max(min(cf[i], out[i - 1]), out[i - 1] + step)
    return np.asarray(out)


def fit_front(
    frame: pd.DataFrame,
    *,
    grid: Sequence[tuple[float, float]] = FRONT_GRID,
    n_boot: int = 200,
    seed: int = 1,
) -> FrontFit:
    """The front's place and width minimising the mean absolute error
    against the lower probe on the training draws (``front_frame``),
    then a day bootstrap: ``n_boot`` resamples of the training days,
    each's best kept."""
    pl = frame.pl.to_numpy()
    tr = ~frame.held.to_numpy(dtype=bool)
    days = frame.day.to_numpy()
    E = {g: np.abs(_front_run(frame, *g) - pl) for g in grid}

    def mae(g: tuple[float, float], at: np.ndarray) -> float:
        return float(E[g][at].mean())

    best = min(grid, key=lambda g: mae(g, tr))
    rng = np.random.default_rng(seed)
    keys = np.unique(days[tr])
    idx = {k: np.flatnonzero((days == k) & tr) for k in keys}
    picks = []
    for _ in range(n_boot):
        ii = np.concatenate([idx[k] for k in rng.choice(keys, len(keys))])
        picks.append(min(grid, key=lambda g: mae(g, ii)))
    return FrontFit(
        lower_probe_gal=best[0],
        front_width_gal=float(best[1]),
        mae_train=float(E[best][tr].mean()),
        mae_held=float(E[best][~tr].mean()) if (~tr).any() else float("nan"),
        place_interval=tuple(
            np.percentile([p[0] for p in picks], [2.5, 50, 97.5])
        ),
        width_interval=tuple(
            np.percentile([p[1] for p in picks], [2.5, 50, 97.5])
        ),
    )


def settle_tails(
    walk: pd.DataFrame,
    draws: Sequence[tuple[datetime, datetime, float]],
    params: HeaterParams,
    *,
    split: datetime,
) -> list[dict[str, Any]]:
    """The quiet tail after each long draw: from its last flowing step
    to the first heating, circulation or draw, at most ``SETTLE_TAIL``,
    every ``SETTLE_EVERY`` steps; the front (``lower_probe_gal``,
    ``front_width_gal``) and the calibrated response at the draw's end,
    both coasting by the decay's standby (its UA, the tank's mass)."""
    vp, w = params.book.lower_probe_gal, params.book.front_width_gal
    ua = (
        params.loss.ua_btu_hr_f
        if params.loss.ua_btu_hr_f is not None
        else params.loss.ua_baseline_btu_hr_f
    )
    mass = params.tank.thermal_mass_btu_f
    kw = _draw_kw(params)
    t = _epochs(walk)
    per_step = (
        (walk.t.iloc[1] - walk.t.iloc[0]).total_seconds() / 60.0
        if len(walk) > 1
        else 10 / 60
    )

    def theta(c: float) -> float:
        return min(1.0, max(0.0, 0.5 - (c - vp) / w))

    tails = []
    for a, b, _ in draws:
        i = int(np.searchsorted(t, a.timestamp()))
        stop_at = min(b + SETTLE_TAIL, cast(datetime, walk.t.iloc[-1]))
        j = int(np.searchsorted(t, stop_at.timestamp(), side="right"))
        df = walk.iloc[i:j]
        heat = np.flatnonzero((df.comp | df.elem).to_numpy())
        if len(heat):
            df = df.iloc[: heat[0]]
        if df.empty or np.isnan(df.cold_gal_after.iloc[0]):
            continue
        flow = (df.house > SETTLE_DRAW_GPM).to_numpy()
        inside = (df.t <= pd.Timestamp(b)).to_numpy()
        idx = np.flatnonzero(flow & inside)
        if len(idx) == 0:
            continue
        e = idx[-1]
        pu, plo = float(df.up.iloc[0]), float(df.lo.iloc[0])
        front = plo
        prev_c = df.cold_gal_after.iloc[0]
        for k in range(1, e + 1):
            c = df.cold_gal_after.iloc[k]
            if flow[k]:
                pu, plo = draw_step(pu, plo, df.house.iloc[k] * per_step, **kw)
                dd = (theta(prev_c) - theta(c)) * (
                    df.up.iloc[k] - df.cold_f_after.iloc[k]
                )
                if dd > 0:
                    front = max(min(front, df.cold_f_after.iloc[k]), front - dd)
            prev_c = c
        tail = df.iloc[e + 1 :]
        stop = np.flatnonzero(
            (tail.house > SETTLE_DRAW_GPM).to_numpy()
            | tail.circulating.to_numpy(dtype=bool)
        )
        if len(stop):
            tail = tail.iloc[: stop[0]]
        tail = tail.iloc[::SETTLE_EVERY]
        if len(tail) < 2:
            continue
        hrs = ((tail.t - df.t.iloc[e]).dt.total_seconds() / 3600).to_numpy()
        mean = (tail.up + tail.lo).to_numpy() / 2
        drift = np.cumsum(
            np.r_[0, np.diff(hrs)] * ua * (mean - tail.air.to_numpy()) / mass
        )
        tails.append(
            {
                "ev": a,
                "day": pd.Timestamp(a).strftime("%Y-%m-%d"),
                "held": pd.Timestamp(a) >= pd.Timestamp(split),
                "hrs": hrs,
                "pl": tail.lo.to_numpy(),
                "drift": drift,
                "front": front,
                "phys": plo,
            }
        )
    return tails


def _settle_model(t: dict[str, Any], tau: float) -> np.ndarray:
    s = min(t["front"], t["phys"])
    if tau == 0:
        z = np.full_like(t["hrs"], s)
    elif np.isinf(tau):
        z = np.full_like(t["hrs"], t["front"])
    else:
        z = s + (t["front"] - s) * np.exp(-t["hrs"] * 60 / tau)
    return np.asarray(z - t["drift"])


def _settle_err(tails: Sequence[dict[str, Any]], tau: float) -> float:
    e = [np.abs(_settle_model(t, tau) - t["pl"]) for t in tails]
    return float(np.concatenate(e).mean()) if e else float("nan")


@dataclass(frozen=True)
class SettleFit:
    """The lower zone's settling after a draw (``BookParams.
    front_settle_min``): the best on the training tails over
    ``SETTLE_TAUS``, and over ``SETTLE_TAUS_READ`` (the finer grid the
    shipped value was read from), and the day bootstrap's
    2.5 / 50 / 97.5 percentiles over ``SETTLE_TAUS_FINE``."""

    front_settle_min: float
    front_settle_min_fine: float
    mae_train: float
    mae_held: float
    interval: tuple[float, float, float]


def fit_front_settle(
    tails: Sequence[dict[str, Any]], *, n_boot: int = 200, seed: int = 0
) -> SettleFit:
    """The settling constant from ``settle_tails``."""
    tr = [t for t in tails if not t["held"]]
    te = [t for t in tails if t["held"]]
    best = min(SETTLE_TAUS, key=lambda x: _settle_err(tr, x))
    fine = min(SETTLE_TAUS_READ, key=lambda x: _settle_err(tr, x))
    days = sorted({t["day"] for t in tr})
    by = {d: [t for t in tr if t["day"] == d] for d in days}
    rng = np.random.default_rng(seed)
    picks = []
    for _ in range(n_boot):
        smp = [t for d in rng.choice(days, len(days)) for t in by[d]]
        picks.append(min(SETTLE_TAUS_FINE, key=lambda x: _settle_err(smp, x)))
    return SettleFit(
        front_settle_min=float(best),
        front_settle_min_fine=float(fine),
        mae_train=_settle_err(tr, best),
        mae_held=_settle_err(te, best),
        interval=tuple(np.percentile(picks, [2.5, 50, 97.5])),
    )


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
    line, the median over its running samples, times its minutes."""

    start: datetime
    end: datetime
    minutes: float
    btu: float | None
    flow_gpm: float | None
    upper_f: float | None
    air_f: float | None


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
    median of those in it."""
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
    for a, b in ((c[0], c[1]) for c in clusters if c[1] > c[0]):
        if any(not (b <= s or e <= a) for s, e in compressor):
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
            )
        )
    return out


def run_heat_btu(
    minutes: float,
    upper_f: float,
    air_f: float,
    displaced: float,
    flow_gpm: float,
) -> float:
    """The heat a run takes for its displaced volume: the gallons it
    displaces (``circulation.displaced_gal``) at the upper zone less the
    air, never negative."""
    if displaced <= 0.0 or minutes <= 0.0 or flow_gpm <= 0.0:
        return 0.0
    gal = circulation_displaced_gal(minutes, displaced, flow_gpm)
    return max(0.0, gal * WATER_BTU_PER_GAL_F * (upper_f - air_f))


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


# ── the probes' share of circulation's heat ─────────────────────────
#
# ``DrawParams.ungated_observability``: the run model's heat
# (``run_heat_btu``) is physical, the flow's integral; the tank it is
# charged to is described in the probes' frame, their mean times the
# tank's mass. The factor between the two is measured on windows of
# circulation with nothing else going on, and **against the displaced
# volume it will be used with**: a saturated run's heat is proportional
# to it, so a factor fitted at one volume misprices those runs at
# another. Refit the two together.

#: Minutes after the last run a window stays open: past the probes'
#: lag, and the factor measured flat from 15 minutes to 4 hours.
OBSERVABILITY_SETTLE = timedelta(minutes=30)
#: A compressor this close before a window disqualifies it.
OBSERVABILITY_LEAD = timedelta(minutes=5)
#: Fewer windows than this and the factor is not fitted.
MIN_OBSERVABILITY_WINDOWS = 20
#: A run cannot cost the tank more than its physical heat, and a factor
#: near zero means the fit failed.
OBSERVABILITY_BOUNDS = (0.05, 1.0)


@dataclass(frozen=True)
class CirculationWindow:
    """One window's evidence, independent of the displaced volume: its
    runs ``(minutes, upper zone at start)``, the air over it, the heat
    the probes lost to the runs (the mean's fall times the tank's mass,
    less standby and the draws' heat), BTU, its length, the gallons
    drawn in it, and the flow its runs ran at (None: the caller's)."""

    runs: tuple[tuple[float, float], ...]
    air_f: float
    apparent_btu: float
    hours: float
    draw_gal: float
    flow_gpm: float | None = None


def _last_at(
    values: np.ndarray, seconds: np.ndarray, at: datetime
) -> float | None:
    ok = np.isfinite(values) & (seconds <= at.timestamp())
    return float(values[ok][-1]) if ok.any() else None


def circulation_windows(
    history: pd.DataFrame,
    circulation: Sequence[tuple[datetime, datetime]],
    params: HeaterParams,
    *,
    draws: Sequence[tuple[datetime, float]],
    settle: timedelta = OBSERVABILITY_SETTLE,
    flow_at: Callable[[datetime], float | None] | None = None,
) -> list[CirculationWindow]:
    """The clean circulation windows in ``history`` (``sa.history``'s:
    the probes, ``compressor_on``, ``air_f``). Each opens at a run and
    closes ``settle`` after the last run that starts before it would,
    so a chain of runs is one window and every run in it is charged. A
    window is left out when the compressor runs within
    ``OBSERVABILITY_LEAD`` before it or in it, or when a draw in it has
    no size (a NaN in ``draws``: its heat cannot be added back); a sized
    draw is charged through the draw term at the window's starting upper
    zone. Standby is the loss law's (``params.loss``) at the mean over
    the air; with no loss law fitted there are no windows. ``flow_at``
    gives each window's runs the flow they ran at (``flow_lookup``)."""
    when = _instants(history)
    seconds = np.array([t.timestamp() for t in when])
    upper, lower = _floats(history, "upper_f"), _floats(history, "lower_f")
    air = _floats(history, "air_f")
    compressor = _on_intervals(
        when, history["compressor_on"].fillna(False).astype(bool).to_numpy()
    )
    loss, d = params.loss, params.draw
    if loss.ua_btu_hr_f is None:
        # No loss law to take standby off with.
        return []
    ua_ref = loss.ua_btu_hr_f
    corpus = sorted(circulation)
    out: list[CirculationWindow] = []
    i = 0
    while i < len(corpus):
        start, end = corpus[i]
        j = i + 1
        while j < len(corpus) and corpus[j][0] <= end + settle:
            end = max(end, corpus[j][1])
            j += 1
        i = j
        close = end + settle
        lead = start - OBSERVABILITY_LEAD
        inside = [g for t, g in draws if lead <= t <= close]
        if any(math.isnan(g) for g in inside):
            continue
        if any(not (close <= s or e <= lead) for s, e in compressor):
            continue
        at0 = start - timedelta(seconds=10)
        u0, l0 = _last_at(upper, seconds, at0), _last_at(lower, seconds, at0)
        u1, l1 = (
            _last_at(upper, seconds, close),
            _last_at(lower, seconds, close),
        )
        span = (seconds >= start.timestamp()) & (seconds <= close.timestamp())
        amb = (
            float(np.nanmean(air[span]))
            if span.any() and np.isfinite(air[span]).any()
            else math.nan
        )
        runs = _in_cycle(None, circulation, upper, seconds, at0, close)[
            "circulation_runs"
        ]
        if (
            u0 is None
            or l0 is None
            or u1 is None
            or l1 is None
            or not runs
            or not math.isfinite(amb)
        ):
            continue
        m0, m1 = (u0 + l0) / 2, (u1 + l1) / 2
        hours = (close - start).total_seconds() / 3600
        dt = (m0 + m1) / 2 - amb
        standby = (
            ua_at(dt, ua_ref, loss.ua_exponent, loss.ua_ref_delta_t_f)
            * max(dt, 0.0)
            * hours
        )
        gal = float(sum(inside))
        draw_btu = 0.0
        if gal > 0.0 and d.observability is not None:
            draw_btu = draw_energy_btu(
                gal,
                u0,
                delivery_temp_f(u0, d.delivery_intercept_f, d.delivery_slope),
                d.inlet_temp_f,
                d.observability,
            )
        out.append(
            CirculationWindow(
                runs=cast(tuple[tuple[float, float], ...], runs),
                air_f=amb,
                apparent_btu=(m0 - m1) * params.tank.thermal_mass_btu_f
                - standby
                - draw_btu,
                hours=hours,
                draw_gal=gal,
                flow_gpm=None if flow_at is None else flow_at(start),
            )
        )
    return out


def fit_ungated_observability(
    windows: Sequence[CirculationWindow],
    displaced_gal: float,
    flow_gpm: float,
) -> tuple[float, int] | None:
    """``DrawParams.ungated_observability``: the windows' apparent heat
    over the run model's (``run_heat_btu``) at ``displaced_gal``, a ratio
    of sums, and the windows it rests on. None with fewer than
    ``MIN_OBSERVABILITY_WINDOWS`` carrying modelled heat, or a ratio
    outside ``OBSERVABILITY_BOUNDS``."""
    if displaced_gal <= 0.0:
        return None
    pairs = [
        (
            w.apparent_btu,
            sum(
                run_heat_btu(
                    minutes,
                    upper,
                    w.air_f,
                    displaced_gal,
                    w.flow_gpm if w.flow_gpm is not None else flow_gpm,
                )
                for minutes, upper in w.runs
            ),
        )
        for w in windows
    ]
    pairs = [(a, m) for a, m in pairs if m > 0.0]
    if len(pairs) < MIN_OBSERVABILITY_WINDOWS:
        return None
    factor = sum(a for a, _ in pairs) / sum(m for _, m in pairs)
    lo, hi = OBSERVABILITY_BOUNDS
    if not lo <= factor <= hi:
        return None
    return factor, len(pairs)


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
