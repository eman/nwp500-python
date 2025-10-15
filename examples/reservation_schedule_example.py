#!/usr/bin/env python3
"""Example: Configure reservation program using documented MQTT payloads."""

import asyncio
import os
import sys
from typing import Any

from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient


async def main() -> None:
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        sys.exit(1)

    async with NavienAuthClient(email, password) as auth_client:
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()
        if not device:
            print("No devices found for this account")
            return

        # Build a weekday morning reservation for High Demand mode at 140°F display (120°F message)
        weekday_reservation = NavienAPIClient.build_reservation_entry(
            enabled=True,
            days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            hour=6,
            minute=30,
            mode_id=4,  # High Demand
            param=120,  # Remember: message value is 20°F lower than display value
        )

        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()

        # Listen for reservation responses so we can print the updated schedule
        response_topic = f"cmd/{device.device_info.device_type}/{mqtt_client.config.client_id}/res/rsv/rd"

        def on_reservation_update(topic: str, message: dict[str, Any]) -> None:
            response = message.get("response", {})
            reservations = response.get("reservation", [])
            print("\nReceived reservation response:")
            print(
                f"  reservationUse: {response.get('reservationUse')} (1=enabled, 2=disabled)"
            )
            print(f"  entries: {len(reservations)}")
            for idx, entry in enumerate(reservations, start=1):
                week_days = NavienAPIClient.decode_week_bitfield(entry.get("week", 0))
                display_temp = entry.get("param", 0) + 20
                print(
                    "   - #{idx}: {time:02d}:{minute:02d} mode={mode} display_temp={temp}F days={days}".format(
                        idx=idx,
                        time=entry.get("hour", 0),
                        minute=entry.get("min", 0),
                        mode=entry.get("mode"),
                        temp=display_temp,
                        days=", ".join(week_days) or "<none>",
                    )
                )

        await mqtt_client.subscribe(response_topic, on_reservation_update)

        print("Sending reservation program update...")
        await mqtt_client.update_reservations(
            device, [weekday_reservation], enabled=True
        )

        print("Requesting current reservation program...")
        await mqtt_client.request_reservations(device)

        print("Waiting up to 15 seconds for reservation responses...")
        await asyncio.sleep(15)

        await mqtt_client.disconnect()
        print("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled by user")
