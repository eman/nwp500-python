"""The simulator's answers on fixed scenarios, held exactly.

``nwp500.sim.engine.simulate()`` walks each case below through the
core's own physics (``TankPhysics`` on the parameters in
``fixtures/sim/heater_params.json``, one NWP500-65's), with no recovery
model and no flowing draws, so every input is data in this file. What
the engine returns is held as its outputs (the path, the heating
intervals, the writes and mode writes as they landed, and the modes),
every float rounded to ``PLACES`` decimals, with a readable summary and
a digest per field, so a moved answer names the fields that moved.

The rounding is not a tolerance for a changed answer. numpy picks its
SIMD kernels by CPU, so the same wheel can differ in the last bit from
one machine to the next, and over a walk of thousands of steps those
bits reach the path. Six decimals of a degree or a watt-hour is far
below anything the model resolves and far above that drift.

The comparison of the rounded answer is exact. ``NWP500_SIM_GOLDEN_REGEN=1``
rewrites the held answer of each case that runs: that is a decision to
state in the pull request (which cases moved, by how much, and why the
new answer is right), never a way to make a red test green.

The core is also deterministic: each case run twice, and once on
another thread, returns an equal ``Simulation``.
"""

import dataclasses
import hashlib
import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from nwp500.sim.engine import (
    Entry,
    Heater,
    RawWrite,
    Simulation,
    simulate,
)
from nwp500.sim.params import HeaterParams, params_from_document
from nwp500.sim.tank_physics import (
    Coast,
    Heat,
    Physics,
    Point,
    TankPhysics,
    TankState,
)

FIXTURES = Path(__file__).with_name("fixtures") / "sim"
GOLDEN = FIXTURES / "engine_golden.json"
REGEN = "NWP500_SIM_GOLDEN_REGEN"

#: The walk's start, on the minute, as an entry's minute is.
T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
#: The TOU window the heater holds, 23:00 to 04:00 UTC.
TOU = ((datetime(2026, 10, 4, 23, 0, tzinfo=UTC), T0 + timedelta(hours=9)),)
#: The engine's outputs that are held.
OUTPUTS = ("points", "heating", "writes", "mode_writes", "modes")
#: Decimal places every held float is rounded to.
PLACES = 6


def at(h: float) -> datetime:
    return T0 + timedelta(hours=h)


def _params() -> HeaterParams:
    doc = json.loads((FIXTURES / "heater_params.json").read_text())
    return params_from_document(doc)


def _ambient(until: datetime) -> Any:
    """The air at the heater every 10 minutes, from an hour before the
    start to 6 hours past ``until``: cooling 0.0625 °F a step from
    71.5 °F for 8 hours, then warming at the same rate. Every value is
    exact in binary, so the series is the same on every platform."""
    stamps = pd.date_range(
        T0 - timedelta(hours=1), until + timedelta(hours=6), freq="10min"
    )
    values = [71.5 - 0.0625 * min(i, 96 - i) for i in range(len(stamps))]
    return pd.DataFrame({"ambient_f": values}, index=stamps)


def _physics(until: datetime, draws_on: bool) -> TankPhysics:
    return TankPhysics(
        _params(),
        _ambient(until),
        48.0,
        draws_on=draws_on,
        tau_gap_hours=10.0,
        low_confidence_floor=0.6,
    )


def _entry(sid: str, h: float, setpoint: float, mode: str) -> Entry:
    """An entry at ``h`` hours, written at the walk's start."""
    return Entry(at(h), mode, setpoint, T0, sid)  # type: ignore[arg-type]


def _shower(h: float, gal: float = 1.6, n: int = 8) -> list[Any]:
    """A shower's gallons a minute apart, from ``h`` hours."""
    return [(at(h) + timedelta(minutes=i), gal) for i in range(n)]


def _start_hold(deficit_f: float | None) -> float:
    """A start's hold in minutes: longer for a deeper deficit."""
    return 1.5 if deficit_f is None else min(6.0, 0.25 * deficit_f)


def _case(
    until_h: float, *, draws_on: bool = False, **kw: Any
) -> dict[str, Any]:
    return {"until_h": until_h, "draws_on": draws_on, **kw}


