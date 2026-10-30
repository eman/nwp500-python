"""REST endpoints added from the NaviLink 2.04.00 audit.

Each test pins the HTTP method, path and request body/params the NaviLink
app sends, and parses a response shaped like the app's own parser expects.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nwp500.api_client import NavienAPIClient, get_app_version
from nwp500.auth import __version__
from nwp500.enums import DeviceType, ErrorCode
from nwp500.exceptions import APIError
from nwp500.models import (
    AppVersionInfo,
    DeviceErrorHistoryEntry,
    DisplayPreferences,
    FirmwareDetail,
    Location,
    MaintenanceHistoryEntry,
    PushSettings,
    SimpleDevice,
    UserProfile,
)

MAC = "0123456789ab"
ADD = "5322"
USER = "test@example.com"


def _make_api_client(
    user_type: str | None = "O",
) -> tuple[NavienAPIClient, AsyncMock]:
    """Create a NavienAPIClient with mocked auth and request."""
    mock_auth = MagicMock()
    mock_auth.is_authenticated = True
    mock_auth.user_email = USER
    mock_auth.session = MagicMock()
    if user_type is None:
        mock_auth.current_user = None
    else:
        mock_auth.current_user.user_type = user_type

    client = NavienAPIClient(auth_client=mock_auth)
    mock_request = AsyncMock()
    client._make_request = mock_request  # type: ignore[method-assign]
    return client, mock_request


def _ok(data: object) -> dict[str, object]:
    return {"code": 200, "msg": "SUCCESS", "data": data}


# --- Push settings -----------------------------------------------------


@pytest.mark.asyncio
async def test_get_push_settings() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(
        {"isErrorAlarm": 1, "isDescalingAlarm": 2, "isEtcAlarm": 0}
    )

    settings = await client.get_push_settings(MAC, ADD)

    mock_request.assert_awaited_once_with(
        "POST",
        "/user/get-push-settings",
        json_data={"userId": USER, "macAddress": MAC, "additionalValue": ADD},
    )
    assert isinstance(settings, PushSettings)
    # 1 is ON and 2 is OFF: the opposite of the device's on/off flags.
    assert settings.is_error_alarm is True
    assert settings.is_descaling_alarm is False
    assert settings.is_etc_alarm is None


@pytest.mark.asyncio
async def test_set_push_settings_encodes_every_given_flag() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(None)

    result = await client.set_push_settings(
        MAC, ADD, error_alarm=True, descaling_alarm=True, etc_alarm=False
    )

    assert result is True
    mock_request.assert_awaited_once_with(
        "POST",
        "/user/set-push-settings",
        json_data={
            "userId": USER,
            "macAddress": MAC,
            "additionalValue": ADD,
            "isErrorAlarm": 1,
            "isDescalingAlarm": 1,
            "isEtcAlarm": 2,
        },
    )


@pytest.mark.asyncio
async def test_set_push_settings_keeps_current_values_of_unset_flags() -> None:
    """The app always sends every flag, so an unset one is read first; one
    the cloud does not report (a member's descaling flag) stays out."""
    client, mock_request = _make_api_client()
    mock_request.side_effect = [
        _ok({"isErrorAlarm": 2, "isDescalingAlarm": 0, "isEtcAlarm": 1}),
        _ok(None),
    ]

    await client.set_push_settings(MAC, ADD, error_alarm=True)

    read, write = mock_request.await_args_list
    assert read.args == ("POST", "/user/get-push-settings")
    assert write.args == ("POST", "/user/set-push-settings")
    assert write.kwargs["json_data"] == {
        "userId": USER,
        "macAddress": MAC,
        "additionalValue": ADD,
        "isErrorAlarm": 1,
        "isEtcAlarm": 1,
    }


# --- Maintenance records ----------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("record_filter_change", "/device/filter/change-info"),
        ("record_cip_change", "/device/cip/change-info"),
    ],
)
async def test_record_maintenance_date_is_not_zero_padded(
    method: str, path: str
) -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(None)

    result = await getattr(client, method)(MAC, ADD, date(2025, 3, 7))

    assert result is True
    mock_request.assert_awaited_once_with(
        "POST",
        path,
        json_data={
            "userId": USER,
            "macAddress": MAC,
            "additionalValue": ADD,
            "deviceType": 52,
            "maintenanceDate": "2025-3-7",
        },
    )


