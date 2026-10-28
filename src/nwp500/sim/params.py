"""The heater's parameters: one frozen value, composed of parts.

``HeaterParams`` gathers every number the simulation runs on, so the
physics take values rather than reaching for a caller's configuration
or a module constant:

- ``TankParams``: the tank's size, and the thermal masses derived
  from it;
- ``LossParams``: the jacket's UA law;
- ``CompressorParams``: the heat pump's performance map, the heat it
  puts in and the power it draws, and the hold at its start;
- ``ElementParams``: the resistance elements;
- ``DrawParams``: a draw through the tank, delivered through the
  mixing valve or flowing from it, and its inflow;
- ``ControllerParams``: the numbers of the firmware's rules for when
  the compressor starts and stops (``sim/controller.py``).
- ``ReadinessParams``: what counts as hot water at the tap, and the
  volumes readiness is judged against (``sim.delivery``).

Every field carries its ``Provenance`` and the unit it is in, in the
dataclass field's ``metadata`` (``provenance_of``, ``unit_of``).

The caller builds a ``HeaterParams``, e.g. from a calibration and its
own configuration; the core never sees either. The parts the
simulation reads (tank, loss, compressor, element, controller) have
defaults. The rest have none: a ``HeaterParams`` is built by the
caller, e.g. from a calibration.

A ``HeaterParams`` is also a document (``params_to_document``,
``params_from_document``): plain JSON values, one object per part, so a
consumer reads the parameters without the model that was trained with
them. Floats are kept as they are, so a document read back is the
value written.

This module imports only the standard library and two leaves of the
core: ``units``, and ``cold_supply`` for the mains by the day (it
imports ``circulation`` alone); none imports it back.
"""

import math
from collections.abc import Mapping
from dataclasses import MISSING, dataclass, field, fields
from datetime import date, timedelta
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType, NoneType, UnionType
from typing import Any, cast, get_args, get_origin, get_type_hints

from nwp500.sim.cold_supply import CLIMATE_MEAN_MIN_F, mains_f
from nwp500.sim.units import WATER_BTU_PER_GAL_F


class Provenance(StrEnum):
    """Where a parameter's value comes from.

    - ``measured``: read off this heater, by a device run or from its
      record;
    - ``fitted``: estimated by a fit, at a retrain or once by a script;
    - ``scaled``: a measured or fitted value carried to another tank
      size or voltage (none yet);
    - ``default``: assumed, or taken from a specification or rating,
      and not measured on this heater.
    """

    MEASURED = "measured"
    FITTED = "fitted"
    SCALED = "scaled"
    DEFAULT = "default"


MEASURED = Provenance.MEASURED
FITTED = Provenance.FITTED
SCALED = Provenance.SCALED
DEFAULT = Provenance.DEFAULT


class Scope(StrEnum):
    """What a parameter describes.

    - ``heater``: the NWP500 itself (its tank, compressor, elements and
      firmware), measured on one unit and expected to hold for the model;
    - ``installation``: where it is installed and how it is used: the
      plumbing (a mixing valve, circulation), the mains, the
      household's draws, and anything fitted only through them. A
      default of this scope describes one installation, not yours.
    """

    HEATER = "heater"
    INSTALLATION = "installation"


HEATER = Scope.HEATER
INSTALLATION = Scope.INSTALLATION

# The frames fitted values carry (``note_of``).
_LOCATION_AIR = (
    "fitted against a sensor of the air where the heater stands, not the "
    "heater's own ambient reading; circulation runs screened out"
)
_IN_RECOVERY = (
    "fitted with one installation's draws and circulation runs inside its "
    "recoveries, against a location-air sensor; durations without them "
    "come out a little long"
)
_VALVE_LINE = (
    "a mixing valve's delivery line; intercept 0 and slope 1 is no valve, "
    "delivery at the tank's own temperature"
)
_MAINS = (
    "one installation's September mains, the median plateau of a "
    "probe's long draws over 2026-09-19..26; the defaults for another "
    "installation take the rating test's 58 degF"
)
_CLIMATE = (
    "one installation's outdoor air, the monthly means of a weather "
    "station's readings over 2025-11..2026-10"
)


def _p(
    provenance: Provenance,
    unit: str,
    scope: Scope = HEATER,
    note: str | None = None,
) -> dict[str, Any]:
    """A field's metadata: its provenance, its unit, its scope, and a
    note on the frame it was fitted in, when that matters."""
    out: dict[str, Any] = {
        "provenance": provenance,
        "unit": unit,
        "scope": scope,
    }
    if note is not None:
        out["note"] = note
    return out


def _field(part: object, name: str) -> Any:
    for f in fields(part):  # type: ignore[arg-type]
        if f.name == name:
            return f
    raise KeyError(f"{type(part).__name__} has no field {name!r}")


def provenance_of(part: object, name: str) -> Provenance:
    """The provenance of ``part``'s field ``name``.

    ``part`` is a parameter dataclass, or an instance of one.
    """
    return Provenance(_field(part, name).metadata["provenance"])


def unit_of(part: object, name: str) -> str:
    """The unit of ``part``'s field ``name``."""
    return str(_field(part, name).metadata["unit"])


def scope_of(part: object, name: str) -> Scope:
    """Whether ``part``'s field ``name`` describes the heater or the
    installation (``Scope``)."""
    return Scope(_field(part, name).metadata["scope"])


def note_of(part: object, name: str) -> str | None:
    """The frame ``part``'s field ``name`` was fitted in, when it
    matters: a sensor it was fitted against, hardware it was fitted
    through."""
    note = _field(part, name).metadata.get("note")
    return None if note is None else str(note)


#: The two-zone gap's time constant on this product, h, which the
#: water column's conductance prior closes (``TankParams.
#: conductance_btu_hr_f``).
_GAP_PRIOR_H = 60.0


