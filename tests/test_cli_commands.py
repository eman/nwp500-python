"""Tests for CLI command handlers."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    # click ships in the optional "cli" extra, not "testing", so it has to be
    # imported inside the guard for this module to skip cleanly without it.
    from click.testing import CliRunner

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

        async def record_monthly(mqtt, device, years):
            calls.append({"years": years})

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
            patch(
                "nwp500.cli.handlers.handle_get_energy_monthly_request",
                side_effect=record_monthly,
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

    def test_years_are_deduplicated(self, energy_cli):
        result, calls = energy_cli(["energy", "--years", "2026,2025,2026"])

        assert result.exit_code == 0, result.output
        assert calls == [{"years": [2026, 2025]}]

    def test_years_asks_for_the_monthly_query(self, energy_cli):
        """--years is the device's monthly query, not the daily one."""
        result, calls = energy_cli(["energy", "--years", "2025, 2026"])

        assert result.exit_code == 0, result.output
        assert calls == [{"years": [2025, 2026]}]


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
                "Use only one of",
            ),
            (["--years", "2025", "--month", "5"], "Use only one of"),
            (["--years", "2025", "--year", "2025"], "do not pass --year"),
            (["--months", "1,2"], "--year is required"),
            (["--years", "abc"], "is not a year"),
            (["--years", ""], "is not a year"),
            (["--years", "0"], "not in the range"),
            (["--year", "1999", "--month", "1"], "not in the range"),
            (["--year", "2100", "--months", "1,2"], "not in the range"),
            (["--years", "2025,99999"], "not in the range"),
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


@pytest.fixture
def query_mqtt(mock_mqtt):
    """MQTT mock whose new query subscriptions answer immediately."""

    def answering(payload):
        async def subscribe_and_invoke(device, callback):
            callback(payload)

        return AsyncMock(side_effect=subscribe_and_invoke)

    from nwp500.models import (
        DeviceDiagnostics,
        FirmwareDownloadInfo,
        RecirculationSchedule,
    )

    mock_mqtt.subscribe_diagnostics = answering(
        DeviceDiagnostics.from_response(
            {
                "typeOfTD": 2,
                "data": {
                    "tsData": {"cumulatedPwrHp": 1266585},
                    "tdData": {},
                    "taData": {"cumulatedOpTimeComp": 3124},
                },
            }
        )
    )
    mock_mqtt.request_diagnostics = AsyncMock()
    mock_mqtt.subscribe_firmware_download_info = answering(
        FirmwareDownloadInfo.model_validate(
            {"downloadSwInfo": [{"swCode": 1, "swVersion": 7}]}
        )
    )
    mock_mqtt.request_firmware_download_info = AsyncMock()
    mock_mqtt.subscribe_recirculation_schedule_response = answering(
        RecirculationSchedule.model_validate(
            {
                "reservationUse": 2,
                "reservation": [
                    {"enable": 2, "week": 62, "hour": 6, "min": 0, "mode": 2}
                ],
            }
        )
    )
    mock_mqtt.request_recirculation_schedule = AsyncMock()
    mock_mqtt.configure_recirculation_schedule = AsyncMock()
    mock_mqtt.set_air_filter_life = AsyncMock()
    mock_mqtt.set_vacation_duration = AsyncMock()
    mock_mqtt.reset_condenser_fault = AsyncMock()
    return mock_mqtt


class TestNewQueryHandlers:
    @pytest.mark.asyncio
    async def test_diagnostics_table(self, query_mqtt, mock_device, capsys):
        from nwp500.cli.handlers import handle_diagnostics_request

        await handle_diagnostics_request(query_mqtt, mock_device)

        query_mqtt.request_diagnostics.assert_awaited_once_with(mock_device)
        out = capsys.readouterr().out
        assert "DEVICE DIAGNOSTICS" in out
        assert "1,266,585 Wh" in out
        assert "3124 h" in out

    @pytest.mark.asyncio
    async def test_diagnostics_json(self, query_mqtt, mock_device, capsys):
        from nwp500.cli.handlers import handle_diagnostics_request

        await handle_diagnostics_request(
            query_mqtt, mock_device, output_json=True
        )

        out = capsys.readouterr().out
        assert '"cumulated_pwr_hp": 1266585' in out

    @pytest.mark.asyncio
    async def test_firmware_info(self, query_mqtt, mock_device, capsys):
        from nwp500.cli.handlers import (
            handle_firmware_download_info_request,
        )

        await handle_firmware_download_info_request(query_mqtt, mock_device)

        query_mqtt.request_firmware_download_info.assert_awaited_once_with(
            mock_device
        )
        out = capsys.readouterr().out
        assert "FIRMWARE DOWNLOAD INFO" in out
        assert "Controller" in out

    @pytest.mark.asyncio
    async def test_recirculation_schedule_get(
        self, query_mqtt, mock_device, capsys
    ):
        from nwp500.cli.handlers import (
            handle_get_recirculation_schedule_request,
        )

        await handle_get_recirculation_schedule_request(query_mqtt, mock_device)

        query_mqtt.request_recirculation_schedule.assert_awaited_once_with(
            mock_device
        )
        out = capsys.readouterr().out
        assert "RECIRCULATION SCHEDULE" in out
        assert "06:00" in out

    @pytest.mark.asyncio
    async def test_recirculation_schedule_set(self, query_mqtt, mock_device):
        from nwp500.cli.handlers import (
            handle_set_recirculation_schedule_request,
        )

        await handle_set_recirculation_schedule_request(
            query_mqtt,
            mock_device,
            '[{"enable": 2, "week": 62, "hour": 6, "min": 0, "mode": 2}]',
            enabled=True,
        )

        query_mqtt.configure_recirculation_schedule.assert_awaited_once()
        _device, schedule = (
            query_mqtt.configure_recirculation_schedule.await_args.args
        )
        assert schedule.reservation_use == 2
        assert schedule.reservation[0].to_protocol_dict() == {
            "enable": 2,
            "week": 62,
            "hour": 6,
            "min": 0,
            "mode": 2,
            "param": -1,
        }

    @pytest.mark.asyncio
    async def test_recirculation_schedule_set_rejects_bad_json(
        self, query_mqtt, mock_device
    ):
        from nwp500.cli.handlers import (
            handle_set_recirculation_schedule_request,
        )

        await handle_set_recirculation_schedule_request(
            query_mqtt, mock_device, '{"not": "a list"}', enabled=True
        )

        query_mqtt.configure_recirculation_schedule.assert_not_awaited()


