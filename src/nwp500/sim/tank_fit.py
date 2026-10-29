"""The stratified tank (``physics.stratified``) fitted to a recorded
history.

Two probes do not say where the water below the lower one is: a tank
that coasts after a draw and one that coasts after a recovery read
alike and behave apart. So each event is started from the layers the
history before it leaves (``replay``): the tank walked through the
recorded heating, draws and circulation, corrected to the probes every
``ASSIMILATE_EVERY``, the probes' own readings at the event laid over
it (``start_state``).

``fit`` then fits the tank's terms (``TERMS``) by robust least squares
on the probes' errors over the record's quiet coasts and the hours
after its draws (``Coast``), each event weighted alike. A fit walks
every event at every trial, so it takes ``map_`` to spread them: the
builtin ``map`` by default, an executor's ``map`` to use more cores.

The record carries no word on which element heats; its element runs
are taken as the upper's, where the heater runs its elements first.

Nothing here reads a file, the network or the clock.
"""

import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from nwp500.sim.circulation import cooled_share
from nwp500.sim.history import REPLAY
from nwp500.sim.params import HeaterParams
from nwp500.sim.physics import stratified as st
from nwp500.sim.physics.heat_pump import start_hold_min

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

#: A reading: an instant and a value.
Reading = tuple[datetime, float]
#: A pair of probe readings at an instant: (instant, upper, lower).
Observed = tuple[datetime, float, float]
#: A run of something on: its first and its last-plus-one minute.
Run = tuple[int, int]
#: A walk's step: its start, its end and its books.
Step = tuple[datetime, datetime, st.Books]

#: The record's grid.
MINUTE = timedelta(minutes=1)
#: How often ``replay`` corrects the layers to the probes.
ASSIMILATE_EVERY = timedelta(minutes=10)
#: How far before a record's part its element runs are kept: an
#: element's heat lags it by its dead time, under this.
_LAG_REACH = timedelta(hours=1)

#: The terms ``fit`` fits: (the params group, the field, its lower and
#: upper bounds, its typical step). The probe heights are shares of the
#: volume; the spreads and the inlet zone gallons.
TERMS: tuple[tuple[str, str, float, float, float], ...] = (
    ("loss", "ua_side_btu_hr_f", 0.0, 10.0, 0.5),
    ("loss", "ua_bottom_btu_hr_f", 0.0, 10.0, 1.0),
    ("loss", "ua_top_btu_hr_f", 0.0, 10.0, 0.5),
    ("tank", "conductance_btu_hr_f", 0.01, 10.0, 0.3),
    ("tank", "lower_probe_height", 0.05, 0.5, 0.05),
    ("tank", "lower_probe_spread_gal", 0.0, 20.0, 3.0),
    ("tank", "lower_probe_offset_f", -3.0, 3.0, 0.5),
    ("tank", "upper_probe_height", 0.6, 0.98, 0.05),
    ("tank", "upper_probe_spread_gal", 0.0, 20.0, 2.0),
    ("tank", "inlet_mix_gal", 0.0, 30.0, 2.0),
)
#: Where the condenser heats, fitted on recoveries (``fit``'s
#: ``terms``): ``TankParams.condenser_span`` as its low end and its
#: width, its top at most the tank's, so every point inside the bounds is
#: a span.
CONDENSER_TERMS: tuple[tuple[str, str, float, float, float], ...] = (
    ("tank", "condenser_low", 0.0, 0.5, 0.05),
    ("tank", "condenser_width", 0.1, 1.0, 0.05),
)
#: The condenser span as ``CONDENSER_TERMS`` name it.
_SPAN = ("condenser_low", "condenser_width")


