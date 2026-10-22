"""Building the simulator's inputs from the library's models.

Each function takes what a client already fetched (a
``DeviceStatus``, a ``DeviceFeature``, a ``ReservationSchedule``, a
``TOUInfo``) and returns a scenario part.

The simulator takes °F and US gallons, whatever unit system the
process has set. This module is where units are crossed, so a caller
works in the library's preferred units and never in the simulator's:

- The device's own fields are read in the device's units, whatever
  the preference.
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

import bisect
import itertools
import math
from array import array
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

import numpy as np

from nwp500.encoding import build_reservation_entry, encode_week_bitfield
from nwp500.enums import (
    CurrentOperationMode,
    DhwOperationSetting,
    ErrorCode,
    HeatSource,
)
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
    Commands,
    Draw,
    DrawWindow,
    Environment,
    HeaterParams,
    HeaterState,
    History,
    Loads,
    RecoveryResult,
    ReservationEntry,
    Scenario,
    Schedules,
    Settings,
    SimulationResult,
    TouPeriod,
    Trace,
    Write,
    default_params,
)
from nwp500.sim import full_tank_book as sim_full_tank_book
from nwp500.sim.book import AMBIENT_DEFAULT_F, book_steps
from nwp500.sim.book import Step as BookStep
from nwp500.sim.cold_supply import ColdSupply, ColdSupplyParams, plateau_t_cold
from nwp500.sim.inputs import POWER_OFF, VACATION
from nwp500.sim.location_air import (
    SITE_LOCATION_AIR,
    LocationAirModel,
)
from nwp500.sim.location_air import project as project_location_air
from nwp500.sim.observed import Observed
from nwp500.sim.observed import observe as observe_record
from nwp500.sim.profile import HeaterProfile
from nwp500.sim.record import Record
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
    resolution), the compressor, either element, and the heater's own
    count of the energy still to heat."""
    return HeaterState(
        upper_f=_from_device(DeciCelsius(status.tank_upper_temperature_raw)),
        lower_f=_from_device(DeciCelsius(status.tank_lower_temperature_raw)),
        compressor_running=bool(status.comp_use),
        element_running=bool(status.heat_upper_use)
        or bool(status.heat_lower_use),
        energy_to_setpoint_wh=float(status.energy_to_setpoint),
    )


