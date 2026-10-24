"""Hot water at the tap: how much the tank can deliver now, and the
delivered temperature along a simulation.

Everything here derives from **deliverable volume**: the water delivered
past the mixing valve that the tank can supply from its current state
before the **delivered** water falls below the line
(``ReadinessParams.line_f``).

**The delivered line is the probe's plus a lag.** Everything is measured
against the upper probe: the empty point is the heat left when it
crossed, the evidence is draws it saw finish above the line. But the
probe is not at the tap. The cold front rises from the bottom, so it
reaches the probe first, and the water above the probe, and in the pipe
to the fixture, still leaves hot: the delivered water crosses the line
``delivered_lag_gal`` gallons after the probe does. So the delivered
answer is the probe line's plus the lag while the probe line has water
left, and from the book, once it is spent, the lag less the gallons
drawn past it. Without a book, a probe below the line answers 0: nothing
says how far past it the draw went; nor does a tank colder than every
evidence draw get the lag, since the evidence vouches for no probe line
there.

**From the tank's booked heat** (``sim.book``) when the caller has a
book: the heat above the empty point, less what a cold region withholds,
per delivered gallon. On the installation the defaults come from, that
is the answer 78 % of the time and the one that can see a bath's cold
water the probes cannot.

**From the evidence otherwise** (``ReadinessParams.evidence``, none by
default): the longest draw the caller's record shows a tank in the same
or a worse state (neither probe warmer) delivering, finishing with the
heat pump and both elements off, from a settled start.
``EXAMPLE_EVIDENCE`` is one installation's.

**A full tank has a floor of its own.** When both probes are within
``full_setpoint_band_f`` of the setpoint or above it, the tank reads as
the book's anchor would, ``8.34 · V · (T_mean − 70)`` at a 70 °F inlet,
less ``full_hidden_gal``: the most the book found such a tank to hold
below what its probes said, the cold water of draws since its anchor
sitting under the lower probe. The answer is the larger of that and the
evidence's. Not while the heater runs: in a recovery's last minutes the
probes reach the setpoint over water it is still warming.

**A hot lower probe has the same floor.** With no book and no evidence,
a lower probe at or above the line says the hot water reaches at least
that low, so the tank reads the full-tank floor from its probes, heating
or not, with the lag on it: never less than ``delivered_lag_gal``.
Against one installation's book over a month, less ``full_hidden_gal``
it read above the book in 11 of 2,689 answers, all post-draw tanks at
rest, by at most 3.6 gal; while heating, never. Heating only adds heat,
so a floor from the probes now stays a floor.

**The book is read no higher than the tank can hold**: all of it at the
warmer probe (``book.tank_max_btu``).

**With the lower probe cold** the boundary is anywhere between the
probes, and heat booked into a cold bottom may not be drawable as hot:
on 2026-04-14 a draw from 139.6/78.4 °F stayed above 129 °F for 15.7
gal, and ninety minutes later a 10 gal top-up from 141.3/89.6 took the
upper probe to 101 °F. At or below ``cold_lower_cutoff_f`` the answer
carries ``thermocline_unlocated``. From the book, the heat that landed
in the cold bottom is withheld; from the evidence, the answer is
**capped** at ``cold_lower_cap_gal``.

**When it runs out** (``delivery_temp_f``): the drawable heat is what a
draw can take before the upper probe crosses the line, and the lag is
what the delivered water holds on after, so the delivery temperature is
the upper zone while either is left (the line itself while only the lag
is and the zone reads below it), the line when both are spent, and
``fall_f_per_gal`` lower per delivered gallon past it, down to the cold
region's temperature. A simulation's delivery (``delivery_along``) and
its windows' ``deliverable_gal`` read the same state, so the two agree on
whether and when the tank runs out. Without a book the delivery is the
upper zone's on the same line (``zone_delivery_f``).

**A draw runs cold** (``depletion``) when the delivery falls more than
``dip_f`` below the line, or stays below it for longer than
``dip_min``: the heater's own transient dip during a draw is not
running out.
"""

