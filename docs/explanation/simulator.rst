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
the heater's data to evaluating a change,
:doc:`simulator-methodology` explains the methods and how each sensor
is used, and :doc:`/reference/simulator-inputs` lists every input it
takes.

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

**The heat pump.** A performance map fitted on the heater's own
recoveries: the heat into the tank and the electricity drawn, each a
plane in the air at the heater and the lower tank's water, each held
to the range it was fitted over. What the condenser gives is what the air gives
plus the electricity, and a fit that claims more than a real heat pump
could is not applied. A start stirs the water the condenser wraps
with the cold water below it, so the lower thermistor holds while the
condenser heats that pool back, longer the longer the compressor was
off, as the record's does (0 to 22 minutes); the tank is walked a
minute at a time with the condenser heating it until the lower
thermistor is a fitted run-on (0.9 degF) past its target.
Outside the manual's operating range (41-113 degF air, 50-149 degF
water) it does not run, and the elements heat the tank as in Electric.

**The tank, in layers.** The tank is a column of 12 layers, each mixed
within itself (``physics.stratified``, after HPWHsim's), and the two
probes are readings of the layers around their heights. Every step
conserves the layers' heat. Each layer loses to the air through its
share of the sides' UA, the bottom layer through the bottom's too and
the top through the top's, exactly, so no layer cools below the air;
the bottom's loss cools the bottom fastest, so a tank left alone
stratifies. Neighbouring layers conduct, and a layer warmer than the
one above turns over at once. The condenser coil wraps the lower part
of the tank, so a recovery heats the layers it wraps and the heat rises
from there: while the tank is stratified the upper probe holds, and it
climbs once the warm water reaches it. On 30 compressor-only
recoveries the upper probe fell a median 0.5 degF while the probes
were over 3 degF apart, then rose to 1.3 degF above its start over the
last 2 to 3 degF of the gap; after that the two probes rose together.
Where the probes read, how widely, the losses, the conductance and
where the condenser heats are fitted together on the record
(``sim.tank_fit``).

**The elements.** They follow the device's own rules
(:doc:`heating-elements`): per-mode entry thresholds, a dead time,
upper before lower, Energy Saver re-engaging at an absolute
104.9 degF, and High Demand re-engaging 4.1 degF short of the setpoint.
Electric's later starts are not measured (it never ran half an hour on
record). A walk in Electric heats again as the elements do in the heat
pump's place: the heater's own triggers start them by Electric's entry
rule, and the upper element starts again 4.1 degF short of the setpoint,
as High Demand's does. The elements stop at the setpoint, not past it as
the compressor does, so they answer the lower trigger no nearer than that
4.1 degF: a setpoint at or under ``hp_lower_on_f`` would start them
again at once. The same holds for the elements in the heat pump's place.
It says so (``electric_later_starts_unverified``). No element starts
later in a stint where it would stop at once: Energy Saver's 104.9 degF
is over its 1.62 degF off point under a setpoint below 106.6 degF, so
there it starts as High Demand's does, 4.1 degF short of the setpoint,
as Electric's does. Neither is measured there.

**The compressor's lower trigger** reads at ``hp_lower_on_f``, but no
nearer than the setpoint, ``hp_stop_overshoot_f`` short of where a
recovery stops: a threshold over it would start a recovery that stops
at once, at every event the walk meets. The heater's threshold is
104.9 degF on the record for setpoints of 106.7 to 149 degF, and none
lower was set, so what it does there is not measured. It says so
(``lower_trigger_at_setpoint``).

**Draws.** A draw is gallons on the delivered (mixed) line. The tank
gives up the hot share of them through the mixing valve, from the top,
and the cold water replacing them enters at the bottom, mixing into the
water there as it comes, and pushes the column up. A draw that empties
the tank takes the upper probe down with it.

**The controller.** The heater's own rules for starting and stopping
(:doc:`what-starts-a-recovery`, :doc:`tou-recovery-cap`):

- the compressor starts when the lower thermistor falls to
  ``hp_lower_on`` (in Heat Pump and Energy Saver, only with the upper
  zone below the setpoint, though in Energy Saver a draw's drop starts
  it), after a setpoint write that leaves the upper zone short,
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

