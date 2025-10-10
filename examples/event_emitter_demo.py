#!/usr/bin/env python3
"""
Event Emitter Pattern Demonstration.

This script demonstrates the event-driven architecture with automatic
state change detection. Shows how multiple independent listeners can
react to device events without tight coupling.

Features demonstrated:
1. Multiple listeners per event
2. State change detection (temperature, mode, power)
3. Event-driven architecture
4. Async handler support
5. One-time listeners
6. Dynamic listener management

Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables before running.
"""

import asyncio
import logging
import os
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient
from nwp500.models import DeviceStatus, OperationMode


# Example 1: Multiple listeners for the same event
def log_temperature(old_temp: float, new_temp: float):
    """Logger for temperature changes."""
    print(f"📊 [Logger] Temperature: {old_temp}°F → {new_temp}°F")


def alert_on_high_temp(old_temp: float, new_temp: float):
    """Alert handler for high temperatures."""
    if new_temp > 145:
        print(f"⚠️  [Alert] HIGH TEMPERATURE: {new_temp}°F!")


async def save_temperature_to_db(old_temp: float, new_temp: float):
    """Async database saver (simulated)."""
    # Simulate async database operation
    await asyncio.sleep(0.1)
    print(f"💾 [Database] Saved temperature change: {new_temp}°F")


# Example 2: Mode change handlers
def log_mode_change(old_mode: OperationMode, new_mode: OperationMode):
    """Log operation mode changes."""
    print(f"🔄 [Mode] Changed from {old_mode.name} to {new_mode.name}")


def optimize_on_mode_change(old_mode: OperationMode, new_mode: OperationMode):
    """Optimization handler."""
    if new_mode == OperationMode.HEAT_PUMP_ONLY:
        print("♻️  [Optimizer] Heat pump mode - maximum efficiency!")
    elif new_mode == OperationMode.HIGH_DEMAND:
        print("⚡ [Optimizer] High demand mode - fast recovery!")


# Example 3: Power state handlers
def on_heating_started(status: DeviceStatus):
    """Handler for when heating starts."""
    print(f"🔥 [Power] Heating STARTED - Power: {status.currentInstPower}W")


def on_heating_stopped(status: DeviceStatus):
    """Handler for when heating stops."""
    print("💤 [Power] Heating STOPPED")


# Example 4: Error handlers
def on_error_detected(error_code: str, status: DeviceStatus):
    """Handler for error detection."""
    print(f"❌ [Error] ERROR DETECTED: {error_code}")
    print(f"   Temperature: {status.dhwTemperature}°F")
    print(f"   Mode: {status.operationMode}")


def on_error_cleared(error_code: str):
    """Handler for error cleared."""
    print(f"✅ [Error] ERROR CLEARED: {error_code}")


# Example 5: Connection state handlers
def on_connection_interrupted(error):
    """Handler for connection interruption."""
    print(f"🔌 [Connection] DISCONNECTED: {error}")


def on_connection_resumed(return_code, session_present):
    """Handler for connection resumption."""
    print(f"🔌 [Connection] RECONNECTED (code: {return_code})")


