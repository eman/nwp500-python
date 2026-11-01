======================================
Calibrate the Simulator to Your Heater
======================================

The simulator's default parameters are one NWP500-65's, fitted at one
installation. Record what your own heater reports for a few weeks and
fit its tank, its compressor and its power to that record.

.. contents::
   :local:
   :depth: 1


Record the history
==================

``nwp-cli simulate record`` appends every status the heater sends to a
file until you stop it (Ctrl+C): the answers to the status requests it
makes every 30 seconds (``--every``), and the statuses the heater sends
between them. One heater sent about 370 an hour, about half of them
identical to the one before. A line is about 2.3 kB, so a day of
recording is about 20 MB, or 0.2 MB gzipped. The command needs the
``cli`` extra and no other:

.. code-block:: bash

   nwp-cli simulate record history.jsonl
   nwp-cli simulate record history.jsonl --every 60

Each line is one status, as JSON: the instant it arrived and the
status payload as the heater sent it:

.. code-block:: json

   {"t": "2026-10-18T23:09:10.298+00:00", "status": {"dhwUse": 1, "...": 0}}

Stopping and starting again appends to the same file, so the record
can have gaps. The heater may have heated or delivered water during a
gap, so ``calibrate`` takes any spacing between statuses of more than
4 times the record's usual spacing (and at least 5 minutes) as
unobserved. No quiet window and no recovery spans such a gap, and the
report counts them. The identical statuses are what show the heater was
observed between changes, so keep them.

Write the file any other way you like (an MQTT callback, an export
from a home-automation recorder) as long as each line has this shape:
``nwp500.status_history.line(instant, raw_status)`` writes one.
``status_history.read(lines)`` reads them back as
``(instant, DeviceStatus)`` pairs, and ``status_history.iter_read(lines)``
yields them one at a time, for a long recording.

Record through quiet nights and full recoveries. The tank's fit needs
10 windows of 3 hours or more with no heating and no hot water in use
(a meter's draws count toward them, from Python), and places the
compressor's heat once it also has 5 recoveries that reached their
target. The compressor fit needs at least 5 recoveries that reached their target,
and holds out the latest fifth once there are 10. The power fits need
10 compressor cycles.


Record the air beside the heater
================================

The tank loses heat to the air it stands in, so the tank's fit needs
that air over the whole record. The heater does not
read it while idle: its sensor sits at the heat pump's intake, and it
reads the air the heater stands in only while the evaporator fan runs.
Idle, it reads the cabinet, about 6 °F warm. So give one of these:

- **A sensor beside the heater:** a CSV file of its readings, an ISO
  8601 instant with its UTC offset and a temperature in your preferred
  unit on each row (a header row is skipped):

  .. code-block:: text

     time,temperature
     2026-10-18T00:00:00-07:00,61.2
     2026-10-18T00:05:00-07:00,61.0

- **A constant,** for a heater in conditioned space that holds one
  temperature.

- **Home Assistant:** ``--sources FILE``, the same sources file as
  ``simulate run`` takes (:doc:`simulate-heater`). The command reads the
  air beside the heater and its humidity over the record. It also reads
  the household's draws (the ``demand`` entity) and the circulation's
  runs, which make the quiet
  test exact: the heater's own "hot water in use" flag also fires on
  circulation. The air is used only over the span its history covers,
  and not while its sensor was ``unavailable``; the humidity takes the
  50 % default outside that span, and the report says how much that
  is. Home Assistant keeps 10 days of history by default, so of a
  60-day record only the last 10 days have the air, and the tank is
  fitted on those alone. For the whole record, raise the
  recorder's ``purge_keep_days`` to cover it before you start
  recording, or give the air another way (``--air``). Where the
  draws' or the circulation's history doesn't cover the whole record,
  the heater's own flag is used instead. ``--air``, ``--ambient`` and
  ``--humidity`` override the sources.

Without the air, the command fits the tank on the heater's own reading
while its compressor is idle. That reading is the cabinet's, and 6.2
degF is taken off it for the cabinet's warmth
(``sim_adapters.IDLE_CABINET_WARM_F``). A quiet window the heater wasn't
heard from throughout is left out, and a note says how many windows
were read and what share of the quiet hours they hold. With no such
reading at all, the tank keeps the base's terms and the report says
so. When you give the air, the recoveries use it
too; without it, they use the heater's own reading while the compressor
runs.

``--humidity`` takes the same kind of file, in %RH. The heat pump's
fit does not use it; it is kept for a recovery model.


Calibrate
=========

``nwp-cli simulate calibrate`` needs the ``cli`` and ``sim`` extras. It
reads the history and prints what each fit found. With ``-o`` it also
writes the fitted parameters, as a ``HeaterParams`` document:

.. code-block:: bash

   nwp-cli simulate calibrate history.jsonl --air air.csv -o params.json
   nwp-cli simulate calibrate history.jsonl --ambient 68 -o params.json
   nwp-cli simulate calibrate history.jsonl --sources sources.toml -o params.json
   nwp-cli simulate run --params params.json

It refits the 65 gal defaults. For another tank size, start from that
size's parameters with ``--params``:

.. code-block:: python

   import json
   from nwp500 import sim
   from nwp500.sim.params import params_to_document

   with open("base.json", "w") as f:
       json.dump(params_to_document(sim.default_params(3)), f)  # 80 gal

The report has a row for each term. Each row gives the term's value,
the evidence it was fitted from and its error, and whether it was
fitted or kept the base's value, and why:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Term
     - Fitted from
   * - The tank: its sides', bottom's and top's losses, the column's
       conductance, each probe's height and spread, the lower probe's
       offset, the inlet's mixing, and where the condenser heats
     - Quiet windows of 3 h or more, starting 45 minutes after any
       heating or hot water in use, and, from Python, a hot-water
       meter's sized draws, each followed for an hour; it needs 10. With
       5 recoveries that reached their target, it fits where the
       condenser heats on those too. Each event's tank is replayed from
       the record before it, and walked from its start as the
       simulation walks it. The terms are fitted together for the least
       error in both probes every 10 minutes; the error is that RMS
       error before and after the fit, °F. A term on its bound says
       so.
   * - Heat at 65 °F air, 120 °F water, and per °F of each
     - Draw-free climbs of 20 minutes or more with the tank mixed, the
       heat the tank kept plus the loss just fitted; it needs 10. The
       error is the RMS heat error, BTU/h. Not applied when, with the
       power, it claims more than a heat pump can.
   * - Power at 65 °F air, 120 °F water, and per °F of each
     - The heater's own power readings in 10-minute blocks of the
       climbs, each at the condenser's water on the record's replay
       (the lower probe's without the air to replay with); it needs
       30. The error is the RMS power error, W.
   * - Run-on overshoot
     - The lower probe past the target at the stop: the median of 5
       draw-free runs or more.

``Unfitted`` lists every term that kept the base's value. The answers
those terms reach say so in their ``reasons`` (for example
``tank_uncalibrated``). The ``draw`` terms are always listed, because
they are fitted only from a hot-water meter's draws, which the command
does not take (see below).


Score on held-out days
----------------------

Each fit's error in the report is on its own evidence, so it cannot say
whether the parameters as a whole predict the tank better.
``--holdout-from`` fits on the history before a date and scores the
base and the fit on the recorded events after it:

.. code-block:: bash

   nwp-cli simulate calibrate history.jsonl --ambient 68 --holdout-from 2026-10-01

The events are taken from the record without any model, so each set of
parameters is scored on the same events, each started from the layers
the record's replay leaves at its start (given the air; without it,
from the probes). Each recovery that reached its
target with no water in use is walked from its recorded start (one with
a draw needs a meter's draws, from Python below), each change of the
setpoint inside it walked as a write at its instant, as the heater
was told it: ``recovery_minutes_abs`` is
how far its predicted run is from the recorded one, and
``recovery_energy_abs_pct`` how far its electricity is from the
meter's. Each quiet window is coasted from its start:
``standby_upper_rmse_f`` and ``standby_lower_rmse_f`` are each probe's
error over it, every 10 minutes. Each metric gives its number of
events and a 90 % interval from resampling whole local days. Hold out at
least a week, or the intervals are wide.

From Python, ``nwp500.sim_score`` scores any history the fits read
(``sim_calibrate.prepare`` or ``prepare_changes``), and takes a hot
water meter's draws for the draw and deliverable-gallon metrics. Give
the fit the draws before the split, and the score the record
(``tank_fit.tank_record``) to start each event from its replay. The
record times each draw by the history's draw detector
(``TankRecord.draw_seconds``). The score walks one the detector times
at the parameters' ``DrawParams.undiluted_gpm`` or faster over that
time, the tank's water whole. It walks every other draw at its onset,
where the meter sizes it: timing them all scored worse
(:doc:`../explanation/simulator-tried`).

.. code-block:: python

   import json

   from nwp500 import sim_calibrate, sim_score
   from nwp500.sim import tank_fit

   ready = sim_calibrate.prepare_changes(rows, observed, record=record)
   start = sim_score.holdout_start(ready.frame.index, tz="America/Los_Angeles")
   done = sim_calibrate.calibrate_changes(
       rows.until(start),
       [t for t in observed if t < start],
       record=record,
       draws=[d for d in draws if d[0] < start],
   )
   found = sim_score.events(ready, draws=draws, flow=flow, since=start)
   score = sim_score.score(
       found,
       done.calibration.params,
       tz="America/Los_Angeles",
       record=tank_fit.tank_record(ready.frame, draws),
   )
   print(json.dumps(score.document(), indent=2))

``sim_score.compare`` reads two score documents and says, for each
metric, whether the second's interval clears the first's value.

Whole days
----------

A scheduler weighs one day's plan against another's, so the score can
also walk whole local days from their start, as the heater was told
over them, and set what it predicts beside what the heater did:
``sim_score.day_events``. It needs what the fits' frame does not carry,
the heater's record (``sim.record.Record``): the mode, the setpoint,
the lower probe's start and stop thresholds, the upper's start
threshold (whose rise marks a TOU window in force), the TOU switch,
what ran and the heater's power. A day is scored only when what ran,
the power, the mode and the setpoint have no gap over it, the
thresholds and the TOU switch are known at its start, the lower stop
threshold sits on the setpoint throughout (the walk heats a recovery
to the setpoint), and the heater, the air and the recorder were heard
throughout it. Each day starts
from the layers its replay leaves and is walked with the recorded
setpoint and mode writes, the TOU windows the heater marked, the
metered draws, the circulation and the air:

.. code-block:: python

   from dataclasses import replace

   from nwp500.sim.record import Record

   heater = Record(compressor=..., upper_element=..., lower_element=...,
                   power_w=..., mode=..., setpoint_f=...,
                   upper_f=..., lower_f=..., hp_lower_on_f=...,
                   hp_lower_off_f=..., hp_upper_on_f=..., tou=...)
   tank = tank_fit.tank_record(ready.frame, draws)
   days = sim_score.day_events(
       ready, heater, tank, tz="America/Los_Angeles", since=start
   )
   score = sim_score.score(
       replace(found, days=days), done.calibration.params,
       tz="America/Los_Angeles", record=tank,
   )

The day metrics are the day's electricity against the meter's
(``day_energy_abs_pct``, ``_bias_pct``), how much of it fell in another
hour than the meter put it in, whatever the total
(``day_energy_misplaced_share``), how often two days are ordered by
their electricity as the meter orders them (``day_energy_concordance``),
the compressor's starts (``day_compressor_starts_bias``, the share of
a day's recorded starts a prediction places within 30 minutes,
``_placed_share``, and each day's recorded starts no prediction places,
``_missed``, and predictions that place none, ``_false``), the
elements' (``day_element_starts_bias``), the upper probe's lowest over
the day (``day_min_upper_abs_f``, ``_bias_f``) and whether either side
took it below the line (``day_line_disagree_share``), and the probes'
mean at the day's end (``day_end_mean_abs_f``).

Score a change to the simulator
-------------------------------

A change to the simulator's physics or its defaults is scored on one
NWP500-65's record, the same way each time, so its score can be set
beside the last:

- the record from 2026-04-16, when its draw detector starts, to
  2026-10-26 22:00 UTC, pinned so each score has the same events;
- fitted before 2026-09-18 07:00 UTC and scored on the events after,
  the fit given the draws before the split and the score the record's
  replay, as above;
- from the site's installation: the defaults with its mains, its
  circulation and a mixing valve at the default delivery.

.. code-block:: python

   from dataclasses import replace

   from nwp500.sim import default_params
   from nwp500.sim.defaults import site_example_params, with_valve
   from nwp500.sim.physics.draw import (
       DEFAULT_TMV_DELIVERY_INTERCEPT_F,
       DEFAULT_TMV_DELIVERY_SLOPE,
   )

   base = default_params()
   site = site_example_params()
   mains = replace(
       base.draw,
       inlet_temp_f=site.draw.inlet_temp_f,
       inlet_from_probe=site.draw.inlet_from_probe,
       climate_f=site.draw.climate_f,
   )
   params = with_valve(
       replace(base, draw=mains, circulation=site.circulation),
       (DEFAULT_TMV_DELIVERY_INTERCEPT_F, DEFAULT_TMV_DELIVERY_SLOPE),
   )
   done = sim_calibrate.calibrate_changes(..., params=params)

Score the code before the change the same way, and set the two side by
side: ``sim_score.compare(before, after)`` says which metrics moved
past their intervals. A figure in these pages was measured on the model
of its day, so it is not a baseline for a new change. The installation
matters to the score: with no circulation terms the replay that starts
each event leaves out the record's pump runs, and the recoveries read
further from their measured durations, so both sides are scored from
the same installation. A change tried and not kept goes in
:doc:`/explanation/simulator-tried`.


From Python
===========

``nwp500.sim_calibrate.calibrate`` does what the command does, and
``report`` gives the command's rows as ``Term`` values. It takes the
statuses one at a time, so a recording kept as a file per day can be
read in order without holding every status:

.. code-block:: python

   from pathlib import Path

   from nwp500 import sim, sim_calibrate, status_history

   def recorded(days):
       for day in days:
           with day.open(encoding="utf-8") as f:
               yield from status_history.iter_read(f)

   done = sim_calibrate.calibrate(
       recorded(sorted(Path("history").glob("*.jsonl"))),
       air=air_readings,            # [(instant, temperature), ...]
       humidity=humidity_readings,  # [(instant, %RH), ...]
       params=sim.default_params(),  # or your own HeaterParams
   )
   params = done.calibration.params
   for term in sim_calibrate.report(done):
       print(term.name, term.value, "fitted" if term.fitted else term.why)

Give ``ambient`` instead of ``air`` for a constant, or neither: the
tank is then fitted on the heater's idle reading less its cabinet's
warmth (above), and ``done.air`` is ``"heater"``. Without ``humidity``
the fits get 50 %. An input it cannot use raises
``CalibrationInputError``.

A hot-water meter's draws, ``draws=[(onset, gallons), ...]``, fit the
tank on each draw too. The tank's fit walks every event for each of up
to 300 trials (``TANK_EVALUATIONS``); ``map_=`` spreads them over a
pool, as the command does over one process per core:

.. code-block:: python

   import functools
   from concurrent.futures import ProcessPoolExecutor

   with ProcessPoolExecutor() as pool:
       done = sim_calibrate.calibrate(
           recorded(days), air=air_readings, draws=meter_draws,
           map_=functools.partial(pool.map, chunksize=8),
       )

On a desktop computer, 60 days of statuses (about 540,000) took about
40 seconds to read, in about 150 MB. The tank's fit takes longest: on
one installation's 155 days (208 quiet windows, 208 metered draws and
91 recoveries) it took about 6 minutes from the priors over 8
processes, under 2 from its own earlier fit.

