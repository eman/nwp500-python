Event Emitter Architecture Documentation
========================================

Overview
--------

The event emitter implementation provides a robust, production-ready
event-driven architecture for the nwp500-python library. This document
details the technical architecture, design decisions, and implementation
patterns.

Architecture Diagram
--------------------

::

   ┌─────────────────────────────────────────────────────────────┐
   │                    NavienMqttClient                         │
   │                  (extends EventEmitter)                     │
   ├─────────────────────────────────────────────────────────────┤
   │                                                             │
   │  ┌──────────────┐         ┌──────────────┐                  │
   │  │ MQTT Thread  │────────▶│  Main Thread │                  │
   │  │ (Dummy-1)    │         │  Event Loop  │                  │
   │  └──────────────┘         └──────────────┘                  │
   │        │                         │                          │
   │        │ message_handler()       │ emit()                   │
   │        │                         │                          │
   │        ▼                         ▼                          │
   │  ┌──────────────────────────────────────────┐               │
   │  │    _schedule_coroutine()                 │               │
   │  │  (Thread-safe scheduling)                │               │
   │  └──────────────────────────────────────────┘               │
   │        │                                                    │
   │        │ run_coroutine_threadsafe()                         │
   │        │                                                    │
   │        ▼                                                    │
   │  ┌──────────────────────────────────────────┐               │
   │  │         EventEmitter.emit()              │               │
   │  │    (Async event distribution)            │               │
   │  └──────────────────────────────────────────┘               │
   │        │                                                    │
   │        ├────────────┬────────────┬────────────┐             │
   │        ▼            ▼            ▼            ▼             │
   │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐         │
   │  │Handler 1│  │Handler 2│  │Handler 3│  │Handler n│         │
   │  │(Pri:100)│  │(Pri: 50)│  │(Pri: 50)│  │(Pri: 10)│         │
   │  └─────────┘  └─────────┘  └─────────┘  └─────────┘         │
   │      ▲            ▲            ▲            ▲               │
   │      │            │            │            │               │
   │  Executed in priority order (high to low)                   │
   │                                                             │
   └─────────────────────────────────────────────────────────────┘

Component Architecture
----------------------

1. EventEmitter Base Class
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Location:** ``src/nwp500/events.py``

**Responsibilities:** - Manage listener registration and removal - Emit
events to registered listeners - Handle priority-based execution -
Support both sync and async handlers - Provide introspection
capabilities

**Key Data Structures:**

.. code:: python

   class EventEmitter:
       _listeners: dict[str, list[EventListener]]
       # Maps event names to lists of listeners
       # Example: {'temperature_changed': [EventListener(...), ...]}
       
       _event_counts: dict[str, int]
       # Tracks how many times each event has been emitted
       # Example: {'temperature_changed': 42}

**Listener Storage:**

.. code:: python

   @dataclass
   class EventListener:
       callback: Callable       # Handler function (sync or async)
       once: bool = False      # Auto-remove after first execution
       priority: int = 50      # Execution priority (higher = earlier)

2. MQTT Client Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Location:** ``src/nwp500/mqtt_client.py``

**Key Components:**

Event Loop Management
^^^^^^^^^^^^^^^^^^^^^

.. code:: python

   class NavienMqttClient(EventEmitter):
       _loop: Optional[asyncio.AbstractEventLoop]
       # Captured during connect() for thread-safe scheduling
       
       async def connect(self):
           # Capture the running event loop
           self._loop = asyncio.get_running_loop()
           # ... connection logic

Thread-Safe Scheduling
^^^^^^^^^^^^^^^^^^^^^^

.. code:: python

   def _schedule_coroutine(self, coro):
       """
       Safely schedule a coroutine from any thread.
       
       This is critical because MQTT callbacks run in threads
       created by the AWS IoT SDK, not in the main event loop.
       """
       if self._loop is None:
           _logger.warning("No event loop available")
           return
       
       try:
           asyncio.run_coroutine_threadsafe(coro, self._loop)
       except Exception as e:
           _logger.error(f"Failed to schedule coroutine: {e}")

State Change Detection
^^^^^^^^^^^^^^^^^^^^^^

