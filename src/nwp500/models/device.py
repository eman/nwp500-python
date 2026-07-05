from typing import Annotated, Self

from pydantic import BeforeValidator

from .._base import NavienBaseModel
from ..converters import enum_validator
from ..enums import ConnectionStatus, DeviceType

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


class Location(NavienBaseModel):
    """Location information for a device."""

    state: str | None = None
    city: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None


class Device(NavienBaseModel):
    """Complete device information including location."""

    device_info: DeviceInfo
    location: Location

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
