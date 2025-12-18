#!/usr/bin/env python3
"""
MQTT Connection Diagnostic Tool for Navien Smart Control.

This script connects to the MQTT broker and monitors connection stability for a
specified duration. It outputs detailed diagnostics including:
- Connection drops and error reasons
- Reconnection attempts
- Session duration statistics
- Message throughput

Usage:
    python scripts/diagnose_mqtt_connection.py [--duration SECONDS] [--verbose]
"""

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
from datetime import datetime

# Add src to path to allow running from project root
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from nwp500 import NavienAuthClient, NavienMqttClient
    from nwp500.mqtt_utils import MqttConnectionConfig
except ImportError:
    print(
        "Error: Could not import nwp500 library. "
        "Run from project root with installed dependencies."
    )
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mqtt_diagnostics")


async def main():
    parser = argparse.ArgumentParser(description="MQTT Connection Diagnostics")
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration to run monitoring in seconds (0 for indefinite)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--email", help="Navien account email (or use NAVIEN_EMAIL env var)"
    )
    parser.add_argument(
        "--password",
        help="Navien account password (or use NAVIEN_PASSWORD env var)",
    )

    args = parser.parse_args()

    # Get credentials
    email = args.email or os.getenv("NAVIEN_EMAIL")
    password = args.password or os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print("Error: Credentials required.")
        print("Set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
        print("OR provide --email and --password arguments.")
        sys.exit(1)

    if args.verbose:
        logging.getLogger("nwp500").setLevel(logging.DEBUG)
        logging.getLogger("awscrt").setLevel(logging.DEBUG)

    print(f"Starting MQTT diagnostics for {email}")
    print(f"Monitoring duration: {args.duration} seconds")
    print("Press Ctrl+C to stop early and generate report")
    print("-" * 60)

    try:
        async with NavienAuthClient(email, password) as auth_client:
            # Configure connection for investigation
            config = MqttConnectionConfig(
                auto_reconnect=True,
                max_reconnect_attempts=5,
                enable_command_queue=True,
            )

            mqtt_client = NavienMqttClient(auth_client, config=config)

            # Setup signal handler for graceful shutdown
            stop_event = asyncio.Event()

            def signal_handler():
                print("\nStopping diagnostics...")
                stop_event.set()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, signal_handler)

            # Connect
            logger.info("Connecting to MQTT broker...")
            await mqtt_client.connect()
            logger.info("Connected!")

            # Start monitoring loop
            start_time = datetime.now()
            conn_start = start_time

            while not stop_event.is_set():
                # Check duration
                if (
                    args.duration > 0
                    and (datetime.now() - start_time).total_seconds()
                    > args.duration
                ):
                    logger.info("Duration reached.")
                    break

                # Print periodic status
                if (datetime.now() - conn_start).total_seconds() >= 10:
                    metrics = mqtt_client.diagnostics.get_metrics()
                    uptime = metrics.current_session_uptime_seconds
                    drops = metrics.total_connection_drops
                    reconnects = metrics.connection_recovered

                    status = (
                        "Connected"
                        if mqtt_client.is_connected
                        else "Disconnected"
                    )
                    print(
                        f"Status: {status} | "
                        f"Uptime: {uptime:.1f}s | "
                        f"Drops: {drops} | "
                        f"Reconnects: {reconnects}"
                    )
                    conn_start = datetime.now()

                await asyncio.sleep(1)

            # Final Summary
            print("\n" + "=" * 60)
            print("DIAGNOSTIC REPORT")
            print("=" * 60)
            mqtt_client.diagnostics.print_summary()

            # Export JSON
            json_report = mqtt_client.diagnostics.export_json()
            report_file = (
                f"mqtt_diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            with open(report_file, "w") as f:
                f.write(json_report)
            print(f"\nDetailed JSON report saved to: {report_file}")

            # Disconnect
            await mqtt_client.disconnect()

    except Exception as e:
        logger.error(f"Diagnostic error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
