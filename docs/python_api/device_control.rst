===========================
Device Control and Commands
===========================

The ``MqttDeviceController`` manages all device control operations including status requests,
mode changes, temperature control, scheduling, and energy queries.

Overview
========

The device controller provides:

* **Status & Info Requests** - Request device status and feature information
* **Power Control** - Turn device on/off
* **Mode Management** - Change DHW operation modes
* **Temperature Control** - Set target water temperature
* **Anti-Legionella** - Enable/disable disinfection cycles
* **Scheduling** - Configure reservations and time-of-use pricing
* **Energy Monitoring** - Query historical energy usage
* **Recirculation** - Control hot water recirculation pump
* **Demand Response** - Participate in utility demand response
* **Capability Checking** - Validate device features before commanding
* **Automatic Capability Checking** - Decorator-based validation with automatic device info requests

All control methods are fully asynchronous and require device capability information
to be cached before execution.

Quick Start
===========

Basic Control
-------------

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient
   import asyncio

   async def control_device():
       async with NavienAuthClient("email@example.com", "password") as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Request device info to populate capability cache
           await mqtt.subscribe_device_feature(device, lambda f: None)
           await mqtt.control.request_device_info(device)
           
           # Now control operations work with automatic capability checking
           await mqtt.control.set_power(device, power_on=True)
           await mqtt.control.set_dhw_mode(device, mode_id=3)  # Energy Saver
           await mqtt.control.set_dhw_temperature(device, 140.0)
           
           await mqtt.disconnect()

   asyncio.run(control_device())

Capability Checking
-------------------

Before executing control commands, check device capabilities:

.. code-block:: python

   from nwp500 import NavienMqttClient, DeviceCapabilityError

   async def safe_control():
       mqtt = NavienMqttClient(auth)
       await mqtt.connect()
       
       # Request device info first
       await mqtt.subscribe_device_feature(device, on_feature)
       await mqtt.control.request_device_info(device)
       
       # Wait for device info to be cached, then control
       try:
           # Control commands automatically check capabilities via decorator
           msg_id = await mqtt.control.set_recirculation_mode(device, 1)
           print(f"Command sent with ID {msg_id}")
       except DeviceCapabilityError as e:
           print(f"Device doesn't support: {e}")

API Reference
=============

MqttDeviceController
--------------------

The ``NavienMqttClient`` includes a built-in device controller for all operations.

Status and Info Methods
-----------------------

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

      await mqtt.subscribe_device_status(device, on_status)
      await mqtt.control.request_device_status(device)

request_device_info()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_device_info(device)

   Request device features and capabilities.

   This populates the device info cache used for capability checking in control commands.
   Always call this before using control commands.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      await mqtt.subscribe_device_feature(device, on_feature)
      await mqtt.control.request_device_info(device)

Power Control
--------------

set_power()
^^^^^^^^^^^

.. py:method:: set_power(device, power_on)

   Turn device on or off.

   **Capability Required:** ``power_use`` - Must be present in device features

   :param device: Device object
   :type device: Device
   :param power_on: True to turn on, False to turn off
   :type power_on: bool
   :return: Publish packet ID
   :rtype: int
   :raises DeviceCapabilityError: If device doesn't support power control

   **Example:**

   .. code-block:: python

      # Turn on
      await mqtt.control.set_power(device, power_on=True)
      
      # Turn off
      await mqtt.control.set_power(device, power_on=False)

DHW Mode Control
-----------------

set_dhw_mode()
^^^^^^^^^^^^^^

