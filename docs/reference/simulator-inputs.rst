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
   * - ``layers_f``
     - degF
     - None
     - The tank's layers, the bottom first, as its history left them
       (``sim_adapters.layers_from_history`` and
       ``layers_from_changes``, ``sim.history.replay``), as many as
       ``TankParams.layers``. With None, the simulator makes them of the
       two probes, and ``reasons`` says ``tank_profile_estimated``.
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
   * - ``resume``
     - JSON text
     - None
     - Where a simulation that ended at this scenario's start left the
       heater: ``SimulationResult.end_state`` carries it, with
       ``end_history`` and ``end_settings`` for the scenario's
       ``history`` and ``settings``. Opaque; keep it as given. With it
       the walk goes on from that one (the compressor, the element,
       the lockout and a held mode), and its own flags and ``History``
       are the resume's. A setpoint or mode other than
       ``end_settings``' is a write at the start. Into or out of
       Vacation or Power Off, the walk starts afresh and ``reasons``
       says ``resume_dropped_heating_disabled_changed``.


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
       ``hp_lower_on_unknown``. The adapter always fills it. Where the
       elements answer it (Electric, or the heat pump outside its
       range) it reads at most
       ``element.upper_reengages_below_setpoint_f`` under the setpoint,
       since they stop at the setpoint.
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
     - **Not reported.** Passed to a ``RecoveryModel``; the heat
       pump's map does not use it. At one installation the air beside
       the heater averaged 53 % (monthly 45-70 %).
   * - ``inlet_f``
     - degF
     - the parameters' mains on each draw's day
     - The mains water temperature. **Not reported**: the device's
       inlet field reads 0. It prices every draw. The default is the
       mains of the parameters' climate on each draw's own day
       (``draw.climate_f``, ``DrawParams.mains_on``), the start's
       named in ``defaults_used``; without a climate, ``draw.inlet_temp_f`` all year: 58 degF
       in ``default_params``, the rating test's
       (:ref:`the mains by season <mains-by-season>`). ``defaults_used``
       names the value.


Draws: ``Loads``
================

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Field
     - Unit
     - Notes
   * - ``draws``
     - ``Draw(at, gallons, per_draw_gal=None, duration_s=0)``
     - Hot water drawn, as gallons on the delivered (mixed) line from
       ``at``, more than 0, at an even flow for ``duration_s`` seconds (up
       to a day):
       the walk takes it at ``at`` and at each whole minute before its
       end, each piece the gallons of its span, so the heating meets it
       between them as it meets a meter's per-minute draws. 0 takes it
       all at ``at``. ``draw_forecast.forecast_loads`` gives each
       expected draw its expected time drawing. **Not reported**: the
       heater does not measure draw volume, so these are a forecast or
       a flow meter's record. With none, the tank only loses heat
       through its jacket.
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
     - The pipe's volume: what a run brings back from the pipe before
       the tank's own water returns, measured on the return line of a
       run after a long rest (``measure_pipe``).
   * - ``pipe_ua_btu_hr_f``
     - The pipe's loss once the tank's own water is coming back, BTU/h
       per degF, measured with the volume (default 0: back as hot as
       it left). That water returns at the rest plus
       ``exp(-UA / (flow x 8.34 x 60))`` of the top's lift over it.
   * - ``return_rest_offset_f``
     - How far above the air at the heater the return rests between
       runs (default 0: at the air). The pipe can run through warmer
       or cooler space than the heater stands in. Fitted with the
       cooling below on the runs' heat (``fit_return``).
   * - ``return_cool_tau_h``
     - The time constant on which the pipe a run warmed cools back to
       rest (default 0: at once). A run this soon after another
       displaces water about two thirds cooled, and its gallons are
       scaled by that share.
   * - ``flow_gpm``
     - The flow a run is priced at.
   * - ``meter_share``
     - The share of a run's own flow a household flow meter also reads
       (default 0, a meter the circulation does not pass). A replay of a
       recorded history takes it off the meter to find the draws.
   * - ``run_gap_min``
     - Runs closer than this are one run (default 10 minutes), merged
       once over the whole input. The return's rest and cooling are
       fitted on runs merged at this gap, so change them together.