@dataclass(frozen=True, eq=False)
class TankRecord:
    """A history on a one-minute grid from ``start``: the probes as of
    each minute (NaN unknown), the air (known throughout:
    ``tank_record`` holds it through its gaps), the runs of the
    compressor, the elements and the circulation, and the draws,
    ``(onset, delivered gallons)``. Its arrays are read-only."""

    start: datetime
    upper_f: np.ndarray = field(repr=False)
    lower_f: np.ndarray = field(repr=False)
    air_f: np.ndarray = field(repr=False)
    compressor: tuple[Run, ...] = field(repr=False)
    element: tuple[Run, ...] = field(repr=False)
    circulating: tuple[Run, ...] = field(repr=False)
    draws: tuple[tuple[datetime, float], ...] = field(repr=False)

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError("the record's start is aware")
        n = len(self.upper_f)
        for name in ("upper_f", "lower_f", "air_f"):
            a = np.array(getattr(self, name), dtype=float)
            if len(a) != n:
                raise ValueError(f"{name} is not the record's length")
            a.setflags(write=False)
            object.__setattr__(self, name, a)
        if not np.isfinite(self.air_f).all():
            raise ValueError("the record's air is known throughout")

    def __len__(self) -> int:
        return len(self.upper_f)

    def minute(self, at: datetime) -> int:
        """The minute ``at`` falls in."""
        return math.floor((at - self.start) / MINUTE)

    def instant(self, minute: int) -> datetime:
        return self.start + minute * MINUTE

    def air_at(self, at: datetime) -> float:
        """The air as of ``at``: the record's nearest minute inside it."""
        i = min(len(self) - 1, max(0, self.minute(at)))
        return float(self.air_f[i])

    def before(self, at: datetime, span: timedelta = REPLAY) -> TankRecord:
        """The part of the record ``replay`` reads for ``at``, which
        replays there as the whole does: from ``span`` before it, on
        the clock's grid, to it, reaching back to the start of a
        circulation run under way then and of an element run whose
        lagged heat is, with the compressor's and the circulation's run
        before those (their time off sets the next one's hold and
        cooled return). Small enough to hand to another process."""
        step = ASSIMILATE_EVERY // MINUTE
        i = max(0, self.minute(at - span))
        i -= (i - self.minute(datetime(1970, 1, 1, tzinfo=UTC))) % step
        i = max(0, i)
        j = min(len(self), max(i, self.minute(at) + 1))
        reach = i - _LAG_REACH // MINUTE
        first = i
        for of, frm in ((self.element, reach), (self.circulating, i)):
            for k in _overlapping(of, frm, j):
                first = min(first, of[k][0])
        first = max(0, first)

        def runs(of: tuple[Run, ...], frm: int, prior: bool) -> tuple[Run, ...]:
            k = _overlapping(of, frm, j)
            lo = max(0, k.start - 1) if prior else k.start
            return tuple((a - first, b - first) for a, b in of[lo : k.stop])

        a, b = self.instant(first), self.instant(j)
        lo = bisect_left(self.draws, (a, -math.inf))
        hi = bisect_left(self.draws, (b, -math.inf))
        return TankRecord(
            start=a,
            upper_f=self.upper_f[first:j],
            lower_f=self.lower_f[first:j],
            air_f=self.air_f[first:j],
            compressor=runs(self.compressor, i, True),
            element=runs(self.element, reach, False),
            circulating=runs(self.circulating, i, True),
            draws=self.draws[lo:hi],
        )


def _runs(on: np.ndarray) -> tuple[Run, ...]:
    edges = np.diff(np.r_[0, on.astype(np.int8), 0])
    starts = np.where(edges == 1)[0]
    ends = np.where(edges == -1)[0]
    return tuple(zip(starts.tolist(), ends.tolist(), strict=True))


