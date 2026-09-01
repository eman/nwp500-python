"""Device models against the shapes the REST API actually returns.

The payloads below are trimmed from live ``/device/list`` and
``/device/info`` responses (identifiers replaced).
"""

import pytest

from nwp500.enums import ErrorCode
from nwp500.models import Device

DEVICE_LIST_ENTRY = {
    "deviceInfo": {
        "installerId": None,
        "homeSeq": 25004,
        "macAddress": "0123456789ab",
        "additionalValue": "5322",
        "deviceType": 52,
        "modelTypeCode": None,
        "deviceName": "NWP500",
        "connected": 2,
    },
    "location": {
        "state": "California",
        "city": "Anytown",
        "address": "123 Main Street",
    },
    "error": {"errorCode": 0, "errorOccuredTime": "2025-12-07T11:58:02"},
    "descaling": {"descalingStartTime": None, "descalingEndTime": None},
}

DEVICE_INFO_ENTRY = {
    "deviceInfo": {
        "homeSeq": 25004,
        "deviceName": "NWP500",
        "deviceType": 52,
        "modelTypeCode": None,
        "installType": "R",
        "connected": 2,
    },
    "location": {
        "state": "California",
        "city": "Anytown",
        "address": "123 Main Street",
        "latitude": 38.011845,
        "longitude": -122.54772,
        "altitude": None,
    },
    "installer": {"installerId": None},
    "alarmInfo": {"isEtcAlarm": 1, "isErrorAlarm": 1},
    "descaling": {"descalingStartTime": None, "descalingEndTime": None},
}


class TestDeviceListEntry:
    def test_error_summary_is_parsed(self):
        device = Device.model_validate(DEVICE_LIST_ENTRY)

        assert device.error is not None
        assert device.error.error_code == ErrorCode.NO_ERROR
        assert device.error.error_occurred_time == "2025-12-07T11:58:02"

    def test_descaling_window_is_parsed(self):
        device = Device.model_validate(DEVICE_LIST_ENTRY)

        assert device.descaling is not None
        assert device.descaling.descaling_start_time is None
        assert device.descaling.descaling_end_time is None

    def test_device_info_extras_are_parsed(self):
        info = Device.model_validate(DEVICE_LIST_ENTRY).device_info

        assert info.model_type_code is None
        assert info.installer_id is None

    @pytest.mark.parametrize("code", [0, 96, 326])
    def test_known_error_code_becomes_an_enum(self, code):
        """Not just ``== ErrorCode(code)``: an int compares equal to its
        member, so only the type tells the two union branches apart."""
        payload = DEVICE_LIST_ENTRY | {"error": {"errorCode": code}}

        error_code = Device.model_validate(payload).error.error_code

        assert isinstance(error_code, ErrorCode)
        assert error_code is ErrorCode(code)

    def test_null_error_code_does_not_break_the_response(self):
        """The cloud sends ``"errorCode": null`` on some devices, which must
        not fail the listing and so make the whole integration unusable."""
        payload = DEVICE_LIST_ENTRY | {
            "error": {"errorCode": None, "errorOccuredTime": None}
        }

        device = Device.model_validate(payload)

        assert device.error is not None
        assert device.error.error_code is None

    def test_absent_error_code_is_not_reported(self):
        """No code in the block reads the same as an explicit null: the
        cloud has told us nothing, not that the device is fault-free."""
        payload = DEVICE_LIST_ENTRY | {"error": {}}

        assert Device.model_validate(payload).error.error_code is None

    def test_unknown_error_code_does_not_break_the_response(self):
        """A code the enum doesn't know must not fail the whole listing."""
        payload = DEVICE_LIST_ENTRY | {"error": {"errorCode": 9999}}

        error_code = Device.model_validate(payload).error.error_code

        assert not isinstance(error_code, ErrorCode)
        assert error_code == 9999


class TestDeviceInfoEntry:
    def test_missing_error_block_is_none(self):
        """``/device/info`` carries no ``error`` section."""
        device = Device.model_validate(DEVICE_INFO_ENTRY)

        assert device.error is None
        assert device.descaling is not None

    def test_unmodelled_sections_are_ignored(self):
        """``installer``/``alarmInfo`` are unmodelled and must not fail."""
        device = Device.model_validate(DEVICE_INFO_ENTRY)

        assert device.device_info.install_type == "R"
