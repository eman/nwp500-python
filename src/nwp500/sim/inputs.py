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

from datetime import UTC, datetime, timedelta
from typing import Annotated, Self
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
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
    #: Whether the compressor is running a recovery.
    compressor_running: bool = False
    #: Whether a heating element is on, and since when (None: unknown).
    element_running: bool = False
    element_running_since: Instant | None = None
    #: The heater's own count of the energy still needed to reach its
    #: recovery target (``DeviceStatus.energy_to_setpoint``), Wh; None:
    #: not read (an injected state's is never its own).
    energy_to_setpoint_wh: float | None = None


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
    #: When the tank last heated, by the compressor or an element.
    heated_at: Instant | None = None


class ReservationEntry(_Value):
    """One weekly reservation, as the device stores it."""

    enabled: bool = True
    #: The days it fires on: the device's week mask (Sunday bit 7,
    #: Monday bit 6, ... Saturday bit 1).
    week: Mask
    hour: Annotated[int, Field(ge=0, le=23)]
    minute: Annotated[int, Field(ge=0, le=59)]
    mode: Mode
    #: The setpoint it writes, half-degrees Celsius (the device's
    #: ``param``).
    setpoint_half_c: int


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
    #: ``DrawParams.inlet_temp_f``.
    inlet_f: float | None = None

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


class Draw(_Value):
    """Hot water drawn: ``gallons`` as a meter on the delivered (mixed)
    line counts them, at ``at``. The tank gives up the hot share through
    the mixing valve (``DrawParams``) and refills at the inlet."""

    at: Instant
    gallons: Annotated[float, Field(gt=0.0)]
    #: For an expected draw (``sim.draw_forecast``), whose ``gallons``
    #: is fractional, the slot's own per-draw volume: what the draw's
    #: domain is judged against. None: ``gallons`` itself.
    per_draw_gal: Annotated[float, Field(gt=0.0)] | None = None


class DrawWindow(_Value):
    """A span the caller expects water to be drawn in, a shower or a
    bath, which the result judges: the tank and the deliverable gallons
    at its onset, and whether the delivered water ran cold over it
    (``SimulationResult.windows``). Its edges are read exactly."""

    start: Instant
    end: Instant
    #: Delivered gallons the window is expected to draw, if known: the
    #: result's ``margin_gal`` is the deliverable gallons less it.
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
    #: The runs are known for a span starting by this instant, and not
    #: after it (nothing charged there). None: known throughout.
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


class Commands(_Value):
    """Device commands under evaluation."""

    #: Setpoint and mode writes, at their instants.
    writes: tuple[Write, ...] = ()
    #: A reservation schedule written at the start, in place of the
    #: heater's. None keeps the heater's.
    reservations: tuple[ReservationEntry, ...] | None = None
    #: The TOU switch, set at the start. None keeps the heater's.
    tou_enabled: bool | None = None


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
