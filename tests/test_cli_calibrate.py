"""``nwp-cli simulate calibrate``: a recorded history in, the fitted
parameters and a report out."""

import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pandas")
pytest.importorskip("scipy")
try:
    from click.testing import CliRunner

    from nwp500.cli import __main__ as cli_main
    from nwp500.cli import calibration as cal_cli
    from nwp500.cli.simulate import InputError
except ImportError:
    pytest.skip("CLI dependencies not installed", allow_module_level=True)

from nwp500 import sim, status_history
from nwp500 import sim_adapters as sa
from nwp500.models import DeviceStatus
from nwp500.sim import calibration as cal
from nwp500.sim.params import params_from_document, params_to_document
from nwp500.unit_system import reset_unit_system, set_unit_system

T0 = datetime(2026, 1, 5, tzinfo=UTC)
UA = 6.0
AIR_F = 60.0
MASS = sim.default_params().tank.thermal_mass_btu_f


@pytest.fixture(autouse=True)
def _units():
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
def history(tmp_path: Path, device_status_dict) -> str:
    path = tmp_path / "history.jsonl"
    path.write_text("\n".join(quiet_lines(device_status_dict)) + "\n")
    return str(path)


def _terms(done: cal_cli.Calibrated) -> dict[str, cal_cli.Term]:
    return {t.name: t for t in cal_cli.report(done)}


