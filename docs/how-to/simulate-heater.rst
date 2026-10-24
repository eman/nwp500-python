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

.. code-block:: bash

   pip install nwp500-python[sim]


From the command line
=====================

``nwp-cli simulate`` needs the ``cli`` and ``sim`` extras
(``pip install 'nwp500-python[cli,sim]'``).

**From the heater as it is now.** With no scenario, the heater and its
schedules are read from the device, the air is the heater's own
reading, and the walk runs 24 hours from now:

.. code-block:: bash

   nwp-cli simulate run
   nwp-cli simulate run --hours 8 --ambient 60 --inlet 55

The table lists each heating interval (what started it, its source,
its target, why it stopped and its energy), the energy by source, how
much hot water the tank can deliver at the start, the draw windows and
which of them ran cold, the reasons the answer may be less than it
seems, and every default it used. ``--format json`` prints the whole
result document (``codec.result_to_document``), and ``--format csv``
the tank along the path, one row per point.

**From a scenario file.** ``snapshot`` writes the heater and its
schedules now as a scenario document, with the default parameters for
its tank size. Edit it and replay it as often as you like; with
``--scenario`` and no ``--live``, nothing is read from the device and
no account is needed:

.. code-block:: bash

   nwp-cli simulate snapshot -o now.json
   nwp-cli simulate run --scenario now.json

A snapshot is one instant: it records nothing over time.
``examples/simulator/scenario.json`` is a scenario to start from.

**The heater now, with some of it changed.** With ``--live`` as well,
the device is read and the scenario document is laid over it: an
object merges field by field, and anything else (a list, a number)
replaces what the device gave. This document lowers the setpoint and
keeps the rest of the heater as it is:

.. code-block:: json

   {"schema_version": 1, "scenario": {"settings": {"setpoint_f": 125.0}}}

.. code-block:: bash

   nwp-cli simulate run --live --scenario lower.json

**Each part is chosen on its own:** a flag first, then the scenario
document, then the device.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Flag
     - Sets
   * - ``--start ISO``
     - The start, an ISO 8601 instant with its offset. Default: the
       scenario's, then now.
   * - ``--hours N``
     - The horizon. Default: the scenario's, then 24.
   * - ``--tz ZONE``
     - The IANA zone of the schedules' local times, which the heater
       does not report. Default: the scenario's, then this machine's.
   * - ``--ambient T``, ``--inlet T``
     - The air at the heater and the mains water, in your unit
       (``--unit-system``, or the heater's own when it is read).
   * - ``--environment FILE``
     - An ``Environment`` document, in place of ``--ambient``: air
       readings over time, humidity, the inlet.
   * - ``--draws FILE``
     - A ``Loads`` document: the draws, the windows to judge, and any
       circulation.
   * - ``--plan FILE``
     - A ``Commands`` document: setpoint and mode writes, a reservation
       schedule, the TOU switch.
   * - ``--params FILE``
     - A ``HeaterParams`` document (``params.params_to_document``), such
       as your own fitted ones. Default: the scenario's ``params``,
       then the defaults for the heater's tank size, then the 65 gal
       defaults (said on stderr).

The files are the simulator's own documents, in its units (°F, US
gallons), with the fields :doc:`/reference/simulator-inputs` lists. A
plan that lowers the setpoint at 22:00 and turns TOU on:

.. code-block:: json

   {
     "writes": [{"at": "2026-10-18T22:00:00-07:00", "setpoint_f": 120.0}],
     "tou_enabled": true
   }

A read from the device knows nothing of the time before it: when the
compressor last stopped, when the tank last heated. The result names
those defaults. Logging goes to stderr, so ``--format json`` and
``csv`` can be piped.

**The air, its humidity and the inlet from Home Assistant.** The heater
doesn't report the air it stands in while idle (it reads its own
cabinet, about 6 degF warm), the humidity or the mains water. If you
record them in Home Assistant, name the entities in a sources file and
pass it with ``--sources`` (or set ``NWP500_SOURCES``):

