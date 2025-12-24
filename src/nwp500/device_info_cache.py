"""Device information caching with periodic updates.

This module manages caching of device information (features, capabilities)
with automatic periodic updates to keep data synchronized with the device.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from .models import DeviceFeature

__author__ = "Emmanuel Levijarvi"

_logger = logging.getLogger(__name__)


class CachedDeviceInfo(TypedDict):
    """Cached device information metadata."""

    mac: str
    cached_at: str
    expires_at: str | None
    is_expired: bool


class CacheInfoResult(TypedDict):
    """Result of get_cache_info() call."""

    device_count: int
    update_interval_minutes: float
    devices: list[CachedDeviceInfo]


class MqttDeviceInfoCache:
    """Manages caching of device information with periodic updates.

    This cache stores device features (capabilities, firmware info, etc.)
    and automatically refreshes them at regular intervals to keep data
    synchronized with the actual device state.

    The cache is keyed by device MAC address, allowing support for
    multiple devices connected to the same MQTT client.
    """

    def __init__(self, update_interval_minutes: int = 30) -> None:
        """Initialize the device info cache.

        Args:
            update_interval_minutes: How often to refresh device info
                (default: 30 minutes). Set to 0 to disable auto-updates.
        """
        self.update_interval = timedelta(minutes=update_interval_minutes)
        # Cache: {mac_address: (feature, timestamp)}
        self._cache: dict[str, tuple[DeviceFeature, datetime]] = {}
        self._lock = asyncio.Lock()

    async def get(self, device_mac: str) -> "DeviceFeature | None":
        """Get cached device features if available and not expired.

        Args:
            device_mac: Device MAC address

        Returns:
            Cached DeviceFeature if available, None otherwise
        """
        async with self._lock:
            if device_mac not in self._cache:
                return None

            features, timestamp = self._cache[device_mac]

            # Check if cache is still fresh
            if self.is_expired(timestamp):
                del self._cache[device_mac]
                return None

            return features

    async def set(self, device_mac: str, features: "DeviceFeature") -> None:
        """Cache device features with current timestamp.

        Args:
            device_mac: Device MAC address
            features: Device feature information to cache
        """
        async with self._lock:
            self._cache[device_mac] = (features, datetime.now(UTC))
            _logger.debug("Device info cached")

    async def invalidate(self, device_mac: str) -> None:
        """Invalidate cache entry for a device.

        Forces a refresh on next request.

        Args:
            device_mac: Device MAC address
        """
        async with self._lock:
            if device_mac in self._cache:
                del self._cache[device_mac]
                from .mqtt.utils import redact_mac

                redacted = redact_mac(device_mac)
                _logger.debug(f"Invalidated cache for {redacted}")

    async def clear(self) -> None:
        """Clear all cached device information."""
        async with self._lock:
            self._cache.clear()
            _logger.debug("Cleared device info cache")

    def is_expired(self, timestamp: datetime) -> bool:
        """Check if a cache entry is expired.

        Args:
            timestamp: When the cache entry was created

        Returns:
            True if expired, False if still fresh
        """
        if self.update_interval.total_seconds() == 0:
            # Auto-updates disabled
            return False

        age = datetime.now(UTC) - timestamp
        return age > self.update_interval

    async def get_all_cached(self) -> dict[str, "DeviceFeature"]:
        """Get all currently cached device features.

        Returns:
            Dictionary mapping MAC addresses to DeviceFeature objects
        """
        async with self._lock:
            # Filter out expired entries
            return {
                mac: features
                for mac, (features, timestamp) in self._cache.items()
                if not self.is_expired(timestamp)
            }

    async def get_cache_info(
        self,
    ) -> CacheInfoResult:
        """Get cache statistics and metadata.

        Returns:
            Dictionary with cache info including:
            - device_count: Number of cached devices
            - update_interval_minutes: Cache update interval in minutes
            - devices: List of device cache metadata
        """
        async with self._lock:
            devices: list[CachedDeviceInfo] = []
            for mac, (_features, timestamp) in self._cache.items():
                expires_at = (
                    timestamp + self.update_interval
                    if self.update_interval.total_seconds() > 0
                    else None
                )
                device_info: CachedDeviceInfo = {
                    "mac": mac,
                    "cached_at": timestamp.isoformat(),
                    "expires_at": expires_at.isoformat()
                    if expires_at
                    else None,
                    "is_expired": self.is_expired(timestamp),
                }
                devices.append(device_info)

            result: CacheInfoResult = {
                "device_count": len(devices),
                "update_interval_minutes": (
                    self.update_interval.total_seconds() / 60
                    if self.update_interval.total_seconds() > 0
                    else 0
                ),
                "devices": devices,
            }
            return result