Each run first returns ``min(flow x minutes, displaced_gal x
cooled_share)`` gallons, the share of the pipe cooled since the last
run ended, at the air where the heater stands plus
``return_rest_offset_f``, then the tank's
own water at its steady share; water warmer than the tank's inlet zone
rises past it to where the tank is as warm. Runs closer than
``run_gap_min`` are one run, as the return's terms were fitted.
None of these has a default: they
describe one installation's plumbing. ``site_example_params`` carries
one installation's (a 6.86 gal pipe losing 14.6 BTU/h per degF, a
return resting 3.74 degF above the air and cooling on 0.72 h,
1.397 gal/min).


The tank's layers from a recorded history
=========================================

The heater cannot tell you how the water under its two probes lies:
they read a full tank over the cold water of a recent draw.
``HeaterState.layers_f`` carries the tank's layers when you know them;
these build them from what was recorded over the day before
(``sim.history.REPLAY``, 24 hours), walked through the layered tank
(``sim.history.replay``) with the probes laid over the result:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - From
     - When
   * - ``sim_adapters.layers_from_history(recorded, params, at=...,
       flow=...)``
     - You record the heater's statuses and meter the hot water.
   * - ``sim_adapters.layers_from_changes(rows, observed, params,
       at=..., flow=...)``
     - The same, from the heater's values' changes (``ChangeRows``) and
       the instants it was heard from, as Home Assistant records them,
       with the flows in gal/min and the temperatures in °F. A span the
       heater wasn't heard from is walked across, its values held.
   * - ``sim_home_assistant.HomeAssistantTank``
     - The same, kept current from Home Assistant: ``read`` reads the
       history once over ``TANK_WINDOW``, then only what is new;
       ``layers`` replays what it holds (``LayersAnswer``, its layers and
       notes).

``steps_from_history`` grids the record onto 10-second steps
(``STEP_GRID_S``): the statuses (the probes, the compressor, either
element) held until the next; the meter's ``flow`` and the circulation's
own ``circulation_flow`` held 60 s (``FLOW_HOLD``); an ``inlet`` probe's
readings held an hour; the ``air`` held until the next, and without an
air reading the heater's own while its compressor runs. The replay
takes the heat pump's and the elements' heat in, standby and
circulation out, and each draw: the meter less
``CirculationParams.meter_share`` of a run's flow, above
``DrawParams.draw_gpm`` (``sim.history.drawn_gal``). With
``flow_volume="delivered"``, the default, a gallon is the water at the
taps through the mixing valve, its hot share drawn from the tank; with
``flow_volume="tank"``, it is the tank's own water (a meter or a
detector on the heater's hot outlet). ``probes`` (upper, lower) are laid
over the replayed layers, by default the record's last. The answer is
None when the record reads both probes at no instant of the span. The
meter must report at rest too: a silence over an hour
(``METER_MAX_GAP``) in the span is a ``ValueError``, since it would
replay as no draw. A missing reading (None or NaN) is skipped, and the
value before it holds.

``steps_from_changes`` grids the changes the same way, each value held
until its next change, the flows and the air too; without a compressor
flag, the heat source says when the compressor runs. A value that holds
writes no change, so only ``observed`` says the heater was heard. A
silence between those instants longer than ``max_gap`` of them (4 times
their usual spacing, and at least 5 minutes), one of ``rows.outages``,
or one of ``flow_outages`` is a span nobody saw. The replay walks
across it, each value held from before it, the flow for ``FLOW_HOLD``
and then none, and ``layers_from_changes`` is None when such a span is
still open at ``at``. With no flow reading at all it is a
``ValueError``; the replay starts no earlier than the flow's first
reading.

To build the steps yourself, pass them to ``sim.history.replay``.


Readiness: ``ReadinessParams``
==============================

``params.readiness`` says what counts as hot water at the tap and the
volumes readiness is judged against: choices an installation makes, not
the heater's terms.

