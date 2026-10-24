"""Heat a draw takes out of the tank.

A draw takes hot water off the top and lets water in at the bottom, at
the draw's **inflow temperature**: the inlet's (the mains) unless the
draw says otherwise. Two kinds are modelled, additive, neither
containing the other:

- a draw **delivered** through the mixing valve at its onset, a
  fixture's: its heat (:func:`draw_energy_btu`) and how the two probes
  move (:func:`probes_after_draw`), below;
- a draw that **flows** straight from the tank over a span, whose
  inflow mixes into the lower zone (:func:`lower_zone_drop_f`, at the
  end of this module).

**The metered volume is not the withdrawn volume.** A thermostatic
mixing valve sits immediately after the heater's hot outlet, and the
house's flow meter is inline downstream of it, so what is published
as a draw's volume is *blended water delivered* to the
fixture. The tank gave up less than that, and how much less depends on
how hot it is.

Mixing to a delivery setpoint gives the hot fraction::

    V_hot / V_del = (T_del − T_cold) / (T_upper − T_cold),   capped at 1

and the tank loses that hot water while taking cold back in at the
bottom::

    E = V_hot · 8.34 · (T_upper − T_cold)

Substituting collapses the two::

    E = V_del · 8.34 · (min(T_upper, T_del) − T_cold)

**`T_del` is not a constant.** A gauge cam on the valve outlet
(2026-09-16/17, five full draw plateaus) reads ~114-116 °F with a
124-131 °F tank and ~120-122 °F with a 138-140 °F tank: about half a
degree of delivery per degree of upper zone. :func:`delivery_temp_f`
carries that as a line in `T_upper`. Had the setpoint been fixed, tank
temperature would cancel exactly while the valve mixes: a hotter tank
gives up proportionally less water for the same shower. With the
measured slope it re-enters at about half weight, so a hotter tank
makes a draw cost somewhat more heat. It re-enters fully only once the
upper zone falls *below* `T_del`, where the valve has nothing to blend
with; on the measured line that is below about 104 °F.

That leaves one unknown the corpus cannot resolve as physics. `T_cold`
and the **observability** of a draw (the share of its enthalpy the
two tank thermistors' mean registers) enter the data only as a
product, because the tank sits above `T_del` on every clean draw and
the conversion then barely varies. Fitting `T_cold` alone returns
97 °F, which is the stratification bias wearing groundwater's clothes.

So `k` is fitted against a **reference** `T_cold`, and the two move
together. That is consistency rather than compromise, because every
other number here is already in the same apparent frame: the
standby law is fitted against the same two-point
mean, and the appliance's own `available_energy_wh` is that mean times
the full tank mass (measured: 153.8 Wh/°F against the tank's 154.5,
r = 0.9988). A physically parameterised draw term would have been the
odd one out, reporting about 1/k ≈ 1.6x more energy removed than the
appliance's own accounting recognises, and a scheduler differencing
a draw's heat against `available_energy_wh`, which is why the two
share a unit, would have been badly wrong. `k` prices a draw's heat
(:func:`draw_energy_btu`), as the calibration reads it; how the probes
move through a draw is the law below, which does not use it.

**The reference is measured (2026-09-26).** A probe on the cold
supply reads `T_cold` from the plateau of long draws: 71.3-73.1 °F
over its first week, median 72.4, where the draw term had assumed 60.
`k` and the probes' response are fitted against 72.4, so parameters
fitted on them may be given the live plateau in place of the
reference, and a projection then need not flag its inlet as modelled.
Swapping the
measurement into the 60 °F `k` without the refit would cut every
draw's heat by a fifth. Most of the corpus predates the probe, so the
history is held at the reference: the probe's week cannot show a
season, and its plateaus move only 0.08 °F per °F of the air at the
heater.

**The probes through a delivered draw.** The water withdrawn is
replaced at the bottom by water at the inflow, and the lower probe
falls toward the inflow by a share that grows with the gap at the
draw: the same draw moves it much further in a tank with its probes
apart than in a mixed one (:func:`probes_after_draw`). The upper probe
falls a few hundredths of a degree per gallon. The gap then relaxes on
the stratification time constant, `tau_gap_hours`. It is fitted each
retrain on quiet windows and carried with the fitted parameters.
Parameters without one project on the 60 h prior, and a projection
whose window contains a draw should then say it used the prior.
Fitted or not, one exponential is a two-zone approximation of a
thermocline, so `t_lower_f` after a draw stays the field to trust
least.

``observability = None`` in the parameters disables delivered draws
entirely, which is what parameters fitted before this existed carry,
so the projection reverts exactly to the behaviour that shipped
without it.
"""

