"""Regression tests for protocol correctness fixes.

Covers:
- Recirculation schedule payload shape and topic (the app's
  reservationUse/reservation envelope on ctrl/recirc-rsv/rd)
- Query payloads and response topics for every st/ query
- Control payloads for goout-day, air-filter-life and cond-fault-reset
- Command queue ordering on failed flush and stale-command expiry
- Negative-temperature ASYMMETRIC Fahrenheit conversion
- Freeze protection default raw values
- error_detected emitted when the error code changes between two errors
- TOU price encoding (half-up rounding, bool rejection)
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nwp500.encoding import build_tou_period, encode_price
from nwp500.enums import CommandCode
from nwp500.events import EventEmitter
from nwp500.exceptions import ParameterValidationError, RangeValidationError
from nwp500.models.schedule import (
    RecirculationSchedule,
    RecirculationScheduleEntry,
    ReservationEntry,
)
from nwp500.models.status import DeviceStatus
from nwp500.mqtt.command_queue import MqttCommandQueue
from nwp500.mqtt.control import MqttDeviceController
from nwp500.mqtt.state_tracker import DeviceStateTracker
from nwp500.mqtt.types import QoS
from nwp500.mqtt.utils import MqttConnectionConfig
from nwp500.temperature import RawCelsius, TempFormulaType
from nwp500.unit_system import reset_unit_system


@pytest.fixture(autouse=True)
def _reset_units():
    yield
    reset_unit_system()


def _status(device_status_dict: dict, **overrides) -> DeviceStatus:
    data = {**device_status_dict, **overrides}
    return DeviceStatus.model_validate(data)


@pytest.fixture
def mock_device():
    device = MagicMock()
    device.device_info.mac_address = "aa:bb:cc:dd:ee:ff"
    device.device_info.device_type = 52
    device.device_info.additional_value = "additional"
    return device


def _make_controller():
    publish = AsyncMock(return_value=1)
    controller = MqttDeviceController(
        client_id="test-client",
        session_id="test-session",
        publish_func=publish,
    )
    # Bypass capability lookup (would require a live device)
    controller._get_device_features = AsyncMock(return_value=MagicMock())
    return controller, publish


class TestSchedulePayloads:
    """Schedule commands must send flat, raw protocol payloads."""

    @pytest.mark.asyncio
    async def test_recirculation_schedule_payload_shape(self, mock_device):
        """The app publishes RECIR_RESERVATION on ctrl/recirc-rsv/rd with
        the same reservationUse/reservation envelope as the weekly
        schedule. The library used to publish {"schedule": [...]} on the
        bare ctrl topic, which the device never answered."""
        controller, publish = _make_controller()

        schedule = RecirculationSchedule(
            reservationUse=2,
            reservation=[
                RecirculationScheduleEntry(
                    enable=2, week=84, hour=6, min=0, mode=2
                )
            ],
        )

        await controller.configure_recirculation_schedule(mock_device, schedule)

        publish.assert_awaited_once()
        topic, command = publish.await_args.args

        assert topic == "cmd/52/navilink-aa:bb:cc:dd:ee:ff/ctrl/recirc-rsv/rd"
        assert (
            command["responseTopic"] == "cmd/52/test-client/res/recirc-rsv/rd"
        )
        request = command["request"]
        assert request["command"] == CommandCode.RECIR_RESERVATION
        assert request["reservationUse"] == 2
        assert "schedule" not in request
        assert request["reservation"] == [
            {
                "enable": 2,
                "week": 84,
                "hour": 6,
                "min": 0,
                "mode": 2,
                "param": -1,
            }
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("hour", 99),
            ("min", -5),
            ("min", 60),
            ("week", 1000),
            ("week", 0),
            ("week", 63),
            ("enable", 7),
            ("mode", 9),
            ("param", 0),
        ],
    )
    async def test_recirculation_schedule_rejects_out_of_range_entries(
        self, mock_device, field, value
    ):
        controller, publish = _make_controller()
        entry = {"enable": 2, "week": 124, "hour": 6, "min": 0, "mode": 2}
        entry[field] = value
        schedule = RecirculationSchedule.model_validate(
            {"reservationUse": 2, "reservation": [entry]}
        )

        with pytest.raises(ParameterValidationError):
            await controller.configure_recirculation_schedule(
                mock_device, schedule
            )
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recirculation_schedule_caps_entries(self, mock_device):
        controller, publish = _make_controller()
        entry = {"enable": 2, "week": 124, "hour": 6, "min": 0, "mode": 2}
        schedule = RecirculationSchedule.model_validate(
            {"reservationUse": 2, "reservation": [entry] * 21}
        )

        with pytest.raises(ParameterValidationError):
            await controller.configure_recirculation_schedule(
                mock_device, schedule
            )
        publish.assert_not_awaited()

    def test_to_protocol_dict_excludes_computed_fields(self):
        entry = ReservationEntry(
            enable=2, week=84, hour=6, min=30, mode=3, param=120
        )
        protocol = entry.to_protocol_dict()
        assert set(protocol) == {
            "enable",
            "week",
            "hour",
            "min",
            "mode",
            "param",
        }
        # The display dump still has the computed fields
        display = entry.model_dump()
        assert "temperature" in display
        assert "days" in display

    def test_recirculation_entry_to_protocol_dict_is_raw(self):
        entry = RecirculationScheduleEntry(enable=2, week=84, hour=6, min=0)
        assert entry.to_protocol_dict() == {
            "enable": 2,
            "week": 84,
            "hour": 6,
            "min": 0,
            "mode": 2,
            "param": -1,
        }
        assert "pump_on" in entry.model_dump()


class TestQueryPayloads:
    """Every st/ query publishes the app's topic, code and reply topic."""

    @pytest.mark.asyncio
    async def test_diagnostics_uses_app_form_response_topic(self, mock_device):
        """The cloud only decodes the td/rd hex into JSON when the reply
        topic has the app's five-segment form; the sequence numbers are
        not checked, so home_seq from the device info and 0 are used."""
        mock_device.device_info.home_seq = 25004
        controller, publish = _make_controller()

        await controller.request_diagnostics(mock_device)

        topic, command = publish.await_args.args
        assert topic == "cmd/52/navilink-aa:bb:cc:dd:ee:ff/st/td/rd"
        assert command["request"]["command"] == 16777228
        assert (
            command["responseTopic"] == "cmd/52/25004/0/test-client/res/td/rd"
        )

    @pytest.mark.asyncio
    async def test_firmware_download_info_uses_device_topic(self, mock_device):
        """The device answers dl-sw-info on its own topic, not a client one."""
        controller, publish = _make_controller()

        await controller.request_firmware_download_info(mock_device)

        topic, command = publish.await_args.args
        assert topic == "cmd/52/navilink-aa:bb:cc:dd:ee:ff/st/dl-sw-info"
        assert command["request"]["command"] == 16777227
        assert (
            command["responseTopic"]
            == "cmd/52/navilink-aa:bb:cc:dd:ee:ff/res/dl-sw-info"
        )

    @pytest.mark.asyncio
    async def test_monthly_energy_query(self, mock_device):
        controller, publish = _make_controller()

        await controller.request_energy_usage_monthly(mock_device, [2025, 2026])

        topic, command = publish.await_args.args
        assert topic.endswith("/st/energy-usage-monthly-query/rd")
        assert command["responseTopic"] == (
            "cmd/52/test-client/res/energy-usage-monthly-query/rd"
        )
        request = command["request"]
        assert request["command"] == 16777226
        assert request["year"] == [2025, 2026]
        assert "month" not in request

    @pytest.mark.asyncio
    async def test_monthly_energy_query_dedupes_years(self, mock_device):
        controller, publish = _make_controller()

        await controller.request_energy_usage_monthly(
            mock_device, [2026, 2025, 2026]
        )

        _topic, command = publish.await_args.args
        assert command["request"]["year"] == [2026, 2025]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("years", [[0], [-1], [99999], [1999]])
    async def test_monthly_energy_query_rejects_out_of_range_years(
        self, mock_device, years
    ):
        controller, publish = _make_controller()
        with pytest.raises(RangeValidationError):
            await controller.request_energy_usage_monthly(mock_device, years)
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_monthly_energy_query_rejects_empty_years(self, mock_device):
        controller, publish = _make_controller()
        with pytest.raises(ParameterValidationError):
            await controller.request_energy_usage_monthly(mock_device, [])
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hourly_energy_query(self, mock_device):
        controller, publish = _make_controller()

        await controller.request_energy_usage_hourly(mock_device, 2026, 9, [3])

        topic, command = publish.await_args.args
        assert topic.endswith("/st/energy-usage-hourly-query/rd")
        request = command["request"]
        assert request["command"] == 16777224
        assert request["year"] == 2026
        assert request["month"] == 9
        assert request["day"] == [3]

    @pytest.mark.asyncio
    async def test_hourly_energy_query_validates(self, mock_device):
        controller, publish = _make_controller()
        with pytest.raises(RangeValidationError):
            await controller.request_energy_usage_hourly(
                mock_device, 2026, 13, [1]
            )
        with pytest.raises(ParameterValidationError):
            await controller.request_energy_usage_hourly(
                mock_device, 2026, 9, []
            )
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recirculation_schedule_read(self, mock_device):
        controller, publish = _make_controller()

        await controller.request_recirculation_schedule(mock_device)

        topic, command = publish.await_args.args
        assert topic.endswith("/st/recirc-rsv/rd")
        assert command["request"]["command"] == 16777231
        assert (
            command["responseTopic"] == "cmd/52/test-client/res/recirc-rsv/rd"
        )

    @pytest.mark.asyncio
    async def test_end_session(self, mock_device):
        controller, publish = _make_controller()

        await controller.end_session(mock_device)

        topic, command = publish.await_args.args
        assert topic == "cmd/52/navilink-aa:bb:cc:dd:ee:ff/st/end"
        assert command["request"]["command"] == 16777218
        assert command["responseTopic"] == "cmd/52/test-client/res/end"


