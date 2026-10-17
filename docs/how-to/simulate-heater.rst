===================
Simulate the Heater
===================

Predict what the heater will do over the next hours, and evaluate a
setpoint, mode, reservation or TOU change before you send it. The
simulator, ``nwp500.sim``, is described in :doc:`/explanation/simulator`;
every input it takes is listed in :doc:`/reference/simulator-inputs`.

.. contents::
   :local:
   :depth: 1


Install the extra
=================

The simulator needs numpy, pandas and scipy, which the core library
does not:

.. code-block:: bash

   pip install nwp500-python[sim]


Fetch what the heater reports
=============================

A scenario starts from four things the library already reads:

- the ``DeviceStatus``: the tank thermistors, what is heating, the
  setpoint, the mode, the TOU switch and the air at the heater;
- the ``DeviceFeature``: the tank size, which picks the default
  parameters, and the controller serial the TOU read needs;
- the ``ReservationSchedule``: the weekly reservations;
- the ``TOUInfo``: the TOU price periods.

The simulator does no I/O, so fetch them first. Each MQTT read is a
request answered on a subscription:

.. code-block:: python

   import asyncio
   import os

   from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient


   async def answer(subscribe, request, device, timeout=15.0):
       """Subscribe, send the request, and return the first reply."""
       reply = asyncio.get_running_loop().create_future()

       def on_reply(value):
           if not reply.done():
               reply.set_result(value)

       await subscribe(device, on_reply)
       await request(device)
       return await asyncio.wait_for(reply, timeout)


   async def fetch():
       async with NavienAuthClient(
           os.environ["NAVIEN_EMAIL"], os.environ["NAVIEN_PASSWORD"]
       ) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           try:
               status = await answer(
                   mqtt.subscribe_device_status,
                   mqtt.request_device_status,
                   device,
               )
               feature = await answer(
                   mqtt.subscribe_device_feature,
                   mqtt.request_device_info,
                   device,
               )
               reservations = await answer(
                   mqtt.subscribe_reservation_response,
                   mqtt.request_reservations,
                   device,
               )
           finally:
               await mqtt.disconnect()

           tou = await api.get_tou_info(
               mac_address=device.device_info.mac_address,
               additional_value=device.device_info.additional_value,
               controller_id=feature.controller_serial_number,
           )
       return status, feature, reservations, tou


   status, feature, reservations, tou = asyncio.run(fetch())

A heater with no TOU plan has no periods to read; pass ``tou=None``
below and leave TOU off.


Build a scenario
================

``nwp500.sim_adapters`` turns those models into a scenario's parts.
The one it cannot fill is the time zone the heater's schedules are in,
which the heater does not report.

.. code-block:: python

   from datetime import UTC, datetime, timedelta

   from nwp500 import sim, sim_adapters as sa

   scenario = sim.Scenario(
       start=datetime.now(UTC),
       horizon=timedelta(hours=24),
       tz="America/Los_Angeles",  # the zone the heater's clock is set to
       state=sa.heater_state(status),
       settings=sa.settings(status),
       schedules=sa.schedules(
           reservations=reservations,
           tou=tou,
           tou_enabled=status.tou_status,
       ),
       environment=sa.environment(status),  # the air at the heater now
   )
   params = sa.params(feature)  # the defaults for this tank size

``start`` must be timezone-aware. ``sa.environment(status)`` holds the
device's reading of the air at its intake for the whole span; a
forecast does better (`Make the answer better`_).


Work in your units
==================

The simulator itself takes degF and US gallons: its fields end in
``_f`` and ``gallons``. Go through ``sim_adapters`` and you never touch
them; it converts at the boundary, in the library's preferred units
(:doc:`manage-units`):

- The device's fields are read raw, so the same status builds the same
  scenario whatever unit system is set.
- What you supply is in the preferred unit: degC and litres after
  ``set_unit_system("metric")``, degF and gallons otherwise.
  ``sa.environment(ambient=..., inlet=...)``, ``sa.loads``, ``sa.write``
  and ``sa.reservation_entry`` take it.
