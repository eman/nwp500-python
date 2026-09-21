====================
The Heating Elements
====================

The NWP500 publishes four element thermostat settings -
``heUpperOnTempSetting``, ``heUpperOffTempSetting`` and their lower-zone
pair - plus a differential for each. Read literally they describe a
thermostat, and how far that holds depends on the mode and the moment:

* **On entry to any element mode they do not** describe when the element
  runs. It engages on a mode-dependent differential of its own, published
  nowhere - the start thresholds below.
* **Later in a stint, in** ``ENERGY_SAVER`` **they do**: the element
  engages as the probe reaches ``heUpperOnTempSetting``. That is from this
  unit's history and confirmed by a commanded run.
* **Later in a stint, in** ``HIGH_DEMAND`` **they do not**: it re-engages
  about 2.1 degC below its ON setting. That is from history only.
  ``ELECTRIC`` is uncharacterised.

The fields also look wrong as a thermostat taken literally: in Electric
and High Demand the on and off settings are **the same value**, and every
``he*DiffTempSetting`` reads 0.

**The start thresholds** here were measured on one unit by commanding
the modes and watching - not inferred from historical logs. That
distinction matters: two earlier values came from "the smallest deficit
ever seen to start an element" in a passive record, and both were wrong,
because such a figure measures where the tank happened to sit rather
than where the device decides.

Two things on this page are *not* from commanded runs, and are labelled
where they appear: High Demand's **steady-state** re-engagement, which
is this unit's history, and the mid-stint behaviour it is contrasted
with. Everything else is a bounded run.

.. contents::
   :local:
   :depth: 2


The short version
=================

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Observation
     - Value
   * - Element start differential
     - **Mode-dependent, one bracket per mode.** ``ELECTRIC`` at most
       **0.3 degC (0.54 degF)** below the setpoint; ``HIGH_DEMAND``
       somewhere in **(0.2, 0.7] degC** ((0.36, 1.26] degF);
       ``ENERGY_SAVER`` in **(0.8, 1.0] degC** ((1.44, 1.80] degF).
       Each bracket has a run on either side of it - except Electric's
       lower edge, whose only negative sits *above* the setpoint.
   * - Where that differential is published
     - **Nowhere.** ``heUpperOnDiffTempSetting`` and its three siblings
       read 0 on this unit while the behaviour above holds.
   * - ``heUpperOnTempSetting`` by mode
     - ``ELECTRIC`` and ``HIGH_DEMAND``: the setpoint, same as
       ``heUpperOffTempSetting``. ``ENERGY_SAVER``: 40.5 degC
       (104.9 degF), the device minimum, in 96 % of recorded minutes on
       this unit. ``HEAT_PUMP``: 40.5 degC only about **half** the time;
       the rest are other values that match the current setpoint only
       6 % of the time. Why is not known.
   * - Energy Saver on entry
     - Switching into ``ENERGY_SAVER`` engages the upper element even
       though ``heUpperOnTempSetting`` rests 33 degC below the tank, so
       **on entry** that field is not what drives it. Its bracket also
       sits higher than the other two modes'. Why the two differ is
       **not** established: the Energy Saver runs had the compressor
       running and the others did not.
   * - Energy Saver later in a stint
     - Different rule. The element re-engages **as the upper probe
       reaches** ``heUpperOnTempSetting`` - the field working exactly
       as this reference describes it. Entry is the exception, not the
       rule.
   * - Electric ordering
     - Upper element to the setpoint, then the lower element, never
       both, as the protocol reference already states. The handover
       takes one poll.
   * - Element power
     - 5,200-5,242 W over three measurements (two upper, one lower),
       metered with the compressor off. The reference gives 5,000 W at
       240 V.
   * - Zone coupling
     - While the lower element runs, the **upper** probe falls about
       1.9 degC (3.4 degF) before recovering. The zones are not
       independent.


The start differential
======================

Three modes, three brackets, and no two of them the same width. Each
run holds a fixed deficit and watches for one to two minutes; the
setpoint quantises to 0.5 degC, so the deficit is set by choosing a
setpoint step relative to the tank.

``ENERGY_SAVER``
----------------

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Deficit below setpoint
     - Upper element
     - Poll at which it engaged
   * - 0.3 degC (0.54 degF)
     - **off** for the whole watch
     - n/a
   * - 0.8 degC (1.44 degF)
     - **off** for the whole watch
     - n/a
   * - 1.0 degC (1.80 degF)
     - **on**
     - first poll after the mode landed
   * - 1.2 degC (2.16 degF)
     - **on**
     - first poll after the mode landed

