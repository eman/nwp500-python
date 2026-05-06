============
MQTT Client
============

``NavienMqttClient`` is the main interface for real-time communication with
Navien devices — status monitoring, device control, and event callbacks.

.. important::
   Use the REST API only for device discovery. Everything else goes through MQTT.

Overview
========

* **Real-Time Monitoring** - Subscribe to device status updates
* **Device Control** - Send commands (power, temperature, mode)
* **Event System** - React to state changes with callbacks
* **Auto-Reconnection** - Exponential backoff reconnection with command queueing
* **Type-Safe** - Returns typed models (DeviceStatus, DeviceFeature)
* **Periodic Requests** - Scheduled status polling
* **Energy Monitoring** - Query historical energy usage data

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
               unit = status.get_field_unit('dhw_temperature')
               print(f"Water Temp: {status.dhw_temperature}{unit}")
               print(f"Target: {status.dhw_temperature_setting}{unit}")
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

Control operations are now exposed directly on :class:`NavienMqttClient`; use
the direct ``mqtt.*`` methods for control operations.

Control methods rely on cached device feature data for capability-aware
validation. Request device info first, or call
:meth:`nwp500.mqtt.client.NavienMqttClient.ensure_device_info_cached` before issuing commands.

.. code-block:: python

   async def control_device():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           await mqtt.subscribe_device_feature(device, lambda f: None)
           await mqtt.request_device_info(device)

           await mqtt.set_power(device, power_on=True)
           await mqtt.set_dhw_mode(device, mode_id=3)
           await mqtt.set_dhw_temperature(device, 140.0)

           await mqtt.disconnect()

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
      def on_interrupted(event):
          print(f"Connection lost: {event.error}")
      
      def on_resumed(event):
          print(f"Connection restored! session_present={event.session_present}")
      
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

   The callback receives :class:`~nwp500.models.DeviceStatus` objects containing
   temperature, power, operation mode, component states, and more.

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
          print(f"Energy: {status.dhw_charge_per}%")
          
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

Capability Checking
^^^^^^^^^^^^^^^^^^^

Most control commands depend on device capabilities reported by
:class:`~nwp500.models.DeviceFeature`. Request device info first so the client
can validate support and ranges before sending commands.

.. code-block:: python

   await mqtt.subscribe_device_feature(device, lambda feature: print(feature))
   await mqtt.request_device_info(device)

   # Alternative helper: request and wait until the cache is populated
   await mqtt.ensure_device_info_cached(device)

Common capability flags include ``power_use``, ``dhw_use``,
``dhw_temperature_setting_use``, ``program_reservation_use``,
``recirculation_use``, ``recirc_reservation_use``, ``freeze_protection_use``,
and ``smart_diagnostic_use``.

set_power()
^^^^^^^^^^^

.. py:method:: set_power(device, power_on)

   Turn device power on or off.

   **Capability Required:** ``power_use``

   :param device: Device object
   :type device: Device
   :param power_on: ``True`` to power on, ``False`` to power off
   :type power_on: bool
   :return: Publish packet ID
   :rtype: int

set_dhw_mode()
^^^^^^^^^^^^^^

.. py:method:: set_dhw_mode(device, mode_id, vacation_days=None)

   Set the DHW operating mode.

   **Capability Required:** ``dhw_use``

   :param mode_id: One of the DHW operation mode IDs
   :type mode_id: int
   :param vacation_days: Required for vacation mode; valid range ``1``-``30``
   :type vacation_days: int or None
   :raises ParameterValidationError: If vacation mode is missing ``vacation_days``
   :raises RangeValidationError: If ``vacation_days`` is outside ``1``-``30``

set_dhw_temperature()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: set_dhw_temperature(device, temperature)

   Set the target water temperature in the current unit system.

   **Capability Required:** ``dhw_temperature_setting_use``

   The valid range is checked against the device's reported
   ``dhw_temperature_min`` and ``dhw_temperature_max`` values.

enable_anti_legionella()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: enable_anti_legionella(device, period_days)

   Enable the anti-Legionella cycle.

   **Capability Required:** ``anti_legionella_setting_use``

   :param period_days: Cycle period in days (``1``-``30``)
   :type period_days: int

