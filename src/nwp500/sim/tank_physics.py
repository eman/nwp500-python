"""The calibrated tank the engine runs on.

The engine (``sim.engine``) takes its physics as a ``Physics``:
a standby coast, a heat-pump recovery and a draw. ``TankPhysics`` is
the core's, and the default: the standby coast (``sim.decay``), the
heat-pump recovery (``sim.heat_pump_recovery``, through a ``RecoveryModel`` when
one is given) and the delivered draw (``sim.decay.draw_step``), all on
one ``HeaterParams`` and one ambient series, so every segment of a
simulation reads the same world.

It reaches no module state, cache or configuration for what it is not
given. Each input is a value its client resolves before it builds one
(the draws that flow over a coast, an inlet, the ambient frame and
humidity, ``HeaterParams``), so the same inputs give the same answer on
any thread.

**Water moves through the tank only as draws** (``sim.decay.Draw``):
the delivered draws the engine hands each coast, and the flowing draws
the client's ``FlowingDraws`` gives for it, each with the temperature of
the water replacing it. What a flowing draw stands for is the client's.

**The ambient frame** (``t_amb_series``) is a ``pd.DataFrame`` with a
tz-aware ``DatetimeIndex`` and an ``ambient_f`` column, °F: the air
at the heater's evaporator. ``sim.decay.AmbientSampler`` reads it.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Protocol

import pandas as pd

from nwp500.sim.decay import (
    AmbientSampler,
    Draw,
    Impulse,
    draw_step,
    project_decay,
)
from nwp500.sim.extensions import RecoveryModel
from nwp500.sim.heat_pump_recovery import (
    PhysicsRecovery,
    Recovery,
    RecoveryContext,
    physics_recovery,
    recovery,
)
from nwp500.sim.heating_trajectory import build_heating_trajectory
from nwp500.sim.params import HeaterParams

#: A delivered draw at the inlet: its onset, and the gallons the meter
#: counts (``Draw(at, gallons)``).
Delivered = tuple[datetime, float]
#: The flowing draws over a coast from ``start`` to ``end``: every one
#: that flows in ``[start, end)``, whole, not clipped to it (the coast
#: charges a draw already under way from its own start). The client's,
#: called once per coast in the order the coasts are walked.
FlowingDraws = Callable[[datetime, datetime], Sequence[Draw]]

#: The recovery's refinement: a recovery is predicted again with the
#: air's mean over the duration the last pass found, until it moves no
#: more than this, minutes.
REFINE_TOL_MINUTES = 2.0


@dataclass(frozen=True)
class Point:
    """A state on the path. ``input_wh`` is the electricity over the
    interval ending here: 0.0 while coasting and on a segment's first
    element, None when the recovery could not price it."""

    at: datetime
    upper_f: float
    lower_f: float
    input_wh: float | None = 0.0
    #: The element's electricity over the same interval (the engine's;
    #: the physics never sets it).
    element_wh: float = 0.0


@dataclass(frozen=True)
class Coast:
    """A standby segment: the path and its extraction drops, and what
    it took (``decay.DecayProjection``'s): the delivered gallons drawn
    and the heat they carried off, the heat the flowing draws
    (circulation) took, and the mean air over it."""

    points: list[Point]
    impulses: list[Impulse] = field(default_factory=list)
    draw_volume_gal: float = 0.0
    draw_heat_btu: float = 0.0
    flowing_heat_btu: float = 0.0
    ambient_mean_f: float | None = None


@dataclass(frozen=True)
class Heat:
    """A recovery from a state to a target, draw-free, to its end.

    ``points`` starts at the state asked for and ends where the lower
    zone reaches the target. ``linear`` marks a path interpolated because
    the physics had none; its energy is then None.
    """

    points: list[Point]
    confidence: float
    reasons: tuple[str, ...] = ()
    linear: bool = False


def point_at(points: Sequence[Point], at: datetime) -> Point:
    """The state at ``at`` on a path, linear between its elements, with
    the interval's energy split in proportion to time (was
    ``sim.engine._interp``)."""
    if at <= points[0].at:
        return replace(points[0], at=at, input_wh=0.0)
    for p0, p1 in pairwise(points):
        if p0.at <= at <= p1.at:
            span = (p1.at - p0.at).total_seconds()
            f = 1.0 if span <= 0 else (at - p0.at).total_seconds() / span
            return Point(
                at,
                p0.upper_f + (p1.upper_f - p0.upper_f) * f,
                p0.lower_f + (p1.lower_f - p0.lower_f) * f,
                None if p1.input_wh is None else p1.input_wh * f,
            )
    return points[-1]


class Physics(Protocol):
    """The calibrated tank, as the engine takes it: ``TankPhysics`` is
    the core's."""

    def coast(
        self,
        start: datetime,
        upper_f: float,
        lower_f: float,
        end: datetime,
        draws: Sequence[Delivered | Draw],
        heated_at: datetime | None = None,
        draw_lower: bool = True,
    ) -> Coast:
        """Standby from ``start`` to ``end``: jacket loss, the flowing
        draws the physics was given, and exactly ``draws`` (delivered
        gallons at their onsets, all in ``[start, end)``; a pair is at
        the inlet). ``heated_at`` is when the tank last heated, by the
        compressor or an element, which a flowing draw's standby pool
        is counted from; None when it is not known.
        ``draw_lower=False`` leaves the lower zone where each draw found
        it, the upper zone taking the draw's own response: with a book,
        the engine takes the lower zone through a draw by the front
        (``_follow_ledger``), and the coast carries only the draws a bound
        shows leave the front below the probe (``_ledger_cut``)."""
        ...

    def heat(
        self,
        start: datetime,
        upper_f: float,
        lower_f: float,
        target_f: float,
        *,
        hold_minutes: float = 0.0,
        draw_load: float = 0.0,
    ) -> Heat | None:
        """A heat-pump recovery to ``target_f`` (the lower zone), draw
        free. None when it cannot be computed. The engine passes
        ``draw_load`` only for a recovery from the recorded tank with
        draws recorded in the ``DRAW_LEAD`` before it: the draw-free
        model's input, as its training rows carried them. It passes
        ``hold_minutes`` only when the recovery begins with a compressor
        start whose hold has time left: the path is then flat for that
        long, and climbs after."""
        ...

    def draw(
        self, at: datetime, upper_f: float, lower_f: float, gal: float
    ) -> tuple[float, float]:
        """The tank just after a delivered draw of ``gal`` at ``at``."""
        ...


