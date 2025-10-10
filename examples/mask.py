"""Small helpers for masking sensitive identifiers in examples.

Place this file in the examples/ directory. Example scripts will try to import
these helpers; if that import fails we leave a small fallback in each script.
"""

from __future__ import annotations

import re
from typing import Optional


def mask_mac(mac: Optional[str]) -> str:
    """Always return fully redacted MAC address label, never expose partial values."""
    return "[REDACTED_MAC]"


def mask_mac_in_topic(topic: str, mac_addr: Optional[str] = None) -> str:
    """Return topic with any MAC-like substrings replaced.

    Also ensures a direct literal match of mac_addr is redacted.
    """
    try:
        mac_regex = r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|(?:[0-9A-Fa-f]{12})"
        topic_masked = re.sub(mac_regex, "[REDACTED_MAC]", topic)
        if mac_addr and mac_addr in topic_masked:
            topic_masked = topic_masked.replace(mac_addr, "[REDACTED_MAC]")
        return topic_masked
    except Exception:
        return "[REDACTED_TOPIC]"


__all__ = ["mask_mac", "mask_mac_in_topic"]


def mask_any(value: Optional[str]) -> str:
    """Generic redaction for strings considered sensitive in examples.

    Always returns a short redaction tag; keep implementation simple so examples
    never leak PII in printed output.
    """
    if not value:
        return "[REDACTED]"
    try:
        s = str(value)
        if not s:
            return "[REDACTED]"
        # Do not expose the string content in examples
        return "[REDACTED]"
    except Exception:
        return "[REDACTED]"


def mask_location(city: Optional[str], state: Optional[str]) -> str:
    """Redact location fields for examples.

    Returns a single redaction tag if either city or state are present.
    """
    if city or state:
        return "[REDACTED_LOCATION]"
    return ""


__all__.extend(["mask_any", "mask_location"])