.. code-block:: toml

   [home_assistant]
   url = "http://homeassistant.local:8123"
   token_env = "HA_TOKEN"   # the variable holding a long-lived token
   draw_flow_volume = "tank"   # optional: what draw_flow counts

   [home_assistant.entities]
   air = "sensor.beside_the_heater_temperature"
   humidity = "sensor.beside_the_heater_humidity"
   inlet = "sensor.cold_supply_temperature"
   demand = "binary_sensor.hot_water_demand"  # on while hot water is drawn
   circulation_speed = "sensor.circulation_pump_speed"
   weather = "weather.forecast_home"
   draw_flow = "sensor.hot_water_draw_flow"  # the household's draws

   [home_assistant.heater]   # optional: the heater's own entities
   heard = "sensor.water_heater_last_status"
   upper = "sensor.water_heater_upper_tank_temperature"
   lower = "sensor.water_heater_lower_tank_temperature"
   compressor = "binary_sensor.water_heater_compressor"
   ambient = "sensor.water_heater_ambient_temperature"

   [location_air]   # optional: air = damping x outdoor(t - lag) + offset
   damping = 0.638
   lag_hours = 2.0
   offset_f = 24.5

.. code-block:: bash

   export HA_TOKEN=...   # Profile > Security > Long-lived access tokens
   nwp-cli simulate run --sources sources.toml

Every entity is optional, and the token never goes in the file. The
``url`` is the one Home Assistant answers on (``https://`` if it uses
TLS); redirects aren't followed. With the heater read live, the sources
give:

- **the air:** the hourly forecast projected through the
  ``[location_air]`` model, shifted to pass through a reading beside the
  heater that is at most an hour old; without a fresh one, the
  projection is unshifted. Without a ``[location_air]`` model, one is
  fitted on the last 3 days of the ``air`` entity's readings against
  the ``weather`` entity's outdoor temperature. Without an ``air``
  entity, or one that gives no fit, the ``[home_assistant.heater]``
  table's ``ambient`` reading while its ``compressor`` runs is fitted
  instead, and the projection is shifted to pass through its newest
  such reading. It is used when the
  readings span a day and follow the outdoor air at r 0.5 or more; a
  note gives the fit. Otherwise, and without a ``weather`` entity, the
  reading beside the heater is held over the span;
- **the humidity:** a reading at most an hour old;
- **the inlet:** the plateau of the long draws (11 minutes or more,
  circulation off) in the last 72 hours, from the inlet probe and the
  ``demand`` entity: a binary sensor that is on while the household
  draws hot water, with the circulation's water not among its draws. A
  circulation pump with no speed reading leaves no estimate, and a draw
  before its first reading is skipped;
