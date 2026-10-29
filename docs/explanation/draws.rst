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
probe did, and the water at the valve's outlet 5.3 gal after, each net
of the pipe from the tank to its thermometer. The gap is the tank water
above the probe; the two figures differ because the spout read
2.74 degF above the gauge. Near that line the delivered water fell by
about 2 degF per gallon.

**The lower probe's response follows the gap.** The same draw moves
the lower probe further the wider the gap between the probes when it
starts.

The simulator's layered tank tracks the water itself: a draw pushes the
column up through an inlet zone (12.2 gal fitted on the whole record)
and out of the top, and the probes read the layers where they sit
(:doc:`simulator-methodology`). On the 46 metered draws after
2026-09-18, each followed for an hour from the layers the record's
replay leaves at its start, fitted on the record before them, its
upper probe's RMS error was 0.299 degF (0.192-0.463) and its lower
2.08 (1.42-2.84). Tracking the water a draw takes from the top of the
tank is what lets an estimate see the tank run out.


How much hot water is left
==========================

Four bath tests, 2026-09-28 to 2026-10-02, recorded the gallon at which
the spout fell below 105 degF, and the gallon at which the valve's
outlet did. Two baths did not run cold. A third crossed at the outlet
after 28.6 gal; the fourth ran cold at the spout after 39.4 gal and at
the outlet after 39.9, with the compressor running through it; and a
later drawdown of the tank crossed at the outlet after 8.6 gal. The
layered tank's estimate has not yet been scored against them.

The estimate reads the tank's layers: the water leaving the top in
turn, each gallon through the mixing valve, to the first the valve
delivers under the line (:doc:`simulator-methodology`). The layers are
what the last day's record leaves (the probes, the compressor and the
elements, the metered draws and the circulation's runs, replayed), with
the probes laid over them. Without a record they are the profile the
two probes stand for, and the answer says so
(``tank_profile_estimated``).

The record has few draws that cross the line. Of 34 deliveries held out
of the fit, none crossed, so each delivered at least its gallons: an
estimate under them is an under-promise. From the replayed layers 3 %
were under-promised, by 1.17 gal on average across all 34 (0-3.40);
from the probes alone, also 3 %, by 0.91 gal (0-2.66). Only three
draws in the whole record took the
upper probe across the line, each with the compressor running. On two,
the model's own crossing of the probe came at 26.1 and 31.3 gal against
the recorded 23.3 and 31.3; the third started below the line. The tap
crosses later than the probe: the water above the probe still leaves
hot. From the layers the estimates at the tap were 34.3 and 44.0 gal,
against 29.2 and 62.0 from the probes alone.

The probes alone over-read a tank whose upper element has just heated a
thin top over a spent tank. On 2026-04-14 a draw from 139.6/78.4 degF
(upper/lower) stayed above 129 degF for 15.7 gal. Ninety minutes later
a six-minute upper element run took the upper probe from 126 to
141 degF, and a 10 gal draw from 141.3/89.6 degF took it to 101 degF.
Two probes can't tell that top from a full tank. The replayed layers
can: the element's heat goes into the layers at and above it, over the
cold the first draw left below.


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

.. _mains-by-season:

The mains by season
-------------------

The installation's ``draw.inlet_temp_f``, 72.4 degF, is the median of
those September plateaus, and the mains moves with the season:

* **October.** The plateaus fell about 0.085 degF a day, from 72.5 degF
  on 2026-10-01 to 69.3-69.6 degF by 10-20.
* **January and February.** There was no probe yet, but the lower probe
  bounds the mains: no water in the tank is colder than the water let
  in. On the deepest draws since the probe went in, the lower probe
  bottomed out at least 5 degF above the plateau. In January and
  February it fell to 68.0 and 69.4 degF, so the mains then was at most
  that, and likely nearer 63-64 degF.

Every 1 degF of inlet moves a delivered gallon's heat by about 2 %, so a
winter mains 9 degF under September's makes each draw take about a fifth
more heat than September's says.

So the mains are placed by the day from the climate
(``cold_supply.mains_f``): Burch and Christensen's correlation of a
utility's water with the year's outdoor air, which the Building America
House Simulation Protocols and EnergyPlus use. It takes the year's mean
air and the spread between the warmest and coldest monthly means; the
water runs 6 degF over the mean air and swings with it, damped and
lagging more in a colder climate.

The installation's weather station read a mean of 61.3 degF and a
spread of 19.9 degF over 2025-11 to 2026-10. From them the correlation
gave:

* **September and October:** a mean 1.5 degF under the plateaus over 25
  days of 2026-09-20 to 10-28 (0.1-3.9 degF), and 0.8 degF under from
  10-20 on, the probe's indoor pipe run included. September's 72.4 degF
  held all year was 4.4 degF over the plateau by 10-28.
* **The year:** 61.6 degF in early February to 73.0 degF in early
  August.
  The winter low, with the 1.5 degF the probe reads over it, is the
  63-64 degF the lower probe points to.

The installation's parameters carry that climate
(``draw.climate_f``). ``default_params``, for another installation,
carries none, and its mains are the rating test's 58 degF all year:
colder than most of the year's mains away from the northern tier, so
its draws err the safe way. Give your own climate, or
``Environment.inlet_f`` from a probe (:doc:`/how-to/simulate-heater`).


Limits
======

One heater, one valve and one plumbing layout: another installation's
valve setting, pipe runs and circulation will differ, and the readiness
defaults are this one's (:doc:`/reference/simulator-inputs`). The valve
line rests on five plateaus read from a dial, the hot-tank ones all
from one evening. Draws were 0.9-1.4 gal/min. The tub figures come from
four baths. The cold supply was measured in September and October
only; how the mains moves through the rest of the year is the
correlation's, checked against the lower probe's winter bound alone.
