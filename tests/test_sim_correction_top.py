"""The probes' lean stops at ``TankParams.correction_top_height``: a
profile built from the probes and the replay's correction toward them
run level below the lower probe, linear from it to the lean's top, and
level above."""

import json
from dataclasses import replace

import pytest

from nwp500.sim import default_params
from nwp500.sim.params import params_from_document, params_to_document
from nwp500.sim.physics import stratified as st

P = default_params()


def _lay(top: float | None) -> st.Layout:
    return replace(st.layout(P), correction_top=top)


def test_the_default_tops_the_lean_at_three_quarters() -> None:
    assert P.tank.correction_top_height == 0.75
    assert st.layout(P).correction_top == 0.75


def test_the_estimate_is_level_above_the_top() -> None:
    lay = st.layout(P)
    layers = st.estimate(lay, 140.0, 100.0).layers_f
    above = [t for c, t in zip(lay.centers, layers, strict=True) if c >= 0.75]
    assert len(set(above)) == 1
    below = [t for c, t in zip(lay.centers, layers, strict=True) if c < 0.75]
    assert max(below) < above[0]


def test_the_probes_still_read_what_they_were_given() -> None:
    for top in (None, 0.6, 0.75):
        lay = _lay(top)
        u, lo = st.observe(lay, st.estimate(lay, 138.0, 104.0))
        assert (u, lo) == (pytest.approx(138.0), pytest.approx(104.0))


def test_none_or_above_the_upper_probe_is_the_upper_probe() -> None:
    old = st.estimate(_lay(None), 138.0, 104.0).layers_f
    assert st.estimate(_lay(0.99), 138.0, 104.0).layers_f == old
    at_probe = st.estimate(_lay(P.tank.upper_probe_height), 138.0, 104.0)
    assert at_probe.layers_f == old


def test_a_cold_lower_probe_barely_moves_the_top() -> None:
    """The replay's correction for a lower probe read 16 degF under the
    layers moves the layers at or above the top by no more than the
    upper probe's spread asks (so it still reads exactly), where the
    lean to the upper probe cooled them."""
    upper, _ = st.observe(st.layout(P), st.TankState((136.0,) * 12))

    def moved(top: float | None) -> list[float]:
        lay = _lay(top)
        state = st.TankState((136.0,) * lay.layers)
        got = st.assimilate(lay, state, upper, 120.0 + lay.lower_probe_offset_f)
        return [
            a - b
            for c, a, b in zip(
                lay.centers, got.layers_f, state.layers_f, strict=True
            )
            if c >= 0.75
        ]

    assert max(abs(d) for d in moved(0.75)) < 0.05 * 16.0
    assert min(moved(None)) < -0.15 * 16.0


def test_a_top_at_or_under_the_lower_probe_is_refused() -> None:
    with pytest.raises(ValueError, match="above the lower probe"):
        _lay(st.layout(P).lower_probe)
    with pytest.raises(ValueError, match="correction_top"):
        _lay(1.5)


def test_a_document_carries_it() -> None:
    p = replace(P, tank=replace(P.tank, correction_top_height=0.7))
    doc = json.loads(json.dumps(params_to_document(p)))
    assert params_from_document(doc).tank.correction_top_height == 0.7
