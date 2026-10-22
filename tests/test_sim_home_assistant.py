"""The simulator's other inputs from Home Assistant
(``nwp500.sim_home_assistant``): the parsing, the rules, and the
environment source against a fake client."""

import math
import time
from collections.abc import Iterable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, TypedDict, cast

import pytest

pytest.importorskip("pandas")

from nwp500 import sim, sim_live
from nwp500 import sim_home_assistant as ha
from nwp500.sim.location_air import LocationAirModel

NOW = datetime(2026, 10, 18, 15, tzinfo=UTC)
MODEL = LocationAirModel(damping=0.638, lag=timedelta(hours=2), offset_f=24.5)


def _state(
    entity: str, value: Any, unit: str | None, age: timedelta = timedelta(0)
) -> dict[str, Any]:
    stamp = (NOW - age).isoformat()
    return {
        "entity_id": entity,
        "state": str(value),
        "attributes": {} if unit is None else {"unit_of_measurement": unit},
        "last_changed": stamp,
        "last_updated": stamp,
    }


class TestParsing:
    def test_a_state(self) -> None:
        s = ha.parse_state(_state("sensor.air", "61.5", "°F"))
        assert (s.entity, s.value, s.unit, s.at) == (
            "sensor.air",
            61.5,
            "°F",
            NOW,
        )

    @pytest.mark.parametrize("value", ["unavailable", "unknown", "nan", "x"])
    def test_no_value_is_none(self, value: str) -> None:
        assert ha.parse_state(_state("sensor.air", value, "°F")).value is None

    def test_freshness_is_the_last_report(self) -> None:
        # A steady sensor: its value last changed 2 h ago, but it
        # reported just now.
        doc = _state("sensor.air", "61.5", "°F", timedelta(hours=2)) | {
            "last_reported": NOW.isoformat(),
        }
        s = ha.parse_state(doc)
        assert s.at == NOW
        assert ha.fresh(s, NOW)

    def test_without_a_report_the_last_update_then_change(self) -> None:
        # Home Assistant before 2024.3 sends no last_reported.
        doc = _state("sensor.air", "61.5", "°F") | {
            "last_changed": (NOW - timedelta(hours=3)).isoformat(),
            "last_updated": (NOW - timedelta(hours=2)).isoformat(),
        }
        s = ha.parse_state(doc)
        assert s.at == NOW - timedelta(hours=2)
        assert not ha.fresh(s, NOW)
        del doc["last_updated"]
        assert ha.parse_state(doc).at == NOW - timedelta(hours=3)

    def test_not_a_state(self) -> None:
        with pytest.raises(ha.HomeAssistantError):
            ha.parse_state(["no"])

    def test_a_history(self) -> None:
        doc = [
            [
                {
                    "entity_id": "sensor.b",
                    "state": "2",
                    "last_changed": "2026-10-18T14:01:00+00:00",
                },
                {
                    "state": "unavailable",
                    "last_changed": "2026-10-18T14:02:00Z",
                },
                {"state": "3", "last_changed": "2026-10-18T14:03:00+00:00"},
            ],
            [
                {
                    "entity_id": "sensor.a",
                    "state": "1",
                    "last_changed": "2026-10-18T14:00:00",
                }
            ],
        ]
        got = ha.parse_history(doc)
        assert got["sensor.b"] == [
            (datetime(2026, 10, 18, 14, 1, tzinfo=UTC), 2.0),
            (datetime(2026, 10, 18, 14, 3, tzinfo=UTC), 3.0),
        ]
        # A naive instant is UTC.
        assert got["sensor.a"] == [
            (datetime(2026, 10, 18, 14, tzinfo=UTC), 1.0)
        ]

    def test_a_forecast(self) -> None:
        doc = {
            "service_response": {
                "weather.home": {
                    "forecast": [
                        {
                            "datetime": "2026-10-18T16:00:00+00:00",
                            "temperature": 55,
                        },
                        {
                            "datetime": "2026-10-18T15:00:00+00:00",
                            "temperature": 54,
                        },
                    ]
                }
            }
        }
        hours, unit = ha.parse_forecast(doc, "weather.home")
        assert [v for _, v in hours] == [54.0, 55.0]
        assert unit is None
        with pytest.raises(ha.HomeAssistantError, match="no forecast"):
            ha.parse_forecast(doc, "weather.other")


class TestUnits:
    def test_temperatures(self) -> None:
        assert ha.to_f(20.0, "°C") == pytest.approx(68.0)
        assert ha.to_f(68.0, "°F") == 68.0
        assert ha.to_f(293.15, "K") == pytest.approx(68.0)
        with pytest.raises(ValueError, match="not a temperature"):
            ha.to_f(1.0, "%")

    def test_flows_and_volumes(self) -> None:
        assert ha.to_gpm(3.785411784, "L/min") == pytest.approx(1.0)
        assert ha.to_gpm(1.0, "gal/min") == 1.0
        assert ha.to_gal(3.785411784, "L") == pytest.approx(1.0)
        assert ha.to_gal(1.0, "ft³") == pytest.approx(7.4805, rel=1e-4)
        with pytest.raises(ValueError, match="not a volume"):
            ha.to_gal(1.0, "°F")
        with pytest.raises(ValueError, match="not a flow"):
            ha.to_gpm(1.0, None)


def _t(minutes: float) -> datetime:
    return NOW + timedelta(minutes=minutes)


class TestPumpRuns:
    def test_no_reading_is_unknown(self) -> None:
        assert ha.pump_runs([], _t(0), _t(60)) is None

    def test_runs_from_the_speed(self) -> None:
        speed = [(_t(-10), 0.0), (_t(5), 2800.0), (_t(7), 2810.0), (_t(9), 0.0)]
        assert ha.pump_runs(speed, _t(0), _t(60)) == [(_t(5), _t(9))]

    def test_a_silent_run_ends_after_five_minutes(self) -> None:
        assert ha.pump_runs([(_t(5), 2800.0)], _t(0), _t(60)) == [
            (_t(5), _t(10))
        ]

    def test_a_run_in_force_at_the_start(self) -> None:
        speed = [(_t(-1), 2800.0), (_t(2), 0.0)]
        assert ha.pump_runs(speed, _t(0), _t(60)) == [(_t(0), _t(2))]


class TestTheConfiguration:
    DOC: ClassVar[dict[str, Any]] = {
        "home_assistant": {
            "url": "http://ha.local:8123/",
            "entities": {"air": "sensor.air", "weather": "weather.home"},
        },
        "location_air": {"damping": 0.638, "lag_hours": 2, "offset_f": 24.5},
    }

    def test_it_reads(self) -> None:
        s = ha.sources_from(self.DOC, {"HA_TOKEN": "secret"})
        assert s.url == "http://ha.local:8123"
        assert s.token == "secret"
        assert "secret" not in repr(s)
        assert s.entities == ha.Entities(
            air="sensor.air", weather="weather.home"
        )
        assert s.location_air == MODEL

    @pytest.mark.parametrize(
        ("change", "environ", "match"),
        [
            ({}, {}, "HA_TOKEN is not set"),
            ({"url": "ha.local"}, {"HA_TOKEN": "x"}, "http"),
            (
                {"entities": {"garden": "sensor.x"}},
                {"HA_TOKEN": "x"},
                "unknown",
            ),
            ({"entities": {"air": "air"}}, {"HA_TOKEN": "x"}, "entity id"),
        ],
    )
    def test_what_is_wrong_is_named(
        self,
        change: dict[str, Any],
        environ: dict[str, str],
        match: str,
    ) -> None:
        doc = {"home_assistant": self.DOC["home_assistant"] | change}
        with pytest.raises(ValueError, match=match):
            ha.sources_from(doc, environ)

    def test_the_token_variable_is_named(self) -> None:
        doc = {
            "home_assistant": self.DOC["home_assistant"]
            | {"token_env": "MY_HA"}
        }
        assert ha.sources_from(doc, {"MY_HA": "t"}).token == "t"

    def test_a_model_needs_every_term(self) -> None:
        doc = self.DOC | {"location_air": {"damping": 1}}
        with pytest.raises(ValueError, match="location_air"):
            ha.sources_from(doc, {"HA_TOKEN": "x"})


class FakeClient:
    """Answers as Home Assistant would, from canned states and series."""

    def __init__(
        self,
        states: dict[str, ha.State] | None = None,
        history: dict[str, list[ha.Reading]] | None = None,
        forecast: tuple[list[ha.Reading], str | None] | None = None,
        fail: set[str] | None = None,
        outages: dict[str, list[ha.Span]] | None = None,
    ) -> None:
        self.states = states or {}
        self.down = outages or {}
        self.series = history or {}
        self.hours = forecast
        self.fail = fail or set()
        self.history_calls: list[tuple[list[str], datetime, datetime]] = []

    async def state(self, entity: str) -> ha.State:
        if entity in self.fail or entity not in self.states:
            raise ha.HomeAssistantError(f"GET /api/states/{entity}: HTTP 404")
        return self.states[entity]

    async def history(
        self, entities: Iterable[str], start: datetime, end: datetime
    ) -> dict[str, list[ha.Reading]]:
        return (await self.read_history(entities, start, end)).readings

    async def read_history(
        self, entities: Iterable[str], start: datetime, end: datetime
    ) -> ha.History:
        self.history_calls.append((list(entities), start, end))
        return ha.History(
            {e: self.series.get(e, []) for e in entities},
            {e: self.down.get(e, []) for e in entities},
        )

    async def forecast(
        self, entity: str
    ) -> tuple[list[ha.Reading], str | None]:
        if self.hours is None:
            raise ha.HomeAssistantError("no forecast")
        return self.hours


