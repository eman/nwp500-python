MQTT Client Documentation
=========================

Overview
--------

The Navien MQTT Client provides real-time communication with Navien
NWP500 water heaters using AWS IoT Core WebSocket connections. It
enables:

- Real-time device status monitoring
- Device control (temperature, mode, power)
- Bidirectional communication over MQTT
- Automatic reconnection and error handling
- **Non-blocking async operations** (compatible with Home Assistant and other async applications)

The client is designed to be fully non-blocking and integrates seamlessly
with async event loops, avoiding the "blocking I/O detected" warnings
commonly seen in Home Assistant and similar applications.

Prerequisites
-------------

.. code:: bash

   pip install awsiotsdk>=1.20.0

Usage Examples
--------------

1. Basic Connection
~~~~~~~~~~~~~~~~~~~

.. code:: python

   import asyncio
   from nwp500 import NavienAuthClient, NavienMqttClient

   async def main():
       # Authenticate
       async with NavienAuthClient("email@example.com", "password") as auth_client:
           
           # Create MQTT client with auth client
           mqtt_client = NavienMqttClient(auth_client)
           
           # Connect to AWS IoT
           await mqtt_client.connect()
           print(f"Connected! Client ID: {mqtt_client.client_id}")
           
           # Disconnect when done
           await mqtt_client.disconnect()

   asyncio.run(main())

2. Subscribe to Device Messages
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   def message_handler(topic: str, message: dict):
       print(f"Received message on {topic}")
       if 'response' in message:
           status = message['response'].get('status', {})
           print(f"DHW Temperature: {status.get('dhwTemperature')}°F")

   # Subscribe to all messages from a device
   await mqtt_client.subscribe_device(device, message_handler)

3. Request Device Status
~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   # Request current device status
   await mqtt_client.request_device_status(device)

4. Control Device
~~~~~~~~~~~~~~~~~

.. code:: python

   # Turn device on/off
   await mqtt_client.set_power(device, power_on=True)

   # Set DHW mode (1=Heat Pump Only, 2=Electric Only, 3=Energy Saver, 4=High Demand)
   await mqtt_client.set_dhw_mode(device, mode_id=3)

   # Set target temperature
   await mqtt_client.set_dhw_temperature(device, temperature=120)

Complete Example
----------------

.. code:: python

   import asyncio
   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

   async def main():
       # Step 1: Authenticate
       async with NavienAuthClient("email@example.com", "password") as auth_client:
           
           # Step 2: Get device list
           api_client = NavienAPIClient(auth_client=auth_client)
           devices = await api_client.list_devices()
           
           device = devices[0]
           
           print(f"Connecting to device: {device.device_info.device_name}")
           
           # Step 3: Connect MQTT
           mqtt_client = NavienMqttClient(auth_client)
           await mqtt_client.connect()
           
           # Step 4: Subscribe and send commands
           messages_received = []
           
           def handle_message(topic, message):
               messages_received.append(message)
               print(f"Message: {message}")
           
           await mqtt_client.subscribe_device(device, handle_message)
           
           # Signal app connection
           await mqtt_client.signal_app_connection(device)
           
           # Request status
           await mqtt_client.request_device_status(device)
           
           # Wait for responses
           await asyncio.sleep(10)
           
           print(f"Received {len(messages_received)} messages")
           
           # Step 5: Disconnect
           await mqtt_client.disconnect()

   asyncio.run(main())

API Reference
-------------

NavienMqttClient
~~~~~~~~~~~~~~~~

Constructor
^^^^^^^^^^^

.. code:: python

   NavienMqttClient(
       auth_client: NavienAuthClient,
       config: Optional[MqttConnectionConfig] = None,
       on_connection_interrupted: Optional[Callable] = None,
       on_connection_resumed: Optional[Callable] = None
   )

**Parameters:** - ``auth_client``: Authenticated NavienAuthClient
instance (required) - ``config``: Optional connection configuration -
``on_connection_interrupted``: Callback for connection interruption -
``on_connection_resumed``: Callback for connection resumption

Automatic Reconnection
^^^^^^^^^^^^^^^^^^^^^^

