Event Emitter Quick Reference
=============================

Quick Start
-----------

.. code:: python

   from nwp500 import NavienAuthClient, NavienMqttClient

   # 1. Authenticate and connect
   async with NavienAuthClient("email", "password") as auth_client:
       mqtt_client = NavienMqttClient(auth_client)
       await mqtt_client.connect()
       
       # 2. Register event handlers
       mqtt_client.on('temperature_changed', handle_temp_change)
       mqtt_client.on('error_detected', handle_error)
       
       # 3. Subscribe to device updates
       await mqtt_client.subscribe_device_status(device, lambda s: None)
       
       # Events will now fire automatically!

Available Events
----------------

+----------------------------+---------------------------------------+-----------------------------+
| Event                      | Arguments                             | Description                 |
+============================+=======================================+=============================+
| ``status_received``        | ``(status: DeviceStatus)``            | Raw status update           |
+----------------------------+---------------------------------------+-----------------------------+
| ``feature_received``       | ``(feature: DeviceFeature)``          | Device info update          |
+----------------------------+---------------------------------------+-----------------------------+
| ``temperature_changed``    | ``(old: float, new: float)``          | Temperature changed         |
+----------------------------+---------------------------------------+-----------------------------+
| ``mode_changed``           | ``(old: int, new: int)``              | Operation mode changed      |
+----------------------------+---------------------------------------+-----------------------------+
| ``power_changed``          | ``(old: float, new: float)``          | Power consumption changed   |
+----------------------------+---------------------------------------+-----------------------------+
| ``heating_started``        | ``(status: DeviceStatus)``            | Heating began               |
+----------------------------+---------------------------------------+-----------------------------+
| ``heating_stopped``        | ``(status: DeviceStatus)``            | Heating stopped             |
+----------------------------+---------------------------------------+-----------------------------+
| ``error_detected``         | ``(code: str, status: DeviceStatus)`` | Error occurred              |
+----------------------------+---------------------------------------+-----------------------------+
| ``error_cleared``          | ``(code: str)``                       | Error resolved              |
+----------------------------+---------------------------------------+-----------------------------+
| ``connection_interrupted`` | ``(error)``                           | Connection lost             |
+----------------------------+---------------------------------------+-----------------------------+
| ``connection_resumed``     | ``(return_code, session_present)``    | Connection restored         |
+----------------------------+---------------------------------------+-----------------------------+

Common Patterns
---------------

Simple Handler
~~~~~~~~~~~~~~

.. code:: python

   def on_temp_change(old_temp, new_temp):
       print(f"Temperature: {old_temp}°F → {new_temp}°F")

   mqtt_client.on('temperature_changed', on_temp_change)

Async Handler
~~~~~~~~~~~~~

.. code:: python

   async def save_to_db(old_temp, new_temp):
       await db.execute("INSERT INTO temps VALUES (?, ?)", (old_temp, new_temp))

   mqtt_client.on('temperature_changed', save_to_db)

Multiple Handlers
~~~~~~~~~~~~~~~~~

.. code:: python

   mqtt_client.on('temperature_changed', log_temperature)
   mqtt_client.on('temperature_changed', update_ui)
   mqtt_client.on('temperature_changed', send_notification)
   # All three will be called in order

One-Time Handler
~~~~~~~~~~~~~~~~

.. code:: python

   mqtt_client.once('device_ready', initialize)
   # Runs once, then auto-removes

Priority Handlers
~~~~~~~~~~~~~~~~~

.. code:: python

   mqtt_client.on('error_detected', emergency_shutdown, priority=100)  # Runs first
   mqtt_client.on('error_detected', log_error, priority=50)            # Runs second
   mqtt_client.on('error_detected', send_alert, priority=10)           # Runs last

Remove Handler
~~~~~~~~~~~~~~

.. code:: python

   mqtt_client.off('temperature_changed', handler)  # Remove specific
   mqtt_client.off('temperature_changed')           # Remove all

API Methods
-----------

Registration
~~~~~~~~~~~~

- ``on(event, callback, priority=50)`` - Register handler
- ``once(event, callback, priority=50)`` - Register one-time handler
- ``off(event, callback=None)`` - Remove handler(s)

Inspection
~~~~~~~~~~

- ``listener_count(event)`` - Count handlers for event
- ``event_count(event)`` - Count times event was emitted
- ``event_names()`` - List all active events
- ``remove_all_listeners(event=None)`` - Clear handlers

Async Operations
~~~~~~~~~~~~~~~~

- ``emit(event, *args, **kwargs)`` - Emit event (async)
- ``wait_for(event, timeout=None)`` - Wait for event (async)

Examples by Use Case
--------------------

Home Automation
~~~~~~~~~~~~~~~

.. code:: python

   async def sync_to_homeassistant(old_temp, new_temp):
       await hass.states.async_set('sensor.water_heater', new_temp)

   mqtt_client.on('temperature_changed', sync_to_homeassistant)

Monitoring & Alerts
~~~~~~~~~~~~~~~~~~~

.. code:: python

   def check_temperature(old_temp, new_temp):
       if new_temp > 140:
           send_alert("Water heater temperature too high!")

   mqtt_client.on('temperature_changed', check_temperature)

Data Logging
~~~~~~~~~~~~

