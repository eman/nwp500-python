"""Temperature-dependent standby loss coefficient.

The decay ODE and the physics ODE both subtract a standby loss term
``UA · (T_tank − T_amb)``.  Both used to take ``UA`` as a single fitted
scalar.  That is wrong across the range this tank operates in.

Measured on clean quiet windows (no compressor and no water moving),
fitting each window independently:

======================  ========  ====================  ========
Window                  mean ΔT   UA (BTU/hr·°F)        fit RMSE
======================  ========  ====================  ========
2026-08-08 → 08-12      13.5 °F   2.93                  0.22 °F
2026-07-31 03:20→15:30  61.8 °F   5.58                  0.11 °F
======================  ========  ====================  ========

A 1.9× spread with residuals of 0.11-0.22 °F is not measurement noise.
A single constant fitted on the hot windows (which is what the corpus is
made of, because hot windows are what happens between ordinary draws)
overstates cold-tank loss by ~1.75×, and a constant fitted on the cold
window understates hot-tank loss by about as much.

The law here is a power law in ΔT::

    UA(ΔT) = ua_ref · (max(|ΔT|, 5) / ref_delta_t) ^ exponent

The shape is not arbitrary.  Free convection in the insulation gap and in
the standing plumbing above the tank scales as ΔT^0.25 (laminar) to
ΔT^0.33 (turbulent).  Fitted on 24 windows over 20 days, the exponent was
0.353, on the turbulent value; over one installation's full record, 301
windows spanning ΔT 11.2-90.7 °F with no band empty, it is 0.227, just
below the laminar one.  So the functional form carries a physical prior
rather than being a curve fitted to two points.

The 20-day fit was the weaker one: its two windows below ΔT 20 °F came
from a single standby soak, and it had none between 20 and 40 °F.  The
fit that sets the exponent (outside the core: it is a fit) therefore
refuses to fit one until the corpus spans at least two ΔT bands, and
falls back to the constant-UA behaviour that shipped before it.

``exponent = 0.0`` reproduces the pre-existing constant-UA model exactly,
which is also what parameter sets fitted before the law existed carry.

The bottom loss
---------------

The law above takes heat from the whole tank, and both probes see it.
Over one installation's 407 quiet windows across ten months, that
cannot be the whole loss. In a window that opens stratified (the upper
probe 1-10 °F above the lower), the gap **widens** rather than closing,
the lower probe falls about 40 % faster than in a mixed tank at the same
temperatures, and the upper probe hardly moves. A single UA fitted
across both kinds of window was a blend: about 4.0 BTU/hr·°F on mixed
windows, 6-7 on stratified ones. Mixed windows dominate after the full
recoveries a cold season brings, so the blend cooled the tank too fast
there.

That is heat leaving at the bottom, into the lower zone, where water
cooled outside the tank comes back in. It is
the same pattern ``physics.draw.lower_zone_drop_f`` measures for cold
water let in at the bottom: in a mixed tank it pools below the lower
probe, unseen, and the probe sees it once the thermocline reaches it.
So the bottom loss ``Q_b`` (``LossParams.bottom_loss_btu_hr``) is
charged to the lower zone alone, and the probe sees the share::

    reach = 1 − e^(−gap / gate)

of it (``bottom_loss_reach``). Fitted jointly with the UA law through
the standby walk on the 306 windows opening with a gap of at most
10 °F, 76 of them stratified, it came out at ``Q_b`` ≈ 89 BTU/hr and a
gate of 1.35 °F, and the UA law at a constant 4.6. The lower probe's
median error over ten hours fell from 1.25 to 0.77 °F from March to
October, and its bias from +0.58 to +0.06 °F; over the winter, from
1.67 to 1.05 °F, and to 1.15 °F trained on March to October alone.

The share the probe does not see is not carried: what a mixed tank
loses below the probe shows up later, through the draw's own pool
(``physics.draw``), not through this term. ``Q_b = 0.0`` is none, and
reproduces the law above exactly.
"""

import math

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
        # Exact passthrough, not a pow() that happens to return 1.0:
        # older parameter sets must reproduce their old numbers bit for
        # bit.
        return ua_ref
    scaled = max(abs(delta_t), UA_MIN_DELTA_T_F) / ref_delta_t
    return float(ua_ref * scaled**exponent)


def bottom_loss_reach(gap_f: float, gate_f: float) -> float:
    """The share of the bottom loss the lower probe sees at a
    stratification gap of ``gap_f``: ``1 − e^(−gap / gate)``, 0.0 in a
    mixed tank (or a gap that does not open, or no gate)."""
    if gap_f <= 0.0 or gate_f <= 0.0:
        return 0.0
    return 1.0 - math.exp(-gap_f / gate_f)


def bottom_loss_drop_f(
    bottom_loss_btu_hr: float,
    gap_f: float,
    gate_f: float,
    hours: float,
    lower_zone_btu_f: float,
) -> float:
    """How far the bottom loss takes the lower probe over ``hours``, °F:
    the share it sees (``bottom_loss_reach``) of ``bottom_loss_btu_hr``,
    against the lower zone's mass. 0.0 with no bottom loss."""
    if bottom_loss_btu_hr <= 0.0 or hours <= 0.0:
        return 0.0
    return (
        bottom_loss_btu_hr
        * bottom_loss_reach(gap_f, gate_f)
        * hours
        / lower_zone_btu_f
    )
