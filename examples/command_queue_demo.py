#!/usr/bin/env python3
"""
Command Queue Demonstration.

This script demonstrates the command queue feature that automatically
queues commands when disconnected and sends them when reconnected.

Features demonstrated:
1. Commands queued while disconnected
2. Automatic sending when reconnected
3. Queue status monitoring
4. Configuration options

Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables before running.
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

from nwp500.auth import NavienAuthClient
from nwp500.mqtt_client import MqttConnectionConfig, NavienMqttClient


async def command_queue_demo():
    """Demonstrate command queue functionality."""

    # Get credentials
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("❌ Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return False

    print("Command Queue Demonstration")
    print("=" * 60)

    try:
        # Step 1: Authenticate
        print("\n1. Authenticating with Navien API...")
        async with NavienAuthClient(email, password) as auth_client:
            print(f"   ✅ Authenticated as: {auth_client.current_user.full_name}")

            # Get devices
            from nwp500.api_client import NavienAPIClient

            api_client = NavienAPIClient(auth_client=auth_client)
            devices = await api_client.list_devices()

            if not devices:
                print("   ❌ No devices found")
                return False

            device = devices[0]
            print(f"   ✅ Found device: {device.device_info.device_name}")

            # Step 2: Create MQTT client with command queue enabled
            print("\n2. Creating MQTT client with command queue...")
            config = MqttConnectionConfig(
                enable_command_queue=True,
                max_queued_commands=50,
                auto_reconnect=True,
            )

            def on_interrupted(error):
                print(f"   ⚠️  Connection interrupted: {error}")
                print(f"   📝 Queued commands: {mqtt_client.queued_commands_count}")

            def on_resumed(return_code, session_present):
                print("   ✅ Connection resumed!")
                print(f"   📝 Queued commands: {mqtt_client.queued_commands_count}")

            mqtt_client = NavienMqttClient(
                auth_client,
                config=config,
                on_connection_interrupted=on_interrupted,
                on_connection_resumed=on_resumed,
            )

            # Step 3: Connect
            print("\n3. Connecting to AWS IoT...")
            await mqtt_client.connect()
            print(f"   ✅ Connected! Client ID: {mqtt_client.client_id}")

            # Step 4: Subscribe to device
            print("\n4. Subscribing to device messages...")

            received_messages = []

            def on_message(topic, message):
                print(f"   📨 Received message on {topic}")
                received_messages.append(message)

            await mqtt_client.subscribe_device(device, on_message)
            print("   ✅ Subscribed to device")

            # Step 5: Test normal operation
            print("\n5. Testing normal operation (connected)...")
            print("   Sending status request...")
            await mqtt_client.request_device_status(device)
            print("   ✅ Command sent successfully")
            await asyncio.sleep(2)

            # Step 6: Simulate disconnection and queue commands
            print("\n6. Simulating disconnection...")
            print(
                "   Note: In real scenarios, this happens automatically during network issues"
            )

            # Manually disconnect
            await mqtt_client.disconnect()
            print("   ✅ Disconnected")

            # Try sending commands while disconnected - they should be queued
            print("\n7. Sending commands while disconnected (will be queued)...")
            print(f"   Queue size before: {mqtt_client.queued_commands_count}")

            # These will be queued
            print("   Queuing status request...")
            await mqtt_client.request_device_status(device)
            print(f"   Queue size: {mqtt_client.queued_commands_count}")

            print("   Queuing device info request...")
            await mqtt_client.request_device_info(device)
            print(f"   Queue size: {mqtt_client.queued_commands_count}")

            print("   Queuing temperature change...")
            await mqtt_client.set_dhw_temperature_display(device, 130)
            print(f"   Queue size: {mqtt_client.queued_commands_count}")

            print(f"   ✅ Queued {mqtt_client.queued_commands_count} command(s)")

            # Step 8: Reconnect and watch commands get sent
            print("\n8. Reconnecting...")
            await mqtt_client.connect()
            print("   ✅ Reconnected!")

            # Give time for queued commands to be sent
            print("   Waiting for queued commands to be sent...")
            await asyncio.sleep(3)

            print(
                f"   ✅ Queue processed! Remaining: {mqtt_client.queued_commands_count}"
            )

            # Step 9: Test queue limits
            print("\n9. Testing queue limits...")
            await mqtt_client.disconnect()

            # Try to exceed queue limit
            print(f"   Sending {config.max_queued_commands + 5} commands...")
            for _i in range(config.max_queued_commands + 5):
                await mqtt_client.request_device_status(device)

            print(
                f"   Queue size: {mqtt_client.queued_commands_count} (max: {config.max_queued_commands})"
            )
            print("   ✅ Queue properly limited (oldest commands dropped)")

            # Clear queue
            cleared = mqtt_client.clear_command_queue()
            print(f"\n   Cleared {cleared} queued command(s)")
            print(f"   Queue size now: {mqtt_client.queued_commands_count}")

            # Final reconnect
            print("\n10. Final reconnection...")
            await mqtt_client.connect()
            await asyncio.sleep(2)

            # Cleanup
            print("\n11. Disconnecting...")
            await mqtt_client.disconnect()
            print("   ✅ Disconnected cleanly")

        print("\n" + "=" * 60)
        print("✅ Command Queue Demo Complete!")
        print("\nKey Features Demonstrated:")
        print("  • Commands queued when disconnected")
        print("  • Automatic sending on reconnection")
        print("  • Queue size monitoring")
        print("  • Queue limit enforcement")
        print("  • Manual queue clearing")

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(command_queue_demo())
    sys.exit(0 if success else 1)
