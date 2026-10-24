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
from typing import Any

import pytest

pytest.importorskip("pandas")

from _sim_site import (  # type: ignore[import-not-found]  # test helper
    DEPLETION_THRESHOLD_F,
    EP,
    Booked,
    compressor_btu,
    deliverable_from_heat,
    delivery_f,
    element_btu,
    full_tank,
    standby_btu,
    tank_max_btu,
    zone_after_draw_f,
    zone_mixed_f,
)

from nwp500.sim import delivery as rd
from nwp500.sim.params import ReadinessParams

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
#: The example evidence 30 gal higher: above what the probes say, so it
#: answers.
TALL = replace(P, evidence=tuple((u, lo, g + 30.0) for u, lo, g in EVIDENCE))
TALL_MAX_GAL = OBSERVED_MAX_GAL + 30.0


def deliverable(
    upper: float,
    lower: float,
    p: ReadinessParams | None = None,
    **kw: Any,
) -> rd.Deliverable:
    return rd.deliverable(upper, lower, P if p is None else p, ep=EP, **kw)


def booked_deliverable(
    booked: Booked,
    upper: float,
    lower: float,
    p: ReadinessParams | None = None,
) -> rd.Deliverable:
    return rd.booked_deliverable(
        booked, upper, lower, P if p is None else p, EP
    )


def delivery_temp_f(
    booked: Booked,
    upper: float,
    p: ReadinessParams | None = None,
    *,
    lower_f: float | None = None,
) -> float:
    return rd.delivery_temp_f(
        booked, upper, P if p is None else p, EP, lower_f=lower_f
    )


def zone_delivery_f(
    upper: float, past: float | None, p: ReadinessParams | None = None
) -> float:
    return rd.zone_delivery_f(upper, past, P if p is None else p)


def demonstrated_gal(upper: float, lower: float) -> float:
    return rd.demonstrated_gal(upper, lower, EVIDENCE)


def probes_gal(upper: float, lower: float) -> float:
    return rd.probes_gal(upper, lower, P, EP)


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


def _step(
    u: float = 141.8,
    lo: float = 141.8,
    flow: float = 0.0,
    comp: bool = False,
    el: bool = False,
    s: float = 10.0,
) -> Step:
    return Step(u, lo, flow, comp, el, s)


def _apply(b: Booked, st: Step) -> Booked:
    """One recorded step: the draw, the heat in, and standby to a 65 °F
    ambient."""
    h = st.s / 3600.0
    if st.flow > DRAW_GPM:
        b = b.drawn(st.flow * st.s / 60.0, st.u, EP)
    heat = compressor_btu(h, 65.0, EP) if st.comp else 0.0
    if st.el:
        heat += element_btu(h, EP)
    b = b.heated(heat)
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


def _bath(gal: float = 30.0) -> Booked:
    """A full 141.8 °F tank that has just run a bath of ``gal``."""
    n = round(gal * 2)  # 3 GPM over 10 s steps: half a gallon each
    steps = [_step(141.0, 141.0 - i * 0.1, flow=3.0) for i in range(n)]
    return _booked([*FULL_TANK, *steps])


