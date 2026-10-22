"""Phase 1: Standby decay projection.

Projects tank upper and lower temperatures forward in time using
the calibrated UA standby-loss ODE and exponential stratification
gap decay, charging the draws it is given (``sim.physics.draw``).

**Draws are the only water the projection takes.** Each is a ``Draw``:
its start, its gallons, and the temperature of the water replacing
them (its inflow), the inlet's unless it says otherwise. A draw with no
end is delivered at its onset through the mixing valve, as a fixture's
is; one with an end flows straight from the tank over its span, and its
inflow mixes into the lower zone. What a draw stands for is the
caller's.

Every input arrives as a value.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import NamedTuple

import numpy as np
import pandas as pd

from nwp500.sim.params import UA_REF_DELTA_T_F, TankParams
from nwp500.sim.physics.draw import (
    DEFAULT_INLET_TEMP_F,
    NO_VALVE_INTERCEPT_F,
    NO_VALVE_SLOPE,
    delivery_temp_f,
    draw_energy_btu,
    gap_opened_f,
    lower_zone_drop_f,
    withdrawn_gal,
)
from nwp500.sim.physics.tank import bottom_loss_drop_f, ua_at
from nwp500.sim.units import DEFAULT_AMBIENT_F, WATER_BTU_PER_GAL_F

#: A draw's inflow temperature, °F: a value, a function of the instant
#: the water comes in, or None, the inlet's.
Inflow = float | Callable[[datetime], float] | None


class Draw(NamedTuple):
    """Water through the tank: ``gallons`` from ``at``, replaced at the
    bottom by water at ``inflow_f``.

    - With no ``until``, the draw is **delivered** at its onset through
      the mixing valve: ``gallons`` is what the meter counts, blended,
      and the tank gives up the hot share of it (``physics.draw``).
      ``(at, gallons)`` alone is such a draw at the inlet, as every
      draw was before the inflow was explicit.
    - With ``until``, it **flows** straight from the tank: ``gallons``
      leave the top at ``gpm`` from ``at``, until they have all left or
      ``until`` comes, and the water replacing them mixes into the lower
      zone (``physics.draw.lower_zone_drop_f``). ``gpm`` None spreads
      them evenly to ``until``. ``gallons`` may not be more than
      ``gpm`` gives by ``until``.

    ``inflow_f`` None is the inlet (the projection's
    ``draw_inlet_temp_f``); a function is read at each instant water
    comes in.
    """

    at: datetime
    gallons: float
    inflow_f: Inflow = None
    until: datetime | None = None
    gpm: float | None = None


def _inflow_at(inflow: Inflow, at: datetime, inlet_f: float) -> float:
    """``inflow`` at ``at``, °F: the inlet's when it is None."""
    if inflow is None:
        return inlet_f
    if callable(inflow):
        return inflow(at)
    return inflow


@dataclass(frozen=True)
class _Flowing:
    """A flowing draw, on its own clock: minutes from ``at``."""

    at: datetime
    until: datetime
    gpm: float
    #: Minutes from ``at`` at which the last gallon has left: ``until``'s
    #: when the draw flows to its end.
    done_at: float
    #: The gallons it stops at before its end; None when it flows to
    #: its end, where it has given them.
    cap: float | None
    inflow: Inflow

    @classmethod
    def of(cls, d: Draw) -> _Flowing | None:
        """``d`` on its clock; None when no water moves."""
        assert d.until is not None
        span = (d.until - d.at).total_seconds() / 60.0
        if span <= 0.0 or d.gallons <= 0.0:
            return None
        gpm = d.gallons / span if d.gpm is None else d.gpm
        if gpm <= 0.0:
            return None
        flows = gpm * span
        if d.gallons > flows * (1.0 + 1e-9):
            raise ValueError(
                f"a draw of {d.gallons} gal at {gpm} gal/min cannot give "
                f"them by its end ({span} min)"
            )
        to_end = d.gallons >= flows
        return cls(
            at=d.at,
            until=d.until,
            gpm=gpm,
            # Flowing to its end, the draw is done there, not at
            # ``gallons / gpm``, which can round a hair short of it; and
            # it needs no cap, which would clip an integration piece
            # that ends a hair past it.
            done_at=span if to_end else d.gallons / gpm,
            cap=None if to_end else d.gallons,
            inflow=d.inflow_f,
        )

    def given(self, minutes: float) -> float:
        """Gallons the draw has given ``minutes`` after ``at``.

        A function of the draw's **own elapsed time**, which is what
        makes it composable: the volume a projection charges over a
        window is ``given(end) - given(start)``, and those increments
        telescope across adjacent windows. Charging each clipped
        window's own length instead re-applies the end of the flow per
        window, so a draw ending across a chained phase boundary is
        charged by both phases.
        """
        if minutes <= 0.0:
            return 0.0
        if self.cap is None:
            return self.gpm * minutes
        return min(self.gpm * minutes, self.cap)


class Impulse(NamedTuple):
    """A step change in the lower zone: an extraction's drop.

    ``at`` is the instant the drop is accounted at: a flowing draw's
    is the end of the integration step that charged it, a delivered
    draw's is its onset, which is in general *not* a trajectory
    instant.  ``lower_before`` is the lower zone just before the drop,
    ``lower_after`` just after; ``None`` means the trajectory's own
    value at ``at``, which is only meaningful for a drop that sits on
    a trajectory instant.
    """

    at: datetime
    lower_before: float
    lower_after: float | None = None


