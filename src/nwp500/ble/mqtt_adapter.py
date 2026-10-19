"""A :class:`NavienBleClient` presented through the MQTT client's methods.

Code written against :class:`nwp500.NavienMqttClient` (the ``nwp-cli``
handlers, for one) can run over Bluetooth for the operations the heater
supports there. Today that is the device-feature request, answered from
the ``DID`` and ``MSCD`` blocks. Every other MQTT client attribute raises
:class:`BleUnsupportedError`: the heater sends no live status over
Bluetooth, and every class it answers is read-only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..exceptions import Nwp500Error
from .client import NavienBleClient
from .protocol import ControllerSerials, DeviceInfo


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
    (byte 21) and the country code (byte 24). Any other ``DeviceFeature``
    field, such as the capability flags or firmware versions, is not in
    these blocks and raises :class:`AttributeError` here rather than
    reading as a default; read those over MQTT.
    """

    controller_serial_number: str
    dhw_temperature_min_raw: int
    dhw_temperature_max_raw: int
    model_type_code: int
    country_code: int


FeatureCallback = Callable[[BleDeviceFeature], None]


def device_feature_from_blocks(
    info: DeviceInfo, serials: ControllerSerials
) -> BleDeviceFeature:
    """The device-feature fields the ``DID`` and ``MSCD`` blocks carry."""
    return BleDeviceFeature(
        controller_serial_number=serials.product_serial,
        dhw_temperature_max_raw=info.hot_water_temp_max,
        dhw_temperature_min_raw=info.hot_water_temp_min,
        model_type_code=info.model_type,
        country_code=info.country_code,
    )


class BleMqttAdapter:
    """Run code written for :class:`~nwp500.NavienMqttClient` over Bluetooth.

    The ``device`` arguments the MQTT methods take are accepted and
    ignored: the connection is already to one heater. A subscription
    callback is called once per matching request, with the decoded reply,
    as the MQTT client does. :attr:`device_info` and
    :attr:`controller_serials` keep the last blocks read, for callers that
    want the whole blocks rather than the :class:`BleDeviceFeature` subset.

    Example::

        async with BleMqttAdapter(NavienBleClient(address)) as mqtt:
            serial = await get_controller_serial_number(mqtt, None)
    """

    def __init__(self, client: NavienBleClient) -> None:
        self.client = client
        self.device_info: DeviceInfo | None = None
        self.controller_serials: ControllerSerials | None = None
        self._feature_callbacks: list[FeatureCallback] = []

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
        """Read ``DID`` and ``MSCD`` and deliver a :class:`BleDeviceFeature`.

        Raises:
            CrcMismatchError: A reply failed its checksum.
            TimeoutError: The heater did not answer.
        """
        self.device_info = await self.client.read_device_info()
        self.controller_serials = await self.client.read_controller_serials()
        feature = device_feature_from_blocks(
            self.device_info, self.controller_serials
        )
        for callback in list(self._feature_callbacks):
            callback(feature)
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
