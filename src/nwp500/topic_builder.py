"""
MQTT topic building utilities for Navien devices.

All MQTT topic construction goes through this class so that the topic schema
is defined in exactly one place.

Topic schema:
  Device command (ctrl/query): cmd/{device_type}/navilink-{mac}/{suffix}
  Device subscribe (wildcard):  cmd/{device_type}/navilink-{mac}/#
  Response (control ack):       cmd/{device_type}/navilink-{mac}/{client_id}/res
  Response (query result):      cmd/{device_type}/{client_id}/res/{suffix}
  Event:                        evt/{device_type}/navilink-{mac}/{suffix}
"""


class MqttTopicBuilder:
    """Helper to construct standard MQTT topics for Navien devices."""

    @staticmethod
    def device_topic(mac_address: str) -> str:
        """Get the navilink device path segment from MAC address."""
        return f"navilink-{mac_address}"

    @staticmethod
    def command_topic(
        device_type: str, mac_address: str, suffix: str = "ctrl"
    ) -> str:
        """Build a device command topic.

        Format: ``cmd/{device_type}/navilink-{mac}/{suffix}``
        """
        dt = MqttTopicBuilder.device_topic(mac_address)
        return f"cmd/{device_type}/{dt}/{suffix}"

    @staticmethod
    def response_ack_topic(
        device_type: str, mac_address: str, client_id: str
    ) -> str:
        """Build the default response topic for control commands.

        The device sends its acknowledgement to this topic; the client
        subscribes via the ``command_topic(..., "#")`` wildcard.

        Format: ``cmd/{device_type}/navilink-{mac}/{client_id}/res``
        """
        dt = MqttTopicBuilder.device_topic(mac_address)
        return f"cmd/{device_type}/{dt}/{client_id}/res"

    @staticmethod
    def response_topic(device_type: str, client_id: str, suffix: str) -> str:
        """Build a client-specific response topic for query commands.

        Used when the device should reply directly to a client-keyed topic
        rather than the device topic (e.g. reservation reads, TOU reads,
        energy queries).

        Format: ``cmd/{device_type}/{client_id}/res/{suffix}``
        """
        return f"cmd/{device_type}/{client_id}/res/{suffix}"

    @staticmethod
    def event_topic(device_type: str, mac_address: str, suffix: str) -> str:
        """Build a device event topic.

        Format: ``evt/{device_type}/navilink-{mac}/{suffix}``
        """
        dt = MqttTopicBuilder.device_topic(mac_address)
        return f"evt/{device_type}/{dt}/{suffix}"