**The tank's layers now.** Two probes cannot say how much hot water is
left once the hot/cold boundary sits between them: after a draw the
bottom is the inlet's, which they read as no different from a tank that
coasted. A scenario's state can carry the tank's layers
(``HeaterState.layers_f``), as its recent history left them
(``sim.history``): the last day's record replayed through the layered
tank, the probes laid over the end. Without them the simulator starts
from the profile the two probes stand for, and says so
(``tank_profile_estimated``).

**Hot water at the tap** (``sim.delivery``). Deliverable gallons are the
water past the mixing valve before the delivered water falls below the
line (105 degF by default): the water leaving the top in turn, each
gallon through the valve, to the first it delivers under the line, the
mains at the scenario's inlet. The tank's outlet is above the upper
probe, so the tap stays hot for the water above the probe after the
probe has crossed. The delivered temperature along a walk is the top
layer's water through the valve, so the gallons and the delivery agree
on when the tank runs out. A draw window runs cold when the delivered
water falls below the line.


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
     - Draws: an onset, delivered gallons and how long they run.
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
loss, compressor, element, draw, controller, readiness and circulation.
Each field records where its value came from
(``params.provenance_of``): ``measured`` on the heater by a targeted
run, ``fitted`` from its record, or an engineering ``default``; and
what it describes (``params.scope_of``): the **heater**, an NWP500's
own tank, compressor, elements and firmware, or the **installation**,
its plumbing (a mixing valve, circulation), its mains and its
household's draws. ``params.note_of`` names the frame a value was
fitted in where it matters: a sensor it was fitted against, hardware it
was fitted through.

The values come from one NWP500-65, fitted between 2026-10-11 and
10-24 from 240 V operation at one installation. ``site_example_params(volume_code)`` is
that installation whole, its thermostatic mixing valve included.
``default_params(volume_code)`` is the same with **no mixing valve**:
the one draw setting with no fitted numbers in it, and the one that
errs the safe way for a valve owner who leaves it unset (every gallon
charged as tank water, so depletion is called early, never late). An
installation with a valve sets its line (``with_valve``). It also has
no circulation, and it names the installation's draw terms as not
fitted (``HeaterParams.unfitted``), so the answers they reach say
``draw_uncalibrated`` until an installation's own meter fits them. The 50 and
80 gal models get the 65's tank resized to theirs
(``defaults.sized``). The manual gives each model's rated storage and
outside dimensions (Ø21.7 × 63, Ø25 × 63 and Ø25 × 71.6 in). The 65
and the 80 are as wide, so the 80's extra water over its extra height
gives the inside diameter, 21.0 in under 2.0 in of wall. The same wall
on the 50 gives a column 17.7 in across and 42.4 tall, as tall as the
65's 42.1: the 50 is narrower, the 80 taller. The sides' loss scales
with the shell, the bottom's with the cross-section, and the column's
conductance with the cross-section over its height. The probes'
spreads and the inlet zone are gallons along the column, so they
scale with the cross-section. The tanks lose 3.55, 4.12 and 4.74
BTU/h·°F. The top's loss (the head, its fittings and pipes), the
heights as shares of the volume, the compressor, the elements and the
controller are the 65's. None of the 50's or the 80's terms is
measured.

What carries to another installation, and what does not:

- **The heater's terms** (the tank's volume, element power and rates,
  controller thresholds, input power) were measured on one unit and are
  expected to hold for the model.
- **The tank's terms** (where the probes read and how widely, the
  losses, the conductance, the inlet's mixing, where the condenser
  heats) were fitted together on that installation's quiet windows,
  metered draws through its mixing valve and recoveries, against a
  sensor of the air where the heater stands. The losses are that
  tank's in that air's surroundings.
- **The compressor terms** were fitted against the same sensor. The
  heater's own ``ambient_temperature`` reads that air within about
  0.35 degF while the compressor runs (August to October; up to about
  2 degF warm from May to July) and about 6 degF warm while it is idle,
  so give the simulator the running readings, or a forecast anchored to
  one. They were fitted with that installation's draws and circulation
  runs inside its recoveries, so a recovery without them comes out a
  little long.