import math

from nwp500.sim.params import TankParams
from nwp500.sim.units import WATER_BTU_PER_GAL_F

#: Share of a draw's enthalpy the two tank thermistors' mean registers,
#: the apparent frame the standby law and the appliance's own energy
#: field measure heat in. It prices a delivered draw's heat
#: (``draw_energy_btu``), as the calibration's compressor and
#: efficiency fits read it, and in the parameters it is what turns
#: delivered draws on. How the probes move through a draw is
#: ``probes_after_draw``'s, which does not use it.
#:
#: First fitted 2026-09-12 on 508 compressor-off episodes with no other
#: water moving
#: against a constant 128 °F delivery and a 60 °F inlet: 0.454, 95 %
#: bootstrap CI [0.403, 0.503]. Refitted 2026-09-17 against the measured
#: delivery line below: ×1.113, to 0.505. **Refitted 2026-09-26
#: against the measured inlet, 72.4 °F:** on a rebuilt corpus of
#: 327 such quiet, compressor-off episodes before the probe, the fit
#: under 72.4 is ×1.254 the fit under 60 (bootstrap [1.252, 1.256]), so
#: 0.505 → 0.633. As before, the ratio carries over rather than the
#: rebuilt value, so only the change of inlet moves it.
#:
#: Below one because the upper half of the tank barely participates:
#: an 11.5 gal draw moves the upper thermistor 0.36 °F while the lower
#: falls 6.8 °F, so the pair under-weighs every draw by roughly the
#: same factor whatever its size. Not a fudge: it is the same
#: apparent frame the standby law and the appliance's own energy field
#: already use.
DEFAULT_OBSERVABILITY = 0.633

#: The inlet ``DEFAULT_OBSERVABILITY`` is fitted against, °F: the median
#: plateau of the cold-supply probe's long draws over 2026-09-19..26,
#: seven draws, 71.3-73.1, bootstrap CI on the median [71.8, 73.0].
#: It is the reference the whole corpus is held at, and the
#: value served when the probe has no fresh plateau. The two move
#: together: change one and refit the other, or neither means
#: anything.
DEFAULT_INLET_TEMP_F = 72.4

#: Mixing-valve delivery, ``T_del = intercept + slope · T_upper``, °F.
#:
#: Least squares through the five full draw plateaus the gauge cam
#: recorded on 2026-09-16/17: tank 123.8-139.5 °F, delivery
#: 114.2-121.8 °F. Five points, and every hot-tank one is an evening,
#: so part of the slope might have been a warmer evening inlet. The
#: probe does not show that it was (2026-09-26): over seven later
#: draws the slope held (0.42 with the inlet in the fit), and the
#: inlet's fitted effect, 2.6 °F per °F, is more than a mixing valve can
#: pass on, so it stands in for the time of day. The five-point slope's
#: 95 % CI is [0.29, 0.68] on 3 degrees of freedom. Carried in the
#: parameters beside ``DEFAULT_OBSERVABILITY`` because the two were
#: fitted together: a fitted ``k`` means nothing under another delivery
#: law.
DEFAULT_TMV_DELIVERY_INTERCEPT_F = 53.56
DEFAULT_TMV_DELIVERY_SLOPE = 0.485