@dataclass
class DecayProjection:
    """Result of the Phase 1 standby decay projection."""

    t_upper: float  # °F at projected heating-start time
    t_lower: float  # °F at projected heating-start time
    stratification_gap: float  # t_upper − t_lower
    t_amb_at_start: float  # projected ambient at start
    t_amb_mean: float  # mean projected ambient over window
    projection_hours: float  # duration of projection
    #: Heat the flowing draws took out over the window, apparent BTU.
    #: 0.0 when none flowed in it.
    flowing_heat_btu: float = 0.0
    #: Delivered draws extracted over the window.  ``draw_volume_gal``
    #: is the **delivered** (metered) basis, so it reconciles with the
    #: metered figures a dashboard shows beside it; ``draw_heat_btu`` is
    #: the tank energy the *withdrawn* water carried away, after the
    #: mixing-valve conversion.  Both stay 0.0 when no draws were
    #: supplied, which the caller distinguishes from "none forecast"
    #: and may report as absent for a quiet scenario.
    draw_volume_gal: float = 0.0
    draw_heat_btu: float = 0.0
    #: The series held no usable reading, so the coast ran at
    #: ``DEFAULT_AMBIENT_F`` throughout (``AmbientSampler.defaulted``).
    ambient_defaulted: bool = False
    #: The path, not just where it ends: ``(at, t_upper, t_lower)`` at
    #: each integration boundary, first element the starting instant
    #: and last exactly ``target_time``.  A schedule optimiser needs
    #: *when* the lower zone crosses the on-threshold, which the
    #: end-state fields cannot say.
    trajectory: list[tuple[datetime, float, float]] = field(
        default_factory=list
    )
    #: Every extraction's drop, in time order: one per integration
    #: step that charged a flowing draw, at that step's end, and one per
    #: delivered draw, at its onset.  The trajectory's points sit on the
    #: grid and cannot show where inside a step the curve stepped down,
    #: so `threshold_crossing` walks these between the grid points: a
    #: crossing the drop caused is reported at the drop, and one the
    #: coast reached is interpolated over the coast segment it fell in,
    #: never rounded up to the next grid point, which a scheduler's
    #: use of the crossing cannot absorb.
    impulses: list[Impulse] = field(default_factory=list)


#: Sub-step, in minutes, for integrating a flowing draw's extraction.
#:
#: A draw of a few gallons can take roughly 2.7 °F with it in about
#: three minutes, so the tank the last gallons leave is materially
#: colder than the tank the first ones left.  Charging a whole step
#: at one temperature ignores that, and then a projection chained
#: mid-draw (which does see the drop across its split) disagrees
#: with the single projection over the same span.  Walking the
#: accrual in half-minute pieces makes both paths integrate the same
#: curve: it holds the disagreement to the same order as the quiet
#: coast's own discretisation, at a handful of extra multiplications
#: per draw.
_EXTRACTION_SUB_STEP_MIN = 0.5

#: Water, in gallons, per piece the gated charge (``lower_gate_f``) is
#: walked in: a tenth of a gallon, so a six-gallon draw is about sixty
#: pieces (``_extraction_pieces``).
_GATED_PIECE_GAL = 0.1


