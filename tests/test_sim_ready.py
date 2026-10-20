"""Time to ready: the bath and shower answers and the time to
bath-ready by mode (``nwp500.sim.ready``).

Ported with the code. The source's readiness defaulted to one
installation's evidence; the library's has none, so ``P`` carries
``EXAMPLE_EVIDENCE`` and the wrappers pass it as the source's defaults
did.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("pandas")

from _sim_site import EP

from nwp500.sim import delivery as rd
from nwp500.sim.params import ElementParams, ReadinessParams
from nwp500.sim.ready import (
    ALWAYS,
    Recovery,
    TankNow,
    whole_showers,
)
from nwp500.sim.ready import (
    assess as _port_assess,
)

NOW = datetime(2026, 9, 21, 20, 0, tzinfo=UTC)
EVIDENCE = rd.EXAMPLE_EVIDENCE
OBSERVED_MAX_GAL = rd.observed_max_gal(EVIDENCE)
P = rd.with_example_evidence(ReadinessParams())
LAG = P.delivered_lag_gal
P0 = replace(P, delivered_lag_gal=0.0)
#: Hot enough to dominate every evidence point.
FULL = (150.0, 150.0)


def deliverable(upper, lower, p=None, **kw):
    return rd.deliverable(upper, lower, P if p is None else p, ep=EP, **kw)


def _tank(upper=FULL[0], lower=FULL[1], **kw) -> TankNow:
    base = {"drawing": False, "element_on": False, "tou_window": False}
    return TankNow(upper_f=upper, lower_f=lower, **{**base, **kw})


def _assess(tank, recovery=Recovery("unavailable"), **kw):
    args = {
        "bath_gal": 30.5,
        "bath_source": "configured",
        "shower_gal": 12.0,
        "shower_source": "weekly_forecast",
        "valid_s": 900.0,
        "params": P,
        "element_params": ElementParams(),
        "book_params": EP,
    }
    return _port_assess(NOW, tank, recovery, **{**args, **kw})


class TestWholeShowers:
    def test_it_floors(self) -> None:
        assert whole_showers(2.99) == 2

    def test_a_float_just_under_a_whole_number_is_that_number(self) -> None:
        assert whole_showers(1.9999999999) == 2

    def test_never_negative(self) -> None:
        assert whole_showers(0.0) == 0


class TestAssess:
    def test_colder_than_every_evidence_draw_says_so(self) -> None:
        """A warm tank below all the evidence answers 0 for want of
        evidence, and must say that rather than look empty."""
        a = _assess(_tank(118.0, 110.0))
        # No lag either: the evidence vouches for no probe line.
        assert a["deliverable_gal"] == 0.0
        assert "colder_than_all_evidence" in a["reasons"]
        assert "colder_than_all_evidence" not in _assess(_tank())["reasons"]

    def test_an_idle_heater_has_no_time_and_says_why(self) -> None:
        a = _assess(_tank(125.0, 110.0), Recovery("idle"))
        assert a["bath"]["ready_in_minutes"] is None
        assert "heating_not_triggered" in a["reasons"]

    def test_every_v1_answer_is_low_confidence_and_says_why(self) -> None:
        a = _assess(_tank())
        assert a["status"] == "low_confidence"
        assert a["reasons"][: len(ALWAYS)] == list(ALWAYS)

    def test_a_full_tank_runs_a_bath_now(self) -> None:
        a = _assess(_tank())
        assert a["bath"]["ready"] is True
        assert a["bath"]["ready_in_minutes"] == 0.0
        assert a["bath"]["ready_at"] == NOW
        assert a["bath"]["margin_gal"] == pytest.approx(
            OBSERVED_MAX_GAL + LAG - 30.5, abs=0.05
        )

    def test_a_stale_book_on_a_tank_at_its_setpoint_runs_the_bath(self) -> None:
        """2026-09-28 14:41 PDT: with no book the evidence said 25.1 gal and
        not ready; the floor at the setpoint says ready, now, in every
        mode."""
        a = _assess(_tank(141.08, 141.26), setpoint_f=141.8, params=P0)
        assert "no_heat_book" in a["reasons"]
        assert a["deliverable_gal"] == pytest.approx(35.7)
        assert a["bath"]["ready"] is True
        assert {r["ready_in_minutes"] for r in a["bath"]["by_mode"]} == {0.0}

    def test_a_running_compressor_withholds_the_floor_now(self) -> None:
        a = _assess(
            _tank(141.08, 141.26, compressor_on=True),
            setpoint_f=141.8,
            params=P0,
        )
        assert a["deliverable_gal"] == 25.1
        assert a["bath"]["ready"] is False

    def test_a_projected_recovery_has_the_floor_only_at_its_end(self) -> None:
        """The floor waits for the heater to stop, in a projection as
        in the live state: a 35 gal bath the evidence never covers is
        ready when the recovery ends, not as it passes setpoint - 2."""
        pts = [
            (
                NOW + timedelta(minutes=i),
                139.0 + 2.8 * i / 20,
                138.0 + 3.8 * i / 20,
            )
            for i in range(21)
        ]
        rec = Recovery("ok", pts, input_wh=[0.0] + [30.0] * 20)
        a = _assess(
            _tank(139.0, 138.0, compressor_on=True),
            rec,
            setpoint_f=141.8,
            bath_gal=35.0,
            params=P0,
        )
        assert a["bath"]["ready"] is False
        assert _modes(a)["heat_pump"]["ready_in_minutes"] == 20.0

    def test_ready_is_decided_on_the_numbers_it_reports(self) -> None:
        """A bath 0.04 gal over the deliverable volume is reported at the
        same one-decimal value; it must read ready with a zero margin,
        not show two equal numbers and say not ready."""
        gal = round(OBSERVED_MAX_GAL + LAG, 1)
        a = _assess(_tank(), bath_gal=gal + 0.04, bath_source="request")
        assert a["bath"]["volume_gal"] == gal
        assert a["bath"]["ready"] is True
        assert a["bath"]["margin_gal"] == 0.0

    def test_near_an_evidence_step_it_says_the_probe_decides(self) -> None:
        u, lo, g = max(EVIDENCE, key=lambda e: e[2])
        on_step = _assess(_tank(u + 0.5, lo + 0.5), bath_gal=g + LAG)
        assert on_step["bath"]["ready"] is True
        assert "bath_ready_within_probe_resolution" in on_step["reasons"]
        clear = _assess(_tank(), bath_gal=5.0)
        assert "bath_ready_within_probe_resolution" not in clear["reasons"]

    def test_time_to_ready_is_the_first_state_that_covers_the_bath(
        self,
    ) -> None:
        points = [
            (NOW + timedelta(minutes=10 * i), 125.0 + 2.5 * i, 110.0 + 4 * i)
            for i in range(10)
        ]
        a = _assess(_tank(125.0, 110.0), Recovery("ok", points))
        first = next(
            i
            for i, (_, u, lo) in enumerate(points)
            if deliverable(u, lo).gal >= 30.5
        )
        # Scored on a one-minute grid between the trajectory's points, so
        # it lands inside the step that first covers the bath.
        assert a["bath"]["ready"] is False
        assert 10.0 * (first - 1) < a["bath"]["ready_in_minutes"] <= 10 * first

    def test_a_recovery_that_never_covers_it_says_so(self) -> None:
        points = [(NOW + timedelta(minutes=10), 126.0, 112.0)]
        a = _assess(_tank(125.0, 110.0), Recovery("ok", points))
        assert a["bath"]["ready_in_minutes"] is None
        assert "bath_not_reached_by_full_recovery" in a["reasons"]

    def test_inside_a_tou_window_the_bath_waits_for_its_end(self) -> None:
        points = [(NOW + timedelta(minutes=10), 126.0, 112.0)]
        a = _assess(
            _tank(125.0, 110.0, tou_window=True),
            Recovery("ok", points, tou_capped=True),
        )
        assert a["bath"]["ready_in_minutes"] is None
        assert "bath_waits_for_tou_window_end" in a["reasons"]
        assert "bath_not_reached_by_full_recovery" not in a["reasons"]

    def test_vacation_has_no_time_to_ready(self) -> None:
        a = _assess(_tank(120.0, 95.0), Recovery("not_scheduled"))
        assert a["bath"]["ready_in_minutes"] is None
        assert "heating_not_scheduled" in a["reasons"]

    def test_a_request_volume_is_labelled_as_one(self) -> None:
        a = _assess(_tank(), bath_source="request", bath_gal=20.0)
        assert a["bath"]["volume_source"] == "request"
        assert "bath_volume_inferred" not in a["reasons"]

    def test_live_conditions_become_reasons(self) -> None:
        a = _assess(
            _tank(drawing=True, element_on=True, tou_window=True),
            shower_source="default",
        )
        for reason in (
            "draw_in_progress",
            "element_running",
            "tou_window_in_force",
            "shower_volume_default",
        ):
            assert reason in a["reasons"]


def _hp(minutes=200, step=10, wh=300.0):
    """A heat-pump recovery from 125/110 to full, linear in time."""
    n = minutes // step
    pts = [
        (
            NOW + timedelta(minutes=step * i),
            125.0 + (141.8 - 125.0) * i / n,
            110.0 + (141.8 - 110.0) * i / n,
        )
        for i in range(n + 1)
    ]
    return Recovery("ok", pts, input_wh=[0.0] + [wh] * n)


def _modes(a):
    return {r["mode"]: r for r in a["bath"]["by_mode"]}


class TestByMode:
    """Time to bath-ready per heating mode."""

    def test_all_four_modes_in_the_contracts_order(self) -> None:
        a = _assess(_tank(125.0, 110.0), _hp(), setpoint_f=141.8)
        assert [r["mode"] for r in a["bath"]["by_mode"]] == [
            "heat_pump",
            "energy_saver",
            "high_demand",
            "electric",
        ]

    def test_the_heat_pump_row_is_the_bath_answer(self) -> None:
        a = _assess(_tank(125.0, 110.0), _hp(), setpoint_f=141.8)
        hp = _modes(a)["heat_pump"]
        assert hp["ready_in_minutes"] == a["bath"]["ready_in_minutes"]
        assert hp["ready_in_minutes"] is not None

    def test_an_element_is_never_slower_than_the_heat_pump_alone(self) -> None:
        m = _modes(_assess(_tank(125.0, 110.0), _hp(), setpoint_f=141.8))
        for mode in ("energy_saver", "high_demand"):
            assert (
                m[mode]["ready_in_minutes"]
                <= m["heat_pump"]["ready_in_minutes"]
            )

    def test_the_element_heats_the_upper_zone_the_heat_pump_leaves(
        self,
    ) -> None:
        """With the upper zone the limit, High Demand and Energy Saver are
        faster than the heat pump because their element heats it.
        Deleting that heating makes them equal, which this must catch."""
        n = 20
        slow_upper = Recovery(
            "ok",
            [
                (
                    NOW + timedelta(minutes=10 * i),
                    120.0 + 3.0 * i / n,
                    139.0 + 2.8 * i / n,
                )
                for i in range(n + 1)
            ],
            input_wh=[0.0] + [300.0] * n,
        )
        m = _modes(_assess(_tank(120.0, 139.0), slow_upper, setpoint_f=141.8))
        assert m["high_demand"]["ready_in_minutes"] is not None
        hp = m["heat_pump"]["ready_in_minutes"]
        for mode in ("high_demand", "energy_saver"):
            got = m[mode]["ready_in_minutes"]
            assert hp is None or got < hp

    def test_element_rows_carry_the_element_models_caveats(self) -> None:
        m = _modes(_assess(_tank(125.0, 110.0), _hp(), setpoint_f=141.8))
        assert m["heat_pump"]["reasons"] == []
        for mode in ("energy_saver", "high_demand", "electric"):
            assert "element_model_small_n" in m[mode]["reasons"]
        assert (
            "upper_zone_dips_during_the_lower_phase" in m["electric"]["reasons"]
        )

    def test_element_energy_is_counted_at_cop_one(self) -> None:
        """High Demand's energy is the heat pump's input to that minute
        plus 5,148 W of element for as long as the element runs."""
        m = _modes(_assess(_tank(125.0, 110.0), _hp(), setpoint_f=141.8))
        hp, hd = m["heat_pump"], m["high_demand"]
        hp_kwh_per_min = 300.0 / 10.0 / 1000.0
        assert hp["energy_kwh"] == pytest.approx(
            hp_kwh_per_min * hp["ready_in_minutes"], abs=0.01
        )
        t = hd["ready_in_minutes"]
        ep = ElementParams()
        # From the on-edge, its lag included (2026-10-02).
        element_min = min(
            t, ep.upper_dead_time_min + (141.8 - 125.0) / ep.upper_f_per_min
        )
        assert hd["energy_kwh"] == pytest.approx(
            hp_kwh_per_min * t + 5.148 * element_min / 60.0, abs=0.01
        )

    def test_energy_saver_charges_its_element_to_the_off_point(self) -> None:
        """Energy Saver's element stops 1.62 °F short of the setpoint
        (2026-10-02): its energy stops there, while the zone
        coasts on to the setpoint at the same rate, so a ready time past
        the off point costs no more element."""
        m = _modes(_assess(_tank(125.0, 110.0), _hp(), setpoint_f=141.8))
        es = m["energy_saver"]
        t = es["ready_in_minutes"]
        ep = ElementParams()
        off_min = (
            ep.upper_dead_time_min + (141.8 - 1.62 - 125.0) / ep.upper_f_per_min
        )
        assert t > off_min
        assert es["energy_kwh"] == pytest.approx(
            300.0 / 10.0 / 1000.0 * t + 5.148 * off_min / 60.0, abs=0.01
        )

    def test_electric_needs_no_heat_pump_trajectory(self) -> None:
        m = _modes(
            _assess(
                _tank(125.0, 110.0), Recovery("unavailable"), setpoint_f=141.8
            )
        )
        assert m["heat_pump"]["ready_in_minutes"] is None
        assert m["energy_saver"]["ready_in_minutes"] is None
        assert m["electric"]["ready_in_minutes"] is not None
        assert m["electric"]["energy_kwh"] > 0

    def test_a_recovery_ending_between_grid_points_is_still_scored(
        self,
    ) -> None:
        """Electric from 140/138 finishes 4.9 min in: upper element 2.1
        min (its 1.21-min lag and 0.9 of rise), lower 2.8. The finished
        tank covers a bath of what it delivers even though no whole
        minute does."""
        full = deliverable(141.8, 141.8, setpoint_f=141.8).gal
        assert full >= 30.5
        m = _modes(
            _assess(
                _tank(140.0, 138.0),
                Recovery("unavailable"),
                setpoint_f=141.8,
                bath_gal=full,
            )
        )
        e = m["electric"]["ready_in_minutes"]
        assert e is not None and 4.0 < e < 5.0

    def test_inside_a_tou_window_only_the_heat_pump_is_reachable(self) -> None:
        m = _modes(
            _assess(
                _tank(125.0, 110.0, tou_window=True), _hp(), setpoint_f=141.8
            )
        )
        assert m["heat_pump"]["reachable_now"]
        assert not any(
            m[x]["reachable_now"]
            for x in ("energy_saver", "high_demand", "electric")
        )

    def test_vacation_reaches_nothing(self) -> None:
        m = _modes(
            _assess(
                _tank(125.0, 110.0), Recovery("not_scheduled"), setpoint_f=141.8
            )
        )
        assert not any(r["reachable_now"] for r in m.values())
        assert all(r["ready_in_minutes"] is None for r in m.values())

    def test_a_ready_bath_is_ready_in_every_mode(self) -> None:
        m = _modes(_assess(_tank(), setpoint_f=141.8))
        assert all(r["ready_in_minutes"] == 0.0 for r in m.values())

    def test_no_setpoint_no_element_projection(self) -> None:
        m = _modes(_assess(_tank(125.0, 110.0), _hp(), setpoint_f=None))
        assert m["heat_pump"]["ready_in_minutes"] is not None
        assert m["electric"]["ready_in_minutes"] is None