class TestControlPayloads:
    """Mode/param payloads match the app's request builder."""

    @pytest.mark.asyncio
    async def test_ota_commit_uses_commit_ota_topics(self, mock_device):
        """The app publishes OTA_COMMIT on ctrl/commit-ota and asks for the
        reply on res/commit-ota in its five-segment topic form."""
        from nwp500.models import OtaCommitPayload

        mock_device.device_info.home_seq = 25004
        controller, publish = _make_controller()

        await controller.commit_firmware_update(
            mock_device, OtaCommitPayload(swCode=1, swVersion=7)
        )

        topic, command = publish.await_args.args
        assert topic == "cmd/52/navilink-aa:bb:cc:dd:ee:ff/ctrl/commit-ota"
        assert command["responseTopic"] == (
            "cmd/52/25004/0/test-client/res/commit-ota"
        )
        assert command["request"]["commitOta"] == {"swCode": 1, "swVersion": 7}

    @pytest.mark.asyncio
    async def test_air_filter_life_rejects_non_integers(self, mock_device):
        controller, publish = _make_controller()
        with pytest.raises(ParameterValidationError):
            await controller.set_air_filter_life(mock_device, 3000.0)
        with pytest.raises(ParameterValidationError):
            await controller.set_air_filter_life(mock_device, True)
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_vacation_duration_sends_goout_day(self, mock_device):
        controller, publish = _make_controller()

        await controller.set_vacation_duration(mock_device, 7)

        _topic, command = publish.await_args.args
        request = command["request"]
        assert request["command"] == CommandCode.GOOUT_DAY
        assert request["mode"] == "goout-day"
        assert request["param"] == [7]
        assert request["paramStr"] == ""

    @pytest.mark.asyncio
    async def test_vacation_duration_range(self, mock_device):
        controller, publish = _make_controller()
        with pytest.raises(RangeValidationError):
            await controller.set_vacation_duration(mock_device, 31)
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("hours", "param"), [(0, 0), (1000, 2), (3000, 6), (10000, 20)]
    )
    async def test_air_filter_life_sends_hours_over_500(
        self, mock_device, hours, param
    ):
        """The app's picker offers 0 or 1000-10000 h in 500 h steps and
        sends hours / 500 on the wire."""
        controller, publish = _make_controller()

        await controller.set_air_filter_life(mock_device, hours)

        _topic, command = publish.await_args.args
        request = command["request"]
        assert request["command"] == CommandCode.AIR_FILTER_LIFE
        assert request["mode"] == "air-filter-life"
        assert request["param"] == [param]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("hours", [500, 1250, 12000, -500])
    async def test_air_filter_life_rejects_values_off_the_picker(
        self, mock_device, hours
    ):
        controller, publish = _make_controller()
        with pytest.raises(ParameterValidationError):
            await controller.set_air_filter_life(mock_device, hours)
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_condenser_fault_reset(self, mock_device):
        controller, publish = _make_controller()

        await controller.reset_condenser_fault(mock_device)

        _topic, command = publish.await_args.args
        request = command["request"]
        assert request["command"] == 33554463
        assert request["mode"] == "cond-fault-reset"
        assert request["param"] == []


