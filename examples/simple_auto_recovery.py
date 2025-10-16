#!/usr/bin/env python3
"""
Example: Simple Automatic Recovery (Recommended Pattern)

This example shows the simplest and most reliable way to handle permanent
connection failures. When the MQTT client fails to reconnect after max
attempts, it will automatically:

1. Wait 60 seconds
2. Refresh authentication tokens
3. Recreate the MQTT client
4. Restore all subscriptions
5. Restart periodic requests

This pattern is production-ready and handles most network issues gracefully.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient
from nwp500.mqtt_client import MqttConnectionConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class ResilientMqttClient:
    """
    Wrapper around NavienMqttClient that automatically recovers from failures.

    This class handles the `reconnection_failed` event and automatically
    recreates the MQTT client with fresh authentication tokens.
    """

    def __init__(self, auth_client, config=None):
        self.auth_client = auth_client
        self.config = config or MqttConnectionConfig()
        self.mqtt_client = None
        self.device = None
        self.status_callback = None

        # Recovery settings
        self.max_recovery_attempts = 10
        self.recovery_delay = 60.0  # seconds
        self.recovery_attempt = 0
        self._recovery_in_progress = False  # Guard against concurrent recovery

    async def connect(self, device, status_callback=None):
        """
        Connect to MQTT and set up automatic recovery.

        Args:
            device: Navien device to monitor
            status_callback: Optional callback for status updates
        """
        self.device = device
        self.status_callback = status_callback

        # Create and connect MQTT client
        await self._create_client()

        logger.info(f"✅ Connected: {self.mqtt_client.client_id}")

    async def _create_client(self):
        """Create MQTT client with recovery handler."""
        # Clean up old client if exists
        if self.mqtt_client and self.mqtt_client.is_connected:
            try:
                await self.mqtt_client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting old client: {e}")

        # Create new client
        self.mqtt_client = NavienMqttClient(self.auth_client, config=self.config)

        # Register recovery handler
        self.mqtt_client.on("reconnection_failed", self._handle_reconnection_failed)

        # Connect
        await self.mqtt_client.connect()

        # Restore subscriptions
        if self.device and self.status_callback:
            await self.mqtt_client.subscribe_device_status(
                self.device, self.status_callback
            )
            await self.mqtt_client.start_periodic_device_status_requests(self.device)
            logger.info("Subscriptions restored")

    async def _handle_reconnection_failed(self, attempts):
        """
        Handle permanent reconnection failure by recreating the client.

        This method is called when the MQTT client exhausts all reconnection
        attempts. It will automatically:
        1. Wait before retrying
        2. Refresh authentication tokens
        3. Recreate the MQTT client
        4. Restore all subscriptions
        """
        # Prevent overlapping recovery attempts
        if self._recovery_in_progress:
            logger.debug(
                "Recovery already in progress, ignoring reconnection_failed event"
            )
            return

        self._recovery_in_progress = True
        self.recovery_attempt += 1

        try:
            logger.error(
                f"Reconnection failed after {attempts} attempts. "
                f"Starting recovery attempt {self.recovery_attempt}/{self.max_recovery_attempts}"
            )

            if self.recovery_attempt >= self.max_recovery_attempts:
                logger.error(
                    "Maximum recovery attempts reached. Manual intervention required."
                )
                # In production, you might want to:
                # - Send alert/notification
                # - Trigger application restart
                # - Log to monitoring system
                return

            # Wait before attempting recovery
            logger.info(f"Waiting {self.recovery_delay} seconds before recovery...")
            await asyncio.sleep(self.recovery_delay)

            # Refresh authentication tokens
            logger.info("Refreshing authentication tokens...")
            await self.auth_client.refresh_token()
            logger.info("Tokens refreshed successfully")

            # Recreate MQTT client
            logger.info("Recreating MQTT client...")
            await self._create_client()

            # Reset recovery counter on success
            self.recovery_attempt = 0
            logger.info("✅ Recovery successful!")

        except Exception as e:
            logger.error(f"Recovery attempt failed: {e}")
            # The next reconnection_failed event will trigger another recovery attempt
        finally:
            self._recovery_in_progress = False

    async def disconnect(self):
        """Disconnect from MQTT."""
        if self.mqtt_client and self.mqtt_client.is_connected:
            await self.mqtt_client.disconnect()
            logger.info("Disconnected")

    @property
    def is_connected(self):
        """Check if currently connected."""
        return self.mqtt_client and self.mqtt_client.is_connected


async def main():
    """Example usage of ResilientMqttClient."""
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return

    print("=" * 70)
    print("Simple Automatic Recovery Example")
    print("=" * 70)

    async with NavienAuthClient(email, password) as auth_client:
        logger.info(f"Authenticated as: {auth_client.current_user.full_name}")

        # Get device
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()

        if not device:
            logger.error("No devices found")
            return

        logger.info(f"Found device: {device.device_info.device_name}")

        # Status callback
        status_count = 0

        def on_status(status):
            nonlocal status_count
            status_count += 1
            logger.info(
                f"Status #{status_count}: Temp={status.dhwTemperature}°F, "
                f"Mode={status.operationMode}"
            )

        # Create resilient MQTT client
        mqtt_config = MqttConnectionConfig(
            auto_reconnect=True,
            max_reconnect_attempts=5,  # Low for demo purposes
            initial_reconnect_delay=1.0,
            max_reconnect_delay=30.0,
        )

        resilient_client = ResilientMqttClient(auth_client, config=mqtt_config)

        # Connect with automatic recovery
        await resilient_client.connect(device, status_callback=on_status)

        print("\n" + "=" * 70)
        print("Monitoring connection (180 seconds)...")
        print("=" * 70)
        print("\nThe client will automatically recover if connection fails.")
        print("To test: disconnect your internet and wait ~30 seconds,")
        print("then reconnect. The client should automatically recover.\n")

        # Monitor for 3 minutes
        for i in range(180):
            await asyncio.sleep(1)

            # Show status every 10 seconds
            if i % 10 == 0:
                status = (
                    "🟢 Connected"
                    if resilient_client.is_connected
                    else "🔴 Disconnected"
                )
                logger.info(f"[{i}s] {status} | Status updates: {status_count}")

        print("\n" + "=" * 70)
        print(f"Monitoring complete. Received {status_count} status updates.")
        print("=" * 70)

        # Disconnect
        await resilient_client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
