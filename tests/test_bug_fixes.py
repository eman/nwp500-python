"""Tests for bug fixes: diagnostics, config validation, encoding, cache."""

import asyncio
import json
from unittest.mock import patch

import pytest

from nwp500.encoding import build_reservation_entry, decode_reservation_hex
from nwp500.events import EventEmitter
from nwp500.mqtt.diagnostics import MqttDiagnosticsCollector, MqttMetrics
from nwp500.mqtt.utils import MqttConnectionConfig


class TestMqttConnectionConfigValidation:
    """Tests for MqttConnectionConfig validation."""

    def test_deep_reconnect_threshold_zero_clamped(self):
        """deep_reconnect_threshold=0 should be clamped to 1."""
        config = MqttConnectionConfig(deep_reconnect_threshold=0)
        assert config.deep_reconnect_threshold == 1

    def test_deep_reconnect_threshold_negative_clamped(self):
        """Negative deep_reconnect_threshold should be clamped to 1."""
        config = MqttConnectionConfig(deep_reconnect_threshold=-5)
        assert config.deep_reconnect_threshold == 1

    def test_deep_reconnect_threshold_valid_preserved(self):
        """Valid deep_reconnect_threshold should be preserved."""
        config = MqttConnectionConfig(deep_reconnect_threshold=5)
        assert config.deep_reconnect_threshold == 5

    def test_default_deep_reconnect_threshold(self):
        """Default deep_reconnect_threshold should be 10."""
        config = MqttConnectionConfig()
        assert config.deep_reconnect_threshold == 10


class TestDiagnosticsReconnectCounter:
    """Tests for total_reconnect_attempts counter."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_reconnect_attempts_incremented_on_drop(self):
        """total_reconnect_attempts should increment on each drop."""
        collector = MqttDiagnosticsCollector()
        assert collector._metrics.total_reconnect_attempts == 0

        await collector.record_connection_drop(error=RuntimeError("test"))
        assert collector._metrics.total_reconnect_attempts == 1

        await collector.record_connection_drop(error=RuntimeError("test2"))
        assert collector._metrics.total_reconnect_attempts == 2

    @pytest.mark.asyncio(loop_scope="function")
    async def test_drop_increments_both_counters(self):
        """Both total_connection_drops and total_reconnect_attempts update."""
        collector = MqttDiagnosticsCollector()
        await collector.record_connection_drop(error=RuntimeError("test"))
        assert collector._metrics.total_connection_drops == 1
        assert collector._metrics.total_reconnect_attempts == 1


class TestMqttMetricsSerialization:
    """Tests for MqttMetrics JSON serialization."""

    def test_to_dict_replaces_inf(self):
        """to_dict should replace inf with None for JSON compatibility."""
        metrics = MqttMetrics()
        d = metrics.to_dict()
        assert d["shortest_session_seconds"] is None

    def test_to_dict_preserves_real_value(self):
        """to_dict should preserve real shortest_session_seconds values."""
        metrics = MqttMetrics(shortest_session_seconds=42.5)
        d = metrics.to_dict()
        assert d["shortest_session_seconds"] == 42.5

    def test_to_dict_json_serializable(self):
        """Default MqttMetrics should be JSON-serializable."""
        metrics = MqttMetrics()
        # Should not raise
        result = json.dumps(metrics.to_dict())
        assert isinstance(result, str)


class TestEventEmitterFuture:
    """Tests for EventEmitter.wait_for future creation."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_wait_for_uses_running_loop(self):
        """wait_for should create future bound to running loop."""
        emitter = EventEmitter()

        async def emit_soon():
            await asyncio.sleep(0.01)
            await emitter.emit("test_event", "data")

        task = asyncio.create_task(emit_soon())
        result = await emitter.wait_for("test_event", timeout=1.0)
        await task
        assert result == ("data",)


class TestDecodeReservationHex:
    """Tests for decode_reservation_hex partial data handling."""

    def test_valid_hex_decoded(self):
        """Valid 6-byte entries should be decoded."""
        result = decode_reservation_hex("013e061e0478")
        assert len(result) == 1
        assert result[0]["enable"] == 1

    def test_partial_entry_logged_and_skipped(self):
        """Partial trailing bytes should be skipped with warning."""
        # 6 valid bytes + 3 trailing bytes
        result = decode_reservation_hex("013e061e0478aabbcc")
        assert len(result) == 1  # Only the complete entry

    def test_empty_hex(self):
        """Empty hex string should return empty list."""
        assert decode_reservation_hex("") == []


class TestBuildReservationEntryTempValidation:
    """Tests for unit-aware temperature validation."""

    @patch("nwp500.unit_system.get_unit_system", return_value="metric")
    def test_celsius_defaults(self, _mock_unit):
        """Metric mode should use Celsius defaults (35-65)."""
        # 50°C is valid in metric mode
        result = build_reservation_entry(
            enabled=True,
            days=["Monday"],
            hour=6,
            minute=30,
            mode_id=3,
            temperature=50.0,
        )
        assert "param" in result

    @patch("nwp500.unit_system.get_unit_system", return_value="metric")
    def test_celsius_rejects_fahrenheit_values(self, _mock_unit):
        """Values outside Celsius range should be rejected in metric mode."""
        from nwp500.exceptions import RangeValidationError

        with pytest.raises(RangeValidationError):
            build_reservation_entry(
                enabled=True,
                days=["Monday"],
                hour=6,
                minute=30,
                mode_id=3,
                temperature=140.0,  # Fahrenheit value, too high for Celsius
            )

    @patch("nwp500.unit_system.get_unit_system", return_value="us_customary")
    def test_fahrenheit_defaults(self, _mock_unit):
        """US customary mode should use Fahrenheit defaults (95-150)."""
        result = build_reservation_entry(
            enabled=True,
            days=["Monday"],
            hour=6,
            minute=30,
            mode_id=3,
            temperature=140.0,
        )
        assert "param" in result

    @patch("nwp500.unit_system.get_unit_system", return_value="us_customary")
    def test_fahrenheit_rejects_low_celsius(self, _mock_unit):
        """Values outside Fahrenheit range should be rejected in US mode."""
        from nwp500.exceptions import RangeValidationError

        with pytest.raises(RangeValidationError):
            build_reservation_entry(
                enabled=True,
                days=["Monday"],
                hour=6,
                minute=30,
                mode_id=3,
                temperature=50.0,  # Celsius value, too low for Fahrenheit
            )

    @patch("nwp500.unit_system.get_unit_system", return_value="metric")
    def test_explicit_limits_override_defaults(self, _mock_unit):
        """Explicit temperature_min/max should override unit defaults."""
        result = build_reservation_entry(
            enabled=True,
            days=["Monday"],
            hour=6,
            minute=30,
            mode_id=3,
            temperature=80.0,
            temperature_min=70.0,
            temperature_max=90.0,
        )
        assert "param" in result
