"""Tests for the public API surface of the nwp500 package."""

import nwp500


def test_all_names_resolve():
    """Every name in __all__ must exist on the package."""
    missing = [name for name in nwp500.__all__ if not hasattr(nwp500, name)]
    assert missing == []


def test_internal_plumbing_not_exported():
    """Internal helpers must not be part of the public surface."""
    internal = [
        "requires_capability",
        "MqttDeviceInfoCache",
        "MqttDeviceCapabilityChecker",
        "log_performance",
        "encode_week_bitfield",
        "decode_week_bitfield",
        "encode_season_bitfield",
        "decode_season_bitfield",
        "encode_price",
        "decode_price",
        "build_reservation_entry",
        "build_tou_period",
    ]
    exported = [name for name in internal if name in nwp500.__all__]
    assert exported == []


def test_removed_exceptions_are_gone():
    """Dead exception classes were removed (never raised anywhere)."""
    removed = [
        "TokenExpiredError",
        "MqttSubscriptionError",
        "DeviceNotFoundError",
        "DeviceOfflineError",
        "DeviceOperationError",
    ]
    still_present = [name for name in removed if hasattr(nwp500, name)]
    assert still_present == []


def test_encoding_helpers_importable_from_submodule():
    """Encoding helpers remain available from nwp500.encoding."""
    from nwp500.encoding import (
        build_reservation_entry,
        build_tou_period,
        decode_price,
        decode_week_bitfield,
        encode_price,
        encode_week_bitfield,
    )

    assert callable(build_reservation_entry)
    assert callable(build_tou_period)
    assert callable(encode_price)
    assert callable(decode_price)
    assert callable(encode_week_bitfield)
    assert callable(decode_week_bitfield)


def test_mqtt_tou_read_is_gone():
    """There is no MQTT read for the TOU schedule; ctrl/tou/rd is the write.

    ``request_tou_settings`` published a TOU_RESERVATION control message with
    no schedule and waited for a reply the device never sends. Reads go
    through ``NavienAPIClient.get_tou_info``.
    """
    from nwp500 import NavienAPIClient, NavienMqttClient

    assert not hasattr(NavienMqttClient, "request_tou_settings")
    assert hasattr(NavienAPIClient, "get_tou_info")


def test_invented_mqtt_commands_are_gone():
    """Commands the NaviLink app declares but never sends were removed.

    The app's request builder has no case for OTA check, WiFi reset or
    reconnect, freeze protection temperature or smart diagnostic, and it
    writes its weekly schedule with ``update_reservations`` on
    ``ctrl/rsv/rd``, never with 33554438. The library's methods for those
    sent made-up payloads.
    """
    from nwp500 import NavienMqttClient

    removed = [
        "check_firmware_update",
        "reconnect_wifi",
        "reset_wifi",
        "set_freeze_protection_temperature",
        "run_smart_diagnostic",
        "update_weekly_reservation",
        "subscribe_weekly_reservation_response",
        "unsubscribe_weekly_reservation_response",
    ]
    still_present = [n for n in removed if hasattr(NavienMqttClient, n)]
    assert still_present == []
    assert not hasattr(nwp500, "WeeklyReservationSchedule")
    assert not hasattr(nwp500, "WeeklyReservationEntry")


def test_app_queries_and_controls_are_exposed():
    """Every query and control the NaviLink app sends has a client method."""
    from nwp500 import NavienMqttClient

    expected = [
        "request_diagnostics",
        "subscribe_diagnostics",
        "request_energy_usage_monthly",
        "subscribe_energy_usage_monthly",
        "request_energy_usage_hourly",
        "subscribe_energy_usage_hourly",
        "request_recirculation_schedule",
        "request_firmware_download_info",
        "subscribe_firmware_download_info",
        "end_session",
        "set_vacation_duration",
        "set_air_filter_life",
        "reset_condenser_fault",
    ]
    missing = [n for n in expected if not hasattr(NavienMqttClient, n)]
    assert missing == []
    for name in (
        "DeviceDiagnostics",
        "DiagnosticsEventCounters",
        "DiagnosticsDhwUsage",
        "DiagnosticsComponentCounters",
        "FirmwareDownloadInfo",
        "FirmwareDownloadEntry",
    ):
        assert name in nwp500.__all__
