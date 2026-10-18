"""Why each recorded start happened (``sim.attribution``) and what the
heater did over a range (``sim.observed``), from its record
(``sim.record``, ``sim_adapters.record``).

They are held to their source by the parity checks run with the port;
these hold their rules.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nwp500 import sim_adapters as sa
from nwp500.models import DeviceStatus
from nwp500.sim.attribution import RESTART_LOCKOUT, attribute
from nwp500.sim.inputs import ENERGY_SAVER
from nwp500.sim.observed import MERGE_STARTS, count_starts, observe
from nwp500.sim.record import Record, Recorded

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def compressor_at(minute: float) -> Recorded:
    return Recorded(at(minute), "compressor")


class TestAttribution:
    def test_a_write_within_two_minutes_owns_the_start(self):
        (a,) = attribute([compressor_at(1.5)], [at(0)])
        assert (a.cause, a.write_at) == ("write", at(0))

    def test_a_write_in_the_lockout_owns_the_start_at_its_end(self):
        stop = at(0)
        written = at(1)
        start = stop + RESTART_LOCKOUT + timedelta(seconds=20)
        (a,) = attribute(
            [Recorded(start, "compressor")], [written], stops=[stop]
        )
        assert a.cause == "write"

    def test_the_heaters_drop_before_a_write(self):
        (a,) = attribute([compressor_at(1)], [], drops=[at(0)])
        assert (a.cause, a.trigger) == ("heater", "mode_dropped")

    def test_the_heaters_own_triggers(self):
        (lower,) = attribute(
            [compressor_at(30)],
            [],
            lower_at=lambda _: 100.5,
            hp_lower_on_f=100.0,
        )
        assert lower.trigger == "lower"
        (opening,) = attribute([compressor_at(1)], [], openings=[at(0)])
        assert opening.trigger == "upper_at_tou_open"
        (element,) = attribute(
            [Recorded(at(5), "element", "upper")],
            [],
            mode_at=lambda _: ENERGY_SAVER,
        )
        assert element.trigger == "energy_saver_upper_on"
        (unknown,) = attribute([compressor_at(30)], [])
        assert (unknown.cause, unknown.trigger) == ("heater", None)

    def test_running_at_the_start(self):
        (a,) = attribute([Recorded(T0, "compressor", running=True)], [])
        assert a.cause == "running"


class TestCounted:
    def test_starts_within_the_merge_are_one(self):
        edges = [at(60), at(70), at(100)]
        assert count_starts(edges, [T0]) == [True, False, True]

    def test_after_a_resync_it_waits_for_a_clear_edge(self):
        edges = [at(10), at(50)]
        assert count_starts(edges, [T0]) == [None, True]
        assert MERGE_STARTS == timedelta(minutes=30)


class TestTheRecord:
    def test_element_starts_need_their_power(self):
        rec = Record(
            upper_element=((at(0), 0.0), (at(10), 1.0), (at(20), 0.0)),
            lower_element=((at(0), 0.0), (at(40), 1.0), (at(50), 0.0)),
            power_w=((at(0), 3.0), (at(11), 5000.0), (at(21), 3.0)),
        )
        got = rec.starts(at(5), at(60))
        assert [(s.at, s.zone) for s in got.starts] == [(at(10), "upper")]
        assert got.uncorroborated == 1

    def test_a_handoff_at_one_wattage_is_corroborated(self):
        """The third review of #162: power records on change, so the
        lower element taking over from the upper at 5000 W leaves no
        row in its run; the value in force at its on-edge shows it."""
        rec = Record(
            upper_element=((at(0), 0.0), (at(10), 1.0), (at(20), 0.0)),
            lower_element=((at(0), 0.0), (at(20), 1.0), (at(30), 0.0)),
            power_w=((at(0), 3.0), (at(19.5), 5000.0), (at(31), 3.0)),
        )
        got = rec.starts(at(5), at(60))
        assert [(s.at, s.zone) for s in got.starts] == [
            (at(10), "upper"),
            (at(20), "lower"),
        ]
        assert got.uncorroborated == 0
        o = observe(rec, at(0), at(60), now=at(600))
        assert [
            (s.start, s.end) for s in o.sources if s.source == "element"
        ] == [(at(10), at(20)), (at(20), at(30))]

    def test_a_stale_power_row_does_not_corroborate(self):
        """The value in force counts only within ``ELEMENT_POWER_SLACK``
        of the on-edge, so an earlier run's row cannot show a flag's."""
        rec = Record(
            lower_element=((at(0), 0.0), (at(20), 1.0), (at(30), 0.0)),
            power_w=((at(0), 3.0), (at(18), 5000.0), (at(31), 3.0)),
        )
        got = rec.starts(at(5), at(60))
        assert got.starts == []
        assert got.uncorroborated == 1

    def test_an_off_edge_at_the_start_is_not_running(self):
        """The third review of #162: a compressor that stopped at the
        span's start is off throughout it; its stop still counts for
        the lockout."""
        rec = Record(compressor=((at(0), 0.0), (at(10), 1.0), (at(20), 0.0)))
        got = rec.starts(at(20), at(30))
        assert got.starts == []
        assert at(20) in got.stops
        on_at = rec.starts(at(10), at(30))
        assert [(s.at, s.running) for s in on_at.starts] == [(at(10), False)]

    def test_writes_and_the_heaters_drop(self):
        rec = Record(
            setpoint_f=((at(0), 140.0), (at(10), 136.4)),
            mode=((at(0), 1.0), (at(20), 3.0), (at(30), 1.0)),
            hp_upper_on_f=((at(0), 104.0), (at(30), 139.0)),
        )
        writes = rec.writes(at(5), at(60))
        assert [(w.at, w.setpoint_f, w.mode, w.dropped) for w in writes] == [
            (at(10), 136.4, None, False),
            (at(20), None, 3, False),
            (at(30), None, 1, True),
        ]


@pytest.fixture
def statuses(device_status_dict):
    """A status a minute for a day: a compressor run from 13:00 to
    14:00 at 450 W, idle at 5 W."""

    def status(m: int) -> DeviceStatus:
        running = 1440 + 60 <= m < 1440 + 120
        d: dict[str, Any] = {
            "compUse": 2 if running else 1,
            "heatUpperUse": 1,
            "heatLowerUse": 1,
            "currentHeatUse": 1 if running else 0,
            "currentInstPower": 450 if running else 5,
            "dhwOperationSetting": 1,
            "hpUpperOnTempSetting": 81,
        }
        return DeviceStatus.model_validate(device_status_dict | d)

    return [(at(m - 1440), status(m)) for m in range(0, 2 * 1440)]


class TestObserve:
    def test_the_run_its_energy_and_what_it_was(self, statuses):
        o = sa.observe(statuses, start=at(0), end=at(240), now=at(600))
        assert [(s.start, s.end, s.source) for s in o.sources] == [
            (at(60), at(120), "compressor")
        ]
        (start,) = o.starts
        assert start.at == at(60) and start.cause == "heater"
        slot = next(s for s in o.slots if s.start == at(60))
        assert slot.energy_wh == pytest.approx(75.0)
        assert not slot.partial
        assert {m.name for m in o.modes} == {"heat_pump"}
        assert any(m.effective for m in o.modes)

    def test_past_now_nothing_is_claimed(self, statuses):
        o = sa.observe(statuses, start=at(0), end=at(240), now=at(180))
        late = [g for g in o.gaps if g.reason == "not_yet_recorded"]
        assert {g.signal for g in late} == {
            "compressor",
            "power",
            "mode",
            "setpoint",
            "elements",
            "heat_source",
            "delivery",
        }
        assert all(g.start == at(180) for g in late)

    def test_record_keeps_only_changes(self, statuses):
        rec = sa.record(statuses)
        assert [v for _, v in rec.compressor] == [0.0, 1.0, 0.0]
        assert [t for t, _ in rec.compressor][1:] == [at(60), at(120)]
        assert observe(rec, at(0), at(240), now=at(600)).starts
