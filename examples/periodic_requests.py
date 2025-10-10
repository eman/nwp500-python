#!/usr/bin/env python3
"""
Example: Periodic Requests (Device Info and Status)

This example demonstrates the flexible periodic request helper that can send
both device info and device status requests at regular intervals.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500 import (
    DeviceFeature,
    DeviceStatus,
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
    PeriodicRequestType,
)

try:
    from examples.mask import mask_mac  # type: ignore
except Exception:

    def mask_mac(mac):  # pragma: no cover - fallback for examples
        return "[REDACTED_MAC]"


async def main():
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Error: NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables required")
        sys.exit(1)

    print("=" * 70)
    print("Periodic Requests Example (Device Info & Status)")
    print("=" * 70)

    # Authenticate and get device
    print("\n1. Authenticating...")
    async with NavienAuthClient(email, password) as auth_client:
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()

    if not device:
        print("Error: No devices found")
        sys.exit(1)

    device_id = device.device_info.mac_address

    print(f"   Device: {device.device_info.device_name}")
    print(f"   MAC: {mask_mac(device_id)}")

    # Connect MQTT
    print("\n2. Connecting to MQTT...")
    mqtt = NavienMqttClient(auth_client)
    await mqtt.connect()
    print(f"   Connected: {mqtt.client_id}")

    # Counters for received messages
    status_count = 0
    info_count = 0

    # Typed callbacks for DeviceStatus and DeviceFeature
    def on_device_status(status: DeviceStatus):
        """Callback receives parsed DeviceStatus objects."""
        nonlocal status_count
        status_count += 1

        print(f"\n--- Status Response #{status_count} ---")
        print(f"  Temperature: {status.dhwTemperature:.1f}°F")
        print(f"  Power: {status.currentInstPower:.1f}W")
        print(f"  Available Energy: {status.availableEnergyCapacity:.1f}%")

    def on_device_feature(feature: DeviceFeature):
        """Callback receives parsed DeviceFeature objects."""
        nonlocal info_count
        info_count += 1

        print(f"\n--- Device Info Response #{info_count} ---")
        print(f"  Serial: {feature.controllerSerialNumber}")
        print(f"  FW Version: {feature.controllerSwVersion}")
        print(f"  Heat Pump: {feature.heatpumpUse}")

    # Subscribe using typed callbacks
    await mqtt.subscribe_device_status(device, on_device_status)
    await mqtt.subscribe_device_feature(device, on_device_feature)

    async def monitor_with_dots(seconds: int, interval: int = 5):
        """Monitor for specified seconds, printing dots every interval."""
        elapsed = 0
        while elapsed < seconds:
            await asyncio.sleep(interval)
            elapsed += interval
            print(
                f"  ... {elapsed}s elapsed (status: {status_count}, info: {info_count})"
            )

    # Small delay to ensure subscription is fully established
    await asyncio.sleep(2)

    print("\n" + "=" * 70)
    print("Example 1: Device Status Requests (Default)")
    print("=" * 70)

    # Start periodic status requests (default behavior)
    print("\nStarting periodic status requests (every 20 seconds for demo)...")
    await mqtt.start_periodic_requests(
        device=device,
        request_type=PeriodicRequestType.DEVICE_STATUS,
        period_seconds=20,
    )

    # Send initial request immediately to get first response
    print("Sending initial status request...")
    await mqtt.request_device_status(device)

    print("Monitoring for 60 seconds...")
    print("(First automatic request in ~20 seconds)")
    await monitor_with_dots(60, 10)

    print("\n" + "=" * 70)
    print("Example 2: Device Info Requests")
    print("=" * 70)

    # Switch to device info requests
    print("\nSwitching to periodic device info requests (every 20 seconds)...")
    await mqtt.start_periodic_requests(
        device=device,
        request_type=PeriodicRequestType.DEVICE_INFO,
        period_seconds=20,
    )

    # Send initial request immediately
    print("Sending initial device info request...")
    await mqtt.request_device_info(device)

    print("Monitoring for 60 seconds...")
    print("(First automatic request in ~20 seconds)")
    await monitor_with_dots(60, 10)

    print("\n" + "=" * 70)
    print("Example 3: Both Types Simultaneously")
    print("=" * 70)

    # Run both types at the same time
    print("\nStarting BOTH status and info requests...")
    print("  - Status: every 20 seconds")
    print("  - Info: every 40 seconds")

    await mqtt.start_periodic_requests(
        device=device,
        request_type=PeriodicRequestType.DEVICE_STATUS,
        period_seconds=20,
    )

    await mqtt.start_periodic_requests(
        device=device,
        request_type=PeriodicRequestType.DEVICE_INFO,
        period_seconds=40,
    )

    # Send initial requests for both types
    print("\nSending initial requests for both types...")
    await mqtt.request_device_status(device)
    await asyncio.sleep(1)  # Small delay between requests
    await mqtt.request_device_info(device)

    print("\nMonitoring for 2 minutes...")
    print("(Status requests: ~20s, ~40s, ~60s, ~80s, ~100s, ~120s)")
    print("(Info requests: ~40s, ~80s, ~120s)")
    await monitor_with_dots(120, 15)

    print("\n" + "=" * 70)
    print("Example 4: Conditional/Optional Usage")
    print("=" * 70)

    # Demonstrate optional/conditional usage
    enable_periodic = False  # Could come from config

    print(f"\nConditionally starting requests (enabled={enable_periodic})...")
    if enable_periodic:
        await mqtt.start_periodic_requests(
            device=device,
            request_type=PeriodicRequestType.DEVICE_STATUS,
            period_seconds=20,
        )
        print("✓ Periodic requests started")
    else:
        print("✓ Periodic requests not started (disabled by config)")

    print("Waiting 15 seconds (should see no new automatic requests)...")
    await asyncio.sleep(15)

    print("\n" + "=" * 70)
    print("Example 5: Stopping Specific Request Types")
    print("=" * 70)

    # Stop only device info requests
    print("\nStopping device info requests (keeping status requests)...")
    await mqtt.stop_periodic_requests(device, PeriodicRequestType.DEVICE_INFO)

    print("Waiting 25 seconds (should only see status requests)...")
    await asyncio.sleep(25)

    # Stop all requests for the device
    print("\nStopping all periodic requests for device...")
    await mqtt.stop_periodic_requests(device)

    print("Waiting 25 seconds (should see no automatic requests)...")
    await asyncio.sleep(25)

    # Cleanup
    print("\n6. Disconnecting...")
    await mqtt.disconnect()
    print("   Disconnected (all periodic tasks stopped automatically)")

    print(f"\n{'=' * 70}")
    print("Summary:")
    print(f"  Status responses received: {status_count}")
    print(f"  Device info responses received: {info_count}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception:
        import logging

        logging.exception("Error running periodic_requests example")
        sys.exit(1)
