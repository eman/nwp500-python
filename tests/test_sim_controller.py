"""The heater's firmware as a state machine (``nwp500.sim.controller``).

One test per transition, each named for its rule; each docstring names
the measurement or record the rule rests on. The engine's walk over
these is tested on its own.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from nwp500.sim import controller
from nwp500.sim.controller import (
    POWERED_ON_BY_ENTRY,
    Action,
    Begins,
    Cap,
    DeadTimeEnds,
    Dropped,
    ElementCheck,
    ElementRetarget,
    ElementWasOn,
    EntryFired,
    EntryFires,
    EntrySkipped,
    Event,
    HeaterTrigger,
    Horizon,
    LockoutEnds,
    ModeHeld,
    ModeSet,
    ModeTook,
    ModeWithdrawn,
    ModeWrite,
    Note,
    RawWrites,
    RecordModeWrite,
    RecordWrite,
    RecoveryDone,
    Retarget,
    SetpointSet,
    SetpointWrite,
    Settings,
    Start,
    StartCompressor,
    StartDue,
    StartElement,
    StartHoldEnds,
    State,
    StopCompressor,
    StopElement,
    Tank,
    Then,
    TriggerDeferred,
    UpperOnCrossed,
    UpperRead,
    WindowCloses,
    WindowOpens,
    Written,
    cap_outcome,
    initial_state,
    judge_cap,
    transition,
    trigger_ahead,
    upper_on_crossing,
    wake_times,
)
from nwp500.sim.decay import Impulse
from nwp500.sim.params import ControllerParams, ElementParams
from nwp500.sim.physics.element import HeaterMode
from nwp500.sim.tank_physics import Point
from nwp500.sim.tou_triggers import LOWER_TRIGGER_HELD, Window

P = ControllerParams()
EP = ElementParams()
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
LAG = P.write_start_lag
LOCKOUT = P.restart_lockout


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


#: A TOU window around the instants these tests act at.
WINDOW = (at(-10), at(60))


def settings(
    *,
    windows: Sequence[Window] = (),
    hp_lower_on: float | None = 104.9,
    disabled: bool = False,
    powered_off: bool = False,
    start_hold: Callable[[float | None], float] | None = None,
) -> Settings:
    return Settings(
        hp_lower_on_f=hp_lower_on,
        tou_windows=tuple(windows),
        heating_disabled=disabled or powered_off,
        powered_off=powered_off,
        start_hold=start_hold,
    )


def fresh(
    *,
    setpoint: float = 140.0,
    mode: HeaterMode = "heat_pump",
    stopped_at: datetime | None = None,
    now: datetime = T0,
) -> State:
    return initial_state(
        at=now,
        setpoint_f=setpoint,
        mode=mode,
        running=False,
        stopped_at=stopped_at,
        params=P,
    )


def step(
    state: State, event: Event, s: Settings | None = None
) -> tuple[State, tuple[Action, ...]]:
    return transition(state, event, s or settings(), P)


def tank(upper: float, lower: float) -> Tank:
    return Tank(upper, lower)


def of[A](actions: Iterable[Action], kind: type[A]) -> list[A]:
    return [a for a in actions if isinstance(a, kind)]


def notes(actions: Iterable[Action]) -> set[str]:
    return {a.reason for a in actions if isinstance(a, Note)}


def running(
    state: State,
    minutes: float = 0.0,
    s: Settings | None = None,
    upper: float = 120.0,
    lower: float = 100.0,
) -> State:
    """``state`` with the compressor started by its own trigger."""
    st, _ = step(
        state,
        HeaterTrigger(at=at(minutes), tank=tank(upper, lower), trigger="lower"),
        s,
    )
    return st


def element_on(
    mode: HeaterMode,
    upper: float,
    lower: float = 120.0,
    setpoint: float = 140.0,
    s: Settings | None = None,
) -> State:
    """``mode`` in force with an element on at the walk's start."""
    st, _ = step(
        fresh(mode=mode, setpoint=setpoint),
        ElementWasOn(at=T0, tank=tank(upper, lower)),
        s,
    )
    assert st.element.running
    return st


# ── The compressor ──────────────────────────────────────────────────


