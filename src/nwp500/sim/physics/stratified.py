"""The tank as stacked layers of water, the bottom first, each mixed
within itself: the stratified tank of HPWHsim, in scalar Python.

A ``TankState`` is the layers' temperatures; a ``Layout`` is the tank
they fill (``layout`` reads it from ``HeaterParams``): its volume,
where the probes read, where the elements and the condenser heat, and
its losses. Heights are shares of the volume from the bottom.

Every operator conserves energy, to rounding, and none takes a layer
past what drives it:

- ``mix``: an inversion (a layer warmer than the one above) turns over
  at once, pooling the layers to their mean (pool-adjacent-violators);
- ``lose``: each layer relaxes toward the air, exactly, through its
  share of the jacket's UA, and the bottom layer through the bottom's
  too, so nothing cools below the air;
- ``conduct``: conduction and the slow mixing between neighbours, sub-
  stepped so no layer passes its neighbours (the maximum principle);
- ``add_heat``: heat into layers, then ``mix``, so heat put in low
  rises to where it belongs;
- ``flow``: water in at the bottom pushes the column up and out of the
  top as a plug, through a well-mixed zone of ``inlet_mix_gal`` at the
  inlet, solved exactly and remapped onto the layers by exact
  integrals;
- ``draw``: a delivered draw through the mixing valve
  (``physics.draw.delivery_temp_f``, ``hot_fraction``), the tank water
  it takes solved from the water leaving the top in turn.

The probes are observations of the layers (``observe``), and a profile
can be built from them (``estimate``) or corrected toward them
(``assimilate``). ``deliverable_gal`` is how much the tap gets at the
line before it runs under. ``walk`` steps the tank through time with
the heat sources, flows and draws given, on a grid anchored to the
clock, and cuts it exactly where a stop says; its ``Books`` close the
energy.

The layers are fixed, so a flow is remapped onto them: water moving a
fraction of a layer carries each layer's water as a line through its
mean, limited so it never passes a neighbour's (``_slope``). A front
inside a layer is then that line, not the front: two draws are one of
both to about a degree at the probes on a smooth profile, more on a
step. Water coming in warmer than the bottom turns over at the end of
each flow (``mix``), so where such a flow is cut matters.

Water's density and heat capacity are taken constant (8.34 BTU per
gallon per °F), so a layer's energy is linear in its temperature and
conservation is exact; the error is about 1.5 % over the tank's span.
"""

import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Literal

from nwp500.sim.params import CompressorParams, HeaterParams
from nwp500.sim.physics.draw import delivery_temp_f, hot_fraction
from nwp500.sim.physics.heat_pump import heat_btu_h, power_w
from nwp500.sim.units import BTU_PER_WH, WATER_BTU_PER_GAL_F

Zone = Literal["upper", "lower"]

#: The walk's steps: ten minutes with nothing heating or flowing, one
#: while something is.
IDLE_STEP = timedelta(minutes=10)
ACTIVE_STEP = timedelta(minutes=1)
#: How closely ``walk`` finds the instant a stop holds.
CUT_RESOLUTION = timedelta(seconds=1)
#: No valve: the tap gets the tank's own water (intercept, slope).
NO_VALVE = (0.0, 1.0)

#: The largest share of a layer's gap to a neighbour ``conduct`` closes
#: in one sub-step: at most a half, so no layer passes its neighbours.
_CONDUCT_SHARE = 0.5
#: The pieces the inlet zone's outflow is taken in where it reaches the
#: top (``draw``, ``deliverable_gal``), gal.
_TAIL_GAL = 0.25
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
#: The pieces each layer's water leaves the top in (``_Column.plug``).
_PIECES = 4


def _slope(below: float, above: float) -> float:
    """A layer's rise across it from its rises from the layer below and
    to the layer above (monotonized central): none at a peak or a
    trough, else the central difference, held to twice the smaller, so
    the line's ends stay within the neighbours' means."""
    if below * above <= 0.0:
        return 0.0
    mag = min(abs(below + above) / 2.0, 2.0 * abs(below), 2.0 * abs(above))
    return math.copysign(mag, below)


@dataclass(frozen=True)
class TankState:
    """The layers' temperatures, °F, the bottom first."""

    layers_f: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.layers_f) < 2:
            raise ValueError("a stratified tank has at least two layers")
        if not all(math.isfinite(t) for t in self.layers_f):
            raise ValueError(f"layers must be finite: {self.layers_f}")

    @classmethod
    def uniform(cls, layers: int, temp_f: float) -> TankState:
        """A mixed tank of ``layers`` layers at ``temp_f``."""
        return cls((float(temp_f),) * layers)


