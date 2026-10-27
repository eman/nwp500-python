"""The heat pump as a performance map: the heat it puts into the tank
and the electricity it draws, each a plane in the air at the heater and
the lower tank's water about ``params.MAP_REF_AIR_F`` and
``params.MAP_REF_WATER_F``, each read with both held to the span it was
fitted on (``CompressorParams``' domains).

Energy is conserved by construction: what the condenser gives the tank
is what the evaporator takes from the air plus the electricity
(``evaporator_btu_h``). ``carnot_cop`` bounds what a fit may claim; it
is not part of the model.
"""

from bisect import bisect_right

from nwp500.sim.params import MAP_REF_AIR_F, MAP_REF_WATER_F, CompressorParams
from nwp500.sim.units import BTU_PER_WH

#: °F to °R.
_RANKINE = 459.67


def _held(value: float, bounds: tuple[float, float]) -> float:
    return min(max(value, bounds[0]), bounds[1])


def _plane(
    air_f: float,
    water_f: float,
    domain: tuple[tuple[float, float], tuple[float, float]],
    level: float,
    per_air: float,
    per_water: float,
    per_both: float,
) -> float:
    a = _held(air_f, domain[0]) - MAP_REF_AIR_F
    w = _held(water_f, domain[1]) - MAP_REF_WATER_F
    return level + per_air * a + per_water * w + per_both * a * w


def heat_btu_h(c: CompressorParams, air_f: float, water_f: float) -> float:
    """The heat into the tank with the air at ``air_f`` and the lower
    tank at ``water_f``, BTU/h."""
    return _plane(
        air_f,
        water_f,
        (c.heat_domain_air_f, c.heat_domain_water_f),
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
        (c.power_domain_air_f, c.power_domain_water_f),
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


def carnot_cop(air_f: float, water_f: float) -> float:
    """The ideal heat pump's COP lifting heat from ``air_f`` to
    ``water_f``: infinite with the water no warmer than the air."""
    lift = water_f - air_f
    if lift <= 0.0:
        return float("inf")
    return (water_f + _RANKINE) / lift