- **The draw terms** (the inlet temperature, the valve's line) were
  measured through that installation's mixing valve, on its mains.
- **Circulation** (the loop's volume, its return's rest and cooling, its
  flow) acts only when a circulation schedule is given.

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

``readiness(state, settings, params, inlet_f=..., on=...)``
   "How much hot water is left?": deliverable gallons now, and what the
   answer rests on: the tank's layers, or the probes alone.

``time_to_ready(scenario, params, bath_gal=...)``
   "When can I run a bath?": ready now or not, the margin, the time to
   ready and its energy in each heating mode, and the showers the tank
   is ready for. Each mode's time is the scenario walked with that mode
   written at its start, up to a day ahead, to the first instant its
   layers deliver the bath; the energy is the walk's to then. In the
   heat pump the tank coasts to the heater's own trigger and recovers
   from there, with the TOU cap judged where it ends.

``element_mode(scenario, params, mode=...)``
   "What if I switch to Energy Saver, High Demand or Electric?": the
   scenario walked with that mode written at its start, to the end of
   the recovery the write sets off or a switch-back. The elements and,
   in High Demand and Energy Saver, the heat pump heat the layers
   together, so the times, the energy and the tank at the end are one
   walk's.

``draw_ensemble.weigh(scenarios, members, params)``
   "How often does each candidate run cold, and what does it cost over
   the households a forecast allows?": each scenario walked on every
   member (``draw_ensemble.members``, households sampled from a weekly
   draw forecast), the same members for every scenario, so candidates
   are compared on the same draws.

``carry_on(walks, tail, params)``
   "What does each change leave behind?": every walk's end walked on
   through one tail, the heater in its standing settings, so changes
   are weighed with the tank each leaves. ``Carried`` holds the walk
   and its tail, their electricity by slot, and how far the tail's end
   is from the first walk's (``residual_f``, ``residual_wh``,
   ``heating_alike``): a tail that ends them alike, the same layers
   and, walked on as itself, with no water drawn or circulation
   started past its end (the tail itself runs none started at or after
   it),
   past every start, hold and lockout still due and every TOU window
   opening on the way (up to 16 h), the same electricity and layers,
   leaves nothing between them unvalued. It takes
   ``simulate``'s keyword inputs for every tail: a ``recovery`` model
   and ``start_hold`` as the walks had them, any windows over the
   tail's own span.

   An example, walked on 2026-10-31 with ``site_example_params()``: a
   120 °F day with 75 gal drawn (two morning showers, three evening
   draws), priced at an illustrative $0.20 a kWh and $0.50 from 16:00
   to 21:00. Of five boosts, each back to 120 °F at 21:00, 140 °F from
   13:00 is the cheapest over its own day ($0.65, the standing day
   $0.62) and leaves the lower tank at 96.9 °F. Carried through the
   same day again it is the third of the boosts ($1.40, against $1.35
   for 130 °F from 13:40 or 14:00, and $1.28 standing). Tails of 24 h
   left every walk within 0.81 °F of the standing one's (108 Wh);
   12 h, 5.7 °F (201 Wh); 36 h, 0.20 °F.

``standby`` with ``settings`` also says when the heater would start
itself on the coast and why; every walk with draws says when a draw
would fall outside the range the draw terms were fitted over
(``draw_out_of_domain``).

A ``RecoveryModel`` (a protocol in ``sim.extensions``) can give each
heat-pump recovery a learned duration. It is served as the pace of the
heat pump's heat for that recovery (``heat_pump_recovery.rate_scale``):
the tank walks the same layers, at the model's speed. With none, the
physics alone is served.

A model is asked about each recovery with its start state (the probes
and the layers), its target, the air, the physics duration and the
start's hold (``RecoveryContext``). ``simulate`` takes what the model
was trained with, beside ``recovery=``:

``start_hold``
   How long a compressor start holds before it heats, minutes, by the
   minutes since the compressor last stopped (None when that isn't
   known). The model is asked with the hold, and serves a duration that
   includes it.

