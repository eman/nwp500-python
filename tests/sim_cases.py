"""Simulator cases the tests share: a run of days with draws through
the public API, and a random engine walk."""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from nwp500.sim import (
    Draw,
    Environment,
    HeaterState,
    History,
    Loads,
    Scenario,
    Schedules,
    Settings,
    TouPeriod,
)
from nwp500.sim.engine import Entry, Heater, RawWrite
from nwp500.sim.params import params_from_document
from nwp500.sim.tank_physics import TankPhysics

T0 = datetime(2026, 10, 4, 7, 0, tzinfo=UTC)
PARAMS = params_from_document(
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


def days_of_draws(days: int) -> Scenario:
    """``days`` from 07:00 UTC with about 30 draws a day, in Heat
    Pump mode."""
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


def walk_case(seed: int, spans: tuple[int, ...] = (8, 24)) -> dict[str, Any]:
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
    draws: list[tuple[datetime, float, bool]] = []
    for _ in range(rng.randrange(hours * 3 + 1)):
        at = t0 + timedelta(minutes=rng.randrange(hours * 60))
        gal = rng.choice((0.5, 1.5, 3.0, 10.0))
        draws += [
            (at + timedelta(minutes=i), gal, False)
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
            PARAMS, air, 48.0, draws_on=True, low_confidence_floor=0.6
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


def peak(opens: int, closes: int) -> Schedules:
    """TOU on, a peak from ``opens``:00 to ``closes``:00 UTC: across
    midnight when it closes earlier in the day than it opens."""

    def period(h0: int, m0: int, h1: int, m1: int, price: int) -> TouPeriod:
        return TouPeriod(
            season=0xFFF,
            week=0xFE,
            start_hour=h0,
            start_minute=m0,
            end_hour=h1,
            end_minute=m1,
            price_max=price,
        )

    if closes < opens:
        periods = (
            period(0, 0, closes - 1, 59, 5),
            period(closes, 0, opens - 1, 59, 1),
            period(opens, 0, 23, 59, 5),
        )
    else:
        periods = (
            period(0, 0, opens - 1, 59, 1),
            period(opens, 0, closes - 1, 59, 5),
            period(closes, 0, 23, 59, 1),
        )
    return Schedules(tou_enabled=True, tou_periods=periods)
