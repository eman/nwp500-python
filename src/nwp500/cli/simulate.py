"""``nwp-cli simulate``: compose a scenario and walk it.

The heater and its schedules come from the device (``nwp500.sim_live``),
from a scenario document, or both; the air, the draws, the commands and
the parameters from flags or files. Each part is chosen on its own, in
this order of precedence: a flag, then the scenario document, then the
device.

This module needs the ``sim`` extra; ``__main__`` imports it only when a
``simulate`` command runs.
"""

import csv
import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rich.console import Console
from rich.table import Table

from nwp500 import sim, sim_live
from nwp500 import sim_adapters as sa
from nwp500.sim.codec import (
    SCHEMA_VERSION,
    result_to_document,
    scenario_to_document,
)
from nwp500.sim.codec import (
    merge as merge,
)
from nwp500.sim.engine import SimulationError
from nwp500.sim.params import params_from_document

if TYPE_CHECKING:
    from nwp500.api_client import NavienAPIClient
    from nwp500.models import Device
    from nwp500.mqtt import NavienMqttClient
    from nwp500.sim_home_assistant import HomeAssistantTank

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

#: How far a run looks ahead when nothing else says.
DEFAULT_HOURS = sim_live.DEFAULT_HORIZON / timedelta(hours=1)


class InputError(ValueError):
    """An input that cannot be read or does not make a scenario."""


