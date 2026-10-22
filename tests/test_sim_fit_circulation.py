"""The circulation's terms from the heat book's re-anchors
(``sim_calibrate.fit_circulation``).

The histories are walked by the book's own heat balance, so the loss per
gallon they were made with is the one a fit should find.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

pytest.importorskip("scipy")

from nwp500 import sim_adapters as sa
from nwp500 import sim_calibrate
from nwp500.sim import site_example_params
from nwp500.sim.defaults import SITE_CIRCULATION
from nwp500.sim.params import CirculationParams, HeaterParams
from nwp500.sim.units import WATER_BTU_PER_GAL_F

T0 = datetime(2026, 1, 5, tzinfo=UTC)
STEP = timedelta(seconds=sa.BOOK_GRID_S)
#: One cycle: quiet, a run, quiet, a recovery, quiet; minutes.
RUN = (60, 75)
RECOVERY = (150, 210)
CYCLE = 360
AIR_F = 65.0
#: The meter's reading during a run, gal/min.
RUN_GPM = 1.0


def history(
    params: HeaterParams,
    cycles: int,
    loss: float,
    *,
    meter_sees: bool = True,
    late_loss: float | None = None,
    late_from: int = 0,
) -> dict[str, Any]:
    """A history of ``cycles`` six-hour cycles walked by the book's own
    balance, each run taking ``loss`` per gallon (``late_loss`` from
    cycle ``late_from`` on), and what ``fit_circulation`` takes."""
    p = params.book_terms()
    mass = WATER_BTU_PER_GAL_F * p.tank_gal
    h = sa.BOOK_GRID_S / 3600.0
    per_step = sa.BOOK_GRID_S / 60.0
    n = cycles * CYCLE * 6
    temp = 125.0
    probe: list[tuple[datetime, float]] = []
    comp: list[tuple[datetime, bool]] = []
    flow: list[tuple[datetime, float]] = []
    runs: list[tuple[datetime, datetime]] = []
    # A recovery first, so there is an anchor before the first run.
    first = (0, 30)
    for i in range(n):
        t = T0 + i * STEP
        minute = (i // 6) % CYCLE
        cycle = i // (6 * CYCLE)
        heating = RECOVERY[0] <= minute < RECOVERY[1] or (
            cycle == 0 and first[0] <= minute < first[1]
        )
        running = RUN[0] <= minute < RUN[1]
        if running and minute == RUN[0] and i % 6 == 0:
            runs.append((t, t + timedelta(minutes=RUN[1] - RUN[0])))
        probe.append((t, temp))
        comp.append((t, heating))
        flow.append((t, RUN_GPM if running and meter_sees else 0.0))
        per_gal = loss if late_loss is None or cycle < late_from else late_loss
        circulated = RUN_GPM * per_step if running else 0.0
        e = (
            heating
            * (p.hp_btu_per_h + p.hp_btu_per_h_per_f * (AIR_F - 65.0))
            * h
            - per_gal * circulated
            - p.ua_btu_per_h_f * max(temp - AIR_F, 0.0) * h
        )
        temp += e / mass
    rows = sa.ChangeRows(upper_f=probe, lower_f=probe, compressor_on=comp)
    return {
        "rows": rows,
        "observed": [t for t, _ in probe[::3]],
        "flow": flow,
        "runs": runs,
        "air": [(T0, AIR_F)],
    }


def fit(
    params: HeaterParams, h: dict[str, Any]
) -> sim_calibrate.CirculationFit:
    return sim_calibrate.fit_circulation(
        h["rows"],
        h["observed"],
        params,
        flow=h["flow"],
        runs=h["runs"],
        air=h["air"],
    )


NO_BASE = replace(site_example_params(), circulation=None)


class TestFitCirculation:
    def test_it_finds_the_loss_the_runs_took(self) -> None:
        got = fit(NO_BASE, history(NO_BASE, 16, 150.0))
        assert got.kept == "refit"
        assert got.params is not None
        assert got.params.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
        assert got.params.meter_share == 1.0
        assert got.params.flow_gpm == pytest.approx(RUN_GPM)
        assert got.params.displaced_gal == SITE_CIRCULATION.displaced_gal
        assert got.runs == 16
        # An anchor after the opening recovery and after each cycle's.
        assert got.pairs == 16
        assert got.error_btu == pytest.approx(0.0, abs=50.0)
        assert "one installation's" in got.why

    def test_a_meter_that_misses_the_runs_prices_them_nominally(
        self,
    ) -> None:
        """With the meter reading nothing, each run is priced at the
        nominal flow: the loss per minute is what the book reads."""
        got = fit(NO_BASE, history(NO_BASE, 16, 150.0, meter_sees=False))
        assert got.kept == "refit"
        assert got.params is not None
        assert got.params.meter_share == 0.0
        assert got.params.flow_gpm == sim_calibrate.NOMINAL_CIRCULATION_GPM
        # Walked at 1 gal/min, the nominal flow.
        assert got.params.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
        assert "doesn't see" in got.why

    def test_a_draw_during_a_run_is_not_its_flow(self) -> None:
        """A tap open for a minute of each run reads over the run's own
        flow by more than the draw line: those minutes aren't the run's."""
        h = history(NO_BASE, 16, 150.0)
        starts = {a for a, _ in h["runs"]}
        tap = [
            (
                t,
                3.0
                if any(a <= t < a + timedelta(minutes=1) for a in starts)
                else v,
            )
            for t, v in h["flow"]
        ]
        got = fit(NO_BASE, h | {"flow": tap})
        assert got.params is not None
        assert got.params.flow_gpm == pytest.approx(RUN_GPM)

    def test_the_refit_replaces_a_worse_base(self) -> None:
        params = site_example_params()
        got = fit(params, history(params, 16, 150.0))
        assert got.kept == "refit"
        assert got.params is not None
        assert got.params.loss_btu_per_gal == pytest.approx(150.0, abs=1.0)
        # The base's own volume and gap are kept.
        assert got.params.displaced_gal == SITE_CIRCULATION.displaced_gal
        assert "kept from the base" in got.why

    def test_a_better_base_is_kept(self) -> None:
        """The held-out runs took 100 BTU/gal, the earlier 150: a base
        at 100 books them better than the refit."""
        base = CirculationParams(
            displaced_gal=5.0,
            flow_gpm=RUN_GPM,
            loss_btu_per_gal=100.0,
            meter_share=1.0,
        )
        params = replace(NO_BASE, circulation=base)
        got = fit(
            params,
            history(params, 16, 150.0, late_loss=100.0, late_from=13),
        )
        assert got.kept == "base"
        assert got.params == base

    def test_too_few_days_keeps_the_base(self) -> None:
        params = site_example_params()
        got = fit(params, history(params, 8, 150.0))
        assert got.kept == "base"
        assert got.params == params.circulation
        assert "8 clean runs over 2 days" in got.why

    def test_a_silence_breaks_the_book(self) -> None:
        h = history(NO_BASE, 16, 150.0)
        gap = (T0 + timedelta(hours=40), T0 + timedelta(hours=44))
        whole = fit(NO_BASE, h)
        h["observed"] = [t for t in h["observed"] if not gap[0] < t < gap[1]]
        got = fit(NO_BASE, h)
        assert got.pairs < whole.pairs

    def test_the_document(self) -> None:
        got = fit(NO_BASE, history(NO_BASE, 16, 150.0))
        doc = got.as_document()
        assert CirculationParams(**doc["circulation"]) == got.params
        assert doc["kept"] == "refit"
        assert np.isfinite(doc["error_btu"])
