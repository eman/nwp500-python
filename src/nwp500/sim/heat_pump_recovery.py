"""A heat-pump recovery's duration, and a model's answer given it.

The physics' duration is the stratified tank's own: the walk from the
start's layers under the heat pump's map until the lower probe reaches
the target (``TankPhysics.recovery``). A ``RecoveryModel``
(``sim.extensions``) is asked for the duration given it, and its answer
is served as a scale on the heat pump's heat for that recovery
(``rate_scale``): the path stays the tank's, only its pace is the
model's. With no model, or when it declines, the physics is served as
it is.

Everything arrives as a value: the start, the air and the humidity. A
model fitted to a heater's own recoveries is one ``RecoveryModel``.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nwp500.sim.extensions import RecoveryModel

#: The reason a truncated recovery carries: its duration is the walk's
#: bound, a lower bound on the recovery rather than an estimate of it.
PHYSICS_TRUNCATED = "physics_truncated=integration_bound_reached"
#: The range a model's scale on the heat pump's heat is held to: a
#: model four times off the physics is not one recovery's answer.
RATE_SCALE_RANGE = (0.25, 4.0)


@dataclass(frozen=True, kw_only=True)
class PhysicsRecovery:
    """The physics' recovery from a start state to a target."""

    #: Its duration, minutes, the start's hold not included.
    minutes: float
    #: The walk stopped at its bound short of the target, so
    #: ``minutes`` is a lower bound rather than a duration.
    truncated: bool
    #: ``minutes`` as an estimate of the recovery's climb: when it is
    #: finite, positive and reached the target. None otherwise.
    estimate: float | None


@dataclass(frozen=True, kw_only=True)
class RecoveryContext:
    """What a ``RecoveryModel`` is asked about: the start state, the
    target, the air, the start's hold, and the physics duration."""

    t_start_lower: float
    t_start_upper: float
    #: The tank's layers at the start, °F, the bottom first.
    layers_f: tuple[float, ...]
    #: The lower probe's target, °F.
    target_f: float
    #: The air at the start, and its mean over the recovery, °F.
    t_amb_start: float
    t_amb_mean: float
    #: The air's humidity at the start, %; None, unknown.
    h_amb_start: float | None
    #: Minutes the recovery holds at its start before it heats
    #: (``physics.heat_pump.start_hold_min``); 0.0 for one already
    #: under way.
    start_hold_minutes: float = 0.0
    physics: PhysicsRecovery


@dataclass(frozen=True, kw_only=True)
class ModelDuration:
    """A ``RecoveryModel``'s answer."""

    #: The served duration, minutes, the start's hold included.
    minutes: float
    #: The hold included in ``minutes``.
    start_hold_minutes: float
    confidence: float
    reasons: tuple[str, ...] = ()
    #: ``minutes`` is a clamp, not an estimate of the same recovery, so
    #: the physics' pace is kept.
    clamped: bool = False


@dataclass(frozen=True, kw_only=True)
class Scaled:
    """A recovery as served: the scale on the heat pump's heat, the
    model's confidence (1.0 with physics alone) and its reasons."""

    scale: float = 1.0
    confidence: float = 1.0
    reasons: tuple[str, ...] = ()
    model: ModelDuration | None = None


def rate_scale(
    ctx: RecoveryContext, *, model: RecoveryModel | None = None
) -> Scaled:
    """The recovery ``ctx`` as served: ``model``'s duration given the
    physics, as the scale on the heat pump's heat that makes the
    physics' climb take the model's (``RATE_SCALE_RANGE``); the physics
    alone, scale 1, with no model, when it declines, or when its answer
    is a clamp or the physics has no estimate to scale."""
    answer = model.duration(ctx) if model is not None else None
    physics = ctx.physics
    truncated = (PHYSICS_TRUNCATED,) if physics.truncated else ()
    if answer is None:
        return Scaled(reasons=truncated)
    reasons = answer.reasons + tuple(
        r for r in truncated if r not in answer.reasons
    )
    climb = answer.minutes - answer.start_hold_minutes
    if answer.clamped or physics.estimate is None or climb <= 0.0:
        return Scaled(
            confidence=answer.confidence, reasons=reasons, model=answer
        )
    low, high = RATE_SCALE_RANGE
    return Scaled(
        scale=min(high, max(low, physics.estimate / climb)),
        confidence=answer.confidence,
        reasons=reasons,
        model=answer,
    )
