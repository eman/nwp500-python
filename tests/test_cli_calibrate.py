"""``nwp-cli simulate calibrate``: a recorded history in, the fitted
parameters and a report out."""

import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

try:
    from click.testing import CliRunner

    from nwp500.cli import __main__ as cli_main
    from nwp500.cli import calibration as cal_cli
    from nwp500.cli.simulate import InputError
except ImportError:
    pytest.skip("CLI dependencies not installed", allow_module_level=True)

from nwp500 import sim, status_history
from nwp500.sim.params import params_from_document, params_to_document
from nwp500.unit_system import reset_unit_system

T0 = datetime(2026, 1, 5, tzinfo=UTC)
UA = 6.0
AIR_F = 60.0
MASS = sim.default_params().tank.thermal_mass_btu_f


@pytest.fixture(autouse=True)
def _units() -> Iterator[None]:
    yield
    reset_unit_system()


def _deci_c(f: float) -> int:
    return round((f - 32) / 1.8 * 10)


def quiet_lines(
    status: dict[str, Any],
    hours: float = 24,
    ua: float = UA,
    *,
    start: datetime = T0,
) -> list[str]:
    """A quiet tank cooling at ``ua`` toward ``AIR_F`` from 130 °F, a
    status every two minutes, as a recorder writes it."""
    lines, tank, gap = [], 130.0, 4.0
    step = timedelta(minutes=2)
    t = start
    while t < start + timedelta(hours=hours):
        raw = status | {
            "tankUpperTemperature": _deci_c(tank + gap / 2),
            "tankLowerTemperature": _deci_c(tank - gap / 2),
        }
        lines.append(status_history.line(t, raw))
        tank -= ua / MASS * (tank - AIR_F) * step.total_seconds() / 3600
        t += step
    return lines


@pytest.fixture
def history(tmp_path: Path, device_status_dict: dict[str, Any]) -> str:
    path = tmp_path / "history.jsonl"
    path.write_text("\n".join(quiet_lines(device_status_dict)) + "\n")
    return str(path)


class TestTheFits:
    def test_a_sensors_readings_fit_it_too(
        self, history: str, tmp_path: Path
    ) -> None:
        air = tmp_path / "air.csv"
        air.write_text(
            "time,temperature\n"
            f"{T0.isoformat()},{AIR_F}\n"
            f"{(T0 + timedelta(days=1)).isoformat()},{AIR_F}\n"
        )
        done = cal_cli.calibrate(
            cal_cli.read_history(history),
            air=cal_cli.read_readings(air, "air"),
        )
        assert done.air == "readings"
        assert done.calibration.standby.ua_ref == pytest.approx(UA, rel=0.05)

    def test_the_notes_name_the_options(self, history: str) -> None:
        done = cal_cli.calibrate(cal_cli.read_history(history))
        assert any("give --params" in n for n in done.notes)
        assert any("compressor is idle" in n for n in done.notes)

    def test_the_parameters_are_a_document(self, history: str) -> None:
        base = sim.default_params(1)
        done = cal_cli.calibrate(
            cal_cli.read_history(history),
            ambient=AIR_F,
            params=params_to_document(base),
        )
        assert done.calibration.params.tank == base.tank
        with pytest.raises(InputError, match="--params is not"):
            cal_cli.calibrate(cal_cli.read_history(history), params={})

    def test_a_refused_input_is_an_input_error(self, history: str) -> None:
        with pytest.raises(InputError, match="not both"):
            cal_cli.calibrate(
                cal_cli.read_history(history),
                air=[(T0, AIR_F)],
                ambient=AIR_F,
            )

    def test_the_report_counts_the_gaps(
        self, tmp_path: Path, device_status_dict: dict[str, Any]
    ) -> None:
        lines = quiet_lines(device_status_dict, hours=8) + quiet_lines(
            device_status_dict, hours=13, start=T0 + timedelta(hours=11)
        )
        path = tmp_path / "restarted.jsonl"
        path.write_text("\n".join(lines) + "\n")
        done = cal_cli.calibrate(cal_cli.read_history(path), ambient=AIR_F)
        out = io.StringIO()
        cal_cli.run(done, None, out)
        assert "1 gap of over 8 min between statuses" in out.getvalue()


