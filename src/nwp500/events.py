"""
Event Emitter for Navien device state changes.

This module provides an event-driven architecture for handling device state
changes, allowing multiple listeners per event and automatic state change
detection.
"""

import asyncio
import inspect
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Optional

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


@dataclass
class EventListener:
    """Represents a registered event listener."""

    callback: Callable
    once: bool = False
    priority: int = 50  # Default priority


class EventEmitter:
    """
    Event emitter with support for multiple listeners per event.

    Provides an event-driven architecture for device state changes with:
    - Multiple listeners per event
    - Async handler support
    - One-time listeners (once)
    - Priority-based execution order
    - Automatic state change detection

    Example::

        emitter = EventEmitter()

        # Register listeners
        emitter.on('temperature_changed', log_temperature)
        emitter.on('temperature_changed', update_ui)

        # Emit events
        await emitter.emit('temperature_changed', old_temp, new_temp)

        # One-time listener
        emitter.once('device_ready', initialize)

        # Remove listener
        emitter.off('temperature_changed', log_temperature)
    """

    def __init__(self):
        """Initialize the event emitter."""
        self._listeners: dict[str, list[EventListener]] = defaultdict(list)
        self._event_counts: dict[str, int] = defaultdict(int)

    def on(
        self,
        event: str,
        callback: Callable,
        priority: int = 50,
    ) -> None:
        """
        Register an event listener.

        Args:
            event: Event name to listen for
            callback: Function to call when event is emitted (can be async)
            priority: Execution priority (higher = earlier, default: 50)

        Example::

            def on_temp_change(old_temp: float, new_temp: float):
                print(f"Temperature: {old_temp}°F → {new_temp}°F")

            emitter.on('temperature_changed', on_temp_change)

            # Async handler
            async def save_to_db(temp: float):
                await db.save(temp)

            emitter.on('temperature_changed', save_to_db, priority=100)
        """
        listener = EventListener(callback=callback, once=False, priority=priority)
        self._listeners[event].append(listener)

        # Sort by priority (highest first)
        self._listeners[event].sort(key=lambda listener: listener.priority, reverse=True)

        _logger.debug(f"Registered listener for '{event}' event (priority: {priority})")

    def once(
        self,
        event: str,
        callback: Callable,
        priority: int = 50,
    ) -> None:
        """
        Register a one-time event listener.

        The listener will be automatically removed after first execution.

        Args:
            event: Event name to listen for
            callback: Function to call when event is emitted
            priority: Execution priority (higher = earlier, default: 50)

        Example::

            emitter.once('device_ready', initialize_device)
            # Will only be called once, then auto-removed
        """
        listener = EventListener(callback=callback, once=True, priority=priority)
        self._listeners[event].append(listener)

        # Sort by priority (highest first)
        self._listeners[event].sort(key=lambda listener: listener.priority, reverse=True)

        _logger.debug(f"Registered one-time listener for '{event}' event (priority: {priority})")

    def off(self, event: str, callback: Optional[Callable] = None) -> int:
        """
        Remove event listener(s).

        Args:
            event: Event name
            callback: Specific callback to remove, or None to remove all for event

        Returns:
            Number of listeners removed

        Example::

            # Remove specific listener
            emitter.off('temperature_changed', log_temperature)

            # Remove all listeners for event
            emitter.off('temperature_changed')
        """
        if event not in self._listeners:
            return 0

        if callback is None:
            # Remove all listeners for this event
            count = len(self._listeners[event])
            del self._listeners[event]
            _logger.debug(f"Removed all {count} listener(s) for '{event}' event")
            return count

        # Remove specific callback
        original_count = len(self._listeners[event])
        self._listeners[event] = [
            listener for listener in self._listeners[event] if listener.callback != callback
        ]
        removed_count = original_count - len(self._listeners[event])

        # Clean up if no listeners left
        if not self._listeners[event]:
            del self._listeners[event]

        if removed_count > 0:
            _logger.debug(f"Removed {removed_count} listener(s) for '{event}' event")

        return removed_count

    async def emit(self, event: str, *args, **kwargs) -> int:
        """
        Emit an event to all registered listeners.

        Executes listeners in priority order (highest first).
        One-time listeners are automatically removed after execution.

        Args:
            event: Event name to emit
            *args: Positional arguments to pass to listeners
            **kwargs: Keyword arguments to pass to listeners

        Returns:
            Number of listeners that were called

        Example::

            # Emit with arguments
            await emitter.emit('temperature_changed', 120, 130)

            # Emit with keyword arguments
            await emitter.emit('status_updated', status=device_status)
        """
        if event not in self._listeners:
            return 0

        listeners = self._listeners[event].copy()  # Copy to allow modification
        called_count = 0
        listeners_to_remove = []

        for listener in listeners:
            try:
                # Call handler and await if it returned an awaitable.
                result = listener.callback(*args, **kwargs)

                if inspect.isawaitable(result):
                    await result

                called_count += 1

                # Mark one-time listeners for removal
                if listener.once:
                    listeners_to_remove.append(listener)

            except Exception as e:
                _logger.error(
                    f"Error in '{event}' event handler: {e}",
                    exc_info=True,
                )

        # Remove one-time listeners
        for listener in listeners_to_remove:
            self._listeners[event].remove(listener)

        # Clean up if no listeners left
        if not self._listeners[event]:
            del self._listeners[event]

        # Track event count
        self._event_counts[event] += 1

        _logger.debug(f"Emitted '{event}' event to {called_count} listener(s)")
        return called_count

    def listener_count(self, event: str) -> int:
        """
        Get the number of listeners for an event.

        Args:
            event: Event name

        Returns:
            Number of registered listeners

        Example::

            count = emitter.listener_count('temperature_changed')
            print(f"{count} listeners registered")
        """
        return len(self._listeners.get(event, []))

    def event_count(self, event: str) -> int:
        """
        Get the number of times an event has been emitted.

        Args:
            event: Event name

        Returns:
            Number of times event was emitted

        Example::

            count = emitter.event_count('temperature_changed')
            print(f"Event emitted {count} times")
        """
        return self._event_counts.get(event, 0)

    def event_names(self) -> list[str]:
        """
        Get list of all registered event names.

        Returns:
            List of event names with active listeners

        Example::

            events = emitter.event_names()
            print(f"Active events: {', '.join(events)}")
        """
        return list(self._listeners.keys())

    def remove_all_listeners(self, event: Optional[str] = None) -> int:
        """
        Remove all listeners for specific event or all events.

        Args:
            event: Event name, or None to remove all listeners

        Returns:
            Number of listeners removed

        Example::

            # Remove all listeners for one event
            emitter.remove_all_listeners('temperature_changed')

            # Remove ALL listeners
            emitter.remove_all_listeners()
        """
        if event is not None:
            return self.off(event)

        # Remove all listeners for all events
        total_count = sum(len(listeners) for listeners in self._listeners.values())
        self._listeners.clear()
        _logger.debug(f"Removed all {total_count} listener(s)")
        return total_count

    async def wait_for(
        self,
        event: str,
        timeout: Optional[float] = None,
    ) -> tuple[Any, ...]:
        """
        Wait for an event to be emitted.

        Args:
            event: Event name to wait for
            timeout: Maximum time to wait in seconds (None = wait forever)

        Returns:
            Tuple of arguments passed to the event

        Raises:
            asyncio.TimeoutError: If timeout is reached

        Example::

            # Wait for device to be ready
            await emitter.wait_for('device_ready', timeout=30)

            # Wait for specific condition
            old_temp, new_temp = await emitter.wait_for('temperature_changed')
        """
        future = asyncio.Future()

        def handler(*args, **kwargs):
            if not future.done():
                # Store both args and kwargs
                future.set_result((args, kwargs))

        # Register one-time listener
        self.once(event, handler)

        try:
            if timeout is not None:
                args, kwargs = await asyncio.wait_for(future, timeout=timeout)
            else:
                args, kwargs = await future

            # Return just args for simplicity (most common case)
            return args

        except asyncio.TimeoutError:
            # Remove the listener on timeout
            self.off(event, handler)
            raise
