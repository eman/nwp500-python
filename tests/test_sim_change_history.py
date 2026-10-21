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
