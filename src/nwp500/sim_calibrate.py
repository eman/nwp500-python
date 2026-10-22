"""Fit a heater's parameters to its recorded history.

The history is the statuses the heater reported, with when
(``nwp500.status_history``). ``calibrate`` builds the frame
``sim.calibration.calibrate`` takes (``sim_adapters.history``), marks
the spans nobody observed, adds the air where the heater stands and its
humidity, and runs the fits; ``report`` says what each fit found, or why
a term kept the base's value.

The standby fit needs the air where the heater stands, which the heater
does not read while idle: an air sensor's readings beside it, a
constant for a heater in conditioned space, or what a Home Assistant
source recorded (``sim_home_assistant.record_inputs``). Filling the gaps
from the heater's own readings while its compressor runs, or projecting
an outdoor history (``sim.location_air``), biases the fit, so neither is
offered; without the air the standby loss keeps the base's value. Given,
the same air is the recoveries' too.

The statuses are taken one at a time, so a long recording read through
``status_history.iter_read`` needs memory for the frame, not for its
statuses::

    from nwp500 import sim_calibrate, status_history

    def recorded(days):
        for day in days:
            with open(day, encoding="utf-8") as f:
                yield from status_history.iter_read(f)

    done = sim_calibrate.calibrate(recorded(day_files), ambient=65.0)
    for term in sim_calibrate.report(done):
        print(term.name, term.value, term.why)

This module needs the ``sim`` extra.
"""

import itertools
import math
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from nwp500 import sim
from nwp500 import sim_adapters as sa
from nwp500.models import DeviceStatus
from nwp500.sim import calibration as cal
from nwp500.sim.params import (
    UNFITTED_TERMS,
    CirculationParams,
    HeaterParams,
    LossParams,
    TankParams,
    params_from_document,
)
from nwp500.sim_adapters import GAP_SAMPLES, MIN_GAP, max_gap, silences

if TYPE_CHECKING:
    import pandas as pd

    from nwp500.sim_home_assistant import RecordInputs

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

__all__ = (
    "DEFAULT_BASE_NOTE",
    "DEFAULT_HUMIDITY_PCT",
    "GAP_SAMPLES",
    "MIN_GAP",
    "NO_AIR_NOTE",
    "CalibrationInputError",
    "Calibrated",
    "CirculationFit",
    "METER_SEES_CIRCULATION_GPM",
    "MIN_CIRCULATION_DAYS",
    "MIN_CIRCULATION_RUNS",
    "NOMINAL_CIRCULATION_GPM",
    "GROUPS",
    "HeldOut",
    "Judged",
    "Term",
    "air_unread_note",
    "calibrate",
    "calibrate_changes",
    "fit_circulation",
    "score",
    "max_gap",
    "report",
)

#: A reading: an instant and a value.
Reading = tuple[datetime, float]

#: The air's relative humidity when none is given, %: the fits' own.
DEFAULT_HUMIDITY_PCT = 50.0

#: The note when no ``params`` were given.
DEFAULT_BASE_NOTE = (
    "refitting the 65 gal defaults (give params for another tank size)"
)
#: The note when no air was given.
NO_AIR_NOTE = "no air given: the standby loss is not fitted"


class CalibrationInputError(ValueError):
    """An input the calibration cannot use."""


def _stepped(series: Sequence[Reading]) -> list[Reading]:
    """A source's ``series`` as the steps it is: a state holds until the
    next, so each change is preceded by the value before it, a moment
    earlier. Interpolated, the readings either side of a long quiet
    spell or an outage would otherwise ramp across it."""
    out: list[Reading] = []
    for t, v in sorted(series):
        if out:
            out.append((t - timedelta(microseconds=1), out[-1][1]))
        out.append((t, v))
    return out


def _unobserved(
    index: Any,
    covers: tuple[datetime, datetime],
    outages: Sequence[tuple[datetime, datetime]],
) -> Any:
    """Where ``index`` falls outside ``covers``, or its interval (to the
    next instant) overlaps an outage."""
    mask = (index < covers[0]) | (index > covers[1])
    nxt = index[1:].append(index[-1:] + timedelta(microseconds=1))
    for a, b in outages:
        mask |= (index < b) & (nxt > a)
    return mask


@dataclass(frozen=True)
class Calibrated:
    """A calibration, and what ``calibrate`` chose along the way."""

    calibration: cal.Calibration
    #: How the air where the heater stands was given (``readings``,
    #: ``constant`` or ``source``), or None.
    air: str | None
    n_statuses: int
    #: Readings further apart than this were taken as unobserved, and
    #: how many such spans the history has.
    max_gap: timedelta
    n_gaps: int
    notes: tuple[str, ...]
    #: The compressor's runs, and how many had no air temperature for
    #: the recoveries (``air_unread_note``): those are no recovery.
    n_runs: int = 0
    n_runs_without_air: int = 0
    #: With ``keep_better``: each group of terms, judged on the evidence
    #: held out of its refit, and that evidence (``score``).
    judged: tuple[Judged, ...] = ()
    held: HeldOut | None = None


# ── keeping the better fit ──────────────────────────────────────────

#: The groups of terms ``keep_better`` judges, each kept or replaced
#: whole: the terms one fit fits together.
GROUPS = ("standby", "gap_tau", "compressor", "power_scale", "cop")


@dataclass(frozen=True)
class Judged:
    """A group of terms judged on the evidence held out of its refit:
    which was kept, both errors, and how many items they were scored
    on. ``kept`` is ``refit`` or ``base``."""

    group: str
    kept: str
    base_error: float | None
    refit_error: float | None
    n_held: int
    why: str


@dataclass(frozen=True)
class HeldOut:
    """The latest of each group's evidence, held out of its refit: the
    quiet windows the loss is fitted on (``sim.calibration.
    loss_windows``), the windows that open a gap, the reached
    recoveries, and the snapshot rows of the cycles the power scale's
    and the COP's fits could use."""

    windows: tuple[cal.StandbyWindow, ...]
    gap_windows: tuple[cal.StandbyWindow, ...]
    recoveries: pd.DataFrame
    power_cycles: pd.DataFrame
    cop_cycles: pd.DataFrame
    #: The gap's constant the standby loss was fitted and judged on,
    #: hours: the one the gap's judgement kept.
    standby_tau_h: float | None = None


def _split(n: int) -> int:
    """How many of ``n`` items, the latest, are held out: as
    ``sim.calibration.split_recoveries`` holds out recoveries."""
    if n < cal.MIN_RECOVERIES_FOR_SPLIT:
        return 0
    return max(cal.MIN_HELDOUT, round(n * cal.HELDOUT_FRACTION))