def project_decay(
    t_upper_now: float,
    t_lower_now: float,
    t_amb_series: pd.DataFrame,
    ua_btu_hr_f: float,
    tau_gap_hours: float,
    target_time: datetime,
    now: datetime,
    ua_exponent: float = 0.0,
    ua_ref_delta_t: float = UA_REF_DELTA_T_F,
    draws: Iterable[Draw | tuple[datetime, float]] | None = None,
    draw_observability: float | None = None,
    draw_inlet_temp_f: float = DEFAULT_INLET_TEMP_F,
    tmv_delivery_intercept_f: float = NO_VALVE_INTERCEPT_F,
    tmv_delivery_slope: float = NO_VALVE_SLOPE,
    draw_gap_open_f_per_gal: float = 0.0,
    draw_lower: bool = True,
    lower_gate_f: float = 0.0,
    pool_f_per_hour: float = 0.0,
    ungated_observability: float = 1.0,
    last_heated_at: datetime | None = None,
    ambient: AmbientSampler | None = None,
    tank: TankParams = TankParams(),
    bottom_loss_btu_hr: float = 0.0,
    bottom_gate_f: float = 1.0,
) -> DecayProjection:
    """Project tank temperatures forward to the target time.

    Uses Euler integration of the bulk decay ODE at 10-minute
    steps, with the stratification gap decaying exponentially.

    Args:
        t_upper_now: Current upper tank temperature (°F).
        t_lower_now: Current lower tank temperature (°F).
        t_amb_series: DataFrame with DatetimeIndex and column
            ``ambient_f`` containing projected ambient (the air
            at the heater).
        ua_btu_hr_f: Calibrated UA value (BTU/hr·°F).  When
            ``ua_exponent`` is non-zero this is the UA at
            ``ua_ref_delta_t`` rather than a flat constant.
        tau_gap_hours: Stratification gap decay time constant.
        target_time: When the tank must be ready (UTC).
        now: Current time (UTC).
        ua_exponent: Power-law exponent for ``UA(ΔT)``.  ``0.0`` (the
            default, and what older calibrations carry) reproduces the
            constant-UA behaviour exactly.  See ``sim.physics.tank``.
        ua_ref_delta_t: ΔT at which ``ua_btu_hr_f`` is quoted (°F).
        draws: The draws (``Draw``; a ``(at, gallons)`` pair is a
            delivered draw at the inlet). A delivered draw is charged
            at its onset, in ``[now, target)``. A flowing draw is
            charged for the part of it inside the window, from its own
            start even when that precedes ``now``. None or empty is
            the quiet tank.
        draw_observability: Share of a delivered draw's enthalpy the
            probes register. None, a tank with no draw calibration,
            charges no delivered draw; flowing draws are charged
            whatever it is.
        draw_inlet_temp_f: The inlet, °F: the inflow of a draw that
            names none.
        tmv_delivery_intercept_f: Mixing-valve delivery line,
            ``intercept + slope · t_upper`` (°F), evaluated at each
            delivered draw's upper zone.  The defaults are the legacy
            constant 128 °F; a calibration supplies the fitted line.
        tmv_delivery_slope: °F of delivery per °F of upper zone.
        draw_gap_open_f_per_gal: The front a withdrawn gallon of a
            delivered draw opens, °F.
        draw_lower: False leaves the lower zone where each delivered
            draw found it, and the upper zone takes the draw's own
            response (the gap restarting from the two): for a caller
            with a booked state, which takes the lower zone through a
            draw by the cold front instead.
            True, the default, is the draw as it always was.
        lower_gate_f: Where a flowing draw's heat lands
            (``sim.physics.draw.lower_zone_drop_f``). Set, the
            incoming water is mixed into the lower zone alone, gated
            on the gap, and the upper zone does not move. ``0.0``
            charges ``ungated_observability`` of the heat the water
            leaving carries above its inflow to both zones alike.
        pool_f_per_hour: The standby pool, °F of reach per hour the
            tank has stood unheated
            (``sim.physics.draw.DEFAULT_POOL_F_PER_HOUR``). Only with
            ``lower_gate_f``; ``0.0`` is the gap alone.
        ungated_observability: Share of a flowing draw's heat the
            apparent-frame tank registers under the ungated charge.
            ``1.0`` charges the whole of it.
        last_heated_at: When the heater last stopped heating (the
            compressor's last off-edge), which the pool is counted
            from. None, unknown or never seen, charges no pool.
        ambient: ``t_amb_series``'s sampler, already built: a caller
            coasting many times over one series builds it once. None
            builds it here; the answer is the same.
        tank: The tank, whose thermal mass the bulk is charged against
            and whose lower zone a flowing draw's inflow mixes into.
        bottom_loss_btu_hr: Heat lost into the lower zone, BTU/hr
            (``LossParams.bottom_loss_btu_hr``), of which the lower
            probe sees ``sim.physics.tank.bottom_loss_reach`` at the
            gap: it falls the lower zone alone and opens the gap.
            ``0.0``, the default, is none, and the walk is the one
            before it to the bit.
        bottom_gate_f: The gap at which the probe sees ``1 - 1/e`` of
            the bottom loss, °F.

    Returns:
        DecayProjection with projected temperatures at the
        target time.
    """
    thermal_mass_btu_f = tank.thermal_mass_btu_f
    projection_hours = (target_time - now).total_seconds() / 3600.0

    # If target is now or in the past, return current state
    if projection_hours <= 0:
        return DecayProjection(
            t_upper=t_upper_now,
            t_lower=t_lower_now,
            stratification_gap=t_upper_now - t_lower_now,
            t_amb_at_start=_get_t_amb(t_amb_series, now),
            t_amb_mean=_get_t_amb(t_amb_series, now),
            projection_hours=0.0,
            ambient_defaulted=(
                AmbientSampler(t_amb_series) if ambient is None else ambient
            ).defaulted,
            # The degenerate projection is the one exception to the
            # trajectory invariants: a single point at the starting
            # instant, because there is no interval to walk.
            trajectory=[(now, t_upper_now, t_lower_now)],
        )

    # Initial conditions
    t_bulk = (t_upper_now + t_lower_now) / 2.0
    gap_0 = t_upper_now - t_lower_now

    # Integration boundaries.  The last step is **shortened** so the
    # walk ends exactly at ``target_time``: the old `ceil` took whole
    # steps and projected an unaligned target up to ten minutes past
    # itself, answering a slightly later question than it was asked.
    step_hours, step_ends = _step_grid(now, target_time, projection_hours)
    ua_is_flat = ua_exponent == 0.0
    decay_rate = ua_btu_hr_f / thermal_mass_btu_f

    # The gap relaxes from a *reference*, not from the start. With no
    # draws the reference never moves and this is the closed form it
    # replaces, evaluated on the same numbers, so the quiet path is
    # bit-identical.
    #
    # A draw moves the reference: it opens the gap, and the relaxation
    # restarts from the wider one. Without this the gap could only
    # ever close, and a front the model exists to represent would
    # decay as if it had always been there.
    gap_ref = gap_0
    gap_ref_at = 0.0

    # The standby pool (``sim.physics.draw.lower_zone_drop_f``): how
    # long the tank has stood unheated at each instant, read off the
    # clock from when it last heated, so a chain cut anywhere computes
    # it identically. Unknown, or a heater never seen to stop, is no
    # pool, the gap alone.
    heated_h0 = (
        (now - last_heated_at).total_seconds() / 3600.0
        if last_heated_at is not None and pool_f_per_hour > 0.0
        else None
    )

    def pool_at(elapsed: float) -> float:
        """The standby pool's share of the reach, °F, ``elapsed`` hours
        into the projection."""
        if heated_h0 is None:
            return 0.0
        return pool_f_per_hour * max(0.0, heated_h0 + elapsed)

    def gap_at(elapsed: float) -> float:
        """The stratification gap after ``elapsed`` hours."""
        return max(
            gap_ref * float(np.exp(-(elapsed - gap_ref_at) / tau_gap_hours)),
            0.0,
        )

    # Ambient is averaged by **duration**, not by sample count.  The
    # steps are no longer all the same length (the last one is
    # shortened so the walk ends exactly at `target_time`), so a mean
    # over one sample per step would give a one-second tail the same
    # weight as a full ten minutes, and `t_amb_mean` would stop
    # describing the window it is documented as describing.  It feeds
    # the recovery physics downstream, so this is not only a display
    # field.
    t_amb_hour_degrees = 0.0
    flowing_heat_btu = 0.0
    draw_heat_btu = 0.0
    draw_volume_total = 0.0
    given = [Draw(*d) for d in draws or ()]  # pyright: ignore[reportArgumentType]
    # Delivered draws, sorted by onset and then gallons so the result
    # cannot depend on the order the caller listed them in.
    # `draw_observability is None` is a tank with no draw
    # calibration, and disables the term outright rather than
    # guessing at one.
    delivered = (
        sorted(
            (d for d in given if d.until is None),
            key=lambda d: (d.at, d.gallons),
        )
        if draw_observability is not None
        else []
    )
    # Flowing draws, **not** clipped to the window.  The volume given
    # is a function of a draw's own elapsed time, so the charge for a
    # window is the increment of that curve across it, and computing
    # the increment needs the true start, even when it precedes
    # ``now``.  In start order (stable), which is what makes the walk
    # below well defined: charges inside a step are priced
    # sequentially, each against a tank the earlier ones have already
    # cooled.
    flowing = sorted(
        (
            f
            for f in (_Flowing.of(d) for d in given if d.until is not None)
            if f is not None
        ),
        key=lambda f: f.at,
    )

    trajectory: list[tuple[datetime, float, float]] = [
        (now, t_upper_now, t_lower_now)
    ]
    impulses: list[Impulse] = []
    amb = AmbientSampler(t_amb_series) if ambient is None else ambient

    elapsed_hours = 0.0
    current_time = now
    for dt_hours, step_end in zip(step_hours, step_ends, strict=True):
        step_start = current_time
        t_amb_step = amb.at(step_start)
        t_amb_hour_degrees += t_amb_step * dt_hours
        # What the flowing draws took off the lower zone in this step,
        # for the impulse record at its end: the bulk's fall under the
        # ungated charge, the lower zone's own under the gated one.
        flow_drop_step = 0.0

        # **The step is partitioned at every draw onset inside it, and
        # each partition is integrated in turn.**  A draw used to be
        # charged in full by the end of the step containing its
        # onset, which placed it anywhere up to ten minutes late, and
        # *where* inside the step it fell depended on the grid, which
        # is anchored to `now`.  A chained projection cut off-grid
        # therefore applied the same draw at a different instant,
        # against a tank that had coasted a different distance and
        # with the front restarting from a different elapsed time.
        # Those are three separate grid-dependent quantities, all
        # scaling with draw volume, and at three times the corpus
        # rate they put chained and single projections 0.11 °F apart.
        # Charging at the onset makes every one of them a function of
        # the clock.  With no draws in the step
        # there is one partition and the arithmetic is the quiet
        # path's, unchanged.
        cuts = sorted({d.at for d in delivered if step_start < d.at < step_end})
        points = [step_start, *cuts, step_end]
        sub_elapsed = elapsed_hours
        last = len(points) - 2
        for i, (sub_start, sub_end) in enumerate(pairwise(points)):
            if i == last:
                # The last partition takes what is left so the pieces
                # sum to the step exactly, and with no draws in the
                # step this is `dt_hours - 0.0`, the quiet path's own
                # step to the bit.
                sub_dt = dt_hours - (sub_elapsed - elapsed_hours)
            else:
                sub_dt = (sub_end - sub_start).total_seconds() / 3600.0

            # Delivered draws at this instant, before the coast that
            # follows them.  An event sits at its slot's `valid_at`,
            # and a draw on a phase boundary is charged by exactly one
            # phase of a chain, so a chained pair sums to the single
            # projection exactly: the phases partition the onsets
            # between them, `[now, target)`, and neither splits one.
            # The order of coincident events is left to the
            # implementation because no consumer can see it.
            for d in delivered:
                if d.at != sub_start:
                    continue
                delivered_gal = d.gallons
                inflow_f = _inflow_at(d.inflow_f, d.at, draw_inlet_temp_f)
                gap_here = gap_at(sub_elapsed)
                t_upper_here = t_bulk + gap_here / 2.0
                t_lower_here = t_bulk - gap_here / 2.0
                t_delivery = delivery_temp_f(
                    t_upper_here,
                    tmv_delivery_intercept_f,
                    tmv_delivery_slope,
                )
                energy = draw_energy_btu(
                    delivered_gal,
                    t_upper_here,
                    t_delivery,
                    inflow_f,
                    draw_observability
                    if draw_observability is not None
                    else 0.0,
                )
                draw_volume_total += delivered_gal
                if energy <= 0.0:
                    continue
                draw_heat_btu += energy
                bulk_drop = energy / thermal_mass_btu_f
                t_bulk -= bulk_drop
                # The front: cold in at the bottom widens the gap, and
                # the relaxation restarts from the wider one. The drop
                # this draw just caused is passed in because the gap
                # is split evenly about the bulk, so an opening wider
                # than twice the drop would *raise* the upper zone,
                # which no draw can do, and which the fitted
                # coefficient produces below about 122 °F without the
                # bound.
                opened = gap_opened_f(
                    withdrawn_gal(
                        delivered_gal,
                        t_upper_here,
                        t_delivery,
                        inflow_f,
                    ),
                    draw_gap_open_f_per_gal,
                    bulk_drop,
                    t_lower_here,
                    inflow_f,
                )
                if opened > 0.0:
                    gap_ref = gap_at(sub_elapsed) + opened
                    gap_ref_at = sub_elapsed
                if not draw_lower:
                    # The lower zone stays where the draw found it, the
                    # upper takes its response: no drop to report. A
                    # small gap does not invert: the lower zone is no
                    # warmer than the upper.
                    upper_after = t_bulk + gap_at(sub_elapsed) / 2.0
                    lower_after = min(t_lower_here, upper_after)
                    t_bulk = (upper_after + lower_after) / 2.0
                    gap_ref = upper_after - lower_after
                    gap_ref_at = sub_elapsed
                    continue
                # The drop, where it happened.  The front is part of
                # it: the lower zone after is read off the widened gap.
                impulses.append(
                    Impulse(
                        sub_start,
                        t_lower_here,
                        t_bulk - gap_at(sub_elapsed) / 2.0,
                    )
                )

            if bottom_loss_btu_hr > 0.0:
                # The bottom loss over the partition, charged at its
                # start as a flowing draw's inflow is: the lower zone
                # alone, so the bulk falls half the drop, the gap opens
                # by all of it, and the upper zone does not move.
                gap_here = gap_at(sub_elapsed)
                bottom_drop = bottom_loss_drop_f(
                    bottom_loss_btu_hr,
                    gap_here,
                    bottom_gate_f,
                    sub_dt,
                    tank.lower_zone_thermal_mass_btu_f,
                )
                if bottom_drop > 0.0:
                    t_bulk -= bottom_drop / 2.0
                    gap_ref = gap_here + bottom_drop
                    gap_ref_at = sub_elapsed

            t_amb = t_amb_step if i == 0 else amb.at(sub_start)
            # Bulk tank decay: dT/dt = -(UA/mc_p)(T − T_amb).  Over a
            # long coast the tank crosses most of the ΔT range, so UA
            # has to be re-evaluated per step rather than hoisted out
            # of the walk.
            delta_t = t_bulk - t_amb
            if not ua_is_flat:
                decay_rate = (
                    ua_at(delta_t, ua_btu_hr_f, ua_exponent, ua_ref_delta_t)
                    / thermal_mass_btu_f
                )
            bulk_at_sub_start = t_bulk
            coast_drop = decay_rate * delta_t * sub_dt
            t_bulk -= coast_drop
            bulk_after_coast = t_bulk

            # Flowing draws, charged for the part of each that falls
            # inside this partition.  Two invariants a consumer can see:
            # no projection charges water that has not moved, so a
            # target falling mid-draw reports the tank as it will be;
            # and chaining is an accounting identity in
            # *volume*: the given-volume curve telescopes exactly at
            # any split, aligned to the step grid or not.
            #
            # Heat is that volume times a price.  The price is the
            # tank at the instant the water left, less the inflow at
            # that same instant, both read off the clock, so a split
            # that re-anchors the grid does not move either.  See the
            # sub-step walk below for what pricing on the grid cost.
            for f in flowing:
                lo = max(sub_start, f.at)
                hi = min(sub_end, f.until)
                if hi <= lo:
                    continue
                to_lo = (lo - f.at).total_seconds() / 60.0
                to_hi = (hi - f.at).total_seconds() / 60.0
                increment = f.given(to_hi) - f.given(to_lo)
                if increment <= 0.0:
                    continue
                # Extraction is integrated in sub-steps, sequentially,
                # against a bulk that already carries what this draw
                # has taken.  A single charge per step prices every
                # gallon at one temperature and ignores the 2.7 °F its
                # own first gallons just removed, so a chained
                # projection, which does see that drop across its
                # split, disagreed with the single projection by
                # 0.035 °F while the same split with the term off
                # differed by 4e-5 °F.  The gap was the accounting,
                # not the physics.
                #
                # Water moves until the draw has given its gallons, so
                # only that part is walked; the rest of the overlap
                # moves none.
                accrual_end = min(to_hi, max(to_lo, f.done_at))
                n_sub = max(
                    1,
                    int(
                        np.ceil(
                            (accrual_end - to_lo) / _EXTRACTION_SUB_STEP_MIN
                        )
                    ),
                )
                sub_min = (accrual_end - to_lo) / n_sub
                energy = 0.0
                lower_drop = 0.0
                for a, b in _extraction_pieces(
                    to_lo,
                    accrual_end,
                    n_sub,
                    sub_min,
                    gated_piece_min=(
                        _GATED_PIECE_GAL / f.gpm if lower_gate_f > 0.0 else None
                    ),
                ):
                    sub_gal = f.given(b) - f.given(a)
                    if sub_gal <= 0.0:
                        continue
                    left_at = f.at + timedelta(minutes=(a + b) / 2.0)
                    # Where in this partition the water left, as a
                    # fraction.  `t_bulk` is the tank at the *end* of
                    # the partition's coast less every extraction
                    # charged so far, so the coast not yet taken at
                    # this instant is added back, which makes the
                    # price a function of the clock rather than of
                    # where the 10-minute grid happens to fall.
                    into_sub = (left_at - sub_start).total_seconds() / 3600.0
                    frac = (
                        min(1.0, max(0.0, into_sub / sub_dt))
                        if sub_dt > 0.0
                        else 1.0
                    )
                    price_bulk = t_bulk + (
                        bulk_at_sub_start - bulk_after_coast
                    ) * (1.0 - frac)
                    t_upper_sub = (
                        price_bulk + gap_at(sub_elapsed + into_sub) / 2.0
                    )
                    # The inflow at the same instant, not at the step
                    # start.  A step-start sample was the last
                    # grid-anchored quantity in the price: an inflow
                    # following the 26 °F daily swing of the air at
                    # the reference heater differs by up to about 1 °F
                    # across a step, a tenth of a degree of tank per
                    # draw, and a cut moved it.
                    inflow_f = _inflow_at(f.inflow, left_at, draw_inlet_temp_f)
                    if lower_gate_f > 0.0:
                        # The inflow comes in at the bottom: the lower
                        # zone takes the water, and how much of it the
                        # thermistor sees depends on the gap at this
                        # instant, so a chain cut mid-draw reads the
                        # same state the single projection does.
                        at_h = sub_elapsed + into_sub
                        gap_here = gap_at(at_h)
                        drop = lower_zone_drop_f(
                            sub_gal,
                            price_bulk - gap_here / 2.0,
                            inflow_f,
                            gap_here,
                            lower_gate_f,
                            pool_f=pool_at(at_h),
                            tank=tank,
                        )
                        if drop <= 0.0:
                            continue
                        # The lower zone alone: the bulk falls half
                        # the drop and the gap opens by all of it, so
                        # the upper zone does not move.
                        t_bulk -= drop / 2.0
                        gap_ref = gap_here + drop
                        gap_ref_at = at_h
                        # The heat is the lower zone's mass by the drop
                        # (``TankParams.lower_zone_share``): the
                        # literal half it replaces, to the bit.
                        energy += drop * tank.lower_zone_thermal_mass_btu_f
                        lower_drop += drop
                        continue
                    # Ungated: the heat the water leaving carries above
                    # its inflow, of which only the share the
                    # thermistors register is charged, to both zones.
                    sub_energy = ungated_observability * max(
                        0.0,
                        sub_gal
                        * WATER_BTU_PER_GAL_F
                        * (t_upper_sub - inflow_f),
                    )
                    energy += sub_energy
                    t_bulk -= sub_energy / thermal_mass_btu_f
                flowing_heat_btu += energy
                flow_drop_step += (
                    lower_drop
                    if lower_gate_f > 0.0
                    else energy / thermal_mass_btu_f
                )

            sub_elapsed += sub_dt

        elapsed_hours += dt_hours
        gap_now = gap_at(elapsed_hours)
        lower_now = t_bulk - gap_now / 2.0
        # A flowing draw's heat is accounted at the end of the step
        # that charged it (the one charge not placed at its own
        # instant), so the drop is recorded there, its size the step's
        # flowing extraction.  Only a charge that moved the tank is an impulse:
        # a tank colder than the inflow gains nothing from it, the
        # clamp above makes the energy zero, and recording that as a
        # drop would make `threshold_crossing` report a step boundary
        # for a slide that was continuous throughout.
        if flow_drop_step > 0.0:
            impulses.append(
                Impulse(step_end, lower_now + flow_drop_step, lower_now)
            )
        trajectory.append((step_end, t_bulk + gap_now / 2.0, lower_now))
        current_time = step_end

    # The value *at* the target, for `t_amb_at_start`.  It is
    # deliberately not folded into the mean above: it is an instant,
    # covering no part of the window, and adding it as one more equal
    # sample is what the weighting is here to stop.
    t_amb_final = amb.at(target_time)

    # One closed form for the gap, evaluated in `gap_at` above and
    # reused here, so the trajectory's last point and these fields
    # cannot disagree.
    gap_final = gap_at(projection_hours)
    t_upper_final = t_bulk + gap_final / 2.0
    t_lower_final = t_bulk - gap_final / 2.0

    t_amb_mean = t_amb_hour_degrees / projection_hours

    return DecayProjection(
        t_upper=t_upper_final,
        t_lower=t_lower_final,
        stratification_gap=gap_final,
        t_amb_at_start=t_amb_final,
        t_amb_mean=t_amb_mean,
        projection_hours=projection_hours,
        flowing_heat_btu=flowing_heat_btu,
        draw_volume_gal=draw_volume_total,
        draw_heat_btu=draw_heat_btu,
        ambient_defaulted=amb.defaulted,
        trajectory=trajectory,
        impulses=impulses,
    )