#: ``name: the walk's inputs``, apart from the physics.
CASES: dict[str, dict[str, Any]] = {
    # An idle tank coasting into the TOU window, where the upper zone's
    # trigger is capped.
    "coast_into_tou": _case(
        10.0,
        upper_f=132.4,
        lower_f=118.6,
        running=False,
        stopped_at=at(-3.2),
        heated_at=at(-3.2),
    ),
    # Entries through every mode and back, and one repeating the state,
    # inside and outside the window.
    "entries_every_mode": _case(
        12.0,
        upper_f=128.0,
        lower_f=112.0,
        running=False,
        stopped_at=at(-2.0),
        entries=[
            _entry("hp", 0.0, 140.9, "heat_pump"),
            _entry("es", 0.5, 143.6, "energy_saver"),
            _entry("hd", 1.5, 143.6, "high_demand"),
            _entry("el", 2.5, 143.6, "electric"),
            _entry("back", 3.5, 140.9, "heat_pump"),
            _entry("eco-window", 5.0, 140.9, "energy_saver"),
            _entry("hold", 8.5, 140.9, "heat_pump"),
        ],
    ),
    # A running recovery, a shower in it, and one in the TOU window
    # whose start waits for the window's close; the lead draws before
    # the start, and a start hold.
    "recovering_draws": _case(
        10.0,
        draws_on=True,
        upper_f=126.8,
        lower_f=101.3,
        running=True,
        stopped_at=at(-5.0),
        heated_at=at(0.0),
        draws=[*_shower(0.4), *_shower(5.2, gal=3.0, n=15)],
        lead_draws=[
            (at(-0.2) + timedelta(seconds=10 * i), 0.13) for i in range(48)
        ],
        running_hold=4.5,
        start_hold=_start_hold,
        marks=[at(0.4), at(5.2)],
    ),
    # Raw writes replayed as made, from Energy Saver with its element
    # on: a setpoint, High Demand, then Heat Pump in the window.
    "raw_writes_element": _case(
        10.0,
        upper_f=103.9,
        lower_f=98.0,
        running=False,
        stopped_at=at(-1.0),
        mode="energy_saver",
        element_running=True,
        element_running_since=at(-0.05),
        raw_writes=[
            RawWrite(at(0.75), setpoint_f=137.3, id="lower"),
            RawWrite(at(1.5), mode="high_demand", id="hd"),
            RawWrite(at(4.5), mode="heat_pump", setpoint_f=140.9, id="back"),
        ],
    ),
    # Withheld windows: the compressor runs and is charged, the tank
    # credited nothing, through two forecast draws.
    "withheld_windows": _case(
        14.0,
        draws_on=True,
        upper_f=131.0,
        lower_f=117.0,
        running=False,
        stopped_at=at(-3.0),
        heated_at=at(-3.0),
        draws=[(at(1.0), 20.0), (at(9.0), 26.0)],
        withheld_windows=[(at(1.0), at(1.5)), (at(9.0), at(9.75))],
        start_hold=_start_hold,
    ),
}


def _run(
    case: dict[str, Any],
    wrap: Callable[[TankPhysics], Physics] = lambda p: p,
) -> Simulation:
    c = dict(case)
    until = at(c.pop("until_h"))
    physics = wrap(_physics(until, c.pop("draws_on")))
    mode = c.pop("mode", "heat_pump")
    return simulate(
        start=T0,
        until=until,
        setpoint_f=140.9,
        heater=Heater(hp_lower_on_f=105.0, tou_windows=TOU, mode=mode),
        physics=physics,
        **c,
    )


# ── how an answer is held ───────────────────────────────────────────


def _default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, frozenset | set):
        return sorted(value)
    raise TypeError(f"not held: {type(value).__name__}")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=_default
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _rounded(value: Any) -> Any:
    """``value`` with every float rounded to ``PLACES``, and ``-0.0``
    held as ``0.0``."""
    if isinstance(value, float):
        return round(value, PLACES) + 0.0
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return value


def _outputs(simulation: Simulation) -> dict[str, Any]:
    """``simulation``'s held outputs as JSON holds them, every float
    rounded to ``PLACES``."""
    whole = dataclasses.asdict(simulation)
    return {k: _rounded(json.loads(_canonical(whole[k]))) for k in OUTPUTS}


def _summary(body: dict[str, Any]) -> dict[str, Any]:
    points = body["points"]
    last = points[-1] if points else None
    summary = {
        "points": len(points),
        "last": None
        if last is None
        else {
            k: last[k]
            for k in ("at", "upper_f", "lower_f", "setpoint_f", "mode")
        },
        "heating": [
            (
                h["start"]["at"],
                h["start"]["cause"],
                h["start"]["trigger"],
                h["end"],
                h["source"],
                h["zone"],
                h["stop"],
                h["input_wh"],
            )
            for h in body["heating"]
        ],
        "modes": [
            (m["start"], m["mode"], m["ended_by"]) for m in body["modes"]
        ],
        "writes": [
            (w["at"], w["mode"], w["setpoint_f"], w["owner"], w["outcome"])
            for w in body["writes"]
        ],
    }
    held: dict[str, Any] = json.loads(_canonical(summary))
    return held


