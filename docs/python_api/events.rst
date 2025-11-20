============
Event System
============

The ``nwp500.events`` module provides an event-driven architecture for
reacting to device state changes, errors, and system events.

Overview
========

The MQTT client uses an EventEmitter pattern that allows you to:

* Subscribe to specific events with callback functions
* React to device state changes in real-time
* Handle connection events (interruption, resumption)
* Monitor errors and diagnostics
* Build reactive, event-driven applications

All events are emitted asynchronously and callbacks are invoked with
relevant data.

EventEmitter
============

Base class for event-driven components.

.. py:class:: EventEmitter

   Provides event subscription and emission capabilities.

   **Methods:**

   .. py:method:: on(event, callback)

      Register a callback for an event.

      :param event: Event name
      :type event: str
      :param callback: Function to call when event fires
      :type callback: Callable

   .. py:method:: off(event, callback=None)

      Unregister callback(s) for an event.

      :param event: Event name
      :type event: str
      :param callback: Specific callback to remove, or None for all
      :type callback: Callable or None

   .. py:method:: emit(event, *args, **kwargs)

      Emit an event to all registered callbacks.

      :param event: Event name
      :type event: str
      :param args: Positional arguments for callbacks
      :param kwargs: Keyword arguments for callbacks

MQTT Client Events
==================

The :doc:`mqtt_client` emits the following events:

Connection Events
-----------------

connection_interrupted
^^^^^^^^^^^^^^^^^^^^^^

Emitted when MQTT connection is lost.

**Callback signature:**

.. code-block:: python

   def on_interrupted(error):
       """
       :param error: Error that caused interruption
       :type error: Exception
       """

**Example:**

.. code-block:: python

   def handle_disconnect(error):
       print(f"Connection lost: {error}")
       # Save state, notify user, etc.

   mqtt.on('connection_interrupted', handle_disconnect)

connection_resumed
^^^^^^^^^^^^^^^^^^

Emitted when MQTT connection is restored.

**Callback signature:**

.. code-block:: python

   def on_resumed(return_code, session_present):
       """
       :param return_code: MQTT return code
       :type return_code: int
       :param session_present: Whether session was resumed
       :type session_present: bool
       """

**Example:**

.. code-block:: python

   def handle_reconnect(return_code, session_present):
       print("Connection restored")
       # Re-request status, resume operations
       await mqtt.request_device_status(device)

   mqtt.on('connection_resumed', handle_reconnect)

Device Events
-------------

status_received
^^^^^^^^^^^^^^^

Emitted when device status update is received.

**Callback signature:**

.. code-block:: python

   def on_status(status):
       """
       :param status: Device status object
       :type status: DeviceStatus
       """

**Example:**

.. code-block:: python

   def handle_status(status):
       print(f"Temperature: {status.dhw_temperature}°F")
       print(f"Power: {status.current_inst_power}W")

   mqtt.on('status_received', handle_status)

feature_received
^^^^^^^^^^^^^^^^

Emitted when device feature/info update is received.

**Callback signature:**

.. code-block:: python

   def on_feature(feature):
       """
       :param feature: Device feature object
       :type feature: DeviceFeature
       """

temperature_changed
^^^^^^^^^^^^^^^^^^^

Emitted when water temperature changes significantly.

**Callback signature:**

.. code-block:: python

   def on_temp_change(old_temp, new_temp):
       """
       :param old_temp: Previous temperature
       :type old_temp: float
       :param new_temp: Current temperature
       :type new_temp: float
       """

mode_changed
^^^^^^^^^^^^

Emitted when operation mode changes.

**Callback signature:**

.. code-block:: python

   def on_mode_change(old_mode, new_mode):
       """
       :param old_mode: Previous mode
       :type old_mode: DhwOperationSetting
       :param new_mode: Current mode
       :type new_mode: DhwOperationSetting
       """

error_detected
^^^^^^^^^^^^^^

