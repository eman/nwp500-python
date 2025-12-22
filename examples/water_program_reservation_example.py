#!/usr/bin/env python3
"""
Example: Water program reservation configuration via MQTT.

This demonstrates how to enable/configure the water program reservation
system for scheduling water heating.
"""

import asyncio
import logging
from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

# Set up logging to see the water program configuration process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def water_program_example():
    """Example of configuring water program reservation mode."""

    # Use environment variables or replace with your credentials
    email = "your_email@example.com"
    password = "your_password"

    async with NavienAuthClient(email, password) as auth_client:
        # Get device information
        api_client = NavienAPIClient(auth_client)
        devices = await api_client.list_devices()

        if not devices:
            logger.error("No devices found")
            return

        device = devices[0]
        logger.info(f"Found device: {device.device_info.device_name}")

        # Connect MQTT client
        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()
        logger.info("MQTT client connected")

        try:
            # Get current status first
            logger.info("Getting current device status...")
            current_status = None

            def on_current_status(status):
                nonlocal current_status
                current_status = status
                logger.info(f"Current operation mode: {status.operation_mode.name}")
                logger.info(
                    f"Current DHW temperature setting: {status.dhw_target_temperature_setting}°F"
                )

            await mqtt_client.subscribe_device_status(device, on_current_status)
            await mqtt_client.control.request_device_status(device)
            await asyncio.sleep(3)  # Wait for current status

            # Enable water program reservation mode
            logger.info("Configuring water program reservation mode...")

            water_program_enabled = False

            def on_water_program_configured(status):
                nonlocal water_program_enabled
                logger.info("Water program reservation mode enabled!")
                logger.info(
                    "You can now set up water heating schedules for "
                    "specific times and days"
                )
                logger.info(f"Operation mode: {status.operation_mode.name}")
                water_program_enabled = True

            await mqtt_client.subscribe_device_status(
                device, on_water_program_configured
            )
            await mqtt_client.control.configure_reservation_water_program(device)

            # Wait for confirmation
            for i in range(10):  # Wait up to 10 seconds
                if water_program_enabled:
                    logger.info(
                        "Water program reservation mode configured successfully!"
                    )
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for configuration confirmation")

            logger.info(
                "Water program reservation mode is now active. "
                "You can use the app or API to set up specific heating schedules."
            )

        finally:
            await mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")


if __name__ == "__main__":
    print("=== Water Program Reservation Configuration Example ===")
    print("This example demonstrates:")
    print("1. Connecting to device via MQTT")
    print("2. Getting current device status")
    print("3. Enabling water program reservation mode")
    print("4. Receiving and displaying the response")
    print()

    # Note: This requires valid credentials
    print(
        "Note: Update email/password or set NAVIEN_EMAIL/NAVIEN_PASSWORD environment variables"
    )
    print()

    # Uncomment to run (requires valid credentials)
    # asyncio.run(water_program_example())

    print("CLI equivalent commands:")
    print("  python -m nwp500.cli water-program")
    print()
    print("Once enabled, you can set up specific heating schedules through:")
    print("- The official Navien mobile app")
    print("- The REST API reservations endpoints")
    print("- This library's set_reservations method")
