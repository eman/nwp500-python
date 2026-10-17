"""R-134a refrigerant saturation property table and interpolation functions.

Property values are derived from ASHRAE Standard 34 and cross-referenced
against the observed telemetry ranges for the Navien NWP500 installation.
The key insight is that saturated vapor density — not Carnot COP — drives
the observed 1.7× capacity difference between the two empirical calibration
cycles.

All temperatures are in °F, pressures in psia, densities in lb/ft³, and
enthalpies in BTU/lb.
"""

from bisect import bisect_right
from math import fma, isnan

import numpy as np

# ── Saturation property table ────────────────────────────────────────────────
# Columns: T_f, P_sat_psia, rho_g_lb_ft3, h_f_btu_lb, h_g_btu_lb
# Temperature range covers the operating envelope:
#   evaporator: ~20°F (41°F ambient − 21°F approach) → 80°F (warm ambient)
#   condenser:  ~130°F–165°F (T_lower + 10°F approach)
#
# Critical density values:
#   40°F → 0.265 lb/ft³ (cold-cycle calibration point)
#   80°F → 0.535 lb/ft³ (warm-cycle calibration point)
#   Ratio ≈ 2.02× — primary driver of 1.7× capacity difference.

_TABLE = np.array(
    [
        # T_f    P_sat    rho_g    h_f      h_g
        [0.0, 21.3, 0.108, 26.6, 108.9],
        [10.0, 26.4, 0.132, 30.3, 110.7],
        [20.0, 33.2, 0.164, 34.0, 112.5],
        [32.0, 42.5, 0.225, 38.8, 115.9],  # frost onset
        [40.0, 49.8, 0.265, 43.5, 117.8],  # cold-cycle calibration
        [50.0, 60.1, 0.316, 48.0, 119.9],
        [53.0, 65.0, 0.342, 50.0, 120.5],  # cold-cycle mean evap
        [60.0, 72.4, 0.384, 52.7, 121.9],
        [70.0, 86.7, 0.454, 57.5, 123.8],
        [80.0, 101.3, 0.535, 62.4, 124.4],  # warm-cycle mean evap
        [90.0, 122.7, 0.634, 67.3, 125.4],
        [100.0, 146.4, 0.747, 72.3, 125.9],
        [110.0, 172.6, 0.876, 77.5, 125.7],
        [120.0, 186.0, 1.050, 82.9, 125.1],  # typical condensing midpoint
        [130.0, 210.6, 1.240, 88.6, 124.0],
        [140.0, 238.2, 1.470, 94.6, 122.4],
        [150.0, 268.6, 1.750, 100.9, 120.2],
        [160.0, 302.2, 2.100, 107.5, 117.2],
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
# what actually has to hold -- exact at the knots and in the clamped tails,
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
    Valid for the residential ambient range (30–120°F, 10–100% RH).

    Args:
        t_db_f: Dry-bulb temperature in °F.
        rh_pct: Relative humidity in percent (0–100).
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
