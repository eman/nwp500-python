=================
Simulator Inputs
=================

Every input ``nwp500.sim`` takes: its unit, whether it is required,
what is assumed when it is left out, and where it comes from. How to
use them is in :doc:`/how-to/simulate-heater`, and the model behind
them in :doc:`/explanation/simulator`.

.. contents::
   :local:
   :depth: 1


Conventions
===========

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Quantity
     - Convention
   * - Temperatures
     - degF in the simulator's own fields (``*_f``), the unit the
       physics were fitted in: the tank, the setpoint, the ambient and
       the inlet. ``sim_adapters`` reads the device's raw fields, and
       takes and gives back caller values in the preferred unit
       (`Units at the boundary`_).
   * - Reservation setpoints
     - Half-degrees Celsius, as the device stores them (the entry's
       ``param``): 120 is 60 degC.
   * - Day masks
     - The device's: Sunday bit 7 (128), Monday bit 6 (64) ... Saturday
       bit 1 (2). Monday to Friday is 124; Saturday and Sunday, 130.
   * - Season masks
     - Bit 0 January ... bit 11 December; 4095 is every month.
   * - Modes
     - ``DhwOperationSetting`` values: 1 Heat Pump, 2 Electric, 3 Energy
       Saver, 4 High Demand, 5 Vacation, 6 Power Off.
   * - Instants
     - Timezone-aware ``datetime`` values. A naive one is refused.
       Instants in a result are aware too: convert them with
       ``astimezone``.
   * - Volumes
     - US gallons in the simulator's own fields; the preferred unit
       through ``sim_adapters``.

Every input is validated when it is built. An unknown field, a value
out of range or a naive instant raises pydantic's
``ValidationError``, a ``ValueError``.

The tables below give the simulator's own fields and units. The
**Source** column says where a value comes from. A library
field is filled by the adapter named; "not reported" means the heater
does not report it, so the caller supplies it or the default is used.
Every default an answer used is named in its ``defaults_used``.


Units at the boundary
=====================

``nwp500.sim`` works in degF and US gallons. ``nwp500.sim_adapters`` is
where units are crossed, so a caller works in the library's preferred
units (:doc:`/how-to/manage-units`): degC and litres after
``set_unit_system("metric")``, degF and gallons otherwise.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Adapter
     - Units
   * - ``heater_state``, ``settings``, ``environment(status)``
     - From the status, whatever unit is preferred.
   * - ``environment(ambient=..., inlet=...)``
     - The air and the mains water in the preferred unit; humidity in
       %RH.
   * - ``loads([(instant, volume), ...])``
     - Draws in the preferred volume unit.
   * - ``write(at, setpoint=..., mode=...)``
     - The setpoint in the preferred unit.
   * - ``reservation_entry(days=..., temperature=...)``
     - The temperature in the preferred unit, range-checked as
       ``build_reservation_entry`` checks it for the device.
   * - ``path(result)``
     - The tank along a ``SimulationResult``, ``RecoveryResult`` or
       ``Trace``, in the preferred unit.
   * - ``temperature(value_f)``, ``volume(value_gal)``
     - Any other value a result holds, in the preferred unit, and
       ``temperature_unit()``, ``volume_unit()`` its symbol.

The simulator's fields can also be set directly, in degF and gallons.


The span
========

.. list-table::
   :header-rows: 1
   :widths: 18 14 12 56

   * - Field
     - Type
     - Required
     - Notes and source
   * - ``start``
     - aware datetime
     - yes
     - The instant the state below was read. Usually now.
   * - ``horizon``
     - timedelta
     - yes
     - How far to walk; positive. 24 h answers most questions.
   * - ``tz``
     - IANA zone name
     - yes
     - The zone the heater's clock is set to, in which its reservations
       and TOU periods are local times. **Not reported**: the heater
       keeps local time with no zone. On a daylight-saving change a
       skipped local time fires an hour later on the wall clock, and a
       repeated one fires once. A TOU window or circulation run the
       clock skips whole never happens; one it skips part of keeps its
       elapsed time.


The heater's state: ``HeaterState``
===================================

Built by ``sim_adapters.heater_state(status)``.

.. list-table::
   :header-rows: 1
   :widths: 24 10 12 54

   * - Field
     - Unit
     - Default
     - Source
   * - ``upper_f``
     - degF
     - required
     - ``DeviceStatus.tank_upper_temperature_raw`` (0.1 degC).
   * - ``lower_f``
     - degF
     - required
     - ``DeviceStatus.tank_lower_temperature_raw`` (0.1 degC).
   * - ``compressor_running``
     - bool
     - False
     - ``DeviceStatus.comp_use``. True starts the walk inside a
       recovery.
   * - ``element_running``
     - bool
     - False
     - ``DeviceStatus.heat_upper_use`` or ``heat_lower_use``.
   * - ``element_running_since``
     - instant
     - None
     - When the element came on. **Not reported**: record the instant
       ``heat_upper_use`` or ``heat_lower_use`` turned on. It leaves
       the element the rest of its dead time; with None, the dead time
       is taken as past.
   * - ``energy_to_setpoint_wh``
     - Wh
     - None
     - ``DeviceStatus.energy_to_setpoint``: the heater's own count of
       the energy still needed to reach its target. ``forecast`` reads
       a zero count as "already ready" outside a TOU window. Leave it
       None for a tank state you made up: the count is the heater's
       own tank's.


Settings: ``Settings``
======================

Built by ``sim_adapters.settings(status)``.

