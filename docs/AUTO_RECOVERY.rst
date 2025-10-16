========================================
Automatic Reconnection After Connection Failure
========================================

This guide explains how to automatically recover from permanent MQTT connection failures (after max reconnection attempts are exhausted).

Understanding the Problem
==========================

The MQTT client has built-in automatic reconnection with exponential backoff:

* When connection drops, it automatically tries to reconnect
* Default: 10 attempts with exponential backoff (1s → 120s)
* After 10 failed attempts, it stops and emits ``reconnection_failed`` event
* Periodic tasks are stopped to prevent log spam

The question is: **How do we automatically retry after these 10 attempts fail?**

Solution Overview
=================

There are 4 strategies, ranging from simple to production-ready:

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Strategy
     - Complexity
     - Use Case
   * - 1. Simple Retry
     - ⭐
     - Quick tests, simple scripts
   * - 2. Full Recreation
     - ⭐⭐
     - Better cleanup, medium apps
   * - 3. Token Refresh
     - ⭐⭐⭐
     - Long-running apps, token expiry issues
   * - 4. Exponential Backoff
     - ⭐⭐⭐⭐
     - **Production (Recommended)**

Strategy 1: Simple Retry with Reset
====================================

Just reset the reconnection counter and try again after a delay.

.. code-block:: python

   from nwp500 import NavienMqttClient
   from nwp500.mqtt_client import MqttConnectionConfig

   config = MqttConnectionConfig(max_reconnect_attempts=10)
   mqtt_client = NavienMqttClient(auth_client, config=config)

   async def on_reconnection_failed(attempts):
       print(f"Failed after {attempts} attempts. Retrying in 60s...")
       await asyncio.sleep(60)
       
       # Reset and retry using public API
       await mqtt_client.reset_reconnect()

   mqtt_client.on('reconnection_failed', on_reconnection_failed)
   await mqtt_client.connect()

**Pros:** Simple, minimal code

**Cons:** May need to refresh tokens for long-running connections

Strategy 2: Full Client Recreation
===================================

Create a new MQTT client instance when reconnection fails.

.. code-block:: python

   mqtt_client = None

   async def create_and_connect():
       global mqtt_client
       
       if mqtt_client and mqtt_client.is_connected:
           await mqtt_client.disconnect()
       
       mqtt_client = NavienMqttClient(auth_client, config=config)
       mqtt_client.on('reconnection_failed', on_reconnection_failed)
       await mqtt_client.connect()
       
       # Restore subscriptions
       await mqtt_client.subscribe_device_status(device, on_status)
       await mqtt_client.start_periodic_device_status_requests(device)
       
       return mqtt_client

   async def on_reconnection_failed(attempts):
       print(f"Failed after {attempts} attempts. Recreating client in 60s...")
       await asyncio.sleep(60)
       await create_and_connect()

   mqtt_client = await create_and_connect()

**Pros:** Clean state, more reliable

**Cons:** Need to restore all subscriptions

Strategy 3: Token Refresh and Retry
====================================

Refresh authentication tokens before retrying (handles token expiry).

.. code-block:: python

   async def on_reconnection_failed(attempts):
       print(f"Failed after {attempts} attempts. Refreshing tokens and retrying...")
       await asyncio.sleep(60)
       
       # Refresh authentication tokens
       await auth_client.refresh_token()
       
       # Recreate client with fresh tokens
       mqtt_client = NavienMqttClient(auth_client, config=config)
       mqtt_client.on('reconnection_failed', on_reconnection_failed)
       await mqtt_client.connect()
       
       # Restore subscriptions
       await mqtt_client.subscribe_device_status(device, on_status)
       await mqtt_client.start_periodic_device_status_requests(device)

**Pros:** Handles token expiry, more robust

**Cons:** More complex, need to manage client lifecycle

Strategy 4: Exponential Backoff (Production-Ready) ⭐ RECOMMENDED
=================================================================

Use exponential backoff between recovery attempts with token refresh.

