"""The simulator's other inputs from Home Assistant
(``nwp500.sim_home_assistant``): the parsing, the rules, and the
environment source against a fake client."""

import math
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

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
    def test_a_state(self):
        s = ha.parse_state(_state("sensor.air", "61.5", "°F"))
        assert (s.entity, s.value, s.unit, s.at) == (
            "sensor.air",
            61.5,
            "°F",
            NOW,
        )

    @pytest.mark.parametrize("value", ["unavailable", "unknown", "nan", "x"])
    def test_no_value_is_none(self, value):
        assert ha.parse_state(_state("sensor.air", value, "°F")).value is None

    def test_freshness_is_the_last_update(self):
        doc = _state("sensor.air", "61.5", "°F") | {
            "last_updated": (NOW - timedelta(hours=2)).isoformat(),
            "last_reported": NOW.isoformat(),
        }
        s = ha.parse_state(doc)
        assert s.at == NOW - timedelta(hours=2)
        assert not ha.fresh(s, NOW)
        assert ha.fresh(ha.parse_state(_state("sensor.air", 1, "°F")), NOW)

    def test_not_a_state(self):
        with pytest.raises(ha.HomeAssistantError):
            ha.parse_state(["no"])

    def test_a_history(self):
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

    def test_a_forecast(self):
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
    def test_temperatures(self):
        assert ha.to_f(20.0, "°C") == pytest.approx(68.0)
        assert ha.to_f(68.0, "°F") == 68.0
        assert ha.to_f(293.15, "K") == pytest.approx(68.0)
        with pytest.raises(ValueError, match="not a temperature"):
            ha.to_f(1.0, "%")

    def test_flows_and_volumes(self):
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
    def test_no_reading_is_unknown(self):
        assert ha.pump_runs([], _t(0), _t(60)) is None

    def test_runs_from_the_speed(self):
        speed = [(_t(-10), 0.0), (_t(5), 2800.0), (_t(7), 2810.0), (_t(9), 0.0)]
        assert ha.pump_runs(speed, _t(0), _t(60)) == [(_t(5), _t(9))]

    def test_a_silent_run_ends_after_five_minutes(self):
        assert ha.pump_runs([(_t(5), 2800.0)], _t(0), _t(60)) == [
            (_t(5), _t(10))
        ]

    def test_a_run_in_force_at_the_start(self):
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

    def test_it_reads(self):
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
    def test_what_is_wrong_is_named(self, change, environ, match):
        doc = {"home_assistant": self.DOC["home_assistant"] | change}
        with pytest.raises(ValueError, match=match):
            ha.sources_from(doc, environ)

    def test_the_token_variable_is_named(self):
        doc = {
            "home_assistant": self.DOC["home_assistant"]
            | {"token_env": "MY_HA"}
        }
        assert ha.sources_from(doc, {"MY_HA": "t"}).token == "t"

    def test_a_model_needs_every_term(self):
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
    ) -> None:
        self.states = states or {}
        self.series = history or {}
        self.hours = forecast
        self.fail = fail or set()
        self.history_calls: list[tuple[list[str], datetime, datetime]] = []

    async def state(self, entity: str) -> ha.State:
        if entity in self.fail or entity not in self.states:
            raise ha.HomeAssistantError(f"GET /api/states/{entity}: HTTP 404")
        return self.states[entity]

    async def history(self, entities, start, end):
        self.history_calls.append((list(entities), start, end))
        return {e: self.series.get(e, []) for e in entities}

    async def forecast(self, entity: str):
        if self.hours is None:
            raise ha.HomeAssistantError("no forecast")
        return self.hours


def _s(entity: str, value: float | None, unit: str, age_min: float = 0):
    return ha.State(entity, value, unit, NOW - timedelta(minutes=age_min))


def _source(client: Any, *, model=None, **entities: str) -> Any:
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
    async def test_projected_and_anchored(self):
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

    async def test_a_stale_reading_leaves_it_unanchored(self):
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

    async def test_without_a_model_the_reading_is_held(self):
        client = FakeClient({"sensor.air": _s("sensor.air", 20.0, "°C")})
        env = await _source(client, air="sensor.air").read()
        assert env.ambient_f == pytest.approx(68.0)

    async def test_nothing_read_is_no_air(self):
        source = _source(FakeClient(), air="sensor.air")
        env = await source.read()
        assert env.ambient_defaulted
        assert any("air: not read" in n for n in source.notes)


