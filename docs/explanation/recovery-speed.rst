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
     - About **4,200-4,500 BTU/hr**, flat from the start of a recovery
       to the end.
   * - Recovery time
     - A median **5.7-7.1 minutes per degF** the lower tank is short of
       the setpoint, so a deep recovery takes 250-400 minutes.
   * - Compressor power
     - Rises through a recovery, about **320 W** with the lower tank at
       70-95 degF to about **470 W** at 138-150 degF.
   * - Efficiency
     - Heat put into the tank per unit of electricity falls from about
       **3.7 to 2.6** through a recovery. Over whole recoveries against
       an energy meter, **2.76** pooled.
   * - Each compressor start
     - About **160 Wh** of electricity before the tank gains anything,
       less when it restarts within about an hour of its last stop.
   * - The air beside the heater
     - Warmer air speeds a recovery a little: about **1.18x** from 54
       to 75 degF.
   * - How much of the tank heats
     - About **0.44** of the tank's mass while it is stratified, and
       **0.96** once it has mixed.
   * - The end of a recovery
     - Outside a TOU window, the lower tank ran **1.1-1.3 degF past the
       setpoint** before the compressor stopped (5 of 5).

The figures come from the unit's recorded status history and, for
energy, a meter on the heater's circuit, between 2025-12-28 and
2026-09-26. The dates are given with each result.


Heat output and power
=====================

Over 269 recoveries from 2025-12-28 to 2026-08-12, measured each minute
as the heat the whole tank gained:

.. list-table::
   :header-rows: 1
   :widths: 25 25 25 25

   * - Lower tank
     - Heat into the tank
     - Compressor power
     - Heat per unit of electricity
   * - 70-95 degF
     - 4,176 BTU/hr
     - 323 W
     - 3.67
   * - 110-120 degF
     - 4,328 BTU/hr
     - 386 W
     - 3.27
   * - 138-150 degF
     - 4,199 BTU/hr
     - 467 W
     - 2.63

**The output does not fall as the tank warms.** The compressor draws
about 45 % more power at the end of a recovery than at the start to
deliver the same heat, because it condenses against hotter water. The
efficiency falls, not the heating rate.

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

**The slowest recovery on record** ran 378 minutes for a 56.8 degF
shortfall, 6.66 minutes per degF, on 2026-08-12 after four days in
``VACATION``. That is 17 % slower than the band's median. The air beside
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
is spread over more water as the tank mixes. Measured over the same 269
recoveries, as the share of the tank's full mass the heat goes into:

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

**Warmer air speeds a recovery, but only a little.** Over 217
recoveries with the lower tank 10 degF or more short, the lower tank's
heating rate rose about 0.75 % per degF of air: **1.18x** from 53.6 to
75.1 degF. The compressor's power mid-cycle was flat across the air
range, a median 392-431 W: the compressor modulates its output
rather than following the air.

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
* **The gap between the tank and the air costs about 0.65 % per
  degF.** Heat per unit of electricity falls by that much for each degF
  the tank's mean sits further above the air.
* **Each compressor start costs about 160 Wh** (162 Wh fitted) before
  the tank gains anything: warming the refrigerant circuit and the
  condenser. It is a cost per start, not per unit of heat, so it is a
  third of the electricity of a short top-off from a hot tank.
* **A warm restart costs less.** A compressor restarting within about an
  hour of its last stop spends about 100 Wh less starting. Fitted on
  240 recoveries up to 2026-09-26, a start-up costs about 202 Wh from
  cold and 63 Wh at an immediate restart. The record held only 10
  restarts within an hour, so that difference is not settled.

To price a recovery: the start-up once, plus the heat to be stored
divided by the efficiency at the tank and air temperatures it will run
at. :doc:`tank-energy` gives the heat a tank is short.


The end of a recovery
=====================

Outside a TOU window, the compressor stops when the lower tank has
passed the setpoint, not when it reaches it. In 5 of 5 draw-free
recoveries in September 2026 the lower tank ran **1.1-1.3 degF past the
setpoint** before the compressor stopped. A setpoint lowered to within
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