.. list-table::
   :header-rows: 1
   :widths: 22 11 67

   * - Field
     - Default
     - What it is, and how it was measured
   * - ``line_f``
     - 105 degF
     - Delivered water below this is not hot. A choice.
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

The deliverable gallons (``sim.delivery.deliverable``) are the water
the tap gets at the line or warmer: the water leaving the top in turn,
each tank gallon delivering ``1 / hot_fraction`` through the mixing
valve, to the first that the valve delivers under the line
(``stratified.deliverable_gal``). The mains it meets is the scenario's
inlet, else the parameters' on the day it is read: a draw window's
onset, a walk's point. The tank is its layers
(``HeaterState.layers_f``, ``Deliverable.basis`` ``layers``), else the
profile its two probes stand for (``basis`` ``probes``, and
``tank_profile_estimated`` in the reasons). The outlet is above the
upper probe, so a probe just under the line still leaves the water
above it.

A parameters document that still carries ``delivered_lag_gal``,
``fall_f_per_gal`` or ``evidence`` under ``readiness``, or a ``book``
part, loads without them, and ``params.unknown_fields`` names them.
``book`` and ``readiness`` in its ``unfitted`` are dropped
(``params.RETIRED_TERMS``).


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
valve**, and names the installation's draw terms
in ``unfitted`` (``INSTALLATION_TERMS``: one installation's fits stand
in for them); ``site_example_params`` is the installation the values were
fitted at, its valve included, and ``with_valve(params, (intercept_f,
slope))`` sets a valve's delivery line, delivered water at ``intercept +
slope x upper zone``, never above the tank. ``NO_VALVE`` is ``(0, 1)``;
``SITE_VALVE`` that installation's ``(53.56, 0.485)``. Each field says whether it
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
     - The 65's, with the tank volume (``tank``) scaled by
       rated storage, 45.2 gal against the 65's 63.2.
   * - 2
     - NWP500-65
     - Fitted on one NWP500-65 at 240 V, 2026-10-11 to 10-24, at one
       installation; without its mixing valve.
   * - 3
     - NWP500-80
     - The 65's, with the tank volume (``tank``) scaled by
       rated storage, 76.1 gal against the 65's 63.2.

Any other code raises ``ValueError``. The defaults belong to one tank
in one place: its losses reflect the air around that tank, its probes'
reading that one heater's, and its inlet that home's mains. With your
own calibration, pass your own ``HeaterParams``
(:doc:`/how-to/calibrate-simulator`).

Where the defaults come from
----------------------------

Every value in ``site_example_params(2)``, with what it was measured or
fitted on. "Retrain" values come from the weekly refit of one NWP500-65's
record on 2026-10-11, over the record to that date (from 2025-12-28),
except where a row gives its own span: the compressor and circulation
rows were refit on the record to 2026-10-24, and the tank's on the
record to 2026-10-26. They move a little at each retrain as the record grows; the range is
the one seen over the retrains from 2026-08-08 to 2026-10-18.

**Fitted at each retrain**

