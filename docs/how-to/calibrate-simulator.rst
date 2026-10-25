======================================
Calibrate the Simulator to Your Heater
======================================

The simulator's default parameters are one NWP500-65's, fitted at one
installation. Record what your own heater reports for a few weeks and
fit its standby loss, its compressor and its power to that record.

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

Record through quiet nights and full recoveries. The standby fit needs
windows of 3 hours or more with no heating and no hot water in use. The
compressor fit needs at least 5 recoveries that reached their target,
and holds out the latest fifth once there are 10. The power fits need
10 compressor cycles.


Record the air beside the heater
================================

The standby loss is the heat the tank loses to the air it stands in,
so the fit needs that air over the whole record. The heater does not
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
  60-day record only the last 10 days have the air, and the standby
  loss is fitted from those alone. For the whole record, raise the
  recorder's ``purge_keep_days`` to cover it before you start
  recording, or give the air another way (``--air``). Where the
  draws' or the circulation's history doesn't cover the whole record,
  the heater's own flag is used instead. ``--air``, ``--ambient`` and
  ``--humidity`` override the sources.

Without the air, the command fits the standby loss on the heater's own
reading, taken once the compressor has run 5 minutes and drawn straight
from one run's reading to the next across the idle span between them.
Only quiet windows with a run within 6 hours of both ends are fitted:
they fall mostly overnight, and a reading held from the day's last run
would read the night warm. Those windows span too narrow a range of
tank-to-air difference to fit the loss law's shape, so only its level is
fitted, on the base's exponent. A note says how many windows qualified
and what share of the quiet hours they hold. Expect the loss to read
somewhat high: at one installation, against a sensor beside the heater,
it read about 12 % high, as the night air dips below the line between
an evening run and a morning one, and the running reading is itself a
little warm. A sensor beside the heater (``--air``) avoids both.
With no such reading at all, the standby loss keeps the base's value
and the report says so. When you give the air, the recoveries use it
too; without it, they use the heater's own reading while the compressor
runs.

``--humidity`` takes the same kind of file, in %RH, for the
evaporator; without it the command gives the fits 50 %.


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
   * - Standby loss, its exponent, the bottom loss and its gate
     - Quiet windows of 3 h or more, starting 45 minutes after any
       heating or hot water in use, that open with a gap of 10 °F or
       less between the probes. A window counts only if its fit tracks
       the probes within 2 °F. Each window's upper and lower probe are
       walked from its start as the simulation walks them, and the
       terms are fitted to where the probes ended. The exponent is
       fitted only when the windows span two 20 °F bands of tank-to-air
       difference; it is held at 0 (a constant loss) otherwise. The
       bottom loss needs 10 windows that open with a gap of 1 °F or
       more; with fewer it is 0, and the loss is the jacket law
       alone.
   * - Zone gap time constant
     - How fast the upper and lower probes' gap closes over quiet
       windows; it needs 20 windows that open with a gap of 2 °F or
       more. The bottom loss opens the gaps it relaxes, so the two are
       fitted in turn until the constant settles.
   * - Compressor constant
     - Heat-pump recoveries that reached their target, against the loss
       just fitted. The error is the mean absolute error of the
       recovery durations, in minutes, also on the held-out recoveries.
       A fit pinned on a bound is reported and not applied.
   * - Input power scale, COP scale, start-up energy, COP lift
     - The heater's own power readings over each compressor cycle,
       against the compressor just fitted. The COP uses only cycles
       with no hot water in use from 30 minutes before them to their
       end.

``Unfitted`` lists every term that kept the base's value. The answers
those terms reach say so in their ``reasons`` (for example
``standby_uncalibrated``). The ``book``, ``readiness`` and ``draw``
terms are always listed, because they are fitted only from a hot-water
meter's draws, which the command does not take (see below).


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
standby loss is then fitted on the heater's own reading between runs,
and ``done.air`` is ``"heater"``. Without ``humidity`` the fits
get 50 %. An input it cannot use raises ``CalibrationInputError``.

On a desktop computer, 60 days of statuses (about 540,000) took about
40 seconds to read and 10 to fit, in about 150 MB.

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

- the standby loss, its exponent, the bottom loss and its gate: its
  quiet windows, scored on the probes' error in each window's fall,
  °F/h;
- the zone gap time constant: its windows that open a gap, judged
  before the standby loss, which is then fitted and scored on the
  constant kept;
- the compressor constant: its reached recoveries;
- the power scale: the metered compressor cycles it can use;
- the COP terms: the cycles the COP fit can use (without a meter of
  draws, those no water was drawn around).

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
cycle's draws took. The fits for the readiness terms, the heat book,
the draw response and the elements also run there: see "Improve
accuracy" and "Fit the elements" in :doc:`simulate-heater`.


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
Assistant's own queries, and 11 to fit, in about 180 MB.


Fit the heat book
=================

The heat book (``book_from_changes``) counts the heat the tank holds
from the compressor's heat rate and its slope with the air, the standby
UA, and, with a circulation pump, what each run takes: its first
gallons, up to the book's circuit volume
(``CirculationParams.book_circuit_gal``), each at the tank's upper
probe less the air, the loop having cooled to the air since the last
run. ``fit_book`` fits them
together from the heater's history, the household's draws, and the
pump's runs with the loop's flow. The draws and the loop's flow are
yours to give, apart from each other: the fit takes every gallon of the
draws as hot water drawn, and each run at the loop's flow.

