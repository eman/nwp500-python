"""Scenarios and results as JSON-compatible documents.

A scenario document is ``{"schema_version": 1, "scenario": {...}}``,
with an optional ``"params"`` section, a ``HeaterParams`` document
(``params.params_to_document``). Instants are ISO 8601 strings with
their offset, the horizon an ISO 8601 duration. Parsing takes a
``str`` (JSON) or a mapping; reading and writing files is the caller's.

A result document holds what the walk answered: the path, the heating
intervals, the writes and mode writes, the modes, the delivery
temperature along the path, the draw windows, the reasons and the
defaults used, with instants as ISO 8601 strings and floats as they
are.

The simulator's other answers (``time_to_ready``'s ``Readiness``,
``forecast``'s ``Forecast`` and the rest in ``DOCUMENT_KINDS``) are
documents through ``to_document``: ``{"schema_version": 1, "kind":
...}`` with the answer's fields, instants as ISO 8601 strings, and a
number that isn't finite as null.
"""

import dataclasses
import enum
import json
import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any

import numpy as np

from nwp500.sim.delivery import Deliverable
from nwp500.sim.inputs import Scenario
from nwp500.sim.params import (
    HeaterParams,
    params_from_document,
    params_to_document,
)
from nwp500.sim.profile import HeaterProfile
from nwp500.sim.ready import Readiness, Recovery
from nwp500.sim.result import (
    ActiveCycle,
    ElementModeResult,
    Forecast,
    RecoveryResult,
    SimulationResult,
    Trace,
)

#: The scenario document's version: it moves only when a reader of the
#: previous one would misread it.
SCHEMA_VERSION = 1

#: The engine's outputs a result document holds.
RESULT_FIELDS = ("points", "heating", "writes", "mode_writes", "modes")


def scenario_to_document(
    scenario: Scenario, params: HeaterParams | None = None
) -> dict[str, Any]:
    """``scenario``, and ``params`` when given, as a document."""
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        # Only what was given: a default left out is still a default
        # when the document is read back, and ``defaults_used`` says so.
        "scenario": scenario.model_dump(mode="json", exclude_unset=True),
    }
    if params is not None:
        doc["params"] = params_to_document(params)
    return doc


def merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """``base`` with ``over`` laid on it: objects merge key by key; any
    other value, a list included, replaces the one under it."""
    out = dict(base)
    for key, value in over.items():
        under = out.get(key)
        if isinstance(value, Mapping) and isinstance(under, Mapping):
            out[key] = merge(under, value)  # pyright: ignore[reportUnknownArgumentType]
        else:
            out[key] = value
    return out


def scenario_from_document(
    doc: str | Mapping[str, Any],
) -> tuple[Scenario, HeaterParams | None]:
    """The scenario ``doc`` holds, and its parameters when it has a
    ``params`` section. A ``schema_version`` other than
    ``SCHEMA_VERSION`` is a ``ValueError``."""
    data: Any = json.loads(doc) if isinstance(doc, str) else doc
    if not isinstance(data, Mapping):
        raise ValueError("a scenario document is an object")
    version = data.get("schema_version")  # pyright: ignore[reportUnknownMemberType]
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {version!r}")
    scenario = Scenario.model_validate(data["scenario"])
    params = data.get("params")  # pyright: ignore[reportUnknownMemberType]
    return scenario, (None if params is None else params_from_document(params))


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        # JSON has no infinity: a tap the mains keeps above the line
        # never runs under it, and its gallons are null.
        return None
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def result_to_document(result: SimulationResult) -> dict[str, Any]:
    """``result`` as a document."""
    whole = dataclasses.asdict(result.simulation)
    return {
        "schema_version": SCHEMA_VERSION,
        "start": result.start.isoformat(),
        "until": result.until.isoformat(),
        **{k: _plain(whole[k]) for k in RESULT_FIELDS},
        "delivery": _plain(list(result.delivery)),
        "windows": [_plain(dataclasses.asdict(w)) for w in result.windows],
        "reasons": list(result.reasons),
        "defaults_used": list(result.defaults_used),
        # Where the walk left the heater: a scenario from ``until`` takes
        # them as its state, history and settings.
        **{
            name: None if value is None else value.model_dump(mode="json")
            for name, value in (
                ("end_state", result.end_state),
                ("end_history", result.end_history),
                ("end_settings", result.end_settings),
            )
        },
    }


#: The answers ``to_document`` takes, and the kind each document names:
#: its type's name in snake case.
DOCUMENT_KINDS: Mapping[type, str] = MappingProxyType(
    {
        Readiness: "readiness",
        Recovery: "recovery",
        RecoveryResult: "recovery_result",
        Forecast: "forecast",
        ActiveCycle: "active_cycle",
        ElementModeResult: "element_mode_result",
        Deliverable: "deliverable",
        Trace: "trace",
        HeaterProfile: "heater_profile",
    }
)


def _json(value: Any) -> Any:
    """``value`` (``dataclasses.asdict``'s) in JSON's types."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, enum.Enum):
        return _json(value.value)
    if isinstance(value, np.generic):
        return _json(value.item())
    if isinstance(value, bool | int | str) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list | tuple):
        return [_json(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    raise TypeError(f"no document for a {type(value).__name__}")


def to_document(value: Any) -> dict[str, Any]:
    """``value``, one of the answers in ``DOCUMENT_KINDS``, as a
    document: ``schema_version``, its ``kind``, and its fields, nested
    answers as objects. A ``TypeError`` for any other value."""
    kind = DOCUMENT_KINDS.get(type(value))
    if kind is None:
        raise TypeError(f"no document kind for a {type(value).__name__}")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        **_json(dataclasses.asdict(value)),
    }