The MQTT client automatically reconnects when the connection is interrupted,
using exponential backoff to avoid overwhelming the server.

**Reconnection Behavior:**

- Automatically triggered when connection is lost (unless manually disconnected)
- Uses exponential backoff: 1s, 2s, 4s, 8s, 16s, ... up to max delay
- Continues until max attempts reached or connection restored
- All subscriptions are maintained by AWS IoT SDK

**Default Configuration:**

.. code:: python

   config = MqttConnectionConfig(
       auto_reconnect=True,              # Enable automatic reconnection
       max_reconnect_attempts=10,        # Maximum retry attempts
       initial_reconnect_delay=1.0,      # Initial delay in seconds
       max_reconnect_delay=120.0,        # Maximum delay cap
       reconnect_backoff_multiplier=2.0  # Exponential multiplier
   )

**Custom Reconnection Example:**

.. code:: python

   from nwp500.mqtt_client import MqttConnectionConfig
   
   # Create custom configuration
   config = MqttConnectionConfig(
       auto_reconnect=True,
       max_reconnect_attempts=15,
       initial_reconnect_delay=2.0,  # Start with 2 seconds
       max_reconnect_delay=60.0,     # Cap at 1 minute
   )
   
   # Callbacks to monitor reconnection
   def on_interrupted(error):
       print(f"Connection lost: {error}")
   
   def on_resumed(return_code, session_present):
       print(f"Reconnected! Code: {return_code}")
   
   # Create client with custom config
   mqtt_client = NavienMqttClient(
       auth_client,
       config=config,
       on_connection_interrupted=on_interrupted,
       on_connection_resumed=on_resumed
   )
   
   await mqtt_client.connect()
   
   # Check reconnection status
   if mqtt_client.is_reconnecting:
       print(f"Reconnecting: attempt {mqtt_client.reconnect_attempts}")

**Properties:**

- ``is_connected`` - Check if currently connected
- ``is_reconnecting`` - Check if reconnection in progress
- ``reconnect_attempts`` - Number of reconnection attempts made

Command Queue
^^^^^^^^^^^^^

The MQTT client automatically queues commands sent while disconnected and sends
them when the connection is restored. This ensures no commands are lost during
network interruptions.

**Queue Behavior:**

- Commands are queued automatically when sent while disconnected
- Queue is processed in FIFO (first-in-first-out) order on reconnection
- Integrates seamlessly with automatic reconnection
- Configurable queue size with automatic oldest-command-dropping when full
- No user intervention required

**Default Configuration:**

.. code:: python

   config = MqttConnectionConfig(
       enable_command_queue=True,  # Enable command queuing
       max_queued_commands=100,    # Maximum queue size
   )

**Queue Usage Example:**

.. code:: python

   from nwp500.mqtt_client import MqttConnectionConfig
   
   # Configure command queue
   config = MqttConnectionConfig(
       enable_command_queue=True,
       max_queued_commands=50,  # Limit to 50 commands
       auto_reconnect=True,
   )
   
   mqtt_client = NavienMqttClient(auth_client, config=config)
   await mqtt_client.connect()
   
   # Commands sent while disconnected are automatically queued
   await mqtt_client.request_device_status(device)  # Queued if disconnected
   await mqtt_client.set_dhw_temperature_display(device, 130)  # Also queued
   
   # Check queue status
   queue_size = mqtt_client.queued_commands_count
   print(f"Commands queued: {queue_size}")
   
   # Clear queue manually if needed
   cleared = mqtt_client.clear_command_queue()
   print(f"Cleared {cleared} commands")

**Disable Command Queue:**

.. code:: python

   # Disable queuing if desired
   config = MqttConnectionConfig(
       enable_command_queue=False,  # Disabled
   )
   
   mqtt_client = NavienMqttClient(auth_client, config=config)
   
   # Now commands sent while disconnected will raise RuntimeError

**Properties:**

- ``queued_commands_count`` - Get number of commands currently queued

**Methods:**

- ``clear_command_queue()`` - Clear all queued commands, returns count cleared

Connection Methods
^^^^^^^^^^^^^^^^^^

