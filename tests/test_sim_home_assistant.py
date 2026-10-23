"""The simulator's other inputs from Home Assistant
(``nwp500.sim_home_assistant``): the parsing, the rules, and the
environment source against a fake client."""

import math
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
#: The household's hot water demand: on while it draws.
DEMAND = "binary_sensor.demand"
#: A history row: a number, or a state such as ``on``.
Row = tuple[datetime, Any]
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


class TestDemandSpans:
    def test_on_is_drawing(self) -> None:
        rows = [(_t(-10), "off"), (_t(5), "on"), (_t(9), "off")]
        assert ha.demand_spans(rows, _t(0), _t(60)) == ([(_t(5), _t(9))], [])

    def test_a_draw_in_force_at_either_end_is_cut_there(self) -> None:
        rows = [(_t(-10), "on"), (_t(2), "off"), (_t(58), "on")]
        assert ha.demand_spans(rows, _t(0), _t(60)) == (
            [(_t(0), _t(2)), (_t(58), _t(60))],
            [],
        )

    def test_unavailable_unknown_and_before_the_first_row_are_dark(
        self,
    ) -> None:
        rows = [
            (_t(5), "off"),
            (_t(10), "unavailable"),
            (_t(12), "On"),
            (_t(20), "unknown"),
            (_t(25), "off"),
        ]
        assert ha.demand_spans(rows, _t(0), _t(60)) == (
            [(_t(12), _t(20))],
            [(_t(0), _t(5)), (_t(10), _t(12)), (_t(20), _t(25))],
        )

    def test_no_rows_is_dark_throughout(self) -> None:
        assert ha.demand_spans([], _t(0), _t(60)) == ([], [(_t(0), _t(60))])


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
        demand = {"entities": {"demand": DEMAND}}
        doc = {"home_assistant": self.DOC["home_assistant"] | demand}
        assert ha.sources_from(doc, {"HA_TOKEN": "x"}).entities.demand == DEMAND
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
            # The meter's draws are the demand entity's now.
            (
                {"entities": {"meter_volume": "sensor.volume"}},
                {"HA_TOKEN": "x"},
                "unknown",
            ),
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
        history: dict[str, list[Row]] | None = None,
        forecast: tuple[list[ha.Reading], str | None] | None = None,
        fail: set[str] | None = None,
        outages: dict[str, list[ha.Span]] | None = None,
        outdoor: list[ha.Reading] | None = None,
    ) -> None:
        self.outdoor = outdoor
        self.outdoor_calls = 0
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
        names = list(entities)
        return ha.History(
            {
                e: [r for r in self.series.get(e, []) if _numeric(r)]
                for e in names
            },
            {e: self.down.get(e, []) for e in names},
            # Every row as Home Assistant writes it, a binary sensor's
            # ``on`` and ``off`` included.
            states={
                e: [(t, str(v)) for t, v in self.series.get(e, [])]
                for e in names
            },
        )

    async def forecast(
        self, entity: str
    ) -> tuple[list[ha.Reading], str | None]:
        if self.hours is None:
            raise ha.HomeAssistantError("no forecast")
        return self.hours

    async def outdoor_history(
        self, entity: str, start: datetime, end: datetime
    ) -> list[ha.Reading]:
        self.outdoor_calls += 1
        if self.outdoor is None:
            raise ha.HomeAssistantError("no history")
        return self.outdoor


def _numeric(row: tuple[datetime, Any]) -> bool:
    return not isinstance(row[1], str)


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
) -> dict[str, list[Row]]:
    """A draw: the demand on through it, off since long before, and the
    probe every 30 s, warm at rest and at the mains once the draw has
    run."""
    end = NOW - timedelta(hours=ended_hours_ago)
    start = end - timedelta(minutes=minutes)
    demand: list[Row] = [
        (NOW - timedelta(days=30), "off"),
        (start, "on"),
        (end, "off"),
    ]
    probe: list[Row] = [(start - timedelta(hours=1), 66.0)]
    t = start
    while t < end:
        t += timedelta(seconds=30)
        into = (t - start).total_seconds()
        probe.append((t, 66.0 - min(into / 300.0, 1.0) * (66.0 - mains_f)))
    # The pipe stays at the mains a few minutes after the draw.
    probe.extend(
        (end + timedelta(seconds=30 * k), mains_f) for k in range(1, 7)
    )
    probe.append((end + timedelta(minutes=20), 65.0))
    return {"sensor.inlet": probe, DEMAND: demand}