- ``sa.path(result)`` gives the tank along a result in the preferred
  unit, and ``sa.temperature(value)`` and ``sa.volume(value)`` convert
  any other value a result holds. ``sa.temperature_unit()`` and
  ``sa.volume_unit()`` give the symbols.

The examples below work in either unit system; the numbers shown are
in degF.


Run it and read the answer
==========================

.. code-block:: python

   from zoneinfo import ZoneInfo

   result = sim.simulate(scenario, params)

   local = ZoneInfo(scenario.tz)  # instants come back in UTC
   for h in result.heating:
       print(
           f"{h.start.at.astimezone(local):%a %H:%M} {h.source:<10} "
           f"started by {h.start.cause}/{h.start.trigger}, ended "
           f"{h.end.astimezone(local):%H:%M} ({h.stop}), "
           f"{h.input_wh or 0:.0f} Wh"
       )

   print(f"Total: {result.input_wh:.0f} Wh")
   for slot, wh in result.energy_by_slot():
       print(slot, wh)

   unit = sa.temperature_unit()
   for r in sa.path(result)[::30]:
       print(f"{r.at.astimezone(local):%H:%M} "
             f"upper {r.upper:.1f}{unit}, lower {r.lower:.1f}{unit}")

What a result holds:

``result.heating``
   One ``HeatingInterval`` per recovery. ``start.cause`` is ``heater``
   (one of its own triggers, named in ``start.trigger``), ``write`` (a
   setpoint or mode write, its ``id`` in ``start.serves``) or
   ``running`` (it was already heating at the start). ``source`` is
   ``compressor`` or ``element``. ``stop`` is ``target``, ``cap`` (the
   TOU cap ended it, and ``capped`` is true), ``write``, ``mode`` or
   ``horizon``. ``input_wh`` is its electricity.
``result.points``
   The tank along the walk, in degF: ``upper_f``, ``lower_f``, the
   setpoint, the mode, and whether it is heating. ``sa.path(result)``
   gives the temperatures in the preferred unit.
``result.writes`` and ``result.mode_writes``
   Every setpoint write and reservation firing, and every mode write, as
   it landed: fired, skipped, held by a TOU window, or withdrawn.
``result.modes``
   The mode in force over each part of the span.
``result.input_wh``, ``energy_by_slot()``, ``energy_by_source()``
   Electricity in total, per clock-aligned slot (an hour by default),
   and per slot split into compressor and element.

Then check what the answer rests on:

.. code-block:: python

   print(result.defaults_used)  # e.g. ('humidity=50.0', 'inlet_f=72.4', ...)
   print(result.reasons)        # e.g. ('tou_cap_projected',)

``defaults_used`` names every input the simulator had to assume.
``reasons`` names what it could not model, such as a reservation in
Vacation mode (``reservation_mode_not_modelled``). Each entry in either
list is a limit on the answer, and most can be removed by supplying the
input (:doc:`/reference/simulator-inputs`).


Evaluate a change before sending it
===================================

A scenario is a frozen value, so a "what if" is a copy with its
``commands`` set. Compare it with the scenario as it stands:

.. code-block:: python

   at = scenario.start + timedelta(hours=2)

   # A setpoint and a mode write, at an instant.
   eco = scenario.model_copy(update={"commands": sim.Commands(
       writes=(sa.write(at, setpoint=130.0, mode=3),),  # Energy Saver
   )})

   # TOU switched off at the start.
   no_tou = scenario.model_copy(update={"commands": sim.Commands(
       tou_enabled=False,
   )})

   # A different reservation schedule, written at the start: weekdays
   # at 05:30, High Demand at 140.
   weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
   early = scenario.model_copy(update={"commands": sim.Commands(
       reservations=(
           sa.reservation_entry(
               days=weekdays, hour=5, minute=30,
               mode=4, temperature=140.0,  # High Demand
           ),
       ),
   )})

   base = sim.simulate(scenario, params).input_wh
   for name, s in [("eco", eco), ("no TOU", no_tou), ("early", early)]:
       print(name, sim.simulate(s, params).input_wh - base, "Wh")

