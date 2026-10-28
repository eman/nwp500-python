"""The heat book: the tank's heat by bookkeeping, and the zones it
leaves through a draw.

Two probes cannot say how much hot water is left once the hot/cold
boundary sits between them, after a bath say. They can say it when the
tank is **full**, both probes within ``BookParams.uniform_band_f``,
with the heat pump mixing the tank as it heats: the tank's heat above
a 70 °F reference is ``8.34 · V · (T_mean − 70)``. So the book anchors
at the end of a recovery with nothing drawn since, and at any step a
recovery's compressor runs with the probes within the band and nothing
drawn or circulated in it, once it has run ``anchor_run_min`` since a
draw after the last anchor. A quiet moment after a draw does not anchor:
the lower probe falls at once, but in a mixed tank by only about a
third of a small draw's heat, and a draw under about 3 gal leaves the
probes within the band. An anchor there would credit most of the draw
back; on the record it would have over-credited by 0.35-3.9 gal. The
draw stays booked until the compressor has run, and the hold is for
the same reason. An
element run does not anchor either: the upper element heats only the
top, and the lower leaves the water below it unheated.

From the anchor the heat is booked: out by each draw through the mixing
valve and by standby, in from the compressor and the elements. The
book's terms are its own (``BookParams``), fitted on the re-anchors of
one NWP500-65's metered record, where the tank became full again and its
booked heat could be checked against the probes: fitted February-June,
scored July-September, mean absolute error 1,987 BTU (about 5 gal)
against 3,761 with textbook constants. The book's error is flat to 18 h
after an anchor and doubles beyond.

**The empty point** (``BookParams.empty_btu``) is the booked heat left
when the upper probe crossed 105 °F in four drawdowns whose anchor was
within 12 h, 14,219-19,590 BTU, median 16,169. Deliverable volume is the
heat above it over the heat a delivered gallon takes. The point is
booked heat, so it is in its debit's frame: those drawdowns were booked
as delivered gallons, and a flow that counts tank water debits more, so
its empty point is lower and is refit on its own record.

**All the booked heat is drawable.** The compressor's heat and the
elements' count in full, wherever in the tank they land. On the
record's drawdowns that took the upper probe below the line, four usable
from February to October, the deliverable answer at each drawdown's
start read within 3.8 gal on average of the gallons delivered to the
crossing, net of the heat added during it, the lag included. Holding
back the heat that landed in a draw's cold water, as the book once did,
under-read the two of them where it held any back (2026-03-31, after a
bath and a heat-pump recovery, and 04-14, after a six-minute upper
element run over a cold bottom) by 9.3 gal on average.

**Its walk along a simulation** (``walk_booked``).
The book's start is the caller's: from their own record, or
``full_tank_book`` when they know the tank is full: quiet since a
recovery ended, or the compressor running with the probes within the
band and nothing drawn. The library never judges a quiet tank full
from the probes, which read full over a small draw. From the start the
walk moves the book through what the simulation did: the draws at
their instants, the compressor and the elements while they run, and
standby. It re-anchors on a full tank at the end of a recovery the
heater ended itself (its target, or the TOU cap), or quiet after one
with the zones within the band, or with the zones within the band as
the compressor runs alone, past the hold and nothing drawn at that
instant.

The simulator reads the walk for what a path delivers
(``delivery.delivery_along``) and its draw windows; the tank's own
probes through a draw are the layered tank's (``physics.stratified``).
"""

from __future__ import annotations

import itertools
import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from statistics import median
from typing import Protocol

from nwp500.sim.engine import Draw, HeatingInterval, PathPoint
from nwp500.sim.history import FlowVolume, Step, house_gpm
from nwp500.sim.params import BookParams, CirculationParams
from nwp500.sim.units import WATER_BTU_PER_GAL_F

#: BTU per Wh, at the rounding the book was fitted with.
BTU_PER_WH = 3.412


