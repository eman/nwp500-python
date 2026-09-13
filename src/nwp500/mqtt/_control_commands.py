"""Device control command proxies for :class:`NavienMqttClient`.

This mixin holds the thin public convenience methods that forward Navien
device-control commands to :class:`~nwp500.mqtt.control.MqttDeviceController`.
Splitting them out of ``client.py`` keeps :class:`NavienMqttClient` focused on
connection orchestration while preserving its public API surface.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from .control import MqttDeviceController

if TYPE_CHECKING:
    from ..models import (
        Device,
        OtaCommitPayload,
        RecirculationSchedule,
    )

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"


class DeviceControlCommandsMixin:
    """Public device-control commands that delegate to the controller."""

    # Provided by NavienMqttClient.__init__.
    _device_controller: MqttDeviceController

    async def request_device_status(self, device: Device) -> int:
        """Request general device status."""
        return await self._device_controller.request_device_status(device)

    async def request_device_info(self, device: Device) -> int:
        """Request device information (features, firmware, etc.)."""
        return await self._device_controller.request_device_info(device)

    async def set_power(self, device: Device, power_on: bool) -> int:
        """Turn device on or off."""
        return await self._device_controller.set_power(device, power_on)

    async def set_dhw_mode(
        self, device: Device, mode_id: int, vacation_days: int | None = None
    ) -> int:
        """Set DHW operation mode."""
        return await self._device_controller.set_dhw_mode(
            device, mode_id, vacation_days
        )

    async def enable_anti_legionella(
        self, device: Device, period_days: int
    ) -> int:
        """Enable Anti-Legionella disinfection."""
        return await self._device_controller.enable_anti_legionella(
            device, period_days
        )

    async def disable_anti_legionella(self, device: Device) -> int:
        """Disable the Anti-Legionella disinfection cycle."""
        return await self._device_controller.disable_anti_legionella(device)

    async def set_dhw_temperature(
        self, device: Device, temperature: float
    ) -> int:
        """Set DHW target temperature in the user's preferred unit."""
        return await self._device_controller.set_dhw_temperature(
            device, temperature
        )

    async def update_reservations(
        self,
        device: Device,
        reservations: Sequence[dict[str, Any]],
        *,
        enabled: bool = True,
    ) -> int:
        """Update programmed reservations."""
        return await self._device_controller.update_reservations(
            device, reservations, enabled=enabled
        )

    async def request_reservations(self, device: Device) -> int:
        """Request the current reservation program from the device."""
        return await self._device_controller.request_reservations(device)

    async def configure_tou_schedule(
        self,
        device: Device,
        controller_serial_number: str,
        periods: Sequence[dict[str, Any]],
        *,
        enabled: bool = True,
    ) -> int:
        """Configure the Time-of-Use rate schedule."""
        return await self._device_controller.configure_tou_schedule(
            device, controller_serial_number, periods, enabled=enabled
        )

    async def set_tou_enabled(self, device: Device, enabled: bool) -> int:
        """Enable or disable Time-of-Use optimization."""
        return await self._device_controller.set_tou_enabled(device, enabled)

    async def request_energy_usage(
        self, device: Device, year: int, months: list[int]
    ) -> int:
        """Request daily energy usage data for specified month(s)."""
        return await self._device_controller.request_energy_usage(
            device, year, months
        )

    async def request_energy_usage_monthly(
        self, device: Device, years: list[int]
    ) -> int:
        """Request per-month energy usage for whole years."""
        return await self._device_controller.request_energy_usage_monthly(
            device, years
        )

    async def request_energy_usage_hourly(
        self, device: Device, year: int, month: int, days: list[int]
    ) -> int:
        """Request per-hour energy usage for specific days."""
        return await self._device_controller.request_energy_usage_hourly(
            device, year, month, days
        )

    async def request_diagnostics(self, device: Device) -> int:
        """Request the installer diagnostics counters."""
        return await self._device_controller.request_diagnostics(device)

    async def request_firmware_download_info(self, device: Device) -> int:
        """Request the firmware download (OTA) information."""
        controller = self._device_controller
        return await controller.request_firmware_download_info(device)

    async def request_recirculation_schedule(self, device: Device) -> int:
        """Request the recirculation pump schedule from the device."""
        controller = self._device_controller
        return await controller.request_recirculation_schedule(device)

    async def signal_app_connection(self, device: Device) -> int:
        """Signal that the app has connected."""
        return await self._device_controller.signal_app_connection(device)

    async def enable_demand_response(self, device: Device) -> int:
        """Enable utility demand response participation."""
        return await self._device_controller.enable_demand_response(device)

    async def disable_demand_response(self, device: Device) -> int:
        """Disable utility demand response participation."""
        return await self._device_controller.disable_demand_response(device)

    async def reset_air_filter(self, device: Device) -> int:
        """Reset air filter maintenance timer."""
        return await self._device_controller.reset_air_filter(device)

    async def set_vacation_days(self, device: Device, days: int) -> int:
        """Enter vacation mode for ``days`` days (1-30)."""
        return await self._device_controller.set_vacation_days(device, days)

    async def set_vacation_duration(self, device: Device, days: int) -> int:
        """Set the vacation day count without changing the operation mode."""
        return await self._device_controller.set_vacation_duration(device, days)

    async def set_air_filter_life(self, device: Device, hours: int) -> int:
        """Set the air filter service interval (0 or 1000-10000 hours)."""
        return await self._device_controller.set_air_filter_life(device, hours)

    async def reset_condenser_fault(self, device: Device) -> int:
        """Clear a condenser fault (installer-level in the app)."""
        return await self._device_controller.reset_condenser_fault(device)

    async def configure_reservation_water_program(self, device: Device) -> int:
        """Enable/configure water program reservation mode."""
        controller = self._device_controller
        return await controller.configure_reservation_water_program(device)

    async def configure_recirculation_schedule(
        self, device: Device, schedule: RecirculationSchedule
    ) -> int:
        """Configure the recirculation pump timed schedule."""
        return await self._device_controller.configure_recirculation_schedule(
            device, schedule
        )

    async def set_recirculation_mode(self, device: Device, mode: int) -> int:
        """Set recirculation pump operation mode (1-4)."""
        return await self._device_controller.set_recirculation_mode(
            device, mode
        )

    async def trigger_recirculation_hot_button(self, device: Device) -> int:
        """Manually trigger the recirculation pump hot button."""
        return await self._device_controller.trigger_recirculation_hot_button(
            device
        )

    async def commit_firmware_update(
        self, device: Device, payload: OtaCommitPayload
    ) -> int:
        """Commit a previously downloaded firmware update."""
        return await self._device_controller.commit_firmware_update(
            device, payload
        )

    async def enable_intelligent_scheduling(self, device: Device) -> int:
        """Enable intelligent/adaptive heating mode."""
        return await self._device_controller.enable_intelligent_scheduling(
            device
        )

    async def disable_intelligent_scheduling(self, device: Device) -> int:
        """Disable intelligent/adaptive heating mode."""
        return await self._device_controller.disable_intelligent_scheduling(
            device
        )
