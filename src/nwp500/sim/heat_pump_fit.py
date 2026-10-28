"""Measuring a heat pump's recoveries from a heater's history: how long
the lower probe holds at a start, how long the compressor runs past its
target, and the heat it puts into the tank and the power it draws while
the tank climbs. No model of the cycle: what a model of it should be
fitted to.

The history is ``sim.calibration``'s frame, and its recoveries are
``calibration.heat_pump_cycles``'. ``recovery_frame`` puts each on a
minute grid, with each minute's phase:

- **hold**: from the start until the lower probe reads above its
  reading from before the start and stays above it for ``CLIMB_HELD``,
  while the refrigerant circuit and the condenser warm;
- **climb**: from there until the lower probe reaches the target;
- **run_on**: from there until the compressor stops.

``start_holds``, ``run_ons``, ``climb_heat`` and ``power_blocks``
measure from that frame, and ``fit_heat_pump`` fits the heat pump's
parameters on them (``evidence``): the heat's and the power's maps
(``physics.heat_pump``), the hold by time off, and the overshoot at
the stop.
"""

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import cast

import numpy as np
import pandas as pd

from nwp500.sim import history_frame as hf
from nwp500.sim.calibration import (
    DRAW_LEAD,
    REACHED_TOLERANCE_F,
    heat_pump_cycles,
    water_in_use,
    water_over,
)
from nwp500.sim.params import (
    MAP_REF_AIR_F,
    MAP_REF_WATER_F,
    CompressorParams,
    HeaterParams,
)
from nwp500.sim.physics import heat_pump as hp
from nwp500.sim.physics import stratified as st
from nwp500.sim.units import BTU_PER_WH, WATER_BTU_PER_GAL_F

#: The grid a recovery is read on.
GRID = timedelta(minutes=1)
GRID_MINUTES = GRID.total_seconds() / 60.0
#: A minute is mixed with the upper probe within this of the lower, °F:
#: from below (an inversion, the condenser heating the bottom) or
#: above.
MIXED_BELOW_F = 5.0
MIXED_ABOVE_F = 1.0
#: The shortest stretch a heating rate is fitted on, minutes: a probe
#: reports in 0.18 °F steps, under two minutes of a recovery's climb.
MIN_STRETCH_MINUTES = 20
#: How long the lower probe must stay above its reading from before a
#: start for its climb to have begun: a probe at rest flips a 0.18 °F
#: step and back. At one installation (94 clean starts, December 2025
#: to October 2026), requiring 5 minutes took the median hold after
#: 3-12 hours off from 6.0 to 18.0 minutes and after over 12 hours from
#: 18.0 to 22.0; within 3 hours of a stop it did not move.
CLIMB_HELD = timedelta(minutes=5)
#: The blocks power is averaged over, minutes.
POWER_BLOCK_MINUTES = 10

PHASES = ("hold", "climb", "run_on")

_FRAME_COLUMNS = (
    "cycle",
    "at",
    "minute",
    "phase",
    "upper_f",
    "lower_f",
    "gap_f",
    "mixed",
    "water",
    "air_f",
    "humidity_pct",
    "power_w",
    "target_f",
    "draw_free",
    "start_clean",
    "minutes_off",
)


def _held(
    values: np.ndarray, seconds: np.ndarray, at: np.ndarray
) -> np.ndarray:
    """``values``' last finite reading at or before each of ``at``
    (epoch seconds); NaN before the first."""
    ok = np.isfinite(values)
    v, s = values[ok], seconds[ok]
    if not len(v):
        return np.full(len(at), np.nan)
    k = np.searchsorted(s, at, side="right") - 1
    return np.where(k >= 0, v[np.maximum(k, 0)], np.nan)


def _first_above(
    values: np.ndarray,
    seconds: np.ndarray,
    level: float,
    held: timedelta = timedelta(0),
) -> float | None:
    """The first sample reading above ``level`` with every sample to
    ``held`` after it above it too, epoch seconds; None if none does."""
    above = values > level
    span = held.total_seconds()
    for k in np.flatnonzero(above):
        stop = int(np.searchsorted(seconds, seconds[k] + span, side="right"))
        if above[k:stop].all():
            return float(seconds[k])
    return None


