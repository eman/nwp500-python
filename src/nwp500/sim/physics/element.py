"""The resistance elements' rules: what each mode does with them once
it is switched on, the modes' names, and where each element starts and
stops. The controller (``sim.controller``) runs these rules and the
stratified tank (``physics.stratified``) takes the elements' heat into
the layers at their heights; ``api.element_mode`` walks a stint. The
device behaviour is in ``docs/explanation/heating-elements.rst``:

- **High Demand.** The heat pump heats the tank as usual.  The upper
  element heats whenever the upper zone is more than the re-engage
  hysteresis below the setpoint, and stops when it reaches the setpoint
  (``he_upper_on`` and ``he_upper_off`` both sit at the setpoint in this
  mode).
- **Electric.** No heat pump.  The upper element runs first, to the
  setpoint; then the lower element, to the setpoint.  Never both at once
  (``docs/reference/protocol/device_status.rst``: "Elements do not
  operate simultaneously in Electric mode").  Every handover on record
  went upper then lower (four, two in device runs).  Which element a
  stint *starts* with is less settled: on one evening of the record the
  lower element ran alone twice with the upper zone 4-5 °F short, which
  the upper-first rule does not explain and this does not model.

- **Entry thresholds differ by mode**, and each is held at its own
  observed edge: Electric 0.54 °F below the setpoint, High Demand 0.72,
  Energy Saver 1.8.  Electric and High Demand handle ``he_upper_on``
  identically and their brackets overlap, so they plausibly share one,
  but High Demand has never been seen to run between 0.36 and 0.72, and
  assuming the smaller number would promise an element that mode has
  never been seen to run.

- **Energy Saver, on entry.** Switched on with the upper zone more than
  about 1.8 °F below the setpoint, the upper element comes on at once
  (device sweep).  The heat pump heats the tank, as in High Demand.

- **Where the element stops** (2026-10-02): at the setpoint in High
  Demand and Electric, but **1.62 °F short of it in Energy Saver**,
  measured at raw off-edges (``ElementParams``).  The element's run and
  energy end there; the heat still in transit lifts the zone on.
  Running Energy Saver's element to the setpoint over-stated its energy
  by +20 % on held-out events.

- **The dead time** (2026-10-02): the upper probe is held for 1.21 min
  after the upper element's on-edge, while the element already draws
  its power (``ElementParams.upper_dead_time_min``).

**Whether the mode can be reached at all is a separate question**: with
TOU enabled a mode write may not take
(``docs/explanation/heating-elements.rst``, *Writing the mode while a
TOU window is in force*).  ``api.element_mode`` reports it.

**Low confidence, by construction.**  Every parameter comes from a few
dozen element runs in history, and the device runs of 2026-09-20 have
checked some of them:

- element power 5,148 W fitted (90 % CI 5,104-5,176 over 168 element-
  minutes); the device metered **5,219 W** and **5,242 W** on two runs,
  both **above** the interval.  **Refitted 2026-10-02 and kept**: every
  metered upper-element stint of at least 90 s, its time-weighted power
  less the compressor's share where it co-ran (the held-out
  validation's method), gives a median **5,143 W, 90 % CI
  5,107-5,161** by day (95 stints on 57 days), which contains 5,148;
  the 16 with a minute or more of compressor-off metering give 5,192
  (5,114-5,211), and the 6 since the device runs 5,152 (4,858-5,215).
  Single runs above 5.2 kW are inside the stints' spread (IQR
  5,036-5,197);
- the entry thresholds (``ElementParams``), which are bracketed on
  both sides by the device and are the only parameters here that are.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, TypeIs

from nwp500.sim.params import ElementParams

ElementMode = Literal["HIGH_DEMAND", "ELECTRIC", "ENERGY_SAVER"]

#: A heater mode, by the short names the simulation uses.
HeaterMode = Literal["heat_pump", "energy_saver", "high_demand", "electric"]

#: Each heater mode's device name (``DhwOperationSetting``). The intent
#: simulation speaks the short names; this module keeps the device's.
#: Read-only, as all of the core's module state is.
DEVICE_MODE: Final[Mapping[HeaterMode, str]] = MappingProxyType(
    {
        "heat_pump": "HEAT_PUMP",
        "energy_saver": "ENERGY_SAVER",
        "high_demand": "HIGH_DEMAND",
        "electric": "ELECTRIC",
    }
)
HEATER_MODE: Final[Mapping[str, HeaterMode]] = MappingProxyType(
    {v: k for k, v in DEVICE_MODE.items()}
)


def is_heater_mode(name: str) -> TypeIs[HeaterMode]:
    """Whether ``name`` is one of the modes the model simulates
    (``DEVICE_MODE``)."""
    return name in DEVICE_MODE


#: Reasons every element-mode answer carries, so a consumer cannot
#: mistake it for the heat pump's confidence.
BASE_REASONS: tuple[str, ...] = ("element_model_small_n",)


def _start_bracket(mode: ElementMode, p: ElementParams) -> tuple[float, float]:
    """The band the device's own decision is known to sit in.

    A deficit inside it is on the edge of a threshold this model treats
    as a step, and no run has been made there.
    """
    if mode == "ENERGY_SAVER":
        return p.energy_saver_bracket_lower_f, p.energy_saver_entry_deficit_f
    if mode == "HIGH_DEMAND":
        return (
            p.high_demand_bracket_lower_f,
            p.high_demand_starts_below_setpoint_f,
        )
    return p.start_bracket_lower_f, p.upper_starts_below_setpoint_f


def _start_deficit(mode: ElementMode, p: ElementParams) -> float:
    """How far below the setpoint the element needs before it starts.

    Two different things wear the same name.  Electric and High Demand
    put ``he_upper_on`` at the setpoint, so this is a thermostat and the
    answer is ~0.  Energy Saver rests it at 104.9 °F and what history
    shows is an entry effect at about 5 °F.
    """
    if mode == "ENERGY_SAVER":
        return p.energy_saver_entry_deficit_f
    if mode == "HIGH_DEMAND":
        return p.high_demand_starts_below_setpoint_f
    return p.upper_starts_below_setpoint_f


def entry_deficit_f(mode: ElementMode, params: ElementParams) -> float:
    """How far below the setpoint the upper zone must be, when ``mode``
    takes effect, for its upper element to start (the device runs'
    edges; see ``ElementParams``)."""
    return _start_deficit(mode, params)


def entry_bracket_f(
    mode: ElementMode, params: ElementParams
) -> tuple[float, float]:
    """The deficits between which the device's own entry decision lies
    and no run has been made."""
    return _start_bracket(mode, params)


def upper_off_deficit_f(mode: ElementMode, params: ElementParams) -> float:
    """How far below the setpoint ``mode``'s upper element switches off:
    Energy Saver's measured off point, 0 (the setpoint) in the others
    (``ElementParams.energy_saver_upper_off_below_setpoint_f``)."""
    if mode == "ENERGY_SAVER":
        return params.energy_saver_upper_off_below_setpoint_f
    return 0.0