import itertools
import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from nwp500.sim.book import (
    Booked,
    BookedPath,
    deliverable_from_heat,
    full_tank,
    probe_line_gal,
)
from nwp500.sim.book import delivery_f as tank_delivery_f
from nwp500.sim.engine import Draw, HeatingInterval, PathPoint, Simulation
from nwp500.sim.params import (
    BookParams,
    DrawParams,
    EvidenceDraw,
    ReadinessParams,
)
from nwp500.sim.units import WATER_BTU_PER_GAL_F


def demonstrated_gal(
    upper_f: float,
    lower_f: float,
    evidence: tuple[EvidenceDraw, ...] = (),
) -> float:
    """The most any evidence draw from a state no better than this one
    delivered before crossing the threshold; 0 if none is that bad."""
    return max(
        (g for u, lo, g in evidence if u <= upper_f and lo <= lower_f),
        default=0.0,
    )


def hot_to_the_lower_probe(
    lower_f: float, p: ReadinessParams | None = None
) -> bool:
    """The lower probe at or above the line: the hot water reaches at
    least as low as it."""
    p = p or ReadinessParams()
    return lower_f >= p.line_f


def full_tank_floor_gal(
    upper_f: float,
    lower_f: float,
    setpoint_f: float | None,
    p: ReadinessParams | None = None,
    ep: BookParams | None = None,
    *,
    heating: bool = False,
    uniform: bool = False,
) -> float:
    """A full tank: the book's anchor heat at a 70 °F inlet, less
    ``full_hidden_gal``. Full is at its setpoint, or with ``uniform``
    (no evidence to answer instead) both probes within the book's
    ``uniform_band_f``, where two probes place the heat as the book's
    anchor does, or the lower probe at or above ``line_f``, heating or
    not (module docstring). 0 for any other state, or while the heater
    runs."""
    p = p or ReadinessParams()
    ep = ep or BookParams()
    at_setpoint = (
        setpoint_f is not None
        and min(upper_f, lower_f) >= setpoint_f - p.full_setpoint_band_f
    )
    if not (uniform and hot_to_the_lower_probe(lower_f, p)) and (
        heating
        or not (
            at_setpoint
            or (uniform and abs(upper_f - lower_f) <= ep.uniform_band_f)
        )
    ):
        return 0.0
    inlet = ep.inlet_default_f
    heat = full_tank(upper_f, lower_f, inlet, ep).heat_btu
    gal = deliverable_from_heat(heat, upper_f, inlet, ep)
    return max(0.0, gal - p.full_hidden_gal)


@dataclass(frozen=True)
class Deliverable:
    """Deliverable volume, and what it rests on."""

    gal: float
    #: ``energy`` when the tank's booked heat answered (``sim.book``),
    #: ``evidence`` when there was none to book from, ``probes`` when
    #: there was no evidence either and the full-tank floor answered.
    basis: Literal["energy", "evidence", "probes"]
    thermocline_unlocated: bool
    #: Evidence basis only: the evidence's largest volume (not when the
    #: full-tank floor answered above it), and a tank cooler than every
    #: evidence draw, or with no evidence at all (0 for want of it).
    at_observed_max: bool
    colder_than_evidence: bool
    #: With no evidence at all and a tank the floor can't read (not
    #: full): the gallons are unknown, not none, and read 0.
    no_evidence: bool = False
    #: With no book and no evidence, the lower probe at or above the
    #: line answered (``hot_to_the_lower_probe``).
    from_probes: bool = False


def delivered_gal(
    probe_gal: float, upper_f: float, p: ReadinessParams | None = None
) -> float:
    """The delivered line from the probe's (module docstring): the
    lag on top while the probe line has water left, the lag less the
    gallons drawn past it once it is spent. A probe reading below the
    line says the probe line is spent, whatever the book says."""
    p = p or ReadinessParams()
    if upper_f < p.line_f:
        probe_gal = min(probe_gal, 0.0)
    return max(0.0, probe_gal + p.delivered_lag_gal)


