"""The heat book: the tank's heat by bookkeeping, and the zones it
leaves through a draw.

Two probes cannot say how much hot water is left once the hot/cold
boundary sits between them, after a bath say. They can say it when the
tank is **full**: at the end of a recovery, both probes within
``BookParams.uniform_band_f`` and nothing drawn since, the tank's heat
above a 70 °F reference is ``8.34 · V · (T_mean − 70)``. Only such a
state anchors the book. A quiet moment after a draw does not: the
draw's cold water sits below the lower probe, which reads hot, and an
anchor there would forget the draw.

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
heat above it over the heat a delivered gallon takes.

**Where the heat lands.** The heat pump heats from the bottom up, so
heating cannot build a hot top over a cold bottom: only a draw makes a
cold bottom. Its cold water is booked as a **cold region**, the tank
gallons the draws displaced since the tank was last full, at their mixed
temperature. Compressor heat, and the lower element's, lands there:
booked, but **withheld**, because water below the line cannot be drawn
above it, until the region passes ``cold_release_f`` and rejoins the hot
water. The upper element's heat lands in a thin top layer, so it is
drawable, but only its own heat: a hot top says nothing about the volume
under it. On 2026-03-31 a bath left the lower probe at 82 °F and the
heat pump then took it to 98 °F with the upper near 137; on 04-14 a
six-minute upper-element run lifted the upper probe 126 -> 141 °F over a
lower at 88. Counted as drawable, both over-promised; withheld, both are
caught. The lower probe can release the region too, once it has read
below ``cold_release_f`` and reads at or above it again with nothing
drawn (``Booked.observed``).

**Its walk along a simulation** (``walk_booked``, ``BookedHeatLedger``).
The book's start is the caller's: from their own record, or
``full_tank_book`` when they know the tank has been quiet since a
recovery ended. The library never judges that from the probes, which
read full over hidden draw water. From the start the walk moves the book
through what the simulation did: the draws at their instants, the
compressor and the elements while they run, and standby. It re-anchors
on a full tank at the end of a recovery the heater ended itself (its
target, or the TOU cap), or quiet after one with the zones within the
band. The engine runs this walk at each draw (``BookedHeatLedger``, the
core's ``HeatLedger``), and a draw that spends the booked heat past the
zone's empty point takes the upper zone down.

**The upper zone through a draw** (``zone_after_draw_f``). The
calibrated draw (``sim.decay.draw_step``) moves the upper zone a
fraction of a degree, as the probe moves on an ordinary draw, and as
little when the cold front reaches the probe, where it falls tens of
degrees: through a 54 gal bath it left the zone at 139.6 °F against the
probe's 104. So at each draw the zone is taken no warmer than the line
plus ``fall_f_per_gal`` per delivered gallon the booked heat gives
before ``zone_empty_btu``, and less per gallon past it, no colder than
the lower zone. ``zone_empty_btu`` is the empty point refit to centre
the five recorded crossings; the served point calls them early by
design, and a zone taken down there misplaced most draws that came near
it without crossing.

**It falls before that point too** (``zone_mixed_f``). The probe
declines from early in a long draw, the water above the rising front
mixing, and faster the less booked heat is left: over the record's draws
of 15 gal or more, 0.08 °F per delivered gallon with more than 30 gal
left before the zone's point, 0.2 at 20-30, 0.6 at 10-15, 1.3 at 5-10.
So a draw also takes the zone no warmer than where it found it less the
integral of ``zone_mix_f_per_gal · exp(-left / zone_mix_gal)`` over its
gallons; the colder of that and the line stands.

**The lower zone through a draw** (``lower_after_draw_f``). The
calibrated draw takes the lower zone down about a degree per delivered
gallon, wherever the cold water is. The probe does not: it sits about
25 tank gallons up, and reads the cold region only once its front gets
there. Over the record's long draws it reads within a degree of the
upper probe until the region is about 9 gal, then falls through a front
about 32 gal wide to the region's own temperature. So with a book the
lower zone at each draw moves by the share of the front the draw moved
past the probe (``front_share``), in place of the calibrated response.
"""

from __future__ import annotations

import itertools
import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from statistics import median
from typing import Protocol, cast

from nwp500.sim.engine import Draw, HeatingInterval, PathPoint
from nwp500.sim.extensions import (
    AfterDraw,
    DrawsAhead,
    DrawTaken,
    LedgerZones,
    Stand,
    UpperAhead,
)
from nwp500.sim.params import BookParams, CirculationParams
from nwp500.sim.tank_physics import point_at
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
    finished and nothing moving since, the book's anchor."""
    return abs(upper_f - lower_f) <= p.uniform_band_f


#: The air a recorded step stands in when none was recorded, °F.
AMBIENT_DEFAULT_F = 65.0