def _loss_error(
    windows: Sequence[cal.StandbyWindow],
    loss: LossParams,
    tau_gap_hours: float,
    tank: TankParams,
) -> float | None:
    """The standby loss's error on ``windows``: the probes' mean absolute
    error in each window's fall, °F/h, walked on ``tau_gap_hours``
    (``sim.calibration.standby_error``)."""
    return cal.standby_error(windows, loss, tau_gap_hours, tank)


def _gap_error(
    windows: Sequence[cal.StandbyWindow],
    loss: LossParams,
    tank: TankParams,
    tau_hours: float | None,
) -> float | None:
    """The gap's mean squared error on ``windows``, °F², relaxing on
    ``tau_hours`` and opened by ``loss``' bottom loss
    (``sim.calibration.gap_error``)."""
    return cal.gap_error(windows, tau_hours, loss, tank)


def _gap_windows(
    windows: Sequence[cal.StandbyWindow],
) -> list[cal.StandbyWindow]:
    """The windows ``fit_gap_tau`` fits on: opening with a gap."""
    return [
        w
        for w in windows
        if len(w.gap_f) >= 2
        and bool(np.isfinite(w.gap_f).all())
        and w.gap_f[0] >= cal.MIN_GAP_FIT_START_F
    ]


def _recovery_error(
    recoveries: pd.DataFrame, params: HeaterParams
) -> float | None:
    """The mean absolute error of ``params``' recovery durations, in
    minutes, as ``fit_compressor`` scores its held-out recoveries."""
    if recoveries.empty:
        return None
    predicted = cal.recovery_minutes(
        recoveries,
        params.compressor.compressor_constant,
        params.compressor.evap_approach_f,
        compressor=params.compressor,
        loss=params.loss,
        tank=params.tank,
        two_zone=params.compressor.two_zone,
        gaps="stratification_gap" in recoveries.columns
        and bool(recoveries["stratification_gap"].notna().all()),
    )
    if not np.isfinite(predicted).all():
        return None
    actual = np.asarray(recoveries["duration_minutes"], dtype=float)
    return float(np.mean(np.abs(predicted - actual)))


def _n_cycles(cycles: pd.DataFrame) -> int:
    """How many cycles ``cycles``' snapshot rows hold."""
    return len(set(cycles["cycle"])) if len(cycles) else 0


def _power_error(cycles: pd.DataFrame, params: HeaterParams) -> float | None:
    """The power scale's mean relative error in each cycle's metered
    energy. None unless ``params`` model every cycle: a score over the
    ones it can would drop the hard ones."""
    scale = params.power.power_scale
    rows = cal.power_cycles(cycles, params)
    if scale is None or not rows or len(rows) < _n_cycles(cycles):
        return None
    return float(np.mean([abs(m - scale * e) / m for _, m, e in rows]))


def _cop_error(cycles: pd.DataFrame, params: HeaterParams) -> float | None:
    """The COP terms' squared error in each cycle's metered energy,
    weighted ``1 / metered``, as ``solve_cop_fit`` fits them. The
    parameters hold no lead share, so none is counted. None unless
    ``params`` model every cycle, as for ``_power_error``."""
    p = params.power
    rows = cal.cop_cycles(cycles, params)
    if p.cop_scale is None or not rows or len(rows) < _n_cycles(cycles):
        return None
    errors = []
    for c in rows:
        cop = c.modelled_cop * np.exp(
            -p.cop_lift_coeff * (c.lift_f - p.cop_lift_ref_f)
        )
        predicted = p.startup_wh + c.heat_wh / (p.cop_scale * cop)
        errors.append((predicted - c.metered_wh) ** 2 / c.metered_wh)
    return float(np.mean(errors))


def score(done: Calibrated, params: HeaterParams) -> dict[str, float | None]:
    """Each group's error for ``params`` on the evidence ``done`` held
    out of its refits (``keep_better``), by ``GROUPS``; None where none
    was held out, or ``params`` cannot model all of it. Lower is better;
    each group's error is its own fit's, or the walk's:

    - ``standby``: the probes' mean absolute error in each window's
      fall, °F/h, walked on ``HeldOut.standby_tau_h``;
    - ``gap_tau``: the gap's mean squared error, °F², relaxing on the
      constant and opened by ``params``' bottom loss;
    - ``compressor``: the recovery durations' mean absolute error, min;
    - ``power_scale``: the mean relative error in metered energy;
    - ``cop``: the squared error in metered energy weighted
      ``1 / metered``.

    Raises ``CalibrationInputError`` for a ``done`` not made with
    ``keep_better``."""
    held = done.held
    if held is None:
        raise CalibrationInputError(
            "nothing was held out: calibrate with keep_better=True"
        )
    loss = params.loss
    return {
        "standby": _loss_error(
            held.windows,
            loss,
            cal.walk_tau(params.tank, held.standby_tau_h),
            params.tank,
        ),
        "gap_tau": _gap_error(
            held.gap_windows,
            params.loss,
            params.tank,
            params.tank.stratification_gap_tau_h,
        ),
        "compressor": _recovery_error(held.recoveries, params),
        "power_scale": _power_error(held.power_cycles, params),
        "cop": _cop_error(held.cop_cycles, params),
    }


def _judge(
    group: str,
    what: str,
    n_held: int,
    base: float | None,
    refit: float | None,
    *,
    refit_exists: bool = True,
    needed: int = cal.MIN_POWER_EVENTS,
) -> Judged:
    """Which of base and refit ``group`` keeps: the refit only when it
    scores better on the ``n_held`` latest ``what`` held out of it. No
    refit (fewer than ``needed`` ``what`` to make one) keeps the base."""
    if not refit_exists:
        return Judged(
            group,
            "base",
            base,
            None,
            n_held,
            f"kept the base: too few {what} to refit on ({needed} needed)",
        )
    if not n_held:
        return Judged(
            group,
            "base",
            None,
            None,
            0,
            f"kept the base: under {cal.MIN_RECOVERIES_FOR_SPLIT} {what} "
            "to judge a refit by",
        )
    if refit is None or (base is not None and base <= refit):
        scores = (
            f"{base:.3g} against the refit's {refit:.3g}"
            if base is not None and refit is not None
            else "the refit has no score"
        )
        return Judged(
            group,
            "base",
            base,
            refit,
            n_held,
            f"kept the base: it scores {scores} on the {n_held} latest {what}",
        )
    return Judged(group, "refit", base, refit, n_held, "")


