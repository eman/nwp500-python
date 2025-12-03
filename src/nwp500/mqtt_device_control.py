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
"""

import logging
from collections.abc import Awaitable, Sequence
from datetime import datetime
from typing import Any, Callable, Optional

from .constants import CommandCode
from .exceptions import ParameterValidationError, RangeValidationError
from .models import Device, DhwOperationSetting, fahrenheit_to_half_celsius

__author__ = "Emmanuel Levijarvi"

_logger = logging.getLogger(__name__)


class MqttDeviceController:
    """
    Manages device control commands for Navien devices.

    Handles all device control operations including status requests,
    mode changes, temperature control, scheduling, and energy queries.
    """

    def __init__(
        self,
        client_id: str,
        session_id: str,
        publish_func: Callable[..., Awaitable[int]],
    ) -> None:
        """
        Initialize device controller.

        Args:
            client_id: MQTT client ID
            session_id: Session ID for commands
            publish_func: Function to publish MQTT messages (async callable)
        """
        self._client_id = client_id
        self._session_id = session_id
        self._publish: Callable[..., Awaitable[int]] = publish_func

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

    async def request_device_status(self, device: Device) -> int:
        """
        Request general device status.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value

        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/st"
        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.STATUS_REQUEST,
            additional_value=additional_value,
        )
        command["requestTopic"] = topic

        return await self._publish(topic, command)

    async def request_device_info(self, device: Device) -> int:
        """
        Request device information (features, firmware, etc.).

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value

        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/st/did"
        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.DEVICE_INFO_REQUEST,
            additional_value=additional_value,
        )
        command["requestTopic"] = topic

        return await self._publish(topic, command)

    async def set_power(self, device: Device, power_on: bool) -> int:
        """
        Turn device on or off.

        Args:
            device: Device object
            power_on: True to turn on, False to turn off

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"
        mode = "power-on" if power_on else "power-off"
        command_code = (
            CommandCode.POWER_ON if power_on else CommandCode.POWER_OFF
        )

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=command_code,
            additional_value=additional_value,
            mode=mode,
            param=[],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self._publish(topic, command)

    async def set_dhw_mode(
        self,
        device: Device,
        mode_id: int,
        vacation_days: Optional[int] = None,
    ) -> int:
        """
        Set DHW (Domestic Hot Water) operation mode.

        Args:
            device: Device object
            mode_id: Mode ID (1=Heat Pump Only, 2=Electric Only, 3=Energy Saver,
                4=High Demand, 5=Vacation)
            vacation_days: Number of vacation days (required when mode_id == 5)

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

        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.DHW_MODE,
            additional_value=additional_value,
            mode="dhw-mode",
            param=param,
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self._publish(topic, command)

    async def enable_anti_legionella(
        self, device: Device, period_days: int
    ) -> int:
        """
        Enable Anti-Legionella disinfection with a 1-30 day cycle.

        This command has been confirmed through HAR analysis of the official
        Navien app.
        When sent, the device responds with antiLegionellaUse=2 (enabled) and
        antiLegionellaPeriod set to the specified value.

        See docs/MQTT_MESSAGES.rst "Anti-Legionella Control" for the
        authoritative
        command code (33554472) and expected payload format:
        {"mode": "anti-leg-on", "param": [<period_days>], "paramStr": ""}

        Args:
            device: The device to control
            period_days: Days between disinfection cycles (1-30)

        Returns:
            The message ID of the published command

        Raises:
            ValueError: If period_days is not in the valid range [1, 30]
        """
        if not 1 <= period_days <= 30:
            raise RangeValidationError(
                "period_days must be between 1 and 30",
                field="period_days",
                value=period_days,
                min_value=1,
                max_value=30,
            )

        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.ANTI_LEGIONELLA_ENABLE,
            additional_value=additional_value,
            mode="anti-leg-on",
            param=[period_days],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self._publish(topic, command)

    async def disable_anti_legionella(self, device: Device) -> int:
        """
        Disable the Anti-Legionella disinfection cycle.

        This command has been confirmed through HAR analysis of the official
        Navien app.
        When sent, the device responds with antiLegionellaUse=1 (disabled) while
        antiLegionellaPeriod retains its previous value.

        The correct command code is 33554471 (not 33554473 as previously
        assumed).
        See docs/MQTT_MESSAGES.rst "Anti-Legionella Control" section for
        details.

        Args:
            device: The device to control

        Returns:
            The message ID of the published command
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.ANTI_LEGIONELLA_DISABLE,
            additional_value=additional_value,
            mode="anti-leg-off",
            param=[],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self._publish(topic, command)

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

        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.DHW_TEMPERATURE,
            additional_value=additional_value,
            mode="dhw-temperature",
            param=[param],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self._publish(topic, command)

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
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl/rsv/rd"

        reservation_use = 1 if enabled else 2
        reservation_payload = [dict(entry) for entry in reservations]

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.RESERVATION_MANAGEMENT,
            additional_value=additional_value,
            reservationUse=reservation_use,
            reservation=reservation_payload,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = (
            f"cmd/{device_type}/{self._client_id}/res/rsv/rd"
        )

        return await self._publish(topic, command)

    async def request_reservations(self, device: Device) -> int:
        """
        Request the current reservation program from the device.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/st/rsv/rd"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.RESERVATION_READ,
            additional_value=additional_value,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = (
            f"cmd/{device_type}/{self._client_id}/res/rsv/rd"
        )

        return await self._publish(topic, command)

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

        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl/tou/rd"

        reservation_use = 1 if enabled else 2
        reservation_payload = [dict(period) for period in periods]

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.TOU_SETTINGS,
            additional_value=additional_value,
            controllerSerialNumber=controller_serial_number,
            reservationUse=reservation_use,
            reservation=reservation_payload,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = (
            f"cmd/{device_type}/{self._client_id}/res/tou/rd"
        )

        return await self._publish(topic, command)

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

        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl/tou/rd"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.TOU_SETTINGS,
            additional_value=additional_value,
            controllerSerialNumber=controller_serial_number,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = (
            f"cmd/{device_type}/{self._client_id}/res/tou/rd"
        )

        return await self._publish(topic, command)

    async def set_tou_enabled(self, device: Device, enabled: bool) -> int:
        """
        Quickly toggle Time-of-Use functionality without modifying the schedule.

        Args:
            device: Device object
            enabled: True to enable TOU, False to disable

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value
        device_topic = f"navilink-{device_id}"
        topic = f"cmd/{device_type}/{device_topic}/ctrl"

        command_code = (
            CommandCode.TOU_ENABLE if enabled else CommandCode.TOU_DISABLE
        )
        mode = "tou-on" if enabled else "tou-off"

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=command_code,
            additional_value=additional_value,
            mode=mode,
            param=[],
            paramStr="",
        )
        command["requestTopic"] = topic

        return await self._publish(topic, command)

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
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        additional_value = device.device_info.additional_value

        device_topic = f"navilink-{device_id}"
        topic = (
            f"cmd/{device_type}/{device_topic}/st/energy-usage-daily-query/rd"
        )

        command = self._build_command(
            device_type=device_type,
            device_id=device_id,
            command=CommandCode.ENERGY_USAGE_QUERY,
            additional_value=additional_value,
            month=months,
            year=year,
        )
        command["requestTopic"] = topic
        command["responseTopic"] = (
            f"cmd/{device_type}/{self._client_id}/res/energy-usage-daily-query/rd"
        )

        return await self._publish(topic, command)

    async def signal_app_connection(self, device: Device) -> int:
        """
        Signal that the app has connected.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        device_id = device.device_info.mac_address
        device_type = device.device_info.device_type
        device_topic = f"navilink-{device_id}"
        topic = f"evt/{device_type}/{device_topic}/app-connection"
        message = {
            "clientID": self._client_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        return await self._publish(topic, message)
