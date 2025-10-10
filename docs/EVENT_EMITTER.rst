Event Emitter
=====================

.. contents::
   :local:
   :depth: 2

Overview
========

The nwp500 library implements an event-driven architecture that allows multiple listeners to respond to device state changes. This pattern enables cleaner code organization, better separation of concerns, and easier integration with other systems.

The event emitter provides automatic state change detection, priority-based execution, and full support for both synchronous and asynchronous event handlers.

Key Features
============

- **Multiple Listeners** - Register multiple handlers for the same event
- **Async Support** - Native support for async/await event handlers
- **Priority-Based Execution** - Control the order in which handlers execute
- **One-Time Listeners** - Handlers that automatically remove themselves after first execution
- **Automatic State Detection** - Events fire only when values actually change
- **Thread-Safe** - Safe event emission from MQTT callback threads
- **Dynamic Management** - Add/remove listeners at runtime
- **Event Statistics** - Track event counts and listener registration

Quick Start
===========

Basic Usage
-----------

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienMqttClient
    import asyncio

    async def main():
        # Authenticate and create MQTT client
        async with NavienAuthClient("email@example.com", "password") as auth_client:
            mqtt_client = NavienMqttClient(auth_client)
            await mqtt_client.connect()
            
            # Register event handlers
            mqtt_client.on('temperature_changed', handle_temperature)
            mqtt_client.on('error_detected', handle_error)
            
            # Subscribe to device updates
            devices = await api_client.list_devices()
            device = devices[0]
            await mqtt_client.subscribe_device_status(device, lambda s: None)
            
            # Events will now fire automatically!
            await asyncio.sleep(300)  # Listen for 5 minutes

    def handle_temperature(old_temp: float, new_temp: float):
        """Called when temperature changes."""
        print(f"Temperature changed: {old_temp}°F → {new_temp}°F")

    def handle_error(error_code: str, status):
        """Called when error is detected."""
        print(f"Error detected: {error_code}")

    asyncio.run(main())

Available Events
================

The MQTT client automatically emits the following events:

Status Events
-------------

.. list-table::
   :header-rows: 1
   :widths: 30 40 30

   * - Event Name
     - Arguments
     - Description
   * - ``status_received``
     - ``(status: DeviceStatus)``
     - Raw status update from device
   * - ``temperature_changed``
     - ``(old: float, new: float)``
     - DHW temperature changed
   * - ``mode_changed``
     - ``(old: int, new: int)``
     - Operation mode changed
   * - ``power_changed``
     - ``(old: float, new: float)``
     - Power consumption changed
   * - ``heating_started``
     - ``(status: DeviceStatus)``
     - Device started heating
   * - ``heating_stopped``
     - ``(status: DeviceStatus)``
     - Device stopped heating
   * - ``error_detected``
     - ``(code: str, status: DeviceStatus)``
     - Error code detected
   * - ``error_cleared``
     - ``(code: str)``
     - Error code cleared

Connection Events
-----------------

.. list-table::
   :header-rows: 1
   :widths: 30 40 30

   * - Event Name
     - Arguments
     - Description
   * - ``connection_interrupted``
     - ``(error)``
     - MQTT connection lost
   * - ``connection_resumed``
     - ``(return_code, session_present)``
     - MQTT connection restored

Feature Events
--------------

.. list-table::
   :header-rows: 1
   :widths: 30 40 30

   * - Event Name
     - Arguments
     - Description
   * - ``feature_received``
     - ``(feature: DeviceFeature)``
     - Device feature/info received

Usage Patterns
==============

Simple Handler
--------------

.. code-block:: python

    def on_temp_change(old_temp: float, new_temp: float):
        """Simple synchronous handler."""
        print(f"Temperature: {old_temp}°F → {new_temp}°F")

    mqtt_client.on('temperature_changed', on_temp_change)

Async Handler
-------------

.. code-block:: python

    async def save_to_database(old_temp: float, new_temp: float):
        """Async handler for I/O operations."""
        async with database.transaction():
            await database.insert_temperature(old_temp, new_temp)

    mqtt_client.on('temperature_changed', save_to_database)

Multiple Handlers
-----------------

.. code-block:: python

    # All handlers will be called in order
    mqtt_client.on('temperature_changed', log_temperature)
    mqtt_client.on('temperature_changed', update_ui)
    mqtt_client.on('temperature_changed', send_notification)

