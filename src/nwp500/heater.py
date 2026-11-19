"""The NWP500's description for a scheduler: what a plan for the heater
may carry, and the facts it is checked against.

- **The modes** (``MODES``): every operation mode the device takes, by
  the short name a plan uses, with its ``DhwOperationSetting`` code,
  the energy sources it heats with, and whether the simulation models
  it. Vacation and Power Off are listed with no sources and
  ``modelled`` false: a plan may carry them, and the simulation drops a
  write into either (``write_mode_not_modelled``).
- **The setpoint range** is the device's own, read from its features
  (``DeviceFeature.dhw_temperature_min_raw`` and ``_max_raw``), or
  104.9-149.9 °F, the NWP500's, without them. The device holds a
  setpoint in steps of half a degree Celsius (``SETPOINT_STEP``).
- **The commands** (``COMMAND_KEYS``) a plan may carry besides a mode
  and a setpoint, each with its keys and their types;
  ``COMMAND_RANGES`` gives the range of each whole-number key, and
  ``COMMAND_KEYS_ONLY_WITH`` the keys given only alongside another
  key's value.

``HeaterProfile`` holds these facts; ``device_profile`` builds it for a
device. ``nwp500.sim.profile.heater_profile`` builds the same profile
with the tank volume and the depletion threshold the simulation runs
by.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from nwp500.enums import DhwOperationSetting
from nwp500.temperature import HalfCelsius

#: The energy sources, in the order served.
SOURCES: tuple[str, ...] = ("compressor", "element")
#: An opaque label, for display and records only.
HEATER_LABEL = "nwp500"


@dataclass(frozen=True)
class ProfileMode:
    """One of the heater's operation modes."""

    #: The name a plan uses: the device's name in lower case
    #: (``heat_pump`` for ``HEAT_PUMP``).
    name: str
    #: Its ``DhwOperationSetting`` value, as the device and a record
    #: hold it.
    code: int
    #: The energy sources it heats with, in the order of ``SOURCES``;
    #: none for a mode that does not heat.
    sources: tuple[str, ...]
    #: Whether the simulation models it. A write into a mode it does
    #: not model is dropped from a walk (``write_mode_not_modelled``).
    modelled: bool


def _mode(
    setting: DhwOperationSetting,
    sources: tuple[str, ...],
    modelled: bool = True,
) -> ProfileMode:
    return ProfileMode(setting.name.lower(), int(setting), sources, modelled)


#: Every mode a plan may carry, in the order served. ``STANDBY`` is a
#: status the device reports and is never set, so it is not one.
MODES: tuple[ProfileMode, ...] = (
    _mode(DhwOperationSetting.HEAT_PUMP, ("compressor",)),
    _mode(DhwOperationSetting.ENERGY_SAVER, ("compressor", "element")),
    _mode(DhwOperationSetting.HIGH_DEMAND, ("compressor", "element")),
    _mode(DhwOperationSetting.ELECTRIC, ("element",)),
    _mode(DhwOperationSetting.VACATION, (), modelled=False),
    _mode(DhwOperationSetting.POWER_OFF, (), modelled=False),
)
#: The device's name for each mode's code (``1``: ``HEAT_PUMP``).
DEVICE_MODE_CODES: Mapping[int, str] = MappingProxyType(
    {m.code: DhwOperationSetting(m.code).name for m in MODES}
)
#: The mode the heater runs when nothing commands it otherwise.
DEFAULT_MODE = "heat_pump"
#: The mode a scheduler assists a recovery with. Sources do not identify
#: it: two modes use both.
ASSISTED_MODE = "energy_saver"

#: The NWP500's lowest setpoint, °F: the one a profile states for a
#: device whose features are not given.
SETPOINT_MIN_F = 104.9
#: The NWP500's highest setpoint, °F, as ``SETPOINT_MIN_F``.
SETPOINT_MAX_F = 149.9
#: The unit of the setpoint step: the device holds a setpoint in
#: degrees Celsius.
SETPOINT_STEP_UNIT = "C"
#: The settable setpoints: half degrees Celsius on this heater.
SETPOINT_STEP = 0.5

#: Vacation's day count, inclusive: the front panel allows 1 to 99.
VACATION_DAYS: tuple[int, int] = (1, 99)
#: Anti-Legionella's cycle period in days, inclusive.
ANTI_LEGIONELLA_PERIOD_DAYS: tuple[int, int] = (1, 30)

