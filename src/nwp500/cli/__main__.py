"""Navien Water Heater Control CLI - Main Entry Point."""

import asyncio
import functools
import logging
import sys
from typing import Any

import click

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

from . import handlers
from .rich_output import get_formatter
from .token_storage import load_tokens, save_tokens

_logger = logging.getLogger(__name__)
_formatter = get_formatter()


def async_command(f: Any) -> Any:
    """Decorator to run click commands asynchronously with device connection."""

    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx: click.Context, *args: Any, **kwargs: Any) -> Any:
        async def runner() -> int:
            email = ctx.obj.get("email")
            password = ctx.obj.get("password")

            # Load cached tokens if available
            tokens, cached_email = load_tokens()
            # If email not provided in args, try cached email
            email = email or cached_email

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

                    _logger.info(
                        f"Using device: {device.device_info.device_name}"
                    )

                    mqtt = NavienMqttClient(auth)
                    await mqtt.connect()
                    try:
                        # Attach api to context for commands that need it
                        ctx.obj["api"] = api

                        await f(mqtt, device, *args, **kwargs)
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

        return asyncio.run(runner())

    return wrapper


@click.group()
@click.option("--email", envvar="NAVIEN_EMAIL", help="Navien account email")
@click.option(
    "--password", envvar="NAVIEN_PASSWORD", help="Navien account password"
)
@click.option("-v", "--verbose", count=True, help="Increase verbosity")
@click.version_option(version=__version__)
@click.pass_context
def cli(
    ctx: click.Context, email: str | None, password: str | None, verbose: int
) -> None:
    """Navien NWP500 Control CLI."""
    ctx.ensure_object(dict)
    ctx.obj["email"] = email
    ctx.obj["password"] = password

    log_level = logging.WARNING
    if verbose == 1:
        log_level = logging.INFO
    elif verbose >= 2:
        log_level = logging.DEBUG

    logging.basicConfig(
        level=logging.WARNING,  # Default for other libraries
        stream=sys.stdout,
        format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s",
    )
    logging.getLogger("nwp500").setLevel(log_level)
    # Ensure this module's logger respects the level
    _logger.setLevel(log_level)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


@cli.command()  # type: ignore[attr-defined]
@click.option("--raw", is_flag=True, help="Output raw JSON response")
@async_command
async def info(mqtt: NavienMqttClient, device: Any, raw: bool) -> None:
    """Show device information (firmware, capabilities)."""
    await handlers.handle_device_info_request(mqtt, device, raw)


@cli.command()  # type: ignore[attr-defined]
@click.option("--raw", is_flag=True, help="Output raw JSON response")
@async_command
async def device_info(
    mqtt: NavienMqttClient,
    device: Any,
    raw: bool,
) -> None:
    """Show basic device info from REST API (DeviceInfo model)."""
    ctx = click.get_current_context()
    api = None
    if ctx and hasattr(ctx, "obj") and ctx.obj is not None:
        api = ctx.obj.get("api")
    if api:
        await handlers.handle_get_device_info_rest(api, device, raw)
    else:
        _logger.error("API client not available")


@cli.command()  # type: ignore[attr-defined]
@click.option("--raw", is_flag=True, help="Output raw JSON response")
@async_command
async def status(mqtt: NavienMqttClient, device: Any, raw: bool) -> None:
    """Show current device status (temps, mode, etc)."""
    await handlers.handle_status_request(mqtt, device, raw)


@cli.command()  # type: ignore[attr-defined]
@async_command
async def serial(mqtt: NavienMqttClient, device: Any) -> None:
    """Get controller serial number."""
    await handlers.handle_get_controller_serial_request(mqtt, device)


@cli.command()  # type: ignore[attr-defined]
@async_command
async def hot_button(mqtt: NavienMqttClient, device: Any) -> None:
    """Trigger hot button (instant hot water)."""
    await handlers.handle_trigger_recirculation_hot_button_request(mqtt, device)


@cli.command()  # type: ignore[attr-defined]
@async_command
async def reset_filter(mqtt: NavienMqttClient, device: Any) -> None:
    """Reset air filter maintenance timer."""
    await handlers.handle_reset_air_filter_request(mqtt, device)


@cli.command()  # type: ignore[attr-defined]
@async_command
async def water_program(mqtt: NavienMqttClient, device: Any) -> None:
    """Enable water program reservation scheduling mode."""
    await handlers.handle_configure_reservation_water_program_request(
        mqtt, device
    )


@cli.command()  # type: ignore[attr-defined]
@click.argument("state", type=click.Choice(["on", "off"], case_sensitive=False))
@async_command
async def power(mqtt: NavienMqttClient, device: Any, state: str) -> None:
    """Turn device on or off."""
    await handlers.handle_power_request(mqtt, device, state.lower() == "on")


