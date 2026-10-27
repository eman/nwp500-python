"""The heater's profile (``sim.profile``), and a kept recovery aged to
now (``recovery_as_of``).

Held to their source by the parity checks run with the port; these
hold their rules.
"""

from datetime import UTC, datetime, timedelta

import pytest

from nwp500.sim import profile as P
from nwp500.sim import recovery_as_of
from nwp500.sim.params import TankParams
from nwp500.sim.ready import Recovery

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class TestTheProfile:
    def test_its_facts(self) -> None:
        p = P.heater_profile()
        P.check(p)
        assert p.default_mode == "heat_pump"
        assert p.sources("energy_saver") == {"compressor", "element"}
        assert p.sources("electric") == {"element"}
        assert p.name_of("HIGH_DEMAND") == "high_demand"
        assert p.name_of("VACATION") is None

    @pytest.mark.parametrize(
        ("reported", "name"),
        [
            (1, "heat_pump"),
            (1.0, "heat_pump"),
            (4, "high_demand"),
            (5, None),
            (6, None),
            (7, None),
            (2.5, None),
            (True, None),
            ("vacation", None),
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

    def test_a_reported_mode_is_read_by_its_name(self) -> None:
        """The third review of #162: ``DeviceStatus`` carries the mode
        as a ``DhwOperationSetting``, whose ``str`` is its number."""
        from nwp500.enums import DhwOperationSetting

        p = P.heater_profile()
        assert p.name_of(DhwOperationSetting.HIGH_DEMAND) == "high_demand"
        assert p.name_of(DhwOperationSetting.HEAT_PUMP) == "heat_pump"
        assert p.name_of(DhwOperationSetting.VACATION) is None

    def test_the_revision_moves_with_a_fact_only(self) -> None:
        p = P.heater_profile()
        assert p.revision == P.heater_profile().revision
        bigger = P.heater_profile(TankParams(volume_gal=80.0))
        assert bigger.revision != p.revision


class TestAKeptRecovery:
    def test_aged_to_now(self) -> None:
        rec = Recovery(
            "ok", start_minute=30.0, coast_btu=900.0, coast_draw_gal=4.0
        )
        later = recovery_as_of(rec, T0, T0 + timedelta(minutes=10))
        assert later.start_minute == pytest.approx(20.0)
        assert later.coast_btu == pytest.approx(600.0)
        assert later.coast_draw_gal == pytest.approx(8.0 / 3.0)
        assert recovery_as_of(rec, T0, T0) is rec

    def test_a_start_at_once_has_no_coast_left(self) -> None:
        """A draw at the instant it was computed that trips the start is
        the coast's (``next_recovery``): a later look has taken it."""
        rec = Recovery("ok", start_minute=0.0, coast_draw_gal=20.0)
        later = recovery_as_of(rec, T0, T0 + timedelta(minutes=30))
        assert later.start_minute == 0.0
        assert later.coast_draw_gal == 0.0
        assert later.coast_btu == 0.0
