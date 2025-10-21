"""
General utility functions for the nwp500 library.

This module provides utilities that are used across multiple components,
including performance monitoring decorators and helper functions.
"""

import asyncio
import functools
import logging
import time
from typing import Any, Callable, TypeVar, cast

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def log_performance(func: F) -> F:
    """Log execution time for async functions at DEBUG level.

    This decorator measures the execution time of async functions and logs
    the duration when DEBUG logging is enabled. It's useful for identifying
    performance bottlenecks and monitoring critical paths.

    Args:
        func: Async function to wrap

    Returns:
        Wrapped function that logs its execution time

    Example::

        @log_performance
        async def fetch_device_status(device_id: str) -> dict:
            # ... expensive operation ...
            return status

        # When called, logs: "fetch_device_status completed in 0.234s"

    Note:
        - Only logs when DEBUG level is enabled to minimize overhead in
          production
        - Uses time.perf_counter() for high-resolution timing
        - Preserves function metadata (name, docstring, etc.)
    """
    if not asyncio.iscoroutinefunction(func):
        raise TypeError(
            "@log_performance can only be applied to async "
            f"functions, got {func}"
        )

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not _logger.isEnabledFor(logging.DEBUG):
            # Skip timing if DEBUG logging is not enabled
            return await func(*args, **kwargs)

        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            elapsed = time.perf_counter() - start_time
            _logger.debug(f"{func.__name__} completed in {elapsed:.3f}s")

    return cast(F, wrapper)