def _share(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} is a share of the volume: {value}")


@dataclass(frozen=True, kw_only=True)
class Layout:
    """The tank the layers fill (``layout``)."""

    volume_gal: float
    layers: int
    upper_probe: float
    lower_probe: float
    upper_element: float
    lower_element: float
    condenser_span: tuple[float, float]
    inlet_mix_gal: float
    #: The jacket's UA, the whole tank's, BTU/hr·°F, shared equally by
    #: the layers.
    ua_btu_hr_f: float
    #: The bottom's, from the bottom layer alone.
    ua_bottom_btu_hr_f: float
    #: The column's axial conductance, end to end, BTU/hr·°F.
    conductance_btu_hr_f: float
    #: Each layer's volume, gal, and its heat capacity, BTU/°F.
    layer_gal: float = field(init=False, repr=False)
    layer_btu_f: float = field(init=False, repr=False)
    #: Each layer's middle, as a share of the volume.
    centers: tuple[float, ...] = field(init=False, repr=False)
    #: The share of the condenser's heat each layer takes: its overlap
    #: with ``condenser_span``.
    condenser_weights: tuple[float, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.layers < 2:
            raise ValueError(f"layers must be at least 2: {self.layers}")
        if self.volume_gal <= 0.0:
            raise ValueError(f"volume_gal must be positive: {self.volume_gal}")
        for name in (
            "upper_probe",
            "lower_probe",
            "upper_element",
            "lower_element",
        ):
            _share(name, getattr(self, name))
        if not self.lower_probe < self.upper_probe:
            raise ValueError("the lower probe reads below the upper")
        low, high = self.condenser_span
        _share("condenser_span", low)
        _share("condenser_span", high)
        if not low < high:
            raise ValueError(f"condenser_span is empty: {self.condenser_span}")
        for name in (
            "inlet_mix_gal",
            "ua_btu_hr_f",
            "ua_bottom_btu_hr_f",
            "conductance_btu_hr_f",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")
        n = self.layers
        gal = self.volume_gal / n
        set_ = object.__setattr__
        set_(self, "layer_gal", gal)
        set_(self, "layer_btu_f", gal * WATER_BTU_PER_GAL_F)
        set_(self, "centers", tuple((i + 0.5) / n for i in range(n)))
        overlap = [
            max(0.0, min(high, (i + 1) / n) - max(low, i / n)) for i in range(n)
        ]
        total = sum(overlap)
        set_(self, "condenser_weights", tuple(w / total for w in overlap))

    def element_layer(self, zone: Zone) -> int:
        """The layer the ``zone`` element heats: the one at its height."""
        h = self.upper_element if zone == "upper" else self.lower_element
        return min(self.layers - 1, int(h * self.layers))


def layout(params: HeaterParams) -> Layout:
    """The stratified tank ``params`` describe. The jacket's UA is its
    reference value (``LossParams.ua_btu_hr_f``, else the baseline),
    constant: the layers' loss stays linear in their temperatures."""
    t, loss = params.tank, params.loss
    return Layout(
        volume_gal=t.volume_gal,
        layers=t.layers,
        upper_probe=t.upper_probe_height,
        lower_probe=t.lower_probe_height,
        upper_element=t.upper_element_height,
        lower_element=t.lower_element_height,
        condenser_span=t.condenser_span,
        inlet_mix_gal=t.inlet_mix_gal,
        ua_btu_hr_f=(
            loss.ua_btu_hr_f
            if loss.ua_btu_hr_f is not None
            else loss.ua_baseline_btu_hr_f
        ),
        ua_bottom_btu_hr_f=loss.ua_bottom_btu_hr_f,
        conductance_btu_hr_f=t.conductance_btu_hr_f,
    )


def _layers(lay: Layout, state: TankState) -> tuple[float, ...]:
    if len(state.layers_f) != lay.layers:
        raise ValueError(
            f"the state has {len(state.layers_f)} layers, "
            f"the layout {lay.layers}"
        )
    return state.layers_f


def energy_btu(lay: Layout, state: TankState) -> float:
    """The tank's heat above 0 °F, BTU."""
    return lay.layer_btu_f * sum(_layers(lay, state))


# ── operators ──


def mix(state: TankState) -> TankState:
    """``state`` with every inversion turned over: adjacent layers whose
    lower is warmer pool to their mean (pool-adjacent-violators), so the
    result rises from the bottom and holds the same heat. A stable
    state is returned as it is."""
    layers = state.layers_f
    if all(a <= b for a, b in pairwise(layers)):
        return state
    pools: list[tuple[float, int]] = []
    for t in layers:
        total, count = t, 1
        while pools and pools[-1][0] * count > total * pools[-1][1]:
            below, n = pools.pop()
            total, count = total + below, count + n
        pools.append((total, count))
    out: list[float] = []
    for total, count in pools:
        out.extend([total / count] * count)
    return TankState(tuple(out))


def lose(
    lay: Layout, state: TankState, air_f: float, hours: float
) -> tuple[TankState, float]:
    """``state`` after ``hours`` losing heat to ``air_f``, and the heat
    lost, BTU: each layer relaxes toward the air exactly, through its
    share of the jacket's UA, the bottom layer through the bottom's
    too."""
    layers = _layers(lay, state)
    if hours <= 0.0:
        return state, 0.0
    side = lay.ua_btu_hr_f / lay.layers
    out: list[float] = []
    for i, t in enumerate(layers):
        ua = side + (lay.ua_bottom_btu_hr_f if i == 0 else 0.0)
        out.append(
            air_f + (t - air_f) * math.exp(-ua * hours / lay.layer_btu_f)
        )
    lost = lay.layer_btu_f * (sum(layers) - sum(out))
    return TankState(tuple(out)), lost


def conduct(lay: Layout, state: TankState, hours: float) -> TankState:
    """``state`` after ``hours`` of conduction between neighbouring
    layers (``Layout.conductance_btu_hr_f``), none through the ends:
    explicit steps, each closing at most half of a gap, so no layer
    passes its neighbours and the heat is the same."""
    layers = _layers(lay, state)
    if hours <= 0.0 or lay.conductance_btu_hr_f <= 0.0:
        return state
    # Layers in series: each interface conducts the column's
    # conductance times their number.
    rate = lay.conductance_btu_hr_f * lay.layers / lay.layer_btu_f
    steps = max(1, math.ceil(rate * hours / _CONDUCT_SHARE))
    r = rate * hours / steps
    t = list(layers)
    n = len(t)
    for _ in range(steps):
        flux = [r * (t[i + 1] - t[i]) for i in range(n - 1)]
        t = [
            t[i]
            + (flux[i] if i < n - 1 else 0.0)
            - (flux[i - 1] if i > 0 else 0.0)
            for i in range(n)
        ]
    return TankState(tuple(t))


def add_heat(lay: Layout, state: TankState, btu: Sequence[float]) -> TankState:
    """``state`` with ``btu`` put into each layer, then mixed: heat put
    in below warmer water rises through it."""
    layers = _layers(lay, state)
    if len(btu) != len(layers):
        raise ValueError("one heat per layer")
    return mix(
        TankState(
            tuple(
                t + q / lay.layer_btu_f
                for t, q in zip(layers, btu, strict=True)
            )
        )
    )


def condenser_water_f(lay: Layout, state: TankState) -> float:
    """The water the condenser heats, °F: the layers over its span,
    weighted by how much of each it wraps."""
    return sum(
        w * t
        for w, t in zip(lay.condenser_weights, _layers(lay, state), strict=True)
    )


def condenser_heat(lay: Layout, btu: float) -> tuple[float, ...]:
    """``btu`` of the condenser's spread over the layers it wraps."""
    return tuple(btu * w for w in lay.condenser_weights)


def element_heat(lay: Layout, zone: Zone, btu: float) -> tuple[float, ...]:
    """``btu`` of the ``zone`` element's, into its layer."""
    at = lay.element_layer(zone)
    return tuple(btu if i == at else 0.0 for i in range(lay.layers))


# ── flow ──


@dataclass(frozen=True)
class _Column:
    """The water leaving the top, and the column after, for a flow in at
    ``inflow_f`` from ``state``: the inlet zone, the bottom
    ``inlet_mix_gal``, well mixed from the flow's start, feeds a plug
    above it, which leaves at the top."""

    lay: Layout
    layers: tuple[float, ...]
    inflow_f: float
    #: Each layer's water as a line through its mean, °F per gallon up,
    #: limited so no layer's edge passes a neighbour's mean (``_slope``):
    #: a front inside a layer moves on sharp, not smeared over it.
    slopes: tuple[float, ...] = field(init=False, repr=False)
    #: The layers integrated from the bottom to each layer's foot.
    feet: tuple[float, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        h, t = self.lay.layer_gal, self.layers
        slopes = [0.0] * len(t)
        for i in range(1, len(t) - 1):
            slopes[i] = _slope(t[i] - t[i - 1], t[i + 1] - t[i]) / h
        feet = [0.0]
        for x in t[:-1]:
            feet.append(feet[-1] + h * x)
        object.__setattr__(self, "slopes", tuple(slopes))
        object.__setattr__(self, "feet", tuple(feet))

    def at(self, i: int, v: float) -> float:
        """Layer ``i``'s water ``v`` gallons up the column, °F."""
        return self.layers[i] + self.slopes[i] * (
            v - (i + 0.5) * self.lay.layer_gal
        )

    @property
    def mix_gal(self) -> float:
        return min(self.lay.inlet_mix_gal, self.lay.volume_gal)

    @property
    def plug_gal(self) -> float:
        return self.lay.volume_gal - self.mix_gal

    def integral(self, v: float) -> float:
        """The layers' temperature integrated from the bottom to ``v``
        gallons up, gal·°F."""
        h = self.lay.layer_gal
        v = min(max(v, 0.0), self.lay.volume_gal)
        i = min(self.lay.layers - 1, int(v / h))
        # The line's integral from the layer's foot to ``v``.
        return (
            self.feet[i]
            + (v - i * h) * (self.at(i, v) + self.at(i, i * h)) / 2.0
        )

    @property
    def mix_start_f(self) -> float:
        """The inlet zone's temperature as the flow starts: its water,
        mixed."""
        if self.mix_gal <= 0.0:
            return self.inflow_f
        return self.integral(self.mix_gal) / self.mix_gal

    def mix_f(self, gal: float) -> float:
        """The inlet zone's temperature after ``gal`` in."""
        if self.mix_gal <= 0.0:
            return self.inflow_f
        return self.inflow_f + (self.mix_start_f - self.inflow_f) * math.exp(
            -gal / self.mix_gal
        )

    def mix_out(self, a: float, b: float) -> float:
        """What the inlet zone passed up between ``a`` and ``b`` gallons
        in, integrated, gal·°F."""
        if self.mix_gal <= 0.0:
            return (b - a) * self.inflow_f
        return (b - a) * self.inflow_f + (
            self.mix_start_f - self.inflow_f
        ) * self.mix_gal * (
            math.exp(-a / self.mix_gal) - math.exp(-b / self.mix_gal)
        )

    def after(self, gal: float, a: float, b: float) -> float:
        """The column ``gal`` in, integrated from ``a`` to ``b`` gallons
        up, gal·°F: the inlet zone at its temperature then, above it
        what it passed up (the latest lowest), and above that the plug
        that was, moved up by ``gal``."""
        m = self.mix_gal
        total = 0.0
        lo, hi = max(a, 0.0), min(b, m)
        if hi > lo:
            total += (hi - lo) * self.mix_f(gal)
        lo, hi = max(a, m), min(b, m + min(gal, self.plug_gal))
        if hi > lo:
            # Water at ``v`` left the inlet zone ``gal - (v - m)`` in.
            total += self.mix_out(gal - (hi - m), gal - (lo - m))
        lo, hi = max(a, m + gal), min(b, self.lay.volume_gal)
        if hi > lo:
            total += self.integral(hi - gal) - self.integral(lo - gal)
        return total

    def plug(self) -> Iterator[tuple[float, float]]:
        """The plug's water leaving the top in turn, as (gal, °F): each
        layer's, down to the inlet zone, in ``_PIECES`` along its line."""
        lay, m = self.lay, self.mix_gal
        h = lay.layer_gal
        for i in reversed(range(lay.layers)):
            foot, top = max(i * h, m), (i + 1) * h
            if top <= foot:
                return
            gal = (top - foot) / _PIECES
            for k in range(_PIECES):
                yield gal, self.at(i, top - (k + 0.5) * gal)

    def leaving(self) -> Iterator[tuple[float, float]]:
        """The water leaving the top in turn, as (gal, °F): the plug's,
        then what the inlet zone passes up, in pieces of ``_TAIL_GAL``
        (all of it at the inflow's temperature with no inlet zone)."""
        yield from self.plug()
        m = self.mix_gal
        if m <= 0.0:
            yield math.inf, self.inflow_f
            return
        x = 0.0
        while True:
            yield _TAIL_GAL, self.mix_f(x + _TAIL_GAL / 2.0)
            x += _TAIL_GAL


@dataclass(frozen=True)
class Flowed:
    """A flow's result: the tank after, and the heat the tank lost to
    it (what left less what came in), BTU."""

    state: TankState
    heat_btu: float


def flow(lay: Layout, state: TankState, gal: float, inflow_f: float) -> Flowed:
    """``gal`` gallons in at the bottom at ``inflow_f``, and as much out
    at the top: through the inlet zone, then as a plug (``_Column``),
    solved exactly and remapped onto the layers by exact integrals,
    then mixed (an inflow warmer than the bottom rises)."""
    layers = _layers(lay, state)
    if gal <= 0.0:
        return Flowed(state, 0.0)
    col = _Column(lay, layers, inflow_f)
    h = lay.layer_gal
    n = lay.layers
    after = tuple(
        col.after(gal, i * h, lay.volume_gal if i == n - 1 else (i + 1) * h) / h
        for i in range(n)
    )
    new = mix(TankState(after))
    return Flowed(new, lay.layer_btu_f * (sum(layers) - sum(new.layers_f)))


# ── draws through the valve ──


def _tank_share(
    temp_f: float, inflow_f: float, valve: tuple[float, float]
) -> float:
    """The share of a delivered gallon the tank gives with ``temp_f``
    leaving its top (``physics.draw.hot_fraction``): all of it when it
    is no warmer than the cold side, which the valve then has nothing
    to temper."""
    if temp_f <= inflow_f:
        return 1.0
    return hot_fraction(temp_f, delivery_temp_f(temp_f, *valve), inflow_f)


@dataclass(frozen=True)
class Drawn:
    """A delivered draw's result: the tank after, the tank water it
    took, gal, the heat the tank lost, BTU, and the last water out of
    the top, °F."""

    state: TankState
    withdrawn_gal: float
    heat_btu: float
    last_f: float


def draw(
    lay: Layout,
    state: TankState,
    delivered_gal: float,
    inflow_f: float,
    valve: tuple[float, float] = NO_VALVE,
) -> Drawn:
    """``delivered_gal`` gallons at the tap through the mixing valve
    ``valve`` (intercept, slope: ``physics.draw.delivery_temp_f``), the
    mains at ``inflow_f`` on its cold side and refilling the tank. The
    tank water it takes is solved from the water leaving the top in
    turn, each gallon of it delivering ``1 / hot_fraction`` at the tap;
    the tank then flows that much (``flow``)."""
    layers = _layers(lay, state)
    if delivered_gal <= 0.0:
        return Drawn(state, 0.0, 0.0, layers[-1])
    col = _Column(lay, layers, inflow_f)
    remaining, withdrawn, last = delivered_gal, 0.0, layers[-1]
    for gal, temp in col.leaving():
        last = temp
        share = _tank_share(temp, inflow_f, valve)
        if share <= 0.0:
            # The valve takes nothing from the tank: the cold side
            # delivers the rest.
            break
        if gal / share >= remaining:
            withdrawn += remaining * share
            break
        withdrawn += gal
        remaining -= gal / share
    flowed = flow(lay, state, withdrawn, inflow_f)
    return Drawn(flowed.state, withdrawn, flowed.heat_btu, last)


def deliverable_gal(
    lay: Layout,
    state: TankState,
    line_f: float,
    inflow_f: float,
    valve: tuple[float, float] = NO_VALVE,
) -> float:
    """The gallons the tap gets at ``line_f`` or warmer before it runs
    under, the mains at ``inflow_f``: the delivered water is the tank's
    tempered by the valve, never warmer than the tank's. Summed over the
    water leaving the top in turn, to the first that delivers under the
    line; the inlet zone's passes to where its temperature reaches the
    line's (``line_f``, or the tank temperature the valve delivers it
    from), in closed form."""
    layers = _layers(lay, state)
    intercept, slope = valve
    if slope > 0.0:
        need = max(line_f, (line_f - intercept) / slope)
    elif intercept >= line_f:
        need = line_f
    else:
        return 0.0
    col = _Column(lay, layers, inflow_f)
    total = 0.0
    for gal, temp in col.plug():
        if temp < need:
            return total
        total += gal / _tank_share(temp, inflow_f, valve)
    if inflow_f >= need:
        # What comes in is at the line already.
        return math.inf
    m, start = col.mix_gal, col.mix_start_f
    if m <= 0.0 or start < need:
        return total
    # The inlet zone's water reaches the top: it passes ``need`` or
    # warmer for ``m · ln((start − in) / (need − in))`` gallons.
    span = m * math.log((start - inflow_f) / (need - inflow_f))
    pieces = 64
    dx = span / pieces
    for k in range(pieces):
        temp = col.mix_f((k + 0.5) * dx)
        total += dx / _tank_share(temp, inflow_f, valve)
    return total


# ── the probes ──


def _read(lay: Layout, layers: Sequence[float], height: float) -> float:
    """``layers`` at ``height``, linear between the layers' middles,
    the end layers' beyond them."""
    c = lay.centers
    if height <= c[0]:
        return layers[0]
    if height >= c[-1]:
        return layers[-1]
    i = min(lay.layers - 2, int(height * lay.layers - 0.5))
    f = (height - c[i]) / (c[i + 1] - c[i])
    return layers[i] + (layers[i + 1] - layers[i]) * f


def observe(lay: Layout, state: TankState) -> tuple[float, float]:
    """What the upper and the lower probes read, °F."""
    layers = _layers(lay, state)
    return _read(lay, layers, lay.upper_probe), _read(
        lay, layers, lay.lower_probe
    )


def _shape(lay: Layout) -> tuple[float, ...]:
    """The profile ``estimate`` builds from, as a share of the way from
    the lower probe's reading to the upper's: flat below the lower
    probe and above the upper, linear between, scaled so the probes
    read 0 and 1 exactly."""
    lo, hi = lay.lower_probe, lay.upper_probe
    s = tuple(min(1.0, max(0.0, (c - lo) / (hi - lo))) for c in lay.centers)
    a, b = _read(lay, s, lo), _read(lay, s, hi)
    return tuple((v - a) / (b - a) for v in s)


def estimate(lay: Layout, upper_f: float, lower_f: float) -> TankState:
    """A profile the probes read as ``upper_f`` and ``lower_f``
    (``observe``): the lower probe's reading below it, the upper's above
    it, linear between."""
    return TankState(
        tuple(lower_f + (upper_f - lower_f) * s for s in _shape(lay))
    )


def assimilate(
    lay: Layout,
    state: TankState,
    upper_f: float,
    lower_f: float,
    gain: float = 1.0,
) -> TankState:
    """``state`` corrected toward the probes' readings: ``gain`` of what
    they read off it laid over it in ``estimate``'s shape, so at a gain
    of 1 the probes read ``upper_f`` and ``lower_f`` exactly. Not mixed:
    a correction that inverts the profile is the caller's to mix."""
    layers = _layers(lay, state)
    u, lo = observe(lay, state)
    du, dl = gain * (upper_f - u), gain * (lower_f - lo)
    return TankState(
        tuple(
            t + dl + (du - dl) * s
            for t, s in zip(layers, _shape(lay), strict=True)
        )
    )


# ── the walk ──


@dataclass(frozen=True, kw_only=True)
class Compressor:
    """The compressor running: drawing its map's power from ``on_at``,
    heating from ``heats_at`` (after its start hold), both to ``off_at``
    (None: past the walk's end). Its map reads the condenser's water
    (``condenser_water_f``)."""

    params: CompressorParams
    on_at: datetime
    heats_at: datetime
    off_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class Element:
    """An element running from ``on_at`` to ``off_at`` (None: past the
    walk's end), drawing ``watts``. Its heat reaches the water ``lag``
    later (the dead time), all of it."""

    zone: Zone
    watts: float
    on_at: datetime
    off_at: datetime | None = None
    lag: timedelta = timedelta(0)


@dataclass(frozen=True, kw_only=True)
class Heating:
    """What heats the tank over a walk."""

    compressor: Compressor | None = None
    elements: tuple[Element, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Flowing:
    """Water flowing through the tank from ``start`` to ``end`` at
    ``gpm``, coming in at ``inflow_f``."""

    start: datetime
    end: datetime
    gpm: float
    inflow_f: float


@dataclass(frozen=True, kw_only=True)
class Delivered:
    """A delivered draw at ``at`` (``draw``)."""

    at: datetime
    gal: float
    inflow_f: float


@dataclass(frozen=True)
class Books:
    """Where a walk's heat went, BTU, and its electricity, Wh. The
    tank's heat moves by ``compressor_btu + element_btu - loss_btu -
    flowing_btu - drawn_btu``."""

    loss_btu: float = 0.0
    compressor_btu: float = 0.0
    compressor_wh: float = 0.0
    element_btu: float = 0.0
    element_wh: float = 0.0
    flowing_btu: float = 0.0
    drawn_btu: float = 0.0
    #: The tank water the delivered draws took, gal.
    withdrawn_gal: float = 0.0

    def __add__(self, other: Books) -> Books:
        return Books(
            *(
                getattr(self, f.name) + getattr(other, f.name)
                for f in fields(self)
            )
        )

    @property
    def net_btu(self) -> float:
        """The heat the tank gained."""
        return (
            self.compressor_btu
            + self.element_btu
            - self.loss_btu
            - self.flowing_btu
            - self.drawn_btu
        )


@dataclass(frozen=True)
class Walked:
    """A walk's result: the tank where it ended, ``end`` (the stop's
    instant when ``stopped``), its books, and the tank at each step's
    end, the start's first."""

    state: TankState
    end: datetime
    stopped: bool
    books: Books
    path: tuple[tuple[datetime, TankState], ...]


def _overlap_h(
    a: datetime, b: datetime, start: datetime, end: datetime | None
) -> float:
    lo = max(a, start)
    hi = b if end is None else min(b, end)
    return max(0.0, (hi - lo).total_seconds() / 3600.0)


def _grid_after(t: datetime, step: timedelta) -> datetime:
    """The first instant after ``t`` on the clock's ``step`` grid."""
    k = math.floor((t - _EPOCH) / step) + 1
    return _EPOCH + step * k


@dataclass(frozen=True)
class _Walk:
    lay: Layout
    air_f: Callable[[datetime], float]
    heating: Heating
    flowing: tuple[Flowing, ...]
    draws: tuple[Delivered, ...]
    valve: tuple[float, float]

    def instants(self, start: datetime, end: datetime) -> list[datetime]:
        """Where a step must end: wherever what acts on the tank
        changes."""
        out: set[datetime] = set()
        c = self.heating.compressor
        if c is not None:
            out.update(x for x in (c.on_at, c.heats_at, c.off_at) if x)
        for e in self.heating.elements:
            out.update((e.on_at, e.on_at + e.lag))
            if e.off_at is not None:
                out.update((e.off_at, e.off_at + e.lag))
        for f in self.flowing:
            out.update((f.start, f.end))
        out.update(d.at for d in self.draws)
        return sorted(x for x in out if start < x < end)

    def active(self, t: datetime) -> bool:
        """Whether anything heats or flows from ``t``."""

        def on(a: datetime, b: datetime | None) -> bool:
            return a <= t and (b is None or t < b)

        c = self.heating.compressor
        if c is not None and on(c.on_at, c.off_at):
            return True
        for e in self.heating.elements:
            off = None if e.off_at is None else e.off_at + e.lag
            if on(e.on_at, off):
                return True
        return any(on(f.start, f.end) for f in self.flowing)

    def drawn(self, t: datetime, state: TankState) -> tuple[TankState, Books]:
        """The draws at ``t`` taken, in order of size."""
        books = Books()
        for d in sorted(
            (d for d in self.draws if d.at == t), key=lambda d: d.gal
        ):
            out = draw(self.lay, state, d.gal, d.inflow_f, self.valve)
            state = out.state
            books += Books(
                drawn_btu=out.heat_btu, withdrawn_gal=out.withdrawn_gal
            )
        return state, books

    def step(
        self, a: datetime, b: datetime, state: TankState
    ) -> tuple[TankState, Books]:
        """The tank from ``a`` (the draws there taken) to ``b``: the
        heat in, the flows, the jacket, conduction, then any inversion
        turned over."""
        lay = self.lay
        hours = (b - a).total_seconds() / 3600.0
        air = self.air_f(a)
        heat = [0.0] * lay.layers
        books = Books()
        c = self.heating.compressor
        if c is not None:
            water = condenser_water_f(lay, state)
            q = heat_btu_h(c.params, air, water) * _overlap_h(
                a, b, c.heats_at, c.off_at
            )
            wh = power_w(c.params, air, water) * _overlap_h(
                a, b, c.on_at, c.off_at
            )
            heat = [
                x + y for x, y in zip(heat, condenser_heat(lay, q), strict=True)
            ]
            books += Books(compressor_btu=q, compressor_wh=wh)
        for e in self.heating.elements:
            off = None if e.off_at is None else e.off_at + e.lag
            q = e.watts * BTU_PER_WH * _overlap_h(a, b, e.on_at + e.lag, off)
            wh = e.watts * _overlap_h(a, b, e.on_at, e.off_at)
            heat = [
                x + y
                for x, y in zip(heat, element_heat(lay, e.zone, q), strict=True)
            ]
            books += Books(element_btu=q, element_wh=wh)
        if any(heat):
            state = add_heat(lay, state, heat)
        for f in self.flowing:
            gal = f.gpm * 60.0 * _overlap_h(a, b, f.start, f.end)
            if gal > 0.0:
                out = flow(lay, state, gal, f.inflow_f)
                state = out.state
                books += Books(flowing_btu=out.heat_btu)
        state, lost = lose(lay, state, air, hours)
        books += Books(loss_btu=lost)
        state = mix(conduct(lay, state, hours))
        return state, books


def walk(
    lay: Layout,
    state: TankState,
    start: datetime,
    end: datetime,
    *,
    air_f: Callable[[datetime], float],
    heating: Heating = Heating(),
    flowing: Sequence[Flowing] = (),
    draws: Sequence[Delivered] = (),
    valve: tuple[float, float] = NO_VALVE,
    stop: Callable[[TankState], bool] | None = None,
    idle_step: timedelta = IDLE_STEP,
    active_step: timedelta = ACTIVE_STEP,
) -> Walked:
    """The tank from ``start`` to ``end`` under ``heating``, the
    ``flowing`` draws and the delivered ``draws`` (those in ``[start,
    end)``, through ``valve``), the air ``air_f`` reads.

    Steps end on the clock's grid, every ``idle_step`` with nothing
    heating or flowing and every ``active_step`` while something is, and
    wherever what acts changes, so a walk split at a step's end is the
    walk whole. Within a step the draws at its start are taken, then the
    heat goes in (the condenser's by its map at the air and the water
    at the step's start), the water flows, the jacket loses, the layers
    conduct, and inversions turn over. ``stop``, read after each step,
    ends the walk at the first instant it holds, to
    ``CUT_RESOLUTION``."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("the walk's instants are aware")
    _layers(lay, state)
    w = _Walk(
        lay,
        air_f,
        heating,
        tuple(flowing),
        tuple(d for d in draws if start <= d.at < end),
        valve,
    )
    instants = w.instants(start, end)
    books = Books()
    path: list[tuple[datetime, TankState]] = [(start, state)]
    t = start
    if stop is not None and stop(state):
        return Walked(state, t, True, books, tuple(path))
    while t < end:
        step = active_step if w.active(t) else idle_step
        nxt = min([_grid_after(t, step), end, *(x for x in instants if x > t)])
        if stop is not None:
            taken, b = w.drawn(t, state)
            if stop(taken):
                # A draw here meets it.
                path.append((t, taken))
                return Walked(taken, t, True, books + b, tuple(path))
        new, b = _step(w, t, nxt, state)
        if stop is not None and stop(new):
            at, new, b = _cut(w, t, nxt, state, stop)
            path.append((at, new))
            return Walked(new, at, True, books + b, tuple(path))
        books += b
        state, t = new, nxt
        path.append((t, state))
    return Walked(state, t, False, books, tuple(path))


def _step(
    w: _Walk, a: datetime, b: datetime, state: TankState
) -> tuple[TankState, Books]:
    taken, drawn = w.drawn(a, state)
    new, books = w.step(a, b, taken)
    return new, drawn + books


def _cut(
    w: _Walk,
    a: datetime,
    b: datetime,
    state: TankState,
    stop: Callable[[TankState], bool],
) -> tuple[datetime, TankState, Books]:
    """The first instant in ``(a, b]`` ``stop`` holds, to
    ``CUT_RESOLUTION``, and the tank and the books from ``a`` to it."""
    lo, hi = a, b
    while hi - lo > CUT_RESOLUTION:
        mid = lo + (hi - lo) / 2
        if stop(_step(w, a, mid, state)[0]):
            hi = mid
        else:
            lo = mid
    new, books = _step(w, a, hi, state)
    return hi, new, books
