"""A hot-water meter's flow, from what it reports.

A meter reports two series: the volume since its previous report (a
signed number per report), and a forward flow rate that goes silent at
rest and reports only when it changes. Neither alone is the flow:

- the rate can sit unreported through a steady draw, and at one
  installation the meter read whole draws backwards with the rate
  silent;
- the volume is exact, but only over a window long enough to hold a
  few reports.

So the flow on a grid is the net volume over a trailing window wherever
that holds up for long enough, and the forward rate elsewhere. The sign
is ignored: the same meter reported whole draws and circulation runs as
negative volume. A sustained run counts from its first step
(``backfill``), as a history is read; live, only once it has lasted.

These are the reference implementation's rules, measured against its
draw detector over a month of one installation's record: a plateau of
the cold supply (``sim.cold_supply``) found every long draw the detector
found, where the rate alone missed one in five.
"""

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

#: A reading: an instant and a value.
Reading = tuple[datetime, float]

#: The grid the flow is read on.
STEP = timedelta(seconds=10)
#: The trailing window the net volume is summed over.
WINDOW = timedelta(seconds=90)
#: The flow that is water moving, gal/min.
DRAW_GPM = 0.3
#: How long the net flow must hold at ``DRAW_GPM`` to be trusted.
SUSTAIN = timedelta(seconds=120)
#: How long a forward-rate report holds.
RATE_HOLD = timedelta(seconds=60)


def flow_gpm(
    volume: Sequence[Reading],
    rate: Sequence[Reading],
    start: datetime,
    end: datetime,
    *,
    backfill: bool = True,
    step: timedelta = STEP,
    window: timedelta = WINDOW,
    draw_gpm: float = DRAW_GPM,
    sustain: timedelta = SUSTAIN,
    rate_hold: timedelta = RATE_HOLD,
) -> list[Reading]:
    """The meter's flow, gal/min, every ``step`` from ``start`` to
    ``end``, on whole multiples of ``step`` (from the Unix epoch), so a
    draw's edges do not move with the instant it is read at.

    ``volume`` is each report's volume since the previous one, gallons,
    at the instant of the report (it belongs to the interval the report
    closes); ``rate`` the forward rate's reports, gal/min. At each step:

    - inside a sustained run (the net flow over ``window`` at or above
      ``draw_gpm`` for ``sustain`` or more), the net flow's magnitude;
    - otherwise the forward rate, held for ``rate_hold``, when it is
      above ``draw_gpm``;
    - otherwise 0.

    With ``backfill`` a sustained run counts from its first step; without
    it, only from the step that completes ``sustain``. A step at or above
    ``draw_gpm`` is water moving: the draw ticks ``sim.cold_supply``
    reads."""
    if step <= timedelta(0) or end < start:
        return []
    reports = sorted(volume, key=lambda r: r[0])
    rates = sorted(rate, key=lambda r: r[0])
    span_s = window.total_seconds()
    times: list[datetime] = []
    epoch = datetime(1970, 1, 1, tzinfo=start.tzinfo or UTC)
    t = epoch + step * math.ceil((start - epoch) / step)
    while t <= end:
        times.append(t)
        t += step
    # The net flow: reports in (t - window, t], summed, then per minute.
    net: list[float] = []
    lo = hi = 0
    total = 0.0
    for t in times:
        while hi < len(reports) and reports[hi][0] <= t:
            total += reports[hi][1]
            hi += 1
        while lo < hi and reports[lo][0] <= t - window:
            total -= reports[lo][1]
            lo += 1
        net.append(abs(total) / span_s * 60.0)
    # The sustained runs.
    need = round(sustain / step)
    sustained = [False] * len(times)
    i = 0
    while i < len(times):
        if net[i] < draw_gpm:
            i += 1
            continue
        j = i
        while j + 1 < len(times) and net[j + 1] >= draw_gpm:
            j += 1
        if j - i >= need:
            first = i if backfill else i + need
            for k in range(first, j + 1):
                sustained[k] = True
        i = j + 1
    # The forward rate, held.
    out: list[Reading] = []
    r = -1
    for k, t in enumerate(times):
        if sustained[k]:
            out.append((t, net[k]))
            continue
        while r + 1 < len(rates) and rates[r + 1][0] <= t:
            r += 1
        held = r >= 0 and t - rates[r][0] <= rate_hold
        forward = rates[r][1] if held else 0.0
        out.append((t, forward if forward > draw_gpm else 0.0))
    return out
