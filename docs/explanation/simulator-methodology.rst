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

- **Two probes, two zones.** The heater reports two thermistors, one
  high in the tank and one low. The model's tank is two zones that
  those probes read, not a finer grid the probes can't check.
- **Events, not time steps.** Nothing the firmware decides happens
  between events, so the walk jumps from one event to the next and lets
  the physics carry the tank across each span.
- **Fitted against the record, scored on later records.** The
  compressor and heat book fits hold out the latest part of a record and
  are scored on it, in time order, so a term that only fits its own data
  shows; with ``keep_better`` the other main terms are scored the same
  way.
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
the lower zone falling to the heater's start threshold, the upper zone
falling to where an element mode starts again, a recovery reaching its
target. The nearest of these is the next event.

**Between events.** The walk moves the tank to that instant with the
physics: a coast when nothing heats, a recovery when the compressor
runs, with an element's heat laid over either. Then it hands the event
to the controller.

**The controller.** ``sim.controller`` is the firmware as a pure
function: ``transition(state, event, settings, params)`` returns the
heater's new state and the actions it takes (start the compressor, stop
an element, set a mode). It reads the tank only through the event it is
given and through predicted paths, and keeps no state of its own. Its
rules and the evidence for each are in :doc:`what-starts-a-recovery`,
:doc:`tou-recovery-cap` and :doc:`heating-elements`.

**Finding a crossing.** Paths are kept as points: every 10 minutes on a
coast, and on a 10-minute grid for a recovery. A crossing of a threshold
is placed by linear interpolation between the two points around it. A
draw that takes the lower zone past the threshold places the crossing at
the draw's own instant.

**A running recovery is predicted once.** When a draw, a pause or a
write interrupts a recovery, the tank is put back on the same predicted
path where the path's lower zone matches the tank's. The recovery is
predicted again only when the tank is colder than where it started, or
the heat book moved the upper zone.

**Details the firmware imposes.** Setpoints are rounded to the device's
0.5 degC. A reservation entry fires at the start of its minute. A start
inside the restart lockout waits until the lockout ends. At the horizon,
whatever runs is cut, with the stop reason ``horizon``.


The tank
========

**State.** The tank is two zones of equal mass: the upper, which the
upper probe reads, and the lower, which the lower probe reads. The walk
carries them as a mean temperature and a gap: upper = mean + gap / 2,
lower = mean - gap / 2. The tank's thermal mass is its storage volume
(63.2 gal for the 65 gal model) times 8.34 BTU per gallon per degF,
about 527 BTU/degF.

**Standby.** Heat leaves through the jacket to the air beside the
heater at ``UA(dT) x dT``, where dT is the tank's mean over the air.
``UA`` follows ``ua_ref x (max(dT, 5) / 50) ^ n``; at the current fit
``n`` is 0, so ``UA`` is a constant. A coast is stepped every 10 minutes
(explicit Euler on the mean), with ``UA`` evaluated at each step.

**The bottom loss.** A second loss, ``Q_b``, leaves the lower zone
alone. The lower probe sees ``1 - exp(-gap / gate)`` of it: nearly all
of it in a stratified tank, little in a mixed one. So a stratified
tank's lower zone falls faster than its upper and the gap opens, as the
record shows. :doc:`standby-loss` has the fits.

**The gap relaxes.** With nothing heating or drawing, the gap closes as
``gap(t) = gap_0 x exp(-t / tau)``, in closed form. A draw, the bottom
loss or a circulation run resets ``gap_0`` to the gap it leaves, and
the relaxation starts again from there.

**The air.** The ambient is given as readings (or one value) and
interpolated onto a 10-minute grid. A coast reads it at each step; a
recovery uses its mean over the recovery's span (below).


A heat-pump recovery
====================

**The cycle.** The heat pump is modelled as an R-134a vapour
compression cycle, integrated on the lower zone in 10-second steps:

1. The evaporator sits below the intake air by a measured approach,
   moving 0.6 degF per degF of air (the coil's own reading on the
   record).
2. The refrigerant's saturation pressure, vapour density and
   enthalpies at the evaporator and the condenser come from a table of
   CoolProp's equation of state, every 5 degF.