``running_hold``
   What is left, at the start, of a running compressor's own start's
   hold, minutes.

With no model, or one that declines, the served duration is the hold
(none unless ``start_hold`` or ``running_hold`` is given: the
parameters impose none, the layers' own start stir holding the lower
probe instead) plus the physics' climb.


Accuracy
========

Measured on one NWP500-65. The recovery, quiet-window and draw figures
are the held-out scoreboard's (``sim_score``): parameters calibrated
(``sim_calibrate.calibrate_changes``) on the record and its metered
draws from 2026-04-16 to 2026-09-18, and scored on the events from
then to 2026-10-26, each started from the layers the record's replay
leaves, with 90 % day-block bootstrap intervals. These were measured
on 2026-10-28, before the start's stir replaced the imposed hold; the
changes since are scored after the list, each against the model before
it, and a new change is scored beside the code it changes
(:doc:`/how-to/calibrate-simulator`), not against these.

- a heat-pump recovery's duration, from physics alone: mean absolute
  error 11.9 min (7.5-16.6) on the 11 with no water moving, a mean
  6.6 min long; 46.4 min (25.6-75.3) on the 16 with water in use
  (drawn, or the circulation running) inside them or in the 30 minutes
  before, a mean 20.2 min short. Over 119 recoveries
  each hot gallon drawn inside one added about 4.7 min to it and each
  minute of circulation about 1.3 min;
- a recovery's electricity, from the map, against the heater's metered
  energy on the 11 metered recoveries: mean absolute error 5.7 %
  (3.6-8.0), a mean 2.5 % low;
- the tank left alone, on the 59 quiet windows: the upper probe within
  0.254 degF RMS (0.226-0.284) and the lower within 0.564 (0.476-0.652);
- the probes over the hour after each of the 46 metered draws: the
  upper within 0.299 degF RMS (0.192-0.463) and the lower within 2.08
  (1.42-2.84) (:doc:`draws`);
- the deliverable gallons at the start of each of the 34 deliveries
  held out, none of which crossed the line, so each delivered at least
  its gallons: 3 % under-promised, by 1.17 gal on average across all
  34 (0-3.40);
- the same parameters on the same events, each started from the two
  probes alone instead of the replay: the lower probe within 1.29 degF
  RMS (1.10-1.51) on the quiet windows and 5.19 (3.38-7.12) after the
  draws, a recovery's electricity 10.3 % off (5.5-15.7), a draw-free
  recovery's duration 9.9 min off (5.6-15.2), and the deliveries 3 %
  under-promised, by 0.91 gal (0-2.66);
- the three draws in the whole record that took the upper probe across
  the line, each with the compressor running: on two, the layered
  tank as first fitted crossed the probe at 26.1 and 31.3 gal against
  the recorded 23.3 and 31.3; the third started below the line;
- the water above the upper probe: one measurement put the tap's
  crossing 5.3-7.3 gal after the probe's; the fitted probe sits with
  6.9 gal of the 63.2 above it.