class TestTheFiles:
    def test_an_empty_history_is_refused(self, tmp_path: Path) -> None:
        empty = tmp_path / "h.jsonl"
        empty.write_text("\n")
        with pytest.raises(InputError, match="holds no statuses"):
            cal_cli.read_history(empty)

    def test_a_bad_history_line_is_named(
        self, tmp_path: Path, device_status_dict: dict[str, Any]
    ) -> None:
        bad = tmp_path / "h.jsonl"
        bad.write_text(status_history.line(T0, device_status_dict) + "\n{\n")
        with pytest.raises(InputError, match="line 2 is not"):
            cal_cli.read_history(bad)

    def test_readings_without_a_header(self, tmp_path: Path) -> None:
        f = tmp_path / "air.csv"
        f.write_text(f"{T0.isoformat()},61.5\n\n{T0.isoformat()},nan\n")
        assert cal_cli.read_readings(f, "air") == [(T0, 61.5)]

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("time,temperature\nyesterday,60\n", "row 2 of the air"),
            ("2026-01-05T00:00:00,60\n", "UTC offset"),
            ("time,temperature\n", "holds no readings"),
        ],
    )
    def test_bad_readings(self, tmp_path: Path, text: str, match: str) -> None:
        f = tmp_path / "air.csv"
        f.write_text(text)
        with pytest.raises(InputError, match=match):
            cal_cli.read_readings(f, "air")


class TestTheCommand:
    def test_it_prints_the_report_and_writes_the_parameters(
        self,
        history: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def no_device(*_: Any) -> int:
            raise AssertionError("connected")

        monkeypatch.setattr(cli_main, "_with_device", no_device)
        out = tmp_path / "params.json"
        result = CliRunner().invoke(
            cli_main.cli,
            [
                "simulate",
                "calibrate",
                history,
                "--ambient",
                str(AIR_F),
                "-o",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Calibration" in result.stdout
        assert "720 statuses" in result.stdout
        params = params_from_document(json.loads(out.read_text()))
        assert params.loss.ua_btu_hr_f == pytest.approx(UA, rel=0.05)

    def test_a_bad_input_is_a_usage_error(self, history: str) -> None:
        result = CliRunner().invoke(
            cli_main.cli,
            [
                "simulate",
                "calibrate",
                history,
                "--ambient",
                "60",
                "--air",
                history,
            ],
        )
        assert result.exit_code == 2
        assert "not both" in result.output

    def test_the_report_alone(self, history: str) -> None:
        done = cal_cli.calibrate(cal_cli.read_history(history))
        out = io.StringIO()
        cal_cli.run(done, None, out)
        text = out.getvalue()
        assert "the cabinet's less its warmth" in text
        assert "gaps of over" not in text
        assert "Unfitted: compressor, power, gap_tau" in text


class TestHoldout:
    @pytest.fixture
    def days(self, tmp_path: Path, device_status_dict: dict[str, Any]) -> str:
        """Five quiet days: the tank coasting from 130 °F."""
        lines = quiet_lines(device_status_dict, hours=5 * 24)
        path = tmp_path / "days.jsonl"
        path.write_text("\n".join(lines) + "\n")
        return str(path)

    def test_the_fit_sees_the_days_before_only(self, days: str) -> None:
        start = T0 + timedelta(days=3)
        held = cal_cli.holdout(cal_cli.read_history(days), start, ambient=AIR_F)
        assert held.done.n_statuses == 3 * 720
        assert held.fitted.events["windows"]
        assert all(
            datetime.fromisoformat(w) >= start
            for w in held.fitted.events["windows"]
        )
        assert held.base.events == held.fitted.events

    def test_the_fit_scores_better_than_the_defaults(self, days: str) -> None:
        held = cal_cli.holdout(
            cal_cli.read_history(days), T0 + timedelta(days=3), ambient=AIR_F
        )
        name = "standby_fall_abs_f_h"
        assert held.fitted.metrics[name].value < held.base.metrics[name].value

    def test_nothing_on_one_side_is_refused(self, days: str) -> None:
        with pytest.raises(InputError, match="one side"):
            cal_cli.holdout(cal_cli.read_history(days), T0, ambient=AIR_F)

    def test_the_command_prints_the_score(self, days: str) -> None:
        result = CliRunner().invoke(
            cli_main.cli,
            [
                "simulate",
                "calibrate",
                days,
                "--ambient",
                str(AIR_F),
                "--holdout-from",
                (T0 + timedelta(days=3)).isoformat(),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Held-out score" in result.stdout
        assert "standby_upper_rmse_f" in result.stdout

    def test_a_date_is_local_midnight(self) -> None:
        at = cal_cli.parse_instant("2026-01-07", "--holdout-from")
        assert at.tzinfo is not None
        assert (at.hour, at.minute) == (0, 0)

    def test_not_a_date(self) -> None:
        with pytest.raises(InputError, match="ISO 8601"):
            cal_cli.parse_instant("next week", "--holdout-from")