- **the heat book:** with the ``[home_assistant.heater]`` table and a
  ``draw_flow`` entity (the household's hot water draw flow, the
  circulation's water not in it; ``draw_flow_volume`` says whether its
  gallons are ``"delivered"`` through the mixing valve, the default, or
  the ``"tank"``'s own water), the tank's heat booked from the last
  72 hours of the heater's readings and the draws
  (``sim_home_assistant.HomeAssistantBook``). The run walks from it,
  and "deliverable now" reads it (``energy``), whatever the gap between
  the two probes. Without it, the probes answer from the heat they
  place in the tank, apart or not (``probes``). With no full
  tank in the 72 hours, or a scenario that doesn't start now, the run
  walks without the book, and a warning says why.

Under "deliverable now", the table gives the bath and the showers the
tank is ready for (``sim.time_to_ready``): the bath ready with its
margin, or how short it is and when the heat pump has it ready; and the
whole showers, as a shower the tank can't finish isn't counted. Both are
delivered volumes, past the mixing valve. ``--bath`` and ``--shower``
give them in the preferred unit; without them, the parameters'
(``ReadinessParams.bath_gal``, 28.7 gal, and ``shower_gal``, 12 gal).

A reading's age is from when Home Assistant last heard the sensor
report (``last_reported``). Over the REST API, Home Assistant serves
that from a copy of the state it keeps until the state changes, and a
report of the same value doesn't renew the copy. So a sensor that has
held one value for over an hour can read as over an hour old, and its part
keeps its default, even while it still reports.

Units come from each entity's ``unit_of_measurement``: the pump's speed
in rpm or Hz. A part that can't be read, or is stale, keeps its
default, and a warning on stderr says why. ``--ambient``, ``--inlet``
and ``--environment`` override what the sources give.

From Python, ``sim_home_assistant.HomeAssistantEnvironment`` reads the
same parts. Given ``heater=``, a ``HeaterEntities`` with ``ambient`` and
``compressor``, it fits the model without an ``air`` entity: on the
heater's own air reading every 10 minutes while the compressor runs,
where the reading was taken 2 minutes or more into the run (earlier, or
idle, it reads the cabinet), and not while the sensor was unavailable.
With a model, given or fitted, and no fresh reading beside the heater,
each ``read`` anchors the projection to the heater's newest such
reading from the last hour. ``fitted_air`` holds the fit once ``read``
has run.

A caller that builds a new environment every few minutes needn't refit
each time. Fit on your own cadence, and pass the fit on:

.. code-block:: python

   fitted, notes = await ha.fit_location_air(
       client, entities, now=now, heater=heater_entities
   )   # hourly, say; None (and notes why) without enough history

   environment = ha.HomeAssistantEnvironment(
       client, entities, start=now, until=now + horizon, now=now,
       heater=heater_entities, fitted_air=fitted,
   )

Given ``fitted_air``, the environment projects through it, notes its r
and lag on every ``read``, and doesn't fit again.

The fit, the samples of the heater's air and the inlet's plateau are
CPU work: the fit alone takes about 100 ms on 3 days of 30-second
readings. To keep it off an event loop, pass ``run=``, a callable that
runs a function and awaits its result, to ``fit_location_air`` and
``HomeAssistantEnvironment``. In Home Assistant that is
``hass.async_add_executor_job``. Without it, the work runs inline.


Fetch what the heater reports
=============================

A scenario starts from four things the library already reads:

- the ``DeviceStatus``: the tank thermistors, what is heating, the
  setpoint, the mode, the TOU switch and the air at the heater;
- the ``DeviceFeature``: the tank size, which picks the default
  parameters, and the controller serial the TOU read needs;
- the ``ReservationSchedule``: the weekly reservations;
- the ``TOUInfo``: the TOU price periods.

``nwp500.sim_live`` fetches them and builds a scenario in one call:

.. code-block:: python

   from datetime import UTC, datetime, timedelta

   from nwp500 import sim, sim_live


   async def simulate_now(mqtt, api, device):
       """The next 24 hours, from the heater as it is now (a connected
       ``NavienMqttClient``, a ``NavienAPIClient`` and the device)."""
       composed = await sim_live.compose(
           start=datetime.now(UTC),
           horizon=timedelta(hours=24),
           tz="America/Los_Angeles",  # the zone the heater's clock is set to
           heater=sim_live.LiveHeaterSource(mqtt, device),
           schedules=sim_live.LiveScheduleSource(mqtt, api, device),
       )
       # Without the feature info the tank size is unknown: the 65 gal
       # defaults stand in.
       params = composed.params or sim.default_params()
       return sim.simulate(composed.scenario, params)

``environment=`` and ``loads=`` take any source with an ``async
read()``; ``sim_live.Given(value)`` is one for a value in hand. Without
``environment`` the air is the heater's own reading. A source that
gets no reply raises ``sim_live.LiveReadError``; so does the schedule
source when TOU is on and its periods cannot be read. A missing
feature info leaves ``composed.params`` None (the tank size is
unknown), so the example falls back to ``sim.default_params()``. Change a part with ``composed.scenario.model_copy(update=...)``.

With the status, the feature info, the reservations and the TOU
periods already read some other way, build the same parts from them:
``sim_live.heater_reading(status, feature)`` is what
``LiveHeaterSource`` reads, and ``sim_live.live_schedules(status,
reservations, tou)`` what ``LiveScheduleSource`` reads. Pass either to
``compose`` as ``sim_live.Given(...)``. ``tou`` is the ``TOUInfo`` the
TOU read gives, or the ``TOUPeriod`` list itself; the TOU switch is the
status's. ``live_schedules`` raises ``LiveReadError`` when the status
has TOU on and ``tou`` is None.

To lay a scenario document over the heater as it is now, as
``nwp-cli simulate --scenario ... --live`` does, use ``overlay``:

.. code-block:: python

   built = sim_live.overlay(composed, doc, now=datetime.now(UTC))
   result = sim.simulate(built.scenario, built.params)

Objects merge key by key, and any other value, a list included,
replaces the one under it, so ``{"schema_version": 1, "scenario":
{"settings": {"setpoint_f": 125}}}`` changes the setpoint and keeps
the rest of the heater's settings. ``composed`` or ``doc`` may be None.
Where neither gives one, the start is ``now``, the horizon 24 hours,
and the zone ``tz=``. The parameters are ``params=``, then the
document's, then the heater's, then the 65 gal defaults (with a note in
``built.notes``). ``replace=`` takes parts that stand in whole for the
scenario's, and ``over=`` parts laid on after them. A document that
doesn't make a scenario raises ``ValueError``.

To have the models themselves, read them directly. Each MQTT read is a
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
forecast does better (`Improve accuracy`_).


Work in your units
==================

The simulator itself takes degF and US gallons: its fields end in
``_f`` and ``gallons``. Go through ``sim_adapters`` and you never touch
them; it converts at the boundary, in the library's preferred units
(:doc:`manage-units`):

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
``reasons`` names what it could not model, such as a reservation that
powers the heater off (``reservation_mode_not_modelled``). Each entry in either
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

A heater already in Vacation or Power Off starts no heating. A write
that switches to either, or a reservation that powers the heater off,
is not modelled: it is left out, and ``reasons`` says so (``write_mode_not_modelled``,
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


Watch the tank cool
===================

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

Without more to go on, the answer is the tank's heat as its two probes
place it (``basis`` ``probes``), heating or not. Give it more:

- **A heat book**, if you know the tank is full: quiet since a recovery
  ended, or the heat pump running with the probes within the book's
  band and nothing drawn in its last 15 minutes (``basis`` becomes
  ``energy``):

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
       switch_back_after_minutes=30,
   )
   print(e.reachable, e.unreachable_reason)
   print(e.plan.upper_setpoint_minutes, e.plan.element_kwh)

``reachable`` is False inside a TOU window, where a mode write may not
take, and while heating is disabled. The heater's own marker
(``Settings.hp_upper_on_f``) decides, and an unknown marker counts as
in force. ``setpoint_f=`` projects to another setpoint without moving
that test. To see the whole day with the
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


Check a shower or a bath
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


Improve accuracy
================

Each of these replaces a default with a fact:

**The air ahead of time.** The device reports the air at its intake
now, and only while the compressor runs is that the air the heater
stands in: idle, it reads its own cabinet, about 6 degF warm. Project
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

   if draw_forecast.check_issue(slots, scenario.start, scenario.until,
                                issued_at=issued_at, now=now) is None:
       profile = draw_forecast.draw_profile(slots, scenario.start,
                                            scenario.until)
       loads, withheld = draw_forecast.forecast_loads(
           profile, scenario.start, worst_case=True)
       result = sim.simulate(scenario.model_copy(update={"loads": loads}),
                             params, book=book, withheld_windows=withheld)

``draw_forecast.shower_gal(profile)`` over the next 24 hours is the
long draw the household expects, the rate-weighted mean of the long
draws' volume; pass it on as ``time_to_ready(shower_gal=...,
shower_from_forecast=True)``.