def delivery_f(upper_f: float, p: BookParams | None = None) -> float:
    """What the mixing valve delivers (``physics.draw.delivery_temp_f``),
    capped at the tank: below it the valve passes tank water through."""
    p = p or BookParams()
    return min(upper_f, p.delivery_intercept_f + p.delivery_slope * upper_f)


def hp_btu_per_h(ambient_f: float, p: BookParams) -> float:
    """Compressor heat into the tank, by the air it draws from."""
    return p.hp_btu_per_h + p.hp_btu_per_h_per_f * (ambient_f - 65.0)


def draw_btu(
    gal: float, upper_f: float, inlet_f: float, p: BookParams | None = None
) -> float:
    """Heat a draw of ``gal`` delivered gallons takes through the valve."""
    return (
        gal * WATER_BTU_PER_GAL_F * max(0.0, delivery_f(upper_f, p) - inlet_f)
    )


def draw_out(
    gal: float,
    upper_f: float,
    inlet_f: float,
    p: BookParams | None = None,
    volume: FlowVolume = "delivered",
) -> float:
    """The heat a draw of ``gal`` gallons at ``upper_f`` takes, BTU.
    Delivered gallons take the valve's heat (``draw_btu``); tank gallons
    are tank water, each at the upper zone."""
    if volume == "tank":
        return gal * WATER_BTU_PER_GAL_F * max(0.0, upper_f - inlet_f)
    return draw_btu(gal, upper_f, inlet_f, p)


def compressor_btu(hours: float, ambient_f: float, p: BookParams) -> float:
    return hp_btu_per_h(ambient_f, p) * hours


def element_btu(hours: float, p: BookParams) -> float:
    return p.element_w * BTU_PER_WH * hours


def standby_btu(
    hours: float,
    upper_f: float,
    lower_f: float,
    ambient_f: float,
    p: BookParams,
) -> float:
    mean = (upper_f + lower_f) / 2.0
    return p.ua_btu_per_h_f * max(0.0, mean - ambient_f) * hours


def is_full(upper_f: float, lower_f: float, p: BookParams) -> bool:
    """Both probes within ``uniform_band_f``: with the heater just
    finished and nothing moving since, or the compressor running with
    nothing moving, the book's anchor."""
    return abs(upper_f - lower_f) <= p.uniform_band_f


def circulated_btu(
    gal: float,
    circulation: CirculationParams | None,
    *,
    before_gal: float = 0.0,
    upper_f: float = 0.0,
    ambient_f: float = 0.0,
) -> float:
    """Heat circulation takes for the ``gal`` it circulates, the run
    having circulated ``before_gal`` already. With
    ``CirculationParams.book_circuit_gal``, the gallons up to that volume
    from the run's start, each at the tank's upper probe less the air:
    the circuit's water cooled to the air since the last run, and once
    the circuit is hot again it takes nothing more. Without it,
    ``loss_btu_per_gal`` per gallon."""
    if circulation is None:
        return 0.0
    circuit = circulation.book_circuit_gal
    if circuit is None:
        return circulation.loss_btu_per_gal * gal
    priced = min(before_gal + gal, circuit) - min(before_gal, circuit)
    return (
        max(0.0, priced) * WATER_BTU_PER_GAL_F * max(0.0, upper_f - ambient_f)
    )


def step_heat_btu(
    s: Step, p: BookParams, circulation: CirculationParams | None = None
) -> float:
    """Heat into the tank over one step, BTU; negative when it loses."""
    h = s.seconds / 3600.0
    heat = 0.0
    if s.compressor_on:
        heat += compressor_btu(h, s.ambient_f, p)
    if s.element_on:
        heat += element_btu(h, p)
    house = house_gpm(s, circulation)
    if house > p.draw_gpm:
        gal = house * s.seconds / 60.0
        heat -= draw_out(gal, s.upper_f, s.inlet_f, p, s.flow_volume)
    if s.circulating:
        heat -= circulated_btu(
            s.circulation_gpm * s.seconds / 60.0,
            circulation,
            before_gal=s.run_gal_before,
            upper_f=s.upper_f,
            ambient_f=s.ambient_f,
        )
    heat -= standby_btu(h, s.upper_f, s.lower_f, s.ambient_f, p)
    return heat


