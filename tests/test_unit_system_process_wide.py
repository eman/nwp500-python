"""Tests locking in the process-wide unit-system semantics (issue #103).

The unit-system preference in :mod:`nwp500.unit_system` is a deliberate
process-wide module-level global rather than a :class:`contextvars.ContextVar`.
These tests document and lock in that behaviour:

* Setting the global preference affects unit-aware computed fields on
  already-constructed model instances at access time.
* The preference is visible across async tasks and threads, i.e. a value set
  in one task/thread is observed by a model read in another — demonstrating it
  is process-wide, not context-local.
"""

import asyncio
import threading
from typing import Any

import pytest

from nwp500.models import ReservationEntry
from nwp500.unit_system import (
    get_unit_system,
    reset_unit_system,
    set_unit_system,
)


@pytest.fixture(autouse=True)
def _reset_unit_system() -> Any:
    """Ensure global unit-system state does not leak between tests."""
    reset_unit_system()
    try:
        yield
    finally:
        reset_unit_system()


def test_set_unit_system_affects_existing_instance_at_access_time(
    device_status_dict: dict[str, Any],
):
    """Changing the global preference affects a pre-built instance's fields."""
    from nwp500.models import DeviceStatus

    data = device_status_dict.copy()
    data["dhwTemperature"] = 120  # 60.0°C -> 140.0°F

    status = DeviceStatus.model_validate(data)

    set_unit_system("metric")
    assert status.dhw_temperature == 60.0

    set_unit_system("us_customary")
    assert status.dhw_temperature == 140.0

    reset_unit_system()
    # Falls back to the device's native temperature_type (Fahrenheit here).
    assert status.dhw_temperature == 140.0


def test_reservation_entry_unit_follows_global_preference():
    """ReservationEntry temperature/unit reflect the global preference."""
    entry = ReservationEntry(param=120)  # 60.0°C

    set_unit_system("metric")
    assert entry.temperature == 60.0
    assert entry.unit == "°C"

    set_unit_system("us_customary")
    assert entry.temperature == 140.0
    assert entry.unit == "°F"


def test_preference_set_in_one_task_seen_in_another_task():
    """A preference set in one asyncio task is visible in another task.

    A ``contextvars.ContextVar`` would isolate the value per task; the
    process-wide global is shared, so the reader task observes the writer's
    setting.
    """

    async def scenario() -> tuple[float, str]:
        entry = ReservationEntry(param=120)  # 60.0°C
        writer_done = asyncio.Event()

        async def writer() -> None:
            set_unit_system("metric")
            writer_done.set()

        async def reader() -> tuple[float, str]:
            await writer_done.wait()
            return entry.temperature, entry.unit

        writer_task = asyncio.create_task(writer())
        reader_task = asyncio.create_task(reader())
        await writer_task
        return await reader_task

    temperature, unit = asyncio.run(scenario())
    assert temperature == 60.0
    assert unit == "°C"


def test_preference_set_in_one_thread_seen_in_another_thread():
    """A preference set in one thread is visible from another thread.

    Model validation triggered by MQTT callbacks runs in AWS CRT callback
    threads. This confirms the preference is shared across threads rather than
    being isolated per-thread/context.
    """
    entry = ReservationEntry(param=120)  # 60.0°C
    set_ready = threading.Event()
    results: dict[str, Any] = {}

    def writer() -> None:
        set_unit_system("metric")
        set_ready.set()

    def reader() -> None:
        set_ready.wait(timeout=5)
        results["seen_preference"] = get_unit_system()
        results["temperature"] = entry.temperature
        results["unit"] = entry.unit

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    reader_thread.start()
    writer_thread.start()
    writer_thread.join()
    reader_thread.join()

    assert results["seen_preference"] == "metric"
    assert results["temperature"] == 60.0
    assert results["unit"] == "°C"
