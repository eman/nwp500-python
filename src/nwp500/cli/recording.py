"""Recording the heater's statuses for the simulator's calibration."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

from nwp500 import Device, DeviceStatus, NavienMqttClient
from nwp500.mqtt.utils import get_response_data
from nwp500.status_history import line as history_line

_logger = logging.getLogger(__name__)

#: How often a status is asked for, seconds.
DEFAULT_EVERY_S = 30.0


class Recorder:
    """An MQTT message handler that appends each status message to
    ``out`` as a history line (``status_history.line``), stamped with
    ``clock()``, the wall clock in UTC by default."""

    def __init__(
        self,
        out: TextIO,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.out = out
        self.clock = clock
        #: The statuses written so far.
        self.written = 0

    def __call__(self, topic: str, message: dict[str, Any]) -> None:
        data = get_response_data(message, "status")
        if not isinstance(data, dict):
            return
        raw = cast(dict[str, Any], data)
        try:
            DeviceStatus.model_validate(raw)
        except ValueError as e:
            _logger.warning(f"Skipping a status that does not parse: {e}")
            return
        # The device's address is the caller's own business, not the
        # history's.
        payload = {k: v for k, v in raw.items() if k != "macAddress"}
        self.out.write(history_line(self.clock(), payload) + "\n")
        self.out.flush()
        self.written += 1


async def handle_recording(
    mqtt: NavienMqttClient,
    device: Device,
    output: str,
    every_s: float = DEFAULT_EVERY_S,
) -> None:
    """Append the device's statuses to ``output`` until interrupted,
    asking for one every ``every_s`` seconds."""
    _logger.info(f"Recording statuses to {output} every {every_s:g} s")
    _logger.info("Press Ctrl+C to stop.")
    with Path(output).open("a", encoding="utf-8") as out:  # noqa: ASYNC230
        await mqtt.subscribe_device(device, Recorder(out))
        await mqtt.start_periodic_requests(device, period_seconds=every_s)
        await mqtt.request_device_status(device)
        await asyncio.Event().wait()
