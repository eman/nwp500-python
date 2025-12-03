"""Navien Water Heater Control Script - Main Entry Point.

This module provides the command-line interface to monitor and control
Navien water heaters using the nwp500-python library.
"""

import argparse
import asyncio
import logging
import os
import sys

from nwp500 import NavienAPIClient, NavienAuthClient, __version__
from nwp500.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    MqttConnectionError,
    MqttError,
    MqttNotConnectedError,
    Nwp500Error,
    RangeValidationError,
    TokenRefreshError,
    ValidationError,
)

from .commands import (
    handle_device_feature_request,
    handle_device_info_request,
    handle_get_controller_serial_request,
    handle_get_energy_request,
    handle_get_reservations_request,
    handle_get_tou_request,
    handle_power_request,
    handle_set_dhw_temp_request,
    handle_set_mode_request,
    handle_set_tou_enabled_request,
    handle_status_raw_request,
    handle_status_request,
    handle_update_reservations_request,
)
from .monitoring import handle_monitoring
from .token_storage import load_tokens, save_tokens

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


async def async_main(args: argparse.Namespace) -> int:
    """
    Asynchronous main function.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Get credentials
    email = args.email or os.getenv("NAVIEN_EMAIL")
    password = args.password or os.getenv("NAVIEN_PASSWORD")

    # Try loading cached tokens
    tokens, cached_email = load_tokens()

    # Use cached email if available, otherwise fall back to provided email
    email = cached_email or email

    if not email or not password:
        _logger.error(
            "Credentials not found. Please provide --email and --password, "
            "or set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables."
        )
        return 1

    try:
        # Use async with to properly manage auth client lifecycle
        async with NavienAuthClient(
            email, password, stored_tokens=tokens
        ) as auth_client:
            # Save refreshed/new tokens after authentication
            if auth_client.current_tokens and auth_client.user_email:
                save_tokens(auth_client.current_tokens, auth_client.user_email)

            api_client = NavienAPIClient(auth_client=auth_client)
            _logger.info("Fetching device information...")
            device = await api_client.get_first_device()

            # Save tokens if they were refreshed during API call
            if auth_client.current_tokens and auth_client.user_email:
                save_tokens(auth_client.current_tokens, auth_client.user_email)

            if not device:
                _logger.error("No devices found for this account.")
                return 1

            _logger.info(f"Found device: {device.device_info.device_name}")

            from nwp500 import NavienMqttClient

            mqtt = NavienMqttClient(auth_client)
            try:
                await mqtt.connect()
                _logger.info("MQTT client connected.")

                # Route to appropriate handler based on arguments
                if args.device_info:
                    await handle_device_info_request(mqtt, device)
                elif args.device_feature:
                    await handle_device_feature_request(mqtt, device)
                elif args.get_controller_serial:
                    await handle_get_controller_serial_request(mqtt, device)
                elif args.power_on:
                    await handle_power_request(mqtt, device, power_on=True)
                    if args.status:
                        _logger.info("Getting updated status after power on...")
                        await asyncio.sleep(2)
                        await handle_status_request(mqtt, device)
                elif args.power_off:
                    await handle_power_request(mqtt, device, power_on=False)
                    if args.status:
                        _logger.info(
                            "Getting updated status after power off..."
                        )
                        await asyncio.sleep(2)
                        await handle_status_request(mqtt, device)
                elif args.set_mode:
                    await handle_set_mode_request(mqtt, device, args.set_mode)
                    if args.status:
                        _logger.info(
                            "Getting updated status after mode change..."
                        )
                        await asyncio.sleep(2)
                        await handle_status_request(mqtt, device)
                elif args.set_dhw_temp:
                    await handle_set_dhw_temp_request(
                        mqtt, device, args.set_dhw_temp
                    )
                    if args.status:
                        _logger.info(
                            "Getting updated status after temperature change..."
                        )
                        await asyncio.sleep(2)
                        await handle_status_request(mqtt, device)
                elif args.get_reservations:
                    await handle_get_reservations_request(mqtt, device)
                elif args.set_reservations:
                    await handle_update_reservations_request(
                        mqtt,
                        device,
                        args.set_reservations,
                        args.reservations_enabled,
                    )
                elif args.get_tou:
                    await handle_get_tou_request(mqtt, device, api_client)
                elif args.set_tou_enabled:
                    enabled = args.set_tou_enabled.lower() == "on"
                    await handle_set_tou_enabled_request(mqtt, device, enabled)
                    if args.status:
                        _logger.info(
                            "Getting updated status after TOU change..."
                        )
                        await asyncio.sleep(2)
                        await handle_status_request(mqtt, device)
                elif args.get_energy:
                    if not args.energy_year or not args.energy_months:
                        _logger.error(
                            "--energy-year and --energy-months are required "
                            "for --get-energy"
                        )
                        return 1
                    try:
                        months = [
                            int(m.strip())
                            for m in args.energy_months.split(",")
                        ]
                        if not all(1 <= m <= 12 for m in months):
                            _logger.error("Months must be between 1 and 12")
                            return 1
                    except ValueError:
                        _logger.error(
                            "Invalid month format. Use comma-separated "
                            "numbers (e.g., '9' or '8,9,10')"
                        )
                        return 1
                    await handle_get_energy_request(
                        mqtt, device, args.energy_year, months
                    )
                elif args.status_raw:
                    await handle_status_raw_request(mqtt, device)
                elif args.status:
                    await handle_status_request(mqtt, device)
                else:  # Default to monitor
                    await handle_monitoring(mqtt, device, args.output)

            except asyncio.CancelledError:
                _logger.info("Monitoring stopped by user.")
            finally:
                _logger.info("Disconnecting MQTT client...")
                await mqtt.disconnect()

            _logger.info("Cleanup complete.")
            return 0

    except InvalidCredentialsError:
        _logger.error("Invalid email or password.")
        return 1
    except TokenRefreshError as e:
        _logger.error(f"Token refresh failed: {e}")
        _logger.info("Try logging in again with fresh credentials.")
        return 1
    except AuthenticationError as e:
        _logger.error(f"Authentication failed: {e}")
        return 1
    except MqttNotConnectedError:
        _logger.error("MQTT connection not established.")
        _logger.info(
            "The device may be offline or network connectivity issues exist."
        )
        return 1
    except MqttConnectionError as e:
        _logger.error(f"MQTT connection error: {e}")
        _logger.info("Check network connectivity and try again.")
        return 1
    except MqttError as e:
        _logger.error(f"MQTT error: {e}")
        return 1
    except ValidationError as e:
        _logger.error(f"Invalid input: {e}")
        # RangeValidationError has min_value/max_value attributes
        if isinstance(e, RangeValidationError):
            _logger.info(
                f"Valid range for {e.field}: {e.min_value} to {e.max_value}"
            )
        return 1
    except asyncio.CancelledError:
        _logger.info("Operation cancelled by user.")
        return 1
    except Nwp500Error as e:
        _logger.error(f"Library error: {e}")
        if hasattr(e, "retriable") and e.retriable:
            _logger.info("This operation may be retried.")
        return 1
    except Exception as e:
        _logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return 1


def parse_args(args: list[str]) -> argparse.Namespace:
    """Parse command line parameters."""
    parser = argparse.ArgumentParser(
        description="Navien Water Heater Control Script"
    )
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
        help="Fetch and print the current device status. "
        "Can be combined with control commands.",
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
        help="Fetch and print comprehensive device information via MQTT, "
        "then exit.",
    )
    group.add_argument(
        "--device-feature",
        action="store_true",
        help="Fetch and print device feature and capability information "
        "via MQTT, then exit.",
    )
    group.add_argument(
        "--get-controller-serial",
        action="store_true",
        help="Fetch and print controller serial number via MQTT, then exit. "
        "This is useful for TOU commands that require the serial number.",
    )
    group.add_argument(
        "--set-mode",
        type=str,
        metavar="MODE",
        help="Set operation mode and display response. "
        "Options: heat-pump, electric, energy-saver, high-demand, "
        "vacation, standby",
    )
    group.add_argument(
        "--set-dhw-temp",
        type=float,
        metavar="TEMP",
        help="Set DHW (Domestic Hot Water) target temperature in Fahrenheit "
        "(95-150°F) and display response.",
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
        "--get-reservations",
        action="store_true",
        help="Fetch and print current reservation schedule from device "
        "via MQTT, then exit.",
    )
    group.add_argument(
        "--set-reservations",
        type=str,
        metavar="JSON",
        help="Update reservation schedule with JSON array of reservation "
        "objects. Use --reservations-enabled to control if schedule is "
        "active.",
    )
    group.add_argument(
        "--get-tou",
        action="store_true",
        help="Fetch and print Time-of-Use settings from the REST API, "
        "then exit. Controller serial number is automatically retrieved.",
    )
    group.add_argument(
        "--set-tou-enabled",
        type=str,
        choices=["on", "off"],
        metavar="ON|OFF",
        help="Enable or disable Time-of-Use functionality. Options: on, off",
    )
    group.add_argument(
        "--get-energy",
        action="store_true",
        help="Request energy usage data for specified year and months "
        "via MQTT, then exit. Requires --energy-year and --energy-months "
        "options.",
    )
    group.add_argument(
        "--monitor",
        action="store_true",
        default=True,  # Default action
        help="Run indefinitely, polling for status every 30 seconds and "
        "logging to a CSV file. (default)",
    )

    # Additional options for new commands
    parser.add_argument(
        "--reservations-enabled",
        action="store_true",
        default=True,
        help="When used with --set-reservations, enable the reservation "
        "schedule. (default: True)",
    )
    parser.add_argument(
        "--tou-serial",
        type=str,
        help="(Deprecated) Controller serial number. No longer required; "
        "serial number is now retrieved automatically.",
    )
    parser.add_argument(
        "--energy-year",
        type=int,
        help="Year for energy usage query (e.g., 2025). "
        "Required with --get-energy.",
    )
    parser.add_argument(
        "--energy-months",
        type=str,
        help="Comma-separated list of months (1-12) for energy usage "
        "query (e.g., '9' or '8,9,10'). Required with --get-energy.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="nwp500_status.csv",
        help="Output CSV file name for monitoring. "
        "(default: nwp500_status.csv)",
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


def setup_logging(loglevel: int) -> None:
    """Configure basic logging for the application.

    Args:
        loglevel: Logging level (e.g., logging.DEBUG, logging.INFO)
    """
    logformat = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
    logging.basicConfig(
        level=loglevel or logging.WARNING,
        stream=sys.stdout,
        format=logformat,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(args_list: list[str]) -> None:
    """Run the asynchronous main function with argument parsing.

    Args:
        args_list: Command-line arguments to parse
    """
    args = parse_args(args_list)

    # Validate that --status and --status-raw are not used together
    if args.status and args.status_raw:
        print(
            "Error: --status and --status-raw cannot be used together.",
            file=sys.stderr,
        )
        return

    # Set default log level for libraries
    setup_logging(logging.WARNING)
    # Set user-defined log level for this script
    _logger.setLevel(args.loglevel or logging.INFO)
    # aiohttp is very noisy at INFO level
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    try:
        result = asyncio.run(async_main(args))
        sys.exit(result)
    except KeyboardInterrupt:
        _logger.info("Script interrupted by user.")


def run() -> None:
    """Entry point for the CLI application."""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()