#: No mixing valve: the tap gets the tank's own water, the one delivery
#: with no fitted numbers in it, and every function's default here. The
#: line above is one installation's valve, set through ``DrawParams``.
NO_VALVE_INTERCEPT_F = 0.0
NO_VALVE_SLOPE = 1.0

#: The constant delivery the first calibration assumed. Parameters
#: saved before the measured law have no delivery fields and load as
#: intercept 128, slope 0, so rolling back to them reverts the
#: conversion exactly.
LEGACY_TMV_DELIVERY_F = 128.0

#: Stratification gap, °F, over which the water a delivered draw lets
#: in at the bottom comes to reach the lower thermistor
#: (``probes_after_draw``): with ``DEFAULT_REACH_OFFSET_F`` added to the
#: gap, it reaches it with share ``1 − 1/e`` at this one. Fitted 2026-10-24 with
#: the offset, ``DEFAULT_REACH_GAL`` and ``DEFAULT_UPPER_F_PER_GAL`` on
#: the 399 clean delivered draws from 2026-02-21 to 07-31 (nothing
#: heating or circulating and the heater heard throughout, from 15 min
#: before to 30 min after; no other draw within 30 min), at the
#: reference inlet, against the probes 10 min after the draw's end.
#: The lower probe then, on all 535 such draws to 2026-10-23, against
#: the law it replaced (the bulk falling by ``DEFAULT_OBSERVABILITY``
#: of the draw's heat and the gap opening 1.235 °F per withdrawn gallon
#: about it), the bias the model less the probe:
#:
#: ============  ===  ==============  ===========
#: Draw          n    Bias, °F        MAE, °F
#: ============  ===  ==============  ===========
#: under 1 gal   281  +0.19 → +0.30   0.48 → 0.35
#: 1-3 gal        55  +0.15 → +0.26   1.68 → 0.91
#: 3-8 gal        51  −0.59 → −0.28   3.70 → 2.12
#: 8-20 gal      127  −2.79 → −1.12   6.72 → 3.52
#: over 20 gal    21  +5.37 → +1.27   8.78 → 6.48
#: ============  ===  ==============  ===========
#:
#: With the probes within 3 °F the bias goes from −1.75 to −0.03 °F,
#: with them further apart from +1.62 to −0.10. On the 136 draws from
#: 08-01, held out, the lower probe's MAE goes from 2.79 to 1.91 °F and
#: the upper's from 0.31 to 0.21 (0.28 to 0.20 on all 535), and the
#: bias of the probes' mean stays within 0.2 °F.
DEFAULT_REACH_GATE_F = 30.0

#: °F added to the gap the reach is gated on, so a mixed tank's lower
#: probe still moves a little; fitted with ``DEFAULT_REACH_GATE_F``.
DEFAULT_REACH_OFFSET_F = 1.25

#: Gallons of the lower zone the water let in mixes with at the lower
#: thermistor; fitted with ``DEFAULT_REACH_GATE_F``.
DEFAULT_REACH_GAL = 9.0

#: °F the upper thermistor falls per delivered gallon; fitted with
#: ``DEFAULT_REACH_GATE_F``.
DEFAULT_UPPER_F_PER_GAL = 0.05

#: Delivered gallons per piece ``probes_after_draw`` walks a draw in, so
#: a draw split into parts moves the probes as the whole does.
_DRAW_PIECE_GAL = 0.25

#: Pre-draw upper-zone range the fit saw, °F: 508 episodes
#: spanning 122.2-147.9. The delivery line was measured only over
#: 123.8-139.5, so the top of this band already extrapolates it. A
#: projection that walks the tank out of the band should say so.
DEFAULT_DOMAIN_T_UPPER_F = (122.2, 147.9)

#: Conditional per-draw volume range the fit saw, gallons.
DEFAULT_DOMAIN_VOLUME_GAL = (1.0, 41.6)


