"""``nwp-cli simulate calibrate``: fit the heater's parameters to its
recorded history.

The history is the statuses the heater reported
(``nwp500.status_history``, as ``nwp-cli simulate record`` writes them).
The fits and the report's terms are ``nwp500.sim_calibrate``'s; this
module reads the command's files and prints the report.

This module needs the ``sim`` extra.
"""

import csv
import functools
import json
import logging
import math
import sys
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console
from rich.table import Table

from nwp500 import sim, status_history
from nwp500 import sim_calibrate as sc
from nwp500 import sim_score as ss
from nwp500.sim import tank_fit as tf
from nwp500.sim.params import params_to_document
from nwp500.sim_calibrate import Calibrated, Term, report

from .simulate import InputError, local_zone, read_params

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


#: The library's notes, naming the command's options.
_OPTION_NOTES = {
    sc.DEFAULT_BASE_NOTE: "refitting the 65 gal defaults (give --params "
    "for another tank size)",
    sc.NO_AIR_NOTE: "no air given (--air, --ambient or --sources): the "
    "tank is not fitted",
}

#: The events each of the tank fit's workers takes at a time.
_CHUNK = 8


def calibrate(
    readings: Sequence[status_history.TimedStatus],
    *,
    air: Sequence[Reading] | None = None,
    ambient: float | None = None,
    humidity: Sequence[Reading] | None = None,
    params: Any = None,
    record: Any = None,
) -> Calibrated:
    """``sim_calibrate.calibrate`` with ``params`` a parameters
    document, its errors as ``InputError`` and its notes naming the
    command's options, the tank's fit spread over the machine's
    processors."""
    base = None if params is None else read_params(params, "--params")
    try:
        with ProcessPoolExecutor() as pool:
            done = sc.calibrate(
                readings,
                air=air,
                ambient=ambient,
                humidity=humidity,
                params=base,
                record=record,
                map_=functools.partial(pool.map, chunksize=_CHUNK),
            )
    except sc.CalibrationInputError as e:
        raise InputError(str(e)) from None
    return replace(
        done, notes=tuple(_OPTION_NOTES.get(n, n) for n in done.notes)
    )


def parse_instant(text: str, what: str) -> datetime:
    """An ISO 8601 date or instant; a date, or an instant without its
    offset, in local time."""
    try:
        at = datetime.fromisoformat(text.strip())
    except ValueError:
        raise InputError(f"{what} {text!r} is not an ISO 8601 date") from None
    return at.astimezone() if at.tzinfo is None else at


@dataclass(frozen=True)
class HeldOutScore:
    """A calibration on the history before ``start``, and the base's
    and the fit's scores on the events from it (``sim_score``)."""

    start: datetime
    done: Calibrated
    base: ss.Score
    fitted: ss.Score


def holdout(
    readings: Sequence[status_history.TimedStatus],
    start: datetime,
    *,
    air: Sequence[Reading] | None = None,
    ambient: float | None = None,
    humidity: Sequence[Reading] | None = None,
    params: Any = None,
    record: Any = None,
) -> HeldOutScore:
    """``calibrate`` on the statuses before ``start``, then the base and
    the fit scored on the events from it. Raises ``InputError`` when
    either side of ``start`` holds no status."""
    before = [r for r in readings if r[0] < start]
    if not before or len(before) == len(readings):
        raise InputError(
            f"--holdout-from {start.isoformat()} leaves no history on one "
            "side of it"
        )
    done = calibrate(
        before,
        air=air,
        ambient=ambient,
        humidity=humidity,
        params=params,
        record=record,
    )
    base = (
        sim.default_params()
        if params is None
        else read_params(params, "--params")
    )
    try:
        ready = sc.prepare(
            readings, air=air, ambient=ambient, humidity=humidity, record=record
        )
    except sc.CalibrationInputError as e:
        raise InputError(str(e)) from None
    found = ss.events(ready, since=start)
    # Each event starts from the layers the history before it leaves.
    replayed = tf.tank_record(ready.frame) if "air_f" in ready.frame else None
    # Local days, as ``--holdout-from`` is read.
    tz = local_zone() or "UTC"
    return HeldOutScore(
        start,
        done,
        ss.score(found, base, tz=tz, record=replayed),
        ss.score(found, done.calibration.params, tz=tz, record=replayed),
    )


def print_score(held: HeldOutScore, console: Console) -> None:
    """The held-out score as a table on ``console``."""
    events = held.fitted.events
    console.print(
        f"Held out from {held.start.isoformat()}: "
        f"{len(events['recoveries'])} recoveries, "
        f"{len(events['windows'])} quiet windows"
    )
    table = Table(title="Held-out score (lower is better, but a bias)")
    for column in ("Metric", "Events", "Base", "Fitted", "Fitted 90 %"):
        table.add_column(column)
    for name, fitted in held.fitted.metrics.items():
        base = held.base.metrics.get(name)
        table.add_row(
            name,
            str(fitted.n),
            "" if base is None else f"{base.value:.3g}",
            f"{fitted.value:.3g}",
            f"{fitted.lo:.3g} to {fitted.hi:.3g}",
        )
    console.print(table)
    failed = sum(held.fitted.failed.values())
    broken = sum(held.fitted.breaks.values())
    if failed or broken:
        console.print(
            f"Fitted: {failed} events the simulator could not answer, "
            f"{broken} predictions below the air"
        )


def _kept(t: Term) -> str:
    if t.fitted:
        return f"fitted: {t.note}" if t.note else "fitted"
    return f"base: {t.why}" if t.why else "base"


def print_report(done: Calibrated, console: Console) -> None:
    """The report as tables on ``console``."""
    c = done.calibration
    console.print(
        f"{done.n_statuses} statuses; {len(c.recoveries)} recoveries found"
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
            "heater": "Air: none given; the heater's own reading, the "
            "cabinet's less its warmth while the compressor is idle",
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
    done: Calibrated,
    output: str | Path | None,
    out: TextIO | None = None,
    held: HeldOutScore | None = None,
) -> None:
    """Print the report, and ``held``'s score, and write the parameters
    to ``output``."""
    for note in done.notes:
        _logger.warning(note)
    console = Console(file=out or sys.stdout)
    print_report(done, console)
    if held is not None:
        print_score(held, console)
    if output is not None:
        text = json.dumps(params_to_document(done.calibration.params), indent=2)
        Path(output).write_text(text + "\n", encoding="utf-8")