.. code:: python

   _previous_status: Optional[DeviceStatus]
   _previous_feature: Optional[DeviceFeature]

   async def _detect_state_changes(self, status: DeviceStatus):
       """Compare current state with previous, emit change events."""
       # Temperature, mode, power, heating state, errors, etc.

3. Message Flow
~~~~~~~~~~~~~~~

Status Update Flow
^^^^^^^^^^^^^^^^^^

::

   1. AWS IoT receives message
      └─▶ MQTT Thread: _on_message_received()
          └─▶ status_message_handler(topic, message)
              ├─▶ Parse DeviceStatus from message
              ├─▶ _schedule_coroutine(emit('status_received', status))
              ├─▶ _schedule_coroutine(_detect_state_changes(status))
              └─▶ Call user callback(status)

   2. Main Event Loop
      └─▶ emit('status_received', status)
          └─▶ Execute all registered handlers in priority order

      └─▶ _detect_state_changes(status)
          ├─▶ Compare with _previous_status
          ├─▶ emit('temperature_changed', old, new) if changed
          ├─▶ emit('mode_changed', old, new) if changed
          ├─▶ emit('heating_started', status) if applicable
          └─▶ emit('error_detected', code, status) if applicable

Feature Update Flow
^^^^^^^^^^^^^^^^^^^

::

   1. AWS IoT receives message
      └─▶ MQTT Thread: feature_message_handler()
          ├─▶ Parse DeviceFeature from message
          ├─▶ _schedule_coroutine(emit('feature_received', feature))
          └─▶ Call user callback(feature)

   2. Main Event Loop
      └─▶ emit('feature_received', feature)
          └─▶ Execute all registered handlers

Connection Event Flow
^^^^^^^^^^^^^^^^^^^^^

::

   1. AWS IoT connection event
      └─▶ MQTT Thread: _on_connection_interrupted_internal()
          ├─▶ _schedule_coroutine(emit('connection_interrupted', error))
          └─▶ Call user callback if registered

   2. Main Event Loop
      └─▶ emit('connection_interrupted', error)
          └─▶ Execute all registered handlers

Design Patterns
---------------

1. Observer Pattern
~~~~~~~~~~~~~~~~~~~

The event emitter implements the classic Observer pattern: -
**Subject:** NavienMqttClient (emits events) - **Observers:** Registered
event handlers - **Notification:** Async event emission

2. Priority Queue Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~

Listeners are executed in priority order: - High priority (>50):
Critical operations (shutdown, safety) - Normal priority (50): Regular
operations (logging, UI updates) - Low priority (<50): Non-critical
operations (notifications, analytics)

3. Producer-Consumer Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Producers:** MQTT message handlers (produce events)
- **Queue:** Event loop task queue
- **Consumers:** Event handlers (consume events)

4. Thread-Safe Bridge Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``_schedule_coroutine()`` method bridges two execution contexts: -
**Context 1:** MQTT callback thread (synchronous, no event loop) -
**Context 2:** Main event loop (asynchronous, event-driven) -
**Bridge:** ``run_coroutine_threadsafe()`` for safe scheduling

Concurrency Model
-----------------

Thread Model
~~~~~~~~~~~~

::

   ┌──────────────────┐
   │  Main Thread     │
   │  Event Loop      │◀─── User code runs here
   │  ┌────────────┐  │
   │  │ Task Queue │  │◀─── Events processed here
   │  └────────────┘  │
   └──────────────────┘
            ▲
            │ run_coroutine_threadsafe()
            │
   ┌──────────────────┐
   │  MQTT Thread     │
   │  (Dummy-1)       │◀─── AWS IoT SDK callbacks
   │  ┌────────────┐  │
   │  │ Callbacks  │  │◀─── Message handlers
   │  └────────────┘  │
   └──────────────────┘

Synchronization Points
~~~~~~~~~~~~~~~~~~~~~~

1. **Event Loop Capture:** Happens once during ``connect()``
2. **Event Scheduling:** Every MQTT callback uses
   ``_schedule_coroutine()``
3. **Handler Execution:** All handlers run in main event loop
4. **State Updates:** All state changes happen in main thread

Lock-Free Design
~~~~~~~~~~~~~~~~

- No explicit locks (mutexes, semaphores)
- Thread safety via event loop scheduling
- State modifications only in event loop
- Read-only access from MQTT threads

