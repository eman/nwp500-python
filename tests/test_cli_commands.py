"""Tests for CLI command handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from nwp500.cli.handlers import (
        get_controller_serial_number,
        handle_device_info_request,
        handle_set_dhw_temp_request,
        handle_set_mode_request,
        handle_status_request,
    )
except ImportError:
    pytest.skip("CLI dependencies not installed", allow_module_level=True)
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
    # Control attribute contains device control methods

    mqtt.request_device_info = AsyncMock()
    mqtt.request_device_status = AsyncMock()
    mqtt.set_dhw_mode = AsyncMock()
    mqtt.set_dhw_temperature = AsyncMock()

    # Async methods on mqtt itself
    mqtt.subscribe_device = AsyncMock()
    mqtt.subscribe_device_feature = AsyncMock()
    mqtt.subscribe_device_status = AsyncMock()
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
    # Check for human-readable format output
    assert "DEVICE STATUS" in captured.out
    assert "STATUS" in captured.out


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

    # 1 = Heat Pump
    mock_mqtt.set_dhw_mode.assert_called_once_with(mock_device, 1)


@pytest.mark.asyncio
async def test_handle_set_mode_request_invalid_mode(mock_mqtt, mock_device):
    """Test setting an invalid mode."""
    await handle_set_mode_request(mock_mqtt, mock_device, "invalid-mode")

    mock_mqtt.set_dhw_mode.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode_name", ["standby", "vacation"])
async def test_handle_set_mode_request_unsupported_modes(
    mock_mqtt, mock_device, mode_name
):
    """Standby/vacation are not settable via the mode command.

    Vacation requires a day count (dedicated ``vacation`` command) and
    standby (0) is not a writable DhwOperationSetting value.
    """
    await handle_set_mode_request(mock_mqtt, mock_device, mode_name)

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
async def test_handle_status_request_raw_with_st_key(
    mock_mqtt, mock_device, capsys
):
    """Raw status request handles the 'st' alt key from Navien devices."""
    status_data = {"operationMode": 1, "hotWaterTemperature": 500}

    async def subscribe_and_invoke(device, callback):
        callback("cmd/52/device/st", {"response": {"st": status_data}})

    mock_mqtt.subscribe_device = AsyncMock(side_effect=subscribe_and_invoke)

    await handle_status_request(mock_mqtt, mock_device, raw=True)

    captured = capsys.readouterr()
    assert "operationMode" in captured.out
    assert "hotWaterTemperature" in captured.out


@pytest.mark.asyncio
async def test_handle_device_info_request_raw_with_did_key(
    mock_mqtt, mock_device, capsys
):
    """Raw device info request handles the 'did' alt key from Navien devices."""
    feature_data = {"serialNumber": "ABC123", "modelName": "NWP500"}

    async def subscribe_and_invoke(device, callback):
        callback("cmd/52/device/st/did", {"response": {"did": feature_data}})

    mock_mqtt.subscribe_device = AsyncMock(side_effect=subscribe_and_invoke)

    await handle_device_info_request(mock_mqtt, mock_device, raw=True)

    captured = capsys.readouterr()
    assert "serialNumber" in captured.out
    assert "modelName" in captured.out


@pytest.mark.asyncio
async def test_handle_status_request_raw_with_standard_key(
    mock_mqtt, mock_device, capsys
):
    """Raw status request handles the standard 'status' key."""
    status_data = {"operationMode": 2, "hotWaterTemperature": 600}

    async def subscribe_and_invoke(device, callback):
        callback("cmd/52/device/st", {"response": {"status": status_data}})

    mock_mqtt.subscribe_device = AsyncMock(side_effect=subscribe_and_invoke)

    await handle_status_request(mock_mqtt, mock_device, raw=True)

    captured = capsys.readouterr()
    assert "operationMode" in captured.out
