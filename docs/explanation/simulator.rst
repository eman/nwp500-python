=====================
The Heater Simulator
=====================

``nwp500.sim`` is a physics simulation of the NWP500. Given the heater's
state, its schedules, the air where it sits and the hot water drawn from
it, it predicts the tank's two thermistors over time, when and why the
heater starts heating and with which source, the electricity it uses,
how much hot water the tank can deliver, and whether a draw runs cold. It also evaluates commands before they are sent: setpoint and mode
writes, a new reservation schedule, TOU on or off.

:doc:`/how-to/simulate-heater` walks through using it, from fetching
the heater's data to evaluating a change, and
:doc:`/reference/simulator-inputs` lists every input it takes.

.. contents::
   :local:
   :depth: 2


Building a scenario
===================

You fetch the heater's data, build a scenario from it, and read the
answer. Anything worth a warning is in the result's ``reasons``.

``nwp500.sim_adapters`` builds a scenario's parts from the library's
models:

.. code-block:: python

   from datetime import datetime, timedelta, UTC
   from nwp500 import sim, sim_adapters as sa

   scenario = sim.Scenario(
       start=datetime.now(UTC),
       horizon=timedelta(hours=24),
       tz="America/Los_Angeles",
       state=sa.heater_state(status),          # DeviceStatus
       settings=sa.settings(status),
       schedules=sa.schedules(
           reservations=reservation_schedule,  # ReservationSchedule
           tou=tou_info,                       # TOUInfo
           tou_enabled=status.tou_status,
       ),
       environment=sa.environment(status),
   )
   result = sim.simulate(scenario, sa.params(feature))  # DeviceFeature

   for h in result.heating:
       print(h.start.at, h.start.trigger, h.source, h.end, h.stop)

A "what if" is a copy of the scenario with one part changed:

.. code-block:: python

   eco = scenario.model_copy(
       update={"commands": sim.Commands(
           writes=(sa.write(scenario.start, mode=3),),  # Energy Saver
       )}
   )
   print(sim.simulate(eco, sa.params(feature)).input_wh)


The model
=========

**The compressor.** A vapour-compression model of the R-134a cycle:
saturation properties from CoolProp's equation of state, an evaporator
approach to the intake air as the coil reads it, a condenser approach to the tank, polytropic
compression with clearance, the fan's airflow, and the latent load of
humid air. It is integrated in 10-second steps until the lower
thermistor reaches its target.