def _step_grid(
    now: datetime, target_time: datetime, projection_hours: float
) -> tuple[list[float], list[datetime]]:
    """The projection's steps: their lengths, hours, and their ends."""
    full_dt = 10.0 / 60.0
    # `ceil` on a float ratio is the trap here.  Ten minutes is not
    # representable in binary, so for 55 of the 168 whole-step
    # horizons up to a week `projection_hours / full_dt` lands a few
    # ulp *above* the integer (50 minutes divides to 5.000000000000001),
    # and the walk took one more step of about 1e-16 hours.  That
    # step charges nothing and decays nothing, so the arithmetic was
    # unharmed, but it appended a second trajectory element at a
    # timestamp equal to the one before it once rounded to
    # microseconds: a consumer plotting the path saw a duplicate, and
    # a consumer chaining from the "last element" saw a zero-length
    # final phase.  The tolerance is in *steps*, and one part in a
    # billion of a step is nine orders of magnitude above the float
    # error and nine below anything a caller could mean.
    n_steps = max(1, int(np.ceil(projection_hours / full_dt - 1e-9)))
    step_hours = [full_dt] * n_steps
    step_hours[-1] = projection_hours - full_dt * (n_steps - 1)
    # Boundaries taken from `now` and `target_time` rather than
    # accumulated: the interior ones are exact multiples of the step
    # and the last one *is* `target_time`, so "the last element sits
    # exactly at target_time" is true by construction instead
    # of by the luck of float addition.
    step_ends = [
        now + timedelta(hours=full_dt * (i + 1)) for i in range(n_steps - 1)
    ] + [target_time]
    return step_hours, step_ends


