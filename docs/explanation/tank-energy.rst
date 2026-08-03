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

Both are raw counts of 4 Wh each, not Watt-hours. Library versions before
10.0 multiplied by 10, overstating tank energy by 2.5x.

Both are also measured **from the setpoint**, so both describe potential
rather than content: move the setpoint and both change while the water in
the tank does not. Neither is a state of charge.

Their **difference** is a state of charge, and is exposed as
``DeviceStatus.usable_energy``:

.. code:: text

   usable_energy = full_recovery_energy - energy_to_setpoint
                 = k * (tank_temperature - 104.9 degF)

The setpoint cancels. What remains is the tank's heat above the device's
minimum operating temperature - close enough to the lowest useful shower
temperature that it is a good estimate of what you can actually draw.


How the fields behave
=====================

Both fields fit a single two-parameter model:

.. code:: text

   energy_to_setpoint    = k * (setpoint - tank_mean_temperature)
   full_recovery_energy  = k * (setpoint - reference_temperature)

where ``k`` is the tank's heat capacity and ``reference_temperature`` is
the device's own minimum setpoint, ``dhwTemperatureMin`` (40.5 degC /
104.9 degF) - though only about two thirds of the time, see
`Two branches`_.

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
how the tank stratifies.

The device does not report a single ``total`` per setpoint - see
`Two branches`_ below - so the table lists the most common value at each
setpoint, which covers 68 % of samples:

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

An arithmetic sequence: least squares gives **R-squared 0.99999** and a
slope of **70.25 raw counts per Kelvin** of whole-tank temperature rise.

The slope is the robust part of this. The second branch, fitted
separately, gives 389.81 units/degF against the primary's 390.56 - the
same figure to within 0.2 %. Two independent populations agreeing on the
slope is stronger evidence for the quantum than either alone.

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

.. _two branches:

Two branches
------------

``totalEnergyCapacity`` is **not** a function of the setpoint alone. At a
fixed setpoint it takes one of two values, flipping between them several
times a day. Over four months at nine setpoints:

.. list-table::
   :header-rows: 1

   * - Branch
     - Share
     - Slope
     - Zero crossing
   * - Primary
     - 68 %
     - 390.56 units/degF
     - **104.95 degF**
   * - Secondary
     - 32 %
     - 389.81 units/degF
     - **108.48 degF**

The two are parallel, separated by a constant 1400-1410 units - exactly
**2 degC** of setpoint - at every setpoint measured.

The primary branch's zero crossing matches the device's
``dhwTemperatureMin`` of 104.9 degF to within a twentieth of a degree,
using only the device's own two numbers: no tank mass, no specific heat,
no thermistors, no assumption about the quantum. On that branch,

.. code:: text

   full_recovery_energy = k * (setpoint - dhwTemperatureMin)

The secondary branch behaves identically with a reference 2 degC higher,
and **what selects between them is unknown**. The device's
``hpUpperOnTemperatureSetting`` correlates with the choice - 104.9 degF
when the primary is active, 143.4 degF when the secondary is - which
would fit the device computing recovery cost from its own turn-on
threshold, but only 22 paired samples were available and that is a lead
rather than a finding.

.. warning::
   Because of this, do not derive the tank's heat capacity from a live
   ``full_recovery_energy`` reading: landing on the wrong branch gives an
   error of about 9 %. Use the slope, which is stable across both
   branches, or compute stored energy from the thermistors directly.


What ``dhwChargePer`` does
==========================

``dhwChargePer`` is a fourth signal and does not reconcile with the other
two. On one device, ``energy_to_setpoint / full_recovery_energy``
implies 30 % charged while ``dhwChargePer`` reads 59 %; over two weeks
the two differ by a mean of 48 points with 32 points of scatter.

Treat it as an opaque vendor heuristic rather than a defined fraction of
anything. For a charge figure with defined meaning, use
``usable_energy``.


Drawable energy
===============

``DeviceStatus.usable_energy`` is the difference of the two fields, and
is the one number here that describes the tank's state rather than its
distance from a target:

.. code:: text

   usable_energy = full_recovery_energy - energy_to_setpoint

Raising the setpoint inflates both inputs equally, so the result does not
move - which is what makes it a state of charge and the two raw fields
not.

The implied reference is ``dhw_temperature_min``, 104.9 degF. A shower
runs around 105 degF, so heat below that reference is real but not
useful, and excluding it is the behaviour you want. Note that a mixing
valve does not change this floor: it caps how *hot* water can be
delivered, and once the tank falls below its setting it simply passes
through, so water stays usable down to the temperature you actually want
at the tap.

Despite ``full_recovery_energy`` being bimodal (see `Two branches`_),
the difference is robust, because both fields shift together. Checked
against the tank thermistors over 12275 samples, the tank temperature
implied by ``usable_energy`` agrees with the thermistor mean to a
standard deviation of **0.57 degF**, with 97.5 % of samples inside
2 degF.

If you need a different floor - a bath at 100 degF, or energy above the
cold inlet - compute it from the thermistors instead. On a 65-gallon tank
the heat capacity is 156 Wh per degF:

.. code:: text

   drawable_Wh = 156 * (tank_mean_temperature - your_floor_degF)


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