def _keep_better(
    frame: pd.DataFrame, base: HeaterParams, recovery_air: str
) -> tuple[cal.Calibration, tuple[Judged, ...], HeldOut]:
    """``sim.calibration.calibrate``'s fits in its order, each group's
    latest evidence held out of its refit, and the refit kept only where
    it scores better there than ``base``. A group ``base`` lists as
    unfitted takes its refit as ``calibrate`` would."""
    unfitted = set(base.unfitted)
    judged: list[Judged] = []
    standby = cal.fit_standby(
        frame, base.tank.thermal_mass_btu_f, tank=base.tank, loss=base.loss
    )
    windows = sorted(standby.windows, key=lambda w: w.start)
    params = base
    # The gap's constant is judged first, its gaps opened by the base's
    # bottom loss, and the standby loss is then fitted and judged on the
    # constant kept, so a loss that wins does so on the gaps the
    # parameters returned will relax on. A group the base has not
    # fitted takes its refit unjudged, on all its evidence.
    gap_all = _gap_windows(windows)
    n_gap_held = 0 if "gap_tau" in unfitted else _split(len(gap_all))
    gap_train = gap_all[: len(gap_all) - n_gap_held]
    held_gaps = tuple(gap_all[len(gap_all) - n_gap_held :])
    both_unfitted = {"gap_tau", "standby"} <= unfitted
    # The gaps are opened by the loss the parameters will carry: the
    # base's, or where the base has not fitted one, the refit's, which
    # is taken unjudged. The constant is fitted and scored on it alike.
    opening = (
        cal.with_standby(base, standby).loss
        if "standby" in unfitted
        else base.loss
    )
    if both_unfitted:
        # Neither is judged: the joint fit ``calibrate`` takes, the
        # constant and the loss fitted in turn (``fit_standby``).
        tau, n_gap = standby.tau_gap_hours, standby.n_gap_windows
    else:
        tau, n_gap = cal.fit_gap_tau(
            [(w.gap_hours, w.gap_f) for w in gap_train],
            loss=opening,
            tank=base.tank,
        )
    if tau is None and "gap_tau" not in unfitted:
        judged.append(
            _judge(
                "gap_tau",
                "windows that open a gap",
                n_gap_held,
                _gap_error(
                    held_gaps,
                    opening,
                    base.tank,
                    base.tank.stratification_gap_tau_h,
                ),
                None,
                refit_exists=False,
                needed=cal.MIN_GAP_FIT_WINDOWS,
            )
        )
    elif tau is not None:
        if "gap_tau" in unfitted:
            params = replace(
                params,
                tank=replace(params.tank, stratification_gap_tau_h=tau),
            )
            unfitted.discard("gap_tau")
        else:
            j = _judge(
                "gap_tau",
                "windows that open a gap",
                n_gap_held,
                _gap_error(
                    held_gaps,
                    opening,
                    base.tank,
                    base.tank.stratification_gap_tau_h,
                ),
                _gap_error(held_gaps, opening, base.tank, tau),
            )
            judged.append(j)
            if j.kept == "refit":
                params = replace(
                    params,
                    tank=replace(params.tank, stratification_gap_tau_h=tau),
                )
    walk_tau = cal.walk_tau(params.tank)
    # The windows the loss can use (``loss_windows``), split.
    law = cal.loss_windows(windows)
    n_held = 0 if "standby" in unfitted else _split(len(law))
    train = law[: len(law) - n_held]
    held_windows = tuple(law[len(law) - n_held :])
    loss_fit = (
        cal.fit_loss(train, walk_tau, base.tank)
        if train and not both_unfitted
        else None
    )
    refit_standby = (
        (None if standby.ua_ref is None else standby)
        if both_unfitted
        else None
        if loss_fit is None
        else replace(
            standby,
            ua_ref=loss_fit.ua_ref,
            ua_exponent=loss_fit.ua_exponent,
            bottom_loss_btu_hr=loss_fit.bottom_loss_btu_hr,
            bottom_gate_f=loss_fit.bottom_gate_f,
            n_stratified=loss_fit.n_stratified,
            tau_gap_hours=None,
        )
    )
    if "standby" not in unfitted and refit_standby is None:
        judged.append(
            Judged(
                "standby",
                "base",
                None,
                None,
                0,
                "kept the base: no quiet window to refit on",
            )
        )
    elif refit_standby is not None and "standby" in unfitted:
        params = cal.with_standby(params, refit_standby)
        unfitted.discard("standby")
    elif refit_standby is not None:
        j = _judge(
            "standby",
            "quiet windows",
            n_held,
            _loss_error(held_windows, base.loss, walk_tau, base.tank),
            _loss_error(
                held_windows,
                cal.with_standby(base, refit_standby).loss,
                walk_tau,
                base.tank,
            ),
        )
        judged.append(j)
        if j.kept == "refit":
            params = cal.with_standby(params, refit_standby)
    fitted_standby = replace(
        standby if refit_standby is None else refit_standby,
        tau_gap_hours=tau,
        n_gap_windows=n_gap,
    )
    rows = cal.snapshots(frame, air=recovery_air)
    found = cal.recoveries(frame, air=recovery_air)
    reached = found.loc[found["reached"].astype(bool)] if len(found) else found
    compressor = cal.fit_compressor(
        reached, params.compressor, params.loss, tank=params.tank
    )
    _, held_recoveries = cal.split_recoveries(reached)
    if compressor is None and "compressor" not in unfitted:
        judged.append(
            _judge(
                "compressor",
                "reached recoveries",
                0,
                None,
                None,
                refit_exists=False,
                needed=cal.MIN_RECOVERIES,
            )
        )
    elif "compressor" in unfitted:
        if compressor is not None and not compressor.hit_bounds:
            params = cal.with_compressor(params, compressor)
            unfitted.discard("compressor")
    elif compressor is not None:
        if compressor.hit_bounds:
            judged.append(
                Judged(
                    "compressor",
                    "base",
                    _recovery_error(held_recoveries, params),
                    compressor.heldout_mae_minutes,
                    compressor.n_heldout,
                    "kept the base: the refit is pinned on a bound",
                )
            )
        else:
            j = _judge(
                "compressor",
                "reached recoveries",
                compressor.n_heldout,
                _recovery_error(held_recoveries, params),
                compressor.heldout_mae_minutes,
            )
            judged.append(j)
            if j.kept == "refit":
                params = cal.with_compressor(params, compressor)
    power = None
    held_power = held_cop = rows.iloc[0:0]

    def split_on(
        starts: Iterable[datetime | None],
    ) -> tuple[pd.DataFrame, pd.DataFrame, int]:
        """``rows`` without and with the latest of the cycles starting at
        ``starts`` (a fit's usable ones), and how many those are."""
        ordered = sorted(t for t in starts if t is not None)
        n = _split(len(ordered))
        held_at = rows["start_time"].isin(ordered[len(ordered) - n :])
        return rows.loc[~held_at], rows.loc[held_at], n

    if "compressor" not in unfitted and "power" in unfitted:
        power = cal.fit_power(rows, params)
        if power.power_scale is not None and power.cop_scale is not None:
            unfitted.discard("power")
        params = cal.with_power(params, power)
    elif "compressor" not in unfitted and len(rows):
        # Each fit's own usable cycles, in time order: the latest held
        # out of it.
        train_power, held_power, n_power_held = split_on(
            t for t, _, _ in cal.power_cycles(rows, params)
        )
        train_cop, held_cop, n_cop_held = split_on(
            c.start for c in cal.cop_cycles(rows, params)
        )
        scale, n_power = cal.fit_power_scale(train_power, params)
        cop, n_cop = cal.fit_cop_scale(train_cop, params)
        power = cal.PowerFit(
            power_scale=scale,
            n_power=n_power,
            cop_scale=None if cop is None else cop[0],
            startup_wh=None if cop is None else cop[1],
            cop_lift_coeff=None if cop is None else cop[3],
            lead_share=None if cop is None else cop[2],
            n_cop=n_cop,
        )
        refit = cal.with_power(params, power)
        j = _judge(
            "power_scale",
            "cycles",
            n_power_held,
            _power_error(held_power, params),
            _power_error(held_power, refit),
            refit_exists=scale is not None,
        )
        judged.append(j)
        if j.kept == "refit":
            params = replace(
                params,
                power=replace(params.power, power_scale=scale),
            )
        j = _judge(
            "cop",
            "cycles",
            n_cop_held,
            _cop_error(held_cop, params),
            _cop_error(held_cop, refit),
            refit_exists=cop is not None,
        )
        judged.append(j)
        if j.kept == "refit":
            params = replace(
                params,
                power=replace(
                    refit.power, power_scale=params.power.power_scale
                ),
            )
    elif "power" not in unfitted:
        # No refit to judge: no compressor to fit it over, or no cycles.
        why = (
            "kept the base: the compressor is not fitted"
            if "compressor" in unfitted
            else f"kept the base: too few cycles to refit on "
            f"({cal.MIN_POWER_EVENTS} needed)"
        )
        judged.extend(
            Judged(group, "base", None, None, 0, why)
            for group in ("power_scale", "cop")
        )
    params = replace(
        params,
        unfitted=tuple(t for t in UNFITTED_TERMS if t in unfitted),
    )
    held = HeldOut(
        held_windows,
        held_gaps,
        held_recoveries,
        held_power,
        held_cop,
        standby_tau_h=walk_tau,
    )
    return (
        cal.Calibration(params, fitted_standby, compressor, power, found),
        tuple(judged),
        held,
    )


