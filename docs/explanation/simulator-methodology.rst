===========================
How the Simulator Works
===========================

This page explains the methods behind ``nwp500.sim``: how a simulation
moves forward in time, the physical model of each part of the heater,
how its parameters are fitted and checked, and what each sensor
contributes. :doc:`simulator` describes what the simulator answers and
how accurate it is; :doc:`/reference/simulator-inputs` lists every
input and parameter.

.. contents::
   :local:
   :depth: 2


The approach
============

The simulator models the heater as two things joined together: the
heater's firmware, which decides when to heat and with what, and the
physics of the tank, the heat pump and the elements, which decides how
the tank's temperatures move in between. The firmware is a state machine
whose rules were read off the heater's own record and device tests. The
physics are compact models with a few free terms, fitted to one heater's
recorded history and checked on later records it was not fitted on.

Four ideas run through the whole simulator:

- **Two probes, a layered tank.** The heater reports two thermistors,
  one high in the tank and one low. The model's tank is a column of
  layers that conserves its heat, and the probes are its observations:
  where they read and how widely are fitted so the model's probes track
  the record's.
- **Events, not time steps.** Nothing the firmware decides happens
  between events, so the walk jumps from one event to the next and lets
  the physics carry the tank across each span.
- **Fitted against the record, scored on later records.** With
  ``keep_better`` each group of terms holds out the latest part of a
  record and is scored on it, in time order, so a term that only fits
  its own data shows.
- **Say what an answer rests on.** Each answer lists its ``reasons``
  (where it may be less than it seems) and ``defaults_used`` (every
  input it assumed), so a caller can tell a measured answer from an
  assumed one.


The walk
========

A simulation is a walk over the scenario's span, from ``start`` to
``start + horizon``.

**Events.** The walk keeps a list of what happens next: a reservation
entry firing, a setpoint or mode write, a TOU window opening or closing,
a pending compressor start coming due, the restart lockout or an
element's dead time ending, a draw window's edge. It also looks ahead
along the tank's predicted path for the events the tank itself causes:
the lower probe falling to the heater's start threshold, the upper
probe falling to where an element mode starts again, a recovery reaching its
target. The nearest of these is the next event.

**Between events.** The walk moves the tank to that instant with the
physics: a coast when nothing heats, a recovery when the compressor
runs, with an element's heat laid over either. Then it hands the event
to the controller.

.. only:: html

   .. mermaid::

      flowchart TD
          A["Scenario: state, settings, schedules, air, draws, writes"] --> B["Next event: fixed instants, and crossings on the tank's predicted path"]
          B --> C{"Compressor running?"}
          C -- yes --> D["Move the tank along the recovery's path"]
          C -- no --> E["Coast: standby loss, draws, circulation"]
          D --> F["controller.transition(state, event)"]
          E --> F
          F --> G["Carry out the actions: start, stop, retarget, set the mode"]
          G --> H{"At the horizon?"}
          H -- no --> B
          H -- yes --> I["Result: path, heating intervals, energy, reasons"]

**The controller.** ``sim.controller`` is the firmware as a pure
function: ``transition(state, event, settings, params)`` returns the
heater's new state and the actions it takes (start the compressor, stop
an element, set a mode). It reads the tank only through the event it is
given and through predicted paths, and keeps no state of its own. Its
rules and the evidence for each are in :doc:`what-starts-a-recovery`,
:doc:`tou-recovery-cap` and :doc:`heating-elements`.

The compressor's part of the state moves through these phases; a start
that comes due while it is locked out waits as a pending start until
the lockout ends:

.. only:: html

   .. mermaid::

      stateDiagram-v2
          [*] --> idle
          idle --> holding: start, with a hold
          idle --> heating: start, no hold
          holding --> heating: the hold ends
          heating --> locked_out: stop at the target, a write or a mode
          heating --> capped: TOU cap stop
          capped --> idle: the window closes
          locked_out --> idle: 330 s after the stop

