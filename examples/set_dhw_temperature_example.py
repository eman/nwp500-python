#!/usr/bin/env python3
"""
Example: Setting DHW target temperature via MQTT and displaying response.

This demonstrates how to programmatically change the water heater DHW
(Domestic Hot Water) target temperature and receive confirmation of the change.
"""

import asyncio
import logging
from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

# Set up logging to see the temperature change process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def set_dhw_temperature_example():
    """Example of setting DHW target temperature programmatically."""

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
                logger.info(
                    f"Current DHW target temperature: {status.dhwTargetTemperatureSetting}°F"
                )
                logger.info(f"Current DHW temperature: {status.dhwTemperature}°F")

            await mqtt_client.subscribe_device_status(device, on_current_status)
            await mqtt_client.request_device_status(device)
            await asyncio.sleep(3)  # Wait for current status

            # Set new target temperature to 140°F
            target_temperature = 140
            logger.info(f"Setting DHW target temperature to {target_temperature}°F...")

            # Set up callback to capture temperature change response
            temp_changed = False

            def on_temp_change_response(status):
                nonlocal temp_changed
                logger.info("Temperature change response received!")
                logger.info(
                    f"New target temperature: {status.dhwTargetTemperatureSetting}°F"
                )
                logger.info(f"Current DHW temperature: {status.dhwTemperature}°F")
                logger.info(f"Operation mode: {status.operationMode.name}")
                logger.info(f"Tank charge: {status.dhwChargePer}%")
                temp_changed = True

            await mqtt_client.subscribe_device_status(device, on_temp_change_response)

            # Send temperature change command using display temperature value
            await mqtt_client.set_dhw_temperature_display(device, target_temperature)

            # Wait for confirmation
            for i in range(15):  # Wait up to 15 seconds
                if temp_changed:
                    logger.info("Temperature change confirmed!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for temperature change confirmation")

        finally:
            await mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")


if __name__ == "__main__":
    print("=== DHW Temperature Change Example ===")
    print("This example demonstrates:")
    print("1. Connecting to device via MQTT")
    print("2. Getting current DHW target temperature")
    print("3. Setting new DHW target temperature to 140°F")
    print("4. Receiving and displaying the response")
    print()

    # Note: This requires valid credentials
    print(
        "Note: Update email/password or set NAVIEN_EMAIL/NAVIEN_PASSWORD environment variables"
    )
    print()

    # Uncomment to run (requires valid credentials)
    # asyncio.run(set_dhw_temperature_example())

    print("CLI equivalent commands:")
    print("  python -m nwp500.cli --set-dhw-temp 140")
    print("  python -m nwp500.cli --set-dhw-temp 130")
    print("  python -m nwp500.cli --set-dhw-temp 150")
    print()
    print("Valid temperature range: 115-150°F")
    print("Note: The device may cap temperatures at 150°F maximum")
