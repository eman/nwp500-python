"""The simulator's other inputs from Home Assistant
(``nwp500.sim_home_assistant``): the parsing, the rules, and the
environment source against a fake client."""

import math
from collections.abc import Iterable
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