def _held_form(answer: dict[str, Any]) -> dict[str, Any]:
    return {
        "sha256": _digest(answer),
        "summary": _summary(answer),
        "fields": {k: _digest(v)[:16] for k, v in sorted(answer.items())},
    }


def _load() -> dict[str, Any]:
    held: dict[str, Any] = (
        json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
    )
    return held


def _check(case: str, answer: dict[str, Any]) -> None:
    got = _held_form(answer)
    if os.environ.get(REGEN) == "1":
        held = _load()
        held[case] = got
        GOLDEN.write_text(json.dumps(held, indent=1, sort_keys=True) + "\n")
    held = _load()
    assert case in held, f"{case} has no held answer: hold one with {REGEN}=1"
    want = held[case]
    assert got["summary"] == want["summary"]
    moved = sorted(
        k
        for k in {*got["fields"], *want["fields"]}
        if got["fields"].get(k) != want["fields"].get(k)
    )
    assert not moved, f"{case}: these fields moved: {moved}"
    assert got["sha256"] == want["sha256"]


# ── the tests ───────────────────────────────────────────────────────


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_answer_is_the_held_one(case: str) -> None:
    _check(case, _outputs(_run(CASES[case])))


def test_the_cases_cover_what_they_claim() -> None:
    held = {k: v["summary"] for k, v in _load().items()}
    assert set(held) == set(CASES)
    every = {m[1] for m in held["entries_every_mode"]["modes"]}
    assert every == {"heat_pump", "energy_saver", "high_demand", "electric"}
    assert "element" in {h[4] for h in held["raw_writes_element"]["heating"]}
    assert held["recovering_draws"]["heating"]
    assert held["withheld_windows"]["heating"]
    assert held["coast_into_tou"]["heating"]


@dataclasses.dataclass(frozen=True, eq=False)
class _Sealed:
    """A state only its physics opens: equal to nothing but itself."""

    inner: TankState


class _SealedPhysics:
    """``TankPhysics`` behind states the engine cannot read."""

    def __init__(self, inner: TankPhysics) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    @staticmethod
    def _open(state: TankState) -> TankState:
        assert isinstance(state, _Sealed)
        return state.inner

    @staticmethod
    def _seal(points: list[Point]) -> list[Point]:
        return [
            dataclasses.replace(
                p, state=None if p.state is None else _Sealed(p.state)
            )
            for p in points
        ]

    def estimate(self, upper_f: float, lower_f: float) -> TankState:
        return _Sealed(self.inner.estimate(upper_f, lower_f))

    def observe(self, state: TankState) -> tuple[float, float]:
        return self.inner.observe(self._open(state))

    def coast(
        self,
        start: datetime,
        state: TankState,
        end: datetime,
        draws: Any,
        heated_at: datetime | None = None,
    ) -> Coast:
        got = self.inner.coast(start, self._open(state), end, draws, heated_at)
        return dataclasses.replace(got, points=self._seal(got.points))

    def heat(
        self, start: datetime, state: TankState, target_f: float, **kw: float
    ) -> Heat | None:
        got = self.inner.heat(start, self._open(state), target_f, **kw)
        if got is None:
            return None
        return dataclasses.replace(got, points=self._seal(got.points))

    def draw(self, at: datetime, state: TankState, gal: float) -> TankState:
        return _Sealed(self.inner.draw(at, self._open(state), gal))


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_engine_reads_the_tank_only_through_its_physics(
    case: str,
) -> None:
    """A physics whose state the engine cannot open or compare walks
    every case as ``TankPhysics`` does: the engine reads the tank only
    through its physics, and hands it back only states it gave."""
    assert _run(CASES[case], _SealedPhysics) == _run(CASES[case])


def _on_a_thread(fn: Callable[[], Simulation]) -> Simulation:
    out: list[Simulation] = []
    thread = threading.Thread(target=lambda: out.append(fn()))
    thread.start()
    thread.join()
    return out[0]


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_walk_is_deterministic(case: str) -> None:
    first = _run(CASES[case])
    assert _run(CASES[case]) == first
    assert _on_a_thread(lambda: _run(CASES[case])) == first
