"""Fit a heater's parameters to its recorded history.

The history is the statuses the heater reported, with when
(``nwp500.status_history``). ``calibrate`` builds the frame
``sim.calibration.calibrate`` takes (``sim_adapters.history``), marks
the spans nobody observed, adds the air where the heater stands and its
humidity, and runs the fits: the layered tank's (``sim.tank_fit``), then
the heat pump's on it; ``report`` says what each fit found, or why a
term kept the base's value.

The tank's fit needs the air where the heater stands: an air sensor's
readings beside it, a constant for a heater in conditioned space, or
what a Home Assistant source recorded
(``sim_home_assistant.record_inputs``). Without it, the fit reads the
heater's own reading while its compressor is idle, the cabinet's, less
``sim_adapters.IDLE_CABINET_WARM_F``; with no such reading, the tank
keeps the base's terms. Given, the same air is the recoveries' too.

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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from scipy.optimize import OptimizeResult, minimize_scalar

from nwp500 import sim
from nwp500 import sim_adapters as sa
from nwp500 import sim_score as ss
from nwp500.models import DeviceStatus
from nwp500.sim import calibration as cal
from nwp500.sim import heat_pump_fit as hpf
from nwp500.sim import tank_fit as tf
from nwp500.sim.history import FlowVolume
from nwp500.sim.params import (
    UNFITTED_TERMS,
    BookParams,
    CirculationParams,
    CompressorParams,
    HeaterParams,
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
    "MIN_TANK_EVENTS",
    "MIN_TANK_RECOVERIES",
    "TANK_EVALUATIONS",
    "TankCalibration",
    "BookTermsFit",
    "MIN_BOOK_PAIRS",
    "MIN_RUN_PAIRS",
    "GROUPS",
    "HeldOut",
    "Judged",
    "Term",
    "air_unread_note",
    "calibrate",
    "calibrate_changes",
    "fit_book",
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
#: The note when no air was given and the heater read none while its
#: compressor ran.
NO_AIR_NOTE = "no air given: the tank is not fitted"

#: The fewest quiet windows and draws the tank's terms are fitted on,
#: and the fewest recoveries where the condenser heats is fitted on with
#: them (``tank_fit.CONDENSER_TERMS``).
MIN_TANK_EVENTS = 10
MIN_TANK_RECOVERIES = 5
#: The tank's fit's most trials (``sim.tank_fit.fit``).
TANK_EVALUATIONS = 300


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
class TankCalibration:
    """The layered tank fitted on a history (``sim.tank_fit.fit``): the
    fit, None where there was none, and why; what it was fitted on, the
    quiet windows, the draws and the recoveries (``sim_score.events``,
    as the stratified tank's events), each started from the history's
    replay; and with ``keep_better``, how many of them were held out of
    it."""

    fit: tf.TankFit | None
    n_windows: int
    n_draws: int
    n_recoveries: int
    why: str = ""
    n_held: int = 0


@dataclass(frozen=True)
class Calibrated:
    """A calibration, and what ``calibrate`` chose along the way."""

    calibration: cal.Calibration
    #: The layered tank's fit, before the heat pump's, which prices its
    #: heat against the tank's loss.
    tank: TankCalibration
    #: How the air where the heater stands was given (``readings``,
    #: ``constant`` or ``source``), ``heater`` for the heater's own
    #: reading (no air given: the cabinet's for the tank's fit, the
    #: running one for the recoveries), or None.
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
GROUPS = ("tank", "heat_map", "power_map", "start_hold", "run_on")


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
    tank's quiet windows, draws and recoveries, with the record they
    start from (``sim.tank_fit.TankRecord``), and the heat pump's
    climbs, blocks, starts and run-ons (``heat_pump_fit.Evidence``)."""

    tank: tuple[tf.Coast, ...]
    record: tf.TankRecord | None
    heat_pump: hpf.Evidence


def _split(n: int) -> int:
    """How many of ``n`` items, the latest, are held out: as
    ``sim.calibration.split_recoveries`` holds out recoveries."""
    if n < cal.MIN_RECOVERIES_FOR_SPLIT:
        return 0
    return max(cal.MIN_HELDOUT, round(n * cal.HELDOUT_FRACTION))


def score(
    done: Calibrated,
    params: HeaterParams,
    *,
    map_: Callable[..., Iterable[Any]] = map,
) -> dict[str, float | None]:
    """Each group's error for ``params`` on the evidence ``done`` held
    out of its refits (``keep_better``), by ``GROUPS``; None where none
    was held out, or ``params`` cannot model all of it. Lower is better;
    each group's error is its own fit's:

    - ``tank``: the probes' RMSE over the held-out quiet windows, draws
      and recoveries, each started from the history's replay, °F
      (``sim.tank_fit.event_rmse``; ``map_`` maps over the events);
    - ``heat_map``: the heat's RMS error on the mixed climbs, weighted by
      their minutes, BTU/h (``heat_pump_fit.heat_map_error``);
    - ``power_map``: the power's RMS error on the climbs' metered
      blocks, W;
    - ``start_hold``: the hold's mean absolute error at the starts, min;
    - ``run_on``: the overshoot's mean absolute error at the stops, °F.

    Raises ``CalibrationInputError`` for a ``done`` not made with
    ``keep_better``."""
    held = done.held
    if held is None:
        raise CalibrationInputError(
            "nothing was held out: calibrate with keep_better=True"
        )
    return {
        "tank": tf.event_rmse(params, held.record, held.tank, map_=map_),
        "heat_map": hpf.heat_map_error(held.heat_pump.heat, params.compressor),
        "power_map": hpf.power_map_error(
            held.heat_pump.power, params.compressor
        ),
        "start_hold": hpf.start_hold_error(
            held.heat_pump.holds, params.compressor
        ),
        "run_on": hpf.overshoot_error(
            held.heat_pump.runs, params.controller.hp_stop_overshoot_f
        ),
    }


def _judge(
    group: str,
    what: str,
    n_held: int,
    base: float | None,
    refit: float | None,
    *,
    refit_exists: bool = True,
    needed: int = 0,
    n_all: int = 0,
) -> Judged:
    """Which of base and refit ``group`` keeps: the refit only when it
    scores better on the ``n_held`` latest ``what`` held out of it. No
    refit (fewer than ``needed`` ``what`` to make one) keeps the base.
    ``n_all``: every ``what`` there was, which says why none was held
    out when there were enough (they were one compressor run's)."""
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
        why = (
            f"kept the base: its {n_all} {what} are one compressor run's, "
            "none to hold out"
            if n_all >= cal.MIN_RECOVERIES_FOR_SPLIT
            else f"kept the base: under {cal.MIN_RECOVERIES_FOR_SPLIT} "
            f"{what} to judge a refit by"
        )
        return Judged(group, "base", None, None, 0, why)
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


#: A meter's draw: its onset, and the gallons it delivered.
MeterDraw = tuple[datetime, float]


@dataclass(frozen=True)
class _TankEvents:
    """A history's events as the stratified tank's (``sim_score``),
    each in time order, and the record they start from; None, and why,
    where the tank cannot be replayed."""

    record: tf.TankRecord | None
    windows: list[tf.Coast]
    draws: list[tf.Coast]
    recoveries: list[tf.Coast]
    why: str = ""


def _tank_events(
    ready: Prepared, params: HeaterParams, draws: Sequence[MeterDraw]
) -> _TankEvents:
    """``ready``'s quiet windows, a meter's ``draws`` and its recoveries
    as the stratified tank's events (``sim_score.layer_coasts``,
    ``layer_recoveries``), on its replay (``sim.tank_fit.tank_record``),
    which needs the air where the heater stands."""
    frame = ready.frame
    if "air_f" not in frame.columns:
        return _TankEvents(None, [], [], [], "no air given")
    if not bool(frame["air_f"].notna().any()):
        return _TankEvents(
            None, [], [], [], "no reading of the air where the heater stands"
        )
    found = ss.events(ready, draws=draws)
    record = tf.tank_record(frame, draws)
    windows, drawn = ss.layer_coasts(found)
    climbs = ss.layer_recoveries(found, params, record)

    def ordered(coasts: list[tf.Coast]) -> list[tf.Coast]:
        return sorted(coasts, key=lambda c: c.start)

    return _TankEvents(
        record, ordered(windows), ordered(drawn), ordered(climbs)
    )


def _fit_tank(
    params: HeaterParams,
    found: _TankEvents,
    map_: Callable[..., Iterable[Any]],
) -> tuple[tf.TankFit | None, str]:
    """The tank's terms (``tank_fit.TERMS``) fitted from ``params``' on
    ``found``'s quiet windows and draws, and with enough recoveries,
    where the condenser heats (``CONDENSER_TERMS``) with them on those
    too: the condenser places the heat each window's replay starts
    from. None, and why, with too few events."""
    if found.record is None:
        return None, found.why
    coasts = [*found.windows, *found.draws]
    if len(coasts) < MIN_TANK_EVENTS:
        return None, (
            f"{len(coasts)} quiet windows and draws; {MIN_TANK_EVENTS} needed"
        )
    terms = tf.TERMS
    if len(found.recoveries) >= MIN_TANK_RECOVERIES:
        coasts += found.recoveries
        terms = tf.TERMS + tf.CONDENSER_TERMS
    fit = tf.fit(
        params,
        found.record,
        coasts,
        terms=terms,
        map_=map_,
        max_evaluations=TANK_EVALUATIONS,
    )
    return fit, ""


def _tank_calibration(
    fit: tf.TankFit | None, found: _TankEvents, why: str, n_held: int = 0
) -> TankCalibration:
    return TankCalibration(
        fit,
        len(found.windows),
        len(found.draws),
        len(found.recoveries),
        why,
        n_held,
    )


def _keep_better_tank(
    ready: Prepared,
    base: HeaterParams,
    draws: Sequence[MeterDraw],
    unfitted: set[str],
    judged: list[Judged],
    map_: Callable[..., Iterable[Any]],
) -> tuple[
    HeaterParams, TankCalibration, tuple[tf.Coast, ...], tf.TankRecord | None
]:
    """The tank's terms refitted on all but the latest of its events
    (its quiet windows, draws and recoveries together, ``_split``), and
    kept only where they score better on those (``score``'s ``tank``).
    With too few events to hold any out, the base is kept without a
    fit. With the tank unfitted in ``base``, the refit is taken
    unjudged, on every event. Returns the parameters, the fit (its
    counts the events it was fitted on), the events held out and the
    record they start from; ``unfitted`` and ``judged`` are updated in
    place."""
    found = _tank_events(ready, base, draws)
    open_tank = "tank" in unfitted
    what = "quiet windows, draws and recoveries"
    events = sorted(
        [*found.windows, *found.draws, *found.recoveries],
        key=lambda c: c.start,
    )
    n = 0 if open_tank else _split(len(events))
    held = events[len(events) - n :]
    out = {id(c) for c in held}

    def kept(kind: list[tf.Coast]) -> list[tf.Coast]:
        return [c for c in kind if id(c) not in out]

    train = replace(
        found,
        windows=kept(found.windows),
        draws=kept(found.draws),
        recoveries=kept(found.recoveries),
    )
    if found.record is not None and not open_tank and not held:
        # Nothing to judge a refit by: not worth the fit's minutes.
        j = _judge("tank", what, 0, None, None)
        judged.append(j)
        return base, _tank_calibration(None, train, j.why), (), found.record
    fit, why = _fit_tank(base, train, map_)
    params = base
    if fit is None:
        if not open_tank:
            judged.append(
                Judged(
                    "tank",
                    "base",
                    None,
                    None,
                    len(held),
                    f"kept the base: {why}",
                )
            )
    elif open_tank:
        params = fit.params
        unfitted.discard("tank")
    else:
        j = _judge(
            "tank",
            what,
            len(held),
            tf.event_rmse(base, found.record, held, map_=map_),
            tf.event_rmse(fit.params, found.record, held, map_=map_),
        )
        judged.append(j)
        if j.kept == "refit":
            params = fit.params
    return (
        params,
        _tank_calibration(fit, train, why, len(held)),
        tuple(held),
        found.record,
    )


def _keep_better(
    ready: Prepared,
    base: HeaterParams,
    draws: Sequence[MeterDraw],
    map_: Callable[..., Iterable[Any]],
) -> tuple[cal.Calibration, TankCalibration, tuple[Judged, ...], HeldOut]:
    """The fits in ``calibrate``'s order, the tank's then the heat
    pump's, each group's latest evidence held out of its refit, and the
    refit kept only where it scores better there than ``base``. A group
    ``base`` lists as unfitted takes its refit as ``calibrate`` would."""
    frame, recovery_air = ready.frame, ready.recovery_air
    unfitted = set(base.unfitted)
    judged: list[Judged] = []
    params, tank, held_tank, record = _keep_better_tank(
        ready, base, draws, unfitted, judged, map_
    )
    found = cal.recoveries(frame, air=recovery_air)
    params, pump, held_pump = _keep_better_heat_pump(
        hpf.evidence(frame, params, air=recovery_air),
        params,
        unfitted,
        judged,
    )
    params = replace(
        params,
        unfitted=tuple(t for t in UNFITTED_TERMS if t in unfitted),
    )
    return (
        cal.Calibration(params, pump, found),
        tank,
        tuple(judged),
        HeldOut(held_tank, record, held_pump),
    )


def _split_frame(
    rows: pd.DataFrame, hold_out: bool
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``rows`` (in time order) without and with their latest
    (``_split``), or all of them and none when not ``hold_out``. Rows
    of one compressor run (``cycle``) fall on one side: the latest runs
    holding at least that many rows, short of every run."""
    n = _split(len(rows)) if hold_out else 0
    if "cycle" not in rows.columns:
        return rows.iloc[: len(rows) - n], rows.iloc[len(rows) - n :]
    runs = list(dict.fromkeys(rows["cycle"]))
    per_run: dict[object, int] = {
        run: int(k) for run, k in rows["cycle"].value_counts().items()
    }
    late: list[object] = []
    count = 0
    for run in reversed(runs[1:]):
        if count >= n:
            break
        late.append(run)
        count += per_run[run]
    held = rows["cycle"].isin(late)
    return rows.loc[~held], rows.loc[held]


def _keep_better_heat_pump(
    found: hpf.Evidence,
    params: HeaterParams,
    unfitted: set[str],
    judged: list[Judged],
) -> tuple[HeaterParams, hpf.HeatPumpFit, hpf.Evidence]:
    """The heat pump's groups (``heat_map``, ``power_map``,
    ``start_hold``, ``run_on``), each refitted on all but its latest
    evidence and kept only where it scores better there. The maps are
    judged one at a time, the heat's with the base's power and the
    power's with the heat kept, and a plane that would leave the pair
    claiming what no heat pump does is not applied
    (``heat_pump_fit.violations``). The groups
    of a term ``params`` lists as unfitted (``compressor`` for the heat,
    the hold and the run-on, ``power`` for the power) take their refit
    unjudged, on all their evidence. Returns the parameters, the refit,
    and the evidence held out; ``unfitted`` and ``judged`` are updated
    in place."""
    open_heat = "compressor" in unfitted
    open_power = "power" in unfitted
    heat, held_heat = _split_frame(found.heat, not open_heat)
    power, held_power = _split_frame(found.power, not open_power)
    holds, held_holds = _split_frame(found.holds, not open_heat)
    runs, held_runs = _split_frame(found.runs, not open_heat)
    held = hpf.Evidence(held_heat, held_power, held_holds, held_runs)
    base = params.compressor
    refit = hpf.fit_heat_pump(hpf.Evidence(heat, power, holds, runs), base)
    # What each plane claims with the other it would be applied with.
    found_claims: dict[str, tuple[str, ...]] = {}

    def plane(
        group: str,
        what: str,
        term: str,
        fitted: hpf.Plane | None,
        n_held: int,
        error: Callable[[CompressorParams], float | None],
        candidate: CompressorParams,
        needed: int,
        n_all: int,
    ) -> bool:
        """Whether ``group``'s refit plane is taken."""
        if fitted is None:
            if term not in unfitted:
                judged.append(
                    _judge(
                        group,
                        what,
                        n_held,
                        error(base),
                        None,
                        refit_exists=False,
                        needed=needed,
                    )
                )
            return False
        claims = hpf.violations(candidate)
        found_claims[group] = claims
        if claims:
            if term not in unfitted:
                why = (
                    "kept the base: the refit claims what no heat pump "
                    f"does ({', '.join(claims)})"
                )
                judged.append(
                    Judged(group, "base", error(base), None, n_held, why)
                )
            return False
        if term in unfitted:
            unfitted.discard(term)
            return True
        j = _judge(
            group, what, n_held, error(base), error(candidate), n_all=n_all
        )
        judged.append(j)
        return j.kept == "refit"

    take_heat = plane(
        "heat_map",
        "recovery climbs",
        "compressor",
        refit.heat,
        len(held_heat),
        lambda c: hpf.heat_map_error(held_heat, c),
        hpf.with_planes(base, refit.heat, None),
        hpf.MIN_HEAT_STRETCHES,
        len(found.heat),
    )
    heated = hpf.with_planes(base, refit.heat if take_heat else None, None)
    take_power = plane(
        "power_map",
        "metered climb blocks",
        "power",
        refit.power,
        len(held_power),
        lambda c: hpf.power_map_error(held_power, c),
        hpf.with_planes(heated, None, refit.power),
        hpf.MIN_POWER_BLOCKS,
        len(found.power),
    )
    compressor = hpf.with_planes(
        heated, None, refit.power if take_power else None
    )
    controller = params.controller
    if refit.start_hold_min is None:
        if not open_heat:
            judged.append(
                _judge(
                    "start_hold",
                    "starts",
                    len(held_holds),
                    hpf.start_hold_error(held_holds, base),
                    None,
                    refit_exists=False,
                    needed=hpf.MIN_BAND_STARTS,
                )
            )
    else:
        with_hold = replace(compressor, start_hold_min=refit.start_hold_min)
        j = (
            None
            if open_heat
            else _judge(
                "start_hold",
                "starts",
                len(held_holds),
                hpf.start_hold_error(held_holds, base),
                hpf.start_hold_error(held_holds, with_hold),
            )
        )
        if j is not None:
            judged.append(j)
        if j is None or j.kept == "refit":
            compressor = with_hold
    if refit.overshoot_f is None:
        if not open_heat:
            judged.append(
                _judge(
                    "run_on",
                    "run-ons",
                    len(held_runs),
                    hpf.overshoot_error(
                        held_runs, controller.hp_stop_overshoot_f
                    ),
                    None,
                    refit_exists=False,
                    needed=hpf.MIN_RUN_ONS,
                )
            )
    else:
        j = (
            None
            if open_heat
            else _judge(
                "run_on",
                "run-ons",
                len(held_runs),
                hpf.overshoot_error(held_runs, controller.hp_stop_overshoot_f),
                hpf.overshoot_error(held_runs, refit.overshoot_f),
            )
        )
        if j is not None:
            judged.append(j)
        if j is None or j.kept == "refit":
            controller = replace(
                controller, hp_stop_overshoot_f=refit.overshoot_f
            )
    refit = replace(
        refit,
        heat_violations=found_claims.get("heat_map", ()),
        power_violations=found_claims.get("power_map", ()),
    )
    return (
        replace(params, compressor=compressor, controller=controller),
        refit,
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
        if done.air in (None, "heater")
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
    draws: Sequence[MeterDraw] = (),
    keep_better: bool = False,
    map_: Callable[..., Iterable[Any]] = map,
) -> Calibrated:
    """``params`` (``HeaterParams`` or a parameters document; default
    the 65 gal defaults) refitted on ``readings``, the statuses the
    heater reported and when, taken once, in any order: the layered
    tank first (``TankCalibration``), then the heat pump, its heat
    priced against the tank's loss.

    The air where the heater stands is ``air`` (a sensor's readings) or
    ``ambient`` (a constant), in the preferred unit, and ``humidity``
    that air's, %. Given, the air is both the tank's and the
    recoveries'; without it, the tank is fitted on the heater's idle
    reading less ``sim_adapters.IDLE_CABINET_WARM_F``, and recoveries
    use the heater's own reading while its compressor runs.
    ``record`` (``sim_home_assistant.RecordInputs``) is what a live
    source recorded over the history, °F: its air and humidity where
    none was given, and its draws and circulation runs, which make the
    quiet test exact. Its air is used only over the span it covers.
    ``draws`` are a meter's, ``(onset, delivered gallons)``: the tank's
    replay takes them, and its terms are fitted on the hours after them
    too. ``map_(function, a, b, c)`` maps the tank's fit over its
    events: a process pool's ``map`` spreads it (a fit on months of
    history takes minutes on one).

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
        draws=draws,
        keep_better=keep_better,
        map_=map_,
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
    draws: Sequence[MeterDraw] = (),
    keep_better: bool = False,
    map_: Callable[..., Iterable[Any]] = map,
) -> Calibrated:
    """``calibrate`` on a heater's values' changes (``rows``) instead of
    its statuses, with ``observed`` the instants it was heard from
    (``sim_adapters.change_history``; ``sim_home_assistant.
    read_heater_history`` reads both from Home Assistant). ``notes``
    open the result's (a reader's). The rows are counted in
    ``n_statuses``. Raises ``CalibrationInputError`` as ``calibrate``
    does, or for no ``observed`` instants. ``draws``, ``keep_better``
    and ``map_`` as for ``calibrate``.
    """
    base, more = _begin(air, ambient, params)
    frame, gaps = _change_frame(rows, observed)
    return _fit(
        frame,
        base,
        [*notes, *more],
        air,
        ambient,
        humidity,
        record,
        gaps=gaps,
        draws=draws,
        keep_better=keep_better,
        map_=map_,
    )


def _air_from_cabinet(
    frame: pd.DataFrame,
) -> tuple[int, int, float] | None:
    """With no air given, the heater's own as ``frame``'s air over the
    quiet windows: its reading while the compressor is idle, the
    cabinet's, less ``sim_adapters.IDLE_CABINET_WARM_F``. A quiet window
    with no such reading throughout is marked ``air_unobserved``, out of
    the tank's fit. How many windows were read, of how many, and their
    share of the quiet hours; None with no such reading."""
    if "heater_cabinet_f" not in frame.columns:
        return None
    cabinet = frame["heater_cabinet_f"].to_numpy(dtype=float)
    if not np.isfinite(cabinet).any():
        return None
    seconds = np.array(
        [t.timestamp() for t in cast("pd.DatetimeIndex", frame.index)]
    )
    usable = np.zeros(len(frame), dtype=bool)
    unseen = np.zeros(len(frame), dtype=bool)
    quiet = cal.quiet_windows(frame)
    n = 0
    hours = kept = 0.0
    for start, end in quiet:
        hours += (end - start).total_seconds()
        inside = (seconds >= start.timestamp()) & (seconds < end.timestamp())
        if np.isfinite(cabinet[inside]).all():
            usable |= inside
            n += 1
            kept += (end - start).total_seconds()
        else:
            unseen |= inside
    frame["air_f"] = np.where(usable, cabinet - sa.IDLE_CABINET_WARM_F, np.nan)
    frame["air_unobserved"] = unseen
    return n, len(quiet), kept / hours if hours else 0.0


@dataclass(frozen=True)
class Prepared:
    """A history as the fits take it: ``history``'s or
    ``change_history``'s frame with the air, the humidity, the record's
    spans and the gaps added (``sim_adapters.add_inputs``)."""

    frame: pd.DataFrame
    #: How the air was given (``Calibrated.air``).
    air: str | None
    #: The frame's column a recovery reads its air from.
    recovery_air: str
    #: Readings further apart than this are unobserved, and how many
    #: such spans the history has.
    max_gap: timedelta
    n_gaps: int
    notes: tuple[str, ...]


def prepare(
    readings: Iterable[tuple[datetime, DeviceStatus]],
    *,
    air: Sequence[Reading] | None = None,
    ambient: float | None = None,
    humidity: Sequence[Reading] | None = None,
    record: RecordInputs | None = None,
) -> Prepared:
    """``readings`` as ``calibrate`` fits them: the frame a scorer reads
    the same history from (``sim_score``). Raises
    ``CalibrationInputError`` as ``calibrate`` does."""
    if air is not None and ambient is not None:
        raise CalibrationInputError("give air or ambient, not both")
    frame = sa.history(readings)
    if frame.empty:
        raise CalibrationInputError("the history holds no statuses")
    return _prepare(frame, [], air, ambient, humidity, record)


def prepare_changes(
    rows: sa.ChangeRows,
    observed: Iterable[datetime],
    *,
    air: Sequence[Reading] | None = None,
    ambient: float | None = None,
    humidity: Sequence[Reading] | None = None,
    record: RecordInputs | None = None,
) -> Prepared:
    """``prepare`` on a heater's values' changes, as
    ``calibrate_changes`` takes them."""
    if air is not None and ambient is not None:
        raise CalibrationInputError("give air or ambient, not both")
    frame, gaps = _change_frame(rows, observed)
    return _prepare(frame, [], air, ambient, humidity, record, gaps)


def _change_frame(
    rows: sa.ChangeRows, observed: Iterable[datetime]
) -> tuple[pd.DataFrame, tuple[timedelta, int]]:
    """``change_history``'s frame, with the silences between the
    instants heard from as outages, and the gaps they make."""
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
    return frame, (gap, len(dark))


def _fit(
    frame: pd.DataFrame,
    base: HeaterParams,
    notes: list[str],
    air: Sequence[Reading] | None,
    ambient: float | None,
    humidity: Sequence[Reading] | None,
    record: RecordInputs | None,
    gaps: tuple[timedelta, int] | None = None,
    draws: Sequence[MeterDraw] = (),
    keep_better: bool = False,
    map_: Callable[..., Iterable[Any]] = map,
) -> Calibrated:
    """The fits on ``frame`` (``history``'s or ``change_history``'s),
    prepared (``_prepare``)."""
    ready = _prepare(frame, notes, air, ambient, humidity, record, gaps)
    frame, how, recovery_air = ready.frame, ready.air, ready.recovery_air
    gap, n_gaps = ready.max_gap, ready.n_gaps
    n_runs, unread = _runs_without_air(frame, recovery_air)
    judged: tuple[Judged, ...] = ()
    held: HeldOut | None = None
    if keep_better:
        fitted, tank, judged, held = _keep_better(ready, base, draws, map_)
    else:
        found = _tank_events(ready, base, draws)
        fit, why = _fit_tank(base, found, map_)
        tank = _tank_calibration(fit, found, why)
        start = base if fit is None else fit.params
        fitted = cal.calibrate(frame, start, recovery_air=recovery_air)
        unfitted = set(fitted.params.unfitted) - {"tank"}
        if fit is None:
            unfitted.add("tank")
        fitted = replace(
            fitted,
            params=replace(
                fitted.params,
                unfitted=tuple(t for t in UNFITTED_TERMS if t in unfitted),
            ),
        )
    done = Calibrated(
        fitted,
        tank,
        how,
        len(frame),
        gap,
        n_gaps,
        ready.notes,
        n_runs=n_runs,
        n_runs_without_air=unread,
        judged=judged,
        held=held,
    )
    if unread:
        done = replace(done, notes=(*done.notes, air_unread_note(done)))
    return done


def _prepare(
    frame: pd.DataFrame,
    notes: list[str],
    air: Sequence[Reading] | None,
    ambient: float | None,
    humidity: Sequence[Reading] | None,
    record: RecordInputs | None,
    gaps: tuple[timedelta, int] | None = None,
) -> Prepared:
    """``frame`` with the air, the humidity, the record's spans and the
    gaps added: ``gaps``' longest spacing taken as observed and how many
    spans are longer, else the frame's own."""
    notes = list(notes)
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
                "the draws and the circulation are used together or not at "
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
    recovery_air = "heater_air_f" if how is None else "air_f"
    if covers is not None and record is not None:
        unseen = _unobserved(index, covers, record.air_outages)
        frame.loc[unseen, "air_f"] = float("nan")
        # And out of the tank's fit, which would interpolate across.
        frame["air_unobserved"] = unseen
        if "heater_air_f" in frame.columns and bool(
            frame["heater_air_f"].notna().any()
        ):
            # A recovery there reads the heater's own air instead.
            frame["recovery_air_f"] = frame["air_f"].where(
                ~unseen, frame["heater_air_f"]
            )
            recovery_air = "recovery_air_f"
            # A recovery reads its air from its own run (``snapshots``),
            # and is no recovery with none there: nothing to take out.
            no_air = np.zeros(len(frame), dtype=bool)
        else:
            no_air = unseen
        # Out of any recovery that would take an older reading.
        frame["excluded"] = frame["excluded"].to_numpy(dtype=bool) | no_air
    if rh_covers is not None and record is not None:
        frame.loc[
            _unobserved(index, rh_covers, record.humidity_outages),
            "humidity_pct",
        ] = DEFAULT_HUMIDITY_PCT
    if how is None:
        read = _air_from_cabinet(frame)
        if read is None:
            notes.append(NO_AIR_NOTE)
        else:
            how = "heater"
            n, of, share = read
            notes.append(
                "no air given: the tank is fitted on the heater's own "
                "reading while its compressor is idle, less "
                f"{sa.IDLE_CABINET_WARM_F:g} °F for the cabinet's warmth "
                f"({n} of {of} quiet windows, {share:.0%} of their hours, "
                "have it throughout)"
            )
    return Prepared(frame, how, recovery_air, gap, n_gaps, tuple(notes))


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
    "tank": (
        "Sides' loss (UA, BTU/h·°F)",
        "Bottom's loss (UA, BTU/h·°F)",
        "Top's loss (UA, BTU/h·°F)",
        "Column conductance (BTU/h·°F)",
        "Lower probe height (share)",
        "Lower probe spread (gal)",
        "Lower probe offset (°F)",
        "Upper probe height (share)",
        "Upper probe spread (gal)",
        "Inlet mixing (gal)",
        "Condenser span (share)",
    ),
    "heat_map": (
        "Heat at 65 °F air, 120 °F water (BTU/h)",
        "Heat per °F of air (BTU/h)",
        "Heat per °F of water (BTU/h)",
    ),
    "power_map": (
        "Power at 65 °F air, 120 °F water (W)",
        "Power per °F of air (W)",
        "Power per °F of water (W)",
    ),
    "start_hold": ("Start hold by time off (min)",),
    "run_on": ("Run-on overshoot (°F)",),
}