So the boundary lies in (0.8, 1.0] degC, and 1.0 degC is the device's
own storage granularity - settings are held in half-degree Celsius
steps - which makes a one-degree differential the natural parameter.

A further run put the element on at 2.0 degC (3.6 degF) short, so
nothing above the boundary has been seen to decline.

``ELECTRIC``
------------

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Deficit below setpoint
     - Upper element
     - Poll at which it engaged
   * - 0.6 degC **above** the setpoint
     - **off** for the whole watch
     - n/a
   * - 0.3 degC (0.54 degF)
     - **on**
     - first poll after the mode landed
   * - 0.4 degC (0.72 degF)
     - **on**
     - first poll after the mode landed

``HIGH_DEMAND``
---------------

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Deficit below setpoint
     - Upper element
     - Poll at which it engaged
   * - 0.2 degC (0.36 degF)
     - **off** for the whole watch
     - n/a
   * - 0.7 degC (1.26 degF)
     - **on**
     - first poll after the mode landed

``heUpperOnTempSetting`` moved to the new setpoint in the same status
message the mode landed in, as it does in Electric.

Putting the three together
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 26 24 26

   * - Mode
     - Element off at
     - Element on at
     - Bracket
   * - ``ELECTRIC``
     - 0.6 degC above setpoint
     - 0.3, 0.4 degC
     - at most 0.3 degC [#electric]_
   * - ``HIGH_DEMAND``
     - 0.2 degC
     - 0.7 degC
     - (0.2, 0.7] degC
   * - ``ENERGY_SAVER``
     - 0.3, 0.8 degC
     - 1.0, 1.2 degC
     - (0.8, 1.0] degC

**These are entry thresholds, not thermostats.** Every run measured what
happens within a poll of switching *into* a mode. In ``HIGH_DEMAND``'s
steady state this unit's history has the upper element on in 1 of 47
minutes 0.2-0.3 degC short and 168 of 169 minutes more than 2.2 degC
short - so a stint already running re-engages on something much larger
than the entry figure. Do not use one for the other.

.. [#electric] Electric's own negative is 0.6 degC *above* the setpoint,
   so nothing at all was observed between there and 0.3 below it. Its
   bracket is open at the bottom: no run has shown Electric declining
   to heat a tank that is short of the setpoint by any amount.

**Electric and High Demand may share one entry threshold. That is an
inference, not a measurement.** Their brackets overlap in
(0.2, 0.3] degC and the two modes handle ``heUpperOnTempSetting``
identically, which is a real argument for one number covering both -
but High Demand has never been watched between 0.2 and 0.7 degC, so
nothing here measures where its boundary falls inside that span.
Energy Saver's band does not intersect either of them: at 0.7 degC
short, High Demand runs the element and Energy Saver does not. One
caveat on that last comparison: the Energy Saver runs had the
compressor running and the others did not, so mode is not the only
difference between them.

A consumer wanting one number per mode should take the **top of that
mode's own bracket** - 0.3 degC for ``ELECTRIC``, **0.7 degC** for
``HIGH_DEMAND``, 1.0 degC for ``ENERGY_SAVER``. Each is the **smallest
deficit at which that mode was seen to start an element**, so assuming
it contradicts no observation of that mode - where anything lower
contradicts that mode's own negative. Borrowing Electric's 0.3 degC for High Demand predicts an
element at, say, 0.4 degC short that High Demand has never been seen to
run; if your consumer is deciding whether hot water will be ready,
that is the expensive direction to be wrong in.

**The differential is not in the protocol.** A ``status --raw`` taken
between these runs shows::

   "heUpperOnTempSetting": 81,      # 40.5 degC
   "heUpperOffTempSetting": 122,    # 61.0 degC
   "heUpperOnDiffTempSetting": 0,
   "heUpperOffDiffTempSetting": 0,
   "heLowerOnTDiffempSetting": 0,
   "heLowerOffDiffTempSetting": 0,

A consumer that wants to predict when an element will run therefore
cannot read it from the status message; it has to assume the per-mode
figures above - 0.3 degC for ``ELECTRIC``, 0.7 for ``HIGH_DEMAND``,
1.0 for ``ENERGY_SAVER`` - and treat a tank inside the corresponding
bracket as a case where the device may go either way. High Demand's
bracket is the widest, so that "either way" span is widest there too.


What the on-setting does and does not tell you
==============================================

``heUpperOnTempSetting`` tracks the **mode**, not the moment:

* In ``ELECTRIC`` and ``HIGH_DEMAND`` it equals ``heUpperOffTempSetting``
  and both equal the DHW setpoint. Taken literally that is a thermostat
  with no hysteresis at all, which cannot be how the device behaves; on
  entry the measured differential is at most 0.3 degC in Electric and
  within (0.2, 0.7] degC in High Demand.
* In ``ENERGY_SAVER`` it rests at 40.5 degC, the device minimum, which
  is 33 degC below a normally charged tank. An earlier version of this
  page said the same of ``HEAT_PUMP``; on this unit that holds in only
  48.5 % of Heat Pump minutes. The rest are other values - 63.0 degC
  most often - which equal the *current* setpoint in only 6 % of Heat
  Pump minutes, so this is not the field tracking the setpoint; it may
  be holding a value over from an earlier mode. Do not rely on it in
  Heat Pump mode.

The second case misleads **on entry only**. Switching into
``ENERGY_SAVER`` with the tank 1.0 degC or more short brought the upper
element on within one poll in both runs tested, while
``heUpperOnTempSetting`` dropped from the setpoint to 40.5 degC in the
*same* status message - 33 degC below the probe. For that moment the
field explains nothing.

That is as far as the entry observation goes. It does not explain *why*
Energy Saver's bracket sits higher than Electric's; the runs differ in
compressor state as well as mode, and nothing here separates the two.

**Later in the same stint the field is exactly what drives the
element.** In 23 mid-stint upper-element starts in ``ENERGY_SAVER``
drawn from one unit's recorded history, **17 have the upper probe
between 39.4 and 41.1 degC** - the band ``heUpperOnTempSetting`` rests
in for this mode - and where the field itself is recorded the median
start is **0.2 degC below it**. The element comes on as the probe
reaches the on-setting, which is what this reference has said all
along.

**Confirmed on the device.** The history above cannot prove it on its
own: with the setpoint fixed for almost the whole record, "at the
on-setting" and "a fixed gap below the setpoint" are the same
prediction. So the setpoint was lowered to 42.0 degC and the unit left
in ``ENERGY_SAVER``. With the on-setting still at 40.5 degC, a fixed gap
would have put the element near 22 degC; it came on three times with
the upper probe reading **39.8 degC**. Two cautions: all three came
while water was moving through the tank, and readings of 40.4, 40.1 and
40.0 degC did not trigger, so on this probe the working threshold may
sit a little under the published 40.5.

``HIGH_DEMAND`` behaves differently, and this is the clearest statement
of the difference on this page. There ``heUpperOnTempSetting`` tracks
the setpoint, and 12 mid-stint starts came a median **2.1 degC below
it**, none in the 39.4-41.1 degC band. That differential is real and is
published nowhere.

So a consumer needs both halves:

.. list-table::
   :header-rows: 1
   :widths: 26 37 37

   * - Mode
     - On entry
     - Later in the stint
   * - ``ENERGY_SAVER``
     - element on, on-setting irrelevant (1.0 degC below setpoint)
     - element on **near** ``heUpperOnTempSetting``
   * - ``HIGH_DEMAND``
     - element on, (0.2, 0.7] degC below setpoint
     - element on ~2.1 degC **below** ``heUpperOnTempSetting``

Three more behaviours, from the same commanded run. Each is one unit
and one morning; the counts are given so they can be weighed.

* **The element runs to the setpoint, not to a fixed point.** It
  stopped about 0.9 degC under ``heUpperOffTempSetting``, which follows
  the setpoint. At a 42.0 degC setpoint that was 41.1 degC; historical
  runs at a 60.5 degC setpoint stop around 59. Only the *engagement*
  point is fixed.
* **Raising the setpoint in** ``ENERGY_SAVER`` **starts the element.**
  With the tank at 41.7 degC, a setpoint raise to 61.0 degC switched the
  heat source to heat pump plus element in the same second (n = 1). It
  is the entry rule again, triggered by the setpoint rather than a mode
  change. A controller writing setpoints in this mode can start a 5 kW
  element.
* **Every engagement came with water moving through the tank** — one
  shower and two runs of a recirculation pump on a cooled loop, which
  the tank experiences as draws. Whether movement is *required*, or the
  temperature alone suffices, is not separable from these.

.. warning::

   These mid-stint figures come from **recorded history, not commanded
   runs**, and they carry a sampling hazard worth repeating - one that
   bit us.

   **The element runs in two very different lengths.** Of 115 raw
   upper-element runs on this unit over eight months, 20 (17 %) lasted
   **under a minute** - median 16 s - and 95 ran a median 8 minutes.
   The short ones are real elements at full power. They carry little
   energy - 0.6 kWh across the record against 93 kWh for the rest -
   but they are not negligible to the probe: a 20-second burst raises
   the upper zone about 0.3 degC, three quanta of its 0.1 degC
   resolution, and measured bursts of 41-58 s moved it 0.7-1.5 degC.
   *(An earlier version said they "heat nothing", from dividing by the
   whole tank's heat capacity rather than the upper zone's - three
   times too large.)*

   They are also easy to lose or to misread. ``currentPower`` samples
   at a median 30 s, with 24 % of gaps over a minute, so **a
   one-minute-resampled power series can miss a sub-minute burst
   entirely** - taking the last sample at or before each minute makes a
   real 5.5 kW element look like 0.5 kW. Resample power with a
   **maximum** over the interval, or work from the raw edges, and
   corroborate a run's duration rather than a single aligned sample.

   For predicting recovery, filter on **duration or energy**, not on
   the flag and not on one power reading: it is the sustained runs that
   heat the tank.


Electric: the handover, and what happens to the upper zone
===========================================================

The protocol reference states that elements do not operate
simultaneously in Electric mode. Confirmed, and the order is upper
first: in a six-minute run the upper element stopped and the lower one
appeared in the next poll, with no overlap.

Two details a consumer modelling the tank should know:

**The upper probe falls while the lower element runs.** It peaked at
63.3 degC (145.9 degF), fell to 61.4 (142.5) over the following three
minutes, then recovered to 62.3 (144.1) as the tank mixed. Anything
that treats "upper zone reached X" as monotonic during an Electric
recovery will be wrong by about 1.9 degC for several minutes.

**The off point lags in both directions.** The upper element switched
off with the probe 0.8 degC (1.4 degF) *below* the setpoint, and the
probe then coasted 1.3 degC (2.3 degF) *past* it. The device's decision
and the probe are not the same instant.


Element power
=============

Metered at the whole-unit power reading with the compressor off, so it
is the element alone:

* upper element: 5,219 W on one run (5,205-5,242 over 33 samples) and
  5,242 W on a second
* lower element: 5,200 W

The reference gives 3,755 W at 208 V or 5,000 W at 240 V. The measured
figure is 4 % above the 240 V rating on this unit, which is one unit at
one supply voltage - a nudge for anyone integrating energy, not a
correction to the specification.

For the record, the upper zone rose at 0.87-0.89 degC/min
(1.56-1.61 degF/min) end to end over 5.8 minutes on a 63.2 gal tank -
the spread is sampling resolution, the higher figure from 10-second
polls and the lower from a one-minute grid - and the lower zone at
0.66-0.86 degC/min depending on where the fit starts; the probe lags the
element for the first 40-60 seconds, which is most of the difference.
Those are tank-specific and are offered as an order of magnitude only.


Writing the mode while a TOU window is in force
===============================================

Relevant when planning any of this: with TOU scheduling enabled and a
window in force, a mode write may not take effect. Measured on the same
unit, four minutes with no change and nothing logged, twice - and the
command was not discarded either: it took effect one poll after the TOU
switch was turned off, with nothing else commanded.

Whether the device queues the command or accepts it and masks the
read-back is undetermined. Either way, **confirm a mode write by reading
the mode back, and do not treat an unconfirmed one as failed.**

Reservation entries are a separate case. Their target temperature
applies normally in a window, and only their mode is held back; see
:ref:`reservations and mode writes during a tou window`.


Limits
======

One unit, one supply voltage, 2026-09-19 and 2026-09-20. **Twenty-two**
bounded runs in all: thirteen on the elements and the thresholds, nine
on mode writes and reservation entries under TOU. Specifically **not**
established:

* **where inside (0.2, 0.7] degC ``HIGH_DEMAND``'s boundary falls.** It
  has a run on each side, so it is bracketed - but that bracket is more
  than twice Electric's width, and one run at 0.4 degC would halve it.
  Until then, whether the two modes share a threshold is unresolved.
* **Electric's** behaviour later in a stint. Energy Saver's and High
  Demand's are described above from history; Electric has only two
  mid-stint starts on record, which characterises nothing.
* anything about runs longer than six minutes.
* whether either differential is firmware-dependent. The unit reported
  ``heUpperOnDiffTempSetting`` as 0 throughout; if another unit reports
  it as non-zero, that field is the better answer and this page is a
  description of one firmware's default.
