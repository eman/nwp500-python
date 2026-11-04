"""The house meter's reading of a delivered gallon
(``DrawParams.meter_reads``): each metered gallon is ``1 / meter_reads``
delivered, wherever the tank takes a metered volume."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_sim_api import _scenario, at

from nwp500 import sim_score as ss
from nwp500.sim import (
    Draw,
    DrawWindow,
    HeaterState,
    Loads,
    default_params,
    next_recovery,
    simulate,
    time_to_ready,
)
from nwp500.sim import history as hist
from nwp500.sim import tank_fit as tf
from nwp500.sim.params import (
    DrawParams,
    HeaterParams,
    params_from_document,
    params_to_document,
)
from nwp500.sim.physics import stratified as S

T0 = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)


def _reads(share: float, params: HeaterParams | None = None) -> HeaterParams:
    p = params or default_params()
    return replace(p, draw=replace(p.draw, meter_reads=share))


@pytest.mark.parametrize("share", [0.0, -0.5, 2.5, float("nan")])
def test_a_share_of_a_gallon_or_refused(share: float) -> None:
    with pytest.raises(ValueError, match="meter_reads"):
        replace(default_params().draw, meter_reads=share)


def test_it_is_off_by_default() -> None:
    d = default_params().draw
    assert d.meter_reads == 1.0
    assert d.delivered_gal(7.5) == 7.5
    assert DrawParams.__dataclass_fields__["meter_reads"].default == 1.0


def test_the_walk_takes_a_metered_draw_as_its_delivered_gallons() -> None:
    def walk(
        gallons: float, params: HeaterParams
    ) -> list[tuple[datetime, float, float]]:
        s = _scenario(loads=Loads(draws=(Draw(at=at(1), gallons=gallons),)))
        r = simulate(s, params)
        return [(p.at, p.upper_f, p.lower_f) for p in r.points]

    assert walk(6.0, _reads(0.5)) == walk(12.0, default_params())
    assert walk(6.0, _reads(0.5)) != walk(6.0, default_params())


def test_the_record_replay_takes_them_too() -> None:
    def coast(gal: float) -> tf.Coast:
        return tf.Coast(
            start=T0,
            end=T0 + timedelta(hours=1),
            upper_f=130.0,
            lower_f=128.0,
            air=((T0, 66.0),),
            observed=tuple(
                (T0 + timedelta(minutes=m), 130.0, 128.0)
                for m in range(0, 61, 10)
            ),
            draws=((T0 + timedelta(minutes=5), gal),),
        )

    half = tf.errors(_reads(0.5), None, coast(6.0))
    whole = tf.errors(default_params(), None, coast(12.0))
    assert half is not None and whole is not None
    for a, b in zip(half, whole, strict=True):
        assert a == pytest.approx(b, abs=1e-9)


def test_a_record_holds_the_meter_s_gallons() -> None:
    # Taken as delivered where the tank takes them (the replay), not
    # where they are read: scaling both would take a gallon twice.
    step = hist.Step(
        seconds=60.0,
        upper_f=128.0,
        lower_f=126.0,
        flow_gpm=2.0,
        compressor_on=False,
        element_on=False,
        ambient_f=62.0,
        inlet_f=60.0,
        flow_volume="delivered",
        at=T0,
    )
    assert hist.drawn_gal(step, _reads(0.8)) == pytest.approx(2.0)
    read = hist.record([step], _reads(0.8)).draws
    assert read == hist.record([step], default_params()).draws


def test_it_round_trips_and_an_older_document_reads_it_off() -> None:
    p = _reads(0.85)
    assert params_from_document(params_to_document(p)) == p
    doc = params_to_document(default_params())
    assert "meter_reads" in doc["draw"]
    del doc["draw"]["meter_reads"]
    assert params_from_document(doc).draw.meter_reads == 1.0


def test_a_window_s_expected_gallons_are_the_meter_s() -> None:
    window = DrawWindow(start=at(1), end=at(2), expected_gal=6.0)
    s = _scenario(loads=Loads(windows=(window,)))
    (half,) = simulate(s, _reads(0.5)).windows
    (whole,) = simulate(s, default_params()).windows
    assert half.expected_gal == pytest.approx(12.0)
    assert whole.expected_gal == pytest.approx(6.0)
    assert half.margin_gal == pytest.approx(half.deliverable_gal - 12.0)
    assert half.deliverable_gal == pytest.approx(whole.deliverable_gal)


def _quiet_record(gal: float) -> tf.TankRecord:
    steps = [
        hist.Step(
            seconds=60.0,
            upper_f=128.0,
            lower_f=126.0,
            flow_gpm=0.0,
            compressor_on=False,
            element_on=False,
            ambient_f=62.0,
            inlet_f=60.0,
            flow_volume="delivered",
            at=T0 + timedelta(minutes=k),
        )
        for k in range(180)
    ]
    rec = hist.record(steps, default_params())
    return replace(rec, draws=((T0 + timedelta(minutes=100), gal),))


def test_the_replay_takes_a_record_s_draws_delivered() -> None:
    lay = S.layout(default_params())
    until = T0 + timedelta(minutes=170)
    half = tf.replay(lay, _reads(0.5), _quiet_record(6.0), until)
    whole = tf.replay(lay, default_params(), _quiet_record(12.0), until)
    as_read = tf.replay(lay, default_params(), _quiet_record(6.0), until)
    assert half is not None and whole is not None and as_read is not None
    assert S.observe(lay, half) == pytest.approx(S.observe(lay, whole))
    assert S.observe(lay, half) != pytest.approx(S.observe(lay, as_read))


def test_a_recovery_takes_the_rest_of_a_draw_under_way_delivered() -> None:
    def recovery(
        gallons: float, params: HeaterParams
    ) -> list[tuple[datetime, float, float]]:
        draw = Draw(at=at(1), gallons=gallons, duration_s=1800.0)
        s = _scenario(
            state=HeaterState(
                upper_f=125.0, lower_f=100.0, compressor_running=True
            ),
            loads=Loads(draws=(draw,)),
        )
        s = s.model_copy(update={"start": at(1) + timedelta(minutes=10)})
        return list(next_recovery(s, params).points)

    # Both under the undiluted flow (``undiluted_gpm``, the meter's).
    assert recovery(20.0, _reads(0.5)) == recovery(40.0, default_params())
    assert recovery(20.0, _reads(0.5)) != recovery(20.0, default_params())


def test_the_score_takes_a_delivery_s_gallons_delivered() -> None:
    def scored(gal: float, params: HeaterParams) -> float:
        e = ss.Delivery(T0, 140.0, 138.0, 140.0, True, gal)
        got = ss.score(ss.Events(deliveries=(e,)), params)
        return got.metrics["deliverable_bias_gal"].value

    assert scored(5.0, _reads(0.5)) == pytest.approx(
        scored(10.0, default_params())
    )


def test_readiness_takes_a_bath_and_a_shower_delivered() -> None:
    s = _scenario(state=HeaterState(upper_f=140.0, lower_f=135.0))
    half = time_to_ready(s, _reads(0.5), bath_gal=10.0, shower_gal=5.0)
    whole = time_to_ready(s, default_params(), bath_gal=20.0, shower_gal=10.0)
    assert half.bath.volume_gal == whole.bath.volume_gal == 20.0
    assert half.bath.margin_gal == whole.bath.margin_gal
    assert half.showers.ready_for == whole.showers.ready_for
