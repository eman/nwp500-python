#!/usr/bin/env python3
"""
Enhanced MQTT messaging test to verify device responses.

This test verifies:
1. Connection to AWS IoT
2. Subscription to device topics
3. Message publishing
4. Receipt of device responses
"""

import asyncio
import json
import logging
import os
import sys
import re
from datetime import datetime

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

from nwp500.api_client import NavienAPIClient
from nwp500.auth import NavienAuthClient
from nwp500.mqtt_client import NavienMqttClient


async def test_mqtt_messaging():
    """Test complete MQTT messaging with device."""

    # Get credentials
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("❌ Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return False

    print("=" * 80)
    print("Enhanced MQTT Messaging Test - Verifying Device Communication")
    print("=" * 80)
    print()

    messages_received = []

    def message_handler(topic: str, message: dict):
        """Handle all incoming messages with detailed logging."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        messages_received.append(
            {"timestamp": timestamp, "topic": topic, "message": message}
        )

        print(f"\n{'=' * 80}")
        print(f"📩 MESSAGE RECEIVED at {timestamp}")
        print(f"{'=' * 80}")
        print(f"Topic: {topic}")
        print("\nFull Message:")
        print(json.dumps(message, indent=2))
        print(f"{'=' * 80}\n")

    try:
        # Step 1: Authenticate
        print("Step 1: Authenticating...")
        async with NavienAuthClient(email, password) as auth_client:
            print(f"✅ Authenticated as: {auth_client.current_user.full_name}")

            if not auth_client.current_tokens.access_key_id:
                print("❌ No AWS credentials available")
                return False

            print("✅ AWS credentials obtained")
            print()

            # Step 2: Get device info
            print("Step 2: Getting device list...")
            api_client = NavienAPIClient(
                auth_client=auth_client, session=auth_client._session
            )
            devices = await api_client.list_devices()

            if not devices:
                print("❌ No devices found")
                return False

            device = devices[0]
            device_id = device.device_info.mac_address
            device_type = device.device_info.device_type
            additional_value = device.device_info.additional_value

            try:
                from examples.mask import mask_any, mask_location  # type: ignore
            except Exception:

                def mask_any(_):
                    return "[REDACTED]"

                def mask_location(_, __):
                    return "[REDACTED_LOCATION]"

            # Helper to mask MAC-like strings for safe printing
            def mask_mac(addr: str) -> str:
                # Always redact to avoid leaking sensitive data
                return "[REDACTED_MAC]"

            print(f"✅ Found device: {device.device_info.device_name}")
            print(f"   MAC Address: {mask_mac(device_id)}")
            print(f"   Device Type: {mask_any(device_type)}")
            print(f"   Additional Value: {additional_value}")
            print(f"   Connection Status: {device.device_info.connected}")
            print()

            # Step 3: Connect MQTT
            print("Step 3: Connecting to AWS IoT...")
            mqtt_client = NavienMqttClient(auth_client)
            await mqtt_client.connect()

            print("✅ Connected to AWS IoT")
            print(f"   Client ID: {mqtt_client.client_id}")
            print(f"   Session ID: {mqtt_client.session_id}")
            print()

            # Step 4: Subscribe to ALL possible response topics
            print("Step 4: Subscribing to device topics...")

            # Subscribe to multiple topic patterns to catch all responses
            device_topic = f"navilink-{device_id}"
            topics = [
                f"cmd/{device_type}/{device_topic}/{mqtt_client.client_id}/res/#",
                f"cmd/{device_type}/{device_topic}/res/#",
                f"cmd/{device_type}/{device_topic}/#",
                f"evt/{device_type}/{device_topic}/#",
            ]

            def mask_mac_in_topic(topic: str, mac_addr: str) -> str:
                # Always redact listed MAC address if present anywhere in topic string
                # Mask recognized MAC patterns AND any direct insertion of the device MAC (regardless of format).
                mac_regex = r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|(?:[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})|(?:[0-9A-Fa-f]{12})"
                topic_masked = re.sub(mac_regex, "[REDACTED_MAC]", topic)
                # Ensure even if regex fails (e.g., odd format), definitely mask raw MAC address string if present.
                if mac_addr and mac_addr in topic_masked:
                    topic_masked = topic_masked.replace(mac_addr, "[REDACTED_MAC]")
                return topic_masked

            for topic in topics:
                try:
                    await mqtt_client.subscribe(topic, message_handler)
                    print(f"   ✅ Subscribed to: {mask_mac_in_topic(topic, device_id)}")
                except Exception:
                    # Avoid printing exception contents which may contain sensitive identifiers
                    try:
                        # mask_any should be available from earlier import
                        from examples.mask import mask_any  # type: ignore
                    except Exception:

                        def mask_any(_):
                            return "[REDACTED]"

                    print(
                        f"   ⚠️ Failed to subscribe to topic. Device type: {mask_any(device_type)}"
                    )
                    logging.debug(
                        "Subscribe failure for device_type=%s; topic name redacted for privacy",
                        device_type,
                        exc_info=True,
                    )

            print()

            # Step 5: Send commands with delays
            print("Step 5: Sending commands to device...")
            print()

            # Command 1: Signal app connection
            print(
                f"📤 [{datetime.now().strftime('%H:%M:%S')}] Signaling app connection..."
            )
            try:
                await mqtt_client.signal_app_connection(device)
                print("   ✅ Sent")
            except Exception as e:
                print(f"   ❌ Error: {e}")
            await asyncio.sleep(3)

            # Command 2: Request device info
            print(
                f"📤 [{datetime.now().strftime('%H:%M:%S')}] Requesting device info..."
            )
            try:
                await mqtt_client.request_device_info(device)
                print("   ✅ Sent")
            except Exception as e:
                print(f"   ❌ Error: {e}")
            await asyncio.sleep(5)

            # Command 3: Request device status
            print(
                f"📤 [{datetime.now().strftime('%H:%M:%S')}] Requesting device status..."
            )
            try:
                await mqtt_client.request_device_status(device)
                print("   ✅ Sent")
            except Exception as e:
                print(f"   ❌ Error: {e}")
            await asyncio.sleep(5)

            # Step 6: Wait for responses with status updates
            print()
            print("Step 6: Waiting for device responses...")
            print("=" * 80)
            print("Monitoring for 30 seconds...")
            print("(Messages will be displayed above as they arrive)")
            print("=" * 80)

            for i in range(6):
                await asyncio.sleep(5)
                print(
                    f"[{(i + 1) * 5}s] Still listening... ({len(messages_received)} messages received)"
                )

            # Step 7: Summary
            print()
            print("=" * 80)
            print("TEST RESULTS")
            print("=" * 80)
            print(f"Total messages received: {len(messages_received)}")
            print()

            if messages_received:
                print("✅ SUCCESS: Device responded to commands!")
                print()
                print("Messages received:")
                for i, msg_data in enumerate(messages_received, 1):
                    print(f"\n{i}. At {msg_data['timestamp']}")
                    print(f"   Topic: {msg_data['topic']}")

                    # Show key data from message
                    msg = msg_data["message"]
                    if "response" in msg:
                        response = msg["response"]
                        if "status" in response:
                            status = response["status"]
                            print("   Type: Status Update")
                            print(
                                f"   - DHW Temp: {status.get('dhwTemperature', 'N/A')}"
                            )
                            print(
                                f"   - Operation Mode: {status.get('operationMode', 'N/A')}"
                            )
                        elif "channelStatus" in response:
                            print("   Type: Channel Status")
                        else:
                            print("   Type: Other Response")
                            print(f"   Keys: {list(response.keys())}")
            else:
                print("❌ FAILURE: No messages received from device")
                print()
                print("Possible causes:")
                print("1. Device is offline or not connected to network")
                print("2. Device MAC address is incorrect")
                print("3. Topic subscription pattern is wrong")
                print("4. AWS IoT permissions issue")
                print()
                print(
                    "Device connection status from API:",
                    device.device_info.connected,
                )
                print("Expected connection status: 2 (online)")

            print()
            print("=" * 80)

            # Step 8: Disconnect
            await mqtt_client.disconnect()
            print("✅ Disconnected from AWS IoT")

            return len(messages_received) > 0

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_mqtt_messaging())
    sys.exit(0 if success else 1)
