"""R-134a refrigerant saturation property table and interpolation functions.

The values are CoolProp's (the table's comment). Saturated vapour
density at the evaporator is what scales the modelled capacity with the
air: the compressor moves a fixed volume, so its mass flow follows the
suction gas's density.

All temperatures are in °F, pressures in psia, densities in lb/ft³, and
enthalpies in BTU/lb.
"""

from bisect import bisect_right
from math import fma, isnan

import numpy as np

# ── Saturation property table ────────────────────────────────────────────────
# Columns: T_f, P_sat_psia, rho_g_lb_ft3, h_f_btu_lb, h_g_btu_lb
# From CoolProp 8.0.0 (Bell et al. 2014, the Tillner-Roth and Baehr 1994
# equation of state for R-134a) every 5 °F, enthalpies on the ASHRAE
# reference (h = 0 for saturated liquid at -40 °F). The range covers the
# operating envelope: the evaporator from about 20 °F (cold air, the
# approach) to 80 °F, and the condenser at the lower zone plus its
# approach, clamped to 80-160 °F.

_TABLE = np.array(
    [
        # T_f    P_sat    rho_g    h_f      h_g
        [0.0, 21.17, 0.4634, 12.20, 103.09],
        [5.0, 23.78, 0.5173, 13.75, 103.82],
        [10.0, 26.63, 0.5761, 15.32, 104.55],
        [15.0, 29.74, 0.6401, 16.89, 105.27],
        [20.0, 33.12, 0.7095, 18.47, 105.99],
        [25.0, 36.80, 0.7848, 20.06, 106.70],
        [30.0, 40.78, 0.8663, 21.65, 107.40],
        [35.0, 45.09, 0.9544, 23.26, 108.09],
        [40.0, 49.74, 1.0495, 24.87, 108.78],
        [45.0, 54.75, 1.1521, 26.50, 109.46],
        [50.0, 60.13, 1.2627, 28.13, 110.14],
        [55.0, 65.91, 1.3816, 29.78, 110.80],
        [60.0, 72.11, 1.5095, 31.43, 111.45],
        [65.0, 78.73, 1.6470, 33.10, 112.09],
        [70.0, 85.80, 1.7946, 34.78, 112.72],
        [75.0, 93.35, 1.9530, 36.47, 113.34],
        [80.0, 101.39, 2.1229, 38.17, 113.94],
        [85.0, 109.93, 2.3052, 39.89, 114.53],
        [90.0, 119.01, 2.5007, 41.62, 115.11],
        [95.0, 128.65, 2.7103, 43.36, 115.67],
        [100.0, 138.85, 2.9352, 45.12, 116.21],
        [105.0, 149.65, 3.1763, 46.90, 116.73],
        [110.0, 161.07, 3.4351, 48.70, 117.24],
        [115.0, 173.14, 3.7130, 50.51, 117.72],
        [120.0, 185.86, 4.0116, 52.35, 118.18],
        [125.0, 199.28, 4.3327, 54.20, 118.61],
        [130.0, 213.41, 4.6786, 56.08, 119.02],
        [135.0, 228.28, 5.0517, 57.98, 119.39],
        [140.0, 243.92, 5.4549, 59.91, 119.73],
        [145.0, 260.36, 5.8916, 61.87, 120.03],
        [150.0, 277.61, 6.3657, 63.87, 120.29],
        [155.0, 295.73, 6.8822, 65.89, 120.50],
        [160.0, 314.73, 7.4471, 67.96, 120.65],
    ],
    dtype=float,
)
# Read-only, and so are the column views below: the core holds no
# mutable module state.
_TABLE.setflags(write=False)

_T = _TABLE[:, 0]
_P = _TABLE[:, 1]
_RHO = _TABLE[:, 2]
_HF = _TABLE[:, 3]
_HG = _TABLE[:, 4]

