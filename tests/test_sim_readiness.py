"""How much hot water the tank can deliver, and the book's zones through
a draw (``nwp500.sim.delivery``, ``nwp500.sim.book``).

Ported with the readiness and book code. The source built its states
from recorded steps, which needed a flow meter; here ``_step`` and
``_apply`` replay the same steps with the book's own terms, in the order
a recorded step applied them, so the states and the numbers are the
same. The source's readiness defaulted to one installation's evidence;
the library's has none, so ``P`` carries ``EXAMPLE_EVIDENCE`` and the
wrappers below pass it as the source's defaults did.
"""

import math
from dataclasses import dataclass, replace

import pytest

pytest.importorskip("pandas")

from nwp500.sim import delivery as rd
from nwp500.sim.book import (
    DEPLETION_THRESHOLD_F,
    Booked,
    compressor_btu,
    deliverable_from_heat,
    delivery_f,
    element_btu,
    front_cannot_move,
    front_share,
    front_start_gal,
    full_tank,
    lower_after_draw_f,
    standby_btu,
    tank_max_btu,
    zone_after_draw_f,
    zone_mixed_f,
)
from nwp500.sim.params import BookParams, ReadinessParams
from nwp500.sim.physics.draw import (
    settled_lower_f,
    unsettled_after_f,
)

EP = BookParams()
TANK_BTU_PER_F = 8.34 * EP.tank_gal
EVIDENCE = rd.EXAMPLE_EVIDENCE
OBSERVED_MAX_GAL = rd.observed_max_gal(EVIDENCE)
P = rd.with_example_evidence(ReadinessParams())
#: The delivered line's lag behind the probe's: every answer carries it
#: on top of the probe line's gallons.
LAG = P.delivered_lag_gal
#: The probe's own line, no lag: for the tests of what the probe line
#: rests on (the evidence, the floor, the clamp), which the lag only
#: shifts.
P0 = replace(P, delivered_lag_gal=0.0)
#: Hot enough to dominate every evidence point.
FULL = (150.0, 150.0)


def deliverable(upper, lower, p=None, **kw):
    return rd.deliverable(upper, lower, P if p is None else p, **kw)


def booked_deliverable(booked, upper, lower, p=None):
    return rd.booked_deliverable(booked, upper, lower, P if p is None else p)


def delivery_temp_f(booked, upper, p=None, *, lower_f=None):
    return rd.delivery_temp_f(
        booked, upper, P if p is None else p, lower_f=lower_f
    )


def zone_delivery_f(upper, past, p=None):
    return rd.zone_delivery_f(upper, past, P if p is None else p)


def demonstrated_gal(upper, lower):
    return rd.demonstrated_gal(upper, lower, EVIDENCE)


# ── recorded steps, replayed with the book's terms ──────────────────

#: The flow that is a draw, GPM.
DRAW_GPM = 0.3


@dataclass(frozen=True)
class Step:
    """``s`` seconds at probes ``u``/``lo`` with ``flow`` GPM drawn."""

    u: float
    lo: float
    flow: float = 0.0
    comp: bool = False
    el: bool = False
    s: float = 10.0
    lower_element: bool = False


def _step(u=141.8, lo=141.8, flow=0.0, comp=False, el=False, s=10.0, **kw):
    return Step(u, lo, flow, comp, el, s, **kw)


def _apply(b: Booked, st: Step) -> Booked:
    """One recorded step: the draw, the lower probe's reading, the heat
    in where it lands, and standby to a 65 °F ambient."""
    h = st.s / 3600.0
    drawing = st.flow > DRAW_GPM
    if drawing:
        b = b.drawn(st.flow * st.s / 60.0, st.u, EP)
    b = b.observed(st.lo, EP, drawing=drawing)
    bottom = compressor_btu(h, 65.0, EP) if st.comp else 0.0
    top = 0.0
    if st.el:
        if st.lower_element:
            bottom += element_btu(h, EP)
        else:
            top = element_btu(h, EP)
    b = b.heated(bottom, top, EP)
    return b.lost(standby_btu(h, st.u, st.lo, 65.0, EP))


def _booked(steps: list[Step]) -> Booked:
    """The book over ``steps`` from its anchor: the last full step that
    has been quiet since a heating ended (as a record's book anchors)."""
    anchor = None
    clean = was_heating = False
    for i, st in enumerate(steps):
        heating = st.comp or st.el
        disturbed = st.flow > DRAW_GPM
        full = abs(st.u - st.lo) <= EP.uniform_band_f
        if heating:
            clean = False
        elif was_heating:
            clean = True
        if disturbed:
            clean = False
        was_heating = heating
        if clean and not heating and full:
            anchor = i
    assert anchor is not None
    a = steps[anchor]
    b = full_tank(a.u, a.lo, EP.inlet_default_f, EP)
    for st in steps[anchor + 1 :]:
        b = _apply(b, st)
    age = sum(st.s for st in steps[anchor + 1 :]) / 3600.0
    return replace(b, anchor_age_h=age)


