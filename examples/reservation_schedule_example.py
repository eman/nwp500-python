#!/usr/bin/env python3
"""Example: Configure reservation program using documented MQTT payloads."""

import asyncio
import os
import sys
from typing import Any

from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient
from nwp500.encoding import build_reservation_entry, decode_week_bitfield


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

        # Build a weekday morning reservation for High Demand mode at 140°F
        weekday_reservation = build_reservation_entry(
            enabled=True,
            days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            hour=6,
            minute=30,
            mode_id=4,  # High Demand
            temperature_f=140.0,  # Temperature in Fahrenheit
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
                week_days = decode_week_bitfield(entry.get("week", 0))
                # Convert half-degrees Celsius param back to Fahrenheit for display
                param = entry.get("param", 0)
                temp_f = (param / 2.0) * 9 / 5 + 32
                print(
                    "   - #{idx}: {time:02d}:{minute:02d} mode={mode} temp={temp:.1f}°F days={days}".format(
                        idx=idx,
                        time=entry.get("hour", 0),
                        minute=entry.get("min", 0),
                        mode=entry.get("mode"),
                        temp=temp_f,
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