def delivery_temp_f(
    t_upper_f: float,
    intercept_f: float = NO_VALVE_INTERCEPT_F,
    slope: float = NO_VALVE_SLOPE,
) -> float:
    """What the mixing valve delivers with the upper zone at ``t_upper_f``.

    Linear in tank temperature, per the gauge-cam plateaus at the
    installation the ``DEFAULT_TMV_*`` line comes from. ``slope = 0``
    gives the constant ``intercept_f``, which is how the older constant
    128 °F is expressed; the default, intercept 0 and slope 1, is no
    valve.
    """
    return intercept_f + slope * t_upper_f


def hot_fraction(
    t_upper_f: float,
    t_delivery_f: float,
    t_cold_f: float,
) -> float:
    """Share of a delivered gallon that came out of the tank.

    1.0 once the upper zone is at or below the delivery setpoint: the
    valve has nothing to blend with and passes tank water straight
    through. Never above 1.0 and never below 0.0: a tank at or under
    the inlet temperature delivers nothing, and the degenerate
    ``T_upper <= T_cold`` case is guarded rather than dividing.
    """
    if t_upper_f <= t_cold_f:
        return 0.0
    if t_upper_f <= t_delivery_f:
        return 1.0
    return min(
        1.0, max(0.0, (t_delivery_f - t_cold_f) / (t_upper_f - t_cold_f))
    )


def draw_energy_btu(
    volume_delivered_gal: float,
    t_upper_f: float,
    t_delivery_f: float,
    t_cold_f: float,
    observability: float = 1.0,
) -> float:
    """Tank heat a delivered volume carries away, in **apparent** BTU.

    ``volume_delivered_gal`` is the **metered** figure: blended water
    past the mixing valve, which is the basis draw volumes are
    published on and the only one a forecast can supply.

    "Apparent" means measured the way the two tank thermistors and the
    appliance's own energy field measure it, which is the frame the
    standby law is already fitted in and the one a consumer comparing
    against ``available_energy_wh`` needs. ``observability`` is the
    factor between that and true enthalpy; 1.0 gives the textbook
    value, and is right only for a caller that can measure the whole
    tank.

    Zero, never negative: a tank colder than its inlet has nothing to
    give, and the clamp keeps a cold-tank projection from gaining heat
    from a shower.
    """
    if volume_delivered_gal <= 0.0:
        return 0.0
    effective = min(t_upper_f, t_delivery_f)
    return max(
        0.0,
        observability
        * volume_delivered_gal
        * WATER_BTU_PER_GAL_F
        * (effective - t_cold_f),
    )


def withdrawn_gal(
    volume_delivered_gal: float,
    t_upper_f: float,
    t_delivery_f: float,
    t_cold_f: float,
) -> float:
    """Hot water taken from the tank, in gallons.

    The energy above does not need this (the substitution cancels it),
    but the lower probe's response does (``probes_after_draw``): the
    water let in at the bottom equals the hot water that left the top.
    """
    if volume_delivered_gal <= 0.0:
        return 0.0
    return volume_delivered_gal * hot_fraction(
        t_upper_f, t_delivery_f, t_cold_f
    )