disable_anti_legionella()
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: disable_anti_legionella(device)

   Disable the anti-Legionella cycle.

set_vacation_days()
^^^^^^^^^^^^^^^^^^^

.. py:method:: set_vacation_days(device, days)

   Convenience wrapper for vacation mode.

   **Capability Required:** ``holiday_use``

update_reservations()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: update_reservations(device, reservations, *, enabled=True)

   Update the standard reservation program.

   :param reservations: Sequence of raw reservation entries using the protocol
      fields ``enable``, ``week``, ``hour``, ``min``, ``mode``, and ``param``
   :type reservations: Sequence[dict[str, Any]]
   :param enabled: Global reservation enable flag
   :type enabled: bool

   **Example:**

   .. code-block:: python

      from nwp500 import build_reservation_entry

      reservations = [
          build_reservation_entry(
              enabled=True,
              days=["MO", "TU", "WE", "TH", "FR"],
              hour=6,
              minute=0,
              mode_id=4,
              temperature=60.0,
          )
      ]

      await mqtt.update_reservations(device, reservations, enabled=True)

request_reservations()
^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_reservations(device)

   Request the current programmed reservations.

subscribe_reservation_response()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: subscribe_reservation_response(device, callback)

   Subscribe to parsed reservation read responses.

   :param callback: Called with :class:`~nwp500.models.ReservationSchedule`
   :type callback: Callable[[ReservationSchedule], None]

update_weekly_reservation()
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: update_weekly_reservation(device, schedule)

   Send a typed weekly reservation schedule.

   **Capability Required:** ``program_reservation_use``

   :param schedule: Weekly reservation schedule payload
   :type schedule: WeeklyReservationSchedule

subscribe_weekly_reservation_response()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: subscribe_weekly_reservation_response(device, callback)

   Subscribe to parsed weekly reservation responses.

   :param callback: Called with :class:`~nwp500.models.WeeklyReservationSchedule`
   :type callback: Callable[[WeeklyReservationSchedule], None]

configure_reservation_water_program()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: configure_reservation_water_program(device)

   Enable the device's reservation water-program mode.

   **Capability Required:** ``program_reservation_use``

configure_recirculation_schedule()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: configure_recirculation_schedule(device, schedule)

   Configure the timed recirculation schedule.

   **Capability Required:** ``recirc_reservation_use``

   :param schedule: Recirculation schedule payload
   :type schedule: RecirculationSchedule

subscribe_recirculation_schedule_response()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: subscribe_recirculation_schedule_response(device, callback)

   Subscribe to parsed recirculation schedule responses.

   :param callback: Called with :class:`~nwp500.models.RecirculationSchedule`
   :type callback: Callable[[RecirculationSchedule], None]

set_recirculation_mode()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: set_recirculation_mode(device, mode)

   Set the recirculation operating mode.

   **Capability Required:** ``recirculation_use``

   :param mode: Mode ID in the range ``1``-``4``
   :type mode: int

trigger_recirculation_hot_button()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: trigger_recirculation_hot_button(device)

   Trigger an immediate recirculation run.

   **Capability Required:** ``recirculation_use``

configure_tou_schedule()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: configure_tou_schedule(device, controller_serial_number, periods, *, enabled=True)

   Configure the Time-of-Use schedule.

   **Capability Required:** ``program_reservation_use``

request_tou_settings()
^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_tou_settings(device, controller_serial_number)

   Request the current TOU schedule.

set_tou_enabled()
^^^^^^^^^^^^^^^^^

.. py:method:: set_tou_enabled(device, enabled)

   Enable or disable TOU optimization.

   **Capability Required:** ``program_reservation_use``

request_energy_usage()
^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_energy_usage(device, year, months)

   Request daily energy usage data for one or more months.

subscribe_energy_usage()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: subscribe_energy_usage(device, callback)

   Subscribe to parsed energy usage responses.

   :param callback: Called with :class:`~nwp500.models.EnergyUsageResponse`
   :type callback: Callable[[EnergyUsageResponse], None]

