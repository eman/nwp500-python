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
     - Read the device's raw fields: the same status gives the same
       values whatever unit is preferred.
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
       repeated one fires once.


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
       Off (6) the heater starts no heating.
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
mode and the setpoint. One in Vacation or Power Off is not modelled: it
is left out, with ``reservation_mode_not_modelled`` in ``reasons``.

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
       in only while the compressor runs (within about 0.35 degF at one
       installation), its cabinet while idle (about 5 degF warm).
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
       evaporator's latent load.
   * - ``inlet_f``
     - degF
     - the parameters' ``draw.inlet_temp_f``
     - The mains water temperature. **Not reported**: the device's
       inlet field reads 0. It prices every draw.


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
       effective volume, fitted together with the air the return
       cools to between runs.
   * - ``flow_gpm``
     - The flow a run is priced at.
   * - ``loss_btu_per_gal``
     - The heat book's loss per gallon circulated while a run is on: the
       pipe's own loss.
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
gallons, its water returning at the air where the heater stands; runs
closer than ``run_gap_min`` are one run, as ``displaced_gal`` was
fitted.
With a heat book, a run also costs the book ``loss_btu_per_gal`` per
gallon circulated, and the book does not re-anchor across it.
``DrawParams.lower_gate_f``, ``pool_f_per_hour`` and
``ungated_observability`` shape how the return reaches the lower probe;
they act only with circulation. None of these has a default: they
describe one installation's plumbing. ``site_example_params`` carries
one installation's (6.2746 gal, 1.397 gal/min, 159 BTU/gal).


The heat book: ``book``
=======================

``simulate(scenario, params, book=...)`` takes the tank's booked heat at
the start (``sim.Booked``): how much heat the tank holds above a 70 degF
reference and where a draw's cold water lies. With it, a draw that
spends the booked heat takes the upper zone down and the lower zone
follows the cold front; without it, each draw moves the zones by its
calibrated response only, which holds the upper zone up through a draw
that empties the tank, and ``reasons`` says ``no_heat_book``.

The heater cannot tell you the starting book, and the library does not
guess it: two probes read a full tank over the cold water of a recent
draw. Start one only from what you know:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Start
     - When
   * - ``sim.full_tank_book(upper_f, lower_f, params.book)``, or
       ``sim_adapters.full_tank_book(status, params)``
     - The tank has been quiet since a recovery ended: it finished, and
       nothing has been drawn since. The book's own anchor.
   * - ``sim_adapters.book_from_history(recorded, params, at=...,
       flow=...)``
     - You record the heater's statuses and meter the hot water: the
       book is walked from the last time the record shows the tank
       full and quiet after a recovery (below).
   * - A ``Booked`` from your own record
     - You keep a book of the tank's heat some other way.

``book_from_history`` grids the record onto 10-second steps: the
statuses (the probes, the compressor, either element) held until the
next; the meter's ``flow`` and the circulation's own
``circulation_flow`` held 60 s; an ``inlet`` probe's readings held an
hour; the ``air`` held until the next. It anchors on the latest step
the tank reads full (``book.uniform_band_f``) with nothing heating,
after a recovery and before anything was drawn or circulated; a
recovery that ends during a draw anchors at its end. Then it books
every step from the anchor: the heat pump's and the elements' heat in,
standby and circulation out, and each draw (the meter less
``CirculationParams.meter_share`` of a run's flow, above
``book.draw_gpm``) through the mixing valve. It reads the last 18 hours
(``book.max_anchor_age_h``) and, without an anchor there, the last 72
(``book.history_h``), aged. The inlet it converts gallons at is the
median of the probe's readings over the last 3 hours
(``book.inlet_window_s``), the default without one. The meter must
report at rest too: a silence over an hour in the window is refused,
since it would read as a quiet full tank. A missing reading (None or
NaN) in any series is left out, here, in every adapter and in a
``Record`` built directly: never a number to compute with, and the
value before it holds. An ambient frame handed to the core
(``decay.project_decay``, ``TankPhysics``) must carry an ``ambient_f``
column: without one it is an error, not a coast at the 65 °F default.
A column with no usable reading does take the default, and the
projection says so (``DecayProjection.ambient_defaulted``).