Error Handling Strategy
-----------------------

Handler Error Isolation
~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   async def emit(self, event: str, *args, **kwargs) -> int:
       """Emit event to all listeners."""
       for listener in listeners:
           try:
               if asyncio.iscoroutinefunction(listener.callback):
                   await listener.callback(*args, **kwargs)
               else:
                   listener.callback(*args, **kwargs)
           except Exception as e:
               # Log error but continue with other handlers
               _logger.error(f"Error in '{event}' handler: {e}")
       # Handler errors don't propagate to emitter

Scheduling Error Handling
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   def _schedule_coroutine(self, coro):
       """Schedule with error handling."""
       if self._loop is None:
           _logger.warning("No event loop available")
           return  # Graceful degradation
       
       try:
           asyncio.run_coroutine_threadsafe(coro, self._loop)
       except Exception as e:
           _logger.error(f"Failed to schedule: {e}")
           # Don't crash, just log

Error Event Propagation
~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   # Errors become events themselves
   mqtt_client.on('error_detected', handle_device_error)

   # Errors don't stop the system
   def risky_handler(status):
       raise Exception("Handler failed")  # Logged, not propagated

   mqtt_client.on('status_received', risky_handler)  # Won't crash system

Performance Characteristics
---------------------------

Time Complexity
~~~~~~~~~~~~~~~

==================== ========== ===========================
Operation            Complexity Notes
==================== ========== ===========================
Register listener    O(n log n) Due to priority sorting
Remove listener      O(n)       Linear search
Emit event           O(n)       n = number of listeners
Check listener count O(1)       Direct dict lookup
Get event names      O(k)       k = number of unique events
==================== ========== ===========================

Space Complexity
~~~~~~~~~~~~~~~~

============== ============
Component      Memory Usage
============== ============
EventListener  ~100 bytes
Event mapping  ~200 bytes
Event counts   ~50 bytes
Total overhead ~1 KB
============== ============

Execution Time
~~~~~~~~~~~~~~

.. code:: python

   # Benchmarks (approximate)
   register_listener()  # < 0.1ms
   emit_event()        # < 1ms per handler
   schedule_coroutine() # < 0.5ms (thread switch)

Memory Management
-----------------

Automatic Cleanup
~~~~~~~~~~~~~~~~~

1. **One-time listeners:** Auto-removed after execution
2. **Empty event lists:** Deleted when last listener removed
3. **Previous state:** Only one previous state kept per device
4. **Event loop reference:** Single reference, captured once

Memory Leaks Prevention
~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   # Clean up empty event lists
   if not self._listeners[event]:
       del self._listeners[event]

   # Remove one-time listeners immediately
   if listener.once:
       self._listeners[event].remove(listener)

   # No circular references (dataclasses, no __del__)

Testing Strategy
----------------

