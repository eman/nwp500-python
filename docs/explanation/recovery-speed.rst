=======================
Recovery Speed and Cost
=======================

How long a heat-pump recovery takes, how much electricity it uses, and
what changes either, as measured on one NWP500-65. The heat pump puts
out about the same heat from the start of a recovery to the end. What
changes is the electricity it takes to do it, and how much of the tank
that heat is spread over.

.. contents::
   :local:
   :depth: 2


Summary
=======

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Observation
     - Value
   * - Heat-pump output
     - About **4,900 BTU/hr** into a mixed tank at 130-140 degF.
       Fitted on the air and the water together, it falls about 16
       BTU/hr per degF of water.
   * - Recovery time
     - A median **5.7-7.1 minutes per degF** the lower tank is short of
       the setpoint, so a deep recovery takes 250-400 minutes.
   * - Compressor power
     - Rises through a recovery, about **320 W** with the lower tank at
       70-95 degF to about **470 W** at 138-150 degF.
   * - Efficiency
     - Heat put into the tank per unit of electricity while it climbs,
       about **3.1** at 130-140 degF and **2.8** at 140-150 degF. Over
       whole recoveries against an energy meter, hold included,
       **2.76** pooled.
   * - Each compressor start
     - About **160 Wh** of electricity before the tank gains anything,
       less when it restarts within about an hour of its last stop.
   * - The air beside the heater
     - Warmer air speeds a recovery: about **56 BTU/hr per degF**, or
       **1.30x** from 54 to 75 degF.
   * - How much of the tank heats
     - About **0.44** of the tank's mass while it is stratified, and
       **0.96** once it has mixed.
   * - The start of a recovery
     - The lower tank does not hold when the compressor restarts within
       15 minutes of its last stop, and holds a median **22 minutes**
       before it climbs after more than 12 hours off.
   * - The end of a recovery
     - The compressor ran a median **10 minutes** past the lower tank
       reaching the setpoint, and the lower tank ended a median
       **0.9 degF past it**. A stop at that overshoot
       predicts the stop better than a fixed run-on.

The figures come from the unit's recorded status history and, for
energy, a meter on the heater's circuit, between 2025-12-28 and
2026-10-26. The dates are given with each result. The heat, power,
hold and run-on figures are measured by ``nwp500.sim.heat_pump_fit``
(``recovery_frame``, ``climb_heat``, ``power_blocks``,
``start_holds``, ``run_ons``) on 404 heat-pump recoveries, the
recoveries the simulator's fits read
(``sim.calibration.heat_pump_cycles``).


Heat output and power
=====================

**Heat.** Measured on the stretches of a recovery's climb with the
tank mixed (the upper probe within 1 degF above to 5 degF below the
lower) and no water in use, at least 20 minutes long: the probes' mean
is then the tank's, and the heat is the tank's mass (63.2 gal) times
the mean's rise, plus the jacket's loss as the shipped map's fit
priced it; refitted from 2026-04-16 with the layered tank's
4.45 BTU/hr per degF instead, the map moves 0.05 % at 65 degF air and
120 degF water (4,497 BTU/hr) and under 0.2 % across its span, its
water slope -16.1 per degF. 38 stretches, 3,059 minutes, 2025-12-28
to 2026-10-26:

.. list-table::
   :header-rows: 1
   :widths: 25 15 20 20 20

   * - Tank
     - Stretches
     - Heat into the tank
     - Compressor power
     - Heat per unit of electricity
   * - 130-140 degF
     - 33
     - 4,878 BTU/hr
     - 457 W
     - 3.14
   * - 140-150 degF
     - 4
     - 4,557 BTU/hr
     - 483 W
     - 2.77

A tank only mixes once a recovery has run a while, so below 130 degF
there is one stretch. Fitted over all 38, weighted by their minutes:
**4,499 + 55.5 x (air - 65) - 15.9 x (water - 120) BTU/hr**, with the
air between 61.2 and 88.7 degF.

The figure closes on the meter. Over the 28 draw-free recoveries mixed
at both ends, the heat the tank kept plus its loss, against the
electricity metered over the whole run, is 2.71 pooled; the meter's
own figure over 235 recoveries is 2.76 (below). The climb's 3.1 less
the hold, 18 % of those runs, gives about 2.5-2.7.

An earlier version of this page gave 4,176-4,328 BTU/hr, flat from a
lower tank of 70 degF to 150 degF. They were not reproduced, and they
do not close: at the power metered with them, 4,200 BTU/hr is an
efficiency of 2.7 while the tank climbs at 130-140 degF, no better than
the meter's 2.76 over whole recoveries, which include the hold's
minutes with no heat.

**Power.** Metered, in 10-minute blocks of the climb and the run past
the target, stratified or mixed, 6,462 blocks:

.. list-table::
   :header-rows: 1
   :widths: 40 30 30

   * - Lower tank
     - Compressor power
     - Air, median
   * - 70-95 degF
     - 324 W
     - 57.3 degF
   * - 95-110 degF
     - 361 W
     - 60.5 degF
   * - 110-120 degF
     - 386 W
     - 63.0 degF
   * - 120-138 degF
     - 429 W
     - 65.9 degF
   * - 138-150 degF
     - 465 W
     - 68.0 degF

The compressor draws about 45 % more power at the end of a recovery
than at the start, because it condenses against hotter water, while
its heat falls only about 0.3 % per degF of water. The efficiency
falls more than the heating rate.

``currentInstPower`` reports the whole unit, elements included: about
410 W with only the compressor running, about 5.1 kW with one element
alone, and about 5.5 kW with the compressor and the upper element
together (see :doc:`heating-elements`).


How long a recovery takes
=========================

From 290 recoveries in the record up to 2026-08-08, the median time per
degF of shortfall, with the shortfall measured at the lower tank from
the setpoint at the start of the recovery:

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Lower tank short by
     - Minutes per degF
   * - 20-30 degF
     - 7.1
   * - 30-36 degF
     - 6.8
   * - 36-45 degF
     - 6.2
   * - 45-60 degF
     - 5.7

So a recovery from deep in the tank runs 250-400 minutes. The rate is
nearly flat across the bands. Under 10 degF short the figure is not
useful: that band is where interrupted cycles sit, and it reaches
over 1,000 minutes per degF.

**A deep recovery on 2026-08-12**, after four days in ``VACATION``, ran
378 minutes for a 56.8 degF shortfall, 6.66 minutes per degF. That is
17 % slower than its band's median. The air beside
the heater was falling (81.9 to 67.3 degF), and the tank had fully
mixed, so both conditions that slow a recovery held at once.

**Energy Saver was not faster than Heat Pump** on the record. From
January to February, recoveries starting 15-35 degF short:

.. list-table::
   :header-rows: 1
   :widths: 20 25 15 20 20

   * - Month
     - Mode
     - Recoveries
     - Median duration
     - Median energy
   * - January
     - ``ENERGY_SAVER``
     - 19
     - 387 min
     - 2.69 kWh
   * - January
     - ``HEAT_PUMP``
     - 9
     - 295 min
     - 2.03 kWh
   * - February
     - ``ENERGY_SAVER``
     - 5
     - 260 min
     - 1.76 kWh
   * - February
     - ``HEAT_PUMP``
     - 17
     - 307 min
     - 2.01 kWh

The order flips between the two months, the element ran a median of
0 minutes in both modes, and Energy Saver was chosen on the coldest
days. No difference is claimed. :doc:`heating-elements` covers when the
element runs.


How fast each zone warms
========================

Draw-free stretches of the same history, by heat source:

.. list-table::
   :header-rows: 1
   :widths: 34 22 22 22

   * - Heat source
     - Upper probe
     - Lower probe
     - Evidence
   * - Heat pump alone
     - +3 degF/h
     - +10 to +13 degF/h
     - 567 stretches, 51,500 min
   * - Upper element, alone or with the compressor
     - +121 to +123 degF/h
     - 0 to +20 degF/h
     - 3 stretches, 35 min
   * - Lower element alone (``ELECTRIC``)
     - -13 degF/h
     - +92 degF/h
     - 3 stretches, 35 min

The heat pump warms the bottom of the tank, where its condenser coil
is. The upper element works on a small top zone: at about 122 degF/h,
that zone holds roughly 41 Wh per degF, about a quarter of the tank.
Ten minutes of the upper element adds roughly 14-20 degF to the upper
probe, where the heat pump adds under 1 degF in the same time.


How much of the tank heats
==========================

The lower probe climbs fast at first and then slows, because the heat
is spread over more water as the tank mixes. Measured over 269
recoveries from 2025-12-28 to 2026-08-12, as the share of the tank's full mass the heat goes into:

.. list-table::
   :header-rows: 1
   :widths: 40 30 30

   * - Upper minus lower probe
     - Share of the tank
     - Minutes
   * - -5 to 1 degF (mixed)
     - 0.958
     - 28,789
   * - 1 to 3 degF
     - 0.699
     - 3,879
   * - 6 to 10 degF
     - 0.475
     - 2,652
   * - 40 to 80 degF (stratified)
     - 0.435
     - 1,228

While the tank is stratified, the compressor heats the lower zone, a
little under half the tank, and the lower probe rises quickly. A
recovery mixes the tank within about its first third, and from there
the whole tank heats as one body, at about half the rate on the lower
probe. 57 % of all heating minutes were in the mixed state. A recovery
that starts from a tank that is already mixed, as after a long idle
period, is the slowest kind.


The air beside the heater
=========================