@dataclass(frozen=True)
class Step:
    """One interval of a recorded history, ``seconds`` long: what the
    book reads of it (``Booked.step``, ``book_steps``)."""

    seconds: float
    upper_f: float
    lower_f: float
    #: The household flow meter's reading, gal/min (0 without a meter:
    #: no draw is booked).
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
    #: The element on is the lower one, whose heat lands at the bottom
    #: as the compressor's does; otherwise the upper, at the top.
    lower_element: bool = False
    #: Circulation's flow over the span ``flow_gpm`` was read over, 0
    #: where it was off: a meter's figure over a trailing window still
    #: holds a run for a while after it stops. None: ``circulation_gpm``
    #: while circulating, else none.
    circulation_in_meter_gpm: float | None = None
    #: Gallons the run had circulated before this step, runs closer
    #: than ``CirculationParams.run_gap_min`` taken as one: what
    #: ``CirculationParams.book_circuit_gal`` caps.
    run_gal_before: float = 0.0
    #: The heater and the flow were known over the step. A step its
    #: caller walked across a gap in the record (held values, standing in
    #: for what nobody saw) anchors nothing, and no anchor is taken after
    #: it until a recovery ends: a draw inside the gap would go unseen.
    heard: bool = True


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
        heat -= draw_btu(house * s.seconds / 60.0, s.upper_f, s.inlet_f, p)
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