class TestDeliverable:
    def test_the_probes_answer_above_the_evidence(self) -> None:
        d = deliverable(*FULL)
        assert probes_gal(*FULL) > OBSERVED_MAX_GAL
        assert d.gal == pytest.approx(probes_gal(*FULL) + LAG, abs=0.05)
        assert d.basis == "evidence" and not d.at_observed_max

    def test_evidence_above_the_probes_answers_to_its_largest(self) -> None:
        d = deliverable(*FULL, TALL)
        assert d.gal == pytest.approx(TALL_MAX_GAL + LAG, abs=0.05)
        assert d.at_observed_max

    def test_below_the_threshold_nothing_is_deliverable(self) -> None:
        assert deliverable(DEPLETION_THRESHOLD_F - 0.1, 104.0).gal == 0.0

    def test_a_state_colder_than_every_evidence_draw_is_zero(self) -> None:
        coldest = min(u for u, _, _ in EVIDENCE)
        assert demonstrated_gal(coldest - 0.1, 150.0) == 0.0

    def test_a_cold_lower_probe_is_not_capped(self) -> None:
        """The probes place the heat whatever the lower one reads."""
        for upper, lower in ((141.26, 89.6), (147.0, 95.0), (128.0, 99.0)):
            d = deliverable(upper, lower)
            probe = max(
                demonstrated_gal(upper, lower), probes_gal(upper, lower)
            )
            assert probe > 6.5
            assert d.gal == pytest.approx(probe + LAG, abs=0.05)

    def test_a_stratified_tank_reads_its_probes_heat(self) -> None:
        """A drawdown from 136.4/111.4 °F delivered 31.1 gal; the
        probes' heat says 34.5 with the lag."""
        bare = replace(P, evidence=())
        d = deliverable(136.4, 111.4, bare)
        assert d.basis == "probes"
        assert d.gal == pytest.approx(34.5, abs=0.05)
        heat = full_tank(136.4, 111.4, 70.0, EP).heat_btu
        assert d.gal == pytest.approx(
            deliverable_from_heat(heat, 136.4, 70.0) + LAG, abs=0.05
        )

    def test_the_book_is_not_capped(self) -> None:
        """From the book the cold lower probe does not cap the answer.
        (38,000 BTU: under the 40,586 a whole tank at 147 °F can hold.)"""

        full = deliverable_from_heat(38000.0, 147.0, 70.0)
        e = deliverable(147.0, 95.0, heat_btu=38000.0, inlet_f=70.0)
        assert e.basis == "energy"
        assert e.gal == pytest.approx(full + LAG, abs=0.05)

    @pytest.mark.parametrize("fixed", [110.0, 125.0, 140.0])
    def test_a_warmer_tank_never_delivers_less(self, fixed: float) -> None:
        steps = [100.0 + 2.0 * i for i in range(26)]
        by_upper = [demonstrated_gal(u, fixed) for u in steps]
        by_lower = [demonstrated_gal(fixed, lo) for lo in steps]
        assert by_upper == sorted(by_upper)
        assert by_lower == sorted(by_lower)

    def test_a_uniform_tank_reads_all_its_heat(self) -> None:
        """2026-09-28 14:41 PDT, a tank just off a recovery to
        141.8 °F, 0.18 °F under the evidence's 33.4 gal step: a 22.4 gal
        bath then left the upper probe at 140.2. Its probes' heat
        answers, with nothing taken off."""
        assert demonstrated_gal(141.08, 141.26) == 25.1
        d = deliverable(141.08, 141.26, P0)
        heat = full_tank(141.08, 141.26, 70.0, EP).heat_btu
        assert d.basis == "evidence"
        assert d.gal == pytest.approx(
            deliverable_from_heat(heat, 141.08, 70.0), abs=0.05
        )
        assert d.gal == pytest.approx(49.2, abs=0.05)

    def test_the_book_is_read_no_higher_than_the_tank_can_hold(self) -> None:
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

    def test_the_probes_above_the_evidence_are_not_its_cap(self) -> None:
        """``at_observed_max`` says the evidence ran out; the probes
        answering above it are not the evidence."""
        d = deliverable(146.0, 146.0)
        assert d.gal > OBSERVED_MAX_GAL
        assert not d.at_observed_max

    def test_every_evidence_point_answers_for_itself(self) -> None:
        for u, lo, g in EVIDENCE:
            assert demonstrated_gal(u, lo) == g


class TestBookkeeping:
    def test_a_full_tank_is_known_exactly(self) -> None:
        b = _booked(FULL_TANK)
        assert b.heat_btu == pytest.approx(TANK_BTU_PER_F * 71.8)
        assert b.anchor_age_h == 0.0

    def test_a_full_tank_delivers_about_48_gallons(self) -> None:
        """The calibration's answer for a 141.8 °F tank; a 30.5 gal bath
        is ready with room to spare."""
        b = _booked(FULL_TANK)
        gal = deliverable_from_heat(b.heat_btu, 141.8, 70.0)
        assert 44.0 < gal < 53.0

    def test_a_draw_takes_what_the_valve_delivers(self) -> None:
        """One minute at 2 GPM from a 140 °F tank: 2 gal at the valve's
        121.5 °F, from a 70 °F inlet."""
        draw = [_step(140.0, 140.0, flow=2.0) for _ in range(6)]
        b = _booked(
            [_step(140.0, 140.0, comp=True), _step(140.0, 140.0), *draw]
        )
        expected = TANK_BTU_PER_F * 70.0 - 2.0 * 8.34 * (121.46 - 70.0)
        assert b.heat_btu == pytest.approx(expected, rel=1e-3)

    def test_the_bath_the_probes_cannot_see_is_counted(self) -> None:
        """After a 30 gal draw the probes can read 141/90, which the
        evidence cannot place. The book knows the heat left."""
        bath = [_step(141.0, 141.0 - i * 0.2, flow=3.0) for i in range(60)]
        b = _booked([*FULL_TANK, *bath])
        full = deliverable_from_heat(TANK_BTU_PER_F * 71.8, 141.8, 70.0)
        left = deliverable_from_heat(b.heat_btu, 141.0, 70.0)
        assert full - left == pytest.approx(30.0, abs=1.5)


