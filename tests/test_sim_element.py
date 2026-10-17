"""The element model for the modes that run an element."""

import pytest

from nwp500.sim.params import ElementParams
from nwp500.sim.physics.element import (
    mode_plan,
    mode_recovery,
)

#: Round numbers, so an expected minute count is obvious by hand.
P = ElementParams(
    element_w=6000.0,
    upper_f_per_min=2.0,
    lower_f_per_min=1.0,
    upper_starts_below_setpoint_f=4.0,
    # Electric and High Demand now carry separate entry thresholds
    # (measured 2026-09-20/21), and most of the tests below drive High
    # Demand as a generic element mode.  Both are pinned to the round
    # number so an expected minute count stays obvious by hand; the
    # *defaults* are what differ, and `TestTheModesAreNotMerged`
    # asserts that.
    high_demand_starts_below_setpoint_f=4.0,
    # No lag, so a minute count is the deficit over the rate;
    # `TestTheDeadTime` holds the lag.
    upper_dead_time_min=0.0,
)


class TestHighDemand:
    def test_the_upper_element_runs_to_the_setpoint(self):
        r = mode_recovery("HIGH_DEMAND", 120.0, 90.0, 140.0, params=P)
        assert r.upper_setpoint_minutes == pytest.approx(10.0)
        assert r.element_minutes == pytest.approx(10.0)

    def test_the_heat_pump_decides_when_it_is_slower(self):
        r = mode_recovery(
            "HIGH_DEMAND", 120.0, 90.0, 140.0, hp_lower_minutes=180.0, params=P
        )
        assert r.full_minutes == pytest.approx(180.0)

    def test_the_element_decides_when_it_is_slower(self):
        r = mode_recovery(
            "HIGH_DEMAND", 100.0, 135.0, 140.0, hp_lower_minutes=5.0, params=P
        )
        assert r.full_minutes == pytest.approx(20.0)

    def test_without_the_heat_pump_the_full_recovery_is_unknown(self):
        r = mode_recovery("HIGH_DEMAND", 120.0, 90.0, 140.0, params=P)
        assert r.full_minutes is None
        assert "hp_lower_not_given" in r.confidence_reasons

    def test_a_ready_threshold_is_reached_before_the_setpoint(self):
        r = mode_recovery(
            "HIGH_DEMAND", 100.0, 90.0, 140.0, ready_upper_f=116.0, params=P
        )
        assert r.upper_ready_minutes == pytest.approx(8.0)
        assert r.upper_setpoint_minutes == pytest.approx(20.0)

    def test_an_upper_zone_already_ready_is_ready_now(self):
        r = mode_recovery(
            "HIGH_DEMAND", 130.0, 90.0, 140.0, ready_upper_f=116.0, params=P
        )
        assert r.upper_ready_minutes == 0.0


class TestWhenTheElementDoesNotStart:
    """The element starts only once the zone is far enough below."""

    def test_just_inside_the_edge_it_stays_off(self):
        r = mode_recovery(
            "HIGH_DEMAND", 137.0, 120.0, 140.0, ready_upper_f=139.0, params=P
        )
        assert r.element_minutes == 0.0
        assert r.upper_ready_minutes is None
        assert r.upper_setpoint_minutes is None, (
            "None, not 0: the zone is short of the setpoint and will not "
            "get there"
        )
        assert "upper_element_does_not_start" in r.confidence_reasons

    def test_just_outside_the_edge_it_runs(self):
        r = mode_recovery("HIGH_DEMAND", 136.0, 120.0, 140.0, params=P)
        assert r.upper_setpoint_minutes == pytest.approx(2.0)

    def test_already_at_the_setpoint_is_zero_not_none(self):
        r = mode_recovery("HIGH_DEMAND", 141.0, 120.0, 140.0, params=P)
        assert r.upper_setpoint_minutes == 0.0
        assert r.upper_ready_minutes == 0.0
        assert r.element_minutes == 0.0

    def test_a_target_above_the_setpoint_is_never_reached(self):
        """The element stops at the setpoint, so 145 never arrives."""
        r = mode_recovery(
            "HIGH_DEMAND", 120.0, 90.0, 140.0, ready_upper_f=145.0, params=P
        )
        assert r.upper_ready_minutes is None
        assert "ready_target_above_setpoint" in r.confidence_reasons


