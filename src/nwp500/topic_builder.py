"""
MQTT topic building utilities for Navien devices.
"""


class MqttTopicBuilder:
    """Helper to construct standard MQTT topics for Navien devices."""

    @staticmethod
    def device_topic(mac_address: str) -> str:
        """Get the base device topic from MAC address."""
        return f"navilink-{mac_address}"

    @staticmethod
    def command_topic(
        device_type: str, mac_address: str, suffix: str = "ctrl"
    ) -> str:
        """
        Build a command topic.
        Format: cmd/{device_type}/navilink-{mac}/{suffix}
        """
        dt = MqttTopicBuilder.device_topic(mac_address)
        return f"cmd/{device_type}/{dt}/{suffix}"

    @staticmethod
    def response_topic(device_type: str, client_id: str, suffix: str) -> str:
        """
        Build a response topic.
        Format: cmd/{device_type}/{client_id}/res/{suffix}
        """
        return f"cmd/{device_type}/{client_id}/res/{suffix}"

    @staticmethod
    def event_topic(device_type: str, mac_address: str, suffix: str) -> str:
        """
        Build an event topic.
        Format: evt/{device_type}/navilink-{mac}/{suffix}
        """
        dt = MqttTopicBuilder.device_topic(mac_address)
        return f"evt/{device_type}/{dt}/{suffix}"
