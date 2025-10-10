#!/usr/bin/env python3
"""
Example: Using the Navien API Client

This example demonstrates how to use the NavienAPIClient to interact with
the Navien Smart Control API and retrieve device information.
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

# If running from examples directory, add parent to path
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nwp500 import NavienAPIClient
from nwp500.api_client import APIError
from nwp500.auth import AuthenticationError, NavienAuthClient

import re


def mask_mac(mac: str) -> str:
    """Redact all MAC addresses in the input string."""
    mac_regex = r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|([0-9A-Fa-f]{12})"
    return re.sub(mac_regex, "[REDACTED_MAC]", mac)


async def example_basic_usage():
    """Basic usage example."""

    # Get credentials from environment variables
    email = os.getenv("NAVIEN_EMAIL", "your_email@example.com")
    password = os.getenv("NAVIEN_PASSWORD", "your_password")

    print("=" * 70)
    print("Navien API Client - Basic Usage Example")
    print("=" * 70)
    print()

    try:
        # Create auth client and authenticate
        async with NavienAuthClient(email, password) as auth_client:
            # Already authenticated!
            print("✅ Authenticated successfully\n")

            # Create API client with authenticated auth_client
            client = NavienAPIClient(auth_client=auth_client)

            # List all devices
            print("📱 Retrieving devices...")
            devices = await client.list_devices()
            print(f"✅ Found {len(devices)} device(s)\n")

            # Display device information
            try:
                from examples.mask import mask_mac  # type: ignore
            except Exception:
                # fallback helper if import fails when running examples directly

                def mask_mac(mac: str) -> str:  # pragma: no cover - small fallback
                    # Always return "[REDACTED_MAC]" regardless of input for safety
                    return "[REDACTED_MAC]"

            try:
                from examples.mask import mask_any, mask_location  # type: ignore
            except Exception:

                def mask_any(_):
                    return "[REDACTED]"

                def mask_location(_, __):
                    return "[REDACTED_LOCATION]"

            for i, device in enumerate(devices, 1):
                info = device.device_info
                loc = device.location

                print(f"Device {i}: {info.device_name}")
                print(f"  MAC Address: {mask_mac(info.mac_address)}")
                print(f"  Type: {mask_any(info.device_type)}")
                print(f"  Connection Status: {info.connected}")

                loc_mask = mask_location(loc.city, loc.state)
                if loc_mask:
                    print(f"  Location: {loc_mask}")
                if loc.address:
                    print("  Address: [REDACTED]")
                print()

            # Get detailed info for first device
            if devices:
                device = devices[0]
                mac = device.device_info.mac_address
                additional = device.device_info.additional_value

                print("📊 Getting detailed device information...")
                detailed_info = await client.get_device_info(mac, additional)

                print(f"✅ Detailed info for: {detailed_info.device_info.device_name}")
                if detailed_info.device_info.install_type:
                    print(f"  Install Type: {detailed_info.device_info.install_type}")
                if detailed_info.location.latitude:
                    print("  Coordinates: (available, not shown for privacy)")
                print()

                # Get firmware information
                print("🔧 Getting firmware information...")
                firmware_list = await client.get_firmware_info(mac, additional)
                print(f"✅ Found {len(firmware_list)} firmware components")

                for fw in firmware_list:
                    print(f"  SW Code: {fw.cur_sw_code}, Version: {fw.cur_version}")
                print()

        print("=" * 70)
        print("✅ Example completed successfully!")
        print("=" * 70)
        return 0

    except AuthenticationError as e:
        print(f"\n❌ Authentication failed: {e.message}")
        print("\nPlease set environment variables:")
        print("  export NAVIEN_EMAIL='your_email@example.com'")
        print("  export NAVIEN_PASSWORD='your_password'")
        return 1

    except APIError as e:
        print(f"\n❌ API error: {e.message}")
        if e.code:
            print(f"   Error code: {e.code}")
        return 1

    except Exception:
        # Avoid printing raw exception details to stdout in examples
        logging.exception("Unexpected error in api_client_example")
        return 1


async def example_convenience_function():
    """Example using the convenience function."""

    email = os.getenv("NAVIEN_EMAIL", "your_email@example.com")
    password = os.getenv("NAVIEN_PASSWORD", "your_password")

    print()
    print("=" * 70)
    print("Navien API Client - Convenience Function Example")
    print("=" * 70)
    print()

    try:
        # Use convenience function for quick device listing
        print("📱 Getting devices with convenience function...")
        async with NavienAuthClient(email, password) as auth_client:
            api_client = NavienAPIClient(auth_client=auth_client)
            devices = await api_client.list_devices()

            print(f"✅ Found {len(devices)} device(s):\n")

            try:
                from examples.mask import mask_any, mask_location  # type: ignore
            except Exception:

                def mask_any(_):
                    return "[REDACTED]"

                def mask_location(_, __):
                    return "[REDACTED_LOCATION]"

            for device in devices:
                print(f"  • {device.device_info.device_name}")
                print(f"    MAC: {mask_mac(device.device_info.mac_address)}")
                print(f"    Type: {mask_any(device.device_info.device_type)}")
                loc_mask = mask_location(device.location.city, device.location.state)
                if loc_mask:
                    print(f"    Location: {loc_mask}")
                print()

        return 0

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return 1


async def example_error_handling():
    """Example showing error handling."""

    email = os.getenv("NAVIEN_EMAIL", "your_email@example.com")
    password = os.getenv("NAVIEN_PASSWORD", "your_password")

    print()
    print("=" * 70)
    print("Navien API Client - Error Handling Example")
    print("=" * 70)
    print()

    async with NavienAuthClient(email, password) as auth_client:
        client = NavienAPIClient(auth_client=auth_client)

        # Example 1: Handling API errors
        print("Example 1: Handling API errors")
        print("-" * 70)
        try:
            # Try to get info for non-existent device
            await client.get_device_info("invalid_mac_address", "invalid")
        except APIError as e:
            print("✅ Caught APIError as expected:")
            print(f"   Message: {e.message}")
            print(f"   Code: {e.code}")
        print()

        # Example 2: Handling authentication errors
        print("Example 2: Authentication check")
        print("-" * 70)
        if client.is_authenticated:
            print("✅ Client is authenticated")
            print(f"   User: {client.user_email}")
        else:
            print("❌ Client is not authenticated")
        print()


def main():
    """Main entry point."""

    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--convenience":
            exit_code = asyncio.run(example_convenience_function())
        elif sys.argv[1] == "--errors":
            exit_code = asyncio.run(example_error_handling())
        else:
            print(f"Unknown option: {sys.argv[1]}")
            print("Usage: python api_client_example.py [--convenience|--errors]")
            exit_code = 1
    else:
        exit_code = asyncio.run(example_basic_usage())

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