class _InletEntities(TypedDict):
    inlet: str
    demand: str


INLET: _InletEntities = {"inlet": "sensor.inlet", "demand": DEMAND}
UNITS = {
    "sensor.inlet": _s("sensor.inlet", 65.0, "°F"),
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
        assert set(names) == {"sensor.inlet", DEMAND}
        assert (since, until) == (NOW - timedelta(hours=72), NOW)

    async def test_a_probe_steady_through_the_tail(self) -> None:
        """A history writes only changes: a probe at the mains from
        minute 5 to the end has one row there, and still a plateau."""
        series = long_draw(ended_hours_ago=5)
        end = NOW - timedelta(hours=5)
        start = end - timedelta(minutes=15)
        series["sensor.inlet"] = [
            (start - timedelta(hours=1), 66.0),
            (start + timedelta(minutes=5), 58.0),
            (end + timedelta(minutes=20), 65.0),
        ]
        source = _source(FakeClient(UNITS, series), **INLET)
        assert (await source.read()).inlet_f == pytest.approx(58.0)

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

    async def test_without_the_demand(self) -> None:
        source = _source(FakeClient(UNITS), inlet="sensor.inlet")
        assert (await source.read()).inlet_f is None
        assert any("demand entity" in n for n in source.notes)

    async def test_a_history_without_states_is_noted(self) -> None:
        class NoStates(FakeClient):
            async def read_history(
                self, entities: Iterable[str], start: datetime, end: datetime
            ) -> ha.History:
                got = await super().read_history(entities, start, end)
                return replace(got, states=None)

        source = _source(NoStates(UNITS, long_draw(ended_hours_ago=5)), **INLET)
        assert (await source.read()).inlet_f is None
        assert any("no states in the history" in n for n in source.notes)

    async def test_a_failed_read_is_the_default(self) -> None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        client.fail = {"sensor.inlet"}
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


@pytest.mark.asyncio
class TestTheRecord:
    START = NOW - timedelta(days=2)

    async def test_the_air_humidity_draws_and_runs(self) -> None:
        series = long_draw(ended_hours_ago=5)
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
                demand=DEMAND,
                circulation_speed="sensor.pump",
            ),
            self.START,
            NOW,
        )
        assert got.air == [(self.START, 68.0), (NOW, pytest.approx(69.8))]
        assert got.humidity == [(self.START, 40.0)]
        assert got.circulating == []
        (drawn,) = got.drawing or []
        assert drawn[1] - drawn[0] == timedelta(minutes=15)
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
        series[DEMAND] = [(late, "off"), *series[DEMAND][1:]]
        series["sensor.pump"] = [(late, 0.0)]
        client = FakeClient(UNITS, series)
        got = await ha.record_inputs(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(demand=DEMAND, circulation_speed="sensor.pump"),
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
                DEMAND: [
                    (self.START, "off"),
                    (gap[0], "unavailable"),
                    (gap[1], "off"),
                ],
                "sensor.pump": [(self.START, 0.0)],
            },
            outages={"sensor.pump": [gap]},
        )
        got = await ha.record_inputs(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(demand=DEMAND, circulation_speed="sensor.pump"),
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


@pytest.mark.asyncio
async def test_the_inlet_looks_back_elapsed_time_across_a_clock_change() -> (
    None
):
    """72 h before noon after the spring change is 71 h of wall time:
    the inlet's read spans the 72 elapsed hours either way."""
    from zoneinfo import ZoneInfo

    local = datetime(
        2026, 3, 9, 12, 0, 1, tzinfo=ZoneInfo("America/Los_Angeles")
    )
    calls = []
    for now in (local, local.astimezone(UTC)):
        client = FakeClient(UNITS, {})
        await ha.HomeAssistantEnvironment(
            client,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            ha.Entities(**INLET),
            start=now,
            until=now + timedelta(hours=6),
            now=now,
        ).read()
        ((_, since, until),) = client.history_calls
        calls.append((since, until))
        assert until - since == ha.INLET_LOOKBACK
    assert calls[0] == calls[1]


@pytest.mark.asyncio
class TestTheInletReadsNoPreference:
    """The inlet's plateau is in °F and gal/min throughout: the
    preferred units, process-wide, never enter it."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> Iterator[None]:
        from nwp500.unit_system import reset_unit_system

        yield
        reset_unit_system()

    @staticmethod
    async def _inlet() -> float | None:
        client = FakeClient(UNITS, long_draw(ended_hours_ago=5))
        env = await _source(client, **INLET).read()
        return cast("float | None", env.inlet_f)

    async def test_either_preference_reads_the_same_mains(self) -> None:
        from nwp500.unit_system import set_unit_system

        set_unit_system("us_customary")
        us = await self._inlet()
        set_unit_system("metric")
        assert await self._inlet() == us
        assert us == pytest.approx(58.0)

    async def test_a_preference_changed_midway_changes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The preference flips to metric as the plateau's readings are
        taken in: the mains is what it was."""
        from nwp500 import sim_adapters as sa
        from nwp500.unit_system import set_unit_system

        set_unit_system("us_customary")
        want = await self._inlet()
        finite = sa._finite  # pyright: ignore[reportPrivateUsage]

        def flipped(rows: Any) -> Any:
            set_unit_system("metric")
            return finite(rows)

        monkeypatch.setattr(sa, "_finite", flipped)
        set_unit_system("us_customary")
        assert await self._inlet() == want


def _outdoor(t: datetime) -> float:
    """A day's swing of 20 °F about 50 °F."""
    return 50.0 + 10.0 * math.sin(2 * math.pi * t.timestamp() / 86400)


#: The outdoor air's history, hourly, from 4 days back, °F.
OUTDOOR_HISTORY = [
    (NOW - timedelta(hours=h), _outdoor(NOW - timedelta(hours=h)))
    for h in range(96, -1, -1)
]


def _at_heater(t: datetime) -> float:
    """``MODEL``'s air at the heater for ``_outdoor``."""
    return MODEL.damping * _outdoor(t - MODEL.lag) + MODEL.offset_f


HEATER = ha.HeaterEntities(
    heard="sensor.heard",
    upper="sensor.upper",
    lower="sensor.lower",
    compressor="binary_sensor.compressor",
    ambient="sensor.heater_air",
)


def _fitting(
    client: Any, heater: ha.HeaterEntities | None = None, **entities: Any
) -> Any:
    return ha.HomeAssistantEnvironment(
        client,  # pyright: ignore[reportArgumentType]
        ha.Entities(weather="weather.home", **entities),
        start=NOW,
        until=NOW + timedelta(hours=6),
        now=NOW,
        heater=heater,
    )


@pytest.mark.asyncio
class TestTheAirFitted:
    """With a weather entity and no model, the environment fits one."""

    async def test_on_the_air_beside_the_heater(self) -> None:
        series = [
            (NOW - timedelta(minutes=m), _at_heater(NOW - timedelta(minutes=m)))
            for m in range(3 * 1440, -1, -30)
        ]
        client = FakeClient(
            {"sensor.air": _s("sensor.air", series[-1][1], "°F")},
            {"sensor.air": series},
            forecast=OUTDOOR,
            outdoor=OUTDOOR_HISTORY,
        )
        source = _fitting(client, air="sensor.air")
        env = await source.read()
        fitted = source.fitted_air
        assert fitted is not None
        assert fitted.model.lag == MODEL.lag
        assert fitted.model.damping == pytest.approx(MODEL.damping, abs=0.02)
        assert isinstance(env.ambient_f, tuple)
        assert any(
            "fitted to the air beside the heater" in n for n in source.notes
        )
        assert any(
            "anchored to the reading beside the heater" in n
            for n in source.notes
        )

    async def test_on_the_heaters_own_reading_while_it_runs(self) -> None:
        """Idle, the heater reads its cabinet, 6 °F warm: left out."""
        compressor: list[Row] = []
        air: list[Row] = []
        for h in range(72, -1, -1):
            at = NOW - timedelta(hours=h)
            on = h % 3 == 1
            compressor.append((at, "on" if on else "off"))
            for m in range(0, 60, 5):
                t = at + timedelta(minutes=m)
                if t <= NOW:
                    air.append((t, _at_heater(t) + (0.0 if on else 6.0)))
        client = FakeClient(
            {"sensor.heater_air": _s("sensor.heater_air", air[-1][1], "°F")},
            {"sensor.heater_air": air, "binary_sensor.compressor": compressor},
            forecast=OUTDOOR,
            outdoor=OUTDOOR_HISTORY,
        )
        source = _fitting(client, HEATER)
        env = await source.read()
        fitted = source.fitted_air
        assert fitted is not None
        assert fitted.model.offset_f == pytest.approx(MODEL.offset_f, abs=1.0)
        assert isinstance(env.ambient_f, tuple)
        assert any(
            "fitted to the heater's own air reading" in n for n in source.notes
        )
        assert any(
            "anchored to the heater's own reading" in n for n in source.notes
        )

    async def test_a_day_of_readings_is_needed(self) -> None:
        series = [
            (NOW - timedelta(hours=h), 60.0 + h) for h in range(12, -1, -1)
        ]
        client = FakeClient(
            {"sensor.air": _s("sensor.air", 60.0, "°F")},
            {"sensor.air": series},
            forecast=OUTDOOR,
            outdoor=OUTDOOR_HISTORY,
        )
        source = _fitting(client, air="sensor.air")
        env = await source.read()
        assert source.fitted_air is None
        assert env.ambient_f == 60.0
        assert any("under the 24 h a fit needs" in n for n in source.notes)

    async def test_a_loose_fit_is_not_used(self) -> None:
        """Air that ignores the outdoor air: held, not projected."""
        series = [
            (NOW - timedelta(hours=h), 60.0 + (3.0 if h % 2 else -3.0))
            for h in range(72, -1, -1)
        ]
        client = FakeClient(
            {"sensor.air": _s("sensor.air", 63.0, "°F")},
            {"sensor.air": series},
            forecast=OUTDOOR,
            outdoor=OUTDOOR_HISTORY,
        )
        source = _fitting(client, air="sensor.air")
        env = await source.read()
        assert source.fitted_air is None
        assert env.ambient_f == 63.0
        assert any("too loosely" in n for n in source.notes)

    async def test_a_steady_air_has_no_fit(self) -> None:
        """A steady air follows nothing: no fit."""
        series = [(NOW - timedelta(hours=h), 60.0) for h in range(72, -1, -1)]
        client = FakeClient(
            {"sensor.air": _s("sensor.air", 60.0, "°F")},
            {"sensor.air": series},
            forecast=OUTDOOR,
            outdoor=OUTDOOR_HISTORY,
        )
        source = _fitting(client, air="sensor.air")
        env = await source.read()
        assert source.fitted_air is None
        assert env.ambient_f == 60.0
        assert any("held one value" in n for n in source.notes)

    async def test_only_readings_the_outdoor_history_covers(self) -> None:
        """Outdoor air for the last hour only: the model would hold it
        flat over three days of readings, so there is no fit."""
        series = [
            (NOW - timedelta(hours=72), 60.0),
            (NOW - timedelta(hours=36), 60.1),
            (NOW, 66.0),
        ]
        client = FakeClient(
            {"sensor.air": _s("sensor.air", 66.0, "°F")},
            {"sensor.air": series},
            forecast=OUTDOOR,
            outdoor=[(NOW - timedelta(hours=1), 50.0), (NOW, 60.0)],
        )
        source = _fitting(client, air="sensor.air")
        await source.read()
        assert source.fitted_air is None
        assert any("outdoor history covers" in n for n in source.notes)

    async def test_a_stale_heater_reading_is_no_anchor(self) -> None:
        """Still running, but the heater's air last changed 2 h ago."""
        compressor: list[Row] = [(NOW - timedelta(hours=72), "off")]
        air: list[Row] = [(NOW - timedelta(hours=72), 80.0)]
        for h in range(71, 1, -1):
            at = NOW - timedelta(hours=h)
            on = h % 3 == 1 or h == 2
            compressor.append((at, "on" if on else "off"))
            if on:
                for m in range(3, 60, 5):
                    t = at + timedelta(minutes=m)
                    air.append((t, _at_heater(t)))
            else:
                air.append((at, _at_heater(at) + 6.0))
        client = FakeClient(
            {"sensor.heater_air": _s("sensor.heater_air", air[-1][1], "°F")},
            {"sensor.heater_air": air, "binary_sensor.compressor": compressor},
            forecast=OUTDOOR,
            outdoor=OUTDOOR_HISTORY,
        )
        source = _fitting(client, HEATER)
        await source.read()
        assert source.fitted_air is not None
        assert any("unanchored" in n for n in source.notes)

    async def test_without_an_air_reading_there_is_nothing_to_fit(self) -> None:
        client = FakeClient(forecast=OUTDOOR, outdoor=OUTDOOR_HISTORY)
        source = _fitting(client)
        env = await source.read()
        assert env.ambient_defaulted
        assert any("no air reading to fit" in n for n in source.notes)
        assert client.outdoor_calls == 0

    async def test_a_given_model_is_not_refitted(self) -> None:
        client = FakeClient(forecast=OUTDOOR, outdoor=OUTDOOR_HISTORY)
        source = _source(client, model=MODEL, weather="weather.home")
        await source.read()
        assert client.outdoor_calls == 0
        assert source.fitted_air is None

    async def test_fitted_once(self) -> None:
        series = [
            (NOW - timedelta(minutes=m), _at_heater(NOW - timedelta(minutes=m)))
            for m in range(3 * 1440, -1, -30)
        ]
        client = FakeClient(
            {"sensor.air": _s("sensor.air", series[-1][1], "°F")},
            {"sensor.air": series},
            forecast=OUTDOOR,
            outdoor=OUTDOOR_HISTORY,
        )
        source = _fitting(client, air="sensor.air")
        await source.read()
        await source.read()
        assert client.outdoor_calls == 1
        assert sum("fitted to" in n for n in source.notes) == 1


class TestOutdoorHistory:
    @staticmethod
    def row(minutes: int, temperature: Any, unit: str | None) -> dict[str, Any]:
        stamp = (NOW - timedelta(minutes=minutes)).isoformat()
        attributes: dict[str, Any] = {"temperature": temperature}
        if unit is not None:
            attributes["temperature_unit"] = unit
        return {
            "entity_id": "weather.home",
            "state": "sunny",
            "attributes": attributes,
            "last_updated": stamp,
        }

    def test_each_row_with_its_own_unit(self) -> None:
        doc = [
            [
                self.row(0, 20.0, "°C"),
                self.row(60, 68.0, "°F"),
                self.row(30, None, "°C"),
                self.row(10, 21.0, None),
            ]
        ]
        assert ha.parse_outdoor_history(doc, "weather.home") == [
            (NOW - timedelta(minutes=60), 68.0, "°F"),
            (NOW - timedelta(minutes=10), 21.0, None),
            (NOW, 20.0, "°C"),
        ]

    def test_not_a_history(self) -> None:
        with pytest.raises(ha.HomeAssistantError):
            ha.parse_outdoor_history({}, "weather.home")

    @pytest.mark.asyncio
    async def test_the_client_converts_each_from_its_own_unit(self) -> None:
        """The entity switched from °F to °C: each reading is read in
        the unit it was recorded in, a row naming none in today's."""
        history = [
            [
                self.row(60, 68.0, "°F"),
                self.row(30, 21.0, None),
                self.row(0, 20.0, "°C"),
                self.row(5, 300.0, "K?"),
            ]
        ]
        state = {
            "entity_id": "weather.home",
            "state": "sunny",
            "attributes": {"temperature_unit": "°C"},
        }

        class Response:
            status = 200

            def __init__(self, body: Any) -> None:
                self.body = body

            async def json(self) -> Any:
                return self.body

            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *a: object) -> bool:
                return False

        class Session:
            def request(self, method: str, url: str, **kw: Any) -> Any:
                return Response(history if "/history/" in url else state)

        client = ha.HomeAssistantClient(
            "http://ha.invalid",
            "t",
            session=Session(),  # pyright: ignore[reportArgumentType]
        )
        got = await client.outdoor_history(
            "weather.home", NOW - timedelta(hours=2), NOW
        )
        assert got == [
            (NOW - timedelta(minutes=60), 68.0),
            (NOW - timedelta(minutes=30), pytest.approx(69.8)),
            (NOW, pytest.approx(68.0)),
        ]


