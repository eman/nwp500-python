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
