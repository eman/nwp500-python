"""An enum code the library does not know keeps the message parseable."""

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
    value = getattr(status, field)
    assert value == 777
    assert type(value) is int


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
    value = getattr(feature, field)
    assert value == 777
    assert type(value) is int


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
    assert device.device_info.connected == 9
    known = Device.model_validate(DEVICE_LIST_ENTRY)
    assert known.device_info.connected is ConnectionStatus(2)
