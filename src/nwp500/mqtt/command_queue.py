"""
MQTT command queue management for Navien Smart Control.

This module handles queueing of commands when the MQTT connection is lost,
and automatically sends them when the connection is restored.
"""

import logging
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .types import QoS
from .utils import QueuedCommand, redact_topic

if TYPE_CHECKING:
    from .utils import MqttConnectionConfig

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


class MqttCommandQueue:
    """
    Manages command queueing when MQTT connection is interrupted.

    Commands sent while disconnected are queued and automatically sent
    when the connection is restored. This ensures commands are not lost
    during temporary network interruptions.

    The queue uses a deque with a fixed maximum size. When the queue is
    full, the oldest command is automatically dropped to make room for
    new commands (FIFO with overflow dropping). Commands older than
    ``config.max_queued_command_age`` seconds are discarded at send time
    rather than replayed to the device.
    """

    def __init__(self, config: MqttConnectionConfig):
        """
        Initialize the command queue.

        Args:
            config: MQTT connection configuration with queue settings
        """
        self.config = config
        # A deque (not asyncio.Queue) so a command that fails mid-flush
        # can be re-inserted at the FRONT, preserving command order.
        self._queue: deque[QueuedCommand] = deque(
            maxlen=config.max_queued_commands
        )

    def enqueue(self, topic: str, payload: dict[str, Any], qos: QoS) -> None:
        """
        Add a command to the queue.

        If the queue is full, the oldest command is dropped to make room
        for the new one (FIFO with overflow dropping).

        Args:
            topic: MQTT topic
            payload: Command payload
            qos: Quality of Service level
        """
        if not self.config.enable_command_queue:
            _logger.warning(
                f"Command queue disabled, dropping command to "
                f"'{redact_topic(topic)}'. Enable command queue in "
                f"config to queue commands when disconnected."
            )
            return

        command = QueuedCommand(
            topic=topic,
            payload=payload,
            qos=qos,
            timestamp=datetime.now(UTC),
        )

        # deque(maxlen=N) drops from the opposite end automatically, but
        # log the overflow explicitly for visibility.
        if len(self._queue) == self._queue.maxlen:
            dropped = self._queue.popleft()
            _logger.warning(
                f"Command queue full ({self.config.max_queued_commands}), "
                f"dropped oldest command to '{redact_topic(dropped.topic)}'"
            )

        self._queue.append(command)
        _logger.info(f"Queued command (queue size: {len(self._queue)})")

    async def send_all(
        self,
        publish_func: Callable[..., Any],
        is_connected_func: Callable[[], bool],
    ) -> tuple[int, int]:
        """
        Send all queued commands.

        This is called automatically when connection is restored.

        Args:
            publish_func: Async function to publish messages (topic, payload,
            qos)
            is_connected_func: Function to check if currently connected

        Returns:
            Tuple of (sent_count, failed_count)
        """
        if not self._queue:
            return (0, 0)

        queue_size = len(self._queue)
        _logger.info(f"Sending {queue_size} queued command(s)...")

        sent_count = 0
        failed_count = 0
        max_age = self.config.max_queued_command_age
        now = datetime.now(UTC)

        while self._queue and is_connected_func():
            command = self._queue.popleft()

            # Don't replay stale control commands (e.g. an hours-old
            # set_power) to a physical appliance after a long outage.
            age = (now - command.timestamp).total_seconds()
            if max_age is not None and age > max_age:
                _logger.warning(
                    f"Discarding expired queued command to "
                    f"'{redact_topic(command.topic)}' "
                    f"(age {age:.0f}s > max {max_age:.0f}s)"
                )
                continue

            try:
                # Publish the queued command
                await publish_func(
                    topic=command.topic,
                    payload=command.payload,
                    qos=command.qos,
                )
                sent_count += 1
                _logger.debug(
                    f"Sent queued command to '{redact_topic(command.topic)}' "
                    f"(queued at {command.timestamp.isoformat()})"
                )
            except Exception as e:
                failed_count += 1
                _logger.error(
                    f"Failed to send queued command to "
                    f"'{redact_topic(command.topic)}': {e}"
                )
                # Re-queue at the FRONT so command order is preserved on
                # the next flush (re-appending would invert order-
                # sensitive sequences like power_on -> set_temp).
                self._queue.appendleft(command)
                break  # Stop processing on error to avoid cascade failures

        if sent_count > 0:
            _logger.info(
                f"Sent {sent_count} queued command(s)"
                + (f", {failed_count} failed" if failed_count > 0 else "")
            )

        return (sent_count, failed_count)

    def clear(self) -> int:
        """
        Clear all queued commands.

        Returns:
            Number of commands cleared
        """
        cleared = len(self._queue)
        self._queue.clear()

        if cleared > 0:
            _logger.info(f"Cleared {cleared} queued command(s)")
        return cleared

    @property
    def count(self) -> int:
        """Get the number of queued commands."""
        return len(self._queue)

    @property
    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return not self._queue

    @property
    def is_full(self) -> bool:
        """Check if the queue is full."""
        return len(self._queue) == self._queue.maxlen
