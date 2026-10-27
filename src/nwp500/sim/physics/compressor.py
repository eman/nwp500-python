"""The heat-pump recovery of the two-zone tank: the lower zone
integrated at 10-second steps until it reaches its target, heated by
the performance map (``physics.heat_pump``) at the air and the lower
zone, less the standby loss.

While the tank is stratified the condenser heats the lower zone
alone, at its mass, and the gap closes by what it gains; once the gap
has closed the whole tank's mass resists the same heat, and the lower
probe rises half as fast. The upper zone is held where it started until
then. On 30 compressor-only recoveries (2026-04 to 10, no metered
flow, gap 5.6 to 46 °F at the start) the upper probe fell a median
0.54 °F while the gap was over 3 °F, and rose to 1.26 °F above its
start as the gap closed its last 2 to 3 °F, where the zones mix; after
closure the two probes rose together (10.4 and 12.2 °F).

The hold at the start and the run-on past the target are not
integrated here: the caller adds the hold (``CompressorParams``'
``start_hold_min``), and the controller runs on past the target
(``ControllerParams.hp_stop_overshoot_f``).
"""

from dataclasses import dataclass

from nwp500.sim.params import (
    UA_REF_DELTA_T_F,
    CompressorParams,
    LossParams,
    TankParams,
)
from nwp500.sim.physics.heat_pump import heat_btu_h, power_w
from nwp500.sim.physics.tank import bottom_loss_reach, ua_at
from nwp500.sim.units import BTU_PER_WH

# Runaway-integration guard, in minutes: an iteration bound only, clear
# of every physically real recovery, or it would be a ceiling on the
# answer. The slowest the map allows is the whole 63.2-gal tank from
# 40 to 150 °F with the air at the bottom of its domain, where the heat
# is about 3,600 BTU/h and the standby loss a seventh of it: about
# 1,200 min. ``converged`` on the result catches anything past the
# bound.
_MAX_MINUTES = 1800.0
#: The integration bound, minutes, for a caller's message about a run
#: that reached it (``PhysicsResult.bound_reached``).
MAX_MINUTES = _MAX_MINUTES
# Integration time step
_DT_SECONDS = 10.0


@dataclass(frozen=True)
class PhysicsPath:
    """The heating path the integrator walked, one sample per step.

    Recorded only on request (``record_path=True``). Sample 0 is the
    starting state; each later sample is the state at the end of a
    step, so ``elapsed_s[-1]`` is ``minutes × 60``.

    ``input_btu`` is the **cumulative** electricity the map charges
    (``heat_pump.power_w``), and ``heat_btu`` the cumulative heat it
    puts into the tank (``heat_pump.heat_btu_h``), before the standby
    loss. Cumulative rather than per-step so a consumer can resample
    them onto any grid by interpolation without losing energy.
    """

    elapsed_s: tuple[float, ...]
    t_lower: tuple[float, ...]
    gap: tuple[float, ...]
    input_btu: tuple[float, ...]
    heat_btu: tuple[float, ...]


@dataclass(frozen=True)
class PhysicsResult:
    """A physics estimate and whether the integrator finished.

    ``converged`` is False when the walk hit ``_MAX_MINUTES`` without the
    lower probe reaching its target. ``minutes`` is then a *lower
    bound*, not an estimate, and callers must not present it as one.
    """

    minutes: float
    converged: bool
    path: PhysicsPath | None = None
    #: The lower zone where the walk ended, °F, when it walked (None for
    #: a start already at its target).
    t_lower_end: float | None = None

    @property
    def bound_reached(self) -> bool:
        """The walk stopped at ``MAX_MINUTES`` short of its target: the
        integration bound, which a caller outside the core reports (the
        core logs nothing)."""
        return not self.converged and self.t_lower_end is not None