class TestWhileRunning:
    ON = NOW - timedelta(hours=1)
    RUNS: ClassVar[list[tuple[datetime, str]]] = [
        (NOW - timedelta(hours=1), "on"),
        (NOW, "off"),
    ]

    def test_a_reading_from_before_the_run_settled_is_not_used(self) -> None:
        air = [
            (self.ON - timedelta(minutes=30), 80.0),  # idle, the cabinet
            (self.ON + timedelta(minutes=1), 75.0),  # not yet settled
            (self.ON + timedelta(minutes=25), 70.0),
        ]
        got, newest = ha._while_running(air, self.RUNS, NOW)  # pyright: ignore[reportPrivateUsage]
        assert got
        assert {v for _, v in got} == {70.0}
        assert got[0][0] == self.ON + timedelta(minutes=32)
        assert newest == air[-1]

    def test_nothing_while_the_sensor_is_unknown(self) -> None:
        air = [(self.ON + timedelta(minutes=3), 70.0)]
        gap = (self.ON + timedelta(minutes=20), self.ON + timedelta(minutes=40))
        got, _ = ha._while_running(air, self.RUNS, NOW, [gap])  # pyright: ignore[reportPrivateUsage]
        assert got
        assert not any(gap[0] <= t < gap[1] for t, _ in got)

    def test_a_repeated_on_row_is_one_run(self) -> None:
        """An attribute's update writes a row with the same state."""
        runs = [(self.ON + timedelta(minutes=m), "on") for m in range(60)]
        air = [(self.ON + timedelta(minutes=3), 70.0)]
        got, _ = ha._while_running(air, runs, NOW)  # pyright: ignore[reportPrivateUsage]
        assert len(got) == 5  # from 12 min, after the 3 min reading

    def test_the_newest_reading_keeps_its_own_instant(self) -> None:
        """Carried to 13:52, a reading from 12:03 is still from 12:03."""
        on = NOW - timedelta(hours=2)
        air = [(on + timedelta(minutes=3), 70.0)]
        got, newest = ha._while_running(air, [(on, "on")], NOW)  # pyright: ignore[reportPrivateUsage]
        assert got[-1][0] == NOW - timedelta(minutes=8)
        assert newest == air[0]


