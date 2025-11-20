"""
MQTT utility functions and data structures for Navien Smart Control.

This module provides utility functions for redacting sensitive information,
configuration classes, and common data structures used across MQTT modules.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from awscrt import mqtt

from .config import AWS_IOT_ENDPOINT, AWS_REGION

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

# Pre-compiled regex patterns for performance
_MAC_PATTERNS = [
    re.compile(r"(navilink-)[0-9a-fA-F]{12}"),
    re.compile(r"\b[0-9a-fA-F]{12}\b"),
    re.compile(r"\b([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"),
    re.compile(r"\b([0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}\b"),
]


def redact(obj: Any, keys_to_redact: Optional[set[str]] = None) -> Any:
    """Return a redacted copy of obj with sensitive keys masked.

    This is a lightweight sanitizer for log messages to avoid emitting
    secrets such as access keys, session tokens, passwords, emails,
    clientIDs and sessionIDs.

    Args:
        obj: Object to redact (dict, list, tuple, or primitive)
        keys_to_redact: Set of key names to redact (uses defaults if None)

    Returns:
        Redacted copy of the object
    """
    if keys_to_redact is None:
        keys_to_redact = {
            "access_key_id",
            "secret_access_key",
            "secret_key",
            "session_token",
            "sessionToken",
            "sessionID",
            "clientID",
            "clientId",
            "client_id",
            "password",
            "pushToken",
            "push_token",
            "token",
            "auth",
            "macAddress",
            "mac_address",
            "email",
        }

    # Primitive types: return as-is
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        # avoid printing long secret-like strings fully
        if len(obj) > 256:
            return obj[:64] + "...<redacted>..." + obj[-64:]
        return obj

    # dicts: redact sensitive keys recursively
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            if str(k) in keys_to_redact:
                redacted[k] = "<REDACTED>"
            else:
                redacted[k] = redact(v, keys_to_redact)
        return redacted

    # lists / tuples: redact elements
    if isinstance(obj, (list, tuple)):
        return type(obj)(redact(v, keys_to_redact) for v in obj)

    # fallback: represent object as string but avoid huge dumps
    try:
        s = str(obj)
        if len(s) > 512:
            return s[:256] + "...<redacted>..."
        return s
    except Exception:
        return "<UNREPRESENTABLE>"


def redact_topic(topic: str) -> str:
    """
    Redact sensitive information from MQTT topic strings.

    Topics often contain MAC addresses or device unique identifiers, e.g.:
    - cmd/52/navilink-04786332fca0/st/did
    - cmd/52/navilink-04786332fca0/ctrl
    - cmd/52/04786332fca0/ctrl
    - or with colons/hyphens (04:78:63:32:fc:a0 or 04-78-63-32-fc-a0)

    Args:
        topic: MQTT topic string

    Returns:
        Topic with MAC addresses redacted

    Note:
        Uses pre-compiled regex patterns for better performance.
    """
    # Extra safety: catch any remaining hexadecimal or device-related sequences
    # MAC/device length w/ possible delimiters, prefixes, or casing
    for pattern in _MAC_PATTERNS:
        topic = pattern.sub("REDACTED", topic)
    # Defensive: Cleanup for most common MAC and device ID patterns
    topic = re.sub(
        r"([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})", "REDACTED", topic
    )  # 01:23:45:67:89:ab
    topic = re.sub(
        r"([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}", "REDACTED", topic
    )  # 01-23-45-67-89-ab
    topic = re.sub(r"([0-9A-Fa-f]{12})", "REDACTED", topic)  # 0123456789ab
    topic = re.sub(
        r"(navilink-)[0-9A-Fa-f]{8,}", r"\1REDACTED", topic
    )  # navilink-xxxxxxx
    # Further defensive: catch anything that looks like a device ID
    # (alphanumeric, 8+ chars)
    topic = re.sub(r"(device[-_]?)?[0-9A-Fa-f]{8,}", "REDACTED", topic)
    # Final fallback: catch any continuous hex/alphanumeric string
    # longer than 8 chars (to cover variant IDs)
    topic = re.sub(r"[0-9A-Fa-f]{8,}", "REDACTED", topic)
    return topic


@dataclass
class MqttConnectionConfig:
    """Configuration for MQTT connection.

    Attributes:
        endpoint: AWS IoT endpoint URL
        region: AWS region
        client_id: MQTT client ID (auto-generated if None)
        clean_session: Whether to start with a clean session
        keep_alive_secs: Keep-alive interval in seconds

        auto_reconnect: Enable automatic reconnection
        max_reconnect_attempts: Maximum reconnection attempts
            (-1 for unlimited)
        initial_reconnect_delay: Initial delay between reconnect attempts
        max_reconnect_delay: Maximum delay between reconnect attempts
        reconnect_backoff_multiplier: Exponential backoff multiplier
        deep_reconnect_threshold: Attempt count to trigger full
            connection rebuild

        enable_command_queue: Enable command queueing when disconnected
        max_queued_commands: Maximum number of queued commands
    """

    endpoint: str = AWS_IOT_ENDPOINT
    region: str = AWS_REGION
    client_id: Optional[str] = None
    clean_session: bool = True
    keep_alive_secs: int = 1200

    # Reconnection settings
    auto_reconnect: bool = True
    max_reconnect_attempts: int = -1  # -1 = unlimited retries
    initial_reconnect_delay: float = 1.0  # seconds
    max_reconnect_delay: float = 120.0  # seconds
    reconnect_backoff_multiplier: float = 2.0
    deep_reconnect_threshold: int = (
        10  # Switch to full rebuild after N attempts
    )

    # Command queue settings
    enable_command_queue: bool = True
    max_queued_commands: int = 100

    def __post_init__(self) -> None:
        """Generate client ID if not provided."""
        if not self.client_id:
            object.__setattr__(
                self, "client_id", f"navien-client-{uuid.uuid4().hex[:8]}"
            )


@dataclass
class QueuedCommand:
    """Represents a command that is queued for sending when reconnected.

    Attributes:
        topic: MQTT topic to publish to
        payload: Command payload dictionary
        qos: Quality of Service level
        timestamp: Time when command was queued
    """

    topic: str
    payload: dict[str, Any]
    qos: mqtt.QoS
    timestamp: datetime


class PeriodicRequestType(Enum):
    """Types of periodic requests that can be sent.

    Attributes:
        DEVICE_INFO: Request device information periodically
        DEVICE_STATUS: Request device status periodically
    """

    DEVICE_INFO = "device_info"
    DEVICE_STATUS = "device_status"


def topic_matches_pattern(topic: str, pattern: str) -> bool:
    """
    Check if a topic matches a subscription pattern with wildcards.

    Supports MQTT wildcards:
    - '+' matches a single level
    - '#' matches multiple levels (must be at end)

    Args:
        topic: Actual topic (e.g., "cmd/52/navilink-ABC/status")
        pattern: Pattern with wildcards (e.g., "cmd/52/+/#")

    Returns:
        True if topic matches pattern

    Examples:
        >>> topic_matches_pattern("cmd/52/device1/status", "cmd/52/+/status")
        True
        >>> topic_matches_pattern(
        ...     "cmd/52/device1/status/extra", "cmd/52/device1/#"
        ... )
        True
    """
    # Handle exact match
    if topic == pattern:
        return True

    # Handle wildcards
    topic_parts = topic.split("/")
    pattern_parts = pattern.split("/")

    # Multi-level wildcard # matches everything after
    if "#" in pattern_parts:
        hash_idx = pattern_parts.index("#")
        # Must be at the end
        if hash_idx != len(pattern_parts) - 1:
            return False
        # Topic must have at least as many parts as before the #
        if len(topic_parts) < hash_idx:
            return False
        # Check parts before # with + wildcard support
        for i in range(hash_idx):
            if pattern_parts[i] != "+" and topic_parts[i] != pattern_parts[i]:
                return False
        return True

    # Single-level wildcard + matches one level
    if len(topic_parts) != len(pattern_parts):
        return False

    for topic_part, pattern_part in zip(topic_parts, pattern_parts):
        if pattern_part != "+" and topic_part != pattern_part:
            return False

    return True
