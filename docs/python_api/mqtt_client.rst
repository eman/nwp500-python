============
MQTT Client
============

The ``NavienMqttClient`` is the **primary interface** for real-time communication
with Navien devices. Use this for monitoring status and sending control commands.

.. important::
   **MQTT is the main way to interact with your Navien device.** Use the REST API
   only for device discovery. MQTT provides real-time updates, lower latency,
   bidirectional communication, and event-driven architecture.

Overview
========

The MQTT client provides:

* **Real-Time Monitoring** - Subscribe to device status updates as they happen
* **Device Control** - Send commands (power, temperature, mode)
* **Event System** - React to state changes with callbacks
* **Auto-Reconnection** - Automatic recovery from network issues with exponential backoff
* **Command Queueing** - Commands queued when offline, sent automatically on reconnect
* **Type-Safe** - Returns strongly-typed data models (DeviceStatus, DeviceFeature)
* **Periodic Requests** - Automatic periodic status/info requests
* **Energy Monitoring** - Query and subscribe to energy usage data

All operations are fully asynchronous and non-blocking.

Quick Start
===========

Basic Monitoring
----------------

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient
   import asyncio

   async def main():
       async with NavienAuthClient("email@example.com", "password") as auth:
           # Get device via API
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           
           # Connect MQTT
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Subscribe to status updates
           def on_status(status):
               print(f"Water Temp: {status.dhw_temperature}°F")
               print(f"Target: {status.dhw_temperature_setting}°F")
               print(f"Power: {status.current_inst_power}W")
               print(f"Mode: {status.dhw_operation_setting.name}")
           
           await mqtt.subscribe_device_status(device, on_status)
           await mqtt.request_device_status(device)
           
           # Monitor for 60 seconds
           await asyncio.sleep(60)
           await mqtt.disconnect()

   asyncio.run(main())

Device Control
--------------

.. code-block:: python

   async def control_device():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Control operations
           await mqtt.set_power(device, power_on=True)
           await mqtt.set_dhw_mode(device, mode_id=3)  # Energy Saver
           await mqtt.set_dhw_temperature(device, 140.0)
           
           await mqtt.disconnect()

   asyncio.run(control_device())

API Reference
=============

NavienMqttClient
----------------

.. py:class:: NavienMqttClient(auth_client, config=None)

   MQTT client for real-time device communication via AWS IoT Core.

   :param auth_client: Authenticated NavienAuthClient instance
   :type auth_client: NavienAuthClient
   :param config: Connection configuration (optional)
   :type config: MqttConnectionConfig or None
   :raises ValueError: If auth_client not authenticated or missing AWS credentials

   **Example:**

   .. code-block:: python

      from nwp500 import NavienMqttClient
      from nwp500.mqtt_utils import MqttConnectionConfig

      # Default configuration
      mqtt = NavienMqttClient(auth)
      
      # Custom configuration
      config = MqttConnectionConfig(
          auto_reconnect=True,
          max_reconnect_attempts=15,
          enable_command_queue=True,
          max_queued_commands=100
      )
      mqtt = NavienMqttClient(auth, config=config)
      
      # Register event handlers
      def on_interrupted(error):
          print(f"Connection lost: {error}")
      
      def on_resumed(return_code, session_present):
          print("Connection restored!")
      
      mqtt.on("connection_interrupted", on_interrupted)
      mqtt.on("connection_resumed", on_resumed)

Connection Methods
------------------

connect()
^^^^^^^^^

.. py:method:: connect()

   Connect to AWS IoT Core MQTT broker.

   :return: True if connection successful
   :rtype: bool
   :raises Exception: If connection fails

   **Example:**

   .. code-block:: python

      mqtt = NavienMqttClient(auth)
      
      try:
          connected = await mqtt.connect()
          if connected:
              print(f"Connected! Client ID: {mqtt.client_id}")
          else:
              print("Connection failed")
      except Exception as e:
          print(f"Error connecting: {e}")

disconnect()
^^^^^^^^^^^^

