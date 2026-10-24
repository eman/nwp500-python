"""``nwp500.sim_calibrate``: a recorded history in, the fitted
parameters and a report of each fit out."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from nwp500 import sim, status_history
from nwp500 import sim_adapters as sa
from nwp500 import sim_calibrate as sc
from nwp500.models import DeviceStatus
from nwp500.sim import calibration as cal
from nwp500.sim.params import params_to_document
from nwp500.temperature import DeciCelsius
from nwp500.unit_system import reset_unit_system, set_unit_system

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


def _read(path: str | Path) -> list[status_history.TimedStatus]:
    with Path(path).open(encoding="utf-8") as f:
        return status_history.read(f)


def _terms(done: sc.Calibrated) -> dict[str, sc.Term]:
    return {t.name: t for t in sc.report(done)}


class TestTheFits:
    def test_a_constant_air_fits_the_standby_loss(self, history: str) -> None:
        done = sc.calibrate(_read(history), ambient=AIR_F)
        assert done.calibration.standby.ua_ref == pytest.approx(UA, rel=0.05)
        assert "standby" not in done.calibration.params.unfitted
        loss = _terms(done)["Standby loss (UA at ref ΔT, BTU/h·°F)"]
        assert loss.fitted
        assert loss.samples == "1 of 1 quiet windows"

    def test_the_air_in_the_preferred_unit(self, history: str) -> None:
        set_unit_system("metric")
        done = sc.calibrate(_read(history), ambient=(AIR_F - 32) / 1.8)
        assert done.calibration.standby.ua_ref == pytest.approx(UA, rel=0.05)

    def test_without_air_the_standby_loss_keeps_the_base(
        self, history: str
    ) -> None:
        done = sc.calibrate(_read(history))
        assert done.air is None
        assert "standby" in done.calibration.params.unfitted
        loss = _terms(done)["Standby loss (UA at ref ΔT, BTU/h·°F)"]
        assert not loss.fitted
        assert loss.why == "no air given"
        assert any("no air given" in n for n in done.notes)

    def test_each_fit_without_evidence_says_why(self, history: str) -> None:
        terms = _terms(sc.calibrate(_read(history), ambient=AIR_F))
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

    def test_a_compressor_fit_reports_its_errors(self, history: str) -> None:
        done = sc.calibrate(_read(history), ambient=AIR_F)
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

    def test_without_humidity_the_air_is_50_percent(
        self, history: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal, "calibrate", spy)
        sc.calibrate(_read(history), ambient=AIR_F)
        assert (seen[0]["humidity_pct"] == 50.0).all()
        sc.calibrate(
            _read(history),
            ambient=AIR_F,
            humidity=[(T0, 35.0)],
        )
        assert (seen[1]["humidity_pct"] == 35.0).all()

    def test_a_stopped_recording_is_not_one_quiet_window(
        self, tmp_path: Path, device_status_dict: dict[str, Any]
    ) -> None:
        # Recorded 0-8 h and 11-24 h; the tank was heated back to 130 °F
        # in between, unobserved.
        lines = quiet_lines(device_status_dict, hours=8) + quiet_lines(
            device_status_dict, hours=13, start=T0 + timedelta(hours=11)
        )
        path = tmp_path / "restarted.jsonl"
        path.write_text("\n".join(lines) + "\n")
        readings = _read(path)
        done = sc.calibrate(readings, ambient=AIR_F)
        assert done.n_gaps == 1
        s = done.calibration.standby
        assert (s.n_quiet, len(s.windows)) == (2, 2)
        assert s.ua_ref == pytest.approx(UA, rel=0.05)
        # Taken as observed, the gap joins them into one window.
        joined = cal.fit_standby(sa.history(readings, air=[(T0, AIR_F)]), MASS)
        assert joined.n_quiet == 1

    @pytest.mark.parametrize(
        ("spacing_s", "expected"),
        [(30, timedelta(minutes=5)), (120, timedelta(minutes=8))],
    )
    def test_the_gap_scales_with_the_spacing(
        self, spacing_s: int, expected: timedelta
    ) -> None:
        times = [T0 + timedelta(seconds=spacing_s * i) for i in range(10)]
        assert sc.max_gap(times) == expected
        assert sc.max_gap(times[:1]) == sc.MIN_GAP

    def test_a_sources_record_fits_over_what_it_covers(
        self, history: str
    ) -> None:
        from nwp500.sim_home_assistant import RecordInputs

        readings = _read(history)
        record = RecordInputs(
            air=[(T0, AIR_F), (T0 + timedelta(days=1), AIR_F)],
            humidity=[(T0, 45.0)],
            drawing=[],
            circulating=[],
            notes=("humidity: a note",),
        )
        done = sc.calibrate(readings, record=record)
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
        half = sc.calibrate(readings, record=late).calibration.standby
        # The later half, the tank nearer the air, and only it.
        assert half.windows
        assert half.windows[0].start >= T0 + timedelta(hours=12)
        assert half.windows[0].delta_t_mean_f < s.windows[0].delta_t_mean_f

    @pytest.mark.parametrize(
        ("drawing", "circulating"), [(None, []), ([], None)]
    )
    def test_the_meter_and_circulation_go_together(
        self,
        history: str,
        monkeypatch: pytest.MonkeyPatch,
        drawing: list[Any] | None,
        circulating: list[Any] | None,
    ) -> None:
        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal, "calibrate", spy)
        record = RecordInputs([(T0, AIR_F)], None, drawing, circulating)
        done = sc.calibrate(_read(history), record=record)
        assert not {"drawing", "circulating"} & set(seen[0].columns)
        assert done.calibration.standby.quiet_by == "dhw_in_use"
        assert any("together or not at all" in n for n in done.notes)

    def test_unobserved_air_and_humidity(
        self, history: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal, "calibrate", spy)
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
        sc.calibrate(_read(history), record=record)
        frame = seen[0]
        inside = frame.index[(frame.index >= gap[0]) & (frame.index < gap[1])]
        assert len(inside) and frame.loc[inside, "air_f"].isna().all()
        assert (frame.loc[inside, "humidity_pct"] == 50.0).all()
        early = frame.index[frame.index < T0 + timedelta(hours=3)]
        late = frame.index[frame.index > T0 + timedelta(hours=11)]
        assert (frame.loc[early, "humidity_pct"] == 30.0).all()
        assert (frame.loc[late, "humidity_pct"] == 50.0).all()
        assert frame.loc[late, "air_f"].notna().all()

    def test_no_window_spans_an_air_outage(self, history: str) -> None:
        from nwp500.sim_home_assistant import RecordInputs

        gap = (T0 + timedelta(hours=10), T0 + timedelta(hours=10, minutes=20))
        record = RecordInputs(
            air=[(T0, AIR_F), (T0 + timedelta(days=1), AIR_F)],
            humidity=None,
            drawing=[],
            circulating=[],
            air_outages=(gap,),
        )
        done = sc.calibrate(_read(history), record=record)
        windows = done.calibration.standby.windows
        assert len(windows) == 2
        assert all(w.end <= gap[0] or w.start >= gap[1] for w in windows)

    def test_a_later_reading_does_not_reach_back_over_an_outage(
        self, history: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal, "calibrate", spy)
        gap = (T0 + timedelta(hours=4), T0 + timedelta(hours=8))
        record = RecordInputs(
            air=[(T0, AIR_F), (gap[1], AIR_F + 20.0)],
            humidity=[(T0, 30.0), (gap[1], 70.0)],
            drawing=[],
            circulating=[],
            air_outages=(gap,),
            humidity_outages=(gap,),
        )
        sc.calibrate(_read(history), record=record)
        frame = seen[0]
        before = frame.index[frame.index < gap[0]]
        assert len(before)
        assert frame.loc[before, "air_f"].tolist() == pytest.approx(
            [AIR_F] * len(before)
        )
        assert (frame.loc[before, "humidity_pct"] == 30.0).all()

    def test_source_states_hold_until_the_next(
        self, history: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal, "calibrate", spy)
        h = timedelta(hours=1)
        record = RecordInputs(
            air=[(T0, AIR_F), (T0 + 8 * h, AIR_F + 20.0), (T0 + 24 * h, AIR_F)],
            humidity=[(T0, 30.0), (T0 + 8 * h, 70.0)],
            drawing=[],
            circulating=[],
        )
        sc.calibrate(_read(history), record=record)
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

    def test_stepped(self) -> None:
        h = timedelta(hours=1)
        tick = timedelta(microseconds=1)
        assert sc._stepped([(T0 + 6 * h, 70.0), (T0, 60.0)]) == [
            (T0, 60.0),
            (T0 + 6 * h - tick, 60.0),
            (T0 + 6 * h, 70.0),
        ]

    def test_no_recovery_spans_unobserved_air(
        self, history: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import numpy as np

        from nwp500.sim_home_assistant import RecordInputs

        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal, "calibrate", spy)
        h = timedelta(hours=1)
        # Recorded to 10 h: the air's span ends at 11 h.
        record = RecordInputs(
            air=[(T0, AIR_F), (T0 + 10 * h, AIR_F)],
            humidity=None,
            drawing=[],
            circulating=[],
        )
        sc.calibrate(_read(history), record=record)
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

    def test_a_rejected_reading_masks_the_air(
        self, history: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from nwp500 import sim_home_assistant as ha

        h = timedelta(hours=1)

        def row(at: datetime, state: str, unit: str | None) -> dict[str, Any]:
            r: dict[str, Any] = {"entity_id": "sensor.air", "state": state}
            r["last_updated"] = at.isoformat()
            if unit:
                r["attributes"] = {"unit_of_measurement": unit}
            return r

        doc = [
            [
                row(T0, str(AIR_F), "°F"),
                row(T0 + 4 * h, str(AIR_F), None),
                row(T0 + 8 * h, str(AIR_F), "°F"),
            ]
        ]

        class Client:
            async def state(self, entity: str) -> ha.State:
                return ha.State(entity, AIR_F, "°F", T0)

            async def read_history(
                self, entities: Any, start: Any, end: Any
            ) -> ha.History:
                names = list(entities)
                return ha.History(
                    ha.history_for(doc, names),
                    {n: [] for n in names},
                    {n: ha.parse_units(doc).get(n, []) for n in names},
                )

        record = asyncio.run(
            ha.record_inputs(
                cast("ha.HomeAssistantClient", Client()),
                ha.Entities(air="sensor.air"),
                T0,
                T0 + 24 * h,
            )
        )
        seen: list[Any] = []
        real = cal.calibrate

        def spy(frame: Any, *args: Any, **kw: Any) -> Any:
            seen.append(frame)
            return real(frame, *args, **kw)

        monkeypatch.setattr(cal, "calibrate", spy)
        sc.calibrate(_read(history), record=record)
        frame = seen[0]
        gap = (frame.index > T0 + 4 * h) & (frame.index < T0 + 8 * h)
        assert gap.any()
        assert frame.loc[gap, "air_f"].isna().all()
        assert frame.loc[gap, "air_unobserved"].all()
        assert frame.loc[gap, "excluded"].all()

    def test_flags_win_over_the_sources(self, history: str) -> None:
        from nwp500.sim_home_assistant import RecordInputs

        record = RecordInputs([(T0, 30.0)], None, None, None)
        done = sc.calibrate(_read(history), ambient=AIR_F, record=record)
        assert done.air == "constant"
        assert done.calibration.standby.ua_ref == pytest.approx(UA, rel=0.05)

    def test_the_base_is_the_one_given(self, history: str) -> None:
        base = replace(sim.default_params(1), unfitted=())
        done = sc.calibrate(
            _read(history),
            ambient=AIR_F,
            params=params_to_document(base),
        )
        assert done.calibration.params.tank == base.tank
        assert not done.notes

    def test_air_and_ambient_together_are_refused(self, history: str) -> None:
        with pytest.raises(sc.CalibrationInputError, match="not both"):
            sc.calibrate(
                _read(history),
                air=[(T0, AIR_F)],
                ambient=AIR_F,
            )


class TestTheInputs:
    def test_heater_params_are_taken_as_they_are(self, history: str) -> None:
        base = replace(sim.default_params(1), unfitted=())
        done = sc.calibrate(_read(history), ambient=AIR_F, params=base)
        assert done.calibration.params.tank == base.tank
        assert not done.notes

    @pytest.mark.parametrize("params", [{"tank": "no"}, [], "params", 3])
    def test_a_bad_document_is_refused(self, history: str, params: Any) -> None:
        with pytest.raises(sc.CalibrationInputError, match="parameters"):
            sc.calibrate(_read(history), params=params)

    def test_instants_across_a_change_of_clocks(self) -> None:
        from datetime import timezone

        pst, pdt = timezone(timedelta(hours=-8)), timezone(timedelta(hours=-7))
        times = [
            datetime(2026, 3, 8, 1, 59, 30, tzinfo=pst),
            datetime(2026, 3, 8, 3, 0, tzinfo=pdt),
            datetime(2026, 3, 8, 3, 0, 30, tzinfo=pdt),
        ]
        assert sc.max_gap(times) == sc.MIN_GAP

    def test_no_statuses_are_refused(self) -> None:
        with pytest.raises(sc.CalibrationInputError, match="no statuses"):
            sc.calibrate(iter(()))

    def test_the_notes_name_no_options(self, history: str) -> None:
        done = sc.calibrate(_read(history))
        assert done.notes == (sc.DEFAULT_BASE_NOTE, sc.NO_AIR_NOTE)
        assert not any("--" in n for n in done.notes)

    def test_a_generator_over_day_files_is_read_once(
        self, tmp_path: Path, device_status_dict: dict[str, Any]
    ) -> None:
        lines = quiet_lines(device_status_dict)
        days = []
        for i, part in enumerate((lines[:300], lines[300:])):
            day = tmp_path / f"day{i}.jsonl"
            day.write_text("\n".join(part) + "\n")
            days.append(day)
        taken = 0

        def readings() -> Iterator[status_history.TimedStatus]:
            nonlocal taken
            for day in days:
                with day.open(encoding="utf-8") as f:
                    for reading in status_history.iter_read(f):
                        taken += 1
                        yield reading

        done = sc.calibrate(readings(), ambient=AIR_F)
        assert taken == done.n_statuses == len(lines)
        whole = sc.calibrate(_read(days[0]) + _read(days[1]), ambient=AIR_F)
        assert done.calibration.standby.ua_ref == pytest.approx(
            whole.calibration.standby.ua_ref
        )


class TestTheFrame:
    def test_readings_in_any_order_make_the_same_frame(
        self, history: str
    ) -> None:
        readings = _read(history)
        # Odd rows, then even rows backwards.
        mixed = readings[1::2] + readings[::2][::-1]
        a = sa.history(readings, air=[(T0, AIR_F)])
        b = sa.history(iter(mixed), air=[(T0, AIR_F)])
        assert a.equals(b)
        assert str(a.index.dtype) == "datetime64[ns, UTC]"

    def test_the_status_columns(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        status = DeviceStatus.model_validate(
            device_status_dict | {"compUse": 2, "dhwUse": 2}
        )
        frame = sa.history([(T0, status)])
        row = frame.iloc[0]
        assert bool(row["compressor_on"]) and bool(row["dhw_in_use"])
        assert frame["compressor_on"].dtype == bool
        assert frame["upper_f"].dtype == float
        assert row["heater_air_f"] == pytest.approx(
            sa._from_device(DeciCelsius(status.ambient_temperature_raw))
        )


def days_of_quiet(
    status: dict[str, Any], uas: list[float]
) -> list[status_history.TimedStatus]:
    """A day for each of ``uas``: 20 h of a quiet tank cooling at that
    UA toward ``AIR_F`` from 130 °F, then 4 h of the upper element
    heating it back. A status every two minutes."""
    out: list[status_history.TimedStatus] = []
    step = timedelta(minutes=2)
    t = T0
    for ua in uas:
        tank, gap = 130.0, 4.0
        end = t + timedelta(hours=20)
        while t < end:
            raw = status | {
                "tankUpperTemperature": _deci_c(tank + gap / 2),
                "tankLowerTemperature": _deci_c(tank - gap / 2),
            }
            out.append((t, DeviceStatus.model_validate(raw)))
            tank -= ua / MASS * (tank - AIR_F) * step.total_seconds() / 3600
            t += step
        end = t + timedelta(hours=4)
        while t < end:
            raw = status | {
                "heatUpperUse": 2,
                "tankUpperTemperature": _deci_c(130.0),
                "tankLowerTemperature": _deci_c(126.0),
            }
            out.append((t, DeviceStatus.model_validate(raw)))
            t += step
    return out


def _fitted(ua: float) -> sim.HeaterParams:
    """The defaults with a standby loss of ``ua``, taken as fitted."""
    base = sim.default_params()
    return replace(
        base,
        loss=replace(base.loss, ua_btu_hr_f=ua, ua_exponent=0.0),
        unfitted=tuple(t for t in base.unfitted if t != "standby"),
    )


class TestKeepBetter:
    def test_a_better_refit_replaces_the_base(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        readings = days_of_quiet(device_status_dict, [UA] * 12)
        done = sc.calibrate(
            readings, ambient=AIR_F, params=_fitted(12.0), keep_better=True
        )
        (standby,) = [j for j in done.judged if j.group == "standby"]
        assert standby.kept == "refit"
        assert standby.n_held == 2
        assert standby.refit_error is not None
        assert standby.base_error is not None
        assert standby.refit_error < standby.base_error
        loss = done.calibration.params.loss
        assert loss.ua_btu_hr_f == pytest.approx(UA, rel=0.05)
        assert "standby" not in done.calibration.params.unfitted
        term = _terms(done)["Standby loss (UA at ref ΔT, BTU/h·°F)"]
        assert term.fitted
        assert "against the base's" in term.note

    def test_the_base_stays_where_the_latest_evidence_favours_it(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        # The tank lost twice as fast until the last two days.
        readings = days_of_quiet(device_status_dict, [2 * UA] * 10 + [UA] * 2)
        base = _fitted(UA)
        done = sc.calibrate(
            readings, ambient=AIR_F, params=base, keep_better=True
        )
        (standby,) = [j for j in done.judged if j.group == "standby"]
        assert standby.kept == "base"
        assert done.calibration.params.loss == base.loss
        term = _terms(done)["Standby loss (UA at ref ΔT, BTU/h·°F)"]
        assert not term.fitted
        assert term.value == "6"
        assert term.why.startswith("kept the base: it scores ")
        assert "on the 2 latest quiet windows" in term.why
        scores = sc.score(done, base)
        assert scores["standby"] == pytest.approx(standby.base_error)

    def test_too_little_evidence_keeps_the_base(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        readings = days_of_quiet(device_status_dict, [UA] * 4)
        base = _fitted(12.0)
        done = sc.calibrate(
            readings, ambient=AIR_F, params=base, keep_better=True
        )
        (standby,) = [j for j in done.judged if j.group == "standby"]
        assert standby.kept == "base"
        assert "under 10 quiet windows" in standby.why
        assert done.calibration.params.loss.ua_btu_hr_f == 12.0
        assert sc.score(done, base)["standby"] is None

    def test_an_unfitted_base_takes_the_refit(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        readings = days_of_quiet(device_status_dict, [UA] * 4)
        base = sim.default_params()
        base = replace(base, unfitted=(*base.unfitted, "standby"))
        done = sc.calibrate(
            readings, ambient=AIR_F, params=base, keep_better=True
        )
        assert not [j for j in done.judged if j.group == "standby"]
        loss = done.calibration.params.loss
        assert loss.ua_btu_hr_f == pytest.approx(UA, rel=0.05)
        assert "standby" not in done.calibration.params.unfitted

    def test_a_score_needs_keep_better(self, history: str) -> None:
        done = sc.calibrate(_read(history), ambient=AIR_F)
        with pytest.raises(sc.CalibrationInputError, match="keep_better"):
            sc.score(done, sim.default_params())


class TestTheJudgement:
    def test_the_refit_wins_only_by_scoring_better(self) -> None:
        win = sc._judge("compressor", "reached recoveries", 3, 9.0, 4.0)
        assert (win.kept, win.why) == ("refit", "")
        tie = sc._judge("compressor", "reached recoveries", 3, 4.0, 4.0)
        assert tie.kept == "base"
        assert tie.why == (
            "kept the base: it scores 4 against the refit's 4 on the 3 "
            "latest reached recoveries"
        )
        unscored = sc._judge("cop", "cycles", 3, 1.0, None)
        assert unscored.kept == "base"
        assert "the refit has no score" in unscored.why
        none_held = sc._judge("cop", "cycles", 0, None, None)
        assert none_held.why == (
            "kept the base: under 10 cycles to judge a refit by"
        )
        no_refit = sc._judge("cop", "cycles", 3, 1.0, None, refit_exists=False)
        assert no_refit.kept == "base"
        assert no_refit.why == (
            "kept the base: too few cycles to refit on (10 needed)"
        )

    def test_the_split_is_the_recoveries(self) -> None:
        assert [sc._split(n) for n in (9, 10, 12, 20, 50)] == [0, 2, 2, 4, 10]


@pytest.fixture
def pinned_compressor(monkeypatch: pytest.MonkeyPatch) -> None:
    """``recovery_days``' recoveries fit K at about 0.04; a ceiling under
    it pins the refit on its bound."""
    monkeypatch.setattr(cal, "K_BOUNDS", (0.004, 0.02))


def recovery_days(days: int) -> Any:
    """A frame of ``days``: a quiet decay, a draw, then a heat-pump
    recovery to 140 °F each day, a sample a minute, the heater drawing
    its compressor's power."""
    import pandas as pd

    parts = []
    upper, lower = 140.0, 138.0
    for d in range(days):
        n = 24 * 60
        h = np.arange(n) / 60
        air = 60.0 + 5.0 * np.sin(d)
        up, lo = np.empty(n), np.empty(n)
        comp, dhw = np.zeros(n, bool), np.zeros(n, bool)
        quiet = h < 16
        mean = air + ((upper + lower) / 2 - air) * np.exp(-UA / MASS * h[quiet])
        up[quiet], lo[quiet] = mean + 1, mean - 1
        draw = (h >= 16) & (h < 16.2)
        dhw[draw] = True
        drop = 20.0 + 2 * (d % 5)
        up[draw] = up[quiet][-1] - 3
        lo[draw] = np.linspace(lo[quiet][-1], lo[quiet][-1] - drop, draw.sum())
        run_h = (40 + 2.5 * drop) / 60
        run = (h >= 16.25) & (h < 16.25 + run_h)
        comp[run] = True
        lo[run] = np.linspace(lo[draw][-1], 140.0, run.sum())
        up[run] = np.linspace(up[draw][-1], 140.0, run.sum())
        between = (h >= 16.2) & (h < 16.25)
        up[between], lo[between] = up[draw][-1], lo[draw][-1]
        rest = h >= 16.25 + run_h
        up[rest], lo[rest] = 140.0, 138.0
        parts.append(
            pd.DataFrame(
                {
                    "upper_f": up,
                    "lower_f": lo,
                    "compressor_on": comp,
                    "element_on": False,
                    "dhw_in_use": dhw,
                    "target_f": 140.0,
                    "excluded": False,
                    "power_w": np.where(comp, 450.0 + 3 * (140 - lo), 3.0),
                    "energy_to_setpoint_wh": np.where(
                        comp | draw, (140 - lo) * 50.0, 0.0
                    ),
                    "heater_air_f": np.where(comp, air, np.nan),
                    "air_f": air,
                    "humidity_pct": 50.0,
                },
                index=pd.DatetimeIndex(
                    [T0 + timedelta(days=d, minutes=int(m)) for m in range(n)]
                ),
            )
        )
    return pd.concat(parts)


