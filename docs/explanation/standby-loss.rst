=============
Standby Loss
=============

A tank that is not heating loses heat two ways: through its jacket to the
air beside the heater, and, where the hot water line has a recirculation
loop, to each run of the loop's pump. The simulator's layered tank loses
through its sides, bottom and top, each layer to the air, and takes a
run's cooled return in at the bottom. On the unit measured, a
circulation run removed more heat in a few minutes than the jacket does
in hours, and most of that heat shows on the lower probe, not the upper.

.. contents::
   :local:
   :depth: 2


Summary
=======

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Loss
     - Observed behaviour
   * - Jacket loss
     - In the simulator's layered tank, **2.89 BTU/hr per degF** through
       the sides, **0.89** through the bottom and **0.68** through the
       top, each layer's to the air: **4.45** in all. For a mixed
       140 degF tank in 65 degF air that is about **0.63 degF an hour**.
   * - A circulation run
     - Priced on an effective loop of **19.36 gal**, its return at the
       air plus 7.84 degF. At the loop fitted in September (6.38 gal), a
       typical run was about 5 degF of the whole tank, and the probes
       showed 0.44 of it.
   * - Where a run's heat shows
     - Ten minutes after a run, the lower probe had fallen **0.9 degF** in
       a mixed tank and **7.0 degF** in a stratified one. The upper probe
       moved no more than standby alone.
   * - The gap between the probes
     - With nothing heating or drawing, it closes on a time constant of
       about **59 h**. In the layered tank the column's conduction
       closes it and the bottom's loss opens it.

All figures come from one NWP500-65 and its recorded status history to
2026-10-24, with the air beside the heater measured separately. The
circulation figures are that installation's loop.


The jacket loss
===============

The simulator walks the tank as layers (:doc:`simulator-methodology`),
each losing to the air through its share of the sides' ``UA``, the
bottom layer through the bottom's too and the top through the top's,
all fitted together with where the probes read (``sim.tank_fit``). On
266 quiet windows, 254 metered draws and 118 recoveries from 2026-04-16
to 10-26, the sides came out at 2.89 BTU/hr per degF, the bottom 0.89
and the top 0.68. The record does not split the bottom from the sides
well: fitted on the record to 2026-09-18 alone, the bottom came out
1.55 and the sides 2.66. On the 59 quiet windows after 2026-09-18,
fitted on the days before them, the layered tank tracks the upper
probe within 0.254 degF RMS and the lower within 0.564
(:doc:`simulator`).

What the probes show
--------------------

Read as one temperature, the probes' mean, the tank loses heat at a
rate ``UA * (T_tank - T_air)`` with a ``UA`` that rises with the
difference between the tank and the air, likely because a hotter tank
is more often stratified, with the bottom's loss leaving water the
lower probe reads. Fitted on 301 quiet windows (no draw, no heating, no circulation
run) covering a tank-to-air difference of 11.2 to 90.7 degF, to
2026-08-12:

``UA(dT) = 4.47 * (dT / 50) ^ 0.227`` BTU/hr per degF

Across the 301 windows ``UA`` averaged 4.87 BTU/hr per degF (standard
deviation 1.26). Refitted on 393 windows to 2026-10-11, the same rule
gave ``4.61 * (dT / 50) ^ 0.186``. Computed from the rising law, with the
tank's thermal mass of
527 BTU/degF:

.. list-table::
   :header-rows: 1
   :widths: 25 25 25 25

   * - Tank above the air
     - ``UA`` (BTU/hr per degF)
     - Heat lost per day
     - Tank cooling per hour
   * - 13 degF
     - 3.29
     - 1,000 BTU
     - 0.08 degF
   * - 50 degF
     - 4.47
     - 5,400 BTU
     - 0.42 degF
   * - 75 degF
     - 4.90
     - 8,800 BTU
     - 0.70 degF
   * - 85 degF
     - 5.04
     - 10,300 BTU
     - 0.81 degF

The cooling rate is for the probes' mean in a tank left alone. It says
nothing about draws or circulation runs, which come on top.