.. py:method:: disconnect()

   Disconnect from MQTT broker and cleanup all resources.

   Stops all periodic tasks, unsubscribes from topics, and closes connection.

   **Example:**

   .. code-block:: python

      try:
          # ... operations ...
      finally:
          await mqtt.disconnect()

Monitoring Methods
------------------

subscribe_device_status()
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: subscribe_device_status(device, callback)

   Subscribe to device status updates with automatic parsing.

   The callback receives DeviceStatus objects with 100+ fields including temperature,
   power consumption, operation mode, and component states.

   :param device: Device object
   :type device: Device
   :param callback: Function receiving DeviceStatus objects
   :type callback: Callable[[DeviceStatus], None]
   :return: Subscription packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      def on_status(status):
          """Called every time device status updates."""
          print(f"Temperature: {status.dhw_temperature}°F")
          print(f"Target: {status.dhw_temperature_setting}°F")
          print(f"Mode: {status.dhw_operation_setting.name}")
          print(f"Power: {status.current_inst_power}W")
          print(f"Energy: {status.available_energy_capacity}%")
          
          # Check if actively heating
          if status.operation_busy:
              print("Device is heating water")
              if status.comp_use:
                  print("  - Heat pump running")
              if status.heat_upper_use:
                  print("  - Upper heater active")
              if status.heat_lower_use:
                  print("  - Lower heater active")
          
          # Check water usage
          if status.dhw_use:
              print("Water is being used (short-term)")
          if status.dhw_use_sustained:
              print("Water is being used (sustained)")
          
          # Check for errors
          if status.error_code != 0:
              print(f"ERROR: {status.error_code}")
      
      await mqtt.subscribe_device_status(device, on_status)
      await mqtt.request_device_status(device)

request_device_status()
^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_device_status(device)

   Request current device status.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      # Subscribe first to receive response
      await mqtt.subscribe_device_status(device, on_status)
      
      # Then request
      await mqtt.request_device_status(device)
      
      # Can request periodically
      while monitoring:
          await mqtt.request_device_status(device)
          await asyncio.sleep(30)  # Every 30 seconds

subscribe_device_feature()
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: subscribe_device_feature(device, callback)

   Subscribe to device feature/capability/info updates.

   The callback receives DeviceFeature objects containing serial number,
   firmware version, temperature limits, and supported features.

   :param device: Device object
   :type device: Device
   :param callback: Function receiving DeviceFeature objects
   :type callback: Callable[[DeviceFeature], None]
   :return: Subscription packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      def on_feature(feature):
          """Called when device features/info received."""
          print(f"Serial: {feature.controller_serial_number}")
          print(f"Firmware: {feature.controller_sw_version}")
          print(f"Temp Range: {feature.dhw_temperature_min}°F - "
                f"{feature.dhw_temperature_max}°F")
          
          # Check capabilities
          if feature.energy_usage_use:
              print("Energy monitoring: Supported")
          if feature.anti_legionella_setting_use:
              print("Anti-Legionella: Supported")
          if feature.reservation_use:
              print("Reservations: Supported")
      
      await mqtt.subscribe_device_feature(device, on_feature)
      await mqtt.request_device_info(device)

request_device_info()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_device_info(device)

   Request device features and capabilities.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      await mqtt.subscribe_device_feature(device, on_feature)
      await mqtt.request_device_info(device)

subscribe_device()
^^^^^^^^^^^^^^^^^^

.. py:method:: subscribe_device(device, callback)

   Subscribe to all messages from a device (low-level).

   This subscribes to both control and status topics, providing raw message access.
   For most use cases, use subscribe_device_status() or subscribe_device_feature() instead.

   :param device: Device object
   :type device: Device
   :param callback: Function receiving (topic, message) tuples
   :type callback: Callable[[str, dict], None]
   :return: List of subscription packet IDs
   :rtype: list[int]

   **Example:**

   .. code-block:: python

      def on_message(topic, message):
          """Receive all messages from device."""
          print(f"Topic: {topic}")
          print(f"Message: {message}")
          
          if 'response' in message:
              response = message['response']
              if 'status' in response:
                  # Device status update
                  status_data = response['status']
              elif 'feature' in response:
                  # Device feature info
                  feature_data = response['feature']
      
      await mqtt.subscribe_device(device, on_message)

