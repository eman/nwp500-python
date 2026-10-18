"""Fitting a heater's own parameters from its history
(``nwp500.sim.calibration``), and the adapter that builds the history.

The fits are held to their source by the parity check run with the
port; these hold what each recovers, screens and reports.
"""

import math
from dataclasses import replace
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
from nwp500.sim import (
    Draw,
    Environment,
    HeaterState,
    Loads,
    Scenario,
    Settings,
    default_params,
    simulate,
)
from nwp500.sim import calibration as cal
from nwp500.sim.params import (
    CompressorParams,
    LossParams,
    TankParams,
    params_from_document,
    params_to_document,
)
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

    def test_a_meter_without_circulation_keeps_the_heaters_flag(self):
        """Only draws recorded: the heater's flag still stands in for
        circulation, which it also fires on."""
        h = decay(12, 5.0)
        h["drawing"] = False
        h.loc[
            T0 + timedelta(hours=4) : T0 + timedelta(hours=5), "dhw_in_use"
        ] = True
        windows = cal.quiet_windows(h)
        assert windows[0] == (T0, T0 + timedelta(hours=4))

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
        # No humidity recorded: unknown, as the model passed it on.
        assert math.isnan(row.h_amb_start)
        assert row.reached

    def test_a_dip_below_the_start_moves_the_row_after_it(self):
        h = recovery_history([(2, 160, 100.0)])
        # A draw takes the lower probe to 95 °F around the 30-minute
        # snapshot; it then recovers to the target by the end.
        dip = T0 + timedelta(hours=2, minutes=30)
        h.loc[dip - timedelta(minutes=5) : dip, "lower_f"] = 95.0
        (row,) = cal.recoveries(h).itertuples()
        assert row.start_time == dip
        assert row.duration_minutes == 130.0
        assert row.delta_t_lower == 45.0
        assert row.reached

    def test_the_air_falls_back_to_the_last_reading(self):
        h = recovery_history([(2, 160, 100.0)])
        start = T0 + timedelta(hours=2)
        h.loc[start:, "heater_air_f"] = np.nan
        h.loc[start, "heater_air_f"] = 61.0
        h.loc[
            start + timedelta(minutes=30) - timedelta(minutes=5) : start
            + timedelta(minutes=30),
            "lower_f",
        ] = 95.0
        (row,) = cal.recoveries(h).itertuples()
        # The coldest snapshot has no air after it: the reading before.
        assert row.start_time == start + timedelta(minutes=30)
        assert row.t_amb_mean == 61.0

    def test_a_cycle_without_air_is_no_recovery(self):
        h = recovery_history([(2, 100, 100.0)])
        h["heater_air_f"] = np.nan
        assert cal.recoveries(h).empty

    def test_the_snapshots(self):
        start = T0
        assert cal._snapshots(start, start + timedelta(minutes=14)) == []
        assert cal._snapshots(start, start + timedelta(minutes=75)) == [
            start + timedelta(minutes=m) for m in (0, 30, 60)
        ]

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
    def test_an_unrecorded_stop_threshold_is_the_usual_one(self):
        h = recovery_history([(2, 100, 100.0)]).drop(columns=["target_f"])
        (row,) = cal.recoveries(h).itertuples()
        assert row.delta_t_lower == pytest.approx(
            cal.UNRECORDED_TARGET_F - row.t_start_lower
        )

    def test_too_little_history_keeps_the_base(self):
        base = default_params()
        got = cal.calibrate(recovery_history([(2, 100, 100.0)]), base)
        assert got.compressor is None
        assert got.standby.ua_ref is None
        # Base's values, each named as not fitted on this heater.
        assert replace(got.params, unfitted=()) == base
        assert got.params.unfitted == (
            "compressor",
            "power",
            "standby",
            "gap_tau",
        )
        assert got.power is None
        assert len(got.recoveries) == 1

    def test_what_was_not_fitted_says_so_in_its_answers(self):
        got = cal.calibrate(
            recovery_history([(2, 100, 100.0)]), default_params()
        )
        p = got.params
        t0 = datetime(2026, 10, 5, tzinfo=UTC)
        s = Scenario(
            start=t0,
            horizon=timedelta(hours=6),
            tz="UTC",
            state=HeaterState(
                upper_f=120.0, lower_f=110.0, compressor_running=True
            ),
            settings=Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
            environment=Environment(ambient_f=65.0),
            loads=Loads(draws=(Draw(at=t0 + timedelta(hours=1), gallons=5.0),)),
        )
        r = simulate(s, p)
        for reason in (
            "physics_uncalibrated",
            "energy_uncalibrated",
            "standby_uncalibrated",
            "tau_gap_prior",
        ):
            assert reason in r.reasons
        # The record survives the parameters' document.
        assert params_from_document(params_to_document(p)).unfitted == (
            p.unfitted
        )


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
        assert first.power_w == on.current_inst_power
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