@pytest.mark.asyncio
async def test_record_maintenance_accepts_enum_device_type() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(None)

    await client.record_cip_change(
        MAC, ADD, date(2025, 12, 25), device_type=DeviceType.HPWH
    )

    body = cast(Any, mock_request.await_args).kwargs["json_data"]
    assert body["deviceType"] == 52
    assert body["maintenanceDate"] == "2025-12-25"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get_filter_history", "/device/filter/history"),
        ("get_cip_history", "/device/cip/history"),
    ],
)
async def test_maintenance_history(method: str, path: str) -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(
        [
            {"maintenanceDate": "2025-3-7", "registerAt": 1741305600},
            {"maintenanceDate": "2024-9-1"},
        ]
    )

    entries = await getattr(client, method)(MAC, ADD, offset=0, count=10)

    mock_request.assert_awaited_once_with(
        "POST",
        path,
        json_data={
            "userId": USER,
            "offset": 0,
            "count": 10,
            "macAddress": MAC,
            "additionalValue": ADD,
        },
    )
    assert [type(e) for e in entries] == [MaintenanceHistoryEntry] * 2
    assert entries[0].maintenance_date == "2025-3-7"
    assert entries[0].register_at == 1741305600
    assert entries[1].register_at is None


@pytest.mark.asyncio
async def test_maintenance_history_null_data_is_empty() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(None)

    assert await client.get_filter_history(MAC, ADD) == []


# --- Display preferences ----------------------------------------------


@pytest.mark.asyncio
async def test_get_display_preferences_uses_query_string() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(
        [
            {
                "modelTypeCode": 1,
                "pressureDisplayFormat": "P",
                "temperatureDisplayFormat": "F",
            }
        ]
    )

    prefs = await client.get_display_preferences(MAC, ADD, model_type_code=1)

    mock_request.assert_awaited_once_with(
        "GET",
        "/device/preferences/format",
        params={"additionalValue": ADD, "macAddress": MAC, "modelTypeCode": 1},
    )
    assert len(prefs) == 1
    assert isinstance(prefs[0], DisplayPreferences)
    assert prefs[0].pressure_display_format == "P"
    assert prefs[0].temperature_display_format == "F"
    assert prefs[0].model_type_code == 1


@pytest.mark.asyncio
async def test_set_display_preferences() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(None)

    result = await client.set_display_preferences(
        MAC,
        ADD,
        pressure_display_format="M",
        temperature_display_format="C",
        model_type_code=1,
    )

    assert result is True
    mock_request.assert_awaited_once_with(
        "POST",
        "/device/preferences/format",
        json_data={
            "additionalValue": ADD,
            "macAddress": MAC,
            "modelTypeCode": 1,
            "pressureDisplayFormat": "M",
            "temperatureDisplayFormat": "C",
        },
    )


# --- Account -------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_profile() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(
        {
            "userType": "O",
            "userFirstName": "Jane",
            "userLastName": None,
            "userPhoneNumber": "5551234",
            "userSeq": 36283,
            "userEmail": USER,
        }
    )

    profile = await client.get_user_profile()

    mock_request.assert_awaited_once_with(
        "POST", "/user/info", json_data={"userId": USER}
    )
    assert isinstance(profile, UserProfile)
    assert profile.user_type == "O"
    assert profile.user_seq == 36283
    assert profile.user_email == USER
    assert profile.user_phone_number == "5551234"
    # The app turns a null last name into "".
    assert profile.full_name == "Jane"


# --- Firmware catalogue -------------------------------------------------


@pytest.mark.asyncio
async def test_get_firmware_detail() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(
        {
            "description": "Bug fixes",
            "modelNumber": 1,
            "modelType": 2,
            "productFamily": 3,
            "registerAt": 1700000000000,
            "runTime": 15,
            "swCode": 33556241,
            "swVersion": 167837696,
        }
    )

    detail = await client.get_firmware_detail(33556241, 167837696)

    mock_request.assert_awaited_once_with(
        "POST",
        "/firmware/info",
        json_data={"swCode": 33556241, "swVersion": 167837696},
    )
    assert isinstance(detail, FirmwareDetail)
    assert detail.description == "Bug fixes"
    assert detail.run_time == 15
    assert detail.register_at == 1700000000000
    assert detail.sw_code == 33556241
    assert detail.sw_version == 167837696