def inlet_now_f(steps: Sequence[Step], p: BookParams) -> float:
    """The inlet a draw would meet, for the conversion from heat to
    gallons: the median of the measured readings over the last
    ``inlet_window_s``, not the last one (a probe on the pipe wanders
    with the air at rest, about a 14 % swing in the gallons at a hot
    tank). The last step's value without one measured, and
    ``inlet_default_f`` with no steps."""
    if not steps:
        return p.inlet_default_f
    window: list[float] = []
    elapsed = 0.0
    for s in reversed(steps):
        if s.inlet_measured:
            window.append(s.inlet_f)
        elapsed += s.seconds
        if elapsed >= p.inlet_window_s:
            break
    if not window:
        return steps[-1].inlet_f
    return float(median(window))


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
    full tank (``is_full``), uniform and quiet, after a recovery ends
    with no draw and no circulation since. A recovery that ends while
    water or circulation moves anchors at its end, uniform there, the
    movement booked from its start; the quiet steps after such a draw
    do not anchor (the probes then read the draw's cold water as full),
    nor do a step not ``heard`` and the quiet steps after it. None with
    no anchor within ``history_h``; older than ``max_anchor_age_h`` the
    book is ``aged``."""
    p = p or BookParams()
    anchor = None
    book_from = 0
    clean = False
    was_heating = was_disturbed = False
    moving_since = 0
    for i, st in enumerate(steps):
        heating, disturbed = _busy(st, p, circulation)
        full = is_full(st.upper_f, st.lower_f, p)
        if disturbed and not was_disturbed:
            moving_since = i
        if heating:
            clean = False
        elif was_heating:
            clean = True
            if disturbed and full and st.heard:
                anchor, book_from = i, moving_since
        if disturbed or not st.heard:
            clean = False
        was_heating, was_disturbed = heating, disturbed
        if clean and not heating and full:
            anchor, book_from = i, i + 1
    if anchor is None:
        return None
    age_h = sum(s.seconds for s in steps[anchor + 1 :]) / 3600.0
    if age_h > p.history_h:
        return None
    a = steps[anchor]
    b = full_tank(a.upper_f, a.lower_f, p.inlet_default_f, p)
    # The movement's part before the recovery ended: its hot water left
    # and its cold water lies below the probes, which read the heat that
    # went in meanwhile at the anchor already.
    for s in steps[book_from:anchor]:
        b = b.step(
            replace(s, compressor_on=False, element_on=False), p, circulation
        )
    for s in steps[max(book_from, anchor) :]:
        b = b.step(s, p, circulation)
    since = steps[anchor:]
    share = sum(1 for s in since if s.inlet_measured) / len(since)
    return replace(
        b,
        anchor_age_h=age_h,
        inlet_f=inlet_now_f(since, p),
        inlet_measured_share=share,
    )


def full_tank(
    upper_f: float, lower_f: float, inlet_f: float, p: BookParams
) -> Booked:
    """The book's anchor: a full tank's heat is what its probes say,
    ``8.34 · V · (T_mean − reference)``, with no cold region."""
    mean = (upper_f + lower_f) / 2.0
    return Booked(
        heat_btu=WATER_BTU_PER_GAL_F * p.tank_gal * (mean - p.reference_f),
        anchor_age_h=0.0,
        inlet_f=inlet_f,
        cold_f=p.reference_f,
    )


@dataclass(frozen=True)
class Booked:
    """The tank's heat above the reference now, where it lies, and what
    it rests on: the state readiness answers from and a simulation
    walks. One set of operations moves it, each the book's own term."""

    heat_btu: float
    anchor_age_h: float
    inlet_f: float
    #: Share of the time since the anchor with a measured inlet, for a
    #: book built from a record.
    inlet_measured_share: float = 0.0
    #: The cold region: tank gallons the draws displaced since the tank
    #: was last full, and their temperature (module docstring).
    cold_gal: float = 0.0
    cold_f: float = 70.0
    #: The lower probe has read below ``cold_release_f`` since the region
    #: formed: it has seen the cold water, so it can see it go.
    cold_seen: bool = False
    #: Gaps in the record since the anchor that the book was walked
    #: across, the values held (``Step.heard``): a draw inside one is not
    #: booked.
    bridged: tuple[tuple[datetime, datetime], ...] = ()

    def aged(self, p: BookParams | None = None) -> bool:
        """Booked from an anchor older than ``max_anchor_age_h``."""
        p = p or BookParams()
        return self.anchor_age_h > p.max_anchor_age_h

    def error_band_btu(self, p: BookParams | None = None) -> float:
        """The book's 90th-percentile error at its anchor's age."""
        p = p or BookParams()
        return p.aged_error_btu if self.aged(p) else p.error_btu

    def withheld_btu(self, p: BookParams | None = None) -> float:
        """Booked heat in the cold region, above the reference: not
        drawable while the region is below ``cold_release_f``. Negative
        for a region colder than the reference (a winter inlet): the
        draw charged the book down to that inlet, and this hands back
        the part below the reference, so a draw costs the drawable heat
        only the hot water that left. Never seen: the record's inlet has
        been ~70 °F."""
        p = p or BookParams()
        if self.cold_gal <= 0.0:
            return 0.0
        return (
            WATER_BTU_PER_GAL_F * self.cold_gal * (self.cold_f - p.reference_f)
        )

    def drawable_btu(self, p: BookParams | None = None) -> float:
        """Heat a draw can take before the upper probe falls below the
        depletion line; negative once a draw has taken more."""
        p = p or BookParams()
        return self.heat_btu - self.withheld_btu(p) - p.empty_btu

    def drawn(
        self, gal: float, upper_f: float, p: BookParams | None = None
    ) -> Booked:
        """After ``gal`` delivered gallons at ``upper_f``: the valve's
        heat out, and the tank gallons it took (its hot share) replaced
        by the inlet at the bottom, in the cold region."""
        p = p or BookParams()
        if gal <= 0.0:
            return self
        inlet = self.inlet_f
        hot = (
            (delivery_f(upper_f, p) - inlet) / (upper_f - inlet)
            if upper_f > inlet
            else 1.0
        )
        cold = min(p.tank_gal, self.cold_gal + gal * max(0.0, hot))
        added = cold - self.cold_gal
        cold_f = (
            (self.cold_f * self.cold_gal + inlet * added) / cold
            if cold > 0.0
            else self.cold_f
        )
        return replace(
            self,
            heat_btu=self.heat_btu - draw_btu(gal, upper_f, inlet, p),
            cold_gal=cold,
            cold_f=cold_f,
            # A new region has not been seen yet; a larger one has.
            cold_seen=self.cold_seen and self.cold_gal > 0.0,
        )

    def heated(
        self,
        bottom_btu: float = 0.0,
        top_btu: float = 0.0,
        p: BookParams | None = None,
    ) -> Booked:
        """Heat in: ``bottom_btu`` (the compressor, the lower element)
        into the cold region while there is one, ``top_btu`` (the upper
        element) into the thin top layer. The region rejoins the hot
        water once past ``cold_release_f``."""
        p = p or BookParams()
        cold_gal, cold_f = self.cold_gal, self.cold_f
        seen = self.cold_seen
        if cold_gal > 0.0 and bottom_btu > 0.0:
            cold_f += bottom_btu / (WATER_BTU_PER_GAL_F * cold_gal)
            if cold_f >= p.cold_release_f:
                cold_gal, cold_f, seen = 0.0, p.reference_f, False
        return replace(
            self,
            heat_btu=self.heat_btu + bottom_btu + top_btu,
            cold_gal=cold_gal,
            cold_f=cold_f,
            cold_seen=seen,
        )

    def lost(self, btu: float) -> Booked:
        """Standby loss, out of the drawable heat."""
        return replace(self, heat_btu=self.heat_btu - btu)

    def observed(
        self,
        lower_f: float,
        p: BookParams | None = None,
        *,
        drawing: bool = False,
    ) -> Booked:
        """The lower probe's reading, read against the cold region
        (module docstring). Below ``cold_release_f`` it has seen
        the region. Seen, and at or above the line again with nothing
        being drawn, it has seen the region rejoin, whatever heat the
        book had placed in it: the region is released. A region the
        probe never read below the line (a shower from a full tank, its
        cold water under the probe) is not."""
        p = p or BookParams()
        if self.cold_gal <= 0.0:
            return self
        if lower_f < p.cold_release_f:
            return self if self.cold_seen else replace(self, cold_seen=True)
        if drawing or not self.cold_seen:
            return self
        return replace(
            self, cold_gal=0.0, cold_f=p.reference_f, cold_seen=False
        )

    def step(
        self,
        s: Step,
        p: BookParams | None = None,
        circulation: CirculationParams | None = None,
    ) -> Booked:
        """One recorded step: ``step_heat_btu``'s terms, placed."""
        p = p or BookParams()
        h = s.seconds / 3600.0
        b = replace(self, inlet_f=s.inlet_f)
        house = house_gpm(s, circulation)
        drawing = house > p.draw_gpm
        if drawing:
            b = b.drawn(house * s.seconds / 60.0, s.upper_f, p)
        b = b.observed(s.lower_f, p, drawing=drawing)
        bottom = compressor_btu(h, s.ambient_f, p) if s.compressor_on else 0.0
        top = 0.0
        if s.element_on:
            if s.lower_element:
                bottom += element_btu(h, p)
            else:
                top = element_btu(h, p)
        b = b.heated(bottom, top, p)
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
        return deliverable_from_heat(
            self.heat_btu,
            upper_f,
            self.inlet_f,
            p,
            withheld_btu=self.withheld_btu(p),
        )


def deliverable_from_heat(
    heat_btu: float,
    upper_f: float,
    inlet_f: float,
    p: BookParams | None = None,
    *,
    withheld_btu: float = 0.0,
) -> float:
    """Delivered gallons the heat above the empty point, less what the
    cold region withholds, will make, each taking
    ``8.34 · (T_delivered − T_inlet)``. Not capped here."""
    p = p or BookParams()
    per_gal = WATER_BTU_PER_GAL_F * (delivery_f(upper_f, p) - inlet_f)
    if per_gal <= 0 or not math.isfinite(heat_btu):
        return 0.0
    return max(0.0, (heat_btu - withheld_btu - p.empty_btu) / per_gal)


# ── What the engine asks of it at a draw ────────────────────────────

#: The line, delivered water below which is not hot, °F: the default of
#: ``ReadinessParams.line_f``, which a caller passes as ``line_f``.
DEPLETION_THRESHOLD_F = 105.0
#: How fast the delivered water falls per delivered gallon once it has
#: crossed the line: the default of ``ReadinessParams.fall_f_per_gal``.
FALL_F_PER_GAL = 2.0
#: Below this a booked zone is the draw's own: the book moves it no less.
_ZONE_MOVED_F = 0.01


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
    withheld_btu: float = 0.0,
    ep: BookParams | None = None,
    *,
    empty_btu: float | None = None,
) -> float:
    """Delivered gallons the booked heat gives before the upper probe
    crosses the line: negative once a draw has gone past it, by the
    gallons it went. The heat is read no higher than ``tank_max_btu``;
    ``-inf`` when a gallon would take no heat (a tank at the inlet).
    ``empty_btu`` is the book's empty point unless given (the zone's,
    ``zone_after_draw_f``)."""
    ep = ep or BookParams()
    per_gal = WATER_BTU_PER_GAL_F * (delivery_f(upper_f, ep) - inlet_f)
    if per_gal <= 0.0 or not math.isfinite(heat_btu):
        return -math.inf
    heat = min(heat_btu, tank_max_btu(upper_f, lower_f, ep))
    empty = ep.empty_btu if empty_btu is None else empty_btu
    return (heat - withheld_btu - empty) / per_gal


