"""Walks carried on through one tail (``sim.carry_on``)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sim_cases import PARAMS

from nwp500 import sim
from nwp500.sim.carry import SETTLED_F

TZ = "America/Los_Angeles"
T0 = datetime(2026, 10, 6, 0, 0, tzinfo=ZoneInfo(TZ))
DAY = timedelta(days=1)
SETTINGS = sim.Settings(setpoint_f=120, hp_lower_on_f=111, hp_lower_off_f=120)
ENV = sim.Environment(ambient_f=62, inlet_f=58)


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def _draws(day: int) -> tuple[sim.Draw, ...]:
    return tuple(
        sim.Draw(at=at(24 * day + h), gallons=g, duration_s=s)
        for h, g, s in (
            (7.0, 15.0, 600),
            (7.5, 15.0, 600),
            (18.5, 10.0, 900),
            (19.5, 20.0, 720),
            (20.0, 15.0, 600),
        )
    )


BASE = sim.Scenario(
    start=T0,
    horizon=DAY,
    tz=TZ,
    state=sim.HeaterState(upper_f=120, lower_f=118),
    settings=SETTINGS,
    history=sim.History(compressor_stopped_at=T0 - timedelta(hours=3)),
    environment=ENV,
    loads=sim.Loads(draws=_draws(0)),
)
TAIL = sim.Scenario(
    start=T0 + DAY,
    horizon=DAY,
    tz=TZ,
    state=sim.HeaterState(upper_f=120, lower_f=118),
    settings=SETTINGS,
    environment=ENV,
    loads=sim.Loads(draws=_draws(1)),
)


def _boost(setpoint_f: float, hours: float) -> sim.Scenario:
    """A pre-peak boost, back to the standing setpoint at 21:00."""
    return BASE.model_copy(
        update={
            "commands": sim.Commands(
                writes=(
                    sim.Write(at=at(hours), setpoint_f=setpoint_f),
                    sim.Write(at=at(21), setpoint_f=120),
                )
            )
        }
    )


def _price(t: datetime) -> float:
    return 0.50 if 16 <= t.astimezone(ZoneInfo(TZ)).hour < 21 else 0.20


def _cost(slots: list[tuple[datetime, float | None]]) -> float:
    return sum(_price(t) * wh / 1000 for t, wh in slots if wh)


SLOT = timedelta(minutes=15)


@pytest.fixture(scope="module")
def plans() -> list[sim.SimulationResult]:
    return [
        sim.simulate(s, PARAMS)
        for s in (BASE, _boost(130, 14), _boost(149, 11))
    ]


@pytest.fixture(scope="module")
def carried(plans: list[sim.SimulationResult]) -> tuple[sim.Carried, ...]:
    return sim.carry_on(plans, TAIL, PARAMS)


class TestCarryOn:
    def test_a_plan_and_its_tail_are_one_walk(
        self, carried: tuple[sim.Carried, ...]
    ) -> None:
        boost = _boost(130, 14)
        whole = sim.simulate(
            boost.model_copy(
                update={
                    "horizon": 2 * DAY,
                    "loads": sim.Loads(draws=_draws(0) + _draws(1)),
                }
            ),
            PARAMS,
        )
        assert carried[1].input_wh == pytest.approx(whole.input_wh, rel=1e-6)
        assert _cost(carried[1].energy_by_slot(SLOT)) == pytest.approx(
            _cost(whole.energy_by_slot(SLOT)), rel=1e-6
        )

    def test_what_a_plan_leaves_is_paid_for_after_it(
        self, carried: tuple[sim.Carried, ...]
    ) -> None:
        base, late, early = carried
        # Over its own day the late boost is the cheapest; it leaves the
        # lower tank short, and the tail heats it again.
        assert _cost(late.walk.energy_by_slot(SLOT)) < _cost(
            base.walk.energy_by_slot(SLOT)
        )
        assert late.walk.end_state is not None
        assert late.walk.end_state.lower_f < 100.0
        assert _cost(late.energy_by_slot(SLOT)) > _cost(
            base.energy_by_slot(SLOT)
        )
        assert _cost(early.energy_by_slot(SLOT)) > _cost(
            base.energy_by_slot(SLOT)
        )

    def test_a_day_long_tail_settles_them(
        self, carried: tuple[sim.Carried, ...]
    ) -> None:
        assert carried[0].residual_wh == 0.0
        assert carried[0].residual_f == 0.0
        assert all(c.settled for c in carried)
        assert all(abs(c.residual_wh) < 100.0 for c in carried)

    def test_a_short_one_does_not(
        self, plans: list[sim.SimulationResult]
    ) -> None:
        short = sim.carry_on(
            plans,
            TAIL.model_copy(update={"horizon": timedelta(hours=12)}),
            PARAMS,
        )
        early = short[2]
        assert not early.settled
        assert early.residual_f > SETTLED_F
        # Its tank still short of the base plan's when the tail ends.
        assert early.residual_wh < 0.0

    def test_the_tail_writes_its_settings_over_what_a_plan_left(self) -> None:
        electric = sim.simulate(
            BASE.model_copy(
                update={
                    "commands": sim.Commands(
                        writes=(sim.Write(at=at(20), mode=2, setpoint_f=130),)
                    )
                }
            ),
            PARAMS,
        )
        assert electric.end_settings is not None
        assert electric.end_settings.mode == 2
        [c] = sim.carry_on([electric], TAIL, PARAMS)
        assert c.tail.modes[0].mode == "heat_pump"
        assert c.tail.modes[0].start == TAIL.start

    def test_a_slot_the_plan_and_tail_share_holds_both(self) -> None:
        off_grid = BASE.model_copy(
            update={"horizon": DAY + timedelta(minutes=7)}
        )
        plan = sim.simulate(off_grid, PARAMS)
        tail = TAIL.model_copy(update={"start": plan.until})
        [c] = sim.carry_on([plan], tail, PARAMS)
        slots = c.energy_by_slot(SLOT)
        assert len({t for t, _ in slots}) == len(slots)
        assert sum(wh for _, wh in slots if wh) == pytest.approx(c.input_wh)

    def test_refuses(self, plans: list[sim.SimulationResult]) -> None:
        with pytest.raises(ValueError, match="no walks"):
            sim.carry_on([], TAIL, PARAMS)
        later = TAIL.model_copy(
            update={"start": TAIL.start + timedelta(hours=1)}
        )
        with pytest.raises(ValueError, match="ends at"):
            sim.carry_on(plans, later, PARAMS)