def power_rows(n: int, params) -> pd.DataFrame:
    """``n`` cycles' first snapshots, metered from the integrator itself
    at a power scale of 0.55 and a COP scale of 1.3 with 150 Wh of
    start-up, no lift term."""
    rng = np.random.default_rng(3)
    rows = pd.DataFrame(
        {
            "cycle": range(n),
            "offset_minutes": 0.0,
            "t_start_lower": rng.uniform(80, 120, n),
            "t_start_upper": rng.uniform(122, 136, n),
            "t_amb_mean": rng.uniform(50, 80, n),
            "h_amb_start": 50.0,
            "draw_free": True,
        }
    )
    rows["delta_t_lower"] = 140.0 - rows["t_start_lower"]
    rows["stratification_gap"] = rows["t_start_upper"] - rows["t_start_lower"]
    rows["t_lower_end"] = 140.0
    rows["t_upper_end"] = 140.0
    rows["duration_minutes"] = rows["delta_t_lower"] * 2.5
    return rows


class TestPower:
    def _fitted(self):
        base = default_params()
        return replace(
            base,
            compressor=replace(
                base.compressor,
                compressor_constant=0.08,
                evap_approach_f=12.0,
                two_zone=True,
            ),
        )

    def test_the_energy_integral_holds_each_reading(self):
        s = np.array([0.0, 600.0, 1200.0]) + T0.timestamp()
        w = np.array([400.0, 500.0, 300.0])
        end = T0 + timedelta(minutes=30)
        # 10 min at 400, 10 at 500, 10 at 300.
        assert cal._energy_wh(w, s, T0, end) == pytest.approx(200.0)
        # No reading before the start: the first is back-filled to it.
        late = T0 - timedelta(minutes=5)
        assert cal._energy_wh(w, s, late, end) == pytest.approx(
            400 * 15 / 60 + 500 * 10 / 60 + 300 * 10 / 60
        )
        assert cal._energy_wh(np.array([]), np.array([]), T0, end) is None

    def test_the_power_scale_is_a_ratio_of_sums(self):
        params = self._fitted()
        rows = power_rows(12, params)
        modelled = []
        for row in rows.to_dict("records"):
            path = cal.path_to_end(row, params)
            assert path is not None
            minutes = path.elapsed_s[-1] / 60
            watts = path.input_btu[-1] / 3.412141633 / (minutes / 60)
            modelled.append(watts * row["duration_minutes"] / 60)
        rows["metered_input_wh"] = 0.55 * np.array(modelled)
        scale, n = cal.fit_power_scale(rows, params)
        assert scale == pytest.approx(0.55)
        assert n == 12
        assert cal.fit_power_scale(rows.head(9), params) == (None, 9)

    def test_the_cop_recovers_its_scale_and_start_up(self):
        params = self._fitted()
        rows = power_rows(14, params)
        wh_per_f = params.tank.thermal_mass_btu_f / 3.412141633
        metered = []
        for row in rows.to_dict("records"):
            path = cal.path_to_end(row, params)
            cop = cal.path_cop(
                path, 0.0, path.elapsed_s[-1], True, row["t_start_upper"]
            )
            heat = wh_per_f * (
                140.0 - (row["t_start_lower"] + row["t_start_upper"]) / 2
            )
            metered.append(150.0 + heat / (1.3 * cop))
        rows["metered_input_wh"] = metered
        (scale, startup, share, lift), n = cal.fit_cop_scale(rows, params)
        assert scale == pytest.approx(1.3, rel=1e-6)
        assert startup == pytest.approx(150.0, rel=1e-6)
        assert lift == 0.0 and share == 0.0 and n == 14

    def test_without_a_meter_only_draw_free_cycles_count(self):
        params = self._fitted()
        rows = power_rows(14, params)
        rows["metered_input_wh"] = 1000.0
        rows.loc[rows.index[:5], "draw_free"] = False
        assert cal.fit_cop_scale(rows, params) == (None, 9)

    def test_the_fit_applies_where_it_had_the_evidence(self):
        base = default_params()
        fit = cal.PowerFit(0.6, 12, None, None, None, None, 4)
        got = cal.with_power(base, fit)
        assert got.power.power_scale == 0.6
        assert got.power.cop_scale == base.power.cop_scale