def zone_after_draw_f(
    booked: Booked,
    upper_f: float,
    lower_f: float,
    fall_f_per_gal: float = FALL_F_PER_GAL,
    ep: BookParams | None = None,
    *,
    line_f: float = DEPLETION_THRESHOLD_F,
) -> float:
    """The upper zone just after a draw, from the booked state after it
    (module docstring, *The upper zone through a draw*): the line plus
    ``fall_f_per_gal`` per delivered gallon the booked heat still gives
    before the zone's empty point (``zone_empty_btu``), less per gallon
    drawn past it; no warmer than ``upper_f``, the draw's own response,
    and no colder than ``lower_f``."""
    ep = ep or BookParams()
    left = probe_line_gal(
        booked.heat_btu,
        upper_f,
        lower_f,
        booked.inlet_f,
        booked.withheld_btu(ep),
        ep,
        empty_btu=ep.zone_empty_btu,
    )
    if not math.isfinite(left):
        return upper_f
    line = line_f + fall_f_per_gal * left
    return min(upper_f, max(lower_f, line))


def _mix_potential(left: float, ep: BookParams) -> float:
    """The integral of ``zone_mixed_f``'s rate over booked gallons left:
    its rate is ``zone_mix_f_per_gal · exp(-left / zone_mix_gal)`` above
    the zone's empty point and ``zone_mix_f_per_gal`` past it."""
    s, lam = ep.zone_mix_f_per_gal, ep.zone_mix_gal
    if left >= 0.0:
        return -s * lam * math.exp(-left / lam)
    return -s * lam + s * left


def zone_mixed_f(
    booked: Booked,
    gal: float,
    upper_before_f: float,
    upper_f: float,
    lower_f: float,
    ep: BookParams | None = None,
) -> float:
    """The upper zone just after ``gal`` delivered gallons drawn from
    ``upper_before_f`` (module docstring, *The upper zone through a
    draw*): the water above the rising front mixes, so the zone falls
    by the rate's integral over the gallons, the booked state after the
    draw ``booked`` giving the gallons left before ``zone_empty_btu``
    at ``upper_f``, the draw's own response, and ``lower_f``. No warmer
    than ``upper_f``, no colder than ``lower_f``; ``upper_f`` when the
    book cannot say (a tank at the inlet)."""
    ep = ep or BookParams()
    if gal <= 0.0 or ep.zone_mix_f_per_gal <= 0.0 or ep.zone_mix_gal <= 0.0:
        return upper_f
    left = probe_line_gal(
        booked.heat_btu,
        upper_f,
        lower_f,
        booked.inlet_f,
        booked.withheld_btu(ep),
        ep,
        empty_btu=ep.zone_empty_btu,
    )
    if not math.isfinite(left):
        return upper_f
    drop = _mix_potential(left + gal, ep) - _mix_potential(left, ep)
    return min(upper_f, max(lower_f, upper_before_f - drop))


def front_share(cold_gal: float, ep: BookParams | None = None) -> float:
    """Where the lower probe reads, between the cold region (0) and the
    hot water above it (1), with the region ``cold_gal`` tank gallons:
    1 until the front reaches the probe, falling linearly across
    ``front_width_gal`` centred on ``lower_probe_gal``, 0 past it."""
    ep = ep or BookParams()
    if ep.front_width_gal <= 0.0:
        return 1.0 if cold_gal < ep.lower_probe_gal else 0.0
    share = 0.5 - (cold_gal - ep.lower_probe_gal) / ep.front_width_gal
    return min(1.0, max(0.0, share))


