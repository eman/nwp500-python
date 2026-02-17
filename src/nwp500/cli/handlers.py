"""Command handlers for CLI operations."""

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar, cast

from nwp500 import (
    Device,
    DeviceFeature,
    DeviceStatus,
    EnergyUsageResponse,
    NavienAPIClient,
    NavienMqttClient,
)
from nwp500.exceptions import (
    DeviceError,
    MqttError,
    Nwp500Error,
    RangeValidationError,
    ValidationError,
)
from nwp500.models import ReservationSchedule
from nwp500.mqtt.utils import redact_serial
from nwp500.unit_system import get_unit_system, set_unit_system

from .output_formatters import (
    print_device_info,
    print_device_status,
    print_energy_usage,
    print_json,
)
from .rich_output import get_formatter

_logger = logging.getLogger(__name__)
_formatter = get_formatter()

# Raw protocol fields for ReservationEntry (used in model_dump include)
_RAW_RESERVATION_FIELDS = {
    "enable",
    "week",
    "hour",
    "min",
    "mode",
    "param",
}

T = TypeVar("T")


async def _wait_for_response(
    subscribe_func: Callable[
        [Device, Callable[[Any], None]], Coroutine[Any, Any, Any]
    ],
    device: Device,
    action_func: Callable[[], Coroutine[Any, Any, Any]],
    timeout: float = 10.0,
    action_name: str = "operation",
) -> Any:
    """Generic helper to wait for a specific MQTT response."""
    future = asyncio.get_running_loop().create_future()

    def callback(res: Any) -> None:
        if not future.done():
            future.set_result(res)

    await subscribe_func(device, callback)
    _logger.info(f"Requesting {action_name}...")
    await action_func()

    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        _logger.error(f"Timed out waiting for {action_name} response.")
        raise


async def _handle_command_with_status_feedback(
    mqtt: NavienMqttClient,
    device: Device,
    action_func: Callable[[], Coroutine[Any, Any, Any]],
    action_name: str,
    success_msg: str,
    print_status: bool = False,
) -> DeviceStatus | None:
    """Helper for commands that wait for a DeviceStatus response."""
    try:
        status: Any = await _wait_for_response(
            mqtt.subscribe_device_status,
            device,
            action_func,
            action_name=action_name,
        )
        if print_status:
            print_json(status.model_dump())
        _logger.info(success_msg)
        _formatter.print_success(success_msg)
        return cast(DeviceStatus, status)
    except (ValidationError, RangeValidationError) as e:
        _logger.error(f"Invalid parameters: {e}")
        _formatter.print_error(str(e), title="Invalid Parameters")
    except (MqttError, DeviceError, Nwp500Error) as e:
        _logger.error(f"Error {action_name}: {e}")
        _formatter.print_error(
            str(e), title=f"Error During {action_name.title()}"
        )
    except Exception as e:
        _logger.error(f"Unexpected error {action_name}: {e}")
        _formatter.print_error(str(e), title="Unexpected Error")
    return None


async def get_controller_serial_number(
    mqtt: NavienMqttClient, device: Device, timeout: float = 10.0
) -> str | None:
    """Retrieve controller serial number from device."""
    try:
        feature: Any = await _wait_for_response(
            mqtt.subscribe_device_feature,
            device,
            lambda: mqtt.control.request_device_info(device),
            timeout=timeout,
            action_name="controller serial",
        )
        serial = cast(DeviceFeature, feature).controller_serial_number
        _logger.info(
            f"Controller serial number retrieved: {redact_serial(serial)}"
        )
        return serial
    except Exception:
        return None