.. list-table::
   :header-rows: 1
   :widths: 24 10 12 54

   * - Field
     - Unit
     - Default
     - Source
   * - ``setpoint_f``
     - degF
     - required
     - ``DeviceStatus.dhw_temperature_setting_raw`` (half degC).
   * - ``mode``
     - mode
     - 1
     - ``DeviceStatus.dhw_operation_setting``. In Vacation (5) or Power
       Off (6) the heater starts no heating. A status in Standby (0) is
       refused by ``sim_adapters.settings``.
   * - ``hp_lower_on_f``
     - degF
     - None
     - ``DeviceStatus.hp_lower_on_temp_setting_raw`` (half degC): the
       lower thermistor's compressor start threshold. Without it the
       heater never starts on the lower zone, its usual trigger
       (:doc:`/explanation/what-starts-a-recovery`), though a TOU
       window's opening still can; ``simulate`` and ``standby`` say
       ``hp_lower_on_unknown``. The adapter always fills it.
   * - ``hp_lower_off_f``
     - degF
     - None
     - ``DeviceStatus.hp_lower_off_temp_setting_raw`` (half degC): the
       lower thermistor's compressor stop threshold, the target
       ``forecast`` and ``active_cycle`` heat the lower zone to. Without
       it they heat to the setpoint, named in ``defaults_used``.
   * - ``hp_upper_on_f``
     - degF
     - None
     - ``DeviceStatus.hp_upper_on_temp_setting_raw`` (half degC): the
       upper thermistor's start threshold, which a TOU window raises to
       about the setpoint: the heater's own mark that a window is in
       force, which sees an override or a skipped window the schedule
       cannot. ``time_to_ready`` and ``element_mode`` read "in a window
       now" from it, ``next_recovery`` lets it override the schedule
       for a recovery running now (away from a scheduled edge), and
       ``forecast`` reads it to tell whether the energy count is
       measured to the setpoint. Without it, ``time_to_ready``,
       ``next_recovery`` and ``element_mode`` count a window as in
       force now, the conservative reading that the heater may not heat
       (named in ``defaults_used``); ``forecast`` lets the thermistors
       decide.


History: ``History``
====================

Facts about the time before ``start``. The heater reports neither, so a
caller that wants them follows the status stream and records the
instants.

.. list-table::
   :header-rows: 1
   :widths: 24 10 12 54

   * - Field
     - Unit
     - Default
     - Source and effect
   * - ``compressor_stopped_at``
     - instant
     - None
     - When ``comp_use`` last turned off. The compressor will not
       restart for 330 s after a stop; with None, no lockout is in
       force at the start.
   * - ``heated_at``
     - instant
     - None
     - When the tank last heated, by either source. Standby settling
       after a recovery runs from it; with None, from
       ``compressor_stopped_at``.


Schedules: ``Schedules``
========================

Built by ``sim_adapters.schedules(reservations=..., tou=...,
tou_enabled=...)``.

.. list-table::
   :header-rows: 1
   :widths: 24 22 54

   * - Field
     - Default
     - Source
   * - ``reservations``
     - none
     - ``ReservationSchedule.reservation``, read with
       ``request_reservations`` (:doc:`/how-to/schedule-operation`).
   * - ``reservations_enabled``
     - True
     - ``ReservationSchedule.enabled``: the schedule's own switch.
   * - ``tou_periods``
     - none
     - ``TOUInfo.schedule`` from ``NavienAPIClient.get_tou_info``, or a
       ``TOUReservationSchedule``, or a list of ``TOUPeriod``.
   * - ``tou_enabled``
     - False
     - ``DeviceStatus.tou_status``; with a ``TOUReservationSchedule``,
       its own ``enabled``.
   * - ``tou_switches``
     - none
     - The TOU switch's changes over the span, ``(instant, on)``, as
       the heater recorded them (``sim_adapters.replay``): a window is
       in force only while the switch is on. The switch at the start is
       ``tou_enabled``.

A ``ReservationEntry`` is one entry as the device stores it:

.. list-table::
   :header-rows: 1
   :widths: 24 18 58

   * - Field
     - Unit
     - Device field
   * - ``enabled``
     - bool
     - ``enable`` (2 on, 1 off)
   * - ``week``
     - day mask
     - ``week``
   * - ``hour``, ``minute``
     - local time
     - ``hour``, ``min``
   * - ``mode``
     - mode
     - ``mode``
   * - ``setpoint_half_c``
     - half degC
     - ``param``

An entry fires in its minute on each day its mask names, setting the
mode and the setpoint. Its ``mode`` is a ``ReservationMode``: 1-4 are
the operation modes of the same ids and 5 is Power Off (there is no
Vacation entry). An entry in Power Off, or with any id other than 1-4,
is not modelled: it is left out, with ``reservation_mode_not_modelled``
in ``reasons``.

A ``TouPeriod`` is one price period: ``season`` and ``week`` masks,
``start_hour``:``start_minute`` to ``end_hour``:``end_minute`` (the end
minute included, so 23:59 ends the day), and the encoded
``price_min``, ``price_max`` and ``decimal_point``. The windows the
heater holds are the highest-priced periods: for each group of periods
sharing a season and a day mask, the contiguous runs at the group's
highest ``price_max``, a run that ends at midnight joining one that
starts there. A group whose periods all share one price has no window.


The environment: ``Environment``
================================

.. list-table::
   :header-rows: 1
   :widths: 18 10 18 54

   * - Field
     - Unit
     - Default
     - Source
   * - ``ambient_f``
     - degF
     - required
     - The air at the heater's intake: one value for the whole span, or
       ``(instant, degF)`` readings. ``DeviceStatus.ambient_temperature_raw``
       (0.1 degC) is the device's reading now
       (``sim_adapters.environment(status)``): the air the heater stands
       in only while the compressor runs (at one installation, within
       about 0.35 degF from August to October and up to about 2 degF warm
       from May to July), its cabinet while idle, and
       ``environment(status)`` takes 6.2 degF off an idle reading.
       ``sim_adapters.location_air`` projects the air from an outdoor
       forecast, anchored to a running reading (``sim.location_air``). **Not reported ahead of
       time**: for the hours to come, pass a forecast or a sensor's
       readings. Readings are interpolated onto a 10-minute grid from an
       hour before ``start`` to 12 hours past the end, and held past
       the first and the last.
   * - ``humidity``
     - %RH
     - 50
     - **Not reported.** It changes the compressor's output through the
       evaporator's latent load. At one installation the air beside the
       heater averaged 53 % (monthly 45-70 %); holding every recovery
       at 50 % instead of its own reading moved the mean duration error
       by 0.4 min (27.5 to 27.9 over 178 recoveries).
   * - ``inlet_f``
     - degF
     - the parameters' ``draw.inlet_temp_f``
     - The mains water temperature. **Not reported**: the device's
       inlet field reads 0. It prices every draw. The default is one
       installation's September mains; give your own outside September
       (:ref:`the mains by season <mains-by-season>`).


