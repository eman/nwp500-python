#!/usr/bin/env python3
"""
Example: MQTT Reconnection with Exponential Backoff

This example demonstrates the automatic reconnection feature of the MQTT client.
The client will automatically reconnect with exponential backoff if the connection
is interrupted.

Features demonstrated:
- Automatic reconnection with exponential backoff
- Custom reconnection configuration
- Reconnection status monitoring
- Connection interruption and resumption callbacks
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient
from nwp500.mqtt_client import MqttConnectionConfig


async def main():
    """Demonstrate automatic reconnection with exponential backoff."""
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return

    print("=" * 70)
    print("MQTT Reconnection Demo")
    print("=" * 70)

    # Connection callbacks
    def on_interrupted(error):
        print(f"\n⚠️  Connection interrupted: {error}")
        print("   Automatic reconnection will begin...")

    def on_resumed(return_code, session_present):
        print("\n✅ Connection resumed!")
        print(f"   Return code: {return_code}")
        print(f"   Session present: {session_present}")

    # Authenticate
    async with NavienAuthClient(email, password) as auth_client:
        print(f"✅ Authenticated as: {auth_client.current_user.full_name}")

        # Get device
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()

        if not device:
            print("No devices found")
            return

        print(f"✅ Found device: {device.device_info.device_name}")

        # Configure MQTT with custom reconnection settings
        config = MqttConnectionConfig(
            auto_reconnect=True,  # Enable automatic reconnection (default)
            max_reconnect_attempts=10,  # Max attempts before giving up
            initial_reconnect_delay=1.0,  # Start with 1 second delay
            max_reconnect_delay=60.0,  # Cap at 60 seconds
            reconnect_backoff_multiplier=2.0,  # Double the delay each time
        )

        # Create MQTT client with reconnection callbacks
        mqtt_client = NavienMqttClient(
            auth_client,
            config=config,
            on_connection_interrupted=on_interrupted,
            on_connection_resumed=on_resumed,
        )

        # Connect
        await mqtt_client.connect()
        print(f"✅ MQTT Connected: {mqtt_client.client_id}")

        # Subscribe to device status
        status_count = 0

        def on_status(status):
            nonlocal status_count
            status_count += 1
            print(f"\n📊 Status update #{status_count}:")
            print(f"   Temperature: {status.dhwTemperature}°F")
            print(f"   Connected: {mqtt_client.is_connected}")
            if mqtt_client.is_reconnecting:
                print(f"   Reconnecting: attempt {mqtt_client.reconnect_attempts}...")

        await mqtt_client.subscribe_device_status(device, on_status)
        await mqtt_client.request_device_status(device)

        # Monitor connection status
        print("\n" + "=" * 70)
        print("Monitoring connection (60 seconds)...")
        print("=" * 70)
        print(
            "\nTo test reconnection, disconnect your internet or simulate a network issue."
        )
        print("The client will automatically reconnect with exponential backoff.")
        print("\nReconnection pattern: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)")

        for i in range(60):
            await asyncio.sleep(1)

            # Show connection status every 5 seconds
            if i % 5 == 0:
                status = (
                    "🟢 Connected" if mqtt_client.is_connected else "🔴 Disconnected"
                )
                reconnecting = ""
                if mqtt_client.is_reconnecting:
                    reconnecting = (
                        f" (Reconnecting: attempt {mqtt_client.reconnect_attempts})"
                    )
                print(f"\n[{i:2d}s] {status}{reconnecting}")

                # Request status update if connected
                if mqtt_client.is_connected:
                    await mqtt_client.request_device_status(device)

        print("\n" + "=" * 70)
        print(f"Monitoring complete. Received {status_count} status updates.")
        print("=" * 70)

        # Disconnect
        await mqtt_client.disconnect()
        print("\n✅ Disconnected")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