def deliverable(
    upper_f: float,
    lower_f: float,
    p: ReadinessParams | None = None,
    *,
    heat_btu: float | None = None,
    inlet_f: float | None = None,
    withheld_btu: float = 0.0,
    ep: BookParams | None = None,
    setpoint_f: float | None = None,
    heating: bool = False,
) -> Deliverable:
    """Deliverable gallons now, at the delivered line.

    With the tank's booked heat, the drawable heat (above the empty
    point, less what the cold region withholds) over the heat a
    delivered gallon takes (the book's). Without it, the
    demonstrated volume from the evidence, capped where the lower probe
    is too cold for the heat below it to be drawn as hot, and no less
    than the full-tank floor at ``setpoint_f`` unless ``heating``. With
    no evidence either, a lower probe at or above the line answers the
    full-tank floor, heating or not, and the lag on it.
    Each is the probe's line; ``delivered_gal`` adds the lag. The
    booked heat is read no higher than ``tank_max_btu``.
    """
    p = p or ReadinessParams()
    ep = ep or BookParams()
    unlocated = lower_f <= p.cold_lower_cutoff_f
    demonstrated = floor = probe = 0.0
    from_probes = False
    if heat_btu is not None:
        probe = probe_line_gal(
            heat_btu,
            upper_f,
            lower_f,
            ep.inlet_default_f if inlet_f is None else inlet_f,
            withheld_btu,
            ep,
        )
        gal = delivered_gal(probe, upper_f, p)
        basis: Literal["energy", "evidence", "probes"] = "energy"
    elif upper_f < p.line_f:
        gal = 0.0
        basis = "evidence"
    else:
        demonstrated = demonstrated_gal(upper_f, lower_f, p.evidence)
        floor = full_tank_floor_gal(
            upper_f,
            lower_f,
            setpoint_f,
            p,
            ep,
            heating=heating,
            uniform=not p.evidence,
        )
        probe = max(demonstrated, floor)
        if unlocated:
            probe = min(probe, p.cold_lower_cap_gal)
        # The lag rides on a probe line the evidence vouches for, or on
        # a lower probe at the line: the zone above it keeps delivering
        # for the lag after the upper probe crosses. A tank colder than
        # every evidence draw is not known to have any: it may be a draw
        # already past its crossing that a transient lifted back over
        # the line (2026-04-14 04:02: an upper element on a spent top,
        # its lower probe cold), so it answers 0, as the reason says.
        from_probes = not p.evidence and hot_to_the_lower_probe(lower_f, p)
        gal = (
            delivered_gal(probe, upper_f, p)
            if probe > 0.0 or from_probes
            else 0.0
        )
        basis = "evidence" if p.evidence else "probes"
    evidence = basis == "evidence"
    unknown = basis == "probes" and probe == 0.0 and not from_probes
    return Deliverable(
        gal=round(gal, 1),
        basis=basis,
        thermocline_unlocated=unlocated,
        at_observed_max=(
            evidence
            and bool(p.evidence)
            and floor <= demonstrated
            and probe >= observed_max_gal(p.evidence)
        ),
        colder_than_evidence=(
            evidence and upper_f >= p.line_f and max(demonstrated, floor) == 0.0
        ),
        no_evidence=unknown,
        from_probes=from_probes,
    )


#: ``deliverable_gal`` is reported to this; less is none.
_GAL_RESOLUTION = 0.05


def booked_deliverable(
    booked: Booked,
    upper_f: float,
    lower_f: float,
    p: ReadinessParams | None = None,
    ep: BookParams | None = None,
) -> Deliverable:
    """``deliverable`` from a booked state: the answer now, and a draw
    window's at its onset, alike."""
    return deliverable(
        upper_f,
        lower_f,
        p,
        heat_btu=booked.heat_btu,
        inlet_f=booked.inlet_f,
        withheld_btu=booked.withheld_btu(ep),
        ep=ep,
    )