@pytest.mark.asyncio
class TestTheHumidity:
    async def test_fresh(self):
        client = FakeClient({"sensor.rh": _s("sensor.rh", 41.0, "%")})
        env = await _source(client, humidity="sensor.rh").read()
        assert env.humidity == 41.0

    async def test_stale_is_the_default(self):
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


INLET = {
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
    async def test_the_plateau_of_a_long_draw(self):
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        source = _source(client, **INLET)
        env = await source.read()
        assert env.inlet_f == pytest.approx(58.0)
        assert "inlet: the plateau of 1 long draws" in source.notes
        ((names, since, until),) = client.history_calls
        assert set(names) == {"sensor.inlet", "sensor.volume"}
        assert (since, until) == (NOW - timedelta(hours=72), NOW)

    async def test_a_short_draw_has_none(self):
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5, minutes=8))
        source = _source(client, **INLET)
        assert (await source.read()).inlet_f is None
        assert any("no long draw" in n for n in source.notes)

    async def test_a_draw_beyond_72_hours_has_none(self):
        client = FakeClient(UNITS, long_draw(ended_hours_ago=73))
        assert (await _source(client, **INLET).read()).inlet_f is None

    async def test_a_draw_during_circulation_has_none(self):
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

    async def test_unknown_circulation_has_none(self):
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        source = _source(client, circulation_speed="sensor.pump", **INLET)
        assert (await source.read()).inlet_f is None
        assert "inlet: the circulation's runs are unknown" in source.notes

    async def test_without_the_meters_volume(self):
        source = _source(FakeClient(UNITS), inlet="sensor.inlet")
        assert (await source.read()).inlet_f is None
        assert any("meter's volume" in n for n in source.notes)

    async def test_a_failed_read_is_the_default(self):
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        client.fail = {"sensor.volume"}
        source = _source(client, **INLET)
        assert (await source.read()).inlet_f is None
        assert any(n.startswith("inlet: not read") for n in source.notes)


@pytest.mark.asyncio
class TestCompose:
    async def test_no_air_from_the_source_is_the_heaters(self):
        heater_env = sim.Environment(ambient_f=75.0)

        class Heater:
            async def read(self) -> Any:
                return sim_live.HeaterReading(
                    state=sim.HeaterState(upper_f=130.0, lower_f=110.0),
                    settings=sim.Settings(setpoint_f=140.0),
                    environment=heater_env,
                    params=None,
                    status=None,  # pyright: ignore[reportArgumentType]
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
    def test_runs_joined_across_short_gaps(self):
        flow = [(_t(0), 2.0), (_t(10 / 60), 2.0), (_t(0.5), 2.0), (_t(5), 0.0)]
        assert ha.draw_spans(flow) == [(_t(0), _t(0.5) + timedelta(seconds=10))]

    def test_a_long_gap_is_two_draws(self):
        flow = [(_t(0), 2.0), (_t(1), 2.0)]
        assert len(ha.draw_spans(flow)) == 2


@pytest.mark.asyncio
class TestTheRecord:
    START = NOW - timedelta(days=2)

    async def test_the_air_humidity_draws_and_runs(self):
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
            FakeClient(states, series),  # pyright: ignore[reportArgumentType]
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

    async def test_coverage_and_missing_parts_are_noted(self):
        late = NOW - timedelta(hours=10)
        got = await ha.record_inputs(
            FakeClient(  # pyright: ignore[reportArgumentType]
                {"sensor.air": _s("sensor.air", 60.0, "°F")},
                {"sensor.air": [(late, 60.0)]},
            ),
            ha.Entities(air="sensor.air", circulation_speed="sensor.pump"),
            self.START,
            NOW,
        )
        assert got.air == [(late, 60.0)]
        assert any("covers only from" in n for n in got.notes)
        assert got.circulating is None
        assert any("circulation: no speed reading" in n for n in got.notes)

    async def test_a_failed_read_is_noted(self):
        client = FakeClient()
        got = await ha.record_inputs(
            client,  # pyright: ignore[reportArgumentType]
            ha.Entities(air="sensor.air"),
            self.START,
            NOW,
        )
        assert (got.air, got.drawing) == (None, None)
        assert got.notes == (
            "sensor.air: unit not read (GET /api/states/sensor.air: HTTP 404)",
        )

    async def test_a_failed_history_is_noted(self):
        class Down(FakeClient):
            async def history(self, entities, start, end):
                raise ha.HomeAssistantError("GET /api/history: HTTP 502")

        got = await ha.record_inputs(
            Down(),  # pyright: ignore[reportArgumentType]
            ha.Entities(air="sensor.air"),
            self.START,
            NOW,
        )
        assert got.air is None
        assert got.notes[0].startswith("not read")
