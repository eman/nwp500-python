"""Per-device state change detection for Navien MQTT clients.

Compares successive :class:`DeviceStatus` snapshots for each device and emits
granular events when individual fields change (temperature, mode, power,
errors).
"""

import logging

from ..events import EventEmitter
from ..models import DeviceStatus
from ..mqtt_events import (
    ErrorClearedEvent,
    ErrorDetectedEvent,
    HeatingStartedEvent,
    HeatingStoppedEvent,
    ModeChangedEvent,
    PowerChangedEvent,
    TemperatureChangedEvent,
)
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

        - ``temperature_changed(TemperatureChangedEvent(...))``
        - ``mode_changed(ModeChangedEvent(...))``
        - ``power_changed(PowerChangedEvent(...))``
        - ``heating_started(HeatingStartedEvent(...))``
        - ``heating_stopped(HeatingStoppedEvent(...))``
        - ``error_detected(ErrorDetectedEvent(...))``
        - ``error_cleared(ErrorClearedEvent(...))``

        Args:
            device_mac: MAC address used as the per-device key.
            status: Freshly received :class:`DeviceStatus`.
        """
        if device_mac not in self._previous_status:
            self._previous_status[device_mac] = status
            return

        prev = self._previous_status[device_mac]

        try:
            # Temperature change (compare raw values)
            if status.dhw_temperature_raw != prev.dhw_temperature_raw:
                await self._event_emitter.emit(
                    "temperature_changed",
                    TemperatureChangedEvent(
                        device_mac=device_mac,
                        old_temperature=prev.dhw_temperature,
                        new_temperature=status.dhw_temperature,
                    ),
                )
                unit_suffix = "°C" if get_unit_system() == "metric" else "°F"
                _logger.debug(
                    "Temperature changed: %s%s → %s%s",
                    prev.dhw_temperature,
                    unit_suffix,
                    status.dhw_temperature,
                    unit_suffix,
                )

            # Operation mode change (compare raw values)
            if status.operation_mode != prev.operation_mode:
                await self._event_emitter.emit(
                    "mode_changed",
                    ModeChangedEvent(
                        device_mac=device_mac,
                        old_mode=prev.operation_mode,
                        new_mode=status.operation_mode,
                    ),
                )
                _logger.debug(
                    "Mode changed: %s → %s",
                    prev.operation_mode,
                    status.operation_mode,
                )

            # Power consumption change (compare raw values)
            if status.current_inst_power != prev.current_inst_power:
                await self._event_emitter.emit(
                    "power_changed",
                    PowerChangedEvent(
                        device_mac=device_mac,
                        old_power=prev.current_inst_power,
                        new_power=status.current_inst_power,
                    ),
                )
                _logger.debug(
                    "Power changed: %sW → %sW",
                    prev.current_inst_power,
                    status.current_inst_power,
                )

            # Heating started / stopped (compare raw values)
            prev_heating = prev.current_inst_power > 0
            curr_heating = status.current_inst_power > 0

            if curr_heating and not prev_heating:
                await self._event_emitter.emit(
                    "heating_started",
                    HeatingStartedEvent(device_mac=device_mac, status=status),
                )
                _logger.debug("Heating started")

            if not curr_heating and prev_heating:
                await self._event_emitter.emit(
                    "heating_stopped",
                    HeatingStoppedEvent(device_mac=device_mac, status=status),
                )
                _logger.debug("Heating stopped")

            # Error detection / clearance. Also emit when the error code
            # CHANGES between two non-zero codes (e.g. E799 -> E407), so
            # consumers never keep displaying a stale error.
            if status.error_code and status.error_code != prev.error_code:
                await self._event_emitter.emit(
                    "error_detected",
                    ErrorDetectedEvent(
                        device_mac=device_mac,
                        error_code=status.error_code,
                        status=status,
                    ),
                )
                _logger.info("Error detected: %s", status.error_code)

            if not status.error_code and prev.error_code:
                await self._event_emitter.emit(
                    "error_cleared",
                    ErrorClearedEvent(
                        device_mac=device_mac, error_code=prev.error_code
                    ),
                )
                _logger.info("Error cleared: %s", prev.error_code)

        except (TypeError, AttributeError, RuntimeError) as e:
            _logger.error("Error detecting state changes: %s", e, exc_info=True)
        finally:
            self._previous_status[device_mac] = status