class TestElectric:
    def test_upper_then_lower_never_together(self):
        r = mode_recovery("ELECTRIC", 120.0, 100.0, 140.0, params=P)
        assert r.upper_setpoint_minutes == pytest.approx(10.0)
        # lower: 40 °F at 1 °F/min, after the upper element finishes
        assert r.full_minutes == pytest.approx(10.0 + 40.0)
        assert r.element_minutes == pytest.approx(50.0)

    def test_a_lower_zone_already_at_setpoint_adds_nothing(self):
        r = mode_recovery("ELECTRIC", 120.0, 141.0, 140.0, params=P)
        assert r.full_minutes == pytest.approx(10.0)

    def test_the_lower_element_still_runs_when_the_upper_does_not(self):
        r = mode_recovery("ELECTRIC", 137.0, 100.0, 140.0, params=P)
        assert r.upper_setpoint_minutes is None
        assert r.full_minutes == pytest.approx(40.0)
        assert r.element_minutes == pytest.approx(40.0)


#: P with a dead time long enough to carry Energy Saver's whole off
#: deficit in transit (2 °F against the default 1.62), so its zone
#: still coasts to the setpoint; every upper time is a minute later.
P_LAG = ElementParams(
    element_w=6000.0,
    upper_f_per_min=2.0,
    lower_f_per_min=1.0,
    upper_starts_below_setpoint_f=4.0,
    high_demand_starts_below_setpoint_f=4.0,
    upper_dead_time_min=1.0,
)


class TestEnergySaver:
    def test_a_switch_with_the_tank_short_boosts_the_upper_zone(self):
        r = mode_recovery(
            "ENERGY_SAVER",
            120.0,
            90.0,
            140.0,
            hp_lower_minutes=200.0,
            params=P_LAG,
        )
        assert r.upper_setpoint_minutes == pytest.approx(11.0)
        assert r.full_minutes == pytest.approx(200.0)
        assert "energy_saver_later_starts_not_modelled" in r.confidence_reasons

    def test_it_uses_the_same_rate_as_the_other_modes(self):
        """History gives one rate for every mode, not one per mode."""
        es = mode_recovery(
            "ENERGY_SAVER",
            120.0,
            90.0,
            140.0,
            hp_lower_minutes=1.0,
            params=P_LAG,
        )
        hd = mode_recovery(
            "HIGH_DEMAND",
            120.0,
            90.0,
            140.0,
            hp_lower_minutes=1.0,
            params=P_LAG,
        )
        assert es.upper_setpoint_minutes == hd.upper_setpoint_minutes