@dataclass(frozen=True, kw_only=True)
class TankParams:
    """The tank: its size, and how the stratified tank lays it out
    (``physics.stratified.layout``).

    The thermal mass is derived, not stored, so a tank of another size
    cannot carry the 63.2-gal tank's mass.
    """

    #: Rated storage, gallons: the NWP500-65's actual 63.2 (marketed as
    #: 65).
    volume_gal: float = field(default=63.2, metadata=_p(DEFAULT, "gal"))
    #: The stratified tank's layers (``physics.stratified``), equal in
    #: volume, the bottom first: HPWHsim's twelve.
    layers: int = field(default=12, metadata=_p(DEFAULT, "1"))
    #: Where the upper and the lower probes read, as a share of the
    #: volume from the bottom. Priors, from where the record's draws
    #: first move each probe; fitted on the clean draws.
    upper_probe_height: float = field(
        default=0.85, metadata=_p(DEFAULT, "fraction")
    )
    lower_probe_height: float = field(
        default=0.2, metadata=_p(DEFAULT, "fraction")
    )
    #: How far along the column each probe feels the water, gal: it
    #: reads the layers weighted by ``exp(-distance / spread)`` from its
    #: height, a probe in a well on the wall rather than a point in the
    #: water. 0.0 reads the point.
    upper_probe_spread_gal: float = field(
        default=0.0, metadata=_p(DEFAULT, "gal")
    )
    lower_probe_spread_gal: float = field(
        default=0.0, metadata=_p(DEFAULT, "gal")
    )
    #: What the lower probe reads above the water it feels, °F: the
    #: probes' disagreement in a mixed tank.
    lower_probe_offset_f: float = field(default=0.0, metadata=_p(DEFAULT, "°F"))
    #: Where the elements heat, the same way: the upper element with
    #: 17.5 gal of the 63.2 above it, the lower near the bottom. Priors;
    #: fitted on the element runs.
    upper_element_height: float = field(
        default=0.72, metadata=_p(DEFAULT, "fraction")
    )
    lower_element_height: float = field(
        default=0.15, metadata=_p(DEFAULT, "fraction")
    )
    #: The span of the tank the condenser coil wraps, from the bottom.
    #: A prior; fitted on stratified climbs.
    condenser_span: tuple[float, float] = field(
        default=(0.0, 0.45), metadata=_p(DEFAULT, "fraction")
    )
    #: The water an inflow mixes with as it enters at the bottom, gal.
    inlet_mix_gal: float = field(default=9.0, metadata=_p(DEFAULT, "gal"))
    #: The water column's axial conductance, end to end, BTU/hr·°F:
    #: conduction and the slow mixing between the layers. The prior
    #: closes a two-zone gap on 60 h (the column's slowest mode,
    #: ``mass / (π² · τ)``), 10.7 between each pair of twelve layers.
    conductance_btu_hr_f: float = field(
        default=63.2 * WATER_BTU_PER_GAL_F / (math.pi**2 * _GAP_PRIOR_H),
        metadata=_p(DEFAULT, "BTU/hr/°F"),
    )

    def __post_init__(self) -> None:
        # A document carries the span as a list.
        low, high = self.condenser_span
        object.__setattr__(self, "condenser_span", (float(low), float(high)))

    @property
    def thermal_mass_btu_f(self) -> float:
        """Full-tank thermal mass, BTU/°F (≈ 527 at 63.2 gal)."""
        return self.volume_gal * WATER_BTU_PER_GAL_F


@dataclass(frozen=True, kw_only=True)
class LossParams:
    """The stratified tank's standby loss (``physics.stratified.lose``):
    each layer relaxes toward the air through its share of the sides'
    UA, the bottom layer through the bottom's too and the top layer
    through the top's."""

    #: Its loss through its sides, shared equally by the layers,
    #: BTU/hr·°F.
    ua_side_btu_hr_f: float = field(
        default=5.0, metadata=_p(FITTED, "BTU/hr/°F", note=_LOCATION_AIR)
    )
    #: Its loss through its bottom, from the bottom layer, BTU/hr·°F.
    ua_bottom_btu_hr_f: float = field(
        default=1.8, metadata=_p(FITTED, "BTU/hr/°F", note=_LOCATION_AIR)
    )
    #: Its loss through its top, from the top layer: the head, the
    #: fittings and the pipes, BTU/hr·°F.
    ua_top_btu_hr_f: float = field(
        default=0.0, metadata=_p(FITTED, "BTU/hr/°F", note=_LOCATION_AIR)
    )


#: The air and the water the heat pump's maps are quoted at, °F
#: (``physics.heat_pump``).
MAP_REF_AIR_F = 65.0
MAP_REF_WATER_F = 120.0

_HEAT_MAP = (
    "fitted on one installation's draw-free climbs with the tank mixed "
    "(38 stretches, water 115-143 °F, air 61-89 °F), against a "
    "location-air sensor"
)
_POWER_MAP = (
    "fitted on one installation's metered 10-minute blocks of its "
    "recoveries' climbs (lower tank 74-148 °F, air 46-89 °F)"
)


#: ``CompressorParams``' domains, each (low, high) °F.
DOMAINS = (
    "heat_domain_air_f",
    "heat_domain_water_f",
    "power_domain_air_f",
    "power_domain_water_f",
)


@dataclass(frozen=True, kw_only=True)
class CompressorParams:
    """The heat pump as a performance map (``physics.heat_pump``): the
    heat it puts into the tank and the electricity it draws, each a
    plane in the air at the heater and the lower tank's water, and the
    hold at its start.

    The heat is what the tank gains plus its standby loss: the
    condenser's output. The heat taken from the air is the heat less
    the electricity (``heat_pump.evaporator_btu_h``), so the cycle
    conserves energy by construction. The maps are read with the air
    and the water held to the span each was fitted on
    (``heat_domain_*``, ``power_domain_*``): a plane is not carried past
    the record it was fitted on.

    Defaults: one NWP500-65's record, 2025-12-28 to 2026-10-26
    (``heat_pump_fit``, ``docs/explanation/recovery-speed.rst``).
    """

    #: The heat into the tank at ``MAP_REF_AIR_F`` air and
    #: ``MAP_REF_WATER_F`` water, BTU/h, and how it moves per °F of
    #: air, of water, and of both together.
    heat_btu_h: float = field(
        default=4499.4, metadata=_p(FITTED, "BTU/hr", note=_HEAT_MAP)
    )
    heat_btu_h_per_air_f: float = field(
        default=55.5, metadata=_p(FITTED, "BTU/hr/°F", note=_HEAT_MAP)
    )
    heat_btu_h_per_water_f: float = field(
        default=-15.95, metadata=_p(FITTED, "BTU/hr/°F", note=_HEAT_MAP)
    )
    heat_btu_h_per_air_water_f: float = field(
        default=0.0, metadata=_p(DEFAULT, "BTU/hr/°F²")
    )
    #: The electricity it draws at the same point, W, and its slopes.
    #: The meter's 10-minute blocks fit it to 13 W RMS; the air moves it
    #: 0.2 W per °F.
    power_w: float = field(
        default=401.7, metadata=_p(FITTED, "W", note=_POWER_MAP)
    )
    power_w_per_air_f: float = field(
        default=0.21, metadata=_p(FITTED, "W/°F", note=_POWER_MAP)
    )
    power_w_per_water_f: float = field(
        default=2.85, metadata=_p(FITTED, "W/°F", note=_POWER_MAP)
    )
    power_w_per_air_water_f: float = field(
        default=0.0, metadata=_p(DEFAULT, "W/°F²")
    )
    #: The air and the water each map is read at are held to these, °F:
    #: the span of the evidence it was fitted on, to the whole degree.
    heat_domain_air_f: tuple[float, float] = field(
        default=(61.0, 89.0), metadata=_p(FITTED, "°F", note=_HEAT_MAP)
    )
    heat_domain_water_f: tuple[float, float] = field(
        default=(114.0, 144.0), metadata=_p(FITTED, "°F", note=_HEAT_MAP)
    )
    power_domain_air_f: tuple[float, float] = field(
        default=(45.0, 90.0), metadata=_p(FITTED, "°F", note=_POWER_MAP)
    )
    power_domain_water_f: tuple[float, float] = field(
        default=(73.0, 148.0), metadata=_p(FITTED, "°F", note=_POWER_MAP)
    )
    #: The hold at a start, minutes, by how long the compressor was off:
    #: ``start_hold_min[i]`` from ``start_hold_after_min[i - 1]``
    #: minutes off (the first from 0), and the last for a stop not
    #: known. On the record's 84 starts with no water in use and the
    #: time off known, the medians under 15 min, 15-60 min, 1-3 h,
    #: 3-12 h and over 12 h off.
    start_hold_after_min: tuple[float, ...] = field(
        default=(15.0, 60.0, 180.0, 720.0), metadata=_p(DEFAULT, "min")
    )
    start_hold_min: tuple[float, ...] = field(
        default=(0.0, 5.0, 10.0, 18.0, 22.0), metadata=_p(FITTED, "min")
    )

    def __post_init__(self) -> None:
        # A document carries the ranges and the bands as lists.
        for name in DOMAINS:
            low, high = getattr(self, name)
            object.__setattr__(self, name, (float(low), float(high)))
            if not low < high:
                raise ValueError(f"{name} is not (low, high)")
        for name in ("start_hold_after_min", "start_hold_min"):
            object.__setattr__(
                self, name, tuple(float(v) for v in getattr(self, name))
            )
        if len(self.start_hold_min) != len(self.start_hold_after_min) + 1:
            raise ValueError(
                "start_hold_min needs one more value than start_hold_after_min"
            )
        edges = self.start_hold_after_min
        if any(b <= a for a, b in pairwise(edges)) or (
            edges and edges[0] <= 0.0
        ):
            raise ValueError("start_hold_after_min is not positive, ascending")
        if any(v < 0.0 for v in self.start_hold_min):
            raise ValueError("start_hold_min is negative")


