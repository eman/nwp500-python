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
