#!/usr/bin/env python3
"""
Example: Automatic Recovery After Reconnection Failure

This example demonstrates different strategies to automatically recover
from permanent connection failures (after max reconnection attempts).

Strategies demonstrated:
1. Simple retry with reset - Just retry the connection after a delay
2. Full client recreation - Recreate the MQTT client from scratch
3. Token refresh and retry - Refresh auth tokens before retry
4. Exponential backoff retry - Use increasing delays between retry attempts
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
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================================
# STRATEGY 1: Simple Retry with Reset
# ============================================================================
async def strategy_simple_retry(auth_client, device):
    """
    Simple strategy: When reconnection fails, wait and try again.

    This is the simplest approach - just restart the reconnection attempts
    after a delay. The MQTT client's internal reconnection counter is reset.
    """
    logger.info("Using Strategy 1: Simple Retry with Reset")

    config = MqttConnectionConfig(
        auto_reconnect=True,
        max_reconnect_attempts=5,  # Fewer attempts for demo
        initial_reconnect_delay=1.0,
        max_reconnect_delay=30.0,
    )

    mqtt_client = NavienMqttClient(auth_client, config=config)

    # Track recovery attempts
    recovery_attempt = 0
    max_recovery_attempts = 3

    async def on_reconnection_failed(attempts):
        """Handle permanent reconnection failure."""
        nonlocal recovery_attempt
        recovery_attempt += 1

        logger.error(f"Reconnection failed after {attempts} attempts")
        logger.info(
            f"Recovery attempt {recovery_attempt}/{max_recovery_attempts} "
            f"- will retry in 30 seconds..."
        )

        if recovery_attempt >= max_recovery_attempts:
            logger.error("Max recovery attempts reached. Giving up.")
            return

        # Wait before retrying
        await asyncio.sleep(30)

        # Reset reconnection counter and try again using public API
        logger.info("Restarting reconnection process...")
        await mqtt_client.reset_reconnect()

    # Register the event handler
    mqtt_client.on("reconnection_failed", on_reconnection_failed)

    try:
        await mqtt_client.connect()
        logger.info(f"Connected: {mqtt_client.client_id}")

        # Subscribe and monitor
        await mqtt_client.subscribe_device_status(device, lambda s: None)
        await mqtt_client.start_periodic_device_status_requests(device)

        # Monitor for 120 seconds
        for i in range(120):
            await asyncio.sleep(1)
            if i % 10 == 0:
                status = (
                    "🟢 Connected" if mqtt_client.is_connected else "🔴 Disconnected"
                )
                logger.info(f"[{i}s] {status}")

    finally:
        if mqtt_client.is_connected:
            await mqtt_client.disconnect()


# ============================================================================
# STRATEGY 2: Full Client Recreation
# ============================================================================
async def strategy_full_recreation(auth_client, device):
    """
    Robust strategy: Recreate the entire MQTT client from scratch.

    This approach creates a new MQTT client instance when reconnection fails.
    It's more robust as it clears all internal state.
    """
    logger.info("Using Strategy 2: Full Client Recreation")

    config = MqttConnectionConfig(
        auto_reconnect=True,
        max_reconnect_attempts=5,
        initial_reconnect_delay=1.0,
        max_reconnect_delay=30.0,
    )

    mqtt_client = None
    recovery_attempt = 0
    max_recovery_attempts = 3

    async def create_and_connect():
        """Create a new MQTT client and connect."""
        nonlocal mqtt_client

        if mqtt_client and mqtt_client.is_connected:
            await mqtt_client.disconnect()

        mqtt_client = NavienMqttClient(auth_client, config=config)
        mqtt_client.on("reconnection_failed", on_reconnection_failed)

        await mqtt_client.connect()
        logger.info(f"Connected: {mqtt_client.client_id}")

        # Re-subscribe
        await mqtt_client.subscribe_device_status(device, lambda s: None)
        await mqtt_client.start_periodic_device_status_requests(device)

        return mqtt_client

    async def on_reconnection_failed(attempts):
        """Handle permanent reconnection failure by recreating client."""
        nonlocal recovery_attempt, mqtt_client

        recovery_attempt += 1
        logger.error(f"Reconnection failed after {attempts} attempts")
        logger.info(
            f"Recovery attempt {recovery_attempt}/{max_recovery_attempts} "
            f"- recreating MQTT client in 30 seconds..."
        )

        if recovery_attempt >= max_recovery_attempts:
            logger.error("Max recovery attempts reached. Giving up.")
            return

        await asyncio.sleep(30)

        try:
            mqtt_client = await create_and_connect()
            recovery_attempt = 0  # Reset on success
            logger.info("Successfully recreated MQTT client")
        except Exception as e:
            logger.error(f"Failed to recreate MQTT client: {e}")

    try:
        mqtt_client = await create_and_connect()

        # Monitor for 120 seconds
        for i in range(120):
            await asyncio.sleep(1)
            if i % 10 == 0:
                status = (
                    "🟢 Connected" if mqtt_client.is_connected else "🔴 Disconnected"
                )
                logger.info(f"[{i}s] {status}")

    finally:
        if mqtt_client and mqtt_client.is_connected:
            await mqtt_client.disconnect()


# ============================================================================
# STRATEGY 3: Token Refresh and Retry
# ============================================================================
async def strategy_token_refresh(auth_client, device):
    """
    Advanced strategy: Refresh authentication tokens before retry.

    Sometimes connection failures are due to expired tokens. This strategy
    refreshes the auth tokens before retrying the connection.
    """
    logger.info("Using Strategy 3: Token Refresh and Retry")

    config = MqttConnectionConfig(
        auto_reconnect=True,
        max_reconnect_attempts=5,
        initial_reconnect_delay=1.0,
        max_reconnect_delay=30.0,
    )

    mqtt_client = None
    recovery_attempt = 0
    max_recovery_attempts = 3

    async def on_reconnection_failed(attempts):
        """Handle permanent reconnection failure with token refresh."""
        nonlocal recovery_attempt, mqtt_client

        recovery_attempt += 1
        logger.error(f"Reconnection failed after {attempts} attempts")
        logger.info(
            f"Recovery attempt {recovery_attempt}/{max_recovery_attempts} "
            f"- refreshing tokens and retrying in 30 seconds..."
        )

        if recovery_attempt >= max_recovery_attempts:
            logger.error("Max recovery attempts reached. Giving up.")
            return

        await asyncio.sleep(30)

        try:
            # Refresh authentication tokens
            logger.info("Refreshing authentication tokens...")
            await auth_client.refresh_token()
            logger.info("Tokens refreshed successfully")

            # Disconnect old client
            if mqtt_client and mqtt_client.is_connected:
                await mqtt_client.disconnect()

            # Create new client with fresh tokens
            mqtt_client = NavienMqttClient(auth_client, config=config)
            mqtt_client.on("reconnection_failed", on_reconnection_failed)

            await mqtt_client.connect()
            logger.info(f"Reconnected with fresh tokens: {mqtt_client.client_id}")

            # Re-subscribe
            await mqtt_client.subscribe_device_status(device, lambda s: None)
            await mqtt_client.start_periodic_device_status_requests(device)

            recovery_attempt = 0  # Reset on success

        except Exception as e:
            logger.error(f"Failed to refresh and reconnect: {e}")

    mqtt_client = NavienMqttClient(auth_client, config=config)
    mqtt_client.on("reconnection_failed", on_reconnection_failed)

    try:
        await mqtt_client.connect()
        logger.info(f"Connected: {mqtt_client.client_id}")

        # Subscribe and monitor
        await mqtt_client.subscribe_device_status(device, lambda s: None)
        await mqtt_client.start_periodic_device_status_requests(device)

        # Monitor for 120 seconds
        for i in range(120):
            await asyncio.sleep(1)
            if i % 10 == 0:
                status = (
                    "🟢 Connected" if mqtt_client.is_connected else "🔴 Disconnected"
                )
                logger.info(f"[{i}s] {status}")

    finally:
        if mqtt_client and mqtt_client.is_connected:
            await mqtt_client.disconnect()


# ============================================================================
# STRATEGY 4: Exponential Backoff Retry (Production-Ready)
# ============================================================================
async def strategy_exponential_backoff(auth_client, device):
    """
    Production-ready strategy: Use exponential backoff for recovery attempts.

    This is the most robust strategy for production use. It:
    - Uses exponential backoff between recovery attempts
    - Refreshes tokens periodically
    - Recreates the client cleanly
    - Has configurable limits
    """
    logger.info("Using Strategy 4: Exponential Backoff Retry (Production)")

    config = MqttConnectionConfig(
        auto_reconnect=True,
        max_reconnect_attempts=5,
        initial_reconnect_delay=1.0,
        max_reconnect_delay=30.0,
    )

    mqtt_client = None
    recovery_attempt = 0
    max_recovery_attempts = 10
    initial_recovery_delay = 30.0
    max_recovery_delay = 300.0  # 5 minutes
    recovery_backoff_multiplier = 2.0

    async def on_reconnection_failed(attempts):
        """Handle permanent reconnection failure with exponential backoff."""
        nonlocal recovery_attempt, mqtt_client

        recovery_attempt += 1
        logger.error(f"Reconnection failed after {attempts} attempts")

        if recovery_attempt >= max_recovery_attempts:
            logger.error("Max recovery attempts reached. Manual intervention required.")
            # In production, you might want to:
            # - Send alert notification
            # - Restart the application
            # - Log to monitoring system
            return

        # Calculate delay with exponential backoff
        delay = min(
            initial_recovery_delay
            * (recovery_backoff_multiplier ** (recovery_attempt - 1)),
            max_recovery_delay,
        )

        logger.info(
            f"Recovery attempt {recovery_attempt}/{max_recovery_attempts} "
            f"in {delay:.1f} seconds..."
        )

        await asyncio.sleep(delay)

        try:
            # Refresh tokens every few attempts
            if recovery_attempt % 3 == 0:
                logger.info("Refreshing authentication tokens...")
                await auth_client.refresh_token()
                logger.info("Tokens refreshed")

            # Clean up old client
            if mqtt_client:
                try:
                    if mqtt_client.is_connected:
                        await mqtt_client.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting old client: {e}")

            # Create new client
            mqtt_client = NavienMqttClient(auth_client, config=config)
            mqtt_client.on("reconnection_failed", on_reconnection_failed)

            await mqtt_client.connect()
            logger.info(f"✅ Recovered! Connected: {mqtt_client.client_id}")

            # Re-subscribe
            await mqtt_client.subscribe_device_status(device, lambda s: None)
            await mqtt_client.start_periodic_device_status_requests(device)

            recovery_attempt = 0  # Reset on success
            logger.info("All subscriptions restored")

        except Exception as e:
            logger.error(f"Recovery attempt failed: {e}")

    mqtt_client = NavienMqttClient(auth_client, config=config)
    mqtt_client.on("reconnection_failed", on_reconnection_failed)

    try:
        await mqtt_client.connect()
        logger.info(f"Connected: {mqtt_client.client_id}")

        # Subscribe and monitor
        await mqtt_client.subscribe_device_status(device, lambda s: None)
        await mqtt_client.start_periodic_device_status_requests(device)

        # Monitor for 120 seconds
        for i in range(120):
            await asyncio.sleep(1)
            if i % 10 == 0:
                status = (
                    "🟢 Connected" if mqtt_client.is_connected else "🔴 Disconnected"
                )
                logger.info(f"[{i}s] {status}")

    finally:
        if mqtt_client and mqtt_client.is_connected:
            await mqtt_client.disconnect()


# ============================================================================
# Main
# ============================================================================
async def main():
    """Run the selected strategy."""
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return

    # Select strategy (1-4)
    strategy = int(os.getenv("STRATEGY", "4"))

    print("=" * 70)
    print("Automatic Recovery After Reconnection Failure")
    print("=" * 70)

    async with NavienAuthClient(email, password) as auth_client:
        logger.info(f"Authenticated as: {auth_client.current_user.full_name}")

        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()

        if not device:
            logger.error("No devices found")
            return

        logger.info(f"Found device: {device.device_info.device_name}")

        # Run selected strategy
        if strategy == 1:
            await strategy_simple_retry(auth_client, device)
        elif strategy == 2:
            await strategy_full_recreation(auth_client, device)
        elif strategy == 3:
            await strategy_token_refresh(auth_client, device)
        elif strategy == 4:
            await strategy_exponential_backoff(auth_client, device)
        else:
            logger.error(f"Invalid strategy: {strategy}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
