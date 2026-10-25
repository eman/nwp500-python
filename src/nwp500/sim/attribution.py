"""Why each **recorded** start happened: the heater's own trigger, or a
write (``sim.record.Record.starts``' starts, ``writes``' writes).

- **A write's start** comes within ``WRITE_EVIDENCE`` of the write: a
  setpoint write that starts the compressor does so a median 30 s later
  (``ControllerParams.write_start_lag_s``), and a mode write's start is
  scored over two minutes. A write made inside the **restart lockout**
  starts the compressor when the lockout ends instead, so such a start
  is the write's if it comes within ``WRITE_EVIDENCE`` of the lockout's
  end, either side of it: the modelled 330 s is a point in a measured
  spread. A write explains a start before the heater's own triggers do:
  it is the more specific cause.
- **The heater's drop.** A compressor start within ``WRITE_EVIDENCE``
  of the heater dropping an element mode, or at the lockout's end after
  one, when the drop is the latest change before it: the heater's,
  trigger ``mode_dropped``, as the simulation names it.
- **The heater's own**, with its trigger when one fits
  (``tou_triggers``): ``upper_at_tou_open`` within ``WRITE_EVIDENCE``
  after a window opens, or later inside the window with the upper zone
  at or within ``UPPER_SLACK_F`` of ``UPPER_DEFICIT_F`` short of the
  setpoint; ``lower_at_tou_close`` within it after one closes; ``lower``
  with the lower zone at or within ``LOWER_SLACK_F`` of ``hp_lower_on``;
  for an element, ``energy_saver_upper_on`` in Energy Saver,
  ``high_demand_upper_short`` for High Demand's upper element and
  ``electric_lower_after_upper`` for Electric's lower element. A start
  none of them fits keeps a null trigger: the record shows the heater
  started and no modelled rule says why.
- **Running**: already on when the span began.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from nwp500.sim.controller import ElementTrigger
from nwp500.sim.inputs import ELECTRIC, ENERGY_SAVER, HIGH_DEMAND
from nwp500.sim.params import ControllerParams
from nwp500.sim.record import Recorded
from nwp500.sim.tou_triggers import UPPER_DEFICIT_F, Trigger

#: The restart lockout a write's start waits out.
RESTART_LOCKOUT = ControllerParams().restart_lockout
#: How soon after a write a start is the write's.
WRITE_EVIDENCE = timedelta(minutes=2)
#: The lower zone this close above ``hp_lower_on`` at a start is the
#: lower trigger: the probe reports in 0.18 °F steps and lags a draw.
LOWER_SLACK_F = 1.0
#: The upper zone this close to ``UPPER_DEFICIT_F`` short at a start
#: inside a window is the upper trigger: two of the probe's 0.18 °F
#: steps, which flicker by one.
UPPER_SLACK_F = 0.36

Cause = Literal["heater", "write", "running"]


@dataclass(frozen=True)
class Attributed:
    at: datetime
    cause: Cause
    trigger: Trigger | ElementTrigger | None
    source: Literal["compressor", "element"]
    zone: Literal["upper", "lower"] | None
    #: The recorded write it is attributed to.
    write_at: datetime | None = None


def attribute(
    starts: Sequence[Recorded],
    writes: Sequence[datetime],
    *,
    stops: Sequence[datetime] = (),
    openings: Sequence[datetime] = (),
    closings: Sequence[datetime] = (),
    lower_at: Callable[[datetime], float | None] = lambda _: None,
    hp_lower_on_f: float | None = None,
    mode_at: Callable[[datetime], int | None] = lambda _: None,
    drops: Sequence[datetime] = (),
    upper_short_at: Callable[[datetime], float | None] = lambda _: None,
) -> list[Attributed]:
    """Each start with its cause (module docstring). ``writes`` are the
    recorded writes' instants; ``stops`` the compressor's off-edges;
    ``openings`` and ``closings`` the TOU window's edges as the heater
    marked them; ``mode_at`` the mode in force (a ``DhwOperationSetting``
    value); ``drops`` the instants the heater dropped an element mode;
    ``upper_short_at`` the setpoint in force less the upper zone."""
    out: list[Attributed] = []
    for s in sorted(starts, key=lambda s: s.at):
        if s.running:
            out.append(Attributed(s.at, "running", None, s.source, s.zone))
            continue
        latest_drop = max((d for d in drops if d <= s.at), default=None)
        latest_write = max((w for w in writes if w <= s.at), default=None)
        if (
            latest_drop is not None
            and (latest_write is None or latest_drop >= latest_write)
            and _event_for(s, latest_drop, stops) is not None
        ):
            out.append(
                Attributed(s.at, "heater", "mode_dropped", s.source, s.zone)
            )
            continue
        write = _write_for(s, writes, stops)
        if write is not None:
            out.append(Attributed(s.at, "write", None, s.source, s.zone, write))
            continue
        out.append(
            Attributed(
                s.at,
                "heater",
                _trigger(
                    s,
                    openings,
                    closings,
                    lower_at,
                    hp_lower_on_f,
                    mode_at,
                    upper_short_at,
                ),
                s.source,
                s.zone,
            )
        )
    return out


def _write_for(
    s: Recorded, writes: Sequence[datetime], stops: Sequence[datetime]
) -> datetime | None:
    before = [w for w in writes if w <= s.at]
    if not before:
        return None
    return _event_for(s, max(before), stops)


def _event_for(
    s: Recorded, w: datetime, stops: Sequence[datetime]
) -> datetime | None:
    """``w`` when a change at ``w`` explains the start ``s``: within
    ``WRITE_EVIDENCE``, or, for the compressor, made inside the restart
    lockout and ``s`` within ``WRITE_EVIDENCE`` of its end."""
    if s.at - w <= WRITE_EVIDENCE:
        return w
    if s.source != "compressor":
        return None
    stop = max((t for t in stops if t <= w), default=None)
    if stop is None or w >= stop + RESTART_LOCKOUT:
        return None
    ends = stop + RESTART_LOCKOUT
    return w if abs(s.at - ends) <= WRITE_EVIDENCE else None


def _trigger(
    s: Recorded,
    openings: Sequence[datetime],
    closings: Sequence[datetime],
    lower_at: Callable[[datetime], float | None],
    hp_lower_on_f: float | None,
    mode_at: Callable[[datetime], int | None],
    upper_short_at: Callable[[datetime], float | None] = lambda _: None,
) -> Trigger | ElementTrigger | None:
    def after(edges: Sequence[datetime]) -> bool:
        return any(timedelta(0) <= s.at - e <= WRITE_EVIDENCE for e in edges)

    if s.source == "element":
        mode = mode_at(s.at)
        if mode == ENERGY_SAVER and s.zone == "upper":
            return "energy_saver_upper_on"
        if mode == HIGH_DEMAND and s.zone == "upper":
            return "high_demand_upper_short"
        if mode == ELECTRIC and s.zone == "lower":
            return "electric_lower_after_upper"
        return None
    if after(openings):
        return "upper_at_tou_open"
    if after(closings):
        return "lower_at_tou_close"
    if _inside(s.at, openings, closings):
        short = upper_short_at(s.at)
        if short is not None and short >= UPPER_DEFICIT_F - UPPER_SLACK_F:
            return "upper_at_tou_open"
    lower = lower_at(s.at)
    if (
        lower is not None
        and hp_lower_on_f is not None
        and lower <= hp_lower_on_f + LOWER_SLACK_F
    ):
        return "lower"
    return None


def _inside(
    at: datetime, openings: Sequence[datetime], closings: Sequence[datetime]
) -> bool:
    """Whether a window was open at ``at``: an opening at or before it
    with no close between."""
    opened = max((o for o in openings if o <= at), default=None)
    return opened is not None and not any(opened < c <= at for c in closings)
