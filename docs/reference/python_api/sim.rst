=========
Simulator
=========

The heater simulator, ``nwp500.sim``, and the adapters that
build its inputs from the library's models, ``nwp500.sim_adapters``.
:doc:`/explanation/simulator` explains the model, its inputs and its
accuracy; :doc:`/how-to/simulate-heater` shows how to use it, and
:doc:`/reference/simulator-inputs` lists every input.

Entry points
============

.. autofunction:: nwp500.sim.simulate

.. autofunction:: nwp500.sim.recovery

.. autofunction:: nwp500.sim.standby

.. autofunction:: nwp500.sim.readiness

.. autofunction:: nwp500.sim.time_to_ready

.. autofunction:: nwp500.sim.next_recovery

.. autofunction:: nwp500.sim.forecast

.. autofunction:: nwp500.sim.active_cycle

.. autofunction:: nwp500.sim.element_mode

.. autofunction:: nwp500.sim.default_params

.. autofunction:: nwp500.sim.full_tank_book


Scenario
========

.. autoclass:: nwp500.sim.Scenario
   :members:

.. autoclass:: nwp500.sim.HeaterState
   :members:

.. autoclass:: nwp500.sim.Settings
   :members:

.. autoclass:: nwp500.sim.History
   :members:

.. autoclass:: nwp500.sim.Schedules
   :members:

.. autoclass:: nwp500.sim.ReservationEntry
   :members:

.. autoclass:: nwp500.sim.TouPeriod
   :members:

.. autoclass:: nwp500.sim.Environment
   :members:

.. autoclass:: nwp500.sim.Loads
   :members:

.. autoclass:: nwp500.sim.Draw
   :members:

.. autoclass:: nwp500.sim.DrawWindow
   :members:

.. autoclass:: nwp500.sim.Commands
   :members:

.. autoclass:: nwp500.sim.Write
   :members:


Results
=======

.. autoclass:: nwp500.sim.SimulationResult
   :members:

.. autoclass:: nwp500.sim.RecoveryResult
   :members:

.. autoclass:: nwp500.sim.Trace
   :members:

.. autoclass:: nwp500.sim.Forecast
   :members:

.. autoclass:: nwp500.sim.ActiveCycle
   :members:

.. autoclass:: nwp500.sim.DrawWindowResult
   :members:

.. autoclass:: nwp500.sim.Deliverable
   :members:

.. autoclass:: nwp500.sim.Readiness
   :members:

.. autoclass:: nwp500.sim.BathReady
   :members:

.. autoclass:: nwp500.sim.ModeReady
   :members:

.. autoclass:: nwp500.sim.ShowersReady
   :members:

.. autoclass:: nwp500.sim.ElementModeResult
   :members:


Parameters
==========

.. autoclass:: nwp500.sim.HeaterParams
   :members:

.. automodule:: nwp500.sim.params
   :members: TankParams, LossParams, CompressorParams, PowerParams,
      ElementParams, DrawParams, ControllerParams, ReadinessParams,
      BookParams, Provenance, provenance_of, unit_of, params_to_document,
      params_from_document, unknown_fields, FITTED, MEASURED, DEFAULT,
      HEATER, INSTALLATION, UNFITTED_TERMS, INSTALLATION_TERMS,
      UA_REF_DELTA_T_F, UA_MIN_DELTA_T_F


Hot water and the heat book
===========================

.. automodule:: nwp500.sim.delivery
   :members: deliverable, booked_deliverable, delivery_temp_f,
      zone_delivery_f, delivery_along, depletion, draw_windows,
      draw_domain_judgement, EXAMPLE_EVIDENCE, with_example_evidence

.. automodule:: nwp500.sim.circulation
   :members: Circulation, CirculationDraws, CirculationLoss, merge_runs,
      run_draws, RUN_GAP

.. automodule:: nwp500.sim.location_air
   :members: LocationAirModel, SITE_LOCATION_AIR, project, fit,
      FittedLocationAir