What an installation's own meter and circulation need beyond this,
its meter's arithmetic and its circulator's reading rules, is the
installation's to compute. Steps built that way go to
``book.book_steps`` directly. ``BookStep.circulation_in_meter_gpm`` is
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
back full: a recovery the heater ends itself, or quiet after one with
the zones within ``book.uniform_band_f``. A ``Booked`` whose
``anchor_age_h`` is past ``book.max_anchor_age_h`` is aged:
``reasons`` says ``heat_book_aged`` and a window's margin comes off by
the book's error band.


Readiness: ``ReadinessParams``
==============================

``params.readiness`` says what counts as hot water at the tap and how
the delivered water follows the upper probe. Most of it describes the
**installation**, not the heater: the pipe to the fixture, the mixing
valve and the household's draws. The defaults were measured at one
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
       probe has crossed it: the water above the probe and in the pipe
       to the fixture. **Provisional, n = 1**: one bath, 7.3 gal at the
       tub spout and 5.3 at a gauge on the valve outlet, the lower kept.
       To measure yours: draw a bath from a full tank, logging the upper
       probe and the water at the tap; it is the gallons between the
       two crossing the line. 0 answers at the probe.
   * - ``fall_f_per_gal``
     - 2.0 degF/gal
     - How fast the delivered water falls per gallon once it has
       crossed the line; also the rate the book's upper zone falls past
       its empty point. Two crossings, 1.6 at the probe and 1.83-2.07 at
       a spout; the faster kept.
   * - ``cold_lower_cutoff_f``
     - 100 degF
     - At or below this lower-probe reading the hot/cold boundary cannot
       be placed between the probes: the answer says
       ``thermocline_unlocated``.
   * - ``cold_lower_cap_gal``
     - 6.5 gal
     - The cap on an evidence answer there (a book is never capped): the
       least any of three draws from such a state gave before the upper
       probe reached 110 degF.
   * - ``full_setpoint_band_f``
     - 2.0 degF
     - Both probes this close to the setpoint, or above it, is a tank
       the heater has brought to its target: it has the full-tank floor.
   * - ``full_hidden_gal``
     - 13.5 gal
     - What the full-tank floor takes off for cold water from earlier
       draws hiding under a lower probe that reads full: the most a book
       found, over 2,505 samples with the setpoint near 141 degF.
   * - ``dip_f``, ``dip_min``
     - 3.4 degF, 3.0 min
     - The transient dip during a draw that is not running out: a
       window is cold only if the delivery falls further below the line,
       or stays below it longer. The NWP500's upper probe's.
   * - ``probe_resolution_f``
     - 1.0 degF
     - A probe error this size either way that would flip "the bath is
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
       reduced to its frontier. The answer without a book for a tank
       that is not full. ``sim.delivery.EXAMPLE_EVIDENCE`` is one
       installation's 19-draw frontier, which
       ``with_example_evidence`` sets (at a 105 degF line only).

Without a book or evidence, ``readiness`` has an answer only for a full
tank (the floor); any other state reads 0 with
``colder_than_evidence``. ``site_example_params`` carries the site's
evidence; ``default_params``, which has no mixing valve, carries none.

``params.book`` (``BookParams``) holds the book's own terms, fitted on
the re-anchors of one NWP500-65's metered record: its compressor,
element and standby heat, the empty point, how the upper zone mixes
down through a draw and where the lower probe reads the cold front.
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
valve**; ``site_example_params`` is the installation the values were
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

``params_to_document`` and ``params_from_document`` in
``nwp500.sim.params`` write and read parameters as a JSON document
(schema ``heater-params/1``). ``sim.codec`` writes a scenario with its
parameters as one document.


Reasons
=======

Every answer carries ``reasons``: why it may be less than it seems. A
caller with its own record can add to them, since they are a tuple.
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
     - A write or a reservation into Vacation or Power Off was left out.
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
