#!/usr/bin/env python3
"""
Example: Browse OpenEI rate plans and apply one to a Navien device.

This example demonstrates the full TOU workflow using the library's
OpenEI client and Navien API methods — the same flow the mobile app
uses:

1. Query OpenEI for utility rate plans by zip code
2. Convert plans to device-ready format via Navien backend
3. Apply the selected plan to the water heater
4. Enable TOU mode via MQTT
"""

import asyncio
import os
import sys

from nwp500 import (
    NavienAPIClient,
    NavienAuthClient,
    NavienMqttClient,
    OpenEIClient,
    decode_price,
    decode_week_bitfield,
)


async def main() -> None:
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")
    zip_code = os.getenv("ZIP_CODE", "94903")

    if not email or not password:
        print("Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        sys.exit(1)

    # --- Step 1: Browse rate plans from OpenEI ---
    print(f"Fetching utility rates for ZIP {zip_code}…")
    async with OpenEIClient() as openei:
        rates = await openei.fetch_rates(zip_code)
        items = rates.get("items", [])

    if not items:
        print("No rate plans found for this location")
        sys.exit(1)

    # Show available utilities
    utilities = sorted({i["utility"] for i in items})
    print(f"\nFound {len(items)} plans from {len(utilities)} utilities:")
    for u in utilities:
        count = sum(1 for i in items if i["utility"] == u)
        print(f"  • {u} ({count} plans)")

    # --- Step 2: Convert plans via Navien backend ---
    print("\nConverting plans to device format…")
    async with NavienAuthClient(email, password) as auth:
        api = NavienAPIClient(auth_client=auth)
        device = await api.get_first_device()
        converted = await api.convert_tou(source_data=items)

    print(f"Converted {len(converted)} plans:")
    for i, plan in enumerate(converted[:10], 1):
        print(f"  {i}. {plan.name} ({plan.utility})")
    if len(converted) > 10:
        print(f"  … and {len(converted) - 10} more")

    # --- Step 3: Select a plan ---
    # For this example, pick the first EV plan (or first plan)
    selected = next((p for p in converted if "EV" in p.name), converted[0])
    source = next(i for i in items if i.get("name") == selected.name)

    print(f"\nSelected: {selected.name}")
    print(f"Utility:  {selected.utility}")
    for sched in selected.schedule:
        for iv in sched.interval:
            days = decode_week_bitfield(iv.week)
            price = decode_price(iv.price_min, iv.decimal_point)
            print(
                f"  {iv.start_hour:02d}:{iv.start_minute:02d}"
                f"–{iv.end_hour:02d}:{iv.end_minute:02d}"
                f"  ${price:.5f}/kWh"
                f"  ({', '.join(days[:3])}…)"
            )

    # --- Step 4: Apply to device ---
    print("\nApplying rate plan to device…")
    async with NavienAuthClient(email, password) as auth:
        api = NavienAPIClient(auth_client=auth)
        device = await api.get_first_device()

        tou_info = {
            "name": selected.name,
            "utility": selected.utility,
            "schedule": [s.model_dump() for s in selected.schedule],
            "zipCode": zip_code,
        }
        result = await api.update_tou(
            mac_address=device.device_info.mac_address,
            additional_value=str(device.device_info.additional_value),
            tou_info=tou_info,
            source_data=source,
            zip_code=zip_code,
        )
        print(f"Applied: {result.name} ({result.utility})")

        # --- Step 5: Enable TOU via MQTT ---
        print("Enabling TOU mode…")
        mqtt = NavienMqttClient(auth)
        await mqtt.connect()
        await mqtt.control.set_tou_enabled(device, enabled=True)
        await mqtt.disconnect()

    print("\nDone! TOU schedule configured and enabled.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled by user")