Control Methods
---------------

set_power()
^^^^^^^^^^^

.. py:method:: set_power(device, power_on)

   Turn device on or off.

   :param device: Device object
   :type device: Device
   :param power_on: True to turn on, False to turn off
   :type power_on: bool
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      # Turn on
      await mqtt.set_power(device, power_on=True)
      print("Device powered ON")
      
      # Turn off
      await mqtt.set_power(device, power_on=False)
      print("Device powered OFF")

set_dhw_mode()
^^^^^^^^^^^^^^

.. py:method:: set_dhw_mode(device, mode_id, vacation_days=None)

   Set DHW (Domestic Hot Water) operation mode.

   :param device: Device object
   :type device: Device
   :param mode_id: Mode ID (1-5)
   :type mode_id: int
   :param vacation_days: Number of days for vacation mode (required if mode_id=5)
   :type vacation_days: int or None
   :return: Publish packet ID
   :rtype: int

   **Operation Modes:**

   * 1 = Heat Pump Only - Most efficient, uses only heat pump
   * 2 = Electric Only - Fast recovery, uses only electric heaters
   * 3 = Energy Saver - Balanced, recommended for most users
   * 4 = High Demand - Maximum heating capacity
   * 5 = Vacation - Low power mode for extended absence

   **Example:**

   .. code-block:: python

      from nwp500 import DhwOperationSetting
      
      # Set to Heat Pump Only (most efficient)
      await mqtt.set_dhw_mode(device, DhwOperationSetting.HEAT_PUMP.value)
      
      # Set to Energy Saver (balanced, recommended)
      await mqtt.set_dhw_mode(device, DhwOperationSetting.ENERGY_SAVER.value)
      # or just:
      await mqtt.set_dhw_mode(device, 3)
      
      # Set to High Demand (maximum heating)
      await mqtt.set_dhw_mode(device, DhwOperationSetting.HIGH_DEMAND.value)
      
      # Set vacation mode for 7 days
      await mqtt.set_dhw_mode(
          device,
          DhwOperationSetting.VACATION.value,
          vacation_days=7
      )

set_dhw_temperature()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: set_dhw_temperature(device, temperature_f)

   Set target DHW temperature.

   :param device: Device object
   :type device: Device
   :param temperature_f: Temperature in Fahrenheit (95-150°F)
   :type temperature_f: float
   :return: Publish packet ID
   :rtype: int
   :raises RangeValidationError: If temperature is outside 95-150°F range

   The temperature is automatically converted to the device's internal
   format (half-degrees Celsius).

   **Example:**

   .. code-block:: python

      # Set temperature to 140°F
      await mqtt.set_dhw_temperature(device, 140.0)
      
      # Common temperatures
      await mqtt.set_dhw_temperature(device, 120.0)  # Standard
      await mqtt.set_dhw_temperature(device, 130.0)  # Medium
      await mqtt.set_dhw_temperature(device, 140.0)  # Hot
      await mqtt.set_dhw_temperature(device, 150.0)  # Maximum

enable_anti_legionella()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: enable_anti_legionella(device, period_days)

   Enable anti-Legionella protection cycle.

   :param device: Device object
   :type device: Device
   :param period_days: Cycle period in days (typically 7 or 14)
   :type period_days: int
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      # Enable weekly anti-Legionella cycle
      await mqtt.enable_anti_legionella(device, period_days=7)
      
      # Enable bi-weekly cycle
      await mqtt.enable_anti_legionella(device, period_days=14)

disable_anti_legionella()
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: disable_anti_legionella(device)

   Disable anti-Legionella protection.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      await mqtt.disable_anti_legionella(device)

Energy Monitoring Methods
--------------------------