def _s(
    entity: str, value: float | None, unit: str, age_min: float = 0
) -> ha.State:
    return ha.State(entity, value, unit, NOW - timedelta(minutes=age_min))


def _source(
    client: Any,
    *,
    # ``Any``: with a precise type, mypy rejects the ``**entities``
    # unpacking of a ``dict[str, str]`` as a possible ``model`` keyword.
    model: Any = None,
    **entities: Any,
) -> Any:
    return ha.HomeAssistantEnvironment(
        client,  # pyright: ignore[reportArgumentType]
        ha.Entities(**entities),
        start=NOW,
        until=NOW + timedelta(hours=6),
        now=NOW,
        location_air=model,
    )


OUTDOOR = ([(NOW + timedelta(hours=h), 50.0 + h) for h in range(-3, 9)], "°F")


@pytest.mark.asyncio
class TestTheAir:
    async def test_projected_and_anchored(self) -> None:
        client = FakeClient(
            {"sensor.air": _s("sensor.air", 62.0, "°F", age_min=10)},
            forecast=OUTDOOR,
        )
        source = _source(
            client, model=MODEL, air="sensor.air", weather="weather.home"
        )
        env = await source.read()
        assert isinstance(env.ambient_f, tuple)
        first_at, first = env.ambient_f[0]
        assert first_at == NOW
        # Through the reading at its own instant, 10 min before now.
        expected = MODEL.at(OUTDOOR[0], [NOW])[0] + (
            62.0 - MODEL.at(OUTDOOR[0], [NOW - timedelta(minutes=10)])[0]
        )
        assert first == pytest.approx(expected)
        assert any("anchored" in n for n in source.notes)

    async def test_a_stale_reading_leaves_it_unanchored(self) -> None:
        client = FakeClient(
            {"sensor.air": _s("sensor.air", 62.0, "°F", age_min=90)},
            forecast=OUTDOOR,
        )
        source = _source(
            client, model=MODEL, air="sensor.air", weather="weather.home"
        )
        env = await source.read()
        assert isinstance(env.ambient_f, tuple)
        assert env.ambient_f[0][1] == pytest.approx(
            MODEL.at(OUTDOOR[0], [NOW])[0]
        )
        assert any("stale (1.5 h old)" in n for n in source.notes)
        assert any("unanchored" in n for n in source.notes)

    async def test_without_a_model_the_reading_is_held(self) -> None:
        client = FakeClient({"sensor.air": _s("sensor.air", 20.0, "°C")})
        env = await _source(client, air="sensor.air").read()
        assert env.ambient_f == pytest.approx(68.0)

    async def test_nothing_read_is_no_air(self) -> None:
        source = _source(FakeClient(), air="sensor.air")
        env = await source.read()
        assert env.ambient_defaulted
        assert any("air: not read" in n for n in source.notes)


@pytest.mark.asyncio
class TestTheHumidity:
    async def test_fresh(self) -> None:
        client = FakeClient({"sensor.rh": _s("sensor.rh", 41.0, "%")})
        env = await _source(client, humidity="sensor.rh").read()
        assert env.humidity == 41.0

    async def test_stale_is_the_default(self) -> None:
        client = FakeClient({"sensor.rh": _s("sensor.rh", 41.0, "%", 61)})
        env = await _source(client, humidity="sensor.rh").read()
        assert env.humidity == sim.Environment(ambient_f=60.0).humidity


def long_draw(
    *, ended_hours_ago: float, minutes: float = 15, mains_f: float = 58.0
) -> dict[str, list[ha.Reading]]:
    """A draw of 2 gal/min: the volume reported every 30 s, and the probe
    every 30 s, warm at rest and at the mains once the draw has run."""
    end = NOW - timedelta(hours=ended_hours_ago)
    start = end - timedelta(minutes=minutes)
    volume, probe = [], [(start - timedelta(hours=1), 66.0)]
    t = start
    while t < end:
        t += timedelta(seconds=30)
        volume.append((t, 1.0))
        into = (t - start).total_seconds()
        probe.append((t, 66.0 - min(into / 300.0, 1.0) * (66.0 - mains_f)))
    # The pipe stays at the mains a few minutes after the draw.
    probe.extend(
        (end + timedelta(seconds=30 * k), mains_f) for k in range(1, 7)
    )
    probe.append((end + timedelta(minutes=20), 65.0))
    return {"sensor.inlet": probe, "sensor.volume": volume}


class _InletEntities(TypedDict):
    inlet: str
    meter_volume: str


INLET: _InletEntities = {
    "inlet": "sensor.inlet",
    "meter_volume": "sensor.volume",
}
UNITS = {
    "sensor.inlet": _s("sensor.inlet", 65.0, "°F"),
    "sensor.volume": _s("sensor.volume", 0.0, "gal"),
    "sensor.pump": _s("sensor.pump", 0.0, "rpm"),
}


@pytest.mark.asyncio
class TestTheInlet:
    async def test_the_plateau_of_a_long_draw(self) -> None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        source = _source(client, **INLET)
        env = await source.read()
        assert env.inlet_f == pytest.approx(58.0)
        assert "inlet: the plateau of 1 long draws" in source.notes
        ((names, since, until),) = client.history_calls
        assert set(names) == {"sensor.inlet", "sensor.volume"}
        assert (since, until) == (NOW - timedelta(hours=72), NOW)

    async def test_a_short_draw_has_none(self) -> None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5, minutes=8))
        source = _source(client, **INLET)
        assert (await source.read()).inlet_f is None
        assert any("no long draw" in n for n in source.notes)

    async def test_a_draw_beyond_72_hours_has_none(self) -> None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=73))
        assert (await _source(client, **INLET).read()).inlet_f is None

    async def test_a_draw_during_circulation_has_none(self) -> None:
        series = long_draw(ended_hours_ago=5)
        start = NOW - timedelta(hours=5, minutes=10)
        series["sensor.pump"] = [
            (NOW - timedelta(hours=80), 0.0),
            (start, 2800.0),
            (start + timedelta(minutes=2), 0.0),
        ]
        client = FakeClient(UNITS, series)
        source = _source(client, circulation_speed="sensor.pump", **INLET)
        assert (await source.read()).inlet_f is None

    async def test_unknown_circulation_has_none(self) -> None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        source = _source(client, circulation_speed="sensor.pump", **INLET)
        assert (await source.read()).inlet_f is None
        assert any(
            n.startswith("inlet: the circulation's runs are unknown")
            for n in source.notes
        )

    async def test_without_the_meters_volume(self) -> None:
        source = _source(FakeClient(UNITS), inlet="sensor.inlet")
        assert (await source.read()).inlet_f is None
        assert any("meter's volume" in n for n in source.notes)

    async def test_a_failed_read_is_the_default(self) -> None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        client.fail = {"sensor.volume"}
        source = _source(client, **INLET)
        assert (await source.read()).inlet_f is None
        assert any(n.startswith("inlet: not read") for n in source.notes)


@pytest.mark.asyncio
class TestCompose:
    async def test_no_air_from_the_source_is_the_heaters(self) -> None:
        heater_env = sim.Environment(ambient_f=75.0)

        class Heater:
            async def read(self) -> Any:
                return sim_live.HeaterReading(
                    state=sim.HeaterState(upper_f=130.0, lower_f=110.0),
                    settings=sim.Settings(setpoint_f=140.0),
                    environment=heater_env,
                    params=None,
                    status=None,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
                    feature=None,
                )

        client = FakeClient({"sensor.rh": _s("sensor.rh", 41.0, "%")})
        composed = await sim_live.compose(
            start=NOW,
            horizon=timedelta(hours=6),
            tz="UTC",
            heater=Heater(),
            environment=_source(client, air="sensor.air", humidity="sensor.rh"),
        )
        env = composed.scenario.environment
        assert env.ambient_f == 75.0
        assert env.humidity == 41.0
        assert not math.isnan(env.ambient_f)


class TestDrawSpans:
    def test_runs_joined_across_short_gaps(self) -> None:
        flow = [(_t(0), 2.0), (_t(10 / 60), 2.0), (_t(0.5), 2.0), (_t(5), 0.0)]
        assert ha.draw_spans(flow) == [(_t(0), _t(0.5) + timedelta(seconds=10))]

    def test_a_long_gap_is_two_draws(self) -> None:
        flow = [(_t(0), 2.0), (_t(1), 2.0)]
        assert len(ha.draw_spans(flow)) == 2


