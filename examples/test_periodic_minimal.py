#!/usr/bin/env python3
"""
Minimal test to verify periodic requests are working
"""

import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500 import (
    DeviceStatus,
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
    PeriodicRequestType,
)


async def main():
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Set NAVIEN_EMAIL and NAVIEN_PASSWORD")
        return

    print("Authenticating...")
    async with NavienAuthClient(email, password) as auth_client:
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()

    if not device:
        print("No devices found")
        return

    device_id = device.device_info.mac_address
    print(f"Device: {device_id}")

    # Connect MQTT
    print("Connecting to MQTT...")
    mqtt = NavienMqttClient(auth_client)
    await mqtt.connect()
    print(f"Connected: {mqtt.client_id}")

    # Track all messages with typed parsing
    message_count = 0

    def on_device_status(status: DeviceStatus):
        """Typed callback for device status."""
        nonlocal message_count
        message_count += 1
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Status #{message_count}")
        print(f"  Temperature: {status.dhwTemperature:.1f}°F")
        print(f"  Power: {status.currentInstPower:.1f}W")

    # Subscribe with typed parsing
    print("Subscribing...")
    await mqtt.subscribe_device_status(device, on_device_status)
    await asyncio.sleep(2)  # Wait for subscription

    # Start periodic requests
    print(
        f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting periodic status requests (every 10 seconds)..."
    )
    await mqtt.start_periodic_requests(
        device=device,
        request_type=PeriodicRequestType.DEVICE_STATUS,
        period_seconds=10,
    )

    # Monitor for 45 seconds (should get ~4 requests)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Monitoring for 45 seconds...\n")

    for i in range(9):  # 9 x 5 = 45 seconds
        await asyncio.sleep(5)
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(
            f"[{timestamp}] ... {(i + 1) * 5}s elapsed, messages received: {message_count}"
        )

    # Cleanup
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Disconnecting...")
    await mqtt.disconnect()
    print(f"Total messages received: {message_count}")


if __name__ == "__main__":
    asyncio.run(main())
