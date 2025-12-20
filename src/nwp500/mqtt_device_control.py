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
from datetime import datetime
from typing import Any

from .command_decorators import requires_capability
from .device_capabilities import DeviceCapabilityChecker
from .device_info_cache import DeviceInfoCache
from .enums import CommandCode, DhwOperationSetting
from .exceptions import (
    DeviceCapabilityError,
    ParameterValidationError,
    RangeValidationError,
)
from nwp500.topic_builder import MqttTopicBuilder
from .models import Device, DeviceFeature, fahrenheit_to_half_celsius

__author__ = "Emmanuel Levijarvi"

_logger = logging.getLogger(__name__)


class MqttDeviceController:
    """
    Manages device control commands for Navien devices.

    Handles all device control operations including status requests,
    mode changes, temperature control, scheduling, and energy queries.

    This controller integrates with DeviceCapabilityChecker to validate
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
        device_info_cache: DeviceInfoCache | None = None,
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
        self._device_info_cache = device_info_cache or DeviceInfoCache(
            update_interval_minutes=30
        )
        # Callback for auto-requesting device info when needed
        self._ensure_device_info_callback: (
            Callable[[Device], Awaitable[None]] | None
        ) = None

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
            RuntimeError: If auto-request callback not set
        """
        if self._ensure_device_info_callback is None:
            raise RuntimeError(
                "Auto-request not available. "
                "Ensure MQTT client has set the callback."
            )
        await self._ensure_device_info_callback(device)

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
        return DeviceCapabilityChecker.supports(feature, device_features)

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
        DeviceCapabilityChecker.assert_supported(feature, device_features)

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

    async def _get_device_features(self, device: Device) -> Any | None:
        """
        Get cached device features, auto-requesting if necessary.

        Internal helper used by decorators and status requests.
        """
        mac = device.device_info.mac_address
        cached_features = await self._device_info_cache.get(mac)

        if cached_features is None:
            _logger.info(
                f"Device info for {mac} not cached, auto-requesting..."
            )
            try:
                await self._auto_request_device_info(device)
                cached_features = await self._device_info_cache.get(mac)
            except Exception as e:
                _logger.warning(f"Failed to auto-request device info: {e}")

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
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value

        topic = MqttTopicBuilder.command_topic(
            device_type, device_id, topic_suffix
        )

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=command_code,
            additional_value=additional_value,
            **payload_kwargs,
        )
        command["requestTopic"] = topic

        if response_topic_suffix:
            command["responseTopic"] = MqttTopicBuilder.response_topic(
                device_type, self._client_id, response_topic_suffix
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
        """
        Turn device on or off.

        Args:
            device: Device object
            power_on: True to turn on, False to turn off

        Returns:
            Publish packet ID
        """
        mode = "power-on" if power_on else "power-off"
        command_code = (
            CommandCode.POWER_ON if power_on else CommandCode.POWER_OFF
        )

        return await self._send_command(
            device=device,
            command_code=command_code,
            mode=mode,
            param=[],
            paramStr="",
        )

    @requires_capability("dhw_use")
    async def set_dhw_mode(
        self,
        device: Device,
        mode_id: int,
        vacation_days: int | None = None,
    ) -> int:
        """
        Set DHW (Domestic Hot Water) operation mode.

        Args:
            device: Device object
            mode_id: Mode ID (1=Heat Pump Only, 2=Electric Only, 3=Energy Saver,
                4=High Demand, 5=Vacation)
            vacation_days: Number of vacation days (required for Vacation mode)

        Returns:
            Publish packet ID

        Note:
            Valid selectable mode IDs are 1, 2, 3, 4, and 5 (vacation).
            Additional modes may appear in status responses:
            - 0: Standby (device in idle state)
            - 6: Power Off (device is powered off)

            Mode descriptions:
            - 1: Heat Pump Only (most efficient, slowest recovery)
            - 2: Electric Only (least efficient, fastest recovery)
            - 3: Energy Saver (balanced, good default)
            - 4: High Demand (maximum heating capacity)
            - 5: Vacation Mode (requires vacation_days parameter)
        """
        if mode_id == DhwOperationSetting.VACATION.value:
            if vacation_days is None:
                raise ParameterValidationError(
                    "Vacation mode requires vacation_days (1-30)",
                    parameter="vacation_days",
                )
            if not 1 <= vacation_days <= 30:
                raise RangeValidationError(
                    "vacation_days must be between 1 and 30",
                    field="vacation_days",
                    value=vacation_days,
                    min_value=1,
                    max_value=30,
                )
            param = [mode_id, vacation_days]
        else:
            if vacation_days is not None:
                raise ParameterValidationError(
                    "vacation_days is only valid for vacation mode (mode 5)",
                    parameter="vacation_days",
                )
            param = [mode_id]

        return await self._send_command(
            device=device,
            command_code=CommandCode.DHW_MODE,
            mode="dhw-mode",
            param=param,
            paramStr="",
        )

    async def enable_anti_legionella(
        self, device: Device, period_days: int
    ) -> int:
        """
        Enable Anti-Legionella disinfection with a 1-30 day cycle.
        ...
        """
        if not 1 <= period_days <= 30:
            raise RangeValidationError(
                "period_days must be between 1 and 30",
                field="period_days",
                value=period_days,
                min_value=1,
                max_value=30,
            )

        return await self._send_command(
            device=device,
            command_code=CommandCode.ANTI_LEGIONELLA_ON,
            mode="anti-leg-on",
            param=[period_days],
            paramStr="",
        )

    async def disable_anti_legionella(self, device: Device) -> int:
        """
        Disable the Anti-Legionella disinfection cycle.
        ...
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.ANTI_LEGIONELLA_OFF,
            mode="anti-leg-off",
            param=[],
            paramStr="",
        )

    @requires_capability("dhw_temperature_setting_use")
    async def set_dhw_temperature(
        self, device: Device, temperature_f: float
    ) -> int:
        """
        Set DHW target temperature.

        Args:
            device: Device object
            temperature_f: Target temperature in Fahrenheit (95-150°F).
                Automatically converted to the device's internal format.

        Returns:
            Publish packet ID

        Raises:
            RangeValidationError: If temperature is outside 95-150°F range

        Example:
            await controller.set_dhw_temperature(device, 140.0)
        """
        if not 95 <= temperature_f <= 150:
            raise RangeValidationError(
                "temperature_f must be between 95 and 150°F",
                field="temperature_f",
                value=temperature_f,
                min_value=95,
                max_value=150,
            )

        param = fahrenheit_to_half_celsius(temperature_f)

        return await self._send_command(
            device=device,
            command_code=CommandCode.DHW_TEMPERATURE,
            mode="dhw-temperature",
            param=[param],
            paramStr="",
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
        # See docs/MQTT_MESSAGES.rst "Reservation Management" for the
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
        # See docs/MQTT_MESSAGES.rst "TOU (Time of Use) Settings" for
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
        """
        Quickly toggle Time-of-Use functionality without modifying the schedule.

        Args:
            device: Device object
            enabled: True to enable TOU, False to disable

        Returns:
            Publish packet ID
        """
        mode = "tou-on" if enabled else "tou-off"
        command_code = CommandCode.TOU_ON if enabled else CommandCode.TOU_OFF

        return await self._send_command(
            device=device,
            command_code=command_code,
            mode=mode,
            param=[],
            paramStr="",
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
        device_type = device.device_info.device_type
        topic = MqttTopicBuilder.event_topic(
            device_type, device_id, "app-connection"
        )
        message = {
            "clientID": self._client_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        return await self._publish(topic, message)

    async def enable_demand_response(self, device: Device) -> int:
        """
        Enable utility demand response participation.
        ...
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.DR_ON,
            mode="dr-on",
            param=[],
            paramStr="",
        )

    async def disable_demand_response(self, device: Device) -> int:
        """
        Disable utility demand response participation.
        ...
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.DR_OFF,
            mode="dr-off",
            param=[],
            paramStr="",
        )

    async def reset_air_filter(self, device: Device) -> int:
        """
        Reset air filter maintenance timer.
        ...
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.AIR_FILTER_RESET,
            mode="air-filter-reset",
            param=[],
            paramStr="",
        )

    @requires_capability("holiday_use")
    async def set_vacation_days(self, device: Device, days: int) -> int:
        """
        Set vacation/away mode duration in days.
        ...
        """
        if days <= 0 or days > 365:
            raise RangeValidationError(
                "days must be between 1 and 365",
                field="days",
                value=days,
                min_value=1,
                max_value=365,
            )

        return await self._send_command(
            device=device,
            command_code=CommandCode.GOOUT_DAY,
            mode="goout-day",
            param=[days],
            paramStr="",
        )

    @requires_capability("program_reservation_use")
    async def configure_reservation_water_program(self, device: Device) -> int:
        """
        Enable/configure water program reservation mode.
        ...
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.RESERVATION_WATER_PROGRAM,
            mode="reservation-mode",
            param=[],
            paramStr="",
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
        """
        Set recirculation pump operation mode.
        ...
        """
        if not 1 <= mode <= 4:
            raise RangeValidationError(
                "mode must be between 1 and 4",
                field="mode",
                value=mode,
                min_value=1,
                max_value=4,
            )

        return await self._send_command(
            device=device,
            command_code=CommandCode.RECIR_MODE,
            mode="recirc-mode",
            param=[mode],
            paramStr="",
        )

    @requires_capability("recirculation_use")
    async def trigger_recirculation_hot_button(self, device: Device) -> int:
        """
        Manually trigger the recirculation pump hot button.
        ...
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.RECIR_HOT_BTN,
            mode="recirc-hotbtn",
            param=[1],
            paramStr="",
        )
