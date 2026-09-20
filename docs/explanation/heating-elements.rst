====================
The Heating Elements
====================

The NWP500 publishes four element thermostat settings -
``heUpperOnTempSetting``, ``heUpperOffTempSetting`` and their lower-zone
pair - plus a differential for each. Read literally they do not describe
when the elements actually run: in Electric and High Demand the on and
off settings are **the same value**, and every ``he*DiffTempSetting``
reads 0. The device nevertheless has a differential, and this page
gives the measured one.

Everything here was measured on one unit by commanding the modes and
watching, not inferred from historical logs. That distinction matters:
two earlier values for the start threshold came from "the smallest
deficit ever seen to start an element" in a passive record, and both
were wrong, because such a figure measures where the tank happened to
sit rather than where the device decides.

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
     - **Mode-dependent.** In ``ENERGY_SAVER`` the upper element starts
       once the zone is **1.0 degC (1.8 degF)** below the setpoint. In
       ``ELECTRIC`` it starts as soon as the zone is under the setpoint
       at all - the boundary is inside 0.3 degC, at or below the probe's
       own resolution. Both are bracketed by runs on either side.
   * - Where that differential is published
     - **Nowhere.** ``heUpperOnDiffTempSetting`` and its three siblings
       read 0 on this unit while the behaviour above holds.
   * - ``heUpperOnTempSetting`` by mode
     - ``ELECTRIC`` and ``HIGH_DEMAND``: the setpoint, same as
       ``heUpperOffTempSetting``. ``HEAT_PUMP`` and ``ENERGY_SAVER``:
       40.5 degC (104.9 degF), the device minimum.
   * - Energy Saver on entry
     - Switching into ``ENERGY_SAVER`` engages the upper element even
       though ``heUpperOnTempSetting`` rests 33 degC below the tank -
       an entry effect rather than that thermostat, and the reason its
       differential differs from Electric's.
   * - Electric ordering
     - Upper element to the setpoint, then the lower element, never
       both, as the protocol reference already states. The handover
       takes one poll.
   * - Element power
     - 5,219 W upper, 5,200 W lower, metered with the compressor off.
       The reference gives 5,000 W at 240 V.
   * - Zone coupling
     - While the lower element runs, the **upper** probe falls about
       1.9 degC (3.4 degF) before recovering. The zones are not
       independent.


The start differential
======================

Two modes, two different answers. Each run holds a fixed deficit and
watches for one to two minutes; the setpoint quantises to 0.5 degC, so
the deficit is set by choosing a setpoint step relative to the tank.

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

**The two modes do not share a threshold.** At the same 0.3 degC
deficit, ``ELECTRIC`` runs the element and ``ENERGY_SAVER`` does not.
Electric's boundary is inside (0, 0.3] degC - at or below the tank
probe's own 0.1 degC resolution - which is what the thermostat reading
of its settings predicts, since it parks ``heUpperOnTempSetting`` at the
setpoint. Energy Saver's 1.0 degC is an entry effect and a different
mechanism.

``HIGH_DEMAND`` shares Electric's settings and has been seen to start an
element at 5.2 degC short, but no run has approached its boundary; the
thermostat reading is an assumption there.

**The differential is not in the protocol.** A ``status --raw`` taken
between these runs shows::

   "heUpperOnTempSetting": 81,      # 40.5 degC
   "heUpperOffTempSetting": 122,    # 61.0 degC
   "heUpperOnDiffTempSetting": 0,
   "heUpperOffDiffTempSetting": 0,
   "heLowerOnTDiffempSetting": 0,
   "heLowerOffDiffTempSetting": 0,

A consumer that wants to predict when an element will run therefore
cannot read it from the status message; it has to assume the 1.0 degC
above, and treat a tank within that of the setpoint as a case where the
device may go either way.


What the on-setting does and does not tell you
==============================================

``heUpperOnTempSetting`` tracks the **mode**, not the moment:

* In ``ELECTRIC`` and ``HIGH_DEMAND`` it equals ``heUpperOffTempSetting``
  and both equal the DHW setpoint. Taken literally that is a thermostat
  with no hysteresis at all, which cannot be how the device behaves; the
  1.0 degC differential above is what it does instead.
* In ``HEAT_PUMP`` and ``ENERGY_SAVER`` it rests at 40.5 degC, the
  device minimum, which is 33 degC below a normally charged tank.

The second case is the one that misleads. In ``ENERGY_SAVER`` the upper
element **does** run, and it runs with the on-setting far below the tank
- so the element is not being driven by that field. Switching into the
mode with the tank 1.0 degC or more short brought the element on within
one poll in both runs tested, and ``heUpperOnTempSetting`` dropped from
the setpoint to 40.5 degC in the *same* status message. Watching that
field for an explanation of the element will not find one.


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

* upper element: 5,219 W (5,205-5,242 over 33 samples)
* lower element: 5,200 W

The reference gives 3,755 W at 208 V or 5,000 W at 240 V. The measured
figure is 4 % above the 240 V rating on this unit, which is one unit at
one supply voltage - a nudge for anyone integrating energy, not a
correction to the specification.

For the record, the upper zone rose at 0.89 degC/min (1.61 degF/min)
end to end over 5.8 minutes on a 63.2 gal tank, and the lower zone at
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

Reservation entries are a separate case and fire normally in a window;
see issue #141 for the documentation fix covering that.


Limits
======

One unit, one supply voltage, 2026-09-19 and 2026-09-20, thirteen
bounded runs in all. Specifically **not** established:

* ``HIGH_DEMAND``'s boundary. It shares Electric's settings and starts
  an element well above the boundary, but no run has approached it.
* what engages the element **later** in an Energy Saver stint, as
  opposed to on entry.
* anything about runs longer than six minutes.
* whether either differential is firmware-dependent. The unit reported
  ``heUpperOnDiffTempSetting`` as 0 throughout; if another unit reports
  it as non-zero, that field is the better answer and this page is a
  description of one firmware's default.
