"""The calibrated tank the engine walks (``nwp500.sim.tank_physics``) and
the served recovery under it (``nwp500.sim.heat_pump_recovery``)."""

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from nwp500.sim.heat_pump_recovery import (  # noqa: E402
    PHYSICS_TRUNCATED,
    ModelDuration,
    PhysicsRecovery,
    RecoveryContext,
    recovery,
)
from nwp500.sim.params import HeaterParams, params_from_document  # noqa: E402
from nwp500.sim.tank_physics import TankPhysics  # noqa: E402

FIXTURES = Path(__file__).with_name("fixtures") / "sim"
T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)


def _params() -> HeaterParams:
    doc = json.loads((FIXTURES / "heater_params.json").read_text())
    return params_from_document(doc)


def _ambient() -> Any:
    stamps = pd.date_range(
        T0 - timedelta(hours=1), T0 + timedelta(hours=12), freq="10min"
    )
    return pd.DataFrame({"ambient_f": 68.0}, index=stamps)


def _physics(params: HeaterParams | None = None, **kw: Any) -> TankPhysics:
    kw.setdefault("draws_on", True)
    return TankPhysics(
        params or _params(), _ambient(), 50.0, tau_gap_hours=10.0, **kw
    )


class _Model:
    """A model that answers every recovery with ``reasons``."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons

    def duration(self, ctx: RecoveryContext) -> ModelDuration:
        return ModelDuration(
            minutes=120.0,
            start_hold_minutes=0.0,
            confidence=1.0,
            reasons=self.reasons,
        )


def _context(*, truncated: bool) -> RecoveryContext:
    return RecoveryContext(
        t_start_lower=100.0,
        t_start_upper=125.0,
        target_f=140.0,
        t_amb_start=68.0,
        t_amb_mean=68.0,
        h_amb_start=50.0,
        physics=PhysicsRecovery(
            minutes=1800.0 if truncated else 150.0,
            truncated=truncated,
            path=None,
            estimate=1800.0 if truncated else 150.0,
        ),
    )


class TestDraws:
    def test_with_draws_off_a_draw_moves_nothing(self):
        assert _physics(draws_on=False).draw(T0, 130.0, 110.0, 10.0) == (
            130.0,
            110.0,
        )

    def test_a_draw_cools_the_tank(self):
        upper, lower = _physics().draw(T0, 130.0, 110.0, 10.0)
        assert upper + lower < 240.0

    def test_a_larger_tank_loses_less_to_the_same_draw(self):
        p = _params()
        big = dataclasses.replace(
            p, tank=dataclasses.replace(p.tank, volume_gal=80.0)
        )
        small_drop = 240.0 - sum(_physics(p).draw(T0, 130.0, 110.0, 10.0))
        big_drop = 240.0 - sum(_physics(big).draw(T0, 130.0, 110.0, 10.0))
        assert big_drop == pytest.approx(
            small_drop * p.tank.volume_gal / 80.0, rel=0.02
        )


class TestRecoveryReasons:
    def test_a_models_reasons_reach_the_heat(self):
        heat = _physics(recovery_model=_Model(("model_extrapolated",))).heat(
            T0, 125.0, 100.0, 140.0
        )
        assert heat is not None
        assert "model_extrapolated" in heat.reasons

    def test_low_confidence_is_added_not_substituted(self):
        heat = _physics(
            recovery_model=_Model(("model_extrapolated",)),
            low_confidence_floor=2.0,
        ).heat(T0, 125.0, 100.0, 140.0)
        assert heat is not None
        assert heat.reasons == ("model_extrapolated", "recovery_low_confidence")


class TestTruncatedPhysics:
    def test_alone_it_is_no_recovery(self):
        """The bound is not a duration, and nothing reached the target."""
        assert recovery(_context(truncated=True)) is None

    def test_a_converged_one_is_served(self):
        served = recovery(_context(truncated=False))
        assert served is not None
        assert served.minutes == 150.0

    def test_a_model_given_it_says_so(self):
        served = recovery(_context(truncated=True), model=_Model(("m",)))
        assert served is not None
        assert served.reasons == ("m", PHYSICS_TRUNCATED)
        assert served.path is None


class TestTheAmbientSeries:
    """The replacement review of #162: an absent ``ambient_f`` column
    is an error, not a silent coast at the default air."""

    def test_an_absent_column_is_an_error(self):
        from nwp500.sim.decay import AmbientSampler, project_decay
        from nwp500.sim.defaults import default_params

        stamps = pd.date_range(T0, periods=4, freq="1h")
        wrong = pd.DataFrame({"temp_f": 55.0}, index=stamps)
        with pytest.raises(ValueError, match="ambient_f"):
            AmbientSampler(wrong)
        with pytest.raises(ValueError, match="ambient_f"):
            project_decay(
                130.0, 120.0, wrong, 3.0, 60.0, T0 + timedelta(hours=2), T0
            )
        with pytest.raises(ValueError, match="ambient_f"):
            TankPhysics(
                default_params(),
                pd.DataFrame(),
                None,
                draws_on=False,
                tau_gap_hours=60.0,
            )

    def test_no_usable_reading_is_the_default_said(self):
        from nwp500.sim.decay import AmbientSampler, project_decay
        from nwp500.sim.units import DEFAULT_AMBIENT_F

        stamps = pd.date_range(T0, periods=4, freq="1h")
        missing = pd.DataFrame({"ambient_f": float("nan")}, index=stamps)
        assert AmbientSampler(missing).defaulted
        assert AmbientSampler(missing).at(T0) == DEFAULT_AMBIENT_F
        out = project_decay(
            130.0, 120.0, missing, 3.0, 60.0, T0 + timedelta(hours=2), T0
        )
        assert out.ambient_defaulted
        assert out.t_amb_mean == pytest.approx(DEFAULT_AMBIENT_F)
        given = project_decay(
            130.0,
            120.0,
            pd.DataFrame({"ambient_f": 56.0}, index=stamps),
            3.0,
            60.0,
            T0 + timedelta(hours=2),
            T0,
        )
        assert not given.ambient_defaulted
        assert given.t_amb_mean == pytest.approx(56.0)