Emitted when device reports an error code.

**Callback signature:**

.. code-block:: python

   def on_error(error_code, sub_error_code):
       """
       :param error_code: Main error code
       :type error_code: int
       :param sub_error_code: Sub-error code
       :type sub_error_code: int
       """

Examples
========

Example 1: Basic Event Handling
--------------------------------

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienMqttClient

   async def main():
       async with NavienAuthClient(email, password) as auth:
           mqtt = NavienMqttClient(auth)

           # Register event handlers
           mqtt.on('status_received', lambda s: print(f"Temp: {s.dhwTemperature}°F"))
           mqtt.on('error_detected', lambda e, se: print(f"Error: {e}"))

           await mqtt.connect()
           # Events will be emitted automatically
           await asyncio.sleep(300)

Example 2: Connection Monitoring
---------------------------------

.. code-block:: python

   async def monitor_connection():
       async with NavienAuthClient(email, password) as auth:
           mqtt = NavienMqttClient(auth)

           def on_disconnected(error):
               print(f"Lost connection: {error}")
               # Alert user, save state

           def on_reconnected(rc, session):
               print("Connection restored!")
               # Resume operations

           mqtt.on('connection_interrupted', on_disconnected)
           mqtt.on('connection_resumed', on_reconnected)

           await mqtt.connect()
           await asyncio.sleep(86400)  # Monitor for 24h

Example 3: Temperature Alerts
------------------------------

.. code-block:: python

   async def temperature_alerts():
       async with NavienAuthClient(email, password) as auth:
           mqtt = NavienMqttClient(auth)

           def check_temp(status):
               if status.dhw_temperature < 110:
                   print("WARNING: Temperature below 110°F")
                   send_alert("Low water temperature")

               if status.dhw_temperature > 145:
                   print("WARNING: Temperature above 145°F")
                   send_alert("High water temperature")

           mqtt.on('status_received', check_temp)

           await mqtt.connect()
           await mqtt.subscribe_device_status(device, lambda s: None)
           await mqtt.start_periodic_requests(device, period_seconds=60)

           await asyncio.sleep(86400)

Example 4: Multiple Event Handlers
-----------------------------------

.. code-block:: python

   async def multi_handler():
       async with NavienAuthClient(email, password) as auth:
           mqtt = NavienMqttClient(auth)

           # Log all status updates
           mqtt.on('status_received', lambda s: log_status(s))

           # Track temperature
           mqtt.on('temperature_changed', lambda old, new: 
                   print(f"Temp: {old}°F → {new}°F"))

           # Monitor mode changes
           mqtt.on('mode_changed', lambda old, new:
                   print(f"Mode: {old.name} → {new.name}"))

           # Alert on errors
           mqtt.on('error_detected', lambda e, se:
                   send_alert(f"Error: {e}:{se}"))

           await mqtt.connect()
           # All handlers will be called automatically

Best Practices
==============

1. **Register handlers before connecting:**

   .. code-block:: python

      # GOOD: Register first
      mqtt.on('status_received', handler)
      await mqtt.connect()

      # BAD: May miss early events
      await mqtt.connect()
      mqtt.on('status_received', handler)

2. **Use lambda for simple handlers:**

   .. code-block:: python

      mqtt.on('status_received', lambda s: print(f"{s.dhwTemperature}°F"))

3. **Use named functions for complex handlers:**

   .. code-block:: python

      def complex_handler(status):
          # Complex logic
          process_status(status)
          update_database(status)
          check_alerts(status)

      mqtt.on('status_received', complex_handler)

4. **Clean up handlers when done:**

   .. code-block:: python

      mqtt.off('status_received', handler)  # Remove specific
      mqtt.off('status_received')           # Remove all

Related Documentation
=====================

* :doc:`mqtt_client` - MQTT client with events
* :doc:`models` - Data models passed to event handlers
* :doc:`exceptions` - Exception handling