FULL_TANK = [_step(comp=True), _step()]


def _bath(gal=30.0):
    """A full 141.8 °F tank that has just run a bath of ``gal``."""
    n = round(gal * 2)  # 3 GPM over 10 s steps: half a gallon each
    steps = [_step(141.0, 141.0 - i * 0.1, flow=3.0) for i in range(n)]
    return _booked([*FULL_TANK, *steps])


class TestDeliverable:
    def test_it_never_promises_more_than_history_has_shown(self):
        d = deliverable(*FULL)
        assert d.gal == pytest.approx(OBSERVED_MAX_GAL + LAG, abs=0.05)
        assert d.at_observed_max

    def test_below_the_threshold_nothing_is_deliverable(self):
        assert deliverable(DEPLETION_THRESHOLD_F - 0.1, 104.0).gal == 0.0

    def test_a_state_colder_than_every_evidence_draw_is_zero(self):
        coldest = min(u for u, _, _ in EVIDENCE)
        assert demonstrated_gal(coldest - 0.1, 150.0) == 0.0

    def test_after_a_bath_it_does_not_promise_what_crashed(self):
        """2026-04-14 03:58: a 10 gal top-up took the upper probe from
        141.3 to 100.9 °F with the lower at 89.6."""
        d = deliverable(141.26, 89.60)
        assert d.thermocline_unlocated
        assert d.gal <= P.cold_lower_cap_gal < 10.0

    def test_the_cold_lower_cap_only_ever_lowers_the_evidence(self):
        for upper, lower in ((147.0, 95.0), (128.0, 99.0)):
            d = deliverable(upper, lower)
            raw = demonstrated_gal(upper, lower)
            probe = min(raw, P.cold_lower_cap_gal)
            assert d.gal == pytest.approx(
                probe + LAG if probe > 0 else 0.0, abs=0.05
            )

    def test_the_book_is_not_capped_its_cold_bottom_is_withheld(self):
        """From the book the cold lower probe does not cap the answer;
        the heat that landed in the cold region comes off it.
        (38,000 BTU: under the 40,586 a whole tank at 147 °F can hold.)"""

        full = deliverable_from_heat(38000.0, 147.0, 70.0)
        e = deliverable(147.0, 95.0, heat_btu=38000.0, inlet_f=70.0)
        assert e.basis == "energy" and e.thermocline_unlocated
        assert e.gal == pytest.approx(full + LAG, abs=0.05)
        assert e.gal > P.cold_lower_cap_gal
        w = deliverable(
            147.0, 95.0, heat_btu=38000.0, inlet_f=70.0, withheld_btu=8000.0
        )
        per_gal = 8.34 * (min(147.0, 53.56 + 0.485 * 147.0) - 70.0)
        assert full + LAG - w.gal == pytest.approx(8000.0 / per_gal, abs=0.1)

    @pytest.mark.parametrize("fixed", [110.0, 125.0, 140.0])
    def test_a_warmer_tank_never_delivers_less(self, fixed):
        steps = [100.0 + 2.0 * i for i in range(26)]
        by_upper = [demonstrated_gal(u, fixed) for u in steps]
        by_lower = [demonstrated_gal(fixed, lo) for lo in steps]
        assert by_upper == sorted(by_upper)
        assert by_lower == sorted(by_lower)

    def test_a_tank_at_its_setpoint_has_the_full_tank_floor(self):
        """2026-09-28 14:41 PDT, a tank just off a recovery to
        141.8 °F read 25.1 gal from the evidence, 0.18 °F under the 33.4
        gal step, and a 22.4 gal bath then left the upper probe at
        140.2. At its setpoint it has the floor; off it, the evidence."""
        assert deliverable(141.08, 141.26, P0).gal == 25.1
        d = deliverable(141.08, 141.26, P0, setpoint_f=141.8)
        assert d.basis == "evidence"
        assert 30.5 < d.gal == pytest.approx(35.7, abs=0.05)
        assert deliverable(141.08, 141.26, P0, setpoint_f=143.2).gal == 25.1

    def test_a_running_heater_withholds_the_floor(self):
        """In a recovery's last minutes the probes reach the setpoint
        over cold water the heater is still warming; the book clears at
        the quiet end that follows."""
        assert (
            deliverable(141.08, 141.26, P0, setpoint_f=141.8, heating=True).gal
            == 25.1
        )

    def test_the_book_is_read_no_higher_than_the_tank_can_hold(self):
        """2026-09-28 17:56 PDT: the 13:29 anchor carried through a
        bath and a TOU-capped recovery booked 39,027 BTU over probes of
        140.18/138.2 °F, 61.1 gal. A whole tank at 140.18 holds 36,991."""

        b = Booked(39027.47, 4.44, 76.66, 1.0)
        cap = tank_max_btu(140.18, 138.2)
        assert cap == pytest.approx(8.34 * 63.2 * (140.18 - 70.0))
        whole = deliverable_from_heat(cap, 140.18, 76.66)
        got = booked_deliverable(b, 140.18, 138.2, P0).gal
        assert got == pytest.approx(whole, abs=0.05)
        assert got < deliverable_from_heat(b.heat_btu, 140.18, 76.66) - 5.0

    def test_the_floor_above_the_evidence_is_not_its_cap(self):
        """``at_observed_max`` says the evidence ran out; the floor
        answering above it is not the evidence."""
        d = deliverable(146.0, 146.0, setpoint_f=146.0)
        assert d.gal > OBSERVED_MAX_GAL
        assert not d.at_observed_max

    def test_every_evidence_point_answers_for_itself(self):
        for u, lo, g in EVIDENCE:
            assert demonstrated_gal(u, lo) == g


