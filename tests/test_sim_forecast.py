"""When a recovery must start to have the tank ready at a time
(``sim.forecast``).

The computation is held to its source by the parity check run with the
port; these hold its answers' shapes.
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from nwp500.sim import (
    Environment,
    HeaterState,
    Settings,
    active_cycle,
    default_params,
    forecast,
)
from nwp500.sim.api import counter_measures_to_setpoint
from nwp500.sim.inputs import VACATION
from nwp500.sim.params import HeaterParams
from nwp500.sim.physics.heat_pump import start_hold_min

if TYPE_CHECKING:
    from nwp500.models import DeviceStatus

T0 = datetime(2026, 10, 9, 13, 10, tzinfo=UTC)
ENV = Environment(ambient_f=65.0, humidity=50.0)
SETTINGS = Settings(setpoint_f=140.9, hp_lower_off_f=140.0, hp_upper_on_f=104.0)


@pytest.fixture(scope="module")
def params() -> HeaterParams:
    return default_params()


def at(h: float) -> datetime:
    return T0 + timedelta(hours=h)


class TestReadyByATime:
    def test_it_starts_a_duration_before_the_target(
        self, params: HeaterParams
    ) -> None:
        f = forecast(
            HeaterState(upper_f=125.0, lower_f=100.0),
            SETTINGS,
            ENV,
            params,
            at=T0,
            target_time=at(10),
        )
        assert f.status == "ok" and f.feasible and f.shortfall_minutes is None
        assert f.ready_at == at(10)
        assert f.start_at == at(10) - timedelta(minutes=f.duration_minutes)
        assert f.target_f == 140.0 and f.estimator == "physics"
        # The physics' climb after a start's hold, the compressor's last
        # stop not known.
        assert f.physics_estimate_minutes is not None
        assert f.duration_minutes == pytest.approx(
            f.physics_estimate_minutes + start_hold_min(params.compressor, None)
        )
        # The tank coasted to the start, cooler than now.
        assert f.upper_f_at_start + f.lower_f_at_start < 125.0 + 100.0
        assert f.trajectory is not None
        assert f.trajectory[0].at == f.start_at
        assert f.trajectory[-1].at == f.ready_at

    def test_too_soon_is_infeasible_and_starts_now(
        self, params: HeaterParams
    ) -> None:
        f = forecast(
            HeaterState(upper_f=125.0, lower_f=100.0),
            SETTINGS,
            ENV,
            params,
            at=T0,
            target_time=at(0.5),
        )
        assert f.status == "infeasible" and not f.feasible
        assert f.start_at == T0
        assert f.ready_at == T0 + timedelta(minutes=f.duration_minutes)
        assert f.shortfall_minutes == pytest.approx(f.duration_minutes - 30.0)

    def test_a_partial_charge_heats_to_its_own_target(
        self, params: HeaterParams
    ) -> None:
        state = HeaterState(upper_f=125.0, lower_f=100.0)
        full = forecast(state, SETTINGS, ENV, params, at=T0, target_time=at(8))
        part = forecast(
            state,
            SETTINGS,
            ENV,
            params,
            at=T0,
            target_time=at(8),
            target_lower_f=120.0,
        )
        assert part.status == "partial_charge" and part.target_f == 120.0
        assert part.duration_minutes < full.duration_minutes
        # To the target asked for, with no run-on past it; the heater's
        # own threshold, with it.
        assert part.trajectory is not None and full.trajectory is not None
        assert part.trajectory[-1].t_lower_f == pytest.approx(120.0, abs=0.1)
        assert full.trajectory[-1].t_lower_f == pytest.approx(
            140.0 + params.controller.hp_stop_overshoot_f, abs=0.1
        )

    def test_without_the_stop_threshold_it_heats_to_the_setpoint(
        self, params: HeaterParams
    ) -> None:
        f = forecast(
            HeaterState(upper_f=125.0, lower_f=100.0),
            Settings(setpoint_f=138.0),
            ENV,
            params,
            at=T0,
            target_time=at(8),
        )
        assert f.target_f == 138.0
        assert "hp_lower_off_f=setpoint_f" in f.defaults_used

    def test_vacation_is_not_scheduled(self, params: HeaterParams) -> None:
        f = forecast(
            HeaterState(upper_f=125.0, lower_f=100.0),
            SETTINGS.model_copy(update={"mode": VACATION}),
            ENV,
            params,
            at=T0,
            target_time=at(8),
        )
        assert f.status == "not_scheduled"
        assert f.start_at is None and f.ready_at is None and not f.feasible
        assert f.duration_minutes > 0

    def test_a_target_past_the_horizon_is_refused(
        self, params: HeaterParams
    ) -> None:
        with pytest.raises(ValueError, match="ahead"):
            forecast(
                HeaterState(upper_f=125.0, lower_f=100.0),
                SETTINGS,
                ENV,
                params,
                at=T0,
                target_time=at(169),
            )


class TestAlreadyReady:
    def test_a_lower_zone_at_its_target(self, params: HeaterParams) -> None:
        f = forecast(
            HeaterState(upper_f=141.0, lower_f=140.0),
            SETTINGS,
            ENV,
            params,
            at=T0,
            target_time=at(4),
        )
        assert f.status == "no_heating_required"
        assert f.start_at == f.ready_at == T0 and f.duration_minutes == 0.0
        assert f.estimator == "no_heating_required"

    def test_a_zero_count_outside_a_tou_window(
        self, params: HeaterParams
    ) -> None:
        f = forecast(
            HeaterState(upper_f=139.0, lower_f=137.0, energy_to_setpoint_wh=0),
            SETTINGS,
            ENV,
            params,
            at=T0,
            target_time=at(4),
        )
        assert f.status == "no_heating_required"

    def test_a_zero_count_inside_one_is_a_counterfactual(
        self, params: HeaterParams
    ) -> None:
        raised = SETTINGS.model_copy(update={"hp_upper_on_f": 139.0})
        f = forecast(
            HeaterState(upper_f=139.0, lower_f=137.0, energy_to_setpoint_wh=0),
            raised,
            ENV,
            params,
            at=T0,
            target_time=at(4),
        )
        assert f.status == "ok" and f.tou_capped

    def test_the_counter_test(self) -> None:
        assert counter_measures_to_setpoint(104.0, 140.0)
        assert counter_measures_to_setpoint(105.8, 140.0)
        assert not counter_measures_to_setpoint(106.0, 140.0)
        assert not counter_measures_to_setpoint(139.0, 140.0)
        assert not counter_measures_to_setpoint(None, 140.0)


class TestTheRunningCycle:
    def test_an_idle_compressor_is_not_heating(
        self, params: HeaterParams
    ) -> None:
        a = active_cycle(
            HeaterState(upper_f=125.0, lower_f=100.0),
            SETTINGS,
            ENV,
            params,
            at=T0,
        )
        assert a.status == "not_heating" and a.remaining_minutes is None

    def test_what_is_left_and_the_physics_beside_it(
        self, params: HeaterParams
    ) -> None:
        state = HeaterState(
            upper_f=125.0, lower_f=110.0, compressor_running=True
        )
        a = active_cycle(state, SETTINGS, ENV, params, at=T0)
        assert a.status == "heating" and a.target_f == 140.0
        assert a.remaining_minutes is not None and a.remaining_minutes > 0
        assert a.ready_at == T0 + timedelta(minutes=a.remaining_minutes)
        # Under way, its hold is over: what is left is the climb.
        assert a.physics_remaining_minutes == pytest.approx(
            a.remaining_minutes, abs=0.2
        )

    def test_a_run_goes_on_where_putting_it_off_is_too_late(
        self, params: HeaterParams
    ) -> None:
        # Put off, the run stops and starts again, its cold bottom
        # stirred: longer than the run going on now. A target between
        # the two is met by the run going on, ready early; one past the
        # later start's own duration puts it off.
        n = params.tank.layers
        state = HeaterState(
            upper_f=130.0,
            lower_f=115.0,
            layers_f=(80.0, 90.0, *([115.0] * (n - 4)), 130.0, 132.0),
            compressor_running=True,
        )
        going = active_cycle(state, SETTINGS, ENV, params, at=T0)
        assert going.remaining_minutes is not None
        late = forecast(state, SETTINGS, ENV, params, at=T0, target_time=at(5))
        assert late.start_at is not None and late.start_at > T0
        assert late.duration_minutes > going.remaining_minutes + 5.0
        between = T0 + timedelta(
            minutes=(going.remaining_minutes + late.duration_minutes) / 2
        )
        f = forecast(state, SETTINGS, ENV, params, at=T0, target_time=between)
        assert f.status == "ok" and f.feasible
        assert f.start_at == T0
        assert f.duration_minutes == pytest.approx(
            going.remaining_minutes, abs=1.0
        )
        assert f.ready_at is not None and f.ready_at < between
        assert f.trajectory is not None
        assert f.trajectory[-1].at == f.ready_at

    @pytest.mark.parametrize("past", [0.0, 1.0])
    def test_a_cycle_past_its_run_on_has_nothing_left(
        self, params: HeaterParams, past: float
    ) -> None:
        lower = 140.0 + params.controller.hp_stop_overshoot_f + past
        a = active_cycle(
            HeaterState(upper_f=141.0, lower_f=lower, compressor_running=True),
            SETTINGS,
            ENV,
            params,
            at=T0,
        )
        assert a.status == "heating" and a.remaining_minutes == 0.0
        assert a.ready_at == T0 and a.physics_remaining_minutes == 0.0

    def test_a_cycle_at_its_target_has_its_run_on_left(
        self, params: HeaterParams
    ) -> None:
        a = active_cycle(
            HeaterState(upper_f=141.0, lower_f=140.0, compressor_running=True),
            SETTINGS,
            ENV,
            params,
            at=T0,
        )
        assert a.target_f == 140.0
        assert a.remaining_minutes is not None
        assert 0.0 < a.remaining_minutes < 15.0


class TestTheAdapters:
    def _status(self, d: dict[str, Any], **kw: Any) -> DeviceStatus:
        from nwp500.models import DeviceStatus

        return DeviceStatus.model_validate(d | kw)

    def test_the_thresholds_and_the_count(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        from nwp500 import sim_adapters as sa

        s = self._status(
            device_status_dict,
            hpLowerOffTempSetting=120,
            hpUpperOnTempSetting=81,
            availableEnergyCapacity=12,
        )
        settings = sa.settings(s)
        assert settings.hp_lower_off_f == pytest.approx(140.0)
        assert settings.hp_upper_on_f == pytest.approx(104.9)
        assert sa.heater_state(s).energy_to_setpoint_wh == s.energy_to_setpoint


def test_recovery_says_why_none_comes_on_vacation(
    params: HeaterParams,
) -> None:
    from nwp500.sim import recovery

    r = recovery(
        HeaterState(upper_f=120.0, lower_f=95.0),
        SETTINGS.model_copy(update={"mode": VACATION}),
        ENV,
        params,
        at=T0,
    )
    assert r.interval is None and "not_scheduled" in r.reasons
    assert "no_recovery_within_horizon" not in r.reasons
