"""The heater as the simulation knows it: what a scheduler may plan
with, stated as the rest of the simulation uses it, so a plan checked
against the profile and the simulation cannot disagree.

- **The modes** are the ones the simulation runs (``DEVICE_MODE``),
  each with the energy it may use as the engine uses it
  (``controller.COMPRESSOR_MODES``, ``controller.ELEMENT_MODES``).
- **The setpoint range** is the one a scenario is checked against
  (``engine.HEATER_SETPOINT_MIN_F`` to ``_MAX_F``), and the step the one
  it rounds to (``engine.SETPOINT_RESOLUTION_C``).
- **The depletion threshold** is readiness's, and the tank volume the
  one the physics uses (``TankParams.volume_gal``).
- ``default_mode`` is the mode the heater runs when nothing commands it
  otherwise; ``assisted_mode`` the mode a scheduler assists a recovery
  with. Sources do not identify it: two modes here use both.
- ``commands`` are the device commands a plan may carry besides a mode
  and a setpoint, with their keys.

``revision`` is a digest of every fact: it moves when, and only when,
one of them does, so a consumer re-reads the profile on a new revision.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from nwp500.sim.book import DEPLETION_THRESHOLD_F
from nwp500.sim.controller import ENERGY_SAVER, HEAT_PUMP
from nwp500.sim.engine import (
    HEATER_SETPOINT_MAX_F,
    HEATER_SETPOINT_MIN_F,
    SETPOINT_RESOLUTION_C,
)
from nwp500.sim.observed import mode_sources
from nwp500.sim.params import TankParams
from nwp500.sim.physics.element import DEVICE_MODE, HEATER_MODE

#: The energy sources, in the order served.
SOURCES: tuple[str, ...] = ("compressor", "element")
#: An opaque label, for display and records only.
HEATER_LABEL = "nwp500"
#: Each device command a plan may carry and its keys, with their types
#: (``int`` a whole number, never a boolean). Every key is required but
#: ``anti_legionella``'s ``period_days``, given with ``enabled: true``
#: only.
COMMAND_KEYS: Mapping[str, Mapping[str, type]] = MappingProxyType(
    {
        "vacation": MappingProxyType({"days": int}),
        "power": MappingProxyType({"on": bool}),
        "anti_legionella": MappingProxyType(
            {"enabled": bool, "period_days": int}
        ),
        "tou": MappingProxyType({"enabled": bool}),
        "demand_response": MappingProxyType({"enabled": bool}),
    }
)
#: The command names, in the order served.
COMMANDS: tuple[str, ...] = tuple(COMMAND_KEYS)
#: The settable setpoints: half degrees Celsius on this heater, the step
#: the simulation rounds a setpoint to.
SETPOINT_STEP_UNIT = "C"
SETPOINT_STEP = SETPOINT_RESOLUTION_C
#: The digest's length, in hex characters: 64 bits.
_REVISION_HEX = 16


@dataclass(frozen=True)
class HeaterProfile:
    """The heater's facts (module docstring)."""

    heater: str
    default_mode: str
    assisted_mode: str | None
    #: ``(name, sources)`` per mode, in the order served.
    modes: tuple[tuple[str, tuple[str, ...]], ...]
    commands: tuple[str, ...]
    setpoint_min_f: float
    setpoint_max_f: float
    setpoint_step_unit: str
    setpoint_step: float
    depletion_threshold_f: float
    tank_gal: float

    def facts(self) -> dict[str, Any]:
        """Every fact, as the revision digests them."""
        return {
            "heater": self.heater,
            "default_mode": self.default_mode,
            "assisted_mode": self.assisted_mode,
            "modes": [
                {"name": name, "sources": list(sources)}
                for name, sources in self.modes
            ],
            "commands": list(self.commands),
            "setpoint_f": {
                "min": self.setpoint_min_f,
                "max": self.setpoint_max_f,
            },
            "setpoint_step": {
                "unit": self.setpoint_step_unit,
                "step": self.setpoint_step,
            },
            "depletion_threshold_f": self.depletion_threshold_f,
            "tank_gal": self.tank_gal,
        }

    @property
    def revision(self) -> str:
        """A digest of :meth:`facts` as canonical JSON (sorted keys, no
        whitespace), so equal facts give equal revisions in any
        process."""
        text = json.dumps(self.facts(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()[:_REVISION_HEX]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(name for name, _ in self.modes)

    def sources(self, name: str) -> frozenset[str]:
        """The mode's sources; empty for a name not listed."""
        for n, sources in self.modes:
            if n == name:
                return frozenset(sources)
        return frozenset()

    def name_of(self, device_mode: object) -> str | None:
        """The profile's name for a mode the heater reported (the
        device's ``HEAT_PUMP``, ...), or None for one it does not list
        (``VACATION``, ``POWER_OFF``)."""
        if device_mode is None:
            return None
        name = HEATER_MODE.get(str(device_mode).upper())
        return name if name in self.names else None


def heater_profile(
    tank: TankParams = TankParams(),
    line_f: float = DEPLETION_THRESHOLD_F,
) -> HeaterProfile:
    """The profile the simulation runs by; ``tank_gal`` is ``tank``'s
    volume, the one the physics use (pass ``HeaterParams.tank``), and
    ``depletion_threshold_f`` the line readiness draws at (pass
    ``HeaterParams.readiness.line_f``)."""
    return HeaterProfile(
        heater=HEATER_LABEL,
        default_mode=HEAT_PUMP,
        assisted_mode=ENERGY_SAVER,
        modes=tuple(
            (name, tuple(s for s in SOURCES if s in mode_sources(name)))
            for name in DEVICE_MODE
        ),
        commands=COMMANDS,
        setpoint_min_f=HEATER_SETPOINT_MIN_F,
        setpoint_max_f=HEATER_SETPOINT_MAX_F,
        setpoint_step_unit=SETPOINT_STEP_UNIT,
        setpoint_step=SETPOINT_STEP,
        depletion_threshold_f=line_f,
        tank_gal=tank.volume_gal,
    )


def check(profile: HeaterProfile) -> None:
    """The profile's invariants, raised as ``ValueError``: non-empty
    modes with distinct names, each with a non-empty subset of
    :data:`SOURCES`; ``default_mode`` and a non-null ``assisted_mode``
    among them."""
    names = [n for n, _ in profile.modes]
    if not names or len(set(names)) != len(names):
        raise ValueError(f"modes must be non-empty and distinct: {names}")
    for name, sources in profile.modes:
        if not sources or not set(sources) <= set(SOURCES):
            raise ValueError(f"mode {name}: sources {sources}")
    if profile.default_mode not in names:
        raise ValueError(f"default_mode {profile.default_mode} not a mode")
    if profile.assisted_mode is not None and profile.assisted_mode not in names:
        raise ValueError(f"assisted_mode {profile.assisted_mode} not a mode")