class TestWhereTheElementStops:
    """Energy Saver's upper element switches off short of the setpoint
    (1.62 °F, raw off-edges, 2026-10-02); the others at it. The element's
    run and energy end at the off point; the zone coasts on by at most
    the off deficit and at most the heat still in transit."""

    #: An off point of 2 °F at 2 °F/min after a 1-min dead time: what is
    #: in transit at the off-edge is 2 °F, the whole off deficit, and the
    #: coast takes one minute. The entry threshold is kept above the off
    #: point, as the params require.
    OFF = ElementParams(
        element_w=6000.0,
        upper_f_per_min=2.0,
        lower_f_per_min=1.0,
        energy_saver_entry_deficit_f=2.5,
        energy_saver_bracket_lower_f=2.2,
        energy_saver_upper_off_below_setpoint_f=2.0,
        upper_dead_time_min=1.0,
    )

    def test_an_off_point_at_or_past_entry_is_rejected(self):
        with pytest.raises(ValueError, match="below energy_saver_entry"):
            ElementParams(energy_saver_upper_off_below_setpoint_f=1.8)
        with pytest.raises(ValueError):
            ElementParams(energy_saver_upper_off_below_setpoint_f=-0.1)

    def test_a_run_just_past_entry_coasts_to_the_setpoint(self):
        # Entry at 2.5 °F short, off at 2: the element lifts the zone
        # 0.5 after its dead time and stops; the 2 °F its dead time put
        # in is still in transit, so the zone coasts on to the setpoint,
        # as the short clean stints did (rises of 0.18-1.44 °F coasted
        # 1.8-2.2).
        r = mode_recovery("ENERGY_SAVER", 137.5, 90.0, 140.0, params=self.OFF)
        assert r.upper_element_minutes == pytest.approx(1.25)
        assert r.element_kwh == pytest.approx(1.25 / 60.0 * 6.0)
        assert r.upper_end_f == pytest.approx(140.0)
        assert r.upper_end_minutes == pytest.approx(2.25)
        assert r.upper_setpoint_minutes == pytest.approx(2.25)
        assert (
            "upper_zone_coasts_short_of_the_setpoint"
            not in r.confidence_reasons
        )
        plan = mode_plan("ENERGY_SAVER", 137.5, 90.0, 140.0, params=self.OFF)
        assert plan.end_upper_f == pytest.approx(140.0)
        ready = mode_recovery(
            "ENERGY_SAVER",
            137.5,
            90.0,
            140.0,
            ready_upper_f=139.0,
            params=self.OFF,
        )
        assert ready.upper_ready_minutes == pytest.approx(1.75)

    def test_the_coast_is_capped_at_what_is_in_transit(self):
        # Half the dead time: 1 °F in transit, under the 2 °F off
        # deficit. The zone coasts 1 °F and ends short of the setpoint;
        # nothing is credited that was not charged.
        short = ElementParams(
            element_w=6000.0,
            upper_f_per_min=2.0,
            lower_f_per_min=1.0,
            energy_saver_entry_deficit_f=2.5,
            energy_saver_bracket_lower_f=2.2,
            energy_saver_upper_off_below_setpoint_f=2.0,
            upper_dead_time_min=0.5,
        )
        r = mode_recovery("ENERGY_SAVER", 120.0, 90.0, 140.0, params=short)
        assert r.upper_element_minutes == pytest.approx(9.5)
        assert r.upper_end_f == pytest.approx(139.0)
        assert r.upper_end_minutes == pytest.approx(10.0)
        assert r.upper_setpoint_minutes is None
        assert "upper_zone_coasts_short_of_the_setpoint" in r.confidence_reasons
        # A target the coast does not reach never arrives.
        miss = mode_recovery(
            "ENERGY_SAVER",
            120.0,
            90.0,
            140.0,
            ready_upper_f=139.5,
            params=short,
        )
        assert miss.upper_ready_minutes is None
        # With no dead time nothing is in transit, and nothing coasts.
        none = mode_recovery(
            "ENERGY_SAVER",
            120.0,
            90.0,
            140.0,
            params=ElementParams(upper_f_per_min=2.0, upper_dead_time_min=0.0),
        )
        assert none.upper_end_f == pytest.approx(140.0 - 1.62)

    def test_the_default_entry_run_coasts_to_the_setpoint(self):
        # The served numbers: entry 1.8 short, off 1.62, 2.43 °F in
        # transit, so a run started at entry lifts the zone 0.18 °F and
        # coasts the last 1.62 to the setpoint. Energy Saver runs that
        # lifted it 0.54, 1.26 and 1.44 °F coasted to 0.18-0.54 over.
        p = ElementParams()
        r = mode_recovery("ENERGY_SAVER", 140.0, 90.0, 141.8)
        assert r.upper_end_f == pytest.approx(141.8)
        minutes = p.upper_dead_time_min + 0.18 / p.upper_f_per_min
        assert r.upper_element_minutes == pytest.approx(minutes)
        assert r.upper_setpoint_minutes == pytest.approx(
            p.upper_dead_time_min + 1.8 / p.upper_f_per_min
        )
        assert r.element_kwh == pytest.approx(minutes / 60.0 * 5.148, rel=1e-3)

    def test_a_long_run_earns_the_full_coast(self):
        r = mode_recovery("ENERGY_SAVER", 120.0, 90.0, 140.0, params=self.OFF)
        assert r.upper_end_f == pytest.approx(140.0)
        assert r.upper_setpoint_minutes == pytest.approx(11.0)
        assert (
            "upper_zone_coasts_short_of_the_setpoint"
            not in r.confidence_reasons
        )

    def test_the_measured_off_point_is_the_default(self):
        assert ElementParams().energy_saver_upper_off_below_setpoint_f == (
            pytest.approx(1.62)
        )

    def test_energy_saver_runs_and_is_charged_to_its_off_point(self):
        r = mode_recovery("ENERGY_SAVER", 120.0, 90.0, 140.0, params=self.OFF)
        assert r.upper_element_minutes == pytest.approx(10.0)
        assert r.element_minutes == pytest.approx(10.0)
        assert r.element_kwh == pytest.approx(10.0 / 60.0 * 6.0)

    def test_the_zone_still_reaches_the_setpoint_on_the_same_clock(self):
        # Time to ready is unchanged: the coast keeps the fitted rate.
        r = mode_recovery(
            "ENERGY_SAVER",
            120.0,
            90.0,
            140.0,
            ready_upper_f=138.0,
            params=self.OFF,
        )
        assert r.upper_setpoint_minutes == pytest.approx(11.0)
        assert r.upper_ready_minutes == pytest.approx(10.0)

    def test_high_demand_and_electric_run_to_the_setpoint(self):
        hd = mode_recovery("HIGH_DEMAND", 120.0, 90.0, 140.0, params=self.OFF)
        assert hd.upper_element_minutes == pytest.approx(11.0)
        assert hd.element_minutes == pytest.approx(11.0)
        el = mode_recovery("ELECTRIC", 120.0, 130.0, 140.0, params=self.OFF)
        assert el.upper_element_minutes == pytest.approx(11.0)
        assert el.element_minutes == pytest.approx(11.0 + 10.0)

    def test_the_plan_ends_at_the_off_point_with_the_coast_credited(self):
        plan = mode_plan(
            "ENERGY_SAVER",
            120.0,
            90.0,
            140.0,
            params=self.OFF,
            slot_minutes=5.0,
        )
        assert plan.element_minutes == pytest.approx(10.0)
        assert plan.element_kwh == pytest.approx(1.0)
        assert sum(s.element_wh for s in plan.profile) == pytest.approx(1000.0)
        assert plan.end_minute == pytest.approx(10.0)
        # The probe peaks at about the setpoint after the off-edge.
        assert plan.end_upper_f == pytest.approx(140.0)

    def test_a_switch_back_during_the_coast_does_not_cut_it(self):
        plan = mode_plan(
            "ENERGY_SAVER",
            120.0,
            90.0,
            140.0,
            params=self.OFF,
            switch_back_after_minutes=10.5,
        )
        assert "truncated_by_switch_back" not in plan.confidence_reasons
        assert plan.upper_setpoint_minutes == pytest.approx(11.0)
        assert plan.end_upper_f == pytest.approx(140.0)

    def test_a_switch_back_before_the_off_point_gets_no_coast(self):
        plan = mode_plan(
            "ENERGY_SAVER",
            120.0,
            90.0,
            140.0,
            params=self.OFF,
            switch_back_after_minutes=5.0,
        )
        assert plan.element_minutes == pytest.approx(5.0)
        assert plan.end_upper_f == pytest.approx(128.0)
        assert plan.upper_setpoint_minutes is None


