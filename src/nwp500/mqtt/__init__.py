"""MQTT package for Navien device communication.

This package provides MQTT client functionality for real-time communication
with Navien devices using AWS IoT Core.

Main exports:
- NavienMqttClient: Main MQTT client class
- MqttConnectionConfig: Configuration for MQTT connections
- PeriodicRequestType: Enum for periodic request types
- MqttDiagnosticsCollector: Metrics and diagnostics collector
- MqttMetrics, ConnectionDropEvent, ConnectionEvent: Diagnostic types
"""

from .client import NavienMqttClient
from .diagnostics import (
    ConnectionDropEvent,
    ConnectionEvent,
    MqttDiagnosticsCollector,
    MqttMetrics,
)
from .utils import MqttConnectionConfig, PeriodicRequestType

__all__ = [
    "NavienMqttClient",
    "MqttConnectionConfig",
    "PeriodicRequestType",
    "MqttDiagnosticsCollector",
    "MqttMetrics",
    "ConnectionDropEvent",
    "ConnectionEvent",
]
