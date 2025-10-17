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

   # Set DHW mode (1=Heat Pump Only, 2=Electric Only, 3=Energy Saver, 4=High Demand, 5=Vacation)
   await mqtt_client.set_dhw_mode(device, mode_id=3)

   # Set vacation mode with duration
   await mqtt_client.set_dhw_mode(device, mode_id=5, vacation_days=7)

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

Complete MQTT API Reference
''''''''''''''''''''''''''''

This section provides a comprehensive reference of all available MQTT client methods for requesting data and controlling devices.

**Request Methods & Corresponding Subscriptions**

+------------------------------------+---------------------------------------+----------------------------------------+
| Request Method                     | Subscribe Method                      | Response Type                          |
+====================================+=======================================+========================================+
| ``request_device_status()``        | ``subscribe_device_status()``         | ``DeviceStatus`` object                |
+------------------------------------+---------------------------------------+----------------------------------------+
| ``request_device_info()``          | ``subscribe_device_feature()``        | ``DeviceFeature`` object               |
+------------------------------------+---------------------------------------+----------------------------------------+
| ``request_energy_usage()``         | ``subscribe_energy_usage()``          | ``EnergyUsageResponse`` object         |
+------------------------------------+---------------------------------------+----------------------------------------+
| ``set_power()``                    | ``subscribe_device_status()``         | Updated ``DeviceStatus``               |
+------------------------------------+---------------------------------------+----------------------------------------+
| ``set_dhw_mode()``                 | ``subscribe_device_status()``         | Updated ``DeviceStatus``               |
+------------------------------------+---------------------------------------+----------------------------------------+
| ``set_dhw_temperature()``          | ``subscribe_device_status()``         | Updated ``DeviceStatus``               |
+------------------------------------+---------------------------------------+----------------------------------------+
| ``set_dhw_temperature_display()``  | ``subscribe_device_status()``         | Updated ``DeviceStatus``               |
+------------------------------------+---------------------------------------+----------------------------------------+

**Generic Subscriptions**

+------------------------------------+---------------------------------------+----------------------------------------+
| Method                             | Purpose                               | Response Type                          |
+====================================+=======================================+========================================+
| ``subscribe_device()``             | Subscribe to all device messages      | Raw ``dict`` (all message types)       |
+------------------------------------+---------------------------------------+----------------------------------------+
| ``subscribe()``                    | Subscribe to any MQTT topic           | Raw ``dict``                           |
+------------------------------------+---------------------------------------+----------------------------------------+

request_device_status()
'''''''''''''''''''''''

.. code:: python

   await mqtt_client.request_device_status(device: Device) -> int

Request current device status including temperatures, operation mode, power consumption, and error codes.

**Command:** ``16777219``

**Topic:** ``cmd/{device_type}/navilink-{device_id}/st``

**Response:** Subscribe with ``subscribe_device_status()`` to receive ``DeviceStatus`` objects

**Example:**

.. code:: python

   def on_status(status: DeviceStatus):
       print(f"Water Temp: {status.dhwTemperature}°F")
       print(f"Mode: {status.operationMode}")
       print(f"Power: {status.currentInstPower}W")
   
   await mqtt_client.subscribe_device_status(device, on_status)
   await mqtt_client.request_device_status(device)

request_device_info()
'''''''''''''''''''''

.. code:: python

   await mqtt_client.request_device_info(device: Device) -> int

Request device information including firmware version, serial number, temperature limits, and capabilities.

**Command:** ``16777217``

**Topic:** ``cmd/{device_type}/navilink-{device_id}/st/did``

**Response:** Subscribe with ``subscribe_device_feature()`` to receive ``DeviceFeature`` objects

**Example:**

.. code:: python

   def on_feature(feature: DeviceFeature):
       print(f"Firmware: {feature.controllerSwVersion}")
       print(f"Serial: {feature.controllerSerialNumber}")
       print(f"Temp Range: {feature.dhwTemperatureMin}-{feature.dhwTemperatureMax}°F")
   
   await mqtt_client.subscribe_device_feature(device, on_feature)
   await mqtt_client.request_device_info(device)

request_energy_usage()
''''''''''''''''''''''

