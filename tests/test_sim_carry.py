"""Walks carried on through one tail (``sim.carry_on``)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sim_cases import PARAMS

from nwp500 import sim
from nwp500.sim import carry

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
        assert early.residual_f > sim.SETTLED_F
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

    def test_the_tail_walks_with_the_walks_inputs(
        self, plans: list[sim.SimulationResult]
    ) -> None:
        def held(_off: float | None) -> float:
            return 30.0

        [plain] = sim.carry_on(plans[2:], TAIL, PARAMS)
        [slow] = sim.carry_on(plans[2:], TAIL, PARAMS, start_hold=held)
        first = plain.tail.heating[0].start.at
        assert slow.tail.heating[0].start.at == first
        assert slow.tail.heating[0].end > plain.tail.heating[0].end

    def test_a_run_under_way_in_one_tail_is_not_settled(
        self, plans: list[sim.SimulationResult]
    ) -> None:
        # At 11:00 the next day the base walk's morning recovery is over
        # and the early boost's still under way.
        short = TAIL.model_copy(update={"horizon": timedelta(hours=11)})
        base, _, early = sim.carry_on(plans, short, PARAMS)
        assert base.tail.end_state is not None
        assert early.tail.end_state is not None
        assert not base.tail.end_state.compressor_running
        assert early.tail.end_state.compressor_running
        assert base.heating_alike
        assert not early.heating_alike
        assert not early.settled

    def test_a_held_mode_does_not_outlast_the_tails_settings(self) -> None:
        # Electric in force at 22:00 inside a window open since 21:00,
        # a Heat Pump entry at 23:30 held to the window's end.
        from nwp500 import sim_adapters as sa

        held = BASE.model_copy(
            update={
                "start": at(22),
                "horizon": timedelta(hours=2),
                "loads": sim.Loads(
                    draws=(sim.Draw(at=at(23.8), gallons=45, duration_s=600),)
                ),
                "settings": SETTINGS.model_copy(update={"mode": 2}),
                "commands": sim.Commands(
                    reservations=(
                        sa.reservation_entry(
                            days=range(7),
                            hour=23,
                            minute=30,
                            mode=1,
                            temperature=120.0,
                        ),
                    )
                ),
            }
        )
        walk = sim.simulate(
            held, PARAMS, tou_windows_in_force=[(at(21), at(25))]
        )
        end = walk.end_state
        assert end is not None and end.resume is not None
        assert '"held": {' in end.resume
        # No window opens at the tail's start to drop the element mode.
        [c] = sim.carry_on([walk], TAIL, PARAMS)
        written = TAIL.model_copy(
            update={
                "commands": sim.Commands(
                    writes=(sim.Write(at=TAIL.start, mode=1, setpoint_f=120),)
                )
            }
        )
        [w] = sim.carry_on([walk], written, PARAMS)
        heats = [h for h in c.tail.heating if h.start.at >= TAIL.start]
        assert heats[0].source == "compressor"
        assert heats[0].start.at - TAIL.start < timedelta(minutes=1)
        assert c.input_wh == pytest.approx(w.input_wh)
        electric = TAIL.model_copy(
            update={"settings": SETTINGS.model_copy(update={"mode": 2})}
        )
        [e] = sim.carry_on([walk], electric, PARAMS)
        assert e.input_wh != pytest.approx(c.input_wh)

    def test_a_start_pending_is_heating_under_way(self) -> None:
        # One tank just under the lower trigger inside the restart
        # lockout, its start pending past the tail's end; one just over.
        def walk(lower_f: float, stopped: timedelta) -> sim.SimulationResult:
            return sim.simulate(
                BASE.model_copy(
                    update={
                        "horizon": timedelta(minutes=1),
                        "loads": sim.Loads(),
                        "state": sim.HeaterState(upper_f=120, lower_f=lower_f),
                        "history": sim.History(
                            compressor_stopped_at=T0 - stopped
                        ),
                    }
                ),
                PARAMS,
            )

        idle = walk(111.2, timedelta(hours=3))
        pending = walk(110.8, timedelta(minutes=1))
        tail = TAIL.model_copy(
            update={
                "start": T0 + timedelta(minutes=1),
                "horizon": timedelta(minutes=2),
                "loads": sim.Loads(),
            }
        )
        first, other = sim.carry_on([idle, pending], tail, PARAMS)
        assert first.heating_alike
        assert other.residual_f <= sim.SETTLED_F
        assert not other.heating_alike
        assert not other.settled

    def test_an_elements_heat_still_arriving_is_under_way(self) -> None:
        # High Demand: the upper element's late-morning run, the walk
        # ending 30 s after it stops with nothing running, its heat
        # reaching the water a dead time (``upper_dead_time_min``,
        # 1.21 min) after.
        high = BASE.model_copy(
            update={
                "loads": sim.Loads(),
                "state": sim.HeaterState(upper_f=100, lower_f=95),
                "settings": SETTINGS.model_copy(update={"mode": 4}),
            }
        )
        probe = sim.simulate(high, PARAMS)
        stop = next(
            h.end
            for h in probe.heating
            if h.source == "element" and h.start.at > at(6)
        )
        span = {"horizon": stop + timedelta(seconds=30) - T0}
        walk = sim.simulate(high.model_copy(update=span), PARAMS)
        assert walk.end_state is not None
        assert not walk.end_state.element_running
        assert not walk.end_state.compressor_running
        assert walk.until < max(carry._due(walk, PARAMS))
        # The same layers with no heat on its way: their tails end
        # within SETTLED_F, the heat still arriving parts them after.
        e = walk.end_state
        bare = sim.simulate(
            BASE.model_copy(
                update={
                    "start": walk.until - timedelta(seconds=1),
                    "horizon": timedelta(seconds=1),
                    "loads": sim.Loads(),
                    "state": sim.HeaterState(
                        upper_f=e.upper_f,
                        lower_f=e.lower_f,
                        layers_f=e.layers_f,
                    ),
                    "history": walk.end_history,
                    "settings": SETTINGS.model_copy(update={"mode": 4}),
                }
            ),
            PARAMS,
        )
        tail = TAIL.model_copy(
            update={
                "start": walk.until,
                "horizon": timedelta(seconds=10),
                "loads": sim.Loads(),
                "settings": SETTINGS.model_copy(update={"mode": 4}),
            }
        )
        _, other = sim.carry_on([bare, walk], tail, PARAMS)
        assert other.residual_f <= sim.SETTLED_F
        assert not other.heating_alike
        assert not other.settled

    def test_a_lockout_with_no_start_wanted_is_none(self) -> None:
        # Both compressors off at the tail's end, one stopped a minute
        # before it: its next start waits out the restart lockout.
        def walk(stopped: timedelta) -> sim.SimulationResult:
            return sim.simulate(
                BASE.model_copy(
                    update={
                        "horizon": timedelta(minutes=1),
                        "loads": sim.Loads(),
                        "history": sim.History(
                            compressor_stopped_at=T0 - stopped
                        ),
                    }
                ),
                PARAMS,
            )

        tail = TAIL.model_copy(
            update={
                "start": T0 + timedelta(minutes=1),
                "horizon": timedelta(minutes=1),
                "loads": sim.Loads(),
            }
        )
        free, locked = walk(timedelta(hours=3)), walk(timedelta(minutes=1))
        _, other = sim.carry_on([free, locked], tail, PARAMS)
        # A full tank: no start is wanted in the lockout.
        assert other.tail.until < max(carry._due(other.tail, PARAMS))
        assert other.heating_alike
        assert other.settled

    def test_a_held_mode_is_written_over_only_where_nothing_else_decides(
        self,
    ) -> None:
        from nwp500 import sim_adapters as sa

        def held_walk(mode: int, entry_mode: int) -> sim.SimulationResult:
            return sim.simulate(
                BASE.model_copy(
                    update={
                        "start": at(22),
                        "horizon": timedelta(hours=2),
                        "loads": sim.Loads(),
                        "settings": SETTINGS.model_copy(update={"mode": mode}),
                        "commands": sim.Commands(
                            reservations=(
                                sa.reservation_entry(
                                    days=range(7),
                                    hour=23,
                                    minute=30,
                                    mode=entry_mode,
                                    temperature=120.0,
                                ),
                            )
                        ),
                    }
                ),
                PARAMS,
                tou_windows_in_force=[(at(21), at(25))],
            )

        heat_pump_held = held_walk(2, 1)
        writes = carry._over_a_hold(heat_pump_held, TAIL).writes
        assert [(w.at, w.mode) for w in writes] == [(TAIL.start, 1)]
        # The tail's mode is not the one held: simulate writes it.
        electric = TAIL.model_copy(
            update={"settings": SETTINGS.model_copy(update={"mode": 2})}
        )
        assert carry._over_a_hold(heat_pump_held, electric).writes == ()
        # An element mode held: written inside a window, held again.
        saver_held = held_walk(1, 3)
        for walk in (heat_pump_held, saver_held):
            assert walk.end_state is not None and walk.end_state.resume
            assert '"held": {' in walk.end_state.resume
        saver = TAIL.model_copy(
            update={"settings": SETTINGS.model_copy(update={"mode": 3})}
        )
        assert carry._over_a_hold(saver_held, saver).writes == ()
        # An entry firing at the tail's start decides the mode there.
        midnight = TAIL.model_copy(
            update={
                "commands": sim.Commands(
                    reservations=(
                        sa.reservation_entry(
                            days=range(7),
                            hour=0,
                            minute=0,
                            mode=3,
                            temperature=120.0,
                        ),
                    )
                )
            }
        )
        assert carry._over_a_hold(heat_pump_held, midnight).writes == ()
        # One the simulation does not model (Power Off) decides nothing.
        off = TAIL.model_copy(
            update={
                "commands": sim.Commands(
                    reservations=(
                        sa.reservation_entry(
                            days=range(7),
                            hour=0,
                            minute=0,
                            mode=5,
                            temperature=120.0,
                        ),
                    )
                )
            }
        )
        writes = carry._over_a_hold(heat_pump_held, off).writes
        assert [(w.at, w.mode) for w in writes] == [(TAIL.start, 1)]

    def test_a_tail_goes_on_with_its_own_schedule(self) -> None:
        # The tail's own entry raises the setpoint at 00:02; one tank's
        # start waits out a lockout, the recoveries run out of step, and
        # at 02:22 one is still heating to the new setpoint, the other
        # done. Gone on in the tail's standing settings, both would stop
        # and read alike.
        from nwp500 import sim_adapters as sa

        def walk(stopped: timedelta) -> sim.SimulationResult:
            return sim.simulate(
                BASE.model_copy(
                    update={
                        "horizon": timedelta(minutes=1),
                        "loads": sim.Loads(),
                        "state": sim.HeaterState(upper_f=120, lower_f=110.8),
                        "history": sim.History(
                            compressor_stopped_at=T0 - stopped
                        ),
                    }
                ),
                PARAMS,
            )

        tail = TAIL.model_copy(
            update={
                "start": T0 + timedelta(minutes=1),
                "horizon": timedelta(minutes=141),
                "loads": sim.Loads(),
                "commands": sim.Commands(),
                "schedules": sim.Schedules(
                    reservations=(
                        sa.reservation_entry(
                            days=range(7),
                            hour=0,
                            minute=2,
                            mode=1,
                            temperature=130.0,
                        ),
                    )
                ),
            }
        )
        first, other = sim.carry_on(
            [walk(timedelta(hours=3)), walk(timedelta(minutes=1))], tail, PARAMS
        )
        assert first.tail.end_state is not None
        assert other.tail.end_state is not None
        assert first.tail.end_state.compressor_running
        assert not other.tail.end_state.compressor_running
        assert other.residual_f <= sim.SETTLED_F
        assert not other.heating_alike

    def test_a_start_a_window_holds_off_is_heating_to_come(self) -> None:
        # A peak 00:30-01:15: at 01:03 the tank below its trigger waits
        # for the window's close, stored as no pending start.
        periods = (
            sim.TouPeriod(
                season=0xFFF, week=0xFE, start_hour=0, start_minute=0,
                end_hour=0, end_minute=29, price_max=10,
            ),
            sim.TouPeriod(
                season=0xFFF, week=0xFE, start_hour=0, start_minute=30,
                end_hour=1, end_minute=14, price_max=50,
            ),
            sim.TouPeriod(
                season=0xFFF, week=0xFE, start_hour=1, start_minute=15,
                end_hour=23, end_minute=59, price_max=10,
            ),
        )  # fmt: skip
        schedules = sim.Schedules(tou_enabled=True, tou_periods=periods)

        def walk(lower_f: float) -> sim.SimulationResult:
            return sim.simulate(
                BASE.model_copy(
                    update={
                        "start": at(1),
                        "horizon": timedelta(minutes=1),
                        "loads": sim.Loads(),
                        "state": sim.HeaterState(upper_f=120, lower_f=lower_f),
                        "schedules": schedules,
                        "history": sim.History(
                            compressor_stopped_at=at(1) - timedelta(hours=3)
                        ),
                    }
                ),
                PARAMS,
            )

        tail = TAIL.model_copy(
            update={
                "start": at(1) + timedelta(minutes=1),
                "horizon": timedelta(minutes=2),
                "loads": sim.Loads(),
                "schedules": schedules,
            }
        )
        _, owing = sim.carry_on([walk(111.2), walk(110.8)], tail, PARAMS)
        assert owing.residual_f <= sim.SETTLED_F
        assert not owing.heating_alike
        assert not owing.settled

    def test_refuses(self, plans: list[sim.SimulationResult]) -> None:
        with pytest.raises(ValueError, match="no walks"):
            sim.carry_on([], TAIL, PARAMS)
        later = TAIL.model_copy(
            update={"start": TAIL.start + timedelta(hours=1)}
        )
        with pytest.raises(ValueError, match="ends at"):
            sim.carry_on(plans, later, PARAMS)
