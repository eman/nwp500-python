"""Tests for encoding helper utilities."""

import math

import pytest  # type: ignore[import]

from nwp500.encoding import (
    build_reservation_entry,
    build_tou_period,
    decode_price,
    decode_season_bitfield,
    decode_week_bitfield,
    encode_price,
    encode_season_bitfield,
    encode_week_bitfield,
)
from nwp500.exceptions import (
    ParameterValidationError,
    RangeValidationError,
)


def test_encode_decode_week_bitfield():
    days = ["Monday", "Wednesday", "Friday"]
    bitfield = encode_week_bitfield(days)
    assert bitfield == (64 | 16 | 4)  # Mon=64, Wed=16, Fri=4 → 84
    decoded = decode_week_bitfield(bitfield)
    assert decoded == ["Monday", "Wednesday", "Friday"]

    # Support integer indices (0=Monday, 6=Sunday)
    assert encode_week_bitfield([0, 5]) == (64 | 2)  # Monday(64) + Saturday(2)
    assert encode_week_bitfield([1, 6]) == (32 | 128)  # Tue(32)+Sun(128)

    # Support 2-letter abbreviations
    assert encode_week_bitfield(["MO", "WE", "FR"]) == (64 | 16 | 4)
    assert encode_week_bitfield(["tu", "th"]) == (32 | 8)

    # Known device protocol values (from NaviLink APK)
    assert encode_week_bitfield(["TU", "WE", "TH", "FR", "SA"]) == 62
    assert encode_week_bitfield(["MO", "TU", "WE", "TH", "FR"]) == 124
    assert encode_week_bitfield(["SA", "SU"]) == 130  # Weekend
    assert decode_week_bitfield(62) == [
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]
    assert decode_week_bitfield(124) == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    ]
    assert decode_week_bitfield(130) == ["Saturday", "Sunday"]
    assert decode_week_bitfield(254) == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    # Invalid weekday name raises ParameterValidationError
    with pytest.raises(ParameterValidationError):
        encode_week_bitfield(["Funday"])  # type: ignore[arg-type]

    # Invalid weekday index raises RangeValidationError
    with pytest.raises(RangeValidationError):
        encode_week_bitfield([10])  # type: ignore[arg-type]

    # Value 7 is out of range (0-6 only)
    with pytest.raises(RangeValidationError):
        encode_week_bitfield([7])  # type: ignore[arg-type]


def test_encode_decode_season_bitfield():
    months = [1, 6, 12]
    bitfield = encode_season_bitfield(months)
    assert bitfield == (1 | 32 | 2048)
    decoded = decode_season_bitfield(bitfield)
    assert decoded == months

    with pytest.raises(RangeValidationError):
        encode_season_bitfield([0])


def test_price_encoding_round_trip():
    encoded = encode_price(0.34831, 5)
    assert encoded == 34831
    decoded = decode_price(encoded, 5)
    assert math.isclose(decoded, 0.34831, rel_tol=1e-9)

    with pytest.raises(RangeValidationError):
        encode_price(1.23, -1)


def test_build_reservation_entry():
    reservation = build_reservation_entry(
        enabled=True,
        days=["Monday", "Tuesday"],
        hour=6,
        minute=30,
        mode_id=4,
        temperature=140.0,
    )

    assert reservation["enable"] == 2  # device bool: 2=ON
    assert reservation["week"] == (64 | 32)  # Mon=64, Tue=32
    assert reservation["hour"] == 6
    assert reservation["min"] == 30
    assert reservation["mode"] == 4
    assert reservation["param"] == 120  # 140°F = 60°C = 120 half-degrees

    # Test 120°F conversion
    reservation2 = build_reservation_entry(
        enabled=True,
        days=["Monday"],
        hour=8,
        minute=0,
        mode_id=3,
        temperature=120.0,
    )
    assert reservation2["param"] == 98  # 120°F ≈ 48.9°C ≈ 98 half-degrees

    with pytest.raises(RangeValidationError):
        build_reservation_entry(
            enabled=True,
            days=["Monday"],
            hour=24,
            minute=0,
            mode_id=1,
            temperature=120.0,
        )

    # Test temperature out of range
    with pytest.raises(RangeValidationError):
        build_reservation_entry(
            enabled=True,
            days=["Monday"],
            hour=6,
            minute=0,
            mode_id=1,
            temperature=200.0,  # Too high
        )


def test_build_tou_period():
    period = build_tou_period(
        season_months=range(1, 13),
        week_days=["Monday", "Friday"],
        start_hour=0,
        start_minute=0,
        end_hour=14,
        end_minute=59,
        price_min=0.34831,
        price_max=0.36217,
        decimal_point=5,
    )

    assert period["season"] == (2**12 - 1)
    assert period["week"] == (64 | 4)  # Mon=64, Fri=4
    assert period["startHour"] == 0
    assert period["endHour"] == 14
    assert period["priceMin"] == 34831
    assert period["priceMax"] == 36217

    with pytest.raises(RangeValidationError):
        build_tou_period(
            season_months=[1],
            week_days=["Sunday"],
            start_hour=25,
            start_minute=0,
            end_hour=1,
            end_minute=0,
            price_min=0.1,
            price_max=0.2,
            decimal_point=5,
        )