def read_document(path: str | Path, what: str) -> dict[str, Any]:
    """The JSON object at ``path``: every document the command reads is
    one."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise InputError(f"cannot read the {what} {path}: {e}") from None
    if not isinstance(doc, dict):
        raise InputError(f"the {what} {path} is not a JSON object")
    return doc  # pyright: ignore[reportUnknownVariableType]


def zone_name(name: str) -> str:
    """``name``, when it is an IANA zone this machine knows."""
    try:
        return sim_live.zone_name(name)
    except ValueError as e:
        raise InputError(str(e)) from None


def local_zone() -> str | None:
    """This machine's IANA zone (``TZ``, then ``/etc/localtime``), or
    None when it has no name."""
    candidates: list[str] = []
    if tz := os.environ.get("TZ"):
        candidates.append(tz.removeprefix(":"))
    try:
        link = str(Path("/etc/localtime").readlink())
    except OSError:
        pass
    else:
        if "zoneinfo/" in link:
            candidates.append(link.rpartition("zoneinfo/")[2])
    for name in candidates:
        try:
            ZoneInfo(name)
        except ZoneInfoNotFoundError, ValueError:
            continue
        return name
    return None


#: A scenario ready to walk, with its parameters.
Built = sim_live.Built

#: The library's notes, naming the command's options.
_OPTION_NOTES = {
    sim_live.DEFAULT_PARAMS_NOTE: "the tank size is unknown: using the 65 "
    "gal defaults (give --params)",
}


@dataclass(frozen=True)
class Inputs:
    """What the command was given. Files are read already; ``ambient``
    and ``inlet`` are in the preferred unit."""

    scenario: Mapping[str, Any] | None = None
    live: bool = False
    hours: float | None = None
    start: datetime | None = None
    tz: str | None = None
    ambient: float | None = None
    environment: Mapping[str, Any] | None = None
    inlet: float | None = None
    loads: Mapping[str, Any] | None = None
    commands: Mapping[str, Any] | None = None
    params: Mapping[str, Any] | None = None
    #: Where the air, its humidity and the inlet are read live
    #: (``sim_home_assistant.Sources``), when the heater is.
    sources: Any = None
    #: The bath and the shower readiness is judged against, delivered,
    #: in the preferred unit; None: the parameters'.
    bath: float | None = None
    shower: float | None = None

    def __post_init__(self) -> None:
        if self.ambient is not None and self.environment is not None:
            raise InputError("give --ambient or --environment, not both")
        if self.start is not None and self.start.tzinfo is None:
            raise InputError("--start needs its UTC offset")
        for name in ("bath", "shower"):
            value = getattr(self, name)
            if value is not None and not value > 0.0:
                raise InputError(f"--{name} must be a positive volume")
        if self.tz is not None:
            zone_name(self.tz)
        if self.scenario is not None:
            version = self.scenario.get("schema_version")
            if version != SCHEMA_VERSION:
                raise InputError(
                    f"unsupported scenario schema_version {version!r}"
                )
            if not isinstance(self.scenario.get("scenario"), Mapping):
                raise InputError("a scenario document has a scenario object")

    @property
    def needs_device(self) -> bool:
        """Whether any part is read from the device: without a scenario
        document, or with one and ``--live``."""
        return self.scenario is None or self.live

    def zone(self) -> str:
        """The zone the schedules' local times are in: ``--tz``, the
        scenario's, then this machine's."""
        if self.tz is not None:
            return self.tz
        if self.scenario is not None:
            given = self.scenario["scenario"].get("tz")
            if isinstance(given, str):
                return zone_name(given)
        if (tz := local_zone()) is not None:
            return tz
        raise InputError(
            "this machine's time zone has no name; give --tz "
            "(an IANA zone such as America/Los_Angeles)"
        )


def build(
    inputs: Inputs, live: sim_live.Composed | None, now: datetime
) -> Built:
    """The scenario: the device's parts (``live``), the scenario
    document's laid over them (``sim_live.overlay``), then the flags'.
    ``now`` is the start when nothing gives one."""
    replace: dict[str, Any] = {}
    if inputs.start is not None:
        replace["start"] = inputs.start
    if inputs.hours is not None:
        replace["horizon"] = timedelta(hours=inputs.hours)
    if inputs.tz is not None:
        replace["tz"] = inputs.tz
    if inputs.environment is not None:
        replace["environment"] = dict(inputs.environment)
    if inputs.loads is not None:
        replace["loads"] = dict(inputs.loads)
    if inputs.commands is not None:
        replace["commands"] = dict(inputs.commands)
    environment: dict[str, float] = {}
    if inputs.ambient is not None:
        environment["ambient_f"] = sa.to_sim_temperature(inputs.ambient)
    if inputs.inlet is not None:
        environment["inlet_f"] = sa.to_sim_temperature(inputs.inlet)
    params = None
    if inputs.params is not None:
        params = read_params(inputs.params, "--params")
    try:
        built = sim_live.overlay(
            live,
            inputs.scenario,
            now=now,
            # A live scenario carries its zone.
            tz=None if live is not None else inputs.zone(),
            params=params,
            replace=replace,
            over={"environment": environment} if environment else None,
        )
    except ValueError as e:
        raise InputError(str(e)) from None
    notes = tuple(_OPTION_NOTES.get(n, n) for n in built.notes)
    return Built(built.scenario, built.params, notes)


def read_params(doc: Any, what: str) -> sim.HeaterParams:
    """``doc`` as parameters; ``what`` names it in the error."""
    try:
        return params_from_document(doc)
    except ValueError as e:
        raise InputError(f"{what} is not a parameters document: {e}") from None


async def compose_live(
    mqtt: NavienMqttClient,
    api: NavienAPIClient,
    device: Device,
    inputs: Inputs,
    now: datetime,
) -> sim_live.Composed:
    """The device's heater and schedules from ``now``, and the air, its
    humidity and the inlet from ``inputs.sources`` when given, over the
    span the scenario will walk (``window``); ``now`` stays the clock a
    reading's freshness is judged by."""
    horizon = timedelta(hours=inputs.hours or DEFAULT_HOURS)
    start, span = window(inputs, now)

    async def compose(environment: Any = None) -> sim_live.Composed:
        return await sim_live.compose(
            start=now,
            horizon=horizon,
            tz=inputs.zone(),
            heater=sim_live.LiveHeaterSource(mqtt, device),
            schedules=sim_live.LiveScheduleSource(mqtt, api, device),
            environment=environment,
        )

    if inputs.sources is None:
        return await compose()
    from nwp500 import sim_home_assistant as ha

    src = inputs.sources
    async with ha.HomeAssistantClient(src.url, src.token) as client:
        environment = ha.HomeAssistantEnvironment(
            client,
            src.entities,
            start=start,
            until=start + span,
            now=now,
            location_air=src.location_air,
            heater=src.heater,
        )
        composed = await compose(environment)
    for note in environment.notes:
        if "not read" in note or "stale" in note or "unknown" in note:
            _logger.warning(note)
        else:
            _logger.info(note)
    return composed


async def read_tank(inputs: Inputs, now: datetime) -> HomeAssistantTank | None:
    """The tank's keeper (``sim_home_assistant.HomeAssistantTank``) with
    the history read to ``now``, when the sources name the heater's
    entities and the draw flow; None otherwise. Its ``layers`` makes no
    request, so it replays after the client is closed."""
    src = inputs.sources
    if src is None or src.heater is None or src.entities.draw_flow is None:
        return None
    from nwp500 import sim_home_assistant as ha

    async with ha.HomeAssistantClient(src.url, src.token) as client:
        keeper = ha.HomeAssistantTank(
            client,
            src.heater,
            src.entities.draw_flow,
            src.entities,
            flow_volume=src.draw_flow_volume,
        )
        await keeper.read(now)
    return keeper


