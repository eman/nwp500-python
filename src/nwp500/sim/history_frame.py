"""Reading a heater's history frame: its instants, the spans a state
is on, and a column's value or integral at an instant.

The frame is ``sim.calibration``'s: a ``pandas.DataFrame`` indexed by
sorted UTC instants, each sample holding until the next. Shared by the
fits that read it (``sim.calibration``, ``sim.heat_pump_fit``).
"""

from datetime import datetime
from typing import cast

import numpy as np
import pandas as pd

#: An interval: its start and its end.
Interval = tuple[datetime, datetime]


def instants(frame: pd.DataFrame) -> list[datetime]:
    """The frame's index as instants."""
    # A history's index holds no NaT: each row is a sample's instant.
    return [
        cast(datetime, pd.Timestamp(t).to_pydatetime()) for t in frame.index
    ]


def on_intervals(when: list[datetime], on: np.ndarray) -> list[Interval]:
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


def merge(intervals: list[Interval]) -> list[Interval]:
    """Overlapping intervals merged, sorted."""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def asof(values: np.ndarray, seconds: np.ndarray, at: datetime) -> float | None:
    """The last finite value at or before ``at`` (``seconds`` its
    instants, sorted); the first if ``at`` precedes them; None if there
    is none."""
    ok = np.isfinite(values)
    if not ok.any():
        return None
    finite, stamps = values[ok], seconds[ok]
    pos = int(np.searchsorted(stamps, at.timestamp(), side="right")) - 1
    return float(finite[max(pos, 0)])


def floats(history: pd.DataFrame, name: str) -> np.ndarray:
    """A column as floats, NaN throughout when the history lacks it."""
    if name not in history.columns:
        return np.full(len(history), np.nan)
    return np.asarray(history[name].to_numpy(dtype=float, na_value=np.nan))


def energy_wh(
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
