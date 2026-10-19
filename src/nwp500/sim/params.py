"""The heater's parameters: one frozen value, composed of parts.

``HeaterParams`` gathers every number the simulation runs on, so the
physics take values rather than reaching for a caller's configuration
or a module constant:

- ``TankParams``: the tank's size, and the thermal masses derived
  from it;
- ``LossParams``: the jacket's UA law;
- ``CompressorParams``: the vapour-compression cycle, its four fixed
  constants included;
- ``PowerParams``: input power and COP, fitted per retrain;
- ``ElementParams``: the resistance elements;
- ``DrawParams``: a draw through the tank, delivered through the
  mixing valve or flowing from it, and its inflow;
- ``ControllerParams``: the numbers of the firmware's rules for when
  the compressor starts and stops (``sim/controller.py``).
- ``ReadinessParams``: what counts as hot water at the tap, and how
  the delivered water follows the upper probe (``sim.delivery``);
- ``BookParams``: the heat book, the tank's heat by bookkeeping
  (``sim.book``).

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
core (``units`` and the UA law's reference ΔT in ``physics.tank``),
which import nothing back.
"""

import math
from collections.abc import Mapping
from dataclasses import MISSING, dataclass, field, fields, replace
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any

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
_VALVE_FRAME = (
    "fitted through one installation's mixing valve and coupled with "
    "inlet_temp_f: change them together"
)
_VALVE_LINE = (
    "a mixing valve's delivery line; intercept 0 and slope 1 is no valve, "
    "delivery at the tank's own temperature"
)
_MAINS = (
    "one installation's mains, a probe's median over one week of "
    "2026-09; coupled with observability"
)
_CIRCULATION = (
    "fitted on one installation's circulation return water; acts only "
    "with flowing draws"
)
_PER_DELIVERED = "per gallon delivered through one installation's mixing valve"


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


# ΔT at which ``ua_ref`` is quoted.  50 °F sits between the cold-soak and
# hot-standby clusters, so ua_ref is interpolated rather than extrapolated
# from either.
UA_REF_DELTA_T_F = 50.0

# ΔT floor inside the power law.  As ΔT → 0 the power law would drive UA
# → 0 (exponent > 0), which is unphysical: conduction through the jacket
# does not vanish.  It also has no observable consequence (the loss term
# is UA·ΔT, so both factors are heading to zero), but it keeps UA finite
# and positive for callers that read it directly.
UA_MIN_DELTA_T_F = 5.0


@dataclass(frozen=True, kw_only=True)
class TankParams:
    """The tank: its size, and the thermal masses that follow from it.

    The masses are derived, not stored, so a tank of another size
    cannot carry the 63.2-gal tank's mass.
    """

    #: Rated storage, gallons: the NWP500-65's actual 63.2 (marketed as
    #: 65).
    volume_gal: float = field(default=63.2, metadata=_p(DEFAULT, "gal"))
    #: The share of the tank the two-zone model gives the lower zone,
    #: the stratum the condenser coil wraps.
    lower_zone_share: float = field(
        default=0.5, metadata=_p(DEFAULT, "fraction")
    )
    #: Time constant of the stratification gap's decay, hours, fitted per
    #: retrain. None, unfitted: the consumer uses its prior.
    stratification_gap_tau_h: float | None = field(
        default=None, metadata=_p(FITTED, "h")
    )

    @property
    def thermal_mass_btu_f(self) -> float:
        """Full-tank thermal mass, BTU/°F (≈ 527 at 63.2 gal)."""
        return self.volume_gal * WATER_BTU_PER_GAL_F

    @property
    def lower_zone_thermal_mass_btu_f(self) -> float:
        """Lower-zone thermal mass, BTU/°F (≈ 263)."""
        return self.thermal_mass_btu_f * self.lower_zone_share

    @property
    def lower_zone_volume_gal(self) -> float:
        """The lower zone, gallons (31.6), which a flowing draw's inflow
        mixes into (``physics.draw.lower_zone_drop_f``)."""
        return self.volume_gal * self.lower_zone_share


