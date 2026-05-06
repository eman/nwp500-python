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

from nwp500 import (
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
    MqttClientEvents,
    CurrentOperationMode,
)


# Example 1: Multiple listeners for the same event
def log_temperature(event):
    """Logger for temperature changes."""
    print(f"📊 [Logger] Temperature: {event.old_temperature} → {event.new_temperature}")


def alert_on_high_temp(event):
    """Alert handler for high temperatures."""
    if event.new_temperature > 145:
        print(f"[WARNING]  [Alert] HIGH TEMPERATURE: {event.new_temperature}!")


async def save_temperature_to_db(event):
    """Async database saver (simulated)."""
    # Simulate async database operation
    await asyncio.sleep(0.1)
    print(f"💾 [Database] Saved temperature change: {event.new_temperature}")


# Example 2: Mode change handlers
def log_mode_change(event):
    """Log operation mode changes."""
    print(f"🔄 [Mode] Changed from {event.old_mode.name} to {event.new_mode.name}")


def optimize_on_mode_change(event):
    """Optimization handler."""
    if event.new_mode == CurrentOperationMode.HEAT_PUMP_MODE:
        print("♻️  [Optimizer] Heat pump mode - maximum efficiency!")
    elif event.new_mode == CurrentOperationMode.HYBRID_EFFICIENCY_MODE:
        print("⚡ [Optimizer] Energy Saver mode - balanced performance!")
    elif event.new_mode == CurrentOperationMode.HYBRID_BOOST_MODE:
        print("⚡ [Optimizer] High Demand mode - fast recovery!")


# Example 3: Power state handlers
def on_heating_started(event):
    """Handler for when heating starts."""
    print(f"🔥 [Power] Heating STARTED - Power: {event.status.current_inst_power}W")


def on_heating_stopped(event):
    """Handler for when heating stops."""
    print("💤 [Power] Heating STOPPED")


# Example 4: Error handlers
def on_error_detected(event):
    """Handler for error detection."""
    print(f"[ERROR] [Error] ERROR DETECTED: {event.error_code}")
    unit = event.status.get_field_unit("dhw_temperature")
    print(f"   Temperature: {event.status.dhw_temperature}{unit}")
    print(f"   Mode: {event.status.operation_mode}")


def on_error_cleared(event):
    """Handler for error cleared."""
    print(f"[SUCCESS] [Error] ERROR CLEARED: {event.error_code}")


# Example 5: Connection state handlers
def on_connection_interrupted(event):
    """Handler for connection interruption."""
    print(f"🔌 [Connection] DISCONNECTED: {event.error}")


def on_connection_resumed(event):
    """Handler for connection resumption."""
    print(f"🔌 [Connection] RECONNECTED (code: {event.return_code})")