# ── Scalar interpolation ─────────────────────────────────────────────────────
# These four lookups were `float(np.interp(t_f, _T, col))`.  Correct, but
# np.interp is an array function: on a scalar it spends roughly 1.5 µs in
# dispatch, argument coercion and the 0-d round trip to do about a dozen
# floating-point operations against an 18-row table.
#
# That is invisible until you count the calls.  predict_physics() walks the
# recovery in Python, and calibrate_physics() wraps it in a Nelder-Mead fit,
# so one training run made ~11.9 million of these calls and spent 18.4 s
# of a 34.3 s profile inside np.interp.  It is the single hottest path in the
# physics model, and it slows every calibration, not only the tests.
#
# So the table is unpacked once into plain Python tuples and the lookup is a
# bisect plus a fused multiply-add.  Values do not move: fma(slope, x-x0, y0)
# is what numpy computes, so on FMA hardware this is bit-identical to
# np.interp, and it is the more accurate form regardless -- one rounding
# instead of two.  Exact bit-equality with np.interp is deliberately NOT the
# contract, because it is not numpy's either: whether np.interp contracts the
# multiply-add depends on the numpy build and the CPU.  What is asserted is
# what has to hold -- exact at the knots and in the clamped tails,
# within one ulp between them, and NaN in gives NaN out.
_T_LIST: tuple[float, ...] = tuple(_T.tolist())
_T_LO = _T_LIST[0]
_T_HI = _T_LIST[-1]


def _slopes(values: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(
        (values[i + 1] - values[i]) / (_T_LIST[i + 1] - _T_LIST[i])
        for i in range(len(values) - 1)
    )


def _lookup(
    t_f: float, values: tuple[float, ...], slopes: tuple[float, ...]
) -> float:
    """Linear interpolation over _T, matching np.interp bit for bit."""
    # np.interp returns NaN for NaN; bisect would silently pick an interval.
    if isnan(t_f):
        return float("nan")
    if t_f <= _T_LO:
        return values[0]
    if t_f >= _T_HI:
        return values[-1]
    i = bisect_right(_T_LIST, t_f) - 1
    # fma, not `slope * dx + y0`: one rounding instead of two.  It is both
    # the more accurate form and the one numpy itself uses, so on FMA
    # hardware this reproduces np.interp exactly.
    return fma(slopes[i], t_f - _T_LIST[i], values[i])


_P_V: tuple[float, ...] = tuple(_P.tolist())
_RHO_V: tuple[float, ...] = tuple(_RHO.tolist())
_HF_V: tuple[float, ...] = tuple(_HF.tolist())
_HG_V: tuple[float, ...] = tuple(_HG.tolist())

_P_S = _slopes(_P_V)
_RHO_S = _slopes(_RHO_V)
_HF_S = _slopes(_HF_V)
_HG_S = _slopes(_HG_V)


def sat_pressure(t_f: float) -> float:
    """Saturation pressure (psia) at temperature t_f (°F)."""
    return _lookup(t_f, _P_V, _P_S)


def vapor_density(t_f: float) -> float:
    """Saturated vapor density (lb/ft³) at temperature t_f (°F)."""
    return _lookup(t_f, _RHO_V, _RHO_S)


def liquid_enthalpy(t_f: float) -> float:
    """Saturated liquid enthalpy h_f (BTU/lb) at temperature t_f (°F)."""
    return _lookup(t_f, _HF_V, _HF_S)


def vapor_enthalpy(t_f: float) -> float:
    """Saturated vapor enthalpy h_g (BTU/lb) at temperature t_f (°F)."""
    return _lookup(t_f, _HG_V, _HG_S)


def dew_point_f(t_db_f: float, rh_pct: float) -> float:
    """Estimate dew point (°F) from dry-bulb temperature and relative humidity.

    Uses the Magnus formula in Celsius, then converts back to Fahrenheit.
    Valid for the residential ambient range (30-120°F, 10-100% RH).

    Args:
        t_db_f: Dry-bulb temperature in °F.
        rh_pct: Relative humidity in percent (0-100).
    """
    # Convert to Celsius for Magnus formula
    t_c = (t_db_f - 32.0) / 1.8
    rh = max(0.01, min(100.0, rh_pct))

    # Magnus formula constants (Alduchov & Eskridge 1996)
    a, b = 17.625, 243.04
    alpha = (a * t_c) / (b + t_c) + np.log(rh / 100.0)
    dp_c = (b * alpha) / (a - alpha)

    # Convert back to Fahrenheit
    return float(dp_c) * 1.8 + 32.0