class TestTheDeadTime:
    """The upper zone is held for the dead time after the upper
    element's on-edge while the element draws its power (2026-10-02):
    every upper-element run is that much longer and charged for it,
    every time the zone reaches that much later, and the heat it puts
    in is the coast, credited once."""

    #: P's round numbers with a one-minute dead time: 2 °F in transit.
    LAG = ElementParams(
        element_w=6000.0,
        upper_f_per_min=2.0,
        lower_f_per_min=1.0,
        upper_starts_below_setpoint_f=4.0,
        high_demand_starts_below_setpoint_f=4.0,
        energy_saver_entry_deficit_f=2.5,
        energy_saver_bracket_lower_f=2.2,
        energy_saver_upper_off_below_setpoint_f=2.0,
        upper_dead_time_min=1.0,
    )

    def test_a_negative_or_unset_lag_is_rejected(self):
        with pytest.raises(ValueError, match="upper_dead_time_min"):
            ElementParams(upper_dead_time_min=-0.1)
        with pytest.raises(ValueError, match="upper_dead_time_min"):
            ElementParams(upper_dead_time_min=float("nan"))
        assert ElementParams(upper_dead_time_min=0.0).upper_dead_time_min == 0

    def test_every_upper_time_is_the_lag_later_and_charged(self):
        r = mode_recovery(
            "HIGH_DEMAND",
            120.0,
            90.0,
            140.0,
            ready_upper_f=130.0,
            params=self.LAG,
        )
        assert r.upper_element_minutes == pytest.approx(11.0)
        assert r.upper_setpoint_minutes == pytest.approx(11.0)
        assert r.upper_ready_minutes == pytest.approx(6.0)
        assert r.element_minutes == pytest.approx(11.0)
        assert r.element_kwh == pytest.approx(11.0 / 60.0 * 6.0)

    def test_a_tank_already_there_waits_for_no_lag(self):
        r = mode_recovery(
            "HIGH_DEMAND",
            141.0,
            90.0,
            140.0,
            ready_upper_f=130.0,
            params=self.LAG,
        )
        assert r.upper_ready_minutes == 0.0
        assert r.element_kwh == 0.0

    def test_the_zone_does_not_move_inside_the_lag(self):
        plan = mode_plan(
            "HIGH_DEMAND",
            120.0,
            90.0,
            140.0,
            params=self.LAG,
            switch_back_after_minutes=0.8,
        )
        assert plan.end_upper_f == pytest.approx(120.0)
        assert plan.element_kwh == pytest.approx(0.8 / 60.0 * 6.0)
        later = mode_plan(
            "HIGH_DEMAND",
            120.0,
            90.0,
            140.0,
            params=self.LAG,
            switch_back_after_minutes=3.0,
        )
        assert later.end_upper_f == pytest.approx(120.0 + 2.0 * 2.0)

    def test_the_lags_heat_is_the_coast_credited_once(self):
        # Entry 2.5 short, off 2: charged 1.25 min, lifted 0.5 during
        # the run; the 2 °F the dead time put in arrives as the coast,
        # and the zone ends at the setpoint, not past it.
        r = mode_recovery("ENERGY_SAVER", 137.5, 90.0, 140.0, params=self.LAG)
        assert r.upper_element_minutes == pytest.approx(1.25)
        assert r.element_kwh == pytest.approx(1.25 / 60.0 * 6.0)
        assert r.upper_end_f == pytest.approx(140.0)
        assert r.upper_end_minutes == pytest.approx(2.25)

    def test_a_long_energy_saver_run_reaches_the_setpoint_lag_late(self):
        r = mode_recovery("ENERGY_SAVER", 120.0, 90.0, 140.0, params=self.LAG)
        assert r.upper_element_minutes == pytest.approx(10.0)
        assert r.upper_setpoint_minutes == pytest.approx(11.0)
        assert r.upper_end_f == pytest.approx(140.0)

    def test_electric_lower_element_has_no_lag(self):
        r = mode_recovery("ELECTRIC", 120.0, 130.0, 140.0, params=self.LAG)
        assert r.upper_element_minutes == pytest.approx(11.0)
        assert r.element_minutes == pytest.approx(11.0 + 10.0)
        assert r.full_minutes == pytest.approx(21.0)