@dataclass(frozen=True)
class _Cycle:
    """A recovery's phase boundaries, epoch seconds."""

    climb: float | None
    reach: float | None


def _phases(
    lower: np.ndarray,
    seconds: np.ndarray,
    start: datetime,
    end: datetime,
    target: float,
) -> _Cycle:
    """Where a recovery's climb and run-on begin (``PHASES``), from the
    lower probe's samples ``[start, end]``: None for a phase it never
    reached."""
    a, b = start.timestamp(), end.timestamp()
    inside = (seconds >= a) & (seconds <= b) & np.isfinite(lower)
    lo, s = lower[inside], seconds[inside]
    # The reading in force before the start: the start's own sample can
    # already hold the dip.
    before = hf.asof(lower, seconds, start - timedelta(microseconds=1))
    if before is None or not len(lo):
        return _Cycle(None, None)
    climb = _first_above(lo, s, before, CLIMB_HELD)
    reach = _first_above(lo, s, target - REACHED_TOLERANCE_F - 1e-9)
    if climb is not None and reach is not None:
        climb = min(climb, reach)
    return _Cycle(climb, reach)


def recovery_frame(
    history: pd.DataFrame, *, air: str = "air_f"
) -> pd.DataFrame:
    """Each heat-pump recovery (``calibration.heat_pump_cycles``) on a
    ``GRID``, ``[start, end)``, a row a minute. Its columns: ``cycle``
    (the run's ``n``), ``at``, ``minute`` (since the start), ``phase``
    (``PHASES``), the probes as of the minute and ``gap_f`` (upper less
    lower), ``mixed`` (``MIXED_BELOW_F``, ``MIXED_ABOVE_F``), ``water``
    (``calibration.water_in_use``), the ``air`` column's reading
    (the sensor's by default) and ``humidity_pct``, ``power_w``,
    ``target_f``, the run's ``draw_free`` and ``start_clean`` (no water
    in use from ``calibration.DRAW_LEAD`` before it to the end of its
    hold, read as ``draw_free`` is), and ``minutes_off`` (since the run
    before it stopped; NaN for the history's first, or with the heater
    unrecorded since). ``water`` is any sample in force over the minute
    reading water in use."""
    cycles = heat_pump_cycles(history)
    if not cycles:
        return pd.DataFrame(columns=list(_FRAME_COLUMNS))
    when = hf.instants(history)
    seconds = np.array([t.timestamp() for t in when])
    lower_f = hf.floats(history, "lower_f")
    upper_f = hf.floats(history, "upper_f")
    columns = {
        "upper_f": upper_f,
        "lower_f": lower_f,
        "air_f": hf.floats(history, air),
        "humidity_pct": hf.floats(history, "humidity_pct"),
        "power_w": hf.floats(history, "power_w"),
        "target_f": hf.floats(history, "target_f"),
    }
    index = pd.DatetimeIndex(history.index)
    tier1, water = water_in_use(history)
    # Water in use at any sample up to each one: a minute is wet with
    # one inside it.
    wet = np.concatenate(([0], np.cumsum(water)))
    parts: list[pd.DataFrame] = []
    for c in cycles:
        a, b = c.start.timestamp(), c.end.timestamp()
        step = GRID.total_seconds()
        # The grid's instants from the start's own, to the nanosecond.
        at = pd.date_range(
            pd.Timestamp(c.start),
            periods=math.ceil((b - a) / step),
            freq=GRID,
        )
        grid = a + step * np.arange(len(at))
        bounds = _phases(lower_f, seconds, c.start, c.end, c.target_f)
        climb = math.inf if bounds.climb is None else bounds.climb
        reach = math.inf if bounds.reach is None else bounds.reach
        phase = np.where(
            grid < climb, "hold", np.where(grid < reach, "climb", "run_on")
        )
        held = {k: _held(v, seconds, grid) for k, v in columns.items()}
        held["target_f"] = np.where(
            np.isfinite(held["target_f"]), held["target_f"], c.target_f
        )
        # The samples in force over each minute: the one at its start to
        # the last before the next.
        first = np.maximum(np.searchsorted(seconds, grid, side="right") - 1, 0)
        last = np.searchsorted(seconds, grid + step, side="left")
        minute_wet = wet[np.maximum(last, first + 1)] > wet[first]
        # The climb's first sample, as the history holds its instant.
        held_to = (
            c.end
            if math.isinf(climb)
            else min(c.end, when[int(np.searchsorted(seconds, climb))])
        )
        start_clean = not water_over(
            index, water, tier1, c.start - DRAW_LEAD, held_to
        )
        gap = held["upper_f"] - held["lower_f"]
        off = (
            math.nan
            if c.stopped_at is None
            else (c.start - c.stopped_at).total_seconds() / 60.0
        )
        parts.append(
            pd.DataFrame(
                {
                    "cycle": c.n,
                    "at": at,
                    "minute": (grid - a) / 60.0,
                    "phase": phase,
                    **held,
                    "gap_f": gap,
                    "mixed": (gap >= -MIXED_BELOW_F) & (gap <= MIXED_ABOVE_F),
                    "water": minute_wet,
                    "draw_free": c.draw_free,
                    "start_clean": start_clean,
                    "minutes_off": off,
                },
                columns=list(_FRAME_COLUMNS),
            )
        )
    return pd.concat(parts, ignore_index=True)


