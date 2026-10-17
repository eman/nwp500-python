"""Building the simulator's inputs from the library's models.

``nwp500.sim`` imports nothing from the rest of the library; this
module is the bridge. Each function takes what a client already fetched
(a ``DeviceStatus``, a ``DeviceFeature``, a ``ReservationSchedule``, a
``TOUInfo``) and returns a scenario part. Nothing here does I/O.

The simulator takes °F and US gallons, whatever unit system the
process has set. This module is where units are crossed, so a caller
works in the library's preferred units and never in the simulator's:

- The device's own fields are read raw (``*_raw``), never through the
  converted properties, whose unit follows the preference: the same
  status always builds the same scenario.
- What a caller supplies (the ambient, the inlet, a write's setpoint, a
  reservation's temperature, a draw's volume) is in the preferred unit:
  °C and litres with ``set_unit_system("metric")``, °F and gallons
  otherwise, as ``preferred_to_half_celsius`` reads it.
- ``temperature``, ``volume`` and ``path`` give a result's values back
  in the preferred unit: ``path`` the tank and the delivered water
  along it, ``volume`` the deliverable gallons of ``sim.delivery`` and
  of a draw window.

A reservation's setpoint stays in the device's half-degrees Celsius.

Example::

    from datetime import timedelta
    from nwp500 import sim, sim_adapters as sa

    scenario = sim.Scenario(
        start=now,
        horizon=timedelta(hours=24),
        tz="America/Los_Angeles",
        state=sa.heater_state(status),
        settings=sa.settings(status),
        schedules=sa.schedules(
            reservations=reservation_schedule,
            tou=tou_info,
            tou_enabled=status.tou_status,
        ),
        environment=sa.environment(status),
    )
    result = sim.simulate(scenario, sa.params(feature))
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, time
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import numpy as np

from nwp500.encoding import build_reservation_entry, encode_week_bitfield
from nwp500.enums import CurrentOperationMode, ErrorCode, HeatSource
from nwp500.models import (
    DeviceFeature,
    DeviceStatus,
    ReservationSchedule,
    TOUInfo,
    TOUPeriod,
    TOUReservationSchedule,
)
from nwp500.sim import (
    Booked,
    CirculationRun,
    Draw,
    DrawWindow,
    Environment,
    HeaterParams,
    HeaterState,
    Loads,
    RecoveryResult,
    ReservationEntry,
    Schedules,
    Settings,
    SimulationResult,
    TouPeriod,
    Trace,
    Write,
    default_params,
)
from nwp500.sim import full_tank_book as sim_full_tank_book
from nwp500.sim.location_air import (
    SITE_LOCATION_AIR,
    LocationAirModel,
)
from nwp500.sim.location_air import project as project_location_air
from nwp500.sim.schedules import weekly_runs
from nwp500.temperature import DeciCelsius, HalfCelsius, Temperature
from nwp500.unit_system import get_unit_system

if TYPE_CHECKING:
    import pandas as pd

# ── units ───────────────────────────────────────────────────────────
# The simulator's core takes °F and US gallons. Every conversion to or
# from them is in this section: a core in other units changes these
# functions and nothing else.

#: Litres in a US gallon.
_L_PER_GAL = 3.785411784


def _metric() -> bool:
    """Whether the preferred units are metric."""
    return get_unit_system() == "metric"


def _from_device(t: Temperature) -> float:
    """A device temperature in the simulator's unit."""
    return t.to_fahrenheit()


def _to_sim(value: float) -> float:
    """A temperature in the preferred unit, in the simulator's."""
    return value * 9 / 5 + 32 if _metric() else value


def _volume_to_sim(value: float) -> float:
    """A volume in the preferred unit, in the simulator's."""
    return value / _L_PER_GAL if _metric() else value


def to_sim_temperature(value: float) -> float:
    """A temperature in the preferred unit, in the simulator's (°F): for
    any input the builders below do not take."""
    return _to_sim(value)