Calibrate in an application
---------------------------

An application that records the heater itself, such as a Home
Assistant integration, can calibrate the same way:

1. Write each status it receives with ``status_history.line``, a file
   per UTC day, and keep as many days as the fit should cover.
2. Read the air beside the heater and its humidity over the same span
   with ``sim_home_assistant.record_inputs(client, entities, start,
   end)``, and pass the result as ``record=``. It also brings the
   household's draws and the circulation's runs. Any client with the same
   ``read_history`` as ``HomeAssistantClient`` works. The recorder's
   retention limits the air, as above.
3. Call ``sim_calibrate.calibrate`` in a worker thread. It takes the
   gaps from the statuses' own spacing: a span longer than 4 times
   their usual spacing, and at least 5 minutes, is unobserved.
4. Store ``params_to_document(done.calibration.params)``, and show the
   ``report(done)`` rows and ``done.notes``.

Refine an existing fit
----------------------

A fit made on months of history should not give way to one made on the
last ten days unless the new one predicts better. Pass the existing
fit as ``params`` with ``keep_better=True``:

.. code-block:: python

   done = sim_calibrate.calibrate(
       recorded(days), ambient=65.0, params=existing, keep_better=True
   )
   for j in done.judged:
       print(j.group, j.kept, j.base_error, j.refit_error, j.why)

