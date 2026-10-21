"""Fit a heater's parameters to its recorded history.

The history is the statuses the heater reported, with when
(``nwp500.status_history``). ``calibrate`` builds the frame
``sim.calibration.calibrate`` takes (``sim_adapters.history``), marks
the spans nobody observed, adds the air where the heater stands and its
humidity, and runs the fits; ``report`` says what each fit found, or why
a term kept the base's value.

The standby fit needs the air where the heater stands, which the heater
does not read while idle: an air sensor's readings beside it, a
constant for a heater in conditioned space, or what a Home Assistant
source recorded (``sim_home_assistant.record_inputs``). Filling the gaps
from the heater's own readings while its compressor runs, or projecting
an outdoor history (``sim.location_air``), biases the fit, so neither is
offered; without the air the standby loss keeps the base's value. Given,
the same air is the recoveries' too.

The statuses are taken one at a time, so a long recording read through
``status_history.iter_read`` needs memory for the frame, not for its
statuses::

    from nwp500 import sim_calibrate, status_history

    def recorded(days):
        for day in days:
            with open(day, encoding="utf-8") as f:
                yield from status_history.iter_read(f)

    done = sim_calibrate.calibrate(recorded(day_files), ambient=65.0)
    for term in sim_calibrate.report(done):
        print(term.name, term.value, term.why)

This module needs the ``sim`` extra.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from nwp500 import sim
from nwp500 import sim_adapters as sa
from nwp500.models import DeviceStatus
from nwp500.sim import calibration as cal
from nwp500.sim.params import HeaterParams, params_from_document

if TYPE_CHECKING:
    import pandas as pd

    from nwp500.sim_home_assistant import RecordInputs

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

__all__ = (
    "DEFAULT_BASE_NOTE",
    "DEFAULT_HUMIDITY_PCT",
    "GAP_SAMPLES",
    "MIN_GAP",
    "NO_AIR_NOTE",
    "CalibrationInputError",
    "Calibrated",
    "Term",
    "calibrate",
    "max_gap",
    "report",
)

#: A reading: an instant and a value.
Reading = tuple[datetime, float]

#: The air's relative humidity when none is given, %: the fits' own.
DEFAULT_HUMIDITY_PCT = 50.0
#: Readings further apart than ``GAP_SAMPLES`` times the record's usual
#: spacing, and at least ``MIN_GAP``, are a span nobody observed.
GAP_SAMPLES = 4
MIN_GAP = timedelta(minutes=5)

#: The note when no ``params`` were given.
DEFAULT_BASE_NOTE = (
    "refitting the 65 gal defaults (give params for another tank size)"
)
#: The note when no air was given.
NO_AIR_NOTE = "no air given: the standby loss is not fitted"


class CalibrationInputError(ValueError):
    """An input the calibration cannot use."""


def max_gap(instants: Iterable[datetime]) -> timedelta:
    """The longest spacing between readings at ``instants`` still taken
    as observed: ``GAP_SAMPLES`` times their median spacing, and at
    least ``MIN_GAP``. A recorder sees a status every few seconds to
    every 30 s, so a stop and restart is far longer; an element run can
    be under a minute, so much longer could hide one."""
    steps = _steps(instants)
    steps = np.sort(steps[steps > 0])
    if not len(steps):
        return MIN_GAP
    usual = timedelta(microseconds=int(steps[len(steps) // 2]) // 1000)
    return max(MIN_GAP, GAP_SAMPLES * usual)


def _steps(instants: Iterable[datetime]) -> np.ndarray:
    """The spacings between ``instants`` in time order, ns."""
    import pandas as pd

    index: Any = (
        instants
        if isinstance(instants, pd.DatetimeIndex)
        else pd.DatetimeIndex(list(instants))
    )
    return np.diff(np.sort(index.as_unit("ns").asi8))


def _stepped(series: Sequence[Reading]) -> list[Reading]:
    """A source's ``series`` as the steps it is: a state holds until the
    next, so each change is preceded by the value before it, a moment
    earlier. Interpolated, the readings either side of a long quiet
    spell or an outage would otherwise ramp across it."""
    out: list[Reading] = []
    for t, v in sorted(series):
        if out:
            out.append((t - timedelta(microseconds=1), out[-1][1]))
        out.append((t, v))
    return out


def _unobserved(
    index: Any,
    covers: tuple[datetime, datetime],
    outages: Sequence[tuple[datetime, datetime]],
) -> Any:
    """Where ``index`` falls outside ``covers``, or its interval (to the
    next instant) overlaps an outage."""
    mask = (index < covers[0]) | (index > covers[1])
    nxt = index[1:].append(index[-1:] + timedelta(microseconds=1))
    for a, b in outages:
        mask |= (index < b) & (nxt > a)
    return mask


@dataclass(frozen=True)
class Calibrated:
    """A calibration, and what ``calibrate`` chose along the way."""

    calibration: cal.Calibration
    #: How the air where the heater stands was given (``readings``,
    #: ``constant`` or ``source``), or None.
    air: str | None
    n_statuses: int
    #: Readings further apart than this were taken as unobserved, and
    #: how many such spans the history has.
    max_gap: timedelta
    n_gaps: int
    notes: tuple[str, ...]


def _base(params: HeaterParams | Any) -> HeaterParams:
    if isinstance(params, HeaterParams):
        return params
    try:
        return params_from_document(params)
    except ValueError as e:
        raise CalibrationInputError(
            f"params is not a parameters document: {e}"
        ) from None


def calibrate(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    *,
    air: Sequence[Reading] | None = None,
    ambient: float | None = None,
    humidity: Sequence[Reading] | None = None,
    params: HeaterParams | Any = None,
    record: RecordInputs | None = None,
) -> Calibrated:
    """``params`` (``HeaterParams`` or a parameters document; default
    the 65 gal defaults) refitted on ``readings``, the statuses the
    heater reported and when, taken once, in any order.

    The air where the heater stands is ``air`` (a sensor's readings) or
    ``ambient`` (a constant), in the preferred unit, and ``humidity``
    that air's, %. Given, the air is both the standby fit's and the
    recoveries'; without it, the standby loss is not fitted and
    recoveries use the heater's own reading while its compressor runs.
    ``record`` (``sim_home_assistant.RecordInputs``) is what a live
    source recorded over the history, °F: its air and humidity where
    none was given, and its draws and circulation runs, which make the
    quiet test exact. Its air is used only over the span it covers.

    Readings further apart than ``max_gap`` of them are a span nobody
    observed, and no fit spans one. Raises ``CalibrationInputError``
    for both ``air`` and ``ambient``, a ``params`` that is not a
    parameters document, or no readings.
    """
    if air is not None and ambient is not None:
        raise CalibrationInputError("give air or ambient, not both")
    notes: list[str] = []
    if params is None:
        base = sim.default_params()
        notes.append(DEFAULT_BASE_NOTE)
    else:
        base = _base(params)
    frame = sa.history(readings)
    if frame.empty:
        raise CalibrationInputError("the history holds no statuses")
    index = cast("pd.DatetimeIndex", frame.index)
    # Timestamps, which are datetimes.
    first, last = cast(datetime, index[0]), cast(datetime, index[-1])
    series: list[Reading] | None = None
    how: str | None = None
    covers: tuple[datetime, datetime] | None = None
    rh_covers: tuple[datetime, datetime] | None = None
    if air is not None:
        series, how = list(air), "readings"
    elif ambient is not None:
        series, how = [(first, ambient), (last, ambient)], "constant"
    elif record is not None and record.air:
        series = [(t, sa.temperature(v)) for t, v in _stepped(record.air)]
        how = "source"
        # A history's first reading is the value in force at its start,
        # and the last holds a reading's freshness past it.
        covers = (record.air[0][0], record.air[-1][0] + timedelta(hours=1))
    if humidity is None and record is not None and record.humidity:
        humidity = _stepped(record.humidity)
        rh_covers = (
            record.humidity[0][0],
            record.humidity[-1][0] + timedelta(hours=1),
        )
    drawing = circulating = None
    if record is not None:
        notes.extend(record.notes)
        if record.drawing is not None and record.circulating is not None:
            drawing, circulating = record.drawing, record.circulating
        elif record.drawing is not None or record.circulating is not None:
            # One alone would replace the heater's in-use flag for the
            # other in the recoveries' draw-free test (``snapshots``).
            notes.append(
                "the meter and the circulation are used together or not at "
                "all: with one unknown, the heater's own in-use flag stands in"
            )
    if humidity is None:
        # The fits' own default, given explicitly: an absent humidity
        # reaches the evaporator's dew point as NaN, which reads as 100 %.
        humidity = [(first, DEFAULT_HUMIDITY_PCT), (last, DEFAULT_HUMIDITY_PCT)]
    gap = max_gap(index)
    n_gaps = int((_steps(index) > gap.total_seconds() * 1e9).sum())
    sa.add_inputs(
        frame,
        air=series,
        humidity=humidity,
        drawing=drawing,
        circulating=circulating,
        max_gap=gap,
    )
    # A source's series, held past its ends or across an outage, would
    # stand for air nobody read: the air is left unknown there, and the
    # humidity takes the fits' own default.
    if covers is not None and record is not None:
        unseen = _unobserved(index, covers, record.air_outages)
        frame.loc[unseen, "air_f"] = float("nan")
        # And out of the standby fit, which would interpolate across,
        # and out of any recovery, which would take an older reading.
        frame["air_unobserved"] = unseen
        frame["excluded"] = frame["excluded"].to_numpy(dtype=bool) | unseen
    if rh_covers is not None and record is not None:
        frame.loc[
            _unobserved(index, rh_covers, record.humidity_outages),
            "humidity_pct",
        ] = DEFAULT_HUMIDITY_PCT
    if how is None:
        notes.append(NO_AIR_NOTE)
    fitted = cal.calibrate(
        frame,
        base,
        recovery_air="heater_air_f" if how is None else "air_f",
    )
    return Calibrated(fitted, how, len(frame), gap, n_gaps, tuple(notes))


# ── the report ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Term:
    """One line of the report: a fitted term, or why it kept the base's
    value."""

    name: str
    value: str
    samples: str
    error: str
    fitted: bool
    why: str = ""
    #: What a fitted value means, where it needs saying.
    note: str = ""


def _num(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}g}"


def report(done: Calibrated) -> list[Term]:
    """What each fit found, in the order they run."""
    c = done.calibration
    s = c.standby
    kept = len(s.windows)
    if s.ua_ref is not None:
        why = ""
    elif done.air is None:
        why = "no air given"
    elif not s.n_quiet:
        why = f"no quiet window of {cal.MIN_QUIET_HOURS:g} h or more"
    else:
        why = (
            f"none of {s.n_quiet} quiet windows tracked the probes within "
            f"{cal.MAX_WINDOW_RMSE_F:g} °F"
        )
    rmse = (
        f"{max(w.rmse_f for w in s.windows):.2f} °F max rmse"
        if s.windows
        else "-"
    )
    terms = [
        Term(
            "Standby loss (UA at ref ΔT, BTU/h·°F)",
            _num(s.ua_ref),
            f"{kept} of {s.n_quiet} quiet windows",
            rmse,
            s.ua_ref is not None,
            why,
        ),
        Term(
            "Standby loss exponent",
            _num(s.ua_exponent),
            f"{kept} windows",
            "-",
            s.ua_exponent is not None,
            why,
            note=""
            if s.ua_exponent != 0.0
            else "0, a constant loss: under 4 windows, under two 20 °F "
            "bands, or the fit clamped to 0",
        ),
        Term(
            "Zone gap time constant (h)",
            _num(s.tau_gap_hours),
            f"{s.n_gap_windows} windows",
            "-",
            s.tau_gap_hours is not None,
            ""
            if s.tau_gap_hours is not None
            else why
            or f"{s.n_gap_windows} windows open a gap; "
            f"{cal.MIN_GAP_FIT_WINDOWS} needed",
        ),
    ]
    found = c.recoveries
    reached = len(found.loc[found["reached"].astype(bool)]) if len(found) else 0
    comp = c.compressor
    if comp is None:
        comp_why = (
            f"{reached} recoveries reached their target; "
            f"{cal.MIN_RECOVERIES} needed"
        )
    elif comp.hit_bounds:
        comp_why = "the fit is pinned on a bound: not applied"
    else:
        comp_why = ""
    comp_error = "-"
    if comp is not None:
        comp_error = f"{comp.mae_minutes:.1f} min mae"
        if comp.heldout_mae_minutes is not None:
            comp_error += (
                f", {comp.heldout_mae_minutes:.1f} on {comp.n_heldout} held out"
            )
    comp_samples = (
        f"{comp.n_fitted} recoveries" if comp else f"{reached} recoveries"
    )
    terms += [
        Term(
            "Compressor constant",
            _num(comp.compressor_constant if comp else None),
            comp_samples,
            comp_error,
            comp is not None and not comp.hit_bounds,
            comp_why,
        ),
        Term(
            "Evaporator approach (°F)",
            _num(comp.evap_approach_f if comp else None),
            comp_samples,
            comp_error,
            comp is not None and not comp.hit_bounds,
            comp_why,
        ),
    ]
    p = c.power
    no_power = comp_why and "the compressor is not fitted"
    few = f"too few cycles ({cal.MIN_POWER_EVENTS} needed)"
    terms += [
        Term(
            "Input power scale",
            _num(p.power_scale if p else None),
            f"{p.n_power} cycles" if p else "-",
            "-",
            p is not None and p.power_scale is not None,
            no_power or ("" if p and p.power_scale is not None else few),
        ),
        Term(
            "COP scale",
            _num(p.cop_scale if p else None),
            f"{p.n_cop} cycles" if p else "-",
            "-",
            p is not None and p.cop_scale is not None,
            no_power or ("" if p and p.cop_scale is not None else few),
        ),
        Term(
            "Start-up energy (Wh)",
            _num(p.startup_wh if p else None),
            f"{p.n_cop} cycles" if p else "-",
            "-",
            p is not None and p.startup_wh is not None,
            no_power or ("" if p and p.startup_wh is not None else few),
        ),
        Term(
            "COP lift coefficient (1/°F)",
            _num(p.cop_lift_coeff if p else None),
            f"{p.n_cop} cycles" if p else "-",
            "-",
            p is not None and p.cop_lift_coeff is not None,
            no_power or ("" if p and p.cop_lift_coeff is not None else few),
        ),
    ]
    return terms
