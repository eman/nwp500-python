"""
MQTT reconnection handler for Navien Smart Control.

This module handles automatic reconnection with exponential backoff when
the MQTT connection is interrupted.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, Callable, Optional

from awscrt.exceptions import AwsCrtError

if TYPE_CHECKING:
    from .mqtt_utils import MqttConnectionConfig

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


class MqttReconnectionHandler:
    """
    Handles automatic reconnection logic with exponential backoff.

    This class manages reconnection attempts when the MQTT connection is
    interrupted, implementing exponential backoff and configurable retry limits.
    """

    def __init__(
        self,
        config: "MqttConnectionConfig",
        is_connected_func: Callable[[], bool],
        schedule_coroutine_func: Callable[[Any], None],
        reconnect_func: Callable[[], Awaitable[None]],
        deep_reconnect_func: Optional[Callable[[], Awaitable[None]]] = None,
        emit_event_func: Optional[Callable[..., Awaitable[Any]]] = None,
    ):
        """
        Initialize reconnection handler.

        Args:
            config: MQTT connection configuration
            is_connected_func: Function to check if currently connected
            schedule_coroutine_func: Function to schedule coroutines from any
            thread
            reconnect_func: Async function to trigger active reconnection
            deep_reconnect_func: Optional async function to trigger deep
                reconnection (full rebuild)
            emit_event_func: Optional async function to emit events
                (e.g., EventEmitter.emit)
        """
        self.config = config
        self._is_connected_func = is_connected_func
        self._schedule_coroutine = schedule_coroutine_func
        self._reconnect_func = reconnect_func
        self._deep_reconnect_func = deep_reconnect_func
        self._emit_event = emit_event_func

        self._reconnect_attempts = 0
        self._reconnect_task: Optional[asyncio.Task[None]] = None
        self._manual_disconnect = False
        self._enabled = False

    def enable(self) -> None:
        """Enable automatic reconnection."""
        self._enabled = True
        self._manual_disconnect = False
        _logger.debug("Automatic reconnection enabled")

    def disable(self) -> None:
        """Disable automatic reconnection (e.g., for manual disconnect)."""
        self._enabled = False
        self._manual_disconnect = True
        _logger.debug("Automatic reconnection disabled")

        # Cancel any pending reconnection task
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None

    def on_connection_interrupted(self, error: Exception) -> None:
        """
        Handle connection interruption.

        Args:
            error: Error that caused the interruption
        """
        _logger.warning(f"Connection interrupted: {error}")

        # Start automatic reconnection if enabled
        if (
            self.config.auto_reconnect
            and self._enabled
            and not self._manual_disconnect
            and (not self._reconnect_task or self._reconnect_task.done())
        ):
            _logger.info("Starting automatic reconnection...")
            self._schedule_coroutine(self._start_reconnect_task())

    def on_connection_resumed(
        self, return_code: Any, session_present: Any
    ) -> None:
        """
        Handle connection resumption.

        Args:
            return_code: MQTT return code
            session_present: Whether session was present
        """
        _logger.info(
            f"Connection resumed: return_code={return_code}, "
            f"session_present={session_present}"
        )
        # Reset reconnection attempts on successful connection
        self._reconnect_attempts = 0

        # Cancel any pending reconnection task
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None

    async def _start_reconnect_task(self) -> None:
        """
        Start the reconnect task within the event loop.

        This is a helper method to create the reconnect task from within
        a coroutine that's scheduled via _schedule_coroutine.
        """
        if not self._reconnect_task or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(
                self._reconnect_with_backoff()
            )

    async def _reconnect_with_backoff(self) -> None:
        """
        Attempt to reconnect with exponential backoff.

        This method is called automatically when connection is interrupted
        if auto_reconnect is enabled. Supports unlimited retries when
        max_reconnect_attempts is -1.

        Uses a two-tier strategy:
        - Quick reconnects (attempts 1-N): Fast reconnection with existing setup
        - Deep reconnects (attempts N+): Full rebuild including token refresh
        """
        unlimited_retries = self.config.max_reconnect_attempts < 0

        while (
            not self._is_connected_func()
            and not self._manual_disconnect
            and (
                unlimited_retries
                or self._reconnect_attempts < self.config.max_reconnect_attempts
            )
        ):
            self._reconnect_attempts += 1

            # Determine if we should do a deep reconnection
            has_deep_reconnect = self._deep_reconnect_func is not None
            is_at_threshold = (
                self._reconnect_attempts >= self.config.deep_reconnect_threshold
            )
            is_threshold_multiple = (
                self._reconnect_attempts % self.config.deep_reconnect_threshold
                == 0
            )
            use_deep_reconnect = (
                has_deep_reconnect and is_at_threshold and is_threshold_multiple
            )

            # Calculate delay with exponential backoff
            delay = min(
                self.config.initial_reconnect_delay
                * (
                    self.config.reconnect_backoff_multiplier
                    ** (self._reconnect_attempts - 1)
                ),
                self.config.max_reconnect_delay,
            )

            if unlimited_retries:
                reconnect_type = "deep" if use_deep_reconnect else "quick"
                _logger.info(
                    "Reconnection attempt %d (%s) in %.1f seconds...",
                    self._reconnect_attempts,
                    reconnect_type,
                    delay,
                )
            else:
                _logger.info(
                    "Reconnection attempt %d/%d in %.1f seconds...",
                    self._reconnect_attempts,
                    self.config.max_reconnect_attempts,
                    delay,
                )

            try:
                await asyncio.sleep(delay)

                # Check if we're already connected (AWS SDK auto-reconnected)
                if self._is_connected_func():
                    _logger.info(
                        "AWS IoT SDK automatically reconnected during delay"
                    )
                    break

                # Trigger appropriate reconnection type
                if use_deep_reconnect and self._deep_reconnect_func is not None:
                    _logger.info(
                        "Triggering deep reconnection "
                        "(full rebuild with token refresh)..."
                    )
                    try:
                        await self._deep_reconnect_func()
                        if self._is_connected_func():
                            _logger.info(
                                "Successfully reconnected via deep reconnection"
                            )
                            break
                    except (AwsCrtError, RuntimeError, ValueError) as e:
                        _logger.warning(
                            f"Deep reconnection failed: {e}. Will retry..."
                        )
                else:
                    _logger.info("Triggering quick reconnection...")
                    try:
                        await self._reconnect_func()
                        if self._is_connected_func():
                            _logger.info(
                                "Successfully reconnected via "
                                "quick reconnection"
                            )
                            break
                    except (AwsCrtError, RuntimeError) as e:
                        _logger.warning(
                            f"Quick reconnection failed: {e}. Will retry..."
                        )

            except asyncio.CancelledError:
                _logger.info("Reconnection task cancelled")
                break
            except (AwsCrtError, RuntimeError) as e:
                _logger.error(
                    f"Error during reconnection attempt: {e}", exc_info=True
                )

        # Check final state (only if not unlimited retries)
        if (
            not unlimited_retries
            and self._reconnect_attempts >= self.config.max_reconnect_attempts
            and not self._is_connected_func()
        ):
            _logger.error(
                f"Failed to reconnect after "
                f"{self.config.max_reconnect_attempts} attempts. "
                "Manual reconnection required."
            )
            # Emit reconnection_failed event if event emitter is available
            if self._emit_event:
                try:
                    await self._emit_event(
                        "reconnection_failed", self._reconnect_attempts
                    )
                except (TypeError, RuntimeError) as e:
                    _logger.error(
                        f"Error emitting reconnection_failed event: {e}"
                    )

    async def cancel(self) -> None:
        """Cancel any pending reconnection task."""
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

    @property
    def is_reconnecting(self) -> bool:
        """Check if currently attempting to reconnect."""
        return (
            self._reconnect_task is not None and not self._reconnect_task.done()
        )

    @property
    def attempt_count(self) -> int:
        """Get the number of reconnection attempts made."""
        return self._reconnect_attempts

    def reset_attempts(self) -> None:
        """Reset the reconnection attempt counter."""
        self._reconnect_attempts = 0

    def reset(self) -> None:
        """Reset reconnection state and enable reconnection."""
        self._reconnect_attempts = 0
        self.enable()