def partitions(
    now: datetime, target_time: datetime, onsets: Iterable[datetime]
) -> list[tuple[datetime, datetime]]:
    """The spans ``project_decay`` from ``now`` to ``target_time`` walks,
    in order: its steps, each cut at every delivered draw's onset inside
    it (``onsets``, the draws it charges). Empty for no window.

    For a caller adding up a quantity over the window as the projection
    does, partition by partition, so its floats are the projection's.
    """
    projection_hours = (target_time - now).total_seconds() / 3600.0
    if projection_hours <= 0:
        return []
    _, step_ends = _step_grid(now, target_time, projection_hours)
    at = set(onsets)
    spans: list[tuple[datetime, datetime]] = []
    step_start = now
    for step_end in step_ends:
        cuts = sorted({t for t in at if step_start < t < step_end})
        spans.extend(pairwise([step_start, *cuts, step_end]))
        step_start = step_end
    return spans


def _extraction_pieces(
    to_lo: float,
    accrual_end: float,
    n_sub: int,
    sub_min: float,
    *,
    gated_piece_min: float | None,
) -> list[tuple[float, float]]:
    """A flowing draw's accrual from ``to_lo`` to ``accrual_end``
    minutes into it, in the pieces the extraction is integrated over.

    The ungated charge divides the span evenly into ``n_sub`` pieces,
    and its arithmetic is kept to the bit. The gated one
    (``lower_gate_f``) is an ODE in the volume given, since each
    piece's drop opens the gap the next is gated on, so it is walked in
    pieces of ``gated_piece_min``, a fixed volume, cut on the draw's own
    clock. Half-minute pieces were too coarse for it: at 2.24 gal/min a
    piece is 1.1 gal, and a chain cut 0.3 min into a draw moved the
    lower zone 0.13 °F off the single projection. On the draw's clock a
    cut adds one boundary and moves none.
    """
    if gated_piece_min is None:
        return [
            (to_lo + sub_min * k, to_lo + sub_min * k + sub_min)
            for k in range(n_sub)
        ]
    first = int(np.floor(to_lo / gated_piece_min)) + 1
    last = int(np.ceil(accrual_end / gated_piece_min))
    inner = [
        k * gated_piece_min
        for k in range(first, last)
        if to_lo < k * gated_piece_min < accrual_end
    ]
    return list(pairwise([to_lo, *inner, accrual_end]))