def delivery_temp_f(
    booked: Booked,
    upper_f: float,
    p: ReadinessParams | None = None,
    ep: BookParams | None = None,
    *,
    lower_f: float | None = None,
) -> float:
    """What the tank delivers past the valve, from the booked state
    (module docstring, *When it runs out*): the upper zone while the
    delivered line has water left (the line itself, not below it, while
    only the lag is left under a zone that reads below it); the line
    once it is spent, falling ``fall_f_per_gal`` per delivered gallon
    drawn past it, to no colder than the water coming up from the cold
    region. It is below the line exactly when ``booked_deliverable`` is
    zero at the same probes: the same heat, read no higher than
    ``tank_max_btu`` at ``lower_f`` (the upper alone without it), and
    the same lag."""
    p = p or ReadinessParams()
    ep = ep or BookParams()
    probe = probe_line_gal(
        booked.heat_btu,
        upper_f,
        upper_f if lower_f is None else lower_f,
        booked.inlet_f,
        booked.withheld_btu(ep),
        ep,
    )
    if probe == -math.inf:
        return upper_f
    if upper_f < p.line_f:
        probe = min(probe, 0.0)
    left = probe + p.delivered_lag_gal
    # Reported to a tenth of a gallon: what rounds to none is spent.
    if left >= _GAL_RESOLUTION:
        return max(upper_f, p.line_f)
    past = max(0.0, -left)
    floor = booked.cold_f if booked.cold_gal > 0.0 else booked.inlet_f
    fallen = _fallen_f(past, p)
    # With a lag the delivered water is warmer than the probe (one
    # measured bath's spout crossed the line with the probe at ~94.5 °F),
    # so it
    # falls from the line per gallon, not to the zone. With none, the
    # probe is the delivery and bounds it.
    top = upper_f if p.delivered_lag_gal <= 0.0 else math.inf
    return min(top, max(floor, fallen))


def _fallen_f(past_gal: float, p: ReadinessParams) -> float:
    """The delivery ``past_gal`` delivered gallons past the delivered
    crossing: ``fall_f_per_gal`` a gallon below the line, and just below
    it at the crossing, so zero gallons and a delivery under the line
    always go together."""
    fallen = p.line_f - p.fall_f_per_gal * past_gal
    return min(fallen, math.nextafter(p.line_f, 0.0))


def zone_delivery_f(
    upper_f: float,
    past_crossing_gal: float | None,
    p: ReadinessParams | None = None,
) -> float:
    """The delivery without a booked state, from the upper zone alone,
    on the same delivered line: the
    zone at or above the line; below it, the line itself until
    ``delivered_lag_gal`` gallons have been delivered since the zone
    crossed (``past_crossing_gal``, None while it has not), then falling
    per gallon, never below the zone."""
    p = p or ReadinessParams()
    if (
        upper_f >= p.line_f
        or past_crossing_gal is None
        or p.delivered_lag_gal <= 0.0
    ):
        return upper_f
    left = p.delivered_lag_gal - past_crossing_gal
    if left >= _GAL_RESOLUTION:
        return p.line_f
    return max(upper_f, _fallen_f(max(0.0, -left), p))


def observed_max_gal(evidence: tuple[EvidenceDraw, ...]) -> float:
    """The largest volume in ``evidence``: what ``at_observed_max``
    means; 0 with none."""
    return max((g for _, _, g in evidence), default=0.0)


# ── Example evidence ────────────────────────────────────────────────

#: The line ``EXAMPLE_EVIDENCE`` was measured at, °F.
EXAMPLE_EVIDENCE_LINE_F = 105.0

