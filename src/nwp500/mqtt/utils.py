"""
MQTT utility functions and data structures for Navien Smart Control.

This module provides utility functions for redacting sensitive information,
configuration classes, and common data structures used across MQTT modules.
"""

import asyncio
import concurrent.futures
import functools
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from ..config import AWS_IOT_ENDPOINT, AWS_REGION
from .types import QoS

if TYPE_CHECKING:
    from ..models import Device

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


def redact(obj: Any, keys_to_redact: set[str] | None = None) -> Any:
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
        redacted: dict[Any, Any] = {}
        for k, v in obj.items():
            if str(k) in keys_to_redact:
                redacted[k] = "<REDACTED>"
            else:
                redacted[k] = redact(v, keys_to_redact)
        return redacted

    # lists / tuples: redact elements
    if isinstance(obj, (list, tuple)):
        # Explicitly annotate generator expression to avoid unknown types
        return type(obj)(redact(v, keys_to_redact) for v in obj)

    # fallback: represent object as string but avoid huge dumps
    try:
        s = str(obj)
        if len(s) > 512:
            return s[:256] + "...<redacted>..."
        return s
    except Exception:
        return "<UNREPRESENTABLE>"


payload_logger = logging.getLogger("nwp500.mqtt.payloads")
"""Logger for every MQTT payload sent and received, at DEBUG."""

# Payload logs keep clientID and sessionID so a reply can be matched to
# the command it answers and a message's sender can be told apart.
_PAYLOAD_REDACT_KEYS = {
    "access_key_id",
    "secret_access_key",
    "secret_key",
    "session_token",
    "sessionToken",
    "password",
    "pushToken",
    "push_token",
    "token",
    "auth",
    "macAddress",
    "mac_address",
    "email",
}


_MAC_KEYS = {"macAddress", "mac_address"}
_NAVILINK_MAC = re.compile(r"navilink-([0-9a-fA-F]{12})(?![0-9a-fA-F])")
_SEGMENT_MAC = re.compile(r"(?:^|/)([0-9a-fA-F]{12})(?=/|$)")


def _collect_macs(text: str, macs: set[str]) -> None:
    """Add the MACs a topic-like string names to ``macs``.

    A MAC is named as ``navilink-<mac>`` or as a 12-hex topic segment.
    """
    macs.update(_NAVILINK_MAC.findall(text))
    if "/" in text:
        macs.update(_SEGMENT_MAC.findall(text))


def _redact_macs(text: str) -> str:
    """Replace MAC addresses in a topic, leaving other identifiers."""
    text = _MAC_PATTERNS[0].sub(r"\1REDACTED", text)
    for pattern in _MAC_PATTERNS[1:]:
        text = pattern.sub("REDACTED", text)
    return text


def _mask_keys(obj: Any, macs: set[str]) -> Any:
    """Mask sensitive keys, leaving every other value whole.

    The values of MAC address keys, and MACs named in topic-like
    values, are added to ``macs``.
    """
    if isinstance(obj, dict):
        masked: dict[Any, Any] = {}
        for key, value in cast(dict[Any, Any], obj).items():
            if str(key) in _MAC_KEYS and isinstance(value, str) and value:
                macs.add(value)
            if str(key) in _PAYLOAD_REDACT_KEYS:
                masked[key] = "<REDACTED>"
            else:
                masked[key] = _mask_keys(value, macs)
        return masked
    if isinstance(obj, (list, tuple)):
        return [_mask_keys(v, macs) for v in cast(list[Any], obj)]
    if isinstance(obj, str):
        _collect_macs(obj, macs)
    return obj


_RAW_FIELD = re.compile(
    r'"('
    + "|".join(re.escape(k) for k in sorted(_PAYLOAD_REDACT_KEYS))
    + r')"\s*:\s*("(?:[^"\\]|\\.)*"?|[^,}\]\s]*)'
)


