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
- ``readiness(state, settings, params)``: how much hot water the tank
  can deliver now; ``time_to_ready(scenario, params)``: whether it can
  run a bath, when it can in each heating mode, and the showers it is
  ready for;
- ``element_mode(state, settings, params, mode=..., at=...)``: a
  recovery in an element mode;
- ``default_params(volume_code)``: the parameters of one NWP500-65,
  with the tank volume scaled for the 50 and 80 gal models.

``nwp500.sim_adapters`` builds a scenario's parts from the library's
models; ``sim.codec`` reads and writes scenarios as JSON documents.
"""

from nwp500.sim.api import (
    element_mode,
    next_recovery,
    readiness,
    recovery,
    simulate,
    standby,
    time_to_ready,
)
from nwp500.sim.book import Booked, full_tank_book
from nwp500.sim.defaults import default_params
from nwp500.sim.delivery import Deliverable, DrawWindowResult
from nwp500.sim.inputs import (
    Commands,
    Draw,
    DrawWindow,
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
from nwp500.sim.params import BookParams, HeaterParams, ReadinessParams
from nwp500.sim.ready import (
    BathReady,
    ModeReady,
    Readiness,
    ShowersReady,
)
from nwp500.sim.result import (
    ElementModeResult,
    RecoveryResult,
    SimulationResult,
    Trace,
)

__all__ = (
    "BathReady",
    "BookParams",
    "Booked",
    "Deliverable",
    "Draw",
    "DrawWindow",
    "DrawWindowResult",
    "ElementModeResult",
    "Environment",
    "HeaterParams",
    "HeaterState",
    "History",
    "Loads",
    "ModeReady",
    "Commands",
    "Readiness",
    "ReadinessParams",
    "RecoveryResult",
    "ReservationEntry",
    "Scenario",
    "Schedules",
    "Settings",
    "ShowersReady",
    "SimulationResult",
    "TouPeriod",
    "Trace",
    "Write",
    "default_params",
    "element_mode",
    "full_tank_book",
    "next_recovery",
    "readiness",
    "recovery",
    "simulate",
    "standby",
    "time_to_ready",
)
