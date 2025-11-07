"""
MQTT Periodic Request Manager for Navien devices.

This module handles periodic/scheduled requests to keep device information
and status up-to-date. Features include:
- Configurable request intervals
- Automatic skip when disconnected
- Graceful task cancellation
- Per-device, per-type task management
"""

import asyncio
import contextlib
import logging
from typing import Any, Callable, Optional

from awscrt.exceptions import AwsCrtError

from .models import Device
from .mqtt_utils import PeriodicRequestType

__author__ = "Emmanuel Levijarvi"

_logger = logging.getLogger(__name__)


class MqttPeriodicRequestManager:
    """
    Manages periodic requests for device information and status.

    Features:
    - Independent tasks per device and request type
    - Automatic skip when disconnected (with throttled logging)
    - Graceful cancellation on disconnect
    - Error recovery and retry
    """

    def __init__(
        self,
        is_connected_func: Callable[[], bool],
        request_device_info_func: Callable[..., Any],
        request_device_status_func: Callable[..., Any],
    ):
        """
        Initialize periodic request manager.

        Args:
            is_connected_func: Function that returns connection status
            request_device_info_func: Async function to request device info
            request_device_status_func: Async function to request device status
        """
        self._is_connected = is_connected_func
        self._request_device_info = request_device_info_func
        self._request_device_status = request_device_status_func

        # Track active periodic tasks
        self._periodic_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def active_task_count(self) -> int:
        """Get number of active periodic tasks."""
        return len(self._periodic_tasks)

    async def start_periodic_requests(
        self,
        device: Device,
        request_type: PeriodicRequestType = PeriodicRequestType.DEVICE_STATUS,
        period_seconds: float = 300.0,
    ) -> None:
        """
        Start sending periodic requests for device information or status.

        This optional helper continuously sends requests at a specified
        interval.
        It can be used to keep device information or status up-to-date.

        Args:
            device: Device object
            request_type: Type of request (DEVICE_INFO or DEVICE_STATUS)
            period_seconds: Time between requests in seconds (default: 300 = 5
            minutes)

        Example:
            >>> # Start periodic status requests (default)
            >>> await manager.start_periodic_requests(device)
            >>>
            >>> # Start periodic device info requests
            >>> await manager.start_periodic_requests(
            ...     device,
            ...     request_type=PeriodicRequestType.DEVICE_INFO
            ... )
            >>>
            >>> # Custom period: request every 60 seconds
            >>> await manager.start_periodic_requests(
            ...     device,
            ...     period_seconds=60
            ... )

        Note:
            - Only one periodic task per request type per device
            - Call stop_periodic_requests() to stop a task
            - All tasks automatically stop when client disconnects
        """
        device_id = device.device_info.mac_address
        # Do not log MAC address; use a generic placeholder to avoid leaking
        # sensitive information
        redacted_device_id = "DEVICE_ID_REDACTED"
        task_name = f"periodic_{request_type.value}_{device_id}"

        # Stop existing task for this device/type if any
        if task_name in self._periodic_tasks:
            _logger.info(
                f"Stopping existing periodic {request_type.value} task"
            )
            await self.stop_periodic_requests(device, request_type)

        async def periodic_request() -> None:
            """Execute periodic requests for device information or status.

            This coroutine runs continuously, sending requests at the configured
            interval. It automatically skips requests when disconnected and
            provides throttled logging to reduce noise.
            """
            _logger.info(
                f"Started periodic {request_type.value} requests for "
                f"{redacted_device_id} (every {period_seconds}s)"
            )

            # Track consecutive skips for throttled logging
            consecutive_skips = 0

            while True:
                try:
                    if not self._is_connected():
                        consecutive_skips += 1
                        # Log warning only on first skip and then every 10th
                        # skip to reduce noise
                        if (
                            consecutive_skips == 1
                            or consecutive_skips % 10 == 0
                        ):
                            _logger.warning(
                                "Not connected, skipping %s request for %s "
                                "(skipped %d time%s)",
                                request_type.value,
                                redacted_device_id,
                                consecutive_skips,
                                "s" if consecutive_skips > 1 else "",
                            )
                        else:
                            _logger.debug(
                                "Not connected, skipping %s request for %s",
                                request_type.value,
                                redacted_device_id,
                            )
                    else:
                        # Reset skip counter when connected
                        if consecutive_skips > 0:
                            _logger.info(
                                "Reconnected, resuming %s requests for %s "
                                "(had skipped %d)",
                                request_type.value,
                                redacted_device_id,
                                consecutive_skips,
                            )
                            consecutive_skips = 0

                        # Send appropriate request type
                        if request_type == PeriodicRequestType.DEVICE_INFO:
                            await self._request_device_info(device)
                        elif request_type == PeriodicRequestType.DEVICE_STATUS:
                            await self._request_device_status(device)

                        _logger.debug(
                            "Sent periodic %s request for %s",
                            request_type.value,
                            redacted_device_id,
                        )

                    # Wait for the specified period
                    await asyncio.sleep(period_seconds)

                except asyncio.CancelledError:
                    _logger.info(
                        f"Periodic {request_type.value} requests cancelled "
                        f"for {redacted_device_id}"
                    )
                    break
                except (AwsCrtError, RuntimeError) as e:
                    # Handle known MQTT errors gracefully
                    error_name = (
                        getattr(e, "name", None)
                        if isinstance(e, AwsCrtError)
                        else None
                    )

                    if (
                        error_name
                        == "AWS_ERROR_MQTT_CANCELLED_FOR_CLEAN_SESSION"
                    ):
                        _logger.debug(
                            "Periodic %s request cancelled due to clean "
                            "session for %s. This is expected during "
                            "reconnection.",
                            request_type.value,
                            redacted_device_id,
                        )
                    elif error_name == "AWS_ERROR_MQTT_CONNECTION_DESTROYED":
                        _logger.warning(
                            "MQTT connection destroyed during %s request "
                            "for %s. This can occur during AWS-initiated "
                            "disconnections (e.g., 24-hour timeout). "
                            "Reconnection will be attempted automatically.",
                            request_type.value,
                            redacted_device_id,
                        )
                    else:
                        _logger.error(
                            "Error in periodic %s request for %s: %s",
                            request_type.value,
                            redacted_device_id,
                            e,
                            exc_info=True,
                        )
                    # Continue despite errors
                    await asyncio.sleep(period_seconds)

        # Create and store the task
        task = asyncio.create_task(periodic_request())
        self._periodic_tasks[task_name] = task

        _logger.info(
            f"Started periodic {request_type.value} task for "
            f"{redacted_device_id} with period {period_seconds}s"
        )

    async def stop_periodic_requests(
        self,
        device: Device,
        request_type: Optional[PeriodicRequestType] = None,
    ) -> None:
        """
        Stop sending periodic requests for a device.

        Args:
            device: Device object
            request_type: Type of request to stop. If None, stops all types
                          for this device.

        Example:
            >>> # Stop specific request type
            >>> await manager.stop_periodic_requests(
            ...     device,
            ...     PeriodicRequestType.DEVICE_STATUS
            ... )
            >>>
            >>> # Stop all periodic requests for device
            >>> await manager.stop_periodic_requests(device)
        """
        device_id = device.device_info.mac_address

        if request_type is None:
            # Stop all request types for this device
            types_to_stop = [
                PeriodicRequestType.DEVICE_INFO,
                PeriodicRequestType.DEVICE_STATUS,
            ]
        else:
            types_to_stop = [request_type]

        stopped_count = 0
        for req_type in types_to_stop:
            task_name = f"periodic_{req_type.value}_{device_id}"

            if task_name in self._periodic_tasks:
                task = self._periodic_tasks[task_name]
                task.cancel()

                with contextlib.suppress(asyncio.CancelledError):
                    await task

                del self._periodic_tasks[task_name]
                stopped_count += 1

        if stopped_count == 0:
            _logger.debug(
                "No periodic tasks found for device"
                + (f" (type={request_type.value})" if request_type else "")
            )

    async def stop_all_periodic_tasks(
        self, reason: Optional[str] = None
    ) -> None:
        """
        Stop all periodic request tasks.

        This is automatically called when disconnecting.

        Args:
            reason: Optional reason for logging context (e.g., "connection
            failure")

        Example:
            >>> await manager.stop_all_periodic_tasks()
            >>> await manager.stop_all_periodic_tasks(reason="disconnect")
        """
        if not self._periodic_tasks:
            return

        task_count = len(self._periodic_tasks)
        reason_msg = f" due to {reason}" if reason else ""
        _logger.info(f"Stopping {task_count} periodic task(s){reason_msg}")

        # Cancel all tasks
        for task in self._periodic_tasks.values():
            task.cancel()

        # Wait for all to complete
        await asyncio.gather(
            *self._periodic_tasks.values(), return_exceptions=True
        )

        self._periodic_tasks.clear()
        _logger.info("All periodic tasks stopped")

    # Convenience methods for common use cases

    async def start_periodic_device_info_requests(
        self, device: Device, period_seconds: float = 300.0
    ) -> None:
        """
        Start sending periodic device info requests.

        This is a convenience wrapper around start_periodic_requests().

        Args:
            device: Device object
            period_seconds: Time between requests in seconds (default: 300 = 5
            minutes)
        """
        await self.start_periodic_requests(
            device=device,
            request_type=PeriodicRequestType.DEVICE_INFO,
            period_seconds=period_seconds,
        )

    async def start_periodic_device_status_requests(
        self, device: Device, period_seconds: float = 300.0
    ) -> None:
        """
        Start sending periodic device status requests.

        This is a convenience wrapper around start_periodic_requests().

        Args:
            device: Device object
            period_seconds: Time between requests in seconds (default: 300 = 5
            minutes)
        """
        await self.start_periodic_requests(
            device=device,
            request_type=PeriodicRequestType.DEVICE_STATUS,
            period_seconds=period_seconds,
        )

    async def stop_periodic_device_info_requests(self, device: Device) -> None:
        """
        Stop sending periodic device info requests for a device.

        This is a convenience wrapper around stop_periodic_requests().

        Args:
            device: Device object
        """
        await self.stop_periodic_requests(
            device, PeriodicRequestType.DEVICE_INFO
        )

    async def stop_periodic_device_status_requests(
        self, device: Device
    ) -> None:
        """
        Stop sending periodic device status requests for a device.

        This is a convenience wrapper around stop_periodic_requests().

        Args:
            device: Device object
        """
        await self.stop_periodic_requests(
            device, PeriodicRequestType.DEVICE_STATUS
        )
