"""Command handlers for CLI operations."""

import asyncio
import json
import logging
from typing import Any

from nwp500 import Device, DeviceFeature, DeviceStatus, NavienMqttClient
from nwp500.exceptions import (
    DeviceCapabilityError,
    DeviceError,
    MqttError,
    Nwp500Error,
    ValidationError,
)
from nwp500.mqtt_utils import redact_serial
from nwp500.topic_builder import MqttTopicBuilder

from .output_formatters import _json_default_serializer

_logger = logging.getLogger(__name__)


async def get_controller_serial_number(
    mqtt: NavienMqttClient, device: Device, timeout: float = 10.0
) -> str | None:
    """Retrieve controller serial number from device.

    Args:
        mqtt: MQTT client instance
        device: Device object
        timeout: Timeout in seconds

    Returns:
        Controller serial number or None if timeout/error
    """
    future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    def on_feature(feature: DeviceFeature) -> None:
        if not future.done():
            future.set_result(feature.controller_serial_number)

    await mqtt.subscribe_device_feature(device, on_feature)
    _logger.info("Requesting controller serial number...")
    await mqtt.control.request_device_info(device)

    try:
        serial_number = await asyncio.wait_for(future, timeout=timeout)
        _logger.info(
            "Controller serial number retrieved: "
            f"{redact_serial(serial_number)}"
        )
        return serial_number
    except TimeoutError:
        _logger.error("Timed out waiting for controller serial number.")
        return None


async def handle_status_request(mqtt: NavienMqttClient, device: Device) -> None:
    """Request device status once and print it."""
    await _request_device_status_common(mqtt, device, parse_pydantic=True)


async def handle_status_raw_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Request device status once and print raw MQTT data (no conversions)."""
    await _request_device_status_common(mqtt, device, parse_pydantic=False)


async def _request_device_status_common(
    mqtt: NavienMqttClient,
    device: Device,
    parse_pydantic: bool = True,
) -> None:
    """Common logic for device status requests.

    Args:
        mqtt: MQTT client
        device: Device to request status for
        parse_pydantic: If True, parse with Pydantic and format output.
                       If False, print raw MQTT status portion.
    """
    future = asyncio.get_running_loop().create_future()

    if parse_pydantic:

        def on_status(status: DeviceStatus) -> None:
            if not future.done():
                from .output_formatters import format_json_output

                print(format_json_output(status.model_dump()))
                future.set_result(None)

        await mqtt.subscribe_device_status(device, on_status)
    else:

        def raw_callback(topic: str, message: dict[str, Any]) -> None:
            if not future.done():
                # Extract and print the raw status portion
                if "response" in message and "status" in message["response"]:
                    print(
                        json.dumps(
                            message["response"]["status"],
                            indent=2,
                            default=_json_default_serializer,
                        )
                    )
                    future.set_result(None)
                elif "status" in message:
                    print(
                        json.dumps(
                            message["status"],
                            indent=2,
                            default=_json_default_serializer,
                        )
                    )
                    future.set_result(None)

        # Subscribe to all device messages
        await mqtt.subscribe_device(device, raw_callback)

    action_name = "device status" if parse_pydantic else "device status (raw)"
    _logger.info(f"Requesting {action_name}...")
    await mqtt.control.request_device_status(device)

    try:
        await asyncio.wait_for(future, timeout=10)
    except TimeoutError:
        _logger.error(f"Timed out waiting for {action_name} response.")


async def _request_device_info_common(
    mqtt: NavienMqttClient,
    device: Device,
    parse_pydantic: bool = True,
) -> None:
    """Common logic for device info requests.

    Args:
        mqtt: MQTT client
        device: Device to request info for
        parse_pydantic: If True, parse with Pydantic and format output.
                       If False, print raw MQTT message.
    """
    future = asyncio.get_running_loop().create_future()

    if parse_pydantic:

        def on_device_info(info: Any) -> None:
            if not future.done():
                from .output_formatters import format_json_output

                print(format_json_output(info.model_dump()))
                future.set_result(None)

        await mqtt.subscribe_device_feature(device, on_device_info)
    else:

        def raw_callback(topic: str, message: dict[str, Any]) -> None:
            if not future.done():
                # Extract and print the raw feature/info portion
                if "response" in message and "feature" in message["response"]:
                    print(
                        json.dumps(
                            message["response"]["feature"],
                            indent=2,
                            default=_json_default_serializer,
                        )
                    )
                    future.set_result(None)
                elif "feature" in message:
                    print(
                        json.dumps(
                            message["feature"],
                            indent=2,
                            default=_json_default_serializer,
                        )
                    )
                    future.set_result(None)

        await mqtt.subscribe_device(device, raw_callback)

    action_name = (
        "device information" if parse_pydantic else "device information (raw)"
    )
    _logger.info(f"Requesting {action_name}...")
    await mqtt.control.request_device_info(device)

    try:
        await asyncio.wait_for(future, timeout=10)
    except TimeoutError:
        _logger.error(f"Timed out waiting for {action_name} response.")


async def handle_device_info_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """
    Request comprehensive device information via MQTT and print it.

    This fetches detailed device information including firmware versions,
    capabilities, temperature ranges, and feature availability - much more
    comprehensive than basic API device data.
    """
    await _request_device_info_common(mqtt, device, parse_pydantic=True)


async def handle_device_info_raw_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Request raw device information via MQTT and print it exactly as received.

    This is similar to handle_device_info_request but prints the raw MQTT
    message without Pydantic model conversions.
    """
    await _request_device_info_common(mqtt, device, parse_pydantic=False)


