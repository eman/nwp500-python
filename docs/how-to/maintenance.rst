==================
Device Maintenance
==================

Maintenance commands cover firmware update information, the installer
diagnostics counters, air filter service intervals and fault resets. All
of them mirror what the NaviLink app sends; the CLI equivalents are noted
with each one.

.. contents:: On This Page
   :local:
   :depth: 2

Before You Start
================

Some maintenance operations are gated on device capabilities. Request
device features first so the client can inspect capability flags.

.. code-block:: python

   await mqtt.subscribe_device_feature(device, lambda feature: print(feature))
   await mqtt.request_device_info(device)

Installer Diagnostics
=====================

The NaviLink app's installer screen shows lifetime counters the device
keeps: heat pump and element energy, days since installation, fault
event counts, demand-response operation times, hot-water draw statistics
and component run times and start counts. The gate is in the app, so a
consumer account's unit answers the query.

.. code-block:: python

   from nwp500 import DeviceDiagnostics

   def on_diagnostics(diag: DeviceDiagnostics) -> None:
       ts, ta = diag.ts_data, diag.ta_data
       print(f"Installed {ts.days_since_installation} days ago")
       print(f"Heat pump: {ts.cumulated_pwr_hp} Wh over "
             f"{ta.cumulated_op_time_comp} h, {ta.cumulated_op_num_comp} starts")
       print(f"Condensate overflows: {ts.cumulated_occ_num_con_ovr_flow}")

   await mqtt.subscribe_diagnostics(device, on_diagnostics)
   await mqtt.request_diagnostics(device)

The two energies are watt-hours and ``cumulated_op_time_*`` values are
hours (both cross-checked against the energy query); the remaining
counters have no documented unit. See
:class:`~nwp500.models.DeviceDiagnostics` for every field.

CLI: ``nwp-cli diagnostics`` (add ``--json`` for the raw model).

Firmware Download Information
=============================

The device reports which firmware components it has downloaded for an
over-the-air update. A unit with nothing pending reports one all-zero
entry.

.. code-block:: python

   from nwp500 import FirmwareDownloadInfo

   def on_firmware(info: FirmwareDownloadInfo) -> None:
       for entry in info.download_sw_info:
           print(entry.component_name, entry.sw_version, entry.status)

   await mqtt.subscribe_firmware_download_info(device, on_firmware)
   await mqtt.request_firmware_download_info(device)

To apply a downloaded update, call
:meth:`nwp500.mqtt.client.NavienMqttClient.commit_firmware_update` with an
:class:`~nwp500.models.OtaCommitPayload` naming the component code and
version from the entry above.

.. warning::

   Committing firmware reboots the device. Heating and MQTT connectivity
   will be interrupted until the upgrade completes.

.. code-block:: python

   from nwp500 import OtaCommitPayload

   payload = OtaCommitPayload(swCode=1, swVersion=1234)
   await mqtt.commit_firmware_update(device, payload)

CLI: ``nwp-cli firmware info``.

Air Filter
==========

The air filter timer is reset after cleaning or replacing the filter. The
service interval is set in evaporator-fan hours: ``0`` disables the alarm,
otherwise 1000 to 10000 hours in 500-hour steps, which are the values the
NaviLink app offers. The device reports the interval back as
``DeviceStatus.air_filter_alarm_period``.

.. code-block:: python

   await mqtt.set_air_filter_life(device, 3000)
   await mqtt.reset_air_filter(device)

CLI: ``nwp-cli filter-life 3000`` and ``nwp-cli reset-filter``.

Condenser Fault Reset
=====================

Clears a condenser fault. The NaviLink app exposes this on its status
screen to installer accounts only; the gate is in the app. A consumer
account's unit acknowledges the command; the clearing effect could not be
observed because no fault was present.

.. code-block:: python

   await mqtt.reset_condenser_fault(device)

CLI: ``nwp-cli reset-condenser-fault``.

Commands the App Never Sends
============================

The NaviLink app's command enum also declares an OTA check, WiFi reconnect
and reset, a freeze-protection temperature and a smart diagnostic trigger,
but its request builder has no case for any of them, so no NaviLink client
publishes those codes and their payloads are unknown. Earlier versions of
this library sent made-up payloads for them; those methods were removed.
The freeze-protection range and the smart diagnostic result remain
readable from :class:`~nwp500.models.DeviceFeature` and
:class:`~nwp500.models.DeviceStatus`.

Related Documentation
=====================

* :doc:`../reference/python_api/mqtt_client` - Full MQTT client API reference
* :doc:`schedule-operation` - Reservations, recirculation schedules, and intelligent scheduling
* :doc:`diagnose-mqtt` - Connection troubleshooting and diagnostics