.. code-block:: python

   import asyncio
   from nwp500 import NavienMqttClient
   from nwp500.mqtt_client import MqttConnectionConfig

   class ResilientMqttClient:
       """Production-ready MQTT client with automatic recovery."""
       
       def __init__(self, auth_client, config=None):
           self.auth_client = auth_client
           self.config = config or MqttConnectionConfig()
           self.mqtt_client = None
           self.device = None
           self.callbacks = {}
           
           # Recovery settings
           self.recovery_attempt = 0
           self.max_recovery_attempts = 10
           self.initial_recovery_delay = 60.0
           self.max_recovery_delay = 300.0
           self.recovery_backoff_multiplier = 2.0
       
       async def connect(self, device, status_callback=None):
           """Connect with automatic recovery."""
           self.device = device
           self.callbacks['status'] = status_callback
           await self._create_client()
       
       async def _create_client(self):
           """Create and configure MQTT client."""
           # Cleanup old client
           if self.mqtt_client and self.mqtt_client.is_connected:
               await self.mqtt_client.disconnect()
           
           # Create new client
           self.mqtt_client = NavienMqttClient(self.auth_client, self.config)
           self.mqtt_client.on('reconnection_failed', self._handle_recovery)
           
           # Connect
           await self.mqtt_client.connect()
           
           # Restore subscriptions
           if self.device and self.callbacks.get('status'):
               await self.mqtt_client.subscribe_device_status(
                   self.device, self.callbacks['status']
               )
               await self.mqtt_client.start_periodic_device_status_requests(
                   self.device
               )
       
       async def _handle_recovery(self, attempts):
           """Handle reconnection failure with exponential backoff."""
           self.recovery_attempt += 1
           
           if self.recovery_attempt >= self.max_recovery_attempts:
               print("Max recovery attempts reached. Manual intervention required.")
               # Send alert, restart app, etc.
               return
           
           # Calculate delay with exponential backoff
           delay = min(
               self.initial_recovery_delay * 
               (self.recovery_backoff_multiplier ** (self.recovery_attempt - 1)),
               self.max_recovery_delay
           )
           
           print(f"Recovery attempt {self.recovery_attempt} in {delay:.0f}s...")
           await asyncio.sleep(delay)
           
           try:
               # Refresh tokens every few attempts
               if self.recovery_attempt % 3 == 0:
                   await self.auth_client.refresh_token()
               
               # Recreate client
               await self._create_client()
               
               # Reset on success
               self.recovery_attempt = 0
               print("✅ Recovery successful!")
               
           except Exception as e:
               print(f"Recovery failed: {e}")
       
       async def disconnect(self):
           """Disconnect gracefully."""
           if self.mqtt_client and self.mqtt_client.is_connected:
               await self.mqtt_client.disconnect()
       
       @property
       def is_connected(self):
           return self.mqtt_client and self.mqtt_client.is_connected

   # Usage
   async with NavienAuthClient(email, password) as auth_client:
       api_client = NavienAPIClient(auth_client=auth_client)
       device = await api_client.get_first_device()
       
       def on_status(status):
           print(f"Temperature: {status.dhwTemperature}°F")
       
       # Create resilient client
       mqtt_config = MqttConnectionConfig(
           auto_reconnect=True,
           max_reconnect_attempts=10,
       )
       
       client = ResilientMqttClient(auth_client, config=mqtt_config)
       await client.connect(device, status_callback=on_status)
       
       # Monitor indefinitely
       while True:
           await asyncio.sleep(60)
           print(f"Status: {'Connected' if client.is_connected else 'Reconnecting...'}")

**Pros:**

* Production-ready
* Handles token expiry
* Exponential backoff prevents overwhelming the server
* Configurable limits
* Clean error handling

**Cons:** More code (but provided in examples)

Configuration Options
=====================

You can tune the reconnection behavior:

.. code-block:: python

   config = MqttConnectionConfig(
       # Initial reconnection (built-in)
       auto_reconnect=True,
       max_reconnect_attempts=10,
       initial_reconnect_delay=1.0,      # Start with 1s
       max_reconnect_delay=120.0,        # Cap at 2 minutes
       reconnect_backoff_multiplier=2.0, # Double each time
   )

**Reconnection Timeline:**

1. Attempt 1: 1s delay
2. Attempt 2: 2s delay
3. Attempt 3: 4s delay
4. Attempt 4: 8s delay
5. Attempt 5: 16s delay
6. Attempt 6: 32s delay
7. Attempt 7: 64s delay
8. Attempts 8-10: 120s delay (capped)

After 10 attempts (~6 minutes), ``reconnection_failed`` event is emitted.

Best Practices
==============

