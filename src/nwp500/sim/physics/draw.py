"""Heat a draw takes out of the tank.

A draw takes hot water off the top and lets water in at the bottom, at
the draw's **inflow temperature**: the inlet's (the mains) unless the
draw says otherwise. Two kinds are modelled, additive, neither
containing the other:

- a draw **delivered** through the mixing valve at its onset, a
  fixture's: its heat (:func:`draw_energy_btu`) and the front it opens
  (:func:`gap_opened_f`), below;
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
and the **observability** of a draw (the share of its enthalpy two tank
thermistors register) enter the data only as a product, because the
tank sits above `T_del` on every clean draw and the conversion then
barely varies. Fitting `T_cold` alone returns 97 °F, which is the
stratification bias wearing groundwater's clothes.

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
share a unit, would have been badly wrong.

**The reference is measured (2026-09-26).** A probe on the cold
supply reads `T_cold` from the plateau of long draws: 71.3-73.1 °F
over its first week, median 72.4, where the draw term had assumed 60.
`k` and the gap coefficient are refitted against 72.4, so parameters
fitted on them may be given the live plateau in place of the
reference, and a projection then need not flag its inlet as modelled.
Swapping the
measurement into the 60 °F `k` without the refit would cut every
draw's heat by a fifth. Most of the corpus predates the probe, so the
history is held at the reference: the probe's week cannot show a
season, and its plateaus move only 0.08 °F per °F of the air at the
heater.

**The front.** A draw does not cool the tank uniformly. It pulls hot
water off the top and admits cold at the bottom, so the upper-lower gap
*opens* by roughly the cold volume admitted, and then relaxes on the
stratification time constant, `tau_gap_hours`. It is fitted each
retrain on quiet windows and carried with the fitted parameters.
Parameters without one project on the 60 h prior, and a projection
whose window contains a draw should then say it used the prior.
Fitted or not, one
exponential is a two-zone approximation of a thermocline, so
`t_lower_f` after a draw stays the field to trust least.

``draw_gap_open_f_per_gal = 0.0`` disables the front and
``observability = None`` in the parameters disables the term entirely,
which is what parameters fitted before this existed carry, so the
projection reverts exactly to the behaviour that shipped without it.
"""

import math

from nwp500.sim.params import TankParams
from nwp500.sim.units import WATER_BTU_PER_GAL_F

#: Share of a draw's enthalpy the two tank thermistors register.
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

