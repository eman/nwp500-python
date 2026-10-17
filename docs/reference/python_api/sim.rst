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

.. automodule:: nwp500.sim.ready
   :members: assess, Recovery, TankNow, showers_ready_for, whole_showers

.. automodule:: nwp500.sim.book
   :members: Booked, BookedHeatLedger, SpanLoss, full_tank_book,
      full_tank, walk_booked, loss_ceiling_btu, BookedPath


Documents
=========

.. automodule:: nwp500.sim.codec
   :members:


Adapters
========

.. automodule:: nwp500.sim_adapters
   :members:
