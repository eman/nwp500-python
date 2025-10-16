"""
API Client for Navien Smart Control REST API.

This module provides a high-level client for interacting with the Navien Smart Control
API, implementing all endpoints from the OpenAPI specification.
"""

import logging
from collections.abc import Iterable
from numbers import Real
from typing import Any, Optional, Union

import aiohttp

from .auth import AuthenticationError, NavienAuthClient
from .config import API_BASE_URL
from .models import (
    Device,
    FirmwareInfo,
    TOUInfo,
)

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


class APIError(Exception):
    """Raised when API returns an error response."""

    def __init__(
        self,
        message: str,
        code: Optional[int] = None,
        response: Optional[dict] = None,
    ):
        self.message = message
        self.code = code
        self.response = response
        super().__init__(self.message)


class NavienAPIClient:
    """
    High-level client for Navien Smart Control REST API.

    This client implements all endpoints from the OpenAPI specification and
    automatically handles authentication, token refresh, and error handling.

    The client requires an authenticated NavienAuthClient to be provided.

    Example:
        >>> async with NavienAuthClient() as auth_client:
        ...     await auth_client.sign_in("user@example.com", "password")
        ...     api_client = NavienAPIClient(auth_client=auth_client)
        ...     devices = await api_client.list_devices()
    """

    _WEEKDAY_ORDER = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]
    _WEEKDAY_NAME_TO_BIT = {name.lower(): 1 << idx for idx, name in enumerate(_WEEKDAY_ORDER)}
    _MONTH_TO_BIT = {month: 1 << (month - 1) for month in range(1, 13)}

    def __init__(
        self,
        auth_client: NavienAuthClient,
        base_url: str = API_BASE_URL,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """
        Initialize Navien API client.

        Args:
            auth_client: Authenticated NavienAuthClient instance. Must already be
                        authenticated via sign_in().
            base_url: Base URL for the API
            session: Optional aiohttp session (uses auth_client's session if not provided)

        Raises:
            ValueError: If auth_client is not authenticated
        """
        if not auth_client.is_authenticated:
            raise ValueError(
                "auth_client must be authenticated before creating API client. "
                "Call auth_client.sign_in() first."
            )

        self.base_url = base_url.rstrip("/")
        self._auth_client = auth_client
        self._session = session or auth_client._session
        self._owned_session = False  # Never own session when auth_client is provided
        self._owned_auth = False  # Never own auth_client

    async def __aenter__(self):
        """Async context manager entry - not required but supported for convenience."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup is handled by auth_client."""
        pass

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Make an authenticated API request.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            json_data: JSON body data
            params: Query parameters

        Returns:
            Response data dictionary

        Raises:
            APIError: If API returns an error
            AuthenticationError: If not authenticated
        """
        if not self._auth_client or not self._auth_client.is_authenticated:
            raise AuthenticationError("Must authenticate before making API calls")

        # Ensure token is valid
        await self._auth_client.ensure_valid_token()

        # Get authentication headers
        headers = self._auth_client.get_auth_headers()

        # Make request
        url = f"{self.base_url}{endpoint}"

        _logger.debug(f"{method} {url}")

        try:
            async with self._session.request(
                method, url, headers=headers, json=json_data, params=params
            ) as response:
                response_data = await response.json()

                # Check for API errors
                code = response_data.get("code", response.status)
                msg = response_data.get("msg", "")

                if code != 200 or not response.ok:
                    _logger.error(f"API error: {code} - {msg}")
                    raise APIError(
                        f"API request failed: {msg}",
                        code=code,
                        response=response_data,
                    )

                return response_data

        except aiohttp.ClientError as e:
            _logger.error(f"Network error: {e}")
            raise APIError(f"Network error: {str(e)}")

    # Device Management Endpoints

    async def list_devices(self, offset: int = 0, count: int = 20) -> list[Device]:
        """
        List all devices associated with the user.

        Args:
            offset: Pagination offset (default: 0)
            count: Number of devices to return (default: 20)

        Returns:
            List of Device objects

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        if not self._auth_client.user_email:
            raise AuthenticationError("Must authenticate first")

        response = await self._make_request(
            "POST",
            "/device/list",
            json_data={
                "offset": offset,
                "count": count,
                "userId": self._auth_client.user_email,
            },
        )

        devices_data = response.get("data", [])
        devices = [Device.from_dict(d) for d in devices_data]

        _logger.info(f"Retrieved {len(devices)} device(s)")
        return devices

    async def get_device_info(self, mac_address: str, additional_value: str = "") -> Device:
        """
        Get detailed information about a specific device.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier (optional)

        Returns:
            Device object with detailed information

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        if not self._auth_client.user_email:
            raise AuthenticationError("Must authenticate first")

        response = await self._make_request(
            "POST",
            "/device/info",
            json_data={
                "macAddress": mac_address,
                "additionalValue": additional_value,
                "userId": self._auth_client.user_email,
            },
        )

        data = response.get("data", {})
        device = Device.from_dict(data)

        _logger.info(f"Retrieved info for device: {device.device_info.device_name}")
        return device

    async def get_firmware_info(
        self, mac_address: str, additional_value: str = ""
    ) -> list[FirmwareInfo]:
        """
        Get firmware information for a specific device.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier (optional)

        Returns:
            List of FirmwareInfo objects

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        if not self._auth_client.user_email:
            raise AuthenticationError("Must authenticate first")

        response = await self._make_request(
            "POST",
            "/device/firmware/info",
            json_data={
                "macAddress": mac_address,
                "additionalValue": additional_value,
                "userId": self._auth_client.user_email,
            },
        )

        data = response.get("data", {})
        firmwares_data = data.get("firmwares", [])
        firmwares = [FirmwareInfo.from_dict(f) for f in firmwares_data]

        _logger.info(f"Retrieved firmware info: {len(firmwares)} firmware(s)")
        return firmwares

    async def get_tou_info(
        self,
        mac_address: str,
        additional_value: str,
        controller_id: str,
        user_type: str = "O",
    ) -> TOUInfo:
        """
        Get Time of Use (TOU) information for a device.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            controller_id: Controller ID
            user_type: User type (default: "O")

        Returns:
            TOUInfo object

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        if not self._auth_client.user_email:
            raise AuthenticationError("Must authenticate first")

        response = await self._make_request(
            "GET",
            "/device/tou",
            params={
                "additionalValue": additional_value,
                "controllerId": controller_id,
                "macAddress": mac_address,
                "userId": self._auth_client.user_email,
                "userType": user_type,
            },
        )

        data = response.get("data", {})
        tou_info = TOUInfo.from_dict(data)

        _logger.info(f"Retrieved TOU info for {mac_address}")
        return tou_info

    async def update_push_token(
        self,
        push_token: str,
        model_name: str = "Python Client",
        app_version: str = "1.0.0",
        os: str = "Python",
        os_version: str = "3.8+",
    ) -> bool:
        """
        Update push notification token.

        Args:
            push_token: Push notification token
            model_name: Device model name (default: "Python Client")
            app_version: Application version (default: "1.0.0")
            os: Operating system (default: "Python")
            os_version: OS version (default: "3.8+")

        Returns:
            True if successful

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        if not self._auth_client.user_email:
            raise AuthenticationError("Must authenticate first")

        await self._make_request(
            "POST",
            "/app/update-push-token",
            json_data={
                "modelName": model_name,
                "appVersion": app_version,
                "os": os,
                "osVersion": os_version,
                "userId": self._auth_client.user_email,
                "pushToken": push_token,
            },
        )

        _logger.info("Push token updated successfully")
        return True

    # Convenience methods

    async def get_first_device(self) -> Optional[Device]:
        """
        Get the first device associated with the user.

        Returns:
            First Device object or None if no devices
        """
        devices = await self.list_devices(count=1)
        return devices[0] if devices else None

    @property
    def is_authenticated(self) -> bool:
        """Check if client is authenticated."""
        return self._auth_client.is_authenticated

    @property
    def user_email(self) -> Optional[str]:
        """Get current user email."""
        return self._auth_client.user_email

    # Helper utilities -------------------------------------------------

    @staticmethod
    def encode_week_bitfield(days: Iterable[Union[str, int]]) -> int:
        """Convert a collection of day names or indices into the reservation bitfield."""
        bitfield = 0
        for value in days:
            if isinstance(value, str):
                key = value.strip().lower()
                if key not in NavienAPIClient._WEEKDAY_NAME_TO_BIT:
                    raise ValueError(f"Unknown weekday: {value}")
                bitfield |= NavienAPIClient._WEEKDAY_NAME_TO_BIT[key]
            elif isinstance(value, int):
                if 0 <= value <= 6:
                    bitfield |= 1 << value
                elif 1 <= value <= 7:
                    bitfield |= 1 << (value - 1)
                else:
                    raise ValueError("Day index must be between 0-6 or 1-7")
            else:
                raise TypeError("Weekday values must be strings or integers")
        return bitfield

    @staticmethod
    def decode_week_bitfield(bitfield: int) -> list[str]:
        """Decode a reservation bitfield back into a list of weekday names."""
        days: list[str] = []
        for idx, name in enumerate(NavienAPIClient._WEEKDAY_ORDER):
            if bitfield & (1 << idx):
                days.append(name)
        return days

    @staticmethod
    def encode_season_bitfield(months: Iterable[int]) -> int:
        """Encode a collection of month numbers (1-12) into a TOU season bitfield."""
        bitfield = 0
        for month in months:
            if month not in NavienAPIClient._MONTH_TO_BIT:
                raise ValueError("Month values must be in the range 1-12")
            bitfield |= NavienAPIClient._MONTH_TO_BIT[month]
        return bitfield

    @staticmethod
    def decode_season_bitfield(bitfield: int) -> list[int]:
        """Decode a TOU season bitfield into the corresponding month numbers."""
        months: list[int] = []
        for month, mask in NavienAPIClient._MONTH_TO_BIT.items():
            if bitfield & mask:
                months.append(month)
        return months

    @staticmethod
    def encode_price(value: Real, decimal_point: int) -> int:
        """Encode a price into the integer representation expected by the device."""
        if decimal_point < 0:
            raise ValueError("decimal_point must be >= 0")
        scale = 10**decimal_point
        return int(round(float(value) * scale))

    @staticmethod
    def decode_price(value: int, decimal_point: int) -> float:
        """Decode an integer price value using the provided decimal point."""
        if decimal_point < 0:
            raise ValueError("decimal_point must be >= 0")
        scale = 10**decimal_point
        return value / scale if scale else float(value)

    @staticmethod
    def build_reservation_entry(
        *,
        enabled: Union[bool, int],
        days: Iterable[Union[str, int]],
        hour: int,
        minute: int,
        mode_id: int,
        param: int,
    ) -> dict[str, int]:
        """Build a reservation payload entry matching the documented MQTT format."""
        if not 0 <= hour <= 23:
            raise ValueError("hour must be between 0 and 23")
        if not 0 <= minute <= 59:
            raise ValueError("minute must be between 0 and 59")
        if mode_id < 0:
            raise ValueError("mode_id must be non-negative")

        if isinstance(enabled, bool):
            enable_flag = 1 if enabled else 2
        elif enabled in (1, 2):
            enable_flag = int(enabled)
        else:
            raise ValueError("enabled must be True/False or 1/2")

        week_bitfield = NavienAPIClient.encode_week_bitfield(days)

        return {
            "enable": enable_flag,
            "week": week_bitfield,
            "hour": hour,
            "min": minute,
            "mode": mode_id,
            "param": param,
        }

    @staticmethod
    def build_tou_period(
        *,
        season_months: Iterable[int],
        week_days: Iterable[Union[str, int]],
        start_hour: int,
        start_minute: int,
        end_hour: int,
        end_minute: int,
        price_min: Union[int, Real],
        price_max: Union[int, Real],
        decimal_point: int,
    ) -> dict[str, int]:
        """Build a TOU period entry consistent with MQTT command requirements."""
        for label, value, upper in (
            ("start_hour", start_hour, 23),
            ("end_hour", end_hour, 23),
        ):
            if not 0 <= value <= upper:
                raise ValueError(f"{label} must be between 0 and {upper}")
        for label, value in (("start_minute", start_minute), ("end_minute", end_minute)):
            if not 0 <= value <= 59:
                raise ValueError(f"{label} must be between 0 and 59")

        week_bitfield = NavienAPIClient.encode_week_bitfield(week_days)
        season_bitfield = NavienAPIClient.encode_season_bitfield(season_months)

        if isinstance(price_min, Real) and not isinstance(price_min, int):
            encoded_min = NavienAPIClient.encode_price(price_min, decimal_point)
        else:
            encoded_min = int(price_min)

        if isinstance(price_max, Real) and not isinstance(price_max, int):
            encoded_max = NavienAPIClient.encode_price(price_max, decimal_point)
        else:
            encoded_max = int(price_max)

        return {
            "season": season_bitfield,
            "week": week_bitfield,
            "startHour": start_hour,
            "startMinute": start_minute,
            "endHour": end_hour,
            "endMinute": end_minute,
            "priceMin": encoded_min,
            "priceMax": encoded_max,
            "decimalPoint": decimal_point,
        }