def to_sim_volume(value: float) -> float:
    """A volume in the preferred unit, in the simulator's (US gallons):
    ``time_to_ready``'s ``bath_gal`` and ``shower_gal``, say."""
    return _volume_to_sim(value)


def temperature(value_f: float) -> float:
    """A temperature from the simulator (a ``*_f`` field) in the
    preferred unit."""
    return (value_f - 32) * 5 / 9 if _metric() else value_f


def volume(value_gal: float) -> float:
    """A volume from the simulator (US gallons) in the preferred unit."""
    return value_gal * _L_PER_GAL if _metric() else value_gal


def temperature_unit() -> str:
    """The preferred temperature unit's symbol."""
    return "°C" if _metric() else "°F"


def volume_unit() -> str:
    """The preferred volume unit's symbol."""
    return "L" if _metric() else "gal"


# ── from the device ─────────────────────────────────────────────────


def heater_state(status: DeviceStatus) -> HeaterState:
    """The tank and what is heating it: both thermistors (0.1 °C
    resolution), the compressor, and either element."""
    return HeaterState(
        upper_f=_from_device(DeciCelsius(status.tank_upper_temperature_raw)),
        lower_f=_from_device(DeciCelsius(status.tank_lower_temperature_raw)),
        compressor_running=bool(status.comp_use),
        element_running=bool(status.heat_upper_use)
        or bool(status.heat_lower_use),
    )


def settings(status: DeviceStatus) -> Settings:
    """The setpoint, the operation mode and the lower-zone start
    threshold."""
    return Settings(
        setpoint_f=_from_device(
            HalfCelsius(status.dhw_temperature_setting_raw)
        ),
        mode=int(status.dhw_operation_setting),
        hp_lower_on_f=_from_device(
            HalfCelsius(status.hp_lower_on_temp_setting_raw)
        ),
    )


def params(feature: DeviceFeature) -> HeaterParams:
    """The default parameters for the heater's tank size
    (``sim.default_params``)."""
    return default_params(int(feature.volume_code))


def reservation_entries(
    schedule: ReservationSchedule,
) -> tuple[ReservationEntry, ...]:
    """The schedule's entries, as the device stores them."""
    return tuple(
        ReservationEntry(
            enabled=e.enabled,
            week=e.week,
            hour=e.hour,
            minute=e.min,
            mode=e.mode,
            setpoint_half_c=e.param,
        )
        for e in schedule.reservation
    )


def _period(p: TOUPeriod, season: int | None = None) -> TouPeriod:
    return TouPeriod(
        season=p.season if season is None else season,
        week=p.week,
        start_hour=p.start_hour,
        start_minute=p.start_min,
        end_hour=p.end_hour,
        end_minute=p.end_min,
        price_min=p.price_min,
        price_max=p.price_max,
        decimal_point=p.decimal_point,
    )


def tou_periods(
    tou: TOUInfo | TOUReservationSchedule | Iterable[TOUPeriod],
) -> tuple[TouPeriod, ...]:
    """The TOU periods of a ``TOUInfo`` (the REST read), a
    ``TOUReservationSchedule`` (the MQTT write confirmation) or a list
    of ``TOUPeriod``."""
    if isinstance(tou, TOUInfo):
        out: list[TouPeriod] = []
        for season in tou.schedule:
            for raw in season.intervals:
                period = TOUPeriod.model_validate(
                    _with_season(raw, season.season)
                )
                out.append(_period(period))
        return tuple(out)
    if isinstance(tou, TOUReservationSchedule):
        return tuple(_period(p) for p in tou.reservation)
    return tuple(_period(p) for p in tou)


def _with_season(raw: Mapping[str, Any], season: int) -> dict[str, Any]:
    return {"season": season, **raw}