Modes are ``DhwOperationSetting`` values: 1 Heat Pump, 2 Electric,
3 Energy Saver, 4 High Demand, 5 Vacation, 6 Power Off. A write must
fall inside the scenario's span. ``sa.reservation_entry`` builds an
entry as ``build_reservation_entry`` builds one for the device
(:doc:`schedule-operation`), with the same range check.

A heater already in Vacation or Power Off starts no heating. A write or
reservation that switches to either is not modelled: it is left out,
and ``reasons`` says so (``write_mode_not_modelled``,
``reservation_mode_not_modelled``). ``input_wh`` is None when an
interval's energy could not be priced.


Ask when the tank will be hot
=============================

``recovery`` answers for one instant: the recovery running now, or the
next one the heater will start, with no draws.

.. code-block:: python

   r = sim.recovery(
       sa.heater_state(status),
       sa.settings(status),
       sa.environment(status),
       params,
       at=datetime.now(UTC),
       schedules=scenario.schedules,  # TOU holds and caps a recovery
       tz=scenario.tz,
   )
   if r.interval is None:
       print("No recovery in the next 24 h:", r.reasons)
   else:
       print(f"Hot at {r.ready_at.astimezone(local):%H:%M}, "
             f"in {r.minutes:.0f} min ({r.interval.stop})")

``ready_at`` is when that interval ends. A recovery the TOU cap stops
ends about 3.6 degF (2 degC) short of the setpoint, and its ``stop``
says ``cap`` (:doc:`/explanation/tou-recovery-cap`).


Watch the tank coast
====================

``standby`` runs the tank with no heating at all: standby loss and any
draws. Use it for "how cold will it be by morning?":

.. code-block:: python

   trace = sim.standby(
       sa.heater_state(status),
       sa.environment(status),
       sim.Loads(),
       params,
       start=datetime.now(UTC),
       until=datetime.now(UTC) + timedelta(hours=10),
   )
   last = sa.path(trace)[-1]
   print(f"{last.at.astimezone(local):%H:%M}: "
         f"upper {last.upper:.1f}{unit}, lower {last.lower:.1f}{unit}")

Pass the settings, and the TOU schedule if there is one, and it also
says when the heater would start itself on that coast, and why:

.. code-block:: python

   trace = sim.standby(
       sa.heater_state(status),
       sa.environment(status),
       sim.Loads(),
       params,
       start=scenario.start,
       until=scenario.start + timedelta(hours=10),
       settings=sa.settings(status),
       schedules=scenario.schedules,
       tz=scenario.tz,
   )
   print(trace.starts_at, trace.trigger, trace.start_held, trace.lower_margin_f)

``trigger`` is ``lower`` (the lower zone reached ``hp_lower_on``),
``upper_at_tou_open`` or ``lower_at_tou_close``; ``start_held`` says a
TOU window or a hot upper zone held the lower trigger back.
``lower_margin_f`` is how far above ``hp_lower_on`` the coast leaves the
lower zone.


Ask how much hot water is left
==============================

``readiness`` answers in delivered gallons: what the tap can get before
the water falls below the line (105 degF by default).

.. code-block:: python

   d = sim.readiness(sa.heater_state(status), sa.settings(status), params)
   print(f"{sa.volume(d.gal):.0f} {sa.volume_unit()} ({d.basis})")

Two probes can say how much is left only when the tank is full, so
without more to go on the answer is a full tank's (a floor that allows
for cold water hiding under the lower probe) or 0. Give it more:

- **A heat book**, if you know the tank has been quiet since a recovery
  ended (``basis`` becomes ``energy``):

  .. code-block:: python

     book = sa.full_tank_book(status, params)  # nothing drawn since it heated
     d = sim.readiness(
         sa.heater_state(status), sa.settings(status), params, book=book
     )

- **Evidence**: draws from your own record of how much a tank in a
  given state delivered (``ReadinessParams.evidence``,
  :doc:`/reference/simulator-inputs`).

The gallons count the water in the pipe to your fixture
(``ReadinessParams.delivered_lag_gal``). The default is one bath's at
one installation; set your own.


Ask when a bath will be ready
=============================

``time_to_ready`` answers for a scenario's start: whether the tank can
run a bath now, and if not how long until it can, in the heat pump and
in each element mode, with the electricity to get there; and how many
showers it is ready for.

.. code-block:: python

   r = sim.time_to_ready(
       scenario,
       params,
       bath_gal=sa.to_sim_volume(40.0),  # your bath, in your unit
       book=book,                        # if you have one
   )
   print(r.bath.ready, r.bath.margin_gal, r.bath.ready_in_minutes)
   for m in r.bath.by_mode:
       print(f"{m.mode:<12} {m.ready_in_minutes} min, {m.energy_kwh} kWh"
             f"{'' if m.reachable_now else ' (not reachable now)'}")
   print(r.showers.ready_for_whole, "showers;", r.reasons)

The heat pump's time follows the recovery the heater runs next
(``r.recovery``): from now if the compressor runs, else from its own
trigger on the coast to it, under the scenario's draws, with the TOU
cap applied where the recovery ends. An element mode is not reachable
inside a TOU window, nor anything while heating is disabled. The bath
defaults to ``ReadinessParams.bath_gal`` (28.7 gal, one household's),
the shower to 12 gal; ``defaults_used`` says when they were used.

The recovery is the core's physics alone. It runs short on long
recoveries (:doc:`/explanation/simulator`), so a long time to ready is
an underestimate.


Try an element mode
===================

``element_mode`` projects one recovery in Energy Saver (3), High
Demand (4) or Electric (2): how fast the upper zone comes up, the
element's running time and energy, and the tank when you switch back.

.. code-block:: python

   e = sim.element_mode(
       sa.heater_state(status),
       sa.settings(status),
       params,
       mode=4,                      # High Demand
       at=scenario.start,
       schedules=scenario.schedules,
       tz=scenario.tz,
       switch_back_after_minutes=30,
   )
   print(e.reachable, e.unreachable_reason)
   print(e.plan.upper_setpoint_minutes, e.plan.element_kwh)

``reachable`` is False inside a TOU window, where a mode write may not
take, and while heating is disabled. To see the whole day with the
mode in force, simulate a mode write instead (`Evaluate a change before
sending it`_).


Have it ready by a time
=======================

When must a heat-pump recovery start for the tank to be hot at 7 am,
and is there time? ``forecast`` coasts the tank to the start, runs the
recovery from there, and moves the start until the two agree:

.. code-block:: python

   f = sim.forecast(
       sa.heater_state(status),
       sa.settings(status),
       environment,
       params,
       at=now,
       target_time=tomorrow_7am,
   )
   print(f.status, f.start_at, f.ready_at, f.duration_minutes)

``status`` is ``ok``; ``infeasible`` when it cannot be ready in time
(it starts now, ``ready_at`` is when it would finish, and
``shortfall_minutes`` is how late); ``no_heating_required`` when the
tank is already there; or ``not_scheduled`` in Vacation or Power Off.
The target is the heater's own stop threshold
(``hp_lower_off_temp_setting``); pass ``target_lower_f=`` for a
partial charge. With a fitted COP, ``f.trajectory`` carries the
electricity, the heat stored and the COP along the way, and
``f.startup_energy_wh`` the cost of the compressor's start.

While the compressor runs, ``sim.active_cycle`` says what is left of
the recovery under way. Pass ``evaporator_f=sa.evaporator_f(status)``
so its physics estimate uses the coil's live reading.


Judge a shower or a bath
========================

Give the draws and the window they fall in; the result says whether
the tank could supply it:

.. code-block:: python

   start = scenario.start + timedelta(hours=12)
   bath = scenario.model_copy(update={"loads": sa.loads(
       [(start + timedelta(minutes=i), 2.5) for i in range(16)],  # 40 gal
       windows=[(start, start + timedelta(minutes=20), 40.0)],
   )})
   r = sim.simulate(bath, params, book=book)
   w = r.windows[0]
   print(w.deliverable_gal, w.margin_gal, w.depleted, w.delivery_min_f)

``deliverable_gal`` and ``margin_gal`` are the tank at the window's
onset against the gallons expected; ``depleted`` says the delivered
water fell more than 3.4 degF below the line, or stayed below it more
than 3 minutes (the heater's own dip during a draw is not running out).

Pass a ``book`` for ``depleted`` to mean anything. Without one, each
draw moves the zones by its calibrated response, which holds the upper
zone up even through a draw that empties the tank, so the delivery does
not fall; ``reasons`` says ``no_heat_book``, and ``margin_gal`` is then
the answer to read. ``result.delivery`` and ``sa.path(result)`` give the
delivered temperature along the whole walk.


Make the answer better
======================

Each of these replaces a default with a fact:

**The air ahead of time.** The device reports the air at its intake
now, and only while the compressor runs is that the air the heater
stands in: idle, it reads its own cabinet, about 5 degF warm. Project
the air from an outdoor forecast instead, anchored to the last reading
taken while the compressor ran:

.. code-block:: python

   reading = sa.location_air_reading(status)  # None while idle
   air = sa.location_air(
       outdoor_forecast,               # [(instant, temperature), ...]
       start=scenario.start,
       until=scenario.until,
       anchor=None if reading is None else (scenario.start, reading),
   )
   environment = sa.environment(
       ambient=air,
       humidity=45.0,  # %RH; the heater does not report it
       inlet=58.0,     # the mains temperature, if you know it
   )

The model, ``air = damping x outdoor(t - lag) + offset``, defaults to
one installation's (0.638, 2 h, +24.5 degF). Fit your own
from the heater's running-compressor readings and the outdoor air's
history over the same time, from a public weather service, say:

.. code-block:: python

   from nwp500.sim import location_air

   fitted = location_air.fit(running_readings, outdoor_history)
   print(fitted.model, fitted.r)
   air = sa.location_air(outdoor_forecast, start=..., until=...,
                         anchor=..., model=fitted.model)

Any readings or forecast of your own work too: they are interpolated
between, and held past the last one.

**Hot water drawn.** The heater does not report draw volume, so give
the draws you expect (a forecast) or the ones a flow meter recorded,
counted on the delivered (mixed) line:

.. code-block:: python

   loads = sa.loads([
       (start + timedelta(hours=1), 12.0),
       (start + timedelta(hours=13), 20.0),
   ])

From a weekly draw forecast (a forecaster learned from your meter, as
``sim.draw_forecast.ForecastSlot`` per 10-minute slot), lay out the
draws it expects instead:

.. code-block:: python

   from nwp500.sim import draw_forecast

   if draw_forecast.check_issue(slots) is None:
       profile = draw_forecast.draw_profile(slots, scenario.start,
                                            scenario.until)
       loads, withheld = draw_forecast.forecast_loads(
           profile, scenario.start, worst_case=True)
       result = sim.simulate(scenario.model_copy(update={"loads": loads}),
                             params, book=book, withheld_windows=withheld)

Each expected draw is a slot's rate times its per-draw mean, a
fraction of a shower in most slots. It keeps that per-draw volume, so
it is judged against the draws the parameters were fitted on, not
against its own fraction. Each of the heater's draw windows opens up to
an hour before its first likely long draw. With ``worst_case``, each
window's long draws come first, back to back from its opening, and no
recovery is credited until they are done. ``result.windows`` then says
whether the tank held through each.

Put them in a scenario with
``scenario.model_copy(update={"environment": environment, "loads": loads})``.

**History.** Without it the simulator assumes no restart lockout is in
force and that it does not know when the tank last heated. Track
``comp_use`` (and ``heat_upper_use``, ``heat_lower_use``) in the status
stream and record when each changed:

.. code-block:: python

   history = sim.History(
       compressor_stopped_at=last_compressor_stop,
       heated_at=last_heating_end,
   )

**Circulation.** If your installation circulates hot water on a
schedule, give the runs and what each takes
(:doc:`/reference/simulator-inputs`):

.. code-block:: python

   from dataclasses import replace

   runs = sa.circulation(
       [(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
         "06:00", "07:00")],
       tz=scenario.tz, start=scenario.start, until=scenario.until,
   )
   circulating = scenario.model_copy(update={"loads": sim.Loads(
       circulation=runs)})
   mine = replace(params, circulation=sim.CirculationParams(
       displaced_gal=5.0, flow_gpm=1.5, loss_btu_per_gal=150.0))

**The heat book.** With a hot-water flow meter and a record of the
heater's statuses, book the tank's heat from the record and pass it as
``book=``: draws then take the zones down as the tank empties.

.. code-block:: python

   book = sa.book_from_history(
       recorded,              # [(instant, DeviceStatus), ...]
       params,
       at=now,
       flow=meter_flow,       # [(instant, flow per minute), ...]
       circulation=runs,      # [(start, end), ...], if you circulate
       circulation_flow=pump_flow,
   )
   readiness = sim.time_to_ready(scenario, params, book=book)

Without a meter, start one only when you know the tank is full and
quiet (``sa.full_tank_book``).

With an inlet probe on the cold supply, convert the book's gallons at
the mains rather than at the probe's own median, which at rest reads
the air around the pipe:

.. code-block:: python

   from nwp500.sim.cold_supply import on_the_mains

   cold = sa.cold_supply(inlet_probe, at=now, flow=meter_flow,
                         circulation=runs)
   book, measured = on_the_mains(book, cold)
   readiness = sim.time_to_ready(scenario, params, book=book,
                                 inlet_measured=measured)

The mains is the median plateau of the long draws (11 minutes or more,
with circulation off) over the last 72 hours, read from minute 9 of each
draw, once the probe has passed the stagnant pipe. There is none
without such a draw, and the book keeps its own inlet.

**Your installation's readiness terms.** The pipe to your fixture, the
line you call hot, your own draws: ``ReadinessParams``
(:doc:`/reference/simulator-inputs`).

**Your heater's own parameters.** The defaults are one NWP500-65's.
Fit your own from what your heater reported: record each status and
when it arrived (a few weeks, through quiet nights and full
recoveries), give the air where it stands over the same time, and
calibrate:

.. code-block:: python

   from nwp500.sim import calibration

   history = sa.history(
       recorded,                 # [(instant, DeviceStatus), ...]
       air=air_over_the_record,  # a sensor's, or sa.location_air(...)
   )
   fitted = calibration.calibrate(history, sa.params(feature))
   print(fitted.standby.ua_ref, fitted.standby.n_quiet)
   print(fitted.compressor)      # None: too few recoveries
   params = fitted.params

Three fits run, each only where the record holds the evidence for it,
and each says what it used:

- **Standby loss**: the jacket's loss law, and how fast the zones
  mix, from windows of 3 hours or more with no heating and no hot water
  in use (45 minutes after either). It needs ``air``.
- **The compressor**: its constant and the evaporator's approach, from
  heat-pump recoveries that reached their target, against the loss
  just fitted. The air over a recovery is the heater's own reading,
  taken while its compressor runs. With 10 recoveries or more, the
  latest fifth is held out, and ``heldout_mae_minutes`` says how well
  the fit predicts recoveries it did not see. A fit that lands on a
  bound is reported (``hit_bounds``) and not applied.
- **Power and COP** (``fitted.power``): the heater's own power readings
  against the compressor just fitted, over 10 cycles or more. Input
  power is scaled as a ratio of sums. The apparent COP gets a level, a
  start-up cost in Wh and a lift term. Without a meter, the COP uses
  only cycles with no hot water in use from 30 minutes before them to
  their end. With one, pass its draws and the circulation's runs,
  ``calibrate(..., draws=[(instant, gallons), ...],
  circulation=[(start, end), ...])`` (an empty list for none), and every
  cycle counts, the heat its draws and runs took priced in.

A part without the evidence keeps the value it had. A meter's draws
and the circulation's runs, where you record them, make the quiet test
exact (``sa.history(..., drawing=..., circulating=...)``): the heater's
own "hot water in use" flag also fires on circulation.

Save the parameters (``nwp500.sim.params.params_to_document``) and load
them with ``params_from_document``.

**With a hot-water meter**, fit the readiness evidence and the heat
book's own terms from the record too. The evidence comes from the
clean draws: circulation and both elements off, and a settled start.
Each draw's volume delivered before the upper probe crossed 105 degF
becomes a point, and the points another beats from a no-better state
are dropped:

.. code-block:: python

   from dataclasses import replace

   frame = sa.draw_frame(recorded, start=since, end=until, flow=meter_flow,
                         circulation=runs)
   draws = calibration.clean_draws(frame)
   evidence = calibration.fit_evidence(draws)
   print(evidence.n_quiet, evidence.held_out_crossed, evidence.held_out_over)

The book's terms are fitted on pairs of anchors on full tanks an hour
to a day apart. Each pair's booked heat is checked against the probes':

.. code-block:: python

   p = params.book_terms()
   steps = sa.book_steps_from_history(
       recorded, start=since, end=until, flow=meter_flow, air=air,
       circulation=runs, circulation_flow=pump_flow, params=params,
   )
   book = calibration.RecordedBook(steps, p, params.circulation, start=since)
   fit = calibration.fit_book_terms(book, book.reanchors(), p)
   p = replace(p, hp_btu_per_h=fit.hp_btu_per_h,
               hp_btu_per_h_per_f=fit.hp_btu_per_h_per_f,
               ua_btu_per_h_f=fit.ua_btu_per_h_f)
   bands = calibration.book_error_bands(book, p, fit.loss_btu_per_gal)
   empty, crossings = calibration.empty_point(book, p, fit.loss_btu_per_gal)
   zone = calibration.zone_empty_point(book, p, fit.loss_btu_per_gal)

``book_error_btu(book, p, fit.loss_btu_per_gal)`` gives the book's
error bands: the 90th percentile of its error pooled over re-anchors an
hour to ``max_anchor_age_h`` apart, and the 18 to 24 h band's past it,
each rounded up to 100 BTU. ``cold_lower_cap(draws,
cutoff_f)`` is the evidence's cap after a cold lower zone. The cutoff
itself, and the bath's volume, are yours to set: measure a bath by
filling one to your usual level at the hot side's meter.

How a draw moves the zones is fitted on the record's long draws too,
the book walked continuously over it (``book_walk``):

.. code-block:: python

   walk = calibration.book_walk(book, zone_empty_btu=p.zone_empty_btu)
   draws = calibration.long_draws(walk)
   split = since + (until - since) * 0.7   # the later draws are held out
   front = calibration.fit_front(
       calibration.front_frame(walk, draws, params, split=split))
   settle = calibration.fit_front_settle(
       calibration.settle_tails(walk, draws, params, split=split))
   mix = calibration.fit_zone_mix(
       calibration.mixing_frame(walk, draws, split=split))

``front`` is where the lower probe sits in the cold front and how wide
the front is (``lower_probe_gal``, ``front_width_gal``). ``settle`` is
how fast the lower zone settles after a draw (``front_settle_min``).
``mix`` is how the upper zone falls through a long draw
(``zone_mix_f_per_gal``, ``zone_mix_gal``). Each reports its error on
the training and held-out draws and a day bootstrap's interval, and
each fit's procedure is the one its value was fitted with. Two inputs
stand in for what that fit had:

- the long draws are the record's own runs of household flow;
- the front's base is the calibrated draw response chained from each
  draw's onset probes, rather than a full replay's lower zone.

With circulation's own telemetry (its running samples, flow and return
line temperature), fit its terms too:

.. code-block:: python

   runs = calibration.measure_runs(running, flow=pump_flow,
                                   return_f=return_line, upper_f=upper,
                                   air_f=air, compressor=compressor_runs)
   circulation = replace(
       params.circulation,
       displaced_gal=calibration.fit_displaced_gal(runs),
       flow_gpm=calibration.recent_flow_gpm(runs, until),
   )

Each run's heat is measured as its flow times the drop from the upper
zone to the return line. Runs with the compressor on are left out. The
displaced volume is the one that prices those runs best.
``recent_flow_gpm`` is the median run flow over the last 14 days, since
the flow is a setting that moves in steps. Either is None when the runs
cannot say.

The mixing fit reads gallons left before ``zone_empty_btu``, so refit
that first. The settle fit reads the front's place and width, so refit
those before it. The delivered water's lag (one bath's measurement) and
the heat hidden from a full tank's probes (a maximum over the record,
not a fit) stay installation values.


