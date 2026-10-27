"""The calibrated tank the engine walks (``nwp500.sim.tank_physics``) and
the served recovery under it (``nwp500.sim.heat_pump_recovery``)."""

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from nwp500.sim.circulation import Circulation
from nwp500.sim.heat_pump_recovery import (
    PHYSICS_TRUNCATED,
    RATE_SCALE_RANGE,
    ModelDuration,
    PhysicsRecovery,
    RecoveryContext,
    rate_scale,
)
from nwp500.sim.params import (
    CirculationParams,
    HeaterParams,
    params_from_document,
)
from nwp500.sim.physics import stratified as st
from nwp500.sim.tank_physics import (
    CompressorRun,
    Running,
    TankPhysics,
    circulation_flows,
    point_at,
)
from nwp500.sim.units import BTU_PER_WH

FIXTURES = Path(__file__).with_name("fixtures") / "sim"
T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)


def _params() -> HeaterParams:
    doc = json.loads((FIXTURES / "heater_params.json").read_text())
    return params_from_document(doc)


def _ambient() -> Any:
    stamps = pd.date_range(
        T0 - timedelta(hours=1), T0 + timedelta(hours=30), freq="10min"
    )
    return pd.DataFrame({"ambient_f": 68.0}, index=stamps)


def _physics(params: HeaterParams | None = None, **kw: Any) -> TankPhysics:
    kw.setdefault("draws_on", True)
    return TankPhysics(params or _params(), _ambient(), 50.0, **kw)


class _Model:
    """A model that answers every recovery ``minutes`` long, the
    physics' hold included, with ``reasons``."""

    def __init__(
        self,
        reasons: tuple[str, ...] = (),
        *,
        minutes: float | None = None,
        clamped: bool = False,
        confidence: float = 1.0,
    ) -> None:
        self.reasons = reasons
        self.minutes = minutes
        self.clamped = clamped
        self.confidence = confidence
        self.asked: list[RecoveryContext] = []

    def duration(self, ctx: RecoveryContext) -> ModelDuration:
        self.asked.append(ctx)
        hold = ctx.start_hold_minutes
        climb = ctx.physics.minutes if self.minutes is None else self.minutes
        return ModelDuration(
            minutes=hold + climb,
            start_hold_minutes=hold,
            confidence=self.confidence,
            reasons=self.reasons,
            clamped=self.clamped,
        )


def _context(physics: PhysicsRecovery) -> RecoveryContext:
    return RecoveryContext(
        t_start_lower=100.0,
        t_start_upper=125.0,
        layers_f=(100.0,) * 12,
        target_f=140.0,
        t_amb_start=68.0,
        t_amb_mean=68.0,
        h_amb_start=50.0,
        physics=physics,
    )


def _heat(state: object, physics: TankPhysics) -> float:
    assert isinstance(state, st.TankState)
    return st.energy_btu(physics.layout, state)


class TestDraws:
    def test_with_draws_off_a_draw_moves_nothing(self) -> None:
        physics = _physics(draws_on=False)
        state = physics.estimate(130.0, 110.0)
        assert physics.draw(T0, state, 10.0) == state

    def test_a_draw_cools_the_tank(self) -> None:
        physics = _physics()
        state = physics.estimate(130.0, 110.0)
        after = physics.draw(T0, state, 10.0)
        assert _heat(after, physics) < _heat(state, physics)
        assert physics.observe(after)[1] < 110.0

    def test_a_walk_takes_its_draws_at_their_instants(self) -> None:
        physics = _physics()
        state = physics.estimate(130.0, 110.0)
        at = T0 + timedelta(minutes=17)
        got = physics.advance(T0, state, T0 + timedelta(hours=1), [(at, 8.0)])
        assert got.draw_volume_gal == 8.0
        assert got.draw_heat_btu > 0.0
        assert [i.at for i in got.impulses] == [at]
        assert got.impulses[0].lower_after is not None
        assert got.impulses[0].lower_after < got.impulses[0].lower_before