An issue answers only a window its slots cover whole, and only for
36 hours after it was issued (``no_covering_issue``). To replay an
issue on another week, move it with ``draw_forecast.shifted`` and pass
``shift=``.

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

With the heater's values recorded as changes instead (Home Assistant's
entity history, which ``read_heater_history`` reads), book from those,
with the instants the heater was heard from:

.. code-block:: python

   from nwp500 import sim_home_assistant as ha

   history = await ha.read_heater_history(client, entities, start, now)
   book = sa.book_from_changes(
       history.rows,
       history.observed,
       params,
       at=now,
       flow=draws_gpm,        # gal/min, whatever the preferred units
       flow_outages=flow_down,  # when the flow entity was unavailable
       circulation=runs,      # [(start, end), ...], if you circulate
       circulation_flow=pump_flow,  # the loop's gal/min while it runs
   )

``flow`` is the household's draws. If your meter also carries the
circulation's water, separate the household's draws from it yourself
and pass those, with ``CirculationParams.meter_share`` 0, so the book
takes nothing off them again. Clean up the loop's flow before passing it
too (drop readings below the pump's floor, or one taken mid-ramp): while
a run is on, each step takes the last reading in force (a run before
any reading takes ``CirculationParams.flow_gpm``).

Like the history's rows, its ``flow``, ``circulation_flow``, ``inlet``
and ``air`` are changes: each value holds until the next, so a steady
draw is one row and an hour at 0 gal/min none. They are gal/min and °F,
whatever the preferred units. Across a span the heater wasn't heard
from (an outage, or a silence much longer than its usual reporting), or
the flow was unknown (``flow_outages``, from the history's
``outages``), such as a Home Assistant restart's few minutes, the book
holds each value from before it and walks on. The flow holds only
``FLOW_HOLD`` (a minute), as a reading does, and is 0 after: a draw
going in most likely ended within minutes, and holding it would charge
a draw nobody made. ``HomeAssistantBook`` holds the pump's speed across
its outages for ``PUMP_STALE`` (five minutes) the same way. The book is None while
the heater isn't heard now or the flow is unknown now. A record that
keeps no instant for each of the heater's responses passes ``heard=``,
the spans the heater was heard over, and an empty ``observed``: the
book walks across a gap between two spans the same way, and the heater
is heard now only inside a span. With no flow reading in force
at the start of the window it books over, it raises ``ValueError``.
An inlet reading holds except through ``inlet_outages``.

To keep a book current as you walk every few minutes, keep the history
rather than the book. Read only what is new since your last read,
extend what you hold with it, trim it to the book's window, and book
again from memory:

.. code-block:: python

   newer = await ha.read_heater_history(client, entities, last_read, now)
   history = history.extended(newer).since(now - timedelta(hours=72))
   flows = flows.extended(
       await client.read_history([FLOW], last_read, now)
   ).since(now - timedelta(hours=72))
   last_read = now

``HeaterHistory`` and ``History`` both take ``extended`` and ``since``.
A read opens with the value in force at its start; as each value holds
until the next change, that row changes nothing. Where both reads have
a row at one instant, the later read's is kept. ``since`` keeps each
value in force at the cut. 72 hours is ``BookParams.history_h``, the
oldest anchor a book reads.

``sim_home_assistant.HomeAssistantBook`` does all of that from Home
Assistant's entities:

.. code-block:: python

   keeper = ha.HomeAssistantBook(
       client,
       heater_entities,                 # ha.HeaterEntities
       "sensor.hot_water_draw_flow",   # the household's draws
       ha.Entities(
           circulation_speed="sensor.circulation_pump_speed",
           inlet="sensor.cold_supply_temperature",
           demand="binary_sensor.hot_water_demand",
       ),
   )

   await keeper.read(now)       # all 72 h the first time, then what's new
   answer = await hass.async_add_executor_job(keeper.book, now, params)
   readiness = sim.time_to_ready(
       scenario, params, book=answer.booked,
       inlet_measured=answer.inlet_measured,
   )

``read`` reads the history since the last read and holds it; a read
that fails is noted, and the next one reads from where it would have
started. Until then, ``book`` takes the flow as unknown since the last
read that worked, rather than holding its last value, and after a
failed read of the heater it gives no book. An optional
entity whose unit can't be read is left out of the book. With no air
entity, or one that gives no reading, the book takes the heater's own
air reading (``HeaterEntities.ambient``) once its compressor has run 5
minutes, and holds it until the next run, and a note says so. Idle, that
sensor reads the cabinet, about 6 °F warm, so an idle reading is never
taken. Before the first run, and while an air entity that gives readings
is unavailable or reads in a unit the book doesn't read, the book takes
the default air (65 °F). ``book`` books from what it holds, with no
request, so it can run in an executor. ``answer.notes`` say what the book rests on, or why
there is none.

The flow is the household's hot water draws, without the circulation's
water, in gal/min or any unit ``to_gpm`` reads. Say which water its
gallons count with ``flow_volume``:

- ``"delivered"`` (the default): the water at the taps, through the
  mixing valve. The book prices a gallon at the valve's delivery line
  (``DrawParams.delivery_intercept_f`` and ``delivery_slope``), and
  takes only its hot share from the tank.
- ``"tank"``: the tank's own water, as a meter or a draw detector on
  the heater's hot outlet counts it. The book prices a gallon at the
  upper probe less the inlet, and the inlet replaces every gallon.

Read as delivered, a tank-water flow books about a quarter of each
draw's heat too little (a 141 degF tank behind a valve delivering 122
degF), and the book promises hot water that isn't there. The shipped
empty points (``BookParams.empty_btu`` and ``zone_empty_btu``) were
booked as delivered gallons, so with ``"tank"`` refit ``empty_btu`` on
your record (``calibration.empty_point``, below) and keep
``zone_empty_btu`` as far below it; booked as tank water, the same
drawdown leaves less heat at the line. As none of the flow is circulation,
``book`` takes ``CirculationParams.meter_share`` as 0. A flow entity that reports a draw late
reaches the book late: the book holds what the history holds at
``read``. Each of the other entities is optional:
``circulation_speed`` gives the circulation's runs, ``inlet`` the inlet
the book converts at, ``inlet`` with ``demand`` the mains, and ``air``
the air beside the heater.

