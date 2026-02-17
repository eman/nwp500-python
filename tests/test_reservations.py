"""Tests for the nwp500.reservations public helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nwp500.models import ReservationEntry, ReservationSchedule
from nwp500.reservations import (
    add_reservation,
    delete_reservation,
    fetch_reservations,
    update_reservation,
)

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
    mqtt.subscribe = AsyncMock()
    mqtt.unsubscribe = AsyncMock()
    mqtt.control.request_reservations = AsyncMock()
    mqtt.control.update_reservations = AsyncMock()
    return mqtt


def _make_schedule(
    entries: list[dict[str, Any]], enabled: bool = True
) -> ReservationSchedule:
    """Build a ReservationSchedule from raw entry dicts."""
    return ReservationSchedule(
        reservationUse=2 if enabled else 1,
        reservation=[ReservationEntry(**e) for e in entries],
    )


def _entry(
    enable: int = 2,
    week: int = 124,
    hour: int = 6,
    min: int = 30,
    mode: int = 4,
    param: int = 120,
) -> dict[str, Any]:
    return {
        "enable": enable,
        "week": week,
        "hour": hour,
        "min": min,
        "mode": mode,
        "param": param,
    }


# ---------------------------------------------------------------------------
# fetch_reservations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_reservations_success(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """fetch_reservations returns a ReservationSchedule on success."""
    schedule = _make_schedule([_entry()])
    captured_callback: list[Any] = []

    async def fake_subscribe(topic: str, cb: Any) -> int:
        captured_callback.append(cb)
        return 1

    mock_mqtt.subscribe.side_effect = fake_subscribe

    async def fake_request(device: Any) -> None:
        # Simulate the device response arriving after subscribe
        topic = "cmd/NWP500/test-client/res/rsv/rd"
        msg = {
            "response": {
                "reservationUse": 2,
                "reservation": "023e061e0478",
            }
        }
        for cb in captured_callback:
            cb(topic, msg)

    mock_mqtt.control.request_reservations.side_effect = fake_request

    with patch(
        "nwp500.reservations.ReservationSchedule",
        return_value=schedule,
    ):
        result = await fetch_reservations(mock_mqtt, mock_device)

    assert result is schedule
    mock_mqtt.unsubscribe.assert_called_once_with(
        "cmd/NWP500/test-client/res/rsv/rd"
    )


@pytest.mark.asyncio
async def test_fetch_reservations_timeout(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """fetch_reservations returns None on timeout and still unsubscribes."""
    mock_mqtt.subscribe = AsyncMock()
    mock_mqtt.control.request_reservations = AsyncMock()  # never fires callback

    result = await fetch_reservations(mock_mqtt, mock_device, timeout=0.01)

    assert result is None
    mock_mqtt.unsubscribe.assert_called_once_with(
        "cmd/NWP500/test-client/res/rsv/rd"
    )


@pytest.mark.asyncio
async def test_fetch_reservations_ignores_wrong_topic(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """fetch_reservations ignores messages on non-reservation topics."""
    captured_callback: list[Any] = []

    async def fake_subscribe(topic: str, cb: Any) -> int:
        captured_callback.append(cb)
        return 1

    mock_mqtt.subscribe.side_effect = fake_subscribe

    async def fake_request(device: Any) -> None:
        # Wrong topic — should be ignored
        for cb in captured_callback:
            cb("cmd/NWP500/test-client/res/other/rd", {"response": {"foo": 1}})

    mock_mqtt.control.request_reservations.side_effect = fake_request

    result = await fetch_reservations(mock_mqtt, mock_device, timeout=0.01)
    assert result is None


# ---------------------------------------------------------------------------
# add_reservation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_reservation_success(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """add_reservation appends the new entry and sends the full list."""
    existing = _entry(hour=6, min=0)
    schedule = _make_schedule([existing])

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        await add_reservation(
            mock_mqtt,
            mock_device,
            enabled=True,
            days=["MO", "TU", "WE", "TH", "FR"],
            hour=8,
            minute=0,
            mode=3,
            temperature=120.0,
        )

    mock_mqtt.control.update_reservations.assert_called_once()
    _, reservations = mock_mqtt.control.update_reservations.call_args.args
    assert len(reservations) == 2


@pytest.mark.asyncio
async def test_add_reservation_invalid_hour(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    with pytest.raises(ValueError, match="Hour"):
        await add_reservation(
            mock_mqtt,
            mock_device,
            enabled=True,
            days=["MO"],
            hour=25,
            minute=0,
            mode=1,
            temperature=120.0,
        )


@pytest.mark.asyncio
async def test_add_reservation_invalid_minute(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    with pytest.raises(ValueError, match="Minute"):
        await add_reservation(
            mock_mqtt,
            mock_device,
            enabled=True,
            days=["MO"],
            hour=6,
            minute=60,
            mode=1,
            temperature=120.0,
        )


@pytest.mark.asyncio
async def test_add_reservation_invalid_mode(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    with pytest.raises(ValueError, match="Mode"):
        await add_reservation(
            mock_mqtt,
            mock_device,
            enabled=True,
            days=["MO"],
            hour=6,
            minute=0,
            mode=7,
            temperature=120.0,
        )


@pytest.mark.asyncio
async def test_add_reservation_timeout(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    with patch("nwp500.reservations.fetch_reservations", return_value=None):
        with pytest.raises(TimeoutError):
            await add_reservation(
                mock_mqtt,
                mock_device,
                enabled=True,
                days=["MO"],
                hour=6,
                minute=0,
                mode=1,
                temperature=120.0,
            )


# ---------------------------------------------------------------------------
# delete_reservation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_reservation_success(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """delete_reservation removes the entry at the given 1-based index."""
    e1 = _entry(hour=6)
    e2 = _entry(hour=8)
    schedule = _make_schedule([e1, e2])

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        await delete_reservation(mock_mqtt, mock_device, index=1)

    mock_mqtt.control.update_reservations.assert_called_once()
    _, reservations = mock_mqtt.control.update_reservations.call_args.args
    assert len(reservations) == 1
    assert reservations[0]["hour"] == 8


@pytest.mark.asyncio
async def test_delete_reservation_disables_when_empty(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """Deleting the last entry sets enabled=False."""
    schedule = _make_schedule([_entry()], enabled=True)

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        await delete_reservation(mock_mqtt, mock_device, index=1)

    enabled = mock_mqtt.control.update_reservations.call_args.kwargs["enabled"]
    assert enabled is False


@pytest.mark.asyncio
async def test_delete_reservation_invalid_index(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    schedule = _make_schedule([_entry()])

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        with pytest.raises(ValueError, match="Invalid reservation index"):
            await delete_reservation(mock_mqtt, mock_device, index=5)


@pytest.mark.asyncio
async def test_delete_reservation_timeout(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    with patch("nwp500.reservations.fetch_reservations", return_value=None):
        with pytest.raises(TimeoutError):
            await delete_reservation(mock_mqtt, mock_device, index=1)


# ---------------------------------------------------------------------------
# update_reservation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_reservation_temperature(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """update_reservation with only temperature changes param."""
    schedule = _make_schedule([_entry(param=120)])

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        await update_reservation(mock_mqtt, mock_device, 1, temperature=150.0)

    mock_mqtt.control.update_reservations.assert_called_once()
    _, reservations = mock_mqtt.control.update_reservations.call_args.args
    # param must differ from the original 120 (150°F = 65.6°C → param=131)
    assert reservations[0]["param"] != 120


@pytest.mark.asyncio
async def test_update_reservation_preserves_fields(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    """update_reservation without temperature preserves existing param."""
    schedule = _make_schedule([_entry(hour=6, param=120)])

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        await update_reservation(mock_mqtt, mock_device, 1, hour=8)

    _, reservations = mock_mqtt.control.update_reservations.call_args.args
    assert reservations[0]["hour"] == 8
    assert reservations[0]["param"] == 120


@pytest.mark.asyncio
async def test_update_reservation_invalid_index(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    schedule = _make_schedule([_entry()])

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        with pytest.raises(ValueError, match="Invalid reservation index"):
            await update_reservation(mock_mqtt, mock_device, 99)


@pytest.mark.asyncio
async def test_update_reservation_invalid_hour(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    schedule = _make_schedule([_entry()])

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        with pytest.raises(ValueError, match="Hour"):
            await update_reservation(mock_mqtt, mock_device, 1, hour=25)


@pytest.mark.asyncio
async def test_update_reservation_invalid_minute(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    schedule = _make_schedule([_entry()])

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        with pytest.raises(ValueError, match="Minute"):
            await update_reservation(mock_mqtt, mock_device, 1, minute=60)


@pytest.mark.asyncio
async def test_update_reservation_invalid_mode(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    schedule = _make_schedule([_entry()])

    with patch("nwp500.reservations.fetch_reservations", return_value=schedule):
        with pytest.raises(ValueError, match="Mode"):
            await update_reservation(mock_mqtt, mock_device, 1, mode=0)


@pytest.mark.asyncio
async def test_update_reservation_timeout(
    mock_mqtt: MagicMock, mock_device: MagicMock
) -> None:
    with patch("nwp500.reservations.fetch_reservations", return_value=None):
        with pytest.raises(TimeoutError):
            await update_reservation(mock_mqtt, mock_device, 1, hour=8)