def _mask_raw_fields(text: str, macs: set[str]) -> str:
    """Mask sensitive fields in text that is not valid JSON.

    A truncated or malformed payload cannot be walked by key, so its
    ``"key": value`` pairs for sensitive keys are masked by pattern.
    The values of MAC address keys are added to ``macs``.
    """

    def mask(match: re.Match[str]) -> str:
        key, value = match.group(1), match.group(2)
        if key in _MAC_KEYS:
            mac = value.strip('"')
            if mac:
                macs.add(mac)
        return f'"{key}":"<REDACTED>"'

    return _RAW_FIELD.sub(mask, text)


def _redact_body(text: str, macs: set[str]) -> str:
    """Replace MAC addresses in a payload body.

    Bare 12-hex values are left alone, since packed data such as a
    one-entry reservation is 12 hex characters too; a bare MAC is
    replaced where the topic or the payload names it.
    """
    for mac in macs:
        text = re.sub(re.escape(mac), "REDACTED", text, flags=re.IGNORECASE)
    text = _MAC_PATTERNS[0].sub(r"\1REDACTED", text)
    for pattern in _MAC_PATTERNS[2:]:
        text = pattern.sub("REDACTED", text)
    return text


def log_payload(
    direction: str,
    topic: str,
    payload: Any,
    packet_id: int | None = None,
) -> None:
    """Log one MQTT payload on ``nwp500.mqtt.payloads`` at DEBUG.

    A payload that is not JSON is logged as its raw text.

    Args:
        direction: ``"send"`` or ``"recv"``.
        topic: Topic the payload was published or received on.
        payload: The payload: a JSON-compatible object, or the message
            as a string or bytes.
        packet_id: MQTT packet id of a publish, logged as ``#<id>``.
    """
    if not payload_logger.isEnabledFor(logging.DEBUG):
        return
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    macs: set[str] = set()
    _collect_macs(topic, macs)
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except ValueError:
            _collect_macs(payload, macs)
            body = _mask_raw_fields(payload, macs)
        else:
            body = json.dumps(_mask_keys(parsed, macs), separators=(",", ":"))
    else:
        body = json.dumps(_mask_keys(payload, macs), separators=(",", ":"))
    if packet_id is not None:
        direction = f"{direction} #{packet_id}"
    payload_logger.debug(
        "%s %s %s", direction, _redact_macs(topic), _redact_body(body, macs)
    )


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


def redact_mac(mac: str | None) -> str:
    """Mask a MAC address or device ID for safe logging.

    Args:
        mac: The MAC address or device ID to redact
            (e.g., 'navilink-0123456789ab')

    Returns:
        A redacted string like 'navilink-01...89ab' or '<REDACTED>'
    """
    if not mac:
        return "<REDACTED>"

    # Handle navilink- prefix
    prefix = ""
    if mac.startswith("navilink-"):
        prefix = "navilink-"
        mac = mac[len("navilink-") :]

    if len(mac) <= 4:
        return f"{prefix}<REDACTED>"

    # Mask central part, keeping first 2 and last 4
    return f"{prefix}{mac[:2]}...{mac[-4:]}"