.. list-table::
   :header-rows: 1
   :widths: 26 14 34 26

   * - Field
     - Value
     - Fitted on, and its error
     - Range over retrains
   * - ``loss.ua_side_btu_hr_f``, ``ua_bottom_btu_hr_f``,
       ``ua_top_btu_hr_f``; ``tank.conductance_btu_hr_f``
     - 3.06, 0.559, 0.557 BTU/hr per degF; 0.511 BTU/hr per degF
     - The layered tank's terms, fitted together
       (``sim_calibrate.calibrate_changes``, ``sim.tank_fit``) on 266
       quiet windows, 254 metered draws and 118 recoveries, 2026-04-16
       to 10-26, each started from the record's replay of the day
       before it, with the compressor's start stirring the layers, no
       hold imposed and the heat pump's maps read along their planes,
       against a sensor of the air beside the heater: both probes'
       error every 10 minutes, 2.26 degF RMS over the events. Fitted on
       the record to 2026-09-18, they scored on the 59 quiet windows
       after it 0.198 and 0.483 degF RMS (upper, lower), and on 46
       draws 0.298 and 2.04 (:doc:`/explanation/simulator`). The
       bottom's loss fell from 0.887 with the hold imposed to 0.168
       with the maps held at their spans' edges: the start's stir
       brings the bottom's cold to the lower probe. Read along its
       plane, the heat at the cold water a recovery starts from is
       more than the edge's, and the bottom gives back 0.445; with a
       circulation run's pipe returned at its measured volume and its
       own water risen to its level, 0.559.
     - 2026-10-27 to 10-29
   * - ``tank.upper_probe_height``, ``lower_probe_height``,
       ``upper_probe_spread_gal``, ``lower_probe_spread_gal``,
       ``lower_probe_offset_f``
     - 0.902, 0.476; 5.22, 2.21 gal; 1.13 degF
     - The same fit. The upper probe's 0.902 puts 6.1 gal of the 63.2
       above it, against the 5.3-7.3 gal the delivered water lags it by
       (:doc:`/explanation/draws`).
     - 2026-10-27 to 10-29
   * - ``tank.inlet_mix_gal``, ``tank.condenser_span``
     - 14.2 gal; 0.154-0.289
     - The same fit, the span on the recoveries. The span's top sits
       under the lower probe (0.476): the start's stir pools the water
       under it, and the probe, above the pool, holds while the
       condenser heats it back. With the hold imposed it was
       0.147-0.576, over the probe.
     - 2026-10-27 to 10-29
   * - ``compressor.heat_btu_h`` and its slopes per degF of air and
       of water
     - 4,499 BTU/hr at 65 degF air and 120 degF water; +55.5 per degF
       of air, -15.9 per degF of water
     - 38 stretches of 20 minutes or more of draw-free climbs with the
       tank mixed (3,059 minutes, 2026-04-21 to 10-22), the air 61.2 to
       88.7 degF and the tank 114.8 to 143.3 degF: 236 BTU/hr RMS. The
       air slope is the one ``recovery-speed`` measures on whole
       recoveries
       (:doc:`/explanation/recovery-speed`).
     - First fitted 2026-10-26
   * - ``compressor.power_w`` and its slopes
     - 408.9 W at 65 degF air and 120 degF water; +1.02 per degF of
       air, +2.72 per degF of the condenser's water
     - 3,562 ten-minute blocks of metered climbs over 211 runs,
       2026-04-16 to 10-26, each at the condenser's water on the
       record's replay (``heat_pump_fit.in_condenser_water``), where the
       walk reads the map: 65.8 to 143.8 degF, 4.7 degF under the lower
       probe on average, the air 53.6 to 89.3 degF: 12.7 W RMS. Read
       there, the map fitted on the lower probe (401.7 W, +0.21, +2.85)
       priced these blocks at 406.9 W against the 418.2 W metered, at
       18.1 W RMS. The runs before 2026-04-16 have no record to replay.
     - 2026-10-29
   * - ``compressor.heat_domain_air_f``, ``heat_domain_water_f``,
       ``power_domain_air_f``, ``power_domain_water_f``
     - 61-89 and 114-144 degF; 53-90 and 67-145 degF
     - The span each map was fitted over, to the whole degree. Each is
       read along its plane past it as within it; a recovery whose air
       is outside the heat's span, or that heats with the probes' mean
       outside its water span, says ``heat_map_out_of_domain``.
     - Set by each fit
   * - ``compressor.start_hold_min`` by ``start_hold_after_min``
     - 0 min in every band
     - No hold is imposed: the start stirs the cold water under the
       condenser into the layers it wraps, and the lower probe holds
       while that is heated back (:doc:`/explanation/recovery-speed`).
       A caller's own hold still applies.
     - Default
   * - ``controller.hp_stop_overshoot_f``
     - 0.9 degF
     - The median overshoot at the stop of 31 draw-free run-ons,
       2026-04-21 to 10-22.
     - First fitted 2026-10-26
   * - ``SITE_CIRCULATION``
     - 6.86 gal, 14.6 BTU/h per degF, +3.74 degF, 0.72 h, 1.397 gal/min
     - The pipe measured on one run on 2026-10-29 (``measure_pipe``):
       35.7 min at constant pressure after a 4 h rest, nothing else
       acting on the tank. The return rose half way to its steady
       value at 6.86 gal of the pump's flow and held 1.6 degF under the
       upper probe at 1.08 gal/min. The rest and the cooling fitted
       with it (``fit_return``) on 122 runs with the compressor off,
       2026-04-04 to 2026-10-24: in five-fold cross-validation the mean
       absolute error is 399 BTU a run, against 300 for the effective
       19.36 gal loop it replaces, whose return came back at the tank's
       own temperature. Most of those runs end as the front arrives
       (the pump stops at a 102 degF return), and the front spreads
       over 5 to 12 gal. Held out from 2026-09-18, the recoveries'
       durations are 27.2 min off against 30.9. The volume is in the
       pump's gallons; the house's meter has read about 0.3 gal/min
       less since 2026-09-14. The flow is the median over the 14 days
       before a retrain.
     - folds 2.3-4.7 degF, 0.70-0.74 h

