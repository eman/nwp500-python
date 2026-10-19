from datetime import UTC, datetime
from typing import Annotated, Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BeforeValidator, Field

from .._base import NavienBaseModel
from ..converters import enum_validator
from ..enums import ConnectionStatus, DeviceType, ErrorCode

ConnectionStatusField = Annotated[
    ConnectionStatus, BeforeValidator(enum_validator(ConnectionStatus))
]


def push_flag_to_python(value: Any) -> bool | None:
    """Convert a push-notification flag to a tri-state Python bool.

    The ``/user/get-push-settings`` and ``/device/info`` ``alarmInfo`` flags
    use the **opposite** encoding to the device's on/off flags: the NaviLink
    app sends ``isChecked() ? 1 : 2``, so 1 is *on* and 2 is *off*. 0 is
    "not reported" (the app omits a 0 from the request body) and maps to
    ``None`` rather than a fabricated off, following
    :func:`nwp500.converters.device_tristate_to_python`.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        number = int(value)
    except TypeError, ValueError:
        return None
    if number == 1:
        return True
    if number == 2:
        return False
    return None


def python_to_push_flag(value: bool | None) -> int | None:
    """Inverse of :func:`push_flag_to_python`: True→1, False→2, None→None."""
    if value is None:
        return None
    return 1 if value else 2


#: A push-notification flag: 1=on, 2=off, 0/absent=unknown (``None``).
PushFlag = Annotated[bool | None, BeforeValidator(push_flag_to_python)]


def _null_to_zero(value: Any) -> Any:
    """``null`` reads as 0, as the NaviLink app's JSON parser reads it."""
    return 0 if value is None else value


#: An integer field the cloud may send as ``null``.
NullableInt = Annotated[int, BeforeValidator(_null_to_zero)]


