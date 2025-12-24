"""Tests for device information caching."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from nwp500.device_info_cache import MqttDeviceInfoCache


@pytest.fixture
def device_feature() -> dict:
    """Create a mock device feature."""
    return {"mac": "AA:BB:CC:DD:EE:FF", "data": "feature_data"}


@pytest.fixture
def cache_with_updates() -> MqttDeviceInfoCache:
    """Create a cache with 30-minute update interval."""
    return MqttDeviceInfoCache(update_interval_minutes=30)


@pytest.fixture
def cache_no_updates() -> MqttDeviceInfoCache:
    """Create a cache with auto-updates disabled."""
    return MqttDeviceInfoCache(update_interval_minutes=0)


class TestMqttDeviceInfoCache:
    """Tests for MqttDeviceInfoCache."""

    @pytest.mark.asyncio
    async def test_cache_get_returns_none_when_empty(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test that get returns None for uncached device."""
        result = await cache_with_updates.get("AA:BB:CC:DD:EE:FF")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_set_and_get(
        self, cache_with_updates: MqttDeviceInfoCache, device_feature: dict
    ) -> None:
        """Test basic set and get operations."""
        mac = "AA:BB:CC:DD:EE:FF"
        await cache_with_updates.set(mac, device_feature)
        result = await cache_with_updates.get(mac)
        assert result is device_feature

    @pytest.mark.asyncio
    async def test_cache_set_overwrites_previous(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test that set overwrites previous cache entry."""
        mac = "AA:BB:CC:DD:EE:FF"
        feature1 = {"data": "first"}
        feature2 = {"data": "second"}

        await cache_with_updates.set(mac, feature1)
        result1 = await cache_with_updates.get(mac)
        assert result1 is feature1

        await cache_with_updates.set(mac, feature2)
        result2 = await cache_with_updates.get(mac)
        assert result2 is feature2

    @pytest.mark.asyncio
    async def test_cache_multiple_devices(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test caching multiple devices."""
        mac1 = "AA:BB:CC:DD:EE:FF"
        mac2 = "11:22:33:44:55:66"

        feature1 = {"data": "device1"}
        feature2 = {"data": "device2"}

        await cache_with_updates.set(mac1, feature1)
        await cache_with_updates.set(mac2, feature2)

        result1 = await cache_with_updates.get(mac1)
        result2 = await cache_with_updates.get(mac2)

        assert result1 is feature1
        assert result2 is feature2

    @pytest.mark.asyncio
    async def test_cache_expiration(self) -> None:
        """Test that cache entries expire."""
        cache_exp = MqttDeviceInfoCache(update_interval_minutes=1)
        mac = "AA:BB:CC:DD:EE:FF"
        feature = {"data": "test"}
        old_time = datetime.now(UTC) - timedelta(minutes=2)
        cache_exp._cache[mac] = (feature, old_time)

        # Get after expiry should return None
        result = await cache_exp.get(mac)
        assert result is None

    @pytest.mark.asyncio
    async def test_is_expired_with_zero_interval(
        self, cache_no_updates: MqttDeviceInfoCache
    ) -> None:
        """Test is_expired returns False when interval is 0 (no updates)."""
        old_time = datetime.now(UTC) - timedelta(hours=1)
        assert not cache_no_updates.is_expired(old_time)

    @pytest.mark.asyncio
    async def test_is_expired_with_fresh_entry(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test is_expired returns False for fresh entries."""
        recent_time = datetime.now(UTC) - timedelta(minutes=5)
        assert not cache_with_updates.is_expired(recent_time)

    @pytest.mark.asyncio
    async def test_is_expired_with_old_entry(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test is_expired returns True for old entries."""
        old_time = datetime.now(UTC) - timedelta(minutes=60)
        assert cache_with_updates.is_expired(old_time)

    @pytest.mark.asyncio
    async def test_cache_invalidate(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test cache invalidation."""
        mac = "AA:BB:CC:DD:EE:FF"
        feature = {"data": "test"}
        await cache_with_updates.set(mac, feature)
        assert await cache_with_updates.get(mac) is not None

        await cache_with_updates.invalidate(mac)
        assert await cache_with_updates.get(mac) is None

    @pytest.mark.asyncio
    async def test_cache_invalidate_nonexistent(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test invalidating nonexistent entry doesn't raise."""
        # Should not raise
        await cache_with_updates.invalidate("AA:BB:CC:DD:EE:FF")

    @pytest.mark.asyncio
    async def test_cache_clear(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test clearing entire cache."""
        mac1 = "AA:BB:CC:DD:EE:FF"
        mac2 = "11:22:33:44:55:66"
        feature = {"data": "test"}

        await cache_with_updates.set(mac1, feature)
        await cache_with_updates.set(mac2, feature)

        assert await cache_with_updates.get(mac1) is not None
        assert await cache_with_updates.get(mac2) is not None

        await cache_with_updates.clear()

        assert await cache_with_updates.get(mac1) is None
        assert await cache_with_updates.get(mac2) is None

    @pytest.mark.asyncio
    async def test_get_all_cached(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test get_all_cached returns all cached devices."""
        mac1 = "AA:BB:CC:DD:EE:FF"
        mac2 = "11:22:33:44:55:66"

        feature1 = {"data": "device1"}
        feature2 = {"data": "device2"}

        await cache_with_updates.set(mac1, feature1)
        await cache_with_updates.set(mac2, feature2)

        all_cached = await cache_with_updates.get_all_cached()

        assert len(all_cached) == 2
        assert all_cached[mac1] is feature1
        assert all_cached[mac2] is feature2

    @pytest.mark.asyncio
    async def test_get_all_cached_excludes_expired(self) -> None:
        """Test get_all_cached excludes expired entries."""
        cache = MqttDeviceInfoCache(update_interval_minutes=1)
        mac1 = "AA:BB:CC:DD:EE:FF"
        mac2 = "11:22:33:44:55:66"
        feature = {"data": "test"}

        # Set one fresh and one expired
        await cache.set(mac1, feature)

        old_time = datetime.now(UTC) - timedelta(minutes=2)
        cache._cache[mac2] = (feature, old_time)

        all_cached = await cache.get_all_cached()

        assert len(all_cached) == 1
        assert mac1 in all_cached
        assert mac2 not in all_cached

    @pytest.mark.asyncio
    async def test_get_cache_info(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test get_cache_info returns correct information."""
        mac = "AA:BB:CC:DD:EE:FF"
        feature = {"data": "test"}
        await cache_with_updates.set(mac, feature)

        info = await cache_with_updates.get_cache_info()

        assert info["device_count"] == 1
        assert info["update_interval_minutes"] == 30
        assert len(info["devices"]) == 1
        assert info["devices"][0]["mac"] == mac
        assert info["devices"][0]["is_expired"] is False
        assert info["devices"][0]["cached_at"] is not None
        assert info["devices"][0]["expires_at"] is not None

    @pytest.mark.asyncio
    async def test_get_cache_info_with_no_updates(
        self, cache_no_updates: MqttDeviceInfoCache
    ) -> None:
        """Test get_cache_info with auto-updates disabled."""
        mac = "AA:BB:CC:DD:EE:FF"
        feature = {"data": "test"}
        await cache_no_updates.set(mac, feature)

        info = await cache_no_updates.get_cache_info()

        assert info["update_interval_minutes"] == 0
        assert info["devices"][0]["expires_at"] is None
        assert info["devices"][0]["is_expired"] is False

    @pytest.mark.asyncio
    async def test_cache_thread_safety(
        self, cache_with_updates: MqttDeviceInfoCache
    ) -> None:
        """Test concurrent cache operations."""
        macs = [f"AA:BB:CC:DD:EE:{i:02X}" for i in range(10)]
        feature = {"data": "test"}

        # Concurrent sets
        await asyncio.gather(
            *[cache_with_updates.set(mac, feature) for mac in macs]
        )

        # Concurrent gets
        results = await asyncio.gather(
            *[cache_with_updates.get(mac) for mac in macs]
        )

        assert all(r is not None for r in results)
        assert len([r for r in results if r is not None]) == 10

    @pytest.mark.asyncio
    async def test_initialization_with_different_intervals(self) -> None:
        """Test cache initialization with different intervals."""
        cache_60 = MqttDeviceInfoCache(update_interval_minutes=60)
        cache_5 = MqttDeviceInfoCache(update_interval_minutes=5)
        cache_0 = MqttDeviceInfoCache(update_interval_minutes=0)

        assert cache_60.update_interval == timedelta(minutes=60)
        assert cache_5.update_interval == timedelta(minutes=5)
        assert cache_0.update_interval == timedelta(minutes=0)