class TestAdvance:
    def test_the_compressor_charges_its_electricity_on_the_points(
        self,
    ) -> None:
        physics = _physics()
        state = physics.estimate(125.0, 100.0)
        on = Running(compressor=CompressorRun(on_at=T0, heats_at=T0))
        got = physics.advance(T0, state, T0 + timedelta(hours=1), running=on)
        assert got.points[0].input_wh == 0.0
        assert sum(p.input_wh or 0.0 for p in got.points) > 300.0
        assert _heat(got.state, physics) > _heat(state, physics)

    def test_uncredited_it_is_charged_and_heats_nothing(self) -> None:
        physics = _physics()
        state = physics.estimate(125.0, 100.0)
        end = T0 + timedelta(hours=1)
        run = CompressorRun(on_at=T0, heats_at=T0)
        withheld = physics.advance(
            T0, state, end, running=Running(compressor=run, credited=False)
        )
        coast = physics.advance(T0, state, end)
        assert sum(p.input_wh or 0.0 for p in withheld.points) > 300.0
        # The same coast, on the heating's finer steps.
        assert physics.observe(withheld.state) == pytest.approx(
            physics.observe(coast.state), abs=0.05
        )

    def test_a_stop_ends_it_where_it_holds(self) -> None:
        physics = _physics()
        state = physics.estimate(125.0, 100.0)
        on = Running(compressor=CompressorRun(on_at=T0, heats_at=T0))
        got = physics.advance(
            T0,
            state,
            T0 + timedelta(hours=8),
            running=on,
            stop=lambda _u, lower: lower >= 110.0,
        )
        assert got.stopped
        assert got.points[-1].lower_f >= 110.0
        assert got.points[-2].lower_f < 110.0

    def test_a_split_walk_is_the_whole(self) -> None:
        physics = _physics()
        state = physics.estimate(130.0, 110.0)
        mid, end = T0 + timedelta(hours=2), T0 + timedelta(hours=5)
        whole = physics.advance(T0, state, end)
        first = physics.advance(T0, state, mid)
        rest = physics.advance(mid, first.state, end)
        assert physics.observe(rest.state) == pytest.approx(
            physics.observe(whole.state), abs=1e-9
        )


