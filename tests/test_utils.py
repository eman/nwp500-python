"""Tests for utils module."""

import asyncio
import logging

import pytest

from nwp500.utils import log_performance


@pytest.mark.asyncio
async def test_log_performance_basic():
    """Test basic functionality of log_performance decorator."""

    @log_performance
    async def sample_async_func():
        await asyncio.sleep(0.1)
        return "result"

    result = await sample_async_func()
    assert result == "result"


@pytest.mark.asyncio
async def test_log_performance_with_args():
    """Test log_performance with function arguments."""

    @log_performance
    async def func_with_args(x: int, y: str, z: bool = False):
        await asyncio.sleep(0.05)
        return f"{x}-{y}-{z}"

    result = await func_with_args(42, "test", z=True)
    assert result == "42-test-True"


@pytest.mark.asyncio
async def test_log_performance_with_exception():
    """Test log_performance still logs when function raises exception."""

    @log_performance
    async def failing_func():
        await asyncio.sleep(0.05)
        raise ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        await failing_func()


@pytest.mark.asyncio
async def test_log_performance_logs_at_debug_level(caplog):
    """Test that execution time is logged at DEBUG level."""
    caplog.set_level(logging.DEBUG)

    @log_performance
    async def timed_func():
        await asyncio.sleep(0.05)
        return "done"

    result = await timed_func()
    assert result == "done"

    # Check that log message was generated
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.DEBUG
    assert "timed_func completed in" in record.message
    assert "s" in record.message  # Has time unit


@pytest.mark.asyncio
async def test_log_performance_no_log_when_debug_disabled(caplog):
    """Test that no logging occurs when DEBUG level is not enabled."""
    caplog.set_level(logging.INFO)  # Above DEBUG

    @log_performance
    async def quiet_func():
        await asyncio.sleep(0.05)
        return "result"

    result = await quiet_func()
    assert result == "result"

    # Should not log anything at INFO level
    assert len(caplog.records) == 0


@pytest.mark.asyncio
async def test_log_performance_timing_accuracy(caplog):
    """Test that logged timing is reasonably accurate."""
    caplog.set_level(logging.DEBUG)

    sleep_duration = 0.1

    @log_performance
    async def sleep_func():
        await asyncio.sleep(sleep_duration)

    await sleep_func()

    # Extract timing from log message
    record = caplog.records[0]
    # Message format: "sleep_func completed in 0.123s"
    parts = record.message.split()
    time_str = parts[-1].rstrip("s")
    logged_time = float(time_str)

    # Allow 50ms tolerance for system overhead
    assert abs(logged_time - sleep_duration) < 0.05


def test_log_performance_rejects_sync_functions():
    """Test that decorator raises TypeError for non-async functions."""
    with pytest.raises(
        TypeError, match="can only be applied to async functions"
    ):

        @log_performance
        def sync_func():
            return "sync"


@pytest.mark.asyncio
async def test_log_performance_preserves_metadata():
    """Test that decorator preserves function metadata."""

    @log_performance
    async def documented_func(x: int) -> str:
        """This is a test function.

        Args:
            x: An integer parameter

        Returns:
            A string
        """
        return str(x)

    # Check that metadata is preserved
    assert documented_func.__name__ == "documented_func"
    assert "This is a test function" in documented_func.__doc__
    assert documented_func.__module__ == __name__


@pytest.mark.asyncio
async def test_log_performance_exception_still_logs(caplog):
    """Test that timing is logged even when function raises exception."""
    caplog.set_level(logging.DEBUG)

    @log_performance
    async def error_func():
        await asyncio.sleep(0.05)
        raise RuntimeError("oops")

    with pytest.raises(RuntimeError):
        await error_func()

    # Should still log timing
    assert len(caplog.records) == 1
    assert "error_func completed in" in caplog.records[0].message


@pytest.mark.asyncio
async def test_log_performance_multiple_calls(caplog):
    """Test decorator works correctly with multiple calls."""
    caplog.set_level(logging.DEBUG)

    @log_performance
    async def multi_call_func(value: int):
        await asyncio.sleep(0.01)
        return value * 2

    results = []
    for i in range(3):
        result = await multi_call_func(i)
        results.append(result)

    assert results == [0, 2, 4]
    assert len(caplog.records) == 3
    for record in caplog.records:
        assert "multi_call_func completed in" in record.message


@pytest.mark.asyncio
async def test_log_performance_concurrent_calls(caplog):
    """Test decorator works correctly with concurrent calls."""
    caplog.set_level(logging.DEBUG)

    @log_performance
    async def concurrent_func(delay: float):
        await asyncio.sleep(delay)
        return delay

    # Run multiple calls concurrently
    results = await asyncio.gather(
        concurrent_func(0.05), concurrent_func(0.03), concurrent_func(0.07)
    )

    assert len(results) == 3
    assert len(caplog.records) == 3
    # All should have logged
    for record in caplog.records:
        assert "concurrent_func completed in" in record.message
