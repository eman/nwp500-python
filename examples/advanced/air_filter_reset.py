#!/usr/bin/env python3
"""
Example: Air filter maintenance via MQTT.

This demonstrates how to reset the air filter maintenance timer
after cleaning or replacing the filter on heat pump models.
"""

import asyncio
import logging
from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

# Set up logging to see the air filter control process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def air_filter_example():
    """Example of resetting the air filter maintenance timer."""

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
            # Get current device info to see filter status
            logger.info("Getting current device feature information...")
            device_features = None

            def on_device_info(features):
                nonlocal device_features
                device_features = features
                if hasattr(features, "air_filter_maintenance_required"):
                    logger.info(
                        f"Air filter maintenance required: "
                        f"{features.air_filter_maintenance_required}"
                    )

            await mqtt_client.subscribe_device_feature(device, on_device_info)
            await mqtt_client.control.request_device_info(device)
            await asyncio.sleep(3)  # Wait for device info

            # Reset air filter maintenance timer
            logger.info("Resetting air filter maintenance timer...")

            filter_reset_complete = False

            def on_filter_reset(status):
                nonlocal filter_reset_complete
                logger.info("Air filter maintenance timer reset!")
                logger.info(f"Operation mode: {status.operation_mode.name}")
                filter_reset_complete = True

            await mqtt_client.subscribe_device_status(device, on_filter_reset)
            await mqtt_client.control.reset_air_filter(device)

            # Wait for confirmation
            for i in range(10):  # Wait up to 10 seconds
                if filter_reset_complete:
                    logger.info("Air filter timer reset successfully!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for filter reset confirmation")

            # Verify the reset by requesting device info again
            logger.info("Verifying filter reset by requesting updated device info...")
            await asyncio.sleep(2)

            def on_updated_device_info(features):
                if hasattr(features, "air_filter_maintenance_required"):
                    logger.info(
                        f"Air filter maintenance now required: "
                        f"{features.air_filter_maintenance_required}"
                    )
                    logger.info("Filter reset appears to have been successful!")

            await mqtt_client.subscribe_device_feature(device, on_updated_device_info)
            await mqtt_client.control.request_device_info(device)
            await asyncio.sleep(3)

        finally:
            await mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")


if __name__ == "__main__":
    print("=== Air Filter Maintenance Example ===")
    print("This example demonstrates:")
    print("1. Connecting to device via MQTT")
    print("2. Checking current air filter maintenance status")
    print("3. Resetting the air filter maintenance timer")
    print("4. Verifying the reset was successful")
    print()

    # Note: This requires valid credentials
    print(
        "Note: Update email/password or set NAVIEN_EMAIL/NAVIEN_PASSWORD environment variables"
    )
    print()

    # Uncomment to run (requires valid credentials)
    # asyncio.run(air_filter_example())

    print("CLI equivalent commands:")
    print("  python -m nwp500.cli reset-filter")
    print()
    print("Note: This feature is primarily for heat pump models.")
