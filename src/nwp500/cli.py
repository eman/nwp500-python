"""
Navien Water Heater Control Script

This script provides a command-line interface to monitor and control
Navien water heaters using the nwp500-python library.
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from nwp500 import (
    Device,
    DeviceStatus,
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
    __version__,
)
from nwp500.auth import AuthTokens, InvalidCredentialsError

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)
TOKEN_FILE = Path.home() / ".nwp500_tokens.json"


# ---- Token Management ----
def save_tokens(tokens: AuthTokens, email: str):
    """Saves authentication tokens and user email to a file."""
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(
                {
                    "email": email,
                    "id_token": tokens.id_token,
                    "access_token": tokens.access_token,
                    "refresh_token": tokens.refresh_token,
                    "authentication_expires_in": tokens.authentication_expires_in,
                    "issued_at": tokens.issued_at.isoformat(),
                    # AWS Credentials
                    "access_key_id": tokens.access_key_id,
                    "secret_key": tokens.secret_key,
                    "session_token": tokens.session_token,
                    "authorization_expires_in": tokens.authorization_expires_in,
                },
                f,
            )
        _logger.info(f"Tokens saved to {TOKEN_FILE}")
    except OSError as e:
        _logger.error(f"Failed to save tokens: {e}")


def load_tokens() -> tuple[Optional[AuthTokens], Optional[str]]:
    """Loads authentication tokens and user email from a file."""
    if not TOKEN_FILE.exists():
        return None, None
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
            email = data["email"]
            # Reconstruct the AuthTokens object
            tokens = AuthTokens(
                id_token=data["id_token"],
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                authentication_expires_in=data["authentication_expires_in"],
                # AWS Credentials (use .get for backward compatibility)
                access_key_id=data.get("access_key_id"),
                secret_key=data.get("secret_key"),
                session_token=data.get("session_token"),
                authorization_expires_in=data.get("authorization_expires_in"),
            )
            # Manually set the issued_at from the stored ISO format string
            tokens.issued_at = datetime.fromisoformat(data["issued_at"])
            _logger.info(f"Tokens loaded from {TOKEN_FILE} for user {email}")
            return tokens, email
    except (OSError, json.JSONDecodeError, KeyError) as e:
        _logger.error(f"Failed to load or parse tokens, will re-authenticate: {e}")
        return None, None


# ---- CSV Writing ----
def write_status_to_csv(file_path: str, status: DeviceStatus):
    """Appends a device status message to a CSV file."""
    try:
        # Convert the entire dataclass to a dictionary to capture all fields
        status_dict = asdict(status)

        # Add a timestamp to the beginning of the data
        data_to_write = {"timestamp": datetime.now().isoformat()}

        # Convert any Enum objects to their string names for CSV compatibility
        for key, value in status_dict.items():
            if isinstance(value, Enum):
                data_to_write[key] = value.name
            else:
                data_to_write[key] = value

        # Dynamically get the fieldnames from the dictionary keys
        fieldnames = list(data_to_write.keys())

        file_exists = os.path.exists(file_path)
        with open(file_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            # Write header only if the file is new
            if not file_exists or os.path.getsize(file_path) == 0:
                writer.writeheader()
            writer.writerow(data_to_write)
        _logger.debug(f"Status written to {file_path}")
    except (OSError, csv.Error) as e:
        _logger.error(f"Failed to write to CSV file {file_path}: {e}")


# ---- Main Application Logic ----
async def get_authenticated_client(
    args: argparse.Namespace,
) -> Optional[NavienAuthClient]:
    """Handles authentication flow."""
    tokens, email = load_tokens()

    # Use cached tokens only if they are valid, unexpired, and contain AWS credentials
    if (
        tokens
        and email
        and not tokens.is_expired
        and tokens.access_key_id
        and tokens.secret_key
        and tokens.session_token
    ):
        _logger.info("Using valid cached tokens.")
        # The password argument is unused when cached tokens are present.
        auth_client = NavienAuthClient(email, "cached_auth")
        auth_client._user_email = email
        await auth_client._ensure_session()

        # Manually construct the auth response since we are not signing in
        from nwp500.auth import AuthenticationResponse, UserInfo

        auth_client._auth_response = AuthenticationResponse(
            user_info=UserInfo.from_dict({}), tokens=tokens
        )
        return auth_client

    _logger.info("Cached tokens are invalid, expired, or incomplete. Re-authenticating...")
    # Fallback to email/password
    email = args.email or os.getenv("NAVIEN_EMAIL")
    password = args.password or os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        _logger.error(
            "Credentials not found. Please provide --email and --password, "
            "or set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables."
        )
        return None

    try:
        auth_client = NavienAuthClient(email, password)
        await auth_client.sign_in(email, password)
        if auth_client.current_tokens and auth_client.user_email:
            save_tokens(auth_client.current_tokens, auth_client.user_email)
        return auth_client
    except InvalidCredentialsError:
        _logger.error("Invalid email or password.")
        return None
    except Exception as e:
        _logger.error(f"An unexpected error occurred during authentication: {e}")
        return None


def _json_default_serializer(o: object) -> str:
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(o, Enum):
        return o.name
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


async def handle_status_request(mqtt: NavienMqttClient, device: Device):
    """Request device status once and print it."""
    future = asyncio.get_running_loop().create_future()

    def on_status(status: DeviceStatus):
        if not future.done():
            print(json.dumps(asdict(status), indent=2, default=_json_default_serializer))
            future.set_result(None)

    await mqtt.subscribe_device_status(device, on_status)
    _logger.info("Requesting device status...")
    await mqtt.request_device_status(device)

    try:
        await asyncio.wait_for(future, timeout=10)
    except asyncio.TimeoutError:
        _logger.error("Timed out waiting for device status response.")


async def handle_status_raw_request(mqtt: NavienMqttClient, device: Device):
    """Request device status once and print raw MQTT data (no conversions)."""
    future = asyncio.get_running_loop().create_future()

    # Subscribe to the raw MQTT topic to capture data before conversion
    def raw_callback(topic: str, message: dict):
        if not future.done():
            # Extract and print the raw status portion
            if "response" in message and "status" in message["response"]:
                print(
                    json.dumps(
                        message["response"]["status"], indent=2, default=_json_default_serializer
                    )
                )
                future.set_result(None)
            elif "status" in message:
                print(json.dumps(message["status"], indent=2, default=_json_default_serializer))
                future.set_result(None)

    # Subscribe to all device messages
    await mqtt.subscribe_device(device, raw_callback)

    _logger.info("Requesting device status (raw)...")
    await mqtt.request_device_status(device)

    try:
        await asyncio.wait_for(future, timeout=10)
    except asyncio.TimeoutError:
        _logger.error("Timed out waiting for device status response.")


async def handle_device_info_request(mqtt: NavienMqttClient, device: Device):
    """
    Request comprehensive device information via MQTT and print it.

    This fetches detailed device information including firmware versions,
    capabilities, temperature ranges, and feature availability - much more
    comprehensive than basic API device data.
    """
    future = asyncio.get_running_loop().create_future()

    def on_device_info(info):
        if not future.done():
            print(json.dumps(asdict(info), indent=2, default=_json_default_serializer))
            future.set_result(None)

    await mqtt.subscribe_device_feature(device, on_device_info)
    _logger.info("Requesting device information...")
    await mqtt.request_device_info(device)

    try:
        await asyncio.wait_for(future, timeout=10)
    except asyncio.TimeoutError:
        _logger.error("Timed out waiting for device info response.")


async def handle_device_feature_request(mqtt: NavienMqttClient, device: Device):
    """Request device feature information once and print it."""
    future = asyncio.get_running_loop().create_future()

    def on_feature(feature):
        if not future.done():
            print(json.dumps(asdict(feature), indent=2, default=_json_default_serializer))
            future.set_result(None)

    await mqtt.subscribe_device_feature(device, on_feature)
    _logger.info("Requesting device feature information...")
    await mqtt.request_device_feature(device)

    try:
        await asyncio.wait_for(future, timeout=10)
    except asyncio.TimeoutError:
        _logger.error("Timed out waiting for device feature response.")


async def handle_set_mode_request(mqtt: NavienMqttClient, device: Device, mode_name: str):
    """
    Set device operation mode and display the response.

    Args:
        mqtt: MQTT client instance
        device: Device to control
        mode_name: Mode name (heat-pump, energy-saver, etc.)
    """
    # Map mode names to mode IDs
    # Based on MQTT client documentation in set_dhw_mode method:
    # - 1: Heat Pump Only (most efficient, slowest recovery)
    # - 2: Electric Only (least efficient, fastest recovery)
    # - 3: Energy Saver (balanced, good default)
    # - 4: High Demand (maximum heating capacity)
    mode_mapping = {
        "standby": 0,
        "heat-pump": 1,  # Heat Pump Only
        "electric": 2,  # Electric Only
        "energy-saver": 3,  # Energy Saver
        "high-demand": 4,  # High Demand
        "vacation": 5,
    }

    mode_name_lower = mode_name.lower()
    if mode_name_lower not in mode_mapping:
        valid_modes = ", ".join(mode_mapping.keys())
        _logger.error(f"Invalid mode '{mode_name}'. Valid modes: {valid_modes}")
        return

    mode_id = mode_mapping[mode_name_lower]

    # Set up callback to capture status response after mode change
    future = asyncio.get_running_loop().create_future()
    responses = []

    def on_status_response(status):
        if not future.done():
            responses.append(status)
            # Complete after receiving response
            future.set_result(None)

    # Subscribe to status updates to see the mode change result
    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        _logger.info(f"Setting operation mode to '{mode_name}' (mode ID: {mode_id})...")

        # Send the mode change command
        await mqtt.set_dhw_mode(device, mode_id)

        # Wait for status response (mode change confirmation)
        try:
            await asyncio.wait_for(future, timeout=15)

            if responses:
                status = responses[0]
                print(json.dumps(asdict(status), indent=2, default=_json_default_serializer))
                _logger.info(f"Mode change successful. New mode: {status.operationMode.name}")
            else:
                _logger.warning("Mode command sent but no status response received")

        except asyncio.TimeoutError:
            _logger.error("Timed out waiting for mode change confirmation")

    except Exception as e:
        _logger.error(f"Error setting mode: {e}")


async def handle_set_dhw_temp_request(mqtt: NavienMqttClient, device: Device, temperature: int):
    """
    Set DHW target temperature and display the response.

    Args:
        mqtt: MQTT client instance
        device: Device to control
        temperature: Target temperature in Fahrenheit (display value)
    """
    # Validate temperature range
    # Based on MQTT client documentation: display range approximately 115-150°F
    if temperature < 115 or temperature > 150:
        _logger.error(f"Temperature {temperature}°F is out of range. Valid range: 115-150°F")
        return

    # Set up callback to capture status response after temperature change
    future = asyncio.get_running_loop().create_future()
    responses = []

    def on_status_response(status):
        if not future.done():
            responses.append(status)
            # Complete after receiving response
            future.set_result(None)

    # Subscribe to status updates to see the temperature change result
    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        _logger.info(f"Setting DHW target temperature to {temperature}°F...")

        # Send the temperature change command using display temperature
        await mqtt.set_dhw_temperature_display(device, temperature)

        # Wait for status response (temperature change confirmation)
        try:
            await asyncio.wait_for(future, timeout=15)

            if responses:
                status = responses[0]
                print(json.dumps(asdict(status), indent=2, default=_json_default_serializer))
                _logger.info(
                    f"Temperature change successful. New target: "
                    f"{status.dhwTargetTemperatureSetting}°F"
                )
            else:
                _logger.warning("Temperature command sent but no status response received")

        except asyncio.TimeoutError:
            _logger.error("Timed out waiting for temperature change confirmation")

    except Exception as e:
        _logger.error(f"Error setting temperature: {e}")


async def handle_power_request(mqtt: NavienMqttClient, device: Device, power_on: bool):
    """
    Set device power state and display the response.

    Args:
        mqtt: MQTT client instance
        device: Device to control
        power_on: True to turn on, False to turn off
    """
    action = "on" if power_on else "off"
    _logger.info(f"Turning device {action}...")

    # Set up callback to capture status response after power change
    future = asyncio.get_running_loop().create_future()

    def on_power_change_response(status: DeviceStatus):
        if not future.done():
            future.set_result(status)

    try:
        # Subscribe to status updates
        await mqtt.subscribe_device_status(device, on_power_change_response)

        # Send power command
        await mqtt.set_power(device, power_on)

        # Wait for response with timeout
        status = await asyncio.wait_for(future, timeout=10.0)

        _logger.info(f"Device turned {action} successfully!")

        # Display relevant status information
        print(
            json.dumps(
                {
                    "result": "success",
                    "action": action,
                    "status": {
                        "operationMode": status.operationMode.name,
                        "dhwOperationSetting": status.dhwOperationSetting.name,
                        "dhwTemperature": f"{status.dhwTemperature}°F",
                        "dhwChargePer": f"{status.dhwChargePer}%",
                        "tankUpperTemperature": f"{status.tankUpperTemperature:.1f}°F",
                        "tankLowerTemperature": f"{status.tankLowerTemperature:.1f}°F",
                    },
                },
                indent=2,
            )
        )

    except asyncio.TimeoutError:
        _logger.error(f"Timed out waiting for power {action} confirmation")

    except Exception as e:
        _logger.error(f"Error turning device {action}: {e}")


async def handle_monitoring(mqtt: NavienMqttClient, device: Device, output_file: str):
    """Start periodic monitoring and write status to CSV."""
    _logger.info(f"Starting periodic monitoring. Writing updates to {output_file}")
    _logger.info("Press Ctrl+C to stop.")

    def on_status_update(status: DeviceStatus):
        _logger.info(
            f"Received status update: Temp={status.dhwTemperature}°F, "
            f"Power={'ON' if status.dhwUse else 'OFF'}"
        )
        write_status_to_csv(output_file, status)

    await mqtt.subscribe_device_status(device, on_status_update)
    await mqtt.start_periodic_device_status_requests(device, period_seconds=30)
    await mqtt.request_device_status(device)  # Get an initial status right away

    # Keep the script running indefinitely
    await asyncio.Event().wait()


async def async_main(args: argparse.Namespace):
    """Asynchronous main function."""
    auth_client = await get_authenticated_client(args)
    if not auth_client:
        return 1  # Authentication failed

    api_client = NavienAPIClient(auth_client=auth_client)
    _logger.info("Fetching device information...")
    device = await api_client.get_first_device()

    if not device:
        _logger.error("No devices found for this account.")
        await auth_client.close()
        return 1

    _logger.info(f"Found device: {device.device_info.device_name}")

    mqtt = NavienMqttClient(auth_client)
    try:
        await mqtt.connect()
        _logger.info("MQTT client connected.")

        if args.device_info:
            await handle_device_info_request(mqtt, device)
        elif args.device_feature:
            await handle_device_feature_request(mqtt, device)
        elif args.power_on:
            await handle_power_request(mqtt, device, power_on=True)
            # If --status was also specified, get status after power change
            if args.status:
                _logger.info("Getting updated status after power on...")
                await asyncio.sleep(2)  # Brief pause for device to process
                await handle_status_request(mqtt, device)
        elif args.power_off:
            await handle_power_request(mqtt, device, power_on=False)
            # If --status was also specified, get status after power change
            if args.status:
                _logger.info("Getting updated status after power off...")
                await asyncio.sleep(2)  # Brief pause for device to process
                await handle_status_request(mqtt, device)
        elif args.set_mode:
            await handle_set_mode_request(mqtt, device, args.set_mode)
            # If --status was also specified, get status after setting mode
            if args.status:
                _logger.info("Getting updated status after mode change...")
                await asyncio.sleep(2)  # Brief pause for device to process
                await handle_status_request(mqtt, device)
        elif args.set_dhw_temp:
            await handle_set_dhw_temp_request(mqtt, device, args.set_dhw_temp)
            # If --status was also specified, get status after setting temperature
            if args.status:
                _logger.info("Getting updated status after temperature change...")
                await asyncio.sleep(2)  # Brief pause for device to process
                await handle_status_request(mqtt, device)
        elif args.status_raw:
            # Raw status request (no conversions)
            await handle_status_raw_request(mqtt, device)
        elif args.status:
            # Status-only request
            await handle_status_request(mqtt, device)
        else:  # Default to monitor
            await handle_monitoring(mqtt, device, args.output)

    except asyncio.CancelledError:
        _logger.info("Monitoring stopped by user.")
    except Exception as e:
        _logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return 1
    finally:
        _logger.info("Disconnecting MQTT client...")
        await mqtt.disconnect()
        await auth_client.close()
        _logger.info("Cleanup complete.")
    return 0


# ---- CLI ----
def parse_args(args):
    """Parse command line parameters."""
    parser = argparse.ArgumentParser(description="Navien Water Heater Control Script")
    parser.add_argument(
        "--version",
        action="version",
        version=f"nwp500-python {__version__}",
    )
    parser.add_argument(
        "--email",
        type=str,
        help="Navien account email. Overrides NAVIEN_EMAIL env var.",
    )
    parser.add_argument(
        "--password",
        type=str,
        help="Navien account password. Overrides NAVIEN_PASSWORD env var.",
    )

    # Status check (can be combined with other actions)
    parser.add_argument(
        "--status",
        action="store_true",
        help="Fetch and print the current device status. Can be combined with control commands.",
    )
    parser.add_argument(
        "--status-raw",
        action="store_true",
        help="Fetch and print the raw device status as received from MQTT "
        "(no conversions applied).",
    )

    # Primary action modes (mutually exclusive)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--device-info",
        action="store_true",
        help="Fetch and print comprehensive device information via MQTT, then exit.",
    )
    group.add_argument(
        "--device-feature",
        action="store_true",
        help="Fetch and print device feature and capability information via MQTT, then exit.",
    )
    group.add_argument(
        "--set-mode",
        type=str,
        metavar="MODE",
        help="Set operation mode and display response. "
        "Options: heat-pump, electric, energy-saver, high-demand, vacation, standby",
    )
    group.add_argument(
        "--set-dhw-temp",
        type=int,
        metavar="TEMP",
        help="Set DHW (Domestic Hot Water) target temperature in Fahrenheit "
        "(115-150°F) and display response.",
    )
    group.add_argument(
        "--power-on",
        action="store_true",
        help="Turn the device on and display response.",
    )
    group.add_argument(
        "--power-off",
        action="store_true",
        help="Turn the device off and display response.",
    )
    group.add_argument(
        "--monitor",
        action="store_true",
        default=True,  # Default action
        help="Run indefinitely, polling for status every 30 seconds and logging to a CSV file. "
        "(default)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="nwp500_status.csv",
        help="Output CSV file name for monitoring. (default: nwp500_status.csv)",
    )

    # Logging
    parser.add_argument(
        "-v",
        "--verbose",
        dest="loglevel",
        help="Set loglevel to INFO",
        action="store_const",
        const=logging.INFO,
    )
    parser.add_argument(
        "-vv",
        "--very-verbose",
        dest="loglevel",
        help="Set loglevel to DEBUG",
        action="store_const",
        const=logging.DEBUG,
    )
    return parser.parse_args(args)


def setup_logging(loglevel):
    """Setup basic logging."""
    logformat = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
    logging.basicConfig(
        level=loglevel or logging.WARNING,
        stream=sys.stdout,
        format=logformat,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(args):
    """Wrapper for the asynchronous main function."""
    args = parse_args(args)

    # Validate that --status and --status-raw are not used together
    if args.status and args.status_raw:
        print("Error: --status and --status-raw cannot be used together.", file=sys.stderr)
        return 1

    # Set default log level for libraries
    setup_logging(logging.WARNING)
    # Set user-defined log level for this script
    _logger.setLevel(args.loglevel or logging.INFO)
    # aiohttp is very noisy at INFO level
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        _logger.info("Script interrupted by user.")


def run():
    """Calls main passing the CLI arguments extracted from sys.argv"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()
