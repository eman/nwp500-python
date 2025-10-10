#!/usr/bin/env python3
"""
Test script to verify MQTT connection functionality.

This script:
1. Authenticates with Navien API
2. Establishes MQTT WebSocket connection to AWS IoT
3. Verifies the connection is working
4. Disconnects cleanly

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

from nwp500.auth import NavienAuthClient
from nwp500.mqtt_client import NavienMqttClient


async def test_mqtt_connection():
    """Test MQTT connection to AWS IoT."""

    # Get credentials
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("❌ Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        return False

    print("Testing MQTT Connection to AWS IoT Core")
    print("=" * 60)

    try:
        # Step 1: Authenticate
        print("\n1. Authenticating with Navien API...")
        async with NavienAuthClient(email, password) as auth_client:
            print(f"   ✅ Authenticated as: {auth_client.current_user.full_name}")

            # Verify AWS credentials
            tokens = auth_client.current_tokens
            if not tokens.access_key_id or not tokens.secret_key:
                print("   ❌ No AWS credentials in response")
                return False

            print(f"   ✅ AWS Access Key ID: {tokens.access_key_id[:15]}...")
            print(
                f"   ✅ AWS Session Token: {'Present' if tokens.session_token else 'None'}"
            )

            # Step 2: Create MQTT client
            print("\n2. Creating MQTT client...")
            mqtt_client = NavienMqttClient(auth_client)
            print(f"   ✅ Client ID: {mqtt_client.client_id}")

            # Step 3: Connect
            print("\n3. Connecting to AWS IoT via WebSocket...")
            await mqtt_client.connect()
            print("   ✅ Connected successfully!")
            print(f"   ✅ Is connected: {mqtt_client.is_connected}")

            # Step 4: Simple verification - wait a moment
            print("\n4. Verifying connection stability...")
            await asyncio.sleep(2)

            if mqtt_client.is_connected:
                print("   ✅ Connection is stable")
            else:
                print("   ❌ Connection lost")
                return False

            # Step 5: Disconnect
            print("\n5. Disconnecting...")
            await mqtt_client.disconnect()
            print("   ✅ Disconnected successfully")
            print(f"   ✅ Is connected: {mqtt_client.is_connected}")

            print("\n" + "=" * 60)
            print("✅ MQTT Connection Test PASSED")
            print("=" * 60)
            return True

    except Exception as e:
        print(f"\n❌ Test FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_mqtt_connection())
    sys.exit(0 if result else 1)
