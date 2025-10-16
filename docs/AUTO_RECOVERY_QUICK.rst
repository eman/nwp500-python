===================================
Quick Reference: MQTT Auto-Recovery
===================================

TL;DR - Just Give Me The Code!
===============================

Copy this class into your project for production-ready automatic recovery:

.. code-block:: python

   import asyncio
   from nwp500 import NavienMqttClient
   from nwp500.mqtt_client import MqttConnectionConfig

   class ResilientMqttClient:
       """MQTT client with automatic recovery from permanent connection failures."""

       def __init__(self, auth_client, config=None):
           self.auth_client = auth_client
           self.config = config or MqttConnectionConfig()
           self.mqtt_client = None
           self.device = None
           self.status_callback = None
           self.recovery_attempt = 0
           self.max_recovery_attempts = 10
           self.recovery_delay = 60.0

       async def connect(self, device, status_callback=None):
           self.device = device
           self.status_callback = status_callback
           await self._create_client()

       async def _create_client(self):
           if self.mqtt_client and self.mqtt_client.is_connected:
               await self.mqtt_client.disconnect()

           self.mqtt_client = NavienMqttClient(self.auth_client, self.config)
           self.mqtt_client.on("reconnection_failed", self._handle_recovery)
           await self.mqtt_client.connect()

           if self.device and self.status_callback:
               await self.mqtt_client.subscribe_device_status(
                   self.device, self.status_callback
               )
               await self.mqtt_client.start_periodic_device_status_requests(self.device)

       async def _handle_recovery(self, attempts):
           self.recovery_attempt += 1
           if self.recovery_attempt >= self.max_recovery_attempts:
               return  # Give up

           await asyncio.sleep(self.recovery_delay)

           try:
               await self.auth_client.refresh_token()
               await self._create_client()
               self.recovery_attempt = 0  # Reset on success
           except Exception as e:
               # Log the error instead of silently passing
               import logging

               logging.getLogger(__name__).warning(f"Recovery attempt failed: {e}")
               # Will retry on next reconnection_failed

       async def disconnect(self):
           if self.mqtt_client:
               await self.mqtt_client.disconnect()

       @property
       def is_connected(self):
           return self.mqtt_client and self.mqtt_client.is_connected

**Usage:**

.. code-block:: python

   client = ResilientMqttClient(auth_client)
   await client.connect(device, status_callback=on_status)

   # Your client will now automatically recover from connection failures!

How It Works
============

1. **Normal operation**: MQTT client connects and operates normally
2. **Connection lost**: Client tries to reconnect automatically (10 attempts with exponential backoff)
3. **Reconnection fails**: After 10 attempts (~6 minutes), ``reconnection_failed`` event fires
4. **Auto-recovery kicks in**: 
   
   * Waits 60 seconds
   * Refreshes authentication tokens
   * Creates new MQTT client
   * Restores all subscriptions
   * Tries up to 10 recovery cycles

Configuration
=============

Tune the behavior:

.. code-block:: python

   config = MqttConnectionConfig(
       max_reconnect_attempts=10,      # Built-in reconnection attempts
       max_reconnect_delay=120.0,      # Max 2 min between attempts
   )

   client = ResilientMqttClient(auth_client, config=config)
   client.max_recovery_attempts = 10   # Recovery cycles
   client.recovery_delay = 60.0         # Seconds between recovery attempts

Complete Examples
=================

See these files for full working examples:

* ``examples/simple_auto_recovery.py`` - Production-ready pattern (recommended)
* ``examples/auto_recovery_example.py`` - All 4 strategies explained
* ``docs/AUTO_RECOVERY.rst`` - Complete documentation

Timeline Example
================

With default settings:

.. code-block:: text

   00:00 - Connection lost
   00:00 - Reconnect attempt 1 (1s delay)
   00:01 - Reconnect attempt 2 (2s delay)
   00:03 - Reconnect attempt 3 (4s delay)
   00:07 - Reconnect attempt 4 (8s delay)
   00:15 - Reconnect attempt 5 (16s delay)
   00:31 - Reconnect attempt 6 (32s delay)
   01:03 - Reconnect attempt 7 (64s delay)
   02:07 - Reconnect attempt 8 (120s delay, capped)
   04:07 - Reconnect attempt 9 (120s delay)
   06:07 - Reconnect attempt 10 (120s delay)

   06:07 - reconnection_failed event emitted
   06:07 - Recovery cycle 1 starts
   07:07 - Token refresh + client recreation
   07:07 - If successful, back to normal operation
   07:07 - If failed, wait for next reconnection_failed event

   [Process repeats up to max_recovery_attempts times]

Events You Can Listen To
========================

.. code-block:: python

   # Built-in MQTT events
   mqtt_client.on('connection_interrupted', lambda err: print(f"Interrupted: {err}"))
   mqtt_client.on('connection_resumed', lambda rc, sp: print("Resumed!"))
   mqtt_client.on('reconnection_failed', lambda attempts: print(f"Failed after {attempts}"))

   # In ResilientMqttClient, reconnection_failed is handled automatically

Testing
=======

Test automatic recovery:

1. Start your application
2. Disconnect internet for ~2 minutes
3. Reconnect internet
4. Watch automatic recovery in logs

Production Considerations
==========================

**DO:**

* ✅ Use ``ResilientMqttClient`` wrapper
* ✅ Set reasonable ``max_recovery_attempts`` (10-20)
* ✅ Log recovery events for monitoring
* ✅ Send alerts when recovery is triggered
* ✅ Monitor token expiration

**DON'T:**

* ❌ Set recovery delay too low (causes server load)
* ❌ Set max_recovery_attempts too high (wastes resources)
* ❌ Ignore the ``reconnection_failed`` event
* ❌ Forget to restore subscriptions after recovery

Need More Info?
================

Read the full documentation: :doc:`AUTO_RECOVERY`