def _holds(values: Sequence[float]) -> str:
    return "/".join(f"{v:g}" for v in values)


def _values(params: HeaterParams) -> dict[str, str]:
    """The value each judged term holds in ``params``, by report name,
    as the report shows it."""
    c = params.compressor
    values = (
        *_tank_values(params),
        _num(c.heat_btu_h, 4),
        _num(c.heat_btu_h_per_air_f),
        _num(c.heat_btu_h_per_water_f),
        _num(c.power_w),
        _num(c.power_w_per_air_f),
        _num(c.power_w_per_water_f),
        _holds(c.start_hold_min),
        _num(params.controller.hp_stop_overshoot_f),
    )
    names = [n for group in _GROUP_TERMS.values() for n in group]
    return dict(zip(names, values, strict=True))


def _tank_values(params: HeaterParams) -> tuple[str, ...]:
    """The tank's terms in ``params``, as the report shows them."""
    t, loss = params.tank, params.loss
    low, high = t.condenser_span
    return (
        _num(loss.ua_side_btu_hr_f),
        _num(loss.ua_bottom_btu_hr_f),
        _num(loss.ua_top_btu_hr_f),
        _num(t.conductance_btu_hr_f),
        _num(t.lower_probe_height),
        _num(t.lower_probe_spread_gal),
        _num(t.lower_probe_offset_f),
        _num(t.upper_probe_height),
        _num(t.upper_probe_spread_gal),
        _num(t.inlet_mix_gal),
        f"{low:.3g}-{high:.3g}",
    )


