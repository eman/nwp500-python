"""A heater's recorded history, and the tank's layers it leaves.

Two probes do not say where the water below the lower one is: a tank
that coasts after a draw and one that coasts after a recovery read
alike and behave apart. The history before an instant does: ``replay``
walks the layered tank (``physics.stratified``) through what was
recorded, the compressor's runs, the elements', the draws and the
circulation's, corrected to the probes as they were read
(``tank_fit.replay``), and lays the probes' last readings over the
layers it leaves. Those are the ``HeaterState.layers_f`` a simulation
starts from; without them it starts from the two probes alone and says
``tank_profile_estimated``.

The history is a run of ``Step``: one interval each, what the heater
and the meter read over it. ``sim_adapters`` makes them of a heater's
statuses or its values' changes (``book_steps_from_history``,
``book_steps_from_changes``).

Nothing here reads a file, the network or the clock.
"""

from __future__ import annotations

import itertools
import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import numpy as np

from nwp500.sim.params import CirculationParams, HeaterParams
from nwp500.sim.physics import stratified as st
from nwp500.sim.physics.draw import delivery_temp_f, hot_fraction

if TYPE_CHECKING:
    from nwp500.sim.tank_fit import TankRecord

#: What a recorded flow counts: gallons delivered through the mixing
#: valve, or gallons of tank water (a meter or a detector on the
#: heater's hot outlet).
FlowVolume = Literal["delivered", "tank"]

#: The air a recorded step stands in when none was recorded, °F.
AMBIENT_DEFAULT_F = 65.0

#: How far back a replay starts (``tank_fit.replay``): the tank's
#: layers forget what came before.
REPLAY = timedelta(hours=24)

