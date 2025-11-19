"""Monitoring and periodic status polling."""

import asyncio
import logging

from nwp500 import Device, DeviceStatus, NavienMqttClient

from .output_formatters import write_status_to_csv

_logger = logging.getLogger(__name__)


async def handle_monitoring(
    mqtt: NavienMqttClient, device: Device, output_file: str
) -> None:
    """
    Start periodic monitoring and write status to CSV.

    Args:
        mqtt: MQTT client instance
        device: Device to monitor
        output_file: Path to output CSV file

    This function runs indefinitely, polling the device every 30 seconds
    and writing status updates to a CSV file.
    """
    _logger.info(
        f"Starting periodic monitoring. Writing updates to {output_file}"
    )
    _logger.info("Press Ctrl+C to stop.")

    def on_status_update(status: DeviceStatus) -> None:
        _logger.info(
            f"Received status update: Temp={status.dhw_temperature}°F, "
            f"Power={'ON' if status.dhw_use else 'OFF'}"
        )
        write_status_to_csv(output_file, status)

    await mqtt.subscribe_device_status(device, on_status_update)
    await mqtt.start_periodic_device_status_requests(device, period_seconds=30)
    await mqtt.request_device_status(device)  # Get an initial status right away

    # Keep the script running indefinitely
    await asyncio.Event().wait()