@dataclass(frozen=True, kw_only=True)
class LossParams:
    """Standby loss through the jacket: the UA law
    (``physics.tank.ua_at``)."""

    #: UA at ``ua_ref_delta_t_f``, BTU/hr·°F, fitted per retrain. None:
    #: ``ua_baseline_btu_hr_f``.
    ua_btu_hr_f: float | None = field(
        default=None, metadata=_p(FITTED, "BTU/hr/°F", note=_LOCATION_AIR)
    )
    #: Power-law exponent of UA in ΔT. 0.0, what a fit from before the
    #: power law carries, is a constant UA.
    ua_exponent: float = field(
        default=0.0, metadata=_p(FITTED, "1", note=_LOCATION_AIR)
    )
    #: ΔT at which ``ua_btu_hr_f`` is quoted, °F.
    ua_ref_delta_t_f: float = field(
        default=UA_REF_DELTA_T_F, metadata=_p(DEFAULT, "°F")
    )
    #: The UA used before any calibration, BTU/hr·°F.
    ua_baseline_btu_hr_f: float = field(
        default=5.0, metadata=_p(DEFAULT, "BTU/hr/°F")
    )


@dataclass(frozen=True, kw_only=True)
class CompressorParams:
    """The R-134a vapour-compression cycle (``physics.compressor``).

    The fitted pair and the two-zone flag come from a calibration. The
    integrator takes those two as arguments, because calibration
    searches over them; it reads the four fixed constants from here.
    """

    #: K = V_disp × N_RPM × η_motor, ft³/s. 0.0 is uncalibrated.
    compressor_constant: float = field(
        default=0.0, metadata=_p(FITTED, "ft³/s", note=_IN_RECOVERY)
    )
    #: T_amb − T_evap at the coil, °F.
    evap_approach_f: float = field(
        default=12.0, metadata=_p(FITTED, "°F", note=_IN_RECOVERY)
    )
    #: Whether ``compressor_constant`` was fitted under the two-zone
    #: integration.
    two_zone: bool = field(default=False, metadata=_p(FITTED, "flag"))
    #: T_cond ≈ T_lower + this, °F.
    cond_approach_f: float = field(default=10.0, metadata=_p(DEFAULT, "°F"))
    #: Clearance volume ratio, in the volumetric efficiency.
    clearance_ratio: float = field(default=0.05, metadata=_p(DEFAULT, "1"))
    #: Polytropic exponent for R-134a compression (1.15-1.20).
    polytropic_exp: float = field(default=1.17, metadata=_p(DEFAULT, "1"))
    #: Evaporator fan airflow, from the NWP500's specification.
    fan_airflow_cfm: float = field(
        default=229.0, metadata=_p(DEFAULT, "ft³/min")
    )


@dataclass(frozen=True, kw_only=True)
class PowerParams:
    """Input power and COP, fitted per retrain to metered cycles. None,
    unfitted: a projection carries no power or COP."""

    power_scale: float | None = field(metadata=_p(FITTED, "1"))
    cop_scale: float | None = field(metadata=_p(FITTED, "1"))
    #: Electricity a compressor start spends before the tank gains
    #: anything.
    startup_wh: float = field(metadata=_p(FITTED, "Wh"))
    #: How much faster than the integrator's COP falls with lift, per °F
    #: about ``cop_lift_ref_f``.
    cop_lift_coeff: float = field(metadata=_p(FITTED, "1/°F"))
    cop_lift_ref_f: float = field(metadata=_p(DEFAULT, "°F"))