def probes_after_draw(
    t_upper: float,
    t_lower: float,
    delivered_gal: float,
    inflow_f: float,
    *,
    intercept_f: float = NO_VALVE_INTERCEPT_F,
    slope: float = NO_VALVE_SLOPE,
    gate_f: float = DEFAULT_REACH_GATE_F,
    offset_f: float = DEFAULT_REACH_OFFSET_F,
    reach_gal: float = DEFAULT_REACH_GAL,
    upper_f_per_gal: float = DEFAULT_UPPER_F_PER_GAL,
) -> tuple[float, float]:
    """The two zones just after a delivered draw, ``(t_upper, t_lower)``,
    °F.

    The hot water withdrawn (``withdrawn_gal``) is replaced at the
    bottom by water at ``inflow_f``, and the lower probe falls toward
    it by a share that grows with the gap at the draw; the upper probe
    falls a little per delivered gallon::

        reach = 1 − e^(−(gap + offset) / gate)
        ΔT_lower = reach · (T_lower − T_in) · V_withdrawn / V_reach
        ΔT_upper = upper_f_per_gal · V_delivered

    The draw is walked in pieces of at most a quarter of a delivered
    gallon, each from the zones the last one left: within a piece the
    lower zone decays toward the inflow exponentially, at the reach and
    hot fraction of the piece's midpoint, so a draw split into parts
    moves the zones as the whole does. Neither zone warms,
    the lower one stops at the inflow, and the upper one at the lower.
    A tank at or under the inflow gives nothing and does not move.

    Args:
        t_upper: Upper zone before the draw, °F.
        t_lower: Lower zone before the draw, °F.
        delivered_gal: The draw, metered, gallons.
        inflow_f: The water replacing it, °F.
        intercept_f: The mixing valve's delivery line
            (``delivery_temp_f``), evaluated at each piece's upper zone.
        slope: °F of delivery per °F of upper zone.
        gate_f: ``DEFAULT_REACH_GATE_F``.
        offset_f: ``DEFAULT_REACH_OFFSET_F``.
        reach_gal: ``DEFAULT_REACH_GAL``.
        upper_f_per_gal: ``DEFAULT_UPPER_F_PER_GAL``.
    """
    if delivered_gal <= 0.0:
        return t_upper, t_lower
    n = max(1, math.ceil(delivered_gal / _DRAW_PIECE_GAL))
    dv = delivered_gal / n

    def rate(upper: float, lower: float) -> float:
        # The lower zone's decay toward the inflow per delivered gallon.
        hot = withdrawn_gal(
            1.0, upper, delivery_temp_f(upper, intercept_f, slope), inflow_f
        )
        reach = 1.0 - math.exp(-max(upper - lower + offset_f, 0.0) / gate_f)
        return reach * hot / reach_gal

    def piece(upper: float, lower: float, k: float, gal: float) -> float:
        return inflow_f + max(lower - inflow_f, 0.0) * math.exp(-k * gal)

    upper, lower = t_upper, t_lower
    for _ in range(n):
        if upper <= inflow_f:
            break
        mid_upper = max(upper - upper_f_per_gal * dv / 2.0, lower)
        mid_lower = min(
            lower, piece(upper, lower, rate(upper, lower), dv / 2.0)
        )
        lower = min(lower, piece(upper, lower, rate(mid_upper, mid_lower), dv))
        upper = max(upper - upper_f_per_gal * dv, min(lower, upper))
    return upper, lower


#: Stratification gap, °F, over which water let in at the bottom comes
#: to reach the lower thermistor (``lower_zone_drop_f``): at this gap it
#: reaches it with share ``1 − 1/e``. Fitted 2026-09-25 through the
#: coast itself on 101 clean circulation runs from 2026-02-26 to 08-31,
#: their inflow at ambient, each projected at its own measured flow,
#: minimising the lower zone's absolute error averaged over 10, 30, 60
#: and 120 min after the run: 5.0 °F at the 10 h gap constant the
#: model then used (bootstrap 95 % CI 3.5-6.0), and 5.5 at the
#: fitted 59 h (CI 4.0-6.0), where 5.0 is within 0.02 °F of the optimum.
#: September was held out to validate it: the value, not the law's
#: form, which was chosen from statistics over all 146 runs,
#: September's included.
DEFAULT_LOWER_GATE_F = 5.0

#: °F of reach per hour the tank has stood unheated, added to the gap a
#: flowing draw is gated on (``lower_zone_drop_f``).
#: Fitted 2026-09-25 through the coast with the gate on the same 101
#: runs to 08-31, at the 10 h gap constant and each run's measured
#: flow: 0.015 at the gate above (bootstrap 95 % CI 0.010 to >= 0.040,
#: the upper bound censored by the grid searched), the joint optimum
#: (5.25 °F, 0.015) within 0.002 °F of it. On September, the rate held
#: out (not the form, chosen on all 146 runs), it takes the lower
#: zone's error after a run from 2.11 to 1.90 °F at 10 min and 1.52 to
#: 1.07 at 120, all of it in tanks the probes read as mixed.
DEFAULT_POOL_F_PER_HOUR = 0.015