class TestAllTheHeatIsDrawable:
    """The book holds none of its heat back: the compressor's and the
    elements' count in full, cold bottom or not."""

    #: The heat a delivered gallon takes from a 141 °F tank.
    PER_GAL = 8.34 * (53.56 + 0.485 * 141.0 - 70.0)

    def test_compressor_heat_after_a_draw_counts_in_full(self) -> None:
        """2026-03-31: after a bath the heat pump lifted the lower zone
        82 -> 98 °F while the upper held near 137. All of its heat is
        drawable."""
        b = _bath(30.0)
        hour = [_step(141.0, 90.0, comp=True)] * 360
        after = b
        for st in hour:
            after = _apply(after, st)
        heat = compressor_btu(1.0, 65.0, EP) - standby_btu(
            1.0, 141.0, 90.0, 65.0, EP
        )
        assert after.heat_btu == pytest.approx(b.heat_btu + heat)
        assert after.deliverable_gal(141.0) - b.deliverable_gal(
            141.0
        ) == pytest.approx(heat / self.PER_GAL, abs=0.01)
        assert booked_deliverable(after, 141.0, 98.0).gal - (
            booked_deliverable(b, 141.0, 82.0).gal
        ) == pytest.approx(heat / self.PER_GAL, abs=0.1)

    def test_the_upper_elements_heat_counts_in_full(self) -> None:
        """2026-04-14: six minutes of the upper element lifted the upper
        probe 126 -> 141 °F over a cold bottom: 1,757 BTU, about four
        delivered gallons."""
        b = _bath(30.0)
        run = _step(141.0, 90.0, el=True, s=360.0)
        gained = _apply(b, run).deliverable_gal(141.0) - b.deliverable_gal(
            141.0
        )
        heat = EP.element_w * 3.412 * 0.1
        assert gained == pytest.approx(heat / self.PER_GAL, abs=0.2)

    def test_the_booked_answer_is_all_its_heat(self) -> None:

        b = _bath(30.0).heated(4000.0)
        d = booked_deliverable(b, 141.0, 90.0)
        assert d.gal == pytest.approx(b.deliverable_gal(141.0) + LAG, abs=0.05)
        assert (
            d.gal
            == deliverable(
                141.0, 90.0, heat_btu=b.heat_btu, inlet_f=b.inlet_f
            ).gal
        )


class TestWhenItRunsOut:
    """The delivery temperature reads the same state as
    ``deliverable_gal``, so the two agree on whether it has run out."""

    def test_the_delivery_reads_the_heat_the_tank_can_hold(self) -> None:
        """The clamp holds for the delivery temperature too, so
        zero gallons and a delivery under the line still go together."""

        # 26,000 BTU booked; a whole tank at 112 °F holds 22,137.
        b = Booked(26000.0, 1.0, 70.0)
        capped = booked_deliverable(b, 112.0, 100.0, P0).gal
        assert capped < b.deliverable_gal(112.0) - 5.0
        for tenth in range(0, 400, 7):
            state = b.drawn(tenth / 10.0, 112.0)
            gal = booked_deliverable(state, 112.0, 100.0, P0).gal
            temp = delivery_temp_f(state, 112.0, P0, lower_f=100.0)
            assert (temp < 105.0) == (gal == 0.0), (tenth, gal)

    def test_while_there_is_drawable_heat_it_is_the_upper_zone(self) -> None:

        assert delivery_temp_f(_bath(10.0), 139.0) == 139.0

    def test_spent_it_falls_below_the_line_and_on_per_gallon(self) -> None:

        b = _bath(30.0)
        # Past the probe's line by the lag: the delivered line.
        left = b.deliverable_gal(141.0) + LAG
        at_line = b.drawn(left + 0.1, 141.0)
        past = b.drawn(left + 3.0, 141.0)
        assert 104.0 < delivery_temp_f(at_line, 141.0) < 105.0
        assert delivery_temp_f(past, 141.0) == pytest.approx(
            105.0 - P.fall_f_per_gal * 3.0, abs=0.3
        )
        # No colder than the inlet.
        far = b.drawn(left + 40.0, 141.0)
        assert delivery_temp_f(far, 141.0) == pytest.approx(far.inlet_f)

    def test_it_agrees_with_the_gallons_on_whether_the_tank_is_empty(
        self,
    ) -> None:

        b = _bath(20.0)
        for tenth in range(0, 400, 7):
            state = b.drawn(tenth / 10.0, 138.0)
            gal = booked_deliverable(state, 138.0, 95.0).gal
            below = delivery_temp_f(state, 138.0) < DEPLETION_THRESHOLD_F
            assert below == (gal == 0.0), (tenth, gal)