class TestBookkeeping:
    def test_a_full_tank_is_known_exactly(self):
        b = _booked(FULL_TANK)
        assert b.heat_btu == pytest.approx(TANK_BTU_PER_F * 71.8)
        assert b.anchor_age_h == 0.0

    def test_a_full_tank_delivers_about_48_gallons(self):
        """The calibration's answer for a 141.8 °F tank; a 30.5 gal bath
        is ready with room to spare."""
        b = _booked(FULL_TANK)
        gal = deliverable_from_heat(b.heat_btu, 141.8, 70.0)
        assert 44.0 < gal < 53.0

    def test_a_draw_takes_what_the_valve_delivers(self):
        """One minute at 2 GPM from a 140 °F tank: 2 gal at the valve's
        121.5 °F, from a 70 °F inlet."""
        draw = [_step(140.0, 140.0, flow=2.0) for _ in range(6)]
        b = _booked(
            [_step(140.0, 140.0, comp=True), _step(140.0, 140.0), *draw]
        )
        expected = TANK_BTU_PER_F * 70.0 - 2.0 * 8.34 * (121.46 - 70.0)
        assert b.heat_btu == pytest.approx(expected, rel=1e-3)

    def test_the_bath_the_probes_cannot_see_is_counted(self):
        """After a 30 gal draw the probes can read 141/90, which the
        evidence cannot place. The book knows the heat left."""
        bath = [_step(141.0, 141.0 - i * 0.2, flow=3.0) for i in range(60)]
        b = _booked([*FULL_TANK, *bath])
        full = deliverable_from_heat(TANK_BTU_PER_F * 71.8, 141.8, 70.0)
        left = deliverable_from_heat(b.heat_btu, 141.0, 70.0)
        assert full - left == pytest.approx(30.0, abs=1.5)


