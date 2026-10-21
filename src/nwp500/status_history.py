"""A heater's recorded statuses, one JSON object per line.

Each line is ``{"t": <ISO 8601 instant>, "status": <raw status>}``: the
instant the status arrived, with its offset, and the status payload as
the device sent it. ``DeviceStatus.model_validate`` reads the payload
back; a parsed ``DeviceStatus`` does not dump back to it, so a recorder
keeps the payload, not the model. ``nwp-cli simulate record`` writes
such a file, and the simulator's calibration reads one
(``sim_adapters.history``, ``sim.calibration.calibrate``).

Nothing here does I/O: the caller reads and writes the lines.

Example::

    from nwp500 import status_history

    with open("history.jsonl") as f:
        readings = status_history.read(f)   # [(instant, DeviceStatus)]

A long recording is better taken a status at a time: ``iter_read``
yields them as it reads, so a consumer such as ``sim_adapters.history``
holds only what it keeps of each.
"""

import json
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime
from typing import Any, cast

from nwp500.models import DeviceStatus

__all__ = ("TimedStatus", "iter_read", "line", "read")

#: A status and the instant it arrived.
TimedStatus = tuple[datetime, DeviceStatus]


def line(at: datetime, status: Mapping[str, Any]) -> str:
    """One line of a history, without its newline: the instant ``at``
    (timezone-aware) and the raw ``status`` payload."""
    if at.tzinfo is None:
        raise ValueError("the instant needs its UTC offset")
    return json.dumps(
        {"t": at.isoformat(), "status": dict(status)}, separators=(",", ":")
    )


def read(lines: Iterable[str]) -> list[TimedStatus]:
    """The statuses on ``lines`` (``line``'s), in their order. Blank
    lines are skipped; any other line that is not one raises
    ``ValueError`` naming its number."""
    return list(iter_read(lines))


def iter_read(lines: Iterable[str]) -> Iterator[TimedStatus]:
    """``read``'s statuses one at a time, each as its line is read."""
    for number, text in enumerate(lines, start=1):
        if not text.strip():
            continue
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("not a JSON object")
            entry = cast(dict[str, Any], parsed)
            at = datetime.fromisoformat(entry["t"])
            if at.tzinfo is None:
                raise ValueError("the instant has no UTC offset")
            status = DeviceStatus.model_validate(entry["status"])
        # A pydantic ValidationError is a ValueError.
        except (KeyError, TypeError, ValueError) as e:
            reason = f"no {e}" if isinstance(e, KeyError) else str(e)
            raise ValueError(
                f"line {number} is not a recorded status: {reason}"
            ) from None
        yield at, status