Fit the elements
================

The element terms (``ElementParams``) come from the heater's raw
change rows (``sim_adapters.record``). They are never read from a
one-minute grid, which can move an edge by as much as the lag being
measured:

.. code-block:: python

   from nwp500.sim import calibration as cal

   record = sim_adapters.record(readings)
   stints = cal.element_stints(record, draws=meter_draws,
                               circulation=circulation_runs, tz=tz)
   lag = cal.fit_element_lag(stints)          # upper_dead_time_min, upper_f_per_min
   off = cal.element_off_points(record, tz=tz)  # where each element stops
   power = cal.element_power(record, off)       # W per metered stint
   rates = cal.fit_element_rates(cal.element_grid(record, draws=meter_draws))

``meter_draws`` and ``circulation_runs`` are ``(start, end)`` spans
from your meter and your circulation. A stint is left out when a draw
or a circulation run falls within 5 minutes before it, up to its
first rise. Without a meter no stint counts as draw-free, and the lag
fit is left with the stints that ended cleanly. The upper probe's lag
and rate are fitted as one line, run minutes = lag + rise / rate. The
rate taken end to end on the grid (``fit_element_rates``) comes out
lower because the lag is inside it. ``day_ci`` is the 90 % interval
the measurements report, bootstrapped over local days.

