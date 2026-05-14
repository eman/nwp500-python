==================
Device Maintenance
==================

Maintenance commands let you handle firmware updates, connectivity recovery,
freeze protection, and onboard diagnostics from MQTT.

.. contents:: On This Page
   :local:
   :depth: 2

Before You Start
================

Many maintenance operations are device-specific. Request device features first so
you can inspect capability flags and supported temperature ranges.

.. code-block:: python

   await mqtt.subscribe_device_feature(device, lambda feature: print(feature))
   await mqtt.request_device_info(device)

Firmware OTA Updates
====================

Use firmware OTA when the device has already downloaded or advertised an update.
The workflow is asynchronous:

1. Call :meth:`nwp500.mqtt.client.NavienMqttClient.check_firmware_update`
2. Wait for the device's response on its control response topic
3. If an update is available, call
   :meth:`nwp500.mqtt.client.NavienMqttClient.commit_firmware_update`
   with an :class:`~nwp500.models.OtaCommitPayload`

.. warning::

   Committing firmware reboots the device. Heating and MQTT connectivity will be
   interrupted until the upgrade completes.

.. code-block:: python

   from nwp500 import OtaCommitPayload

   def on_message(topic, message):
       print(topic)
       print(message)

   await mqtt.subscribe_device(device, on_message)
   await mqtt.check_firmware_update(device)

   # After confirming the component code/version from the async response:
   payload = OtaCommitPayload(swCode=1, swVersion=1234)
   await mqtt.commit_firmware_update(device, payload)

WiFi Management
===============

Two commands cover WiFi recovery:

* :meth:`nwp500.mqtt.client.NavienMqttClient.reconnect_wifi` performs a soft
  reconnect using the currently stored credentials.
* :meth:`nwp500.mqtt.client.NavienMqttClient.reset_wifi` clears WiFi settings and
  returns the device to an unprovisioned state.

.. warning::

   ``reset_wifi()`` is effectively a factory reset for network settings. You will
   need to reconfigure the device in the Navien app afterward.

.. code-block:: python

   # Try this first when the device drops off WiFi
   await mqtt.reconnect_wifi(device)

   # Use only when credentials or provisioning are broken
   await mqtt.reset_wifi(device)

Freeze Protection
=================

Freeze protection is available on devices that expose the
``freeze_protection_use`` capability. The threshold is specified in the user's
preferred temperature unit and converted automatically.

The implementation documentation describes a typical supported range of
35-45 °F (about 1.7-7.2 °C). You can also inspect
``DeviceFeature.freeze_protection_temp_min`` and
``DeviceFeature.freeze_protection_temp_max`` after requesting device info.

.. code-block:: python

   # Fahrenheit example
   await mqtt.set_freeze_protection_temperature(device, 40.0)

Smart Diagnostics
=================

Smart diagnostics are available on devices that expose the
``smart_diagnostic_use`` capability. Triggering the diagnostic tells the device
to run its onboard self-check routine.

The result is reflected in the next
:class:`~nwp500.models.DeviceStatus` update via the ``smart_diagnostic`` field.

.. code-block:: python

   def on_status(status):
       print(f"Diagnostic status: {status.smart_diagnostic}")

   await mqtt.subscribe_device_status(device, on_status)
   await mqtt.run_smart_diagnostic(device)
   await mqtt.request_device_status(device)

Related Documentation
=====================

* :doc:`../reference/python_api/mqtt_client` - Full MQTT client API reference
* :doc:`schedule-operation` - Reservations, recirculation schedules, and intelligent scheduling
* :doc:`diagnose-mqtt` - Connection troubleshooting and diagnostics
