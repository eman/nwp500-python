"""
Reservation schedule management helpers.

This module provides high-level helpers for managing individual reservation
entries on a Navien device.  The device protocol requires sending the full
schedule for every change, so each helper follows a read-modify-write pattern:
fetch the current schedule, apply the change, then send the updated list back.

All functions are ``async`` and require a connected :class:`NavienMqttClient`.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from .converters import device_bool_from_python
from .encoding import build_reservation_entry, encode_week_bitfield
from .models import ReservationSchedule

if TYPE_CHECKING:
    from .models import Device
    from .mqtt import NavienMqttClient

_logger = logging.getLogger(__name__)

# Raw protocol fields for ReservationEntry (used in model_dump include)
_RAW_RESERVATION_FIELDS = {
    "enable",
    "week",
    "hour",
    "min",
    "mode",
    "param",
}


async def fetch_reservations(
    mqtt: NavienMqttClient,
    device: Device,
    *,
    timeout: float = 10.0,
) -> ReservationSchedule | None:
    """Fetch the current reservation schedule from a device.

    Sends a request to the device and waits for the response.

    Args:
        mqtt: Connected MQTT client.
        device: Target device.
        timeout: Seconds to wait for a response before giving up.

    Returns:
        The current :class:`ReservationSchedule`, or ``None`` on timeout.
    """
    future: asyncio.Future[ReservationSchedule] = (
        asyncio.get_running_loop().create_future()
    )

    def on_schedule(schedule: ReservationSchedule) -> None:
        if not future.done():
            future.set_result(schedule)

    await mqtt.subscribe_reservation_response(device, on_schedule)
    await mqtt.request_reservations(device)
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        return None
    finally:
        try:
            await mqtt.unsubscribe_reservation_response(device, on_schedule)
        except Exception:
            _logger.warning(
                "Failed to unsubscribe reservations response handler for "
                "device %s",
                device.device_info.mac_address,
                exc_info=True,
            )


async def update_reservations_confirmed(
    mqtt: NavienMqttClient,
    device: Device,
    reservations: Sequence[dict[str, Any]],
    *,
    enabled: bool = True,
    timeout: float = 10.0,
) -> ReservationSchedule | None:
    """Write the full reservation list and confirm the device applied it.

    Sends ``update_reservations`` and waits for the device's ``rsv/rd``
    echo, returning the parsed :class:`ReservationSchedule` the device now
    holds. Compare it against the desired program with
    :meth:`ReservationSchedule.canonical`, e.g.::

        confirmed = await update_reservations_confirmed(mqtt, device, entries)
        assert confirmed is not None
        assert confirmed.canonical() == desired_schedule.canonical()

    Args:
        mqtt: Connected MQTT client.
        device: Target device.
        reservations: List of raw reservation entry dicts to write.
        enabled: Whether reservations are enabled (default: True).
        timeout: Seconds to wait for the confirming response.

    Returns:
        The :class:`ReservationSchedule` the device echoed back after the
        write, or ``None`` if no matching response arrived within
        ``timeout``.

    Note:
        The device protocol has no request/response correlation id on
        ``rsv/rd``, so a response is only accepted once its
        :meth:`~nwp500.models.ReservationSchedule.canonical` form matches
        what was just written. This avoids resolving on a stale/unrelated
        ``rsv/rd`` message (e.g. from a concurrent read or a previous
        write) that happens to arrive in the same window.
    """
    expected = ReservationSchedule(
        reservationUse=device_bool_from_python(enabled),
        reservation=list(reservations),
    ).canonical()

    future: asyncio.Future[ReservationSchedule] = (
        asyncio.get_running_loop().create_future()
    )

    def on_schedule(schedule: ReservationSchedule) -> None:
        if not future.done() and schedule.canonical() == expected:
            future.set_result(schedule)

    await mqtt.subscribe_reservation_response(device, on_schedule)
    try:
        await mqtt.update_reservations(device, reservations, enabled=enabled)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            return None
    finally:
        try:
            await mqtt.unsubscribe_reservation_response(device, on_schedule)
        except Exception:
            from .mqtt.utils import redact_mac

            _logger.warning(
                "Failed to unsubscribe reservations response handler for "
                "device %s",
                redact_mac(device.device_info.mac_address),
                exc_info=True,
            )


async def add_reservation(
    mqtt: NavienMqttClient,
    device: Device,
    *,
    enabled: bool,
    days: Sequence[str | int],
    hour: int,
    minute: int,
    mode: int,
    temperature: float,
) -> None:
    """Add a single reservation entry to the device schedule.

    Fetches the current schedule, appends the new entry, and sends the
    updated list back to the device.  The schedule is automatically enabled
    after a successful add.

    Args:
        mqtt: Connected MQTT client.
        device: Target device.
        enabled: Whether the new reservation is active.
        days: Days of the week.  Accepts full names (``"Monday"``), 2-letter
            abbreviations (``"MO"``), or integer indices where 0 = Monday and
            6 = Sunday.
        hour: Hour of the day in 24-hour format (0–23).
        minute: Minute of the hour (0–59).
        mode: DHW operation mode (1–6).
        temperature: Target temperature in the user's preferred unit.

    Raises:
        ValueError: If ``hour``, ``minute``, or ``mode`` are out of range.
        RangeValidationError: If ``temperature`` is out of the device's range.
        ValidationError: If the entry fails model validation.
        TimeoutError: If the current schedule cannot be fetched.
    """
    if not 0 <= hour <= 23:
        raise ValueError(f"Hour must be between 0 and 23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"Minute must be between 0 and 59, got {minute}")
    if not 1 <= mode <= 6:
        raise ValueError(f"Mode must be between 1 and 6, got {mode}")

    reservation_entry = build_reservation_entry(
        enabled=enabled,
        days=days,
        hour=hour,
        minute=minute,
        mode_id=mode,
        temperature=temperature,
    )

    schedule = await fetch_reservations(mqtt, device)
    if schedule is None:
        raise TimeoutError("Timed out fetching current reservations")

    current_reservations = [
        e.model_dump(include=_RAW_RESERVATION_FIELDS)
        for e in schedule.reservation
    ]
    current_reservations.append(reservation_entry)

    await mqtt.update_reservations(device, current_reservations, enabled=True)


async def delete_reservation(
    mqtt: NavienMqttClient,
    device: Device,
    index: int,
) -> None:
    """Delete a single reservation entry by 1-based index.

    Fetches the current schedule, removes the entry at ``index``, and sends
    the updated list back.  If the schedule becomes empty, it is automatically
    disabled.

    Args:
        mqtt: Connected MQTT client.
        device: Target device.
        index: 1-based position of the reservation to delete.

    Raises:
        ValueError: If ``index`` is out of the valid range.
        TimeoutError: If the current schedule cannot be fetched.
    """
    schedule = await fetch_reservations(mqtt, device)
    if schedule is None:
        raise TimeoutError("Timed out fetching current reservations")

    count = len(schedule.reservation)
    if index < 1 or index > count:
        raise ValueError(
            f"Invalid reservation index {index}. "
            f"Valid range: 1–{count} ({count} reservation(s) exist)"
        )

    current_reservations = [
        e.model_dump(include=_RAW_RESERVATION_FIELDS)
        for e in schedule.reservation
    ]
    removed = current_reservations.pop(index - 1)
    _logger.info(f"Removing reservation {index}: {removed}")

    still_enabled = schedule.enabled and len(current_reservations) > 0

    await mqtt.update_reservations(
        device, current_reservations, enabled=still_enabled
    )


async def update_reservation(
    mqtt: NavienMqttClient,
    device: Device,
    index: int,
    *,
    enabled: bool | None = None,
    days: Sequence[str | int] | None = None,
    hour: int | None = None,
    minute: int | None = None,
    mode: int | None = None,
    temperature: float | None = None,
) -> None:
    """Update a single reservation entry in-place by 1-based index.

    Only the fields that are explicitly provided are changed; all other fields
    are preserved from the existing entry.

    Args:
        mqtt: Connected MQTT client.
        device: Target device.
        index: 1-based position of the reservation to update.
        enabled: Set the enabled state, or ``None`` to keep current.
        days: Replace the days, or ``None`` to keep current.  Accepts full
            names, 2-letter abbreviations, or integer indices (see
            :func:`add_reservation`).
        hour: Replace the hour (0–23), or ``None`` to keep current.
        minute: Replace the minute (0–59), or ``None`` to keep current.
        mode: Replace the mode (1–6), or ``None`` to keep current.
        temperature: Replace the temperature (in the user's preferred unit),
            or ``None`` to keep the existing raw ``param`` value unchanged.

    Raises:
        ValueError: If ``index`` is out of the valid range, or if any of
            ``hour``, ``minute``, or ``mode`` are provided but out of range.
        RangeValidationError: If ``temperature`` is out of the device's range.
        ValidationError: If the updated entry fails model validation.
        TimeoutError: If the current schedule cannot be fetched.
    """
    schedule = await fetch_reservations(mqtt, device)
    if schedule is None:
        raise TimeoutError("Timed out fetching current reservations")

    count = len(schedule.reservation)
    if index < 1 or index > count:
        raise ValueError(
            f"Invalid reservation index {index}. "
            f"Valid range: 1–{count} ({count} reservation(s) exist)"
        )

    if hour is not None and not 0 <= hour <= 23:
        raise ValueError(f"Hour must be between 0 and 23, got {hour}")
    if minute is not None and not 0 <= minute <= 59:
        raise ValueError(f"Minute must be between 0 and 59, got {minute}")
    if mode is not None and not 1 <= mode <= 6:
        raise ValueError(f"Mode must be between 1 and 6, got {mode}")

    existing = schedule.reservation[index - 1]

    new_enabled = enabled if enabled is not None else existing.enabled
    new_days = days if days is not None else existing.days
    new_hour = hour if hour is not None else existing.hour
    new_minute = minute if minute is not None else existing.min
    new_mode = mode if mode is not None else existing.mode

    if temperature is not None:
        new_entry = build_reservation_entry(
            enabled=new_enabled,
            days=new_days,
            hour=new_hour,
            minute=new_minute,
            mode_id=new_mode,
            temperature=temperature,
        )
    else:
        new_entry = {
            "enable": 2 if new_enabled else 1,
            "week": encode_week_bitfield(new_days),
            "hour": new_hour,
            "min": new_minute,
            "mode": new_mode,
            "param": existing.param,
        }

    current_reservations = [
        e.model_dump(include=_RAW_RESERVATION_FIELDS)
        for e in schedule.reservation
    ]
    current_reservations[index - 1] = new_entry

    await mqtt.update_reservations(
        device, current_reservations, enabled=schedule.enabled
    )


__all__ = [
    "fetch_reservations",
    "update_reservations_confirmed",
    "add_reservation",
    "delete_reservation",
    "update_reservation",
]