.. py:method:: set_dhw_mode(device, mode_id, vacation_days=None)

   Set DHW (Domestic Hot Water) operation mode.

   **Capability Required:** ``dhw_use`` - Must be present in device features

   :param device: Device object
   :type device: Device
   :param mode_id: Mode ID (1-5)
   :type mode_id: int
   :param vacation_days: Number of days for vacation mode (required if mode_id=5, 1-30)
   :type vacation_days: int or None
   :return: Publish packet ID
   :rtype: int
   :raises ParameterValidationError: If vacation_days invalid for non-vacation modes
   :raises RangeValidationError: If vacation_days not in 1-30 range
   :raises DeviceCapabilityError: If device doesn't support DHW mode control

   **Operation Modes:**

   * 1 = Heat Pump Only - Most efficient, uses only heat pump
   * 2 = Electric Only - Fast recovery, uses only electric heaters
   * 3 = Energy Saver - Balanced, recommended for most users
   * 4 = High Demand - Maximum heating capacity
   * 5 = Vacation - Low power mode for extended absence

   **Example:**

   .. code-block:: python

      from nwp500 import DhwOperationSetting
      
      # Set to Energy Saver (balanced, recommended)
      await mqtt.control.set_dhw_mode(device, DhwOperationSetting.ENERGY_SAVER.value)
      # or just:
      await mqtt.control.set_dhw_mode(device, 3)
      
      # Set vacation mode for 7 days
      await mqtt.control.set_dhw_mode(
          device,
          DhwOperationSetting.VACATION.value,
          vacation_days=7
      )

Temperature Control
--------------------

set_dhw_temperature()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: set_dhw_temperature(device, temperature_f)

   Set DHW target temperature.

   **Capability Required:** ``dhw_temperature_setting_use`` - DHW temperature control enabled

   :param device: Device object
   :type device: Device
   :param temperature_f: Target temperature in Fahrenheit (95-150°F)
   :type temperature_f: float
   :return: Publish packet ID
   :rtype: int
   :raises RangeValidationError: If temperature is outside 95-150°F range
   :raises DeviceCapabilityError: If device doesn't support temperature control

   The temperature is automatically converted to the device's internal format
   (half-degrees Celsius).

   **Example:**

   .. code-block:: python

      # Set temperature to 140°F
      await mqtt.control.set_dhw_temperature(device, 140.0)
      
      # Common temperatures
      await mqtt.control.set_dhw_temperature(device, 120.0)  # Standard
      await mqtt.control.set_dhw_temperature(device, 130.0)  # Medium
      await mqtt.control.set_dhw_temperature(device, 140.0)  # Hot
      await mqtt.control.set_dhw_temperature(device, 150.0)  # Maximum

Anti-Legionella Control
------------------------

enable_anti_legionella()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: enable_anti_legionella(device, period_days)

   Enable anti-Legionella disinfection cycle.

   :param device: Device object
   :type device: Device
   :param period_days: Cycle period in days (1-30)
   :type period_days: int
   :return: Publish packet ID
   :rtype: int
   :raises RangeValidationError: If period_days not in 1-30 range

   **Example:**

   .. code-block:: python

      # Enable weekly anti-Legionella cycle
      await mqtt.control.enable_anti_legionella(device, period_days=7)
      
      # Enable bi-weekly cycle
      await mqtt.control.enable_anti_legionella(device, period_days=14)

disable_anti_legionella()
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: disable_anti_legionella(device)

   Disable anti-Legionella disinfection cycle.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      await mqtt.control.disable_anti_legionella(device)

Vacation Mode
--------------

set_vacation_days()
^^^^^^^^^^^^^^^^^^^

.. py:method:: set_vacation_days(device, days)

   Set vacation/away mode duration in days.

   **Capability Required:** ``holiday_use`` - Must be present in device features

   Configures the device to operate in energy-saving mode for the specified number
   of days during absence.

   :param device: Device object
   :type device: Device
   :param days: Number of vacation days (1-365 recommended, positive values)
   :type days: int
   :return: Publish packet ID
   :rtype: int
   :raises RangeValidationError: If days is not positive
   :raises DeviceCapabilityError: If device doesn't support vacation mode

   **Example:**

   .. code-block:: python

      # Set vacation for 14 days
      await mqtt.control.set_vacation_days(device, 14)
      
      # Set for full month
      await mqtt.control.set_vacation_days(device, 30)

