"""An enum code the library does not know keeps the message parseable."""

from enum import IntEnum
from typing import Any

import pytest
from test_device_rest_models import DEVICE_LIST_ENTRY
from test_models import TestDeviceFeatureWireAliases

from nwp500.enums import (
    ConnectionStatus,
    CurrentOperationMode,
    ErrorCode,
    HeatSource,
    VolumeCode,
)
from nwp500.models import Device, DeviceFeature, DeviceStatus

FEATURE = TestDeviceFeatureWireAliases.MINIMAL_FEATURE


@pytest.mark.parametrize(
    ("wire", "field"),
    [
        ("errorCode", "error_code"),
        ("operationMode", "operation_mode"),
        ("currentHeatUse", "current_heat_use"),
        ("dhwOperationSetting", "dhw_operation_setting"),
        ("drEventStatus", "dr_event_status"),
        ("recircOperationMode", "recirc_operation_mode"),
        ("tempFormulaType", "temp_formula_type"),
        ("temperatureType", "temperature_type"),
    ],
)
def test_status_keeps_unknown_code_as_int(
    device_status_dict: dict[str, Any], wire: str, field: str
) -> None:
    status = DeviceStatus.model_validate(device_status_dict | {wire: 777})
    value: IntEnum = getattr(status, field)
    known = DeviceStatus.model_validate(device_status_dict)
    enum_class = type(getattr(known, field))
    assert isinstance(value, enum_class)
    assert value == 777
    assert value.value == 777
    assert value.name == "UNKNOWN_777"


def test_status_known_codes_are_members(
    device_status_dict: dict[str, Any],
) -> None:
    status = DeviceStatus.model_validate(
        device_status_dict
        | {"errorCode": 0, "operationMode": 0, "currentHeatUse": 1}
    )
    assert status.error_code is ErrorCode.NO_ERROR
    assert status.operation_mode is CurrentOperationMode.STANDBY
    assert status.current_heat_use is HeatSource(1)


@pytest.mark.parametrize(
    ("wire", "field"),
    [
        ("volumeCode", "volume_code"),
        ("tempFormulaType", "temp_formula_type"),
        ("temperatureType", "temperature_type"),
        ("dhwTemperatureSettingUse", "dhw_temperature_setting_use"),
    ],
)
def test_feature_keeps_unknown_code_as_int(wire: str, field: str) -> None:
    feature = DeviceFeature.model_validate(FEATURE | {wire: 777})
    value: IntEnum = getattr(feature, field)
    assert value == 777
    assert value.name == "UNKNOWN_777"


def test_feature_known_volume_code_is_member() -> None:
    code = next(iter(VolumeCode))
    feature = DeviceFeature.model_validate(FEATURE | {"volumeCode": code.value})
    assert feature.volume_code is code


def test_device_list_keeps_unknown_connection_status() -> None:
    info = DEVICE_LIST_ENTRY["deviceInfo"]
    assert isinstance(info, dict)
    device = Device.model_validate(
        DEVICE_LIST_ENTRY | {"deviceInfo": info | {"connected": 9}}
    )
    connected: IntEnum = device.device_info.connected
    assert connected == 9
    assert connected.name == "UNKNOWN_9"
    known = Device.model_validate(DEVICE_LIST_ENTRY)
    assert known.device_info.connected is ConnectionStatus(2)


def test_unknown_dhw_control_code_does_not_permit_writes() -> None:
    from nwp500.device_capabilities import MqttDeviceCapabilityChecker

    for code, supported in [(777, False), (0, False), (1, False), (2, True)]:
        feature = DeviceFeature.model_validate(
            FEATURE | {"dhwTemperatureSettingUse": code}
        )
        assert (
            MqttDeviceCapabilityChecker.supports(
                "dhw_temperature_setting_use", feature
            )
            is supported
        ), code


def test_status_with_unknown_code_dumps_and_compares(
    device_status_dict: dict[str, Any],
) -> None:
    status = DeviceStatus.model_validate(
        device_status_dict | {"errorCode": 777}
    )
    assert status.model_dump()["error_code"] == "UNKNOWN_777"
    assert '"errorCode":777' in status.model_dump_json(by_alias=True)
    assert status.error_code != ErrorCode.NO_ERROR


def test_fractional_dhw_control_code_is_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DeviceFeature.model_validate(
            FEATURE | {"dhwTemperatureSettingUse": 2.9}
        )