**Measured on the heater**

.. list-table::
   :header-rows: 1
   :widths: 30 18 52

   * - Field
     - Value
     - Evidence
   * - ``tank.volume_gal``
     - 63.2 gal
     - The heater's own energy fields put the tank at 156.6 Wh per degF
       (:doc:`/explanation/tank-energy`).
   * - ``element.element_w``
     - 5,148 W
     - Element-only minutes in the record (90 % CI 5,104-5,176 W,
       168 min). A later refit over 95 element runs gave 5,143 W. Two
       commanded runs on one evening read 5,219 and 5,242 W.
   * - ``element.upper_dead_time_min``
     - 1.21 min
     - 29 upper-element runs on 21 days (:doc:`/explanation/heating-elements`).
   * - ``element`` start and stop thresholds
     - 0.54, 0.72, 1.44, 1.8, 1.62 degF; 104.9 degF
     - The entry-threshold sweeps and the off point
       (:doc:`/explanation/heating-elements`).
   * - ``element.upper_reengages_below_setpoint_f``
     - 4.1 degF
     - 12 High Demand restarts mid-stint (90 % CI 3.8-4.5 degF); the
       four of 2026-04-26/27 came at 3.78-4.14 degF short, each about
       3 minutes to the setpoint. The simulator starts High Demand's
       upper element there later in a stint, and Electric's, which is
       not measured.
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
   * - ``controller.hp_air_range_f``, ``controller.hp_water_range_f``
     - 41-113 degF, 50-149 degF
     - The heat pump's operating range, from the user's manual
       (3.13.1, Heat Pump Operation Prevention): outside it the heat
       pump does not run and the elements heat the tank (3.13.4). The
       water is read at the lower zone. Not measured: the record's air
       ran 45.9-89.3 degF, and no takeover by the elements is on it.

**Fitted at one installation** (``unfitted`` in ``default_params``)

.. list-table::
   :header-rows: 1
   :widths: 30 18 52

   * - Field
     - Value
     - Evidence
   * - ``draw.inlet_temp_f``, the valve line
     - 72.4 degF, (53.56, 0.485)
     - Long-draw plateaus on the cold supply, and five plateaus at the
       valve outlet (:doc:`/explanation/draws`). ``default_params``
       takes no valve and the rating test's 58 degF
       (``RATING_INLET_F``, 10 CFR 430, Subpart B, Appendix E).
   * - ``draw.climate_f``
     - (61.3, 19.9) degF
     - The installation's weather station: its monthly means over
       2025-11 to 2026-10 (``cold_supply.climate_of``). Not in
       ``default_params``: give your own (:ref:`the mains by season
       <mains-by-season>`).
   * - ``readiness``
     - the Readiness section above
     - The bath tests (:doc:`/explanation/draws`).

**Engineering values**, not measured on the heater: the maps' cross
terms (0: the record does not place them). ``CompressorParams()`` is
this fit, rounded.