class TestTheRecovery:
    def test_it_reaches_its_target(self) -> None:
        physics = _physics()
        state = physics.estimate(125.0, 100.0)
        got = physics.recovery(T0, state, 130.0)
        assert not got.truncated
        assert got.estimate == got.minutes
        assert 60.0 < got.minutes < 600.0

    def test_served_with_no_model_it_is_the_hold_and_the_climb(self) -> None:
        physics = _physics()
        state = physics.estimate(125.0, 100.0)
        alone = physics.recovery(T0, state, 130.0, hold_minutes=10.0)
        got = physics.recover(T0, state, 130.0, hold_minutes=10.0)
        assert got.reached
        assert got.minutes == pytest.approx(10.0 + alone.minutes)
        assert got.start_hold_minutes == 10.0
        assert got.confidence == 1.0
        assert got.model is None

    def test_a_model_paces_the_heat_pump(self) -> None:
        """A model's longer duration is a smaller scale on the heat, and
        the recovery then takes the model's time."""
        physics = _physics()
        state = physics.estimate(125.0, 100.0)
        alone = physics.recovery(T0, state, 130.0)
        slow = _physics(recovery_model=_Model(minutes=1.5 * alone.minutes))
        got = slow.recover(T0, state, 130.0)
        assert got.model is not None
        assert got.minutes == pytest.approx(1.5 * alone.minutes, rel=0.01)
        assert got.physics.minutes == pytest.approx(alone.minutes)

    def test_a_clamped_answer_keeps_the_physics_pace(self) -> None:
        physics = _physics()
        state = physics.estimate(125.0, 100.0)
        alone = physics.recover(T0, state, 130.0)
        clamped = _physics(recovery_model=_Model(minutes=1.0, clamped=True))
        got = clamped.recover(T0, state, 130.0)
        assert got.minutes == pytest.approx(alone.minutes)

    def test_the_model_is_asked_with_the_layers(self) -> None:
        model = _Model()
        physics = _physics(recovery_model=model)
        state = physics.estimate(125.0, 100.0)
        physics.recover(T0, state, 130.0, hold_minutes=5.0)
        ctx = model.asked[0]
        assert isinstance(state, st.TankState)
        assert ctx.layers_f == state.layers_f
        assert ctx.start_hold_minutes == 5.0
        assert (ctx.t_start_upper, ctx.t_start_lower) == pytest.approx(
            (125.0, 100.0)
        )

    def test_a_models_reasons_reach_it(self) -> None:
        physics = _physics(recovery_model=_Model(("model_extrapolated",)))
        got = physics.recover(T0, physics.estimate(125.0, 100.0), 130.0)
        assert "model_extrapolated" in got.reasons

    def test_low_confidence_is_added_not_substituted(self) -> None:
        physics = _physics(
            recovery_model=_Model(("model_extrapolated",), confidence=0.5),
            low_confidence_floor=0.6,
        )
        got = physics.recover(T0, physics.estimate(125.0, 100.0), 130.0)
        assert got.reasons == ("model_extrapolated", "recovery_low_confidence")

    def test_short_of_its_target_it_says_so(self) -> None:
        """A heat pump too weak to keep up with the jacket."""
        p = _params()
        weak = dataclasses.replace(
            p,
            compressor=dataclasses.replace(
                p.compressor,
                heat_btu_h=20.0,
                heat_btu_h_per_air_f=0.0,
                heat_btu_h_per_water_f=0.0,
            ),
        )
        physics = _physics(weak)
        got = physics.recover(T0, physics.estimate(125.0, 100.0), 130.0)
        assert not got.reached
        assert got.physics.truncated
        assert got.physics.estimate is None
        assert PHYSICS_TRUNCATED in got.reasons

    def test_its_trajectory_is_its_walk(self) -> None:
        physics = _physics()
        got = physics.recover(
            T0, physics.estimate(125.0, 100.0), 130.0, hold_minutes=10.0
        )
        first, last = got.trajectory[0], got.trajectory[-1]
        assert (first.input_energy_wh, first.stored_energy_wh) == (0.0, 0.0)
        assert first.at == T0
        assert last.at == T0 + timedelta(minutes=got.minutes)
        assert last.t_lower_f >= 130.0 - 1e-3
        held = [
            p for p in got.trajectory[1:] if p.at <= T0 + timedelta(minutes=10)
        ]
        assert held
        assert all(p.cop is None and p.input_energy_wh for p in held)
        climbing = [p for p in got.trajectory if p.cop is not None]
        assert climbing
        assert all(1.0 < p.cop < 6.0 for p in climbing if p.cop is not None)
        stored = sum(p.stored_energy_wh for p in got.trajectory)
        assert stored * BTU_PER_WH > 0.0


class TestTheRateScale:
    def test_no_model_is_scale_one(self) -> None:
        got = rate_scale(
            _context(
                PhysicsRecovery(minutes=150.0, truncated=False, estimate=150.0)
            )
        )
        assert got.scale == 1.0
        assert got.reasons == ()

    def test_it_is_the_physics_over_the_models_climb(self) -> None:
        ctx = _context(
            PhysicsRecovery(minutes=150.0, truncated=False, estimate=150.0)
        )
        got = rate_scale(ctx, model=_Model(minutes=300.0))
        assert got.scale == pytest.approx(0.5)

    def test_it_is_held_to_its_range(self) -> None:
        ctx = _context(
            PhysicsRecovery(minutes=150.0, truncated=False, estimate=150.0)
        )
        assert (
            rate_scale(ctx, model=_Model(minutes=10.0)).scale
            == (RATE_SCALE_RANGE[1])
        )
        assert (
            rate_scale(ctx, model=_Model(minutes=6000.0)).scale
            == (RATE_SCALE_RANGE[0])
        )

    def test_a_truncated_physics_is_not_scaled_and_says_so(self) -> None:
        ctx = _context(
            PhysicsRecovery(minutes=960.0, truncated=True, estimate=None)
        )
        got = rate_scale(ctx, model=_Model(("m",), minutes=200.0))
        assert got.scale == 1.0
        assert got.reasons == ("m", PHYSICS_TRUNCATED)