class TestTheCompressor:
    def test_a_compressor_running_at_the_start_runs_on_with_its_hold(
        self,
    ) -> None:
        """A start holds before the lower zone climbs, and a compressor
        already running at the walk's start holds for what is left of
        its own start's hold. Electric runs no heat pump (0 of 6)."""
        st, acts = step(
            fresh(),
            Begins(at=T0, tank=tank(120, 100), running=True, running_hold=3.0),
        )
        assert of(acts, StartCompressor) == [
            StartCompressor(Start(T0, "running"), False, 3.0)
        ]
        assert st.compressor.phase == "holding"
        assert st.compressor.hold_until == at(3)
        _, acts = step(
            fresh(mode="electric"),
            Begins(at=T0, tank=tank(120, 100), running=True),
        )
        assert not of(acts, StartCompressor)

    def test_a_start_holds_by_how_long_the_compressor_was_off(self) -> None:
        """The start hold: a start holds the longer the longer the
        compressor was off, by a fitted function of the minutes since
        the last stop; ``holding`` until it ends, then ``heating``."""
        gaps: list[float | None] = []

        def hold(gap: float | None) -> float:
            gaps.append(gap)
            return 4.0

        s = settings(start_hold=hold)
        st = running(fresh(stopped_at=at(-60)), s=s)
        assert gaps == [60.0]
        assert st.compressor.phase == "holding"
        st, _ = step(st, StartHoldEnds(at=at(3)), s)
        assert st.compressor.phase == "holding"
        st, _ = step(st, StartHoldEnds(at=at(4)), s)
        assert st.compressor.phase == "heating"

    def test_the_restart_lockout_holds_a_start_330_s_after_a_stop(self) -> None:
        """After it stops, the compressor does not start again for
        330 s: two device write-test restarts on 2026-09-23 came
        5 min 28 s and 5 min 31 s after the stop; on the record, starts
        within ten minutes of a stop waited up to 329 s. A trigger
        inside it waits as a pending start, the earliest kept."""
        st = fresh(stopped_at=T0)
        assert st.compressor.phase == "locked_out"
        coast = [(T0, 130.0, 106.0), (at(10), 129.0, 103.9)]
        ahead, _ = trigger_ahead(st, settings(), P, coast, [], T0)
        assert ahead is not None
        assert ahead.trigger_at < T0 + LOCKOUT
        assert ahead.starts_at == T0 + LOCKOUT
        st, _ = step(
            st,
            TriggerDeferred(
                at=T0,
                starts_at=ahead.starts_at,
                trigger=ahead.trigger,
                horizon=at(60),
            ),
        )
        assert st.compressor.pending == Start(
            T0 + LOCKOUT, "heater", trigger="lower"
        )
        later, _ = step(
            st,
            TriggerDeferred(
                at=T0,
                starts_at=at(8),
                trigger="lower",
                horizon=at(60),
            ),
        )
        assert later.compressor.pending == st.compressor.pending
        st, _ = step(st, LockoutEnds(at=T0 + LOCKOUT))
        assert st.compressor.phase == "idle"

    def test_the_lower_zone_at_hp_lower_on_starts_it(self) -> None:
        """Outside a window, the lower zone falling to
        ``hp_lower_on`` starts the compressor: 104 of 104 crossings in
        heat_pump that reached two probe steps under it started within
        30 s, every one with the upper zone short of the setpoint. The
        heater's own start takes over any start pending."""
        st = replace(
            fresh(),
            compressor=replace(
                fresh().compressor, pending=Start(at(30), "write")
            ),
        )
        coast = [(T0, 130.0, 106.0), (at(10), 129.0, 103.9)]
        ahead, found = trigger_ahead(st, settings(), P, coast, [], T0)
        assert ahead is not None and found == ()
        assert ahead.trigger == "lower"
        assert ahead.starts_at == ahead.trigger_at
        st, acts = step(
            st,
            HeaterTrigger(
                at=ahead.starts_at, tank=tank(129.5, 104.9), trigger="lower"
            ),
        )
        assert of(acts, StartCompressor) == [
            StartCompressor(
                Start(ahead.starts_at, "heater", trigger="lower"), True, 0.0
            )
        ]
        assert st.compressor.pending is None
        assert st.compressor.running

    def test_the_lower_trigger_waits_while_the_upper_zone_is_at_setpoint(
        self,
    ) -> None:
        """A device test on 2026-10-03: the hold-off entry left the upper
        zone 14.04 °F above a 120.2 °F setpoint, the lower zone fell to
        99.5 °F, and nothing started, in heat_pump. Energy Saver held a
        lower zone 18 °F under its setting for 9 h 54 min with the upper
        zone above a 107.6 °F setpoint, and a circulation run's drop
        started it (2026-09-21)."""
        coast = [(T0, 134.2, 106.0), (at(10), 134.0, 99.5)]
        drop = [Impulse(at(20), 99.4, 95.0)]
        longer = [*coast, (at(30), 133.8, 95.0)]
        for mode in ("heat_pump", "energy_saver"):
            ahead, found = trigger_ahead(
                fresh(setpoint=120.2, mode=mode), settings(), P, coast, [], T0
            )
            assert ahead is None
            assert found == (LOWER_TRIGGER_HELD,)
        ahead, _ = trigger_ahead(
            fresh(setpoint=120.2), settings(), P, longer, drop, T0
        )
        assert ahead is None
        ahead, _ = trigger_ahead(
            fresh(setpoint=120.2, mode="energy_saver"),
            settings(),
            P,
            longer,
            drop,
            T0,
        )
        assert ahead is not None and ahead.trigger == "lower"
        assert ahead.trigger_at == at(20)

    @pytest.mark.parametrize(
        ("before", "after", "starts"),
        [(108.0, 107.0, False), (108.0, 103.0, True), (103.0, 103.0, False)],
    )
    def test_energy_saver_starts_on_a_drop_landing_under_its_setting(
        self, before: float, after: float, starts: bool
    ) -> None:
        """A lower zone the gap's relaxation warmed past the setting is
        not released by a drop that leaves it there, nor one under it by
        a draw that moved the upper zone alone."""
        coast = [(T0, 134.2, 104.0), (at(10), 134.0, before)]
        coast += [(at(20), 133.8, after)]
        drop = [Impulse(at(15), before, after)]
        ahead, _ = trigger_ahead(
            fresh(setpoint=120.2, mode="energy_saver"),
            settings(),
            P,
            coast,
            drop,
            T0,
        )
        assert (ahead is not None and ahead.trigger_at == at(15)) is starts

    def test_a_held_lower_trigger_the_lower_zone_warmed_out_of_waits(
        self,
    ) -> None:
        """The upper zone falls below the setpoint after the lower zone
        has warmed back over its setting: the lower trigger alone
        decides from there."""
        coast = [(T0, 134.2, 104.0), (at(10), 121.0, 108.0)]
        coast += [(at(20), 119.0, 107.0)]
        drop = [Impulse(at(15), 108.0, 107.0)]
        ahead, _ = trigger_ahead(
            fresh(setpoint=120.2), settings(), P, coast, drop, T0
        )
        assert ahead is None
        coast += [(at(30), 118.8, 103.0)]
        ahead, _ = trigger_ahead(
            fresh(setpoint=120.2), settings(), P, coast, drop, T0
        )
        assert ahead is not None
        assert ahead.trigger_at == at(20) + (at(30) - at(20)) * (2.1 / 4.0)

    def test_the_lower_zone_between_drops_runs_to_the_next_drops_start(
        self,
    ) -> None:
        """Read back at an upper release, the lower zone's coast runs to
        the next drop's start, as ``threshold_crossing`` walks it: the
        crossing stays where the coast put it."""
        coast = [(T0, 119.0, 106.0), (at(20), 118.8, 106.0)]
        drops = [Impulse(at(10), 104.0, 103.0)]
        ahead, _ = trigger_ahead(
            fresh(setpoint=120.2), settings(), P, coast, drops, T0
        )
        assert ahead is not None
        assert ahead.trigger_at == T0 + (at(10) - T0) * (1.1 / 2.0)

    def test_the_upper_zone_short_in_a_window_starts_it(self) -> None:
        """Inside a window the heater starts when the upper
        zone is more than 14.4 °F short of the setpoint: 17 of 17
        openings 15.48 °F or more short started 25-34 s later, and none
        of 38 at 11.88 °F or less did."""
        s = settings(windows=[(at(10), at(100))])
        coast = [(T0, 124.0, 120.0), (at(20), 123.9, 119.9)]
        ahead, _ = trigger_ahead(fresh(), s, P, coast, [], T0)
        assert ahead is not None
        assert (ahead.starts_at, ahead.trigger) == (at(10), "upper_at_tou_open")
        warm = [(T0, 130.0, 120.0), (at(20), 129.9, 119.9)]
        assert trigger_ahead(fresh(), s, P, warm, [], T0)[0] is None

    def test_the_lower_trigger_inside_a_window_waits_for_its_close(
        self,
    ) -> None:
        """9 of 9 window closes with the lower zone below
        ``hp_lower_on`` started at once; of 19 in-window crossings with
        the compressor off (2026-04-08 to 10-01), none started on the
        lower trigger before the close."""
        s = settings(windows=[(at(-10), at(30))])
        coast = [(T0, 135.0, 106.0), (at(60), 134.0, 100.0)]
        ahead, _ = trigger_ahead(fresh(), s, P, coast, [], T0)
        assert ahead is not None
        assert (ahead.starts_at, ahead.trigger) == (
            at(30),
            "lower_at_tou_close",
        )

    def test_a_raise_releasing_the_lower_trigger_is_answered_as_a_write(
        self,
    ) -> None:
        """The closing entry of a device test on 2026-10-03: the raise
        released a held lower trigger and the compressor started 31.6 s after it
        landed, as a write's start, not the heater's own at once."""
        coast = [(T0, 112.0, 99.5), (at(10), 111.9, 99.4)]
        st = fresh(setpoint=128.6)
        ahead, _ = trigger_ahead(st, settings(), P, coast, [], T0)
        assert ahead is not None and ahead.starts_at == T0
        pending = replace(
            st,
            compressor=replace(st.compressor, pending=Start(T0 + LAG, "write")),
        )
        assert trigger_ahead(pending, settings(), P, coast, [], T0)[0] is None

    def test_a_trigger_cannot_read_the_tank_a_recovery_just_left(self) -> None:
        """A recovery that ended has left the lower zone at its target:
        no start reads that tank at the same instant (on the record,
        starts within ten minutes of a stop waited a median 86 s and up
        to 329 s, never none)."""
        st, _ = step(running(fresh()), RecoveryDone(at=T0, tank=tank(140, 140)))
        coast = [(T0, 130.0, 104.0), (at(10), 129.0, 103.0)]
        assert st.compressor.finished_at == T0
        assert trigger_ahead(st, settings(), P, coast, [], T0)[0] is None

    def test_a_pending_start_comes_due(self) -> None:
        """A write's start lands about 30 s after the write (a median
        over the record's starts more than ten minutes after a stop;
        118 of 120 writes leaving the upper zone short started); one
        already running is not started again."""
        st, _ = step(
            fresh(setpoint=130.0),
            SetpointWrite(
                at=T0, tank=tank(128, 120), setpoint_f=140.0, serves="w"
            ),
        )
        assert st.compressor.pending == Start(T0 + LAG, "write", serves="w")
        st, acts = step(st, StartDue(at=T0 + LAG, tank=tank(128, 120)))
        assert of(acts, StartCompressor)[0].start == Start(
            T0 + LAG, "write", serves="w"
        )
        assert st.compressor.pending is None
        again = replace(
            st, compressor=replace(st.compressor, pending=Start(at(5), "write"))
        )
        _, acts = step(again, StartDue(at=at(5), tank=tank(130, 125)))
        assert not of(acts, StartCompressor)

    def test_the_horizon_cuts_what_runs(self) -> None:
        """The walk's end: a recovery and an element running there end
        at it, ``horizon``."""
        st = running(element_on("energy_saver", upper=130.0))
        _, acts = step(st, Horizon(at=at(60), tank=tank(131, 125)))
        assert of(acts, StopCompressor) == [StopCompressor(at(60), "horizon")]
        assert of(acts, StopElement) == [StopElement(at(60), "horizon")]