class TestNewControlHandlers:
    @pytest.fixture
    def status_mqtt(self, query_mqtt):
        status = MagicMock(spec=DeviceStatus)

        async def subscribe_and_invoke(device, callback):
            callback(status)

        query_mqtt.subscribe_device_status.side_effect = subscribe_and_invoke
        return query_mqtt

    @pytest.mark.asyncio
    async def test_air_filter_life(self, status_mqtt, mock_device):
        from nwp500.cli.handlers import handle_set_air_filter_life_request

        await handle_set_air_filter_life_request(status_mqtt, mock_device, 3000)

        status_mqtt.set_air_filter_life.assert_awaited_once_with(
            mock_device, 3000
        )

    @pytest.mark.asyncio
    async def test_vacation_duration(self, status_mqtt, mock_device):
        from nwp500.cli.handlers import (
            handle_set_vacation_duration_request,
        )

        await handle_set_vacation_duration_request(status_mqtt, mock_device, 7)

        status_mqtt.set_vacation_duration.assert_awaited_once_with(
            mock_device, 7
        )

    @pytest.mark.asyncio
    async def test_condenser_fault_reset(self, status_mqtt, mock_device):
        from nwp500.cli.handlers import handle_reset_condenser_fault_request

        await handle_reset_condenser_fault_request(status_mqtt, mock_device)

        status_mqtt.reset_condenser_fault.assert_awaited_once_with(mock_device)


class TestParseTimeValidation:
    """Commands reject bad input before authenticating or connecting.

    No stubbing: reaching the network would fail these tests.
    """

    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            (["filter-life", "1250"], "not accepted"),
            (["filter-life", "999"], "not accepted"),
            (["filter-life", "12000"], "not accepted"),
            (
                ["recirc-schedule", "set", '[{"startHour": 6}]'],
                "unknown keys",
            ),
            (
                [
                    "recirc-schedule",
                    "set",
                    '[{"week": 124, "hour": 99, "min": 0}]',
                ],
                "hour=99",
            ),
            (["recirc-schedule", "set", "not json"], "not valid JSON"),
            (
                [
                    "recirc-schedule",
                    "set",
                    '[{"week": 124, "hour": 6, "min": 0, "param": 255}]',
                ],
                "param must be -1",
            ),
            (
                ["recirc-schedule", "set", '[{"week": 124, "bogus": 1}]'],
                "expected enable, week, hour, min, mode, param",
            ),
            (["recirc-schedule", "set", '{"week": 124}'], "JSON array"),
            (
                ["recirc-schedule", "set", '[{"week": 124, "hour": 6}]'],
                "missing 'min'",
            ),
            (
                [
                    "recirc-schedule",
                    "set",
                    '[{"week": 124, "hour": "6", "min": 0}]',
                ],
                "must be an integer",
            ),
        ],
    )
    def test_rejected_during_parsing(self, args, expected):
        from nwp500.cli.__main__ import cli

        result = CliRunner().invoke(
            cli,
            args,
            env={
                "NAVIEN_EMAIL": "user@example.com",
                "NAVIEN_PASSWORD": "secret",
            },
        )

        assert result.exit_code == 2, result.output
        assert expected in result.output

    def test_too_many_recirculation_entries(self):
        import json as _json

        from nwp500.cli.handlers import parse_recirculation_schedule_json

        entries = [{"week": 124, "hour": 6, "min": 0}] * 21
        with pytest.raises(ValueError, match="at most 20"):
            parse_recirculation_schedule_json(_json.dumps(entries), True)


class TestNoAnswer:
    """Unanswered queries are reported instead of failing silently."""

    @pytest.mark.asyncio
    async def test_diagnostics_timeout_is_reported(
        self, mock_mqtt, mock_device, monkeypatch, capsys
    ):
        from nwp500.cli import handlers

        mock_mqtt.subscribe_diagnostics = AsyncMock()
        mock_mqtt.request_diagnostics = AsyncMock()

        async def no_answer(*args, **kwargs):
            raise TimeoutError

        monkeypatch.setattr(handlers, "_wait_for_response", no_answer)

        await handlers.handle_diagnostics_request(mock_mqtt, mock_device)

        assert (
            "did not answer the diagnostics request" in capsys.readouterr().out
        )

    @pytest.mark.asyncio
    async def test_recirculation_write_without_echo(
        self, mock_mqtt, mock_device, monkeypatch, capsys
    ):
        from nwp500.cli import handlers

        async def no_answer(*args, **kwargs):
            raise TimeoutError

        monkeypatch.setattr(handlers, "_wait_for_response", no_answer)

        await handlers.handle_set_recirculation_schedule_request(
            mock_mqtt,
            mock_device,
            '[{"week": 124, "hour": 6, "min": 0}]',
            enabled=True,
        )

        out = capsys.readouterr().out
        assert "sent, but the device did not echo it" in out
