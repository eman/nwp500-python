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
target. The nearest of these is the next event. A coast walks ahead
2 hours, then each time twice as far, to a 10-minute mark of the
clock, and stops walking once the heater's own start is triggered: each of its rules finds its
instant from the tank up to it, so the start is the one a walk to the
next event finds, and a simulation's cost grows with its span, not its
square. The tank split at such a mark is the tank walked whole.

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
the draw's own instant, or the instant of the piece of a draw over time
(``Draw.pieces``) that does.

**A running recovery is the tank walked with the compressor on.** From
its start the tank is walked with the condenser heating it, through
whatever draws, writes and element events come, until the lower probe
reaches the stop. Nothing is predicted ahead and put back: after a
draw or a pause the walk goes on from the tank as it stands.

**Details the firmware imposes.** Setpoints are rounded to the device's
0.5 degC. A reservation entry fires at the start of its minute. A start
inside the restart lockout waits until the lockout ends. At the horizon,
whatever runs is cut, with the stop reason ``horizon``.

**Going on from a walk.** A result ends with the heater as it stands:
``end_state`` (the probes, the layers, what runs, and ``resume``, the
controller's state), ``end_history`` and ``end_settings``. A scenario
given them walks on from there, with the compressor's hold, lockout
and pending start, an element's dead time and the running intervals
carried on, as if the two were one walk with a mark at the cut. A mark
is exact on the clock's 10-minute grid, where an idle walk steps; a
cut between grid points splits a step and moves the tank by
thousandths of a degree. A setpoint or mode other than the one the
last walk left is a write at the start. Each draw meets its own
day's mains, so a walk going on past midnight meets the next day's as
one walk does. A change into or out of
Vacation or Power Off is a write the simulation holds no rule for: that
walk starts afresh from the tank and the history, and says so.


The tank
========

**State.** The tank is a column of layers of equal volume, 12 by
default (``TankParams.layers``), the bottom first, each mixed within
itself: HPWHsim's stratified tank (``physics.stratified``). Each of the
:math:`n` layers holds :math:`V/n` of the storage volume :math:`V`
(63.2 gal for the 65 gal model), and a gallon's heat per degree falls
as it warms (``physics.water``):

.. math::

   c(T) = 8.34 \text{ BTU/gal degF at 58 degF},\quad 8.20 \text{ at 140 degF}

from water's density (1.6 % lighter at 140 degF) and its heat
capacity, fitted as a quartic to 0.002 BTU/gal degF over 32 to
212 degF. The whole tank holds 527 BTU/degF cold and 518 at 140 degF.
The layers' heat is kept as each one's :math:`h(T)`, the temperature
water of a constant 8.34 would have with the same heat, in which mixing,
flows and heat put in are linear: every operator below conserves the
layers' energy to rounding. Where a temperature drives the heat, the
air, a neighbour, the condenser's water, the operator reads it, and
books the heat it moves in :math:`h`.

**The layer count is part of the fitted model.** The tank's fitted
terms (the probes' heights, spreads and offset, the condenser's span,
the inlet zone, the column's conductance and the losses) are fitted at
12 layers and absorb what 12 layers do. ``TankParams.layers`` is not a
resolution to turn up: with the terms held, other counts move the
answers, and not steadily. On the 65's defaults (no mixing valve), with
the air held at 65 degF: a mixed 130 degF tank gives a 40 gal draw at
once, the mains at 58 degF, and from the draw's end the compressor
alone runs until the lower probe reads 130.9 degF, or the upper
element alone, 5,148 W, until the upper probe reads 130 degF; the
gallons are those the drawn tank then delivers over 105 degF
(``stratified.draw``, ``walk``, ``deliverable_gal``):

.. list-table::
   :header-rows: 1
   :widths: 16 21 21 21 21

   * - Layers
     - Heat-pump recovery to the lower probe at 130.9 degF
     - Upper element to the upper probe at 130 degF
     - Gallons delivered over 105 degF
     - Upper probe after the draw
   * - 6
     - 262.0 min
     - 9.2 min
     - 15.8
     - 122.02 degF
   * - 10
     - 276.1
     - 7.0
     - 15.8
     - 123.30
   * - 11
     - 281.0
     - 11.2
     - 15.8
     - 123.56
   * - 12
     - 264.4
     - 9.1
     - 15.8
     - 123.73
   * - 13
     - 252.9
     - 7.4
     - 14.6
     - 123.83
   * - 24
     - 264.4
     - 6.5
     - 15.1
     - 124.21
   * - 96
     - 262.2
     - 6.1
     - 15.0
     - 124.39

A day's standby from 130 degF is the same at every count, to 0.15
degF. The
recovery's swings are the condenser's: what it heats turns over into
the layers above a whole layer at a time, so when the lower probe
reaches its stop depends on where the layers' edges fall. The
element's are its own: it heats its layer whole (below).

Moving to 24 layers and refitting was tried (2026-10-30) and dropped.
Fitted before 2026-09-18 and scored after (``sim_score``, as in
:doc:`/how-to/calibrate-simulator`), both from the defaults'
installation, without ``site_example_params``'s mixing valve,
circulation and mains that :doc:`simulator`'s accuracy is measured
with (with no circulation terms the replay that starts each event
leaves out the record's pump runs), it read recoveries 38.2 min
off against 37.7 at 12, their energy 12.9 % against 12.4, the draws'
lower probe 3.00 degF RMS against 3.03: no difference outside the
scores' intervals. Refitted on the whole record, its upper probe
climbs under the upper element 1.70 degF/min against 1.58 at 12 and
the record's 2.01: the fit widens the upper probe's spread (5.6 to 6.5
gal), and the probe feels the water under the heated layers. A walk
takes 1.55 times as long. The fit also moved the bottom's loss and the
inlet zone, which the record barely tells apart (0.006 BTU/hr per degF
and 10.5 gal at 12 layers, 0.57 and 5.25 at 24): a refit at another
count lands on another point of that ridge, not a better one. The
element's shortfall is how it heats, a whole layer, not how many
layers there are; a change that would close it is one that heats the
volume over its height at any count. :doc:`simulator-tried` keeps this
and the simulator's other changes tried and dropped.

**The probes.** The probes read the layers; they are not the state.
Each reads the layers around its height (a share of the volume from
the bottom), weighted by :math:`e^{-d/s}` with the distance :math:`d`
along the column and its spread :math:`s`, and the lower one reads a
fixed offset above them. A walk that starts from the two probes alone
builds a profile they read back exactly (``estimate``) and says
``tank_profile_estimated``. While the compressor heats, the real
probes also read higher than at rest, after 40 minutes or more of
heating about 0.5 degF the upper and 0.9 the lower
(:doc:`recovery-speed`); the model's probes do not.

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
interpolated onto a 10-minute grid. Coast and recovery alike read it
at each step's start: a recovery's heat, power and losses follow the
air through its span. The air's mean is used only to judge where the
heat pump heats against its map (``heat_map_out_of_domain``, below)
and as context for a learned duration (``t_amb_mean``).

The air is an input, not a state: the heat pump takes about 3,000
BTU/hr from its room while it runs, and the simulator does not cool
the room for it. At one installation that cooling was 0.49 degF on
average over a run (0.04-0.95, :doc:`recovery-speed`), 27 BTU/hr of the
heat at the map's air slope, about a ninth of the map's own error
(236 BTU/hr RMS). A replay reads a sensor's air, the cooling in it. A
forecast's air is shifted through a fresh reading beside the heater,
else the heater's own from the last hour while its compressor ran, else
left unanchored (the inputs, below); it carries the cooling only as its
anchor did, and otherwise leaves it out: at this installation 0.49
degF on average, 0.95 at the top of the measurement's range; other
rooms may differ. A room of its own
would need its capacity and its loss to outdoors, which no heater's
record measures.


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

The power is fitted where it is read, at :math:`T_c`: each metered
block at the condenser's water on the record's replay
(``heat_pump_fit.in_condenser_water``), which is below the lower probe,
by the probe's fixed offset in a mixed tank and by more while the tank
is stratified (4.8 degF on average over the record's climbs). Fitted on
the lower probe's reading and read at :math:`T_c`, it priced the
record's climbs at 406.9 W against the 418.2 W metered.

Each is read along its plane over the envelope the heat pump runs in
(the controller's 41 to 113 degF air and 50 to 149 degF water, the
region a fit is checked over, below), past the span it was fitted over (the heat's 61 to 89 degF air and 114 to 144 degF
water, the power's 53 to 90 degF air and 65 to 144 degF water, on the
record) as within it. The heat is fitted on a mixed tank, where the
tank's mean and the condenser's water are within a few degrees; while
the tank is stratified the condenser's water is below the heat's span,
and the heat there is the plane's. Held at the span's edges instead, a
45 degF air would heat as 61 degF does, and the heat and the power,
held at different water, would give a COP that bends where neither was
measured. The controller judges the water at the lower probe, and a
cold bottom can leave the condenser's below the envelope while the
compressor runs; there the maps are read at the envelope's edge
(``stratified.Layout.map_air_f``, ``map_water_f``), so no read falls
where no fit was checked. A recovery whose air is outside the heat's
span says so (``heat_map_out_of_domain``), and so does one whose
probes' mean over its heating, over the whole run, is outside the
heat's water span: the
heat was fitted on mixed climbs against that mean, each climb's
average, 114 to 144 °F on the site's record, so a cold tank's recovery,
or one to a low setpoint (from the heater's 104.9 °F trigger, 117 °F
and under at 67.5 °F air), reads the plane past its evidence. The map
is read at the condenser's water, which in a layered tank runs under
that mean (from that trigger to a 130 °F setpoint it starts at 102.1
°F and averages 114.3 °F over the run, the probes' mean 121.9 °F): it
is not what is judged.

A fit's slopes take the sign the cycle gives them: warmer air boils the
refrigerant warmer and denser, so the heat rises with :math:`T_a`
(:math:`q_a \ge 0`); warmer water condenses it hotter, so the heat
falls and the compressor's work rises with :math:`T_c` (:math:`q_w \le
0`, :math:`p_w \ge 0`). The power in the air is left free: a
compressor's work rises or falls with the denser gas by how far it
lifts it. The plane is the least-squares one so constrained: of the
planes with each slope free or pinned at 0, the best that keeps every
sign (``heat_pump_fit.HEAT_SLOPE_SIGNS``, ``POWER_SLOPE_SIGNS``).

The COP is :math:`\dot Q_h / 3.412 P`, and the heat taken from the air
is :math:`\dot Q_h - 3.412 P`: what the condenser gives is what the
evaporator takes plus the electricity, by construction. A fitted map
must claim nowhere the heat pump runs (the controller's 41 to 113 degF
air and 50 to 149 degF water) a COP above 0.6 of Carnot's between the
evaporator's coil and the water, heat given to the air, or under 50 W;
one that does is not applied. The coil is taken 20.5 degF under the
air, as close as it ran in 90 % of the record's steady running minutes
(``heat_pump.EVAPORATOR_APPROACH_F``; median 24.5 degF), and the
refrigerant condenses no colder than the water, so no cycle between
them does better (``heat_pump.refrigerant_carnot_cop``). Against the
coil as read, the site's map runs a steady 0.43 of that ideal from 60
to 100 degF air and never over 0.46; carried over the whole envelope it
reaches 0.45. Each plane is checked with the one it would be applied
with.

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

**The start's stir.** After a start the compressor runs some minutes
before the lower probe climbs, longer the longer it was off (0 to 22
minutes on the record, :doc:`recovery-speed`), while the upper probe
holds still: the heat is going into water below the lower probe. The
condenser does not wrap the tank's bottom, so the water under it is
left cold by a recovery and cools on through a stand, and the layers
carry that cold. At the instant the condenser's heating begins the walk
pools the water the condenser wraps with the water below it
(``stratified.stir``: each layer by its share under the condenser's
top, ``Layout.stir_weights``), the same heat spread over the pool, and
the climb follows from there. A compressor already running when a walk
starts has had its stir, so it is not stirred again unless some of a
caller's hold is left, and one stopped before its heating begins stirs
nothing. The lower probe, above the pool, holds
until the condenser has heated the pool past its reading, and the
upper probe holds as the record's does. The hold is nothing of its
own, so a stand's cold costs the heat it does and no more: a 22-minute
hold at the map's power with no heat credited was 165 Wh and 3 degF of
tank a start. ``CompressorParams.start_hold_min`` imposes no hold by
default; a caller may still pass ``start_hold`` by time off, or
``running_hold`` for a compressor already running.

**The run-on.** The heat pump does not stop the moment the lower probe
reaches its target: on the record it stops a median 0.9 degF past it
(``ControllerParams.hp_stop_overshoot_f``). The climb is integrated to
the target plus that overshoot. The overshoot is the probe's reading,
which runs high while the compressor heats, and the model's probe
carries nothing for the heating, so a long recovery's water ends
warmer than the real one's and the recovery runs about 4 minutes
longer for it (:doc:`simulator`). The TOU window's cap on the lower probe
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
context (the air at its start and its mean over the physics' span among
it), and may decline, in which case the physics is served.


The elements
============

An element puts its power, 5,148 W, into its layer: the upper's at 0.72
of the volume from the bottom (17.7 gal of the 63.2 above it), the
lower's at 0.15. The upper's heat reaches the water 1.21 minutes after
it starts, and goes on as long after it stops. The heat rises from its
layer as the layers turn over, so the upper element heats the water
above it and the lower the whole tank. The height therefore acts in
whole layers: the upper's layer and those above it hold 21.1 gal, so
its heat climbs the upper probe 1.59 degF/min, where the record's clean
runs climb it 2.01 (the next layer up, 15.8 gal, gives 2.00). More
layers do not close it (the layer count, above). The
record's element runs mostly come with water drawn or the compressor
running, and replayed they read the upper probe closer from the lower
layer (7.9 degF RMS on 24 runs against 10.2), so that one is kept.
It runs to its off point (the setpoint; Energy Saver's upper element
stops 1.62 degF short, and its heat still in transit lands after). Its
heat is walked with whatever else the tank is doing: a coast with its
losses and draws, or a recovery. When an element starts, and in which
mode, is the controller's (:doc:`heating-elements`).


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
layers without a sharp front. The zone is the same at every flow: the
record's quiet draws (``sim_score``'s draw events) of 4 gal or more all
ran at 0.7-1.3 gal/min, too narrow a span to fit a flow term on
(:doc:`simulator-tried`). The probes then read the layers where
they sit: a draw shows on the lower probe first, and on the upper only
once the cold has risen to it, so a draw that empties the tank takes
the top down too. A draw split in two moves the tank as the whole draw
does, to about a degree at the probes. :doc:`draws` has the record's
draws.

**A fast draw.** A draw at ``DrawParams.undiluted_gpm`` or faster, its
gallons over its ``Draw.duration_s``, takes as much of the tank's water
as it delivers, as with no valve; one at an instant has no flow to
judge and goes through the valve. On the site's record (2026-04-16 to
10-26, measured 2026-10-31) the draw detector timed 24 draws of 20 gal
or more. Twenty ran at 0.8-1.7 gal/min. Replayed from the record's
state just before each, the walk through the valve put the upper probe
within a few degF of the record's on 21 of them. Four ran at 2.1-2.7
gal/min (05-04, 09-29, 09-30, 10-02). On the three of 30 gal or more
the record's upper probe fell 45-55 degF and the walk's 24-30, and on
05-04 the record's lower probe reached 81.7 degF against the walk's
112.6. These draws took about 1.3 times the tank water the valve's
share gives, as with no valve. The probes' fall says so, and so does
the recovery after: on 09-29 and 10-02 the walk through the valve
finished 66 and 51 min before the record did, and at 1.3 times 36 min
before and 14 min after. A larger inlet zone does not reproduce it
(:doc:`simulator-tried`): mixing keeps the heat, and the record's tank
lost more. Whether the valve passes more at that flow or the meter
reads less, the record does not say. ``site_example_params`` sets 2.0
gal/min (``SITE_UNDILUTED_GPM``); the default, None, takes every draw
through the valve. The tank's fit takes its draws at their onsets
through the valve, as before. A forecast's expected draw carries its
per-draw time (``sim.draw_forecast``), so its flow is judged too.

**A slower draw.** Through the valve, a delivered gallon takes the
valve's share :math:`s` of the tank's water and the rest from the
mains. A slower draw takes :math:`s + k\,(1 - s)`, ``k`` the share of
that cold side the tank gives as well (``DrawParams.undiluted_share``,
0 to 1, 0 by default). On the site's record the lower probe fell
further after a draw than the valve's share lets it. Measured on
2026-11-01 over the draws of 8 gal or more with the compressor off for
the hour after, each walked from the record's state at its onset on
the parameters fitted before 2026-09-18: on the 137 before then, the
record's probe fell a mean 13.7 degF and the walk's 10.8, less on 97.
With :math:`k` of 0.25 the walk's fell 12.6, within 7.13 degF RMS of
the record's against 7.40 (0.2 within 7.13 and 0.3 within 7.14; its
mean fall reaches the record's near 0.4, at 7.27), and with 1, all of
the tank's water, 18.1, 9.62 RMS. On the 32 held out after it, 10.7
degF against the record's 14.9 at 0, 12.1 at 0.25, RMS 6.25 to 5.19.
``site_example_params`` sets 0.25 (``SITE_UNDILUTED_SHARE``). The same
share is taken where a gallon delivered is reckoned from the tank's:
the deliverable gallons (``sim.delivery``) and a history's metered tank
gallons (``history.drawn_gal``). Whether the meter reads less at the
slower flows, the valve passes more than its line or the cold reaches
further up, the record does not say: the valve's line is the tap's
measured temperature and is kept.

**The fitted range.** The record's draws span a range of upper probe
temperatures and draw volumes (``DrawParams.domain_upper_f``,
``domain_volume_gal``). A walk with draws says ``draw_out_of_domain``
when its largest draw is outside those volumes, or the upper probe
leaves that range anywhere along the walk.


Circulation
===========

A recirculation loop's pump pulls tank water around the house and
returns it to the bottom of the tank. A run first brings back the water
that rested in the pipe: the share of the pipe's volume
:math:`V_{\text{pipe}}` that had cooled in the :math:`t_{\text{rest}}` since
the last run, at the return's rest, the air plus an offset. After that
the tank's own water comes back, cooled on its way round by the pipe's
loss :math:`UA_{\text{pipe}}` at the run's flow :math:`\dot m`:

.. math::

   V_{\text{cooled}} = \min\left(\dot V\,t_{\text{run}},\;
   V_{\text{pipe}}\left(1 - e^{-t_{\text{rest}}/\tau_c}\right)\right),
   \qquad T_{\text{rest}} = T_a + \Delta T_{\text{rest}},

   T_{\text{steady}} = T_{\text{rest}} + \left(T_{\text{top}} -
   T_{\text{rest}}\right) e^{-UA_{\text{pipe}}/(\dot m c)}

Water colder than the tank's inlet zone comes in there and pushes the
column up, as a draw's cold water does. Water warmer than it, the run's
own once the pipe's cold has come back, rises past the zone to where
the tank is as warm and pushes out only what is above that. Runs closer
than 10 minutes count as one. The terms and how they were measured are
in :doc:`standby-loss`.


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
scenario's inlet, else the parameters' mains on the day it is read
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
followed from its start through the recorded run to its recorded end.
(The score walks a recovery instead to where its run stops, a change
of the setpoint inside it a write at its instant; a restart a write
causes before the recorded end continues the run.) The tank's fit needs
10 windows and draws.

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
  stratified or not, at the air and the condenser's water on the
  record's replay through the terms just fitted (the lower probe's,
  with no record to replay): a least-squares plane with 30 blocks or
  more;
- **the run-on**: the median of the lower probe's overshoot past the
  target at the stop of draw-free runs, with 5 runs or more.

The planes are applied only when together they claim nothing no heat
pump does (*The map*, above).

**The installation's terms.** The circulation's terms have fits of
their own (:doc:`/how-to/simulate-heater`).

**Held out, in time order.** With ``keep_better``, the tank's terms, the
heat's map, the power's map and the run-on are each
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
