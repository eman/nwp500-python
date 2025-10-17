#!/usr/bin/env python3
"""Example: Toggle Anti-Legionella protection via MQTT.

This example demonstrates:
1. Getting the initial Anti-Legionella status
2. Enabling Anti-Legionella with a specific period
3. Displaying the status after enabling
4. Disabling Anti-Legionella
5. Displaying the status after disabling

Note: Disabling Anti-Legionella may increase health risks from Legionella bacteria.
"""

import asyncio
import os
import sys
from typing import Any

from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient
from nwp500.constants import (
    CMD_ANTI_LEGIONELLA_DISABLE,
    CMD_ANTI_LEGIONELLA_ENABLE,
    CMD_STATUS_REQUEST,
)


def display_anti_legionella_status(status: dict[str, Any], label: str = "") -> None:
    """Display Anti-Legionella status in a formatted way."""
    period = status.get("antiLegionellaPeriod")
    use_value = status.get("antiLegionellaUse")
    enabled = use_value == 2
    busy = status.get("antiLegionellaOperationBusy") == 2

    if period is not None and use_value is not None:
        prefix = f"{label}: " if label else ""
        status_str = "ENABLED" if enabled else "DISABLED"
        running_str = " (running now)" if busy else ""

        print(f"{prefix}Anti-Legionella is {status_str}")
        print(f"  - Period: every {period} day(s)")
        print(
            f"  - Status: {'Running disinfection cycle' if busy else 'Not running'}{running_str}"
        )
        print(
            f"  - Raw values: antiLegionellaUse={use_value}, antiLegionellaPeriod={period}, busy={busy}"
        )


async def main() -> None:
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        sys.exit(1)

    async with NavienAuthClient(email, password) as auth_client:
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()
        if not device:
            print("No devices found for this account")
            return

        print(f"Connected to device: {device.device_info.device_name}")
        print(f"Device MAC: {device.device_info.mac_address}")
        print()

        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()

        # Track the latest status
        latest_status = {}
        status_received = asyncio.Event()

        # Expected command codes for each step
        expected_command = None

        def on_status(topic: str, message: dict[str, Any]) -> None:
            nonlocal latest_status
            # Debug: print what we received
            print(f"[DEBUG] Received message on topic: {topic}")

            # Skip command echoes (messages on /ctrl topic)
            if topic.endswith("/ctrl"):
                print("[DEBUG] Skipping command echo")
                return

            status = message.get("response", {}).get("status", {})
            command = status.get("command")

            # Only capture status if it has Anti-Legionella data
            if status.get("antiLegionellaPeriod") is not None:
                # If we're expecting a specific command, only accept that
                if expected_command is None or command == expected_command:
                    latest_status = status
                    status_received.set()
                    print(
                        f"[DEBUG] Anti-Legionella status captured (command={command})"
                    )
                else:
                    print(
                        f"[DEBUG] Ignoring status from different command (got {command}, expected {expected_command})"
                    )
            else:
                print("[DEBUG] Message doesn't contain antiLegionellaPeriod")

        # Listen for status updates
        device_type = device.device_info.device_type
        device_id = device.device_info.mac_address
        device_topic = f"navilink-{device_id}"
        response_topic = f"cmd/{device_type}/{device_topic}/#"
        print(f"[DEBUG] Subscribing to: {response_topic}")
        await mqtt_client.subscribe(response_topic, on_status)
        print("[DEBUG] Subscription successful")
        await asyncio.sleep(1)  # Give subscription time to settle

        # Step 1: Get initial status
        print("=" * 70)
        print("STEP 1: Getting initial Anti-Legionella status...")
        print("=" * 70)
        status_received.clear()
        expected_command = CMD_STATUS_REQUEST
        await mqtt_client.request_device_status(device)

        try:
            await asyncio.wait_for(status_received.wait(), timeout=10)
            display_anti_legionella_status(latest_status, "INITIAL STATE")
        except asyncio.TimeoutError:
            print("Timeout waiting for status response")
            return

        print()
        await asyncio.sleep(2)

        # Step 2: Enable Anti-Legionella
        print("=" * 70)
        print("STEP 2: Enabling Anti-Legionella cycle every 7 days...")
        print("=" * 70)
        status_received.clear()
        expected_command = CMD_ANTI_LEGIONELLA_ENABLE
        await mqtt_client.enable_anti_legionella(device, period_days=7)

        try:
            await asyncio.wait_for(status_received.wait(), timeout=10)
            display_anti_legionella_status(latest_status, "AFTER ENABLE")
        except asyncio.TimeoutError:
            print("Timeout waiting for status response after enable")

        print()
        await asyncio.sleep(2)

        # Step 3: Disable Anti-Legionella
        print("=" * 70)
        print("STEP 3: Disabling Anti-Legionella cycle...")
        print("WARNING: This reduces protection against Legionella bacteria!")
        print("=" * 70)
        status_received.clear()
        expected_command = CMD_ANTI_LEGIONELLA_DISABLE
        await mqtt_client.disable_anti_legionella(device)

        try:
            await asyncio.wait_for(status_received.wait(), timeout=10)
            display_anti_legionella_status(latest_status, "AFTER DISABLE")
        except asyncio.TimeoutError:
            print("Timeout waiting for status response after disable")

        print()
        await asyncio.sleep(2)

        # Step 4: Re-enable with different period
        print("=" * 70)
        print("STEP 4: Re-enabling Anti-Legionella with 14-day cycle...")
        print("=" * 70)
        status_received.clear()
        expected_command = CMD_ANTI_LEGIONELLA_ENABLE
        await mqtt_client.enable_anti_legionella(device, period_days=14)

        try:
            await asyncio.wait_for(status_received.wait(), timeout=10)
            display_anti_legionella_status(latest_status, "AFTER RE-ENABLE")
        except asyncio.TimeoutError:
            print("Timeout waiting for status response after re-enable")

        print()
        await asyncio.sleep(1)

        await mqtt_client.disconnect()
        print("=" * 70)
        print("Done. Anti-Legionella protection is now enabled with 14-day cycle.")
        print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled by user")