3. The condenser sits a fixed approach above the lower zone.
4. The compressor moves ``compressor_constant`` cubic feet of vapour a
   second, less what the clearance volume costs at the pressure ratio;
   that times the vapour's density is the refrigerant's mass flow.
5. Polytropic compression gives the work per pound; the heat into the
   tank is the mass flow times the enthalpy the condenser rejects, plus
   the latent heat of the humid air's water condensing on the coil when
   the coil is below the air's dew point.
6. The standby loss and the bottom loss are taken off, and the lower
   zone rises by the net heat over the zone's mass.

It stops when the lower zone reaches the target (``hp_lower_off``), or
after 30 hours, reported as truncated. ``compressor_constant`` is the
one term fitted on durations. The evaporator's approach and slope are
the coil's own reading; the condenser approach, the clearance, the
exponent and the fan's airflow are engineering values the record cannot
separate from it (:doc:`/reference/simulator-inputs`).

**Two zones in a recovery.** The condenser coil wraps the lower part of
the tank. While there is a gap, the heat goes into the lower zone's
mass and the upper zone holds; once the gap closes, the tank heats as
one body.

**The air over the recovery.** A recovery's duration depends on the air
it runs in, and the air depends on how long it runs. The walk
integrates the recovery at the air at its start, then once more at the
mean air over the first answer's span, and keeps the second.
``forecast`` repeats this up to three more times, stopping once the
duration moves 2 minutes or less.

**The start's hold.** After a start the compressor runs some minutes
before the lower zone climbs. A caller with a ``RecoveryModel`` can pass
``start_hold``, that hold by how long the compressor was off: the model
is asked with it, serves a duration that includes it, and the path
stays flat for it. With the physics alone there is no hold, since the
fitted durations already include it.

**Power and efficiency.** The cycle's own compression work, times a
fitted ``power_scale``, is the electricity. The efficiency is fitted
apart from it: the heat stored (the tank's mass times the rise of its
mean, net of the standby loss) over the cycle's own unscaled work,
times a fitted ``cop_scale`` and an exponential lift term. Start-up energy is recorded once per start.
:doc:`recovery-speed` has the measurements.

**A learned duration.** A ``RecoveryModel`` (``sim.extensions``) may
replace the physics' duration with one learned from a heater's own
recoveries. It is asked with the physics' answer and the recovery's
context, and may decline, in which case the physics is served.


The elements
============

An element heats its zone at a constant rate: the upper at 2.01 degF a
minute after a 1.21 minute dead time, the lower at 1.38 degF a minute,
at 5,148 W. It runs to its off point (the setpoint; Energy Saver's
upper element stops 1.62 degF short, and its zone coasts on with the
heat in transit). Its heat is laid over whatever the tank is doing: a
coast with its losses and draws, or a recovery's path, where the upper
zone takes the higher of the two. When an element starts, and in which
mode, is the controller's (:doc:`heating-elements`).


Draws
=====

**Delivered gallons.** A draw is given in gallons on the delivered
line, after the mixing valve, because that is what a flow meter on the
hot line reads. The valve blends tank water with cold water to its
line, ``delivered = intercept + slope x upper``, never above the tank.
The tank's share of a delivered gallon is ``(delivered - inlet) /
(upper - inlet)``. With no valve (``NO_VALVE``) every delivered gallon
is tank water.

**How a draw moves the probes.** Cold water enters at the bottom, so a
draw moves the lower zone first and most. Per delivered gallon, the
lower zone falls toward the incoming water at a rate set by how much of
the draw reaches the probe: ``reach = 1 - exp(-(gap + offset) /
gate)``. A mixed tank (small gap) hides much of a small draw from the
lower probe; a stratified one shows it. The upper zone falls a fixed
small amount per gallon. A draw is walked a quarter gallon at a time,
so a draw split in two moves the tank as the whole draw does.
:doc:`draws` has the fit and its held-out scores.

**Observability.** The share of a draw's heat that the two probes' mean
registers (``observability``, 0.633 at the site) prices draws in the
same frame as the standby fit. It is a pricing term; the probes'
response above does not use it.