def layered(
    keeper: HomeAssistantTank | None, built: Built, now: datetime
) -> Built:
    """``built`` starting from the tank's layers its history leaves
    (``HomeAssistantTank.layers``), the scenario's probes laid over
    them: only for a scenario that starts ``now``, whose state is the
    heater's now, and gives no layers of its own. Without them, ``built``
    as it is, which the simulator starts from the two probes. The notes
    are logged."""
    state = built.scenario.state
    if keeper is None or state.layers_f is not None:
        return built
    if built.scenario.start != now:
        _logger.warning(
            "layers: the scenario starts at %s, not now: walked from "
            "the two probes",
            built.scenario.start.isoformat(),
        )
        return built
    answer = keeper.layers(now, built.params, (state.upper_f, state.lower_f))
    for note in answer.notes:
        if answer.layers_f is None:
            _logger.warning(note)
        else:
            _logger.info(note)
    if answer.layers_f is None:
        return built
    scenario = built.scenario.model_copy(
        update={"state": state.model_copy(update={"layers_f": answer.layers_f})}
    )
    return Built(scenario, built.params, built.notes)


def window(inputs: Inputs, now: datetime) -> tuple[datetime, timedelta]:
    """The start and horizon ``build`` will give the scenario: a flag,
    then the scenario document's, then ``now`` and ``DEFAULT_HOURS``.
    A document value that does not parse is left for ``build`` to
    refuse."""
    from pydantic import TypeAdapter, ValidationError

    doc = {} if inputs.scenario is None else inputs.scenario["scenario"]
    start, horizon = now, timedelta(hours=DEFAULT_HOURS)
    try:
        if "start" in doc:
            start = TypeAdapter(datetime).validate_python(doc["start"])
        if "horizon" in doc:
            horizon = TypeAdapter(timedelta).validate_python(doc["horizon"])
    except ValidationError:
        pass
    if inputs.start is not None:
        start = inputs.start
    if inputs.hours is not None:
        horizon = timedelta(hours=inputs.hours)
    return start, horizon


def read_sources(path: str | Path) -> Any:
    """The sources file at ``path`` (TOML), its token read from the
    environment."""
    import tomllib

    from nwp500 import sim_home_assistant as ha

    try:
        with Path(path).open("rb") as f:
            doc = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise InputError(f"cannot read the sources file {path}: {e}") from None
    try:
        return ha.sources_from(doc, os.environ)
    except ValueError as e:
        raise InputError(f"the sources file {path}: {e}") from None


def snapshot_document(composed: sim_live.Composed) -> dict[str, Any]:
    """The device's state as a scenario document, to edit and replay:
    one instant, with the parameters for its tank size when known."""
    return scenario_to_document(composed.scenario, composed.params)


# ── output ──────────────────────────────────────────────────────────


def _local(at: datetime, tz: str) -> str:
    return at.astimezone(ZoneInfo(tz)).strftime("%a %H:%M")


def _wh(value: float | None) -> str:
    return "unpriced" if value is None else f"{value:,.0f}"


def _temp(value_f: float) -> str:
    return f"{sa.temperature(value_f):.1f} {sa.temperature_unit()}"


def _volume(value_gal: float | None) -> str:
    if value_gal is None:
        return "-"
    return f"{sa.volume(value_gal):.1f} {sa.volume_unit()}"


def energy_totals(
    result: sim.SimulationResult,
) -> tuple[float | None, float]:
    """The compressor's and the elements' electricity over the walk, Wh;
    the compressor's None when an interval could not be priced."""
    compressor: float | None = 0.0
    element = 0.0
    for _, c, e in result.energy_by_source():
        compressor = None if c is None or compressor is None else compressor + c
        element += e
    return compressor, element


def hot_water_lines(
    built: Built,
    bath_gal: float | None = None,
    shower_gal: float | None = None,
) -> list[str]:
    """The bath and the showers the tank is ready for now
    (``sim.time_to_ready``): the bath's margin, or when the heat pump
    has it ready; the whole showers. Volumes in gallons, None for the
    parameters'."""
    try:
        r = sim.time_to_ready(
            built.scenario,
            built.params,
            bath_gal=bath_gal,
            shower_gal=shower_gal,
        )
    except SimulationError as e:
        return [f"Bath and showers: not computed ({e})"]
    bath = r.bath
    if bath.ready:
        state = f"ready, {_volume(bath.margin_gal)} to spare"
    elif bath.ready_at is not None:
        state = (
            f"not ready, {_volume(-bath.margin_gal)} short; the heat pump "
            f"has it ready at {_local(bath.ready_at, built.scenario.tz)}"
        )
    else:
        state = f"not ready, {_volume(-bath.margin_gal)} short"
    showers = r.showers
    return [
        f"Bath ({_volume(bath.volume_gal)}): {state}",
        f"Showers ({_volume(showers.volume_gal)}): "
        f"{showers.ready_for_whole} ready",
    ]