# --- TOU ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_tou_sends_request_as_query_string() -> None:
    client, mock_request = _make_api_client(user_type="M")
    mock_request.return_value = _ok(None)

    result = await client.delete_tou(MAC, ADD)

    assert result is True
    mock_request.assert_awaited_once_with(
        "DELETE",
        "/device/tou",
        params={
            "additionalValue": ADD,
            "controllerId": None,
            "macAddress": MAC,
            "registerPath": "wifi",
            "sourceType": "openei",
            "userId": USER,
            "userType": "M",
        },
    )


@pytest.mark.asyncio
async def test_delete_tou_explicit_user_type_and_controller() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(None)

    await client.delete_tou(
        MAC, ADD, register_path="bt", controller_id="CTRL1", user_type="O"
    )

    params = cast(Any, mock_request.await_args).kwargs["params"]
    assert params["registerPath"] == "bt"
    assert params["controllerId"] == "CTRL1"
    assert params["userType"] == "O"


@pytest.mark.asyncio
async def test_get_manufacture_id() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok({"manufactureId": "6760E2532669023"})

    manufacture_id = await client.get_manufacture_id(MAC, ADD, "CTRL1")

    mock_request.assert_awaited_once_with(
        "GET",
        "/device/tou/manufacture-id",
        params={
            "additionalValue": ADD,
            "controllerId": "CTRL1",
            "macAddress": MAC,
            "userId": USER,
        },
    )
    assert manufacture_id == "6760E2532669023"


@pytest.mark.asyncio
async def test_convert_tou_uses_signed_in_user_type() -> None:
    client, mock_request = _make_api_client(user_type="M")
    mock_request.return_value = _ok({"touInfo": []})

    await client.convert_tou([])

    assert (
        cast(Any, mock_request.await_args).kwargs["json_data"]["userType"]
        == "M"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("user_type", [None, ""])
async def test_convert_tou_defaults_to_owner(user_type: str | None) -> None:
    client, mock_request = _make_api_client(user_type=user_type)
    mock_request.return_value = _ok({"touInfo": []})

    await client.convert_tou([])

    assert (
        cast(Any, mock_request.await_args).kwargs["json_data"]["userType"]
        == "O"
    )


def test_user_type_ignores_non_string_mock_attribute() -> None:
    """A bare MagicMock auth client (as older tests build) still yields "O"."""
    mock_auth = MagicMock()
    mock_auth.is_authenticated = True
    mock_auth.session = MagicMock()

    assert NavienAPIClient(auth_client=mock_auth)._user_type() == "O"


# --- Fault history -------------------------------------------------------


@pytest.mark.asyncio
async def test_get_error_history_first_page() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(
        {
            "timeZone": "America/Los_Angeles",
            "errorInfo": [
                {
                    "channelNumber": 1,
                    "unitType": 1,
                    "errorCode": 96,
                    "subError": 0,
                    "errorOccuredTime": 1733572682000,
                },
                {"channelNumber": 1, "unitType": 1, "errorCode": 9999},
            ],
        }
    )

    entries = await client.get_error_history(MAC, ADD)

    mock_request.assert_awaited_once_with(
        "POST",
        "/device/error/list",
        json_data={
            "installerId": USER,
            "macAddress": MAC,
            "additionalValue": ADD,
            "continuousKey": None,
            "count": 20,
        },
    )
    assert all(isinstance(e, DeviceErrorHistoryEntry) for e in entries)
    first, second = entries
    assert isinstance(first.error_code, ErrorCode)
    assert first.error_code is ErrorCode(96)
    assert first.error_occurred_time == 1733572682000
    assert first.occurred_at == datetime(2024, 12, 7, 11, 58, 2, tzinfo=UTC)
    assert second.error_code == 9999
    assert not isinstance(second.error_code, ErrorCode)
    assert second.occurred_at is None
    assert first.time_zone == "America/Los_Angeles"
    assert first.occurred_at_local == first.occurred_at
    assert first.occurred_at_local is not None
    assert first.occurred_at_local.utcoffset() == -timedelta(hours=8)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1733572682000, 1733572682000),
        ("1733572682000", 1733572682000),
        ("2024-12-07T11:58:02Z", 1733572682000),
        ("2024-12-07T11:58:02", 1733572682000),
        ("2024-12-07T03:58:02-08:00", 1733572682000),
        (None, None),
        ("", None),
    ],
)
def test_error_occurred_time_accepts_epoch_ms_or_iso(
    raw: object, expected: int | None
) -> None:
    entry = DeviceErrorHistoryEntry.model_validate({"errorOccuredTime": raw})
    assert entry.error_occurred_time == expected