**Finding a crossing.** The tank is walked between events (below), and
the walk finds the instant a threshold is crossed to the second. A draw
that takes the lower probe past the threshold places the crossing at
the draw's own instant.

**A running recovery is the tank walked with the compressor on.** From
its start the tank is walked with the condenser heating it, through
whatever draws, writes and element events come, until the lower probe
reaches the stop. Nothing is predicted ahead and put back: after a
draw or a pause the walk goes on from the tank as it stands.

**Details the firmware imposes.** Setpoints are rounded to the device's
0.5 degC. A reservation entry fires at the start of its minute. A start
inside the restart lockout waits until the lockout ends. At the horizon,
whatever runs is cut, with the stop reason ``horizon``.


The tank
========

**State.** The tank is a column of layers of equal volume, 12 by
default (``TankParams.layers``), the bottom first, each mixed within
itself: HPWHsim's stratified tank (``physics.stratified``). The whole
tank's mass is

.. math::

   m = 8.34\,V

where :math:`V` is the storage volume (63.2 gal for the 65 gal model),
so :math:`m` is about 527 BTU/degF, and each of the :math:`n` layers
holds :math:`m/n`. Every operator below conserves the layers' energy to
rounding.

**The probes.** The probes read the layers; they are not the state.
Each reads the layers around its height (a share of the volume from
the bottom), weighted by :math:`e^{-d/s}` with the distance :math:`d`
along the column and its spread :math:`s`, and the lower one reads a
fixed offset above them. A walk that starts from the two probes alone
builds a profile they read back exactly (``estimate``) and says
``tank_profile_estimated``.

**Standby.** Each layer relaxes toward the air beside the heater, at
:math:`T_a`, through its share of the sides' loss, the bottom layer
through the bottom's too and the top layer through the top's, with
:math:`t` in hours:

.. math::

   \frac{m}{n} \frac{dT_i}{dt} = -\left(\frac{UA_s}{n}
   + [i = 1]\,UA_b + [i = n]\,UA_t\right)\left(T_i - T_a\right)

Each step solves it exactly, so no layer passes the air and a tank at
the air stays there. The bottom's loss cools the bottom layer faster
than the rest, so a tank left alone stratifies, as the record shows.
:doc:`standby-loss` has the measurements.

**Conduction.** Neighbouring layers exchange heat through the column's
conductance (``conductance_btu_hr_f``, end to end): conduction in the
water and the slow mixing between layers. It is sub-stepped so no layer
passes its neighbours.

**Turnover.** A layer warmer than the one above turns over at once: the
layers pool to their mean. Heat put in low rises to where it belongs
so.

**Steps.** A walk steps every 10 minutes with nothing heating or
flowing, and every minute while something is, on a grid anchored to
the clock, so a walk split at a step's end is the walk whole. Within a
step the draws at its start are taken, then the heat goes in, the water
flows, the tank loses, the layers conduct, and inversions turn over.
A stop (a target reached, a threshold crossed) is found to the second.

**The air.** The ambient is given as readings (or one value) and
interpolated onto a 10-minute grid. A coast reads it at each step; a
recovery uses its mean over the recovery's span (below).


A heat-pump recovery
====================

**The map.** The heat pump is modelled by what it does, not by its
refrigerant: the heat it puts into the tank :math:`\dot Q_h` and the
electricity it draws :math:`P`, each a plane in the air at the heater
:math:`T_a` and the lower tank's water :math:`T_L`, quoted at 65 degF
air and 120 degF water (``physics.heat_pump``):

.. math::

   \dot Q_h = Q_0 + q_a\,(T_a - 65) + q_w\,(T_c - 120), \qquad
   P = P_0 + p_a\,(T_a - 65) + p_w\,(T_c - 120)

where :math:`T_c` is the water the condenser heats: the layers it
wraps, weighted by how much of each.

