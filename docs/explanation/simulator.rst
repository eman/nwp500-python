=====================
The Heater Simulator
=====================

``nwp500.sim`` is a physics simulation of the NWP500. Given the heater's
state, its schedules, the air where it sits and the hot water drawn from
it, it predicts the tank's two thermistors over time, when and why the
heater starts heating and with which source, the electricity it uses,
how much hot water the tank can deliver, and whether a draw runs cold. It also evaluates commands before they are sent: setpoint and mode
writes, a new reservation schedule, TOU on or off.

It is optional. Install it with the ``sim`` extra
(``pip install nwp500-python[sim]``), which adds numpy, pandas and
scipy. ``import nwp500`` does not load it.

:doc:`/how-to/simulate-heater` walks through using it, from fetching
the heater's data to evaluating a change, and
:doc:`/reference/simulator-inputs` lists every input it takes.

.. contents::
   :local:
   :depth: 2


Values in, values out
=====================

The simulator does no I/O: it makes no MQTT or REST request, reads no
file or environment variable, and never reads the clock. The start,
the horizon and the time zone are inputs, so a scenario replays
identically. It keeps no module state and does not log; anything it
would warn about is in the result's ``reasons``. A client fetches what
it needs, builds a scenario, and reads the answer.

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
saturation properties from a refrigerant table, an evaporator approach
to the intake air, a condenser approach to the tank, polytropic
compression with clearance, the fan's airflow, and the latent load of
humid air. It is integrated in 10-second steps until the lower
thermistor reaches its target.

**The tank, in two zones.** The condenser coil wraps the lower part of
the tank, so while the tank is stratified a recovery warms the lower
zone (about half the tank's mass). Once the gap between the zones
closes, the tank heats as one body. In standby the gap relaxes on a
fitted time constant. Standby loss follows a jacket law,
``UA(dT) = ua_ref * (max(dT, 5) / 50) ^ n``, with the ambient as the
other side.

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
  ``hp_lower_on``, after a setpoint write that leaves the upper zone
  short, after a mode write, or at a TOU window's opening when the
  upper zone is far short;
- inside a TOU window the lower trigger is held until the window
  closes, a recovery stops 3.6 degF short of the setpoint (the 90 %
  cap), and a mode write is held until the window ends;
- after a stop, the compressor will not restart for 330 s;
- reservations fire in their minute; Vacation and Power Off start no
  heating.

**The heat book.** Two probes cannot say how much hot water is left
once the hot/cold boundary sits between them; they can when the tank is
full. The book (``sim.book``) starts from a full tank and books the
heat from there: out by each draw through the mixing valve and by
standby, in from the compressor and the elements, with a draw's cold
water kept as a region at the bottom, where the heat pump's heat lands
and is held back until the region rejoins the hot water. At each draw
it moves the zones the probes would show: the upper zone falls as the
water above the rising front mixes and, once the booked heat is spent,
to the line and below; the lower zone follows the front past its probe.
Without a book each draw moves the zones by its calibrated response
only, which is what the probes show on an ordinary draw and holds the
upper zone up through one that empties the tank. The library starts a
book only from what the caller knows: probes reading full can hide the
cold water of a recent draw.

**Hot water at the tap** (``sim.delivery``). Deliverable gallons are the
water past the mixing valve before the delivered water falls below the
line (105 degF by default), from the book's heat above its empty point.
The probe is not at the tap: the delivered water crosses the line some
gallons after the upper probe does, the water above it and in the pipe
to the fixture, so every answer carries that lag. Without a book, the
answer is a full tank's floor, or evidence from the caller's own
draws. A draw window runs cold when the delivered water falls more than
the heater's own transient dip below the line, or stays below it longer.


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
``sim_adapters`` is the boundary: it reads the device's raw fields
(``*_raw``), never the converted properties, so the process-wide unit
preference (:doc:`/how-to/manage-units`) cannot change a scenario, and
it takes what a caller supplies and gives back a result's values in
that preference. A core in other units would change the adapters'
conversions and nothing a caller writes.

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
nominal size, and nothing else: their compressors, elements and jacket
loss have not been measured.

What carries to another installation, and what does not:

- **The heater's terms** (tank, element power and rates, controller
  thresholds, the stratification time constant, input power) were
  measured on one unit and are expected to hold for the model.
- **The standby loss and the compressor terms** were fitted against a
  sensor of the air where the heater stands. The heater's own
  ``ambient_temperature`` reads that air within about 0.35 degF while
  the compressor runs and about 5 degF warm while it is idle, so give
  the simulator the running readings, or a forecast anchored to one.
  The compressor terms were fitted with that installation's draws and
  circulation runs inside its recoveries, so a recovery without them
  comes out a little long.
- **The draw terms** (observability, the gap a draw opens, the inlet
  temperature) were fitted together through that installation's mixing
  valve, on its mains and its household's metered draws. Change them
  together, or not at all. The **book's** and **readiness's** terms are
  that installation's too, and its evidence over-promises on an
  installation without a valve.
- **Circulation** (the gate, the pool, the return water's share) acts
  only when a circulation schedule is given.

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


Accuracy
========

Measured on one NWP500-65:

- a heat-pump recovery's duration, from physics alone: mean absolute
  error about 28 min (18 %); about 13 min for a deficit under 15 degF,
  and about 45 min past 35 degF. Physics alone runs short on long
  recoveries: cold starts come out about 55 min short, and past about
  180 min it under-predicts; under about 60 min it is the better
  estimate. The source this was ported from serves a recovery model
  trained on its heater's record on top of the physics, and has no
  physics-only mode for readiness's time to ready; the library serves
  physics alone, through ``RecoveryModel`` for a caller with a model of
  their own;
- recorded compressor starts reproduced: 35 of 47;
- daily energy: 10.8 % high;
- the heat book against the tank's re-anchors, fitted February-June and
  scored July-September: mean absolute error 1,987 BTU (about 5 gal),
  flat to 18 h after an anchor and about double beyond;
- the five recorded crossings of the line: all caught, 0.8-12.7 gal
  early (in sample); draws of 5 gal or more that did not cross, called
  empty before they ended: 14 of 446 (3.1 %);
- the outlet lag: one measurement (5.3-7.3 gal, 5.0 used).

The library makes no claim beyond these until they are measured again.


What it cannot know
===================

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
- **The installation.** The pipe to the fixture, the mixing valve's
  setting and the household's draws are the installation's: the
  readiness defaults are one installation's (``ReadinessParams``).
