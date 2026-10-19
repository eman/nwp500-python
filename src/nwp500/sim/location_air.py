"""The air where the heater stands, ahead of time, from an outdoor
forecast.

The heater reports the air at its intake now (``ambient_temperature``),
not what it will be. Wherever the heater stands, that air follows the
outdoor air, damped and late::

    air(t) = damping x outdoor(t - lag) + offset

``project`` lays a forecast out on a grid by that model, the outdoor
air interpolated in time and held past its ends, and anchors it to a
reading: the whole series moves by a constant so it passes through the
reading at the reading's own instant (not the series' start, which would
move it by the model's own daily swing between the two). Anchored, the
offset no longer matters; the damping and the lag shape the projection.

The anchor to use is the heater's own reading **while the compressor
runs**: the evaporator fan then draws the air it stands in past the
sensor, which read that air within 0.35 °F (sd 1.25) at one
installation from August to October, but up to about 2 °F warm from May
to July, and about 2.7 °F warm in a run's first 2 minutes. Idle, the
sensor sits in the cabinet and read about 6 °F warm there, by an amount
that varies with the air; an idle reading is a poor anchor.

The projection is for looking ahead. Unanchored over a record's quiet
windows, the same installation's ran about 6 °F cold, so it is no
substitute for a sensor's air in calibration.

``fit`` fits the damping, the offset and the lag on a history of such
readings against the outdoor air's history, from a public weather
service, say. ``SITE_LOCATION_AIR`` is one installation's, fitted against
a weather station there: an example, not a default.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np

#: A reading: an instant and a temperature, °F.
Reading = tuple[datetime, float]


@dataclass(frozen=True)
class LocationAirModel:
    """``air(t) = damping x outdoor(t - lag) + offset``, °F."""

    damping: float
    lag: timedelta
    offset_f: float

    def at(
        self, outdoor: Sequence[Reading], when: Sequence[datetime]
    ) -> list[float]:
        """The model's air at each of ``when``: the outdoor air
        interpolated in time at ``when - lag``, held past its ends."""
        # By elapsed instant: local datetimes in one zone compare by wall
        # clock, so a repeated hour's two halves would sort out of order.
        series = sorted(outdoor, key=lambda r: r[0].timestamp())
        if not series:
            raise ValueError("no outdoor readings")
        xs = np.array([t.timestamp() for t, _ in series])
        ys = np.array([v for _, v in series])
        # In elapsed time: a lag off a local wall clock would gain or
        # lose an hour across a daylight-saving change.
        lagged = np.array(
            [(t.astimezone(UTC) - self.lag).timestamp() for t in when]
        )
        return [
            float(v)
            for v in self.damping * np.interp(lagged, xs, ys) + self.offset_f
        ]


#: One installation's, fitted against a weather station there,
#: R = 0.915 at a 2 h lag (0.852 at none). Seasonal fits differed
#: (winter 0.505 / +29.8 °F, summer 0.595 / +32.9 °F): the single line
#: under-reads summer by about 4 °F unanchored.
SITE_LOCATION_AIR = LocationAirModel(
    damping=0.638, lag=timedelta(hours=2), offset_f=24.5
)


def project(
    model: LocationAirModel,
    outdoor: Sequence[Reading],
    start: datetime,
    end: datetime,
    *,
    step: timedelta = timedelta(minutes=10),
    anchor: Reading | None = None,
) -> tuple[Reading, ...]:
    """The air where the heater stands from ``start`` to ``end`` every
    ``step``, by ``model`` on the ``outdoor`` forecast, moved to pass
    through ``anchor`` (a reading and its instant) when given: the
    readings ``Environment.ambient_f`` takes. No outdoor forecast is no
    projection: empty, not an error, so the caller falls back to its
    own air."""
    if step <= timedelta(0):
        raise ValueError("step must be positive")
    if not outdoor:
        return ()
    # The grid in elapsed time, UTC: a local wall clock skips or repeats
    # an hour at a daylight-saving change.
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if end < start:
        raise ValueError("end must not be before start")
    when: list[datetime] = []
    t = start
    while t <= end:
        when.append(t)
        t += step
    air = model.at(outdoor, when)
    if anchor is not None:
        at, value = anchor
        shift = value - model.at(outdoor, [at])[0]
        if np.isfinite(shift):
            air = [a + shift for a in air]
    return tuple(zip(when, air, strict=True))


@dataclass(frozen=True)
class FittedLocationAir:
    """A fitted model, and how well it fits: Pearson's r at its lag, and
    the readings it was fitted on."""

    model: LocationAirModel
    r: float
    n: int


#: The lags ``fit`` tries, hours.
FIT_LAGS_H = tuple(h / 2 for h in range(0, 13))


def fit(
    readings: Sequence[Reading],
    outdoor: Sequence[Reading],
    *,
    lags_h: Sequence[float] = FIT_LAGS_H,
) -> FittedLocationAir:
    """The damping, offset and lag that best map the ``outdoor`` air's
    history onto ``readings`` of the air where the heater stands (the
    heater's own, while its compressor runs): least squares at each lag,
    the lag with the highest r kept. At least three readings."""
    if len(readings) < 3:
        raise ValueError("fit needs at least three readings")
    when = [t for t, _ in readings]
    y = np.array([v for _, v in readings])
    best: FittedLocationAir | None = None
    for lag_h in lags_h:
        lag = timedelta(hours=lag_h)
        x = np.array(LocationAirModel(1.0, lag, 0.0).at(outdoor, when))
        if float(np.std(x)) == 0.0:
            continue
        damping, offset = np.polyfit(x, y, 1)
        r = float(np.corrcoef(x, y)[0, 1])
        if best is None or r > best.r:
            best = FittedLocationAir(
                LocationAirModel(float(damping), lag, float(offset)),
                r,
                len(readings),
            )
    if best is None:
        raise ValueError("the outdoor air does not vary over the readings")
    return best
