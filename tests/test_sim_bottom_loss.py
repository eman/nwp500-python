"""The bottom loss: heat leaving the lower zone, which the lower probe
sees only while the tank is stratified (``sim.physics.tank``)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("scipy")

import numpy as np
import pandas as pd

from nwp500 import sim
from nwp500 import sim_calibrate as sc
from nwp500.sim import calibration as cal
from nwp500.sim.decay import DecayProjection, project_decay
from nwp500.sim.params import (
    HeaterParams,
    LossParams,
    params_from_document,
    params_to_document,
)
from nwp500.sim.physics.compressor import predict_physics_detailed
from nwp500.sim.physics.tank import bottom_loss_drop_f, bottom_loss_reach

T0 = datetime(2026, 1, 5, tzinfo=UTC)
TANK = sim.default_params().tank
TAU = 60.0
UA = 4.0
Q_B = 90.0
GATE = 1.5


def _air(air_f: float, hours: float, start: datetime = T0) -> pd.DataFrame:
    return pd.DataFrame(
        {"ambient_f": [air_f, air_f]},
        index=pd.DatetimeIndex([start, start + timedelta(hours=hours + 1)]),
    )


def _walk(
    upper: float,
    lower: float,
    hours: float,
    *,
    bottom: float = 0.0,
    gate: float = GATE,
    air_f: float = 60.0,
    start: datetime = T0,
) -> DecayProjection:
    return project_decay(
        upper,
        lower,
        _air(air_f, hours, start),
        UA,
        TAU,
        start + timedelta(hours=hours),
        start,
        tank=TANK,
        bottom_loss_btu_hr=bottom,
        bottom_gate_f=gate,
    )


class TestTheReach:
    def test_a_mixed_tank_shows_none_of_it(self) -> None:
        assert bottom_loss_reach(0.0, GATE) == 0.0
        assert bottom_loss_reach(-1.0, GATE) == 0.0
        assert bottom_loss_reach(3.0, 0.0) == 0.0

    def test_a_stratified_tank_shows_more_of_it_as_the_gap_opens(
        self,
    ) -> None:
        assert bottom_loss_reach(GATE, GATE) == pytest.approx(1 - np.exp(-1))
        assert bottom_loss_reach(1.0, GATE) < bottom_loss_reach(4.0, GATE)
        assert bottom_loss_reach(50.0, GATE) == pytest.approx(1.0)

    def test_the_drop_is_the_seen_heat_on_the_lower_zone(self) -> None:
        lower = TANK.lower_zone_thermal_mass_btu_f
        drop = bottom_loss_drop_f(Q_B, 4.0, GATE, 2.0, lower)
        assert drop == pytest.approx(
            Q_B * bottom_loss_reach(4.0, GATE) * 2.0 / lower
        )
        assert bottom_loss_drop_f(0.0, 4.0, GATE, 2.0, lower) == 0.0


class TestTheWalk:
    def test_no_bottom_loss_is_the_walk_before_it(self) -> None:
        before = _walk(136.0, 131.0, 9.5)
        after = project_decay(
            136.0,
            131.0,
            _air(60.0, 9.5),
            UA,
            TAU,
            T0 + timedelta(hours=9.5),
            T0,
            tank=TANK,
            bottom_loss_btu_hr=0.0,
            bottom_gate_f=GATE,
        )
        assert after.trajectory == before.trajectory
        assert (after.t_upper, after.t_lower) == (
            before.t_upper,
            before.t_lower,
        )

    def test_a_stratified_tank_loses_it_from_the_lower_zone(self) -> None:
        without = _walk(136.0, 131.0, 10.0)
        with_it = _walk(136.0, 131.0, 10.0, bottom=Q_B)
        # The lower zone falls and the gap opens. The upper zone moves
        # only as the wider gap relaxes on its constant.
        assert with_it.t_upper == pytest.approx(without.t_upper, abs=0.1)
        assert with_it.t_lower < without.t_lower - 1.0
        assert with_it.stratification_gap > 5.0

    def test_a_mixed_tank_hides_it(self) -> None:
        without = _walk(135.0, 135.0, 10.0)
        with_it = _walk(135.0, 135.0, 10.0, bottom=Q_B)
        assert (with_it.t_upper, with_it.t_lower) == (
            without.t_upper,
            without.t_lower,
        )

    def test_a_chain_is_the_single_walk(self) -> None:
        single = _walk(136.0, 131.0, 10.0, bottom=Q_B)
        first = _walk(136.0, 131.0, 3.7, bottom=Q_B)
        second = _walk(
            first.t_upper,
            first.t_lower,
            6.3,
            bottom=Q_B,
            start=T0 + timedelta(hours=3.7),
        )
        assert second.t_lower == pytest.approx(single.t_lower, abs=0.02)
        assert second.t_upper == pytest.approx(single.t_upper, abs=0.02)

    def test_the_fits_walk_is_the_simulations(self) -> None:
        loss = replace(
            sim.default_params().loss,
            ua_btu_hr_f=UA,
            ua_exponent=0.0,
            bottom_loss_btu_hr=Q_B,
            bottom_gate_f=GATE,
        )
        walked = _walk(136.0, 131.0, 10.0, bottom=Q_B)
        (window,) = windows_of([(136.0, 131.0, 60.0, 10.0)], loss)
        upper, lower = cal.standby_ends([window], loss, TAU, TANK)
        assert upper[0] == pytest.approx(walked.t_upper, abs=0.02)
        assert lower[0] == pytest.approx(walked.t_lower, abs=0.02)


class TestTheRecovery:
    def _minutes(self, bottom: float, gap: float) -> float:
        params = sim.default_params()
        loss = replace(
            params.loss, bottom_loss_btu_hr=bottom, bottom_gate_f=GATE
        )
        return predict_physics_detailed(
            t_start_lower=100.0,
            hp_lower_off=130.0,
            t_amb_mean=60.0,
            compressor_constant=params.compressor.compressor_constant,
            evap_approach_f=params.compressor.evap_approach_f,
            compressor=params.compressor,
            loss=loss,
            ua_btu_hr_f=UA,
            stratification_gap=gap,
            two_zone=True,
            tank=params.tank,
        ).minutes

    def test_no_bottom_loss_is_the_recovery_before_it(self) -> None:
        params = sim.default_params()
        before = predict_physics_detailed(
            t_start_lower=100.0,
            hp_lower_off=130.0,
            t_amb_mean=60.0,
            compressor_constant=params.compressor.compressor_constant,
            evap_approach_f=params.compressor.evap_approach_f,
            compressor=params.compressor,
            loss=params.loss,
            ua_btu_hr_f=UA,
            stratification_gap=20.0,
            two_zone=True,
            tank=params.tank,
        )
        assert self._minutes(0.0, 20.0) == before.minutes

    def test_a_stratified_recovery_runs_longer_for_it(self) -> None:
        assert self._minutes(Q_B, 20.0) > self._minutes(0.0, 20.0)
        assert self._minutes(Q_B, 0.0) == self._minutes(0.0, 0.0)


def windows_of(
    starts: list[tuple[float, float, float, float]],
    loss: LossParams,
    tau: float = TAU,
) -> list[cal.StandbyWindow]:
    """A quiet window for each ``(upper, lower, air, hours)``, a day
    apart, its probes the simulation's own walk on ``loss`` and ``tau``,
    on a 10-minute grid."""
    out = []
    for day, (upper, lower, air, hours) in enumerate(starts):
        start = T0 + timedelta(days=day)
        walked = project_decay(
            upper,
            lower,
            _air(air, hours, start),
            cast_ua(loss),
            tau,
            start + timedelta(hours=hours),
            start,
            ua_exponent=loss.ua_exponent,
            tank=TANK,
            bottom_loss_btu_hr=loss.bottom_loss_btu_hr,
            bottom_gate_f=loss.bottom_gate_f,
        )
        when = [t for t, _, _ in walked.trajectory]
        up = np.array([u for _, u, _ in walked.trajectory])
        lo = np.array([low for _, _, low in walked.trajectory])
        out.append(
            cal.StandbyWindow(
                start=start,
                end=when[-1],
                ua_btu_hr_f=UA,
                rmse_f=0.05,
                delta_t_mean_f=float(np.mean((up + lo) / 2 - air)),
                duration_hours=hours,
                gap_hours=np.array(
                    [(t - start).total_seconds() / 3600 for t in when]
                ),
                gap_f=up - lo,
                upper_f=up,
                lower_f=lo,
                air_f=np.full(len(up), air),
            )
        )
    return out


def cast_ua(loss: LossParams) -> float:
    assert loss.ua_btu_hr_f is not None
    return loss.ua_btu_hr_f


def planted_starts(n: int) -> list[tuple[float, float, float, float]]:
    """``n`` windows' starts: every third mixed, the rest opening with a
    2-8 °F gap, across tank temperatures, airs and lengths."""
    out = []
    for i in range(n):
        tank = 125.0 + 3 * (i % 6)
        gap = 0.0 if i % 3 == 0 else 2.0 + 1.5 * (i % 5)
        out.append(
            (tank + gap / 2, tank - gap / 2, 50.0 + 4 * (i % 7), 6.0 + i % 9)
        )
    return out


PLANTED = replace(
    sim.default_params().loss,
    ua_btu_hr_f=UA,
    ua_exponent=0.0,
    bottom_loss_btu_hr=Q_B,
    bottom_gate_f=GATE,
)


class TestTheFit:
    def test_it_recovers_a_planted_bottom_loss(self) -> None:
        windows = windows_of(planted_starts(30), PLANTED)
        fit = cal.fit_loss(windows, TAU, TANK)
        assert fit is not None
        assert fit.n_stratified == 20
        assert fit.ua_ref == pytest.approx(UA, rel=0.03)
        assert fit.bottom_loss_btu_hr == pytest.approx(Q_B, rel=0.05)
        assert fit.bottom_gate_f == pytest.approx(GATE, rel=0.15)
        assert fit.ua_exponent == pytest.approx(0.0, abs=0.02)

    def test_too_few_stratified_windows_fit_the_jacket_law_alone(
        self,
    ) -> None:
        starts = [s for s in planted_starts(30) if s[0] == s[1]]
        windows = windows_of(starts, replace(PLANTED, bottom_loss_btu_hr=0.0))
        fit = cal.fit_loss(windows, TAU, TANK)
        assert fit is not None
        assert (fit.bottom_loss_btu_hr, fit.bottom_gate_f) == (0.0, None)
        assert fit.n_stratified == 0
        assert fit.ua_ref == pytest.approx(UA, rel=0.05)

    def test_a_draws_front_is_not_its_evidence(self) -> None:
        windows = windows_of(
            [(140.0, 120.0, 60.0, 8.0), (136.0, 131.0, 60.0, 8.0)], PLANTED
        )
        assert cal.loss_windows(windows) == windows[1:]
        no_probes = replace(windows[1], upper_f=np.zeros(0))
        assert cal.loss_windows([no_probes]) == []

    def test_the_error_is_the_probes_fall(self) -> None:
        windows = windows_of(planted_starts(12), PLANTED)
        assert cal.standby_error(windows, PLANTED, TAU, TANK) == (
            pytest.approx(0.0, abs=1e-9)
        )
        jacket = replace(PLANTED, bottom_loss_btu_hr=0.0)
        error = cal.standby_error(windows, jacket, TAU, TANK)
        assert error is not None and error > 0.01
        assert cal.standby_error([], PLANTED, TAU, TANK) is None

    def test_with_standby_takes_the_bottom_loss_with_the_law(self) -> None:
        base = sim.default_params()
        base = replace(
            base,
            loss=replace(base.loss, bottom_loss_btu_hr=50.0, bottom_gate_f=3.0),
        )
        fit = cal.StandbyFit(
            windows=(),
            n_quiet=0,
            n_dropped=0,
            ua_ref=4.0,
            ua_exponent=0.0,
            tau_gap_hours=None,
            n_gap_windows=0,
            quiet_by="dhw_in_use",
        )
        # A law fitted without a bottom loss has none.
        loss = cal.with_standby(base, fit).loss
        assert (loss.bottom_loss_btu_hr, loss.bottom_gate_f) == (0.0, 3.0)
        loss = cal.with_standby(
            base, replace(fit, bottom_loss_btu_hr=Q_B, bottom_gate_f=GATE)
        ).loss
        assert (loss.bottom_loss_btu_hr, loss.bottom_gate_f) == (Q_B, GATE)


class TestTheParameters:
    def test_a_document_from_before_it_has_none(self) -> None:
        doc = params_to_document(sim.default_params())
        for name in ("bottom_loss_btu_hr", "bottom_gate_f"):
            del doc["loss"][name]
        loss = params_from_document(doc).loss
        assert loss.bottom_loss_btu_hr == 0.0
        assert params_from_document(doc) == sim.default_params()

    def test_it_round_trips(self) -> None:
        params = replace(sim.default_params(), loss=PLANTED)
        assert params_from_document(params_to_document(params)) == params


class TestKeepBetter:
    def _keep(
        self, base_loss: LossParams
    ) -> tuple[HeaterParams, sc.Judged, sc.HeldOut, HeaterParams]:
        windows = tuple(windows_of(planted_starts(30), PLANTED))
        base = replace(
            sim.default_params(),
            loss=base_loss,
            tank=replace(TANK, stratification_gap_tau_h=TAU),
        )
        fit = cal.StandbyFit(
            windows=windows,
            n_quiet=len(windows),
            n_dropped=0,
            ua_ref=UA,
            ua_exponent=0.0,
            tau_gap_hours=None,
            n_gap_windows=0,
            quiet_by="dhw_in_use",
        )
        frame = pd.DataFrame(
            {
                "upper_f": [130.0, 130.0],
                "lower_f": [130.0, 130.0],
                "compressor_on": False,
                "element_on": False,
                "dhw_in_use": False,
                "air_f": 60.0,
            },
            index=pd.DatetimeIndex([T0, T0 + timedelta(minutes=5)]),
        )
        with pytest.MonkeyPatch.context() as m:
            m.setattr(cal, "fit_standby", lambda *_, **__: fit)
            m.setattr(cal, "fit_gap_tau", lambda *_, **__: (None, 0))
            done, judged, held = sc._keep_better(frame, base, "air_f")
        (standby,) = [j for j in judged if j.group == "standby"]
        return done.params, standby, held, base

    def test_a_refit_with_the_bottom_loss_beats_a_jacket_law(self) -> None:
        jacket = replace(PLANTED, ua_btu_hr_f=5.0, bottom_loss_btu_hr=0.0)
        params, standby, held, _ = self._keep(jacket)
        assert standby.kept == "refit"
        assert standby.n_held == 6 == len(held.windows)
        assert standby.base_error is not None
        assert standby.refit_error is not None
        assert standby.refit_error < standby.base_error / 10
        assert params.loss.bottom_loss_btu_hr == pytest.approx(Q_B, rel=0.05)
        assert held.standby_tau_h == TAU

    def test_the_planted_law_stays(self) -> None:
        params, standby, held, base = self._keep(PLANTED)
        assert standby.base_error == pytest.approx(0.0, abs=1e-9)
        assert standby.kept == "base"
        assert params.loss == base.loss
        done = sc.Calibrated(
            cal.Calibration(params, cast_fit(), None, None, pd.DataFrame()),
            "constant",
            2,
            timedelta(minutes=5),
            0,
            (),
            judged=(standby,),
            held=held,
        )
        assert sc.score(done, base)["standby"] == pytest.approx(0.0, abs=1e-9)
        terms = {t.name: t for t in sc.report(done)}
        assert terms["Bottom loss (BTU/h)"].value == f"{Q_B:.3g}"
        assert terms["Bottom loss gate (°F)"].value == f"{GATE:.3g}"


def cast_fit() -> cal.StandbyFit:
    return cal.StandbyFit(
        windows=(),
        n_quiet=0,
        n_dropped=0,
        ua_ref=None,
        ua_exponent=None,
        tau_gap_hours=None,
        n_gap_windows=0,
        quiet_by="dhw_in_use",
    )


def quiet_history(
    starts: list[tuple[float, float, float, float]],
    loss: LossParams,
    tau: float = TAU,
) -> pd.DataFrame:
    """A history of quiet windows, one a day from each ``(upper, lower,
    air, hours)``, the probes the simulation's own walk on ``loss`` and
    ``tau`` a sample every 5 minutes, the rest of each day the
    compressor running."""
    rows: list[tuple[datetime, float, float, float, bool]] = []
    for day, (upper, lower, air, hours) in enumerate(starts):
        start = T0 + timedelta(days=day)
        walked = project_decay(
            upper,
            lower,
            _air(air, hours, start),
            cast_ua(loss),
            tau,
            start + timedelta(hours=hours),
            start,
            tank=TANK,
            bottom_loss_btu_hr=loss.bottom_loss_btu_hr,
            bottom_gate_f=loss.bottom_gate_f,
        )
        for at, up, lo in walked.trajectory:
            rows.append((at, up, lo, air, False))
        t = walked.trajectory[-1][0] + timedelta(minutes=5)
        while t < start + timedelta(days=1):
            rows.append((t, 125.0, 125.0, air, True))
            t += timedelta(minutes=30)
    frame = pd.DataFrame(
        [r[1:] for r in rows],
        columns=["upper_f", "lower_f", "air_f", "compressor_on"],
        index=pd.DatetimeIndex([r[0] for r in rows]),
    )
    frame["element_on"] = False
    frame["dhw_in_use"] = False
    return frame


class TestTheWholeStandbyFit:
    def test_it_recovers_the_loss_and_the_gaps_constant(self) -> None:
        # Windows opening with a draw's wide gap relax on the constant;
        # those opening 2-8 °F apart widen under the bottom loss.
        starts = planted_starts(30) + [
            (140.0, 122.0 + i, 55.0 + i, 10.0) for i in range(12)
        ]
        planted_tau = 25.0
        history = quiet_history(starts, PLANTED, planted_tau)
        fit = cal.fit_standby(history, TANK.thermal_mass_btu_f, tank=TANK)
        assert fit.tau_gap_hours is not None
        assert fit.tau_gap_hours == pytest.approx(planted_tau, rel=0.1)
        assert fit.ua_ref == pytest.approx(UA, rel=0.05)
        assert fit.bottom_loss_btu_hr == pytest.approx(Q_B, rel=0.1)
        # Read as a pure relaxation, the widening gaps drag the constant
        # far off.
        unforced, _ = cal.fit_gap_tau(
            [(w.gap_hours, w.gap_f) for w in fit.windows]
        )
        assert unforced is not None
        assert abs(unforced - planted_tau) > abs(
            fit.tau_gap_hours - planted_tau
        )


class TestTheGapIsJudgedFirst:
    def test_a_rejected_gap_constant_does_not_fit_the_loss(self) -> None:
        # The gap refit loses (the base's constant is the planted one,
        # the earlier windows relaxing on another), while the loss refit
        # wins on the UA: it is fitted and scored on the base's
        # constant, the one the parameters returned relax on.
        planted_tau = 25.0
        early = [(140.0, 122.0 + i % 4, 55.0, 10.0) for i in range(20)]
        base = replace(
            sim.default_params(),
            loss=replace(PLANTED, ua_btu_hr_f=5.0),
            tank=replace(TANK, stratification_gap_tau_h=planted_tau),
        )
        gap_windows = windows_of(early, PLANTED, tau=200.0)
        loss_windows = windows_of(planted_starts(30), PLANTED, tau=planted_tau)
        windows = tuple(
            replace(w, start=T0 + timedelta(days=i), end=w.end)
            for i, w in enumerate([*gap_windows, *loss_windows])
        )
        fit = cal.StandbyFit(
            windows=windows,
            n_quiet=len(windows),
            n_dropped=0,
            ua_ref=UA,
            ua_exponent=0.0,
            tau_gap_hours=None,
            n_gap_windows=0,
            quiet_by="dhw_in_use",
        )
        frame = pd.DataFrame(
            {
                "upper_f": [130.0, 130.0],
                "lower_f": [130.0, 130.0],
                "compressor_on": False,
                "element_on": False,
                "dhw_in_use": False,
                "air_f": 60.0,
            },
            index=pd.DatetimeIndex([T0, T0 + timedelta(minutes=5)]),
        )
        with pytest.MonkeyPatch.context() as m:
            m.setattr(cal, "fit_standby", lambda *_, **__: fit)
            done, judged, held = sc._keep_better(frame, base, "air_f")
        groups = {j.group: j for j in judged}
        assert groups["gap_tau"].kept == "base"
        assert groups["standby"].kept == "refit"
        assert done.params.tank.stratification_gap_tau_h == planted_tau
        assert held.standby_tau_h == planted_tau
        assert done.params.loss.bottom_loss_btu_hr == pytest.approx(
            Q_B, rel=0.1
        )