def draw_step(
    t_upper: float,
    t_lower: float,
    delivered_gal: float,
    *,
    draw_observability: float,
    draw_inlet_temp_f: float = DEFAULT_INLET_TEMP_F,
    tmv_delivery_intercept_f: float = NO_VALVE_INTERCEPT_F,
    tmv_delivery_slope: float = NO_VALVE_SLOPE,
    draw_gap_open_f_per_gal: float = 0.0,
    tank: TankParams = TankParams(),
) -> tuple[float, float]:
    """The tank just after one delivered draw, as ``project_decay``
    charges it at an onset: the heat the withdrawn water carried out of
    the bulk, and the front it opens at the bottom.

    For a draw that lands inside a recovery, where the
    tank is not coasting and the integrator above does not run. The
    arithmetic is the coast's, term for term, so a draw costs the tank
    the same whichever kind of segment it falls in.
    ``draw_inlet_temp_f`` is the draw's inflow, the inlet's for a
    fixture.
    """
    bulk = (t_upper + t_lower) / 2.0
    gap = t_upper - t_lower
    t_delivery = delivery_temp_f(
        t_upper, tmv_delivery_intercept_f, tmv_delivery_slope
    )
    energy = draw_energy_btu(
        delivered_gal,
        t_upper,
        t_delivery,
        draw_inlet_temp_f,
        draw_observability,
    )
    if energy <= 0.0:
        return t_upper, t_lower
    bulk_drop = energy / tank.thermal_mass_btu_f
    bulk -= bulk_drop
    opened = gap_opened_f(
        withdrawn_gal(delivered_gal, t_upper, t_delivery, draw_inlet_temp_f),
        draw_gap_open_f_per_gal,
        bulk_drop,
        t_lower,
        draw_inlet_temp_f,
    )
    gap = max(gap, 0.0) + max(opened, 0.0)
    return bulk + gap / 2.0, bulk - gap / 2.0