#: Each device command a plan may carry and its keys, with their types
#: (``int`` a whole number, never a boolean). Every key is required but
#: those in ``COMMAND_KEYS_ONLY_WITH``.
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
#: The inclusive range of each whole-number key in ``COMMAND_KEYS``.
COMMAND_RANGES: Mapping[str, Mapping[str, tuple[int, int]]] = MappingProxyType(
    {
        "vacation": MappingProxyType({"days": VACATION_DAYS}),
        "anti_legionella": MappingProxyType(
            {"period_days": ANTI_LEGIONELLA_PERIOD_DAYS}
        ),
    }
)
#: The keys given only with other keys at the values here, and left
#: out otherwise: ``anti_legionella``'s ``period_days`` comes only with
#: ``enabled: true``.
COMMAND_KEYS_ONLY_WITH: Mapping[str, Mapping[str, Mapping[str, Any]]] = (
    MappingProxyType(
        {
            "anti_legionella": MappingProxyType(
                {"period_days": MappingProxyType({"enabled": True})}
            )
        }
    )
)
#: The command names, in the order served.
COMMANDS: tuple[str, ...] = tuple(COMMAND_KEYS)
#: The digest's length, in hex characters: 64 bits.
_REVISION_HEX = 16
#: A key's type as a document names it.
_TYPE_NAMES: Mapping[type, str] = MappingProxyType(
    {int: "integer", bool: "boolean"}
)


def command_key_facts(command: str) -> dict[str, dict[str, Any]]:
    """``command``'s keys as a document states them: each key's
    ``type`` (``integer`` or ``boolean``), with ``min`` and ``max`` for
    a whole number and ``only_with`` for a key given only with others;
    empty for a command not in ``COMMAND_KEYS``."""
    ranges = COMMAND_RANGES.get(command, {})
    only_with = COMMAND_KEYS_ONLY_WITH.get(command, {})
    out: dict[str, dict[str, Any]] = {}
    for key, kind in COMMAND_KEYS.get(command, {}).items():
        fact: dict[str, Any] = {"type": _TYPE_NAMES[kind]}
        if key in ranges:
            fact["min"], fact["max"] = ranges[key]
        if key in only_with:
            fact["only_with"] = dict(only_with[key])
        out[key] = fact
    return out


class SetpointLimits(Protocol):
    """A device's setpoint range in half degrees Celsius, as
    ``DeviceFeature`` holds it."""

    @property
    def dhw_temperature_min_raw(self) -> int: ...

    @property
    def dhw_temperature_max_raw(self) -> int: ...


def setpoint_range_f(
    feature: SetpointLimits | None = None,
) -> tuple[float, float]:
    """The setpoint range, °F: the device's from its features, or
    ``SETPOINT_MIN_F`` to ``SETPOINT_MAX_F`` without them."""
    if feature is None:
        return SETPOINT_MIN_F, SETPOINT_MAX_F
    return (
        round(HalfCelsius(feature.dhw_temperature_min_raw).to_fahrenheit(), 2),
        round(HalfCelsius(feature.dhw_temperature_max_raw).to_fahrenheit(), 2),
    )