request_energy_usage()
^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_energy_usage(device, year, months)

   Request daily energy usage data for specified period.

   :param device: Device object
   :type device: Device
   :param year: Year to query (e.g., 2024)
   :type year: int
   :param months: List of months to query (1-12)
   :type months: list[int]
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      # Subscribe first
      await mqtt.subscribe_energy_usage(device, on_energy)
      
      # Request current month
      from datetime import datetime
      now = datetime.now()
      await mqtt.request_energy_usage(device, now.year, [now.month])
      
      # Request multiple months
      await mqtt.request_energy_usage(device, 2024, [8, 9, 10])
      
      # Request full year
      await mqtt.request_energy_usage(device, 2024, list(range(1, 13)))

subscribe_energy_usage()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: subscribe_energy_usage(device, callback)

   Subscribe to energy usage query responses.

   :param device: Device object
   :type device: Device
   :param callback: Function receiving EnergyUsageResponse objects
   :type callback: Callable[[EnergyUsageResponse], None]
   :return: Subscription packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      def on_energy(energy):
          """Process energy usage data."""
          print(f"Total Usage: {energy.total.total_usage} Wh")
          print(f"Heat Pump: {energy.total.heat_pump_percentage:.1f}%")
          print(f"Electric: {energy.total.heat_element_percentage:.1f}%")
          
          print("\nDaily Breakdown:")
          for day_data in energy.data:
              print(f"  Date: Day {len(energy.data)}")
              print(f"    Total: {day_data.total_usage} Wh")
              print(f"    HP: {day_data.hpUsage} Wh ({day_data.hpTime}h)")
              print(f"    HE: {day_data.heUsage} Wh ({day_data.heTime}h)")
      
      await mqtt.subscribe_energy_usage(device, on_energy)
      await mqtt.request_energy_usage(device, year=2024, months=[10])

Reservation Methods
-------------------

update_reservations()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: update_reservations(device, enabled, reservations)

   Update device reservation schedule.

   :param device: Device object
   :type device: Device
   :param enabled: Enable/disable reservation schedule
   :type enabled: bool
   :param reservations: List of reservation objects
   :type reservations: list[dict]
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      # Define reservations
      reservations = [
          {
              "startHour": 6,
              "startMinute": 0,
              "endHour": 22,
              "endMinute": 0,
              "weekDays": [1, 1, 1, 1, 1, 0, 0],  # Mon-Fri
              "temperature": 120
          },
          {
              "startHour": 8,
              "startMinute": 0,
              "endHour": 20,
              "endMinute": 0,
              "weekDays": [0, 0, 0, 0, 0, 1, 1],  # Sat-Sun
              "temperature": 130
          }
      ]
      
      # Update schedule
      await mqtt.update_reservations(device, True, reservations)

request_reservations()
^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_reservations(device)

   Request current reservation schedule.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

Time-of-Use Methods
-------------------

set_tou_enabled()
^^^^^^^^^^^^^^^^^

.. py:method:: set_tou_enabled(device, enabled)

   Enable or disable Time-of-Use optimization.

   :param device: Device object
   :type device: Device
   :param enabled: True to enable, False to disable
   :type enabled: bool
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      # Enable TOU
      await mqtt.set_tou_enabled(device, True)
      
      # Disable TOU
      await mqtt.set_tou_enabled(device, False)

Periodic Request Methods
------------------------

start_periodic_requests()
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: start_periodic_requests(device, request_type=DEVICE_STATUS, period_seconds=300.0)

   Start automatic periodic status or info requests.

   :param device: Device object
   :type device: Device
   :param request_type: Type of request (DEVICE_STATUS or DEVICE_INFO)
   :type request_type: PeriodicRequestType
   :param period_seconds: Interval in seconds (default: 300 = 5 minutes)
   :type period_seconds: float

   **Example:**

   .. code-block:: python

      from nwp500.mqtt_utils import PeriodicRequestType
      
      # Subscribe first
      await mqtt.subscribe_device_status(device, on_status)
      
      # Start periodic status requests every 60 seconds
      await mqtt.start_periodic_requests(
          device,
          PeriodicRequestType.DEVICE_STATUS,
          period_seconds=60
      )
      
      # Monitor for extended period
      await asyncio.sleep(3600)  # 1 hour
      
      # Stop when done
      await mqtt.stop_periodic_requests(
          device,
          PeriodicRequestType.DEVICE_STATUS
      )