def mains_f(
    steps: Sequence[Step],
    p: BookParams,
    circulation: CirculationParams | None = None,
) -> float | None:
    """The mains from the long draws in ``steps``, as
    ``cold_supply.plateau_t_cold`` reads it: each household draw of
    ``settle_s + tail_s`` or more with circulation off throughout gives
    the median measured inlet over its last ``tail_s`` (none before
    ``settle_s``), kept within ``plausible_f``; the answer is the median
    of those that ended within ``window_s`` of the last step. None with
    no such draw. The probe's readings at rest are not the mains: the
    pipe stagnates and tracks the air."""
    from nwp500.sim.cold_supply import ColdSupplyParams

    cp = ColdSupplyParams()
    plateaus: list[tuple[float, float]] = []
    run: list[tuple[float, Step]] = []
    # Circulation at any point of a draw rules out the whole draw.
    tainted = False
    t = 0.0

    def close() -> None:
        if not run:
            return
        onset, end = run[0][0] - run[0][1].seconds, run[-1][0]
        if end - onset < cp.settle_s + cp.tail_s:
            return
        tail_from = max(onset + cp.settle_s, end - cp.tail_s)
        readings = [
            s.inlet_f for at, s in run if at > tail_from and s.inlet_measured
        ]
        if len(readings) < cp.min_readings:
            return
        plateau = float(median(readings))
        if cp.plausible_f[0] <= plateau <= cp.plausible_f[1]:
            plateaus.append((end, plateau))

    for s in steps:
        t += s.seconds
        if house_gpm(s, circulation) > p.draw_gpm:
            tainted = tainted or s.circulating
            run.append((t, s))
            continue
        if not tainted:
            close()
        run, tainted = [], False
    if not tainted:
        close()
    recent = [v for end, v in plateaus if end >= t - cp.window_s]
    return float(median(recent)) if recent else None


def inlet_now_f(
    steps: Sequence[Step],
    p: BookParams,
    circulation: CirculationParams | None = None,
) -> float:
    """The inlet a draw would meet, for the conversion from heat to
    gallons: the mains from the long draws in ``steps`` (``mains_f``),
    else ``inlet_default_f``. Not the probe's readings at rest: over
    2026-09-21 to 10-24 at one installation, a 3 h median of them sat
    a standard deviation of 4.8 °F from the long draws' mains, up to
    14 °F, and moved the gallons by up to 41 %."""
    found = mains_f(steps, p, circulation)
    return p.inlet_default_f if found is None else found


def compressing(s: Step) -> bool:
    """The compressor running alone in ``s``: a step whose full tank
    anchors the book while it heats."""
    return s.compressor_on and not s.element_on


def anchor_held(run_s: float | None, p: BookParams) -> bool:
    """The compressor's run since the last draw past ``anchor_run_min``,
    or no draw since the last anchor (``run_s`` None)."""
    return run_s is None or run_s >= p.anchor_run_min * 60.0


def _busy(
    s: Step, p: BookParams, circulation: CirculationParams | None
) -> tuple[bool, bool]:
    """(heating, disturbed): heat going in; water moving or
    circulating."""
    heating = s.compressor_on or s.element_on
    disturbed = house_gpm(s, circulation) > p.draw_gpm or s.circulating
    return heating, disturbed


