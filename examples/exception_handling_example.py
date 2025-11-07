#!/usr/bin/env python3
"""
Example: Comprehensive Exception Handling (v5.0+)

This example demonstrates best practices for exception handling with the
new exception architecture introduced in nwp500-python v5.0.

Features demonstrated:
1. Specific exception handling for different error types
2. Using exception attributes (error_code, retriable, etc.)
3. Implementing retry logic with retriable exceptions
4. Structured error logging with to_dict()
5. User-friendly error messages
6. Exception chaining inspection
"""

import asyncio
import json
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

from nwp500 import NavienAPIClient, NavienMqttClient
from nwp500.auth import NavienAuthClient
from nwp500.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    MqttConnectionError,
    MqttError,
    MqttNotConnectedError,
    MqttPublishError,
    Nwp500Error,
    RangeValidationError,
    TokenRefreshError,
    ValidationError,
)

logger = logging.getLogger(__name__)


async def example_authentication_errors():
    """Demonstrate authentication error handling."""
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Authentication Error Handling")
    print("=" * 70)

    # Intentionally use invalid credentials
    try:
        async with NavienAuthClient("invalid@example.com", "wrong_password") as _:
            pass
    except InvalidCredentialsError as e:
        print(f"[OK] Caught InvalidCredentialsError: {e}")
        print(f"  Status code: {e.status_code}")
        print("  Can check credentials and retry")

    except TokenRefreshError as e:
        print(f"[OK] Caught TokenRefreshError: {e}")
        print("  Need to re-authenticate with fresh credentials")

    except AuthenticationError as e:
        print(f"[OK] Caught AuthenticationError: {e}")
        print("  General authentication failure")

    # Show structured error data
    error = InvalidCredentialsError("Invalid email or password", status_code=401)
    print(f"\nStructured error data: {json.dumps(error.to_dict(), indent=2)}")


async def example_mqtt_errors():
    """Demonstrate MQTT error handling."""
    print("\n" + "=" * 70)
    print("EXAMPLE 2: MQTT Error Handling")
    print("=" * 70)

    email = os.getenv("NAVIEN_EMAIL", "your_email@example.com")
    password = os.getenv("NAVIEN_PASSWORD", "your_password")

    if email == "your_email@example.com":
        print("[WARNING]  Set NAVIEN_EMAIL and NAVIEN_PASSWORD to run this example")
        return

    try:
        async with NavienAuthClient(email, password) as auth_client:
            mqtt = NavienMqttClient(auth_client)
            await mqtt.connect()

            # Get first device
            api = NavienAPIClient(auth_client)
            devices = await api.list_devices()
            if not devices:
                print("No devices found")
                return

            device = devices[0]

            # Intentionally disconnect and try to use MQTT
            await mqtt.disconnect()

            try:
                await mqtt.request_device_status(device)
            except MqttNotConnectedError as e:
                print(f"[OK] Caught MqttNotConnectedError: {e}")
                print("  Can reconnect and retry the operation")

    except MqttConnectionError as e:
        print(f"[OK] Caught MqttConnectionError: {e}")
        print(f"  Error code: {e.error_code}")
        print("  Network or AWS IoT connection issue")

    except MqttPublishError as e:
        print(f"[OK] Caught MqttPublishError: {e}")
        if e.retriable:
            print("  [OK] This error is retriable!")
            print("  Can implement exponential backoff retry")

    except MqttError as e:
        print(f"[OK] Caught MqttError (base class): {e}")
        print("  Catches all MQTT-related errors")


async def example_validation_errors():
    """Demonstrate validation error handling."""
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Validation Error Handling")
    print("=" * 70)

    email = os.getenv("NAVIEN_EMAIL", "your_email@example.com")
    password = os.getenv("NAVIEN_PASSWORD", "your_password")

    if email == "your_email@example.com":
        print("[WARNING]  Set NAVIEN_EMAIL and NAVIEN_PASSWORD to run this example")
        return

    try:
        async with NavienAuthClient(email, password) as auth_client:
            mqtt = NavienMqttClient(auth_client)
            await mqtt.connect()

            api = NavienAPIClient(auth_client)
            devices = await api.list_devices()
            if not devices:
                print("No devices found")
                return

            device = devices[0]

            # Try to set invalid vacation days
            try:
                await mqtt.set_dhw_mode(device, mode_id=5, vacation_days=50)
            except RangeValidationError as e:
                print(f"[OK] Caught RangeValidationError: {e}")
                print(f"  Field: {e.field}")
                print(f"  Invalid value: {e.value}")
                print(f"  Valid range: {e.min_value} to {e.max_value}")
                print("  Can show user-friendly error message!")

            except ValidationError as e:
                print(f"[OK] Caught ValidationError (base class): {e}")

            await mqtt.disconnect()

    except Nwp500Error as e:
        print(f"Caught library error: {e}")


