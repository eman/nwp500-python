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
from nwp500.mqtt.utils import redact_serial

from .output_formatters import (
    print_device_info,
    print_device_status,
    print_energy_usage,
    print_json,
)
from .rich_output import get_formatter

_logger = logging.getLogger(__name__)
_formatter = get_formatter()

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
    await _handle_command_with_status_feedback(
        mqtt,
        device,
        lambda: mqtt.control.set_dhw_temperature(device, temperature),
        "setting temperature",
        f"Temperature set to {temperature}°F",
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


async def handle_get_reservations_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Request current reservation schedule."""
    future = asyncio.get_running_loop().create_future()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        if not future.done() and "response" in message:
            from nwp500.encoding import (
                decode_reservation_hex,
                decode_week_bitfield,
            )

            response = message.get("response", {})
            reservation_hex = response.get("reservation", "")
            reservations = (
                decode_reservation_hex(reservation_hex)
                if isinstance(reservation_hex, str)
                else []
            )

            output = {
                "reservationUse": response.get("reservationUse", 0),
                "reservationEnabled": response.get("reservationUse") == 1,
                "reservations": [
                    {
                        "number": i + 1,
                        "enabled": e.get("enable") == 1,
                        "days": decode_week_bitfield(e.get("week", 0)),
                        "time": f"{e.get('hour', 0):02d}:{e.get('min', 0):02d}",
                        "mode": e.get("mode"),
                        "temperatureF": e.get("param", 0) + 20,
                        "raw": e,
                    }
                    for i, e in enumerate(reservations)
                ],
            }
            print_json(output)
            future.set_result(None)

    device_type = str(device.device_info.device_type)
    # Subscribe to all command responses from this device type
    # Topic pattern: cmd/{device_type}/+/# matches all responses
    response_pattern = f"cmd/{device_type}/+/#"
    await mqtt.subscribe(response_pattern, raw_callback)
    await mqtt.control.request_reservations(device)
    try:
        await asyncio.wait_for(future, timeout=10)
    except TimeoutError:
        _logger.error("Timed out waiting for reservations.")


async def handle_update_reservations_request(
    mqtt: NavienMqttClient,
    device: Device,
    reservations_json: str,
    enabled: bool,
) -> None:
    """Update reservation schedule."""
    try:
        reservations = json.loads(reservations_json)
        if not isinstance(reservations, list):
            raise ValueError("Must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        _logger.error(f"Invalid reservations JSON: {e}")
        return

    future = asyncio.get_running_loop().create_future()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        if not future.done() and "response" in message:
            print_json(message)
            future.set_result(None)

    device_type = device.device_info.device_type
    response_topic = f"cmd/{device_type}/+/+/{mqtt.client_id}/res/rsv/rd"
    await mqtt.subscribe(response_topic, raw_callback)
    await mqtt.control.update_reservations(
        device, reservations, enabled=enabled
    )
    try:
        await asyncio.wait_for(future, timeout=10)
    except TimeoutError:
        _logger.error("Timed out updating reservations.")


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
            # Print simple formatted output
            info = device_info_obj.device_info

            install_type_str = info.install_type if info.install_type else "N/A"
            print("\n=== Device Info (REST API) ===\n")
            print(f"Device Name:       {info.device_name}")
            mac_display = (
                redact_serial(info.mac_address) if info.mac_address else "N/A"
            )
            print(f"MAC Address:       {mac_display}")
            print(f"Device Type:       {info.device_type}")
            print(f"Home Seq:          {info.home_seq}")
            print(f"Connected:         {info.connected}")
            print(f"Install Type:      {install_type_str}")
            print(f"Additional Value:  {info.additional_value or 'N/A'}")
            print()
    except Exception as e:
        _logger.error(f"Error fetching device info: {e}")


async def handle_get_tou_request(
    mqtt: NavienMqttClient, device: Device, api_client: Any
) -> None:
    """Request Time-of-Use settings from REST API."""
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
        print_json(
            {
                "name": tou_info.name,
                "utility": tou_info.utility,
                "zipCode": tou_info.zip_code,
                "schedule": [
                    {"season": s.season, "intervals": s.intervals}
                    for s in tou_info.schedule
                ],
            }
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


async def handle_get_energy_request(
    mqtt: NavienMqttClient, device: Device, year: int, months: list[int]
) -> None:
    """Request energy usage data."""
    try:
        res: Any = await _wait_for_response(
            mqtt.subscribe_energy_usage,
            device,
            lambda: mqtt.control.request_energy_usage(device, year, months),
            action_name="energy usage",
            timeout=15,
        )
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
