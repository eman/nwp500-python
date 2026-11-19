"""A scenario takes reservation entries in the device's fields and every
command a plan carries (``sim.profile.COMMAND_KEYS``), walking those the
simulation models and naming the rest in ``reasons``."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from nwp500 import sim_adapters as sa
from nwp500.models import ReservationEntry as DeviceEntry
from nwp500.models import ReservationSchedule
from nwp500.mqtt.control import RESERVATION_ENTRY_FIELDS
from nwp500.sim import (
    AntiLegionellaCommand,
    Commands,
    DemandResponseCommand,
    Environment,
    HeaterState,
    History,
    PowerCommand,
    ReservationEntry,
    Scenario,
    Schedules,
    Settings,
    VacationCommand,
    carry_on,
    default_params,
    element_mode,
    next_recovery,
    simulate,
    time_to_ready,
)
from nwp500.sim.api import VACATION_RETURNS_EARLY
from nwp500.sim.codec import scenario_from_document, scenario_to_document
from nwp500.sim.inputs import DEVICE_ENTRY_FIELDS, POWER_OFF, VACATION
from nwp500.sim.params import HeaterParams
from nwp500.sim.profile import COMMAND_KEYS

T0 = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
EVERY_DAY = 254
#: An entry as the device reports it: weekdays at 05:30, High Demand at
#: 60 °C.
DEVICE = {
    "enable": 2,
    "week": 124,
    "hour": 5,
    "min": 30,
    "mode": 4,
    "param": 120,
}
SIM = ReservationEntry(
    enabled=True, week=124, hour=5, minute=30, mode=4, setpoint_half_c=120
)

#: Each plan command's model.
MODELS: dict[str, type[BaseModel]] = {
    "vacation": VacationCommand,
    "power": PowerCommand,
    "anti_legionella": AntiLegionellaCommand,
    "demand_response": DemandResponseCommand,
}


@pytest.fixture(scope="module")
def params() -> HeaterParams:
    return default_params()


def _scenario(**kw: Any) -> Scenario:
    """A tank whose lower zone is under the compressor's start: the
    heater heats at once unless something stops it."""
    base: dict[str, Any] = {
        "start": T0,
        "horizon": timedelta(hours=12),
        "tz": "UTC",
        "state": HeaterState(upper_f=110.0, lower_f=95.0),
        "settings": Settings(setpoint_f=140.9, hp_lower_on_f=105.0),
        "history": History(compressor_stopped_at=T0 - timedelta(hours=2)),
        "environment": Environment(ambient_f=68.0, humidity=48.0),
    }
    base.update(kw)
    return Scenario(**base)


def _with_mode(s: Scenario, mode: int) -> Scenario:
    return s.model_copy(
        update={"settings": s.settings.model_copy(update={"mode": mode})}
    )


class TestDeviceEntries:
    def test_the_mapping_is_the_device_s_six_fields(self) -> None:
        assert tuple(DEVICE_ENTRY_FIELDS) == RESERVATION_ENTRY_FIELDS
        assert set(DEVICE_ENTRY_FIELDS.values()) == set(
            ReservationEntry.model_fields
        )

    def test_a_device_entry_reads_as_the_simulator_s(self) -> None:
        assert ReservationEntry.model_validate(DEVICE) == SIM
        assert ReservationEntry.from_device(DEVICE) == SIM

    def test_to_device_gives_the_device_s_entry_back(self) -> None:
        assert SIM.to_device() == DEVICE
        off = SIM.model_copy(update={"enabled": False})
        assert off.to_device()["enable"] == 1
        assert ReservationEntry.from_device(off.to_device()) == off

    def test_the_library_s_entry_reads_as_the_simulator_s(self) -> None:
        core = DeviceEntry(**DEVICE)
        assert ReservationEntry.from_device(core) == SIM
        assert Commands(reservations=(core,)).reservations == (SIM,)  # type: ignore[arg-type]

    def test_enable_other_than_2_is_off(self) -> None:
        for enable in (0, 1):
            e = ReservationEntry.from_device({**DEVICE, "enable": enable})
            assert not e.enabled

    def test_a_boolean_enable_is_refused(self) -> None:
        """``True`` is 1, which the device reads as off."""
        with pytest.raises(ValidationError, match="enable"):
            ReservationEntry.model_validate({**DEVICE, "enable": True})

    def test_a_device_entry_needs_all_six_fields(self) -> None:
        partial = {k: v for k, v in DEVICE.items() if k != "min"}
        with pytest.raises(ValidationError, match="missing min"):
            ReservationEntry.model_validate(partial)
        with pytest.raises(ValueError, match="missing enable"):
            ReservationEntry.from_device(SIM.model_dump())

    def test_the_two_forms_do_not_mix(self) -> None:
        with pytest.raises(ValidationError, match="not both"):
            ReservationEntry.model_validate({**DEVICE, "minute": 30})

    def test_the_adapters_read_through_the_same_mapping(self) -> None:
        schedule = ReservationSchedule.model_validate(
            {"reservationUse": 2, "reservation": [DEVICE]}
        )
        assert sa.reservation_entries(schedule) == (SIM,)
        assert sa.schedules(reservations=schedule).reservations == (SIM,)

    def test_a_scenario_document_takes_device_entries(self) -> None:
        doc = scenario_to_document(_scenario())
        doc["scenario"]["commands"] = {"reservations": [DEVICE]}
        doc["scenario"]["schedules"] = {"reservations": [DEVICE]}
        s, _ = scenario_from_document(doc)
        assert s.commands.reservations == (SIM,)
        assert s.schedules.reservations == (SIM,)

    def test_device_entries_walk_as_the_simulator_s(
        self, params: HeaterParams
    ) -> None:
        entry = {**DEVICE, "week": EVERY_DAY, "hour": 21, "mode": 3}
        device = _scenario(commands=Commands(reservations=(entry,)))  # type: ignore[arg-type]
        own = _scenario(
            commands=Commands(
                reservations=(ReservationEntry.from_device(entry),)
            )
        )
        got = simulate(device, params)
        assert got.simulation == simulate(own, params).simulation
        assert got.simulation != simulate(_scenario(), params).simulation


class TestCommandShapes:
    """Each command takes the keys ``COMMAND_KEYS`` gives it."""

    def test_every_plan_command_is_a_field(self) -> None:
        fields = set(Commands.model_fields)
        for name in COMMAND_KEYS:
            assert name in fields or name == "tou"
        for name, model in MODELS.items():
            assert set(model.model_fields) == set(COMMAND_KEYS[name])

    def test_a_plan_s_commands_are_taken_whole(self) -> None:
        c = Commands.model_validate(
            {
                "vacation": {"days": 3},
                "power": {"on": False},
                "anti_legionella": {"enabled": True, "period_days": 7},
                "tou": {"enabled": True},
                "demand_response": {"enabled": False},
            }
        )
        assert c.vacation == VacationCommand(days=3)
        assert c.power == PowerCommand(on=False)
        assert c.anti_legionella == AntiLegionellaCommand(
            enabled=True, period_days=7
        )
        assert c.tou_enabled is True
        assert c.demand_response == DemandResponseCommand(enabled=False)

    def test_tou_or_tou_enabled_not_both(self) -> None:
        with pytest.raises(ValidationError, match="not both"):
            Commands.model_validate(
                {"tou": {"enabled": True}, "tou_enabled": False}
            )
        # A document laid over a scenario carries an unset switch.
        c = Commands.model_validate(
            {"tou": {"enabled": False}, "tou_enabled": None}
        )
        assert c.tou_enabled is False

    @pytest.mark.parametrize(
        "tou", [True, {"enabled": 1}, {"enabled": True, "x": 1}, {}]
    )
    def test_a_bad_tou_is_refused(self, tou: object) -> None:
        with pytest.raises(ValidationError, match="tou"):
            Commands.model_validate({"tou": tou})

    @pytest.mark.parametrize(
        "command",
        [
            {"vacation": {"days": 0}},
            {"vacation": {"days": 100}},
            {"vacation": {"days": True}},
            {"vacation": {"days": 2.0}},
            {"power": {"on": 1}},
            {"power": {}},
            {"anti_legionella": {"enabled": True, "period_days": 31}},
            {"anti_legionella": {"enabled": False, "period_days": 7}},
            {"demand_response": {"enabled": "yes"}},
            {"demand_response": {"enabled": True, "level": 1}},
        ],
    )
    def test_a_value_out_of_its_type_or_range_is_refused(
        self, command: dict[str, Any]
    ) -> None:
        with pytest.raises(ValidationError):
            Commands.model_validate(command)

    def test_anti_legionella_on_needs_no_period(self) -> None:
        assert AntiLegionellaCommand(enabled=True).period_days is None


class TestPower:
    def test_off_walks_as_powered_off(self, params: HeaterParams) -> None:
        s = _scenario(commands=Commands(power=PowerCommand(on=False)))
        got = simulate(s, params)
        off = simulate(_with_mode(_scenario(), POWER_OFF), params)
        assert got.simulation == off.simulation
        assert simulate(_scenario(), params).heating
        assert not got.heating
        assert got.end_settings is not None
        assert got.end_settings.mode == POWER_OFF
        assert not [r for r in got.reasons if r.endswith("_not_modelled")]

    def test_an_entry_turns_a_heater_powered_off_on(
        self, params: HeaterParams
    ) -> None:
        entry = ReservationEntry(
            week=EVERY_DAY, hour=20, minute=0, mode=1, setpoint_half_c=124
        )
        s = _scenario(
            commands=Commands(power=PowerCommand(on=False)),
            schedules=Schedules(reservations=(entry,)),
        )
        got = simulate(s, params)
        assert got.heating
        assert got.heating[0].start.at >= T0.replace(hour=20)
        assert "powered_on_by_entry" in got.reasons

    def test_on_is_no_change_on_a_heater_that_is_on(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(commands=Commands(power=PowerCommand(on=True)))
        got = simulate(s, params)
        base = simulate(_scenario(), params)
        assert got.simulation == base.simulation
        assert got.reasons == base.reasons

    def test_on_is_not_modelled_on_a_heater_powered_off(
        self, params: HeaterParams
    ) -> None:
        """Back on, it runs the mode it had, which the scenario does not
        hold."""
        off = _with_mode(_scenario(), POWER_OFF)
        s = off.model_copy(
            update={"commands": Commands(power=PowerCommand(on=True))}
        )
        got = simulate(s, params)
        assert "power_not_modelled" in got.reasons
        assert got.simulation == simulate(off, params).simulation

    def test_next_recovery_and_element_mode_see_it_off(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(commands=Commands(power=PowerCommand(on=False)))
        assert next_recovery(s, params).outcome == "not_scheduled"
        stint = element_mode(s, params, mode=4)
        assert stint.unreachable_reason == "heating_disabled"


class TestVacation:
    def test_a_vacation_over_the_span_walks_as_vacation(
        self, params: HeaterParams
    ) -> None:
        s = _scenario(commands=Commands(vacation=VacationCommand(days=2)))
        got = simulate(s, params)
        vacation = simulate(_with_mode(_scenario(), VACATION), params)
        assert got.simulation == vacation.simulation
        assert not got.heating
        assert got.end_settings is not None
        assert got.end_settings.mode == VACATION
        assert "vacation_not_modelled" not in got.reasons

    def test_it_lasts_its_days_less_nine_hours(
        self, params: HeaterParams
    ) -> None:
        """The heater returns to its mode 9 h before the days are up (the
        user's manual, 3.4.5): a span ending there is all vacation."""
        assert timedelta(hours=9) == VACATION_RETURNS_EARLY
        last = timedelta(days=1) - VACATION_RETURNS_EARLY
        command = Commands(vacation=VacationCommand(days=1))
        inside = simulate(_scenario(horizon=last, commands=command), params)
        assert "vacation_not_modelled" not in inside.reasons
        assert not inside.heating

    def test_a_return_inside_the_span_is_not_modelled(
        self, params: HeaterParams
    ) -> None:
        """The walk holds no rule for leaving Vacation, so the command is
        left out whole."""
        span = timedelta(days=1) - VACATION_RETURNS_EARLY + timedelta(minutes=1)
        s = _scenario(
            horizon=span, commands=Commands(vacation=VacationCommand(days=1))
        )
        got = simulate(s, params)
        assert "vacation_not_modelled" in got.reasons
        base = simulate(_scenario(horizon=span), params)
        assert got.simulation == base.simulation

    def test_on_a_heater_powered_off_it_is_not_modelled(
        self, params: HeaterParams
    ) -> None:
        off = _with_mode(_scenario(), POWER_OFF)
        s = off.model_copy(
            update={"commands": Commands(vacation=VacationCommand(days=5))}
        )
        got = simulate(s, params)
        assert "vacation_not_modelled" in got.reasons
        assert got.end_settings is not None
        assert got.end_settings.mode == POWER_OFF

    def test_power_off_after_it_leaves_the_heater_off(
        self, params: HeaterParams
    ) -> None:
        """Taken in the order a plan serves them: vacation, then power."""
        s = _scenario(
            commands=Commands(
                vacation=VacationCommand(days=5), power=PowerCommand(on=False)
            )
        )
        got = simulate(s, params)
        assert got.end_settings is not None
        assert got.end_settings.mode == POWER_OFF
        assert not [r for r in got.reasons if r.endswith("_not_modelled")]

    def test_power_on_after_it_is_no_change(self, params: HeaterParams) -> None:
        s = _scenario(
            commands=Commands(
                vacation=VacationCommand(days=5), power=PowerCommand(on=True)
            )
        )
        got = simulate(s, params)
        assert got.end_settings is not None
        assert got.end_settings.mode == VACATION
        assert "power_not_modelled" not in got.reasons


class TestCyclesAndUtilityEvents:
    @pytest.mark.parametrize(
        ("name", "on"),
        [
            ("anti_legionella", AntiLegionellaCommand(enabled=True)),
            ("demand_response", DemandResponseCommand(enabled=True)),
        ],
    )
    def test_on_is_not_modelled(
        self, params: HeaterParams, name: str, on: BaseModel
    ) -> None:
        got = simulate(
            _scenario(commands=Commands.model_validate({name: on})), params
        )
        assert f"{name}_not_modelled" in got.reasons
        assert got.simulation == simulate(_scenario(), params).simulation

    @pytest.mark.parametrize(
        ("name", "off"),
        [
            ("anti_legionella", AntiLegionellaCommand(enabled=False)),
            ("demand_response", DemandResponseCommand(enabled=False)),
        ],
    )
    def test_off_is_the_walk_as_it_runs(
        self, params: HeaterParams, name: str, off: BaseModel
    ) -> None:
        got = simulate(
            _scenario(commands=Commands.model_validate({name: off})), params
        )
        base = simulate(_scenario(), params)
        assert got.simulation == base.simulation
        assert got.reasons == base.reasons


def _running(**kw: Any) -> Scenario:
    """The compressor running at the start, warm above its lower
    trigger."""
    return _scenario(
        state=HeaterState(upper_f=110.0, lower_f=95.0, compressor_running=True),
        **kw,
    )


class TestAStartWithHeatingDisabledStopsIt:
    """Vacation or Power Off at the start, by the settings or a command,
    stops what is running there: the compressor's stop is the start."""

    ENTRY = ReservationEntry(
        week=EVERY_DAY, hour=19, minute=2, mode=1, setpoint_half_c=124
    )

    @pytest.mark.parametrize(
        "command",
        [
            Commands(power=PowerCommand(on=False)),
            Commands(vacation=VacationCommand(days=2)),
        ],
    )
    def test_the_stop_is_the_start(
        self, params: HeaterParams, command: Commands
    ) -> None:
        got = simulate(_running(commands=command), params)
        assert got.end_history is not None
        assert got.end_history.compressor_stopped_at == T0
        assert not got.heating
        assert not got.simulation.points[0].heating

    def test_an_entry_soon_after_waits_out_the_lockout(
        self, params: HeaterParams
    ) -> None:
        """Powered off with the compressor running, an entry 2 minutes
        later turns the heater on; the compressor restarts no sooner
        than the restart lockout from the start allows."""
        s = _running(
            commands=Commands(power=PowerCommand(on=False)),
            schedules=Schedules(reservations=(self.ENTRY,)),
        )
        got = simulate(s, params)
        assert got.heating
        lockout = params.controller.restart_lockout
        assert got.heating[0].start.at >= T0 + lockout

    def test_the_command_walks_as_the_settings_do(
        self, params: HeaterParams
    ) -> None:
        schedules = Schedules(reservations=(self.ENTRY,))
        command = _running(
            commands=Commands(power=PowerCommand(on=False)),
            schedules=schedules,
        )
        settings = _with_mode(_running(schedules=schedules), POWER_OFF)
        got = simulate(command, params)
        assert got.simulation == simulate(settings, params).simulation
        assert got.end_history == simulate(settings, params).end_history

    def test_the_probes_keep_their_warmth_over_the_water(
        self, params: HeaterParams
    ) -> None:
        """Read while the compressor ran, the probes read warm over the
        water: the tank at the start is the water's, as for a run."""
        du, dl = params.compressor.running_probes_warm_f
        off = simulate(
            _running(commands=Commands(power=PowerCommand(on=False))), params
        )
        first = off.simulation.points[0]
        assert first.upper_f == pytest.approx(110.0 - du)
        assert first.lower_f == pytest.approx(95.0 - dl)

    def test_a_running_resume_dropped_stops_at_the_start(
        self, params: HeaterParams
    ) -> None:
        walk = simulate(_scenario(horizon=timedelta(minutes=30)), params)
        assert walk.end_state is not None
        assert walk.end_state.compressor_running
        assert walk.end_history is not None
        assert walk.end_settings is not None
        on = _scenario(
            start=walk.until,
            state=walk.end_state,
            history=walk.end_history,
            settings=walk.end_settings,
            commands=Commands(power=PowerCommand(on=False)),
        )
        got = simulate(on, params)
        assert "resume_dropped_heating_disabled_changed" in got.reasons
        assert got.end_history is not None
        assert got.end_history.compressor_stopped_at == walk.until
        assert not got.heating


class TestEveryWalkJudgesTheCommandsAlike:
    """An answer that walks a scenario over spans of different lengths
    judges its commands over the farthest: a one-day vacation returns
    15 hours in, inside a 24-hour look ahead though not a 12-hour
    scenario."""

    ONE_DAY = Commands(vacation=VacationCommand(days=1))

    def test_element_mode(self, params: HeaterParams) -> None:
        away = element_mode(_scenario(commands=self.ONE_DAY), params, mode=4)
        home = element_mode(_scenario(), params, mode=4)
        assert "vacation_not_modelled" in away.reasons
        # Left out of the reachability test too.
        assert away.unreachable_reason != "heating_disabled"
        assert replace(away, reasons=home.reasons) == home

    def test_element_mode_over_a_vacation_it_covers(
        self, params: HeaterParams
    ) -> None:
        away = element_mode(
            _scenario(commands=Commands(vacation=VacationCommand(days=2))),
            params,
            mode=4,
        )
        assert not away.reachable
        assert away.unreachable_reason == "heating_disabled"
        assert "vacation_not_modelled" not in away.reasons

    def test_next_recovery(self, params: HeaterParams) -> None:
        away = next_recovery(_scenario(commands=self.ONE_DAY), params)
        assert away.reasons == ("vacation_not_modelled",)
        assert replace(away, reasons=()) == next_recovery(_scenario(), params)
        assert away.outcome != "not_scheduled"
        two = Commands(vacation=VacationCommand(days=2))
        assert next_recovery(_scenario(commands=two), params).outcome == (
            "not_scheduled"
        )

    def test_time_to_ready(self, params: HeaterParams) -> None:
        away = time_to_ready(_scenario(commands=self.ONE_DAY), params)
        home = time_to_ready(_scenario(), params)
        assert "vacation_not_modelled" in away.reasons
        assert away.bath == home.bath
        assert replace(away.recovery, reasons=()) == home.recovery

    def test_carry_on_does_not_go_on_past_the_return(
        self, params: HeaterParams
    ) -> None:
        """A tail inside the vacation walks it; walked on past the
        return, which no walk follows, it is not shown going on
        alike."""
        walk = simulate(_scenario(), params)
        tail = _scenario(
            start=walk.until,
            horizon=timedelta(days=1)
            - VACATION_RETURNS_EARLY
            - timedelta(seconds=30),
            commands=self.ONE_DAY,
        )
        [c] = carry_on([walk], tail, params)
        assert "vacation_not_modelled" not in c.tail.reasons
        assert not c.tail.heating
        assert not c.heating_alike


class TestEveryAnswerNamesTheCommandsLeftOut:
    """An answer from a scenario names each command it leaves out,
    whether or not it walks a mode."""

    LEFT_OUT = Commands(
        anti_legionella=AntiLegionellaCommand(enabled=True),
        demand_response=DemandResponseCommand(enabled=True),
    )
    NAMED = ("anti_legionella_not_modelled", "demand_response_not_modelled")

    @staticmethod
    def _off_turned_on() -> Scenario:
        """Powered off, told to turn on: back on, it runs the mode it
        had, which the scenario does not hold."""
        return _with_mode(
            _scenario(commands=Commands(power=PowerCommand(on=True))),
            POWER_OFF,
        )

    @staticmethod
    def _hot(**kw: Any) -> Scenario:
        """A tank ready for a bath now: no mode is walked."""
        return _scenario(state=HeaterState(upper_f=140.0, lower_f=138.0), **kw)

    def test_time_to_ready_with_heating_disabled(
        self, params: HeaterParams
    ) -> None:
        got = time_to_ready(self._off_turned_on(), params)
        assert got.recovery.outcome == "not_scheduled"
        assert "power_not_modelled" in got.reasons
        assert "power_not_modelled" in got.recovery.reasons

    def test_time_to_ready_with_the_bath_ready_now(
        self, params: HeaterParams
    ) -> None:
        got = time_to_ready(self._hot(commands=self.LEFT_OUT), params)
        assert got.bath.ready
        assert set(self.NAMED) <= set(got.reasons)

    def test_next_recovery_whatever_its_outcome(
        self, params: HeaterParams
    ) -> None:
        off = next_recovery(self._off_turned_on(), params)
        assert off.outcome == "not_scheduled"
        assert off.reasons == ("power_not_modelled",)
        on = next_recovery(_scenario(commands=self.LEFT_OUT), params)
        assert on.outcome == "ok"
        assert on.reasons == self.NAMED
        assert next_recovery(_scenario(), params).reasons == ()

    def test_element_mode_with_heating_disabled(
        self, params: HeaterParams
    ) -> None:
        got = element_mode(self._off_turned_on(), params, mode=4)
        assert got.unreachable_reason == "heating_disabled"
        assert "power_not_modelled" in got.reasons

    def test_carry_on(self, params: HeaterParams) -> None:
        walk = simulate(_scenario(), params)
        tail = _scenario(start=walk.until, commands=self.LEFT_OUT)
        [c] = carry_on([walk], tail, params)
        assert set(self.NAMED) <= set(c.tail.reasons)
