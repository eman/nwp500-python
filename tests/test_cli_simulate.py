"""``nwp-cli simulate``: composing live, scenario and flag inputs, the
snapshot round trip, and the output."""

import csv
import io
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

try:
    from click.testing import CliRunner

    from nwp500.cli import __main__ as cli_main
    from nwp500.cli import simulate as sim_cli
except ImportError:
    pytest.skip("CLI dependencies not installed", allow_module_level=True)

from nwp500 import sim, sim_live
from nwp500.sim.codec import scenario_to_document
from nwp500.sim.engine import SimulationError
from nwp500.sim.params import params_to_document
from nwp500.unit_system import reset_unit_system, set_unit_system

NOW = datetime(2026, 10, 18, 14, tzinfo=UTC)
TZ = "America/Los_Angeles"


@pytest.fixture(autouse=True)
def _units() -> Iterator[None]:
    yield
    reset_unit_system()


def _scenario(**update: Any) -> sim.Scenario:
    base = sim.Scenario(
        start=NOW,
        horizon=timedelta(hours=12),
        tz=TZ,
        state=sim.HeaterState(upper_f=118.0, lower_f=95.0),
        settings=sim.Settings(
            setpoint_f=130.0,
            hp_lower_on_f=110.0,
            hp_lower_off_f=125.0,
            hp_upper_on_f=124.0,
        ),
        environment=sim.Environment(ambient_f=62.0),
        loads=sim.Loads(
            windows=(
                sim.DrawWindow(
                    start=NOW + timedelta(hours=11),
                    end=NOW + timedelta(hours=11, minutes=15),
                    expected_gal=20.0,
                ),
            )
        ),
    )
    return base.model_copy(update=update)


def _live(**update: Any) -> sim_live.Composed:
    """What the live sources would compose: the device's heater (65
    gal), its schedules, its own air."""
    scenario = sim.Scenario(
        start=NOW,
        horizon=timedelta(hours=24),
        tz=TZ,
        state=sim.HeaterState(upper_f=134.0, lower_f=133.0),
        settings=sim.Settings(setpoint_f=140.0, hp_lower_on_f=105.0),
        schedules=sim.Schedules(tou_enabled=True),
        environment=sim.Environment(ambient_f=74.0),
    ).model_copy(update=update)
    reading = sim_live.HeaterReading(
        state=scenario.state,
        settings=scenario.settings,
        environment=scenario.environment,
        params=sim.default_params(2),
        status=None,  # type: ignore[arg-type]
        feature=None,
    )
    return sim_live.Composed(scenario, sim.default_params(2), reading)


def _doc(scenario: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "scenario": scenario, **extra}


class TestMerge:
    def test_objects_merge_and_other_values_replace(self) -> None:
        base = {"a": {"x": 1, "y": 2}, "b": [1, 2], "c": 1}
        over = {"a": {"y": 3}, "b": [9], "d": 4}
        assert sim_cli.merge(base, over) == {
            "a": {"x": 1, "y": 3},
            "b": [9],
            "c": 1,
            "d": 4,
        }
        assert base["a"] == {"x": 1, "y": 2}


class TestInputs:
    def test_ambient_and_environment_are_exclusive(self) -> None:
        with pytest.raises(sim_cli.InputError, match="not both"):
            sim_cli.Inputs(ambient=60.0, environment={"ambient_f": 60.0})

    def test_a_start_needs_its_offset(self) -> None:
        with pytest.raises(sim_cli.InputError, match="offset"):
            sim_cli.Inputs(start=datetime(2026, 10, 18, 7))  # noqa: DTZ001

    def test_a_scenario_of_another_version_is_refused(self) -> None:
        with pytest.raises(sim_cli.InputError, match="schema_version"):
            sim_cli.Inputs(scenario={"schema_version": 2, "scenario": {}})

    def test_the_device_is_read_without_a_scenario_or_with_live(self) -> None:
        assert sim_cli.Inputs().needs_device
        assert not sim_cli.Inputs(scenario=_doc({})).needs_device
        assert sim_cli.Inputs(scenario=_doc({}), live=True).needs_device

    def test_the_zone_is_the_flag_then_the_scenario_then_the_machine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sim_cli, "local_zone", lambda: "Europe/Berlin")
        doc = _doc({"tz": "America/Denver"})
        assert sim_cli.Inputs(tz="UTC", scenario=doc).zone() == "UTC"
        assert sim_cli.Inputs(scenario=doc).zone() == "America/Denver"
        assert sim_cli.Inputs().zone() == "Europe/Berlin"
        monkeypatch.setattr(sim_cli, "local_zone", lambda: None)
        with pytest.raises(sim_cli.InputError, match="--tz"):
            sim_cli.Inputs().zone()


