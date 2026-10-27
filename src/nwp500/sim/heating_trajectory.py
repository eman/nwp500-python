"""The heating path published with a recovery.

The stratified tank's walk under the heat pump (``TankPhysics.recover``)
is the recovery's path: each element at a step of the walk, carrying
both probes, the electricity over the interval ending there, the heat
the tank kept and the heat pump's COP.

**Electricity is the map's** (``physics.heat_pump.power_w``), drawn
from the compressor's start, through its hold.

**Heat stored is the layers'**: the change in the tank's heat over the
interval, net of what the jacket and the circulation took.

**COP is the map's** over the interval: the heat the heat pump put in
over the electricity it drew. The hold, which heats nothing, has none.

Each element's ``input_energy_wh`` is the difference of the rounded
running total, so the elements sum exactly to the recovery's total
however the grid falls. That is what lets a caller price a recovery that
crosses a tariff boundary by summing elements per slot.
"""

from dataclasses import dataclass
from datetime import datetime

from nwp500.sim.physics import stratified as st
from nwp500.sim.units import BTU_PER_WH

#: Published precision: temperatures to 0.001 °F, energy to 0.01 Wh.
_TEMP_DECIMALS = 3
_WH_DECIMALS = 2
_COP_DECIMALS = 3


@dataclass(frozen=True)
class HeatingPoint:
    """One element of the heating trajectory."""

    at: datetime
    t_upper_f: float
    t_lower_f: float
    #: Electrical input over the interval ending at ``at``, Wh. ``0.0``
    #: on the first element, which ends no interval.
    input_energy_wh: float | None
    #: Heat stored in the tank over the same interval, Wh, net of what
    #: it lost. ``0.0`` on the first element.
    stored_energy_wh: float
    #: The heat pump's COP over the interval (the map's heat over its
    #: electricity). Positive when not None. None on the first element
    #: and on one in the hold.
    cop: float | None = None


def from_walk(lay: st.Layout, walked: st.Walked) -> list[HeatingPoint]:
    """The trajectory of a recovery's walk (``physics.stratified.walk``)
    in the tank ``lay`` lays out."""
    out: list[HeatingPoint] = []
    total = 0.0
    shown = 0.0
    before = st.energy_btu(lay, walked.path[0][1])
    for k, (at, state) in enumerate(walked.path):
        upper, lower = st.observe(lay, state)
        if k == 0:
            out.append(
                HeatingPoint(
                    at,
                    round(upper, _TEMP_DECIMALS),
                    round(lower, _TEMP_DECIMALS),
                    0.0,
                    0.0,
                )
            )
            continue
        step = walked.steps[k - 1]
        total += step.compressor_wh
        rounded = round(total, _WH_DECIMALS)
        heat = st.energy_btu(lay, state)
        cop = (
            round(
                step.compressor_btu / (step.compressor_wh * BTU_PER_WH),
                _COP_DECIMALS,
            )
            if step.compressor_btu > 0.0 and step.compressor_wh > 0.0
            else None
        )
        out.append(
            HeatingPoint(
                at,
                round(upper, _TEMP_DECIMALS),
                round(lower, _TEMP_DECIMALS),
                round(rounded - shown, _WH_DECIMALS),
                round((heat - before) / BTU_PER_WH, _WH_DECIMALS),
                cop,
            )
        )
        shown, before = rounded, heat
    return out
