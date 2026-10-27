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
from nwp500.sim import heat_pump_fit as hpf
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

    def test_without_air_the_standby_loss_is_fitted_on_the_cabinet(
        self, history: str
    ) -> None:
        done = sc.calibrate(_read(history))
        assert done.air == "heater"
        assert "standby" not in done.calibration.params.unfitted
        assert _terms(done)["Standby loss (UA at ref ΔT, BTU/h·°F)"].fitted
        assert any("compressor is idle" in n for n in done.notes)

    def test_each_fit_without_evidence_says_why(self, history: str) -> None:
        terms = _terms(sc.calibrate(_read(history), ambient=AIR_F))
        exponent = terms["Standby loss exponent"]
        # Applied, not kept: the fit replaces the base's exponent with 0.
        assert exponent.fitted and exponent.value == "0"
        assert "a constant loss" in exponent.note
        assert "two 20 °F bands" in exponent.note
        assert "20 needed" in terms["Zone gap time constant (h)"].why
        heat = terms["Heat at 65 °F air, 120 °F water (BTU/h)"]
        assert not heat.fitted
        assert heat.why == ("0 draw-free climbs with the tank mixed; 10 needed")
        power = terms["Power at 65 °F air, 120 °F water (W)"]
        assert not power.fitted
        assert power.why == "0 metered climb blocks; 30 needed"

    def test_a_heat_pump_fit_reports_its_values_and_errors(
        self, history: str
    ) -> None:
        done = sc.calibrate(_read(history), ambient=AIR_F)
        fit = hpf.HeatPumpFit(
            heat=hpf.Plane(4400.0, 50.0, -15.0),
            power=None,
            start_hold_min=(0.0, 4.0, 9.0, 17.0, 21.0),
            overshoot_f=None,
            n_heat=12,
            n_power=4,
            n_holds=40,
            n_runs=2,
            heat_error=210.0,
            power_error=None,
        )
        params = hpf.with_heat_pump(done.calibration.params, fit)
        fitted = replace(
            done,
            calibration=replace(done.calibration, params=params, heat_pump=fit),
        )
        terms = _terms(fitted)
        heat = terms["Heat at 65 °F air, 120 °F water (BTU/h)"]
        assert heat.fitted and heat.value == "4400"
        assert heat.samples == "12 climbs"
        assert heat.error == "210 BTU/h rms"
        power = terms["Power at 65 °F air, 120 °F water (W)"]
        assert not power.fitted
        assert power.why == "4 metered climb blocks; 30 needed"
        hold = terms["Start hold by time off (min)"]
        assert hold.fitted and hold.value == "0/4/9/17/21"
        assert hold.note == "under 15, 60, 180, 720 min off, and beyond"
        assert not terms["Run-on overshoot (°F)"].fitted
        claims = replace(
            fitted,
            calibration=replace(
                fitted.calibration,
                heat_pump=replace(fit, violations=("cop_over_carnot",)),
            ),
        )
        heat = _terms(claims)["Heat at 65 °F air, 120 °F water (BTU/h)"]
        assert not heat.fitted
        assert "claims what no heat pump does (cop_over_carnot)" in heat.why

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
        assert done.notes[0] == sc.DEFAULT_BASE_NOTE
        assert len(done.notes) == 2
        assert "compressor is idle" in done.notes[1]
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
    """The defaults with a standby loss of ``ua``, taken as fitted, no
    bottom loss and a gap that relaxes on 60 h."""
    base = sim.default_params()
    return replace(
        base,
        tank=replace(base.tank, stratification_gap_tau_h=60.0),
        loss=replace(
            base.loss,
            ua_btu_hr_f=ua,
            ua_exponent=0.0,
            bottom_loss_btu_hr=0.0,
            bottom_gate_f=1.0,
        ),
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
        win = sc._judge("heat_map", "recovery climbs", 3, 9.0, 4.0)
        assert (win.kept, win.why) == ("refit", "")
        tie = sc._judge("heat_map", "recovery climbs", 3, 4.0, 4.0)
        assert tie.kept == "base"
        assert tie.why == (
            "kept the base: it scores 4 against the refit's 4 on the 3 "
            "latest recovery climbs"
        )
        unscored = sc._judge("run_on", "run-ons", 3, 1.0, None)
        assert unscored.kept == "base"
        assert "the refit has no score" in unscored.why
        none_held = sc._judge("run_on", "run-ons", 0, None, None)
        assert none_held.why == (
            "kept the base: under 10 run-ons to judge a refit by"
        )
        no_refit = sc._judge(
            "run_on", "run-ons", 3, 1.0, None, refit_exists=False, needed=5
        )
        assert no_refit.kept == "base"
        assert no_refit.why == (
            "kept the base: too few run-ons to refit on (5 needed)"
        )

    def test_the_split_is_the_recoveries(self) -> None:
        assert [sc._split(n) for n in (9, 10, 12, 20, 50)] == [0, 2, 2, 4, 10]


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
                    "heater_cabinet_f": np.where(
                        comp, np.nan, air + sa.IDLE_CABINET_WARM_F
                    ),
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
        assert {"standby", "heat_map", "power_map"} <= set(groups)
        # A draw leads every run: no climb or start is clean, but every
        # run's blocks are metered.
        assert "too few recovery climbs" in groups["heat_map"].why
        assert groups["power_map"].n_held == len(held.heat_pump.power) > 0
        for j in judged:
            if j.kept == "refit":
                assert j.base_error is not None and j.refit_error is not None
                assert j.refit_error < j.base_error
            elif j.refit_error is not None:
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
        if groups["power_map"].kept == "base":
            assert sc.score(done, fitted.params)["power_map"] == (
                pytest.approx(groups["power_map"].base_error)
            )
        names = {t.name for t in sc.report(done)}
        assert "Heat at 65 °F air, 120 °F water (BTU/h)" in names


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
        assert judged["heat_map"].why == (
            "kept the base: too few recovery climbs to refit on (10 needed)"
        )
        assert judged["gap_tau"].why == (
            "kept the base: too few windows that open a gap to refit on "
            "(20 needed)"
        )
        terms = _terms(done)
        for name, value in (
            (
                "Heat at 65 °F air, 120 °F water (BTU/h)",
                f"{base.compressor.heat_btu_h:.4g}",
            ),
            (
                "Zone gap time constant (h)",
                f"{base.tank.stratification_gap_tau_h:.3g}",
            ),
            (
                "Power at 65 °F air, 120 °F water (W)",
                f"{base.compressor.power_w:.3g}",
            ),
            ("Start hold by time off (min)", "0/5/10/18/22"),
        ):
            assert terms[name].value == value
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


#: Two heat pumps the planted evidence follows: the heat's and the
#: power's planes, the hold by time off, and the overshoot.
PUMP_A = (
    hpf.Plane(4500.0, 55.0, -16.0),
    hpf.Plane(400.0, 0.2, 2.8),
    (0.0, 5.0, 10.0, 18.0, 22.0),
    0.9,
)
PUMP_B = (
    hpf.Plane(3900.0, 30.0, -5.0),
    hpf.Plane(460.0, 1.0, 1.5),
    (2.0, 8.0, 14.0, 25.0, 30.0),
    1.8,
)


def planted_evidence(law_at: Any, n: int = 50) -> hpf.Evidence:
    """``n`` of each of the heat pump's measures a day apart, each what
    ``law_at(day)`` (a ``PUMP_*``) gives: a climb, a metered block, a
    clean start and a run-on."""
    import pandas as pd

    days = range(n)
    starts = [T0 + timedelta(days=d) for d in days]
    air = [55.0 + 3 * (d % 7) for d in days]
    water = [118.0 + 4 * (d % 6) for d in days]
    lower = [80.0 + 11 * (d % 6) for d in days]
    off = [5.0, 30.0, 100.0, 300.0, 1000.0]
    law = [law_at(d) for d in days]

    def at(plane: hpf.Plane, a: float, w: float) -> float:
        return (
            plane.level + plane.per_air * (a - 65) + plane.per_water * (w - 120)
        )

    heat = pd.DataFrame(
        {
            "start": starts,
            "minutes": 30,
            "air_f": air,
            "water_f": water,
            "heat_btu_h": [
                at(x[0], a, w) for x, a, w in zip(law, air, water, strict=True)
            ],
        }
    )
    power = pd.DataFrame(
        {
            "start": starts,
            "air_f": air,
            "lower_f": lower,
            "power_w": [
                at(x[1], a, w) for x, a, w in zip(law, air, lower, strict=True)
            ],
        }
    )
    holds = pd.DataFrame(
        {
            "start": starts,
            "minutes_off": [off[d % 5] for d in days],
            "hold_minutes": [law[d][2][d % 5] for d in days],
        }
    )
    runs = pd.DataFrame({"start": starts, "overshoot_f": [x[3] for x in law]})
    return hpf.Evidence(heat, power, holds, runs)


def _with_pump(pump: Any, unfitted: tuple[str, ...] = ()) -> sim.HeaterParams:
    heat, power, hold, over = pump
    base = _fitted(UA)
    return replace(
        base,
        compressor=replace(
            hpf.with_planes(base.compressor, heat, power),
            start_hold_min=hold,
        ),
        controller=replace(base.controller, hp_stop_overshoot_f=over),
        unfitted=unfitted,
    )


def _keep_pump(
    law_at: Any, base: sim.HeaterParams
) -> tuple[sim.HeaterParams, dict[str, sc.Judged], sc.HeldOut]:
    found = planted_evidence(law_at)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(hpf, "evidence", lambda *_, **__: found)
        done, judged, held = sc._keep_better(recovery_days(1), base, "air_f")
    return done.params, {j.group: j for j in judged}, held


PUMP_GROUPS = ("heat_map", "power_map", "start_hold", "run_on")


class TestKeepBetterTheHeatPump:
    def test_each_refit_that_scores_better_replaces_the_base(self) -> None:
        params, judged, held = _keep_pump(lambda _: PUMP_A, _with_pump(PUMP_B))
        for group in PUMP_GROUPS:
            j = judged[group]
            assert j.kept == "refit", group
            assert j.n_held == 10
            assert j.base_error is not None and j.refit_error is not None
            assert j.refit_error < j.base_error
        assert len(held.heat_pump.heat) == len(held.heat_pump.runs) == 10
        c = params.compressor
        assert c.heat_btu_h == pytest.approx(4500.0)
        assert c.heat_btu_h_per_water_f == pytest.approx(-16.0)
        assert c.power_w == pytest.approx(400.0)
        assert c.start_hold_min == (0.0, 5.0, 10.0, 18.0, 22.0)
        assert params.controller.hp_stop_overshoot_f == 0.9

    def test_a_base_the_latest_evidence_favours_stays(self) -> None:
        # The refit learns the other pump from the earlier days; the
        # latest follow the base's.
        base = _with_pump(PUMP_A)
        params, judged, _ = _keep_pump(
            lambda d: PUMP_A if d >= 40 else PUMP_B, base
        )
        for group in PUMP_GROUPS:
            assert judged[group].kept == "base", group
        assert params.compressor == base.compressor
        assert params.controller == base.controller

    def test_a_refit_that_claims_too_much_is_not_applied(self) -> None:
        # Three times the heat for the same power: a COP over the share
        # of Carnot's the map may claim.
        greedy = (hpf.Plane(13500.0, 55.0, -16.0), *PUMP_A[1:])
        base = _with_pump(PUMP_A)
        params, judged, _ = _keep_pump(lambda _: greedy, base)
        for group in ("heat_map", "power_map"):
            assert judged[group].kept == "base"
            assert "cop_over_carnot" in judged[group].why
        assert params.compressor.heat_btu_h == base.compressor.heat_btu_h

    def test_an_unfitted_heat_pump_takes_its_refit_unjudged(self) -> None:
        base = _with_pump(PUMP_B, unfitted=("compressor", "power"))
        params, judged, held = _keep_pump(lambda _: PUMP_A, base)
        assert not set(PUMP_GROUPS) & set(judged)
        assert held.heat_pump.heat.empty and held.heat_pump.power.empty
        assert params.compressor.heat_btu_h == pytest.approx(4500.0)
        assert params.controller.hp_stop_overshoot_f == 0.9
        assert {"compressor", "power"}.isdisjoint(params.unfitted)


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
        # The fixture's cabinet reads its air plus the cabinet's warmth:
        # each window's loss is the one on the air given.
        assert [w.ua_btu_hr_f for w in own.calibration.standby.windows] == (
            pytest.approx(
                [w.ua_btu_hr_f for w in given.calibration.standby.windows]
            )
        )
        assert sc.NO_AIR_NOTE not in own.notes
        assert any(
            "compressor is idle" in n and "of their hours" in n
            for n in own.notes
        )

    def test_on_the_heaters_air_the_exponent_is_the_bases(self) -> None:
        frame = recovery_days(6).drop(columns=["air_f"])
        base = sim.default_params()
        base = replace(base, loss=replace(base.loss, ua_exponent=0.28))
        done = sc._fit(frame, base, [], None, None, None, None)
        standby = done.calibration.standby
        assert standby.ua_ref is not None
        assert standby.ua_exponent == pytest.approx(0.28)

    def test_without_the_heaters_reading_it_keeps_the_base(self) -> None:
        frame = recovery_days(3).drop(columns=["air_f", "heater_cabinet_f"])
        done = sc._fit(frame, sim.default_params(), [], None, None, None, None)
        assert done.air is None
        assert sc.NO_AIR_NOTE in done.notes
        assert "standby" in done.calibration.params.unfitted

    def test_the_air_is_the_cabinets_less_its_warmth(self) -> None:
        frame = recovery_days(3).drop(columns=["air_f"])
        assert sc._air_from_cabinet(frame) is not None
        # Day 1's quiet decay, at that day's air.
        day = frame.index[0] + timedelta(days=1)
        quiet = frame.loc[day : day + timedelta(hours=10), "air_f"].dropna()
        assert len(quiet) > 0
        assert quiet.to_numpy() == pytest.approx(60.0 + 5.0 * np.sin(1.0))

    def test_a_window_without_the_idle_reading_is_not_fitted(self) -> None:
        frame = recovery_days(6).drop(columns=["air_f"])
        # Unheard for an hour inside each quiet window.
        hour = (frame.index - frame.index[0]).total_seconds() / 3600 % 24
        unheard = ((hour >= 8) & (hour < 9)) | ((hour >= 20) & (hour < 21))
        frame.loc[unheard, "heater_cabinet_f"] = np.nan
        done = sc._fit(frame, sim.default_params(), [], None, None, None, None)
        assert done.air == "heater"
        assert done.calibration.standby.ua_ref is None
        why = {t.name: t.why for t in sc.report(done)}
        assert any(
            "no quiet window has the heater's idle reading throughout" in w
            for w in why.values()
        )