def tank_record(
    frame: pd.DataFrame, draws: Iterable[tuple[datetime, float]] = ()
) -> TankRecord:
    """The record of a history frame (``sim_calibrate.prepare``): its
    ``upper_f``, ``lower_f``, ``air_f`` (held through its gaps),
    ``compressor_on``, ``element_on`` and ``circulating`` as of each
    minute, and the ``draws`` from a meter, ``(onset, delivered
    gallons)``."""
    if frame.empty:
        raise ValueError("the frame is empty")
    for name in ("upper_f", "lower_f", "air_f"):
        if name not in frame.columns:
            raise ValueError(f"the frame has no {name}")
    rows = frame[~frame.index.duplicated(keep="last")].sort_index()
    first = pd.Timestamp(rows.index[0]).ceil("1min")
    grid = pd.date_range(first, pd.Timestamp(rows.index[-1]), freq="1min")

    def column(name: str) -> pd.Series:
        return cast(pd.Series, rows[name])

    def held(name: str) -> np.ndarray:
        if name not in rows.columns:
            return np.zeros(len(grid), dtype=bool)
        on = column(name).astype("boolean").fillna(False).astype(bool)
        return on.reindex(grid, method="ffill").fillna(False).to_numpy()

    def value(name: str) -> pd.Series:
        return column(name).astype(float).reindex(grid, method="ffill")

    return TankRecord(
        start=cast(datetime, first.to_pydatetime()).astimezone(UTC),
        upper_f=value("upper_f").to_numpy(dtype=float),
        lower_f=value("lower_f").to_numpy(dtype=float),
        # The air holds through a gap in its readings, and before the
        # first, as the walk needs one.
        air_f=value("air_f").ffill().bfill().to_numpy(dtype=float),
        compressor=_runs(held("compressor_on")),
        element=_runs(held("element_on")),
        circulating=_runs(held("circulating")),
        draws=tuple(sorted((t, float(g)) for t, g in draws if g > 0.0)),
    )


# ── the replay ──


def _overlapping(runs: Sequence[Run], i: int, j: int) -> range:
    """The indices of the runs that overlap minutes ``[i, j)``."""
    k = bisect_right(runs, (i, math.inf))
    if k > 0 and runs[k - 1][1] > i:
        k -= 1
    m = k
    while m < len(runs) and runs[m][0] < j:
        m += 1
    return range(k, m)


def _compressor(
    params: HeaterParams, record: TankRecord, run: Run, k: int
) -> st.Compressor:
    """The compressor run ``run`` (the ``k``-th): its hold by the time
    off before it."""
    a, b = run
    off = float(a - record.compressor[k - 1][1]) if k > 0 else None
    hold = start_hold_min(params.compressor, off)
    on_at = record.instant(a)
    return st.Compressor(
        params=params.compressor,
        on_at=on_at,
        heats_at=on_at + timedelta(minutes=hold),
        off_at=record.instant(b),
    )


def _flows(
    params: HeaterParams, record: TankRecord, i: int, j: int
) -> list[st.Flowing]:
    """The circulation runs over minutes ``[i, j)``: the water the
    circuit's pipe cooled comes back first, at the return's rest
    (``CirculationParams.return_rest_offset_f`` above the air), as much
    as the pipe cooled since the last run (``circulation.cooled_share``);
    then the run's own water, back at the upper probe's reading."""
    c = params.circulation
    if c is None or c.flow_gpm <= 0.0:
        return []
    runs = record.circulating
    out: list[st.Flowing] = []
    for k in _overlapping(runs, i, j):
        a, b = runs[k]
        rest = (a - runs[k - 1][1]) / 60.0 if k > 0 else None
        cooled = c.displaced_gal * cooled_share(rest, c.return_cool_tau_h)
        turn = record.instant(a) + timedelta(minutes=cooled / c.flow_gpm)
        lo, hi = record.instant(max(a, i)), record.instant(min(b, j))
        air = float(record.air_f[a])
        if lo < min(turn, hi):
            out.append(
                st.Flowing(
                    start=lo,
                    end=min(turn, hi),
                    gpm=c.flow_gpm,
                    inflow_f=air + c.return_rest_offset_f,
                )
            )
        if max(turn, lo) < hi:
            m = max(record.minute(max(turn, lo)), 0)
            back = float(record.upper_f[m])
            out.append(
                st.Flowing(
                    start=max(turn, lo),
                    end=hi,
                    gpm=c.flow_gpm,
                    inflow_f=back if math.isfinite(back) else air,
                )
            )
    return out


