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
    def test_its_facts(self):
        p = P.heater_profile()
        P.check(p)
        assert p.default_mode == "heat_pump"
        assert p.sources("energy_saver") == {"compressor", "element"}
        assert p.sources("electric") == {"element"}
        assert p.name_of("HIGH_DEMAND") == "high_demand"
        assert p.name_of("VACATION") is None

    def test_the_revision_moves_with_a_fact_only(self):
        p = P.heater_profile()
        assert p.revision == P.heater_profile().revision
        bigger = P.heater_profile(TankParams(volume_gal=80.0))
        assert bigger.revision != p.revision


class TestAKeptRecovery:
    def test_aged_to_now(self):
        rec = Recovery(
            "ok", start_minute=30.0, coast_btu=900.0, coast_draw_gal=4.0
        )
        later = recovery_as_of(rec, T0, T0 + timedelta(minutes=10))
        assert later.start_minute == pytest.approx(20.0)
        assert later.coast_btu == pytest.approx(600.0)
        assert later.coast_draw_gal == pytest.approx(8.0 / 3.0)
        assert recovery_as_of(rec, T0, T0) is rec
