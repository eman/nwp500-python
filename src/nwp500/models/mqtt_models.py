from enum import IntEnum
from typing import Any

from pydantic import Field, field_validator

from .._base import NavienBaseModel
from ..enums import DeviceType

#: Value the library sends in ``event.connection.os`` of app-connection
#: messages. ``"A"`` is Android's tag. Only ``status`` and ``sessionNumber``
#: carry meaning on the topic, and AWS IoT delivers the message to
#: subscribers unchanged, so the library identifies itself as ``"P"``
#: (Python) instead of using Android's tag.
APP_CONNECTION_OS = "P"

#: ``protocolVersion`` of app-connection messages.
APP_CONNECTION_PROTOCOL_VERSION = 1


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


class ControlFailCode(IntEnum):
    """``failCode`` values of a control failure (``res/ctrl-fail``).

    One value is known: 2, "DHW control interval exceeded". Any other
    value has no known meaning; the library keeps such values as plain
    ``int``.
    """

    DHW_CONTROL_INTERVAL_EXCEEDED = 2
    """The device refused a DHW control because the previous one was too
    recent. Wait and resend."""


class ControlFailDetail(NavienBaseModel):
    """The ``response`` object of a control failure message."""

    device_type: DeviceType | int
    mac_address: str
    additional_value: str = ""
    fail_code: ControlFailCode | int
    sw_version: int | None = None

    @field_validator("fail_code", mode="after")
    @classmethod
    def _known_fail_code(cls, value: int) -> ControlFailCode | int:
        """Promote a known code to :class:`ControlFailCode`.

        Pydantic's union resolution keeps an ``int`` input as ``int``, so
        known codes are promoted here; unknown ones stay plain integers.
        """
        try:
            return ControlFailCode(value)
        except ValueError:
            return value

    @property
    def reason(self) -> str:
        """Human-readable meaning of :attr:`fail_code`."""
        if self.fail_code == ControlFailCode.DHW_CONTROL_INTERVAL_EXCEEDED:
            return "DHW control interval exceeded"
        return f"unknown failure code {int(self.fail_code)}"


class ControlFailResponse(NavienBaseModel):
    """A control failure published on ``res/ctrl-fail``.

    Sent on ``cmd/{deviceType}/navilink-{mac}/res/ctrl-fail`` when the
    device rejects a control command. The envelope names the client whose
    command failed (``clientID``, ``sessionID``, ``requestTopic``) and
    ``response`` carries the device identity and the ``failCode``.
    """

    client_id: str | None = Field(default=None, alias="clientID")
    session_id: str | None = Field(default=None, alias="sessionID")
    request_topic: str | None = None
    protocol_version: int | None = None
    response: ControlFailDetail

    @property
    def fail_code(self) -> ControlFailCode | int:
        """Shortcut for ``response.fail_code``."""
        return self.response.fail_code

    @property
    def reason(self) -> str:
        """Shortcut for ``response.reason``."""
        return self.response.reason

    @property
    def mac_address(self) -> str:
        """Shortcut for ``response.mac_address``."""
        return self.response.mac_address


class AppConnectionStatus(NavienBaseModel):
    """The ``connection`` object of an app-connection message.

    ``status`` is 1 while the publishing client is connected and 0 in
    the Last-Will the broker publishes when it drops. Any value at or
    below 0 means disconnected. ``os`` is set by the publisher
    (``"A"`` for Android, :data:`APP_CONNECTION_OS` for this
    library); ``sessionNumber``, which the device's ``connection``
    event carries, is kept when present.
    """

    status: int
    os: str | None = None
    session_number: int | None = None

    @property
    def connected(self) -> bool:
        """``True`` when ``status`` is above 0."""
        return self.status > 0


class AppConnectionInfo(NavienBaseModel):
    """The ``event`` object of an app-connection message."""

    mac_address: str
    device_type: DeviceType | int
    additional_value: str = ""
    model_type_code: int | None = None
    connection: AppConnectionStatus


class AppConnectionEvent(NavienBaseModel):
    """An app-connection message (``evt/.../app-connection``).

    Published by a client when it connects to a device
    (``connection.status`` 1) and by the broker as that client's
    Last-Will when its connection is lost without a DISCONNECT
    (``connection.status`` 0).
    """

    client_id: str | None = Field(default=None, alias="clientID")
    session_id: str | None = Field(default=None, alias="sessionID")
    protocol_version: int = APP_CONNECTION_PROTOCOL_VERSION
    request_topic: str | None = None
    event: AppConnectionInfo

    @property
    def connected(self) -> bool:
        """Shortcut for ``event.connection.connected``."""
        return self.event.connection.connected

    @property
    def mac_address(self) -> str:
        """Shortcut for ``event.mac_address``."""
        return self.event.mac_address

    @classmethod
    def build(
        cls,
        *,
        client_id: str,
        session_id: str,
        topic: str,
        mac_address: str,
        device_type: int,
        additional_value: str = "",
        model_type_code: int | None = None,
        connected: bool,
        os: str = APP_CONNECTION_OS,
    ) -> AppConnectionEvent:
        """Build the message a client publishes for itself.

        Args:
            client_id: The publishing client's MQTT client ID.
            session_id: The publishing client's session ID.
            topic: The app-connection topic, echoed as ``requestTopic``.
            mac_address: Device MAC address.
            device_type: Device type code (52 for the NWP500).
            additional_value: ``additionalValue`` from the device info.
            model_type_code: ``modelTypeCode`` from the device info.
            connected: ``True`` for a connect announcement (status 1),
                ``False`` for a Last-Will (status 0).
            os: Publisher platform tag.
        """
        return cls(
            clientID=client_id,
            sessionID=session_id,
            request_topic=topic,
            event=AppConnectionInfo(
                mac_address=mac_address,
                device_type=device_type,
                additional_value=additional_value,
                model_type_code=model_type_code,
                connection=AppConnectionStatus(
                    status=1 if connected else 0, os=os
                ),
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        """The JSON object to publish, with protocol field names."""
        payload = self.to_protocol_dict()
        event = payload["event"]
        # device_type may be a DeviceType enum, which to_protocol_dict
        # renders by name; the wire wants the integer code.
        event["deviceType"] = int(self.event.device_type)
        if event.get("modelTypeCode") is None:
            event.pop("modelTypeCode", None)
        if event["connection"].get("sessionNumber") is None:
            event["connection"].pop("sessionNumber", None)
        return payload
