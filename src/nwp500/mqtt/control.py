"""
MQTT Device Control Commands for Navien devices.

This module handles all device control operations including:
- Status and info requests
- Power control
- Mode changes (DHW operation modes)
- Temperature control
- Anti-Legionella configuration
- Reservation scheduling
- Time-of-Use (TOU) configuration
- Energy usage queries
- App connection signaling
- Demand response control
- Air filter maintenance
- Vacation mode configuration
- Recirculation pump control and scheduling
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from ..command_decorators import requires_capability
from ..device_capabilities import MqttDeviceCapabilityChecker
from ..device_info_cache import MqttDeviceInfoCache
from ..enums import CommandCode, DhwOperationSetting
from ..exceptions import (
    DeviceCapabilityError,
    ParameterValidationError,
    RangeValidationError,
)
from ..models import Device, DeviceFeature, fahrenheit_to_half_celsius
from ..topic_builder import MqttTopicBuilder

__author__ = "Emmanuel Levijarvi"

_logger = logging.getLogger(__name__)


class MqttDeviceController:
    """
    Manages device control commands for Navien devices.

    Handles all device control operations including status requests,
    mode changes, temperature control, scheduling, and energy queries.

    This controller integrates with MqttDeviceCapabilityChecker to validate
    device capabilities before executing commands. Use check_support()
    or assert_support() methods to verify feature availability based on
    device capabilities before attempting to execute commands:

    Example:
        >>> controller.assert_support("recirculation_mode", device_features)
        >>> # Will raise DeviceCapabilityError if not supported
        >>> msg_id = await controller.set_recirculation_mode(device, mode)
    """

    def __init__(
        self,
        client_id: str,
        session_id: str,
        publish_func: Callable[..., Awaitable[int]],
        device_info_cache: MqttDeviceInfoCache | None = None,
    ) -> None:
        """
        Initialize device controller.

        Args:
            client_id: MQTT client ID
            session_id: Session ID for commands
            publish_func: Function to publish MQTT messages (async callable)
            device_info_cache: Optional device info cache. If not provided,
                a new cache with 30-minute update interval is created.
        """
        self._client_id = client_id
        self._session_id = session_id
        self._publish: Callable[..., Awaitable[int]] = publish_func
        self._device_info_cache = device_info_cache or MqttDeviceInfoCache(
            update_interval_minutes=30
        )
        # Callback for auto-requesting device info when needed
        self._ensure_device_info_callback: (
            Callable[[Device], Awaitable[bool]] | None
        ) = None

    def set_ensure_device_info_callback(
        self, callback: Callable[[Device], Awaitable[bool]] | None
    ) -> None:
        """Set the callback for ensuring device info is cached."""
        self._ensure_device_info_callback = callback

    @property
    def device_info_cache(self) -> "MqttDeviceInfoCache":
        """Get the device info cache."""
        return self._device_info_cache

    async def _ensure_device_info_cached(
        self, device: Device, timeout: float = 5.0
    ) -> None:
        """
        Ensure device info is cached, requesting if necessary.

        Automatically requests device info if not already cached.
        Used internally by control commands.

        Args:
            device: Device to ensure info for
            timeout: Timeout for waiting for device info response

        Raises:
            DeviceCapabilityError: If device info cannot be obtained
        """
        mac = device.device_info.mac_address

        # Check if already cached
        cached = await self._device_info_cache.get(mac)
        if cached is not None:
            return  # Already cached

        raise DeviceCapabilityError(
            "device_info",
            (
                f"Device info not cached for {mac}. "
                "Ensure device info request has been made."
            ),
        )

    async def _auto_request_device_info(self, device: Device) -> None:
        """
        Auto-request device info and wait for response.

        Called by decorator when device info is not cached.

        Args:
            device: Device to request info for

        Raises:
            RuntimeError: If auto-request callback not set or request fails
        """
        if self._ensure_device_info_callback is None:
            raise RuntimeError(
                "Auto-request not available. "
                "Ensure MQTT client has set the callback."
            )
        success = await self._ensure_device_info_callback(device)
        if not success:
            raise RuntimeError(
                "Failed to obtain device info: "
                "Device did not respond with feature data within timeout"
            )

    def check_support(
        self, feature: str, device_features: DeviceFeature
    ) -> bool:
        """Check if device supports a controllable feature.

        Args:
            feature: Name of the controllable feature
            device_features: Device feature information

        Returns:
            True if feature is supported, False otherwise

        Raises:
            ValueError: If feature is not recognized
        """
        return MqttDeviceCapabilityChecker.supports(feature, device_features)

    def assert_support(
        self, feature: str, device_features: DeviceFeature
    ) -> None:
        """Assert that device supports a controllable feature.

        Args:
            feature: Name of the controllable feature
            device_features: Device feature information

        Raises:
            DeviceCapabilityError: If feature is not supported
            ValueError: If feature is not recognized
        """
        MqttDeviceCapabilityChecker.assert_supported(feature, device_features)

    def _build_command(
        self,
        device_type: int,
        device_id: str,
        command: int,
        additional_value: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Build a Navien MQTT command structure.

        Args:
            device_type: Device type code (e.g., 52 for NWP500)
            device_id: Device MAC address
            command: Command code constant
            additional_value: Additional value from device info
            **kwargs: Additional command-specific fields

        Returns:
            Complete command dictionary ready to publish
        """
        request = {
            "command": command,
            "deviceType": device_type,
            "macAddress": device_id,
            "additionalValue": additional_value,
            **kwargs,
        }

        # Use navilink- prefix for device ID in topics (from reference
        # implementation)
        device_topic = f"navilink-{device_id}"

        return {
            "clientID": self._client_id,
            "sessionID": self._session_id,
            "protocolVersion": 2,
            "request": request,
            "requestTopic": f"cmd/{device_type}/{device_topic}",
            "responseTopic": (
                f"cmd/{device_type}/{device_topic}/{self._client_id}/res"
            ),
        }

    async def _mode_command(
        self,
        device: Device,
        code: int,
        mode: str,
        param: list[Any] | None = None,
    ) -> int:
        """Helper for standard mode-based commands."""
        return await self._send_command(
            device, code, mode=mode, param=param or [], paramStr=""
        )

    def _validate_range(
        self, field: str, val: float, min_val: float, max_val: float
    ) -> None:
        """Helper to validate parameter ranges."""
        if not min_val <= val <= max_val:
            raise RangeValidationError(
                f"{field} must be between {min_val} and {max_val}",
                field,
                val,
                min_val,
                max_val,
            )

    async def _get_device_features(
        self, device: Device
    ) -> DeviceFeature | None:
        """
        Get cached device features, auto-requesting if necessary.

        Internal helper used by decorators and status requests.
        """
        mac = device.device_info.mac_address
        cached_features = await self._device_info_cache.get(mac)

        if cached_features is None:
            _logger.info("Device info not cached, auto-requesting...")
            await self._auto_request_device_info(device)
            cached_features = await self._device_info_cache.get(mac)

        return cached_features

    async def _send_command(
        self,
        device: Device,
        command_code: int,
        topic_suffix: str = "ctrl",
        response_topic_suffix: str | None = None,
        **payload_kwargs: Any,
    ) -> int:
        """
        Internal helper to build and send a device command.

        Args:
            device: Device to send command to
            command_code: Command code to use
            topic_suffix: Suffix for the command topic
            response_topic_suffix: Optional suffix for custom response topic
            **payload_kwargs: Additional fields for the request payload

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type_int = device.device_info.device_type
        device_type_str = str(device_type_int)
        additional_value = device.device_info.additional_value

        topic = MqttTopicBuilder.command_topic(
            device_type_str, device_id, topic_suffix
        )

        command = self._build_command(
            device_type=device_type_int,
            device_id=device_id,
            command=command_code,
            additional_value=additional_value,
            **payload_kwargs,
        )
        command["requestTopic"] = topic

        if response_topic_suffix:
            command["responseTopic"] = MqttTopicBuilder.response_topic(
                device_type_str, self._client_id, response_topic_suffix
            )

        return await self._publish(topic, command)

    async def request_device_status(self, device: Device) -> int:
        """
        Request general device status.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.STATUS_REQUEST,
            topic_suffix="st",
        )

    async def request_device_info(self, device: Device) -> int:
        """
        Request device information (features, firmware, etc.).

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.DEVICE_INFO_REQUEST,
            topic_suffix="st/did",
        )

    @requires_capability("power_use")
    async def set_power(self, device: Device, power_on: bool) -> int:
        """Turn device on or off."""
        return await self._mode_command(
            device,
            CommandCode.POWER_ON if power_on else CommandCode.POWER_OFF,
            "power-on" if power_on else "power-off",
        )

    @requires_capability("dhw_use")
    async def set_dhw_mode(
        self, device: Device, mode_id: int, vacation_days: int | None = None
    ) -> int:
        """Set DHW operation mode."""
        if mode_id == DhwOperationSetting.VACATION.value:
            if vacation_days is None:
                raise ParameterValidationError(
                    "Vacation mode requires vacation_days",
                    parameter="vacation_days",
                )
            self._validate_range("vacation_days", vacation_days, 1, 30)
            param = [mode_id, vacation_days]
        else:
            param = [mode_id]
        return await self._mode_command(
            device, CommandCode.DHW_MODE, "dhw-mode", param
        )

    @requires_capability("anti_legionella_setting_use")
    async def enable_anti_legionella(
        self, device: Device, period_days: int
    ) -> int:
        """Enable Anti-Legionella disinfection."""
        self._validate_range("period_days", period_days, 1, 30)
        return await self._mode_command(
            device, CommandCode.ANTI_LEGIONELLA_ON, "anti-leg-on", [period_days]
        )

    @requires_capability("anti_legionella_setting_use")
    async def disable_anti_legionella(self, device: Device) -> int:
        """Disable the Anti-Legionella disinfection cycle."""
        return await self._mode_command(
            device, CommandCode.ANTI_LEGIONELLA_OFF, "anti-leg-off"
        )

    @requires_capability("dhw_temperature_setting_use")
    async def set_dhw_temperature(
        self, device: Device, temperature_f: float
    ) -> int:
        """Set DHW target temperature (95-150°F)."""
        self._validate_range("temperature_f", temperature_f, 95, 150)
        return await self._mode_command(
            device,
            CommandCode.DHW_TEMPERATURE,
            "dhw-temperature",
            [fahrenheit_to_half_celsius(temperature_f)],
        )

    async def update_reservations(
        self,
        device: Device,
        reservations: Sequence[dict[str, Any]],
        *,
        enabled: bool = True,
    ) -> int:
        """
        Update programmed reservations for temperature/mode changes.

        Args:
            device: Device object
            reservations: List of reservation entries
            enabled: Whether reservations are enabled (default: True)

        Returns:
            Publish packet ID
        """
        # See docs/protocol/mqtt_protocol.rst "Reservation Management" for the
        # command code (16777226) and the reservation object fields
        # (enable, week, hour, min, mode, param).
        reservation_use = 1 if enabled else 2
        reservation_payload = [dict(entry) for entry in reservations]

        return await self._send_command(
            device=device,
            command_code=CommandCode.RESERVATION_MANAGEMENT,
            topic_suffix="ctrl/rsv/rd",
            response_topic_suffix="rsv/rd",
            reservationUse=reservation_use,
            reservation=reservation_payload,
        )

    async def request_reservations(self, device: Device) -> int:
        """
        Request the current reservation program from the device.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.RESERVATION_READ,
            topic_suffix="st/rsv/rd",
            response_topic_suffix="rsv/rd",
        )

    @requires_capability("program_reservation_use")
    async def configure_tou_schedule(
        self,
        device: Device,
        controller_serial_number: str,
        periods: Sequence[dict[str, Any]],
        *,
        enabled: bool = True,
    ) -> int:
        """
        Configure Time-of-Use pricing schedule via MQTT.

        Args:
            device: Device object
            controller_serial_number: Controller serial number
            periods: List of TOU period definitions
            enabled: Whether TOU is enabled (default: True)

        Returns:
            Publish packet ID

        Raises:
            ValueError: If controller_serial_number is empty or periods is empty
        """
        # See docs/protocol/mqtt_protocol.rst "TOU (Time of Use) Settings" for
        # the command code (33554439) and TOU period fields
        # (season, week, startHour, startMinute, endHour, endMinute,
        #  priceMin, priceMax, decimalPoint).
        if not controller_serial_number:
            raise ParameterValidationError(
                "controller_serial_number is required",
                parameter="controller_serial_number",
            )
        if not periods:
            raise ParameterValidationError(
                "At least one TOU period must be provided", parameter="periods"
            )

        reservation_use = 1 if enabled else 2
        reservation_payload = [dict(period) for period in periods]

        return await self._send_command(
            device=device,
            command_code=CommandCode.TOU_RESERVATION,
            topic_suffix="ctrl/tou/rd",
            response_topic_suffix="tou/rd",
            controllerSerialNumber=controller_serial_number,
            reservationUse=reservation_use,
            reservation=reservation_payload,
        )

    async def request_tou_settings(
        self,
        device: Device,
        controller_serial_number: str,
    ) -> int:
        """
        Request current Time-of-Use schedule from the device.

        Args:
            device: Device object
            controller_serial_number: Controller serial number

        Returns:
            Publish packet ID

        Raises:
            ValueError: If controller_serial_number is empty
        """
        if not controller_serial_number:
            raise ParameterValidationError(
                "controller_serial_number is required",
                parameter="controller_serial_number",
            )

        return await self._send_command(
            device=device,
            command_code=CommandCode.TOU_RESERVATION,
            topic_suffix="ctrl/tou/rd",
            response_topic_suffix="tou/rd",
            controllerSerialNumber=controller_serial_number,
        )

    @requires_capability("program_reservation_use")
    async def set_tou_enabled(self, device: Device, enabled: bool) -> int:
        """Toggle Time-of-Use functionality."""
        return await self._mode_command(
            device,
            CommandCode.TOU_ON if enabled else CommandCode.TOU_OFF,
            "tou-on" if enabled else "tou-off",
        )

    async def request_energy_usage(
        self, device: Device, year: int, months: list[int]
    ) -> int:
        """
        Request daily energy usage data for specified month(s).

        This retrieves historical energy usage data showing heat pump and
        electric heating element consumption broken down by day. The response
        includes both energy usage (Wh) and operating time (hours) for each
        component.

        Args:
            device: Device object
            year: Year to query (e.g., 2025)
            months: List of months to query (1-12). Can request multiple months.

        Returns:
            Publish packet ID

        Example::

            # Request energy usage for September 2025
            await controller.request_energy_usage(
                device,
                year=2025,
                months=[9]
            )

            # Request multiple months
            await controller.request_energy_usage(
                device,
                year=2025,
                months=[7, 8, 9]
            )
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.ENERGY_USAGE_QUERY,
            topic_suffix="st/energy-usage-daily-query/rd",
            response_topic_suffix="energy-usage-daily-query/rd",
            month=months,
            year=year,
        )

    async def signal_app_connection(self, device: Device) -> int:
        """
        Signal that the app has connected.
        ...
        """
        device_id = device.device_info.mac_address
        device_type = str(device.device_info.device_type)
        topic = MqttTopicBuilder.event_topic(
            device_type, device_id, "app-connection"
        )
        message = {
            "clientID": self._client_id,
            "timestamp": (datetime.now(UTC).isoformat().replace("+00:00", "Z")),
        }

        return await self._publish(topic, message)

    async def enable_demand_response(self, device: Device) -> int:
        """Enable utility demand response participation."""
        return await self._mode_command(device, CommandCode.DR_ON, "dr-on")

    async def disable_demand_response(self, device: Device) -> int:
        """Disable utility demand response participation."""
        return await self._mode_command(device, CommandCode.DR_OFF, "dr-off")

    async def reset_air_filter(self, device: Device) -> int:
        """Reset air filter maintenance timer."""
        return await self._mode_command(
            device, CommandCode.AIR_FILTER_RESET, "air-filter-reset"
        )

    @requires_capability("holiday_use")
    async def set_vacation_days(self, device: Device, days: int) -> int:
        """Set vacation/away mode duration (1-365 days)."""
        self._validate_range("days", days, 1, 365)
        return await self._mode_command(
            device, CommandCode.GOOUT_DAY, "goout-day", [days]
        )

    @requires_capability("program_reservation_use")
    async def configure_reservation_water_program(self, device: Device) -> int:
        """Enable/configure water program reservation mode."""
        return await self._mode_command(
            device, CommandCode.RESERVATION_WATER_PROGRAM, "reservation-mode"
        )

    @requires_capability("recirc_reservation_use")
    async def configure_recirculation_schedule(
        self,
        device: Device,
        schedule: dict[str, Any],
    ) -> int:
        """
        Configure recirculation pump schedule.
        ...
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.RECIR_RESERVATION,
            schedule=schedule,
        )

    @requires_capability("recirculation_use")
    async def set_recirculation_mode(self, device: Device, mode: int) -> int:
        """Set recirculation pump operation mode (1-4)."""
        self._validate_range("mode", mode, 1, 4)
        return await self._mode_command(
            device, CommandCode.RECIR_MODE, "recirc-mode", [mode]
        )

    @requires_capability("recirculation_use")
    async def trigger_recirculation_hot_button(self, device: Device) -> int:
        """Manually trigger the recirculation pump hot button."""
        return await self._mode_command(
            device, CommandCode.RECIR_HOT_BTN, "recirc-hotbtn", [1]
        )
