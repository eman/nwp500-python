"""The calibrated tank the engine runs on.

The engine (``sim.engine``) takes its physics as a ``Physics``: the
tank as a state it carries without reading it, which the physics
walks forward under whatever runs (``advance``), takes a draw from
(``draw``), and reads the probes of (``observe``); ``estimate`` makes
a state of two probe readings. ``TankPhysics`` is the core's: the
stratified tank (``physics.stratified``) its ``HeaterParams`` lay out,
heated by the heat pump's map and the elements where they sit, losing
through its jacket, drawn through the mixing valve and with the
circulation's water through it, all on one ambient series, so every
segment of a simulation reads the same world.

It reaches no module state, cache or configuration for what it is not
given. Each input is a value its client resolves before it builds one
(the circulation's runs, an inlet, the ambient frame and humidity,
``HeaterParams``), so the same inputs give the same answer on any
thread.

**Water moves through the tank as draws and flows**: the delivered
draws the engine hands each walk, through the valve, and the
circulation's runs (``sim.circulation.Circulation``), whose cooled
pipe water comes back first at its rest temperature and then the run's
own, straight from the top.

**A recovery is the walk** with the heat pump on until the lower
probe reaches the target (``recovery``): the duration a
``RecoveryModel`` is asked about, whose answer scales the heat pump's
heat (``heat_pump_recovery.rate_scale``).

**The ambient frame** (``t_amb_series``) is a ``pd.DataFrame`` with a
tz-aware ``DatetimeIndex`` and an ``ambient_f`` column, °F: the air
at the heater's evaporator. ``sim.decay.AmbientSampler`` reads it.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Literal, Protocol

import pandas as pd

from nwp500.sim.circulation import Circulation, cooled_share
from nwp500.sim.decay import AmbientSampler, Impulse
from nwp500.sim.extensions import RecoveryModel
from nwp500.sim.heat_pump_recovery import (
    RATE_SCALE_RANGE,
    ModelDuration,
    PhysicsRecovery,
    RecoveryContext,
    Scaled,
    rate_scale,
)
from nwp500.sim.heating_trajectory import HeatingPoint, from_walk
from nwp500.sim.params import CirculationParams, CompressorParams, HeaterParams
from nwp500.sim.physics import stratified as st
from nwp500.sim.physics.heat_pump import (
    HEAT_MAP_OUT_OF_DOMAIN,
    heat_air_outside,
    heat_water_outside,
)

#: A delivered draw at the inlet: its onset, the gallons the meter
#: counts, and whether it takes the tank's water whole
#: (``DrawParams.undiluted``) rather than through the valve.
Delivered = tuple[datetime, float, bool]
#: The tank as a ``Physics`` carries it: opaque to the engine, which
#: reads it only through ``Physics.observe``.
TankState = object
#: What ends a walk early: a test of the probes, ``(upper, lower)``.
Stop = Callable[[float, float], bool]
#: The longest a recovery is walked for before it is called short of
#: its target.
RECOVERY_BOUND = timedelta(hours=16)


@dataclass(frozen=True)
class Point:
    """A state on the path: the probes, and the physics' state when it
    gave one. ``input_wh`` is the compressor's electricity over the
    interval ending here: 0.0 while it is off and on a segment's first
    element; None where it could not be priced."""

    at: datetime
    upper_f: float
    lower_f: float
    input_wh: float | None = 0.0
    #: The elements' electricity over the same interval.
    element_wh: float = 0.0
    #: The physics' state here, whose observation ``upper_f`` and
    #: ``lower_f`` are; None where the engine made the point, when the
    #: engine estimates one from the probes.
    state: TankState | None = field(default=None, compare=False)


@dataclass(frozen=True, kw_only=True)
class CompressorRun:
    """The compressor on from ``on_at``, heating from ``heats_at`` (its
    start's hold over), to ``off_at`` (None: past the walk), its heat
    scaled by ``scale`` (a recovery model's, ``Scaled``). ``stirs``:
    its heating begins at ``heats_at``, with the start's stir; False
    for a run under way at the walk's start, already heating."""

    on_at: datetime
    heats_at: datetime
    off_at: datetime | None = None
    scale: float = 1.0
    stirs: bool = True


@dataclass(frozen=True, kw_only=True)
class ElementRun:
    """An element on from ``on_at`` to ``off_at`` (None: past the
    walk). Its heat reaches the water its dead time later, so a run
    that has stopped still heats for that long."""

    zone: Literal["upper", "lower"]
    on_at: datetime
    off_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class Running:
    """What heats over a walk. Not ``credited`` (a withheld draw
    window), each source is charged its electricity and the tank gets
    none of its heat."""

    compressor: CompressorRun | None = None
    elements: tuple[ElementRun, ...] = ()
    credited: bool = True


@dataclass(frozen=True, kw_only=True)
class Recovered:
    """A recovery as served (``TankPhysics.recover``): its minutes, the
    hold included, whether it reached its target within
    ``RECOVERY_BOUND``, the model's confidence and the reasons, the
    physics' own duration and the model's answer, the air at its start
    and its mean over it, and its path."""

    minutes: float
    start_hold_minutes: float
    reached: bool
    confidence: float
    reasons: tuple[str, ...]
    physics: PhysicsRecovery
    model: ModelDuration | None
    ambient_start_f: float
    ambient_mean_f: float
    trajectory: tuple[HeatingPoint, ...]


@dataclass(frozen=True)
class Stretch:
    """A walk of the tank (``Physics.advance``): its points, the
    start's first, each later one with the electricity over the
    interval ending there; whether a stop ended it (at its last
    point); the lower probe's drop at each instant draws were taken,
    and at the end of each step the circulation cooled it over; the
    delivered gallons drawn and the heat they took, the heat the
    flows took, and the mean air over it; the reasons it carries (a
    heat pump heating outside its map's air); and the hours the
    condenser's heat went in, with the probes' mean times them, which
    a recovery's stretches sum to judge its water
    (``TankPhysics.heating_reasons``)."""

    points: list[Point]
    stopped: bool = False
    impulses: list[Impulse] = field(default_factory=list)
    draw_volume_gal: float = 0.0
    draw_heat_btu: float = 0.0
    flowing_heat_btu: float = 0.0
    ambient_mean_f: float | None = None
    reasons: tuple[str, ...] = ()
    heating_h: float = 0.0
    heating_mean_f_h: float = 0.0

    @property
    def end(self) -> datetime:
        return self.points[-1].at

    @property
    def state(self) -> TankState:
        state = self.points[-1].state
        assert state is not None
        return state


def point_at(points: Sequence[Point], at: datetime) -> Point:
    """The state at ``at`` on a path, linear between its elements, with
    the interval's energy split in proportion to time. On one of its
    elements it keeps that element's physics state; between two it has
    none."""
    if at <= points[0].at:
        return replace(points[0], at=at, input_wh=0.0, element_wh=0.0)
    for p0, p1 in pairwise(points):
        if p0.at <= at <= p1.at:
            span = (p1.at - p0.at).total_seconds()
            f = 1.0 if span <= 0 else (at - p0.at).total_seconds() / span
            return Point(
                at,
                p0.upper_f + (p1.upper_f - p0.upper_f) * f,
                p0.lower_f + (p1.lower_f - p0.lower_f) * f,
                None if p1.input_wh is None else p1.input_wh * f,
                p1.element_wh * f,
                # A recorded path's points (``PathPoint``) carry none.
                state=getattr(p1, "state", None) if at == p1.at else None,
            )
    return points[-1]


class Physics(Protocol):
    """The calibrated tank, as the engine takes it: ``TankPhysics`` is
    the core's. The tank is its state (``TankState``), which only it
    reads."""

    def estimate(self, upper_f: float, lower_f: float) -> TankState:
        """The state the probes reading ``upper_f`` and ``lower_f``
        stand for."""
        ...

    def observe(self, state: TankState) -> tuple[float, float]:
        """The probes on ``state``: upper, lower, °F."""
        ...

    def advance(
        self,
        start: datetime,
        state: TankState,
        end: datetime,
        draws: Sequence[Delivered] = (),
        *,
        running: Running = Running(),
        stop: Stop | None = None,
    ) -> Stretch:
        """The tank from ``start`` to ``end`` under ``running``, taking
        exactly ``draws`` (delivered gallons at their onsets, all in
        ``[start, end)``), with the circulation the physics was given.
        ``stop`` ends it at the first instant it holds."""
        ...

    def draw(
        self,
        at: datetime,
        state: TankState,
        gal: float,
        undiluted: bool = False,
    ) -> TankState:
        """The tank just after a delivered draw of ``gal`` at ``at``,
        through the valve or, ``undiluted``, its water whole."""
        ...


def _water_outside(c: CompressorParams, books: st.Books) -> bool:
    """Whether a walk's heating, if any, ran with the probes' mean over
    it outside the heat map's water span."""
    return books.compressor_heat_h > 0.0 and heat_water_outside(
        c, books.compressor_mean_f_h / books.compressor_heat_h
    )


def ambient_window_mean(
    t_amb_series: pd.DataFrame, start: datetime, end: datetime
) -> float | None:
    """Mean projected air temperature at the heater over [start, end],
    or None."""
    if t_amb_series.empty:
        return None
    index = t_amb_series.index
    if index.is_monotonic_increasing:
        # The same rows the mask below takes, found by bisection.
        lo = index.searchsorted(pd.Timestamp(start), side="left")  # pyright: ignore[reportCallIssue, reportArgumentType]
        hi = index.searchsorted(pd.Timestamp(end), side="right")  # pyright: ignore[reportCallIssue, reportArgumentType]
        window = t_amb_series["ambient_f"].iloc[lo:hi]
    else:
        window = t_amb_series.loc[
            (index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end)),
            "ambient_f",
        ]
    if window.empty:
        return None
    value = float(window.mean())
    return value if not math.isnan(value) else None


def circulation_flows(
    circulation: Circulation,
    terms: CirculationParams,
    air_at: Callable[[datetime], float],
    start: datetime,
    end: datetime,
) -> list[st.Flowing]:
    """The circulation's runs overlapping ``[start, end)``, whole, as
    the water they move through the tank: the pipe's cooled water first
    (``displaced_gal`` times its ``cooled_share`` since the run before),
    at the return's rest (the air plus ``return_rest_offset_f``), then
    the run's own from the top, back at the rest plus its
    ``steady_share`` of the top's lift over it."""
    if terms.flow_gpm <= 0.0:
        return []
    runs = circulation.over(start, end)
    if not runs:
        return []
    out: list[st.Flowing] = []
    every = sorted(circulation.runs)
    for a, b in runs:
        before = [r for r in every if r[1] <= a]
        rest = (
            None
            if not before
            else (a - max(r[1] for r in before)).total_seconds() / 3600.0
        )
        cooled = terms.displaced_gal * cooled_share(
            rest, terms.return_cool_tau_h
        )
        turn = min(b, a + timedelta(minutes=cooled / terms.flow_gpm))
        rest_f = air_at(a) + terms.return_rest_offset_f
        if turn > a:
            out.append(
                st.Flowing(
                    start=a, end=turn, gpm=terms.flow_gpm, inflow_f=rest_f
                )
            )
        if b > turn:
            out.append(
                st.Flowing(
                    start=turn,
                    end=b,
                    gpm=terms.flow_gpm,
                    inflow_f=None,
                    rest_f=rest_f,
                    pipe_ua_btu_hr_f=terms.pipe_ua_btu_hr_f,
                )
            )
    return out


class TankPhysics:
    """The calibrated tank, for ``sim.engine``: the stratified tank
    ``params`` lay out (``physics.stratified.layout``), walked on one
    ambient series.

    Every input is a value its client resolved:

    - ``params``: the heater's parameters;
    - ``t_amb_series``: the ambient frame (the module docstring), and
      ``humidity``, %, at the start (None: unknown);
    - ``draws_on``: whether delivered draws move the tank (a draw
      scenario);
    - ``circulation``: the circulation's runs, on its terms
      (``params.circulation``, else ``circulation_terms``); None, none;
    - ``draw_inlet_temp_f``: the water replacing a draw; None, the
      parameters' (``DrawParams.inlet_temp_f``);
    - ``draw_inlet_on``: the water replacing a draw on each day, in
      place of ``draw_inlet_temp_f`` (``DrawParams.mains_on``); None,
      that one all the span;
    - ``recovery_model``: the model of a recovery's duration; None, the
      physics alone;
    - ``low_confidence_floor``: a recovery whose confidence is below it
      carries ``recovery_low_confidence``;
    - ``air_readings``: the readings the air comes from, for where it
      leaves the heat pump's range (``air_outside``); None, the series.
    """

    def __init__(
        self,
        params: HeaterParams,
        t_amb_series: pd.DataFrame,
        humidity: float | None,
        *,
        draws_on: bool,
        circulation: Circulation | None = None,
        circulation_terms: CirculationParams | None = None,
        draw_inlet_temp_f: float | None = None,
        draw_inlet_on: Callable[[date], float] | None = None,
        recovery_model: RecoveryModel | None = None,
        low_confidence_floor: float = 0.0,
        air_readings: pd.DataFrame | None = None,
    ) -> None:
        self.params = params
        self.layout = st.layout(params)
        #: The water replacing a draw.
        self.draw_inlet_temp_f = (
            params.draw.inlet_temp_f
            if draw_inlet_temp_f is None
            else draw_inlet_temp_f
        )
        self.draw_inlet_on = draw_inlet_on
        self.valve = (
            params.draw.delivery_intercept_f,
            params.draw.delivery_slope,
        )
        self.circulation = circulation
        self.circulation_terms = (
            params.circulation
            if params.circulation is not None
            else circulation_terms
        )
        self.recovery_model = recovery_model
        self.low_confidence_floor = low_confidence_floor
        self.series = t_amb_series
        self.ambient = AmbientSampler(t_amb_series)
        self.air_readings = (
            None if air_readings is None else AmbientSampler(air_readings)
        )
        self.humidity = humidity
        self.draws_on = draws_on

    def estimate(self, upper_f: float, lower_f: float) -> st.TankState:
        return st.mix(st.estimate(self.layout, upper_f, lower_f))

    def layers(self, layers_f: Sequence[float]) -> st.TankState:
        """The tank of the layers ``layers_f``, °F, the bottom first:
        as many as the parameters lay out (``TankParams.layers``)."""
        if len(layers_f) != self.layout.layers:
            raise ValueError(
                f"{len(layers_f)} layers given, the parameters lay out "
                f"{self.layout.layers}"
            )
        return st.mix(st.TankState(tuple(float(t) for t in layers_f)))

    def observe(self, state: TankState) -> tuple[float, float]:
        return st.observe(self.layout, _layers(state))

    def _heating(self, running: Running) -> st.Heating:
        c = running.compressor
        el = self.params.element
        return st.Heating(
            compressor=None
            if c is None
            else st.Compressor(
                params=self.params.compressor,
                on_at=c.on_at,
                heats_at=c.heats_at,
                off_at=c.off_at,
                scale=c.scale,
                stirs=c.stirs,
            ),
            elements=tuple(
                st.Element(
                    zone=e.zone,
                    watts=el.element_w,
                    on_at=e.on_at,
                    off_at=e.off_at,
                    lag=timedelta(
                        minutes=el.upper_dead_time_min
                        if e.zone == "upper"
                        else 0.0
                    ),
                )
                for e in running.elements
            ),
            credited=running.credited,
        )

    def _flows(self, start: datetime, end: datetime) -> list[st.Flowing]:
        terms = self.circulation_terms
        if self.circulation is None or terms is None:
            return []
        return circulation_flows(
            self.circulation,
            terms,
            self.ambient.at,
            start,
            end,
        )

    def advance(
        self,
        start: datetime,
        state: TankState,
        end: datetime,
        draws: Sequence[Delivered] = (),
        *,
        running: Running = Running(),
        stop: Stop | None = None,
    ) -> Stretch:
        lay = self.layout
        taken = list(draws) if self.draws_on else []
        walked = st.walk(
            lay,
            _layers(state),
            start,
            end,
            air_f=self.ambient.at,
            heating=self._heating(running),
            flowing=self._flows(start, end),
            draws=[
                st.Delivered(
                    at=t, gal=g, inflow_f=self.inlet_at(t), undiluted=u
                )
                for t, g, u in taken
            ],
            valve=self.valve,
            stop=None
            if stop is None
            else (lambda s: stop(*st.observe(lay, s))),
        )
        points: list[Point] = []
        for k, (at, s) in enumerate(walked.path):
            u, lo = st.observe(lay, s)
            b = walked.steps[k - 1] if k else None
            points.append(
                Point(
                    at,
                    u,
                    lo,
                    0.0 if b is None else b.compressor_wh,
                    0.0 if b is None else b.element_wh,
                    state=s,
                )
            )
        drawn = {at: after for at, _, after in walked.drops}
        lower_drawn = {at: st.observe(lay, a)[1] for at, a in drawn.items()}
        impulses = [
            Impulse(at, st.observe(lay, before)[1], lower_drawn[at])
            for at, before, _ in walked.drops
        ]
        # A step the circulation took heat over, the lower probe falling,
        # is a drop too, at the step's end: Energy Saver's held lower
        # trigger is released by one (``tou_triggers.heater_start``).
        for (a, b), books in zip(pairwise(points), walked.steps, strict=True):
            before = lower_drawn.get(a.at, a.lower_f)
            if books.flowing_btu > 0.0 and b.lower_f < before:
                impulses.append(Impulse(b.at, before, b.lower_f))
        impulses.sort(key=lambda i: i.at)
        # The path holds the tank just before a draw at its instant;
        # the tank just after it is the next element there, as the
        # engine's path carries a draw.
        out: list[Point] = []
        for k, p in enumerate(points):
            out.append(p)
            after = drawn.get(p.at)
            last_there = k + 1 == len(points) or points[k + 1].at != p.at
            if after is not None and p.state is not after and last_there:
                u, lo = st.observe(lay, after)
                out.append(Point(p.at, u, lo, 0.0, 0.0, state=after))
        points = out
        mean = ambient_window_mean(self.series, start, walked.end)
        reasons: tuple[str, ...] = ()
        if (
            running.compressor is not None
            and mean is not None
            and heat_air_outside(self.params.compressor, mean)
        ):
            reasons = (HEAT_MAP_OUT_OF_DOMAIN,)
        books = walked.books
        return Stretch(
            points,
            stopped=walked.stopped,
            impulses=impulses,
            draw_volume_gal=sum(
                g for t, g, _ in taken if start <= t < walked.end
            ),
            draw_heat_btu=books.drawn_btu,
            flowing_heat_btu=books.flowing_btu,
            ambient_mean_f=mean,
            reasons=reasons,
            heating_h=books.compressor_heat_h,
            heating_mean_f_h=books.compressor_mean_f_h,
        )

    def heating_reasons(
        self, heating_h: float, mean_f_h: float
    ) -> tuple[str, ...]:
        """What a recovery's heating says of the heat map's water: its
        hours and the probes' mean times them, summed over its
        stretches (``Stretch.heating_h``, ``heating_mean_f_h``)."""
        if heating_h > 0.0 and heat_water_outside(
            self.params.compressor, mean_f_h / heating_h
        ):
            return (HEAT_MAP_OUT_OF_DOMAIN,)
        return ()

    def draw(
        self,
        at: datetime,
        state: TankState,
        gal: float,
        undiluted: bool = False,
    ) -> st.TankState:
        layers = _layers(state)
        if not self.draws_on:
            return layers
        valve = st.NO_VALVE if undiluted else self.valve
        return st.draw(self.layout, layers, gal, self.inlet_at(at), valve).state

    def inlet_at(self, at: datetime) -> float:
        """The water replacing a draw at ``at``: that day's, or the one
        all the span."""
        if self.draw_inlet_on is None:
            return self.draw_inlet_temp_f
        return self.draw_inlet_on(at.date())

    def _climb(
        self,
        start: datetime,
        layers: st.TankState,
        target_f: float,
        hold_minutes: float,
        scale: float = 1.0,
        *,
        under_way: bool = False,
    ) -> st.Walked:
        """The heat pump on from ``start``, heating after
        ``hold_minutes``, until the lower probe reaches ``target_f``,
        within ``RECOVERY_BOUND``: nothing drawn, the circulation as
        given. ``under_way``: it is running at ``start``, so its heating
        has begun unless ``hold_minutes`` of its hold are left; begun,
        the layers are not stirred again."""
        heats = start + timedelta(minutes=max(0.0, hold_minutes))
        end = heats + RECOVERY_BOUND
        lay = self.layout
        return st.walk(
            lay,
            layers,
            start,
            end,
            air_f=self.ambient.at,
            heating=st.Heating(
                compressor=st.Compressor(
                    params=self.params.compressor,
                    on_at=start,
                    heats_at=heats,
                    scale=scale,
                    stirs=not under_way or hold_minutes > 0.0,
                )
            ),
            flowing=self._flows(start, end),
            valve=self.valve,
            stop=lambda s: st.observe(lay, s)[1] >= target_f,
        )

    def recovery(
        self,
        start: datetime,
        state: TankState,
        target_f: float,
        *,
        hold_minutes: float = 0.0,
        under_way: bool = False,
    ) -> PhysicsRecovery:
        """The heat pump's recovery from ``state`` until the lower probe
        reaches ``target_f`` after a hold of ``hold_minutes``: its
        climb's minutes. ``under_way``: the compressor is running at
        ``start`` (``_climb``)."""
        return _physics(
            self._climb(
                start,
                _layers(state),
                target_f,
                hold_minutes,
                under_way=under_way,
            ),
            start,
            hold_minutes,
        )

    def _ask(
        self,
        start: datetime,
        layers: st.TankState,
        target_f: float,
        hold_minutes: float,
        physics: PhysicsRecovery,
        under_way: bool = False,
    ) -> tuple[Scaled, float, float]:
        """The ``recovery_model``'s answer for ``physics``, with this
        tank's confidence reason, and the air at the start and its mean
        over the recovery."""
        upper, lower = self.observe(layers)
        end = start + timedelta(minutes=hold_minutes + physics.minutes)
        amb = self.ambient.at(start)
        mean = ambient_window_mean(self.series, start, end)
        air = amb if mean is None else mean
        got = rate_scale(
            RecoveryContext(
                t_start_lower=lower,
                t_start_upper=upper,
                layers_f=layers.layers_f,
                target_f=target_f,
                t_amb_start=amb,
                t_amb_mean=air,
                h_amb_start=self.humidity,
                start_hold_minutes=hold_minutes,
                physics=physics,
            ),
            model=self.recovery_model,
        )
        if (
            self.recovery_model is not None
            and got.confidence < self.low_confidence_floor
        ):
            got = replace(
                got, reasons=(*got.reasons, "recovery_low_confidence")
            )
        paced = self._paced(
            start, layers, target_f, hold_minutes, got, under_way
        )
        return paced, amb, air

    def _paced(
        self,
        start: datetime,
        layers: st.TankState,
        target_f: float,
        hold_minutes: float,
        got: Scaled,
        under_way: bool = False,
    ) -> Scaled:
        """``got``'s scale corrected once, so the scaled climb takes the
        model's: a slower heat loses more to the jacket on the way, so
        the climb does not stretch exactly as the heat is scaled. The
        correction takes the climb to be in inverse proportion to the
        scale near the first."""
        answer = got.model
        if answer is None or got.scale == 1.0:
            return got
        want = answer.minutes - answer.start_hold_minutes
        walked = self._climb(
            start,
            layers,
            target_f,
            hold_minutes,
            got.scale,
            under_way=under_way,
        )
        climb = _physics(walked, start, hold_minutes).estimate
        if climb is None or want <= 0.0:
            return got
        low, high = RATE_SCALE_RANGE
        return replace(got, scale=min(high, max(low, got.scale * climb / want)))

    def scale(
        self,
        start: datetime,
        state: TankState,
        target_f: float,
        *,
        hold_minutes: float = 0.0,
        under_way: bool = False,
    ) -> Scaled:
        """A recovery starting at ``start`` as served: the
        ``recovery_model``'s scale on the heat pump's heat
        (``heat_pump_recovery.rate_scale``), its confidence and its
        reasons. Scale 1 and no reasons with no model. ``under_way``:
        the compressor is running at ``start`` (``_climb``)."""
        if self.recovery_model is None:
            return Scaled()
        layers = _layers(state)
        physics = self.recovery(
            start,
            layers,
            target_f,
            hold_minutes=hold_minutes,
            under_way=under_way,
        )
        return self._ask(
            start, layers, target_f, hold_minutes, physics, under_way
        )[0]

    def recover(
        self,
        start: datetime,
        state: TankState,
        target_f: float,
        *,
        hold_minutes: float = 0.0,
        under_way: bool = False,
    ) -> Recovered:
        """The recovery from ``state`` to ``target_f`` as served: the
        physics' walk at the pace the ``recovery_model`` gives it
        (``scale``), its duration, the hold included, and its path.
        ``under_way``: the compressor is running at ``start``
        (``_climb``)."""
        layers = _layers(state)
        walked = self._climb(
            start, layers, target_f, hold_minutes, under_way=under_way
        )
        physics = _physics(walked, start, hold_minutes)
        scaled, amb, air = self._ask(
            start, layers, target_f, hold_minutes, physics, under_way
        )
        if scaled.scale != 1.0:
            walked = self._climb(
                start,
                layers,
                target_f,
                hold_minutes,
                scaled.scale,
                under_way=under_way,
            )
        reasons = scaled.reasons
        if heat_air_outside(self.params.compressor, air) or _water_outside(
            self.params.compressor, walked.books
        ):
            reasons = (*reasons, HEAT_MAP_OUT_OF_DOMAIN)
        return Recovered(
            minutes=(walked.end - start).total_seconds() / 60.0,
            start_hold_minutes=max(0.0, hold_minutes),
            reached=walked.stopped,
            confidence=scaled.confidence,
            reasons=reasons,
            physics=physics,
            model=scaled.model,
            ambient_start_f=amb,
            ambient_mean_f=air,
            trajectory=tuple(from_walk(self.layout, walked)),
        )

    def air_outside(
        self, start: datetime, end: datetime, low: float, high: float
    ) -> list[tuple[datetime, datetime]]:
        """The spans of ``[start, end)`` with the air at the heater below
        ``low`` or at ``high`` and above (``AmbientSampler.outside``):
        where the heat pump is outside its operating range. On the
        readings the air comes from when given, so a dip shorter than the
        series' grid is seen."""
        air = self.ambient if self.air_readings is None else self.air_readings
        return air.outside(start, end, low, high)


def _physics(
    walked: st.Walked, start: datetime, hold_minutes: float
) -> PhysicsRecovery:
    heats = start + timedelta(minutes=max(0.0, hold_minutes))
    minutes = max(0.0, (walked.end - heats).total_seconds() / 60.0)
    return PhysicsRecovery(
        minutes=minutes,
        truncated=not walked.stopped,
        estimate=minutes if walked.stopped and minutes > 0.0 else None,
    )


def _layers(state: TankState) -> st.TankState:
    if not isinstance(state, st.TankState):
        raise TypeError(f"not TankPhysics' state: {state!r}")
    return state