def book_steps(
    steps: Sequence[Step],
    p: BookParams | None = None,
    circulation: CirculationParams | None = None,
) -> Booked | None:
    """The heat now, booked from a recorded history's last anchor: a
    full tank (``is_full``) at a step the compressor runs alone with
    nothing drawn or circulated in it, once it has run ``anchor_run_min``
    since the last draw (or the history's start, before an anchor), or
    uniform and quiet after a
    recovery ends with no draw and no circulation since. A recovery
    that ends while water or circulation moves anchors at its end,
    uniform there, and books the movement from that step on (its probes
    read the step's start); the quiet steps after such a draw do not
    anchor (the probes then show only part of the draw). None with no
    anchor within ``history_h``; older than ``max_anchor_age_h`` the
    book is ``aged``."""
    p = p or BookParams()
    anchor = None
    book_from = 0
    clean = False
    was_heating = False
    # The compressor's run since the last draw, s (``anchor_run_min``),
    # from the history's start until an anchor; None with no draw since
    # the last anchor.
    run_s: float | None = 0.0
    for i, st in enumerate(steps):
        heating, disturbed = _busy(st, p, circulation)
        full = is_full(st.upper_f, st.lower_f, p)
        if house_gpm(st, circulation) > p.draw_gpm:
            run_s = 0.0
        elif st.compressor_on and run_s is not None:
            run_s += st.seconds
        if heating:
            clean = False
        elif was_heating:
            clean = True
            if disturbed and full:
                anchor, book_from = i, i
        if disturbed:
            clean = False
        was_heating = heating
        if clean and not heating and full:
            anchor, book_from = i, i + 1
        if compressing(st) and anchor_held(run_s, p) and not disturbed and full:
            anchor, book_from = i, i + 1
        if anchor == i and not disturbed:
            run_s = None
    if anchor is None:
        return None
    age_h = sum(s.seconds for s in steps[anchor + 1 :]) / 3600.0
    if age_h > p.history_h:
        return None
    a = steps[anchor]
    b = full_tank(a.upper_f, a.lower_f, p.inlet_default_f, p)
    for s in steps[book_from:]:
        b = b.step(s, p, circulation)
    mains = mains_f(steps, p, circulation)
    return replace(
        b,
        anchor_age_h=age_h,
        inlet_f=p.inlet_default_f if mains is None else mains,
        inlet_measured_share=0.0 if mains is None else 1.0,
        hold_s=run_s,
    )


def full_tank(
    upper_f: float, lower_f: float, inlet_f: float, p: BookParams
) -> Booked:
    """The book's anchor: a full tank's heat is what its probes say,
    ``8.34 · V · (T_mean − reference)``."""
    mean = (upper_f + lower_f) / 2.0
    return Booked(
        heat_btu=WATER_BTU_PER_GAL_F * p.tank_gal * (mean - p.reference_f),
        anchor_age_h=0.0,
        inlet_f=inlet_f,
    )


