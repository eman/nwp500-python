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
    ``location_air`` model, anchored to a fresh reading of the air
    beside the heater; without a model, that reading held over the
    span;
  - **the humidity:** a fresh reading;
  - **the inlet:** the plateau of the long draws in the last 72 h, from
    the inlet probe, the meter's flow and the circulation's runs
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
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from nwp500 import sim_adapters as sa
from nwp500.exceptions import Nwp500Error
from nwp500.sim import Environment, meter
from nwp500.sim.cold_supply import ColdSupply
from nwp500.sim.location_air import LocationAirModel
from nwp500.sim.location_air import project as project_air

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
#: A pump speed reading older than this is off.
PUMP_STALE = timedelta(seconds=300)
#: How far back the inlet's plateau looks.
INLET_LOOKBACK = timedelta(hours=72)
#: How long a request waits, seconds.
DEFAULT_TIMEOUT = 10.0

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
    #: A hot-water meter's volume since its previous report.
    meter_volume: str | None = None
    #: The same meter's forward flow rate.
    meter_flow: str | None = None
    #: The circulation pump's speed.
    circulation_speed: str | None = None
    #: A weather entity with an hourly forecast.
    weather: str | None = None


@dataclass(frozen=True)
class Sources:
    """Where the inputs are: Home Assistant's address and token, the
    entities, and the model that projects the air from the outdoor
    forecast (None: hold a fresh reading)."""

    url: str
    token: str = field(repr=False)
    entities: Entities
    location_air: LocationAirModel | None = None


def sources_from(doc: Mapping[str, Any], environ: Mapping[str, str]) -> Sources:
    """``Sources`` from a configuration document (a parsed TOML file)::

        [home_assistant]
        url = "http://homeassistant.local:8123"
        token_env = "HA_TOKEN"          # the variable holding the token

        [home_assistant.entities]
        air = "sensor.beside_the_heater_temperature"
        humidity = "sensor.beside_the_heater_humidity"
        inlet = "sensor.cold_supply_temperature"
        meter_volume = "sensor.water_volume"
        meter_flow = "sensor.water_flow_rate"
        circulation_speed = "sensor.circulation_pump_speed"
        weather = "weather.forecast_home"

        [location_air]                  # optional
        damping = 0.638
        lag_hours = 2.0
        offset_f = 24.5

    The token is read from ``environ``, never from the file. Raises
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
    )


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
    last reported (``last_reported``), so a sensor that keeps reporting
    the same value stays fresh. Home Assistant before 2024.3 has no
    ``last_reported``; then ``at`` is the last state or attribute change
    (``last_updated``, else ``last_changed``)."""
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


def reports_after(series: Sequence[Reading], start: datetime) -> list[Reading]:
    """A report series (a meter's volume since its previous report) from
    a history, without the row in force at ``start``: that row repeats
    the last report before the span, not one inside it."""
    return [(t, v) for t, v in series if t > start]


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
    stale: timedelta = PUMP_STALE,
) -> list[Span] | None:
    """The spans the pump ran from ``start`` to ``end``, from its speed
    (the reading in force at ``start`` first, as a history gives it): at
    or above ``on_rpm`` is running, below is stopped, and a run silent
    for longer than ``stale`` ended ``stale`` after its last reading.
    None (unknown, not idle) when there is no reading at all. Instants
    are read as UTC, so the silence holds across a change of clocks."""
    rows = sorted((t.astimezone(UTC), v) for t, v in speed)
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if not rows:
        return None
    runs: list[Span] = []
    for (at, rpm), nxt in zip(rows, [*rows[1:], None], strict=True):
        if rpm < on_rpm:
            continue
        a = max(at, start)
        b = min(at + stale, end) if nxt is None else min(nxt[0], at + stale)
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

    async def _attributes(self, entity: str) -> Mapping[str, Any]:
        doc = await self._json("GET", f"/api/states/{entity}")
        attributes = doc.get("attributes") if isinstance(doc, dict) else None
        return (
            cast(Mapping[str, Any], attributes)
            if isinstance(attributes, Mapping)
            else {}
        )


# ── the environment source ──────────────────────────────────────────


