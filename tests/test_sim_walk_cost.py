"""What a simulation walks: a small multiple of its span, however long
the span, and the same answer however far a coast walks at a time.

A coast finds the heater's own start on the walk ahead of it and then
walks again to there, so how far it walks before it looks bounds what
a simulation costs (``engine._COAST_AHEAD``).
"""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from nwp500 import sim
from nwp500.sim import (
    Draw,
    Environment,
    HeaterState,
    History,
    Loads,
    Scenario,
    Settings,
    engine,
)
from nwp500.sim.circulation import Circulation
from nwp500.sim.defaults import SITE_CIRCULATION
from nwp500.sim.engine import Entry, Heater, RawWrite
from nwp500.sim.params import params_from_document
from nwp500.sim.tank_physics import TankPhysics

T0 = datetime(2026, 10, 4, 7, 0, tzinfo=UTC)
_PARAMS = params_from_document(
    json.loads(
        (
            Path(__file__).with_name("fixtures") / "sim" / "heater_params.json"
        ).read_text()
    )
)
MODES = ("heat_pump", "energy_saver", "high_demand", "electric")
#: Setpoints are drawn from one of these, as low as Energy Saver's
#: upper element rests (104.9 °F) and under it.
SETPOINTS = ((95.0, 110.0), (110.0, 150.0))


def _days(days: int) -> Scenario:
    draws = [
        Draw(at=T0 + timedelta(days=d, hours=h, minutes=i), gallons=gal)
        for d in range(days)
        for h, gal, n in ((0.5, 1.8, 8), (5.0, 0.5, 4), (12.0, 1.8, 10))
        for i in range(n)
    ]
    return Scenario(
        start=T0,
        horizon=timedelta(days=days),
        tz="UTC",
        state=HeaterState(upper_f=128.0, lower_f=118.0),
        settings=Settings(setpoint_f=130.0, hp_lower_on_f=111.0),
        history=History(compressor_stopped_at=T0 - timedelta(hours=2)),
        environment=Environment(ambient_f=65.0, inlet_f=60.0),
        loads=Loads(draws=tuple(draws)),
    )


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
    s = _days(days)
    result = sim.simulate(s, sim.site_example_params())
    assert result.simulation.heating, "the week heats"
    # Past each start a coast walks to the end of its piece, and the
    # walk is taken again to the start: about twice the span.
    assert sum(walked, timedelta()) < 2.5 * s.horizon


def _case(seed: int, spans: tuple[int, ...] = (8, 24)) -> dict[str, Any]:
    """A random walk for ``engine.simulate``: any mode and setpoint,
    TOU windows, draws (some at one instant), entries, raw writes,
    withheld windows, a compressor or an element running at the start,
    on an air that swings daily, over one of ``spans`` hours."""
    rng = random.Random(seed)  # noqa: S311 (reproducible cases)
    t0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC) + timedelta(
        minutes=rng.randrange(600), seconds=rng.choice((0, 0, 17))
    )
    hours = rng.choice(spans)
    mode = rng.choice(MODES)
    upper = rng.uniform(85.0, 150.0)
    running = rng.random() < 0.3 and mode != "electric"
    element = not running and mode != "heat_pump" and rng.random() < 0.3
    day = t0.replace(hour=0, minute=0, second=0)
    tou: list[tuple[datetime, datetime]] = []
    if rng.random() < 0.6:
        for d in range(hours // 24 + 2):
            a = day + timedelta(days=d, hours=rng.choice((14, 15, 16, 23)))
            tou.append((a, a + timedelta(hours=rng.choice((1, 3, 5)))))
    draws: list[tuple[datetime, float]] = []
    for _ in range(rng.randrange(hours * 3 + 1)):
        at = t0 + timedelta(minutes=rng.randrange(hours * 60))
        gal = rng.choice((0.5, 1.5, 3.0, 10.0))
        draws += [
            (at + timedelta(minutes=i), gal)
            for i in range(rng.choice((1, 3, 8)))
        ]
    entries = [
        Entry(
            (t0 + timedelta(minutes=rng.randrange(1, hours * 60))).replace(
                second=0
            ),
            rng.choice(MODES),  # type: ignore[arg-type]
            round(rng.uniform(100.0, 145.0) * 2) / 2,
            t0,
            f"e{i}",
        )
        for i in range(rng.randrange(4))
    ]
    entries = [e for e in entries if e.at > t0]
    raw = [
        RawWrite(
            t0 + timedelta(minutes=rng.randrange(1, hours * 60)),
            setpoint_f=rng.choice((None, float(rng.randrange(100, 146)))),
            mode=rng.choice((None, *MODES)),  # type: ignore[arg-type]
            id=f"r{i}",
        )
        for i in range(rng.choice((0, 0, 1, 2)))
    ]
    withheld: list[tuple[datetime, datetime]] = []
    if rng.random() < 0.3:
        a = t0 + timedelta(minutes=rng.randrange(hours * 60))
        withheld.append((a, a + timedelta(minutes=rng.choice((30, 90)))))
    stamps = pd.date_range(
        t0 - timedelta(hours=1), t0 + timedelta(hours=hours + 6), freq="10min"
    )
    base, swing = rng.uniform(30.0, 80.0), rng.uniform(0.0, 20.0)
    air = pd.DataFrame(
        {
            "ambient_f": [
                base + swing * (i % 144 / 144 - 0.5) for i in range(len(stamps))
            ]
        },
        index=stamps,
    )
    return {
        "start": t0,
        "until": t0 + timedelta(hours=hours),
        "setpoint_f": round(
            rng.choice((rng.uniform(95, 110), rng.uniform(110, 150))) * 2
        )
        / 2,
        "upper_f": upper,
        "lower_f": rng.uniform(70.0, min(upper, 145.0)),
        "running": running,
        "heater": Heater(
            hp_lower_on_f=rng.choice((None, 105.0, 111.0, 118.0)),
            tou_windows=tuple(tou),
            mode=mode,  # type: ignore[arg-type]
        ),
        "physics": TankPhysics(
            _PARAMS, air, 48.0, draws_on=True, low_confidence_floor=0.6
        ),
        "entries": entries,
        "draws": draws,
        "withheld_windows": withheld,
        "marks": [d[0] for d in draws[:3]],
        "element_running": element,
        "raw_writes": raw,
        "stopped_at": None
        if running
        else t0 - timedelta(minutes=rng.choice((1, 3, 30, 300))),
        "running_hold": rng.choice((0.0, 2.0)) if running else 0.0,
    }


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
        try:
            return engine.simulate(**_case(seed, spans))
        except engine.SimulationError as e:
            pytest.skip(str(e))

    whole = answer(timedelta(days=30))
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
            _PARAMS,
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
    physics = TankPhysics(_PARAMS, _flat_air(124.0), 48.0, draws_on=True)
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
