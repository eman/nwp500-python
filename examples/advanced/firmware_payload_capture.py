#!/usr/bin/env python3
"""
Firmware Payload Capture Tool.

Captures raw MQTT payloads for all scheduling-related topics and dumps them
to a timestamped JSON file. Use this to detect changes introduced by firmware
updates by diffing captures taken before and after an update.

Specifically captures:
  - Weekly reservations (rsv/rd)
  - Time-of-Use schedule (tou/rd)
  - Device info (firmware versions, capabilities)
  - Device status (current operating state)
  - All other response/event topics (via wildcards)

Usage:
    NAVIEN_EMAIL=your@email.com NAVIEN_PASSWORD=password python3 firmware_payload_capture.py

Output:
    payload_capture_YYYYMMDD_HHMMSS.json  — all captured payloads with topics
                                            and timestamps

Comparing two captures to find firmware changes:
    diff <(jq '.payloads[] | select(.topic | contains("rsv"))' before.json) \\
         <(jq '.payloads[] | select(.topic | contains("rsv"))' after.json)
"""

import asyncio
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient
from nwp500.models import DeviceFeature
from nwp500.topic_builder import MqttTopicBuilder

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
_logger = logging.getLogger(__name__)


def _redact_mac_in_text(text: str) -> str:
    """Redact MAC addresses in text before console output."""
    separated_mac_pattern = re.compile(r"(?i)\b([0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b")
    compact_mac_pattern = re.compile(r"(?i)\b[0-9a-f]{12}\b")

    def _mask_separated(match: re.Match[str]) -> str:
        parts = re.split(r"[:-]", match.group(0))
        return ":".join(parts[:3] + ["**", "**", "**"])

    def _mask_compact(match: re.Match[str]) -> str:
        value = match.group(0).lower()
        return f"{value[:2]}:{value[2:4]}:{value[4:6]}:**:**:**"

    text = separated_mac_pattern.sub(_mask_separated, text)
    return compact_mac_pattern.sub(_mask_compact, text)


class PayloadCapture:
    """Captures and records raw MQTT payloads."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def record(self, topic: str, message: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "topic": topic,
            "payload": message,
        }
        self.payloads.append(entry)
        print(f"  ← {_redact_mac_in_text(topic)}")

    def save(self, path: Path) -> None:
        data = {
            "captured_at": datetime.now(UTC).isoformat(),
            "total_payloads": len(self.payloads),
            "payloads": self.payloads,
        }
        path.write_text(json.dumps(data, indent=2, default=str))
        print(f"\nSaved {len(self.payloads)} payloads → {path}")


async def main() -> None:
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Error: set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        sys.exit(1)

    capture = PayloadCapture()

    async with NavienAuthClient(email, password) as auth_client:
        api_client = NavienAPIClient(auth_client=auth_client)
        device = await api_client.get_first_device()
        if not device:
            print("No devices found for this account")
            return

        device_type = str(device.device_info.device_type)
        print(f"Device connected [{device_type}]")

        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()

        client_id = mqtt_client.client_id

        # --- Wildcard subscriptions to catch everything ---

        # All response messages back to this client
        res_wildcard = MqttTopicBuilder.response_topic(device_type, client_id, "#")
        # All event messages pushed by the device
        evt_wildcard = MqttTopicBuilder.event_topic(device_type, mac, "#")

        print(
            f"\nSubscribing to:\n  {_redact_mac_in_text(res_wildcard)}\n"
            f"  {_redact_mac_in_text(evt_wildcard)}\n"
        )
        print("Captured topics:")

        await mqtt_client.subscribe(res_wildcard, capture.record)
        await mqtt_client.subscribe(evt_wildcard, capture.record)

        # --- Step 1: fetch device info (needed for firmware version + serial) ---
        device_info_event: asyncio.Event = asyncio.Event()
        device_feature: DeviceFeature | None = None

        def on_feature(feature: DeviceFeature) -> None:
            nonlocal device_feature
            device_feature = feature
            device_info_event.set()

        await mqtt_client.subscribe_device_feature(device, on_feature)
        await mqtt_client.control.request_device_info(device)
        await asyncio.wait_for(device_info_event.wait(), timeout=30.0)

        if device_feature:
            print(
                f"\nFirmware: controller={device_feature.controller_sw_version} "
                f"panel={device_feature.panel_sw_version} "
                f"wifi={device_feature.wifi_sw_version}"
            )

        # --- Step 2: request device status ---
        await mqtt_client.control.request_device_status(device)
        await asyncio.sleep(3)

        # --- Step 3: request reservation (weekly) schedule ---
        print("\nRequesting weekly reservation schedule...")
        await mqtt_client.control.request_reservations(device)
        await asyncio.sleep(5)

        # --- Step 4: request TOU schedule (requires controller serial number) ---
        if device_feature and device_feature.program_reservation_use:
            serial = device_feature.controller_serial_number
            if serial:
                print("Requesting TOU schedule...")
                try:
                    await mqtt_client.control.request_tou_settings(device, serial)
                    await asyncio.sleep(5)
                except Exception as exc:
                    print(f"  TOU request failed: {exc}")

        # --- Step 5: wait a bit more to catch any late-arriving messages ---
        print("\nWaiting for any remaining messages...")
        await asyncio.sleep(5)

        await mqtt_client.disconnect()

    # --- Save results ---
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_path = Path(f"payload_capture_{timestamp}.json")
    capture.save(output_path)

    # Print a summary grouped by topic
    print("\n--- Summary by topic ---")
    by_topic: dict[str, int] = {}
    for entry in capture.payloads:
        by_topic[entry["topic"]] = by_topic.get(entry["topic"], 0) + 1
    for topic, count in sorted(by_topic.items()):
        print(f"  {count:2d}x  {topic}")

    if device_feature:
        print(
            f"\nFirmware captured: controller_sw_version="
            f"{device_feature.controller_sw_version}"
        )
        print(
            "Compare this file against a capture from a different firmware version "
            "to detect scheduling changes.\n"
            "Useful diff command:\n"
            f"  diff <(jq '.payloads[] | select(.topic | contains(\"rsv\"))' "
            f"before.json) \\\n"
            f"       <(jq '.payloads[] | select(.topic | contains(\"rsv\"))' "
            f"{output_path})"
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled by user")
    except TimeoutError:
        print("\nError: timed out waiting for device response. Is the device online?")
        sys.exit(1)
