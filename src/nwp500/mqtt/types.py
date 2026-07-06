"""Library-owned MQTT transport types.

This module defines transport-level types that the library exposes on its own
public and internal signatures instead of leaking ``awscrt`` SDK types. It is
the single boundary where the library's own :class:`QoS` enum is translated
to and from :class:`awscrt.mqtt.QoS`, keeping ``awscrt`` an implementation
detail that could be swapped for a different MQTT transport in the future.
"""

from enum import IntEnum

from awscrt import mqtt

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"


class QoS(IntEnum):
    """MQTT Quality of Service level.

    Mirrors the MQTT specification's QoS levels. Integer values match the
    wire protocol (and :class:`awscrt.mqtt.QoS`) so translation is a direct
    value mapping.
    """

    AT_MOST_ONCE = 0
    """QoS 0: fire-and-forget delivery with no acknowledgement."""

    AT_LEAST_ONCE = 1
    """QoS 1: acknowledged delivery; duplicates possible."""

    EXACTLY_ONCE = 2
    """QoS 2: acknowledged, exactly-once delivery."""


# Opaque handle for the underlying MQTT connection object. Typed as an alias so
# callers and internal code refer to the library's name rather than the
# concrete ``awscrt`` type, keeping the transport swappable.
type MqttConnectionHandle = mqtt.Connection


def to_awscrt_qos(qos: QoS) -> mqtt.QoS:
    """Translate a library :class:`QoS` to :class:`awscrt.mqtt.QoS`."""
    return mqtt.QoS(int(qos))


def from_awscrt_qos(qos: mqtt.QoS) -> QoS:
    """Translate an :class:`awscrt.mqtt.QoS` to a library :class:`QoS`."""
    return QoS(int(qos))