def lower_zone_drop_f(
    gallons: float,
    t_lower: float,
    inflow_f: float,
    gap_f: float,
    gate_f: float,
    pool_f: float = 0.0,
    tank: TankParams = TankParams(),
) -> float:
    """How far water let in at the bottom cools the lower thermistor, °F.

    A draw that flows straight from the tank takes water off the top,
    and the water replacing it comes in below the lower thermistor at
    the draw's inflow temperature. What the thermistors show is
    measured on 146 circulation runs with no draw and no compressor or
    element, their inflow at ambient, from 2026-02-26 to 09-24: the
    upper zone does not move (−0.36 °F 10 min after the run, most of it
    standby), and the lower zone moves by an amount set by where the
    thermocline is. With the tank mixed (gap ≤ 1 °F) it fell 0.90 °F;
    with a gap over 3 °F, 7.02 °F. The drop persisted for the two hours
    the record stays clean for; it did not mix back.

    So the incoming water is mixed into the lower zone, half the tank,
    at its inflow temperature::

        drop = reach · (1 − e^(−V / V_lower)) · (T_lower − T_in)
        reach = 1 − e^(−(gap + stood) / gate)
        stood = rate · hours since the heater last stopped

    ``reach`` is the share of the inflow's cooling the lower thermistor
    shows: little in a freshly heated, mixed tank, and nearly all once
    the thermocline sits at it.
    ``V_lower`` is not fitted: a free fit of this closed form, gated on
    the gap before the draw, put it at 33.2 gal against the zone's 31.6.

    ``stood`` is the time since heating. A tank that has stood unheated
    for hours reads mixed, but its lower probe falls further on a run:
    on the 48 runs into a mixed tank the drop was 0.7 °F within 3 h of
    the heater stopping and 3.6 °F after 14 h (n = 5). The rate is
    ``DEFAULT_POOL_F_PER_HOUR``, fitted with the gate as a pair.

    What was tested and is **not** here: the volume of cold water let
    in below the probe since the last recovery, the probe reading the
    cold layer once it passes a fitted volume under the probe. As a
    threshold it separates the drops over 9.5 °F worse than this law
    does (ROC AUC 0.68 [0.59, 0.77] against 0.89 [0.82, 0.94],
    n = 117), and fitted as a front, a threshold or a multiplier it
    does not improve on the gap, in sample or on September.

    The heat this takes out, half the tank's mass times the drop, is the
    apparent heat of the draw. The tail is wide: a draw that pushes the
    thermocline past the thermistor can take the lower zone down
    10-21 °F. Neither the probes nor the record's history foresee it: a
    random forest given the gap, the tank, the draw, the draws since the
    last recovery, the hours since it and the probe's own fall before
    the draw predicts the six drops over 12 °F at about 10, left out one
    at a time.

    Args:
        gallons: Water let in, gallons.
        t_lower: Lower zone as the water comes in, °F.
        inflow_f: The incoming water's temperature, °F.
        gap_f: Stratification gap, upper less lower, °F.
        gate_f: ``DEFAULT_LOWER_GATE_F``, as the parameters carry it.
            ``0.0`` is the ungated charge, which this does not describe,
            and returns 0.0.
        pool_f: ``stood``, °F: the rate times the hours the tank has
            stood unheated. ``0.0``, unknown, is the gap alone.
        tank: The tank, whose lower zone (``lower_zone_volume_gal``,
            half of it) the water mixes into.

    Returns:
        The drop, never negative and never past the inflow.
    """
    shown = max(gap_f, 0.0) + max(pool_f, 0.0)
    if gallons <= 0.0 or gate_f <= 0.0 or shown <= 0.0:
        return 0.0
    reach = 1.0 - math.exp(-shown / gate_f)
    mixed = 1.0 - math.exp(-gallons / tank.lower_zone_volume_gal)
    return reach * mixed * max(0.0, t_lower - inflow_f)
