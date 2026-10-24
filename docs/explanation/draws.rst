==========================
Draws and Delivered Water
==========================

The tank probes are not the tap. On the installation measured, a
thermostatic mixing valve after the hot outlet delivered water 10-18 degF
cooler than the upper probe read, and the upper probe barely moved
through most of a long draw. This page gives what was measured at the
valve, at a tub spout, at the two tank probes and at a probe on the cold
supply, and what it means for any estimate of how much hot water is
left.

.. contents::
   :local:
   :depth: 2


Summary
=======

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Measurement
     - Observed
   * - Delivered temperature
     - A thermostatic mixing valve delivered **114-122 degF** on draws,
       rising about **0.49 degF per degF** of upper probe, and held it
       while the lower tank fell 23 degF.
   * - During a circulation run
     - The valve passed near-tank water, **125-133 degF**, 6-10 degF
       below the upper probe.
   * - At a tub spout
     - **12-19 degF below** the upper probe on average in three of four
       baths; 4.7 degF above it in the fourth.
   * - Pipe to a fixture
     - **2.4-2.9 gal** (42-49 s) between the valve and a tub spout.
   * - The probes through a draw
     - Over 16-41 gal the upper probe fell a median 1.08 degF and the
       lower probe 22.14 degF.
   * - Delivered water after the upper probe
     - The delivered water crossed 105 degF **5.3-7.3 gal after** the
       upper probe did (one bath).
   * - The cold supply
     - A probe on the cold supply read **71.3-73.1 degF** on long draws,
       and the air around it at rest.

All figures come from one NWP500-65 and one installation, between
2026-02-25 and 2026-10-02. Dates and times are local.


The delivered temperature
=========================

The valve was read by a dial thermometer on its outlet, to about
±1.5 degF. A reading counted when water had flowed for at least 180 s
with the circulation pump off, the first 60 s discarded; the plateau is
the median of the draw's last 3 minutes. Six draws on 2026-09-16 and 17
qualified:

.. list-table::
   :header-rows: 1
   :widths: 24 16 20 20 20

   * - Upper probe
     - Length
     - Delivered
     - Lower tank, start
     - Lower tank, end
   * - 123.8 degF
     - 460 s
     - 114.2 degF
     - 115 degF
     - 113 degF
   * - 125.8 degF
     - 450 s
     - 114.6 degF
     - 106 degF
     - 94 degF
   * - 130.5 degF
     - 450 s
     - 115.6 degF
     - 108 degF
     - 98 degF
   * - 139.6 degF
     - 180 s
     - 117.6 degF, still rising
     - 138 degF
     - 137 degF
   * - 139.5 degF
     - 440 s
     - 121.8 degF
     - 137 degF
     - 134 degF
   * - 138.2 degF
     - 580 s
     - 120.4 degF
     - 131 degF
     - 108 degF

* **The valve regulates.** In the last draw the lower tank fell 23 degF
  and the delivered water held at 120-121 degF.
* **Its output follows the tank.** A line through the five full plateaus
  is ``delivered = 53.56 + 0.485 * upper probe`` (degF), within 1.5 degF
  of each. The slope's 95 % interval is 0.29-0.68. Over 16 full-plateau
  draws up to 2026-09-26 it was 0.435 (0.23-0.64). The cold supply's
  temperature explains little of it.
* **During circulation the valve passes tank water.** On that
  installation the circulation return joins the cold line that feeds the
  valve's cold port, so with the pump running and no draw the valve has
  little cold water to mix. Four pump runs of 210-230 s peaked at
  125.0-133.2 degF, 6-10 degF below the upper probe, and were still
  rising when the pump stopped. A draw during a pump run was not
  measured.

A probe on a tub spout, over four baths from 2026-09-28 to 2026-10-02,
read on average 19.3, 12.0 and 11.9 degF below the upper probe in three
of them, and 4.7 degF above it in the fourth. The difference depends on
how hot the tank is. The pipe from the valve to the spout held 2.4,
2.4, 2.5 and 2.9 gal: the hot water took 42-49 s to reach the spout.


How the probes respond to a draw
================================

From 538 draws with the compressor off, 2026-02-25 to 2026-09-12, the
median change in each probe by volume delivered:

.. list-table::
   :header-rows: 1
   :widths: 30 14 28 28

   * - Delivered
     - Draws
     - Upper probe
     - Lower probe
   * - 1-2 gal
     - 185
     - -0.18 degF
     - -0.90 degF
   * - 2-4 gal
     - 88
     - -0.18 degF
     - -1.44 degF
   * - 4-8 gal
     - 55
     - -0.36 degF
     - -4.50 degF
   * - 8-16 gal
     - 163
     - -0.36 degF
     - -6.84 degF
   * - 16-41 gal
     - 47
     - -1.08 degF
     - -22.14 degF

Cold water enters at the bottom and rises as a front. The lower probe
sees it first; the upper probe holds near full until the front reaches
it, then falls quickly. In a 54 gal bath on 2026-10-02 the upper probe
fell to 104 degF. Both probes report in 0.18 degF steps, so a draw of
1-2 gal is about one step on the upper probe.

**The upper probe sits below the outlet.** In one bath on 2026-09-29,
the water at the tub spout crossed 105 degF 7.3 gal after the upper
probe did, and the water at the valve's outlet 5.3 gal after. Near
that line the delivered water fell by about 2 degF per gallon.

**A two-zone model of the probes has limits.** Fitted on the draws
before 2026-06-23 and scored on the draws after, a model of the lower
probe after a draw had a mean absolute error of 3.09 degF, against
5.32 for assuming no change. By draw:

