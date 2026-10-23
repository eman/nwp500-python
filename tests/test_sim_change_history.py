"""A heater's calibration from its values' changes: Home Assistant's
entity history (``sim_home_assistant.read_heater_history``), the frame
(``sim_adapters.change_history``) and the fits
(``sim_calibrate.calibrate_changes``)."""

import asyncio
import math
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

pytest.importorskip("pandas")
pytest.importorskip("scipy")

from nwp500 import sim, status_history
from nwp500 import sim_adapters as sa
from nwp500 import sim_calibrate as sc
from nwp500 import sim_home_assistant as ha
from nwp500.enums import CurrentOperationMode, ErrorCode, HeatSource
from nwp500.models import DeviceStatus
from nwp500.sim.book import AMBIENT_DEFAULT_F
from nwp500.temperature import DeciCelsius

T0 = datetime(2026, 1, 5, tzinfo=UTC)
UA = 6.0
AIR_F = 60.0
MASS = sim.default_params().tank.thermal_mass_btu_f
H = timedelta(hours=1)


def _deci_c(f: float) -> int:
    return round((f - 32) / 1.8 * 10)


def quiet(
    status: dict[str, Any], hours: float = 24
) -> list[status_history.TimedStatus]:
    """A quiet tank cooling at ``UA`` toward ``AIR_F`` from 130 °F, a
    status every 30 s."""
    raw = status | {"compUse": 0, "dhwUse": 0, "heatUpperUse": 0}
    raw |= {"antiLegionellaOperationBusy": 0, "currentHeatUse": 0}
    out, tank, gap = [], 130.0, 4.0
    step = timedelta(seconds=30)
    t = T0
    while t < T0 + timedelta(hours=hours):
        s = raw | {
            "tankUpperTemperature": _deci_c(tank + gap / 2),
            "tankLowerTemperature": _deci_c(tank - gap / 2),
        }
        out.append((t, DeviceStatus.model_validate(s)))
        tank -= UA / MASS * (tank - AIR_F) * step.total_seconds() / 3600
        t += step
    return out


def changes_of(
    readings: list[status_history.TimedStatus],
) -> sa.ChangeRows:
    """What an entity history of ``readings`` holds: each value only
    where it changed."""

    def series(value: Any) -> list[tuple[datetime, Any]]:
        out: list[tuple[datetime, Any]] = []
        for t, s in readings:
            v = value(s)
            if not out or out[-1][1] != v:
                out.append((t, v))
        return out

    def f(raw: Any) -> Any:
        return lambda s: sa._from_device(DeciCelsius(raw(s)))

    return sa.ChangeRows(
        upper_f=series(f(lambda s: s.tank_upper_temperature_raw)),
        lower_f=series(f(lambda s: s.tank_lower_temperature_raw)),
        compressor_on=series(lambda s: bool(s.comp_use)),
        upper_element_on=series(lambda s: bool(s.heat_upper_use)),
        lower_element_on=series(lambda s: bool(s.heat_lower_use)),
        heat_source=series(lambda s: s.current_heat_use),
        dhw_in_use=series(lambda s: bool(s.dhw_use)),
        target_f=series(
            lambda s: sa._from_device(
                sa.HalfCelsius(s.hp_lower_off_temp_setting_raw)  # type: ignore[attr-defined]
            )
        ),
        operation_mode=series(lambda s: s.operation_mode),
        anti_legionella=series(
            lambda s: bool(s.anti_legionella_operation_busy)
        ),
        error_code=series(lambda s: s.error_code),
        power_w=series(lambda s: float(s.current_inst_power)),
        energy_to_setpoint_wh=series(lambda s: float(s.energy_to_setpoint)),
        heater_air_f=series(f(lambda s: s.ambient_temperature_raw)),
    )