def schedules(
    *,
    reservations: ReservationSchedule | None = None,
    tou: TOUInfo | TOUReservationSchedule | Iterable[TOUPeriod] | None = None,
    tou_enabled: bool = False,
) -> Schedules:
    """The heater's schedules. ``tou_enabled`` is the device's TOU
    switch (``DeviceStatus.tou_status``); with a
    ``TOUReservationSchedule`` its own ``enabled`` is used instead."""
    if isinstance(tou, TOUReservationSchedule):
        tou_enabled = tou.enabled
    return Schedules(
        reservations=(
            () if reservations is None else reservation_entries(reservations)
        ),
        reservations_enabled=(
            True if reservations is None else reservations.enabled
        ),
        tou_periods=() if tou is None else tou_periods(tou),
        tou_enabled=tou_enabled,
    )


def environment(
    status: DeviceStatus | None = None,
    *,
    ambient: float | Iterable[tuple[datetime, float]] | None = None,
    humidity: float | None = None,
    inlet: float | None = None,
) -> Environment:
    """Where the heater sits. ``ambient`` is the air at the heater, in
    the preferred unit: one value, or ``(instant, value)`` readings such
    as ``location_air``'s projection. Without it, ``status``'s own
    reading of the air at its intake now (``ambient_temperature_raw``)
    holds for the whole span; while the compressor is idle that reading
    is the cabinet's, about 5 °F warm (``location_air_reading``).
    ``humidity`` is %RH; ``inlet`` the mains water, in the preferred
    unit. Each left out is the simulator's default, which its result
    names in ``defaults_used``."""
    if ambient is None:
        if status is None:
            raise ValueError("give ambient, or a status to read it from")
        ambient_f: float | tuple[tuple[datetime, float], ...] = _from_device(
            DeciCelsius(status.ambient_temperature_raw)
        )
    elif isinstance(ambient, int | float):
        ambient_f = _to_sim(float(ambient))
    else:
        ambient_f = tuple((at, _to_sim(v)) for at, v in ambient)
    kw: dict[str, Any] = {"ambient_f": ambient_f}
    if humidity is not None:
        kw["humidity"] = humidity
    if inlet is not None:
        kw["inlet_f"] = _to_sim(inlet)
    return Environment(**kw)


# ── what a caller supplies, in the preferred units ──────────────────


def loads(
    draws: Iterable[tuple[datetime, float]],
    windows: Iterable[tuple[datetime, datetime, float | None]] = (),
) -> Loads:
    """Hot water drawn: ``(instant, volume)`` pairs, the volume in the
    preferred unit as a meter on the delivered (mixed) line counts it;
    and the windows to judge, ``(start, end, expected volume or None)``
    (``sim.DrawWindow``)."""
    return Loads(
        draws=tuple(Draw(at=at, gallons=_volume_to_sim(v)) for at, v in draws),
        windows=tuple(
            DrawWindow(
                start=a,
                end=b,
                expected_gal=None if v is None else _volume_to_sim(v),
            )
            for a, b, v in windows
        ),
    )


def full_tank_book(
    status: DeviceStatus,
    params: HeaterParams,
    *,
    inlet: float | None = None,
) -> Booked:
    """The heat book anchored on ``status``'s tank as full
    (``sim.full_tank_book``), for a caller who knows it has been quiet
    since a heating ended: a recovery finished and nothing drawn since.
    ``inlet`` is the mains water, in the preferred unit."""
    return sim_full_tank_book(
        _from_device(DeciCelsius(status.tank_upper_temperature_raw)),
        _from_device(DeciCelsius(status.tank_lower_temperature_raw)),
        params.book_terms(),
        inlet_f=None if inlet is None else _to_sim(inlet),
    )


def write(
    at: datetime,
    *,
    setpoint: float | None = None,
    mode: int | None = None,
    id: str | None = None,
) -> Write:
    """A setpoint or mode write at ``at``, the setpoint in the preferred
    unit; ``mode`` a ``DhwOperationSetting`` value."""
    return Write(
        at=at,
        setpoint_f=None if setpoint is None else _to_sim(setpoint),
        mode=mode,
        id=id,
    )