Draws: ``Loads``
================

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Field
     - Unit
     - Notes
   * - ``draws``
     - ``Draw(at, gallons)``
     - Hot water drawn, as gallons on the delivered (mixed) line at an
       instant, more than 0. **Not reported**: the heater does not
       measure draw volume, so these are a forecast or a flow meter's
       record. With none, the tank only loses heat through its jacket.
   * - ``windows``
     - ``DrawWindow(start, end, expected_gal=None)``
     - Spans to judge, a shower or a bath: the result gives the tank
       and the deliverable gallons at each onset, the margin over
       ``expected_gal``, and whether the delivered water ran cold
       (``SimulationResult.windows``). Their edges are read exactly.
   * - ``circulation``
     - ``CirculationRun(start, end)``
     - An installation's circulation of hot water through its own
       plumbing, as runs: a weekly schedule laid out by
       ``sim_adapters.circulation``, a record, or a run on demand. An
       empty tuple is a circuit known to be quiet. None, the default,
       charges nothing: with ``HeaterParams.circulation`` set, the runs
       are not known, which is not the same as none ran, and
       ``reasons`` says ``circulation_unknown``. Needs
       ``HeaterParams.circulation`` (`Circulation`_).
   * - ``circulation_known_until``
     - instant
     - The runs are known for a span starting by this instant, and not
       after it, where nothing is charged (``circulation_unknown``).
       None: known throughout.


Commands: ``Commands``
======================

What a client is considering sending. Leave it empty to see what the
heater does on its own.

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Field
     - Default
     - Notes
   * - ``writes``
     - none
     - ``Write(at, setpoint_f=..., mode=..., id=...)``: a setpoint, a
       mode or both, at an instant inside the span. ``id`` names it in
       the result. Its setpoint is taken as the device will hold it, to
       the nearest half degree Celsius (146 degF is held as 146.3). A
       write to Vacation or Power Off is not modelled and is dropped
       whole, setpoint included (``write_mode_not_modelled``).
   * - ``reservations``
     - None
     - A reservation schedule written at the start, replacing the
       heater's; it is in force whatever ``reservations_enabled``
       says. None keeps the heater's.
   * - ``tou_enabled``
     - None
     - The TOU switch, set at the start. None keeps the heater's.


Circulation
===========

Some installations circulate hot water from the tank around their
plumbing on a schedule, so a tap runs hot sooner. A run takes heat only
while it runs. Give its runs in ``Loads.circulation`` and its terms in
``HeaterParams.circulation`` (``CirculationParams``); with no runs,
nothing is charged.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Field
     - What it is
   * - ``displaced_gal``
     - Gallons a run displaces before hot water comes back: an
       effective volume, fitted together with the two return terms
       below (``fit_return``).
   * - ``return_rest_offset_f``
     - How far above the air at the heater the return rests between
       runs (default 0: at the air). The pipe can run through warmer
       or cooler space than the heater stands in.
   * - ``return_cool_tau_h``
     - The time constant on which the pipe a run warmed cools back to
       rest (default 0: at once). A run this soon after another
       displaces water about two thirds cooled, and its gallons are
       scaled by that share.
   * - ``flow_gpm``
     - The flow a run is priced at.
   * - ``loss_btu_per_gal``
     - The heat book's loss per gallon circulated while a run is on: the
       pipe's own loss. The book's form without ``book_circuit_gal``.
   * - ``book_circuit_gal``
     - The heat book's circuit volume: with it, a run costs the book its
       first gallons up to this volume, each at the upper probe less the
       air. An effective volume fitted on the book's re-anchors
       (``fit_book``), smaller than ``displaced_gal``, and kept apart
       from it.
   * - ``meter_share``
     - The share of a run's own flow a household flow meter also reads
       (default 0, a meter the circulation does not pass). A book from
       a recorded history takes it off the meter to find the draws.
   * - ``run_gap_min``
     - Runs closer than this are one run (default 10 minutes), merged
       once over the whole input before both the zone draws and the
       book's loss. ``displaced_gal`` is fitted on runs merged at this
       gap, so change them together.

Each run is a flowing draw of ``min(flow x minutes, displaced_gal)``
gallons times the share of the pipe cooled since the last run ended,
its water returning at the air where the heater stands plus
``return_rest_offset_f``; runs closer than ``run_gap_min`` are one run,
as ``displaced_gal`` was fitted.
With a heat book, a run also costs the book its first
``book_circuit_gal`` gallons, each at the tank's upper probe less the
air (``loss_btu_per_gal`` per gallon circulated without it), and the
book does not re-anchor across it. A projection takes the upper probe
at the setpoint.
``DrawParams.lower_gate_f``, ``pool_f_per_hour`` and
``ungated_observability`` shape how the return reaches the lower probe;
they act only with circulation. None of these has a default: they
describe one installation's plumbing. ``site_example_params`` carries
one installation's (19.36 gal, a return resting 7.84 degF above the air
and cooling on 0.464 h, 1.397 gal/min, 159 BTU/gal, a 1.47 gal book
circuit).


The heat book: ``book``
=======================