1. Use the ResilientMqttClient wrapper (Strategy 4)
----------------------------------------------------

See ``examples/simple_auto_recovery.py`` for a complete implementation.

2. Implement monitoring and alerting
-------------------------------------

.. code-block:: python

   async def on_reconnection_failed(attempts):
       # Send alert when recovery starts
       await send_alert(f"MQTT connection failed after {attempts} attempts")

3. Set reasonable limits
------------------------

.. code-block:: python

   max_recovery_attempts = 10        # Stop after 10 recovery cycles
   max_recovery_delay = 300.0        # Max 5 minutes between attempts

4. Refresh tokens periodically
-------------------------------

.. code-block:: python

   # Refresh every 3rd recovery attempt
   if recovery_attempt % 3 == 0:
       await auth_client.refresh_token()

5. Log recovery events
----------------------

.. code-block:: python

   logger.info(f"Recovery attempt {recovery_attempt}/{max_recovery_attempts}")
   logger.info(f"Waiting {delay:.0f} seconds before retry")
   logger.info("✅ Recovery successful!")

Examples
========

Complete working examples are provided:

1. **examples/simple_auto_recovery.py** - Recommended pattern (Strategy 4)
   
   * Production-ready ResilientMqttClient wrapper
   * Exponential backoff
   * Token refresh
   * Easy to use

2. **examples/auto_recovery_example.py** - All 4 strategies
   
   * Shows all approaches side-by-side
   * Good for learning and comparison
   * Select strategy with ``STRATEGY=1-4`` env var

Run them:

.. code-block:: bash

   # Simple recovery (recommended)
   NAVIEN_EMAIL=your@email.com NAVIEN_PASSWORD=yourpass \
   python examples/simple_auto_recovery.py

   # All strategies (for learning)
   NAVIEN_EMAIL=your@email.com NAVIEN_PASSWORD=yourpass STRATEGY=4 \
   python examples/auto_recovery_example.py

Testing Recovery
================

To test automatic recovery:

1. Start the example
2. Wait for connection
3. Disconnect your internet for ~1 minute
4. Reconnect internet
5. Watch the client automatically recover

The logs will show:

.. code-block:: text

   ERROR: Failed to reconnect after 10 attempts. Manual reconnection required.
   INFO: Stopping 2 periodic task(s) due to connection failure
   INFO: Starting recovery attempt 1/10
   INFO: Waiting 60 seconds before recovery...
   INFO: Refreshing authentication tokens...
   INFO: Recreating MQTT client...
   INFO: ✅ Connected: navien-client-abc123
   INFO: Subscriptions restored
   INFO: ✅ Recovery successful!

When to Use Each Strategy
==========================

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Scenario
     - Recommended Strategy
   * - Simple script, occasional use
     - Strategy 1: Simple Retry
   * - Development/testing
     - Strategy 2: Full Recreation
   * - Long-running service
     - Strategy 3: Token Refresh
   * - **Production application**
     - **Strategy 4: Exponential Backoff**
   * - Home automation integration
     - Strategy 4: Exponential Backoff
   * - Monitoring dashboard
     - Strategy 4: Exponential Backoff

Additional Options
==================

Increase max reconnection attempts
-----------------------------------

Instead of implementing recovery, you can increase the built-in attempts:

.. code-block:: python

   config = MqttConnectionConfig(
       max_reconnect_attempts=50,  # Try 50 times before giving up
       max_reconnect_delay=300.0,  # Up to 5 minutes between attempts
   )

This gives ~4+ hours of retry attempts before needing recovery.

Disable automatic reconnection
-------------------------------

If you want to handle everything manually:

.. code-block:: python

   config = MqttConnectionConfig(
       auto_reconnect=False,  # Disable automatic reconnection
   )

   mqtt_client.on('connection_interrupted', my_custom_handler)

Conclusion
==========

For production use, **use Strategy 4 (Exponential Backoff)** via the ``ResilientMqttClient`` wrapper provided in ``examples/simple_auto_recovery.py``. It handles:

* ✅ Automatic recovery from permanent failures
* ✅ Exponential backoff to prevent server overload
* ✅ Token refresh for long-running connections
* ✅ Clean client recreation
* ✅ Subscription restoration
* ✅ Configurable limits and delays

This ensures your application stays connected even during extended network outages.
