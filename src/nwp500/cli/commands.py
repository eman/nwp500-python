"""Command handlers for CLI operations."""

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

from nwp500 import Device, DeviceStatus, NavienMqttClient

from .output_formatters import _json_default_serializer

_logger = logging.getLogger(__name__)


async def handle_status_request(mqtt: NavienMqttClient, device: Device) -> None:
    """Request device status once and print it."""
    future = asyncio.get_running_loop().create_future()

    def on_status(status: DeviceStatus) -> None:
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


async def handle_status_raw_request(mqtt: NavienMqttClient, device: Device) -> None:
    """Request device status once and print raw MQTT data (no conversions)."""
    future = asyncio.get_running_loop().create_future()

    # Subscribe to the raw MQTT topic to capture data before conversion
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


async def handle_device_info_request(mqtt: NavienMqttClient, device: Device) -> None:
    """
    Request comprehensive device information via MQTT and print it.

    This fetches detailed device information including firmware versions,
    capabilities, temperature ranges, and feature availability - much more
    comprehensive than basic API device data.
    """
    future = asyncio.get_running_loop().create_future()

    def on_device_info(info: Any) -> None:
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


async def handle_device_feature_request(mqtt: NavienMqttClient, device: Device) -> None:
    """Request device feature information once and print it."""
    future = asyncio.get_running_loop().create_future()

    def on_feature(feature: Any) -> None:
        if not future.done():
            print(json.dumps(asdict(feature), indent=2, default=_json_default_serializer))
            future.set_result(None)

    await mqtt.subscribe_device_feature(device, on_feature)
    _logger.info("Requesting device feature information...")
    # Note: request_device_feature method does not exist in NavienMqttClient
    await mqtt.request_device_info(device)

    try:
        await asyncio.wait_for(future, timeout=10)
    except asyncio.TimeoutError:
        _logger.error("Timed out waiting for device feature response.")


async def handle_set_mode_request(mqtt: NavienMqttClient, device: Device, mode_name: str) -> None:
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


async def handle_set_dhw_temp_request(
    mqtt: NavienMqttClient, device: Device, temperature: int
) -> None:
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

    def on_status_response(status: DeviceStatus) -> None:
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


async def handle_power_request(mqtt: NavienMqttClient, device: Device, power_on: bool) -> None:
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


async def handle_get_reservations_request(mqtt: NavienMqttClient, device: Device) -> None:
    """Request current reservation schedule from the device."""
    future = asyncio.get_running_loop().create_future()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        if not future.done():
            # Print the full reservation response
            print(json.dumps(message, indent=2, default=_json_default_serializer))
            future.set_result(None)

    # Subscribe to reservation response topic
    device_type = device.device_info.device_type
    response_topic = f"cmd/{device_type}/+/res/rsv/rd"

    await mqtt.subscribe(response_topic, raw_callback)
    _logger.info("Requesting current reservation schedule...")
    await mqtt.request_reservations(device)

    try:
        await asyncio.wait_for(future, timeout=10)
    except asyncio.TimeoutError:
        _logger.error("Timed out waiting for reservation response.")


async def handle_update_reservations_request(
    mqtt: NavienMqttClient, device: Device, reservations_json: str, enabled: bool
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
        if not future.done():
            print(json.dumps(message, indent=2, default=_json_default_serializer))
            future.set_result(None)

    # Subscribe to reservation response topic
    device_type = device.device_info.device_type
    response_topic = f"cmd/{device_type}/+/res/rsv/rd"

    await mqtt.subscribe(response_topic, raw_callback)
    _logger.info(f"Updating reservation schedule (enabled={enabled})...")
    await mqtt.update_reservations(device, reservations, enabled=enabled)

    try:
        await asyncio.wait_for(future, timeout=10)
    except asyncio.TimeoutError:
        _logger.error("Timed out waiting for reservation update response.")


async def handle_get_tou_request(
    mqtt: NavienMqttClient, device: Device, serial_number: str
) -> None:
    """Request Time-of-Use settings from the device."""
    if not serial_number:
        _logger.error("Controller serial number is required. Use --tou-serial option.")
        return

    future = asyncio.get_running_loop().create_future()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        if not future.done():
            print(json.dumps(message, indent=2, default=_json_default_serializer))
            future.set_result(None)

    # Subscribe to TOU response topic
    device_type = device.device_info.device_type
    response_topic = f"cmd/{device_type}/+/res/tou/rd"

    await mqtt.subscribe(response_topic, raw_callback)
    _logger.info("Requesting Time-of-Use settings...")
    await mqtt.request_tou_settings(device, serial_number)

    try:
        await asyncio.wait_for(future, timeout=10)
    except asyncio.TimeoutError:
        _logger.error("Timed out waiting for TOU settings response.")


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
        await mqtt.set_tou_enabled(device, enabled)

        try:
            await asyncio.wait_for(future, timeout=10)
            if responses:
                status = responses[0]
                print(json.dumps(asdict(status), indent=2, default=_json_default_serializer))
                _logger.info(f"TOU {action} successful.")
            else:
                _logger.warning("TOU command sent but no response received")
        except asyncio.TimeoutError:
            _logger.error(f"Timed out waiting for TOU {action} confirmation")

    except Exception as e:
        _logger.error(f"Error {action} TOU: {e}")


async def handle_get_energy_request(
    mqtt: NavienMqttClient, device: Device, year: int, months: list[int]
) -> None:
    """Request energy usage data for specified months."""
    future = asyncio.get_running_loop().create_future()

    def raw_callback(topic: str, message: dict[str, Any]) -> None:
        if not future.done():
            print(json.dumps(message, indent=2, default=_json_default_serializer))
            future.set_result(None)

    # Subscribe to energy usage response (uses default device topic)
    await mqtt.subscribe_device(device, raw_callback)
    _logger.info(f"Requesting energy usage for {year}, months: {months}...")
    await mqtt.request_energy_usage(device, year, months)

    try:
        await asyncio.wait_for(future, timeout=15)
    except asyncio.TimeoutError:
        _logger.error("Timed out waiting for energy usage response.")