def _queue(max_age: float | None = 300.0) -> MqttCommandQueue:
    config = MqttConnectionConfig(
        client_id="test-client", max_queued_command_age=max_age
    )
    return MqttCommandQueue(config)


class TestCommandQueueOrdering:
    """A failed flush must preserve command order."""

    @pytest.mark.asyncio
    async def test_failed_command_requeued_at_front(self):
        """Regression: a failed command was re-queued at the TAIL behind
        newer commands, so [power_on, set_temp] became [set_temp,
        power_on] on the next flush."""
        queue = _queue()
        queue.enqueue("topic/power_on", {"cmd": "power"}, QoS.AT_LEAST_ONCE)
        queue.enqueue("topic/set_temp", {"cmd": "temp"}, QoS.AT_LEAST_ONCE)

        publish = AsyncMock(side_effect=RuntimeError("still down"))

        sent, failed = await queue.send_all(publish, lambda: True)

        assert (sent, failed) == (0, 1)
        # Order preserved for the next flush
        assert [c.topic for c in queue._queue] == [
            "topic/power_on",
            "topic/set_temp",
        ]

        publish_ok = AsyncMock(return_value=1)
        sent, failed = await queue.send_all(publish_ok, lambda: True)
        assert (sent, failed) == (2, 0)
        sent_topics = [
            call.kwargs["topic"] for call in publish_ok.await_args_list
        ]
        assert sent_topics == ["topic/power_on", "topic/set_temp"]


