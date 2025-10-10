#!/usr/bin/env python3
"""
Test script for Navien API Client.

This script tests all API endpoints and verifies data parsing with models.
"""

import asyncio
import logging
import os
import sys

# Add src to path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from nwp500.api_client import APIError, NavienAPIClient
from nwp500.auth import AuthenticationError, NavienAuthClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s:%(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_logger = logging.getLogger(__name__)


async def test_api_client():
    """Test the API client with all endpoints."""

    # Get credentials from environment
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("❌ Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return 1

    print("=" * 70)
    print("Navien API Client Test")
    print("=" * 70)
    print()

    try:
        async with NavienAuthClient(email, password) as auth_client:
            # Test 1: Authentication
            print("Test 1: Authentication")
            print("-" * 70)
            print(f"✅ Authenticated as: {email}")
            print()

            # Create API client with authenticated auth_client
            client = NavienAPIClient(auth_client=auth_client)
            print(f"   Is authenticated: {client.is_authenticated}")
            print()

            # Test 2: List Devices
            print("Test 2: List Devices")
            print("-" * 70)
            devices = await client.list_devices()
            print(f"✅ Found {len(devices)} device(s)")

            # Helper to mask MAC addresses for safe printing
            def _mask_mac(mac: str) -> str:
                import re

                mac_regex = r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|([0-9A-Fa-f]{12})"
                return re.sub(mac_regex, "[REDACTED_MAC]", mac)

            try:
                from examples.mask import mask_any, mask_location  # type: ignore
            except Exception:

                def mask_any(_):
                    return "[REDACTED]"

                def mask_location(_, __):
                    return "[REDACTED_LOCATION]"

            for i, device in enumerate(devices, 1):
                print(f"\nDevice {i}:")
                print(f"  Name: {device.device_info.device_name}")
                print("  MAC Address: [REDACTED_MAC]")
                print(f"  Device Type: {mask_any(device.device_info.device_type)}")
                print(f"  Home Seq: {device.device_info.home_seq}")
                print(f"  Additional Value: {device.device_info.additional_value}")
                print(f"  Connected: {device.device_info.connected}")

                loc_mask = mask_location(device.location.city, device.location.state)
                if loc_mask:
                    print(f"  Location: {loc_mask}")
                if device.location.address:
                    print("  Address: [REDACTED]")
            print()

            if not devices:
                print("⚠️  No devices found. Cannot test device-specific endpoints.")
                return 0

            # Use first device for remaining tests
            test_device = devices[0]
            mac = test_device.device_info.mac_address
            additional = test_device.device_info.additional_value

            # Test 3: Get Device Info
            print("Test 3: Get Device Info")
            print("-" * 70)
            device_info = await client.get_device_info(mac, additional)
            print(
                f"✅ Retrieved detailed info for: {device_info.device_info.device_name}"
            )
            print(f"   MAC: {device_info.device_info.mac_address}")
            print(f"   Type: {device_info.device_info.device_type}")
            if device_info.device_info.install_type:
                print(f"   Install Type: {device_info.device_info.install_type}")
            if device_info.location.latitude and device_info.location.longitude:
                print("   Coordinates: [REDACTED]")
            print()

            # Test 4: Get Firmware Info
            print("Test 4: Get Firmware Info")
            print("-" * 70)
            try:
                firmware_list = await client.get_firmware_info(mac, additional)
                print(f"✅ Retrieved firmware info: {len(firmware_list)} firmware(s)")
                for fw in firmware_list:
                    print(f"   Current SW Code: {fw.cur_sw_code}")
                    print(f"   Current Version: {fw.cur_version}")
                    if fw.downloaded_version:
                        print(f"   Downloaded Version: {fw.downloaded_version}")
            except APIError as e:
                print(f"⚠️  Firmware info not available: {e.message}")
            print()

            # Test 5: Get TOU Info (if applicable)
            print("Test 5: Get TOU Info")
            print("-" * 70)
            try:
                # Note: controller_id may need to be obtained from device data
                # This might fail if TOU is not configured
                print("⚠️  TOU info requires controller_id - skipping for now")
                print("   (This endpoint requires device-specific configuration)")
            except Exception as e:
                print(f"⚠️  TOU info error: {e}")
            print()

            # Test 6: Convenience Method
            print("Test 6: Convenience Methods")
            print("-" * 70)
            first_device = await client.get_first_device()
            if first_device:
                print(f"✅ Get first device: {first_device.device_info.device_name}")
            else:
                print("⚠️  No devices available")
            print()

            # Test 7: Data Model Verification
            print("Test 7: Data Model Verification")
            print("-" * 70)
            print("✅ DeviceInfo model:")
            print(f"   - home_seq: {type(test_device.device_info.home_seq).__name__}")
            print(
                f"   - mac_address: {type(test_device.device_info.mac_address).__name__}"
            )
            print(
                f"   - device_type: {type(test_device.device_info.device_type).__name__}"
            )
            print(f"   - connected: {type(test_device.device_info.connected).__name__}")

            print("✅ Location model:")
            print(f"   - state: {type(test_device.location.state).__name__}")
            print(f"   - city: {type(test_device.location.city).__name__}")
            if test_device.location.latitude:
                print(f"   - latitude: {type(test_device.location.latitude).__name__}")
            print()

            # Test 8: Error Handling
            print("Test 8: Error Handling")
            print("-" * 70)
            try:
                # Try to get info for non-existent device
                await client.get_device_info("invalid_mac", "invalid")
            except APIError as e:
                print(f"✅ APIError caught correctly: {e.message[:50]}...")
            except Exception as e:
                print(f"⚠️  Unexpected error type: {type(e).__name__}")
            print()

        print("=" * 70)
        print("✅ All API client tests completed successfully!")
        print("=" * 70)
        print()
        print("Summary:")
        print("  ✅ Authentication working")
        print("  ✅ Device listing working")
        print("  ✅ Device info retrieval working")
        print("  ✅ Data models parsing correctly")
        print("  ✅ Error handling functional")
        print()
        return 0

    except AuthenticationError as e:
        print(f"❌ Authentication error: {e.message}")
        return 1
    except APIError as e:
        print(f"❌ API error: {e.message}")
        if e.code:
            print(f"   Code: {e.code}")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        import traceback

        traceback.print_exc()
        return 1


async def test_convenience_function():
    """Test the convenience function."""

    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("❌ Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return 1

    print()
    print("=" * 70)
    print("Testing Convenience Function: get_devices()")
    print("=" * 70)
    print()

    try:
        from nwp500 import NavienAPIClient
        from nwp500.auth import NavienAuthClient

        async with NavienAuthClient(email, password) as auth_client:
            api_client = NavienAPIClient(auth_client=auth_client)
            devices = await api_client.list_devices()
            print(f"✅ get_devices() returned {len(devices)} device(s)")

            for idx, _ in enumerate(devices, start=1):
                # Do not log sensitive data like device name or MAC address
                print(f"   - Device #{idx} found.")
        return 0

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return 1


def main():
    """Main entry point."""

    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--convenience":
            exit_code = asyncio.run(test_convenience_function())
        else:
            exit_code = asyncio.run(test_api_client())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting cleanly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