class TestWhereTheHeatLands:
    """The heat pump heats from the bottom up, so heat that lands
    in the cold water a draw left is booked but not drawable; the upper
    element's lands in a thin layer at the top, and is."""

    def test_a_draw_leaves_its_cold_water_at_the_bottom(self):
        b = _bath(30.0)
        # 30 delivered gallons from a 141 °F tank through the valve.
        hot = (53.56 + 0.485 * 141.0 - 70.0) / (141.0 - 70.0)
        assert b.cold_gal == pytest.approx(30.0 * hot, rel=0.02)
        assert b.cold_f == pytest.approx(70.0)

    def test_compressor_heat_in_the_cold_bottom_is_withheld(self):
        """2026-03-31: after a bath the heat pump lifted the lower zone
        82 -> 98 °F while the upper held near 137. The book counted that
        heat as drawable and over-promised by 13.7 gal."""
        b = _bath(30.0)
        hour = [_step(141.0, 90.0, comp=True)] * 360
        after = b
        for st in hour:
            after = _apply(after, st)
        assert after.heat_btu > b.heat_btu + 3500.0
        assert after.deliverable_gal(141.0) == pytest.approx(
            b.deliverable_gal(141.0), abs=0.6
        )

    def test_the_lower_elements_heat_lands_there_too(self):
        b = _bath(30.0)
        lower = _step(141.0, 90.0, el=True, s=600.0, lower_element=True)
        assert _apply(b, lower).deliverable_gal(141.0) == pytest.approx(
            b.deliverable_gal(141.0), abs=0.2
        )

    def test_the_upper_elements_heat_is_drawable_but_only_its_own(self):
        """2026-04-14: six minutes of the upper element lifted the upper
        probe 126 -> 141 °F over a cold bottom. That is 1,757 BTU at the
        top: about four delivered gallons, not a full tank."""
        b = _bath(30.0)
        run = _step(141.0, 90.0, el=True, s=360.0)
        per_gal = 8.34 * (53.56 + 0.485 * 141.0 - 70.0)
        gained = _apply(b, run).deliverable_gal(141.0) - b.deliverable_gal(
            141.0
        )
        heat = EP.element_w * 3.412 * 0.1
        assert gained == pytest.approx(heat / per_gal, abs=0.2)

    def test_the_cold_bottom_rejoins_once_the_heat_pump_has_warmed_it(self):
        b = _bath(30.0)
        need = 8.34 * b.cold_gal * (EP.cold_release_f - 70.0)
        warm = b.heated(bottom_btu=need + 1.0)
        assert warm.cold_gal == 0.0 and warm.withheld_btu() == 0.0
        # All of it drawable at once, the heat that warmed the region too.
        per_gal = 8.34 * (53.56 + 0.485 * 141.0 - 70.0)
        assert warm.deliverable_gal(141.0) - b.deliverable_gal(
            141.0
        ) == pytest.approx((need + 1.0) / per_gal, abs=0.05)

    def test_a_colder_inlet_takes_only_the_hot_water_that_left(self):
        """Below the 70 °F reference the cold region's heat is negative,
        and so is `withheld_btu`. That is the accounting, not a slip:
        the draw charged the book the valve's heat down to the colder
        inlet, and the region hands back the part below the reference,
        so the drawable heat falls by the hot water that left, at its
        heat above the reference, whatever the inlet. Clamping it at
        zero would charge a winter inlet twice. Only ~70 °F inlets are
        in the record."""
        for inlet in (50.0, 70.0, 72.4):
            b = replace(_booked(FULL_TANK), inlet_f=inlet)
            after = b.drawn(10.0, 141.8)
            hot = after.cold_gal - b.cold_gal
            assert b.drawable_btu() - after.drawable_btu() == pytest.approx(
                8.34 * hot * (141.8 - 70.0)
            )
            assert (after.withheld_btu() < 0.0) == (inlet < 70.0)

    @staticmethod
    def _seen_bath() -> Booked:
        """A 30 gal bath the lower probe followed down to 85 °F, then an
        hour of compressor heat into its cold bottom."""
        n = 60
        steps = [
            _step(141.0, 141.0 - i * (56.0 / n), flow=3.0) for i in range(n)
        ]
        b = _booked([*FULL_TANK, *steps])
        for st in [_step(141.0, 90.0, comp=True)] * 360:
            b = _apply(b, st)
        return b

    def test_a_region_the_probe_saw_rejoins_when_it_reads_the_line(self):
        """The heat the compressor put into the cold bottom is
        withheld until the book's region passes 100 °F, or until the
        lower probe, having read the region below the line, reads the
        line again with nothing drawn: then all of it is drawable."""
        b = self._seen_bath()
        assert b.cold_seen and b.withheld_btu() > 3000.0
        per_gal = 8.34 * (53.56 + 0.485 * 141.0 - 70.0)
        at_line = _apply(b, _step(141.0, EP.cold_release_f))
        assert at_line.cold_gal == 0.0 and at_line.withheld_btu() == 0.0
        assert at_line.deliverable_gal(141.0) - b.deliverable_gal(
            141.0
        ) == pytest.approx(b.withheld_btu() / per_gal, abs=0.05)
        below = _apply(b, _step(141.0, EP.cold_release_f - 0.1))
        assert below.cold_gal == b.cold_gal

    def test_not_while_a_draw_runs(self):
        b = self._seen_bath()
        drawing = _apply(b, _step(141.0, EP.cold_release_f + 5.0, flow=3.0))
        assert drawing.cold_gal > b.cold_gal

    def test_nor_a_region_the_probe_never_saw(self):
        """A shower from a full tank leaves its cold water under the
        lower probe, which reads hot throughout (63 of 73 draws of
        15-25 gal from a tank at 125 °F or more still read 100 °F or
        more five minutes on). That region is not released,
        and heat the compressor puts into it stays withheld."""
        b = _bath(20.0)
        assert b.cold_gal > 10.0 and not b.cold_seen
        quiet = b
        for st in [_step(141.0, 130.0)] * 30:
            quiet = _apply(quiet, st)
        assert quiet.cold_gal == b.cold_gal

    def test_a_new_region_must_be_seen_again(self):
        b = replace(self._seen_bath(), cold_gal=0.0)  # a flag left over
        again = b.drawn(10.0, 141.0)
        assert again.cold_gal > 0.0 and not again.cold_seen
        grown = self._seen_bath().drawn(5.0, 141.0)
        assert grown.cold_seen

    def test_the_booked_answer_is_the_placed_one(self):

        b = _bath(30.0).heated(bottom_btu=4000.0)
        d = booked_deliverable(b, 141.0, 90.0)
        assert d.gal == pytest.approx(b.deliverable_gal(141.0) + LAG, abs=0.05)
        assert (
            d.gal
            < deliverable(
                141.0, 90.0, heat_btu=b.heat_btu, inlet_f=b.inlet_f
            ).gal
            - 5.0
        )


