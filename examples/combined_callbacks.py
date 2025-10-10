#!/usr/bin/env python3
"""
Example: Combined Status and Feature Callbacks

This example demonstrates using both subscribe_device_status() and
subscribe_device_feature() together to get complete device information.

Requirements:
- Set environment variables: NAVIEN_EMAIL and NAVIEN_PASSWORD
- Have at least one device registered in your account
"""

import asyncio
import logging
import os
import sys

# Setup logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("nwp500.mqtt_client").setLevel(logging.INFO)
logging.getLogger("nwp500.auth").setLevel(logging.INFO)
logging.getLogger("nwp500.api_client").setLevel(logging.INFO)

# If running from examples directory, add parent to path
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500.api_client import NavienAPIClient
from nwp500.auth import NavienAuthClient
from nwp500.models import DeviceFeature, DeviceStatus
from nwp500.mqtt_client import NavienMqttClient


async def main():
    """Main example function."""

    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print(
            "❌ Error: Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables"
        )
        return 1

    print("=" * 70)
    print("Combined Callbacks Example - Status + Feature")
    print("=" * 70)
    print()

    try:
        async with NavienAuthClient(email, password) as auth_client:
            print(f"✅ Authenticated as: {auth_client.current_user.full_name}")
            print()

            api_client = NavienAPIClient(
                auth_client=auth_client, session=auth_client._session
            )
            devices = await api_client.list_devices()

            if not devices:
                print("❌ No devices found")
                return 1

            device = devices[0]
            device_id = device.device_info.mac_address
            device_type = device.device_info.device_type

            print(f"Device: {device.device_info.device_name} ({device_id})")
            print()

            mqtt_client = NavienMqttClient(auth_client)

            try:
                await mqtt_client.connect()
                print("✅ Connected to MQTT")
                print()

                counts = {"status": 0, "feature": 0}

                # Callback for status updates
                def on_status(status: DeviceStatus):
                    counts["status"] += 1
                    print(f"\n📊 Status Update #{counts['status']}")
                    print(f"  Mode: {status.operationMode.name}")
                    print(f"  DHW Temp: {status.dhwTemperature:.1f}°F")
                    print(f"  DHW Charge: {status.dhwChargePer:.1f}%")
                    print(f"  Compressor: {'On' if status.compUse else 'Off'}")

                # Callback for feature/capability info
                def on_feature(feature: DeviceFeature):
                    counts["feature"] += 1
                    print(f"\n📋 Feature Info #{counts['feature']}")
                    print(f"  Serial: {feature.controllerSerialNumber}")
                    print(f"  FW Version: {feature.controllerSwVersion}")
                    print(
                        f"  Temp Range: {feature.dhwTemperatureMin}-{feature.dhwTemperatureMax}°F"
                    )
                    print(f"  Heat Pump: {'Yes' if feature.heatpumpUse == 2 else 'No'}")
                    print(f"  Electric: {'Yes' if feature.electricUse == 2 else 'No'}")

                # Subscribe to broader topics to catch all messages
                print("Subscribing to status and feature callbacks...")
                device_topic = f"navilink-{device_id}"

                # Subscribe to all command messages
                await mqtt_client.subscribe(
                    f"cmd/{device_type}/{device_topic}/#",
                    lambda topic, msg: None,  # Will be handled by typed callbacks
                )
                # Subscribe to all event messages
                await mqtt_client.subscribe(
                    f"evt/{device_type}/{device_topic}/#",
                    lambda topic, msg: None,  # Will be handled by typed callbacks
                )

                # Now subscribe to typed callbacks
                await mqtt_client.subscribe_device_status(device, on_status)
                await mqtt_client.subscribe_device_feature(device, on_feature)
                print("✅ Subscribed to both callbacks")
                print()

                # Request both types of data
                print("Requesting device info and status...")
                await mqtt_client.signal_app_connection(device)
                await asyncio.sleep(1)

                await mqtt_client.request_device_info(device)
                await asyncio.sleep(2)

                await mqtt_client.request_device_status(device)
                print("✅ Requests sent")
                print()

                # Wait for responses
                print("⏳ Waiting for responses (15 seconds)...")
                await asyncio.sleep(15)

                print()
                print("=" * 70)
                print("📊 Summary:")
                print(f"  Status updates:  {counts['status']}")
                print(f"  Feature messages: {counts['feature']}")
                print("=" * 70)

                await mqtt_client.disconnect()
                print("\n✅ Disconnected")

            except Exception as e:
                print(f"❌ Error: {e}")
                if mqtt_client.is_connected:
                    await mqtt_client.disconnect()
                return 1

        return 0

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