@dataclass(frozen=True, kw_only=True)
class DrawParams:
    """A draw through the tank (``physics.draw``), as a calibration
    carries it: a delivered draw's terms (``draw_*``), and how a flowing draw's
    inflow mixes into the lower zone (the last three)."""

    #: Share of a draw's enthalpy the probes register. None: the
    #: consumer's default (``physics.draw.DEFAULT_OBSERVABILITY``).
    observability: float | None = field(
        metadata=_p(FITTED, "1", INSTALLATION, _VALVE_FRAME)
    )
    #: Stratification gap a gallon drawn opens, °F/gal.
    gap_open_f_per_gal: float = field(
        metadata=_p(FITTED, "°F/gal", INSTALLATION, _VALVE_FRAME)
    )
    #: The mixing valve's delivery line: intercept + slope × T_upper,
    #: never above the tank. Intercept 0 and slope 1 is no valve.
    delivery_intercept_f: float = field(
        metadata=_p(FITTED, "°F", INSTALLATION, _VALVE_LINE)
    )
    delivery_slope: float = field(
        metadata=_p(FITTED, "1", INSTALLATION, _VALVE_LINE)
    )
    #: The cold inlet's reference temperature, °F.
    inlet_temp_f: float = field(metadata=_p(FITTED, "°F", INSTALLATION, _MAINS))
    #: Whether ``inlet_temp_f`` was read from the inlet probe.
    inlet_from_probe: bool = field(metadata=_p(MEASURED, "flag", INSTALLATION))
    #: The stratification gap over which a flowing draw's inflow reaches
    #: the lower thermistor (``physics.draw.lower_zone_drop_f``). 0.0 is
    #: the ungated charge, ``ungated_observability`` of the heat to both
    #: zones alike.
    lower_gate_f: float = field(
        metadata=_p(FITTED, "°F", INSTALLATION, _CIRCULATION)
    )
    #: The standby pool's growth, °F per hour unheated, added to the gap
    #: the inflow is gated on.
    pool_f_per_hour: float = field(
        metadata=_p(FITTED, "°F/h", INSTALLATION, _CIRCULATION)
    )
    #: Share of a flowing draw's heat the probes register under the
    #: ungated charge (``lower_gate_f = 0.0``, parameters from before
    #: the lower-zone law).
    ungated_observability: float = field(
        metadata=_p(FITTED, "1", INSTALLATION, _CIRCULATION)
    )
    #: The range the draw terms were fitted over: the upper zone before
    #: a draw, °F (508 episodes spanning 122.2-147.9; the delivery line
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

    def __post_init__(self) -> None:
        # A document carries the ranges as lists.
        for name in ("domain_upper_f", "domain_volume_gal"):
            v = getattr(self, name)
            if v is not None:
                low, high = v
                object.__setattr__(self, name, (float(low), float(high)))

    def out_of_domain(self, upper_f: float, volume_gal: float) -> bool:
        """Whether a draw of ``volume_gal`` (its own volume, never a
        rate times a mean) from an upper zone at ``upper_f`` lies
        outside the range the draw terms were fitted over; both bounds
        are inclusive."""
        for value, bounds in (
            (upper_f, self.domain_upper_f),
            (volume_gal, self.domain_volume_gal),
        ):
            if bounds is not None and not bounds[0] <= value <= bounds[1]:
                return True
        return False


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
      zone above it;
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
    #: Any mode write into a compressor mode starts it with the lower
    #: zone this much or more short.
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
    #: Judging at the start caught 17 of 59 capped cycles against 43 at
    #: the end (``docs/explanation/tou-recovery-cap.rst``).
    tou_cap_f: float = field(default=3.6, metadata=_p(MEASURED, "°F"))

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
    upper_f_per_min: float = field(default=2.01, metadata=_p(FITTED, "°F/min"))
    lower_f_per_min: float = field(default=1.38, metadata=_p(FITTED, "°F/min"))
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
    #: Recorded because the entry figure above is routinely mistaken
    #: for it; nothing in this module projects a re-engagement, and no
    #: device run has tested one.
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
    #: short; the zone then coasts on with no input, by at most
    #: this much and at most the heat in transit (``coast_f``), so
    #: ``upper_setpoint_minutes`` and time to ready keep the fitted rate
    #: and only the element's run and energy stop here.
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
    #: zone is held, before it rises at ``upper_f_per_min``
    #: (2026-10-02).  The element draws its power, and is charged, from the
    #: on-edge.  Every mode: the same element and probe.
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
    #: **The rate moved with it, from 1.66 to 2.01.**  1.66 was rise over
    #: elapsed between the first and last one-minute grid points with
    #: the element on, which spreads the lag through the rate; adding a
    #: lag to it would count the lag twice and make every long run late.
    #: The line gives back 1.63 in that convention at the median run (4.7
    #: min), inside 1.66's interval.  On the Energy Saver and High Demand
    #: stints of under 8 °F, the size an assisted mode makes, the line
    #: lands within 0.31 min of every recorded run, where 1.66 alone was
    #: 0.54-1.22 min early on every one; three short Electric runs rose
    #: faster than either.
    #:
    #: **One lag, start and end** (``coast_f``): the coast after the
    #: off-edge is the same lag's heat arriving, 0.98 min of rise at this
    #: rate (median coast 1.98 °F, CI 1.80-1.98).  What is in transit at
    #: the off-edge, rate × lag = 2.43 °F, exceeds both the coast and the
    #: off deficit, so the setpoint, not the lag, bounds the coast.  The
    #: lag's own minutes lift nothing during the run; their heat is the
    #: coast, credited once, and the coast is capped at it (rate × the
    #: lesser of the run and the lag), so nothing is credited that was
    #: not charged.  Short clean stints coast the same ~2 °F whatever
    #: their rise: Energy Saver runs lifting the zone 0.54, 1.26 and
    #: 1.44 °F coasted 2.16, 1.98 and 2.16, each to 0.18-0.54 °F over
    #: the setpoint; an Electric run of 0.18, 1.80; High Demand's 2.34,
    #: 2.34.  So a run at the entry threshold coasts to the setpoint.
    #:
    #: **The upper element only.**  Electric's lower zone keeps its
    #: end-to-end rate, which spans the lower probe's first-minute dip.
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