.. list-table::
   :header-rows: 1
   :widths: 40 20 20 20

   * - Draws
     - n
     - Model
     - No change
   * - Long
     - 69
     - 5.33 degF
     - 9.73 degF
   * - Short
     - 84
     - 1.24 degF
     - 1.69 degF
   * - Tank well mixed (gap under 2 degF)
     - 90
     - 3.32 degF
     - 3.67 degF
   * - Gap over 10 degF
     - 27
     - 2.20 degF
     - 5.43 degF

A well-mixed tank, the usual state overnight, gains least. The gap a
draw opens grows faster than the volume: per gallon it is larger for
the biggest draws.

The upper probe is harder. Over 563 draws of 5 gal or more in 204 days,
a two-zone model's upper zone, moved only by each draw's calibrated
response, ran too warm by a mean of 0.22 degF over the first 5 gal,
9.1 degF at 30-40 gal and 19.0 degF past 40 gal. Tracking the heat a draw takes
from the top of the tank, as the simulator's heat book does
(:doc:`simulator`), is what lets an estimate see the tank run out.


How much hot water is left
==========================

Four bath tests, 2026-09-28 to 2026-10-02, each scored an estimate
made before the tap opened against the gallon at which the spout fell
below 105 degF:

* Two baths did not run cold, and the estimate said so.
* One, bath B, ran cold 5.2 gal later than estimated: a cautious answer.
* One ran cold after 39.4 gal against an estimate of 56.6, an
  over-promise of 17.2 gal. The compressor ran through it.

A second scoring used the gallon at which the valve outlet, not the
spout, fell below 105 degF. Three draws crossed there: bath B, the bath
that ran cold after 39.4 gal, and a later drawdown of the tank. Their
estimates against the outlet's crossing were 30.3 gal against 28.6,
56.9 against 39.9 and 1.6 against 8.6: a mean 3.9 gal over, and a
worst over-promise of 17.0 gal. With the inlet read from long-draw
plateaus (next section) instead, they were 26.3, 49.3 and 2.4: a mean
0.3 gal over, and a worst over-promise of 9.4 gal. Three events say
little about the level.

Without a full tank in the last 72 hours for the heat book to count
from, the estimate reads the tank's heat from its two probes, as the
book's anchor does, and adds the lag to the delivered water (5 gal by
default). It does so for any state with the upper probe at or above the
line, the probes together or apart, the heater running or not. Two
drawdowns from uniform tanks delivered what the probes said, net of the
heat added during them, and one from 136.4/111.4 degF (upper/lower)
delivered 31.1 gal where the probes said 34.5.

Evidence, where the caller has it, can raise the estimate: the longest
draw the history shows from a tank in the same state or colder, counted
to the upper probe's crossing. That is a low figure. No clean recorded
draw took the upper probe below 105 degF (the lowest reached
107.2 degF), so for a full tank that had filled a 38 gal bath the
evidence gives 33.4 gal at the probe. Its assumption, that a tank no
colder delivers at least as much, failed on small differences: 15 of 22
later draws over-promised for a 2 degF fall.

The probes over-read a tank whose upper element has just heated a thin
top over a spent tank. On 2026-04-14 a draw from 139.6/78.4 degF
stayed above 129 degF for 15.7 gal, where the probes say 15.3. Ninety
minutes later a six-minute upper element run took the upper probe from
126 to 141 degF, and a 10 gal draw from 141.3/89.6 degF took it to
101 degF, where the probes say 22.9. The heat book answers it: it
counts that element's 1,757 BTU, about four delivered gallons, on top
of what the first draw left, where the probes alone can't tell that top
from a full one. From the book the second draw read 15.7 gal at its
start against 14.3 delivered to the crossing, net of the heat added,
the lag included.
The heat book's catch of recorded depletions is in :doc:`simulator`,
under Accuracy.


Reading a cold-supply probe
===========================

The heater's own inlet field reads 0 (:doc:`unknown-values`), so the
inlet needs its own probe. One on the mains side, upstream of where a
circulation return joins, behaved as follows from 2026-09-19:

* **At rest it reads the air around the pipe**: a median 1.3 degF above
  it, 15-30 minutes behind.
* **A draw reaches it within about 50 s**, then a dip and a bump over
  the first 4 minutes as the water standing in the house pipe passes,
  then it settles from above for several more minutes. A 2-minute window
  from minute 9 was within 0.3 degF of everything after it.
* **So a plateau is the median of a draw's last 2 minutes, none before
  minute 9, and a draw needs 11 minutes to have one.** Seven of eleven
  long draws did. Their plateaus were 71.3-73.1 degF, median 72.4 degF,
  and moved only 0.082 degF per degF of air across air at 65.9-85.4 degF.
* **Count only draws a meter saw.** With the pump off and no metered
  flow, the probe reads the air. A flow of at least 0.3 gal/min over the
  window qualifies.

The at-rest reading misleads. On later draws the plateaus sat at
71.2-72.8 degF, while the probe's 3-hour median ran 3.4 degF below them
with the air under 68 degF and 5.7 degF above them with the air over
80 degF. Converting heat to gallons at that median swung the gallons
available by 10-20 %. :doc:`/how-to/simulate-heater` reads the plateau.


Limits
======

One heater, one valve and one plumbing layout: another installation's
valve setting, pipe runs and circulation will differ, and the readiness
defaults are this one's (:doc:`/reference/simulator-inputs`). The valve
line rests on five plateaus read from a dial, the hot-tank ones all
from one evening. Draws were 0.9-1.4 gal/min. The tub figures come from
four baths. The cold supply was measured in September and October
only; how the mains moves through the year was not.
