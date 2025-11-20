"""
Client for interacting with the Navien NWP500 API.

This module provides an async HTTP client for device management and control.
"""

import logging
from typing import Any, Optional

import aiohttp

from .auth import NavienAuthClient
from .config import API_BASE_URL
from .exceptions import APIError, AuthenticationError, TokenRefreshError
from .models import Device, FirmwareInfo, TOUInfo

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
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """
        Initialize Navien API client.

        Args:
            auth_client: Authenticated NavienAuthClient instance. Must already
            be
                        authenticated via sign_in().
            base_url: Base URL for the API
            session: Optional aiohttp session (uses auth_client's session if not
            provided)

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
        self._auth_client = auth_client
        _session = session or auth_client._session
        if _session is None:
            raise ValueError("auth_client must have an active session")
        self._session = _session
        self._owned_session = (
            False  # Never own session when auth_client is provided
        )
        self._owned_auth = False  # Never own auth_client

    async def __aenter__(self) -> "NavienAPIClient":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager."""
        pass

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
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

        try:
            async with self._session.request(
                method, url, headers=headers, json=json_data, params=params
            ) as response:
                response_data: dict[str, Any] = await response.json()

                # Check for API errors
                code = response_data.get("code", response.status)
                msg = response_data.get("msg", "")

                if code != 200 or not response.ok:
                    # If we get a 401 and haven't retried yet, try refreshing
                    # token
                    if code == 401 and retry_on_auth_failure:
                        _logger.warning(
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
            raise APIError(f"Network error: {str(e)}") from e

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
        tou_info = TOUInfo.model_validate(data)

        _logger.info("Retrieved TOU info for device")
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