def redact_serial(serial: str | None) -> str:
    """Mask a serial number for safe logging.

    Args:
        serial: Serial number to redact

    Returns:
        Redacted serial like 'AB...1234'
    """
    if not serial:
        return "<REDACTED>"

    if len(serial) <= 6:
        return "<REDACTED>"

    # Mask central part, keeping first 2 and last 4
    return f"{serial[:2]}...{serial[-4:]}"


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

        operation_timeout: Maximum seconds to wait for a broker
            acknowledgement of an MQTT operation (connect, publish,
            subscribe, unsubscribe). Prevents callers from hanging
            forever on half-open TCP connections.

        enable_command_queue: Enable command queueing when disconnected
        max_queued_commands: Maximum number of queued commands
        max_queued_command_age: Maximum age in seconds for a queued
            command to still be sent when the connection is restored;
            older commands are discarded instead of being replayed to
            the appliance. ``None`` disables expiry.

        send_session_end_on_disconnect: Publish the ``st/end`` session-end
            query to each subscribed device when ``disconnect()`` is
            called. Its effect on other clients connected to the same
            device is not known; turn it off to disconnect without it.

        last_will_device: Device whose ``app-connection`` event topic
            receives this client's MQTT Last-Will. The broker publishes it
            (``connection.status`` 0) if the connection is lost without a
            DISCONNECT, so other clients watching the topic learn the client
            dropped. A will names one topic, so one device. ``None`` (the
            default) registers no will.
    """

    endpoint: str = AWS_IOT_ENDPOINT
    region: str = AWS_REGION
    client_id: str | None = None
    clean_session: bool = True
    keep_alive_secs: int = 60

    # Reconnection settings
    auto_reconnect: bool = True
    max_reconnect_attempts: int = -1  # -1 = unlimited retries
    initial_reconnect_delay: float = 1.0  # seconds
    max_reconnect_delay: float = 120.0  # seconds
    reconnect_backoff_multiplier: float = 2.0
    deep_reconnect_threshold: int = (
        10  # Switch to full rebuild after N attempts
    )

    # MQTT operation acknowledgement timeout
    operation_timeout: float = 30.0  # seconds

    # Command queue settings
    enable_command_queue: bool = True
    max_queued_commands: int = 100
    max_queued_command_age: float | None = 300.0  # seconds

    # Session end
    send_session_end_on_disconnect: bool = True

    # Last-Will target
    last_will_device: Device | None = None

    def __post_init__(self) -> None:
        """Generate client ID if not provided and validate settings."""
        if not self.client_id:
            object.__setattr__(
                self, "client_id", f"navien-client-{uuid.uuid4().hex[:8]}"
            )
        if self.deep_reconnect_threshold < 1:
            object.__setattr__(self, "deep_reconnect_threshold", 1)
        # Validate queue settings up front: a non-positive queue size
        # would make enqueue() fail at runtime in hard-to-debug ways,
        # and a negative max age would silently expire every command.
        if self.max_queued_commands < 1:
            raise ValueError(
                "max_queued_commands must be >= 1, got "
                f"{self.max_queued_commands}"
            )
        if (
            self.max_queued_command_age is not None
            and self.max_queued_command_age < 0
        ):
            raise ValueError(
                "max_queued_command_age must be >= 0 or None, got "
                f"{self.max_queued_command_age}"
            )
        if self.operation_timeout <= 0:
            raise ValueError(
                f"operation_timeout must be > 0, got {self.operation_timeout}"
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
    qos: QoS
    timestamp: datetime


class PeriodicRequestType(StrEnum):
    """Types of periodic requests that can be sent.

    Attributes:
        DEVICE_INFO: Request device information periodically
        DEVICE_STATUS: Request device status periodically
    """

    DEVICE_INFO = "device_info"
    DEVICE_STATUS = "device_status"


_ALT_KEYS: dict[str, str] = {
    "status": "st",
    "feature": "did",
}

_SENTINEL = object()


def consume_abandoned_future(
    future: asyncio.Future[Any], operation: str, logger: logging.Logger
) -> None:
    """Retrieve the eventual result of an abandoned acknowledgement future.

    When :func:`await_ack` is cancelled or times out, the shielded future
    keeps running in the background. If nobody retrieves its eventual
    exception, asyncio logs a "Future exception was never retrieved"
    warning at garbage-collection time. This callback consumes that
    result/exception so the warning is never emitted, logging benign
    errors (e.g. ``AwsCrtError`` from clean-session cancellation during
    reconnect) at debug level instead.
    """
    if future.cancelled():
        return
    exc = future.exception()
    if exc is not None:
        # The type only: a late SubscribeError's text is the topic.
        logger.debug(
            "%s completed with exception after being abandoned: %s",
            operation,
            type(exc).__name__,
        )


async def await_ack(
    future: concurrent.futures.Future[Any] | asyncio.Future[Any],
    operation: str,
    timeout: float,
    logger: logging.Logger,
) -> Any:
    """Await a broker acknowledgement future with a timeout.

    The awscrt future is shielded so cancellation (or a timeout) never
    propagates into the SDK future: the underlying operation completes
    independently, preventing InvalidStateError in AWS CRT callbacks.

    A timeout guards against half-open TCP connections where the
    acknowledgement never arrives; without it callers can hang until
    the keep-alive expires (20+ minutes).

    If the awaiting task is cancelled or times out before the shielded
    future completes, a done callback is attached so its eventual
    result/exception is still retrieved, preventing asyncio's "Future
    exception was never retrieved" warnings.

    Args:
        future: Acknowledgement future: the
            ``concurrent.futures.Future`` returned by the AWS CRT SDK
            (wrapped via ``asyncio.wrap_future``), or an already
            loop-bound ``asyncio.Future``
        operation: Human-readable operation name for error messages
        timeout: Seconds to wait for the acknowledgement
        logger: Logger for the cancellation, timeout and late-error
            messages

    Returns:
        The acknowledgement result

    Raises:
        TimeoutError: If no acknowledgement within
            ``timeout`` seconds
        asyncio.CancelledError: If the awaiting task is cancelled
    """
    awaitable_future: asyncio.Future[Any] = (
        asyncio.wrap_future(future)
        if isinstance(future, concurrent.futures.Future)
        else future
    )
    try:
        return await asyncio.wait_for(
            asyncio.shield(awaitable_future), timeout=timeout
        )
    except (asyncio.CancelledError, TimeoutError) as e:
        if isinstance(e, TimeoutError):
            logger.error("%s not acknowledged within %.1fs", operation, timeout)
        else:
            logger.debug(
                "%s was cancelled but will complete in background", operation
            )
        awaitable_future.add_done_callback(
            functools.partial(
                consume_abandoned_future, operation=operation, logger=logger
            )
        )
        raise


async def request_reply[T](
    subscribe: Callable[[Device, Callable[[T], None]], Awaitable[Any]],
    unsubscribe: Callable[[Device, Callable[[T], None]], Awaitable[Any]],
    device: Device,
    send: Callable[[], Awaitable[Any]],
    *,
    timeout: float,
    what: str,
    logger: logging.Logger,
    accept: Callable[[T], bool] = lambda _: True,
) -> T | None:
    """Subscribe, ``send``, and wait for the first reply ``accept`` takes.

    Returns ``None`` when no such reply arrives within ``timeout``. The
    callback is removed afterwards; a failed unsubscribe is logged to
    ``logger`` as a warning naming ``what``, the kind of response.
    """
    future: asyncio.Future[T] = asyncio.get_running_loop().create_future()

    def on_reply(reply: T) -> None:
        if not future.done() and accept(reply):
            future.set_result(reply)

    try:
        await subscribe(device, on_reply)
        await send()
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            return None
    finally:
        try:
            await unsubscribe(device, on_reply)
        except Exception:
            logger.warning(
                "Failed to unsubscribe %s response handler for device %s",
                what,
                redact_mac(device.device_info.mac_address),
                exc_info=True,
            )


def get_response_data(message: dict[str, Any], key: str | None) -> Any:
    """Extract data from an MQTT message, supporting key variants.

    Checks both the nested ``response`` dict and the top-level message,
    using both the primary key and its alternate short-form name (e.g.
    ``"status"`` / ``"st"``, ``"feature"`` / ``"did"``). Lookup order
    preserves a strict *nested-first* precedence:

    1. ``response[key]``
    2. ``response[alt_key]``
    3. ``message[key]``
    4. ``message[alt_key]``

    Key presence is checked explicitly (not by truthiness), so falsy
    values like ``0``, ``False``, or ``{}`` are returned correctly and
    do not fall through to a lower-precedence candidate.

    Args:
        message: Raw MQTT message dict.
        key: Primary key to look up. When ``None``, the nested
            ``response`` dict is returned directly.

    Returns:
        The value of the first *present* key in priority order,
        or ``None`` if no candidate key is found.
    """
    res: dict[str, Any] = message.get("response", {})
    if key is None:
        return res
    alt_key = _ALT_KEYS.get(key)
    for source, k in (
        (res, key),
        (res, alt_key),
        (message, key),
        (message, alt_key),
    ):
        if k is not None:
            value = source.get(k, _SENTINEL)
            if value is not _SENTINEL:
                return value
    return None


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

    for topic_part, pattern_part in zip(
        topic_parts, pattern_parts, strict=True
    ):
        if pattern_part != "+" and topic_part != pattern_part:
            return False

    return True