class TestCommandQueueExpiry:
    """Stale commands must not be replayed to the appliance."""

    @pytest.mark.asyncio
    async def test_expired_commands_discarded_on_flush(self):
        queue = _queue(max_age=300.0)
        queue.enqueue("topic/old", {"cmd": "old"}, QoS.AT_LEAST_ONCE)
        queue.enqueue("topic/new", {"cmd": "new"}, QoS.AT_LEAST_ONCE)
        # Age the first command past the limit
        queue._queue[0].timestamp = datetime.now(UTC) - timedelta(hours=2)

        publish = AsyncMock(return_value=1)
        sent, failed = await queue.send_all(publish, lambda: True)

        assert (sent, failed) == (1, 0)
        sent_topics = [call.kwargs["topic"] for call in publish.await_args_list]
        assert sent_topics == ["topic/new"]

    @pytest.mark.asyncio
    async def test_expiry_disabled_with_none(self):
        queue = _queue(max_age=None)
        queue.enqueue("topic/old", {"cmd": "old"}, QoS.AT_LEAST_ONCE)
        queue._queue[0].timestamp = datetime.now(UTC) - timedelta(days=1)

        publish = AsyncMock(return_value=1)
        sent, failed = await queue.send_all(publish, lambda: True)

        assert (sent, failed) == (1, 0)

    def test_overflow_drops_oldest(self):
        config = MqttConnectionConfig(
            client_id="test-client", max_queued_commands=2
        )
        queue = MqttCommandQueue(config)
        for name in ("a", "b", "c"):
            queue.enqueue(f"topic/{name}", {}, QoS.AT_LEAST_ONCE)

        assert queue.count == 2
        assert [c.topic for c in queue._queue] == ["topic/b", "topic/c"]


