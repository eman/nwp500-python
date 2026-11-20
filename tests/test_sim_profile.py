"""The heater's profile (``sim.profile``), and a kept recovery aged to
now (``recovery_as_of``).

Held to their source by the parity checks run with the port; these
hold their rules.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from nwp500 import heater
from nwp500.sim import profile as P
from nwp500.sim import recovery_as_of
from nwp500.sim.params import TankParams
from nwp500.sim.ready import Recovery


@dataclass(frozen=True)
class _Limits:
    """A setpoint range in half degrees Celsius, as a device's features
    hold it."""

    dhw_temperature_min_raw: int
    dhw_temperature_max_raw: int


T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class TestTheProfile:
    def test_its_facts(self) -> None:
        p = P.heater_profile()
        P.check(p)
        assert p.default_mode == "heat_pump"
        assert p.sources("energy_saver") == {"compressor", "element"}
        assert p.sources("electric") == {"element"}
        assert p.sources("vacation") == frozenset()
        assert p.name_of("HIGH_DEMAND") == "high_demand"
        assert p.name_of("VACATION") == "vacation"
        assert p.modelled_names == {
            "heat_pump",
            "energy_saver",
            "high_demand",
            "electric",
        }
        assert p.names == p.modelled_names | {"vacation", "power_off"}

    @pytest.mark.parametrize(
        ("reported", "name"),
        [
            (1, "heat_pump"),
            (1.0, "heat_pump"),
            (4, "high_demand"),
            (5, "vacation"),
            (6, "power_off"),
            (0, None),
            (7, None),
            (2.5, None),
            (True, None),
            ("vacation", "vacation"),
            ("STANDBY", None),
        ],
    )
    def test_a_recorded_mode_value(
        self, reported: object, name: str | None
    ) -> None:
        """The replacement review of #162: a record holds the mode as
        its ``DhwOperationSetting`` value."""
        assert P.heater_profile().name_of(reported) == name

    def test_a_mode_in_effect(self) -> None:
        p = P.heater_profile()
        compressor, element = frozenset({"compressor"}), frozenset({"element"})
        assert p.effective("heat_pump", compressor) is True
        assert p.effective("energy_saver", compressor) is False
        assert p.effective("energy_saver", compressor | element) is True
        assert p.effective("electric", compressor) is False
        assert p.effective("heat_pump", None) is None
        assert p.effective("vacation", compressor) is None

    def test_a_reported_mode_is_read_by_its_name(self) -> None:
        """The third review of #162: ``DeviceStatus`` carries the mode
        as a ``DhwOperationSetting``, whose ``str`` is its number."""
        from nwp500.enums import DhwOperationSetting

        p = P.heater_profile()
        assert p.name_of(DhwOperationSetting.HIGH_DEMAND) == "high_demand"
        assert p.name_of(DhwOperationSetting.HEAT_PUMP) == "heat_pump"
        assert p.name_of(DhwOperationSetting.VACATION) == "vacation"
        assert p.name_of(DhwOperationSetting.STANDBY) is None

    def test_the_revision_moves_with_a_fact_only(self) -> None:
        p = P.heater_profile()
        assert p.revision == P.heater_profile().revision
        bigger = P.heater_profile(TankParams(volume_gal=80.0))
        assert bigger.revision != p.revision

    def test_the_devices_profile_with_the_simulations_facts(self) -> None:
        """``heater_profile`` is the device's profile with the tank and
        the depletion threshold; the device's setpoint range when its
        features are given."""
        p = P.heater_profile(TankParams(volume_gal=70.0), 110.0)
        assert (p.tank_gal, p.depletion_threshold_f) == (70.0, 110.0)
        base = P.device_profile()
        assert replace(p, tank_gal=None, depletion_threshold_f=None) == base
        feature = _Limits(81, 121)
        narrow = P.heater_profile(feature=feature)
        assert (narrow.setpoint_min_f, narrow.setpoint_max_f) == (104.9, 140.9)
        assert narrow.revision != P.heater_profile().revision

    def test_a_wider_device_range_plans_what_the_walk_runs(self) -> None:
        """A device reporting a wider range than the simulation runs
        gets the simulation's: a write at the profile's maximum walks."""
        wide = P.heater_profile(feature=_Limits(70, 140))
        assert P.device_profile(_Limits(70, 140)).setpoint_max_f == 158.0
        assert (wide.setpoint_min_f, wide.setpoint_max_f) == (
            P.SETPOINT_MIN_F,
            P.SETPOINT_MAX_F,
        )
        from nwp500.sim.api import _check_setpoint

        _check_setpoint("write", wide.setpoint_min_f)
        _check_setpoint("write", wide.setpoint_max_f)

    def test_the_device_facts_are_the_cores(self) -> None:
        """``sim.profile`` re-exports ``nwp500.heater``'s facts."""
        from nwp500 import heater

        for name in P.__all__:
            if hasattr(heater, name):
                assert getattr(P, name) is getattr(heater, name), name


