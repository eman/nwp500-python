"""Physics-based ODE integrator for NWP500 heating-duration prediction.

Models the R-134a vapor compression cycle coupled to the stratified tank,
integrating the lower-zone temperature at 10-second steps until the
lower thermostat setpoint is reached.

The free parameters, ``compressor_constant`` (absorbs V_disp × N_RPM ×
η_motor) and ``evap_approach_f`` (T_amb − T_evap at the coil), are fit
over the full training corpus by a calibration outside this package,
which passes them in.
"""

from dataclasses import dataclass

from nwp500.sim.params import (
    UA_REF_DELTA_T_F,
    CompressorParams,
    LossParams,
    TankParams,
)
from nwp500.sim.physics.refrigerant import (
    dew_point_f,
    liquid_enthalpy,
    sat_pressure,
    vapor_density,
    vapor_enthalpy,
)
from nwp500.sim.physics.tank import bottom_loss_reach, ua_at

# Tank thermal masses come from ``TankParams``: the lower zone's while
# the tank is stratified (≈ 263 BTU/°F, half the 63.2-gal tank), the full
# tank's (≈ 527) once the gap closes.  Once the stratification gap closes
# the tank is one body, and the same heat has to warm all of it.  Measured
# across 269 recovery traces, the effective mass resisting the lower probe
# is 0.44-0.48 × full tank while stratified and 0.96 × once mixed, and
# 57 % of all heating steps are in the mixed regime, where integrating at
# half-tank mass runs the tank up roughly twice as fast as it does.
# Latent heat of vaporization of water at typical condensation temperatures
_H_FG_WATER_BTU_LB = 1054.0
# Runaway-integration guard, in minutes.
#
# An iteration bound only.  It must sit clear of every *physically real*
# recovery, or it stops being a guard and becomes a ceiling on the answer,
# which is what 600 was: the ODE needs 621 min at ΔT 80 °F and 735 at
# 95, so deep deficits returned a flat 600, and under the ratio target
# that propagated into a flat served duration.
#
# The envelope has to include ambient, which an earlier revision of this
# comment left out and got the bound wrong for. Integration time rises
# steeply as the air at the heater cools, because the standby loss term
# eats a larger share of compressor output. Measured unbounded at one
# fitted parameter set:
#
#     setpoint 142.8, ΔT 93, ambient 65 °F  ->   720 min
#     setpoint 142.8, ΔT 93, ambient 48 °F  ->   961 min   <- corpus min amb
#     setpoint 150.0, ΔT 105, ambient 40 °F -> 1,321 min
#     setpoint 150.0, ΔT 110, ambient 32 °F -> 1,700 min   <- envelope
#
# 150 °F is this HPWH's maximum setpoint and 32 °F freezing air, so
# 1,700 is the corner of what the hardware can present. 1800 clears it.
#
# The cost of a generous bound is iterations in the pathological case
# only (10,800 steps of scalar arithmetic), and no real call approaches
# it. The cost of a tight one is a silent wrong answer, which is what 600
# gave. When in doubt, raise it: ``converged`` on the result is what
# catches anything past the bound, and unlike the bound it cannot be
# wrong, only ignored.
#
# Not a training change. Calibration was fitted bit-identically at 600 and
# at 900 on the real corpus (19,591 Nelder-Mead trial integrations, none
# of which reached either bound), and the deepest corpus row (ΔT 67.1 °F)
# integrates in 457 min. Raising an iteration bound cannot alter a run that
# already terminated.
_MAX_MINUTES = 1800.0
#: The integration bound, minutes, for a caller's message about a run
#: that reached it (``PhysicsResult.bound_reached``).
MAX_MINUTES = _MAX_MINUTES
# Integration time step
_DT_SECONDS = 10.0


