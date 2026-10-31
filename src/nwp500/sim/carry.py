"""What a walk leaves behind: walks carried on through one tail.

A walk's electricity over its own span says nothing of the tank it
leaves. A change that heats late, or not at all, can come out cheapest
over its day and owe the difference the next: a tank left 30 °F short
is heated again, at whatever the hour of that reheat costs. Two
changes (``Commands``) are weighed on an equal footing only when each
walk is carried on until what they left no longer differs.

``carry_on`` walks every walk's end through the same ``tail``: the
heater in its standing settings (written at the tail's start over
whatever a walk left in force), the same draws, air and schedules.
Tails that end alike, the same layers with the same heating running,
leave nothing between the walks unvalued, so a walk's electricity and
its tail's, priced at any tariff, are the whole of what the change
costs. How alike the tails end is given (``Carried.residual_f``,
``Carried.residual_wh``, ``Carried.running_alike``): a tail too short
to settle them leaves that much out.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from nwp500.sim.api import simulate
from nwp500.sim.extensions import RecoveryModel
from nwp500.sim.inputs import Scenario
from nwp500.sim.params import HeaterParams
from nwp500.sim.physics.stratified import TankState, energy_btu, layout
from nwp500.sim.result import SimulationResult
from nwp500.sim.units import BTU_PER_WH

#: How near, °F in every layer, a tail's end must come to the first
#: walk's tail's for the two to count as settled (``Carried.settled``).
SETTLED_F = 0.5


@dataclass(frozen=True)
class Carried:
    """A walk and the tail walked on from where it ended."""

    walk: SimulationResult
    tail: SimulationResult
    #: The heat the tail ends with less the first walk's tail's, Wh:
    #: what this walk leaves that the tail did not value (positive,
    #: more heat left).
    residual_wh: float
    #: The largest difference of a layer at the tail's end from the
    #: first walk's tail's, °F.
    residual_f: float
    #: Whether the tail ends with the compressor and the elements
    #: running or not as the first walk's tail does: a run under way
    #: in one and not the other is heat one is still paying for.
    running_alike: bool = True

    @property
    def settled(self) -> bool:
        """Whether the tail ends as the first walk's tail does: within
        ``SETTLED_F`` in every layer, the same heating running."""
        return self.residual_f <= SETTLED_F and self.running_alike

    @property
    def input_wh(self) -> float | None:
        """The electricity of the walk and its tail, Wh. None when an
        interval of either could not be priced."""
        walk, tail = self.walk.input_wh, self.tail.input_wh
        return None if walk is None or tail is None else walk + tail

    def energy_by_slot(
        self, slot: timedelta = timedelta(hours=1)
    ) -> list[tuple[datetime, float | None]]:
        """The walk's and its tail's electricity per clock-aligned
        ``slot``, Wh, as ``SimulationResult.energy_by_slot`` gives it: a
        slot the two share holds both."""
        out: dict[datetime, float | None] = {}
        for at, wh in [
            *self.walk.energy_by_slot(slot),
            *self.tail.energy_by_slot(slot),
        ]:
            if at not in out:
                out[at] = wh
            else:
                held = out[at]
                out[at] = None if held is None or wh is None else held + wh
        return sorted(out.items())


def carry_on(
    walks: Sequence[SimulationResult],
    tail: Scenario,
    params: HeaterParams,
    *,
    recovery: RecoveryModel | None = None,
    tou_windows_in_force: Sequence[tuple[datetime, datetime]] | None = None,
    withheld_windows: Sequence[tuple[datetime, datetime]] = (),
    inlet_measured: bool = False,
    start_hold: Callable[[float | None], float] | None = None,
) -> tuple[Carried, ...]:
    """Each of ``walks`` walked on through ``tail`` from where it ended,
    in their order, each tail's end set beside the first's.

    ``tail`` is the span after the walks: its settings the heater's
    standing ones, its loads, environment and schedules what follows.
    Its ``state`` and ``history`` are each walk's end
    (``SimulationResult.end_state``, ``end_history``); its settings are
    written at its start over what the walk left. Every walk must end
    where ``tail`` starts. A tail long enough to take each tank through
    the recovery the heater makes anyway ends them alike
    (``Carried.settled``). A walk that ends in, or a tail that starts
    in, Vacation or Power Off with the other not is carried on afresh
    from the walk's layers and history, as ``simulate`` goes on from
    any (``resume_dropped_*`` in the tail's ``reasons``).

    The keyword inputs are ``simulate``'s, the same for every tail.
    ``recovery``, ``start_hold`` and ``inlet_measured`` go on as the
    walks had them: a walk made with a recovery model is carried on
    with it. ``tou_windows_in_force`` and ``withheld_windows`` are the
    tail's own, over its span: a walk's, before the tail starts, leave
    it with none.

    Raises ``ValueError`` when ``walks`` is empty, or a walk does not
    end where ``tail`` starts or carries no end, and
    ``engine.SimulationError`` when a walk cannot be completed.
    """
    if not walks:
        raise ValueError("no walks to carry on")
    tails: list[SimulationResult] = []
    for walk in walks:
        if walk.until != tail.start:
            raise ValueError(
                f"a walk ends at {walk.until.isoformat()}, the tail "
                f"starts at {tail.start.isoformat()}"
            )
        if walk.end_state is None or walk.end_history is None:
            raise ValueError("a walk carries no end to go on from")
        tails.append(
            simulate(
                tail.model_copy(
                    update={
                        "state": walk.end_state,
                        "history": walk.end_history,
                    }
                ),
                params,
                recovery=recovery,
                tou_windows_in_force=tou_windows_in_force,
                withheld_windows=withheld_windows,
                inlet_measured=inlet_measured,
                start_hold=start_hold,
            )
        )
    lay = layout(params)
    ends = [_layers(t) for t in tails]
    running = [_running(t) for t in tails]
    first = ends[0]
    first_wh = energy_btu(lay, TankState(first)) / BTU_PER_WH
    return tuple(
        Carried(
            walk=walk,
            tail=t,
            residual_wh=energy_btu(lay, TankState(end)) / BTU_PER_WH - first_wh,
            residual_f=max(abs(a - b) for a, b in zip(end, first, strict=True)),
            running_alike=on == running[0],
        )
        for walk, t, end, on in zip(walks, tails, ends, running, strict=True)
    )


def _running(result: SimulationResult) -> tuple[bool, bool]:
    end = result.end_state
    assert end is not None
    return end.compressor_running, end.element_running


def _layers(result: SimulationResult) -> tuple[float, ...]:
    end = result.end_state
    if end is None or end.layers_f is None:
        raise ValueError("a tail carries no layers at its end")
    return tuple(end.layers_f)