class TestWhenItRunsOut:
    """The delivery temperature reads the same state as
    ``deliverable_gal``, so the two agree on whether it has run out."""

    def test_the_delivery_reads_the_heat_the_tank_can_hold(self):
        """The clamp holds for the delivery temperature too, so
        zero gallons and a delivery under the line still go together."""

        # 26,000 BTU booked; a whole tank at 112 °F holds 22,137.
        b = Booked(26000.0, 1.0, 70.0, cold_gal=30.0, cold_f=99.0)
        assert b.drawable_btu() > 0.0
        assert booked_deliverable(b, 112.0, 100.0, P0).gal == 0.0
        assert delivery_temp_f(b, 112.0, P0, lower_f=100.0) < 105.0

    def test_while_there_is_drawable_heat_it_is_the_upper_zone(self):

        assert delivery_temp_f(_bath(10.0), 139.0) == 139.0

    def test_spent_it_falls_below_the_line_and_on_per_gallon(self):

        b = _bath(30.0)
        # Past the probe's line by the lag: the delivered line.
        left = b.deliverable_gal(141.0) + LAG
        at_line = b.drawn(left + 0.1, 141.0)
        past = b.drawn(left + 3.0, 141.0)
        assert 104.0 < delivery_temp_f(at_line, 141.0) < 105.0
        assert delivery_temp_f(past, 141.0) == pytest.approx(
            105.0 - P.fall_f_per_gal * 3.0, abs=0.3
        )
        # No colder than the cold water coming up behind it.
        far = b.drawn(left + 40.0, 141.0)
        assert delivery_temp_f(far, 141.0) == pytest.approx(far.cold_f)

    def test_it_agrees_with_the_gallons_on_whether_the_tank_is_empty(self):

        b = _bath(20.0)
        for tenth in range(0, 400, 7):
            state = b.drawn(tenth / 10.0, 138.0)
            gal = booked_deliverable(state, 138.0, 95.0).gal
            below = delivery_temp_f(state, 138.0) < DEPLETION_THRESHOLD_F
            assert below == (gal == 0.0), (tenth, gal)