class TestBadInputs:
    @pytest.mark.parametrize("text", ["null", "[1]", "3"])
    def test_a_document_is_an_object(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / "doc.json"
        path.write_text(text)
        with pytest.raises(sim_cli.InputError, match="not a JSON object"):
            sim_cli.read_document(path, "scenario")

    def test_an_unknown_zone_flag(self) -> None:
        with pytest.raises(sim_cli.InputError, match="unknown time zone"):
            sim_cli.Inputs(tz="Mars/Base")

    def test_an_unknown_zone_in_the_scenario(self) -> None:
        doc = scenario_to_document(_scenario())
        doc["scenario"]["tz"] = "Mars/Base"
        inputs = sim_cli.Inputs(scenario=doc)
        with pytest.raises(sim_cli.InputError, match="unknown time zone"):
            inputs.zone()
        with pytest.raises(sim_cli.InputError, match="unknown time zone"):
            sim_cli.build(inputs, None, NOW)

    def test_a_good_zone_flag_wins_over_a_bad_one_in_the_scenario(self) -> None:
        doc = scenario_to_document(_scenario())
        doc["scenario"]["tz"] = "Mars/Base"
        built = sim_cli.build(sim_cli.Inputs(scenario=doc, tz="UTC"), None, NOW)
        assert built.scenario.tz == "UTC"

    def test_parameters_that_are_not_a_document(self) -> None:
        doc = scenario_to_document(_scenario())
        with pytest.raises(sim_cli.InputError, match="--params"):
            sim_cli.build(sim_cli.Inputs(scenario=doc, params={}), None, NOW)
        with pytest.raises(sim_cli.InputError, match="--params"):
            sim_cli.build(sim_cli.Inputs(scenario=doc, params=[]), None, NOW)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        with pytest.raises(sim_cli.InputError, match="scenario's params"):
            sim_cli.build(
                sim_cli.Inputs(scenario={**doc, "params": {}}), None, NOW
            )

    def test_a_scenario_the_simulator_refuses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*_: Any, **__: Any) -> Any:
            raise SimulationError("no fitted draw response")

        monkeypatch.setattr(sim, "simulate", refuse)
        with pytest.raises(sim_cli.InputError, match="cannot be simulated"):
            sim_cli.run(
                sim_cli.Inputs(scenario=scenario_to_document(_scenario())),
                None,
                NOW,
                "json",
                io.StringIO(),
            )


