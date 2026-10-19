"""``nwp-cli simulate calibrate``: fit the heater's parameters to its
recorded history.

The history is the statuses the heater reported
(``nwp500.status_history``, as ``nwp-cli simulate record`` writes them).
The standby fit also needs the air where the heater stands over the
same time, which the heater does not read while idle: an air sensor's
readings beside it, or a constant for a heater in conditioned space.
Filling the gaps from the heater's own readings while its compressor
runs, or projecting an outdoor history (``sim.location_air``), biases
the fit, so neither is offered; without the air the standby loss keeps
the base's value. Given, the same air is the recoveries' too.

This module needs the ``sim`` extra.
"""

import csv
import itertools
import json
import logging
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console
from rich.table import Table

from nwp500 import sim, status_history
from nwp500 import sim_adapters as sa
from nwp500.sim import calibration as cal
from nwp500.sim.params import params_to_document

from .simulate import InputError, read_params

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

#: A reading: an instant and a value.
Reading = tuple[datetime, float]


def read_history(path: str | Path) -> list[status_history.TimedStatus]:
    """The statuses recorded at ``path``."""
    try:
        with Path(path).open(encoding="utf-8") as f:
            readings = status_history.read(f)
    except (OSError, ValueError) as e:
        raise InputError(f"cannot read the history {path}: {e}") from None
    if not readings:
        raise InputError(f"the history {path} holds no statuses")
    return readings


def read_readings(path: str | Path, what: str) -> list[Reading]:
    """A CSV file's readings: an ISO 8601 instant with its offset, then
    a value, on each row. A first row that is not one is a header."""
    try:
        with Path(path).open(encoding="utf-8", newline="") as f:
            rows = [r for r in csv.reader(f) if r and any(c.strip() for c in r)]
    except OSError as e:
        raise InputError(f"cannot read the {what} {path}: {e}") from None
    out: list[Reading] = []
    for number, row in enumerate(rows, start=1):
        try:
            at = datetime.fromisoformat(row[0].strip())
            value = float(row[1])
        except IndexError, ValueError:
            if number == 1:
                continue
            raise InputError(
                f"row {number} of the {what} {path} is not an instant "
                "and a value"
            ) from None
        if at.tzinfo is None:
            raise InputError(
                f"row {number} of the {what} {path}: give the instant's "
                "UTC offset"
            )
        if math.isfinite(value):
            out.append((at, value))
    if not out:
        raise InputError(f"the {what} {path} holds no readings")
    return out


#: The air's relative humidity when none is given, %: the fits' own.
DEFAULT_HUMIDITY_PCT = 50.0
#: Readings further apart than ``GAP_SAMPLES`` times the record's usual
#: spacing, and at least ``MIN_GAP``, are a span nobody observed.
GAP_SAMPLES = 4
MIN_GAP = timedelta(minutes=5)


