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
families do this:

.. list-table::
   :header-rows: 1
   :widths: 60 40

   * - Values
     - Zero
   * - On/off flags (:class:`~nwp500.enums.OnOffFlag`)
     - ``UNKNOWN``
   * - Heat source (:class:`~nwp500.enums.HeatSource`)
     - ``UNKNOWN``
   * - Demand Response event (:class:`~nwp500.enums.DREvent`)
     - ``UNKNOWN``
   * - Recirculation mode (:class:`~nwp500.enums.RecirculationMode`)
     - ``UNKNOWN``
   * - DHW control type (:class:`~nwp500.enums.DHWControlTypeFlag`)
     - ``UNKNOWN``
   * - Efficiency mode
     - ``UNKNOWN``
   * - Reservation mode (:class:`~nwp500.enums.ReservationMode`)
     - ``NOT_RESERVATION``
   * - Firmware type (:class:`~nwp500.enums.FirmwareType`)
     - ``UNKNOWN``


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

:class:`~nwp500.enums.OnOffFlag` carries the protocol's ``UNKNOWN = 0``
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
``int`` for compatibility; 2 means a Demand Response override is
applied, and ``DeviceStatus.dr_override_active`` gives that reading.

Every other flag keeps :data:`~nwp500.models.status.DeviceBool`.


Capability flags: zero means "not fitted"
=========================================

The DID/feature ``Use`` flags are a third case. They are not enum-coded:
zero means "this device does not have the feature", which is a definite
answer, not an absent one: a ``recirculationUse`` of 0 means the unit
has no recirculation. ``False`` is the faithful mapping and :data:`~nwp500.models.feature.CapabilityFlag` is
unchanged.


Temperatures carry no sentinel
==============================

This is the important negative result, because it is the one that has
been guessed wrong before.

- **No out-of-band values.** The protocol has no ``0xFFFF``, ``-999`` or
  ``-1`` for a temperature it cannot read.
- **Zero is not reserved.** A temperature field that reads 0 converts
  like any other reading. The protocol has no notion of an unavailable
  temperature.

So a temperature of zero means zero. The library does not map any
temperature field to ``None``.


Absent fields
=============

The protocol has no marker for "not reported". Where a field is absent
from the payload, that shows through Pydantic's own missing-field
handling, not through any sentinel.


Fields that may read 0
======================

Several fields that look like natural candidates for N/A handling belong
to sensors or features a given unit may not have:

``outsideTemperature``, ``mixingRate``, ``currentInletTemperature``,
``dhwTemperature2``, ``recircTemperature``, ``recircFaucetTemperature``,
``recircDhwFlowRate``, ``heLowerOnTempSetting``,
``cumulatedDhwFlowRate``.

The NWP500 always reports 0 for ``currentInletTemperature``. Observing
that one of these "is always 0" in a capture is not evidence that 0 is
a sentinel. It is equally consistent with the sensor being absent, the
feature being unfitted, or the field being unused on this model. The
protocol makes no determination, so neither does this library.

``cumulatedDhwFlowRate`` is the clearest case. On the unit these docs were
checked against it reads 0 after 392 days in service, and so does every
draw counter in the diagnostics response, the draw count ``numOfdhwUse``
included, although the heater was in regular use. The firmware on that
unit is not keeping draw accounting, so its 0 does not mean that no water
has been used.

One numeric field does use zero for "not configured":
``airFilterAlarmPeriod`` reads 0 when no filter period has been set.
That is a property of that one field, not a converter-level rule.


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
