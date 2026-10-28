"""Time to ready: the bath and shower answers and the time to
bath-ready by mode (``nwp500.sim.ready``)."""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nwp500.sim.delivery import Deliverable
from nwp500.sim.ready import (
    ALWAYS,
    MODES,
    ModeRun,
    Recovery,
    TankNow,
    assess,
    typed,
    whole_showers,
)

NOW = datetime(2026, 9, 21, 20, 0, tzinfo=UTC)
FULL = Deliverable(50.0, "layers")


def _tank(upper: float = 141.0, lower: float = 140.0, **kw: Any) -> TankNow:
    base = {"drawing": False, "element_on": False, "tou_window": False}
    return TankNow(upper_f=upper, lower_f=lower, **{**base, **kw})


def _runs(minutes: float = 40.0) -> list[ModeRun]:
    """Each mode's walk: the heat pump at ``minutes``, the element modes
    faster, Electric fastest, each at its own cost."""
    return [
        ModeRun("heat_pump", minutes, 0.5),
        ModeRun("energy_saver", minutes * 0.6, 1.2),
        ModeRun("high_demand", minutes * 0.5, 1.6),
        ModeRun("electric", minutes * 0.4, 2.0, ("element_model_small_n",)),
    ]


def _assess(
    tank: TankNow | None = None,
    recovery: Recovery = Recovery("ok"),
    now_gal: Deliverable = FULL,
    runs: list[ModeRun] | None = None,
    **kw: Any,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "bath_gal": 30.5,
        "bath_source": "configured",
        "shower_gal": 12.0,
        "shower_source": "weekly_forecast",
        "valid_s": 900.0,
    }
    return assess(
        NOW,
        tank or _tank(),
        recovery,
        now_gal,
        _runs() if runs is None else runs,
        **{**args, **kw},
    )


def _modes(a: dict[str, Any]) -> dict[str, Any]:
    return {r["mode"]: r for r in a["bath"]["by_mode"]}


class TestWholeShowers:
    def test_it_floors(self) -> None:
        assert whole_showers(2.99) == 2

    def test_a_float_just_under_a_whole_number_is_that_number(self) -> None:
        assert whole_showers(1.9999999999) == 2

    def test_never_negative(self) -> None:
        assert whole_showers(0.0) == 0

    def test_a_tap_that_never_runs_cold_is_counted(self) -> None:
        assert whole_showers(math.inf) == 10**9