Each group of terms holds out its latest evidence from its refit:

- the tank: its quiet windows, draws and recoveries together, scored
  on both probes' RMS error, °F;
- the heat's map: its climbs, scored on the RMS heat error, judged
  with the base's power;
- the power's map: its metered blocks (a run's blocks on one side),
  scored on the RMS power error, judged with the heat kept;
- the run-on: its runs, on the overshoot's mean absolute error.

Once a group has 10 items, the latest fifth (at least 2) is held out.
The refit replaces the existing values only where it scores better on
them, by the error its own fit minimizes. With fewer items the existing
values stay. The terms in a group are kept or replaced together, and the
report's reasons say which, with both scores.
``sim_calibrate.score(done, params)`` gives those errors for any
parameters.

Use it over a fit of this heater. The defaults are another heater's fit,
and ``keep_better`` keeps them wherever there is too little evidence to
judge by. A group the existing fit lists as unfitted takes its refit, as
without ``keep_better``.

``sim.calibration.calibrate`` underneath takes the frame
``sim_adapters.history`` builds; ``sim_adapters.add_inputs`` adds the
air, the humidity, the household's draws and the circulation's runs to it.
From there you can also give the draws that price the heat each
cycle's draws took. The fits for the draw response, the circulation
and the elements also run there: see "Improve accuracy" and "Fit the
elements" in :doc:`simulate-heater`.


