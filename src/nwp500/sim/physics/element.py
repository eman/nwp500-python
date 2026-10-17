"""Heating with the resistance elements when a mode is switched on.

The rest of ``physics/`` models the heat pump: the condenser warms the
lower zone until it reaches ``hp_lower_off``.  Neither the training data
(which drops every cycle an element touched) nor the integrator knows
anything about the two 5 kW elements.  This is the first model of them,
for what history shows each mode doing once it is switched on (the
device behaviour is in ``docs/explanation/heating-elements.rst``):

- **High Demand.** The heat pump heats the lower zone as usual.  The upper
  element heats the upper zone whenever it is more than the re-engage
  hysteresis below the setpoint, and stops when it reaches the setpoint
  (``he_upper_on`` and ``he_upper_off`` both sit at the setpoint in this
  mode).
- **Electric.** No heat pump.  The upper element runs first, to the
  setpoint; then the lower element, to the setpoint.  Never both at once
  (``docs/reference/protocol/device_status.rst``: "Elements do not
  operate simultaneously in Electric mode"; the upper-first order is
  what every Electric sequence in history shows).

- **Entry thresholds differ by mode**, and each is held at its own
  observed edge: Electric 0.54 °F below the setpoint, High Demand 0.72,
  Energy Saver 1.8.  Electric and High Demand handle ``he_upper_on``
  identically and their brackets overlap, so they plausibly share one —
  but High Demand has never been seen to run between 0.36 and 0.72, and
  assuming the smaller number would promise an element that mode has
  never been seen to run.

- **Energy Saver, on entry.** Switched on with the upper zone more than
  about 1.8 °F below the setpoint, the upper element comes on at once
  (device sweep).  The heat pump heats the lower zone, as in High
  Demand.  Element starts *later* in a stint are not modelled; the
  result says so.

- **Where the element stops** (2026-10-02): at the setpoint in High
  Demand and Electric, but **1.62 °F short of it in Energy Saver**,
  measured at raw off-edges (``ElementParams``).  The element's run and
  energy end there; the upper zone then coasts on with no input, by at
  most the off deficit and at most the heat still in transit
  (``coast_f``), so it reaches the setpoint, from a run at the entry
  threshold too.
  Running Energy Saver's element to the setpoint over-stated its energy
  by +20 % on held-out events.

- **The dead time** (2026-10-02): the upper zone is held for 1.21 min
  after the upper element's on-edge, while the element already draws
  its power, then rises at 2.01 °F/min (``ElementParams``
  ``upper_dead_time_min``, ``upper_f_per_min``).  Every upper-element
  run is that much longer, and charged for it.  The rate was 1.66 end
  to end, the lag spread through it, which made a short run early and
  under-charged (−32 % of the metered energy on a 2.7-min run) and a
  long one late.

**This models the entry decision only.**  Every device run measured what
happens within a poll of switching *into* a mode, and that is the
question ``mode_recovery`` answers — a recovery from the moment the mode
takes effect.  It is **not** a thermostat: in High Demand's steady state
history has the upper element on in 2 % of minutes 0.36-0.54 °F short
and 99 % of minutes more than 4 °F short, so a stint that has been
running for a while re-engages on something much nearer the 4.1 °F
steady-state figure than the entry figures below.  A plan that depends
on the element coming back mid-stint is outside what this models.

**Whether the mode can be reached at all is a separate question** and not
this module's: with TOU enabled a mode write may simply not take
(``docs/explanation/heating-elements.rst``, *Writing the mode while a
TOU window is in force*).  A caller
planning against these numbers must check that first — the API layer
reports it.

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
- upper-zone rise 1.66 °F/min fitted end to end (90 % CI 1.60-1.76, 64
  runs); the device gives 1.61 on 10-second polls and **1.55 on the
  one-minute grid the fit itself consumes**, the latter below the
  interval.  **Refitted 2026-10-02 as 2.01 after a 1.21-min lag**
  (``upper_dead_time_min``), from raw run lengths, which give back
  1.63 in the old fit's own convention;
- lower-zone rise 1.38 °F/min fitted (90 % CI 1.21-1.62, **9 runs**);
  the device gives 1.19 end-to-end, **below** the interval, and 1.26 on
  the fit's own grid, inside it;
- the entry thresholds below, which are bracketed on both sides by the
  device and are the only parameters here that are.

Rates are held constant: history shows no clear dependence on how far
below the setpoint a run starts.  Draws and standby loss during a run are
ignored; at 5 kW standby is under 2 % of the input.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
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


#: Most intervals one plan may carry.  A caller can ask for a slot
#: narrower than the rounding on ``end_minute`` (3 dp) or a setpoint
#: absurd enough to make the recovery days long; both used to build the
#: list anyway, until the process ran out of memory.
MAX_PROFILE_SLOTS = 2000

#: Reasons every result carries, so a consumer cannot mistake this for the
#: heat-pump model's confidence.
BASE_REASONS: tuple[str, ...] = ("element_model_small_n",)


@dataclass(frozen=True)
class ModeRecovery:
    """How a recovery in an element mode unfolds from a given tank state.

    Minutes are from the moment the mode takes effect.

    - ``upper_ready_minutes``: when the upper zone reaches ``ready_upper_f``
      (0 if it already has; **None** if it never will, because the element
      stops at the setpoint or does not start at all).
    - ``upper_setpoint_minutes``: when the upper zone reaches the setpoint;
      0 if it is already there, **None** if the element does not start.
      In Energy Saver the last stretch is the zone coasting after the
      element has stopped (``upper_off_deficit_f``), at the same rate,
      and None when less than that is in transit (``coast_f``; not at
      the served numbers).
    - ``upper_element_minutes``: when the upper element stops, at its
      mode's off point: the setpoint, or in Energy Saver 1.62 °F short
      of it.  0 if it has nothing to do, **None** if it does not start.
      It includes the dead time (``ElementParams.upper_dead_time_min``),
      during which the element is on and the zone has not yet moved, as
      every upper-zone time here does.
      With less than the off deficit in transit the zone ends below
      the setpoint (``upper_end_f``); ``upper_setpoint_minutes`` is
      then None.
    - ``full_minutes``: when the whole recovery ends.  High Demand: the later
      of the upper zone reaching the setpoint and the heat pump's
      lower-zone recovery (``hp_lower_minutes``, from the heat-pump
      model; None if not given).  Electric: upper element, then lower.
    - ``element_minutes`` / ``element_kwh``: element running time and its
      energy, each element to its off point.  The heat pump's energy is
      the heat-pump model's to report.
    """

    mode: ElementMode
    upper_ready_minutes: float | None
    upper_setpoint_minutes: float | None
    upper_element_minutes: float | None
    #: Where the upper zone ends up, and when: the setpoint, or, with a
    #: dead time too short to carry the whole off deficit in transit,
    #: Energy Saver's off point plus that coast (``coast_f``).  Minutes
    #: None when the element does not start.
    upper_end_f: float
    upper_end_minutes: float | None
    full_minutes: float | None
    element_minutes: float
    element_kwh: float
    confidence_reasons: tuple[str, ...]


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


def coast_f(
    mode: ElementMode, params: ElementParams, run_minutes: float
) -> float:
    """How far the upper zone rises, uncharged, after ``mode``'s upper
    element stops at its off point, for a run of ``run_minutes`` from
    its on-edge, the dead time included.

    The coast is the heat in transit when the element stops: what it
    was charged for over its last dead time and the probe has not shown
    (``ElementParams.upper_dead_time_min``), so **the smaller of the off
    deficit, which keeps the zone at or under the setpoint, and the rate
    times the lesser of the run and the dead time**.  Nothing is credited
    that was not charged, and the dead time's heat is credited once.

    Measured on raw rows (2026-10-02): the probe rises about 2 °F after
    an off-edge whatever the run put in (a median 1.98 °F over 21
    clean Energy Saver stints, correlation with run length −0.08).  The
    short clean stints say the same: Energy Saver runs that lifted the
    zone 1.26 and 1.44 °F coasted 1.98 and 2.16, an Electric run that
    lifted it 0.18 coasted 1.80, a High Demand run of 2.34 coasted 2.34.
    In transit at the served numbers is 2.01 × 1.21 = 2.43 °F, so Energy
    Saver's 1.62 °F off deficit binds and every run, a run at the entry
    threshold included, coasts to the setpoint.  A cap at the run's own
    visible rise (the earlier rule) had a run at entry coast
    0.18 °F; the stints contradict it.
    """
    in_transit = params.upper_f_per_min * max(
        0.0, min(run_minutes, params.upper_dead_time_min)
    )
    return max(0.0, min(upper_off_deficit_f(mode, params), in_transit))


def upper_rise_f(params: ElementParams, minutes: float) -> float:
    """How far the upper element lifts its zone in its first ``minutes``
    from the on-edge: nothing for the dead time, then its fitted rate
    (``ElementParams.upper_dead_time_min``)."""
    return params.upper_f_per_min * max(
        0.0, minutes - params.upper_dead_time_min
    )


def mode_recovery(
    mode: ElementMode,
    t_upper: float,
    t_lower: float,
    setpoint: float,
    *,
    ready_upper_f: float | None = None,
    hp_lower_minutes: float | None = None,
    params: ElementParams | None = None,
) -> ModeRecovery:
    """Recovery in an element mode from ``(t_upper, t_lower)``.

    Args:
        mode: ``HIGH_DEMAND``, ``ELECTRIC`` or ``ENERGY_SAVER`` (on entry
            only: see the module docstring).
        t_upper, t_lower: tank probes when the mode takes effect (°F).
        setpoint: the heater's setpoint (°F).  The elements' off
            settings follow it: each element stops at it, except Energy
            Saver's upper element, which stops
            ``energy_saver_upper_off_below_setpoint_f`` short of it.
        ready_upper_f: an upper-zone temperature that counts as "ready",
            for example the depletion threshold.  Defaults to the setpoint.
        hp_lower_minutes: High Demand and Energy Saver: the heat-pump
            model's minutes for the lower zone to reach its target from
            ``t_lower``.
        params: fitted terms; the defaults are the history fit.
    """
    if mode not in ("HIGH_DEMAND", "ELECTRIC", "ENERGY_SAVER"):
        raise ValueError(
            f"{mode!r} is not modelled: only HIGH_DEMAND, ELECTRIC and "
            "ENERGY_SAVER run an element"
        )
    p = params or ElementParams()
    target = setpoint if ready_upper_f is None else ready_upper_f
    reasons = list(BASE_REASONS)

    rate = p.upper_f_per_min
    # The zone does not move for this long after the on-edge, while the
    # element is on and charged (``ElementParams.upper_dead_time_min``).
    dead = p.upper_dead_time_min
    off_at = setpoint - upper_off_deficit_f(mode, p)
    #: Where the upper zone ends: the setpoint, or Energy Saver's off
    #: point plus its coast, which a short run leaves below it.
    top = setpoint
    if t_upper >= setpoint:
        # Nothing for the element to do.
        upper_min: float | None = 0.0
        upper_el: float | None = 0.0
        upper_done: float | None = 0.0
    elif t_upper <= setpoint - _start_deficit(mode, p):
        # The element stops at its off point; the zone coasts on by the
        # heat still in transit, at most to the setpoint (``coast_f``).
        rise = max(0.0, off_at - t_upper)
        upper_el = dead + rise / rate
        top = min(setpoint, max(t_upper, off_at) + coast_f(mode, p, upper_el))
        upper_done = dead + (top - t_upper) / rate
        if top >= setpoint - 1e-9:
            upper_min = dead + (setpoint - t_upper) / rate
        else:
            upper_min = None
            reasons.append("upper_zone_coasts_short_of_the_setpoint")
    else:
        # Short of the setpoint, but not far enough below it to start.
        upper_min = upper_el = upper_done = None
        reasons.append("upper_element_does_not_start")

    if t_upper >= target:
        ready: float | None = 0.0
    elif target > setpoint:
        # The element stops at the setpoint, so the target never arrives.
        ready = None
        reasons.append("ready_target_above_setpoint")
    elif upper_done is None or target > top + 1e-9:
        # The element does not start, or a short run's coast stops short.
        ready = None
    else:
        ready = dead + (target - t_upper) / rate

    lower, upper_edge = _start_bracket(mode, p)
    if lower < setpoint - t_upper < upper_edge:
        reasons.append("deficit_inside_the_start_threshold_bracket")
    if mode == "ELECTRIC" and t_lower < setpoint:
        # Measured 2026-09-20: once the upper element stops and
        # the lower one takes over, the upper probe *falls* — 3.4 °F in
        # that run — before recovering as the tank mixes.  Nothing here
        # models redistribution, so an answer that depends on
        # the upper zone staying put through the lower phase is not
        # safe.
        reasons.append("upper_zone_dips_during_the_lower_phase")
    if mode == "ENERGY_SAVER":
        reasons.append("energy_saver_later_starts_not_modelled")
    if mode in ("HIGH_DEMAND", "ENERGY_SAVER"):
        lower_elem_min = 0.0
        if hp_lower_minutes is None:
            full: float | None = None
            reasons.append("hp_lower_not_given")
        else:
            full = max(upper_done or 0.0, hp_lower_minutes)
    else:
        # The lower element takes over when the upper one stops.
        lower_elem_min = max(0.0, setpoint - t_lower) / p.lower_f_per_min
        full = (upper_el or 0.0) + lower_elem_min
        reasons.append("lower_element_nine_runs")

    element_min = (upper_el or 0.0) + lower_elem_min
    return ModeRecovery(
        mode=mode,
        upper_ready_minutes=ready,
        upper_setpoint_minutes=upper_min,
        upper_element_minutes=upper_el,
        upper_end_f=top,
        upper_end_minutes=upper_done,
        full_minutes=full,
        element_minutes=element_min,
        element_kwh=element_min / 60.0 * p.element_w / 1000.0,
        confidence_reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class ElementInterval:
    """One slot of an element-mode recovery's electrical input."""

    #: Minutes from the moment the mode takes effect to the slot's end.
    end_minute: float
    #: Element input over the slot, Wh.  **Elements only** — in High
    #: Demand and Energy Saver the heat pump runs alongside and its
    #: input is the heat-pump model's to report.
    element_wh: float