async def handle_get_controller_serial_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Request and display just the controller serial number."""
    serial = await get_controller_serial_number(mqtt, device)
    if serial:
        print(serial)
    else:
        _logger.error("Failed to retrieve controller serial number.")


async def _handle_info_request(
    mqtt: NavienMqttClient,
    device: Device,
    subscribe_method: Callable[
        [Device, Callable[[Any], None]], Coroutine[Any, Any, Any]
    ],
    request_method: Callable[[Device], Coroutine[Any, Any, Any]],
    data_key: str,
    action_name: str,
    raw: bool = False,
    formatter: Callable[[Any], None] | None = None,
) -> None:
    """Generic helper for requesting and displaying device information."""
    try:
        if not raw:
            res = await _wait_for_response(
                subscribe_method,
                device,
                lambda: request_method(device),
                action_name=action_name,
            )
            if formatter:
                formatter(res)
            else:
                print_json(res.model_dump())
        else:
            future = asyncio.get_running_loop().create_future()

            def raw_cb(topic: str, message: dict[str, Any]) -> None:
                if not future.done():
                    res = message.get("response", {}).get(
                        data_key
                    ) or message.get(data_key)
                    if res:
                        print_json(res)
                        future.set_result(None)

            await mqtt.subscribe_device(device, raw_cb)
            await request_method(device)
            await asyncio.wait_for(future, timeout=10)
    except Exception as e:
        _logger.error(f"Failed to get {action_name}: {e}")


async def handle_status_request(
    mqtt: NavienMqttClient, device: Device, raw: bool = False
) -> None:
    """Request device status and print it."""
    await _handle_info_request(
        mqtt,
        device,
        mqtt.subscribe_device_status,
        mqtt.control.request_device_status,
        "status",
        "device status",
        raw,
        formatter=print_device_status if not raw else None,
    )


async def handle_device_info_request(
    mqtt: NavienMqttClient, device: Device, raw: bool = False
) -> None:
    """Request comprehensive device information."""
    await _handle_info_request(
        mqtt,
        device,
        mqtt.subscribe_device_feature,
        mqtt.control.request_device_info,
        "feature",
        "device information",
        raw,
        formatter=print_device_info if not raw else None,
    )


async def handle_set_mode_request(
    mqtt: NavienMqttClient, device: Device, mode_name: str
) -> None:
    """Set device operation mode."""
    mode_mapping = {
        "standby": 0,
        "heat-pump": 1,
        "electric": 2,
        "energy-saver": 3,
        "high-demand": 4,
        "vacation": 5,
    }
    mode_id = mode_mapping.get(mode_name.lower())
    if mode_id is None:
        _logger.error(
            f"Invalid mode '{mode_name}'. Valid: {list(mode_mapping.keys())}"
        )
        return

    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.set_dhw_mode(device, mode_id),
        "setting mode",
        f"Mode changed to {mode_name}",
    )


async def handle_set_dhw_temp_request(
    mqtt: NavienMqttClient, device: Device, temperature: float
) -> None:
    """Set DHW target temperature."""
    unit_suffix = "°C" if get_unit_system() == "metric" else "°F"
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.set_dhw_temperature(device, temperature),
        "setting temperature",
        f"Temperature set to {temperature}{unit_suffix}",
    )


async def handle_power_request(
    mqtt: NavienMqttClient, device: Device, power_on: bool
) -> None:
    """Set device power state."""
    state = "on" if power_on else "off"
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.set_power(device, power_on),
        f"turning {state}",
        f"Device turned {state}",
    )


async def _fetch_reservations(
    mqtt: NavienMqttClient, device: Device
) -> ReservationSchedule | None:
    """Fetch current reservations from device and return as a model.

    Returns None on timeout.
    """
    future: asyncio.Future[ReservationSchedule] = (
        asyncio.get_running_loop().create_future()
    )
    caller_unit_system = get_unit_system()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        if (
            future.done()
            or "response" not in message
            or "/res/rsv/" not in topic
        ):
            return
        response = message.get("response", {})
        # Ensure it's actually a reservation response (not some other /res/ msg)
        if "reservationUse" not in response and "reservation" not in response:
            return
        if caller_unit_system:
            set_unit_system(caller_unit_system)
        schedule = ReservationSchedule(**response)
        future.set_result(schedule)

    device_type = str(device.device_info.device_type)
    response_pattern = f"cmd/{device_type}/+/#"
    await mqtt.subscribe(response_pattern, raw_callback)
    await mqtt.control.request_reservations(device)
    try:
        return await asyncio.wait_for(future, timeout=10)
    except TimeoutError:
        _logger.error("Timed out waiting for reservations.")
        return None


def _schedule_to_display_list(
    schedule: ReservationSchedule,
) -> list[dict[str, Any]]:
    """Convert a ReservationSchedule to a list of display-ready dicts."""
    result: list[dict[str, Any]] = []
    for i, entry in enumerate(schedule.reservation):
        d = entry.model_dump()
        d["number"] = i + 1
        d["mode"] = d.pop("mode_name")
        result.append(d)
    return result


async def handle_get_reservations_request(
    mqtt: NavienMqttClient, device: Device, output_json: bool = False
) -> None:
    """Request current reservation schedule."""
    schedule = await _fetch_reservations(mqtt, device)
    if schedule is None:
        return

    if output_json:
        print_json(schedule.model_dump())
    else:
        reservation_list = _schedule_to_display_list(schedule)
        _formatter.print_reservations_table(reservation_list, schedule.enabled)


async def handle_update_reservations_request(
    mqtt: NavienMqttClient,
    device: Device,
    reservations_json: str,
    enabled: bool,
) -> None:
    """Update reservation schedule."""
    try:
        data: Any = json.loads(reservations_json)
        if not isinstance(data, list):
            raise ValueError("Must be a JSON array")
        reservations: list[Any] = data  # type: ignore[reportUnknownVariableType]
    except (json.JSONDecodeError, ValueError) as e:
        _logger.error(f"Invalid reservations JSON: {e}")
        return

    future = asyncio.get_running_loop().create_future()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        if not future.done() and "response" in message:
            print_json(message)
            future.set_result(None)

    device_type = device.device_info.device_type
    response_topic = f"cmd/{device_type}/{mqtt.client_id}/res/rsv/rd"
    await mqtt.subscribe(response_topic, raw_callback)
    await mqtt.control.update_reservations(
        device, reservations, enabled=enabled
    )
    try:
        await asyncio.wait_for(future, timeout=10)
    except TimeoutError:
        _logger.error("Timed out updating reservations.")


async def handle_add_reservation_request(
    mqtt: NavienMqttClient,
    device: Device,
    enabled: bool,
    days: str,
    hour: int,
    minute: int,
    mode: int,
    temperature: float,
) -> None:
    """Add a single reservation to the existing schedule."""
    from nwp500.encoding import build_reservation_entry

    # Validate inputs
    if not 0 <= hour <= 23:
        _logger.error("Hour must be between 0 and 23")
        return
    if not 0 <= minute <= 59:
        _logger.error("Minute must be between 0 and 59")
        return
    if not 1 <= mode <= 6:
        _logger.error("Mode must be between 1 and 6")
        return

    # Parse day string (comma-separated: "MO,WE,FR" or full day names)
    day_list = [d.strip() for d in days.split(",")]

    try:
        # Build the reservation entry
        reservation_entry = build_reservation_entry(
            enabled=enabled,
            days=day_list,
            hour=hour,
            minute=minute,
            mode_id=mode,
            temperature=temperature,
        )

        # Fetch current reservations using shared helper
        schedule = await _fetch_reservations(mqtt, device)
        if schedule is None:
            _logger.error("Timed out fetching current reservations")
            return

        # Build raw entry list and append new one
        current_reservations = [
            e.model_dump(include=_RAW_RESERVATION_FIELDS)
            for e in schedule.reservation
        ]
        current_reservations.append(reservation_entry)

        # Update the full schedule
        await mqtt.control.update_reservations(
            device, current_reservations, enabled=True
        )

        print("✓ Reservation added successfully")

    except (RangeValidationError, ValidationError) as e:
        _logger.error(f"Failed to add reservation: {e}")


async def handle_delete_reservation_request(
    mqtt: NavienMqttClient,
    device: Device,
    index: int,
) -> None:
    """Delete a single reservation by 1-based index."""
    schedule = await _fetch_reservations(mqtt, device)
    if schedule is None:
        _logger.error("Timed out fetching current reservations")
        return

    count = len(schedule.reservation)
    if index < 1 or index > count:
        _logger.error(
            f"Invalid reservation index {index}. "
            f"Valid range: 1-{count} ({count} reservation(s) exist)"
        )
        return

    # Build raw entry list and remove the target
    current_reservations = [
        e.model_dump(include=_RAW_RESERVATION_FIELDS)
        for e in schedule.reservation
    ]
    removed = current_reservations.pop(index - 1)
    _logger.info(f"Removing reservation {index}: {removed}")

    # Determine if reservations should stay enabled
    still_enabled = schedule.enabled and len(current_reservations) > 0

    await mqtt.control.update_reservations(
        device, current_reservations, enabled=still_enabled
    )
    print(f"✓ Reservation {index} deleted successfully")


async def handle_update_reservation_request(
    mqtt: NavienMqttClient,
    device: Device,
    index: int,
    *,
    enabled: bool | None = None,
    days: str | None = None,
    hour: int | None = None,
    minute: int | None = None,
    mode: int | None = None,
    temperature: float | None = None,
) -> None:
    """Update a single reservation by 1-based index.

    Only the provided fields are modified; others are preserved.
    """
    from nwp500.encoding import build_reservation_entry

    schedule = await _fetch_reservations(mqtt, device)
    if schedule is None:
        _logger.error("Timed out fetching current reservations")
        return

    count = len(schedule.reservation)
    if index < 1 or index > count:
        _logger.error(
            f"Invalid reservation index {index}. "
            f"Valid range: 1-{count} ({count} reservation(s) exist)"
        )
        return

    existing = schedule.reservation[index - 1]

    # Merge: use provided values or fall back to existing
    new_enabled = enabled if enabled is not None else existing.enabled
    new_days: list[str] = (
        [d.strip() for d in days.split(",")] if days else existing.days
    )
    new_hour = hour if hour is not None else existing.hour
    new_minute = minute if minute is not None else existing.min
    new_mode = mode if mode is not None else existing.mode

    # Temperature requires special handling: if user provides a value
    # it's in their preferred unit, otherwise keep the raw param.
    if temperature is not None:
        new_entry = build_reservation_entry(
            enabled=new_enabled,
            days=new_days,
            hour=new_hour,
            minute=new_minute,
            mode_id=new_mode,
            temperature=temperature,
        )
    else:
        from nwp500.encoding import encode_week_bitfield

        new_entry = {
            "enable": 2 if new_enabled else 1,
            "week": encode_week_bitfield(new_days),
            "hour": new_hour,
            "min": new_minute,
            "mode": new_mode,
            "param": existing.param,
        }

    # Build full list with the replacement
    current_reservations = [
        e.model_dump(include=_RAW_RESERVATION_FIELDS)
        for e in schedule.reservation
    ]
    current_reservations[index - 1] = new_entry

    await mqtt.control.update_reservations(
        device, current_reservations, enabled=schedule.enabled
    )
    print(f"✓ Reservation {index} updated successfully")


async def handle_enable_anti_legionella_request(
    mqtt: NavienMqttClient,
    device: Device,
    period_days: int,
) -> None:
    """Enable Anti-Legionella disinfection cycle."""
    try:
        await mqtt.control.enable_anti_legionella(device, period_days)
        print(f"✓ Anti-Legionella enabled (cycle every {period_days} day(s))")
    except (RangeValidationError, ValidationError) as e:
        _logger.error(f"Failed to enable Anti-Legionella: {e}")
    except DeviceError as e:
        _logger.error(f"Device error: {e}")


async def handle_disable_anti_legionella_request(
    mqtt: NavienMqttClient,
    device: Device,
) -> None:
    """Disable Anti-Legionella disinfection cycle."""
    try:
        await mqtt.control.disable_anti_legionella(device)
        print("✓ Anti-Legionella disabled")
    except DeviceError as e:
        _logger.error(f"Device error: {e}")


async def handle_get_anti_legionella_status_request(
    mqtt: NavienMqttClient,
    device: Device,
) -> None:
    """Display Anti-Legionella status from device status."""
    future: asyncio.Future[DeviceStatus] = (
        asyncio.get_running_loop().create_future()
    )

    def _on_status(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    await mqtt.subscribe_device_status(device, _on_status)
    await mqtt.control.request_device_status(device)
    try:
        status = await asyncio.wait_for(future, timeout=10)
        period = getattr(status, "anti_legionella_period", None)
        use = getattr(status, "anti_legionella_use", None)
        busy = getattr(status, "anti_legionella_operation_busy", None)

        items = [
            (
                "ANTI-LEGIONELLA",
                "Status",
                "Enabled" if use else "Disabled",
            ),
            (
                "ANTI-LEGIONELLA",
                "Cycle Period",
                f"{period} day(s)" if period else "N/A",
            ),
            (
                "ANTI-LEGIONELLA",
                "Currently Running",
                "Yes" if busy else "No",
            ),
        ]
        _formatter.print_status_table(items)
    except TimeoutError:
        _logger.error("Timed out waiting for device status.")


async def handle_get_device_info_rest(
    api_client: NavienAPIClient, device: Device, raw: bool = False
) -> None:
    """Get device info from REST API (minimal DeviceInfo fields)."""
    try:
        device_info_obj = await api_client.get_device_info(
            mac_address=device.device_info.mac_address,
            additional_value=device.device_info.additional_value,
        )
        if raw:
            print_json(device_info_obj.model_dump())
        else:
            # Print formatted output with rich support
            info = device_info_obj.device_info

            install_type_str = info.install_type if info.install_type else "N/A"
            mac_display = (
                redact_serial(info.mac_address) if info.mac_address else "N/A"
            )

            # Collect items for rich formatter
            all_items = [
                ("DEVICE INFO", "Device Name", info.device_name),
                ("DEVICE INFO", "MAC Address", mac_display),
                ("DEVICE INFO", "Device Type", str(info.device_type)),
                ("DEVICE INFO", "Home Seq", str(info.home_seq)),
                ("DEVICE INFO", "Connected", str(info.connected)),
                ("DEVICE INFO", "Install Type", install_type_str),
                (
                    "DEVICE INFO",
                    "Additional Value",
                    info.additional_value or "N/A",
                ),
            ]

            _formatter.print_status_table(all_items)
    except Exception as e:
        _logger.error(f"Error fetching device info: {e}")


async def handle_get_tou_request(
    mqtt: NavienMqttClient,
    device: Device,
    api_client: Any,
    *,
    output_json: bool = False,
) -> None:
    """Request Time-of-Use settings from REST API."""
    from nwp500.encoding import (
        decode_price,
        decode_season_bitfield,
        decode_week_bitfield,
    )

    try:
        serial = await get_controller_serial_number(mqtt, device)
        if not serial:
            _logger.error("Failed to get controller serial.")
            return

        tou_info = await api_client.get_tou_info(
            mac_address=device.device_info.mac_address,
            additional_value=device.device_info.additional_value,
            controller_id=serial,
            user_type="O",
        )

        if output_json:
            print_json(
                {
                    "name": tou_info.name,
                    "utility": tou_info.utility,
                    "zipCode": tou_info.zip_code,
                    "schedule": [
                        {
                            "season": s.season,
                            "intervals": s.intervals,
                        }
                        for s in tou_info.schedule
                    ],
                }
            )
            return

        _formatter.print_tou_schedule(
            name=tou_info.name,
            utility=tou_info.utility,
            zip_code=tou_info.zip_code,
            schedules=tou_info.schedule,
            decode_season=decode_season_bitfield,
            decode_week=decode_week_bitfield,
            decode_price_fn=decode_price,
        )
    except Exception as e:
        _logger.error(f"Error fetching TOU: {e}")


async def handle_set_tou_enabled_request(
    mqtt: NavienMqttClient, device: Device, enabled: bool
) -> None:
    """Enable or disable Time-of-Use."""
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.set_tou_enabled(device, enabled),
        f"{'enabling' if enabled else 'disabling'} TOU",
        f"TOU {'enabled' if enabled else 'disabled'}",
    )


async def handle_tou_rates_request(
    zip_code: str,
    utility: str | None = None,
) -> None:
    """List utilities and rate plans for a zip code."""
    from nwp500.openei import OpenEIClient

    try:
        async with OpenEIClient() as client:
            plans = await client.list_rate_plans(zip_code, utility=utility)

        if not plans:
            _formatter.print_error(
                f"No rate plans found for zip code {zip_code}",
                title="No Results",
            )
            return

        # Group by utility
        utilities: dict[str, list[dict[str, Any]]] = {}
        for plan in plans:
            util_name = plan["utility"]
            utilities.setdefault(util_name, []).append(plan)

        output: list[dict[str, Any]] = []
        for util_name, util_plans in sorted(utilities.items()):
            unique_names = sorted({p["name"] for p in util_plans})
            output.append(
                {
                    "utility": util_name,
                    "planCount": len(unique_names),
                    "plans": unique_names,
                }
            )

        print_json(output)
    except ValueError as e:
        _formatter.print_error(str(e), title="Configuration Error")
    except Exception as e:
        _logger.error(f"Error fetching rate plans: {e}")
        _formatter.print_error(str(e), title="Error")


async def handle_tou_plan_request(
    api_client: NavienAPIClient,
    zip_code: str,
    plan_name: str,
    utility: str | None = None,
    *,
    output_json: bool = False,
) -> None:
    """View a converted rate plan's details."""
    from nwp500.encoding import (
        decode_price,
        decode_season_bitfield,
        decode_week_bitfield,
    )
    from nwp500.openei import OpenEIClient

    try:
        async with OpenEIClient() as client:
            rate_plan = await client.get_rate_plan(
                zip_code, plan_name, utility=utility
            )

        if not rate_plan:
            _formatter.print_error(
                f"Rate plan matching '{plan_name}' not found",
                title="Not Found",
            )
            return

        # Convert via Navien backend
        converted = await api_client.convert_tou([rate_plan])

        if not converted:
            _formatter.print_error(
                "Backend returned no converted plans",
                title="Conversion Error",
            )
            return

        plan = converted[0]

        if output_json:
            schedules = []
            for sched in plan.schedule:
                months = decode_season_bitfield(sched.season)
                intervals = []
                for iv in sched.intervals:
                    days = decode_week_bitfield(iv.get("week", 0))
                    dp = iv.get("decimalPoint", 5)
                    intervals.append(
                        {
                            "days": days,
                            "time": (
                                f"{iv.get('startHour', 0):02d}:"
                                f"{iv.get('startMinute', 0):02d}-"
                                f"{iv.get('endHour', 0):02d}:"
                                f"{iv.get('endMinute', 0):02d}"
                            ),
                            "priceMin": (
                                "$"
                                f"{decode_price(iv.get('priceMin', 0), dp):.5f}"
                                "/kWh"
                            ),
                            "priceMax": (
                                "$"
                                f"{decode_price(iv.get('priceMax', 0), dp):.5f}"
                                "/kWh"
                            ),
                        }
                    )
                schedules.append({"months": months, "intervals": intervals})
            print_json(
                {
                    "utility": plan.utility,
                    "name": plan.name,
                    "schedules": schedules,
                }
            )
            return

        _formatter.print_tou_schedule(
            name=plan.name,
            utility=plan.utility,
            zip_code=int(zip_code) if zip_code.isdigit() else 0,
            schedules=plan.schedule,
            decode_season=decode_season_bitfield,
            decode_week=decode_week_bitfield,
            decode_price_fn=decode_price,
        )
    except ValueError as e:
        _formatter.print_error(str(e), title="Configuration Error")
    except Exception as e:
        _logger.error(f"Error viewing rate plan: {e}")
        _formatter.print_error(str(e), title="Error")