def threshold_crossing(
    trajectory: list[tuple[datetime, float, float]],
    threshold: float,
    impulses: Iterable[Impulse] | None = None,
) -> datetime | None:
    """When ``t_lower`` first falls below ``threshold``.

    Linearly interpolated inside the coast segment that contains the
    crossing, so the answer is not quantised to the trajectory's
    sample interval. Without that it could run a whole step late,
    which is more than the scheduler's use of it can absorb.

    **The curve between two trajectory points is a slide with drops in
    it.**  The tank coasts continuously, and each extraction lands as a
    step change at its own instant (a flowing draw's at the end of the
    step that charged it, a delivered draw's at its onset), so the path is
    coast, drop, coast, drop, coast.  The walk follows it in that
    order: a crossing that lies on a coast segment is interpolated
    over that segment, between the drops on either side of it, and a
    crossing a drop caused is reported at the drop and nowhere else.
    Interpolating through a drop would report a crossing minutes
    before anything happened; rounding a coast crossing up to the
    next grid point would report it up to a step late, which the
    scheduler cannot absorb.

    A start already below the threshold returns the starting instant,
    which is also what makes the degenerate single-point projection
    answer correctly rather than returning ``None``.

    Returns ``None`` when the tank stays above the threshold for the
    whole projection.
    """
    if not trajectory:
        return None
    if trajectory[0][2] < threshold:
        return trajectory[0][0]

    drops = sorted(impulses or (), key=lambda i: i.at)

    def interpolate(
        t0: datetime, lower0: float, t1: datetime, lower1: float
    ) -> datetime:
        span = lower0 - lower1
        if span <= 0:
            return t1
        return t0 + (t1 - t0) * ((lower0 - threshold) / span)

    for (t0, _, lower0), (t1, _, lower1) in pairwise(trajectory):
        cur_t, cur_lower = t0, lower0
        # A drop on the segment's start instant belongs to it (a draw
        # at a grid point is charged before the coast that follows),
        # and one on its end instant is the flowing accounting boundary.
        # A drop already walked from the previous segment's end is
        # seen again here with nothing left to cross, harmlessly.
        for drop in drops:
            if not t0 <= drop.at <= t1:
                continue
            if drop.lower_before < threshold:
                return interpolate(cur_t, cur_lower, drop.at, drop.lower_before)
            after = drop.lower_after
            if after is None:
                after = lower1 if drop.at == t1 else drop.lower_before
            if after < threshold:
                return drop.at
            cur_t, cur_lower = drop.at, after
        if lower1 < threshold:
            return interpolate(cur_t, cur_lower, t1, lower1)
    return None