class HomeAssistantEnvironment:
    """An ``EnvironmentSource``: the air, its humidity and the inlet from
    Home Assistant, over ``start`` to ``until``, as of ``now`` (the
    driver's clock). ``notes`` say what each part rests on, or why it
    was left to the default, once ``read`` has run."""

    def __init__(
        self,
        client: HomeAssistantClient,
        entities: Entities,
        *,
        start: datetime,
        until: datetime,
        now: datetime | None = None,
        location_air: LocationAirModel | None = None,
    ) -> None:
        self.client = client
        self.entities = entities
        self.start = start
        self.until = until
        self.now = start if now is None else now
        self.location_air = location_air
        self.notes: list[str] = []

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
        anchor: Reading | None = None
        if e.air is not None:
            state = await self._fresh_state("air", e.air)
            if state is not None and state.value is not None:
                try:
                    anchor = (state.at, to_f(state.value, state.unit))
                except ValueError as err:
                    self.notes.append(f"air: {err}")
        if weather is not None and self.location_air is not None:
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
                    self.location_air,
                    outdoor,
                    self.start,
                    self.until,
                    anchor=anchor,
                )
                if air:
                    self.notes.append(
                        "air: projected from the outdoor forecast, "
                        + (
                            "anchored to the reading beside the heater"
                            if anchor
                            else "unanchored"
                        )
                    )
                    return air
        if anchor is not None:
            self.notes.append("air: the reading beside the heater, held")
            return anchor[1]
        return math.nan

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
        if e.inlet is None:
            return None
        if e.meter_volume is None:
            self.notes.append(
                "inlet: needs the meter's volume to find long draws"
            )
            return None

        async def read() -> float | None:
            notes: list[str] = []
            try:
                use = await _water_use(
                    self.client, e, self.now, INLET_LOOKBACK, notes, book=False
                )
            finally:
                self.notes.extend(f"inlet: {n}" for n in notes)
            return None if use.cold is None else use.cold.t_cold_f

        return cast("float | None", await self._guard("inlet", read, None))


@dataclass(frozen=True)
class WaterUse:
    """The water moving at the heater over a span (``read_water_use``):
    what the heat book and the inlet's plateau read."""

    #: The meter's flow, gal/min, on its grid (``sim.meter.flow_gpm``),
    #: any net flow however brief; from the meter's first reading when
    #: its history starts late, none while it was unavailable or read in
    #: no unit this reads, through its last report (``State.at``), and
    #: empty without a meter or its history. The book refuses the gaps.
    flow: list[Reading]
    #: The circulation pump's runs; empty without a pump, None when they
    #: are unknown (``notes`` say why), its speed unavailable over any of
    #: the span among them. Unknown runs are no runs to book by: the
    #: meter's circulation share can't be told from draws.
    runs: list[Span] | None
    #: The inlet probe's readings, °F; empty without one.
    probe: list[Reading]
    #: The spans water may have moved unseen: the runs, the readings in
    #: no unit this reads, and each entity's outages.
    busy: list[Span]
    #: The mains from the probe's plateau over the span's long draws
    #: (sustained runs of the meter, none overlapping ``busy``), °F; None
    #: without a probe and a meter, with no speed reading to know the
    #: pump's runs by, or with no long draw.
    cold: ColdSupply | None
    notes: tuple[str, ...] = ()


async def read_water_use(
    client: HomeAssistantClient,
    entities: Entities,
    *,
    now: datetime,
    lookback: timedelta = INLET_LOOKBACK,
) -> WaterUse:
    """The meter's flow, the circulation's runs, the inlet probe and the
    mains from ``lookback`` before ``now`` to ``now``, in one history
    read, as the live source's inlet reads them. The book takes them in
    the preferred units (``sim_adapters.volume`` and
    ``sim_adapters.temperature`` convert), and ``cold`` goes to
    ``sim.cold_supply.on_the_mains``. A part not read leaves its default
    and a note."""
    notes: list[str] = []
    try:
        return replace(
            await _water_use(client, entities, now, lookback, notes),
            notes=tuple(notes),
        )
    except (HomeAssistantError, ValueError) as err:
        notes.append(f"not read ({err})")
        return WaterUse([], None, [], [], None, tuple(notes))


