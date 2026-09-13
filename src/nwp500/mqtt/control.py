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
- Energy usage queries (daily, monthly, hourly)
- Installer diagnostics and firmware download info queries
- Session end (sent automatically on disconnect)
- App connection signaling
- Demand response control
- Air filter maintenance
- Vacation mode configuration
- Recirculation pump control and scheduling

Every command here has a matching case in the NaviLink app's request
builder (``SendRequestMgppData.java``); a few of those cases (goout-day,
demand response, intelligent mode, water program) have no screen that
calls them. Codes the app's enum declares with no builder case (OTA check,
WiFi reset/reconnect, freeze protection temperature, smart diagnostic,
weekly reservation) have no method.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from ..command_decorators import requires_capability
from ..config import MQTT_PROTOCOL_VERSION
from ..converters import device_bool_from_python
from ..device_capabilities import MqttDeviceCapabilityChecker
from ..device_info_cache import MqttDeviceInfoCache
from ..enums import CommandCode, DhwOperationSetting
from ..exceptions import (
    DeviceCapabilityError,
    ParameterValidationError,
    RangeValidationError,
)
from ..models import (
    Device,
    DeviceFeature,
    OtaCommitPayload,
    RecirculationSchedule,
    preferred_to_half_celsius,
)
from ..topic_builder import MqttTopicBuilder

__author__ = "Emmanuel Levijarvi"

_logger = logging.getLogger(__name__)

#: Year bounds accepted by the energy queries.
MIN_ENERGY_YEAR = 2000
MAX_ENERGY_YEAR = 2099