class TestTheZoneThroughADraw:
    """The upper zone after a draw reads the book too, against the empty
    point refit on the drawable frame (12,636 BTU), which centres the
    crossings; the delivery keeps the served one, which calls them
    early."""

    @staticmethod
    def _left(
        gal: float, cold_gal: float = 0.0, cold_f: float = 70.0
    ) -> Booked:
        """``gal`` delivered gallons above the zone's empty point at a
        140 °F zone, over a cold region of ``cold_gal`` at ``cold_f``."""

        per_gal = 8.34 * (delivery_f(140.0) - 70.0)
        return Booked(
            EP.zone_empty_btu + gal * per_gal,
            1.0,
            70.0,
            cold_gal=cold_gal,
            cold_f=cold_f,
        )

    def test_the_zone_point_is_the_refit_one_and_after_the_served(self):
        assert EP.zone_empty_btu == 12636.0 < EP.empty_btu

    def test_two_degrees_per_gallon_left_over_the_line(self):

        assert zone_after_draw_f(self._left(5.0), 140.0, 90.0) == (
            pytest.approx(105.0 + P.fall_f_per_gal * 5.0)
        )
        assert zone_after_draw_f(self._left(0.0), 140.0, 90.0) == (
            pytest.approx(105.0)
        )
        assert zone_after_draw_f(self._left(-3.0), 140.0, 90.0) == (
            pytest.approx(105.0 - P.fall_f_per_gal * 3.0)
        )

    def test_never_warmer_than_the_draw_left_it_nor_below_the_lower(self):

        assert zone_after_draw_f(self._left(40.0), 140.0, 120.0) == 140.0
        assert zone_after_draw_f(self._left(-40.0), 140.0, 92.0) == 92.0

    def test_the_cold_regions_heat_is_withheld_from_it(self):
        """Heat the compressor put into a cold bottom is no hot water
        above the zone: withheld, it is not counted."""

        warm = self._left(5.0, cold_gal=30.0, cold_f=95.0)
        withheld = warm.withheld_btu(EP)
        per_gal = 8.34 * (53.56 + 0.485 * 140.0 - 70.0)
        assert zone_after_draw_f(warm, 140.0, 60.0) == pytest.approx(
            105.0 + P.fall_f_per_gal * (5.0 - withheld / per_gal)
        )

    def test_the_zone_mixes_down_faster_the_less_is_left(self):
        """The water above the rising front mixes, so
        the zone falls ``zone_mix_f_per_gal · exp(-left / zone_mix_gal)``
        °F per delivered gallon before the empty point, integrated over
        the draw's gallons, from where the draw found it."""

        s, lam = EP.zone_mix_f_per_gal, EP.zone_mix_gal

        def fall(left: float, gal: float) -> float:
            return 140.0 - zone_mixed_f(
                self._left(left), gal, 140.0, 140.0, 60.0
            )

        assert fall(30.0, 4.0) == pytest.approx(
            s * lam * (math.exp(-30.0 / lam) - math.exp(-34.0 / lam))
        )
        assert 0.0 < fall(40.0, 4.0) < fall(20.0, 4.0) < fall(5.0, 4.0)
        # Past the empty point, the rate at it, per gallon.
        assert fall(-6.0, 2.0) == pytest.approx(s * 2.0)
        # Across it: its rate over the gallons before, ``s`` after.
        assert fall(-1.0, 3.0) == pytest.approx(
            s * lam * (1.0 - math.exp(-2.0 / lam)) + s * 1.0
        )

    def test_mixing_is_the_same_in_one_draw_or_several(self):
        """The rate is integrated over the gallons, so a draw split into
        pieces at one zone comes out where the whole of it does."""

        whole = zone_mixed_f(self._left(10.0), 8.0, 140.0, 140.0, 60.0)
        half = zone_mixed_f(self._left(14.0), 4.0, 140.0, 140.0, 60.0)
        both = zone_mixed_f(self._left(10.0), 4.0, half, 140.0, 60.0)
        assert both == pytest.approx(whole)

    def test_mixing_never_warms_the_zone_nor_takes_it_below_the_lower(
        self,
    ):

        # The draw's own response is colder than the mixing: it stands.
        assert zone_mixed_f(self._left(40.0), 2.0, 140.0, 130.0, 60.0) == (
            130.0
        )
        assert zone_mixed_f(self._left(-40.0), 30.0, 140.0, 141.0, 120.0) == (
            120.0
        )
        assert zone_mixed_f(self._left(5.0), 0.0, 140.0, 141.0, 60.0) == (141.0)

    def test_where_the_served_point_is_spent_it_is_still_over_the_line(
        self,
    ):

        per_gal = 8.34 * (delivery_f(140.0) - 70.0)
        spent = Booked(EP.empty_btu, 1.0, 70.0)
        assert booked_deliverable(spent, 140.0, 90.0, P0).gal == 0.0
        assert zone_after_draw_f(spent, 140.0, 90.0) == pytest.approx(
            105.0
            + P.fall_f_per_gal * (EP.empty_btu - EP.zone_empty_btu) / per_gal
        )