class TestPrecedence:
    def test_live_alone(self) -> None:
        live = _live()
        built = sim_cli.build(sim_cli.Inputs(), live, NOW)
        assert built.scenario == live.scenario
        assert built.params == sim.default_params(2)
        assert built.notes == ()

    def test_a_scenario_alone_reads_nothing_live(self) -> None:
        s = _scenario()
        built = sim_cli.build(
            sim_cli.Inputs(scenario=scenario_to_document(s)), None, NOW
        )
        assert built.scenario == s
        assert built.params == sim.default_params()
        assert "65 gal defaults (give --params)" in built.notes[0]

    def test_a_scenario_laid_on_live_wins_where_it_speaks(self) -> None:
        overlay = _doc({"settings": {"setpoint_f": 120.0}, "horizon": "PT6H"})
        live = _live()
        built = sim_cli.build(
            sim_cli.Inputs(scenario=overlay, live=True), live, NOW
        )
        s = built.scenario
        assert s.settings.setpoint_f == 120.0
        # the rest of the settings, and every other part, are the device's
        assert s.settings.hp_lower_on_f == 105.0
        assert s.horizon == timedelta(hours=6)
        assert s.state == live.scenario.state
        assert s.schedules == live.scenario.schedules
        assert s.environment == live.scenario.environment

    def test_flags_win_over_the_scenario(self) -> None:
        s = _scenario()
        start = NOW + timedelta(hours=1)
        built = sim_cli.build(
            sim_cli.Inputs(
                scenario=scenario_to_document(s),
                hours=3.0,
                start=start,
                tz="UTC",
                ambient=50.0,
                inlet=55.0,
                loads={"draws": [{"at": start.isoformat(), "gallons": 5.0}]},
                commands={"tou_enabled": True},
            ),
            None,
            NOW,
        )
        b = built.scenario
        assert (b.start, b.horizon, b.tz) == (start, timedelta(hours=3), "UTC")
        assert (b.environment.ambient_f, b.environment.inlet_f) == (50.0, 55.0)
        assert b.loads == sim.Loads(draws=(sim.Draw(at=start, gallons=5.0),))
        assert b.commands == sim.Commands(tou_enabled=True)
        assert b.state == s.state

    def test_flags_win_over_live(self) -> None:
        built = sim_cli.build(
            sim_cli.Inputs(environment={"ambient_f": 40.0, "humidity": 30.0}),
            _live(),
            NOW,
        )
        assert built.scenario.environment == sim.Environment(
            ambient_f=40.0, humidity=30.0
        )

    def test_the_air_and_inlet_flags_are_in_the_preferred_unit(self) -> None:
        set_unit_system("metric")
        built = sim_cli.build(
            sim_cli.Inputs(ambient=10.0, inlet=15.0), _live(), NOW
        )
        assert built.scenario.environment.ambient_f == pytest.approx(50.0)
        assert built.scenario.environment.inlet_f == pytest.approx(59.0)

    def test_without_a_start_or_horizon_now_and_a_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sim_cli, "local_zone", lambda: TZ)
        doc = scenario_to_document(_scenario())
        for key in ("start", "horizon", "tz"):
            del doc["scenario"][key]
        b = sim_cli.build(sim_cli.Inputs(scenario=doc), None, NOW).scenario
        assert (b.start, b.horizon, b.tz) == (NOW, timedelta(hours=24), TZ)

    def test_the_parameters_flag_then_the_document_then_the_device(
        self,
    ) -> None:
        p80, p50 = sim.default_params(3), sim.default_params(1)
        doc = scenario_to_document(_scenario(), p50)
        live = _live()
        both = sim_cli.Inputs(
            scenario=doc, live=True, params=params_to_document(p80)
        )
        assert sim_cli.build(both, live, NOW).params == p80
        assert (
            sim_cli.build(
                sim_cli.Inputs(scenario=doc, live=True), live, NOW
            ).params
            == p50
        )
        assert sim_cli.build(sim_cli.Inputs(), live, NOW).params == (
            sim.default_params(2)
        )

    def test_an_incomplete_scenario_is_an_input_error(self) -> None:
        with pytest.raises(sim_cli.InputError, match="do not make a scenario"):
            sim_cli.build(sim_cli.Inputs(scenario=_doc({"tz": TZ})), None, NOW)


class TestSnapshot:
    def test_a_snapshot_replays_as_the_live_run(self) -> None:
        live = _live()
        text = json.dumps(sim_cli.snapshot_document(live))
        replayed = sim_cli.build(
            sim_cli.Inputs(scenario=json.loads(text)), None, NOW
        )
        direct = sim_cli.build(sim_cli.Inputs(), live, NOW)
        assert replayed.scenario == direct.scenario
        assert replayed.params == direct.params
        assert sim.simulate(replayed.scenario, replayed.params) == sim.simulate(
            direct.scenario, direct.params
        )