class TestTheSimulationRunsTheProfile:
    """The simulation's own names for the device facts agree with
    ``nwp500.heater``'s, so a plan checked against the profile runs."""

    def test_the_modelled_modes_are_the_engines(self) -> None:
        from nwp500.sim.api import ENGINE_MODE
        from nwp500.sim.physics.element import DEVICE_MODE

        modelled = [m for m in heater.MODES if m.modelled]
        assert {m.code: m.name for m in modelled} == dict(ENGINE_MODE)
        assert {m.name: m.name.upper() for m in modelled} == dict(DEVICE_MODE)
        for m in heater.MODES:
            assert set(m.sources) == P.mode_sources(m.name), m.name

    def test_the_mode_codes_are_the_inputs(self) -> None:
        from nwp500.sim import inputs

        assert {
            m.code: getattr(inputs, m.name.upper()) for m in heater.MODES
        } == {m.code: m.code for m in heater.MODES}

    def test_the_setpoint_range_and_step_are_the_engines(self) -> None:
        from nwp500.sim import engine

        assert engine.HEATER_SETPOINT_MIN_F == heater.SETPOINT_MIN_F
        assert engine.HEATER_SETPOINT_MAX_F == heater.SETPOINT_MAX_F
        assert engine.SETPOINT_RESOLUTION_C == heater.SETPOINT_STEP

    def test_a_write_into_an_unmodelled_mode_is_dropped(self) -> None:
        from nwp500 import sim

        t0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
        for m in heater.MODES:
            scenario = sim.Scenario(
                start=t0,
                horizon=timedelta(hours=1),
                tz="UTC",
                state=sim.HeaterState(upper_f=128.0, lower_f=112.0),
                settings=sim.Settings(setpoint_f=140.0, hp_lower_on_f=105.0),
                environment=sim.Environment(ambient_f=68.0, humidity=48.0),
                commands=sim.Commands(
                    writes=(
                        sim.Write(
                            at=t0 + timedelta(minutes=10), mode=m.code, id="w"
                        ),
                    )
                ),
            )
            result = sim.simulate(scenario, sim.site_example_params())
            dropped = "write_mode_not_modelled" in result.reasons
            assert dropped is not m.modelled, m.name


class TestAKeptRecovery:
    def test_aged_to_now(self) -> None:
        rec = Recovery("ok", start_minute=30.0)
        later = recovery_as_of(rec, T0, T0 + timedelta(minutes=10))
        assert later.start_minute == pytest.approx(20.0)
        assert recovery_as_of(rec, T0, T0) is rec

    def test_a_start_at_once_stays_at_once(self) -> None:
        rec = Recovery("ok", start_minute=0.0)
        later = recovery_as_of(rec, T0, T0 + timedelta(minutes=30))
        assert later.start_minute == 0.0