async def handle_get_controller_serial_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Request and display just the controller serial number."""
    serial_number = await get_controller_serial_number(mqtt, device)
    if serial_number:
        print(serial_number)
    else:
        _logger.error("Failed to retrieve controller serial number.")


async def handle_set_mode_request(
    mqtt: NavienMqttClient, device: Device, mode_name: str
) -> None:
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

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            responses.append(status)
            # Complete after receiving response
            future.set_result(None)

    # Subscribe to status updates to see the mode change result
    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        _logger.info(
            f"Setting operation mode to '{mode_name}' (mode ID: {mode_id})..."
        )

        # Send the mode change command
        await mqtt.control.set_dhw_mode(device, mode_id)

        # Wait for status response (mode change confirmation)
        try:
            await asyncio.wait_for(future, timeout=15)

            if responses:
                status = responses[0]
                from .output_formatters import format_json_output

                print(format_json_output(status.model_dump()))
                _logger.info(
                    f"Mode change successful. New mode: "
                    f"{status.operation_mode.name}"
                )
            else:
                _logger.warning(
                    "Mode command sent but no status response received"
                )

        except TimeoutError:
            _logger.error("Timed out waiting for mode change confirmation")

    except ValidationError as e:
        _logger.error(f"Invalid mode or parameters: {e}")
        if hasattr(e, "field"):
            _logger.info(f"Check the value for: {e.field}")
    except MqttError as e:
        _logger.error(f"MQTT error setting mode: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error setting mode: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error setting mode: {e}")


async def handle_set_dhw_temp_request(
    mqtt: NavienMqttClient, device: Device, temperature: float
) -> None:
    """
    Set DHW target temperature and display the response.

    Args:
        mqtt: MQTT client instance
        device: Device to control
        temperature: Target temperature in Fahrenheit (95-150°F)
    """
    # Validate temperature range
    if temperature < 95 or temperature > 150:
        _logger.error(
            f"Temperature {temperature}°F is out of range. "
            f"Valid range: 95-150°F"
        )
        return

    # Set up callback to capture status response after temperature change
    future = asyncio.get_running_loop().create_future()
    responses = []

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            responses.append(status)
            # Complete after receiving response
            future.set_result(None)

    # Subscribe to status updates to see the temperature change result
    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        _logger.info(f"Setting DHW target temperature to {temperature}°F...")

        # Send the temperature change command
        await mqtt.control.set_dhw_temperature(device, temperature)

        # Wait for status response (temperature change confirmation)
        try:
            await asyncio.wait_for(future, timeout=15)

            if responses:
                status = responses[0]
                from .output_formatters import format_json_output

                print(format_json_output(status.model_dump()))
                _logger.info(
                    f"Temperature change successful. New target: "
                    f"{status.dhw_target_temperature_setting}°F"
                )
            else:
                _logger.warning(
                    "Temperature command sent but no status response received"
                )

        except TimeoutError:
            _logger.error(
                "Timed out waiting for temperature change confirmation"
            )

    except ValidationError as e:
        _logger.error(f"Invalid temperature: {e}")
        if hasattr(e, "min_value") and hasattr(e, "max_value"):
            _logger.info(f"Valid range: {e.min_value}°F to {e.max_value}°F")
    except MqttError as e:
        _logger.error(f"MQTT error setting temperature: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error setting temperature: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error setting temperature: {e}")


async def handle_power_request(
    mqtt: NavienMqttClient, device: Device, power_on: bool
) -> None:
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

    def on_power_change_response(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    try:
        # Subscribe to status updates
        await mqtt.subscribe_device_status(device, on_power_change_response)

        # Send power command
        await mqtt.control.set_power(device, power_on)

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
                        "tankUpperTemperature": (
                            f"{status.tankUpperTemperature:.1f}°F"
                        ),
                        "tankLowerTemperature": (
                            f"{status.tankLowerTemperature:.1f}°F"
                        ),
                    },
                },
                indent=2,
            )
        )

    except TimeoutError:
        _logger.error(f"Timed out waiting for power {action} confirmation")

    except MqttError as e:
        _logger.error(f"MQTT error turning device {action}: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error turning device {action}: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error turning device {action}: {e}")


async def handle_get_reservations_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Request current reservation schedule from the device."""
    future = asyncio.get_running_loop().create_future()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        # Device responses have "response" field with actual data
        if not future.done() and "response" in message:
            # Decode and format the reservation data for human readability
            from nwp500.encoding import (
                decode_reservation_hex,
                decode_week_bitfield,
            )

            response = message.get("response", {})
            reservation_use = response.get("reservationUse", 0)
            reservation_hex = response.get("reservation", "")

            # Decode the hex string into structured entries
            if isinstance(reservation_hex, str):
                reservations = decode_reservation_hex(reservation_hex)
            else:
                # Already structured (shouldn't happen but handle it)
                reservations = (
                    reservation_hex if isinstance(reservation_hex, list) else []
                )

            # Format for display
            output = {
                "reservationUse": reservation_use,
                "reservationEnabled": reservation_use == 1,
                "reservations": [],
            }

            for idx, entry in enumerate(reservations, start=1):
                week_days = decode_week_bitfield(entry.get("week", 0))
                param_value = entry.get("param", 0)
                # Temperature is encoded as (display - 20), so display = param +
                # 20
                display_temp = param_value + 20

                formatted_entry = {
                    "number": idx,
                    "enabled": entry.get("enable") == 1,
                    "days": week_days,
                    "time": (
                        f"{entry.get('hour', 0):02d}:{entry.get('min', 0):02d}"
                    ),
                    "mode": entry.get("mode"),
                    "temperatureF": display_temp,
                    "raw": entry,
                }
                output["reservations"].append(formatted_entry)

            # Print formatted output
            print(
                json.dumps(output, indent=2, default=_json_default_serializer)
            )
            future.set_result(None)

    # Subscribe to all device-type messages to catch the response
    # Responses come on various patterns depending on the command
    device_type = device.device_info.device_type
    response_pattern = MqttTopicBuilder.command_topic(
        device_type, mac_address="+", suffix="#"
    )

    await mqtt.subscribe(response_pattern, raw_callback)
    _logger.info("Requesting current reservation schedule...")
    await mqtt.control.request_reservations(device)

    try:
        await asyncio.wait_for(future, timeout=10)
    except TimeoutError:
        _logger.error("Timed out waiting for reservation response.")