Unit Tests (``tests/test_events.py``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Listener registration/removal
- Event emission (sync/async)
- Priority ordering
- One-time listeners
- Error handling
- Wait for events
- Statistics tracking

Integration Tests
~~~~~~~~~~~~~~~~~

- MQTT callback integration
- Thread-safe scheduling
- State change detection
- Real device message handling

Test Coverage
~~~~~~~~~~~~~

::

   src/nwp500/events.py: 93% coverage
   - 19 unit tests
   - All edge cases covered
   - Async functionality tested

Configuration & Tuning
----------------------

Priority Levels (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   # Emergency/Safety (100-150)
   mqtt_client.on('error_detected', emergency_shutdown, priority=150)

   # Critical Operations (75-99)
   mqtt_client.on('temperature_changed', critical_alert, priority=90)

   # Normal Operations (50-74)
   mqtt_client.on('status_received', log_status, priority=50)

   # Low Priority (1-49)
   mqtt_client.on('status_received', send_notification, priority=20)

Event Loop Tuning
~~~~~~~~~~~~~~~~~

.. code:: python

   # For high-frequency updates, consider batching
   class BatchHandler:
       def __init__(self, batch_size=10):
           self.buffer = []
           self.batch_size = batch_size
       
       def on_status(self, status):
           self.buffer.append(status)
           if len(self.buffer) >= self.batch_size:
               self.flush()
       
       def flush(self):
           # Process batch
           self.buffer.clear()

Upgrade Path
------------

Phase 1 → Phase 2
~~~~~~~~~~~~~~~~~

1. Add event filtering with lambda conditions
2. Implement event middleware
3. Add event buffering and replay
4. Introduce event namespacing

Phase 2 → Phase 3
~~~~~~~~~~~~~~~~~

1. Wildcard event subscriptions (``device.*``)
2. Event history and time-travel debugging
3. Performance metrics and monitoring
4. Event TTL and expiration

Best Practices
--------------

Do’s 
~~~~~~~

- Register handlers before calling ``connect()``
- Use priority for execution order control
- Keep handlers lightweight and fast
- Use async handlers for I/O operations
- Check event counts for debugging
- Remove handlers when no longer needed

Don’ts
~~~~~~~~~

- Don’t register handlers from MQTT threads
- Don’t block in sync handlers
- Don’t raise exceptions in handlers (they’re logged)
- Don’t register same handler multiple times
- Don’t store large objects in handler closures
- Don’t forget to ``await connect()`` first

Debugging Guide
---------------

Enable Debug Logging
~~~~~~~~~~~~~~~~~~~~

.. code:: python

   import logging
   logging.basicConfig(level=logging.DEBUG)
   logging.getLogger('nwp500.events').setLevel(logging.DEBUG)
   logging.getLogger('nwp500.mqtt_client').setLevel(logging.DEBUG)

Inspection Tools
~~~~~~~~~~~~~~~~

.. code:: python

   # Check registration
   print(f"Listeners: {mqtt_client.listener_count('temperature_changed')}")
   print(f"Events: {mqtt_client.event_names()}")
   print(f"Emitted: {mqtt_client.event_count('temperature_changed')}")

   # Test handler
   def debug_handler(*args, **kwargs):
       print(f"Handler called: args={args}, kwargs={kwargs}")

   mqtt_client.on('temperature_changed', debug_handler)

Common Debugging Patterns
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   # Trace all events
   def event_tracer(event_name):
       def handler(*args, **kwargs):
           print(f"[{event_name}] {args} {kwargs}")
       return handler

   for event in ['status_received', 'temperature_changed', 'error_detected']:
       mqtt_client.on(event, event_tracer(event))

Security Considerations
-----------------------

Input Validation
~~~~~~~~~~~~~~~~

- Event names are string keys (no injection risk)
- Handler arguments are from trusted sources (device messages)
- No eval() or exec() usage
- No dynamic code execution

Resource Limits
~~~~~~~~~~~~~~~

- No limit on listener count (consider adding if needed)
- No limit on event count tracking (consider periodic reset)
- Memory bounded by number of registered handlers
- No recursive event emission (by design)

Thread Safety
~~~~~~~~~~~~~

- All mutations happen in event loop (single-threaded)
- No race conditions in listener list
- Thread-safe scheduling from MQTT threads
- No shared mutable state across threads

Appendix
--------

File Locations
~~~~~~~~~~~~~~

::

   src/nwp500/
   ├── events.py           # EventEmitter implementation
   ├── mqtt_client.py      # Integration and state detection
   └── __init__.py         # Exports

   examples/
   └── event_emitter_demo.py  # Usage examples

   tests/
   └── test_events.py      # Unit tests

   docs/
   ├── EVENT_EMITTER_PHASE1_COMPLETE.md  # Feature documentation
   └── EVENT_ARCHITECTURE.md              # This file

Dependencies
~~~~~~~~~~~~

- Python 3.9+
- asyncio (standard library)
- AWS IoT SDK (for MQTT)
- pytest-asyncio (testing only)

References
~~~~~~~~~~

- `PEP 492 - Coroutines with
  async/await <https://www.python.org/dev/peps/pep-0492/>`__
- `asyncio
  Documentation <https://docs.python.org/3/library/asyncio.html>`__
- `Observer
  Pattern <https://refactoring.guru/design-patterns/observer>`__
- `AWS IoT SDK <https://github.com/aws/aws-iot-device-sdk-python-v2>`__

--------------

| **Document Version:** 1.0
| **Last Updated:** January 2025
| **Author:** Emmanuel Levijarvi
