"""
Example: Clean Authentication Pattern

This example shows the proper way to use the nwp500 library:
- Create NavienAuthClient with credentials (authenticates automatically)
- Use the auth_client with NavienAPIClient to get devices
- Use the same auth_client with NavienMqttClient for real-time updates
"""

import asyncio
import os

from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient


async def main():
    """Demonstrate clean authentication pattern."""
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return

    # Authenticate once and use the auth_client everywhere
    async with NavienAuthClient(email, password) as auth_client:
        # Already authenticated!
        print(f"[SUCCESS] Authenticated as: {auth_client.user_email}")

        # Step 2: Create API client and get device
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()

        if not device:
            print("No devices found")
            return

        print(f"[SUCCESS] Found device: {device.device_info.device_name}")

        # Step 3: Create MQTT client using the same auth_client
        mqtt = NavienMqttClient(auth_client)
        await mqtt.connect()
        print(f"[SUCCESS] MQTT Connected: {mqtt.client_id}")

        # Step 4: Monitor device status
        def on_status(status):
            print("\n📊 Device Status:")
            print(f"   Temperature: {status.dhw_temperature}°F")
            print(f"   Target: {status.dhw_temperature_setting}°F")
            print(f"   Power: {status.current_inst_power}W")

        await mqtt.subscribe_device_status(device, on_status)
        await mqtt.request_device_status(device)

        # Keep alive for a few seconds to receive status
        print("\nMonitoring for 10 seconds...")
        await asyncio.sleep(10)

        await mqtt.disconnect()
        print("\n[SUCCESS] Disconnected")


if __name__ == "__main__":
    asyncio.run(main())
