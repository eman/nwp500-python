"""The simulator's other inputs, read live from Home Assistant.

The heater reports its tank, its settings and its schedules, but not
the air it stands in while idle, that air's humidity, the mains water,
the water drawn or a circulation pump it does not run. An owner who
records those in Home Assistant gets them into a simulation through
this module, a ``sim_live`` source:

- ``HomeAssistantClient`` reads Home Assistant's REST API, read-only:
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
    (``sim_adapters.cold_supply``), never the probe's raw reading.

The rules are the reference implementation's:

- a reading more than an hour old is not used;
- a pump with no reading in force is unknown, never idle;
- a part that cannot be read leaves the simulator's default in place,
  and ``notes`` say why: a source that fails never fails the
  simulation.

Units come from each entity's ``unit_of_measurement``, never assumed.
Entity ids belong to the caller's configuration (``sources_from``), not
to this module. The parsing is pure and does no I/O; only the client
makes requests.
"""

import logging
import math
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from nwp500 import sim_adapters as sa
from nwp500.exceptions import Nwp500Error
from nwp500.sim import Environment, meter
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
    """``/api/states/<entity>``'s answer. ``at`` is the entity's last
    state or attribute change (``last_updated``), as the reference
    implementation's change rows date a reading."""
    if not isinstance(doc, Mapping) or "state" not in doc:
        raise HomeAssistantError("not an entity state")
    d = cast(Mapping[str, Any], doc)
    attributes = d.get("attributes")
    unit = None
    if isinstance(attributes, Mapping):
        u = cast(Mapping[str, Any], attributes).get("unit_of_measurement")
        unit = u if isinstance(u, str) else None
    stamp = d.get("last_updated") or d.get("last_changed")
    return State(
        entity=str(d.get("entity_id", "")),
        value=_number(d.get("state")),
        unit=unit,
        at=_instant(stamp),
    )


def parse_history(doc: Any) -> dict[str, list[Reading]]:
    """``/api/history/period``'s answer (with ``minimal_response``), by
    entity: each change's instant and number, in time order, values
    Home Assistant does not have left out."""
    if not isinstance(doc, list):
        raise HomeAssistantError("not a history")
    out: dict[str, list[Reading]] = {}
    for series in cast(list[Any], doc):
        if not isinstance(series, list) or not series:
            continue
        rows = cast(list[Any], series)
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
            stamp = r.get("last_changed") or r.get("last_updated")
            if value is not None and stamp is not None:
                readings.append((_instant(stamp), value))
        out[entity] = sorted(readings, key=lambda x: x[0])
    return out


def parse_forecast(doc: Any, entity: str) -> tuple[list[Reading], str | None]:
    """``weather.get_forecasts``'s answer for ``entity``: each hour's
    instant and temperature, and the unit when the answer gives one."""
    try:
        body = cast(Mapping[str, Any], doc)["service_response"][entity]
        hours = cast(list[Any], body["forecast"])
    except KeyError, TypeError:
        raise HomeAssistantError(f"no forecast for {entity}") from None
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
    None (unknown, not idle) when there is no reading at all."""
    rows = sorted(speed, key=lambda r: r[0])
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
    """Home Assistant's REST API, read-only. Use it as an async context
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
            async with self._session.request(
                method,
                self.url + path,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                **kw,
            ) as response:
                if response.status != 200:
                    body = (await response.text())[:200]
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
            raise HomeAssistantError(f"{method} {path}: {e!r}") from None

    async def state(self, entity: str) -> State:
        """``entity``'s value now."""
        return parse_state(await self._json("GET", f"/api/states/{entity}"))

    async def history(
        self, entities: Iterable[str], start: datetime, end: datetime
    ) -> dict[str, list[Reading]]:
        """Each of ``entities``' changes from ``start`` to ``end``. The
        first reading is the value in force at ``start``."""
        names = sorted(set(entities))
        if not names:
            return {}
        doc = await self._json(
            "GET",
            f"/api/history/period/{start.astimezone(UTC).isoformat()}",
            params={
                "filter_entity_id": ",".join(names),
                "end_time": end.astimezone(UTC).isoformat(),
                "minimal_response": "",
                "no_attributes": "",
            },
        )
        return parse_history(doc)

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
        state = await self._guard(what, lambda: self.client.state(entity), None)
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
        if not 0.0 <= state.value <= 100.0:
            self.notes.append(f"humidity: {state.value} is not a percentage")
            return None
        return state.value

    async def _inlet(self) -> float | None:
        e = self.entities
        probe_id, volume_id = e.inlet, e.meter_volume
        rate_id, pump_id = e.meter_flow, e.circulation_speed
        if probe_id is None:
            return None
        if volume_id is None:
            self.notes.append(
                "inlet: needs the meter's volume to find long draws"
            )
            return None
        since = self.now - INLET_LOOKBACK
        names = [n for n in (probe_id, volume_id, rate_id, pump_id) if n]

        async def read() -> float | None:
            history = await self.client.history(names, since, self.now)
            probe_unit = (await self.client.state(probe_id)).unit
            volume_unit = (await self.client.state(volume_id)).unit
            probe = [
                (t, to_f(v, probe_unit)) for t, v in history.get(probe_id, [])
            ]
            rate: list[Reading] = []
            if rate_id is not None:
                rate_unit = (await self.client.state(rate_id)).unit
                rate = [
                    (t, to_gpm(v, rate_unit))
                    for t, v in history.get(rate_id, [])
                ]
            flow = meter.flow_gpm(
                [
                    (t, to_gal(v, volume_unit))
                    for t, v in history.get(volume_id, [])
                ],
                rate,
                since,
                self.now,
            )
            runs: list[Span] | None = []
            if pump_id is not None:
                runs = pump_runs(history.get(pump_id, []), since, self.now)
                if runs is None:
                    self.notes.append(
                        "inlet: the circulation's runs are unknown"
                    )
                    return None
            # The adapter takes the preferred unit; these are °F and gal.
            cold = sa.cold_supply(
                [(t, sa.temperature(v)) for t, v in probe],
                at=self.now,
                flow=[(t, sa.volume(v)) for t, v in flow],
                ticks=[t for t, v in flow if v >= meter.DRAW_GPM],
                circulation=runs,
            )
            if cold.t_cold_f is None:
                self.notes.append(
                    "inlet: no long draw in the last 72 h to read the "
                    "mains from"
                )
                return None
            self.notes.append(f"inlet: the plateau of {cold.draws} long draws")
            return cold.t_cold_f

        return await self._guard("inlet", read, None)