@dataclass(frozen=True)
class PhysicsPath:
    """The heating path the integrator walked, one sample per step.

    Recorded only on request (``record_path=True``): calibration runs
    the integrator tens of thousands of times and needs none of it.
    Sample 0 is the starting state; each later sample is the state at
    the end of a step, so ``elapsed_s[-1]`` is ``minutes × 60``.

    ``input_btu`` is **cumulative** compressor input work, ``ṁ ·
    w_comp`` summed over the steps so far: what the refrigerant cycle
    is charged for in this model. It excludes the evaporator fan and
    the controls. Its level is not published as is: a scale fitted
    per retrain to metered power corrects it, outside the core. Its
    per-step shape agrees with the meter by thirds of a recovery.
    Cumulative rather than per-step so a consumer can
    resample it onto any grid by interpolation without losing energy.
    """

    elapsed_s: tuple[float, ...]
    t_lower: tuple[float, ...]
    gap: tuple[float, ...]
    input_btu: tuple[float, ...]


@dataclass(frozen=True)
class PhysicsResult:
    """A physics estimate and whether the integrator finished.

    ``converged`` is False when the walk hit ``_MAX_MINUTES`` without the
    lower probe reaching setpoint.  ``minutes`` is then a *lower bound*,
    not an estimate, and callers must not present it as one. That
    distinction was invisible for as long as this returned a bare float,
    which is how a truncated integration reached production looking like
    a converged answer.
    """

    minutes: float
    converged: bool
    path: PhysicsPath | None = None
    #: The lower zone where the walk ended, °F, when it walked (None for
    #: an uncalibrated compressor or a start already at setpoint).
    t_lower_end: float | None = None

    @property
    def bound_reached(self) -> bool:
        """The walk stopped at ``MAX_MINUTES`` short of setpoint: the
        integration bound, which a caller outside the core reports (the
        core logs nothing). An uncalibrated compressor is not."""
        return not self.converged and self.t_lower_end is not None