@dataclass(frozen=True)
class HeaterProfile:
    """The heater's facts (module docstring)."""

    heater: str
    default_mode: str
    assisted_mode: str | None
    #: Every mode, in the order served.
    modes: tuple[ProfileMode, ...]
    commands: tuple[str, ...]
    setpoint_min_f: float
    setpoint_max_f: float
    setpoint_step_unit: str
    setpoint_step: float
    #: The upper probe's reading at which readiness counts the tank
    #: depleted, °F; None in a profile built without the simulation.
    depletion_threshold_f: float | None = None
    #: The tank's volume, gallons, as the simulation's physics take it;
    #: None in a profile built without the simulation.
    tank_gal: float | None = None

    def facts(self) -> dict[str, Any]:
        """Every fact, as the revision digests them."""
        return {
            "heater": self.heater,
            "default_mode": self.default_mode,
            "assisted_mode": self.assisted_mode,
            "modes": [
                {
                    "name": m.name,
                    "code": m.code,
                    "sources": list(m.sources),
                    "modelled": m.modelled,
                }
                for m in self.modes
            ],
            "commands": list(self.commands),
            "command_keys": {c: command_key_facts(c) for c in self.commands},
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

    def document(self) -> dict[str, Any]:
        """The profile as a JSON-compatible document: :meth:`facts`
        and ``revision``."""
        return {**self.facts(), "revision": self.revision}

    @property
    def names(self) -> frozenset[str]:
        """Every mode's name."""
        return frozenset(m.name for m in self.modes)

    @property
    def modelled_names(self) -> frozenset[str]:
        """The names of the modes the simulation models."""
        return frozenset(m.name for m in self.modes if m.modelled)

    def mode(self, name: str) -> ProfileMode | None:
        """The mode of that name, or None for a name not listed."""
        for m in self.modes:
            if m.name == name:
                return m
        return None

    def sources(self, name: str) -> frozenset[str]:
        """The mode's sources; empty for a name not listed, or a mode
        that does not heat."""
        m = self.mode(name)
        return frozenset() if m is None else frozenset(m.sources)

    def name_of(self, device_mode: object) -> str | None:
        """The profile's name for a mode the heater reported, or None
        for one it does not list (``STANDBY``) or does not know. The
        mode may be the device's name (``HEAT_PUMP``, ...), a
        ``DhwOperationSetting`` member, or its value as a record holds it
        (``1``, ``1.0``)."""
        if device_mode is None or isinstance(device_mode, bool):
            return None
        if isinstance(device_mode, (int, float)):
            value = float(device_mode)
            if not value.is_integer():
                return None
            code = int(value)
            return next((m.name for m in self.modes if m.code == code), None)
        label = str(getattr(device_mode, "name", device_mode)).lower()
        return label if label in self.names else None

    def effective(
        self, name: str, reported: frozenset[str] | None
    ) -> bool | None:
        """Whether the heater's reported heat source shows mode
        ``name`` in effect. ``reported`` is the sources the heat source
        names; None or empty: it reports none, and the answer is None,
        as it is for a mode with no sources. True when every reported
        source is one the mode uses and, where the mode uses a source
        the default mode does not (an element, for each element mode
        here), that source is among them; else False. So a compressor
        alone never shows an element mode in effect."""
        if not reported:
            return None
        mode = self.sources(name)
        if not mode:
            return None
        beyond = mode - self.sources(self.default_mode)
        return reported <= mode and beyond <= reported


def device_profile(feature: SetpointLimits | None = None) -> HeaterProfile:
    """The profile of a device: its setpoint range from ``feature``
    (a ``DeviceFeature``), or the NWP500's 104.9-149.9 °F without one.
    The tank volume and the depletion threshold are the simulation's
    and are None here (``nwp500.sim.profile.heater_profile``)."""
    low, high = setpoint_range_f(feature)
    return HeaterProfile(
        heater=HEATER_LABEL,
        default_mode=DEFAULT_MODE,
        assisted_mode=ASSISTED_MODE,
        modes=MODES,
        commands=COMMANDS,
        setpoint_min_f=low,
        setpoint_max_f=high,
        setpoint_step_unit=SETPOINT_STEP_UNIT,
        setpoint_step=SETPOINT_STEP,
    )


def check(profile: HeaterProfile) -> None:
    """The profile's invariants, raised as ``ValueError``: non-empty
    modes with distinct names, each with sources from :data:`SOURCES`,
    non-empty for a modelled mode; ``default_mode`` and a non-null
    ``assisted_mode`` among the modelled modes; commands from
    :data:`COMMAND_KEYS`; and a setpoint range with its minimum below
    its maximum."""
    names = [m.name for m in profile.modes]
    if not names or len(set(names)) != len(names):
        raise ValueError(f"modes must be non-empty and distinct: {names}")
    for m in profile.modes:
        if not set(m.sources) <= set(SOURCES) or (m.modelled and not m.sources):
            raise ValueError(f"mode {m.name}: sources {m.sources}")
    modelled = profile.modelled_names
    if profile.default_mode not in modelled:
        raise ValueError(
            f"default_mode {profile.default_mode} not a modelled mode"
        )
    if profile.assisted_mode is not None and (
        profile.assisted_mode not in modelled
    ):
        raise ValueError(
            f"assisted_mode {profile.assisted_mode} not a modelled mode"
        )
    unknown = [c for c in profile.commands if c not in COMMAND_KEYS]
    if unknown:
        raise ValueError(f"commands not known: {unknown}")
    if not profile.setpoint_min_f < profile.setpoint_max_f:
        raise ValueError(
            f"setpoint range {profile.setpoint_min_f}-"
            f"{profile.setpoint_max_f} °F is empty"
        )