@dataclass(frozen=True)
class Booked:
    """The tank's heat above the reference now, and what it rests on:
    the state readiness answers from and a simulation walks. One set of
    operations moves it, each the book's own term."""

    heat_btu: float
    anchor_age_h: float
    inlet_f: float
    #: For a book built from a record: 1 when ``inlet_f`` is the mains
    #: read from its long draws (``mains_f``), 0 when it is the default.
    inlet_measured_share: float = 0.0
    #: The compressor's run since a draw booked after the anchor, s,
    #: which holds its anchor (``BookParams.anchor_run_min``); None with
    #: no draw since the anchor.
    hold_s: float | None = None

    def aged(self, p: BookParams | None = None) -> bool:
        """Booked from an anchor older than ``max_anchor_age_h``."""
        p = p or BookParams()
        return self.anchor_age_h > p.max_anchor_age_h

    def error_band_btu(self, p: BookParams | None = None) -> float:
        """The book's 90th-percentile error at its anchor's age."""
        p = p or BookParams()
        return p.aged_error_btu if self.aged(p) else p.error_btu

    def drawable_btu(self, p: BookParams | None = None) -> float:
        """Heat a draw can take before the upper probe falls below the
        depletion line; negative once a draw has taken more."""
        p = p or BookParams()
        return self.heat_btu - p.empty_btu

    def drawn(
        self,
        gal: float,
        upper_f: float,
        p: BookParams | None = None,
        volume: FlowVolume = "delivered",
    ) -> Booked:
        """After ``gal`` gallons at ``upper_f``, delivered or of tank
        water: their heat out (``draw_out``)."""
        p = p or BookParams()
        if gal <= 0.0:
            return self
        out = draw_out(gal, upper_f, self.inlet_f, p, volume)
        return replace(self, heat_btu=self.heat_btu - out, hold_s=0.0)

    def heated(self, btu: float) -> Booked:
        """Heat in, from the compressor or an element: all of it
        drawable."""
        return replace(self, heat_btu=self.heat_btu + btu)

    def ran(self, seconds: float) -> Booked:
        """After the compressor has run ``seconds``: its hold runs."""
        if self.hold_s is None:
            return self
        return replace(self, hold_s=self.hold_s + seconds)

    def lost(self, btu: float) -> Booked:
        """Standby loss, out of the drawable heat."""
        return replace(self, heat_btu=self.heat_btu - btu)

    def step(
        self,
        s: Step,
        p: BookParams | None = None,
        circulation: CirculationParams | None = None,
    ) -> Booked:
        """One recorded step: ``step_heat_btu``'s terms."""
        p = p or BookParams()
        h = s.seconds / 3600.0
        b = replace(self, inlet_f=s.inlet_f)
        house = house_gpm(s, circulation)
        if house > p.draw_gpm:
            b = b.drawn(house * s.seconds / 60.0, s.upper_f, p, s.flow_volume)
        elif s.compressor_on:
            b = b.ran(s.seconds)
        heat = compressor_btu(h, s.ambient_f, p) if s.compressor_on else 0.0
        if s.element_on:
            heat += element_btu(h, p)
        b = b.heated(heat)
        lost = standby_btu(h, s.upper_f, s.lower_f, s.ambient_f, p)
        if s.circulating:
            lost += circulated_btu(
                s.circulation_gpm * s.seconds / 60.0,
                circulation,
                before_gal=s.run_gal_before,
                upper_f=s.upper_f,
                ambient_f=s.ambient_f,
            )
        return replace(b.lost(lost), inlet_f=self.inlet_f)

    def deliverable_gal(
        self, upper_f: float, p: BookParams | None = None
    ) -> float:
        """Delivered gallons the drawable heat makes at ``upper_f``."""
        return deliverable_from_heat(self.heat_btu, upper_f, self.inlet_f, p)


def deliverable_from_heat(
    heat_btu: float,
    upper_f: float,
    inlet_f: float,
    p: BookParams | None = None,
) -> float:
    """Delivered gallons the heat above the empty point will make, each
    taking ``8.34 · (T_delivered − T_inlet)``. Not capped here."""
    p = p or BookParams()
    per_gal = WATER_BTU_PER_GAL_F * (delivery_f(upper_f, p) - inlet_f)
    if per_gal <= 0 or not math.isfinite(heat_btu):
        return 0.0
    return max(0.0, (heat_btu - p.empty_btu) / per_gal)


# ── The line ─────────────────────────────────────────────────────────

#: The line, delivered water below which is not hot, °F: the default of
#: ``ReadinessParams.line_f``, which a caller passes as ``line_f``.
DEPLETION_THRESHOLD_F = 105.0


def tank_max_btu(
    upper_f: float, lower_f: float, ep: BookParams | None = None
) -> float:
    """The most heat the tank can hold at these probes: all of it at the
    warmer one, above the book's reference. The book is read no
    higher: its compressor term runs warm in warm air, and on
    2026-09-28 it carried an anchor through a bath and a TOU-capped
    recovery to 39,027 BTU over probes of 140.18/138.2 °F, 2,036 above
    this."""
    ep = ep or BookParams()
    top = max(upper_f, lower_f)
    return full_tank(top, top, ep.inlet_default_f, ep).heat_btu