#: An evidence draw (``ReadinessParams.evidence``): the upper and lower
#: probes before it, °F, and the delivered gallons it gave before the
#: upper probe crossed the line.
EvidenceDraw = tuple[float, float, float]


@dataclass(frozen=True, kw_only=True)
class ReadinessParams:
    """What counts as hot water at the tap, and how the delivered water
    follows the upper probe (``sim.delivery``).

    Most of these describe an installation, not the heater: the pipe
    between the heater and the tap, the mixing valve and the household's
    draws. The defaults were measured at one NWP500-65's installation;
    each field says on how much. Measure your own where you can
    (the simulator reference's *Readiness* section says how).
    """

    #: Delivered water below this is not hot, °F: the line every answer
    #: is drawn at. A choice, not a measurement. ``book.empty_btu`` and
    #: an ``evidence`` set were measured at their line, so changing it
    #: means measuring them again.
    line_f: float = field(
        default=105.0, metadata=_p(DEFAULT, "°F", INSTALLATION)
    )
    #: Delivered gallons the tap still gets at or above the line once
    #: the upper probe has crossed it: the water between the probe and
    #: the tap, which the rising cold front reaches after the probe.
    #: Mostly the installation's pipe run to the fixture. Measured once
    #: (n = 1), at one bath's tub spout: 7.3 gal at the spout and 5.3 at
    #: a gauge on the valve outlet; the lower, rounded down. 0 answers
    #: at the probe itself.
    delivered_lag_gal: float = field(
        default=5.0, metadata=_p(MEASURED, "gal", INSTALLATION)
    )
    #: How fast the delivered water falls per delivered gallon once it
    #: has crossed the line, °F/gal; also the rate the heat book's
    #: upper zone falls at past its empty point. From two crossings,
    #: 1.6 at the probe and 1.83-2.07 at a spout; the faster kept.
    fall_f_per_gal: float = field(
        default=2.0, metadata=_p(MEASURED, "°F/gal", INSTALLATION)
    )
    #: At or below this lower-probe reading the thermocline cannot be
    #: placed between the probes: the largest drops on the record start
    #: here.
    cold_lower_cutoff_f: float = field(
        default=100.0, metadata=_p(FITTED, "°F", INSTALLATION)
    )
    #: The answer's cap there, from ``evidence`` only (a heat book is
    #: not capped): the least any draw from such a state gave before the
    #: upper probe reached 110 °F, three draws, rounded down.
    cold_lower_cap_gal: float = field(
        default=6.5, metadata=_p(MEASURED, "gal", INSTALLATION)
    )
    #: Both probes within this of the setpoint, or above it: a tank the
    #: heater has brought to its target, which has the full-tank floor.
    full_setpoint_band_f: float = field(
        default=2.0, metadata=_p(DEFAULT, "°F", INSTALLATION)
    )
    #: What the full-tank floor takes off the tank's heat, in delivered
    #: gallons: the most cold water from earlier draws was found hiding
    #: under the lower probe of a tank that read full, over 2,505
    #: five-minute samples with the setpoint near 141 °F.
    full_hidden_gal: float = field(
        default=13.5,
        metadata=_p(
            FITTED,
            "gal",
            INSTALLATION,
            _PER_DELIVERED + "; may include circulation return water",
        ),
    )
    #: A draw's transient dip that is not running out: the delivered
    #: water may fall this far below the line, for this long, before the
    #: draw counts as cold (the NWP500's upper probe dips about 3.4 °F for
    #: about 3 min during a draw).
    dip_f: float = field(default=3.4, metadata=_p(MEASURED, "°F"))
    dip_min: float = field(default=3.0, metadata=_p(MEASURED, "min"))
    #: How far a probe reading can be off and still describe the same
    #: tank: the element's own decisions sit 1.4 °F from the probe's. A
    #: bath answer that a probe error this size would flip says
    #: ``bath_ready_within_probe_resolution``.
    probe_resolution_f: float = field(default=1.0, metadata=_p(MEASURED, "°F"))
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
    #: Draws that show how much a tank in a given state delivers before
    #: the upper probe crosses ``line_f``: the readiness answer without a
    #: heat book. Each is ``(upper_f, lower_f, gallons)``, reduced to its
    #: frontier. None by default: they are a household's own record.
    #: ``sim.delivery.EXAMPLE_EVIDENCE`` is one installation's.
    evidence: tuple[EvidenceDraw, ...] = field(
        default=(),
        metadata=_p(
            MEASURED,
            "°F, °F, gal",
            INSTALLATION,
            "metered gallons delivered through a mixing valve; over-promises "
            "on an installation without one",
        ),
    )

    def __post_init__(self) -> None:
        # A document carries the draws as lists; the value holds tuples,
        # so one read back equals the one written.
        object.__setattr__(
            self,
            "evidence",
            tuple(
                (float(u), float(lo), float(g)) for u, lo, g in self.evidence
            ),
        )


