===========================
What Starts a Recovery
===========================

A heat-pump recovery does not only start when the lower tank cools to its
turn-on setting. On the unit measured, about half of all compressor starts
had the lower tank above that setting, and about four in five of those
followed a **control write**: a setpoint change or an operation-mode
change, made by anyone. The device behaves as if it re-evaluates whether
to heat whenever it is told something new.

This matters to anything that writes to the heater on a schedule. A write
is a possible start, and holding the heater off takes more than lowering
one threshold.

.. contents::
   :local:
   :depth: 2


The short version
=================

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Trigger
     - Observed behaviour
   * - Lower tank at its turn-on setting
     - Outside a TOU window, ``hp_lower_on_temp_setting`` read
       **104.9 degF** at every setpoint from 107.6 to 149 degF. It does
       not follow the setpoint.
   * - A TOU window
     - ``hp_upper_on_temp_setting`` is raised to the setpoint. At the
       window's opening the upper tank can start a cycle, and the lower
       trigger waits for the window to close.
   * - A setpoint write
     - Outside a TOU window, a write that leaves the upper tank below the
       new setpoint started the compressor within 2 minutes in **112 of
       117** writes, typically **30 s** after it, raises and lowerings
       alike.
   * - A mode write
     - With the compressor off, **46 of 81** mode writes (57 %) started
       it within 2 minutes. ``ELECTRIC`` started an element instead.
   * - Stopping mid-cycle
     - A setpoint lowered well below the upper tank stopped the running
       compressor within **5 s**. Restoring it called for heat within
       5 s, and the compressor started **2 min 34 s** later.

All figures come from one NWP500, from its recorded status history
(2025-12-28 to 2026-09-22) and from deliberate device tests between
2026-09-19 and 2026-09-21. Dates and times are local.


The thermostat triggers
=======================

The lower tank
--------------

Outside a TOU window, both ``hp_lower_on_temp_setting`` and
``hp_upper_on_temp_setting`` read 104.9 degF at every setpoint in the
history, from 107.6 to 149 degF. **The lower-tank trigger does not move
with the setpoint.** Lowering the setpoint to hold the heater off
therefore does nothing to this trigger.

Inside a TOU window
-------------------

While a TOU window is in force, ``hp_upper_on_temp_setting`` equals the
setpoint, with a differential of 2.9 degF. This is the in-window marker
:doc:`tank-energy` describes. ``hp_lower_on_temp_setting`` also followed
the setpoint in-window from December to March, and has not since April.
On this unit the window is the TOU schedule's highest-priced period. It
opened at 14:00 or at 16:00, depending on the time of year, and closed at
21:00.

From every heat-pump start since 2026-04-08:

* **At the window's opening, a start followed when the upper tank was well
  below the setpoint.** All 19 openings with the upper tank more than
  13.7 degF short started a cycle, and none of the other 50 did. The
  boundary lies somewhere between 11.9 and 15.5 degF.
* **Later in the window, no simple threshold predicts a start.** From
  June, 10 window-days had a start inside the window. A 13.7 degF rule
  caught 5 of them, and the upper tank was a median 10.8 degF short at
  those starts.
* **The lower-tank trigger waits for the window to close** (9 of 9).

**"Upper tank below** ``hp_upper_on_temp_setting`` **" is a condition,
not a predictor.** In-window that setting equals the setpoint, so the
condition holds for most of any window in which the tank is not full. It
held at 11 % of starts, and at 16.7 % of random compressor-off minutes.


A setpoint write re-evaluates
=============================

From 260 setpoint writes in ``HEAT_PUMP`` with the compressor off:

* **Outside a TOU window**, a write that leaves the upper tank **below the
  new setpoint** started the compressor within 2 minutes **112 times in
  117**, whatever the lower tank read. That includes lowering the setpoint:
  48 of 49 writes that lowered it but left it above the upper tank started
  a recovery. The delay is a median **30 s** (IQR 25-31 s). Writes that
  left the new setpoint at or below the upper tank started it in 2 of 3,
  too few to say.
* **Inside a TOU window**, a write that put the setpoint 2 degF or more
  **below** the upper tank never started it (0 of 8). One that left the
  upper tank 4 degF or more short almost always did (57 of 58). In
  between, about 70 % did.
* **A reservation entry's setpoint is such a write.** On 2026-09-21 at
  21:43, after the window, an entry lowered the setpoint from 141.8 to
  137.3 degF with the upper tank at 135.5 degF. The device called for
  heat in the same poll: ``current_heat_use`` went to the heat pump. The
  setpoint was restored 6 s later, so whether the compressor would then
  have started is not recorded. At 141.8 degF the same tank had sat
  6.3 degF short without a call.

The device does not distinguish who made the write: the manufacturer's
app, a script and a reservation entry all behave the same.


A mode write re-evaluates
=========================

Of 165 operation-mode writes (``dhw_operation_setting``) since
2026-04-08, **81** were made with the compressor already off, and **46**
of those (57 %) started it within 2 minutes. Adjacent writes sometimes
share a start, so the 46 writes account for 36 distinct starts. By chance,
a 2-minute window would hold a start 0.13-0.27 % of the time, by three
separate estimates: the naive rate, random compressor-off minutes, and
circular shifts of the whole write series.

.. list-table::
   :header-rows: 1
   :widths: 34 33 33

   * - Mode written
     - Compressor within 2 min
     - Element within 2 min
   * - ``HEAT_PUMP``
     - 34 / 47
     - 7
   * - ``HIGH_DEMAND``
     - 4 / 5
     - 3
   * - ``ENERGY_SAVER``
     - 7 / 11
     - 9
   * - ``ELECTRIC``
     - **0 / 6**
     - **5**
   * - ``VACATION``
     - 1 / 10
     - 2
   * - ``POWER_OFF``
     - 0 / 2
     - 0