**The fitted range.** The draw terms were fitted over a range of upper
zone temperatures and draw volumes. A walk with draws says
``draw_out_of_domain`` when its largest draw is outside the fitted
volumes, or the upper zone leaves the fitted range anywhere along the
walk.


Circulation
===========

A recirculation loop's pump pulls tank water around the house and
returns it, cooled, to the tank. A run is priced as a flowing draw: its
gallons are the loop volume it displaced, scaled by how far the pipe
had cooled since the last run (``1 - exp(-rest / tau)``), and its
return comes back at the air plus a fitted offset. Only the lower zone
moves on a gated run; an ungated one charges a share of its heat to
both zones. Runs closer than 10 minutes count as one. The terms and
their fits are in :doc:`standby-loss`.


The heat book
=============

Two probes can say how much hot water is left while the tank is full
or nearly so. Once the boundary between hot and cold water sits between
them, they can't: the upper probe reads hot until the cold reaches it.
The heat book (``sim.book``) answers by bookkeeping instead.

**What it books.** Heat above 70 degF, starting from a moment the tank
is known full. From there it debits each draw (by delivered gallons
through the valve, or tank gallons at the upper zone), standby loss and
circulation, and credits the compressor's heat (a fitted rate that
rises with the air) and the elements'. Credited heat is drawable
wherever it lands.

**Anchors.** A book starts, and restarts, only where the tank is known
full: both probes within ``uniform_band_f`` at the end of a recovery
with nothing drawn or circulated since, or with the compressor running
alone, nothing drawn or circulating at that step, once it has run
``anchor_run_min`` since the last draw. A quiet tank after a draw is
not an anchor: the lower probe shows only part of a small draw in a
mixed tank, and an anchor there would credit the draw back. The book's
error is flat for ``max_anchor_age_h`` (18 h) after its anchor and
larger beyond, so an older anchor is marked aged and carries a wider
band.

**Reading a record.** ``book_from_history`` and ``book_from_changes``
put the recorded statuses, the meter and the air on a 10-second grid
and walk the book from the last anchor. From statuses, a meter reading
holds 60 seconds and an inlet reading an hour, and a meter silent for
more than an hour is refused; from changes, each value holds until the
next. A span the heater went unheard is walked across with its values
held; across a span the meter was unknown, the flow holds 60 seconds
and then is none.

**How much is left.** The empty point (``empty_btu``) is the booked
heat left when the upper probe crossed the line in recorded drawdowns.
Deliverable gallons are the heat above it over the heat a delivered
gallon takes. Along a walk the book also moves the upper zone the probe
would show as the tank empties, and re-anchors where the walk's tank
is full: at the end of a recovery the heater stopped itself, quiet
after one with the zones within the band, or with the compressor
running alone past the hold.

**From outside.** Any ``HeatLedger`` (``sim.extensions``) can stand in
for the book.


Hot water at the tap
====================

**The line.** Water below ``line_f`` (105 degF by default) is not hot.
Every readiness answer is drawn at it.

**The lag.** The probe is not at the tap. When the upper probe crosses
the line, the water above it still leaves hot, so the tap runs cold
``delivered_lag_gal`` gallons later (measured once, 5.3 to 7.3 gal;
5.0 used).

**Deliverable gallons.** With a book: the booked heat above the empty
point, plus the lag. Without one: the tank's heat as the two probes
place it, or the most that recorded draws delivered from probes no
warmer than now (``evidence``), whichever is more, plus the lag; with
the upper probe already below the line, none.

**Ready for a bath.** ``time_to_ready`` compares the deliverable
gallons with the bath. If the tank is short, it finds the first minute
the bath is covered along the heat pump's next recovery (from now if
the compressor runs, else from the heater's own trigger after a coast
on the standby model), and in each element mode as if written now. An
answer within the book's error band, or one that a 1 degF probe error
would flip, says so.


Fitting and checking the parameters
===================================

``sim_calibrate.calibrate`` fits a heater's parameters from its
recorded statuses, and ``sim_calibrate.fit_book`` the heat book's;
:doc:`/how-to/calibrate-simulator` shows how to run them. The methods,
in the order they run:

**The frame.** One row per status, each holding until the next: the
probes, the running flags, the power, the energy count, the target, and
the heater's air reading. A silence longer than four times the usual
spacing (and at least 5 minutes) marks the span unobserved. The air
beside the heater and the humidity are added where given, and the
draws and circulation runs where both are.

**Quiet windows.** Spans of 3 hours or more with nothing heating and no
water moving, starting 45 minutes after the last of either. Each window
is fitted on its own first; a window whose fit misses the probes' mean
by 2 degF RMS or more is dropped.

**Standby loss.** Only windows that open with a gap of 10 degF or less
are used. With 10 or more that open with a gap of 1 degF or more, the
loss law, the bottom loss and its gate are fitted together by least
squares with a soft L1 loss, so outlying windows weigh less, on where
each window's two probes ended, each walked from its start as the
simulation walks it. With fewer, the law is fitted on the windows' own
``UA`` values and there is no bottom loss. The exponent is fitted only
with 4 or more windows across two 20 degF bands of tank-to-air
difference and an air sensor; on the heater's own reading it stays at
the base's.

**The gap's time constant.** Fitted on the windows that open with a gap
of 2 degF or more, by a bounded search. The bottom loss opens the gaps
the constant closes, so the two fits alternate until the constant moves
0.5 % or less.

**The compressor.** Recoveries that reached their target, with no
element in them. A recovery whose energy-to-setpoint count is still
above 500 Wh at its end was cut short and is left out. ``compressor_constant`` is the value whose
predicted durations best match the recorded ones (a bounded search on
the squared error). A fit pinned on a bound is reported, not applied.

**Power and efficiency.** On the compressor cycles' metered energy:
``power_scale`` is the ratio of metered to modelled energy; ``cop_scale``
and the start-up energy come from a weighted linear fit; the lift term
from a grid search. The efficiency uses only cycles with no water in
use around them. ``sim.calibration.calibrate``, given a meter's draws
and the circulation runs, prices that heat instead.

**The installation's terms.** ``sim_calibrate.fit_book`` fits the heat
book's terms on pairs of anchors (the heat booked between two full-tank moments against the
change the probes show) by an L1 linear program; a term the pairs can't
tell apart from the others stays at the base. The circulation's terms,
the draw response and the readiness evidence have fits of their own
(:doc:`/how-to/simulate-heater`).

**Held out, in time order.** The compressor fit holds out the latest
fifth of its recoveries (with 10 or more) and reports the error there
as well as on what it was fitted on. The heat book's fit needs 10
pairs, holds out the latest fifth, and replaces the base only when it
books those no worse. With ``keep_better``, the standby loss, the gap's
constant, the compressor, the power scale and the efficiency are each
refitted on their earlier four fifths, and a refit replaces the base's
value only where it scores better on the latest fifth; with fewer than
10 items the base is kept. A group the base lists as unfitted takes its
refit without that comparison, fitted on all its data.

**Provenance.** Every parameter records whether it was ``measured`` on
the heater by a targeted run, ``fitted`` from its record, or an
engineering ``default``, and whether it describes the **heater** or the
**installation** (``params.provenance_of``, ``params.scope_of``). A term
the calibration could not fit is listed in ``HeaterParams.unfitted``,
and every answer that relies on it says so in its ``reasons``
(``physics_uncalibrated``, ``book_uncalibrated`` and the rest).


How the sensors are used
========================

The heater's own readings are the only required input; everything else
improves an answer where it is given and has a stated default where it
is not.