@dataclass(frozen=True, kw_only=True)
class BookParams:
    """The heat book (``sim.book``): the tank's heat by bookkeeping, and
    where in the tank it lies, which a draw reads to move the zones.

    Its own parameter set, fitted on the re-anchors of one NWP500-65's
    metered record (where the tank became full again and its booked heat
    could be checked against the probes), and not a copy of the other
    parts: it carries its own compressor, element and standby terms.
    """

    #: The tank, gallons, as the book counts it.
    tank_gal: float = field(
        default=63.2, metadata=_p(DEFAULT, "gal", INSTALLATION)
    )
    #: Compressor heat into the tank at a 65 °F ambient, and its slope.
    hp_btu_per_h: float = field(
        default=4252.0, metadata=_p(FITTED, "BTU/h", INSTALLATION)
    )
    hp_btu_per_h_per_f: float = field(
        default=76.1, metadata=_p(FITTED, "BTU/h/°F", INSTALLATION)
    )
    element_w: float = field(
        default=5148.0, metadata=_p(MEASURED, "W", INSTALLATION)
    )
    #: Standby loss per °F of tank mean over the ambient.
    ua_btu_per_h_f: float = field(
        default=2.88, metadata=_p(FITTED, "BTU/h/°F", INSTALLATION)
    )
    #: The reference the book counts heat above, and the inlet it
    #: assumes where none is given; ``empty_btu`` was fitted in this
    #: frame.
    reference_f: float = field(
        default=70.0, metadata=_p(DEFAULT, "°F", INSTALLATION)
    )
    inlet_default_f: float = field(
        default=70.0, metadata=_p(DEFAULT, "°F", INSTALLATION)
    )
    #: The mixing valve's delivery line, intercept + slope × upper zone:
    #: ``DrawParams.delivery_intercept_f`` and ``delivery_slope``, which
    #: the simulator copies here (``HeaterParams.book_terms``). Intercept
    #: 0 and slope 1, the default, is no valve.
    delivery_intercept_f: float = field(
        default=0.0, metadata=_p(FITTED, "°F", INSTALLATION, _VALVE_LINE)
    )
    delivery_slope: float = field(
        default=1.0, metadata=_p(FITTED, "1", INSTALLATION, _VALVE_LINE)
    )
    #: Booked heat above the reference when the upper probe reaches the
    #: line (``ReadinessParams.line_f``): the median of five drawdowns,
    #: 14,219-19,590 BTU.
    empty_btu: float = field(
        default=16169.0, metadata=_p(FITTED, "BTU", INSTALLATION)
    )
    #: The same point refit so it centres those crossings rather than
    #: catching them all early: where a draw takes the upper zone
    #: across the line. Readiness and the delivery keep ``empty_btu``.
    zone_empty_btu: float = field(
        default=12636.0, metadata=_p(FITTED, "BTU", INSTALLATION)
    )
    #: How the upper zone falls through a draw before that point, as the
    #: water above the rising front mixes:
    #: ``zone_mix_f_per_gal · exp(-left / zone_mix_gal)`` °F per
    #: delivered gallon, ``left`` the gallons before ``zone_empty_btu``.
    #: Fitted on 112 draws of 15 gal or more.
    zone_mix_f_per_gal: float = field(
        default=1.25,
        metadata=_p(FITTED, "°F/gal", INSTALLATION, _PER_DELIVERED),
    )
    zone_mix_gal: float = field(
        default=14.0, metadata=_p(FITTED, "gal", INSTALLATION, _PER_DELIVERED)
    )
    #: Where the lower probe reads the cold region, tank gallons from
    #: the bottom, and the width of the front it reads through. Fitted
    #: on 316 draws of 5 gal or more.
    lower_probe_gal: float = field(
        default=25.0, metadata=_p(FITTED, "gal", INSTALLATION)
    )
    front_width_gal: float = field(
        default=32.0, metadata=_p(FITTED, "gal", INSTALLATION)
    )
    #: The lower probe's settling after a draw, minutes (time constant).
    front_settle_min: float = field(
        default=300.0, metadata=_p(FITTED, "min", INSTALLATION)
    )
    #: The book's 90th-percentile error within ``max_anchor_age_h`` of
    #: its anchor, and past it.
    error_btu: float = field(
        default=3000.0, metadata=_p(FITTED, "BTU", INSTALLATION)
    )
    aged_error_btu: float = field(
        default=4100.0, metadata=_p(FITTED, "BTU", INSTALLATION)
    )
    #: Both probes within this of each other: a full tank, the book's
    #: anchor, once it has been quiet since a heating ended.
    uniform_band_f: float = field(
        default=1.5, metadata=_p(FITTED, "°F", INSTALLATION)
    )
    #: An anchor younger than this is fresh.
    max_anchor_age_h: float = field(
        default=18.0, metadata=_p(FITTED, "h", INSTALLATION)
    )
    #: The cold region a draw leaves rejoins the hot water once the heat
    #: landing in it takes it past this.
    cold_release_f: float = field(
        default=100.0, metadata=_p(FITTED, "°F", INSTALLATION)
    )
    #: How old an anchor a book from a recorded history still carries,
    #: aged: a coverage bound, not a fit.
    history_h: float = field(
        default=72.0, metadata=_p(DEFAULT, "h", INSTALLATION)
    )
    #: The household flow that is a draw, gal/min.
    draw_gpm: float = field(
        default=0.3, metadata=_p(DEFAULT, "gal/min", INSTALLATION)
    )
    #: How far back a recorded book reads the inlet for its conversion
    #: to gallons: a probe on the pipe wanders with the air at rest, and
    #: the median over this window steadies the answer without lagging
    #: the mains.
    inlet_window_s: float = field(
        default=10800.0, metadata=_p(DEFAULT, "s", INSTALLATION)
    )