.. automodule:: nwp500.sim.calibration
   :members: calibrate, Calibration, fit_standby, StandbyFit, StandbyWindow,
      fit_compressor, CompressorFit, split_recoveries, recovery_minutes,
      clean_draws, CleanDraw, crossing,
      demonstrated, frontier, capacity, held_out, fit_evidence,
      EvidenceFit, cold_lower_cap, RecordedBook, fit_book_terms, BookFit,
      fit_terms_l1, BOOK_TERMS, BOOK_TERM_BOUNDS,
      book_error_bands, book_error_btu, empty_point,
      zone_empty_point, withheld_btu, book_walk, long_draws,
      front_frame, fit_front, FrontFit, settle_tails, fit_front_settle,
      SettleFit, mixing_frame, fit_zone_mix, ZoneMixFit, MeasuredRun,
      measure_runs, run_heat_btu, fit_displaced_gal, recent_flow_gpm,
      flow_lookup, circulation_windows, CirculationWindow,
      fit_ungated_observability, element_stints, fit_element_lag, ElementLagFit,
      element_off_points, element_power, element_grid, element_runs,
      fit_element_rates, ElementRateFit, day_ci,
      energy_saver_off_deficit, upper_start_edge, fit_power,
      PowerFit, fit_power_scale, power_cycles, cop_cycles, CopCycle,
      fit_cop_scale, solve_cop_fit, solve_cop_scale, draw_free_withdrawn,
      metered_withdrawn, metered_lead,
      path_to_end, with_power, snapshots, recoveries, quiet_windows,
      busy_intervals, fit_window, fit_ua_law, fit_gap_tau, with_standby,
      fit_loss, LossFit, loss_windows, standby_ends, standby_error,
      walk_tau, gap_paths, gap_error,
      with_compressor, UA_SEARCH_BOUNDS, UA_EXPONENT_BOUNDS, DRAW_LEAD

.. automodule:: nwp500.sim.profile
   :members: HeaterProfile, heater_profile, check, COMMAND_KEYS

.. automodule:: nwp500.sim.draw_forecast
   :members: ForecastSlot, check_issue, covers, shifted, draw_profile,
      DrawProfile, ExpectedDraw, heater_draw_windows, ForecastWindow,
      draws_first, forecast_loads, shower_gal

.. automodule:: nwp500.sim.cold_supply
   :members: plateau_t_cold, ColdSupply, ColdSupplyParams, on_the_mains

.. automodule:: nwp500.sim.meter
   :members: flow_gpm

.. automodule:: nwp500.sim.record
   :members: Record, RecordedWrite, Recorded, RecordedStarts, corroborator

.. automodule:: nwp500.sim.attribution
   :members: attribute, Attributed, WRITE_EVIDENCE, LOWER_SLACK_F,
      UPPER_SLACK_F

.. automodule:: nwp500.sim.observed
   :members: observe, Observed, ModeInterval, SetpointInterval,
      SourceInterval, Start, Slot, Gap, count_starts, effective

.. automodule:: nwp500.sim.ready
   :members: assess, Recovery, TankNow, showers_ready_for, whole_showers

.. automodule:: nwp500.sim.book
   :members: Booked, BookedHeatLedger, SpanLoss, full_tank_book,
      full_tank, walk_booked, loss_ceiling_btu, BookedPath, Step,
      book_steps, house_gpm, step_heat_btu, inlet_now_f


The engine and the physics
==========================

The pieces the entry points are built from.

.. automodule:: nwp500.sim.engine
   :members: simulate, Simulation, SimulationError, Heater, Entry,
      HeatingInterval, PathPoint, Write, RawWrite, ModeWrite,
      ModeInterval, quantise, floor_minute, energy_by_slot,
      energy_by_source, DRAW_LEAD, HEATER_SETPOINT_MIN_F,
      HEATER_SETPOINT_MAX_F

.. automodule:: nwp500.sim.tank_physics
   :members: TankPhysics, Physics, Point, Coast, Heat, point_at,
      ambient_window_mean, REFINE_TOL_MINUTES

.. automodule:: nwp500.sim.heat_pump_recovery
   :members: physics_recovery, PhysicsRecovery, recovery, Recovery,
      RecoveryContext, ModelDuration, PHYSICS_TRUNCATED

