"""The element terms from a heater's raw record (``sim.calibration``'s
element measurements): the upper probe's lag and rate, where an element
switches off, its power, and the zones' rates on the one-minute grid.

Held to its source by the parity check run with the port; these hold
its rules on a tank whose terms are known.
"""

from datetime import UTC, datetime, timedelta

import pytest

from nwp500.sim import calibration as cal
from nwp500.sim.inputs import ELECTRIC, ENERGY_SAVER, HIGH_DEMAND
from nwp500.sim.record import Record

T0 = datetime(2026, 9, 10, tzinfo=UTC)
LAG_S = 72
RATE = 2.0
STEP = 0.18


def tank(
    draw_at: int | None = None,
) -> tuple[Record, list[tuple[datetime, datetime]]]:
    """Twenty upper stints over ten days, each from a different deficit,
    the probe reporting every 15 s on a change; the mode rotates; in
    Energy Saver the element stops 1.6 °F short. A lower stint follows
    each in Electric. ``draw_at``: a draw over that stint's start."""
    rows: dict[str, list[tuple[datetime, float]]] = {
        k: [(T0, v)]
        for k, v in (
            ("U", 0.0),
            ("L", 0.0),
            ("C", 0.0),
            ("W", 3.0),
            ("sp", 140.0),
            ("mode", float(ENERGY_SAVER)),
            ("upper", 120.0),
            ("lower", 110.0),
        )
    }
    draws = []
    for k in range(20):
        on = T0 + timedelta(hours=12 * k + 1)
        mode = (ENERGY_SAVER, HIGH_DEMAND, ELECTRIC)[k % 3]
        rows["mode"].append((on - timedelta(minutes=20), float(mode)))
        start = round((140.0 - 3.0 - 1.1 * k) / STEP) * STEP
        rows["upper"].append((on - timedelta(minutes=10), start))
        stop = 140.0 - (1.6 if mode == ENERGY_SAVER else 0.0)
        run_s = LAG_S + (stop - start) / RATE * 60
        off = on + timedelta(seconds=run_s)
        rows["U"] += [(on, 1.0), (off, 0.0)]
        rows["W"] += [
            (on + timedelta(seconds=5 + 30 * i), 5150.0)
            for i in range(int(run_s // 30))
        ] + [(off, 3.0)]
        t, last = 0, start
        while t <= run_s + 30:
            v = start + max(0.0, t - LAG_S) / 60 * RATE
            v = round(round(min(v, stop + 0.2) / STEP) * STEP, 2)
            if v != last:
                rows["upper"].append((on + timedelta(seconds=t + 0.2), v))
                last = v
            t += 15
        if mode == ELECTRIC:
            lon, loff = off, off + timedelta(minutes=8)
            rows["L"] += [(lon, 1.0), (loff, 0.0)]
            rows["lower"] += [
                (lon + timedelta(minutes=m), 110.0 + 1.4 * m) for m in range(9)
            ]
        if k == draw_at:
            draws.append((on - timedelta(minutes=1), on + timedelta(minutes=2)))
    record = Record(
        compressor=tuple(rows["C"]),
        upper_element=tuple(rows["U"]),
        lower_element=tuple(rows["L"]),
        power_w=tuple(sorted(rows["W"])),
        mode=tuple(rows["mode"]),
        setpoint_f=tuple(rows["sp"]),
        upper_f=tuple(sorted(rows["upper"])),
        lower_f=tuple(sorted(rows["lower"])),
    )
    return record, draws


class TestTheLag:
    def test_the_line_recovers_the_lag_and_the_rise(self) -> None:
        record, _ = tank()
        stints = cal.element_stints(record, draws=[])
        fit = cal.fit_element_lag(stints, n_boot=200)
        assert fit is not None
        assert fit.rise_f_per_min == pytest.approx(RATE, abs=0.05)
        assert fit.upper_dead_time_min == pytest.approx(LAG_S / 60, abs=0.15)
        assert fit.lag_interval[0] <= fit.upper_dead_time_min

    def test_a_stint_with_a_draw_is_left_out(self) -> None:
        record, draws = tank(draw_at=4)
        stints = cal.element_stints(record, draws=draws)
        assert bool(stints["draw"].sum() == 1)
        assert stints["draw_known"].iloc[4]

    def test_without_a_meter_no_draw_is_known(self) -> None:
        record, _ = tank()
        assert not bool(cal.element_stints(record)["draw_known"].any())


class TestTheOffPoint:
    def test_energy_saver_stops_short(self) -> None:
        record, _ = tank()
        off = cal.element_off_points(record)
        upper = off[(off["which"] == "upper") & off["clean"]]
        saver = upper.loc[upper["mode"] == ENERGY_SAVER, "deficit"]
        others = upper.loc[upper["mode"] != ENERGY_SAVER, "deficit"]
        # The probe's read at an edge is up to a report old in every
        # mode; Energy Saver stops 1.6 °F before the others.
        assert saver.median() - others.median() == pytest.approx(1.6, abs=0.2)

    def test_the_power_of_a_metered_stint(self) -> None:
        record, _ = tank()
        power = cal.element_power(record, cal.element_off_points(record))
        assert bool(power["net_w"].median() == pytest.approx(5150.0, rel=0.01))


class TestTheGridPower:
    def test_the_elements_power(self) -> None:
        record, _ = tank()
        fit = cal.fit_element_w(cal.element_grid(record), n_boot=200)
        assert fit.element_w == pytest.approx(5150.0)