class TestTheAmbientSeries:
    """An absent ``ambient_f`` column is an error, not a silent coast at
    the default air."""

    def test_an_absent_column_is_an_error(self) -> None:
        from nwp500.sim.decay import AmbientSampler
        from nwp500.sim.defaults import default_params

        stamps = pd.date_range(T0, periods=4, freq="1h")
        wrong = pd.DataFrame({"temp_f": 55.0}, index=stamps)
        with pytest.raises(ValueError, match="ambient_f"):
            AmbientSampler(wrong)
        with pytest.raises(ValueError, match="ambient_f"):
            TankPhysics(default_params(), pd.DataFrame(), None, draws_on=False)

    def test_no_usable_reading_is_the_default_said(self) -> None:
        from nwp500.sim.decay import AmbientSampler
        from nwp500.sim.units import DEFAULT_AMBIENT_F

        stamps = pd.date_range(T0, periods=4, freq="1h")
        missing = pd.DataFrame({"ambient_f": float("nan")}, index=stamps)
        assert AmbientSampler(missing).defaulted
        assert AmbientSampler(missing).at(T0) == DEFAULT_AMBIENT_F


class TestState:
    def test_the_probes_are_the_states_observation(self) -> None:
        physics = _physics()
        state = physics.estimate(130.0, 110.0)
        assert physics.observe(state) == pytest.approx((130.0, 110.0))
        coast = physics.advance(T0, state, T0 + timedelta(hours=3))
        for p in coast.points:
            assert p.state is not None
            assert physics.observe(p.state) == (p.upper_f, p.lower_f)

    def test_another_physics_state_is_refused(self) -> None:
        with pytest.raises(TypeError):
            _physics().observe((130.0, 110.0))

    def test_its_layers_are_as_many_as_it_lays_out(self) -> None:
        physics = _physics()
        n = physics.layout.layers
        state = physics.layers([120.0 + k for k in range(n)])
        assert isinstance(state, st.TankState)
        assert state.layers_f[-1] == 120.0 + n - 1
        with pytest.raises(ValueError, match="layers"):
            physics.layers([120.0] * (n + 1))

    def test_given_layers_are_mixed_where_they_invert(self) -> None:
        physics = _physics()
        n = physics.layout.layers
        state = physics.layers([130.0] + [120.0] * (n - 1))
        assert isinstance(state, st.TankState)
        assert list(state.layers_f) == sorted(state.layers_f)

    def test_a_path_keeps_its_state_on_its_points(self) -> None:
        physics = _physics()
        coast = physics.advance(
            T0, physics.estimate(130.0, 110.0), T0 + timedelta(hours=3)
        )
        a, b = coast.points[1], coast.points[2]
        assert point_at(coast.points, a.at).state is a.state
        assert point_at(coast.points, a.at + (b.at - a.at) / 2).state is None


class TestTheCirculation:
    TERMS = CirculationParams(
        flow_gpm=2.0,
        displaced_gal=4.0,
        return_rest_offset_f=5.0,
        return_cool_tau_h=1.0,
        loss_btu_per_gal=0.0,
    )

    def test_the_cooled_water_comes_back_first(self) -> None:
        run = (T0, T0 + timedelta(minutes=10))
        got = circulation_flows(
            Circulation((run,)), self.TERMS, lambda _: 60.0, T0, run[1]
        )
        assert [(f.start, f.end, f.inflow_f) for f in got] == [
            (T0, T0 + timedelta(minutes=2), 65.0),
            (T0 + timedelta(minutes=2), run[1], None),
        ]

    def test_a_run_soon_after_another_finds_the_pipe_warm(self) -> None:
        a = (T0, T0 + timedelta(minutes=10))
        b = (T0 + timedelta(minutes=40), T0 + timedelta(minutes=50))
        got = circulation_flows(
            Circulation((a, b)), self.TERMS, lambda _: 60.0, b[0], b[1]
        )
        cooled = got[0]
        assert cooled.inflow_f == 65.0
        assert cooled.end - cooled.start < timedelta(minutes=2)

    def test_its_runs_cool_the_tank(self) -> None:
        run = (T0, T0 + timedelta(minutes=10))
        alone = _physics()
        state = alone.estimate(130.0, 110.0)
        end = T0 + timedelta(hours=1)
        circulating = _physics(
            circulation=Circulation((run,)), circulation_terms=self.TERMS
        ).advance(T0, state, end)
        quiet = alone.advance(T0, state, end)
        assert circulating.flowing_heat_btu > 0.0
        assert _heat(circulating.state, alone) < _heat(quiet.state, alone)
