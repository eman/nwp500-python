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

.. autofunction:: nwp500.sim.recovery_as_of


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

.. autoclass:: nwp500.sim.CirculationRun
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
   :members: TankParams, LossParams, CompressorParams, MAP_REF_AIR_F,
      MAP_REF_WATER_F, ElementParams, DrawParams, ControllerParams,
      ReadinessParams, Provenance, provenance_of, unit_of,
      params_to_document, params_from_document, unknown_fields,
      PARAMS_SCHEMA, RETIRED_SCHEMAS, FITTED,
      MEASURED, DEFAULT, HEATER, INSTALLATION, UNFITTED_TERMS,
      INSTALLATION_TERMS, RETIRED_TERMS, CirculationParams

.. automodule:: nwp500.sim.defaults
   :members: site_example_params, with_valve, SITE_VALVE, NO_VALVE,
      RATED_GAL, RATING_INLET_F, SITE_CLIMATE


Extension points
================

.. automodule:: nwp500.sim.extensions
   :members: RecoveryModel

.. automodule:: nwp500.sim.api
   :members: counter_measures_to_setpoint, tou_marked, marked_windows,
      READY_HORIZON


Hot water and calibration
=========================

.. automodule:: nwp500.sim.delivery
   :members: deliverable, within_resolution, delivery_f, delivery_along,
      depletion, Depletion, draw_windows, draw_domain_judgement

.. automodule:: nwp500.sim.circulation
   :members: Circulation, merge_runs, RUN_GAP, cooled_share,
      displaced_gal

.. automodule:: nwp500.sim.location_air
   :members: LocationAirModel, SITE_LOCATION_AIR, project, fit,
      FittedLocationAir

.. automodule:: nwp500.sim.calibration
   :members: calibrate, Calibration, clean_draws, CleanDraw, crossing,
      demonstrated, MeasuredRun,
      measure_runs, run_heat_btu, fit_return, fit_displaced_gal,
      REST_OFFSET_BOUNDS, COOL_TAU_BOUNDS, MIN_TERM_INDEPENDENCE,
      recent_flow_gpm,
      flow_lookup, element_stints, fit_element_lag, ElementLagFit,
      element_off_points, element_power, element_grid, element_runs,
      fit_element_rates, ElementRateFit, day_ci,
      energy_saver_off_deficit, upper_start_edge, snapshots, recoveries, quiet_windows,
      busy_intervals, DRAW_LEAD,
      heat_pump_cycles, HeatPumpCycle, water_in_use

.. automodule:: nwp500.sim.heat_pump_fit
   :members: recovery_frame, start_holds, run_ons, RunOnFit, climb_heat,
      power_blocks, PHASES, CLIMB_HELD, MIXED_BELOW_F, MIXED_ABOVE_F,
      MIN_STRETCH_MINUTES, POWER_BLOCK_MINUTES, Evidence, evidence,
      Plane, fit_heat_map, fit_power_map, heat_map_error,
      power_map_error, fit_start_hold, start_hold_error, fit_overshoot,
      overshoot_error, violations, with_planes, HeatPumpFit,
      fit_heat_pump, with_heat_pump, MIN_HEAT_STRETCHES,
      MIN_POWER_BLOCKS, MIN_BAND_STARTS, MIN_RUN_ONS, CARNOT_SHARE,
      MIN_POWER_W, CHECK_POINTS

.. automodule:: nwp500.sim.history_frame
   :members: Interval, instants, on_intervals, merge, asof, floats, energy_wh

.. automodule:: nwp500.sim.profile
   :members: HeaterProfile, heater_profile, check, COMMAND_KEYS

.. automodule:: nwp500.sim.draw_forecast
   :members: ForecastSlot, check_issue, covers, shifted, draw_profile,
      DrawProfile, ExpectedDraw, heater_draw_windows, ForecastWindow,
      draws_first, forecast_loads, shower_gal

.. automodule:: nwp500.sim.cold_supply
   :members: plateau_t_cold, ColdSupply, ColdSupplyParams, mains_f,
      climate_of, MAINS_OFFSET_F, MAINS_REFERENCE_AIR_F,
      CLIMATE_MONTH_DAYS, CLIMATE_MEAN_MIN_F

.. automodule:: nwp500.sim.record
   :members: Record, RecordedWrite, Recorded, RecordedStarts, corroborator

.. automodule:: nwp500.sim.attribution
   :members: attribute, Attributed, WRITE_EVIDENCE, LOWER_SLACK_F,
      UPPER_SLACK_F

.. automodule:: nwp500.sim.observed
   :members: observe, Observed, ModeInterval, SetpointInterval,
      SourceInterval, Start, Slot, Gap, count_starts, effective

.. automodule:: nwp500.sim.ready
   :members: assess, Recovery, TankNow, ModeRun, MODES, showers_ready_for,
      whole_showers

.. automodule:: nwp500.sim.history
   :members: Step, house_gpm, drawn_gal, record, replay, REPLAY,
      FlowVolume, AMBIENT_DEFAULT_F


The engine and the physics
==========================

The pieces the entry points are built from.

