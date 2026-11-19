"""What a simulation is asked: a ``Scenario`` and its parts.

Every part is a frozen pydantic model, so a scenario is a value: a
"what if" is ``scenario.model_copy(update=...)``, and the same scenario
replays identically. Nothing here reads the device, the network or the
clock; a client builds a scenario from what it fetched
(``nwp500.sim_adapters`` builds one from the library's models).

Units:

- Temperatures of the tank, the settings, the ambient and the inlet
  are in °F, the unit the physics are fitted in.
- Schedules are in the device's own terms: a reservation's setpoint in
  half-degrees Celsius as the device stores it (``param``), day and
  season masks as the device encodes them, and modes as
  ``DhwOperationSetting`` values (1 Heat Pump, 2 Electric, 3 Energy
  Saver, 4 High Demand, 5 Vacation, 6 Power Off).
- Instants are timezone-aware, and held in UTC (``Instant``).
  ``Scenario.tz`` is the zone the schedules' local times are laid out
  in.
"""

import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Any, Self, cast
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

#: The device's operation modes (``DhwOperationSetting``).
HEAT_PUMP = 1
ELECTRIC = 2
ENERGY_SAVER = 3
HIGH_DEMAND = 4
VACATION = 5
POWER_OFF = 6

Mode = Annotated[int, Field(ge=HEAT_PUMP, le=POWER_OFF)]

#: A reservation entry's mode (``ReservationMode``), its own numbering:
#: 1-4 are the operation modes of the same ids, 5 is Power Off, and 0 an
#: unused slot. Any id the device stores is accepted (an earlier version
#: of the library wrote 6); only 1-4 are modelled.
EntryMode = Annotated[int, Field(ge=0, le=255)]


def _utc(at: datetime) -> datetime:
    return at.astimezone(UTC)


#: An aware instant, held in UTC: the same instant given in any zone is
#: the same value, and a span added to it is elapsed time, not the wall
#: clock's (a local start across a daylight-saving change would gain or
#: lose an hour). The schedules' local times are laid out in
#: ``Scenario.tz``.
type Instant = Annotated[AwareDatetime, AfterValidator(_utc)]
Mask = Annotated[int, Field(ge=0, le=0xFFFF)]


class _Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HeaterState(_Value):
    """The tank and what is heating it, at the scenario's start."""

    #: The upper and lower tank thermistors, °F.
    upper_f: float
    lower_f: float
    #: The tank's layers, °F, the bottom first, as its history left
    #: them (``history.replay``): as many as the parameters lay out
    #: (``TankParams.layers``). None: the simulator makes them of the
    #: two probes, and says ``tank_profile_estimated``.
    layers_f: tuple[float, ...] | None = None
    #: Whether the compressor is running a recovery.
    compressor_running: bool = False
    #: Whether a heating element is on, and since when (None: unknown).
    element_running: bool = False
    element_running_since: Instant | None = None
    #: The heater's own count of the energy still needed to reach its
    #: recovery target (``DeviceStatus.energy_to_setpoint``), Wh; None:
    #: not read (an injected state's is never its own).
    energy_to_setpoint_wh: float | None = None
    #: Where a simulation that ended at this scenario's start left the
    #: heater (``SimulationResult.end_state``): what it keeps beyond the
    #: probes and the layers, so the walk goes on as if unbroken.
    #: Opaque JSON text; kept as given. With it the compressor, the
    #: element and ``History`` are its, not these flags'. None: the walk
    #: starts afresh.
    resume: str | None = None


class Settings(_Value):
    """The heater's settings at the start."""

    #: The DHW setpoint, °F.
    setpoint_f: float
    #: The operation mode, a ``DhwOperationSetting`` value.
    mode: Mode = HEAT_PUMP
    #: The lower thermistor's compressor start threshold
    #: (``hp_lower_on_temp_setting``), °F. None: the heater starts no
    #: recovery on the lower zone.
    hp_lower_on_f: float | None = None
    #: The lower thermistor's compressor stop threshold
    #: (``hp_lower_off_temp_setting``), °F: what a heat-pump recovery
    #: heats the lower zone to. None: not known.
    hp_lower_off_f: float | None = None
    #: The upper thermistor's compressor start threshold
    #: (``hp_upper_on_temp_setting``), °F: raised to about the setpoint
    #: while a TOU window is in force. None: not known.
    hp_upper_on_f: float | None = None


class History(_Value):
    """Facts about the time before the start that change what happens
    after it. Each is optional; the result names a default it used."""

    #: When the compressor last stopped: the restart lockout runs from
    #: it. None: no lockout is in force at the start.
    compressor_stopped_at: Instant | None = None