def probe_line_gal(
    heat_btu: float,
    upper_f: float,
    lower_f: float,
    inlet_f: float,
    ep: BookParams | None = None,
    *,
    empty_btu: float | None = None,
) -> float:
    """Delivered gallons the booked heat gives before the upper probe
    crosses the line: negative once a draw has gone past it, by the
    gallons it went. The heat is read no higher than ``tank_max_btu``;
    ``-inf`` when a gallon would take no heat (a tank at the inlet).
    ``empty_btu`` is the book's empty point unless given."""
    ep = ep or BookParams()
    per_gal = WATER_BTU_PER_GAL_F * (delivery_f(upper_f, ep) - inlet_f)
    if per_gal <= 0.0 or not math.isfinite(heat_btu):
        return -math.inf
    heat = min(heat_btu, tank_max_btu(upper_f, lower_f, ep))
    empty = ep.empty_btu if empty_btu is None else empty_btu
    return (heat - empty) / per_gal


# ── Its walk along a simulation ─────────────────────────────────────

Run = tuple[datetime, datetime]


class SpanLoss(Protocol):
    """A loss of heat the book does not model, a client's own: water the
    installation circulates through its own plumbing, say. The walk
    cuts its spans at ``edges``, charges ``loss`` over each span, and
    treats a disturbed span as not quiet, so the tank does not
    re-anchor across it; the engine's bound on what the walk can charge
    (``loss_ceiling_btu``) adds ``bound``. None of it is called without
    one (``walk_booked``'s ``extra``)."""

    def edges(self, start: datetime, end: datetime) -> Iterable[datetime]:
        """Instants within ``[start, end]`` where the loss starts or
        stops, which the walk must stop at."""
        ...

    def loss(self, start: datetime, end: datetime) -> tuple[float, bool]:
        """Heat lost over ``[start, end)``, BTU, and whether the tank is
        disturbed then (not quiet)."""
        ...

    def bound(self, start: datetime, end: datetime) -> float:
        """The most ``loss`` can charge over ``[start, end]``, BTU."""
        ...


@dataclass(frozen=True)
class BookedPath:
    """The booked state at each element of a simulation's path, in its
    order, and at each instant the walk stopped at."""

    #: One per ``Simulation.points`` element. Of two elements at one
    #: instant (a draw's step), the first is before it, the second after.
    states: list[Booked]
    instants: list[datetime]
    #: At each of ``instants``, before anything drawn there.
    befores: list[Booked]

    def before(self, at: datetime) -> Booked:
        """The state at ``at``, before anything drawn at that instant.
        The walk stops at every path element, so a draw window's onset
        (a mark) is one of its instants; between two, the earlier."""
        i = bisect_right(self.instants, at) - 1
        return self.befores[max(0, i)]


