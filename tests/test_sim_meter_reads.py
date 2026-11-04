"""The house meter's reading of a delivered gallon
(``DrawParams.meter_reads``): each metered gallon is ``1 / meter_reads``
delivered, wherever the tank takes a metered volume."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_sim_api import _scenario, at

from nwp500.sim import Draw, Loads, default_params, simulate
from nwp500.sim import history as hist
from nwp500.sim import tank_fit as tf
from nwp500.sim.params import (
    DrawParams,
    HeaterParams,
    params_from_document,
    params_to_document,
)

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