.. code:: python

   async def log_status(status: DeviceStatus):
       await db.log(temperature=status.dhwTemperature,
                    mode=status.dhwOperationSetting,
                    power=status.currentInstPower)

   mqtt_client.on('status_received', log_status)

Error Handling
~~~~~~~~~~~~~~

.. code:: python

   def handle_error(error_code: str, status: DeviceStatus):
       if error_code == "E001":
           # Critical error
           mqtt_client.set_power(device, False)
       else:
           # Log and notify
           logger.error(f"Error {error_code}")

   mqtt_client.on('error_detected', handle_error, priority=100)

Statistics Tracking
~~~~~~~~~~~~~~~~~~~

.. code:: python

   class Stats:
       def __init__(self):
           self.temp_changes = 0
           self.heating_cycles = 0
       
       def on_temp_change(self, old, new):
           self.temp_changes += 1
       
       def on_heating_start(self, status):
           self.heating_cycles += 1

   stats = Stats()
   mqtt_client.on('temperature_changed', stats.on_temp_change)
   mqtt_client.on('heating_started', stats.on_heating_start)

Debugging
---------

Check Handler Registration
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   count = mqtt_client.listener_count('temperature_changed')
   print(f"Handlers registered: {count}")

Check Event Emissions
~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   emissions = mqtt_client.event_count('temperature_changed')
   print(f"Event fired {emissions} times")

List Active Events
~~~~~~~~~~~~~~~~~~

.. code:: python

   events = mqtt_client.event_names()
   print(f"Active events: {events}")

Enable Debug Logging
~~~~~~~~~~~~~~~~~~~~

.. code:: python

   import logging
   logging.basicConfig(level=logging.DEBUG)
   logging.getLogger('nwp500.events').setLevel(logging.DEBUG)

Trace All Events
~~~~~~~~~~~~~~~~

.. code:: python

   def trace_event(event_name):
       def handler(*args, **kwargs):
           print(f"[{event_name}] {args}")
       return handler

   for event in mqtt_client.event_names():
       mqtt_client.on(event, trace_event(event))

Best Practices
--------------

✅ Do This
~~~~~~~~~~

.. code:: python

   # Register handlers before connecting
   mqtt_client.on('temperature_changed', handler)
   await mqtt_client.connect()

   # Use async for I/O operations
   async def handler(old, new):
       await db.save(old, new)

   # Use priority for critical handlers
   mqtt_client.on('error_detected', shutdown, priority=100)

   # Remove handlers when done
   mqtt_client.off('temperature_changed', handler)

❌ Don’t Do This
~~~~~~~~~~~~~~~~

.. code:: python

   # Don't block in sync handlers
   def bad_handler(old, new):
       time.sleep(10)  # Blocks event loop!

   # Don't raise uncaught exceptions
   def bad_handler(old, new):
       raise Exception()  # Logged, but not good practice

   # Don't register same handler twice
   mqtt_client.on('temp_changed', handler)
   mqtt_client.on('temp_changed', handler)  # Duplicate!

Common Issues
-------------

Handler Not Called
~~~~~~~~~~~~~~~~~~

.. code:: python

   # Check: Are you subscribed to device updates?
   await mqtt_client.subscribe_device_status(device, lambda s: None)

   # Check: Is handler registered?
   print(mqtt_client.listener_count('temperature_changed'))

   # Check: Is event being emitted?
   print(mqtt_client.event_count('temperature_changed'))

“No running event loop” Error
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   # Make sure connect() is called first
   await mqtt_client.connect()  # This captures the event loop

   # Then register handlers and subscribe
   mqtt_client.on('temperature_changed', handler)
   await mqtt_client.subscribe_device_status(device, callback)

Multiple Emissions
~~~~~~~~~~~~~~~~~~

.. code:: python

   # Don't subscribe multiple times
   await mqtt_client.subscribe_device_status(device, callback)  # Once only!

   # Or use once() for one-time handlers
   mqtt_client.once('temperature_changed', handler)

Performance Tips
----------------

Batch Processing
~~~~~~~~~~~~~~~~

.. code:: python

   class BatchHandler:
       def __init__(self):
           self.buffer = []
       
       def on_status(self, status):
           self.buffer.append(status)
           if len(self.buffer) >= 10:
               self.process_batch()
       
       def process_batch(self):
           # Process all at once
           self.buffer.clear()

Selective Listening
~~~~~~~~~~~~~~~~~~~

.. code:: python

   # Only listen to what you need
   mqtt_client.on('temperature_changed', handler)  # Specific event
   # Instead of:
   mqtt_client.on('status_received', handler)      # All status updates

Handler Cleanup
~~~~~~~~~~~~~~~

.. code:: python

   # Remove handlers when done
   def cleanup():
       mqtt_client.off('temperature_changed', temp_handler)
       mqtt_client.off('error_detected', error_handler)

See Also
--------

- **EVENT_EMITTER_PHASE1_COMPLETE.md** - Complete feature documentation
- **EVENT_ARCHITECTURE.md** - Technical architecture details
- **examples/event_emitter_demo.py** - Working examples
- **tests/test_events.py** - Test cases and usage patterns

--------------

| **Version:** 1.0
| **Last Updated:** January 2025
| **Status:** Production Ready