class TestEnergy:
    def test_kwh_follows_the_running_minutes_and_the_fitted_power(self):
        r = mode_recovery("ELECTRIC", 120.0, 100.0, 140.0, params=P)
        assert r.element_kwh == pytest.approx(50.0 / 60.0 * 6.0)

    def test_no_element_is_no_energy(self):
        r = mode_recovery("HIGH_DEMAND", 137.0, 120.0, 140.0, params=P)
        assert r.element_kwh == 0.0


class TestScope:
    def test_a_mode_without_an_element_is_rejected(self):
        with pytest.raises(ValueError, match="not modelled"):
            mode_recovery("HEAT_PUMP", 120.0, 100.0, 140.0)  # type: ignore[arg-type]

    def test_every_result_says_it_is_small_n(self):
        r = mode_recovery("ELECTRIC", 120.0, 100.0, 140.0)
        assert "element_model_small_n" in r.confidence_reasons

    def test_the_defaults_are_the_fitted_terms(self):
        """The rates are history's; the start "threshold" is gone.

        It was 3.8, then 3.6, from the smallest start seen in an
        uncontrolled record — which measures where the tank happened to
        be. Device runs started the element at 9.4, 3.6 and 1.8 °F short,
        and Electric and High Demand park `he_upper_on` at
        the setpoint, so there is no floor above the device's own
        differential. Energy Saver's ~5 °F entry effect is a different
        thing and survives.
        """
        p = ElementParams()
        assert p.element_w == pytest.approx(5148.0)
        # After the lag, from raw run lengths (2026-10-02): 1.66 end to
        # end on the grid before.
        assert p.upper_f_per_min == pytest.approx(2.01)
        assert p.upper_dead_time_min == pytest.approx(1.21)
        assert p.lower_f_per_min == pytest.approx(1.38)
        # Three modes, three brackets, three thresholds, each the top
        # of its own. Electric and High Demand plausibly
        # share one — their brackets overlap in (0.36, 0.54] and they
        # handle `he_upper_on` alike — but that is an inference, and
        # acting on it would promise an element at 0.6 °F that High
        # Demand has never been seen to run.
        assert p.upper_starts_below_setpoint_f == pytest.approx(0.54)
        assert p.start_bracket_lower_f == pytest.approx(0.0)
        assert p.high_demand_starts_below_setpoint_f == pytest.approx(0.72)
        assert p.high_demand_bracket_lower_f == pytest.approx(0.36)
        assert p.energy_saver_entry_deficit_f == pytest.approx(1.8)
        assert p.energy_saver_bracket_lower_f == pytest.approx(1.44)


class TestTheModesAreNotMerged:
    """Each mode's entry threshold is its own observed edge.

    The merge is tempting and was in the model until a code review
    called it what it is: Electric's 0.54 °F applied to a
    mode whose only negative is 0.36 and whose lowest positive is 0.72
    (1.26 until the 2026-09-21 runs). Between those two numbers High
    Demand has never been watched, so the model must not claim to know.
    """

    #: Inside High Demand's bracket and outside Electric's.  If the two
    #: are ever merged onto 0.54 this stops being a disagreement and
    #: these tests fail.
    BETWEEN = 0.63

    def test_electric_starts_between_the_two_thresholds(self):
        r = mode_recovery("ELECTRIC", 140.0 - self.BETWEEN, 120.0, 140.0)
        assert r.element_minutes > 0.0
        assert "upper_element_does_not_start" not in r.confidence_reasons

    def test_high_demand_does_not(self):
        r = mode_recovery("HIGH_DEMAND", 140.0 - self.BETWEEN, 120.0, 140.0)
        assert r.element_minutes == 0.0
        assert "upper_element_does_not_start" in r.confidence_reasons

    def test_high_demand_starts_at_its_own_edge(self):
        """0.72 is the smallest deficit it was actually seen to run at."""
        r = mode_recovery("HIGH_DEMAND", 140.0 - 0.72, 120.0, 140.0)
        assert r.element_minutes > 0.0

    def test_high_demand_starts_where_it_was_seen_to_in_september(self):
        """0.90 and 0.72 °F (2026-09-21); 0.8 was a negative until then."""
        for deficit in (0.90, 0.8):
            r = mode_recovery("HIGH_DEMAND", 140.0 - deficit, 120.0, 140.0)
            assert r.element_minutes > 0.0