.. automodule:: nwp500.sim.heating_trajectory
   :members: build_heating_trajectory, HeatingPoint, path_cop

.. automodule:: nwp500.sim.decay
   :members: project_decay, DecayProjection, AmbientSampler, Draw,
      Impulse, draw_step, partitions, threshold_crossing,
      compute_start_time

.. automodule:: nwp500.sim.tou_triggers
   :members: autonomous_start, heater_start, in_window, while_enabled,
      Trigger, LOWER_TRIGGER_HELD, UPPER_DEFICIT_F

.. automodule:: nwp500.sim.schedules
   :members: TouRule, tou_rules, tou_windows, rule_windows, Firing,
      reservation_firings, week_bit, month_bit, half_c_to_f, weekly_runs

.. automodule:: nwp500.sim.physics.compressor
   :members: predict_physics_detailed, predict_physics, PhysicsPath,
      PhysicsResult, MAX_MINUTES

.. automodule:: nwp500.sim.physics.refrigerant
   :members: sat_pressure, vapor_density, liquid_enthalpy,
      vapor_enthalpy, dew_point_f

.. automodule:: nwp500.sim.physics.tank
   :members: ua_at, bottom_loss_reach, bottom_loss_drop_f

.. automodule:: nwp500.sim.physics.element
   :members: mode_recovery, ModeRecovery, mode_plan, ModePlan,
      ElementInterval, entry_deficit_f, entry_bracket_f,
      upper_off_deficit_f, coast_f, upper_rise_f, is_heater_mode,
      DEVICE_MODE, HEATER_MODE

.. automodule:: nwp500.sim.physics.draw
   :members: delivery_temp_f, hot_fraction, draw_energy_btu,
      withdrawn_gal, gap_opened_f, lower_zone_drop_f, settled_lower_f,
      unsettled_after_f, DEFAULT_OBSERVABILITY, DEFAULT_INLET_TEMP_F,
      DEFAULT_TMV_DELIVERY_INTERCEPT_F, DEFAULT_TMV_DELIVERY_SLOPE,
      DEFAULT_GAP_OPEN_F_PER_GAL, DEFAULT_DOMAIN_T_UPPER_F,
      DEFAULT_DOMAIN_VOLUME_GAL, DEFAULT_LOWER_GATE_F,
      DEFAULT_POOL_F_PER_HOUR


Documents
=========

.. automodule:: nwp500.sim.codec
   :members:


Adapters
========

.. automodule:: nwp500.sim_adapters
   :members:


Live sources
============

.. automodule:: nwp500.sim_live
   :members: compose, Composed, Source, Given, HeaterReading,
      LiveHeaterSource, LiveScheduleSource, LiveReadError, read_status,
      read_feature, read_reservations, HeaterSource, ScheduleSource,
      EnvironmentSource, LoadSource, DEFAULT_TIMEOUT, overlay, Built,
      DEFAULT_HORIZON, DEFAULT_PARAMS_NOTE, zone_name


Recorded history
================

.. automodule:: nwp500.status_history
   :members:

.. automodule:: nwp500.sim_calibrate
   :members: calibrate, calibrate_changes, Calibrated, report, Term,
      fit_book, BookTermsFit, MIN_BOOK_PAIRS, MIN_RUN_PAIRS,
      score, Judged, HeldOut, GROUPS, air_unread_note,
      CalibrationInputError, DEFAULT_HUMIDITY_PCT,
      DEFAULT_BASE_NOTE, NO_AIR_NOTE


Home Assistant sources
======================

.. automodule:: nwp500.sim_home_assistant
   :members: HomeAssistantEnvironment, HomeAssistantClient, record_inputs,
      RecordInputs, INLET_LOOKBACK, Sources, Entities, sources_from, State, parse_state,
      parse_history, parse_outages, parse_states, History, history_for,
      parse_forecast, read_heater_history, HeaterEntities, HeaterHistory,
      HISTORY_WINDOW, to_w, to_wh,
      pump_runs, draw_spans, busy, covers_start, reports_after, percent,
      is_running_total, reports_from_total, TOTAL_STATE_CLASSES,
      fresh, to_f, to_gpm, to_gal, to_rpm, HomeAssistantError
