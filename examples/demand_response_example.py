#!/usr/bin/env python3
"""
Example: Controlling utility demand response via MQTT.

This demonstrates how to enable/disable demand response participation
to help utilities manage peak loads.
"""

import asyncio
import logging
from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

# Set up logging to see the demand response control process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def demand_response_example():
    """Example of controlling demand response participation."""

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

            # Enable demand response
            logger.info("Enabling demand response...")

            dr_enabled = False

            def on_dr_enabled(status):
                nonlocal dr_enabled
                logger.info("Demand response enabled!")
                logger.info("Device is now ready to respond to utility signals")
                dr_enabled = True

            await mqtt_client.subscribe_device_status(device, on_dr_enabled)
            await mqtt_client.control.enable_demand_response(device)

            # Wait for confirmation
            for i in range(10):  # Wait up to 10 seconds
                if dr_enabled:
                    logger.info("Demand response participation enabled successfully!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning(
                    "Timeout waiting for demand response enable confirmation"
                )

            # Wait a bit before disabling
            logger.info("Waiting 5 seconds before disabling demand response...")
            await asyncio.sleep(5)

            # Disable demand response
            logger.info("Disabling demand response...")

            dr_disabled = False

            def on_dr_disabled(status):
                nonlocal dr_disabled
                logger.info("Demand response disabled!")
                logger.info("Device will no longer respond to utility demand signals")
                dr_disabled = True

            await mqtt_client.subscribe_device_status(device, on_dr_disabled)
            await mqtt_client.control.disable_demand_response(device)

            # Wait for confirmation
            for i in range(10):  # Wait up to 10 seconds
                if dr_disabled:
                    logger.info("Demand response participation disabled successfully!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning(
                    "Timeout waiting for demand response disable confirmation"
                )

        finally:
            await mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")


if __name__ == "__main__":
    print("=== Demand Response Example ===")
    print("This example demonstrates:")
    print("1. Connecting to device via MQTT")
    print("2. Getting current device status")
    print("3. Enabling demand response participation")
    print("4. Disabling demand response participation")
    print("5. Receiving and displaying the responses")
    print()

    # Note: This requires valid credentials
    print(
        "Note: Update email/password or set NAVIEN_EMAIL/NAVIEN_PASSWORD environment variables"
    )
    print()

    # Uncomment to run (requires valid credentials)
    # asyncio.run(demand_response_example())

    print("CLI equivalent commands:")
    print("  python -m nwp500.cli dr enable")
    print("  python -m nwp500.cli dr disable")