async def main():
    """Main demonstration function."""

    # Get credentials
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print(
            "[ERROR] Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables"
        )
        return False

    print("=" * 70)
    print("Event Emitter Pattern Demonstration")
    print("=" * 70)
    print()

    try:
        # Step 1: Authenticate
        print("1. Authenticating...")
        async with NavienAuthClient(email, password) as auth_client:
            print(
                f"   [SUCCESS] Authenticated as: {auth_client.current_user.full_name}"
            )
            print()

            # Get devices
            api_client = NavienAPIClient(auth_client=auth_client)
            devices = await api_client.list_devices()

            if not devices:
                print("   [ERROR] No devices found")
                return False

            device = devices[0]
            print(f"   [SUCCESS] Device: {device.device_info.device_name}")
            print()

            # Step 2: Create MQTT client (inherits EventEmitter)
            print("2. Creating MQTT client with event emitter...")
            mqtt_client = NavienMqttClient(auth_client)
            print("   [SUCCESS] Client created")
            print()

            # Step 3: Register event listeners BEFORE connecting
            print("3. Registering event listeners...")
            print("   (Using MqttClientEvents for type-safe event constants)")

            # Temperature change - multiple handlers
            mqtt_client.on(MqttClientEvents.TEMPERATURE_CHANGED, log_temperature)
            mqtt_client.on(MqttClientEvents.TEMPERATURE_CHANGED, alert_on_high_temp)
            mqtt_client.on(MqttClientEvents.TEMPERATURE_CHANGED, save_temperature_to_db)
            print("   [SUCCESS] Registered 3 temperature change handlers")

            # Mode change - multiple handlers
            mqtt_client.on(MqttClientEvents.MODE_CHANGED, log_mode_change)
            mqtt_client.on(MqttClientEvents.MODE_CHANGED, optimize_on_mode_change)
            print("   [SUCCESS] Registered 2 mode change handlers")

            # Power state changes
            mqtt_client.on(MqttClientEvents.HEATING_STARTED, on_heating_started)
            mqtt_client.on(MqttClientEvents.HEATING_STOPPED, on_heating_stopped)
            print("   [SUCCESS] Registered heating start/stop handlers")

            # Error handling
            mqtt_client.on(MqttClientEvents.ERROR_DETECTED, on_error_detected)
            mqtt_client.on(MqttClientEvents.ERROR_CLEARED, on_error_cleared)
            print("   [SUCCESS] Registered error handlers")

            # Connection state
            mqtt_client.on(
                MqttClientEvents.CONNECTION_INTERRUPTED, on_connection_interrupted
            )
            mqtt_client.on(MqttClientEvents.CONNECTION_RESUMED, on_connection_resumed)
            print("   [SUCCESS] Registered connection handlers")

            # One-time listener example
            mqtt_client.once(
                MqttClientEvents.STATUS_RECEIVED,
                lambda event: print(
                    f"   🎉 First status received: {event.status.dhw_temperature}{event.status.get_field_unit('dhw_temperature')}"
                ),
            )
            print("   [SUCCESS] Registered one-time status handler")
            print()

            # Show listener counts
            print("4. Listener statistics:")
            print(
                f"   {MqttClientEvents.TEMPERATURE_CHANGED}: {mqtt_client.listener_count(MqttClientEvents.TEMPERATURE_CHANGED)} listeners"
            )
            print(
                f"   {MqttClientEvents.MODE_CHANGED}: {mqtt_client.listener_count(MqttClientEvents.MODE_CHANGED)} listeners"
            )
            print(
                f"   {MqttClientEvents.HEATING_STARTED}: {mqtt_client.listener_count(MqttClientEvents.HEATING_STARTED)} listeners"
            )
            print(f"   Total events registered: {len(mqtt_client.event_names())}")
            print()
            print(
                f"   Available events: {', '.join(MqttClientEvents.get_all_events())}"
            )
            print()

            # Step 4: Connect and subscribe
            print("5. Connecting to MQTT...")
            await mqtt_client.connect()
            print("   [SUCCESS] Connected!")
            print()

            print("6. Subscribing to device status...")
            # We pass a dummy callback since we're using events
            await mqtt_client.subscribe_device_status(device, lambda s: None)
            print("   [SUCCESS] Subscribed - events will now be emitted")
            print()

            # Step 5: Request initial status
            print("7. Requesting initial status...")
            await mqtt_client.control.request_device_status(device)
            print("   [SUCCESS] Request sent")
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
                f"   {MqttClientEvents.TEMPERATURE_CHANGED}: emitted {mqtt_client.event_count(MqttClientEvents.TEMPERATURE_CHANGED)} times"
            )
            print(
                f"   {MqttClientEvents.MODE_CHANGED}: emitted {mqtt_client.event_count(MqttClientEvents.MODE_CHANGED)} times"
            )
            print(
                f"   {MqttClientEvents.STATUS_RECEIVED}: emitted {mqtt_client.event_count(MqttClientEvents.STATUS_RECEIVED)} times"
            )
            print()

            # Step 8: Dynamic listener management
            print("10. Demonstrating dynamic listener removal...")
            print(
                f"    Before: {mqtt_client.listener_count(MqttClientEvents.TEMPERATURE_CHANGED)} listeners"
            )

            # Remove one listener
            mqtt_client.off(MqttClientEvents.TEMPERATURE_CHANGED, alert_on_high_temp)
            print(
                f"    After removing alert: {mqtt_client.listener_count(MqttClientEvents.TEMPERATURE_CHANGED)} listeners"
            )

            # Add it back
            mqtt_client.on(MqttClientEvents.TEMPERATURE_CHANGED, alert_on_high_temp)
            print(
                f"    After adding back: {mqtt_client.listener_count(MqttClientEvents.TEMPERATURE_CHANGED)} listeners"
            )
            print()

            # Step 9: Cleanup
            print("11. Disconnecting...")
            await mqtt_client.disconnect()
            print("    [SUCCESS] Disconnected cleanly")
            print()

        print("=" * 70)
        print("[SUCCESS] Event Emitter Demo Complete!")
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
        print(f"\n[ERROR] Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
