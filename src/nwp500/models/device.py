from typing import Annotated, Self

from pydantic import BeforeValidator, Field

from .._base import NavienBaseModel
from ..converters import enum_validator
from ..enums import ConnectionStatus, DeviceType, ErrorCode

ConnectionStatusField = Annotated[
    ConnectionStatus, BeforeValidator(enum_validator(ConnectionStatus))
]


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

    #: ``NO_ERROR`` when the device has no recorded fault. Typed to accept a
    #: bare int as well, following ``device_type``, so a code the enum does
    #: not know cannot make a whole ``/device/list`` response unparseable.
    error_code: ErrorCode | int = ErrorCode.NO_ERROR
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


class Device(NavienBaseModel):
    """Complete device information including location."""

    device_info: DeviceInfo
    location: Location
    #: Present on ``/device/list``; absent from ``/device/info``.
    error: DeviceErrorSummary | None = None
    #: Present on both ``/device/list`` and ``/device/info``.
    descaling: DescalingInfo | None = None

    def with_info(self, info: DeviceInfo) -> Self:
        """Return a new Device instance with updated DeviceInfo."""
        return self.model_copy(update={"device_info": info})


class FirmwareInfo(NavienBaseModel):
    """Firmware information for a device."""

    mac_address: str = ""
    additional_value: str = ""
    device_type: DeviceType | int = DeviceType.NPF700_WIFI
    cur_sw_code: int = 0
    cur_version: int = 0
    downloaded_version: int | None = None
    device_group: str | None = None