# --- mode_plan: pricing and chaining ------------------------------------


def test_the_profile_sums_to_the_recovery_energy():
    """A plan that crosses a tariff boundary is a per-slot sum, so the
    slots must add up to what the recovery says it costs."""
    plan = mode_plan("ELECTRIC", 118.0, 116.0, 140.0)
    total_wh = sum(s.element_wh for s in plan.profile)
    assert total_wh == pytest.approx(plan.recovery.element_kwh * 1000, rel=1e-3)
    assert plan.profile[-1].end_minute == pytest.approx(
        plan.recovery.element_minutes, abs=0.001
    )


def test_slots_are_whole_except_the_last():
    plan = mode_plan("ELECTRIC", 100.0, 100.0, 140.0, slot_minutes=10.0)
    ends = [s.end_minute for s in plan.profile]
    assert ends[:3] == [10.0, 20.0, 30.0]
    assert ends[-1] == pytest.approx(plan.recovery.element_minutes, abs=0.001)


def test_switching_back_early_truncates_the_energy_and_the_tank():
    """The scheduler prices a bounded make-up, not a full recovery,
    and needs the tank it hands back."""
    full = mode_plan("ELECTRIC", 120.0, 118.0, 140.0)
    short = mode_plan(
        "ELECTRIC", 120.0, 118.0, 140.0, switch_back_after_minutes=5.0
    )

    assert short.end_minute == 5.0
    assert sum(s.element_wh for s in short.profile) < sum(
        s.element_wh for s in full.profile
    )
    # The lag, then 2.01 °F/min for the rest of the five minutes.
    assert short.end_upper_f == pytest.approx(
        120.0 + (5 - 1.21) * 2.01, abs=0.01
    )
    assert "truncated_by_switch_back" in short.confidence_reasons


def test_a_switch_back_after_the_recovery_is_not_a_truncation():
    plan = mode_plan(
        "ELECTRIC", 138.0, 139.0, 140.0, switch_back_after_minutes=90.0
    )
    assert "truncated_by_switch_back" not in plan.confidence_reasons


def test_the_upper_zone_never_projects_past_the_setpoint():
    plan = mode_plan(
        "HIGH_DEMAND",
        139.0,
        120.0,
        140.0,
        switch_back_after_minutes=60.0,
        hp_lower_minutes=45.0,
    )
    assert plan.end_upper_f <= 140.0


def test_the_lower_zone_is_left_alone_when_the_heat_pump_owns_it():
    """High Demand and Energy Saver heat the lower zone with the
    compressor, which this module does not model — so it must not
    invent a number for it."""
    for mode in ("HIGH_DEMAND", "ENERGY_SAVER"):
        plan = mode_plan(mode, 120.0, 118.0, 140.0, hp_lower_minutes=50.0)
        assert plan.end_lower_f == 118.0
        assert "lower_zone_not_projected_under_heat_pump" in (
            plan.confidence_reasons
        )


def test_electric_does_project_its_lower_zone():
    plan = mode_plan("ELECTRIC", 139.5, 120.0, 140.0)
    assert plan.end_lower_f == pytest.approx(140.0)
    assert "lower_zone_not_projected_under_heat_pump" not in (
        plan.confidence_reasons
    )


def test_a_tank_already_at_setpoint_costs_nothing():
    plan = mode_plan("ENERGY_SAVER", 141.0, 141.0, 140.0, hp_lower_minutes=0.0)
    assert plan.profile == ()
    assert plan.recovery.element_kwh == 0.0
    assert plan.end_upper_f == 141.0


def test_every_plan_carries_the_small_n_warning():
    plan = mode_plan("ELECTRIC", 120.0, 118.0, 140.0)
    assert "element_model_small_n" in plan.confidence_reasons