_MINUTE = timedelta(minutes=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Step:
    """One interval of a recorded history, ``seconds`` long: what the
    heater and the meter read over it."""

    seconds: float
    upper_f: float
    lower_f: float
    #: The household flow meter's reading, gal/min (0 without a meter:
    #: no draw is booked), in ``flow_volume``'s gallons.
    flow_gpm: float
    compressor_on: bool
    element_on: bool
    ambient_f: float
    inlet_f: float
    #: Circulation running, and its own flow, gal/min.
    circulating: bool = False
    circulation_gpm: float = 0.0
    #: Whether ``inlet_f`` was measured (an inlet probe).
    inlet_measured: bool = False
    #: Circulation's flow over the span ``flow_gpm`` was read over, 0
    #: where it was off: a meter's figure over a trailing window still
    #: holds a run for a while after it stops. None: ``circulation_gpm``
    #: while circulating, else none.
    circulation_in_meter_gpm: float | None = None
    #: Gallons the run had circulated before this step, runs closer
    #: than ``CirculationParams.run_gap_min`` taken as one: what
    #: ``CirculationParams.book_circuit_gal`` caps.
    run_gal_before: float = 0.0
    #: What ``flow_gpm`` counts (``FlowVolume``).
    flow_volume: FlowVolume = "delivered"
    #: When the step starts: None where only its length is known, which
    #: ``replay`` cannot place.
    at: datetime | None = None


def house_gpm(s: Step, circulation: CirculationParams | None = None) -> float:
    """The household's flow: the meter less the share of it that is
    circulation (``CirculationParams.meter_share`` of its own flow),
    never below 0."""
    share = 0.0 if circulation is None else circulation.meter_share
    if s.circulation_in_meter_gpm is not None:
        return max(0.0, s.flow_gpm - share * s.circulation_in_meter_gpm)
    if s.circulating:
        return max(0.0, s.flow_gpm - share * s.circulation_gpm)
    return s.flow_gpm


def _instant(s: Step) -> datetime:
    if s.at is None:
        raise ValueError("a step to replay says when it starts")
    return s.at.astimezone(UTC)


def drawn_gal(s: Step, params: HeaterParams) -> float:
    """The gallons delivered through the mixing valve over ``s``: the
    household's flow (``house_gpm``) over ``BookParams.draw_gpm``, none
    under it. Tank gallons (``Step.flow_volume``) are the valve's
    delivery of them: each takes a hot share of tank water
    (``physics.draw.hot_fraction``) at the step's upper probe, with the
    parameters' inlet."""
    house = house_gpm(s, params.circulation)
    if house <= params.book.draw_gpm:
        return 0.0
    gal = house * s.seconds / 60.0
    if s.flow_volume == "delivered":
        return gal
    d = params.draw
    delivered = delivery_temp_f(
        s.upper_f, d.delivery_intercept_f, d.delivery_slope
    )
    share = hot_fraction(s.upper_f, min(s.upper_f, delivered), d.inlet_temp_f)
    return gal / share if share > 0.0 else 0.0


def _runs(on: Sequence[bool]) -> tuple[tuple[int, int], ...]:
    """The runs of ``on``: each one's first and last-plus-one index."""
    out: list[tuple[int, int]] = []
    start: int | None = None
    for k, v in enumerate(on):
        if v and start is None:
            start = k
        elif not v and start is not None:
            out.append((start, k))
            start = None
    if start is not None:
        out.append((start, len(on)))
    return tuple(out)


def record(steps: Sequence[Step], params: HeaterParams) -> TankRecord:
    """``steps`` as the tank's record (``tank_fit.TankRecord``), on the
    minutes from the first step's on: each minute as the step under way
    at its start reads, the probes unknown and nothing running where
    none is, the air held from the last known (and the first, before
    it). The draws are each step's delivered gallons (``drawn_gal``),
    summed by minute at the minute's first step. Each step says when it
    starts (``Step.at``); a ValueError without any."""
    # The fit loads scipy, which the simulator's core does not.
    from nwp500.sim.tank_fit import TankRecord

    if not steps:
        raise ValueError("no steps to replay")
    starts = [_instant(s) for s in steps]
    if any(b < a for a, b in itertools.pairwise(starts)):
        raise ValueError("the steps are not in time order")
    first = starts[0]
    first += (_EPOCH - first) % _MINUTE
    end = starts[-1] + timedelta(seconds=steps[-1].seconds)
    n = max(0, math.floor((end - first) / _MINUTE))
    upper = [math.nan] * n
    lower = [math.nan] * n
    air = [math.nan] * n
    compressor = [False] * n
    element = [False] * n
    circulating = [False] * n
    for k in range(n):
        t = first + k * _MINUTE
        i = bisect_right(starts, t) - 1
        if i < 0 or t >= starts[i] + timedelta(seconds=steps[i].seconds):
            continue
        s = steps[i]
        upper[k], lower[k], air[k] = s.upper_f, s.lower_f, s.ambient_f
        compressor[k] = s.compressor_on
        element[k] = s.element_on
        circulating[k] = s.circulating
    known = [a for a in air if math.isfinite(a)]
    held = known[0] if known else AMBIENT_DEFAULT_F
    for k, a in enumerate(air):
        if math.isfinite(a):
            held = a
        else:
            air[k] = held
    drawn: dict[int, tuple[datetime, float]] = {}
    for t, s in zip(starts, steps, strict=True):
        gal = drawn_gal(s, params)
        if gal <= 0.0:
            continue
        k = math.floor((t - first) / _MINUTE)
        at, before = drawn.get(k, (t, 0.0))
        drawn[k] = (at, before + gal)
    return TankRecord(
        start=first,
        upper_f=np.array(upper, dtype=float),
        lower_f=np.array(lower, dtype=float),
        air_f=np.array(air, dtype=float),
        compressor=_runs(compressor),
        element=_runs(element),
        circulating=_runs(circulating),
        draws=tuple(sorted(drawn.values())),
    )


def replay(
    steps: Sequence[Step],
    params: HeaterParams,
    *,
    gain: float = 1.0,
    probes: tuple[float, float] | None = None,
) -> st.TankState | None:
    """The tank's layers at the end of ``steps``: the tank ``params``
    describe walked through the last ``REPLAY`` of them
    (``record``, ``tank_fit.replay``, corrected to the probes by
    ``gain`` as they were read), on the minutes up to the last step's
    end, and the probes laid over it exactly: ``probes``, (upper,
    lower) °F, or the last step's. None when
    the steps never read both probes and the air. Each step says when
    it starts (``Step.at``)."""
    from nwp500.sim import tank_fit as tf

    if not steps:
        return None
    rec = record(steps, params)
    if not len(rec):
        return None
    lay = st.layout(params)
    state = tf.replay(lay, params, rec, rec.instant(len(rec)), gain=gain)
    if state is None:
        return None
    upper_f, lower_f = (
        (steps[-1].upper_f, steps[-1].lower_f) if probes is None else probes
    )
    return st.mix(st.assimilate(lay, state, upper_f, lower_f))
