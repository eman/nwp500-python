"""The simulator's other inputs, read live from Home Assistant.

The heater reports its tank, its settings and its schedules, but not
the air it stands in while idle, that air's humidity, the mains water,
the water drawn or a circulation pump it does not run. An owner who
records those in Home Assistant gets them into a simulation through
this module, a ``sim_live`` source:

- ``HomeAssistantClient`` reads Home Assistant's REST API:
  ``/api/states/<entity>`` for the value now, ``/api/history/period``
  for recent history, and the ``weather.get_forecasts`` service for the
  outdoor forecast.
- ``HomeAssistantEnvironment`` is an ``EnvironmentSource`` for
  ``sim_live.compose()``:

  - **the air:** the outdoor forecast projected through a
    ``location_air`` model, given or fitted on the recent history,
    anchored to a fresh reading of the air beside the heater; without
    a weather entity or a model, that reading held over the span;
  - **the humidity:** a fresh reading;
  - **the inlet:** the plateau of the long draws in the last 72 h, from
    the inlet probe, the household's draws (a demand entity) and the
    circulation's runs
    (``sim_adapters.cold_supply``).

Readings are used by these rules:

- a reading more than an hour old is not used;
- a pump with no reading in force is unknown, never idle;
- a part that cannot be read leaves the simulator's default in place,
  and ``notes`` say why.

Units come from each entity's ``unit_of_measurement``. Entity ids come
from the caller's configuration (``sources_from``).
"""

import enum
import logging
import math
from bisect import bisect_right
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from nwp500 import sim_adapters as sa
from nwp500.exceptions import Nwp500Error
from nwp500.sim import Environment
from nwp500.sim.book import AMBIENT_DEFAULT_F, Booked, FlowVolume
from nwp500.sim.cold_supply import ColdSupply, on_the_mains
from nwp500.sim.location_air import (
    FIT_LAGS_H,
    FittedLocationAir,
    LocationAirModel,
)
from nwp500.sim.location_air import fit as fit_air
from nwp500.sim.location_air import project as project_air
from nwp500.sim.params import HeaterParams

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

#: A reading: an instant and a value.
Reading = tuple[datetime, float]
#: A span: its start and its end.
Span = tuple[datetime, datetime]

#: A reading older than this is not used.
FRESH = timedelta(hours=1)
#: A pump at or above this speed is running, rpm.
PUMP_ON_RPM = 10.0
#: For a sampled speed (``pump_runs``' ``stale``): a run silent this
#: long has ended. A history of changes writes no row for a steady
#: speed, so its runs hold until the speed changes.
PUMP_STALE = timedelta(seconds=300)
#: How far back the inlet's plateau looks.
INLET_LOOKBACK = timedelta(hours=72)
#: The grid the inlet probe's history is read on (``held``): the
#: plateau takes readings as samples, and a history keeps only changes.
PROBE_STEP = timedelta(seconds=10)
#: How far back the air beside the heater and the outdoor air are read
#: to fit a ``location_air`` model where none is given.
LOCATION_AIR_WINDOW = timedelta(days=3)
#: The least span of readings such a fit is made on: a day, so it sees
#: the outdoor air's daily swing.
LOCATION_AIR_MIN_SPAN = timedelta(days=1)
#: The least r (``FittedLocationAir.r``) such a fit is used at.
LOCATION_AIR_MIN_R = 0.5
#: The heater's own air reading is the air it stands in from this far
#: into a compressor run, and not while idle: the book's settle
#: (``sim_adapters.HEATER_AIR_SETTLE``).
RUN_SETTLE = sa.HEATER_AIR_SETTLE
#: How long a request waits, seconds.
DEFAULT_TIMEOUT = 10.0

#: Runs a piece of CPU work and awaits its result: Home Assistant's
#: ``hass.async_add_executor_job``, say, so the work leaves the event
#: loop. ``inline`` runs it where it is.
type Run = Callable[[Callable[[], Any]], Awaitable[Any]]


async def inline(work: Callable[[], Any]) -> Any:
    """``work()``, on the caller's own thread: the default ``Run``."""
    return work()


#: The states Home Assistant reports for a value it does not have.
_NO_VALUE = frozenset({"unknown", "unavailable", "none", ""})
_L_PER_GAL = 3.785411784


class HomeAssistantError(Nwp500Error):
    """Home Assistant could not be read, or did not answer as it does."""


# ── configuration ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Entities:
    """The Home Assistant entities that hold each input; None for one
    the installation does not record."""

    #: The air beside the heater (a temperature sensor).
    air: str | None = None
    #: That air's relative humidity.
    humidity: str | None = None
    #: A probe on the cold supply.
    inlet: str | None = None
    #: A binary sensor on while the household draws hot water, the
    #: circulation's water not among its draws (``demand_spans``).
    demand: str | None = None
    #: The circulation pump's speed.
    circulation_speed: str | None = None
    #: A weather entity with an hourly forecast, its ``temperature``
    #: attribute the outdoor air.
    weather: str | None = None
    #: The household's hot water draw flow, the circulation's water not
    #: in it, such as a draw detector's (``HomeAssistantBook``'s
    #: ``flow``): with the heater's entities, the heat book.
    draw_flow: str | None = None


@dataclass(frozen=True)
class Sources:
    """Where the inputs are: Home Assistant's address and token, the
    entities, and the model that projects the air from the outdoor
    forecast (None: one fitted from the recent history, as
    ``HomeAssistantEnvironment`` fits it)."""

    url: str
    token: str = field(repr=False)
    entities: Entities
    location_air: LocationAirModel | None = None
    #: The heater's own entities, whose air while the compressor runs
    #: fits and anchors the projection where no air entity does.
    heater: HeaterEntities | None = None
    #: What ``entities.draw_flow``'s gallons count (``book.FlowVolume``).
    draw_flow_volume: FlowVolume = "delivered"


