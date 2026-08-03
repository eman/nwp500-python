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
  0.5 degC raises it by 35 counts, about 140 Wh, on a 65-gallon tank. Seven months of
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

``totalEnergyCapacity`` is a whole-tank quantity, so its slope against
the setpoint measures the quantum without needing any assumption about
how the tank stratifies. Pairing each setpoint with the ``total`` it
produces, on a 65-gallon unit:

.. list-table::
   :header-rows: 1

   * - Setpoint
     - ``total``
     - Setpoint
     - ``total``
   * - 140.0 degF
     - 13690
     - 144.5 degF
     - 15450
   * - 140.9 degF
     - 14040
     - 145.4 degF
     - 15800
   * - 141.8 degF
     - 14390
     - 146.3 degF
     - 16150
   * - 142.7 degF
     - 14750
     - 147.2 degF
     - 16500
   * - 143.6 degF
     - 15100
     - 148.1 degF
     - 16850

An arithmetic sequence: least squares over those ten points gives
**R-squared 0.99999** and a slope of **70.25 raw counts per Kelvin** of
whole-tank temperature rise.

Converting that to Watt-hours needs a water mass, and this is where care
is required: a "65 gallon" tank does not hold 65 gallons of water. Rather
than assume nominal volume and derive an odd-looking quantum, assume the
quantum is a round number - every other conversion in this protocol is
(half-degrees, tenths) - and see which one implies a sensible volume:

.. list-table::
   :header-rows: 1

   * - Candidate quantum
     - Implied water volume
     - Plausible?
   * - **4 Wh** (1/250 kWh)
     - **241.7 L / 63.9 gal**
     - Yes - slightly under nominal, as expected
   * - 1/240 kWh (4.167 Wh)
     - 251.8 L / 66.5 gal
     - No - more than the nameplate
   * - 10 kJ
     - 167.8 L / 44.3 gal
     - No
   * - 15 kJ
     - 251.7 L / 66.5 gal
     - No

**4 Wh per count** is the only round candidate implying a volume below
the nameplate, which is the only physically sensible direction. The
library uses 4.0.

A second, noisier method agrees. Across 183 individual heating
recoveries, dividing each tank sensible-heat gain (from the two
thermistors and the nominal mass) by the device's reported change gives a
median of 4.11 Wh/count, p10 3.47 and p90 4.45. That route depends on
``(upper + lower) / 2`` approximating the true mean tank temperature, so
it is far less precise, but it is an independent confirmation and it does
not use electrical input at all.

The efficiency cross-check
--------------------------

A third check rules out the old scale on its own. Integrating
``currentInstPower`` over each recovery gives the electrical energy in,
and dividing the device's *reported* energy gain by it gives an implied
coefficient of performance:

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

This argument is worth stating separately because it needs no tank
volume, specific heat or stratification model - only the device's own
reported energy and its own reported power. It cannot tell you what the
quantum *is*, but it rules out the pre-10.0 value regardless of anything
assumed elsewhere on this page.

The reference temperature
-------------------------

This is the strongest result here, because it needs no physics at all.
Extrapolating the setpoint regression above to ``total = 0`` gives:

.. list-table::
   :header-rows: 1

   * - Quantity
     - Value
   * - Regression zero crossing
     - **104.92 degF**
   * - Device ``dhwTemperatureMin``
     - **104.9 degF**

Those agree to within a fiftieth of a degree, and the calculation uses
only the device's own two numbers - no tank mass, no specific heat, no
thermistor readings, no assumption about the quantum. It establishes

.. code:: text

   full_recovery_energy = k * (setpoint - dhwTemperatureMin)

as fact rather than inference. The device measures a full recovery from
its own minimum setpoint, not from the cold water inlet.


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