Without a meter, start one only when you know the tank is full
(``sa.full_tank_book``).

With an inlet probe on the cold supply, convert the book's gallons at
the mains rather than at the probe's own median, which at rest reads
the air around the pipe:

.. code-block:: python

   from nwp500.sim.cold_supply import on_the_mains

   cold = sa.cold_supply(inlet_probe, at=now, draws=draws,
                         circulation=runs)
   book, measured = on_the_mains(book, cold)
   readiness = sim.time_to_ready(scenario, params, book=book,
                                 inlet_measured=measured)

``draws`` are the (start, end) spans the household drew hot water,
without the circulation's water. ``sa.cold_supply`` takes the probe in
the preferred unit. ``sa.cold_supply_f`` takes it in °F and reads no
unit preference, for a caller whose preference may change while it
runs.

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
calibrate. :doc:`calibrate-simulator` does it from the command line
and says which air to give; from Python:

.. code-block:: python

   from datetime import timedelta

   from nwp500.sim import calibration

   history = sa.history(
       recorded,                 # [(instant, DeviceStatus), ...]
       air=air_over_the_record,  # a sensor's, beside the heater
       humidity=humidity,        # %RH; give 50 if you have none
       max_gap=timedelta(minutes=5),  # a longer gap is unobserved
   )
   fitted = calibration.calibrate(history, sa.params(feature),
                                  recovery_air="air_f")
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
  just fitted. ``recovery_air="air_f"`` takes the air over a recovery
  from the sensor's too; the default is the heater's own reading,
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
  cycle counts, the heat its draws and runs took priced in. The flow of
  a circulation can move from run to run; pass
  ``circulation_flow_at=cal.flow_lookup(cal.measure_runs(...))`` and
  each cycle's runs are priced at the flow they ran at.
