"""The heater as the simulation knows it: what a scheduler may plan
with, stated as the rest of the simulation uses it, so a plan checked
against the profile and the simulation cannot disagree.

The device's facts (its modes, setpoint range and step, and commands)
are ``nwp500.heater``'s, re-exported here; the simulation takes its own
from there. ``heater_profile`` adds the two the simulation holds: the
depletion threshold readiness draws at, and the tank volume the physics
uses (``TankParams.volume_gal``).

``revision`` is a digest of every fact: it moves when, and only when,
one of them does, so a consumer re-reads the profile on a new revision.
"""

import dataclasses

from nwp500.heater import (
    ANTI_LEGIONELLA_PERIOD_DAYS,
    ASSISTED_MODE,
    COMMAND_KEYS,
    COMMAND_KEYS_ONLY_WITH,
    COMMAND_RANGES,
    COMMANDS,
    DEFAULT_MODE,
    DEVICE_MODE_CODES,
    HEATER_LABEL,
    MODES,
    SETPOINT_MAX_F,
    SETPOINT_MIN_F,
    SETPOINT_STEP,
    SETPOINT_STEP_UNIT,
    SOURCES,
    VACATION_DAYS,
    HeaterProfile,
    ProfileMode,
    SetpointLimits,
    check,
    command_key_facts,
    device_profile,
    setpoint_range_f,
)
from nwp500.sim.controller import COMPRESSOR_MODES, ELEMENT_MODES
from nwp500.sim.params import ReadinessParams, TankParams

__all__ = (
    "ANTI_LEGIONELLA_PERIOD_DAYS",
    "ASSISTED_MODE",
    "COMMANDS",
    "COMMAND_KEYS",
    "COMMAND_KEYS_ONLY_WITH",
    "COMMAND_RANGES",
    "DEFAULT_MODE",
    "DEVICE_MODE_CODES",
    "HEATER_LABEL",
    "MODES",
    "SETPOINT_MAX_F",
    "SETPOINT_MIN_F",
    "SETPOINT_STEP",
    "SETPOINT_STEP_UNIT",
    "SOURCES",
    "VACATION_DAYS",
    "HeaterProfile",
    "ProfileMode",
    "SetpointLimits",
    "check",
    "command_key_facts",
    "device_profile",
    "heater_profile",
    "mode_sources",
    "setpoint_range_f",
)


def mode_sources(name: str) -> frozenset[str]:
    """The sources a mode uses, as the engine runs it; none for a mode
    it does not model."""
    return frozenset(
        s
        for s, uses in (
            ("compressor", name in COMPRESSOR_MODES),
            ("element", name in ELEMENT_MODES),
        )
        if uses
    )


def heater_profile(
    tank: TankParams = TankParams(),
    line_f: float = ReadinessParams().line_f,
    *,
    feature: SetpointLimits | None = None,
) -> HeaterProfile:
    """The profile the simulation runs by: the device's
    (``nwp500.heater.device_profile``, its setpoint range from
    ``feature``, a ``DeviceFeature``, when given), with ``tank_gal``
    ``tank``'s volume, the one the physics use (pass
    ``HeaterParams.tank``), and ``depletion_threshold_f`` the line
    readiness draws at (pass ``HeaterParams.readiness.line_f``)."""
    return dataclasses.replace(
        device_profile(feature),
        depletion_threshold_f=line_f,
        tank_gal=tank.volume_gal,
    )