@dataclass(frozen=True)
class ModePlan:
    """A :class:`ModeRecovery` a scheduler can price and chain.

    Adds what `ModeRecovery` deliberately leaves out: where the energy
    falls in time, what the tank looks like when the mode is switched
    back, and how far the projection is trusted.

    **Every field here describes the stint as planned**, truncation
    included.  ``recovery`` is the *untruncated* recovery and is kept
    only for reference — reading a scalar off it after a switch-back
    gives the cost and the readiness of a stint that will not happen,
    which is how this class was wrong when first written.
    """

    #: The full recovery, ignoring ``switch_back_after_minutes``.
    recovery: ModeRecovery
    profile: tuple[ElementInterval, ...]
    #: Tank when the elements stop, for chaining into a standby
    #: projection or another mode.
    end_upper_f: float
    end_lower_f: float
    end_minute: float
    #: Element running time and energy **for this stint**.
    element_minutes: float
    element_kwh: float
    #: When the upper zone reaches the ready target / the setpoint, and
    #: when the whole recovery ends — **None when the stint ends
    #: first**, since a time after the switch-back is a time that never
    #: arrives.
    upper_ready_minutes: float | None
    upper_setpoint_minutes: float | None
    full_minutes: float | None
    confidence_reasons: tuple[str, ...]