Each is read with the air and the water held to the span it was
fitted over (the heat's 61 to 89 degF air and 114 to 144 degF water,
the power's 45 to 90 degF air and 73 to 148 degF water, on the record),
so a recovery outside it takes the nearest edge rather than
extrapolating. The heat is fitted on a mixed tank, where the tank's
mean and the condenser's water are within a few degrees; while the tank
is stratified the condenser's water is below the heat's span and the
heat is the edge's.
The COP is :math:`\dot Q_h / 3.412 P`, and the heat taken from the air
is :math:`\dot Q_h - 3.412 P`: what the condenser gives is what the
evaporator takes plus the electricity, by construction. A fitted map
must claim nowhere over its domain a COP above 0.6 of Carnot's between
the air and the water, heat given to the air, or under 50 W; one that
does is not applied. Each plane is checked with the one it would be
applied with.

**The climb.** The tank is walked a minute at a time with the
condenser's heat, :math:`\dot Q_h` at the step's air and condenser
water, spread over the layers it wraps (``TankParams.condenser_span``),
while the tank loses and conducts as it does standing. The heat put in
low rises: the layers it heats turn over into the ones above as they
pass them, so a stratified tank heats from the bottom up and the upper
probe holds until the warm water reaches it. The electricity is
:math:`\int P\,dt` over the same steps. The climb stops when the lower
probe reads the target (``hp_lower_off``) plus the run-on below (in
``simulate`` and ``active_cycle``, and in ``forecast`` to the heater's
own threshold, not a partial charge's), or after 16 hours, reported as
truncated. Each step reads the air at its start, so a recovery runs in
the air its own span has.

**The start's hold.** After a start the compressor runs some minutes
before the lower probe climbs, while the refrigerant circuit and the
condenser warm. The hold is ``CompressorParams.start_hold_min``, a
value for each band of time the compressor was off (under 15, 60, 180
and 720 minutes, and beyond): 0, 5, 10, 18 and 22 minutes on the
record (:doc:`recovery-speed`). The tank holds as it started through
it, drawing the map's power there, and the climb follows. A caller may
pass its own ``start_hold`` by time off, or ``running_hold`` for a
compressor already running.

**The run-on.** The heat pump does not stop the moment the lower probe
reaches its target: on the record it stops a median 0.9 degF past it
(``ControllerParams.hp_stop_overshoot_f``). The climb is integrated to
the target plus that overshoot. The TOU window's cap on the lower probe
is still judged at the target.

**The operating range.** The heat pump runs only with the air at the
heater at 41 to 113 degF and the water in the tank at 50 to 149 degF
(the user's manual, 3.13.1; ``ControllerParams.hp_air_range_f`` and
``hp_water_range_f``, the water read at the lower probe). The walk finds
where the air readings cross either air bound, exactly on the readings
themselves, and checks the water at each coast point, after each draw
and where a recovery ends; at an instant where the range changes, the
change comes before anything else that lands there. Outside the range a
running compressor stops, every mode heats as Electric does, and the
heater's own triggers and a write's start go to the elements: the upper
element, then the lower (3.13.4, "If the heat pump cannot operate, the
electric heater will be used"). A recovery stops at 149 degF at most,
and the elements finish a target above it. Back inside the range with
an element still heating, the recovery returns to the heat pump where
the compressor starts as it does out of Electric with room to heat
before 149 degF: it starts at once, or when its lockout ends, and an
element started in its place that the mode would not run (Electric's
lower element; in Heat Pump mode, either) stops as it starts. With less
left, the elements finish the recovery first, a start pending or not.
With nothing heating, the heater's own triggers decide. An element
heating a tank below 50 degF runs to its off point before the heat pump
takes over, whatever the air does meanwhile. Answers that assume a
heat-pump recovery say ``heat_pump_unavailable``, as does one whose stop
(its target and run-on) is over 149 degF; ``next_recovery`` is
``unavailable``, and ``time_to_ready`` projects every mode as Electric,
Heat Pump mode from the heater's own trigger and the tank its coast
leaves there.
None of this is on the record, whose air ran 45.9 to 89.3 degF, so a
walk that uses it says ``envelope_fallback_unverified``.

**Power and efficiency.** The electricity is the map's, so a COP is the
map's heat over its electricity over the same climb; neither is scaled.
When a ``RecoveryModel`` serves a different duration, the climb's
electricity is stretched to the served climb at the same power, so a
recovery that takes longer uses more energy. :doc:`recovery-speed` has
the measurements.

**A learned duration.** A ``RecoveryModel`` (``sim.extensions``) may
replace the physics' duration with one learned from a heater's own
recoveries. It is asked with the physics' answer and the recovery's
context, and may decline, in which case the physics is served.


The elements
============

An element puts its power, 5,148 W, into its layer: the upper's at 0.72
of the volume from the bottom (17.5 gal of the 63.2 above it), the
lower's at 0.15. The upper's heat reaches the water 1.21 minutes after
it starts, and goes on as long after it stops. The heat rises from its
layer as the layers turn over, so the upper element heats the water
above it and the lower the whole tank. It runs to its off point (the
setpoint; Energy Saver's upper element stops 1.62 degF short, and its
heat still in transit lands after). Its heat is walked with whatever
else the tank is doing: a coast with its losses and draws, or a
recovery. When an element starts, and in which mode, is the
controller's (:doc:`heating-elements`).


Draws
=====

**Delivered gallons.** A draw is given in gallons on the delivered
line, after the mixing valve, because that is what a flow meter on the
hot line reads. The valve blends tank water with cold water to its
line, never above the tank, and the tank's share :math:`h` of a
delivered gallon follows:

.. math::

   T_{\text{del}} = \min\left(T_U,\; b + k\,T_U\right), \qquad
   h = \frac{T_{\text{del}} - T_{\text{in}}}{T_U - T_{\text{in}}}

with the valve's intercept :math:`b` and slope :math:`k`. With no valve
(``NO_VALVE``, :math:`b = 0`, :math:`k = 1`) every delivered gallon is
tank water.

**How a draw moves the tank.** Cold water enters at the bottom and
pushes the column up and out of the top as a plug: the tank water a
draw takes is the delivered gallons' tank share, solved gallon by
gallon from the water leaving the top. The inflow mixes into the
bottom ``inlet_mix_gal`` as it comes, so a short draw cools the bottom
layers without a sharp front. The probes then read the layers where
they sit: a draw shows on the lower probe first, and on the upper only
once the cold has risen to it, so a draw that empties the tank takes
the top down too. A draw split in two moves the tank as the whole draw
does, to about a degree at the probes. :doc:`draws` has the record's
draws.

**The fitted range.** The record's draws span a range of upper probe
temperatures and draw volumes (``DrawParams.domain_upper_f``,
``domain_volume_gal``). A walk with draws says ``draw_out_of_domain``
when its largest draw is outside those volumes, or the upper probe
leaves that range anywhere along the walk.


Circulation
===========

A recirculation loop's pump pulls tank water around the house and
returns it, cooled, to the tank. A run is priced as a flowing draw: its
gallons are the loop volume :math:`V_{\text{loop}}` it displaced,
scaled by how far the pipe had cooled in the :math:`t_{\text{rest}}`
since the last run, and its return comes back at the air plus a fitted
offset:

.. math::

   V_{\text{run}} = \min\left(\dot V\,t_{\text{run}},\;
   V_{\text{loop}}\right)\left(1 - e^{-t_{\text{rest}}/\tau_c}\right),
   \qquad T_{\text{return}} = T_a + \Delta T_{\text{rest}}

The pipe's cooled water returns at the bottom as a draw's cold water
does, pushing as much out of the top; the rest of the run's water comes
back as it left. Runs closer than 10 minutes count as one. The terms
and their fits are in :doc:`standby-loss`.


The tank now
============

Two probes can say how much hot water is left while the tank is full
or nearly so. Once the boundary between hot and cold water sits between
them, they can't: the upper probe reads hot until the cold reaches it,
and after a draw the bottom is the inlet's, which they read as no
different from a tank that coasted. The record before now can
(``sim.history``).

**The replay.** The last ``REPLAY`` (24 hours) of the heater's record is
put on a one-minute grid: both probes, the compressor's and the
elements' runs, the air, the metered draws (a flow over
``DrawParams.draw_gpm``, in delivered gallons through the valve) and the
circulation's runs. The tank starts as the profile the probes stand for
at the span's start and is walked through all of it on the layered
tank's own physics, corrected toward the probes every 10 minutes they
are read (``stratified.assimilate``), and the probes' last readings are
laid over the end. Those layers are the scenario's
``HeaterState.layers_f``. ``sim_adapters.layers_from_history`` and
``layers_from_changes`` read them from a record, and
``sim_home_assistant.HomeAssistantTank`` keeps them current from Home
Assistant. A meter silent for more than an hour in the span is refused,
as is a record with no flow reading at all, and the replay starts no
earlier than the flow's first reading. A span the heater went unheard
is walked across with its values held; across a span the meter was
unknown, the flow holds 60 seconds and then is none.

**Without a record** the simulation starts from the profile the two
probes stand for (``stratified.estimate``) and says so
(``tank_profile_estimated``).


Hot water at the tap
====================

**The line.** Water below ``line_f`` (105 degF by default) is not hot.
Every readiness answer is drawn at it.

**Deliverable gallons** (``delivery.deliverable``). The water leaving
the top in turn, each tank gallon delivering
:math:`1/f_{\text{hot}}` at the tap through the mixing valve, to the
first the valve delivers under the line; the inlet zone's water, which
warms toward the column as it rises, in closed form. The mains is the
scenario's inlet, else the parameters' mains on its first day
(``DrawParams.mains_on``: the climate's, else ``inlet_temp_f``). The
tank's outlet
is its top, above the upper probe: the tap stays hot for the water
above the probe after the probe has crossed (one measurement: 5.3 to
7.3 gal; the fitted probe has 6.9 gal above it).

**The delivery along a walk** is the top layer's water through the
valve, so the gallons and the delivery agree on when the tank runs
out.

**Ready for a bath.** ``time_to_ready`` compares the deliverable
gallons with the bath. If the tank is short, it walks the scenario in
each mode, the mode written at the start, for up to a day, and takes
the first instant the walk's layers deliver the bath; in the heat pump
that is from now if the compressor runs, else from the heater's own
trigger after a coast. An answer that a 1 degF error on either probe
would flip says so.


Fitting and checking the parameters
===================================

``sim_calibrate.calibrate`` fits a heater's parameters from its
recorded statuses; :doc:`/how-to/calibrate-simulator` shows how to run
it. The methods,
in the order they run:

**The frame.** One row per status, each holding until the next: the
probes, the running flags, the power, the energy count, the target, and
the heater's air reading. A silence longer than four times the usual
spacing (and at least 5 minutes) marks the span unobserved. The air
beside the heater and the humidity are added where given, and the
draws and circulation runs where both are.

**The tank's events.** Quiet windows: spans of 3 hours or more with
nothing heating and no water moving, starting 45 minutes after the last
of either, followed for up to 24 hours. A meter's sized draws, each
followed for an hour. And recoveries that reached their target, each
followed from its start. The tank's fit needs 10 windows and draws.

**The tank** (``sim.tank_fit``). Two probes do not say where the water
below the lower one is, so each event starts from the layers the record
before it leaves: the tank walked over the 24 hours before it through
the recorded heating, draws and circulation, corrected toward the
probes every 10 minutes, and the probes' own readings at the event laid
over it. The tank's terms (the sides', bottom's and top's losses, the
column's conductance, each probe's height and spread, the lower
probe's offset and the inlet's mixing) are then fitted together by
least squares with a soft L1 loss, so outlying readings weigh less, on
each probe's error every 10 minutes over every event, each event
weighing alike. With 5 recoveries or more, where the condenser heats is
fitted with them, on the recoveries too. A fit walks every event at
every trial, up to 300.

**The heat pump** (``sim.heat_pump_fit``). Each compressor run is put
on a one-minute grid and split into its hold, its climb and its
run-on, and four measures are read from it:

- **the heat**, on draw-free stretches of 20 minutes or more of a climb with the
  tank mixed (the probes within 5 degF below or 1 degF above each
  other), as the tank's mass times the mean's rise plus the tank's
  losses, at the terms just fitted. The heat's plane is a least-squares fit weighted by
  each stretch's minutes, with 10 stretches or more;
- **the power**, on 10-minute blocks of a climb's metered power,
  stratified or not, at the air and the lower probe: a least-squares
  plane with 30 blocks or more;
- **the hold**, on clean starts (no water moving from 30 minutes
  before them to the end of the hold): the minutes until the lower probe stays 5
  minutes above its reading from before the start. Each band's hold is
  the median of 3 starts or more in it, the base's otherwise;
- **the run-on**: the median of the lower probe's overshoot past the
  target at the stop of draw-free runs, with 5 runs or more.

The planes are applied only when together they claim nothing no heat
pump does (*The map*, above).

**The installation's terms.** The circulation's terms have fits of
their own (:doc:`/how-to/simulate-heater`).

**Held out, in time order.** With ``keep_better``, the tank's terms, the
heat's map, the power's map, the start's hold and the run-on are each
refitted on their earlier four fifths (the tank's quiet windows, draws
and recoveries together), and a refit
replaces the base's value only where it scores better on the latest
fifth; with fewer than 10 items the base is kept, and the tank's refit
still needs 10 windows and draws among the four fifths it is fitted on.
A group the base lists as unfitted takes its refit without that
comparison, fitted on all its data.

**Provenance.** Every parameter records whether it was ``measured`` on
the heater by a targeted run, ``fitted`` from its record, or an
engineering ``default``, and whether it describes the **heater** or the
**installation** (``params.provenance_of``, ``params.scope_of``). A term
the calibration could not fit is listed in ``HeaterParams.unfitted``,
and every answer that relies on it says so in its ``reasons``
(``physics_uncalibrated``, ``draw_uncalibrated`` and the rest).


How the sensors are used
========================

The heater's own readings are the only required input; everything else
improves an answer where it is given and has a stated default where it
is not.

.. only:: html

   .. mermaid::

      flowchart LR
          subgraph heater["The heater"]
              P["Tank probes"]
              F["Running flags, heat source"]
              A["Air reading"]
              W["Power, energy count"]
              S["Setpoint, thresholds, mode, TOU"]
          end
          subgraph site["The installation"]
              AS["Air sensor, humidity"]
              IN["Cold supply probe"]
              FM["Hot line flow meter"]
              CP["Circulation pump"]
              OF["Outdoor forecast"]
          end
          P --> SC["Scenario"]
          F --> SC
          S --> SC
          A --> SC
          AS --> SC
          OF --> SC
          CP --> SC
          FM --> SC
          IN --> SC
          P --> LY["The tank's layers"]
          F --> LY
          A --> LY
          FM --> LY
          CP --> LY
          LY --> SC
          P --> CAL["Calibration"]
          F --> CAL
          A --> CAL
          W --> CAL
          AS --> CAL
          FM --> CAL
          CP --> CAL

The heater's readings
---------------------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Reading
     - How the simulator uses it
   * - The upper and lower tank probes
     - The tank's state at the start (laid over the replayed layers),
       what the replay is corrected toward, and what every fit is
       scored against. Required.
   * - The compressor's running flag
     - Whether a recovery is in progress; its last stop starts the
       restart lockout and dates the last heating. In a record it
       defines the recovery runs and decides which air reading a
       sample is (below). In a change history without it, the heat
       source stands in; from statuses an unknown flag counts as
       stopped.
   * - The elements' running flags and the heat source
     - Whether an element is running and since when. A recovery with an
       element in it, or in the 10 minutes before it, is left out of the
       heat pump's fit.
   * - The heater's air reading
     - While the compressor runs, the air drawn over the coil. The
       replay and the Home Assistant air fit use it from 5 minutes into a
       run, once it has settled; the heat pump's fit reads it minute by
       minute. From August to October it read within about 0.35 degF
       of a sensor beside the heater, up to about 2 degF warm from May
       to July. While it is idle, the
       cabinet's own warmth: about 6 degF warm, so 6.2 degF
       (``IDLE_CABINET_WARM_F``) is taken off and the answer says
       ``ambient_from_idle_cabinet``. With the compressor's state
       unknown, it is not corrected. Without an air sensor, the tank's
       fit uses the idle reading corrected the same way, and the
       recoveries the running one.
   * - The heater's power reading
     - The metered power through each compressor run, which the power's
       map is fitted on.
   * - The energy-to-setpoint count
     - In a record, a recovery whose count is still above 500 Wh at its
       end was cut short and is left out. In ``forecast``, a zero count
       means no heating is needed, but only while no TOU window has
       raised the upper start threshold.
   * - The setpoint and the thresholds
     - The setpoint, ``hp_lower_on`` (the lower probe's start; without it
       that start is never searched, ``hp_lower_on_unknown``),
       ``hp_lower_off`` (the recovery's target; without it, the
       setpoint), and ``hp_upper_on``, whose rise marks a TOU window in
       force.
   * - The mode, TOU switch and status flags
     - The mode in force and the TOU switch. A hybrid operating mode,
       an anti-legionella cycle or an error code keeps a recovery out of
       the heat pump's fit. The "hot water in use" flag is the quiet test
       where no meter is given; it also fires on circulation.

Readings the simulator does not use: the inlet temperature field (it
reads 0, so the inlet is an input), the flow rate fields (the
cumulative one reads 0 after a year in service), the discharge and
suction temperatures, the evaporator coil's reading, the fan speed, the
expansion valve, the outdoor
temperature field and the recirculation fields
(:doc:`unknown-values`).

An installation's sensors
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Sensor
     - How the simulator uses it
   * - Air beside the heater
     - The ambient for the tank's losses and the recoveries, and the
       circulation return's rest temperature. In a fit from Home
       Assistant, its readings count only over the span they cover. Without it: the heater's
       own reading as above, or 65 degF with ``ambient_defaulted``.
   * - Humidity of that air
     - Passed to a ``RecoveryModel``; the map does not use it, since on
       the record it moved a recovery's heat by no more than the
       probes resolve. Without it: 50 %, named in ``defaults_used``.
   * - A probe on the cold supply
     - The mains a draw meets and the deliverable gallons are drawn
       against. It is never a raw reading, since at rest the pipe
       tracks the air: it is the median plateau of long draws
       (11 minutes or more, circulation off) that ended in the last
       72 hours, each draw's plateau the median of its last 2 minutes,
       none earlier than minute 9. Without the probe: the parameters'
       mains on the day (their climate's, else ``inlet_temp_f``: the
       rating test's 58 degF in ``default_params``) with
       ``inlet_temp_modelled``.
   * - A flow meter on the hot line
     - The draws, in delivered gallons (or tank gallons, with
       ``flow_volume="tank"``), which move the tank in the replay and
       the fits. From statuses a reading holds 60 seconds and then
       counts as no flow; from a change history it holds until the next
       change. Without one there is no replay, so the tank starts from
       the probes (``tank_profile_estimated``), and in a fit the
       heater's "in use" flag stands in for the quiet test.
   * - The circulation pump
     - Its runs, from its speed (10 rpm or more is running), priced as
       above. Without them, an installation that circulates says
       ``circulation_unknown``.
   * - An outdoor forecast
     - The air ahead of time,
       :math:`T_a(t) = d\,T_{\text{out}}(t - \lambda) + c`, fitted
       from the air beside the heater (without that sensor, the
       heater's running readings) against the outdoor history. It is
       shifted to pass through a fresh reading beside the heater, or
       failing that the heater's own reading from the last hour while
       its compressor ran; with neither it stays unanchored.
       Not used in calibration: unanchored, it ran about 6 degF cold.

Where a sensor's record has a gap, the value before it holds across a
short silence (a Home Assistant restart, say); a span nobody heard is
left out of the fits, and the air across an air sensor's outage is
65 degF in the replay.