``simulate(scenario, params, book=...)`` takes the tank's booked heat at
the start (``sim.Booked``): how much heat the tank holds above a 70 degF
reference. With it, a draw that
spends the booked heat takes the upper zone down; without it, the upper
zone takes each draw's calibrated response only, which holds it up
through a draw that empties the tank, and ``reasons`` says
``no_heat_book``. The lower zone takes each draw's calibrated response
either way.

The heater cannot tell you the starting book: two probes read a full
tank over the cold water of a recent draw. Start one only from what you know:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Start
     - When
   * - ``sim.full_tank_book(upper_f, lower_f, params.book)``, or
       ``sim_adapters.full_tank_book(status, params)``
     - The tank is full: quiet since a recovery ended (it finished, and
       nothing has been drawn since), or the heat pump running alone
       with the probes within ``book.uniform_band_f``, nothing drawn in
       its last ``book.anchor_run_min``. The book's own anchors.
   * - ``sim_adapters.book_from_history(recorded, params, at=...,
       flow=...)``
     - You record the heater's statuses and meter the hot water: the
       book is walked from the last time the record shows the tank
       full (below).
   * - ``sim_adapters.book_from_changes(rows, observed, params, at=...,
       flow=...)``
     - The same, from the heater's values' changes (``ChangeRows``) and
       the instants it was heard from, as Home Assistant records them,
       with the flows in gal/min and the temperatures in °F.
       Only an anchor after the last span the heater wasn't heard from
       counts.
   * - A ``Booked`` from your own record
     - You keep a book of the tank's heat some other way.

``book_from_history`` grids the record onto 10-second steps: the
statuses (the probes, the compressor, either element) held until the
next; the meter's ``flow`` and the circulation's own
``circulation_flow`` held 60 s; an ``inlet`` probe's readings held an
hour; the ``air`` held until the next. It anchors on the latest step
the tank reads full (``book.uniform_band_f``) with nothing drawn or
circulated in it: with nothing heating, after a recovery and before
anything was drawn or circulated, or with the heat pump running alone.
After a draw, the heat pump must first run ``book.anchor_run_min``
(15 minutes of its running time) for its anchor, since until then the
probes show only part of a draw's heat;
with no anchor in the record, that run counts from its start. A
quiet full-looking tank after a draw is no anchor, for the same
reason. A recovery that ends during a draw anchors at its end. Then it
books every step from the anchor: the heat pump's and the elements' heat in,
standby and circulation out, and each draw (the meter less
``CirculationParams.meter_share`` of a run's flow, above
``book.draw_gpm``). With ``flow_volume="delivered"``, the default, a
gallon is the water at the taps, priced at the mixing valve's delivery,
its hot share drawn from the tank; with ``flow_volume="tank"``, it is
the tank's own water (a meter or a detector on the heater's hot
outlet), priced at the upper probe less the inlet. The book's empty
points (``book.empty_btu``, ``book.zone_empty_btu``) were booked as
delivered gallons, so a tank-water flow takes ``empty_btu`` refit on
its own record and ``zone_empty_btu`` as far below it. It reads the last
18 hours (``book.max_anchor_age_h``) and, without an anchor there, the last 72
(``book.history_h``), aged. The inlet it converts gallons at is the
mains read from the long draws in those hours, as ``cold_supply`` reads
it (the probe's median over the last 2 minutes of each household draw
of 11 minutes or more with circulation off), and
``book.inlet_default_f`` without one. The probe's readings at rest
track the air around the pipe, not the mains. The meter must
report at rest too: a silence over an hour in the window is refused,
since it would read as a quiet full tank. A missing reading (None or
NaN) is skipped, and the value before it holds; it doesn't count as the
meter reporting.

``book_from_changes`` grids the changes the same way, each value held
until its next change, the flows, the inlet and the air too; without a
compressor flag, the heat source says when the compressor runs. A value
that holds writes no change, so only ``observed`` says the heater was
heard. A silence between those instants longer than ``max_gap`` of them
(4 times their usual spacing, and at least 5 minutes), one of
``rows.outages``, or one of ``flow_outages`` is a span nobody saw. The
book is read only from after the last such span, and is None when the
heater isn't heard at ``at``. No flow reading in force at the start of
the window it books over is a ``ValueError``. An inlet reading holds
except through ``inlet_outages``.