async def _water_use(
    client: HomeAssistantClient,
    e: Entities,
    now: datetime,
    lookback: timedelta,
    notes: list[str],
    *,
    book: bool = True,
) -> WaterUse:
    """``read_water_use``, adding its notes to ``notes`` as it goes;
    without ``book``, no flow for the book (the live inlet's read)."""
    probe_id, volume_id = e.inlet, e.meter_volume
    rate_id, pump_id = e.meter_flow, e.circulation_speed
    since = now - lookback
    names = [n for n in (probe_id, volume_id, rate_id, pump_id) if n]
    if not names:
        return WaterUse([], [], [], [], None)
    got = await client.read_history(names, since, now)
    unread: list[Span] = []
    unread_of: dict[str, list[Span]] = {}
    reported: dict[str, datetime] = {}

    async def read_in(
        entity: str, to: Callable[[float, str | None], float]
    ) -> list[Reading]:
        state = await client.state(entity)
        reported[entity] = state.at
        rows, spans = got.converted(entity, state.unit, to, now)
        if spans:
            notes.append(
                f"{len(spans)} readings of {entity} in no unit this reads "
                "left out"
            )
            unread.extend(spans)
            unread_of[entity] = spans
        return rows

    probe = [] if probe_id is None else await read_in(probe_id, to_f)
    rate = [] if rate_id is None else await read_in(rate_id, to_gpm)
    volume = [] if volume_id is None else await read_in(volume_id, to_gal)
    reports = reports_after(volume, since)
    # The plateau's flow: only sustained runs count as draws.
    sustained = meter.flow_gpm(reports, rate, since, now)
    flow: list[Reading] = []
    if not book or volume_id is None:
        pass
    elif not volume:
        notes.append(f"no history of {volume_id} over the span")
    else:
        # The book's: any net flow is water drawn, however briefly. A
        # meter recorded only from later says nothing before that.
        begin = since if covers_start(volume, since) else volume[0][0]
        if begin > since:
            notes.append(
                f"{volume_id}: history covers only from {begin.isoformat()}"
            )
        flow = meter.flow_gpm(
            [r for r in reports if r[0] >= begin],
            rate,
            begin,
            now,
            sustain=timedelta(0),
        )
        # While the meter was unavailable, or said what nobody can read,
        # it was silent: no flow there, so the book refuses a long one.
        meter_ids = [n for n in (volume_id, rate_id) if n]
        dark = busy(
            *(unread_of.get(n, []) for n in meter_ids),
            *(got.outages.get(n, []) for n in meter_ids),
        )
        if dark:
            flow = [
                (t, v) for t, v in flow if not any(a <= t < b for a, b in dark)
            ]
            dark_h = sum((b - a).total_seconds() for a, b in dark) / 3600
            notes.append(
                f"the meter was unavailable or unread {len(dark)} times "
                f"({dark_h:.1f} h), left out of the flow"
            )
        # Nor after its last report: a meter that stopped reporting
        # without going unavailable is silent since.
        last = max(reported[n] for n in meter_ids)
        if last < now:
            flow = [(t, v) for t, v in flow if t <= last]
    runs: list[Span] | None = []
    if pump_id is not None:
        runs = await _pump_runs_since(
            client, pump_id, got, since, now, notes, unread
        )
    # A draw while any of them was unavailable may have overlapped a run
    # or ended unseen: the plateau skips it, as it skips one that
    # overlaps a run.
    down = busy(runs or [], unread, *(got.outages.get(n, []) for n in names))
    cold = None
    if probe_id is not None and volume_id is not None and runs is not None:
        # The adapter takes the preferred unit; these are °F and gal.
        cold = sa.cold_supply(
            [(t, sa.temperature(v)) for t, v in probe],
            at=now,
            flow=[(t, sa.volume(v)) for t, v in sustained],
            ticks=[t for t, v in sustained if v >= meter.DRAW_GPM],
            circulation=down,
            window=lookback,
        )
        hours = f"{lookback.total_seconds() / 3600:g}"
        if cold.t_cold_f is None:
            notes.append(
                f"no long draw in the last {hours} h to read the mains from"
            )
            cold = None
        else:
            notes.append(f"the plateau of {cold.draws} long draws")
    if book and pump_id is not None and runs is not None:
        # The plateau skips the draws over the pump's outages, but the
        # book can't: it may have run then.
        outages = got.outages.get(pump_id, [])
        if outages:
            notes.append(
                f"the circulation's runs are unknown ({len(outages)} "
                "outages of its speed)"
            )
            runs = None
    return WaterUse(flow, runs, probe, down, cold)


async def _pump_runs_since(
    client: HomeAssistantClient,
    pump_id: str,
    got: History,
    since: datetime,
    now: datetime,
    notes: list[str],
    unread: list[Span],
) -> list[Span] | None:
    """The pump's runs since ``since``, or None (and a note) when they
    are unknown: no reading in force at ``since`` (a draw before the
    first may have overlapped a run), or a speed in no unit this
    reads. The spans it may have run unseen go to ``unread``, and with
    the runs unknown, the runs it was seen to make too."""
    why = None
    speed: list[Reading] = []
    rows = got.readings.get(pump_id, [])
    start = since
    if not covers_start(rows, since):
        why = "no speed reading in force at the start"
        unread.append((since, rows[0][0] if rows else now))
        start = rows[0][0] if rows else now
    if rows:
        try:
            unit = (await client.state(pump_id)).unit
            speed, left = got.converted(pump_id, unit, to_rpm, now)
            if left:
                # A reading left out could have been a run.
                why = why or f"{len(left)} readings in no speed unit"
                unread.extend(left)
        except (HomeAssistantError, ValueError) as err:
            why = why or str(err)
            unread.append((start, now))
    runs = pump_runs(speed, start, now) if speed else None
    if why is not None:
        notes.append(f"the circulation's runs are unknown ({why})")
        unread.extend(runs or [])
        return None
    return runs


