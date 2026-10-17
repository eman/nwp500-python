"""
Client for interacting with the Navien NWP500 API.

This module provides an async HTTP client for device management and control.
"""

import logging
from datetime import date
from typing import Any, Self

import aiohttp

from .auth import NavienAuthClient
from .config import API_BASE_URL
from .enums import DeviceType
from .exceptions import APIError, AuthenticationError, TokenRefreshError
from .models import (
    AppVersionInfo,
    ConvertedTOUPlan,
    Device,
    DeviceErrorHistoryEntry,
    DisplayPreferences,
    FirmwareDetail,
    FirmwareInfo,
    Location,
    MaintenanceHistoryEntry,
    PushSettings,
    SimpleDevice,
    TOUInfo,
    UserProfile,
    format_maintenance_date,
)
from .unit_system import UnitSystemType

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


__all__ = [
    "NavienAPIClient",
]


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

    def __init__(
        self,
        auth_client: NavienAuthClient,
        base_url: str = API_BASE_URL,
        session: aiohttp.ClientSession | None = None,
        unit_system: UnitSystemType = None,
    ):
        """
        Initialize Navien API client.

        Args:
            auth_client: Authenticated NavienAuthClient instance. Must already
                be authenticated via sign_in().
            base_url: Base URL for the API
            session: Optional aiohttp session (uses auth_client's session if not
                provided)
            unit_system: Preferred unit system:
                - "metric": Celsius, LPM, Liters
                - "us_customary": Fahrenheit, GPM, Gallons

                - None: Auto-detect from device (default)

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
        self._unit_system = unit_system
        # An explicitly provided session always wins; otherwise the auth
        # client's session is resolved per request (never cached) so the
        # API client keeps working if the auth client recreates its
        # session.
        self._session_override = session

        if self._session_override is None and auth_client.session is None:
            raise ValueError(
                "auth_client must have an active session or a session "
                "must be provided"
            )
        self._owned_session = False
        self._owned_auth = False

    @property
    def _session(self) -> aiohttp.ClientSession | None:
        """The session used for requests, resolved dynamically."""
        return self._session_override or self._auth_client.session

    def _require_user_email(self) -> str:
        """The signed-in user's e-mail, or raise if there is none."""
        user_email = self._auth_client.user_email
        if not user_email:
            raise AuthenticationError("Must authenticate first")
        return user_email

    def _user_type(self) -> str:
        """The signed-in user's type, defaulting to owner (``"O"``).

        The sign-in response carries ``userInfo.userType`` (``"O"`` owner,
        ``"M"`` member, or an installer type) and the NaviLink app sends
        that value on the TOU endpoints. It is empty when the auth client
        restored a session without a sign-in response.
        """
        user = self._auth_client.current_user
        user_type = getattr(user, "user_type", None) if user else None
        if isinstance(user_type, str) and user_type:
            return user_type
        return "O"

    async def __aenter__(self) -> Self:
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager."""
        pass

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: dict[str, Any | None] | None = None,
        params: dict[str, Any | None] | None = None,
        retry_on_auth_failure: bool = True,
    ) -> dict[str, Any]:
        """
        Make an authenticated API request.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            json_data: JSON body data
            params: Query parameters
            retry_on_auth_failure: Whether to retry once on 401 errors

        Returns:
            Response data dictionary

        Raises:
            APIError: If API returns an error
            AuthenticationError: If not authenticated
        """
        if not self._auth_client or not self._auth_client.is_authenticated:
            raise AuthenticationError(
                "Must authenticate before making API calls"
            )

        # Ensure token is valid
        await self._auth_client.ensure_valid_token()

        # Get authentication headers
        headers = self._auth_client.get_auth_headers()

        # Make request
        url = f"{self.base_url}{endpoint}"

        _logger.debug(f"{method} {url}")

        # Filter out None values from params/json_data for aiohttp
        # compatibility
        clean_params: dict[str, Any] | None = None
        clean_json_data: dict[str, Any] | None = None

        if params:
            clean_params = {k: v for k, v in params.items() if v is not None}
        if json_data:
            clean_json_data = {
                k: v for k, v in json_data.items() if v is not None
            }

        try:
            _logger.debug(f"Starting {method} request to {url}")
            session = self._session
            if session is None:
                raise APIError(
                    "No active session available. The auth client session "
                    "has been closed."
                )
            async with session.request(
                method,
                url,
                headers=headers,
                json=clean_json_data,
                params=clean_params,
            ) as response:
                _logger.debug(
                    f"Response received from {url}: {response.status}"
                )
                response_data: dict[str, Any] = await response.json()

                # Check for API errors
                code = response_data.get("code", response.status)
                msg = response_data.get("msg", "")

                if code != 200 or not response.ok:
                    # If we get a 401 and haven't retried yet, try refreshing
                    # token
                    if code == 401 and retry_on_auth_failure:
                        _logger.info(
                            "Received 401 Unauthorized. "
                            "Attempting to refresh token..."
                        )
                        try:
                            # Try to refresh the token
                            tokens = self._auth_client.current_tokens
                            if tokens and tokens.refresh_token:
                                await self._auth_client.refresh_token(
                                    tokens.refresh_token
                                )
                                # Retry the request once with new token
                                return await self._make_request(
                                    method,
                                    endpoint,
                                    json_data,
                                    params,
                                    retry_on_auth_failure=False,
                                )
                            else:
                                _logger.error(
                                    "Cannot refresh token: "
                                    "refresh_token not available"
                                )
                        except (
                            TokenRefreshError,
                            AuthenticationError,
                        ) as refresh_error:
                            _logger.error(
                                f"Token refresh failed: {refresh_error}"
                            )
                            # Fall through to raise original error

                    _logger.error(f"API error: {code} - {msg}")
                    raise APIError(
                        f"API request failed: {msg}",
                        code=code,
                        response=response_data,
                    )

                return response_data

        except aiohttp.ClientError as e:
            _logger.error(f"Network error: {e}")
            raise APIError(f"Network error: {e!s}") from e

    # Device Management Endpoints

    async def list_devices(
        self, offset: int = 0, count: int = 20
    ) -> list[Device]:
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
        devices = [Device.model_validate(d) for d in devices_data]

        _logger.info(f"Retrieved {len(devices)} device(s)")
        return devices

    async def get_device_info(
        self, mac_address: str, additional_value: str = ""
    ) -> Device:
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
        device = Device.model_validate(data)

        _logger.info(
            f"Retrieved info for device: {device.device_info.device_name}"
        )
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
        firmwares = [FirmwareInfo.model_validate(f) for f in firmwares_data]

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
            controller_id: Controller serial number from the device feature
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
        tou_info = TOUInfo.model_validate(data)

        _logger.info("Retrieved TOU info for device")
        return tou_info

    async def convert_tou(
        self,
        source_data: list[dict[str, Any]],
        source_type: str = "openei",
        source_version: int = 7,
    ) -> list[ConvertedTOUPlan]:
        """
        Convert OpenEI rate plans to device TOU format.

        Sends raw OpenEI rate plan data to the Navien backend for
        conversion into device-ready TOU schedules with season/week
        bitfields and scaled pricing.

        Args:
            source_data: List of OpenEI rate plan dictionaries
            source_type: Data source type (default: "openei")
            source_version: API version (default: 7)

        Returns:
            List of ConvertedTOUPlan objects with device-ready schedules

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated

        Note:
            ``userType`` is taken from the signed-in user's sign-in
            response (``auth_client.current_user.user_type``) and falls
            back to ``"O"`` (owner) when that is unavailable.
        """
        if not self._auth_client.user_email:
            raise AuthenticationError("Must authenticate first")

        response = await self._make_request(
            "POST",
            "/device/tou/convert",
            json_data={
                "sourceData": source_data,
                "sourceType": source_type,
                "sourceVersion": source_version,
                "userId": self._auth_client.user_email,
                "userType": self._user_type(),
            },
        )

        data = response.get("data", {})
        tou_list = data.get("touInfo", [])
        plans = [ConvertedTOUPlan.model_validate(item) for item in tou_list]

        _logger.info("Converted %d rate plans to device format", len(plans))
        return plans

    async def update_tou(
        self,
        mac_address: str,
        additional_value: str,
        tou_info: dict[str, Any],
        source_data: dict[str, Any],
        zip_code: str,
        register_path: str = "wifi",
        source_type: str = "openei",
        user_type: str = "O",
    ) -> TOUInfo:
        """
        Apply a TOU rate plan to a device.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            tou_info: Converted TOU info dict (name, schedule, utility, zipCode)
            source_data: Original OpenEI rate plan dictionary
            zip_code: Service area zip code
            register_path: Device connection type (default: "wifi")
            source_type: Data source type (default: "openei")
            user_type: User type (default: "O")

        Returns:
            TOUInfo object with the applied configuration

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        if not self._auth_client.user_email:
            raise AuthenticationError("Must authenticate first")

        response = await self._make_request(
            "PUT",
            "/device/tou",
            json_data={
                "additionalValue": additional_value,
                "macAddress": mac_address,
                "registerPath": register_path,
                "sourceData": source_data,
                "sourceType": source_type,
                "touInfo": tou_info,
                "userId": self._auth_client.user_email,
                "userType": user_type,
                "zipCode": zip_code,
            },
        )

        data = response.get("data", {})
        result = TOUInfo.model_validate(data)

        _logger.info("Applied TOU rate plan to device")
        return result

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

    async def delete_tou(
        self,
        mac_address: str,
        additional_value: str,
        register_path: str = "wifi",
        source_type: str = "openei",
        controller_id: str | None = None,
        user_type: str | None = None,
    ) -> bool:
        """
        Remove the TOU rate plan from a device.

        Sends ``DELETE /device/tou``. The NaviLink app serialises the same
        ``TouRequest`` it uses for ``PUT`` and appends it to the URL as a
        query string (a DELETE carries no body), so this method passes the
        fields as query parameters.

        The app identifies the device by ``controllerId`` when the plan was
        registered over Bluetooth (``registerPath == "bt"``) and by
        ``macAddress``/``additionalValue`` otherwise; both are sent here
        when ``controller_id`` is given.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            register_path: How the plan was registered, ``"wifi"`` or
                ``"bt"`` (default: "wifi")
            source_type: Data source type (default: "openei")
            controller_id: Controller ID, required for a ``"bt"`` plan
            user_type: User type; defaults to the signed-in user's type
                (see :meth:`convert_tou`)

        Returns:
            True if successful

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        user_email = self._require_user_email()

        await self._make_request(
            "DELETE",
            "/device/tou",
            params={
                "additionalValue": additional_value,
                "controllerId": controller_id,
                "macAddress": mac_address,
                "registerPath": register_path,
                "sourceType": source_type,
                "userId": user_email,
                "userType": user_type or self._user_type(),
            },
        )

        _logger.info("Removed TOU rate plan from device")
        return True

    async def get_manufacture_id(
        self, mac_address: str, additional_value: str, controller_id: str
    ) -> str:
        """
        Look up the manufacture ID the TOU service knows for a device.

        Sends ``GET /device/tou/manufacture-id``. The NaviLink app treats
        ``"000000000000000"`` as "not available".

        ``controller_id`` is the controller serial number reported in the
        device feature (``DeviceFeature.controller_serial_number``), the
        same value ``get_tou_info()`` takes. Any other value makes the cloud
        answer ``500 INTERNAL_SERVER_ERROR``.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            controller_id: Controller ID

        Returns:
            The manufacture ID string

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        user_email = self._require_user_email()

        response = await self._make_request(
            "GET",
            "/device/tou/manufacture-id",
            params={
                "additionalValue": additional_value,
                "controllerId": controller_id,
                "macAddress": mac_address,
                "userId": user_email,
            },
        )

        data = response.get("data") or {}
        manufacture_id = str(data.get("manufactureId", ""))

        _logger.info("Retrieved manufacture ID for device")
        return manufacture_id

    # Push notification settings

    async def get_push_settings(
        self, mac_address: str, additional_value: str = ""
    ) -> PushSettings:
        """
        Read which push notifications are enabled for a device.

        Sends ``POST /user/get-push-settings``.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier (optional)

        Returns:
            PushSettings with each flag True (on), False (off) or None
            (not reported)

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        user_email = self._require_user_email()

        response = await self._make_request(
            "POST",
            "/user/get-push-settings",
            json_data={
                "userId": user_email,
                "macAddress": mac_address,
                "additionalValue": additional_value,
            },
        )

        settings = PushSettings.model_validate(response.get("data") or {})

        _logger.info("Retrieved push settings for device")
        return settings

    async def set_push_settings(
        self,
        mac_address: str,
        additional_value: str = "",
        *,
        error_alarm: bool | None = None,
        descaling_alarm: bool | None = None,
        etc_alarm: bool | None = None,
    ) -> bool:
        """
        Enable or disable push notifications for a device.

        Sends ``POST /user/set-push-settings``. Flags are encoded 1 (on)
        or 2 (off); a flag left ``None`` is omitted from the request, as
        the NaviLink app does for a member account's descaling flag.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier (optional)
            error_alarm: Notify on device faults
            descaling_alarm: Notify when descaling is due
            etc_alarm: Other notifications

        Returns:
            True if successful

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        user_email = self._require_user_email()

        flags = PushSettings(
            is_error_alarm=error_alarm,
            is_descaling_alarm=descaling_alarm,
            is_etc_alarm=etc_alarm,
        ).to_request_dict()

        await self._make_request(
            "POST",
            "/user/set-push-settings",
            json_data={
                "userId": user_email,
                "macAddress": mac_address,
                "additionalValue": additional_value,
                **flags,
            },
        )

        _logger.info("Updated push settings for device")
        return True

    # Maintenance records

    async def _record_maintenance(
        self,
        kind: str,
        mac_address: str,
        additional_value: str,
        device_type: DeviceType | int,
        maintenance_date: date,
    ) -> bool:
        user_email = self._require_user_email()

        await self._make_request(
            "POST",
            f"/device/{kind}/change-info",
            json_data={
                "userId": user_email,
                "macAddress": mac_address,
                "additionalValue": additional_value,
                "deviceType": int(device_type),
                "maintenanceDate": format_maintenance_date(maintenance_date),
            },
        )

        _logger.info("Recorded %s replacement on %s", kind, maintenance_date)
        return True

    async def record_filter_change(
        self,
        mac_address: str,
        additional_value: str,
        maintenance_date: date,
        device_type: DeviceType | int = DeviceType.NPF700_WIFI,
    ) -> bool:
        """
        Record the date the air filter was replaced.

        Sends ``POST /device/filter/change-info``. The date is formatted
        ``YYYY-M-D`` without zero padding, as the NaviLink app sends it.
        This only updates the cloud's maintenance log; to reset the
        device's own filter timer use
        :meth:`nwp500.NavienMqttClient.reset_air_filter`.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            maintenance_date: Date of the replacement
            device_type: Device type code (default: NWP500)

        Returns:
            True if successful

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        return await self._record_maintenance(
            "filter",
            mac_address,
            additional_value,
            device_type,
            maintenance_date,
        )

    async def record_cip_change(
        self,
        mac_address: str,
        additional_value: str,
        maintenance_date: date,
        device_type: DeviceType | int = DeviceType.NPF700_WIFI,
    ) -> bool:
        """
        Record the date a CIP (clean-in-place / descaling) service was done.

        Sends ``POST /device/cip/change-info``; see
        :meth:`record_filter_change` for the date format.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            maintenance_date: Date of the service
            device_type: Device type code (default: NWP500)

        Returns:
            True if successful

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        return await self._record_maintenance(
            "cip", mac_address, additional_value, device_type, maintenance_date
        )

    async def _get_maintenance_history(
        self,
        kind: str,
        mac_address: str,
        additional_value: str,
        offset: int,
        count: int,
    ) -> list[MaintenanceHistoryEntry]:
        user_email = self._require_user_email()

        response = await self._make_request(
            "POST",
            f"/device/{kind}/history",
            json_data={
                "userId": user_email,
                "offset": offset,
                "count": count,
                "macAddress": mac_address,
                "additionalValue": additional_value,
            },
        )

        entries = [
            MaintenanceHistoryEntry.model_validate(item)
            for item in response.get("data") or []
        ]

        _logger.info("Retrieved %d %s history entries", len(entries), kind)
        return entries

    async def get_filter_history(
        self,
        mac_address: str,
        additional_value: str,
        offset: int = 0,
        count: int = 20,
    ) -> list[MaintenanceHistoryEntry]:
        """
        List recorded air-filter replacements.

        Sends ``POST /device/filter/history``.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            offset: Pagination offset (default: 0)
            count: Number of entries to return (default: 20)

        Returns:
            List of MaintenanceHistoryEntry objects

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        return await self._get_maintenance_history(
            "filter", mac_address, additional_value, offset, count
        )

    async def get_cip_history(
        self,
        mac_address: str,
        additional_value: str,
        offset: int = 0,
        count: int = 20,
    ) -> list[MaintenanceHistoryEntry]:
        """
        List recorded CIP (descaling) services.

        Sends ``POST /device/cip/history``.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            offset: Pagination offset (default: 0)
            count: Number of entries to return (default: 20)

        Returns:
            List of MaintenanceHistoryEntry objects

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        return await self._get_maintenance_history(
            "cip", mac_address, additional_value, offset, count
        )

    # Display preferences

    async def get_display_preferences(
        self,
        mac_address: str,
        additional_value: str,
        model_type_code: int | None = None,
    ) -> list[DisplayPreferences]:
        """
        Read the unit display preferences stored for a device.

        Sends ``GET /device/preferences/format``. The cloud answers with
        a list; the NaviLink app uses the first entry.

        Not accepted for the NWP500: the cloud answers
        ``400 COMMON_BAD_REQUEST`` for device type 52 whatever the
        parameters (checked live). The app only calls it for the
        IoT-module hydro unit (device type 8).

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            model_type_code: Model type code from the device feature
                (omitted when None)

        Returns:
            List of DisplayPreferences objects

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        self._require_user_email()

        response = await self._make_request(
            "GET",
            "/device/preferences/format",
            params={
                "additionalValue": additional_value,
                "macAddress": mac_address,
                "modelTypeCode": model_type_code,
            },
        )

        preferences = [
            DisplayPreferences.model_validate(item)
            for item in response.get("data") or []
        ]

        _logger.info("Retrieved %d display preference(s)", len(preferences))
        return preferences

    async def set_display_preferences(
        self,
        mac_address: str,
        additional_value: str,
        pressure_display_format: str,
        temperature_display_format: str,
        model_type_code: int | None = None,
    ) -> bool:
        """
        Store the unit display preferences for a device.

        Sends ``POST /device/preferences/format``. The NaviLink app writes
        ``"F"``/``"C"`` for temperature and ``"P"`` (psi)/``"M"`` (metric)
        for pressure.

        Not accepted for the NWP500: the cloud answers
        ``400 COMMON_BAD_REQUEST`` for device type 52 whatever the
        parameters (checked live). The app only calls it for the
        IoT-module hydro unit (device type 8).

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            pressure_display_format: ``"P"`` or ``"M"``
            temperature_display_format: ``"F"`` or ``"C"``
            model_type_code: Model type code from the device feature
                (omitted when None)

        Returns:
            True if successful

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        self._require_user_email()

        await self._make_request(
            "POST",
            "/device/preferences/format",
            json_data={
                "additionalValue": additional_value,
                "macAddress": mac_address,
                "modelTypeCode": model_type_code,
                "pressureDisplayFormat": pressure_display_format,
                "temperatureDisplayFormat": temperature_display_format,
            },
        )

        _logger.info("Updated display preferences for device")
        return True

    # Account

    async def get_user_profile(self) -> UserProfile:
        """
        Fetch the signed-in user's profile.

        Sends ``POST /user/info``.

        Returns:
            UserProfile object

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        user_email = self._require_user_email()

        response = await self._make_request(
            "POST", "/user/info", json_data={"userId": user_email}
        )

        profile = UserProfile.model_validate(response.get("data") or {})

        _logger.info("Retrieved profile for %s", profile.user_email)
        return profile

    # Firmware catalogue

    async def get_firmware_detail(
        self, sw_code: int, sw_version: int
    ) -> FirmwareDetail:
        """
        Describe a firmware image by its code and version.

        Sends ``POST /firmware/info``. The NaviLink app passes
        ``cur_sw_code`` with ``downloaded_version`` (when one is pending and
        differs from the current one) or ``cur_version`` from
        :class:`~nwp500.models.FirmwareInfo`.

        Args:
            sw_code: Firmware component code
            sw_version: Firmware version number

        Returns:
            FirmwareDetail object

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        response = await self._make_request(
            "POST",
            "/firmware/info",
            json_data={"swCode": sw_code, "swVersion": sw_version},
        )

        detail = FirmwareDetail.model_validate(response.get("data") or {})

        _logger.info("Retrieved firmware detail for code %s", sw_code)
        return detail

    # Fault history

    async def get_error_history(
        self,
        mac_address: str,
        additional_value: str,
        continuous_key: int | None = None,
        count: int = 20,
        installer_id: str | None = None,
    ) -> list[DeviceErrorHistoryEntry]:
        """
        List the faults the cloud has recorded for a device.

        Sends ``POST /device/error/list``. The NaviLink app calls this from
        its installer-only error list and sends the signed-in user's ID as
        ``installerId``. An owner account is rejected with
        ``404 COMMON_NOT_AUTHORIZED`` (checked live), so this only works
        when signed in as the device's installer. Pass ``continuous_key``
        (the last entry's ``error_occurred_time``) to fetch the next page.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            continuous_key: Pagination cursor (epoch ms of the last entry)
            count: Number of entries to return (default: 20)
            installer_id: Installer ID (default: the signed-in user)

        Returns:
            List of DeviceErrorHistoryEntry objects

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        user_email = self._require_user_email()

        response = await self._make_request(
            "POST",
            "/device/error/list",
            json_data={
                "installerId": installer_id or user_email,
                "macAddress": mac_address,
                "additionalValue": additional_value,
                "continuousKey": continuous_key or None,
                "count": count,
            },
        )

        data = response.get("data") or {}
        entries = [
            DeviceErrorHistoryEntry.model_validate(item)
            for item in data.get("errorInfo") or []
        ]

        _logger.info("Retrieved %d error history entries", len(entries))
        return entries

    # Device registration details

    async def update_device_info(
        self,
        mac_address: str,
        additional_value: str,
        device_name: str,
        device_type: DeviceType | int = DeviceType.NPF700_WIFI,
        install_type: str | None = None,
        location: Location | None = None,
    ) -> bool:
        """
        Rename a device or update its installation details.

        Sends ``POST /device/change-info``. Following the NaviLink app,
        ``installType`` is omitted when empty, the ``location`` object is
        omitted when it has no state, city or address, and within it empty
        strings and zero coordinates are left out.

        Args:
            mac_address: Device MAC address
            additional_value: Additional device identifier
            device_name: New device name
            device_type: Device type code (default: NWP500)
            install_type: Installation type, e.g. ``"R"`` (optional)
            location: New location (optional)

        Returns:
            True if successful

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        user_email = self._require_user_email()

        device_info: dict[str, Any] = {
            "macAddress": mac_address,
            "additionalValue": additional_value,
            "deviceType": int(device_type),
            "deviceName": device_name,
        }
        if install_type:
            device_info["installType"] = install_type

        body: dict[str, Any] = {"userId": user_email, "deviceInfo": device_info}

        if location and (location.state or location.city or location.address):
            # The app drops empty strings and 0.0 coordinates.
            body["location"] = {
                key: value
                for key, value in (
                    ("state", location.state),
                    ("city", location.city),
                    ("address", location.address),
                    ("latitude", location.latitude),
                    ("longitude", location.longitude),
                    ("altitude", location.altitude),
                )
                if value
            }

        await self._make_request("POST", "/device/change-info", json_data=body)

        _logger.info("Updated device info for %s", device_name)
        return True

    async def list_simple_devices(
        self,
        target_user_id: str | None = None,
        offset: int = 0,
        count: int = 20,
    ) -> list[SimpleDevice]:
        """
        List devices in the trimmed ``/device/simple-list`` form.

        The NaviLink app uses this for its product-management list (with
        ``targetUserId`` equal to the signed-in user) and for an installer
        viewing an owner's devices (``targetUserId`` = the owner).

        Args:
            target_user_id: Whose devices to list (default: the signed-in
                user)
            offset: Pagination offset (default: 0)
            count: Number of devices to return (default: 20)

        Returns:
            List of SimpleDevice objects

        Raises:
            APIError: If API request fails
            AuthenticationError: If not authenticated
        """
        user_email = self._require_user_email()

        response = await self._make_request(
            "POST",
            "/device/simple-list",
            json_data={
                "userId": user_email,
                "targetUserId": target_user_id or user_email,
                "offset": offset,
                "count": count,
            },
        )

        devices = [
            SimpleDevice.model_validate(item)
            for item in response.get("data") or []
        ]

        _logger.info("Retrieved %d device(s) (simple list)", len(devices))
        return devices

    # App

    async def get_app_version(self, os: str = "A") -> AppVersionInfo:
        """
        Query the NaviLink app versions the cloud expects.

        Sends ``POST /app/version`` **without** authentication, as the app
        does on its splash screen before sign-in. A 403 whose data carries
        ``serverCheckText`` is a maintenance notice and is returned as an
        :class:`~nwp500.models.AppVersionInfo` with
        ``server_check_text`` set; any other failure raises.

        Args:
            os: Platform code; the app sends ``"A"`` (Android)

        Returns:
            AppVersionInfo object

        Raises:
            APIError: If the request fails for a reason other than a
                maintenance notice
        """
        url = f"{self.base_url}/app/version"
        session = self._session
        if session is None:
            raise APIError(
                "No active session available. The auth client session "
                "has been closed."
            )

        _logger.debug(f"POST {url}")
        try:
            async with session.post(url, json={"os": os}) as response:
                response_data: dict[str, Any] = await response.json()
        except aiohttp.ClientError as e:
            _logger.error(f"Network error: {e}")
            raise APIError(f"Network error: {e!s}") from e

        code = response_data.get("code", response.status)
        data = response_data.get("data") or {}

        if code == 200:
            return AppVersionInfo.model_validate(data)

        if code == 403 and isinstance(data, dict) and "serverCheckText" in data:
            _logger.warning("Navien cloud reports maintenance")
            return AppVersionInfo.model_validate(data)

        msg = response_data.get("msg", "")
        _logger.error(f"API error: {code} - {msg}")
        raise APIError(
            f"API request failed: {msg}", code=code, response=response_data
        )

    # Convenience methods

    async def get_first_device(self) -> Device | None:
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
    def user_email(self) -> str | None:
        """Get current user email."""
        return self._auth_client.user_email