def epoch_ms_to_python(value: Any) -> Any:
    """Read a timestamp as epoch milliseconds.

    The NaviLink app reads ``errorOccuredTime`` as a number. The same key
    on ``/device/list`` is an ISO 8601 string, so a string is accepted
    too: a numeric one as is, an ISO 8601 one converted (UTC when it
    carries no offset).
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        return int(text)
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


class DeviceInfo(NavienBaseModel):
    """Device information from API."""

    home_seq: int = 0
    mac_address: str = ""
    additional_value: str = ""
    device_type: DeviceType | int = DeviceType.NPF700_WIFI
    device_name: str = "Unknown"
    connected: ConnectionStatusField = ConnectionStatus.DISCONNECTED
    install_type: str | None = None
    model_type_code: int | None = None
    installer_id: str | None = None


class Location(NavienBaseModel):
    """Location information for a device."""

    state: str | None = None
    city: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None


class DeviceErrorSummary(NavienBaseModel):
    """Last device fault as reported by the REST API.

    The cloud keeps this independently of the live MQTT status, so it is
    readable without an MQTT connection - including while the device is
    offline, where it reports the fault as of the last time the device
    was heard from.
    """

    #: ``NO_ERROR`` when the device has no recorded fault, and ``None`` when
    #: the cloud reports no code at all - it sends ``"errorCode": null`` on
    #: some devices, which is not the same claim as "no error". Typed to
    #: accept a bare int as well, following ``device_type``, so neither a
    #: null nor a code the enum does not know can make a whole
    #: ``/device/list`` response unparseable.
    #:
    #: ``union_mode`` matters here: pydantic's default smart union matches an
    #: incoming int against the ``int`` branch exactly and never reaches the
    #: enum, so every code - known or not - would stay a plain int. Trying the
    #: branches left to right instead means a known code becomes an
    #: ``ErrorCode`` member and only an unknown one falls through to ``int``.
    error_code: ErrorCode | int | None = Field(
        default=None, union_mode="left_to_right"
    )
    #: Spelled "Occured" by the API; the Python name is spelled correctly.
    error_occurred_time: str | None = Field(
        default=None, alias="errorOccuredTime"
    )


class DescalingInfo(NavienBaseModel):
    """Descaling window reported by the REST API.

    Both timestamps are ``None`` on a device with no descaling scheduled
    or recorded.
    """

    descaling_start_time: str | None = None
    descaling_end_time: str | None = None


class DeviceInstaller(NavienBaseModel):
    """Installer linked to a device, from ``/device/info``.

    Every field is ``None`` on a device registered without an installer.
    """

    installer_id: str | None = None
    installer_first_name: str | None = None
    installer_last_name: str | None = None
    installer_phone_number: str | None = None


class PushSettings(NavienBaseModel):
    """Push-notification preferences for one device.

    Returned by ``/user/get-push-settings`` and embedded in ``/device/info``
    as ``alarmInfo``. Each flag is sent as 1 (on) or 2 (off); ``None``
    means the cloud did not report it. The descaling flag is omitted for
    member (``userType`` ``"M"``) accounts.
    """

    is_error_alarm: PushFlag = None
    is_descaling_alarm: PushFlag = None
    is_etc_alarm: PushFlag = None

    def to_request_dict(self) -> dict[str, int]:
        """Flags encoded as the API expects (1=on, 2=off), unset ones omitted.

        Mirrors the NaviLink app, which leaves a key out of
        ``/user/set-push-settings`` when its value is 0.
        """
        encoded = {
            "isErrorAlarm": python_to_push_flag(self.is_error_alarm),
            "isDescalingAlarm": python_to_push_flag(self.is_descaling_alarm),
            "isEtcAlarm": python_to_push_flag(self.is_etc_alarm),
        }
        return {k: v for k, v in encoded.items() if v is not None}


class Device(NavienBaseModel):
    """Complete device information including location."""

    device_info: DeviceInfo
    location: Location
    #: Present on ``/device/list``; absent from ``/device/info``.
    error: DeviceErrorSummary | None = None
    #: Present on both ``/device/list`` and ``/device/info``.
    descaling: DescalingInfo | None = None
    #: Present on ``/device/info``; absent from ``/device/list``.
    installer: DeviceInstaller | None = None
    #: Push-notification flags; present on ``/device/info`` only.
    alarm_info: PushSettings | None = None

    def with_info(self, info: DeviceInfo) -> Self:
        """Return a new Device instance with updated DeviceInfo."""
        return self.model_copy(update={"device_info": info})


class FirmwareDeviceGroup(NavienBaseModel):
    """Firmware group membership reported by ``/device/firmware/info``.

    The NaviLink app reads ``deviceGroup`` as an object with ``groupSeq``
    and ``unitNum``; the cloud sends ``null`` for a stand-alone unit.
    """

    group_seq: int | None = None
    unit_num: int | None = None


class FirmwareInfo(NavienBaseModel):
    """Firmware information for a device."""

    mac_address: str = ""
    additional_value: str = ""
    device_type: DeviceType | int = DeviceType.NPF700_WIFI
    cur_sw_code: int = 0
    cur_version: int = 0
    downloaded_version: int | None = None
    #: An object per the app's parser. A bare string is still accepted
    #: because earlier docs showed one; ``None`` for a stand-alone unit.
    device_group: FirmwareDeviceGroup | str | None = None
    #: Unit number within the group, sent at the top level by some
    #: responses (the app reads both this and ``deviceGroup.unitNum``).
    device_group_unit_no: int | None = None


class FirmwareDetail(NavienBaseModel):
    """Description of one firmware image, from ``POST /firmware/info``.

    Looked up by the ``swCode``/``swVersion`` pair that
    :class:`FirmwareInfo` reports; the NaviLink app shows ``description``
    on its update screen and ``run_time`` as the estimated update time.
    """

    description: str | None = None
    #: The integer fields read ``null`` as 0, as the app does.
    model_number: NullableInt = 0
    model_type: NullableInt = 0
    product_family: NullableInt = 0
    #: When the image was registered, as the cloud sends it (epoch
    #: milliseconds).
    register_at: NullableInt = 0
    #: Estimated update duration in minutes (added in NaviLink 2.04.00).
    run_time: NullableInt = 0
    sw_code: NullableInt = 0
    sw_version: NullableInt = 0


class DisplayPreferences(NavienBaseModel):
    """Unit display preferences from ``/device/preferences/format``.

    The NaviLink app compares ``temperatureDisplayFormat`` against ``"F"``
    (the other value it writes is ``"C"``) and ``pressureDisplayFormat``
    against ``"P"`` (psi; the alternative it writes is ``"M"``).
    """

    model_type_code: int | None = None
    #: ``"P"`` (psi) or ``"M"`` (metric).
    pressure_display_format: str | None = None
    #: ``"F"`` or ``"C"``.
    temperature_display_format: str | None = None


class SimpleDevice(NavienBaseModel):
    """One entry of ``POST /device/simple-list``.

    A trimmed device record: identifiers, type and name only. The app uses
    it for the product-management list and for an installer viewing an
    owner's devices.
    """

    mac_address: str = ""
    additional_value: str = ""
    device_type: DeviceType | int = DeviceType.NPF700_WIFI
    model_type_code: int | None = None
    device_name: str = ""


class DeviceErrorHistoryEntry(NavienBaseModel):
    """One recorded fault from ``POST /device/error/list``."""

    channel_number: int = 0
    unit_type: int = 0
    #: See :attr:`DeviceErrorSummary.error_code` for why this is a
    #: left-to-right union.
    error_code: ErrorCode | int | None = Field(
        default=None, union_mode="left_to_right"
    )
    sub_error: int = 0
    #: Epoch milliseconds. Spelled "Occured" by the API; the Python name is
    #: spelled correctly. The app passes the last entry's value back as
    #: ``continuousKey`` to fetch the next page. An ISO 8601 string is
    #: converted (see :func:`epoch_ms_to_python`).
    error_occurred_time: Annotated[
        int | None, BeforeValidator(epoch_ms_to_python)
    ] = Field(default=None, alias="errorOccuredTime")
    #: The list's ``timeZone`` (an IANA name), which the app formats the
    #: times in. ``None`` when the cloud sends none.
    time_zone: str | None = None

    @property
    def occurred_at(self) -> datetime | None:
        """``error_occurred_time`` as an aware UTC datetime."""
        if self.error_occurred_time is None:
            return None
        return datetime.fromtimestamp(self.error_occurred_time / 1000, tz=UTC)

    @property
    def occurred_at_local(self) -> datetime | None:
        """``occurred_at`` in ``time_zone``; in UTC when the zone is
        missing or unknown."""
        moment = self.occurred_at
        if moment is None or not self.time_zone:
            return moment
        try:
            return moment.astimezone(ZoneInfo(self.time_zone))
        except ZoneInfoNotFoundError, ValueError:
            return moment