def test_error_entry_unknown_time_zone_reads_as_utc() -> None:
    entry = DeviceErrorHistoryEntry.model_validate(
        {"errorOccuredTime": 1733572682000, "timeZone": "Not/AZone"}
    )
    assert entry.occurred_at_local == entry.occurred_at


@pytest.mark.asyncio
async def test_get_error_history_next_page_and_installer_override() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok({"errorInfo": []})

    entries = await client.get_error_history(
        MAC,
        ADD,
        continuous_key=1733572682000,
        count=5,
        installer_id="installer@example.com",
    )

    assert entries == []
    body = cast(Any, mock_request.await_args).kwargs["json_data"]
    assert body["continuousKey"] == 1733572682000
    assert body["count"] == 5
    assert body["installerId"] == "installer@example.com"


# --- Device registration ------------------------------------------------


@pytest.mark.asyncio
async def test_update_device_info_minimal_body() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(None)

    result = await client.update_device_info(MAC, ADD, "Garage Heater")

    assert result is True
    mock_request.assert_awaited_once_with(
        "POST",
        "/device/change-info",
        json_data={
            "userId": USER,
            "deviceInfo": {
                "macAddress": MAC,
                "additionalValue": ADD,
                "deviceType": 52,
                "deviceName": "Garage Heater",
            },
        },
    )


@pytest.mark.asyncio
async def test_update_device_info_omits_empty_location_values() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(None)

    await client.update_device_info(
        MAC,
        ADD,
        "NWP500",
        install_type="R",
        location=Location(
            state="California",
            city="",
            address=None,
            latitude=38.011845,
            longitude=-122.54772,
            altitude=0.0,
        ),
    )

    body = cast(Any, mock_request.await_args).kwargs["json_data"]
    assert body["deviceInfo"]["installType"] == "R"
    assert body["location"] == {
        "state": "California",
        "latitude": 38.011845,
        "longitude": -122.54772,
    }


@pytest.mark.asyncio
async def test_update_device_info_drops_location_without_address_parts() -> (
    None
):
    """The app only sends ``location`` when state, city or address is set."""
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(None)

    await client.update_device_info(
        MAC, ADD, "NWP500", location=Location(latitude=1.0, longitude=2.0)
    )

    assert (
        "location" not in cast(Any, mock_request.await_args).kwargs["json_data"]
    )


@pytest.mark.asyncio
async def test_list_simple_devices() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok(
        [
            {
                "macAddress": MAC,
                "additionalValue": ADD,
                "deviceType": 52,
                "modelTypeCode": None,
                "deviceName": "NWP500",
            }
        ]
    )

    devices = await client.list_simple_devices()

    mock_request.assert_awaited_once_with(
        "POST",
        "/device/simple-list",
        json_data={
            "userId": USER,
            "targetUserId": USER,
            "offset": 0,
            "count": 20,
        },
    )
    assert len(devices) == 1
    assert isinstance(devices[0], SimpleDevice)
    assert devices[0].mac_address == MAC
    assert devices[0].device_type == DeviceType.HPWH
    assert devices[0].model_type_code is None
    assert devices[0].device_name == "NWP500"


@pytest.mark.asyncio
async def test_list_simple_devices_for_another_user() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok([])

    await client.list_simple_devices("owner@example.com", offset=20, count=5)

    assert cast(Any, mock_request.await_args).kwargs["json_data"] == {
        "userId": USER,
        "targetUserId": "owner@example.com",
        "offset": 20,
        "count": 5,
    }


# --- App version (unauthenticated) --------------------------------------


class _FakeResponse:
    def __init__(self, status: int, payload: dict[str, object]) -> None:
        self.status = status
        self._payload = payload

    async def json(self) -> dict[str, object]:
        return self._payload

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _client_with_session(
    status: int, payload: dict[str, object]
) -> tuple[NavienAPIClient, MagicMock]:
    session = MagicMock()
    session.post = MagicMock(return_value=_FakeResponse(status, payload))
    mock_auth = MagicMock()
    mock_auth.is_authenticated = True
    mock_auth.user_email = USER
    mock_auth.session = session
    client = NavienAPIClient(auth_client=mock_auth, base_url="https://x/api")
    return client, session