class TestKeepBetterEveryGroup:
    def test_each_judgement_follows_its_scores(self) -> None:
        frame = recovery_days(14)
        base = sim.default_params()
        fitted, judged, held = sc._keep_better(frame, base, "air_f")
        groups = {j.group: j for j in judged}
        assert {"standby", "compressor"} <= set(groups)
        assert groups["compressor"].n_held == 3
        assert len(held.recoveries) == 3
        for j in judged:
            if j.kept == "refit":
                assert j.base_error is not None and j.refit_error is not None
                assert j.refit_error < j.base_error
            elif "pinned" not in j.why and j.refit_error is not None:
                assert j.base_error is not None
                assert j.base_error <= j.refit_error
        done = sc.Calibrated(
            fitted,
            "constant",
            len(frame),
            timedelta(minutes=5),
            0,
            (),
            judged=judged,
            held=held,
        )
        assert set(sc.score(done, base)) == set(sc.GROUPS)
        # The compressor is judged against the loss kept before it: the
        # parameters it ends in.
        if groups["compressor"].kept == "base":
            assert sc.score(done, fitted.params)["compressor"] == (
                pytest.approx(groups["compressor"].base_error)
            )
        names = {t.name for t in sc.report(done)}
        assert "Compressor constant" in names


class TestKeepBetterFirstReview:
    def test_a_law_is_scored_at_its_own_reference(self) -> None:
        hours = np.linspace(0.0, 4.0, 49)
        window = cal.StandbyWindow(
            start=T0,
            end=T0 + timedelta(hours=4),
            ua_btu_hr_f=7.0,
            rmse_f=0.1,
            delta_t_mean_f=40.0,
            duration_hours=4.0,
            gap_hours=hours,
            gap_f=np.zeros(49),
            upper_f=100.0 - 0.6 * hours,
            lower_f=100.0 - 0.6 * hours,
            air_f=np.full(49, 60.0),
        )
        u30, e = 6.0, 0.3
        base = sim.default_params()
        loss = replace(
            base.loss, ua_btu_hr_f=u30, ua_exponent=e, ua_ref_delta_t_f=30.0
        )
        # The same law, quoted at 50 °F.
        same = replace(loss, ua_btu_hr_f=u30 * (50 / 30) ** e)
        same = replace(same, ua_ref_delta_t_f=50.0)
        at = sc._loss_error([window], loss, 60.0, base.tank)
        assert at == pytest.approx(
            sc._loss_error([window], same, 60.0, base.tank)
        )
        assert at != pytest.approx(
            sc._loss_error(
                [window], replace(loss, ua_ref_delta_t_f=50.0), 60.0, base.tank
            )
        )

    def test_a_refit_law_takes_its_own_reference(self) -> None:
        base = sim.default_params()
        base = replace(base, loss=replace(base.loss, ua_ref_delta_t_f=30.0))
        fit = cal.StandbyFit(
            windows=(),
            n_quiet=0,
            n_dropped=0,
            ua_ref=6.0,
            ua_exponent=0.2,
            tau_gap_hours=None,
            n_gap_windows=0,
            quiet_by="dhw_in_use",
        )
        loss = cal.with_standby(base, fit).loss
        assert (loss.ua_btu_hr_f, loss.ua_ref_delta_t_f) == (6.0, 50.0)

    def test_power_and_cop_hold_out_their_own_cycles(self) -> None:
        frame = recovery_days(14)
        base = sim.default_params()
        fitted, judged, held = sc._keep_better(frame, base, "air_f")
        groups = {j.group: j for j in judged}
        # A draw leads every cycle: none is the COP's, all the power's.
        assert groups["cop"].n_held == 0
        assert held.cop_cycles.empty
        assert groups["power_scale"].n_held == 3
        starts = held.power_cycles["start_time"].unique()
        assert len(starts) == 3
        done = sc.Calibrated(
            fitted,
            "constant",
            len(frame),
            timedelta(minutes=5),
            0,
            (),
            judged=judged,
            held=held,
        )
        # A kept base shows its values, and the refit's own reason.
        cop = {t.name: t for t in sc.report(done)}["COP scale"]
        assert cop.value == f"{base.power.cop_scale:.3g}"
        assert not cop.fitted
        assert cop.why == (
            "kept the base: too few cycles to refit on (10 needed)"
        )


