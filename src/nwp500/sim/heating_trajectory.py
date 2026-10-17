"""The heating path published with a recovery.

The physics integrator walks the recovery at 10-second steps and used to
discard everything but its duration. This turns that walk into the
published trajectory: 10-minute elements from ``start_at`` to
``ready_at``, each carrying both zone temperatures and the compressor's
electrical input over the interval ending there.

**The path is time-scaled so it ends at ``ready_at``.** The headline
duration comes from the recovery model, not the integrator, so a raw
physics path would end at a different instant from the ``ready_at``
served with it. Every element at served time ``τ`` is read off the
physics path at ``τ · (physics / served)``. Temperatures along the
recovery are therefore physics', and the timing is the served
estimate's. The rule is uniform. When the model is outside its
training domain the recovery's reasons already say so, and the
trajectory inherits that caveat rather than switching rules.

**Power comes from the integrator, its level from the meter.** The
integrator's ``ṁ · w_comp`` has the right shape through a recovery but
not the right level: its constants are fitted to durations, and it runs
at about 1.8× the metered power. Each element's power is the
integrator's power at the matching physics instant, times the fitted
``PowerParams.power_scale``. Its energy is that power over the
element's *served* interval. A recovery the model expects to take longer
than physics therefore uses more energy, at the same power, as a real
one does. The cost is that energy inherits the model's duration error
one for one. Without the scale no energy is published.

Scaling energy totals instead, as the first version did, mixed three
clocks: modelled energy over the physics duration, metered energy over
the real cycle, and publication over the served duration. That put
average power above anything the heat pump draws.

**Heat stored is the temperatures', in the apparent frame.** Each
element's ``stored_energy_wh`` is the full tank's mass times the rise of
the two-zone mean over the interval: the frame the device's
``available_energy_wh`` is in, net of standby loss. It does not stretch
with the served clock.

**COP is its own field.** ``stored / input`` is not the heat pump's
COP: input is spread over the served duration, which the model learned
from real cycles and so includes the time draws during them
add. ``cop`` is the integrator's heat per unit of its own input over the
interval, on the physics clock, times the fitted
``PowerParams.cop_scale`` and its lift term, ``exp(−γ (lift − ref))``
with lift the interval's tank mean less the air at the heater. It is
the *running* COP, what each further Wh buys once the compressor is
going. The electricity a cycle spends before the tank gains anything is
not in it. It is a per-start cost, counted once per recovery
(``PowerParams.startup_wh``). Folding it into the first elements' COP,
as this did first, published 0.0 on the first two elements of every
recovery while the same elements showed heat stored.

Each element's ``input_energy_wh`` is the difference of the rounded
running total, so the elements sum exactly to the recovery's total
however the grid falls. That is what lets a caller price a recovery that
crosses a tariff boundary by summing elements per slot.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta

from nwp500.sim.params import TankParams
from nwp500.sim.physics.compressor import PhysicsPath
from nwp500.sim.units import BTU_PER_WH

#: Element spacing, seconds: the same 10 minutes as the standby
#: trajectory's.
STEP_SECONDS = 600.0

#: Published precision: temperatures to 0.001 °F, as the standby
#: trajectory's, and energy to 0.01 Wh.
_TEMP_DECIMALS = 3
_WH_DECIMALS = 2
_COP_DECIMALS = 3


def _wh_per_mean_f(tank: TankParams) -> float:
    """Apparent heat per °F of the two-zone mean, Wh: the full tank's
    mass, the frame the device's `available_energy_wh` is in."""
    return tank.thermal_mass_btu_f / BTU_PER_WH


#: Grid instants closer than this to ready_at are not emitted, so the
#: shortened final interval is never degenerate.
_GRID_EPSILON_S = 1e-6


@dataclass(frozen=True)
class HeatingPoint:
    """One element of the heating trajectory."""

    at: datetime
    t_upper_f: float
    t_lower_f: float
    #: Electrical input over the interval ending at ``at``, Wh. ``0.0``
    #: on the first element, which ends no interval. None when the
    #: parameters carry no metered scale for the integrator's figure.
    input_energy_wh: float | None
    #: Heat stored in the tank over the same interval, Wh, in the
    #: apparent frame: the full tank mass times the rise of the two-zone
    #: mean, net of standby loss. ``0.0`` on the first element.
    stored_energy_wh: float
    #: The heat pump's running apparent COP over the interval ending at
    #: ``at``, start-up excluded. Positive when not None. None on the
    #: first element, when there is no fitted COP scale, and when the
    #: integrator stores nothing over the interval.
    cop: float | None = None


