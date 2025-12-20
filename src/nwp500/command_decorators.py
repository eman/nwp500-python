"""Decorators for device command validation and capability checking.

This module provides decorators that automatically validate device capabilities
before command execution, preventing unsupported commands from being sent.
"""

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from .device_capabilities import DeviceCapabilityChecker
from .exceptions import DeviceCapabilityError

__author__ = "Emmanuel Levijarvi"

_logger = logging.getLogger(__name__)

# Type variable for async functions
F = TypeVar("F", bound=Callable[..., Any])


def requires_capability(feature: str) -> Callable[[F], F]:
    """Decorator that validates device capability before executing command.

    This decorator automatically checks if a device supports a specific
    controllable feature before allowing the command to execute. If the
    device doesn't support the feature, a DeviceCapabilityError is raised.

    The decorator expects the command method to:
    1. Have 'self' (controller instance with _device_info_cache)
    2. Have 'device' parameter (Device object with mac_address)

    The device info must be cached (via request_device_info) before calling
    the command, otherwise a DeviceCapabilityError is raised.

    Args:
        feature: Name of the required capability (e.g., "recirculation_mode")

    Returns:
        Decorator function

    Raises:
        DeviceCapabilityError: If device doesn't support the feature
        ValueError: If feature name is not recognized

    Example:
        >>> class MyController:
        ...     def __init__(self, cache):
        ...         self._device_info_cache = cache
        ...
        ...     @requires_capability("recirculation_mode")
        ...     async def set_recirculation_mode(self, device, mode):
        ...         # Command automatically checked before execution
        ...         return await self._publish(...)
    """

    def decorator(func: F) -> F:
        # Determine if this is an async function
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @functools.wraps(func)
            async def async_wrapper(
                self: Any, device: Any, *args: Any, **kwargs: Any
            ) -> Any:
                mac = device.device_info.mac_address
                cached_features = await self._device_info_cache.get(mac)

                # If not cached, auto-request from device
                if cached_features is None:
                    _logger.info(
                        "Device info not cached, auto-requesting from device..."
                    )
                    try:
                        # Call controller method to auto-request
                        await self._auto_request_device_info(device)
                        # Try again after requesting
                        cached_features = await self._device_info_cache.get(mac)
                    except Exception as e:
                        _logger.warning(
                            f"Failed to auto-request device info: {e}"
                        )

                    # Check if we got features after auto-request
                    if cached_features is None:
                        raise DeviceCapabilityError(
                            feature,
                            f"Cannot execute {func.__name__}: "
                            f"Device info could not be obtained.",
                        )

                # Validate capability
                DeviceCapabilityChecker.assert_supported(
                    feature, cached_features
                )

                # Capability validated, execute command
                _logger.debug(
                    f"Device supports {feature}, executing {func.__name__}"
                )
                return await func(self, device, *args, **kwargs)

            return async_wrapper  # type: ignore

        else:

            @functools.wraps(func)
            def sync_wrapper(
                self: Any, device: Any, *args: Any, **kwargs: Any
            ) -> Any:
                # For sync functions, we can't await the cache
                # Log a warning and proceed (backward compatibility)
                _logger.warning(
                    f"{func.__name__} should be async to support "
                    f"capability checking with requires_capability"
                )
                return func(self, device, *args, **kwargs)

            return sync_wrapper  # type: ignore

    return decorator