class TestOutput:
    def _run(self, fmt: str) -> str:
        out = io.StringIO()
        sim_cli.run(
            sim_cli.Inputs(scenario=scenario_to_document(_scenario())),
            None,
            NOW,
            fmt,
            out,
        )
        return out.getvalue()

    def test_json_is_the_result_document(self) -> None:
        doc = json.loads(self._run("json"))
        assert doc["schema_version"] == 1
        assert doc["heating"]
        assert doc["windows"]

    def test_csv_is_the_path(self) -> None:
        rows = list(csv.reader(io.StringIO(self._run("csv"))))
        assert rows[0] == [
            "at",
            "upper_f",
            "lower_f",
            "setpoint_f",
            "delivery_f",
            "heating",
            "compressor_wh",
            "element_wh",
            "mode",
        ]
        assert rows[1][:4] == [NOW.isoformat(), "118.0", "95.0", "130.0"]

    def test_csv_in_celsius_says_so(self) -> None:
        set_unit_system("metric")
        header = self._run("csv").splitlines()[0]
        assert header.startswith("at,upper_c,lower_c,setpoint_c,delivery_c")

    def test_the_table(self) -> None:
        text = self._run("table")
        assert "Heating" in text
        assert "compressor" in text
        assert "Draw windows" in text
        assert "Defaults used" in text


