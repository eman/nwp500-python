#!/usr/bin/env python3
"""
Example: Controlling device power via MQTT.

This demonstrates how to programmatically turn the water heater on and off
and receive confirmation of the power state change.
"""

import asyncio
import logging
from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

# Set up logging to see the power control process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def power_control_example():
    """Example of controlling device power programmatically."""

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
                logger.info(f"Current operation mode: {status.operationMode.name}")
                logger.info(f"Current DHW temperature: {status.dhwTemperature}°F")

            await mqtt_client.subscribe_device_status(device, on_current_status)
            await mqtt_client.request_device_status(device)
            await asyncio.sleep(3)  # Wait for current status

            # Turn device off
            logger.info("Turning device OFF...")

            power_off_complete = False

            def on_power_off_response(status):
                nonlocal power_off_complete
                logger.info("Power OFF response received!")
                logger.info(f"Operation mode: {status.operationMode.name}")
                logger.info(f"DHW Operation Setting: {status.dhwOperationSetting.name}")
                power_off_complete = True

            await mqtt_client.subscribe_device_status(device, on_power_off_response)
            await mqtt_client.set_power(device, power_on=False)

            # Wait for confirmation
            for i in range(15):  # Wait up to 15 seconds
                if power_off_complete:
                    logger.info("Device turned OFF successfully!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for power OFF confirmation")

            # Wait a bit before turning back on
            logger.info("Waiting 5 seconds before turning device back ON...")
            await asyncio.sleep(5)

            # Turn device back on
            logger.info("Turning device ON...")

            power_on_complete = False

            def on_power_on_response(status):
                nonlocal power_on_complete
                logger.info("Power ON response received!")
                logger.info(f"Operation mode: {status.operationMode.name}")
                logger.info(f"DHW Operation Setting: {status.dhwOperationSetting.name}")
                logger.info(f"Tank charge: {status.dhwChargePer}%")
                power_on_complete = True

            await mqtt_client.subscribe_device_status(device, on_power_on_response)
            await mqtt_client.set_power(device, power_on=True)

            # Wait for confirmation
            for i in range(15):  # Wait up to 15 seconds
                if power_on_complete:
                    logger.info("Device turned ON successfully!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for power ON confirmation")

        finally:
            await mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")


if __name__ == "__main__":
    print("=== Power Control Example ===")
    print("This example demonstrates:")
    print("1. Connecting to device via MQTT")
    print("2. Getting current device status")
    print("3. Turning device OFF")
    print("4. Turning device ON")
    print("5. Receiving and displaying the responses")
    print()

    # Note: This requires valid credentials
    print(
        "Note: Update email/password or set NAVIEN_EMAIL/NAVIEN_PASSWORD environment variables"
    )
    print()

    # Uncomment to run (requires valid credentials)
    # asyncio.run(power_control_example())

    print("CLI equivalent commands:")
    print("  python -m nwp500.cli --power-off")
    print("  python -m nwp500.cli --power-on")
    print("  python -m nwp500.cli --power-on --status")