@cli.command()  # type: ignore[attr-defined]
@click.argument(
    "mode_name",
    type=click.Choice(
        [
            "standby",
            "heat-pump",
            "electric",
            "energy-saver",
            "high-demand",
            "vacation",
        ],
        case_sensitive=False,
    ),
)
@async_command
async def mode(mqtt: NavienMqttClient, device: Any, mode_name: str) -> None:
    """Set operation mode."""
    await handlers.handle_set_mode_request(mqtt, device, mode_name)


@cli.command()  # type: ignore[attr-defined]
@click.argument("value", type=float)
@async_command
async def temp(mqtt: NavienMqttClient, device: Any, value: float) -> None:
    """Set target hot water temperature (deg F)."""
    await handlers.handle_set_dhw_temp_request(mqtt, device, value)


@cli.command()  # type: ignore[attr-defined]
@click.argument("days", type=int)
@async_command
async def vacation(mqtt: NavienMqttClient, device: Any, days: int) -> None:
    """Enable vacation mode for N days."""
    await handlers.handle_set_vacation_days_request(mqtt, device, days)


@cli.command()  # type: ignore[attr-defined]
@click.argument(
    "mode_val", type=click.Choice(["1", "2", "3", "4"]), metavar="MODE"
)
@async_command
async def recirc(mqtt: NavienMqttClient, device: Any, mode_val: str) -> None:
    """Set recirculation pump mode (1-4)."""
    await handlers.handle_set_recirculation_mode_request(
        mqtt, device, int(mode_val)
    )


@cli.group()  # type: ignore[attr-defined]
def reservations() -> None:
    """Manage reservations."""
    pass


@reservations.command("get")  # type: ignore[attr-defined]
@async_command
async def reservations_get(mqtt: NavienMqttClient, device: Any) -> None:
    """Get current reservation schedule."""
    await handlers.handle_get_reservations_request(mqtt, device)


@reservations.command("set")  # type: ignore[attr-defined]
@click.argument("json_str", metavar="JSON")
@click.option("--disabled", is_flag=True, help="Disable reservations")
@async_command
async def reservations_set(
    mqtt: NavienMqttClient, device: Any, json_str: str, disabled: bool
) -> None:
    """Set reservation schedule from JSON."""
    await handlers.handle_update_reservations_request(
        mqtt, device, json_str, not disabled
    )


@cli.group()  # type: ignore[attr-defined]
def tou() -> None:
    """Manage Time-of-Use settings."""
    pass


@tou.command("get")  # type: ignore[attr-defined]
@click.pass_context  # We need context to access api
@async_command
async def tou_get(
    mqtt: NavienMqttClient, device: Any, ctx: click.Context | None = None
) -> None:
    """Get current TOU schedule."""
    ctx = click.get_current_context()
    api = None
    if ctx and hasattr(ctx, "obj") and ctx.obj is not None:
        api = ctx.obj.get("api")
    if api:
        await handlers.handle_get_tou_request(mqtt, device, api)
    else:
        _logger.error("API client not available")


@tou.command("set")  # type: ignore[attr-defined]
@click.argument("state", type=click.Choice(["on", "off"], case_sensitive=False))
@async_command
async def tou_set(mqtt: NavienMqttClient, device: Any, state: str) -> None:
    """Enable or disable TOU pricing."""
    await handlers.handle_set_tou_enabled_request(
        mqtt, device, state.lower() == "on"
    )


@cli.command()  # type: ignore[attr-defined]
@click.option("--year", type=int, required=True)
@click.option(
    "--months", required=True, help="Comma-separated months (e.g. 1,2,3)"
)
@async_command
async def energy(
    mqtt: NavienMqttClient, device: Any, year: int, months: str
) -> None:
    """Query historical energy usage."""
    month_list = [int(m.strip()) for m in months.split(",")]
    await handlers.handle_get_energy_request(mqtt, device, year, month_list)


@cli.command()  # type: ignore[attr-defined]
@click.argument(
    "action", type=click.Choice(["enable", "disable"], case_sensitive=False)
)
@async_command
async def dr(mqtt: NavienMqttClient, device: Any, action: str) -> None:
    """Enable or disable Demand Response."""
    if action.lower() == "enable":
        await handlers.handle_enable_demand_response_request(mqtt, device)
    else:
        await handlers.handle_disable_demand_response_request(mqtt, device)


@cli.command()  # type: ignore[attr-defined]
@click.option(
    "-o", "--output", default="nwp500_status.csv", help="Output CSV file"
)
@async_command
async def monitor(mqtt: NavienMqttClient, device: Any, output: str) -> None:
    """Monitor device status in real-time."""
    from .monitoring import handle_monitoring

    await handle_monitoring(mqtt, device, output)


if __name__ == "__main__":
    cli()  # type: ignore[call-arg]

run = cli
