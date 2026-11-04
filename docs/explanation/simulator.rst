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
   opening on the way (up to 8 days; tails owing one past that are not
   counted alike), the same electricity and layers, leaves nothing
   between them unvalued. It takes
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
sooner. Timing each draw by the draw detector was tried and dropped
(:doc:`simulator-tried`, "A metered draw timed by the draw detector").
The one 284 min short (2026-09-30 02:51 UTC) had been walked to the
setpoint in force at its start, 110.3 degF; it was raised to 141.8
3.5 min in, and the heater ran to it. With each change of the setpoint
inside a recovery walked as a write, on the same params on 2026-10-31,
the 16 came out 31.4 min off, a mean 18.2 short, that one 77.3 short
from a tank at 100.9 degF upper and 78.4 lower; and one whose
setpoint rose 1.8 degF 32 min in went from 8.6 short to 38.3 long. The
11 draw-free went from 5.7 to 5.6 min, their electricity from 4.5 % to
4.2 %. With a draw at 2 gal/min or faster under way at a recovery's
start replayed only as far as it ran by then, and walked on from the
start for the rest of its time with the tank's water whole
(``DrawParams.undiluted_gpm``, :doc:`simulator-methodology`, "A fast
draw"), on the same params, the 16 came out 25.0 min off (18.8-31.5),
a mean 11.8 short, and all 27 17.1 min off against 20.9; the draw-free
and the electricity did not move. With a slower draw taking a quarter
of its cold side's share from the tank as well
(``DrawParams.undiluted_share``, :doc:`simulator-methodology`, "A
slower draw"), on the same params on 2026-11-01, the 16 came out 21.2
min off (14.6-28.6), a mean 13.1 short; the 11 draw-free 4.8 min off
(2.7-7.3) against 5.6, their electricity 4.0 % off (2.5-5.7) against
4.2; all 27 14.5 min off. The lower probe over the hour after the 46
metered draws came within 1.74 degF RMS (1.17-2.41) against 2.01, the
upper within 0.30 as before, and the deliveries came out 3 %
under-promised, by 1.35 gal on average (0-3.92) against 1.24.

With every draw the detector timed split at a recovery's start, a slower
one's rest all at the start, as the score walks a slower draw at its
onset, on the same params on 2026-11-02: 44 of the 116 recoveries from
2026-04-17 to 10-26 started inside a slower one (46 inside a timed draw;
the 2 fast ones did not move), a mean 5.8 gal still to run, which the
walk had not taken. The 16 held out came out 18.3 min off (12.3-25.3), a
mean 1.7 short; all 27 12.8 min off. Before 2026-09-18 the 79 with water
in use came out 27.7 min off (21.5-35.3) against 25.3, a mean 25.2 long
against 9.2. On the 44 the mean went from 7.5 min short to 25.3 long, a
mean 23.7 min off to 26.9, in both sets of days the lower probe's error
after a draw falls into (below): leaving the rest out had hidden that
the walk runs a recovery long when a draw runs on into it. Walked over
the rest of its time instead, the 44 came out the same, 25.4 long. The
draw-free and the electricity did not move, nor the days: no local
midnight of the record falls inside a timed draw.

Most of the walk's extra cooling over those recoveries comes at the
later draws inside them (measured 2026-11-02 on the same params). Over
the 46 recoveries started inside a timed draw, from 15 minutes in, the
walk's mean probe fell away from the record's by 2.9 degF an hour over
the 20 minutes from 10-15 before each later draw of 0.5 gal or more to
5-10 after, against 0.2 an hour in the spans with none: 80.6 of the
118.8 degF it fell away in all, summed over 5-minute spans. Over the 75
draws of 1 gal or more alone in their 12 minutes inside a recovery with
water in use, from 10 minutes in to 12 before its end (a mean 6.1 gal),
from 3 minutes before to 12 after, the upper probe fell 2.83 degF in the
walk against 1.77 in the record, the lower 0.67 against 0.01. Before
2026-09-18 the walk's mean probe fell 0.177 degF a gallon further than
the record's (62 draws: 0.169 from 05-01 to 09-17, 56, and 0.273 in
April, 6), its lower probe 0.93 degF a draw further; on the 13 held out,
0.022 a gallon less, the lower probe 0.69 degF a draw less. That is the
fit's split, before 2026-09-18 against after, not the two sets of days
the lower probe's error after a draw falls into with the compressor off
(below), which put April with the days from 09-18; with only 6 draws in
April it may be either. A slower draw's share at 0.1 instead of 0.25 did
not take it out (:doc:`simulator-tried`, "The share at 0.1 on the score
that splits a slower draw").

A walk's ``draw_out_of_domain`` says how far to trust it (measured
2026-11-02 on the same params). Of the 16 held-out recoveries with water
in use, the 10 whose walks said it came out 21.6 min off, a mean 8.9
short (61.4 short to 30.7 long); the 6 that did not, 13.0 off, a mean
10.2 long. The largest, 2026-10-23 22:48 UTC, started from 117.1 degF at
the upper probe, under the 122.2 the draw terms were fitted over
(``DrawParams.domain_upper_f``; the valve's line was measured over
123.8-139.5), and came out 61.4 min short. Its 15.4 gal draw at 1.1
gal/min, 48 min in, took 42 degF a gallon from the walk's tank, and the
walk drew electricity at the record's pace (2.18 kWh to its end, the
record 2.08 to the same minute), yet reached the target on 2.18 where
the record took 2.54: from the same probes, the record used about a
sixth more electricity. Colder water in the record's tank than the
probes show would account for it, as would its heat pump giving less
heat a kWh than the map; the record does not say which, though the 11
draw-free recoveries held out came out 0.9 % under the meter's
electricity on average (4.0 % off each).

A recovery from a mixed cold tank runs short in the walk (measured
2026-11-02 on the same params). On 2026-08-12 03:32 UTC, after four days
in ``VACATION``, the probes read 84.6 and 85.3 degF, and the walk
reached the 140.9 target 38.3 min early (340 against 378 min), on 7.3 %
less electricity than the meter's. Over each 5 degF of the probes' mean
from 90 to 140, the record's climb times the tank's mass, with its loss,
came to 4,190-5,880 BTU/h, 0.96-1.08 of the map's heat, but the walk's
probes climbed 1.11-1.15 times as fast as its own map's heat would warm
the whole tank: its bottom layer, under the condenser, went from 82.8 to
94.8 degF while the probes climbed 56, so the walk reached the target
with some 7 of the 63.2 gal still cold. The heat is fitted as the whole
tank's mass times the record's climb, so a walk climbs faster by the
share of the tank it leaves unheated, whatever the real tank's bottom
does. It does so in the mixed part of nearly every long draw-free
recovery: over 20-minute stretches with the probes within 3 degF, the
walk's climb came to 1.08-1.12 of its map's heat (a median 1.10) in each
of the 11 draw-free recoveries from a lower probe under 120 degF with
five such stretches or more, the record's to 0.98-1.07 (1.01; the map is
fitted on such stretches). Before the probes come together the walk is
slow instead: in the 11 of the 12 from a lower probe under 120 degF that
started with the probes more than 3 degF apart, from 20 minutes in to
the record's first minute with them within 3 degF (32-103 min long), the
walk's probes' mean climbed a median 0.89 times as fast as the record's,
and its lower probe 0.93, slower in 10 of the 11. In those, the two
partly cancel; one from a mixed tank has only the fast part. The 11
recoveries since 2026-04-17 that started with the upper probe under 125
degF came out a mean 2.8 % of the record's minutes short, 8 of them
short, against 10 % long for the other 105. Stirring the water below the
condenser into its pool through a run, not only at its start, took that
one to 2.7 min long and those of 2026-09-30 02:51 and 10-23 22:48 to 5.2
and 4.4 min short, but lengthened nearly every recovery by about as
much, and so did the condenser's span taken down to the bottom
(:doc:`simulator-tried`, "The water below the condenser stirred through
a run", "The condenser's span reaching the bottom"). Moving the
condenser's span higher or scaling the heat down, against the two
errors, did not take them out together (:doc:`simulator-tried`, "The
condenser's span higher, or the heat scaled down"), and neither did its
heat rising as a plume ("The condenser's heat rising as a plume").

**Whole days** (``sim_score.day_events``), measured on 2026-10-31 on the
same split and installation, the parameters fitted on that date's code:
the 29 held-out local days the record observed throughout, each walked
from midnight with the setpoint and mode writes the heater recorded,
the TOU windows it marked (16:00 to 21:00, on 10-02 broken from 19:50
to 20:20), the metered draws, the circulation and the air:

- the day's electricity: mean absolute error 16.0 % (10.4-22.3), a mean
  12.1 % low; within 12 % on 19 of the 29 days. The meter's figure
  holds the heater's idle draw, about 1 Wh an hour, which the walk
  does not: about 1 % of a day's;
- when in the day it was used: 19 % of the day's electricity predicted
  in another hour than the meter put it in (11-27 %);
- two days ordered by their electricity as the meter orders them, 84 %
  of the time (76-91 %);
- the compressor's starts: on a day with any, 78 % of its recorded
  starts placed by a prediction within 30 minutes (66-89 %); 0.45 a
  day placed by none (0.21-0.69), and 0.14 a day predicted that placed
  none (0.03-0.24);
- the upper probe's lowest over the day within 2.9 degF (1.8-4.1), a
  mean 1.8 degF warm; below the line on the same days as the record's.

These are with a draw at 2 gal/min or faster taking the tank's water
whole over the time the detector held it (``DrawParams.undiluted_gpm``,
:doc:`simulator-methodology`, "A fast draw"), on the same params on
2026-10-31. Before it: electricity 16.5 % off (10.8-22.9), 12.8 % low,
within 12 % on 18 days; starts 79 % placed, 0.41 missed and 0.10 false a
day; the lowest upper probe 3.8 degF off (2.2-5.7), 2.8 warm, the end
state 5.4 degF off (3.8-7.3) against 4.8 (3.2-6.6). With a slower draw's
share as well (``DrawParams.undiluted_share``), on the same params on
2026-11-01: electricity 14.3 % off (8.8-20.6), a mean 9.8 % low, within
12 % on 20 days; two days ordered as the meter orders them 86 % of the
time (79-92 %); starts 78 % placed, 0.45 a day missed and 0.17 false
(0.07-0.28); the lowest upper probe 2.6 degF off (1.6-3.8), 1.3 warm;
the end state 4.0 degF off (2.5-5.8). Taken as if the meter had read
since its step what a known volume put it at on 2026-11-03 (the two sets
of days, below), the draws of the days held out from the fit (those the
slower draw's share was chosen on) at 1/0.85 of their metered gallons
(measured 2026-11-03 on the same params): electricity 12.9 % off
(7.7-19.3), a mean 2.4 % low, within 12 % on 18 days; two days ordered
as the meter orders them 90 % of the time (85-95 %); starts 74 % placed
(61-86 %), 0.45 a day missed and 0.28 false (0.14-0.45); the lowest
upper probe 2.3 degF off (1.4-3.5), 0.4 cold; the end state's mean of
the two probes 3.1 degF off (1.7-4.8). 10-20 then starts at 21:00 as the
record does, and comes out 1 % high (2,832 Wh against the meter's 2,805)
where it was 42 % low, the walk's false start kept (at 11:56) and the
record's at 07:35 still missed; 10-18 still does not start. The draws of
late September it likely takes too far (the same, below). The reading is
``DrawParams.meter_reads``, 1 (the meter as it reads) unless set: at
0.85 it takes every draw so where the walk, the replay and the score
take it, and puts the same days within 0.01 of these, the held-out days
all falling after the step (measured 2026-11-03). The false starts it
adds are starts the record made, taken early, and one more (measured
2026-11-04, 8 against 5): 09-28's goes, and the starts of 09-18, 09-23
and 10-11, placed as metered, come 118, 57 and 56 min before the
record's. 09-18's and 09-23's follow a draw the walk takes further than
the record: 09-18's 17.8 gal leaves its lower probe 21.9 degF under the
record's at the end of the hour it was drawn in, against 15.7 as
metered, the record's falling over the hour after; 09-23's 10.5 leaves
its upper probe 3.5 under an hour before the window's opening, against
0.7 over. 10-11's comes in an hour of 6.6 gal, its lower probe level
with the record's at the hour before and 2.1 degF under it at the hour
after, so its hour's samples do not show why. 10-24 gains a start at the
window's close, its lower probe falling 33.0 degF over the hour of a
21.1 gal draw to 7.8 under the record's, whose fell 6.5 with the heater
running. The missed starts stay 0.45 a day: 09-28 gains the record's two
and 10-20 one, the three early ones lost.

After a large draw the walk's lower probe falls at once, the record's
over about ten minutes (measured 2026-11-04 on the clean compressor-off
draws of 8 gal or more, their hour after, each walked as the score walks
it, at its onset unless at ``undiluted_gpm`` or faster). Over the 28
held out, the record's comes to half its hour's fall a median 10 minutes
after the walk's (11 against 1, later in 27 of the 28 as metered and in
all 28 at 0.85); over the 95 from 05-01 to the step, 8. The walk stands
furthest under the record a minute in, a median 10.7 degF as metered and
12.8 at 0.85, by 5 degF or more in 22 and 23 of the 28. By the hour the
gap is gone: a median 3.1 degF the other way as metered, the record
ending under the walk in 23 of the 28, and 0.1 at 0.85. 09-18's early
start is that fall: the walk's lower probe stands at 104.6 degF a minute
after the draw, under its 104.9 trigger, where the record's fell to
111.9 by 10 minutes and 109.6 by the hour. Each draw walked over the
detector's span instead, the record's half comes a median 2 minutes
after the walk's and the walk's dip is 4.2 degF at 11 minutes (at 0.85),
but the days come out no better (:doc:`simulator-tried`, "Every timed
draw walked over its span, the days"). The figures here on the lower
probe's fall over the hour after a large draw (by the draw's length, at
the meter's reading) walk each draw over the detector's span; walked as
the score walks it, the hour's fall comes out about the same, a median
3.0 degF short against 2.9 as metered and 0.1 too far against 0.5 at
0.85 on the 28, and before the step 0.0, 1.4 and 4.1 degF further than
the record by length against 0.1, 1.6 and 3.6 (the 95). What follows is on the draws
as metered.

The days the walk misses are the ones that matter to a schedule. On
three, the record starts at or near the window's close (21:00 on 10-20
and 10-21, 20:41 on 10-18) and the walk does not: its lower probe reads
warmer by then than the trigger, and the day comes out 41 to 100 % low.
The record's lower probe sat within 0.5 degF of its 104.9 degF trigger
(104.7 at 07:35 on 10-20, 104.4 at 21:00 on 10-21), and the walk's 11 to
12 degF above it; its running power matched the record's, about 400 W,
and it ran 2 to 3 h a day less. The window shows the shortfall, it does
not make it: the slower draws cooled the walk's lower probe less than
the record's, over the 32 held-out draws of 8 gal or more with the
compressor off 11.1 degF against 14.9, walked from the record's own
state before each with its draws over the hour. At 20:41 on 10-18 the
record's upper probe was 14.2 degF short of the setpoint, at the
window's 14.4 degF start, the walk's 12.3. With a slower draw's share as
well, those draws cooled it 12.6 degF, and 10-21 starts at 21:00 and
comes out 4.5 % low; 10-18 and 10-20 still do not start. On two, evening
draws in the window (69 and 57 gal on 09-29 and 10-02) took the record's
upper probe to 79.5 and 96.1 degF, the only two days on which the record
crossed the line. Each held one draw of 31 or 54 gal at 2.4 or 2.7
gal/min. Through the valve the walk's upper probe held at 107.5 and
113.3 degF and called neither. Taking that draw's water whole over its
time, it fell to 96.2 and 94.8 degF and called both. 10-02's electricity
went from 2.6 % high to 7.7 % high, and 09-29's from 5.0 % to 3.3 %. On
09-28 a 19 gal draw at 2.2 gal/min moved a start, one more missed and
one more false, and the day's electricity went from 27 % low to 9 % low.

Of the two days still missed, 10-18 and 10-20 (measured 2026-11-02 on
the parameters fitted before 2026-09-18, the share at 0.25), neither
shows a fault that a term was seen to mend. On 10-18 the walk's upper
probe matched the record's to 11:00 and was 2 degF warmer by 20:41: the
day's draws and the evening's coast each took it a little less. The
coast, from 15:00 to 20:30 with no circulation and 0.1 gal drawn, took
the walk's upper probe 0.60 degF an hour against the record's 0.72 (a
line fitted over the half-hours), from a walk 1.3 degF warmer than the
record at the upper probe and 5.6 at the lower, its probes 15 degF apart
and the record's 19. On the 59 held-out quiet windows, each started from
the record's state (measured 2026-11-03 on the same params), the walk's
upper probe fell as the record's, 0.002 degF an hour the less pooled
over 456 hours, and on the 21 starting with the probes more than 5 degF
apart 0.02 an hour the further; of the 13 of those 5 hours or more, none
fell more than 0.035 degF an hour the less (a standard deviation of
0.034). The walk takes no coast short on average, but the evening's 0.12
is more than any such window, and may come from the state the day's walk
carried to 15:00 rather than from the coast. Over the clean draws of 8
gal or more (less than a gallon of other draws in the hour after) the
upper probe's fall in the hour after came out 0.11 degF too small before
2026-09-18 (110 draws, a standard error of 0.05) and as the record's
after it (28, 1.40 against 1.39 degF, a standard error of 0.19), though
the later draws are among those the share was chosen on. The record's
start came within 0.2 degF of the line. On 10-20 the record started
twice. The draws of 06:03 and 07:12 (11.4 and 6.3 gal) took its lower
probe from 131.9 to 104.7 degF by 07:35, when its compressor came on,
and the walk's to 113.8; the walk started at 11:58 instead and heated
until about 16:00, so it met the draw of 18:31 (15.8 gal) with its lower
probe at 140.4 degF against the record's 130.6. That draw took the
record's to 97.3 by 19:00 and the walk's to 113.8, which left the walk 8
degF above the trigger at 21:00, when the window closed and the record
started. Over the 169 draws of 8 gal or more with the compressor off for
the hour after, the walk's fall in that hour is 1.2 degF too far on
average before 2026-09-18 and 2.2 too short after it, with a spread of
4.1 degF about those means (one standard deviation, the draws on both
sides together). The error follows the tank's temperature at the draw
weakly (a correlation of -0.25 with the upper probe, 6 % of its
variance, the walk falling further from a hotter tank), and none of the
other inputs the walk is given, the draw's gallons or flow, the time
since the last heating, the hour or the air, follows it with a
correlation over 0.22. A scheduler sees only the walk's margin to a
trigger. For the lower probe's, the measurement above, each draw walked
from the record's state over the hour after it, puts the walk's error at
about 4 degF a draw (4.2 degF RMS before 2026-09-18) and about 5 on the
draws since (4.9, the walk standing about 2 degF high). A day's walk,
which carries its own state from draw to draw, can be further off, as on
10-20, where at 21:00 the walk stood 8 degF above its trigger and the
record 7 below it. For the upper probe's, which set 10-18's start, the
same walk, read at the hour's end on those draws, puts the error at
about 0.5 degF a draw (0.51 RMS) before 2026-09-18 and about 1 (0.97)
since, yet on 10-18 the walk's upper probe ran 2 degF warm by 20:41. A
start the walk calls or misses by less than a probe's error a draw
should be read as uncertain, and after a day of draws a wider margin can
be too, as on 10-20, where at 21:00 the walk's lower probe stood 15 degF
above the record's. ``sim.start_margins`` gives each coast of a walk its
nearest approach to each trigger. On the 29 held-out days (measured
2026-11-03 on the same params, the draws as metered) the walk placed all
but 11 of the record's compressor starts within 30 minutes, and 3 of the
11 fell on coasts it did not start, 5 on coasts it started at another
time and 3 while it was heating. By trigger, inside the windows 2 of 23
such coasts: 10-18 at the smallest upper margin, 1.8 degF, at the
window's close, and 10-24 at the fourth smallest, 7.8; for the lower
trigger 1 of 24, 10-20 at the second smallest, 7.0 degF. The lower
margin of 23 of the 24 is read at the walk's end, where it stops. Three
misses rank the margin; they do not fix a threshold.

The lower probe's error after a large draw falls into two sets of days,
not the fit's split (measured 2026-11-02 on the same 169 draws, walked
as above, grouped by the site's local dates). From 05-01 to 09-17 the
walk's fall over the hour is too far by a mean 1.5 degF (121 draws, a
standard error of 0.3), with no difference from month to month inside (a
one-way analysis of variance over its four months and 09-01..09-17, p =
0.78) nor a trend over its days (p = 0.35). Over 04-17..04-30 and from
09-18 it is too short, by 1.6 (16, 1.2) and 2.2 degF (32, 0.8), the two
alike (p = 0.68). Inside the fit period alone April's error is 3.1 degF
the higher, the walk the shorter (p = 0.026), so no constant term fitted
there takes the shift out. The two sets part after the draw has run.
From 05-01 to 09-17 the walk's fall is 1.6 degF the further by 15
minutes and stays so, over all the draws. In the other days the two
agree to 15 minutes, after which the record's lower probe goes on
falling: over the clean draws timed to end within 15 minutes, 1.7 degF
from 15 to 60 minutes after the draw (31) against the walk's 0.8, where
from 05-01 to 09-17 it falls 1.3 (74) against 0.8. Water the house's
draw detector did not count is not seen to account for that further fall
in the other days (measured 2026-11-03 on the clean draws among them
from 09-18, 14 with the compressor off, no circulation in the hour and
no draw counted from 15 to 60 minutes after). Of the 12 among them with
the detector quiet then (2 more showed demand), after 8 the house meter
read 0.34 to 1.16 gal over those 45 minutes while the detector showed no
demand, where none of 753 quiet 45-minute windows after the meter's step
(2026-09-12 19:51 UTC, described below) read 0.3 gal (8 % before it);
but the record's lower probe fell 0.70 degF further than the walk's over
those 8 (a standard error of 0.24) and 0.85 (0.38) over the 4 that read
less, with no rise in the further fall with the water inside the 8 (a
correlation of -0.27). Nothing the walk is given follows the shift. In
quiet hours, with no draw, heating or circulation in the hour or the 30
minutes before, the walk's lower probe drifts as the record's to within
0.13 degF an hour in every half-month (25 hours each). At each draw the
replay's lower probe sits within 0.17 degF of the record's (0.03 for 95
% of the draws), and its upper within 0.28 (0.06), before the correction
to them. The air by the heater (a mean 73.3 and 71.8 degF), the gallons
and flow and the water drawn since the last heating do not separate the
two sets. The time since the last heating (a mean 462 and 338 minutes)
and the minutes of water in use after the draw (3.0 and 1.0) differ in
their means (not by rank), but the first would move the error the other
way, as it follows it from 05-01 to 09-17 (a correlation of +0.30), and
the second barely follows it in either. None of these follows the error
inside either set more strongly than the tank's temperature at the draw
does from 05-01 to 09-17 (-0.33; -0.02 in the other days). Moving the
mains 5 degF either way moves the error from 09-18 by 0.7 degF, so it
would take them some 15 degF colder than the model, where an inlet probe
read them 1.5 degF warmer over 09-20..10-28 (:doc:`simulator-tried`,
"The mains colder, for the lower probe's error after a draw"). On these
draws, 2026-04-17 to 10-25, a scheduler reading the lower probe's margin
after a large draw should take the walk as falling about 1.5 degF too
far from May to mid-September and about 2 too short in late April and
from mid-September, beside the spread of about 4 degF a draw. Which set
a day outside them falls in is not known. Left to place the split
themselves (measured 2026-11-03), the 153 draws from 05-01 put it
between 2026-09-12 17:02 and 09-13 19:06 UTC, a mean 1.67 degF too far
before (117) and 2.30 too short after (36), no split of them shuffled as
good in 2,000, and a step there fits them better than a line over the
days (a squared error of 2,195 against 2,376, of 2,630 about the mean);
the record's 36 after it cannot tell a step from the season turning. The
recoveries with water in use have their best split about two weeks
earlier, between 08-29 16:52 and 08-30 16:56 UTC, 11.5 % of the record's
minutes long on average before (67) and 1.9 % after (28), but as good a
split came of them shuffled in 6 % of 2,000. The lower probe's split
holds a step in the house meter, whose gallons size the draws: at
2026-09-12 19:51 UTC the meter (a Droplet) began reading the circulation
pump's runs lower (:doc:`standby-loss`, "What the pump's flow says").
Its reading of the pump's runs of 5 to 8 gallons also fell through the
record, from 0.98 in April to 0.76 in October (at 8 to 12 it held at
about 0.94 from July to the step), and the runs either side of the step
are too few to fix the step's size. With each draw before then taken as
0.90, 0.87 or 0.81 of its metered gallons, in the replay and the walk,
the same 117 draws come out 0.92, 1.66 and 3.09 degF too short (standard
errors about 0.3), against 2.2 (0.8) for those held out, whose draws it
does not scale (measured 2026-11-03, :doc:`simulator-tried`, "The draws
before the meter's step scaled down"). April's do not follow: its 16
draws go from 1.6 to 4.9, 5.9 and 7.7 degF short. Nor are April's air,
model mains and lower probe at the draw, or the replay's start, seen to
account for its draws (measured 2026-11-03). April's air is colder (a
mean 65.9 degF against 73.2 from 05-01 to the step), its mains in the
model colder (66.4 against 71.0) and its lower probe warmer at the draw
(140.4 against 137.0); each one's slope inside 05-01 to the step moves
April's draws toward too far, by 0.03, 0.27 and 0.59 degF, where they
are 1.60 too short (April's mains lie below the range of those from
05-01, so the second is extrapolated). The replay started on 05-01
instead of 04-16 puts the draws of 05-01 to 05-14 0.63 degF too far
against 0.79 (14), and those of 05-15 to 06-14 1.94 either way (34), so
the first two weeks of May sit between April and those of 05-15 to 06-14
on either start. A known volume puts today's reading low (measured
2026-11-04 03:19 UTC): 1.00 gal, as the vessel holds it, filled at a hot
tap with no other water in use and the circulation pump off, read 0.846
gal, so on that day the meter read 0.85 of the water it passed (one
fill, which the meter read backwards, to about 0.03 from its own noise).
It measures that day alone: the meter's reading of the pump's runs of 5
to 8 gallons went on falling after the step, from 0.84 to 09-30 to 0.76
from mid-October, so if those runs held their flow, and the meter read
them as it reads a tap's draw, it read nearer 0.94 in late September.
The runs tell that fall from their own shortening only weakly (measured
2026-11-04 on the 49 after the step): a run's reading falls 0.0022 a day
on the date alone (a standard error of 0.0007), and fits about as well
on its length (0.920 less 0.75 over its gallons, a residual of 0.059
against 0.057), the runs' weekly median falling from 7.8 gal in the
first week to 5.0 in the last and the two correlated 0.73. Taken
together the date keeps a slope of 0.0020 (0.0010), about two standard
errors, and the length's falls to 0.13 (0.41): the runs lean toward the
meter's fall, not decisively. The 0.94 holds if the fall is the meter's.
Taken as if the meter had read 0.85 since the step, the held-out draws
at 1/0.85 of their metered gallons, in the replay and the walk, put the
walk's lower probe after their 32 large draws 1.45 degF too far (a
standard error of 0.79) where as metered it falls 2.21 short, those of
09-18 to 09-30 2.00 too far against 1.57 short (15) and those from 10-01
0.96 too far against 2.77 short (17), its RMS 4.60 against 4.86; their
16 recoveries with water in use come out 20.9 min off against 18.3 (7.2
long against 1.7 short) and the 11 draw-free 4.2 against 4.8. The draws
are sized from the meter outside this package, unscaled, and taken at
``DrawParams.meter_reads`` (1 unless set). On these
parameters, fitted on the earlier gallons, the walk on the held-out
draws as metered (2026-09-18 to 10-25, after the step) falls about 2
degF short after a large draw. The walk's error after a large draw
changes with the draw's length, the other way either side of the step
(measured 2026-11-03 on the clean draws of 8 gal or more with the
compressor off from 05-01, the lower probe's fall over the hour): before
it the walk falls 0.1 degF further than the record over the draws of 10
minutes or less (29 of them), 1.6 over those of 10 to 15 (42) and 3.6
over those of more than 15 (24); after it, 1.3 less (4), 1.3 (21) and
6.4 (6, a standard error of 1.8), so that after the step the growth
rests on its 6 longest draws. Whether the change at the step goes with
the draws' minutes or their metered gallons the record does not tell
(pooled and taken per spread, 2.8 and 1.2 degF, the minutes ahead in 78
% of resamples). The clean draws of 8 to 12 and 12 to 16 metered gallons
run longer after the step (medians of 9.5 against 11.3 minutes and 12.2
against 14.0), as a lower reading or a slower flow would have them; the
4 of 16 to 30 do not. Before the step the meter read the pump's longer
runs higher against the pump than its shorter ones (0.86 under 5 gal,
0.94 at 8 to 12), which fits the longer draws falling further then;
after it the longer runs read higher too (0.79 under 8 gal over 45 runs,
0.87 at 8 to 12 over 4), but the longer draws fall less. What sets the
change the record does not show.

At ``DrawParams.meter_reads`` 0.85 the walk's lower probe falls further
at every length, the longest draws' error coming down and those of 10 to
15 minutes going past the record's, and the error's growth with minutes
stays (measured 2026-11-04 on the 28 of those draws from 09-18, held out
from the fit). The walk falls 0.9 degF further than the record over the
draws of 10 minutes or less (4), 2.1 further over those of 10 to 15 (18)
and 1.8 less over the longer (6), against 1.3, 1.2 and 6.4 less as
metered: 2.2 degF off the shortest, 3.4 off those of 10 to 15 and 4.6
off the longest, which carry more gallons. The growth is 0.24 degF a
minute (a standard error of 0.13) against 0.28 (0.12) as metered, and
taken with the gallons the minutes' term holds at 0.27 (0.13), the
gallons' going from 0.21 (0.27) to -0.30 (0.27). Without one draw, 10-02
00:50's 9.4 gal over 43 minutes, it is 0.14 (0.24) at 0.85 and 0.37
(0.23) as metered: that draw carries the growth's standard error at
0.85, not most of its size, and without it neither is told from none.

Circulation running through a summer recovery slows the walk's more than
the record's (measured 2026-11-03 on the parameters in use, the share at
0.25, every scored recovery walked with the record's runs, setpoint
writes and draws, a slower draw under way at its start split there). Of
the 21 recoveries with circulation inside them, the 16 before 2026-09-14
came out a mean 57 min long (61 min absolute), the six from 07-08 to
08-04, each with 22 to 28 minutes of circulation, 38 to 240 min long,
07-28 16:45 UTC's 152 among them; the five from 09-14 came out 9 min
long (13 absolute), and the 72 of the fit period with none 14.7 (18.4).
Walked without the runs, the 16 came out 16 min short. Measured on
2026-11-02, before a slower draw under way at a recovery's start was
split there, the 16 were 45 min long, the five 3 and the 72 0.3; what
the runs add to the 16, walked with them against without, is 72 min then
and 74 now. The heat the summer's runs took is priced about as the
record measured it: each run's flow times the drop from the upper probe
to the return line came to 1.16 and 1.03 times the walk's price for it
at the 1.40 gal/min the walk prices runs at, over the 44 and 42 runs of
July and August with the compressor running (1.04 and 1.01 over the 45
and 48 with it off). 07-28's seven runs overlapping the recovery,
counted whole, measured 10,177 BTU against the walk's 12,744. Where the
walk takes that heat from differs. Over the hours of July and August
holding a run and no draw or heating (53), the walk's lower probe fell
10.0 degF against the record's 5.3 and its upper 1.7 against 1.2, where
over September and October (16) the two came within about 0.6 degF. The
heat pump stops on the lower probe, so a walk whose lower probe the runs
keep cool runs on. Why the summer's runs reached the record's lower
probe less is not known; priced at 1.05 gal/min, about 07-28's runs' own
flow, 07-28's walk without its setpoint write stopped 10 minutes sooner,
of the 109 it was long (:doc:`simulator-tried`, "The circulation priced
at the runs' own flow"). On this record a walk's recovery with
circulation inside it reads long by up to hours in July and August, and
from mid-September no longer than one without circulation.

A forecast's draw windows, and the element modes, measured 2026-11-02 on
the parameters in use (fitted before 2026-09-18, the share at 0.25):

- **A forecast's draw windows.** The 29 held-out days of the day
  backtest (2026-09-18 to 10-25), each walked as the heater was told
  over it, with the draw forecast issued before the day in place of the
  metered draws: 225 windows, about 8 a day. The record's upper probe
  crossed the line in 4 (in one measured bath the delivered water
  crossed 5.3 to 7.3 gal after it, :doc:`draws`), two adjacent windows
  on each of the two depletion days (the evenings of 09-29 and 10-02,
  local). The walk on the forecast flagged none of the 4, on the
  forecast's expected draws or with each window's long draws placed
  first and heat withheld over them, and none of the other 221. The
  forecast expected 4.3 and 2.8 gal in the first window of each where
  the meter read 30.8 and 54.4 (the median window expects 2.2). Walked
  on the metered draws, the same days flag all 4 and none of the others:
  the misses are the forecast's. On 09-29 the walk on the forecast left
  14.6 gal deliverable at the window's opening, 10.3 over what it
  expected; on 10-02, 46.5, 43.7 over.
- **An element run's energy after a switch.** The record's 46 switches
  into an element mode (2026-04-16 to 10-19; 25 to Energy Saver, 16 to
  Electric, 5 to High Demand), each walked with the mode written at the
  switch, to the record's next mode change. In 19 the record or the walk
  ran an element for 0.05 kWh or more. Over each, from the switch to the
  later of the two's last element run's end inside the hold (a median 12
  min), the heater's whole electricity came to 20.58 kWh in the walk
  against 20.27 in the record (1.5 % high), a mean 0.102 kWh off (median
  0.045), 10 within 0.05 kWh; the 5 held out (from 2026-09-18), 3.20
  against 3.21, a mean 0.120 off. The elements' running time was a mean
  1.0 min off. The 9 of them to Electric, where the compressor does not
  run beside the element, came to 8.15 against 8.19 kWh, a mean 0.034
  off. The six largest misses are switches to Energy Saver, where it
  does: on 05-05 04:45 UTC the element ran 7.6 min in the record and
  12.3 in the walk. These are with a draw under way at the switch split
  there (``sim_score``, above). Before, the switch at 04-28 13:40, 6 s
  into a 29.7 gal draw at 1.7 gal/min, was walked without the draw: the
  element ran 11.2 min against the record's 22.6 (21.9 with it), and the
  19 came to 19.68 kWh, 2.9 % low, a mean 0.150 off. Two of the six,
  both high (05-05 and 10-03, the element 0.36 and 0.24 kWh more in the
  walk), are the walk's upper element running on. It stops on the upper
  probe (in Energy Saver 1.62 degF short of the setpoint,
  ``ElementParams.energy_saver_upper_off_below_setpoint_f``), and the
  walk's probe climbs slower under it: at its height, 0.72 of the column
  (21.1 gal from there up), the model's climb from a mixed tank is about
  1.6 degF a minute, where the record's 29 clean element runs climbed
  2.0 (:doc:`simulator-tried`, "The upper element higher"). Over the
  first upper-element run after the 4 draw-free switches to Energy Saver
  where the record's ran 2 min or more and the walk's ran with it, the
  record's upper probe climbed 1.60 degF a minute and the walk's 1.19,
  over 6.5 min against 8.9 (measured 2026-11-02); after the 4 such to
  Electric, 1.88 against 1.37, over 10.5 min against 12.8. In Electric
  the lower element heats what the upper leaves, so the elements' whole
  running time came out alike (05-01, 20.4 min in both); in Energy Saver
  the compressor heats the rest, and over 05-05 and 10-03 it did not run
  less to offset the element's extra. The other four are not this: on
  04-30 the element's energy matched and the miss is the compressor's,
  over a 500 min hold; on 09-21, 04-21 and 04-28 the walk's element ran
  less.
- **The time to ready after a switch** is scored only where the tank
  could not already deliver the bath at it: by the record's probes, 3 of
  the 46 at the default 28.7 gal (one 1.5 s after a TOU window's close,
  where the heater's marker still read the window in force, so
  ``time_to_ready`` took the mode as not reachable; the heater took it),
  6 at 50 gal. Read on the probes in both, the walk was slower in each
  of the three the record's hold reached: at 28.7 gal, 05-05 04:45 UTC,
  16 min in the record against 76; at 50 gal, 04-30 16:08, 16 min
  against 32, and 05-05, 99 min against none inside the 110-min hold. On
  04-28 13:40 neither reached the bath in its 22.7-min hold (the walk
  did in 10 without the draw under way at the switch). ``time_to_ready``
  reads the walk's layers, not its probes: at 05-05 it found the bath
  ready at the switch, where the record's probes delivered 23 gal.


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
