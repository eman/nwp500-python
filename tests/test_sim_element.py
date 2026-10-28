"""A stint in a mode that runs an element (``sim.element_mode``): the
scenario walked with the mode written at its start."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nwp500.sim import (
    Commands,
    ElementModeResult,
    Environment,
    HeaterState,
    History,
    Scenario,
    Schedules,
    Settings,
    TouPeriod,
    Write,
    element_mode,
)
from nwp500.sim.defaults import site_example_params
from nwp500.sim.params import ElementParams, HeaterParams

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
SETPOINT = 141.8
#: The device's minimum setpoint: the upper start threshold at rest,
#: outside a TOU window.
RESTING = 104.9
ELECTRIC, ENERGY_SAVER, HIGH_DEMAND = 2, 3, 4


@pytest.fixture(scope="module")
def params() -> HeaterParams:
    return site_example_params()


def _scenario(
    upper: float, lower: float, *, given: Any = None, **settings: Any
) -> Scenario:
    return Scenario(
        **(given or {}),
        start=T0,
        horizon=timedelta(hours=12),
        tz="UTC",
        state=HeaterState(upper_f=upper, lower_f=lower),
        settings=Settings(
            **{
                "setpoint_f": SETPOINT,
                "hp_lower_on_f": 105.0,
                "hp_upper_on_f": RESTING,
                **settings,
            }
        ),
        history=History(compressor_stopped_at=T0 - timedelta(hours=2)),
        environment=Environment(ambient_f=68.0, humidity=48.0),
    )


def _stint(
    params: HeaterParams,
    mode: int,
    upper: float = 125.0,
    lower: float = 110.0,
    **kw: Any,
) -> ElementModeResult:
    return element_mode(_scenario(upper, lower), params, mode=mode, **kw)


class TestEachMode:
    @pytest.mark.parametrize("mode", [ELECTRIC, ENERGY_SAVER, HIGH_DEMAND])
    def test_the_upper_element_brings_the_top_to_the_setpoint(
        self, params: HeaterParams, mode: int
    ) -> None:
        r = _stint(params, mode)
        assert r.reachable and r.unreachable_reason is None
        assert r.upper_setpoint_minutes is not None
        assert 0.0 < r.upper_setpoint_minutes < 30.0
        assert r.element_kwh > 0.0
        assert "element_model_small_n" in r.reasons

    def test_electric_runs_no_heat_pump_and_hands_over_to_the_lower(
        self, params: HeaterParams
    ) -> None:
        r = _stint(params, ELECTRIC)
        assert r.mode == "electric"
        assert r.heat_pump_kwh == 0.0
        assert r.upper_setpoint_minutes is not None
        assert r.element_minutes > r.upper_setpoint_minutes
        assert r.end_lower_f == pytest.approx(SETPOINT, abs=1.0)
        assert "lower_element_nine_runs" in r.reasons

    @pytest.mark.parametrize("mode", [ENERGY_SAVER, HIGH_DEMAND])
    def test_the_heat_pump_heats_the_rest_alongside(
        self, params: HeaterParams, mode: int
    ) -> None:
        """The lower zone is the heat pump's, walked with it: the
        recovery ends when the heat pump does, long after the
        element."""
        r = _stint(params, mode)
        assert r.heat_pump_kwh is not None and r.heat_pump_kwh > 0.0
        assert r.full_minutes is not None
        assert r.full_minutes > r.element_minutes + 30.0
        assert r.end_lower_f > 135.0

    def test_energy_savers_element_stops_short_of_high_demands(
        self, params: HeaterParams
    ) -> None:
        """1.62 °F short of the setpoint, where High Demand's runs to
        it: a shorter run for the same tank."""
        saver = _stint(params, ENERGY_SAVER)
        demand = _stint(params, HIGH_DEMAND)
        assert saver.element_minutes < demand.element_minutes
        assert saver.element_kwh < demand.element_kwh

    def test_the_energy_is_the_running_minutes_at_the_fitted_power(
        self, params: HeaterParams
    ) -> None:
        r = _stint(params, ELECTRIC)
        assert r.element_kwh == pytest.approx(
            r.element_minutes / 60.0 * params.element.element_w / 1000.0,
            rel=0.01,
        )

    def test_the_end_is_the_walks_tank(self, params: HeaterParams) -> None:
        r = _stint(params, HIGH_DEMAND)
        assert r.full_minutes is not None
        assert r.full_minutes == pytest.approx(r.end_minute, abs=0.05)
        assert r.end_layers_f is not None
        assert min(r.end_layers_f) <= r.end_lower_f <= max(r.end_layers_f)


class TestWhenTheElementDoesNotStart:
    def test_a_tank_at_the_setpoint_needs_no_element(
        self, params: HeaterParams
    ) -> None:
        r = _stint(params, ENERGY_SAVER, upper=SETPOINT + 1.0, lower=SETPOINT)
        assert r.upper_setpoint_minutes == 0.0
        assert r.element_minutes == 0.0 and r.element_kwh == 0.0
        assert "upper_element_does_not_start" not in r.reasons

    def test_short_of_the_entry_deficit_it_says_so(
        self, params: HeaterParams
    ) -> None:
        """Energy Saver stayed off 1.44 °F short (the device sweep) and
        ran at 1.80."""
        off = _stint(params, ENERGY_SAVER, upper=SETPOINT - 1.44)
        assert off.element_minutes == 0.0
        assert "upper_element_does_not_start" in off.reasons
        on = _stint(params, ENERGY_SAVER, upper=SETPOINT - 1.80)
        assert on.element_minutes > 0.0
        assert "upper_element_does_not_start" not in on.reasons


class TestTheModesAreNotMerged:
    """Each mode's entry threshold is its own observed edge: Electric
    0.54 °F, High Demand 0.72, Energy Saver 1.8."""

    #: Inside High Demand's bracket and outside Electric's.
    BETWEEN = 0.63

    def test_electric_starts_between_the_two_thresholds(
        self, params: HeaterParams
    ) -> None:
        r = _stint(params, ELECTRIC, upper=SETPOINT - self.BETWEEN)
        assert r.element_minutes > 0.0

    def test_high_demand_does_not(self, params: HeaterParams) -> None:
        r = _stint(params, HIGH_DEMAND, upper=SETPOINT - self.BETWEEN)
        assert r.element_minutes == 0.0
        assert "upper_element_does_not_start" in r.reasons

    def test_energy_saver_declines_where_high_demand_runs(
        self, params: HeaterParams
    ) -> None:
        """High Demand ran at 1.26 °F short (2026-09-21)."""
        assert _stint(params, HIGH_DEMAND, upper=SETPOINT - 1.26).element_kwh
        assert not _stint(
            params, ENERGY_SAVER, upper=SETPOINT - 1.26
        ).element_kwh

    def test_the_defaults_are_the_device_runs_edges(self) -> None:
        p = ElementParams()
        assert p.upper_starts_below_setpoint_f == pytest.approx(0.54)
        assert p.high_demand_starts_below_setpoint_f == pytest.approx(0.72)
        assert p.energy_saver_entry_deficit_f == pytest.approx(1.8)


class TestTheReadyLevel:
    def test_a_lower_level_is_reached_before_the_setpoint(
        self, params: HeaterParams
    ) -> None:
        r = _stint(params, HIGH_DEMAND, ready_upper_f=130.0)
        assert r.upper_ready_minutes is not None
        assert r.upper_setpoint_minutes is not None
        assert 0.0 < r.upper_ready_minutes < r.upper_setpoint_minutes

    def test_one_already_reached_is_now(self, params: HeaterParams) -> None:
        r = _stint(params, HIGH_DEMAND, ready_upper_f=120.0)
        assert r.upper_ready_minutes == 0.0

    def test_one_above_the_setpoint_says_so(self, params: HeaterParams) -> None:
        r = _stint(params, ENERGY_SAVER, ready_upper_f=SETPOINT + 5.0)
        assert r.upper_ready_minutes is None
        assert "ready_target_above_setpoint" in r.reasons


class TestTheSwitchBack:
    def test_switching_back_early_ends_the_stint(
        self, params: HeaterParams
    ) -> None:
        whole = _stint(params, ELECTRIC)
        cut = _stint(params, ELECTRIC, switch_back_after_minutes=5.0)
        assert cut.end_minute == pytest.approx(5.0)
        assert cut.element_minutes == pytest.approx(5.0, abs=0.1)
        assert cut.element_kwh < whole.element_kwh
        assert cut.end_upper_f < whole.end_upper_f
        assert cut.upper_setpoint_minutes is None
        assert cut.full_minutes is None
        assert "truncated_by_switch_back" in cut.reasons

    def test_one_after_the_recovery_changes_nothing(
        self, params: HeaterParams
    ) -> None:
        whole = _stint(params, ELECTRIC)
        assert whole.full_minutes is not None
        late = _stint(
            params,
            ELECTRIC,
            switch_back_after_minutes=whole.full_minutes + 30.0,
        )
        assert late == whole

    def test_a_negative_one_is_refused(self, params: HeaterParams) -> None:
        with pytest.raises(ValueError, match="switch_back_after_minutes"):
            _stint(params, ELECTRIC, switch_back_after_minutes=-1.0)


class TestTheProfile:
    def test_it_sums_to_the_stints_energy(self, params: HeaterParams) -> None:
        r = _stint(params, HIGH_DEMAND)
        assert sum(s.element_wh for s in r.profile) / 1000.0 == (
            pytest.approx(r.element_kwh, abs=1e-3)
        )
        assert r.heat_pump_kwh is not None
        assert sum(s.heat_pump_wh for s in r.profile) / 1000.0 == (
            pytest.approx(r.heat_pump_kwh, abs=1e-3)
        )

    def test_slots_are_whole_except_the_last(
        self, params: HeaterParams
    ) -> None:
        r = _stint(params, ELECTRIC, slot_minutes=10.0)
        ends = [s.end_minute for s in r.profile]
        assert ends[:-1] == [10.0 * (i + 1) for i in range(len(ends) - 1)]
        assert ends[-1] == pytest.approx(r.end_minute)

    def test_a_tank_with_nothing_to_do_has_none(
        self, params: HeaterParams
    ) -> None:
        r = _stint(params, ELECTRIC, upper=SETPOINT, lower=SETPOINT)
        assert r.profile == ()
        assert r.end_minute == 0.0
        assert (r.end_upper_f, r.end_lower_f) == (SETPOINT, SETPOINT)

    @pytest.mark.parametrize("slot", [0.0, -1.0])
    def test_a_slot_must_be_positive(
        self, params: HeaterParams, slot: float
    ) -> None:
        with pytest.raises(ValueError, match="slot_minutes"):
            _stint(params, ELECTRIC, slot_minutes=slot)

    def test_too_many_slots_are_refused(self, params: HeaterParams) -> None:
        with pytest.raises(ValueError, match="widen slot_minutes"):
            _stint(params, ELECTRIC, slot_minutes=0.001)


def _tou_opening_at(hour: int, minute: int) -> Schedules:
    """TOU on, a peak from ``hour:minute`` to 13:59 UTC every day."""

    def period(h0: int, m0: int, h1: int, m1: int, price: int) -> TouPeriod:
        return TouPeriod(
            season=0xFFF,
            week=0xFE,
            start_hour=h0,
            start_minute=m0,
            end_hour=h1,
            end_minute=m1,
            price_max=price,
        )

    return Schedules(
        tou_enabled=True,
        tou_periods=(
            period(0, 0, hour, minute - 1, 10),
            period(hour, minute, 13, 59, 50),
            period(14, 0, 23, 59, 10),
        ),
    )


class TestWhatEndsTheRecovery:
    @pytest.mark.parametrize("back", [5.0, 10.0, 30.0])
    def test_any_switch_back_before_it_ends_truncates(
        self, params: HeaterParams, back: float
    ) -> None:
        """However the heat pump the switch-back would start falls
        against the stint's end."""
        r = _stint(params, ELECTRIC, switch_back_after_minutes=back)
        assert r.end_minute == pytest.approx(back)
        assert r.full_minutes is None
        assert "truncated_by_switch_back" in r.reasons

    def test_a_window_dropping_the_mode_cuts_it_short(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(125.0, 110.0, given={"schedules": _tou_opening_at(12, 8)})
        r = element_mode(s, params, mode=ELECTRIC)
        assert r.end_minute == pytest.approx(8.0)
        assert r.full_minutes is None
        assert {"element_mode_dropped_projected", "recovery_cut_short"} <= (
            set(r.reasons)
        )

    def test_the_scenarios_own_setpoint_is_the_target(
        self, params: HeaterParams
    ) -> None:
        """A write at the start that lowers the setpoint below the tank:
        it is there already."""
        s = _scenario(
            125.0,
            110.0,
            given={
                "commands": Commands(writes=(Write(at=T0, setpoint_f=120.0),))
            },
        )
        r = element_mode(s, params, mode=HIGH_DEMAND)
        assert r.upper_setpoint_minutes == 0.0
        assert "upper_element_does_not_start" not in r.reasons

    def test_a_ready_level_the_coast_reaches_is_not_flagged(
        self, params: HeaterParams
    ) -> None:
        """The upper zone coasts past the setpoint once the element
        stops."""
        r = _stint(params, HIGH_DEMAND, ready_upper_f=SETPOINT + 0.2)
        assert r.upper_ready_minutes is not None
        assert "ready_target_above_setpoint" not in r.reasons

    def test_the_mode_in_force_says_so(self, params: HeaterParams) -> None:
        s = _scenario(125.0, 110.0, mode=ELECTRIC)
        r = element_mode(s, params, mode=ELECTRIC)
        assert "mode_already_in_force" in r.reasons

    def test_a_stint_with_nothing_to_heat_keeps_its_reasons(
        self, params: HeaterParams
    ) -> None:
        """Inside Electric's entry bracket: the walk says so."""
        r = _stint(params, ELECTRIC, upper=SETPOINT - 0.3, lower=SETPOINT + 0.5)
        assert r.end_minute == 0.0
        assert "deficit_inside_the_start_threshold_bracket" in r.reasons


@pytest.mark.parametrize("slot", [float("inf"), float("nan")])
def test_a_slot_must_be_finite(params: HeaterParams, slot: float) -> None:
    with pytest.raises(ValueError, match="slot_minutes"):
        _stint(params, ELECTRIC, slot_minutes=slot)


def test_one_slot_wider_than_the_stint_holds_it_all(
    params: HeaterParams,
) -> None:
    r = _stint(params, ELECTRIC, slot_minutes=1e9)
    assert len(r.profile) == 1
    assert r.profile[0].element_wh / 1000.0 == pytest.approx(
        r.element_kwh, abs=1e-3
    )