#: A reservation entry's fields as the device names them (the library's
#: ``nwp500.models.ReservationEntry``, the entries
#: ``update_reservations`` writes), in the device's order, each with
#: the simulator's name for it. The values are the same but
#: ``enable``'s: the device's 2 (on) or 1 (off) for ``enabled``, any
#: value other than 2 read as off.
DEVICE_ENTRY_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        "enable": "enabled",
        "week": "week",
        "hour": "hour",
        "min": "minute",
        "mode": "mode",
        "param": "setpoint_half_c",
    }
)
#: The device's ``enable`` values.
DEVICE_ON = 2
DEVICE_OFF = 1
#: The fields only one of the two forms names.
_DEVICE_ONLY = frozenset(DEVICE_ENTRY_FIELDS) - set(
    DEVICE_ENTRY_FIELDS.values()
)
_SIM_ONLY = frozenset(DEVICE_ENTRY_FIELDS.values()) - set(DEVICE_ENTRY_FIELDS)


def _device_enabled(enable: object) -> bool:
    """The device's ``enable`` as ``enabled``: 2 is on and any other
    whole number off, as the library reads it (the device writes 1). A
    bool is refused: ``True`` is 1, which reads as off."""
    if isinstance(enable, bool) or not isinstance(enable, int):
        raise ValueError(
            f"enable is the device's {DEVICE_ON} (on) or {DEVICE_OFF} (off), "
            f"got {enable!r}"
        )
    return enable == DEVICE_ON


def _from_device(fields: Mapping[str, Any]) -> dict[str, Any]:
    """A device entry's fields in the simulator's names."""
    missing = [k for k in DEVICE_ENTRY_FIELDS if k not in fields]
    if missing:
        raise ValueError(
            "a device entry has "
            + ", ".join(DEVICE_ENTRY_FIELDS)
            + "; missing "
            + ", ".join(missing)
        )
    both = sorted(_SIM_ONLY & set(fields))
    if both:
        raise ValueError(
            "an entry is in the device's fields or the simulator's, not "
            f"both: {', '.join(both)} given with enable, min and param"
        )
    out = {DEVICE_ENTRY_FIELDS.get(k, k): v for k, v in fields.items()}
    out["enabled"] = _device_enabled(fields["enable"])
    return out


class ReservationEntry(_Value):
    """One weekly reservation, as the device stores it.

    It takes the simulator's fields or the device's (``enable``,
    ``week``, ``hour``, ``min``, ``mode``, ``param``, all six), as a
    mapping or as the library's ``nwp500.models.ReservationEntry``:
    :data:`DEVICE_ENTRY_FIELDS` maps one to the other.
    :meth:`from_device` reads the device's form and :meth:`to_device`
    gives it back."""

    enabled: bool = True
    #: The days it fires on: the device's week mask (Sunday bit 7,
    #: Monday bit 6, ... Saturday bit 1).
    week: Mask
    hour: Annotated[int, Field(ge=0, le=23)]
    minute: Annotated[int, Field(ge=0, le=59)]
    mode: EntryMode
    #: The setpoint it writes, half-degrees Celsius (the device's
    #: ``param``).
    setpoint_half_c: int

    @model_validator(mode="before")
    @classmethod
    def _device_form(cls, data: Any) -> Any:
        """An entry in the device's fields, read into the simulator's."""
        if isinstance(data, Mapping):
            fields = cast(Mapping[str, Any], data)
            if _DEVICE_ONLY.isdisjoint(fields):
                return fields
            return _from_device(fields)
        if not isinstance(data, BaseModel) or isinstance(data, cls):
            return data
        if all(hasattr(data, k) for k in DEVICE_ENTRY_FIELDS):
            return _from_device(
                {k: getattr(data, k) for k in DEVICE_ENTRY_FIELDS}
            )
        return data

    @classmethod
    def from_device(cls, entry: Mapping[str, Any] | BaseModel) -> Self:
        """The entry the device holds as ``entry``: a mapping of its six
        fields (``enable``, ``week``, ``hour``, ``min``, ``mode``,
        ``param``), as the device reports an entry and
        ``update_reservations`` writes one, or the library's
        ``nwp500.models.ReservationEntry``. ``enable`` 2 is on and any
        other whole number off; the rest are taken as they are
        (``DEVICE_ENTRY_FIELDS``). Raises ``ValueError`` for an entry
        missing one of the six, an ``enable`` that is not a whole number,
        or a field out of its range."""
        if isinstance(entry, Mapping):
            fields: Mapping[str, Any] = entry
        else:
            fields = {
                k: getattr(entry, k)
                for k in DEVICE_ENTRY_FIELDS
                if hasattr(entry, k)
            }
        return cls.model_validate(_from_device(fields))

    def to_device(self) -> dict[str, int]:
        """The entry in the device's fields, as ``update_reservations``
        writes it: ``enable`` 2 (on) or 1 (off), ``week``, ``hour``,
        ``min``, ``mode`` and ``param``."""
        return {
            "enable": DEVICE_ON if self.enabled else DEVICE_OFF,
            "week": self.week,
            "hour": self.hour,
            "min": self.minute,
            "mode": self.mode,
            "param": self.setpoint_half_c,
        }