def test_a_plan_rejects_nonsense_bounds():
    with pytest.raises(ValueError, match="slot_minutes"):
        mode_plan("ELECTRIC", 120.0, 118.0, 140.0, slot_minutes=0)
    with pytest.raises(ValueError, match="switch_back"):
        mode_plan(
            "ELECTRIC", 120.0, 118.0, 140.0, switch_back_after_minutes=-1.0
        )


def test_electric_warns_that_the_upper_zone_dips():
    """Measured 2026-09-20: once the lower element takes over, the upper
    probe falls — 3.4 °F in that run — before the tank mixes back. A
    readiness answer that assumes the upper zone holds is not safe."""
    plan = mode_plan("ELECTRIC", 120.0, 118.0, 140.0)
    assert "upper_zone_dips_during_the_lower_phase" in (plan.confidence_reasons)


def test_no_dip_warning_when_the_lower_zone_needs_nothing():
    plan = mode_plan("ELECTRIC", 120.0, 141.0, 140.0)
    assert "upper_zone_dips_during_the_lower_phase" not in (
        plan.confidence_reasons
    )


def test_the_heat_pump_modes_do_not_carry_the_dip_warning():
    # Their lower zone is the compressor's, and this was measured under
    # the lower *element*.
    plan = mode_plan("HIGH_DEMAND", 120.0, 118.0, 140.0, hp_lower_minutes=50.0)
    assert "upper_zone_dips_during_the_lower_phase" not in (
        plan.confidence_reasons
    )


def test_electric_starts_the_element_at_the_measured_differential():
    """Measured 2026-09-20: 1.8 °F short and the element came on at
    once. The old 3.6 °F floor would have said it stays off."""
    r = mode_recovery("ELECTRIC", 144.5, 143.6, 146.3)
    assert r.upper_setpoint_minutes is not None
    assert r.element_minutes > 0
    assert "upper_element_does_not_start" not in r.confidence_reasons


def test_high_demand_starts_the_element_just_under_the_setpoint():
    r = mode_recovery("HIGH_DEMAND", 144.5, 120.0, 146.3, hp_lower_minutes=30.0)
    assert r.upper_setpoint_minutes is not None


def test_the_start_threshold_matches_the_sweep():
    """A sweep: off at 0.54 and 1.44 °F, on at 1.80 and 2.16.

    Bracketed on both sides, which is what distinguishes it from the
    3.8 and 5.0 it replaced — those were smallest-observed values with
    no negative observations at all.
    """
    off = mode_recovery(
        "ENERGY_SAVER", 145.0 - 1.44, 120.0, 145.0, hp_lower_minutes=30.0
    )
    assert off.upper_element_minutes is None
    assert "upper_element_does_not_start" in off.confidence_reasons

    on = mode_recovery(
        "ENERGY_SAVER", 145.0 - 1.80, 120.0, 145.0, hp_lower_minutes=30.0
    )
    assert on.upper_element_minutes is not None


def test_a_deficit_inside_the_bracket_says_so():
    """1.44–1.80 °F is where the device's decision actually lives, and
    no run has been made inside it."""
    edge = mode_recovery(
        "ENERGY_SAVER", 145.0 - 1.6, 120.0, 145.0, hp_lower_minutes=30.0
    )
    assert "deficit_inside_the_start_threshold_bracket" in (
        edge.confidence_reasons
    )

    clear = mode_recovery(
        "ENERGY_SAVER", 138.0, 120.0, 146.3, hp_lower_minutes=30.0
    )
    assert "deficit_inside_the_start_threshold_bracket" not in (
        clear.confidence_reasons
    )


def test_a_tank_at_or_above_setpoint_still_needs_no_element():
    """History: 2 of 10 engaged with the tank at or above setpoint, and
    there is nothing for the element to do there anyway."""
    r = mode_recovery(
        "ENERGY_SAVER", 147.0, 120.0, 146.3, hp_lower_minutes=30.0
    )
    assert r.upper_setpoint_minutes == 0.0
    assert r.element_minutes == 0.0


def test_electric_and_energy_saver_do_not_share_a_threshold():
    """Measured 2026-09-20 at the same 0.54 °F deficit: Electric ran the
    element, Energy Saver did not.

    They were briefly modelled with one shared number — in both
    directions — before either was bracketed.
    """
    electric = mode_recovery("ELECTRIC", 141.8 - 0.54, 141.8, 141.8)
    assert electric.upper_setpoint_minutes is not None
    assert electric.element_minutes > 0

    eco = mode_recovery(
        "ENERGY_SAVER", 141.26, 141.8, 141.8, hp_lower_minutes=20.0
    )
    assert eco.upper_setpoint_minutes is None
    assert "upper_element_does_not_start" in eco.confidence_reasons