# ── Setpoint writes ───────────────────────────────────────────


class TestSetpointWrites:
    def test_a_write_leaving_the_upper_zone_short_starts_it(self) -> None:
        """Outside a window, a write that left the upper zone short
        of the new setpoint started the compressor in 118 of 120 writes
        (120 of 122 to 2026-10-03), 30 s after it (median); inside the
        restart lockout, when the lockout ends."""
        st, acts = step(
            fresh(setpoint=130.0),
            SetpointWrite(
                at=T0, tank=tank(128, 120), setpoint_f=140.0, serves="w"
            ),
        )
        assert of(acts, RecordWrite) == [RecordWrite(T0, 140.0, None, "w")]
        assert of(acts, SetpointSet) == [SetpointSet(T0, 140.0)]
        assert st.setpoint_f == 140.0
        assert st.compressor.pending == Start(T0 + LAG, "write", serves="w")
        locked, _ = step(
            fresh(setpoint=130.0, stopped_at=at(-1)),
            SetpointWrite(at=T0, tank=tank(128, 120), setpoint_f=140.0),
        )
        assert locked.compressor.pending is not None
        assert locked.compressor.pending.at == at(-1) + LOCKOUT

    def test_a_write_left_at_or_above_the_upper_zone_starts_nothing(
        self,
    ) -> None:
        """Lowerings that left the upper zone at or above the new
        setpoint started 0 of 15 (the hold-off entry of a device test on
        2026-10-03, 120.2 °F with the upper zone at 137.1, among them):
        no start, unflagged.
        A raise so left started 1 of 1 (2026-05-01): no start, flagged.
        A write repeating the setpoint is no write."""
        st, acts = step(
            fresh(setpoint=140.0),
            SetpointWrite(at=T0, tank=tank(137.1, 130), setpoint_f=120.2),
        )
        assert st.compressor.pending is None
        assert "write_start_uncertain" not in notes(acts)
        st, acts = step(
            fresh(setpoint=120.0),
            SetpointWrite(at=T0, tank=tank(137.0, 130), setpoint_f=125.0),
        )
        assert st.compressor.pending is None
        assert "write_start_uncertain" in notes(acts)
        _, acts = step(
            fresh(setpoint=140.0),
            SetpointWrite(at=T0, tank=tank(130, 120), setpoint_f=140.0),
        )
        assert acts == ()

    def test_in_a_window_a_write_starts_it_only_more_than_4_f_short(
        self,
    ) -> None:
        """Inside a TOU window: writes more than 4 °F short started
        16 of 17; 0-4 °F short, 3 of 15 (device runs 2026-09-25 at
        1.8 °F and 09-26 at 2.7 °F started nothing; 09-26's 3.8 °F
        restore started it): no start there, flagged."""
        s = settings(windows=[WINDOW])
        st, _ = step(
            fresh(),
            SetpointWrite(at=T0, tank=tank(138, 130), setpoint_f=142.5),
            s,
        )
        assert st.compressor.pending is not None
        st, acts = step(
            fresh(),
            SetpointWrite(at=T0, tank=tank(138, 130), setpoint_f=141.0),
            s,
        )
        assert st.compressor.pending is None
        assert "write_start_uncertain" in notes(acts)

    def test_a_write_that_starts_nothing_cancels_a_writes_start(self) -> None:
        """Each write decides afresh, so a later write that would
        not start the compressor cancels a start an earlier write set
        going (a count over stepped sequences credited the later, larger
        step); the heater's own start, waiting out the lockout,
        stands."""
        st, _ = step(
            fresh(setpoint=130.0),
            SetpointWrite(at=T0, tank=tank(128, 120), setpoint_f=140.0),
        )
        assert st.compressor.pending is not None
        st, _ = step(
            st, SetpointWrite(at=at(0.1), tank=tank(128, 120), setpoint_f=125.0)
        )
        assert st.compressor.pending is None
        own = Start(at(5), "heater", trigger="lower")
        st = replace(st, compressor=replace(st.compressor, pending=own))
        st, _ = step(
            st, SetpointWrite(at=at(0.2), tank=tank(128, 120), setpoint_f=120.0)
        )
        assert st.compressor.pending == own

    def test_a_lowering_to_the_upper_zone_stops_a_recovery(self) -> None:
        """With the compressor on, a lowering to at or below the
        upper zone ends the call for heat: 19 of 25 so stopped, against
        10 of 44 left above it; two device runs on 2026-09-23 both
        stopped, 6 s and 150 s after the write. A raise leaves the call
        the lower zone's: the recovery runs on to the new target."""
        st = running(fresh())
        after, acts = step(
            st, SetpointWrite(at=at(1), tank=tank(130, 110), setpoint_f=125.0)
        )
        assert of(acts, StopCompressor) == [StopCompressor(at(1), "write")]
        assert after.compressor.phase == "locked_out"
        _, acts = step(
            st, SetpointWrite(at=at(1), tank=tank(130, 110), setpoint_f=145.0)
        )
        assert of(acts, Retarget) == [Retarget(at(1))]
        assert not of(acts, StopCompressor)

    def test_in_a_window_a_write_ends_a_recovery_at_the_caps_level(
        self,
    ) -> None:
        """The TOU cap with the write rule: the lower zone already at
        the new setpoint is a finished recovery, and inside a window
        that is the cap's level, 3.6 °F short (the device references its
        deficit counter 2 °C under the setpoint there;
        ``docs/explanation/tou-recovery-cap.rst``)."""
        s = settings(windows=[WINDOW])
        st = running(fresh(setpoint=135.0), s=s)
        _, acts = step(
            st,
            SetpointWrite(at=at(1), tank=tank(130, 137), setpoint_f=140.0),
            s,
        )
        assert of(acts, StopCompressor) == [StopCompressor(at(1), "write")]
        _, acts = step(
            running(fresh(setpoint=135.0)),
            SetpointWrite(at=at(1), tank=tank(130, 137), setpoint_f=140.0),
        )
        assert of(acts, Retarget) == [Retarget(at(1))]


