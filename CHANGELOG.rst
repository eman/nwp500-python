=========
Changelog
=========

Unreleased
==========

Fixed
-----
- ``sim_adapters.book_from_changes`` read its flow as a sampled meter:
  a reading held 60 seconds (``FLOW_HOLD``) and the inlet's an hour,
  and flow rows more than an hour apart refused the book as a silent
  meter. A history of changes writes a row only when a value changes,
  so a steady draw counted for a minute and an hour at 0 gal/min was
  refused. Its flows, inlet and air now hold until the next change. It
  takes ``flow_outages``, a span with no anchor before it counting, as
  for a heater unheard, and ``inlet_outages``. No flow reading in force
  at the window's start is a ``ValueError`` (#219).
- ``sim_home_assistant.pump_runs`` ended a run 5 minutes after its last
  speed reading. A pump at a steady speed writes no row, so a long run
  read as 5 minutes. A speed now holds until it changes; ``stale``
  (``PUMP_STALE``) keeps the old rule for a sampled speed (#219).

Version 9.11.0 (2026-10-22)
===========================

Added
-----
- **The air from a weather entity without a model** (#214). With a
  weather entity and no ``location_air`` model,
  ``sim_home_assistant.HomeAssistantEnvironment`` fits one
  (``sim.location_air.fit``) on the last 3 days
  (``LOCATION_AIR_WINDOW``) of the air entity's readings, or with
  ``heater=`` the heater's own air reading while its compressor runs,
  against the weather entity's outdoor temperature, each reading from
  the unit it was recorded in (``HomeAssistantClient.outdoor_history``,
  ``parse_outdoor_history``). It projects the forecast through the fit
  when the readings the outdoor history covers span a day and follow
  the outdoor air at r 0.5 or more, and keeps it as ``fitted_air``.
  ``nwp-cli simulate --sources`` fits one the same way when the sources
  file has no ``[location_air]``.

Fixed
-----
- ``sim.params.params_from_document`` raised ``TypeError`` for a list
  field given as something else (``unfitted``, the draw domain ranges,
  readiness ``evidence``), past the ``ValueError`` it documents and
  that ``sim_live.overlay`` and ``nwp-cli simulate`` handle. It read a
  string, null or bool in a number field without complaint. Each is
  now a ``ValueError`` naming the field (#212).
- ``HomeAssistantEnvironment`` found no inlet plateau for a probe that
  held one value through a long draw's tail. Home Assistant's history
  writes a row only when a value changes, so the tail had one reading
  or none, under the plateau's 3. The probe's history is now read as
  the value in force every 10 seconds (``held``, ``PROBE_STEP``)
  (#216).

Version 9.10.0 (2026-10-22)
===========================

Added
-----
- **The heat book from a heater's values' changes** (#191).
  ``sim_adapters.book_from_changes`` books the tank's heat from
  ``ChangeRows`` and the instants the heater was heard from (a
  ``HeaterHistory``'s ``rows`` and ``observed``, as
  ``calibrate_changes`` takes them), with the same steps, anchor search
  and silent-meter refusal as ``book_from_history``. Like the rows, its
  flows are gal/min and its temperatures °F, whatever the preferred
  units. A span the heater
  wasn't heard from (a silence longer than ``max_gap`` of the heard
  instants, or an outage) breaks the book: it is read only from after
  the last one, and is None while the heater isn't heard at ``at``.
  ``book_steps_from_changes`` gives the steps, and ``silences`` the
  unheard spans.
- ``sim_adapters.cold_supply_f``: the mains' plateau with the probe in
  °F, reading no unit preference. The live source's inlet reads through it,
  so a preference changed while it runs changes nothing.
- ``sim_adapters.cold_supply(..., window=)``: how far back a long draw
  counts (72 hours by default).
- **The heat book's terms and the circulation loop's loss, fitted
  together** (#196). ``sim_calibrate.fit_book`` fits the book's
  compressor heat rate and slope with the air, its standby UA and a
  circulation loop's loss per gallon from a heater's values' changes,
  the household's draws, and the pump's runs with the loop's flow, each
  given apart from the other. The loss is fitted with the book's terms
  on the pairs of quiet full tanks with a run between. It needs 10
  pairs (10 with a run for the loss), and keeps the base unless the
  refit books the held-out latest fifth no worse, and unless a term
  reaches its bound (``BookTermsFit``). ``sim.calibration.fit_terms_l1``
  fits the terms exactly on ``RecordedBook.pair_terms``, within
  ``BOOK_TERM_BOUNDS``. ``sim_adapters.run_readings`` gives the book a
  loop's flow readings within its runs, each run's first held from its
  start, as the fit takes them, and ``sim_adapters.run_flow`` gives runs
  at a flow.
- **A scenario document over the live scenario** (#201).
  ``sim_live.overlay`` lays a scenario document over the heater's
  composed scenario, as ``nwp-cli simulate --live`` does, and the CLI
  now calls it: objects merge key by key (``sim.codec.merge``) and any
  other value replaces. The start, horizon and zone take defaults, and
  the parameters come from the caller, then the document, then the
  heater, then the defaults (``Built``).
- **The simulator's answers as documents** (#205).
  ``sim.codec.to_document`` writes ``Readiness``, ``Recovery``,
  ``RecoveryResult``, ``Forecast``, ``ActiveCycle``,
  ``ElementModeResult``, ``Deliverable``, ``Trace`` and
  ``HeaterProfile`` as JSON documents with ``schema_version`` and a
  ``kind`` (``DOCUMENT_KINDS``), as ``result_to_document`` does for a
  walk's result.
- **The live parts from values read** (#207).
  ``sim_live.heater_reading(status, feature)`` and
  ``live_schedules(status, reservations, tou)``: what
  ``LiveHeaterSource`` and ``LiveScheduleSource`` read, from a status,
  a feature info, the reservations and the TOU periods read any other
  way. Both sources now build their answers through them.

Fixed
-----
- The live source's inlet looked back 72 hours of wall time, an hour
  more or less than 72 hours across a clock change. It now looks back
  72 elapsed hours.
- ``book_from_history`` counted a missing meter reading (None or NaN)
  as the meter reporting, so a gap filled with them passed the
  ``METER_MAX_GAP`` check and was booked as no flow. Missing readings
  now count as silence.

Changed
-------
- ``parse_state`` and the simulate how-to say that over Home
  Assistant's REST API an entity's ``last_reported`` comes from a copy
  that a report of the same value doesn't renew, so a sensor holding
  one value for over an hour can read as stale.
- ``sim.calibration.RecordedBook`` prices a draw against each step's
  inlet, as the heat book does (``book.step_heat_btu``), where it priced
  it against the book's reference. Without an inlet the steps take
  ``inlet_default_f``, the reference by default, and nothing changes.
- ``max_gap``, ``GAP_SAMPLES`` and ``MIN_GAP`` are defined in
  ``sim_adapters`` and documented there. ``sim_calibrate`` still exports
  them.
- **The household's draws come from a demand entity** (#203). The
  simulator no longer works out when hot water was drawn from a water
  meter. ``sim_home_assistant.Entities.demand`` (``demand`` in a
  sources file) is a binary sensor on while the household draws hot
  water, with the circulation's water not among its draws; the live
  inlet's long draws and ``record_inputs``' ``drawing`` come from it
  (``demand_spans``). ``sim.cold_supply.plateau_t_cold``,
  ``sim_adapters.cold_supply`` and ``cold_supply_f`` take the draws as
  (start, end) spans (``draws=``) in place of the meter's flow and draw
  instants; ``ColdSupplyParams`` loses ``tick_s``, ``tick_gap_s`` and
  ``draw_gpm``.

Removed
-------
- ``Entities.meter_volume`` and ``meter_flow`` (and their sources-file
  keys), ``sim.meter``, ``sim_home_assistant.draw_spans``,
  ``volume_spans`` and ``reports_after``: the simulator's own reading
  of draws from a water meter.

Version 9.9.0 (2026-10-22)
==========================

Added
-----
- **A bottom loss in the standby model** (#187). Over one installation's 407
  quiet windows across ten months, a window that opens stratified loses
  heat at the bottom: its gap widens, its lower probe falls about 40 %
  faster than a mixed tank's, and its upper probe hardly moves. One UA
  on the whole tank could not represent it, and the fitted UA was a
  blend that cooled a mixed tank too fast, as after a cold season's full
  recoveries. ``LossParams`` gains ``bottom_loss_btu_hr`` and
  ``bottom_gate_f``: heat leaving the lower zone, of which the lower
  probe sees ``1 - exp(-gap / gate)`` (``sim.physics.tank.
  bottom_loss_reach``). The standby walk (``decay.project_decay``) and
  the recovery integrator charge it to the lower zone. A bottom loss of
  0.0, the default and what stored parameter sets carry, reproduces the
  model before it.
- ``sim.calibration.fit_loss`` fits the UA law and the bottom loss
  together, through the standby walk, on the quiet windows opening with
  a gap of 10 °F or less (``loss_windows``); ``fit_standby`` uses it.
  On the installation above, the lower probe's median error over ten
  hours fell from 1.25 to 0.77 °F from March to October and from 1.67
  to 1.05 °F over the winter (1.15 °F trained without the winter).
  ``StandbyWindow`` carries each window's probes and air, and
  ``standby_ends`` and ``standby_error`` walk a loss over windows.
- The report has the bottom loss and its gate, and ``keep_better``
  judges them with the standby loss, on the probes' error in each
  held-out window's fall, °F/h.

Changed
-------
- The standby loss is fitted only on quiet windows opening with a gap of
  10 °F or less: a wider gap is a draw's front closing, which the gap's
  time constant describes.
- ``keep_better`` scores the standby group on the probes' error in each
  held-out window's fall, walked as the simulation walks it, in place of
  the error in log UA, so a loss with a bottom term and one without are
  scored alike.
- The zone gap time constant is fitted with the bottom loss opening the
  gaps it relaxes (``fit_gap_tau``'s ``loss``, ``gap_paths``), in turn
  with the loss until it settles: a gap the bottom loss widens read as a
  pure relaxation pushed the constant long. ``keep_better`` judges the
  constant before the standby loss and fits and scores the loss on the
  constant kept.

Version 9.8.0 (2026-10-21)
==========================

Added
-----
- **Refine a fit without making it worse** (``keep_better=True`` on
  ``sim_calibrate.calibrate`` and ``calibrate_changes``, #184). Each
  group of terms holds out its latest evidence from its refit (the last
  fifth, once it has 10 items) and keeps the existing values unless the
  refit scores better there, by the error its own fit minimizes. The
  terms in a group are kept or replaced together. ``Calibrated.judged``
  records each judgement, and the report's reasons give both scores.
  ``sim_calibrate.score(done, params)`` scores any parameters on that
  held-out evidence.
- ``sim.calibration.split_recoveries``, ``recovery_minutes``,
  ``power_cycles`` and ``cop_cycles``: the evidence the compressor and
  power fits use, and their predictions, which ``fit_compressor``,
  ``fit_power_scale`` and ``fit_cop_scale`` now take from.

Fixed
-----
- **The report names compressor runs without an air temperature.**
  A recovery is timed against the air, so a run with none (no air
  given, and no heater ambient reading while the compressor runs) is
  left out of the recoveries. The report blamed the heater instead:
  "0 recoveries reached their target". ``Calibrated`` now counts the
  runs (``n_runs``, ``n_runs_without_air``), and the compressor term's
  reason and the notes say how many had no air
  (``sim_calibrate.air_unread_note``).
- ``sim.calibration.with_standby`` quotes the fitted UA at the ΔT the
  law was fitted at (50 °F). It kept the ``ua_ref_delta_t_f`` of the
  parameters it was given, so a refit applied over parameters quoted at
  another ΔT ran as a different loss law.
- ``sim.calibration.fit_cop_scale`` takes the integrator's COP on the
  heater's own tank (``HeaterParams.tank``), as the simulation does. It
  used the default tank's mass, so a heater with another tank was fitted
  against a COP the simulation does not run.

Version 9.7.0 (2026-10-21)
==========================

Added
-----
- **Calibrate from Home Assistant's history** (#179), for a heater with
  no recording of its statuses.
  ``sim_home_assistant.read_heater_history`` reads the heater's own
  entities a day at a time: the probes, what is heating, the in-use
  flag, the stop threshold, the operation mode, the error code, the
  power, the energy to setpoint and the heater's own air, each number
  from the unit it was recorded in. An entity that changes on every
  response (``heard``) says when the heater was observed.
  ``sim_calibrate.calibrate_changes`` fits on what it read, and gives
  the same ``Calibrated`` and ``report()`` as ``calibrate``.
- ``sim_adapters.ChangeRows`` and ``sim_adapters.change_history``: the
  calibration frame from each value's changes and the instants the
  heater was heard from, for any store of that history.
- ``History.states``: every row's state as written, numbers or not.
  ``HomeAssistantClient.read_history`` fills it (``parse_states``).
- ``sim_home_assistant.to_w`` and ``to_wh``.

Version 9.6.0 (2026-10-21)
==========================

Added
-----
- **Calibration outside the CLI** (``nwp500.sim_calibrate``, #177).
  ``calibrate``, ``Calibrated``, ``report``, ``Term`` and ``max_gap``
  moved here from ``nwp500.cli.calibration`` so an application can
  calibrate without ``click`` or ``rich``. ``calibrate`` takes
  ``HeaterParams`` or a parameters document as ``params`` and raises
  ``CalibrationInputError`` (a ``ValueError``). Its notes no longer name
  the command's options; ``nwp-cli simulate calibrate`` adds them.
- ``status_history.iter_read`` yields a recording's statuses one at a
  time.
- ``sim_adapters.add_inputs`` adds the air, its humidity, a meter's
  draws, the circulation's runs and the unobserved gaps to a frame
  ``sim_adapters.history`` built.

Changed
-------
- **A long history calibrates in bounded memory** (#177).
  ``sim_adapters.history`` reads its statuses one at a time and keeps
  only the frame's values, and ``sim_calibrate.calibrate`` takes the
  record's span and gaps from the frame, so a generator over day files
  is read once. 60 days of statuses (about 540,000) now take about
  150 MB instead of about 6 GB of parsed statuses. The drawing and
  circulating columns are computed per span instead of per row and
  span.

Documentation
-------------
- The calibration how-to says the recorder writes every status the
  heater sends and what that costs on disk, shows calibrating from
  day files with ``sim_calibrate``, adds calibrating in an
  application, and says what Home Assistant's 10-day retention means
  for a longer record.

Version 9.5.1 (2026-10-21)
==========================

Fixed
-----
- **A steady Home Assistant sensor no longer goes stale in the
  simulator** (#174). ``sim_home_assistant.parse_state`` dated a state by
  ``last_updated``, which moves only when the value or its attributes
  change. An air sensor holding the same value for over an hour failed
  ``fresh()``, and the simulation fell back to the default air
  temperature. A state is now dated by ``last_reported`` (Home Assistant
  2024.3 and later), then ``last_updated``, then ``last_changed``. The
  history parsers still date each change row by its change.

Version 9.5.0 (2026-10-20)
==========================

Added
-----
- **Bluetooth LE access to the controller** (``nwp500.ble``, optional
  ``ble`` extra). The NWP500 exposes a GATT service that carries the
  controller's native class-code protocol once the heater is put in pairing
  mode (with the heater off, hold Back and Power for five seconds; it
  advertises as ``HPWH1…``). The scan also lists a heater in Wi-Fi setup
  mode (``HPWH4610``), which answers nothing, and the CLIs pick an
  ``HPWH1`` heater over it.
  The package frames and parses those packets (header, class code, address,
  CRC-16/MODBUS), scans for the heater, and reads data classes with a
  matched request/reply client; ``python -m nwp500.ble scan`` and
  ``python -m nwp500.ble read`` dump the blocks. Checked on a unit: it
  answers a DIP-switch block, error history, four diagnostics counters, the stored
  time-of-use plan, device info, the controller serial numbers and a
  software-data block; the boiler parameter classes 51-54 do not answer, so
  installer parameters are not reachable yet. ``write_block()`` exists for
  the eventual parameter write and is marked experimental. ``read``
  dumps the classes the heater answers by default and exits 1 when none
  answered; the readers that decode a block raise ``CrcMismatchError``
  on a reply that failed its checksum.
  ``read_tou_records()`` decodes the stored time-of-use plan into
  ``TOUPeriod``, the cloud's model, reading the controller's 40-slot table
  whole (a ``TOU_PLAN`` read's payload byte is the last slot, not a
  length; ``build_tou_read()``). ``write_tou_records()`` stores a plan of
  up to twelve intervals (``build_tou_write()``: the NaviLink app's clock
  header, then the records in the read layout) and reads it back. It
  refuses to write over a longer stored plan, whose extra intervals no
  Bluetooth write can clear, and raises ``TouWriteError`` when the
  heater refuses or stores something else. ``TOU_PLAN`` is the only
  class written so far (``NWP500_WRITABLE_CLASSES``). A read that gets no reply
  is sent once more, since the first request on a new connection
  sometimes goes unanswered. ``DeviceInfoBlock`` (``DID``), ``ControllerSerials``
  (``MSCD``) and ``SoftwareInfoBlock`` (``MSWD``) use the cloud models'
  field names for the fields matched against them.
  ``read_sub_status()`` decodes the ``SSD`` block into two DIP-switch
  words (``SubStatus``), using the layout Navien's boiler service toolkit
  reads; it is unconfirmed on the NWP500.
  ``read_status()`` returns live status: the class-50 session command 200
  makes the heater push the ``RTMD`` block about every 300 ms until the
  connection closes, and ``RealTimeStatus`` decodes the fields checked
  against the MQTT status report, in standby and while heating (operation
  mode, state number, DHW temperature and setpoint, the six thermistors,
  superheat and EEV step), under the ``DeviceStatus`` names and
  conversions. A read ends the stream, and the next ``read_status()``
  starts it again. The
  heater's display unit is in no Bluetooth block, so Bluetooth
  temperatures follow the unit-system preference.
- ``nwp-cli --backend ble`` (with ``--ble-address`` or a scan) runs
  ``serial``, ``info`` and ``status`` over Bluetooth without signing in,
  and refuses other commands. Without ``--backend``, commands use the cloud as before.
  The handlers run unchanged against ``nwp500.ble.BleMqttAdapter``, which
  offers the MQTT client methods the heater serves over Bluetooth and
  raises ``BleUnsupportedError`` for the rest. Bluetooth temperatures use
  the cloud models' conversion and unit-system preference;
  ``DeviceInfoBlock.min_operation_temperature()`` follows the preference
  when ``celsius`` is not given (Fahrenheit without one, as before).
- **New REST endpoints.** ``NavienAPIClient`` gains
  ``get_push_settings()`` / ``set_push_settings()``
  (``/user/get-push-settings``, ``/user/set-push-settings``),
  ``record_filter_change()`` / ``record_cip_change()`` and
  ``get_filter_history()`` / ``get_cip_history()`` (the cloud's maintenance
  log; dates are sent ``YYYY-M-D`` without zero padding, as the app does),
  ``get_display_preferences()`` / ``set_display_preferences()``
  (``/device/preferences/format``; the cloud rejects it for the NWP500,
  the app only uses it for the IoT-module hydro unit), ``get_user_profile()`` (``/user/info``),
  ``get_firmware_detail()`` (``/firmware/info``; ``run_time`` is the
  estimated update time in minutes), ``delete_tou()``
  (``DELETE /device/tou``), ``get_manufacture_id()``,
  ``get_error_history()`` (``/device/error/list``; installer accounts
  only, an owner account gets ``COMMON_NOT_AUTHORIZED``), ``update_device_info()``
  (``/device/change-info``), ``list_simple_devices()`` and
  ``get_app_version()`` (unauthenticated; a 403 maintenance notice is
  returned as ``server_check_text``; ``nwp500.get_app_version()`` asks
  before sign-in, without a client). ``set_push_settings()`` keeps the
  current value of a flag left ``None``, since the app always sends
  every flag. ``get_error_history()`` entries carry the list's
  ``timeZone`` (``time_zone``, ``occurred_at_local``). New models: ``PushSettings``,
  ``DeviceInstaller``, ``FirmwareDeviceGroup``, ``FirmwareDetail``,
  ``DisplayPreferences``, ``SimpleDevice``, ``DeviceErrorHistoryEntry``,
  ``MaintenanceHistoryEntry``, ``UserProfile``, ``AppVersionInfo``. Push
  flags are 1 = on, 2 = off, the reverse of the device's on/off flags, and
  decode to ``True``/``False``/``None``. ``Device.installer`` and
  ``Device.alarm_info`` are parsed from ``/device/info`` as the app does;
  ``TOUSchedule.nickname`` is modelled.
- **AWS credentials renew without the password.**
  ``NavienAuthClient.refresh_session()`` posts to ``/auth/session/refresh``
  with the access token and updates only the AWS credential fields the
  server returns, as the app does when the MQTT connection fails with an
  auth error. ``secured_sign_in()`` posts to ``/user/secured-sign-in`` with
  the access token and overlays whatever token fields come back (observed
  live: the AWS credentials only; the JWTs are kept), which the app uses
  for auto-login. When the AWS credentials expire, ``ensure_valid_token()``
  and the context manager's stored-token check now try session refresh,
  then secured sign-in, and only then the password sign-in; both token
  steps are skipped when the access token has expired and cannot be
  refreshed. ``re_authenticate()`` tries secured sign-in while the access
  token is live, then the password sign-in, so a client restored from
  tokens alone can use it too.
  The MQTT client's deep reconnect calls ``refresh_session()`` after the
  forced token refresh. ``AuthTokens`` gained an optional
  ``aws_credentials_issued_at`` so a renewed AWS expiry survives
  ``to_dict()``/restore. Stored tokens without the field load as before.
- **Control failures are parsed and surfaced.** When the device refuses a
  control command it publishes on ``cmd/52/navilink-{mac}/res/ctrl-fail``
  instead of acknowledging it; the library silently dropped that message.
  It is now parsed into ``ControlFailResponse``
  (``ControlFailCode.DHW_CONTROL_INTERVAL_EXCEEDED`` = 2 is the only code
  the app interprets: the previous DHW control was too recent) and emitted
  as the ``control_failed`` client event (``ControlFailedEvent`` with
  ``own_command`` and ``reason``) for every device subscription, with a
  WARNING log. ``subscribe_control_fail_response()`` /
  ``unsubscribe_control_fail_response()`` add a plain callback.
- **MQTT Last-Will and app-connection presence.** Set
  ``MqttConnectionConfig.last_will_device`` to register the app's Last-Will
  on ``evt/52/navilink-{mac}/app-connection`` (``event.connection.status``
  0, QoS 1) so other clients learn when this one drops; every rebuilt
  connection carries it. ``subscribe_app_connection()`` /
  ``unsubscribe_app_connection()`` parse the topic into
  ``AppConnectionEvent`` and emit ``app_connection_received``
  (``AppConnectionReceivedEvent``). New ``MqttTopicBuilder`` helpers
  ``control_fail_response_topic()`` and ``app_connection_topic()``.
- **``DeviceStatus.air_filter_remaining_hours``**: the app's remaining
  filter life (``None`` when the reminder period is 0, else clamped at 0).
- **``DeviceStatus.minor_code``** (``minorCode``): the secondary alarm code
  the app shows as ``R%03d``; 101 is the one it lets the user reset.
  Defaults to 0 for payloads that omit it.
- **``DhwOperationSetting.STANDBY`` (0)**, the app's
  ``MgppOperationMode.STANDBY``. ``DeviceStatus.dhw_operation_setting``
  previously rejected a 0. It is status-only: ``set_dhw_mode()`` refuses
  it, as it now refuses any id outside 1-6. ``sim_adapters.settings()``
  refuses a Standby status, which the simulator does not model.
- **``DREvent.GRID_EMERGENCY`` (6).** The app declares CPE and Grid
  Emergency both as id 5 but decodes ``drEventStatus`` by array position,
  so raw 6 is Grid Emergency; ``CPE`` (5) stays "Customer Peak Event".
- **``UnitType``** NCB700 (22), NFB700_H (24), CAS_NFB700_H (25),
  NPF_SYSTEM (514); **``DeviceType``** IOT_MODULE (8), NFB700_MAIN (50),
  NFB700_SUB (51) (the app's names; ``NPF700_MAIN``/``NPF700_SUB`` remain
  as aliases) and ``HPWH`` as an alias of 52, which is the NWP500
  (``DefineData.HPWH_MODEL``), not an NPF700 WiFi module. A dumped device
  of type 50 or 51 now names it ``NFB700_MAIN`` or ``NFB700_SUB``.
- **A recovery model's inputs, through ``nwp500.sim.simulate``** (#165).
  Beside ``recovery=``, ``simulate`` takes what a learned model was
  trained with and brings: ``start_hold`` (a start's hold by the
  minutes since the compressor last stopped), ``running_hold`` (what
  is left of a running compressor's), ``lead_draws`` (draws recorded
  before the start), ``draw_hold_factor`` and ``physics_usable``. Each
  goes to the engine as given. Left at their defaults, no answer
  changes.
  Lead draws move the tank as the scenario's own draws do. Like them,
  they are refused on parameters with no fitted draw response
  (``draw_model_unsupported``), and those the model reads carry
  ``draw_uncalibrated`` and ``inlet_temp_modelled`` where they apply.
- **The air, its humidity and the inlet, live from Home Assistant**
  (#166).

  - ``nwp500.sim_home_assistant`` reads Home Assistant's REST API,
    read-only. ``HomeAssistantEnvironment`` is a ``sim_live``
    environment source:

    - the air is the hourly forecast projected through a
      ``location_air`` model, anchored to a reading beside the heater at
      most an hour old (without a model, that reading held);
    - the humidity is a reading at most an hour old;
    - the inlet is the plateau of the last 72 hours' long draws, from
      the inlet probe, the meter and the circulation's runs.

    Units come from each entity's ``unit_of_measurement``. A part that
    can't be read keeps its default, and the source says why.
    ``record_inputs`` reads the same entities over a recorded history.
  - ``nwp500.sim.meter.flow_gpm`` is a meter's flow from its volume
    reports and its forward rate: the net volume over a trailing 90 s
    where it holds at the draw line for 120 s, the rate elsewhere. It
    finds the long draws the inlet plateau needs where the rate alone,
    silent through a steady draw, misses some.
  - ``nwp-cli simulate run``, ``snapshot`` and ``calibrate`` take
    ``--sources FILE`` (or ``NWP500_SOURCES``), a TOML file naming the
    entities, with the token in an environment variable.
    ``calibrate`` reads the air, the humidity, the draws and the
    circulation over the record, which makes the quiet test exact.
  - ``sim_live.compose`` takes the heater's own air reading when the
    environment source has none.
- **An optional heater simulator, ``nwp500.sim``** (#150, first part). The
  core of a physics simulation of the NWP500: an R-134a compressor model
  coupled to a two-zone tank, standby loss, the heating elements, draws,
  and the heater's own controller (start triggers, the TOU hold and
  recovery cap, the restart lockout, reservation entries, setpoint and
  mode writes), walked as events by ``nwp500.sim.engine.simulate()``. It
  is a port of an engine checked against recorded data from one
  NWP500-65, and returns the same answers to the last bit. Install it
  with the ``sim`` extra (numpy, pandas, scipy). It performs no I/O,
  reads no clock and holds no module state, and ``import nwp500`` does
  not load it. An import-linter contract in ``tox -e lint`` keeps it
  from importing the MQTT or REST clients, aiohttp, the AWS IoT SDK or
  ``logging``.
- **The simulator's API** (#150, second part).

  - ``nwp500.sim.simulate(scenario, params)`` walks a frozen
    ``Scenario``: the heater's state, settings, history, schedules,
    environment, draws and the commands under evaluation.
  - ``recovery()`` answers "when will the tank be hot?", and
    ``standby()`` projects the tank coasting.
  - The TOU periods become the windows the heater holds, and the
    reservations become firings, with the local times in the
    scenario's zone (``sim.schedules``).
  - Results name every default they used.
  - ``default_params(volume_code)`` carries one NWP500-65's parameters,
    with the tank volume scaled for the 50 and 80 gal models.
  - ``sim.codec`` reads and writes scenarios as JSON documents.
  - ``nwp500.sim_adapters`` builds the inputs from ``DeviceStatus``,
    ``DeviceFeature``, ``ReservationSchedule`` and ``TOUInfo``, reading
    the raw fields so the unit preference cannot change them. It is
    where units are crossed: ``environment``, ``loads``, ``write`` and
    ``reservation_entry`` take a caller's values in the preferred units
    (degC and litres under ``metric``), and ``path``, ``temperature``
    and ``volume`` give a result's back in them. The simulator itself
    works in degF and US gallons.
  - Docs: a how-to (``docs/how-to/simulate-heater.rst``), from fetching
    the heater's data to evaluating a change before sending it; a
    reference of every input, its unit, default and source
    (``docs/reference/simulator-inputs.rst``); an explanation of the
    model and its accuracy (``docs/explanation/simulator.rst``); and the
    API reference.

  - Hot water at the tap: ``nwp500.sim.readiness(state, settings,
    params)`` gives deliverable gallons now; ``Loads.windows`` judge a
    shower or a bath (deliverable gallons and margin at the onset, and
    whether the delivered water ran cold); ``SimulationResult.delivery``
    is the delivered temperature along the walk (``sim.delivery``).
  - The heat book (``sim.book``): the tank's heat by bookkeeping, walked
    through the simulation as the engine's ``HeatLedger`` so a draw that
    spends it takes the zones down. Started from the caller's knowledge
    (``full_tank_book``) or their own record, never guessed from the
    probes.
  - ``HeaterParams`` gains ``readiness`` (the line, the outlet lag, the
    fall rate, the dip tolerance, evidence) and ``book`` parts, with one
    installation's measured defaults and their provenance.
  - Time to ready: ``nwp500.sim.time_to_ready(scenario, params)`` says
    whether the tank can run a bath, when it can in the heat pump and
    in each element mode with the energy to get there, and how many
    showers it is ready for, along the recovery the heater runs next
    (``next_recovery``) (``sim.ready``).
  - ``standby(..., settings=)`` says when the heater would start itself
    on the coast and why; ``element_mode`` projects a recovery in an
    element mode.
  - A walk with draws outside the range the draw terms were fitted over
    says ``draw_out_of_domain`` (``DrawParams.domain_upper_f``,
    ``domain_volume_gal``); a write or a written reservation outside the
    setpoint range the simulation runs is refused.

  **Behaviour notes.** Answers that a client carrying an earlier copy of
  this engine will see change at the switch:

  - When no ``RecoveryModel`` answers (none given, or it declines) and
    the physics integration stops at its bound short of the target,
    there is no recovery and ``simulate`` raises ``SimulationError``.
    The bound is no longer served as a duration.
  - A recovery's reasons keep the served recovery's own (a truncated
    integration, a model's diagnostics) beside ``recovery_low_confidence``.
  - ``mode_recovery``'s ``upper_end_f`` is the zone's own temperature
    when the element does not start or has nothing to do.
  - A draw during a recovery honours ``draws_on`` and is priced on the
    configured tank, not the 63.2 gal default.
  - No ``hp_lower_on`` disables only the lower trigger; the upper
    zone's at a TOU window's opening still starts the heater.
  - A draw at a draw window's onset counts its cold side when the window
    is judged.
  - TOU prices are compared decoded at their own ``decimal_point``; each
    period is laid out on the dates its day and season masks select
    before windows that touch are joined across midnight.
  - Scenario instants are held in UTC, so a horizon is elapsed time
    across a daylight-saving change; a scenario document keeps which
    fields were left to their defaults.
  - ``sim.book.SpanLoss`` lets a client charge a loss the book does not
    model; without one, the book charges none.
  - Circulation runs within 10 minutes of each other are one run over
    the whole schedule, so a coast boundary between them no longer
    charges each its own displaced volume.
  - ``default_params()`` has no mixing valve; ``site_example_params()``
    is the installation the values were fitted at, its valve included
    (``with_valve``, ``SITE_VALVE``). The core's draw functions default
    to no valve as well. Each parameter says whether it describes the
    heater or the installation (``scope_of``), and the frame it was
    fitted in (``note_of``).
  - Circulation (``sim.circulation``): an installation's runs
    (``Loads.circulation``, ``sim_adapters.circulation`` for a weekly
    schedule) charged as flowing draws and to the heat book while they
    run, on ``HeaterParams.circulation``; with none, nothing is charged.
  - The air where the heater stands, from the heater alone and a public
    forecast: ``sim_adapters.location_air_reading`` (the heater's own
    reading, only while the compressor runs) and
    ``sim_adapters.location_air`` (an outdoor forecast projected by
    ``sim.location_air``, anchored to that reading, with ``fit`` for
    one's own model). ``time_to_ready`` and ``next_recovery`` take a
    ``RecoveryModel``.
  - Calibration from the heater's own record (``sim.calibration``,
    ``sim_adapters.history`` to build one from ``DeviceStatus``
    readings): the standby loss law and the zones' mixing constant from
    quiet windows, then the compressor constant and evaporator approach
    from heat-pump recoveries that reached their target, then input
    power and apparent COP against the heater's own power readings, each
    reported
    with what it rested on (held-out error, windows used, a fit pinned
    on a bound). An element run counts as busy in the quiet test, not
    only the compressor and hot water in use.
  - ``forecast``: when a recovery must start to have the tank ready at
    a time, and whether it can (``feasible``, ``shortfall_minutes``),
    to the heater's own stop threshold or a partial charge, with
    ``no_heating_required`` (the lower zone at its target, or a zero
    energy count outside a TOU window), ``not_scheduled``, and the
    trajectory's electricity, stored heat and COP.
    ``active_cycle``: what is left of a running recovery, its physics
    estimate on the evaporator coil's live reading.
    ``Settings.hp_lower_off_f``, ``hp_upper_on_f`` and
    ``HeaterState.energy_to_setpoint_wh`` carry what they need, filled
    by the adapters; ``recovery`` says ``not_scheduled`` in Vacation and
    Power Off.
  - The heater's profile (``sim.profile``): its modes and their energy,
    setpoint range and step, depletion threshold and tank, under a
    revision digest; and ``recovery_as_of``, a kept recovery aged to
    now.
  - The element terms from a heater's raw record (``sim.calibration``):
    the upper probe's lag and rate as one line from clean stints
    (``element_stints``, ``fit_element_lag``), where each element
    switches off and what it draws per metered stint
    (``element_off_points``, ``element_power``), and the zones' rates
    and element power on the one-minute grid (``element_grid``,
    ``fit_element_rates``), each with day-bootstrap intervals.
  - Draws from a weekly draw forecast (``sim.draw_forecast``): an issue
    checked whole, its expected draws (rate x per-draw mean, the
    per-draw volume kept), the heater's draw windows, and the worst case
    of each window's long draws first (``forecast_loads``,
    ``simulate(withheld_windows=)``). A draw's domain is now judged by
    its per-draw volume where it carries one (``Draw.per_draw_gal``),
    not its fractional expectation.
  - The mains from an inlet probe (``sim.cold_supply``,
    ``sim_adapters.cold_supply``): the median plateau of recent long
    draws with circulation off and the meter reading flow, from minute 9
    of each; ``on_the_mains`` converts a book's gallons at it.
  - What the heater did over a range, from its record, as the model
    reads it: ``sim.record.Record`` (each signal's change rows, its
    writes and the heater's own drops, TOU switches and window edges,
    starts with elements corroborated by power;
    ``sim_adapters.record``), ``sim.attribution`` (why each recorded
    start happened) and ``sim.observed`` (modes and whether each was in
    effect, when each source ran, counted and attributed starts, energy
    per slot, the delivered temperature, and the record's gaps;
    ``sim_adapters.observe``). ``replay`` reads its writes from the same
    record.
  - The readiness evidence and the heat book's own terms from a metered
    record (``sim.calibration``, ``sim_adapters.draw_frame``): clean
    draws and their demonstrated volumes reduced to the frontier, with a
    time-ordered held-out check, and the cap after a cold lower zone;
    the book's compressor rate, its slope with the air, standby UA and
    circulation's loss fitted on re-anchors of full tanks
    (``RecordedBook``, ``fit_book_terms``), its error by anchor age, and
    the empty points in the book's frame and the drawable one, and the
    error bands (``book_error_btu``: the p90 pooled over anchors an hour
    to 18 h old, and the 18-24 h band's, each rounded up to 100 BTU).
    With a meter, the COP fit prices the heat each cycle's draws and
    circulation runs took, and the draws just before it
    (``metered_withdrawn``, ``metered_lead``; ``calibrate(draws=,
    circulation=)``), as the model's fit did, each run at the flow it
    ran at (``circulation_flow_at=``, ``flow_lookup``). What could not be fitted
    keeps the base's value and is named in ``HeaterParams.unfitted``;
    every answer it reaches says ``physics_uncalibrated``,
    ``energy_uncalibrated``, ``standby_uncalibrated`` or
    ``tau_gap_prior``.
    The probes' share of circulation's heat
    (``circulation_windows``, ``fit_ungated_observability``), fitted
    against the displaced volume it is used with.
    Circulation's terms from its own telemetry: each run's measured heat
    (``measure_runs``), the displaced volume that prices them
    (``fit_displaced_gal``), its recent flow and the flow a past run ran
    at (``recent_flow_gpm``, ``flow_lookup``), as the model fitted them.
    The book's response to a draw, fitted on the record's long draws by
    the procedures its values were fitted with: the cold front's place
    and width (``fit_front``), the lower zone's settling after a draw
    (``fit_front_settle``) and the upper zone's mixing
    (``fit_zone_mix``), each with a day bootstrap.
  - The heat book from a recorded history, as the model kept it:
    ``sim.book.Step``, ``book_steps`` (the anchor on a quiet full tank
    after a recovery, or a recovery's end during a draw; every step
    booked from it; the inlet the median of 3 h of a probe), and
    ``sim_adapters.book_from_history``, which grids the heater's
    statuses, a hot-water meter's flow, circulation's runs and flow and
    an inlet probe onto 10 s steps and books 18 h, else 72 h aged.
    ``CirculationParams.meter_share`` is the share of a run's flow the
    meter also reads; ``BookParams`` gains ``history_h``, ``draw_gpm``
    and ``inlet_window_s``.
  - ``sim_adapters.replay``: a past scenario from the statuses the
    heater reported, as the model's replay read its record: the state
    then, the compressor's last stop and the last heating from their
    edges, the recorded setpoint and mode changes as writes (but the
    heater's own drop to Heat Pump at a window), and the TOU switch's
    changes (``Schedules.tou_switches``, which the walk applies).
  - The heater's own TOU marker (``Settings.hp_upper_on_f`` raised):
    ``time_to_ready`` and ``element_mode`` read "in a window now" from
    it, and ``next_recovery`` lets it override the schedule for a
    recovery running now (``api.marked_windows``), as the model did;
    an unknown marker counts as in force. ``simulate(tou_windows_in_force=)``
    takes the windows to keep, and TOU on with no periods says
    ``tou_schedule_unknown``. ``element_mode(setpoint_f=)`` projects to a
    what-if setpoint while the heater's own decides the window test.
  - ``time_to_ready`` says ``inlet_temp_modelled`` when a booked answer
    converts at an inlet nobody measured (``inlet_measured=``, or a
    book whose steps measured it); ``next_recovery``'s coast loses the
    heat circulation takes on it as well as standby; a served recovery
    under 0.6 confidence says ``recovery_low_confidence``. ``standby``
    reports the gallons drawn and the heat they took, circulation's
    minutes and heat, and the mean air over the coast.
  - ``default_params()`` names the installation's book, readiness and
    draw terms in ``HeaterParams.unfitted`` (``INSTALLATION_TERMS``):
    they are one installation's fits, so answers they reach say
    ``book_uncalibrated``, ``readiness_uncalibrated`` or
    ``draw_uncalibrated``. A ``Record`` drops missing readings on entry
    and takes its installation's cadences and the heater's resting
    threshold (``drop_within``, ``element_power_slack``,
    ``resting_upper_on_f``). ``observe(profile=, revision_since=)``
    names modes by a heater profile. ``schedules.rule_windows`` lays out
    TOU rules that have no prices, such as a learned schedule. The
    engine, the tank physics and the physics models are documented as
    public (:doc:`/reference/python_api/sim`).
- **``nwp-cli simulate``, and the live sources it composes** (#151).

  - ``nwp500.sim_live`` reads what a scenario needs from the device:
    ``LiveHeaterSource`` (the state, the settings, the air and the
    tank size, from one status and one feature read) and
    ``LiveScheduleSource`` (the reservations over MQTT, the TOU
    periods over REST, the TOU switch from the status).
    ``compose()`` awaits them, and any other source with an ``async
    read()`` (``Given`` for a value in hand), into a ``Scenario``. A
    read with no reply raises ``LiveReadError``, as does a TOU read
    that fails while TOU is on. The simulator still imports none of
    it.
  - ``nwp-cli simulate run`` walks the heater as it is now, a scenario
    file, or the heater now with a scenario file laid on it
    (``--live``). Each part is chosen on its own: a flag
    (``--start``, ``--hours``, ``--tz``, ``--ambient``,
    ``--environment``, ``--inlet``, ``--draws``, ``--plan``,
    ``--params``), then the scenario file, then the device. It prints
    a table (the heating intervals, the energy by source, readiness,
    the draw windows and which ran cold, the defaults used), the
    result document (``--format json``) or the path (``--format
    csv``). ``nwp-cli simulate snapshot`` writes the heater and its
    schedules now as a scenario file to edit and replay. Without the
    ``sim`` extra the commands stop with an install hint.
    ``examples/simulator/`` has a scenario, a plan and an overlay to
    start from; :doc:`/how-to/simulate-heater` shows each use.
- **Record a heater's history and calibrate the simulator to it**
  (#152).

  - ``nwp500.status_history`` is the history's format: one JSON line
    per status, ``{"t": <ISO 8601 instant>, "status": <raw payload>}``.
    ``line()`` writes one and ``read()`` reads them back as
    ``(instant, DeviceStatus)`` pairs. It does no I/O and needs no
    extra.
  - ``nwp-cli simulate record HISTORY`` appends the heater's statuses
    to a file until stopped, by default asking for one every 30 s.
  - ``nwp-cli simulate calibrate HISTORY`` fits the standby loss, the
    compressor and the power to that history
    (``sim.calibration.calibrate``). It prints a row for each term: the
    value, what it was fitted from, its error, and whether it was
    fitted or kept the base's value, and why. ``-o`` writes the fitted
    ``HeaterParams`` document for ``simulate run --params``. The
    standby fit needs the air beside the heater, from a sensor
    (``--air``, a CSV file) or a constant (``--ambient``). Given, that
    air is the recoveries' air too. The heater's own reading, filled
    across the gaps between compressor runs, and an outdoor projection
    both biased the fitted loss, so neither stands in for the air.
    Without ``--humidity`` the fits get 50 %, their documented default.
    A gap between statuses of more than 4 times the record's usual
    spacing (at least 5 minutes) is unobserved, so no quiet window or
    recovery spans a stopped recording. If a write fails, ``record``
    stops with an error.
  - ``sim_adapters.history(..., max_gap=)`` marks such gaps: the
    sample before one is set to water in use and excluded.
  - :doc:`/how-to/calibrate-simulator` covers the recording, the air,
    the report, and what a history cannot tell (the draws, a
    circulation loop the heater does not run).
  - Three helpers the issue proposed are left out:

    - **A mains-temperature estimate from the air.** The draw terms
      were fitted against a measured inlet, so an estimated inlet
      would bias every draw.
    - **A draw-timing profile from the "hot water in use" flag.** The
      flag also fires on circulation, and the expected draws from such
      a profile never predicted better than no draws.
    - **A check against the daily energy totals.** Power and COP are
      fitted cycle by cycle.

Changed
-------
- **Recirculation mode values follow the NaviLink app.** ``RecirculationMode``
  had 2 and 3 swapped and 4 wrong: the app's
  ``MgppRecirculationOperationMode`` (sent by ``recirc-mode`` and decoded
  from ``recircOperationMode``) is 1 Always on, 2 Weekly, 3 HotButton only,
  4 No recirculation. The members are now ``ALWAYS_ON``, ``WEEKLY``,
  ``HOT_BUTTON_ONLY`` and ``OFF``; ``ALWAYS`` remains as an alias of
  ``ALWAYS_ON``. **Behaviour change:** ``BUTTON``, ``SCHEDULE`` and
  ``TEMPERATURE`` are removed, since their meanings were wrong; code that
  sent ``RecirculationMode.BUTTON`` (2) was selecting the weekly schedule.
  ``RECIRC_MODE_TEXT``, the ``recirc`` CLI command, the recirculation
  example and the protocol docs follow. ``model_dump()`` writes enum
  names, so a dumped status now says ``"ALWAYS_ON"`` for 1 (was
  ``"ALWAYS"``) and ``"WEEKLY"`` for 2 (was ``"BUTTON"``); code keyed on
  the old strings must follow.
- **Reservation mode 5 is Power Off, not Vacation.** Weekly-schedule
  entries carry the app's ``MgppReservationMode`` (0 not reserved, 1 Heat
  Pump, 2 Electric, 3 Energy Saver, 4 High Demand, 5 Power Off; there is
  no vacation entry), now the ``ReservationMode`` enum.
  ``ReservationEntry.mode_name`` resolves through it, so a mode-5 entry
  reads "Power Off" instead of "Vacation" and mode 0 reads "Not Reserved".
  **Behaviour change:** reservation writes (``add_reservation()``,
  ``update_reservation()``, ``build_reservation_entry()`` and the MQTT
  reservation validator) now accept mode 1-5 and reject 6, which was never
  a valid entry mode. An entry already on the heater with mode 6 (earlier
  versions documented 6 as Power Off) does not block the reservation
  helpers: they send the entries they did not change as they read them
  (``update_reservations(kept=)``). Changing such an entry needs a mode
  of 1-5. The simulator's reservation entries take the same numbering
  (``sim.inputs.EntryMode``); only 1-4 are modelled, as before.
- **``dr_override_status`` is an on/off flag, not hours.** The app decodes
  it with its 0/1/2 on-off enum and shows "DR applied" when it is 2. The
  field stays an ``int`` but no longer carries an ``hours`` unit; the new
  ``DeviceStatus.dr_override_active`` is True when it is 2.
- **Air-filter life comes from ``cumulated_op_time_eva_fan``.** The app
  computes remaining filter life as ``air_filter_alarm_period -
  cumulated_op_time_eva_fan`` and never reads ``air_filter_alarm_elapsed``.
  The two descriptions were the wrong way round; ``cumulated_op_time_eva_fan``
  is fan hours since the last filter reset and ``air_filter_alarm_elapsed``
  is unconfirmed.
- **``signal_app_connection()`` sends the app's message shape.** It
  published ``{clientID, timestamp}``, a shape nothing reads. It now
  publishes the NaviLink app's ``RequestLastWill`` envelope with
  ``event.connection.status`` 1.
- Sign-in and ``/auth/refresh`` requests now send the library's
  ``User-Agent`` and ``Content-Type`` headers, as every other request does.
- **The heater's own air reading is not as close as documented in
  every season.** ``sim_adapters.location_air_reading``,
  ``sim.location_air`` and the inputs reference said it read the air
  beside the heater within about 0.35 °F while the compressor runs.
  Measured against a sensor beside the heater, that held from August
  to October. From May to July the reading was up to about 2 °F warm,
  and in a run's first 2 minutes about 2.7 °F warm. The idle reading
  is about 6 °F warm, not 5.
- **The CLI logs to stderr.** It logged to stdout, so a warning could
  land in the middle of ``--json``, ``--raw`` or CSV output piped to
  another program. Output stays on stdout.
- **The package root loads its exports on first use** (PEP 562).
  ``from nwp500 import NavienMqttClient``, ``nwp500.DeviceStatus`` and
  ``nwp500.mqtt`` work as before, and type checkers read the same names,
  but ``import nwp500.sim`` and ``nwp500.sim_adapters`` no longer load
  the clients, aiohttp or the AWS IoT SDK (tested in a fresh
  interpreter).
- **Superheat is converted as a difference** (#153).
  ``DeviceStatus.target_super_heat`` and ``current_super_heat`` converted
  their raw tenths of a degree Celsius as absolute temperatures, so in
  Fahrenheit they added 32. Superheat is a temperature difference (suction
  minus evaporator), so they now use ``DeciCelsiusDelta``, as the
  ``*_diff_temp_setting`` properties already do. Raw 50 now reads 9.0 degF
  instead of 41.0 degF. **Behaviour change:** every Fahrenheit value drops
  by 32, so stored or charted Fahrenheit superheat from earlier versions is
  32 degF too high. Celsius values are unchanged. The protocol docs now
  describe both fields as differences.
- **Vacation accepts 1-99 days** (#155). ``set_dhw_mode()`` (vacation),
  ``set_vacation_days()`` and ``set_vacation_duration()`` rejected anything
  over 30 days. The NaviLink app's vacation picker and the front panel
  (User's Information Manual, section 3.4.5) both offer 1-99, so the
  library now accepts the same. The ``vacation`` and
  ``vacation-duration`` CLI commands follow.

Fixed
-----
- ``FirmwareInfo.device_group`` was typed as a string; the app reads an
  object ``{groupSeq, unitNum}`` (plus a top-level ``deviceGroupUnitNo``).
  It is now ``FirmwareDeviceGroup``, with a bare string still accepted.
- ``convert_tou()`` hard-coded ``userType: "O"``; it now sends the
  signed-in user's type from the sign-in response, defaulting to ``"O"``.
- **A reservation entry turns a powered-off heater on in the
  simulator.** The controller skipped entries while powered off, as in
  Vacation, on a misreading of the device test, which found that a
  powered-off heater fires the entry and turns on in its mode (two
  runs). ``Settings.powered_off`` tells power-off from Vacation; the
  entry is judged as a mode write out of power-off, and the result
  carries ``powered_on_by_entry``. In Vacation entries are still
  skipped.

Documentation
-------------
- **What the device tests and the record measured.** Three new
  explanation pages: :doc:`/explanation/recovery-speed` (heat output,
  minutes per degF, compressor power and efficiency, start-up energy,
  the air's effect, how much of the tank heats),
  :doc:`/explanation/standby-loss` (the jacket loss, a circulation run's
  heat and where it shows) and :doc:`/explanation/draws` (the delivered
  temperature, the probes through a draw, how much hot water is left,
  reading a cold-supply probe). The element pages gain hours and energy
  by mode, the off point and the probe's lag; scheduling gains write and
  entry timing; the simulator's Accuracy section gains time to ready and
  the lower zone after a draw.
- **Where the simulator's defaults come from.** A table in
  :doc:`/reference/simulator-inputs` gives each default parameter's
  evidence: what it was measured or fitted on, its error, and how far
  the per-retrain values move between retrains.
- **Accuracy figures corrected.** ``simulator.rst`` gave 18 % and the
  13 and 45 min deficit-band errors as physics alone; they scored the
  physics with a learned correction, and are removed. The "cold starts
  about 55 min short" figure is replaced by the recorded errors by time
  left. The lower trigger's in-window wait is given with its full count.
- ``unknown-values``, ``tank-energy`` and the MQTT protocol reference now
  cite the current NaviLink app release they were checked against.
- ``docs/openapi.yaml`` and ``rest_api.rst`` describe every endpoint above
  plus ``POST /auth/session/refresh`` and ``POST /user/secured-sign-in``;
  ``mqtt_protocol.rst`` documents ``res/ctrl-fail`` and the
  ``app-connection`` event / Last-Will payload; ``diagnose-mqtt.rst`` gains
  "Why was my command rejected?"; ``maintenance.rst`` gains a "Maintenance
  Log" section; ``authenticate.rst`` explains the password-free renewal
  chain.
- **Less noise.** Implementation notes, the docs' own revision history
  and where things were ported from are gone from the pages, and
  section titles are plainer. The ``sim`` extra is listed under
  :doc:`/reference/installation`'s optional dependencies.
- **Corrections from the device tests and the recorded history.** The
  explanation pages, the how-tos, the protocol reference and the
  simulator's docstrings said things later measurements contradict:

  - High Demand's element starts somewhere in (0.2, 0.4] degC short,
    not (0.2, 0.7]; Electric ran upper first in the commanded runs, but
    the record also has the lower running alone; the element-run and
    mid-stint counts are the record's.
  - Inside a TOU window the upper tank starts a cycle when it is more
    than 14.4 degF short, at the opening or later. A setpoint write
    starts one in 120 of 122 writes leaving the upper tank short (not
    about 70 %), a lowering to the upper tank or below in none, and in
    ``HEAT_PUMP`` a draw does not start one while the upper tank is at
    or above the setpoint. The restart lockout measured 5.5 min.
  - The simulator's accuracy figures are the ones measured with
    start-up charged once (3.6 % and 4.4 % low; starts 31 of 40 held
    out), and the heater's idle air reading is about 6 degF warm.
  - ``HYBRID_BOOST_MODE`` is also Energy Saver with an element running;
    ``touStatus`` means TOU is enabled, not that a period is in force.
  - A device has held at least 32 reservation entries and 20 TOU
    periods; a list write can be lost with no error, so read it back;
    a powered-off heater runs its reservation entries; forcing a full
    recovery with ``tou_override_status`` is untested.
  - The ambient effect on the compressor is about 1.18x, not 1.7x; the
    standby soak's figures, the 60 h gap prior and the circulation runs
    behind the lower-zone drop are stated as measured.
- **Docs that contradicted the code or the vendor's sources** (#155). Each
  now has one value with its source:

  - The mode-ID table in ``device_features.rst`` numbered Energy Saver 2,
    High Demand 3 and Electric 4. The IDs are Electric 2, Energy Saver 3,
    High Demand 4, as in ``DhwOperationSetting`` and the NaviLink app's
    ``MgppOperationMode``.
  - ``track-energy.rst`` used ``comp_running_minute_total`` and
    ``heater1/2_running_minute_total``, which do not exist. Lifetime run
    times come from the diagnostics query, in hours
    (``DeviceDiagnostics.ta_data.cumulated_op_time_comp``, ``_uhe``,
    ``_lhe``).
  - ``currentHeatUse`` is the ``HeatSource`` enum (0-3), not a bool.
  - ``drEventStatus`` is the ``DREvent`` enum, not a bitfield.
  - ``tou-recovery-cap.rst`` named ``dhw_outlet_temperature``, Home
    Assistant's name for ``dhw_temperature``.
  - Vacation is 1-99 days; the docs said 0-99 in some places, and the
    library said 1-30.
  - Anti-legionella heats to 140 degF (60 degC), defaults to a 7-day
    period, is adjustable from 1 to 30 days and ships disabled (User's
    Information Manual, section 3.14.2). The scheduling how-to said 158
    degF, a 14-day default, periods up to 90 days and "mandatory".
  - ``dhwTemperatureMin`` is the installer's minimum operation
    temperature: 95-113 degF, factory default 95 degF. 104.9 degF was one
    unit's setting, not a contradiction.
  - ``ambientTemperature`` is the air around the unit, per the manual;
    neither "intake" nor "outlet" is sourced. The heat pump runs only
    between 41 and 113 degF.
  - ``docs/explanation/advanced-features.rst`` is removed. Its weather
    thresholds, COP figures, DR bitfield, stratification tables and code
    sample were unsourced or wrong, and the sourced material is covered
    by the protocol reference, ``what-starts-a-recovery`` and
    ``tank-energy``.

- **Flow-rate units corrected** (#154). The protocol reference said
  ``currentDhwFlowRate`` and ``recircDhwFlowRate`` were tenths of a GPM and
  ``cumulatedDhwFlowRate`` was gallons, while the properties treated them as
  tenths of an LPM and as litres. The properties are right. Navien's
  NaviLink app (2.01.02, decompiled) shows ``currentDhwFlowRate`` as
  ``raw / 10`` LPM in Celsius and ``raw / 3.785 / 10`` GPM in Fahrenheit.
  The NWP500 manual lists the panel's water-flow reading in LPM even though
  the panel defaults to GPM. The app's diagnostics screen shows the heater's
  hot-water volume totals in whole litres in either setting. Flow rates are
  0.1 LPM and the cumulative counter is whole litres in both unit systems.
  ``device_status.rst``, ``data_conversions.rst`` and ``mqtt_protocol.rst``
  now say so, and ``DiagnosticsDhwUsage`` documents its units (litres, hours,
  minutes, counts) instead of calling them unknown. ``unknown-values.rst``
  notes that on the unit checked, ``cumulatedDhwFlowRate`` and every draw
  counter read 0 after 392 days in use, so a 0 there does not mean no water
  was used. Library output is unchanged. The raw fields no longer carry a
  fixed ``"GPM"`` or ``"gal"`` ``unit_of_measurement``, which contradicted
  their raw units. ``get_field_unit()``, which was already driven by
  ``device_class``, returns the same units as before. New tests pin both
  flow properties to the app's formula in each unit system.

Version 9.4.3 (2026-10-01)
==========================

Changed
-------
- **Raw reservation writes are now validated** (#148).
  ``update_reservations()`` and ``update_reservations_confirmed()`` sent
  their entry dicts unchecked, so an unknown mode such as 7, an hour of 99
  or a setpoint of 200 (100 degC) went to the device as-is. A Python
  ``True`` for ``enable`` was worse: the confirmed helper read it as 1,
  which means disabled. Every entry is now checked before anything is
  sent, with the same rules as ``build_reservation_entry()``: the six
  protocol fields present and plain integers, ``enable`` 1 or 2, ``week``
  a day bitfield, ``hour`` 0-23, ``min`` 0-59 and ``mode`` a
  ``DhwOperationSetting`` id. ``param`` is held to the setpoint range the
  heater reports in its feature data (``dhw_temperature_min_raw`` to
  ``dhw_temperature_max_raw``), which is requested if it is not cached;
  clearing the schedule with an empty list needs none. A bad entry raises
  ``ParameterValidationError`` or ``RangeValidationError``, and missing
  feature data raises ``DeviceCapabilityError``. Callers that wrote
  entries outside these ranges and relied on the heater to clamp them now
  get an error instead. The checks are also available on their own as
  ``nwp500.mqtt.control.validate_reservation_entries()``.

Documentation
-------------
- **New: what starts a recovery**
  (``docs/explanation/what-starts-a-recovery.rst``). The lower-tank
  turn-on setting is one trigger among several. Measured on one unit:
  outside a TOU window the lower setting reads 104.9 degF at every
  setpoint and never follows it; at a window's opening the upper tank
  starts a cycle when it is well below the setpoint, and the lower trigger
  waits for the close. **A control write re-evaluates**: outside a window,
  in ``HEAT_PUMP`` with the compressor off, a setpoint write leaving the
  upper tank below the new setpoint started the compressor within
  2 minutes in 112 of 117 writes (a median 30 s later), lowerings
  included. 46 of 81 mode writes made with the compressor off did the
  same. A setpoint dropped well below the upper tank stopped a running
  compressor within 5 s (one run). A lowered setpoint did not hold off a
  draw-driven start (one run, in ``ENERGY_SAVER``). The page also covers
  traps for anyone re-deriving this from history.
- **TOU window: the two open cases measured, and three more results.** In
  ``docs/how-to/schedule-operation.rst`` (one or two runs each): an entry
  scheduled after a window fires on its minute; a mode held in a window
  takes effect when the window ends naturally; writing ``HEAT_PUMP`` over
  a held mode withdraws it; turning TOU back on inside a window drops a
  running element mode; and the operation setting reports the configured
  mode, not activity. The section's first measurement date is corrected to
  local time (2026-09-19).
- **New: what the heating elements do**
  (``docs/explanation/heating-elements.rst``). The four
  ``he*TempSetting`` fields describe the thermostat, and **on entry to
  a mode the thermostat is not what runs the element**: in
  Electric and High Demand the on and off settings are the same value,
  and every ``he*DiffTempSetting`` reads 0. Measured on one unit by
  commanding the modes and watching, the start differential is
  **mode-dependent**, one bracket per mode: ``ELECTRIC`` at most
  **0.3 degC** below the setpoint, ``HIGH_DEMAND`` within
  **(0.2, 0.7] degC**, ``ENERGY_SAVER`` within **(0.8, 1.0] degC**.
  Whether the first two share one threshold is an open question, not a
  finding. At 0.7 degC short, High Demand runs the element and Energy
  Saver does not. These
  are **entry** thresholds, not thermostats: in High Demand's steady
  state this unit's history has the element on in 1 of 47 minutes
  0.2-0.3 degC short and 168 of 169 more than 2.2 degC short.
  Neither differential is published anywhere in the status message.

  **Later in a stint it depends on the mode.** From one
  unit's recorded history, 17 of 23 mid-stint upper-element starts in
  ``ENERGY_SAVER`` have the probe in the 39.4-41.1 degC band where
  ``heUpperOnTempSetting`` rests, a median 0.2 degC below the field -
  the element comes on as the probe reaches it. ``HIGH_DEMAND``, whose
  ON setting tracks the setpoint, re-engages a median 2.1 degC *below*
  it, which the field does not describe. So in ``ENERGY_SAVER`` entry is
  the exception and the reference description is the rule; in
  ``HIGH_DEMAND`` it is not; ``ELECTRIC`` is uncharacterised.
  ``data_conversions.rst``'s warning now says which applies when.
  A sampling note with it: the element runs in two very different
  lengths. Of 115 upper-element runs over eight months, 20 lasted under
  a minute (median 16 s), carrying 0.6 kWh against 93 kWh for the rest.
  They are real elements, and not negligible to the probe: a 20 s burst
  is ~0.3 degC. Because ``currentPower`` samples at a median 30 s, a
  one-minute-resampled power series can miss one entirely, making a
  5.5 kW element look like 0.5 kW. Resample power with a maximum.

  Confirmed on the device, one unit, 2026-09-21: in ``ENERGY_SAVER``
  the upper element engages near ``heUpperOnTempSetting`` rather than a
  fixed gap below the setpoint (setpoint lowered to 42.0 degC; a gap
  predicted 22 degC; it engaged at 39.8, three times). It then runs to
  ~0.9 degC under the setpoint-tracking ``heUpperOffTempSetting``, not
  to a fixed point. Raising the setpoint in that mode starts the element
  through the entry rule. And ``heUpperOnTempSetting`` rests at 40.5
  degC reliably only in ``ENERGY_SAVER``; in ``HEAT_PUMP``, about half
  the time.

  Also documents Energy Saver's entry behaviour (the element engages
  although ``heUpperOnTempSetting`` rests 33 degC below the tank), Electric's
  upper-to-lower handover and the upper probe **falling** 1.9 degC while
  the lower element runs, measured element power of 5,219 W against the
  5,000 W rating, and that a mode write may not take effect while a TOU
  window is in force. ``device_status.rst``'s Heating Elements notes now
  point at it.
- **currentInstPower includes the heating elements.** The field
  table and *Power and Energy Fields* in the protocol reference, and the
  ``current_inst_power`` field description, said it excludes element
  power; ``track-energy.rst`` said it includes it. On a 240 V NWP500-65
  it includes it: element-only minutes read about 5.1 kW, compressor
  and element together about 5.5 kW, and the tank's heat gain agrees.
  All four now say so, with the measurement and its limits (one model,
  240 V only). (#139)
- **TOU does not suspend reservations.** ``schedule-operation.rst``
  said twice that it does, and its own priority table said otherwise. On
  one NWP500, inside an active peak window, a reservation entry moved the
  setpoint at its scheduled minute, twice. What the window holds back is
  the entry's **mode**, as it does a direct ``set_operation_mode()``.
  The mode is held, not discarded: a mode written in the window took
  effect when TOU was switched off, and the upper element came on. The
  priority table and Important Notes are corrected, and a new section
  gives the measurements and their limits. ``heating-elements.rst`` now
  links to it instead of to the issue. (#141)
- **tank-energy: what selects the second branch, and where usable_energy
  under-reads.** ``tank-energy.rst`` left open what selects
  ``full_recovery_energy``'s second branch. On one NWP500-65 over 50,819
  ``HEAT_PUMP`` minutes, ``hpUpperOnTempSetting`` separates the branches
  with no exceptions: 104.9 degF on the primary, raised to about the
  setpoint during the afternoon TOU window on the secondary.
  ``energy_to_setpoint`` shifts by the same 2 degC. Because of that,
  ``usable_energy`` does not always hold up across the branch. In the window it
  caps at ``full_recovery_energy`` once ``energy_to_setpoint`` hits 0,
  up to about 3.6 degF short of the setpoint, and under-reads by up to
  561 Wh. The page and the ``usable_energy`` docstring now say so and
  recommend the thermistors in that case. The ``full_recovery_energy``
  and ``energy_to_setpoint`` descriptions in the model, the protocol
  reference, the API reference and ``track-energy.rst`` now note the
  window too. (#140)

Version 9.4.2 (2026-09-17)
==========================

Changed
-------
- **A dropped response message now says why it was dropped.** The typed
  response handlers declined a message in three places without a word: a
  topic that does not end in the required suffix, a payload with no data
  under the expected key, and a reply whose ``macAddress`` names another
  device. A caller watching for a reply that never reached its callback
  could not tell a dropped message from one the cloud never published, and
  the two want opposite fixes. Each branch now logs its reason at DEBUG,
  with the topic and MAC redacted as elsewhere, and guarded by
  ``isEnabledFor`` so the redaction regexes do not run on the normal
  dispatch path when debug logging is off.

Version 9.4.1 (2026-09-17)
==========================

Fixed
-----
- **The reconnect attempt counter never reset after a successful quick or
  deep reconnect.** Both build a new connection, so the SDK never calls
  ``on_connection_resumed``, the only place the counter was reset. Each
  later interruption started where the last one stopped: its first delay
  was longer and it reached the deep-reconnect threshold sooner. A
  long-running client saw the first delay grow from about 1 s to 12 s
  over five daily AWS IoT disconnects. The counter now resets whenever the
  backoff loop ends connected.

Version 9.4.0 (2026-09-12)
==========================

This release realigns the MQTT command set with what the NaviLink app
sends. The app (version 2.03.00) was decompiled and its request
builder compared with the library; every query it sends now has a
method, six commands it never sends were removed, and the recirculation
schedule write was corrected. Breaking changes are listed under
*Removed* and *Changed*.

Added
-----
- **Installer diagnostics query.** ``request_diagnostics()`` /
  ``subscribe_diagnostics()`` and the ``nwp-cli diagnostics`` command
  return the lifetime counters the app's installer screen shows: heat
  pump and element energy, days since installation, fault event counts,
  demand-response operation times, hot-water draw statistics and
  component run times and start counts, as
  :class:`~nwp500.models.DeviceDiagnostics`. The device answers the
  ``st/td/rd`` query with packed hex; the NaviLink cloud decodes it into
  JSON only when the reply topic has the app's five-segment form, so the
  library requests that form. Verified live: the energies and compressor
  and element run times match the energy query's lifetime totals.
- **Monthly energy query.** ``request_energy_usage_monthly()`` /
  ``subscribe_energy_usage_monthly()`` and ``nwp-cli energy --years``
  return one entry per year with twelve per-month items. Verified live.
- **Hourly energy query.** ``request_energy_usage_hourly()`` /
  ``subscribe_energy_usage_hourly()`` send the app's per-hour query. The
  NWP500 tested never answered it in four attempts, so it has no CLI
  command.
- **Recirculation schedule read.** ``request_recirculation_schedule()``
  and ``nwp-cli recirc-schedule get``; the write is exposed as
  ``nwp-cli recirc-schedule set``, which checks the JSON before
  connecting (known keys only, integers in range, at most 20 entries).
  The read was verified live on a unit that reports recirculation
  scheduling but has no pump (empty, disabled schedule); the write and
  its echo are unverified. The CLI reports a write as updated only when
  the echo matches what was written. ``RecirculationSchedule`` and
  ``RecirculationScheduleEntry`` fields are strict integers, so ``True``
  or ``6.0`` is rejected instead of coerced.
- **Firmware download info.** ``request_firmware_download_info()`` /
  ``subscribe_firmware_download_info()`` and ``nwp-cli firmware info``
  return :class:`~nwp500.models.FirmwareDownloadInfo`. The device replies
  on its own topic rather than a client-keyed one. Verified live.
- **Session end.** ``end_session()`` sends the ``st/end`` query the app
  sends whenever it leaves a device. No reply to it has been observed.
  Unlike other commands it is never queued while disconnected (it raises
  ``MqttNotConnectedError``), since a session end replayed after a
  reconnect would end the new session.
- ``MqttConnectionConfig.send_session_end_on_disconnect`` (default
  ``True``) controls whether ``disconnect()`` sends it.
- ``subscribe_firmware_commit_response()`` receives the reply to
  ``commit_firmware_update()``, which is requested on the app-form
  ``res/commit-ota`` topic that no other subscription covers.
- **Controls with app builder cases that had no method:**
  ``set_vacation_duration(days)`` (``goout-day``; the app has a builder
  case but no screen that calls it; verified live to change the day count
  without changing the operation mode),
  ``set_air_filter_life(hours)`` (``air-filter-life``; the wire value is
  hours divided by 500, matching the app's 0 or 1000-10000 picker;
  verified live) and ``reset_condenser_fault()`` (``cond-fault-reset``,
  installer-level in the app; acknowledged live, clearing effect not
  observable without a fault). CLI: ``vacation-duration``,
  ``filter-life``, ``reset-condenser-fault``.
- **Command codes** for every member of the app's ``DeviceControlMGPP``
  enum, with the declared-but-never-sent ones annotated.
- ``EnergyUsageResponse.type_of_usage``, ``get_year_data()``,
  ``MonthlyEnergyData.day`` and ``EnergyUsageDay.ep_usage`` /
  ``water_usage`` (declared by the app; not reported by the NWP500).

Changed
-------
- **Recirculation schedule models take the app's entry shape** (breaking).
  :class:`~nwp500.models.RecirculationScheduleEntry` is now
  ``enable``/``week``/``hour``/``min``/``mode``/``param`` like a
  reservation entry (``mode`` is the entry's pump on/off toggle in the
  app's editor) and :class:`~nwp500.models.RecirculationSchedule` carries
  ``reservation_use`` plus ``reservation`` instead of ``schedule``. The
  previous start/end window fields were not what the device accepts.
- ``MonthlyEnergyData.month`` is optional: monthly-query entries have no
  month.
- **``NavienMqttClient.disconnect()`` now sends ``st/end``** to every
  device that was passed to any subscription, as the NaviLink app does
  when it leaves a device. The publishes go straight to the connection,
  never into the offline command queue, stop if the connection drops,
  are bounded by a short timeout and never fail the disconnect. What it
  does to other clients connected to the same device (for example a Home
  Assistant integration) is not known; turn it off with
  ``MqttConnectionConfig(send_session_end_on_disconnect=False)``.
- **CLI energy summaries total the requested periods.** ``energy
  --month``, ``--months`` and ``--years`` printed the device's lifetime
  total under a per-month or per-year heading. Each summary now covers
  only the rows shown, and the lifetime total is printed once under its
  own heading. (The response's ``total`` is lifetime whatever is
  requested; checked live.)
- **Parameter validation.** ``set_air_filter_life()``,
  ``set_vacation_duration()`` and the daily, monthly and hourly energy
  queries reject non-integers (including ``True`` and floats) and
  out-of-range values; years must be 2000-2099 and ``--years`` drops
  duplicates. ``filter-life``, ``--year`` and ``--years`` reject bad
  input before connecting. ``request_energy_usage()`` now rejects an
  empty month list.

Fixed
-----
- **``configure_recirculation_schedule()`` published to the wrong topic
  with the wrong keys.** It sent ``{"schedule": [...]}`` on the bare
  ``ctrl`` topic; the app publishes RECIR_RESERVATION on
  ``ctrl/recirc-rsv/rd`` with ``reservationUse`` and ``reservation`` and
  asks for the echo on ``recirc-rsv/rd``.
- **``commit_firmware_update()`` published to the bare ``ctrl`` topic.**
  The app publishes OTA_COMMIT on ``ctrl/commit-ota`` and asks for the
  reply on ``res/commit-ota``; the library now does the same. Not
  exercised against a device.
- **Unsubscribing could remove the wrong handler.** When one callback was
  registered for more than one device-wildcard subscription (status,
  feature, firmware info), unsubscribing one removed whichever handler
  came first. Handlers are now matched on subscription kind as well.
- **Query replies could reach another device's callback.** Client-keyed
  reply topics are shared by every device a client queries, so with two
  devices subscribed a reservation, energy, TOU, diagnostics or
  recirculation reply reached both callbacks. Typed subscriptions now
  ignore replies whose ``macAddress`` names a different device.
- Recirculation read-backs in hex carry the unused ``param`` as ``0xFF``
  and in JSON as ``-1``; the model normalizes to ``-1`` so the two compare
  equal.
- **Protocol documentation** rewritten from the decompiled request
  builder and live captures: real topic structure, the anti-legionella
  modes (``anti-leg-on [days]`` / ``anti-leg-off``, not
  ``anti-legionella-setting``), the message example that paired the
  weekly-reservation code with ``dhw-temperature``, the undocumented
  16777226 reservation write, response shapes for every query, and the
  quick reference's invented ``header``/``body`` format with 0x11/0x21/0x31
  codes that never existed. Stale ``docs/protocol/`` paths in code
  comments and docstrings now point at ``docs/reference/protocol/``.
- ``models/schedule.py`` docstrings cited 33554444 (the hot button) for
  the recirculation reservation; it is 33554440.
- CLI reference: token cache path is ``~/.nwp500_tokens.json``, ``-vv``
  is a repeated ``-v`` (there was no ``--very-verbose``), and the
  ``--unit-system`` option and ``tou rates``/``plan``/``apply`` commands
  are documented.

Removed
-------
- **Six MQTT commands the NaviLink app never sends** (breaking):
  ``check_firmware_update()``, ``reconnect_wifi()``, ``reset_wifi()``,
  ``set_freeze_protection_temperature()``, ``run_smart_diagnostic()`` and
  ``update_weekly_reservation()`` with
  ``subscribe_weekly_reservation_response()`` and the
  ``WeeklyReservationEntry`` / ``WeeklyReservationSchedule`` models. The
  app's enum declares the first five codes but its request builder has
  no case for them, so the library's ``ota-check``, ``wifi-reconnect``,
  ``wifi-reset``, ``frez-temp`` and ``smart-diagnostic`` mode strings were
  invented. The app's weekly schedule is the ordinary reservation
  program: it writes with 16777226 on ``ctrl/rsv/rd``
  (``update_reservations()``), never with 33554438 or a ``rsv-weekly/rd``
  topic. The ``CommandCode`` members stay, annotated as declared only.

Version 9.3.2 (2026-09-01)
==========================

Fixed
-----
- **A null ``errorCode`` no longer makes ``/device/list`` unparseable.**
  The cloud returns ``"error": {"errorCode": null}`` on some devices.
  :class:`~nwp500.models.DeviceErrorSummary` typed the field
  ``ErrorCode | int``, so validation of the whole listing failed and every
  caller (including the Home Assistant integration, which could no longer
  set up) lost the device entirely. ``error_code`` is now
  ``ErrorCode | int | None`` and defaults to ``None``: a null means the
  cloud reported no code, which is not the same claim as ``NO_ERROR``.
  Callers that treated the field as always-present should handle ``None``.

Security
--------
- **MAC address no longer logged in the clear when a reservations
  unsubscribe fails.** ``fetch_reservations`` logged
  ``device_info.mac_address`` unredacted in its cleanup warning, while the
  identical warning in ``update_reservations_confirmed`` a few lines below
  passed it through ``redact_mac``. CodeQL flagged it as
  ``py/clear-text-logging-sensitive-data`` (high). Both call sites now
  redact.

Version 9.3.1 (2026-08-29)
==========================

``NavienMqttClient.request_tou_settings()`` is removed. Not a breaking
change in practice: the device never answered it, so no caller can have
been getting a schedule out of it. Code that still names the method will
now fail with ``AttributeError`` rather than time out. See Removed below.

Added
-----
- **REST fields the cloud added since the models were written.**
  ``/device/list`` now returns an ``error`` block (``errorCode``,
  ``errorOccuredTime``) and the ``descaling`` block previously seen only
  on ``/device/info``, and ``deviceInfo`` gained ``modelTypeCode`` and
  ``installerId``. None of these were modelled, and ``NavienBaseModel``
  ignores unknown keys, so all of them were silently discarded.
  :class:`~nwp500.models.Device` gains optional ``error``
  (:class:`~nwp500.models.DeviceErrorSummary`) and ``descaling``
  (:class:`~nwp500.models.DescalingInfo`) sections, and
  :class:`~nwp500.models.DeviceInfo` gains ``model_type_code`` and
  ``installer_id``. ``error`` makes the device's last recorded fault
  readable without an MQTT connection, including while the device is
  offline. Every new field is optional, so responses that omit them (such
  as ``/device/info``, which carries no ``error`` block) parse unchanged.
  ``error_code`` is typed ``ErrorCode | int`` (validated left to right, so a
  known code becomes an ``ErrorCode`` member and only an unknown one stays a
  plain int) so an unrecognised code cannot make a whole listing unparseable. ``docs/openapi.yaml`` is
  updated to match.

Removed
-------
- **``request_tou_settings()`` removed - the device has no MQTT read for its
  TOU schedule.** The method published a ``CommandCode.TOU_RESERVATION``
  message to ``ctrl/tou/rd`` carrying only ``controllerSerialNumber``, then
  waited for a reply on ``res/tou/rd``. No reply ever comes: a live device
  with TOU provisioned (``program_reservation_use`` true, a valid controller
  serial, and a plan the REST API returns in full) stayed silent for 45
  seconds. ``ctrl/tou/rd`` with that command code is the *write* - it is what
  :meth:`~nwp500.NavienMqttClient.configure_tou_schedule` publishes and what
  the vendor app publishes from its TOU editor
  (``TouScheduleViewmodel.setPublishMgppControlTou``), and the device answers
  on ``res/tou/rd`` only to confirm such a write. The vendor app reads TOU
  over REST, which is the only TOU read the protocol has.

  Beyond returning nothing, the call published a write-shaped command with no
  schedule attached. This device ignored it (``touStatus`` was unchanged
  across repeated calls), but a firmware that took it at face value could read
  it as "store an empty TOU schedule".

  **Migration**: use :meth:`~nwp500.NavienAPIClient.get_tou_info`, which
  returns the stored plan: rate name, utility, ZIP code and the seasonal
  pricing intervals. The read itself is pure REST; it is keyed by the
  controller serial number, which only the MQTT device-info response
  publishes, so fetch that once and cache it.
  :meth:`~nwp500.NavienMqttClient.subscribe_tou_response` is unaffected and
  still delivers write confirmations. Enabling and disabling TOU
  (:meth:`~nwp500.NavienMqttClient.set_tou_enabled`, command codes
  ``TOU_ON``/``TOU_OFF``) is a separate path and is unaffected.

Fixed
-----
- **CLI ``energy --months`` no longer duplicates ``--month`` output.**
  ``handle_get_energy_request`` picked the view from the length of the
  month list, so ``--months 5`` took the single-month branch and printed
  the same daily breakdown as ``--month 5`` instead of the monthly
  summary. The handler now takes an explicit ``daily`` flag set by the
  option the user passed. ``energy`` also rejects ``--month``
  and ``--months`` together rather than silently preferring ``--month``,
  and validates the ``--months`` range and format the way ``--month``
  already did. All of that validation now happens while Click parses the
  arguments, so a bad invocation is a usage error (exit code 2) before any
  authentication or MQTT connection is attempted. Previously the command
  body raised ``ClickException`` after connecting, where ``async_command``'s
  catch-all reported it as an "Unexpected Error" with a traceback, and
  anyone without working credentials saw an authentication failure instead
  of the usage error. That catch-all now re-raises ``ClickException`` so any
  command can report a usage error as itself.
- **``DeviceFeature.mixing_valve_use`` now reads the device's actual key.**
  The field was aliased to ``mixingValveUse``, but the device sends
  ``mixingValueUse`` - "Value", not "Valve" - and the base model ignores
  unknown keys, so the field silently reported its ``False`` default on
  every device regardless of whether a thermostatic mixing valve was
  supported. The CLI's "Mixing Valve" capability row was wrong for the
  same reason. The misspelling is Navien's own: it appears in the vendor
  app's ``KDResponseMgppDid$Feature`` class and in
  ``docs/reference/protocol/device_features.rst``, which documented the
  wire spelling correctly all along.

- **``firmware_payload_capture.py`` captured almost nothing.** Its wildcards
  covered ``cmd/{type}/{client_id}/res/#`` and the event topic, but the device
  acknowledges control and query commands on
  ``cmd/{type}/navilink-{mac}/{client_id}/res``, which neither pattern
  matches, so the device status and device info responses were missed, along
  with every request published on the device path. A capture run recorded 2
  payloads where it should have recorded 11. It now also subscribes to
  ``cmd/{type}/navilink-{mac}/#``, which also picks up traffic from
  other clients on the same device. Query results the device routes back to a
  client-keyed topic, such as reservations and energy usage, were already
  covered by the existing response wildcard.

Version 9.3.0 (2026-08-03)
==========================

**BREAKING CHANGES**: two independent corrections land together.

Tank energy values were wrong in two ways, a 2.5x unit-scale error and
two actively misleading field names, and both are corrected. Reported
tank energy is now 2.5x smaller and two public field names are removed.

Separately, eight status flags change type from ``bool`` to
``bool | None`` so the device's "unknown" state is no longer reported as
a definite OFF.

Changed
-------
- **Energy unit scale corrected.** ``totalEnergyCapacity`` and ``availableEnergyCapacity`` were
  scaled by 10 on the assumption the device reported 10 Wh units. It does
  not. Because ``totalEnergyCapacity`` is a whole-tank quantity, its slope
  against the setpoint measures the quantum with no stratification
  assumption: on a 65-gallon NWP500 that is 70.25 raw counts per Kelvin.
  The field is bimodal (at a fixed setpoint it takes one of
  two values exactly 2 degC apart), but both branches give the same slope
  to within 0.2%, so the quantum is unaffected. Converting to Watt-hours needs a
  water mass, and a "65 gallon" tank does not hold 65 gallons, so taking
  the quantum to be round, as every other conversion in this protocol is,
  4 Wh/count is the only candidate implying a water volume below the
  nameplate (241.7 L). Two further checks agree: 183 individual heating
  recoveries give 4.11 Wh/count by a noisier route, and integrating
  ``currentInstPower`` over them implies a heat-pump COP of 2.89 at the new
  scale against 7.02 at the old, the latter being physically impossible.
  **Reported tank energy is now 2.5x smaller.**
  Historical series logged from earlier versions need rescaling by 0.4 to
  be comparable.

- **Energy fields renamed.**
  ``availableEnergyCapacity`` is not available energy: it is the energy
  still *needed* to reach the setpoint. It falls as the tank heats and
  reaches zero when the tank is fully charged, so code treating it as
  stored energy had the signal backwards (regression against mean tank
  temperature: negative slope, R-squared 0.93, zero crossing at the
  setpoint). Likewise ``totalEnergyCapacity`` is not a fixed tank size but
  the cost of a full recovery to the *current setpoint*, measured from the
  device's own minimum setpoint of 104.9 degF; it moves by about 140 Wh
  per 0.5 degC of setpoint change.

  .. code-block:: python

     # OLD (removed)
     status.total_energy_capacity        # 15800.0
     status.available_energy_capacity    # 11660.0

     # NEW
     status.full_recovery_energy         # 6320.0
     status.energy_to_setpoint           # 4664.0

  The protocol field names on the wire are unchanged. CLI rows are
  relabelled from "Total Capacity"/"Available Capacity" to
  "Full Recovery"/"Energy to Setpoint".

- **Status flags now preserve the device's unknown state.** The protocol
  encodes these flags as ``0 = unknown, 1 = OFF, 2 = ON``, and the library
  was collapsing 0 to ``False``, inventing an OFF the device never claimed.
  Confirmed against Navien's own NaviLink app (2.03.00, versionCode 141),
  which decodes exactly this set of fields through an enum declared
  ``UNKNOWN(0), OFF(1), ON(2)``; two sibling enums render their zero as
  ``"-"`` and ``"Not Applied"`` rather than as an off state.

  Affected: ``operation_busy``, ``comp_use``, ``anti_legionella_use``,
  ``anti_legionella_operation_busy``, ``heat_upper_use``, ``heat_lower_use``,
  ``air_filter_alarm_use``, ``recirc_reservation_use``.

  ``None`` is falsy, so ``if status.comp_use:`` is unaffected. Code that
  distinguishes ``is False`` from "not reported", or does arithmetic or
  formatting on these fields, needs a ``None`` check. For Home Assistant
  this is the wanted shape: ``None`` renders as "Unknown" instead of writing
  a fabricated OFF into the recorder database.

- ``OnOffFlag`` gains the vendor's ``UNKNOWN = 0`` member. It previously
  started at ``OFF = 1``, leaving the device's reserved value unrepresented.

- The CLI renders these flags as ``Unknown`` rather than ``No``. Both
  affected rows are updated: "Busy" under OPERATION STATUS and
  "Operation Busy" under ANTI-LEGIONELLA.

Added
-----
- **``DeviceStatus.usable_energy``**: drawable energy in Watt-hours,
  computed as ``full_recovery_energy - energy_to_setpoint``. Both raw
  fields are measured from the setpoint, so neither is a state of charge;
  subtracting them cancels the setpoint and leaves the tank's heat above
  the device's minimum operating temperature (104.9 degF), which is about
  the lowest temperature usable for a shower. It holds despite
  ``full_recovery_energy`` being bimodal, since both fields shift
  together: the implied tank temperature tracks the thermistor mean to a
  standard deviation of 0.57 degF over 12275 samples. Rendered by the CLI
  as "Usable Energy".

- ``converters.device_tristate_to_python`` and
  ``models.status.DeviceTriState`` for flags the device may decline to
  report. ``converters.device_bool_to_python`` is unchanged and remains
  correct for capability flags.
- New ``docs/explanation/unknown-values.rst`` recording which field families
  use 0 as a sentinel and which do not, with the app evidence for each.

Removed
-------
- **Misnamed energy fields**: removed ``DeviceStatus.total_energy_capacity``
  and ``DeviceStatus.available_energy_capacity`` outright rather than
  aliasing them, so a missed rename fails with ``AttributeError`` instead
  of silently returning a number 2.5x too large. Use
  ``full_recovery_energy`` and ``energy_to_setpoint``.

- **Incorrect converter**: removed ``converters.mul_10``, which existed
  only to apply the wrong 10 Wh scale. Use
  ``converters.energy_count_to_wh`` and ``converters.WH_PER_ENERGY_COUNT``.

Fixed
-----
- **Documentation contradicted itself and the code on energy capacity.**
  Three incompatible descriptions were published: Watt-hours with no
  conversion (protocol reference), Watt-hours with a x10 scale (the code),
  and a 0-100 percentage (``how-to/track-energy.rst``,
  ``reference/python_api/models.rst``, ``project/history.rst``). The
  percentage claim was never true of any library version. All are now
  consistent.
- ``how-to/track-energy.rst`` documented four fields that do not exist on
  ``DeviceStatus`` (``dhw_tank_upper_temp``, ``dhw_tank_lower_temp``,
  ``comp_temp``, ``dhw_heatex_out_temp``); replaced with the real names.
- ``dhwTemperature`` is documented as an outlet temperature but is
  measured inside the tank: it tracks ``tankUpperTemperature`` to within
  one 0.5 degC step, and the device has no sensor downstream of itself.
  Navien's own app agrees, labelling it "DHW Temp." beside the tank
  thermistors and showing ``dischargeTemperature`` separately.
- ``docs/explanation/tank-energy.rst`` tabulated ``totalEnergyCapacity``
  and ``availableEnergyCapacity`` at ten times their raw wire values,
  under column headings naming the raw protocol fields. The series had
  been logged through the pre-fix library, which multiplied by 10. The
  prose beside the tables ("70.25 raw counts per Kelvin", "35 counts")
  was already in true raw counts, so the page contradicted itself by
  exactly the factor it exists to correct. Tables are now in raw counts;
  1580 counts at a 145.4 degF setpoint matches the test fixtures and the
  6320 Wh the CLI reports. No numeric conclusion changes.
- ``docs/explanation/tank-energy.rst`` referred to a field
  ``hpUpperOnTemperatureSetting``; the protocol name is
  ``hpUpperOnTempSetting``.
- The setpoint-per-0.5-degC figure is 140 Wh, not 143 Wh, which is what
  the documented slope of 70.25 counts/K gives at 4 Wh/count. Corrected
  in the changelog, the model field description and the protocol
  reference.
- New ``docs/explanation/tank-energy.rst`` records what the two fields
  measure and the calibration evidence behind the scale change,
  including that Navien's own NaviLink app (2.03.00, versionCode 141)
  reads neither field, so no vendor-side corroboration exists.

- Documented that **temperature fields carry no sentinel at all**. The app
  has no out-of-band constant (no ``0xFFFF``/``-999``/``-1``), no zero-guard
  in any display path, and formats whatever arrives, so a temperature of
  zero means zero. This closes a recurring source of bugs where zero-as-none
  was applied to temperature converters and reported working sensors as
  missing during cold-weather operation.
- Documented that capability flags are a distinct case: the app hides a
  feature's entire UI when its DID ``Use`` flag reads 0, so 0 there means
  "not fitted" and the existing ``bool`` mapping is correct.

Version 9.2.1 (2026-07-30)
==========================

Added
-----
- **Confirmed reservation/TOU write helpers and canonical schedule
  comparison** (`#111 <https://github.com/eman/nwp500-python/issues/111>`_):
  ``update_reservations`` and ``configure_tou_schedule`` were
  fire-and-forget, returning only an MQTT publish packet id with no way to
  confirm the device applied the write. New
  ``nwp500.reservations.update_reservations_confirmed()`` and
  ``nwp500.tou_schedule.configure_tou_schedule_confirmed()`` (also exported
  from the top-level ``nwp500`` package) send the write and await the
  device's ``rsv/rd``/``tou/rd`` echo, returning the parsed schedule the
  device now holds (or ``None`` on timeout). Because the protocol has no
  request/response correlation id on these topics, a response is only
  accepted once it matches the content that was just written, so a
  stale/unrelated response from a concurrent read or a previous write
  can't be mistaken for confirmation. Also added
  ``ReservationEntry.canonical_key()``/``ReservationSchedule.canonical()``
  and the ``TOUPeriod``/``TOUReservationSchedule`` equivalents: a stable,
  order-independent, hashable representation of the raw protocol fields so
  a desired program can be compared against a device read-back with
  ``desired.canonical() == confirmed.canonical()`` instead of hand-diffing.

Fixed
-----
- **Freeze protection temperature now validated against device limits**
  (`#112 <https://github.com/eman/nwp500-python/issues/112>`_):
  ``set_freeze_protection_temperature`` documented a 35-45°F valid range
  but sent the value straight through with no validation. It now fetches
  device features and validates against
  ``freeze_protection_temp_min``/``freeze_protection_temp_max`` (raising
  ``RangeValidationError`` if out of range), matching the pattern already
  used by ``set_dhw_temperature``. The command is also now gated behind a
  new ``freeze_protection_use`` capability (added to
  ``MqttDeviceCapabilityChecker._CAPABILITY_MAP`` and enforced with
  ``@requires_capability``), so it's no longer dispatched to devices that
  don't support freeze protection at all.
- **Demand response commands gated on the dr_setting_use capability**
  (`#114 <https://github.com/eman/nwp500-python/issues/114>`_):
  ``enable_demand_response``/``disable_demand_response`` were dispatched
  unconditionally even though the ``dr_setting_use`` capability flag
  exists on ``DeviceFeature``. Every other controllable feature follows
  flag + ``_CAPABILITY_MAP`` entry + ``@requires_capability`` decorator;
  DR was the one gap. Added the missing map entry and decorators so DR
  now follows the same pattern.

Documentation
-------------
- **decode_reservation_hex docstring corrected** (`#113
  <https://github.com/eman/nwp500-python/issues/113>`_): the ``param``
  byte was documented as "temperature offset by 20°F", contradicting the
  half-degrees-Celsius encoding used consistently everywhere else
  (``models/schedule.py``, ``models/_converters.py``). Corrected to
  "target temperature, half-degrees Celsius; °C = param/2", and fixed the
  accompanying doctest-style example, which showed a ``minute`` key where
  the function returns ``min``.

Version 9.2.0 (2026-07-06)
==========================

Changed
-------
- **CLI formatting stacks merged; Rich is the sole human renderer**
  (`#100 <https://github.com/eman/nwp500-python/issues/100>`_): a new
  ``src/nwp500/cli/presentation.py`` owns all data-shaping for CLI output
  (field selection, labels, units, ordering, value formatting and energy
  aggregation) as presentation-neutral structures. Because the CLI
  hard-requires ``rich`` (there is no plain-text fallback), the redundant
  plain-text human renderer and the Rich-vs-plain fallback machinery were
  removed: ``rich_output.py`` no longer contains ``_should_use_rich``,
  ``_rich_available``, the ``NWP500_NO_RICH`` toggle, or any
  ``_print_*_plain`` methods, and now renders the neutral structures
  (including the energy ``TOTAL SUMMARY``) exclusively with Rich, consuming
  the presentation dataclasses directly instead of dict adapters.
  ``output_formatters.py`` keeps only JSON/CSV rendering plus thin
  human-output dispatch. Net CLI code drops from ~2088 to ~1838 lines with a
  single data-shaping layer and a single human renderer. Non-energy output
  is byte-for-byte unchanged (verified by golden capture and the existing
  CLI tests); energy output now renders a summary table plus a breakdown
  table entirely in Rich rather than printing plain text and a Rich table.
- **mqtt/client.py slimmed toward a thin façade** (`#99
  <https://github.com/eman/nwp500-python/issues/99>`_): the ~40 device
  control command proxies and the typed ``subscribe_*``/``unsubscribe_*``
  device-subscription proxies were moved out of ``NavienMqttClient`` into
  two focused mixins, ``DeviceControlCommandsMixin``
  (``mqtt/_control_commands.py``) and ``DeviceSubscriptionsMixin``
  (``mqtt/_device_subscriptions.py``). ``NavienMqttClient`` now inherits
  both, so its public API is unchanged, while ``mqtt/client.py`` shrinks
  from ~1572 to ~1196 lines and reads as connection
  orchestration plus a public façade. No behavior change.
- **Event system relationship clarified and de-duplicated** (`#102
  <https://github.com/eman/nwp500-python/issues/102>`_): ``events.py`` and
  ``mqtt_events.py`` are not two competing event mechanisms.
  ``EventEmitter`` (``events.py``) is the sole delivery mechanism, while
  ``mqtt_events.py`` provides the event-name registry
  (``MqttClientEvents``) and the typed dataclass payloads it carries.
  Internal ``emit`` call sites in ``mqtt/state_tracker.py``,
  ``mqtt/client.py`` and ``mqtt/subscriptions.py`` now reference the
  ``MqttClientEvents`` constants instead of duplicating the raw event-name
  strings, so each event name is defined in exactly one place. Module
  docstrings and the event-system reference docs were updated to document
  the relationship, and typed-payload delivery is now covered by tests.
- **awscrt types wrapped out of public MQTT signatures** (`#101
  <https://github.com/eman/nwp500-python/issues/101>`_): the library no
  longer exposes ``awscrt`` SDK types on its own public/semi-public API
  surface. A library-owned ``nwp500.mqtt.QoS`` ``IntEnum`` (also exported
  as ``nwp500.QoS``) now replaces ``awscrt.mqtt.QoS`` on the ``publish``
  and ``subscribe`` methods of ``NavienMqttClient``, ``MqttConnection``
  and ``MqttSubscriptionManager``, on ``MqttCommandQueue.enqueue`` and on
  the ``QueuedCommand`` dataclass. ``awscrt.mqtt.Connection`` handles are
  typed behind the ``MqttConnectionHandle`` alias, and translation to/from
  ``awscrt`` happens only at the connection-layer boundary
  (``nwp500/mqtt/types.py``). ``NavienMqttClient.publish`` now wraps
  otherwise-uncaught ``AwsCrtError`` in ``MqttPublishError`` so ``awscrt``
  exceptions no longer leak out of the public boundary.

  .. code-block:: python

     # OLD
     from awscrt import mqtt
     await client.publish(topic, payload, qos=mqtt.QoS.AT_LEAST_ONCE)

     # NEW
     from nwp500 import QoS
     await client.publish(topic, payload, qos=QoS.AT_LEAST_ONCE)

Fixed
-----
- **MQTT ack futures now consumed on abandonment** (`#97
  <https://github.com/eman/nwp500-python/issues/97>`_): ``_await_ack()``
  in ``mqtt/connection.py`` and the inline subscribe/unsubscribe
  acknowledgement waits in ``mqtt/subscriptions.py`` shield the AWS CRT
  future so a timeout or cancellation doesn't propagate into the SDK
  future. Previously, if the shielded future later completed with an
  exception (e.g. ``AwsCrtError`` from clean-session cancellation during
  reconnect) after the awaiting task had already given up, nobody
  retrieved that exception, and asyncio logged a "Future exception was
  never retrieved" warning at garbage-collection time. A done callback
  is now attached whenever a wait is abandoned so the eventual
  result/exception is always retrieved and logged at debug level
  instead of leaking as an unhandled asyncio warning.

Documentation
-------------
- **Unit-system preference is a deliberate process-wide global** (`#103
  <https://github.com/eman/nwp500-python/issues/103>`_): clarified and
  locked in that the preference in ``nwp500.unit_system`` is an intentional
  process-wide module-level global rather than a
  ``contextvars.ContextVar``. A context-local value silently reverted to
  auto-detect for real-time data because MQTT message handling runs in tasks
  scheduled from AWS CRT callback threads whose context never inherits from
  the application task. Added prominent docstring notes to the affected
  models (``DeviceStatus``, ``DeviceFeature``, ``ReservationEntry``,
  ``WeeklyReservationEntry``, and ``TOUPeriod``) explaining that unit-aware
  computed fields read the preference at access time and share it across all
  async tasks and threads. This is a non-breaking documentation and test
  change; no API changes.

Added
-----
- **Tests for process-wide unit-system semantics** (`#103
  <https://github.com/eman/nwp500-python/issues/103>`_): new
  ``tests/test_unit_system_process_wide.py`` verifies that setting the global
  preference affects already-constructed model instances at access time and
  that the preference is visible across async tasks and threads.

Version 9.0.0 (2026-07-05)
==========================

**BREAKING CHANGES**: Public API surface trimmed and dead code removed.
These changes require a major version bump.

Modernization (Python 3.14)
---------------------------
- **Removed** ``from __future__ import annotations`` **project-wide**
  (57 files): redundant on a Python >=3.14-only package where lazy
  annotation evaluation (PEP 649) is the default.
- **Adopted additional ruff rule sets**: ``RUF`` (Ruff-specific),
  ``DTZ`` (naive datetime), ``PTH`` (pathlib), ``ASYNC``, and ``PERF``,
  with documented ignores for intentional patterns (grouped ``__all__``
  lists, unicode degree signs, public ``timeout`` parameters). Fixes
  applied for all resulting findings, including a timezone-naive
  timestamp in CSV exports (now timezone-aware local time),
  ``Path.open()`` usage, ``itertools.pairwise()`` in the CLI range
  collapser, a ``ClassVar`` annotation on the capability map, and
  dangling ``asyncio.create_task`` references in tests.
- **PeriodicRequestType is now a StrEnum** (was a plain ``Enum`` with
  string values), matching the enum style used elsewhere.
- **Event payload dataclasses use** ``slots=True``: the frozen event
  dataclasses in ``mqtt_events.py`` and ``events.EventListener`` are
  created per state change; slots reduce their memory footprint.
- **match statement** for the periodic request-type dispatch.

Testing
-------
- New unit tests for previously untested modules:
  ``topic_builder.py`` (full topic schema), ``field_factory.py``
  (metadata defaults, overrides, merge semantics), and
  ``models/_converters.py`` (unit-preference conversions and
  round-trips).

Removed
-------
- **Deprecated ``.control`` property**: removed
  ``NavienMqttClient.control`` (deprecated shim slated for v9.0.0; the
  project policy is to remove rather than deprecate). Use the delegated
  methods on the client directly:

  .. code-block:: python

     # OLD (removed)
     await client.control.set_power(device, True)

     # NEW
     await client.set_power(device, True)

- **Unused exception classes**: removed ``TokenExpiredError``,
  ``MqttSubscriptionError``, ``DeviceNotFoundError``,
  ``DeviceOfflineError``, and ``DeviceOperationError``. None of them was
  ever raised by the library, so no working error handling can break;
  catch the parent classes (``AuthenticationError``, ``MqttError``,
  ``DeviceError``) instead.
- **Internal plumbing removed from the top-level namespace**: the
  package no longer re-exports ``requires_capability``,
  ``MqttDeviceInfoCache``, ``MqttDeviceCapabilityChecker``,
  ``log_performance``, or the bit-encoding helpers
  (``encode_week_bitfield``, ``decode_week_bitfield``,
  ``encode_season_bitfield``, ``decode_season_bitfield``,
  ``encode_price``, ``decode_price``, ``build_reservation_entry``,
  ``build_tou_period``). Import them from their owning modules:

  .. code-block:: python

     # OLD (removed)
     from nwp500 import build_reservation_entry, encode_price

     # NEW
     from nwp500.encoding import build_reservation_entry, encode_price

- **Dead code**: removed the never-imported ``nwp500.cli.commands``
  module (its metadata had drifted from the real click commands), the
  unused ``converters.str_enum_validator``, the unused module-level
  ``temperature.half_celsius_to_fahrenheit`` /
  ``deci_celsius_to_fahrenheit`` wrappers, the no-op
  ``NavienMqttClient._on_message_received`` placeholder, and unused
  width calculations in the CLI formatters.

Changed
-------
- **Temperature classes deduplicated**: ``HalfCelsius``, ``DeciCelsius``,
  ``RawCelsius``, and ``DeciCelsiusDelta`` were four near-identical
  copies differing only in a scale constant. All conversions are now
  implemented once on the ``Temperature`` base class with a per-class
  ``_scale``; only special rounding (``RawCelsius``) and delta semantics
  (``DeciCelsiusDelta``) are overridden. Behavior is unchanged
  (~200 lines removed).
- **field_factory deduplicated**: the four field factories shared a
  copy-pasted metadata-merge block, now extracted into a single private
  helper. Behavior is unchanged.
- **Device boolean encoding centralized**: ``mqtt/control.py`` now uses
  ``converters.device_bool_from_python()`` instead of inline
  ``2 if enabled else 1`` literals.
- **Version resolution decoupled**: ``auth.py`` resolves the package
  version from distribution metadata instead of ``from . import
  __version__``, removing an order-dependent near-circular import.

Bug Fixes
---------
- **Fix malformed weekly reservation and recirculation schedule
  payloads**: ``update_weekly_reservation()`` and
  ``configure_recirculation_schedule()`` dumped the schedule models
  as-is, double-nesting the request (``request.reservation.reservation``
  / ``request.schedule.schedule``) and leaking pydantic computed display
  fields (including a unit-converted ``temperature`` alongside the raw
  half-Celsius ``param``) into device commands. Both now send the flat,
  raw protocol shape used by ``update_reservations()``. A new
  ``NavienBaseModel.to_protocol_dict()`` dumps only declared protocol
  fields.
- **Preserve command order when a queued flush fails**: a command that
  failed mid-flush was re-queued at the tail, behind commands queued
  after it, inverting order-sensitive sequences (e.g. ``set_temp``
  replayed before ``power_on``). The queue is now a deque and failed
  commands are re-inserted at the front.
- **Expire stale queued commands**: queued commands stored a timestamp
  that was never checked, so a multi-hour outage replayed hours-old
  control commands (e.g. ``set_power``) to the appliance on reconnect.
  Commands older than ``MqttConnectionConfig.max_queued_command_age``
  (default 300 s, ``None`` to disable) are now discarded at send time.
- **Fix Fahrenheit conversion for sub-zero temperatures** (ASYMMETRIC
  formula): the rounding used Python's floored ``%``, which is always
  non-negative, while the firmware/app uses a truncated remainder. Raw
  ``-11`` (-5.5 °C) decoded to 22 °F instead of the app's 23 °F. Now
  uses ``math.fmod`` semantics.
- **Fix freeze protection default limits**: the defaults (43/65) were
  Fahrenheit display values stored in raw half-Celsius fields, decoding
  to 70.7 °F / 90.5 °F when the device omitted them. Corrected to raw
  12/20 (43 °F / 50 °F), matching the documented fixed limits.
- **Emit error_detected when the error code changes**: a transition
  between two non-zero error codes (e.g. E799 → E407) emitted no event,
  so consumers kept displaying the stale error.
- **Fix TOU price encoding**: ``encode_price()`` used banker's rounding,
  under-encoding exact half values at even boundaries (0.125 at
  ``decimal_point=2`` encoded to 12 instead of 13). It now uses
  ``Decimal`` half-up rounding. ``build_tou_period()`` also treated
  ``bool`` prices as pre-encoded integers (``True`` sent as price 1).
- **Fix protocol documentation errors**: ``decode_reservation_hex()``
  documented the enable flag inverted (1=enabled instead of 2=enabled);
  the ``build_reservation_entry()`` example showed ``week: 158`` for
  Mon/Wed/Fri instead of the correct 84; temperature doctest examples
  showed ``int`` raw values where ``float`` is returned.
- **Run MQTT message dispatch on the event loop**: JSON parsing, pydantic
  model validation, and user callbacks all executed directly on the AWS
  CRT network thread. A slow or blocking callback (e.g. the CLI monitor's
  CSV writes) stalled all MQTT message processing, user callbacks ran on
  an undocumented SDK thread where asyncio operations are unsafe, and the
  handler registry could be mutated on the event loop while the CRT
  thread iterated it (``RuntimeError: dictionary changed size during
  iteration``, dropping the message, most likely during the
  reconnect/resubscribe window). The awscrt callback now only marshals
  the raw payload onto the event loop; parsing and dispatch run there,
  iterating snapshots of the handler registries.
- **Stop one raising handler from aborting message delivery**: handler
  dispatch caught only ``(TypeError, AttributeError, KeyError)``; a user
  callback raising anything else (e.g. ``ValueError``) escaped into the
  awscrt callback machinery and skipped the remaining handlers for that
  message. Individual handler failures are now logged and isolated.
- **Make the unit system preference process-wide**:
  ``set_unit_system()`` stored the preference in a ``ContextVar`` set in
  the caller's task. Tasks scheduled from AWS CRT callback threads never
  inherit that context, so the preference silently reverted to
  auto-detect for all MQTT-delivered data: ``nwp-cli --unit-system
  metric monitor`` logged temperatures in the device's native unit while
  labeling them °C. The preference is now a process-wide setting visible
  from every task and thread.
- **Fix once-listeners firing more than once**: ``EventEmitter.emit()``
  removed one-time listeners only after invoking them, so a callback
  that raised stayed registered forever, and two overlapping emits could
  both fire the same once-listener. Once-listeners are now removed
  before invocation.
- **Fix wait_for() leaking its listener on cancellation**:
  ``EventEmitter.wait_for()`` removed its listener only on timeout; a
  cancelled waiter left the listener registered until the event next
  fired, setting a result on a dead future. Cleanup now happens in a
  ``finally`` block.
- **Fix wait_for() docstring examples**: examples showed
  ``args, _ = await emitter.wait_for(...)``, but ``wait_for`` returns
  just the args tuple, so following the documented pattern raised
  ``ValueError`` or silently mis-assigned.
- **Serialize concurrent token refresh**: ``ensure_valid_token()`` and
  ``refresh_token()`` had no lock, so concurrent callers (API 401 retry,
  MQTT reconnect, periodic requests) at token expiry fired parallel
  refresh requests; with token rotation the losers were left holding
  invalidated tokens. Refreshes are now serialized behind an
  ``asyncio.Lock`` with a post-acquire re-check: callers that lose the
  race receive the already-refreshed tokens, callers passing a stale
  (pre-rotation) refresh token get the fresh tokens instead of a
  guaranteed failure, and an explicit refresh with the current token
  still forces a refresh (deep-reconnect behavior preserved).
- **Preserve refresh_token/id_token across refreshes**: the refresh
  response merge preserved AWS credential fields but not
  ``refresh_token``/``id_token``. A refresh response omitting them wiped
  the stored refresh token, so the next refresh posted an empty string
  and failed unconditionally.
- **Fix aiohttp session leak when authentication fails in**
  ``__aenter__``: Python never calls ``__aexit__`` when ``__aenter__``
  raises, so bad credentials or a network error leaked the owned
  ``ClientSession`` (one per retry attempt). The session is now closed
  before the exception propagates.
- **Make** ``NavienAuthClient.__aenter__`` **idempotent**:
  ``create_navien_clients()`` pre-enters the context and its docstring
  instructs users to enter again with ``async with auth:``; the second
  entry created a fresh session and orphaned the first, which the API
  client was still pinned to. Re-entering now reuses the existing
  session.
- **Fall back to full sign-in when stored-token refresh fails**:
  restoring expired stored tokens raised ``TokenRefreshError`` even
  though credentials for a full ``sign_in()`` were available.
- **Stop pinning the auth session in the API client**:
  ``NavienAPIClient`` captured ``auth_client.session`` at construction
  and kept using it after the auth client recreated its session
  (``RuntimeError: Session is closed``). The session is now resolved per
  request; an explicitly provided session still takes precedence.
- **Add HTTP timeouts to unguarded sessions**: the standalone
  ``refresh_access_token()`` helper and ``OpenEIClient`` created
  ``ClientSession``s without a ``ClientTimeout``; requests could hang
  indefinitely. Both now use a 30-second total timeout.
- **Fix reconnection loop dying on authentication errors**: the backoff
  loop caught only ``AwsCrtError`` and ``RuntimeError``, so
  ``TokenRefreshError``, ``AuthenticationError``, and
  ``MqttCredentialsError`` raised during quick/deep reconnection escaped
  and silently killed the reconnect task. A routine outage coinciding
  with token expiry left the client permanently offline despite unlimited
  retries. All library errors (``Nwp500Error``) and operation timeouts
  are now treated as failed attempts and retried; only
  ``InvalidCredentialsError`` is fatal and stops the loop with a
  ``reconnection_failed`` event.
- **Fix disconnect() being a no-op while the connection is interrupted**:
  calling ``disconnect()`` during an interruption returned early without
  disabling automatic reconnection or stopping periodic tasks, so the
  backoff loop would resurrect the connection after the application shut
  the client down. ``disconnect()`` now always disables reconnection and
  stops periodic tasks, and tears down the SDK connection even when not
  connected.
- **Fix queued commands being lost after active/deep reconnection**: the
  command queue was only flushed from the SDK's ``on_connection_resumed``
  callback, which never fires for the new connection built by
  active/deep reconnection. Commands queued while offline were silently
  dropped. Both reconnect paths now flush the queue after subscriptions
  are restored.
- **Fix periodic request tasks dying on MQTT errors**: the periodic loop
  caught only ``AwsCrtError`` and ``RuntimeError``;
  ``MqttNotConnectedError``/``MqttPublishError`` raised by a publish
  racing a disconnection permanently killed the polling task while it
  still appeared active. The loop now survives all library errors.
- **Fix silent failures in thread-scheduled coroutines**: futures
  returned by ``run_coroutine_threadsafe`` were discarded, so exceptions
  from scheduled work (e.g. a failed resubscribe after a clean-session
  resume, leaving the client connected but deaf) vanished. A done
  callback now logs them.
- **Fix CancelledError being swallowed in reconnection and periodic
  loops**: both loops caught ``asyncio.CancelledError`` and ``break``-ed,
  so cancelled tasks ended "successfully" (and the reconnection loop
  could emit ``reconnection_failed`` during a manual disconnect).
  Cancellation now propagates correctly.
- **Fix AttributeError in configure_reservation_water_program**: The
  ``NavienMqttClient`` proxy referenced ``self._control``, which is never
  assigned (the attribute is ``_device_controller``), so every call raised
  ``AttributeError``. Now delegates correctly; a regression test guards all
  proxies against references to the undefined attribute.
- **Fix broken CLI mode choices**: ``nwp-cli mode vacation`` always failed
  because vacation mode (5) requires a day count that was never supplied, and
  ``mode standby`` sent the invalid writable mode value ``0``. Both choices
  were removed from the ``mode`` command; use the dedicated ``vacation DAYS``
  and ``power off`` commands instead.
- **Fix CLI exit codes**: click ignores command return values in standalone
  mode, so the CLI always exited ``0`` even when a command failed. Failures
  now propagate through ``ctx.exit()`` and produce a non-zero exit code for
  scripts and automation.
- **Fix cached tokens being reused for a different account**: passing
  ``--email`` for account B while tokens for account A were cached silently
  ran commands against account A's session. Cached tokens are now discarded
  when the provided email does not match the cached one.
- **Surface OpenEI application errors**: OpenEI reports errors such as an
  invalid API key in the body of an HTTP 200 response; these were masked as
  "no rate plans found". ``fetch_rates()`` now raises ``APIError`` with the
  API's error message.
- **Fix broken example import**: ``examples/advanced/mqtt_diagnostics.py``
  imported ``MqttConnectionConfig`` from the nonexistent ``nwp500.mqtt_utils``
  module and used the deprecated ``datetime.utcnow()``.

Improvements
------------
- **MQTT operation acknowledgement timeouts**: connect, publish,
  subscribe, unsubscribe, and disconnect acknowledgements are now awaited
  with a timeout (``MqttConnectionConfig.operation_timeout``, default 30
  seconds). Previously a half-open TCP connection could hang callers
  until the 20-minute keep-alive expired.
- **Reconnection backoff jitter**: reconnect delays are now randomized
  (±50%, capped at ``max_reconnect_delay``) so fleets of clients
  disconnected simultaneously (e.g. the AWS IoT 24-hour disconnect) no
  longer reconnect in synchronized waves.

Security
--------
- **Restrict token cache file permissions**: ``~/.nwp500_tokens.json``
  (refresh token and AWS credentials) was written world-readable. It is now
  created with mode ``0600``, and existing files are tightened on save.

Version 8.1.3 (2026-06-15)
==========================

Bug Fixes
---------
- **Fix MQTT reconnection storm caused by non-thread-safe Task.cancel()**: The
  ``on_connection_resumed`` callback is invoked from an AWS IoT SDK background
  thread.  It was calling ``asyncio.Task.cancel()`` directly on that thread, which
  is not thread-safe.  When the event loop was busy at the moment of cancellation
  (e.g. the sleeping task's timer callback had already been enqueued), the
  cancellation was silently dropped.  The stale ``_reconnect_with_backoff`` task
  would then complete its sleep, call ``_reconnect_func``, and tear down an
  otherwise healthy connection, restarting the entire disconnect → reconnect →
  ``AWS_ERROR_MQTT_UNEXPECTED_HANGUP`` cycle.  Fixed by replacing the direct
  ``task.cancel()`` call with a ``_cancel_pending_reconnect()`` coroutine scheduled
  via ``_schedule_coroutine``, so the cancellation runs on the event loop where
  asyncio operations are safe.  The method also uses an identity check before
  clearing ``_reconnect_task`` to avoid wiping a newer task created during the
  await, and clears stale references to already-done tasks.

Version 8.1.0 (2026-05-16)
==========================

Bug Fixes
---------
- **Fix MQTT connection flapping after reconnect**: When ``_active_reconnect()``
  created a new ``MqttConnection``, the old connection was never closed. The old
  SDK connection's built-in auto-reconnect would eventually succeed, creating two
  active connections sharing the same client ID. Because AWS IoT allows only one
  connection per client ID, the broker would kick one off, triggering
  ``on_connection_interrupted`` and starting yet another reconnection: an
  infinite connect/disconnect loop. Fixed by adding ``MqttConnection.close()``
  (unconditional teardown regardless of ``_connected`` state) and calling it
  before creating the replacement connection in both ``_active_reconnect()`` and
  ``_deep_reconnect()``.

- **Thread-safety race in ``ensure_device_info_cached``**: The ``future.done()``
  check and ``future.set_result()`` were performed in the AWS SDK callback thread
  without synchronisation, creating a race against the asyncio event loop thread.
  Moved both operations inside a ``call_soon_threadsafe`` callback so they execute
  atomically on the event loop thread.

- **ZeroDivisionError when ``deep_reconnect_threshold`` is 0**: Config validation
  now clamps ``deep_reconnect_threshold`` to a minimum of 1, preventing a
  ``ZeroDivisionError`` in the exponential-backoff reconnection logic.

- **Reconnect counter never incremented**: ``total_reconnect_attempts`` in
  diagnostics was not incremented on connection drops, so it always reported 0
  despite active reconnections. Counter is now incremented on each
  ``on_connection_interrupted`` event.

- **``shortest_session_seconds`` not JSON-serialisable**: The diagnostics
  ``to_dict()`` method used ``float('inf')`` as the initial value for
  ``shortest_session_seconds``, which is not valid JSON. Changed to ``None``
  so serialisation succeeds when no session has completed yet.

- **``wait_for()`` future not bound to running loop**: ``wait_for()`` created a
  bare ``asyncio.Future()`` rather than
  ``asyncio.get_running_loop().create_future()``, which could bind the future to
  a different loop in multi-loop test setups.

- **Reservation temperature validation was US-only**: ``build_reservation_entry``
  validated set-point temperatures against hardcoded Fahrenheit bounds (95-150 °F)
  regardless of the active unit system. Validation now uses the current unit system
  context: 35-65 °C in metric mode, 95-150 °F in US mode. Celsius users previously
  received spurious ``ValueError`` rejections for valid temperatures.

- **Malformed reservation data silently dropped**: ``build_reservation_entry`` now
  logs a warning when reservation hex data contains unexpected trailing bytes
  instead of silently dropping partial entries.

- **Unknown ``PeriodicRequestType`` silently ignored**: The periodic-request handler
  now logs an error and breaks when it encounters an unknown request type instead of
  doing nothing.

- **Memory leak in device info cache**: ``get_all_cached()`` only filtered expired
  entries from its return value but left them in the cache dictionary. Expired
  entries are now evicted during ``get_all_cached()`` to prevent unbounded growth.

Version 8.0.0 (2026-05-13)
===========================

Bug Fixes
---------
- **Fix MQTT reconnection after unexpected AWS hangup**: The
  ``on_connection_resumed`` callback was missing the ``connection`` parameter
  required by the AWS IoT SDK callback signature. The SDK calls
  ``on_connection_resumed(connection, return_code, session_present, **kwargs)``,
  but the handler only accepted ``(return_code, session_present)``. The
  mismatched signature caused the callback to fail silently (exception swallowed
  by the AWS CRT C layer), so ``self._connected`` was never restored to ``True``
  after an ``AWS_ERROR_MQTT_UNEXPECTED_HANGUP``. As a result, the
  ``connection_resumed`` event was never emitted, the reconnection loop ran
  indefinitely, and device sensors became permanently unavailable until a manual
  restart. (`#85 <https://github.com/eman/nwp500-python/issues/85>`_)

Features
--------
- **Multi-device support enhancements**: Improved support for accounts with multiple
  Navilink devices by injecting device identity into models and events.

  - Added ``mac_address`` field to ``DeviceStatus`` and ``DeviceFeature`` models.
  - Added ``device_mac`` attribute to all device-specific MQTT events (temperature
    changes, mode changes, power updates, errors, etc.).
  - Updated ``DeviceStateTracker`` and ``MqttSubscriptionManager`` to propagate
    device identity correctly.

**BREAKING CHANGES**: ``.on()`` event handler callbacks now receive a single typed
event dataclass instead of positional arguments. ``MqttDeviceController`` is no longer
accessible as ``.control`` on ``NavienMqttClient``; all control methods are now
available directly on the client.

Breaking Changes
----------------
- **Typed event payloads**: All ``.on()`` event handler callbacks now receive a single
  typed event dataclass instance. The dataclasses are exported from
  ``nwp500.mqtt_events``.

  .. code-block:: python

     # OLD (removed)
     mqtt.on("temperature_changed", lambda old, new: print(old, new))
     mqtt.on("connection_resumed", lambda rc, sp: print(rc, sp))

     # NEW
     mqtt.on("temperature_changed", lambda e: print(e.old_temperature, e.new_temperature))
     mqtt.on("connection_resumed", lambda e: print(e.return_code, e.session_present))

- **``MqttDeviceController`` no longer public**: ``NavienMqttClient`` no longer exposes
  a ``.control`` attribute. All control methods are now available directly on the
  client.

  .. code-block:: python

     # OLD (removed)
     await mqtt.control.set_temperature(device, 50)

     # NEW
     await mqtt.set_temperature(device, 50)

Migration Guide (from 7.x.x)
----------------------------
The following steps are recommended for a smooth migration, particularly for complex
integrations like Home Assistant:

1.  **Update Event Listeners**: Locate all ``mqtt.on()`` or ``mqtt.once()`` calls.
    Update the callback signatures to accept a single argument (the event object) and
    update the body to access fields via the object (e.g., ``event.new_temperature``
    instead of ``new_val``).
2.  **Refactor Control Calls**: Remove ``.control`` from all device command invocations.
    Instead of ``await mqtt.control.set_power(...)``, use ``await mqtt.set_power(...)``.
3.  **Handle Unit Conversions**: If your integration previously performed its own
    conversions or relied on the library's eager conversion:
    ``DeviceStatus`` fields like ``dhw_temperature`` are now properties. They return
    values based on the global unit system context (``us_customary`` by default).

    *   **Home Assistant Tip**: To keep your state tracking immune to unit system
        toggles within the library, use the new ``*_raw`` fields (e.g.,
        ``status.dhw_temperature_raw``) for comparison logic, and use the properties
        only for display or when a converted value is explicitly needed.
4.  **Remove ``from_dict()`` Calls**: The ``from_dict()`` method has been removed
    from all models. Use ``model_validate()`` instead.

    *   **Note**: ``AuthenticationResponse.model_validate()`` now automatically handles
        the ``"data": { ... }`` wrapper found in raw API responses.
5.  **Subpackage Imports**: While top-level imports from ``nwp500.models`` are
    preserved, if you were importing from the internal ``nwp500.models`` module file
    directly, you must update your imports to point to the new structured files
    (e.g., ``nwp500.models.status``).

Added
-----
- **New control methods**: Nine previously unimplemented ``CommandCode`` values now have
  full implementations: ``check_firmware``, ``commit_firmware``, ``reconnect_wifi``,
  ``reset_wifi``, ``set_freeze_protection_temperature``, ``run_smart_diagnostic``,
  ``enable_intelligent_reservation``, ``disable_intelligent_reservation``, and
  ``set_water_program_reservation``.
- **Typed subscription methods**: ``subscribe_reservation``,
  ``subscribe_weekly_reservation``, and ``subscribe_recirculation`` return typed
  responses directly without requiring raw MQTT event handlers.
- **New protocol models**: ``WeeklyReservationSchedule``, ``WeeklyReservationEntry``,
  ``RecirculationSchedule``, ``RecirculationScheduleEntry``, and ``OtaCommitPayload``.
- **``DeviceStateTracker``**: State change detection extracted into a dedicated class
  in ``nwp500.mqtt.state_tracker`` with per-device tracking keyed by MAC address.
- **``MQTT_PROTOCOL_VERSION`` constant**: Protocol version is now a named constant in
  ``nwp500.config`` rather than a hardcoded integer in the command payload builder.
- **``response_ack_topic()``**: New method on ``MqttTopicBuilder`` for control command
  acknowledgement topics.

Changed
-------
- **Unit conversion redesign**: Temperature, flow rate, and volume fields in
  ``DeviceStatus`` and ``DeviceFeature`` now store raw device values as ``*_raw: int``
  fields and expose converted values via lazy computed properties. Conversion happens at
  access time rather than during Pydantic deserialization, preserving the original
  device value in all cases.
- **Models split into subpackage**: ``nwp500.models`` is now a package
  (``nwp500/models/``) with modules for status, schedule, TOU, and MQTT models. Public
  imports from ``nwp500.models`` are unchanged.
- **Topic building centralised**: All MQTT topic construction now goes through
  ``MqttTopicBuilder``. Hardcoded topic strings removed from ``control.py``,
  ``reservations.py``, and ``cli/handlers.py``.
- **``set_vacation_days`` delegates to ``set_dhw_mode``**: The method now calls
  ``set_dhw_mode(device, DhwOperationSetting.VACATION, vacation_days=days)`` directly.
- **Per-device state tracking**: ``_previous_status`` changed from a single
  ``DeviceStatus | None`` to a ``dict[str, DeviceStatus]`` keyed by MAC address,
  preventing spurious state-change events when multiple devices are connected.
- **Unit system stored as instance variable**: ``NavienAPIClient``,
  ``NavienMqttClient``, and ``NavienAuthClient`` no longer call ``set_unit_system()``
  as a constructor side-effect.
- **``NavienBaseModel`` consolidated**: Duplicate definitions in ``auth.py`` and
  ``models.py`` merged into a single definition in ``nwp500._base``.

Version 7.4.10 (2026-04-13)
===========================

Changed
-------
- **Loosened pydantic version requirement**: Changed from ``pydantic>=2.12.5`` to
  ``pydantic>=2.0.0`` to resolve dependency conflicts with Home Assistant, which
  ships with ``pydantic==2.12.2``.

Version 7.4.9 (2026-04-12)
==========================

Added
-----
- **Firmware Payload Capture Tool**: New example script
  ``examples/advanced/firmware_payload_capture.py`` for capturing raw MQTT
  payloads to detect firmware-introduced protocol changes. Subscribes to all
  response and event topics via wildcards, requests the full scheduling
  data set (weekly reservations, TOU, device info), and saves everything to a
  timestamped JSON file suitable for ``jq``/``diff`` comparison across firmware
  versions.

Fixed
-----
- **Timezone-naive datetime in token expiry checks**: ``AuthTokens.is_expired``,
  ``are_aws_credentials_expired``, and ``time_until_expiry`` used
  ``datetime.now()`` (naive, local time). During DST transitions or timezone
  changes this could cause incorrect expiry detection, leading to premature
  re-authentication or use of an expired token. Fixed by using
  ``datetime.now(UTC)`` throughout, switching the ``issued_at`` field default
  to ``datetime.now(UTC)``, and adding a field validator to normalize any
  timezone-naive ``issued_at`` values loaded from old stored token files to UTC
  (previously this would raise a ``TypeError`` at comparison time). The
  validator was further extended to also handle ISO 8601 strings without
  timezone info (e.g. ``"2026-02-17T14:47:01.686943"``), which is the actual
  format written by ``to_dict()`` for tokens stored before this fix.
- **Vacation mode sent wrong MQTT command**: ``set_vacation_days()`` used
  ``CommandCode.GOOUT_DAY`` (33554466), which the device silently accepted
  but did not activate vacation mode; the operating mode remained unchanged.
  HAR capture of the official Navien app confirms the correct command is
  ``DHW_MODE`` (33554437) with ``param=[5, days]``
  (``DhwOperationSetting.VACATION``). The valid range has also been corrected
  from 1-365 to 1-30 to match the device's actual constraint.
- **Duplicate AWS IoT subscribe calls on reconnect**: ``resubscribe_all()``
  called ``connection.subscribe()`` (a network round-trip to AWS IoT) once per
  handler per topic. If a topic had N handlers, N identical subscribe requests
  were sent on every reconnect. Fixed by making one network call per unique
  topic and registering remaining handlers directly into ``_message_handlers``.
- **Anti-Legionella set-period State Preservation**: ``nwp-cli anti-legionella
  set-period`` was calling ``enable_anti_legionella()`` in both the enabled and
  disabled branches, silently re-enabling the feature when it was off. The
  command now informs the user that the period can only be updated while the
  feature is enabled and directs them to ``anti-legionella enable``.
- **Subscription State Lost After Failed Resubscription**: ``resubscribe_all()``
  cleared ``_subscriptions`` and ``_message_handlers`` before the re-subscribe
  loop. Topics that failed to resubscribe were permanently dropped from internal
  state and could not be retried on the next reconnection. Failed topics are now
  restored so they are retried automatically.
- **Unit System Detection Returns None on Timeout**: ``_detect_unit_system()``
  declared return type ``UnitSystemType`` but returned ``None`` on
  ``TimeoutError``, violating the type contract. Now returns
  ``"us_customary"`` consistent with the warning message.
- **Once-Listener Becomes Permanent With Duplicate Callbacks**: ``emit()``
  identified once-listeners via a ``set`` of ``(event, callback)`` tuples. If
  the same callback was registered twice with ``once=True``, the set
  deduplicated the tuple: after the first emit the second listener lost its
  once-status and became permanent. Fixed by checking ``listener.once``
  directly on the ``EventListener`` object.
- **Auth Session Leaked on Client Construction Failure**: In
  ``create_navien_clients()``, if ``NavienAPIClient`` or
  ``NavienMqttClient`` construction raised after a successful
  ``auth_client.__aenter__()``, the auth session and its underlying
  ``aiohttp`` session would leak. Client construction is now wrapped in a
  ``try/except`` that calls ``auth_client.__aexit__()`` on failure.
  Both ``except BaseException`` blocks have been replaced with
  ``except Exception`` (passing real exception info to ``__aexit__``) plus a
  separate ``except asyncio.CancelledError`` block that uses
  ``asyncio.shield()`` so cleanup completes even when the task is
  being cancelled.
- **Hypothesis Tests Broke All Test Collection**: ``test_mqtt_hypothesis.py``
  imported ``hypothesis`` at module level; when it was not installed, pytest
  failed to collect every test in the suite. ``hypothesis`` is now mandated
  as a ``[testing]`` extra dependency, restoring correct collection behaviour.

Changed
-------
- **Dependency updates**: Bumped minimum versions to track current releases:
  ``aiohttp >= 3.13.5``, ``pydantic >= 2.12.5``, ``click >= 8.3.0``,
  ``rich >= 14.3.0``.
- **Dependency: awsiotsdk >= 1.28.2**: Bumped minimum ``awsiotsdk`` version
  from ``>=1.27.0`` to ``>=1.28.2`` to track the current patch release.
  ``awscrt`` 0.31.3 is pulled in transitively.

Version 7.4.8 (2026-02-17)
==========================

Added
-----
- **Reservation CRUD Helpers**: New public functions ``fetch_reservations()``,
  ``add_reservation()``, ``delete_reservation()``, and ``update_reservation()``
  in ``nwp500.reservations`` (and exported from ``nwp500``). These abstract the
  read-modify-write pattern for single-entry schedule management so library
  users no longer need to fetch the full schedule, splice it manually, and send
  it back. The CLI now delegates to these library functions.

Version 7.4.7 (2026-02-17)
==========================

Added
-----
- **OpenEI Client Module**: New ``OpenEIClient`` async client (``nwp500.openei``) for browsing utility rate plans from the OpenEI API by zip code. Supports listing utilities, filtering rate plans, and fetching plan details. API key read from ``OPENEI_API_KEY`` environment variable.
- **Convert TOU API**: ``NavienAPIClient.convert_tou()`` sends raw OpenEI rate data to the Navien backend for server-side conversion into device-ready TOU schedules with season/week bitfields and scaled pricing.
- **Update TOU API**: ``NavienAPIClient.update_tou()`` applies a converted TOU rate plan to a device, matching the mobile app's ``PUT /device/tou`` endpoint.
- **ConvertedTOUPlan Model**: New Pydantic model for parsed ``convert_tou()`` results (utility, name, schedule).
- **CLI ``tou rates``**: Browse utilities and rate plans for a zip code (``nwp500 tou rates 94903``).
- **CLI ``tou plan``**: View converted rate plan details with decoded pricing (``nwp500 tou plan 94903 "EV Rate A"``).
- **CLI ``tou apply``**: Apply a rate plan to the water heater with optional ``--enable`` flag to activate TOU via MQTT.
- **CLI Reservations Table Output**: ``nwp-cli reservations get`` now displays reservations as a formatted table by default with global status indicator (ENABLED/DISABLED). Use ``--json`` flag for JSON output.
- **CLI ``anti-legionella set-period``**: New subcommand to change the Anti-Legionella cycle period (1-30 days) without toggling the feature. Use ``nwp-cli anti-legionella set-period 7`` to update cycle period.

Changed
-------
- **``examples/advanced/tou_openei.py``**: Rewritten to use the new ``OpenEIClient`` and ``convert_tou()``/``update_tou()`` library methods instead of inline OpenEI API calls and client-side conversion.

Fixed
-----
- **Week Bitfield Encoding**: Fixed MGPP week bitfield encoding to match NaviLink APK protocol. Sunday is now correctly bit 7 (128), Monday bit 6 (64), ..., Saturday bit 1 (2); bit 0 is unused. Affects all reservation and TOU schedule operations. Verified against reference captures.
- **Enable/Disable Convention**: Fixed reservation and TOU enable/disable flags to use standard device boolean convention (1=OFF, 2=ON) instead of inverted logic. This aligns with other device binary sensors and matches app behavior. Global reservation status now correctly shows DISABLED when ``reservationUse=1``.
- **Reservation Set Command Timeout**: Fixed ``reservations set`` subscription pattern that had extra wildcards preventing response matching. Command now receives confirmations correctly.
- **Intermittent Fetch Bug**: Tightened MQTT topic filter for reservation fetch from ``/res/`` to ``/res/rsv/`` with content validation to prevent false matches on unrelated response messages.

Version 7.4.6 (2026-02-13)
==========================

Fixed
-----
- **Converter Consistency**: ``div_10()`` and ``mul_10()`` now correctly apply division/multiplication to all input types after ``float()`` conversion, not just ``int``/``float`` types
- **Reservation Decoding**: Fixed ``decode_reservation_hex()`` to validate chunk length before checking for empty entries, preventing potential out-of-bounds access
- **Factory Cleanup**: ``create_navien_clients()`` now properly cleans up auth session if authentication fails during context manager entry
- **MQTT Reconnection**: MQTT client now resubscribes to all topics after successful reconnection
- **Subscription Leak**: Fixed resource leak where ``wait_for_device_feature()`` did not unsubscribe its callback after completion
- **Duplicate Handlers**: Subscription manager now prevents duplicate callback registration for the same topic
- **Command Queue**: ``MqttCommandQueue`` now raises on ``QueueFull`` instead of silently swallowing the error
- **Flow Rate Metadata**: Removed hardcoded ``"GPM"`` unit from ``recirc_dhw_flow_rate`` field; unit is now dynamic based on unit system
- **Temperature Rounding**: ``RawCelsius`` Fahrenheit conversion now uses a catch-all default for standard rounding instead of matching only ``STANDARD`` enum value
- **Unit System Default**: ``is_metric_preferred()`` now returns ``False`` (Fahrenheit) instead of ``None`` when no unit system override or context is set

Security
--------
- **Sensitive Data Logging**: Redacted MQTT topics in subscription manager logging to prevent leaking device IDs (resolves CodeQL alerts)

Added
-----
- **Auth Session Property**: Added ``NavienAuthClient.session`` property to access the active ``aiohttp`` session without using ``getattr``
- **Unsubscribe Feature**: Added ``unsubscribe_device_feature()`` method to MQTT client and subscription manager for targeted callback removal
- **Hypothesis Fuzzing**: Added property-based fuzzing tests for MQTT payload handling
- **Bandit Security Scanning**: Added bandit configuration for security analysis in CI

Version 7.4.5 (2026-02-04)
==========================

Fixed
-----
- **Energy Capacity Unit Scaling**: Corrected unit scaling for energy capacity fields that were off by a factor of 10
- **CLI Output**: Fixed linting issue by replacing str and Enum with StrEnum for InstallType

Version 7.3.4 (2026-01-27)
==========================

Fixed
-----
- **Temperature Delta Conversions**: Fixed incorrect Fahrenheit conversion for differential temperature settings (heat pump and heater element on/off thresholds)

  - Created new ``DeciCelsiusDelta`` class for temperature deltas that apply scale factor (9/5) but NOT the +32 offset
  - Heat pump and heater element differential settings now use ``DeciCelsiusDelta`` instead of ``DeciCelsius``
  - ``hp_upper_on_diff_temp_setting``, ``hp_lower_on_diff_temp_setting``, ``he_upper_on_diff_temp_setting``, ``he_lower_on_diff_temp_setting``, and related off settings now convert correctly to Fahrenheit
  - Example: A device value of 5 (representing 0.5°C delta) now correctly converts to 0.9°F delta instead of 32.9°F

- **CLI Output**: Added display of heat pump and heater element differential temperature settings in device status output

Changed
-------
- **Internal API**: Added ``div_10_celsius_delta_to_preferred`` converter for temperature delta values in device models


Version 7.3.3 (2026-01-27)
==========================

Breaking Changes
----------------
- **Temperature Setpoint Limits**: Replaced hardcoded temperature limits with device-provided values

  - ``set_dhw_temperature()`` now validates against device-specific ``dhw_temperature_min`` and ``dhw_temperature_max`` instead of hardcoded 95-150°F bounds
  - ``build_reservation_entry()`` changed parameter name from ``temperature_f`` to ``temperature`` (unit-agnostic)
  - Added optional ``temperature_min`` and ``temperature_max`` parameters to ``build_reservation_entry()`` for device-specific limit overrides
  - Temperature parameters now accept values in the user's preferred unit (Celsius or Fahrenheit) based on global unit system context
  - Fixes Home Assistant and other integrations that prefer Celsius unit display

  **Migration guide:**

  .. code-block:: python

     # OLD (hardcoded 95-150°F)
     await mqtt.set_dhw_temperature(device, temperature_f=140.0)
     entry = build_reservation_entry(
         enabled=True,
         days=["Monday"],
         hour=6,
         minute=0,
         mode_id=3,
         temperature_f=140.0,
     )

     # NEW (device-provided limits, unit-aware)
     # Temperature value automatically uses user's preferred unit
     await mqtt.set_dhw_temperature(device, 140.0)
     
     # Device features provide min/max in user's preferred unit
     features = await device_info_cache.get(device.device_info.mac_address)
     entry = build_reservation_entry(
         enabled=True,
         days=["Monday"],
         hour=6,
         minute=0,
         mode_id=3,
         temperature=140.0,
         temperature_min=features.dhw_temperature_min,
         temperature_max=features.dhw_temperature_max,
     )

Added
-----
- **Reservation Temperature Conversion**: New ``reservation_param_to_preferred()`` utility function for unit-aware reservation display

  - Converts device reservation parameters (half-degree Celsius) to user's preferred unit
  - Respects global unit system context (metric/us_customary)
  - Enables proper thermostat/reservation scheduling display in Home Assistant and other integrations
  - Example usage:

  .. code-block:: python

     from nwp500 import reservation_param_to_preferred

     # Display reservation temperature in user's preferred unit
     param = 120  # Device raw value in half-Celsius
     temp = reservation_param_to_preferred(param)
     # Returns: 60.0 (Celsius) or 140.0 (Fahrenheit) based on unit context

- **Unit-Aware Temperature Conversion**: New ``preferred_to_half_celsius()`` utility function

  - Converts temperature from user's preferred unit to half-degree Celsius for device commands
  - Respects global unit system context (metric/us_customary)
  - Replaces misleading ``fahrenheit_to_half_celsius()`` in unit-agnostic code paths
  - Used internally by ``set_dhw_temperature()`` and ``build_reservation_entry()``

Changed
-------
- **Unit System Agnostic Display**: All logging and user-facing messages now respect global unit system context

  - Temperature change logs dynamically show °C or °F based on user preference
  - CLI monitoring and temperature setting messages use correct unit suffix
  - Event listener documentation updated with unit-aware examples
  - Reservation schedule examples now use ``reservation_param_to_preferred()`` for proper unit handling

Fixed
-----
- **Temperature Unit Bug in Set Operations**: Fixed incorrect temperature conversion when setting DHW temperature and reservations

  - ``set_dhw_temperature()`` was calling ``fahrenheit_to_half_celsius()`` with unit-agnostic temperature parameter
  - ``build_reservation_entry()`` had the same issue
  - **Impact**: If user preferred Celsius, temperature would be interpreted as Fahrenheit, causing wrong setpoints
  - **Fix**: Use new ``preferred_to_half_celsius()`` that respects unit system context
  - This was a data correctness bug that would cause incorrect device behavior for Celsius users

Version 7.3.2 (2026-01-25)
==========================

Changed
-------
- **Unit System Consistency**: Removed deprecated ``"imperial"`` unit system identifier in favor of ``"us_customary"`` for Home Assistant compatibility

  - Changed all references from ``UnitSystem.IMPERIAL`` to ``UnitSystem.US_CUSTOMARY``
  - Updated ``set_unit_system()`` and related functions to use ``"us_customary"`` exclusively
  - ``"metric"`` remains unchanged for Metric conversions
  - Affects API client, MQTT client, and CLI unit system handling
  - Improves consistency with Home Assistant naming conventions

Fixed
-----
- **Unit System Consolidation**: Consolidated duplicate ``UnitSystemType`` type alias definitions into single canonical definition in ``unit_system.py``

  - Removed redundant type definitions from multiple modules
  - Improved code maintainability and consistency
  - All unit system operations now reference centralized type definition

Version 7.3.1 (2026-01-25)
==========================

Fixed
-----
- **MQTT Client Initialization**: Removed overly strict token validity check from ``NavienMqttClient.__init__()``

  - The strict token validity check prevented creating MQTT clients with restored tokens that may have expired between application restarts
  - However, ``NavienMqttClient.connect()`` already handles token refresh automatically, making the check redundant
  - This change allows integrations to create MQTT clients with expired tokens and let connect() handle validation
  - Simplifies application code by removing duplicate token refresh calls
  - Enables proper handling of restored authentication sessions
  - Fixes MQTT connection failures when using stored tokens across application restarts

Version 7.3.0 (2026-01-19)
==========================

Added
-----
- **Dynamic Unit Conversion**: All temperature, flow, and volume measurements now dynamically convert based on user's region preference (Metric/Imperial)

  - Temperature fields convert between Celsius and Fahrenheit using standard formulas
  - Flow rate fields convert between LPM (Liters Per Minute) and GPM (Gallons Per Minute)
  - Volume fields convert between Liters and Gallons
  - Available devices and regions determine conversion support (validated at runtime)
  - ``get_field_unit()`` method retrieves the correct unit suffix for any field
  - All conversions use Pydantic ``WrapValidator`` for transparent, automatic conversion
  - Documentation in ``docs/guides/unit_conversion.rst``
  - Example usage:

    .. code-block:: python

       # Get converted value with unit
       temp_f = device_status.flow_rate_target  # Returns Fahrenheit if region prefers imperial
       unit = device_status.get_field_unit("flow_rate_target")  # Returns "°F" or "°C"

       # All conversions are transparent - values automatically convert to preferred units
       flow_gpm = device_status.flow_rate_current  # GPM if imperial, LPM if metric
       volume_gal = device_status.tank_volume  # Gallons if imperial, Liters if metric

  - Supported conversion fields:

    - **Temperature**: ``flow_rate_target``, ``flow_rate_current``, ``in_water_temp``, ``out_water_temp``, ``set_temp``, ``in_temp``, ``out_temp``, etc.
    - **Flow Rate**: ``flow_rate_target``, ``flow_rate_current``
    - **Volume**: ``tank_volume`` and related storage fields

  - Integration patterns for Home Assistant, CLI, and custom integrations documented

- **Unit System Override**: Allow applications and CLI users to override the device's temperature preference and explicitly specify Metric or Imperial units

  - Library-level: Add optional ``unit_system`` parameter to ``NavienAuthClient``, ``NavienMqttClient``, and ``NavienAPIClient`` initialization
  - Set once at initialization; applies to all subsequent data conversions
  - Accepts: ``"metric"`` (Celsius/LPM/Liters), ``"imperial"`` (Fahrenheit/GPM/Gallons), or ``None`` (auto-detect from device)
  - Decouples unit preference from device configuration - users can override what the device is set to
  - Uses context variables for thread-safe and async-safe unit system management
  - Example usage:

    .. code-block:: python

       # Library initialization
       from nwp500 import NavienAuthClient, set_unit_system
       auth = NavienAuthClient(email, password, unit_system="metric")

       # Or set after initialization
       set_unit_system("imperial")
       device_status = await mqtt.request_device_status(device)
       # Values now in F, GPM, gallons regardless of device setting

  - CLI-level: Add ``--unit-system`` flag for per-command override
  - Example: ``nwp-cli status --unit-system metric``
  - Defaults to device's setting if not specified
  - New exported functions:
    - ``set_unit_system(unit_system)`` - Set the preferred unit system
    - ``get_unit_system()`` - Get the current unit system preference
    - ``reset_unit_system()`` - Reset to auto-detect mode

Fixed
-----
- **MQTT Unit System Override Bug**: Fixed unit_system CLI flag not applying to device status values

  - **Issue**: Running ``nwp-cli --unit-system metric status`` displayed values in device's native format (imperial) with metric unit strings (e.g., "104.9 °C" instead of "40.5 °C")
  - **Root Cause**: MQTT callbacks from AWS CRT execute on different threads where context variables are not set. Since Python's context variables are task-local, the unit_system preference was not visible to validators
  - **Solution**: Store unit_system in ``NavienMqttClient`` and ``MqttSubscriptionManager``. Before parsing MQTT messages, explicitly set the context variable in message handlers so validators use the correct unit system regardless of thread context
  - **Result**: Values and units now correctly convert when ``--unit-system`` override is specified
  - **Testing**: All 393 tests pass including new unit system context override tests

- **Type Annotation Quotes**: Removed unnecessary quoted type annotations (UP037 violations)

  - With ``from __future__ import annotations``, explicit string quotes are redundant
  - Updated ``from_dict()`` methods in ``UserInfo``, ``AuthTokens``, ``AuthenticationResponse``, ``DeviceStatus``, ``DeviceFeature``, and ``EnergyUsageResponse``
  - Improves code clarity and passes modern linting standards

Version 7.2.3 (2026-01-15)
==========================

Added
-----
- **Daily Energy Breakdown by Month**: New ``--month`` option for energy command to show daily energy data for a specific month

  .. code-block:: bash

     # Daily breakdown for a single month
     nwp-cli energy --year 2025 --month 12

     # Monthly summary for multiple months (existing)
     nwp-cli energy --year 2025 --months 10,11,12

  - Displays daily energy consumption, efficiency, and heat source breakdown
  - Rich formatted output with progress bars and color-coded efficiency percentages
  - Plain text fallback for non-Rich environments
  - Smart routing: single month shows daily data, multiple months show summary

Fixed
-----
- **Documentation**: Fixed all warnings and broken cross-references in documentation

  - Fixed docstring formatting in field_factory.py module
  - Fixed broken cross-reference links in enumerations.rst, mqtt_diagnostics.rst, cli.rst, and models.rst
  - Fixed invalid JSON syntax in code examples (removed invalid [...] and ... tokens)
  - Suppressed duplicate object description warnings from re-exported classes

- **CLI Documentation**: Updated documentation for all 19 CLI commands

  - Added missing device-info command documentation
  - Added --raw flag documentation for status, info, and device-info commands
  - Added --month option documentation to energy command
  - Clarified mutually exclusive options (--months vs --month)

- **RST Title Hierarchy**: Fixed title level inconsistencies in device_control.rst

- **Read the Docs Configuration**: Updated Python version requirement to 3.13 in Read the Docs config

- **CI Test Failures**: Fixed ``ModuleNotFoundError`` when running tests without CLI dependencies installed

  - Wrapped CLI module imports in try-except blocks in test modules
  - Tests are skipped gracefully when optional dependencies (click, rich) are not installed
  - Allows pytest to run without CLI extra, while supporting full test suite with tox
  - Network errors in authentication are now marked as retriable for better resilience

Changed
-------
- **Installation Documentation**: Updated installation instructions to clarify optional CLI and Rich dependencies

Version 7.2.2 (2025-12-25)
==========================

Fixed
-----
- **TOU Status Always Showing False**: Fixed ``touStatus`` field always reporting ``False`` regardless of actual device state

  - Root cause: Version 7.2.1 incorrectly changed ``touStatus`` to use device-specific 1/2 encoding, but the device uses standard 0/1 encoding
  - Solution: Use Python's built-in ``bool()`` for ``touStatus`` field (handles 0=False, 1=True naturally)
  - Updated documentation in ``docs/protocol/quick_reference.rst`` to note ``touStatus`` exception
  - Added tests verifying built-in ``bool()`` handles 0/1 encoding correctly
  - Device encoding: 0=OFF/disabled, 1=ON/enabled (standard Python truthiness)

Version 7.2.1 (2025-12-25)
==========================

Added
-----
- **CLI Command**: New ``device-info`` command to retrieve basic device information from REST API

  .. code-block:: bash

     # Get basic device info (DeviceInfo model)
     python3 -m nwp500.cli device-info
     python3 -m nwp500.cli device-info --raw

- **ConnectionStatus Enum**: New ``ConnectionStatus`` enum for device cloud connection state

  - ``ConnectionStatus.DISCONNECTED`` = 1 - Device offline/not connected
  - ``ConnectionStatus.CONNECTED`` = 2 - Device online and reachable
  - Used in ``DeviceInfo.connected`` field with automatic validation

- **InstallType Enum**: New ``InstallType`` enum for device installation classification

  - ``InstallType.RESIDENTIAL`` = "R" - Residential use
  - ``InstallType.COMMERCIAL`` = "C" - Commercial use
  - Used in ``DeviceInfo.install_type`` field with automatic validation
  - Includes ``INSTALL_TYPE_TEXT`` mapping for display purposes

- **String Enum Validator**: New ``str_enum_validator()`` converter for string-based enums

Changed
-------
- **DeviceInfo Model**:
  - ``connected`` field now uses ``ConnectionStatus`` enum instead of plain int
  - ``install_type`` field now uses ``InstallType`` enum instead of plain string

- **TOU Status Conversion**: Simplified TOU status to use standard ``device_bool_to_python`` converter (consistent with other OnOffFlag fields)
  - Removed special-case ``tou_status_to_python()`` converter
  - ``TouStatus`` annotated type now uses ``device_bool_to_python`` validator
  - Device encoding: 1=OFF/disabled, 2=ON/enabled (consistent with all other boolean fields)

- **CLI Documentation**: Clarified distinction between ``info`` (DeviceFeature via MQTT) and ``device-info`` (DeviceInfo via REST API) commands

- **Type Annotations**: Fixed CLI rich_output console type annotation to declare at class level

Removed
-------
- **constants.py Module**: Removed empty ``constants.py`` module. ``CommandCode`` enum was already moved to ``enums.py`` in version 4.2.0.

  .. code-block:: python

     # OLD (removed)
     from nwp500.constants import CommandCode

     # NEW (use this)
     from nwp500.enums import CommandCode

- **Firmware Tracking**: Removed unused firmware tracking constants and documentation (``KNOWN_FIRMWARE_FIELD_CHANGES``, ``LATEST_KNOWN_FIRMWARE``, ``docs/protocol/firmware_tracking.rst``)

- **TOU Status Converter**: Removed redundant ``tou_status_to_python()`` converter function and associated tests


Version 7.2.0 (2025-12-23)
==========================

**BREAKING CHANGES**: Class names renamed for consistency with MQTT-specific functionality

Removed
-------

- **Renamed Classes**: Updated class names to clarify MQTT-specific implementations

  .. code-block:: python

     # OLD (removed)
     from nwp500 import DeviceCapabilityChecker, DeviceInfoCache

     # NEW
     from nwp500 import MqttDeviceCapabilityChecker, MqttDeviceInfoCache

  **Rationale**: The original names were too generic. These classes are specifically designed
  for MQTT client functionality (auto-fetching device info, caching, capability checking).
  The new names make it clear they're MQTT-specific implementations, leaving room for future
  REST API versions if needed.

  **Migration**: Simple find-and-replace:

  - ``DeviceCapabilityChecker`` → ``MqttDeviceCapabilityChecker``
  - ``DeviceInfoCache`` → ``MqttDeviceInfoCache``

  All functionality remains identical; only the class names changed.

Added
-----

- **Factory Function**: New ``create_navien_clients()`` factory for streamlined client initialization

  .. code-block:: python

     # Create both API and MQTT clients in one call
     from nwp500 import create_navien_clients

     async with create_navien_clients(email, password) as (api_client, mqtt_client):
         devices = await api_client.get_devices()
         await mqtt_client.connect()
         # Both clients ready to use

  - Automatic auth client management (created internally, shared by both clients)
  - Simplified initialization for common use case (API + MQTT)
  - Proper async context manager support
  - Reduces boilerplate in application code
  - Documentation in ``docs/guides/authentication.rst``
  - Example: ``examples/intermediate/advanced_auth_patterns.py``

- **VolumeCode Enum**: Tank capacity identification with gallon values

  .. code-block:: python

     from nwp500 import VolumeCode

     # Enum values: VOLUME_50GAL = 65, VOLUME_65GAL = 66, VOLUME_80GAL = 67
     # Human-readable text available in VOLUME_CODE_TEXT dict

  - Maps device codes to actual tank capacities (50, 65, 80 gallons)
  - Used in ``DeviceFeature.volume_code`` field with automatic validation
  - Exported from main package for convenience
  - Includes ``VOLUME_CODE_TEXT`` mapping for display purposes

- **Temperature Conversion Classes**: Type-safe temperature handling with clear precision

  - ``HalfCelsius`` class: 0.5°C precision (value / 2.0)
  - ``DeciCelsius`` class: 0.1°C precision (value / 10.0)
  - Base ``Temperature`` ABC with ``to_celsius()`` and ``to_fahrenheit()`` methods
  - ``from_fahrenheit()`` class methods for reverse conversions
  - Validator functions for Pydantic integration
  - Centralized in new ``temperature.py`` module
  - Better type safety and clearer intent than raw number conversions

- **Protocol Converters Module**: Centralized device protocol conversion logic

  - ``device_bool_to_python()``: Convert device boolean (1=False, 2=True)
  - ``device_bool_from_python()``: Reverse conversion
  - ``tou_status_to_python()``: Time of Use status conversion
  - ``tou_override_to_python()``: TOU override status conversion
  - ``div_10()``: Divide by 10.0 utility
  - ``enum_validator()``: Generic enum factory
  - Documentation explaining device protocol quirks
  - New ``converters.py`` module replacing scattered validators

- **MQTT Event System**: Structured event handling for MQTT operations

  - ``MqttClientEvents`` class with type-safe event definitions
  - Feature monitoring and capability detection events
  - Enhanced device capability monitoring in MQTT control module
  - New ``mqtt_events.py`` module for event infrastructure
  - Improved separation of concerns for event-driven architectures

- **Pyright Type Checking**: Static type analysis integrated into CI/CD

  - Added pyright>=1.1.0 to dev dependencies
  - Configured in ``pyproject.toml`` with strict mode for ``src/nwp500``
  - Integrated into tox lint environment and CI workflows
  - Runs automatically with ``make ci-lint`` or ``python3 scripts/lint.py``
  - All source code now passes strict type checking (0 errors)
  - Improved type annotations across codebase

- **Dynamic Unit Extraction in CLI**: CLI output now dynamically extracts units from DeviceStatus model metadata

  - New helper functions: ``_get_unit_suffix()`` and ``_add_numeric_item()``
  - Eliminates hardcoded units in output formatter
  - Single source of truth: model metadata drives CLI display

- **Protocol Documentation**: Complete protocol reference documentation

  - New ``docs/protocol/quick_reference.rst`` with command codes, field formats, and conversions
  - Converted protocol documentation to RST format for Sphinx integration
  - Added protocol reference links in source code comments
  - Improved cross-referencing between code and documentation

Changed
-------

- **MQTT Module Reorganization**: Consolidated 9 separate modules into cohesive ``mqtt`` package

  .. code-block:: python

     # OLD imports (still work via compatibility layer)
     from nwp500.mqtt_client import NavienMqttClient
     from nwp500.mqtt_diagnostics import MqttDiagnosticsCollector
     from nwp500.mqtt_utils import MqttConnectionConfig

     # NEW imports (preferred)
     from nwp500.mqtt import NavienMqttClient, MqttDiagnosticsCollector, MqttConnectionConfig
     # OR import from main package (recommended)
     from nwp500 import NavienMqttClient, MqttDiagnosticsCollector, MqttConnectionConfig

  - Created ``src/nwp500/mqtt/`` package with organized submodules
  - Better package organization and structure
  - Clearer public vs internal APIs
  - New ``mqtt/__init__.py`` with clean public API exports
  - Backward compatibility maintained via main package exports
  - All 209 tests pass with zero type checking errors

- **CLI Framework Migration**: Migrated from argparse to Click framework

  - Implemented ``async_command`` decorator for automatic loop and connection management
  - Added support for command groups (reservations, tou)
  - Improved argument and option parsing with built-in validation
  - Enhanced help text and version reporting
  - Centralized command registry in ``src/nwp500/cli/commands.py``
  - Reorganized CLI handlers into ``src/nwp500/cli/handlers.py``
  - Better separation of concerns between CLI framework and business logic
  - Industry-standard CLI framework with better maintainability
  - Added click>=8.0.0 dependency

- **Examples Reorganization**: Restructured examples into beginner/intermediate/advanced/testing categories

  - Created structured hierarchy in ``examples/`` directory
  - Renamed and moved 35+ example scripts for better discoverability
  - Updated ``examples/README.md`` with 'Getting Started' guide and categorized index
  - Added 01-04 beginner series for smooth onboarding:

    - ``beginner/01_authentication.py`` - Basic authentication patterns
    - ``beginner/02_list_devices.py`` - Retrieving device information
    - ``beginner/03_get_status.py`` - Getting device status
    - ``beginner/04_set_temperature.py`` - Basic device control

  - Intermediate examples: event-driven control, error handling, MQTT monitoring
  - Advanced examples: demand response, recirculation, TOU schedules, diagnostics
  - Testing examples: connection testing, periodic updates, minimal examples
  - All examples updated with correct imports for new package structure

- **Authentication Documentation**: Major improvements to authentication guide

  - Complete rewrite of ``docs/guides/authentication.rst``
  - Added factory function patterns and examples
  - Improved context manager documentation
  - Added best practices and common patterns
  - More code examples

- **Model Refactoring**: Updated to use new converter modules

  - Replaced 53 lines of scattered validators with imports
  - Updated ``fahrenheit_to_half_celsius()`` to use ``HalfCelsius`` class
  - Cleaner model definitions with centralized conversion logic
  - No breaking changes to public API

- **CLI Output Formatter Refactoring**: Restructured ``print_device_status()`` to use dynamic unit extraction

  - Reduced code duplication by ~400 lines
  - Improved maintainability: field additions automatically get correct units
  - No breaking changes to CLI output format or behavior

- **Type Annotations**: Improved type safety across entire codebase

  - Fixed datetime imports to use ``datetime.UTC`` (Python 3.13)
  - Fixed type annotations in ``rich_output.py`` for optional dependencies
  - Fixed type narrowing issues in ``encoding.py``
  - Updated ``MqttConnection`` callback signature to use ``AwsCrtError``
  - Added public properties and setters where needed for type checking

Fixed
-----

- **Superheat Temperature Units**: Target and Current SuperHeat now correctly display in °F instead of °C

  - Both fields use ``DeciCelsiusToF`` conversion, now properly reflected in CLI output
  - Fields were displaying inconsistent units compared to all other temperature readings

- **Missing CLI Output Units**: Multiple fields now display with proper units from model metadata

  - ``current_dhw_flow_rate``: Now shows GPM unit
  - ``total_energy_capacity``: Now shows Wh unit
  - ``available_energy_capacity``: Now shows Wh unit
  - ``dr_override_status``: Now shows hours unit
  - ``vacation_day_setting``: Now shows days unit
  - ``vacation_day_elapsed``: Now shows days unit
  - ``anti_legionella_period``: Fixed to show days unit (was incorrectly h)
  - ``wifi_rssi``: Now shows dBm unit

- **Invalid MQTT Topic Filter**: Fixed ``reservations get`` command subscription topic

  - Changed invalid topic pattern ``cmd/52/navilink-+/#`` to valid ``cmd/52/+/#``
  - AWS IoT Core MQTT does not support wildcards within topic segments
  - Affected: ``handle_get_reservations_request()`` in commands.py

- **DeviceFeature Documentation**: Clarified field descriptions and fixed documentation errors

  - Fixed ``country_code`` documentation (actual value is 3, not 1 as previously noted)
  - Clarified ``model_type_code``, ``control_type_code``, ``recirc_model_type_code`` field purposes
  - Updated ``volume_code`` to use new ``VolumeCode`` enum with validation

- **Type Checking Errors**: Resolved all pyright type checking errors in source code

  - Fixed datetime imports and type annotations
  - Added missing public properties and setters
  - Removed unused imports and variables
  - All source code now passes strict type checking

Version 7.1.0 (2025-12-22)
==========================

Added
-----

- **Device Capability System**: New device capability detection and validation framework:
  - ``DeviceCapabilityChecker``: Validates device feature support based on device models
  - ``DeviceInfoCache``: Efficient caching of device information with configurable update intervals
  - ``@requires_capability`` decorator: Automatic capability validation for MQTT commands
  - ``DeviceCapabilityError``: New exception for unsupported device features

- **Advanced Control Commands**: New MQTT commands for advanced device features:
  - ``enable_demand_response()`` / ``disable_demand_response()``: Demand response participation control
  - ``reset_air_filter()``: Air filter maintenance tracking reset
  - ``set_vacation_days()``: Configure vacation mode duration
  - ``configure_reservation_water_program()``: Water program reservation management
  - ``set_recirculation_mode()`` / ``configure_recirculation_schedule()`` / ``trigger_recirculation_hot_button()``: Recirculation pump control and scheduling

- **CLI Documentation Updates**: Documentation updates for subcommand-based CLI
  - Complete rewrite of ``docs/python_api/cli.rst`` with full command reference
  - Updated README.rst with new subcommand syntax and examples
  - Added 8+ practical usage examples (cron jobs, automation, monitoring)
  - Added troubleshooting guide and best practices section

- **Model Field Factory Pattern**: New field factory to reduce boilerplate in model definitions
  - Automatic field conversion and validation
  - Cleaner model architecture

Changed
-------

- **CLI Output**: Numeric values in status output now rounded to one decimal place for better readability
- ``MqttDeviceController`` now integrates device capability checking with auto-caching of device info
- Exception type hints improved with proper None handling in optional parameters
- **MQTT Control Refactoring**: Centralized device control via ``.control`` namespace
  - Standardized periodic request patterns
  - Public API method ``ensure_device_info_cached()`` for better cache management
- **Logging Security**: Enhanced sensitive data redaction
  - MAC addresses consistently redacted across all logging output
  - Token logging removed from docstrings and examples
  - Intermediate variables used for redacted data

Fixed
-----

- Type annotation consistency: Optional parameters now properly annotated as ``type | None`` instead of ``type``
- **Type System Fixes**: Resolved multiple type annotation issues for CI compatibility
- **Mixing Valve Field**: Corrected alias field name and removed unused TOU status validator
- **Vacation Days Validation**: Enforced maximum value validation for vacation mode days
- **CI Linting**: Fixed line length violations and import sorting issues
- **Security Scanning**: Resolved intermediate variable issues in redacted MAC address handling
- **Parser Regressions**: Fixed data parsing issues introduced in MQTT refactoring

Version 7.0.1 (2025-12-18)
==========================

Fixed
-----
- Minor bug fixes and improvements

Version 7.0.0 (2025-12-17)
==========================

**BREAKING CHANGES**:
- Minimum Python version raised to 3.13
- Enumerations refactored for type safety and consistency

Removed
-------
- **Python 3.9-3.12 Support**: Minimum Python version is now 3.13

  Home Assistant has deprecated Python 3.12 support, making Python 3.13 the de facto minimum for this ecosystem.

  Python 3.13 features and improvements:

  - **Experimental free-threaded mode** (PEP 703): Optional GIL removal for true parallelism
  - **JIT compiler** (PEP 744): Just-in-time compilation for performance improvements
  - **Better error messages**: Enhanced suggestions for NameError, AttributeError, and import errors
  - **Type system enhancements**: TypeVars with defaults (PEP 696), @deprecated decorator (PEP 702), ReadOnly TypedDict (PEP 705)
  - **Performance**: ~5-10% faster overall, optimized dictionary/set operations, better function calls
  - PEP 695: New type parameter syntax for generics
  - PEP 701: f-string improvements
  - Built-in ``datetime.UTC`` constant

  If you need Python 3.12 support, use version 6.1.x of this library.

- **CommandCode moved**: Import from ``nwp500.enums`` instead of ``nwp500.constants``

  .. code-block:: python

     # OLD (removed)
     from nwp500.constants import CommandCode

     # NEW
     from nwp500.enums import CommandCode
     # OR
     from nwp500 import CommandCode  # Still works

Added
-----

- **Python 3.12+ Optimizations**: Use the latest Python features

  - PEP 695: New type parameter syntax (``def func[T](...)`` instead of ``TypeVar``)
  - Use ``datetime.UTC`` constant instead of ``datetime.timezone.utc``
  - Native union syntax (``X | Y`` instead of ``Union[X, Y]``)
  - Cleaner generic type annotations throughout codebase

- **Enumerations Module (``src/nwp500/enums.py``)**: Type-safe enums for device control and status

  - Status value enums: ``OnOffFlag``, ``Operation``, ``DhwOperationSetting``, ``CurrentOperationMode``, ``HeatSource``, ``DREvent``, ``WaterLevel``, ``FilterChange``, ``RecirculationMode``
  - Time of Use enums: ``TouWeekType``, ``TouRateType``
  - Device capability enums: ``CapabilityFlag``, ``TemperatureType``, ``DeviceType``
  - Device control command enum: ``CommandCode`` (all MQTT command codes)
  - Error code enum: ``ErrorCode`` with complete error code mappings
  - Human-readable text mappings for all enums (e.g., ``DHW_OPERATION_SETTING_TEXT``, ``ERROR_CODE_TEXT``)
  - Exported from main package: ``from nwp500 import OnOffFlag, ErrorCode, CommandCode``
  - Documentation in ``docs/enumerations.rst``
  - Example usage in ``examples/error_code_demo.py``

Changed
-------

- **Command Code Constants**: Migrated from ``constants.py`` to ``CommandCode`` enum in ``enums.py``

  - ``ANTI_LEGIONELLA_ENABLE`` → ``CommandCode.ANTI_LEGIONELLA_ON``
  - ``ANTI_LEGIONELLA_DISABLE`` → ``CommandCode.ANTI_LEGIONELLA_OFF``
  - ``TOU_ENABLE`` → ``CommandCode.TOU_ON``
  - ``TOU_DISABLE`` → ``CommandCode.TOU_OFF``
  - ``TOU_SETTINGS`` → ``CommandCode.TOU_RESERVATION``
  - All command constants now use consistent naming in ``CommandCode`` enum

- **Model Enumerations**: Updated type annotations for clarity and type safety

  - ``TemperatureUnit`` → ``TemperatureType`` (matches device protocol field names)
  - All capability flags (e.g., ``power_use``, ``dhw_use``) now use ``CapabilityFlag`` type
  - ``MqttRequest.device_type`` now accepts ``Union[DeviceType, int]`` for flexibility

- **Model Serialization**: Enums automatically serialize to human-readable names

  - `model_dump()` converts enums to names (e.g., `DhwOperationSetting.HEAT_PUMP` → `"HEAT_PUMP"`)
  - CLI and other consumers benefit from automatic enum name serialization
  - Text mappings available for custom formatting (e.g., `DHW_OPERATION_TEXT[enum]` → "Heat Pump Only")

- **Documentation**: Updates across protocol and API documentation

  - ``docs/guides/time_of_use.rst``: Clarified TOU override status behavior (1=OFF/override active, 2=ON/normal operation)
  - ``docs/protocol/data_conversions.rst``: Updated TOU field descriptions with correct enum values
  - ``docs/protocol/device_features.rst``: Added capability flag pattern explanation (2=supported, 1=not supported)
  - ``docs/protocol/mqtt_protocol.rst``: Updated command code references to use new enum names
  - ``docs/python_api/models.rst``: Updated model field type annotations

- **Examples**: Updated to use new enums for type-safe device control

  - ``examples/anti_legionella_example.py``: Uses ``CommandCode`` enum
  - ``examples/device_feature_callback.py``: Uses capability enums
  - ``examples/event_emitter_demo.py``: Uses status enums
  - ``examples/mqtt_diagnostics_example.py``: Uses command enums

- **CLI Code Cleanup**: Refactored JSON formatting to use shared utility function

  - Extracted repeated `json.dumps()` calls to `format_json_output()` helper
  - Cleaner code with consistent formatting across all commands

Fixed
-----

- **Temperature Conversion Test**: Corrected ``test_device_status_div10`` to use ``HalfCelsiusToF`` conversion (100 → 122°F, not 50.0)
- **Documentation**: Fixed references to non-existent ``OperationMode`` enum - replaced with correct ``DhwOperationSetting`` and ``CurrentOperationMode`` enums

Version 6.1.1 (2025-12-08)
==========================

Added
-----

- **MQTT Diagnostics Module**: New ``MqttDiagnosticsCollector`` for capturing MQTT message traffic for debugging

  - Captures all MQTT publish/subscribe activity with timestamps and payloads
  - Configurable message filtering by topic pattern
  - Message deduplication to reduce storage
  - Automatic cleanup of old diagnostics (configurable retention)
  - Export diagnostics to JSON for analysis and debugging
  - Home Assistant integration support for custom components
  - ``examples/mqtt_diagnostics_example.py`` demonstrating usage patterns
  - Documentation in ``docs/MQTT_DIAGNOSTICS.rst``
  - Exported from main package: ``from nwp500 import MqttDiagnosticsCollector``

Version 6.1.0 (2025-12-03)
==========================

**BREAKING CHANGES**: Temperature API simplified with Fahrenheit input

This release fixes incorrect temperature conversions and provides a cleaner API
where users pass temperatures in Fahrenheit directly, with automatic conversion
to the device's internal format.

Changed
-------

- **``build_reservation_entry()``**: Now accepts ``temperature_f`` (Fahrenheit)
  instead of raw ``param`` value. The conversion to half-degrees Celsius is
  handled automatically.

  .. code-block:: python

     # OLD (removed)
     build_reservation_entry(..., param=120)

     # NEW
     build_reservation_entry(..., temperature_f=140.0)

- **``set_dhw_temperature()``**: Now accepts ``temperature_f: float`` (Fahrenheit)
  instead of raw integer. Valid range: 95-150°F.

  .. code-block:: python

     # OLD (removed)
     await mqtt.set_dhw_temperature(device, 120)

     # NEW
     await mqtt.set_dhw_temperature(device, 140.0)

Removed
-------

- **``set_dhw_temperature_display()``**: Removed. This method used an incorrect
  conversion formula (subtracting 20 instead of proper half-degrees Celsius
  encoding). Use ``set_dhw_temperature()`` with Fahrenheit directly.

Added
-----

- **``fahrenheit_to_half_celsius()``**: New utility function for converting
  Fahrenheit to the device's half-degrees Celsius format. Exported from the
  main package for advanced use cases.

  .. code-block:: python

     from nwp500 import fahrenheit_to_half_celsius

     param = fahrenheit_to_half_celsius(140.0)  # Returns 120

Fixed
-----

- **Temperature Encoding Bug**: Fixed ``set_dhw_temperature()`` which was using
  an incorrect "subtract 20" conversion instead of proper half-degrees Celsius
  encoding. This caused temperatures to be set incorrectly for values other
  than 140°F (where both formulas happened to give the same result).

Version 6.0.8 (2025-12-02)
==========================

Changed
-------

- **Maintenance Release**: Version bump for PyPI release

Version 6.0.7 (2025-11-30)
==========================

Added
-----

- **Documentation**: Added TOU (Time-of-Use) enable/disable command payload formats to protocol documentation

Version 6.0.6 (2025-11-24)
==========================

Added
-----

- **Field Descriptions**: Added Field descriptions to ``DeviceStatus`` and ``DeviceFeature`` models with full documentation details including units, ranges, and usage context

Fixed
-----

- **Example Code**: Fixed ``device_status_callback.py`` example to use snake_case attribute names consistently
- **Field Descriptions**: Clarified distinctions between similar fields:

  - ``dhw_temperature_setting`` vs ``dhw_target_temperature_setting`` descriptions
  - ``freeze_protection_temp`` descriptions differ between DeviceStatus and DeviceFeature
  - ``eco_use`` descriptions differ between DeviceStatus (current state) and DeviceFeature (capability)

Version 6.0.5 (2025-11-21)
==========================

Fixed
-----

- **Temperature Conversion Bug**: Corrected temperature conversion formula for 8 sensor fields that were displaying values ~100°F higher than expected. The v6.0.4 change incorrectly used division by 5 (pentacelsius) instead of division by 10 (decicelsius) for these fields:

  - ``tank_upper_temperature`` - Water tank upper sensor
  - ``tank_lower_temperature`` - Water tank lower sensor
  - ``discharge_temperature`` - Compressor discharge temperature (refrigerant)
  - ``suction_temperature`` - Compressor suction temperature (refrigerant)
  - ``evaporator_temperature`` - Evaporator coil temperature (refrigerant)
  - ``ambient_temperature`` - Ambient air temperature at heat pump
  - ``target_super_heat`` - Target superheat setpoint
  - ``current_super_heat`` - Measured superheat value

  **Impact**: These fields now correctly display temperatures in expected ranges:

  - Tank temperatures: ~120°F (close to DHW temperature, not ~220°F)
  - Discharge temperature: 120-180°F (not 220-280°F)
  - Suction, evaporator, ambient: Now showing physically realistic values

  **Technical details**: Changed from ``PentaCelsiusToF`` (÷5) back to ``DeciCelsiusToF`` (÷10). The correct formula is ``(raw_value / 10.0) * 9/5 + 32``.

Changed
-------

- **Documentation**: Updated ``data_conversions.rst`` and ``device_status.rst`` to reflect correct ``DeciCelsiusToF`` conversion for refrigerant circuit and tank temperature sensors

Version 6.0.4 (2025-11-21)
==========================

Fixed
-----

- **Temperature Conversion Accuracy**: Corrected temperature conversion logic based on analysis of the decompiled mobile application. Previous conversions used approximations; new logic uses exact formulas from the app:

  - Replaced ``Add20`` validator with ``HalfCelsiusToF`` for fields transmitted as half-degrees Celsius
  - Replaced ``DeciCelsiusToF`` with ``PentaCelsiusToF`` for fields scaled by factor of 5
  - Affects multiple temperature sensor readings for improved accuracy

- **CLI Output Formatting**: Fixed formatting issues in command-line interface output

Changed
-------

- **Documentation**: Updated temperature conversion documentation to use precise 9/5 fraction instead of 1.8 approximation for clarity

Added
-----

- **Test Coverage**: Added ``tests/test_models.py`` to verify temperature conversion correctness

Version 6.0.3 (2025-11-20)
==========================

**BREAKING CHANGES**: Migration from custom dataclass-based models to Pydantic BaseModel implementations with automatic field validation and alias handling.

Removed
-------

- Removed legacy dataclass implementations for models (DeviceInfo, Location, Device, FirmwareInfo, DeviceStatus, DeviceFeature, EnergyUsage*). All models now inherit from ``NavienBaseModel`` (Pydantic).
- Removed manual ``from_dict`` constructors relying on camelCase key mapping logic.
- Removed field metadata conversion system (``meta()`` + ``apply_field_conversions()``) in favor of Pydantic ``BeforeValidator`` pipeline.

Changed
-------

- Models now use snake_case attribute names consistently; camelCase keys from API/MQTT are mapped automatically via Pydantic ``alias_generator=to_camel``.
- Boolean device fields now validated via ``DeviceBool`` Annotated type (device value 2 -> True, 0/1 -> False) replacing manual conversion code.
- Temperature offset (+20), scale division (/10) and decicelsius-to-Fahrenheit conversions implemented with lightweight ``BeforeValidator`` functions (``Add20``, ``Div10``, ``DeciCelsiusToF``) instead of post-processing.
- Enum parsing now handled directly by Pydantic; unknown values default safely via explicit Field defaults instead of try/except conversion loops.
- Field names updated (examples & docs) to snake_case: e.g. ``operationMode`` -> ``operation_mode``, ``dhwTemperatureSetting`` -> ``dhw_temperature_setting``.
- API typo handled using Field alias (``heLowerOnTDiffempSetting`` -> ``he_lower_on_diff_temp_setting``) rather than custom dictionary mutation.
- DeviceStatus conversion now performed on parse instead of separate transformation step, improving performance and reducing memory copies.
- Improved validation error messages from Pydantic on malformed payloads.
- Simplified energy usage model accessors; removed manual percentage methods duplication.

Added
-----

- Introduced ``NavienBaseModel`` configuring alias generation, population by name, and ignoring unknown fields for forward compatibility.
- Added structured Annotated types: ``DeviceBool``, ``Add20``, ``Div10``, ``DeciCelsiusToF`` for declarative conversion definitions.
- Added consistent default enum values directly in field declarations (e.g. ``operation_mode=STANDBY``).

Migration Guide (v6.0.2 -> v6.0.3)
----------------------------------

1. Replace any imports of dataclass models with Pydantic versions (paths unchanged). No code change required if you only accessed attributes.
2. Remove calls to ``Model.from_dict(data)``: Either use ``Model.model_validate(data)`` or continue calling ``from_dict`` where still provided (thin wrapper for backward compatibility on some classes). Preferred: ``DeviceStatus.model_validate(raw_payload)``.
3. Update attribute access to snake_case. Common mappings:
   - ``deviceInfo.macAddress`` -> ``device.device_info.mac_address``
   - ``deviceStatus.operationMode`` -> ``status.operation_mode``
   - ``deviceStatus.dhwTemperatureSetting`` -> ``status.dhw_temperature_setting``
   - ``deviceStatus.currentInletTemperature`` -> ``status.current_inlet_temperature``
4. Remove manual conversion code. Raw numeric values are converted automatically; stop adding +20 or dividing by 10 in user code.
5. Stop performing boolean normalization (``value == 2``) manually; attributes already return proper bools.
6. For enum handling, remove try/except wrappers; rely on defaulted fields (e.g. ``operation_mode`` defaults to ``STANDBY``).
7. If you previously mutated raw payload keys to snake_case, eliminate that transformation step.
8. If you logged intermediate converted dictionaries, you can access ``model.model_dump()`` for a fully converted representation.
9. Replace any custom validation logic with Pydantic validators or continue using existing patterns; most prior validation code is now unnecessary.
10. Energy usage: Access percentages via properties unchanged; object types now Pydantic models.

Quick Example
~~~~~~~~~~~~~

.. code-block:: python

   # OLD (v6.0.2)
   raw = mqtt_payload["deviceStatus"]
   converted = apply_field_conversions(DeviceStatus, raw)
   status = DeviceStatus(**converted)
   print(converted["dhwTemperatureSetting"] + 20)  # manual offset

   # NEW (v6.0.3)
   status = DeviceStatus.model_validate(mqtt_payload["deviceStatus"])
   print(status.dhw_temperature_setting)  # already includes +20 offset

   # OLD boolean and enum handling
   is_heating = converted["currentHeatUse"] == 2
   mode = OperationMode(converted["operationMode"]) if converted["operationMode"] in (0,32,64,96) else OperationMode.STANDBY

   # NEW simplified
   is_heating = status.current_heat_use
   mode = status.operation_mode

Benefits
~~~~~~~~

- Declarative conversions reduce 400+ lines of imperative transformation logic.
- Improved performance (single parse vs copy + transform).
- Automatic camelCase key mapping; less brittle than manual dict key copying.
- Rich validation errors for debugging malformed device messages.
- Cleaner, shorter model definitions with clearer intent.
- Easier extension: add new fields with conversion by combining Annotated + validator.

Version 6.0.2 (2025-11-15)
==========================

Fixed
-----

- DNS resolution in containerized environments using ThreadedResolver
- Updated AWS IoT library version
- Device status field conversions

Changed
-------

- Refactored ThreadedResolver session creation into helper method

Version 6.0.1 (2025-11-06)
==========================

Fixed
-----

- Minor bug fixes and improvements

Version 6.0.0 (2025-11-02)
==========================

**BREAKING CHANGES**: Removed constructor callbacks and backward compatibility re-exports

Removed
-------

- **Constructor Callbacks**: Removed ``on_connection_interrupted`` and ``on_connection_resumed`` constructor parameters from ``NavienMqttClient``

  .. code-block:: python

     # OLD (removed in v6.0.0)
     mqtt_client = NavienMqttClient(
         auth_client,
         on_connection_interrupted=on_interrupted,
         on_connection_resumed=on_resumed,
     )

     # NEW (use event emitter pattern)
     mqtt_client = NavienMqttClient(auth_client)
     mqtt_client.on("connection_interrupted", on_interrupted)
     mqtt_client.on("connection_resumed", on_resumed)

- **Backward Compatibility Re-exports**: Removed exception re-exports from ``api_client`` and ``auth`` modules

  .. code-block:: python

     # OLD (removed in v6.0.0)
     from nwp500.api_client import APIError
     from nwp500.auth import AuthenticationError, TokenRefreshError

     # NEW (import from exceptions module)
     from nwp500.exceptions import APIError, AuthenticationError, TokenRefreshError

     # OR (import from package root - recommended)
     from nwp500 import APIError, AuthenticationError, TokenRefreshError

- **Rationale**: Library is young with no external clients. Removing backward compatibility
  allows for cleaner architecture and prevents accumulation of legacy patterns.

Changed
-------

- **Migration Benefits**:

  - Multiple listeners per event (not just one callback)
  - Consistent API with other events (temperature_changed, mode_changed, etc.)
  - Dynamic listener management (add/remove listeners at runtime)
  - Async handler support
  - Priority-based execution
  - Cleaner imports (exceptions from one module)

- Updated ``examples/command_queue_demo.py`` to use event emitter pattern
- Updated ``examples/reconnection_demo.py`` to use event emitter pattern
- Updated ``examples/device_status_callback.py`` to import exceptions from correct module
- Updated ``examples/device_status_callback_debug.py`` to import exceptions from correct module
- Updated ``examples/device_feature_callback.py`` to import exceptions from correct module
- Updated ``examples/test_api_client.py`` to import exceptions from correct module
- Removed misleading "legacy state" comments from connection tracking code

Version 5.0.2 (2025-10-31)
==========================

Fixed
-----

- **MQTT Future Cancellation**: Fixed InvalidStateError exceptions during disconnect

  - Added asyncio.shield() to protect concurrent.futures.Future objects from cancellation
  - Applied consistent cancellation handling across all MQTT operations (connect, disconnect, subscribe, unsubscribe, publish)
  - AWS CRT callbacks can now complete independently without raising InvalidStateError
  - Added debug logging when operations are cancelled for better diagnostics
  - Clean shutdown without spurious exception messages

Version 5.0.1 (2025-10-27)
==========================

Changed
-------

- **Maintenance Release**: Removed deprecated backward compatibility code

  - Removed ``CMD_*`` backward compatibility aliases from ``constants.py``
  - Removed ``cli.py`` backward compatibility wrapper module
  - Updated setup.cfg entry point to use ``nwp500.cli.__main__:run`` directly
  - Updated all examples to use ``CommandCode`` enum instead of ``CMD_*`` aliases
  - Updated examples to use standalone functions (``build_tou_period``, ``encode_price``, ``decode_price``, ``encode_week_bitfield``, ``decode_week_bitfield``) instead of ``NavienAPIClient.*`` static methods
  - Updated documentation to reference standalone functions
  - Fixed deprecated method name (``set_dhw_operation_setting`` → ``set_dhw_mode``)
  - Removed broken relative links from ``README.rst``
  - Added Read the Docs and GitHub links to ``README.rst`` header

Version 5.0.0 (2025-10-27)
==========================

**BREAKING CHANGES**: This release introduces an enterprise exception architecture.
See migration guide below for details on updating your code.

Added
-----

- **Enterprise Exception Architecture**: Complete exception hierarchy for better error handling

  - Created ``exceptions.py`` module with an exception hierarchy
  - Added ``Nwp500Error`` as base exception for all library errors
  - Added MQTT-specific exceptions: ``MqttError``, ``MqttConnectionError``, ``MqttNotConnectedError``,
    ``MqttPublishError``, ``MqttSubscriptionError``, ``MqttCredentialsError``
  - Added validation exceptions: ``ValidationError``, ``ParameterValidationError``, ``RangeValidationError``
  - Added device exceptions: ``DeviceError``, ``DeviceNotFoundError``, ``DeviceOfflineError``,
    ``DeviceOperationError``
  - All exceptions now include ``error_code``, ``details``, and ``retriable`` attributes
  - Added ``to_dict()`` method to all exceptions for structured logging
  - Added a test suite in ``tests/test_exceptions.py``
  - **Added an exception handling example** (``examples/exception_handling_example.py``)
  - **Updated the main examples** to demonstrate new exception handling patterns

Changed
-------

- **Exception Handling Improvements**:

  - All exception wrapping now uses exception chaining (``raise ... from e``) to preserve stack traces
  - Replaced 19+ instances of ``RuntimeError("Not connected to MQTT broker")`` with ``MqttNotConnectedError``
  - Replaced ``ValueError`` in validation code with ``RangeValidationError`` and ``ParameterValidationError``
  - Replaced ``ValueError`` for credentials with ``MqttCredentialsError``
  - Replaced ``RuntimeError`` for connection issues with ``MqttConnectionError``
  - Enhanced ``AwsCrtError`` wrapping in MQTT code with proper exception chaining
  - Moved authentication exceptions from ``auth.py`` to ``exceptions.py``
  - Moved ``APIError`` from ``api_client.py`` to ``exceptions.py``
  - **CLI now handles specific exception types** with better error messages and user guidance

Migration Guide (v4.x to v5.0)
-------------------------------

**Breaking Changes Summary**:

The library now uses specific exception types instead of generic ``RuntimeError`` and ``ValueError``.
This improves error handling but requires updates to exception handling code.

**1. MQTT Connection Errors**

.. code-block:: python

    # OLD CODE (v4.x) - will break
    try:
        await mqtt_client.request_device_status(device)
    except RuntimeError as e:
        if "Not connected" in str(e):
            await mqtt_client.connect()

    # NEW CODE (v5.0+)
    from nwp500 import MqttNotConnectedError, MqttError

    try:
        await mqtt_client.request_device_status(device)
    except MqttNotConnectedError:
        # Handle not connected - attempt reconnection
        await mqtt_client.connect()
        await mqtt_client.request_device_status(device)
    except MqttError as e:
        # Handle other MQTT errors
        logger.error(f"MQTT error: {e}")

**2. Validation Errors**

.. code-block:: python

    # OLD CODE (v4.x) - will break
    try:
        set_vacation_mode(device, days=35)
    except ValueError as e:
        print(f"Invalid input: {e}")

    # NEW CODE (v5.0+)
    from nwp500 import RangeValidationError, ValidationError

    try:
        set_vacation_mode(device, days=35)
    except RangeValidationError as e:
        # Access structured error information
        print(f"Invalid {e.field}: must be {e.min_value}-{e.max_value}")
        print(f"You provided: {e.value}")
    except ValidationError as e:
        # Handle other validation errors
        print(f"Validation error: {e}")

**3. AWS Credentials Errors**

.. code-block:: python

    # OLD CODE (v4.x) - will break
    try:
        mqtt_client = NavienMqttClient(auth_client)
    except ValueError as e:
        if "credentials" in str(e).lower():
            # handle missing credentials

    # NEW CODE (v5.0+)
    from nwp500 import MqttCredentialsError

    try:
        mqtt_client = NavienMqttClient(auth_client)
    except MqttCredentialsError as e:
        # Handle missing or invalid AWS credentials
        logger.error(f"Credentials error: {e}")
        await re_authenticate()

**4. Catching All Library Errors**

.. code-block:: python

    # NEW CODE (v5.0+) - catch all library exceptions
    from nwp500 import Nwp500Error

    try:
        # Any library operation
        await mqtt_client.request_device_status(device)
    except Nwp500Error as e:
        # All nwp500 exceptions inherit from Nwp500Error
        logger.error(f"Library error: {e.to_dict()}")

        # Check if retriable
        if e.retriable:
            await retry_operation()

**5. Enhanced Error Information**

All exceptions now include structured information:

.. code-block:: python

    from nwp500 import MqttPublishError

    try:
        await mqtt_client.publish(topic, payload)
    except MqttPublishError as e:
        # Access structured error information
        error_info = e.to_dict()
        # {
        #     'error_type': 'MqttPublishError',
        #     'message': 'Publish failed',
        #     'error_code': 'AWS_ERROR_...',
        #     'details': {},
        #     'retriable': True
        # }

        # Log for monitoring/alerting
        logger.error("Publish failed", extra=error_info)

        # Implement retry logic
        if e.retriable:
            await asyncio.sleep(1)
            await mqtt_client.publish(topic, payload)

**Quick Migration Strategy**:

1. Import new exception types: ``from nwp500 import MqttNotConnectedError, MqttError, ValidationError``
2. Replace ``except RuntimeError`` with ``except MqttNotConnectedError`` for connection checks
3. Replace ``except ValueError`` with ``except ValidationError`` for parameter validation
4. Use ``except Nwp500Error`` to catch all library errors
5. Test error handling paths thoroughly

**Benefits of New Architecture**:

- Specific exception types for specific errors (no more string matching)
- Preserved stack traces with exception chaining (``from e``)
- Structured error information via ``to_dict()``
- Retriable flag for implementing retry logic
- Better integration with monitoring/logging systems
- Type-safe error handling
- Clearer API documentation

Version 4.8.0 (2025-10-27)
==========================

Added
-----

- **Token Restoration Support**: Enable session persistence across application restarts

  - Added ``stored_tokens`` parameter to ``NavienAuthClient.__init__()`` for restoring saved tokens
  - Added ``AuthTokens.to_dict()`` method for serializing tokens (includes ``issued_at`` timestamp)
  - Enhanced ``AuthTokens.from_dict()`` to support both API responses (camelCase) and stored data (snake_case)
  - Modified ``NavienAuthClient.__aenter__()`` to skip authentication when valid stored tokens are provided
  - Automatically refreshes expired JWT tokens or re-authenticates if AWS credentials expired
  - Added 7 new tests for token serialization, deserialization, and restoration flows
  - Added ``examples/token_restoration_example.py`` demonstrating save/restore workflow
  - Updated authentication documentation with token restoration guide

- **Benefits**: Reduces API load, improves startup time, prevents rate limiting for frequently restarting applications (e.g., Home Assistant)

Version 4.7.1 (2025-10-27)
==========================

Changed
-------

- **Patch Release**: No code changes, updated version format to full semantic versioning

Version 4.7 (2025-10-27)
========================

Added
-----

- **MQTT Reconnection**: Two-tier reconnection strategy with unlimited retries

  - Implemented quick reconnection (attempts 1-9) for fast recovery from transient network issues
  - Implemented deep reconnection (every 10th attempt) with full connection rebuild and credential refresh
  - Changed default ``max_reconnect_attempts`` from 10 to -1 (unlimited retries)
  - Added ``deep_reconnect_threshold`` configuration parameter (default: 10)
  - Added ``has_stored_credentials`` property to ``NavienAuthClient``
  - Added ``re_authenticate()`` method to ``NavienAuthClient`` for credential-based re-authentication
  - Added ``resubscribe_all()`` method to ``MqttSubscriptionManager`` for subscription recovery
  - Deep reconnection now performs token refresh and falls back to full re-authentication if needed
  - Deep reconnection automatically re-establishes all subscriptions after rebuild
  - Connection now continues retrying indefinitely instead of giving up after 10 attempts

Improved
--------

- **Exception Handling**: Replaced 25 catch-all exception handlers with specific exception types

  - ``mqtt_client.py``: Uses ``AwsCrtError``, ``AuthenticationError``, ``TokenRefreshError``, ``RuntimeError``, ``ValueError``, ``TypeError``, ``AttributeError``
  - ``mqtt_reconnection.py``: Uses ``AwsCrtError``, ``RuntimeError``, ``ValueError``, ``TypeError``
  - ``mqtt_connection.py``: Uses ``AwsCrtError``, ``RuntimeError``, ``ValueError``
  - ``mqtt_subscriptions.py``: Uses ``AwsCrtError``, ``RuntimeError``, ``TypeError``, ``AttributeError``, ``KeyError``, ``ValueError``
  - ``mqtt_periodic.py``: Uses ``AwsCrtError``, ``RuntimeError``
  - ``events.py``: Retains ``Exception`` for user callbacks (documented as legitimate use case)
  - Added exception handling guidelines to ``.github/copilot-instructions.md``

- **Code Quality**: Multiple readability and safety improvements

  - Simplified nested conditions by extracting to local variables
  - Added ``hasattr()`` checks before accessing ``AwsCrtError.name`` attribute
  - Optimized ``resubscribe_all()`` to break after first failure per topic (reduces redundant error logs)
  - Fixed subscription failure tracking to use sets for unique topic counting
  - Improved code clarity with intermediate variables for complex boolean expressions

Fixed
-----

- **MQTT Reconnection**: Eliminated duplicate "Connection interrupted" log messages

  - Removed duplicate logging from ``mqtt_client.py`` (kept in ``mqtt_reconnection.py``)

Version 3.1.4 (2025-10-26)
==========================

Fixed
-----

- **MQTT Reconnection**: Fixed MQTT reconnection failures due to expired AWS credentials

  - Added AWS credential expiration tracking (``_aws_expires_at`` field in ``AuthTokens``)
  - Added ``are_aws_credentials_expired`` property to check AWS credential validity
  - Modified ``ensure_valid_token()`` to prioritize AWS credential expiration check
  - Triggers full re-authentication (not just token refresh) when AWS credentials expire
  - Preserves AWS credential expiration timestamps during token refresh
  - Prevents reconnection failures when connection interrupts after AWS credentials expire but before JWT tokens expire
  - Resolves AWS_ERROR_HTTP_WEBSOCKET_UPGRADE_FAILURE errors during reconnection attempts
  - Improved test coverage for auth module from 31% to 60%

Version 3.1.3 (2025-10-24)
==========================

Fixed
-----

- **MQTT Reconnection**: Improved MQTT reconnection reliability with active reconnection

  - **Breaking Internal Change**: ``MqttReconnectionHandler`` now requires ``reconnect_func`` parameter (not Optional)
  - Implemented active reconnection that always recreates MQTT connection on interruption
  - Removed unreliable passive fallback to AWS IoT SDK automatic reconnection
  - Added automatic connection state checking during reconnection attempts
  - Now emits ``reconnection_failed`` event when max reconnection attempts are exhausted
  - Improved error handling and logging during reconnection process
  - Better recovery from WebSocket connection interruptions (AWS_ERROR_MQTT_UNEXPECTED_HANGUP)
  - Resolves issues where connection would fail to recover after network interruptions
  - Note: Public API unchanged - ``NavienMqttClient`` continues to work as before
  - Compatible with existing auto-recovery examples (``auto_recovery_example.py``, ``simple_auto_recovery.py``)

Version 3.1.2 (2025-01-23)
==========================

Fixed
-----

- **Authentication**: Fixed 401 authentication errors with automatic token refresh

  - Add automatic token refresh on 401 Unauthorized responses in API client
  - Preserve AWS credentials when refreshing tokens (required for MQTT)
  - Save refreshed tokens to cache after successful API calls
  - Add retry logic to prevent infinite retry loops
  - Validate refresh_token exists before attempting refresh
  - Use specific exception types (TokenRefreshError, AuthenticationError) in error handling
  - Prevents masking unexpected errors during token refresh
  - Resolves 'API request failed: 401' error when using cached tokens

Version 3.1.1 (2025-01-22)
==========================

Fixed
-----

- **MQTT Client**: Fixed connection interrupted callback signature for AWS SDK

  - Updated callback to match latest AWS IoT SDK signature: ``(connection, error, **kwargs)``
  - Fixed type annotations in ``MqttConnection`` for proper type checking
  - Resolves mypy type checking errors and keeps AWS SDK compatibility
  - Fixed E501 line length linting issue in connection interruption handler

Version 3.0.0 (Unreleased)
==========================

**Breaking Changes**

- **REMOVED**: ``OperationMode`` enum has been removed

  - This enum was deprecated in v2.0.0 and has now been fully removed
  - Use ``DhwOperationSetting`` for user-configured mode preferences (values 1-6)
  - Use ``CurrentOperationMode`` for real-time operational states (values 0, 32, 64, 96)
  - Migration was supported throughout the v2.x series

- **REMOVED**: Migration helper functions and deprecation infrastructure

  - Removed ``migrate_operation_mode_usage()`` function
  - Removed ``enable_deprecation_warnings()`` function
  - Removed migration documentation files (MIGRATION.md, BREAKING_CHANGES_V3.md)
  - All functionality available through ``DhwOperationSetting`` and ``CurrentOperationMode``

Version 2.0.0 (Unreleased)
==========================

**Breaking Changes (Planned for v3.0.0)**

- **DEPRECATION**: ``OperationMode`` enum is deprecated and will be removed in v3.0.0


  - Use ``DhwOperationSetting`` for user-configured mode preferences (values 1-6)
  - Use ``CurrentOperationMode`` for real-time operational states (values 0, 32, 64, 96)
  - See ``MIGRATION.md`` for detailed migration guide

Added
-----

- **Enhanced Type Safety**: Split ``OperationMode`` into semantically distinct enums

  - ``DhwOperationSetting``: User-configured mode preferences (HEAT_PUMP, ELECTRIC, ENERGY_SAVER, HIGH_DEMAND, VACATION, POWER_OFF)
  - ``CurrentOperationMode``: Real-time operational states (STANDBY, HEAT_PUMP_MODE, HYBRID_EFFICIENCY_MODE, HYBRID_BOOST_MODE)
  - Prevents accidental comparison of user preferences with real-time states
  - Better IDE support with more specific enum types

- **Migration Support**: Tools for migration

  - ``migrate_operation_mode_usage()`` helper function with programmatic guidance
  - ``MIGRATION.md`` with step-by-step migration instructions
  - Value mappings and common usage pattern examples
  - Backward compatibility preservation during transition

- **Documentation Updates**: Updated all documentation to reflect new enum structure

  - ``DEVICE_STATUS_FIELDS.rst`` updated with new enum types
  - Code examples use new enums with proper imports
  - Clear distinction between configuration vs real-time status

Changed
-------

- **DeviceStatus Model**: Updated to use specific enum types

  - ``operationMode`` field now uses ``CurrentOperationMode`` type
  - ``dhwOperationSetting`` field now uses ``DhwOperationSetting`` type
  - Maintains backward compatibility through value preservation

- **Example Scripts**: Updated to demonstrate new enum usage

  - ``event_emitter_demo.py`` updated to use ``CurrentOperationMode``
  - Fixed incorrect enum references (HEAT_PUMP_ONLY → HEAT_PUMP_MODE)
  - All examples remain functional with new type system

Deprecated
----------

- **OperationMode enum**: Will be removed in v3.0.0

  - All functionality preserved for backward compatibility
  - Migration guide available in ``MIGRATION.md``
  - Helper function ``migrate_operation_mode_usage()`` provides guidance
  - Original enum remains available during transition period

Version 1.2.2 (2025-10-17)
==========================

Fixed
-----

- Release version 1.2.2

Version 0.2 (Unreleased)
========================

Added
-----

- **Local/CI Linting Synchronization**: Tooling for consistent linting results

  - Multiple sync methods: tox (recommended), direct scripts, pre-commit hooks, Makefile commands
  - CI-identical scripts: ``scripts/lint.py`` and ``scripts/format.py`` mirror ``tox -e lint`` and ``tox -e format``
  - Pre-commit hooks configuration for automatic checking
  - Documentation: ``LINTING_SETUP.md``, ``DEVELOPMENT.md``, ``FIX_LINTING.md``
  - Makefile commands: ``make ci-lint``, ``make ci-format``, ``make ci-check``
  - Standardized ruff configuration across all environments
  - Eliminates "passes locally but fails in CI" issues
  - Cross-platform support (Linux, macOS, Windows, containers)

  - All MQTT operations (connect, disconnect, subscribe, unsubscribe, publish) use ``asyncio.wrap_future()`` to convert AWS SDK Futures to asyncio Futures
  - Eliminates "blocking I/O detected" warnings in Home Assistant and other async applications
  - Fully compatible with async event loops without blocking other operations
  - More efficient than executor-based approaches (no thread pool usage)
  - No API changes required - existing code works without modification
  - Maintains full performance and reliability of the underlying AWS IoT SDK
  - Safe for use in Home Assistant custom integrations and other async applications
  - Updated documentation with non-blocking implementation details

- **Event Emitter Pattern (Phase 1)**: Event-driven architecture for device state changes

  - ``EventEmitter`` base class with multiple listeners per event
  - Async and sync handler support
  - Priority-based execution order (higher priority executes first)
  - One-time listeners with ``once()`` method
  - Dynamic listener management with ``on()``, ``off()``, ``remove_all_listeners()``
  - Event statistics tracking (``listener_count()``, ``event_count()``)
  - ``wait_for()`` pattern for waiting on specific events
  - Thread-safe event emission from MQTT callback threads
  - Automatic state change detection for device monitoring
  - 11 events emitted automatically: ``status_received``, ``feature_received``, ``temperature_changed``, ``mode_changed``, ``power_changed``, ``heating_started``, ``heating_stopped``, ``error_detected``, ``error_cleared``, ``connection_interrupted``, ``connection_resumed``
  - NavienMqttClient now inherits from EventEmitter
  - Full backward compatibility with existing callback API
  - 19 unit tests with 93% code coverage
  - Example: ``event_emitter_demo.py``
  - Documentation: ``EVENT_EMITTER.rst``, ``EVENT_QUICK_REFERENCE.rst``, ``EVENT_ARCHITECTURE.rst``

- **Authentication**: Simplified constructor-based authentication

  - ``NavienAuthClient`` now requires ``user_id`` and ``password`` in constructor
  - Automatic authentication when entering async context manager
  - No need to call ``sign_in()`` manually
  - Breaking change: credentials are now required parameters
  - Updated all 18 example files to use new pattern
  - Updated all documentation with new authentication examples

- **MQTT Command Queue**: Automatic command queuing when disconnected

  - Commands sent while disconnected are automatically queued
  - Queue processed in FIFO order when connection is restored
  - Configurable queue size (default: 100 commands)
  - Automatic oldest-command-dropping when queue is full
  - Enabled by default for reliability
  - ``queued_commands_count`` property for monitoring
  - ``clear_command_queue()`` method for manual management
  - Works with automatic reconnection
  - Example: ``command_queue_demo.py``
  - Documentation: ``COMMAND_QUEUE.rst``

- **MQTT Reconnection**: Automatic reconnection with exponential backoff

  - Automatic reconnection on connection interruption
  - Configurable exponential backoff (default: 1s, 2s, 4s, 8s, ... up to 120s)
  - Configurable max attempts (default: 10)
  - Connection state properties: ``is_reconnecting``, ``reconnect_attempts``
  - User callbacks for connection interruption and resumption events
  - Manual disconnect detection to prevent unwanted reconnection
  - ``MqttConnectionConfig`` with reconnection settings
  - Example: ``reconnection_demo.py``
  - Documentation: Added reconnection section to MQTT_CLIENT.rst

- **MQTT Client**: Complete implementation of real-time device communication

  - WebSocket MQTT connection to AWS IoT Core
  - Device subscription and message handling
  - Status request methods (device info, device status)
  - Control commands for device management
  - Topic pattern matching with wildcard support
  - Connection lifecycle management (connect, disconnect, reconnect)

- **Device Control**: Fully implemented and verified control commands

  - Power control (on/off) with correct command codes
  - DHW mode control (Heat Pump, Electric, Energy Saver, High Demand)
  - DHW temperature control with 20°F offset handling
  - App connection signaling
  - Helper method for display-value temperature control

- **Typed Callbacks**: 100% coverage of all MQTT response types

  - ``subscribe_device_status()`` - Automatic parsing of status messages into ``DeviceStatus`` objects
  - ``subscribe_device_feature()`` - Automatic parsing of feature messages into ``DeviceFeature`` objects
  - ``subscribe_energy_usage()`` - Automatic parsing of energy usage responses into ``EnergyUsageResponse`` objects
  - Type-safe callbacks with IDE autocomplete support
  - Error handling and logging
  - Example scripts demonstrating usage patterns

- **Energy Usage API (EMS)**: Historical energy consumption data

  - ``request_energy_usage()`` - Query daily energy usage for specified month(s)
  - ``EnergyUsageResponse`` dataclass with daily breakdown
  - ``EnergyUsageTotal`` with percentage calculations
  - ``MonthlyEnergyData`` with per-day access methods
  - ``EnergyUsageData`` for individual day/month metrics
  - Heat pump vs. electric element usage tracking
  - Operating time statistics (hours)
  - Energy consumption data (Watt-hours)
  - Efficiency percentage calculations

- **Data Models**: Type-safe models

  - ``DeviceStatus`` dataclass with 125 sensor and operational fields
  - ``DeviceFeature`` dataclass with 46 capability and configuration fields
  - ``EnergyUsageResponse`` dataclass for historical energy data
  - ``EnergyUsageTotal`` with aggregated statistics and percentages
  - ``MonthlyEnergyData`` with daily breakdown per month
  - ``EnergyUsageData`` for individual day/month metrics
  - ``OperationMode`` enum including STANDBY state (value 0)
  - ``TemperatureUnit`` enum (Celsius/Fahrenheit)
  - MQTT command structures
  - Authentication tokens and user info

- **API Client**: High-level REST API client

  - Device listing and information retrieval
  - Firmware information queries
  - Time-of-Use (TOU) schedule management
  - Push notification token management
  - Async context manager support
  - Automatic session management

- **Authentication**: AWS Cognito integration

  - Sign-in with email/password
  - Access token management
  - Token refresh functionality
  - AWS IoT credentials extraction for MQTT
  - Async context manager support

- **Documentation**: Complete protocol and API documentation

  - MQTT message format specifications
  - Energy usage query API documentation (EMS data)
  - API client usage guide
  - MQTT client usage guide
  - Typed callbacks implementation guide
  - Control command reference with verified command codes
  - Example scripts for common use cases
  - Troubleshooting guides
  - Complete energy data reference (ENERGY_DATA_SUMMARY.md)

- **Examples**: Production-ready example scripts

  - ``device_status_callback.py`` - Real-time status monitoring with typed callbacks
  - ``device_feature_callback.py`` - Device capabilities and firmware info
  - ``combined_callbacks.py`` - Both status and feature callbacks together
  - ``mqtt_client_example.py`` - Complete MQTT usage demonstration
  - ``energy_usage_example.py`` - Historical energy usage monitoring and analysis
  - ``reconnection_demo.py`` - MQTT automatic reconnection demonstration
  - ``auth_constructor_example.py`` - Simplified authentication pattern

Changed
-------

- **Breaking**: Python version requirement updated to 3.9+

  - Minimum Python version is now 3.9 (was 3.8)
  - Migrated to native type hints (PEP 585): ``dict[str, Any]`` instead of ``Dict[str, Any]``
  - Removed ``typing.Dict``, ``typing.List``, ``typing.Deque`` imports
  - Cleaner, more readable code with modern Python features
  - Added Python version classifiers (3.9-3.13) to setup.cfg
  - Updated ruff target-version to py39

- **Breaking**: ``NavienAuthClient`` constructor signature

  - Now requires ``user_id`` and ``password`` as first parameters
  - Old: ``NavienAuthClient()`` then ``await client.sign_in(email, password)``
  - New: ``NavienAuthClient(email, password)`` - authentication is automatic
  - Migration: Pass credentials to constructor instead of sign_in()
  - All 18 example files updated to new pattern
  - All documentation updated with new examples

- **Documentation**: Major updates across all files

  - Fixed all RST formatting issues (title underlines, tables)
  - Updated authentication examples in 8 documentation files
  - Fixed broken documentation links (local file paths)
  - Removed "Optional Feature" and "not required for basic operation" phrases
  - Fixed table rendering in DEVICE_STATUS_FIELDS.rst
  - Fixed JSON syntax in code examples
  - Added reconnection documentation
  - Added command queue documentation
  - Cleaned up backward compatibility references (new library)

Fixed
-----

- **Bug**: Thread-safe reconnection task creation from MQTT callbacks

  - Fixed ``RuntimeError: no running event loop`` when connection is interrupted
  - Fixed ``RuntimeWarning: coroutine '_reconnect_with_backoff' was never awaited``
  - Connection interruption callbacks run in separate threads without event loops
  - Implemented ``_start_reconnect_task()`` helper method to properly create reconnection tasks
  - Uses existing ``_schedule_coroutine()`` method for thread-safe task scheduling
  - Prevents crashes during automatic reconnection after connection interruptions
  - Reconnection tasks are awaited and executed

- **Bug**: Thread-safe event emission from MQTT callbacks

  - Fixed ``RuntimeError: no running event loop in thread 'Dummy-1'``
  - MQTT callbacks run in separate threads created by AWS IoT SDK
  - Implemented ``_schedule_coroutine()`` method for thread-safe scheduling
  - Event loop reference captured during ``connect()`` for cross-thread access
  - Uses ``asyncio.run_coroutine_threadsafe()`` for safe event emission
  - Prevents crashes when emitting events from MQTT message handlers
  - All event emissions now work correctly from any thread

- **Bug**: Incorrect method parameter passing in temperature control

  - Fixed ``set_dhw_temperature_display()`` calling ``set_dhw_temperature()`` with wrong parameters
  - Was passing individual parameters (``device_id``, ``device_type``, ``additional_value``)
  - Now correctly passes ``Device`` object as expected by method signature
  - Simplified implementation to just calculate offset and delegate to base method
  - Updated docstrings to match actual method signatures

- **Enhancement**: Anonymized MAC addresses in documentation

  - Replaced all occurrences of real MAC address (``04786332fca0``) with placeholder (``aabbccddeeff``)
  - Updated ``API_CLIENT.rst``, ``MQTT_CLIENT.rst``, ``MQTT_MESSAGES.rst``
  - Updated built HTML documentation files
  - Protects privacy in public documentation

- **Bug**: Device control command codes

  - Fixed incorrect command code usage causing unintended power-off
  - Power-off now uses command code ``33554433``
  - Power-on now uses command code ``33554434``
  - DHW mode control now uses command code ``33554437``
  - Discovered through network traffic analysis of official app

- **Bug**: MQTT topic pattern matching with wildcards

  - Fixed ``_topic_matches_pattern()`` to correctly handle ``#`` wildcard
  - Topics now match when message arrives on base topic (e.g., ``cmd/52/device/res``)
  - Topics also match subtopics (e.g., ``cmd/52/device/res/extra``)
  - Added length validation to prevent index out of bounds errors
  - Enables callbacks to receive messages correctly

- **Bug**: Missing ``OperationMode.STANDBY`` enum value

  - Added ``STANDBY = 0`` to ``OperationMode`` enum
  - Device reports mode 0 when tank is fully charged and no heating is needed
  - Added graceful fallback for unknown enum values
  - Prevents ``ValueError`` when parsing device status

- **Bug**: Insufficient topic subscriptions

  - Examples now subscribe to broader topic patterns
  - Subscribe to ``cmd/{device_type}/{device_topic}/#`` to catch all command messages
  - Subscribe to ``evt/{device_type}/{device_topic}/#`` to catch all event messages
  - All device responses are received

- **Enhancement**: Enum conversion with fallbacks

  - Added try/except blocks for all enum conversions in ``DeviceStatus.from_dict()``
  - Added try/except blocks for all enum conversions in ``DeviceFeature.from_dict()``
  - Unknown operation modes default to ``STANDBY``
  - Unknown temperature types default to ``FAHRENHEIT``
  - Prevents parsing failures from unexpected values

- **Documentation**: Updated MQTT_MESSAGES.rst with correct command codes and temperature offset

Verified
--------

- **Device Control**: Real-world testing with Navien NWP500 device

  - Successfully changed DHW mode from Heat Pump to Energy Saver
  - Successfully changed DHW mode from Energy Saver to High Demand
  - Successfully changed DHW temperature (discovered 20°F offset between message and display)
  - Commands confirmed to reach and control physical device
  - Documented in DEVICE_CONTROL_VERIFIED.md

Version 0.1
===========

- Initial Documentation