def test_electric_leaves_the_element_off_above_the_setpoint():
    """The control that brackets Electric from beneath: 1.08 °F above
    setpoint, element off for the whole watch."""
    r = mode_recovery("ELECTRIC", 141.08, 141.8, 140.0)
    assert r.upper_setpoint_minutes == 0.0
    assert r.element_minutes == 0.0


def test_only_energy_saver_gets_the_bracket_warning():
    """Electric's bracket, (0, 0.54], is narrower than the probe's
    0.18 °F resolution, so there is no band to warn about."""
    electric = mode_recovery("ELECTRIC", 140.2, 141.8, 141.8)
    assert "deficit_inside_the_start_threshold_bracket" not in (
        electric.confidence_reasons
    )
    eco = mode_recovery(
        "ENERGY_SAVER", 141.8 - 1.6, 120.0, 141.8, hp_lower_minutes=20.0
    )
    assert "deficit_inside_the_start_threshold_bracket" in (
        eco.confidence_reasons
    )


def test_high_demand_shares_electrics_threshold_not_energy_savers():
    """High Demand stayed off at 0.36 °F and ran at 1.26, then
    at 0.90 and 0.72 (2026-09-21).

    Its bracket, (0.36, 0.72], overlaps Electric's (0, 0.54] only in
    (0.36, 0.54] — so one threshold fits both, and it is not Energy
    Saver's (1.44, 1.80].
    """
    off = mode_recovery(
        "HIGH_DEMAND", 141.8 - 0.36, 120.0, 141.8, hp_lower_minutes=40.0
    )
    assert off.upper_setpoint_minutes is None

    on = mode_recovery(
        "HIGH_DEMAND", 141.8 - 1.26, 120.0, 141.8, hp_lower_minutes=40.0
    )
    assert on.upper_setpoint_minutes is not None

    # Energy Saver declines at a deficit High Demand acts on.
    eco = mode_recovery(
        "ENERGY_SAVER", 141.8 - 1.26, 120.0, 141.8, hp_lower_minutes=40.0
    )
    assert eco.upper_setpoint_minutes is None


def test_each_mode_warns_inside_its_own_bracket():
    hd = mode_recovery(
        "HIGH_DEMAND", 141.8 - 0.45, 120.0, 141.8, hp_lower_minutes=40.0
    )
    assert "deficit_inside_the_start_threshold_bracket" in (
        hd.confidence_reasons
    )
    # 0.45 is nowhere near Energy Saver's band, which is 1.44-1.80.
    eco = mode_recovery(
        "ENERGY_SAVER", 141.8 - 0.45, 120.0, 141.8, hp_lower_minutes=40.0
    )
    assert "deficit_inside_the_start_threshold_bracket" not in (
        eco.confidence_reasons
    )


def test_the_entry_threshold_is_not_the_reengage_threshold():
    """They are different questions and history separates them.

    Every device run measured entry — what happens within a poll of a
    mode switch. In High Demand's steady state the element is on in 2 %
    of minutes 0.36–0.54 °F short and 99 % of minutes over 4 °F short,
    so a mid-stint re-engagement is nearer the 4.1 °F seen there. Nothing here
    projects one; the figure is recorded so the two are not conflated.
    """
    p = ElementParams()
    assert p.upper_starts_below_setpoint_f == pytest.approx(0.54)
    assert p.upper_reengages_below_setpoint_f == pytest.approx(4.1)
    assert p.upper_reengages_below_setpoint_f > (
        p.upper_starts_below_setpoint_f
    )


def test_the_two_mid_stint_figures_are_recorded_with_their_references():
    """A **value** guard, and deliberately not claimed as more.

    Neither figure is consumed by any computation — they are recorded
    so entry and mid-stint are not conflated — so there is no
    behaviour here to protect and this test cannot fail on one. It
    fails when someone edits a literal, which is its whole job.

    What it does encode is that the two are measured against
    *different references*. Energy Saver's is absolute: the
    element tracks `he_upper_on` at 104.9 °F, and the same minutes
    binned by deficit show no step at all. High Demand's is
    setpoint-relative, stepping at 4 °F below. Converting either into
    the other's form is meaningless, so the assertions below are
    written in each one's own units.

    When either value is consumed, replace this with a projection
    test: build a recovery from one and assert it is not reproducible
    from the other.
    """
    p = ElementParams()
    assert p.energy_saver_reengages_at_f == pytest.approx(104.9)
    assert p.upper_reengages_below_setpoint_f == pytest.approx(4.1)
    # Absolute, so it does not move when the setpoint does.
    assert p.energy_saver_reengages_at_f < 130.0
    # Relative, so it is a small gap rather than a tank temperature.
    assert p.upper_reengages_below_setpoint_f < 10.0
