#!/usr/bin/env python3
"""
Example: Device Feature Callback with DeviceFeature Dataclass

This example demonstrates:
1. Using the subscribe_device_feature() method for automatic parsing
2. Receiving DeviceFeature objects directly in the callback
3. Accessing typed device capabilities and configuration fields

Requirements:
- Set environment variables: NAVIEN_EMAIL and NAVIEN_PASSWORD
- Have at least one device registered in your account
"""

import asyncio
import logging
import os
import sys

# Setup logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("nwp500.mqtt_client").setLevel(logging.INFO)
logging.getLogger("nwp500.auth").setLevel(logging.INFO)
logging.getLogger("nwp500.api_client").setLevel(logging.INFO)

# If running from examples directory, add parent to path
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500.api_client import NavienAPIClient
from nwp500.auth import NavienAuthClient
from nwp500.enums import OnOffFlag
from nwp500.exceptions import AuthenticationError
from nwp500.models import DeviceFeature
from nwp500.mqtt_client import NavienMqttClient

try:
    from examples.mask import mask_mac  # type: ignore
except Exception:

    def mask_mac(mac):  # pragma: no cover - fallback
        return "[REDACTED_MAC]"


async def main():
    """Main example function."""

    # Get credentials from environment variables
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print(
            "[ERROR] Error: Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables"
        )
        print("\nExample:")
        print("  export NAVIEN_EMAIL='your_email@example.com'")
        print("  export NAVIEN_PASSWORD='your_password'")
        return 1

    print("=" * 70)
    print("Device Feature Callback Example - Parsed DeviceFeature Objects")
    print("=" * 70)
    print()

    try:
        # Step 1: Authenticate and get AWS credentials
        print("Step 1: Authenticating with Navien API...")
        async with NavienAuthClient(email, password) as auth_client:
            print(f"[SUCCESS] Authenticated as: {auth_client.current_user.full_name}")
            print()

            # Step 2: Get device list
            print("Step 2: Fetching device list...")
            api_client = NavienAPIClient(
                auth_client=auth_client, session=auth_client._session
            )
            devices = await api_client.list_devices()

            if not devices:
                print("[ERROR] Error: No devices found in your account")
                return 1

            device = devices[0]
            device_id = device.device_info.mac_address
            device_type = device.device_info.device_type

            print(f"[SUCCESS] Using device: {device.device_info.device_name}")
            print(f"   MAC Address: {mask_mac(device_id)}")
            print()

            # Step 3: Create MQTT client and connect
            print("Step 3: Connecting to AWS IoT via MQTT...")
            mqtt_client = NavienMqttClient(auth_client)

            try:
                await mqtt_client.connect()
                print("[SUCCESS] Connected to AWS IoT Core")
                print()

                # Step 4: Subscribe to device feature with automatic parsing
                print("Step 4: Subscribing to device feature updates...")

                feature_count = {"count": 0}

                def on_device_feature(feature: DeviceFeature):
                    """
                    Callback that receives parsed DeviceFeature objects.

                    This callback is automatically invoked when a feature
                    message is received and successfully parsed into a
                    DeviceFeature object.
                    """
                    feature_count["count"] += 1
                    print(f"\n📋 Device Feature Information #{feature_count['count']}")
                    print("=" * 60)

                    # Access typed feature fields directly
                    print("Device Identity:")
                    print(f"  Serial Number:      {feature.controller_serial_number}")
                    print(f"  Country Code:       {feature.country_code}")
                    print(f"  Model Type:         {feature.model_type_code}")
                    print(f"  Control Type:       {feature.control_type_code}")
                    print(f"  Volume Code:        {feature.volume_code}")

                    print("\nFirmware Versions:")
                    print(
                        f"  Controller SW:      {feature.controller_sw_version} (code: {feature.controller_sw_code})"
                    )
                    print(
                        f"  Panel SW:           {feature.panel_sw_version} (code: {feature.panel_sw_code})"
                    )
                    print(
                        f"  WiFi SW:            {feature.wifi_sw_version} (code: {feature.wifi_sw_code})"
                    )

                    print("\nConfiguration:")
                    print(f"  Temperature Unit:   {feature.temperature_type.name}")
                    print(f"  Temp Formula Type:  {feature.temp_formula_type}")
                    print(
                        f"  DHW Temp Range:     {feature.dhw_temperature_min}°F - {feature.dhw_temperature_max}°F"
                    )
                    print(
                        f"  Freeze Prot Range:  {feature.freeze_protection_temp_min}°F - {feature.freeze_protection_temp_max}°F"
                    )

                    print("\nFeature Support:")
                    print(
                        f"  Power Control:      {'Yes' if feature.power_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  DHW Control:        {'Yes' if feature.dhw_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  DHW Temp Setting:   Level {feature.dhw_temperature_setting_use}"
                    )
                    print(
                        f"  Heat Pump Mode:     {'Yes' if feature.heatpump_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  Electric Mode:      {'Yes' if feature.electric_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  Energy Saver:       {'Yes' if feature.energy_saver_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  High Demand:        {'Yes' if feature.high_demand_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  Eco Mode:           {'Yes' if feature.eco_use == OnOffFlag.ON else 'No'}"
                    )

                    print("\nAdvanced Features:")
                    print(
                        f"  Holiday Mode:       {'Yes' if feature.holiday_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  Program Schedule:   {'Yes' if feature.program_reservation_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  Smart Diagnostic:   {'Yes' if feature.smart_diagnostic_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  WiFi RSSI:          {'Yes' if feature.wifi_rssi_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  Energy Usage:       {'Yes' if feature.energy_usage_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  Freeze Protection:  {'Yes' if feature.freeze_protection_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  Mixing Valve:       {'Yes' if feature.mixing_value_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  DR Settings:        {'Yes' if feature.dr_setting_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  Anti-Legionella:    {'Yes' if feature.anti_legionella_setting_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  HPWH:               {'Yes' if feature.hpwh_use == OnOffFlag.ON else 'No'}"
                    )
                    print(
                        f"  DHW Refill:         {'Yes' if feature.dhw_refill_use == OnOffFlag.ON else 'No'}"
                    )

                    print("=" * 60)

                # Subscribe to broader topics first to catch all messages
                device_topic = f"navilink-{device_id}"

                # Subscribe to all command and event messages
                await mqtt_client.subscribe(
                    f"cmd/{device_type}/{device_topic}/#",
                    lambda topic, msg: None,  # Will be handled by typed callback
                )
                await mqtt_client.subscribe(
                    f"evt/{device_type}/{device_topic}/#",
                    lambda topic, msg: None,  # Will be handled by typed callback
                )

                # Subscribe with automatic parsing
                await mqtt_client.subscribe_device_feature(device, on_device_feature)
                print("[SUCCESS] Subscribed to device features with automatic parsing")
                print()

                # Step 5: Request device info to get feature data
                print("Step 5: Requesting device information...")
                await mqtt_client.signal_app_connection(device)
                await asyncio.sleep(1)

                await mqtt_client.request_device_info(device)
                print("[SUCCESS] Device info request sent")
                print()

                # Wait for feature message
                print("⏳ Waiting for device feature data (10 seconds)...")
                print("   Press Ctrl+C to stop earlier")
                try:
                    await asyncio.sleep(10)
                except KeyboardInterrupt:
                    print("\n[WARNING]  Interrupted by user")

                print()
                print(
                    f"📊 Summary: Received {feature_count['count']} feature message(s)"
                )
                print()

                # Disconnect
                print("Step 6: Disconnecting from AWS IoT...")
                await mqtt_client.disconnect()
                print("[SUCCESS] Disconnected successfully")

            except Exception:
                import logging

                logging.exception("MQTT error in device_feature_callback")

                if mqtt_client.is_connected:
                    await mqtt_client.disconnect()

                return 1

        print()
        print("=" * 70)
        print("[SUCCESS] Device Feature Callback Example Completed Successfully!")
        print("=" * 70)
        return 0

    except AuthenticationError as e:
        print(f"\n[ERROR] Authentication failed: {e.message}")
        if e.code:
            print(f"   Error code: {e.code}")
        return 1

    except Exception:
        import logging

        logging.exception("Unexpected error in device_feature_callback")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