@dataclass(frozen=True, kw_only=True)
class DrawParams:
    """A draw through the tank as an installation carries it: its
    mixing valve (``physics.draw``), its inlet, and the range its draws
    were seen over."""

    #: The mixing valve's delivery line: intercept + slope × T_upper,
    #: never above the tank. Intercept 0 and slope 1 is no valve.
    delivery_intercept_f: float = field(
        metadata=_p(FITTED, "°F", INSTALLATION, _VALVE_LINE)
    )
    delivery_slope: float = field(
        metadata=_p(FITTED, "1", INSTALLATION, _VALVE_LINE)
    )
    #: The cold inlet's temperature, °F, all year, when ``climate_f``
    #: does not place the mains by the day.
    inlet_temp_f: float = field(metadata=_p(FITTED, "°F", INSTALLATION, _MAINS))
    #: Whether ``inlet_temp_f`` was read from the inlet probe.
    inlet_from_probe: bool = field(metadata=_p(MEASURED, "flag", INSTALLATION))
    #: The range the record's draws spanned: the upper probe before a
    #: draw, °F (508 episodes spanning 122.2-147.9; the delivery line
    #: was measured only over 123.8-139.5, so the top of the band
    #: already extrapolates it), and a draw's own volume, gallons. A
    #: walk with a draw outside either says ``draw_out_of_domain``.
    #: None skips that range.
    domain_upper_f: tuple[float, float] | None = field(
        default=(122.2, 147.9), metadata=_p(MEASURED, "°F", INSTALLATION)
    )
    domain_volume_gal: tuple[float, float] | None = field(
        default=(1.0, 41.6), metadata=_p(MEASURED, "gal", INSTALLATION)
    )
    #: The household flow that is a draw, gal/min: a meter's reading
    #: under it is its noise (``history.drawn_gal``).
    draw_gpm: float = field(
        default=0.3, metadata=_p(DEFAULT, "gal/min", INSTALLATION)
    )
    #: The installation's climate, which places the mains by the day
    #: (``cold_supply.mains_f``): the year's mean outdoor air and its
    #: warmest monthly mean less its coldest, °F
    #: (``cold_supply.climate_of``). None: the mains are
    #: ``inlet_temp_f`` all year.
    climate_f: tuple[float, float] | None = field(
        default=None, metadata=_p(MEASURED, "°F", INSTALLATION, _CLIMATE)
    )

    def __post_init__(self) -> None:
        # A document carries the ranges as lists.
        for name in ("domain_upper_f", "domain_volume_gal", "climate_f"):
            v = getattr(self, name)
            if v is not None:
                low, high = v
                object.__setattr__(self, name, (float(low), float(high)))
        if self.climate_f is not None:
            mean, swing = self.climate_f
            if not (math.isfinite(mean) and math.isfinite(swing)):
                raise ValueError("climate_f is not a number")
            if swing < 0.0:
                raise ValueError("climate_f's swing is negative")
            if mean < CLIMATE_MEAN_MIN_F:
                # Under it the correlation's seasons invert.
                raise ValueError(
                    f"climate_f's mean is under {CLIMATE_MEAN_MIN_F} °F"
                )

    def mains_on(self, day: date) -> float:
        """The mains on ``day``, °F: the climate's (``climate_f``,
        ``cold_supply.mains_f``) when given, else ``inlet_temp_f``."""
        if self.climate_f is None:
            return self.inlet_temp_f
        return mains_f(*self.climate_f, day)

    def out_of_domain(self, upper_f: float, volume_gal: float) -> bool:
        """Whether a draw of ``volume_gal`` (its own volume, never a
        rate times a mean) from an upper probe at ``upper_f`` lies
        outside the range the record's draws spanned; both bounds are
        inclusive."""
        for value, bounds in (
            (upper_f, self.domain_upper_f),
            (volume_gal, self.domain_volume_gal),
        ):
            if bounds is not None and not bounds[0] <= value <= bounds[1]:
                return True
        return False


_ENVELOPE = (
    "the user's manual (3.13.1 Heat Pump Operation Prevention); the "
    "elements' takeover outside it (3.13.4) is not seen on the record"
)