def flows(
    params: HeaterParams, record: TankRecord, start: datetime, end: datetime
) -> list[st.Flowing]:
    """The circulation's runs in the record from ``start`` to ``end``,
    as the water they move through the tank (``replay``'s)."""
    i = max(0, record.minute(start))
    j = min(len(record), record.minute(end) + 1)
    return [
        replace(f, start=max(f.start, start), end=min(f.end, end))
        for f in _flows(params, record, i, j)
        if f.end > start and f.start < end
    ]


def _span(
    lay: st.Layout,
    params: HeaterParams,
    record: TankRecord,
    state: st.TankState,
    i: int,
    j: int,
    steps: list[Step] | None = None,
) -> st.TankState:
    """``state`` walked over minutes ``[i, j)`` of the record: split
    where a second compressor run starts, so each walk has one. The
    walks' steps are added to ``steps`` where it is given."""
    runs = _overlapping(record.compressor, i, j)
    if len(runs) > 1:
        cut = record.compressor[runs[1]][0]
        state = _span(lay, params, record, state, i, cut, steps)
        return _span(lay, params, record, state, cut, j, steps)
    compressor = (
        _compressor(params, record, record.compressor[runs[0]], runs[0])
        if runs
        else None
    )
    lag = min(timedelta(minutes=params.element.upper_dead_time_min), _LAG_REACH)
    reach = math.ceil(lag / MINUTE)
    elements = tuple(
        st.Element(
            zone="upper",
            watts=params.element.element_w,
            on_at=record.instant(record.element[k][0]),
            off_at=record.instant(record.element[k][1]),
            lag=lag,
        )
        for k in _overlapping(record.element, i - reach, j)
    )
    start, end = record.instant(i), record.instant(j)
    lo = bisect_left(record.draws, (start, -math.inf))
    hi = bisect_left(record.draws, (end, -math.inf))
    d = params.draw
    walked = st.walk(
        lay,
        state,
        start,
        end,
        air_f=record.air_at,
        heating=st.Heating(compressor=compressor, elements=elements),
        flowing=_flows(params, record, i, j),
        draws=[
            st.Delivered(at=t, gal=g, inflow_f=d.mains_on(t))
            for t, g in record.draws[lo:hi]
        ],
        valve=(d.delivery_intercept_f, d.delivery_slope),
    )
    if steps is not None:
        times = [t for t, _ in walked.path]
        steps.extend(zip(times[:-1], times[1:], walked.steps, strict=True))
    return walked.state


def _known(record: TankRecord, i: int) -> bool:
    return bool(
        math.isfinite(record.upper_f[i])
        and math.isfinite(record.lower_f[i])
        and math.isfinite(record.air_f[i])
    )


def replay(
    lay: st.Layout,
    params: HeaterParams,
    record: TankRecord,
    until: datetime,
    *,
    span: timedelta = REPLAY,
    gain: float = 1.0,
) -> st.TankState | None:
    """The layers at ``until`` the record leaves: from ``estimate`` of
    the probes ``span`` before it, walked through the record's heating,
    draws and circulation, corrected to the probes by ``gain``
    (``stratified.assimilate``) every ``ASSIMILATE_EVERY`` they are
    read. None when the record does not reach back to a reading of both
    probes and the air before ``until``."""
    end = record.minute(until)
    if end <= 0 or end > len(record):
        return None
    return _replayed(
        lay, params, record, record.minute(until - span), end, gain=gain
    )


