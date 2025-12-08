#!/usr/bin/env python3
"""
Example: MQTT Connection Drop Diagnostics Collection.

This example demonstrates how to:
1. Enable comprehensive MQTT diagnostics
2. Collect connection drop events with context
3. Export diagnostics for analysis
4. Correlate drops with system metrics

Run this while your MQTT client is connected to baseline connection stability.

Usage:
    python3 mqtt_diagnostics_example.py
    # Or with stored credentials:
    NAVIEN_EMAIL=your@email.com NAVIEN_PASSWORD=password python3 mqtt_diagnostics_example.py

This will run for 1 hour, collecting diagnostics and exporting every 5 minutes.
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from nwp500 import NavienAuthClient, NavienMqttClient
from nwp500.mqtt_diagnostics import MqttDiagnosticsCollector
from nwp500.mqtt_utils import MqttConnectionConfig

# Configure logging to show detailed MQTT information
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("mqtt_diagnostics.log"),
    ],
)

_logger = logging.getLogger(__name__)


class MqttDiagnosticsExample:
    """Example showing how to collect MQTT diagnostics for debugging."""

    def __init__(self):
        """Initialize the example."""
        self.mqtt_client: NavienMqttClient | None = None
        self.diagnostics = MqttDiagnosticsCollector(
            max_events_retained=1000, enable_verbose_logging=True
        )
        self.running = True
        self.output_dir = Path("mqtt_diagnostics_output")
        self.output_dir.mkdir(exist_ok=True)

    def setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""

        def handle_signal(signum, frame):
            _logger.info(f"Received signal {signum}, shutting down...")
            self.running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    async def export_diagnostics(self, interval: float = 300.0) -> None:
        """
        Periodically export diagnostics to JSON.

        Args:
            interval: Export interval in seconds (default: 5 minutes)
        """
        while self.running:
            try:
                await asyncio.sleep(interval)

                if not self.running:
                    break

                # Export JSON
                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                output_file = self.output_dir / f"diagnostics_{timestamp}.json"

                json_data = self.diagnostics.export_json()
                with open(output_file, "w") as f:
                    f.write(json_data)

                _logger.info(f"Exported diagnostics to {output_file}")

                # Also print summary
                self.diagnostics.print_summary()

            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.error(f"Error exporting diagnostics: {e}", exc_info=True)

    async def monitor_connection_state(self, interval: float = 10.0) -> None:
        """
        Monitor connection state and update metrics.

        Args:
            interval: Update interval in seconds
        """
        while self.running:
            try:
                await asyncio.sleep(interval)

                if self.mqtt_client:
                    await self.diagnostics.update_metrics()

                    # Log current state
                    metrics = self.diagnostics.get_metrics()
                    _logger.info(
                        f"Connection state: "
                        f"connected={self.mqtt_client.is_connected}, "
                        f"reconnecting={self.mqtt_client.is_reconnecting}, "
                        f"uptime={metrics.current_session_uptime_seconds:.0f}s, "
                        f"drops={metrics.total_connection_drops}, "
                        f"queued={self.mqtt_client.queued_commands_count}"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.error(f"Error monitoring state: {e}", exc_info=True)

    async def on_connection_drop(self, error: Exception) -> None:
        """Handle connection drop event."""
        _logger.warning(f"Connection dropped: {error}")

        # Record with diagnostics
        active_subs = (
            len(
                self.mqtt_client._subscription_manager.subscriptions
                if self.mqtt_client and self.mqtt_client._subscription_manager
                else []
            )
            if self.mqtt_client
            else 0
        )
        queued_cmds = self.mqtt_client.queued_commands_count if self.mqtt_client else 0

        await self.diagnostics.record_connection_drop(
            error=error,
            active_subscriptions=active_subs,
            queued_commands=queued_cmds,
        )

    async def on_connection_resumed(
        self, return_code: int, session_present: bool
    ) -> None:
        """Handle connection resumed event."""
        _logger.info(
            f"Connection resumed: return_code={return_code}, "
            f"session_present={session_present}"
        )

        await self.diagnostics.record_connection_success(
            event_type="resumed",
            session_present=session_present,
            return_code=return_code,
        )

    async def run_example(
        self,
        email: str,
        password: str,
        duration_seconds: float = 3600.0,
    ) -> None:
        """
        Run the diagnostics collection example.

        Args:
            email: Navien account email
            password: Navien account password
            duration_seconds: How long to run (default: 1 hour)
        """
        self.setup_signal_handlers()

        _logger.info("=" * 70)
        _logger.info("MQTT DIAGNOSTICS COLLECTION EXAMPLE")
        _logger.info("=" * 70)
        _logger.info(f"Duration: {duration_seconds / 60:.0f} minutes")
        _logger.info(f"Diagnostics will be saved to: {self.output_dir.absolute()}")

        try:
            # Authenticate
            _logger.info("Authenticating with Navien API...")
            async with NavienAuthClient(email, password) as auth_client:
                await auth_client.sign_in(email, password)

                # Create MQTT client with diagnostics-friendly config
                # Reduced keep-alive to test for NAT timeout issues
                config = MqttConnectionConfig(
                    keep_alive_secs=60,  # Test with 60s instead of 1200s
                    initial_reconnect_delay=0.5,
                    max_reconnect_delay=60.0,
                    deep_reconnect_threshold=5,
                    max_reconnect_attempts=-1,  # Unlimited retries
                    enable_command_queue=True,
                )

                self.mqtt_client = NavienMqttClient(auth_client, config=config)

                # Hook into connection events
                self.mqtt_client.on(
                    "connection_interrupted",
                    lambda e: asyncio.create_task(self.on_connection_drop(e)),
                )
                self.mqtt_client.on(
                    "connection_resumed",
                    lambda rc, sp: asyncio.create_task(
                        self.on_connection_resumed(rc, sp)
                    ),
                )

                # Connect
                _logger.info("Connecting to MQTT broker...")
                await self.mqtt_client.connect()
                await self.diagnostics.record_connection_success(event_type="connected")

                _logger.info("Connected successfully!")
                _logger.info(
                    f"Client ID: {self.mqtt_client.client_id}, "
                    f"Session ID: {self.mqtt_client.session_id}"
                )

                # Start background tasks
                export_task = asyncio.create_task(
                    self.export_diagnostics(interval=300)  # Export every 5 min
                )
                monitor_task = asyncio.create_task(
                    self.monitor_connection_state(interval=10)
                )

                try:
                    # Run for specified duration
                    _logger.info(
                        f"Running for {duration_seconds / 60:.0f} minutes. "
                        "Press Ctrl+C to stop early."
                    )

                    await asyncio.sleep(duration_seconds)

                except asyncio.CancelledError:
                    _logger.info("Example cancelled")

                finally:
                    # Cleanup
                    self.running = False
                    export_task.cancel()
                    monitor_task.cancel()

                    try:
                        await asyncio.wait_for(
                            asyncio.gather(
                                export_task, monitor_task, return_exceptions=True
                            ),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        pass

                    # Final export
                    _logger.info("Exporting final diagnostics...")
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    final_file = self.output_dir / f"diagnostics_final_{timestamp}.json"
                    with open(final_file, "w") as f:
                        f.write(self.diagnostics.export_json())
                    _logger.info(f"Final diagnostics saved to {final_file}")

                    # Print summary
                    self.diagnostics.print_summary()

                    # Disconnect
                    _logger.info("Disconnecting...")
                    await self.mqtt_client.disconnect()

                    _logger.info("Example complete")

        except Exception as e:
            _logger.error(f"Error during example: {e}", exc_info=True)
            raise


async def main():
    """Main entry point."""
    # Get credentials from environment or prompt
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        print(
            "Usage: NAVIEN_EMAIL=your@email.com NAVIEN_PASSWORD=password python3 mqtt_diagnostics_example.py"
        )
        sys.exit(1)

    # Run example for 1 hour (or until interrupted)
    example = MqttDiagnosticsExample()
    await example.run_example(
        email=email,
        password=password,
        duration_seconds=3600.0,  # 1 hour
    )


if __name__ == "__main__":
    asyncio.run(main())
