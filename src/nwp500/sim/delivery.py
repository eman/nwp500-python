"""Hot water at the tap: how much the tank can deliver now, and the
delivered temperature along a simulation, both from the tank's layers
(``physics.stratified``).

**Deliverable volume** is the water delivered past the mixing valve
that the tank gives before the **delivered** water falls below the line
(``ReadinessParams.line_f``): the water leaving the top in turn, each
tank gallon delivering ``1 / hot_fraction`` at the tap
(``physics.draw``), to the first that the valve delivers under the line
(``stratified.deliverable_gal``). The tank's outlet is its top, above
the upper probe, so the tap stays hot for the water above the probe
after the probe has crossed. The mains the draw meets is the scenario's
inlet, else ``DrawParams.inlet_temp_f`` (a caller that knows the day
passes ``DrawParams.mains_on``'s).

**The layers** are the state's (``HeaterState.layers_f``: as the tank's
history left them, ``sim.history``), and ``basis`` says ``layers``;
without them, the profile the two probes stand for
(``stratified.estimate``), and ``basis`` says ``probes``. The probes
alone cannot say where the water below the lower one is: after a draw
the bottom is the inlet's, which they read as no different from a tank
that coasted.

**The delivery along a simulation** (``delivery_along``) is the top
layer's water through the valve (``delivery_f``), so a simulation's
delivery and its windows' ``deliverable_gal`` read the same layers and
agree on whether and when the tank runs out.

**A draw runs cold** (``depletion``) when the delivery falls below the
line.
"""

import itertools
import math
from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from nwp500.sim.engine import HeatingInterval, PathPoint, Simulation
from nwp500.sim.params import DrawParams, HeaterParams, ReadinessParams
from nwp500.sim.physics import stratified as st
from nwp500.sim.physics.draw import delivery_temp_f


@dataclass(frozen=True)
class Deliverable:
    """Deliverable volume, delivered gallons at the line, and what it
    rests on: the tank's ``layers``, or the profile its two ``probes``
    stand for."""

    gal: float
    basis: Literal["layers", "probes"]


def _valve(params: HeaterParams) -> tuple[float, float]:
    d = params.draw
    return d.delivery_intercept_f, d.delivery_slope


def _tank(
    params: HeaterParams,
    upper_f: float,
    lower_f: float,
    layers_f: Sequence[float] | None,
) -> tuple[st.Layout, st.TankState]:
    lay = st.layout(params)
    if layers_f is None:
        return lay, st.mix(st.estimate(lay, upper_f, lower_f))
    if len(layers_f) != lay.layers:
        raise ValueError(
            f"{len(layers_f)} layers given, the parameters lay out {lay.layers}"
        )
    return lay, st.mix(st.TankState(tuple(float(t) for t in layers_f)))


def deliverable(
    params: HeaterParams,
    upper_f: float,
    lower_f: float,
    layers_f: Sequence[float] | None = None,
    *,
    inlet_f: float | None = None,
) -> Deliverable:
    """Deliverable gallons now, at the delivered line, a tenth of a
    gallon: from the tank's ``layers_f`` (the bottom first), else from
    the profile the probes ``upper_f`` and ``lower_f`` stand for; the
    mains at ``inlet_f``, else ``DrawParams.inlet_temp_f``."""
    lay, tank = _tank(params, upper_f, lower_f, layers_f)
    inflow = params.draw.inlet_temp_f if inlet_f is None else inlet_f
    gal = st.deliverable_gal(
        lay, tank, params.readiness.line_f, inflow, _valve(params)
    )
    return Deliverable(
        gal=round(gal, 1) if math.isfinite(gal) else gal,
        basis="probes" if layers_f is None else "layers",
    )


def within_resolution(
    params: HeaterParams,
    upper_f: float,
    lower_f: float,
    layers_f: Sequence[float] | None,
    gal: float,
    *,
    inlet_f: float | None = None,
) -> bool:
    """Whether a probe error of ``ReadinessParams.probe_resolution_f``
    either way, on each probe on its own, would take ``deliverable``
    across ``gal``: less than the probes can resolve decides the answer.
    The layers are moved with the probes (``stratified.assimilate``),
    or the profile is made of the moved probes."""
    r = params.readiness.probe_resolution_f
    lay, tank = _tank(params, upper_f, lower_f, layers_f)
    inflow = params.draw.inlet_temp_f if inlet_f is None else inlet_f
    line, valve = params.readiness.line_f, _valve(params)

    def enough(state: st.TankState) -> bool:
        got = st.deliverable_gal(lay, state, line, inflow, valve)
        return round(got, 1) >= gal

    ready = enough(tank)
    seen_u, seen_l = st.observe(lay, tank)
    for du, dl in itertools.product((-r, 0.0, r), repeat=2):
        if du == dl == 0.0:
            continue
        moved = (
            st.estimate(lay, upper_f + du, lower_f + dl)
            if layers_f is None
            else st.assimilate(lay, tank, seen_u + du, seen_l + dl)
        )
        if enough(st.mix(moved)) != ready:
            return True
    return False


