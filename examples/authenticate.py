#!/usr/bin/env python3
"""
Example: Basic Authentication

This example demonstrates how to authenticate with the Navien Smart Control API
and retrieve authentication tokens.
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

from nwp500.auth import (
    AuthenticationError,
    InvalidCredentialsError,
    NavienAuthClient,
)


async def main():
    """Main example function."""

    # Get credentials from environment variables or use defaults
    email = os.getenv("NAVIEN_EMAIL", "your_email@example.com")
    password = os.getenv("NAVIEN_PASSWORD", "your_password")

    print("Navien Authentication Example")
    print("=" * 50)
    print()

    try:
        # Create authentication client
        async with NavienAuthClient(email, password) as client:
            print(f"Authenticating as: {email}")

            # Already authenticated!
            response = client._auth_response

            # Display user information
            print("\n✅ Authentication successful!")
            print("\nUser Information:")
            print(f"  Name: {response.user_info.full_name}")
            print(f"  Status: {response.user_info.user_status}")
            print(f"  Type: {response.user_info.user_type}")
            print(f"  User ID: {response.user_info.user_seq}")

            # Display token information
            tokens = response.tokens
            print("\nToken Information:")
            print(f"  Access Token: {tokens.access_token[:30]}...")
            print(f"  Refresh Token: {tokens.refresh_token[:30]}...")
            print(f"  Expires in: {tokens.authentication_expires_in} seconds")
            print(f"  Time until expiry: {tokens.time_until_expiry}")
            print(f"  Is expired: {tokens.is_expired}")

            # Show how to use the token in API requests
            print("\nCorrect Authorization Headers:")
            auth_headers = client.get_auth_headers()
            print(f"  authorization: {auth_headers['authorization'][:50]}...")
            print("\n⚠️  IMPORTANT: Use lowercase 'authorization' with raw token")
            print("  (no 'Bearer ' prefix). Standard Bearer format will NOT work!")
            print("\n  Correct:   {'authorization': 'eyJraWQi...'}")
            print("  Wrong:     {'Authorization': 'Bearer eyJraWQi...'}")

            # AWS credentials (if available)
            if tokens.access_key_id:
                print("\nAWS Credentials available for IoT/MQTT:")
                print(f"  Access Key ID: {tokens.access_key_id[:15]}...")
                print(
                    f"  Session Token: {tokens.session_token[:30] if tokens.session_token else 'N/A'}..."
                )

    except InvalidCredentialsError as e:
        print(f"\n❌ Invalid credentials: {e.message}")
        print("\nPlease set environment variables:")
        print("  export NAVIEN_EMAIL='your_email@example.com'")
        print("  export NAVIEN_PASSWORD='your_password'")
        return 1

    except AuthenticationError as e:
        print(f"\n❌ Authentication failed: {e.message}")
        if e.code:
            print(f"Error code: {e.code}")
        return 1

    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