@pytest.mark.asyncio
class TestTheRecord:
    START = NOW - timedelta(days=2)

    async def test_the_air_humidity_draws_and_runs(self) -> None:
        series = long_draw(ended_hours_ago=5)
        # The meter's row in force at the start repeats an old report.
        series["sensor.volume"].insert(0, (self.START, 5.0))
        series |= {
            "sensor.air": [(self.START, 20.0), (NOW, 21.0)],
            "sensor.rh": [(self.START, 40.0)],
            "sensor.pump": [(self.START, 0.0)],
        }
        states = UNITS | {
            "sensor.air": _s("sensor.air", 21.0, "°C"),
            "sensor.rh": _s("sensor.rh", 40.0, "%"),
        }
        got = await ha.record_inputs(
            FakeClient(states, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(
                air="sensor.air",
                humidity="sensor.rh",
                meter_volume="sensor.volume",
                circulation_speed="sensor.pump",
            ),
            self.START,
            NOW,
        )
        assert got.air == [(self.START, 68.0), (NOW, pytest.approx(69.8))]
        assert got.humidity == [(self.START, 40.0)]
        assert got.circulating == []
        (drawn,) = got.drawing or []
        assert drawn[1] - drawn[0] > timedelta(minutes=15)
        assert got.notes == ()

    async def test_coverage_and_missing_parts_are_noted(self) -> None:
        late = NOW - timedelta(hours=10)
        got = await ha.record_inputs(
            FakeClient(  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
                {
                    "sensor.air": _s("sensor.air", 60.0, "°F"),
                    "sensor.pump": _s("sensor.pump", 0.0, "rpm"),
                },
                {"sensor.air": [(late, 60.0)]},
            ),
            ha.Entities(air="sensor.air", circulation_speed="sensor.pump"),
            self.START,
            NOW,
        )
        assert got.air == [(late, 60.0)]
        assert any("covers only from" in n for n in got.notes)
        assert got.circulating is None
        assert any(
            n.startswith("circulation: history covers only part")
            for n in got.notes
        )

    async def test_a_failed_read_is_noted(self) -> None:
        client = FakeClient()
        got = await ha.record_inputs(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(air="sensor.air"),
            self.START,
            NOW,
        )
        assert (got.air, got.drawing) == (None, None)
        assert got.notes == (
            "sensor.air: unit not read (GET /api/states/sensor.air: HTTP 404)",
        )

    async def test_a_failed_history_is_noted(self) -> None:
        class Down(FakeClient):
            async def read_history(
                self,
                entities: Iterable[str],
                start: datetime,
                end: datetime,
            ) -> ha.History:
                raise ha.HomeAssistantError("GET /api/history: HTTP 502")

        got = await ha.record_inputs(
            Down(),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(air="sensor.air"),
            self.START,
            NOW,
        )
        assert got.air is None
        assert got.notes[0].startswith("not read")


class TestReviewRegressions:
    def test_an_omitted_entity_is_an_empty_series(self) -> None:
        doc = [
            [
                {
                    "entity_id": "sensor.a",
                    "state": "1",
                    "last_changed": NOW.isoformat(),
                }
            ]
        ]
        assert ha.history_for(doc, ["sensor.a", "sensor.b"]) == {
            "sensor.a": [(NOW, 1.0)],
            "sensor.b": [],
        }
        assert ha.history_for([], ["sensor.a"]) == {"sensor.a": []}

    def test_humidity_is_a_percentage(self) -> None:
        assert ha.percent(41.0, "%") == 41.0
        with pytest.raises(ValueError, match="not a relative humidity unit"):
            ha.percent(10.0, "g/m³")
        with pytest.raises(ValueError, match="not a relative humidity"):
            ha.percent(140.0, "%")

    def test_covers_start(self) -> None:
        assert ha.covers_start([(NOW, 1.0)], NOW)
        assert not ha.covers_start([(NOW + timedelta(minutes=6), 1.0)], NOW)
        assert not ha.covers_start([], NOW)


@pytest.mark.asyncio
class TestReviewRegressionsLive:
    START = NOW - timedelta(days=2)

    async def test_humidity_in_another_unit_is_the_default(self) -> None:
        client = FakeClient({"sensor.rh": _s("sensor.rh", 10.0, "g/m³")})
        source = _source(client, humidity="sensor.rh")
        env = await source.read()
        assert env.humidity == sim.Environment(ambient_f=60.0).humidity
        assert any("not a relative humidity unit" in n for n in source.notes)

    async def test_recorded_humidity_is_checked(self) -> None:
        client = FakeClient(
            {"sensor.rh": _s("sensor.rh", 40.0, "%")},
            {"sensor.rh": [(self.START, 40.0), (NOW, 140.0)]},
        )
        got = await ha.record_inputs(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(humidity="sensor.rh"),
            self.START,
            NOW,
        )
        assert got.humidity == [(self.START, 40.0)]
        assert any("outside 0-100" in n for n in got.notes)
        wrong = FakeClient(
            {"sensor.rh": _s("sensor.rh", 4.0, "g/m³")},
            {"sensor.rh": [(self.START, 4.0)]},
        )
        got = await ha.record_inputs(
            wrong,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(humidity="sensor.rh"),
            self.START,
            NOW,
        )
        assert got.humidity is None

    async def test_part_histories_leave_the_heaters_flag(self) -> None:
        late = NOW - timedelta(hours=10)
        series = long_draw(ended_hours_ago=5)
        series["sensor.pump"] = [(late, 0.0)]
        client = FakeClient(UNITS, series)
        got = await ha.record_inputs(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(
                meter_volume="sensor.volume", circulation_speed="sensor.pump"
            ),
            self.START,
            NOW,
        )
        assert (got.drawing, got.circulating) == (None, None)
        assert sum("covers only part" in n for n in got.notes) == 2

    async def test_a_pump_read_only_late_is_unknown_for_the_inlet(self) -> None:
        series = long_draw(ended_hours_ago=5)
        # One idle reading an hour ago: before it, nobody knows.
        series["sensor.pump"] = [(NOW - timedelta(hours=1), 0.0)]
        client = FakeClient(UNITS, series)
        source = _source(client, circulation_speed="sensor.pump", **INLET)
        assert (await source.read()).inlet_f is None
        assert any(
            n.startswith("inlet: the circulation's runs are unknown")
            for n in source.notes
        )

    async def test_an_omitted_entity_in_the_record_is_no_history(self) -> None:
        class Omits(FakeClient):
            async def read_history(
                self,
                entities: Iterable[str],
                start: datetime,
                end: datetime,
            ) -> ha.History:
                return ha.History({}, {})

        got = await ha.record_inputs(
            Omits({"sensor.air": _s("sensor.air", 60.0, "°F")}),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(air="sensor.air", circulation_speed="sensor.pump"),
            self.START,
            NOW,
        )
        assert got.air is None
        assert any("air: no history" in n for n in got.notes)


class TestTheSecondReview:
    def test_outages_run_to_the_next_number(self) -> None:
        def row(at: datetime, state: str) -> dict[str, str]:
            return {
                "entity_id": "sensor.m",
                "state": state,
                "last_changed": at.isoformat(),
            }

        a, b, c = NOW, NOW + timedelta(minutes=5), NOW + timedelta(minutes=9)
        doc = [[row(a, "0"), row(b, "unavailable"), row(c, "0.1")]]
        assert ha.parse_outages(doc, c + timedelta(hours=1)) == {
            "sensor.m": [(b, c)]
        }
        tail = [[row(a, "0"), row(b, "unknown")]]
        assert ha.parse_outages(tail, c) == {"sensor.m": [(b, c)]}
        # Left out of the readings, as before.
        assert ha.parse_history(doc) == {"sensor.m": [(a, 0.0), (c, 0.1)]}

    def test_a_null_forecast_is_an_error(self) -> None:
        doc = {"service_response": {"weather.home": {"forecast": None}}}
        with pytest.raises(ha.HomeAssistantError, match="no forecast"):
            ha.parse_forecast(doc, "weather.home")

    def test_rpm(self) -> None:
        assert ha.to_rpm(1200.0, "RPM") == 1200.0
        assert ha.to_rpm(5.0, "Hz") == 300.0
        with pytest.raises(ValueError, match="rotational speed"):
            ha.to_rpm(40.0, "%")
        with pytest.raises(ValueError, match="rotational speed"):
            ha.to_rpm(40.0, None)

    def test_busy(self) -> None:
        x = [(_t(0), _t(1)), (_t(3), _t(4))]
        assert ha.busy(x, [(_t(0.5), _t(2))]) == [
            (_t(0), _t(2)),
            (_t(3), _t(4)),
        ]


@pytest.mark.asyncio
class TestTheSecondReviewLive:
    START = NOW - timedelta(days=2)

    async def test_a_pump_in_hz_is_running(self) -> None:
        series = long_draw(ended_hours_ago=5)
        since = NOW - ha.INLET_LOOKBACK
        # 5 Hz, 300 rpm, through the draw: it overlapped a run.
        ended = NOW - timedelta(hours=5)
        series["sensor.pump"] = [(since, 0.0)] + [
            (ended - timedelta(minutes=m), 5.0) for m in range(30, -10, -4)
        ]
        states = UNITS | {"sensor.pump": _s("sensor.pump", 5.0, "Hz")}
        source = _source(
            FakeClient(states, series), circulation_speed="sensor.pump", **INLET
        )
        assert (await source.read()).inlet_f is None
        assert "inlet: the plateau of 0 long draws" not in source.notes

    async def test_a_pump_in_no_speed_unit_is_unknown(self) -> None:
        series = long_draw(ended_hours_ago=5)
        series["sensor.pump"] = [(NOW - ha.INLET_LOOKBACK, 0.0)]
        states = UNITS | {"sensor.pump": _s("sensor.pump", 0.0, "%")}
        source = _source(
            FakeClient(states, series), circulation_speed="sensor.pump", **INLET
        )
        assert (await source.read()).inlet_f is None
        assert any("not a rotational speed unit" in n for n in source.notes)
        got = await ha.record_inputs(
            FakeClient(states, {"sensor.pump": [(self.START, 0.0)]}),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(circulation_speed="sensor.pump"),
            self.START,
            NOW,
        )
        assert got.circulating is None
        assert any("not a rotational speed unit" in n for n in got.notes)

    async def test_a_pump_outage_skips_the_draw_for_the_inlet(self) -> None:
        series = long_draw(ended_hours_ago=5)
        series["sensor.pump"] = [(NOW - ha.INLET_LOOKBACK, 0.0)]
        down = {
            "sensor.pump": [
                (NOW - timedelta(hours=6), NOW - timedelta(hours=4))
            ]
        }
        source = _source(
            FakeClient(UNITS, series, outages=down),
            circulation_speed="sensor.pump",
            **INLET,
        )
        assert (await source.read()).inlet_f is None
        clear = _source(
            FakeClient(UNITS, series), circulation_speed="sensor.pump", **INLET
        )
        assert (await clear.read()).inlet_f == pytest.approx(58.0)

    async def test_outages_after_valid_readings_count_as_busy(self) -> None:
        gap = (NOW - timedelta(hours=10), NOW - timedelta(hours=8))
        client = FakeClient(
            UNITS,
            {
                "sensor.volume": [(self.START, 0.0)],
                "sensor.pump": [(self.START, 0.0)],
            },
            outages={"sensor.volume": [gap], "sensor.pump": [gap]},
        )
        got = await ha.record_inputs(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(
                meter_volume="sensor.volume", circulation_speed="sensor.pump"
            ),
            self.START,
            NOW,
        )
        assert got.drawing == [gap]
        assert got.circulating == [gap]
        assert sum("counted as busy" in n for n in got.notes) == 2

    async def test_a_null_forecast_falls_back(self) -> None:
        class Null(FakeClient):
            async def forecast(
                self, entity: str
            ) -> tuple[list[ha.Reading], str | None]:
                return ha.parse_forecast(
                    {"service_response": {entity: {"forecast": None}}}, entity
                )

        states = {"sensor.air": _s("sensor.air", 70.0, "°F")}
        source = _source(
            Null(states), model=MODEL, air="sensor.air", weather="weather.home"
        )
        env = await source.read()
        assert env.ambient_f == 70.0


@pytest.mark.asyncio
class TestTheThirdReview:
    START = NOW - timedelta(days=2)

    async def test_a_short_draw_without_a_rate_is_drawing(self) -> None:
        at = NOW - timedelta(hours=3)
        client = FakeClient(
            UNITS,
            {
                "sensor.volume": [
                    (self.START, 0.0),
                    (at, 1.0),
                    (at + timedelta(seconds=30), 1.0),
                ],
                "sensor.pump": [(self.START, 0.0)],
            },
        )
        got = await ha.record_inputs(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(
                meter_volume="sensor.volume", circulation_speed="sensor.pump"
            ),
            self.START,
            NOW,
        )
        (drawn,) = got.drawing or []
        assert drawn[0] <= at <= drawn[1]

    async def test_air_and_humidity_outages_are_carried(self) -> None:
        gap = (NOW - timedelta(hours=10), NOW - timedelta(hours=8))
        client = FakeClient(
            {
                "sensor.air": _s("sensor.air", 60.0, "°F"),
                "sensor.rh": _s("sensor.rh", 40.0, "%"),
            },
            {
                "sensor.air": [(self.START, 60.0)],
                "sensor.rh": [(self.START, 40.0)],
            },
            outages={"sensor.air": [gap], "sensor.rh": [gap]},
        )
        got = await ha.record_inputs(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(air="sensor.air", humidity="sensor.rh"),
            self.START,
            NOW,
        )
        assert got.air_outages == (gap,)
        assert got.humidity_outages == (gap,)
        assert sum("left unobserved" in n for n in got.notes) == 2


class TestFullRows:
    def test_last_updated_wins(self) -> None:
        changed = NOW - timedelta(minutes=10)
        doc = [
            [
                {
                    "entity_id": "sensor.v",
                    "state": "1.0",
                    "last_changed": changed.isoformat(),
                    "last_updated": NOW.isoformat(),
                }
            ]
        ]
        assert ha.parse_history(doc) == {"sensor.v": [(NOW, 1.0)]}


class TestTheSixthReview:
    def test_pump_runs_hold_their_silence_across_a_change_of_clocks(
        self,
    ) -> None:
        from zoneinfo import ZoneInfo

        la = ZoneInfo("America/Los_Angeles")
        on = datetime(2026, 11, 1, 1, 55, tzinfo=la)  # PDT
        off = datetime(2026, 11, 1, 1, 57, tzinfo=la, fold=1)  # PST, 62 min on
        start, end = on - timedelta(hours=1), off + timedelta(hours=1)
        local = ha.pump_runs([(on, 1200.0), (off, 0.0)], start, end)
        utc = ha.pump_runs(
            [(on.astimezone(UTC), 1200.0), (off.astimezone(UTC), 0.0)],
            start.astimezone(UTC),
            end.astimezone(UTC),
        )
        assert local == utc
        ((a, b),) = local or []
        assert b - a == ha.PUMP_STALE

    def test_a_small_report_is_water_moving(self) -> None:
        at = NOW - timedelta(hours=1)
        spans = ha.volume_spans(
            [(at - timedelta(seconds=30), 0.002), (at, 0.25)]
        )
        assert spans == [(at - timedelta(seconds=30), at)]
        # A meter's noise at rest is not.
        assert ha.volume_spans([(at, -0.0017)]) == []


@pytest.mark.asyncio
class TestTheSixthReviewLive:
    START = NOW - timedelta(days=2)

    async def test_a_quarter_gallon_draw_is_drawing(self) -> None:
        at = NOW - timedelta(hours=3)
        client = FakeClient(
            UNITS,
            {
                "sensor.volume": [(self.START, 0.0), (at, 0.25)],
                "sensor.pump": [(self.START, 0.0)],
            },
        )
        got = await ha.record_inputs(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(
                meter_volume="sensor.volume", circulation_speed="sensor.pump"
            ),
            self.START,
            NOW,
        )
        (drawn,) = got.drawing or []
        assert drawn[0] < at <= drawn[1]


@pytest.mark.asyncio
class TestTheToken:
    TOKEN = "secret-token-value"

    def client_raising(
        self, exc: BaseException
    ) -> tuple[ha.HomeAssistantClient, Any]:
        class Response:
            async def __aenter__(self) -> None:
                raise exc

            async def __aexit__(self, *a: object) -> bool:
                return False

        class Session:
            def __init__(self) -> None:
                self.kw: dict[str, Any] = {}

            def request(self, method: str, url: str, **kw: Any) -> Any:
                self.kw = kw
                return Response()

        session = Session()
        return (
            ha.HomeAssistantClient(
                "http://ha.invalid",
                self.TOKEN,
                session=session,  # pyright: ignore[reportArgumentType]
            ),
            session,
        )

    async def test_a_request_error_never_carries_the_token(self) -> None:
        import aiohttp
        from multidict import CIMultiDict, CIMultiDictProxy
        from yarl import URL

        info = aiohttp.RequestInfo(
            URL("http://ha.invalid/api/states/sensor.a"),
            "GET",
            CIMultiDictProxy(
                CIMultiDict({"Authorization": f"Bearer {self.TOKEN}"})
            ),
        )
        client, session = self.client_raising(
            aiohttp.TooManyRedirects(info, ())
        )
        with pytest.raises(ha.HomeAssistantError) as err:
            await client.state("sensor.a")
        assert self.TOKEN not in str(err.value)
        assert "TooManyRedirects" in str(err.value)
        assert session.kw["allow_redirects"] is False

    async def test_an_error_body_is_scrubbed(self) -> None:
        class Response:
            status = 401

            async def text(self) -> str:
                # The token across the 200-character cut.
                return "x" * 190 + f" {TestTheToken.TOKEN} bad token"

            async def __aenter__(self) -> Response:
                return self

            async def __aexit__(self, *a: object) -> bool:
                return False

        class Session:
            def request(self, method: str, url: str, **kw: Any) -> Any:
                return Response()

        client = ha.HomeAssistantClient(
            "http://ha.invalid",
            self.TOKEN,
            session=Session(),  # pyright: ignore[reportArgumentType]
        )
        with pytest.raises(ha.HomeAssistantError) as err:
            await client.state("sensor.a")
        assert self.TOKEN[:5] not in str(err.value)
        assert "<tok" in str(err.value)


class TestRecordedUnits:
    @staticmethod
    def doc() -> tuple[
        list[list[dict[str, Any]]],
        tuple[datetime, datetime, datetime],
    ]:
        def row(at: datetime, state: str, unit: str | None) -> dict[str, Any]:
            r: dict[str, Any] = {
                "entity_id": "sensor.air",
                "state": state,
                "last_updated": at.isoformat(),
            }
            if unit is not None:
                r["attributes"] = {"unit_of_measurement": unit}
            return r

        a, b, c = (
            NOW - timedelta(hours=3),
            NOW - timedelta(hours=2),
            NOW - timedelta(hours=1),
        )
        # 68 °F, then the sensor switched to °C, then a row with no unit.
        return [
            [row(a, "68.0", "°F"), row(b, "20.0", "°C"), row(c, "21.0", None)]
        ], (a, b, c)

    def test_each_row_in_its_own_unit(self) -> None:
        doc, (a, b, _) = self.doc()
        assert ha.parse_units(doc) == {"sensor.air": ["°F", "°C", None]}
        got = ha.History(
            ha.history_for(doc, ["sensor.air"]), {}, ha.parse_units(doc)
        )
        rows, unread = got.converted("sensor.air", "°C", ha.to_f, NOW)
        assert rows == [(a, 68.0), (b, pytest.approx(68.0))]
        # The unitless row, unknown from itself to the end.
        assert unread == [(NOW - timedelta(hours=1), NOW)]

    def test_without_recorded_units_todays_unit(self) -> None:
        doc, (a, _, _) = self.doc()
        got = ha.History(ha.history_for(doc, ["sensor.air"]), {})
        rows, unread = got.converted("sensor.air", "°C", ha.to_f)
        # cast keeps the tuple's element type open against approx.
        assert cast(object, rows[0]) == (a, pytest.approx(154.4))
        assert unread == []

    def test_todays_unit_must_read(self) -> None:
        doc, _ = self.doc()
        got = ha.History(
            ha.history_for(doc, ["sensor.air"]), {}, ha.parse_units(doc)
        )
        with pytest.raises(ValueError, match="not a temperature unit"):
            got.converted("sensor.air", "%", ha.to_f)


@pytest.mark.asyncio
class TestRecordedUnitsLive:
    START = NOW - timedelta(days=2)

    async def test_a_unit_change_in_the_record(self) -> None:
        class Changed(FakeClient):
            async def read_history(
                self,
                entities: Iterable[str],
                start: datetime,
                end: datetime,
            ) -> ha.History:
                doc, _ = TestRecordedUnits.doc()
                return ha.History(
                    ha.history_for(doc, list(entities)),
                    {e: [] for e in entities},
                    {e: ha.parse_units(doc).get(e, []) for e in entities},
                )

        got = await ha.record_inputs(
            Changed({"sensor.air": _s("sensor.air", 21.0, "°C")}),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(air="sensor.air"),
            self.START,
            NOW,
        )
        assert [v for _, v in got.air or []] == [68.0, pytest.approx(68.0)]
        assert any("1 readings in no unit" in n for n in got.notes)


def _history_client(doc: Any, states: dict[str, ha.State]) -> FakeClient:
    """A client answering ``read_history`` from a raw history document,
    through the real parsers."""

    class Raw(FakeClient):
        async def read_history(
            self,
            entities: Iterable[str],
            start: datetime,
            end: datetime,
        ) -> ha.History:
            names = list(entities)
            units = ha.parse_units(doc)
            return ha.History(
                ha.history_for(doc, names),
                {n: ha.parse_outages(doc, end).get(n, []) for n in names},
                {n: units.get(n, []) for n in names},
            )

    return Raw(states)


def _row(
    entity: str, at: datetime, state: str, unit: str | None
) -> dict[str, Any]:
    r: dict[str, Any] = {
        "entity_id": entity,
        "state": state,
        "last_updated": at.isoformat(),
    }
    if unit is not None:
        r["attributes"] = {"unit_of_measurement": unit}
    return r


@pytest.mark.asyncio
class TestTheThirteenthReview:
    START = NOW - timedelta(days=2)

    async def test_a_rejected_air_reading_is_unobserved(self) -> None:
        h = timedelta(hours=1)
        doc = [
            [
                _row("sensor.air", self.START, "60.0", "°F"),
                _row("sensor.air", self.START + 4 * h, "70.0", None),
                _row("sensor.air", self.START + 8 * h, "80.0", "°F"),
            ]
        ]
        got = await ha.record_inputs(
            _history_client(doc, {"sensor.air": _s("sensor.air", 80.0, "°F")}),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(air="sensor.air"),
            self.START,
            NOW,
        )
        assert got.air_outages == ((self.START + 4 * h, self.START + 8 * h),)
        assert any("unobserved" in n for n in got.notes)

    async def test_a_rejected_volume_report_is_drawing(self) -> None:
        at = NOW - timedelta(hours=3)
        doc = [
            [
                _row("sensor.volume", self.START, "0.0", "gal"),
                _row("sensor.volume", at, "0.0", "furlongs"),
                _row("sensor.volume", at + timedelta(minutes=2), "0.0", "gal"),
            ],
            [_row("sensor.pump", self.START, "0", "rpm")],
        ]
        got = await ha.record_inputs(
            _history_client(doc, UNITS),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(
                meter_volume="sensor.volume", circulation_speed="sensor.pump"
            ),
            self.START,
            NOW,
        )
        assert got.drawing == [(at, at + timedelta(minutes=2))]

    async def test_a_first_reading_after_the_start_is_not_the_start(
        self,
    ) -> None:
        late = self.START + timedelta(minutes=4)
        assert not ha.covers_start([(late, 0.0)], self.START)
        assert ha.covers_start([(self.START, 0.0)], self.START)
        got = await ha.record_inputs(
            FakeClient(UNITS, {"sensor.pump": [(late, 0.0)]}),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(circulation_speed="sensor.pump"),
            self.START,
            NOW,
        )
        assert got.circulating is None

    async def test_a_pump_read_four_minutes_late_is_unknown_for_the_inlet(
        self,
    ) -> None:
        series = long_draw(ended_hours_ago=5)
        series["sensor.pump"] = [
            (NOW - ha.INLET_LOOKBACK + timedelta(minutes=4), 0.0)
        ]
        source = _source(
            FakeClient(UNITS, series), circulation_speed="sensor.pump", **INLET
        )
        assert (await source.read()).inlet_f is None


def _running_total(
    reports: list[ha.Reading], start: float = 1200.0
) -> list[ha.Reading]:
    """``reports`` (volume since the previous report) as a running
    total's readings, from ``start``: a baseline before the first."""
    first = reports[0][0] - timedelta(seconds=30)
    total, out = start, [(first, start)]
    for t, v in reports:
        total += v
        out.append((t, total))
    return out


class TestARunningTotal:
    def test_its_state_class_is_read(self) -> None:
        doc = _state("sensor.volume", "1234.5", "gal")
        doc["attributes"]["state_class"] = "total_increasing"
        s = ha.parse_state(doc)
        assert s.state_class == "total_increasing"
        assert (
            ha.parse_state(_state("sensor.air", "1", "°F")).state_class is None
        )

    def test_rises_are_reports_and_a_drop_is_a_reset(self) -> None:
        series = [
            (_t(0), 100.0),
            (_t(1), 101.5),
            (_t(2), 104.0),
            (_t(3), 3.0),
            (_t(4), 4.5),
        ]
        reports, resets = ha.reports_from_total(series)
        assert reports == [
            (_t(1), 1.5),
            (_t(2), 2.5),
            (_t(3), 0.0),
            (_t(4), 1.5),
        ]
        assert resets == 1
        assert ha.reports_from_total([(_t(0), 5.0)]) == ([], 0)

    def test_the_flag_overrides_the_state_class(self) -> None:
        total = ha.State("sensor.volume", 1.0, "gal", NOW, "total_increasing")
        plain = ha.State("sensor.volume", 1.0, "gal", NOW, "measurement")
        unset = ha.Entities(meter_volume="sensor.volume")
        assert ha.is_running_total(unset, total)
        assert ha.is_running_total(unset, replace(total, state_class="total"))
        assert not ha.is_running_total(unset, plain)
        assert not ha.is_running_total(replace(unset, meter_total=False), total)
        assert ha.is_running_total(replace(unset, meter_total=True), plain)

    def test_the_configuration_takes_the_flag(self) -> None:
        doc = {
            "home_assistant": TestTheConfiguration.DOC["home_assistant"]
            | {"entities": {"meter_volume": "sensor.v", "meter_total": True}}
        }
        s = ha.sources_from(doc, {"HA_TOKEN": "x"})
        assert s.entities.meter_total is True
        doc["home_assistant"]["entities"]["meter_total"] = "yes"
        with pytest.raises(ValueError, match="true or false"):
            ha.sources_from(doc, {"HA_TOKEN": "x"})


TOTAL_UNITS = UNITS | {
    "sensor.volume": ha.State(
        "sensor.volume", 0.0, "gal", NOW, "total_increasing"
    )
}


@pytest.mark.asyncio
class TestARunningTotalsInputs:
    async def test_the_inlet_reads_the_same_plateau(self) -> None:
        series = long_draw(ended_hours_ago=5)
        series["sensor.volume"] = _running_total(series["sensor.volume"])
        source = _source(FakeClient(TOTAL_UNITS, series), **INLET)
        assert (await source.read()).inlet_f == pytest.approx(58.0)
        assert any("running total" in n for n in source.notes)

    async def test_the_record_reads_the_same_draws(self) -> None:
        start = NOW - timedelta(days=2)
        reports = long_draw(ended_hours_ago=5)
        reports["sensor.volume"].insert(0, (start, 5.0))
        totals = dict(reports)
        # The total in force at the start is the baseline.
        totals["sensor.volume"] = [(start, 900.0)] + [
            (t, 900.0 + v)
            for t, v in _running_total(reports["sensor.volume"][1:], 0.0)[1:]
        ]
        entities = ha.Entities(meter_volume="sensor.volume")
        plain = await ha.record_inputs(
            FakeClient(UNITS, reports),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            entities,
            start,
            NOW,
        )
        total = await ha.record_inputs(
            FakeClient(TOTAL_UNITS, totals),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            entities,
            start,
            NOW,
        )
        assert total.drawing == plain.drawing
        assert plain.drawing
        assert any("running total" in n for n in total.notes)


def recorded_draw(
    ended_hours_ago: float, lookback: timedelta = ha.INLET_LOOKBACK
) -> dict[str, list[ha.Reading]]:
    """``long_draw`` as Home Assistant records it: the meter's history
    opens with the report in force at its start."""
    series = long_draw(ended_hours_ago=ended_hours_ago)
    series["sensor.volume"].insert(0, (NOW - lookback, 0.5))
    return series


@pytest.mark.asyncio
class TestTheWaterUse:
    async def test_the_flow_probe_and_mains_in_one_read(self) -> None:
        client = FakeClient(UNITS, recorded_draw(ended_hours_ago=5))
        use = await ha.read_water_use(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(**INLET),
            now=NOW,
        )
        assert use.cold is not None
        assert use.cold.t_cold_f == pytest.approx(58.0)
        assert use.runs == []
        assert use.busy == []
        assert use.probe == long_draw(ended_hours_ago=5)["sensor.inlet"]
        assert max(v for _, v in use.flow) == pytest.approx(2.0)
        assert use.notes == ("the plateau of 1 long draws",)
        ((names, since, until),) = client.history_calls
        assert set(names) == {"sensor.inlet", "sensor.volume"}
        assert (since, until) == (NOW - ha.INLET_LOOKBACK, NOW)

    async def test_the_live_inlet_is_its_mains(self) -> None:
        series = recorded_draw(ended_hours_ago=5)
        source = _source(FakeClient(UNITS, series), **INLET)
        use = await ha.read_water_use(
            FakeClient(UNITS, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(**INLET),
            now=NOW,
        )
        assert use.cold is not None
        assert (await source.read()).inlet_f == use.cold.t_cold_f
        assert source.notes == [f"inlet: {n}" for n in use.notes]

    async def test_unknown_runs_leave_the_flow(self) -> None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        use = await ha.read_water_use(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(circulation_speed="sensor.pump", **INLET),
            now=NOW,
        )
        assert use.runs is None
        assert use.cold is None
        assert use.flow
        assert any("runs are unknown" in n for n in use.notes)

    async def test_without_a_probe_the_flow_alone(self) -> None:
        series = recorded_draw(ended_hours_ago=5)
        series["sensor.pump"] = [(NOW - timedelta(hours=80), 0.0)]
        use = await ha.read_water_use(
            FakeClient(UNITS, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(
                meter_volume="sensor.volume", circulation_speed="sensor.pump"
            ),
            now=NOW,
        )
        assert (use.probe, use.runs, use.cold) == ([], [], None)
        assert use.flow
        assert use.notes == ()

    async def test_outages_are_busy(self) -> None:
        down = (NOW - timedelta(hours=10), NOW - timedelta(hours=9))
        use = await ha.read_water_use(
            FakeClient(  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
                UNITS,
                long_draw(ended_hours_ago=5),
                outages={"sensor.volume": [down]},
            ),
            ha.Entities(**INLET),
            now=NOW,
        )
        assert use.busy == [down]

    async def test_the_lookback_is_the_span(self) -> None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=30))
        use = await ha.read_water_use(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(**INLET),
            now=NOW,
            lookback=timedelta(hours=24),
        )
        assert use.cold is None
        assert use.notes == (
            "no long draw in the last 24 h to read the mains from",
        )
        assert client.history_calls[0][1] == NOW - timedelta(hours=24)

    async def test_a_failed_read_is_noted(self) -> None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        client.fail = {"sensor.volume"}
        use = await ha.read_water_use(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(**INLET),
            now=NOW,
        )
        assert (use.flow, use.runs, use.cold) == ([], None, None)
        assert use.notes[-1].startswith("not read")

    async def test_nothing_named_reads_nothing(self) -> None:
        client = FakeClient()
        use = await ha.read_water_use(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(air="sensor.air"),
            now=NOW,
        )
        assert use == ha.WaterUse([], [], [], [], None)
        assert client.history_calls == []

    async def test_a_short_draw_is_flow(self) -> None:
        """Two 1-gal reports 30 s apart: too short for the plateau, but
        water drawn for the book."""
        start = NOW - timedelta(hours=2)
        series = {
            "sensor.volume": [
                (NOW - ha.INLET_LOOKBACK, 0.0),
                (start, 1.0),
                (start + timedelta(seconds=30), 1.0),
            ]
        }
        use = await ha.read_water_use(
            FakeClient(UNITS, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(meter_volume="sensor.volume"),
            now=NOW,
        )
        assert sum(v for _, v in use.flow) > 0

    async def test_no_meter_history_is_no_flow(self) -> None:
        use = await ha.read_water_use(
            FakeClient(UNITS, {}),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(meter_volume="sensor.volume"),
            now=NOW,
        )
        assert use.flow == []
        assert use.notes == ("no history of sensor.volume over the span",)

    async def test_a_late_meter_history_starts_the_flow(self) -> None:
        first = NOW - timedelta(hours=10)
        series = {"sensor.volume": [(first, 0.0), (NOW, 0.0)]}
        use = await ha.read_water_use(
            FakeClient(UNITS, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(meter_volume="sensor.volume"),
            now=NOW,
        )
        assert use.flow[0][0] >= first
        assert any("covers only from" in n for n in use.notes)

    async def test_a_longer_lookback_reads_older_draws(self) -> None:
        lookback = timedelta(hours=96)
        use = await ha.read_water_use(
            FakeClient(UNITS, recorded_draw(80, lookback)),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(**INLET),
            now=NOW,
            lookback=lookback,
        )
        assert use.cold is not None
        assert use.cold.t_cold_f == pytest.approx(58.0)

    async def test_unknown_pump_spans_are_busy(self) -> None:
        series = recorded_draw(ended_hours_ago=5)
        late = NOW - timedelta(hours=10)
        series["sensor.pump"] = [(late, 0.0)]
        use = await ha.read_water_use(
            FakeClient(UNITS, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(circulation_speed="sensor.pump", **INLET),
            now=NOW,
        )
        assert use.runs is None
        assert use.busy == [(NOW - ha.INLET_LOOKBACK, late)]
        series["sensor.pump"] = [(NOW - ha.INLET_LOOKBACK, 0.0)]
        odd = UNITS | {"sensor.pump": _s("sensor.pump", 0.0, "%")}
        use = await ha.read_water_use(
            FakeClient(odd, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(circulation_speed="sensor.pump", **INLET),
            now=NOW,
        )
        assert use.runs is None
        assert use.busy == [(NOW - ha.INLET_LOOKBACK, NOW)]

    async def test_a_meter_outage_is_no_flow(self) -> None:
        down = (NOW - timedelta(hours=10), NOW - timedelta(hours=8))
        use = await ha.read_water_use(
            FakeClient(  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
                UNITS,
                recorded_draw(ended_hours_ago=5),
                outages={"sensor.volume": [down]},
            ),
            ha.Entities(meter_volume="sensor.volume"),
            now=NOW,
        )
        assert use.flow
        # No step's interval, [t, t + 10 s), reaches into it.
        step = timedelta(seconds=10)
        assert not any(
            v > 0 and down[0] < t + step and t < down[1] for t, v in use.flow
        )
        assert any("left out of the flow" in n for n in use.notes)

    async def test_a_pump_outage_leaves_the_runs_unknown(self) -> None:
        series = recorded_draw(ended_hours_ago=5)
        series["sensor.pump"] = [(NOW - ha.INLET_LOOKBACK, 0.0)]
        down = (NOW - timedelta(hours=30), NOW - timedelta(hours=28))
        client = FakeClient(UNITS, series, outages={"sensor.pump": [down]})
        entities = ha.Entities(circulation_speed="sensor.pump", **INLET)
        use = await ha.read_water_use(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            entities,
            now=NOW,
        )
        assert use.runs is None
        assert down in use.busy
        # The plateau skips only the draws over it.
        assert use.cold is not None
        source = _source(client, circulation_speed="sensor.pump", **INLET)
        assert (await source.read()).inlet_f == use.cold.t_cold_f

    @pytest.mark.parametrize("with_rate", [False, True])
    async def test_a_meter_silent_since_ends_the_flow(
        self, with_rate: bool
    ) -> None:
        """Its volume's last report ends the flow, a rate still reporting
        or not."""
        last = NOW - timedelta(hours=2)
        states = UNITS | {
            "sensor.volume": _s("sensor.volume", 0.0, "gal", 120),
            "sensor.rate": _s("sensor.rate", 0.0, "gal/min"),
        }
        series = recorded_draw(ended_hours_ago=5)
        series["sensor.rate"] = [(NOW - ha.INLET_LOOKBACK, 0.0)]
        use = await ha.read_water_use(
            FakeClient(states, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(
                meter_volume="sensor.volume",
                meter_flow="sensor.rate" if with_rate else None,
            ),
            now=NOW,
        )
        assert use.flow[-1][0] < last + timedelta(seconds=90)


class TestTheWaterUseBooked:
    """``read_water_use``'s flow through the book's silent-meter check."""

    @pytest.fixture
    def statuses(self, device_status_dict: dict[str, Any]) -> list[Any]:
        from nwp500.models import DeviceStatus

        out = []
        t = NOW - timedelta(hours=20)
        while t <= NOW:
            heating = NOW - timedelta(hours=4) <= t < NOW - timedelta(hours=3.5)
            out.append(
                (
                    t,
                    DeviceStatus.model_validate(
                        device_status_dict
                        | {
                            "tankUpperTemperature": 600,
                            "tankLowerTemperature": 598,
                            "compUse": 2 if heating else 1,
                            "heatUpperUse": 1,
                            "heatLowerUse": 1,
                        }
                    ),
                )
            )
            t += timedelta(minutes=1)
        return out

    async def _book(
        self,
        statuses: list[Any],
        states: dict[str, ha.State],
        outages: dict[str, list[ha.Span]] | None = None,
    ) -> Any:
        from nwp500 import sim_adapters as sa
        from nwp500.sim import site_example_params

        lookback = timedelta(hours=20)
        series = {"sensor.volume": [(NOW - lookback, 0.0)]}
        use = await ha.read_water_use(
            FakeClient(states, series, outages=outages),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(meter_volume="sensor.volume"),
            now=NOW,
            lookback=lookback,
        )
        return sa.book_from_history(
            statuses,
            site_example_params(),
            at=NOW,
            flow=[(t, sa.volume(v)) for t, v in use.flow],
        )

    @pytest.mark.asyncio
    async def test_a_quiet_meter_books(self, statuses: list[Any]) -> None:
        assert await self._book(statuses, UNITS) is not None

    @pytest.mark.asyncio
    async def test_an_outage_inside_is_refused(
        self, statuses: list[Any]
    ) -> None:
        down = (NOW - timedelta(hours=3), NOW - timedelta(hours=1, minutes=30))
        with pytest.raises(ValueError, match="silent"):
            await self._book(statuses, UNITS, {"sensor.volume": [down]})

    @pytest.mark.asyncio
    async def test_a_meter_silent_since_is_refused(
        self, statuses: list[Any]
    ) -> None:
        states = UNITS | {"sensor.volume": _s("sensor.volume", 0.0, "gal", 120)}
        with pytest.raises(ValueError, match="silent"):
            await self._book(statuses, states)


class TestALatePump:
    @pytest.mark.asyncio
    async def test_its_later_runs_and_unread_are_busy(self) -> None:
        series = recorded_draw(ended_hours_ago=5)
        first = NOW - timedelta(hours=10)
        ran = NOW - timedelta(hours=8)
        odd = (NOW - timedelta(hours=7), NOW - timedelta(hours=6))
        series["sensor.pump"] = [
            (first, 0.0),
            (ran, 2800.0),
            (ran + timedelta(minutes=2), 0.0),
            (odd[0], 40.0),
            (odd[1], 0.0),
        ]

        class Recorded(FakeClient):
            """Its pump's fourth reading recorded in a unit no speed is."""

            async def read_history(
                self, entities: Iterable[str], start: datetime, end: datetime
            ) -> ha.History:
                got = await super().read_history(entities, start, end)
                units: dict[str, list[str | None]] = {
                    "sensor.pump": ["rpm", "rpm", "rpm", "%", "rpm"]
                }
                return replace(got, units=units)

        use = await ha.read_water_use(
            Recorded(UNITS, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(circulation_speed="sensor.pump", **INLET),
            now=NOW,
        )
        assert use.runs is None
        for span in (
            (NOW - ha.INLET_LOOKBACK, first),
            (ran, ran + timedelta(minutes=2)),
            odd,
        ):
            assert any(a <= span[0] and span[1] <= b for a, b in use.busy)


@pytest.mark.asyncio
async def test_the_lookback_is_elapsed_across_a_clock_change() -> None:
    """72 h before noon after the spring change is 71 h of wall time:
    the read spans the 72 elapsed hours either way."""
    from zoneinfo import ZoneInfo

    local = datetime(
        2026, 3, 9, 12, 0, 1, tzinfo=ZoneInfo("America/Los_Angeles")
    )
    calls = []
    for now in (local, local.astimezone(UTC)):
        client = FakeClient(UNITS, {})
        await ha.read_water_use(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(meter_volume="sensor.volume"),
            now=now,
        )
        ((_, since, until),) = client.history_calls
        calls.append((since, until))
        assert until - since == ha.INLET_LOOKBACK
    assert calls[0] == calls[1]


@pytest.mark.asyncio
async def test_a_running_total_reads_the_same_water_use() -> None:
    reports = recorded_draw(ended_hours_ago=5)
    totals = dict(reports)
    # The reading in force at the start is the baseline.
    start = reports["sensor.volume"][0][0]
    totals["sensor.volume"] = [(start, 900.0)] + [
        (t, 900.0 + v)
        for t, v in _running_total(reports["sensor.volume"][1:], 0.0)[1:]
    ]
    entities = ha.Entities(**INLET)
    plain = await ha.read_water_use(
        FakeClient(UNITS, reports),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        entities,
        now=NOW,
    )
    total = await ha.read_water_use(
        FakeClient(TOTAL_UNITS, totals),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        entities,
        now=NOW,
    )
    assert total.flow == plain.flow
    assert total.cold == plain.cold
    assert any("running total" in n for n in total.notes)
    assert not any("covers only" in n for n in total.notes)


@pytest.mark.asyncio
async def test_the_last_reports_volume_is_kept() -> None:
    """A lone 1-gal report off the grid, the meter's last: its gallon is
    in the flow, and the flow ends after it."""
    last = NOW - timedelta(minutes=10) + timedelta(seconds=5)
    series = {"sensor.volume": [(NOW - ha.INLET_LOOKBACK, 0.0), (last, 1.0)]}
    states = UNITS | {
        "sensor.volume": ha.State("sensor.volume", 1.0, "gal", last)
    }
    use = await ha.read_water_use(
        FakeClient(states, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        ha.Entities(meter_volume="sensor.volume"),
        now=NOW,
    )
    step_min = 10 / 60
    assert sum(v for _, v in use.flow) * step_min == pytest.approx(1.0)
    assert use.flow[-1][0] < last + timedelta(seconds=90)


@pytest.mark.asyncio
async def test_a_report_before_an_outage_keeps_its_volume() -> None:
    """1 gal reported 5 s before a 2-minute outage: its gallon lands
    before the outage, none in it."""
    at = NOW - timedelta(hours=2) - timedelta(seconds=5)
    down = (at + timedelta(seconds=5), at + timedelta(minutes=2, seconds=5))
    series = {
        "sensor.volume": [
            (NOW - ha.INLET_LOOKBACK, 0.0),
            (at, 1.0),
            (NOW - timedelta(minutes=1), 0.0),
        ]
    }
    use = await ha.read_water_use(
        FakeClient(  # type: ignore[arg-type]
            UNITS, series, outages={"sensor.volume": [down]}
        ),
        ha.Entities(meter_volume="sensor.volume"),
        now=NOW,
    )
    step = timedelta(seconds=10)
    assert sum(v for _, v in use.flow) * step / timedelta(minutes=1) == (
        pytest.approx(1.0)
    )
    assert not any(
        v > 0 and down[0] < t + step and t < down[1] for t, v in use.flow
    )


def test_the_book_flow_keeps_every_reports_volume() -> None:
    """A slow trickle under the draw line is kept, to the gallon, and a
    rate fills the steps no report reaches."""
    start = NOW - timedelta(hours=1)
    trickle = [
        (start + timedelta(minutes=10, seconds=30 * k), 0.1) for k in range(12)
    ]
    flow = ha.book_flow(trickle, [], start, NOW)
    total = sum(v for _, v in flow) * (10 / 60)
    assert total == pytest.approx(1.2)
    rate = [(start + timedelta(minutes=40), 2.0)]
    flow = ha.book_flow([], rate, start, NOW)
    assert max(v for _, v in flow) == pytest.approx(2.0)


def test_a_first_report_after_the_baseline_keeps_its_volume() -> None:
    """A rise 30 s after the start: its interval reaches before the
    grid, and its gallon all lands on it."""
    start = datetime(2026, 10, 18, 12, tzinfo=UTC)
    flow = ha.book_flow([(start + timedelta(seconds=30), 1.0)], [], start, NOW)
    assert sum(v for _, v in flow) * (10 / 60) == pytest.approx(1.0)


def test_an_off_grid_outage_keeps_the_volume_before_it() -> None:
    """1 gal reported at 12:02:04, an outage from 12:02:05: the step
    the outage touches isn't given, and the gallon lands on the steps
    before it."""
    base = datetime(2026, 10, 18, 12, tzinfo=UTC)
    reports = [
        (base + timedelta(minutes=2, seconds=1), 0.0),
        (base + timedelta(minutes=2, seconds=4), 1.0),
    ]
    down = (
        base + timedelta(minutes=2, seconds=5),
        base + timedelta(minutes=4, seconds=5),
    )
    flow = ha.book_flow(reports, [], base, base + timedelta(minutes=10), [down])
    assert sum(v for _, v in flow) * (10 / 60) == pytest.approx(1.0)
    # It stays on the step nearest it, before the outage.
    assert all(t < down[0] for t, v in flow if v > 0)


def test_the_book_takes_a_final_report_once() -> None:
    """The book holds a reading a minute: the flow ends with a zero
    just after its last report, so a final 1-gal report is booked as
    1 gal, not more."""
    from nwp500 import sim_adapters as sa
    from nwp500.sim import site_example_params

    start = datetime(2026, 10, 18, 12, tzinfo=UTC)
    last = start + timedelta(minutes=30)
    flow = ha.book_flow(
        [(start, 0.0), (last - timedelta(seconds=30), 0.0), (last, 1.0)],
        [],
        start,
        last,
    )
    steps = sa.book_steps_from_changes(
        sa.ChangeRows(upper_f=[(start, 120.0)], lower_f=[(start, 120.0)]),
        start=start,
        end=last + timedelta(minutes=2),
        flow=flow,
        params=site_example_params(),
    )
    booked = sum(s.flow_gpm * s.seconds / 60 for s in steps)
    assert booked == pytest.approx(1.0)


def _booked_gal(
    flow: list[ha.Reading], start: datetime, end: datetime
) -> float:
    """The gallons the book takes of ``flow`` from ``start`` to ``end``."""
    from nwp500 import sim_adapters as sa
    from nwp500.sim import site_example_params

    steps = sa.book_steps_from_changes(
        sa.ChangeRows(upper_f=[(start, 120.0)], lower_f=[(start, 120.0)]),
        start=start,
        end=end,
        flow=flow,
        params=site_example_params(),
    )
    return sum(s.flow_gpm * s.seconds / 60 for s in steps)


@pytest.mark.asyncio
async def test_the_book_takes_a_report_at_now() -> None:
    """A 1-gal report on the grid at ``now``: the book up to ``now``
    takes its gallon."""
    series = {
        "sensor.volume": [
            (NOW - ha.INLET_LOOKBACK, 0.0),
            (NOW - timedelta(seconds=10), 0.0),
            (NOW, 1.0),
        ]
    }
    use = await ha.read_water_use(
        FakeClient(UNITS, series),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        ha.Entities(meter_volume="sensor.volume"),
        now=NOW,
    )
    got = _booked_gal(use.flow, NOW - timedelta(hours=1), NOW)
    assert got == pytest.approx(1.0)


@pytest.mark.parametrize("offset_s", [0, 3, 5, 9])
def test_a_book_on_any_clock_takes_each_gallon_once(offset_s: int) -> None:
    """The meter's last reports, 0 and 1 gal at 12:30:01 and 12:30:04: a
    book whose steps fall anywhere in the meter's takes the gallon
    once."""
    base = datetime(2026, 10, 18, 12, tzinfo=UTC)
    last = base + timedelta(minutes=30, seconds=4)
    reports = [(last - timedelta(seconds=3), 0.0), (last, 1.0)]
    flow = ha.book_flow(reports, [], base, last)
    start = base + timedelta(seconds=offset_s)
    end = last + timedelta(minutes=2)
    assert _booked_gal(flow, start, end) == pytest.approx(1.0)


@pytest.mark.parametrize("offset_s", [0, 3, 4, 9])
def test_a_book_to_an_off_grid_now_takes_the_last_gallon(offset_s: int) -> None:
    """The last reports, 0 and 1 gal at ``now`` - 3 s and ``now``, off
    the minute: a book only up to ``now`` takes the gallon."""
    now = datetime(2026, 10, 18, 12, 30, tzinfo=UTC) + timedelta(
        seconds=offset_s
    )
    start = now - timedelta(hours=1)
    reports = [(now - timedelta(seconds=3), 0.0), (now, 1.0)]
    flow = ha.book_flow(reports, [], start, now)
    assert _booked_gal(flow, start, now) == pytest.approx(1.0)


def test_a_meter_dark_throughout_gives_no_flow() -> None:
    """Every step dark: no flow, and no walk of the steps per report."""
    start = datetime(2026, 10, 15, 12, tzinfo=UTC)
    end = start + timedelta(hours=72)
    reports = [(start + timedelta(seconds=30 * i), 0.1) for i in range(1, 8640)]
    assert ha.book_flow(reports, [], start, end, [(start, end)]) == []


def test_a_rate_reading_at_the_end_adds_no_earlier_flow() -> None:
    """The volume still, and the first 2 gal/min rate reading at
    ``now``: no step before ``now`` takes it."""
    start = NOW - timedelta(hours=1)
    flow = ha.book_flow([(start, 0.0)], [(NOW, 2.0)], start, NOW)
    assert _booked_gal(flow, start, NOW) == pytest.approx(0.0)


def test_reports_outside_the_span_add_nothing() -> None:
    """A gallon the day before, half a gallon in the span, a gallon
    after it: only the half is booked."""
    start = datetime(2026, 10, 18, 12, tzinfo=UTC)
    end = start + timedelta(hours=1)
    reports = [
        (start - timedelta(days=1), 1.0),
        (start + timedelta(minutes=5), 0.5),
        (end + timedelta(minutes=1), 1.0),
    ]
    flow = ha.book_flow(reports, [], start, end)
    assert _booked_gal(flow, start, end) == pytest.approx(0.5)


def test_many_outages_keep_every_gallon_out_of_them() -> None:
    """72 h, a report every 30 s and an outage of a minute every 2:
    every reported gallon is kept, none in an outage."""
    start = datetime(2026, 10, 15, 12, tzinfo=UTC)
    end = start + timedelta(hours=72)
    down = [
        (
            start + timedelta(minutes=m, seconds=40),
            start + timedelta(minutes=m + 1, seconds=40),
        )
        for m in range(0, 72 * 60, 2)
    ]
    reports = [(start + timedelta(seconds=30 * i), 0.1) for i in range(1, 8640)]
    began = time.perf_counter()
    flow = ha.book_flow(reports, [], start, end, down)
    took = time.perf_counter() - began
    step = timedelta(seconds=10)
    assert sum(v for _, v in flow) * (10 / 60) == pytest.approx(0.1 * 8639)
    assert not any(
        v > 0 and any(x < t + step and t < y for x, y in down[:20])
        for t, v in flow[:400]
    )
    assert took < 5.0


@pytest.mark.asyncio
class TestTheWaterHistory:
    """``read_water_history`` reads; ``water_use`` computes, without
    the client."""

    @staticmethod
    def _series() -> dict[str, list[ha.Reading]]:
        series = recorded_draw(ended_hours_ago=5)
        start = NOW - ha.INLET_LOOKBACK
        series["sensor.pump"] = [
            (start, 0.0),
            (NOW - timedelta(hours=20), 2500.0),
            (NOW - timedelta(hours=19, minutes=45), 0.0),
        ]
        series["sensor.rate"] = [(start, 0.0)]
        return series

    @pytest.mark.parametrize(
        "names",
        [
            {},
            {"meter_volume": "sensor.volume"},
            {"circulation_speed": "sensor.pump", "meter_flow": "sensor.rate"},
        ],
    )
    async def test_it_is_read_water_use_apart(
        # ``Any``: mypy reads a ``dict[str, str]`` as maybe the flag.
        self,
        names: dict[str, Any],
    ) -> None:
        states = UNITS | {"sensor.rate": _s("sensor.rate", 0.0, "gal/min")}
        entities = replace(ha.Entities(**INLET), **names)
        client = FakeClient(states, self._series())
        history = await ha.read_water_history(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            entities,
            now=NOW,
        )
        whole = await ha.read_water_use(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            entities,
            now=NOW,
        )
        assert ha.water_use(history) == whole
        assert whole.flow
        if "circulation_speed" in names:
            assert whole.runs

    async def test_a_pump_state_not_read_leaves_its_runs_unknown(
        self,
    ) -> None:
        entities = ha.Entities(circulation_speed="sensor.pump", **INLET)
        client = FakeClient(UNITS, self._series(), fail={"sensor.pump"})
        history = await ha.read_water_history(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            entities,
            now=NOW,
        )
        assert "sensor.pump" in history.unread_states
        use = ha.water_use(history)
        assert use.runs is None
        assert any("HTTP 404" in n for n in use.notes)

    async def test_a_failed_read_raises_and_is_noted(self) -> None:
        client = FakeClient({}, self._series())
        with pytest.raises(ha.HomeAssistantError):
            await ha.read_water_history(
                client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
                ha.Entities(**INLET),
                now=NOW,
            )
        use = await ha.read_water_use(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(**INLET),
            now=NOW,
        )
        assert use.notes[0].startswith("not read")


@pytest.mark.asyncio
class TestTheWaterUseReadsNoPreference:
    """``water_use`` is in °F and gal/min throughout: the preferred
    units, process-wide, never enter it."""

    @staticmethod
    async def _history() -> ha.WaterHistory:
        return await ha.read_water_history(
            FakeClient(UNITS, recorded_draw(ended_hours_ago=5)),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(**INLET),
            now=NOW,
        )

    @pytest.fixture(autouse=True)
    def _reset(self) -> Iterator[None]:
        from nwp500.unit_system import reset_unit_system

        yield
        reset_unit_system()

    async def test_either_preference_reads_the_same_mains(self) -> None:
        from nwp500.unit_system import set_unit_system

        history = await self._history()
        set_unit_system("us_customary")
        us = ha.water_use(history)
        set_unit_system("metric")
        assert ha.water_use(history) == us
        assert us.cold is not None

    async def test_a_preference_changed_midway_changes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The preference flips to metric as the plateau's readings are
        taken in: the mains is what it was."""
        from nwp500 import sim_adapters as sa
        from nwp500.unit_system import set_unit_system

        history = await self._history()
        set_unit_system("us_customary")
        want = ha.water_use(history)
        finite = sa._finite  # pyright: ignore[reportPrivateUsage]

        def flipped(rows: Any) -> Any:
            set_unit_system("metric")
            return finite(rows)

        monkeypatch.setattr(sa, "_finite", flipped)
        set_unit_system("us_customary")
        assert ha.water_use(history) == want
