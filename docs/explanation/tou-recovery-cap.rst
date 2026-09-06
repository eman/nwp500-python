==========================
The TOU Recovery Cap
==========================

When a Time-of-Use schedule is active, the NWP500 stops a heat-pump
recovery at about **90 % charge** instead of running to the setpoint. The
tank finishes roughly 1.9 degC below ``hp_lower_off_temp_setting`` and
stays there. Nothing in the protocol announces this, and no error is
raised - the compressor simply stops early.

This matters for anything that waits for the tank to reach its setpoint:
under an active TOU window that instant never arrives.

.. contents::
   :local:
   :depth: 2


The short version
=================

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Observation
     - Value
   * - Charge at termination
     - ``dhw_charge_per`` = 90 % (p10 89, p90 91). Never reaches 100.
   * - Shortfall below setpoint
     - ``tank_lower_temperature`` finishes 1.9 degC (3.42 degF) below
       ``hp_lower_off_temp_setting``
   * - Precondition
     - An expensive TOU period in force, un-overridden. ``tou_status``
       alone is **not** the test - see below.
   * - Frequency
     - 59 of 333 recoveries (18 %) over 260 days

A normal recovery, for contrast, ends with ``dhw_charge_per`` at 100 %
(p10 99) and the lower probe at or above the setpoint.


Evidence
========

Measured across 333 heat-pump recovery cycles of 15-480 minutes, from
2025-12-28 to 2026-09-06, on one unit. 196 reached the lower-off
setpoint; 137 did not.

The shortfall of the 137 is **bimodal**, not a spread:

.. code:: text

   shortfall below hp_lower_off_temp_setting, cycles that never reached it

     min 0.18   p10 1.66   p25 3.42   median 3.42   p75 4.32
     p90 31.03  max 58.86     (degF)

   most common values:  3.42 degF x 59 cycles    3.24 x 6    3.60 x 6

The spike at 3.42 degF is 1.9 degC exactly, and 19 steps of the 0.1 degC
tank-probe quantum. It holds across eight different setpoints from 140.0
to 147.2 degF and appears in all nine months observed, so it is an
offset in the control logic rather than a proportional effect or a
seasonal one. The long tail beyond 8 degF is ordinary interruption -
a draw starting mid-recovery, a mode change - and is unrelated.

``tou_status`` looks like a clean separator, and is not one:

.. list-table::
   :header-rows: 1
   :widths: 34 14 26 26

   * - Population
     - n
     - ``tou_status`` True
     - ``tou_override_status`` True
   * - Stopped 3.42 degF short
     - 59
     - **59 / 59 (100 %)**
     - 0 / 59
   * - Other unreached
     - 78
     - 49 / 78 (63 %)
     - 6 / 78
   * - Reached setpoint
     - 196
     - 98 / 196 (50 %)
     - 27 / 196

All 59 ran in ``HEAT_PUMP`` mode throughout, so this is not
``ENERGY_SAVER`` or ``VACATION`` behaviour.

But read that table carefully: 98 cycles reached the setpoint with
``tou_status`` True. **The flag only reports that TOU scheduling is
enabled.** It says nothing about whether the recovery ran inside an
expensive period, and the cap bites only when it did - outside one, an
enabled schedule does nothing at all.

The device marks a period itself. While inside one it applies non-zero
``*_diff_temp_setting`` offsets and reverts them at the end; on the unit
measured this toggles at 21:00 and 04:00 UTC daily. Using that as the
in-period test, among ``tou_status`` True cycles:

.. list-table::
   :header-rows: 1
   :widths: 34 22 22 22

   * - At cycle end
     - Capped
     - Reached
     - Other
   * - Inside a period
     - **42 (62 %)**
     - 12
     - 14
   * - Outside a period
     - 16 (12 %)
     - 86
     - 34

Test it at the moment the cycle *ended*, not when it began: a recovery
that starts off-peak and runs into a period is still capped, and testing
the start catches 17 of 59 against 43 testing the end.

Two plausible explanations were tested and **refuted**:

- *The upper zone satisfied its own cut-out first.* No -
  ``tank_upper_temperature`` reached ``hp_upper_off_temp_setting`` on
  only 2 of 137 unreached cycles, against 179 of 196 reached ones. The
  upper probe finishes short too, by a median of 4.5 degF.
- *The device terminates on outlet temperature.* No -
  ``dhw_outlet_temperature`` reached the setpoint on only 2 of 136.


What is not yet established
===========================

Being inside a period is a strong predictor but not a deterministic one:
12 cycles reached the setpoint from inside one, and 16 were capped from
outside. Some of that is the marker's own resolution - it is sampled at
the cycle end, and a period boundary crossed mid-recovery is not captured
- but it has not been reconciled against the schedule the device was
actually holding, which ``configure_tou_schedule_confirmed`` can read
back.

The 90 % figure has been observed on one unit under one TOU schedule. It
is not known whether the ceiling is fixed in firmware, derived from the
schedule, or configurable.

A note on reading ``tou_status`` over time: the field emits brief
``unknown`` values on integration reconnect - sub-second blips that
return immediately to the value they interrupted - so a raw state history
contains entries that are not transitions. Stores that keep only boolean
values drop these, which is the right behaviour and leaves a faithful
record of the genuine changes.

Do not read a low record count as lost data. It means the state was
*held*: on the unit measured, ``tou_status`` logged 165 changes in one
month and 5 in another, and the sparse month was the one in which TOU was
active nearly continuously. Forward-filling the genuine transitions is
correct. It can be corroborated against the ``*_diff_temp_setting``
fields, which toggle away from zero at the start of each TOU window and
back at the end.


Working with the cap
====================

**Do not wait for the setpoint.** Code that treats "tank reached
``hp_lower_off_temp_setting``" as the completion signal will block
indefinitely on a capped recovery. Watch ``dhw_charge_per`` plateauing,
or the compressor stopping, instead.

**Do not read a capped cycle as a fault or as degraded capacity.** The
appliance is doing what the schedule told it to. A recovery that ends at
90 % charge with ``tou_status`` True is a normal outcome.

**When measuring recovery duration, treat capped cycles separately.**
They are not censored observations of a full recovery - they are
complete observations of a different, shorter target. Pooling them with
uncapped recoveries biases any duration estimate downward; discarding
them biases it upward, because capped cycles are systematically shorter
(median 161 minutes against 235 for cycles that ran to setpoint).

**To force a full recovery,** set ``tou_override_status`` - none of the
59 capped cycles had it set, and 27 of the cycles that ran to setpoint
under an active TOU schedule did.
