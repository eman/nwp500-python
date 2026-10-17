=========
Simulator
=========

The optional heater simulator, ``nwp500.sim``, and the adapters that
build its inputs from the library's models, ``nwp500.sim_adapters``.
:doc:`/explanation/simulator` explains the model, its inputs and its
accuracy; :doc:`/how-to/simulate-heater` shows how to use it, and
:doc:`/reference/simulator-inputs` lists every input.

Install it with the ``sim`` extra:

.. code-block:: bash

   pip install nwp500-python[sim]


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
      params_from_document


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
      fit_compressor, CompressorFit, clean_draws, CleanDraw, crossing,
      demonstrated, frontier, capacity, held_out, fit_evidence,
      EvidenceFit, cold_lower_cap, RecordedBook, fit_book_terms, BookFit,
      book_error_bands, book_error_btu, empty_point,
      zone_empty_point, withheld_btu, book_walk, long_draws,
      front_frame, fit_front, FrontFit, settle_tails, fit_front_settle,
      SettleFit, mixing_frame, fit_zone_mix, ZoneMixFit, MeasuredRun,
      measure_runs, run_heat_btu, fit_displaced_gal, recent_flow_gpm,
      flow_lookup, fit_power,
      PowerFit, fit_power_scale,
      fit_cop_scale, solve_cop_fit, solve_cop_scale, draw_free_withdrawn,
      metered_withdrawn, metered_lead,
      path_to_end, with_power, snapshots, recoveries, quiet_windows,
      busy_intervals, fit_window, fit_ua_law, fit_gap_tau, with_standby,
      with_compressor

.. automodule:: nwp500.sim.draw_forecast
   :members: ForecastSlot, check_issue, draw_profile, DrawProfile,
      ExpectedDraw, heater_draw_windows, ForecastWindow, draws_first,
      forecast_loads

.. automodule:: nwp500.sim.cold_supply
   :members: plateau_t_cold, ColdSupply, ColdSupplyParams, on_the_mains

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


Documents
=========

.. automodule:: nwp500.sim.codec
   :members:


Adapters
========

.. automodule:: nwp500.sim_adapters
   :members:
