"""The heat pump as a performance map: the heat it puts into the tank
and the electricity it draws, each a plane in the air at the heater and
the lower tank's water about ``params.MAP_REF_AIR_F`` and
``params.MAP_REF_WATER_F``. Each is read along its plane wherever the
heat pump runs, past the span it was fitted on (``CompressorParams``'
domains) as within it: held at the span's edge, a plane would give the
heat a 41 °F air does at 61 °F, and the heat and the power, fitted over
different water, a COP neither measured. A fit's slopes take the sign
the cycle gives them (``heat_pump_fit.HEAT_SLOPE_SIGNS``,
``POWER_SLOPE_SIGNS``), so the plane
carried past its evidence moves the way the heat pump does.

Energy is conserved by construction: what the condenser gives the tank
is what the evaporator takes from the air plus the electricity
(``evaporator_btu_h``). ``refrigerant_carnot_cop`` bounds what a fit may
claim over the envelope the heat pump runs in; it is not part of the
model.
"""

from bisect import bisect_right

from nwp500.sim.params import MAP_REF_AIR_F, MAP_REF_WATER_F, CompressorParams
from nwp500.sim.units import BTU_PER_WH

#: °F to °R.
_RANKINE = 459.67
#: How far under the air the evaporator's coil runs, at the least, °F:
#: the coil read at least this far under the heater's air in 90 % of
#: the steady running minutes on one NWP500-65's record (145,286 minutes
#: of 416 runs, 15 minutes or more into a run with the elements off and
#: no draw, 2026-04-16 to 10-26; median 24.5 °F, widening 0.39 °F per °F
#: of air).
EVAPORATOR_APPROACH_F = 20.5


def _plane(
    air_f: float,
    water_f: float,
    level: float,
    per_air: float,
    per_water: float,
    per_both: float,
) -> float:
    a = air_f - MAP_REF_AIR_F
    w = water_f - MAP_REF_WATER_F
    return level + per_air * a + per_water * w + per_both * a * w


def heat_btu_h(c: CompressorParams, air_f: float, water_f: float) -> float:
    """The heat into the tank with the air at ``air_f`` and the lower
    tank at ``water_f``, BTU/h."""
    return _plane(
        air_f,
        water_f,
        c.heat_btu_h,
        c.heat_btu_h_per_air_f,
        c.heat_btu_h_per_water_f,
        c.heat_btu_h_per_air_water_f,
    )


def power_w(c: CompressorParams, air_f: float, water_f: float) -> float:
    """The electricity it draws there, W."""
    return _plane(
        air_f,
        water_f,
        c.power_w,
        c.power_w_per_air_f,
        c.power_w_per_water_f,
        c.power_w_per_air_water_f,
    )


def cop(c: CompressorParams, air_f: float, water_f: float) -> float:
    """The heat over the electricity there."""
    return heat_btu_h(c, air_f, water_f) / (
        power_w(c, air_f, water_f) * BTU_PER_WH
    )


def evaporator_btu_h(
    c: CompressorParams, air_f: float, water_f: float
) -> float:
    """The heat it takes from the air there, BTU/h: the heat less the
    electricity."""
    return heat_btu_h(c, air_f, water_f) - power_w(c, air_f, water_f) * (
        BTU_PER_WH
    )


def start_hold_min(c: CompressorParams, minutes_off: float | None) -> float:
    """The hold at a start after ``minutes_off`` with the compressor
    off, minutes: the band's (``CompressorParams.start_hold_min``), the
    last for a stop not known (None)."""
    if minutes_off is None:
        return c.start_hold_min[-1]
    return c.start_hold_min[
        bisect_right(c.start_hold_after_min, max(0.0, minutes_off))
    ]


#: The reason a recovery carries whose air is outside the heat map's
#: fitted span (``CompressorParams.heat_domain_air_f``): its heat is the
#: plane carried past the record, not a reading's.
HEAT_MAP_OUT_OF_DOMAIN = "heat_map_out_of_domain"


def heat_air_outside(c: CompressorParams, air_f: float) -> bool:
    """Whether ``air_f`` is outside the heat map's fitted air span."""
    low, high = c.heat_domain_air_f
    return not low <= air_f <= high


def carnot_cop(air_f: float, water_f: float) -> float:
    """The ideal heat pump's COP lifting heat from ``air_f`` to
    ``water_f``: infinite with the water no warmer than the air."""
    lift = water_f - air_f
    if lift <= 0.0:
        return float("inf")
    return (water_f + _RANKINE) / lift


def refrigerant_carnot_cop(air_f: float, water_f: float) -> float:
    """The ideal heat pump's COP between the evaporator's coil, at
    ``EVAPORATOR_APPROACH_F`` under the air, and the water: the
    refrigerant boils colder than the air and condenses no colder than
    the water, so no cycle between them does better. On the record the
    map's COP ran a steady 0.43 of the ideal between the coil as read
    and the water from 60 to 100 °F air, never over 0.46."""
    return carnot_cop(air_f - EVAPORATOR_APPROACH_F, water_f)