def _cycles(frame: pd.DataFrame) -> list[pd.DataFrame]:
    return [g for _, g in frame.groupby("cycle", sort=True)]


def start_holds(frame: pd.DataFrame) -> pd.DataFrame:
    """Each recovery's hold (``recovery_frame``): ``cycle``, ``start``,
    ``minutes_off``, ``hold_minutes`` (to the climb's first minute; NaN
    for a run that never climbed), ``lower_f`` at the start,
    ``draw_free`` and ``start_clean``: the hold is measured on the
    clean starts."""
    rows: list[dict[str, object]] = []
    for g in _cycles(frame):
        climbing = g["phase"].to_numpy() != "hold"
        minutes = g["minute"].to_numpy(dtype=float)
        rows.append(
            {
                "cycle": int(g["cycle"].iloc[0]),
                "start": g["at"].iloc[0],
                "minutes_off": float(g["minutes_off"].iloc[0]),
                "hold_minutes": (
                    float(minutes[np.argmax(climbing)])
                    if climbing.any()
                    else math.nan
                ),
                "lower_f": float(g["lower_f"].iloc[0]),
                "draw_free": bool(g["draw_free"].iloc[0]),
                "start_clean": bool(g["start_clean"].iloc[0]),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "cycle",
            "start",
            "minutes_off",
            "hold_minutes",
            "lower_f",
            "draw_free",
            "start_clean",
        ],
    )


@dataclass(frozen=True)
class RunOnFit:
    """Two rules for when a compressor stops past its target, each
    judged leaving each recovery out of its own median:

    - ``minutes``: a fixed run-on after the lower probe reaches the
      target, the median of ``n`` recoveries' run-ons;
    - ``overshoot_f``: the lower probe passing the target by the median
      overshoot at the stop.

    ``*_mae_min``: the mean absolute error each puts on the stop,
    minutes, over the same recoveries; None with under three.
    ``unstopped``: the recoveries the overshoot rule could not place a
    stop on (a run-on that did not climb), left out of both."""

    n: int
    minutes: float | None
    overshoot_f: float | None
    minutes_mae_min: float | None
    overshoot_mae_min: float | None
    unstopped: int = 0


def _crossing_minute(
    minutes: np.ndarray, lower: np.ndarray, level: float
) -> float | None:
    """The minute the lower probe first reads ``level`` or above over a
    run-on; past its last minute, extrapolated at the run-on's rate;
    None if it did not climb."""
    hit = np.flatnonzero(lower >= level - 1e-9)
    if len(hit):
        return float(minutes[hit[0]])
    rise = float(lower[-1] - lower[0])
    span = float(minutes[-1] - minutes[0])
    if rise <= 0.0 or span <= 0.0:
        return None
    return float(minutes[-1]) + (level - float(lower[-1])) * span / rise


