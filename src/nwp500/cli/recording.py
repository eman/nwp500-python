"""Recording the heater's statuses for the simulator's calibration."""

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

import click

from nwp500 import Device, DeviceStatus, NavienMqttClient
from nwp500.mqtt.utils import get_response_data
from nwp500.status_history import line as history_line

_logger = logging.getLogger(__name__)


class RecordingError(click.ClickException):
    """The history could not be written."""


#: How often a status is asked for, seconds.
DEFAULT_EVERY_S = 30.0


class Recorder:
    """An MQTT message handler that appends each status message to
    ``out`` as a history line (``status_history.line``), stamped with
    ``clock()``, the wall clock in UTC by default.

    The client logs and drops what a handler raises, so a failed write
    goes to ``on_error`` instead, and the recorder writes nothing more.
    """

    def __init__(
        self,
        out: TextIO,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        on_error: Callable[[OSError], None] = lambda e: None,
    ) -> None:
        self.out = out
        self.clock = clock
        self.on_error = on_error
        #: The statuses written so far.
        self.written = 0
        #: The write that failed, once one has.
        self.failed: OSError | None = None

    def __call__(self, topic: str, message: dict[str, Any]) -> None:
        if self.failed is not None:
            return
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
        try:
            self.out.write(history_line(self.clock(), payload) + "\n")
            self.out.flush()
        except OSError as e:
            self.failed = e
            self.on_error(e)
            return
        self.written += 1


def _ends_a_line(path: Path) -> bool:
    """Whether ``path`` is empty or missing, or ends with a newline: an
    append then starts a line of its own."""
    try:
        with path.open("rb") as f:
            if f.seek(0, os.SEEK_END) == 0:
                return True
            f.seek(-1, os.SEEK_END)
            return f.read(1) == b"\n"
    except FileNotFoundError:
        return True


async def handle_recording(
    mqtt: NavienMqttClient,
    device: Device,
    output: str,
    every_s: float = DEFAULT_EVERY_S,
) -> None:
    """Append the device's statuses to ``output`` until interrupted,
    asking for one every ``every_s`` seconds. A write that fails stops
    the recording with ``RecordingError``."""
    _logger.info(f"Recording statuses to {output} every {every_s:g} s")
    _logger.info("Press Ctrl+C to stop.")
    path = Path(output)
    loop = asyncio.get_running_loop()
    failed: asyncio.Future[OSError] = loop.create_future()

    def on_error(e: OSError) -> None:
        def settle() -> None:
            if not failed.done():
                failed.set_result(e)

        loop.call_soon_threadsafe(settle)

    try:
        new_line = not await asyncio.to_thread(_ends_a_line, path)
        with path.open("a", encoding="utf-8") as out:  # noqa: ASYNC230
            if new_line:
                # Whatever wrote the file left its last line open.
                out.write("\n")
            record = Recorder(out, on_error=on_error)
            await mqtt.subscribe_device(device, record)
            await mqtt.start_periodic_requests(device, period_seconds=every_s)
            await mqtt.request_device_status(device)
            error = await failed
    except OSError as e:
        error = e
    raise RecordingError(
        f"cannot write to {output}: {error}; recording stopped"
    )