def reservation_entry(
    *,
    days: Iterable[str | int],
    hour: int,
    minute: int,
    mode: int,
    temperature: float,
    enabled: bool = True,
) -> ReservationEntry:
    """A reservation entry as ``build_reservation_entry`` builds one for
    the device: ``days`` as names or indices (Monday 0), ``temperature``
    in the preferred unit and range-checked as it is for the device."""
    e = build_reservation_entry(
        enabled=enabled,
        days=days,
        hour=hour,
        minute=minute,
        mode_id=mode,
        temperature=temperature,
    )
    return ReservationEntry(
        enabled=e["enable"] == 2,
        week=e["week"],
        hour=e["hour"],
        minute=e["min"],
        mode=e["mode"],
        setpoint_half_c=e["param"],
    )


# ── results, in the preferred units ─────────────────────────────────


@dataclass(frozen=True)
class TankReading:
    """The tank at an instant, in the preferred unit."""

    at: datetime
    upper: float
    lower: float
    #: The setpoint in force; None for a ``Trace``, which has none.
    setpoint: float | None
    #: The delivered water's temperature; None but for a
    #: ``SimulationResult`` (``SimulationResult.delivery``).
    delivery: float | None = None


def path(
    result: SimulationResult | RecoveryResult | Trace,
) -> tuple[TankReading, ...]:
    """The tank along a result's path, in the preferred unit."""
    if isinstance(result, Trace):
        return tuple(
            TankReading(
                p.at, temperature(p.upper_f), temperature(p.lower_f), None
            )
            for p in result.points
        )
    if isinstance(result, SimulationResult):
        delivery: list[float | None] = (
            list(result.delivery)
            if result.delivery
            else [None] * len(result.points)
        )
        return tuple(
            TankReading(
                p.at,
                temperature(p.upper_f),
                temperature(p.lower_f),
                temperature(p.setpoint_f),
                None if d is None else temperature(d),
            )
            for p, d in zip(result.points, delivery, strict=True)
        )
    return tuple(
        TankReading(
            p.at,
            temperature(p.upper_f),
            temperature(p.lower_f),
            temperature(p.setpoint_f),
        )
        for p in result.path
    )


def _local_time(value: time | str) -> time:
    return value if isinstance(value, time) else time.fromisoformat(value)


def circulation(
    schedule: Iterable[tuple[Iterable[str | int], time | str, time | str]],
    *,
    tz: str,
    start: datetime,
    until: datetime,
) -> tuple[CirculationRun, ...]:
    """An installation's weekly circulation schedule as the runs between
    ``start`` and ``until`` (``Loads.circulation``): each entry
    ``(days, starts, ends)``, the days as names or indices (Monday 0),
    the local times as ``time`` or ``"HH:MM"`` in ``tz``; an ``ends`` at
    or before ``starts`` ends the next day."""
    entries = [
        (encode_week_bitfield(days), _local_time(a), _local_time(b))
        for days, a, b in schedule
    ]
    return tuple(
        CirculationRun(start=a, end=b)
        for a, b in weekly_runs(entries, ZoneInfo(tz), start, until)
    )


def location_air_reading(status: DeviceStatus) -> float | None:
    """The air where the heater stands, from its own sensor, in the
    preferred unit: only while the compressor runs, when the evaporator
    fan draws that air past it (within about 0.35 °F at one
    installation). None while idle, when it reads the cabinet, about
    5 °F warm."""
    if not status.comp_use:
        return None
    return temperature(
        _from_device(DeciCelsius(status.ambient_temperature_raw))
    )


def location_air(
    outdoor: Iterable[tuple[datetime, float]],
    *,
    start: datetime,
    until: datetime,
    anchor: tuple[datetime, float] | None = None,
    model: LocationAirModel = SITE_LOCATION_AIR,
) -> tuple[tuple[datetime, float], ...]:
    """The air where the heater stands from ``start`` to ``until``,
    projected from an ``outdoor`` forecast by ``model``
    (``sim.location_air``), every 10 minutes, in the preferred unit:
    ``environment(ambient=...)`` takes it. ``anchor``, a reading and its
    instant (``location_air_reading``'s, when the compressor last ran),
    moves the projection through it. ``model`` defaults to one
    installation's; fit your own with ``sim.location_air.fit``."""
    air = project_location_air(
        model,
        [(at, _to_sim(v)) for at, v in outdoor],
        start,
        until,
        anchor=None if anchor is None else (anchor[0], _to_sim(anchor[1])),
    )
    return tuple((at, temperature(v)) for at, v in air)