Priority-Based Execution
------------------------

Higher priority handlers execute first (default priority is 50):

.. code-block:: python

    # Critical operations (execute first)
    mqtt_client.on('error_detected', emergency_shutdown, priority=100)
    
    # Normal operations (execute second)
    mqtt_client.on('error_detected', log_error, priority=50)
    
    # Low priority operations (execute last)
    mqtt_client.on('error_detected', send_notification, priority=10)

One-Time Handlers
-----------------

.. code-block:: python

    def initialize_device(status):
        """Called only once, then automatically removed."""
        print(f"Device initialized at {status.dhwTemperature}°F")

    mqtt_client.once('status_received', initialize_device)

Dynamic Handler Management
--------------------------

.. code-block:: python

    # Add handler
    mqtt_client.on('temperature_changed', handler)
    
    # Remove specific handler
    mqtt_client.off('temperature_changed', handler)
    
    # Remove all handlers for an event
    mqtt_client.off('temperature_changed')
    
    # Check how many handlers are registered
    count = mqtt_client.listener_count('temperature_changed')
    print(f"Handlers registered: {count}")

Wait for Event
--------------

.. code-block:: python

    # Wait for a specific event
    await mqtt_client.wait_for('device_ready', timeout=30)
    
    # Wait and capture event arguments
    old_temp, new_temp = await mqtt_client.wait_for('temperature_changed')
    print(f"Temperature changed to {new_temp}°F")

Integration Examples
====================

Home Assistant Integration
---------------------------

.. code-block:: python

    async def sync_to_homeassistant(old_temp: float, new_temp: float):
        """Sync temperature changes to Home Assistant."""
        await hass.states.async_set(
            'sensor.water_heater_temperature',
            new_temp,
            {
                'unit_of_measurement': '°F',
                'previous_value': old_temp,
                'device_class': 'temperature'
            }
        )

    mqtt_client.on('temperature_changed', sync_to_homeassistant)

Database Logging
----------------

.. code-block:: python

    async def log_all_status_updates(status):
        """Log every status update to database."""
        await db.execute('''
            INSERT INTO device_status (
                timestamp, temperature, mode, power, heating
            ) VALUES (?, ?, ?, ?, ?)
        ''', (
            datetime.now(),
            status.dhwTemperature,
            status.dhwOperationSetting,
            status.currentInstPower,
            status.compUse or status.heatUpperUse or status.heatLowerUse
        ))

    mqtt_client.on('status_received', log_all_status_updates, priority=10)

Alert System
------------

.. code-block:: python

    def send_critical_alert(error_code: str, status):
        """Send push notification for critical errors."""
        if error_code in ['E001', 'E002', 'E003']:
            push_service.send(
                title="Water Heater Critical Error",
                message=f"Error code {error_code} requires attention",
                priority="high"
            )

    mqtt_client.on('error_detected', send_critical_alert, priority=100)

Statistics Tracking
-------------------

.. code-block:: python

    class DeviceStatistics:
        def __init__(self):
            self.heating_cycles = 0
            self.total_heating_time = 0
            self.heating_start_time = None
        
        def on_heating_started(self, status):
            """Track when heating starts."""
            self.heating_start_time = datetime.now()
            self.heating_cycles += 1
        
        def on_heating_stopped(self, status):
            """Calculate heating duration."""
            if self.heating_start_time:
                duration = (datetime.now() - self.heating_start_time).total_seconds()
                self.total_heating_time += duration
                self.heating_start_time = None
        
        def get_average_cycle_time(self):
            """Calculate average heating cycle duration."""
            if self.heating_cycles == 0:
                return 0
            return self.total_heating_time / self.heating_cycles

    stats = DeviceStatistics()
    mqtt_client.on('heating_started', stats.on_heating_started)
    mqtt_client.on('heating_stopped', stats.on_heating_stopped)

API Reference
=============

EventEmitter Methods
--------------------

The ``NavienMqttClient`` inherits from ``EventEmitter`` and provides these methods:

on(event, callback, priority=50)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Register an event listener.

:param event: Event name to listen for
:type event: str
:param callback: Function to call when event is emitted (can be sync or async)
:type callback: Callable
:param priority: Execution priority (higher values execute first, default: 50)
:type priority: int
:return: None

.. code-block:: python

    mqtt_client.on('temperature_changed', handle_temp_change)
    mqtt_client.on('error_detected', critical_handler, priority=100)

