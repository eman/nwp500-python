"""Tests for CLI command handlers."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

try:
    from nwp500.cli.handlers import (
        get_controller_serial_number,
        handle_device_info_request,
        handle_get_energy_request,
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


@pytest.fixture
def energy_views(monkeypatch):
    """Record which energy view a handler call renders."""
    rendered = []
    monkeypatch.setattr(
        "nwp500.cli.handlers.print_energy_usage",
        lambda response: rendered.append("monthly"),
    )
    monkeypatch.setattr(
        "nwp500.cli.output_formatters.print_daily_energy_usage",
        lambda response, year, month: rendered.append(f"daily:{month}"),
    )
    return rendered


@pytest.fixture
def energy_mqtt(mock_mqtt):
    """MQTT mock that answers an energy usage request immediately."""

    async def subscribe_and_invoke(device, callback):
        callback(MagicMock())

    mock_mqtt.subscribe_energy_usage = AsyncMock(
        side_effect=subscribe_and_invoke
    )
    mock_mqtt.request_energy_usage = AsyncMock()
    return mock_mqtt


@pytest.mark.asyncio
async def test_handle_get_energy_request_daily(
    energy_mqtt, mock_device, energy_views
):
    """--month asks for the daily breakdown."""
    await handle_get_energy_request(
        energy_mqtt, mock_device, 2025, [5], daily=True
    )

    assert energy_views == ["daily:5"]


@pytest.mark.asyncio
async def test_handle_get_energy_request_single_month_summary(
    energy_mqtt, mock_device, energy_views
):
    """A one-month --months list still gets the monthly summary."""
    await handle_get_energy_request(
        energy_mqtt, mock_device, 2025, [5], daily=False
    )

    assert energy_views == ["monthly"]


@pytest.mark.asyncio
async def test_handle_get_energy_request_multi_month_summary(
    energy_mqtt, mock_device, energy_views
):
    """Multiple months get the monthly summary."""
    await handle_get_energy_request(
        energy_mqtt, mock_device, 2025, [1, 2, 3], daily=False
    )

    assert energy_views == ["monthly"]


@pytest.fixture(autouse=True)
def _restore_logging():
    """Undo the logging setup the CLI group performs on every invocation.

    ``cli()`` calls ``logging.basicConfig`` and pins the ``nwp500`` logger
    to the verbosity flags, which would otherwise leak into later tests -
    ``tests/test_utils.py`` asserts on DEBUG records and sees none once
    this module has run.
    """
    nwp500_logger = logging.getLogger("nwp500")
    levels = (logging.root.level, nwp500_logger.level)
    handlers = list(logging.root.handlers)
    yield
    logging.root.setLevel(levels[0])
    nwp500_logger.setLevel(levels[1])
    logging.root.handlers[:] = handlers


@pytest.fixture
def energy_cli():
    """Invoke the real ``energy`` command with the network stubbed out.

    Returns a callable taking CLI args and giving back
    ``(result, calls)``, where ``calls`` records what the command asked
    :func:`handle_get_energy_request` for. This exercises the actual Click
    options, so a wrong ``--month``/``--months`` mapping fails here even
    though the handler-level tests above would still pass.
    """
    from nwp500.cli.__main__ import cli

    def invoke(args):
        calls = []

        async def record(mqtt, device, year, months, daily=False):
            calls.append({"year": year, "months": months, "daily": daily})

        auth = MagicMock()
        auth.__aenter__ = AsyncMock(return_value=auth)
        auth.__aexit__ = AsyncMock(return_value=False)
        auth.current_tokens = None
        auth.user_email = "user@example.com"
        api = MagicMock()
        api.get_first_device = AsyncMock(return_value=MagicMock())
        mqtt = MagicMock()
        mqtt.connect = AsyncMock()
        mqtt.disconnect = AsyncMock()

        with (
            patch("nwp500.cli.__main__.NavienAuthClient", return_value=auth),
            patch("nwp500.cli.__main__.NavienAPIClient", return_value=api),
            patch("nwp500.cli.__main__.NavienMqttClient", return_value=mqtt),
            patch(
                "nwp500.cli.__main__.load_tokens",
                return_value=(None, "user@example.com"),
            ),
            patch(
                "nwp500.cli.__main__._detect_unit_system",
                AsyncMock(return_value="us_customary"),
            ),
            patch(
                "nwp500.cli.handlers.handle_get_energy_request",
                side_effect=record,
            ),
        ):
            result = CliRunner().invoke(
                cli,
                args,
                env={
                    "NAVIEN_EMAIL": "user@example.com",
                    "NAVIEN_PASSWORD": "secret",
                },
            )
        return result, calls

    return invoke


class TestEnergyCommandDispatch:
    """The option that was passed picks the view, not the month count."""

    def test_month_asks_for_the_daily_breakdown(self, energy_cli):
        result, calls = energy_cli(["energy", "--year", "2025", "--month", "5"])

        assert result.exit_code == 0
        assert calls == [{"year": 2025, "months": [5], "daily": True}]

    def test_single_month_list_asks_for_the_summary(self, energy_cli):
        """The regression: ``--months 5`` must not become a daily view."""
        result, calls = energy_cli(
            ["energy", "--year", "2025", "--months", "5"]
        )

        assert result.exit_code == 0
        assert calls == [{"year": 2025, "months": [5], "daily": False}]

    def test_month_list_asks_for_the_summary(self, energy_cli):
        result, calls = energy_cli(
            ["energy", "--year", "2025", "--months", "1,2,3"]
        )

        assert result.exit_code == 0
        assert calls == [{"year": 2025, "months": [1, 2, 3], "daily": False}]

    def test_months_tolerates_spaces(self, energy_cli):
        result, calls = energy_cli(
            ["energy", "--year", "2025", "--months", "1, 2, 3"]
        )

        assert result.exit_code == 0
        assert calls == [{"year": 2025, "months": [1, 2, 3], "daily": False}]


class TestEnergyCommandUsageErrors:
    """Bad input is rejected while parsing, before any network work.

    These invoke the CLI with no stubbing at all: if any of them reached
    authentication, the test would hit the network instead of exiting 2.
    """

    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            (["--year", "2025", "--month", "13"], "13 is not in the range"),
            (["--year", "2025", "--month", "0"], "0 is not in the range"),
            (["--year", "2025", "--months", "abc"], "is not a month number"),
            (["--year", "2025", "--months", "1,13"], "13 is not in the range"),
            (["--year", "2025", "--months", ""], "is not a month number"),
            (["--year", "2025"], "is required"),
            (
                ["--year", "2025", "--month", "5", "--months", "1,2"],
                "not both",
            ),
        ],
    )
    def test_rejected_during_parsing(self, args, expected):
        from nwp500.cli.__main__ import cli

        result = CliRunner().invoke(
            cli,
            ["energy", *args],
            env={
                "NAVIEN_EMAIL": "user@example.com",
                "NAVIEN_PASSWORD": "secret",
            },
        )

        assert result.exit_code == 2, result.output
        assert expected in result.output