def print_table(
    built: Built,
    result: sim.SimulationResult,
    console: Console,
    bath_gal: float | None = None,
    shower_gal: float | None = None,
) -> None:
    """The heating intervals, the energy by source, the readiness with
    the bath and the showers, the draw windows
    (and which ran cold), the reasons and the defaults."""
    s = built.scenario
    tz = s.tz
    ready = sim.readiness(
        s.state, s.settings, built.params, inlet_f=s.environment.inlet_f
    )
    console.print(
        f"[bold]{_local(s.start, tz)} to {_local(s.until, tz)}[/bold] ({tz}): "
        f"tank {_temp(s.state.upper_f)} upper, {_temp(s.state.lower_f)} "
        f"lower, setpoint {_temp(s.settings.setpoint_f)}; "
        f"{_volume(ready.gal)} deliverable now ({ready.basis})"
    )
    for line in hot_water_lines(built, bath_gal, shower_gal):
        console.print(line)

    heating = Table(title="Heating")
    for col in ("Start", "End", "Source", "Why", "Target", "Stop", "Wh"):
        heating.add_column(col)
    for h in result.heating:
        why = h.start.trigger or h.start.cause
        if h.start.serves:
            why = f"{why} ({h.start.serves})"
        source = h.source if h.zone is None else f"{h.source} ({h.zone})"
        heating.add_row(
            _local(h.start.at, tz),
            _local(h.end, tz),
            source,
            str(why),
            _temp(h.target_f),
            h.stop + (" (capped)" if h.capped else ""),
            _wh(h.input_wh),
        )
    if result.heating:
        console.print(heating)
    else:
        console.print("No heating over the span.")

    compressor, element = energy_totals(result)
    console.print(
        f"Energy: compressor {_wh(compressor)} Wh, element {_wh(element)} Wh"
    )

    if result.windows:
        windows = Table(title="Draw windows")
        for col in ("Start", "End", "Deliverable", "Margin", "Lowest", "Cold"):
            windows.add_column(col)
        for w in result.windows:
            windows.add_row(
                _local(w.start, tz),
                _local(w.end, tz),
                _volume(w.deliverable_gal),
                _volume(w.margin_gal),
                _temp(w.delivery_min_f),
                "[red]ran cold[/red]" if w.depleted else "",
            )
        console.print(windows)

    if result.reasons:
        console.print("Reasons: " + ", ".join(result.reasons))
    if result.defaults_used:
        console.print("Defaults used: " + ", ".join(result.defaults_used))


#: The CSV's columns after the instant, the temperatures in the
#: preferred unit.
CSV_COLUMNS = (
    "upper",
    "lower",
    "setpoint",
    "delivery",
    "heating",
    "compressor_wh",
    "element_wh",
    "mode",
)


def write_csv(result: sim.SimulationResult, out: TextIO) -> None:
    """The path, one row per point."""
    suffix = "_c" if sa.temperature_unit() == "°C" else "_f"
    header = [
        f"{c}{suffix}" if c in ("upper", "lower", "setpoint", "delivery") else c
        for c in CSV_COLUMNS
    ]
    writer = csv.writer(out)
    writer.writerow(["at", *header])
    for reading, point in zip(sa.path(result), result.points, strict=True):
        writer.writerow(
            [
                reading.at.isoformat(),
                reading.upper,
                reading.lower,
                reading.setpoint,
                "" if reading.delivery is None else reading.delivery,
                int(point.heating),
                "" if point.input_wh is None else point.input_wh,
                point.element_wh,
                point.mode,
            ]
        )


def run(
    inputs: Inputs,
    live: sim_live.Composed | None,
    now: datetime,
    output_format: str,
    out: TextIO | None = None,
    keeper: HomeAssistantTank | None = None,
) -> sim.SimulationResult:
    """Build the scenario, walk it and print the result: from the tank's
    layers when ``keeper`` (``read_tank``) gives them."""
    built = layered(keeper, build(inputs, live, now), now)
    for note in built.notes:
        _logger.warning(note)
    try:
        result = sim.simulate(built.scenario, built.params)
    except SimulationError as e:
        raise InputError(f"the scenario cannot be simulated: {e}") from None
    stream = out or sys.stdout
    if output_format == "json":
        json.dump(result_to_document(result), stream, indent=2)
        stream.write("\n")
    elif output_format == "csv":
        write_csv(result, stream)
    else:
        print_table(
            built,
            result,
            Console(file=stream),
            None if inputs.bath is None else sa.to_sim_volume(inputs.bath),
            None if inputs.shower is None else sa.to_sim_volume(inputs.shower),
        )
    return result
