==================
Device Maintenance
==================

Maintenance commands cover firmware update information, the installer
diagnostics counters, air filter service intervals, the cloud's
replacement log and fault resets. The CLI equivalents are noted with
each one.

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

The device keeps lifetime counters: heat pump and element energy, days
since installation, fault event counts, demand-response operation times,
hot-water draw statistics and component run times and start counts. They
are installer data, but a consumer account's unit answers the query.

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
hours; the remaining counters have no documented unit. See
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
otherwise 1000 to 10000 hours in 500-hour steps. The device reports the interval back as
``DeviceStatus.air_filter_alarm_period``.

.. code-block:: python

   await mqtt.set_air_filter_life(device, 3000)
   await mqtt.reset_air_filter(device)

CLI: ``nwp-cli filter-life 3000`` and ``nwp-cli reset-filter``.

Maintenance Log
===============

Separately from the device's own filter timer, the Navien cloud keeps a
log of when the air filter was replaced and when a CIP (clean-in-place,
the descaling flush) service was done. The REST client reads and writes
it.

Recording a replacement date only updates the cloud's log; it does not
reset the device's filter timer. Do both after servicing the filter.

.. code-block:: python

   from datetime import date

   from nwp500 import NavienAPIClient

   api = NavienAPIClient(auth)
   info = device.device_info

   # Log today's filter replacement, then reset the device's timer.
   await api.record_filter_change(info.mac_address, info.additional_value, date.today())
   await mqtt.reset_air_filter(device)

   # Log a descaling flush.
   await api.record_cip_change(info.mac_address, info.additional_value, date(2025, 3, 7))

The date is sent as ``YYYY-M-D`` without zero padding (``2025-3-7``);
pass a :class:`datetime.date` and the library does the formatting.

Reading the history back returns the newest entries first:

.. code-block:: python

   for entry in await api.get_filter_history(info.mac_address, info.additional_value):
       print("Filter replaced", entry.maintenance_date)

   for entry in await api.get_cip_history(info.mac_address, info.additional_value):
       print("Descaled", entry.maintenance_date)

Each :class:`~nwp500.models.MaintenanceHistoryEntry` carries the date as
the cloud returns it and ``register_at``, the record's creation stamp,
whose unit is not known. Both calls page with ``offset`` and
``count`` (default 20).

Related cloud-side data readable without MQTT:
:meth:`~nwp500.NavienAPIClient.get_error_history` for recorded faults and
``Device.descaling`` (from :meth:`~nwp500.NavienAPIClient.get_device_info`)
for the scheduled descaling window.

Condenser Fault Reset
=====================

Clears a condenser fault. This is an installer-level control, but a
consumer account's unit acknowledges the command; the clearing effect could not be
observed because no fault was present.

.. code-block:: python

   await mqtt.reset_condenser_fault(device)

CLI: ``nwp-cli reset-condenser-fault``.

Unsupported Commands
====================

An OTA check, WiFi reconnect and reset, setting the freeze-protection
temperature and triggering a smart diagnostic aren't supported: their
payloads are unknown. The freeze-protection range and the smart diagnostic result remain
readable from :class:`~nwp500.models.DeviceFeature` and
:class:`~nwp500.models.DeviceStatus`.

Related Documentation
=====================

* :doc:`../reference/python_api/mqtt_client`: Full MQTT client API reference
* :doc:`schedule-operation`: Reservations, recirculation schedules, and intelligent scheduling
* :doc:`diagnose-mqtt`: Connection troubleshooting and diagnostics
