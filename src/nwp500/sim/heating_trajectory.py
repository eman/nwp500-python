"""The heating path published with a recovery.

The physics integrator walks the recovery at 10-second steps. This
turns that walk into the published trajectory: 10-minute elements from
``start_at`` to ``ready_at``, each carrying both zone temperatures, the
electricity over the interval ending there, the heat the tank kept and
the heat pump's COP.

**The path is time-scaled so it ends at ``ready_at``.** The served
duration is the start's hold plus the climb, and the climb may be a
recovery model's rather than the integrator's, so a raw physics path
would end at a different instant from the ``ready_at`` served with it.
Every element at served time ``τ`` past the hold is read off the
physics path at ``(τ − hold) · (physics / climb)``. Temperatures along
the recovery are therefore physics', and the timing is the served
estimate's. With physics alone the climb is the integrator's own and
the scale is 1.

**Electricity is the map's** (``physics.heat_pump.power_w``): through
the hold at the starting state, then the integrator's at the matching
physics instant, over the element's *served* interval. A recovery the
model expects to take longer than physics therefore uses more energy,
at the same power, as a real one does.

**Heat stored is the temperatures', in the apparent frame.** Each
element's ``stored_energy_wh`` is the full tank's mass times the rise of
the two-zone mean over the interval: the frame the device's
``available_energy_wh`` is in, net of standby loss. It does not stretch
with the served clock.

**COP is the map's** over the interval's climb: the heat the heat pump
put in (before the standby loss) over the electricity it drew, on the
physics clock. The hold, which heats nothing, is not in it.

Each element's ``input_energy_wh`` is the difference of the rounded
running total, so the elements sum exactly to the recovery's total
however the grid falls. That is what lets a caller price a recovery that
crosses a tariff boundary by summing elements per slot.
"""

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
    #: on the first element, which ends no interval. None when the path
    #: has no duration to carry the served one.
    input_energy_wh: float | None
    #: Heat stored in the tank over the same interval, Wh, in the
    #: apparent frame: the full tank mass times the rise of the two-zone
    #: mean, net of standby loss. ``0.0`` on the first element.
    stored_energy_wh: float
    #: The heat pump's COP over the interval's climb (the map's heat
    #: over its electricity). Positive when not None. None on the first
    #: element and on one that climbs none of the path (in the hold).
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


def _path_mean(path: PhysicsPath, t: float) -> float:
    """Two-zone mean on ``path`` at physics second ``t``."""
    return (
        _interp(path.elapsed_s, path.t_lower, t)
        + _interp(path.elapsed_s, path.gap, t) / 2.0
    )


def _path_cop(path: PhysicsPath, t0: float, t1: float) -> float | None:
    """The map's COP over physics ``[t0, t1]``: its heat over its
    electricity. None when no electricity falls in the interval."""
    input_btu = _interp(path.elapsed_s, path.input_btu, t1) - _interp(
        path.elapsed_s, path.input_btu, t0
    )
    if input_btu <= 0.0:
        return None
    heat_btu = _interp(path.elapsed_s, path.heat_btu, t1) - _interp(
        path.elapsed_s, path.heat_btu, t0
    )
    return heat_btu / input_btu


def build_heating_trajectory(
    path: PhysicsPath,
    served_minutes: float,
    start_at: datetime,
    t_upper_start: float,
    t_lower_start: float | None = None,
    hold_minutes: float = 0.0,
    start_power_w: float | None = None,
    tank: TankParams = TankParams(),
) -> list[HeatingPoint]:
    """Resample ``path`` onto the served timeline.

    Args:
        path: The converged integrator path.
        served_minutes: The served duration, the hold included; the
            last element sits exactly ``served_minutes`` after
            ``start_at``.
        start_at: The first element's instant.
        t_upper_start: Upper zone at ``start_at``. The upper zone is
            ``t_lower + gap`` along the path: the condenser warms the
            bottom, and the top is unchanged until the gap closes.
        t_lower_start: Lower zone at ``start_at``, which the first element
            carries exactly. Defaults to the path's own start.
        hold_minutes: The hold at the compressor's start, part of
            ``served_minutes``: the tank stays as it started for that
            long, drawing ``start_power_w``, and the path is then
            resampled onto the rest. An element marks its end.
        start_power_w: The electricity through the hold, W: the map's at
            the starting state. None: the path's own first step's.
        tank: The tank, whose full mass turns the mean's rise into
            heat.

    Returns:
        At least one element. A zero-length recovery is the single
        starting element.
    """
    wh_per_mean_f = tank.thermal_mass_btu_f / BTU_PER_WH
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
    # The hold's electricity, Wh per second.
    if start_power_w is not None:
        hold_wh_per_s = start_power_w / 3600.0
    elif len(path.elapsed_s) > 1 and path.elapsed_s[1] > path.elapsed_s[0]:
        hold_wh_per_s = (
            (path.input_btu[1] - path.input_btu[0])
            / (path.elapsed_s[1] - path.elapsed_s[0])
            / BTU_PER_WH
        )
    else:
        hold_wh_per_s = 0.0
    # A path with no duration has no power to carry over a positive
    # served climb: physics says nothing is heated while the model says
    # time passes. Null, not a trajectory claiming 0 Wh over real
    # minutes.
    priced = not (physics_s <= 0.0 and climb_s > 0.0)

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

    # Heat is measured from the path's own start, not from element 0:
    # for an inverted tank element 0 carries the reported upper zone,
    # which the integrator does not, and differencing across that seam
    # would book heat nobody supplied.
    mean_origin = _path_mean(path, 0.0)

    points: list[HeatingPoint] = []
    previous_wh = 0.0
    previous_stored = 0.0
    previous_t = 0.0
    for i, tau in enumerate(instants):
        t = min(max(tau - hold_s, 0.0) * scale, physics_s)
        if i == 0 or tau <= hold_s + _GRID_EPSILON_S:
            # The starting state exactly, as it was reported at the
            # start, and through the hold, which it has not left. The
            # path's rule below would give t_lower + max(0, gap), which
            # differs for an inverted tank.
            t_lower, t_upper = t_lower_start, t_upper_start
        else:
            t_lower = _interp(path.elapsed_s, path.t_lower, t)
            t_upper = t_lower + _interp(path.elapsed_s, path.gap, t)
        energy: float | None = None
        if priced:
            # The hold's electricity, then physics energy up to the
            # mapped instant rescaled from the physics clock to the
            # served one (power × served time). Round the running total,
            # then difference it: the elements sum exactly to the
            # rounded total, which rounding each element on its own does
            # not.
            cumulative_wh = round(
                min(tau, hold_s) * hold_wh_per_s
                + time_stretch
                * _interp(path.elapsed_s, path.input_btu, t)
                / BTU_PER_WH,
                _WH_DECIMALS,
            )
            energy = round(cumulative_wh - previous_wh, _WH_DECIMALS)
            previous_wh = cumulative_wh
        # Heat does not depend on the clock, so no time-stretch here.
        cumulative_stored = round(
            wh_per_mean_f * (_path_mean(path, t) - mean_origin), _WH_DECIMALS
        )
        stored = round(cumulative_stored - previous_stored, _WH_DECIMALS)
        previous_stored = cumulative_stored
        cop: float | None = None
        if i > 0 and t > previous_t:
            raw = _path_cop(path, previous_t, t)
            # A heat pump that puts in nothing per Wh has no COP to
            # divide by: null, never 0.
            if raw is not None and raw > 0.0:
                cop = round(raw, _COP_DECIMALS)
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
