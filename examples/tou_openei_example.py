#!/usr/bin/env python3
"""
Example: Retrieve TOU schedule from OpenEI API and configure device.

This example demonstrates how to:
1. Query the OpenEI Utility Rates API for electricity rate plans
2. Parse the rate structure from the API response
3. Convert OpenEI rate schedules into TOU periods
4. Configure the TOU schedule on a Navien device via MQTT
"""

import asyncio
import os
import sys
from typing import Any

import aiohttp

from nwp500 import (
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
    build_tou_period,
    decode_price,
    decode_week_bitfield,
)

# OpenEI API configuration
OPENEI_API_URL = "https://api.openei.org/utility_rates"
OPENEI_API_VERSION = 7

# You can get a free API key from https://openei.org/services/api/signup/
# For testing purposes, you can use the demo key (rate limited)
OPENEI_API_KEY = "DEMO_KEY"


async def fetch_openei_rates(
    zip_code: str, api_key: str = OPENEI_API_KEY
) -> dict[str, Any]:
    """
    Fetch utility rate information from OpenEI API.

    Args:
        zip_code: ZIP code to search for rates
        api_key: OpenEI API key (default: DEMO_KEY)

    Returns:
        Dictionary containing rate plan data from OpenEI

    Raises:
        aiohttp.ClientError: If the API request fails
    """
    params = {
        "version": OPENEI_API_VERSION,
        "format": "json",
        "api_key": api_key,
        "detail": "full",
        "address": zip_code,
        "sector": "Residential",
        "orderby": "startdate",
        "direction": "desc",
        "limit": 100,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(OPENEI_API_URL, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            return data


def select_rate_plan(rate_data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Select a suitable rate plan from OpenEI response.

    This example selects the first approved residential rate plan
    with time-of-use pricing (has energyweekdayschedule).

    Args:
        rate_data: Response data from OpenEI API

    Returns:
        Selected rate plan dictionary, or None if no suitable plan found
    """
    items = rate_data.get("items", [])

    for plan in items:
        # Look for approved residential plans with TOU schedules
        if (
            plan.get("approved")
            and plan.get("sector") == "Residential"
            and "energyweekdayschedule" in plan
            and "energyratestructure" in plan
        ):
            return plan

    return None


def convert_openei_to_tou_periods(
    rate_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Convert OpenEI rate plan to TOU period format for Navien device.

    This is a simplified conversion that handles basic TOU schedules.
    More complex rate structures (e.g., tiered rates, demand charges)
    may require additional logic.

    Args:
        rate_plan: Rate plan data from OpenEI

    Returns:
        List of TOU period dictionaries ready for device configuration
    """
    weekday_schedule = rate_plan.get("energyweekdayschedule", [[]])
    # Note: weekend_schedule available but not used in this simplified example
    # weekend_schedule = rate_plan.get("energyweekendschedule", [[]])
    rate_structure = rate_plan.get("energyratestructure", [[]])

    # For simplicity, we'll use the first month's schedule
    # A production implementation would handle all 12 months
    if not weekday_schedule or not weekday_schedule[0]:
        print("Warning: No weekday schedule found in rate plan")
        return []

    hourly_schedule = weekday_schedule[0]  # 24-hour array

    # Extract unique rate periods from the hourly schedule
    # Build a map of period_index -> rate
    period_to_rate = {}
    for month_idx, month_tiers in enumerate(rate_structure):
        if month_tiers:
            for tier_idx, tier in enumerate(month_tiers):
                if tier_idx not in period_to_rate:
                    period_to_rate[tier_idx] = tier.get("rate", 0.0)

    # Find continuous time blocks with the same rate period
    periods = []
    current_period = None
    start_hour = 0

    for hour in range(24):
        period_idx = hourly_schedule[hour]

        if current_period is None:
            # Start of first period
            current_period = period_idx
            start_hour = hour
        elif period_idx != current_period:
            # Period changed, save previous period
            rate = period_to_rate.get(current_period, 0.0)
            periods.append(
                {
                    "start_hour": start_hour,
                    "end_hour": hour - 1,
                    "end_minute": 59,
                    "rate": rate,
                }
            )

            # Start new period
            current_period = period_idx
            start_hour = hour

    # Don't forget the last period
    if current_period is not None:
        rate = period_to_rate.get(current_period, 0.0)
        periods.append(
            {
                "start_hour": start_hour,
                "end_hour": 23,
                "end_minute": 59,
                "rate": rate,
            }
        )

    # Convert to TOU period format
    tou_periods = []
    weekdays = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    ]

    for period in periods:
        tou_period = build_tou_period(
            season_months=range(1, 13),  # All months
            week_days=weekdays,
            start_hour=period["start_hour"],
            start_minute=0,
            end_hour=period["end_hour"],
            end_minute=period["end_minute"],
            price_min=period["rate"],
            price_max=period["rate"],
            decimal_point=5,
        )
        tou_periods.append(tou_period)

    return tou_periods


async def _wait_for_controller_serial(mqtt_client: NavienMqttClient, device) -> str:
    """Get controller serial number from device."""
    loop = asyncio.get_running_loop()
    feature_future: asyncio.Future = loop.create_future()

    def capture_feature(feature) -> None:
        if not feature_future.done():
            feature_future.set_result(feature)

    await mqtt_client.subscribe_device_feature(device, capture_feature)
    await mqtt_client.request_device_info(device)
    feature = await asyncio.wait_for(feature_future, timeout=15)
    return feature.controller_serial_number


async def main() -> None:
    # Check for required environment variables
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")
    zip_code = os.getenv("ZIP_CODE", "94103")  # Default to SF

    if not email or not password:
        print("Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        sys.exit(1)

    # Optional: Use custom OpenEI API key
    api_key = os.getenv("OPENEI_API_KEY", OPENEI_API_KEY)

    print(f"Fetching utility rates for ZIP code: {zip_code}")
    print("(This may take a few seconds...)")

    # Step 1: Fetch rate data from OpenEI
    try:
        rate_data = await fetch_openei_rates(zip_code, api_key)
    except Exception as e:
        print(f"Error fetching OpenEI data: {e}")
        sys.exit(1)

    # Step 2: Select a suitable rate plan
    rate_plan = select_rate_plan(rate_data)
    if not rate_plan:
        print("No suitable TOU rate plan found for this location")
        sys.exit(1)

    print("\nSelected rate plan:")
    print(f"  Utility: {rate_plan.get('utility')}")
    print(f"  Name: {rate_plan.get('name')}")
    print(f"  EIA ID: {rate_plan.get('eiaid')}")

    # Step 3: Convert rate plan to TOU periods
    tou_periods = convert_openei_to_tou_periods(rate_plan)

    if not tou_periods:
        print("Could not convert rate plan to TOU periods")
        sys.exit(1)

    print(f"\nConverted to {len(tou_periods)} TOU periods:")
    for i, period in enumerate(tou_periods, 1):
        # Decode for display
        days = decode_week_bitfield(period["week"])
        price = decode_price(period["priceMin"], period["decimalPoint"])
        print(
            f"  {i}. {period['startHour']:02d}:{period['startMinute']:02d}"
            f"-{period['endHour']:02d}:{period['endMinute']:02d} "
            f"@ ${price:.5f}/kWh ({', '.join(days[:2])}...)"
        )

    # Step 4: Connect to Navien device
    print("\nConnecting to Navien device...")
    async with NavienAuthClient(email, password) as auth_client:
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()

        if not device:
            print("No devices found for this account")
            return

        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()

        print("Getting controller serial number...")
        try:
            controller_serial = await _wait_for_controller_serial(mqtt_client, device)
        except asyncio.TimeoutError:
            print("Timed out waiting for device info")
            await mqtt_client.disconnect()
            return

        # Step 5: Configure TOU schedule on device
        print("\nConfiguring TOU schedule on device...")

        response_topic = (
            f"cmd/{device.device_info.device_type}/"
            f"{mqtt_client.config.client_id}/res/tou/rd"
        )

        def on_tou_response(topic: str, message: dict[str, Any]) -> None:
            response = message.get("response", {})
            enabled = response.get("reservationUse")
            print("\nDevice confirmed TOU schedule configured")
            print(f"  Enabled: {enabled == 2}")
            print(f"  Periods: {len(response.get('reservation', []))}")

        await mqtt_client.subscribe(response_topic, on_tou_response)

        await mqtt_client.configure_tou_schedule(
            device=device,
            controller_serial_number=controller_serial,
            periods=tou_periods,
            enabled=True,
        )

        print("Waiting for device confirmation...")
        await asyncio.sleep(5)

        await mqtt_client.disconnect()
        print("\nTOU schedule from OpenEI successfully configured!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled by user")