connect()
'''''''''

.. code:: python

   await mqtt_client.connect() -> bool

Establish WebSocket connection to AWS IoT Core.

**Returns:** ``True`` if connection successful

**Raises:** ``Exception`` if connection fails

disconnect()
''''''''''''

.. code:: python

   await mqtt_client.disconnect()

Disconnect from AWS IoT Core and cleanup resources.

Subscription Methods
^^^^^^^^^^^^^^^^^^^^

subscribe()
'''''''''''

.. code:: python

   await mqtt_client.subscribe(
       topic: str,
       callback: Callable[[str, Dict], None],
       qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE
   ) -> int

Subscribe to an MQTT topic.

**Parameters:** - ``topic``: MQTT topic (supports wildcards like ``#``
and ``+``) - ``callback``: Function called when messages arrive
``(topic, message) -> None`` - ``qos``: Quality of Service level

**Returns:** Subscription packet ID

subscribe_device()
''''''''''''''''''

.. code:: python

   await mqtt_client.subscribe_device(
       device: Device,
       callback: Callable[[str, Dict], None]
   ) -> int

Subscribe to all messages from a specific device.

**Parameters:** - ``device``: Device object from API client -
``callback``: Message handler function

**Returns:** Subscription packet ID

unsubscribe()
'''''''''''''

.. code:: python

   await mqtt_client.unsubscribe(topic: str)

Unsubscribe from an MQTT topic.

Publishing Methods
^^^^^^^^^^^^^^^^^^

publish()
'''''''''

.. code:: python

   await mqtt_client.publish(
       topic: str,
       payload: Dict[str, Any],
       qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE
   ) -> int

Publish a message to an MQTT topic.

**Parameters:** - ``topic``: MQTT topic - ``payload``: Message payload
(will be JSON-encoded) - ``qos``: Quality of Service level

**Returns:** Publish packet ID

Device Command Methods
^^^^^^^^^^^^^^^^^^^^^^

request_device_status()
'''''''''''''''''''''''

.. code:: python

   await mqtt_client.request_device_status(device: Device) -> int

Request current device status.

**Command:** ``16777219``

**Topic:** ``cmd/{device_type}/navilink-{device_id}/st``

request_device_info()
'''''''''''''''''''''

.. code:: python

   await mqtt_client.request_device_info(device: Device) -> int

Request device information.

**Command:** ``16777217``

**Topic:** ``cmd/{device_type}/navilink-{device_id}/st/did``

set_power()
'''''''''''

.. code:: python

   await mqtt_client.set_power(device: Device, power_on: bool) -> int

Turn device on or off.

**Command:** ``33554433``

**Mode:** ``power-on`` or ``power-off``

set_dhw_mode()
''''''''''''''

.. code:: python

   await mqtt_client.set_dhw_mode(device: Device, mode_id: int) -> int

Set DHW (Domestic Hot Water) operation mode.

**Command:** ``33554433``

**Mode:** ``dhw-mode``

**Mode IDs:** - ``1``: Heat Pump (most efficient, longest recovery) -
``2``: Electric (least efficient, fastest recovery) - ``3``: Energy
Saver (default, balanced) - ``4``: High Demand (faster recovery)

set_dhw_temperature()
'''''''''''''''''''''

.. code:: python

   await mqtt_client.set_dhw_temperature(device: Device, temperature: int) -> int

Set DHW target temperature.

**Command:** ``33554433``

**Mode:** ``dhw-temperature``

**Parameters:** - ``temperature``: Target temperature in Fahrenheit

signal_app_connection()
'''''''''''''''''''''''

.. code:: python

   await mqtt_client.signal_app_connection(device: Device) -> int

Signal that the app has connected.

**Topic:** ``evt/{device_type}/navilink-{device_id}/app-connection``

Periodic Request Methods (Optional)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These optional helper methods automate regular device updates.

start_periodic_requests()
'''''''''''''''''''''''''

.. code:: python

   await mqtt_client.start_periodic_requests(
       device: Device,
       request_type: PeriodicRequestType = PeriodicRequestType.DEVICE_STATUS,
       period_seconds: float = 300.0
   ) -> None

Start sending periodic requests for device information or status.