Recirculation Control
---------------------

set_recirculation_mode()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: set_recirculation_mode(device, mode)

   Set recirculation pump operation mode.

   **Capability Required:** ``recirculation_use`` - Must be present in device features

   Configures how the recirculation pump operates:

   * 1 = Always On - Pump runs continuously
   * 2 = Button Only - Pump activates only via button press
   * 3 = Schedule - Pump follows configured schedule
   * 4 = Temperature - Pump maintains water temperature

   :param device: Device object
   :type device: Device
   :param mode: Recirculation mode (1-4)
   :type mode: int
   :return: Publish packet ID
   :rtype: int
   :raises RangeValidationError: If mode not in 1-4 range
   :raises DeviceCapabilityError: If device doesn't support recirculation

   **Example:**

   .. code-block:: python

      # Enable always-on recirculation
      await mqtt.control.set_recirculation_mode(device, 1)
      
      # Set to temperature-based control
      await mqtt.control.set_recirculation_mode(device, 4)

trigger_recirculation_hot_button()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: trigger_recirculation_hot_button(device)

   Manually trigger the recirculation pump hot button.

   **Capability Required:** ``recirculation_use`` - Must be present in device features

   Activates the recirculation pump for immediate hot water delivery.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int
   :raises DeviceCapabilityError: If device doesn't support recirculation

   **Example:**

   .. code-block:: python

      # Manually activate recirculation for immediate hot water
      await mqtt.control.trigger_recirculation_hot_button(device)

configure_recirculation_schedule()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: configure_recirculation_schedule(device, schedule)

   Configure recirculation pump schedule.

   **Capability Required:** ``recirc_reservation_use`` - Recirculation scheduling enabled

   Sets up the recirculation pump operating schedule with specified periods and settings.

   :param device: Device object
   :type device: Device
   :param schedule: Recirculation schedule configuration
   :type schedule: dict
   :return: Publish packet ID
   :rtype: int
   :raises DeviceCapabilityError: If device doesn't support recirculation scheduling

   **Example:**

   .. code-block:: python

      schedule = {
          "enabled": True,
          "periods": [
              {
                  "startHour": 6,
                  "startMinute": 0,
                  "endHour": 22,
                  "endMinute": 0,
                  "weekDays": [1, 1, 1, 1, 1, 0, 0]  # Mon-Fri
              }
          ]
      }
      
      await mqtt.control.configure_recirculation_schedule(device, schedule)

Time-of-Use Control
--------------------

set_tou_enabled()
^^^^^^^^^^^^^^^^^

.. py:method:: set_tou_enabled(device, enabled)

   Enable or disable Time-of-Use optimization.

   **Capability Required:** ``program_reservation_use`` - Must be present in device features

   :param device: Device object
   :type device: Device
   :param enabled: True to enable, False to disable
   :type enabled: bool
   :return: Publish packet ID
   :rtype: int
   :raises DeviceCapabilityError: If device doesn't support TOU

   **Example:**

   .. code-block:: python

      # Enable TOU
      await mqtt.control.set_tou_enabled(device, True)
      
      # Disable TOU
      await mqtt.control.set_tou_enabled(device, False)

configure_tou_schedule()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: configure_tou_schedule(device, controller_serial_number, periods, enabled=True)

   Configure Time-of-Use pricing schedule via MQTT.

   **Capability Required:** ``program_reservation_use`` - Must be present in device features

   :param device: Device object
   :type device: Device
   :param controller_serial_number: Controller serial number
   :type controller_serial_number: str
   :param periods: List of TOU period definitions
   :type periods: list[dict]
   :param enabled: Whether TOU is enabled (default: True)
   :type enabled: bool
   :return: Publish packet ID
   :rtype: int
   :raises ParameterValidationError: If controller_serial_number empty or periods empty
   :raises DeviceCapabilityError: If device doesn't support TOU

   **Example:**

   .. code-block:: python

      periods = [
          {
              "season": 0,
              "week": 0,
              "startHour": 9,
              "startMinute": 0,
              "endHour": 17,
              "endMinute": 0,
              "priceMin": 0.10,
              "priceMax": 0.25,
              "decimalPoint": 2
          }
      ]
      
      await mqtt.control.configure_tou_schedule(
          device,
          controller_serial_number="ABC123",
          periods=periods
      )

