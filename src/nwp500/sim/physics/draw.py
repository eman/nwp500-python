"""What a draw delivered through a mixing valve takes from the tank.

A draw takes hot water off the top and lets water in at the bottom, at
the draw's **inflow temperature**: the inlet's (the mains) unless the
draw says otherwise. How the layers take it is
``physics.stratified.draw``'s; this module is the valve.

**The metered volume is not the withdrawn volume.** A thermostatic
mixing valve sits immediately after the heater's hot outlet, and the
house's flow meter is inline downstream of it, so what is published
as a draw's volume is *blended water delivered* to the
fixture. The tank gave up less than that, and how much less depends on
how hot it is.

Mixing to a delivery temperature gives the hot fraction::

    V_hot / V_del = (T_del − T_cold) / (T_upper − T_cold),   capped at 1

and the tank loses that hot water while taking cold back in at the
bottom.

**`T_del` is not a constant.** A gauge cam on the valve outlet
(2026-09-16/17, five full draw plateaus) reads ~114-116 °F with a
124-131 °F tank and ~120-122 °F with a 138-140 °F tank: about half a
degree of delivery per degree of upper zone. :func:`delivery_temp_f`
carries that as a line in `T_upper`. A hotter tank gives up
proportionally less water for the same shower, but not in full: with
the measured slope, a hotter tank makes a draw cost somewhat more
heat. Below `T_del` the valve has nothing to blend with and passes
tank water straight through; on the measured line that is below
about 104 °F.
"""

#: The cold inlet's reference, °F: the median plateau of the
#: cold-supply probe's long draws over 2026-09-19..26, seven draws,
#: 71.3-73.1, bootstrap CI on the median [71.8, 73.0]. A September
#: value: the plateaus fell to 69.3-69.6 °F by 2026-10-20, and the
#: lower probe's 68.0 and 69.4 °F in January and February bound the
#: winter mains below that.
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
#: 95 % CI is [0.29, 0.68] on 3 degrees of freedom.
DEFAULT_TMV_DELIVERY_INTERCEPT_F = 53.56
DEFAULT_TMV_DELIVERY_SLOPE = 0.485

#: No mixing valve: the tap gets the tank's own water, the one delivery
#: with no fitted numbers in it, and every function's default here. The
#: line above is one installation's valve, set through ``DrawParams``.
NO_VALVE_INTERCEPT_F = 0.0
NO_VALVE_SLOPE = 1.0


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


def withdrawn_gal(
    volume_delivered_gal: float,
    t_upper_f: float,
    t_delivery_f: float,
    t_cold_f: float,
) -> float:
    """Hot water taken from the tank, in gallons.

    The water let in at the bottom equals the hot water that left the
    top (``physics.stratified.draw``).
    """
    if volume_delivered_gal <= 0.0:
        return 0.0
    return volume_delivered_gal * hot_fraction(
        t_upper_f, t_delivery_f, t_cold_f
    )