#: One NWP500-65 installation's evidence, an example and not a default:
#: each row one metered draw with the heat pump and both elements off
#: throughout, the upper and lower probes before it (°F) and the volume
#: it delivered past the mixing valve before the upper probe crossed
#: 105 °F (the whole draw if it never did), reduced to the frontier, 19
#: of 257 draws. It describes that household's mixing valve and draws:
#: no clean draw in it took the upper probe below 105 °F (the lowest
#: reached 107.2), so it is a floor, and a low one (a full tank that had
#: filled a 38 gal bath reads 33.4 gal). Its core assumption, that a
#: no-colder state delivers at least as much, fails on small drops (15
#: of 22 later draws over-promised for a 2 °F fall), because two probes
#: do not see where the hot/cold boundary is.
EXAMPLE_EVIDENCE: tuple[EvidenceDraw, ...] = (
    (124.88, 115.34, 8.2),
    (127.76, 102.20, 7.8),
    (127.76, 124.16, 11.7),
    (128.66, 125.24, 15.4),
    (129.20, 113.36, 8.7),
    (129.74, 99.32, 12.7),
    (130.64, 120.92, 13.6),
    (132.08, 127.76, 16.5),
    (133.70, 111.38, 14.2),
    (134.78, 135.86, 18.1),
    (134.96, 135.50, 18.3),
    (135.50, 135.68, 18.6),
    (135.86, 135.50, 23.6),
    (135.86, 136.76, 24.1),
    (139.64, 139.28, 25.1),
    (140.36, 132.98, 22.1),
    (141.08, 141.44, 33.4),
    (142.52, 113.00, 14.3),
    (142.52, 142.52, 38.2),
)


def with_example_evidence(p: ReadinessParams) -> ReadinessParams:
    """``p`` with ``EXAMPLE_EVIDENCE``. Refused unless ``p.line_f`` is
    the line it was measured at: at another line its gallons are not
    the ones a tank delivers before crossing it."""
    if p.line_f != EXAMPLE_EVIDENCE_LINE_F:
        raise ValueError(
            f"EXAMPLE_EVIDENCE was measured at {EXAMPLE_EVIDENCE_LINE_F} °F,"
            f" not line_f={p.line_f}"
        )
    return replace(p, evidence=EXAMPLE_EVIDENCE)


# ── Along a simulation ──────────────────────────────────────────────


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


def _interval_at(points: Sequence[PathPoint], at: datetime) -> PathPoint | None:
    """The point ending the simulated interval that holds ``at``: a
    point carries the setpoint in force, and whether the heater ran,
    over the interval up to it. The full-tank floor's, for a window read
    without a book."""
    for p0, p1 in itertools.pairwise(points):
        if p0.at <= at <= p1.at:
            return p1
    return None


@dataclass(frozen=True)
class Depletion:
    """The delivery temperature over a span, judged with the dip
    tolerance."""

    #: The lowest delivery over the span, °F.
    min_f: float
    #: The longest stretch below the line, minutes.
    below_min: float
    #: Below the line by more than ``dip_f``, or for longer than
    #: ``dip_min``: the draw ran cold.
    depleted: bool


def depletion(
    points: Sequence[PathPoint],
    a: datetime,
    b: datetime,
    delivery: Sequence[float],
    p: ReadinessParams | None = None,
) -> Depletion:
    """The delivery temperature over ``[a, b]``, judged with the dip
    tolerance (``ReadinessParams.dip_f``, ``dip_min``: the heater's
    transient dip during a draw): depleted when it falls more than
    ``dip_f`` below the line, or stays below it for longer than
    ``dip_min`` minutes. ``delivery`` is its value at each element of
    ``points`` (``delivery_along``). Linear between the path's elements;
    a draw's step is two elements at one instant."""
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
    return Depletion(
        low, minutes, low < threshold_f - p.dip_f or minutes > p.dip_min
    )


def delivery_along(
    points: Sequence[PathPoint],
    draws: Sequence[Draw],
    booked: BookedPath | None = None,
    p: ReadinessParams | None = None,
    ep: BookParams | None = None,
) -> list[float]:
    """The delivery temperature at each element of the path: the booked
    state's (``delivery_temp_f``), or without one the upper zone on the
    same delivered line, a lag behind it, counted in the walk's
    ``draws`` (``zone_delivery_f``)."""
    p = p or ReadinessParams()
    if booked is None:
        return _zone_delivery(points, draws, p)
    return [
        delivery_temp_f(b, pt.upper_f, p, ep, lower_f=pt.lower_f)
        for pt, b in zip(points, booked.states, strict=True)
    ]


