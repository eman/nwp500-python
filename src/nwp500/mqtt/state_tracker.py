"""Per-device state change detection for Navien MQTT clients.

Compares successive :class:`DeviceStatus` snapshots for each device and emits
granular events when individual fields change (temperature, mode, power,
errors).
"""

from __future__ import annotations

import logging

from ..events import EventEmitter
from ..models import DeviceStatus
from ..unit_system import get_unit_system

_logger = logging.getLogger(__name__)


class DeviceStateTracker:
    """Tracks previous device states and emits change events.

    Each device (identified by MAC address) gets its own slot in
    ``_previous_status``.  On every new status update, this class compares
    it against the stored snapshot and emits events for changed fields,
    then stores the new snapshot.
    """

    def __init__(self, event_emitter: EventEmitter) -> None:
        self._event_emitter = event_emitter
        self._previous_status: dict[str, DeviceStatus] = {}

    def clear(self) -> None:
        """Drop all stored snapshots (call on disconnect)."""
        self._previous_status.clear()

    async def process(self, device_mac: str, status: DeviceStatus) -> None:
        """Compare *status* with the previous snapshot for *device_mac*.

        Emits the following events when values change:

        - ``temperature_changed(prev_temp, curr_temp)``
        - ``mode_changed(prev_mode, curr_mode)``
        - ``power_changed(prev_power, curr_power)``
        - ``heating_started(curr_status)``
        - ``heating_stopped(curr_status)``
        - ``error_detected(error_code, curr_status)``
        - ``error_cleared(prev_error_code)``

        Args:
            device_mac: MAC address used as the per-device key.
            status: Freshly received :class:`DeviceStatus`.
        """
        if device_mac not in self._previous_status:
            self._previous_status[device_mac] = status
            return

        prev = self._previous_status[device_mac]

        try:
            # Temperature change
            if status.dhw_temperature != prev.dhw_temperature:
                await self._event_emitter.emit(
                    "temperature_changed",
                    prev.dhw_temperature,
                    status.dhw_temperature,
                )
                unit_suffix = "°C" if get_unit_system() == "metric" else "°F"
                _logger.debug(
                    "Temperature changed: %s%s → %s%s",
                    prev.dhw_temperature,
                    unit_suffix,
                    status.dhw_temperature,
                    unit_suffix,
                )

            # Operation mode change
            if status.operation_mode != prev.operation_mode:
                await self._event_emitter.emit(
                    "mode_changed",
                    prev.operation_mode,
                    status.operation_mode,
                )
                _logger.debug(
                    "Mode changed: %s → %s",
                    prev.operation_mode,
                    status.operation_mode,
                )

            # Power consumption change
            if status.current_inst_power != prev.current_inst_power:
                await self._event_emitter.emit(
                    "power_changed",
                    prev.current_inst_power,
                    status.current_inst_power,
                )
                _logger.debug(
                    "Power changed: %sW → %sW",
                    prev.current_inst_power,
                    status.current_inst_power,
                )

            # Heating started / stopped
            prev_heating = prev.current_inst_power > 0
            curr_heating = status.current_inst_power > 0

            if curr_heating and not prev_heating:
                await self._event_emitter.emit("heating_started", status)
                _logger.debug("Heating started")

            if not curr_heating and prev_heating:
                await self._event_emitter.emit("heating_stopped", status)
                _logger.debug("Heating stopped")

            # Error detection / clearance
            if status.error_code and not prev.error_code:
                await self._event_emitter.emit(
                    "error_detected", status.error_code, status
                )
                _logger.info("Error detected: %s", status.error_code)

            if not status.error_code and prev.error_code:
                await self._event_emitter.emit("error_cleared", prev.error_code)
                _logger.info("Error cleared: %s", prev.error_code)

        except (TypeError, AttributeError, RuntimeError) as e:
            _logger.error("Error detecting state changes: %s", e, exc_info=True)
        finally:
            self._previous_status[device_mac] = status
