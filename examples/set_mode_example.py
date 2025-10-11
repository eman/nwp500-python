#!/usr/bin/env python3
"""
Example: Setting operation mode via MQTT and displaying response.

This demonstrates how to programmatically change the water heater operation mode
and receive confirmation of the change.
"""

import asyncio
import logging
from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

# Set up logging to see the mode change process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def set_mode_example():
    """Example of setting operation mode programmatically."""

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
                logger.info(f"Current mode: {status.operationMode.name}")

            await mqtt_client.subscribe_device_status(device, on_current_status)
            await mqtt_client.request_device_status(device)
            await asyncio.sleep(3)  # Wait for current status

            # Change to Energy Saver mode
            logger.info("Changing to Energy Saver mode...")

            # Set up callback to capture mode change response
            mode_changed = False

            def on_mode_change_response(status):
                nonlocal mode_changed
                logger.info("Mode change response received!")
                logger.info(f"New mode: {status.operationMode.name}")
                logger.info(f"DHW Temperature: {status.dhwTemperature}°F")
                logger.info(f"Tank Charge: {status.dhwChargePer}%")
                mode_changed = True

            await mqtt_client.subscribe_device_status(device, on_mode_change_response)

            # Send mode change command (3 = Energy Saver, per MQTT protocol)
            await mqtt_client.set_dhw_mode(device, 3)

            # Wait for confirmation
            for i in range(15):  # Wait up to 15 seconds
                if mode_changed:
                    logger.info("Mode change confirmed!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for mode change confirmation")

        finally:
            await mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")


if __name__ == "__main__":
    print("=== Operation Mode Change Example ===")
    print("This example demonstrates:")
    print("1. Connecting to device via MQTT")
    print("2. Getting current operation mode")
    print("3. Changing to Energy Saver mode")
    print("4. Receiving and displaying the response")
    print()

    # Note: This requires valid credentials
    print(
        "Note: Update email/password or set NAVIEN_EMAIL/NAVIEN_PASSWORD environment variables"
    )
    print()

    # Uncomment to run (requires valid credentials)
    # asyncio.run(set_mode_example())

    print("CLI equivalent commands:")
    print("  python -m nwp500.cli --set-mode energy-saver")
    print("  python -m nwp500.cli --set-mode heat-pump")
    print("  python -m nwp500.cli --set-mode electric")
    print("  python -m nwp500.cli --set-mode high-demand")
    print("  python -m nwp500.cli --set-mode vacation")
    print("  python -m nwp500.cli --set-mode standby")
