"""``mqtt.utils.request_reply`` removes its reply handler on every path."""

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nwp500.mqtt.utils import request_reply

LOG = logging.getLogger(__name__)


async def _ask(subscribe: Any, send: Any, timeout: float = 1.0) -> Any:
    unsubscribe = AsyncMock()
    device = MagicMock()
    task = asyncio.create_task(
        request_reply(
            subscribe,
            unsubscribe,
            device,
            send,
            timeout=timeout,
            what="test",
            logger=LOG,
        )
    )
    return task, unsubscribe


@pytest.mark.asyncio
async def test_the_reply_is_returned_and_the_handler_removed() -> None:
    async def subscribe(device: Any, callback: Any) -> None:
        callback("answer")

    task, unsubscribe = await _ask(subscribe, AsyncMock())
    assert await task == "answer"
    unsubscribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_reply_is_none_and_the_handler_removed() -> None:
    task, unsubscribe = await _ask(AsyncMock(), AsyncMock(), timeout=0.01)
    assert await task is None
    unsubscribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_while_subscribing_removes_the_handler() -> None:
    """The subscription manager registers the callback before the
    broker's acknowledgement; a cancel then still removes it."""
    acked = asyncio.Event()

    async def subscribe(device: Any, callback: Any) -> None:
        await acked.wait()

    task, unsubscribe = await _ask(subscribe, AsyncMock())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    unsubscribe.assert_awaited_once()