def _runs_without_air(frame: pd.DataFrame, air: str) -> tuple[int, int]:
    """How many compressor runs ``frame`` holds, and how many of them
    have no reading in its ``air`` column: a recovery is timed against
    the air, so those are left out of the recoveries."""
    on = frame["compressor_on"].to_numpy(dtype=bool)
    if air in frame.columns:
        known = np.isfinite(frame[air].to_numpy(dtype=float))
    else:
        known = np.zeros(len(frame), dtype=bool)
    starts = np.flatnonzero(on & ~np.r_[False, on[:-1]])
    ends = np.flatnonzero(on & ~np.r_[on[1:], False]) + 1
    unread = sum(
        not known[a:b].any() for a, b in zip(starts, ends, strict=True)
    )
    return len(starts), int(unread)


def air_unread_note(done: Calibrated) -> str:
    """Why ``done``'s compressor runs without an air temperature are no
    recovery, or "" when every run had one."""
    if not done.n_runs_without_air:
        return ""
    why = (
        "no air given, and no heater ambient reading while the compressor runs"
        if done.air is None
        else "the air given does not cover them"
    )
    return (
        f"{done.n_runs_without_air} of {done.n_runs} compressor runs have "
        f"no air temperature ({why})"
    )


def _base(params: HeaterParams | Any) -> HeaterParams:
    if isinstance(params, HeaterParams):
        return params
    if not isinstance(params, Mapping):
        raise CalibrationInputError(
            "params is not a parameters document: not an object"
        )
    try:
        return params_from_document(cast(Mapping[str, Any], params))
    except (TypeError, ValueError) as e:
        raise CalibrationInputError(
            f"params is not a parameters document: {e}"
        ) from None


def _begin(
    air: Sequence[Reading] | None,
    ambient: float | None,
    params: HeaterParams | Any,
) -> tuple[HeaterParams, list[str]]:
    """The base to refit and the notes so far; the inputs checked before
    a history is read."""
    if air is not None and ambient is not None:
        raise CalibrationInputError("give air or ambient, not both")
    if params is None:
        return sim.default_params(), [DEFAULT_BASE_NOTE]
    return _base(params), []


def calibrate(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    *,
    air: Sequence[Reading] | None = None,
    ambient: float | None = None,
    humidity: Sequence[Reading] | None = None,
    params: HeaterParams | Any = None,
    record: RecordInputs | None = None,
    keep_better: bool = False,
) -> Calibrated:
    """``params`` (``HeaterParams`` or a parameters document; default
    the 65 gal defaults) refitted on ``readings``, the statuses the
    heater reported and when, taken once, in any order.

    The air where the heater stands is ``air`` (a sensor's readings) or
    ``ambient`` (a constant), in the preferred unit, and ``humidity``
    that air's, %. Given, the air is both the standby fit's and the
    recoveries'; without it, the standby loss is not fitted and
    recoveries use the heater's own reading while its compressor runs.
    ``record`` (``sim_home_assistant.RecordInputs``) is what a live
    source recorded over the history, °F: its air and humidity where
    none was given, and its draws and circulation runs, which make the
    quiet test exact. Its air is used only over the span it covers.

    Readings further apart than ``max_gap`` of them are a span nobody
    observed, and no fit spans one. Raises ``CalibrationInputError``
    for both ``air`` and ``ambient``, a ``params`` that is not a
    parameters document, or no readings.

    ``keep_better``: refine ``params`` without making it worse. Each
    group of terms (``GROUPS``) holds out its latest evidence (the last
    fifth, once it has 10 items) from its refit, and the refit replaces
    ``params``' values only where it scores better there (``score``).
    With fewer items, the group keeps ``params``' values. A group
    ``params`` lists as unfitted takes its refit as without it. Each
    judgement is in ``judged``, and in the report's reasons. Use it over
    a fit of this heater: the defaults are another heater's fit, and
    would be kept wherever the evidence is too little to judge by.
    """
    base, notes = _begin(air, ambient, params)
    frame = sa.history(readings)
    if frame.empty:
        raise CalibrationInputError("the history holds no statuses")
    return _fit(
        frame,
        base,
        notes,
        air,
        ambient,
        humidity,
        record,
        keep_better=keep_better,
    )