.. code-block:: python

   from dataclasses import replace

   from nwp500 import sim_adapters as sa

   async with ha.HomeAssistantClient(url, token) as client:
       history = await ha.read_heater_history(client, entities, start, end)
       record = await ha.record_inputs(client, ha.Entities(air=..., humidity=...),
                                       start, end)
   params = sim_calibrate.calibrate_changes(
       history.rows, history.observed, record=record, notes=history.notes
   ).calibration.params
   fit = sim_calibrate.fit_book(
       history.rows, history.observed, params,
       flow=draws, runs=runs, circulation_flow=loop_flow,
       air=record.air or (),
   )
   params = replace(params, book=fit.book)

``draws`` and ``loop_flow`` are (instant, gal/min) readings and ``runs``
the pump's (start, end) spans; ``record_inputs``' air is °F, as the fit
takes it. ``fit.book_circuit_gal`` is the circuit volume for your
``CirculationParams`` (None without a loop).

The fit reads the pairs of quiet full tanks up to
``book.max_anchor_age_h`` apart, and fits each term for the least mean
absolute error between the book and the probes at the second of each
pair:

- **The book's terms:** the compressor's heat rate and slope, and the
  standby UA, on every pair. A term the pairs can't tell apart from
  the others (the slope, with the air never off one temperature) stays
  at ``params.book``. The rest of the book (its draw line, the anchors'
  age, the valve's line) is ``params``'.
- **The book's circuit volume:** on 10 pairs with a run between, with
  the book's terms fitted at each volume tried. Runs closer than
  ``run_gap_min`` are one run. It is an effective volume, smaller than
  the loop's own (``displaced_gal``): at one installation 1.4 gal
  against 6.4. Fit and keep them apart. Its runs are priced as cooled
  to the air: at that installation, pricing them at the loop's return
  (``fit_return``: the pipe resting 7.84 degF over the air and cooling
  on 0.464 h) booked the 87 pairs the fit takes no better, a mean
  absolute error of 17,018 BTU against 16,991, on 109 pairs with 51
  runs. With fewer pairs, the loop is
  priced as ``params.circulation`` prices it, and without one, the
  pairs with a run are left out. A pair with a run that has no flow
  reading is left out.

The fit needs 10 pairs. It holds out the latest fifth and replaces the
base only when it books them no worse. A term on its bound
(``sim.calibration.BOOK_TERM_BOUNDS``) is no fit: the book misses
something between those anchors that the term is standing in for. The
circuit volume on its bound (``sim.calibration.BOOK_CIRCUIT_GAL_BOUNDS``)
leaves the loop at the base's; any other term on its bound keeps the
base. ``fit.kept`` says which it
kept and ``fit.why`` why. A span the heater wasn't heard from, a probe
read nothing, or the draws were silent over an hour, breaks the book.

A pair with a run needs a quiet full tank on each side of it, so they
come slowly. With a pump running about once a day, one installation had
5 in 14 days and 19 in 42: fit on four weeks or more, and raise Home
Assistant's ``purge_keep_days`` to keep them.

Book with the same inputs. Runs are priced at the circuit volume, in a
``CirculationParams`` of your installation's with ``meter_share`` 0,
since the draws hold none of the loop's water; without one, they can't
be booked. ``sa.run_readings`` gives the book each run's flow as
the fit takes it: its own readings, the first from its start, and none
read outside the runs.

.. code-block:: python

   from nwp500.sim.params import CirculationParams

   book = None
   volume = fit.book_circuit_gal
   if volume is not None or not runs:
       loop = None
       if volume is not None:
           loop = CirculationParams(
               displaced_gal=..., flow_gpm=..., loss_btu_per_gal=...,
               book_circuit_gal=volume, meter_share=0.0,
           )
       book = sa.book_from_changes(
           history.rows, history.observed, replace(params, circulation=loop),
           at=end, flow=draws, circulation=runs,
           circulation_flow=sa.run_readings(runs, loop_flow),
           air=record.air or (),
       )


Limitations
===========

- **The draws.** The heater reports no draw volume, and in recorded
  statuses its inlet and flow readings read 0. The draw terms
  (``book``, ``readiness``, ``draw``) need a hot-water meter and an
  inlet probe.
- **Circulation the heater does not run.** The quiet test is the
  heater's own "hot water in use" flag, which also fires on
  circulation. A loop's heat that does not trip the flag is invisible
  to the heater and lands in the standby loss. From Python, pass the
  circulation's runs (``record=`` or ``sa.history(...,
  circulating=...)``) to keep them out of the quiet windows.


See also
========

* :doc:`simulate-heater`: run the simulator with your parameters
* :doc:`/reference/python_api/sim`: ``sim_calibrate``,
  ``sim.calibration``, ``sim_adapters.history``,
  ``sim_adapters.change_history``, ``status_history`` and
  ``sim_home_assistant.read_heater_history``