**Warmer air speeds a recovery.** On the mixed climbs above, the heat
rose 55.5 BTU/hr per degF of air, about 1.2 % per degF: **1.30x** from
54 to 75 degF, the lower end extrapolated from 61.2 degF. Over 217
recoveries with the lower tank 10 degF or more short, the lower tank's
heating rate, stratified tank included, rose about 0.75 % per degF of
air (1.18x from 53.6 to 75.1 degF). The compressor's power mid-cycle
was flat across the air range, a median 392-431 W.

The air matters more to the electricity than to the time. Over whole
recoveries, metered (below), heat per unit of electricity was 2.50 with
the air below 65 degF, 2.84 between 65 and 75 degF, and 3.12 above
75 degF.


Electricity per recovery
========================

Against an energy meter on the heater's circuit, 235 recoveries of at
least 300 Wh, up to 2026-09-18, counting the heat the tank kept plus
the heat draws took out during the recovery:

* **Heat per unit of electricity: 2.76 pooled**, 2.09-3.30 from
  recovery to recovery (10th to 90th percentile). 2.98 with the tank
  averaging 125-130 degF, 2.76 at 130-140 degF.
* **Each compressor start costs about 160 Wh** (162 Wh fitted) before
  the tank gains anything: warming the refrigerant circuit and the
  condenser. It is a cost per start, not per unit of heat, so it is a
  third of the electricity of a short top-off from a hot tank.
* **A warm restart costs less.** A compressor restarting within about an
  hour of its last stop spends about 100 Wh less starting. Fitted on
  240 recoveries up to 2026-09-26, a start-up costs about 202 Wh from
  cold and 63 Wh at an immediate restart. The record held only 10
  restarts within an hour, so that difference is not settled.

To price a recovery from the whole-recovery figures above, divide the
heat to be stored by the efficiency at the tank and air temperatures it
will run at. Those figures already include the start-up, so don't add
it again. :doc:`tank-energy` gives the heat a tank is short.


The start of a recovery
=======================

At a compressor start the lower tank dips, then holds while the
refrigerant circuit and the condenser warm, and only then climbs. The
hold is longer the longer the compressor has been off. There were 94
starts with no water in use from 30 minutes before to the end of the
hold, 2025-12-28 to 2026-10-26. For the 84 of them with the time off
known and a climb, the minutes until the lower tank read above its
reading from before the start and stayed above it for 5 minutes
(``heat_pump_fit.start_holds``):

.. list-table::
   :header-rows: 1
   :widths: 40 15 20 25

   * - Compressor off for
     - Starts
     - Hold, median
     - Middle half
   * - Under 15 minutes
     - 8
     - 0 min
     - 0-1 min
   * - 15 minutes to 1 hour
     - 12
     - 5 min
     - 3-5 min
   * - 1-3 hours
     - 7
     - 10 min
     - 7-11.5 min
   * - 3-12 hours
     - 14
     - 18 min
     - 13.25-28.5 min
   * - Over 12 hours
     - 43
     - 22 min
     - 15.5-28 min

A probe at rest flips a 0.18 degF step and back, so a climb counts
only once it holds for 5 minutes. Counting the first step instead, as
an earlier version of this page did over 121 starts to 2026-09-26
(3.0, 4.5, 11.5, 11.4 and 17.8 minutes), gives 6 minutes at 3-12 hours
and 18 beyond.

A short top-off after a long idle spends much of its run in this hold,
and the start-up energy above goes into the same warming.


The end of a recovery
=====================

The compressor stops after the lower tank has passed the setpoint,
not when it reaches it. Over the 31 draw-free recoveries to 2026-10-26
that reached an unchanged setpoint (``heat_pump_fit.run_ons``), it ran
on for a median **10 minutes** after the lower tank first read the
setpoint, 2-15 minutes across them, and the lower tank ended a median
**0.9 degF past the setpoint**, -0.5 to 1.4 degF. Judged leaving each
recovery out of its own median, on the 30 whose run-on climbed, a stop
at that overshoot puts the stop 2.4 minutes from the recorded one on
average, and a fixed 10-minute run-on 3.3 minutes: the stop follows the
tank, not the clock. The record does not mark TOU windows, so a run-on
a window cut short counts too. A setpoint lowered to within
that margin of the lower tank during a recovery did not stop it (one
run, 2026-09-21; see :doc:`what-starts-a-recovery`).

Inside a TOU window the device ends a recovery short of the setpoint
instead (see :doc:`tou-recovery-cap`).


Limits
======

One NWP500-65, at one installation, with the air beside the heater
between about 54 and 88 degF. Deep recoveries were rare: 10 of 283
metered recoveries in a year started with the tank averaging 125 degF
or less, so the efficiency figures rest mostly on top-offs from a warm
tank. The Energy Saver comparison is small and confounded by the
weather. The warm-restart figure rests on 10 restarts. :doc:`simulator`
uses these behaviours, and its accuracy against this unit's record is
given there.