Two errors in a heat-pump recovery partly cancel. The climb stops when
the model's lower probe, which carries nothing for the compressor's
heating, reaches the target plus the run-on's overshoot, but the
overshoot is measured on the real probe, which after 40 minutes or more
of heating reads about 0.9 degF higher than at rest
(:doc:`recovery-speed`), so a long recovery runs long. And the power was
read at the condenser's water, below the lower probe's reading it was
fitted on: pooled over the 11 held-out draw-free recoveries, 392 W
against the 417 W metered, which offset the long runs in their
electricity. Modelling both, with an offset that builds over the first
minutes of heating, fitted on the stops, cut those 11 recoveries' mean
from 6.6 min long to 2.5 min but raised their mean absolute error from
11.9 to 12.7 min, and the electricity's from 5.7 % to 9.9 %. Over all 21
draw-free recoveries from 2026-04-16 (in-sample before 2026-09-18), the
13 of 90 minutes or more went from 7.8 min long to 3.6, and the 8
shorter ones from 1.9 min short to 8.2. The offset is not applied. The
power is now fitted where it is read, at the condenser's water on the
record's replay: on the same 11 recoveries, with the start's stir, the
electricity went from 2.7 % low to 0.4 % high on average and its mean
absolute error from 4.5 % to 5.0 %, the long runs no longer offset.
The maps are now read along their planes past the spans they were
fitted on, so a recovery from a cold tank gets the heat its cold water
gives rather than the heat at 114 degF: with the tank refitted so, on
the same 11 recoveries the duration's mean absolute error went from 6.9
to 5.7 min (5.0 to 3.1 min long on average) and the electricity's from
5.0 % to 4.5 %, from 0.4 % high to 0.6 % low on average; the 16 with
water in use (drawn, or the circulation running) inside them or in the
30 minutes before went from 47.2 to 48.2 min. On the code of
2026-10-31 the same 16 came out 42.5 min off, a mean 34.1 short. The
five 38 min or more short (38-284) each start within 30 minutes of
10-31 gal drawn, or have a 15 gal draw inside. In two of the three
traced the shower ran on into the recovery: the walk takes a metered
draw at the meter's onset, so its lower probe had fallen before the
start and moved under 1 degF over the next 10 min, where the record's
fell another 13-15 degF, and the walk's probe reaches its target
sooner. Timing each draw
by the draw detector was tried and dropped (:doc:`simulator-tried`, "A
metered draw timed by the draw detector").

**Whole days** (``sim_score.day_events``), measured on 2026-10-31 on the
same split and installation, the parameters fitted on that date's code:
the 29 held-out local days the record observed throughout, each walked
from midnight with the setpoint and mode writes the heater recorded,
the TOU windows it marked (16:00 to 21:00, on 10-02 broken from 19:50
to 20:20), the metered draws, the circulation and the air:

- the day's electricity: mean absolute error 16.5 % (10.8-22.9), a mean
  12.8 % low; within 12 % on 18 of the 29 days. The meter's figure
  holds the heater's idle draw, about 1 Wh an hour, which the walk
  does not: about 1 % of a day's;
- when in the day it was used: 18 % of the day's electricity predicted
  in another hour than the meter put it in (11-27 %);
- two days ordered by their electricity as the meter orders them, 84 %
  of the time (76-91 %);
- the compressor's starts: on a day with any, 79 % of its recorded
  starts placed by a prediction within 30 minutes (68-90 %); 0.41 a
  day placed by none (0.21-0.66), and 0.10 a day predicted that placed
  none (0.03-0.21);
- the upper probe's lowest over the day within 3.8 degF (2.2-5.7), a
  mean 2.8 degF warm.

The days the walk misses are the ones that matter to a schedule. On
three, the record starts at or near the window's close (21:00 on
10-20 and 10-21, 20:41 on 10-18) and the walk does not: its lower probe
reads warmer by then than the trigger, and the day comes out 41 to
100 % low. On two, evening draws in the window (69 and 57 gal on 09-29
and 10-02) took the record's upper probe to 79.5 and 96.1 degF while
the walk's held at 107.5 and 113.3 degF, though it placed the 09-29
start within 3 minutes: the only two days on which the record crossed
the line, and the walk called neither.

Not yet measured on the layered tank: a forecast's draw windows, and
the time to ready and an element run's energy after a switch into an
element mode.


Limitations
===========

- **The inlet temperature.** The device's inlet field reads 0, so the
  inlet is an input, or the parameters' mains on the day: their
  climate's (``DrawParams.climate_f``), else ``inlet_temp_f``.
- **Draw volume.** The device does not report how much water was
  drawn, so draws are an input: a forecast, or a flow meter's record.
- **Supply voltage.** Element power is the fitted 240 V figure.
- **The air at the heater ahead of time.** The ambient is an input: the
  device reports the air at its intake now, not what it will be.
- **The tank's state now.** The heater reports the probes, not how
  much of the tank is cold water from the last draw. The layers come
  from replaying the caller's last day of record, which needs a metered
  draw flow; without it, the profile the probes stand for, which
  promises too much after a draw.
- **The installation.** The mixing valve's setting and the household's
  draws are the installation's: the readiness defaults are one
  installation's (``ReadinessParams``).