stop_periodic_requests()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: stop_periodic_requests(device, request_type)

   Stop periodic requests for a device.

   :param device: Device object
   :type device: Device
   :param request_type: Type of request to stop
   :type request_type: PeriodicRequestType

stop_all_periodic_tasks()
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: stop_all_periodic_tasks(device)

   Stop all periodic tasks for a device.

   :param device: Device object
   :type device: Device

Utility Methods
---------------

signal_app_connection()
^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: signal_app_connection(device)

   Signal that an application has connected (recommended at startup).

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      await mqtt.connect()
      await mqtt.signal_app_connection(device)

subscribe(), unsubscribe(), publish()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Low-level MQTT operations (advanced use only).

Properties
----------

is_connected
^^^^^^^^^^^^

.. py:attribute:: is_connected

   Check if currently connected to MQTT broker.

   :type: bool

   **Example:**

   .. code-block:: python

      if mqtt.is_connected:
          await mqtt.set_power(device, True)
      else:
          print("Not connected")

client_id
^^^^^^^^^

.. py:attribute:: client_id

   Get MQTT client ID.

   :type: str

session_id
^^^^^^^^^^

.. py:attribute:: session_id

   Get current session ID.

   :type: str

queued_commands_count
^^^^^^^^^^^^^^^^^^^^^

.. py:attribute:: queued_commands_count

   Get number of queued commands (when offline).

   :type: int

   **Example:**

   .. code-block:: python

      count = mqtt.queued_commands_count
      if count > 0:
          print(f"{count} commands queued (will send on reconnect)")

reconnect_attempts
^^^^^^^^^^^^^^^^^^

.. py:attribute:: reconnect_attempts

   Get current reconnection attempt count.

   :type: int

is_reconnecting
^^^^^^^^^^^^^^^

.. py:attribute:: is_reconnecting

   Check if currently attempting to reconnect.

   :type: bool

Examples
========

Example 1: Complete Monitoring Application
-------------------------------------------

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient
   from datetime import datetime
   import asyncio

   async def monitor_device():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Track state
           last_temp = None
           last_power = None
           
           def on_status(status):
               nonlocal last_temp, last_power
               now = datetime.now().strftime("%H:%M:%S")
               
               # Temperature changed
               if last_temp != status.dhw_temperature:
                   print(f"[{now}] Temperature: {status.dhw_temperature}°F "
                         f"(Target: {status.dhw_temperatureSetting}°F)")
                   last_temp = status.dhw_temperature
               
               # Power changed
               if last_power != status.current_inst_power:
                   print(f"[{now}] Power: {status.current_inst_power}W")
                   last_power = status.current_inst_power
               
               # Heating state
               if status.operation_busy:
                   components = []
                   if status.comp_use:
                       components.append("HP")
                   if status.heat_upper_use:
                       components.append("Upper")
                   if status.heat_lower_use:
                       components.append("Lower")
                   print(f"[{now}] Heating: {', '.join(components)}")
           
           await mqtt.subscribe_device_status(device, on_status)
           await mqtt.request_device_status(device)
           
           # Monitor indefinitely
           try:
               while True:
                   await asyncio.sleep(3600)
           except KeyboardInterrupt:
               print("Stopping...")
           finally:
               await mqtt.disconnect()

   asyncio.run(monitor_device())

Example 2: Automatic Temperature Control
-----------------------------------------

