"""
MQTT command queue management for Navien Smart Control.

This module handles queueing of commands when the MQTT connection is lost,
and automatically sends them when the connection is restored.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from awscrt import mqtt

from .mqtt_utils import QueuedCommand, redact_topic

if TYPE_CHECKING:
    from .mqtt_utils import MqttConnectionConfig

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

    The queue uses a deque with a fixed maximum size. When the queue
    is full, the oldest command is automatically dropped to make room for
    new commands (FIFO with overflow dropping).
    """

    def __init__(self, config: MqttConnectionConfig):
        """
        Initialize the command queue.

        Args:
            config: MQTT connection configuration with queue settings
        """
        self.config = config
        # Use deque for thread-safe queue that doesn't require event loop
        self._queue: deque[QueuedCommand] = deque(
            maxlen=config.max_queued_commands
        )

    def enqueue(
        self, topic: str, payload: dict[str, Any], qos: mqtt.QoS
    ) -> None:
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
            topic=topic, payload=payload, qos=qos, timestamp=datetime.utcnow()
        )

        # Check if adding will cause overflow (deque auto-removes oldest)
        if len(self._queue) >= self.config.max_queued_commands:
            _logger.warning(
                f"Command queue full ({self.config.max_queued_commands}), "
                f"oldest command will be dropped"
            )

        # Add new command (deque automatically drops oldest if at maxlen)
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

        while self._queue and is_connected_func():
            # Get command from queue (FIFO - popleft)
            command = self._queue.popleft()

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
                # Re-queue at front if there's room
                if len(self._queue) < self.config.max_queued_commands:
                    self._queue.appendleft(command)
                    _logger.warning("Re-queued failed command")
                else:
                    _logger.error("Failed to re-queue command - queue is full")
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
        return len(self._queue) == 0

    @property
    def is_full(self) -> bool:
        """Check if the queue is full."""
        return len(self._queue) >= self.config.max_queued_commands
