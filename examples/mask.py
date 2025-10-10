"""Small helpers for masking sensitive identifiers in examples.

Place this file in the examples/ directory. Example scripts will try to import
these helpers; if that import fails we leave a small fallback in each script.
"""

from __future__ import annotations

import re
from typing import Optional


def mask_mac(mac: Optional[str]) -> str:
    """Return a masked representation of a MAC-like string.

    - If a MAC-like pattern is detected it is replaced with "[REDACTED_MAC]".
    - If the input is None/empty we return a redaction tag.
    - Otherwise we return a short masked fallback showing the last 4 chars.
    """
    if not mac:
        return "[REDACTED_MAC]"

    try:
        mac_regex = r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|(?:[0-9A-Fa-f]{12})"
        masked = re.sub(mac_regex, "[REDACTED_MAC]", mac)
        if masked and masked != mac:
            return masked
        # fallback: always redact to avoid any leakage
        return "[REDACTED_MAC]"
    except Exception:
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