def calibrate_changes(
    rows: sa.ChangeRows,
    observed: Iterable[datetime],
    *,
    air: Sequence[Reading] | None = None,
    ambient: float | None = None,
    humidity: Sequence[Reading] | None = None,
    params: HeaterParams | Any = None,
    record: RecordInputs | None = None,
    notes: Iterable[str] = (),
    keep_better: bool = False,
) -> Calibrated:
    """``calibrate`` on a heater's values' changes (``rows``) instead of
    its statuses, with ``observed`` the instants it was heard from
    (``sim_adapters.change_history``; ``sim_home_assistant.
    read_heater_history`` reads both from Home Assistant). ``notes``
    open the result's (a reader's). The rows are counted in
    ``n_statuses``. Raises ``CalibrationInputError`` as ``calibrate``
    does, or for no ``observed`` instants. ``keep_better`` as for
    ``calibrate``.
    """
    base, more = _begin(air, ambient, params)
    heard = sorted(observed)
    # The gaps are the silences between the instants heard from: a
    # change inside one says nothing of the time around it.
    gap = max_gap(heard)
    dark = silences(heard, gap)
    frame = sa.change_history(
        replace(rows, outages=(*rows.outages, *dark)), heard
    )
    if frame.empty:
        raise CalibrationInputError("the history holds no observed instants")
    return _fit(
        frame,
        base,
        [*notes, *more],
        air,
        ambient,
        humidity,
        record,
        gaps=(gap, len(dark)),
        keep_better=keep_better,
    )


def _fit(
    frame: pd.DataFrame,
    base: HeaterParams,
    notes: list[str],
    air: Sequence[Reading] | None,
    ambient: float | None,
    humidity: Sequence[Reading] | None,
    record: RecordInputs | None,
    gaps: tuple[timedelta, int] | None = None,
    keep_better: bool = False,
) -> Calibrated:
    """The fits on ``frame`` (``history``'s or ``change_history``'s),
    with the air, the humidity, the record's spans and the gaps added:
    ``gaps``' longest spacing taken as observed and how many spans are
    longer, else the frame's own."""
    index = cast("pd.DatetimeIndex", frame.index)
    # Timestamps, which are datetimes.
    first, last = cast(datetime, index[0]), cast(datetime, index[-1])
    series: list[Reading] | None = None
    how: str | None = None
    covers: tuple[datetime, datetime] | None = None
    rh_covers: tuple[datetime, datetime] | None = None
    if air is not None:
        series, how = list(air), "readings"
    elif ambient is not None:
        series, how = [(first, ambient), (last, ambient)], "constant"
    elif record is not None and record.air:
        series = [(t, sa.temperature(v)) for t, v in _stepped(record.air)]
        how = "source"
        # A history's first reading is the value in force at its start,
        # and the last holds a reading's freshness past it.
        covers = (record.air[0][0], record.air[-1][0] + timedelta(hours=1))
    if humidity is None and record is not None and record.humidity:
        humidity = _stepped(record.humidity)
        rh_covers = (
            record.humidity[0][0],
            record.humidity[-1][0] + timedelta(hours=1),
        )
    drawing = circulating = None
    if record is not None:
        notes.extend(record.notes)
        if record.drawing is not None and record.circulating is not None:
            drawing, circulating = record.drawing, record.circulating
        elif record.drawing is not None or record.circulating is not None:
            # One alone would replace the heater's in-use flag for the
            # other in the recoveries' draw-free test (``snapshots``).
            notes.append(
                "the meter and the circulation are used together or not at "
                "all: with one unknown, the heater's own in-use flag stands in"
            )
    if humidity is None:
        # The fits' own default, given explicitly: an absent humidity
        # reaches the evaporator's dew point as NaN, which reads as 100 %.
        humidity = [(first, DEFAULT_HUMIDITY_PCT), (last, DEFAULT_HUMIDITY_PCT)]
    if gaps is None:
        gap = max_gap(index)
        n_gaps = len(silences(index, gap))
    else:
        gap, n_gaps = gaps
    sa.add_inputs(
        frame,
        air=series,
        humidity=humidity,
        drawing=drawing,
        circulating=circulating,
        max_gap=gap,
    )
    # A source's series, held past its ends or across an outage, would
    # stand for air nobody read: the air is left unknown there, and the
    # humidity takes the fits' own default.
    if covers is not None and record is not None:
        unseen = _unobserved(index, covers, record.air_outages)
        frame.loc[unseen, "air_f"] = float("nan")
        # And out of the standby fit, which would interpolate across,
        # and out of any recovery, which would take an older reading.
        frame["air_unobserved"] = unseen
        frame["excluded"] = frame["excluded"].to_numpy(dtype=bool) | unseen
    if rh_covers is not None and record is not None:
        frame.loc[
            _unobserved(index, rh_covers, record.humidity_outages),
            "humidity_pct",
        ] = DEFAULT_HUMIDITY_PCT
    if how is None:
        notes.append(NO_AIR_NOTE)
    recovery_air = "heater_air_f" if how is None else "air_f"
    n_runs, unread = _runs_without_air(frame, recovery_air)
    judged: tuple[Judged, ...] = ()
    held: HeldOut | None = None
    if keep_better:
        fitted, judged, held = _keep_better(frame, base, recovery_air)
    else:
        fitted = cal.calibrate(frame, base, recovery_air=recovery_air)
    done = Calibrated(
        fitted,
        how,
        len(frame),
        gap,
        n_gaps,
        tuple(notes),
        n_runs=n_runs,
        n_runs_without_air=unread,
        judged=judged,
        held=held,
    )
    if unread:
        done = replace(done, notes=(*done.notes, air_unread_note(done)))
    return done


# ── the report ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Term:
    """One line of the report: a fitted term, or why it kept the base's
    value."""

    name: str
    value: str
    samples: str
    error: str
    fitted: bool
    why: str = ""
    #: What a fitted value means, where it needs saying.
    note: str = ""


