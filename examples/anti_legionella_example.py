#!/usr/bin/env python3
"""Example: Toggle Anti-Legionella protection via MQTT."""

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

        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()

        def on_status(topic: str, message: dict[str, Any]) -> None:
            status = message.get("response", {}).get("status", {})
            period = status.get("antiLegionellaPeriod")
            enabled = status.get("antiLegionellaUse") == 2
            busy = status.get("antiLegionellaOperationBusy") == 2
            if period is not None:
                print(
                    "Anti-Legionella status: enabled={enabled} period={period}d running={busy}".format(
                        enabled=enabled,
                        period=period,
                        busy=busy,
                    )
                )

        # Listen for status snapshots so we can observe changes
        device_type = device.device_info.device_type
        status_topic = f"cmd/{device_type}/{mqtt_client.config.client_id}/res/#"
        await mqtt_client.subscribe(status_topic, on_status)

        print("Enabling Anti-Legionella cycle every 7 days...")
        await mqtt_client.enable_anti_legionella(device, period_days=7)

        print("Requesting status to confirm...")
        await mqtt_client.request_device_status(device)
        await asyncio.sleep(5)

        print("Disabling Anti-Legionella cycle (not recommended long-term)...")
        await mqtt_client.disable_anti_legionella(device)

        print("Requesting status to confirm...")
        await mqtt_client.request_device_status(device)
        await asyncio.sleep(5)

        await mqtt_client.disconnect()
        print("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled by user")