class TestTheCommand:
    def _write(self, tmp_path: Path, name: str, doc: Any) -> str:
        path = tmp_path / name
        path.write_text(json.dumps(doc))
        return str(path)

    def test_a_scenario_run_never_touches_the_device(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def no_device(*_: Any) -> int:
            raise AssertionError("connected")

        monkeypatch.setattr(cli_main, "_with_device", no_device)
        scenario = self._write(
            tmp_path, "s.json", scenario_to_document(_scenario())
        )
        result = CliRunner().invoke(
            cli_main.cli,
            ["simulate", "run", "--scenario", scenario, "--format", "json"],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["schema_version"] == 1

    def test_live_runs_connect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[Any] = []

        async def device(ctx: Any, command: Any) -> int:
            called.append(command)
            return 0

        monkeypatch.setattr(cli_main, "_with_device", device)
        overlay = self._write(tmp_path, "o.json", _doc({}))
        runner = CliRunner()
        assert runner.invoke(cli_main.cli, ["simulate", "run"]).exit_code == 0
        assert (
            runner.invoke(
                cli_main.cli,
                ["simulate", "run", "--scenario", overlay, "--live"],
            ).exit_code
            == 0
        )
        assert (
            runner.invoke(cli_main.cli, ["simulate", "snapshot"]).exit_code == 0
        )
        assert len(called) == 3

    def test_a_bad_input_is_a_usage_error(self, tmp_path: Path) -> None:
        scenario = self._write(
            tmp_path, "s.json", scenario_to_document(_scenario())
        )
        result = CliRunner().invoke(
            cli_main.cli,
            [
                "simulate",
                "run",
                "--scenario",
                scenario,
                "--ambient",
                "60",
                "--environment",
                scenario,
            ],
        )
        assert result.exit_code == 2
        assert "not both" in result.output

    def test_a_null_scenario_never_reads_the_device(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def no_device(*_: Any) -> int:
            raise AssertionError("connected")

        monkeypatch.setattr(cli_main, "_with_device", no_device)
        scenario = self._write(tmp_path, "null.json", None)
        result = CliRunner().invoke(
            cli_main.cli, ["simulate", "run", "--scenario", scenario]
        )
        assert result.exit_code == 2
        assert "not a JSON object" in result.output

    def test_an_unreadable_file_is_a_usage_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{")
        result = CliRunner().invoke(
            cli_main.cli, ["simulate", "run", "--scenario", str(bad)]
        )
        assert result.exit_code == 2
        assert "cannot read the scenario" in result.output

    def test_without_the_extra_a_one_line_hint(self) -> None:
        code = (
            "import sys; "
            "sys.modules.update(numpy=None, pandas=None, scipy=None); "
            "from nwp500.cli.__main__ import cli; "
            "cli(['simulate', 'snapshot'])"
        )
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
        )
        assert done.returncode == 1
        assert done.stderr.strip() == (
            "Error: nwp-cli simulate needs the sim extra: "
            "pip install 'nwp500-python[sim]'"
        )


class TestTheExamples:
    EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "simulator"

    def _doc(self, name: str) -> Any:
        return json.loads((self.EXAMPLES / name).read_text())

    def test_the_scenario_and_its_plan_run(self) -> None:
        inputs = sim_cli.Inputs(
            scenario=self._doc("scenario.json"),
            commands=self._doc("plan.json"),
        )
        built = sim_cli.build(inputs, None, NOW)
        assert built.scenario.commands.tou_enabled is False
        assert built.scenario.commands.writes[0].setpoint_f == 140.0
        result = sim.simulate(built.scenario, built.params)
        assert result.heating
        assert result.windows

    def test_the_overlay_lowers_the_live_setpoint(self) -> None:
        inputs = sim_cli.Inputs(
            scenario=self._doc("lower-setpoint.json"), live=True
        )
        built = sim_cli.build(inputs, _live(), NOW)
        assert built.scenario.settings.setpoint_f == 125.0
        assert built.scenario.state == _live().scenario.state


class TestTheSourcesWindow:
    NOW = datetime(2026, 10, 18, 15, tzinfo=UTC)

    def test_now_and_the_default(self) -> None:
        assert sim_cli.window(sim_cli.Inputs(), self.NOW) == (
            self.NOW,
            timedelta(hours=sim_cli.DEFAULT_HOURS),
        )

    def test_the_scenarios_then_the_flags(self) -> None:
        doc = {
            "schema_version": 1,
            "scenario": {
                "start": "2026-10-19T06:00:00+00:00",
                "horizon": "PT48H",
            },
        }
        start, horizon = sim_cli.window(
            sim_cli.Inputs(scenario=doc, live=True), self.NOW
        )
        assert start == datetime(2026, 10, 19, 6, tzinfo=UTC)
        assert horizon == timedelta(hours=48)
        later = self.NOW + timedelta(days=2)
        assert sim_cli.window(
            sim_cli.Inputs(scenario=doc, live=True, start=later, hours=6),
            self.NOW,
        ) == (later, timedelta(hours=6))


class _Keeper:
    """A ``HomeAssistantBook`` that books ``booked`` without a request."""

    def __init__(self, booked: sim.Booked | None) -> None:
        self.booked = booked
        self.asked: list[tuple[datetime, sim.HeaterParams]] = []

    def book(self, at: datetime, params: sim.HeaterParams) -> Any:
        from nwp500 import sim_home_assistant as ha

        self.asked.append((at, params))
        return ha.BookAnswer(self.booked, False, ("book: a note",))


class TestTheHeatBook:
    """With the sources' heater entities and draw flow, the run walks
    from the tank's booked heat, and readiness reads it with the probes
    apart."""

    def _run(
        self, keeper: Any, start: datetime = NOW, **given: Any
    ) -> tuple[str, Any]:
        out = io.StringIO()
        result = sim_cli.run(
            sim_cli.Inputs(
                scenario=scenario_to_document(_scenario(start=start)), **given
            ),
            None,
            NOW,
            "table",
            out,
            keeper=keeper,
        )
        return " ".join(out.getvalue().split()), result

    def test_without_a_book_the_probes_apart_read_their_heat(self) -> None:
        text, result = self._run(None)
        assert "12.7 gal deliverable now (probes)" in text
        assert "no_heat_book" in result.reasons

    def test_the_book_answers(self) -> None:
        keeper = _Keeper(sim.full_tank_book(130.0, 130.0))
        text, result = self._run(keeper)
        assert "deliverable now (energy)" in text
        assert "no_heat_book" not in result.reasons
        assert keeper.asked[0][0] == NOW

    def test_the_bath_and_the_showers(self) -> None:
        text, _ = self._run(None)
        assert "Bath (28.7 gal): not ready, 16.0 gal short" in text
        assert "Showers (12.0 gal): 1 ready" in text
        text, _ = self._run(_Keeper(sim.full_tank_book(130.0, 130.0)))
        assert (
            "Bath (28.7 gal): not ready, 0.9 gal short; the heat pump" in text
        )
        assert "Showers (12.0 gal): 2 ready" in text

    def test_the_bath_and_shower_volumes_given(self) -> None:
        keeper = _Keeper(sim.full_tank_book(130.0, 130.0))
        text, _ = self._run(keeper, bath=20.0, shower=9.0)
        assert "Bath (20.0 gal): ready, 7.8 gal to spare" in text
        assert "Showers (9.0 gal): 3 ready" in text

    def test_the_volumes_are_in_the_preferred_unit(self) -> None:
        set_unit_system("metric")
        keeper = _Keeper(sim.full_tank_book(130.0, 130.0))
        text, _ = self._run(keeper, shower=34.0679)
        assert "Showers (34.1 L): 3 ready" in text

    @pytest.mark.parametrize("name", ["bath", "shower"])
    def test_a_volume_is_positive(self, name: str) -> None:
        with pytest.raises(sim_cli.InputError, match=f"--{name}"):
            given: dict[str, Any] = {name: 0.0}
            sim_cli.Inputs(**given)

    def test_the_table_reads_the_book_at_the_scenarios_inlet(self) -> None:
        """At a 50 °F inlet, as the walk takes it: not the book's own."""
        import dataclasses

        book = sim.full_tank_book(130.0, 130.0)
        s = _scenario(environment=sim.Environment(ambient_f=62.0, inlet_f=50.0))
        out = io.StringIO()
        sim_cli.run(
            sim_cli.Inputs(scenario=scenario_to_document(s)),
            None,
            NOW,
            "table",
            out,
            keeper=cast(Any, _Keeper(book)),
        )
        p = sim.default_params(2)
        at_50 = sim.readiness(
            s.state, s.settings, p, book=dataclasses.replace(book, inlet_f=50.0)
        ).gal
        own = sim.readiness(s.state, s.settings, p, book=book).gal
        assert at_50 != own
        assert f"{at_50:.1f} gal deliverable now" in " ".join(
            out.getvalue().split()
        )

    def test_no_anchor_walks_without_it(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        _, result = self._run(_Keeper(None))
        assert "no_heat_book" in result.reasons
        assert "book: a note" in caplog.text

    def test_a_scenario_not_starting_now_is_not_booked(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        keeper = _Keeper(sim.full_tank_book(130.0, 130.0))
        _, result = self._run(keeper, start=NOW + timedelta(hours=1))
        assert not keeper.asked
        assert "no_heat_book" in result.reasons
        assert "not now" in caplog.text

    def test_the_keeper_takes_the_draw_flows_volume(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from nwp500 import sim_home_assistant as ha

        class Client:
            def __init__(self, *_: object) -> None:
                pass

            async def __aenter__(self) -> Client:
                return self

            async def __aexit__(self, *_: object) -> None:
                pass

        made: list[dict[str, Any]] = []

        class Keeper:
            def __init__(self, *args: object, **kw: Any) -> None:
                made.append(kw)

            async def read(self, now: datetime) -> None:
                pass

        monkeypatch.setattr(ha, "HomeAssistantClient", Client)
        monkeypatch.setattr(ha, "HomeAssistantBook", Keeper)
        heater = ha.HeaterEntities(
            heard="sensor.heard", upper="sensor.u", lower="sensor.l"
        )
        src = ha.Sources(
            "http://ha.local",
            "t",
            ha.Entities(draw_flow="sensor.draws"),
            heater=heater,
            draw_flow_volume="tank",
        )
        asyncio.run(sim_cli.read_book(sim_cli.Inputs(sources=src), NOW))
        assert made == [{"flow_volume": "tank"}]

    def test_no_keeper_without_the_heater_or_the_flow(self) -> None:
        import asyncio

        from nwp500 import sim_home_assistant as ha

        heater = ha.HeaterEntities(
            heard="sensor.heard", upper="sensor.u", lower="sensor.l"
        )
        for entities, h in (
            (ha.Entities(draw_flow="sensor.draws"), None),
            (ha.Entities(), heater),
        ):
            src = ha.Sources("http://ha.local", "t", entities, heater=h)
            got = asyncio.run(
                sim_cli.read_book(sim_cli.Inputs(sources=src), NOW)
            )
            assert got is None