@dataclass(frozen=True, kw_only=True)
class ControllerParams:
    """The firmware's rules' numbers: when the compressor starts and
    stops (``sim/controller.py``). The element's thresholds are in
    ``ElementParams``.

    What a sustained setpoint write does, on the device's record (to
    2026-09-27 00:00 UTC: 291 writes held two minutes or more, in
    heat-pump mode, since
    2025-12-28; the call for heat 90 s after the write, and the
    compressor over ten minutes). The record grows, so each count is as
    of that instant:

    - compressor off, outside a TOU window: it started when the write
      left the upper zone short of the new setpoint, 118 of 120, and 1
      of 14 when it did not (six of them device runs on 2026-09-24 and
      25, none of which started it). *Updated 2026-10-03 after a
      device test, to 2026-10-03 21:30 UTC:* 301 writes; short of it,
      120 of 122 (the test's closing entry, 8.3 °F short, among them:
      the compressor 31.6 s after the setpoint landed); not short, 1
      of 16, which splits by direction. Lowerings: 0 of 15 (the test's
      hold-off entry, 120.2 °F with the upper zone at 137.1, among them;
      it held for 4 h), so a lowering is projected as no start
      unflagged. Raises: 1 of 1 (2026-05-01, the lower zone 19.8 °F
      short), so a raise left at or above the upper zone is still
      projected as no start, flagged;
    - compressor off, inside a window: it started when the write left
      the upper zone more than ``window_write_starts_f`` short, 16 of
      17, and 3 of 15 when 0-4 °F short. Device runs bracket that band:
      on 2026-09-25 a write 1.8 °F short (139.1 °F, held six minutes, so
      counted) called for no heat and started nothing; on 2026-09-26
      one 2.7 °F short (140.9 °F, held six minutes) started nothing, and
      the run's restore to 141.8 °F, 3.8 °F short, started it 38 s
      after; on 2026-09-24 one 3.1 °F short started it 36 s after the
      write, but held its 142.7 °F for 33 s, so the sustained count
      leaves it out. (A count over every write, stepped sequences
      included, put that band near 70 %: a later, larger step was
      taking the credit.)
    - compressor on, setpoint lowered: the heater stops calling for
      heat, and the compressor stops, when the new setpoint is at or
      below the upper zone. Scored on the call for heat and a
      ten-minute window, the compressor stopped 19 times in 25 so,
      against 10 in 44 with the setpoint left above the upper zone. Two
      device runs on 2026-09-23 both stopped, 6 s and 150 s after the
      write, the call ending at once (the two-minute count had scored
      the 150 s one as "kept heating").

    A reservation entry's setpoint is such a write (measured on this
    heater's entry tests, 2026-09).

    What a sustained **mode** write does with the compressor off, on the
    device's record (to 2026-09-25 12:00 UTC: 91 writes held two
    minutes or more since 2025-12-28, outside the restart lockout, the
    compressor scored over two minutes as an earlier count scored its
    46 of 81). Outside a TOU
    window, by the mode the write leaves and the one it names:

    - **the lower zone** ``mode_write_lower_starts_f`` or more short of
      the setpoint started it into every compressor mode, whatever the
      upper zone: 19 of 19 out of a heating mode (the most short with no
      start was 2.70 °F). This is what a return to ``heat_pump`` after
      an element run turns on: the element heats the upper zone, so the
      lower is the one short. Out of ``electric`` into ``heat_pump``, 5
      of 5 so (three of them no more than 2 °F short in the upper zone,
      two at or above the setpoint there), and 0 of 2 with the lower
      zone above it. Out of ``heat_pump`` it needs the upper zone short
      too: Energy Saver landing at a window's close with the upper zone
      18.7 °F above the setpoint and the lower 20.9 °F under it started
      nothing in 9 h 56 min (2026-09-21 04:00 UTC);
    - into ``heat_pump``, the upper zone more than
      ``mode_write_starts_f`` short: 7 of 7 out of ``energy_saver``.
      With neither, 1 of 10 started;
    - into ``energy_saver`` or ``high_demand``, the upper zone short at
      all: 7 of 7 into ``energy_saver`` out of ``heat_pump``, from
      ``energy_saver_write_seen_f`` to 13.9 °F short, and 2 of 2 into
      ``high_demand``; nothing nearer the setpoint was scored. Out of
      ``electric`` they started whatever the tank: 4 of 4, each with the
      upper zone at or above the setpoint
      (``controller.ELECTRIC_EXIT``);
    - into ``electric``: never the compressor (0 of 2 here, 0 of 6 in
      the earlier count), an element instead (2 of 2);
    - an entry repeating the heater's mode and setpoint: nothing (0 of
      4, in a device test).

    Out of ``vacation`` or ``power_off`` the heater starts afresh (38 of
    39 started); the simulation holds no rule for those writes. Inside
    a TOU window a mode is held (``controller``); the heater's own drop
    to ``heat_pump`` there is judged as a setpoint write is.
    """

    #: A setpoint write that leaves the upper zone below the new
    #: setpoint starts the compressor about this long after it: a median
    #: 30 s over the record's starts more than ten minutes after a stop.
    write_start_lag_s: float = field(default=30.0, metadata=_p(MEASURED, "s"))
    #: After it stops, the compressor does not start again for this
    #: long, though the heater calls for heat at once. Two restarts in
    #: a device run on 2026-09-23 came 5 min 28 s and 5 min 31 s after
    #: the stop; on the record, starts within ten minutes of
    #: a stop waited a median 86 s and up to 329 s. The 2026-09-21
    #: restore that took 2 min 34 s is the same lockout, part-served.
    restart_lockout_s: float = field(default=330.0, metadata=_p(MEASURED, "s"))
    #: Inside a TOU window a write starts the compressor only when it
    #: leaves the upper zone more than this short (the record above).
    window_write_starts_f: float = field(
        default=4.0, metadata=_p(MEASURED, "°F")
    )
    #: A mode write into ``heat_pump`` starts it with the upper zone
    #: more than this short.
    mode_write_starts_f: float = field(default=2.0, metadata=_p(MEASURED, "°F"))
    #: A mode write into a compressor mode starts it with the lower zone
    #: this much or more short: out of an element mode whatever the
    #: upper zone, otherwise with the upper zone short too.
    mode_write_lower_starts_f: float = field(
        default=3.6, metadata=_p(MEASURED, "°F")
    )
    #: The least deficit a write into ``energy_saver`` was seen to start
    #: the compressor at.
    energy_saver_write_seen_f: float = field(
        default=1.44, metadata=_p(MEASURED, "°F")
    )
    #: How far short of its target a recovery ending in a TOU window
    #: stops, judged at its end: the device references its deficit
    #: counter 2 °C under the setpoint while the window is in force.
    #: The probe reads 1.9 °C (3.42 °F) short at the stop, one 0.1 °C
    #: step past the threshold; a recovery reaching its setpoint ends
    #: with the probe 0.5-2 °F over it in the same way. The simulator
    #: stops a capped one at the threshold, and one outside a window
    #: ``hp_stop_overshoot_f`` past its target.
    #: Judging at the start caught 17 of 59 capped cycles against 43 at
    #: the end (``docs/explanation/tou-recovery-cap.rst``).
    tou_cap_f: float = field(default=3.6, metadata=_p(MEASURED, "°F"))
    #: Outside a TOU window the compressor runs on past its target
    #: until the lower probe reads this far over it, °F. On 31
    #: draw-free recoveries (2025-12-28 to 2026-10-26) the median
    #: overshoot at the stop, after a median 10 min run-on; leaving each
    #: out of its own median, the stop it places is 2.4 min off against
    #: 3.3 for a fixed run-on (``heat_pump_fit.run_ons``).
    hp_stop_overshoot_f: float = field(default=0.9, metadata=_p(FITTED, "°F"))
    #: The heat pump runs only with the air around the heater and the
    #: water in the tank inside these, °F (low, high: the low included,
    #: the high not); outside them it does not run and the elements heat
    #: the tank (the user's manual, §3.13.1 and §3.13.4). The water is
    #: read at the lower zone, the one the condenser heats. Not seen on
    #: the record: its air ran 45.9-89.3 °F.
    hp_air_range_f: tuple[float, float] = field(
        default=(41.0, 113.0), metadata=_p(DEFAULT, "°F", note=_ENVELOPE)
    )
    hp_water_range_f: tuple[float, float] = field(
        default=(50.0, 149.0), metadata=_p(DEFAULT, "°F", note=_ENVELOPE)
    )

    def __post_init__(self) -> None:
        if self.hp_stop_overshoot_f < 0.0:
            raise ValueError("hp_stop_overshoot_f is negative")
        for name in ("hp_air_range_f", "hp_water_range_f"):
            low, high = getattr(self, name)
            object.__setattr__(self, name, (float(low), float(high)))
            if not low < high:
                raise ValueError(f"{name} is not (low, high)")

    @property
    def write_start_lag(self) -> timedelta:
        """``write_start_lag_s`` as a span."""
        return timedelta(seconds=self.write_start_lag_s)

    @property
    def restart_lockout(self) -> timedelta:
        """``restart_lockout_s`` as a span."""
        return timedelta(seconds=self.restart_lockout_s)