async def handle_tou_apply_request(
    mqtt: NavienMqttClient,
    device: Device,
    api_client: NavienAPIClient,
    zip_code: str,
    plan_name: str,
    utility: str | None = None,
    enable: bool = False,
) -> None:
    """Apply a TOU rate plan to the water heater."""
    from nwp500.openei import OpenEIClient

    try:
        # Step 1: Find the rate plan from OpenEI
        async with OpenEIClient() as client:
            rate_plan = await client.get_rate_plan(
                zip_code, plan_name, utility=utility
            )

        if not rate_plan:
            _formatter.print_error(
                f"Rate plan matching '{plan_name}' not found",
                title="Not Found",
            )
            return

        # Step 2: Convert via Navien backend
        converted = await api_client.convert_tou([rate_plan])

        if not converted:
            _formatter.print_error(
                "Backend returned no converted plans",
                title="Conversion Error",
            )
            return

        plan = converted[0]

        # Step 3: Get device register path from current TOU info
        serial = await get_controller_serial_number(mqtt, device)
        if not serial:
            _logger.error("Failed to get controller serial.")
            return

        current_tou = await api_client.get_tou_info(
            mac_address=device.device_info.mac_address,
            additional_value=device.device_info.additional_value,
            controller_id=serial,
        )
        register_path = current_tou.register_path or "wifi"

        # Step 4: Apply via PUT /device/tou
        tou_info_dict = {
            "name": plan.name,
            "schedule": [
                {"season": s.season, "interval": s.intervals}
                for s in plan.schedule
            ],
            "utility": plan.utility,
            "zipCode": zip_code,
        }

        result = await api_client.update_tou(
            mac_address=device.device_info.mac_address,
            additional_value=device.device_info.additional_value,
            tou_info=tou_info_dict,
            source_data=rate_plan,
            zip_code=zip_code,
            register_path=register_path,
        )

        _formatter.print_success(
            f"Applied rate plan: {result.name} ({result.utility})"
        )

        # Step 5: Optionally enable TOU
        if enable:
            await _handle_command_with_status_feedback(
                mqtt,
                device,
                lambda: mqtt.control.set_tou_enabled(device, True),
                "enabling TOU",
                "TOU enabled",
            )

    except ValueError as e:
        _formatter.print_error(str(e), title="Configuration Error")
    except Exception as e:
        _logger.error(f"Error applying rate plan: {e}")
        _formatter.print_error(str(e), title="Error")


