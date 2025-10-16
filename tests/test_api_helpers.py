"""Tests for NavienAPIClient helper utilities."""

import math

import pytest  # type: ignore[import]

from nwp500.api_client import NavienAPIClient


def test_encode_decode_week_bitfield():
    days = ["Monday", "Wednesday", "Friday"]
    bitfield = NavienAPIClient.encode_week_bitfield(days)
    assert bitfield == (2 | 8 | 32)
    decoded = NavienAPIClient.decode_week_bitfield(bitfield)
    assert decoded == ["Monday", "Wednesday", "Friday"]

    # Support integer indices (0=Sunday) and 1-based (1=Monday)
    assert NavienAPIClient.encode_week_bitfield([0, 6]) == (1 | 64)
    assert NavienAPIClient.encode_week_bitfield([1, 7]) == (2 | 64)

    with pytest.raises(ValueError):
        NavienAPIClient.encode_week_bitfield(["Funday"])  # type: ignore[arg-type]


def test_encode_decode_season_bitfield():
    months = [1, 6, 12]
    bitfield = NavienAPIClient.encode_season_bitfield(months)
    assert bitfield == (1 | 32 | 2048)
    decoded = NavienAPIClient.decode_season_bitfield(bitfield)
    assert decoded == months

    with pytest.raises(ValueError):
        NavienAPIClient.encode_season_bitfield([0])


def test_price_encoding_round_trip():
    encoded = NavienAPIClient.encode_price(0.34831, 5)
    assert encoded == 34831
    decoded = NavienAPIClient.decode_price(encoded, 5)
    assert math.isclose(decoded, 0.34831, rel_tol=1e-9)

    with pytest.raises(ValueError):
        NavienAPIClient.encode_price(1.23, -1)


def test_build_reservation_entry():
    reservation = NavienAPIClient.build_reservation_entry(
        enabled=True,
        days=["Monday", "Tuesday"],
        hour=6,
        minute=30,
        mode_id=4,
        param=120,
    )

    assert reservation["enable"] == 1
    assert reservation["week"] == (2 | 4)
    assert reservation["hour"] == 6
    assert reservation["min"] == 30
    assert reservation["mode"] == 4
    assert reservation["param"] == 120

    with pytest.raises(ValueError):
        NavienAPIClient.build_reservation_entry(
            enabled=True,
            days=["Monday"],
            hour=24,
            minute=0,
            mode_id=1,
            param=100,
        )


def test_build_tou_period():
    period = NavienAPIClient.build_tou_period(
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
    assert period["week"] == (2 | 32)
    assert period["startHour"] == 0
    assert period["endHour"] == 14
    assert period["priceMin"] == 34831
    assert period["priceMax"] == 36217

    with pytest.raises(ValueError):
        NavienAPIClient.build_tou_period(
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