def _num(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}g}"


#: The report's terms of each group ``keep_better`` judges.
_GROUP_TERMS = {
    "standby": (
        "Standby loss (UA at ref ΔT, BTU/h·°F)",
        "Standby loss exponent",
        "Bottom loss (BTU/h)",
        "Bottom loss gate (°F)",
    ),
    "gap_tau": ("Zone gap time constant (h)",),
    "compressor": ("Compressor constant", "Evaporator approach (°F)"),
    "power_scale": ("Input power scale",),
    "cop": (
        "COP scale",
        "Start-up energy (Wh)",
        "COP lift coefficient (1/°F)",
    ),
}


def _values(params: HeaterParams) -> dict[str, float | None]:
    """The value each judged term holds in ``params``, by report name."""
    loss, power = params.loss, params.power
    values = (
        loss.ua_btu_hr_f,
        loss.ua_exponent,
        loss.bottom_loss_btu_hr,
        loss.bottom_gate_f,
        params.tank.stratification_gap_tau_h,
        params.compressor.compressor_constant,
        params.compressor.evap_approach_f,
        power.power_scale,
        power.cop_scale,
        power.startup_wh,
        power.cop_lift_coeff,
    )
    names = [n for group in _GROUP_TERMS.values() for n in group]
    return dict(zip(names, values, strict=True))


def _judged(terms: list[Term], done: Calibrated) -> list[Term]:
    """``terms`` with ``keep_better``'s judgements: a group that kept the
    base shows the base's values and why; one whose refit won says by
    how much."""
    values = _values(done.calibration.params)
    out = {t.name: t for t in terms}
    for j in done.judged:
        for name in _GROUP_TERMS[j.group]:
            t = out[name]
            if j.kept == "base":
                # The refit's error is not the kept values'; the reason
                # gives both scores.
                out[name] = replace(
                    t,
                    value=_num(values[name]),
                    error="-",
                    fitted=False,
                    why=j.why,
                    note="",
                )
            elif (
                j.kept == "refit"
                and t.fitted
                and j.base_error is not None
                and j.refit_error is not None
            ):
                # A plain fit's reason for having none does not hold
                # for a refit that won.
                out[name] = replace(
                    t,
                    fitted=True,
                    why="",
                    note=(f"{t.note}; " if t.note else "")
                    + f"scores {j.refit_error:.3g} against the base's "
                    f"{j.base_error:.3g} on the {j.n_held} latest held out",
                )
    return [out[t.name] for t in terms]


def report(done: Calibrated) -> list[Term]:
    """What each fit found, in the order they run, and with
    ``keep_better`` which of base and refit each group kept."""
    c = done.calibration
    s = c.standby
    kept = len(s.windows)
    if s.ua_ref is not None:
        why = ""
    elif done.air is None:
        why = "no air given"
    elif not s.n_quiet:
        why = f"no quiet window of {cal.MIN_QUIET_HOURS:g} h or more"
    else:
        why = (
            f"none of {s.n_quiet} quiet windows tracked the probes within "
            f"{cal.MAX_WINDOW_RMSE_F:g} °F"
        )
    rmse = (
        f"{max(w.rmse_f for w in s.windows):.2f} °F max rmse"
        if s.windows
        else "-"
    )
    bottom_why = (
        ""
        if s.bottom_gate_f is not None
        else f"{s.n_stratified} windows open stratified (a gap of "
        f"{cal.MIN_BOTTOM_FIT_GAP_F:g} °F or more); "
        f"{cal.MIN_BOTTOM_FIT_WINDOWS} needed"
    )
    terms = [
        Term(
            "Standby loss (UA at ref ΔT, BTU/h·°F)",
            _num(s.ua_ref),
            f"{kept} of {s.n_quiet} quiet windows",
            rmse,
            s.ua_ref is not None,
            why,
        ),
        Term(
            "Standby loss exponent",
            _num(s.ua_exponent),
            f"{kept} windows",
            "-",
            s.ua_exponent is not None,
            why,
            note=""
            if s.ua_exponent != 0.0
            else "0, a constant loss: under 4 windows, under two 20 °F "
            "bands, or the fit clamped to 0",
        ),
        Term(
            "Bottom loss (BTU/h)",
            _num(s.bottom_loss_btu_hr if s.bottom_gate_f is not None else None),
            f"{s.n_stratified} stratified windows",
            "-",
            s.bottom_gate_f is not None,
            why or bottom_why,
            note="heat leaving the lower zone, which the lower probe "
            "sees only while the tank is stratified",
        ),
        Term(
            "Bottom loss gate (°F)",
            _num(s.bottom_gate_f),
            f"{s.n_stratified} stratified windows",
            "-",
            s.bottom_gate_f is not None,
            why or bottom_why,
        ),
        Term(
            "Zone gap time constant (h)",
            _num(s.tau_gap_hours),
            f"{s.n_gap_windows} windows",
            "-",
            s.tau_gap_hours is not None,
            ""
            if s.tau_gap_hours is not None
            else why
            or f"{s.n_gap_windows} windows open a gap; "
            f"{cal.MIN_GAP_FIT_WINDOWS} needed",
        ),
    ]
    found = c.recoveries
    reached = len(found.loc[found["reached"].astype(bool)]) if len(found) else 0
    comp = c.compressor
    if comp is None:
        comp_why = (
            f"{reached} recoveries reached their target; "
            f"{cal.MIN_RECOVERIES} needed"
        )
        if done.n_runs_without_air:
            # The runs left out are the cause, not the heater.
            comp_why = f"{air_unread_note(done)}; {comp_why}"
    elif comp.hit_bounds:
        comp_why = "the fit is pinned on a bound: not applied"
    else:
        comp_why = ""
    comp_error = "-"
    if comp is not None:
        comp_error = f"{comp.mae_minutes:.1f} min mae"
        if comp.heldout_mae_minutes is not None:
            comp_error += (
                f", {comp.heldout_mae_minutes:.1f} on {comp.n_heldout} held out"
            )
    comp_samples = (
        f"{comp.n_fitted} recoveries" if comp else f"{reached} recoveries"
    )
    terms += [
        Term(
            "Compressor constant",
            _num(comp.compressor_constant if comp else None),
            comp_samples,
            comp_error,
            comp is not None and not comp.hit_bounds,
            comp_why,
        ),
        Term(
            "Evaporator approach (°F)",
            _num(comp.evap_approach_f if comp else None),
            comp_samples,
            comp_error,
            comp is not None and not comp.hit_bounds,
            comp_why,
        ),
    ]
    p = c.power
    # Power is fitted over the compressor the parameters hold: with
    # ``keep_better``, a base's when this refit has none.
    no_power = p is None and comp_why and "the compressor is not fitted"
    few = f"too few cycles ({cal.MIN_POWER_EVENTS} needed)"
    terms += [
        Term(
            "Input power scale",
            _num(p.power_scale if p else None),
            f"{p.n_power} cycles" if p else "-",
            "-",
            p is not None and p.power_scale is not None,
            no_power or ("" if p and p.power_scale is not None else few),
        ),
        Term(
            "COP scale",
            _num(p.cop_scale if p else None),
            f"{p.n_cop} cycles" if p else "-",
            "-",
            p is not None and p.cop_scale is not None,
            no_power or ("" if p and p.cop_scale is not None else few),
        ),
        Term(
            "Start-up energy (Wh)",
            _num(p.startup_wh if p else None),
            f"{p.n_cop} cycles" if p else "-",
            "-",
            p is not None and p.startup_wh is not None,
            no_power or ("" if p and p.startup_wh is not None else few),
        ),
        Term(
            "COP lift coefficient (1/°F)",
            _num(p.cop_lift_coeff if p else None),
            f"{p.n_cop} cycles" if p else "-",
            "-",
            p is not None and p.cop_lift_coeff is not None,
            no_power or ("" if p and p.cop_lift_coeff is not None else few),
        ),
    ]
    return _judged(terms, done) if done.judged else terms


