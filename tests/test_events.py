"""Tests for event emitter functionality."""

import asyncio

import pytest

from nwp500.events import EventEmitter, EventListener


def test_event_listener_creation():
    """Test EventListener dataclass creation."""

    def callback():
        return None

    listener = EventListener(callback=callback, once=False, priority=50)

    assert listener.callback == callback
    assert listener.once is False
    assert listener.priority == 50


def test_event_emitter_initialization():
    """Test EventEmitter initialization."""
    emitter = EventEmitter()

    assert isinstance(emitter._listeners, dict)
    assert isinstance(emitter._event_counts, dict)
    assert len(emitter._listeners) == 0
    assert len(emitter._event_counts) == 0


def test_register_listener():
    """Test registering an event listener."""
    emitter = EventEmitter()
    called = []

    def handler():
        called.append(True)

    emitter.on("test_event", handler)

    assert emitter.listener_count("test_event") == 1
    assert "test_event" in emitter.event_names()


def test_multiple_listeners_same_event():
    """Test multiple listeners for the same event."""
    emitter = EventEmitter()
    results = []

    def handler1():
        results.append(1)

    def handler2():
        results.append(2)

    def handler3():
        results.append(3)

    emitter.on("test_event", handler1)
    emitter.on("test_event", handler2)
    emitter.on("test_event", handler3)

    assert emitter.listener_count("test_event") == 3


@pytest.mark.asyncio
async def test_emit_event():
    """Test emitting an event."""
    emitter = EventEmitter()
    called = []

    def handler(value):
        called.append(value)

    emitter.on("test_event", handler)

    count = await emitter.emit("test_event", 42)

    assert count == 1
    assert called == [42]
    assert emitter.event_count("test_event") == 1


@pytest.mark.asyncio
async def test_emit_multiple_args():
    """Test emitting event with multiple arguments."""
    emitter = EventEmitter()
    results = []

    def handler(a, b, c):
        results.append((a, b, c))

    emitter.on("test_event", handler)

    await emitter.emit("test_event", 1, 2, 3)

    assert results == [(1, 2, 3)]


@pytest.mark.asyncio
async def test_emit_kwargs():
    """Test emitting event with keyword arguments."""
    emitter = EventEmitter()
    results = []

    def handler(name, value):
        results.append({"name": name, "value": value})

    emitter.on("test_event", handler)

    await emitter.emit("test_event", name="test", value=42)

    assert results == [{"name": "test", "value": 42}]


@pytest.mark.asyncio
async def test_async_handler():
    """Test async event handler."""
    emitter = EventEmitter()
    results = []

    async def async_handler(value):
        await asyncio.sleep(0.01)  # Simulate async operation
        results.append(value)

    emitter.on("test_event", async_handler)

    await emitter.emit("test_event", "async_test")

    assert results == ["async_test"]


@pytest.mark.asyncio
async def test_priority_ordering():
    """Test handlers execute in priority order."""
    emitter = EventEmitter()
    results = []

    def low_priority():
        results.append("low")

    def medium_priority():
        results.append("medium")

    def high_priority():
        results.append("high")

    # Register in mixed order
    emitter.on("test_event", medium_priority, priority=50)
    emitter.on("test_event", high_priority, priority=100)
    emitter.on("test_event", low_priority, priority=10)

    await emitter.emit("test_event")

    # Should execute in priority order (high to low)
    assert results == ["high", "medium", "low"]


@pytest.mark.asyncio
async def test_once_listener():
    """Test one-time listener."""
    emitter = EventEmitter()
    called_count = []

    def handler():
        called_count.append(1)

    emitter.once("test_event", handler)

    # First emit
    await emitter.emit("test_event")
    assert len(called_count) == 1
    assert emitter.listener_count("test_event") == 0  # Auto-removed

    # Second emit - should not call handler
    await emitter.emit("test_event")
    assert len(called_count) == 1  # Still 1


def test_remove_specific_listener():
    """Test removing a specific listener."""
    emitter = EventEmitter()

    def handler1():
        pass

    def handler2():
        pass

    emitter.on("test_event", handler1)
    emitter.on("test_event", handler2)

    assert emitter.listener_count("test_event") == 2

    # Remove handler1
    removed = emitter.off("test_event", handler1)

    assert removed == 1
    assert emitter.listener_count("test_event") == 1


def test_remove_all_listeners_for_event():
    """Test removing all listeners for an event."""
    emitter = EventEmitter()

    emitter.on("test_event", lambda: None)
    emitter.on("test_event", lambda: None)
    emitter.on("test_event", lambda: None)

    assert emitter.listener_count("test_event") == 3

    # Remove all
    removed = emitter.off("test_event")

    assert removed == 3
    assert emitter.listener_count("test_event") == 0


def test_remove_all_listeners():
    """Test removing all listeners for all events."""
    emitter = EventEmitter()

    emitter.on("event1", lambda: None)
    emitter.on("event1", lambda: None)
    emitter.on("event2", lambda: None)
    emitter.on("event3", lambda: None)

    assert len(emitter.event_names()) == 3

    removed = emitter.remove_all_listeners()

    assert removed == 4
    assert len(emitter.event_names()) == 0


@pytest.mark.asyncio
async def test_wait_for_event():
    """Test waiting for an event."""
    emitter = EventEmitter()

    async def emit_later():
        await asyncio.sleep(0.1)
        await emitter.emit("test_event", "test_value")

    # Start emitting in background
    asyncio.create_task(emit_later())

    # Wait for event
    result = await emitter.wait_for("test_event", timeout=1.0)

    assert result == ("test_value",)


@pytest.mark.asyncio
async def test_wait_for_timeout():
    """Test wait_for with timeout."""
    emitter = EventEmitter()

    with pytest.raises(asyncio.TimeoutError):
        await emitter.wait_for("nonexistent_event", timeout=0.1)


@pytest.mark.asyncio
async def test_event_error_handling():
    """Test that errors in handlers don't stop other handlers."""
    emitter = EventEmitter()
    results = []

    def bad_handler():
        raise ValueError("Handler error")

    def good_handler():
        results.append("success")

    emitter.on("test_event", bad_handler)
    emitter.on("test_event", good_handler)

    # Should not raise, and good_handler should still execute
    await emitter.emit("test_event")

    # Both handlers are called (even though one errors)
    # The emitter logs the error but continues with other handlers
    assert results == ["success"]  # Good handler succeeded


def test_event_names():
    """Test getting list of event names."""
    emitter = EventEmitter()

    emitter.on("event1", lambda: None)
    emitter.on("event2", lambda: None)
    emitter.on("event3", lambda: None)

    names = emitter.event_names()

    assert len(names) == 3
    assert "event1" in names
    assert "event2" in names
    assert "event3" in names


@pytest.mark.asyncio
async def test_event_count_tracking():
    """Test event emission counting."""
    emitter = EventEmitter()

    emitter.on("test_event", lambda: None)

    assert emitter.event_count("test_event") == 0

    await emitter.emit("test_event")
    assert emitter.event_count("test_event") == 1

    await emitter.emit("test_event")
    await emitter.emit("test_event")
    assert emitter.event_count("test_event") == 3


@pytest.mark.asyncio
async def test_no_listeners_emit():
    """Test emitting event with no listeners."""
    emitter = EventEmitter()

    # Should not raise
    count = await emitter.emit("nonexistent_event", "value")

    assert count == 0