def mode_plan(
    mode: ElementMode,
    t_upper: float,
    t_lower: float,
    setpoint: float,
    *,
    ready_upper_f: float | None = None,
    hp_lower_minutes: float | None = None,
    switch_back_after_minutes: float | None = None,
    slot_minutes: float = 10.0,
    params: ElementParams | None = None,
) -> ModePlan:
    """Plan a stint in an element mode.

    ``switch_back_after_minutes`` truncates the stint: the elements stop
    there, and the end state is the tank at that moment. That answers
    "what happens when switching back mid-recovery" — the scheduler
    needs it to price a bounded make-up rather than a full recovery.

    The end state projects **only what this module models**: the upper
    zone under the upper element, and Electric's lower zone under the
    lower element. In High Demand and Energy Saver the lower zone is the
    heat pump's, so it is returned unchanged with a reason saying so —
    chain the heat-pump model for that half rather than reading a number
    this model did not produce.
    """
    if slot_minutes <= 0:
        raise ValueError("slot_minutes must be positive")
    p = params or ElementParams()
    if switch_back_after_minutes is not None and (
        switch_back_after_minutes < 0
    ):
        raise ValueError("switch_back_after_minutes must not be negative")
    rec = mode_recovery(
        mode,
        t_upper,
        t_lower,
        setpoint,
        ready_upper_f=ready_upper_f,
        hp_lower_minutes=hp_lower_minutes,
        params=p,
    )
    reasons = list(rec.confidence_reasons)

    span = rec.element_minutes
    truncated = (
        switch_back_after_minutes is not None
        and switch_back_after_minutes < span
    )
    if truncated:
        reasons.append("truncated_by_switch_back")
        span = min(span, switch_back_after_minutes or 0.0)

    upper_el = rec.upper_element_minutes or 0.0
    upper_run = min(span, upper_el)
    lower_run = max(0.0, span - upper_el)
    if mode != "ELECTRIC":
        lower_run = 0.0
        reasons.append("lower_zone_not_projected_under_heat_pump")

    # An upper element that reached its own off point leaves the zone to
    # coast on (Energy Saver's stops 1.62 °F short; ``coast_f`` caps the
    # coast at the heat in transit), and the end state credits that
    # coast.  One cut off sooner does not.
    ran_out = (
        rec.upper_element_minutes is not None and upper_run >= upper_el - 1e-9
    )
    zone_minutes = (rec.upper_end_minutes or 0.0) if ran_out else upper_run
    # The element only ever heats: a tank already above the setpoint
    # stays where it is rather than being pulled down to it.  A stint
    # cut off inside the dead time is charged and lifts nothing.
    end_upper = max(
        t_upper, min(setpoint, t_upper + upper_rise_f(p, zone_minutes))
    )
    end_lower = (
        max(t_lower, min(setpoint, t_lower + p.lower_f_per_min * lower_run))
        if mode == "ELECTRIC"
        else t_lower
    )

    if not math.isfinite(span):
        raise ValueError(f"the recovery span is not finite: {span}")
    if span / slot_minutes > MAX_PROFILE_SLOTS:
        raise ValueError(
            f"a {span:.0f}-minute stint in {slot_minutes}-minute slots is "
            f"{span / slot_minutes:.0f} intervals, over the "
            f"{MAX_PROFILE_SLOTS} cap; widen slot_minutes"
        )
    profile: list[ElementInterval] = []
    elapsed = 0.0
    while elapsed < span - 1e-9:
        slot = min(slot_minutes, span - elapsed)
        elapsed += slot
        profile.append(
            ElementInterval(
                end_minute=round(elapsed, 3),
                element_wh=round(slot / 60.0 * p.element_w, 2),
            )
        )

    # The stint ends when the elements stop, which is the switch-back
    # only when that came first.  Carrying the switch-back through
    # instead would hand back a tank held at setpoint for however long
    # the caller named, with the standby loss over that gap silently
    # dropped — and nothing here models standby.
    if (
        switch_back_after_minutes is not None
        and switch_back_after_minutes > span
    ):
        reasons.append("plan_ends_when_the_elements_stop_not_at_switch_back")

    def _before_the_end(minutes: float | None) -> float | None:
        """A time the stint actually reaches, else None.

        Gated on the **switch-back**, not on the element span: in High
        Demand and Energy Saver the heat pump carries on after the
        elements stop, so ``full_minutes`` legitimately lands long
        after them.  Only leaving the mode ends the recovery.
        """
        if minutes is None:
            return None
        limit = (
            switch_back_after_minutes
            if switch_back_after_minutes is not None
            else math.inf
        )
        return minutes if minutes <= limit + 1e-9 else None

    # The upper zone's times hang on the element only while it runs: once
    # it has stopped at its own off point, the coast it earned goes on
    # whatever the mode, so a switch-back after that cuts neither.
    if truncated:
        ready = _before_the_end(rec.upper_ready_minutes)
        to_setpoint = _before_the_end(rec.upper_setpoint_minutes)
    else:
        ready = rec.upper_ready_minutes
        to_setpoint = rec.upper_setpoint_minutes
    full = _before_the_end(rec.full_minutes)
    if truncated and (
        ready is None
        or to_setpoint is None
        or (rec.full_minutes is not None and full is None)
    ):
        reasons.append("switch_back_lands_before_the_recovery_finishes")

    return ModePlan(
        recovery=rec,
        profile=tuple(profile),
        end_upper_f=round(end_upper, 2),
        end_lower_f=round(end_lower, 2),
        end_minute=round(span, 3),
        element_minutes=round(span, 3),
        element_kwh=round(span / 60.0 * p.element_w / 1000.0, 4),
        upper_ready_minutes=ready,
        upper_setpoint_minutes=to_setpoint,
        full_minutes=full,
        confidence_reasons=tuple(dict.fromkeys(reasons)),
    )