- **The probes' share of circulation's heat**
  (``DrawParams.ungated_observability``):
  ``cal.fit_ungated_observability(cal.circulation_windows(history,
  runs, params, draws=meter_draws), displaced_gal, flow_gpm)``. It
  works on windows of circulation with no compressor and no unsized
  draw (a NaN gallon count). Fit it at the same ``displaced_gal`` you
  will use (``fit_displaced_gal``): a long run's modelled heat is
  proportional to that volume, so the two are a pair. It needs 20
  windows, and a factor outside 0.05-1 is refused.

A part without the evidence keeps the value it had, and is named in
``cal.params.unfitted``: ``compressor`` (too few recoveries, or a fit
pinned on a bound), ``power``, ``standby`` (no quiet window) or
``gap_tau``. Every answer such a term reaches says so in its
``reasons``: ``physics_uncalibrated`` for a recovery's duration,
``energy_uncalibrated`` for its energy and COP, ``standby_uncalibrated``
for the jacket's loss, and ``tau_gap_prior`` for a gap that draws open.
The base's record of the installation's book, readiness and draw terms
is kept (``default_params`` names all three): they are fitted apart,
from a meter's draws, and once you apply your own fits drop each from
``unfitted`` (``replace(params, unfitted=...)``). A meter's draws
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
   fit = calibration.fit_book_terms(book, book.reanchors(), p, circuit=True)
   p = replace(p, hp_btu_per_h=fit.hp_btu_per_h,
               hp_btu_per_h_per_f=fit.hp_btu_per_h_per_f,
               ua_btu_per_h_f=fit.ua_btu_per_h_f)
   v = fit.book_circuit_gal
   bands = calibration.book_error_bands(book, p, 0.0, v)
   empty, crossings = calibration.empty_point(book, p, 0.0, circuit_gal=v)

