"""Fitting a heater's own parameters from its history
(``nwp500.sim.calibration``), and the adapter that builds the history.

The fits are held to their source by the parity check run with the
port; these hold what each recovers, screens and reports.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("scipy")

import numpy as np
import pandas as pd

from nwp500 import sim_adapters as sa
from nwp500.models import DeviceStatus
from nwp500.sim import calibration as cal
from nwp500.sim import default_params
from nwp500.sim.params import CompressorParams, LossParams, TankParams
from nwp500.sim.physics.compressor import predict_physics_detailed
from nwp500.unit_system import reset_unit_system, set_unit_system

T0 = datetime(2026, 1, 5, tzinfo=UTC)
MASS = TankParams().thermal_mass_btu_f


@pytest.fixture(autouse=True)
def _units():
    yield
    reset_unit_system()


def decay(
    hours: float,
    ua: float,
    *,
    start: datetime = T0,
    tank_f: float = 130.0,
    gap_f: float = 6.0,
    air_f: float = 60.0,
    tau_gap_h: float = 60.0,
    step: timedelta = timedelta(minutes=1),
) -> pd.DataFrame:
    """A quiet tank cooling at ``ua`` toward ``air_f``, its gap relaxing
    on ``tau_gap_h``."""
    rows, t, tank, gap = [], start, tank_f, gap_f
    while t < start + timedelta(hours=hours):
        rows.append((t, tank + gap / 2, tank - gap / 2, air_f))
        h = step.total_seconds() / 3600
        tank -= ua / MASS * (tank - air_f) * h
        gap *= np.exp(-h / tau_gap_h)
        t += step
    frame = pd.DataFrame(
        [r[1:] for r in rows],
        columns=["upper_f", "lower_f", "air_f"],
        index=pd.DatetimeIndex([r[0] for r in rows]),
    )
    for name in ("compressor_on", "element_on", "dhw_in_use"):
        frame[name] = False
    return frame


class TestQuiet:
    def test_heating_and_water_are_busy_and_settle(self):
        h = decay(12, 5.0)
        h.loc[
            T0 + timedelta(hours=4) : T0 + timedelta(hours=5), "dhw_in_use"
        ] = True
        windows = cal.quiet_windows(h)
        assert windows[0] == (T0, T0 + timedelta(hours=4))
        # The draw's last "on" sample, its next "off", then 45 minutes.
        assert windows[1][0] == T0 + timedelta(hours=5, minutes=46)

    def test_a_meter_replaces_the_heaters_flag(self):
        h = decay(12, 5.0)
        h["dhw_in_use"] = True
        h["drawing"] = False
        h["circulating"] = False
        assert cal.quiet_windows(h) == [(T0, h.index[-1].to_pydatetime())]
        assert cal.fit_standby(h, MASS).quiet_by == "meter"

    def test_short_gaps_are_not_windows(self):
        h = decay(5, 5.0)
        h.loc[T0 + timedelta(hours=2), "compressor_on"] = True
        assert cal.quiet_windows(h) == []


class TestStandby:
    def test_a_window_recovers_its_ua(self):
        h = decay(24, 6.0)
        fit = cal.fit_window(h, (T0, T0 + timedelta(hours=24)), MASS)
        assert fit is not None
        assert fit.ua_btu_hr_f == pytest.approx(6.0, rel=0.02)
        assert fit.delta_t_mean_f > 0

    def test_a_window_without_air_is_not_fitted(self):
        h = decay(24, 6.0).drop(columns="air_f")
        assert cal.fit_window(h, (T0, T0 + timedelta(hours=24)), MASS) is None

    def test_the_law_is_constant_without_the_range(self):
        ua, exponent = cal.fit_ua_law([50, 52, 55, 51], [5, 6, 5, 6])
        assert exponent == 0.0
        assert ua == pytest.approx(5.5)

    def test_the_law_recovers_an_exponent(self):
        dt = [20.0, 35.0, 50.0, 70.0, 90.0]
        ua = [5.0 * (x / 50.0) ** 0.3 for x in dt]
        ref, exponent = cal.fit_ua_law(dt, ua)
        assert exponent == pytest.approx(0.3)
        assert ref == pytest.approx(5.0)

    def test_the_gap_needs_enough_windows(self):
        t = np.arange(0, 10, 1 / 12)
        few = [(t, 5.0 * np.exp(-t / 50.0))] * (cal.MIN_GAP_FIT_WINDOWS - 1)
        assert cal.fit_gap_tau(few) == (None, cal.MIN_GAP_FIT_WINDOWS - 1)
        tau, n = cal.fit_gap_tau(few + few[:1])
        assert tau == pytest.approx(50.0, rel=1e-3)
        assert n == cal.MIN_GAP_FIT_WINDOWS

    def test_fit_standby_and_its_parameters(self):
        h = decay(24, 6.0)
        fit = cal.fit_standby(h, MASS)
        assert (fit.n_quiet, fit.n_dropped) == (1, 0)
        assert fit.ua_ref == pytest.approx(6.0, rel=0.02)
        assert fit.tau_gap_hours is None
        params = cal.with_standby(default_params(), fit)
        assert params.loss.ua_btu_hr_f == fit.ua_ref
        assert (
            params.tank.stratification_gap_tau_h
            == default_params().tank.stratification_gap_tau_h
        )


def recovery_history(
    runs: list[tuple[float, float, float]],
    *,
    target_f: float = 140.0,
) -> pd.DataFrame:
    """Each run ``(start_h, minutes, start_lower_f)``: the lower probe
    rising from its start to ``target_f`` over the run."""
    index = pd.date_range(T0, T0 + timedelta(hours=48), freq="1min")
    frame = pd.DataFrame(
        {
            "upper_f": 135.0,
            "lower_f": 120.0,
            "compressor_on": False,
            "element_on": False,
            "dhw_in_use": False,
            "target_f": target_f,
            "excluded": False,
            "heater_air_f": np.nan,
        },
        index=index,
    )
    for start_h, minutes, lower in runs:
        a = T0 + timedelta(hours=start_h)
        b = a + timedelta(minutes=minutes)
        span = (index >= a) & (index < b)
        frame.loc[span, "compressor_on"] = True
        frame.loc[span, "heater_air_f"] = 65.0
        frame.loc[span, "lower_f"] = np.linspace(lower, target_f, span.sum())
        frame.loc[a - timedelta(minutes=1), "lower_f"] = lower
    return frame


class TestRecoveries:
    def test_a_clean_run(self):
        (row,) = cal.recoveries(
            recovery_history([(2, 100, 100.0)])
        ).itertuples()
        assert row.start_time == T0 + timedelta(hours=2)
        assert row.duration_minutes == 100.0
        assert row.t_start_lower == 100.0
        assert row.delta_t_lower == 40.0
        assert row.stratification_gap == 35.0
        assert row.t_amb_mean == 65.0
        assert row.h_amb_start == 50.0
        assert row.reached

    def test_one_stopped_short_is_not_reached(self):
        h = recovery_history([(2, 100, 100.0)])
        h.loc[h["compressor_on"], "lower_f"] -= 3.4
        assert not cal.recoveries(h)["reached"].item()

    def test_an_element_or_a_hybrid_mode_rules_it_out(self):
        h = recovery_history([(2, 100, 100.0), (10, 100, 100.0)])
        h.loc[T0 + timedelta(hours=1, minutes=55), "element_on"] = True
        h.loc[T0 + timedelta(hours=10, minutes=30), "excluded"] = True
        assert cal.recoveries(h).empty

    def test_one_cut_short_is_no_recovery(self):
        h = recovery_history([(2, 100, 100.0)])
        h["energy_to_setpoint_wh"] = 0.0
        end = T0 + timedelta(hours=2, minutes=100)
        # Still to heat once the compressor stopped: the last reading
        # around the end counts.
        tail = slice(end - timedelta(minutes=1), end + timedelta(minutes=1))
        h.loc[tail, "energy_to_setpoint_wh"] = 600.0
        assert cal.recoveries(h).empty
        h.loc[tail, "energy_to_setpoint_wh"] = 400.0
        assert len(cal.recoveries(h)) == 1

    @pytest.mark.parametrize("minutes", [60, 900])
    def test_an_implausible_rate_is_no_recovery(self, minutes):
        # 40 °F in an hour is faster than the heat pump heats; in 15
        # hours, an interruption nobody saw.
        assert cal.recoveries(recovery_history([(2, minutes, 100.0)])).empty

    def test_a_target_below_the_probe_is_no_recovery(self):
        assert cal.recoveries(
            recovery_history([(2, 100, 141.0)], target_f=140.0)
        ).empty


def physics_durations(
    starts: list[float], air: list[float], k: float, approach: float
) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "t_start_lower": starts,
            "t_amb_mean": air,
            "stratification_gap": [10.0] * len(starts),
            "start_time": [T0 + timedelta(days=i) for i in range(len(starts))],
        }
    )
    df["delta_t_lower"] = 140.0 - df["t_start_lower"]
    df["duration_minutes"] = [
        predict_physics_detailed(
            t_start_lower=s,
            hp_lower_off=140.0,
            t_amb_mean=a,
            compressor_constant=k,
            evap_approach_f=approach,
            compressor=CompressorParams(),
            loss=LossParams(),
            stratification_gap=10.0,
            two_zone=True,
        ).minutes
        for s, a in zip(starts, air, strict=True)
    ]
    return df


class TestCompressor:
    def test_too_few_recoveries_fit_nothing(self):
        df = physics_durations([100.0] * 4, [60.0] * 4, 0.08, 12.0)
        assert cal.fit_compressor(df, CompressorParams(), LossParams()) is None

    def test_it_recovers_known_physics(self):
        starts = [80.0, 90.0, 100.0, 110.0, 85.0, 95.0, 105.0, 115.0]
        air = [50.0, 80.0, 60.0, 70.0, 75.0, 55.0, 65.0, 85.0]
        df = physics_durations(starts, air, 0.08, 12.0)
        fit = cal.fit_compressor(df, CompressorParams(), LossParams())
        assert fit is not None
        assert fit.compressor_constant == pytest.approx(0.08, rel=0.02)
        assert fit.evap_approach_f == pytest.approx(12.0, abs=0.5)
        assert fit.mae_minutes < 1.0
        assert (fit.n_fitted, fit.n_heldout, fit.two_zone) == (8, 0, True)
        assert not fit.hit_bounds

    def test_without_gaps_it_fits_one_zone(self):
        df = physics_durations([100.0] * 6, [60.0] * 6, 0.08, 12.0)
        fit = cal.fit_compressor(
            df.drop(columns="stratification_gap"),
            CompressorParams(),
            LossParams(),
        )
        assert fit is not None and not fit.two_zone

    def test_a_pinned_fit_is_not_applied(self):
        fit = cal.CompressorFit(0.3, 4.0, 1.0, None, 8, 0, True, True)
        base = default_params()
        assert cal.with_compressor(base, fit) is base


class TestCalibrate:
    def test_too_little_history_keeps_the_base(self):
        base = default_params()
        got = cal.calibrate(recovery_history([(2, 100, 100.0)]), base)
        assert got.compressor is None
        assert got.standby.ua_ref is None
        assert got.params == base
        assert len(got.recoveries) == 1


class TestTheHistoryAdapter:
    def _status(self, d: dict[str, Any], **kw: Any) -> DeviceStatus:
        return DeviceStatus.model_validate(d | kw)

    def test_it_reads_the_status(self, device_status_dict):
        on = self._status(
            device_status_dict, compUse=2, dhwUse=2, ambientTemperature=200
        )
        off = self._status(device_status_dict, currentHeatUse=2, errorCode=96)
        h = sa.history(
            [(T0 + timedelta(minutes=1), off), (T0, on)],
            air=[(T0, 20.0), (T0 + timedelta(minutes=2), 22.0)],
        )
        assert list(h.index) == [T0, T0 + timedelta(minutes=1)]
        first, second = h.iloc[0], h.iloc[1]
        assert first.upper_f == pytest.approx(95.0)
        assert first.target_f == pytest.approx(140.0)
        assert first.compressor_on and first.dhw_in_use
        assert first.heater_air_f == pytest.approx(68.0)
        assert not first.element_on and not first.excluded
        assert np.isnan(second.heater_air_f)
        assert second.element_on and second.excluded
        # The air in °F, its preferred unit by default.
        assert second.air_f == pytest.approx(21.0)

    def test_the_air_in_the_preferred_unit(self, device_status_dict):
        set_unit_system("metric")
        s = self._status(device_status_dict)
        h = sa.history([(T0, s)], air=[(T0, 20.0)])
        assert h.iloc[0].air_f == pytest.approx(68.0)

    def test_a_meters_spans(self, device_status_dict):
        s = self._status(device_status_dict)
        h = sa.history(
            [(T0 + timedelta(minutes=m), s) for m in range(4)],
            drawing=[(T0 + timedelta(minutes=1), T0 + timedelta(minutes=3))],
            circulating=[],
        )
        assert list(h["drawing"]) == [False, True, True, False]
        assert not h["circulating"].any()
