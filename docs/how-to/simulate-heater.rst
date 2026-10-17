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
now. Pass readings or a forecast instead; they are interpolated
between, and held past the last one. The humidity and the mains water
temperature are not reported at all:

.. code-block:: python

   start = scenario.start
   environment = sa.environment(
       ambient=[
           (start, 66.0),
           (start + timedelta(hours=6), 61.5),
           (start + timedelta(hours=12), 70.0),
       ],
       humidity=45.0,  # %RH
       inlet=58.0,     # the mains temperature, if you know it
   )

**Hot water drawn.** The heater does not report draw volume, so give
the draws you expect (a forecast) or the ones a flow meter recorded,
counted on the delivered (mixed) line:

.. code-block:: python

   loads = sa.loads([
       (start + timedelta(hours=1), 12.0),
       (start + timedelta(hours=13), 20.0),
   ])

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

**The heat book.** Start one when you know the tank is full and
quiet (``sa.full_tank_book``), or from your own record, and pass it as
``book=``: draws then take the zones down as the tank empties.

**Your installation's readiness terms.** The pipe to your fixture, the
line you call hot, your own draws: ``ReadinessParams``
(:doc:`/reference/simulator-inputs`).

**Your heater's own parameters.** The defaults are one NWP500-65's.
With your own calibration, build a ``HeaterParams`` or load one from a
document (``nwp500.sim.params.params_from_document``) and pass it
instead of ``sa.params(feature)``.


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
