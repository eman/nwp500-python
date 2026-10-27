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
measure from that frame.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

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
from nwp500.sim.params import LossParams, TankParams
from nwp500.sim.physics.tank import bottom_loss_reach, ua_at
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


def _ua_ref(loss: LossParams) -> float:
    return (
        loss.ua_btu_hr_f
        if loss.ua_btu_hr_f is not None
        else loss.ua_baseline_btu_hr_f
    )


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
    tank: TankParams,
    loss: LossParams,
    *,
    min_minutes: int = MIN_STRETCH_MINUTES,
) -> pd.DataFrame:
    """The heat a recovery puts into the tank, from its draw-free climbs
    with the tank mixed (``recovery_frame``): the probes' mean is then
    the tank's, and the heat is its mass times the mean's rise (a
    least-squares slope over at least ``min_minutes``) plus the loss
    ``loss`` prices against the air: the UA law's, and the bottom
    loss's share at each minute's gap
    (``physics.tank.bottom_loss_reach``). A row a stretch:
    ``cycle``, ``start``, ``minutes``, ``water_f`` (the mean's mean),
    ``lower_f``, ``air_f``, ``humidity_pct``, ``rise_f_h``,
    ``loss_btu_h``, ``heat_btu_h``, the metered ``power_w`` (NaN
    without a reading) and ``cop`` (the heat over the power)."""
    mass = tank.volume_gal * WATER_BTU_PER_GAL_F
    ua_ref = _ua_ref(loss)
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
            dt = water - air
            reach = [
                bottom_loss_reach(float(gap), loss.bottom_gate_f)
                for gap in s["gap_f"].to_numpy(dtype=float)
            ]
            lost = ua_at(
                dt, ua_ref, loss.ua_exponent, loss.ua_ref_delta_t_f
            ) * dt + loss.bottom_loss_btu_hr * float(np.mean(reach))
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
