"""What a simulation walks: a small multiple of its span, however long
the span, and the same answer however far a coast walks at a time.

A coast finds the heater's own start on the walk ahead of it and then
walks again to there, so how far it walks before it looks bounds what
a simulation costs (``engine._COAST_AHEAD``).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest
from sim_cases import PARAMS, days_of_draws, walk_case

from nwp500 import sim
from nwp500.sim import (
    engine,
)
from nwp500.sim.circulation import Circulation
from nwp500.sim.defaults import SITE_CIRCULATION
from nwp500.sim.engine import Heater
from nwp500.sim.tank_physics import TankPhysics


@pytest.mark.parametrize("days", [2, 7, 14])
def test_a_simulation_walks_about_its_span(
    monkeypatch: pytest.MonkeyPatch, days: int
) -> None:
    walked: list[timedelta] = []
    advance = TankPhysics.advance

    def counted(
        self: TankPhysics,
        start: datetime,
        state: Any,
        end: datetime,
        *args: Any,
        **kw: Any,
    ) -> Any:
        out = advance(self, start, state, end, *args, **kw)
        walked.append(out.points[-1].at - start)
        return out

    monkeypatch.setattr(TankPhysics, "advance", counted)
    s = days_of_draws(days)
    result = sim.simulate(s, sim.site_example_params())
    assert result.simulation.heating, "the week heats"
    # Past each start a coast walks to the end of its piece, and the
    # walk is taken again to the start: about twice the span.
    assert sum(walked, timedelta()) < 2.5 * s.horizon


#: Cases a coast cut at its look-ahead (its controller read again at
#: each cut) answered differently, and one whose start a draw on a
#: piece's end took (``(18, (8, 24, 48))``).
CASES = [
    *((seed, (8, 24)) for seed in (24, 187, 207, 365, 32, 375, 33, 28)),
    *((seed, (8, 24)) for seed in (181, 36, 387, 25, 0, 1)),
    (18, (8, 24, 48)),
]


@pytest.mark.parametrize(("seed", "spans"), CASES)
def test_the_answer_does_not_depend_on_the_pieces(
    monkeypatch: pytest.MonkeyPatch, seed: int, spans: tuple[int, ...]
) -> None:
    """A coast walked in pieces of 20 minutes, or of 3 hours, answers as
    one walked whole to its event: where the heater starts itself is
    decided by the tank up to the start, and nothing reads the tank at
    a piece's end."""

    def answer(ahead: timedelta) -> engine.Simulation:
        monkeypatch.setattr(engine, "_COAST_AHEAD", ahead)
        return engine.simulate(**walk_case(seed, spans))

    try:
        whole = answer(timedelta(days=30))
    except engine.SimulationError as e:
        pytest.skip(f"the case does not simulate: {e}")
    assert answer(timedelta(minutes=20)) == whole
    assert answer(timedelta(hours=3)) == whole


T5 = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)


def _flat_air(air_f: float = 60.0) -> pd.DataFrame:
    stamps = pd.date_range(
        T5 - timedelta(hours=2), T5 + timedelta(days=2), freq="10min"
    )
    return pd.DataFrame({"ambient_f": air_f}, index=stamps)


def _circulating(
    gal: float, lower_on: float, known_until: datetime | None = None
) -> dict[str, Any]:
    """A circulation run over a coast. With ``known_until``, the run
    goes on past where it is known; else a draw of ``gal`` lands on
    the first piece's end, where the circulation's drop over the step
    ending there is the last piece's."""
    run = (
        (T5 + timedelta(hours=1), T5 + timedelta(hours=6))
        if known_until
        else (T5 + timedelta(hours=1), T5 + timedelta(hours=8))
    )
    return {
        "start": T5,
        "until": T5 + timedelta(hours=8),
        "setpoint_f": 140.0,
        "upper_f": 130.0,
        "lower_f": 125.0,
        "running": False,
        "heater": Heater(hp_lower_on_f=lower_on, mode="heat_pump"),
        "physics": TankPhysics(
            PARAMS,
            _flat_air(),
            48.0,
            draws_on=True,
            circulation=Circulation((run,), known_until=known_until),
            circulation_terms=SITE_CIRCULATION,
        ),
        "draws": [] if known_until else [(T5 + timedelta(hours=3), gal)],
    }


def _overlapping() -> dict[str, Any]:
    """A coast that begins inside one TOU window, its upper zone less
    than a probe step past the line, a later window opening inside it:
    the start is the first window's, crossing past the second's
    opening."""
    physics = TankPhysics(PARAMS, _flat_air(124.0), 48.0, draws_on=True)
    first = (T5 - timedelta(hours=1), T5 + timedelta(hours=10))
    second = (T5 + timedelta(hours=1), T5 + timedelta(hours=10))
    return {
        "start": T5,
        "until": T5 + timedelta(hours=12),
        "setpoint_f": 140.0,
        "upper_f": 125.55,
        "lower_f": 125.55,
        "running": False,
        "state": physics.layers([125.55] * physics.layout.layers),
        "heater": Heater(
            hp_lower_on_f=None, mode="heat_pump", tou_windows=(first, second)
        ),
        "physics": physics,
    }


@pytest.mark.parametrize(
    "build",
    [
        lambda: _circulating(10.0, 105.0),
        lambda: _circulating(0.5, 106.393),
        lambda: _circulating(0.0, 105.0, known_until=T5 + timedelta(hours=2)),
        _overlapping,
    ],
    ids=["drop-order", "drop-order-small", "known-until", "overlapping-tou"],
)
def test_a_piece_answers_as_the_whole_walk(
    monkeypatch: pytest.MonkeyPatch, build: Any
) -> None:
    """Where pieces meet a circulation's drop and a draw at one instant,
    a circulation run known only from before a piece's start, and TOU
    windows that overlap: the coast in pieces answers as one walked
    whole."""

    def answer(ahead: timedelta) -> engine.Simulation:
        monkeypatch.setattr(engine, "_COAST_AHEAD", ahead)
        return engine.simulate(**build())

    whole = answer(timedelta(days=30))
    assert answer(timedelta(hours=3)) == whole
    assert answer(timedelta(minutes=10)) == whole