async def handle_update_reservations_request(
    mqtt: NavienMqttClient,
    device: Device,
    reservations_json: str,
    enabled: bool,
) -> None:
    """Update reservation schedule on the device."""
    try:
        reservations = json.loads(reservations_json)
        if not isinstance(reservations, list):
            _logger.error("Reservations must be a JSON array.")
            return
    except json.JSONDecodeError as e:
        _logger.error(f"Invalid JSON for reservations: {e}")
        return

    future = asyncio.get_running_loop().create_future()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        # Only process response messages, not request echoes
        if not future.done() and "response" in message:
            print(
                json.dumps(message, indent=2, default=_json_default_serializer)
            )
            future.set_result(None)

    # Subscribe to client-specific response topic pattern
    # Responses come on: cmd/{deviceType}/+/+/{clientId}/res/rsv/rd
    device_type = device.device_info.device_type
    client_id = mqtt.client_id
    response_topic = MqttTopicBuilder.response_topic(
        device_type, client_id, "rsv/rd"
    ).replace(f"navilink-{device.device_info.mac_address}", "+")
    # Note: The original pattern wascmd/{deviceType}/+/+/{clientId}/res/rsv/rd
    # which is slightly different from our standard builder.
    # But cmd/{device_type}/+/+/... is very permissive.
    # I'll use a more standard pattern if possible, but I'll stick to
    # something close to the original for now if it's meant to be a wildcard.
    response_topic = f"cmd/{device_type}/+/+/{client_id}/res/rsv/rd"

    await mqtt.subscribe(response_topic, raw_callback)
    _logger.info(f"Updating reservation schedule (enabled={enabled})...")
    await mqtt.control.update_reservations(
        device, reservations, enabled=enabled
    )

    try:
        await asyncio.wait_for(future, timeout=10)
    except TimeoutError:
        _logger.error("Timed out waiting for reservation update response.")