Replay a day the heater lived
=============================

Record each status and when it arrived, and the simulator can be held
to what the heater did. ``sa.replay`` builds the scenario as of a past
instant from the record:

.. code-block:: python

   r = sa.replay(
       recorded,                 # [(instant, DeviceStatus), ...]
       at=yesterday_6pm,
       until=yesterday_11pm,
       tz="America/Los_Angeles",
       schedules=sa.schedules(tou=tou_info, reservations=reservations),
       environment=sa.environment(ambient=air_then),
   )
   result = sim.simulate(r.scenario, params)

The tank, what was heating and the settings are the last status at or
before ``at``. When the compressor last stopped and when the tank last
heated come from the record's edges. Every setpoint or mode change
over the span is a write, except the heater's own drop to Heat Pump as
a TOU window opens. The TOU switch's changes are kept too. A write into
Vacation or Power Off cannot be simulated and is named in
``r.reasons``. The record holds no schedule, so give the heater's own,
read with this library.


Compare it with what the heater did
-----------------------------------

``sa.observe`` reads the same record for what actually happened over a
range, in the simulation's terms:

.. code-block:: python

   seen = sa.observe(recorded, start=yesterday_6pm, end=yesterday_11pm,
                     now=now)
   for s in seen.starts:
       print(s.at, s.cause, s.trigger, s.counted)

