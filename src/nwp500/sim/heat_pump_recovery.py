"""A heat-pump recovery: the physics duration, and a model's answer
given it.

The integrator's duration is computed apart from any model, so a
recovery can be had without a trained one:

- ``physics_recovery``: the performance map's recovery
  (``physics.compressor``) from a start state to a target, and whether
  its duration is usable as an estimate;
- ``recovery``: the served recovery. A ``RecoveryModel``
  (``sim.extensions``) is asked for the duration given the physics;
  with none, or when it declines, the physics is served alone, after
  the start's hold.

Everything arrives as a value: the parameters, the ambient and the
humidity. A model fitted to a heater's own recoveries is one
``RecoveryModel``.
"""

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nwp500.sim.params import CompressorParams, LossParams, TankParams
from nwp500.sim.physics.compressor import (
    PhysicsPath,
    predict_physics_detailed,
)

if TYPE_CHECKING:
    from nwp500.sim.extensions import RecoveryModel

#: The reason a truncated integration carries: its duration is the
#: integrator's bound, a lower bound on the recovery rather than an
#: estimate of it.
PHYSICS_TRUNCATED = "physics_truncated=integration_bound_reached"


@dataclass(frozen=True, kw_only=True)
class PhysicsRecovery:
    """The integrator's recovery from a start state to a target."""

    #: Its duration, minutes, the start's hold not included: 0.0 when
    #: it failed. A model reads it as it is, so the integrator's input
    #: to a model is the same whether or not the estimate below is
    #: usable.
    minutes: float
    #: The integration stopped at its bound short of the target, so
    #: ``minutes`` is a lower bound rather than a duration.
    truncated: bool
    #: The path it walked, when asked for and it ran.
    path: PhysicsPath | None
    #: ``minutes`` as an estimate of the recovery's climb: only when
    #: the caller may serve the physics and the duration is finite and
    #: positive. None otherwise, which a caller reports as null.
    estimate: float | None
    #: The integrator raised: what it raised (``Type: message``), for a
    #: caller outside the core to report; None when it did not (the
    #: core logs nothing). ``minutes`` is then 0.0 and
    #: ``estimate`` None, as before.
    failed: str | None = None


def physics_recovery(
    *,
    t_start_lower: float,
    t_start_upper: float,
    target_f: float,
    t_amb_mean: float,
    compressor: CompressorParams,
    loss: LossParams,
    usable: bool = True,
    record_path: bool = False,
    tank: TankParams = TankParams(),
) -> PhysicsRecovery:
    """The integrator's recovery of the lower zone from
    ``t_start_lower`` to ``target_f`` (``physics.compressor``).

    ``usable``: whether the physics may be served as an estimate.
    """
    minutes = 0.0
    truncated = False
    path: PhysicsPath | None = None
    failed: str | None = None
    try:
        result = predict_physics_detailed(
            t_start_lower=t_start_lower,
            hp_lower_off=target_f,
            t_amb_mean=t_amb_mean,
            compressor=compressor,
            loss=loss,
            ua_btu_hr_f=loss.ua_btu_hr_f,
            ua_exponent=loss.ua_exponent,
            ua_ref_delta_t=loss.ua_ref_delta_t_f,
            stratification_gap=t_start_upper - t_start_lower,
            record_path=record_path,
            tank=tank,
        )
        minutes = result.minutes
        path = result.path
        # The integrator stopped at its bound without reaching the
        # target, so this is a lower bound rather than a duration. A
        # model that scales it propagates the truncation to the caller,
        # who cannot tell a real estimate from a clamped one unless we
        # say so.
        truncated = not result.converged
    except Exception as e:
        # No estimate (``estimate`` None), which the caller reads, and
        # what was raised (``failed``), which it may report: the core
        # logs nothing.
        failed = f"{type(e).__name__}: {e}"
    return PhysicsRecovery(
        minutes=minutes,
        truncated=truncated,
        failed=failed,
        path=path,
        estimate=(
            minutes
            if usable and not math.isnan(minutes) and minutes > 0.0
            else None
        ),
    )


