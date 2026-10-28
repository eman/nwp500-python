"""``sim.heat_pump_fit``: a heat pump's recoveries measured from a
history, recovered from a tank planted with a known heat, power, start
hold and stop."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from nwp500 import sim
from nwp500.sim import default_params
from nwp500.sim import heat_pump_fit as hpf
from nwp500.sim.calibration import heat_pump_cycles
from nwp500.sim.params import CompressorParams, LossParams
from nwp500.sim.units import WATER_BTU_PER_GAL_F

T0 = datetime(2026, 3, 2, tzinfo=UTC)
#: The planted tank loses through its jacket alone.
PARAMS = replace(
    default_params(),
    loss=LossParams(ua_side_btu_hr_f=4.4, ua_bottom_btu_hr_f=0.0),
)
MASS = PARAMS.tank.volume_gal * WATER_BTU_PER_GAL_F
TARGET = 140.0
OVERSHOOT = 1.2
STEP_S = 30.0
QUANTUM = 0.18


def heat(air: float, water: float) -> float:
    return 4230.0 + 33.0 * (air - 65.0) - 2.0 * (water - 120.0)


def power(water: float) -> float:
    return 406.0 + 2.33 * (water - 120.0)


def hold(minutes_off: float) -> float:
    for edge, value in ((15, 3.0), (60, 4.5), (180, 11.5), (720, 11.4)):
        if minutes_off < edge:
            return value
    return 17.8


def _quantised(x: float, rng: np.random.Generator) -> float:
    return round((x + rng.normal(0.0, 0.03)) / QUANTUM) * QUANTUM


def planted(
    cycles: list[tuple[float, float, float]],
    *,
    draw_in: int | None = None,
    seed: int = 7,
) -> pd.DataFrame:
    """A history of ``cycles``, each ``(minutes off before it, the
    tank's temperature at its start, the air)``: a mixed tank with its
    probes 0.5 °F either side of its mean, sampled every 30 s with a few
    seconds' jitter and 0.18 °F steps; each run holding for ``hold``,
    then heating at ``heat`` less the jacket's loss and drawing
    ``power``, stopping ``OVERSHOOT`` past the target. ``draw_in``: the
    cycle a draw flag is set through."""
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    t = T0
    water = cycles[0][1]
    for k, (off, start_f, air) in enumerate(cycles):
        # Off: the tank brought to the next start, the compressor idle.
        n_off = int(off * 60 / STEP_S)
        for i in range(n_off):
            w = water + (start_f - water) * i / max(n_off, 1)
            rows.append(
                _row(t, w + 0.25, w - 0.25, False, air, math.nan, False, rng)
            )
            t += timedelta(seconds=STEP_S)
        water = start_f
        began = t
        while True:
            minutes = (t - began).total_seconds() / 60.0
            if minutes >= hold(off):
                q = heat(air, water) - 4.4 * (water - air)
                water += q / MASS * STEP_S / 3600.0
                lower = water - 0.25
            else:
                # The lower probe dips at the start, then holds.
                lower = water - 0.25 - (QUANTUM if minutes < 1.0 else 0.0)
            rows.append(
                _row(
                    t,
                    water + 0.25,
                    lower,
                    True,
                    air,
                    power(water),
                    k == draw_in,
                    rng,
                )
            )
            t += timedelta(seconds=STEP_S)
            if lower >= TARGET + OVERSHOOT:
                break
    rows.append(
        _row(t, water + 0.25, water - 0.25, False, 65.0, math.nan, False, rng)
    )
    frame = pd.DataFrame(rows)
    return frame.set_index("at")


def _row(
    t: datetime,
    upper: float,
    lower: float,
    on: bool,
    air: float,
    watts: float,
    drawing: bool,
    rng: np.random.Generator,
) -> dict[str, object]:
    jitter = timedelta(seconds=float(rng.uniform(-3.0, 3.0)))
    return {
        "at": t + jitter,
        "upper_f": _quantised(upper, rng),
        "lower_f": _quantised(lower, rng),
        "compressor_on": on,
        "element_on": False,
        "dhw_in_use": drawing,
        "target_f": TARGET,
        "excluded": False,
        "power_w": watts + rng.normal(0.0, 2.0) if on else 0.0,
        "energy_to_setpoint_wh": math.nan,
        "air_f": air,
        "humidity_pct": 50.0,
    }


#: Off times across the bands; starts in the middle of a probe step.
CYCLES = [
    (900.0, 110.07, 60.0),
    (8.0, 138.99, 70.0),
    (40.0, 136.11, 55.0),
    (120.0, 130.89, 80.0),
    (400.0, 120.09, 65.0),
    (10.0, 139.17, 75.0),
    (1000.0, 100.17, 58.0),
    (30.0, 137.97, 62.0),
]


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return hpf.recovery_frame(planted(CYCLES))


class TestTheFrame:
    def test_each_run_on_a_minute_grid(self, frame: pd.DataFrame) -> None:
        assert frame["cycle"].nunique() == len(CYCLES)
        steps = frame.groupby("cycle")["minute"].diff().dropna()
        assert (steps == 1.0).all()

    def test_the_phases_in_order(self, frame: pd.DataFrame) -> None:
        order = {p: i for i, p in enumerate(hpf.PHASES)}
        for _, g in frame.groupby("cycle"):
            ranks = g["phase"].map(order).to_numpy()
            assert (np.diff(ranks) >= 0).all()
            assert set(g["phase"]) == set(hpf.PHASES)

    def test_the_tank_is_mixed(self, frame: pd.DataFrame) -> None:
        assert frame["mixed"].all()

    def test_the_minutes_off(self, frame: pd.DataFrame) -> None:
        off = frame.drop_duplicates("cycle")["minutes_off"].to_numpy(float)
        assert math.isnan(off[0])
        assert off[1:] == pytest.approx([c[0] for c in CYCLES[1:]], abs=0.2)

    def test_each_minute_is_the_cycle_s_own(self, frame: pd.DataFrame) -> None:
        starts = {c.start for c in heat_pump_cycles(planted(CYCLES))}
        firsts = frame.drop_duplicates("cycle")["at"]
        assert set(firsts.dt.to_pydatetime()) == starts

    def test_a_draw_inside_a_minute_wets_it(self) -> None:
        history = planted(CYCLES[3:5])
        start = heat_pump_cycles(history)[1].start
        # One sample, past the minute's start.
        inside = history.index[
            history.index > start + timedelta(minutes=40, seconds=20)
        ][0]
        history.loc[inside, "dhw_in_use"] = True
        f = hpf.recovery_frame(history)
        wet = f.loc[f["water"], "at"]
        assert len(wet) >= 1
        assert (wet - pd.Timestamp(inside)).abs().min() < timedelta(minutes=1)


class TestTheRuns:
    def test_a_run_open_at_either_end_is_none(self) -> None:
        history = planted(CYCLES[:3])
        cycles = heat_pump_cycles(history)
        # Cut inside the last run, and from inside the first.
        cut = history.loc[
            (history.index > cycles[0].start + timedelta(minutes=30))
            & (history.index < cycles[2].end - timedelta(minutes=5))
        ]
        assert [c.start for c in heat_pump_cycles(cut)] == [cycles[1].start]

    def test_a_gap_since_the_last_stop_is_no_time_off(self) -> None:
        history = planted(CYCLES[3:5])
        first, _ = heat_pump_cycles(history)
        history["unrecorded"] = False
        between = (history.index > first.end) & (
            history.index < first.end + timedelta(minutes=10)
        )
        history.loc[between, "unrecorded"] = True
        assert heat_pump_cycles(history)[1].stopped_at is None
        f = hpf.recovery_frame(history)
        assert f.drop_duplicates("cycle")["minutes_off"].isna().all()

    def test_a_flag_before_the_lead_leaves_a_start_clean(self) -> None:
        history = planted(CYCLES[3:5])
        start = heat_pump_cycles(history)[1].start
        early = (history.index > start - timedelta(minutes=40)) & (
            history.index < start - timedelta(minutes=31)
        )
        history.loc[early, "dhw_in_use"] = True
        (cycle,) = [c for c in heat_pump_cycles(history) if c.start == start]
        holds = hpf.start_holds(hpf.recovery_frame(history))
        assert cycle.draw_free
        assert holds["start_clean"].tolist() == [True, True]


class TestTheHold:
    def test_each_hold_by_its_minutes_off(self, frame: pd.DataFrame) -> None:
        holds = hpf.start_holds(frame)
        want = [hold(off) for off, _, _ in CYCLES]
        # Read on the minute grid, at the first 0.18 °F step of a slow
        # climb: up to a few minutes late, never early.
        late = holds["hold_minutes"].to_numpy() - want
        assert late.min() >= -0.5
        assert late.max() <= 3.0
        assert holds["draw_free"].all()

    def test_a_step_and_back_is_not_the_climb(self) -> None:
        history = planted(CYCLES[:2])
        start = heat_pump_cycles(history)[1].start
        after = history.index > start + timedelta(minutes=1)
        flip = after & (history.index < start + timedelta(minutes=2))
        history.loc[flip, "lower_f"] += 2 * QUANTUM
        holds = hpf.start_holds(hpf.recovery_frame(history))
        assert holds["hold_minutes"].iloc[1] >= hold(CYCLES[1][0])

    def test_water_at_the_start_is_no_clean_start(self) -> None:
        history = planted(CYCLES[3:5])
        start = heat_pump_cycles(history)[1].start
        near = abs(history.index - start) < timedelta(minutes=2)
        history.loc[near, "dhw_in_use"] = True
        holds = hpf.start_holds(hpf.recovery_frame(history))
        assert holds["start_clean"].tolist() == [True, False]


class TestTheRunOn:
    def test_the_stop_is_the_overshoot(self, frame: pd.DataFrame) -> None:
        found, fit = hpf.run_ons(frame)
        assert len(found) == len(CYCLES)
        assert fit.n == len(CYCLES)
        assert fit.overshoot_f == pytest.approx(OVERSHOOT, abs=0.2)
        assert fit.minutes == pytest.approx(10.0, abs=1.5)

    def test_the_rule_that_stopped_it_fits_better(self) -> None:
        # The air apart, so the run-on's rate is: a stop at an overshoot
        # is no fixed number of minutes.
        cycles = [
            (60.0, 130.05 + i * 0.18, (50.0, 90.0)[i % 2]) for i in range(8)
        ]
        _, fit = hpf.run_ons(hpf.recovery_frame(planted(cycles)))
        assert fit.overshoot_mae_min is not None
        assert fit.minutes_mae_min is not None
        assert fit.overshoot_mae_min < fit.minutes_mae_min

    def test_a_run_on_that_never_climbs_is_left_out_of_both(
        self, frame: pd.DataFrame
    ) -> None:
        flat = frame.copy()
        one = (flat["cycle"] == flat["cycle"].iloc[0]) & (
            flat["phase"] == "run_on"
        )
        flat.loc[one, "lower_f"] = flat.loc[one, "lower_f"].iloc[0]
        _, fit = hpf.run_ons(flat)
        _, whole = hpf.run_ons(frame)
        assert fit.unstopped == 1
        assert whole.unstopped == 0
        assert fit.minutes_mae_min != whole.minutes_mae_min

    def test_too_few_to_judge(self) -> None:
        _, fit = hpf.run_ons(hpf.recovery_frame(planted(CYCLES[:2])))
        assert fit.n == 2
        assert fit.minutes is not None
        assert fit.minutes_mae_min is None


class TestTheHeat:
    def test_the_planted_heat_and_power(self, frame: pd.DataFrame) -> None:
        got = hpf.climb_heat(frame, PARAMS)
        # The top-offs from near the target climb for under 20 minutes.
        assert len(got) >= 4
        for r in got.itertuples():
            assert r.heat_btu_h == pytest.approx(  # type: ignore[attr-defined]
                heat(r.air_f, r.water_f),  # type: ignore[attr-defined]
                rel=0.04,
            )
            assert r.power_w == pytest.approx(power(r.water_f), abs=6.0)  # type: ignore[attr-defined]
            assert r.cop == pytest.approx(  # type: ignore[attr-defined]
                r.heat_btu_h / (r.power_w * 3.412141633),  # type: ignore[attr-defined]
            )

    def test_the_ends_loss_is_priced(self, frame: pd.DataFrame) -> None:
        """The heat is what the tank kept plus what it lost: through its
        sides, its bottom and its top, the tank mixed."""
        ends = replace(
            PARAMS,
            loss=replace(
                PARAMS.loss, ua_bottom_btu_hr_f=1.5, ua_top_btu_hr_f=0.5
            ),
        )
        plain = hpf.climb_heat(frame, PARAMS)
        more = hpf.climb_heat(frame, ends)
        added = more["heat_btu_h"] - plain["heat_btu_h"]
        assert added.to_numpy() == pytest.approx(
            (2.0 * (plain["water_f"] - plain["air_f"])).to_numpy()
        )

    def test_the_air_raises_the_heat(self, frame: pd.DataFrame) -> None:
        got = hpf.climb_heat(frame, PARAMS)
        slope = np.polyfit(got["air_f"], got["heat_btu_h"], 1)[0]
        assert slope == pytest.approx(33.0, abs=10.0)

    def test_a_run_with_a_draw_gives_none(self) -> None:
        history = planted(CYCLES[3:5], draw_in=0)
        cycles = heat_pump_cycles(history)
        assert [c.draw_free for c in cycles] == [False, True]
        got = hpf.climb_heat(hpf.recovery_frame(history), PARAMS)
        assert set(got["cycle"]) <= {cycles[1].n}


class TestThePower:
    def test_blocks_at_the_planted_power(self, frame: pd.DataFrame) -> None:
        got = hpf.power_blocks(frame)
        assert len(got) > 50
        water = (got["upper_f"] + got["lower_f"]) / 2.0
        assert np.abs(got["power_w"] - water.map(power)).max() < 5.0
        assert set(got["phase"]) <= set(hpf.PHASES)


@pytest.fixture(scope="module")
def found() -> hpf.Evidence:
    """Three passes of ``CYCLES``: enough of each measure to fit."""
    return hpf.evidence(planted(CYCLES * 3, seed=11), PARAMS)


class TestTheFits:
    def test_the_evidence_in_time_order(self, found: hpf.Evidence) -> None:
        for rows in (found.heat, found.power, found.holds, found.runs):
            assert rows["start"].is_monotonic_increasing
        assert (found.power["phase"] == "climb").all()
        assert found.holds["minutes_off"].notna().all()

    def test_it_recovers_the_planted_heat_pump(
        self, found: hpf.Evidence
    ) -> None:
        fit = hpf.fit_heat_pump(found, CompressorParams())
        assert fit.n_heat >= hpf.MIN_HEAT_STRETCHES
        assert fit.heat is not None and fit.power is not None
        assert fit.heat.level == pytest.approx(heat(65.0, 120.0), rel=0.03)
        assert fit.heat.per_air == pytest.approx(33.0, abs=10.0)
        # The power is read at the lower probe, a quarter degree under
        # the planted tank's mean.
        assert fit.power.level == pytest.approx(power(120.25), abs=2.0)
        assert fit.power.per_water == pytest.approx(2.33, abs=0.1)
        assert fit.power.per_air == pytest.approx(0.0, abs=0.2)
        assert fit.overshoot_f == pytest.approx(OVERSHOOT, abs=0.2)
        assert fit.violations == ()
        # Each plane is read over what it was fitted on.
        water = found.heat["water_f"]
        assert fit.heat.water_f == (
            math.floor(water.min()),
            math.ceil(water.max()),
        )
        applied = hpf.with_planes(CompressorParams(), fit.heat, fit.power)
        assert applied.heat_domain_water_f == fit.heat.water_f
        assert applied.power_domain_air_f == fit.power.air_f
        assert fit.heat_error is not None and fit.heat_error < 200.0

    def test_a_band_with_its_starts_takes_their_hold(
        self, found: hpf.Evidence
    ) -> None:
        c = CompressorParams()
        held = hpf.fit_start_hold(found.holds, c)
        assert held is not None
        band = np.searchsorted(
            c.start_hold_after_min, found.holds["minutes_off"], side="right"
        )
        for i, value in enumerate(held):
            n = int((band == i).sum())
            if n >= hpf.MIN_BAND_STARTS:
                # The band's planted hold, read on the minute grid at the
                # first 0.18 °F step of a slow climb: up to a few minutes
                # late, never early (``TestTheHold``).
                edge = (15, 60, 180, 720, math.inf)[i] - 1e-9
                assert -0.5 <= value - hold(edge) <= 3.0
            else:
                assert value == c.start_hold_min[i]

    def test_too_little_fits_nothing(self) -> None:
        empty = hpf.evidence(planted(CYCLES[:2]), PARAMS)
        fit = hpf.fit_heat_pump(empty, CompressorParams())
        assert fit.heat is None and fit.power is None
        assert fit.overshoot_f is None
        base = sim.default_params()
        assert hpf.with_heat_pump(base, fit) == base

    def test_a_fit_applies_where_it_had_the_evidence(
        self, found: hpf.Evidence
    ) -> None:
        fit = hpf.fit_heat_pump(found, CompressorParams())
        got = hpf.with_heat_pump(sim.default_params(), fit)
        assert fit.heat is not None and fit.overshoot_f is not None
        assert got.compressor.heat_btu_h == fit.heat.level
        assert got.controller.hp_stop_overshoot_f == fit.overshoot_f
        claims = replace(fit, heat_violations=("cop_over_carnot",))
        base = sim.default_params()
        kept = hpf.with_heat_pump(base, claims)
        assert kept.compressor.heat_btu_h == base.compressor.heat_btu_h
        assert kept.compressor.power_w == base.compressor.power_w

    def test_the_errors_are_the_maps_own(self, found: hpf.Evidence) -> None:
        c = CompressorParams()
        fit = hpf.fit_heat_pump(found, c)
        better = hpf.with_planes(c, fit.heat, fit.power)
        heat_before = hpf.heat_map_error(found.heat, c)
        heat_after = hpf.heat_map_error(found.heat, better)
        assert heat_before is not None and heat_after is not None
        assert heat_after < heat_before
        assert hpf.start_hold_error(found.holds.iloc[0:0], c) is None
        assert hpf.overshoot_error(found.runs, OVERSHOOT) == pytest.approx(
            0.0, abs=0.2
        )