def predict_physics_detailed(
    t_start_lower: float,
    hp_lower_off: float,
    t_amb_mean: float,
    compressor: CompressorParams,
    loss: LossParams,
    ua_btu_hr_f: float | None = None,
    ua_exponent: float = 0.0,
    ua_ref_delta_t: float = UA_REF_DELTA_T_F,
    stratification_gap: float = 0.0,
    record_path: bool = False,
    tank: TankParams = TankParams(),
) -> PhysicsResult:
    """The recovery of the lower zone from ``t_start_lower`` to
    ``hp_lower_off`` with the air at ``t_amb_mean``, integrated at
    ``_DT_SECONDS`` steps. Each step heats the zone resisting it (the
    lower zone's mass while ``stratification_gap`` is open, the whole
    tank's once it has closed) by the map's heat at the air and the
    lower zone, less the standby loss: the UA law's on the tank's mean
    (``ua_btu_hr_f`` at ``ua_ref_delta_t``, raised to ``ua_exponent``;
    ``loss.ua_baseline_btu_hr_f`` when None) and the bottom loss's
    share at the gap (``physics.tank.bottom_loss_reach``).

    Returns:
        A :class:`PhysicsResult`. ``converged`` is False when the walk
        hit ``_MAX_MINUTES`` short of the target, and ``minutes`` is
        then a lower bound.
    """
    gap = max(0.0, stratification_gap)
    if t_start_lower >= hp_lower_off:
        # Already at or above its target: nothing to integrate, and that
        # is a finished answer rather than a truncated one.
        return PhysicsResult(
            minutes=0.0,
            converged=True,
            path=PhysicsPath(
                elapsed_s=(0.0,),
                t_lower=(t_start_lower,),
                gap=(gap,),
                input_btu=(0.0,),
                heat_btu=(0.0,),
            )
            if record_path
            else None,
        )

    t_lower = t_start_lower
    t_amb = t_amb_mean
    if ua_btu_hr_f is None:
        ua_btu_hr_f = loss.ua_baseline_btu_hr_f
    # With a flat UA the loss's factor is step-invariant and stays
    # hoisted; with a ΔT-dependent one it is recomputed each step.
    ua_is_flat = ua_exponent == 0.0
    ua_per_s = ua_btu_hr_f / 3600.0
    # The bottom loss (``LossParams.bottom_loss_btu_hr``), BTU/s.
    bottom_per_s = loss.bottom_loss_btu_hr / 3600.0
    bottom_gate = loss.bottom_gate_f
    m_lower_cp = tank.lower_zone_thermal_mass_btu_f
    m_full_cp = tank.thermal_mass_btu_f

    elapsed_s = 0.0
    max_seconds = _MAX_MINUTES * 60.0
    input_btu = 0.0
    heat_btu = 0.0
    rec_elapsed: list[float] = [0.0]
    rec_lower: list[float] = [t_lower]
    rec_gap: list[float] = [gap]
    rec_input: list[float] = [0.0]
    rec_heat: list[float] = [0.0]

    while elapsed_s < max_seconds:
        q_h = heat_btu_h(compressor, t_amb, t_lower) / 3600.0
        # The jacket loses heat from the whole tank, priced on its mean,
        # which sits above the lower zone while the tank is stratified.
        t_mean = t_lower + gap / 2.0
        delta_t = t_mean - t_amb
        if not ua_is_flat:
            ua_per_s = (
                ua_at(delta_t, ua_btu_hr_f, ua_exponent, ua_ref_delta_t)
                / 3600.0
            )
        q_loss = ua_per_s * max(0.0, delta_t)
        if bottom_per_s > 0.0:
            # The bottom loss leaves the lower zone the condenser is
            # heating, the share the probe sees at this gap, as the
            # standby walk charges it.
            q_loss += bottom_per_s * bottom_loss_reach(gap, bottom_gate)
        net_btu = (q_h - q_loss) * _DT_SECONDS
        if record_path:
            input_btu += (
                power_w(compressor, t_amb, t_lower) * BTU_PER_WH * _DT_SECONDS
            ) / 3600.0
            heat_btu += q_h * _DT_SECONDS
        if gap <= 0.0:
            t_lower += net_btu / m_full_cp
        elif net_btu > gap * m_lower_cp:
            # The gap closes inside the step: the lower zone's mass to
            # it, the whole tank's after.
            t_lower += gap + (net_btu - gap * m_lower_cp) / m_full_cp
            gap = 0.0
        else:
            # The bottom catches up to the top by exactly what it gained.
            rise = net_btu / m_lower_cp
            t_lower += rise
            gap = max(0.0, gap - rise)

        elapsed_s += _DT_SECONDS
        if record_path:
            rec_elapsed.append(elapsed_s)
            rec_lower.append(t_lower)
            rec_gap.append(gap)
            rec_input.append(input_btu)
            rec_heat.append(heat_btu)

        if t_lower >= hp_lower_off:
            break

    # Not converged: the integration bound, not the target, ended it,
    # and the estimate is a lower bound, not a duration. The result says
    # so (``converged``, ``bound_reached``), which
    # ``sim.heat_pump_recovery`` serves as its ``PHYSICS_TRUNCATED``
    # reason and callers outside the core log; the core logs nothing.
    converged = t_lower >= hp_lower_off
    path = (
        PhysicsPath(
            elapsed_s=tuple(rec_elapsed),
            t_lower=tuple(rec_lower),
            gap=tuple(rec_gap),
            input_btu=tuple(rec_input),
            heat_btu=tuple(rec_heat),
        )
        if record_path
        else None
    )
    return PhysicsResult(
        minutes=elapsed_s / 60.0,
        converged=converged,
        path=path,
        t_lower_end=t_lower,
    )
