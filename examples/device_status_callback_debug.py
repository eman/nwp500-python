#!/usr/bin/env python3
"""
Debug version of device status callback example.

This version shows ALL messages received, not just status messages,
to help debug why status callbacks might not be invoked.
"""

import asyncio
import json
import logging
import os
import sys

# Setup logging with DEBUG level
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# If running from examples directory, add parent to path
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500.api_client import NavienAPIClient
from nwp500.auth import AuthenticationError, NavienAuthClient
from nwp500.models import DeviceStatus
from nwp500.mqtt_client import NavienMqttClient

try:
    from examples.mask import mask_mac  # type: ignore
except Exception:

    def mask_mac(mac):  # pragma: no cover - fallback
        return "[REDACTED_MAC]"


async def main():
    """Main example function."""

    # Get credentials from environment variables
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print(
            "❌ Error: Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables"
        )
        return 1

    print("=" * 70)
    print("Device Status Callback DEBUG - See All Messages")
    print("=" * 70)
    print()

    try:
        # Step 1: Authenticate and get AWS credentials
        print("Step 1: Authenticating with Navien API...")
        async with NavienAuthClient(email, password) as auth_client:
            print(f"✅ Authenticated as: {auth_client.current_user.full_name}")
            print()

            # Step 2: Get device list
            print("Step 2: Fetching device list...")
            api_client = NavienAPIClient(
                auth_client=auth_client, session=auth_client._session
            )
            devices = await api_client.list_devices()

            if not devices:
                print("❌ Error: No devices found in your account")
                return 1

            device = devices[0]
            device_id = device.device_info.mac_address
            device_type = device.device_info.device_type

            try:
                from examples.mask import mask_any  # type: ignore
            except Exception:

                def mask_any(_):
                    return "[REDACTED]"

            print(f"✅ Using device: {device.device_info.device_name}")
            print(f"   MAC Address: {mask_mac(device_id)}")
            print(f"   Device Type: {mask_any(device_type)}")
            print()

            # Step 3: Create MQTT client and connect
            print("Step 3: Connecting to AWS IoT via MQTT...")
            mqtt_client = NavienMqttClient(auth_client)

            try:
                await mqtt_client.connect()
                print("✅ Connected to AWS IoT Core")
                print()

                # Step 4: Subscribe with BOTH raw and parsed callbacks
                print("Step 4: Subscribing to device messages...")

                message_count = {"raw": 0, "status": 0}

                # First, subscribe to ALL messages to see what we receive
                def raw_message_handler(topic: str, message: dict):
                    """Log all raw messages."""
                    message_count["raw"] += 1
                    print(f"\n📩 RAW Message #{message_count['raw']} on topic: {topic}")
                    print(f"   Message keys: {list(message.keys())}")

                    if "response" in message:
                        print(f"   Response keys: {list(message['response'].keys())}")

                        if "status" in message["response"]:
                            print("   ✅ Contains STATUS data")
                            status_keys = list(message["response"]["status"].keys())[
                                :10
                            ]
                            print(f"   Status sample keys: {status_keys}...")

                        if "feature" in message["response"]:
                            print("   Contains FEATURE data (device info)")

                    print(f"   Full message: {json.dumps(message, indent=2)[:500]}...")

                # Second, subscribe with the parsed callback
                def on_device_status(status: DeviceStatus):
                    """Parsed status callback."""
                    message_count["status"] += 1
                    print(f"\n✅ PARSED Status Update #{message_count['status']}")
                    print(f"   DHW Temperature: {status.dhwTemperature:.1f}°F")
                    print(f"   Operation Mode: {status.operationMode.name}")
                    print(f"   Compressor: {status.compUse}")

                # Subscribe with raw handler first
                print("Subscribing to raw messages...")
                await mqtt_client.subscribe_device(device, raw_message_handler)
                print("✅ Subscribed to raw messages")

                # Also subscribe with parsed handler
                print("Subscribing to parsed status...")
                await mqtt_client.subscribe_device_status(device, on_device_status)
                print("✅ Subscribed to parsed status")
                print()

                # Step 5: Request device status
                print("Step 5: Requesting device status...")
                await mqtt_client.signal_app_connection(device)
                await asyncio.sleep(1)

                await mqtt_client.request_device_status(device)
                print("✅ Status request sent")
                print()

                # Wait for status updates
                print("⏳ Waiting for messages (20 seconds)...")
                print("   Press Ctrl+C to stop earlier")
                try:
                    await asyncio.sleep(20)
                except KeyboardInterrupt:
                    print("\n⚠️  Interrupted by user")

                print()
                print("📊 Summary:")
                print(f"   Raw messages received: {message_count['raw']}")
                print(f"   Parsed status updates: {message_count['status']}")
                print()

                # Disconnect
                print("Step 6: Disconnecting from AWS IoT...")
                await mqtt_client.disconnect()
                print("✅ Disconnected successfully")

            except Exception:
                import logging

                logging.exception("MQTT error in device_status_callback_debug")

                if mqtt_client.is_connected:
                    await mqtt_client.disconnect()

                return 1

        print()
        print("=" * 70)
        print("✅ Debug Example Completed!")
        print("=" * 70)
        return 0

    except AuthenticationError as e:
        print(f"\n❌ Authentication failed: {e.message}")
        if e.code:
            print(f"   Error code: {e.code}")
        return 1

    except Exception:
        import logging

        logging.exception("Unexpected error in device_status_callback_debug")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
