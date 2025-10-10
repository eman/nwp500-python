#!/usr/bin/env python3
"""
Simple Example: Periodic Status Requests

A minimal example showing periodic device status requests.
"""

import asyncio
import os
import sys

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
        print("Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return

    # Authenticate and get device
    async with NavienAuthClient(email, password) as auth_client:
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()

    # Connect MQTT
    mqtt = NavienMqttClient(auth_client)
    await mqtt.connect()

    # Typed callback
    def on_status(status: DeviceStatus):
        print(f"Status: {status.dhwTemperature:.1f}°F, {status.currentInstPower:.1f}W")

    # Subscribe with typed parsing
    await mqtt.subscribe_device_status(device, on_status)

    # Start periodic status requests (every 5 minutes by default)
    await mqtt.start_periodic_requests(
        device=device, request_type=PeriodicRequestType.DEVICE_STATUS
    )

    print("Periodic status requests started (every 5 minutes)")
    print("Press Ctrl+C to stop...")

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nStopping...")
    finally:
        await mqtt.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete.")