The heater's readings
---------------------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Reading
     - How the simulator uses it
   * - The upper and lower tank probes
     - The tank's state at the start, the two zones every fit is scored
       against, and the heat book's anchors (both within
       ``uniform_band_f`` is a full tank). Required.
   * - The compressor's running flag
     - Whether a recovery is in progress; its last stop starts the
       restart lockout and dates the last heating. In a record it
       defines the recovery runs and decides which air reading a
       sample is (below). Without it, the heat source stands in.
   * - The elements' running flags and the heat source
     - Whether an element is running and since when. A recovery with an
       element in it, or in the 10 minutes before it, is left out of the
       compressor fit.
   * - The heater's air reading
     - While the compressor runs, the air drawn over the coil. The heat
       book and the Home Assistant air fit use it from 5 minutes into a
       run, once it has settled; the compressor fit takes its mean over
       the run. From August to October it read within about 0.35 degF
       of a sensor beside the heater, up to about 2 degF warm from May
       to July. While it is idle, the
       cabinet's own warmth: about 6 degF warm, so 6.2 degF
       (``IDLE_CABINET_WARM_F``) is taken off and the answer says
       ``ambient_from_idle_cabinet``. With the compressor's state
       unknown, it is not corrected. Without an air sensor, the standby
       fit uses the idle reading corrected the same way, and the
       recoveries the running one.
   * - The evaporator coil's reading
     - In ``active_cycle``, the running cycle's evaporator in place of
       the model's own estimate. The measured approach (19.56 degF at
       65 degF air) came from it.
   * - The heater's power reading
     - The metered energy of each compressor cycle, which the power and
       efficiency fits are made on.
   * - The energy-to-setpoint count
     - In a record, a recovery whose count is still above 500 Wh at its
       end was cut short and is left out. In ``forecast``, a zero count
       means no heating is needed, but only while no TOU window has
       raised the upper start threshold.
   * - The setpoint and the thresholds
     - The setpoint, ``hp_lower_on`` (the lower zone's start; without it
       that start is never searched, ``hp_lower_on_unknown``),
       ``hp_lower_off`` (the recovery's target; without it, the
       setpoint), and ``hp_upper_on``, whose rise marks a TOU window in
       force.
   * - The mode, TOU switch and status flags
     - The mode in force and the TOU switch. A hybrid operating mode,
       an anti-legionella cycle or an error code keeps a recovery out of
       the compressor and power fits. The "hot water in use" flag is the quiet test
       where no meter is given; it also fires on circulation.

Readings the simulator does not use: the inlet temperature field (it
reads 0, so the inlet is an input), the flow rate fields (the
cumulative one reads 0 after a year in service), the discharge and
suction temperatures, the fan speed, the expansion valve, the outdoor
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
     - The ambient for the standby loss and the recoveries, and the
       circulation return's rest temperature. In a fit from Home
       Assistant, its readings count only over the span they cover. Without it: the heater's
       own reading as above, or 65 degF with ``ambient_defaulted``.
   * - Humidity of that air
     - The coil's latent load, through the air's dew point. Without it:
       50 %, named in ``defaults_used``. On the record it moves a
       recovery's duration by a mean 1.2 min.
   * - A probe on the cold supply
     - The mains temperature, but never its raw reading: at rest the
       pipe tracks the air. The mains is the median plateau of long
       draws (11 minutes or more, circulation off) that ended in the last
       72 hours; each draw's plateau is the median of its last 2
       minutes, none earlier than minute 9. Without it: the parameters' inlet (one
       installation's September mains) with ``inlet_temp_modelled``.
   * - A flow meter on the hot line
     - The draws, in delivered gallons (or tank gallons, with
       ``flow_volume="tank"``), which move the tank and debit the heat
       book. A reading holds 60 seconds and then counts as no flow.
       Without one there is no heat book (``no_heat_book``), and in a
       fit the heater's "in use" flag stands in for the quiet test.
   * - The circulation pump
     - Its runs, from its speed (10 rpm or more is running), priced as
       above. Without them, an installation that circulates says
       ``circulation_unknown``.
   * - An outdoor forecast
     - The air ahead of time: ``air = damping x outdoor(t - lag) +
       offset``, fitted from the air beside the heater (without that
       sensor, the heater's running readings) against the outdoor
       history, and shifted to pass through the heater's last running
       reading.
       Not used in calibration: unanchored, it ran about 6 degF cold.

Where a sensor's record has a gap, the value before it holds across a
short silence (a Home Assistant restart, say); a span nobody heard is
left out of the fits, and the air across an air sensor's outage is
65 degF in the heat book.