def run_ons(frame: pd.DataFrame) -> tuple[pd.DataFrame, RunOnFit]:
    """Each recovery that reached its target with the target unchanged
    through it (``recovery_frame``): ``cycle``, ``start``, ``target_f``,
    ``reached_minute`` and ``end_minute`` (since the start),
    ``run_on_minutes``, ``overshoot_f`` (the lower probe at the stop
    less the target) and ``draw_free``; and the two stop rules judged
    on the draw-free ones (``RunOnFit``)."""
    rows: list[dict[str, object]] = []
    traces: list[tuple[np.ndarray, np.ndarray]] = []
    for g in _cycles(frame):
        target = g["target_f"].to_numpy(dtype=float)
        run_on = g["phase"].to_numpy() == "run_on"
        if not run_on.any() or float(np.ptp(target)) > 0.01:
            continue
        minutes = g["minute"].to_numpy(dtype=float)
        lower = g["lower_f"].to_numpy(dtype=float)
        reached = float(minutes[np.argmax(run_on)])
        end = float(minutes[-1]) + GRID_MINUTES
        rows.append(
            {
                "cycle": int(g["cycle"].iloc[0]),
                "start": g["at"].iloc[0],
                "target_f": float(target[0]),
                "reached_minute": reached,
                "end_minute": end,
                "run_on_minutes": end - reached,
                "overshoot_f": float(lower[-1] - target[0]),
                "draw_free": bool(g["draw_free"].iloc[0]),
            }
        )
        traces.append((minutes[run_on], lower[run_on]))
    found = pd.DataFrame(
        rows,
        columns=[
            "cycle",
            "start",
            "target_f",
            "reached_minute",
            "end_minute",
            "run_on_minutes",
            "overshoot_f",
            "draw_free",
        ],
    )
    free = found["draw_free"].to_numpy(dtype=bool)
    keep = np.flatnonzero(free)
    runs = found["run_on_minutes"].to_numpy(dtype=float)[keep]
    over = found["overshoot_f"].to_numpy(dtype=float)[keep]
    if not len(keep):
        return found, RunOnFit(0, None, None, None, None)
    fit_minutes, fit_over = float(np.median(runs)), float(np.median(over))
    if len(keep) < 3:
        return found, RunOnFit(len(keep), fit_minutes, fit_over, None, None)
    ends = found["end_minute"].to_numpy(dtype=float)[keep]
    reached = found["reached_minute"].to_numpy(dtype=float)[keep]
    targets = found["target_f"].to_numpy(dtype=float)[keep]
    by_minutes: list[float] = []
    by_over: list[float] = []
    unstopped = 0
    for j, i in enumerate(keep):
        rest = np.delete(np.arange(len(keep)), j)
        level = targets[j] + float(np.median(over[rest]))
        stop = _crossing_minute(*traces[int(i)], level)
        if stop is None:
            # Both rules on the same recoveries, or neither.
            unstopped += 1
            continue
        by_over.append(abs(stop + GRID_MINUTES - ends[j]))
        by_minutes.append(
            abs(reached[j] + float(np.median(runs[rest])) - ends[j])
        )
    return found, RunOnFit(
        len(keep),
        fit_minutes,
        fit_over,
        float(np.mean(by_minutes)) if by_minutes else None,
        float(np.mean(by_over)) if by_over else None,
        unstopped,
    )


def _stretches(ok: np.ndarray) -> list[tuple[int, int]]:
    """The runs of True in ``ok``: ``[i, j)``."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], ok.astype(int), [0]))))
    return [
        (int(i), int(j)) for i, j in zip(edges[::2], edges[1::2], strict=True)
    ]


def _mean(values: np.ndarray) -> float:
    """The finite values' mean; NaN with none."""
    ok = np.isfinite(values)
    return float(np.mean(values[ok])) if ok.any() else math.nan


_HEAT_COLUMNS = (
    "cycle",
    "start",
    "minutes",
    "water_f",
    "lower_f",
    "air_f",
    "humidity_pct",
    "rise_f_h",
    "loss_btu_h",
    "heat_btu_h",
    "power_w",
    "cop",
)


