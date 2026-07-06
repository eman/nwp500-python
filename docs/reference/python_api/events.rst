Event System
============

The MQTT client exposes two complementary callback patterns:

* ``subscribe_*()`` methods parse device messages and call your callback with a
  model object such as :class:`~nwp500.models.DeviceStatus` or
  :class:`~nwp500.models.ReservationSchedule`.
* :meth:`nwp500.events.EventEmitter.on` listens for higher-level client events
  from :class:`nwp500.mqtt_events.MqttClientEvents`. These callbacks always
  receive **one typed event dataclass**.

Overview
========

Use the event system when you want to react to connection changes, status
transitions, or derived state changes such as temperature deltas and error
conditions.

How the pieces fit together
---------------------------

The event system is split across two complementary modules:

* :mod:`nwp500.events` provides the delivery **mechanism** — the generic
  :class:`~nwp500.events.EventEmitter` (multiple listeners, async handlers,
  one-time listeners, priority ordering). ``NavienMqttClient`` extends it.
* :mod:`nwp500.mqtt_events` provides the **vocabulary** — the
  :class:`~nwp500.mqtt_events.MqttClientEvents` name registry and the typed,
  frozen dataclass payloads carried by each event.

These are not two competing systems. Internal ``emit`` call sites reference the
``MqttClientEvents`` constants and emit the matching payload dataclass, and you
subscribe with the same constants, so an event name is defined in exactly one
place.

Two Subscription Patterns
=========================

Typed device subscriptions
--------------------------

These methods deliver parsed model objects directly to the callback.

.. code-block:: python

   def on_status(status):
       print(status.dhw_temperature)
       print(status.current_inst_power)

   await mqtt.subscribe_device_status(device, on_status)
   await mqtt.request_device_status(device)

Examples include:

* :meth:`nwp500.mqtt.client.NavienMqttClient.subscribe_device_status`
* :meth:`nwp500.mqtt.client.NavienMqttClient.subscribe_device_feature`
* :meth:`nwp500.mqtt.client.NavienMqttClient.subscribe_energy_usage`
* :meth:`nwp500.mqtt.client.NavienMqttClient.subscribe_reservation_response`
* :meth:`nwp500.mqtt.client.NavienMqttClient.subscribe_weekly_reservation_response`
* :meth:`nwp500.mqtt.client.NavienMqttClient.subscribe_recirculation_schedule_response`

Client event subscriptions
--------------------------

Event emitter callbacks receive a single event object.

.. code-block:: python

   from nwp500 import MqttClientEvents

   def on_status_event(event):
       print(event.status.dhw_temperature)

   def on_resumed(event):
       print(event.return_code)
       print(event.session_present)

   mqtt.on(MqttClientEvents.STATUS_RECEIVED, on_status_event)
   mqtt.on(MqttClientEvents.CONNECTION_RESUMED, on_resumed)

EventEmitter API
================

.. py:class:: EventEmitter

   Base class for event-driven components.

   .. py:method:: on(event, callback)

      Register a callback for an event name.

   .. py:method:: off(event, callback=None)

      Remove one callback or all callbacks for an event.

   .. py:method:: wait_for(event, timeout=None)

      Wait for the next event emission and return the positional event
      arguments as a tuple.

      .. code-block:: python

         args = await mqtt.wait_for(MqttClientEvents.CONNECTION_RESUMED, timeout=30)
         resumed = args[0]
         print(resumed.session_present)

MQTT Client Events
==================

The :class:`nwp500.mqtt_events.MqttClientEvents` registry exposes all supported
client event names with IDE-friendly constants.

.. code-block:: python

   from nwp500 import MqttClientEvents

   for event_name in MqttClientEvents.get_all_events():
       print(event_name)

ConnectionInterruptedEvent
--------------------------

.. py:class:: nwp500.mqtt_events.ConnectionInterruptedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.CONNECTION_INTERRUPTED`.

   **Fields:**

   * ``error`` (:class:`Exception`) - The exception that interrupted the MQTT
     connection.

   **Example:**

   .. code-block:: python

      def on_interrupted(event):
          print(f"Connection lost: {event.error}")

      mqtt.on(MqttClientEvents.CONNECTION_INTERRUPTED, on_interrupted)

ConnectionResumedEvent
----------------------

.. py:class:: nwp500.mqtt_events.ConnectionResumedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.CONNECTION_RESUMED`.

   **Fields:**

   * ``return_code`` (int) - MQTT return code from the resume attempt.
   * ``session_present`` (bool) - Whether broker session state was preserved.

   **Example:**

   .. code-block:: python

      def on_resumed(event):
          if not event.session_present:
              print("Broker session was reset")

      mqtt.on(MqttClientEvents.CONNECTION_RESUMED, on_resumed)

