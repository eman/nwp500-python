"""
TOU (Time-of-Use) schedule management helpers.

Companion to :mod:`nwp500.reservations`: the device protocol requires
sending the full TOU period list for every change, and confirming that a
write landed requires waiting for the device's ``tou/rd`` echo rather than
just the MQTT publish packet id.

All functions are ``async`` and require a connected :class:`NavienMqttClient`.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from .converters import device_bool_from_python
from .models import TOUReservationSchedule

if TYPE_CHECKING:
    from .models import Device
    from .mqtt import NavienMqttClient

_logger = logging.getLogger(__name__)


async def configure_tou_schedule_confirmed(
    mqtt: NavienMqttClient,
    device: Device,
    controller_serial_number: str,
    periods: Sequence[dict[str, Any]],
    *,
    enabled: bool = True,
    timeout: float = 10.0,
) -> TOUReservationSchedule | None:
    """Write the TOU schedule and confirm the device applied it.

    Sends ``configure_tou_schedule`` and waits for the device's ``tou/rd``
    echo, returning the parsed :class:`TOUReservationSchedule` the device
    now holds. Compare it against the desired program with
    :meth:`TOUReservationSchedule.canonical`, e.g.::

        confirmed = await configure_tou_schedule_confirmed(
            mqtt, device, serial, periods
        )
        assert confirmed is not None
        assert confirmed.canonical() == desired_schedule.canonical()

    Args:
        mqtt: Connected MQTT client.
        device: Target device.
        controller_serial_number: Controller serial number.
        periods: List of raw TOU period dicts to write.
        enabled: Whether TOU is enabled (default: True).
        timeout: Seconds to wait for the confirming response.

    Returns:
        The :class:`TOUReservationSchedule` the device echoed back after
        the write, or ``None`` if no matching response arrived within
        ``timeout``.

    Note:
        The device protocol has no request/response correlation id on
        ``tou/rd``, so a response is only accepted once its
        :meth:`~nwp500.models.TOUReservationSchedule.canonical` form
        matches what was just written. This avoids resolving on a
        stale/unrelated ``tou/rd`` message (e.g. from a concurrent read or
        a previous configure) that happens to arrive in the same window.
    """
    expected = TOUReservationSchedule(
        reservationUse=device_bool_from_python(enabled),
        reservation=list(periods),
    ).canonical()

    future: asyncio.Future[TOUReservationSchedule] = (
        asyncio.get_running_loop().create_future()
    )

    def on_schedule(schedule: TOUReservationSchedule) -> None:
        if not future.done() and schedule.canonical() == expected:
            future.set_result(schedule)

    await mqtt.subscribe_tou_response(device, on_schedule)
    try:
        await mqtt.configure_tou_schedule(
            device, controller_serial_number, periods, enabled=enabled
        )
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            return None
    finally:
        try:
            await mqtt.unsubscribe_tou_response(device, on_schedule)
        except Exception:
            from .mqtt.utils import redact_mac

            _logger.warning(
                "Failed to unsubscribe TOU response handler for device %s",
                redact_mac(device.device_info.mac_address),
                exc_info=True,
            )


__all__ = ["configure_tou_schedule_confirmed"]