#: Each report line of the tank's (``_GROUP_TERMS``), by the fit's
#: term (``tank_fit.TERMS``, ``CONDENSER_TERMS``).
_TANK_TERM_LINES = {
    "ua_side_btu_hr_f": 0,
    "ua_bottom_btu_hr_f": 1,
    "ua_top_btu_hr_f": 2,
    "conductance_btu_hr_f": 3,
    "lower_probe_height": 4,
    "lower_probe_spread_gal": 5,
    "lower_probe_offset_f": 6,
    "upper_probe_height": 7,
    "upper_probe_spread_gal": 8,
    "inlet_mix_gal": 9,
    "condenser_low": 10,
    "condenser_width": 10,
}


def _tank_terms(done: Calibrated) -> list[Term]:
    """The report's lines of the tank's fit (``TankCalibration``)."""
    t = done.tank
    fit = t.fit
    names = _GROUP_TERMS["tank"]
    values = _tank_values(done.calibration.params)
    fitted = (
        set() if fit is None else {_TANK_TERM_LINES[name] for name in fit.terms}
    )
    bound = (
        set()
        if fit is None
        else {_TANK_TERM_LINES[name] for name in fit.on_bound}
    )
    samples = (
        f"{t.n_windows} windows, {t.n_draws} draws, {t.n_recoveries} recoveries"
    )
    error = (
        "-"
        if fit is None
        else f"{fit.rmse_before:.2f} → {fit.rmse_after:.2f} °F rms"
    )
    if fit is None:
        why = t.why
    else:
        why = f"{t.n_recoveries} recoveries; {MIN_TANK_RECOVERIES} needed"
    return [
        Term(
            name,
            values[i],
            samples,
            error if i == 0 else "-",
            i in fitted,
            "" if i in fitted else why,
            note="on its bound" if i in bound else "",
        )
        for i, name in enumerate(names)
    ]


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
                    value=values[name],
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
    terms = _tank_terms(done)
    pump = c.heat_pump
    cp = c.params.compressor

    def claims(found: tuple[str, ...]) -> str:
        return (
            "the fit claims what no heat pump does "
            f"({', '.join(found)}): not applied"
            if found
            else ""
        )

    air_why = air_unread_note(done) if done.n_runs_without_air else ""

    def needs(n: int, what: str, needed: int) -> str:
        why = f"{n} {what}; {needed} needed"
        return f"{air_why}; {why}" if air_why else why

    heat_why = claims(pump.heat_violations) or (
        ""
        if pump.heat is not None
        else needs(
            pump.n_heat,
            "draw-free climbs with the tank mixed",
            hpf.MIN_HEAT_STRETCHES,
        )
    )
    power_why = claims(pump.power_violations) or (
        ""
        if pump.power is not None
        else needs(pump.n_power, "metered climb blocks", hpf.MIN_POWER_BLOCKS)
    )
    heat_error = (
        "-" if pump.heat_error is None else f"{pump.heat_error:.0f} BTU/h rms"
    )
    power_error = (
        "-" if pump.power_error is None else f"{pump.power_error:.1f} W rms"
    )
    heat_ok = pump.heat is not None and not pump.heat_violations
    power_ok = pump.power is not None and not pump.power_violations
    terms += [
        Term(
            name,
            _num(value, digits),
            f"{pump.n_heat} climbs",
            heat_error if i == 0 else "-",
            heat_ok,
            heat_why,
        )
        for i, (name, value, digits) in enumerate(
            zip(
                _GROUP_TERMS["heat_map"],
                (
                    cp.heat_btu_h,
                    cp.heat_btu_h_per_air_f,
                    cp.heat_btu_h_per_water_f,
                ),
                (4, 3, 3),
                strict=True,
            )
        )
    ]
    terms += [
        Term(
            name,
            _num(value),
            f"{pump.n_power} blocks",
            power_error if i == 0 else "-",
            power_ok,
            power_why,
        )
        for i, (name, value) in enumerate(
            zip(
                _GROUP_TERMS["power_map"],
                (cp.power_w, cp.power_w_per_air_f, cp.power_w_per_water_f),
                strict=True,
            )
        )
    ]
    terms += [
        Term(
            "Start hold by time off (min)",
            _holds(cp.start_hold_min),
            f"{pump.n_holds} starts",
            "-",
            pump.start_hold_min is not None,
            ""
            if pump.start_hold_min is not None
            else needs(
                pump.n_holds,
                "starts with no water in use",
                hpf.MIN_BAND_STARTS,
            ),
            note="under "
            + ", ".join(f"{m:g}" for m in cp.start_hold_after_min)
            + " min off, and beyond",
        ),
        Term(
            "Run-on overshoot (°F)",
            _num(c.params.controller.hp_stop_overshoot_f),
            f"{pump.n_runs} run-ons",
            "-",
            pump.overshoot_f is not None,
            ""
            if pump.overshoot_f is not None
            else needs(pump.n_runs, "draw-free run-ons", hpf.MIN_RUN_ONS),
        ),
    ]
    return _judged(terms, done) if done.judged else terms