def _replayed(
    lay: st.Layout,
    params: HeaterParams,
    record: TankRecord,
    first: int,
    end: int,
    *,
    gain: float = 1.0,
    steps: list[Step] | None = None,
) -> st.TankState | None:
    """``replay``'s walk from minute ``first`` to ``end``, its walks'
    steps added to ``steps`` where it is given; None with no reading of
    both probes and the air before ``end``."""
    step = ASSIMILATE_EVERY // MINUTE
    i = max(0, first)
    # On the clock's grid, as every walk is.
    i += (record.minute(datetime(1970, 1, 1, tzinfo=UTC)) - i) % step
    while i < end and not _known(record, i):
        i += step
    if i >= end:
        return None
    state = st.mix(
        st.estimate(lay, float(record.upper_f[i]), float(record.lower_f[i]))
    )
    while i < end:
        j = min(end, i + step)
        state = _span(lay, params, record, state, i, j, steps)
        if j < len(record) and _known(record, j):
            state = st.mix(
                st.assimilate(
                    lay,
                    state,
                    float(record.upper_f[j]),
                    float(record.lower_f[j]),
                    gain,
                )
            )
        i = j
    return state


def start_state(
    lay: st.Layout,
    params: HeaterParams,
    record: TankRecord | None,
    at: datetime,
    upper_f: float,
    lower_f: float,
) -> st.TankState:
    """The layers an event at ``at`` starts from: the ``replay`` there
    corrected to the probes' ``upper_f`` and ``lower_f`` exactly, or,
    with no record or none reaching back, ``estimate`` of them."""
    state = None if record is None else replay(lay, params, record, at)
    if state is None:
        return st.mix(st.estimate(lay, upper_f, lower_f))
    return st.mix(st.assimilate(lay, state, upper_f, lower_f))


def condenser_water(
    params: HeaterParams,
    record: TankRecord,
    spans: Sequence[tuple[datetime, datetime]],
) -> list[float]:
    """The water the condenser reads over each of ``spans``, °F: on one
    ``replay`` through the record, from ``REPLAY`` before the first span
    to the last's end, the water the walk read the power's map at
    (``stratified.Books.compressor_water_f_h``, after the draws and the
    start's stir), weighted by the hours it ran in the span; NaN for a
    span the compressor did not run in."""
    if not spans:
        return []
    lay = st.layout(params)
    first = min(a for a, _ in spans)
    end = min(len(record), record.minute(max(b for _, b in spans)) + 1)
    steps: list[Step] = []
    _replayed(
        lay, params, record, record.minute(first - REPLAY), end, steps=steps
    )
    starts = [a for a, _, _ in steps]
    out: list[float] = []
    for a, b in spans:
        hours = water = 0.0
        for lo, hi, books in steps[max(0, bisect_right(starts, a) - 1) :]:
            if lo >= b:
                break
            share = _share(lo, hi, a, b)
            hours += share * books.compressor_h
            water += share * books.compressor_water_f_h
        out.append(water / hours if hours > 0.0 else math.nan)
    return out


def _share(lo: datetime, hi: datetime, a: datetime, b: datetime) -> float:
    """The share of the step ``[lo, hi)`` inside ``[a, b)``."""
    inside = (min(hi, b) - max(lo, a)) / (hi - lo)
    return max(0.0, inside)


# ── the events and their errors ──


@dataclass(frozen=True)
class Coast:
    """A stretch of the record: the probes at its start, the air
    through it (readings holding to the next), its draws ``(onset,
    delivered gallons)``, and the probes ``observed`` after its start.
    Nothing heats it but the ``compressor`` run given, ``(on, heating
    from, off)``, and the water ``flowing`` through it (the
    circulation's) is given too."""

    start: datetime
    end: datetime
    upper_f: float
    lower_f: float
    air: tuple[Reading, ...]
    observed: tuple[Observed, ...]
    draws: tuple[tuple[datetime, float], ...] = ()
    compressor: tuple[datetime, datetime, datetime] | None = None
    flowing: tuple[st.Flowing, ...] = ()

    def __post_init__(self) -> None:
        if not self.air:
            raise ValueError("a coast needs its air")
        if not self.observed:
            raise ValueError("a coast needs its observations")