def climb_heat(
    frame: pd.DataFrame,
    params: HeaterParams,
    *,
    min_minutes: int = MIN_STRETCH_MINUTES,
) -> pd.DataFrame:
    """The heat a recovery puts into the tank, from its draw-free climbs
    with the tank mixed (``recovery_frame``): the probes' mean is then
    the tank's, and the heat is its mass times the mean's rise (a
    least-squares slope over at least ``min_minutes``) plus what the
    tank ``params`` lay out loses at that temperature, mixed: its sides',
    top's and bottom's UA (``physics.stratified.layout``) against the
    air. A row a stretch:
    ``cycle``, ``start``, ``minutes``, ``water_f`` (the mean's mean),
    ``lower_f``, ``air_f``, ``humidity_pct``, ``rise_f_h``,
    ``loss_btu_h``, ``heat_btu_h``, the metered ``power_w`` (NaN
    without a reading) and ``cop`` (the heat over the power)."""
    lay = st.layout(params)
    mass = lay.volume_gal * WATER_BTU_PER_GAL_F
    ua = lay.ua_btu_hr_f + lay.ua_top_btu_hr_f + lay.ua_bottom_btu_hr_f
    rows: list[dict[str, object]] = []
    for g in _cycles(frame):
        if not bool(g["draw_free"].iloc[0]):
            continue
        ok = (
            (g["phase"].to_numpy() == "climb")
            & g["mixed"].to_numpy(dtype=bool)
            & ~g["water"].to_numpy(dtype=bool)
            & np.isfinite(g["air_f"].to_numpy(dtype=float))
        )
        for i, j in _stretches(ok):
            if j - i < min_minutes:
                continue
            s = g.iloc[i:j]
            minutes = s["minute"].to_numpy(dtype=float)
            mean = (
                s["upper_f"].to_numpy(dtype=float)
                + s["lower_f"].to_numpy(dtype=float)
            ) / 2.0
            rise = float(np.polyfit(minutes, mean, 1)[0]) * 60.0
            water = float(np.mean(mean))
            air = float(np.mean(s["air_f"].to_numpy(dtype=float)))
            lost = ua * (water - air)
            heat = mass * rise + lost
            power = _mean(s["power_w"].to_numpy(dtype=float))
            rows.append(
                {
                    "cycle": int(s["cycle"].iloc[0]),
                    "start": s["at"].iloc[0],
                    "minutes": j - i,
                    "water_f": water,
                    "lower_f": _mean(s["lower_f"].to_numpy(dtype=float)),
                    "air_f": air,
                    "humidity_pct": _mean(
                        s["humidity_pct"].to_numpy(dtype=float)
                    ),
                    "rise_f_h": rise,
                    "loss_btu_h": lost,
                    "heat_btu_h": heat,
                    "power_w": power,
                    "cop": heat / (power * BTU_PER_WH)
                    if power > 0.0
                    else math.nan,
                }
            )
    return pd.DataFrame(rows, columns=list(_HEAT_COLUMNS))


_POWER_COLUMNS = (
    "cycle",
    "start",
    "phase",
    "lower_f",
    "upper_f",
    "gap_f",
    "mixed",
    "air_f",
    "power_w",
    "draw_free",
)


def power_blocks(
    frame: pd.DataFrame, *, block_minutes: int = POWER_BLOCK_MINUTES
) -> pd.DataFrame:
    """The power a recovery draws, metered, over blocks of
    ``block_minutes`` within one phase (``recovery_frame``), the tank
    stratified or mixed: ``cycle``, ``start``, ``phase``, the probes'
    and the gap's means, ``mixed`` (every minute of it), ``air_f``,
    ``power_w`` and the run's ``draw_free``. A block with a minute
    unmetered is left out."""
    rows: list[dict[str, object]] = []
    for g in _cycles(frame):
        phase = g["phase"].to_numpy()
        for name in PHASES:
            for i, j in _stretches(phase == name):
                for a in range(i, j - block_minutes + 1, block_minutes):
                    s = g.iloc[a : a + block_minutes]
                    watts = s["power_w"].to_numpy(dtype=float)
                    if not np.isfinite(watts).all():
                        continue
                    rows.append(
                        {
                            "cycle": int(s["cycle"].iloc[0]),
                            "start": s["at"].iloc[0],
                            "phase": name,
                            "lower_f": float(s["lower_f"].mean()),
                            "upper_f": float(s["upper_f"].mean()),
                            "gap_f": float(s["gap_f"].mean()),
                            "mixed": bool(s["mixed"].all()),
                            "air_f": float(s["air_f"].mean()),
                            "power_w": float(watts.mean()),
                            "draw_free": bool(s["draw_free"].iloc[0]),
                        }
                    )
    return pd.DataFrame(rows, columns=list(_POWER_COLUMNS))


# ── the heat pump's parameters, fitted on these measures ────────────