class TestAsymmetricNegativeTemperatures:
    """Firmware uses truncated remainder; Python's % is floored."""

    def test_negative_raw_matches_firmware_rounding(self):
        """Regression: raw -11 (-5.5degC) gave -11 % 10 == 9 -> floor ->
        22degF, while the firmware/app's truncated remainder (-1) applies
        ceil -> 23degF."""
        temp = RawCelsius(-11)
        assert (
            temp.to_fahrenheit_with_formula(TempFormulaType.ASYMMETRIC) == 23.0
        )

    def test_positive_raw_behavior_unchanged(self):
        # raw 119 -> 59.5degC -> 139.1degF; remainder 9 -> floor -> 139
        assert (
            RawCelsius(119).to_fahrenheit_with_formula(
                TempFormulaType.ASYMMETRIC
            )
            == 139.0
        )
        # raw 120 -> 60.0degC -> 140.0degF; remainder 0 -> ceil -> 140
        assert (
            RawCelsius(120).to_fahrenheit_with_formula(
                TempFormulaType.ASYMMETRIC
            )
            == 140.0
        )

    def test_negative_raw_with_remainder_nine_equivalent(self):
        # raw -19 -> -9.5degC -> 14.9degF; truncated remainder -9 -> ceil -> 15
        assert (
            RawCelsius(-19).to_fahrenheit_with_formula(
                TempFormulaType.ASYMMETRIC
            )
            == 15.0
        )


class TestFreezeProtectionDefaults:
    """Defaults must be raw half-Celsius values (43degF / 50degF)."""

    def test_defaults_decode_to_documented_range(self, device_status_dict):
        """Regression: defaults 43/65 were Fahrenheit display values
        pasted into raw half-Celsius fields, decoding to 70.7degF/90.5degF
        instead of the documented fixed 43degF/50degF limits."""
        from nwp500.unit_system import set_unit_system

        set_unit_system("us_customary")
        data = dict(device_status_dict)
        data.pop("freezeProtectionTempMin", None)
        data.pop("freezeProtectionTempMax", None)
        status = DeviceStatus.model_validate(data)

        assert status.freeze_protection_temp_min_raw == 12
        assert status.freeze_protection_temp_max_raw == 20
        assert status.freeze_protection_temp_min == pytest.approx(43, abs=1)
        assert status.freeze_protection_temp_max == pytest.approx(50, abs=1)


class TestDemandResponseCapabilityGate:
    """enable/disable_demand_response must be gated on dr_setting_use."""

    @pytest.mark.asyncio
    async def test_enable_blocked_when_unsupported(self, mock_device):
        from nwp500.exceptions import DeviceCapabilityError

        controller, publish = _make_controller()
        controller._get_device_features = AsyncMock(
            return_value=MagicMock(dr_setting_use=False)
        )

        with pytest.raises(DeviceCapabilityError):
            await controller.enable_demand_response(mock_device)
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disable_blocked_when_unsupported(self, mock_device):
        from nwp500.exceptions import DeviceCapabilityError

        controller, publish = _make_controller()
        controller._get_device_features = AsyncMock(
            return_value=MagicMock(dr_setting_use=False)
        )

        with pytest.raises(DeviceCapabilityError):
            await controller.disable_demand_response(mock_device)
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enable_allowed_when_supported(self, mock_device):
        controller, publish = _make_controller()
        controller._get_device_features = AsyncMock(
            return_value=MagicMock(dr_setting_use=True)
        )

        await controller.enable_demand_response(mock_device)
        publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disable_allowed_when_supported(self, mock_device):
        controller, publish = _make_controller()
        controller._get_device_features = AsyncMock(
            return_value=MagicMock(dr_setting_use=True)
        )

        await controller.disable_demand_response(mock_device)
        publish.assert_awaited_once()


class TestErrorCodeChangeEvents:
    """error_detected must fire when the error code changes."""

    @pytest.mark.asyncio
    async def test_error_code_change_emits_error_detected(
        self, device_status_dict
    ):
        """Regression: only 0 -> non-zero emitted error_detected; a
        transition E799 -> E407 emitted nothing, so consumers kept
        displaying the stale error."""
        emitter = EventEmitter()
        tracker = DeviceStateTracker(emitter)

        events = []
        emitter.on("error_detected", lambda e: events.append(int(e.error_code)))

        # Baseline snapshot (no events emitted for the first status)
        await tracker.process("mac", _status(device_status_dict, errorCode=0))
        await tracker.process("mac", _status(device_status_dict, errorCode=799))
        await tracker.process("mac", _status(device_status_dict, errorCode=407))

        assert events == [799, 407]

    @pytest.mark.asyncio
    async def test_unchanged_error_code_not_re_emitted(
        self, device_status_dict
    ):
        emitter = EventEmitter()
        tracker = DeviceStateTracker(emitter)

        events = []
        emitter.on("error_detected", lambda e: events.append(int(e.error_code)))

        await tracker.process("mac", _status(device_status_dict, errorCode=0))
        await tracker.process("mac", _status(device_status_dict, errorCode=799))
        await tracker.process("mac", _status(device_status_dict, errorCode=799))

        assert events == [799]

    @pytest.mark.asyncio
    async def test_error_cleared_still_emitted(self, device_status_dict):
        emitter = EventEmitter()
        tracker = DeviceStateTracker(emitter)

        cleared = []
        emitter.on("error_cleared", lambda e: cleared.append(int(e.error_code)))

        await tracker.process("mac", _status(device_status_dict, errorCode=0))
        await tracker.process("mac", _status(device_status_dict, errorCode=799))
        await tracker.process("mac", _status(device_status_dict, errorCode=0))

        assert cleared == [799]