async def handle_get_energy_request(
    mqtt: NavienMqttClient, device: Device, year: int, months: list[int]
) -> None:
    """Request energy usage data.

    If a single month is provided, shows daily breakdown.
    If multiple months are provided, shows monthly summary.
    """
    try:
        res: Any = await _wait_for_response(
            mqtt.subscribe_energy_usage,
            device,
            lambda: mqtt.control.request_energy_usage(device, year, months),
            action_name="energy usage",
            timeout=15,
        )
        # If single month requested, show daily breakdown
        if len(months) == 1:
            from .output_formatters import print_daily_energy_usage

            print_daily_energy_usage(
                cast(EnergyUsageResponse, res), year, months[0]
            )
        else:
            print_energy_usage(cast(EnergyUsageResponse, res))
    except Exception as e:
        _logger.error(f"Error getting energy data: {e}")


async def handle_reset_air_filter_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Reset air filter timer."""
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.reset_air_filter(device),
        "resetting air filter",
        "Air filter timer reset",
    )


async def handle_set_vacation_days_request(
    mqtt: NavienMqttClient, device: Device, days: int
) -> None:
    """Set vacation mode duration."""
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.set_vacation_days(device, days),
        "setting vacation days",
        f"Vacation days set to {days}",
    )


async def handle_set_recirculation_mode_request(
    mqtt: NavienMqttClient, device: Device, mode: int
) -> None:
    """Set recirculation pump mode."""
    mode_map = {1: "ALWAYS", 2: "BUTTON", 3: "SCHEDULE", 4: "TEMPERATURE"}
    mode_name = mode_map.get(mode, str(mode))
    status = await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.set_recirculation_mode(device, mode),
        "setting recirculation mode",
        f"Recirculation mode set to {mode_name}",
    )

    if status and status.recirc_operation_mode.value != mode:
        _logger.warning(
            f"Device reported mode {status.recirc_operation_mode.name} "
            f"instead of expected {mode_name}. External factor or "
            "device state may have prevented the change."
        )


async def handle_trigger_recirculation_hot_button_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Trigger hot button."""
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.trigger_recirculation_hot_button(device),
        "triggering hot button",
        "Hot button triggered",
    )


async def handle_enable_demand_response_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Enable demand response."""
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.enable_demand_response(device),
        "enabling DR",
        "Demand response enabled",
    )


async def handle_disable_demand_response_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Disable demand response."""
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.disable_demand_response(device),
        "disabling DR",
        "Demand response disabled",
    )


async def handle_configure_reservation_water_program_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Configure water program."""
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.configure_reservation_water_program(device),
        "configuring water program",
        "Water program configured",
    )