**Parameters:** - ``device``: Device object from API client -
``request_type``: Type of request (``PeriodicRequestType.DEVICE_INFO``
or ``PeriodicRequestType.DEVICE_STATUS``) - ``period_seconds``: Time
between requests in seconds (default: 300 = 5 minutes)

**Example:**

.. code:: python

   from nwp500 import PeriodicRequestType

   # Default: periodic status requests every 5 minutes
   await mqtt_client.start_periodic_requests(device)

   # Periodic device info requests
   await mqtt_client.start_periodic_requests(
       device,
       request_type=PeriodicRequestType.DEVICE_INFO
   )

   # Custom period (1 minute)
   await mqtt_client.start_periodic_requests(
       device,
       period_seconds=60
   )

   # Both types simultaneously
   await mqtt_client.start_periodic_requests(
       device,
       request_type=PeriodicRequestType.DEVICE_STATUS,
       period_seconds=300
   )
   await mqtt_client.start_periodic_requests(
       device,
       request_type=PeriodicRequestType.DEVICE_INFO,
       period_seconds=600
   )

**Notes:**
- Only one task per request type per device
- Tasks automatically stop when client disconnects
- Continues running even if connection is interrupted (skips requests when disconnected)

stop_periodic_requests()
''''''''''''''''''''''''

.. code:: python

   await mqtt_client.stop_periodic_requests(
       device: Device,
       request_type: Optional[PeriodicRequestType] = None
   ) -> None

Stop sending periodic requests for a device.

**Parameters:** - ``device``: Device object from API client -
``request_type``: Type to stop. If None, stops all types for this
device.

**Example:**

.. code:: python

   # Stop specific type
   await mqtt_client.stop_periodic_requests(
       device,
       PeriodicRequestType.DEVICE_STATUS
   )

   # Stop all types for device
   await mqtt_client.stop_periodic_requests(device)

Convenience Methods
'''''''''''''''''''

For ease of use, these wrapper methods are also available:

**start_periodic_device_info_requests()**

.. code-block:: python

   await mqtt_client.start_periodic_device_info_requests(
       device: Device,
       period_seconds: float = 300.0
   ) -> None

**start_periodic_device_status_requests()**

.. code-block:: python

   await mqtt_client.start_periodic_device_status_requests(
       device: Device,
       period_seconds: float = 300.0
   ) -> None

**stop_periodic_device_info_requests()**

.. code-block:: python

   await mqtt_client.stop_periodic_device_info_requests(device: Device) -> None

**stop_periodic_device_status_requests()**

.. code-block:: python

   await mqtt_client.stop_periodic_device_status_requests(device: Device) -> None

stop_all_periodic_tasks()
'''''''''''''''''''''''''

.. code-block:: python

   await mqtt_client.stop_all_periodic_tasks() -> None

Stop all periodic request tasks. This is automatically called when
disconnecting.

**Example:**

.. code-block:: python

   await mqtt_client.stop_all_periodic_tasks()

Properties
^^^^^^^^^^

is_connected
''''''''''''

.. code:: python

   mqtt_client.is_connected -> bool

Check if client is connected to AWS IoT.

client_id
'''''''''

.. code:: python

   mqtt_client.client_id -> str

Get the MQTT client ID.

session_id
''''''''''

.. code:: python

   mqtt_client.session_id -> str

Get the current session ID.

MqttConnectionConfig
~~~~~~~~~~~~~~~~~~~~

Configuration for MQTT connection.

.. code:: python

   MqttConnectionConfig(
       endpoint: str = "a1t30mldyslmuq-ats.iot.us-east-1.amazonaws.com",
       region: str = "us-east-1",
       client_id: Optional[str] = None,
       clean_session: bool = True,
       keep_alive_secs: int = 1200
   )

**Parameters:** - ``endpoint``: AWS IoT endpoint - ``region``: AWS
region - ``client_id``: MQTT client ID (auto-generated if not provided)
- ``clean_session``: Start with clean session - ``keep_alive_secs``:
Keep-alive interval

MQTT Topics
-----------

Command Topics
~~~~~~~~~~~~~~

Commands are sent to topics with this structure:

::

   cmd/{device_type}/navilink-{device_id}/{command_suffix}

Examples: - Status request: ``cmd/52/navilink-aabbccddeeff/st`` - Device
info: ``cmd/52/navilink-aabbccddeeff/st/did`` - Control:
``cmd/52/navilink-aabbccddeeff/ctrl``

Response Topics
~~~~~~~~~~~~~~~

Responses are received on topics with this structure:

::

   cmd/{device_type}/navilink-{device_id}/{client_id}/res/{response_suffix}

Use wildcards to subscribe to all responses:

::

   cmd/52/navilink-aabbccddeeff/{client_id}/res/#

Event Topics
~~~~~~~~~~~~

Events are published to:

::

   evt/{device_type}/navilink-{device_id}/{event_type}

Example: - App connection:
``evt/52/navilink-aabbccddeeff/app-connection``

Message Structure
-----------------

Command Message
~~~~~~~~~~~~~~~

.. code:: json

   {
     "clientID": "navien-client-abc123",
     "sessionID": "def456",
     "protocolVersion": 2,
     "request": {
       "command": 16777219,
       "deviceType": 52,
       "macAddress": "aabbccddeeff",
       "additionalValue": "5322",
       "mode": "power-on",
       "param": [],
       "paramStr": ""
     },
     "requestTopic": "cmd/52/navilink-aabbccddeeff/ctrl",
     "responseTopic": "cmd/52/navilink-aabbccddeeff/navien-client-abc123/res"
   }

Response Message
~~~~~~~~~~~~~~~~

.. code:: json

   {
     "sessionID": "def456",
     "response": {
       "status": {
         "dhwTemperature": 120,
         "tankUpperTemperature": 115,
         "tankLowerTemperature": 110,
         "operationMode": 3,
         "dhwUse": true,
         "compUse": false
       }
     }
   }

Error Handling
--------------

.. code:: python

   from nwp500.mqtt_client import NavienMqttClient

   try:
       async with NavienAuthClient("email@example.com", "password") as auth_client:
           mqtt_client = NavienMqttClient(auth_client)
           await mqtt_client.connect()
           
           # Use client...
       
   except ValueError as e:
       print(f"Configuration error: {e}")
   except RuntimeError as e:
       print(f"Connection error: {e}")
   except Exception as e:
       print(f"Unexpected error: {e}")
   finally:
       if mqtt_client.is_connected:
           await mqtt_client.disconnect()

Advanced Usage
--------------

Non-Blocking Implementation
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The MQTT client is designed to be fully compatible with async event loops
and will not block or interfere with other async operations. This makes it
suitable for integration with Home Assistant, web servers, and other 
async applications.

**Implementation Details:**

- All AWS IoT SDK operations that could block are wrapped with ``asyncio.run_in_executor()``
- Connection, disconnection, subscription, and publishing operations are non-blocking
- The client maintains full compatibility with the existing API
- No additional configuration required for non-blocking behavior

**Home Assistant Integration:**

.. code:: python

   # Safe for use in Home Assistant custom integrations
   class MyCoordinator(DataUpdateCoordinator):
       async def _async_update_data(self):
           # This will not trigger "blocking I/O detected" warnings
           await self.mqtt_client.request_device_status(self.device)
           return self.latest_data

**Concurrent Operations:**

.. code:: python

   # MQTT operations will not block other async tasks
   async def main():
       # Both tasks run concurrently without blocking
       await asyncio.gather(
           mqtt_client.connect(),
           some_other_async_operation(),
           web_server.start(),
       )

Custom Connection Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   from nwp500.mqtt_client import MqttConnectionConfig

   config = MqttConnectionConfig(
       client_id="my-custom-client",
       keep_alive_secs=600,
       clean_session=False
   )

   mqtt_client = NavienMqttClient(auth_tokens, config=config)

Connection Callbacks
~~~~~~~~~~~~~~~~~~~~

.. code:: python

   def on_interrupted(error):
       print(f"Connection interrupted: {error}")

   def on_resumed(return_code, session_present):
       print(f"Connection resumed: {return_code}")

   mqtt_client = NavienMqttClient(
       auth_client,
       on_connection_interrupted=on_interrupted,
       on_connection_resumed=on_resumed
   )