.. code-block:: python

   async def auto_temperature_control():
       \"\"\"Adjust temperature based on usage patterns.\"\"\"
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Track water usage
           last_use_time = None
           
           def on_status(status):
               nonlocal last_use_time
               
               # Water is being used
               if status.dhw_use or status.dhw_use_sustained:
                   last_use_time = datetime.now()
                   
                   # If temp dropped below 130°F, boost to high demand
                   if status.dhw_temperature < 130:
                       asyncio.create_task(
                           mqtt.set_dhw_mode(device, 4)  # High Demand
                       )
               
               # No use for 2 hours, go to energy saver
               elif last_use_time:
                   idle_time = (datetime.now() - last_use_time).seconds
                   if idle_time > 7200:  # 2 hours
                       asyncio.create_task(
                           mqtt.set_dhw_mode(device, 3)  # Energy Saver
                       )
           
           await mqtt.subscribe_device_status(device, on_status)
           await mqtt.start_periodic_requests(device, period_seconds=60)
           
           # Run for extended period
           await asyncio.sleep(86400)  # 24 hours
           await mqtt.disconnect()

   asyncio.run(auto_temperature_control())

Example 3: Multi-Device Monitoring
-----------------------------------

.. code-block:: python

   async def monitor_multiple_devices():
       \"\"\"Monitor multiple devices simultaneously.\"\"\"
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           devices = await api.list_devices()
           
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Create callback for each device
           def create_callback(device_name):
               def callback(status):
                   print(f"[{device_name}] {status.dhw_temperature}°F, "
                         f"{status.current_inst_power}W, "
                         f"{status.dhw_operation_setting.name}")
               return callback
           
           # Subscribe to all devices
           for device in devices:
               callback = create_callback(device.device_info.device_name)
               await mqtt.subscribe_device_status(device, callback)
               await mqtt.request_device_status(device)
           
           # Monitor
           await asyncio.sleep(3600)
           await mqtt.disconnect()

   asyncio.run(monitor_multiple_devices())

Best Practices
==============

1. **Always subscribe before requesting:**

   .. code-block:: python

      # CORRECT order
      await mqtt.subscribe_device_status(device, on_status)
      await mqtt.request_device_status(device)
      
      # WRONG - response will be missed
      await mqtt.request_device_status(device)
      await mqtt.subscribe_device_status(device, on_status)

2. **Use context managers:**

   .. code-block:: python

      async with NavienAuthClient(email, password) as auth:
          mqtt = NavienMqttClient(auth)
          try:
              await mqtt.connect()
              # ... operations ...
          finally:
              await mqtt.disconnect()

3. **Handle connection events:**

   .. code-block:: python

      mqtt = NavienMqttClient(auth)
      
      def on_interrupted(error):
          print(f"Connection lost: {error}")
          # Save state, notify user, etc.
      
      def on_resumed(return_code, session_present):
          print("Connection restored")
          # Re-request status, etc.
      
      mqtt.on("connection_interrupted", on_interrupted)
      mqtt.on("connection_resumed", on_resumed)

4. **Use periodic requests for long-running monitoring:**

   .. code-block:: python

      # Instead of manual loop
      await mqtt.subscribe_device_status(device, on_status)
      await mqtt.start_periodic_requests(device, period_seconds=300)
      
      # Monitor as long as needed
      await asyncio.sleep(86400)  # 24 hours
      
      await mqtt.stop_periodic_requests(device)

5. **Check connection status:**

   .. code-block:: python

      if mqtt.is_connected:
          await mqtt.set_power(device, True)
      else:
          print("Not connected - reconnecting...")
          await mqtt.connect()

Related Documentation
=====================

* :doc:`auth_client` - Authentication client
* :doc:`api_client` - REST API client
* :doc:`models` - Data models (DeviceStatus, DeviceFeature, etc.)
* :doc:`events` - Event system
* :doc:`exceptions` - Exception handling
* :doc:`../protocol/mqtt_protocol` - MQTT protocol details
* :doc:`../guides/energy_monitoring` - Energy monitoring guide
* :doc:`../guides/command_queue` - Command queueing guide
* :doc:`../guides/auto_recovery` - Auto-reconnection guide