def delivery_f(
    params: HeaterParams,
    upper_f: float,
    layers_f: Sequence[float] | None = None,
) -> float:
    """What the tap gets now: the water leaving the top (the top layer,
    else the upper probe) through the mixing valve, never warmer than
    the tank's."""
    top = upper_f if layers_f is None else float(layers_f[-1])
    d = params.draw
    valve = delivery_temp_f(top, d.delivery_intercept_f, d.delivery_slope)
    return min(top, valve)


def _state_before(
    points: Sequence[PathPoint], at: datetime
) -> tuple[float, float] | None:
    """The simulated tank at ``at``, before anything taken at that
    instant: a draw's step sits on it as a second element."""
    for p0, p1 in itertools.pairwise(points):
        if p0.at <= at <= p1.at:
            span = (p1.at - p0.at).total_seconds()
            f = 0.0 if span <= 0 else (at - p0.at).total_seconds() / span
            return (
                p0.upper_f + (p1.upper_f - p0.upper_f) * f,
                p0.lower_f + (p1.lower_f - p0.lower_f) * f,
            )
    return None


def _at_onset(
    points: Sequence[PathPoint],
    delivery: Sequence[float],
    at: datetime,
    upper: float,
) -> float:
    """The delivery at ``at``, before anything drawn there: the last
    element before it, or the first at it; the zone if none."""
    k = next((i for i, p in enumerate(points) if p.at >= at), None)
    if k is None:
        return upper
    return delivery[k] if points[k].at == at else delivery[max(0, k - 1)]


@dataclass(frozen=True)
class Depletion:
    """The delivery temperature over a span, and whether it fell below
    the line."""

    #: The lowest delivery over the span, °F.
    min_f: float
    #: The longest stretch below the line, minutes.
    below_min: float
    #: Below the line at any point: the draw ran cold.
    depleted: bool


def depletion(
    points: Sequence[PathPoint],
    a: datetime,
    b: datetime,
    delivery: Sequence[float],
    p: ReadinessParams | None = None,
) -> Depletion:
    """The delivery temperature over ``[a, b]``: depleted when it falls
    below the line (``ReadinessParams.line_f``). ``delivery`` is its
    value at each element of ``points`` (``delivery_along``). Linear
    between the path's elements; a draw's step is two elements at one
    instant."""
    p = p or ReadinessParams()
    threshold_f = p.line_f
    values = list(delivery)
    series = [
        replace(pt, upper_f=v, lower_f=v)
        for pt, v in zip(points, values, strict=True)
    ]
    first = _state_before(series, a)
    path = [(a, first[0] if first is not None else values[0])]
    # The elements at ``a`` too: a draw at the onset is a step there,
    # and its cold side is the window's.
    path += [
        (pt.at, v)
        for pt, v in zip(points, values, strict=True)
        if a <= pt.at < b
    ]
    last = _state_before(series, b)
    if b > a and last is not None:
        # The state after anything taken at ``b``: the last element there.
        at_b = [v for pt, v in zip(points, values, strict=True) if pt.at == b]
        path.append((b, at_b[-1] if at_b else last[0]))
    low = min(u for _, u in path)
    longest = timedelta(0)
    below_since: datetime | None = a if path[0][1] < threshold_f else None
    for (t0, u0), (t1, u1) in itertools.pairwise(path):
        if below_since is None and u1 < threshold_f:
            below_since = (
                t0
                if t1 == t0 or u0 <= u1
                else t0 + (t1 - t0) * ((u0 - threshold_f) / (u0 - u1))
            )
        elif below_since is not None and u1 >= threshold_f:
            up = (
                t1
                if t1 == t0 or u1 <= u0
                else t0 + (t1 - t0) * ((threshold_f - u0) / (u1 - u0))
            )
            longest = max(longest, up - below_since)
            below_since = None
    if below_since is not None:
        longest = max(longest, path[-1][0] - below_since)
    minutes = longest.total_seconds() / 60.0
    return Depletion(low, minutes, low < threshold_f)


def delivery_along(
    points: Sequence[PathPoint], params: HeaterParams
) -> list[float]:
    """The delivery temperature at each element of the path
    (``delivery_f``), from its layers, or from its upper probe where it
    has none."""
    return [delivery_f(params, pt.upper_f, pt.layers_f) for pt in points]


