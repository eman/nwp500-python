"""Command registry for NWP500 CLI."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import handlers


@dataclass
class CliCommand:
    """Definition of a CLI command."""

    name: str
    help: str
    callback: Callable[..., Any]
    args: list[str]  # Required arguments
    options: list[str]  # Optional arguments
    examples: list[str]  # Usage examples


CLI_COMMANDS = [
    CliCommand(
        name="status",
        help="Show current device status",
        callback=handlers.handle_status_request,
        args=[],
        options=["--format {text,json,csv}"],
        examples=["nwp-cli status"],
    ),
    CliCommand(
        name="info",
        help="Show device information",
        callback=handlers.handle_device_info_request,
        args=[],
        options=["--raw"],
        examples=["nwp-cli info"],
    ),
    CliCommand(
        name="mode",
        help="Set operation mode",
        callback=handlers.handle_set_mode_request,
        args=["MODE"],
        options=[],
        examples=["nwp-cli mode heat-pump"],
    ),
    CliCommand(
        name="power",
        help="Turn device on or off",
        callback=handlers.handle_power_request,
        args=["STATE"],
        options=[],
        examples=["nwp-cli power on"],
    ),
    CliCommand(
        name="temp",
        help="Set target hot water temperature",
        callback=handlers.handle_set_dhw_temp_request,
        args=["VALUE"],
        options=[],
        examples=["nwp-cli temp 120"],
    ),
    CliCommand(
        name="vacation",
        help="Enable vacation mode for N days",
        callback=handlers.handle_set_vacation_days_request,
        args=["DAYS"],
        options=[],
        examples=["nwp-cli vacation 7"],
    ),
    CliCommand(
        name="recirc",
        help="Set recirculation pump mode",
        callback=handlers.handle_set_recirculation_mode_request,
        args=["MODE"],
        options=[],
        examples=["nwp-cli recirc 2"],
    ),
]


def get_command(name: str) -> CliCommand | None:
    """Lookup command by name."""
    return next((c for c in CLI_COMMANDS if c.name == name), None)


def list_commands() -> list[CliCommand]:
    """Get all available commands."""
    return CLI_COMMANDS
