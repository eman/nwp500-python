#!/usr/bin/env python3
"""
Example: Recirculation pump control via MQTT.

This demonstrates how to control the recirculation pump operation mode,
trigger the hot button, and configure scheduling.
"""

import asyncio
import logging
from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

# Set up logging to see the recirculation control process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def recirculation_example():
    """Example of controlling the recirculation pump."""

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

            await mqtt_client.subscribe_device_status(device, on_current_status)
            await mqtt_client.control.request_device_status(device)
            await asyncio.sleep(3)  # Wait for current status

            # Set recirculation mode to "Always On"
            logger.info("Setting recirculation pump mode to 'Always On'...")

            mode_set = False

            def on_mode_set(status):
                nonlocal mode_set
                logger.info("Recirculation pump mode set to 'Always On'!")
                logger.info(
                    "The pump will continuously circulate hot water to fixtures"
                )
                mode_set = True

            await mqtt_client.subscribe_device_status(device, on_mode_set)
            await mqtt_client.control.set_recirculation_mode(device, 1)  # 1 = Always On

            # Wait for confirmation
            for i in range(10):  # Wait up to 10 seconds
                if mode_set:
                    logger.info("Recirculation mode set successfully!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for mode change confirmation")

            logger.info("Waiting 5 seconds before triggering hot button...")
            await asyncio.sleep(5)

            # Trigger the recirculation hot button
            logger.info("Triggering recirculation pump hot button...")

            hot_button_triggered = False

            def on_hot_button(status):
                nonlocal hot_button_triggered
                logger.info("Recirculation pump hot button triggered!")
                logger.info("Hot water is now being delivered to fixtures")
                hot_button_triggered = True

            await mqtt_client.subscribe_device_status(device, on_hot_button)
            await mqtt_client.control.trigger_recirculation_hot_button(device)

            # Wait for confirmation
            for i in range(10):  # Wait up to 10 seconds
                if hot_button_triggered:
                    logger.info("Hot button triggered successfully!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for hot button confirmation")

            logger.info("Waiting 5 seconds before changing mode to 'Button Only'...")
            await asyncio.sleep(5)

            # Change mode to "Button Only"
            logger.info("Changing recirculation pump mode to 'Button Only'...")

            button_only_set = False

            def on_button_only_set(status):
                nonlocal button_only_set
                logger.info("Recirculation pump mode changed to 'Button Only'!")
                logger.info("The pump will only run when the hot button is pressed")
                button_only_set = True

            await mqtt_client.subscribe_device_status(device, on_button_only_set)
            await mqtt_client.control.set_recirculation_mode(
                device, 2
            )  # 2 = Button Only

            # Wait for confirmation
            for i in range(10):  # Wait up to 10 seconds
                if button_only_set:
                    logger.info("Recirculation mode changed successfully!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Timeout waiting for mode change confirmation")

        finally:
            await mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")


if __name__ == "__main__":
    print("=== Recirculation Pump Control Example ===")
    print("This example demonstrates:")
    print("1. Connecting to device via MQTT")
    print("2. Getting current device status")
    print("3. Setting recirculation pump mode to 'Always On'")
    print("4. Triggering the recirculation pump hot button")
    print("5. Changing recirculation pump mode to 'Button Only'")
    print("6. Receiving and displaying responses")
    print()

    # Note: This requires valid credentials
    print(
        "Note: Update email/password or set NAVIEN_EMAIL/NAVIEN_PASSWORD environment variables"
    )
    print()

    # Uncomment to run (requires valid credentials)
    # asyncio.run(recirculation_example())

    print("CLI equivalent commands:")
    print("  python -m nwp500.cli recirc 1")
    print("  python -m nwp500.cli hot-button")
    print("  python -m nwp500.cli recirc 2")
    print()
    print("Valid recirculation modes:")
    print("  1 = Always On (pump continuously circulates hot water)")
    print("  2 = Button Only (pump runs only when hot button is pressed)")
    print("  3 = Schedule (pump operates on a defined schedule)")
    print("  4 = Temperature (pump operates when temperature falls below setpoint)")
