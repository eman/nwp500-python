"""Scenarios and results as JSON-compatible documents.

A scenario document is ``{"schema_version": 1, "scenario": {...}}``,
with an optional ``"params"`` section, a ``HeaterParams`` document
(``params.params_to_document``). Instants are ISO 8601 strings with
their offset, the horizon an ISO 8601 duration. Parsing takes a
``str`` (JSON) or a mapping; reading and writing files is the caller's.

A result document holds what the walk answered: the path, the heating
intervals, the writes and mode writes, the modes, the reasons and the
defaults used, with instants as ISO 8601 strings and floats as they
are.
"""

import dataclasses
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from nwp500.sim.inputs import Scenario
from nwp500.sim.params import (
    HeaterParams,
    params_from_document,
    params_to_document,
)
from nwp500.sim.result import SimulationResult

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
        "scenario": scenario.model_dump(mode="json"),
    }
    if params is not None:
        doc["params"] = params_to_document(params)
    return doc


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
        "reasons": list(result.reasons),
        "defaults_used": list(result.defaults_used),
    }