def settings(status: DeviceStatus) -> Settings:
    """The setpoint, the operation mode, the lower zone's start and stop
    thresholds, and the upper zone's start threshold.

    Raises:
        ValueError: The heater reports Standby (0), a status-only mode
            the simulator does not model.
    """
    if status.dhw_operation_setting == DhwOperationSetting.STANDBY:
        raise ValueError(
            "the heater reports Standby (dhw_operation_setting 0), a mode "
            "the simulator does not model"
        )
    return Settings(
        setpoint_f=_from_device(
            HalfCelsius(status.dhw_temperature_setting_raw)
        ),
        mode=int(status.dhw_operation_setting),
        hp_lower_on_f=_from_device(
            HalfCelsius(status.hp_lower_on_temp_setting_raw)
        ),
        hp_lower_off_f=_from_device(
            HalfCelsius(status.hp_lower_off_temp_setting_raw)
        ),
        hp_upper_on_f=_from_device(
            HalfCelsius(status.hp_upper_on_temp_setting_raw)
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


def _finite(
    rows: Iterable[tuple[datetime, float | None]],
) -> list[tuple[datetime, float]]:
    """``rows`` without its missing readings: a None, NaN or infinite
    value is a reading not taken, never a number to compute with."""
    return [
        (t, float(v)) for t, v in rows if v is not None and math.isfinite(v)
    ]


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
    is the cabinet's, about 6 °F warm (``location_air_reading``).
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
        ambient_f = tuple((at, _to_sim(v)) for at, v in _finite(ambient))
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
        draws=tuple(
            Draw(at=at, gallons=_volume_to_sim(v)) for at, v in _finite(draws)
        ),
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


def evaporator_f(status: DeviceStatus) -> float | None:
    """The evaporator coil's live reading, °F, for
    ``sim.active_cycle``: only while the compressor runs, when the
    running refrigerant cools it to the operating point; None
    otherwise."""
    if not status.comp_use:
        return None
    return _from_device(DeciCelsius(status.evaporator_temperature_raw))


def location_air_reading(status: DeviceStatus) -> float | None:
    """The air where the heater stands, from its own sensor, in the
    preferred unit: only while the compressor runs, when the evaporator
    fan draws that air past it. At one installation, against a sensor
    beside the heater, it read within about 0.35 °F from August to
    October, but up to about 2 °F warm from May to July, and about
    2.7 °F warm in a run's first 2 minutes. None while idle, when it
    reads the cabinet, about 6 °F warm."""
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
        [(at, _to_sim(v)) for at, v in _finite(outdoor)],
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
) -> np.ndarray:
    """Each row's interval (its instant to the next row's) that overlaps
    a span: a span wholly between two samples marks the first. The
    index is in time order."""
    import pandas as pd

    t = index.as_unit("ns").asi8
    n = len(t)
    out = np.zeros(n, dtype=bool)
    spans = list(spans)
    if not spans or not n:
        return out
    # utc=True takes instants with differing offsets (across a change
    # of clocks).
    starts = pd.to_datetime([a for a, _ in spans], utc=True)
    ends = pd.to_datetime([b for _, b in spans], utc=True)
    a = starts.as_unit("ns").asi8
    b = ends.as_unit("ns").asi8
    # Row i < n - 1 is marked when a < t[i + 1] and b > t[i]: from the
    # last row at or before a to the last row before b.
    lo = np.maximum(np.searchsorted(t, a, side="right") - 1, 0)
    hi = np.minimum(np.searchsorted(t, b, side="left"), n - 1)
    keep = hi > lo
    marks = np.zeros(n + 1, dtype=np.int64)
    np.add.at(marks, lo[keep], 1)
    np.add.at(marks, hi[keep], -1)
    out[:] = np.cumsum(marks[:n]) > 0
    # The last row has no next: a span holding its instant marks it.
    out[-1] = bool(((a <= t[-1]) & (t[-1] < b)).any())
    return out


#: The epoch, for an instant as whole microseconds.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_US = timedelta(microseconds=1)

#: The history's columns from a status, in order, and their type code.
_COLUMNS = (
    ("upper_f", "d"),
    ("lower_f", "d"),
    ("compressor_on", "b"),
    ("element_on", "b"),
    ("dhw_in_use", "b"),
    ("target_f", "d"),
    ("excluded", "b"),
    ("power_w", "d"),
    ("energy_to_setpoint_wh", "d"),
    ("heater_air_f", "d"),
)


def _row(s: DeviceStatus) -> tuple[float | bool, ...]:
    """A status's values, in ``_COLUMNS``' order."""
    return (
        _from_device(DeciCelsius(s.tank_upper_temperature_raw)),
        _from_device(DeciCelsius(s.tank_lower_temperature_raw)),
        bool(s.comp_use),
        bool(s.heat_upper_use)
        or bool(s.heat_lower_use)
        or s.current_heat_use
        in (HeatSource.HEATELEMENT, HeatSource.HEATPUMP_HEATELEMENT),
        bool(s.dhw_use),
        _from_device(HalfCelsius(s.hp_lower_off_temp_setting_raw)),
        _hybrid(s)
        or bool(s.anti_legionella_operation_busy)
        or s.error_code != ErrorCode.NO_ERROR,
        float(s.current_inst_power),
        float(s.energy_to_setpoint),
        _from_device(DeciCelsius(s.ambient_temperature_raw))
        if s.comp_use
        else float("nan"),
    )


def history(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    *,
    air: Iterable[tuple[datetime, float]] | None = None,
    humidity: Iterable[tuple[datetime, float]] | None = None,
    drawing: Iterable[tuple[datetime, datetime]] | None = None,
    circulating: Iterable[tuple[datetime, datetime]] | None = None,
    max_gap: timedelta | None = None,
) -> pd.DataFrame:
    """A heater's history as ``sim.calibration`` takes it, from the
    statuses it reported and when (``readings``, any order).

    Everything a status carries is read from it: the probes, what is
    heating, ``dhw_use``, the lower probe's stop threshold, what rules a
    sample out of a heat-pump recovery, the power it draws, the energy
    still to heat, and the heater's own air reading while its compressor
    runs. ``readings`` is taken one at a time and only those values are
    kept, so a generator over a long recording
    (``status_history.iter_read``) needs memory for the history, not
    for its statuses.

    What a status does not carry is the caller's, as
    ``add_inputs`` takes it.
    """
    import pandas as pd

    times: array[int] = array("q")
    values: list[array[Any]] = [array(code) for _, code in _COLUMNS]
    for at, status in readings:
        times.append((at - _EPOCH) // _US)
        for column, value in zip(values, _row(status), strict=True):
            column.append(value)
    stamps = (
        np.frombuffer(times, dtype=np.int64) if times else np.empty(0, np.int64)
    )
    order = np.argsort(stamps, kind="stable")
    ordered = bool(np.all(order == np.arange(len(order))))
    data: dict[str, np.ndarray] = {}
    for (name, code), column in zip(_COLUMNS, values, strict=True):
        a = np.array(column, dtype=float if code == "d" else bool)
        data[name] = a if ordered else a[order]
    index = pd.DatetimeIndex(
        pd.to_datetime(
            stamps if ordered else stamps[order], unit="us", utc=True
        )
    ).as_unit("ns")
    frame = pd.DataFrame(data, index=index)
    return add_inputs(
        frame,
        air=air,
        humidity=humidity,
        drawing=drawing,
        circulating=circulating,
        max_gap=max_gap,
    )


def add_inputs(
    frame: pd.DataFrame,
    *,
    air: Iterable[tuple[datetime, float]] | None = None,
    humidity: Iterable[tuple[datetime, float]] | None = None,
    drawing: Iterable[tuple[datetime, datetime]] | None = None,
    circulating: Iterable[tuple[datetime, datetime]] | None = None,
    max_gap: timedelta | None = None,
) -> pd.DataFrame:
    """``frame`` (``history``'s) with what its statuses do not carry,
    added in place, in the preferred unit:

    - ``air``: the air where the heater stands, interpolated in time onto
      the readings (a sensor's, or ``location_air``'s projection); the
      standby fit needs it;
    - ``humidity``: that air's relative humidity, %;
    - ``drawing``, ``circulating``: the spans a meter saw water drawn and
      a circulation pump ran, where an installation records them. A
      sample is marked when its interval (to the next sample) overlaps
      a span, so a short one between samples is not lost. Give
      both or neither: the standby fit keeps the heater's ``dhw_use``
      for whichever is missing, but the recoveries' draw-free test
      (``calibration.snapshots``) drops it once either is given.

    ``max_gap``: readings further apart than this are a span nobody
    observed (a recorder stopped and started again). The sample before
    such a span is marked water in use and excluded, so no quiet
    window and no recovery spans it. Without it, every span between two
    readings is taken as observed.
    """
    index = cast("pd.DatetimeIndex", frame.index)
    seconds = index.as_unit("ns").asi8 / 1e9
    for name, series in (("air_f", air), ("humidity_pct", humidity)):
        if series is None:
            continue
        points = sorted(_finite(series), key=lambda r: r[0])
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
    unobserved = np.zeros(len(frame), dtype=bool)
    if max_gap is not None and len(frame) > 1:
        unobserved[:-1] = np.diff(seconds) > max_gap.total_seconds()
    if "heater_unobserved" in frame.columns:
        # ``change_history``'s outages, into the draws added here too.
        unobserved |= frame["heater_unobserved"].to_numpy(dtype=bool)
    if unobserved.any():
        for name in ("dhw_in_use", "drawing", "excluded"):
            if name in frame.columns:
                frame[name] = frame[name].to_numpy(dtype=bool) | unobserved
    return frame


# ── a heater's history from its values' changes ───────────────────

#: A value's changes: each instant it took a new value, and the value.
Changes = Sequence[tuple[datetime, Any]]


@dataclass(frozen=True)
class ChangeRows:
    """A heater's history as the changes of each value a status carries
    (Home Assistant's entity history, say): each series the instants a
    value changed and what it changed to, in time order. A value holds
    until its next change. Temperatures are °F, power W, energy Wh.

    Only the probes are needed. Without a value, its column keeps
    ``history``'s default: the flags off, a number unknown.
    """

    upper_f: Changes
    lower_f: Changes
    compressor_on: Changes = ()
    upper_element_on: Changes = ()
    lower_element_on: Changes = ()
    #: ``HeatSource`` values.
    heat_source: Changes = ()
    dhw_in_use: Changes = ()
    #: The lower probe's heat-pump stop threshold.
    target_f: Changes = ()
    #: ``CurrentOperationMode`` values.
    operation_mode: Changes = ()
    anti_legionella: Changes = ()
    #: ``ErrorCode`` values.
    error_code: Changes = ()
    power_w: Changes = ()
    energy_to_setpoint_wh: Changes = ()
    #: The heater's own air reading, used only while its compressor runs.
    heater_air_f: Changes = ()
    #: The spans a value was unknown (Home Assistant's ``unavailable``
    #: or ``unknown``): unobserved, like a gap between statuses.
    outages: Sequence[tuple[datetime, datetime]] = ()


def _ns(instants: Iterable[datetime]) -> np.ndarray:
    """``instants`` as UTC nanoseconds."""
    import pandas as pd

    return np.asarray(
        pd.to_datetime(list(instants), utc=True).as_unit("ns").asi8,
        dtype=np.int64,
    )


def _held_at(
    changes: Changes, at: np.ndarray, missing: Any, dtype: Any
) -> np.ndarray:
    """``changes`` held from each change to the next, read at ``at``
    (ns); ``missing`` before the first."""
    out = np.full(len(at), missing, dtype=dtype)
    if not changes:
        return out
    rows = sorted(changes, key=lambda r: r[0])
    times = _ns(t for t, _ in rows)
    values = np.array([v for _, v in rows], dtype=dtype)
    i = np.searchsorted(times, at, side="right") - 1
    seen = i >= 0
    out[seen] = values[i[seen]]
    return out


def change_history(
    rows: ChangeRows, observed: Iterable[datetime]
) -> pd.DataFrame:
    """``history``'s frame from a heater's values' changes (``rows``).

    A value that holds writes no change, so the changes cannot tell an
    observed span from one nobody saw: ``observed`` is the instants the
    heater was heard from (an entity that changes on every status
    response, say). The frame has a row at each of them and at each
    change between the first and the last, each value as it stood
    then. Rows over an outage are marked water in use and excluded, as
    ``add_inputs`` marks a gap, and ``heater_unobserved``. Without a
    compressor flag, the heat source says when the compressor runs.
    """
    import pandas as pd

    heard = _ns(observed)
    if not len(heard):
        at = heard
    else:
        first, last = heard.min(), heard.max()
        changed = [
            _ns(t for t, _ in series)
            for series in (
                rows.upper_f,
                rows.lower_f,
                rows.compressor_on,
                rows.upper_element_on,
                rows.lower_element_on,
                rows.heat_source,
                rows.dhw_in_use,
                rows.target_f,
                rows.operation_mode,
                rows.anti_legionella,
                rows.error_code,
                rows.power_w,
                rows.energy_to_setpoint_wh,
                rows.heater_air_f,
            )
            if series
        ]
        at = np.unique(np.concatenate([heard, *changed]))
        at = at[(at >= first) & (at <= last)]
    nan = float("nan")
    source = _held_at(rows.heat_source, at, -1, np.int64)
    compressor = (
        _held_at(rows.compressor_on, at, False, bool)
        if rows.compressor_on
        # Without its own flag, the heat source says when it runs.
        else np.isin(
            source,
            [int(HeatSource.HEATPUMP), int(HeatSource.HEATPUMP_HEATELEMENT)],
        )
    )
    mode = _held_at(rows.operation_mode, at, -1, np.int64)
    error = _held_at(rows.error_code, at, int(ErrorCode.NO_ERROR), np.int64)

    def optional(series: Changes) -> np.ndarray | None:
        return _held_at(series, at, nan, float) if series else None

    columns: dict[str, np.ndarray | None] = {
        "upper_f": _held_at(rows.upper_f, at, nan, float),
        "lower_f": _held_at(rows.lower_f, at, nan, float),
        "compressor_on": compressor,
        "element_on": _held_at(rows.upper_element_on, at, False, bool)
        | _held_at(rows.lower_element_on, at, False, bool)
        | np.isin(
            source,
            [int(HeatSource.HEATELEMENT), int(HeatSource.HEATPUMP_HEATELEMENT)],
        ),
        "dhw_in_use": _held_at(rows.dhw_in_use, at, False, bool),
        "target_f": optional(rows.target_f),
        "excluded": np.isin(
            mode,
            [
                int(CurrentOperationMode.HYBRID_EFFICIENCY_MODE),
                int(CurrentOperationMode.HYBRID_BOOST_MODE),
            ],
        )
        | _held_at(rows.anti_legionella, at, False, bool)
        | (error != int(ErrorCode.NO_ERROR)),
        "power_w": optional(rows.power_w),
        "energy_to_setpoint_wh": optional(rows.energy_to_setpoint_wh),
        "heater_air_f": np.where(
            compressor, _held_at(rows.heater_air_f, at, nan, float), nan
        ),
    }
    # ``history``'s columns, in its order, less the values not given.
    data = {k: v for k, v in columns.items() if v is not None}
    index = pd.DatetimeIndex(pd.to_datetime(at, unit="ns", utc=True))
    frame = pd.DataFrame(data, index=index)
    if rows.outages and len(frame):
        down = np.asarray(_interval_column(index, rows.outages))
        for name in ("dhw_in_use", "excluded"):
            frame[name] = frame[name].to_numpy(dtype=bool) | down
        # Kept, so ``add_inputs`` marks a meter's draws over them too.
        frame["heater_unobserved"] = down
    return frame


# ── a past scenario, from the statuses the heater reported ─────────

#: A tank reading older than this at the instant is no state to start
#: from.
TANK_MAX_AGE = timedelta(hours=2)
#: How far back the compressor's edge is looked for: a recovery runs
#: hours and the restart lockout minutes.
COMPRESSOR_LOOKBACK = timedelta(days=1)
#: How far back an element's or a setting's last state is looked for.
STATUS_LOOKBACK = timedelta(days=7)


@dataclass(frozen=True)
class Replay:
    """A past scenario built from what the heater reported, and what
    could not be put in it (``recorded_write_not_modelled``: a write
    into Vacation or Power Off, for which the simulator holds no
    rule)."""

    scenario: Scenario
    reasons: tuple[str, ...]


def _last_edge(
    rows: list[tuple[datetime, bool]],
) -> tuple[bool, datetime | None]:
    """A sampled state's last value, and when it took it: the first
    sample of its last run; None when every sample has it (the change
    is before them)."""
    if not rows:
        return False, None
    i = len(rows) - 1
    while i > 0 and rows[i - 1][1] == rows[-1][1]:
        i -= 1
    return rows[-1][1], rows[i][0] if i > 0 else None


def _air(status: DeviceStatus) -> Environment:
    """``environment(status)``, for a function whose own parameter is
    named so."""
    return environment(status)


def record(readings: Iterable[tuple[datetime, DeviceStatus]]) -> Record:
    """A heater's record (``sim.record.Record``) from the statuses it
    reported and when: each signal's value at each status, kept only
    where it changed. A value then holds until its next row, as the
    record's readers take it."""
    rows = sorted(
        ((t.astimezone(UTC), s) for t, s in readings), key=lambda r: r[0]
    )

    def changes(
        f: Callable[[DeviceStatus], float],
    ) -> tuple[tuple[datetime, float], ...]:
        out: list[tuple[datetime, float]] = []
        for t, s in rows:
            v = f(s)
            if not out or out[-1][1] != v:
                out.append((t, v))
        return tuple(out)

    def on(flag: object) -> float:
        return 1.0 if flag else 0.0

    return Record(
        compressor=changes(lambda s: on(s.comp_use)),
        upper_element=changes(lambda s: on(s.heat_upper_use)),
        lower_element=changes(lambda s: on(s.heat_lower_use)),
        power_w=changes(lambda s: float(s.current_inst_power)),
        mode=changes(lambda s: float(int(s.dhw_operation_setting))),
        setpoint_f=changes(
            lambda s: _from_device(HalfCelsius(s.dhw_temperature_setting_raw))
        ),
        heat_source=changes(lambda s: float(int(s.current_heat_use))),
        upper_f=changes(
            lambda s: _from_device(DeciCelsius(s.tank_upper_temperature_raw))
        ),
        lower_f=changes(
            lambda s: _from_device(DeciCelsius(s.tank_lower_temperature_raw))
        ),
        hp_lower_on_f=changes(
            lambda s: _from_device(HalfCelsius(s.hp_lower_on_temp_setting_raw))
        ),
        hp_upper_on_f=changes(
            lambda s: _from_device(HalfCelsius(s.hp_upper_on_temp_setting_raw))
        ),
        tou=changes(lambda s: on(s.tou_status)),
    )


def observe(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    profile: HeaterProfile | None = None,
    revision_since: datetime | None = None,
) -> Observed:
    """What the heater did over ``[start, end)`` (``sim.observed``),
    from the statuses it reported: modes and whether each was in
    effect, when each source ran, the compressor's starts with why and
    whether each counts, the energy per slot from its own power, the
    delivered temperature, and where its record was missing. Nothing
    after ``now`` is claimed; ``start`` and ``end`` on the 10-minute
    slot grid. Modes are named by ``profile`` from ``revision_since``
    (``sim.observed.observe``)."""
    return observe_record(
        record(readings),
        start.astimezone(UTC),
        end.astimezone(UTC),
        now=now.astimezone(UTC),
        profile=profile,
        revision_since=(
            None if revision_since is None else revision_since.astimezone(UTC)
        ),
    )


#: How far before a replay's start its recorded air is read.
CLIMATE_LOOKBACK = timedelta(hours=6)


def _recorded_air(
    air: Iterable[tuple[datetime, float]] | None,
    at: datetime,
    until: datetime,
    humidity: float | None,
    status: DeviceStatus,
) -> Environment:
    """A replay's air: the recorded readings' 10-minute means from
    ``CLIMATE_LOOKBACK`` before ``at`` to as long after ``until``, the
    last carried over a silent bin; the heater's own reading with
    none."""
    import pandas as pd

    rows = sorted(
        (t.astimezone(UTC), _to_sim(v))
        for t, v in _finite(air or ())
        if at - CLIMATE_LOOKBACK
        <= t.astimezone(UTC)
        <= until + CLIMATE_LOOKBACK
    )
    if not rows:
        fallback = _air(status)
        if humidity is None:
            return fallback
        return fallback.model_copy(update={"humidity": humidity})
    series = pd.Series(
        [v for _, v in rows], index=pd.DatetimeIndex([t for t, _ in rows])
    )
    binned = series.resample("10min").mean().ffill().dropna()
    kw: dict[str, Any] = {
        "ambient_f": tuple(
            (t.to_pydatetime(), float(v)) for t, v in binned.items()
        )
    }
    if humidity is not None:
        kw["humidity"] = humidity
    return Environment(**kw)


def replay(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    *,
    at: datetime,
    until: datetime,
    tz: str,
    schedules: Schedules | None = None,
    environment: Environment | None = None,
    air: Iterable[tuple[datetime, float]] | None = None,
    humidity: float | None = None,
    loads: Loads | None = None,
    writes: bool = True,
) -> Replay:
    """The scenario from ``at`` to ``until`` as the heater stood: each
    from the last status at or before ``at`` (``readings``, ``(instant,
    status)``, any order), as the model's replay read its record.

    - the tank, what is heating, the settings and the TOU switch: the
      status in force at ``at``, which must be within ``TANK_MAX_AGE``;
    - when the compressor last stopped (for the restart lockout), and
      when the tank last heated: its last off-edge within
      ``COMPRESSOR_LOOKBACK``, and the elements' within
      ``STATUS_LOOKBACK``, an edge being the first status after the
      change (a sampled record knows no closer);
    - the TOU switch's changes over the span (``Schedules.tou_switches``);
    - with ``writes``, every recorded change of the setpoint or the mode
      over the span as a write, but the heater's own drop to Heat Pump
      at a window's opening (within ``sim.record.DROP_WITHIN`` of TOU
      switching on or its upper threshold rising).

    ``schedules`` brings the TOU periods and reservations (the
    heater's own, read with this library: the record has none); its
    switch and switches are the record's. ``environment`` defaults to
    the recorded ``air`` where the heater stands (a sensor's readings,
    in the preferred unit), as 10-minute means from ``CLIMATE_LOOKBACK``
    before ``at`` (a past instant's weather forecast is not recorded),
    with ``humidity`` (%RH); without it, to the heater's own air reading
    at ``at``, which reads the cabinet, about 6 °F warm, while the
    compressor is idle.
    """
    at, until = at.astimezone(UTC), until.astimezone(UTC)
    if until <= at:
        raise ValueError("until must be after at")
    rows = sorted(
        ((t.astimezone(UTC), s) for t, s in readings), key=lambda r: r[0]
    )
    before = [(t, s) for t, s in rows if t <= at]
    if not before or at - before[-1][0] > TANK_MAX_AGE:
        raise ValueError(f"no status within {TANK_MAX_AGE} before at")
    now = before[-1][1]
    comp = [
        (t, bool(s.comp_use))
        for t, s in before
        if t >= at - COMPRESSOR_LOOKBACK
    ]
    running, edge = _last_edge(comp)
    stopped = None if running else edge
    recent = [(t, s) for t, s in before if t >= at - STATUS_LOOKBACK]
    upper_on, upper_edge = _last_edge(
        [(t, bool(s.heat_upper_use)) for t, s in recent]
    )
    lower_on, lower_edge = _last_edge(
        [(t, bool(s.heat_lower_use)) for t, s in recent]
    )
    heated: datetime | None = None
    if running or upper_on or lower_on:
        heated = at
    elif stopped is not None:
        heated = max(
            [stopped, *(e for e in (upper_edge, lower_edge) if e is not None)]
        )
    state = heater_state(now).model_copy(
        update={
            "compressor_running": running,
            "element_running_since": upper_edge if upper_on else None,
        }
    )
    rec = record(rows)
    switches = rec.tou_switches(at, until)
    base = schedules if schedules is not None else Schedules()
    reasons: list[str] = []
    recorded: list[Write] = []
    if writes:
        for w in rec.writes(at, until):
            if w.dropped:
                continue
            if w.mode is not None:
                if w.mode in (VACATION, POWER_OFF):
                    # No rule for what a write into or out of them does:
                    # the whole write is left out, its setpoint too.
                    reasons.append("recorded_write_not_modelled")
                    continue
                else:
                    recorded.append(Write(at=w.at, mode=w.mode))
            if w.setpoint_f is not None:
                recorded.append(Write(at=w.at, setpoint_f=w.setpoint_f))
    scenario = Scenario(
        start=at,
        horizon=until - at,
        tz=tz,
        state=state,
        settings=settings(now),
        history=History(compressor_stopped_at=stopped, heated_at=heated),
        schedules=base.model_copy(
            update={
                "tou_enabled": bool(now.tou_status),
                "tou_switches": tuple(switches),
            }
        ),
        environment=(
            environment
            if environment is not None
            else _recorded_air(air, at, until, humidity, now)
        ),
        loads=loads if loads is not None else Loads(),
        commands=Commands(writes=tuple(recorded)),
    )
    return Replay(scenario, tuple(dict.fromkeys(reasons)))


# ── the heat book, from a recorded history ─────────────────────────

#: The grid a recorded history is booked on, seconds.
BOOK_GRID_S = 10
#: How long a flow reading holds (the household meter's, circulation's).
FLOW_HOLD = timedelta(seconds=60)
#: How long an inlet probe's reading holds.
INLET_HOLD = timedelta(hours=1)
#: The longest the meter may be silent in a booked window: a gap would
#: read as a quiet full tank, a false anchor.
METER_MAX_GAP = timedelta(hours=1)


def _held(
    readings: Sequence[tuple[datetime, float]],
    grid: Sequence[datetime],
    hold: timedelta | None,
) -> list[float | None]:
    """The reading in force at each instant of ``grid``, no older than
    ``hold``; None where there is none."""
    out: list[float | None] = []
    i = -1
    for t in grid:
        while i + 1 < len(readings) and readings[i + 1][0] <= t:
            i += 1
        if i < 0 or (hold is not None and t - readings[i][0] > hold):
            out.append(None)
        else:
            out.append(readings[i][1])
    return out


def _book_grid(start: datetime, end: datetime) -> list[datetime]:
    """The book's grid (``BOOK_GRID_S``) from ``start`` up to ``end``."""
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    grid: list[datetime] = []
    t = start
    while t < end:
        grid.append(t)
        t += timedelta(seconds=BOOK_GRID_S)
    return grid


@dataclass(frozen=True)
class _Heater:
    """The heater's columns on the book's grid: the probes (°F; None
    where unknown), and whether the compressor and each element run."""

    upper: list[float | None]
    lower: list[float | None]
    compressor: list[bool]
    upper_element: list[bool]
    lower_element: list[bool]


def run_flow(
    runs: Iterable[tuple[datetime, datetime]], flow_gpm: float
) -> list[tuple[datetime, float]]:
    """``runs`` at ``flow_gpm`` (gal/min) as the circulation's own flow
    readings on the book's grid, for ``book_from_changes``'s
    ``circulation_flow`` where no sensor reads the pump: a run is booked
    at its flow (``CirculationParams.flow_gpm``)."""
    out: list[tuple[datetime, float]] = []
    step = timedelta(seconds=BOOK_GRID_S)
    for t, end in sorted(
        (a.astimezone(UTC), b.astimezone(UTC)) for a, b in runs
    ):
        while t < end:
            out.append((t, flow_gpm))
            t += step
    return out


def run_readings(
    runs: Iterable[tuple[datetime, datetime]],
    readings: Iterable[tuple[datetime, float | None]],
) -> list[tuple[datetime, float]]:
    """The loop's flow ``readings`` (gal/min) within ``runs``, for
    ``book_from_changes``'s ``circulation_flow``: each run's own, its
    first held from the run's start. A reading outside every run (a
    pump read as 0 while off) is none of theirs, and a missing one
    (None, NaN) is none; a run with no reading has none here."""
    rows = sorted(
        (t.astimezone(UTC), float(v))
        for t, v in readings
        if v is not None and math.isfinite(v)
    )
    times = [t for t, _ in rows]
    out: list[tuple[datetime, float]] = []
    for a, b in sorted((a.astimezone(UTC), b.astimezone(UTC)) for a, b in runs):
        inside = rows[
            bisect.bisect_left(times, a) : bisect.bisect_left(times, b)
        ]
        if inside:
            out.append((a, inside[0][1]))
            out.extend(inside)
    return out


def book_steps_from_history(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    *,
    start: datetime,
    end: datetime,
    flow: Iterable[tuple[datetime, float]] = (),
    circulation: Iterable[tuple[datetime, datetime]] = (),
    circulation_flow: Iterable[tuple[datetime, float]] = (),
    inlet: Iterable[tuple[datetime, float]] = (),
    air: Iterable[tuple[datetime, float]] = (),
    params: HeaterParams | None = None,
) -> list[BookStep]:
    """A recorded history on the book's grid (``BOOK_GRID_S``), from
    ``start`` to ``end``: the heater's statuses (the probes, the
    compressor, either element) held until the next; the household
    meter's ``flow`` and ``circulation_flow`` held ``FLOW_HOLD``, 0
    past it; ``inlet`` (a probe) held ``INLET_HOLD``; ``air`` held
    until the next (the book's default without it). Flows are per
    minute and temperatures in the preferred units.

    A step inside a ``circulation`` run is circulating at its last flow
    reading, this run's or an earlier one's; with none yet, the meter's
    over ``CirculationParams.meter_share`` (all of it circulation), else
    the circulation's priced flow."""
    grid = _book_grid(start, end)
    statuses = sorted(
        ((t.astimezone(UTC), s) for t, s in readings), key=lambda r: r[0]
    )

    def of(
        f: Callable[[DeviceStatus], float],
    ) -> list[tuple[datetime, float]]:
        return [(t, f(s)) for t, s in statuses]

    def flag(f: Callable[[DeviceStatus], object]) -> list[bool]:
        return [
            bool(v) for v in _held(of(lambda s: float(bool(f(s)))), grid, None)
        ]

    heater = _Heater(
        upper=_held(
            of(
                lambda s: _from_device(
                    DeciCelsius(s.tank_upper_temperature_raw)
                )
            ),
            grid,
            None,
        ),
        lower=_held(
            of(
                lambda s: _from_device(
                    DeciCelsius(s.tank_lower_temperature_raw)
                )
            ),
            grid,
            None,
        ),
        compressor=flag(lambda s: s.comp_use),
        upper_element=flag(lambda s: s.heat_upper_use),
        lower_element=flag(lambda s: s.heat_lower_use),
    )
    return _book_steps_on(
        grid,
        heater,
        flow=flow,
        circulation=circulation,
        circulation_flow=circulation_flow,
        inlet=inlet,
        air=air,
        params=params,
        preferred=True,
    )


def book_steps_from_changes(
    rows: ChangeRows,
    *,
    start: datetime,
    end: datetime,
    flow: Iterable[tuple[datetime, float]] = (),
    circulation: Iterable[tuple[datetime, datetime]] = (),
    circulation_flow: Iterable[tuple[datetime, float]] = (),
    inlet: Iterable[tuple[datetime, float]] = (),
    air: Iterable[tuple[datetime, float]] = (),
    params: HeaterParams | None = None,
) -> list[BookStep]:
    """``book_steps_from_history`` from a heater's values' changes
    (``ChangeRows``) instead of its statuses: each value held until its
    next change. Like the rows, ``flow`` and ``circulation_flow`` are
    gal/min and ``inlet`` and ``air`` °F, whatever the preferred units.
    Without a compressor flag, the heat source says when the compressor
    runs, and it adds to the elements' flags, as in
    ``change_history``. Whether the heater was heard from over the span
    is the caller's (``book_from_changes``)."""
    grid = _book_grid(start, end)

    def held(changes: Changes) -> list[Any]:
        return _held(
            sorted(((t.astimezone(UTC), v) for t, v in changes), key=_at),
            grid,
            None,
        )

    def probe(changes: Changes) -> list[float | None]:
        return [
            None if v is None or not math.isfinite(float(v)) else float(v)
            for v in held(changes)
        ]

    def flag(changes: Changes) -> list[bool]:
        return [bool(v) for v in held(changes)]

    source = [-1 if v is None else int(v) for v in held(rows.heat_source)]
    pump = {int(HeatSource.HEATPUMP), int(HeatSource.HEATPUMP_HEATELEMENT)}
    element = {
        int(HeatSource.HEATELEMENT),
        int(HeatSource.HEATPUMP_HEATELEMENT),
    }
    heater = _Heater(
        upper=probe(rows.upper_f),
        lower=probe(rows.lower_f),
        compressor=(
            flag(rows.compressor_on)
            if rows.compressor_on
            # Without its own flag, the heat source says when it runs.
            else [v in pump for v in source]
        ),
        upper_element=[
            a or v in element
            for a, v in zip(flag(rows.upper_element_on), source, strict=True)
        ],
        lower_element=flag(rows.lower_element_on),
    )
    return _book_steps_on(
        grid,
        heater,
        flow=flow,
        circulation=circulation,
        circulation_flow=circulation_flow,
        inlet=inlet,
        air=air,
        params=params,
        preferred=False,
    )


def _at(row: tuple[datetime, Any]) -> datetime:
    return row[0]


def _book_steps_on(
    grid: list[datetime],
    heater: _Heater,
    *,
    flow: Iterable[tuple[datetime, float]],
    circulation: Iterable[tuple[datetime, datetime]],
    circulation_flow: Iterable[tuple[datetime, float]],
    inlet: Iterable[tuple[datetime, float]],
    air: Iterable[tuple[datetime, float]],
    params: HeaterParams | None,
    preferred: bool,
) -> list[BookStep]:
    """The book's steps on ``grid``: ``heater``'s columns with the
    meter, the circulation, the inlet and the air
    (``book_steps_from_history``), in the preferred units, or with
    ``preferred`` False the simulator's (°F, gal/min)."""
    p = (params if params is not None else default_params()).book_terms()
    terms = None if params is None else params.circulation

    def series(
        rows: Iterable[tuple[datetime, float]], to: Callable[[float], float]
    ) -> list[tuple[datetime, float]]:
        return sorted(
            (
                (t.astimezone(UTC), to(v) if preferred else v)
                for t, v in _finite(rows)
            ),
            key=lambda r: r[0],
        )

    upper, lower = heater.upper, heater.lower
    comp, up_el, lo_el = (
        heater.compressor,
        heater.upper_element,
        heater.lower_element,
    )
    meter = _held(series(flow, _volume_to_sim), grid, FLOW_HOLD)
    run_flow = _held(series(circulation_flow, _volume_to_sim), grid, FLOW_HOLD)
    probe = _held(series(inlet, _to_sim), grid, INLET_HOLD)
    amb = _held(series(air, _to_sim), grid, None)
    runs = sorted(
        (a.astimezone(UTC), b.astimezone(UTC)) for a, b in circulation
    )
    steps: list[BookStep] = []
    settled: float | None = None
    for i, at in enumerate(grid):
        u, lo, a_f, in_f = upper[i], lower[i], amb[i], probe[i]
        if u is None or lo is None:
            continue
        m = meter[i] or 0.0
        on = any(a <= at < b for a, b in runs)
        gpm = 0.0
        if on:
            if run_flow[i] is not None:
                settled = run_flow[i]
            if settled is not None:
                gpm = settled
            elif terms is not None and terms.meter_share > 0.0:
                gpm = m / terms.meter_share
            elif terms is not None:
                gpm = terms.flow_gpm
        steps.append(
            BookStep(
                seconds=float(BOOK_GRID_S),
                upper_f=u,
                lower_f=lo,
                flow_gpm=m,
                compressor_on=bool(comp[i]),
                element_on=bool(up_el[i]) or bool(lo_el[i]),
                ambient_f=a_f if a_f is not None else AMBIENT_DEFAULT_F,
                inlet_f=in_f if in_f is not None else p.inlet_default_f,
                circulating=on,
                circulation_gpm=gpm,
                inlet_measured=in_f is not None,
                lower_element=bool(lo_el[i]),
            )
        )
    return steps


def book_from_history(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    params: HeaterParams,
    *,
    at: datetime,
    flow: Iterable[tuple[datetime, float]],
    circulation: Iterable[tuple[datetime, datetime]] = (),
    circulation_flow: Iterable[tuple[datetime, float]] = (),
    inlet: Iterable[tuple[datetime, float]] = (),
    air: Iterable[tuple[datetime, float]] = (),
) -> Booked | None:
    """The tank's booked heat at ``at`` from what was recorded before
    it (``book.book_steps``), for ``simulate`` and ``time_to_ready``'s
    ``book=``: from the last ``max_anchor_age_h`` when that holds an
    anchor, else from the last ``history_h``, aged. None with no anchor
    in either.

    ``flow`` is the household meter's flow (per minute, the preferred
    volume) and must report at rest too: a silence over
    ``METER_MAX_GAP`` in the window (missing readings, None or NaN,
    count as silence) is refused, since it would read as a quiet full
    tank. ``circulation`` are its runs, with
    ``circulation_flow`` its own flow; ``inlet`` an inlet probe's
    readings; ``air`` the air where the heater stands. Draws are what
    the meter reads less circulation's share of it
    (``CirculationParams.meter_share``)."""
    at = at.astimezone(UTC)
    rows = list(readings)
    # A missing reading is none: it neither moves water nor shows the
    # meter reporting.
    flows = sorted((t.astimezone(UTC), v) for t, v in _finite(flow))
    runs = list(circulation)
    run_flow = list(circulation_flow)
    probe = list(inlet)
    airs = list(air)
    return _book_windows(
        lambda start: book_steps_from_history(
            rows,
            start=start,
            end=at,
            flow=flows,
            circulation=runs,
            circulation_flow=run_flow,
            inlet=probe,
            air=airs,
            params=params,
        ),
        flows,
        params,
        at,
    )


def book_from_changes(
    rows: ChangeRows,
    observed: Iterable[datetime],
    params: HeaterParams,
    *,
    at: datetime,
    flow: Iterable[tuple[datetime, float]],
    circulation: Iterable[tuple[datetime, datetime]] = (),
    circulation_flow: Iterable[tuple[datetime, float]] = (),
    inlet: Iterable[tuple[datetime, float]] = (),
    air: Iterable[tuple[datetime, float]] = (),
) -> Booked | None:
    """``book_from_history`` from a heater's values' changes (``rows``)
    instead of its statuses, with ``observed`` the instants it was heard
    from, as ``sim_calibrate.calibrate_changes`` takes them
    (``sim_home_assistant.read_heater_history`` reads both from Home
    Assistant). The same anchor search, and the same refusal of a
    silent meter. Like the rows, ``flow`` and ``circulation_flow`` are
    gal/min and ``inlet`` and ``air`` °F, whatever the preferred units.

    A value that holds writes no change, so only ``observed`` says the
    heater was heard: a silence between those instants longer than
    ``max_gap`` of them, or one of ``rows.outages``, is a span nobody
    saw, and no anchor before it counts (the heat that left meanwhile is
    unknown). The book is from after the last such span; None when the
    heater is not heard at ``at``, or there is no anchor since."""
    at = at.astimezone(UTC)
    heard = sorted(t for t in (t.astimezone(UTC) for t in observed) if t <= at)
    if not heard:
        return None
    gap = max_gap(heard)
    if at - heard[-1] > gap:
        return None
    since = heard[0]
    for a, b in [*silences(heard, gap), *rows.outages]:
        a, b = a.astimezone(UTC), b.astimezone(UTC)
        if a <= at:
            if b >= at:
                return None
            since = max(since, b)
    # A missing reading is none: it neither moves water nor shows the
    # meter reporting.
    flows = sorted((t.astimezone(UTC), v) for t, v in _finite(flow))
    runs = list(circulation)
    run_flow = list(circulation_flow)
    probe = list(inlet)
    airs = list(air)
    return _book_windows(
        lambda start: book_steps_from_changes(
            rows,
            start=start,
            end=at,
            flow=flows,
            circulation=runs,
            circulation_flow=run_flow,
            inlet=probe,
            air=airs,
            params=params,
        ),
        flows,
        params,
        at,
        since,
    )


def _book_windows(
    steps: Callable[[datetime], list[BookStep]],
    flows: Sequence[tuple[datetime, float]],
    params: HeaterParams,
    at: datetime,
    since: datetime | None = None,
) -> Booked | None:
    """The book at ``at`` from ``steps`` (the steps from an instant to
    ``at``): over the last ``max_anchor_age_h`` when that holds an
    anchor, else the last ``history_h``, neither from before ``since``.
    Raises ValueError for a meter (``flows``) silent over
    ``METER_MAX_GAP`` in the window."""
    p = params.book_terms()

    def booked(hours: float) -> Booked | None:
        start = at - timedelta(hours=hours)
        if since is not None:
            start = max(start, since)
        beats = [start, *(t for t, _ in flows if start <= t <= at), at]
        gap = max(b - a for a, b in itertools.pairwise(beats))
        if gap > METER_MAX_GAP:
            raise ValueError(
                f"the meter was silent for {gap}; the history is incomplete"
            )
        return book_steps(steps(start), p, params.circulation)

    found = booked(p.max_anchor_age_h)
    return found if found is not None else booked(p.history_h)


#: Readings further apart than ``GAP_SAMPLES`` times the record's usual
#: spacing, and at least ``MIN_GAP``, are a span nobody observed.
GAP_SAMPLES = 4
MIN_GAP = timedelta(minutes=5)


def max_gap(instants: Iterable[datetime]) -> timedelta:
    """The longest spacing between readings at ``instants`` still taken
    as observed: ``GAP_SAMPLES`` times their median spacing, and at
    least ``MIN_GAP``. A recorder sees a status every few seconds to
    every 30 s, so a stop and restart is far longer; an element run can
    be under a minute, so much longer could hide one."""
    steps = _spacings(instants)
    steps = np.sort(steps[steps > 0])
    if not len(steps):
        return MIN_GAP
    usual = timedelta(microseconds=int(steps[len(steps) // 2]) // 1000)
    return max(MIN_GAP, GAP_SAMPLES * usual)


def silences(
    instants: Iterable[datetime], gap: timedelta | None = None
) -> list[tuple[datetime, datetime]]:
    """The spans between consecutive ``instants`` longer than ``gap``
    (``max_gap`` of them by default): spans nobody observed."""
    import pandas as pd

    index = _instants(instants)
    if gap is None:
        gap = max_gap(index)
    ns = np.sort(index.as_unit("ns").asi8)
    (wide,) = np.nonzero(np.diff(ns) > gap.total_seconds() * 1e9)

    def instant(i: int) -> datetime:
        # A Timestamp, which is a datetime (never NaT: a real instant).
        return cast(datetime, pd.Timestamp(int(ns[i]), tz=UTC))

    return [(instant(i), instant(i + 1)) for i in wide.tolist()]


def _instants(instants: Iterable[datetime]) -> pd.DatetimeIndex:
    import pandas as pd

    return (
        instants
        if isinstance(instants, pd.DatetimeIndex)
        else pd.to_datetime(list(instants), utc=True)
    )


def _spacings(instants: Iterable[datetime]) -> np.ndarray:
    """The spacings between ``instants`` in time order, ns."""
    return np.diff(np.sort(_instants(instants).as_unit("ns").asi8))


def draw_frame(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    *,
    start: datetime,
    end: datetime,
    flow: Iterable[tuple[datetime, float]],
    circulation: Iterable[tuple[datetime, datetime]] = (),
) -> pd.DataFrame:
    """A metered record on ``sim.calibration``'s draw grid
    (``DRAW_GRID_S``), for ``clean_draws``: the household meter's
    ``flow`` (per minute, the preferred volume) held ``FLOW_HOLD``, 0
    past it; the probes, the compressor and either element held until
    the next status; ``circulating`` inside a ``circulation`` run."""
    import pandas as pd

    from nwp500.sim.calibration import DRAW_GRID_S

    start, end = start.astimezone(UTC), end.astimezone(UTC)
    grid: list[datetime] = []
    t = start
    while t <= end:
        grid.append(t)
        t += timedelta(seconds=DRAW_GRID_S)
    statuses = sorted(
        ((t.astimezone(UTC), s) for t, s in readings), key=lambda r: r[0]
    )

    def of(
        f: Callable[[DeviceStatus], float],
    ) -> list[float | None]:
        return _held([(t, f(s)) for t, s in statuses], grid, None)

    meter = _held(
        sorted((t.astimezone(UTC), _volume_to_sim(v)) for t, v in flow),
        grid,
        FLOW_HOLD,
    )
    runs = sorted(
        (a.astimezone(UTC), b.astimezone(UTC)) for a, b in circulation
    )
    nan = float("nan")
    return pd.DataFrame(
        {
            "flow_gpm": [m if m is not None else 0.0 for m in meter],
            "circulating": [any(a <= g < b for a, b in runs) for g in grid],
            "upper_f": [
                nan if v is None else v
                for v in of(
                    lambda s: _from_device(
                        DeciCelsius(s.tank_upper_temperature_raw)
                    )
                )
            ],
            "lower_f": [
                nan if v is None else v
                for v in of(
                    lambda s: _from_device(
                        DeciCelsius(s.tank_lower_temperature_raw)
                    )
                )
            ],
            "compressor_on": [
                bool(v) for v in of(lambda s: float(bool(s.comp_use)))
            ],
            "element_on": [
                bool(a) or bool(b)
                for a, b in zip(
                    of(lambda s: float(bool(s.heat_upper_use))),
                    of(lambda s: float(bool(s.heat_lower_use))),
                    strict=True,
                )
            ],
        },
        index=pd.DatetimeIndex(grid),
    )


def cold_supply(
    probe: Iterable[tuple[datetime, float]],
    *,
    at: datetime,
    flow: Iterable[tuple[datetime, float]],
    ticks: Iterable[datetime] | None = None,
    circulation: Iterable[tuple[datetime, datetime]] | None = (),
    window: timedelta | None = None,
) -> ColdSupply:
    """The mains as of ``at`` from an inlet probe's ``probe`` readings
    over recent long draws (``sim.cold_supply``), the probe and the
    meter's ``flow`` (per minute) in the preferred units. ``ticks`` are
    the instants water was drawn; by default, each flow reading at or
    above the draw line, each standing for the meter's own reporting
    interval. ``circulation`` are its runs: none (the default) for an
    installation without, None for runs not recorded (no estimate). A
    missing reading (NaN) is left out. ``window`` is how far back a long
    draw counts (``ColdSupplyParams.window_s`` by default). The estimate
    is degF: pass it on as ``environment(inlet=temperature(...))`` or
    with ``on_the_mains``."""
    return cold_supply_f(
        [(t, _to_sim(v)) for t, v in _finite(probe)],
        at=at,
        flow=[(t, _volume_to_sim(v)) for t, v in _finite(flow)],
        ticks=ticks,
        circulation=circulation,
        window=window,
    )


def cold_supply_f(
    probe: Iterable[tuple[datetime, float]],
    *,
    at: datetime,
    flow: Iterable[tuple[datetime, float]],
    ticks: Iterable[datetime] | None = None,
    circulation: Iterable[tuple[datetime, datetime]] | None = (),
    window: timedelta | None = None,
) -> ColdSupply:
    """``cold_supply`` in the simulator's units, the probe °F and the
    flow gal/min, whatever the preferred units: it reads no unit
    preference."""
    readings = [(t.astimezone(UTC), v) for t, v in _finite(probe)]
    flows = sorted((t.astimezone(UTC), v) for t, v in _finite(flow))
    p = ColdSupplyParams()
    if window is not None:
        p = replace(p, window_s=window.total_seconds())
    if ticks is not None:
        drawn = [t.astimezone(UTC) for t in ticks]
    else:
        drawn = [t for t, v in flows if v >= p.draw_gpm]
        # Each reading stands for the meter's own interval, whatever its
        # cadence: a meter reporting every minute closes a minute.
        cadence = _cadence_s([t for t, _ in flows])
        if cadence is not None and cadence > p.tick_s:
            p = replace(
                p,
                tick_s=cadence,
                tick_gap_s=max(p.tick_gap_s, 1.5 * cadence),
            )
    return plateau_t_cold(
        readings,
        drawn,
        None
        if circulation is None
        else [(a.astimezone(UTC), b.astimezone(UTC)) for a, b in circulation],
        at.astimezone(UTC),
        p,
        flow=flows,
    )


def _cadence_s(times: Sequence[datetime]) -> float | None:
    """The median spacing of consecutive readings, s, those a reporting
    gap (over 10 min) apart left out; None with fewer than two."""
    gaps = [
        (b - a).total_seconds()
        for a, b in itertools.pairwise(times)
        if 0 < (b - a).total_seconds() <= 600
    ]
    return float(np.median(gaps)) if gaps else None