@dataclass(frozen=True, kw_only=True)
class CirculationParams:
    """An installation's circulation of hot water through its own
    plumbing (``sim.circulation``): what each run takes. No defaults:
    they describe one installation's plumbing, and nothing measured
    carries to another; ``site_example_params`` has one's."""

    #: Gallons a run displaces before hot water comes back: an effective
    #: volume, fitted with the return's cooling to the air between runs,
    #: so refit it and the air it returns at together.
    displaced_gal: float = field(metadata=_p(FITTED, "gal", INSTALLATION))
    #: The flow a run is priced at, gal/min.
    flow_gpm: float = field(metadata=_p(MEASURED, "gal/min", INSTALLATION))
    #: The book's loss per gallon circulated while a run is on, BTU/gal:
    #: the pipe's own loss, unsaturated.
    loss_btu_per_gal: float = field(
        metadata=_p(FITTED, "BTU/gal", INSTALLATION)
    )
    #: The share of a run's own flow a household flow meter also reads,
    #: for the heat book from a recorded history (``book.house_gpm``):
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
#: them: ``compressor`` (its constant and approach: a recovery's
#: duration), ``power`` (the power and COP scales: its energy and COP),
#: ``standby`` (the jacket's loss law) and ``gap_tau`` (the gap's time
#: constant); and the installation's terms fitted from a meter's draws,
#: ``book`` (``BookParams``: the heat book's terms and error bands),
#: ``readiness`` (``ReadinessParams``: the delivered lag, hidden heat,
#: cap and volumes) and ``draw`` (``DrawParams``: the draw response and
#: its domain).
UNFITTED_TERMS: tuple[str, ...] = (
    "compressor",
    "power",
    "standby",
    "gap_tau",
    "book",
    "readiness",
    "draw",
)
#: The installation's terms another installation's values stand in for
#: until its own meter fits them (``defaults.default_params``).
INSTALLATION_TERMS: tuple[str, ...] = ("book", "readiness", "draw")