def front_start_gal(ep: BookParams | None = None) -> float:
    """The cold region's volume at which the front first reaches the
    lower probe (``front_share`` falls below 1)."""
    ep = ep or BookParams()
    return ep.lower_probe_gal - max(0.0, ep.front_width_gal) / 2.0


def lower_after_draw_f(
    before: Booked,
    after: Booked,
    upper_f: float,
    lower_f: float,
    ep: BookParams | None = None,
) -> float:
    """The lower zone just after a draw, from where the booked cold
    region puts the front (module docstring, *The lower zone through a
    draw*): ``lower_f``, the zone before it, less the front's passage
    over the probe, the share it crossed (``front_share`` before, less
    after) of the span from the region to ``upper_f``, the water above
    it. A draw that leaves the front below the probe moves the zone not
    at all; it never goes below the region, and is never warmed."""
    ep = ep or BookParams()
    crossed = front_share(before.cold_gal, ep) - front_share(after.cold_gal, ep)
    drop = crossed * (upper_f - after.cold_f)
    if drop <= 0.0:
        return lower_f
    return max(min(lower_f, after.cold_f), lower_f - drop)


def front_cannot_move(
    booked: Booked, gal: float, ep: BookParams | None = None
) -> bool:
    """Whether no draw can move the lower zone (``lower_after_draw_f``)
    from ``booked`` through ``gal`` more delivered gallons: the region
    grows by at most the gallons delivered (each takes its hot share of
    a gallon from the tank, never more) and nothing else grows it, so
    while that bound leaves it short of ``front_start_gal`` the front
    has not reached the probe. For the engine to skip walking the book
    (``engine._follow_ledger``); it never decides a move."""
    return booked.cold_gal + max(0.0, gal) < front_start_gal(ep)


def zone_cannot_move(
    booked: Booked,
    gal: float,
    lost_btu: float,
    upper_lo_f: float,
    upper_hi_f: float,
    fall_f_per_gal: float = FALL_F_PER_GAL,
    ep: BookParams | None = None,
    *,
    line_f: float = DEPLETION_THRESHOLD_F,
) -> bool:
    """Whether no draw can move the upper zone (``zone_after_draw_f``)
    from ``booked`` through ``gal`` more delivered gallons and at most
    ``lost_btu`` of standby, with the zone anywhere in
    ``[upper_lo_f, upper_hi_f]``; True only when that is certain.

    A floor under the heat less what the cold region withholds: draws
    priced at the hottest zone, any withheld heat dropped (a release
    can lift a winter region's negative share to none), and every
    gallon's inlet above the reference withheld; heat going in only
    raises it, since the bottom's lands in the region it is withheld
    from. The tank's ceiling (``tank_max_btu``) is taken at the zone,
    less the most a region below ``cold_release_f`` can withhold. A
    re-anchor is no floor: the caller rules one out. For the engine to
    skip walking the book where it is far from the zone's empty point;
    it never decides a move."""
    ep = ep or BookParams()
    inlet = booked.inlet_f
    hot = max(0.0, delivery_f(upper_hi_f, ep) - inlet)
    floor = (
        booked.heat_btu
        - max(0.0, booked.withheld_btu(ep))
        - gal * WATER_BTU_PER_GAL_F * (hot + max(0.0, inlet - ep.reference_f))
        - lost_btu
    )
    region = min(ep.tank_gal, booked.cold_gal + gal)
    withheld_max = max(
        booked.withheld_btu(ep),
        WATER_BTU_PER_GAL_F * region * (ep.cold_release_f - ep.reference_f),
    )
    u = upper_lo_f
    while True:
        per_gal = WATER_BTU_PER_GAL_F * (delivery_f(u, ep) - inlet)
        if per_gal > 0.0:
            ceiling = tank_max_btu(u, u, ep) - withheld_max
            left = (min(floor, ceiling) - ep.zone_empty_btu) / per_gal
            if line_f + fall_f_per_gal * left < u:
                return False
        if u >= upper_hi_f:
            return True
        u = min(upper_hi_f, u + 0.25)


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
class WalkCarry:
    """Where a walk stood on reaching an instant, before its rules there
    ran: enough to resume it from that instant and get what the whole
    walk gets from there on (``walk_booked``'s ``carry``). Only an
    instant whose past cannot change is a place to resume from: the
    engine's own clock, with the path before it written."""

    at: datetime
    state: Booked
    clean: bool
    drawn: bool
    #: Heat in over the span that ended at ``at``, any and at the bottom.
    heated: bool
    bottom: bool


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
    #: Where the walk stood at ``walk_booked``'s ``keep``: None without
    #: one, or when ``keep`` is not one of its instants.
    carry: WalkCarry | None = None

    def before(self, at: datetime) -> Booked:
        """The state at ``at``, before anything drawn at that instant.
        The walk stops at every path element, so a draw window's onset
        (a mark) is one of its instants; between two, the earlier."""
        i = bisect_right(self.instants, at) - 1
        return self.befores[max(0, i)]


