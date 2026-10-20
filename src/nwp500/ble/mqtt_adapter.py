"""A :class:`NavienBleClient` presented through the MQTT client's methods.

Code written against :class:`nwp500.NavienMqttClient` (the ``nwp-cli``
handlers, for one) can run over Bluetooth for the operations the heater
supports there: the device-feature request, answered from the ``DID``,
``MSCD`` and ``MSWD`` blocks, and the status request, answered from the
``RTMD`` stream. Every other MQTT client attribute raises
:class:`BleUnsupportedError`, since every class the heater answers is
read-only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..exceptions import Nwp500Error
from ..temperature import HalfCelsius
from .client import NavienBleClient
from .protocol import (
    ControllerSerials,
    DeviceInfoBlock,
    RealTimeStatus,
    SoftwareInfoBlock,
    prefers_celsius,
    temperature_unit,
)


class BleUnsupportedError(Nwp500Error):
    """The operation has no Bluetooth equivalent on the NWP500."""

    def __init__(self, operation: str) -> None:
        super().__init__(f"{operation} is not available over Bluetooth")
        self.operation = operation


@dataclass(frozen=True)
class BleDeviceFeature:
    """The :class:`~nwp500.models.DeviceFeature` fields Bluetooth carries.

    The adapter delivers this where the MQTT client delivers a
    ``DeviceFeature``. The fields have the same names and raw encodings,
    and each was checked against the same heater's MQTT device-info
    report (2026-10-19): the controller serial (``MSCD``), the setpoint
    range (``DID`` bytes 16 and 17, half-degrees Celsius), the model type
    (byte 21), the country code (byte 24) and the controller software code
    (``MSWD`` bytes 0-3). Any other ``DeviceFeature``
    field, such as the capability flags or firmware versions, is not in
    these blocks and raises :class:`AttributeError` here rather than
    reading as a default; read those over MQTT.

    ``dhw_temperature_min`` and ``dhw_temperature_max`` convert as the
    ``DeviceFeature`` properties do, following the unit-system preference.
    The heater's own display unit is not in these blocks, so without a
    preference they are Fahrenheit.
    """

    controller_serial_number: str
    dhw_temperature_min_raw: int
    dhw_temperature_max_raw: int
    model_type_code: int
    country_code: int
    controller_sw_code: int

    @property
    def dhw_temperature_min(self) -> float:
        return HalfCelsius(self.dhw_temperature_min_raw).to_preferred(
            prefers_celsius()
        )

    @property
    def dhw_temperature_max(self) -> float:
        return HalfCelsius(self.dhw_temperature_max_raw).to_preferred(
            prefers_celsius()
        )

    def get_field_unit(self, field_name: str) -> str:
        """Unit suffix for a field, as ``DeviceFeature.get_field_unit``."""
        if field_name.removesuffix("_raw") in {
            "dhw_temperature_min",
            "dhw_temperature_max",
        }:
            return temperature_unit()
        return ""


FeatureCallback = Callable[[BleDeviceFeature], None]
StatusCallback = Callable[[RealTimeStatus], None]


def device_feature_from_blocks(
    info: DeviceInfoBlock,
    serials: ControllerSerials,
    software: SoftwareInfoBlock,
) -> BleDeviceFeature:
    """The device-feature fields in the ``DID``, ``MSCD``, ``MSWD`` blocks."""
    return BleDeviceFeature(
        controller_serial_number=serials.controller_serial_number,
        dhw_temperature_max_raw=info.dhw_temperature_max_raw,
        dhw_temperature_min_raw=info.dhw_temperature_min_raw,
        model_type_code=info.model_type_code,
        country_code=info.country_code,
        controller_sw_code=software.controller_sw_code,
    )


class BleMqttAdapter:
    """Run code written for :class:`~nwp500.NavienMqttClient` over Bluetooth.

    The ``device`` arguments the MQTT methods take are accepted and
    ignored: the connection is already to one heater. A subscription
    callback is called once per matching request, with the decoded reply,
    as the MQTT client does. Where the MQTT client delivers a
    ``DeviceStatus``, the adapter delivers a
    :class:`~nwp500.ble.RealTimeStatus`, which has the status fields
    Bluetooth carries under the same names. A device info request ends a
    status stream, which the next status request starts again.
    :attr:`device_info` and :attr:`controller_serials` keep the last blocks
    read, for callers that want the whole blocks rather than the
    :class:`BleDeviceFeature` subset.

    Example::

        async with BleMqttAdapter(NavienBleClient(address)) as mqtt:
            serial = await get_controller_serial_number(mqtt, None)
    """

    def __init__(self, client: NavienBleClient) -> None:
        self.client = client
        self.device_info: DeviceInfoBlock | None = None
        self.controller_serials: ControllerSerials | None = None
        self.software_info: SoftwareInfoBlock | None = None
        self._feature_callbacks: list[FeatureCallback] = []
        self._status_callbacks: list[StatusCallback] = []

    async def __aenter__(self) -> BleMqttAdapter:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()

    async def connect(self) -> bool:
        await self.client.connect()
        return True

    async def disconnect(self) -> None:
        await self.client.disconnect()

    async def subscribe_device_feature(
        self, device: Any, callback: FeatureCallback
    ) -> int:
        self._feature_callbacks.append(callback)
        return 0

    async def request_device_info(self, device: Any) -> int:
        """Read the blocks and deliver a :class:`BleDeviceFeature`.

        Reads ``DID``, ``MSCD`` and ``MSWD``.

        Raises:
            CrcMismatchError: A reply failed its checksum.
            TimeoutError: The heater did not answer.
        """
        self.device_info = await self.client.read_device_info()
        self.controller_serials = await self.client.read_controller_serials()
        self.software_info = await self.client.read_software_info()
        feature = device_feature_from_blocks(
            self.device_info, self.controller_serials, self.software_info
        )
        for callback in list(self._feature_callbacks):
            callback(feature)
        return 0

    async def subscribe_device_status(
        self, device: Any, callback: StatusCallback
    ) -> int:
        self._status_callbacks.append(callback)
        return 0

    async def request_device_status(self, device: Any) -> int:
        """Deliver the next :class:`~nwp500.ble.RealTimeStatus` block.

        The first request starts the heater's status stream; see
        :meth:`~nwp500.ble.NavienBleClient.read_status`.

        Raises:
            CrcMismatchError: The block failed its checksum.
            TimeoutError: No block arrived.
        """
        status = await self.client.read_status()
        for callback in list(self._status_callbacks):
            callback(status)
        return 0

    def __getattr__(self, name: str) -> Any:
        # Only reached for names not defined above: everything else the
        # MQTT client offers.
        if name.startswith("_"):
            raise AttributeError(name)
        raise BleUnsupportedError(name)


__all__ = [
    "BleDeviceFeature",
    "BleMqttAdapter",
    "BleUnsupportedError",
    "device_feature_from_blocks",
]
