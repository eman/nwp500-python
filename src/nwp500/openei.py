"""
OpenEI Utility Rates API client.

Provides async access to the OpenEI Utility Rates API for querying
electricity rate plans by zip code. Used to populate Time-of-Use (TOU)
schedules on Navien devices.

API key can be obtained for free at https://openei.org/services/api/signup/
"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

OPENEI_API_URL = "https://api.openei.org/utility_rates"
OPENEI_API_VERSION = 7

__all__ = [
    "OpenEIClient",
]


class OpenEIClient:
    """Async client for the OpenEI Utility Rates API.

    Queries residential electricity rate plans by zip code.
    Requires an API key from https://openei.org/services/api/signup/

    The API key is resolved in this order:
    1. ``api_key`` constructor parameter
    2. ``OPENEI_API_KEY`` environment variable

    Example:
        >>> async with OpenEIClient() as client:
        ...     plans = await client.list_rate_plans("94903")
        ...     for plan in plans:
        ...         print(f"{plan['utility']}: {plan['name']}")
    """

    def __init__(
        self,
        api_key: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENEI_API_KEY")
        self._session = session
        self._owned_session = False

    def _ensure_api_key(self) -> str:
        if not self._api_key:
            raise ValueError(
                "OpenEI API key required. Set OPENEI_API_KEY environment "
                "variable or pass api_key to OpenEIClient(). "
                "Get a free key at https://openei.org/services/api/signup/"
            )
        return self._api_key

    async def __aenter__(self) -> OpenEIClient:
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._owned_session = True
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._owned_session and self._session:
            await self._session.close()
            self._session = None
            self._owned_session = False

    async def fetch_rates(
        self,
        zip_code: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch all residential rate plans for a zip code.

        Args:
            zip_code: US zip code to search
            limit: Maximum number of results (default: 100)

        Returns:
            List of raw OpenEI rate plan dictionaries

        Raises:
            ValueError: If no API key is configured
            aiohttp.ClientError: If the API request fails
        """
        api_key = self._ensure_api_key()

        params: dict[str, str | int] = {
            "version": OPENEI_API_VERSION,
            "format": "json",
            "api_key": api_key,
            "detail": "full",
            "address": zip_code,
            "sector": "Residential",
            "orderby": "startdate",
            "direction": "desc",
            "limit": limit,
        }

        if self._session is None:
            raise RuntimeError(
                "Session not initialized. Use 'async with OpenEIClient()' "
                "or call __aenter__() first."
            )

        _logger.debug("Fetching OpenEI rates for zip code %s", zip_code)
        async with self._session.get(OPENEI_API_URL, params=params) as resp:
            resp.raise_for_status()
            data: dict[str, Any] = await resp.json()
            items: list[dict[str, Any]] = data.get("items", [])
            _logger.info(
                "Retrieved %d rate plans for zip %s",
                len(items),
                zip_code,
            )
            return items

    async def list_utilities(self, zip_code: str) -> list[str]:
        """List unique utility providers for a zip code.

        Args:
            zip_code: US zip code to search

        Returns:
            Sorted list of unique utility names
        """
        items = await self.fetch_rates(zip_code)
        utilities = sorted(
            {item.get("utility", "") for item in items if item.get("utility")}
        )
        return utilities

    async def list_rate_plans(
        self,
        zip_code: str,
        *,
        utility: str | None = None,
    ) -> list[dict[str, Any]]:
        """List rate plans, optionally filtered by utility.

        Args:
            zip_code: US zip code to search
            utility: Filter by utility name (case-insensitive substring match)

        Returns:
            List of rate plan dictionaries with keys: name, utility, label,
            eiaid, approved, has_tou_schedule
        """
        items = await self.fetch_rates(zip_code)
        plans: list[dict[str, Any]] = []

        for item in items:
            if (
                utility
                and utility.lower() not in item.get("utility", "").lower()
            ):
                continue
            plans.append(
                {
                    "name": item.get("name", ""),
                    "utility": item.get("utility", ""),
                    "label": item.get("label", ""),
                    "eiaid": item.get("eiaid"),
                    "approved": item.get("approved", False),
                    "has_tou_schedule": "energyweekdayschedule" in item,
                    "description": item.get("description", ""),
                }
            )
        return plans

    async def get_rate_plan(
        self,
        zip_code: str,
        plan_name: str,
        *,
        utility: str | None = None,
    ) -> dict[str, Any] | None:
        """Get a specific rate plan by name.

        Returns the first matching plan. Use ``utility`` to disambiguate
        if multiple utilities serve the same zip code.

        Args:
            zip_code: US zip code to search
            plan_name: Rate plan name (case-insensitive substring match)
            utility: Filter by utility name (case-insensitive substring match)

        Returns:
            Full rate plan dictionary or None if not found
        """
        items = await self.fetch_rates(zip_code)
        for item in items:
            if (
                utility
                and utility.lower() not in item.get("utility", "").lower()
            ):
                continue
            if plan_name.lower() in item.get("name", "").lower():
                return item
        return None