def projected_release(
    state: Booked,
    lower_f: float,
    p: BookParams | None = None,
    *,
    heating: bool,
    drawn: bool,
) -> Booked:
    """``state`` once a projected lower zone reads ``lower_f``.

    The book believes the lower probe (``Booked.observed``): a
    cold region the probe read below ``cold_release_f`` rejoins once it
    reads at or above it with nothing being drawn. A projection whose
    lower zone gets there must release it the same way, or it answers
    later than the book will when the tank arrives: replayed over cold
    bottoms without this, readiness ran a mean +14.7 min late
    (2026-10-03).

    Only while ``heating`` and with nothing ``drawn`` in the projection,
    or a draw running now. The lower zone then rises from the probe's
    own reading by the heat going in, which is the trajectory readiness
    projects. A modelled zone after a modelled draw reads warm where the
    probe would read the cold front (releasing there turned
    2026-09-21's forecast depletion into a miss), and mid-draw the probe
    reads the water above the incoming cold, which the book holds on
    too.

    It only releases: a region the probe has not read below the line is
    not marked seen by a modelled zone, whose reading is no probe's."""
    if not state.cold_seen or drawn or not heating:
        return state
    return state.observed(lower_f, p)


def walk_booked(
    start: Booked,
    points: Sequence[PathPoint],
    heating: Sequence[HeatingInterval],
    draws: Sequence[Draw],
    ambient_at: Callable[[datetime], float],
    p: BookParams | None = None,
    *,
    carry: WalkCarry | None = None,
    keep: datetime | None = None,
    withheld: Sequence[Run] = (),
    extra: SpanLoss | None = None,
) -> BookedPath:
    """``start`` walked along ``points`` with the book's own terms.

    Draws are taken at their instants, at the simulated upper zone then
    (before the step). Between instants, the compressor's heat and the
    lower element's land at the bottom, the upper element's in the top
    layer, and standby (at the simulated zones' mean, to the ambient)
    comes out of the drawable heat. After the start,
    while the compressor or the lower element heats and nothing has been
    drawn, the simulated lower zone releases a cold region the probe saw
    (``projected_release``); the start is the book's own, which has
    already read the live probe.

    ``carry`` resumes a walk where an earlier one stood (``WalkCarry``):
    ``points`` then begin at ``carry.at`` and ``start`` is not read, and
    from there on the answer is the whole walk's, element for element.
    ``keep``, one of the walk's instants, is where to stand for the next
    resume (``BookedPath.carry``). The engine resumes at each draw from
    its own clock, so a day's walk is walked once, not once a draw.

    ``withheld`` are the windows over which a recovery is credited no
    heat (the engine's ``withheld_windows``): the compressor or
    element runs there and adds nothing to the book, as it adds nothing
    to the zones. It is still running, so the tank is not quiet there.

    ``extra`` is a client's own loss (``SpanLoss``): charged over each
    span, and a span it disturbs is not quiet.
    """
    p = p or BookParams()
    if carry is not None:
        start = carry.state
        points = [pt for pt in points if pt.at >= carry.at]
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

    def heat_in(a: datetime, b: datetime) -> tuple[float, float]:
        """Heat in over ``[a, b)``, (bottom, top), by source; none
        inside a withheld window."""
        mid = a + (b - a) / 2
        hours = (b - a).total_seconds() / 3600.0
        bottom = top = 0.0
        if any(w0 <= mid < w1 for w0, w1 in withheld):
            return bottom, top
        for h in heating:
            if not h.start.at <= mid < h.end:
                continue
            if h.source == "compressor":
                bottom += compressor_btu(hours, ambient_at(mid), p)
            elif h.zone == "lower":
                bottom += element_btu(hours, p)
            else:
                top += element_btu(hours, p)
        return bottom, top

    spans = list(itertools.pairwise(instants))
    inflow = [heat_in(a, b) for a, b in spans]
    # The heater running, which the anchor rule reads as not quiet,
    # whether its heat is credited or withheld.
    heats = [
        sum(x) > 0.0 or (bool(withheld) and running(a, b))
        for x, (a, b) in zip(inflow, spans, strict=True)
    ]
    # Heat into the bottom: what lifts the lower zone (``projected_release``).
    bottom_heats = [x[0] > 0.0 for x in inflow]
    # A client's own loss over each span, and whether it disturbs it.
    extras = [
        extra.loss(a, b) if extra is not None else (0.0, False)
        for a, b in spans
    ]

    state = start
    before: list[Booked] = []
    after: dict[datetime, Booked] = {}
    kept: WalkCarry | None = None
    # The book's anchor rule on the simulated
    # tank: quiet since a heating ended, and full. A recovery the heater
    # stopped itself, at its target or the TOU cap, is full by the
    # heater's own rule, whatever gap the zones show then; any other
    # end, or any quiet instant after one, is full when the zones are
    # within the book's band.
    clean = False if carry is None else carry.clean
    drawn_yet = False if carry is None else carry.drawn

    def heated_before(k: int) -> tuple[bool, bool]:
        """Heat in over the span ending at instant ``k`` (any, bottom):
        the carry's at a resumed walk's first instant, none at a fresh
        walk's."""
        if k > 0:
            return heats[k - 1], bottom_heats[k - 1]
        if carry is not None:
            return carry.heated, carry.bottom
        return False, False

    for k, at in enumerate(instants):
        prev_heat, prev_bottom = heated_before(k)
        if at == keep:
            kept = WalkCarry(
                at, state, clean, drawn_yet, prev_heat, prev_bottom
            )
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
        before.append(state)
        gal = by_instant.get(at, 0.0)
        if gal > 0.0:
            state = state.drawn(gal, zones(at)[0], p)
            clean = False
        drawn_yet = drawn_yet or gal > 0.0
        if k > 0 or carry is not None:
            state = projected_release(
                state,
                zones(at)[1],
                p,
                heating=prev_bottom,
                drawn=drawn_yet,
            )
        after[at] = state
        if k == len(spans):
            break
        nxt = instants[k + 1]
        mid = at + (nxt - at) / 2
        hours = (nxt - at).total_seconds() / 3600.0
        bottom, top = inflow[k]
        upper, lower = zones(mid)
        lost = standby_btu(hours, upper, lower, ambient_at(mid), p)
        lost += extras[k][0]
        if extras[k][1]:
            clean = False
        if heats[k]:
            clean = False
        state = state.heated(bottom, top, p).lost(lost)

    index = {at: i for i, at in enumerate(instants)}
    states = []
    for i, pt in enumerate(points):
        repeated = i + 1 < len(points) and points[i + 1].at == pt.at
        states.append(before[index[pt.at]] if repeated else after[pt.at])
    return BookedPath(states, instants, before, kept)


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


