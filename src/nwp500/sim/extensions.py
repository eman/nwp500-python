"""The core's extension points.

Each is a ``Protocol``.

- ``RecoveryModel``: a learned correction to the physics recovery,
  such as a model fitted to a heater's own recoveries. With none, the
  core serves the physics alone.
"""

from __future__ import annotations

from typing import Protocol

from nwp500.sim.heat_pump_recovery import ModelDuration, RecoveryContext


class RecoveryModel(Protocol):
    """A recovery's duration given the physics (``sim.heat_pump_recovery``)."""

    def duration(self, ctx: RecoveryContext) -> ModelDuration | None:
        """The served duration for ``ctx``, the start's hold included,
        with its confidence and reasons. ``ctx.physics`` is the
        integrator's duration, which the model may scale or replace.
        None declines: the physics is served alone."""
        ...