class TestAssess:
    def test_every_answer_is_low_confidence_and_says_why(self) -> None:
        a = _assess()
        assert a["status"] == "low_confidence"
        assert a["reasons"][: len(ALWAYS)] == list(ALWAYS)

    def test_the_probes_alone_say_so(self) -> None:
        assert "tank_profile_estimated" not in _assess()["reasons"]
        a = _assess(now_gal=Deliverable(50.0, "probes"))
        assert "tank_profile_estimated" in a["reasons"]

    def test_a_full_tank_runs_a_bath_now_in_every_mode(self) -> None:
        a = _assess()
        assert a["deliverable_gal"] == 50.0
        assert a["bath"]["ready"] is True
        assert a["bath"]["ready_in_minutes"] == 0.0
        assert a["bath"]["ready_at"] == NOW
        assert a["bath"]["margin_gal"] == pytest.approx(19.5)
        assert all(
            r["ready_in_minutes"] == 0.0 and r["energy_kwh"] == 0.0
            for r in a["bath"]["by_mode"]
        )

    def test_ready_is_decided_on_the_numbers_it_reports(self) -> None:
        """A bath 0.04 gal over the deliverable volume is reported at the
        same one-decimal value; it must read ready with a zero margin,
        not show two equal numbers and say not ready."""
        a = _assess(bath_gal=50.04, bath_source="request")
        assert a["bath"]["volume_gal"] == 50.0
        assert a["bath"]["ready"] is True
        assert a["bath"]["margin_gal"] == 0.0

    def test_within_the_probes_resolution_it_says_so(self) -> None:
        a = _assess(within_resolution=True)
        assert "bath_ready_within_probe_resolution" in a["reasons"]
        assert "bath_ready_within_probe_resolution" not in _assess()["reasons"]

    def test_the_modes_walks_are_the_times(self) -> None:
        a = _assess(now_gal=Deliverable(10.0, "layers"))
        m = _modes(a)
        assert [r["mode"] for r in a["bath"]["by_mode"]] == list(MODES)
        assert a["bath"]["ready"] is False
        assert a["bath"]["ready_in_minutes"] == 40.0
        assert a["bath"]["ready_at"] == NOW + timedelta(minutes=40)
        assert m["electric"]["ready_in_minutes"] == 16.0
        assert m["electric"]["energy_kwh"] == 2.0
        assert m["electric"]["reasons"] == ["element_model_small_n"]
        assert m["heat_pump"]["reasons"] == []

    def test_a_walk_that_never_gets_there_says_so(self) -> None:
        runs = [ModeRun(mode, None, None) for mode in MODES]
        a = _assess(now_gal=Deliverable(10.0, "layers"), runs=runs)
        assert a["bath"]["ready_in_minutes"] is None
        assert "bath_not_reached_by_full_recovery" in a["reasons"]

    def test_inside_a_tou_window_the_bath_waits_for_its_end(self) -> None:
        runs = [ModeRun(mode, None, None) for mode in MODES]
        a = _assess(
            _tank(tou_window=True),
            Recovery("ok", tou_capped=True),
            Deliverable(10.0, "layers"),
            runs,
        )
        assert "bath_waits_for_tou_window_end" in a["reasons"]
        assert "bath_not_reached_by_full_recovery" not in a["reasons"]
        m = _modes(a)
        assert m["heat_pump"]["reachable_now"]
        assert not any(
            m[x]["reachable_now"]
            for x in ("energy_saver", "high_demand", "electric")
        )

    def test_an_idle_heater_with_no_time_says_why(self) -> None:
        runs = [ModeRun(mode, None, None) for mode in MODES]
        a = _assess(
            recovery=Recovery("idle"),
            now_gal=Deliverable(10.0, "layers"),
            runs=runs,
        )
        assert a["bath"]["ready_in_minutes"] is None
        assert "heating_not_triggered" in a["reasons"]

    def test_vacation_reaches_nothing(self) -> None:
        a = _assess(
            recovery=Recovery("not_scheduled"),
            now_gal=Deliverable(10.0, "layers"),
            runs=[],
        )
        m = _modes(a)
        assert "heating_not_scheduled" in a["reasons"]
        assert not any(r["reachable_now"] for r in m.values())
        assert all(r["ready_in_minutes"] is None for r in m.values())

    def test_no_recovery_is_no_time(self) -> None:
        a = _assess(
            recovery=Recovery("unavailable"),
            now_gal=Deliverable(10.0, "layers"),
            runs=[],
        )
        assert "time_to_ready_unavailable" in a["reasons"]

    def test_a_request_volume_is_labelled_as_one(self) -> None:
        a = _assess(bath_source="request", bath_gal=20.0)
        assert a["bath"]["volume_source"] == "request"
        assert "bath_volume_inferred" not in a["reasons"]

    def test_the_showers_are_the_gallons_over_a_shower(self) -> None:
        a = _assess(shower_gal=12.0)
        assert a["showers"]["ready_for"] == pytest.approx(50.0 / 12.0, abs=0.01)
        assert a["showers"]["ready_for_whole"] == 4

    def test_live_conditions_become_reasons(self) -> None:
        a = _assess(
            _tank(drawing=True, element_on=True, tou_window=True),
            shower_source="default",
        )
        for reason in (
            "draw_in_progress",
            "element_running",
            "tou_window_in_force",
            "shower_volume_default",
        ):
            assert reason in a["reasons"]

    def test_it_types(self) -> None:
        r = typed(_assess(), NOW, Recovery("ok"), ["bath_gal=30.5"])
        assert r.deliverable_gal == 50.0
        assert r.bath.ready
        assert r.defaults_used == ("bath_gal=30.5",)