StatusReceivedEvent
-------------------

.. py:class:: nwp500.mqtt_events.StatusReceivedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.STATUS_RECEIVED`.

   **Fields:**

   * ``status`` (:class:`~nwp500.models.DeviceStatus`) - Parsed device status.

TemperatureChangedEvent
-----------------------

.. py:class:: nwp500.mqtt_events.TemperatureChangedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.TEMPERATURE_CHANGED`.

   **Fields:**

   * ``old_temperature`` (float) - Previous DHW temperature in the current unit system.
   * ``new_temperature`` (float) - New DHW temperature in the current unit system.

ModeChangedEvent
----------------

.. py:class:: nwp500.mqtt_events.ModeChangedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.MODE_CHANGED`.

   **Fields:**

   * ``old_mode`` (:class:`~nwp500.CurrentOperationMode`) - Previous operating mode.
   * ``new_mode`` (:class:`~nwp500.CurrentOperationMode`) - New operating mode.

PowerChangedEvent
-----------------

.. py:class:: nwp500.mqtt_events.PowerChangedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.POWER_CHANGED`.

   **Fields:**

   * ``old_power`` (float) - Previous instantaneous power draw in watts.
   * ``new_power`` (float) - New instantaneous power draw in watts.

HeatingStartedEvent
-------------------

.. py:class:: nwp500.mqtt_events.HeatingStartedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.HEATING_STARTED`.

   **Fields:**

   * ``status`` (:class:`~nwp500.models.DeviceStatus`) - Status snapshot when
     heating started.

HeatingStoppedEvent
-------------------

.. py:class:: nwp500.mqtt_events.HeatingStoppedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.HEATING_STOPPED`.

   **Fields:**

   * ``status`` (:class:`~nwp500.models.DeviceStatus`) - Status snapshot when
     heating stopped.

ErrorDetectedEvent
------------------

.. py:class:: nwp500.mqtt_events.ErrorDetectedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.ERROR_DETECTED`.

   **Fields:**

   * ``error_code`` (:class:`~nwp500.ErrorCode`) - Newly detected device error.
   * ``status`` (:class:`~nwp500.models.DeviceStatus`) - Status snapshot that
     contained the error.

ErrorClearedEvent
-----------------

.. py:class:: nwp500.mqtt_events.ErrorClearedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.ERROR_CLEARED`.

   **Fields:**

   * ``error_code`` (:class:`~nwp500.ErrorCode`) - Error code that cleared.

FeatureReceivedEvent
--------------------

.. py:class:: nwp500.mqtt_events.FeatureReceivedEvent

   Emitted for :attr:`nwp500.mqtt_events.MqttClientEvents.FEATURE_RECEIVED`.

   **Fields:**

   * ``feature`` (:class:`~nwp500.models.DeviceFeature`) - Parsed device feature payload.

Usage Examples
==============

React to typed event payloads
-----------------------------

.. code-block:: python

   from nwp500 import MqttClientEvents

   def on_temperature_changed(event):
       print(f"{event.old_temperature} -> {event.new_temperature}")

   def on_error(event):
       print(f"Error: {event.error_code}")
       print(f"Current mode: {event.status.operation_mode}")

   mqtt.on(MqttClientEvents.TEMPERATURE_CHANGED, on_temperature_changed)
   mqtt.on(MqttClientEvents.ERROR_DETECTED, on_error)

Wait for a connection event
---------------------------

.. code-block:: python

   args = await mqtt.wait_for(MqttClientEvents.CONNECTION_RESUMED, timeout=30)
   resumed = args[0]
   print(resumed.return_code)

Related Documentation
=====================

* :doc:`mqtt_client` - MQTT client API reference
* :doc:`models` - Models used by subscription callbacks
* :doc:`../../how-to/monitor-status` - Event-driven programming guide