# ── The TOU cap ───────────────────────────────────────────────


class TestTheTouCap:
    def test_a_recovery_ending_in_a_window_stops_short_of_its_target(
        self,
    ) -> None:
        """A recovery that ends inside a window stops 3.6 °F short of
        its target, judged at its end: judging at the start caught 17 of
        59 capped cycles against 43 at the end
        (``docs/explanation/tou-recovery-cap.rst``)."""
        window = (at(60), at(180))
        full = [Point(T0, 120.0, 120.0), Point(at(120), 140.0, 140.0)]
        cap = judge_cap(
            full,
            at=T0,
            lower_f=120.0,
            target_f=140.0,
            windows=[window],
            params=P,
        )
        assert cap == Cap("to_level", 140.0 - P.tou_cap_f, window)
        assert cap_outcome(at(98.4), window) == "to_level"
        assert cap_outcome(at(30), window) == "until_open"
        assert cap_outcome(None, window) == "until_open"
        assert cap_outcome(at(200), window) == "full"
        assert judge_cap(
            full, at=T0, lower_f=120.0, target_f=140.0, windows=[], params=P
        ) == Cap("none")
        there = [Point(at(70), 137.0, 137.0), Point(at(80), 140.0, 140.0)]
        assert (
            judge_cap(
                there,
                at=at(70),
                lower_f=137.0,
                target_f=140.0,
                windows=[window],
                params=P,
            ).kind
            == "at_level"
        )

    def test_a_capped_stop_is_capped_until_the_window_closes(self) -> None:
        """A recovery reaching the cap's level stops there, ``cap``,
        and the compressor is ``capped`` until the window closes (the
        cap holds while the window is in force,
        ``docs/explanation/tou-recovery-cap.rst``)."""
        s = settings(windows=[(at(60), at(180))])
        st = running(fresh(), minutes=30, s=s)
        st, acts = step(
            st, RecoveryDone(at=at(100), tank=tank(138, 136.4), capped=True), s
        )
        assert of(acts, StopCompressor) == [StopCompressor(at(100), "cap")]
        assert st.compressor.phase == "capped"
        st, _ = step(st, LockoutEnds(at=at(100) + LOCKOUT), s)
        assert st.compressor.phase == "capped"
        st, _ = step(st, LockoutEnds(at=at(180)), s)
        assert st.compressor.phase == "idle"
        st, acts = step(
            running(fresh(), s=s),
            RecoveryDone(at=at(10), tank=tank(140, 140)),
            s,
        )
        assert of(acts, StopCompressor) == [StopCompressor(at(10), "target")]
        assert st.compressor.phase == "locked_out"


# ── Reservation entries ───────────────────────────────────────


