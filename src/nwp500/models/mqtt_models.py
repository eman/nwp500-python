from __future__ import annotations

from typing import Any

from pydantic import Field

from .._base import NavienBaseModel
from ..enums import DeviceType


class MqttRequest(NavienBaseModel):
    """MQTT command request payload."""

    command: int
    device_type: DeviceType | int
    mac_address: str
    additional_value: str = "..."
    mode: str | None = None
    param: list[int | float] = Field(default_factory=list)
    param_str: str = ""
    month: list[int] | None = None
    year: int | None = None


class MqttCommand(NavienBaseModel):
    """Represents an MQTT command message."""

    client_id: str = Field(alias="clientID")
    session_id: str = Field(alias="sessionID")
    request_topic: str
    response_topic: str
    request: MqttRequest | dict[str, Any]
    protocol_version: int = 2
