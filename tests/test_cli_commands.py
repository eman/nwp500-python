"""Tests for CLI command handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nwp500.cli.commands import (
    get_controller_serial_number,
    handle_set_dhw_temp_request,
    handle_set_mode_request,
    handle_status_request,
)
from nwp500.models import Device, DeviceFeature, DeviceStatus


@pytest.fixture
def mock_device():
    device = MagicMock(spec=Device)
    device.device_info = MagicMock()
    device.device_info.device_type = 123
    return device


@pytest.fixture
def mock_mqtt():
    mqtt = MagicMock()
    # Async methods need to be AsyncMock
    mqtt.subscribe_device_feature = AsyncMock()
    mqtt.request_device_info = AsyncMock()
    mqtt.subscribe_device_status = AsyncMock()
    mqtt.request_device_status = AsyncMock()
    mqtt.set_dhw_mode = AsyncMock()
    mqtt.set_dhw_temperature = AsyncMock()
    return mqtt


@pytest.mark.asyncio
async def test_get_controller_serial_number_success(mock_mqtt, mock_device):
    """Test successful retrieval of controller serial number."""
    # Setup the feature that will be returned
    feature = MagicMock(spec=DeviceFeature)
    feature.controller_serial_number = "TEST_SERIAL_123"

    # When subscribe is called, capture the callback and call it immediately
    async def side_effect_subscribe(device, callback):
        callback(feature)
        return None

    mock_mqtt.subscribe_device_feature.side_effect = side_effect_subscribe

    serial = await get_controller_serial_number(
        mock_mqtt, mock_device, timeout=1.0
    )

    assert serial == "TEST_SERIAL_123"
    mock_mqtt.request_device_info.assert_called_once_with(mock_device)


@pytest.mark.asyncio
async def test_get_controller_serial_number_timeout(mock_mqtt, mock_device):
    """Test timeout when retrieving controller serial number."""
    # Do nothing when subscribe is called, so future never completes
    mock_mqtt.subscribe_device_feature.return_value = None

    # Reduce timeout for test speed
    serial = await get_controller_serial_number(
        mock_mqtt, mock_device, timeout=0.1
    )

    assert serial is None
    mock_mqtt.request_device_info.assert_called_once_with(mock_device)


@pytest.mark.asyncio
async def test_handle_status_request(mock_mqtt, mock_device, capsys):
    """Test status request handler prints output."""
    status = MagicMock(spec=DeviceStatus)
    status.model_dump.return_value = {"some": "data"}

    async def side_effect_subscribe(device, callback):
        callback(status)
        return None

    mock_mqtt.subscribe_device_status.side_effect = side_effect_subscribe

    await handle_status_request(mock_mqtt, mock_device)

    mock_mqtt.request_device_status.assert_called_once_with(mock_device)
    captured = capsys.readouterr()
    assert "some" in captured.out
    assert "data" in captured.out


@pytest.mark.asyncio
async def test_handle_set_mode_request_success(mock_mqtt, mock_device):
    """Test successful mode setting."""
    status = MagicMock(spec=DeviceStatus)
    # Configure nested mock explicitly to avoid spec issues with Pydantic
    operation_mode = MagicMock()
    operation_mode.name = "HEAT_PUMP"
    status.operation_mode = operation_mode
    status.model_dump.return_value = {"mode": "HEAT_PUMP"}

    async def side_effect_subscribe(device, callback):
        # Invoke callback immediately; handler waits on completed future
        callback(status)
        return None

    mock_mqtt.subscribe_device_status.side_effect = side_effect_subscribe

    await handle_set_mode_request(mock_mqtt, mock_device, "heat-pump")

    mock_mqtt.set_dhw_mode.assert_called_once_with(
        mock_device, 1
    )  # 1 = Heat Pump


@pytest.mark.asyncio
async def test_handle_set_mode_request_invalid_mode(mock_mqtt, mock_device):
    """Test setting an invalid mode."""
    await handle_set_mode_request(mock_mqtt, mock_device, "invalid-mode")

    mock_mqtt.set_dhw_mode.assert_not_called()


@pytest.mark.asyncio
async def test_handle_set_dhw_temp_request_success(mock_mqtt, mock_device):
    """Test successful temperature setting."""
    status = MagicMock(spec=DeviceStatus)
    status.dhw_target_temperature_setting = 120
    status.model_dump.return_value = {"temp": 120}

    async def side_effect_subscribe(device, callback):
        callback(status)
        return None

    mock_mqtt.subscribe_device_status.side_effect = side_effect_subscribe

    await handle_set_dhw_temp_request(mock_mqtt, mock_device, 120.0)

    mock_mqtt.set_dhw_temperature.assert_called_once_with(mock_device, 120.0)


@pytest.mark.asyncio
async def test_handle_set_dhw_temp_request_out_of_range(mock_mqtt, mock_device):
    """Test setting temperature out of range."""
    await handle_set_dhw_temp_request(mock_mqtt, mock_device, 160.0)  # > 150
    mock_mqtt.set_dhw_temperature.assert_not_called()

    await handle_set_dhw_temp_request(mock_mqtt, mock_device, 90.0)  # < 95
    mock_mqtt.set_dhw_temperature.assert_not_called()