request_tou_settings()
^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_tou_settings(device, controller_serial_number)

   Request current Time-of-Use schedule from the device.

   :param device: Device object
   :type device: Device
   :param controller_serial_number: Controller serial number
   :type controller_serial_number: str
   :return: Publish packet ID
   :rtype: int
   :raises ParameterValidationError: If controller_serial_number empty

Reservation Management
----------------------

update_reservations()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: update_reservations(device, reservations, enabled=True)

   Update device reservation schedule.

   **Capability Required:** ``program_reservation_use`` - Must be present in device features

   :param device: Device object
   :type device: Device
   :param reservations: List of reservation objects
   :type reservations: list[dict]
   :param enabled: Enable/disable reservation schedule (default: True)
   :type enabled: bool
   :return: Publish packet ID
   :rtype: int
   :raises DeviceCapabilityError: If device doesn't support reservations

   **Example:**

   .. code-block:: python

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
      
      await mqtt.control.update_reservations(device, reservations, enabled=True)

request_reservations()
^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_reservations(device)

   Request current reservation schedule from the device.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

configure_reservation_water_program()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: configure_reservation_water_program(device)

   Enable/configure water program reservation mode.

   **Capability Required:** ``program_reservation_use`` - Must be present in device features

   Enables the water program reservation system for scheduling.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int
   :raises DeviceCapabilityError: If device doesn't support reservation programs

Energy Monitoring
------------------

request_energy_usage()
^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: request_energy_usage(device, year, months)

   Request daily energy usage data for specified period.

   Retrieves historical energy usage data showing heat pump and electric heating
   element consumption broken down by day.

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
      await mqtt.control.request_energy_usage(device, now.year, [now.month])
      
      # Request multiple months
      await mqtt.control.request_energy_usage(device, 2024, [8, 9, 10])

Demand Response
----------------

enable_demand_response()
^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: enable_demand_response(device)

   Enable utility demand response participation.

   Allows the device to respond to utility demand response signals to reduce
   consumption (shed) or pre-heat (load up) before peak periods.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      # Enable demand response
      await mqtt.control.enable_demand_response(device)

disable_demand_response()
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: disable_demand_response(device)

   Disable utility demand response participation.

   Prevents the device from responding to utility demand response signals.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      # Disable demand response
      await mqtt.control.disable_demand_response(device)

Air Filter Maintenance
-----------------------

reset_air_filter()
^^^^^^^^^^^^^^^^^^

.. py:method:: reset_air_filter(device)

   Reset air filter maintenance timer.

   Used for heat pump models to reset the maintenance timer after filter
   cleaning or replacement.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      # Reset air filter timer after maintenance
      await mqtt.control.reset_air_filter(device)

Utility Methods
---------------

signal_app_connection()
^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: signal_app_connection(device)

   Signal that an application has connected.

   Recommended to call at startup to notify the device of app connection.

   :param device: Device object
   :type device: Device
   :return: Publish packet ID
   :rtype: int

   **Example:**

   .. code-block:: python

      await mqtt.connect()
      await mqtt.control.signal_app_connection(device)

Device Capabilities Module
==========================

The ``DeviceCapabilityChecker`` provides a mapping-based approach to validate
device capabilities without requiring individual checker functions.

.. py:class:: DeviceCapabilityChecker

   Generalized device capability checker using a capability map.

   Class Methods
   ^^^^^^^^^^^^^

