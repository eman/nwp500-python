=====================
The Heater Simulator
=====================

``nwp500.sim`` is a physics simulation of the NWP500. Given the heater's
state, its schedules, the air where it sits and the hot water drawn from
it, it predicts the tank's two thermistors over time, when and why the
heater starts heating and with which source, and the electricity it
uses. It also evaluates commands before they are sent: setpoint and mode
writes, a new reservation schedule, TOU on or off.

It is optional. Install it with the ``sim`` extra
(``pip install nwp500-python[sim]``), which adds numpy, pandas and
scipy. ``import nwp500`` does not load it.

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
       environment=sim.Environment(ambient_f=68.0),
   )
   result = sim.simulate(scenario, sa.params(feature))  # DeviceFeature

   for h in result.heating:
       print(h.start.at, h.start.trigger, h.source, h.end, h.stop)

A "what if" is a copy of the scenario with one part changed:

.. code-block:: python

   eco = scenario.model_copy(
       update={"commands": sim.Commands(
           writes=(sim.Write(at=scenario.start, mode=3),),  # Energy Saver
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

Temperatures are in degF, the unit the physics were fitted in;
schedules keep the device's units. The adapters read the raw fields
(``*_raw``), never the converted properties, so the process-wide unit
preference (:doc:`/how-to/manage-units`) cannot change a scenario.

``sim.codec`` writes a scenario, with or without its parameters, as a
JSON document, and reads one back.


Parameters and their defaults
=============================

``HeaterParams`` holds every fitted or device constant, in parts: tank,
loss, compressor, power, element, draw and controller. Each field
records where its value came from (``params.provenance_of``):
``measured`` on the heater by a targeted run, ``fitted`` from its
record, or an engineering ``default``.

``default_params(volume_code)`` returns one NWP500-65's parameters, as
fitted on 2026-10-11 from 240 V operation. The 50 and 80 gal models
get the same parameters with the tank's volume scaled by nominal size,
and nothing else: their compressors, elements and jacket loss have not
been measured. The fit belongs to one tank in one place, so its standby
loss reflects the air around that tank and its draw response one
household's draws. A caller with its own calibration passes its own
``HeaterParams``.

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

A ``RecoveryModel`` can replace each heat-pump recovery's duration with
a learned one, and a ``HeatLedger`` can track booked heat from a flow
meter; both are protocols in ``sim.extensions``. With neither, the
physics alone is served.


Accuracy
========

Measured on one NWP500-65:

- a heat-pump recovery's duration, from physics alone: mean absolute
  error about 28 min (18 %); about 13 min for a deficit under 15 degF,
  and about 45 min past 35 degF;
- recorded compressor starts reproduced: 35 of 47;
- daily energy: 10.8 % high.

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

Hot-water readiness (how many gallons the tank can deliver now) and
which draws would run cold are not modelled yet. Both need a validated
two-zone readiness model.