class TestTheFits:
    def test_a_constant_air_fits_the_standby_loss(self, history):
        done = cal_cli.calibrate(cal_cli.read_history(history), ambient=AIR_F)
        assert done.calibration.standby.ua_ref == pytest.approx(UA, rel=0.05)
        assert "standby" not in done.calibration.params.unfitted
        loss = _terms(done)["Standby loss (UA at ref ΔT, BTU/h·°F)"]
        assert loss.fitted
        assert loss.samples == "1 of 1 quiet windows"

    def test_a_sensors_readings_fit_it_too(self, history, tmp_path):
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

    def test_the_air_in_the_preferred_unit(self, history):
        set_unit_system("metric")
        done = cal_cli.calibrate(
            cal_cli.read_history(history), ambient=(AIR_F - 32) / 1.8
        )
        assert done.calibration.standby.ua_ref == pytest.approx(UA, rel=0.05)

    def test_without_air_the_standby_loss_keeps_the_base(self, history):
        done = cal_cli.calibrate(cal_cli.read_history(history))
        assert done.air is None
        assert "standby" in done.calibration.params.unfitted
        loss = _terms(done)["Standby loss (UA at ref ΔT, BTU/h·°F)"]
        assert not loss.fitted
        assert loss.why == "no air given"
        assert any("no air given" in n for n in done.notes)

    def test_each_fit_without_evidence_says_why(self, history):
        terms = _terms(
            cal_cli.calibrate(cal_cli.read_history(history), ambient=AIR_F)
        )
        exponent = terms["Standby loss exponent"]
        # Applied, not kept: the fit replaces the base's exponent with 0.
        assert exponent.fitted and exponent.value == "0"
        assert "a constant loss" in exponent.note
        assert "two 20 °F bands" in exponent.note
        assert "20 needed" in terms["Zone gap time constant (h)"].why
        compressor = terms["Compressor constant"]
        assert not compressor.fitted
        assert compressor.why == "0 recoveries reached their target; 5 needed"
        power = terms["Input power scale"]
        assert not power.fitted
        assert power.why == "the compressor is not fitted"

    def test_a_compressor_fit_reports_its_errors(self, history):
        done = cal_cli.calibrate(cal_cli.read_history(history), ambient=AIR_F)
        fit = cal.CompressorFit(
            compressor_constant=0.06,
            evap_approach_f=11.0,
            mae_minutes=4.2,
            heldout_mae_minutes=6.5,
            n_fitted=12,
            n_heldout=3,
            hit_bounds=False,
            two_zone=False,
        )
        power = cal.PowerFit(
            power_scale=1.05,
            n_power=14,
            cop_scale=None,
            startup_wh=None,
            cop_lift_coeff=None,
            lead_share=None,
            n_cop=4,
        )
        fitted = replace(
            done,
            calibration=replace(done.calibration, compressor=fit, power=power),
        )
        terms = _terms(fitted)
        k = terms["Compressor constant"]
        assert k.fitted and k.value == "0.06"
        assert k.samples == "12 recoveries"
        assert k.error == "4.2 min mae, 6.5 on 3 held out"
        assert terms["Input power scale"].fitted
        cop = terms["COP scale"]
        assert not cop.fitted
        assert cop.why == "too few cycles (10 needed)"
        pinned = replace(
            fitted,
            calibration=replace(
                fitted.calibration, compressor=replace(fit, hit_bounds=True)
            ),
        )
        k = _terms(pinned)["Compressor constant"]
        assert not k.fitted
        assert "pinned on a bound" in k.why

    def test_without_humidity_the_air_is_50_percent(self, history, monkeypatch):
        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal_cli.cal, "calibrate", spy)
        cal_cli.calibrate(cal_cli.read_history(history), ambient=AIR_F)
        assert (seen[0]["humidity_pct"] == 50.0).all()
        cal_cli.calibrate(
            cal_cli.read_history(history),
            ambient=AIR_F,
            humidity=[(T0, 35.0)],
        )
        assert (seen[1]["humidity_pct"] == 35.0).all()

    def test_a_stopped_recording_is_not_one_quiet_window(
        self, tmp_path, device_status_dict
    ):
        # Recorded 0-8 h and 11-24 h; the tank was heated back to 130 °F
        # in between, unobserved.
        lines = quiet_lines(device_status_dict, hours=8) + quiet_lines(
            device_status_dict, hours=13, start=T0 + timedelta(hours=11)
        )
        path = tmp_path / "restarted.jsonl"
        path.write_text("\n".join(lines) + "\n")
        readings = cal_cli.read_history(path)
        done = cal_cli.calibrate(readings, ambient=AIR_F)
        assert done.n_gaps == 1
        s = done.calibration.standby
        assert (s.n_quiet, len(s.windows)) == (2, 2)
        assert s.ua_ref == pytest.approx(UA, rel=0.05)
        # Taken as observed, the gap joins them into one window.
        joined = cal.fit_standby(sa.history(readings, air=[(T0, AIR_F)]), MASS)
        assert joined.n_quiet == 1
        out = io.StringIO()
        cal_cli.run(done, None, out)
        assert "1 gap of over 8 min between statuses" in out.getvalue()

    @pytest.mark.parametrize(
        ("spacing_s", "expected"),
        [(30, timedelta(minutes=5)), (120, timedelta(minutes=8))],
    )
    def test_the_gap_scales_with_the_spacing(
        self, device_status_dict, spacing_s, expected
    ):
        status = DeviceStatus.model_validate(device_status_dict)
        readings = [
            (T0 + timedelta(seconds=spacing_s * i), status) for i in range(10)
        ]
        assert cal_cli.max_gap(readings) == expected
        assert cal_cli.max_gap(readings[:1]) == cal_cli.MIN_GAP

    def test_a_sources_record_fits_over_what_it_covers(self, history):
        from nwp500.sim_home_assistant import RecordInputs

        readings = cal_cli.read_history(history)
        record = RecordInputs(
            air=[(T0, AIR_F), (T0 + timedelta(days=1), AIR_F)],
            humidity=[(T0, 45.0)],
            drawing=[],
            circulating=[],
            notes=("humidity: a note",),
        )
        done = cal_cli.calibrate(readings, record=record)
        assert done.air == "source"
        s = done.calibration.standby
        assert s.ua_ref == pytest.approx(UA, rel=0.05)
        assert s.quiet_by == "meter"
        assert "humidity: a note" in done.notes
        # Only what it covers: from 12 h in, half the window is left.
        late = replace(
            record,
            air=[
                (T0 + timedelta(hours=12), AIR_F),
                (T0 + timedelta(days=1), AIR_F),
            ],
        )
        half = cal_cli.calibrate(readings, record=late).calibration.standby
        # The later half, the tank nearer the air, and only it.
        assert half.windows
        assert half.windows[0].start >= T0 + timedelta(hours=12)
        assert half.windows[0].delta_t_mean_f < s.windows[0].delta_t_mean_f

    @pytest.mark.parametrize(
        ("drawing", "circulating"), [(None, []), ([], None)]
    )
    def test_the_meter_and_circulation_go_together(
        self, history, monkeypatch, drawing, circulating
    ):
        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal_cli.cal, "calibrate", spy)
        record = RecordInputs([(T0, AIR_F)], None, drawing, circulating)
        done = cal_cli.calibrate(cal_cli.read_history(history), record=record)
        assert not {"drawing", "circulating"} & set(seen[0].columns)
        assert done.calibration.standby.quiet_by == "dhw_in_use"
        assert any("together or not at all" in n for n in done.notes)

    def test_unobserved_air_and_humidity(self, history, monkeypatch):
        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal_cli.cal, "calibrate", spy)
        gap = (T0 + timedelta(hours=4), T0 + timedelta(hours=6))
        record = RecordInputs(
            air=[(T0, AIR_F), (T0 + timedelta(days=1), AIR_F)],
            # Recorded over the first 10 h only.
            humidity=[(T0, 30.0), (T0 + timedelta(hours=9), 30.0)],
            drawing=[],
            circulating=[],
            air_outages=(gap,),
            humidity_outages=(gap,),
        )
        cal_cli.calibrate(cal_cli.read_history(history), record=record)
        frame = seen[0]
        inside = frame.index[(frame.index >= gap[0]) & (frame.index < gap[1])]
        assert len(inside) and frame.loc[inside, "air_f"].isna().all()
        assert (frame.loc[inside, "humidity_pct"] == 50.0).all()
        early = frame.index[frame.index < T0 + timedelta(hours=3)]
        late = frame.index[frame.index > T0 + timedelta(hours=11)]
        assert (frame.loc[early, "humidity_pct"] == 30.0).all()
        assert (frame.loc[late, "humidity_pct"] == 50.0).all()
        assert frame.loc[late, "air_f"].notna().all()

    def test_no_window_spans_an_air_outage(self, history):
        from nwp500.sim_home_assistant import RecordInputs

        gap = (T0 + timedelta(hours=10), T0 + timedelta(hours=10, minutes=20))
        record = RecordInputs(
            air=[(T0, AIR_F), (T0 + timedelta(days=1), AIR_F)],
            humidity=None,
            drawing=[],
            circulating=[],
            air_outages=(gap,),
        )
        done = cal_cli.calibrate(cal_cli.read_history(history), record=record)
        windows = done.calibration.standby.windows
        assert len(windows) == 2
        assert all(w.end <= gap[0] or w.start >= gap[1] for w in windows)

    def test_a_later_reading_does_not_reach_back_over_an_outage(
        self, history, monkeypatch
    ):
        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal_cli.cal, "calibrate", spy)
        gap = (T0 + timedelta(hours=4), T0 + timedelta(hours=8))
        record = RecordInputs(
            air=[(T0, AIR_F), (gap[1], AIR_F + 20.0)],
            humidity=[(T0, 30.0), (gap[1], 70.0)],
            drawing=[],
            circulating=[],
            air_outages=(gap,),
            humidity_outages=(gap,),
        )
        cal_cli.calibrate(cal_cli.read_history(history), record=record)
        frame = seen[0]
        before = frame.index[frame.index < gap[0]]
        assert len(before)
        assert frame.loc[before, "air_f"].tolist() == pytest.approx(
            [AIR_F] * len(before)
        )
        assert (frame.loc[before, "humidity_pct"] == 30.0).all()

    def test_source_states_hold_until_the_next(self, history, monkeypatch):
        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal_cli.cal, "calibrate", spy)
        h = timedelta(hours=1)
        record = RecordInputs(
            air=[(T0, AIR_F), (T0 + 8 * h, AIR_F + 20.0), (T0 + 24 * h, AIR_F)],
            humidity=[(T0, 30.0), (T0 + 8 * h, 70.0)],
            drawing=[],
            circulating=[],
        )
        cal_cli.calibrate(cal_cli.read_history(history), record=record)
        frame = seen[0]
        at = frame.index[(frame.index > T0 + h) & (frame.index < T0 + 8 * h)]
        assert len(at)
        assert frame.loc[at, "air_f"].tolist() == pytest.approx(
            [AIR_F] * len(at)
        )
        assert (frame.loc[at, "humidity_pct"] == 30.0).all()
        after = frame.index[
            (frame.index >= T0 + 8 * h) & (frame.index < T0 + 9 * h)
        ]
        assert (frame.loc[after, "humidity_pct"] == 70.0).all()

    def test_stepped(self):
        h = timedelta(hours=1)
        tick = timedelta(microseconds=1)
        assert cal_cli._stepped([(T0 + 6 * h, 70.0), (T0, 60.0)]) == [
            (T0, 60.0),
            (T0 + 6 * h - tick, 60.0),
            (T0 + 6 * h, 70.0),
        ]

    def test_no_recovery_spans_unobserved_air(self, history, monkeypatch):
        import numpy as np

        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal_cli.cal, "calibrate", spy)
        h = timedelta(hours=1)
        # Recorded to 10 h: the air's span ends at 11 h.
        record = RecordInputs(
            air=[(T0, AIR_F), (T0 + 10 * h, AIR_F)],
            humidity=None,
            drawing=[],
            circulating=[],
        )
        cal_cli.calibrate(cal_cli.read_history(history), record=record)
        frame = seen[0].copy()
        # Reached and not cut short: nothing left to heat at the end.
        frame["energy_to_setpoint_wh"] = 0.0
        target = float(frame["target_f"].iloc[0])
        for start in (T0 + 2 * h, T0 + 10 * h + timedelta(minutes=30)):
            span = (frame.index >= start) & (frame.index < start + 2 * h)
            frame.loc[span, "compressor_on"] = True
            frame.loc[span, "lower_f"] = np.linspace(
                target - 30.0, target, int(span.sum())
            )
        found = cal.recoveries(frame, air="air_f")
        # The one inside the air's span, not the one across its end.
        assert len(found) == 1
        assert found["start_time"].iloc[0] < T0 + 10 * h

    def test_flags_win_over_the_sources(self, history):
        from nwp500.sim_home_assistant import RecordInputs

        record = RecordInputs([(T0, 30.0)], None, None, None)
        done = cal_cli.calibrate(
            cal_cli.read_history(history), ambient=AIR_F, record=record
        )
        assert done.air == "constant"
        assert done.calibration.standby.ua_ref == pytest.approx(UA, rel=0.05)

    def test_the_base_is_the_one_given(self, history):
        base = replace(sim.default_params(1), unfitted=())
        done = cal_cli.calibrate(
            cal_cli.read_history(history),
            ambient=AIR_F,
            params=params_to_document(base),
        )
        assert done.calibration.params.tank == base.tank
        assert not done.notes

    def test_air_and_ambient_together_are_refused(self, history):
        with pytest.raises(InputError, match="not both"):
            cal_cli.calibrate(
                cal_cli.read_history(history),
                air=[(T0, AIR_F)],
                ambient=AIR_F,
            )