class TestKeepBetterSecondReview:
    def test_every_kept_group_is_judged_and_reported(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        # Quiet days only: nothing to refit the gap, compressor or power
        # on, so each keeps the base and says why.
        readings = days_of_quiet(device_status_dict, [UA] * 4)
        base = _fitted(12.0)
        done = sc.calibrate(
            readings, ambient=AIR_F, params=base, keep_better=True
        )
        judged = {j.group: j for j in done.judged}
        assert set(judged) == set(sc.GROUPS)
        assert all(j.kept == "base" for j in judged.values())
        assert done.calibration.params.compressor == base.compressor
        assert done.calibration.params.power == base.power
        assert judged["compressor"].why == (
            "kept the base: too few reached recoveries to refit on (5 needed)"
        )
        assert judged["gap_tau"].why == (
            "kept the base: too few windows that open a gap to refit on "
            "(20 needed)"
        )
        terms = _terms(done)
        for name, value in (
            ("Compressor constant", base.compressor.compressor_constant),
            ("Zone gap time constant (h)", base.tank.stratification_gap_tau_h),
            ("COP scale", base.power.cop_scale),
        ):
            assert terms[name].value == f"{value:.3g}"
            assert terms[name].why.startswith("kept the base: ")

    def test_an_unfitted_group_is_refitted_on_all_its_evidence(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        readings = days_of_quiet(device_status_dict, [UA] * 12)
        base = sim.default_params()
        base = replace(base, unfitted=(*base.unfitted, "standby"))
        done = sc.calibrate(
            readings, ambient=AIR_F, params=base, keep_better=True
        )
        assert done.held is not None
        assert done.held.windows == ()
        plain = sc.calibrate(readings, ambient=AIR_F, params=base)
        assert done.calibration.params.loss == plain.calibration.params.loss


class TestKeepBetterThirdReview:
    def test_windows_the_law_cannot_use_are_not_its_evidence(self) -> None:
        def window(day: int, delta_t: float) -> cal.StandbyWindow:
            return cal.StandbyWindow(
                start=T0 + timedelta(days=day),
                end=T0 + timedelta(days=day, hours=4),
                ua_btu_hr_f=UA,
                rmse_f=0.1,
                delta_t_mean_f=delta_t,
                duration_hours=4.0,
                gap_hours=np.zeros(2),
                gap_f=np.zeros(2),
            )

        # Eight windows with the tank at or below the air, then two the
        # law can use: too few to judge by, and no error from a refit
        # on none.
        windows = tuple(
            [window(d, 0.0) for d in range(8)]
            + [window(d, 50.0) for d in (8, 9)]
        )
        fit = cal.StandbyFit(
            windows=windows,
            n_quiet=10,
            n_dropped=0,
            ua_ref=UA,
            ua_exponent=0.0,
            tau_gap_hours=None,
            n_gap_windows=0,
            quiet_by="dhw_in_use",
        )
        base = _fitted(12.0)
        frame = recovery_days(1)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(cal, "fit_standby", lambda *_, **__: fit)
            _, judged, held = sc._keep_better(frame, base, "air_f")
        (standby,) = [j for j in judged if j.group == "standby"]
        assert standby.n_held == 0
        assert held.windows == ()

    def test_a_power_refit_that_wins_drops_the_compressors_reason(
        self, pinned_compressor: None
    ) -> None:
        frame = recovery_days(14)
        fitted, judged, held = sc._keep_better(
            frame, sim.default_params(), "air_f"
        )
        groups = {j.group: j for j in judged}
        assert groups["compressor"].kept == "base"
        assert groups["power_scale"].kept == "refit"
        done = sc.Calibrated(
            fitted,
            "constant",
            len(frame),
            timedelta(minutes=5),
            0,
            (),
            judged=judged,
            held=held,
        )
        term = _terms(done)["Input power scale"]
        assert term.fitted
        assert term.why == ""
        assert "against the base's" in term.note


class TestKeepBetterFourthReview:
    def test_the_cop_is_the_heaters_own_tanks(self) -> None:
        from nwp500.sim.heating_trajectory import path_cop

        base = sim.default_params()
        params = replace(base, tank=replace(base.tank, volume_gal=40.0))
        rows = cal.snapshots(recovery_days(3), air="air_f")
        cycles = cal.cop_cycles(rows, params, withdrawn=lambda _: 0.0)
        assert cycles
        row = rows.loc[rows["offset_minutes"] == 0.0].iloc[0].to_dict()
        path = cal.path_to_end(row, params)
        assert path is not None
        assert cycles[0].modelled_cop == pytest.approx(
            path_cop(
                path,
                0.0,
                path.elapsed_s[-1],
                params.compressor.two_zone,
                float(row["t_start_upper"]),
                tank=params.tank,
            )
        )

    def test_power_fitted_over_a_kept_compressor_has_no_failure_reason(
        self, pinned_compressor: None
    ) -> None:
        # The compressor's refit is pinned, so the base's is kept; the
        # power, unfitted in the base, is fitted over it.
        frame = recovery_days(14)
        base = sim.default_params()
        base = replace(base, unfitted=(*base.unfitted, "power"))
        fitted, judged, held = sc._keep_better(frame, base, "air_f")
        assert {j.group: j.kept for j in judged}["compressor"] == "base"
        assert fitted.power is not None
        assert fitted.power.power_scale is not None
        done = sc.Calibrated(
            fitted,
            "constant",
            len(frame),
            timedelta(minutes=5),
            0,
            (),
            judged=judged,
            held=held,
        )
        term = _terms(done)["Input power scale"]
        assert term.fitted
        assert term.why == ""


class TestKeepBetterFifthReview:
    def test_a_score_needs_every_held_out_cycle_modelled(self) -> None:
        params = sim.default_params()
        rows = cal.snapshots(recovery_days(3), air="air_f")
        whole = cal.power_cycles(rows, params)
        assert len(whole) == 3
        assert sc._power_error(rows, params) is not None
        cop = cal.CopCycle(T0, 1000.0, 0.0, 3.0, 500.0, 60.0)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(cal, "power_cycles", lambda *_: whole[:2])
            m.setattr(cal, "cop_cycles", lambda *_: [cop, cop])
            assert sc._power_error(rows, params) is None
            assert sc._cop_error(rows, params) is None
            m.setattr(cal, "cop_cycles", lambda *_: [cop] * 3)
            assert sc._cop_error(rows, params) is not None

    def test_a_kept_compressor_shows_no_refit_error(
        self, pinned_compressor: None
    ) -> None:
        frame = recovery_days(14)
        fitted, judged, held = sc._keep_better(
            frame, sim.default_params(), "air_f"
        )
        assert {j.group: j.kept for j in judged}["compressor"] == "base"
        done = sc.Calibrated(
            fitted,
            "constant",
            len(frame),
            timedelta(minutes=5),
            0,
            (),
            judged=judged,
            held=held,
        )
        terms = _terms(done)
        assert terms["Compressor constant"].error == "-"
        approach = terms["Evaporator approach (°F)"]
        assert not approach.fitted and approach.error == "-"
        assert approach.value == sc._num(
            fitted.params.compressor.evap_approach_f
        )


def gap_windows(taus: list[float]) -> tuple[cal.StandbyWindow, ...]:
    """A quiet window a day for each of ``taus``: a 6 °F zone gap
    relaxing on that time constant over 6 h, the loss steady at ``UA``."""
    hours = np.linspace(0.0, 6.0, 37)
    return tuple(
        cal.StandbyWindow(
            start=T0 + timedelta(days=d),
            end=T0 + timedelta(days=d, hours=6),
            ua_btu_hr_f=UA,
            rmse_f=0.1,
            delta_t_mean_f=50.0,
            duration_hours=6.0,
            gap_hours=hours,
            gap_f=6.0 * np.exp(-hours / tau),
        )
        for d, tau in enumerate(taus)
    )


def _keep_gap(
    windows: tuple[cal.StandbyWindow, ...], base: sim.HeaterParams
) -> tuple[sim.HeaterParams, sc.Judged, sc.HeldOut]:
    """``_keep_better`` over ``windows``' standby, the gap's judgement."""
    fit = cal.StandbyFit(
        windows=windows,
        n_quiet=len(windows),
        n_dropped=0,
        ua_ref=UA,
        ua_exponent=0.0,
        tau_gap_hours=None,
        n_gap_windows=0,
        quiet_by="dhw_in_use",
    )
    with pytest.MonkeyPatch.context() as m:
        m.setattr(cal, "fit_standby", lambda *_, **__: fit)
        done, judged, held = sc._keep_better(recovery_days(1), base, "air_f")
    (gap,) = [j for j in judged if j.group == "gap_tau"]
    return done.params, gap, held


def _with_tau(tau: float) -> sim.HeaterParams:
    base = _fitted(UA)
    return replace(base, tank=replace(base.tank, stratification_gap_tau_h=tau))


#: The COP law the synthetic cycles follow, and another.
COP_LAW = (0.8, 120.0, 0.01)
OTHER_COP_LAW = (1.3, 40.0, 0.002)


def cop_cycles_by(law_at: Any) -> Any:
    """A stand-in for ``cop_cycles``: a cycle for each of the rows'
    cycles, its metered energy what ``law_at(start)``'s ``(scale,
    start-up Wh, lift coefficient)`` says."""

    def cycles(rows: Any, params: sim.HeaterParams, **_: Any) -> Any:
        starts = rows.loc[rows["offset_minutes"] == 0.0]["start_time"]
        out = []
        for t in sorted(set(starts)):
            day = (t - T0).days
            heat = 3000.0 + 150 * (day % 4)
            lift, cop = 40.0 + 6 * (day % 5), 3.0
            scale, startup, k = law_at(t)
            ref = params.power.cop_lift_ref_f
            metered = startup + heat / (
                scale * cop * float(np.exp(-k * (lift - ref)))
            )
            out.append(cal.CopCycle(t, heat, 0.0, cop, metered, lift))
        return out

    return cycles


def _keep_cop(
    law_at: Any, base: sim.HeaterParams
) -> tuple[sim.HeaterParams, dict[str, sc.Judged], sc.HeldOut]:
    with pytest.MonkeyPatch.context() as m:
        m.setattr(cal, "cop_cycles", cop_cycles_by(law_at))
        done, judged, held = sc._keep_better(recovery_days(14), base, "air_f")
    return done.params, {j.group: j for j in judged}, held


def _with_cop(law: tuple[float, float, float]) -> sim.HeaterParams:
    base = sim.default_params()
    scale, startup, k = law
    return replace(
        base,
        power=replace(
            base.power, cop_scale=scale, startup_wh=startup, cop_lift_coeff=k
        ),
    )


class TestKeepBetterSixthReview:
    def test_a_gap_refit_that_scores_better_replaces_the_base(self) -> None:
        params, gap, held = _keep_gap(gap_windows([4.0] * 26), _with_tau(1.0))
        assert gap.kept == "refit"
        assert gap.n_held == 5 == len(held.gap_windows)
        assert gap.base_error is not None and gap.refit_error is not None
        assert gap.refit_error < gap.base_error
        assert params.tank.stratification_gap_tau_h == pytest.approx(
            4.0, rel=0.01
        )

    def test_a_gap_base_the_latest_windows_favour_stays(self) -> None:
        windows = gap_windows([1.0] * 21 + [4.0] * 5)
        params, gap, held = _keep_gap(windows, _with_tau(4.0))
        assert gap.kept == "base"
        assert len(held.gap_windows) == 5
        assert gap.base_error is not None and gap.refit_error is not None
        assert gap.base_error < gap.refit_error
        assert params.tank.stratification_gap_tau_h == 4.0

    def test_a_cop_refit_that_scores_better_replaces_the_base(self) -> None:
        base = _with_cop(OTHER_COP_LAW)
        params, judged, held = _keep_cop(lambda _: COP_LAW, base)
        cop = judged["cop"]
        assert cop.kept == "refit"
        assert cop.n_held == 3
        assert held.cop_cycles["cycle"].nunique() == 3
        assert cop.base_error is not None and cop.refit_error is not None
        assert cop.refit_error < cop.base_error
        scale, startup, k = COP_LAW
        assert params.power.cop_scale == pytest.approx(scale, rel=1e-3)
        assert params.power.startup_wh == pytest.approx(startup, abs=0.5)
        assert params.power.cop_lift_coeff == pytest.approx(k)
        # The power scale is judged on its own.
        assert judged["power_scale"].kept == "refit"
        assert params.power.power_scale != base.power.power_scale

    def test_a_cop_base_the_latest_cycles_favour_stays(self) -> None:
        # The refit learns the other law from the earlier cycles; the
        # latest follow the base's.
        last = T0 + timedelta(days=11)
        base = _with_cop(COP_LAW)
        params, judged, _ = _keep_cop(
            lambda t: COP_LAW if t >= last else OTHER_COP_LAW, base
        )
        cop = judged["cop"]
        assert cop.kept == "base"
        assert cop.base_error is not None and cop.refit_error is not None
        assert cop.base_error < cop.refit_error
        assert (
            params.power.cop_scale,
            params.power.startup_wh,
            params.power.cop_lift_coeff,
        ) == COP_LAW
        assert judged["power_scale"].kept == "refit"
        assert params.power.power_scale != base.power.power_scale


def physics_recoveries(
    params: sim.HeaterParams, law_at: Any, n: int = 14
) -> Any:
    """``n`` reached recoveries a day apart, each lasting what the
    physics says under ``law_at(day)``'s ``(compressor constant,
    evaporator approach)`` on ``params``' loss and tank."""
    import pandas as pd

    frame = pd.DataFrame(
        {
            "start_time": [T0 + timedelta(days=d) for d in range(n)],
            "t_start_lower": [95.0 + 3 * (d % 5) for d in range(n)],
            "delta_t_lower": [30.0 + 4 * (d % 4) for d in range(n)],
            "t_amb_mean": [55.0 + 3 * (d % 6) for d in range(n)],
            "h_amb_start": [50.0] * n,
            "stratification_gap": [8.0 + (d % 3) for d in range(n)],
            "reached": [True] * n,
        }
    )
    minutes = [
        cal.recovery_minutes(
            frame.iloc[[d]],
            *law_at(d),
            compressor=params.compressor,
            loss=params.loss,
            tank=params.tank,
            two_zone=True,
            gaps=True,
        )[0]
        for d in range(n)
    ]
    return frame.assign(duration_minutes=minutes)


#: Two compressor laws whose recoveries the fit leaves off its bounds.
COMPRESSOR_LAW = (0.025, 9.0)
OTHER_COMPRESSOR_LAW = (0.019, 14.0)


def _keep_compressor(
    law_at: Any, base_law: tuple[float, float]
) -> tuple[cal.Calibration, sc.Judged, sc.HeldOut, sim.HeaterParams]:
    """``_keep_better`` on a base with ``base_law`` and recoveries under
    ``law_at``: the calibration, the compressor's judgement, what was
    held out, and the base."""
    base = _fitted(UA)
    k, approach = base_law
    base = replace(
        base,
        compressor=replace(
            base.compressor,
            compressor_constant=k,
            evap_approach_f=approach,
            two_zone=False,
        ),
    )
    found = physics_recoveries(base, law_at)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(cal, "recoveries", lambda *_, **__: found)
        done, judged, held = sc._keep_better(recovery_days(1), base, "air_f")
    (comp,) = [j for j in judged if j.group == "compressor"]
    return done, comp, held, base


class TestKeepBetterSeventhReview:
    def test_an_unpinned_compressor_refit_that_scores_better_wins(
        self,
    ) -> None:
        done, comp, held, base = _keep_compressor(
            lambda _: COMPRESSOR_LAW, OTHER_COMPRESSOR_LAW
        )
        params, refit = done.params, done.compressor
        assert refit is not None and not refit.hit_bounds
        assert comp.kept == "refit"
        assert comp.n_held == 3 == len(held.recoveries)
        assert comp.base_error is not None and comp.refit_error is not None
        assert comp.refit_error < comp.base_error
        # The base's error is on the loss kept before it.
        assert params.loss == base.loss
        assert sc._recovery_error(held.recoveries, base) == pytest.approx(
            comp.base_error
        )
        assert comp.refit_error == refit.heldout_mae_minutes
        c = params.compressor
        assert (c.compressor_constant, c.evap_approach_f, c.two_zone) == (
            refit.compressor_constant,
            refit.evap_approach_f,
            True,
        )
        assert c.compressor_constant != base.compressor.compressor_constant

    def test_a_compressor_base_the_latest_recoveries_favour_stays(
        self,
    ) -> None:
        done, comp, _, base = _keep_compressor(
            lambda d: COMPRESSOR_LAW if d >= 11 else OTHER_COMPRESSOR_LAW,
            COMPRESSOR_LAW,
        )
        params, refit = done.params, done.compressor
        assert refit is not None and not refit.hit_bounds
        assert comp.kept == "base"
        assert "pinned" not in comp.why
        assert comp.base_error is not None and comp.refit_error is not None
        assert comp.base_error < comp.refit_error
        assert params.compressor == base.compressor
        assert not params.compressor.two_zone


class TestAPartialAirRecordKeepsRecoveries:
    def test_each_recovery_outside_it_reads_the_heaters_air(self) -> None:
        from nwp500 import sim_home_assistant as ha

        frame = recovery_days(6).drop(columns=["air_f"])
        base = sim.default_params()
        alone = sc._fit(frame.copy(), base, [], None, None, None, None)
        # An air record over the last day only.
        last = frame.index[-1].to_pydatetime()
        record = ha.RecordInputs(
            air=[(last - timedelta(days=1), 60.0), (last, 60.0)],
            humidity=None,
            drawing=None,
            circulating=None,
        )
        partial = sc._fit(frame.copy(), base, [], None, None, None, record)
        assert len(alone.calibration.recoveries) == 6
        assert len(partial.calibration.recoveries) == 6

    def test_heater_air_missing_early_in_a_run_keeps_it(self) -> None:
        import numpy as np

        from nwp500 import sim_home_assistant as ha

        frame = recovery_days(6).drop(columns=["air_f"])
        on = frame["compressor_on"].to_numpy(dtype=bool)
        # Each run's first five minutes have no air reading yet.
        starts = np.flatnonzero(on & ~np.roll(on, 1))
        for i in starts:
            frame.iloc[i : i + 5, frame.columns.get_loc("heater_air_f")] = (
                np.nan
            )
        base = sim.default_params()
        alone = sc._fit(frame.copy(), base, [], None, None, None, None)
        last = frame.index[-1].to_pydatetime()
        record = ha.RecordInputs(
            air=[(last - timedelta(days=1), 60.0), (last, 60.0)],
            humidity=None,
            drawing=None,
            circulating=None,
        )
        partial = sc._fit(frame.copy(), base, [], None, None, None, record)
        assert len(alone.calibration.recoveries) > 0
        assert len(partial.calibration.recoveries) == len(
            alone.calibration.recoveries
        )


class TestStandbyOnTheHeatersAir:
    def test_with_no_air_given_it_fits_on_the_heaters(self) -> None:
        frame = recovery_days(6)
        base = sim.default_params()
        # The fixture's loss is constant: its exponent, held, is 0.
        base = replace(base, loss=replace(base.loss, ua_exponent=0.0))
        readings = [
            (cast(datetime, t.to_pydatetime()), float(v))
            for t, v in frame["air_f"].items()
        ]
        heater_only = frame.drop(columns=["air_f"])
        given = sc._fit(
            heater_only.copy(), base, [], readings, None, None, None
        )
        own = sc._fit(heater_only.copy(), base, [], None, None, None, None)
        assert given.air == "readings"
        assert own.air == "heater"
        assert given.calibration.standby.ua_ref is not None
        assert own.calibration.standby.ua_ref is not None
        # The fixture's air steps at midnight, and the heater's is drawn
        # straight from one evening's run to the next: within 5 %.
        assert own.calibration.standby.ua_ref == pytest.approx(
            given.calibration.standby.ua_ref, rel=0.05
        )
        assert sc.NO_AIR_NOTE not in own.notes
        assert any(
            "heater's own air" in n and "of their hours" in n for n in own.notes
        )

    def test_on_the_heaters_air_the_exponent_is_the_bases(self) -> None:
        frame = recovery_days(6).drop(columns=["air_f"])
        base = sim.default_params()
        base = replace(base, loss=replace(base.loss, ua_exponent=0.28))
        done = sc._fit(frame, base, [], None, None, None, None)
        standby = done.calibration.standby
        assert standby.ua_ref is not None
        assert standby.ua_exponent == pytest.approx(0.28)

    def test_between_runs_the_air_is_interpolated(self) -> None:
        frame = recovery_days(3).drop(columns=["air_f"])
        assert sc._air_between_runs(frame) is not None
        # Day 1's quiet decay, between day 0's run (air 60) and day 1's
        # (60 + 5 sin 1): a straight line from one to the other.
        day = frame.index[0] + timedelta(days=1)
        a, b = day - timedelta(hours=6), day + timedelta(hours=6)
        mid = frame.loc[a:b, "air_f"].dropna()
        assert len(mid) > 0
        assert mid.is_monotonic_increasing
        assert 60.0 < mid.iloc[len(mid) // 2] < 60.0 + 5.0 * np.sin(1.0)

    def test_a_window_without_a_run_at_both_ends_is_not_fitted(self) -> None:
        frame = recovery_days(6).drop(columns=["air_f"])
        # The heater read its air on the first day's run only.
        later = frame.index >= frame.index[0] + timedelta(days=1)
        frame.loc[later, "heater_air_f"] = np.nan
        done = sc._fit(frame, sim.default_params(), [], None, None, None, None)
        assert done.air == "heater"
        assert done.calibration.standby.ua_ref is None
        why = {t.name: t.why for t in sc.report(done)}
        assert any(
            "no quiet window has a run within 6 h of both ends" in w
            for w in why.values()
        )

    def test_a_run_heard_again_partway_settles_from_then(self) -> None:
        frame = recovery_days(3).drop(columns=["air_f"])
        on = frame["compressor_on"].to_numpy(dtype=bool)
        starts = np.flatnonzero(on & ~np.roll(on, 1))
        frame["unrecorded"] = False
        unrecorded = frame.columns.get_loc("unrecorded")
        air = frame.columns.get_loc("heater_air_f")
        for i in starts:
            # Unrecorded for the run's first 3 minutes, then its startup
            # air, warm, for 4 more.
            frame.iloc[i : i + 3, unrecorded] = True
            frame.iloc[i + 3 : i + 7, air] = 95.0
        assert sc._air_between_runs(frame) is not None
        assert frame["air_f"].max() < 90.0

    def test_a_run_excluded_from_the_recoveries_still_reads_it(self) -> None:
        """A hybrid mode's samples are excluded from the recoveries, not
        unrecorded: their runs still give the air."""
        frame = recovery_days(6).drop(columns=["air_f"])
        frame["excluded"] = True
        done = sc._fit(frame, sim.default_params(), [], None, None, None, None)
        assert done.air == "heater"