# ── circulation, from the heat book's re-anchors ────────────────────


#: The fewest clean circulation runs, and the fewest days they span,
#: ``fit_circulation`` refits on.
MIN_CIRCULATION_RUNS = 10
MIN_CIRCULATION_DAYS = 3
#: Below this median meter flow over clean run minutes, gal/min, the
#: meter is taken not to pass the circulation (``meter_share`` 0).
METER_SEES_CIRCULATION_GPM = 0.05
#: The flow a run is priced at when the meter doesn't see it, gal/min,
#: without a base to take it from: the loss per gallon is fitted at it,
#: so the loss per run minute is what the book reads either way.
NOMINAL_CIRCULATION_GPM = 1.0
#: The shortest observed span ``fit_circulation`` books, hours.
_MIN_SEGMENT_H = 2.0
#: The largest loss per gallon ``fit_circulation`` fits, BTU/gal.
_MAX_LOSS_BTU_PER_GAL = 500.0


@dataclass(frozen=True)
class CirculationFit:
    """``fit_circulation``'s result: the circulation's terms to use
    (``params``), whether they are the base's or the refit's (``kept``,
    None with neither), the clean runs and the re-anchor pairs with a
    run in them it read, the held-out error of the terms kept (mean
    absolute, BTU; None with nothing held out), and why."""

    params: CirculationParams | None
    kept: str | None
    runs: int
    pairs: int
    error_btu: float | None
    why: str

    def as_document(self) -> dict[str, Any]:
        """The fit as a document: ``circulation`` the terms' fields
        (None without), and the rest as they are."""
        return {
            "circulation": None
            if self.params is None
            else {
                f.name: getattr(self.params, f.name)
                for f in dataclass_fields(self.params)
            },
            "kept": self.kept,
            "runs": self.runs,
            "pairs": self.pairs,
            "error_btu": self.error_btu,
            "why": self.why,
        }


