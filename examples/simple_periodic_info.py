#!/usr/bin/env python3
"""
Simple Example: Periodic Device Info Requests

A minimal example showing how to use periodic device info requests.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500 import (
    DeviceFeature,
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
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
    def on_feature(feature: DeviceFeature):
        print(
            f"Device info: Serial {feature.controllerSerialNumber}, FW {feature.controllerSwVersion}"
        )

    # Subscribe with typed parsing
    await mqtt.subscribe_device_feature(device, on_feature)

    # Start periodic requests (every 5 minutes by default)
    await mqtt.start_periodic_device_info_requests(device=device)

    print("Periodic device info requests started (every 5 minutes)")
    print("Press Ctrl+C to stop...")

    try:
        # Run until interrupted
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
