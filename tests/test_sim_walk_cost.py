"""What a simulation walks: about its span once, however long the span.

A coast finds the heater's own start on the walk ahead of it and then
walks again to there, so how far it looks bounds what a simulation
costs. These hold the span walked over days of draws to a small
multiple of the days.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

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
)
from nwp500.sim.tank_physics import TankPhysics

T0 = datetime(2026, 10, 4, 7, 0, tzinfo=UTC)


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
    # Each start walks a coast's look-ahead twice at most.
    assert sum(walked, timedelta()) < 1.5 * s.horizon
