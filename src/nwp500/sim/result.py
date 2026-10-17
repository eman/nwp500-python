"""What the simulator answers: ``SimulationResult``, ``RecoveryResult``
and ``Trace``.

Each carries the engine's own values (``nwp500.sim.engine``'s path
points, heating intervals, writes and modes) with the reasons the walk
gave and every default the answer used, so a caller can tell an input
it gave from one it was assumed.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from nwp500.sim.book import BookedPath
from nwp500.sim.delivery import DrawWindowResult
from nwp500.sim.engine import (
    HeatingInterval,
    ModeInterval,
    ModeWrite,
    PathPoint,
    Simulation,
    Write,
    energy_by_slot,
    energy_by_source,
)
from nwp500.sim.physics.element import ModePlan
from nwp500.sim.tank_physics import Point


@dataclass(frozen=True)
class SimulationResult:
    """A scenario walked from its start to its end."""

    start: datetime
    until: datetime
    #: The engine's walk, whole.
    simulation: Simulation
    #: Why the answer may be less than it seems: the walk's own reasons
    #: and the inputs it could not model.
    reasons: tuple[str, ...]
    #: Each default the answer used, as ``name=value``.
    defaults_used: tuple[str, ...]
    #: The delivered water's temperature at each element of ``points``,
    #: °F: the booked state's with a heat book, the upper zone's on the
    #: same delivered line without one (``sim.delivery``).
    delivery: tuple[float, ...] = ()
    #: The scenario's draw windows as the walk found them
    #: (``Loads.windows``).
    windows: tuple[DrawWindowResult, ...] = ()
    #: The heat book at each element of ``points``, when the walk had
    #: one (``sim.book``).
    booked: BookedPath | None = field(default=None, repr=False)
    #: With ``draw_out_of_domain`` in ``reasons``: the first instant from
    #: which the largest draw would be outside the draw terms' fitted
    #: range to the end (``DrawParams.domain_upper_f``); None when the
    #: walk ends in range.
    draw_out_of_domain_at: datetime | None = None

    @property
    def points(self) -> list[PathPoint]:
        """The tank along the walk: both zones, the setpoint, whether
        it is heating, the energy put in and the mode."""
        return self.simulation.points

    @property
    def heating(self) -> list[HeatingInterval]:
        """Each heating interval: its start and cause, its source
        (compressor or element), its end and why, its target, whether
        the TOU cap stopped it, and its energy."""
        return self.simulation.heating

    @property
    def writes(self) -> list[Write]:
        """The setpoint writes and reservation firings, as they landed."""
        return self.simulation.writes

    @property
    def mode_writes(self) -> list[ModeWrite]:
        """The mode writes, as they landed: taken, held or withdrawn."""
        return self.simulation.mode_writes

    @property
    def modes(self) -> list[ModeInterval]:
        """The mode in force over each part of the walk."""
        return self.simulation.modes

    @property
    def input_wh(self) -> float | None:
        """The electricity put in over the walk, Wh, both sources. None
        when an interval's energy could not be priced."""
        total = 0.0
        for h in self.simulation.heating:
            if h.input_wh is None:
                return None
            total += h.input_wh
        return total

    def energy_by_slot(
        self, slot: timedelta = timedelta(hours=1)
    ) -> list[tuple[datetime, float | None]]:
        """Electricity per clock-aligned ``slot``, Wh: ``(slot start,
        Wh)``, None where an unpriced interval touches the slot."""
        return energy_by_slot(self.simulation, slot)

    def energy_by_source(
        self, slot: timedelta = timedelta(hours=1)
    ) -> list[tuple[datetime, float | None, float]]:
        """``energy_by_slot`` by source: ``(slot start, compressor Wh,
        element Wh)``."""
        return energy_by_source(self.simulation, slot)


@dataclass(frozen=True)
class RecoveryResult:
    """The first heating interval from an instant: "when will the tank
    be hot?"."""

    at: datetime
    #: The interval, or None when none begins within the horizon.
    interval: HeatingInterval | None
    #: The tank from ``at`` to the interval's end.
    path: tuple[PathPoint, ...]
    reasons: tuple[str, ...]
    defaults_used: tuple[str, ...]

    @property
    def ready_at(self) -> datetime | None:
        """When the interval ends: the target reached, or the stop that
        ended it (``interval.stop``)."""
        return None if self.interval is None else self.interval.end

    @property
    def minutes(self) -> float | None:
        """Minutes from ``at`` to ``ready_at``."""
        if self.ready_at is None:
            return None
        return (self.ready_at - self.at).total_seconds() / 60.0


@dataclass(frozen=True)
class Trace:
    """The tank coasting, with no heating: standby loss and draws, and,
    given the settings, when the heater would start itself."""

    points: tuple[Point, ...]
    defaults_used: tuple[str, ...]
    #: When the heater's own trigger fires on the coast, and which; None
    #: when it does not before the end, or without settings.
    starts_at: datetime | None = None
    trigger: str | None = None
    #: The lower trigger was held (the upper zone at the setpoint, or a
    #: TOU window), which moved or dropped the start.
    start_held: bool = False
    #: The lower zone at the end less ``hp_lower_on``, °F: how far above
    #: its start threshold the coast leaves it; None without settings.
    lower_margin_f: float | None = None
    reasons: tuple[str, ...] = ()
    #: As ``SimulationResult.draw_out_of_domain_at``.
    draw_out_of_domain_at: datetime | None = None
    #: The delivered gallons drawn over the coast, and the heat they
    #: carried off the tank, Wh (after the mixing valve); None with no
    #: draws given.
    draw_volume_gal: float | None = None
    draw_heat_wh: float | None = None
    #: The minutes circulation ran over the coast and the heat it took
    #: from the zones, Wh; None with no circulation given (an empty run
    #: list is known-quiet: 0).
    circulation_minutes: float | None = None
    circulation_heat_wh: float | None = None
    #: The mean air at the heater over the coast, °F, and its length.
    ambient_mean_f: float | None = None
    hours: float = 0.0


@dataclass(frozen=True)
class ElementModeResult:
    """A recovery projected in an element mode from an instant
    (``physics.element.mode_plan``), and whether a mode write can take
    then."""

    starts_at: datetime
    plan: ModePlan
    #: False while heating is disabled (Vacation, Power Off) or a TOU
    #: window is in force, when a mode write may not take effect.
    reachable: bool
    #: Why not, when not.
    unreachable_reason: str | None = None
