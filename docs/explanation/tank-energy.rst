===========
Tank Energy
===========

The NWP500 reports two energy figures, ``totalEnergyCapacity`` and
``availableEnergyCapacity``. Both names mislead, and before v10.0 this
library also scaled them wrongly. This page explains what they
actually measure and shows the evidence for the correction.

.. contents::
   :local:
   :depth: 2


The short version
=================

.. list-table::
   :header-rows: 1
   :widths: 22 30 48

   * - Protocol field
     - What the name suggests
     - What it actually is
   * - ``availableEnergyCapacity``
     - Energy available in the tank
     - Energy still **needed** to reach the setpoint. It *falls* as the
       tank heats and hits zero when the tank is fully charged - the
       exact inverse of the name.
   * - ``totalEnergyCapacity``
     - Fixed tank capacity
     - Cost of a full recovery to the **current setpoint**. It moves
       whenever the setpoint moves.

Both are raw counts of about 4 Wh each, not Watt-hours. Library versions
before 10.0 multiplied by 10, overstating tank energy by 2.43x.

Neither field tells you how much hot water you can actually draw. That
depends on tank volume, the inlet temperature and the temperature you
want water delivered at, none of which the device reports.


How the fields behave
=====================

Both fields fit a single two-parameter model:

.. code:: text

   energy_to_setpoint    = k * (setpoint - tank_mean_temperature)
   full_recovery_energy  = k * (setpoint - reference_temperature)

where ``reference_temperature`` is the device's own minimum setpoint,
``dhwTemperatureMin`` (40.5 degC / 104.9 degF), and ``k`` is the tank's
heat capacity.

Two consequences follow, and both matter:

* ``energy_to_setpoint`` is a **deficit**. Code that treats it as stored
  energy has the signal backwards: it is largest when the tank is
  coldest.
* ``full_recovery_energy`` is **not a constant**. Raising the setpoint by
  0.5 degC raises it by about 143 Wh on a 65-gallon tank. Seven months of
  history on one device shows sixteen distinct values as the setpoint was
  adjusted.


The evidence
============

Deficit, not stored energy
--------------------------

During a heating recovery on a 65-gallon unit at a 140.9 degF setpoint,
with the tank warming and no draws:

.. list-table::
   :header-rows: 1

   * - Mean tank temp
     - Setpoint minus tank
     - ``availableEnergyCapacity``
     - ``dhwChargePer``
   * - 119.5 degF
     - 21.4 degF
     - 8816
     - 54.5 %
   * - 127.4 degF
     - 13.5 degF
     - 5300
     - 69.5 %
   * - 135.1 degF
     - 5.8 degF
     - 2275
     - 85.7 %

The field falls as the tank fills with heat. Regressed against mean tank
temperature over two weeks of five-minute samples, the slope is negative
with an R-squared of 0.93 and a zero crossing at the setpoint.

The 4 Wh quantum
----------------

The quantum was measured across **183 independent heating recoveries**.
For each, the tank's sensible-heat gain was computed from the two
thermistors and the known tank mass:

.. code:: text

   gain_Wh = mass_kg * 4.186 kJ/kg/K * temperature_rise_K / 3.6

and divided by the device's own reported change. This comparison is
independent of the heat pump's efficiency, because it never uses
electrical input.

.. list-table::
   :header-rows: 1

   * - Quantity
     - Median
     - p10
     - p90
   * - Wh per raw count
     - 4.11
     - 3.47
     - 4.45

The library uses **4.0**. The 2.8 % gap is consistent with the tank
holding slightly less than its nominal 65 gallons, which is normal.

The efficiency cross-check
--------------------------

An independent check settles it. Integrating ``currentInstPower`` over
each recovery gives the electrical energy in, and dividing the tank's
heat gain by it gives the heat pump's coefficient of performance:

.. list-table::
   :header-rows: 1

   * - Scale used
     - Implied COP (median)
     - Verdict
   * - 4 Wh/count (corrected)
     - 2.89
     - Normal for a heat pump water heater
   * - 10 Wh/count (pre-10.0)
     - 7.02
     - Physically impossible

A heat pump water heater in a 72 degF room runs at a COP of roughly 2 to
4. A COP of 7 would mean the device generated energy it never consumed.

The reference temperature
-------------------------

Solving ``reference = setpoint - full_recovery_energy / k`` across the
same history gives a median of 104.5 degF, matching the device's
``dhwTemperatureMin`` of 104.9 degF. The device measures a full recovery
from its own minimum setpoint, not from the cold water inlet.


What ``dhwChargePer`` does
==========================

``dhwChargePer`` is a fourth signal and does not reconcile with the other
two. On one device, ``energy_to_setpoint / full_recovery_energy``
implies 30 % charged while ``dhwChargePer`` reads 59 %; over two weeks
the two differ by a mean of 48 points with 32 points of scatter.

Treat it as an opaque vendor heuristic rather than a defined fraction of
anything.


Migrating from before v10.0
===========================

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Old
     - New
   * - ``status.total_energy_capacity`` (removed)
     - ``status.full_recovery_energy`` - and the value is 2.5x smaller
   * - ``status.available_energy_capacity`` (removed)
     - ``status.energy_to_setpoint`` - 2.5x smaller, and note it was
       never "available"
   * - Treating the value as available energy
     - It is a deficit; invert the logic. ``full_recovery_energy -
       energy_to_setpoint`` is the energy added above the device's
       reference temperature
   * - Treating the value as a percentage
     - It never was one

The old attribute names are removed rather than aliased, so a
rename that is missed fails immediately with ``AttributeError`` instead
of silently returning a number 2.5x too large.

If you logged these values historically, the stored series needs
rescaling by 0.4 to be comparable with values from v10.0 onward.


See also
========

- :doc:`../how-to/track-energy` - Monitoring energy and power
- :doc:`../reference/protocol/data_conversions` - Protocol field conversions