The clearest single window was 93.9 hours from 2026-08-08 to 2026-08-12,
with no draw, no heating and no circulation run. The tank destratified
within the first day, and with the tank 13.5 degF above the air it lost
heat at a ``UA`` of **2.93**, a time constant of 180 h (fit error
0.22 degF). A hot window on 2026-07-31, 61.8 degF above the air, gave
5.58. A single constant ``UA`` of 5.12 missed the cold window's
temperatures by 2.06 degF (RMS); a law in this form missed them by
0.19 degF.

By season, constant fits over the history gave winter **4.52** (93
windows), spring **5.24** (137) and summer **5.53** (97) BTU/hr per degF,
with standard deviations of 1.65 to 2.22. The spreads overlap, so the
seasonal trend is weak.

Measuring it on your own heater
-------------------------------

A window that contains a draw, a heating cycle or a circulation run
inflates ``UA``, sometimes far past anything physical. Over 2026-07-23
to 2026-08-12, windows bounded only by the moment a draw or heating
started gave 28 windows at 5.58 BTU/hr per degF (standard deviation
3.24, highest 18.44). Requiring the whole window to be clear of draws,
heating and runs, starting 45 minutes after the last of them, left 24
windows at 4.78 (standard deviation 1.19). :doc:`../how-to/calibrate-simulator`
uses that rule.

How long to wait matters little past half an hour. Over February to
October 2026 the rising law's level (its ``UA`` at a 50 degF
difference) was:

.. list-table::
   :header-rows: 1
   :widths: 25 25 25 25

   * - Wait after the last event
     - Quiet windows
     - Mean window ``UA`` (sd)
     - Law's level
   * - 0 min
     - 369
     - 5.26 (1.47)
     - 4.49
   * - 15 min
     - 353
     - 5.08 (1.29)
     - 4.46
   * - 30 min
     - 331
     - 4.97 (1.15)
     - 4.44
   * - 45 min
     - 313
     - 5.01 (1.12)
     - 4.47
   * - 60 min
     - 297
     - 5.01 (1.10)
     - 4.47
   * - 90 min
     - 271
     - 5.02 (1.03)
     - 4.48

From 30 minutes on, the mean window settles at about 5.0 and the law's
level moves under 1 %; 45 minutes keeps that with the windows a longer
wait would drop.


Circulation runs
================

A recirculation pump replaces the cooled water standing in the loop with
hot water from the tank. On this installation the loop returns into the
cold line at the tank's **cold inlet**, so the cooled water reaches the
tank at the bottom.

How much heat a run removes
---------------------------

A run first displaces the water standing in the loop, which has cooled
toward the air, and then recirculates water it has already warmed. The
cooled water it returns to the tank is at most about one loop volume,
fitted from the runs themselves. After that, the warmed pipe keeps
losing heat for as long as the pump runs. Runs less than 10 minutes
apart count as one, because the loop has not cooled in between.

The loop's water does not cool all the way to the air beside the
heater, and a run soon after another finds it still warm. On 123 runs
with the compressor off (2026-04-04 to 2026-10-24):

* Before a run that followed 16 h or more without one, the return
  probe read a median **6.9 degF** above the heater's air, and it
  followed that air with a slope of 0.95 (49 runs).
* A run within an hour of the last took a median **1,583 BTU**; one
  after 8 h or more, **3,223 BTU**.
* Fitted together, the return rests **7.84 degF** above the air and the
  warmed pipe cools back to that on **0.46 h**.
* The longest runs never brought hot water back: after 16 to 20 gal,
  the return still read 17 to 38 degF under the tank's upper probe.
  The fitted volume (19.4 gal) is therefore above the typical 4 minute
  run (5.9 gal), and a run takes heat as long as it runs.

The fitted volume of the same loop grew between two measurements:

* **August.** Measured from the loop's flow and the difference between
  the tank's upper probe and the return temperature, a run removed a
  median **1,126 BTU** (18 runs, 2026-08-06 to 2026-08-08), about
  2.1 degF of the whole tank. The loop volume fitted on 64 runs then was
  3.59 gal.