Multiple Device Subscriptions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   devices = [device1, device2]

   for device in devices:
       await mqtt_client.subscribe_device(
           device,
           lambda topic, msg: print(f"{device.device_info.mac_address}: {msg}")
       )

Periodic Requests
~~~~~~~~~~~~~~~~~

Automatically request device information or status at regular intervals:

.. code:: python

   from nwp500 import PeriodicRequestType

   # Device status requests (default) - every 5 minutes
   await mqtt_client.start_periodic_requests(device)

   # Device info requests - every 10 minutes
   await mqtt_client.start_periodic_requests(
       device,
       request_type=PeriodicRequestType.DEVICE_INFO,
       period_seconds=600
   )

   # Monitor updates
   def on_message(topic: str, message: dict):
       response = message.get('response', {})
       if 'status' in response:
           print(f"Status: {response['status'].get('dhwTemperature')}°F")
       if 'feature' in response:
           print(f"Firmware: {response['feature'].get('controllerSwVersion')}")

   await mqtt_client.subscribe_device(device, on_message)

   # Keep running...
   await asyncio.sleep(3600)  # Run for 1 hour

   # Stop when done
   await mqtt_client.stop_periodic_requests(device)

**Use Cases:** - Monitor firmware updates automatically - Keep device
status current without manual polling - Detect when devices go
offline/online - Track configuration changes - Automated monitoring
applications

**Multiple Request Types:**

.. code:: python

   # Run both status and info requests simultaneously
   await mqtt_client.start_periodic_requests(
       device,
       request_type=PeriodicRequestType.DEVICE_STATUS,
       period_seconds=300  # Every 5 minutes
   )

   await mqtt_client.start_periodic_requests(
       device,
       request_type=PeriodicRequestType.DEVICE_INFO,
       period_seconds=1800  # Every 30 minutes
   )

   # Stop specific type
   await mqtt_client.stop_periodic_requests(device, PeriodicRequestType.DEVICE_INFO)

   # Stop all types for device
   # Stop all types for device
   await mqtt_client.stop_periodic_requests(device)

**Convenience Methods:**

.. code:: python

   # These are wrappers around start_periodic_requests()
   await mqtt_client.start_periodic_device_info_requests(device)
   await mqtt_client.start_periodic_device_status_requests(device)

Troubleshooting
---------------

Connection Issues
~~~~~~~~~~~~~~~~~

**Problem:** ``AWS_IO_DNS_INVALID_NAME`` error

**Solution:** Verify the endpoint is correct:
``a1t30mldyslmuq-ats.iot.us-east-1.amazonaws.com``

--------------

**Problem:** ``AWS credentials not available``

**Solution:** Ensure authentication returns AWS credentials:

.. code:: python

   async with NavienAuthClient(email, password) as auth_client:
       if not auth_client.current_tokens.access_key_id:
           print("No AWS credentials in response")

No Messages Received
~~~~~~~~~~~~~~~~~~~~

**Problem:** Commands sent but no responses

**Possible causes:** 1. Device is offline 2. Wrong topic subscription 3.
Device object not properly configured

**Solution:**

.. code:: python

   # Correct - use Device object from API
   device = await api_client.get_first_device()
   await mqtt_client.request_device_status(device)

Session Expiration
~~~~~~~~~~~~~~~~~~

AWS credentials expire after a certain time. The auth client
automatically handles token refresh:

.. code:: python

   async with NavienAuthClient("email@example.com", "password") as auth_client:
       
       # Auth client automatically manages token refresh
       mqtt_client = NavienMqttClient(auth_client)
       await mqtt_client.connect()

Examples
--------

See the ``examples/`` directory:

- ``mqtt_client_example.py``: Complete example with device discovery and communication
- ``test_mqtt_connection.py``: Simple connection test

References
----------

- :doc:`MQTT_MESSAGES`: Complete MQTT protocol documentation
- `AWS IoT Device SDK for Python v2 <https://github.com/aws/aws-iot-device-sdk-python-v2>`__
- `OpenAPI Specification <openapi.yaml>`__: REST API specification