#: Most recirculation schedule entries the NaviLink app lets a user create
#: (``BottomSheetDialogWeeklyMgpp``).
MAX_RECIRCULATION_ENTRIES = 20


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_recirculation_schedule(schedule: RecirculationSchedule) -> None:
    """Check a recirculation schedule before it is written to the device.

    The model itself accepts any integers so that device read-backs always
    parse; writes are held to the ranges the app's editor can produce.

    Raises:
        ParameterValidationError: On too many entries, a non-integer field,
            or a field outside its range: ``reservationUse`` and ``enable``
            1-2, ``week`` a day bitfield (2-254, bit 0 clear), ``hour``
            0-23, ``min`` 0-59, ``mode`` 1-2, ``param`` -1.
    """

    def fail(message: str, parameter: str, value: Any) -> None:
        raise ParameterValidationError(
            message, parameter=parameter, value=value
        )

    if schedule.reservation_use not in (1, 2):
        fail(
            "reservation_use must be 1 (off) or 2 (on)",
            "reservation_use",
            schedule.reservation_use,
        )
    if len(schedule.reservation) > MAX_RECIRCULATION_ENTRIES:
        fail(
            f"at most {MAX_RECIRCULATION_ENTRIES} entries are allowed",
            "reservation",
            len(schedule.reservation),
        )
    for index, entry in enumerate(schedule.reservation, start=1):
        checks: list[tuple[str, int, bool]] = [
            ("enable", entry.enable, entry.enable in (1, 2)),
            (
                "week",
                entry.week,
                0 < entry.week <= 254 and entry.week % 2 == 0,
            ),
            ("hour", entry.hour, 0 <= entry.hour <= 23),
            ("min", entry.min, 0 <= entry.min <= 59),
            ("mode", entry.mode, entry.mode in (1, 2)),
            ("param", entry.param, entry.param == -1),
        ]
        for name, value, ok in checks:
            if not ok:
                fail(
                    f"entry {index}: {name}={value} is out of range",
                    f"reservation[{index}].{name}",
                    value,
                )


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
    def device_info_cache(self) -> MqttDeviceInfoCache:
        """Get the device info cache."""
        return self._device_info_cache

    @device_info_cache.setter
    def device_info_cache(self, cache: MqttDeviceInfoCache) -> None:
        """Set the device info cache."""
        self._device_info_cache = cache

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

        device_type_str = str(device_type)
        return {
            "clientID": self._client_id,
            "sessionID": self._session_id,
            "protocolVersion": MQTT_PROTOCOL_VERSION,
            "request": request,
            "requestTopic": MqttTopicBuilder.command_topic(
                device_type_str, device_id
            ),
            "responseTopic": MqttTopicBuilder.response_ack_topic(
                device_type_str, device_id, self._client_id
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

    def _validate_int(self, field: str, val: Any) -> None:
        """Reject non-integers (including bool and float) for a field."""
        if not _is_int(val):
            raise ParameterValidationError(
                f"{field} must be an integer", parameter=field, value=val
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
        response_form: str = "client",
        **payload_kwargs: Any,
    ) -> int:
        """
        Internal helper to build and send a device command.

        Args:
            device: Device to send command to
            command_code: Command code to use
            topic_suffix: Suffix for the command topic
            response_topic_suffix: Optional suffix for custom response topic
            response_form: Which response topic shape to request when
                ``response_topic_suffix`` is set: ``"client"`` for
                ``cmd/{dt}/{client_id}/res/{suffix}``, ``"app"`` for the
                NaviLink app's ``cmd/{dt}/{homeSeq}/{userSeq}/{client_id}/
                res/{suffix}`` (the cloud only decodes some replies for this
                shape), ``"device"`` for ``cmd/{dt}/navilink-{mac}/res/
                {suffix}``.
            **payload_kwargs: Additional fields for the request payload

        Returns:
            Publish packet ID
        """
        topic, command = self._prepare_command(
            device,
            command_code,
            topic_suffix=topic_suffix,
            response_topic_suffix=response_topic_suffix,
            response_form=response_form,
            **payload_kwargs,
        )
        return await self._publish(topic, command)

    def _prepare_command(
        self,
        device: Device,
        command_code: int,
        topic_suffix: str = "ctrl",
        response_topic_suffix: str | None = None,
        response_form: str = "client",
        **payload_kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        """Build the publish topic and envelope for a device command.

        Same arguments as :meth:`_send_command`, without publishing.
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
            command["responseTopic"] = self._response_topic(
                device, response_topic_suffix, response_form
            )

        return topic, command

    def _response_topic(
        self, device: Device, suffix: str, form: str = "client"
    ) -> str:
        """Build the response topic for a query in the requested form."""
        device_type_str = str(device.device_info.device_type)
        if form == "app":
            return MqttTopicBuilder.app_response_topic(
                device_type_str,
                device.device_info.home_seq,
                0,
                self._client_id,
                suffix,
            )
        if form == "device":
            return MqttTopicBuilder.device_response_topic(
                device_type_str, device.device_info.mac_address, suffix
            )
        return MqttTopicBuilder.response_topic(
            device_type_str, self._client_id, suffix
        )

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
        self, device: Device, temperature: float
    ) -> int:
        """Set DHW target temperature.

        Temperature is in the user's preferred unit (Celsius or Fahrenheit)
        based on the global unit system context.
        """
        features = await self._get_device_features(device)
        if features is None:
            raise DeviceCapabilityError(
                "dhw_temperature_setting_use",
                (
                    "Device features not available. "
                    "Unable to validate temperature range."
                ),
            )

        self._validate_range(
            "temperature",
            temperature,
            features.dhw_temperature_min,
            features.dhw_temperature_max,
        )
        return await self._mode_command(
            device,
            CommandCode.DHW_TEMPERATURE,
            "dhw-temperature",
            [preferred_to_half_celsius(temperature)],
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
        # See docs/reference/protocol/mqtt_protocol.rst "Reservations" for the
        # command code (16777226) and the reservation object fields
        # (enable, week, hour, min, mode, param).
        reservation_use = device_bool_from_python(enabled)
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
        # See docs/reference/protocol/mqtt_protocol.rst "Time-of-Use" for
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

        reservation_use = device_bool_from_python(enabled)
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
        self._validate_int("year", year)
        self._validate_range("year", year, MIN_ENERGY_YEAR, MAX_ENERGY_YEAR)
        if not months:
            raise ParameterValidationError(
                "At least one month is required", parameter="months"
            )
        for month in months:
            self._validate_int("month", month)
            self._validate_range("month", month, 1, 12)
        return await self._send_command(
            device=device,
            command_code=CommandCode.ENERGY_USAGE_QUERY,
            topic_suffix="st/energy-usage-daily-query/rd",
            response_topic_suffix="energy-usage-daily-query/rd",
            month=months,
            year=year,
        )

    async def request_energy_usage_monthly(
        self, device: Device, years: list[int]
    ) -> int:
        """
        Request per-month energy usage for whole years.

        The NaviLink app sends this for the previous and current year. The
        response has one ``usage`` entry per year (``month`` absent) whose
        ``data`` list holds twelve per-month items, plus lifetime totals.

        Args:
            device: Device object
            years: Years to query (e.g. ``[2025, 2026]``), each between
                2000 and 2099. Duplicates are dropped.

        Returns:
            Publish packet ID

        Raises:
            ParameterValidationError: If ``years`` is empty or holds a
                non-integer.
            RangeValidationError: If a year is out of range.
        """
        if not years:
            raise ParameterValidationError(
                "At least one year is required", parameter="years"
            )
        unique_years = list(dict.fromkeys(years))
        for year in unique_years:
            self._validate_int("year", year)
            self._validate_range("year", year, MIN_ENERGY_YEAR, MAX_ENERGY_YEAR)
        return await self._send_command(
            device=device,
            command_code=CommandCode.ENERGY_USAGE_MONTHLY_QUERY,
            topic_suffix="st/energy-usage-monthly-query/rd",
            response_topic_suffix="energy-usage-monthly-query/rd",
            year=unique_years,
        )

    async def request_energy_usage_hourly(
        self, device: Device, year: int, month: int, days: list[int]
    ) -> int:
        """
        Request per-hour energy usage for specific days.

        Mirrors the NaviLink app's hourly query. The NWP500 firmware tested
        never answered this query (four attempts, both response-topic
        forms), so treat a timeout as the expected outcome on that model.
        Subscribe with ``subscribe_energy_usage_hourly`` to receive a reply
        if the device supports it.

        Args:
            device: Device object
            year: Year to query
            month: Month to query (1-12)
            days: Days of the month to query

        Returns:
            Publish packet ID
        """
        self._validate_int("year", year)
        self._validate_range("year", year, MIN_ENERGY_YEAR, MAX_ENERGY_YEAR)
        self._validate_int("month", month)
        self._validate_range("month", month, 1, 12)
        if not days:
            raise ParameterValidationError(
                "At least one day is required", parameter="days"
            )
        for day in days:
            self._validate_int("day", day)
            self._validate_range("day", day, 1, 31)
        return await self._send_command(
            device=device,
            command_code=CommandCode.ENERGY_USAGE_HOURLY_QUERY,
            topic_suffix="st/energy-usage-hourly-query/rd",
            response_topic_suffix="energy-usage-hourly-query/rd",
            year=year,
            month=month,
            day=list(days),
        )

    async def request_diagnostics(self, device: Device) -> int:
        """
        Request the installer diagnostics counters.

        Sends DIAGNOSTICS_REQUEST (16777228) on ``st/td/rd``. The device
        replies with packed hex; the NaviLink cloud decodes it into JSON on
        ``res/td/rd`` only when the response topic has the app's
        five-segment form, which this method requests. Subscribe with
        ``subscribe_diagnostics`` to receive a
        :class:`~nwp500.models.DeviceDiagnostics`.

        In the app this screen is installer-only, but the gate is in the
        app; a consumer account's unit answers.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.DIAGNOSTICS_REQUEST,
            topic_suffix="st/td/rd",
            response_topic_suffix="td/rd",
            response_form="app",
        )

    async def request_firmware_download_info(self, device: Device) -> int:
        """
        Request the firmware download (OTA) information.

        Sends FIRMWARE_DOWNLOAD_INFO_REQUEST (16777227) on
        ``st/dl-sw-info``. The device answers on its own topic
        ``cmd/{dt}/navilink-{mac}/res/dl-sw-info``; subscribe with
        ``subscribe_firmware_download_info``.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.FIRMWARE_DOWNLOAD_INFO_REQUEST,
            topic_suffix="st/dl-sw-info",
            response_topic_suffix="dl-sw-info",
            response_form="device",
        )

    @requires_capability("recirc_reservation_use")
    async def request_recirculation_schedule(self, device: Device) -> int:
        """
        Request the recirculation pump schedule from the device.

        Sends RECIRC_RESERVATION_READ (16777231) on ``st/recirc-rsv/rd``.
        Subscribe with ``subscribe_recirculation_schedule_response``.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.RECIRC_RESERVATION_READ,
            topic_suffix="st/recirc-rsv/rd",
            response_topic_suffix="recirc-rsv/rd",
        )

    async def end_session(self, device: Device) -> int:
        """
        Tell the device the client is done with it.

        Sends SESSION_END (16777218) on ``st/end``. The NaviLink app sends
        this whenever it leaves a device screen. No reply to it has been
        observed. :meth:`~nwp500.NavienMqttClient.disconnect` sends it
        automatically for every device the client subscribed to, unless
        ``MqttConnectionConfig.send_session_end_on_disconnect`` is off.

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        topic, command = self.build_session_end(device)
        return await self._publish(topic, command)

    def build_session_end(self, device: Device) -> tuple[str, dict[str, Any]]:
        """Build the ``st/end`` topic and envelope without publishing.

        Used by ``NavienMqttClient.disconnect()``, which publishes it
        straight to the connection so it can never be queued for a later
        connect.
        """
        return self._prepare_command(
            device,
            CommandCode.SESSION_END,
            topic_suffix="st/end",
            response_topic_suffix="end",
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

    @requires_capability("dr_setting_use")
    async def enable_demand_response(self, device: Device) -> int:
        """Enable utility demand response participation."""
        return await self._mode_command(device, CommandCode.DR_ON, "dr-on")

    @requires_capability("dr_setting_use")
    async def disable_demand_response(self, device: Device) -> int:
        """Disable utility demand response participation."""
        return await self._mode_command(device, CommandCode.DR_OFF, "dr-off")

    async def reset_air_filter(self, device: Device) -> int:
        """Reset air filter maintenance timer."""
        return await self._mode_command(
            device, CommandCode.AIR_FILTER_RESET, "air-filter-reset"
        )

    async def set_air_filter_life(self, device: Device, hours: int) -> int:
        """Set the air filter service interval.

        Sends AIR_FILTER_LIFE (33554474, mode ``air-filter-life``). The
        NaviLink app offers 0 (alarm off) or 1000-10000 evaporator-fan
        hours in 500-hour steps and sends ``hours / 500`` as the parameter;
        the device reports the interval back as ``air_filter_alarm_period``
        in hours (verified live: sending 3000 reads back as 3000).

        Args:
            device: Device object
            hours: 0 to disable the alarm, or 1000-10000 in steps of 500

        Returns:
            Publish packet ID

        Raises:
            ParameterValidationError: If ``hours`` is not one of the
                app's accepted values.
        """
        if not _is_int(hours) or (
            hours != 0 and not (1000 <= hours <= 10000 and hours % 500 == 0)
        ):
            raise ParameterValidationError(
                "hours must be 0 or between 1000 and 10000 in steps of 500",
                parameter="hours",
                value=hours,
            )
        return await self._mode_command(
            device,
            CommandCode.AIR_FILTER_LIFE,
            "air-filter-life",
            [hours // 500],
        )

    async def reset_condenser_fault(self, device: Device) -> int:
        """Clear a condenser fault.

        Sends COND_FAULT_RESET (33554463, mode ``cond-fault-reset``). The
        NaviLink app exposes this on the status screen to installer
        accounts only; the gate is in the app. A consumer account's unit
        acknowledges the command with a status object (verified live; no
        fault was present, so the clearing effect itself is unverified).

        Args:
            device: Device object

        Returns:
            Publish packet ID
        """
        return await self._mode_command(
            device, CommandCode.COND_FAULT_RESET, "cond-fault-reset"
        )

    @requires_capability("holiday_use")
    async def set_vacation_days(self, device: Device, days: int) -> int:
        """Enter vacation mode for ``days`` days (1-30).

        Sends ``dhw-mode`` with ``[5, days]``, which is what the NaviLink
        app's vacation flow does. To change the day count without changing
        the operation mode, see :meth:`set_vacation_duration`.
        """
        return await self.set_dhw_mode(
            device, DhwOperationSetting.VACATION.value, vacation_days=days
        )

    @requires_capability("holiday_use")
    async def set_vacation_duration(self, device: Device, days: int) -> int:
        """Set the vacation day count without changing the operation mode.

        Sends GOOUT_DAY (33554466, mode ``goout-day``) with ``[days]``.
        The app's request builder has a case for it but no screen calls
        it. Verified live: the device updates ``vacation_day_setting`` and
        leaves ``dhw_operation_setting`` unchanged. Use
        :meth:`set_vacation_days` to actually enter vacation mode.

        Args:
            device: Device object
            days: Vacation duration in days (1-30)

        Returns:
            Publish packet ID
        """
        self._validate_int("days", days)
        self._validate_range("days", days, 1, 30)
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
        schedule: RecirculationSchedule,
    ) -> int:
        """Configure the recirculation pump schedule.

        Sends RECIR_RESERVATION (33554440) on ``ctrl/recirc-rsv/rd`` with
        the same ``reservationUse``/``reservation`` envelope the app uses,
        and asks for the schedule back on ``recirc-rsv/rd`` (see
        ``subscribe_recirculation_schedule_response``). That echo has not
        been observed on a unit with a recirculation pump.

        Args:
            device: Device to configure
            schedule: Recirculation schedule entries

        Returns:
            Publish packet ID

        Raises:
            ParameterValidationError: If the schedule has more than 20
                entries or an entry has an out-of-range field (see
                :func:`validate_recirculation_schedule`).
        """
        validate_recirculation_schedule(schedule)
        # Flat list of raw protocol entries; dumping the model as-is would
        # leak computed display fields to the device.
        return await self._send_command(
            device=device,
            command_code=CommandCode.RECIR_RESERVATION,
            topic_suffix="ctrl/recirc-rsv/rd",
            response_topic_suffix="recirc-rsv/rd",
            reservationUse=schedule.reservation_use,
            reservation=[
                entry.to_protocol_dict() for entry in schedule.reservation
            ],
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

    async def commit_firmware_update(
        self, device: Device, payload: OtaCommitPayload
    ) -> int:
        """Commit a previously downloaded firmware update.

        Sends the OTA_COMMIT command (33554442) with a special
        ``commitOta`` structure (not the standard mode/param format) on
        ``ctrl/commit-ota``, asking for the reply on ``res/commit-ota`` in
        the app's reply-topic form, as the NaviLink app's firmware screen
        does (``setPublishMgppControlOTA``).

        Args:
            device: Device to update
            payload: OTA commit payload specifying which firmware component
                and version to commit.

        Returns:
            Publish packet ID
        """
        return await self._send_command(
            device=device,
            command_code=CommandCode.OTA_COMMIT,
            topic_suffix="ctrl/commit-ota",
            response_topic_suffix="commit-ota",
            response_form="app",
            commitOta=payload.model_dump(by_alias=True),
        )

    async def enable_intelligent_scheduling(self, device: Device) -> int:
        """Enable intelligent/adaptive heating mode.

        Sends the RESERVATION_INTELLIGENT_ON command (33554468). In this
        mode the device learns usage patterns and pre-heats water
        proactively to reduce energy consumption.

        Args:
            device: Device to configure

        Returns:
            Publish packet ID
        """
        return await self._mode_command(
            device, CommandCode.RESERVATION_INTELLIGENT_ON, "intelligent-on"
        )

    async def disable_intelligent_scheduling(self, device: Device) -> int:
        """Disable intelligent/adaptive heating mode.

        Sends the RESERVATION_INTELLIGENT_OFF command (33554467).

        Args:
            device: Device to configure

        Returns:
            Publish packet ID
        """
        return await self._mode_command(
            device, CommandCode.RESERVATION_INTELLIGENT_OFF, "intelligent-off"
        )
