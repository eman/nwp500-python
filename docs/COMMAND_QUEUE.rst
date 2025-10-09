=======================
MQTT Command Queue
=======================

Summary
=======

The MQTT client (``NavienMqttClient``) implements automatic command queuing. Commands sent while disconnected are automatically queued and sent when the connection is restored, ensuring no commands are lost during network interruptions.

Features
========

Automatic Command Queuing
--------------------------

- Commands are automatically queued when sent while disconnected
- Queue is processed automatically when connection is restored
- Commands are sent in FIFO (first-in-first-out) order
- No user intervention required

Queue Configuration
-------------------

New fields added to ``MqttConnectionConfig``:

.. code-block:: python

    @dataclass
    class MqttConnectionConfig:
        # ... existing fields ...
        
        # Command queue settings
        enable_command_queue: bool = True
        max_queued_commands: int = 100

Configuration Options
^^^^^^^^^^^^^^^^^^^^^

- ``enable_command_queue`` - Enable/disable command queuing (default: True)
- ``max_queued_commands`` - Maximum number of commands to queue (default: 100)

When the queue is full, the oldest command is automatically dropped to make room for new commands.

Queue Management
----------------

**New Properties:**

- ``queued_commands_count`` - Get the number of commands currently queued

**New Methods:**

- ``clear_command_queue()`` - Manually clear all queued commands

**Internal Components:**

- ``QueuedCommand`` dataclass - Stores command details (topic, payload, QoS, timestamp)
- ``_command_queue`` - Deque with maximum length for efficient FIFO operations
- ``_queue_command()`` - Internal method to add commands to queue
- ``_send_queued_commands()`` - Internal method to process queue on reconnection

Integration with Reconnection
------------------------------

The command queue integrates seamlessly with the existing automatic reconnection feature:

1. Connection is lost
2. Commands sent during disconnection are queued
3. Automatic reconnection begins (with exponential backoff)
4. Connection is restored
5. Queued commands are automatically sent
6. Queue is cleared

Implementation Details
======================

Command Flow
------------

When Connected
^^^^^^^^^^^^^^

::

    User calls command method
          ↓
    publish() called
          ↓
    Command sent immediately via MQTT
          ↓
    Returns packet ID

When Disconnected (Queue Enabled)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

::

    User calls command method
          ↓
    publish() called
          ↓
    Detects disconnection
          ↓
    Adds command to queue
          ↓
    Returns 0 (queued indicator)

On Reconnection
^^^^^^^^^^^^^^^

::

    Connection restored
          ↓
    _on_connection_resumed_internal() triggered
          ↓
    _send_queued_commands() scheduled
          ↓
    Process queue:
      For each command:
        1. Remove from queue
        2. Attempt to send
        3. On success: continue
        4. On failure: re-queue and stop
          ↓
    Queue empty or error

Error Handling
--------------

Queue Full
^^^^^^^^^^

- Oldest command is automatically dropped (deque with maxlen)
- Warning logged
- New command is added

Send Failure
^^^^^^^^^^^^

- Failed command is re-queued (if space available)
- Queue processing stops to prevent cascade failures
- Error logged
- Remaining commands stay queued for next reconnection

Disabled Queue
^^^^^^^^^^^^^^

- ``RuntimeError`` raised if trying to publish while disconnected
- Useful for strict fail-fast behavior if desired

Usage Examples
==============

Basic Usage (Default Configuration)
------------------------------------

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienMqttClient

    async with NavienAuthClient(email, password) as auth_client:
        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()
        
        # Command queue is enabled by default
        # Commands sent during disconnection are automatically queued
        await mqtt_client.request_device_status(device)
        
        # If disconnected, command is queued and sent on reconnection
        # No user action needed

Custom Configuration
--------------------

.. code-block:: python

    from nwp500.mqtt_client import MqttConnectionConfig

    config = MqttConnectionConfig(
        enable_command_queue=True,
        max_queued_commands=50,  # Limit queue to 50 commands
        auto_reconnect=True,
    )

    mqtt_client = NavienMqttClient(auth_client, config=config)
    await mqtt_client.connect()

Disable Command Queue
---------------------

.. code-block:: python

    config = MqttConnectionConfig(
        enable_command_queue=False,  # Disable queue
        auto_reconnect=True,
    )

    mqtt_client = NavienMqttClient(auth_client, config=config)
    await mqtt_client.connect()

    # RuntimeError raised if command sent while disconnected

Monitor Queue Size
------------------

.. code-block:: python

    # Check how many commands are queued
    count = mqtt_client.queued_commands_count
    print(f"Commands in queue: {count}")

    # Clear queue manually if needed
    mqtt_client.clear_command_queue()
    print(f"Queue cleared. Size: {mqtt_client.queued_commands_count}")

Handle Queue Full Condition
----------------------------

.. code-block:: python

    # Queue has max size of 100 by default
    # Oldest commands automatically dropped when full
    for i in range(150):
        await mqtt_client.request_device_status(device)
        # First 100 queued, remaining 50 replace oldest

    print(f"Queued: {mqtt_client.queued_commands_count}")  # Will be 100

Benefits
========

1. **No Lost Commands** - Commands sent during disconnection are preserved
2. **Automatic Recovery** - Works seamlessly with auto-reconnection
3. **Transparent** - Works automatically without user intervention
4. **Configurable** - Adjust queue size or disable if needed
5. **Monitorable** - Query queue status at any time
6. **Efficient** - FIFO queue with O(1) operations using deque
7. **Safe** - Queue limits prevent memory issues
8. **Order Preserved** - Commands sent in original order

Design Philosophy
=================

The command queue feature is designed with reliability and ease of use in mind:

- **Enabled by default** - Most users want commands preserved during network issues
- **Automatic operation** - No manual queue management required
- **Configurable** - Can be disabled or tuned for specific use cases
- **Integrated** - Works seamlessly with automatic reconnection

Use Cases
=========

Reliable Device Control
-----------------------

.. code-block:: python

    # Even during network issues, commands are preserved
    await mqtt_client.set_dhw_temperature_display(device, 140)
    await mqtt_client.set_dhw_mode(device, 2)  # Energy Saver mode

    # Commands queued if disconnected, sent when reconnected

Monitoring with Interruptions
------------------------------

.. code-block:: python

    # Periodic status requests continue even with network issues
    await mqtt_client.start_periodic_device_status_requests(device, 60)

    # Requests queued during disconnection, sent on reconnection

Batch Operations
----------------

.. code-block:: python

    # Send multiple commands without worrying about connection state
    for device in devices:
        await mqtt_client.request_device_status(device)
        await mqtt_client.request_device_info(device)

    # All commands reach their destination eventually

Technical Notes
===============

- Queue uses ``collections.deque`` with maxlen for efficient FIFO operations
- Timestamps are recorded when commands are queued (for debugging/logging)
- QoS (Quality of Service) level is preserved in queue
- Queue is cleared on manual disconnect (via ``disconnect()``)
- Queue persists across automatic reconnections
- Failed sends are re-queued if space available
- Processing stops on first error to prevent cascade failures
- Queue state is maintained across multiple disconnect/reconnect cycles

See Also
========

- :doc:`MQTT_CLIENT` - MQTT client documentation
- :doc:`EVENT_EMITTER` - Event emitter documentation
- :doc:`AUTHENTICATION` - Authentication and tokens

Example Code
============

Complete working examples can be found in the ``examples/`` directory:

- ``examples/command_queue_demo.py`` - Comprehensive command queue demonstration

.. note::
   The command queue feature works hand-in-hand with automatic reconnection. When disconnection occurs, commands are queued automatically and sent when the connection is restored. No user intervention is required.