async def handle_get_tou_request(
    mqtt: NavienMqttClient, device: Device, api_client: Any
) -> None:
    """Request Time-of-Use settings from the REST API."""
    try:
        # Get controller serial number via MQTT
        controller_id = await get_controller_serial_number(mqtt, device)
        if not controller_id:
            _logger.error("Failed to retrieve controller serial number.")
            return

        _logger.info(f"Controller ID: {controller_id}")
        _logger.info("Fetching Time-of-Use settings from REST API...")

        # Get TOU info from REST API
        mac_address = device.device_info.mac_address
        additional_value = device.device_info.additional_value

        tou_info = await api_client.get_tou_info(
            mac_address=mac_address,
            additional_value=additional_value,
            controller_id=controller_id,
            user_type="O",
        )

        # Print the TOU info
        print(
            json.dumps(
                {
                    "registerPath": tou_info.register_path,
                    "sourceType": tou_info.source_type,
                    "controllerId": tou_info.controller_id,
                    "manufactureId": tou_info.manufacture_id,
                    "name": tou_info.name,
                    "utility": tou_info.utility,
                    "zipCode": tou_info.zip_code,
                    "schedule": [
                        {
                            "season": schedule.season,
                            "interval": schedule.intervals,
                        }
                        for schedule in tou_info.schedule
                    ],
                },
                indent=2,
            )
        )

    except MqttError as e:
        _logger.error(f"MQTT error fetching TOU settings: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error fetching TOU settings: {e}")
    except Exception as e:
        _logger.error(
            f"Unexpected error fetching TOU settings: {e}", exc_info=True
        )


async def handle_set_tou_enabled_request(
    mqtt: NavienMqttClient, device: Device, enabled: bool
) -> None:
    """Enable or disable Time-of-Use functionality."""
    action = "enabling" if enabled else "disabling"
    _logger.info(f"Time-of-Use {action}...")

    future = asyncio.get_running_loop().create_future()
    responses = []

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            responses.append(status)
            future.set_result(None)

    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        await mqtt.control.set_tou_enabled(device, enabled)

        try:
            await asyncio.wait_for(future, timeout=10)
            if responses:
                status = responses[0]
                from .output_formatters import format_json_output

                print(format_json_output(status.model_dump()))
                _logger.info(f"TOU {action} successful.")
            else:
                _logger.warning("TOU command sent but no response received")
        except TimeoutError:
            _logger.error(f"Timed out waiting for TOU {action} confirmation")

    except MqttError as e:
        _logger.error(f"MQTT error {action} TOU: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error {action} TOU: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error {action} TOU: {e}")


async def handle_get_energy_request(
    mqtt: NavienMqttClient, device: Device, year: int, months: list[int]
) -> None:
    """Request energy usage data for specified months."""
    future = asyncio.get_running_loop().create_future()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        if not future.done():
            print(
                json.dumps(message, indent=2, default=_json_default_serializer)
            )
            future.set_result(None)

    # Subscribe to energy usage response (uses default device topic)
    await mqtt.subscribe_device(device, raw_callback)
    _logger.info(f"Requesting energy usage for {year}, months: {months}...")
    await mqtt.control.request_energy_usage(device, year, months)

    try:
        await asyncio.wait_for(future, timeout=15)
    except TimeoutError:
        _logger.error("Timed out waiting for energy usage response.")


async def handle_enable_demand_response_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Enable utility demand response participation."""
    _logger.info("Enabling demand response...")

    future = asyncio.get_running_loop().create_future()

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        await mqtt.control.enable_demand_response(device)

        try:
            await asyncio.wait_for(future, timeout=10)
            _logger.info("Demand response enabled successfully!")
        except TimeoutError:
            _logger.error("Timed out waiting for response confirmation")

    except MqttError as e:
        _logger.error(f"MQTT error enabling demand response: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error enabling demand response: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error enabling demand response: {e}")


async def handle_disable_demand_response_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Disable utility demand response participation."""
    _logger.info("Disabling demand response...")

    future = asyncio.get_running_loop().create_future()

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        await mqtt.control.disable_demand_response(device)

        try:
            await asyncio.wait_for(future, timeout=10)
            _logger.info("Demand response disabled successfully!")
        except TimeoutError:
            _logger.error("Timed out waiting for response confirmation")

    except MqttError as e:
        _logger.error(f"MQTT error disabling demand response: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error disabling demand response: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error disabling demand response: {e}")