supports()
""""""""""

.. py:staticmethod:: supports(feature, device_features)

   Check if device supports control of a specific feature.

   :param feature: Name of the controllable feature
   :type feature: str
   :param device_features: Device feature information
   :type device_features: DeviceFeature
   :return: True if feature control is supported, False otherwise
   :rtype: bool
   :raises ValueError: If feature is not recognized

   **Supported Features:**

   * ``power_use`` - Device power on/off control
   * ``dhw_use`` - DHW mode changes
   * ``dhw_temperature_setting_use`` - DHW temperature control
   * ``holiday_use`` - Vacation/away mode
   * ``program_reservation_use`` - Reservations and TOU scheduling
   * ``recirculation_use`` - Recirculation pump control
   * ``recirc_reservation_use`` - Recirculation scheduling

   **Example:**

   .. code-block:: python

      from nwp500.device_capabilities import DeviceCapabilityChecker

      if DeviceCapabilityChecker.supports("recirculation_use", device_features):
          print("Device supports recirculation pump control")
      else:
          print("Device doesn't support recirculation pump")

assert_supported()
""""""""""""""""""

.. py:staticmethod:: assert_supported(feature, device_features)

   Assert that device supports control of a feature.

   :param feature: Name of the controllable feature
   :type feature: str
   :param device_features: Device feature information
   :type device_features: DeviceFeature
   :raises DeviceCapabilityError: If feature control is not supported
   :raises ValueError: If feature is not recognized

   **Example:**

   .. code-block:: python

      from nwp500.device_capabilities import DeviceCapabilityChecker
      from nwp500 import DeviceCapabilityError

      try:
          DeviceCapabilityChecker.assert_supported("recirculation_use", features)
          await mqtt.control.set_recirculation_mode(device, 1)
      except DeviceCapabilityError as e:
          print(f"Cannot set recirculation: {e}")

get_available_controls()
""""""""""""""""""""""""

.. py:staticmethod:: get_available_controls(device_features)

   Get all controllable features available on a device.

   :param device_features: Device feature information
   :type device_features: DeviceFeature
   :return: Dictionary mapping feature names to whether they can be controlled
   :rtype: dict[str, bool]

   **Example:**

   .. code-block:: python

      from nwp500.device_capabilities import DeviceCapabilityChecker

      controls = DeviceCapabilityChecker.get_available_controls(device_features)
      for feature, supported in controls.items():
          status = "✓" if supported else "✗"
          print(f"{status} {feature}")

register_capability()
"""""""""""""""""""""

.. py:staticmethod:: register_capability(name, check_fn)

   Register a custom controllable feature check.

   Allows extensions or applications to define custom capability checks without
   modifying the core library.

   :param name: Feature name
   :type name: str
   :param check_fn: Function that takes DeviceFeature and returns bool
   :type check_fn: Callable[[DeviceFeature], bool]

   **Example:**

   .. code-block:: python

      from nwp500.device_capabilities import DeviceCapabilityChecker

      def check_custom_feature(features):
          return features.some_custom_field is not None

      # Register custom capability
      DeviceCapabilityChecker.register_capability("custom_feature", check_custom_feature)

      # Now can use it with control methods
      if DeviceCapabilityChecker.supports("custom_feature", device_features):
          # Execute custom command
          pass

Controller Capability Methods
------------------------------

MqttDeviceController also provides direct capability checking methods:

check_support()
^^^^^^^^^^^^^^^

.. py:method:: check_support(feature, device_features)

   Check if device supports a controllable feature.

   :param feature: Name of the controllable feature
   :type feature: str
   :param device_features: Device feature information
   :type device_features: DeviceFeature
   :return: True if feature is supported, False otherwise
   :rtype: bool
   :raises ValueError: If feature is not recognized

   **Example:**

   .. code-block:: python

      if mqtt.check_support("recirculation_use", device_features):
          await mqtt.control.set_recirculation_mode(device, 1)

assert_support()
^^^^^^^^^^^^^^^^