# ── The core's HeatLedger ───────────────────────────────────────────


@dataclass(frozen=True)
class BookedHeatLedger:
    """The book as the core's ``HeatLedger``: ``start`` walked along the
    engine's path with the book's own terms (``walk_booked``), and read
    at each draw for the zones it leaves. It holds nothing between
    calls: its walk's ``WalkCarry`` is the engine's ``Stand``.

    Built per simulation: the book at the walk's start, the ambient the
    compressor and standby run to, the line and the fall rate the upper
    zone is taken down on (``ReadinessParams.line_f``,
    ``fall_f_per_gal``), the windows over which heat is credited none,
    and a client's own loss (``SpanLoss``), if any."""

    start: Booked
    ambient_at: Callable[[datetime], float]
    p: BookParams = field(default_factory=BookParams)
    withheld: Sequence[Run] = ()
    line_f: float = DEPLETION_THRESHOLD_F
    fall_f_per_gal: float = FALL_F_PER_GAL
    extra: SpanLoss | None = None

    @property
    def zones(self) -> LedgerZones:
        """The lower zone's settling after the front moves it, and
        whether every draw may mix the upper zone down."""
        return LedgerZones(
            settle_min=self.p.front_settle_min,
            inlet_f=self.p.inlet_default_f,
            mixes=self.p.zone_mix_f_per_gal > 0.0 and self.p.zone_mix_gal > 0.0,
        )

    def walk(
        self,
        points: Sequence[PathPoint],
        heating: Sequence[HeatingInterval],
        draws: Sequence[Draw],
        carry: WalkCarry | None = None,
        keep: datetime | None = None,
    ) -> BookedPath:
        """``start`` walked along ``points`` (``walk_booked``): resumed
        from ``carry``, standing at ``keep`` for the next."""
        return walk_booked(
            self.start,
            points,
            heating,
            draws,
            self.ambient_at,
            self.p,
            carry=carry,
            keep=keep,
            withheld=self.withheld,
            extra=self.extra,
        )

    def loss_bound(
        self, start: datetime, end: datetime, upper_f: float
    ) -> float:
        """The most the walk can charge over ``[start, end]``
        (``loss_ceiling_btu``)."""
        return loss_ceiling_btu(start, end, upper_f, self.p, extra=self.extra)

    def after_draw(self, q: DrawTaken) -> AfterDraw:
        """The book walked along the path to the draws at ``q.at``, as
        the walk after the simulation walks it, unless a bound shows
        neither zone can move (``_zone_far``, ``_front_far``; with
        mixing, none does). The lower zone is the front's: from
        ``q.lower_f``, by the share of the front the draws moved past the
        probe (``lower_after_draw_f``). The upper zone goes down to the
        colder of ``zone_after_draw_f`` and ``zone_mixed_f`` (the mixing
        above the front, from ``q.upper_f``) of the booked state after
        them when that is below the draws' own response, over the lower
        zone the engine then reads (the front's, no warmer than the upper
        zone, or their own response while the heater runs)."""
        carry = cast("WalkCarry | None", q.stand)
        upper_far = self._zone_far(carry, q)
        if upper_far and (q.heating or self._front_far(carry, q.drawn_gal)):
            # The front is still below the probe, or the heater runs:
            # the front has no say over the lower zone.
            return AfterDraw(lower_f=q.lower_f)
        walked = self.walk(q.path, q.intervals, q.draws, carry, q.at)
        stand = walked.carry
        inlet = walked.states[-1].inlet_f if walked.states else None
        after = walked.states[-1]
        front = lower_after_draw_f(
            walked.before(q.at), after, q.upper_f, q.lower_f, self.p
        )
        if upper_far:
            return AfterDraw(front, stand=stand, inlet_f=inlet)
        lower = q.drawn_lower_f if q.heating else min(front, q.drawn_upper_f)
        line = zone_after_draw_f(
            after,
            q.drawn_upper_f,
            lower,
            self.fall_f_per_gal,
            self.p,
            line_f=self.line_f,
        )
        zone = min(
            line,
            zone_mixed_f(
                after, q.gallons, q.upper_f, q.drawn_upper_f, lower, self.p
            ),
        )
        if zone >= q.drawn_upper_f - _ZONE_MOVED_F:
            return AfterDraw(front, stand=stand, inlet_f=inlet)
        spent = line < q.drawn_upper_f - _ZONE_MOVED_F
        return AfterDraw(front, zone, spent, stand, inlet)

    def front_moves_at(
        self, stand: Stand, drawn_gal: float, pending: Sequence[Draw]
    ) -> datetime | None:
        """``front_cannot_move`` from where the walk stood, through every
        draw since and every pending one to each onset."""
        carry = cast("WalkCarry", stand)
        gal = drawn_gal
        for at, g in pending:
            gal += g
            if not front_cannot_move(carry.state, gal, self.p):
                return at
        return None

    def upper_moves_at(self, q: DrawsAhead) -> UpperAhead:
        """The book walked along the path ahead (to the first onset only
        with ``q.head``, the rest then decided by ``zone_cannot_move``
        where it can be), and each onset's draw read against it as
        ``after_draw`` reads one: the first whose zone goes below the
        draw's own response on the coast."""
        stand = cast("WalkCarry | None", q.stand)
        inlet: float | None = None

        def walk(
            path: Sequence[PathPoint], draws: Sequence[Draw]
        ) -> BookedPath:
            nonlocal stand, inlet
            walked = self.walk(path, q.intervals, draws, stand, q.at)
            if walked.carry is not None:
                stand = walked.carry
            if walked.states:
                inlet = walked.states[-1].inlet_f
            return walked

        gal: dict[datetime, float] = {}
        for at, g in q.pending:
            gal[at] = gal.get(at, 0.0) + g
        onsets = q.onsets
        first = onsets[0]
        if q.head is not None:
            walked = walk(
                q.head, [*q.taken, *(d for d in q.pending if d[0] <= first)]
            )
        else:
            walked = walk(q.path, [*q.taken, *q.pending])
        whole = q.head is None
        after: Booked | None = None
        for i, at in enumerate(onsets):
            if i == 1 and not whole:
                assert after is not None and q.bound is not None
                if zone_cannot_move(
                    after,
                    sum(gal[x] for x in onsets[1:]),
                    q.bound.lost_btu,
                    q.bound.upper_lo_f,
                    q.bound.upper_hi_f,
                    self.fall_f_per_gal,
                    self.p,
                    line_f=self.line_f,
                ):
                    return UpperAhead(None, stand, inlet)
                walked = walk(q.path, [*q.taken, *q.pending])
                whole = True
            here = point_at(q.points, at)
            upper, lower = q.respond(at, here.upper_f, here.lower_f, gal[at])
            after = walked.before(at).drawn(gal[at], here.upper_f, self.p)
            zone = min(
                zone_after_draw_f(
                    after,
                    upper,
                    lower,
                    self.fall_f_per_gal,
                    self.p,
                    line_f=self.line_f,
                ),
                zone_mixed_f(
                    after, gal[at], here.upper_f, upper, lower, self.p
                ),
            )
            if zone < upper - _ZONE_MOVED_F:
                return UpperAhead(at, stand, inlet)
        return UpperAhead(None, stand, inlet)

    def _zone_far(self, carry: WalkCarry | None, q: DrawTaken) -> bool:
        """Whether, by a bound and without walking, the draws just taken
        cannot move the upper zone (``zone_cannot_move``): from where the
        walk last stood, through every draw since, with the engine's
        ``loss_bound`` and any heat in ignored. Not across a re-anchor,
        which is no floor: none can have happened since that stand when
        nothing has stopped heating since (the engine's to rule out:
        ``q.bound`` None), and what heated then is heating still."""
        bound = q.bound
        if carry is None or bound is None or carry.clean:
            return False
        if carry.heated and not any(
            at <= carry.at for at in bound.running_since
        ):
            return False
        return zone_cannot_move(
            carry.state,
            q.drawn_gal,
            bound.lost_btu,
            bound.upper_lo_f,
            bound.upper_hi_f,
            self.fall_f_per_gal,
            self.p,
            line_f=self.line_f,
        )

    def _front_far(self, carry: WalkCarry | None, drawn_gal: float) -> bool:
        """Whether, by a bound and without walking, the draws since the
        stand leave the front below the lower probe
        (``front_cannot_move``). Only draws grow the cold region, so no
        re-anchor, release or heat since can defeat it."""
        if carry is None:
            return False
        return front_cannot_move(carry.state, drawn_gal, self.p)


def full_tank_book(
    upper_f: float,
    lower_f: float,
    p: BookParams | None = None,
    *,
    inlet_f: float | None = None,
) -> Booked:
    """A book anchored on a full tank at these zones (``full_tank``),
    for a caller who knows the tank has been quiet since a heating ended:
    a recovery finished and nothing drawn since. The library does not
    judge that from the probes, which read full over the cold water of a
    draw. ``inlet_f`` defaults to ``BookParams.inlet_default_f``, the
    frame ``empty_btu`` was fitted in."""
    p = p or BookParams()
    return full_tank(
        upper_f,
        lower_f,
        p.inlet_default_f if inlet_f is None else inlet_f,
        p,
    )
