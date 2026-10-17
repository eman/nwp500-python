"""nwp500's optional heater simulator.

Pure functions and value types, which a caller feeds values into: no
I/O, no wall clock and no module state. The package imports nothing
from the rest of ``nwp500``, and needs the ``sim`` extra (numpy,
pandas and scipy).

- ``simulate(scenario, params)``: walk a ``Scenario`` from its start to
  its end, and return a ``SimulationResult``.
- ``recovery(state, settings, environment, params, at=...)``: the first
  heating interval from an instant ("when will the tank be hot?").
- ``standby(state, environment, loads, params, start=..., until=...)``:
  the tank coasting with no heating.
- ``default_params(volume_code)``: the parameters of one NWP500-65,
  with the tank volume scaled for the 50 and 80 gal models.

``nwp500.sim_adapters`` builds a scenario's parts from the library's
models; ``sim.codec`` reads and writes scenarios as JSON documents.
"""

from nwp500.sim.api import recovery, simulate, standby
from nwp500.sim.defaults import default_params
from nwp500.sim.inputs import (
    Commands,
    Draw,
    Environment,
    HeaterState,
    History,
    Loads,
    ReservationEntry,
    Scenario,
    Schedules,
    Settings,
    TouPeriod,
    Write,
)
from nwp500.sim.params import HeaterParams
from nwp500.sim.result import RecoveryResult, SimulationResult, Trace

__all__ = (
    "Draw",
    "Environment",
    "HeaterParams",
    "HeaterState",
    "History",
    "Loads",
    "Commands",
    "RecoveryResult",
    "ReservationEntry",
    "Scenario",
    "Schedules",
    "Settings",
    "SimulationResult",
    "TouPeriod",
    "Trace",
    "Write",
    "default_params",
    "recovery",
    "simulate",
    "standby",
)
