"""Temperature-dependent standby loss coefficient.

The decay ODE and the physics ODE both subtract a standby loss term
``UA · (T_tank − T_amb)``.  Both used to take ``UA`` as a single fitted
scalar.  That is wrong across the range this tank actually operates in.

Measured on clean quiet windows (no compressor and no water moving),
fitting each window independently:

======================  ========  ====================  ========
Window                  mean ΔT   UA (BTU/hr·°F)        fit RMSE
======================  ========  ====================  ========
2026-08-08 → 08-12      13.1 °F   3.14                  0.15 °F
2026-07-31 03:20→15:30  61.8 °F   5.58                  0.11 °F
======================  ========  ====================  ========

A 1.78× spread with residuals of 0.11–0.15 °F is not measurement noise.
A single constant fitted on the hot windows — which is what the corpus is
made of, because hot windows are what happens between ordinary draws —
overstates cold-tank loss by ~1.75×, and a constant fitted on the cold
window understates hot-tank loss by about as much.

The law here is a power law in ΔT::

    UA(ΔT) = ua_ref · (max(|ΔT|, 5) / ref_delta_t) ^ exponent

The shape is not arbitrary.  Free convection in the insulation gap and in
the standing plumbing above the tank scales as ΔT^0.25 (laminar) to
ΔT^0.33 (turbulent); the two anchors above imply an exponent of 0.371,
which sits just above the turbulent value — consistent with an additional
thermosiphon term in the standing plumbing that only runs when the tank
is hot.  So the functional form carries a physical prior rather than
being a curve fitted to two points.

Which is the caveat that matters: **it is two points.**  The corpus has
n=2 windows below ΔT 20 °F (both from a single 2026-08 vacation episode)
and nothing at all between 20 and 40 °F.  The fit that sets the exponent
(outside the core: it is a fit) therefore refuses to fit one until the
corpus spans at least two ΔT bands, and falls back to the constant-UA
behaviour that shipped before it.

``exponent = 0.0`` reproduces the pre-existing constant-UA model exactly,
which is also what parameter sets fitted before the law existed carry.
"""

from nwp500.sim.params import UA_MIN_DELTA_T_F, UA_REF_DELTA_T_F


def ua_at(
    delta_t: float,
    ua_ref: float,
    exponent: float,
    ref_delta_t: float = UA_REF_DELTA_T_F,
) -> float:
    """Standby loss coefficient at a given tank-to-ambient difference.

    Args:
        delta_t: Tank temperature minus ambient (°F).  Sign is ignored;
            the loss coefficient is symmetric.
        ua_ref: UA at ``ref_delta_t`` (BTU/hr·°F).
        exponent: Power-law exponent.  ``0.0`` gives constant UA.
        ref_delta_t: ΔT at which ``ua_ref`` is quoted (°F).

    Returns:
        UA in BTU/hr·°F.
    """
    if exponent == 0.0:
        # Exact passthrough, not a pow() that happens to return 1.0 —
        # older parameter sets must reproduce their old numbers bit for
        # bit.
        return ua_ref
    scaled = max(abs(delta_t), UA_MIN_DELTA_T_F) / ref_delta_t
    return float(ua_ref * scaled**exponent)
