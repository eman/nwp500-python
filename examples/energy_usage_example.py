#!/usr/bin/env python3
"""
Example: Energy Usage Monitoring

This example demonstrates how to query and monitor historical energy usage
data from a Navien NWP500 water heater, including:
- Heat pump energy consumption and operating time
- Electric heating element energy consumption and operating time
- Daily energy usage breakdown
- Energy efficiency percentages

The energy data comes from the EMS (Energy Management System) API.
"""

import asyncio
import os
import sys
from datetime import datetime

from nwp500 import (
    EnergyUsageResponse,
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
)


async def main():
    # Get credentials from environment
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        sys.exit(1)

    # Energy usage callback
    def on_energy_usage(energy: EnergyUsageResponse):
        """Handle energy usage data."""
        print("\n" + "=" * 70)
        print("ENERGY USAGE REPORT (EMS Data)")
        print("=" * 70)

        # Total statistics
        print("\n📊 TOTAL STATISTICS")
        print(f"   Total Energy Consumption: {energy.total.total_usage:,} Wh")
        print(f"   Total Operating Time: {energy.total.total_time} hours")
        print()

        # Heat pump details
        print("🔵 HEAT PUMP")
        print(
            f"   Energy Usage: {energy.total.hpUsage:,} Wh ({energy.total.heat_pump_percentage:.1f}%)"
        )
        print(f"   Operating Time: {energy.total.hpTime} hours")
        print()

        # Electric heater details
        print("🔴 ELECTRIC HEATER")
        print(
            f"   Energy Usage: {energy.total.heUsage:,} Wh ({energy.total.heat_element_percentage:.1f}%)"
        )
        print(f"   Operating Time: {energy.total.heTime} hours")
        print()

        # Efficiency analysis
        hp_pct = energy.total.heat_pump_percentage
        if hp_pct > 80:
            efficiency_rating = "Excellent"
            emoji = "🌟"
        elif hp_pct > 60:
            efficiency_rating = "Good"
            emoji = "✅"
        elif hp_pct > 40:
            efficiency_rating = "Fair"
            emoji = "⚠️"
        else:
            efficiency_rating = "Poor"
            emoji = "⚠️"

        print(f"⚡ EFFICIENCY RATING: {emoji} {efficiency_rating}")
        print("   (Higher heat pump usage = better efficiency)")
        print()

        # Daily breakdown
        print("📅 DAILY BREAKDOWN")
        for month_data in energy.usage:
            print(f"\n   {month_data.year}-{month_data.month:02d}:")

            for day_num, day_data in enumerate(month_data.data, start=1):
                if day_data.total_usage > 0:  # Only show days with usage
                    date_str = f"{month_data.year}-{month_data.month:02d}-{day_num:02d}"
                    hp_pct_day = (
                        (day_data.hpUsage / day_data.total_usage * 100)
                        if day_data.total_usage > 0
                        else 0
                    )

                    print(
                        f"   {date_str}: {day_data.total_usage:5,} Wh "
                        f"(HP: {day_data.hpUsage:5,} Wh, HE: {day_data.heUsage:4,} Wh, "
                        f"HP%: {hp_pct_day:4.1f}%)"
                    )

        print("\n" + "=" * 70)

    # Create API client and authenticate
    print("Authenticating...")
    async with NavienAuthClient(email, password) as auth_client:
        print("✓ Authenticated")

        # Create API client with authenticated auth_client
        api_client = NavienAPIClient(auth_client=auth_client)

        # Get devices
        devices = await api_client.list_devices()

        if not devices:
            print("No devices found")
            return

        device = devices[0]
        # Avoid logging sensitive info such as MAC address.
        print(f"✓ Device detected: {device.device_info.device_name}")

        # Connect to MQTT
        print("\nConnecting to MQTT...")
        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()
        print("✓ Connected to MQTT")

        # Subscribe to energy usage responses
        print("\nSubscribing to energy usage data...")
        await mqtt_client.subscribe_energy_usage(device, on_energy_usage)
        print("✓ Subscribed to energy usage responses")

        # Request energy usage for current month
        now = datetime.now()
        current_year = now.year
        current_month = now.month

        print(f"\nRequesting energy usage for {current_year}-{current_month:02d}...")
        await mqtt_client.request_energy_usage(
            device, year=current_year, months=[current_month]
        )
        print("✓ Request sent")

        # Wait for response
        print("\nWaiting for energy data (up to 30 seconds)...")
        await asyncio.sleep(30)

        # Cleanup
        print("\nDisconnecting...")
        await mqtt_client.disconnect()
        print("✓ Disconnected")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()