# ── the heat book's terms, from its re-anchors ──────────────────────


#: The fewest re-anchor pairs ``fit_book`` refits the book on, and the
#: fewest with a circulation run in them it fits the loop's loss on.
MIN_BOOK_PAIRS = 10
MIN_RUN_PAIRS = 10
#: The flow a run without a flow reading is booked at, gal/min, so that
#: it breaks the quiet anchors; its pairs are left out.
_UNPRICED_GPM = 1.0
#: The shortest observed span ``fit_book`` books, hours.
_MIN_SEGMENT_H = 2.0

#: A re-anchor pair: its later anchor's instant, its book's index, the
#: pair, whether a circulation run is in it, and whether every run in it
#: has its flow.
_Pair = tuple[datetime, int, tuple[int, int], bool, bool]


@dataclass(frozen=True)
class BookTermsFit:
    """``fit_book``'s result: the book's terms to use (``book``, for
    ``HeaterParams.book``), the circulation loop's book circuit volume
    (``book_circuit_gal``, for ``CirculationParams``) and the base's
    loss per gallon (``loss_btu_per_gal``; None without a loop),
    whether they are the base's or the refit's (``kept``), the re-anchor
    pairs read and those with a circulation run in them, the held-out
    error of the terms kept (mean absolute, BTU; None with nothing held
    out), and why."""

    book: BookParams
    loss_btu_per_gal: float | None
    kept: str
    pairs: int
    run_pairs: int
    error_btu: float | None
    why: str
    #: The book's circuit volume (``CirculationParams.book_circuit_gal``)
    #: the terms were fitted with, gal; None for the loss per gallon.
    book_circuit_gal: float | None = None

    def as_document(self) -> dict[str, Any]:
        """The fit as a document: ``book`` the terms' fields, and the
        rest as they are."""
        return {
            "book": {
                f.name: getattr(self.book, f.name)
                for f in dataclass_fields(self.book)
            },
            "loss_btu_per_gal": self.loss_btu_per_gal,
            "book_circuit_gal": self.book_circuit_gal,
            "kept": self.kept,
            "pairs": self.pairs,
            "run_pairs": self.run_pairs,
            "error_btu": self.error_btu,
            "why": self.why,
        }


