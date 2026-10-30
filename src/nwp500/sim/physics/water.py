"""Water's heat per gallon, which falls as it warms.

A gallon of water holds 8.34 BTU per °F at the mains (58 °F) and 8.20 at
140 °F: it is lighter, by 1.6 %, and its heat capacity changes little.
``btu_per_gal_f`` is that, a quartic in °F fitted to Kell's (1975)
density and IAPWS-95's heat capacity at one atmosphere, 32-212 °F,
to 0.002 BTU per gallon per °F.

The tank's layers hold equal volumes, so its heat is not linear in its
temperatures. ``heat_f`` makes it so: the temperature water holding a
constant ``WATER_BTU_PER_GAL_F`` would have with the same heat per
gallon, equal to the temperature at ``_REF_F``. A layer's heat is
``WATER_BTU_PER_GAL_F`` per gallon per degree of it, so mixing, flows
and heat put in are linear in it and conserve energy; ``temp_f``
takes it back, to 3e-13 of the heat. It reads 0.4 °F under the temperature at
120 °F and 0.8 at 150.
"""

from nwp500.sim.units import WATER_BTU_PER_GAL_F

#: ``btu_per_gal_f``'s coefficients, the constant first (°F⁰ to °F⁴).
_C = (
    8.53848269,
    -5.28082242e-3,
    4.61765100e-5,
    -2.44058000e-7,
    4.38000000e-10,
)
#: Where ``heat_f`` is the temperature, °F.
_REF_F = 60.0
#: ``heat_f`` as one polynomial in °F, the constant first: the integral
#: of ``btu_per_gal_f`` over ``WATER_BTU_PER_GAL_F``.
_H = (
    0.0,
    *(c / (k + 1) / WATER_BTU_PER_GAL_F for k, c in enumerate(_C)),
)
#: Where Newton's method starts for ``temp_f``: a quintic in the heat
#: fitted on 20-220 °F, within 0.0006 °F there.
_T = (
    0.5935399495663974,
    0.976471515738717,
    0.0003132110929141318,
    -1.8366549817121586e-06,
    7.380084003243354e-09,
    -1.056034059727582e-11,
)
#: The span the start is fitted on, °F: one step from it is within
#: 1e-10 °F there, and outside it two more are taken.
_START_SPAN_F = (20.0, 220.0)


def btu_per_gal_f(temp_f: float) -> float:
    """A gallon's heat per °F at ``temp_f``, BTU."""
    c0, c1, c2, c3, c4 = _C
    t = temp_f
    return c0 + t * (c1 + t * (c2 + t * (c3 + t * c4)))


def _raw_heat_f(temp_f: float) -> float:
    _, h1, h2, h3, h4, h5 = _H
    t = temp_f
    return t * (h1 + t * (h2 + t * (h3 + t * (h4 + t * h5))))


_OFFSET_F = _REF_F - _raw_heat_f(_REF_F)


def heat_f(temp_f: float) -> float:
    """Water at ``temp_f``'s heat, as the temperature water of a constant
    ``WATER_BTU_PER_GAL_F`` would have with it, °F."""
    _, h1, h2, h3, h4, h5 = _H
    t = temp_f
    return _OFFSET_F + t * (h1 + t * (h2 + t * (h3 + t * (h4 + t * h5))))


def temp_f(heat: float) -> float:
    """The temperature whose ``heat_f`` is ``heat``, °F: Newton's
    method from a fitted start (``_T``)."""
    a0, a1, a2, a3, a4, a5 = _T
    h = heat
    t = a0 + h * (a1 + h * (a2 + h * (a3 + h * (a4 + h * a5))))
    low, high = _START_SPAN_F
    steps = 1 if low <= t <= high else 3
    for _ in range(steps):
        t -= (heat_f(t) - heat) * WATER_BTU_PER_GAL_F / btu_per_gal_f(t)
    return t
