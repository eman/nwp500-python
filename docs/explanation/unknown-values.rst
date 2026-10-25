==============
Unknown Values
==============

The device sometimes declines to report a field. This page records what
the protocol does about that, which fields are affected, and which
fields look affected but are not.

**There is no single rule about zero.** Zero is a
reserved sentinel in some field families, a real value in others, and
carries no special meaning at all for temperatures.

.. contents::
   :local:
   :depth: 2


Enum-coded flags: zero is a sentinel
====================================

Many status fields are enum-coded, and in most of them zero is reserved
for "unknown". The generic on/off flag is 0 unknown, 1 off, 2 on
(:class:`~nwp500.enums.OnOffFlag`): real values start at 1. Eight
families do this, and the NaviLink app shows two of their zeros as
something a user would read as "no data":

.. list-table::
   :header-rows: 1
   :widths: 42 20 38

   * - Values
     - Zero
     - The NaviLink app shows
   * - On/off flags (:class:`~nwp500.enums.OnOffFlag`)
     - ``UNKNOWN``
     - "Unknown"
   * - Heat source (:class:`~nwp500.enums.HeatSource`)
     - ``UNKNOWN``
     - **"-"**
   * - Demand Response event (:class:`~nwp500.enums.DREvent`)
     - ``UNKNOWN``
     - **"Not Applied"**
   * - Recirculation mode (:class:`~nwp500.enums.RecirculationMode`)
     - ``UNKNOWN``
     - "Unknown"
   * - DHW control type (:class:`~nwp500.enums.DHWControlTypeFlag`)
     - ``UNKNOWN``
     - "Unknown"
   * - Efficiency mode
     - ``UNKNOWN``
     - "Unknown"
   * - Reservation mode (:class:`~nwp500.enums.ReservationMode`)
     - ``NOT_RESERVATION``
     - "NOT RESERVATION"
   * - Firmware type (:class:`~nwp500.enums.FirmwareType`)
     - ``UNKNOWN``
     - "Unknown"


Enums where zero is a value
---------------------------

The rule is not global, and this is where a blanket converter goes wrong:

.. list-table::
   :header-rows: 1
   :widths: 42 58

   * - Values
     - Zero means
   * - Current operation mode
       (:class:`~nwp500.enums.CurrentOperationMode`)
     - ``STANDBY``, a real, common state
   * - Filter change (:class:`~nwp500.enums.FilterChange`)
     - ``NORMAL``: the filter is fine

A device sitting in standby reports 0 constantly. Treating that as
"unknown" would blank the operating mode most of the time.


What this library does
----------------------

:class:`~nwp500.enums.OnOffFlag` carries the vendor's ``UNKNOWN = 0``
member. Nine status fields are on/off flags; eight of them exist here as
flags and are typed :data:`~nwp500.models.status.DeviceTriState`, which
maps 0 to ``None``:

- ``operation_busy``
- ``comp_use``
- ``anti_legionella_use``
- ``anti_legionella_operation_busy``
- ``heat_upper_use``
- ``heat_lower_use``
- ``air_filter_alarm_use``
- ``recirc_reservation_use``

The ninth is ``drOverrideStatus``, which this library keeps as a raw
``int`` for compatibility; the app shows "DR applied" when it is 2, and
``DeviceStatus.dr_override_active`` gives the same reading.

Every other flag keeps :data:`~nwp500.models.status.DeviceBool`.


Capability flags: zero means "not fitted"
=========================================

The DID/feature ``Use`` flags are a third case. They are not enum-coded:
zero means "this device does not have the feature", which is a definite
answer, not an absent one. The NaviLink app hides its whole
recirculation screen when ``recirculationUse`` is 0. ``False`` is the
faithful mapping and :data:`~nwp500.models.feature.CapabilityFlag` is
unchanged.


Temperatures carry no sentinel
==============================

This is the important negative result, because it is the one that has
been guessed wrong before.

- **No out-of-band values.** The protocol has no ``0xFFFF``, ``-999`` or
  ``-1`` for a temperature it cannot read.
- **No zero guard.** The NaviLink app converts and shows whatever
  temperature arrives, so a device reporting 0 would show 32 degF. It
  has no notion of an unavailable temperature.

So a temperature of zero means zero. The library does not map any
temperature field to ``None``.


Absent and zero are indistinguishable
=====================================

The NaviLink app reads a numeric field missing from the status message
as 0, so the vendor's own client cannot tell "not reported" from
"reported as zero" either.

There is consequently no protocol-level concept of "unreported" to
recover. Where a field is absent from the payload, that is
visible to this library through Pydantic's own missing-field handling,
not through any sentinel.


Fields the app never displays
=============================

Several fields that look like natural candidates for N/A handling are
not shown by the NaviLink app for this device type:

``outsideTemperature``, ``mixingRate``, ``currentInletTemperature``,
``dhwTemperature2``, ``recircTemperature``, ``recircFaucetTemperature``,
``recircDhwFlowRate``, ``heLowerOnTempSetting``.

The app does not read ``cumulatedDhwFlowRate`` at all.

Observing that one of these "is always 0" in a capture is not evidence
that 0 is a sentinel. It is equally consistent with the sensor being
absent, the feature being unfitted, or the field being unused on this
model. The app makes no determination, so neither does this library.

``cumulatedDhwFlowRate`` is the clearest case. On the unit these docs were
checked against it reads 0 after 392 days in service, and so does every
draw counter in the diagnostics response, the draw count ``numOfdhwUse``
included, although the heater was in regular use. The firmware on that
unit is not keeping draw accounting, so its 0 does not mean that no water
has been used.

The one place the app does treat a numeric zero as "not configured" is
``airFilterAlarmPeriod``, and it handles it by substituting a different
*message* ("filter setup needed") rather than blanking a value: a
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
   # After:  True for both OFF and unknown, but now you can tell them apart
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

- :doc:`tank-energy`: the other case where the protocol's own names
  mislead
- :doc:`../reference/protocol/data_conversions`: protocol field conversions
