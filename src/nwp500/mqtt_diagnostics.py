"""MQTT diagnostics and telemetry collection.

This module provides detailed diagnostics and metrics collection for MQTT
connection stability analysis, helping to identify whether connection drops
are caused by:
- Network/environmental issues (intermittent connectivity, NAT timeouts)
- AWS server-side limits (connection lifetime, message rate limits)
- Client-side configuration issues (insufficient keep-alive, poor backoff)
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from awscrt.exceptions import AwsCrtError

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)


@dataclass
class ConnectionDropEvent:
    """Record of a single connection drop event."""

    timestamp: str  # ISO 8601 timestamp
    error_name: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[int] = None
    reconnect_attempt: int = 0
    duration_connected_seconds: Optional[float] = None
    active_subscriptions: int = 0
    queued_commands: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ConnectionEvent:
    """Record of a connection success/resumption event."""

    timestamp: str  # ISO 8601 timestamp
    event_type: str  # "connected", "resumed", "deep_reconnected"
    session_present: bool = False
    return_code: Optional[int] = None
    attempt_number: int = 0
    time_to_reconnect_seconds: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class MqttMetrics:
    """Aggregate metrics for MQTT connection stability."""

    # Connection lifecycle
    total_connections: int = 0
    total_disconnects: int = 0
    total_connection_drops: int = 0
    total_reconnect_attempts: int = 0

    # Timing metrics
    longest_session_seconds: float = 0.0
    shortest_session_seconds: float = float("inf")
    average_session_seconds: float = 0.0
    current_session_uptime_seconds: float = 0.0

    # Failure analysis
    connection_drops_by_error: dict[str, int] = field(default_factory=dict)
    reconnection_attempts_distribution: dict[str, int] = field(
        default_factory=dict
    )  # Bucketed by attempt count

    # Recent activity
    last_drop_timestamp: Optional[str] = None
    last_successful_connect_timestamp: Optional[str] = None
    connection_recovered: int = 0  # Number of successful reconnections

    # QoS tracking
    messages_published: int = 0
    messages_queued: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class MqttDiagnosticsCollector:
    """
    Collects detailed diagnostics and metrics for MQTT connection analysis.

    This collector tracks:
    - Connection drop events with error details
    - Connection recovery timeline
    - Error frequency and patterns
    - Session duration statistics
    - Network topology and timing information

    For debugging:
    - Export logs to JSON for correlation with AWS CloudWatch
    - Enables continuous monitoring with configurable retention
    """

    def __init__(
        self,
        max_events_retained: int = 1000,
        enable_verbose_logging: bool = False,
    ):
        """
        Initialize diagnostics collector.

        Args:
            max_events_retained: Maximum number of events to keep in memory
                (older events are discarded, but logged)
            enable_verbose_logging: If True, log every event to logger
        """
        self.max_events_retained = max_events_retained
        self.enable_verbose_logging = enable_verbose_logging

        # Event history (limited size)
        self._drop_events: list[ConnectionDropEvent] = []
        self._connection_events: list[ConnectionEvent] = []

        # Aggregate metrics
        self._metrics = MqttMetrics()

        # Session tracking
        self._session_start_time: Optional[float] = None
        self._session_duration_history: list[float] = []
        self._last_connection_timestamp: Optional[str] = None
        self._last_drop_timestamp: Optional[float] = None

        # Error categorization
        self._aws_error_name_counts: dict[str, int] = defaultdict(int)

        # Callbacks
        self._on_drop_listeners: list[
            Callable[[ConnectionDropEvent], None]
        ] = []

    def on_connection_drop(
        self,
        callback: Callable[[ConnectionDropEvent], None],
    ) -> None:
        """
        Register a callback to be invoked on each connection drop event.

        Args:
            callback: Function that receives ConnectionDropEvent
        """
        self._on_drop_listeners.append(callback)

    async def record_connection_drop(
        self,
        error: Optional[Exception] = None,
        reconnect_attempt: int = 0,
        active_subscriptions: int = 0,
        queued_commands: int = 0,
    ) -> None:
        """
        Record a connection drop event.

        Args:
            error: The exception that caused the drop
            reconnect_attempt: Which reconnection attempt this is (0 = initial)
            active_subscriptions: Number of active subscriptions at time of drop
            queued_commands: Number of commands in the queue
        """
        now = datetime.utcnow().isoformat() + "Z"
        duration = None

        if self._session_start_time is not None:
            duration = time.time() - self._session_start_time

        # Extract error details
        error_name = None
        error_message = None
        error_code = None

        if error is not None:
            error_message = str(error)
            if isinstance(error, AwsCrtError):
                error_name = getattr(error, "name", None)
                error_code = getattr(error, "code", None)
                # Track AWS error frequency
                if error_name:
                    self._aws_error_name_counts[error_name] += 1

        # Create event
        event = ConnectionDropEvent(
            timestamp=now,
            error_name=error_name,
            error_message=error_message,
            error_code=error_code,
            reconnect_attempt=reconnect_attempt,
            duration_connected_seconds=duration,
            active_subscriptions=active_subscriptions,
            queued_commands=queued_commands,
        )

        # Update metrics
        self._metrics.total_connection_drops += 1
        if error_name:
            self._metrics.connection_drops_by_error[error_name] = (
                self._metrics.connection_drops_by_error.get(error_name, 0) + 1
            )
        self._metrics.last_drop_timestamp = now
        self._last_drop_timestamp = time.time()

        # Track session duration
        if duration is not None:
            self._session_duration_history.append(duration)
            if duration > self._metrics.longest_session_seconds:
                self._metrics.longest_session_seconds = duration
            if duration < self._metrics.shortest_session_seconds:
                self._metrics.shortest_session_seconds = duration
            # Recalculate average
            if self._session_duration_history:
                self._metrics.average_session_seconds = sum(
                    self._session_duration_history
                ) / len(self._session_duration_history)

        # Store event (with size limit)
        self._drop_events.append(event)
        if len(self._drop_events) > self.max_events_retained:
            self._drop_events.pop(0)

        # Log if verbose mode enabled
        if self.enable_verbose_logging:
            _logger.warning(
                f"Connection drop recorded: error={error_name}, "
                f"duration={duration}s, attempt={reconnect_attempt}, "
                f"subs={active_subscriptions}, queued={queued_commands}"
            )

        # Call registered callbacks
        for callback in self._on_drop_listeners:
            try:
                callback(event)
            except Exception as e:
                _logger.error(f"Error in drop listener: {e}")

    async def record_connection_success(
        self,
        event_type: str = "connected",
        session_present: bool = False,
        return_code: Optional[int] = None,
        attempt_number: int = 0,
    ) -> None:
        """
        Record a successful connection or reconnection event.

        Args:
            event_type: "connected", "resumed", or "deep_reconnected"
            session_present: Whether MQTT session was present
            return_code: MQTT return code
            attempt_number: Reconnection attempt number (0 = initial connect)
        """
        now = datetime.utcnow().isoformat() + "Z"
        time_to_reconnect = None

        # Update metrics
        if event_type == "connected":
            self._metrics.total_connections += 1
        else:
            self._metrics.connection_recovered += 1

        # Calculate time to reconnect
        if self._last_drop_timestamp is not None:
            time_to_reconnect = time.time() - self._last_drop_timestamp

        # Start new session
        self._session_start_time = time.time()
        self._last_connection_timestamp = now

        # Create event
        event = ConnectionEvent(
            timestamp=now,
            event_type=event_type,
            session_present=session_present,
            return_code=return_code,
            attempt_number=attempt_number,
            time_to_reconnect_seconds=time_to_reconnect,
        )

        # Update current uptime
        self._metrics.current_session_uptime_seconds = 0.0
        self._metrics.last_successful_connect_timestamp = now

        # Store event
        self._connection_events.append(event)
        if len(self._connection_events) > self.max_events_retained:
            self._connection_events.pop(0)

        # Log if verbose
        if self.enable_verbose_logging:
            _logger.info(
                f"Connection success recorded: type={event_type}, "
                f"session_present={session_present}, "
                f"time_to_reconnect={time_to_reconnect}s, "
                f"attempt={attempt_number}"
            )

    def record_publish(self, queued: bool = False) -> None:
        """Record a publish/queue operation."""
        if queued:
            self._metrics.messages_queued += 1
        else:
            self._metrics.messages_published += 1

    async def update_metrics(self) -> None:
        """Update current metrics (e.g., current session uptime)."""
        if self._session_start_time is not None:
            self._metrics.current_session_uptime_seconds = (
                time.time() - self._session_start_time
            )

    def get_metrics(self) -> MqttMetrics:
        """Get current aggregate metrics."""
        # Update current session uptime before returning
        if self._session_start_time is not None:
            self._metrics.current_session_uptime_seconds = (
                time.time() - self._session_start_time
            )

        # Rebuild reconnection attempt distribution from drop events
        attempt_buckets: dict[str, int] = defaultdict(int)
        for event in self._drop_events:
            # Bucket attempts: 1, 2-5, 6-10, 11+
            if event.reconnect_attempt <= 1:
                bucket = "1"
            elif event.reconnect_attempt <= 5:
                bucket = "2-5"
            elif event.reconnect_attempt <= 10:
                bucket = "6-10"
            else:
                bucket = "11+"
            attempt_buckets[bucket] += 1

        self._metrics.reconnection_attempts_distribution = dict(attempt_buckets)

        return self._metrics

    def get_recent_drops(self, limit: int = 10) -> list[ConnectionDropEvent]:
        """Get the N most recent connection drop events."""
        return self._drop_events[-limit:]

    def get_recent_connections(self, limit: int = 10) -> list[ConnectionEvent]:
        """Get the N most recent connection events."""
        return self._connection_events[-limit:]

    def export_json(self) -> str:
        """
        Export all collected diagnostics as JSON.

        Returns:
            JSON string suitable for storing or sending to monitoring systems
        """
        export_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "metrics": self.get_metrics().to_dict(),
            "recent_drops": [
                event.to_dict() for event in self.get_recent_drops(50)
            ],
            "recent_connections": [
                event.to_dict() for event in self.get_recent_connections(50)
            ],
            "aws_error_counts": dict(self._aws_error_name_counts),
            "session_history_summary": {
                "total_sessions": len(self._session_duration_history),
                "sample_durations": self._session_duration_history[-20:],
            },
        }

        return json.dumps(export_data, indent=2, default=str)

    def print_summary(self) -> None:
        """Print a human-readable summary of diagnostics."""
        metrics = self.get_metrics()

        _logger.info("=" * 70)
        _logger.info("MQTT CONNECTION DIAGNOSTICS SUMMARY")
        _logger.info("=" * 70)

        _logger.info(f"Total Connections: {metrics.total_connections}")
        _logger.info(
            f"Total Connection Drops: {metrics.total_connection_drops}"
        )
        _logger.info(
            f"Successful Reconnections: {metrics.connection_recovered}"
        )
        _logger.info(
            f"Total Reconnection Attempts: {metrics.total_reconnect_attempts}"
        )

        _logger.info("-" * 70)
        _logger.info("SESSION DURATION STATISTICS")
        _logger.info("-" * 70)

        if self._session_duration_history:
            _logger.info(
                f"Longest Session: {metrics.longest_session_seconds:.1f}s"
            )
            _logger.info(
                f"Shortest Session: {metrics.shortest_session_seconds:.1f}s"
            )
            _logger.info(
                f"Average Session: {metrics.average_session_seconds:.1f}s"
            )
        _logger.info(
            f"Current Session Uptime: "
            f"{metrics.current_session_uptime_seconds:.1f}s"
        )

        if metrics.connection_drops_by_error:
            _logger.info("-" * 70)
            _logger.info("CONNECTION DROPS BY ERROR TYPE")
            _logger.info("-" * 70)
            for error, count in sorted(
                metrics.connection_drops_by_error.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                _logger.info(f"  {error}: {count}")

        if metrics.reconnection_attempts_distribution:
            _logger.info("-" * 70)
            _logger.info("RECONNECTION ATTEMPTS DISTRIBUTION")
            _logger.info("-" * 70)
            for bucket, count in sorted(
                metrics.reconnection_attempts_distribution.items()
            ):
                _logger.info(f"  Attempts {bucket}: {count}")

        _logger.info("-" * 70)
        _logger.info(f"Messages Published: {metrics.messages_published}")
        _logger.info(f"Messages Queued: {metrics.messages_queued}")

        _logger.info("=" * 70)