To build the steps yourself, pass them to ``book.book_steps``.
``BookStep.circulation_in_meter_gpm`` is
the circulation's flow the meter's figure still holds (a meter
reporting a trailing net holds a run's flow after it stops), and a
``Draw``'s ``per_draw_gal`` is the size a recorded draw is judged by
for ``draw_out_of_domain``.

A loss the book does not model, water an installation circulates
through its own plumbing say, comes in through ``sim.book.SpanLoss``:
its ``edges`` (where it starts and stops), its ``loss`` over each span
and whether that span disturbs the tank (no re-anchor across it), and
its ``bound``. Build the ledger with it and pass that instead of the
book: ``simulate(scenario, params,
ledger=BookedHeatLedger(book, ambient_at, params.book, extra=loss))``.

Once started, the walk re-anchors whenever the simulated tank comes
back full: a recovery the heater ends itself, quiet after one with
the zones within ``book.uniform_band_f``, or the heat pump running
alone with the zones within it, past the same hold. The book carries
the hold (``Booked.hold_s``), so a book from a record goes on with
its own. A ``Booked`` whose ``anchor_age_h`` is past ``book.max_anchor_age_h`` is aged:
``reasons`` says ``heat_book_aged`` and a window's margin comes off by
the book's error band.


Readiness: ``ReadinessParams``
==============================

``params.readiness`` says what counts as hot water at the tap and how
the delivered water follows the upper probe. Most of it describes the
**installation**, not the heater: the mixing valve and the household's
draws. ``delivered_lag_gal`` is the tank's. The defaults were measured at one
NWP500-65's installation; measure your own where you can.

.. list-table::
   :header-rows: 1
   :widths: 22 11 67

   * - Field
     - Default
     - What it is, and how it was measured
   * - ``line_f``
     - 105 degF
     - Delivered water below this is not hot. A choice. ``book.empty_btu``
       and any ``evidence`` were measured at their line, so move it and
       measure them again.
   * - ``delivered_lag_gal``
     - 5.0 gal
     - Gallons the tap still gets at or above the line after the upper
       probe has crossed it: the tank water above the probe. The pipe to
       the fixture is not in it. **Provisional, n = 1**: one bath on an
       NWP500-65, 7.3 gal at the tub spout and 5.3 at a gauge on the
       valve outlet, each net of its pipe run, the lower kept. The two
       differ by calibration (the spout read 2.74 degF above the gauge).
       To measure yours: draw a bath from a full tank, logging the upper
       probe and the water at the tap; it is the gallons between the
       two crossing the line, less the gallons from the tank to the
       thermometer. 0 answers at the probe.
   * - ``fall_f_per_gal``
     - 2.0 degF/gal
     - How fast the delivered water falls per gallon once it has
       crossed the line; also the rate the book's upper zone falls past
       its empty point. Two crossings, 1.6 at the probe and 1.83-2.07 at
       a spout; the faster kept.
   * - ``probe_resolution_f``
     - 1.0 degF
     - A round figure between the probe's jitter (about 0.36 degF
       either way) and the element's decisions, 1.4 degF from the
       probe's (:doc:`/explanation/heating-elements`). A probe error this size either way that would flip "the bath is
       ready" puts ``bath_ready_within_probe_resolution`` in
       ``time_to_ready``'s reasons.
   * - ``bath_gal``
     - 28.7 gal
     - The bath ``time_to_ready`` judges when none is given: the larger
       of two hot-only fills to one household's usual bath level, read
       on a meter (22.4 and 28.7 gal). The level is a choice; set yours.
   * - ``shower_gal``
     - 12.0 gal
     - A shower, when none is given. Assumed, not measured.
   * - ``evidence``
     - none (``site_example_params``: the site's 19)
     - Draws from your own record: ``(upper_f, lower_f, gallons)``, the
       probes before a draw with the heat pump and elements off and the
       gallons it delivered before the upper probe crossed the line,
       reduced to its frontier. Without a book, the answer where it
       shows more than the probes. ``sim.delivery.EXAMPLE_EVIDENCE`` is one
       installation's 19-draw frontier, which
       ``with_example_evidence`` sets (at a 105 degF line only).

Without a book, ``readiness`` reads the tank's heat from its two
probes, as the book's anchor does (``sim.delivery.probes_gal``), for any
state with the upper probe at or above ``line_f``, whether the probes
agree or not and whether the heater runs or not, with
``delivered_lag_gal`` on it. With evidence, the answer is the larger of
that and the evidence's. An upper probe below the line reads 0.
``site_example_params`` carries the site's evidence; ``default_params``,
which has no mixing valve, carries none.

A parameters document that still carries ``cold_lower_cutoff_f``,
``cold_lower_cap_gal``, ``full_setpoint_band_f`` or ``full_hidden_gal``
under ``readiness`` loads without them (``params.RETIRED_FIELDS``).

``params.book`` (``BookParams``) holds the book's own terms, fitted on
the re-anchors of one NWP500-65's metered record: its compressor,
element and standby heat, the empty point and how the upper zone mixes
down through a draw.
Its ``delivery_intercept_f`` and ``delivery_slope`` are the mixing
valve's line, which the simulator takes from ``draw``'s.


The draw range
==============

``params.draw.domain_upper_f`` (122.2-147.9 degF) and
``domain_volume_gal`` (1.0-41.6 gal) are the range the draw terms were
fitted over: the upper zone before a draw, across 508 episodes, and a
draw's own volume. The delivery line was measured only over 123.8-139.5
degF, so the top of the band already extrapolates it. When a walk would
draw outside either (its largest draw, at any instant of its path),
``reasons`` says ``draw_out_of_domain`` and ``draw_out_of_domain_at`` is
the first instant from which it stays out. ``None`` skips a range.


Parameters: ``HeaterParams``
============================

The physics constants, passed beside the scenario. Each field records
whether it was ``measured``, ``fitted`` or an engineering ``default``
(``nwp500.sim.params.provenance_of``).

``default_params(volume_code)`` takes ``DeviceFeature.volume_code``
(``sim_adapters.params(feature)`` passes it). It has **no mixing
valve**, and names the installation's book, readiness and draw terms
in ``unfitted`` (``INSTALLATION_TERMS``: one installation's fits stand
in for them); ``site_example_params`` is the installation the values were
fitted at, its valve included, and ``with_valve(params, (intercept_f,
slope))`` sets a valve's delivery line, delivered water at ``intercept +
slope x upper zone``, never above the tank. ``NO_VALVE`` is ``(0, 1)``;
``SITE_VALVE`` that installation's ``(53.56, 0.485)``. The book reads
the same line (``HeaterParams.book_terms``). Each field says whether it
describes the heater or the installation (``params.scope_of``) and,
where it matters, the frame it was fitted in (``params.note_of``):

.. list-table::
   :header-rows: 1
   :widths: 15 20 65

   * - Code
     - Model
     - Parameters
   * - 1
     - NWP500-50
     - The 65's, with the tank volume (``tank`` and ``book``) scaled to
       50 gal nominal.
   * - 2
     - NWP500-65
     - Fitted on one NWP500-65 at 240 V, 2026-10-11, at one
       installation; without its mixing valve.
   * - 3
     - NWP500-80
     - The 65's, with the tank volume (``tank`` and ``book``) scaled to
       80 gal nominal.

Any other code raises ``ValueError``. The defaults belong to one tank
in one place: its jacket loss reflects the air around that tank, its
draw response one household's draws, and its inlet that home's mains.
With your own calibration, pass your own ``HeaterParams``. These are
what a simulation needs of it:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Field
     - Without it
   * - ``tank.stratification_gap_tau_h``
     - A 60 h prior (history puts the constant near it on this
       product), named in ``defaults_used``; with draws, which open a
       gap that closes on it, ``reasons`` says ``tau_gap_prior``.
   * - ``compressor.compressor_constant`` above 0
     - No heat-pump recovery can be predicted, and a walk that needs
       one raises ``SimulationError``.
   * - ``draw.observability``
     - A scenario with draws is refused: ``SimulationError``
       (``draw_model_unsupported``).
   * - ``loss.ua_btu_hr_f``
     - The jacket loss falls back to ``loss.ua_baseline_btu_hr_f``.

Where the defaults come from
----------------------------

Every value in ``site_example_params(2)``, with what it was measured or
fitted on. "Retrain" values come from the weekly refit of one NWP500-65's
record on 2026-10-11, over the record to that date (from 2025-12-28).
They move a little at each retrain as the record grows; the range is
the one seen over the retrains from 2026-08-08 to 2026-10-18.

**Fitted at each retrain**

.. list-table::
   :header-rows: 1
   :widths: 26 14 34 26

   * - Field
     - Value
     - Fitted on, and its error
     - Range over retrains
   * - ``loss.ua_btu_hr_f``, ``loss.ua_exponent``,
       ``loss.bottom_loss_btu_hr``, ``loss.bottom_gate_f``
     - 4.483, 0; 90.8 BTU/hr, 1.83 degF
     - 378 quiet windows, 2026-02-14 to 10-24, the bottom loss on the 64
       that were stratified; each window kept only if it tracks the
       probes within 2 degF. On the 56 latest held out, the probes'
       fall is tracked within 0.068 degF/h, against 0.096 for the
       earlier law without a bottom loss, 4.605 and 0.186
       (:doc:`/explanation/standby-loss`).
     - 4.47-4.61 and 0.184-0.225 without a bottom loss
   * - ``tank.stratification_gap_tau_h``
     - 50.9 h
     - 127 quiet windows that opened with a gap of 2 degF or more, the
       bottom loss opening the gaps it relaxes. On the 32 latest held
       out, a mean squared error of 1.58 degF² against 1.78 for the
       earlier 60.06 h without a bottom loss. A separate fit on 146
       windows gave 59 h (95 % CI 47-94 h).
     - 50.9-60.4 h
   * - ``compressor.compressor_constant``
     - 0.0160 ft³/s
     - 142 recoveries from 2026-02-18 to 09-01, at the coil's approach;
       mean absolute error 25.3 min on them and 33.7 min on the 35 that
       followed (the old refrigerant table: 25.9 and 32.2, a difference
       the paired errors don't resolve). A rotary compressor of about
       8 cc at 3,500 rpm.
     - Refit on the CoolProp table once
   * - ``compressor.evap_approach_f``
     - 19.56 degF
     - The evaporator coil's reading, 6.7 + 0.596 x air, at 65 degF air.
       Held by the compressor fit: the durations don't place it (with K
       free they reach the same error from 6.9 degF).
     - Measured once, not refit
   * - ``compressor.evap_air_slope``
     - 0.596
     - The evaporator coil's reading against the air beside the heater
       over 377 compressor runs, air 48-86 degF. A free fit on the
       recoveries' durations chose 0.62. 1 is a fixed approach.
     - Measured once, not refit
   * - ``power.power_scale``
     - 1.640
     - The heater's own power readings over 323 compressor cycles: the
       metered input is 1.64 times the model's polytropic work, about
       61 % compression efficiency. Carried from the old table's 0.530
       by the two models' power on 83 metered cycles.
     - 0.528-0.551 on the old table
   * - ``power.cop_scale``, ``power.startup_wh``, ``power.cop_lift_coeff``
     - 0.688, 160.3 Wh, 0.002
     - 257 cycles against an energy meter on the heater's circuit. The
       lift term corrects the model's efficiency for the gap between the
       tank and the air, which the refrigerant model alone under-states.
       No error is recorded for these coefficients. An evaluation of the
       same fit on 2026-09-18, on the record to then, gave a median error
       of 4.8 % per recovery (Accuracy in :doc:`/explanation/simulator`).
     - 2.08-2.22, 158-171 Wh, 0.004-0.0065 on the old table. Carried
       to this one by the two models' COP on 178 recoveries, which
       differ by 1.156 - 0.003 per degF of lift in log
   * - ``draw.ungated_observability``
     - 0.263
     - ``fit_ungated_observability`` on 165 windows around circulation
       runs, April to October 2026, at the run model's terms (below):
       the share of the run model's heat the probes showed. The return
       feeds the mixing valve's cold port as well as the tank's inlet,
       and that split is not measured, so the share is the split and
       any shortfall of the probes together. It falls as the record
       grows: 0.117 on the 50 windows since September. Held out, the
       COP fit's latest 45 cycles came out at 6.1 % (median) against
       6.3 % with the 0.398 measured at the earlier loop
       (:doc:`/explanation/standby-loss`).
     - 0.117-0.263 (since September, since April)
   * - ``SITE_CIRCULATION``
     - 19.36 gal, +7.84 degF, 0.464 h, 1.397 gal/min
     - The run model's three terms fitted together (``fit_return``) on
       123 runs with the compressor off, 2026-04-04 to 2026-10-24. In
       five-fold cross-validation the mean absolute error is 268 BTU a
       run, against 767 for a return at the air (that form refits at
       6.36 gal). Before a run after 16 h or more, the return probe
       read a median 6.9 degF above the heater's air, following it
       with a slope of 0.95. Runs within an hour of another took a
       median 1,583 BTU, against 3,223 after 8 h. The record's long
       runs never brought hot water back (the return still 17-38 degF
       under the tank after 16-20 gal), so the volume is effective and
       above the typical 4 min (5.9 gal) run. The longest measured run
       (19.8 gal) sets it: ``fit_return`` refuses a set of runs none of
       which is longer than the volume found. The flow is the median
       over the 14 days before a retrain.
     - folds 14.6-19.5 gal, 7.3-8.2 degF, 0.45-0.51 h

**Measured on the heater**

.. list-table::
   :header-rows: 1
   :widths: 30 18 52

   * - Field
     - Value
     - Evidence
   * - ``tank.volume_gal``, ``tank.lower_zone_share``
     - 63.2 gal, 0.5
     - The heater's own energy fields put the tank at 156.6 Wh per degF
       (:doc:`/explanation/tank-energy`). Recoveries heat 0.44-0.48 of
       the tank while it is stratified and 0.96 once mixed, over 269
       recoveries (:doc:`/explanation/recovery-speed`). The share
       is a round 0.5: refitting the compressor constant at 0.435-0.5
       moved the held-out recovery error by under 0.7 min (33.7-34.3).
   * - ``element.element_w``
     - 5,148 W
     - Element-only minutes in the record (90 % CI 5,104-5,176 W,
       168 min). A later refit over 95 element runs gave 5,143 W. Two
       commanded runs on one evening read 5,219 and 5,242 W.
   * - ``element.upper_f_per_min``, ``element.upper_dead_time_min``
     - 2.01 degF/min, 1.21 min
     - 29 upper-element runs on 21 days (:doc:`/explanation/heating-elements`).
   * - ``element.lower_f_per_min``
     - 1.38 degF/min
     - 9 lower-element runs (90 % CI 1.21-1.62). One commanded run read
       1.19-1.55, depending on how the rise is measured.
   * - ``element`` start and stop thresholds
     - 0.54, 0.72, 1.44, 1.8, 1.62 degF; 104.9 degF
     - The entry-threshold sweeps and the off point
       (:doc:`/explanation/heating-elements`).
   * - ``element.upper_reengages_below_setpoint_f``
     - 4.1 degF
     - 12 High Demand restarts mid-stint (90 % CI 3.8-4.5 degF); the
       four of 2026-04-26/27 came at 3.78-4.14 degF short, each about
       3 minutes to the setpoint. The simulator starts High Demand's
       upper element there later in a stint.
   * - ``controller.write_start_lag_s``, ``restart_lockout_s``,
       ``window_write_starts_f``
     - 30 s, 330 s, 4.0 degF
     - Setpoint writes and their starts, and two restarts at 5 min 28 s
       and 5 min 31 s (:doc:`/explanation/what-starts-a-recovery`).
   * - ``controller.mode_write_starts_f``
     - 2.0 degF
     - A mode write into a compressor mode with the upper tank this far
       short started it: 7 of 7 out of ``ENERGY_SAVER``.
   * - ``controller.mode_write_lower_starts_f``
     - 3.6 degF
     - A mode write into a compressor mode with the lower tank this far
       short started it: 19 of 19 out of an element mode; the most short
       with no start was 2.70 degF. Out of ``HEAT_PUMP`` the upper tank
       must be short too: Energy Saver landing with it 18.7 degF above
       the setpoint started nothing (2026-09-21).
   * - ``controller.energy_saver_write_seen_f``
     - 1.44 degF
     - The least shortfall at which a write into ``ENERGY_SAVER`` was
       seen to start the compressor (7 of 7, from 1.44 to 13.9 degF).
   * - ``controller.tou_cap_f``
     - 3.6 degF
     - The device's 2 degC reduced target; capped recoveries stopped
       3.42 degF short (:doc:`/explanation/tou-recovery-cap`), one
       0.1 degC probe step past it, as a recovery reaching its setpoint
       ends with the probe 0.5-2 degF over it. Both stop at the
       threshold in the simulator.

**Fitted at one installation** (``unfitted`` in ``default_params``)

.. list-table::
   :header-rows: 1
   :widths: 30 18 52

   * - Field
     - Value
     - Evidence
   * - ``draw.observability``
     - 0.633
     - Draws with the compressor off, metered, refitted on 2026-09-26
       with the inlet probe (earlier fits 0.454 and 0.505). It prices a
       draw's heat; without it no draw moves the tank.
   * - ``draw.reach_gate_f``, ``draw.reach_offset_f``,
       ``draw.reach_gal``, ``draw.upper_f_per_gal``
     - 30.0 degF, 1.25 degF, 9.0 gal, 0.05 degF/gal
     - How a draw moves the probes: 399 draws from 2026-02-21 to 07-31
       with nothing heating or circulating around them, against the
       probes 10 minutes after each ended. Held-out accuracy in
       :doc:`/explanation/draws`.
   * - ``draw.inlet_temp_f``, the valve line
     - 72.4 degF, (53.56, 0.485)
     - Long-draw plateaus on the cold supply, and five plateaus at the
       valve outlet (:doc:`/explanation/draws`).
   * - ``draw.lower_gate_f``, ``draw.pool_f_per_hour``
     - 5.0 degF, 0.015 degF/h
     - 146 circulation runs with no draw: the gap above which a run's
       heat lands on the lower probe (interval 3.5-6.0 degF), and the
       slow cooling of the water below it
       (:doc:`/explanation/standby-loss`).
   * - ``book.hp_btu_per_h``, ``book.hp_btu_per_h_per_f``, ``book.ua_btu_per_h_f``
     - 4,338, 66.0, 2.88
     - The book's heat-pump rate and standby, refitted on 2026-10-23
       with the circulation at a 1.47 gal circuit volume
       (``CirculationParams.book_circuit_gal``), on 284 pairs of
       moments when the tank read full from 2026-02-14, its air a room
       sensor beside the heater; against those anchors its mean absolute
       error was 2,207 BTU (2,403 with the loss per gallon). Fitted on
       a 63.2 gal book (``book.tank_gal``).
   * - ``book.empty_btu``, ``book.zone_empty_btu``
     - 16,169, 12,636 BTU
     - The heat left at five recorded drawdowns to the line
       (14,237-19,616 BTU). ``zone_empty_btu`` is where a draw takes the
       upper zone across the line, 3,533 BTU lower so the zone centres
       the crossings: their median when the book held back the heat in
       a draw's cold water. Booked as delivered gallons: a flow that
       counts tank water (``flow_volume="tank"``) books less heat left
       at the line, so refit ``empty_btu`` on your record and keep
       ``zone_empty_btu`` as far below it.
   * - ``book.zone_mix_f_per_gal``, ``book.zone_mix_gal``
     - 1.25 degF/gal, 14 gal
     - 112 draws. A refit on the full record gave 0.65 degF/gal over
       16 gal, on fewer draws and with three times its fit error held
       out; the shipped pair is unchanged.
   * - ``book.error_btu``, ``book.aged_error_btu``
     - 3,000, 4,100 BTU
     - The book's drift from the anchors, fresh and after 18 h. A refit
       on the full record gave 3,000 and 3,900.
   * - ``readiness``
     - the Readiness section above
     - The bath tests, the outlet lag and the readiness evidence
       (:doc:`/explanation/draws`).

**Engineering values**, not measured on the heater: the condenser
approach (10 degF), clearance ratio (0.05), polytropic exponent (1.17),
the fan's airflow in the latent term (229 CFM; no airflow is
published, and the manual's 229 is the 50 gal model's shipping weight
in pounds), the jacket loss fallback (5.0 BTU/hr per degF) and the
lift reference (62 degF). The record cannot fit the first three: the
compressor constant absorbs each, and refitting it with the condenser
approach at 5 to 20 degF, the clearance at 0.02 to 0.08 or the exponent
at 1.10 to 1.25 moved the held-out recovery error by under 0.7 min
(33.1 to 34.3 on 35 recoveries). The latent term is up to about 150 BTU/hr
of about 4,000; on the record, a recovery's duration moves a mean
1.2 min between its own humidity and 50 % (at most 3 %).

