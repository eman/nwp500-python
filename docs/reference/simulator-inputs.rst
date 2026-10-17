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
     - degF, the unit the physics were fitted in: the tank, the
       setpoint, the ambient and the inlet. The adapters convert the
       device's raw fields, whatever unit system the process has set.
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
     - US gallons.

Every input is validated when it is built. An unknown field, a value
out of range or a naive instant raises pydantic's
``ValidationError``, a ``ValueError``.

The **Source** column below says where a value comes from. A library
field is filled by the adapter named; "not reported" means the heater
does not report it, so the caller supplies it or the default is used.
Every default an answer used is named in its ``defaults_used``.


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
       (:doc:`/explanation/what-starts-a-recovery`); the adapter always
       fills it.


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
       (0.1 degC) is the device's reading now. **Not reported ahead of
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
       the result. A write to Vacation or Power Off is not modelled
       (``write_mode_not_modelled``).
   * - ``reservations``
     - None
     - A reservation schedule written at the start, replacing the
       heater's; it is in force whatever ``reservations_enabled``
       says. None keeps the heater's.
   * - ``tou_enabled``
     - None
     - The TOU switch, set at the start. None keeps the heater's.


Parameters: ``HeaterParams``
============================

The physics constants, passed beside the scenario. Each field records
whether it was ``measured``, ``fitted`` or an engineering ``default``
(``nwp500.sim.params.provenance_of``).

``default_params(volume_code)`` takes ``DeviceFeature.volume_code``
(``sim_adapters.params(feature)`` passes it):

.. list-table::
   :header-rows: 1
   :widths: 15 20 65

   * - Code
     - Model
     - Parameters
   * - 1
     - NWP500-50
     - The 65's, with the tank volume scaled to 50 gal nominal.
   * - 2
     - NWP500-65
     - Fitted on one NWP500-65 at 240 V, 2026-10-11.
   * - 3
     - NWP500-80
     - The 65's, with the tank volume scaled to 80 gal nominal.

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
     - Required: ``simulate`` raises ``ValueError``.
   * - ``compressor.compressor_constant`` above 0
     - No heat-pump recovery can be predicted, and a walk that needs
       one raises ``SimulationError``.
   * - ``draw.observability``
     - Draws do not move the tank.
   * - ``loss.ua_btu_hr_f``
     - The jacket loss falls back to ``loss.ua_baseline_btu_hr_f``.

``params_to_document`` and ``params_from_document`` in
``nwp500.sim.params`` write and read parameters as a JSON document
(schema ``heater-params/1``). ``sim.codec`` writes a scenario with its
parameters as one document.


Errors
======

``ValueError`` (or pydantic's ``ValidationError``)
   An input out of range, an unknown field, a naive instant, an
   unknown zone, a write outside the span, an unknown ``volume_code``,
   or parameters missing ``stratification_gap_tau_h``.
``nwp500.sim.engine.SimulationError``
   The walk could not be completed: most often a heat-pump recovery
   the parameters cannot predict, or one past the integrator's
   30-hour bound.