**The layered tank's priors** (``TankParams()``, ``LossParams()``):
where a calibration starts, and what a heater without one is walked
with. Heights are shares of the volume from the bottom.

.. list-table::
   :header-rows: 1
   :widths: 30 18 52

   * - Field
     - Value
     - Where it comes from
   * - ``tank.layers``
     - 12
     - HPWHsim's layer count.
   * - ``tank.upper_probe_height``, ``tank.lower_probe_height``
     - 0.85, 0.2
     - Where the record's draws first move each probe.
   * - ``tank.upper_element_height``, ``tank.lower_element_height``
     - 0.72, 0.15
     - The upper element with 17.5 gal of the 63.2 above it, the volume
       its rise on 29 clean runs (2.01 degF/min) heats; the lower near
       the bottom. Not fitted: an element heats its layer and the ones
       above, so the height acts in whole layers. Of twelve, 0.72 heats
       21.1 gal and the upper probe climbs 1.59 degF/min; 0.75-0.833
       heats 15.8 gal, 2.00 degF/min. The record's 24 element runs from
       2026-04-16, most with water drawn or the compressor running,
       read the upper probe to 7.9 degF RMS at 0.72 against 10.2 at
       0.79, so 0.72 is kept.
   * - ``tank.condenser_span``
     - 0-0.45
     - The coil wraps the lower stratum: recoveries heat 0.44-0.48 of
       the tank while it is stratified.
   * - ``tank.inlet_mix_gal``
     - 9 gal
     - The water an inflow mixes with as it enters. A starting value;
       the fit finds 14.2 gal.
   * - ``tank.conductance_btu_hr_f``
     - 0.89 BTU/hr per degF
     - The water column's, end to end (10.7 between each pair of twelve
       layers): its slowest mode, ``mass / (pi^2 tau)``, closes a gap
       between the probes on about 60 h, near the record's 59 h
       (:doc:`/explanation/standby-loss`). A starting value; the fit
       finds 0.42.
   * - ``tank.upper_probe_spread_gal``, ``tank.lower_probe_spread_gal``
     - 0 gal
     - How far along the column each probe feels the water: it reads the
       layers weighted by ``exp(-distance / spread)``. 0 reads the
       point; the fit (``sim.tank_fit``) finds a few gallons.
   * - ``tank.lower_probe_offset_f``
     - 0 degF
     - What the lower probe reads above the water it feels: the probes'
       disagreement in a mixed tank (about 0.5 degF on the record, the
       lower higher, after a recovery).
   * - ``loss.ua_bottom_btu_hr_f``
     - 1.8 BTU/hr per degF
     - About 90 BTU/hr over a 50 degF gap to the air, from the bottom
       layer alone. A starting value; the fit finds 0.89.
   * - ``loss.ua_top_btu_hr_f``
     - 0 BTU/hr per degF
     - The top's loss, from the top layer: the head, the fittings and
       the pipes.
   * - ``loss.ua_side_btu_hr_f``
     - 5.0 BTU/hr per degF
     - The sides' loss, shared equally by the layers: an engineering
       value for an insulated tank of this size.

