=========
Constants
=========

The ``nwp500.constants`` module defines MQTT command codes and protocol constants.

Command Codes
=============

CommandCode
-----------

MQTT command codes for device communication.

.. py:class:: CommandCode(IntEnum)

   All MQTT commands use these numeric codes. Commands fall into two categories:

   * **Query commands** (16777xxx) - Request information
   * **Control commands** (33554xxx) - Change settings

Query Commands
^^^^^^^^^^^^^^

.. py:attribute:: DEVICE_INFO_REQUEST = 16777217

   Request device feature information and capabilities.

   **Response:** DeviceFeature object with firmware versions, serial number,
   temperature limits, and supported features.

   **Example:**

   .. code-block:: python

      await mqtt.request_device_info(device)

.. py:attribute:: STATUS_REQUEST = 16777219

   Request current device status.

   **Response:** DeviceStatus object with 100+ fields including temperatures,
   power consumption, operation mode, and component states.

   **Example:**

   .. code-block:: python

      await mqtt.request_device_status(device)

.. py:attribute:: RESERVATION_READ = 16777222

   Read current reservation schedule.

   **Response:** Reservation schedule configuration.

   **Example:**

   .. code-block:: python

      await mqtt.request_reservations(device)

.. py:attribute:: ENERGY_USAGE_QUERY = 16777225

   Query historical energy usage data.

   **Request Parameters:**
      * year (int) - Year to query
      * months (list[int]) - List of months (1-12)

   **Response:** EnergyUsageResponse with daily breakdown of heat pump and
   electric heater consumption.

   **Example:**

   .. code-block:: python

      await mqtt.request_energy_usage(device, 2024, [10, 11])

.. py:attribute:: RESERVATION_MANAGEMENT = 16777226

   Update reservation schedule.

   **Request Parameters:**
      * enabled (bool) - Enable/disable schedule
      * reservations (list[dict]) - Reservation entries

   **Example:**

   .. code-block:: python

      await mqtt.update_reservations(device, True, reservations)

Power Control Commands
^^^^^^^^^^^^^^^^^^^^^^

.. py:attribute:: POWER_OFF = 33554433

   Turn device off.

   **Example:**

   .. code-block:: python

      await mqtt.set_power(device, power_on=False)

.. py:attribute:: POWER_ON = 33554434

   Turn device on.

   **Example:**

   .. code-block:: python

      await mqtt.set_power(device, power_on=True)

DHW Control Commands
^^^^^^^^^^^^^^^^^^^^

.. py:attribute:: DHW_MODE = 33554437

   Change DHW operation mode.

   **Request Parameters:**
      * mode_id (int) - Mode: 1=Heat Pump, 2=Electric, 3=Energy Saver,
        4=High Demand, 5=Vacation
      * vacation_days (int, optional) - Days for vacation mode

   **Example:**

   .. code-block:: python

      from nwp500 import DhwOperationSetting

      # Energy Saver mode
      await mqtt.set_dhw_mode(device, DhwOperationSetting.ENERGY_SAVER.value)

      # Vacation mode for 7 days
      await mqtt.set_dhw_mode(
          device,
          DhwOperationSetting.VACATION.value,
          vacation_days=7
      )

.. py:attribute:: DHW_TEMPERATURE = 33554464

   Set DHW target temperature.

   **Request Parameters:**
      * temperature (int) - Temperature in °F (message value, not display)

   .. important::
      Message value is 20°F less than display value.
      Display 140°F = Message 120°F

   **Example:**

   .. code-block:: python

      # Set temperature to 140°F
      await mqtt.set_dhw_temperature(device, 140.0)

Anti-Legionella Commands
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:attribute:: ANTI_LEGIONELLA_DISABLE = 33554471

   Disable anti-Legionella protection cycle.

   **Example:**

   .. code-block:: python

      await mqtt.disable_anti_legionella(device)

.. py:attribute:: ANTI_LEGIONELLA_ENABLE = 33554472

   Enable anti-Legionella protection cycle.

   **Request Parameters:**
      * period_days (int) - Cycle period (typically 7 or 14 days)

   **Example:**

   .. code-block:: python

      # Enable weekly cycle
      await mqtt.enable_anti_legionella(device, period_days=7)