class TestTouPriceEncoding:
    """Price encoding must round half-up and reject bool as int."""

    def test_encode_price_rounds_half_up(self):
        """Regression: round() applies banker's rounding, under-encoding
        exact halves at even boundaries."""
        assert encode_price(0.125, 2) == 13
        assert encode_price(0.135, 2) == 14
        assert encode_price(12.34, 2) == 1234

    def test_build_tou_period_bool_price_not_treated_as_encoded(self):
        """Regression: bool is an int subclass, so True passed the
        'already encoded' isinstance check and was sent as price 1."""
        period = build_tou_period(
            week_days=["Monday"],
            season_months=[1],
            start_hour=0,
            start_minute=0,
            end_hour=6,
            end_minute=0,
            price_min=True,  # nonsense input, but must be encoded not passed
            price_max=2.5,
            decimal_point=2,
        )
        assert period["priceMin"] == 100  # encode_price(1.0, 2)
        assert period["priceMax"] == 250

    def test_build_tou_period_int_passthrough(self):
        period = build_tou_period(
            week_days=["Monday"],
            season_months=[1],
            start_hour=0,
            start_minute=0,
            end_hour=6,
            end_minute=0,
            price_min=500,  # pre-encoded
            price_max=0.075,
            decimal_point=3,
        )
        assert period["priceMin"] == 500
        assert period["priceMax"] == 75


class TestConfigValidation:
    """MqttConnectionConfig must reject unusable queue settings."""

    def test_zero_max_queued_commands_rejected(self):
        with pytest.raises(ValueError, match="max_queued_commands"):
            MqttConnectionConfig(client_id="t", max_queued_commands=0)

    def test_negative_max_queued_commands_rejected(self):
        with pytest.raises(ValueError, match="max_queued_commands"):
            MqttConnectionConfig(client_id="t", max_queued_commands=-5)

    def test_negative_max_age_rejected(self):
        with pytest.raises(ValueError, match="max_queued_command_age"):
            MqttConnectionConfig(client_id="t", max_queued_command_age=-1.0)

    def test_none_max_age_allowed(self):
        config = MqttConnectionConfig(
            client_id="t", max_queued_command_age=None
        )
        assert config.max_queued_command_age is None

    def test_zero_max_age_allowed(self):
        config = MqttConnectionConfig(client_id="t", max_queued_command_age=0.0)
        assert config.max_queued_command_age == 0.0

    def test_nonpositive_operation_timeout_rejected(self):
        with pytest.raises(ValueError, match="operation_timeout"):
            MqttConnectionConfig(client_id="t", operation_timeout=0)


class TestEncodePriceDecimalPrecision:
    """encode_price must not lose precision by round-tripping via float."""

    def test_decimal_input_used_directly(self):
        from decimal import Decimal

        # A value that is exact as Decimal but not as binary float
        assert encode_price(Decimal("0.145"), 2) == 15  # HALF_UP on exact half

    def test_high_precision_decimal(self):
        from decimal import Decimal

        assert encode_price(Decimal("0.1234567895"), 10) == 1234567895

    def test_int_input(self):
        assert encode_price(100, 0) == 100

    def test_float_input_unchanged_behavior(self):
        assert encode_price(12.34, 2) == 1234
        assert encode_price(0.125, 2) == 13

    def test_rawcelsius_to_fahrenheit_returns_float(self):
        result = RawCelsius(120).to_fahrenheit()
        assert result == 140.0
        assert isinstance(result, float)