#: Fewer than these and a part is not fitted: stretches for the heat,
#: climb blocks for the power, starts in a band for its hold, and
#: draw-free run-ons for the overshoot.
MIN_HEAT_STRETCHES = 10
MIN_POWER_BLOCKS = 30
MIN_BAND_STARTS = 3
MIN_RUN_ONS = 5
#: What a fitted map may claim anywhere over its domain, checked on a
#: ``CHECK_POINTS`` × ``CHECK_POINTS`` grid: a COP no more than
#: ``CARNOT_SHARE`` of the ideal heat pump's between the air and the
#: water, heat taken from the air (not given to it), and at least
#: ``MIN_POWER_W``.
CARNOT_SHARE = 0.6
MIN_POWER_W = 50.0
CHECK_POINTS = 8


@dataclass(frozen=True)
class Evidence:
    """What the heat pump's parameters are fitted on, each in time
    order: ``climb_heat``'s stretches, ``power_blocks``' climb blocks
    with their air, lower tank and power read, the clean starts with
    their time off and hold known (``start_holds``), and the draw-free
    run-ons (``run_ons``)."""

    heat: pd.DataFrame
    power: pd.DataFrame
    holds: pd.DataFrame
    runs: pd.DataFrame


def evidence(
    history: pd.DataFrame,
    params: HeaterParams,
    *,
    air: str = "air_f",
) -> Evidence:
    """``Evidence`` from ``history`` (``recovery_frame``, read with
    ``air``), the heat priced against the loss of the tank ``params``
    lay out (``climb_heat``)."""
    frame = recovery_frame(history, air=air)
    heat = climb_heat(frame, params).dropna(
        subset=["air_f", "water_f", "heat_btu_h"]
    )
    blocks = power_blocks(frame)
    power = blocks.loc[blocks["phase"] == "climb"].dropna(
        subset=["air_f", "lower_f", "power_w"]
    )
    holds = start_holds(frame)
    holds = holds.loc[holds["start_clean"].astype(bool)].dropna(
        subset=["minutes_off", "hold_minutes"]
    )
    runs, _ = run_ons(frame)
    runs = runs.loc[runs["draw_free"].astype(bool)]
    return Evidence(
        *(
            cast(pd.DataFrame, d.sort_values("start").reset_index(drop=True))
            for d in (heat, power, holds, runs)
        )
    )


@dataclass(frozen=True)
class Plane:
    """A map's plane: its value at ``params.MAP_REF_AIR_F`` air and
    ``params.MAP_REF_WATER_F`` water, its slopes per °F of each, and the
    air and the water it was fitted over, to the whole degree (None:
    the parameters' own)."""

    level: float
    per_air: float
    per_water: float
    air_f: tuple[float, float] | None = None
    water_f: tuple[float, float] | None = None


def _span(values: np.ndarray) -> tuple[float, float]:
    return (
        float(math.floor(float(np.min(values)))),
        float(math.ceil(float(np.max(values)))),
    )


def _fit_plane(
    air: np.ndarray, water: np.ndarray, y: np.ndarray, weight: np.ndarray
) -> Plane | None:
    """The weighted least-squares plane through ``y``; None when the
    air and the water do not place one."""
    x = np.column_stack(
        [np.ones(len(y)), air - MAP_REF_AIR_F, water - MAP_REF_WATER_F]
    )
    w = np.sqrt(weight)[:, None]
    if np.linalg.matrix_rank(x * w) < 3:
        return None
    coef, *_ = np.linalg.lstsq(x * w, y * w[:, 0], rcond=None)
    return Plane(
        float(coef[0]),
        float(coef[1]),
        float(coef[2]),
        _span(air),
        _span(water),
    )


def _columns(rows: pd.DataFrame, *names: str) -> list[np.ndarray]:
    return [rows[n].to_numpy(dtype=float) for n in names]


def fit_heat_map(rows: pd.DataFrame) -> Plane | None:
    """The heat's plane through ``Evidence.heat``'s stretches, each
    weighted by its minutes, in the air and the tank's mean (the tank
    is mixed); None with fewer than ``MIN_HEAT_STRETCHES``."""
    if len(rows) < MIN_HEAT_STRETCHES:
        return None
    air, water, heat, minutes = _columns(
        rows, "air_f", "water_f", "heat_btu_h", "minutes"
    )
    return _fit_plane(air, water, heat, minutes)


