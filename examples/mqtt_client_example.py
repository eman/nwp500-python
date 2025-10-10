#!/usr/bin/env python3
"""
Example: MQTT Client Connection and Communication

This example demonstrates:
1. Authenticating with the Navien API to get AWS credentials
2. Establishing an MQTT connection using AWS IoT WebSocket
3. Subscribing to device messages
4. Sending commands to devices
5. Real-time monitoring of device status

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
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# If running from examples directory, add parent to path
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500.api_client import NavienAPIClient
from nwp500.auth import AuthenticationError, NavienAuthClient
from nwp500.models import DeviceFeature, DeviceStatus
from nwp500.mqtt_client import NavienMqttClient

try:
    from examples.mask import mask_mac  # type: ignore
except Exception:

    def mask_mac(mac):  # pragma: no cover - fallback for examples
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
        print("\nExample:")
        print("  export NAVIEN_EMAIL='your_email@example.com'")
        print("  export NAVIEN_PASSWORD='your_password'")
        return 1

    print("=" * 70)
    print("Navien MQTT Client Example - Real-time Device Communication")
    print("=" * 70)
    print()

    try:
        # Step 1: Authenticate and get AWS credentials
        print("Step 1: Authenticating with Navien API...")
        async with NavienAuthClient(email, password) as auth_client:
            print(f"✅ Authenticated as: {auth_client.current_user.full_name}")

            # Check if we have AWS credentials for MQTT
            if not auth_client.current_tokens.access_key_id:
                print("❌ Error: No AWS credentials in authentication response")
                print("   MQTT communication requires AWS IoT credentials")
                return 1

            print("✅ AWS IoT credentials obtained")
            print(
                f"   Access Key ID: {auth_client.current_tokens.access_key_id[:15]}..."
            )
            print()

            # Step 2: Get device list
            print("Step 2: Fetching device list...")

            # Create a new API client that shares the auth client and session
            api_client = NavienAPIClient(
                auth_client=auth_client, session=auth_client._session
            )
            # Set the user email so API client knows we're authenticated

            devices = await api_client.list_devices()
            devices = await api_client.list_devices()

            if not devices:
                print("❌ Error: No devices found in your account")
                print("   Please register a device first")
                return 1

            print(f"✅ Found {len(devices)} device(s):")
            for i, device in enumerate(devices):
                print(f"   {i + 1}. {device.device_info.device_name} (MAC: **MASKED**)")
                print(
                    f"      Type: {device.device_info.device_type}, Connected: {device.device_info.connected}"
                )
            print()

            # Use the first device for this example
            device = devices[0]
            device_id = device.device_info.mac_address
            device_type = device.device_info.device_type

            try:
                from examples.mask import mask_any  # type: ignore
            except Exception:

                def mask_any(_):  # pragma: no cover - fallback
                    return "[REDACTED]"

            print(f"✅ Using device: {device.device_info.device_name}")
            print(f"   MAC Address: {mask_mac(device_id)}")
            print(f"   Device Type: {mask_any(device_type)}")
            print()

            # Step 3: Create MQTT client and connect
            print("Step 3: Connecting to AWS IoT via MQTT WebSocket...")
            mqtt_client = NavienMqttClient(auth_client)

            try:
                await mqtt_client.connect()
                print("✅ Connected to AWS IoT Core")
                print(f"   Client ID: {mqtt_client.client_id}")
                print(f"   Session ID: {mqtt_client.session_id}")
                print()

                # Step 4: Subscribe to device messages with typed parsing
                print("Step 4: Subscribing to device messages...")

                message_count = {"count": 0, "status": 0, "feature": 0}

                def on_device_status(status: DeviceStatus):
                    """Typed callback for device status."""
                    message_count["count"] += 1
                    message_count["status"] += 1
                    print(
                        f"\n📊 Status Update #{message_count['status']} (Message #{message_count['count']})"
                    )
                    print(f"   - DHW Temperature: {status.dhwTemperature:.1f}°F")
                    print(f"   - Tank Upper: {status.tankUpperTemperature:.1f}°F")
                    print(f"   - Tank Lower: {status.tankLowerTemperature:.1f}°F")
                    print(f"   - Operation Mode: {status.operationMode}")
                    print(f"   - DHW Active: {status.dhwUse}")
                    print(f"   - Compressor: {status.compUse}")

                def on_device_feature(feature: DeviceFeature):
                    """Typed callback for device features."""
                    message_count["count"] += 1
                    message_count["feature"] += 1
                    print(
                        f"\n📋 Device Info #{message_count['feature']} (Message #{message_count['count']})"
                    )
                    print(f"   - Serial: {feature.controllerSerialNumber}")
                    print(f"   - SW Version: {feature.controllerSwVersion}")
                    print(f"   - Heat Pump: {feature.heatpumpUse}")

                # Subscribe with typed parsing wrappers

                # Subscribe with typed parsing
                await mqtt_client.subscribe_device_status(device, on_device_status)
                await mqtt_client.subscribe_device_feature(device, on_device_feature)
                print("✅ Subscribed to device messages with typed parsing")
                print()

                # Step 5: Send commands and monitor responses
                print("Step 5: Sending commands to device...")
                print()

                # Signal app connection
                print("📤 Signaling app connection...")
                await mqtt_client.signal_app_connection(device)
                await asyncio.sleep(1)

                # Request device info
                print("📤 Requesting device information...")
                await mqtt_client.request_device_info(device)
                await asyncio.sleep(2)

                # Request device status
                print("📤 Requesting device status...")
                await mqtt_client.request_device_status(device)
                await asyncio.sleep(2)

                # Wait for messages
                print()
                print("⏳ Waiting for device responses (15 seconds)...")
                print("   Press Ctrl+C to stop earlier")
                try:
                    await asyncio.sleep(15)
                except KeyboardInterrupt:
                    print("\n⚠️  Interrupted by user")

                print()
                print(f"📊 Summary: Received {message_count['count']} message(s)")
                print()

                # Step 6: Disconnect
                print("Step 6: Disconnecting from AWS IoT...")
                await mqtt_client.disconnect()
                print("✅ Disconnected successfully")

            except Exception:
                import logging

                logging.exception("MQTT error in mqtt_client_example")

                if mqtt_client.is_connected:
                    await mqtt_client.disconnect()

                return 1

        print()
        print("=" * 70)
        print("✅ MQTT Client Example Completed Successfully!")
        print("=" * 70)
        return 0

    except AuthenticationError as e:
        print(f"\n❌ Authentication failed: {e.message}")
        if e.code:
            print(f"   Error code: {e.code}")
        return 1

    except Exception:
        import logging

        logging.exception("Unexpected error in mqtt_client_example")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