def ambient_window_mean(
    t_amb_series: pd.DataFrame, start: datetime, end: datetime
) -> float | None:
    """Mean projected air temperature at the heater over [start, end],
    or None."""
    if t_amb_series.empty:
        return None
    index = t_amb_series.index
    if index.is_monotonic_increasing:
        # The same rows the mask below takes, found by bisection: this
        # runs for every recovery a simulation predicts.
        lo = index.searchsorted(pd.Timestamp(start), side="left")  # pyright: ignore[reportCallIssue, reportArgumentType]
        hi = index.searchsorted(pd.Timestamp(end), side="right")  # pyright: ignore[reportCallIssue, reportArgumentType]
        window = t_amb_series["ambient_f"].iloc[lo:hi]
    else:
        window = t_amb_series.loc[
            (index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end)),
            "ambient_f",
        ]
    if window.empty:
        return None
    value = float(window.mean())
    return value if not math.isnan(value) else None


class TankPhysics:
    """The calibrated tank, for ``sim.engine``: the standby coast,
    the heat-pump recovery, and the delivered draw, all from one
    ``HeaterParams`` and one ambient series, so every segment of a
    simulation reads the same world.

    Every input is a value its client resolved:

    - ``params``: the heater's parameters;
    - ``t_amb_series``: the ambient frame (the module docstring), and
      ``humidity``, %, at the start (None: unknown);
    - ``draws_on``: whether delivered draws move the tank (a draw
      scenario);
    - ``flowing_draws``: the draws that flow over each coast, whatever
      ``draws_on`` says; None, none;
    - ``tau_gap_hours``: the stratification gap's time constant, the
      fitted one or the client's prior;
    - ``draw_inlet_temp_f``: the inlet a draw is priced at; None, the
      parameters' reference (``DrawParams.inlet_temp_f``);
    - ``physics_usable``: whether the integrator's duration may be
      served as an estimate; None, when the compressor is calibrated
      (a positive constant);
    - ``recovery_model``: the correction to the physics recovery; None,
      the physics alone;
    - ``low_confidence_floor``: a recovery whose confidence is below it
      carries ``recovery_low_confidence``.

    It counts, as it goes, the recoveries whose integration stopped at
    its bound short of the target (``truncated_recoveries``) and those
    whose integrator raised (``failed_recoveries``, the last error in
    ``last_failure``): what a caller outside the core reports, since the
    core logs nothing. Counted once a recovery asked, from
    its last refinement pass, served or not; nothing it answers depends
    on them.
    """

    def __init__(
        self,
        params: HeaterParams,
        t_amb_series: pd.DataFrame,
        humidity: float | None,
        *,
        draws_on: bool,
        tau_gap_hours: float,
        flowing_draws: FlowingDraws | None = None,
        draw_inlet_temp_f: float | None = None,
        physics_usable: bool | None = None,
        recovery_model: RecoveryModel | None = None,
        low_confidence_floor: float = 0.0,
    ) -> None:
        self.params = params
        #: The inlet a draw is priced at; None given: the parameters'
        #: reference.
        self.draw_inlet_temp_f = (
            params.draw.inlet_temp_f
            if draw_inlet_temp_f is None
            else draw_inlet_temp_f
        )
        #: The draws that flow over a coast.
        self.flowing_draws = flowing_draws
        self.tau_gap_hours = tau_gap_hours
        self.physics_usable = (
            params.compressor.compressor_constant > 0.0
            if physics_usable is None
            else physics_usable
        )
        self.recovery_model = recovery_model
        self.low_confidence_floor = low_confidence_floor
        self.series = t_amb_series
        self.ambient = AmbientSampler(t_amb_series)
        self.humidity = humidity
        self.draws_on = draws_on
        #: Recoveries served whose integration hit its bound.
        self.truncated_recoveries = 0
        #: Recoveries served whose integrator raised, and the last error.
        self.failed_recoveries = 0
        self.last_failure: str | None = None

    def coast(
        self,
        start: datetime,
        upper_f: float,
        lower_f: float,
        end: datetime,
        draws: Sequence[Delivered | Draw],
        heated_at: datetime | None = None,
        draw_lower: bool = True,
    ) -> Coast:
        p = self.params
        flowing = (
            self.flowing_draws(start, end)
            if self.flowing_draws is not None
            else ()
        )
        decay = project_decay(
            t_upper_now=upper_f,
            t_lower_now=lower_f,
            t_amb_series=self.series,
            ua_btu_hr_f=(
                p.loss.ua_btu_hr_f
                if p.loss.ua_btu_hr_f is not None
                else p.loss.ua_baseline_btu_hr_f
            ),
            ua_exponent=p.loss.ua_exponent,
            ua_ref_delta_t=p.loss.ua_ref_delta_t_f,
            tau_gap_hours=self.tau_gap_hours,
            target_time=end,
            now=start,
            lower_gate_f=p.draw.lower_gate_f,
            pool_f_per_hour=p.draw.pool_f_per_hour,
            ungated_observability=p.draw.ungated_observability,
            last_heated_at=heated_at,
            draws=[*draws, *flowing],
            draw_observability=(
                p.draw.observability if self.draws_on else None
            ),
            draw_inlet_temp_f=self.draw_inlet_temp_f,
            tmv_delivery_intercept_f=p.draw.delivery_intercept_f,
            tmv_delivery_slope=p.draw.delivery_slope,
            draw_gap_open_f_per_gal=p.draw.gap_open_f_per_gal,
            draw_lower=draw_lower,
            ambient=self.ambient,
            tank=p.tank,
        )
        return Coast(
            [Point(at, up, lo) for at, up, lo in decay.trajectory],
            decay.impulses,
            draw_volume_gal=decay.draw_volume_gal,
            draw_heat_btu=decay.draw_heat_btu,
            flowing_heat_btu=decay.flowing_heat_btu,
            ambient_mean_f=decay.t_amb_mean,
        )

    def _predict(
        self,
        start: datetime,
        upper_f: float,
        lower_f: float,
        target_f: float,
        hold_minutes: float = 0.0,
        draw_load: float = 0.0,
    ) -> Recovery | None:
        """The recovery from an injected state: one pass with the air at
        the heater at the start, a second with its mean over the recovery
        the first found."""
        amb = self.ambient.at(start)
        prediction: Recovery | None = None
        # The engine's walk takes every draw itself, so each recovery is
        # a draw-free model's: one trained on all cycles carries the
        # average draw time, which the walk would then count twice. The
        # ``recovery_model`` given is expected to be draw-free.
        heat_minutes = 0.0
        physics: PhysicsRecovery | None = None
        for _ in range(2):
            mean = ambient_window_mean(
                self.series, start, start + timedelta(minutes=heat_minutes)
            )
            t_amb_mean = mean if mean is not None else amb
            prediction = recovery(
                RecoveryContext(
                    t_start_lower=lower_f,
                    t_start_upper=upper_f,
                    target_f=target_f,
                    t_amb_start=amb,
                    t_amb_mean=t_amb_mean,
                    h_amb_start=self.humidity,
                    start_hold_minutes=hold_minutes,
                    draw_load=draw_load,
                    physics=(
                        physics := physics_recovery(
                            t_start_lower=lower_f,
                            t_start_upper=upper_f,
                            target_f=target_f,
                            t_amb_mean=t_amb_mean,
                            h_amb_start=self.humidity,
                            compressor=self.params.compressor,
                            loss=self.params.loss,
                            usable=self.physics_usable,
                            record_path=True,
                            tank=self.params.tank,
                        )
                    ),
                ),
                model=self.recovery_model,
            )
            if prediction is None:
                break
            if abs(prediction.minutes - heat_minutes) <= REFINE_TOL_MINUTES:
                break
            heat_minutes = prediction.minutes
        if physics is not None:
            self._count(physics)
        return prediction

    def _count(self, physics: PhysicsRecovery) -> None:
        """A recovery's integration, counted for the caller to report."""
        if physics.truncated:
            self.truncated_recoveries += 1
        if physics.failed is not None:
            self.failed_recoveries += 1
            self.last_failure = physics.failed

    def heat(
        self,
        start: datetime,
        upper_f: float,
        lower_f: float,
        target_f: float,
        hold_minutes: float = 0.0,
        draw_load: float = 0.0,
    ) -> Heat | None:
        first = Point(start, upper_f, lower_f, 0.0)
        if lower_f >= target_f:
            return Heat([first], 1.0)
        p = self._predict(
            start, upper_f, lower_f, target_f, hold_minutes, draw_load
        )
        if p is None:
            return None
        power = self.params.power
        # The served recovery's own reasons (a truncated integration,
        # a model's diagnostics), and this tank's confidence flag.
        reasons: tuple[str, ...] = (*p.reasons,) + (
            ("recovery_low_confidence",)
            if p.confidence < self.low_confidence_floor
            else ()
        )
        # When the physics path is not the served recovery: none at all,
        # or the model clamped the duration
        # (``sim.heat_pump_recovery._path_publishable`` leaves no path then).
        if p.path is not None:
            points = [
                Point(pt.at, pt.t_upper_f, pt.t_lower_f, pt.input_energy_wh)
                for pt in build_heating_trajectory(
                    p.path,
                    served_minutes=p.minutes,
                    start_at=start,
                    t_upper_start=upper_f,
                    t_lower_start=lower_f,
                    two_zone=self.params.compressor.two_zone,
                    power_scale=power.power_scale,
                    cop_scale=power.cop_scale,
                    cop_lift_coeff=power.cop_lift_coeff,
                    cop_lift_ref_f=power.cop_lift_ref_f,
                    t_amb=p.context.t_amb_mean,
                    hold_minutes=p.start_hold_minutes,
                    tank=self.params.tank,
                )
            ]
            points[0] = first
            return Heat(points, p.confidence, reasons)
        # No path to follow: the served duration, a straight line in the
        # lower zone after the start's hold, and no energy rather than an
        # invented one.
        hold = min(max(p.start_hold_minutes, 0.0), max(p.minutes, 0.0))
        minutes = max(p.minutes, 0.0) - hold
        steps = max(1, math.ceil(minutes / 10.0))
        points = [first]
        if hold > 0.0:
            points.append(
                Point(start + timedelta(minutes=hold), upper_f, lower_f, None)
            )
        for i in range(1, steps + 1):
            f = i / steps
            lower = lower_f + (target_f - lower_f) * f
            points.append(
                Point(
                    start + timedelta(minutes=hold + minutes * f),
                    max(upper_f, lower),
                    lower,
                    None,
                )
            )
        return Heat(points, p.confidence, reasons, linear=True)

    def draw(
        self, at: datetime, upper_f: float, lower_f: float, gal: float
    ) -> tuple[float, float]:
        d = self.params.draw
        # As in ``coast``: with draws off, a draw does not move the tank.
        if not self.draws_on or d.observability is None:
            return upper_f, lower_f
        return draw_step(
            upper_f,
            lower_f,
            gal,
            draw_observability=d.observability,
            draw_inlet_temp_f=self.draw_inlet_temp_f,
            tmv_delivery_intercept_f=d.delivery_intercept_f,
            tmv_delivery_slope=d.delivery_slope,
            draw_gap_open_f_per_gal=d.gap_open_f_per_gal,
            tank=self.params.tank,
        )