@dataclass(frozen=True)
class ElementParams:
    """Fitted element terms; see ``physics.element``'s module docstring
    for provenance."""

    element_w: float = field(default=5148.0, metadata=_p(FITTED, "W"))
    #: How far below the setpoint the upper zone must be **on entry to
    #: the mode** before the element starts, **in Electric**.  Not a
    #: thermostat; see the module docstring.
    #:
    #: Electric ran the element at 0.54 and 0.72 °F short and stayed
    #: off 1.08 °F *above* the setpoint, so 0.54 is the top of
    #: what it was ever seen declining below.  Nothing was observed
    #: between 0 and 0.54.
    upper_starts_below_setpoint_f: float = field(
        default=0.54, metadata=_p(MEASURED, "°F")
    )

    #: The same for **High Demand**, whose own bracket is wider:
    #: off at 0.36 °F short, on at 1.26, then on at 0.90 and **0.72**
    #: (two device runs on 2026-09-21).
    #: 0.72 rather than Electric's 0.54 because High Demand was never
    #: seen running an element between them.
    #:
    #: The two modes handle ``he_upper_on`` identically and their
    #: brackets overlap in (0.36, 0.54], so they plausibly share one
    #: threshold, but that is an **inference, not a measurement**, and
    #: assuming it would have the model promise an element at 0.6 °F
    #: that High Demand has never been seen to run.  The expensive
    #: error is promising hot water that does not arrive, so
    #: each mode keeps its own observed edge until a run splits them.
    #: What is left between them is one 0.18 °F probe step, under the
    #: upper probe's ±0.36 °F jitter, so another run is unlikely to.
    high_demand_starts_below_setpoint_f: float = field(
        default=0.72, metadata=_p(MEASURED, "°F")
    )

    #: Lower edges of those brackets.  High Demand's negative held for
    #: 53 seconds as the tank cooled through it, not a whole watch;
    #: Electric's lower edge is not observed at all: its only
    #: negative is above the setpoint.
    start_bracket_lower_f: float = field(
        default=0.0, metadata=_p(MEASURED, "°F")
    )
    high_demand_bracket_lower_f: float = field(
        default=0.36, metadata=_p(MEASURED, "°F")
    )

    #: What the element re-engages at **mid-stint in High Demand**,
    #: from history (4.1 °F below the setpoint, 90 % CI 3.8-4.5,
    #: 12 starts).
    #:
    #: **Checked** against the nine mid-stint High Demand
    #: starts on record, read at each run's raw on-edge: deficits 2.5,
    #: 3.8 x4, 4.1 x2, 5.0, median **3.8 °F**. Consistent with 4.1 and
    #: inside that interval. This is the same series by a different
    #: estimator (starts rather than minutes), so it catches a gross
    #: error and is **not** independent confirmation.
    #:
    #: **High Demand only.** `he_upper_on` equals the setpoint in this
    #: mode, so a setpoint-relative rule and a field-relative one
    #: coincide here and cannot be told apart. Energy Saver's figure is
    #: expressed as a temperature instead (see
    #: ``energy_saver_reengages_at_f``), but which of the two forms the
    #: device uses is unresolved in both modes.
    #: The controller starts High Demand's upper element here later in a
    #: stint (``controller.later_upper_on``); the four restarts of
    #: 2026-04-26/27 came at 3.78-4.14 °F short and ran to the
    #: setpoint. No device run has tested it.
    upper_reengages_below_setpoint_f: float = field(
        default=4.1, metadata=_p(MEASURED, "°F")
    )

    #: What the element re-engages at **mid-stint in Energy Saver**:
    #: an absolute tank temperature, not a deficit.
    #:
    #: ``he_upper_on`` rests at 104.9 °F (40.5 degC, the device
    #: minimum) in Energy Saver, and the mid-stint starts cluster just
    #: under it: of 21 on record, **16 begin between 103.6 and
    #: 104.7 °F**. The zone also cannot stay below the setting:
    #: 52 minutes under 104.9 across 36,946, an element running in
    #: 50, no excursion reaching 10 minutes.
    #:
    #: **The engagement point is a temperature, not a gap**
    #: (2026-09-21). With the setpoint at 107.6 the element engaged
    #: three times with the upper zone reading 103.64; a fixed gap below
    #: the setpoint predicted 71.6. And no single gap fits both that and
    #: history's ~104-104.7 at a 140.9 setpoint. History alone could not
    #: show it. Where exactly the threshold sits is less sure:
    #: readings of 104.72, 104.18 and 104.0 did not trigger, which
    #: suggests ~103.7-104.0 on this probe rather than 104.9 plus a lag.
    #:
    #: **The release is run-to-setpoint, not this constant.** It stops
    #: ~1.6 °F under ``he_upper_off``, which tracks the setpoint (107.6
    #: that morning, so it released at 105.98; at 140.9 it runs on to
    #: ~138-139). An earlier version called it a fixed ~106 thermostat
    #: because the setpoint never moved during the replication.
    #:
    #: **Every engagement came with water moving through the tank**:
    #: one shower and two flowing draws of water that had stood and
    #: cooled, each a draw on the tank (it took the upper zone down
    #: 5-8 °F each time). So "the element needs demand on the tank" fits
    #: everything seen; whether demand is *required*, rather than the
    #: temperature alone, is untested. And a setpoint *raise* in this
    #: mode starts it too, via the entry rule, so this constant
    #: describes descents only.
    #:
    #: It is also not razor-sharp: the tank sits at 104.9-106 °F with
    #: the element off in 20 episodes, the longest 35 minutes.
    #:
    #: The *entry* effect is the exception to the field, not the rule:
    #: switching in with the tank 1.8 °F short starts the element while
    #: ``he_upper_on`` sits 33 °F below the probe.
    #:
    #: **Sanity-check the live field before preferring it** to this
    #: default: the reported ``heUpperOnTempSetting`` reads 32 °F
    #: (0 degC, plainly unset) for 16,988 minutes in 2026-03/04. Only
    #: 646 of them in Energy Saver, but a consumer taking 32 °F as the
    #: element threshold would wait for a tank that never gets there.
    energy_saver_reengages_at_f: float = field(
        default=104.9, metadata=_p(MEASURED, "°F")
    )

    #: Energy Saver's entry threshold: **1.8 °F (1.0 °C)**, bracketed by
    #: a descending sweep that found the element off at 0.54 and
    #: 1.44 °F and on within one poll at 1.80 and 2.16.
    #:
    #: Larger than Electric's and High Demand's, and the modes do
    #: differ: at 0.54 °F short Electric ran the element and Energy Saver
    #: did not.  (Those two runs also differed in compressor state, so
    #: the *mechanism* is one reading of two.)
    #:
    #: An earlier 5 °F read a history count, "2 of 11 engaged within
    #: 5 °F", as a threshold.  The count is right; 8 of those 11 are tanks at or
    #: above setpoint, with nothing for an element to do.  Of the three
    #: short, history gives 0 of 2 at 1-2 °F and 1 of 1 at
    #: 2-3 °F: thin, and consistent with the 1.8 the sweep measured.
    energy_saver_entry_deficit_f: float = field(
        default=1.8, metadata=_p(MEASURED, "°F")
    )

    #: Lower edge of the bracket around Energy Saver's entry threshold:
    #: the sweep bounds it to (1.44, 1.80].  Electric and High Demand
    #: have their own band, (0.36, 0.54], in
    #: ``start_bracket_lower_f``. Both are reported, and a plan landing
    #: inside either says so rather than pretending the step is sharp.
    energy_saver_bracket_lower_f: float = field(
        default=1.44, metadata=_p(MEASURED, "°F")
    )

    #: Where **Energy Saver's** upper element switches off: this far
    #: below the setpoint, not at it (2026-10-02, a held-out re-run).
    #: The element runs, and is charged, until the upper zone is this
    #: short; the zone then coasts on with no input, the heat still in
    #: transit after the dead time (``upper_dead_time_min``), so only the
    #: element's run and energy stop here.
    #:
    #: **Measured from raw rows**: every upper-element off-edge on the
    #: device's record against the upper probe and the setpoint as of the edge,
    #: leaving out stints a mode change ended or a setpoint change
    #: crossed.  Since the device runs (2026-09-19 on): **1.62 °F**,
    #: n = 5 on 3 days, range 1.62-1.80, 90 % CI by day 1.62-1.80, at
    #: setpoints of 107.6 and 141.8.  Over the whole record, with the
    #: probe reported at most 6 s before the edge: 1.62, n = 21 on 15
    #: days, CI 1.62-1.80, range 1.26-2.16, at six setpoints from 107.6
    #: to 147.2.  Reads older than that sit 2.16 short (n = 27): the
    #: probe was still rising, so they are left out, not averaged in.
    #: 1.62 °F is 0.9 °C, five probe steps.
    #:
    #: **Energy Saver only.**  High Demand stops at the setpoint
    #: (median 0.18 °F *over* it, one probe step, CI by day −0.18 to
    #: 0.00, n = 10 fresh reads on 4 days, none since the device runs)
    #: and so does Electric's upper element (n = 5, median 0.00, range
    #: −0.54 to +0.90); both keep the setpoint.  A pooled figure would
    #: have moved them by an offset neither shows.  Electric's lower
    #: element has too few clean stops to measure and keeps it too.
    energy_saver_upper_off_below_setpoint_f: float = field(
        default=1.62, metadata=_p(MEASURED, "°F")
    )

    #: Minutes from the upper element's on-edge during which the upper
    #: zone is held, before its heat reaches the layers (2026-10-02).
    #: The element draws its power, and is charged, from the on-edge.
    #: Every mode: the same element and probe.
    #:
    #: **It is the lag of the line the probe's rise settles on, not its
    #: first tick.**  Measured from raw rows, stints that ran to their
    #: own off point, with no draw recorded (a detector session or a
    #: flowing draw) or from before draws were, the two events a
    #: held-out check left out: run minutes = lag + rise ÷ rate,
    #: Theil-Sen, gives **1.21 min (90 % CI by day 0.95-1.60) and
    #: 2.01 °F/min (1.86-2.29), n = 29 on 21 days**; with no draw recorded
    #: only, 1.10 and 2.10 (n = 13).  The probe's first held step comes
    #: sooner, 0.54 min after the on-edge less its reporting cadence (CI
    #: 0.42-0.68, n = 19 on 12 days; a device run saw 42 s with no
    #: movement at all), but its rise is smeared over the next minute: a
    #: zone held for 0.54 min and then lifted at any one rate is early
    #: at one end of a run or late at the other.  By mode that first
    #: step is Energy Saver 0.71 (n = 8, CI −0.03 to 0.90), High Demand
    #: 0.67 (n = 4 on 2 days), Electric 0.43 (n = 7, 0.15-0.67): no
    #: split the data can carry, so one figure.
    #:
    #: **One lag, start and end**: the coast after the off-edge is the
    #: same lag's heat arriving (median coast 1.98 °F, CI 1.80-1.98).
    #: Short clean stints coast the same ~2 °F whatever their rise:
    #: Energy Saver runs lifting the zone 0.54, 1.26 and 1.44 °F coasted
    #: 2.16, 1.98 and 2.16, each to 0.18-0.54 °F over the setpoint; an
    #: Electric run of 0.18, 1.80; High Demand's 2.34, 2.34.
    upper_dead_time_min: float = field(default=1.21, metadata=_p(FITTED, "min"))

    def __post_init__(self) -> None:
        """An off point at or past the entry threshold would have the
        element stop before it starts: every entry run would be charged
        nothing and credited a coast.  A negative dead time would lift
        the zone before the element is on."""
        dead = self.upper_dead_time_min
        if not (math.isfinite(dead) and dead >= 0.0):
            raise ValueError(
                f"upper_dead_time_min must be at least 0 (got {dead})"
            )
        off = self.energy_saver_upper_off_below_setpoint_f
        if not 0.0 <= off < self.energy_saver_entry_deficit_f:
            raise ValueError(
                "energy_saver_upper_off_below_setpoint_f must be at least 0 "
                "and below energy_saver_entry_deficit_f "
                f"({off} vs {self.energy_saver_entry_deficit_f})"
            )


