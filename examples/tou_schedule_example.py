#!/usr/bin/env python3
"""Example: Configure Time-of-Use (TOU) pricing schedule over MQTT."""

import asyncio
import os
import sys
from typing import Any

from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient


async def _wait_for_controller_serial(mqtt_client: NavienMqttClient, device) -> str:
    loop = asyncio.get_running_loop()
    feature_future: asyncio.Future = loop.create_future()

    def capture_feature(feature) -> None:
        if not feature_future.done():
            feature_future.set_result(feature)

    mqtt_client.once("feature_received", capture_feature)
    await mqtt_client.request_device_info(device)
    feature = await asyncio.wait_for(feature_future, timeout=15)
    return feature.controllerSerialNumber


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

        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()

        print("Requesting controller serial number via device info...")
        try:
            controller_serial = await _wait_for_controller_serial(mqtt_client, device)
        except asyncio.TimeoutError:
            print("Timed out waiting for device features")
            await mqtt_client.disconnect()
            return

        print("Controller serial number acquired.")

        # Build two TOU periods as documented in MQTT_MESSAGES.rst
        off_peak = NavienAPIClient.build_tou_period(
            season_months=range(1, 13),
            week_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            start_hour=0,
            start_minute=0,
            end_hour=14,
            end_minute=59,
            price_min=0.34831,
            price_max=0.34831,
            decimal_point=5,
        )
        peak = NavienAPIClient.build_tou_period(
            season_months=range(1, 13),
            week_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            start_hour=15,
            start_minute=0,
            end_hour=20,
            end_minute=59,
            price_min=0.45000,
            price_max=0.45000,
            decimal_point=5,
        )

        response_topic = f"cmd/{device.device_info.device_type}/{mqtt_client.config.client_id}/res/tou/rd"

        def on_tou_response(topic: str, message: dict[str, Any]) -> None:
            response = message.get("response", {})
            reservation = response.get("reservation", [])
            print("\nTOU response received:")
            print(f"  reservationUse: {response.get('reservationUse')}")
            for idx, entry in enumerate(reservation, start=1):
                week_days = NavienAPIClient.decode_week_bitfield(entry.get("week", 0))
                price_min_value = NavienAPIClient.decode_price(
                    entry.get("priceMin", 0), entry.get("decimalPoint", 0)
                )
                price_max_value = NavienAPIClient.decode_price(
                    entry.get("priceMax", 0), entry.get("decimalPoint", 0)
                )
                print(
                    "   - #{idx} {start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d} price={min_price:.5f}-{max_price:.5f} days={days}".format(
                        idx=idx,
                        start_h=entry.get("startHour", 0),
                        start_m=entry.get("startMinute", 0),
                        end_h=entry.get("endHour", 0),
                        end_m=entry.get("endMinute", 0),
                        min_price=price_min_value,
                        max_price=price_max_value,
                        days=", ".join(week_days) or "<none>",
                    )
                )

        await mqtt_client.subscribe(response_topic, on_tou_response)

        print("Uploading TOU schedule (enabling reservation)...")
        await mqtt_client.configure_tou_schedule(
            device=device,
            controller_serial_number=controller_serial,
            periods=[off_peak, peak],
            enabled=True,
        )

        print("Requesting current TOU settings for confirmation...")
        await mqtt_client.request_tou_settings(device, controller_serial)

        print("Waiting up to 15 seconds for TOU responses...")
        await asyncio.sleep(15)

        print("Toggling TOU off for quick test...")
        await mqtt_client.set_tou_enabled(device, enabled=False)
        await asyncio.sleep(3)

        print("Re-enabling TOU...")
        await mqtt_client.set_tou_enabled(device, enabled=True)
        await asyncio.sleep(3)

        await mqtt_client.disconnect()
        print("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled by user")