@dataclass(frozen=True)
class DrawWindowResult:
    """A draw window as the simulation found it: the tank at its onset,
    the deliverable gallons and the delivery there, and the delivery
    over the window (``depletion``)."""

    start: datetime
    end: datetime
    #: Delivered gallons the caller expects the window to draw.
    expected_gal: float | None
    upper_f: float
    lower_f: float
    #: The delivery at the onset, °F.
    delivery_f: float
    #: Deliverable gallons at the onset (``deliverable``).
    deliverable_gal: float
    #: ``deliverable_gal`` less the expected gallons; None without an
    #: expectation.
    margin_gal: float | None
    #: The heating interval overlapping the window, if any.
    recovery: HeatingInterval | None
    #: The delivery over the window (``depletion``).
    delivery_min_f: float
    below_line_min: float
    depleted: bool
    #: For a forecast's window (``DrawWindow.expected_count``): the
    #: draws it expects, fractional, and when its long draws end in the
    #: worst case (``DrawWindow.draws_until``). None otherwise.
    expected_count: float | None = None
    draws_until: datetime | None = None


def _onset(points: Sequence[PathPoint], at: datetime) -> PathPoint | None:
    """The path's element in force at ``at``, before anything taken
    there: the first at that instant, else the last before it."""
    k = bisect_left([p.at for p in points], at)
    if k < len(points) and points[k].at == at:
        return points[k]
    return points[k - 1] if k > 0 else None


def draw_windows(
    sim: Simulation,
    windows: Sequence[tuple[datetime, datetime, float | None]],
    delivery: Sequence[float],
    params: HeaterParams,
    *,
    inlet_f: float | None = None,
    inlet_on: Callable[[datetime], float] | None = None,
    forecast: Sequence[tuple[float | None, datetime | None]] = (),
) -> list[DrawWindowResult]:
    """One per ``(start, end, expected_gal)`` window; ``forecast`` gives
    each, by index, the draws a forecast expects in it and the end of its
    long draws in the worst case. The tank at the onset (before anything
    drawn there), its ``deliverable_gal`` and the delivery judged over
    the window all read the path's layers. ``inlet_on`` gives the mains
    at a window's onset, in place of ``inlet_f``."""
    p = params.readiness
    out: list[DrawWindowResult] = []
    for k, (start, end, expected) in enumerate(windows):
        count, draws_until = forecast[k] if k < len(forecast) else (None, None)
        # A window already open at the start is read at the start.
        opened = max(start, sim.points[0].at)
        state = _state_before(sim.points, opened)
        there = _onset(sim.points, opened)
        if state is None or there is None:
            continue
        upper, lower = state
        judged = depletion(
            sim.points, opened, min(end, sim.points[-1].at), delivery, p
        )
        gal = deliverable(
            params,
            upper,
            lower,
            there.layers_f,
            inlet_f=inlet_f if inlet_on is None else inlet_on(opened),
        ).gal
        recovery = next(
            (h for h in sim.heating if h.start.at < end and h.end > start),
            None,
        )
        out.append(
            DrawWindowResult(
                start=start,
                end=end,
                expected_gal=expected,
                upper_f=upper,
                lower_f=lower,
                delivery_f=_at_onset(sim.points, delivery, opened, upper),
                deliverable_gal=gal,
                margin_gal=None if expected is None else gal - expected,
                recovery=recovery,
                delivery_min_f=judged.min_f,
                below_line_min=judged.below_min,
                depleted=judged.depleted,
                expected_count=count,
                draws_until=draws_until,
            )
        )
    return out


def draw_domain_judgement(
    draw: DrawParams,
    walk: Sequence[tuple[datetime, float]],
    volume_gal: float,
) -> tuple[bool, datetime | None]:
    """The draw-range judgement over a projection's instants: whether a
    draw of ``volume_gal`` (the largest the projection draws) would lie
    outside the range the draw terms were fitted over at any instant of
    ``walk`` (``(at, upper_f)``), and the bound: the first instant from
    which every later one is out of range too, so a draw anywhere from
    it to the end is extrapolated. None when the walk ends in range: a
    start above the band that decays into it is out at the start, and
    naming the start would end a phase at zero length though its draws,
    later, are in range."""
    out = [draw.out_of_domain(up, volume_gal) for _, up in walk]
    bound: datetime | None = None
    for (at, _), is_out in zip(reversed(walk), reversed(out), strict=True):
        if not is_out:
            break
        bound = at
    return any(out), bound