@pytest.mark.asyncio
async def test_get_app_version_is_unauthenticated_post() -> None:
    client, session = _client_with_session(
        200, _ok({"appVersion": "2.04.00", "appForceVersion": "2.00.00"})
    )

    info = await client.get_app_version()

    session.post.assert_called_once_with(
        "https://x/api/app/version",
        json={"os": "A"},
        headers={
            "User-Agent": f"nwp500-python/{__version__}",
            "Content-Type": "application/json",
        },
    )
    assert isinstance(info, AppVersionInfo)
    assert info.app_version == "2.04.00"
    assert info.app_force_version == "2.00.00"
    assert info.server_check_text is None
    assert info.is_under_maintenance is False


@pytest.mark.asyncio
async def test_get_app_version_maintenance_notice() -> None:
    client, _ = _client_with_session(
        403,
        {
            "code": 403,
            "msg": "FORBIDDEN",
            "data": {"serverCheckText": "Down until 3pm"},
        },
    )

    info = await client.get_app_version()

    assert info.server_check_text == "Down until 3pm"
    assert info.is_under_maintenance is True
    assert info.app_version is None


@pytest.mark.asyncio
async def test_get_app_version_other_error_raises() -> None:
    client, _ = _client_with_session(
        500, {"code": 500, "msg": "ERROR", "data": None}
    )

    with pytest.raises(APIError) as excinfo:
        await client.get_app_version()

    assert excinfo.value.code == 500


@pytest.mark.asyncio
async def test_module_get_app_version_needs_no_client() -> None:
    session = MagicMock()
    session.post = MagicMock(
        return_value=_FakeResponse(200, _ok({"appVersion": "2.04.00"}))
    )

    info = await get_app_version(session=session, base_url="https://x/api/")

    args, kwargs = session.post.call_args
    assert args == ("https://x/api/app/version",)
    assert "authorization" not in kwargs["headers"]
    assert info.app_version == "2.04.00"


@pytest.mark.asyncio
async def test_get_app_version_non_object_body_raises_api_error() -> None:
    client, _ = _client_with_session(200, ["not", "an", "object"])  # type: ignore[arg-type]

    with pytest.raises(APIError, match="not an object"):
        await client.get_app_version()


@pytest.mark.asyncio
async def test_get_manufacture_id_null_is_empty() -> None:
    client, mock_request = _make_api_client()
    mock_request.return_value = _ok({"manufactureId": None})

    assert await client.get_manufacture_id(MAC, ADD, "CTRL1") == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(("user_type", "sent"), [("M", "M"), (None, "O")])
async def test_tou_reads_and_writes_send_the_signed_in_user_type(
    user_type: str | None, sent: str
) -> None:
    client, mock_request = _make_api_client(user_type=user_type)
    mock_request.return_value = _ok({})

    await client.get_tou_info(MAC, ADD, "CTRL1")
    await client.update_tou(MAC, ADD, {}, {}, "94103")

    get_call, put_call = mock_request.await_args_list
    assert get_call.kwargs["params"]["userType"] == sent
    assert put_call.kwargs["json_data"]["userType"] == sent


@pytest.mark.asyncio
async def test_tou_explicit_user_type_wins() -> None:
    client, mock_request = _make_api_client(user_type="M")
    mock_request.return_value = _ok({})

    await client.get_tou_info(MAC, ADD, "CTRL1", user_type="O")

    assert (
        cast(Any, mock_request.await_args).kwargs["params"]["userType"] == "O"
    )


def test_firmware_detail_reads_null_as_zero() -> None:
    detail = FirmwareDetail.model_validate(
        {"description": None, "runTime": None, "registerAt": None, "swCode": 7}
    )
    assert detail.run_time == 0
    assert detail.register_at == 0
    assert detail.sw_code == 7


def test_user_profile_reads_null_as_empty() -> None:
    profile = UserProfile.model_validate(
        {
            "userType": None,
            "userFirstName": "Jane",
            "userLastName": None,
            "userSeq": None,
            "userEmail": None,
        }
    )
    assert profile.user_type == ""
    assert profile.user_last_name == ""
    assert profile.user_seq == 0
    assert profile.full_name == "Jane"