def fit_circulation(
    rows: sa.ChangeRows,
    observed: Iterable[datetime],
    params: HeaterParams,
    *,
    flow: Iterable[tuple[datetime, float | None]],
    runs: Iterable[tuple[datetime, datetime]],
    inlet: Iterable[tuple[datetime, float]] = (),
    air: Iterable[tuple[datetime, float]] = (),
) -> CirculationFit:
    """The circulation's terms (``CirculationParams``) from a heater's
    values' changes and the instants it was heard from, its household
    meter's ``flow`` and the circulation pump's ``runs``, as
    ``sim_adapters.book_from_changes`` takes them, without a flow sensor
    on the pump. Like the rows, ``flow`` is gal/min and ``inlet`` and
    ``air`` °F, whatever the preferred units (``read_water_use``'s).
    ``params.circulation`` is the base.

    The book reads two things of a run per minute: the flow the meter
    sees, and the heat it takes. The meter's is the median over clean
    run minutes (no more than ``book.draw_gpm`` over the run's own
    median: no draw), taken as the run's flow with ``meter_share`` 1;
    under ``METER_SEES_CIRCULATION_GPM`` the meter doesn't pass the
    circulation, and a run is priced at the base's flow (else
    ``NOMINAL_CIRCULATION_GPM``) with ``meter_share`` 0. The loss per
    gallon is the one that books best from each quiet full tank to the
    next with a run between (``sim.calibration.RecordedBook``'s
    re-anchors up to ``max_anchor_age_h`` apart), the book's other terms
    held at ``params.book``, each run booked at its terms' flow
    (``sim_adapters.run_flow``), so the meter's excess over it is a
    draw. ``displaced_gal`` and ``run_gap_min`` are the base's, else
    ``site_example_params``': the book can't tell them.

    It refits only on ``MIN_CIRCULATION_RUNS`` clean runs over
    ``MIN_CIRCULATION_DAYS`` days. The latest fifth of the pairs (once
    there are 10) is held out of the refit, which replaces the base only
    when it books them no worse. A span the heater wasn't heard from
    (``sim_adapters.silences``, ``rows.outages``) breaks the book, and
    so does the meter's silence over ``sim_adapters.METER_MAX_GAP``, or
    before its first reading or after its last."""
    from nwp500.sim.defaults import SITE_CIRCULATION

    base = params.circulation
    book_p = params.book_terms()
    # A missing reading (None, NaN) is none.
    flow_rows = sorted(
        (t.astimezone(UTC), float(v))
        for t, v in flow
        if v is not None and math.isfinite(v)
    )
    run_spans = sorted((a.astimezone(UTC), b.astimezone(UTC)) for a, b in runs)
    inlets, airs = list(inlet), list(air)

    def keep(why: str, n_runs: int, n_pairs: int = 0) -> CirculationFit:
        return CirculationFit(
            base, None if base is None else "base", n_runs, n_pairs, None, why
        )

    if not flow_rows:
        return keep("no meter flow to read the runs by", 0)
    # The meter's flow over clean run minutes.
    gpm = sorted(flow_rows)
    times = [t for t, _ in gpm]
    clean: list[float] = []
    clean_runs: list[datetime] = []
    for a, b in run_spans:
        lo, hi = bisect_left(times, a), bisect_left(times, b)
        inside = [v for _, v in gpm[lo:hi]]
        if not inside:
            continue
        own = float(np.median(inside))
        quiet = [v for v in inside if v <= own + book_p.draw_gpm]
        if quiet:
            clean.extend(quiet)
            clean_runs.append(a)
    days = len({t.date() for t in clean_runs})
    if len(clean_runs) < MIN_CIRCULATION_RUNS or days < MIN_CIRCULATION_DAYS:
        return keep(
            f"{len(clean_runs)} clean runs over {days} days: "
            f"{MIN_CIRCULATION_RUNS} over {MIN_CIRCULATION_DAYS} needed",
            len(clean_runs),
        )
    seen = float(np.median(clean))
    template = base or SITE_CIRCULATION
    if seen >= METER_SEES_CIRCULATION_GPM:
        flow_gpm, share = seen, 1.0
    else:
        flow_gpm = (
            base.flow_gpm if base is not None else NOMINAL_CIRCULATION_GPM
        )
        share = 0.0
    refit = CirculationParams(
        displaced_gal=template.displaced_gal,
        flow_gpm=flow_gpm,
        loss_btu_per_gal=0.0,
        meter_share=share,
        run_gap_min=template.run_gap_min,
    )

    # The observed spans, each booked on its own.
    heard = sorted(t.astimezone(UTC) for t in observed)
    if not heard:
        return keep("the heater was never heard from", len(clean_runs))
    # And the meter's: a silence over ``METER_MAX_GAP``, or before its
    # first reading or after its last, would read as a quiet tank.
    beats = [t for t, _ in flow_rows]
    meter_dark = [
        (a, b)
        for a, b in itertools.pairwise([heard[0], *beats, heard[-1]])
        if b - a > sa.METER_MAX_GAP or not (beats[0] <= a and b <= beats[-1])
    ]
    dark = sorted(
        [
            *silences(heard, max_gap(heard)),
            *((a.astimezone(UTC), b.astimezone(UTC)) for a, b in rows.outages),
            *meter_dark,
        ]
    )
    segments: list[tuple[datetime, datetime]] = []
    at = heard[0]
    for a, b in dark:
        if a >= heard[-1]:
            break
        if a > at:
            segments.append((at, a))
        at = max(at, b)
    if heard[-1] > at:
        segments.append((at, heard[-1]))
    segments = [
        (a, b)
        for a, b in segments
        if (b - a).total_seconds() >= _MIN_SEGMENT_H * 3600
    ]

    def books(terms: CirculationParams) -> list[cal.RecordedBook]:
        with_terms = replace(params, circulation=terms)
        return [
            cal.RecordedBook(
                sa.book_steps_from_changes(
                    rows,
                    start=a,
                    end=b,
                    flow=flow_rows,
                    circulation=run_spans,
                    # A run at its own flow: the meter's excess over it
                    # is a draw.
                    circulation_flow=sa.run_flow(run_spans, terms.flow_gpm),
                    inlet=inlets,
                    air=airs,
                    params=with_terms,
                ),
                book_p,
                terms,
                start=a,
            )
            for a, b in segments
        ]

    fitted = books(refit)
    # Each pair with a run between: (its later anchor's instant, the
    # book, the pair).
    pairs = sorted(
        (
            (bk.at(a1), i, (a0, a1))
            for i, bk in enumerate(fitted)
            if len(bk.steps)
            for a0, a1 in bk.reanchors(book_p.max_anchor_age_h)
            if bk.circulated[a0:a1].sum() > 0
        ),
        key=lambda x: x[0],
    )
    if not pairs:
        return keep(
            "no quiet full tank on both sides of a run to book it by",
            len(clean_runs),
        )
    n_held = _split(len(pairs))
    train, held = pairs[: len(pairs) - n_held], pairs[len(pairs) - n_held :]

    def parts(
        bks: list[cal.RecordedBook], chosen: Sequence[Any]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Each pair's error without the run's loss, BTU, and the
        gallons it circulated: its error is the first less the loss
        per gallon times the second."""
        by_book: dict[int, list[tuple[int, int]]] = {}
        for _, i, pair in chosen:
            by_book.setdefault(i, []).append(pair)
        e0: list[float] = []
        gal: list[float] = []
        for i, these in by_book.items():
            bk = bks[i]
            e0.extend(float(e) for e in bk.errors(book_p, 0.0, these))
            gal.extend(float(bk.circulated[a0:a1].sum()) for a0, a1 in these)
        return np.array(e0), np.array(gal)

    e0, gal = parts(fitted, train)
    loss = min(_weighted_median(e0 / gal, gal), _MAX_LOSS_BTU_PER_GAL)
    loss = max(loss, 0.0)
    refit = replace(refit, loss_btu_per_gal=loss)
    note = (
        "displaced_gal and run_gap_min kept from the base"
        if base is not None
        else "displaced_gal and run_gap_min are one installation's "
        "(site_example_params): the book can't tell them"
    )
    how = (
        f"the meter sees {seen:.2f} gal/min of a run"
        if share
        else "the meter doesn't see the runs"
    )
    if not held:
        if base is None:
            return CirculationFit(
                refit,
                "refit",
                len(clean_runs),
                len(pairs),
                None,
                f"{how}; {len(pairs)} pairs, too few to hold any out; {note}",
            )
        return keep(
            f"{len(pairs)} pairs with a run: too few to judge a refit by "
            f"({cal.MIN_RECOVERIES_FOR_SPLIT} needed)",
            len(clean_runs),
            len(pairs),
        )
    e0h, galh = parts(fitted, held)
    refit_err = float(np.mean(np.abs(e0h - loss * galh)))
    if base is None:
        return CirculationFit(
            refit,
            "refit",
            len(clean_runs),
            len(pairs),
            refit_err,
            f"{how}; {note}",
        )
    b0, bgal = parts(books(base), held)
    base_err = float(np.mean(np.abs(b0 - base.loss_btu_per_gal * bgal)))
    if refit_err <= base_err:
        return CirculationFit(
            refit,
            "refit",
            len(clean_runs),
            len(pairs),
            refit_err,
            f"{how}; held out, {refit_err:.0f} BTU against the base's "
            f"{base_err:.0f}; {note}",
        )
    return CirculationFit(
        base,
        "base",
        len(clean_runs),
        len(pairs),
        base_err,
        f"held out, the base's {base_err:.0f} BTU against the refit's "
        f"{refit_err:.0f}",
    )


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """The value minimising the weighted sum of absolute deviations."""
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w)
    return float(v[np.searchsorted(cum, cum[-1] / 2.0)])
