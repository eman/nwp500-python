"""Tests for command queue functionality."""

from collections import deque
from datetime import datetime

from awscrt import mqtt

from nwp500.mqtt_client import MqttConnectionConfig, QueuedCommand


def test_queued_command_dataclass():
    """Test QueuedCommand dataclass creation."""
    topic = "test/topic"
    payload = {"key": "value"}
    qos = mqtt.QoS.AT_LEAST_ONCE
    timestamp = datetime.utcnow()

    command = QueuedCommand(topic=topic, payload=payload, qos=qos, timestamp=timestamp)

    assert command.topic == topic
    assert command.payload == payload
    assert command.qos == qos
    assert command.timestamp == timestamp


def test_mqtt_config_default_queue_settings():
    """Test default command queue configuration."""
    config = MqttConnectionConfig()

    assert config.enable_command_queue is True
    assert config.max_queued_commands == 100


def test_mqtt_config_custom_queue_settings():
    """Test custom command queue configuration."""
    config = MqttConnectionConfig(enable_command_queue=False, max_queued_commands=50)

    assert config.enable_command_queue is False
    assert config.max_queued_commands == 50


def test_deque_maxlen():
    """Test that deque with maxlen drops oldest items."""
    max_size = 5
    queue = deque(maxlen=max_size)

    # Fill the queue
    for i in range(max_size):
        queue.append(i)

    assert len(queue) == max_size
    assert list(queue) == [0, 1, 2, 3, 4]

    # Add one more - oldest should be dropped
    queue.append(5)
    assert len(queue) == max_size
    assert list(queue) == [1, 2, 3, 4, 5]


def test_queued_command_fifo_order():
    """Test that queued commands maintain FIFO order."""
    queue = deque()
    timestamps = []

    # Add commands
    for i in range(5):
        timestamp = datetime.utcnow()
        timestamps.append(timestamp)
        command = QueuedCommand(
            topic=f"test/topic/{i}",
            payload={"value": i},
            qos=mqtt.QoS.AT_LEAST_ONCE,
            timestamp=timestamp,
        )
        queue.append(command)

    # Verify FIFO order
    for i in range(5):
        command = queue.popleft()
        assert command.topic == f"test/topic/{i}"
        assert command.payload == {"value": i}
        assert command.timestamp == timestamps[i]

    assert len(queue) == 0