once(event, callback, priority=50)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Register a one-time event listener that automatically removes itself after first execution.

:param event: Event name to listen for
:type event: str
:param callback: Function to call when event is emitted
:type callback: Callable
:param priority: Execution priority (default: 50)
:type priority: int
:return: None

.. code-block:: python

    mqtt_client.once('device_ready', initialize)

off(event, callback=None)
^^^^^^^^^^^^^^^^^^^^^^^^^^

Remove event listener(s).

:param event: Event name
:type event: str
:param callback: Specific callback to remove, or None to remove all for event
:type callback: Optional[Callable]
:return: Number of listeners removed
:rtype: int

.. code-block:: python

    # Remove specific listener
    mqtt_client.off('temperature_changed', handler)
    
    # Remove all listeners for event
    mqtt_client.off('temperature_changed')

emit(event, \*args, \*\*kwargs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Emit an event to all registered listeners (async method).

:param event: Event name to emit
:type event: str
:param args: Positional arguments to pass to listeners
:param kwargs: Keyword arguments to pass to listeners
:return: Number of listeners that were called
:rtype: int

.. note::
   This method is called automatically by the MQTT client. You typically don't need to call it directly.

.. code-block:: python

    # Usually called internally, but you can emit custom events
    await mqtt_client.emit('custom_event', data1, data2)

wait_for(event, timeout=None)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Wait for an event to be emitted (async method).

:param event: Event name to wait for
:type event: str
:param timeout: Maximum time to wait in seconds (None = wait forever)
:type timeout: Optional[float]
:return: Tuple of arguments passed to the event
:rtype: tuple
:raises asyncio.TimeoutError: If timeout is reached

.. code-block:: python

    # Wait for device to be ready
    await mqtt_client.wait_for('device_ready', timeout=30)
    
    # Wait and capture event data
    old_temp, new_temp = await mqtt_client.wait_for('temperature_changed')

listener_count(event)
^^^^^^^^^^^^^^^^^^^^^

Get the number of listeners registered for an event.

:param event: Event name
:type event: str
:return: Number of registered listeners
:rtype: int

.. code-block:: python

    count = mqtt_client.listener_count('temperature_changed')
    print(f"Handlers registered: {count}")

event_count(event)
^^^^^^^^^^^^^^^^^^

Get the number of times an event has been emitted.

:param event: Event name
:type event: str
:return: Number of times event was emitted
:rtype: int

.. code-block:: python

    count = mqtt_client.event_count('temperature_changed')
    print(f"Event emitted {count} times")

event_names()
^^^^^^^^^^^^^

Get list of all registered event names.

:return: List of event names with active listeners
:rtype: list[str]

.. code-block:: python

    events = mqtt_client.event_names()
    print(f"Active events: {', '.join(events)}")

remove_all_listeners(event=None)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Remove all listeners for specific event or all events.

:param event: Event name, or None to remove all listeners
:type event: Optional[str]
:return: Number of listeners removed
:rtype: int

.. code-block:: python

    # Remove all listeners for one event
    mqtt_client.remove_all_listeners('temperature_changed')
    
    # Remove ALL listeners
    mqtt_client.remove_all_listeners()

Best Practices
==============

Do's
-----

- **Register handlers before connecting** - Set up event handlers before calling ``connect()``
- **Use priority for critical operations** - High priority (>50) for safety/shutdown logic
- **Keep handlers lightweight** - Event handlers should be fast; delegate heavy work
- **Use async for I/O** - Use async handlers for database, network, or file operations
- **Remove handlers when done** - Clean up handlers to prevent memory leaks
- **Check event counts for debugging** - Use ``listener_count()`` and ``event_count()`` to debug

.. code-block:: python

    # Good practice
    mqtt_client.on('error_detected', emergency_shutdown, priority=100)
    mqtt_client.on('temperature_changed', async_db_save)
    await mqtt_client.connect()

Don'ts
-------

- **Don't block in sync handlers** - Avoid ``time.sleep()`` or long computations
- **Don't register from MQTT threads** - Always register from main thread
- **Don't raise uncaught exceptions** - Exceptions are logged but break the handler
- **Don't register duplicates** - Check if handler is already registered
- **Don't forget to subscribe** - Must call ``subscribe_device_status()`` to receive events

.. code-block:: python

    # Bad practice
    def bad_handler(old, new):
        time.sleep(10)  # Blocks event loop!
        raise Exception()  # Breaks handler execution

Troubleshooting
===============

Handler Not Being Called
-------------------------

**Check 1: Is the handler registered?**

.. code-block:: python

    count = mqtt_client.listener_count('temperature_changed')
    if count == 0:
        print("No handlers registered!")

**Check 2: Are you subscribed to device updates?**

.. code-block:: python

    # Must subscribe to receive events
    await mqtt_client.subscribe_device_status(device, lambda s: None)

**Check 3: Is the event being emitted?**

.. code-block:: python

    emissions = mqtt_client.event_count('temperature_changed')
    print(f"Event emitted {emissions} times")

"No Running Event Loop" Error
------------------------------

This error occurs when trying to emit events before ``connect()`` is called.

**Solution:**

.. code-block:: python

    # Correct order
    mqtt_client = NavienMqttClient(auth_client)
    await mqtt_client.connect()  # This captures the event loop
    mqtt_client.on('temperature_changed', handler)
    await mqtt_client.subscribe_device_status(device, callback)

Events Firing Multiple Times
-----------------------------

This usually happens when subscribing to the same device multiple times.

**Solution:**

.. code-block:: python

    # Subscribe only once
    await mqtt_client.subscribe_device_status(device, callback)
    
    # Or use once() for one-time handlers
    mqtt_client.once('temperature_changed', handler)

Enable Debug Logging
--------------------

.. code-block:: python

    import logging
    
    # Enable debug logging
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger('nwp500.events').setLevel(logging.DEBUG)
    logging.getLogger('nwp500.mqtt_client').setLevel(logging.DEBUG)

Trace All Events
----------------

.. code-block:: python

    def trace_all_events(event_name):
        """Create a tracer for an event."""
        def tracer(*args, **kwargs):
            print(f"[{event_name}] args={args}, kwargs={kwargs}")
        return tracer

    # Trace specific events
    for event in ['status_received', 'temperature_changed', 'error_detected']:
        mqtt_client.on(event, trace_all_events(event))

Technical Details
=================

Thread Safety
-------------

The event emitter implementation is thread-safe:

- MQTT callbacks run in separate threads (e.g., 'Dummy-1')
- Event handlers always execute in the main event loop
- Thread-safe scheduling via ``asyncio.run_coroutine_threadsafe()``
- The event loop reference is captured during ``connect()``

State Change Detection
----------------------

The MQTT client automatically detects state changes by comparing the current device status with the previous status. Events are only emitted when values actually change:

.. code-block:: python

    # Temperature change detection (internal)
    if status.dhwTemperature != prev.dhwTemperature:
        await self.emit('temperature_changed', 
                       prev.dhwTemperature, 
                       status.dhwTemperature)

Error Handling
--------------

Errors in event handlers are isolated and logged but don't affect other handlers:

.. code-block:: python

    # Even if handler1 raises an exception, handler2 still executes
    mqtt_client.on('temperature_changed', handler1)  # May raise exception
    mqtt_client.on('temperature_changed', handler2)  # Still executes

Performance
-----------

- **Event emission:** O(n) where n = number of listeners
- **Listener registration:** O(n log n) due to priority sorting
- **Memory overhead:** ~100 bytes per registered listener
- **No performance impact** when events are not used

Backward Compatibility
======================

The event emitter pattern is **fully backward compatible** with existing code:

.. code-block:: python

    # Traditional callback pattern (still works)
    async def on_status(status: DeviceStatus):
        print(f"Temperature: {status.dhwTemperature}°F")

    await mqtt_client.subscribe_device_status(device, on_status)

    # New event emitter pattern (works alongside)
    mqtt_client.on('temperature_changed', handle_temp_change)

Both patterns can be used simultaneously in the same application.

See Also
========

- :doc:`MQTT_CLIENT` - MQTT client documentation
- :doc:`DEVICE_STATUS_FIELDS` - Complete status field reference
- :doc:`API_CLIENT` - REST API client
- :doc:`AUTHENTICATION` - Authentication and tokens

Example Code
============

Complete working examples can be found in the ``examples/`` directory:

- ``examples/event_emitter_demo.py`` - Comprehensive event emitter demonstration

For unit tests and additional usage patterns, see:

- ``tests/test_events.py`` - Event emitter unit tests

.. note::
   This feature is part of Phase 1 of the event emitter implementation. Future phases may add additional features like event filtering, wildcards, and event history.
