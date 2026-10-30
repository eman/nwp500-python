"""What the simulator answers: ``SimulationResult``, ``RecoveryResult``
and ``Trace``.

Each carries the engine's own values (``nwp500.sim.engine``'s path
points, heating intervals, writes and modes) with the reasons the walk
gave and every default the answer used, so a caller can tell an input
it gave from one it was assumed.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

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
from nwp500.sim.inputs import HeaterState, History, Settings
from nwp500.sim.physics.element import HeaterMode
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
    #: °F: the top layer's water through the mixing valve
    #: (``delivery.delivery_f``).
    delivery: tuple[float, ...] = ()
    #: The scenario's draw windows as the walk found them
    #: (``Loads.windows``).
    windows: tuple[DrawWindowResult, ...] = ()
    #: With ``draw_out_of_domain`` in ``reasons``: the first instant from
    #: which the largest draw would be outside the draw terms' fitted
    #: range to the end (``DrawParams.domain_upper_f``); None when the
    #: walk ends in range.
    draw_out_of_domain_at: datetime | None = None
    #: The heater at ``until``, for a scenario from there to go on from
    #: (its ``state``, ``history`` and ``settings``): the probes and the
    #: layers where the walk ended, what was running, and what the
    #: heater keeps beyond them (``HeaterState.resume``). The settings
    #: are the setpoint and the mode in force then; a scenario given
    #: others has them written at its start.
    end_state: HeaterState | None = None
    end_history: History | None = None
    end_settings: Settings | None = None

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
class Forecast:
    """When a heat-pump recovery must start to have the tank ready at a
    target time (``api.forecast``), and the recovery itself.

    ``status``: ``ok``; ``partial_charge`` (a lower-zone target was
    asked for); ``low_confidence`` (a model served it under
    ``LOW_CONFIDENCE_FLOOR``); ``infeasible`` (it cannot be ready in
    time: it starts now, ``ready_at`` is when it ends, and
    ``shortfall_minutes`` how late); ``no_heating_required`` (the tank is
    already at its target); ``not_scheduled`` (heating is disabled:
    ``duration_minutes`` stands alone, with no start or end).
    """

    status: str
    start_at: datetime | None
    ready_at: datetime | None
    duration_minutes: float
    confidence: float
    #: The lower zone's target the recovery heats to, °F.
    target_f: float
    feasible: bool
    shortfall_minutes: float | None
    #: The integrator's own duration beside a model's; None when the
    #: physics is not usable as an estimate.
    physics_estimate_minutes: float | None
    #: What served the duration: ``physics``, ``model`` or
    #: ``no_heating_required``.
    estimator: str
    #: The tank where the recovery starts, °F, and the heater's own
    #: energy count then (None unless read live).
    upper_f_at_start: float
    lower_f_at_start: float
    energy_to_setpoint_wh: float | None
    #: A zero counter inside a TOU window: the heater has met its
    #: reduced target and will not heat until the window closes, so the
    #: recovery is a counterfactual.
    tou_capped: bool
    #: The heating path with its electricity, stored heat and COP per
    #: interval (``heating_trajectory.HeatingPoint``); None when none
    #: can be published.
    trajectory: tuple[Any, ...] | None
    reasons: tuple[str, ...]
    defaults_used: tuple[str, ...]


@dataclass(frozen=True)
class ActiveCycle:
    """What is left of the recovery the compressor is running
    (``api.active_cycle``). ``status`` is ``heating``, or
    ``not_heating`` when the compressor is off (nothing else is set)."""

    status: str
    ready_at: datetime | None = None
    remaining_minutes: float | None = None
    #: The integrator's own remaining climb, minutes, whatever model
    #: serves ``remaining_minutes``.
    physics_remaining_minutes: float | None = None
    lower_f: float | None = None
    target_f: float | None = None
    confidence: float | None = None
    reasons: tuple[str, ...] = ()
    defaults_used: tuple[str, ...] = ()


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
    #: its start threshold the coast leaves it (the elements', in
    #: Electric or with the heat pump outside its range,
    #: ``controller.lower_trigger_f``); None without settings or without
    #: the threshold.
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
class ElementInterval:
    """One slot of an element-mode stint's electricity."""

    #: Minutes from the stint's start to the slot's end.
    end_minute: float
    #: The elements' input over the slot, Wh.
    element_wh: float
    #: The heat pump's, Wh (High Demand and Energy Saver run it
    #: alongside).
    heat_pump_wh: float


@dataclass(frozen=True)
class ElementModeResult:
    """A stint in an element mode from an instant (``api.element_mode``):
    the scenario walked with the mode written then, and whether a mode
    write can take then. Minutes are from ``starts_at``; a time the
    stint does not reach is None."""

    starts_at: datetime
    mode: HeaterMode
    #: False while heating is disabled (Vacation, Power Off) or a TOU
    #: window is in force, when a mode write may not take effect.
    reachable: bool
    #: Why not, when not.
    unreachable_reason: str | None
    #: When the upper probe reaches the ready level, and the setpoint
    #: (0 when it already has).
    upper_ready_minutes: float | None
    upper_setpoint_minutes: float | None
    #: When the recovery the write set off ends: every element and the
    #: heat pump stopped at its target. None when the switch-back comes
    #: first, a later mode write or the heater dropping the mode at a
    #: window stops part of it, a setpoint write stops the compressor
    #: short of the new setpoint, or it does not end within the walk.
    full_minutes: float | None
    #: The stint's end, and the tank then: the probes and the layers
    #: (``HeaterState.layers_f``).
    end_minute: float
    end_upper_f: float
    end_lower_f: float
    end_layers_f: tuple[float, ...] | None
    #: The elements' running time and energy over the stint.
    element_minutes: float
    element_kwh: float
    #: The heat pump's energy over the stint; None when a recovery could
    #: not price it.
    heat_pump_kwh: float | None
    profile: tuple[ElementInterval, ...]
    #: Why the answer may be less than it seems: the walk's own reasons,
    #: and always ``element_model_small_n``.
    reasons: tuple[str, ...]
