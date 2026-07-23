"""Tests for the nwp500.tou_schedule public helpers."""

from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from nwp500.models import TOUPeriod, TOUReservationSchedule
from nwp500.tou_schedule import configure_tou_schedule_confirmed

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_device() -> MagicMock:
    device = MagicMock()
    device.device_info.device_type = "NWP500"
    return device


@pytest.fixture
def mock_mqtt(mock_device: MagicMock) -> MagicMock:
    mqtt = MagicMock()
    mqtt.client_id = "test-client"
    mqtt.subscribe_tou_response = AsyncMock()
    mqtt.unsubscribe_tou_response = AsyncMock()
    mqtt.configure_tou_schedule = AsyncMock()
    return mqtt


def _make_schedule(
    periods: list[dict[str, Any]], enabled: bool = True
) -> TOUReservationSchedule:
    return TOUReservationSchedule(
        reservationUse=2 if enabled else 0,
        reservation=[TOUPeriod(**p) for p in periods],
    )


def _period(
    season: int = 4095,
    week: int = 254,
    start_hour: int = 0,
    start_minute: int = 0,
    end_hour: int = 23,
    end_minute: int = 59,
    price_min: int = 10,
    price_max: int = 25,
    decimal_point: int = 2,
) -> dict[str, Any]:
    return {
        "season": season,
        "week": week,
        "startHour": start_hour,
        "startMinute": start_minute,
        "endHour": end_hour,
        "endMinute": end_minute,
        "priceMin": price_min,
        "priceMax": price_max,
        "decimalPoint": decimal_point,
    }


# ---------------------------------------------------------------------------
# configure_tou_schedule_confirmed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_tou_schedule_confirmed_success(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """Returns the device's echoed schedule after a successful write."""
    periods = [_period()]
    echoed = _make_schedule(periods)
    captured_callback: list[Any] = []

    async def fake_subscribe(device: Any, cb: Any) -> int:
        captured_callback.append(cb)
        return 1

    mock_mqtt.subscribe_tou_response.side_effect = fake_subscribe

    async def fake_configure(
        device: Any, controller_serial_number: Any, periods: Any, **kwargs: Any
    ) -> int:
        for cb in captured_callback:
            cb(echoed)
        return 1

    mock_mqtt.configure_tou_schedule.side_effect = fake_configure

    result = await configure_tou_schedule_confirmed(
        mock_mqtt, mock_device, "SERIAL123", periods
    )

    assert result is echoed
    mock_mqtt.configure_tou_schedule.assert_awaited_once_with(
        mock_device, "SERIAL123", periods, enabled=True
    )
    mock_mqtt.unsubscribe_tou_response.assert_called_once_with(mock_device, ANY)


@pytest.mark.asyncio
async def test_configure_tou_schedule_confirmed_timeout(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """Returns None on timeout, still writes and unsubscribes."""
    mock_mqtt.subscribe_tou_response = AsyncMock()
    mock_mqtt.configure_tou_schedule = AsyncMock()  # never fires callback

    result = await configure_tou_schedule_confirmed(
        mock_mqtt, mock_device, "SERIAL123", [_period()], timeout=0.01
    )

    assert result is None
    mock_mqtt.configure_tou_schedule.assert_awaited_once()
    mock_mqtt.unsubscribe_tou_response.assert_called_once_with(mock_device, ANY)


@pytest.mark.asyncio
async def test_configure_tou_schedule_confirmed_matches_desired(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """The echoed schedule's canonical() form matches what was written,
    even if the device returns periods in a different order."""
    periods = [
        _period(start_hour=0, end_hour=11),
        _period(start_hour=12, end_hour=23),
    ]
    desired = _make_schedule(periods)
    echoed = _make_schedule(list(reversed(periods)))
    captured_callback: list[Any] = []

    async def fake_subscribe(device: Any, cb: Any) -> int:
        captured_callback.append(cb)
        return 1

    mock_mqtt.subscribe_tou_response.side_effect = fake_subscribe

    async def fake_configure(
        device: Any, controller_serial_number: Any, periods: Any, **kwargs: Any
    ) -> int:
        for cb in captured_callback:
            cb(echoed)
        return 1

    mock_mqtt.configure_tou_schedule.side_effect = fake_configure

    result = await configure_tou_schedule_confirmed(
        mock_mqtt, mock_device, "SERIAL123", periods
    )

    assert result is not None
    assert result.canonical() == desired.canonical()