Calibrate from Home Assistant's history
=======================================

A heater whose integration writes its values to Home Assistant can be
calibrated from that history, with no recording of its statuses. Home
Assistant keeps each entity's changes, and a value that holds writes
none, so the history also needs an entity that changes every time the
heater answers, such as the integration's last response time. Its
changes are when the heater was heard from; a silence between them
longer than 4 times their usual spacing (and at least 5 minutes) is
unobserved, as a gap between statuses is.

.. code-block:: python

   from datetime import UTC, datetime, timedelta

   from nwp500 import sim_calibrate
   from nwp500 import sim_home_assistant as ha

   entities = ha.HeaterEntities(
       heard="sensor.water_heater_last_mqtt_response",
       upper="sensor.water_heater_tank_upper_temperature",
       lower="sensor.water_heater_tank_lower_temperature",
       compressor="binary_sensor.water_heater_compressor_running",
       upper_element="binary_sensor.water_heater_upper_element",
       lower_element="binary_sensor.water_heater_lower_element",
       heat_source="sensor.water_heater_current_heat_source",
       dhw_in_use="binary_sensor.water_heater_dhw_in_use",
       target="sensor.water_heater_hp_lower_off_temperature",
       operation_mode="sensor.water_heater_current_operation_mode",
       error_code="sensor.water_heater_error_code",
       power="sensor.water_heater_current_power",
       energy_to_setpoint="sensor.water_heater_energy_to_setpoint",
       ambient="sensor.water_heater_ambient_temperature",
   )
   end = datetime.now(UTC)
   start = end - timedelta(days=60)
   async with ha.HomeAssistantClient(url, token) as client:
       history = await ha.read_heater_history(client, entities, start, end)
       record = await ha.record_inputs(client, ha.Entities(air=..., humidity=...),
                                       start, end)
   done = sim_calibrate.calibrate_changes(
       history.rows, history.observed, record=record, notes=history.notes
   )

Use your own entity ids. Only ``heard`` and the two probes are needed;
leave out what your installation does not record. ``read_heater_history``:

- reads a day at a time, so the heartbeat's rows are never all held as
  Home Assistant gives them;
- takes each number from the unit it was recorded in (°F, °C or K; W or
  kW; Wh or kWh), ``on`` and ``off`` from the binary sensors, and the
  heat source, operation mode and error code by their enum names
  (``HeatSource``, ``CurrentOperationMode``, ``ErrorCode``);