def fit_power_map(rows: pd.DataFrame) -> Plane | None:
    """The power's plane through ``Evidence.power``'s blocks, in the
    air and the lower tank; None with fewer than ``MIN_POWER_BLOCKS``."""
    if len(rows) < MIN_POWER_BLOCKS:
        return None
    air, water, power = _columns(rows, "air_f", "lower_f", "power_w")
    return _fit_plane(air, water, power, np.ones(len(rows)))


def heat_map_error(rows: pd.DataFrame, c: CompressorParams) -> float | None:
    """``c``'s heat against ``Evidence.heat``'s stretches: the RMS
    error weighted by their minutes, BTU/h; None with none."""
    if rows.empty:
        return None
    air, water, heat, minutes = _columns(
        rows, "air_f", "water_f", "heat_btu_h", "minutes"
    )
    got = np.array(
        [hp.heat_btu_h(c, a, w) for a, w in zip(air, water, strict=True)]
    )
    return float(np.sqrt(np.average((got - heat) ** 2, weights=minutes)))


def power_map_error(rows: pd.DataFrame, c: CompressorParams) -> float | None:
    """``c``'s power against ``Evidence.power``'s blocks: the RMS
    error, W; None with none."""
    if rows.empty:
        return None
    air, water, power = _columns(rows, "air_f", "lower_f", "power_w")
    got = np.array(
        [hp.power_w(c, a, w) for a, w in zip(air, water, strict=True)]
    )
    return float(np.sqrt(np.mean((got - power) ** 2)))


def fit_start_hold(
    rows: pd.DataFrame, c: CompressorParams
) -> tuple[float, ...] | None:
    """The hold by time off: each of ``c``'s bands
    (``CompressorParams.start_hold_after_min``) the median of
    ``Evidence.holds``' starts in it, or ``c``'s own with fewer than
    ``MIN_BAND_STARTS`` there; None when no band has as many."""
    off, held = _columns(rows, "minutes_off", "hold_minutes")
    band = np.searchsorted(c.start_hold_after_min, off, side="right")
    out: list[float] = []
    fitted = False
    for i, base in enumerate(c.start_hold_min):
        inside = held[band == i]
        if len(inside) >= MIN_BAND_STARTS:
            out.append(float(np.median(inside)))
            fitted = True
        else:
            out.append(base)
    return tuple(out) if fitted else None


def start_hold_error(rows: pd.DataFrame, c: CompressorParams) -> float | None:
    """``c``'s hold against ``Evidence.holds``' starts: the mean
    absolute error, minutes; None with none."""
    if rows.empty:
        return None
    off, held = _columns(rows, "minutes_off", "hold_minutes")
    got = np.array([hp.start_hold_min(c, float(o)) for o in off])
    return float(np.mean(np.abs(got - held)))


def fit_overshoot(rows: pd.DataFrame) -> float | None:
    """The median overshoot at the stop of ``Evidence.runs``' run-ons,
    °F (``run_ons``), at least 0: a heater does not stop short of its
    target on its own; None with fewer than ``MIN_RUN_ONS``."""
    if len(rows) < MIN_RUN_ONS:
        return None
    return max(0.0, float(np.median(rows["overshoot_f"].to_numpy(dtype=float))))


def overshoot_error(rows: pd.DataFrame, overshoot_f: float) -> float | None:
    """``overshoot_f`` against ``Evidence.runs``' run-ons: the mean
    absolute error, °F; None with none."""
    if rows.empty:
        return None
    return float(
        np.mean(np.abs(rows["overshoot_f"].to_numpy(dtype=float) - overshoot_f))
    )


