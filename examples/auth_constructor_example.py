"""
Example: Using NavienAuthClient with Automatic Authentication

This example demonstrates how credentials are passed to the constructor
and authentication happens automatically when entering the async context.
"""

import asyncio
import os

from nwp500 import NavienAPIClient, NavienAuthClient


async def main():
    """Demonstrate automatic authentication via constructor."""
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return

    # Pass credentials to constructor - authentication happens automatically
    async with NavienAuthClient(email, password) as auth_client:
        # Already authenticated! No need to call sign_in()
        print(f"✅ Authenticated as: {auth_client.current_user.full_name}")
        print(f"📧 Email: {auth_client.user_email}")
        print(f"🔑 Token expires at: {auth_client.current_tokens.expires_at}")

        # Use with API client
        api_client = NavienAPIClient(auth_client=auth_client)
        devices = await api_client.list_devices()
        print(f"\n📱 Found {len(devices)} device(s)")

        for device in devices:
            print(f"   - {device.device_info.device_name}")


if __name__ == "__main__":
    asyncio.run(main())