@dataclass(frozen=True, kw_only=True)
class HeaterParams:
    """Every parameter the simulation runs on, as one frozen value."""

    tank: TankParams
    loss: LossParams
    compressor: CompressorParams
    power: PowerParams
    element: ElementParams
    draw: DrawParams
    controller: ControllerParams
    readiness: ReadinessParams = field(default_factory=ReadinessParams)
    book: BookParams = field(default_factory=BookParams)
    #: None: no circulation, or none described.
    circulation: CirculationParams | None = None
    #: The term groups (``UNFITTED_TERMS``) whose values were not fitted
    #: on this heater but kept from the parameters calibration started
    #: from (``calibration.calibrate``): every answer they reach says so
    #: (``api`` reasons ``physics_uncalibrated``, ``energy_uncalibrated``,
    #: ``standby_uncalibrated``, ``tau_gap_prior``). A client with its own
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

    def book_terms(self) -> BookParams:
        """``book`` with the mixing valve's line taken from ``draw``: one
        valve, whichever model prices a draw."""
        return replace(
            self.book,
            delivery_intercept_f=self.draw.delivery_intercept_f,
            delivery_slope=self.draw.delivery_slope,
        )


#: The document's schema: its name, and a version that moves only when
#: a reader of the previous one would misread it.
PARAMS_SCHEMA = "heater-params/1"

#: Each part of ``HeaterParams``, by its field name, in document order.
PARTS: Mapping[str, type] = MappingProxyType(
    {
        "tank": TankParams,
        "loss": LossParams,
        "compressor": CompressorParams,
        "power": PowerParams,
        "element": ElementParams,
        "draw": DrawParams,
        "controller": ControllerParams,
        "readiness": ReadinessParams,
        "book": BookParams,
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
        out.extend(f"{name}.{k}" for k in doc.get(name, {}) if k not in known)
    return out


def params_from_document(doc: Mapping[str, Any]) -> HeaterParams:
    """The ``HeaterParams`` ``doc`` holds.

    A field the document does not carry takes its default, as a part
    added after the document was written would; one with no default is
    a ``ValueError``. Parts and fields this code does not know are left
    out (``unknown_fields`` names them): the code reading the document
    runs no rule that could use them. A schema other than
    ``PARAMS_SCHEMA`` is a ``ValueError``.
    """
    if doc.get("schema") != PARAMS_SCHEMA:
        raise ValueError(
            f"not a {PARAMS_SCHEMA} document: schema {doc.get('schema')!r}"
        )
    parts: dict[str, Any] = {}
    for name, cls in PARTS.items():
        if name in OPTIONAL_PARTS and doc.get(name) is None:
            continue
        given = doc.get(name, {})
        if not isinstance(given, Mapping):
            raise ValueError(f"part {name!r} is not an object")
        values = {}
        for f in fields(cls):
            if f.name in given:
                values[f.name] = given[f.name]
            elif f.default is MISSING and f.default_factory is MISSING:
                raise ValueError(f"{name}.{f.name} is missing")
        parts[name] = cls(**values)
    return HeaterParams(**parts, unfitted=tuple(doc.get("unfitted", ())))