.. code:: python

   await mqtt_client.request_energy_usage(device: Device, year: int, months: list[int]) -> int

Request historical daily energy usage data for specified month(s). Returns heat pump and electric heating element consumption with daily breakdown.

**Command:** ``16777225``

**Topic:** ``cmd/{device_type}/navilink-{device_id}/st/energy-usage-daily-query/rd``

**Response:** Subscribe with ``subscribe_energy_usage()`` to receive ``EnergyUsageResponse`` objects

**Parameters:**

- ``year``: Year to query (e.g., 2025)
- ``months``: List of months to query (1-12). Can request multiple months.

**Example:**

.. code:: python

   def on_energy(energy: EnergyUsageResponse):
       print(f"Total Usage: {energy.total.total_usage} Wh")
       print(f"Heat Pump: {energy.total.heat_pump_percentage:.1f}%")
       for day in energy.daily:
           print(f"Day {day.day}: {day.total_usage} Wh")
   
   await mqtt_client.subscribe_energy_usage(device, on_energy)
   await mqtt_client.request_energy_usage(device, year=2025, months=[9])

set_power()
'''''''''''

.. code:: python

   await mqtt_client.set_power(device: Device, power_on: bool) -> int

Turn device on or off.

**Command:** ``33554433``

**Mode:** ``power-on`` or ``power-off``

**Response:** Device status is updated; subscribe with ``subscribe_device_status()`` to see changes

set_dhw_mode()
''''''''''''''

.. code:: python

   await mqtt_client.set_dhw_mode(device: Device, mode_id: int) -> int

Set DHW (Domestic Hot Water) operation mode. This sets the ``dhwOperationSetting`` field, which determines what heating mode the device will use when it needs to heat water.

**Command:** ``33554433``

**Mode:** ``dhw-mode``

**Mode IDs (command values):**

* ``1``: Heat Pump Only (most efficient, longest recovery)
* ``2``: Electric Only (least efficient, fastest recovery)  
* ``3``: Energy Saver (default, balanced - Hybrid: Efficiency)
* ``4``: High Demand (faster recovery - Hybrid: Boost)
* ``5``: Vacation (suspend heating for 0-99 days)

**Response:** Device status is updated; subscribe with ``subscribe_device_status()`` to see changes

**Important:** Setting the mode updates ``dhwOperationSetting`` but does not immediately change ``operationMode``. The ``operationMode`` field reflects the device's current operational state and changes automatically when the device starts/stops heating. See :doc:`DEVICE_STATUS_FIELDS` for details on the relationship between these fields.

set_dhw_temperature()
'''''''''''''''''''''

.. code:: python

   await mqtt_client.set_dhw_temperature(device: Device, temperature: int) -> int

Set DHW target temperature using the **MESSAGE value** (20°F lower than display).

**Command:** ``33554433``

**Mode:** ``dhw-temperature``

**Parameters:** 

- ``temperature``: Target temperature in Fahrenheit (message value, not display value)

**Response:** Device status is updated; subscribe with ``subscribe_device_status()`` to see changes

**Important:** The temperature in the message is 20°F lower than what displays on the device/app:

- Message value 120°F → Display shows 140°F
- Message value 130°F → Display shows 150°F

set_dhw_temperature_display()
''''''''''''''''''''''''''''''

.. code:: python

   await mqtt_client.set_dhw_temperature_display(device: Device, display_temperature: int) -> int

Set DHW target temperature using the **DISPLAY value** (what you see on device/app). This is a convenience method that automatically converts display temperature to message value.

**Parameters:**

- ``display_temperature``: Target temperature as shown on display/app (Fahrenheit)

