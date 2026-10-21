"""``nwp500.sim_calibrate``: a recorded history in, the fitted
parameters and a report of each fit out."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("pandas")
pytest.importorskip("scipy")

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

    def test_a_bad_document_is_refused(self, history: str) -> None:
        with pytest.raises(sc.CalibrationInputError, match="parameters"):
            sc.calibrate(_read(history), params={"tank": "no"})

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