class TestTheFiles:
    def test_an_empty_history_is_refused(self, tmp_path):
        empty = tmp_path / "h.jsonl"
        empty.write_text("\n")
        with pytest.raises(InputError, match="holds no statuses"):
            cal_cli.read_history(empty)

    def test_a_bad_history_line_is_named(self, tmp_path, device_status_dict):
        bad = tmp_path / "h.jsonl"
        bad.write_text(status_history.line(T0, device_status_dict) + "\n{\n")
        with pytest.raises(InputError, match="line 2 is not"):
            cal_cli.read_history(bad)

    def test_readings_without_a_header(self, tmp_path):
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
    def test_bad_readings(self, tmp_path, text, match):
        f = tmp_path / "air.csv"
        f.write_text(text)
        with pytest.raises(InputError, match=match):
            cal_cli.read_readings(f, "air")


class TestTheCommand:
    def test_it_prints_the_report_and_writes_the_parameters(
        self, history, tmp_path, monkeypatch
    ):
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

    def test_a_bad_input_is_a_usage_error(self, history):
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

    def test_the_report_alone(self, history):
        done = cal_cli.calibrate(cal_cli.read_history(history))
        out = io.StringIO()
        cal_cli.run(done, None, out)
        text = out.getvalue()
        assert "base: no air given" in text
        assert "gaps of over" not in text
        assert "Unfitted: compressor, power, standby, gap_tau" in text