@dataclass(frozen=True, kw_only=True)
class ReadinessParams:
    """What counts as hot water at the tap (``sim.delivery``), and the
    volumes readiness is judged against: choices an installation makes,
    not the heater's terms."""

    #: Delivered water below this is not hot, °F: the line every answer
    #: is drawn at. A choice, not a measurement.
    line_f: float = field(
        default=105.0, metadata=_p(DEFAULT, "°F", INSTALLATION)
    )
    #: How far a probe reading can be off and still describe the same
    #: tank: a round 1 °F, between the probe's jitter of about 0.36 °F
    #: either way and the element's own decisions, which sit 1.4 °F from
    #: the probe's (``docs/explanation/heating-elements.rst``). A bath
    #: answer that a probe error this size would flip says
    #: ``bath_ready_within_probe_resolution``.
    probe_resolution_f: float = field(default=1.0, metadata=_p(DEFAULT, "°F"))
    #: The bath readiness is judged against, delivered gallons: the
    #: larger of two hot-only fills to one household's usual bath level,
    #: read on a meter (22.4 and 28.7 gal). The level is a household's
    #: choice; set your own.
    bath_gal: float = field(
        default=28.7, metadata=_p(MEASURED, "gal", INSTALLATION)
    )
    #: A shower, delivered gallons, when the caller has no forecast of
    #: its own. Assumed, not measured.
    shower_gal: float = field(
        default=12.0, metadata=_p(DEFAULT, "gal", INSTALLATION)
    )