def _interp(xs: tuple[float, ...], ys: tuple[float, ...], x: float) -> float:
    """Linear interpolation on an ascending ``xs``, clamped at both ends."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x)
    x0, x1 = xs[i - 1], xs[i]
    y0, y1 = ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _path_mean(
    path: PhysicsPath, t: float, two_zone: bool, t_upper_start: float
) -> float:
    """Two-zone mean on ``path`` at physics second ``t``."""
    lower = _interp(path.elapsed_s, path.t_lower, t)
    if two_zone:
        return lower + _interp(path.elapsed_s, path.gap, t) / 2.0
    return (lower + max(t_upper_start, lower)) / 2.0


def path_cop(
    path: PhysicsPath,
    t0: float,
    t1: float,
    two_zone: bool,
    t_upper_start: float,
    tank: TankParams = TankParams(),
) -> float | None:
    """The integrator's own apparent COP over physics ``[t0, t1]``.

    Heat stored (the full tank's mass times the rise of the two-zone
    mean, net of standby loss) over the integrator's compressor input.
    Unscaled: the published figure multiplies it by the fitted
    ``PowerParams.cop_scale``. None when no input falls in the interval.
    """
    input_wh = (
        _interp(path.elapsed_s, path.input_btu, t1)
        - _interp(path.elapsed_s, path.input_btu, t0)
    ) / BTU_PER_WH
    if input_wh <= 0.0:
        return None
    heat_wh = _wh_per_mean_f(tank) * (
        _path_mean(path, t1, two_zone, t_upper_start)
        - _path_mean(path, t0, two_zone, t_upper_start)
    )
    return heat_wh / input_wh


def build_heating_trajectory(
    path: PhysicsPath,
    served_minutes: float,
    start_at: datetime,
    t_upper_start: float,
    two_zone: bool,
    power_scale: float | None,
    t_lower_start: float | None = None,
    cop_scale: float | None = None,
    cop_lift_coeff: float = 0.0,
    cop_lift_ref_f: float = 62.0,
    t_amb: float | None = None,
    hold_minutes: float = 0.0,
    tank: TankParams = TankParams(),
) -> list[HeatingPoint]:
    """Resample ``path`` onto the served timeline.

    Args:
        path: The converged integrator path.
        served_minutes: The served duration; the last
            element sits exactly ``served_minutes`` after ``start_at``.
        start_at: The first element's instant.
        t_lower_start: Lower zone at ``start_at``, which the first element
            carries exactly. Defaults to the path's own start.
        t_upper_start: Upper zone at ``start_at``. Used directly by a
            single-zone calibration, which does not track the gap.
        two_zone: Whether the integrator tracked the stratification gap.
            When it did, the upper zone is ``t_lower + gap``: the
            condenser warms the bottom, and the top is unchanged until
            the gap closes. When it did not, the upper zone is held at
            its starting value until the lower zone overtakes it.
        power_scale: Metered / modelled input power, fitted.
            The integrator's own power has the right shape and the
            wrong level, so it is never published unscaled: None gives
            ``input_energy_wh = None`` on every element.
        cop_scale: Measured / modelled apparent COP, fitted. None
            gives ``cop = None`` on every element.
        cop_lift_coeff: The fitted lift term, per °F, about
            ``cop_lift_ref_f``. Non-zero needs ``t_amb``, the air at the
            heater over the heating window, or ``cop`` is None: the term
            cannot be applied without the lift it depends on.
        hold_minutes: The hold at the compressor's start, part of
            ``served_minutes``: the tank stays as it started for that
            long, drawing the path's starting power, and the path is
            then resampled onto the rest. An element marks its end.
        tank: The tank, whose full mass turns the mean's rise into
            heat.

    Returns:
        At least one element. A zero-length recovery is the single
        starting element.
    """
    wh_per_mean_f = _wh_per_mean_f(tank)
    if t_lower_start is None:
        t_lower_start = path.t_lower[0]
    served_s = max(0.0, served_minutes * 60.0)
    hold_s = min(max(0.0, hold_minutes * 60.0), served_s)
    climb_s = served_s - hold_s
    physics_s = path.elapsed_s[-1]
    scale = physics_s / climb_s if climb_s > 0.0 else 0.0
    # Served seconds per physics second: what turns physics energy (its
    # power over its own duration) into the same power over the served
    # duration.
    time_stretch = climb_s / physics_s if physics_s > 0.0 else 0.0
    # The hold draws the path's starting power (Wh of physics input per
    # second).
    start_power = (
        (path.input_btu[1] - path.input_btu[0])
        / (path.elapsed_s[1] - path.elapsed_s[0])
        / BTU_PER_WH
        if len(path.elapsed_s) > 1 and path.elapsed_s[1] > path.elapsed_s[0]
        else 0.0
    )
    # A path with no duration has no power to hold over a positive served
    # interval: physics says nothing is heated while the model says time
    # passes. Null, not a trajectory claiming 0 Wh over real minutes.
    if physics_s <= 0.0 and served_s > 0.0:
        power_scale = None

    instants = [0.0]
    # The epsilon keeps a duration a hair past a 10-minute multiple from
    # producing two elements at the same instant.
    while instants[-1] + STEP_SECONDS < served_s - _GRID_EPSILON_S:
        instants.append(instants[-1] + STEP_SECONDS)
    if served_s > 0.0:
        # The final interval is shortened, so the last element sits
        # exactly at ready_at, as the standby walk's last step does.
        instants.append(served_s)
    if 0.0 < hold_s < served_s and not any(
        abs(x - hold_s) < _GRID_EPSILON_S for x in instants
    ):
        instants = sorted([*instants, hold_s])

    def path_mean(t: float) -> float:
        return _path_mean(path, t, two_zone, t_upper_start)

    # Heat is measured from the path's own start, not from element 0:
    # for an inverted tank element 0 carries the reported upper zone,
    # which the integrator does not, and differencing across that seam
    # would book heat nobody supplied.
    mean_origin = path_mean(0.0)

    points: list[HeatingPoint] = []
    previous_wh = 0.0
    previous_stored = 0.0
    previous_t = 0.0
    for i, tau in enumerate(instants):
        t = min(max(tau - hold_s, 0.0) * scale, physics_s)
        if i == 0 or tau <= hold_s + _GRID_EPSILON_S:
            # The starting state exactly, as it was reported at the
            # start, and through the hold, which it has not
            # left. The two-zone rule below would give t_lower + max(0,
            # gap), which differs for an inverted tank.
            t_lower, t_upper = t_lower_start, t_upper_start
        else:
            t_lower = _interp(path.elapsed_s, path.t_lower, t)
            if two_zone:
                t_upper = t_lower + _interp(path.elapsed_s, path.gap, t)
            else:
                t_upper = max(t_upper_start, t_lower)
        energy: float | None = None
        if power_scale is not None:
            # Physics energy up to the mapped instant, rescaled from the
            # physics clock to the served one (power × served time), then
            # to the meter's level. Round the running total, then
            # difference it: the elements sum exactly to the rounded
            # total, which rounding each element on its own does not.
            cumulative_wh = round(
                power_scale
                * (
                    min(tau, hold_s) * start_power
                    + time_stretch
                    * _interp(path.elapsed_s, path.input_btu, t)
                    / BTU_PER_WH
                ),
                _WH_DECIMALS,
            )
            energy = round(cumulative_wh - previous_wh, _WH_DECIMALS)
            previous_wh = cumulative_wh
        # Heat does not depend on the clock, so no time-stretch here.
        cumulative_stored = round(
            wh_per_mean_f * (path_mean(t) - mean_origin), _WH_DECIMALS
        )
        stored = round(cumulative_stored - previous_stored, _WH_DECIMALS)
        previous_stored = cumulative_stored
        # COP is a ratio on the physics clock: stretching time scales
        # input and not heat, and the served stretch carries the model's
        # expectation of draws during the recovery, which is not the
        # heat pump's efficiency.
        cop: float | None = None
        if i > 0 and cop_scale is not None:
            raw = path_cop(
                path, previous_t, t, two_zone, t_upper_start, tank=tank
            )
            lift = 1.0
            if cop_lift_coeff:
                if t_amb is None:
                    raw = None
                else:
                    mean = (path_mean(previous_t) + path_mean(t)) / 2.0
                    lift = math.exp(
                        -cop_lift_coeff * (mean - t_amb - cop_lift_ref_f)
                    )
            # A heat pump that stores nothing per Wh has no COP to divide
            # by: null, never 0.
            if raw is not None and raw > 0.0:
                cop = round(cop_scale * raw * lift, _COP_DECIMALS)
        previous_t = t
        points.append(
            HeatingPoint(
                at=start_at + timedelta(seconds=tau),
                t_upper_f=round(t_upper, _TEMP_DECIMALS),
                t_lower_f=round(t_lower, _TEMP_DECIMALS),
                input_energy_wh=energy,
                stored_energy_wh=stored,
                cop=cop,
            )
        )
    return points