class TestHeld:
    def test_the_value_in_force_on_the_grid(self) -> None:
        rows = [(NOW + timedelta(seconds=25), 2.0), (NOW, 1.0)]
        got = ha.held(
            rows, NOW - timedelta(seconds=10), NOW + timedelta(seconds=40)
        )
        assert got == [
            (NOW, 1.0),
            (NOW + timedelta(seconds=10), 1.0),
            (NOW + timedelta(seconds=20), 1.0),
            (NOW + timedelta(seconds=30), 2.0),
            (NOW + timedelta(seconds=40), 2.0),
        ]

    def test_across_a_clock_change_by_elapsed_time(self) -> None:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Los_Angeles")
        # 01:30 PDT, then the clock falls back to 01:00 PST.
        start = datetime(2026, 11, 1, 1, 30, tzinfo=tz)
        end = start.astimezone(UTC) + timedelta(hours=1)
        got = ha.held([(start, 1.0)], start, end, timedelta(minutes=30))
        assert [t - got[0][0] for t, _ in got] == [
            timedelta(minutes=30 * k) for k in range(3)
        ]

    def test_readings_in_the_repeated_hour_in_order(self) -> None:
        """01:40 PDT comes before 01:10 PST, though its wall clock is later."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Los_Angeles")
        first = datetime(2026, 11, 1, 1, 40, tzinfo=tz)
        second = datetime(2026, 11, 1, 1, 10, fold=1, tzinfo=tz)
        assert second.astimezone(UTC) > first.astimezone(UTC)
        got = ha.held(
            [(second, 2.0), (first, 1.0)],
            first,
            second.astimezone(UTC) + timedelta(minutes=10),
            timedelta(minutes=10),
        )
        assert got[0][1] == 1.0
        assert got[-1][1] == 2.0
        assert [v for _, v in got].count(2.0) == 2

    def test_a_step_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            ha.held([], NOW, NOW, timedelta(0))


class TestHistoryKeptCurrent:
    def test_extended_merges_readings_units_states_and_outages(self) -> None:
        t = [NOW + timedelta(minutes=m) for m in range(4)]
        older = ha.History(
            {"sensor.a": [(t[0], 68.0)]},
            {"sensor.a": [(t[0], t[1])]},
            {"sensor.a": ["°F"]},
            {"sensor.a": [(t[0], "68.0")]},
        )
        newer = ha.History(
            {"sensor.a": [(t[1], 20.0), (t[3], 21.0)]},
            {"sensor.a": [(t[1], t[2])]},
            {"sensor.a": ["°C", "°C"]},
            {"sensor.a": [(t[1], "20.0"), (t[3], "21.0")]},
        )
        got = older.extended(newer)
        assert got.readings["sensor.a"] == [
            (t[0], 68.0),
            (t[1], 20.0),
            (t[3], 21.0),
        ]
        assert got.units == {"sensor.a": ["°F", "°C", "°C"]}
        assert got.outages["sensor.a"] == [(t[0], t[2])]
        assert got.states is not None
        assert [v for _, v in got.states["sensor.a"]] == [
            "68.0",
            "20.0",
            "21.0",
        ]
        f, unread = got.converted("sensor.a", "°C", ha.to_f, t[3])
        assert [v for _, v in f] == pytest.approx([68.0, 68.0, 69.8])
        assert unread == []

    def test_units_one_read_lacks_are_none(self) -> None:
        older = ha.History({"sensor.a": [(NOW, 1.0)]}, {})
        newer = ha.History({"sensor.a": [(NOW, 1.0)]}, {}, {"sensor.a": ["°F"]})
        assert older.extended(newer).units is None
        assert older.extended(newer).states is None

    def test_missing_units_stay_todays(self) -> None:
        """No unit recorded for an entity is today's unit, not a reading
        recorded with none: trimmed or merged, it still converts."""
        h = ha.History({"sensor.a": [(NOW, 20.0)]}, {}, {})
        for got in (h.since(NOW), h.extended(ha.History({}, {}, {}))):
            f, unread = got.converted("sensor.a", "°C", ha.to_f, NOW)
            assert [t for t, _ in f] == [NOW]
            assert f[0][1] == pytest.approx(68.0)
            assert unread == []

    def test_a_recorded_unitless_reading_stays_unreadable(self) -> None:
        h = ha.History({"sensor.a": [(NOW, 20.0)]}, {}, {"sensor.a": [None]})
        f, unread = h.since(NOW).converted("sensor.a", "°C", ha.to_f, NOW)
        assert f == [] and len(unread) == 1

    def test_since_keeps_the_value_in_force(self) -> None:
        t = [NOW + timedelta(minutes=m) for m in range(4)]
        h = ha.History(
            {"sensor.a": [(t[0], 1.0), (t[2], 2.0)]},
            {"sensor.a": [(t[0], t[1])]},
            {"sensor.a": ["°F", "°F"]},
            {"sensor.a": [(t[0], "1.0"), (t[2], "2.0")]},
        )
        got = h.since(t[1] + timedelta(seconds=30))
        assert got.readings["sensor.a"] == [(t[0], 1.0), (t[2], 2.0)]
        assert got.outages["sensor.a"] == []
        assert h.since(t[3]).readings["sensor.a"] == [(t[2], 2.0)]

    def test_a_heater_history_extended_and_trimmed(self) -> None:
        from nwp500 import sim_adapters as sa

        t = [NOW + timedelta(minutes=m) for m in range(4)]
        a = ha.HeaterHistory(
            sa.ChangeRows(upper_f=[(t[0], 140.0)], lower_f=[(t[0], 139.0)]),
            [t[0], t[1]],
        )
        b = ha.HeaterHistory(
            sa.ChangeRows(
                upper_f=[(t[1], 140.0), (t[2], 130.0)], lower_f=[(t[1], 139.0)]
            ),
            [t[1], t[2], t[3]],
            ("a note",),
        )
        got = a.extended(b)
        assert list(got.rows.upper_f) == [
            (t[0], 140.0),
            (t[1], 140.0),
            (t[2], 130.0),
        ]
        assert list(got.rows.lower_f) == [(t[0], 139.0), (t[1], 139.0)]
        assert got.observed == t
        assert got.notes == ("a note",)
        trimmed = got.since(t[2])
        assert list(trimmed.rows.upper_f) == [(t[2], 130.0)]
        assert list(trimmed.rows.lower_f) == [(t[1], 139.0)]
        assert trimmed.observed == t[2:]