The steps read the meter as delivered gallons, as the readiness fit
above does. For a flow that counts tank water, book it with
``flow_volume="tank"`` here, so ``empty`` comes out in that frame, and
set ``zone_empty_btu`` as far below it as the shipped pair are (3,533
BTU).

With ``circuit=True`` the runs are priced at a circuit volume
(``CirculationParams.book_circuit_gal``) fitted in place of a loss per
gallon. ``book_error_btu(book, p, 0.0, v)`` gives the book's
error bands: the 90th percentile of its error pooled over re-anchors an
hour to ``max_anchor_age_h`` apart, and the 18 to 24 h band's past it,
each rounded up to 100 BTU. The bath's volume is yours to set:
measure a bath by filling one to your usual level at the hot side's
meter.

How a draw moves the upper zone is fitted on the record's long draws
too, the book walked continuously over it (``book_walk``):

.. code-block:: python

   walk = calibration.book_walk(book, zone_empty_btu=p.zone_empty_btu)
   draws = calibration.long_draws(walk)
   split = since + (until - since) * 0.7   # the later draws are held out
   mix = calibration.fit_zone_mix(
       calibration.mixing_frame(walk, draws, split=split))

``mix`` is how the upper zone falls through a long draw
(``zone_mix_f_per_gal``, ``zone_mix_gal``). It reports its error on the
training and held-out draws and a day bootstrap's interval. The lower
zone takes each draw's calibrated response (``DrawParams``), with a
book or without one.

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