class AmbientSampler:
    """Ambient temperature (the air at the heater) as a function of
    the clock.

    Built once per projection: the index is validated, cleaned and
    converted to seconds a single time, and every lookup after that is
    one `searchsorted`.  The per-call form, `_get_t_amb`, used to do
    all of that on every step, which was affordable at one lookup a
    step and is not at one per flowing draw's sub-step.

    **Ambient is a function of the clock, not of the step grid.**  The
    lookup used to return the *nearest* sample, and the step grid is
    anchored to the projection's own ``now``, so cutting a chain at a
    different instant moved every step start, moved which sample each
    step snapped to, and moved the answer.  That lookup was the
    dominant term in the chained-versus-single disagreement, ahead of
    the flowing charge.  Interpolating makes a split invisible to
    ambient for the same reason elapsed-portion pricing made it
    invisible to the flowing term.

    Ends are **clamped, never extrapolated**: a projection reaching past
    the last sample holds it flat rather than running a 26 °F daily
    swing off the end of the data, which is the failure mode that would
    matter and the one no test would catch at a flat ambient.
    """

    __slots__ = ("_base", "_stamps", "_values")

    def __init__(self, series: pd.DataFrame) -> None:
        self._stamps: np.ndarray | None = None
        # An absent column is a caller's mistake, not a missing reading:
        # it would coast every projection at the default air unannounced.
        if "ambient_f" not in series.columns:
            raise ValueError(
                "the ambient series has no 'ambient_f' column: pass the "
                "air at the heater, °F, or an empty frame with the column"
            )
        if series.empty:
            return

        # DatetimeIndex, not the bare Index the attribute is typed as:
        # subtracting a datetime from the latter has no defined result
        # type. Indexing one returns the bare type again, hence the
        # rewraps below.
        idx = pd.DatetimeIndex(series.index)
        values = series["ambient_f"].to_numpy(dtype=float)

        # Drop unusable rows rather than interpolating through them.  A
        # single NaN sample used to poison one nearest-neighbour cell;
        # it would now poison *both* bracketing intervals, and `nan`
        # flows straight through `t_bulk` into the trajectory and out
        # of the end state, and past any downstream guard whose `<=`
        # and `>=` are both False against it, so duration caps
        # silently stop arming.  `NaT` in the index does the same
        # through `searchsorted`.
        usable = np.isfinite(values) & ~pd.isna(idx)
        if not usable.all():
            idx, values = pd.DatetimeIndex(idx[usable]), values[usable]
            if len(idx) == 0:
                return

        if idx.tz is None:
            # Assumed UTC, matching every reader of these series.
            # Earlier this raised instead, so a caller handing back
            # *local* naive timestamps now reads ambient up to eight
            # hours out of phase (several °F on a 26 °F swing),
            # silently rather than loudly.  Guarded below rather than
            # left implicit.
            idx = idx.tz_localize(UTC)

        # `searchsorted` is only meaningful on a sorted index, and a
        # reader that changes its sort order would otherwise silently
        # corrupt every lookup rather than failing.
        if not idx.is_monotonic_increasing:
            # Stable, so duplicate timestamps keep their input order
            # and the tie below resolves the same way twice.
            order = np.argsort(idx.to_numpy(), kind="stable")
            idx, values = pd.DatetimeIndex(idx[order]), values[order]

        # Seconds from the first sample, never raw integer timestamps.
        # `DatetimeIndex.asi8` is *resolution-dependent*: pandas 2
        # gives a `datetime64[us]` index here and `Timestamp.value` is
        # always nanoseconds, so mixing them is a silent factor of 1000
        # that clamps every lookup to the last sample.  Subtraction
        # carries the units for us.
        # A plain datetime, not a Timestamp: `at` subtracts from it on
        # every call and that is now the projection's hot path.
        self._base = idx[0].to_pydatetime()  # pyright: ignore[reportAttributeAccessIssue]
        self._stamps = np.asarray(
            (idx - idx[0]) / pd.Timedelta(seconds=1), dtype=float
        )
        self._values = values

    @property
    def defaulted(self) -> bool:
        """Whether no usable reading was given (none, or all missing),
        so every lookup is ``DEFAULT_AMBIENT_F``."""
        return self._stamps is None

    def at(self, target: datetime) -> float:
        """Ambient temperature at ``target``, linearly interpolated."""
        if self._stamps is None:
            # Fallback to a reasonable ambient default
            return DEFAULT_AMBIENT_F
        stamps, values = self._stamps, self._values

        # Ensure target is tz-aware
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        want = (target - self._base).total_seconds()

        pos = int(np.searchsorted(stamps, want))
        if pos <= 0:
            return float(values[0])
        if pos >= len(stamps):
            return float(values[-1])

        lo, hi = pos - 1, pos
        span = stamps[hi] - stamps[lo]
        if span <= 0:  # duplicate timestamps
            return float(values[hi])
        weight = (want - stamps[lo]) / span
        return float(values[lo] + weight * (values[hi] - values[lo]))


def _get_t_amb(series: pd.DataFrame, target: datetime) -> float:
    """Ambient temperature at ``target``, linearly interpolated.

    The one-shot form of `AmbientSampler`, for a caller that needs a
    single value; the integrator builds the sampler once and reuses it.
    """
    return AmbientSampler(series).at(target)


def compute_start_time(
    target_time: datetime,
    duration_minutes: float,
) -> datetime:
    """Compute when the compressor must start.

    start_at = target_time − duration_minutes.
    """
    return target_time - timedelta(minutes=duration_minutes)