class TouPeriod(_Value):
    """One TOU price period, as the device stores it."""

    #: The months it applies in: bit 0 January ... bit 11 December.
    season: Mask
    #: The days it applies on (Sunday bit 7 ... Saturday bit 1).
    week: Mask
    start_hour: Annotated[int, Field(ge=0, le=23)]
    start_minute: Annotated[int, Field(ge=0, le=59)]
    #: The period's last minute, inclusive (23:59 ends the day).
    end_hour: Annotated[int, Field(ge=0, le=23)]
    end_minute: Annotated[int, Field(ge=0, le=59)]
    #: The encoded prices (divide by ``10 ** decimal_point``).
    price_min: int = 0
    price_max: int = 0
    decimal_point: int = 0


class Schedules(_Value):
    """The heater's schedules: its reservations and its TOU."""

    reservations: tuple[ReservationEntry, ...] = ()
    #: The reservation schedule's own switch.
    reservations_enabled: bool = True
    tou_periods: tuple[TouPeriod, ...] = ()
    #: Whether TOU is on.
    tou_enabled: bool = False
    #: The TOU switch's changes over the span, ``(at, on)``, as the
    #: heater recorded them (``sim_adapters.replay``): a window is in
    #: force only while it is on. The switch at the start is
    #: ``tou_enabled`` (or ``Commands.tou_enabled``).
    tou_switches: tuple[tuple[Instant, bool], ...] = ()


#: An ambient reading: the instant and the air temperature, °F.
AmbientPoint = tuple[Instant, float]


def _when(reading: tuple[datetime, float]) -> datetime:
    return reading[0]


class Environment(_Value):
    """Where the heater sits."""

    #: The air temperature at the heater's intake, °F: one value for
    #: the whole span, or readings, which are interpolated between and
    #: held past their ends.
    ambient_f: float | tuple[AmbientPoint, ...]
    #: Relative humidity, percent.
    humidity: Annotated[float, Field(ge=0.0, le=100.0)] = 50.0
    #: The inlet (mains) water temperature, °F. None: the parameters'
    #: mains on each day, as each draw meets it (``DrawParams.mains_on``).
    inlet_f: float | None = None
    #: ``ambient_f`` comes from the heater's own reading while its
    #: compressor was idle, its cabinet's, less the cabinet's measured
    #: warmth (``sim_adapters.IDLE_CABINET_WARM_F``, 6.2 °F).
    ambient_cabinet: bool = False

    @property
    def ambient_defaulted(self) -> bool:
        """Whether no usable air reading was given (a missing value, or
        readings all missing), so the simulation runs at its default
        air (``units.DEFAULT_AMBIENT_F``)."""
        a = self.ambient_f
        if isinstance(a, tuple):
            return not any(math.isfinite(v) for _, v in a)
        return not math.isfinite(a)

    @field_validator("ambient_f")
    @classmethod
    def _readings(
        cls, v: float | tuple[AmbientPoint, ...]
    ) -> float | tuple[AmbientPoint, ...]:
        if isinstance(v, tuple):
            if not v:
                raise ValueError("ambient readings are empty")
            return tuple(sorted(v, key=_when))
        return v


#: A draw over time is taken at each whole minute of it: the
#: stratified walk's step while water moves
#: (``physics.stratified.ACTIVE_STEP``).
DRAW_STEP = timedelta(minutes=1)