#: °F of stratification gap opened per gallon withdrawn. First fitted
#: on the same 508 episodes against 128 °F: 1.043, 95 % CI
#: [0.936, 1.158]. The measured delivery line lowers the hot fraction
#: (at a 139 °F tank 0.77 of a delivered gallon comes from the tank,
#: not 0.86), so the same openings mean more °F per withdrawn gallon:
#: ×1.119, to 1.167. A 72.4 °F inlet lowers it again (0.73 at
#: 139 °F): ×1.058 on the rebuilt corpus (bootstrap [1.058, 1.058]),
#: to 1.235. The response is mildly *convex* rather than
#: saturating: a power fit puts the exponent at 1.57, CI [1.11, 2.07],
#: because the thermocline has to reach the lower thermistor before
#: the gap opens at all, so this linear coefficient under-reads the
#: largest draws.
DEFAULT_GAP_OPEN_F_PER_GAL = 1.235

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
    but the **front** does: what opens the stratification gap is the
    cold water admitted at the bottom, which equals the hot water that
    left the top.
    """
    if volume_delivered_gal <= 0.0:
        return 0.0
    return volume_delivered_gal * hot_fraction(
        t_upper_f, t_delivery_f, t_cold_f
    )


def gap_opened_f(
    withdrawn_volume_gal: float,
    open_f_per_gal: float,
    bulk_drop_f: float,
    t_lower_f: float,
    t_cold_f: float,
) -> float:
    """How far a draw opens the upper-lower gap, in °F.

    Linear in the withdrawn volume, and then bounded twice, because
    the coefficient alone will happily produce a tank that no draw
    could make.

    **A draw cannot warm any part of the tank.** The gap is split
    evenly about the bulk, so an opening larger than twice the bulk
    drop raises the upper zone, and with the fitted coefficient that
    is not a corner case: it happens below about 122 °F, which is the
    depleted-tank regime this term exists to describe. Measured
    before the cap, a 9.5 gal draw against a 110 °F tank *heated* the
    top by 0.8 °F. Capping at twice the drop means the worst a draw
    can do is leave the top untouched and put the whole loss into the
    bottom, which is also what the corpus shows it doing: an 11.5 gal
    draw moves the upper thermistor 0.36 °F and the lower 6.8 °F.

    **The lower zone cannot go below the water coming in**, so the
    opening is also capped at the room it has. Note what this bounds
    and what it does not: only the gap half. The bulk drop is applied
    separately and is not bounded here, so a single implausibly large
    event can still carry `t_lower` below the inlet. Aggregate slot
    events are a few gallons and real mornings are tens, so this is a
    latent edge rather than a live one, but it is an edge, and the
    docstring used to claim otherwise.
    """
    if withdrawn_volume_gal <= 0.0 or open_f_per_gal <= 0.0:
        return 0.0
    opened = open_f_per_gal * withdrawn_volume_gal
    no_warming = max(0.0, 2.0 * bulk_drop_f)
    headroom = max(0.0, 2.0 * (t_lower_f - t_cold_f))
    return min(opened, no_warming, headroom)


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

#: The standby pool, °F of reach per hour the tank has stood unheated,
#: added to the gap a flowing draw is gated on (``lower_zone_drop_f``).
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
        reach = 1 − e^(−(gap + pool) / gate)
        pool = rate · hours since the heater last stopped

    ``reach`` is the share of the water that gets to the lower
    thermistor: none in a freshly heated, mixed tank, where it pools
    below the probe, and nearly all once the thermocline sits at it.
    ``V_lower`` is not fitted: a free fit of this closed form, gated on
    the gap before the draw, put it at 33.2 gal against the zone's 31.6.

    ``pool`` is cold water the probes cannot see. A tank that has stood
    unheated for hours reads mixed, but a draw then lifts water that
    cooled below the probe: on the 48 runs into a mixed tank the drop
    was 0.7 °F within 3 h of the heater stopping and 3.6 °F after
    14 h (n = 5). The rate is ``DEFAULT_POOL_F_PER_HOUR``, fitted with
    the gate as a pair.

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
        pool_f: The standby pool, °F: the rate times the hours the tank
            has stood unheated. ``0.0``, unknown, is the gap alone.
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


# ── The lower zone after a delivered draw settles ───────────────────
#
# A client that knows where a draw's cold water lies (a heat ledger,
# ``sim.extensions.HeatLedger``) reads the lower zone at the front its
# cold region puts against the probe, in place of the draw's calibrated
# response. The probe keeps falling once the flow stops, for hours: a
# front placed at the draw alone left the zone too warm 3-12 h on, so
# whole days read worse and recoveries begun from it ran short. The zone
# settles from the front's reading toward the colder of the front and
# its calibrated level (the response the draw term was fitted to, after
# the draw), on one time constant (the ledger's, ``LedgerZones``:
# 300 min, fitted on the quiet hours after the long draws before
# 2026-07-01, day-bootstrap 180-480). It is the only parameter the
# settling adds; the settled level is the existing calibration's. It
# never settles below the inlet. A compressor recovery or an element run
# takes what is left at its start, and while either runs a draw is its
# own response.


def settled_lower_f(
    front_f: float,
    settled_response_f: float,
    floor_f: float,
) -> tuple[float, float]:
    """The lower zone just after a draw and how far it sits above where
    it settles: ``front_f`` the front's reading, ``settled_response_f``
    the draw's calibrated response priced from the level the zone was
    settling to, and ``floor_f`` the inlet. The zone reads the front; it
    settles to the colder of the front and the calibrated response,
    never below the inlet (nor above the front)."""
    settled = max(min(settled_response_f, front_f), min(front_f, floor_f))
    return front_f, max(0.0, front_f - settled)


def unsettled_after_f(
    unsettled_f: float, minutes: float, settle_min: float
) -> float:
    """How far above its settled level the lower zone still sits
    ``minutes`` after it sat ``unsettled_f`` above it: one time
    constant, ``settle_min``."""
    if unsettled_f <= 0.0:
        return 0.0
    if settle_min <= 0.0:
        return 0.0
    return unsettled_f * math.exp(-max(0.0, minutes) / settle_min)