class TestTheFrame:
    def test_the_same_frame_as_the_statuses(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        readings = quiet(device_status_dict, hours=2)
        # Running, heating and in use part of the time, in hybrid mode
        # and in error for a while.
        busy = device_status_dict | {"compUse": 2, "dhwUse": 2}
        busy |= {"operationMode": 64, "errorCode": 0}
        for i in range(60, 90):
            t, s = readings[i]
            raw = busy | {
                "tankUpperTemperature": s.tank_upper_temperature_raw,
                "tankLowerTemperature": s.tank_lower_temperature_raw,
            }
            readings[i] = (t, DeviceStatus.model_validate(raw))
        from_statuses = sa.history(readings)
        from_changes = sa.change_history(
            changes_of(readings), (t for t, _ in readings)
        )
        assert list(from_changes.columns) == list(from_statuses.columns)
        assert from_changes.index.equals(from_statuses.index)
        for column in from_statuses.columns:
            a = from_statuses[column].to_numpy()
            b = from_changes[column].to_numpy()
            assert ((a == b) | (a != a) & (b != b)).all(), column

    def test_a_value_holds_until_its_next_change(self) -> None:
        rows = sa.ChangeRows(
            upper_f=[(T0, 130.0), (T0 + 2 * H, 128.0)],
            lower_f=[(T0 + H, 120.0)],
            compressor_on=[(T0, False), (T0 + 2 * H, True)],
            heater_air_f=[(T0, 61.0)],
        )
        frame = sa.change_history(rows, [T0, T0 + 3 * H])
        # A row at each instant heard and each change between them.
        assert list(frame.index) == [T0 + i * H for i in range(4)]
        assert frame["upper_f"].tolist() == [130.0, 130.0, 128.0, 128.0]
        assert math.isnan(frame["lower_f"].iloc[0])
        assert frame["lower_f"].iloc[1] == 120.0
        # The heater's own air only while the compressor runs.
        air = frame["heater_air_f"].tolist()
        assert math.isnan(air[1]) and air[2] == 61.0
        assert not frame["dhw_in_use"].any()
        assert "power_w" not in frame.columns

    def test_what_is_excluded(self) -> None:
        rows = sa.ChangeRows(
            upper_f=[(T0, 130.0)],
            lower_f=[(T0, 120.0)],
            operation_mode=[
                (T0, CurrentOperationMode.STANDBY),
                (T0 + H, CurrentOperationMode.HYBRID_BOOST_MODE),
                (T0 + 2 * H, CurrentOperationMode.STANDBY),
            ],
            anti_legionella=[(T0, False), (T0 + 3 * H, True)],
            error_code=[(T0, ErrorCode.NO_ERROR), (T0 + 4 * H, ErrorCode(1))]
            if 1 in ErrorCode._value2member_map_
            else [(T0, ErrorCode.NO_ERROR)],
            heat_source=[(T0, HeatSource.HEATELEMENT)],
        )
        frame = sa.change_history(rows, [T0 + i * H for i in range(5)])
        excluded = frame["excluded"].tolist()
        assert excluded[:4] == [False, True, False, True]
        assert frame["element_on"].all()

    def test_an_outage_is_unobserved(self) -> None:
        rows = sa.ChangeRows(
            upper_f=[(T0, 130.0)],
            lower_f=[(T0, 120.0)],
            outages=[(T0 + H + timedelta(minutes=5), T0 + 2 * H)],
        )
        frame = sa.change_history(rows, [T0 + i * H for i in range(4)])
        assert frame["dhw_in_use"].tolist() == [False, True, False, False]
        assert frame["excluded"].tolist() == [False, True, False, False]

    def test_nothing_heard_is_no_rows(self) -> None:
        rows = sa.ChangeRows(upper_f=[(T0, 130.0)], lower_f=[(T0, 120.0)])
        assert sa.change_history(rows, []).empty


class TestTheFits:
    def test_the_standby_loss_from_the_changes(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        readings = quiet(device_status_dict)
        heard = [t for t, _ in readings]
        done = sc.calibrate_changes(
            changes_of(readings), heard, ambient=AIR_F, notes=("read: a note",)
        )
        assert done.calibration.standby.ua_ref == pytest.approx(UA, rel=0.05)
        assert done.notes[0] == "read: a note"
        same = sc.calibrate(readings, ambient=AIR_F)
        assert done.calibration.standby.ua_ref == pytest.approx(
            same.calibration.standby.ua_ref
        )
        assert done.n_statuses == same.n_statuses

    def test_a_silence_is_a_gap(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        readings = quiet(device_status_dict)
        # Nothing heard from 8 h to 11 h.
        heard = [t for t, _ in readings if not T0 + 8 * H < t < T0 + 11 * H]
        rows = changes_of(readings)
        done = sc.calibrate_changes(rows, heard, ambient=AIR_F)
        assert done.n_gaps == 1
        assert done.calibration.standby.n_quiet == 2

    def test_nothing_heard_is_refused(self) -> None:
        rows = sa.ChangeRows(upper_f=[(T0, 130.0)], lower_f=[(T0, 120.0)])
        with pytest.raises(sc.CalibrationInputError, match="observed"):
            sc.calibrate_changes(rows, [])


# ── Home Assistant ──────────────────────────────────────────────────


def _row(
    entity: str, at: datetime, state: str, unit: str | None = None
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "entity_id": entity,
        "state": state,
        "last_changed": at.isoformat(),
        "last_updated": at.isoformat(),
    }
    if unit:
        row["attributes"] = {"unit_of_measurement": unit}
    return row


class WindowedClient:
    """A Home Assistant that answers each ``read_history`` as its REST
    API does: the state in force at the window's start, stamped at the
    start, then the rows inside it."""

    def __init__(
        self,
        rows: Iterable[dict[str, Any]],
        units: dict[str, str | None],
        *,
        states: bool = True,
    ) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            self.rows.setdefault(r["entity_id"], []).append(r)
        self.units = units
        self.states = states
        self.windows: list[tuple[datetime, datetime]] = []

    async def state(self, entity: str) -> ha.State:
        return ha.State(entity, 0.0, self.units.get(entity), T0)

    async def read_history(
        self, entities: Iterable[str], start: datetime, end: datetime
    ) -> ha.History:
        self.windows.append((start, end))
        names = list(entities)
        doc = []
        for n in names:
            rows = self.rows.get(n, [])
            before = [
                r for r in rows if ha._instant(r["last_updated"]) <= start
            ]
            inside = [
                r for r in rows if start < ha._instant(r["last_updated"]) <= end
            ]
            series = []
            if before:
                series.append(
                    before[-1]
                    | {
                        "last_changed": start.isoformat(),
                        "last_updated": start.isoformat(),
                    }
                )
            series += inside
            if series:
                doc.append(series)
        states = ha.parse_states(doc)
        units = ha.parse_units(doc)
        outages = ha.parse_outages(doc, end)
        return ha.History(
            ha.history_for(doc, names),
            {n: outages.get(n, []) for n in names},
            {n: units.get(n, []) for n in names},
            {n: states.get(n, []) for n in names} if self.states else None,
        )


ENTITIES = ha.HeaterEntities(
    heard="sensor.last_response",
    upper="sensor.upper",
    lower="sensor.lower",
    compressor="binary_sensor.compressor",
    operation_mode="sensor.mode",
    power="sensor.power",
)


UNITS: dict[str, str | None] = {
    "sensor.upper": "°F",
    "sensor.lower": "°F",
    "sensor.power": "W",
}


def _heater_rows(days: int = 3) -> list[dict[str, Any]]:
    rows = []
    t = T0
    end = T0 + timedelta(days=days)
    while t < end:
        rows.append(_row("sensor.last_response", t, t.isoformat()))
        t += timedelta(minutes=10)
    rows += [
        _row("sensor.upper", T0, "130.0", "°F"),
        # Recorded in °C for a while: 54.0 °C is 129.2 °F.
        _row("sensor.upper", T0 + 30 * H, "54.0", "°C"),
        _row("sensor.upper", T0 + 50 * H, "128.0", "°F"),
        _row("sensor.lower", T0, "120.0", "°F"),
        _row("binary_sensor.compressor", T0, "off"),
        _row("binary_sensor.compressor", T0 + 20 * H, "on"),
        _row("binary_sensor.compressor", T0 + 21 * H, "off"),
        _row("sensor.mode", T0, "STANDBY"),
        _row("sensor.mode", T0 + 40 * H, "HYBRID_BOOST_MODE"),
        _row("sensor.mode", T0 + 41 * H, "NOT_A_MODE"),
        _row("sensor.power", T0, "0.45", "kW"),
        # Down across the second window's start.
        _row("sensor.power", T0 + 23 * H, "unavailable"),
        _row("sensor.power", T0 + 25 * H, "450", "W"),
    ]
    return rows


def _read(client: WindowedClient, days: int = 3) -> ha.HeaterHistory:
    return asyncio.run(
        ha.read_heater_history(
            cast(ha.HomeAssistantClient, client),
            ENTITIES,
            T0,
            T0 + timedelta(days=days),
        )
    )


class TestTheReader:
    def test_states_keep_what_is_not_a_number(self) -> None:
        doc = [
            [
                _row("binary_sensor.c", T0, "on"),
                _row("binary_sensor.c", T0 + H, "unavailable"),
            ]
        ]
        assert ha.parse_states(doc) == {
            "binary_sensor.c": [(T0, "on"), (T0 + H, "unavailable")]
        }
        assert ha.parse_history(doc) == {"binary_sensor.c": []}

    def test_a_day_at_a_time(self) -> None:
        client = WindowedClient(_heater_rows(), UNITS)
        got = _read(client)
        assert client.windows == [
            (T0 + timedelta(days=d), T0 + timedelta(days=d + 1))
            for d in range(3)
        ]
        # Each response once; no window's opening row counts as one.
        assert len(got.observed) == len(set(got.observed))
        assert got.observed[0] == T0 + timedelta(minutes=10)
        assert T0 + timedelta(days=1) in got.observed
        r = got.rows
        # Each value once, however many windows repeat it.
        assert r.lower_f == [(T0, 120.0)]
        assert [v for _, v in r.upper_f] == pytest.approx([130.0, 129.2, 128.0])
        assert r.compressor_on == [
            (T0, False),
            (T0 + 20 * H, True),
            (T0 + 21 * H, False),
        ]
        assert r.operation_mode == [
            (T0, CurrentOperationMode.STANDBY),
            (T0 + 40 * H, CurrentOperationMode.HYBRID_BOOST_MODE),
        ]
        assert r.power_w == [(T0, 450.0)]
        # One outage, across the windows' edge.
        assert list(r.outages) == [(T0 + 23 * H, T0 + 25 * H)]
        assert any("operation_mode: 1 states" in n for n in got.notes)
        assert any("unavailable 1 times (2.0 h)" in n for n in got.notes)
        assert any("anti-legionella cycle is not" in n for n in got.notes)

    def test_it_calibrates(self) -> None:
        client = WindowedClient(_heater_rows(), UNITS)
        got = _read(client)
        done = sc.calibrate_changes(
            got.rows, got.observed, ambient=AIR_F, notes=got.notes
        )
        assert done.n_statuses >= len(got.observed)
        assert got.notes[0] in done.notes

    def test_a_client_without_states_is_refused(self) -> None:
        client = WindowedClient(_heater_rows(), UNITS, states=False)
        with pytest.raises(ha.HomeAssistantError, match="no states"):
            _read(client)

    def test_the_probes_are_needed(self) -> None:
        rows = [r for r in _heater_rows() if r["entity_id"] != "sensor.lower"]
        client = WindowedClient(rows, UNITS)
        with pytest.raises(ha.HomeAssistantError, match="probes"):
            _read(client)

    def test_an_optional_entity_in_no_unit_is_left_out(self) -> None:
        client = WindowedClient(_heater_rows(), UNITS | {"sensor.power": "V"})
        got = _read(client)
        assert not got.rows.power_w
        assert any("power_w: not read" in n for n in got.notes)

    def test_power_and_energy_units(self) -> None:
        assert ha.to_w(0.5, "kW") == 500.0
        assert ha.to_wh(1.5, "kWh") == 1500.0
        with pytest.raises(ValueError, match="power"):
            ha.to_w(1.0, "V")


class TestTheFirstReview:
    def test_a_window_must_move_forward(self) -> None:
        client = WindowedClient(_heater_rows(), UNITS)
        for window in (timedelta(0), -H):
            with pytest.raises(ValueError, match="positive"):
                asyncio.run(
                    ha.read_heater_history(
                        cast(ha.HomeAssistantClient, client),
                        ENTITIES,
                        T0,
                        T0 + H,
                        window=window,
                    )
                )
        assert client.windows == []

    def test_the_heat_source_says_when_the_compressor_runs(self) -> None:
        rows = sa.ChangeRows(
            upper_f=[(T0, 130.0)],
            lower_f=[(T0, 120.0)],
            heat_source=[
                (T0, HeatSource.UNKNOWN),
                (T0 + H, HeatSource.HEATPUMP),
                (T0 + 2 * H, HeatSource.HEATPUMP_HEATELEMENT),
                (T0 + 3 * H, HeatSource.HEATELEMENT),
            ],
            heater_air_f=[(T0, 61.0)],
        )
        frame = sa.change_history(rows, [T0 + i * H for i in range(4)])
        assert frame["compressor_on"].tolist() == [False, True, True, False]
        assert frame["element_on"].tolist() == [False, False, True, True]
        assert frame["heater_air_f"].iloc[1] == 61.0

    def test_an_outage_reaches_the_meters_draws(self) -> None:
        rows = sa.ChangeRows(
            upper_f=[(T0, 130.0)],
            lower_f=[(T0, 120.0)],
            outages=[(T0 + H + timedelta(minutes=5), T0 + 2 * H)],
        )
        frame = sa.change_history(rows, [T0 + i * H for i in range(4)])
        sa.add_inputs(frame, drawing=[], circulating=[])
        assert frame["drawing"].tolist() == [False, True, False, False]
        assert not frame["circulating"].any()

    def test_an_unavailable_heartbeat_is_no_response(self) -> None:
        # Down from 22 h to 26 h: across the second window's start.
        down = T0 + 22 * H + timedelta(minutes=1)
        rows = [
            *_heater_rows(),
            _row("sensor.last_response", down, "unavailable"),
        ]
        rows = [
            r
            for r in rows
            if not (
                r["entity_id"] == "sensor.last_response"
                and T0 + 22 * H + timedelta(minutes=1)
                < ha._instant(r["last_updated"])
                < T0 + 26 * H
            )
        ]
        rows.append(_row("sensor.last_response", T0 + 26 * H, "back"))
        got = _read(WindowedClient(rows, UNITS))
        assert not any(
            T0 + 22 * H + timedelta(minutes=1) <= t < T0 + 26 * H
            for t in got.observed
        )
        assert (
            T0 + 22 * H + timedelta(minutes=1),
            T0 + 26 * H,
        ) in got.rows.outages

    def test_an_enums_own_unknown_is_a_value(self) -> None:
        rows = [
            *_heater_rows(),
            _row("sensor.source", T0, "HEATPUMP"),
            _row("sensor.source", T0 + 2 * H, "UNKNOWN"),
            _row("sensor.source", T0 + 4 * H, "unknown"),
            _row("sensor.source", T0 + 5 * H, "HEATPUMP"),
        ]
        entities = ha.HeaterEntities(
            heard=ENTITIES.heard,
            upper=ENTITIES.upper,
            lower=ENTITIES.lower,
            heat_source="sensor.source",
        )
        got = asyncio.run(
            ha.read_heater_history(
                cast(ha.HomeAssistantClient, WindowedClient(rows, UNITS)),
                entities,
                T0,
                T0 + timedelta(days=1),
            )
        )
        assert got.rows.heat_source == [
            (T0, HeatSource.HEATPUMP),
            (T0 + 2 * H, HeatSource.UNKNOWN),
            (T0 + 5 * H, HeatSource.HEATPUMP),
        ]
        assert list(got.rows.outages) == [(T0 + 4 * H, T0 + 5 * H)]

    def test_a_row_recorded_in_no_unit_is_left_out(self) -> None:
        # Today in °F; this row was recorded with no unit at all.
        rows = [*_heater_rows(), _row("sensor.lower", T0 + 5 * H, "20.0")]
        got = _read(WindowedClient(rows, UNITS))
        assert got.rows.lower_f == [(T0, 120.0)]
        assert any("lower_f: 1 states" in n for n in got.notes)


class TestRunsWithoutAir:
    @staticmethod
    def _runs(air: bool) -> tuple[sa.ChangeRows, list[datetime]]:
        """Five days, a 1 h compressor run each, the lower probe rising
        from 100 °F to its 140 °F target."""
        lower: list[tuple[datetime, Any]] = []
        compressor: list[tuple[datetime, Any]] = []
        for d in range(5):
            on = T0 + timedelta(days=d, hours=6)
            compressor += [(on, True), (on + H, False)]
            lower += [
                (on + timedelta(minutes=5 * i), 100.0 + 40.0 * i / 12)
                for i in range(13)
            ]
        rows = sa.ChangeRows(
            upper_f=[(T0, 140.0)],
            lower_f=lower,
            compressor_on=compressor,
            target_f=[(T0, 140.0)],
            heater_air_f=[(T0, 65.0)] if air else (),
        )
        step = timedelta(seconds=30)
        heard = [T0 + i * step for i in range(int(timedelta(days=5) / step))]
        return rows, heard

    def test_the_report_names_the_missing_air(self) -> None:
        rows, heard = self._runs(air=False)
        done = sc.calibrate_changes(rows, heard)
        assert (done.n_runs, done.n_runs_without_air) == (5, 5)
        why = {t.name: t.why for t in sc.report(done)}["Compressor constant"]
        assert why.startswith(
            "5 of 5 compressor runs have no air temperature (no air given, "
            "and no heater ambient reading while the compressor runs)"
        )
        assert sc.air_unread_note(done) in done.notes

    def test_with_the_heaters_air_every_run_is_read(self) -> None:
        rows, heard = self._runs(air=True)
        done = sc.calibrate_changes(rows, heard)
        assert (done.n_runs, done.n_runs_without_air) == (5, 0)
        why = {t.name: t.why for t in sc.report(done)}["Compressor constant"]
        assert "no air temperature" not in why
        assert sc.air_unread_note(done) == ""


END = T0 + timedelta(days=3)
BOOK_HEATER = ha.HeaterEntities(
    heard="sensor.last_status",
    upper="sensor.upper",
    lower="sensor.lower",
    compressor="binary_sensor.compressor",
)
FLOW = "sensor.draw_flow"
BOOK_UNITS: dict[str, str | None] = {
    "sensor.upper": "°F",
    "sensor.lower": "°F",
    FLOW: "gal/min",
    "sensor.inlet": "°F",
    "sensor.pump": "rpm",
}


def _book_rows(*, mains: bool = False) -> list[dict[str, Any]]:
    """Three days of a full tank: heard every minute, a recovery 4 h
    before ``END``, a draw of 2 gal/min for 15 minutes 2 h before it.
    With ``mains``, an inlet probe settling to 58 °F through the draw
    and the demand entity on through it."""
    rows = []
    t = T0
    while t <= END:
        rows.append(_row("sensor.last_status", t, t.isoformat()))
        t += timedelta(minutes=1)
    draw = END - 2 * H
    rows += [
        _row("sensor.upper", T0, "140.0", "°F"),
        _row("sensor.lower", T0, "139.6", "°F"),
        _row("binary_sensor.compressor", T0, "off"),
        _row("binary_sensor.compressor", END - 4 * H, "on"),
        _row("binary_sensor.compressor", END - 3.5 * H, "off"),
        _row(FLOW, T0, "0.0", "gal/min"),
        _row(FLOW, draw, "2.0", "gal/min"),
        _row(FLOW, draw + timedelta(minutes=15), "0.0", "gal/min"),
        _row("sensor.pump", T0, "0.0", "rpm"),
    ]
    if mains:
        rows += [
            _row("sensor.inlet", T0, "66.0", "°F"),
            _row("sensor.inlet", draw + timedelta(minutes=5), "58.0", "°F"),
            _row("sensor.inlet", draw + timedelta(minutes=30), "65.0", "°F"),
            _row("binary_sensor.demand", T0, "off"),
            _row("binary_sensor.demand", draw, "on"),
            _row("binary_sensor.demand", draw + timedelta(minutes=15), "off"),
        ]
    return rows


def _keeper(client: WindowedClient, **entities: Any) -> ha.HomeAssistantBook:
    return ha.HomeAssistantBook(
        cast(ha.HomeAssistantClient, client),
        BOOK_HEATER,
        FLOW,
        ha.Entities(**entities),
    )


class TestTheBookKeptCurrent:
    P = sim.default_params()

    def test_it_books_as_book_from_changes(self) -> None:
        client = WindowedClient(_book_rows(), BOOK_UNITS)
        keeper = _keeper(client)
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        history = asyncio.run(
            ha.read_heater_history(
                cast(ha.HomeAssistantClient, client),
                BOOK_HEATER,
                END - ha.BOOK_WINDOW,
                END,
            )
        )
        flow = asyncio.run(
            client.read_history([FLOW], END - ha.BOOK_WINDOW, END)
        )
        readings, _ = flow.converted(FLOW, "gal/min", ha.to_gpm, END)
        want = sa.book_from_changes(
            history.rows, history.observed, self.P, at=END, flow=readings
        )
        assert want is not None and got.booked is not None
        assert got.booked.heat_btu == pytest.approx(want.heat_btu)
        assert not got.inlet_measured

    def test_later_reads_ask_only_for_what_is_new(self) -> None:
        once = WindowedClient(_book_rows(), BOOK_UNITS)
        whole = _keeper(once)
        asyncio.run(whole.read(END))
        client = WindowedClient(_book_rows(), BOOK_UNITS)
        keeper = _keeper(client)
        for at in (END - 3 * H, END - 1 * H, END):
            asyncio.run(keeper.read(at))
        # Each read from the last: none reaches back past it.
        assert client.windows[-1][0] == END - 1 * H
        a = whole.book(END, self.P).booked
        b = keeper.book(END, self.P).booked
        assert a is not None and b is not None
        assert b.heat_btu == pytest.approx(a.heat_btu)

    def test_the_mains_from_the_inlet_and_demand(self) -> None:
        client = WindowedClient(_book_rows(mains=True), BOOK_UNITS)
        keeper = _keeper(
            client, inlet="sensor.inlet", demand="binary_sensor.demand"
        )
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert got.booked is not None
        assert got.inlet_measured
        assert got.booked.inlet_f == pytest.approx(58.0)

    def test_without_demand_no_conversion_at_the_mains(self) -> None:
        client = WindowedClient(_book_rows(mains=True), BOOK_UNITS)
        keeper = _keeper(client, inlet="sensor.inlet")
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert got.booked is not None and not got.inlet_measured

    def test_the_pump_gives_the_runs(self) -> None:
        client = WindowedClient(_book_rows(), BOOK_UNITS)
        keeper = _keeper(client, circulation_speed="sensor.pump")
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert got.booked is not None
        assert not any("circulation" in n for n in got.notes)

    def test_no_flow_history_is_no_book(self) -> None:
        rows = [r for r in _book_rows() if r["entity_id"] != FLOW]
        keeper = _keeper(WindowedClient(rows, BOOK_UNITS))
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert got.booked is None
        assert f"book: no history of {FLOW} read" in got.notes

    def test_before_a_read_there_is_no_book(self) -> None:
        keeper = _keeper(WindowedClient(_book_rows(), BOOK_UNITS))
        got = keeper.book(END, self.P)
        assert got.booked is None and got.notes == ("book: no history read",)

    def test_a_failed_read_is_noted_and_read_again(self) -> None:
        class Failing(WindowedClient):
            fail = True

            async def read_history(
                self, entities: Iterable[str], start: datetime, end: datetime
            ) -> ha.History:
                if self.fail and FLOW in entities:
                    raise ha.HomeAssistantError("down")
                return await super().read_history(entities, start, end)

        client = Failing(_book_rows(), BOOK_UNITS)
        keeper = _keeper(client)
        asyncio.run(keeper.read(END - H))
        assert keeper.book(END - H, self.P).booked is None
        client.fail = False
        asyncio.run(keeper.read(END))
        # The flow is read again from the window's start, not from the
        # failed read.
        assert client.windows[-1][0] == END - ha.BOOK_WINDOW
        assert keeper.book(END, self.P).booked is not None


class TestTheBookFirstReview:
    P = sim.default_params()

    def test_the_flow_is_never_taken_off_as_circulation(self) -> None:
        from dataclasses import replace

        rows = [
            *_book_rows(),
            _row(
                "sensor.pump", END - 2 * H - timedelta(minutes=1), "2000", "rpm"
            ),
            _row(
                "sensor.pump", END - 2 * H + timedelta(minutes=20), "0", "rpm"
            ),
        ]

        def heat(share: float) -> float:
            p = replace(
                self.P,
                circulation=sim.CirculationParams(
                    displaced_gal=1.0,
                    flow_gpm=2.0,
                    loss_btu_per_gal=50.0,
                    meter_share=share,
                ),
            )
            keeper = _keeper(
                WindowedClient(rows, BOOK_UNITS),
                circulation_speed="sensor.pump",
            )
            asyncio.run(keeper.read(END))
            got = keeper.book(END, p)
            assert got.booked is not None
            return got.booked.heat_btu

        assert heat(0.81) == pytest.approx(heat(0.0))

    def test_an_optional_unit_unread_leaves_the_rest(self) -> None:
        class NoInlet(WindowedClient):
            async def state(self, entity: str) -> ha.State:
                if entity == "sensor.inlet":
                    raise ha.HomeAssistantError("404")
                return await super().state(entity)

        client = NoInlet(_book_rows(mains=True), BOOK_UNITS)
        keeper = _keeper(
            client, inlet="sensor.inlet", demand="binary_sensor.demand"
        )
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert got.booked is not None and not got.inlet_measured
        assert any("sensor.inlet's unit not read" in n for n in got.notes)

    def test_an_inlet_in_no_unit_books_without_the_mains(self) -> None:
        client = WindowedClient(
            _book_rows(mains=True), BOOK_UNITS | {"sensor.inlet": "lux"}
        )
        keeper = _keeper(
            client, inlet="sensor.inlet", demand="binary_sensor.demand"
        )
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert got.booked is not None and not got.inlet_measured

    def test_after_a_failed_read_the_unread_flow_is_unknown(self) -> None:
        class Failing(WindowedClient):
            fail = False

            async def read_history(
                self, entities: Iterable[str], start: datetime, end: datetime
            ) -> ha.History:
                if self.fail and FLOW in entities:
                    raise ha.HomeAssistantError("down")
                return await super().read_history(entities, start, end)

        client = Failing(_book_rows(), BOOK_UNITS)
        keeper = _keeper(client)
        # Read before the draw, then fail across it.
        asyncio.run(keeper.read(END - 3 * H))
        client.fail = True
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert any("nothing read since" in n for n in got.notes)
        # The unread span is an outage of the flow: no book rather than
        # one that holds the flow at zero through the draw.
        assert got.booked is None

    def test_a_short_window_reads_the_mains_within_it(self) -> None:
        client = WindowedClient(_book_rows(mains=True), BOOK_UNITS)
        keeper = ha.HomeAssistantBook(
            cast(ha.HomeAssistantClient, client),
            BOOK_HEATER,
            FLOW,
            ha.Entities(
                inlet="sensor.inlet",
                demand="binary_sensor.demand",
                circulation_speed="sensor.pump",
            ),
            window=timedelta(hours=24),
        )
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert got.booked is not None
        assert got.inlet_measured, got.notes


class TestTheBookAir:
    """An air unknown, unavailable or in no unit this reads, is the
    default air, not the last reading held."""

    P = sim.default_params()
    OUT = END - 30 * H

    def _heat(self, air_rows: list[dict[str, Any]], unit: str) -> float:
        client = WindowedClient(
            [*_book_rows(), *air_rows], BOOK_UNITS | {"sensor.air": unit}
        )
        keeper = _keeper(client, air="sensor.air")
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert got.booked is not None, got.notes
        return got.booked.heat_btu

    def _default_from_out(self) -> float:
        return self._heat(
            [
                _row("sensor.air", T0, "40.0", "°F"),
                _row("sensor.air", self.OUT, str(AMBIENT_DEFAULT_F), "°F"),
            ],
            "°F",
        )

    def test_an_outage_is_the_default_air(self) -> None:
        held = self._heat([_row("sensor.air", T0, "40.0", "°F")], "°F")
        out = self._heat(
            [
                _row("sensor.air", T0, "40.0", "°F"),
                _row("sensor.air", self.OUT, "unavailable"),
            ],
            "°F",
        )
        assert out == pytest.approx(self._default_from_out())
        assert out != pytest.approx(held)

    def test_a_reading_in_no_unit_is_the_default_air(self) -> None:
        out = self._heat(
            [
                _row("sensor.air", T0, "40.0", "°F"),
                _row("sensor.air", self.OUT, "300.0", "lux"),
            ],
            "°F",
        )
        assert out == pytest.approx(self._default_from_out())


class TestThePumpThirdReview:
    P = sim.default_params()

    def test_a_reading_in_no_unit_outside_the_span_is_no_matter(self) -> None:
        rows = [
            _row("sensor.pump", T0, "500", "lux"),
            _row("sensor.pump", T0 + H, "0", "rpm"),
        ]
        client = WindowedClient(rows, BOOK_UNITS)
        got = asyncio.run(client.read_history(["sensor.pump"], T0, END))
        runs, why = ha.known_runs(got, "sensor.pump", "rpm", T0 + 2 * H, END)
        assert runs == [] and why is None
        runs, why = ha.known_runs(got, "sensor.pump", "rpm", T0, END)
        assert runs is None and why == "1 readings in no speed unit"

    def test_the_pumps_outages_count_when_its_runs_are_unknown(self) -> None:
        from dataclasses import replace

        p = replace(
            self.P,
            circulation=sim.CirculationParams(
                displaced_gal=1.0, flow_gpm=2.0, loss_btu_per_gal=50.0
            ),
        )
        rows = [r for r in _book_rows() if r["entity_id"] != "sensor.pump"] + [
            # Unavailable from the start: the runs are unknown.
            _row("sensor.pump", T0, "unavailable"),
            _row("sensor.pump", END - H, "0", "rpm"),
        ]

        def heat(pump: bool) -> float:
            keeper = _keeper(
                WindowedClient(rows, BOOK_UNITS),
                **({"circulation_speed": "sensor.pump"} if pump else {}),
            )
            asyncio.run(keeper.read(END))
            got = keeper.book(END, p)
            assert got.booked is not None, got.notes
            return got.booked.heat_btu

        # The outage is booked as the pump running: less heat than none.
        assert heat(True) < heat(False)


class TestTheBookFourthReview:
    P = sim.default_params()

    def test_a_read_without_the_flow_is_read_again(self) -> None:
        class Dropping(WindowedClient):
            drop = False

            async def read_history(
                self, entities: Iterable[str], start: datetime, end: datetime
            ) -> ha.History:
                got = await super().read_history(entities, start, end)
                if self.drop:
                    got.readings[FLOW] = []
                return got

        client = Dropping(_book_rows(), BOOK_UNITS)
        keeper = _keeper(client)
        asyncio.run(keeper.read(END - 3 * H))
        client.drop = True
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert f"book: no history of {FLOW} read" in got.notes
        # Not booked as if the flow held at zero through the draw.
        assert got.booked is None
        client.drop = False
        asyncio.run(keeper.read(END))
        # Read again from the last read that held the flow.
        assert client.windows[-1][0] == END - 3 * H
        assert keeper.book(END, self.P).booked is not None


class TestTheBookFifthReview:
    P = sim.default_params()

    def test_an_omitted_pump_is_unknown_not_held(self) -> None:
        from dataclasses import replace

        p = replace(
            self.P,
            circulation=sim.CirculationParams(
                displaced_gal=1.0, flow_gpm=2.0, loss_btu_per_gal=50.0
            ),
        )

        class Dropping(WindowedClient):
            drop = False

            async def read_history(
                self, entities: Iterable[str], start: datetime, end: datetime
            ) -> ha.History:
                names = [
                    n
                    for n in entities
                    if not (self.drop and n == "sensor.pump")
                ]
                return await super().read_history(names, start, end)

        def heat(drop: bool) -> float:
            client = Dropping(_book_rows(), BOOK_UNITS)
            keeper = _keeper(client, circulation_speed="sensor.pump")
            asyncio.run(keeper.read(END - 3 * H))
            client.drop = drop
            asyncio.run(keeper.read(END))
            got = keeper.book(END, p)
            assert got.booked is not None, got.notes
            return got.booked.heat_btu

        # Unread, the pump may have run: less heat than held idle.
        assert heat(True) < heat(False)

    def test_an_omitted_demand_is_an_unknown_state(self) -> None:
        got = ha.History(
            {FLOW: [(T0, 0.0)]}, {FLOW: []}, None, {FLOW: [(T0, "0.0")]}
        )
        marked = ha._unread_marked(got, [FLOW, "binary_sensor.demand"], T0, END)
        assert marked.outages["binary_sensor.demand"] == [(T0, END)]
        assert marked.states is not None
        assert marked.states["binary_sensor.demand"] == [(T0, "unknown")]
        assert marked.states[FLOW] == [(T0, "0.0")]


class TestTheBookSixthReview:
    P = sim.default_params()

    def test_an_omitted_compressor_is_no_heating_credited(self) -> None:
        class Dropping(WindowedClient):
            drop = False

            async def read_history(
                self, entities: Iterable[str], start: datetime, end: datetime
            ) -> ha.History:
                names = [
                    n
                    for n in entities
                    if not (self.drop and n == "binary_sensor.compressor")
                ]
                return await super().read_history(names, start, end)

        client = Dropping(_book_rows(), BOOK_UNITS)
        keeper = _keeper(client)
        # Read while the compressor runs, then omit it across its stop.
        asyncio.run(keeper.read(END - 3.75 * H))
        client.drop = True
        asyncio.run(keeper.read(END))
        got = keeper.book(END, self.P)
        assert any(
            n.startswith("compressor_on: nothing read") for n in got.notes
        )
        # Unobserved to the end: no book, not one heated throughout.
        assert got.booked is None

    def test_a_compressor_omitted_from_one_window_is_unobserved(self) -> None:
        class Dropping(WindowedClient):
            async def read_history(
                self, entities: Iterable[str], start: datetime, end: datetime
            ) -> ha.History:
                # The last day's window has nothing of the compressor.
                names = [
                    n
                    for n in entities
                    if not (
                        start >= END - 24 * H
                        and n == "binary_sensor.compressor"
                    )
                ]
                return await super().read_history(names, start, end)

        rows = [
            r
            for r in _book_rows()
            if r["entity_id"] != "binary_sensor.compressor"
        ] + [
            _row("binary_sensor.compressor", T0, "off"),
            # On through the second day's end, into the omitted window.
            _row("binary_sensor.compressor", END - 25 * H, "on"),
        ]
        history = asyncio.run(
            ha.read_heater_history(
                cast(ha.HomeAssistantClient, Dropping(rows, BOOK_UNITS)),
                BOOK_HEATER,
                T0,
                END,
            )
        )
        assert (END - 24 * H, END) in history.rows.outages
        assert "compressor_on: nothing read in 1 windows, left unobserved" in (
            history.notes
        )


class TestTheBookEighthReview:
    P = sim.default_params()

    def test_after_a_failed_heater_read_no_heating_is_credited(self) -> None:
        class Failing(WindowedClient):
            fail = False

            async def read_history(
                self, entities: Iterable[str], start: datetime, end: datetime
            ) -> ha.History:
                names = list(entities)
                if self.fail and "sensor.upper" in names:
                    raise ha.HomeAssistantError("down")
                return await super().read_history(names, start, end)

        client = Failing(_book_rows(), BOOK_UNITS)
        keeper = _keeper(client)
        # The compressor is on; a minute later the heater can't be read,
        # though the flow can.
        on = END - 3.75 * H
        asyncio.run(keeper.read(on))
        client.fail = True
        later = on + timedelta(minutes=1)
        asyncio.run(keeper.read(later))
        got = keeper.book(later, self.P)
        assert got.booked is None
        assert any("none past the heater's last read" in n for n in got.notes)
        client.fail = False
        asyncio.run(keeper.read(END))
        assert keeper.book(END, self.P).booked is not None


class TestCirculationTermsDefaulted:
    P = sim.default_params()

    def test_runs_without_terms_are_priced_and_noted(self) -> None:
        from dataclasses import replace

        from nwp500.sim.defaults import SITE_CIRCULATION

        assert self.P.circulation is None
        rows = [
            *[r for r in _book_rows() if r["entity_id"] != "sensor.pump"],
            _row("sensor.pump", T0, "0", "rpm"),
            _row(
                "sensor.pump", END - 2 * H - timedelta(minutes=1), "2000", "rpm"
            ),
            _row("sensor.pump", END - H, "0", "rpm"),
        ]

        def book(p: Any) -> ha.BookAnswer:
            keeper = _keeper(
                WindowedClient(rows, BOOK_UNITS),
                circulation_speed="sensor.pump",
            )
            asyncio.run(keeper.read(END))
            return keeper.book(END, p)

        bare = book(self.P)
        site = book(
            replace(
                self.P, circulation=replace(SITE_CIRCULATION, meter_share=0.0)
            )
        )
        assert bare.booked is not None and site.booked is not None
        assert bare.booked.heat_btu == pytest.approx(site.booked.heat_btu)
        assert any("one installation's terms" in n for n in bare.notes)
        quiet = _keeper(WindowedClient(_book_rows(), BOOK_UNITS))
        asyncio.run(quiet.read(END))
        none = quiet.book(END, self.P).booked
        assert none is not None and bare.booked.heat_btu < none.heat_btu