**The tank, in two zones.** The condenser coil wraps the lower part of
the tank, so while the tank is stratified a recovery warms the lower
zone (about half the tank's mass). Once the gap between the zones
closes, the tank heats as one body. In standby the gap relaxes on a
fitted time constant. Standby loss follows a jacket law,
``UA(dT) = ua_ref * (max(dT, 5) / 50) ^ n``, with the ambient as the
other side, on the whole tank. A bottom loss ``Q_b`` leaves the lower
zone alone: the lower probe sees the share ``1 - exp(-gap / gate)`` of
it, so a stratified tank's lower zone falls faster and its gap opens,
while a mixed tank's lower probe shows little of it. With ``Q_b = 0``
the loss is the jacket law alone.

**The elements.** They follow the device's own rules
(:doc:`heating-elements`): per-mode entry thresholds, a dead time,
upper before lower, and Energy Saver re-engaging at an absolute
104.9 degF.

**Draws.** A draw is gallons on the delivered (mixed) line. The tank
gives up the hot share of them through the mixing valve, and the cold
water replacing them enters at the bottom and mixes into the lower zone
according to how stratified the tank is.

**The controller.** The heater's own rules for starting and stopping
(:doc:`what-starts-a-recovery`, :doc:`tou-recovery-cap`):

- the compressor starts when the lower thermistor falls to
  ``hp_lower_on`` (in Heat Pump, only with the upper zone below the
  setpoint), after a setpoint write that leaves the upper zone short,
  after a mode write, or inside a TOU window when the upper zone is
  more than 14.4 degF short;
- inside a TOU window the lower trigger is held until the window
  closes, a recovery stops 3.6 degF (2 degC) short of the setpoint (the
  90 % cap; recorded capped recoveries stopped 3.42 degF short), and a
  mode write is held until the window ends;
- after a stop, the compressor will not restart for 330 s (two device
  tests restarted 5 min 28 s and 5 min 31 s after the stop);
- reservations fire in their minute; Vacation and Power Off start no
  heating. In Vacation an entry is skipped; powered off, it fires and
  turns the heater on, judged as a mode write.

**The heat book.** Two probes cannot say how much hot water is left
once the hot/cold boundary sits between them; they can when the tank is
full. The book (``sim.book``) starts from a full tank and books the
heat from there: out by each draw through the mixing valve and by
standby, in from the compressor and the elements, all of it drawable
wherever it lands, in a draw's cold water at the bottom too. At each
draw it moves the upper zone the probe would show: it falls as the water
above the rising front mixes and, once the booked heat is spent, to the
line and below. The lower zone takes each draw's calibrated response at
once, with a book or without one, as the lower probe falls on every
draw. Without a book the upper zone takes its calibrated response too,
which is what the probe shows on an ordinary draw and holds the upper
zone up through one that empties the tank. The library starts a
book only from what the caller knows: after a small draw the probes
can still read full.

**Hot water at the tap** (``sim.delivery``). Deliverable gallons are the
water past the mixing valve before the delivered water falls below the
line (105 degF by default), from the book's heat above its empty point.
The probe is not at the tap: the delivered water crosses the line some
gallons after the upper probe does, the tank water above it, so every
answer carries that lag. Without a book, the
answer is the tank's heat as its two probes place it, or evidence from
the caller's own draws where it shows more. A draw window runs cold when the delivered water falls below the line.


Inputs
======

A ``Scenario`` is a frozen value made of parts:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Part
     - Contents
   * - ``start``, ``horizon``, ``tz``
     - The span, and the IANA zone the schedules' local times are in.
   * - ``state``
     - Both thermistors, and whether the compressor or an element is
       running.
   * - ``settings``
     - The setpoint, the mode (a ``DhwOperationSetting`` value) and
       ``hp_lower_on``.
   * - ``history``
     - When the compressor last stopped (the lockout) and when the tank
       last heated. Optional.
   * - ``schedules``
     - Reservation entries and TOU periods in the device's own terms
       (half-degree Celsius setpoints, the device's day and season
       masks), with their switches.
   * - ``environment``
     - The air temperature at the heater, one value or readings; the
       humidity; the inlet water temperature.
   * - ``loads``
     - Draws: an instant and delivered gallons.
   * - ``commands``
     - Setpoint and mode writes at instants, a reservation schedule
       written at the start, and the TOU switch set at the start.

The simulator's fields are in degF and US gallons, the units the
physics were fitted in; schedules keep the device's units.
``sim_adapters`` converts between them: it builds a scenario from the
library's models whatever the unit preference
(:doc:`/how-to/manage-units`), and gives back a result's values in that
preference.

``sim.codec`` writes a scenario, with or without its parameters, as a
JSON document, and reads one back. :doc:`/reference/simulator-inputs`
gives each field's unit, default and source.


Parameters and their defaults
=============================

``HeaterParams`` holds every fitted or device constant, in parts: tank,
loss, compressor, power, element, draw, controller, readiness and the
book. Each field records where its value came from
(``params.provenance_of``): ``measured`` on the heater by a targeted
run, ``fitted`` from its record, or an engineering ``default``; and
what it describes (``params.scope_of``): the **heater**, an NWP500's
own tank, compressor, elements and firmware, or the **installation**,
its plumbing (a mixing valve, circulation), its mains and its
household's draws. ``params.note_of`` names the frame a value was
fitted in where it matters: a sensor it was fitted against, hardware it
was fitted through.

The values come from one NWP500-65, fitted on 2026-10-11 from 240 V
operation at one installation. ``site_example_params(volume_code)`` is
that installation whole, its thermostatic mixing valve included.
``default_params(volume_code)`` is the same with **no mixing valve**:
the one draw setting with no fitted numbers in it, and the one that
errs the safe way for a valve owner who leaves it unset (every gallon
charged as tank water, so depletion is called early, never late). An
installation with a valve sets its line (``with_valve``). It also has
no circulation and no readiness evidence, and it names the
installation's heat book, readiness and draw terms as not fitted
(``HeaterParams.unfitted``), so the answers they reach say
``book_uncalibrated``, ``readiness_uncalibrated`` or
``draw_uncalibrated`` until an installation's own meter fits them. The 50 and
80 gal models get the same parameters with the tank's volume scaled by
rated storage (45.2 and 76.1 gal against the 65's 63.2), and nothing
else: their compressors, elements and jacket loss have not been
measured.

What carries to another installation, and what does not:

- **The heater's terms** (tank, element power and rates, controller
  thresholds, the stratification time constant, input power) were
  measured on one unit and are expected to hold for the model.
- **The standby loss and the compressor terms** were fitted against a
  sensor of the air where the heater stands. The heater's own
  ``ambient_temperature`` reads that air within about 0.35 degF while
  the compressor runs (August to October; up to about 2 degF warm from
  May to July) and about 6 degF warm while it is idle, so give
  the simulator the running readings, or a forecast anchored to one.
  The compressor terms were fitted with that installation's draws and
  circulation runs inside its recoveries, so a recovery without them
  comes out a little long.
- **The draw terms** (observability, how far a draw moves each probe,
  the inlet temperature) were fitted together through that installation's mixing
  valve, on its mains and its household's metered draws. Change them
  together, or not at all. The **book's** and **readiness's** terms are
  that installation's too, and its evidence over-promises on an
  installation without a valve.
- **Circulation** (the gate, the hours stood, the return water's
  share) acts only when a circulation schedule is given.

A caller with its own calibration passes its own ``HeaterParams``.

Every default an answer relied on is listed in ``defaults_used``
(the humidity, the inlet temperature, a missing lockout or heating
history), so an input given can be told from one assumed.


Entry points
============

``simulate(scenario, params)``
   The whole walk. ``SimulationResult`` holds the path, each heating
   interval (its cause, source, end, stop reason, whether the TOU cap
   ended it, and its energy), the writes and mode writes as they
   landed, the modes in force, and energy by time slot and by source.

``recovery(state, settings, environment, params, at=...)``
   "When will the tank be hot?": the first heating interval from an
   instant, running or next to start, with no draws. Pass
   ``schedules`` for a recovery under TOU.

``standby(state, environment, loads, params, start=..., until=...)``
   The tank coasting with no heating: jacket loss and draws.

``readiness(state, settings, params, book=...)``
   "How much hot water is left?": deliverable gallons now, and what the
   answer rests on.

``time_to_ready(scenario, params, bath_gal=..., book=...)``
   "When can I run a bath?": ready now or not, the margin, the time to
   ready and its energy in each heating mode, and the showers the tank
   is ready for. The heat pump's time follows the recovery the heater
   runs next (``next_recovery``): the tank coasts on the standby model
   to the heater's own trigger, and the recovery runs from there to the
   heater's stop threshold, with the TOU cap judged where it ends.

``element_mode(state, settings, params, mode=..., at=...)``
   One recovery in an element mode, from the element model.

``standby`` with ``settings`` also says when the heater would start
itself on the coast and why; every walk with draws says when a draw
would fall outside the range the draw terms were fitted over
(``draw_out_of_domain``).

A ``RecoveryModel`` can replace each heat-pump recovery's duration with
a learned one, and a ``HeatLedger`` can track booked heat from a flow
meter; both are protocols in ``sim.extensions``. With neither, the
physics alone is served.

A model is asked about each recovery with its start state, its target,
the air, the physics duration, the start's hold and the draw load
(``RecoveryContext``). ``simulate`` takes what the model was trained
with, beside ``recovery=``:

``start_hold``
   How long a compressor start holds before the lower zone climbs,
   minutes, by the minutes since the compressor last stopped (None when
   that isn't known). The model is asked with the hold, and serves a
   duration that includes it.

``running_hold``
   What is left, at the start, of a running compressor's own start's
   hold, minutes.

``lead_draws``
   Draws recorded before the start. Those within 30 minutes of the
   first recovery's start are its ``draw_load``: what they took off the
   tank, over the recovery's deficit.

``physics_usable``
   Whether the physics duration may be served; by default, when the
   compressor is calibrated. A model may still answer from the
   integrator's minutes when it isn't.

With no model, or one that declines, the served duration adds no start
hold and the lead draws are not read. The holds still mark where the
lower zone starts to climb: a recovery placed again after a draw inside
its hold counts from there.


Accuracy
========

Measured on one NWP500-65. The recovery-duration figures are those of
the fit the default parameters come from (2026-10-11): cross-validated
over its record, and held out on the 40 recoveries after the 162 it was
fitted on.

- a heat-pump recovery's duration, from physics alone: mean absolute
  error about 28 min, and 38.6 min held out in time order. Scored by the time a recovery had left (28 recoveries over
  45 days to 2026-09-06, an earlier fit): with under 30 min left,
  4.4 min; with over 180 min left, 55.9 min, a mean 44 min short.
  Under about 60-90 min left, physics alone is the better estimate
  of the two;
- replaying recorded writes, with a recovery model trained on the
  heater's record:
  recorded starts reproduced over six days held out, 31 of 40; daily
  energy, with start-up charged once, 3.6 % low in sample and 4.4 %
  low held out (2.0 % low and 2.2 % high with the start hold);
- a recovery's electricity, priced from the fitted power and efficiency
  and checked against an energy meter on later cycles than it was
  fitted on (188 of 235 cycles, 2026-09-18): median error 4.8 % per
  recovery, 90th percentile 13 %, against 10.9 % and 26 % for a
  constant efficiency;
- replaying the recorded draws from each draw's start (1,312 draw
  events from 2026-02-25), with the upper probe crossing the line
  standing in for the tap running cold: recorded depletions caught, 5 of
  5; draws called empty where the probe never crossed, 17 of 1,306
  (1.3 %). From 2026-07-01, after the heat book's fit, 2 of 2 caught
  (one independent event) and 2 false calls in 488. Replayed over whole
  days (214, 2026-02-26 to 2026-09-27) the zones drift from the record:
  mean absolute error 3.22 degF a day on the upper zone and 6.61 degF on
  the lower;
- a forecast's draw windows, issued every 3 h for 24 h ahead from
  2026-09-08 to 2026-09-28, flagged by the delivered water and scored
  against the upper probe crossing the line, which reads 5.3-7.3 gal
  before the delivered water does (:doc:`draws`): 1 of the 8 windows in
  which the probe crossed was flagged, and 1 of 160 others;
- time to ready after a switch into an element mode, 12 events (8 of
  them Energy Saver): mean absolute error 0.51 min; on the two held
  out, 0.13 min, ready a little later than predicted.
  Element energy on the 7 whole runs: mean absolute error 0.045 kWh,
  7 % high;
- the lower zone after a draw, fitted before 2026-06-23 and scored on
  the draws after: mean absolute error 3.09 degF, against 5.32 for
  assuming no change; 5.33 degF on long draws and 1.24 degF on short
  ones; a well-mixed tank gains least (:doc:`draws`);
- the heat book against the tank's re-anchors, fitted February-June and
  scored July-September: mean absolute error 1,987 BTU (about 5 gal),
  against 3,761 BTU with textbook constants; flat to 18 h after an
  anchor and about double beyond;
- the five recorded crossings of the line, with the book as it was when
  it held back the heat in a draw's cold water: all caught, 0.8-12.7
  gal early, in sample (the book's form was chosen with all five in
  view; fitted without them, 2 of 5); draws of 5 gal or more that did
  not cross, called empty before they ended: 14 of 446 (3.1 %);
- the deliverable answer from the book at the start of the four usable
  drawdowns to the line, February to October, against the gallons
  delivered to the crossing net of the heat added, the lag included:
  3.8 gal mean absolute error (7.4 gal under to 5.7 over). Holding
  back the heat in a draw's cold water under-read the two drawdowns
  where it held any back by 9.3 gal on average;
- the outlet lag: one measurement (5.3-7.3 gal, 5.0 used).


Limitations
===========

- **The inlet temperature.** The device's inlet field reads 0, so the
  inlet is an input, or the parameters' fitted value.
- **Draw volume.** The device does not report how much water was
  drawn, so draws are an input: a forecast, or a flow meter's record.
- **Supply voltage.** Element power is the fitted 240 V figure.
- **The air at the heater ahead of time.** The ambient is an input: the
  device reports the air at its intake now, not what it will be.
- **The book's starting point.** The heater reports the probes, not
  how much of the tank is cold water from the last draw. A book starts
  from the caller's knowledge, or not at all.
- **The installation.** The mixing valve's setting and the household's
  draws are the installation's: the readiness defaults are one
  installation's (``ReadinessParams``).
