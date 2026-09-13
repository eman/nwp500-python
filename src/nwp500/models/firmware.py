"""Firmware download information (``st/dl-sw-info`` query).

Requested with command 16777227 on ``st/dl-sw-info``. Unlike every other
query, the device answers on the **device-keyed** topic
``cmd/{deviceType}/navilink-{mac}/res/dl-sw-info`` rather than a
client-keyed one, so the response is delivered through the device
wildcard subscription.
"""

from pydantic import Field, computed_field

from .._base import NavienBaseModel
from ..enums import FirmwareType

__all__ = ["FirmwareDownloadEntry", "FirmwareDownloadInfo"]


class FirmwareDownloadEntry(NavienBaseModel):
    """One downloadable firmware component.

    The only capture available (a unit with no pending update) reports a
    single all-zero entry, so the meaning of ``ota_mode`` and ``status``
    values other than 0 is unknown.
    """

    sw_code: int = 0
    ota_mode: int = 0
    sw_version: int = 0
    status: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def component_name(self) -> str:
        """Human-readable firmware component name from ``sw_code``."""
        try:
            return FirmwareType(self.sw_code).name.replace("_", " ").title()
        except ValueError:
            return f"Unknown ({self.sw_code})"


class FirmwareDownloadInfo(NavienBaseModel):
    """Decoded ``res/dl-sw-info`` response."""

    device_type: int = 0
    mac_address: str = ""
    additional_value: str = ""
    download_sw_info: list[FirmwareDownloadEntry] = Field(default_factory=list)
