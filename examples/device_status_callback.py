#!/usr/bin/env python3
"""
Example: Device Status Callback with DeviceStatus Dataclass

This example demonstrates:
1. Using the subscribe_device_status() method for automatic parsing
2. Receiving DeviceStatus objects directly in the callback
3. Accessing typed device status fields

Requirements:
- Set environment variables: NAVIEN_EMAIL and NAVIEN_PASSWORD
- Have at least one device registered in your account
"""

import asyncio
import logging
import os
import sys

# Setup logging
# Set nwp500 logger to DEBUG to see all message flow
logging.basicConfig(
    level=logging.WARNING,  # Suppress most third-party logs
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Enable DEBUG logging for MQTT client to see all message processing
logging.getLogger("nwp500.mqtt_client").setLevel(logging.DEBUG)
# Enable INFO logging for auth and api_client
logging.getLogger("nwp500.auth").setLevel(logging.INFO)
logging.getLogger("nwp500.api_client").setLevel(logging.INFO)

# If running from examples directory, add parent to path
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500.api_client import NavienAPIClient
from nwp500.auth import AuthenticationError, NavienAuthClient
from nwp500.models import DeviceStatus
from nwp500.mqtt_client import NavienMqttClient

try:
    from examples.mask import mask_mac, mask_mac_in_topic  # type: ignore
except Exception:

    def mask_mac(mac):  # pragma: no cover - fallback
        return "[REDACTED_MAC]"

    def mask_mac_in_topic(topic, mac):  # pragma: no cover - fallback
        return topic


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
    print("Device Status Callback Example - Parsed DeviceStatus Objects")
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

            print(f"✅ Using device: {device.device_info.device_name}")
            print(f"   MAC Address: {mask_mac(device_id)}")
            print()

            # Step 3: Create MQTT client and connect
            print("Step 3: Connecting to AWS IoT via MQTT...")
            mqtt_client = NavienMqttClient(auth_client)

            try:
                await mqtt_client.connect()
                print("✅ Connected to AWS IoT Core")
                print()

                # Step 4: Subscribe to device status with automatic parsing
                print("Step 4: Subscribing to device status updates...")

                status_count = {"count": 0}
                message_count = {"count": 0}

                # First subscribe to ALL messages to see what's arriving
                def on_any_message(topic: str, message: dict):
                    """Debug handler to see all messages."""
                    message_count["count"] += 1
                    print(
                        f"\n📩 Raw Message #{message_count['count']} on topic: {topic}"
                    )
                    print(f"   Keys: {list(message.keys())}")
                    if "response" in message:
                        print(f"   Response keys: {list(message['response'].keys())}")

                def on_device_status(status: DeviceStatus):
                    """
                    Callback that receives parsed DeviceStatus objects.

                    This callback is automatically invoked whenever a status
                    message is received and successfully parsed into a
                    DeviceStatus object.
                    """
                    status_count["count"] += 1
                    print(f"\n📊 Device Status Update #{status_count['count']}")
                    print("=" * 60)

                    # Access typed status fields directly
                    print("Temperatures:")
                    print(f"  DHW Temperature:        {status.dhwTemperature:.1f}°F")
                    print(
                        f"  DHW Target Setting:     {status.dhwTargetTemperatureSetting:.1f}°F"
                    )
                    print(
                        f"  Tank Upper:             {status.tankUpperTemperature:.1f}°F"
                    )
                    print(
                        f"  Tank Lower:             {status.tankLowerTemperature:.1f}°F"
                    )
                    print(
                        f"  Discharge:              {status.dischargeTemperature:.1f}°F"
                    )
                    print(
                        f"  Ambient:                {status.ambientTemperature:.1f}°F"
                    )

                    print("\nOperation:")
                    print(f"  Mode:                   {status.operationMode.name}")
                    print(f"  Operation Busy:         {status.operationBusy}")
                    print(f"  DHW Active:             {status.dhwUse}")
                    print(f"  Compressor Active:      {status.compUse}")
                    print(f"  Evaporator Fan Active:  {status.evaFanUse}")
                    print(f"  Current Power:          {status.currentInstPower:.1f}W")

                    print("\nSystem Status:")
                    print(f"  Error Code:             {status.errorCode}")
                    print(f"  WiFi RSSI:              {status.wifiRssi} dBm")
                    print(f"  DHW Charge:             {status.dhwChargePer:.1f}%")
                    print(f"  Eco Mode:               {status.ecoUse}")
                    print(f"  Freeze Protection:      {status.freezeProtectionUse}")

                    print("\nAdvanced:")
                    print(
                        f"  Fan RPM:                {status.currentFanRpm}/{status.targetFanRpm}"
                    )
                    print(f"  EEV Step:               {status.eevStep}")
                    print(f"  Super Heat:             {status.currentSuperHeat:.1f}°F")
                    print(
                        f"  Flow Rate:              {status.currentDhwFlowRate:.1f} GPM"
                    )
                    print(f"  Temperature Unit:       {status.temperatureType.name}")

                    print("=" * 60)

                # Subscribe to raw messages first - use multiple topics like working example
                device_topic = f"navilink-{device_id}"

                # Subscribe to multiple topics to catch all messages
                await mqtt_client.subscribe(
                    f"cmd/{device_type}/{device_topic}/#", on_any_message
                )
                await mqtt_client.subscribe(
                    f"evt/{device_type}/{device_topic}/#", on_any_message
                )

                # Then subscribe with automatic parsing
                await mqtt_client.subscribe_device_status(device, on_device_status)
                print("✅ Subscribed to device messages and status parsing")
                print()

                # Step 5: Request device status
                print("Step 5: Requesting device status...")
                await mqtt_client.signal_app_connection(device)
                await asyncio.sleep(1)

                await mqtt_client.request_device_status(device)
                print("✅ Status request sent")
                print()

                # Wait for status updates
                print("⏳ Waiting for device status updates (20 seconds)...")
                print("   Press Ctrl+C to stop earlier")
                try:
                    await asyncio.sleep(20)
                except KeyboardInterrupt:
                    print("\n⚠️  Interrupted by user")

                print()
                print("📊 Summary:")
                print(f"   Raw messages received: {message_count['count']}")
                print(f"   Parsed status updates: {status_count['count']}")
                print()

                # Disconnect
                print("Step 6: Disconnecting from AWS IoT...")
                await mqtt_client.disconnect()
                print("✅ Disconnected successfully")

            except Exception:
                import logging

                logging.exception("MQTT error in device_status_callback")

                if mqtt_client.is_connected:
                    await mqtt_client.disconnect()

                return 1

        print()
        print("=" * 70)
        print("✅ Device Status Callback Example Completed Successfully!")
        print("=" * 70)
        return 0

    except AuthenticationError as e:
        print(f"\n❌ Authentication failed: {e.message}")
        if e.code:
            print(f"   Error code: {e.code}")
        return 1

    except Exception:
        import logging

        logging.exception("Unexpected error in device_status_callback")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