async def handle_reset_air_filter_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Reset air filter maintenance timer."""
    _logger.info("Resetting air filter timer...")

    future = asyncio.get_running_loop().create_future()

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        await mqtt.control.reset_air_filter(device)

        try:
            await asyncio.wait_for(future, timeout=10)
            _logger.info("Air filter timer reset successfully!")
        except TimeoutError:
            _logger.error("Timed out waiting for response confirmation")

    except MqttError as e:
        _logger.error(f"MQTT error resetting air filter: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error resetting air filter: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error resetting air filter: {e}")


async def handle_set_vacation_days_request(
    mqtt: NavienMqttClient, device: Device, days: int
) -> None:
    """Set vacation mode duration in days."""
    _logger.info(f"Setting vacation mode to {days} days...")

    future = asyncio.get_running_loop().create_future()

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        await mqtt.control.set_vacation_days(device, days)

        try:
            await asyncio.wait_for(future, timeout=10)
            _logger.info(f"Vacation mode set to {days} days successfully!")
        except TimeoutError:
            _logger.error("Timed out waiting for response confirmation")

    except ValidationError as e:
        _logger.error(f"Invalid vacation days: {e}")
        if hasattr(e, "min_value"):
            _logger.info(f"Valid range: {e.min_value}+ days")
    except MqttError as e:
        _logger.error(f"MQTT error setting vacation days: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error setting vacation days: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error setting vacation days: {e}")


async def handle_set_recirculation_mode_request(
    mqtt: NavienMqttClient, device: Device, mode: int
) -> None:
    """Set recirculation pump operation mode."""
    mode_names = {
        1: "Always On",
        2: "Button Only",
        3: "Schedule",
        4: "Temperature",
    }
    mode_name = mode_names.get(mode, "Unknown")
    _logger.info(f"Setting recirculation mode to {mode_name} (mode {mode})...")

    future = asyncio.get_running_loop().create_future()

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        await mqtt.control.set_recirculation_mode(device, mode)

        try:
            await asyncio.wait_for(future, timeout=10)
            _logger.info(f"Recirculation mode set to {mode_name} successfully!")
        except TimeoutError:
            _logger.error("Timed out waiting for response confirmation")

    except ValidationError as e:
        _logger.error(f"Invalid recirculation mode: {e}")
        _logger.info(
            "Valid modes: 1=Always On, 2=Button Only, 3=Schedule, 4=Temperature"
        )
    except MqttError as e:
        _logger.error(f"MQTT error setting recirculation mode: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error setting recirculation mode: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error setting recirculation mode: {e}")


async def handle_trigger_recirculation_hot_button_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Trigger the recirculation pump hot button."""
    _logger.info("Triggering recirculation pump hot button...")

    future = asyncio.get_running_loop().create_future()

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        await mqtt.control.trigger_recirculation_hot_button(device)

        try:
            await asyncio.wait_for(future, timeout=10)
            _logger.info(
                "Recirculation pump hot button triggered successfully!"
            )
        except TimeoutError:
            _logger.error("Timed out waiting for response confirmation")

    except DeviceCapabilityError as e:
        _logger.error(f"Device does not support recirculation: {e}")
    except MqttError as e:
        _logger.error(f"MQTT error triggering hot button: {e}")
    except DeviceError as e:
        _logger.error(f"Device error triggering hot button: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error triggering hot button: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error triggering hot button: {e}")


async def handle_configure_reservation_water_program_request(
    mqtt: NavienMqttClient, device: Device
) -> None:
    """Enable/configure water program reservation mode."""
    _logger.info("Configuring water program reservation mode...")

    future = asyncio.get_running_loop().create_future()

    def on_status_response(status: DeviceStatus) -> None:
        if not future.done():
            future.set_result(status)

    await mqtt.subscribe_device_status(device, on_status_response)

    try:
        await mqtt.control.configure_reservation_water_program(device)

        try:
            await asyncio.wait_for(future, timeout=10)
            _logger.info(
                "Water program reservation mode configured successfully!"
            )
        except TimeoutError:
            _logger.error("Timed out waiting for response confirmation")

    except MqttError as e:
        _logger.error(f"MQTT error configuring water program: {e}")
    except Nwp500Error as e:
        _logger.error(f"Error configuring water program: {e}")
    except Exception as e:
        _logger.error(f"Unexpected error configuring water program: {e}")
