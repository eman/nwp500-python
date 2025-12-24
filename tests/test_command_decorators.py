"""Tests for command decorators."""

from typing import Any
from unittest.mock import Mock

import pytest

from nwp500.command_decorators import requires_capability
from nwp500.device_info_cache import MqttDeviceInfoCache
from nwp500.exceptions import DeviceCapabilityError


class BaseMockController:
    """Base class for mock controllers to avoid duplication."""

    def __init__(self, cache: MqttDeviceInfoCache) -> None:
        self._device_info_cache = cache

    async def _get_device_features(self, device: Any) -> Any:
        """Get device features, helper for the decorator."""
        features = await self._device_info_cache.get(
            device.device_info.mac_address
        )
        if features is None and hasattr(self, "_auto_request_device_info"):
            try:
                await self._auto_request_device_info(device)
                features = await self._device_info_cache.get(
                    device.device_info.mac_address
                )
            except Exception:
                pass
        return features


class TestRequiresCapabilityDecorator:
    """Tests for requires_capability decorator."""

    @pytest.mark.asyncio
    async def test_decorator_allows_supported_capability(self) -> None:
        """Test decorator allows execution when capability is supported."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        # Create mock features that supports power_use
        mock_features = Mock()
        mock_features.power_use = True

        await cache.set(mock_device.device_info.mac_address, mock_features)

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)
                self.command_called = False

            @requires_capability("power_use")
            async def set_power(self, device: Mock, power_on: bool) -> None:
                self.command_called = True

        controller = MockController()
        await controller.set_power(mock_device, True)
        assert controller.command_called

    @pytest.mark.asyncio
    async def test_decorator_blocks_unsupported_capability(self) -> None:
        """Test decorator blocks execution when capability is not supported."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        # Create mock features that does not support power_use
        mock_features = Mock()
        mock_features.power_use = False

        await cache.set(mock_device.device_info.mac_address, mock_features)

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)
                self.command_called = False

            @requires_capability("power_use")
            async def set_power(self, device: Mock, power_on: bool) -> None:
                self.command_called = True

        controller = MockController()
        with pytest.raises(DeviceCapabilityError):
            await controller.set_power(mock_device, True)
        assert not controller.command_called

    @pytest.mark.asyncio
    async def test_decorator_auto_requests_device_info(self) -> None:
        """Test decorator auto-requests device info when not cached."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        # Create mock features that support power_use
        mock_features = Mock()
        mock_features.power_use = True

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)
                self.command_called = False
                self.auto_request_called = False

            @requires_capability("power_use")
            async def set_power(self, device: Mock, power_on: bool) -> None:
                self.command_called = True

            async def _auto_request_device_info(self, device: Mock) -> None:
                self.auto_request_called = True
                await self._device_info_cache.set(
                    device.device_info.mac_address, mock_features
                )

        controller = MockController()
        await controller.set_power(mock_device, True)
        assert controller.auto_request_called
        assert controller.command_called

    @pytest.mark.asyncio
    async def test_decorator_fails_when_info_not_available(self) -> None:
        """Test decorator fails when device info cannot be obtained."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)

            @requires_capability("power_use")
            async def set_power(self, device: Mock, power_on: bool) -> None:
                pass

            async def _auto_request_device_info(self, device: Mock) -> None:
                # Simulate failure to get device info
                pass

        controller = MockController()
        with pytest.raises(DeviceCapabilityError):
            await controller.set_power(mock_device, True)

    @pytest.mark.asyncio
    async def test_decorator_with_multiple_arguments(self) -> None:
        """Test decorator works with multiple function arguments."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        mock_features = Mock()
        mock_features.power_use = True

        await cache.set(mock_device.device_info.mac_address, mock_features)

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)
                self.received_args = None

            @requires_capability("power_use")
            async def command(
                self,
                device: Mock,
                arg1: str,
                arg2: int,
                kwarg1: str = "default",
            ) -> None:
                self.received_args = (arg1, arg2, kwarg1)

        controller = MockController()
        await controller.command(mock_device, "value1", 42, kwarg1="custom")
        assert controller.received_args == ("value1", 42, "custom")

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_name(self) -> None:
        """Test decorator preserves function name."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        mock_features = Mock()
        mock_features.power_use = True

        await cache.set(mock_device.device_info.mac_address, mock_features)

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)

            @requires_capability("power_use")
            async def my_special_command(self, device: Mock) -> None:
                pass

        controller = MockController()
        assert controller.my_special_command.__name__ == "my_special_command"

    @pytest.mark.asyncio
    async def test_decorator_with_different_capabilities(self) -> None:
        """Test decorator works with different capability requirements."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        # Device supports only power_use
        mock_features = Mock()
        mock_features.power_use = True
        mock_features.dhw_use = False

        await cache.set(mock_device.device_info.mac_address, mock_features)

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)
                self.power_called = False
                self.dhw_called = False

            @requires_capability("power_use")
            async def set_power(self, device: Mock) -> None:
                self.power_called = True

            @requires_capability("dhw_use")
            async def set_dhw(self, device: Mock) -> None:
                self.dhw_called = True

        controller = MockController()

        # power_use should succeed
        await controller.set_power(mock_device)
        assert controller.power_called

        # dhw_use should fail
        with pytest.raises(DeviceCapabilityError):
            await controller.set_dhw(mock_device)
        assert not controller.dhw_called

    @pytest.mark.asyncio
    async def test_decorator_with_sync_function_logs_warning(self) -> None:
        """Test decorator with sync function raises TypeError."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)
                self.command_called = False

            @requires_capability("power_use")
            def set_power_sync(self, device: Mock, power_on: bool) -> None:
                self.command_called = True

        controller = MockController()

        with pytest.raises(
            TypeError,
            match="must be async to use @requires_capability decorator",
        ):
            controller.set_power_sync(mock_device, True)

    @pytest.mark.asyncio
    async def test_decorator_handles_auto_request_exception(self) -> None:
        """Test decorator handles exception during auto-request."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)

            @requires_capability("power_use")
            async def set_power(self, device: Mock, power_on: bool) -> None:
                pass

            async def _auto_request_device_info(self, device: Mock) -> None:
                # Simulate exception during auto-request
                raise RuntimeError("Connection failed")

        controller = MockController()

        with pytest.raises(DeviceCapabilityError):
            await controller.set_power(mock_device, True)

    @pytest.mark.asyncio
    async def test_decorator_returns_function_result(self) -> None:
        """Test decorator properly returns function result."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        mock_features = Mock()
        mock_features.power_use = True

        await cache.set(mock_device.device_info.mac_address, mock_features)

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)

            @requires_capability("power_use")
            async def get_status(self, device: Mock) -> str:
                return "status_ok"

        controller = MockController()
        result = await controller.get_status(mock_device)
        assert result == "status_ok"

    @pytest.mark.asyncio
    async def test_decorator_with_exception_in_decorated_function(self) -> None:
        """Test decorator propagates exceptions from decorated function."""
        cache = MqttDeviceInfoCache()
        mock_device = Mock()
        mock_device.device_info.mac_address = "AA:BB:CC:DD:EE:FF"

        mock_features = Mock()
        mock_features.power_use = True

        await cache.set(mock_device.device_info.mac_address, mock_features)

        class MockController(BaseMockController):
            def __init__(self) -> None:
                super().__init__(cache)

            @requires_capability("power_use")
            async def failing_command(self, device: Mock) -> None:
                raise RuntimeError("Command failed")

        controller = MockController()

        with pytest.raises(RuntimeError, match="Command failed"):
            await controller.failing_command(mock_device)
