==============
Unknown Values
==============

The device sometimes declines to report a field. This page records what
the protocol actually does about that, which fields are affected, and -
just as importantly - which fields look affected but are not.

The short answer: **there is no single rule about zero.** Zero is a
reserved sentinel in some field families, a real value in others, and
carries no special meaning at all for temperatures. Earlier attempts to
apply one rule library-wide produced bugs in both directions.

.. contents::
   :local:
   :depth: 2


Where the evidence comes from
=============================

Navien's own Android client, NaviLink, was decompiled - version 2.03.00,
versionCode 141, published March 2026. The app is a first-party decoder
for the same MQTT payloads this library parses, so its enum tables and
its null-handling are direct evidence of intent rather than inference
from observed traffic.

Two cautions apply to everything below. The app is a *consumer* of the
protocol, not its specification, and it ignores a great deal of what the
device sends. Absence of handling in the app is therefore weak evidence
on its own; presence of an explicit sentinel is strong evidence.


Enum-coded flags: zero is a sentinel
====================================

The app decodes many status fields through enums in ``KDEnum.java``. The
generic on/off flag is declared:

.. code:: java

   public enum MgppOnOFFFlag {
       UNKNOWN(0, "Unknown"),
       OFF(1, "OFF"),
       ON(2, "ON");
   }

Zero is reserved and real values start at 1. This is not an accident of
one enum - eight of the app's enums do it, and two render their zero as
something a user would read as "no data":

.. list-table::
   :header-rows: 1
   :widths: 42 20 38

   * - App enum
     - Zero member
     - Display text
   * - ``MgppOnOFFFlag``
     - ``UNKNOWN``
     - "Unknown"
   * - ``HPWHHeatSource``
     - ``UNKNOWN``
     - **"-"**
   * - ``HPWHDREvent``
     - ``UNKNOWN``
     - **"Not Applied"**
   * - ``MgppRecirculationOperationMode``
     - ``UNKNOWN``
     - "Unknown"
   * - ``MgppDHWControlTypeFlag``
     - ``UNKNOWN``
     - "Unknown"
   * - ``HydroElectricalEfficiencyMode``
     - ``UNKNOWN``
     - "Unknown"
   * - ``MgppReservationMode``
     - ``NOT_RESERVATION``
     - "NOT RESERVATION"
   * - ``firmwareType``
     - ``Unknown``
     - "Unknown"


But in five other enums zero is real
------------------------------------

The rule is not global, and this is where a blanket converter goes wrong:

.. list-table::
   :header-rows: 1
   :widths: 42 58

   * - App enum
     - Zero means
   * - ``MgppOperationMode``
     - ``STANDBY`` - a real, common state
   * - ``OperationMode``
     - ``STANDBY``
   * - ``HydroOperationMode``
     - ``STOP``
   * - ``HydroFsmState``
     - ``INIT``
   * - ``FilterChange``
     - ``NORMAL`` - filter is fine

A device sitting in standby reports 0 constantly. Treating that as
"unknown" would blank the operating mode most of the time.


What this library does
----------------------

:class:`~nwp500.enums.OnOffFlag` carries the vendor's ``UNKNOWN = 0``
member. The app decodes nine status fields through ``MgppOnOFFFlag``;
eight of them exist here as flags and are typed
:data:`~nwp500.models.status.DeviceTriState`, which maps 0 to ``None``:

- ``operation_busy``
- ``comp_use``
- ``anti_legionella_use``
- ``anti_legionella_operation_busy``
- ``heat_upper_use``
- ``heat_lower_use``
- ``air_filter_alarm_use``
- ``recirc_reservation_use``

The ninth is ``drOverrideStatus``, which this library exposes as a raw
``int`` rather than a flag, so it is left alone.

Every other flag keeps :data:`~nwp500.models.status.DeviceBool`.


Capability flags: zero means "not fitted"
=========================================

The DID/feature ``Use`` flags are a third case, and the app treats them
differently from status flags - it does not decode them through an enum
at all, and checks them directly:

.. code:: java

   if (... feature.getRecirculationUse() == 0) {
       this.viewDataBinding.layoutHotButton.setVisibility(8);
       this.viewDataBinding.linearLayoutControlRecirculation.setVisibility(8);
       return;
   }

Zero hides the entire recirculation UI. For a capability flag, zero means
"this device does not have the feature", which is a definite answer, not
an absent one. ``False`` is the faithful mapping and
:data:`~nwp500.models.feature.CapabilityFlag` is unchanged.


Temperatures carry no sentinel
==============================

This is the important negative result, because it is the one that has
been guessed wrong before.

- **No out-of-band values.** No ``0xFFFF``, ``-999`` or ``-1`` appears
  anywhere in the app's status handling. The only ``65535`` constants in
  the app are CRC16 masks and infrared remote-control codes.
- **No zero-guard in any display path.** The only ``== 0`` comparisons on
  the status screen are ``errorCode``, ``minorCode``, ``waterSprayStatus``
  and ``airFilterAlarmPeriod``. Not one is a temperature.
- **The formatter is unconditional.** ``getTempText()`` converts and
  prints whatever arrives, so a device reporting 0 would render as
  32 degF. The app has no notion of an unavailable temperature.

So a temperature of zero means zero. The library does not map any
temperature field to ``None``.

.. warning::
   Do not add zero-as-none to a temperature field on the strength of it
   "always reading 0" in a capture. Ambient and tank temperatures can
   legitimately reach 0 degC, and a heat pump in a cold garage will get
   there. A previous attempt did exactly this and had to be reverted after
   it reported working sensors as missing during cold-weather operation.


Absent and zero are indistinguishable
=====================================

All 126 numeric fields in the app's status model are declared as
primitive ``int`` - there is not a single boxed ``Integer`` among them. A
field missing from the JSON therefore deserializes to ``0``, and the
vendor's own client cannot tell "not reported" from "reported as zero"
either.

There is consequently no protocol-level concept of "unreported" to
recover. Where a field is genuinely absent from the payload, that is
visible to this library through Pydantic's own missing-field handling,
not through any sentinel.


Fields the app never displays
=============================

Several fields that look like natural candidates for N/A handling are
simply not rendered by the app for this device type. They exist as
getters on the status model with no UI call site:

``outsideTemperature``, ``mixingRate``, ``currentInletTemperature``,
``dhwTemperature2``, ``recircTemperature``, ``recircFaucetTemperature``,
``heLowerOnTempSetting``.

Observing that one of these "is always 0" in a capture is not evidence
that 0 is a sentinel. It is equally consistent with the sensor being
absent, the feature being unfitted, or the field being unused on this
model. The app makes no determination, so neither does this library.

The one place the app does treat a numeric zero as "not configured" is
``airFilterAlarmPeriod``, and it handles it by substituting a different
*message* ("filter setup needed") rather than blanking a value - a
per-field UI decision, not a converter-level rule.


Migration
=========

Eight fields change type from ``bool`` to ``bool | None``. ``None`` is
falsy, so truthiness checks are unaffected:

.. code:: python

   if status.comp_use:          # unchanged
       ...

The risk is in negative and identity checks, which no longer mean the
same thing:

.. code:: python

   # Before: True for both OFF and unknown
   # After:  True for both OFF and unknown - but now you can tell them apart
   if not status.comp_use:
       ...

   # Distinguish explicitly
   if status.comp_use is None:
       ...                      # device is not reporting
   elif status.comp_use:
       ...                      # compressor running

Anything doing arithmetic or formatting on these fields needs a ``None``
check. For Home Assistant this is the desired shape: ``None`` renders as
"Unknown" rather than recording a fabricated OFF into the recorder
database and skewing history.

The CLI renders these as ``Unknown`` rather than ``No``.


See also
========

- :doc:`tank-energy` - the other case where the protocol's own names
  mislead, worked out from the same teardown
- :doc:`../reference/protocol/data_conversions` - protocol field conversions