.. automodule:: nwp500.sim.engine
   :members: simulate, Simulation, SimulationError, Heater, Entry,
      HeatingInterval, PathPoint, Write, RawWrite, ModeWrite,
      ModeInterval, quantise, floor_minute, energy_by_slot,
      energy_by_source, HEATER_SETPOINT_MIN_F,
      HEATER_SETPOINT_MAX_F

.. automodule:: nwp500.sim.controller
   :members:

.. automodule:: nwp500.sim.tank_physics
   :members: TankPhysics, Physics, TankState, Point, Stretch, Running,
      CompressorRun, ElementRun, Recovered, Delivered, Stop, point_at,
      ambient_window_mean, circulation_flows, RECOVERY_BOUND

.. automodule:: nwp500.sim.heat_pump_recovery
   :members: rate_scale, Scaled, PhysicsRecovery, RecoveryContext,
      ModelDuration, PHYSICS_TRUNCATED, RATE_SCALE_RANGE

.. automodule:: nwp500.sim.heating_trajectory
   :members: from_walk, HeatingPoint

.. automodule:: nwp500.sim.decay
   :members: AmbientSampler, Impulse, threshold_crossing,
      compute_start_time

.. automodule:: nwp500.sim.tou_triggers
   :members: autonomous_start, heater_start, in_window, while_enabled,
      Trigger, LOWER_TRIGGER_HELD, UPPER_DEFICIT_F, LOWER_HOLD_MODES,
      DROP_STARTS_MODE

.. automodule:: nwp500.sim.schedules
   :members: TouRule, tou_rules, tou_windows, rule_windows, Firing,
      reservation_firings, week_bit, month_bit, half_c_to_f, weekly_runs

.. automodule:: nwp500.sim.physics.heat_pump
   :members: heat_btu_h, power_w, cop, evaporator_btu_h, start_hold_min,
      carnot_cop, heat_air_outside, HEAT_MAP_OUT_OF_DOMAIN

.. automodule:: nwp500.sim.physics.stratified
   :members: TankState, Layout, layout, energy_btu, mix, lose, conduct,
      add_heat, condenser_water_f, condenser_heat, element_heat, flow,
      Flowed, draw, Drawn, deliverable_gal, observe, estimate,
      assimilate, walk, Walked, Books, Heating, Compressor, Element,
      Flowing, Delivered, IDLE_STEP, ACTIVE_STEP, CUT_RESOLUTION, NO_VALVE

.. automodule:: nwp500.sim.tank_fit
   :members: TankRecord, tank_record, replay, start_state, Coast, errors,
      rmse, event_rmse, fit, TankFit, TERMS, CONDENSER_TERMS, term_values,
      with_terms, ASSIMILATE_EVERY, MINUTE

.. automodule:: nwp500.sim.physics.element
   :members: mode_recovery, ModeRecovery, mode_plan, ModePlan,
      ElementInterval, entry_deficit_f, entry_bracket_f,
      upper_off_deficit_f, coast_f, upper_rise_f, is_heater_mode,
      DEVICE_MODE, HEATER_MODE

.. automodule:: nwp500.sim.physics.draw
   :members: delivery_temp_f, hot_fraction, withdrawn_gal,
      DEFAULT_INLET_TEMP_F, DEFAULT_TMV_DELIVERY_INTERCEPT_F,
      DEFAULT_TMV_DELIVERY_SLOPE, NO_VALVE_INTERCEPT_F, NO_VALVE_SLOPE


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
      DEFAULT_HORIZON, DEFAULT_PARAMS_NOTE, zone_name, heater_reading,
      live_schedules


Recorded history
================

.. automodule:: nwp500.status_history
   :members:

.. automodule:: nwp500.sim_calibrate
   :members: calibrate, calibrate_changes, Calibrated, TankCalibration,
      MIN_TANK_EVENTS, MIN_TANK_RECOVERIES, TANK_EVALUATIONS, prepare,
      prepare_changes, Prepared, report, Term, score, Judged, HeldOut, GROUPS, air_unread_note,
      CalibrationInputError, DEFAULT_HUMIDITY_PCT,
      DEFAULT_BASE_NOTE, NO_AIR_NOTE

.. automodule:: nwp500.sim_score
   :members: events, Events, Recovery, Window, DrawEvent, Delivery, score,
      Score, Stat, compare, Comparison, Change, holdout_start,
      params_digest, SCHEMA, score_layers, fit_layers, layer_coasts


Home Assistant sources
======================

.. automodule:: nwp500.sim_home_assistant
   :members: HomeAssistantEnvironment, HomeAssistantClient, fit_location_air,
      Run, inline, HomeAssistantTank, LayersAnswer, TANK_WINDOW,
      mains_plateau, known_runs,
      record_inputs,
      RecordInputs, INLET_LOOKBACK, PROBE_STEP, held, LOCATION_AIR_WINDOW,
      LOCATION_AIR_MIN_SPAN, LOCATION_AIR_MIN_R, RUN_SETTLE, Sources,
      Entities, sources_from, State, parse_state,
      parse_history, parse_units, parse_outages, parse_states, History,
      history_for,
      parse_forecast, parse_outdoor_history, read_heater_history, HeaterEntities, HeaterHistory,
      HISTORY_WINDOW, to_w, to_wh,
      pump_runs, demand_spans, busy, covers_start, percent,
      fresh, to_f, to_gpm, to_gal, to_rpm, HomeAssistantError
