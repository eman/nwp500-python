======================================
Calibrate the Simulator to Your Heater
======================================

The simulator's default parameters are one NWP500-65's, fitted at one
installation. Record what your own heater reports for a few weeks and
fit its standby loss, its compressor and its power to that record. The
library records nothing itself: you collect the history, and the fits
run on what you give them.

.. contents::
   :local:
   :depth: 1


Record the history
==================

``nwp-cli simulate record`` asks the heater for its status every 30
seconds and appends each one to a file until you stop it (Ctrl+C). It
needs the ``cli`` extra and no other:

.. code-block:: bash

   nwp-cli simulate record history.jsonl
   nwp-cli simulate record history.jsonl --every 60

Each line is one status, as JSON: the instant it arrived and the
status payload as the heater sent it (the device's address is left
out):

.. code-block:: json

   {"t": "2026-10-18T23:09:10.298+00:00", "status": {"dhwUse": 1, "...": 0}}

Stopping and starting again appends to the same file, so the record
can have gaps. The heater may have heated or delivered water during a
gap, so ``calibrate`` takes any spacing between statuses of more than
4 times the record's usual spacing (and at least 5 minutes) as
unobserved. No quiet window and no recovery spans such a gap, and the
report counts them. If a write fails (a full disk, say), the recording
stops with an error rather than carrying on without saving. Write the
file any other way you like (an MQTT callback, an
export from a home-automation recorder) as long as each line has this
shape: ``nwp500.status_history.line(instant, raw_status)`` writes one,
and ``status_history.read(lines)`` reads them back as
``(instant, DeviceStatus)`` pairs.

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
  circulation. Home Assistant keeps 10 days of history by default. The
  air is used only over the span its history covers, and not while its
  sensor was ``unavailable``; the humidity takes the 50 % default
  outside that span, and the report says how much that is. Any flow the
  meter reports counts as a draw here, however short. The meter's draws and the circulation's runs
  are used only when their history covers the whole record; otherwise
  the heater's own flag stands in, since a span with no history would
  read as one with no water moving. For the same reason, a spell when
  the meter or the pump was ``unavailable`` counts as busy. A flag (``--air``, ``--ambient``,
  ``--humidity``) wins over the sources.

Neither of the ways to stand in for a sensor reproduced a sensor's fit
at the installation the model was fitted at. Over 279 quiet windows,
both moved the fitted loss, and the command offers neither:

- **The heater's own readings while its compressor ran, filled across
  the gaps:** these ran about 5 °F warm over the quiet windows. Quiet
  windows are the long gaps, often overnight, and the runs that bound
  them come in warmer hours.
- **An outdoor history projected through** ``sim.location_air``: this
  ran about 6 °F cold. The projection is for looking ahead.

Without either, the standby loss keeps the base's value and the report
says so.

When you give the air, the recoveries use it too. Without it, they
use the heater's own reading while the compressor runs. At that
installation, against the sensor, that reading was within about
0.35 °F from August to October. It was up to about 2 °F warm from May
to July, and about 2.7 °F warm in a run's first 2 minutes.

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

The command is a thin layer over ``sim.calibration.calibrate``:

.. code-block:: python

   from datetime import timedelta

   from nwp500 import sim, sim_adapters as sa, status_history
   from nwp500.sim import calibration

   with open("history.jsonl") as f:
       readings = status_history.read(f)
   history = sa.history(
       readings,
       air=air_readings,            # [(instant, temperature), ...]
       humidity=humidity_readings,  # [(instant, %RH), ...]
       max_gap=timedelta(minutes=5),
   )
   fitted = calibration.calibrate(history, sim.default_params(),
                                  recovery_air="air_f")
   params = fitted.params

Give the humidity: without a ``humidity_pct`` column, a recovery's
humidity reaches the evaporator's dew point as NaN, which reads as
100 %, not the 50 % the fits document. A constant series of 50 %, as
the command passes, is the fits' own default. ``max_gap`` is what
marks a recording's gaps as unobserved; without it every span between
two statuses is taken as observed.

From Python you can also give a meter's draws and the circulation's
runs, which make the quiet test exact and price the heat each cycle's
draws took. The fits for the readiness terms, the heat book, the draw
response and the elements also run there: see "Make the answer better"
and "Fit the elements" in :doc:`simulate-heater`.


What the history cannot tell
============================

- **The draws.** The heater reports no draw volume, and in recorded
  statuses its inlet and flow readings read 0. The draw terms
  (``book``, ``readiness``, ``draw``) need a hot-water meter and an
  inlet probe.
- **Circulation the heater does not run.** The quiet test is the
  heater's own "hot water in use" flag, which also fires on
  circulation. A loop's heat that does not trip the flag is invisible
  to the heater and lands in the standby loss. From Python, pass the
  circulation's runs (``sa.history(..., circulating=...)``) to keep
  them out of the quiet windows.
- **Daily energy totals.** The fit is not compared with the heater's
  daily totals (``request_energy_usage``): power and COP are fitted
  cycle by cycle, against its own power readings.


See also
========

* :doc:`simulate-heater`: run the simulator with your parameters
* :doc:`/reference/python_api/sim`: ``sim.calibration``,
  ``sim_adapters.history`` and ``status_history``
