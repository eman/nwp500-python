"""Typed device-subscription proxies for :class:`NavienMqttClient`.

This mixin holds the public ``subscribe_*``/``unsubscribe_*`` convenience
methods that forward to the
:class:`~nwp500.mqtt.subscriptions.MqttSubscriptionManager`.
Splitting them out of ``client.py`` keeps :class:`NavienMqttClient` focused on
connection orchestration while preserving its public API surface.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from ..exceptions import MqttNotConnectedError
from .subscriptions import MqttSubscriptionManager

if TYPE_CHECKING:
    from ..models import (
        Device,
        DeviceFeature,
        DeviceStatus,
        EnergyUsageResponse,
        RecirculationSchedule,
        ReservationSchedule,
        TOUReservationSchedule,
        WeeklyReservationSchedule,
    )

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"


class DeviceSubscriptionsMixin:
    """Public typed device subscriptions that delegate to the manager."""

    # Provided by NavienMqttClient.__init__.
    _connected: bool
    _subscription_manager: MqttSubscriptionManager | None

    async def subscribe_device(
        self, device: Device, callback: Callable[[str, dict[str, Any]], None]
    ) -> int:
        """
        Subscribe to all messages from a specific device.

        Args:
            device: Device object
            callback: Message handler

        Returns:
            Subscription packet ID
        """
        if not self._connected or not self._subscription_manager:
            raise MqttNotConnectedError("Not connected to MQTT broker")

        # Delegate to subscription manager
        return await self._subscription_manager.subscribe_device(
            device, callback
        )

    async def _delegate_subscription(self, method_name: str, *args: Any) -> int:
        """Helper to delegate subscription to subscription manager."""
        if not self._connected or not self._subscription_manager:
            raise MqttNotConnectedError("Not connected to MQTT broker")
        method = getattr(self._subscription_manager, method_name)
        return cast(int, await method(*args))

    async def subscribe_device_status(
        self, device: Device, callback: Callable[[DeviceStatus], None]
    ) -> int:
        """Subscribe to device status messages with automatic parsing."""
        return await self._delegate_subscription(
            "subscribe_device_status", device, callback
        )

    async def unsubscribe_device_status(
        self, device: Device, callback: Callable[[DeviceStatus], None]
    ) -> None:
        """Unsubscribe a specific device status callback."""
        if not self._connected or not self._subscription_manager:
            return
        await self._subscription_manager.unsubscribe_device_status(
            device, callback
        )

    async def subscribe_device_feature(
        self, device: Device, callback: Callable[[DeviceFeature], None]
    ) -> int:
        """Subscribe to device feature/info messages with automatic parsing."""
        return await self._delegate_subscription(
            "subscribe_device_feature", device, callback
        )

    async def unsubscribe_device_feature(
        self, device: Device, callback: Callable[[DeviceFeature], None]
    ) -> None:
        """Unsubscribe a specific device feature callback."""
        if not self._connected or not self._subscription_manager:
            return
        await self._subscription_manager.unsubscribe_device_feature(
            device, callback
        )

    async def subscribe_energy_usage(
        self,
        device: Device,
        callback: Callable[[EnergyUsageResponse], None],
    ) -> int:
        """Subscribe to energy usage query responses with automatic parsing."""
        return await self._delegate_subscription(
            "subscribe_energy_usage", device, callback
        )

    async def unsubscribe_energy_usage(
        self,
        device: Device,
        callback: Callable[[EnergyUsageResponse], None],
    ) -> None:
        """Unsubscribe a specific energy usage callback."""
        if not self._connected or not self._subscription_manager:
            return
        await self._subscription_manager.unsubscribe_energy_usage(
            device, callback
        )

    async def subscribe_reservation_response(
        self,
        device: Device,
        callback: Callable[[ReservationSchedule], None],
    ) -> int:
        """Subscribe to reservation read responses with automatic parsing."""
        return await self._delegate_subscription(
            "subscribe_reservation_response", device, callback
        )

    async def unsubscribe_reservation_response(
        self,
        device: Device,
        callback: Callable[[ReservationSchedule], None],
    ) -> None:
        """Unsubscribe a specific reservation response callback."""
        if not self._connected or not self._subscription_manager:
            return
        await self._subscription_manager.unsubscribe_reservation_response(
            device, callback
        )

    async def subscribe_weekly_reservation_response(
        self,
        device: Device,
        callback: Callable[[WeeklyReservationSchedule], None],
    ) -> int:
        """Subscribe to weekly reservation read responses."""
        return await self._delegate_subscription(
            "subscribe_weekly_reservation_response", device, callback
        )

    async def unsubscribe_weekly_reservation_response(
        self,
        device: Device,
        callback: Callable[[WeeklyReservationSchedule], None],
    ) -> None:
        """Unsubscribe a specific weekly reservation callback."""
        if not self._connected or not self._subscription_manager:
            return
        manager = self._subscription_manager
        await manager.unsubscribe_weekly_reservation_response(device, callback)

    async def subscribe_recirculation_schedule_response(
        self,
        device: Device,
        callback: Callable[[RecirculationSchedule], None],
    ) -> int:
        """Subscribe to recirculation schedule read responses."""
        return await self._delegate_subscription(
            "subscribe_recirculation_schedule_response", device, callback
        )

    async def unsubscribe_recirculation_schedule_response(
        self,
        device: Device,
        callback: Callable[[RecirculationSchedule], None],
    ) -> None:
        """Unsubscribe a specific recirculation schedule callback."""
        if not self._connected or not self._subscription_manager:
            return
        manager = self._subscription_manager
        await manager.unsubscribe_recirculation_schedule_response(
            device, callback
        )

    async def subscribe_tou_response(
        self,
        device: Device,
        callback: Callable[[TOUReservationSchedule], None],
    ) -> int:
        """Subscribe to Time-of-Use schedule read responses with automatic
        parsing.

        Subscribes to the ``tou/rd`` response topic for the given device.
        The callback receives a fully-parsed
        :class:`~nwp500.models.TOUReservationSchedule` whenever the device
        responds to a TOU read or configure request (triggered by
        :meth:`request_tou_settings` or :meth:`configure_tou_schedule`).

        Args:
            device: Device whose TOU responses to receive.
            callback: Called with the parsed schedule on each response.

        Returns:
            Publish packet ID from the MQTT subscribe call.
        """
        return await self._delegate_subscription(
            "subscribe_tou_response", device, callback
        )

    async def unsubscribe_tou_response(
        self,
        device: Device,
        callback: Callable[[TOUReservationSchedule], None],
    ) -> None:
        """Unsubscribe a specific TOU response callback."""
        if not self._connected or not self._subscription_manager:
            return
        await self._subscription_manager.unsubscribe_tou_response(
            device, callback
        )