def predict_physics_detailed(
    t_start_lower: float,
    hp_lower_off: float,
    t_amb_mean: float,
    compressor_constant: float,
    evap_approach_f: float,
    compressor: CompressorParams,
    loss: LossParams,
    h_amb_start: float = 50.0,
    t_evap_override: float | None = None,
    ua_btu_hr_f: float | None = None,
    ua_exponent: float = 0.0,
    ua_ref_delta_t: float = UA_REF_DELTA_T_F,
    stratification_gap: float = 0.0,
    two_zone: bool = False,
    record_path: bool = False,
    tank: TankParams = TankParams(),
) -> PhysicsResult:
    """Estimate heating duration via first-principles ODE integration.

    Integrates the lower-zone tank temperature at ``_DT_SECONDS``-second
    steps.  Each step:

    1. Compute evaporator temperature: T_evap = T_amb − evap_approach_f
       (or use ``t_evap_override`` directly when the live coil temperature
       is available mid-cycle)
    2. Look up R-134a saturation properties at T_evap
    3. Compute condenser temperature: T_cond ≈ T_lower + cond_approach_f
    4. Compute pressure ratio r_p = P_cond / P_evap
    5. Compute volumetric efficiency: η_v = 1 − C × (r_p^(1/n) − 1)
    6. Compute mass flow: ṁ = K × η_v × ρ_suction
    7. Compute discharge enthalpy: h₂ = h_g(T_evap) + w_comp, where
       w_comp is the polytropic compression work; the condenser rejects
       evaporator heat *plus* compression work (Q̇_h = ṁ(h₂ − h₃))
    8. Compute condenser enthalpy span: Δh = h₂ − h_f(T_cond)
    9. Add latent heat extraction when T_evap < dew_point
    10. Apply net heating rate to lower zone: dT/dt = (Q̇_h − UA×ΔT) / (m×Cp)
    11. Advance T_lower by one step; stop when T_lower ≥ hp_lower_off

    Args:
        t_start_lower: Initial lower-zone temperature (°F).
        hp_lower_off: Lower thermostat cut-off setpoint (°F).
        t_amb_mean: Mean ambient temperature, the air at the heater,
            during the cycle (°F).
        compressor_constant: Calibrated K = V_disp × N_RPM × η_motor (ft³/s).
            Use 0.0 to signal uncalibrated (returns NaN).
        evap_approach_f: T_amb − T_evap temperature approach at the
            evaporator coil (°F).  Fitted, not measured, and it absorbs
            structural error besides the coil's: 10-15 °F holds for
            winter-only fits, and an all-season fit with compression
            work lands near 18 °F.  Ignored when ``t_evap_override`` is
            supplied.
        compressor: The cycle's fixed constants (``cond_approach_f``,
            ``clearance_ratio``, ``polytropic_exp``, ``fan_airflow_cfm``).
            Its fitted pair and two-zone flag are not read: they are the
            arguments above and below, which calibration searches over.
        loss: Supplies ``ua_baseline_btu_hr_f``, the UA used when
            ``ua_btu_hr_f`` is None, and the bottom loss
            (``bottom_loss_btu_hr``, ``bottom_gate_f``).
        h_amb_start: Ambient relative humidity at cycle start (%).
            Used to compute dew point for latent heat term.
        t_evap_override: Live evaporator coil temperature (°F).  When
            provided, bypasses the ``T_evap = T_amb − evap_approach_f``
            estimate.  Use for mid-cycle inference where the coil temperature
            is a meaningful real-time signal (compressor actively running).
        ua_btu_hr_f: Standby-loss UA (BTU/hr·°F).  Pass the calibrated
            UA estimate so the physics and decay ODEs share one
            UA; falls back to ``loss.ua_baseline_btu_hr_f`` when None
            (pre-calibration only).  When ``ua_exponent`` is non-zero this
            is the UA at ``ua_ref_delta_t`` rather than a flat constant.
        ua_exponent: Power-law exponent for ``UA(ΔT)``.  ``0.0`` (the
            default, and what older parameter sets carry) reproduces the
            constant-UA behaviour exactly.  See ``physics.tank``.
        ua_ref_delta_t: ΔT at which ``ua_btu_hr_f`` is quoted (°F).
        stratification_gap: ``T_upper − T_lower`` at cycle start (°F).
            Ignored unless ``two_zone``.
        two_zone: Track the stratification gap and switch to the full-tank
            mass once it closes.  ``False`` (the default, and what
            parameters calibrated before this carry) integrates the lower
            zone at half-tank mass for the whole cycle, which is what
            shipped.
            See the note below; a fitted ``K`` is only valid for the mode
            it was fitted under.
        record_path: Also return the walked path as a
            :class:`PhysicsPath`.  Off by default; the integration itself
            is identical either way.
        tank: The tank, whose lower-zone and full thermal masses resist
            the heating.

    Returns:
        A :class:`PhysicsResult`.  ``converged`` is False when the
        integrator hit ``_MAX_MINUTES`` without reaching setpoint, in
        which case ``minutes`` is a lower bound.  ``minutes`` is NaN when
        ``compressor_constant == 0.0`` (uncalibrated); ``converged`` is
        False there too, because a NaN is not a finished integration.
    """
    if compressor_constant == 0.0:
        return PhysicsResult(minutes=float("nan"), converged=False)

    if t_start_lower >= hp_lower_off:
        # Already at or above setpoint: nothing to integrate, and that is
        # a finished answer rather than a truncated one.
        return PhysicsResult(
            minutes=0.0,
            converged=True,
            path=PhysicsPath(
                elapsed_s=(0.0,),
                t_lower=(t_start_lower,),
                gap=(max(0.0, stratification_gap) if two_zone else 0.0,),
                input_btu=(0.0,),
            )
            if record_path
            else None,
        )

    t_lower = t_start_lower
    t_amb = t_amb_mean
    dp_f = dew_point_f(t_amb, h_amb_start)
    gap = max(0.0, stratification_gap) if two_zone else 0.0

    if ua_btu_hr_f is None:
        ua_btu_hr_f = loss.ua_baseline_btu_hr_f
    # Convert UA from BTU/hr·°F to BTU/s·°F for per-step integration.  With
    # a flat UA this is step-invariant and stays hoisted; with a ΔT-dependent
    # one it has to be recomputed each step, so only pay for that when the
    # parameters carry an exponent.
    ua_is_flat = ua_exponent == 0.0
    ua_per_s = ua_btu_hr_f / 3600.0
    # The bottom loss (``LossParams.bottom_loss_btu_hr``), BTU/s; 0.0 is
    # none, and the integration is the one before it to the bit.
    bottom_per_s = loss.bottom_loss_btu_hr / 3600.0
    bottom_gate = loss.bottom_gate_f

    cond_approach = compressor.cond_approach_f
    clearance = compressor.clearance_ratio
    poly_n = compressor.polytropic_exp
    fan_cfm = compressor.fan_airflow_cfm
    m_lower_cp = tank.lower_zone_thermal_mass_btu_f
    m_full_cp = tank.thermal_mass_btu_f

    # Air density for latent heat: standard conditions (0.075 lb/ft³)
    rho_air_lb_ft3 = 0.075

    # ── Evaporator side is step-invariant ──────────────────────────
    # T_evap is fixed for the whole call (t_amb is constant and
    # t_evap_override, when given, is a constant), so every quantity that
    # depends only on T_evap is computed once here rather than each of the
    # up-to-10,800 Euler steps: a pure, behaviour-preserving speedup that
    # also cuts calibration time (Nelder-Mead runs this per event per
    # iteration).
    t_evap = (
        t_evap_override
        if t_evap_override is not None
        else t_amb - evap_approach_f
    )
    t_evap_clamped = max(0.0, min(t_evap, 100.0))
    rho_g = vapor_density(t_evap_clamped)
    p_evap = sat_pressure(t_evap_clamped)
    h_g_evap = vapor_enthalpy(t_evap_clamped)

    # Polytropic compression-work prefactor (BTU/lb, sans the r_p term):
    # w = n/(n−1) · P₁v₁ · (r_p^((n−1)/n) − 1), P in lbf/ft², v in ft³/lb,
    # converted to BTU/lb via 778.16 ft·lbf/BTU.  Only the r_p factor
    # varies with T_lower.
    w_comp_prefactor = (
        (poly_n / (poly_n - 1.0)) * (p_evap * 144.0) * (1.0 / rho_g) / 778.16
    )
    w_comp_exponent = (poly_n - 1.0) / poly_n
    eta_exponent = 1.0 / poly_n

    # Latent heat from moisture condensation is step-invariant (depends on
    # T_evap and dew point only): the condenser rejects evaporator heat
    # plus compression work; latent capture adds a fixed extra term.
    q_latent = 0.0
    if t_evap < dp_f:
        m_dot_air = fan_cfm / 60.0 * rho_air_lb_ft3
        condensation_rate = m_dot_air * 0.01 * max(0.0, dp_f - t_evap) / 1000.0
        q_latent = condensation_rate * _H_FG_WATER_BTU_LB

    m_dot_base = compressor_constant * rho_g

    elapsed_s = 0.0
    max_seconds = _MAX_MINUTES * 60.0

    input_btu = 0.0
    rec_elapsed: list[float] = [0.0]
    rec_lower: list[float] = [t_lower]
    rec_gap: list[float] = [gap]
    rec_input: list[float] = [0.0]

    while elapsed_s < max_seconds:
        # Condenser side varies with T_lower each step.
        t_cond = t_lower + cond_approach
        t_cond_clamped = max(80.0, min(t_cond, 160.0))
        p_cond = sat_pressure(t_cond_clamped)

        r_p = p_cond / max(p_evap, 1.0)
        eta_v = max(0.0, 1.0 - clearance * (r_p**eta_exponent - 1.0))

        # Mass flow rate: lb/s
        m_dot = m_dot_base * eta_v

        # Discharge enthalpy h₂ = h_g(T_evap) + w_comp; condenser span is
        # h₂ − h_f(T_cond).
        w_comp = w_comp_prefactor * (r_p**w_comp_exponent - 1.0)
        delta_h = max(
            0.0,
            h_g_evap + w_comp - liquid_enthalpy(t_cond_clamped),
        )

        # Heating rate from refrigerant cycle plus latent capture (BTU/s)
        q_h = m_dot * delta_h + q_latent

        # Standby heat loss (BTU/s).  UA itself rises with tank-to-ambient
        # ΔT, and over a deep recovery that ΔT roughly doubles, so the loss
        # term cannot use a single UA fitted at one end of the cycle.
        # Priced on the tank *mean*, which sits above t_lower while the tank
        # is still stratified: the jacket loses heat from the whole tank,
        # not from the lower zone alone.
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
            # heating, the share the probe sees at this gap
            # (``tank.bottom_loss_reach``), as the standby walk charges it.
            q_loss += bottom_per_s * bottom_loss_reach(gap, bottom_gate)

        # Net heat → temperature rise, against whatever mass is
        # resisting it.  While the tank is stratified the condenser warms
        # the lower zone alone; once the gap closes the same heat has to
        # warm the whole tank, and the lower probe rises half as fast.
        mass = m_lower_cp if (not two_zone or gap > 0.0) else m_full_cp
        dt_lower = ((q_h - q_loss) * _DT_SECONDS) / mass
        t_lower += dt_lower
        if gap > 0.0:
            # The bottom catches up to the top by exactly what it gained.
            gap = max(0.0, gap - dt_lower)

        elapsed_s += _DT_SECONDS
        if record_path:
            input_btu += m_dot * w_comp * _DT_SECONDS
            rec_elapsed.append(elapsed_s)
            rec_lower.append(t_lower)
            rec_gap.append(gap)
            rec_input.append(input_btu)

        if t_lower >= hp_lower_off:
            break

    # Not converged: the integration bound, not setpoint, ended it, and
    # the estimate is a lower bound, not a duration. The result says so
    # (``converged``, ``bound_reached``), which
    # ``sim.heat_pump_recovery`` serves as its ``PHYSICS_TRUNCATED``
    # reason and callers outside the core log; the core logs nothing.
    converged = t_lower >= hp_lower_off
    path = (
        PhysicsPath(
            elapsed_s=tuple(rec_elapsed),
            t_lower=tuple(rec_lower),
            gap=tuple(rec_gap),
            input_btu=tuple(rec_input),
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


def predict_physics(
    t_start_lower: float,
    hp_lower_off: float,
    t_amb_mean: float,
    compressor_constant: float,
    evap_approach_f: float,
    compressor: CompressorParams,
    loss: LossParams,
    h_amb_start: float = 50.0,
    t_evap_override: float | None = None,
    ua_btu_hr_f: float | None = None,
    ua_exponent: float = 0.0,
    ua_ref_delta_t: float = UA_REF_DELTA_T_F,
    stratification_gap: float = 0.0,
    two_zone: bool = False,
    tank: TankParams = TankParams(),
) -> float:
    """Backwards-compatible float wrapper.

    Kept for callers that cannot act on truncation: the calibration fits
    and the training-feature build, which want a number per row and
    nothing else.  Anything that surfaces the estimate to a *user* should
    call :func:`predict_physics_detailed` and say so when ``converged`` is
    False; a lower bound presented as a duration understates how long the
    tank needs, in the one regime where starting late cannot be recovered.

    The signature is spelled out rather than forwarded as ``**kwargs``.
    A ``**kwargs: Any`` wrapper silently disabled mypy for every caller of
    this function: a typo'd keyword, a ``str`` where a ``float`` belongs,
    and a call missing required arguments all type-checked clean.
    """
    return predict_physics_detailed(
        t_start_lower=t_start_lower,
        hp_lower_off=hp_lower_off,
        t_amb_mean=t_amb_mean,
        compressor_constant=compressor_constant,
        evap_approach_f=evap_approach_f,
        compressor=compressor,
        loss=loss,
        h_amb_start=h_amb_start,
        t_evap_override=t_evap_override,
        ua_btu_hr_f=ua_btu_hr_f,
        ua_exponent=ua_exponent,
        ua_ref_delta_t=ua_ref_delta_t,
        stratification_gap=stratification_gap,
        two_zone=two_zone,
        tank=tank,
    ).minutes
