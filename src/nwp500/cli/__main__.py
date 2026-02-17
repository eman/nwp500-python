"""Navien Water Heater Control CLI - Main Entry Point."""

import asyncio
import functools
import logging
import sys
from typing import Any

import click

from nwp500 import (
    Device,
    DeviceStatus,
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
    __version__,
    set_unit_system,
)
from nwp500.enums import TemperatureType
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
from nwp500.unit_system import UnitSystemType

from . import handlers
from .rich_output import get_formatter
from .token_storage import load_tokens, save_tokens

_logger = logging.getLogger(__name__)
_formatter = get_formatter()


async def _detect_unit_system(
    mqtt: NavienMqttClient, device: Device
) -> UnitSystemType:
    """Detect unit system from device status when not explicitly set.

    Requests a quick device status to read the device's temperature_type
    preference, then returns the matching unit system.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[DeviceStatus] = loop.create_future()

    def _on_status(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    await mqtt.subscribe_device_status(device, _on_status)
    await mqtt.control.request_device_status(device)
    try:
        status = await asyncio.wait_for(future, timeout=5.0)
        if status.temperature_type == TemperatureType.CELSIUS:
            _logger.info("Auto-detected metric unit system from device")
            return "metric"
        _logger.info("Auto-detected us_customary unit system from device")
        return "us_customary"
    except TimeoutError:
        _logger.warning(
            "Timed out detecting unit system, defaulting to us_customary"
        )
        return None


def async_command(f: Any) -> Any:
    """Decorator to run click commands asynchronously with device connection."""

    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx: click.Context, *args: Any, **kwargs: Any) -> Any:
        async def runner() -> int:
            email = ctx.obj.get("email")
            password = ctx.obj.get("password")
            unit_system = ctx.obj.get("unit_system")

            # Set unit system if provided
            if unit_system:
                set_unit_system(unit_system)

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

                    if unit_system is not None:
                        api = NavienAPIClient(
                            auth_client=auth, unit_system=unit_system
                        )
                    else:
                        api = NavienAPIClient(auth_client=auth)
                    device = await api.get_first_device()
                    if not device:
                        _logger.error("No devices found.")
                        return 1

                    _logger.info(
                        f"Using device: {device.device_info.device_name}"
                    )

                    if unit_system is not None:
                        mqtt = NavienMqttClient(auth, unit_system=unit_system)
                    else:
                        mqtt = NavienMqttClient(auth)
                    await mqtt.connect()
                    try:
                        # Auto-detect unit system from device when not
                        # explicitly set. This ensures commands like
                        # reservations use the correct temperature unit.
                        if unit_system is None:
                            detected = await _detect_unit_system(mqtt, device)
                            if detected:
                                set_unit_system(detected)

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
@click.option(
    "--unit-system",
    type=click.Choice(["metric", "us_customary"], case_sensitive=False),
    help="Unit system: metric (C/LPM/L) or us_customary (F/GPM/gal)",
)
@click.option("-v", "--verbose", count=True, help="Increase verbosity")
@click.version_option(version=__version__)
@click.pass_context
def cli(
    ctx: click.Context,
    email: str | None,
    password: str | None,
    unit_system: str | None,
    verbose: int,
) -> None:
    """Navien NWP500 Control CLI."""
    ctx.ensure_object(dict)
    ctx.obj["email"] = email
    ctx.obj["password"] = password
    ctx.obj["unit_system"] = unit_system

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
@click.option("--json", "output_json", is_flag=True, help="Output raw JSON")
@async_command
async def reservations_get(
    mqtt: NavienMqttClient, device: Any, output_json: bool = False
) -> None:
    """Get current reservation schedule."""
    await handlers.handle_get_reservations_request(mqtt, device, output_json)


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


@reservations.command("add")  # type: ignore[attr-defined]
@click.option(
    "--days",
    required=True,
    help="Days (comma-separated: MO,TU,WE,TH,FR,SA,SU or full names)",
)
@click.option("--hour", type=int, required=True, help="Hour (0-23)")
@click.option("--minute", type=int, required=True, help="Minute (0-59)")
@click.option(
    "--mode",
    type=int,
    required=True,
    help="Mode: 1=HP, 2=Electric, 3=EnergySaver, 4=HighDemand, "
    "5=Vacation, 6=PowerOff",
)
@click.option(
    "--temp",
    type=float,
    required=True,
    help="Temperature in device unit (Fahrenheit or Celsius)",
)
@click.option("--disabled", is_flag=True, help="Create as disabled reservation")
@async_command
async def reservations_add(
    mqtt: NavienMqttClient,
    device: Any,
    days: str,
    hour: int,
    minute: int,
    mode: int,
    temp: float,
    disabled: bool,
) -> None:
    """Add a single reservation to the schedule."""
    await handlers.handle_add_reservation_request(
        mqtt, device, not disabled, days, hour, minute, mode, temp
    )


@reservations.command("delete")  # type: ignore[attr-defined]
@click.argument("index", type=int)
@async_command
async def reservations_delete(
    mqtt: NavienMqttClient, device: Any, index: int
) -> None:
    """Delete a reservation by its number (1-based index)."""
    await handlers.handle_delete_reservation_request(mqtt, device, index)


@reservations.command("update")  # type: ignore[attr-defined]
@click.argument("index", type=int)
@click.option(
    "--days",
    default=None,
    help="Days (comma-separated: MO,TU,WE,TH,FR,SA,SU or full names)",
)
@click.option("--hour", type=int, default=None, help="Hour (0-23)")
@click.option("--minute", type=int, default=None, help="Minute (0-59)")
@click.option(
    "--mode",
    type=int,
    default=None,
    help="Mode: 1=HP, 2=Electric, 3=EnergySaver, 4=HighDemand, "
    "5=Vacation, 6=PowerOff",
)
@click.option(
    "--temp",
    type=float,
    default=None,
    help="Temperature in preferred unit (Fahrenheit or Celsius)",
)
@click.option("--enable", is_flag=True, default=None, help="Enable")
@click.option("--disable", is_flag=True, default=None, help="Disable")
@async_command
async def reservations_update(
    mqtt: NavienMqttClient,
    device: Any,
    index: int,
    days: str | None,
    hour: int | None,
    minute: int | None,
    mode: int | None,
    temp: float | None,
    enable: bool | None,
    disable: bool | None,
) -> None:
    """Update a reservation by its number (1-based index).

    Only the specified fields are changed; others are preserved.
    """
    enabled: bool | None = None
    if enable:
        enabled = True
    elif disable:
        enabled = False

    await handlers.handle_update_reservation_request(
        mqtt,
        device,
        index,
        enabled=enabled,
        days=days,
        hour=hour,
        minute=minute,
        mode=mode,
        temperature=temp,
    )


@cli.group()  # type: ignore[attr-defined]
def anti_legionella() -> None:
    """Manage Anti-Legionella disinfection settings."""
    pass


@anti_legionella.command("enable")  # type: ignore[attr-defined]
@click.option(
    "--period",
    type=int,
    required=True,
    help="Cycle period in days (1-30)",
)
@async_command
async def anti_legionella_enable(
    mqtt: NavienMqttClient, device: Any, period: int
) -> None:
    """Enable Anti-Legionella disinfection cycle."""
    await handlers.handle_enable_anti_legionella_request(mqtt, device, period)


@anti_legionella.command("disable")  # type: ignore[attr-defined]
@async_command
async def anti_legionella_disable(mqtt: NavienMqttClient, device: Any) -> None:
    """Disable Anti-Legionella disinfection cycle."""
    await handlers.handle_disable_anti_legionella_request(mqtt, device)


@anti_legionella.command("status")  # type: ignore[attr-defined]
@async_command
async def anti_legionella_status(mqtt: NavienMqttClient, device: Any) -> None:
    """Show Anti-Legionella status."""
    await handlers.handle_get_anti_legionella_status_request(mqtt, device)


@anti_legionella.command("set-period")  # type: ignore[attr-defined]
@click.argument("days", type=int)
@async_command
async def anti_legionella_set_period(
    mqtt: NavienMqttClient, device: Any, days: int
) -> None:
    """Set Anti-Legionella cycle period in days (1-30)."""
    await handlers.handle_enable_anti_legionella_request(mqtt, device, days)


@cli.group()  # type: ignore[attr-defined]
def tou() -> None:
    """Manage Time-of-Use settings."""
    pass


@tou.command("get")  # type: ignore[attr-defined]
@click.option("--json", "output_json", is_flag=True, help="Output raw JSON")
@async_command
async def tou_get(
    mqtt: NavienMqttClient,
    device: Any,
    output_json: bool = False,
) -> None:
    """Get current TOU schedule."""
    ctx = click.get_current_context()
    api = None
    if ctx and hasattr(ctx, "obj") and ctx.obj is not None:
        api = ctx.obj.get("api")
    if api:
        await handlers.handle_get_tou_request(
            mqtt, device, api, output_json=output_json
        )
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


@tou.command("rates")  # type: ignore[attr-defined]
@click.argument("zip_code")
@click.option("--utility", default=None, help="Filter by utility name")
@async_command
async def tou_rates(
    mqtt: NavienMqttClient, device: Any, zip_code: str, utility: str | None
) -> None:
    """List utility rate plans for a zip code.

    Queries the OpenEI API for residential electricity rate plans.
    Requires OPENEI_API_KEY environment variable.
    """
    await handlers.handle_tou_rates_request(zip_code, utility=utility)


@tou.command("plan")  # type: ignore[attr-defined]
@click.argument("zip_code")
@click.argument("plan_name")
@click.option("--utility", default=None, help="Filter by utility name")
@click.option("--json", "output_json", is_flag=True, help="Output raw JSON")
@async_command
async def tou_plan(
    mqtt: NavienMqttClient,
    device: Any,
    zip_code: str,
    plan_name: str,
    utility: str | None,
    output_json: bool = False,
) -> None:
    """View converted rate plan details.

    Shows decoded seasons, time intervals, and prices per kWh.
    Requires OPENEI_API_KEY environment variable.
    """
    ctx = click.get_current_context()
    api = ctx.obj.get("api") if ctx and ctx.obj else None
    if api:
        await handlers.handle_tou_plan_request(
            api,
            zip_code,
            plan_name,
            utility=utility,
            output_json=output_json,
        )
    else:
        _logger.error("API client not available")


@tou.command("apply")  # type: ignore[attr-defined]
@click.argument("zip_code")
@click.argument("plan_name")
@click.option("--utility", default=None, help="Filter by utility name")
@click.option("--enable", is_flag=True, help="Also enable TOU after applying")
@async_command
async def tou_apply(
    mqtt: NavienMqttClient,
    device: Any,
    zip_code: str,
    plan_name: str,
    utility: str | None,
    enable: bool,
) -> None:
    """Apply a rate plan to the water heater.

    Fetches the plan from OpenEI, converts it via the Navien backend,
    and applies it to the device. Use --enable to also enable TOU mode.

    Requires OPENEI_API_KEY environment variable.
    """
    ctx = click.get_current_context()
    api = ctx.obj.get("api") if ctx and ctx.obj else None
    if api:
        await handlers.handle_tou_apply_request(
            mqtt,
            device,
            api,
            zip_code,
            plan_name,
            utility=utility,
            enable=enable,
        )
    else:
        _logger.error("API client not available")


@cli.command()  # type: ignore[attr-defined]
@click.option("--year", type=int, required=True, help="Year to query")
@click.option(
    "--months", required=False, help="Comma-separated months (e.g. 1,2,3)"
)
@click.option(
    "--month",
    type=int,
    required=False,
    help="Show daily breakdown for a specific month (1-12)",
)
@async_command
async def energy(
    mqtt: NavienMqttClient,
    device: Any,
    year: int,
    months: str | None,
    month: int | None,
) -> None:
    """Query historical energy usage.

    Use either --months for monthly summary or --month for daily breakdown.
    """
    if month is not None:
        # Daily breakdown for a single month
        if month < 1 or month > 12:
            raise click.ClickException("Month must be between 1 and 12")
        await handlers.handle_get_energy_request(mqtt, device, year, [month])
    elif months is not None:
        # Monthly summary
        month_list = [int(m.strip()) for m in months.split(",")]
        await handlers.handle_get_energy_request(mqtt, device, year, month_list)
    else:
        raise click.ClickException(
            "Either --months (for monthly summary) or --month "
            "(for daily breakdown) required"
        )


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
