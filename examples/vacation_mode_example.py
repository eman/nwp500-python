#!/usr/bin/env python3
"""
Example: Vacation mode configuration via MQTT.

This demonstrates how to set vacation/away mode duration for energy-saving
during periods of absence.
"""

import asyncio
import logging
from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

# Set up logging to see the vacation mode control process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def vacation_mode_example():
    """Example of configuring vacation mode."""

    # Use environment variables or replace with your credentials
    email = "your_email@example.com"
    password = "your_password"

    # Vacation duration in days
    vacation_days = 14

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

            # Set vacation mode
            logger.info(f"Setting vacation mode for {vacation_days} days...")

            vacation_set = False

            def on_vacation_set(status):
                nonlocal vacation_set
                logger.info(f"Vacation mode set for {vacation_days} days!")
                logger.info("Device is now in energy-saving mode during absence")
                logger.info(f"Operation mode: {status.operation_mode.name}")
                vacation_set = True

            await mqtt_client.subscribe_device_status(device, on_vacation_set)
            await mqtt_client.control.set_vacation_days(device, vacation_days)

            # Wait for confirmation
            for i in range(10):  # Wait up to 10 seconds
                if vacation_set:
                    logger.info("Vacation mode set successfully!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for vacation mode confirmation")

            logger.info(
                f"Vacation mode active: Device will operate in energy-saving mode "
                f"until {vacation_days} days have elapsed."
            )
            logger.info(
                "The device will automatically return to normal operation "
                "after the vacation period ends."
            )

        finally:
            await mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")


if __name__ == "__main__":
    print("=== Vacation Mode Example ===")
    print("This example demonstrates:")
    print("1. Connecting to device via MQTT")
    print("2. Getting current device status")
    print("3. Setting vacation mode for a specified number of days")
    print("4. Receiving and displaying the response")
    print()

    # Note: This requires valid credentials
    print(
        "Note: Update email/password or set NAVIEN_EMAIL/NAVIEN_PASSWORD environment variables"
    )
    print()

    # Uncomment to run (requires valid credentials)
    # asyncio.run(vacation_mode_example())

    print("CLI equivalent commands:")
    print("  python -m nwp500.cli vacation 7")
    print("  python -m nwp500.cli vacation 14")
    print("  python -m nwp500.cli vacation 21")
    print()
    print("Valid range: 1-365+ days")