``ELECTRIC`` is the clearest case. It never started the compressor, but in
5 of its 6 writes an element came on 4-6 s later: the device heated with
whatever the new mode uses. ``VACATION`` and ``POWER_OFF`` suppress
heating, and rarely started either (``VACATION`` 1 in 10).

A mode written inside a TOU window may be held rather than applied. See
:ref:`reservations and mode writes during a tou window`.


Every start, classified
=======================

246 compressor starts from 2026-04-08 to 2026-09-17, with starts less
than 30 minutes apart merged, tested against the rules above in this
order:

.. list-table::
   :header-rows: 1
   :widths: 60 20 20

   * - Condition at the start
     - Starts
     - Share
   * - Lower tank at or below its turn-on setting
     - 125
     - 50.8 %
   * - Within 2 min of a setpoint write
     - 83
     - 33.7 %
   * - Inside a TOU window, upper tank below
       ``hp_upper_on_temp_setting``
     - 18
     - 7.3 %
   * - A control write shortly before (ten of eleven a mode write)
     - 11
     - 4.5 %
   * - A deliberate device test
     - 7
     - 2.8 %
   * - A draw or pump run, lower tank above its turn-on
     - 2
     - 0.8 %

**Read the shares as one ordering, not as the data.** The conditions
overlap: 139 of the 246 starts satisfy more than one, so the shares move
with the order they are tested in. The order-independent result is that
**every start satisfies at least one documented condition**. The 11 that
satisfy none of the thermostat or setpoint rules all follow a control
write, within 22-34 s except one at 194 s. That is the same signature as
a setpoint write.


Stopping and restarting mid-cycle
=================================

Two setpoint drops on the morning of 2026-09-21, outside the window, with
the compressor running:

* **Well below the upper tank, it stops.** Lowered from 141.8 to
  114.8 degF with the upper tank at 123.1 degF, the compressor stopped
  within **5 s**. Restoring 141.8 degF called for heat within 5 s, and the
  compressor started **2 min 34 s** later.
* **Just above the upper tank, it doesn't.** Lowered to 124.7 degF with the
  upper tank at 123.8-124.2 degF, the compressor kept running for the
  50 s observed.

How far below the tank a setpoint must go to stop a running compressor is
not mapped. A restore is also a start: putting a higher setpoint back is
the same as a write above the tank.


What a lowered setpoint holds off
=================================

* **In-window, nothing started, but for a reason this run can't isolate.**
  On 2026-09-20 the setpoint was lowered to 107.6 degF at 17:48, inside the
  window, and nothing started before the window closed at 21:00, although
  the lower tank fell to 86.7 degF. The lowered setpoint (the in-window
  upper setting follows it down) and the in-window deferral of the lower
  trigger both explain it. An Energy Saver command was also outstanding
  throughout (see :ref:`reservations and mode writes during a tou
  window`), so the device's effective mode is uncertain.
* **A start driven by a draw, no.** On 2026-09-21, with the setpoint still
  107.6 degF, a recirculation-pump run on a cooled loop (a draw on the
  tank) took the lower zone from 88 to 84 degF between 06:54 and 06:56.
  The heat pump started at 06:55:55, with the lower zone at 86.2 degF. The
  lower-tank setting stays at 104.9 degF whatever the setpoint. The device
  was in ``ENERGY_SAVER`` by then (the held mode had taken effect at
  21:00), so for ``HEAT_PUMP`` this is inferred, not measured.
* **A lower zone that is merely low does not always start it.** Before
  that pump run, the lower zone had sat near 87 degF for about 10 hours,
  below its 104.9 degF setting, without a start, also in
  ``ENERGY_SAVER``. A further fall did start one. The rule is therefore
  not a simple level test on the lower probe. This is one observation,
  and the mechanism is not established.

To hold the heater off with the setpoint, put it **at least 2 degF below
the upper tank**: inside a window, none of 8 such writes started the
compressor. Closer than that, and outside a window, it is not
established. Expect a draw to start the heater anyway.


Working with it
===============

* **Treat every control write as a possible start.** That includes a
  restore, a setpoint lowered as a hold-off unless it is well below the
  upper tank, and a mode change to anything that heats.
* **Confirm by reading back, not by the command's return.** Read
  ``dhw_target_temperature_setting``, ``dhw_operation_setting`` and
  ``comp_use`` afterwards. Inside a TOU window a mode's read-back is
  itself unreliable, because the device may be holding it (see
  :ref:`reservations and mode writes during a tou window`).
* **Don't predict starts from the lower threshold alone.** On this unit
  that misses about half of them.


Reading the history yourself
============================

Two traps, both of which moved results when this was first measured:

* **The turn-on settings report only on change,** sometimes not for
  months. Carry them forward without a staleness limit. A 72-hour cut
  dropped ``hp_lower_on_temp_setting`` for 99 of the 246 starts and
  silently moved them into "unexplained".
* **Settings arrive as a batch with one shared timestamp.** When
  attributing a start to the nearest write, read the whole batch, not
  whichever row sorts last. A write that appears as
  ``hp_upper_off_temp_setting`` is usually a setpoint write under another
  name: it equals ``dhw_target_temperature_setting`` at 96.8 % of
  change-points.


Limits
======

One unit, one household, one TOU schedule. The record mixes the
manufacturer's app, test scripts and the device's own schedule, which is
part of the finding: the device does not care who wrote. The mid-cycle,
hold-off and after-window results each come from a single run. The
shoulder period was not tested.