class TestMeteredPricing:
    """With a meter, the COP fit prices what each cycle's draws and
    circulation took instead of keeping only draw-free cycles."""

    def _row(self, **kw):
        return {
            "draw_gal": 0.0,
            "draw_t_upper": None,
            "draw_lead_gal": 0.0,
            "circulation_runs": (),
            "t_amb_mean": 65.0,
            "t_start_upper": 130.0,
        } | kw

    def test_nothing_drawn_is_nothing_withdrawn(self):
        from nwp500.sim import site_example_params

        w = cal.metered_withdrawn(site_example_params())
        assert w(self._row()) == 0.0
        assert w(self._row(draw_gal=None)) is None

    def test_draws_and_runs_are_priced(self):
        from nwp500.sim import site_example_params

        p = site_example_params()
        w = cal.metered_withdrawn(p)
        drawn = w(self._row(draw_gal=10.0, draw_t_upper=130.0))
        run = w(self._row(circulation_runs=((10.0, 130.0),)))
        assert drawn is not None and drawn > 0
        assert run is not None and run > 0
        both = w(
            self._row(
                draw_gal=10.0,
                draw_t_upper=130.0,
                circulation_runs=((10.0, 130.0),),
            )
        )
        assert both == pytest.approx(drawn + run)
        # Circulation without the installation's terms is unpriceable.
        bare = cal.metered_withdrawn(replace(p, circulation=None))
        assert bare(self._row(circulation_runs=((10.0, 130.0),))) is None
        lead = cal.metered_lead(p)
        assert lead(self._row(draw_lead_gal=4.0)) > 0
        assert lead(self._row()) == 0.0

    def test_a_run_is_priced_at_the_flow_it_ran_at(self):
        """A slower circulation displaces its volume later, so a short
        run priced at the flow it ran at takes less heat."""
        from nwp500.sim import site_example_params

        p = site_example_params()
        row = self._row(
            circulation_runs=((2.0, 135.0),),
            start_time=pd.Timestamp("2026-07-10", tz="UTC"),
        )
        today = cal.metered_withdrawn(p)(row)
        then = cal.metered_withdrawn(p, flow_at=lambda _: 1.1)(row)
        assert then is not None and today is not None and then < today
        unknown = cal.metered_withdrawn(p, flow_at=lambda _: None)(row)
        assert unknown == today

    def test_snapshots_carry_the_cycles_draws(self):
        h = recovery_history([(2, 100, 100.0)])
        start = T0 + timedelta(hours=2)
        draws = [
            (start + timedelta(minutes=20), 3.0),
            (start - timedelta(minutes=10), 2.0),
        ]
        runs = [(start + timedelta(minutes=30), start + timedelta(minutes=40))]
        rows = cal.snapshots(h, draws=draws, circulation=runs)
        row = next(rows.loc[rows.offset_minutes == 0].itertuples())
        assert row.draw_gal == 3.0 and row.draw_lead_gal == 2.0
        assert row.circulation_runs == ((10.0, 135.0),)
        plain = cal.snapshots(h)
        assert plain.draw_gal.isna().all()


class TestTheProbesShareOfCirculation:
    """``circulation_windows`` and ``fit_ungated_observability``."""

    def _history(self, runs, compressor=()):
        times = [T0 + timedelta(minutes=m) for m in range(24 * 60)]
        upper, lower = [], []
        u, lo = 138.0, 130.0
        for t in times:
            on = any(a <= t < b for a, b in runs)
            u -= 0.6 if on else 0.002
            lo -= 0.3 if on else 0.002
            upper.append(u)
            lower.append(lo)
        heating = [any(a <= t < b for a, b in compressor) for t in times]
        return pd.DataFrame(
            {
                "upper_f": upper,
                "lower_f": lower,
                "air_f": [65.0] * len(times),
                "compressor_on": heating,
            },
            index=pd.DatetimeIndex(times),
        )

    def test_a_chain_of_runs_is_one_window(self):
        from nwp500.sim import site_example_params

        runs = [
            (T0 + timedelta(hours=2), T0 + timedelta(hours=2, minutes=10)),
            (
                T0 + timedelta(hours=2, minutes=20),
                T0 + timedelta(hours=2, minutes=25),
            ),
            (T0 + timedelta(hours=6), T0 + timedelta(hours=6, minutes=8)),
        ]
        w = cal.circulation_windows(
            self._history(runs), runs, site_example_params(), draws=[]
        )
        assert len(w) == 2
        assert [len(x.runs) for x in w] == [1, 1]  # merged within the gap
        assert w[0].runs[0][0] == pytest.approx(25.0)
        assert all(x.apparent_btu > 0 for x in w)

    def test_a_compressor_or_an_unsized_draw_rules_one_out(self):
        from nwp500.sim import site_example_params

        runs = [
            (T0 + timedelta(hours=2), T0 + timedelta(hours=2, minutes=10)),
            (T0 + timedelta(hours=6), T0 + timedelta(hours=6, minutes=8)),
            (T0 + timedelta(hours=10), T0 + timedelta(hours=10, minutes=8)),
        ]
        heating = [
            (T0 + timedelta(hours=6, minutes=20), T0 + timedelta(hours=7))
        ]
        unsized = [(T0 + timedelta(hours=10, minutes=4), float("nan"))]
        w = cal.circulation_windows(
            self._history(runs, heating),
            runs,
            site_example_params(),
            draws=unsized,
        )
        assert len(w) == 1

    def test_too_few_windows_fit_nothing(self):
        from nwp500.sim import site_example_params

        runs = [(T0 + timedelta(hours=2), T0 + timedelta(hours=2, minutes=10))]
        p = site_example_params()
        w = cal.circulation_windows(self._history(runs), runs, p, draws=[])
        assert p.circulation is not None
        assert (
            cal.fit_ungated_observability(
                w, p.circulation.displaced_gal, p.circulation.flow_gpm
            )
            is None
        )
        many = w * cal.MIN_OBSERVABILITY_WINDOWS
        got = cal.fit_ungated_observability(
            many, p.circulation.displaced_gal, p.circulation.flow_gpm
        )
        assert got is not None and got[1] == cal.MIN_OBSERVABILITY_WINDOWS
