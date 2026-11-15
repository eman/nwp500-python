"""The CLI's reply helpers always remove the callback they register."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from nwp500.cli.handlers import _wait_for_response
except ImportError:
    pytest.skip("CLI dependencies not installed", allow_module_level=True)


def _pair(reply: Any = None) -> tuple[AsyncMock, AsyncMock, list[Any]]:
    """subscribe/unsubscribe mocks; subscribe answers with ``reply``."""
    registered: list[Any] = []

    async def subscribe(device: Any, callback: Any) -> None:
        registered.append(callback)
        if reply is not None:
            callback(reply)

    return AsyncMock(side_effect=subscribe), AsyncMock(), registered


def _assert_removed(
    unsubscribe: AsyncMock, device: Any, registered: list[Any]
) -> None:
    unsubscribe.assert_awaited_once_with(device, registered[0])


@pytest.mark.asyncio
async def test_success_removes_the_callback() -> None:
    device = MagicMock()
    subscribe, unsubscribe, registered = _pair(reply="answer")
    result = await _wait_for_response(
        subscribe, unsubscribe, device, AsyncMock(), timeout=1
    )
    assert result == "answer"
    _assert_removed(unsubscribe, device, registered)


@pytest.mark.asyncio
async def test_timeout_removes_the_callback() -> None:
    device = MagicMock()
    subscribe, unsubscribe, registered = _pair()
    with pytest.raises(TimeoutError):
        await _wait_for_response(
            subscribe, unsubscribe, device, AsyncMock(), timeout=0.01
        )
    _assert_removed(unsubscribe, device, registered)


@pytest.mark.asyncio
async def test_action_failure_removes_the_callback() -> None:
    device = MagicMock()
    subscribe, unsubscribe, registered = _pair()
    with pytest.raises(RuntimeError, match="publish failed"):
        await _wait_for_response(
            subscribe,
            unsubscribe,
            device,
            AsyncMock(side_effect=RuntimeError("publish failed")),
            timeout=1,
        )
    _assert_removed(unsubscribe, device, registered)


@pytest.mark.asyncio
async def test_cancel_removes_the_callback() -> None:
    device = MagicMock()
    subscribe, unsubscribe, registered = _pair()
    task = asyncio.create_task(
        _wait_for_response(
            subscribe, unsubscribe, device, AsyncMock(), timeout=10
        )
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _assert_removed(unsubscribe, device, registered)


@pytest.mark.asyncio
async def test_failed_unsubscribe_keeps_the_reply() -> None:
    device = MagicMock()
    subscribe, _, registered = _pair(reply="answer")
    unsubscribe = AsyncMock(side_effect=TimeoutError())
    result = await _wait_for_response(
        subscribe, unsubscribe, device, AsyncMock(), timeout=1
    )
    assert result == "answer"
    _assert_removed(unsubscribe, device, registered)


@pytest.mark.asyncio
async def test_failed_unsubscribe_keeps_the_request_error() -> None:
    device = MagicMock()
    subscribe, _, _ = _pair()
    unsubscribe = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(RuntimeError, match="publish failed"):
        await _wait_for_response(
            subscribe,
            unsubscribe,
            device,
            AsyncMock(side_effect=RuntimeError("publish failed")),
            timeout=1,
        )


@pytest.mark.asyncio
async def test_cancel_during_subscribe_removes_the_callback() -> None:
    device = MagicMock()
    registered: list[Any] = []
    started = asyncio.Event()

    async def subscribe(device: Any, callback: Any) -> None:
        # The manager registers the handler before awaiting the SUBACK.
        registered.append(callback)
        started.set()
        await asyncio.Event().wait()

    unsubscribe = AsyncMock()
    task = asyncio.create_task(
        _wait_for_response(
            AsyncMock(side_effect=subscribe),
            unsubscribe,
            device,
            AsyncMock(),
            timeout=10,
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _assert_removed(unsubscribe, device, registered)