.. py:method:: assert_support(feature, device_features)

   Assert that device supports a controllable feature.

   :param feature: Name of the controllable feature
   :type feature: str
   :param device_features: Device feature information
   :type device_features: DeviceFeature
   :raises DeviceCapabilityError: If feature is not supported
   :raises ValueError: If feature is not recognized

   **Example:**

   .. code-block:: python

      try:
          mqtt.assert_support("recirculation_use", device_features)
          await mqtt.control.set_recirculation_mode(device, 1)
      except DeviceCapabilityError as e:
          print(f"Device doesn't support: {e}")

Capability Checking Decorator
==============================

The ``@requires_capability`` decorator automatically validates device capabilities
before command execution.

.. py:function:: requires_capability(feature)

   Decorator that validates device capability before executing command.

   This decorator automatically checks if a device supports a specific controllable
   feature before allowing the command to execute. If the device doesn't support
   the feature, a ``DeviceCapabilityError`` is raised.

   **Requirements:**

   The decorated method must:

   1. Have ``self`` (controller instance with ``_device_info_cache``)
   2. Have ``device`` parameter (Device object with ``mac_address``)
   3. Be async (sync methods log a warning and bypass checking for backward compatibility)

   The device info must be cached (via ``request_device_info``) before calling
   the command, otherwise a ``DeviceCapabilityError`` is raised. The decorator
   supports automatic device info requests if the controller callback is configured.

   :param feature: Name of the required capability (e.g., "recirculation_use")
   :type feature: str
   :return: Decorator function
   :rtype: Callable

   :raises DeviceCapabilityError: If device doesn't support the feature
   :raises ValueError: If feature name is not recognized

   **How It Works:**

   1. Extracts device MAC address from ``device`` parameter
   2. Checks if device info is already cached
   3. If not cached, automatically attempts to request it (if callback configured)
   4. Validates the capability using ``DeviceCapabilityChecker``
   5. Executes command only if capability check passes
   6. Logs all operations for debugging

   **Example Usage:**

   .. code-block:: python

      from nwp500.mqtt_device_control import MqttDeviceController
      from nwp500.command_decorators import requires_capability

      class MyController(MqttDeviceController):
          @requires_capability("recirculation_use")
          async def set_recirculation_mode(self, device, mode):
              # Capability automatically checked before this executes
              return await self._publish(...)

   **Automatic Device Info Requests:**

   When a control method is called and device info isn't cached, the decorator
   attempts to automatically request it:

   .. code-block:: python

      # Device info is automatically requested if not cached
      await mqtt.control.set_recirculation_mode(device, 1)
      
      # This triggers:
      # 1. Check cache (not found)
      # 2. Auto-request device info
      # 3. Wait for response
      # 4. Validate capability
      # 5. Execute command

Error Handling
--------------

**DeviceCapabilityError** is raised when:

1. Device doesn't support the required feature
2. Device info cannot be obtained (for automatic requests)
3. Feature name is not recognized

.. code-block:: python

   from nwp500 import DeviceCapabilityError

   try:
       await mqtt.control.set_recirculation_mode(device, 1)
   except DeviceCapabilityError as e:
       print(f"Cannot execute command: {e}")
       print(f"Missing capability: {e.feature}")

Best Practices
==============

1. **Always request device info first:**

   .. code-block:: python

      # Request device info before control commands
      await mqtt.subscribe_device_feature(device, on_feature)
      await mqtt.control.request_device_info(device)
      
      # Now control commands can proceed
      await mqtt.control.set_power(device, True)

2. **Check capabilities manually for custom logic:**

   .. code-block:: python

      from nwp500.device_capabilities import DeviceCapabilityChecker

      controls = DeviceCapabilityChecker.get_available_controls(features)
      
      if controls.get("recirculation_use"):
          await mqtt.control.set_recirculation_mode(device, 1)
      else:
          print("Recirculation not supported")

3. **Handle capability errors gracefully:**

   .. code-block:: python

      from nwp500 import DeviceCapabilityError

      try:
          await mqtt.control.set_recirculation_mode(device, 1)
      except DeviceCapabilityError as e:
          logger.warning(f"Feature not supported: {e.feature}")
          # Fallback to alternative command