Time-of-Use Commands
^^^^^^^^^^^^^^^^^^^^

.. py:attribute:: TOU_SETTINGS = 33554439

   Configure TOU schedule.

   **Example:**

   .. code-block:: python

      await mqtt.configure_tou_schedule(device, schedule_data)

.. py:attribute:: TOU_DISABLE = 33554475

   Disable TOU optimization.

   **Example:**

   .. code-block:: python

      await mqtt.set_tou_enabled(device, False)

.. py:attribute:: TOU_ENABLE = 33554476

   Enable TOU optimization.

   **Example:**

   .. code-block:: python

      await mqtt.set_tou_enabled(device, True)

Usage Examples
==============

Using Command Codes Directly
-----------------------------

.. code-block:: python

   from nwp500.constants import CommandCode
   from nwp500.models import MqttRequest, MqttCommand

   # Build custom request
   request = MqttRequest(
       command=CommandCode.STATUS_REQUEST,
       deviceType=52,
       macAddress="04786332fca0",
       additionalValue="",
       param=[],
       paramStr=""
   )

   command = MqttCommand(
       clientID=mqtt.client_id,
       sessionID=mqtt.session_id,
       requestTopic=f"cmd/52/04786332fca0/ctrl",
       responseTopic=f"cmd/52/04786332fca0/st",
       request=request,
       protocolVersion=2
   )

   # Publish
   await mqtt.publish(topic, command)

Checking Command Types
----------------------

.. code-block:: python

   from nwp500.constants import CommandCode

   def is_query_command(cmd_code: int) -> bool:
       """Check if command is a query (not control)."""
       return 16777000 <= cmd_code < 16778000

   def is_control_command(cmd_code: int) -> bool:
       """Check if command is a control operation."""
       return 33554000 <= cmd_code < 33555000

   # Usage
   if is_query_command(CommandCode.STATUS_REQUEST):
       print("This is a query command")

   if is_control_command(CommandCode.POWER_ON):
       print("This is a control command")

Firmware Version Constants
===========================

Latest Known Firmware
---------------------

The library tracks known firmware versions for compatibility:

.. code-block:: python

   from nwp500.constants import LATEST_KNOWN_FIRMWARE

   # Latest observed versions
   {
       "controllerSwVersion": 184614912,
       "panelSwVersion": 0,
       "wifiSwVersion": 34013184
   }

Firmware Field Changes
----------------------

Some fields were introduced in specific firmware versions:

.. code-block:: python

   from nwp500.constants import KNOWN_FIRMWARE_FIELD_CHANGES

   # Example: heatMinOpTemperature field
   {
       "heatMinOpTemperature": {
           "introduced_in": "Controller: 184614912, WiFi: 34013184",
           "description": "Minimum heat pump operation temperature",
           "conversion": "HalfCelsiusToF"
       }
   }

Best Practices
==============

1. **Use enums instead of magic numbers:**

   .. code-block:: python

      # [OK] Clear and type-safe
      from nwp500.constants import CommandCode
      request.command = CommandCode.STATUS_REQUEST

      # ✗ Magic number
      request.command = 16777219

2. **Let the client handle command building:**

   .. code-block:: python

      # [OK] Preferred - client handles command codes
      await mqtt.request_device_status(device)

      # ✗ Manual - only for advanced use cases
      await mqtt.publish(topic, build_command(CommandCode.STATUS_REQUEST))

3. **Check command types for logging/debugging:**

   .. code-block:: python

      def log_command(cmd_code: int):
          cmd_name = CommandCode(cmd_code).name
          cmd_type = "Query" if cmd_code < 33554000 else "Control"
          print(f"{cmd_type} command: {cmd_name} ({cmd_code})")

Related Documentation
=====================

* :doc:`models` - Data models and enums
* :doc:`mqtt_client` - MQTT client using these commands
* :doc:`../protocol/mqtt_protocol` - MQTT protocol details