``params_to_document`` and ``params_from_document`` in
``nwp500.sim.params`` write and read parameters as a JSON document
(schema ``heater-params/2``; a ``heater-params/1`` document is refused,
and a heater fitted under it is calibrated again). ``sim.codec`` writes
a scenario with its
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
       ``tank_uncalibrated``
     - A term calibration could not fit on this heater (a recovery's
       duration; its energy and COP; the tank's losses, probes and
       condenser) is the base's (``HeaterParams.unfitted``).
   * - ``draw_uncalibrated``
     - The installation's draw terms (its valve's line and inlet) are
       another installation's (``default_params()`` marks them,
       ``INSTALLATION_TERMS``), not fitted from this one's meter. Any
       answer with draws says it, and the readiness answer always: its
       gallons are drawn through them. Fit them and drop ``draw`` from
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
   * - ``tank_profile_estimated``
     - The tank's layers were made of its two probes
       (``HeaterState.layers_f`` not given), not walked from its
       history: the probes do not say how the water between and below
       them is layered.
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
     - The readiness answer's gallons meet an inlet nobody measured at
       the mains (``time_to_ready`` without ``inlet_measured``).
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
   * - ``recovery_path_linear``
     - A recovery's path is a straight line from start to end, with its
       energy unknown: a recovery model gave the duration and the
       physics had no path to stretch onto it (its integration failed
       or was truncated, or the model clamped the duration).
   * - ``recorded_write_not_modelled``
     - A recorded write into Vacation or Power Off was left out of a
       replay, its setpoint too.
   * - ``heat_pump_unavailable``
     - The heat pump was outside its operating range
       (``controller.hp_air_range_f``, ``hp_water_range_f``) in the
       walk, or is at the answer's start, in a mode that runs it; or
       the answer's stop (its target and run-on) is over its top, which the
       elements finish. A
       ``forecast`` or ``active_cycle`` answer is still the heat pump's,
       which the heater will not run; ``next_recovery`` is
       ``unavailable``, and ``time_to_ready``'s walks heat every mode as
       Electric does (Heat Pump mode from the heater's own trigger).
   * - ``envelope_fallback_unverified``
     - The elements heated in the heat pump's place, outside its range,
       by Electric's rule (the upper element, then the lower): the
       manual's rule, not seen on the record.
   * - ``heat_map_out_of_domain``
     - A recovery's air is outside the span the heat pump's heat was
       fitted on (``compressor.heat_domain_air_f``), or it heats with
       the probes' mean outside the heat's water span
       (``heat_domain_water_f``, the water the heat was fitted against
       on mixed climbs), so its heat is the plane carried past the
       record.

The ones about the heater's own rules, each resting on the device runs
:doc:`/explanation/what-starts-a-recovery`,
:doc:`/explanation/tou-recovery-cap` and
:doc:`/explanation/heating-elements` describe:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Reason
     - What it says
   * - ``tou_cap_projected``
     - The TOU cap stopped a recovery short of its target: at the
       cap's level inside a window, as a window opened, or before it
       heated at all.
   * - ``mode_write_held_projected``, ``mode_write_start_projected``
     - A mode write inside a TOU window was held to the window's close,
       and (the second) started the compressor, as a write inside a
       window does.
   * - ``heat_pump_entry_held_spec_only``
     - A reservation entry's Heat Pump write inside a window was held:
       that rests on the documented rule for entries, measured only on
       an element mode's entry.
   * - ``resume_dropped_heating_disabled_changed``
     - ``HeaterState.resume`` was not gone on from: the scenario is in
       Vacation or Power Off and the walk that left it was not, or the
       other way round, a write the simulation holds no rule for. The
       walk starts from the tank and the history.
   * - ``element_mode_dropped_projected``
     - A TOU window's opening dropped an element mode to Heat Pump.
   * - ``write_start_uncertain``
     - A setpoint or mode write, or a window's drop of an element mode,
       left the tank where the record doesn't settle whether it starts
       the compressor.
   * - ``deficit_inside_the_start_threshold_bracket``
     - The upper zone's deficit on entering an element mode lies
       between the deficits seen to start the element and not to.
   * - ``element_model_small_n``, ``lower_element_nine_runs``,
       ``element_start_on_setpoint_raise_n1``
     - The element model rests on few runs: the lower element's on
       nine, Energy Saver's start on a setpoint raise on one.
   * - ``electric_later_starts_unverified``
     - Electric's elements started later in a stint: the upper element
       4.1 degF short of the setpoint, as High Demand's, or the
       heater's own trigger starting them by Electric's entry rule, as
       in the heat pump's place, from the tank a draw then leaves.
       The lower element after such an upper one, and a walk going on
       from either, say it too. Electric's own rule is not on the
       record.
   * - ``upper_zone_dips_during_the_lower_phase``
     - The upper zone dips while the lower element runs, and the model
       holds it.

The ones ``element_mode`` adds about its own answer:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Reason
     - What it says
   * - ``upper_element_does_not_start``
     - The upper zone is short of the setpoint, and no element starts on
       the write: the deficit is under the mode's entry deficit, the
       mode is already in force, the write is held in a TOU window, or
       heating is disabled.
   * - ``mode_already_in_force``
     - The mode asked about is the heater's own: the write changes
       nothing, and the stint is what the heater does in it anyway.
   * - ``ready_target_above_setpoint``
     - The ready temperature asked for is above the setpoint, where the
       element stops, and the stint does not reach it.
   * - ``truncated_by_switch_back``
     - ``switch_back_after_minutes`` ends the stint before its recovery
       does: a time it does not reach by then is None.
   * - ``recovery_cut_short``
     - Within the stint, a later mode write or the heater dropping the
       mode at a window (``element_mode_dropped_projected``) stopped part
       of the recovery, or a setpoint write stopped the compressor short
       of the new setpoint: there is no ``full_minutes``.
   * - ``tou_schedule_unknown``
     - TOU is on and its periods are not known: the stint's walk counts
       the heater's marker, or a window in force when that is unknown
       too.

The ones about readiness:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Reason
     - What it says
   * - ``tank_profile_estimated``
     - The gallons are the profile the two probes stand for: the
       scenario gave no layers (``HeaterState.layers_f``).
   * - ``bath_ready_within_probe_resolution``
     - A probe error of ``ReadinessParams.probe_resolution_f`` either
       way would flip whether the bath is ready now
       (``delivery.within_resolution``).
   * - ``draw_in_progress``
     - Hot water is being drawn now: the probes are moving.
   * - ``element_running``
     - An element runs now.
   * - ``heating_not_scheduled``
     - Not ready, and heating is disabled (Vacation or Power Off).
   * - ``heating_not_triggered``
     - Not ready, and the heater would not start itself within 24 h.
   * - ``time_to_ready_unavailable``
     - Not ready, and the heat pump's walk couldn't be completed.
   * - ``bath_waits_for_tou_window_end``
     - Not ready, and the TOU cap stops the next recovery short of the
       bath: the heat pump's walk gets there after the window ends.
   * - ``bath_not_reached_by_full_recovery``
     - Not ready, and the heat pump's walk does not cover the bath
       within ``READY_HORIZON`` (24 h).

Each mode's time is the scenario walked with that mode written at its
start (``simulate``, the mode's entry rule run as on a write; a mode the
scenario writes there is replaced, its later writes still take) to the
first instant its layers deliver the bath, and its energy the walk's
electricity to then. The walks keep the TOU windows the heater does
(``marked_windows``); with TOU on and neither its periods nor the
heater's marker known, a window is taken as in force throughout, and
the answer says ``tou_schedule_unknown``. The heat pump's walk's
reasons, to the bath, are the answer's; an element mode's row carries
the reasons its walk gives beyond the answer's (``ModeReady.reasons``).
A setpoint written outside the heater's range is a ``ValueError``, as
for ``simulate``.

A bath or shower volume not given is named in ``defaults_used``
(``bath_gal=``, ``shower_gal=``), not in ``reasons``. The readiness
model's standing caveats (the deliverable volume rests on the layered
tank's draws, checked on few drawdowns, and the line is a choice) are
left out of ``Readiness.reasons``.


Errors
======

``ValueError`` (or pydantic's ``ValidationError``)
   An input out of range, an unknown field, a naive instant, an
   unknown zone, a write outside the span, a write or a written
   reservation whose setpoint is outside the range the simulation runs
   (104.9-149.9 degF; the device's own limits are its
   ``DeviceFeature``'s), a draw window that does not end after it
   starts, an element mode that runs no element, an unknown
   ``volume_code``, or layers (``HeaterState.layers_f``) other than the
   parameters lay out.
``nwp500.sim.engine.SimulationError``
   The walk could not be completed, or a recovery ``forecast`` or
   ``active_cycle`` was asked for falls short of its target after 16
   hours (``tank_physics.RECOVERY_BOUND``; the message names it).