@dataclass(frozen=True, kw_only=True)
class CirculationParams:
    """An installation's circulation of hot water through its own
    plumbing (``sim.circulation``): what each run takes. No defaults:
    they describe one installation's plumbing, and nothing measured
    carries to another; ``site_example_params`` has one's."""

    #: Gallons a run displaces before hot water comes back: an effective
    #: volume, fitted with ``return_rest_offset_f`` and
    #: ``return_cool_tau_h`` (``calibration.fit_return``), so refit the
    #: three together.
    displaced_gal: float = field(metadata=_p(FITTED, "gal", INSTALLATION))
    #: The flow a run is priced at, gal/min.
    flow_gpm: float = field(metadata=_p(MEASURED, "gal/min", INSTALLATION))
    #: How far above the air at the heater the return rests between
    #: runs, °F: the pipe runs through warmer or cooler space than the
    #: heater's. 0 rests it at the air.
    return_rest_offset_f: float = field(
        default=0.0, metadata=_p(FITTED, "°F", INSTALLATION)
    )
    #: The time constant on which the pipe a run warmed cools back to
    #: rest, hours: a run this soon after another displaces water about
    #: two thirds cooled (``circulation.cooled_share``). 0 takes it as
    #: cooled at once.
    return_cool_tau_h: float = field(
        default=0.0, metadata=_p(FITTED, "h", INSTALLATION)
    )
    #: The share of a run's own flow a household flow meter also reads,
    #: for the draws of a recorded history (``history.house_gpm``):
    #: 0 for a meter the circulation does not pass. Re-measure it when
    #: the plumbing or the meter changes.
    meter_share: float = field(
        default=0.0, metadata=_p(MEASURED, "1", INSTALLATION)
    )
    #: Runs closer than this are one run, minutes: a restart displaces
    #: water the last run warmed. ``displaced_gal`` is fitted on runs
    #: merged at this gap, so change them together.
    run_gap_min: float = field(
        default=10.0, metadata=_p(MEASURED, "min", INSTALLATION)
    )


#: The term groups calibration fits, as ``HeaterParams.unfitted`` names
#: them: ``compressor`` (the heat map: a recovery's duration),
#: ``power`` (the power map: its energy and COP) and ``tank`` (the
#: layered tank's probes, mixing, conduction, losses and condenser,
#: ``sim.tank_fit``); and the installation's terms fitted from a meter's
#: draws, ``draw`` (``DrawParams``: the delivery line and the inlet).
UNFITTED_TERMS: tuple[str, ...] = ("compressor", "power", "tank", "draw")
#: The installation's terms another installation's values stand in for
#: until its own meter fits them (``defaults.default_params``).
INSTALLATION_TERMS: tuple[str, ...] = ("draw",)
#: Term groups a document may name unfitted that this code no longer
#: has: the heat book's and the readiness evidence's, read and left out.
RETIRED_TERMS = frozenset({"book", "readiness"})


@dataclass(frozen=True, kw_only=True)
class HeaterParams:
    """Every parameter the simulation runs on, as one frozen value."""

    tank: TankParams
    loss: LossParams
    compressor: CompressorParams
    element: ElementParams
    draw: DrawParams
    controller: ControllerParams
    readiness: ReadinessParams = field(default_factory=ReadinessParams)
    #: None: no circulation, or none described.
    circulation: CirculationParams | None = None
    #: The term groups (``UNFITTED_TERMS``) whose values were not fitted
    #: on this heater but kept from the parameters calibration started
    #: from (``calibration.calibrate``): every answer they reach says so
    #: (``api`` reasons ``physics_uncalibrated``, ``energy_uncalibrated``,
    #: ``tank_uncalibrated``). A client with its own
    #: model may read it and turn the physics off itself.
    unfitted: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unknown = set(self.unfitted) - set(UNFITTED_TERMS)
        if unknown:
            raise ValueError(
                f"unfitted names {sorted(unknown)}, not one of "
                f"{list(UNFITTED_TERMS)}"
            )
        object.__setattr__(
            self,
            "unfitted",
            tuple(t for t in UNFITTED_TERMS if t in set(self.unfitted)),
        )