class TestTheZoneThroughADraw:
    """The upper zone after a draw reads the book too, against the
    zone's own empty point (12,636 BTU), which centres the crossings;
    the delivery keeps the served one, which calls them early."""

    @staticmethod
    def _left(gal: float) -> Booked:
        """``gal`` delivered gallons above the zone's empty point at a
        140 °F zone."""

        per_gal = 8.34 * (delivery_f(140.0) - 70.0)
        return Booked(EP.zone_empty_btu + gal * per_gal, 1.0, 70.0)

    def test_the_zone_point_is_the_refit_one_and_after_the_served(self) -> None:
        assert EP.zone_empty_btu == 12636.0 < EP.empty_btu

    def test_two_degrees_per_gallon_left_over_the_line(self) -> None:

        assert zone_after_draw_f(self._left(5.0), 140.0, 90.0) == (
            pytest.approx(105.0 + P.fall_f_per_gal * 5.0)
        )
        assert zone_after_draw_f(self._left(0.0), 140.0, 90.0) == (
            pytest.approx(105.0)
        )
        assert zone_after_draw_f(self._left(-3.0), 140.0, 90.0) == (
            pytest.approx(105.0 - P.fall_f_per_gal * 3.0)
        )

    def test_never_warmer_than_the_draw_left_it_nor_below_the_lower(
        self,
    ) -> None:

        assert zone_after_draw_f(self._left(40.0), 140.0, 120.0) == 140.0
        assert zone_after_draw_f(self._left(-40.0), 140.0, 92.0) == 92.0

    def test_the_zone_mixes_down_faster_the_less_is_left(self) -> None:
        """The water above the rising front mixes, so
        the zone falls ``zone_mix_f_per_gal · exp(-left / zone_mix_gal)``
        °F per delivered gallon before the empty point, integrated over
        the draw's gallons, from where the draw found it."""

        s, lam = EP.zone_mix_f_per_gal, EP.zone_mix_gal

        def fall(left: float, gal: float) -> float:
            mixed: float = zone_mixed_f(
                self._left(left), gal, 140.0, 140.0, 60.0
            )
            return 140.0 - mixed

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

    def test_mixing_is_the_same_in_one_draw_or_several(self) -> None:
        """The rate is integrated over the gallons, so a draw split into
        pieces at one zone comes out where the whole of it does."""

        whole = zone_mixed_f(self._left(10.0), 8.0, 140.0, 140.0, 60.0)
        half = zone_mixed_f(self._left(14.0), 4.0, 140.0, 140.0, 60.0)
        both = zone_mixed_f(self._left(10.0), 4.0, half, 140.0, 60.0)
        assert both == pytest.approx(whole)

    def test_mixing_never_warms_the_zone_nor_takes_it_below_the_lower(
        self,
    ) -> None:

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
    ) -> None:

        per_gal = 8.34 * (delivery_f(140.0) - 70.0)
        spent = Booked(EP.empty_btu, 1.0, 70.0)
        assert booked_deliverable(spent, 140.0, 90.0, P0).gal == 0.0
        assert zone_after_draw_f(spent, 140.0, 90.0) == pytest.approx(
            105.0
            + P.fall_f_per_gal * (EP.empty_btu - EP.zone_empty_btu) / per_gal
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

    def test_the_lag_is_the_one_measurement_rounded_down(self) -> None:
        # Provisional, n = 1: the lower of the spout's 7.3 and the
        # gauge's 5.3. (09-21 14:08's > 2.4 is no geometric bound: an
        # element heated the lag volume.)
        assert LAG == 5.0 < 5.3 < 7.32

    def test_the_answer_is_the_probe_lines_plus_the_lag(self) -> None:

        b = self._left(12.0)
        assert booked_deliverable(b, 141.0, 140.0, P0).gal == 12.0
        assert booked_deliverable(b, 141.0, 140.0).gal == 12.0 + LAG

    def test_past_the_probe_line_the_lag_counts_down(self) -> None:

        b = self._left(-2.0)
        assert booked_deliverable(b, 141.0, 140.0, P0).gal == 0.0
        assert booked_deliverable(b, 141.0, 140.0).gal == LAG - 2.0
        assert booked_deliverable(self._left(-LAG - 1.0), 141.0, 140.0).gal == 0

    def test_a_probe_below_the_line_has_spent_the_probe_line(self) -> None:
        """The probe reading under the line says its line is spent,
        whatever the book says: the lag is what is left at most, less
        what the book says went past it."""

        assert booked_deliverable(self._left(4.0), 103.0, 90.0).gal == LAG
        assert booked_deliverable(
            self._left(-2.0, 103.0), 103.0, 90.0
        ).gal == pytest.approx(LAG - 2.0, abs=0.05)

    def test_without_a_book_a_probe_below_the_line_is_empty(self) -> None:
        """Nothing says how far past its line the draw went."""
        assert deliverable(104.9, 104.0).gal == 0.0
        assert deliverable(104.9, 104.0, replace(P, evidence=())).gal == 0.0

    def test_at_the_line_the_lag_is_left(self) -> None:
        """A probe line with no heat above the empty point still has
        the lag above it: the probe has not crossed."""
        assert probes_gal(105.2, 95.0) == 0.0
        assert deliverable(105.2, 95.0).gal == LAG
        assert deliverable(105.2, 95.0, replace(P, evidence=())).gal == LAG

    def test_the_probes_carry_the_lag_once(self) -> None:
        """49.2 gal on the probe's line, 54.2 delivered."""
        d = deliverable(141.08, 141.26)
        assert deliverable(141.08, 141.26, P0).gal == pytest.approx(49.2)
        assert d.gal == pytest.approx(49.2 + LAG, abs=0.05) == 54.2

    def test_capped_at_observed_volume_reads_the_probe_line(self) -> None:
        """``at_observed_max`` says the evidence ran out: its largest
        volume on the probe's line, not the delivered answer."""
        below = [
            e
            for e in EVIDENCE
            if OBSERVED_MAX_GAL - LAG <= e[2] < OBSERVED_MAX_GAL
        ]
        assert below
        u, lo, g = max(below, key=lambda e: e[2])
        d = deliverable(u, lo, TALL)
        assert d.gal == pytest.approx(g + 30.0 + LAG, abs=0.05)
        assert d.gal >= TALL_MAX_GAL
        assert not d.at_observed_max
        assert deliverable(*FULL, TALL).at_observed_max

    def test_between_the_lines_the_delivery_is_at_the_line_not_under(
        self,
    ) -> None:

        b = self._left(-2.0, 103.0)
        assert delivery_temp_f(b, 103.0) == DEPLETION_THRESHOLD_F
        # A zone above the line reads as itself.
        assert delivery_temp_f(self._left(-2.0), 141.0) == 141.0
        # Past the lag it falls.
        spent = self._left(-LAG - 1.0, 103.0)
        assert delivery_temp_f(spent, 103.0) < DEPLETION_THRESHOLD_F

    def test_past_the_lag_it_falls_from_the_line_not_to_the_zone(self) -> None:
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

    def test_without_a_book_the_zone_holds_at_the_line_for_the_lag(
        self,
    ) -> None:
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
        self, upper: float, p: ReadinessParams
    ) -> None:

        for tenth in range(-120, 60, 3):
            b = self._left(tenth / 10.0, upper)
            gal = booked_deliverable(b, upper, 95.0, p).gal
            below = delivery_temp_f(b, upper, p) < DEPLETION_THRESHOLD_F
            assert below == (gal == 0.0), (upper, tenth, gal)


class TestTheReviewOfDepletion:
    def test_a_draw_at_the_windows_onset_counts_its_cold_side(self) -> None:
        """110 °F before the onset, 100 °F just after a draw there, 110
        °F at the window's end: the dip past the tolerance is the
        window's."""
        from datetime import UTC, datetime, timedelta

        from nwp500.sim.engine import PathPoint

        t0 = datetime(2026, 10, 4, 19, tzinfo=UTC)
        points = [
            PathPoint(t0, 110.0, 100.0, 140.0, False, 0.0),
            PathPoint(t0, 100.0, 95.0, 140.0, False, 0.0),
            PathPoint(
                t0 + timedelta(minutes=5), 110.0, 100.0, 140.0, False, 0.0
            ),
        ]
        judged = rd.depletion(
            points,
            t0,
            t0 + timedelta(minutes=5),
            [p.upper_f for p in points],
            P,
        )
        assert judged.min_f == 100.0
        assert judged.depleted