class TestEntries:
    def test_an_entry_sets_the_setpoint_then_the_mode(self) -> None:
        """The device fires an entry in its minute whatever runs,
        setting both its setpoint and its mode (the reservation spec;
        02:08:02 on 2026-09-20's reservation run): the setpoint first,
        so the new mode's rules judge it."""
        st, acts = step(
            fresh(),
            EntryFires(
                at=T0,
                tank=tank(135, 120),
                setpoint_f=130.0,
                mode="energy_saver",
                serves="e",
                ref=3,
            ),
        )
        assert acts[0] == EntryFired(3)
        kinds = [type(a) for a in acts]
        assert kinds.index(SetpointSet) < kinds.index(RecordModeWrite)
        assert of(acts, RecordModeWrite) == [
            RecordModeWrite(T0, "energy_saver", "plan", "e")
        ]
        assert of(acts, ModeSet) == [ModeSet(T0, "energy_saver", "write")]
        assert (st.setpoint_f, st.mode.in_force) == (130.0, "energy_saver")

    def test_an_entry_repeating_the_heaters_state_starts_nothing(self) -> None:
        """An entry repeating the heater's mode and setpoint started
        nothing, 0 of 4 (the reservation spec's device test
        ``unchanged_entry_starts_recovery``)."""
        st, acts = step(
            fresh(),
            EntryFires(
                at=T0,
                tank=tank(130, 120),
                setpoint_f=140.0,
                mode="heat_pump",
                ref=0,
            ),
        )
        assert acts == (EntryFired(0),)
        assert st.compressor.pending is None

    def test_an_entry_in_vacation_is_skipped(self) -> None:
        """In Vacation the device skips an entry as its minute passes and
        does not run it late (the reservation spec's device test
        ``entries_fire_in_vacation``)."""
        st, acts = step(
            fresh(),
            EntryFires(
                at=T0,
                tank=tank(130, 120),
                setpoint_f=130.0,
                mode="energy_saver",
                ref=2,
            ),
            settings(disabled=True),
        )
        assert acts == (EntrySkipped(2),)
        assert st.setpoint_f == 140.0

    def test_an_entry_turns_a_powered_off_heater_on(self) -> None:
        """Powered off, the device fires an entry and turns the heater
        on, in the entry's mode (two device runs, 2026-09-24): judged as
        a mode write out of power-off, which with the tank short starts
        the compressor."""
        st, acts = step(
            fresh(),
            EntryFires(
                at=T0,
                tank=tank(120, 100),
                setpoint_f=140.0,
                mode="heat_pump",
                ref=3,
            ),
            settings(powered_off=True),
        )
        assert acts[0] == EntryFired(3)
        assert Note(POWERED_ON_BY_ENTRY) in acts
        assert st.powered_on
        assert st.compressor.pending is not None

    def test_a_powered_off_heater_with_no_entry_stays_off(self) -> None:
        """With no entry, a powered-off heater starts nothing (six
        minutes, the same device test)."""
        s = settings(powered_off=True)
        assert controller.disabled(fresh(), s)
        assert not controller.disabled(replace(fresh(), powered_on=True), s)
        assert controller.disabled(
            replace(fresh(), powered_on=True), settings(disabled=True)
        )


# ── Mode writes ──────────────────────────────────────────