def walk_booked(
    start: Booked,
    points: Sequence[PathPoint],
    heating: Sequence[HeatingInterval],
    draws: Sequence[Draw],
    ambient_at: Callable[[datetime], float],
    p: BookParams | None = None,
    *,
    withheld: Sequence[Run] = (),
    extra: SpanLoss | None = None,
) -> BookedPath:
    """``start`` walked along ``points`` with the book's own terms.

    Draws are taken at their instants, at the simulated upper zone then
    (before the step). Between instants, the compressor's heat and the
    elements' go in, and standby (at the simulated zones' mean, to the
    ambient) comes out of the drawable heat.

    ``withheld`` are the windows over which a recovery is credited no
    heat (the engine's ``withheld_windows``): the compressor or
    element runs there and adds nothing to the book, as it adds nothing
    to the zones. It is still running, so the tank is not quiet there.

    ``extra`` is a client's own loss (``SpanLoss``): charged over each
    span, and a span it disturbs is not quiet.
    """
    p = p or BookParams()
    t0, t1 = points[0].at, points[-1].at
    times = [pt.at for pt in points]

    def zones(at: datetime) -> tuple[float, float]:
        """The path at ``at``: the first element there (before a draw's
        step), linear between elements."""
        i = bisect_left(times, at)
        if i < len(times) and times[i] == at:
            return points[i].upper_f, points[i].lower_f
        if i == 0:
            return points[0].upper_f, points[0].lower_f
        if i >= len(times):
            return points[-1].upper_f, points[-1].lower_f
        a, b = points[i - 1], points[i]
        f = (at - a.at) / (b.at - a.at)
        return (
            a.upper_f + (b.upper_f - a.upper_f) * f,
            a.lower_f + (b.lower_f - a.lower_f) * f,
        )

    cuts = {*times}
    cuts.update(at for at, _ in draws if t0 <= at <= t1)
    for h in heating:
        cuts.update(x for x in (h.start.at, h.end) if t0 < x < t1)
    for a, b in withheld:
        cuts.update(x for x in (a, b) if t0 < x < t1)
    if extra is not None:
        cuts.update(x for x in extra.edges(t0, t1) if t0 < x < t1)
    instants = sorted(cuts)
    by_instant: dict[datetime, float] = {}
    for at, gal in draws:
        if t0 <= at <= t1:
            by_instant[at] = by_instant.get(at, 0.0) + gal

    def running(a: datetime, b: datetime) -> bool:
        """Whether a heating runs over ``[a, b)``, credited or not."""
        mid = a + (b - a) / 2
        return any(h.start.at <= mid < h.end for h in heating)

    def compressor_on(a: datetime, b: datetime) -> tuple[bool, bool]:
        """Whether the compressor runs over ``[a, b)``, and whether
        alone."""
        mid = a + (b - a) / 2
        on = [
            h.source == "compressor"
            for h in heating
            if h.start.at <= mid < h.end
        ]
        return any(on), bool(on) and all(on)

    def heat_in(a: datetime, b: datetime) -> float:
        """Heat in over ``[a, b)``; none inside a withheld window."""
        mid = a + (b - a) / 2
        hours = (b - a).total_seconds() / 3600.0
        if any(w0 <= mid < w1 for w0, w1 in withheld):
            return 0.0
        heat = 0.0
        for h in heating:
            if not h.start.at <= mid < h.end:
                continue
            if h.source == "compressor":
                heat += compressor_btu(hours, ambient_at(mid), p)
            else:
                heat += element_btu(hours, p)
        return heat

    spans = list(itertools.pairwise(instants))
    inflow = [heat_in(a, b) for a, b in spans]
    # The heater running, which the anchor rule reads as not quiet,
    # whether its heat is credited or withheld.
    heats = [
        x > 0.0 or (bool(withheld) and running(a, b))
        for x, (a, b) in zip(inflow, spans, strict=True)
    ]
    # A client's own loss over each span, and whether it disturbs it.
    extras = [
        extra.loss(a, b) if extra is not None else (0.0, False)
        for a, b in spans
    ]
    # The compressor running, credited: alone and undisturbed, a full
    # tank at the span's end anchors as it heats. In a withheld window
    # the draws come first, so it neither anchors nor runs the hold.
    compressor = [
        compressor_on(a, b) if x > 0.0 else (False, False)
        for (a, b), x in zip(spans, inflow, strict=True)
    ]
    alone = [c[1] and not x[1] for c, x in zip(compressor, extras, strict=True)]

    state = start
    before: list[Booked] = []
    after: dict[datetime, Booked] = {}
    # The book's anchor rule on the simulated
    # tank: quiet since a heating ended, and full. A recovery the heater
    # stopped itself, at its target or the TOU cap, is full by the
    # heater's own rule, whatever gap the zones show then; any other
    # end, or any quiet instant after one, is full when the zones are
    # within the book's band. So is an instant the compressor has run
    # alone up to, past the book's hold (``Booked.hold_s``), nothing
    # drawn there.
    clean = False
    for k, at in enumerate(instants):
        # Heat in, and the compressor alone, over the span ending here.
        prev_heat = k > 0 and heats[k - 1]
        prev_alone = k > 0 and alone[k - 1]
        busy_next = k < len(spans) and (heats[k] or extras[k][1])
        disturbed = by_instant.get(at, 0.0) > 0.0 or busy_next
        if prev_heat and not (k < len(spans) and heats[k]):
            clean = True
            if not disturbed and any(
                h.end == at and _stopped_full(h) for h in heating
            ):
                state = _anchored(state, *zones(at), p)
                clean = False
        if clean and not disturbed and is_full(*zones(at), p):
            state = _anchored(state, *zones(at), p)
        gal = by_instant.get(at, 0.0)
        if (
            prev_alone
            and gal == 0.0
            and anchor_held(state.hold_s, p)
            and is_full(*zones(at), p)
        ):
            state = _anchored(state, *zones(at), p)
        before.append(state)
        if gal > 0.0:
            state = state.drawn(gal, zones(at)[0], p)
            clean = False
        after[at] = state
        if k == len(spans):
            break
        nxt = instants[k + 1]
        mid = at + (nxt - at) / 2
        hours = (nxt - at).total_seconds() / 3600.0
        upper, lower = zones(mid)
        lost = standby_btu(hours, upper, lower, ambient_at(mid), p)
        lost += extras[k][0]
        if extras[k][1]:
            clean = False
        if heats[k]:
            clean = False
        if compressor[k][0]:
            state = state.ran((nxt - at).total_seconds())
        state = state.heated(inflow[k]).lost(lost)

    index = {at: i for i, at in enumerate(instants)}
    states = []
    for i, pt in enumerate(points):
        repeated = i + 1 < len(points) and points[i + 1].at == pt.at
        states.append(before[index[pt.at]] if repeated else after[pt.at])
    return BookedPath(states, instants, before)