def max_gap(readings: Sequence[status_history.TimedStatus]) -> timedelta:
    """The longest spacing between readings still taken as observed:
    ``GAP_SAMPLES`` times their median spacing, and at least
    ``MIN_GAP``. A recorder asks every 30 s, so a stop and restart is
    far longer; an element run can be under a minute, so much longer
    could hide one."""
    times = sorted(t.timestamp() for t, _ in readings)
    steps = sorted(b - a for a, b in itertools.pairwise(times) if b > a)
    if not steps:
        return MIN_GAP
    usual = timedelta(seconds=steps[len(steps) // 2])
    return max(MIN_GAP, GAP_SAMPLES * usual)


def _held_to(
    series: Sequence[Reading], outages: Sequence[tuple[datetime, datetime]]
) -> list[Reading]:
    """A source's ``series`` with the value in force at each outage's
    start repeated there: a state holds until the next, so the readings
    either side of an outage are not to be drawn as a ramp across it,
    which would reach back before it."""
    out = sorted(series)
    for a, _ in outages:
        before = [v for t, v in out if t <= a]
        if before:
            out.append((a, before[-1]))
    return sorted(set(out))


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


async def read_record(
    sources: Any, readings: Sequence[status_history.TimedStatus]
) -> Any:
    """What ``sources`` recorded over ``readings``' span
    (``sim_home_assistant.record_inputs``)."""
    from nwp500 import sim_home_assistant as ha

    first = min(t for t, _ in readings)
    last = max(t for t, _ in readings)
    async with ha.HomeAssistantClient(sources.url, sources.token) as client:
        return await ha.record_inputs(client, sources.entities, first, last)


@dataclass(frozen=True)
class Calibrated:
    """A calibration, and what the command chose along the way."""

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


def calibrate(
    readings: Sequence[status_history.TimedStatus],
    *,
    air: Sequence[Reading] | None = None,
    ambient: float | None = None,
    humidity: Sequence[Reading] | None = None,
    params: Any = None,
    record: Any = None,
) -> Calibrated:
    """``params`` (a parameters document; default the 65 gal defaults)
    refitted on ``readings``. The air where the heater stands is
    ``air`` (a sensor's readings) or ``ambient`` (a constant), in the
    preferred unit, and ``humidity`` that air's, %. Given, the air is
    both the standby fit's and the recoveries'; without it, the standby
    loss is not fitted and recoveries use the heater's own reading while
    its compressor runs. ``record`` (``sim_home_assistant.RecordInputs``)
    is what a live source recorded over the history, °F: its air and
    humidity where none was given, and its draws and circulation runs,
    which make the quiet test exact. Its air is used only over the span
    it covers."""
    if air is not None and ambient is not None:
        raise InputError("give --air or --ambient, not both")
    notes: list[str] = []
    if params is None:
        base = sim.default_params()
        notes.append(
            "refitting the 65 gal defaults (give --params for another "
            "tank size)"
        )
    else:
        base = read_params(params, "--params")
    first = min(t for t, _ in readings)
    last = max(t for t, _ in readings)
    series: list[Reading] | None = None
    how: str | None = None
    covers: tuple[datetime, datetime] | None = None
    rh_covers: tuple[datetime, datetime] | None = None
    if air is not None:
        series, how = list(air), "readings"
    elif ambient is not None:
        series, how = [(first, ambient), (last, ambient)], "constant"
    elif record is not None and record.air:
        series = [
            (t, sa.temperature(v))
            for t, v in _held_to(record.air, record.air_outages)
        ]
        how = "source"
        # A history's first reading is the value in force at its start,
        # and the last holds a reading's freshness past it.
        covers = (record.air[0][0], record.air[-1][0] + timedelta(hours=1))
    if humidity is None and record is not None and record.humidity:
        humidity = _held_to(record.humidity, record.humidity_outages)
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
    gap = max_gap(readings)
    times = sorted(t for t, _ in readings)
    n_gaps = sum(b - a > gap for a, b in itertools.pairwise(times))
    frame = sa.history(
        readings,
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
        unseen = _unobserved(frame.index, covers, record.air_outages)
        frame.loc[unseen, "air_f"] = float("nan")
        # And out of the standby fit, which would interpolate across.
        frame["air_unobserved"] = unseen
    if rh_covers is not None and record is not None:
        frame.loc[
            _unobserved(frame.index, rh_covers, record.humidity_outages),
            "humidity_pct",
        ] = DEFAULT_HUMIDITY_PCT
    if how is None:
        notes.append(
            "no air given (--air, --ambient or --sources): the standby "
            "loss is not fitted"
        )
    fitted = cal.calibrate(
        frame,
        base,
        recovery_air="heater_air_f" if how is None else "air_f",
    )
    return Calibrated(fitted, how, len(readings), gap, n_gaps, tuple(notes))


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
            _num(comp and comp.compressor_constant),
            comp_samples,
            comp_error,
            comp is not None and not comp.hit_bounds,
            comp_why,
        ),
        Term(
            "Evaporator approach (°F)",
            _num(comp and comp.evap_approach_f),
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
            _num(p and p.power_scale),
            f"{p.n_power} cycles" if p else "-",
            "-",
            p is not None and p.power_scale is not None,
            no_power or ("" if p and p.power_scale is not None else few),
        ),
        Term(
            "COP scale",
            _num(p and p.cop_scale),
            f"{p.n_cop} cycles" if p else "-",
            "-",
            p is not None and p.cop_scale is not None,
            no_power or ("" if p and p.cop_scale is not None else few),
        ),
        Term(
            "Start-up energy (Wh)",
            _num(p and p.startup_wh),
            f"{p.n_cop} cycles" if p else "-",
            "-",
            p is not None and p.startup_wh is not None,
            no_power or ("" if p and p.startup_wh is not None else few),
        ),
        Term(
            "COP lift coefficient (1/°F)",
            _num(p and p.cop_lift_coeff),
            f"{p.n_cop} cycles" if p else "-",
            "-",
            p is not None and p.cop_lift_coeff is not None,
            no_power or ("" if p and p.cop_lift_coeff is not None else few),
        ),
    ]
    return terms


def _kept(t: Term) -> str:
    if t.fitted:
        return f"fitted: {t.note}" if t.note else "fitted"
    return f"base: {t.why}" if t.why else "base"


def print_report(done: Calibrated, console: Console) -> None:
    """The report as tables on ``console``."""
    c = done.calibration
    console.print(
        f"{done.n_statuses} statuses; quiet test: {c.standby.quiet_by}; "
        f"{len(c.recoveries)} recoveries found"
    )
    if done.n_gaps:
        minutes = done.max_gap.total_seconds() / 60
        console.print(
            f"{done.n_gaps} gap{'' if done.n_gaps == 1 else 's'} of over "
            f"{minutes:g} min between statuses: no fit spans them"
        )
    console.print(
        {
            "readings": "Air: the readings given",
            "constant": "Air: the constant given",
            "source": "Air: the sources' record beside the heater",
            None: "Air: none given; recoveries use the heater's own reading",
        }[done.air]
    )
    table = Table(title="Calibration")
    for column in ("Term", "Value", "From", "Error", "Kept"):
        table.add_column(column)
    for t in report(done):
        table.add_row(
            t.name,
            t.value,
            t.samples,
            t.error,
            _kept(t),
        )
    console.print(table)
    unfitted = ", ".join(c.params.unfitted) or "none"
    console.print(f"Unfitted: {unfitted}")


def run(
    done: Calibrated, output: str | Path | None, out: TextIO | None = None
) -> None:
    """Print the report and write the parameters to ``output``."""
    for note in done.notes:
        _logger.warning(note)
    print_report(done, Console(file=out or sys.stdout))
    if output is not None:
        text = json.dumps(params_to_document(done.calibration.params), indent=2)
        Path(output).write_text(text + "\n", encoding="utf-8")
