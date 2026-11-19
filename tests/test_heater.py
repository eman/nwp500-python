"""The heater's description (``nwp500.heater``): its modes, setpoint
range and commands, usable without the simulator."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace

import pytest

from nwp500 import heater as H
from nwp500.enums import DhwOperationSetting
from nwp500.models import DeviceFeature
from nwp500.unit_system import set_unit_system


@dataclass(frozen=True)
class _Limits:
    """A setpoint range in half degrees Celsius, as a device's features
    hold it."""

    dhw_temperature_min_raw: int
    dhw_temperature_max_raw: int


def _feature(min_raw: int, max_raw: int) -> DeviceFeature:
    return DeviceFeature.model_validate(
        {
            "temperatureType": 1,
            "countryCode": 3,
            "modelTypeCode": 513,
            "controlTypeCode": 100,
            "volumeCode": 1,
            "controllerSwVersion": 1,
            "panelSwVersion": 1,
            "wifiSwVersion": 1,
            "controllerSwCode": 1,
            "panelSwCode": 1,
            "wifiSwCode": 1,
            "recircSwVersion": 1,
            "recircModelTypeCode": 0,
            "controllerSerialNumber": "ABC123",
            "dhwTemperatureSettingUse": 2,
            "tempFormulaType": 1,
            "dhwTemperatureMin": min_raw,
            "dhwTemperatureMax": max_raw,
            "freezeProtectionTempMin": 12,
            "freezeProtectionTempMax": 20,
            "recircTemperatureMin": 81,
            "recircTemperatureMax": 120,
        }
    )


def test_it_loads_without_the_simulator() -> None:
    """A client without the ``sim`` extra imports it."""
    script = (
        "import json, sys\n"
        "import nwp500.heater\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    loaded = json.loads(out.stdout)
    heavy = {"numpy", "pandas", "scipy", "pydantic"}
    assert not [m for m in loaded if m.split(".")[0] in heavy]
    assert not [m for m in loaded if m.split(".")[:2] == ["nwp500", "sim"]]


class TestTheModes:
    def test_every_mode_a_plan_may_carry(self) -> None:
        """Every ``DhwOperationSetting`` but the status-only
        ``STANDBY``, by its name in lower case."""
        assert {m.code for m in H.MODES} == {
            int(s) for s in DhwOperationSetting if s.name != "STANDBY"
        }
        for m in H.MODES:
            assert m.name == DhwOperationSetting(m.code).name.lower()
            assert H.DEVICE_MODE_CODES[m.code] == m.name.upper()

    def test_vacation_and_power_off_are_not_modelled(self) -> None:
        unmodelled = {m.name: m.sources for m in H.MODES if not m.modelled}
        assert unmodelled == {"vacation": (), "power_off": ()}

    def test_the_profile_lists_them_all(self) -> None:
        p = H.device_profile()
        assert p.modes == H.MODES
        assert p.mode("power_off") == H.MODES[-1]
        assert p.mode("standby") is None
        assert p.name_of(6) == "power_off"
        assert p.sources("power_off") == frozenset()
        assert p.effective("power_off", frozenset({"element"})) is None


class TestTheSetpointRange:
    def test_the_nwp500s_without_a_device(self) -> None:
        p = H.device_profile()
        assert (p.setpoint_min_f, p.setpoint_max_f) == (104.9, 149.9)
        assert (p.setpoint_step_unit, p.setpoint_step) == ("C", 0.5)

    def test_the_devices_own_from_its_features(self) -> None:
        p = H.device_profile(_feature(81, 131))
        assert (p.setpoint_min_f, p.setpoint_max_f) == (104.9, 149.9)
        narrow = H.device_profile(_feature(90, 121))
        assert (narrow.setpoint_min_f, narrow.setpoint_max_f) == (113.0, 140.9)
        assert narrow.revision != p.revision

    def test_in_fahrenheit_whatever_the_unit_preference(self) -> None:
        set_unit_system("metric")
        try:
            p = H.device_profile(_feature(81, 131))
        finally:
            set_unit_system(None)
        assert (p.setpoint_min_f, p.setpoint_max_f) == (104.9, 149.9)

    def test_any_object_with_the_raw_limits(self) -> None:
        limits = _Limits(81, 131)
        assert H.setpoint_range_f(limits) == (104.9, 149.9)


class TestTheCommands:
    def test_each_whole_number_key_has_its_range(self) -> None:
        whole = {
            (c, k)
            for c, keys in H.COMMAND_KEYS.items()
            for k, t in keys.items()
            if t is int
        }
        ranged = {(c, k) for c, keys in H.COMMAND_RANGES.items() for k in keys}
        assert whole == ranged
        assert H.COMMAND_RANGES["vacation"]["days"] == (1, 99)
        assert H.COMMAND_RANGES["anti_legionella"]["period_days"] == (1, 30)

    def test_a_commands_keys_as_a_document_states_them(self) -> None:
        assert H.command_key_facts("anti_legionella") == {
            "enabled": {"type": "boolean"},
            "period_days": {
                "type": "integer",
                "min": 1,
                "max": 30,
                "only_with": {"enabled": True},
            },
        }
        assert H.command_key_facts("vacation") == {
            "days": {"type": "integer", "min": 1, "max": 99}
        }
        assert H.command_key_facts("unknown") == {}


class TestTheDocument:
    def test_facts_and_revision(self) -> None:
        p = H.device_profile()
        doc = p.document()
        assert doc == {**p.facts(), "revision": p.revision}
        assert json.loads(json.dumps(doc, allow_nan=False)) == doc
        assert doc["modes"][-1] == {
            "name": "power_off",
            "code": 6,
            "sources": [],
            "modelled": False,
        }
        assert doc["command_keys"]["vacation"]["days"]["max"] == 99
        assert doc["setpoint_f"] == {"min": 104.9, "max": 149.9}
        assert doc["tank_gal"] is None

    def test_the_revision_moves_with_a_fact_only(self) -> None:
        p = H.device_profile()
        assert p.revision == H.device_profile().revision
        assert replace(p, setpoint_max_f=140.0).revision != p.revision


class TestCheck:
    def test_the_devices_profile_passes(self) -> None:
        H.check(H.device_profile())

    def test_an_unmodelled_mode_may_have_no_sources(self) -> None:
        H.check(replace(H.device_profile(), modes=H.MODES))

    @pytest.mark.parametrize(
        ("change", "match"),
        [
            (
                {"modes": (H.ProfileMode("heat_pump", 1, (), True),)},
                "sources",
            ),
            ({"modes": H.MODES + H.MODES[:1]}, "distinct"),
            ({"default_mode": "vacation"}, "default_mode"),
            ({"assisted_mode": "power_off"}, "assisted_mode"),
            ({"commands": ("vacation", "reboot")}, "commands"),
            ({"setpoint_min_f": 150.0}, "setpoint range"),
        ],
    )
    def test_a_broken_profile_is_refused(
        self, change: dict[str, object], match: str
    ) -> None:
        with pytest.raises(ValueError, match=match):
            H.check(replace(H.device_profile(), **change))  # type: ignore[arg-type]