The mixing fit reads gallons left before ``zone_empty_btu``, so set
that first. The delivered water's lag (one bath's measurement) stays
an installation value.


Fit the elements
================

The element terms (``ElementParams``) come from the heater's raw
change rows (``sim_adapters.record``):

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
``cal.energy_saver_off_deficit(off)`` reduces the off-edges to Energy
Saver's stop short of the setpoint, and
``cal.upper_start_edge(cal.element_runs(grid))`` the runs to how far
below the setpoint the upper element starts.

Plan with the heater profile
============================

A scheduler plans with ``sim.profile.heater_profile(params.tank)``.
It lists the modes and the energy each one uses, the setpoint range
and step, the depletion threshold and the tank's volume, all as the
simulation runs them. ``profile.revision`` changes only when one of
those facts changes, so re-read the profile when the revision moves.
Express a plan as reservation entries (``Commands.reservations``) and
writes (``Commands.writes``).

To keep a ``next_recovery`` answer and reuse it later, age it with
``sim.recovery_as_of(rec, computed_at, now)``. Otherwise its start
comes late and the part of the coast that has already happened is
charged a second time.

Replay a recorded day
=====================

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
       air=air_readings,         # [(instant, value), ...] where it stands
   )
   result = sim.simulate(r.scenario, params)

The tank, what was heating and the settings are the last status at or
before ``at``. When the compressor last stopped and when the tank last
heated come from the record's edges. Every setpoint or mode change
over the span is a write, except the heater's own drop to Heat Pump as
a TOU window opens. The TOU switch's changes are kept too. A write into
Vacation or Power Off cannot be simulated: it is left out whole and
named in ``r.reasons``. The record holds no schedule, so give the
heater's own, read with this library. With ``air``, the air is the
recorded readings as 10-minute means from 6 hours before ``at``, and
``humidity=``
goes with it. Without it, the heater's own reading at ``at`` holds,
and that reads the cabinet, about 6 degF warm, while the compressor is
idle. ``environment=`` replaces either.


Compare with the recorded day
-----------------------------

``sa.observe`` reads the same record for what happened over a
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
element counts only where the heater's power shows it running, by a
reading in the run or one at most a minute before it starts
(``Record.element_power_slack``; a meter reporting less often passes
its own). Power is recorded on change, so a handoff between the
elements at one wattage leaves no new reading. A drop to Heat Pump
within 5 seconds of a TOU window opening is the heater's own, not a
write (``Record.drop_within``, for a slower poll), and the upper start
threshold reads 104.9 degF at rest (``Record.resting_upper_on_f``).
``seen.slots`` are the energy per 10 minutes from the heater's own
power; ``seen.modes`` are the mode in force and whether the heat source
the heater reported showed it in effect, named by a heater profile
(``profile=``, the simulation's own by default; a mode it does not list
has no name) from when its revision took effect (``revision_since=``).
``seen.gaps`` are where a
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

``codec.result_to_document(result)`` writes a result the same
way. The other answers (``time_to_ready``, ``next_recovery``,
``recovery``, ``forecast``, ``active_cycle``, ``element_mode``,
``readiness``, ``standby`` and ``heater_profile``) are documents through
``codec.to_document``:

.. code-block:: python

   doc = codec.to_document(sim.time_to_ready(scenario, params))
   doc["kind"]             # "readiness"
   doc["deliverable_gal"]  # the answer's fields, at the top level

Each document has ``schema_version`` and ``kind``, the answer's type
in snake case (``codec.DOCUMENT_KINDS``). Instants are ISO 8601 strings,
nested answers are objects, and a number that isn't finite is null, so
the document is strict JSON.


See also
========

* :doc:`/explanation/simulator`: the model, and how accurate it is
* :doc:`/reference/simulator-inputs`: every input, its unit, and where
  it comes from
* :doc:`/reference/python_api/sim`: the API