async def example_retry_logic():
    """Demonstrate retry logic with retriable exceptions."""
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Retry Logic with Retriable Exceptions")
    print("=" * 70)

    async def operation_with_retry(max_retries=3):
        """Example operation with retry logic."""
        for attempt in range(max_retries):
            try:
                # Simulated operation
                print(f"  Attempt {attempt + 1}/{max_retries}")

                # Create a retriable error for demonstration
                raise MqttPublishError(
                    "Publish cancelled during reconnection",
                    error_code="AWS_ERROR_MQTT_CANCELLED",
                    retriable=True,
                )

            except MqttPublishError as e:
                if e.retriable and attempt < max_retries - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    print(
                        f"  [OK] Retriable error: {e.error_code}, "
                        f"retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    print("  ✗ Max retries reached or not retriable")
                    raise

    try:
        await operation_with_retry()
    except MqttPublishError as e:
        print("\nFinal result: Operation failed after retries")
        print(f"Error: {e}")


async def example_structured_logging():
    """Demonstrate structured error logging."""
    print("\n" + "=" * 70)
    print("EXAMPLE 5: Structured Error Logging")
    print("=" * 70)

    # Create various errors
    errors = [
        MqttConnectionError(
            "AWS IoT connection failed",
            error_code="CONNECTION_TIMEOUT",
            details={"endpoint": "example.iot.amazonaws.com", "port": 443},
        ),
        RangeValidationError(
            "Temperature out of range",
            field="temperature",
            value=200,
            min_value=100,
            max_value=140,
        ),
        MqttPublishError("Publish failed", error_code="MQTT_TIMEOUT", retriable=True),
    ]

    print("\nStructured error data for logging/monitoring:\n")
    for error in errors:
        error_dict = error.to_dict()
        print(json.dumps(error_dict, indent=2))
        print()

    print("This structured data can be sent to:")
    print("  - Logging systems (ELK, Splunk, etc.)")
    print("  - Monitoring/alerting systems")
    print("  - Error tracking services")


async def example_catch_all_library_errors():
    """Demonstrate catching all library errors."""
    print("\n" + "=" * 70)
    print("EXAMPLE 6: Catching All Library Errors")
    print("=" * 70)

    try:
        # Simulate various library operations
        raise MqttNotConnectedError("Not connected")

    except Nwp500Error as e:
        print(f"[OK] Caught Nwp500Error (base for all library errors): {e}")
        print(f"  Error type: {type(e).__name__}")
        print("  Can catch all library exceptions with single handler")

        # Check specific error type
        if isinstance(e, MqttError):
            print("  [OK] This is an MQTT error")
        elif isinstance(e, AuthenticationError):
            print("  [OK] This is an authentication error")
        elif isinstance(e, ValidationError):
            print("  [OK] This is a validation error")


async def example_exception_chaining():
    """Demonstrate exception chaining inspection."""
    print("\n" + "=" * 70)
    print("EXAMPLE 7: Exception Chain Inspection")
    print("=" * 70)

    try:
        # Simulate wrapped exception (library does this internally)
        try:
            import aiohttp

            raise aiohttp.ClientError("Connection refused")
        except aiohttp.ClientError as e:
            raise AuthenticationError("Network error during sign-in") from e

    except AuthenticationError as e:
        print(f"[OK] Caught AuthenticationError: {e}")
        print(f"  Original cause: {e.__cause__}")
        print(f"  Original cause type: {type(e.__cause__).__name__}")
        print("\nFull exception chain is preserved for debugging!")


async def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("COMPREHENSIVE EXCEPTION HANDLING EXAMPLES (v5.0+)")
    print("=" * 70)

    # Run all examples
    await example_authentication_errors()
    await example_mqtt_errors()
    await example_validation_errors()
    await example_retry_logic()
    await example_structured_logging()
    await example_catch_all_library_errors()
    await example_exception_chaining()

    print("\n" + "=" * 70)
    print("[SUCCESS] All examples completed!")
    print("=" * 70)
    print("\nKey Takeaways:")
    print("  1. Use specific exception types for better error handling")
    print("  2. Check 'retriable' flag for retry logic")
    print("  3. Use to_dict() for structured logging")
    print("  4. Access exception attributes for user-friendly messages")
    print("  5. Use Nwp500Error to catch all library errors")
    print("  6. Exception chains are preserved (use __cause__)")


if __name__ == "__main__":
    asyncio.run(main())