def fit_book(
    rows: sa.ChangeRows,
    observed: Iterable[datetime],
    params: HeaterParams,
    *,
    flow: Iterable[tuple[datetime, float | None]],
    runs: Iterable[tuple[datetime, datetime]] = (),
    circulation_flow: Iterable[tuple[datetime, float | None]] = (),
    inlet: Iterable[tuple[datetime, float]] = (),
    air: Iterable[tuple[datetime, float]] = (),
    flow_volume: FlowVolume = "delivered",
) -> BookTermsFit:
    """The heat book's terms (``BookParams``) and a circulation loop's
    book circuit volume from a heater's values' changes and the instants it
    was heard from, the household's draws (``flow``), and the
    circulation pump's ``runs`` with the loop's flow
    (``circulation_flow``, apart from the draws). Like the rows, the
    flows are gal/min and ``inlet`` and ``air`` °F, whatever the
    preferred units, and ``flow_volume`` is what the draws' gallons
    count (``sim_adapters.book_from_history``), as the book will debit
    them. ``params.book`` and ``params.circulation``'s pricing (its
    ``book_circuit_gal``, else its loss per gallon) are the base.

    The book's terms are fitted together, on every pair of quiet full
    tanks (``sim.calibration.RecordedBook``'s re-anchors up to
    ``max_anchor_age_h`` apart) across the history: the compressor's
    heat rate and its slope with the air and the standby UA
    (``sim.calibration.BOOK_TERMS``), for the least mean absolute error,
    and, with ``MIN_RUN_PAIRS`` pairs with a run in them, the loop's
    book circuit volume (``CirculationParams.book_circuit_gal``, within
    ``sim.calibration.BOOK_CIRCUIT_GAL_BOUNDS``): each run's gallons up
    to it from its start, runs closer than ``run_gap_min`` one run, each
    gallon at the upper probe less the air. The others are fitted
    exactly at each volume, and the volume searched. A term the pairs
    can't tell apart from the others (the slope, with the air never off
    one temperature) is held at the base. The
    rest of the book (the draw line, the anchors' age, the valve's line)
    is ``params``'; the valve's line is ``params.draw``'s, so the fitted
    ``book`` keeps its own no-valve default there
    (``HeaterParams.book_terms``). The empty points are ``params``' too,
    booked as delivered gallons; with ``flow_volume="tank"``, refit
    them (``sim.calibration.empty_point``, and ``zone_empty_btu`` as far
    below it).
    Without the volume fitted, the loop
    is priced as the base prices it, and without a base, the pairs with
    a run in them are left out. A run's
    flow is its readings, the first from its start; readings outside
    the runs are not used, and the pairs with a run that has none are
    left out.

    It refits only on ``MIN_BOOK_PAIRS`` pairs: the latest fifth is held
    out of the refit, which replaces the base only when it books them no
    worse. A term on its bound (``sim.calibration.BOOK_TERM_BOUNDS``) is
    no fit: the book then misses something between the anchors that the
    term is standing in for. Without a fit, the base is kept. A span the
    heater wasn't heard from (``sim_adapters.silences``,
    ``rows.outages``) breaks the book, and so do a probe's missing
    readings (None, NaN) and the draws' silence over
    ``sim_adapters.METER_MAX_GAP``, or before their first reading or
    after their last."""
    from nwp500.sim.defaults import SITE_CIRCULATION

    base = params.circulation
    base_loss = None if base is None else base.loss_btu_per_gal
    base_circuit = None if base is None else base.book_circuit_gal
    book_p = params.book_terms()

    def finite(
        rows: Iterable[tuple[datetime, float | None]],
    ) -> list[tuple[datetime, float]]:
        """``rows`` in UTC, in order; a missing reading (None, NaN) is
        none."""
        return sorted(
            (t.astimezone(UTC), float(v))
            for t, v in rows
            if v is not None and math.isfinite(v)
        )

    flow_rows = finite(flow)
    run_spans = sorted((a.astimezone(UTC), b.astimezone(UTC)) for a, b in runs)
    # Each run's flow is its own readings (``sim_adapters.run_readings``,
    # as booking takes them); one without any is booked at
    # ``_UNPRICED_GPM``, and isn't priced.
    run_rows = sa.run_readings(run_spans, circulation_flow)
    read_from = {t for t, _ in run_rows}
    priced = [a in read_from for a, _ in run_spans]
    run_rows = sorted(
        [
            *run_rows,
            *(
                (a, _UNPRICED_GPM)
                for (a, _), ok in zip(run_spans, priced, strict=True)
                if not ok
            ),
        ]
    )
    inlets, airs = list(inlet), list(air)
    seen_n = {"pairs": 0, "run_pairs": 0}

    def keep(why: str, error: float | None = None) -> BookTermsFit:
        return BookTermsFit(
            params.book,
            base_loss,
            "base",
            seen_n["pairs"],
            seen_n["run_pairs"],
            error,
            why,
            base_circuit,
        )

    if not flow_rows:
        return keep("no draws: the book can't see them")

    # The observed spans, each booked on its own.
    heard = sorted(t.astimezone(UTC) for t in observed)
    if not heard:
        return keep("the heater was never heard from")
    # And the draws': a silence over ``METER_MAX_GAP``, or before their
    # first reading or after their last, would read as a quiet tank.
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
            *_unread_spans(rows.upper_f, heard[-1]),
            *_unread_spans(rows.lower_f, heard[-1]),
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
    # The book has no step before both probes read: each span starts
    # there, so its steps' instants are its own.
    firsts = [
        min(read)
        for read in (
            [
                t.astimezone(UTC)
                for t, v in r
                if v is not None and math.isfinite(v)
            ]
            for r in (rows.upper_f, rows.lower_f)
        )
        if read
    ]
    probed = max(firsts) if len(firsts) == 2 else heard[-1]
    segments = [(max(a, probed), b) for a, b in segments]
    segments = [
        (a, b)
        for a, b in segments
        if (b - a).total_seconds() >= _MIN_SEGMENT_H * 3600
    ]

    # The loop's terms for booking: the draws hold none of its water.
    # The loss is each fit's own (``errors``, ``pair_terms``).
    template = base or SITE_CIRCULATION
    terms = CirculationParams(
        displaced_gal=template.displaced_gal,
        flow_gpm=_UNPRICED_GPM,
        loss_btu_per_gal=0.0,
        meter_share=0.0,
        run_gap_min=template.run_gap_min,
    )
    with_terms = replace(params, circulation=terms if run_spans else None)
    fitted = [
        cal.RecordedBook(
            sa.book_steps_from_changes(
                rows,
                start=a,
                end=b,
                flow=flow_rows,
                circulation=run_spans,
                circulation_flow=run_rows,
                inlet=inlets,
                air=airs,
                params=with_terms,
                unheard=silences(heard, max_gap(heard)),
                flow_volume=flow_volume,
            ),
            book_p,
            with_terms.circulation,
            start=a,
        )
        for a, b in segments
    ]

    def pairs_of() -> list[_Pair]:
        out: list[_Pair] = []
        for i, bk in enumerate(fitted):
            if not bk.steps:
                continue
            for a0, a1 in bk.reanchors(book_p.max_anchor_age_h):
                t0, t1 = bk.at(a0), bk.at(a1)
                inside = [
                    ok
                    for (a, b), ok in zip(run_spans, priced, strict=True)
                    if a < t1 and t0 < b
                ]
                out.append((t1, i, (a0, a1), bool(inside), all(inside)))
        return sorted(out, key=lambda x: x[0])

    def system(
        chosen: Sequence[_Pair], circuit_gal: float | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """The chosen pairs' errors as ``k + x @ terms``, in their
        order, the runs priced at ``circuit_gal`` where given."""
        rows: dict[int, list[int]] = {}
        for at, (_, i, *_) in enumerate(chosen):
            rows.setdefault(i, []).append(at)
        k = np.zeros(len(chosen))
        x = np.zeros((len(chosen), len(cal.BOOK_TERMS)))
        for i, ats in rows.items():
            bk, bx = fitted[i].pair_terms(
                book_p, [chosen[at][2] for at in ats], circuit_gal
            )
            k[ats], x[ats] = bk, bx
        return k, x

    def attempt(fit_loss: bool, notes: list[str]) -> BookTermsFit | str:
        """The fit with the book's circuit volume fitted, or the loop
        held at the base's terms; why not, as a string, when only the
        volume is on its bound."""
        found = [f for f in pairs_of() if f[4]]
        if not fit_loss and base_loss is None:
            # Runs the book can't price: their pairs are left out.
            found = [f for f in found if not f[3]]
        seen_n["pairs"] = len(found)
        seen_n["run_pairs"] = sum(f[3] for f in found)
        note = "; ".join(notes)

        def because(why: str) -> str:
            return f"{why}; {note}" if note else why

        n_held = _split(len(found))
        if len(found) < MIN_BOOK_PAIRS or not n_held:
            return keep(
                because(
                    f"{len(found)} re-anchor pairs: {MIN_BOOK_PAIRS} needed "
                    "to hold the latest out and judge a refit by"
                )
            )
        train, held = found[: len(found) - n_held], found[len(found) - n_held :]
        start = np.array(
            [
                book_p.hp_btu_per_h,
                book_p.hp_btu_per_h_per_f,
                book_p.ua_btu_per_h_f,
                base_loss or 0.0,
            ],
            dtype=float,
        )
        bounds = cal.BOOK_TERM_BOUNDS

        def solve(
            circuit_gal: float | None,
        ) -> tuple[np.ndarray, list[int], float]:
            """The book's terms on the training pairs with the runs
            priced at ``circuit_gal`` (else the base's loss per gallon,
            held), the terms fitted, and their training error."""
            k, x = system(train, circuit_gal)
            free = _independent(x, range(3))
            fixed = [j for j in range(4) if j not in free]
            got = start.copy()
            got[free] = cal.fit_terms_l1(
                k + x[:, fixed] @ start[fixed],
                x[:, free],
                [bounds[j] for j in free],
            )
            return got, free, float(np.mean(np.abs(k + x @ got)))

        circuit = base_circuit
        if fit_loss:
            # The circuit volume is no linear term: the others are fitted
            # exactly at each volume, and the volume searched.
            lo, hi = cal.BOOK_CIRCUIT_GAL_BOUNDS
            grid = np.linspace(lo, hi, 61)
            scores = [solve(float(v))[2] for v in grid]
            best = int(np.argmin(scores))
            a = float(grid[max(best - 1, 0)])
            b = float(grid[min(best + 1, len(grid) - 1)])

            def score(v: float) -> float:
                return solve(float(v))[2]

            found_v = cast(
                OptimizeResult,
                minimize_scalar(score, bounds=(a, b), method="bounded"),
            )
            circuit = float(found_v.x)
            if min(circuit - lo, hi - circuit) <= 1e-3 * (hi - lo):
                return (
                    f"the book's circuit volume on its bound, not a fit: "
                    f"{circuit:.4g} gal ({lo:g} to {hi:g})"
                )
            # Past the most any group of runs circulated between the
            # training pairs' anchors, every volume books them the same:
            # the runs can't say which.
            most = 0.0
            for _, i, (a0, a1), *_ in train:
                bk = fitted[i]
                if a1 > a0:
                    span = bk.run_before[a0:a1] + bk.circulated[a0:a1]
                    most = max(most, float(np.max(span)))
            if circuit >= most - 1e-6:
                return (
                    f"the book's circuit volume {circuit:.4g} gal is past the "
                    f"most a run circulated ({most:.4g} gal): not a fit"
                )
            # And what the volume moves, the book's terms must not make
            # (the same runs after the same recoveries, say): else the
            # heat rate could take up any volume.
            step = max(1e-3, 0.01 * circuit)
            k_up, x_at = system(train, circuit + step)
            k_down, _ = system(train, max(lo, circuit - step))
            moves = (k_up - k_down) / (circuit + step - max(lo, circuit - step))
            _, free_at, _ = solve(circuit)
            cols = np.column_stack([x_at[:, free_at], moves])
            norms = np.linalg.norm(cols, axis=0)
            if (
                np.any(norms <= 1e-9)
                or np.linalg.matrix_rank(cols / norms, tol=1e-6) < cols.shape[1]
            ):
                return (
                    "the book's circuit volume can't be told from the book's "
                    "terms on these pairs, not a fit"
                )
        got, free, _ = solve(circuit)
        by_book: dict[int, list[tuple[int, int]]] = {}
        for _, i, pair, *_ in held:
            by_book.setdefault(i, []).append(pair)
        base_err = float(
            np.mean(
                np.abs(
                    np.concatenate(
                        [
                            fitted[i].errors(
                                book_p, base_loss or 0.0, these, base_circuit
                            )
                            for i, these in by_book.items()
                        ]
                    )
                )
            )
        )
        on_bound = [
            j
            for j in free
            if min(got[j] - bounds[j][0], bounds[j][1] - got[j])
            <= 1e-6 * (bounds[j][1] - bounds[j][0])
        ]
        named = ", ".join(
            f"{cal.BOOK_TERMS[j]} {got[j]:.4g} ({bounds[j][0]:g} to "
            f"{bounds[j][1]:g})"
            for j in on_bound
        )
        if on_bound:
            return keep(because(f"on its bound, not a fit: {named}"), base_err)
        kh, xh = system(held, circuit)
        refit_err = float(np.mean(np.abs(kh + xh @ got)))
        versus = (
            f"held out, {refit_err:.0f} BTU against the base's {base_err:.0f}"
        )
        if refit_err > base_err:
            return keep(because(versus), base_err)
        return BookTermsFit(
            replace(
                params.book,
                hp_btu_per_h=float(got[0]),
                hp_btu_per_h_per_f=float(got[1]),
                ua_btu_per_h_f=float(got[2]),
            ),
            base_loss,
            "refit",
            seen_n["pairs"],
            seen_n["run_pairs"],
            refit_err,
            because(versus),
            circuit,
        )

    notes: list[str] = []
    with_run = sum(f[3] for f in pairs_of() if f[4])
    if with_run >= MIN_RUN_PAIRS:
        done = attempt(True, notes)
        if isinstance(done, BookTermsFit):
            return done
        notes = [done]
    elif run_spans:
        notes = [
            f"{with_run} pairs with a run: {MIN_RUN_PAIRS} needed to fit "
            "the loop's circuit volume"
        ]
    # With the loss held, nothing is fitted on its bound but the book.
    return cast(BookTermsFit, attempt(False, notes))


#: The order ``fit_book`` takes its terms in when the pairs can't tell
#: them all apart: the slope with the air last, as with the air never
#: moving it only rescales the heat rate.
_TERM_PRIORITY = (0, 2, 3, 1)


def _independent(x: np.ndarray, terms: Iterable[int]) -> list[int]:
    """Of ``terms``, the columns of ``x`` the pairs tell apart, in
    ``_TERM_PRIORITY``: a column no other combination of those taken
    can make is taken, and the rest are held. A column of zeros (a term
    the pairs don't move) or one in proportion to another (the slope,
    with the air at one temperature) is held."""
    taken: list[int] = []
    wanted = set(terms)
    for j in _TERM_PRIORITY:
        if j not in wanted:
            continue
        scale = np.linalg.norm(x[:, j])
        if scale <= 1e-9:
            continue
        trial = [*taken, j]
        cols = x[:, trial] / np.linalg.norm(x[:, trial], axis=0)
        if np.linalg.matrix_rank(cols, tol=1e-6) == len(trial):
            taken.append(j)
    return sorted(taken)


def _unread_spans(
    probe: Iterable[tuple[datetime, float | None]], end: datetime
) -> list[tuple[datetime, datetime]]:
    """The spans a probe's held reading is none (None, NaN), to ``end``
    for one never read again: the book has no step there. In instant
    order, UTC, whatever zone (or none, local) each reading is in."""
    out: list[tuple[datetime, datetime]] = []
    began: datetime | None = None
    for t, v in sorted(
        ((t.astimezone(UTC), v) for t, v in probe), key=lambda r: r[0]
    ):
        known = v is not None and math.isfinite(v)
        if not known and began is None:
            began = t
        elif known and began is not None:
            out.append((began, t))
            began = None
    if began is not None:
        out.append((began, end))
    return out
