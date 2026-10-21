"""``nwp-cli simulate calibrate``: fit the heater's parameters to its
recorded history.

The history is the statuses the heater reported
(``nwp500.status_history``, as ``nwp-cli simulate record`` writes them).
The fits and the report's terms are ``nwp500.sim_calibrate``'s; this
module reads the command's files and prints the report.

This module needs the ``sim`` extra.
"""

import csv
import json
import logging
import math
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console
from rich.table import Table

from nwp500 import sim_calibrate as sc
from nwp500 import status_history
from nwp500.sim.params import params_to_document
from nwp500.sim_calibrate import Calibrated, Term, report

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
    "standby loss is not fitted",
}


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
    command's options."""
    base = None if params is None else read_params(params, "--params")
    try:
        done = sc.calibrate(
            readings,
            air=air,
            ambient=ambient,
            humidity=humidity,
            params=base,
            record=record,
        )
    except sc.CalibrationInputError as e:
        raise InputError(str(e)) from None
    return replace(
        done, notes=tuple(_OPTION_NOTES.get(n, n) for n in done.notes)
    )


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