# ── over a recorded history, for the calibration ────────────────────


#: Draw ticks further apart than this are two draws.
DRAW_GAP = timedelta(seconds=30)


@dataclass(frozen=True)
class RecordInputs:
    """What Home Assistant recorded over a heater's history: the air
    beside it and that air's humidity (°F, %), the spans a meter saw
    water drawn, and the circulation's runs. None for a part it does
    not record, or could not be read (``notes`` say which)."""

    air: list[Reading] | None
    humidity: list[Reading] | None
    drawing: list[Span] | None
    circulating: list[Span] | None
    notes: tuple[str, ...] = ()
    #: The spans the air's and the humidity's entities were unavailable:
    #: not observed, whatever the readings either side say.
    air_outages: tuple[Span, ...] = ()
    humidity_outages: tuple[Span, ...] = ()


def draw_spans(
    flow: Sequence[Reading],
    *,
    draw_gpm: float = 0.3,
    gap: timedelta = DRAW_GAP,
    step: timedelta = timedelta(seconds=10),
) -> list[Span]:
    """The spans water moved, from a flow series on a grid
    (``sim.meter.flow_gpm``): runs of steps at or above ``draw_gpm``,
    joined across gaps up to ``gap``, each to its last step's end."""
    out: list[Span] = []
    for t, v in flow:
        if v < draw_gpm:
            continue
        if out and t - out[-1][1] <= gap:
            out[-1] = (out[-1][0], t + step)
        else:
            out.append((t, t + step))
    return out


def volume_spans(
    volume: Sequence[Reading],
    *,
    min_gal: float = meter.DRAW_GPM * meter.STEP.total_seconds() / 60.0,
    window: timedelta = meter.WINDOW,
) -> list[Span]:
    """The spans a meter's volume reports (each the volume since its
    previous report, gallons) say water moved: each report of
    ``min_gal`` or more, either sign, from the previous report (or
    ``window`` before it, if longer ago) to itself. The default is the
    draw line held for one step, well above a meter's noise at rest.
    However short or slow the draw, it is caught here, where the net
    flow over ``window`` can stay under the line."""
    out: list[Span] = []
    prev: datetime | None = None
    for t, v in sorted((t.astimezone(UTC), v) for t, v in volume):
        if abs(v) >= min_gal:
            a = t - window if prev is None else max(prev, t - window)
            out.append((a, t))
        prev = t
    return busy(out)


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
    names = [
        n
        for n in (
            e.air,
            e.humidity,
            e.meter_volume,
            e.meter_flow,
            e.circulation_speed,
        )
        if n
    ]
    if not names:
        return RecordInputs(None, None, None, None, ())
    try:
        got = await client.read_history(names, start, end)
    except HomeAssistantError as err:
        return RecordInputs(None, None, None, None, (f"not read ({err})",))
    history = got.readings
    units: dict[str, str | None] = {}
    for n in (
        e.air,
        e.humidity,
        e.meter_volume,
        e.meter_flow,
        e.circulation_speed,
    ):
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
        # and a meter's or pump's spans replace the heater's own flag:
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
    volume_id, rate_id = e.meter_volume, e.meter_flow
    volume = history.get(volume_id, []) if volume_id else []
    if volume_id and volume_id in units and whole("meter", volume):
        try:
            gallons = reports_after(read_in("meter", volume_id, to_gal), start)
            rate = (
                read_in("meter", rate_id, to_gpm)
                if rate_id and rate_id in units
                else []
            )
            # Any net flow at the line is water moving, however briefly:
            # the quiet test is conservative where the plateau's sustain
            # filter is not.
            flow = meter.flow_gpm(
                gallons, rate, start, end, sustain=timedelta(0)
            )
            # While the meter was unavailable, or said what nobody can
            # read, water may have moved.
            down = busy(
                unread.get("meter", []),
                *(got.outages.get(n, []) for n in (volume_id, rate_id) if n),
            )
            drawing = busy(
                draw_spans(flow),
                volume_spans(gallons),
                down,
            )
            outage("meter", down)
        except ValueError as err:
            notes.append(f"meter: {err}")
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
    ``sim_calibrate.calibrate_changes`` takes it: its values' changes,
    the instants it was heard from, and what the reading noted."""

    rows: sa.ChangeRows
    observed: list[datetime]
    notes: tuple[str, ...] = ()


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
    entities go unavailable together. Raises ``HomeAssistantError`` when
    a probe cannot be read, or the client gives no states
    (``History.states``)."""
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
