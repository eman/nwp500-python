"""nwp500's heater simulator.

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
- ``element_mode(scenario, params, mode=...)``: a stint in an element
  mode, the scenario walked with the mode written at its start;
- ``carry_on(walks, tail, params)``: each walk's end walked on through
  one tail, so changes are weighed with what each leaves behind;
- ``default_params(volume_code)``: one NWP500-65's parameters with no
  mixing valve; ``site_example_params`` that installation whole, valve
  included (``with_valve`` sets one); the parameters of one NWP500-65,
  with the tank resized to the 50 and 80 gal models' (``defaults.sized``).

``nwp500.sim_adapters`` builds a scenario's parts from the library's
models; ``sim.codec`` reads and writes scenarios as JSON documents.
"""

from nwp500.sim.api import (
    active_cycle,
    element_mode,
    forecast,
    next_recovery,
    readiness,
    recovery,
    simulate,
    standby,
    time_to_ready,
)
from nwp500.sim.carry import SETTLED_F, Carried, carry_on
from nwp500.sim.defaults import (
    NO_VALVE,
    SITE_UNDILUTED_GPM,
    SITE_VALVE,
    default_params,
    site_example_params,
    with_valve,
)
from nwp500.sim.delivery import Deliverable, DrawWindowResult
from nwp500.sim.inputs import (
    CirculationRun,
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
from nwp500.sim.params import (
    CirculationParams,
    HeaterParams,
    ReadinessParams,
)
from nwp500.sim.ready import (
    BathReady,
    ModeReady,
    Readiness,
    ShowersReady,
    recovery_as_of,
)
from nwp500.sim.result import (
    ActiveCycle,
    ElementInterval,
    ElementModeResult,
    Forecast,
    RecoveryResult,
    SimulationResult,
    Trace,
)

__all__ = (
    "CirculationParams",
    "CirculationRun",
    "NO_VALVE",
    "SITE_UNDILUTED_GPM",
    "SITE_VALVE",
    "SETTLED_F",
    "BathReady",
    "Carried",
    "Deliverable",
    "Draw",
    "DrawWindow",
    "DrawWindowResult",
    "ElementInterval",
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
    "ActiveCycle",
    "Forecast",
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
    "carry_on",
    "default_params",
    "element_mode",
    "active_cycle",
    "forecast",
    "next_recovery",
    "readiness",
    "recovery",
    "simulate",
    "site_example_params",
    "standby",
    "recovery_as_of",
    "time_to_ready",
    "with_valve",
)