**Response:** Device status is updated; subscribe with ``subscribe_device_status()`` to see changes

**Example:**

.. code:: python

   # Set display temperature to 140°F (sends 120°F in message)
   await mqtt_client.set_dhw_temperature_display(device, 140)

signal_app_connection()
'''''''''''''''''''''''

.. code:: python

   await mqtt_client.signal_app_connection(device: Device) -> int

Signal that the app has connected.

**Topic:** ``evt/{device_type}/navilink-{device_id}/app-connection``

Subscription Methods
''''''''''''''''''''

subscribe_device_status()
.........................

.. code:: python

   await mqtt_client.subscribe_device_status(
       device: Device,
       callback: Callable[[DeviceStatus], None]
   ) -> int

Subscribe to device status messages with automatic parsing into ``DeviceStatus`` objects. Use this after calling ``request_device_status()`` or any control commands to receive updates.

**Emits Events:**

- ``status_received``: Every status update (DeviceStatus)
- ``temperature_changed``: Temperature changed (old_temp, new_temp)
- ``mode_changed``: Operation mode changed (old_mode, new_mode)
- ``power_changed``: Power consumption changed (old_power, new_power)
- ``heating_started``: Device started heating (status)
- ``heating_stopped``: Device stopped heating (status)
- ``error_detected``: Error code detected (error_code, status)
- ``error_cleared``: Error code cleared (error_code)

subscribe_device_feature()
..........................

.. code:: python

   await mqtt_client.subscribe_device_feature(
       device: Device,
       callback: Callable[[DeviceFeature], None]
   ) -> int

Subscribe to device feature/info messages with automatic parsing into ``DeviceFeature`` objects. Use this after calling ``request_device_info()`` to receive device capabilities and firmware info.

**Emits Events:**

- ``feature_received``: Feature/info received (DeviceFeature)

subscribe_energy_usage()
........................

.. code:: python

   await mqtt_client.subscribe_energy_usage(
       device: Device,
       callback: Callable[[EnergyUsageResponse], None]
   ) -> int

Subscribe to energy usage query responses with automatic parsing into ``EnergyUsageResponse`` objects. Use this after calling ``request_energy_usage()`` to receive historical energy data.

subscribe_device()
..................

.. code:: python

   await mqtt_client.subscribe_device(
       device: Device,
       callback: Callable[[str, dict], None]
   ) -> int

Subscribe to all messages from a device (no parsing). Receives all message types as raw dictionaries. Use the specific subscription methods above for automatic parsing.

subscribe()
...........

.. code:: python

   await mqtt_client.subscribe(
       topic: str,
       callback: Callable[[str, dict], None],
       qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE
   ) -> int

Subscribe to any MQTT topic. Supports wildcards (``#``, ``+``). Receives raw dictionary messages.

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
         "operationMode": 64,
         "dhwOperationSetting": 3,
         "dhwUse": true,
         "compUse": false
       }
     }
   }

Note: ``operationMode`` shows the current operational state (64 = Energy Saver actively heating), while ``dhwOperationSetting`` shows the configured mode preference (3 = Energy Saver). See :doc:`DEVICE_STATUS_FIELDS` for the distinction between these fields.

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

- AWS IoT SDK operations return ``concurrent.futures.Future`` objects that are converted to asyncio Futures using ``asyncio.wrap_future()``
- Connection, disconnection, subscription, and publishing operations are fully non-blocking
- No thread pool resources are used for MQTT operations (more efficient than executor-based approaches)
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

Advanced Features
-----------------

Vacation Mode
~~~~~~~~~~~~~

Set the device to vacation mode to save energy during extended absences:

.. code:: python

   # Set vacation mode for 7 days
   await mqtt_client.set_dhw_mode(device, mode_id=5, vacation_days=7)
   
   # Check vacation status in device status
   def on_status(topic: str, message: dict):
       status = message.get('response', {}).get('status', {})
       if status.get('dhwOperationSetting') == 5:
           days_set = status.get('vacationDaySetting', 0)
           days_elapsed = status.get('vacationDayElapsed', 0)
           days_remaining = days_set - days_elapsed
           print(f"Vacation mode: {days_remaining} days remaining")
   
   await mqtt_client.subscribe_device(device, on_status)
   await mqtt_client.request_device_status(device)

Reservation Management
~~~~~~~~~~~~~~~~~~~~~~

Manage programmed temperature and mode changes:

.. code:: python

   # Create a reservation for weekday mornings
   reservation = {
       "enable": 1,  # 1=enabled, 2=disabled
       "week": 124,  # Weekdays (Mon-Fri)
       "hour": 6,
       "min": 30,
       "mode": 4,  # High Demand mode
       "param": 120  # Target temperature (140°F display = 120°F message)
   }
   
   # Send reservation update
   await mqtt_client.publish(
       topic=f"cmd/52/{device.device_info.mac_address}/ctrl/rsv/rd",
       payload={
           "clientID": mqtt_client.client_id,
           "protocolVersion": 2,
           "request": {
               "command": 16777226,
               "deviceType": 52,
               "macAddress": device.device_info.mac_address,
               "reservationUse": 1,  # Enable reservations
               "reservation": [reservation]
           },
           "requestTopic": f"cmd/52/{device.device_info.mac_address}/ctrl/rsv/rd",
           "responseTopic": "...",
           "sessionID": str(int(time.time() * 1000))
       }
   )

**Week Bitfield Values:**

* ``127`` - All days (Sunday through Saturday)
* ``62`` - Weekdays (Monday through Friday)
* ``65`` - Weekend (Saturday and Sunday)
* ``31`` - Sunday through Thursday

Time of Use (TOU) Pricing
~~~~~~~~~~~~~~~~~~~~~~~~~~

Configure energy pricing schedules for demand response:

.. code:: python

   # Define TOU periods
   tou_periods = [
       {
           "season": 31,  # All seasons
           "week": 124,   # Weekdays
           "startHour": 0,
           "startMinute": 0,
           "endHour": 14,
           "endMinute": 59,
           "priceMin": 34831,  # $0.34831 per kWh
           "priceMax": 34831,
           "decimalPoint": 5  # Divide by 100000
       },
       {
           "season": 31,
           "week": 124,
           "startHour": 15,
           "startMinute": 0,
           "endHour": 20,
           "endMinute": 59,
           "priceMin": 45000,  # $0.45 per kWh (peak pricing)
           "priceMax": 45000,
           "decimalPoint": 5
       }
   ]
   
   # Send TOU settings
   await mqtt_client.publish(
       topic=f"cmd/52/{device.device_info.mac_address}/ctrl/tou/rd",
       payload={
           "clientID": mqtt_client.client_id,
           "protocolVersion": 2,
           "request": {
               "command": 33554439,
               "deviceType": 52,
               "macAddress": device.device_info.mac_address,
               "controllerSerialNumber": device.controller_serial_number,
               "reservationUse": 2,  # Enable TOU
               "reservation": tou_periods
           },
           "requestTopic": f"cmd/52/{device.device_info.mac_address}/ctrl/tou/rd",
           "responseTopic": "...",
           "sessionID": str(int(time.time() * 1000))
       }
   )

**Note:** TOU settings help the device optimize operation based on energy prices, potentially reducing costs during peak pricing periods.

Anti-Legionella Monitoring
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Monitor the Anti-Legionella protection cycle that prevents bacterial growth:

.. code:: python

   # Check Anti-Legionella status
   def on_status(topic: str, message: dict):
       status = message.get('response', {}).get('status', {})
       
       # Check if feature is enabled
       anti_legionella_enabled = status.get('antiLegionellaUse') == 2
       
       # Get cycle period in days
       period_days = status.get('antiLegionellaPeriod', 0)
       
       # Check if currently running
       is_running = status.get('antiLegionellaOperationBusy') == 2
       
       print(f"Anti-Legionella: {'Enabled' if anti_legionella_enabled else 'Disabled'}")
       print(f"Cycle Period: Every {period_days} days")
       print(f"Status: {'Running' if is_running else 'Idle'}")
       
       if is_running:
           print("Device is heating to 140°F for bacterial disinfection")
   
   await mqtt_client.subscribe_device(device, on_status)
   await mqtt_client.request_device_status(device)

**Controlling Anti-Legionella:**

.. code:: python

   import time
   
   # Enable Anti-Legionella with 7-day cycle
   await mqtt_client.publish(
       topic=f"cmd/52/{device.device_info.mac_address}/ctrl",
       payload={
           "clientID": mqtt_client.client_id,
           "protocolVersion": 2,
           "request": {
               "command": 33554472,
               "deviceType": 52,
               "macAddress": device.device_info.mac_address,
               "mode": "anti-leg-on",
               "param": [7],  # 7-day cycle period
               "paramStr": ""
           },
           "requestTopic": f"cmd/52/{device.device_info.mac_address}/ctrl",
           "responseTopic": "...",
           "sessionID": str(int(time.time() * 1000))
       }
   )
   
   # Disable Anti-Legionella (not recommended - health risk)
   await mqtt_client.publish(
       topic=f"cmd/52/{device.device_info.mac_address}/ctrl",
       payload={
           "clientID": mqtt_client.client_id,
           "protocolVersion": 2,
           "request": {
               "command": 33554473,
               "deviceType": 52,
               "macAddress": device.device_info.mac_address,
               "mode": "anti-leg-off",
               "param": [],
               "paramStr": ""
           },
           "requestTopic": f"cmd/52/{device.device_info.mac_address}/ctrl",
           "responseTopic": "...",
           "sessionID": str(int(time.time() * 1000))
       }
   )

**Important Safety Notes:**

* Anti-Legionella heats water to 140°F (60°C) to kill Legionella bacteria
* Requires a mixing valve to prevent scalding at taps
* Cycle period is typically 7 days but can be configured for 1-30 days
* During the cycle, the device will heat the entire tank to the disinfection temperature
* This is a health safety feature recommended for all water heaters
* **WARNING**: Disabling Anti-Legionella increases health risks - consult local codes

TOU Quick Enable/Disable
~~~~~~~~~~~~~~~~~~~~~~~~~

Toggle TOU functionality without modifying the schedule:

.. code:: python

   import time
   
   # Enable TOU
   await mqtt_client.publish(
       topic=f"cmd/52/{device.device_info.mac_address}/ctrl",
       payload={
           "clientID": mqtt_client.client_id,
           "protocolVersion": 2,
           "request": {
               "command": 33554476,
               "deviceType": 52,
               "macAddress": device.device_info.mac_address,
               "mode": "tou-on",
               "param": [],
               "paramStr": ""
           },
           "requestTopic": f"cmd/52/{device.device_info.mac_address}/ctrl",
           "responseTopic": "...",
           "sessionID": str(int(time.time() * 1000))
       }
   )
   
   # Disable TOU
   await mqtt_client.publish(
       topic=f"cmd/52/{device.device_info.mac_address}/ctrl",
       payload={
           "clientID": mqtt_client.client_id,
           "protocolVersion": 2,
           "request": {
               "command": 33554475,
               "deviceType": 52,
               "macAddress": device.device_info.mac_address,
               "mode": "tou-off",
               "param": [],
               "paramStr": ""
           },
           "requestTopic": f"cmd/52/{device.device_info.mac_address}/ctrl",
           "responseTopic": "...",
           "sessionID": str(int(time.time() * 1000))
       }
   )

**Note:** The TOU schedule remains stored when disabled and will resume when re-enabled.

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