class TestTheLowerZoneThroughADraw:
    """The lower zone after a draw is the front's,
    from where the booked cold region puts it against the lower probe
    (``lower_probe_gal`` up, ``front_width_gal`` wide)."""

    @staticmethod
    def _region(cold_gal: float, cold_f: float = 70.0) -> Booked:
        return Booked(30000.0, 1.0, 70.0, cold_gal=cold_gal, cold_f=cold_f)

    def test_the_probe_reads_hot_until_the_front_reaches_it(self):

        start = EP.lower_probe_gal - EP.front_width_gal / 2.0
        assert front_start_gal(EP) == start == 9.0
        assert front_share(0.0, EP) == front_share(start, EP) == 1.0
        assert front_share(EP.lower_probe_gal, EP) == 0.5
        assert front_share(start + EP.front_width_gal, EP) == 0.0
        assert front_share(63.2, EP) == 0.0
        # Linear across the front.
        assert front_share(17.0, EP) == pytest.approx(0.75)

    def test_a_draw_below_the_front_leaves_the_zone_alone(self):

        before = self._region(0.0)
        after = before.drawn(10.0, 140.0, EP)
        assert 0.0 < after.cold_gal < 9.0
        assert lower_after_draw_f(before, after, 140.0, 131.0, EP) == 131.0

    def test_one_across_it_takes_the_share_it_crossed(self):

        before = self._region(15.0)
        after = before.drawn(10.0, 140.0, EP)
        crossed = front_share(15.0, EP) - front_share(after.cold_gal, EP)
        assert 0.1 < crossed < 0.5
        assert lower_after_draw_f(before, after, 140.0, 127.0, EP) == (
            pytest.approx(127.0 - crossed * (140.0 - after.cold_f))
        )

    def test_never_below_the_region_nor_warmed(self):

        before = self._region(30.0)
        after = before.drawn(20.0, 140.0, EP)
        assert lower_after_draw_f(before, after, 140.0, 80.0, EP) == 70.0
        # A zone already colder than the region stays where it was.
        assert lower_after_draw_f(before, after, 140.0, 65.0, EP) == 65.0

    def test_it_reads_the_front_and_settles_to_the_colder(self):

        # The front far below the probe: the zone stays at 130 and
        # settles to the calibrated response priced from where it was
        # settling (128 less a 6 °F drop).
        assert settled_lower_f(130.0, 122.0, 72.0) == (130.0, 8.0)
        # The front past the calibrated level: it is the settled one.
        assert settled_lower_f(120.0, 124.0, 72.0) == (120.0, 0.0)
        # Never below the inlet, nor above the front.
        assert settled_lower_f(90.0, 60.0, 72.0) == (90.0, 18.0)
        assert settled_lower_f(65.0, 50.0, 72.0) == (65.0, 0.0)

    def test_one_time_constant(self):

        tau = EP.front_settle_min
        assert unsettled_after_f(8.0, 0.0, tau) == 8.0
        assert unsettled_after_f(8.0, tau, tau) == pytest.approx(
            8.0 / 2.718281828
        )
        assert unsettled_after_f(0.0, 30.0, tau) == 0.0

    def test_the_bound_holds_while_the_front_cannot_reach(self):

        before = self._region(3.0)
        assert front_cannot_move(before, 5.9, EP)
        assert not front_cannot_move(before, 6.0, EP)
        # Wherever it says so, no draw of those gallons moves the zone.
        for gal in (1.0, 3.0, 5.9):
            for upper in (105.0, 125.0, 150.0):
                after = before.drawn(gal, upper, EP)
                assert (
                    lower_after_draw_f(before, after, upper, 120.0, EP) == 120.0
                )