``params_to_document`` and ``params_from_document`` in
``nwp500.sim.params`` write and read parameters as a JSON document
(schema ``heater-params/1``). ``sim.codec`` writes a scenario with its
parameters as one document.


Reasons
=======

Every answer carries ``reasons``: why it may be less than it seems.
The ones about inputs and parameters:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Reason
     - What it says
   * - ``physics_uncalibrated``, ``energy_uncalibrated``,
       ``standby_uncalibrated``
     - A term calibration could not fit on this heater (a recovery's
       duration; its energy and COP; the jacket's loss) is the base's
       (``HeaterParams.unfitted``).
   * - ``book_uncalibrated``, ``readiness_uncalibrated``,
       ``draw_uncalibrated``
     - The installation's heat book terms, readiness terms or draw
       response are another installation's (``default_params()`` marks
       all three, ``INSTALLATION_TERMS``), not fitted from this one's
       meter. The readiness answer says the first two, whether or not a
       recovery was needed; any answer with draws, the third. Fit them and drop each from
       ``HeaterParams.unfitted``.
   * - ``ambient_defaulted``
     - No usable air reading was given (``Environment.ambient_f`` missing,
       or its readings all missing), so the answer ran at the default
       air, 65 °F.
   * - ``ambient_from_idle_cabinet``
     - The air comes from the heater's own reading taken while its
       compressor was idle (``Environment.ambient_cabinet``): its
       cabinet's, less 6.2 °F, the cabinet's mean warmth at one
       installation. Corrected so, it was within 2.2 °F of the air on
       average (5 to 9 °F warm raw, by season).
   * - ``tau_gap_prior``
     - Draws opened a gap that closes on a prior time constant, not one
       fitted on this heater.
   * - ``circulation_unknown``
     - The installation circulates, and its runs are not known over
       the span: nothing was charged there.
   * - ``hp_lower_on_unknown``
     - The lower-zone start threshold was not known, so that start was
       never searched (a TOU opening's still was).
   * - ``tou_schedule_unknown``
     - TOU is on (or, for ``standby``, no schedule was given) and no
       window could be laid out.
   * - ``tou_window_in_force``
     - The heater is in a TOU window now (an unknown marker counts as
       in force): an element mode write may not take.
   * - ``lower_trigger_held_uncertain``
     - The lower trigger was held (the upper zone at the setpoint, or a
       window), which moved or dropped a start.
   * - ``inlet_temp_modelled``
     - Draws' cold water, or a book's gallons, are priced at an inlet
       nobody measured at the mains.
   * - ``draw_out_of_domain``
     - A draw lies outside the range the draw terms were fitted over.
   * - ``write_mode_not_modelled``, ``reservation_mode_not_modelled``
     - A write into Vacation or Power Off, or a reservation in Power Off
       (or a mode id other than 1-4), was left out.
   * - ``physics_truncated=integration_bound_reached``
     - A served recovery rests on an integration that hit its bound.
   * - ``physics_failed``
     - The integrator raised on a recovery the walk went without.
   * - ``recovery_low_confidence``
     - A recovery model served a duration under 0.6 confidence.
   * - ``no_heat_book``, ``heat_book_aged``
     - Without a book the delivery is the upper zone's; an aged one
       carries its error band.


Errors
======

``ValueError`` (or pydantic's ``ValidationError``)
   An input out of range, an unknown field, a naive instant, an
   unknown zone, a write outside the span, a write or a written
   reservation whose setpoint is outside the range the simulation runs
   (104.9-149.9 degF; the device's own limits are its
   ``DeviceFeature``'s), a draw window that does not end after it
   starts, an element mode that runs no element, an unknown ``volume_code``, or
   ``with_example_evidence`` at a line other than 105 degF.
``nwp500.sim.engine.SimulationError``
   The walk could not be completed: most often a heat-pump recovery
   the parameters cannot predict, or one past the integrator's
   30-hour bound (the message names the bound), or draws the parameters
   have no draw response for (``draw_model_unsupported``).
