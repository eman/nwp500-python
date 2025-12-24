#!/usr/bin/env python3
"""
Example: Complete Authentication and Client Setup Pattern

This example demonstrates the recommended pattern for:
1. Creating an authenticated auth client
2. Sharing the session with API and MQTT clients
3. Properly managing the session lifecycle
"""

import asyncio
import os

from nwp500 import (
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
)


async def example_basic_pattern():
    """Demonstrate the basic authentication pattern."""
    print("=" * 60)
    print("Basic Authentication Pattern")
    print("=" * 60)

    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return

    # Step 1: Create and enter the auth context
    # Authentication happens automatically here
    async with NavienAuthClient(email, password) as auth_client:
        print(f"✓ Authenticated as: {auth_client.user_email}")
        print("✓ Session active (will close after this block)")

        # Step 2: Create API client sharing the same session
        api_client = NavienAPIClient(auth_client=auth_client)
        print("✓ API client created (using shared session)")

        # Step 3: Use the API client
        devices = await api_client.list_devices()
        print(f"✓ Found {len(devices)} device(s)")

        if devices:
            device = devices[0]
            print(f"  Device: {device.device_info.device_name}")
            print(f"  Temperature: {device.status.dhw_temperature}°F")

    print("✓ Context exited, session closed")


async def example_with_mqtt():
    """Demonstrate sharing session between API and MQTT clients."""
    print("\n" + "=" * 60)
    print("Multi-Client Pattern (API + MQTT)")
    print("=" * 60)

    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Skipping - credentials not set")
        return

    async with NavienAuthClient(email, password) as auth_client:
        print(f"✓ Authenticated: {auth_client.user_email}")

        # Both clients share the same session
        api_client = NavienAPIClient(auth_client=auth_client)
        mqtt_client = NavienMqttClient(auth_client=auth_client)
        print("✓ Created API and MQTT clients (shared session)")

        # Get device
        devices = await api_client.list_devices()
        if not devices:
            print("No devices found")
            return

        device = devices[0]
        print(f"✓ Device: {device.device_info.device_name}")

        # Connect MQTT for real-time updates
        try:
            await mqtt_client.connect()
            print("✓ MQTT Connected")

            # Subscribe to status updates
            def on_status(status):
                print(
                    f"  📊 Status: Temp={status.dhw_temperature}°F, "
                    f"Mode={status.operation_mode}, "
                    f"Power={status.current_inst_power}W"
                )

            await mqtt_client.subscribe_device_status(device, on_status)

            # Request initial status
            await mqtt_client.control.request_device_status(device)

            # Wait for a moment to receive updates
            await asyncio.sleep(3)

            await mqtt_client.disconnect()
            print("✓ MQTT Disconnected")

        except Exception as e:
            print(f"✗ MQTT error: {e}")

    print("✓ Context exited, session closed")


async def example_explicit_initialization():
    """
    Demonstrate explicit initialization steps.

    This shows exactly what happens at each step for clarity.
    """
    print("\n" + "=" * 60)
    print("Explicit Initialization Steps")
    print("=" * 60)

    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Skipping - credentials not set")
        return

    # Step 1: Create auth client (doesn't authenticate yet)
    print("Step 1: Create auth client (no session yet)")
    auth_client = NavienAuthClient(email, password)
    print("  ✓ Auth client created")
    print(f"    - Email: {auth_client._user_email or 'not set'}")
    print(f"    - Session exists: {auth_client._session is not None}")

    # Step 2: Enter context manager (creates session and authenticates)
    print("\nStep 2: Enter context manager (creates session, authenticates)")
    await auth_client.__aenter__()
    print("  ✓ Session created")
    print(f"    - Email: {auth_client.user_email}")
    print(f"    - Session exists: {auth_client._session is not None}")
    print(f"    - Tokens available: {auth_client.current_tokens is not None}")

    # Step 3: Create other clients
    print("\nStep 3: Create API and MQTT clients (share session)")
    api_client = NavienAPIClient(auth_client=auth_client)
    _mqtt_client = NavienMqttClient(auth_client=auth_client)
    print("  ✓ Clients created")

    # Step 4: Use clients
    print("\nStep 4: Use clients (session is active)")
    devices = await api_client.list_devices()
    print(f"  ✓ API call succeeded: {len(devices)} device(s) found")

    # Step 5: Exit context manager (closes session)
    print("\nStep 5: Exit context manager (closes session)")
    await auth_client.__aexit__(None, None, None)
    print("  ✓ Session closed")
    print(f"    - Session exists: {auth_client._session is not None}")

    print("\nNote: Clients can no longer be used after context exits")


async def main():
    """Run all examples."""
    try:
        await example_basic_pattern()
        await example_with_mqtt()
        await example_explicit_initialization()
    except KeyboardInterrupt:
        print("\n⚠ Interrupted by user")


if __name__ == "__main__":
    asyncio.run(main())