class TestModeWrites:
    def test_an_entrys_mode_in_a_window_is_held_to_its_close(self) -> None:
        """An entry's mode does not take inside a TOU window while its
        setpoint does (the reservation spec's
        ``entry_mode_in_tou_window: held`` and its device test of it; a
        device run at 02:15 UTC on 2026-09-20): held to the window's
        close. Its start is judged as a write in the window is: the upper
        zone here is 5 °F short."""
        s = settings(windows=[WINDOW])
        st, acts = step(
            fresh(),
            EntryFires(
                at=T0,
                tank=tank(135, 120),
                setpoint_f=140.0,
                mode="energy_saver",
                serves="e",
                ref=0,
            ),
            s,
        )
        assert of(acts, ModeHeld) == [ModeHeld(0)]
        assert st.mode.in_force == "heat_pump"
        assert st.mode.commanded == "energy_saver"
        assert st.mode.held is not None and st.mode.held.until == WINDOW[1]
        assert st.compressor.pending == Start(T0 + LAG, "write", serves="e")
        assert {
            "mode_write_held_projected",
            "mode_write_start_projected",
        } <= notes(acts)

    def test_a_held_heat_pump_entry_rests_on_the_specs_letter(self) -> None:
        """The reservation spec's device test measured an element
        mode's entry only; a ``heat_pump`` entry held in a window rests
        on the spec's letter, and says so."""
        s = settings(windows=[WINDOW])
        st, acts = step(
            fresh(mode="energy_saver"),
            EntryFires(
                at=T0,
                tank=tank(135, 120),
                setpoint_f=140.0,
                mode="heat_pump",
            ),
            s,
        )
        assert st.mode.held is not None
        assert "heat_pump_entry_held_spec_only" in notes(acts)

    def test_a_direct_element_mode_is_held_and_a_direct_heat_pump_takes(
        self,
    ) -> None:
        """Four in-window direct writes of Energy Saver did not take
        (device runs at 01:17, 01:26 and 02:15 UTC on 2026-09-20 and at
        23:24 UTC on 2026-09-21); five direct Electric to Heat Pump
        writes inside a window on 2026-04-16 each took at once."""
        s = settings(windows=[WINDOW])
        st, acts = step(
            fresh(),
            ModeWrite(
                at=T0, tank=tank(135, 120), mode="energy_saver", owner="raw"
            ),
            s,
        )
        assert of(acts, ModeHeld) == [ModeHeld(0)]
        assert st.mode.in_force == "heat_pump"
        st, acts = step(
            fresh(mode="electric"),
            ModeWrite(
                at=T0, tank=tank(141, 120), mode="heat_pump", owner="raw"
            ),
            s,
        )
        assert of(acts, ModeTook) == [ModeTook(0, T0)]
        assert st.mode.in_force == "heat_pump"

    def test_a_write_over_a_held_one_withdraws_it(self) -> None:
        """A mode write over a held one withdraws it (a device run at
        23:24 UTC on 2026-09-21)."""
        s = settings(windows=[WINDOW])
        st, _ = step(
            fresh(),
            ModeWrite(
                at=T0, tank=tank(135, 120), mode="energy_saver", owner="raw"
            ),
            s,
        )
        st, acts = step(
            st,
            ModeWrite(
                at=at(1), tank=tank(135, 120), mode="heat_pump", owner="raw"
            ),
            s,
        )
        assert of(acts, ModeWithdrawn) == [ModeWithdrawn(0, at(1))]
        assert st.mode.held is None
        assert st.mode.commanded == "heat_pump"

    @pytest.mark.parametrize("upper", [137.6, 167.5])
    def test_a_held_write_starts_only_as_a_window_write_would(
        self, upper: float
    ) -> None:
        """Two held Energy Saver writes, the upper zone 2.4 °F short and
        27.5 °F above the setpoint, started nothing for hours
        (2026-09-21 00:48 and 23:24 UTC)."""
        st, acts = step(
            fresh(),
            ModeWrite(
                at=T0, tank=tank(upper, 120), mode="energy_saver", owner="raw"
            ),
            settings(windows=[WINDOW]),
        )
        assert st.mode.held is not None
        assert st.compressor.pending is None
        assert "mode_write_start_projected" not in notes(acts)

    def test_a_landing_over_the_setpoint_starts_nothing(self) -> None:
        """Energy Saver landing at a window's close with the upper zone
        18.7 °F above a 107.6 °F setpoint and the lower 20.9 °F under
        it started nothing in 9 h 56 min (2026-09-21 04:00 UTC)."""
        s = settings(windows=[WINDOW])
        st, _ = step(
            fresh(setpoint=107.6),
            ModeWrite(
                at=T0, tank=tank(126.3, 86.7), mode="energy_saver", owner="raw"
            ),
            s,
        )
        st, acts = step(
            st, WindowCloses(at=WINDOW[1], tank=tank(126.3, 86.7)), s
        )
        assert st.mode.in_force == "energy_saver"
        assert st.compressor.pending is None
        assert of(acts, StartCompressor) == []

    def test_a_held_mode_lands_as_its_window_closes(self) -> None:
        """A held entry lands as its window ends (the reservation
        spec's device test saw its entry land as its window ended)."""
        s = settings(windows=[WINDOW])
        st, _ = step(
            fresh(),
            EntryFires(
                at=T0,
                tank=tank(139, 130),
                setpoint_f=140.0,
                mode="energy_saver",
                serves="e",
            ),
            s,
        )
        st, acts = step(st, WindowCloses(at=WINDOW[1], tank=tank(137, 128)), s)
        assert of(acts, ModeTook) == [ModeTook(0, WINDOW[1])]
        assert of(acts, ModeSet) == [
            ModeSet(WINDOW[1], "energy_saver", "write")
        ]
        assert st.mode.in_force == "energy_saver"
        assert st.mode.held is None

    def test_an_element_mode_is_dropped_at_a_windows_opening(self) -> None:
        """The heater dropped Energy Saver to the heat pump within
        11 s of TOU being switched on in-window (a device run at
        01:35 UTC on 2026-09-20),
        and the drop, 9.5 °F short, started the compressor 21-32 s
        later, judged as a write in a window is. At a window's start it
        is assumed to do the same."""
        s = settings(windows=[(T0, at(300))])
        st, acts = step(
            fresh(mode="energy_saver"),
            WindowOpens(at=T0, tank=tank(130.5, 125)),
            s,
        )
        assert of(acts, Dropped) == [Dropped(T0, "energy_saver")]
        assert of(acts, ModeSet) == [ModeSet(T0, "heat_pump", "dropped")]
        assert (st.mode.in_force, st.mode.commanded) == (
            "heat_pump",
            "heat_pump",
        )
        assert st.compressor.pending == Start(
            T0 + LAG, "heater", trigger="mode_dropped"
        )
        _, acts = step(fresh(), WindowOpens(at=T0, tank=tank(130, 125)), s)
        assert acts == ()

    @pytest.mark.parametrize(
        ("previous", "mode", "upper", "lower", "starts"),
        [
            # The lower zone 3.6 °F short: 19 of 19 out of an element
            # mode, whatever the upper zone; out of heat_pump with the
            # upper zone above the setpoint, 0 of 1 (2026-09-21).
            ("electric", "heat_pump", 141.0, 136.4, True),
            ("heat_pump", "energy_saver", 141.0, 136.4, False),
            ("heat_pump", "energy_saver", 139.8, 136.4, True),
            # Into heat_pump, the upper zone more than 2 °F short: 7 of
            # 7 out of Energy Saver; with neither, 1 of 10.
            ("energy_saver", "heat_pump", 137.9, 139.0, True),
            ("energy_saver", "heat_pump", 138.5, 139.0, False),
            # Into Energy Saver, the upper zone short at all: 7 of 7.
            ("heat_pump", "energy_saver", 139.0, 138.0, True),
            # Out of Electric into High Demand, whatever the tank: 4 of 4.
            ("electric", "high_demand", 141.0, 139.0, True),
            # Into Electric, never the compressor: 0 of 6.
            ("heat_pump", "electric", 130.0, 120.0, False),
        ],
    )
    def test_a_mode_taking_effect_starts_the_compressor_by_its_record(
        self,
        previous: HeaterMode,
        mode: HeaterMode,
        upper: float,
        lower: float,
        starts: bool,
    ) -> None:
        """The write rule for mode writes: 91 sustained mode writes on
        the device's record to 2026-09-25, by the mode left and the one
        named."""
        st, _ = step(
            fresh(mode=previous),
            ModeWrite(at=T0, tank=tank(upper, lower), mode=mode, owner="raw"),
        )
        assert (st.compressor.pending is not None) is starts

    def test_electric_ends_a_recovery(self) -> None:
        """Electric runs no heat pump (0 of 6): a write
        into it ends a running recovery, ``mode``, and drops a start a
        write set going."""
        st = running(fresh())
        st, acts = step(
            st,
            ModeWrite(
                at=at(1), tank=tank(130, 120), mode="electric", owner="raw"
            ),
        )
        assert of(acts, StopCompressor) == [StopCompressor(at(1), "mode")]
        assert st.compressor.pending is None

    def test_a_mode_write_in_vacation_takes_nothing(self) -> None:
        """Out of Vacation or power-off the heater starts afresh (38 of
        39 started), a rule the simulation does not hold: the write is
        recorded and takes nothing."""
        st, acts = step(
            fresh(),
            ModeWrite(
                at=T0,
                tank=tank(130, 120),
                mode="energy_saver",
                owner="raw",
                serves="w",
            ),
            settings(disabled=True),
        )
        assert acts == (RecordModeWrite(T0, "energy_saver", "raw", "w"),)
        assert st.mode.commanded == "heat_pump"

    def test_direct_writes_at_one_instant_apply_setpoints_first(self) -> None:
        """Direct writes at one instant apply every setpoint, then
        every mode, as an entry does; the device's own order there is
        unmeasured (no mode and setpoint write on the record share an
        instant; the three pairs 17-67 ms apart come in either order).
        A mode change among them leaves the elements to the new mode."""
        _, acts = step(
            fresh(),
            RawWrites(
                at=T0,
                tank=tank(130, 120),
                writes=(
                    Written(None, "energy_saver", "m"),
                    Written(130.0, None, "s"),
                ),
            ),
        )
        assert acts == (
            Then(
                SetpointWrite(
                    at=T0, setpoint_f=130.0, serves="s", mode_follows=True
                )
            ),
            Then(
                ModeWrite(at=T0, mode="energy_saver", owner="raw", serves="m")
            ),
        )


