"""The default parameters by tank size (``nwp500.sim.default_params``)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from nwp500.sim.defaults import (
    NO_VALVE,
    SITE_CIRCULATION,
    SITE_VALVE,
    default_params,
    site_example_params,
    with_valve,
)
from nwp500.sim.params import (
    DEFAULT,
    FITTED,
    HEATER,
    INSTALLATION,
    INSTALLATION_TERMS,
    MEASURED,
    Scope,
    note_of,
    params_from_document,
    params_to_document,
    provenance_of,
    scope_of,
    unknown_fields,
)


def test_the_65_round_trips_as_a_document() -> None:
    p = default_params()
    assert params_from_document(params_to_document(p)) == p


@pytest.mark.parametrize(("code", "gal"), [(1, 50.0), (3, 80.0)])
def test_other_sizes_scale_the_tank_volume_only(code: int, gal: float) -> None:
    base, other = default_params(2), default_params(code)
    assert other.tank.volume_gal == pytest.approx(63.2 * gal / 65.0)
    assert other.book.tank_gal == pytest.approx(63.2 * gal / 65.0)
    assert replace(other, tank=base.tank, book=base.book) == base


def test_an_unknown_size_is_refused() -> None:
    with pytest.raises(ValueError, match="volume_code"):
        default_params(4)


def test_the_constants_say_where_they_came_from() -> None:
    p = default_params()
    assert provenance_of(p.compressor, "compressor_constant") == FITTED
    assert provenance_of(p.controller, "restart_lockout_s") == MEASURED
    assert provenance_of(p.compressor, "polytropic_exp") == DEFAULT
    assert p.controller.restart_lockout_s == 330.0
    assert p.controller.tou_cap_f == 3.6


def test_the_65_is_ready_to_simulate() -> None:
    p = default_params()
    assert p.tank.stratification_gap_tau_h is not None
    assert p.compressor.compressor_constant > 0.0
    assert p.loss.ua_btu_hr_f is not None


#: A document a retrain wrote from a fitted model (heater-params/1),
#: byte for byte as it was written.
FITTED_DOC = (
    Path(__file__).with_name("fixtures") / "sim" / "heater_params_fitted.json"
)


def test_a_fitted_document_reads_to_its_values_bit_for_bit() -> None:
    doc = json.loads(FITTED_DOC.read_text())
    p = params_from_document(doc)
    for part, values in doc.items():
        if part == "schema":
            continue
        for name, value in values.items():
            got = getattr(getattr(p, part), name)
            assert got == value and repr(got) == repr(value), (part, name)
    assert unknown_fields(doc) == []


def test_a_fitted_document_writes_back_as_it_was() -> None:
    """What it carries is written back unchanged; the parts and fields
    added since it was written are their defaults."""
    doc = json.loads(FITTED_DOC.read_text())
    written = json.loads(
        json.dumps(params_to_document(params_from_document(doc)))
    )
    assert {
        part: (
            {k: written[part][k] for k in values}
            if isinstance(values, dict)
            else written[part]
        )
        for part, values in doc.items()
    } == doc
    assert params_from_document(written) == params_from_document(doc)


def test_the_site_example_is_that_fitted_model() -> None:
    """The document carries no circulation (its bundle keeps that
    apart); the site example adds the installation's."""
    # Nor its readiness evidence, which the model kept in its code.
    site = site_example_params()
    assert params_from_document(json.loads(FITTED_DOC.read_text())) == (
        replace(
            site,
            circulation=None,
            readiness=replace(site.readiness, evidence=()),
        )
    )
    assert len(site.readiness.evidence) == 19
    assert site_example_params().circulation == SITE_CIRCULATION


def test_the_default_is_the_site_without_its_mixing_valve() -> None:
    d, site = default_params(), site_example_params()
    assert (d.draw.delivery_intercept_f, d.draw.delivery_slope) == NO_VALVE
    book = d.book_terms()
    assert (book.delivery_intercept_f, book.delivery_slope) == NO_VALVE
    site_book = site.book_terms()
    assert (site_book.delivery_intercept_f, site_book.delivery_slope) == (
        SITE_VALVE
    )
    assert d.circulation is None and d.readiness.evidence == ()
    assert with_valve(d, SITE_VALVE) == replace(
        site,
        circulation=None,
        readiness=d.readiness,
        unfitted=INSTALLATION_TERMS,
    )


def test_the_defaults_installation_terms_are_named_unfitted() -> None:
    """The replacement review of #162: one installation's book,
    readiness and draw terms stand in for another's, and every answer
    they reach says so; the site's own example is its fit."""
    assert default_params().unfitted == INSTALLATION_TERMS
    assert site_example_params().unfitted == ()


def test_one_valve_drives_the_draw_and_the_book() -> None:
    p = replace(
        default_params(),
        draw=replace(default_params().draw, delivery_intercept_f=50.0),
    )
    assert p.book_terms().delivery_intercept_f == 50.0
    assert p.book_terms().delivery_slope == 1.0


def test_without_a_valve_every_gallon_is_tank_water() -> None:
    """The same tank delivers fewer gallons through no valve: each one is
    all tank water."""
    from nwp500.sim import HeaterState, Settings, full_tank_book, readiness

    state, settings = (
        HeaterState(upper_f=140.5, lower_f=139.6),
        Settings(setpoint_f=140.9),
    )
    gal = {}
    for name, p in (
        ("none", default_params()),
        ("site", site_example_params()),
    ):
        book = full_tank_book(140.5, 139.6, p.book_terms())
        gal[name] = readiness(state, settings, p, book=book).gal
    assert 0.0 < gal["none"] < gal["site"] / 1.2


@pytest.mark.parametrize(
    ("part", "name", "scope"),
    [
        ("tank", "volume_gal", HEATER),
        ("controller", "restart_lockout_s", HEATER),
        ("element", "upper_f_per_min", HEATER),
        ("draw", "observability", INSTALLATION),
        ("draw", "inlet_temp_f", INSTALLATION),
        ("draw", "delivery_slope", INSTALLATION),
        ("book", "empty_btu", INSTALLATION),
        ("readiness", "delivered_lag_gal", INSTALLATION),
        ("readiness", "dip_f", HEATER),
    ],
)
def test_each_parameter_says_what_it_describes(
    part: str, name: str, scope: Scope
) -> None:
    p = default_params()
    assert scope_of(getattr(p, part), name) == scope


def test_the_fitted_frames_are_noted() -> None:
    p = default_params()
    assert "where the heater stands" in (note_of(p.loss, "ua_btu_hr_f") or "")
    assert "recoveries" in (note_of(p.compressor, "compressor_constant") or "")
    assert "mixing valve" in (note_of(p.draw, "observability") or "")
    assert note_of(p.tank, "volume_gal") is None
