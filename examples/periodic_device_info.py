#!/usr/bin/env python3
"""
Example: Periodic Device Info Requests

This example demonstrates how to use the periodic device info request helper
to automatically request device information at regular intervals.

The helper is useful for:
- Keeping device configuration up-to-date
- Monitoring device availability
- Detecting firmware updates
- Tracking device feature changes
"""

import asyncio
import os
import sys

# Add src directory to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500 import (
    DeviceFeature,
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
)

try:
    from examples.mask import mask_mac  # type: ignore
except Exception:

    def mask_mac(mac):  # pragma: no cover - fallback for examples
        return "[REDACTED_MAC]"


async def main():
    # Get credentials from environment
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Error: NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables required")
        sys.exit(1)

    print("=" * 60)
    print("Periodic Device Info Request Example")
    print("=" * 60)

    # Authenticate and get device
    print("\n1. Authenticating...")
    async with NavienAuthClient(email, password) as auth_client:
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()

    if not device:
        print("Error: No devices found")
        sys.exit(1)

    device_id = device.device_info.mac_address

    print(f"   Device: {device.device_info.device_name}")
    print(f"   MAC: {mask_mac(device_id)}")

    # Connect MQTT
    print("\n2. Connecting to MQTT...")
    mqtt = NavienMqttClient(auth_client)
    await mqtt.connect()
    print(f"   Connected: {mqtt.client_id}")

    # Subscribe to device info responses with typed parsing
    info_count = 0

    def on_device_feature(feature: DeviceFeature):
        """Typed callback for device features."""
        nonlocal info_count
        info_count += 1

        print(f"\n--- Device Info Response #{info_count} ---")
        print(f"Controller Serial: {feature.controllerSerialNumber}")
        print(f"Controller SW Version: {feature.controllerSwVersion}")
        print(f"Heat Pump Use: {feature.heatpumpUse}")
        print(
            f"DHW Temp Min/Max: {feature.dhwTemperatureMin}/{feature.dhwTemperatureMax}°F"
        )

    # Subscribe with typed parsing
    await mqtt.subscribe_device_feature(device, on_device_feature)

    # Example 1: Default period (300 seconds = 5 minutes)
    print("\n3. Starting periodic device info requests (every 5 minutes)...")
    await mqtt.start_periodic_device_info_requests(
        device=device  # period_seconds defaults to 300
    )

    # Send initial request to get immediate response
    print("   Sending initial request...")
    await mqtt.request_device_info(device)

    # Wait for a few updates with the default period
    print("   Waiting 15 seconds for response...")
    await asyncio.sleep(15)

    # Example 2: Custom period (20 seconds for demonstration)
    print("\n4. Changing to faster period (every 20 seconds)...")
    await mqtt.start_periodic_device_info_requests(
        device=device,
        period_seconds=20,  # Request every 20 seconds
    )

    # Send initial request for immediate feedback
    print("   Sending initial request...")
    await mqtt.request_device_info(device)

    # Monitor for 2 minutes
    print("\n   Monitoring for 2 minutes...")
    print("   (You should see device info responses approximately every 20 seconds)")

    for i in range(8):  # 8 x 15 seconds = 120 seconds
        await asyncio.sleep(15)
        print(f"   ... {(i + 1) * 15}s elapsed (responses: {info_count})")

    # Example 3: Stop periodic requests
    print("\n5. Stopping periodic requests...")
    await mqtt.stop_periodic_device_info_requests(device)

    print("\n   Waiting 25 seconds (no new requests should be sent)...")
    for i in range(5):  # 5 x 5 seconds = 25 seconds
        await asyncio.sleep(5)
        print(f"   ... {(i + 1) * 5}s elapsed")

    # Cleanup
    print("\n6. Disconnecting...")
    await mqtt.disconnect()
    print("   Disconnected (all periodic tasks stopped automatically)")

    print(f"\n{'=' * 60}")
    print(f"Summary: Received {info_count} device info response(s)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception:
        import logging

        logging.exception("Error running periodic_device_info example")
        sys.exit(1)