``seen.starts`` are the compressor's starts. Each start's ``cause`` is a
recorded write (``write_at`` says which) or the heater's own trigger:
the lower zone at its start threshold, the upper zone short as a TOU
window opens, the lower zone as one closes, or the heater dropping an
element mode. ``counted`` merges starts less than 30 minutes apart.
``seen.sources`` are when the compressor and each element ran; an
element counts only where the heater's power shows it running.
``seen.slots`` are the energy per 10 minutes from the heater's own
power; ``seen.modes`` are the mode in force and whether the heat source
the heater reported showed it in effect. ``seen.gaps`` are where a
signal's record was missing, and a start a missing record could explain
gets no ``cause``. Set them beside the replay's ``result.heating``
(each interval's start, with its cause and trigger) and
``result.energy_by_slot()``.


Save and replay a scenario
==========================

A scenario, with or without its parameters, is a JSON document. Save
the ones you want to look at again, or attach one to a bug report:

.. code-block:: python

   import json
   from nwp500.sim import codec

   with open("scenario.json", "w") as f:
       json.dump(codec.scenario_to_document(scenario, params), f)

   with open("scenario.json") as f:
       scenario, params = codec.scenario_from_document(f.read())

The same scenario on the same parameters always returns the same
answer. ``codec.result_to_document(result)`` writes a result the same
way.


See also
========

* :doc:`/explanation/simulator`: the model, and how accurate it is
* :doc:`/reference/simulator-inputs`: every input, its unit, and where
  it comes from
* :doc:`/reference/python_api/sim`: the API