# ── The elements ──────────────────────────────────────────────


class TestTheElements:
    @pytest.mark.parametrize(
        ("mode", "on", "off"),
        [
            # A descending sweep: off at 1.44 °F, on at 1.80.
            ("energy_saver", 1.8, 1.44),
            # Device runs to 2026-09-21: off at 0.36, on at 0.72.
            ("high_demand", 0.72, 0.36),
        ],
    )
    def test_a_mode_starts_its_element_at_its_entry_deficit(
        self, mode: HeaterMode, on: float, off: float
    ) -> None:
        """On entry to an element mode the upper element starts
        when the upper zone is at least the mode's entry deficit short:
        Energy Saver 1.8 °F, High Demand 0.72, Electric 0.54, each
        bracketed on both sides by the 2026-09-20/21 device runs. Inside
        a bracket the projection says so."""
        st, acts = step(
            fresh(mode="heat_pump"),
            ModeWrite(
                at=T0, tank=tank(140.0 - on, 139.0), mode=mode, owner="raw"
            ),
        )
        assert of(acts, StartElement)[0].zone == "upper"
        assert st.element.running
        st, acts = step(
            fresh(mode="heat_pump"),
            ModeWrite(
                at=T0, tank=tank(140.0 - off, 139.0), mode=mode, owner="raw"
            ),
        )
        assert not of(acts, StartElement)
        _, acts = step(
            fresh(mode="heat_pump"),
            ModeWrite(
                at=T0,
                tank=tank(140.0 - (on + off) / 2, 139.0),
                mode=mode,
                owner="raw",
            ),
        )
        assert "deficit_inside_the_start_threshold_bracket" in notes(acts)

    def test_electric_runs_the_lower_element_when_the_upper_is_done(
        self,
    ) -> None:
        """Electric ran its element at 0.54 °F short (a device run on
        2026-09-20); with the upper zone at the setpoint, its lower
        element heats the lower zone."""
        _, acts = step(
            fresh(),
            ModeWrite(
                at=T0, tank=tank(139.46, 139.0), mode="electric", owner="raw"
            ),
        )
        assert [a.zone for a in of(acts, StartElement)] == ["upper"]
        _, acts = step(
            fresh(),
            ModeWrite(
                at=T0, tank=tank(140.0, 120.0), mode="electric", owner="raw"
            ),
        )
        assert [a.zone for a in of(acts, StartElement)] == ["lower"]

    def test_energy_savers_element_reengages_at_he_upper_on(self) -> None:
        """Energy Saver's element engages as the upper zone reaches
        ``he_upper_on``, an absolute 104.9 °F: a device run at 13:54 UTC
        on 2026-09-21 at a 107.6 °F setpoint engaged at 103.64,
        where a setpoint-relative rule said 71.6; 16 of 21 mid-stint
        starts lay between 103.6 and 104.7 °F."""
        _, acts = step(
            fresh(mode="energy_saver", setpoint=107.6),
            UpperRead(at=T0, tank=tank(103.64, 100.0)),
        )
        assert of(acts, StartElement)[0].start == Start(
            T0, "heater", trigger="energy_saver_upper_on", source="element"
        )
        _, acts = step(
            fresh(mode="energy_saver"),
            UpperRead(at=T0, tank=tank(105.5, 100.0)),
        )
        assert not of(acts, StartElement)
        _, acts = step(
            fresh(mode="heat_pump"), UpperRead(at=T0, tank=tank(103.0, 100.0))
        )
        assert not of(acts, StartElement)

    def test_a_coast_to_he_upper_on_starts_it_there(self) -> None:
        """The same rule met on a coast: where the upper zone falls
        through 104.9 °F the element starts (every engagement on record
        came with water moving through the tank)."""
        st = fresh(mode="energy_saver")
        points = [Point(T0, 106.0, 100.0), Point(at(10), 104.0, 99.0)]
        crossing = upper_on_crossing(st, settings(), points)
        assert crossing == at(5.5)
        _, acts = step(st, UpperOnCrossed(at=at(5.5), tank=tank(104.9, 99.5)))
        assert of(acts, StartElement)[0].start.trigger == (
            "energy_saver_upper_on"
        )

    def test_a_setpoint_raise_in_energy_saver_starts_the_element(self) -> None:
        """In Energy Saver a raise leaving the upper zone the entry
        deficit short started the element (n = 1, the 2026-09 heating
        modes study), unless a mode write at the instant changes the
        mode: its rules decide then."""
        _, acts = step(
            fresh(mode="energy_saver", setpoint=120.0),
            SetpointWrite(
                at=T0, tank=tank(125, 120), setpoint_f=130.0, serves="w"
            ),
        )
        assert of(acts, StartElement)[0].start == Start(
            T0, "write", serves="w", source="element"
        )
        assert "element_start_on_setpoint_raise_n1" in notes(acts)
        _, acts = step(
            fresh(mode="energy_saver", setpoint=120.0),
            SetpointWrite(
                at=T0, tank=tank(125, 120), setpoint_f=130.0, mode_follows=True
            ),
        )
        assert not of(acts, StartElement)

    def test_energy_savers_upper_element_stops_1_62_f_short(self) -> None:
        """Energy Saver's upper element switches off 1.62 °F short
        of the setpoint (n = 21 off-edges on 15 days, 2026-10-02) and
        the zone coasts on with the heat in transit; High Demand's stops
        at the setpoint (n = 10)."""
        st = element_on("energy_saver", upper=130.0)
        _, acts = step(st, ElementCheck(at=at(5), tank=tank(138.0, 120)))
        assert of(acts, ElementRetarget) == [ElementRetarget(140.0 - 1.62)]
        st, acts = step(st, ElementCheck(at=at(5), tank=tank(138.38, 120)))
        assert of(acts, StopElement) == [
            StopElement(at(5), "target", "ENERGY_SAVER")
        ]
        assert not st.element.running
        hd = element_on("high_demand", upper=130.0)
        _, acts = step(hd, ElementCheck(at=at(5), tank=tank(138.38, 120)))
        assert of(acts, ElementRetarget) == [ElementRetarget(140.0)]
        _, acts = step(hd, ElementCheck(at=at(5), tank=tank(139.96, 120)))
        assert of(acts, StopElement) == [StopElement(at(5), "target")]

    def test_electric_hands_the_upper_element_to_the_lower(self) -> None:
        """Electric runs its upper element, then its lower (nine
        lower-element runs)."""
        st = element_on("electric", upper=130.0)
        st, acts = step(st, ElementCheck(at=at(5), tank=tank(139.96, 120)))
        assert [type(a) for a in acts if not isinstance(a, Note)] == [
            StopElement,
            StartElement,
            ElementRetarget,
        ]
        assert of(acts, StartElement)[0].start.trigger == (
            "electric_lower_after_upper"
        )
        assert st.element.zone == "lower"

    def test_an_upper_element_waits_out_its_dead_time(self) -> None:
        """The upper zone does not move for 1.21 min after an upper
        element's on-edge (n = 29 on 21 days, 2026-10-02); one on at the
        walk's start has the rest of it left when its on-edge is known,
        and is past it when it is not."""
        st, acts = step(
            fresh(),
            ModeWrite(
                at=T0, tank=tank(138.0, 139.0), mode="energy_saver", owner="raw"
            ),
        )
        live = T0 + timedelta(minutes=EP.upper_dead_time_min)
        assert of(acts, StartElement)[0].live_at == live
        assert st.element.phase == "dead_time"
        st, _ = step(st, DeadTimeEnds(at=live))
        assert st.element.phase == "heating"
        known, acts = step(
            fresh(mode="energy_saver"),
            ElementWasOn(at=T0, tank=tank(130, 120), since=at(-0.5)),
        )
        assert of(acts, StartElement)[0].credited_min == pytest.approx(0.5)
        assert known.element.phase == "dead_time"
        unknown, _ = step(
            fresh(mode="energy_saver"), ElementWasOn(at=T0, tank=tank(130, 120))
        )
        assert unknown.element.phase == "heating"

    def test_a_setpoint_write_moves_the_elements_off_point(self) -> None:
        """An element's off setting follows the setpoint: a raise
        moves it, and a write bringing it to or below
        the zone ends the run, as at its own off point."""
        st = element_on("energy_saver", upper=130.0)
        _, acts = step(
            st, SetpointWrite(at=at(1), tank=tank(130, 120), setpoint_f=145.0)
        )
        assert of(acts, ElementRetarget) == [ElementRetarget(145.0 - 1.62)]
        _, acts = step(
            st, SetpointWrite(at=at(1), tank=tank(130, 120), setpoint_f=131.0)
        )
        assert of(acts, StopElement) == [
            StopElement(at(1), "write", "ENERGY_SAVER")
        ]

    def test_leaving_the_element_modes_stops_the_element(self) -> None:
        """In heat_pump no element runs: a mode write out of the
        element modes ends the run, ``mode``."""
        st = element_on("energy_saver", upper=130.0)
        st, acts = step(
            st,
            ModeWrite(
                at=at(1), tank=tank(131, 120), mode="heat_pump", owner="raw"
            ),
        )
        assert of(acts, StopElement) == [StopElement(at(1), "mode")]
        assert not st.element.running

    def test_an_element_on_at_the_start_runs_on(self) -> None:
        """An element on at the walk's start (the record's flags) runs
        on in an element mode: the upper while the upper zone is short,
        else the lower."""
        _, acts = step(
            fresh(mode="electric"), ElementWasOn(at=T0, tank=tank(130, 120))
        )
        assert of(acts, StartElement)[0].zone == "upper"
        _, acts = step(
            fresh(mode="electric"), ElementWasOn(at=T0, tank=tank(139.98, 120))
        )
        assert of(acts, StartElement)[0].zone == "lower"
        _, acts = step(fresh(), ElementWasOn(at=T0, tank=tank(130, 120)))
        assert acts == ()

    def test_later_starts_are_modelled_for_energy_saver_only(self) -> None:
        """Mid-stint re-engagement is measured for Energy
        Saver alone (16 of 21 starts just under 104.9 °F); High
        Demand's and Electric's later starts are not projected, and the
        projection says so."""
        _, acts = step(
            fresh(mode="high_demand"), Begins(at=T0, tank=tank(130, 120))
        )
        assert "element_later_starts_not_modelled" in notes(acts)
        _, acts = step(
            fresh(mode="energy_saver"), Begins(at=T0, tank=tank(130, 120))
        )
        assert "element_later_starts_not_modelled" not in notes(acts)


def test_the_controller_wakes_at_its_own_instants() -> None:
    """What the walk must stop at for the controller: a pending start,
    the dead time's end, a held mode's landing, and a window opening
    while an element mode is in force."""
    s = settings(windows=[WINDOW, (at(120), at(180))])
    st, _ = step(
        fresh(),
        EntryFires(
            at=T0,
            tank=tank(130.0, 129.0),
            setpoint_f=140.0,
            mode="energy_saver",
        ),
        s,
    )
    assert wake_times(st, s) == {T0 + LAG, WINDOW[1]}
    es, _ = step(
        fresh(),
        ModeWrite(
            at=T0, tank=tank(138.0, 139.0), mode="energy_saver", owner="raw"
        ),
    )
    live = T0 + timedelta(minutes=EP.upper_dead_time_min)
    assert wake_times(es, s) == {T0 + LAG, live, WINDOW[0], at(120)}


def test_a_transition_is_pure() -> None:
    """The same state and event give the same answer, and the state
    handed in is left as it was."""
    st = fresh()
    event = SetpointWrite(at=T0, tank=tank(128, 120), setpoint_f=145.0)
    first = step(st, event)
    assert step(st, event) == first
    assert st == fresh()