#: The document's schema: its name, and a version that moves only when
#: a reader of the previous one would misread it.
PARAMS_SCHEMA = "heater-params/2"
#: Schemas this code no longer reads: their parameters ran a model it
#: no longer has, so they are refitted, not converted.
RETIRED_SCHEMAS = frozenset({"heater-params/1"})

#: Each part of ``HeaterParams``, by its field name, in document order.
PARTS: Mapping[str, type] = MappingProxyType(
    {
        "tank": TankParams,
        "loss": LossParams,
        "compressor": CompressorParams,
        "element": ElementParams,
        "draw": DrawParams,
        "controller": ControllerParams,
        "readiness": ReadinessParams,
        "circulation": CirculationParams,
    }
)

#: Parts that may be absent: None, not their defaults.
OPTIONAL_PARTS = frozenset({"circulation"})


def _plain(value: Any) -> Any:
    """A field's value as JSON holds it: a tuple as a list."""
    if isinstance(value, tuple):
        return [_plain(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def params_to_document(params: HeaterParams) -> dict[str, Any]:
    """``params`` as a document: ``schema``, and each part an object of
    its fields' values, as they are (``None``, a bool, a number, a list
    for a tuple)."""
    doc: dict[str, Any] = {"schema": PARAMS_SCHEMA}
    for name in PARTS:
        part = getattr(params, name)
        if part is None:
            continue
        doc[name] = {
            f.name: _plain(getattr(part, f.name)) for f in fields(part)
        }
    if params.unfitted:
        doc["unfitted"] = list(params.unfitted)
    return doc


def unknown_fields(doc: Mapping[str, Any]) -> list[str]:
    """The parts and fields ``doc`` names that ``HeaterParams`` has not
    (``part`` or ``part.field``): what a newer writer added, which
    ``params_from_document`` leaves out."""
    out = [k for k in doc if k not in ("schema", "unfitted") and k not in PARTS]
    for name, cls in PARTS.items():
        known = {f.name for f in fields(cls)}
        given = doc.get(name, {})
        if isinstance(given, Mapping):
            keys = cast(Mapping[str, Any], given)
            out.extend(f"{name}.{k}" for k in keys if k not in known)
    return out


def _check(where: str, hint: Any, value: Any) -> None:
    """A ``ValueError`` naming ``where`` when ``value`` is not what a
    document holds for a field of type ``hint``: a number for a float, a
    whole number for an int,
    a list for a tuple, null for None."""
    args = get_args(hint)
    if get_origin(hint) is UnionType:
        if value is None and NoneType in args:
            return
        (hint,) = (a for a in args if a is not NoneType)
        args = get_args(hint)
    if get_origin(hint) is tuple:
        if not isinstance(value, list | tuple):
            raise ValueError(f"{where} is {value!r}, not a list")
        items: list[Any] | tuple[Any, ...] = value
        if len(args) == 2 and args[1] is Ellipsis:
            args = (args[0],) * len(items)
        elif len(items) != len(args):
            raise ValueError(
                f"{where} has {len(items)} values, not {len(args)}"
            )
        for i, (h, v) in enumerate(zip(args, items, strict=True)):
            _check(f"{where}[{i}]", h, v)
        return
    if hint is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        kind = "a number"
    elif hint is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
        kind = "a whole number"
    elif hint is bool:
        ok, kind = isinstance(value, bool), "true or false"
    elif hint is str:
        ok, kind = isinstance(value, str), "a string"
    else:
        return
    if not ok:
        raise ValueError(f"{where} is {value!r}, not {kind}")


#: The two-zone tank's term groups in ``HeaterParams.unfitted``, and its
#: fitted loss: a document that names either was written before the
#: layered tank was calibrated.
_TWO_ZONE_TERMS = frozenset({"standby", "gap_tau"})
_TWO_ZONE_LOSS = "ua_btu_hr_f"


def params_from_document(doc: Mapping[str, Any]) -> HeaterParams:
    """The ``HeaterParams`` ``doc`` holds.

    A field the document does not carry takes its default, as a part
    added after the document was written would; one with no default is
    a ``ValueError``. Parts and fields this code does not know are left
    out (``unknown_fields`` names them): the code reading the document
    runs no rule that could use them. A document of the two-zone tank's
    (its ``loss.ua_btu_hr_f``, or ``standby`` or ``gap_tau`` unfitted)
    carries none of the layered tank's fitted terms, so its tank reads
    as the priors (a loss it leaves null included), with ``tank``
    unfitted. A document fitted with the heat book has its book's
    ``draw_gpm`` read as ``DrawParams.draw_gpm`` where the draw part
    carries none. A schema other than
    ``PARAMS_SCHEMA`` is a ``ValueError``, and so are a ``doc`` that is
    not an object and a value of the wrong type (a number where a list
    goes, a string where a number goes).
    """
    if not isinstance(doc, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError("a parameters document is an object")
    schema = doc.get("schema")
    if schema in RETIRED_SCHEMAS:
        raise ValueError(
            f"a {schema} document is from before the heat pump's "
            f"performance map, which {PARAMS_SCHEMA} carries: calibrate "
            "again (see the CHANGELOG)"
        )
    if schema != PARAMS_SCHEMA:
        raise ValueError(f"not a {PARAMS_SCHEMA} document: schema {schema!r}")
    unfitted = doc.get("unfitted", ())
    _check("unfitted", tuple[str, ...], unfitted)
    names = set(unfitted) - RETIRED_TERMS
    loss = doc.get("loss")
    two_zone = bool(names & _TWO_ZONE_TERMS) or (
        isinstance(loss, Mapping) and _TWO_ZONE_LOSS in loss
    )
    if two_zone:
        names = (names - _TWO_ZONE_TERMS) | {"tank"}
    parts: dict[str, Any] = {}
    for name, cls in PARTS.items():
        if name in OPTIONAL_PARTS and doc.get(name) is None:
            continue
        given = doc.get(name, {})
        if not isinstance(given, Mapping):
            raise ValueError(f"part {name!r} is not an object")
        values = {}
        book = doc.get("book")
        if (
            name == "draw"
            and "draw_gpm" not in given
            and isinstance(book, Mapping)
            and "draw_gpm" in book
        ):
            # The flow that is a draw was the heat book's term.
            given = {**given, "draw_gpm": book["draw_gpm"]}
        hints = get_type_hints(cls)
        for f in fields(cls):
            if two_zone and name == "loss" and given.get(f.name) is None:
                # Its sides' loss was unset: the jacket's, not a term.
                continue
            if f.name in given:
                _check(f"{name}.{f.name}", hints[f.name], given[f.name])
                values[f.name] = given[f.name]
            elif f.default is MISSING and f.default_factory is MISSING:
                raise ValueError(f"{name}.{f.name} is missing")
        parts[name] = cls(**values)
    return HeaterParams(**parts, unfitted=tuple(names))