class TestTheDeliveredLine:
    """The probe is not at the tap. The cold front reaches it first, and
    the water above it still leaves hot: one measured bath's tub spout
    crossed 105 °F 7.3 gal after the upper probe did, a gauge on the
    valve 5.3. Every answer is at the delivered line, the probe's plus
    the lag."""

    @staticmethod
    def _left(gal: float, upper: float = 141.0) -> Booked:
        """A book with ``gal`` delivered gallons left on the probe's
        line at ``upper`` (negative: drawn that far past it)."""

        per_gal = 8.34 * (delivery_f(upper) - 70.0)
        return Booked(EP.empty_btu + gal * per_gal, 1.0, 70.0)

    def test_the_lag_is_the_one_measurement_rounded_down(self):
        # Provisional, n = 1: the lower of the spout's 7.3 and the
        # gauge's 5.3. (09-21 14:08's > 2.4 is no geometric bound: an
        # element heated the lag volume.)
        assert LAG == 5.0 < 5.3 < 7.32

    def test_the_answer_is_the_probe_lines_plus_the_lag(self):

        b = self._left(12.0)
        assert booked_deliverable(b, 141.0, 140.0, P0).gal == 12.0
        assert booked_deliverable(b, 141.0, 140.0).gal == 12.0 + LAG

    def test_past_the_probe_line_the_lag_counts_down(self):

        b = self._left(-2.0)
        assert booked_deliverable(b, 141.0, 140.0, P0).gal == 0.0
        assert booked_deliverable(b, 141.0, 140.0).gal == LAG - 2.0
        assert booked_deliverable(self._left(-LAG - 1.0), 141.0, 140.0).gal == 0

    def test_a_probe_below_the_line_has_spent_the_probe_line(self):
        """The probe reading under the line says its line is spent,
        whatever the book says: the lag is what is left at most, less
        what the book says went past it."""

        assert booked_deliverable(self._left(4.0), 103.0, 90.0).gal == LAG
        assert booked_deliverable(
            self._left(-2.0, 103.0), 103.0, 90.0
        ).gal == pytest.approx(LAG - 2.0, abs=0.05)

    def test_without_a_book_a_probe_below_the_line_is_empty(self):
        """Nothing says how far past its line the draw went."""
        assert deliverable(104.9, 104.0).gal == 0.0
        u, lo, g = min(EVIDENCE, key=lambda e: e[0])
        assert deliverable(u, lo).gal == pytest.approx(g + LAG, abs=0.05)

    def test_colder_than_all_evidence_promises_nothing(self):
        """The lag rides on a probe line the evidence
        vouches for. 2026-04-14 04:02 the upper element lifted a spent
        top back to 105.4 °F: with no book that state must answer 0,
        not the lag."""
        d = deliverable(105.2, 95.0)
        assert d.colder_than_evidence and d.gal == 0.0

    def test_the_full_tank_floor_carries_the_lag_once(self):
        """35.7 gal on the probe's line, 40.7 delivered."""
        d = deliverable(141.08, 141.26, setpoint_f=141.8)
        assert d.gal == pytest.approx(35.7 + LAG, abs=0.05) == 40.7

    def test_the_cold_lower_cap_is_on_the_probe_line_not_the_delivered(
        self,
    ):
        """The cap is the evidence's, on the probe's line; the lag
        comes after it."""
        u, lo = 150.0, 99.5
        assert demonstrated_gal(u, lo) > P.cold_lower_cap_gal
        d = deliverable(u, lo)
        assert d.thermocline_unlocated
        assert d.gal == pytest.approx(P.cold_lower_cap_gal + LAG, abs=0.05)

    def test_capped_at_observed_volume_reads_the_probe_line(self):
        """``at_observed_max`` says the evidence ran out: its largest
        volume on the probe's line, not the delivered answer."""
        below = [
            e
            for e in EVIDENCE
            if OBSERVED_MAX_GAL - LAG <= e[2] < OBSERVED_MAX_GAL
        ]
        assert below
        u, lo, _ = max(below, key=lambda e: e[2])
        d = deliverable(u, lo)
        assert d.gal >= OBSERVED_MAX_GAL
        assert not d.at_observed_max
        assert deliverable(*FULL).at_observed_max

    def test_between_the_lines_the_delivery_is_at_the_line_not_under(self):

        b = self._left(-2.0, 103.0)
        assert delivery_temp_f(b, 103.0) == DEPLETION_THRESHOLD_F
        # A zone above the line reads as itself.
        assert delivery_temp_f(self._left(-2.0), 141.0) == 141.0
        # Past the lag it falls.
        spent = self._left(-LAG - 1.0, 103.0)
        assert delivery_temp_f(spent, 103.0) < DEPLETION_THRESHOLD_F

    def test_past_the_lag_it_falls_from_the_line_not_to_the_zone(self):
        """The delivered water is warmer than the probe, so once the lag
        is spent it falls from the line per gallon, not straight to the
        zone the probe reads (the measured bath's spout crossed 105 °F
        with the probe near 94.5)."""

        just = self._left(-LAG - 0.1, 103.0)
        assert delivery_temp_f(just, 103.0) == pytest.approx(
            105.0 - P.fall_f_per_gal * 0.1, abs=0.01
        )
        far = self._left(-LAG - 3.0, 100.0)
        assert delivery_temp_f(far, 100.0) == pytest.approx(
            105.0 - P.fall_f_per_gal * 3.0, abs=0.01
        )
        # With no lag the probe is the delivery, and bounds it.
        assert delivery_temp_f(self._left(-0.1, 103.0), 103.0, P0) == 103.0

    def test_without_a_book_the_zone_holds_at_the_line_for_the_lag(self):
        """Without a book the depletion view is on the same delivered
        line as ``deliverable_gal``."""

        assert zone_delivery_f(110.0, None) == 110.0
        assert zone_delivery_f(103.0, 0.0) == DEPLETION_THRESHOLD_F
        assert zone_delivery_f(103.0, LAG - 0.1) == DEPLETION_THRESHOLD_F
        assert zone_delivery_f(103.0, LAG + 0.5) == pytest.approx(104.0)
        # Never below the zone.
        assert zone_delivery_f(103.0, LAG + 10.0) == 103.0
        assert zone_delivery_f(103.0, 0.0, P0) == 103.0

    @pytest.mark.parametrize("p", [P, P0], ids=["lag", "no_lag"])
    @pytest.mark.parametrize("upper", [103.0, 120.0, 138.0])
    def test_the_delivery_and_the_gallons_agree_across_both_lines(
        self, upper, p
    ):

        for tenth in range(-120, 60, 3):
            b = self._left(tenth / 10.0, upper)
            gal = booked_deliverable(b, upper, 95.0, p).gal
            below = delivery_temp_f(b, upper, p) < DEPLETION_THRESHOLD_F
            assert below == (gal == 0.0), (upper, tenth, gal)