def violations(c: CompressorParams) -> tuple[str, ...]:
    """What ``c``'s map claims somewhere over its two maps' domains
    together that no heat pump does (``CARNOT_SHARE``,
    ``MIN_POWER_W``): ``cop_over_carnot``, ``evaporator_heat_negative``,
    ``power_too_low``; empty when none. The grid holds every domain's
    edges, where a map held to its domain bends, so the heat less the
    power, linear between them, is checked at its extremes."""
    found: set[str] = set()

    def axis(*edges: float) -> list[float]:
        grid = np.linspace(min(edges), max(edges), CHECK_POINTS)
        return sorted({*(float(v) for v in grid), *edges})

    airs = axis(*c.heat_domain_air_f, *c.power_domain_air_f)
    waters = axis(*c.heat_domain_water_f, *c.power_domain_water_f)
    for air in airs:
        for water in waters:
            a, w = float(air), float(water)
            if hp.power_w(c, a, w) < MIN_POWER_W:
                found.add("power_too_low")
                continue
            if hp.cop(c, a, w) > CARNOT_SHARE * hp.carnot_cop(a, w):
                found.add("cop_over_carnot")
            if hp.evaporator_btu_h(c, a, w) < 0.0:
                found.add("evaporator_heat_negative")
    return tuple(sorted(found))


def with_planes(
    c: CompressorParams, heat: Plane | None, power: Plane | None
) -> CompressorParams:
    """``c`` with the planes given, the cross terms 0 where one is, and
    each read over the span it was fitted on where it says."""
    if heat is not None:
        c = replace(
            c,
            heat_btu_h=heat.level,
            heat_btu_h_per_air_f=heat.per_air,
            heat_btu_h_per_water_f=heat.per_water,
            heat_btu_h_per_air_water_f=0.0,
            heat_domain_air_f=heat.air_f or c.heat_domain_air_f,
            heat_domain_water_f=heat.water_f or c.heat_domain_water_f,
        )
    if power is not None:
        c = replace(
            c,
            power_w=power.level,
            power_w_per_air_f=power.per_air,
            power_w_per_water_f=power.per_water,
            power_w_per_air_water_f=0.0,
            power_domain_air_f=power.air_f or c.power_domain_air_f,
            power_domain_water_f=power.water_f or c.power_domain_water_f,
        )
    return c


@dataclass(frozen=True)
class HeatPumpFit:
    """The heat pump's parameters fitted on ``Evidence``, each None
    where it had too little to go on: the heat's and the power's planes,
    the hold by time off, and the overshoot at the stop; how many of
    each they were fitted on; and the in-sample errors
    (``heat_map_error``, ``power_map_error``). ``heat_violations`` and
    ``power_violations``: what each plane, with the other it is applied
    with, claims that no heat pump does (``violations``), in which case
    it is not applied; ``violations`` is either's."""

    heat: Plane | None
    power: Plane | None
    start_hold_min: tuple[float, ...] | None
    overshoot_f: float | None
    n_heat: int
    n_power: int
    n_holds: int
    n_runs: int
    heat_error: float | None
    power_error: float | None
    heat_violations: tuple[str, ...] = ()
    power_violations: tuple[str, ...] = ()

    @property
    def violations(self) -> tuple[str, ...]:
        return tuple(sorted({*self.heat_violations, *self.power_violations}))


def fit_heat_pump(found: Evidence, base: CompressorParams) -> HeatPumpFit:
    """Every part of the heat pump fitted on ``found``, over ``base``."""
    heat = fit_heat_map(found.heat)
    power = fit_power_map(found.power)
    planes = with_planes(base, heat, power)
    found_claims = violations(planes)
    return HeatPumpFit(
        heat=heat,
        power=power,
        start_hold_min=fit_start_hold(found.holds, base),
        overshoot_f=fit_overshoot(found.runs),
        n_heat=len(found.heat),
        n_power=len(found.power),
        n_holds=len(found.holds),
        n_runs=len(found.runs),
        heat_error=None if heat is None else heat_map_error(found.heat, planes),
        power_error=(
            None if power is None else power_map_error(found.power, planes)
        ),
        heat_violations=found_claims if heat is not None else (),
        power_violations=found_claims if power is not None else (),
    )


def with_heat_pump(params: HeaterParams, fit: HeatPumpFit) -> HeaterParams:
    """``params`` with ``fit``'s values where it has them; the planes
    only when they claim nothing no heat pump does."""
    c = params.compressor
    if not fit.violations:
        c = with_planes(c, fit.heat, fit.power)
    if fit.start_hold_min is not None:
        c = replace(c, start_hold_min=fit.start_hold_min)
    controller = params.controller
    if fit.overshoot_f is not None:
        controller = replace(controller, hp_stop_overshoot_f=fit.overshoot_f)
    return replace(params, compressor=c, controller=controller)
