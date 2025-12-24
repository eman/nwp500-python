"""Navien Water Heater Control Script - Main Entry Point."""

import argparse
import asyncio
import logging
import os
import sys

from nwp500 import (
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
    __version__,
)
from nwp500.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    MqttConnectionError,
    MqttError,
    MqttNotConnectedError,
    Nwp500Error,
    TokenRefreshError,
    ValidationError,
)

from . import commands as cmds
from .commands import (
    handle_configure_reservation_water_program_request as handle_water_prog,
)
from .commands import (
    handle_trigger_recirculation_hot_button_request as handle_hot_btn,
)
from .monitoring import handle_monitoring
from .rich_output import get_formatter
from .token_storage import load_tokens, save_tokens

_logger = logging.getLogger(__name__)
_formatter = get_formatter()


async def async_main(args: argparse.Namespace) -> int:
    """Asynchronous main function."""
    email = args.email or os.getenv("NAVIEN_EMAIL")
    password = args.password or os.getenv("NAVIEN_PASSWORD")
    tokens, cached_email = load_tokens()
    email = cached_email or email

    if not email or not password:
        _logger.error(
            "Credentials missing. Use --email/--password or env vars."
        )
        return 1

    try:
        async with NavienAuthClient(
            email, password, stored_tokens=tokens
        ) as auth:
            if auth.current_tokens and auth.user_email:
                save_tokens(auth.current_tokens, auth.user_email)

            api = NavienAPIClient(auth_client=auth)
            device = await api.get_first_device()
            if not device:
                _logger.error("No devices found.")
                return 1

            _logger.info(f"Using device: {device.device_info.device_name}")

            mqtt = NavienMqttClient(auth)
            await mqtt.connect()
            try:
                # Command Dispatching
                cmd = args.command
                if cmd == "info":
                    await cmds.handle_device_info_request(
                        mqtt, device, args.raw
                    )
                elif cmd == "status":
                    await cmds.handle_status_request(mqtt, device, args.raw)
                elif cmd == "serial":
                    await cmds.handle_get_controller_serial_request(
                        mqtt, device
                    )
                elif cmd == "power":
                    await cmds.handle_power_request(
                        mqtt, device, args.state == "on"
                    )
                elif cmd == "mode":
                    await cmds.handle_set_mode_request(mqtt, device, args.name)
                elif cmd == "temp":
                    await cmds.handle_set_dhw_temp_request(
                        mqtt, device, args.value
                    )
                elif cmd == "vacation":
                    await cmds.handle_set_vacation_days_request(
                        mqtt, device, args.days
                    )
                elif cmd == "recirc":
                    await cmds.handle_set_recirculation_mode_request(
                        mqtt, device, args.mode
                    )
                elif cmd == "reservations":
                    if args.action == "get":
                        await cmds.handle_get_reservations_request(mqtt, device)
                    else:
                        await cmds.handle_update_reservations_request(
                            mqtt, device, args.json, not args.disabled
                        )
                elif cmd == "tou":
                    if args.action == "get":
                        await cmds.handle_get_tou_request(mqtt, device, api)
                    else:
                        await cmds.handle_set_tou_enabled_request(
                            mqtt, device, args.state == "on"
                        )
                elif cmd == "energy":
                    months = [int(m.strip()) for m in args.months.split(",")]
                    await cmds.handle_get_energy_request(
                        mqtt, device, args.year, months
                    )
                elif cmd == "dr":
                    if args.action == "enable":
                        await cmds.handle_enable_demand_response_request(
                            mqtt, device
                        )
                    else:
                        await cmds.handle_disable_demand_response_request(
                            mqtt, device
                        )
                elif cmd == "hot-button":
                    await handle_hot_btn(mqtt, device)
                elif cmd == "reset-filter":
                    await cmds.handle_reset_air_filter_request(mqtt, device)
                elif cmd == "water-program":
                    await handle_water_prog(mqtt, device)
                elif cmd == "monitor":
                    await handle_monitoring(mqtt, device, args.output)

            finally:
                await mqtt.disconnect()
            return 0

    except (
        InvalidCredentialsError,
        AuthenticationError,
        TokenRefreshError,
    ) as e:
        _logger.error(f"Auth failed: {e}")
        _formatter.print_error(str(e), title="Authentication Failed")
    except (MqttNotConnectedError, MqttConnectionError, MqttError) as e:
        _logger.error(f"MQTT error: {e}")
        _formatter.print_error(str(e), title="MQTT Connection Error")
    except ValidationError as e:
        _logger.error(f"Validation error: {e}")
        _formatter.print_error(str(e), title="Validation Error")
    except Nwp500Error as e:
        _logger.error(f"Library error: {e}")
        _formatter.print_error(str(e), title="Library Error")
    except Exception as e:
        _logger.error(f"Unexpected error: {e}", exc_info=True)
        _formatter.print_error(str(e), title="Unexpected Error")
    return 1


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Navien NWP500 CLI")
    parser.add_argument(
        "--version", action="version", version=f"nwp500-python {__version__}"
    )
    parser.add_argument("--email", help="Navien email")
    parser.add_argument("--password", help="Navien password")
    parser.add_argument(
        "-v",
        "--verbose",
        dest="loglevel",
        action="store_const",
        const=logging.INFO,
    )
    parser.add_argument(
        "-vv",
        "--very-verbose",
        dest="loglevel",
        action="store_const",
        const=logging.DEBUG,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Simple commands
    subparsers.add_parser(
        "info",
        help="Show device information (firmware, capabilities, serial number)",
    ).add_argument("--raw", action="store_true")
    subparsers.add_parser(
        "status",
        help="Show current device status (temperature, mode, power usage)",
    ).add_argument("--raw", action="store_true")
    subparsers.add_parser("serial", help="Get controller serial number")
    subparsers.add_parser(
        "hot-button", help="Trigger hot button (instant hot water)"
    )
    subparsers.add_parser(
        "reset-filter", help="Reset air filter maintenance timer"
    )
    subparsers.add_parser(
        "water-program", help="Enable water program reservation scheduling mode"
    )

    # Command with args
    subparsers.add_parser("power", help="Turn device on or off").add_argument(
        "state", choices=["on", "off"]
    )
    subparsers.add_parser("mode", help="Set operation mode").add_argument(
        "name",
        help="Mode name",
        choices=[
            "standby",
            "heat-pump",
            "electric",
            "energy-saver",
            "high-demand",
            "vacation",
        ],
    )
    subparsers.add_parser(
        "temp", help="Set target hot water temperature"
    ).add_argument("value", type=float, help="Temp °F")
    subparsers.add_parser(
        "vacation", help="Enable vacation mode for N days"
    ).add_argument("days", type=int)
    subparsers.add_parser(
        "recirc", help="Set recirculation pump mode (1-4)"
    ).add_argument("mode", type=int, choices=[1, 2, 3, 4])

    # Sub-sub commands
    res = subparsers.add_parser(
        "reservations",
        help="Schedule mode and temperature changes at specific times",
    )
    res_sub = res.add_subparsers(dest="action", required=True)
    res_sub.add_parser("get", help="Get current reservation schedule")
    res_set = res_sub.add_parser(
        "set", help="Set reservation schedule from JSON"
    )
    res_set.add_argument("json", help="Reservation JSON")
    res_set.add_argument("--disabled", action="store_true")

    tou = subparsers.add_parser(
        "tou", help="Configure time-of-use pricing schedule"
    )
    tou_sub = tou.add_subparsers(dest="action", required=True)
    tou_sub.add_parser("get", help="Get current TOU schedule")
    tou_set = tou_sub.add_parser("set", help="Enable or disable TOU pricing")
    tou_set.add_argument("state", choices=["on", "off"])

    energy = subparsers.add_parser(
        "energy", help="Query historical energy usage by month"
    )
    energy.add_argument("--year", type=int, required=True)
    energy.add_argument(
        "--months", required=True, help="Comma-separated months"
    )

    dr = subparsers.add_parser(
        "dr", help="Enable or disable utility demand response"
    )
    dr.add_argument("action", choices=["enable", "disable"])

    monitor = subparsers.add_parser(
        "monitor", help="Monitor device status in real-time (logs to CSV)"
    )
    monitor.add_argument("-o", "--output", default="nwp500_status.csv")

    return parser.parse_args(args)


def main(args_list: list[str]) -> None:
    args = parse_args(args_list)
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stdout,
        format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s",
    )
    _logger.setLevel(args.loglevel or logging.INFO)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    try:
        sys.exit(asyncio.run(async_main(args)))
    except KeyboardInterrupt:
        _logger.info("Interrupted.")


def run() -> None:
    main(sys.argv[1:])


if __name__ == "__main__":
    run()