class Draw(_Value):
    """Hot water drawn: ``gallons`` as a meter on the delivered (mixed)
    line counts them, from ``at`` for ``duration_s`` at an even flow
    (``pieces``). The tank gives up the hot share through the mixing
    valve (``DrawParams``) and refills at the inlet."""

    at: Instant
    gallons: Annotated[float, Field(gt=0.0)]
    #: For an expected draw (``sim.draw_forecast``), whose ``gallons``
    #: is fractional, the slot's own per-draw volume: what the draw's
    #: domain is judged against. None: ``gallons`` itself.
    per_draw_gal: Annotated[float, Field(gt=0.0)] | None = None
    #: How long it runs, s, up to a day. 0: all at ``at``.
    duration_s: Annotated[
        float, Field(ge=0.0, le=86400.0, allow_inf_nan=False)
    ] = 0.0

    @property
    def flow_gpm(self) -> float | None:
        """Its flow, gal/min: ``gallons`` over ``duration_s`` (an
        expected draw's rate cancels: its per-draw volume over its
        per-draw time). None for a draw all at ``at``."""
        if self.duration_s <= 0.0:
            return None
        return self.gallons / (self.duration_s / 60.0)

    def pieces(self) -> tuple[tuple[datetime, float], ...]:
        """The draw as the walk takes it, ``(instant, gallons)``: at
        ``at`` and at each whole minute of the clock before its end
        (the walk's step while water moves), each the gallons of the
        span to the next, so a draw over several minutes meets the
        heating between them."""
        if self.duration_s <= 0.0:
            return ((self.at, self.gallons),)
        end = self.at + timedelta(seconds=self.duration_s)
        gpm = self.gallons / (self.duration_s / 60.0)
        cuts = [self.at]
        t = self.at.replace(second=0, microsecond=0) + DRAW_STEP
        while t < end:
            cuts.append(t)
            t += DRAW_STEP
        out: list[tuple[datetime, float]] = []
        left = self.gallons
        for a, b in zip(cuts, [*cuts[1:], end], strict=True):
            g = left if b == end else gpm * (b - a).total_seconds() / 60.0
            left -= g
            out.append((a, g))
        return tuple(out)


class DrawWindow(_Value):
    """A span the caller expects water to be drawn in, a shower or a
    bath, which the result judges: the tank and the deliverable gallons
    at its onset, and whether the delivered water ran cold over it
    (``SimulationResult.windows``). Its edges are read exactly."""

    start: Instant
    end: Instant
    #: Gallons the window is expected to draw, if known, as the meter
    #: reads them, a ``Draw``'s ``gallons`` (a forecast's, an
    #: ensemble's): the result's ``expected_gal`` is them delivered
    #: at the reading at the window's start (``DrawParams.delivered_gal``,
    #: the same at ``meter_reads`` 1 with no ``meter_reads_since``) and
    #: its ``margin_gal`` the deliverable gallons less those.
    expected_gal: Annotated[float, Field(ge=0.0)] | None = None
    #: For a draw forecast's window (``draw_forecast.forecast_loads``):
    #: the draws it expects to start in it, fractional, and when its
    #: long draws end with them first (the worst case), carried to the
    #: result as they are. None otherwise.
    expected_count: Annotated[float, Field(ge=0.0)] | None = None
    draws_until: Instant | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("a draw window ends after it starts")
        return self


class CirculationRun(_Value):
    """A run of an installation's circulation of hot water through its
    own plumbing (``sim.circulation``)."""

    start: Instant
    end: Instant

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("a circulation run ends after it starts")
        return self


class Loads(_Value):
    """The water drawn over the span, the windows to judge, and any
    circulation."""

    draws: tuple[Draw, ...] = ()
    windows: tuple[DrawWindow, ...] = ()
    #: The installation's circulation runs, as instants (a weekly
    #: schedule laid out by ``sim_adapters.circulation``, a record, or a
    #: run on demand); they need ``HeaterParams.circulation``. None: no
    #: circulation, and nothing is charged. An empty tuple is a circuit
    #: known to be quiet.
    circulation: tuple[CirculationRun, ...] | None = None
    #: The runs are known as far as this instant: one starting after it
    #: is not known and charges nothing, one under way at it is charged
    #: whole. None: known throughout.
    circulation_known_until: Instant | None = None


class Write(_Value):
    """A setpoint or mode write at an instant, as an app or an
    integration makes it."""

    at: Instant
    setpoint_f: float | None = None
    mode: Mode | None = None
    id: str | None = None

    @model_validator(mode="after")
    def _sets_something(self) -> Self:
        if self.setpoint_f is None and self.mode is None:
            raise ValueError("a write sets a setpoint, a mode, or both")
        return self


class VacationCommand(_Value):
    """Vacation for ``days`` days, set at the start (a plan's
    ``vacation`` command)."""

    #: 1-99, as the device takes them.
    days: Annotated[StrictInt, Field(ge=1, le=99)]


