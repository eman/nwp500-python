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
     - A median **1,126 BTU** per run, about 2.1 degF of the whole tank,
       measured from the loop's flow and temperatures.
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
deviation 1.26). Computed from the fit, with the tank's thermal mass of
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


Circulation runs
================

A recirculation pump replaces the cooled water standing in the loop with
hot water from the tank. On this installation the loop returns into the
cold line at the tank's **cold inlet**, so the cooled water reaches the
tank at the bottom.

How much heat a run removes
---------------------------

Measured from the loop's flow and the difference between the tank's
upper probe and the return temperature, a run removed a median
**1,126 BTU** (18 runs, 2026-08-06 to 2026-08-08), about 2.1 degF of the
whole tank. A run displaces the water standing in the loop and then
recirculates water it has already warmed, so a run costs at most about
one loop volume of water heated from the air to the tank. Its cost
depends on the loop's volume and the tank-to-air difference. Runs less
than 10 minutes apart cost about one run between them, because the loop
has not cooled in between.

Compared with the jacket table above, a few runs a day remove heat of
the same order as the jacket's whole daily loss (computed from the two
figures, not measured together).

Where a run's heat shows
------------------------

The probes do not see a run's heat evenly. On 146 runs with no draw and
no heating, 2026-02-26 to 2026-09-24, ten minutes after each run:

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
stratified tank the cold return lands in the lower probe's zone. In a
mixed one most of it sits below the probe. A tank the probes read as
mixed still holds water that cooled below the lower probe while it stood:
the lower probe fell a median 0.7 degF after runs within 3 h of a
recovery (26 runs), and 3.6 degF after 14 h (5 runs).

Pooled over 136 windows, the two probes' mean fell by about **0.44** of
the heat the loop measurement gives for the runs (90 % CI 0.38-0.50, read
30 minutes after the last run, 2026-09-18). That share held from 15
minutes to 2 hours after a run.

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


Limits
======

One unit, one installation, one loop. The jacket law is fitted on quiet
windows, and the clearest cold window, the 93.9-hour stretch, is one
episode. The heat per run and where it shows depend on
the loop's volume, its plumbing and where its return enters; on a loop
that returns elsewhere, the split between the probes will differ.