def _zone_delivery(
    points: Sequence[PathPoint],
    draws: Sequence[Draw],
    p: ReadinessParams,
) -> list[float]:
    """``zone_delivery_f`` along the path: the gallons delivered since
    the zone last crossed below the line, a draw at an instant that has
    two elements counted after the first (its step). A zone already
    below the line at the start has no crossing to count from: nothing
    says how far past it the tank is, so it gets no lag, as the
    evidence answers 0 there."""
    ordered = sorted(draws)
    at = [d for d, _ in ordered]
    gal = list(itertools.accumulate(g for _, g in ordered))

    def drawn(i: int) -> float:
        t = points[i].at
        before = i + 1 < len(points) and points[i + 1].at == t
        k = (bisect_left if before else bisect_right)(at, t)
        return gal[k - 1] if k else 0.0

    out: list[float] = []
    since: float | None = None
    above = bool(points) and points[0].upper_f >= p.line_f
    for i, pt in enumerate(points):
        if pt.upper_f >= p.line_f:
            since, above = None, True
        elif since is None and above:
            since, above = drawn(i), False
        out.append(
            zone_delivery_f(
                pt.upper_f, None if since is None else drawn(i) - since, p
            )
        )
    return out


@dataclass(frozen=True)
class DrawWindowResult:
    """A draw window as the simulation found it: the tank at its onset,
    the deliverable gallons and the delivery there, and the delivery
    over the window, judged with the dip tolerance."""

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
    #: ``deliverable_gal`` less the expected gallons, and less an aged
    #: book's error band in gallons; None without an expectation.
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


def draw_windows(
    sim: Simulation,
    windows: Sequence[tuple[datetime, datetime, float | None]],
    delivery: Sequence[float],
    *,
    booked: BookedPath | None = None,
    band_btu: float = 0.0,
    p: ReadinessParams | None = None,
    ep: BookParams | None = None,
    forecast: Sequence[tuple[float | None, datetime | None]] = (),
) -> list[DrawWindowResult]:
    """One per ``(start, end, expected_gal)`` window; ``forecast`` gives
    each, by index, the draws a forecast expects in it and the end of its
    long draws in the worst case. ``band_btu`` is
    taken off ``margin_gal``, in gallons at the window's tank: an aged
    book's error band. With the booked state walked along the path, the
    tank at the onset, its ``deliverable_gal`` and the delivery judged
    over the window all read that state; without it, the zones and the
    evidence."""
    p = p or ReadinessParams()
    ep = ep or BookParams()
    out: list[DrawWindowResult] = []
    for k, (start, end, expected) in enumerate(windows):
        count, draws_until = forecast[k] if k < len(forecast) else (None, None)
        # A window already open at the start is read at the start.
        opened = max(start, sim.points[0].at)
        state = _state_before(sim.points, opened)
        if state is None:
            continue
        upper, lower = state
        judged = depletion(
            sim.points, opened, min(end, sim.points[-1].at), delivery, p
        )
        band_gal = 0.0
        if booked is None:
            there_now = _interval_at(sim.points, opened)
            gal = deliverable(
                upper,
                lower,
                p,
                ep=ep,
                setpoint_f=None if there_now is None else there_now.setpoint_f,
                heating=there_now is not None and there_now.heating,
            ).gal
            at_onset = _at_onset(sim.points, delivery, opened, upper)
        else:
            there = booked.before(opened)
            gal = booked_deliverable(there, upper, lower, p, ep).gal
            at_onset = delivery_temp_f(there, upper, p, ep, lower_f=lower)
            per_gal = WATER_BTU_PER_GAL_F * max(
                1.0, tank_delivery_f(upper, ep) - there.inlet_f
            )
            band_gal = band_btu / per_gal
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
                delivery_f=at_onset,
                deliverable_gal=gal,
                margin_gal=(
                    None if expected is None else gal - band_gal - expected
                ),
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