class PowerCommand(_Value):
    """The heater turned on or off at the start (a plan's ``power``
    command)."""

    on: StrictBool


class AntiLegionellaCommand(_Value):
    """The anti-legionella cycle switched on or off at the start (a
    plan's ``anti_legionella`` command)."""

    enabled: StrictBool
    #: Days between cycles, 1-30, as the device takes them; given only
    #: with ``enabled``.
    period_days: Annotated[StrictInt, Field(ge=1, le=30)] | None = None

    @model_validator(mode="after")
    def _period_when_enabled(self) -> Self:
        if self.period_days is not None and not self.enabled:
            raise ValueError("period_days is given only with enabled true")
        return self


class DemandResponseCommand(_Value):
    """Demand response switched on or off at the start (a plan's
    ``demand_response`` command)."""

    enabled: StrictBool


class Commands(_Value):
    """Device commands under evaluation.

    Besides ``writes``, each is set at the start. A plan's commands
    (``sim.profile.COMMAND_KEYS``) are taken as they are: ``tou``
    (``{"enabled": ...}``) is ``tou_enabled``. The result's ``reasons``
    name each command the simulation does not model
    (:doc:`/reference/simulator-inputs`)."""

    #: Setpoint and mode writes, at their instants.
    writes: tuple[Write, ...] = ()
    #: A reservation schedule written at the start, in place of the
    #: heater's. None keeps the heater's.
    reservations: tuple[ReservationEntry, ...] | None = None
    #: The TOU switch, set at the start. None keeps the heater's.
    tou_enabled: bool | None = None
    #: Vacation from the start. None: no vacation command.
    vacation: VacationCommand | None = None
    #: The heater turned on or off at the start. None: no power command.
    power: PowerCommand | None = None
    #: The anti-legionella cycle switched at the start. None: no command.
    anti_legionella: AntiLegionellaCommand | None = None
    #: Demand response switched at the start. None: no command.
    demand_response: DemandResponseCommand | None = None

    @model_validator(mode="before")
    @classmethod
    def _plan_tou(cls, data: Any) -> Any:
        """A plan's ``tou`` command as ``tou_enabled``
        (``commands_in_simulator_names``)."""
        if not isinstance(data, Mapping):
            return data
        return commands_in_simulator_names(cast(Mapping[str, Any], data))


def commands_in_simulator_names(commands: Mapping[str, Any]) -> dict[str, Any]:
    """A ``Commands`` mapping with a plan's ``tou`` command,
    ``{"enabled": ...}``, as ``tou_enabled``; the rest as given. Raises
    ``ValueError`` for both given in it (``tou_enabled`` not None), or
    a ``tou`` of any other shape. Layers merged key by key
    (``sim.codec.merge``) are each put in these names first, so a
    layer's ``tou`` replaces a ``tou_enabled`` under it."""
    fields = dict(commands)
    if "tou" not in fields:
        return fields
    tou = fields.pop("tou")
    if fields.get("tou_enabled") is not None:
        raise ValueError("give tou or tou_enabled, not both")
    shape: Mapping[str, Any] = (
        cast(Mapping[str, Any], tou) if isinstance(tou, Mapping) else {}
    )
    enabled: object = (
        shape.get("enabled") if set(shape) == {"enabled"} else None
    )
    if not isinstance(enabled, bool):
        raise ValueError('tou is {"enabled": true} or {"enabled": false}')
    fields["tou_enabled"] = enabled
    return fields


class Scenario(_Value):
    """One question for the simulator: the heater, where it is, what
    is drawn from it and what it is told, from ``start`` for
    ``horizon``."""

    start: Instant
    horizon: timedelta
    #: The IANA zone the schedules' local times are in.
    tz: str
    state: HeaterState
    settings: Settings
    history: History = History()
    schedules: Schedules = Schedules()
    environment: Environment
    loads: Loads = Loads()
    commands: Commands = Commands()

    @field_validator("horizon")
    @classmethod
    def _positive(cls, v: timedelta) -> timedelta:
        if v <= timedelta(0):
            raise ValueError("horizon must be positive")
        return v

    @field_validator("tz")
    @classmethod
    def _zone(cls, v: str) -> str:
        ZoneInfo(v)  # raises for an unknown zone
        return v

    @property
    def until(self) -> datetime:
        """The span's end: ``start + horizon``."""
        return self.start + self.horizon

    @model_validator(mode="after")
    def _in_span(self) -> Self:
        for w in self.commands.writes:
            if not self.start <= w.at < self.until:
                raise ValueError(
                    f"write at {w.at.isoformat()} is outside the span"
                )
        return self
