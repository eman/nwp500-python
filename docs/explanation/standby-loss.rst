=============
Standby Loss
=============

A tank that is not heating loses heat two ways: through its jacket to the
air beside the heater, and, where the hot water line has a recirculation
loop, to each run of the loop's pump. On the unit measured, the jacket
loss grows with the difference between the tank and the air, and a
circulation run removed more heat in a few minutes than the jacket does in
hours. Most of that run's heat shows on the lower probe, not the upper.

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
     - ``UA`` of about **3.3 BTU/hr per degF** with the tank 13 degF above
       the air, rising to about **5.0** at 85 degF. For a 140 degF tank
       in 65 degF air that is about **0.7 degF an hour**.
   * - A circulation run
     - About **5 degF** of the whole tank for a typical run at the loop
       volume fitted in September (6.38 gal), of which the probes show
       about 0.44. In August, at a smaller fitted loop, a median
       1,126 BTU (about 2.1 degF).
   * - Where a run's heat shows
     - Ten minutes after a run, the lower probe had fallen **0.9 degF** in
       a mixed tank and **7.0 degF** in a stratified one. The upper probe
       moved no more than standby alone.
   * - The gap between the probes
     - With nothing heating or drawing, it closes on a time constant of
       about **59 h**.

All figures come from one NWP500-65 and its recorded status history to
2026-09-24, with the air beside the heater measured separately. The
circulation figures are that installation's loop.


The jacket loss
===============

The tank loses heat to the air at a rate ``UA * (T_tank - T_air)``. On
this unit ``UA`` is not a constant: it rises with the difference between
the tank and the air. Fitted on 301 quiet windows (no draw, no heating,
no circulation run) covering a tank-to-air difference of 11.2 to
90.7 degF continuously, to 2026-08-12:

``UA(dT) = 4.47 * (dT / 50) ^ 0.227`` BTU/hr per degF

Across the 301 windows ``UA`` averaged 4.87 BTU/hr per degF (standard
deviation 1.26). The same rule, refitted on 393 windows to 2026-10-11,
gave ``4.61 * (dT / 50) ^ 0.186``, the simulator's default
(:doc:`/reference/simulator-inputs`); the law has moved steadily that
way as windows accrued. Computed from the fit, with the tank's thermal mass of
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
October 2026 the fitted ``ua_ref`` was:

.. list-table::
   :header-rows: 1
   :widths: 25 25 25 25

   * - Wait after the last event
     - Quiet windows
     - Mean window ``UA`` (sd)
     - ``ua_ref``
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
losing heat for as long as the pump runs: on this installation the heat
book charges 159 BTU for each gallon circulated. Runs less than 10
minutes apart count as one, because the loop has not cooled in between.

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


Projecting the tank's cooling
=============================

Standby projections made with this model were scored against what the
tank did, over the day and a half of projections available on
2026-09-22, at horizons of 1 to 24 hours. With no draw and no compressor
run in between, the lower probe's mean absolute error was **0.86 degF at
1 hour** and **1.41 degF at 3 hours**. With a draw or a compressor run
in between it was 9.15 and 13.99 degF. A projection with nothing in it
includes neither: a draw takes the tank below it, and a compressor run
above it.


Limits
======

One unit, one installation, one loop. The jacket law is fitted on quiet
windows, and the clearest cold window, the 93.9-hour stretch, is one
episode. The heat per run and where it shows depend on
the loop's volume, its plumbing and where its return enters; on a loop
that returns elsewhere, the split between the probes will differ. The
projection's accuracy rests on a day and a half of projections.