@dataclass(frozen=True, kw_only=True)
class RecoveryContext:
    """What a ``RecoveryModel`` is asked about: the start state,
    the target, the air, the start's hold, the draw load, and the
    physics duration."""

    t_start_lower: float
    t_start_upper: float
    #: The lower zone's target, °F (``hp_lower_off``).
    target_f: float
    #: The air at the start, and its mean over the recovery, °F.
    t_amb_start: float
    t_amb_mean: float
    #: The air's humidity at the start, %; None, unknown.
    h_amb_start: float | None
    #: Minutes the recovery holds at its start before the lower zone
    #: climbs (``physics.heat_pump.start_hold_min``); 0.0 for one
    #: already under way.
    start_hold_minutes: float = 0.0
    #: Gallons drawn just before the recovery, for a model that takes
    #: them as an input; 0.0, none.
    draw_load: float = 0.0
    physics: PhysicsRecovery


@dataclass(frozen=True, kw_only=True)
class ModelDuration:
    """A ``RecoveryModel``'s answer."""

    #: The served duration, minutes, the start's hold included.
    minutes: float
    #: The hold included in ``minutes``, where the path stays flat.
    start_hold_minutes: float
    confidence: float
    reasons: tuple[str, ...] = ()
    #: ``minutes`` is a clamp, not an estimate of the same recovery, so
    #: the physics path is not stretched onto it.
    clamped: bool = False


@dataclass(frozen=True, kw_only=True)
class Recovery:
    """The served recovery."""

    minutes: float
    start_hold_minutes: float
    #: The model's confidence; 1.0 with physics alone, which nothing
    #: scores (a recovery's confidence only ever lowers a cycle's).
    confidence: float
    reasons: tuple[str, ...]
    context: RecoveryContext
    #: The physics path, when it can be time-scaled onto ``minutes``
    #: (``_path_publishable``); None otherwise.
    path: PhysicsPath | None
    #: The model's answer; None when physics is served alone.
    model: ModelDuration | None = field(default=None)

    @property
    def physics(self) -> PhysicsRecovery:
        return self.context.physics


def _path_publishable(
    physics: PhysicsRecovery, served_minutes: float, clamped: bool
) -> bool:
    """Whether the physics path can be time-scaled onto the served
    duration.

    The heating trajectory stretches the integrator's path to end at
    `ready_at`. That is only sound when the served
    duration is an estimate of the same recovery. It is not when:

    - physics is unusable, or the integration was truncated short of the
      target, so the path does not reach it;
    - the model clamped the served duration (an edge guardrail). The
      cap is a clamp, not an estimate, and squeezing a multi-hour path
      into it gives a heat pump several kilowatts;
    - the served duration was floored to zero while physics needed time,
      which would discard the recovery's energy.
    """
    if physics.estimate is None or physics.truncated:
        return False
    if served_minutes <= 0.0:
        return False
    return not clamped


def recovery(
    ctx: RecoveryContext, *, model: RecoveryModel | None = None
) -> Recovery | None:
    """The served recovery for ``ctx``: ``model``'s duration given the
    physics, or the physics alone, after the start's hold, with no
    model or when it declines. None when there is neither: no model's
    answer and no usable physics estimate. A truncated integration is
    not one: its minutes are the bound, and nothing reached the
    target."""
    answer = model.duration(ctx) if model is not None else None
    physics = ctx.physics
    if answer is None:
        if physics.estimate is None or physics.truncated:
            return None
        hold = max(0.0, ctx.start_hold_minutes)
        minutes = hold + physics.estimate
        return Recovery(
            minutes=minutes,
            start_hold_minutes=hold,
            confidence=1.0,
            reasons=(),
            context=ctx,
            path=(
                physics.path
                if _path_publishable(physics, minutes, False)
                else None
            ),
        )
    return Recovery(
        minutes=answer.minutes,
        start_hold_minutes=answer.start_hold_minutes,
        confidence=answer.confidence,
        # The model answered from a truncated integration: say so.
        reasons=(
            (*answer.reasons, PHYSICS_TRUNCATED)
            if physics.truncated and PHYSICS_TRUNCATED not in answer.reasons
            else answer.reasons
        ),
        context=ctx,
        path=(
            physics.path
            if _path_publishable(physics, answer.minutes, answer.clamped)
            else None
        ),
        model=answer,
    )