check_firmware_update()
^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: check_firmware_update(device)

   Trigger an OTA firmware availability check. The response arrives
   asynchronously on the device's MQTT response topic.

commit_firmware_update()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: commit_firmware_update(device, payload)

   Commit a previously downloaded firmware update.

   :param payload: OTA commit payload identifying the component and version
   :type payload: OtaCommitPayload

   .. warning::

      The device reboots when a firmware commit is applied.

reconnect_wifi()
^^^^^^^^^^^^^^^^

.. py:method:: reconnect_wifi(device)

   Ask the device to reconnect to WiFi using its current configuration.

reset_wifi()
^^^^^^^^^^^^

.. py:method:: reset_wifi(device)

   Clear the stored WiFi configuration.

   .. warning::

      After ``reset_wifi()``, the device must be provisioned again.

set_freeze_protection_temperature()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: set_freeze_protection_temperature(device, temperature)

   Set the freeze-protection threshold in the current unit system.

   Available on devices that expose ``freeze_protection_use``.

run_smart_diagnostic()
^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: run_smart_diagnostic(device)

   Trigger the device's smart diagnostic routine.

   Available on devices that expose ``smart_diagnostic_use``.

   The result appears in the next ``DeviceStatus.smart_diagnostic`` update.

enable_intelligent_scheduling()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: enable_intelligent_scheduling(device)

   Enable adaptive/intelligent scheduling mode.

disable_intelligent_scheduling()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: disable_intelligent_scheduling(device)

   Disable adaptive/intelligent scheduling mode.

enable_demand_response()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: enable_demand_response(device)

   Enable utility demand-response participation.

disable_demand_response()
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: disable_demand_response(device)

   Disable utility demand-response participation.

reset_air_filter()
^^^^^^^^^^^^^^^^^^

.. py:method:: reset_air_filter(device)

   Reset the air-filter maintenance timer.

signal_app_connection()
^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: signal_app_connection(device)

   Publish an app-connection heartbeat event to the device.

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
                         f"(Target: {status.dhw_temperature_setting}°F)")
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

Subscribe before requesting
----------------------------

The device responds on a topic you must already be listening to:

.. code-block:: python

   # correct
   await mqtt.subscribe_device_status(device, on_status)
   await mqtt.request_device_status(device)

   # wrong — response arrives before subscription
   await mqtt.request_device_status(device)
   await mqtt.subscribe_device_status(device, on_status)

Use context managers
---------------------

.. code-block:: python

   async with NavienAuthClient(email, password) as auth:
       mqtt = NavienMqttClient(auth)
       try:
           await mqtt.connect()
           # ... operations ...
       finally:
           await mqtt.disconnect()

Handle connection events
------------------------

.. code-block:: python

   def on_interrupted(event):
       print(f"Connection lost: {event.error}")

   def on_resumed(event):
       print(f"Connection restored (session_present={event.session_present})")

   mqtt.on("connection_interrupted", on_interrupted)
   mqtt.on("connection_resumed", on_resumed)

Periodic requests for long-running monitoring
----------------------------------------------

.. code-block:: python

   await mqtt.subscribe_device_status(device, on_status)
   await mqtt.start_periodic_requests(device, period_seconds=300)
   await asyncio.sleep(86400)
   await mqtt.stop_periodic_requests(device)

Related Documentation
=====================

* :doc:`auth_client` - Authentication client
* :doc:`api_client` - REST API client
* :doc:`models` - Data models (DeviceStatus, DeviceFeature, etc.)
* :doc:`events` - Event system
* :doc:`exceptions` - Exception handling
* :doc:`../protocol/mqtt_protocol` - MQTT protocol details
* :doc:`../guides/energy_monitoring` - Energy monitoring guide
* :doc:`../guides/scheduling` - Scheduling, recirculation, and intelligent modes
* :doc:`../guides/device_maintenance` - OTA, WiFi, freeze protection, and diagnostics
* :doc:`../guides/command_queue` - Command queueing guide
* :doc:`../guides/auto_recovery` - Auto-reconnection guide