def _held(readings: Sequence[Reading]) -> Callable[[datetime], float]:
    times = [t for t, _ in readings]

    def at(t: datetime) -> float:
        return readings[max(0, bisect_right(times, t) - 1)][1]

    return at


def _along(path: Sequence[tuple[datetime, float]], t: datetime) -> float:
    """``path`` at ``t``, linear between its points, its last beyond."""
    times = [p[0] for p in path]
    k = bisect_right(times, t) - 1
    if k < 0:
        return path[0][1]
    if k >= len(path) - 1:
        return path[-1][1]
    (t0, a), (t1, b) = path[k], path[k + 1]
    return a + (b - a) * ((t - t0) / (t1 - t0))


def errors(
    params: HeaterParams, record: TankRecord | None, coast: Coast
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Each probe's error over ``coast``, predicted less observed at
    each observation: the tank ``params`` describe started from
    ``start_state`` and walked through the coast's air and draws."""
    lay = st.layout(params)
    state = start_state(
        lay, params, record, coast.start, coast.upper_f, coast.lower_f
    )
    d = params.draw
    end = max(coast.end, coast.observed[-1][0] + timedelta(seconds=1))
    run = coast.compressor
    walked = st.walk(
        lay,
        state,
        coast.start,
        end,
        air_f=_held(coast.air),
        heating=st.Heating(
            compressor=None
            if run is None
            else st.Compressor(
                params=params.compressor,
                on_at=run[0],
                heats_at=run[1],
                off_at=run[2],
            )
        ),
        flowing=coast.flowing,
        draws=[
            st.Delivered(at=t, gal=g, inflow_f=d.mains_on(t))
            for t, g in coast.draws
        ],
        valve=(d.delivery_intercept_f, d.delivery_slope),
    )
    read = [(t, st.observe(lay, s)) for t, s in walked.path]
    upper = [(t, u) for t, (u, _) in read]
    lower = [(t, lo) for t, (_, lo) in read]
    return (
        tuple(_along(upper, t) - u for t, u, _ in coast.observed),
        tuple(_along(lower, t) - lo for t, _, lo in coast.observed),
    )


def rmse(values: Sequence[float]) -> float:
    return math.sqrt(math.fsum(v * v for v in values) / len(values))


# ── the fit ──


Terms = tuple[tuple[str, str, float, float, float], ...]


def term_values(
    params: HeaterParams, terms: Terms = TERMS
) -> tuple[float, ...]:
    """``params``' values of ``terms``."""
    out: list[float] = []
    for group, name, *_ in terms:
        if name in _SPAN:
            low, high = params.tank.condenser_span
            out.append(low if name == "condenser_low" else high - low)
        else:
            out.append(float(getattr(getattr(params, group), name)))
    return tuple(out)


def with_terms(
    params: HeaterParams, values: Sequence[float], terms: Terms = TERMS
) -> HeaterParams:
    """``params`` with ``terms`` set to ``values``."""
    if len(values) != len(terms):
        raise ValueError(f"{len(terms)} values, not {len(values)}")
    groups: dict[str, dict[str, Any]] = {}
    low, high = params.tank.condenser_span
    span = [low, high - low]
    for (group, name, *_), v in zip(terms, values, strict=True):
        if name in _SPAN:
            span[_SPAN.index(name)] = float(v)
            groups.setdefault("tank", {})["condenser_span"] = (
                span[0],
                min(span[0] + span[1], 1.0),
            )
        else:
            groups.setdefault(group, {})[name] = float(v)
    return replace(
        params,
        **{
            g: replace(getattr(params, g), **changes)
            for g, changes in groups.items()
        },
    )


@dataclass(frozen=True)
class TankFit:
    """``fit``'s result: the parameters with the terms fitted, each
    term's value (``TERMS``' names), those the fit left on a bound, the
    probes' RMSE at the start and at the end (``fit``'s: each event
    weighing alike, °F), and the trials it took."""

    params: HeaterParams
    terms: dict[str, float]
    on_bound: tuple[str, ...]
    rmse_before: float
    rmse_after: float
    evaluations: int


def _event_rmse(found: Iterable[Sequence[Sequence[float]]]) -> float:
    """The root mean square, over the events and the two probes, of each
    probe's RMSE over its event, °F."""
    squares = [
        (math.fsum(e * e for e in du) + math.fsum(e * e for e in dl))
        / (2 * len(du))
        for du, dl in found
    ]
    return math.sqrt(math.fsum(squares) / len(squares))


def event_rmse(
    params: HeaterParams,
    record: TankRecord | None,
    coasts: Sequence[Coast],
    *,
    map_: Callable[..., Iterable[Any]] = map,
) -> float | None:
    """``params``' error on ``coasts`` as ``fit`` measures it, each
    started from the ``record``'s replay: the root mean square, over
    the events and the two probes, of each probe's RMSE over its event,
    °F; None with no events."""
    if not coasts:
        return None
    parts = [None if record is None else record.before(c.start) for c in coasts]
    return _event_rmse(map_(errors, [params] * len(coasts), parts, coasts))


def _robust(error: float) -> float:
    """``error`` through the soft-L1 loss at 1 °F, as a residual: its
    square is ``2 (sqrt(1 + e²) - 1)``, quadratic small and linear
    large."""
    return math.copysign(
        math.sqrt(2.0 * (math.sqrt(1.0 + error * error) - 1.0)), error
    )


def fit(
    params: HeaterParams,
    record: TankRecord | None,
    coasts: Sequence[Coast],
    *,
    terms: Terms = TERMS,
    map_: Callable[..., Iterable[Any]] = map,
    max_evaluations: int = 200,
) -> TankFit:
    """``terms`` (``TERMS``, or ``CONDENSER_TERMS`` on recoveries)
    fitted on ``coasts`` from ``params``' values: a robust
    (soft-L1, 1 °F) least squares of each probe's error at each
    observation, each event weighing alike however long it was
    observed, the events started from the ``record``'s replay
    (``start_state``). ``map_(function, a, b, c)`` maps over the
    events. Its RMSE is the root mean square, over the events and the
    two probes, of each probe's RMSE over the event, °F."""
    if not coasts:
        raise ValueError("no events to fit on")
    lo = np.array([t[2] for t in terms])
    hi = np.array([t[3] for t in terms])
    scale = np.array([t[4] for t in terms])
    x0 = np.clip(np.array(term_values(params, terms)), lo, hi)
    n = len(coasts)
    parts = [None if record is None else record.before(c.start) for c in coasts]

    def trial(x: np.ndarray) -> list[tuple[tuple[float, ...], ...]]:
        p = with_terms(params, x.tolist(), terms)
        return list(map_(errors, [p] * n, parts, coasts))

    def residuals(x: np.ndarray) -> np.ndarray:
        out: list[float] = []
        for du, dl in trial(x):
            w = 1.0 / math.sqrt(len(du))
            out.extend(w * _robust(e) for e in (*du, *dl))
        return np.array(out)

    before = _event_rmse(trial(x0))
    done = least_squares(
        residuals,
        x0,
        bounds=(lo, hi),
        x_scale=scale,
        diff_step=2e-2,
        max_nfev=max_evaluations,
    )
    x = done.x
    names = tuple(t[1] for t in terms)
    width = hi - lo
    edge = (x - lo < 1e-3 * width) | (hi - x < 1e-3 * width)
    return TankFit(
        params=with_terms(params, x.tolist(), terms),
        terms=dict(zip(names, x.tolist(), strict=True)),
        on_bound=tuple(k for k, e in zip(names, edge, strict=True) if e),
        rmse_before=before,
        rmse_after=_event_rmse(trial(x)),
        evaluations=int(done.nfev),
    )
