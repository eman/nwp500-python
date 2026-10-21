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
  the meter's draws and the circulation's runs, which make the quiet
  test exact: the heater's own "hot water in use" flag also fires on
  circulation. The air is used only over the span its history covers,
  and not while its sensor was ``unavailable``; the humidity takes the
  50 % default outside that span, and the report says how much that
  is. Home Assistant keeps 10 days of history by default, so of a
  60-day record only the last 10 days have the air, and the standby
  loss is fitted from those alone. For the whole record, raise the
  recorder's ``purge_keep_days`` to cover it before you start
  recording, or give the air another way (``--air``). Where the
  meter's or the circulation's history doesn't cover the whole record,
  the heater's own flag is used instead. ``--air``, ``--ambient`` and
  ``--humidity`` override the sources.

Without the air, the standby loss keeps the base's value and the report
says so. When you give the air, the recoveries use it too; without it,
they use the heater's own reading while the compressor runs.

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
   * - Standby loss and its exponent
     - Quiet windows of 3 h or more, starting 45 minutes after any
       heating or hot water in use. A window counts only if its fit
       tracks the probes within 2 °F. The exponent is fitted only when
       the windows span two 20 °F bands of tank-to-air difference; it
       is held at 0 (a constant loss) otherwise.
   * - Zone gap time constant
     - How fast the upper and lower probes' gap closes over quiet
       windows; it needs 20 windows that open with a gap of 2 °F or
       more.
   * - Compressor constant, evaporator approach
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
standby loss then keeps the base's value. Without ``humidity`` the fits
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
   meter's draws and the circulation's runs. Any client with the same
   ``read_history`` as ``HomeAssistantClient`` works. The recorder's
   retention limits the air, as above.
3. Call ``sim_calibrate.calibrate`` in a worker thread. It takes the
   gaps from the statuses' own spacing: a span longer than 4 times
   their usual spacing, and at least 5 minutes, is unobserved.
4. Store ``params_to_document(done.calibration.params)``, and show the
   ``report(done)`` rows and ``done.notes``.

``sim.calibration.calibrate`` underneath takes the frame
``sim_adapters.history`` builds; ``sim_adapters.add_inputs`` adds the
air, the humidity, a meter's draws and the circulation's runs to it.
From there you can also give the draws that price the heat each
cycle's draws took. The fits for the readiness terms, the heat book,
the draw response and the elements also run there: see "Improve
accuracy" and "Fit the elements" in :doc:`simulate-heater`.


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
  ``sim.calibration``, ``sim_adapters.history`` and ``status_history``