# ── for calibration ─────────────────────────────────────────────────


def _hybrid(status: DeviceStatus) -> bool:
    return status.operation_mode in (
        CurrentOperationMode.HYBRID_EFFICIENCY_MODE,
        CurrentOperationMode.HYBRID_BOOST_MODE,
    )


def _interval_column(
    index: pd.DatetimeIndex, spans: Iterable[tuple[datetime, datetime]]
) -> list[bool]:
    spans = list(spans)
    return [any(a <= t < b for a, b in spans) for t in index]


def history(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    *,
    air: Iterable[tuple[datetime, float]] | None = None,
    humidity: Iterable[tuple[datetime, float]] | None = None,
    drawing: Iterable[tuple[datetime, datetime]] | None = None,
    circulating: Iterable[tuple[datetime, datetime]] | None = None,
) -> pd.DataFrame:
    """A heater's history as ``sim.calibration`` takes it, from the
    statuses it reported and when (``readings``, any order).

    Everything a status carries is read from it: the probes, what is
    heating, ``dhw_use``, the lower probe's stop threshold, what rules a
    sample out of a heat-pump recovery, the energy still to heat, and
    the heater's own air
    reading while its compressor runs. What it does not carry is the
    caller's, in the preferred unit:

    - ``air``: the air where the heater stands, interpolated in time onto
      the readings (a sensor's, or ``location_air``'s projection); the
      standby fit needs it;
    - ``humidity``: that air's relative humidity, %;
    - ``drawing``, ``circulating``: the spans a meter saw water drawn and
      a circulation pump ran, where an installation records them.
    """
    import pandas as pd

    rows = sorted(readings, key=lambda r: r[0])
    index = pd.DatetimeIndex([at for at, _ in rows]).tz_convert("UTC")
    frame = pd.DataFrame(
        {
            "upper_f": [
                _from_device(DeciCelsius(s.tank_upper_temperature_raw))
                for _, s in rows
            ],
            "lower_f": [
                _from_device(DeciCelsius(s.tank_lower_temperature_raw))
                for _, s in rows
            ],
            "compressor_on": [bool(s.comp_use) for _, s in rows],
            "element_on": [
                bool(s.heat_upper_use)
                or bool(s.heat_lower_use)
                or s.current_heat_use
                in (HeatSource.HEATELEMENT, HeatSource.HEATPUMP_HEATELEMENT)
                for _, s in rows
            ],
            "dhw_in_use": [bool(s.dhw_use) for _, s in rows],
            "target_f": [
                _from_device(HalfCelsius(s.hp_lower_off_temp_setting_raw))
                for _, s in rows
            ],
            "excluded": [
                _hybrid(s)
                or bool(s.anti_legionella_operation_busy)
                or s.error_code != ErrorCode.NO_ERROR
                for _, s in rows
            ],
            "energy_to_setpoint_wh": [
                float(s.energy_to_setpoint) for _, s in rows
            ],
            "heater_air_f": [
                _from_device(DeciCelsius(s.ambient_temperature_raw))
                if s.comp_use
                else float("nan")
                for _, s in rows
            ],
        },
        index=index,
    )
    seconds = [t.timestamp() for t in index]
    for name, series in (("air_f", air), ("humidity_pct", humidity)):
        if series is None:
            continue
        points = sorted(series, key=lambda r: r[0])
        if not points:
            continue
        to = _to_sim if name == "air_f" else float
        frame[name] = np.interp(
            seconds,
            [at.timestamp() for at, _ in points],
            [to(v) for _, v in points],
        )
    for name, spans in (("drawing", drawing), ("circulating", circulating)):
        if spans is not None:
            frame[name] = _interval_column(index, spans)
    return frame