* **September.** With runs less than 10 minutes apart merged, the loop
  fitted at **6.38 gal** on 2026-09-18, and a typical run removed about
  **5 degF** of the whole tank. The probes show about 0.44 of that
  (below), about 2 degF.

At about 5 degF of the tank, one run removes as much heat as the jacket
loses in about 7 hours with the tank 75 degF above the air, so three
runs a day match the jacket's whole daily loss (computed from the
figures on this page, not measured together).

Where a run's heat shows
------------------------

The probes do not see a run's heat evenly. Of 146 runs with no draw and
no heating, 2026-02-26 to 2026-09-24, 117 are classified below by the
gap before the run, ten minutes after each run:

.. list-table::
   :header-rows: 1
   :widths: 34 12 27 27

   * - Tank before the run
     - Runs
     - Lower probe
     - Upper probe
   * - Mixed, gap 1 degF or less
     - 48
     - -0.90 degF
     - -0.18 degF
   * - Gap 1-3 degF
     - 10
     - -3.87 degF
     - -0.27 degF
   * - Stratified, gap over 3 degF
     - 59
     - -7.02 degF
     - -0.36 degF

The upper probe's change is about its standby over the same ten minutes.
The lower probe's drop does not mix back: from 10 to 60 minutes after a
run it fell a further 0.45 degF (18 runs), no more than standby. In a
stratified tank the lower probe shows most of the cold return; in a
mixed one, little of it. The longer a tank the probes read as mixed has
stood, the more its lower probe falls: a median 0.7 degF after runs
within 3 h of a recovery (26 runs), and 3.6 degF after 14 h (5 runs).

Pooled over 136 windows at the 6.38 gal loop, the two probes' mean
fell by about **0.44** of the heat the loop measurement gives for the
runs (90 % CI 0.38-0.50, read 30 minutes after the last run,
2026-09-18). The loop measurement counts all the loop's flow as the
tank's, but the return feeds the mixing valve's cold port as well as
the tank's cold inlet, and how it splits between the two is not
measured. The 0.44 is that split and any shortfall of the probes
together. That share held from 15 minutes to 2 hours after a run. At
4 hours it read 0.56, on 32 windows.

Those figures price a run at the September loop with its return at the
air. At the current run model (19.36 gal, the return at the air plus
7.84 degF, the pipe cooling on 0.464 h), the share came out at
**0.263** on 165 windows from April to October, and 0.117 on the 50
since September. The layered tank carries a run's water through the
column, where the probes read the layers it reaches.

A run into a stratified tank can take the lower probe to its turn-on
setting while the upper probe has not moved, and the lower-tank trigger
then applies as it does after a draw (see :doc:`what-starts-a-recovery`).


The gap between the probes
==========================

A recovery leaves the tank mixed; draws and circulation runs open a gap,
with the lower probe below the upper. With nothing heating or drawing,
the gap closes exponentially on a time constant of about **59 h** (146
quiet windows that started with a gap of at least 2 degF; bootstrap 95 %
CI 47-94 h; fitted on 2026-09-22). A gap of 10 degF is about 9 degF
six hours later and about 6.7 degF a day later.

That fit takes the gap as relaxing alone. The layered tank has no gap
constant: the column's conductance (0.42 BTU/hr per degF end to end,
fitted with the losses) closes the gap, and the bottom's loss opens it
again while the tank is stratified. On the 59 quiet windows after
2026-09-18, its gap at each window's end had a mean squared error of
3.04 degF² (0.90-5.97).


Projecting the tank's cooling
=============================

On the 59 quiet windows after 2026-09-18, each walked from the layers
the record's replay leaves at its start, the probes' mean fell within
**0.081 degF an hour** (0.055-0.110) of the recorded fall. A projection
with nothing in it includes no draw and no compressor run: a draw takes
the tank below it, and a compressor run above it.


Limits
======

One unit, one installation, one loop. The losses are fitted on quiet
windows, draws and recoveries, and the clearest cold window, the 93.9-hour stretch, is one
episode. The heat per run and where it shows depend on
the loop's volume, its plumbing and where its return enters; on a loop
that returns elsewhere, the split between the probes will differ. The
projection's accuracy rests on 59 windows over five weeks.