4. **Use try/except for robust error handling:**

   .. code-block:: python

      from nwp500 import DeviceCapabilityError, RangeValidationError

      try:
          await mqtt.control.set_dhw_temperature(device, 140.0)
      except DeviceCapabilityError as e:
          print(f"Device doesn't support temperature control: {e}")
      except RangeValidationError as e:
          print(f"Invalid temperature {e.value}°F: {e.message}")

5. **Implement device capability discovery:**

   .. code-block:: python

      from nwp500.device_capabilities import DeviceCapabilityChecker

      def print_device_capabilities(device_features):
          """Print all supported controls."""
          controls = DeviceCapabilityChecker.get_available_controls(device_features)
          
          print("Available Controls:")
          for feature in sorted(controls.keys()):
              supported = controls[feature]
              status = "✓" if supported else "✗"
              print(f"  {status} {feature}")

Examples
========

Example 1: Safe Device Control with Capability Checking
--------------------------------------------------------

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient
   from nwp500.device_capabilities import DeviceCapabilityChecker
   from nwp500 import DeviceCapabilityError
   import asyncio

   async def safe_device_control():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Store features from device info
           features = None
           
           def on_feature(f):
               nonlocal features
               features = f
           
           # Request device info
           await mqtt.subscribe_device_feature(device, on_feature)
           await mqtt.control.request_device_info(device)
           
           # Wait a bit for response
           await asyncio.sleep(2)
           
           if features:
               # Check what's supported
               controls = DeviceCapabilityChecker.get_available_controls(features)
               
               # Power control
               if controls.get("power_use"):
                   try:
                       await mqtt.control.set_power(device, True)
                       print("✓ Device powered ON")
                   except DeviceCapabilityError as e:
                       print(f"✗ Power control failed: {e}")
               
               # Recirculation control
               if controls.get("recirculation_use"):
                   try:
                       await mqtt.control.set_recirculation_mode(device, 1)
                       print("✓ Recirculation enabled")
                   except DeviceCapabilityError as e:
                       print(f"✗ Recirculation failed: {e}")
               
               # Temperature control
               if controls.get("dhw_temperature_setting_use"):
                   try:
                       await mqtt.control.set_dhw_temperature(device, 140.0)
                       print("✓ Temperature set to 140°F")
                   except DeviceCapabilityError as e:
                       print(f"✗ Temperature control failed: {e}")
           
           await mqtt.disconnect()

   asyncio.run(safe_device_control())

Example 2: Automatic Capability Checking with Decorator
--------------------------------------------------------

.. code-block:: python

   # Control methods are automatically decorated with @requires_capability
   # No additional code needed - just call them!

   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient
   from nwp500 import DeviceCapabilityError
   import asyncio

   async def simple_control():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Request device info once
           await mqtt.subscribe_device_feature(device, lambda f: None)
           await mqtt.control.request_device_info(device)
           
           # All control methods now have automatic capability checking
           try:
               await mqtt.control.set_power(device, True)
               await mqtt.control.set_dhw_mode(device, 3)
               await mqtt.control.set_recirculation_mode(device, 1)
           except DeviceCapabilityError as e:
               print(f"Device doesn't support: {e}")
           
           await mqtt.disconnect()

   asyncio.run(simple_control())

Related Documentation
=====================

* :doc:`mqtt_client` - MQTT client overview
* :doc:`models` - Data models (DeviceStatus, DeviceFeature, etc.)
* :doc:`exceptions` - Exception handling (DeviceCapabilityError, etc.)
* :doc:`../protocol/device_features` - Device features reference
* :doc:`../guides/scheduling_features` - Scheduling guide
* :doc:`../guides/energy_monitoring` - Energy monitoring guide
* :doc:`../guides/reservations` - Reservations guide
* :doc:`../guides/time_of_use` - Time-of-use guide