#: The coldest ambient a standby bound assumes, °F.
_COLDEST_AMBIENT_F = -20.0


def loss_ceiling_btu(
    a: datetime,
    b: datetime,
    upper_f: float,
    p: BookParams | None = None,
    *,
    extra: SpanLoss | None = None,
) -> float:
    """The most the walk can charge over ``[a, b]`` with no zone hotter
    than ``upper_f``: standby from it to the coldest ambient
    (``walk_booked``'s term, bounded), and a client's own loss's bound."""
    p = p or BookParams()
    hours = max(0.0, (b - a).total_seconds() / 3600.0)
    standby = p.ua_btu_per_h_f * max(0.0, upper_f - _COLDEST_AMBIENT_F) * hours
    return standby + (extra.bound(a, b) if extra is not None else 0.0)


def _stopped_full(h: HeatingInterval) -> bool:
    """A heating the heater ended itself with the lower zone at its
    target (the compressor's, or the lower element's in Electric) or at
    the TOU cap: the tank is full by the heater's own rule. The upper
    element's target is the upper zone's, and a write, a mode or the
    horizon end a recovery the heater had not finished."""
    if h.stop not in ("target", "cap"):
        return False
    return h.source == "compressor" or h.zone == "lower"


def _anchored(
    state: Booked, upper_f: float, lower_f: float, p: BookParams
) -> Booked:
    return replace(
        full_tank(upper_f, lower_f, state.inlet_f, p),
        inlet_measured_share=state.inlet_measured_share,
    )


# ── A full tank ──────────────────────────────────────────────────────


def full_tank_book(
    upper_f: float,
    lower_f: float,
    p: BookParams | None = None,
    *,
    inlet_f: float | None = None,
) -> Booked:
    """A book anchored on a full tank at these zones (``full_tank``),
    for a caller who knows the tank is full: quiet since a heating
    ended (a recovery finished and nothing drawn since), or the
    compressor running with the zones within ``uniform_band_f`` and
    nothing drawn. The library does not judge a quiet tank full from the
    probes, which read full over a small draw. ``inlet_f`` defaults to
    ``BookParams.inlet_default_f``, the frame ``empty_btu`` was fitted
    in."""
    p = p or BookParams()
    return full_tank(
        upper_f,
        lower_f,
        p.inlet_default_f if inlet_f is None else inlet_f,
        p,
    )