def sources_from(doc: Mapping[str, Any], environ: Mapping[str, str]) -> Sources:
    """``Sources`` from a configuration document (a parsed TOML file)::

        [home_assistant]
        url = "http://homeassistant.local:8123"
        token_env = "HA_TOKEN"          # the variable holding the token
        draw_flow_volume = "tank"       # optional: "delivered", the default

        [home_assistant.entities]
        air = "sensor.beside_the_heater_temperature"
        humidity = "sensor.beside_the_heater_humidity"
        inlet = "sensor.cold_supply_temperature"
        demand = "binary_sensor.hot_water_demand"
        circulation_speed = "sensor.circulation_pump_speed"
        weather = "weather.forecast_home"
        draw_flow = "sensor.hot_water_draw_flow"

        [home_assistant.heater]         # optional: the heater's own
        heard = "sensor.water_heater_last_status"
        upper = "sensor.water_heater_upper_tank_temperature"
        lower = "sensor.water_heater_lower_tank_temperature"
        compressor = "binary_sensor.water_heater_compressor"
        ambient = "sensor.water_heater_ambient_temperature"

        [location_air]                  # optional
        damping = 0.638
        lag_hours = 2.0
        offset_f = 24.5

    The token is read from ``environ``, never from the file.
    ``draw_flow_volume`` says what the draw flow's gallons count: the
    water delivered through the mixing valve, or the tank's own water
    (``sim_adapters.book_from_history``'s ``flow_volume``). Raises
    ``ValueError`` naming what is wrong."""
    ha = doc.get("home_assistant")
    if not isinstance(ha, Mapping):
        raise ValueError("no [home_assistant] table")
    ha = cast(Mapping[str, Any], ha)
    url = ha.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("home_assistant.url must be an http(s) URL")
    token_env = ha.get("token_env", "HA_TOKEN")
    if not isinstance(token_env, str):
        raise ValueError("home_assistant.token_env must be a variable name")
    token = environ.get(token_env)
    if not token:
        raise ValueError(f"the token variable {token_env} is not set")
    volume = ha.get("draw_flow_volume", "delivered")
    if volume not in ("delivered", "tank"):
        raise ValueError(
            'home_assistant.draw_flow_volume must be "delivered" or "tank"'
        )
    raw = ha.get("entities", {})
    if not isinstance(raw, Mapping):
        raise ValueError("home_assistant.entities must be a table")
    raw = cast(Mapping[str, Any], raw)
    known = set(Entities.__dataclass_fields__)
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"unknown entities: {', '.join(unknown)}")
    for name, value in raw.items():
        if not isinstance(value, str) or "." not in value:
            raise ValueError(f"entities.{name} must be an entity id")
    model = None
    la = doc.get("location_air")
    if la is not None:
        if not isinstance(la, Mapping):
            raise ValueError("[location_air] must be a table")
        la = cast(Mapping[str, Any], la)
        try:
            model = LocationAirModel(
                damping=float(la["damping"]),
                lag=timedelta(hours=float(la["lag_hours"])),
                offset_f=float(la["offset_f"]),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(
                "[location_air] needs damping, lag_hours and offset_f"
            ) from e
    return Sources(
        url=url.rstrip("/"),
        token=token,
        entities=Entities(**raw),
        location_air=model,
        heater=_heater_from(ha.get("heater")),
        draw_flow_volume=volume,
    )


def _heater_from(raw: Any) -> HeaterEntities | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("home_assistant.heater must be a table")
    raw = cast(Mapping[str, Any], raw)
    unknown = sorted(set(raw) - set(HeaterEntities.__dataclass_fields__))
    if unknown:
        raise ValueError(f"unknown heater entities: {', '.join(unknown)}")
    for name, value in raw.items():
        if not isinstance(value, str) or "." not in value:
            raise ValueError(f"heater.{name} must be an entity id")
    missing = [n for n in ("heard", "upper", "lower") if n not in raw]
    if missing:
        raise ValueError(f"home_assistant.heater needs {', '.join(missing)}")
    return HeaterEntities(**raw)


# ── parsing: Home Assistant's answers, as values ────────────────────


def _instant(text: Any) -> datetime:
    if not isinstance(text, str):
        raise HomeAssistantError(f"{text!r} is not an instant")
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        raise HomeAssistantError(f"{text!r} is not an instant") from None
    # Home Assistant's instants are UTC; a naive one is taken as UTC.
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at


def _number(state: Any) -> float | None:
    if not isinstance(state, str | int | float) or isinstance(state, bool):
        return None
    if isinstance(state, str) and state.strip().lower() in _NO_VALUE:
        return None
    try:
        value = float(state)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


@dataclass(frozen=True)
class State:
    """An entity's value now: the number (None for none), its unit, and
    when it was last reported."""

    entity: str
    value: float | None
    unit: str | None
    at: datetime


def parse_state(doc: Any) -> State:
    """``/api/states/<entity>``'s answer. ``at`` is when the entity
    last reported (``last_reported``). Home Assistant serves that answer
    from a copy it keeps until the state or its attributes change, and a
    report of the same value doesn't renew it, so over REST ``at`` can
    be older than the entity's last report. Home Assistant before 2024.3
    has no ``last_reported``; then ``at`` is the last state or attribute
    change (``last_updated``, else ``last_changed``)."""
    if not isinstance(doc, Mapping) or "state" not in doc:
        raise HomeAssistantError("not an entity state")
    d = cast(Mapping[str, Any], doc)
    attributes = d.get("attributes")
    unit = None
    if isinstance(attributes, Mapping):
        u = cast(Mapping[str, Any], attributes).get("unit_of_measurement")
        unit = u if isinstance(u, str) else None
    stamp = (
        d.get("last_reported") or d.get("last_updated") or d.get("last_changed")
    )
    return State(
        entity=str(d.get("entity_id", "")),
        value=_number(d.get("state")),
        unit=unit,
        at=_instant(stamp),
    )


def parse_history(doc: Any) -> dict[str, list[Reading]]:
    """``/api/history/period``'s answer, by entity: each row's instant
    (``last_updated``, else ``last_changed``) and number, in time
    order, values Home Assistant does not have left out."""
    if not isinstance(doc, list):
        raise HomeAssistantError("not a history")
    out: dict[str, list[Reading]] = {}
    for series in doc:
        if not isinstance(series, list) or not series:
            continue
        rows = series
        first = rows[0]
        if not isinstance(first, Mapping) or "entity_id" not in first:
            raise HomeAssistantError("a history series names no entity")
        entity = str(cast(Mapping[str, Any], first)["entity_id"])
        readings: list[Reading] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            r = cast(Mapping[str, Any], row)
            value = _number(r.get("state"))
            stamp = r.get("last_updated") or r.get("last_changed")
            if value is not None and stamp is not None:
                readings.append((_instant(stamp), value))
        out[entity] = sorted(readings, key=lambda x: x[0])
    return out


def parse_outages(doc: Any, end: datetime) -> dict[str, list[Span]]:
    """The spans in ``/api/history/period``'s answer that each entity
    was ``unavailable`` or ``unknown``: from that row to the next with a
    number, or to ``end``. ``parse_history`` leaves those rows out, so
    without these an outage reads as the last value held."""
    if not isinstance(doc, list):
        raise HomeAssistantError("not a history")
    out: dict[str, list[Span]] = {}
    for series in doc:
        if not isinstance(series, list) or not series:
            continue
        rows = [
            cast(Mapping[str, Any], r) for r in series if isinstance(r, Mapping)
        ]
        if not rows or "entity_id" not in rows[0]:
            continue
        stamped = sorted(
            (
                (_instant(stamp), _number(r.get("state")) is not None)
                for r in rows
                if (stamp := r.get("last_updated") or r.get("last_changed"))
            ),
            key=lambda x: x[0],
        )
        spans: list[Span] = []
        down: datetime | None = None
        for at, known in stamped:
            if not known and down is None:
                down = at
            elif known and down is not None:
                spans.append((down, at))
                down = None
        if down is not None and end > down:
            spans.append((down, end))
        out[str(rows[0]["entity_id"])] = spans
    return out


@dataclass(frozen=True)
class History:
    """A history's readings and its outages, by entity, each present,
    and the unit each reading was recorded in, where it was read."""

    readings: dict[str, list[Reading]]
    outages: dict[str, list[Span]]
    #: Aligned with ``readings``; None where the history carries no
    #: attributes, when each reading is taken to be in today's unit.
    units: dict[str, list[str | None]] | None = None
    #: Every row's instant and state as Home Assistant wrote it, numbers
    #: or not, ``unavailable`` and ``unknown`` included, in time order;
    #: None from a client that does not give them.
    states: dict[str, list[tuple[datetime, str]]] | None = None

    def extended(self, newer: History) -> History:
        """This history with a later read's, entity by entity: the
        readings (with their units) and the states merged by instant,
        the later read's row winning at a shared instant, the outages
        joined. Units or states that either read lacks are None; an
        entity's units are kept only where every reading records one,
        else its readings are in today's unit, as ``converted`` reads a
        history without them."""
        names = sorted({*self.readings, *newer.readings})
        readings: dict[str, list[Reading]] = {}
        units: dict[str, list[str | None]] = {}
        for n in names:
            rows = sa.merge_changes(_with_units(self, n), _with_units(newer, n))
            readings[n] = [(t, v) for t, (v, _, _) in rows]
            recorded = _unit_list(rows)
            if recorded is not None:
                units[n] = recorded
        states = None
        if self.states is not None and newer.states is not None:
            states = {
                n: [
                    (t, str(v))
                    for t, v in sa.merge_changes(
                        self.states.get(n, []), newer.states.get(n, [])
                    )
                ]
                for n in sorted({*self.states, *newer.states})
            }
        return History(
            readings,
            {
                n: sa.join_spans(
                    self.outages.get(n, []), newer.outages.get(n, [])
                )
                for n in sorted({*self.outages, *newer.outages})
            },
            units
            if self.units is not None and newer.units is not None
            else None,
            states,
        )

    def since(self, start: datetime) -> History:
        """This history from ``start``: each entity's readings and states
        from it and the one in force at it, the outages that end after
        it."""
        readings: dict[str, list[Reading]] = {}
        units: dict[str, list[str | None]] = {}
        for n in self.readings:
            rows = sa.changes_since(_with_units(self, n), start)
            readings[n] = [(t, v) for t, (v, _, _) in rows]
            recorded = _unit_list(rows)
            if recorded is not None:
                units[n] = recorded
        return History(
            readings,
            {n: sa.spans_since(s, start) for n, s in self.outages.items()},
            None if self.units is None else units,
            None
            if self.states is None
            else {
                n: [(t, str(v)) for t, v in sa.changes_since(rows, start)]
                for n, rows in self.states.items()
            },
        )

    def converted(
        self,
        entity: str,
        unit: str | None,
        to: Callable[[float, str | None], float],
        until: datetime | None = None,
    ) -> tuple[list[Reading], list[Span]]:
        """``entity``'s readings through ``to``, each from the unit it
        was recorded in (``unit``, today's, where the history carries
        none): a sensor's unit can change, and its history keeps the
        old one. The second item is the spans of the readings left out,
        in a unit ``to`` refuses or none at all: each from its instant to
        the next reading's (``until`` for the last), when what the
        entity said is unknown. Raises ValueError if ``to`` refuses
        ``unit`` itself."""
        to(50.0, unit)
        rows = self.readings.get(entity, [])
        recorded = None if self.units is None else self.units.get(entity)
        out: list[Reading] = []
        unread: list[Span] = []
        for i, (t, v) in enumerate(rows):
            u = unit if recorded is None or i >= len(recorded) else recorded[i]
            try:
                out.append((t, to(v, u)))
            except ValueError:
                b = rows[i + 1][0] if i + 1 < len(rows) else until or t
                unread.append((t, max(b, t)))
        return out, unread


def _with_units(
    history: History, entity: str
) -> list[tuple[datetime, tuple[float, str | None, bool]]]:
    """``entity``'s readings, each with the unit it was recorded in and
    whether the history records one for it: without (no units, or none
    for this reading), ``converted`` reads it in today's unit, which an
    explicit None (recorded with no unit) is not."""
    rows = history.readings.get(entity, [])
    units = None if history.units is None else history.units.get(entity)
    return [
        (
            t,
            (v, units[i], True)
            if units is not None and i < len(units)
            else (v, None, False),
        )
        for i, (t, v) in enumerate(rows)
    ]


def _unit_list(
    rows: Sequence[tuple[datetime, tuple[float, str | None, bool]]],
) -> list[str | None] | None:
    """The units of ``rows`` as ``History.units`` holds them, or None
    (today's unit for each) unless every reading records its own."""
    if not all(known for _, (_, _, known) in rows):
        return None
    return [u for _, (_, u, _) in rows]


def parse_units(doc: Any) -> dict[str, list[str | None]]:
    """The unit each of ``parse_history``'s readings was recorded in
    (its row's ``unit_of_measurement``, None if it carries none), by
    entity, in the same order."""
    if not isinstance(doc, list):
        raise HomeAssistantError("not a history")
    out: dict[str, list[str | None]] = {}
    for series in doc:
        if not isinstance(series, list) or not series:
            continue
        rows = [
            cast(Mapping[str, Any], r) for r in series if isinstance(r, Mapping)
        ]
        if not rows or "entity_id" not in rows[0]:
            continue
        units: list[tuple[datetime, str | None]] = []
        for r in rows:
            stamp = r.get("last_updated") or r.get("last_changed")
            if _number(r.get("state")) is None or stamp is None:
                continue
            attributes = r.get("attributes")
            unit = (
                cast(Mapping[str, Any], attributes).get("unit_of_measurement")
                if isinstance(attributes, Mapping)
                else None
            )
            units.append(
                (_instant(stamp), unit if isinstance(unit, str) else None)
            )
        out[str(rows[0]["entity_id"])] = [
            u for _, u in sorted(units, key=lambda x: x[0])
        ]
    return out


def parse_states(doc: Any) -> dict[str, list[tuple[datetime, str]]]:
    """Every row of ``/api/history/period``'s answer, by entity: its
    instant (``last_updated``, else ``last_changed``) and its state as
    written, in time order. ``parse_history`` keeps only the numbers;
    these keep a binary sensor's ``on``, an enum's name and an outage's
    ``unavailable`` too."""
    if not isinstance(doc, list):
        raise HomeAssistantError("not a history")
    out: dict[str, list[tuple[datetime, str]]] = {}
    for series in doc:
        if not isinstance(series, list) or not series:
            continue
        rows = [
            cast(Mapping[str, Any], r) for r in series if isinstance(r, Mapping)
        ]
        if not rows or "entity_id" not in rows[0]:
            continue
        out[str(rows[0]["entity_id"])] = sorted(
            (
                (_instant(stamp), str(r.get("state")))
                for r in rows
                if (stamp := r.get("last_updated") or r.get("last_changed"))
            ),
            key=lambda x: x[0],
        )
    return out


def history_for(doc: Any, entities: Iterable[str]) -> dict[str, list[Reading]]:
    """``parse_history`` for ``entities``, each present: Home Assistant
    leaves out an entity with no history over the span, which is an
    empty series, not an error."""
    parsed = parse_history(doc)
    return {e: parsed.get(e, []) for e in entities}


def parse_forecast(doc: Any, entity: str) -> tuple[list[Reading], str | None]:
    """``weather.get_forecasts``'s answer for ``entity``: each hour's
    instant and temperature, and the unit when the answer gives one."""
    try:
        body = cast(Mapping[str, Any], doc)["service_response"][entity]
        hours = body["forecast"]
    except KeyError, TypeError:
        raise HomeAssistantError(f"no forecast for {entity}") from None
    if not isinstance(hours, list):
        raise HomeAssistantError(f"no forecast for {entity}")
    out: list[Reading] = []
    for hour in hours:
        if not isinstance(hour, Mapping):
            continue
        h = cast(Mapping[str, Any], hour)
        value = _number(h.get("temperature"))
        if value is not None and "datetime" in h:
            out.append((_instant(h["datetime"]), value))
    unit = body.get("temperature_unit") if isinstance(body, Mapping) else None
    return sorted(out, key=lambda x: x[0]), (
        unit if isinstance(unit, str) else None
    )


def parse_outdoor_history(
    doc: Any, entity: str
) -> list[tuple[datetime, float, str | None]]:
    """A weather entity's outdoor air from ``/api/history/period``'s
    answer: each row's instant, ``temperature`` attribute and the unit
    it was recorded in (``temperature_unit``, None where the row names
    none), in time order. Rows without a number are left out."""
    if not isinstance(doc, list):
        raise HomeAssistantError("not a history")
    out: list[tuple[datetime, float, str | None]] = []
    for series in doc:
        if not isinstance(series, list):
            continue
        for r in series:
            if not isinstance(r, Mapping):
                continue
            row = cast(Mapping[str, Any], r)
            if row.get("entity_id", entity) != entity:
                break
            stamp = row.get("last_updated") or row.get("last_changed")
            attributes = row.get("attributes")
            if stamp is None or not isinstance(attributes, Mapping):
                continue
            a = cast(Mapping[str, Any], attributes)
            value = _number(a.get("temperature"))
            if value is None:
                continue
            unit = a.get("temperature_unit")
            out.append(
                (
                    _instant(stamp),
                    value,
                    unit if isinstance(unit, str) else None,
                )
            )
    out.sort(key=lambda x: x[0])
    return out


def to_f(value: float, unit: str | None) -> float:
    """A temperature in ``unit`` (°F, °C or K), in °F."""
    u = (unit or "").strip().replace("º", "°")
    if u in ("°F", "F"):
        return value
    if u in ("°C", "C"):
        return value * 1.8 + 32.0
    if u == "K":
        return (value - 273.15) * 1.8 + 32.0
    raise ValueError(f"{unit!r} is not a temperature unit")


def to_gpm(value: float, unit: str | None) -> float:
    """A flow in ``unit`` (gal/min, L/min, L/h, m³/h), in US gal/min."""
    u = (unit or "").strip().lower().replace(" ", "")
    if u in ("gal/min", "gpm"):
        return value
    if u in ("l/min", "lpm"):
        return value / _L_PER_GAL
    if u == "l/h":
        return value / _L_PER_GAL / 60.0
    if u in ("m³/h", "m3/h"):
        return value * 1000.0 / _L_PER_GAL / 60.0
    raise ValueError(f"{unit!r} is not a flow unit")


def to_rpm(value: float, unit: str | None) -> float:
    """A rotational speed in ``unit`` (rpm, Hz), in rpm."""
    u = (unit or "").strip().lower().replace(" ", "")
    if u in ("rpm", "r/min", "rev/min"):
        return value
    if u == "hz":
        return value * 60.0
    raise ValueError(f"{unit!r} is not a rotational speed unit")


def held(
    readings: Sequence[Reading],
    start: datetime,
    end: datetime,
    step: timedelta = PROBE_STEP,
) -> list[Reading]:
    """``readings``, a history of changes, as a probe sampled every
    ``step`` from ``start`` to ``end`` would read them: the value in
    force at each instant, none before the first reading. A history
    writes no row for a report of the value it already holds, so a
    probe steady over a span has one reading there, or none. The grid
    is in UTC, every ``step`` of elapsed time across a clock change."""
    if step <= timedelta(0):
        raise ValueError("step must be positive")
    # In UTC: two local times in one zone compare, and step, by the wall
    # clock, which skips or repeats an hour at a daylight-saving change.
    rows = sorted((t.astimezone(UTC), v) for t, v in readings)
    out: list[Reading] = []
    i = -1
    t, end = start.astimezone(UTC), end.astimezone(UTC)
    while t <= end:
        while i + 1 < len(rows) and rows[i + 1][0] <= t:
            i += 1
        if i >= 0:
            out.append((t, rows[i][1]))
        t += step
    return out


def busy(*spans: Sequence[Span]) -> list[Span]:
    """``spans`` together, overlapping ones joined, in time order, in
    UTC."""
    out: list[Span] = []
    flat = (
        (a.astimezone(UTC), b.astimezone(UTC))
        for group in spans
        for a, b in group
    )
    for a, b in sorted(flat):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def to_gal(value: float, unit: str | None) -> float:
    """A volume in ``unit`` (gal, L, m³, ft³), in US gallons."""
    u = (unit or "").strip().lower()
    if u in ("gal", "gallons"):
        return value
    if u in ("l", "litres", "liters"):
        return value / _L_PER_GAL
    if u in ("m³", "m3"):
        return value * 1000.0 / _L_PER_GAL
    if u in ("ft³", "ft3"):
        return value * 7.480519480519
    raise ValueError(f"{unit!r} is not a volume unit")


def to_w(value: float, unit: str | None) -> float:
    """A power in ``unit`` (W, kW), in W."""
    u = (unit or "").strip()
    if u == "W":
        return value
    if u == "kW":
        return value * 1000.0
    raise ValueError(f"{unit!r} is not a power unit")


def to_wh(value: float, unit: str | None) -> float:
    """An energy in ``unit`` (Wh, kWh), in Wh."""
    u = (unit or "").strip()
    if u == "Wh":
        return value
    if u == "kWh":
        return value * 1000.0
    raise ValueError(f"{unit!r} is not an energy unit")


def covers_start(series: Sequence[Reading], start: datetime) -> bool:
    """Whether a history ``series`` holds the value in force at
    ``start``: Home Assistant's history opens with it, stamped at
    ``start`` itself, when it has one. A first reading any later says
    nothing of the time before it."""
    return bool(series) and series[0][0] <= start


def demand_spans(
    rows: Sequence[tuple[datetime, str]], start: datetime, end: datetime
) -> tuple[list[Span], list[Span]]:
    """A demand entity's draws from ``start`` to ``end``, from its
    history's rows (``History.states``: each instant and state as
    written, the row in force at ``start`` first): the spans it was
    ``on``, and the spans it said nothing anyone can read, when a draw
    may have gone unseen: ``unavailable``, ``unknown``, or before its
    first row."""
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    on: list[Span] = []
    dark: list[Span] = []
    ordered = sorted((t.astimezone(UTC), v) for t, v in rows)
    if not ordered:
        return [], [(start, end)]
    if ordered[0][0] > start:
        dark.append((start, min(ordered[0][0], end)))
    # Each row holds until the next, the last until ``end``.
    until = [t for t, _ in ordered[1:]] + [end]
    for (t, state), nxt in zip(ordered, until, strict=True):
        a, b = max(t, start), min(nxt, end)
        if b <= a:
            continue
        state = state.strip().lower()
        if state == "on":
            on.append((a, b))
        elif state != "off":
            dark.append((a, b))
    return busy(on), busy(dark)


def percent(value: float, unit: str | None) -> float:
    """A relative humidity in ``unit`` (%), checked to lie in 0-100."""
    if (unit or "").strip() != "%":
        raise ValueError(f"{unit!r} is not a relative humidity unit")
    if not 0.0 <= value <= 100.0:
        raise ValueError(f"{value} is not a relative humidity")
    return value


def fresh(state: State, now: datetime, max_age: timedelta = FRESH) -> bool:
    """Whether ``state`` holds a value reported within ``max_age`` of
    ``now``."""
    return state.value is not None and now - state.at <= max_age


def pump_runs(
    speed: Sequence[Reading],
    start: datetime,
    end: datetime,
    *,
    on_rpm: float = PUMP_ON_RPM,
    stale: timedelta | None = None,
) -> list[Span] | None:
    """The spans the pump ran from ``start`` to ``end``, from its speed
    (the reading in force at ``start`` first, as a history gives it): at
    or above ``on_rpm`` is running, below is stopped. Each speed holds
    until the next, as a history of changes writes them; with ``stale``
    (``PUMP_STALE`` for a sampled speed), a run silent for longer ended
    ``stale`` after its last reading. The pump's outages are the
    caller's. None (unknown, not idle) when there is no reading at all.
    Instants are read as UTC, so a silence holds across a change of
    clocks."""
    rows = sorted((t.astimezone(UTC), v) for t, v in speed)
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if not rows:
        return None
    runs: list[Span] = []
    for (at, rpm), nxt in zip(rows, [*rows[1:], None], strict=True):
        if rpm < on_rpm:
            continue
        a = max(at, start)
        b = end if nxt is None else nxt[0]
        if stale is not None:
            b = min(b, at + stale)
        b = min(b, end)
        if b > a:
            if runs and runs[-1][1] >= a:
                runs[-1] = (runs[-1][0], b)
            else:
                runs.append((a, b))
    return runs


# ── the client ──────────────────────────────────────────────────────


class HomeAssistantClient:
    """Home Assistant's REST API. Use it as an async context
    manager, or pass a ``session`` the caller owns."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        session: Any = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.url = url.rstrip("/")
        self._token = token
        self._session = session
        self._owned = session is None
        self.timeout = timeout

    async def __aenter__(self) -> HomeAssistantClient:
        if self._session is None:
            import aiohttp

            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owned and self._session is not None:
            await self._session.close()
            self._session = None

    async def _json(self, method: str, path: str, **kw: Any) -> Any:
        import aiohttp

        if self._session is None:
            raise HomeAssistantError("the client is not open")
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            # No redirects: the API needs none, and following one would
            # carry the token and put it in the error's request details.
            async with self._session.request(
                method,
                self.url + path,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                allow_redirects=False,
                **kw,
            ) as response:
                if response.status != 200:
                    # Scrubbed whole, then cut: cut first, a token across
                    # the cut would keep its prefix.
                    body = self._scrub(await response.text())[:200]
                    raise HomeAssistantError(
                        f"{method} {path}: HTTP {response.status} {body}"
                    )
                try:
                    return await response.json()
                except aiohttp.ContentTypeError, ValueError:
                    raise HomeAssistantError(
                        f"{method} {path}: the answer is not JSON"
                    ) from None
        except (aiohttp.ClientError, TimeoutError) as e:
            # The type alone: an exception's repr can carry the request's
            # headers, and so the token.
            raise HomeAssistantError(
                f"{method} {path}: {type(e).__name__}"
            ) from None

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, "<token>") if self._token else text

    async def state(self, entity: str) -> State:
        """``entity``'s value now."""
        return parse_state(await self._json("GET", f"/api/states/{entity}"))

    async def history(
        self, entities: Iterable[str], start: datetime, end: datetime
    ) -> dict[str, list[Reading]]:
        """Each of ``entities``' changes from ``start`` to ``end``. The
        first reading is the value in force at ``start``."""
        return (await self.read_history(entities, start, end)).readings

    async def read_history(
        self, entities: Iterable[str], start: datetime, end: datetime
    ) -> History:
        """``history``, with the spans each entity was unavailable."""
        names = sorted(set(entities))
        if not names:
            return History({}, {})
        doc = await self._json(
            "GET",
            f"/api/history/period/{start.astimezone(UTC).isoformat()}",
            params={
                "filter_entity_id": ",".join(names),
                "end_time": end.astimezone(UTC).isoformat(),
                # Full rows, every change: a minimal row carries only
                # ``last_changed``, which an attribute-only update
                # leaves behind.
                # With attributes: each row's unit, which can change.
                "significant_changes_only": "0",
            },
        )
        outages = parse_outages(doc, end)
        units = parse_units(doc)
        states = parse_states(doc)
        return History(
            history_for(doc, names),
            {n: outages.get(n, []) for n in names},
            {n: units.get(n, []) for n in names},
            {n: states.get(n, []) for n in names},
        )

    async def forecast(self, entity: str) -> tuple[list[Reading], str | None]:
        """``entity``'s hourly forecast: each hour's temperature, and the
        unit when the answer gives one. A service call that reads, and
        changes nothing."""
        doc = await self._json(
            "POST",
            "/api/services/weather/get_forecasts?return_response",
            json={"entity_id": entity, "type": "hourly"},
        )
        hours, unit = parse_forecast(doc, entity)
        if unit is None:
            unit = (await self._attributes(entity)).get("temperature_unit")
        return hours, unit if isinstance(unit, str) else None

    async def outdoor_history(
        self, entity: str, start: datetime, end: datetime
    ) -> list[Reading]:
        """A weather entity's outdoor air from ``start`` to ``end``, °F,
        each reading from the unit it was recorded in
        (``parse_outdoor_history``), the entity's own unit where a row
        names none. A reading in no unit ``to_f`` reads is left out."""
        doc = await self._json(
            "GET",
            f"/api/history/period/{start.astimezone(UTC).isoformat()}",
            params={
                "filter_entity_id": entity,
                "end_time": end.astimezone(UTC).isoformat(),
                # Every row, with its attributes: the temperature is one.
                "significant_changes_only": "0",
            },
        )
        rows = parse_outdoor_history(doc, entity)
        today: str | None = None
        if any(u is None for _, _, u in rows):
            u = (await self._attributes(entity)).get("temperature_unit")
            today = u if isinstance(u, str) else None
        out: list[Reading] = []
        for t, v, u in rows:
            try:
                out.append((t, to_f(v, u or today)))
            except ValueError:
                continue
        return out

    async def _attributes(self, entity: str) -> Mapping[str, Any]:
        doc = await self._json("GET", f"/api/states/{entity}")
        attributes = doc.get("attributes") if isinstance(doc, dict) else None
        return (
            cast(Mapping[str, Any], attributes)
            if isinstance(attributes, Mapping)
            else {}
        )


def known_runs(
    history: History,
    pump: str,
    unit: str | None,
    since: datetime,
    now: datetime,
) -> tuple[list[Span] | None, list[Span], str | None]:
    """The pump's runs since ``since`` from its speed in ``history``
    (``pump_runs``), the span before its first reading when that is
    after ``since`` (unknown: it may have run then), and why the runs
    are unknown altogether (None for them): no speed reading at all, or
    one in no unit this reads."""
    readings = history.readings.get(pump, [])
    if not readings:
        return None, [], "no speed reading"
    unknown: list[Span] = []
    # Before its first row, a reading or an outage (which the caller
    # takes as a run), nothing is known of the pump.
    heard = [
        *(t for t, _ in readings),
        *(a for a, _ in history.outages.get(pump, [])),
    ]
    first = min(t.astimezone(UTC) for t in heard)
    if not covers_start(readings, since) and first > since:
        unknown = [(since, min(first, now))]
    try:
        speed, unread = history.converted(pump, unit, to_rpm, now)
    except ValueError as err:
        return None, [], str(err)
    # A reading left out could have been a run: one inside the span
    # leaves the runs unknown.
    inside = [(a, b) for a, b in unread if a < now and b > since]
    if inside:
        return None, [], f"{len(inside)} readings in no speed unit"
    return pump_runs(speed, since, now) or [], unknown, None


def mains_plateau(
    history: History,
    probe: str,
    demand: str,
    pump: str | None,
    *,
    probe_unit: str | None,
    pump_unit: str | None,
    since: datetime,
    now: datetime,
    notes: list[str],
) -> ColdSupply | None:
    """The mains from the inlet ``probe``'s plateaus over the long draws
    since ``since`` (``sim_adapters.cold_supply_f``): the draws are the
    ``demand`` entity's (``demand_spans``), and a draw that overlaps the
    ``pump``'s runs, or the probe's or the pump's outages, is skipped.
    The probe's history is read as the value in force every
    ``PROBE_STEP`` (``held``). None, with ``notes`` saying why, when the
    pump's runs are unknown or no draw gives a plateau. All of it is CPU
    work, for a caller's ``Run``."""
    states = history.states or {}
    readings, unread = history.converted(probe, probe_unit, to_f, now)
    if unread:
        notes.append(
            f"inlet: {len(unread)} readings of {probe} in no unit this "
            "reads left out"
        )
    # Its outages split its draws, so none overlaps a draw.
    draws, _ = demand_spans(states.get(demand, []), since, now)
    runs: list[Span] = []
    if pump is not None:
        known, unknown, why = known_runs(history, pump, pump_unit, since, now)
        if known is None:
            notes.append(f"inlet: the circulation's runs are unknown ({why})")
            return None
        # Before the pump's first reading, a draw may have overlapped a
        # run: skipped, as one that overlaps a run is.
        runs = busy(known, unknown)
    # A draw while the probe or the pump was unavailable may have
    # overlapped a run unseen: the plateau skips it, as it skips one
    # that overlaps a run.
    busy_spans = busy(
        runs,
        unread,
        *(history.outages.get(n, []) for n in (probe, pump) if n),
    )
    # In °F, as read: no unit preference is read here.
    cold = sa.cold_supply_f(
        held(readings, since, now),
        at=now,
        draws=draws,
        circulation=busy_spans,
        window=now - since,
    )
    if cold.t_cold_f is None:
        hours = f"{(now - since).total_seconds() / 3600:g}"
        notes.append(
            f"inlet: no long draw in the last {hours} h to read the mains from"
        )
        return None
    notes.append(f"inlet: the plateau of {cold.draws} long draws")
    return cold


# ── the environment source ──────────────────────────────────────────


def _while_running(
    air: Sequence[Reading],
    compressor: Sequence[tuple[datetime, str]],
    end: datetime,
    unknown: Sequence[Span] = (),
    step: timedelta = timedelta(minutes=10),
) -> tuple[list[Reading], Reading | None]:
    """``air``'s value in force every ``step`` through each of
    ``compressor``'s runs (its ``on`` states) to its end, or ``end`` for
    one still running, where that value was read ``RUN_SETTLE`` or more
    into the run: one read earlier, or while idle, is not the air the
    heater stands in. None inside ``unknown``, when the sensor said
    nothing that was read. The second item is the newest reading those
    samples rest on, at its own instant."""
    # A row that repeats the state (an attribute's update) is not a new
    # run; a change to anything else, ``unavailable`` included, ends one.
    changes: list[tuple[datetime, str]] = []
    for at, state in compressor:
        text = state.strip().lower()
        if not changes or changes[-1][1] != text:
            changes.append((at, text))
    times = [t for t, _ in air]
    out: list[Reading] = []
    runs: list[Span] = []
    for i, (on_at, state) in enumerate(changes):
        if state != "on":
            continue
        stop = changes[i + 1][0] if i + 1 < len(changes) else end
        settled = on_at + RUN_SETTLE
        runs.append((settled, stop))
        t = settled
        while t < stop:
            k = bisect_right(times, t)
            if (
                k
                and times[k - 1] >= settled
                and not any(a <= t < b for a, b in unknown)
            ):
                out.append((t, air[k - 1][1]))
            t += step
    # Off the grid: a reading taken between two samples is newer than
    # either would show.
    newest = next(
        (
            r
            for r in reversed(air)
            if any(a <= r[0] < b for a, b in runs)
            and not any(a <= r[0] < b for a, b in unknown)
        ),
        None,
    )
    return out, newest


async def fit_location_air(
    client: HomeAssistantClient,
    entities: Entities,
    *,
    now: datetime,
    heater: HeaterEntities | None = None,
    run: Run = inline,
) -> tuple[FittedLocationAir | None, list[str]]:
    """The ``location_air`` model ``HomeAssistantEnvironment`` fits
    where it is given none, and notes on what it rests on: the last
    ``LOCATION_AIR_WINDOW`` of the air entity's readings, or without one
    the heater's own air reading while its compressor runs (``heater``'s
    ``ambient`` and ``compressor``), against ``entities.weather``'s
    outdoor air. With an air entity that can't be read or gives no fit,
    the heater's own reading is tried. None, and a note why, without
    enough history or for a loose fit. A caller that reads the
    environment often fits on its own cadence and passes the fit on as
    ``fitted_air``. The arithmetic
    (the samples, the fit) goes through ``run``."""
    notes: list[str] = []
    weather = entities.weather
    if weather is None:
        notes.append("air: no weather entity to fit the air to")
        return None, notes
    at = now.astimezone(UTC)
    fitted = await _try_fit(client, entities, heater, weather, at, notes, run)
    if (
        fitted is None
        and entities.air is not None
        and heater is not None
        and heater.ambient is not None
        and heater.compressor is not None
    ):
        # The air entity gave no fit: the heater's own air may.
        notes.append("air: fitting to the heater's own air reading instead")
        fitted = await _try_fit(
            client, replace(entities, air=None), heater, weather, at, notes, run
        )
    return fitted, notes


async def _try_fit(
    client: HomeAssistantClient,
    entities: Entities,
    heater: HeaterEntities | None,
    weather: str,
    now: datetime,
    notes: list[str],
    run: Run,
) -> FittedLocationAir | None:
    try:
        return await _fit(client, entities, heater, weather, now, notes, run)
    except (HomeAssistantError, ValueError) as e:
        notes.append(f"air: not read ({e})")
        return None


async def _fit(
    client: HomeAssistantClient,
    entities: Entities,
    heater: HeaterEntities | None,
    weather: str,
    now: datetime,
    notes: list[str],
    run: Run,
) -> FittedLocationAir | None:
    since = now - LOCATION_AIR_WINDOW
    air = await _air_readings(client, entities, heater, since, now, notes, run)
    if air is None:
        return None
    readings, what = air
    if not readings:
        notes.append(f"air: no readings of {what} to fit to")
        return None
    if not _spans_a_day(readings, what, "", notes):
        return None
    # From before the first reading by the longest lag a fit tries.
    outdoor = await client.outdoor_history(weather, since - _MAX_LAG, now)
    if not outdoor:
        notes.append(f"air: no outdoor air recorded for {weather}")
        return None
    return cast(
        "FittedLocationAir | None",
        await run(lambda: _fit_readings(readings, outdoor, what, notes)),
    )


#: The longest lag a fit tries.
_MAX_LAG = timedelta(hours=max(FIT_LAGS_H))


def _fit_readings(
    readings: Sequence[Reading],
    outdoor: Sequence[Reading],
    what: str,
    notes: list[str],
) -> FittedLocationAir | None:
    """The fit on ``readings`` against ``outdoor``, or None (and a note):
    the CPU work of ``fit_location_air``."""
    # Only readings the outdoor history covers at every lag tried:
    # past its ends, the model holds the outdoor air flat.
    first, last = outdoor[0][0] + _MAX_LAG, outdoor[-1][0]
    readings = [(t, v) for t, v in readings if first <= t <= last]
    if not readings:
        notes.append(
            f"air: no readings of {what} that the outdoor history covers"
        )
        return None
    if not _spans_a_day(
        readings, what, " that the outdoor history covers", notes
    ):
        return None
    if len({v for _, v in readings}) < 2:
        notes.append(f"air: {what} held one value, so nothing to fit to")
        return None
    fitted = fit_air(readings, outdoor)
    days = LOCATION_AIR_WINDOW.total_seconds() / 86400
    # A steady air has no r (NaN): no fit either.
    if not fitted.r >= LOCATION_AIR_MIN_R:
        notes.append(
            f"air: {what} follows the outdoor air too loosely to "
            f"project it (r {fitted.r:.2f}, under {LOCATION_AIR_MIN_R})"
        )
        return None
    notes.append(
        f"air: the outdoor air fitted to {what} over the last {days:g} "
        f"days ({_fit_terms(fitted)})"
    )
    return fitted


def _fit_terms(fitted: FittedLocationAir) -> str:
    return (
        f"r {fitted.r:.2f}, {fitted.model.lag.total_seconds() / 3600:g} h late"
    )


def _spans_a_day(
    readings: Sequence[Reading], what: str, covered: str, notes: list[str]
) -> bool:
    """Whether ``readings`` span ``LOCATION_AIR_MIN_SPAN``; a note when
    they don't."""
    span = readings[-1][0] - readings[0][0]
    if span >= LOCATION_AIR_MIN_SPAN:
        return True
    notes.append(
        f"air: {span.total_seconds() / 3600:.0f} h of {what}{covered}, "
        f"under the {LOCATION_AIR_MIN_SPAN.total_seconds() / 3600:g} h "
        "a fit needs"
    )
    return False


async def _air_readings(
    client: HomeAssistantClient,
    entities: Entities,
    heater: HeaterEntities | None,
    since: datetime,
    now: datetime,
    notes: list[str],
    run: Run = inline,
) -> tuple[list[Reading], str] | None:
    """The air where the heater stands since ``since``, °F, and what it
    was read from: the air entity, or the heater's own reading every 10
    minutes while its compressor runs (``_heater_air``). None (and a
    note) when neither is recorded."""
    if entities.air is not None:
        got = await client.read_history([entities.air], since, now)
        unit = (await client.state(entities.air)).unit
        air = entities.air
        readings = cast(
            list[Reading],
            await run(lambda: got.converted(air, unit, to_f, now)[0]),
        )
        return readings, "the air beside the heater"
    heard = await _heater_air(client, heater, since, now, notes, run)
    if heard is None:
        notes.append(
            "air: no air reading to fit the outdoor air to (an air "
            "entity, or the heater's own air and compressor)"
        )
        return None
    return heard[0], "the heater's own air reading"


async def _heater_air(
    client: HomeAssistantClient,
    heater: HeaterEntities | None,
    since: datetime,
    now: datetime,
    notes: list[str],
    run: Run = inline,
) -> tuple[list[Reading], Reading | None] | None:
    """The heater's own air reading since ``since`` while its compressor
    ran (``_while_running``), and the newest reading those samples rest
    on. None when ``heater`` has no ambient or compressor, or (and a
    note) the compressor's states are not in the history."""
    if heater is None or heater.ambient is None or heater.compressor is None:
        return None
    got = await client.read_history(
        [heater.ambient, heater.compressor], since, now
    )
    if got.states is None:
        notes.append(
            f"air: {heater.compressor} not read (no states in the history)"
        )
        return None
    unit = (await client.state(heater.ambient)).unit
    ambient_id, compressor = (
        heater.ambient,
        got.states.get(heater.compressor, []),
    )

    def work() -> tuple[list[Reading], Reading | None]:
        ambient, unread = got.converted(ambient_id, unit, to_f, now)
        return _while_running(
            ambient,
            compressor,
            now,
            busy(unread, got.outages.get(ambient_id, [])),
        )

    return cast("tuple[list[Reading], Reading | None]", await run(work))


class HomeAssistantEnvironment:
    """An ``EnvironmentSource``: the air, its humidity and the inlet from
    Home Assistant, over ``start`` to ``until``, as of ``now`` (the
    driver's clock). ``notes`` say what each part rests on, or why it
    was left to the default, once ``read`` has run.

    With a weather entity and neither a ``location_air`` model nor a
    ``fitted_air``, ``read`` fits one (``fit_location_air``) and keeps
    it as ``fitted_air``. With a model and no fresh reading of the air
    beside the heater, the projection is anchored to ``heater``'s own
    air reading from its last hour, while its compressor ran, if
    there is one. The CPU work (the fit, the samples of the heater's
    air, the inlet's plateau) goes through ``run``."""

    def __init__(
        self,
        client: HomeAssistantClient,
        entities: Entities,
        *,
        start: datetime,
        until: datetime,
        now: datetime | None = None,
        location_air: LocationAirModel | None = None,
        heater: HeaterEntities | None = None,
        fitted_air: FittedLocationAir | None = None,
        run: Run = inline,
    ) -> None:
        self.client = client
        self.entities = entities
        self.start = start
        self.until = until
        self.now = start if now is None else now
        self.location_air = location_air
        self.heater = heater
        self.run = run
        self.notes: list[str] = []
        #: The fit the air is projected through: the one given, or the
        #: one ``read`` fitted where no model was given; None when a
        #: model was given, or none could be fitted.
        self.fitted_air: FittedLocationAir | None = fitted_air
        self._fit_notes: list[str] | None = (
            None
            if fitted_air is None
            else [f"air: the fitted model given ({_fit_terms(fitted_air)})"]
        )

    async def read(self) -> Environment:
        """The environment; a part that cannot be read is left to the
        simulator's default (the air to the heater's own reading, in
        ``sim_live.compose``)."""
        self.notes = []
        kw: dict[str, Any] = {
            "ambient_f": await self._air(),
        }
        humidity = await self._humidity()
        if humidity is not None:
            kw["humidity"] = humidity
        inlet = await self._inlet()
        if inlet is not None:
            kw["inlet_f"] = inlet
        return Environment(**kw)

    async def _guard(
        self, what: str, read: Callable[[], Awaitable[Any]], default: Any
    ) -> Any:
        try:
            return await read()
        except (HomeAssistantError, ValueError) as e:
            self.notes.append(f"{what}: not read ({e})")
            return default

    async def _fresh_state(self, what: str, entity: str) -> State | None:
        state: State | None = await self._guard(
            what, lambda: self.client.state(entity), None
        )
        if state is None:
            return None
        if not fresh(state, self.now):
            age = (
                "no value"
                if state.value is None
                else (
                    f"{(self.now - state.at).total_seconds() / 3600:.1f} h old"
                )
            )
            self.notes.append(f"{what}: {entity} is stale ({age})")
            return None
        return state

    async def _air(self) -> float | tuple[Reading, ...]:
        e = self.entities
        weather = e.weather
        held: Reading | None = None
        if e.air is not None:
            state = await self._fresh_state("air", e.air)
            if state is not None and state.value is not None:
                try:
                    held = (state.at, to_f(state.value, state.unit))
                except ValueError as err:
                    self.notes.append(f"air: {err}")
        model = self.location_air
        if weather is not None and model is None:
            fitted = await self._fit_air()
            if fitted is not None:
                model = fitted.model
        anchor = held
        if weather is not None and model is not None and anchor is None:
            anchor = await self._heater_anchor()
        if weather is not None and model is not None:
            hours = await self._guard(
                "outdoor forecast",
                lambda: self.client.forecast(weather),
                None,
            )
            if hours is not None:
                readings, unit = hours
                try:
                    outdoor = [(t, to_f(v, unit)) for t, v in readings]
                except ValueError as err:
                    outdoor = []
                    self.notes.append(f"outdoor forecast: {err}")
                air = project_air(
                    model,
                    outdoor,
                    self.start,
                    self.until,
                    anchor=anchor,
                )
                if air:
                    self.notes.append(
                        "air: projected from the outdoor forecast, "
                        + (
                            "unanchored"
                            if anchor is None
                            else "anchored to the reading beside the heater"
                            if anchor is held
                            else "anchored to the heater's own reading"
                        )
                    )
                    return air
        if held is not None:
            self.notes.append("air: the reading beside the heater, held")
            return held[1]
        return math.nan

    async def _fit_air(self) -> FittedLocationAir | None:
        """``fitted_air``, fitted (``fit_location_air``) on the first
        ``read`` where it was not given; a later ``read`` reuses it and
        repeats its notes."""
        if self._fit_notes is None:
            self.fitted_air, self._fit_notes = await fit_location_air(
                self.client,
                self.entities,
                now=self.now,
                heater=self.heater,
                run=self.run,
            )
        self.notes.extend(self._fit_notes)
        return self.fitted_air

    async def _heater_anchor(self) -> Reading | None:
        """The heater's newest air reading while its compressor ran, at
        its own instant, if under ``FRESH`` old; None without one."""
        now = self.now.astimezone(UTC)
        notes: list[str] = []
        heard = await self._guard(
            "air",
            # From before the cut by the settling time: a run already on
            # at the cut then shows where it started, or settled.
            lambda: _heater_air(
                self.client,
                self.heater,
                now - FRESH - RUN_SETTLE,
                now,
                notes,
                self.run,
            ),
            None,
        )
        self.notes.extend(notes)
        if heard is None:
            return None
        newest = cast("Reading | None", heard[1])
        if newest is None or now - newest[0] > FRESH:
            return None
        return newest

    async def _humidity(self) -> float | None:
        e = self.entities
        if e.humidity is None:
            return None
        state = await self._fresh_state("humidity", e.humidity)
        if state is None or state.value is None:
            return None
        try:
            return percent(state.value, state.unit)
        except ValueError as err:
            self.notes.append(f"humidity: {err}")
            return None

    async def _inlet(self) -> float | None:
        e = self.entities
        probe_id, demand_id, pump_id = e.inlet, e.demand, e.circulation_speed
        if probe_id is None:
            return None
        if demand_id is None:
            self.notes.append(
                "inlet: needs the demand entity to find long draws"
            )
            return None
        # In UTC: a lookback across a clock change is the elapsed span,
        # not the wall time's.
        now = self.now.astimezone(UTC)
        since = now - INLET_LOOKBACK
        names = [n for n in (probe_id, demand_id, pump_id) if n]

        async def read() -> float | None:
            got = await self.client.read_history(names, since, now)
            if got.states is None:
                self.notes.append(
                    f"inlet: {demand_id} not read (no states in the history)"
                )
                return None
            probe_unit = (await self.client.state(probe_id)).unit
            pump_unit: str | None = None
            if pump_id is not None:
                try:
                    pump_unit = (await self.client.state(pump_id)).unit
                except HomeAssistantError as err:
                    self.notes.append(
                        f"inlet: the circulation's runs are unknown ({err})"
                    )
                    return None
            notes: list[str] = []
            # The held grid and the plateau are the CPU work, through
            # ``run``.
            cold = cast(
                "ColdSupply | None",
                await self.run(
                    lambda: mains_plateau(
                        got,
                        probe_id,
                        demand_id,
                        pump_id,
                        probe_unit=probe_unit,
                        pump_unit=pump_unit,
                        since=since,
                        now=now,
                        notes=notes,
                    )
                ),
            )
            self.notes.extend(notes)
            return None if cold is None else cold.t_cold_f

        return cast("float | None", await self._guard("inlet", read, None))


# ── over a recorded history, for the calibration ────────────────────


@dataclass(frozen=True)
class RecordInputs:
    """What Home Assistant recorded over a heater's history: the air
    beside it and that air's humidity (°F, %), the spans the household
    drew hot water (the demand entity's), and the circulation's runs.
    None for a part it does not record, or could not be read (``notes``
    say which)."""

    air: list[Reading] | None
    humidity: list[Reading] | None
    drawing: list[Span] | None
    circulating: list[Span] | None
    notes: tuple[str, ...] = ()
    #: The spans the air's and the humidity's entities were unavailable:
    #: not observed, whatever the readings either side say.
    air_outages: tuple[Span, ...] = ()
    humidity_outages: tuple[Span, ...] = ()


async def record_inputs(
    client: HomeAssistantClient,
    entities: Entities,
    start: datetime,
    end: datetime,
) -> RecordInputs:
    """The air, its humidity, the draws and the circulation's runs from
    ``start`` to ``end``. A series that starts after ``start`` covers
    only its own span; the notes say how much."""
    notes: list[str] = []
    e = entities
    names = [n for n in (e.air, e.humidity, e.demand, e.circulation_speed) if n]
    if not names:
        return RecordInputs(None, None, None, None, ())
    try:
        got = await client.read_history(names, start, end)
    except HomeAssistantError as err:
        return RecordInputs(None, None, None, None, (f"not read ({err})",))
    units: dict[str, str | None] = {}
    for n in (e.air, e.humidity, e.circulation_speed):
        if n:
            try:
                units[n] = (await client.state(n)).unit
            except HomeAssistantError as err:
                notes.append(f"{n}: unit not read ({err})")

    def covered(what: str, series: list[Reading]) -> list[Reading] | None:
        if not series:
            notes.append(f"{what}: no history over the record")
            return None
        if not covers_start(series, start):
            notes.append(
                f"{what}: history covers only from {series[0][0].isoformat()}"
            )
        return series

    def whole(what: str, series: list[Reading]) -> bool:
        # Spans read as "nothing happened" outside what was recorded,
        # and the draws' or pump's spans replace the heater's own flag:
        # a part history is no history.
        if covers_start(series, start):
            return True
        since = f"from {series[0][0].isoformat()}" if series else "none"
        notes.append(
            f"{what}: history covers only part of the record ({since}); "
            "the heater's own in-use flag stands in"
        )
        return False

    def outage(what: str, spans: list[Span]) -> None:
        if spans:
            hours = sum((b - a).total_seconds() for a, b in spans) / 3600
            notes.append(
                f"{what}: unavailable {len(spans)} times ({hours:.1f} h), "
                "counted as busy"
            )

    unread: dict[str, list[Span]] = {}

    def read_in(
        what: str, entity: str, to: Callable[[float, str | None], float]
    ) -> list[Reading]:
        rows, spans = got.converted(entity, units[entity], to, end)
        if spans:
            notes.append(
                f"{what}: {len(spans)} readings in no unit this reads, or "
                "outside 0-100 for a humidity, left out and unobserved"
            )
            unread.setdefault(what, []).extend(spans)
        return rows

    air = humidity = None
    try:
        if e.air and e.air in units:
            air = covered("air", read_in("air", e.air, to_f))
    except ValueError as err:
        notes.append(f"air: {err}")
    if e.humidity and e.humidity in units:
        try:
            humidity = covered(
                "humidity", read_in("humidity", e.humidity, percent)
            )
        except ValueError as err:
            notes.append(f"humidity: {err}")
    drawing = None
    if e.demand:
        rows = None if got.states is None else got.states.get(e.demand, [])
        if rows is None:
            notes.append("demand: not read (no states in the history)")
        elif whole("demand", [(t, 0.0) for t, _ in rows]):
            on, dark = demand_spans(rows, start, end)
            # While it was unavailable, a draw may have gone unseen.
            drawing = busy(on, dark)
            outage("demand", dark)
    circulating = None
    pump_id = e.circulation_speed
    if pump_id and pump_id in units:
        try:
            rpm, bad = got.converted(pump_id, units[pump_id], to_rpm, end)
            if bad:
                # A reading left out could have been a run.
                raise ValueError(f"{len(bad)} readings in no speed unit")
            if whole("circulation", rpm):
                down = got.outages.get(pump_id, [])
                runs = pump_runs(rpm, start, end)
                # While the pump was unavailable, it may have run.
                circulating = None if runs is None else busy(runs, down)
                outage("circulation", down)
        except ValueError as err:
            notes.append(f"circulation: {err}")
    air_down = (
        tuple(busy(got.outages.get(e.air, []), unread.get("air", [])))
        if air is not None and e.air
        else ()
    )
    rh_down = (
        tuple(busy(got.outages.get(e.humidity, []), unread.get("humidity", [])))
        if humidity is not None and e.humidity
        else ()
    )
    for what, spans in (("air", air_down), ("humidity", rh_down)):
        if spans:
            hours = sum((b - a).total_seconds() for a, b in spans) / 3600
            notes.append(
                f"{what}: unavailable {len(spans)} times ({hours:.1f} h), "
                "left unobserved"
            )
    return RecordInputs(
        air,
        humidity,
        drawing,
        circulating,
        tuple(notes),
        air_outages=air_down,
        humidity_outages=rh_down,
    )


# ── the heater's own history, for its calibration ───────────────────


@dataclass(frozen=True)
class HeaterEntities:
    """The heater's own entities in Home Assistant, by the value each
    holds (``sim_adapters.ChangeRows``); None for one the installation
    does not record."""

    #: An entity that changes on every status the heater answers with,
    #: such as the integration's last response time: when the heater was
    #: heard from.
    heard: str
    upper: str
    lower: str
    compressor: str | None = None
    upper_element: str | None = None
    lower_element: str | None = None
    #: The heat source, by ``HeatSource`` name.
    heat_source: str | None = None
    dhw_in_use: str | None = None
    #: The lower probe's heat-pump stop threshold.
    target: str | None = None
    #: The operation mode, by ``CurrentOperationMode`` name.
    operation_mode: str | None = None
    anti_legionella: str | None = None
    #: The error code, by ``ErrorCode`` name.
    error_code: str | None = None
    power: str | None = None
    energy_to_setpoint: str | None = None
    #: The heater's own air reading.
    ambient: str | None = None


@dataclass(frozen=True)
class HeaterHistory:
    """A heater's history from Home Assistant, as
    ``sim_calibrate.calibrate_changes`` and
    ``sim_adapters.book_from_changes`` take it: its values' changes, the
    instants it was heard from, and what the reading noted."""

    rows: sa.ChangeRows
    observed: list[datetime]
    notes: tuple[str, ...] = ()

    def extended(self, newer: HeaterHistory) -> HeaterHistory:
        """This history with a later read's (``ChangeRows.extended``),
        the instants heard from joined, and the later read's notes. Read
        only from where the last read ended, extend, and trim with
        ``since``."""
        return HeaterHistory(
            self.rows.extended(newer.rows),
            sorted(
                {t.astimezone(UTC) for t in (*self.observed, *newer.observed)}
            ),
            newer.notes,
        )

    def since(self, start: datetime) -> HeaterHistory:
        """This history from ``start`` (``ChangeRows.since``), the
        instants heard from at or after it."""
        start = start.astimezone(UTC)
        return HeaterHistory(
            self.rows.since(start),
            [t for t in self.observed if t.astimezone(UTC) >= start],
            self.notes,
        )


#: How much history ``read_heater_history`` asks for at once.
HISTORY_WINDOW = timedelta(days=1)

#: A role's value from an entity's state, and its unit: a number through
#: a unit converter, ``on``/``off``, or an enum's name.
_Read = Callable[[float, str | None], float] | type[enum.Enum] | None


def _missing(state: str, read: _Read) -> bool:
    """Whether ``state`` is Home Assistant's for a value it does not
    have. An enum's own ``UNKNOWN`` is a value."""
    text = state.strip()
    is_name = (
        isinstance(read, type)
        and issubclass(read, enum.Enum)
        and text in read.__members__
    )
    return not is_name and text.lower() in _NO_VALUE


def _value(state: str, read: _Read, unit: str | None) -> Any:
    """``state`` as ``read`` takes it, a number from ``unit``; None when
    it is not one."""
    text = state.strip()
    if read is None:
        return {"on": True, "off": False}.get(text.lower())
    if isinstance(read, type) and issubclass(read, enum.Enum):
        try:
            return read[text]
        except KeyError:
            number = _number(text)
            try:
                return None if number is None else read(int(number))
            except ValueError:
                return None
    number = _number(text)
    if number is None:
        return None
    convert = cast(Callable[[float, str | None], float], read)
    try:
        return convert(number, unit)
    except ValueError:
        return None


#: The heater's roles that say it heats: a window without one of them is
#: unobserved.
_HEATING = frozenset(
    ("compressor_on", "upper_element_on", "lower_element_on", "heat_source")
)


async def read_heater_history(
    client: HomeAssistantClient,
    entities: HeaterEntities,
    start: datetime,
    end: datetime,
    *,
    window: timedelta = HISTORY_WINDOW,
) -> HeaterHistory:
    """The heater's history from ``start`` to ``end``, read a ``window``
    at a time so that no more than a window's rows are held as Home
    Assistant gives them.

    Each number is taken from the unit it was recorded in. A state
    ``unavailable`` or ``unknown`` is an outage, and an outage of any
    entity leaves the heater unobserved over it: the integration's
    entities go unavailable together. So does a window that has nothing
    of a heating flag (the compressor, an element, the heat source).
    Raises ``HomeAssistantError`` when a probe cannot be read, or the
    client gives no states (``History.states``)."""
    from nwp500.enums import CurrentOperationMode, ErrorCode, HeatSource

    if window <= timedelta(0):
        raise ValueError(f"window {window} is not a positive span")
    e = entities
    roles: dict[str, tuple[str, _Read]] = {
        name: (entity, read)
        for name, entity, read in (
            ("upper_f", e.upper, to_f),
            ("lower_f", e.lower, to_f),
            ("compressor_on", e.compressor, None),
            ("upper_element_on", e.upper_element, None),
            ("lower_element_on", e.lower_element, None),
            ("heat_source", e.heat_source, HeatSource),
            ("dhw_in_use", e.dhw_in_use, None),
            ("target_f", e.target, to_f),
            ("operation_mode", e.operation_mode, CurrentOperationMode),
            ("anti_legionella", e.anti_legionella, None),
            ("error_code", e.error_code, ErrorCode),
            ("power_w", e.power, to_w),
            ("energy_to_setpoint_wh", e.energy_to_setpoint, to_wh),
            ("heater_air_f", e.ambient, to_f),
        )
        if entity
    }
    notes: list[str] = []
    if not e.anti_legionella:
        notes.append(
            "anti_legionella: not recorded; an anti-legionella cycle is not "
            "excluded from the fits"
        )
    units: dict[str, str | None] = {}
    for name, (entity, read) in list(roles.items()):
        if read is None or isinstance(read, type):
            continue
        try:
            units[name] = (await client.state(entity)).unit
            read(50.0, units[name])
        except (HomeAssistantError, ValueError) as err:
            if name in ("upper_f", "lower_f"):
                raise HomeAssistantError(f"{entity}: {err}") from None
            notes.append(f"{name}: not read ({err})")
            del roles[name]
    changes: dict[str, list[tuple[datetime, Any]]] = {n: [] for n in roles}
    unread: dict[str, int] = {}
    blank: dict[str, list[Span]] = {}
    down: list[Span] = []
    heard: list[datetime] = []
    names = sorted({e.heard, *(entity for entity, _ in roles.values())})
    a = start
    while a < end:
        b = min(a + window, end)
        got = await client.read_history(names, a, b)
        if got.states is None:
            raise HomeAssistantError(
                "the client's history carries no states (History.states)"
            )
        was: datetime | None = None
        for t, state in got.states.get(e.heard, []):
            if _missing(state, None):
                was = t if was is None else was
                continue
            if was is not None:
                down.append((was, t))
                was = None
            # The window opens with the state in force at its start,
            # which is no response inside it.
            if t > a:
                heard.append(t)
        if was is not None:
            down.append((was, b))
        for name, (entity, read) in roles.items():
            series = changes[name]
            if name in _HEATING and not got.states.get(entity):
                # A window opens with the state in force: nothing is no
                # read, and a flag held from before would credit heating
                # across it.
                blank.setdefault(name, []).append((a, b))
            was = None
            # The unit each number was recorded in, where the history
            # says; today's where it does not.
            recorded = dict(
                zip(
                    (t for t, _ in got.readings.get(entity, [])),
                    (got.units or {}).get(entity, []),
                    strict=False,
                )
            )
            for t, state in got.states.get(entity, []):
                if _missing(state, read):
                    was = t if was is None else was
                    continue
                if was is not None:
                    down.append((was, t))
                    was = None
                unit = recorded[t] if t in recorded else units.get(name)
                value = _value(state, read, unit)
                if value is None:
                    # Counted once, not again as the next window opens.
                    if t > a or a == start:
                        unread[name] = unread.get(name, 0) + 1
                    continue
                # A window's first row repeats the last one before it, and
                # a value that comes back unchanged is no change.
                if not series or (t > series[-1][0] and value != series[-1][1]):
                    series.append((t, value))
            if was is not None:
                down.append((was, b))
        a = b
    for name, series in changes.items():
        if not series:
            notes.append(f"{name}: no history over the record")
        elif series[0][0] > start:
            notes.append(
                f"{name}: history covers only from {series[0][0].isoformat()}"
            )
    for name, count in unread.items():
        notes.append(f"{name}: {count} states this does not read, left out")
    for name, spans in blank.items():
        if not changes[name]:
            # No history over the whole record: not recorded at all, so
            # left out (``no history over the record``), not unobserved.
            continue
        down.extend(spans)
        notes.append(
            f"{name}: nothing read in {len(spans)} windows, left unobserved"
        )
    outages = busy(down)
    if outages:
        hours = sum((b - a).total_seconds() for a, b in outages) / 3600
        notes.append(
            f"heater: unavailable {len(outages)} times ({hours:.1f} h), "
            "left unobserved"
        )
    if not changes.get("upper_f") or not changes.get("lower_f"):
        raise HomeAssistantError("the probes have no history over the record")
    rows = sa.ChangeRows(**changes, outages=tuple(outages))
    return HeaterHistory(rows, sorted(set(heard)), tuple(notes))


# ── the heat book, kept current ─────────────────────────────────────

#: How far back ``HomeAssistantBook`` holds the history: the oldest
#: anchor a book reads (``BookParams.history_h``'s default).
BOOK_WINDOW = timedelta(hours=72)


@dataclass(frozen=True)
class BookAnswer:
    """``HomeAssistantBook.book``'s answer: the book (None without one),
    whether its gallons convert at the mains, as ``time_to_ready``'s
    ``inlet_measured`` takes it, and what it rests on."""

    booked: Booked | None
    inlet_measured: bool
    notes: tuple[str, ...]


def _heating_lost(
    held: HeaterHistory, newer: HeaterHistory, start: datetime, end: datetime
) -> HeaterHistory:
    """``newer`` unobserved from ``start`` to ``end`` when it has nothing
    of a heating flag ``held`` has history of: a read opens with the
    value in force, so nothing is no read (``read_heater_history``
    leaves out a flag it has no history of at all), and the flag held
    from before would credit heating across it."""
    lost = [
        name
        for name in _HEATING
        if getattr(held.rows, name) and not getattr(newer.rows, name)
    ]
    if not lost:
        return newer
    rows = replace(newer.rows, outages=(*newer.rows.outages, (start, end)))
    notes = (
        *newer.notes,
        *(f"{name}: nothing read, left unobserved" for name in sorted(lost)),
    )
    return replace(newer, rows=rows, notes=notes)


def _unread_marked(
    got: History, names: Iterable[str], start: datetime, end: datetime
) -> History:
    """``got`` with each of ``names`` it has nothing of (a read opens
    with the value in force, so nothing is no read) unknown from
    ``start`` to ``end``: an outage, and a state ``unknown``, so that a
    value held from an earlier read does not carry across it."""
    missing = [
        n
        for n in names
        if not got.readings.get(n)
        and not got.outages.get(n)
        and not (got.states or {}).get(n)
    ]
    if not missing:
        return got
    outages = dict(got.outages) | {n: [(start, end)] for n in missing}
    states = got.states
    if states is not None:
        states = dict(states) | {n: [(start, "unknown")] for n in missing}
    return replace(got, outages=outages, states=states)


def _without(spans: Sequence[Span], cut: Sequence[Span]) -> list[Span]:
    """``spans`` less what of them is inside ``cut``."""
    out: list[Span] = []
    for span in spans:
        pieces = [span]
        for c, d in cut:
            pieces = [
                (x, y)
                for a, b in pieces
                for x, y in ((a, min(b, c)), (max(a, d), b))
                if y > x
            ]
        out.extend(pieces)
    return out


class HomeAssistantBook:
    """The tank's heat booked (``sim_adapters.book_from_changes``) from
    Home Assistant and kept current: ``read`` reads the history once
    over ``window``, then only what is new since the last read, and
    holds it (``extended``, ``since``); ``book`` books from what it
    holds, with no request.

    ``flow`` is the household's hot water draw flow, the circulation's
    water not in it, in any unit ``to_gpm`` reads. ``flow_volume`` says
    what its gallons count. Delivered at the taps through the mixing
    valve, the default, the book prices a gallon at the valve's delivery
    line (``DrawParams.delivery_intercept_f`` and ``delivery_slope``);
    the tank's own water (a meter or a detector on the heater's hot
    outlet, ``"tank"``), at the upper probe. ``heater`` is the heater's own
    entities. Of ``entities``, ``circulation_speed`` gives the
    circulation's runs, ``inlet`` the inlet the book converts at, and
    with ``demand`` the mains (``mains_plateau``, ``on_the_mains``),
    and ``air`` the air beside the heater; each optional, a book without
    one losing only what it gives. A flow reported late reaches the
    book late: it books what the history holds at ``read``. Across a
    span an entity was unavailable, a restart's say, the book holds its
    value from before: the flow for ``sim_adapters.FLOW_HOLD`` and the
    pump's speed for ``PUMP_STALE``, then none."""

    def __init__(
        self,
        client: HomeAssistantClient,
        heater: HeaterEntities,
        flow: str,
        entities: Entities | None = None,
        *,
        window: timedelta = BOOK_WINDOW,
        flow_volume: FlowVolume = "delivered",
    ) -> None:
        if window <= timedelta(0):
            raise ValueError(f"window {window} is not a positive span")
        self.client = client
        self.heater = heater
        self.flow = flow
        self.flow_volume: FlowVolume = flow_volume
        self.entities = entities or Entities()
        self.window = window
        self._heater_history: HeaterHistory | None = None
        self._history: History | None = None
        self._heater_read: datetime | None = None
        self._heater_tried: datetime | None = None
        self._read: datetime | None = None
        self._tried: datetime | None = None
        self._units: dict[str, str | None] = {}
        self._notes: list[str] = []

    @property
    def _others(self) -> list[str]:
        e = self.entities
        return [
            n
            for n in (self.flow, e.circulation_speed, e.inlet, e.demand, e.air)
            if n
        ]

    async def read(self, now: datetime) -> None:
        """Read the history since the last read (the whole ``window``
        the first time) and hold it, trimmed to ``window``. A read that
        fails is noted, and the next reads again from where it would
        have started."""
        now = now.astimezone(UTC)
        cut = now - self.window
        self._notes = []
        start = (
            cut if self._heater_read is None else max(self._heater_read, cut)
        )
        self._heater_tried = now
        try:
            newer = await read_heater_history(
                self.client, self.heater, start, now
            )
        except (HomeAssistantError, ValueError) as err:
            self._notes.append(f"book: the heater's history not read ({err})")
        else:
            held_ = self._heater_history
            if held_ is not None:
                newer = _heating_lost(held_, newer, start, now)
            whole = newer if held_ is None else held_.extended(newer)
            self._heater_history = whole.since(cut)
            self._heater_read = now
        start = cut if self._read is None else max(self._read, cut)
        self._tried = now
        try:
            got = await self.client.read_history(self._others, start, now)
        except HomeAssistantError as err:
            self._notes.append(f"book: the flow's history not read ({err})")
        else:
            # A read opens with the value in force: with neither a reading
            # nor an outage, the flow is unread, and read again next time.
            if not got.readings.get(self.flow) and not got.outages.get(
                self.flow
            ):
                self._notes.append(f"book: no history of {self.flow} read")
            else:
                got = _unread_marked(got, self._others, start, now)
                had = self._history
                merged = got if had is None else had.extended(got)
                self._history = merged.since(cut)
                self._read = now
        for n in self._others:
            if n == self.entities.demand:
                continue
            try:
                self._units[n] = (await self.client.state(n)).unit
            except HomeAssistantError as err:
                # Without its unit, its readings are left out of the book.
                self._units.pop(n, None)
                self._notes.append(f"book: {n}'s unit not read ({err})")

    def book(self, at: datetime, params: HeaterParams) -> BookAnswer:
        """The book at ``at`` from the history held, with no request:
        CPU work, for an executor. None, and notes why, without the
        heater's or the flow's history, or with no anchor."""
        at = at.astimezone(UTC)
        rows, got = self._heater_history, self._history
        # The last heater read's notes, then this keeper's.
        notes = [*(rows.notes if rows is not None else ()), *self._notes]
        if rows is None or got is None:
            notes.append("book: no history read")
            return BookAnswer(None, False, tuple(notes))
        if self._heater_tried != self._heater_read:
            # Since the last heater read that worked, its flags are
            # unknown: none held from before may credit heating.
            notes.append(
                "book: none past the heater's last read "
                f"({cast(datetime, self._heater_read).isoformat()})"
            )
            return BookAnswer(None, False, tuple(notes))
        since = at - self.window
        e = self.entities
        circulation = params.circulation
        if circulation is not None and circulation.meter_share > 0.0:
            # The flow is the household's draws, the circulation's water
            # not in it: none of it is to be taken off as circulation.
            params = replace(
                params, circulation=replace(circulation, meter_share=0.0)
            )
            notes.append(
                "book: the flow has no circulation in it, so the "
                "circulation's meter_share is taken as 0"
            )
        # After a read that failed, nothing is known past the last that
        # didn't: unknown, not held.
        unseen: list[Span] = []
        failed = self._tried is not None and self._tried != self._read
        if failed and self._read is not None and self._read < at:
            unseen = [(self._read, at)]
            notes.append(f"book: nothing read since {self._read.isoformat()}")
        try:
            flow, unread = got.converted(
                self.flow, self._units.get(self.flow), to_gpm, at
            )
        except ValueError as err:
            notes.append(f"book: {self.flow}: {err}")
            return BookAnswer(None, False, tuple(notes))
        flow_out = busy(unread, got.outages.get(self.flow, []), unseen)
        runs: list[Span] = []
        if e.circulation_speed is not None:
            known, unknown, why = known_runs(
                got,
                e.circulation_speed,
                self._units.get(e.circulation_speed),
                since,
                at,
            )
            if known is None:
                notes.append(
                    f"book: the circulation's runs are unknown ({why}); "
                    "booked with only its outages"
                )
            if unknown:
                notes.append(
                    "book: the circulation's runs are known only from "
                    f"{unknown[-1][1].isoformat()}"
                )
            # Across the pump's outages its speed holds, as a sampled
            # speed does, for PUMP_STALE: a run going in is over by then.
            stale = [
                (a + PUMP_STALE, b)
                for a, b in got.outages.get(e.circulation_speed, [])
                if a + PUMP_STALE < b
            ]
            runs = busy(_without(known or [], stale), unseen)
        inlet: list[Reading] = []
        inlet_out: list[Span] = []
        if e.inlet is not None:
            try:
                inlet, bad = got.converted(
                    e.inlet, self._units.get(e.inlet), to_f, at
                )
                inlet_out = busy(bad, got.outages.get(e.inlet, []), unseen)
            except ValueError as err:
                notes.append(f"book: {e.inlet}: {err}")
        air: list[Reading] = []
        air_out: list[Span] = []
        if e.air is not None:
            try:
                air, bad = got.converted(
                    e.air, self._units.get(e.air), to_f, at
                )
                air_out = busy(bad, got.outages.get(e.air, []), unseen)
            except ValueError as err:
                notes.append(f"book: {e.air}: {err}")
        if runs and params.circulation is None:
            notes.append(
                "book: the circulation's runs priced at one installation's "
                "terms (CirculationParams)"
            )
        try:
            booked = sa.book_from_changes(
                rows.rows,
                rows.observed,
                params,
                at=at,
                flow=flow,
                circulation=runs,
                inlet=inlet,
                air=air,
                flow_outages=flow_out,
                inlet_outages=inlet_out,
                air_outages=air_out,
                flow_volume=self.flow_volume,
            )
        except ValueError as err:
            notes.append(f"book: {err}")
            return BookAnswer(None, False, tuple(notes))
        if not air and rows.rows.heater_air_f:
            # As the book takes it: unheard across its outages and the
            # silences between the instants it was heard.
            heard = sorted(t.astimezone(UTC) for t in rows.observed if t <= at)
            silent = sa.silences(heard, sa.max_gap(heard)) if heard else []
            settled = sa.settled_air(
                sa.compressor_changes(rows.rows),
                rows.rows.heater_air_f,
                until=at,
                unheard=[*silent, *rows.rows.outages],
            )
            notes.append(
                "book: the air is the heater's own reading while its "
                "compressor runs"
                if settled
                else "book: the heater's air not read while its compressor "
                f"ran {sa.HEATER_AIR_SETTLE.total_seconds() / 60:g} "
                f"minutes: the air is the default, {AMBIENT_DEFAULT_F:g} °F"
            )
        if booked is None:
            if any(a <= at <= b for a, b in flow_out):
                notes.append(f"book: {self.flow} is unknown now")
            else:
                notes.append(
                    "book: no anchor in the history, or the heater not "
                    "heard now"
                )
            return BookAnswer(None, False, tuple(notes))
        if e.inlet is None or e.demand is None or not inlet:
            return BookAnswer(booked, False, tuple(notes))
        if got.states is None:
            notes.append(
                f"inlet: {e.demand} not read (no states in the history)"
            )
            return BookAnswer(booked, False, tuple(notes))
        cold = mains_plateau(
            got,
            e.inlet,
            e.demand,
            e.circulation_speed,
            probe_unit=self._units.get(e.inlet),
            pump_unit=self._units.get(e.circulation_speed or ""),
            since=at - min(INLET_LOOKBACK, self.window),
            now=at,
            notes=notes,
        )
        if cold is None:
            return BookAnswer(booked, False, tuple(notes))
        moved, measured = on_the_mains(booked, cold)
        return BookAnswer(moved, measured, tuple(notes))