async def main():
    """Main demonstration function."""

    # Get credentials
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("❌ Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return False

    print("=" * 70)
    print("Event Emitter Pattern Demonstration")
    print("=" * 70)
    print()

    try:
        # Step 1: Authenticate
        print("1. Authenticating...")
        async with NavienAuthClient(email, password) as auth_client:
            print(f"   ✅ Authenticated as: {auth_client.current_user.full_name}")
            print()

            # Get devices
            api_client = NavienAPIClient(auth_client=auth_client)
            devices = await api_client.list_devices()

            if not devices:
                print("   ❌ No devices found")
                return False

            device = devices[0]
            print(f"   ✅ Device: {device.device_info.device_name}")
            print()

            # Step 2: Create MQTT client (inherits EventEmitter)
            print("2. Creating MQTT client with event emitter...")
            mqtt_client = NavienMqttClient(auth_client)
            print("   ✅ Client created")
            print()

            # Step 3: Register event listeners BEFORE connecting
            print("3. Registering event listeners...")

            # Temperature change - multiple handlers
            mqtt_client.on("temperature_changed", log_temperature)
            mqtt_client.on("temperature_changed", alert_on_high_temp)
            mqtt_client.on("temperature_changed", save_temperature_to_db)
            print("   ✅ Registered 3 temperature change handlers")

            # Mode change - multiple handlers
            mqtt_client.on("mode_changed", log_mode_change)
            mqtt_client.on("mode_changed", optimize_on_mode_change)
            print("   ✅ Registered 2 mode change handlers")

            # Power state changes
            mqtt_client.on("heating_started", on_heating_started)
            mqtt_client.on("heating_stopped", on_heating_stopped)
            print("   ✅ Registered heating start/stop handlers")

            # Error handling
            mqtt_client.on("error_detected", on_error_detected)
            mqtt_client.on("error_cleared", on_error_cleared)
            print("   ✅ Registered error handlers")

            # Connection state
            mqtt_client.on("connection_interrupted", on_connection_interrupted)
            mqtt_client.on("connection_resumed", on_connection_resumed)
            print("   ✅ Registered connection handlers")

            # One-time listener example
            mqtt_client.once(
                "status_received",
                lambda s: print(f"   🎉 First status received: {s.dhwTemperature}°F"),
            )
            print("   ✅ Registered one-time status handler")
            print()

            # Show listener counts
            print("4. Listener statistics:")
            print(
                f"   temperature_changed: {mqtt_client.listener_count('temperature_changed')} listeners"
            )
            print(
                f"   mode_changed: {mqtt_client.listener_count('mode_changed')} listeners"
            )
            print(
                f"   heating_started: {mqtt_client.listener_count('heating_started')} listeners"
            )
            print(f"   Total events registered: {len(mqtt_client.event_names())}")
            print()

            # Step 4: Connect and subscribe
            print("5. Connecting to MQTT...")
            await mqtt_client.connect()
            print("   ✅ Connected!")
            print()

            print("6. Subscribing to device status...")
            # We pass a dummy callback since we're using events
            await mqtt_client.subscribe_device_status(device, lambda s: None)
            print("   ✅ Subscribed - events will now be emitted")
            print()

            # Step 5: Request initial status
            print("7. Requesting initial status...")
            await mqtt_client.request_device_status(device)
            print("   ✅ Request sent")
            print()

            # Step 6: Monitor for changes
            print("8. Monitoring for state changes (60 seconds)...")
            print("   (Change temperature or mode in the app to see events)")
            print()
            print("-" * 70)

            await asyncio.sleep(60)

            print()
            print("-" * 70)
            print()

            # Step 7: Show event statistics
            print("9. Event statistics:")
            print(
                f"   temperature_changed: emitted {mqtt_client.event_count('temperature_changed')} times"
            )
            print(
                f"   mode_changed: emitted {mqtt_client.event_count('mode_changed')} times"
            )
            print(
                f"   status_received: emitted {mqtt_client.event_count('status_received')} times"
            )
            print()

            # Step 8: Dynamic listener management
            print("10. Demonstrating dynamic listener removal...")
            print(
                f"    Before: {mqtt_client.listener_count('temperature_changed')} listeners"
            )

            # Remove one listener
            mqtt_client.off("temperature_changed", alert_on_high_temp)
            print(
                f"    After removing alert: {mqtt_client.listener_count('temperature_changed')} listeners"
            )

            # Add it back
            mqtt_client.on("temperature_changed", alert_on_high_temp)
            print(
                f"    After adding back: {mqtt_client.listener_count('temperature_changed')} listeners"
            )
            print()

            # Step 9: Cleanup
            print("11. Disconnecting...")
            await mqtt_client.disconnect()
            print("    ✅ Disconnected cleanly")
            print()

        print("=" * 70)
        print("✅ Event Emitter Demo Complete!")
        print()
        print("Key Features Demonstrated:")
        print("  • Multiple listeners per event")
        print("  • Automatic state change detection")
        print("  • Async handler support")
        print("  • One-time listeners")
        print("  • Dynamic listener management")
        print("  • Event statistics and monitoring")
        print("=" * 70)

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