- takes ``unavailable`` or ``unknown`` on any of the entities as an
  outage of the heater, unobserved (an enum's own ``UNKNOWN`` is a
  value);
- takes the heat source as the compressor's state where no compressor
  entity is given;
- notes a value it could not read, and an entity whose history starts
  after ``start``.

A recovery is timed against the air, so the compressor and power fits
need an air temperature over each compressor run: the air beside the
heater (``record=``, ``air`` or ``ambient``), or the heater's own reading
(``ambient`` in ``HeaterEntities``). Runs without one are no recovery,
and the report says how many there were.

Give ``anti_legionella`` where it is recorded. Without it an
anti-legionella cycle is not kept out of the recoveries, and the notes
say so.

Home Assistant keeps 10 days of history by default, so ``start`` reaches
back only that far unless the recorder's ``purge_keep_days`` is raised
to cover the record you want to fit. The same is true of the air.

Rows from another store of the same history (an export, say) go in as
``sim_adapters.ChangeRows``, each value's changes as ``(instant,
value)`` pairs, with the instants heard from:
``sim_calibrate.calibrate_changes(rows, observed, ...)``.

On a desktop computer, 60 days with a heartbeat every 10 seconds
(about 550,000 rows) took about 13 seconds to read, not counting Home
Assistant's own queries, in about 180 MB; the fit takes as long as
above.


Start from the tank's layers
============================

With the parameters fitted, the tank's layers now
(``layers_from_changes``) are the heater's history replayed over the
last 24 hours (``sim.history.REPLAY``): the compressor's and the
elements' runs, the household's draws and, with a circulation pump, its
runs, walked through the tank and corrected to the probes as they were
read. The draws and the loop's flow are yours to give, apart from each
other: the replay takes every gallon of the draws as hot water drawn,
and each run at the loop's flow. Runs are priced in a
``CirculationParams`` of your installation's with ``meter_share`` 0,
since the draws hold none of the loop's water; without one, one
installation's are taken and a note says so. ``sa.run_readings`` gives
each run's flow: its own readings, the first from its start, and none
read outside the runs.

.. code-block:: python

   from dataclasses import replace

   from nwp500 import sim_adapters as sa
   from nwp500.sim.params import CirculationParams

   async with ha.HomeAssistantClient(url, token) as client:
       history = await ha.read_heater_history(client, entities, start, end)
       record = await ha.record_inputs(client, ha.Entities(air=..., humidity=...),
                                       start, end)
   params = sim_calibrate.calibrate_changes(
       history.rows, history.observed, record=record, notes=history.notes
   ).calibration.params
   loop = CirculationParams(displaced_gal=..., flow_gpm=..., meter_share=0.0)
   layers = sa.layers_from_changes(
       history.rows, history.observed, replace(params, circulation=loop),
       at=end, flow=draws, circulation=runs,
       circulation_flow=sa.run_readings(runs, loop_flow),
       air=record.air or (),
   )

``draws`` and ``loop_flow`` are (instant, gal/min) readings and ``runs``
the pump's (start, end) spans; ``record_inputs``' air is °F, as the
replay takes it. Give the layers as the scenario's
``HeaterState.layers_f``: the simulation starts from them, and the
deliverable gallons read them. None, when the heater isn't heard at
``end`` or the flow is unknown then, starts it from the two probes.


Limitations
===========

- **The draws.** The heater reports no draw volume, and in recorded
  statuses its inlet and flow readings read 0. The draw terms
  (``draw``) and the tank's layers need a hot-water meter, and the
  draws' mains an inlet probe.
- **Circulation the heater does not run.** The quiet test is the
  heater's own "hot water in use" flag, which also fires on
  circulation. A loop's heat that does not trip the flag is invisible
  to the heater and lands in the tank's losses. From Python, pass the
  circulation's runs (``record=`` or ``sa.history(...,
  circulating=...)``) to keep them out of the quiet windows.


See also
========

* :doc:`simulate-heater`: run the simulator with your parameters
* :doc:`/reference/python_api/sim`: ``sim_calibrate``,
  ``sim.calibration``, ``sim_adapters.history``,
  ``sim_adapters.change_history``, ``status_history`` and
  ``sim_home_assistant.read_heater_history``
