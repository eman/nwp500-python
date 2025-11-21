===========
Data Models
===========

The ``nwp500.models`` module provides type-safe data models for all Navien
device data, including device information, status, features, and energy usage.

Overview
========

All models are **immutable dataclasses** with:

* Type annotations for all fields
* Automatic validation
* JSON serialization support
* Enum types for categorical values
* Automatic unit conversions

Enumerations
============

DhwOperationSetting
-------------------

DHW (Domestic Hot Water) operation modes - the user's configured heating
preference.

.. py:class:: DhwOperationSetting(Enum)

   **Values:**

   * ``HEAT_PUMP = 1`` - Heat Pump Only
      - Most efficient mode
      - Uses only heat pump (no electric heaters)
      - Slowest recovery time
      - Lowest operating cost
      - Best for normal daily use

   * ``ELECTRIC = 2`` - Electric Only
      - Fast recovery mode
      - Uses only electric resistance heaters
      - Fastest recovery time
      - Highest operating cost
      - Use for high-demand situations

   * ``ENERGY_SAVER = 3`` - Energy Saver (Hybrid)
      - **Recommended for most users**
      - Balanced efficiency and performance
      - Uses heat pump primarily, electric when needed
      - Good recovery time
      - Moderate operating cost

   * ``HIGH_DEMAND = 4`` - High Demand
      - Maximum heating capacity
      - Uses both heat pump and electric heaters
      - Fast recovery with continuous demand
      - Higher operating cost
      - Best for large families or frequent use

   * ``VACATION = 5`` - Vacation Mode
      - Low-power standby mode
      - Maintains minimum temperature
      - Prevents freezing
      - Lowest energy consumption
      - Requires vacation_days parameter

   **Example:**

   .. code-block:: python

      from nwp500 import DhwOperationSetting, NavienMqttClient

      # Set to Energy Saver (recommended)
      await mqtt.set_dhw_mode(device, DhwOperationSetting.ENERGY_SAVER.value)

      # Set to Heat Pump Only (most efficient)
      await mqtt.set_dhw_mode(device, DhwOperationSetting.HEAT_PUMP.value)

      # Set vacation mode for 7 days
      await mqtt.set_dhw_mode(
          device,
          DhwOperationSetting.VACATION.value,
          vacation_days=7
      )

      # Check current mode from status
      def on_status(status):
          if status.dhw_operation_setting == DhwOperationSetting.ENERGY_SAVER:
              print("Running in Energy Saver mode")

CurrentOperationMode
--------------------

Current real-time operational state - what the device is doing **right now**.

.. py:class:: CurrentOperationMode(Enum)

   Unlike ``DhwOperationSetting`` (user preference), this reflects the actual
   real-time operation and changes dynamically.

   **Values:**

   * ``IDLE = 0`` - Device is idle, not heating
   * ``HEAT_PUMP = 1`` - Heat pump actively running
   * ``ELECTRIC_HEATER = 2`` - Electric heater actively running
   * ``HEAT_PUMP_AND_HEATER = 3`` - Both heat pump and electric running

   **Example:**

   .. code-block:: python

      from nwp500 import CurrentOperationMode

      def on_status(status):
          mode = status.operation_mode

          if mode == CurrentOperationMode.IDLE:
              print("Device idle")
          elif mode == CurrentOperationMode.HEAT_PUMP:
              print(f"Heat pump running at {status.current_inst_power}W")
          elif mode == CurrentOperationMode.ELECTRIC_HEATER:
              print(f"Electric heater at {status.current_inst_power}W")
          elif mode == CurrentOperationMode.HEAT_PUMP_AND_HEATER:
              print(f"Both running at {status.current_inst_power}W")

TemperatureUnit
---------------

Temperature scale enumeration.

.. py:class:: TemperatureUnit(Enum)

   **Values:**

   * ``CELSIUS = 1`` - Celsius (°C)
   * ``FAHRENHEIT = 2`` - Fahrenheit (°F)

   **Example:**

   .. code-block:: python

      def on_status(status):
          if status.temperature_type == TemperatureUnit.FAHRENHEIT:
              print(f"Temperature: {status.dhw_temperature}°F")
          else:
              print(f"Temperature: {status.dhw_temperature}°C")

Device Models
=============

Device
------

Complete device representation with info and location.

.. py:class:: Device

   **Fields:**

   * ``device_info`` (DeviceInfo) - Device identification and status
   * ``location`` (Location) - Physical location information

   **Example:**

   .. code-block:: python

      device = await api.get_first_device()

      # Access device info
      info = device.device_info
      print(f"Name: {info.device_name}")
      print(f"MAC: {info.mac_address}")
      print(f"Type: {info.device_type}")
      print(f"Connected: {info.connected == 2}")

      # Access location
      loc = device.location
      if loc.city:
          print(f"Location: {loc.city}, {loc.state}")
          print(f"Coords: {loc.latitude}, {loc.longitude}")

DeviceInfo
----------

Device identification and connection information.

.. py:class:: DeviceInfo

   **Fields:**

   * ``home_seq`` (int) - Home sequence number
   * ``mac_address`` (str) - MAC address (without colons)
   * ``additional_value`` (str) - Additional identifier
   * ``device_type`` (int) - Device type code (52 for NWP500)
   * ``device_name`` (str) - User-assigned device name
   * ``connected`` (int) - Connection status (2 = online, 0 = offline)
   * ``install_type`` (str, optional) - Installation type

   **Example:**

   .. code-block:: python

      info = device.device_info

      print(f"Device: {info.device_name}")
      print(f"MAC: {info.mac_address}")
      print(f"Type: {info.device_type}")

      if info.connected == 2:
          print("Status: Online [OK]")
      else:
          print("Status: Offline ✗")

Location
--------

Physical location information for a device.

.. py:class:: Location

   **Fields:**

   * ``state`` (str, optional) - State/province
   * ``city`` (str, optional) - City name
   * ``address`` (str, optional) - Street address
   * ``latitude`` (float, optional) - GPS latitude
   * ``longitude`` (float, optional) - GPS longitude
   * ``altitude`` (float, optional) - Altitude in meters

   **Example:**

   .. code-block:: python

      loc = device.location

      if loc.city and loc.state:
          print(f"Location: {loc.city}, {loc.state}")

      if loc.latitude and loc.longitude:
          print(f"GPS: {loc.latitude}, {loc.longitude}")

FirmwareInfo
------------

Firmware version information.

.. py:class:: FirmwareInfo

   **Fields:**

   * ``mac_address`` (str) - Device MAC address
   * ``additional_value`` (str) - Additional identifier
   * ``device_type`` (int) - Device type code
   * ``cur_sw_code`` (int) - Current software code
   * ``cur_version`` (int) - Current version number
   * ``downloaded_version`` (int, optional) - Downloaded update version
   * ``device_group`` (str, optional) - Device group

   **Example:**

   .. code-block:: python

      fw_list = await api.get_firmware_info()

      for fw in fw_list:
          print(f"Device: {fw.mac_address}")
          print(f"  Current: {fw.cur_version} (code: {fw.cur_sw_code})")

          if fw.downloaded_version:
              print(f"  [WARNING]  Update available: {fw.downloaded_version}")
          else:
              print(f"  [OK] Up to date")

Status Models
=============

DeviceStatus
------------

Complete real-time device status with 100+ fields.

.. py:class:: DeviceStatus

   **Key Temperature Fields:**

   * ``dhw_temperature`` (float) - Current water temperature (°F or °C)
   * ``dhw_temperature_setting`` (float) - Target temperature setting
   * ``dhw_target_temperature_setting`` (float) - Target with offsets applied
   * ``tank_upper_temperature`` (float) - Upper tank sensor
   * ``tank_lower_temperature`` (float) - Lower tank sensor
   * ``current_inlet_temperature`` (float) - Cold water inlet temperature
   * ``outside_temperature`` (float) - Outdoor temperature
   * ``ambient_temperature`` (float) - Ambient air temperature

   .. note::
      Temperature values from the device are automatically converted from their raw (scaled Celsius) representation to Fahrenheit or Celsius based on the device's settings. The library handles these conversions transparently.

   **Key Power/Energy Fields:**

   * ``current_inst_power`` (float) - Current power consumption (Watts)
   * ``total_energy_capacity`` (float) - Total energy capacity (%)
   * ``available_energy_capacity`` (float) - Available energy (%)
   * ``dhw_charge_per`` (float) - DHW charge percentage

   **Operation Mode Fields:**

   * ``operation_mode`` (CurrentOperationMode) - Current operational state
   * ``dhw_operation_setting`` (DhwOperationSetting) - User's mode preference
   * ``temperature_type`` (TemperatureUnit) - Temperature unit

   **Boolean Status Fields:**

   * ``operation_busy`` (bool) - Device actively heating water
   * ``dhw_use`` (bool) - Water being used (short-term detection)
   * ``dhw_use_sustained`` (bool) - Water being used (sustained)
   * ``comp_use`` (bool) - Compressor/heat pump running
   * ``heat_upper_use`` (bool) - Upper electric heater active
   * ``heat_lower_use`` (bool) - Lower electric heater active
   * ``eva_fan_use`` (bool) - Evaporator fan running
   * ``anti_legionella_use`` (bool) - Anti-Legionella enabled
   * ``anti_legionella_operation_busy`` (bool) - Anti-Legionella cycle active
   * ``program_reservation_use`` (bool) - Reservation schedule enabled
   * ``freeze_protection_use`` (bool) - Freeze protection enabled

   **Error/Diagnostic Fields:**

   * ``error_code`` (int) - Error code (0 = no error)
   * ``sub_error_code`` (int) - Sub-error code
   * ``smart_diagnostic`` (int) - Smart diagnostic status
   * ``fault_status1`` (int) - Fault status flags
   * ``fault_status2`` (int) - Additional fault flags

   **Network/Communication:**

   * ``wifi_rssi`` (int) - WiFi signal strength (dBm)

   **Vacation/Schedule:**

   * ``vacation_day_setting`` (int) - Vacation days configured
   * ``vacation_day_elapsed`` (int) - Vacation days elapsed
   * ``anti_legionella_period`` (int) - Anti-Legionella cycle period

   **Time-of-Use (TOU):**

   * ``tou_status`` (int) - TOU status
   * ``tou_override_status`` (int) - TOU override status

   **Heat Pump Detailed Status:**

   * ``target_fan_rpm`` (int) - Target fan RPM
   * ``current_fan_rpm`` (int) - Current fan RPM
   * ``fan_pwm`` (int) - Fan PWM duty cycle
   * ``mixing_rate`` (float) - Mixing valve rate
   * ``eev_step`` (int) - Electronic expansion valve position
   * ``discharge_temperature`` (float) - Compressor discharge temp
   * ``suction_temperature`` (float) - Compressor suction temp
   * ``evaporator_temperature`` (float) - Evaporator temperature
   * ``target_super_heat`` (float) - Target superheat
   * ``current_super_heat`` (float) - Current superheat

   **Example:**

   .. code-block:: python

      def on_status(status):
          # Temperature monitoring
          print(f"Water: {status.dhw_temperature}°F")
          print(f"Target: {status.dhw_temperature_setting}°F")
          print(f"Upper Tank: {status.tank_upper_temperature}°F")
          print(f"Lower Tank: {status.tank_lower_temperature}°F")

          # Power consumption
          print(f"Power: {status.current_inst_power}W")
          print(f"Energy: {status.available_energy_capacity}%")

          # Operation mode
          print(f"Mode: {status.dhw_operation_setting.name}")
          print(f"State: {status.operation_mode.name}")

          # Active heating
          if status.operation_busy:
              print("Heating water:")
              if status.comp_use:
                  print("  - Heat pump running")
              if status.heat_upper_use:
                  print("  - Upper heater active")
              if status.heat_lower_use:
                  print("  - Lower heater active")

          # Water usage detection
          if status.dhw_use:
              print("Water usage detected (short-term)")
          if status.dhw_useSustained:
              print("Water usage detected (sustained)")

          # Errors
          if status.error_code != 0:
              print(f"ERROR: {status.error_code}")
              if status.sub_error_code != 0:
                  print(f"  Sub-error: {status.sub_error_code}")

DeviceFeature
-------------

Device capabilities, features, and firmware information.

.. py:class:: DeviceFeature

   **Firmware Version Fields:**

   * ``controller_sw_version`` (int) - Controller firmware version
   * ``panel_sw_version`` (int) - Panel firmware version
   * ``wifi_sw_version`` (int) - WiFi module firmware version
   * ``controller_sw_code`` (int) - Controller software code
   * ``panel_sw_code`` (int) - Panel software code
   * ``wifi_sw_code`` (int) - WiFi software code
   * ``controller_serial_number`` (str) - Controller serial number

   **Device Configuration:**

   * ``country_code`` (int) - Country code
   * ``model_type_code`` (int) - Model type
   * ``control_type_code`` (int) - Control type
   * ``volume_code`` (int) - Tank volume code
   * ``temp_formula_type`` (int) - Temperature formula type
   * ``temperature_type`` (TemperatureUnit) - Temperature unit

   **Temperature Limits:**

   * ``dhw_temperature_min`` (int) - Minimum DHW temperature
   * ``dhw_temperature_max`` (int) - Maximum DHW temperature
   * ``freeze_protection_temp_min`` (int) - Min freeze protection temp
   * ``freeze_protection_temp_max`` (int) - Max freeze protection temp

   **Feature Flags (all int, 0=disabled, 1=enabled):**

   * ``power_use`` - Power control supported
   * ``dhw_use`` - DHW functionality
   * ``dhw_temperature_setting_use`` - Temperature control
   * ``energy_usage_use`` - Energy monitoring supported
   * ``anti_legionella_setting_use`` - Anti-Legionella supported
   * ``program_reservation_use`` - Reservation scheduling supported
   * ``freeze_protection_use`` - Freeze protection available
   * ``heatpump_use`` - Heat pump mode available
   * ``electric_use`` - Electric mode available
   * ``energy_saver_use`` - Energy Saver mode available
   * ``high_demand_use`` - High Demand mode available
   * ``smart_diagnostic_use`` - Smart diagnostics available
   * ``wifi_rssi_use`` - WiFi signal strength available
   * ``holiday_use`` - Holiday/vacation mode
   * ``mixing_value_use`` - Mixing valve
   * ``dr_setting_use`` - Demand response
   * ``dhw_refill_use`` - DHW refill
   * ``eco_use`` - Eco mode

   **Example:**

   .. code-block:: python

      def on_feature(feature):
          print(f"Serial: {feature.controller_serial_number}")
          print(f"Firmware: {feature.controller_sw_version}")
          print(f"WiFi: {feature.wifi_sw_version}")

          print(f"\nTemperature Range:")
          print(f"  Min: {feature.dhw_temperature_min}°F")
          print(f"  Max: {feature.dhw_temperature_max}°F")

          print(f"\nSupported Features:")
          if feature.energy_usage_use:
              print("  [OK] Energy monitoring")
          if feature.anti_legionella_setting_use:
              print("  [OK] Anti-Legionella")
          if feature.program_reservation_use:
              print("  [OK] Reservations")
          if feature.heatpump_use:
              print("  [OK] Heat pump mode")
          if feature.electric_use:
              print("  [OK] Electric mode")
          if feature.energy_saver_use:
              print("  [OK] Energy Saver mode")
          if feature.high_demand_use:
              print("  [OK] High Demand mode")

Energy Models
=============

EnergyUsageResponse
-------------------

Complete energy usage response with daily breakdown.

.. py:class:: EnergyUsageResponse

   **Fields:**

   * ``device_type`` (int) - Device type
   * ``mac_address`` (str) - Device MAC
   * ``additional_value`` (str) - Additional identifier
   * ``type_of_usage`` (int) - Usage type code
   * ``total`` (EnergyUsageTotal) - Total usage summary
   * ``usage`` (list[MonthlyEnergyData]) - Monthly data with daily breakdown

   **Example:**

   .. code-block:: python

      def on_energy(energy):
          # Overall totals
          total = energy.total
          print(f"Total Usage: {total.total_usage} Wh")
          print(f"Heat Pump: {total.heat_pump_percentage:.1f}%")
          print(f"Electric: {total.heat_element_percentage:.1f}%")

          # Monthly data
          for month_data in energy.usage:
              print(f"\n{month_data.year}-{month_data.month:02d}:")

              # Daily breakdown
              for day_num, day in enumerate(month_data.data, 1):
                  if day.total_usage > 0:
                      print(f"  Day {day_num}: {day.total_usage} Wh")
                      print(f"    HP: {day.heat_pump_usage} Wh ({day.heat_pump_time}h)")
                      print(f"    HE: {day.heat_element_usage} Wh ({day.heat_element_time}h)")

EnergyUsageTotal
----------------

Summary totals for energy usage.

.. py:class:: EnergyUsageTotal

   **Fields:**

   * ``heat_element_usage`` (int) - Total heat element usage (Wh)
   * ``heat_pump_usage`` (int) - Total heat pump usage (Wh)
   * ``heat_element_time`` (int) - Total heat element time (hours)
   * ``heat_pump_time`` (int) - Total heat pump time (hours)

   **Computed Properties:**

   * ``total_usage`` (int) - heat_element_usage + heat_pump_usage
   * ``heat_pump_percentage`` (float) - (heat_pump_usage / total) × 100
   * ``heat_element_percentage`` (float) - (heat_element_usage / total) × 100

MonthlyEnergyData
-----------------

Energy data for one month with daily breakdown.

.. py:class:: MonthlyEnergyData

   **Fields:**

   * ``year`` (int) - Year
   * ``month`` (int) - Month (1-12)
   * ``data`` (list[EnergyUsageData]) - Daily data (index 0 = day 1)

EnergyUsageData
---------------

Energy data for a single day.

.. py:class:: EnergyUsageData

   **Fields:**

   * ``heat_element_usage`` (int) - Heat element usage (Wh)
   * ``heat_pump_usage`` (int) - Heat pump usage (Wh)
   * ``heat_element_time`` (int) - Heat element time (hours)
   * ``heat_pump_time`` (int) - Heat pump time (hours)

   **Computed Properties:**

   * ``total_usage`` (int) - heat_element_usage + heat_pump_usage

Time-of-Use Models
==================

TOUInfo
-------

Time-of-Use pricing schedule information.

.. py:class:: TOUInfo

   **Fields:**

   * ``register_path`` (str) - Registration path
   * ``source_type`` (str) - Source type
   * ``controller_id`` (str) - Controller ID
   * ``manufacture_id`` (str) - Manufacturer ID
   * ``name`` (str) - Schedule name
   * ``utility`` (str) - Utility provider name
   * ``zip_code`` (int) - ZIP code
   * ``schedule`` (list[TOUSchedule]) - Seasonal schedules

   **Example:**

   .. code-block:: python

      tou = await api.get_tou_info(mac, additional_value, controller_id)

      print(f"Utility: {tou.utility}")
      print(f"Schedule: {tou.name}")
      print(f"ZIP: {tou.zip_code}")

      for season in tou.schedule:
          print(f"\nSeason {season.season}:")
          for interval in season.intervals:
              print(f"  {interval}")

TOUSchedule
-----------

Seasonal TOU schedule.

.. py:class:: TOUSchedule

   **Fields:**

   * ``season`` (int) - Season identifier/months
   * ``intervals`` (list[dict]) - Time intervals with pricing tiers

MQTT Models
===========

MqttCommand
-----------

Complete MQTT command message.

.. py:class:: MqttCommand

   **Fields:**

   * ``client_id`` (str) - MQTT client ID
   * ``session_id`` (str) - Session ID
   * ``request_topic`` (str) - Request topic
   * ``response_topic`` (str) - Response topic
   * ``request`` (MqttRequest) - Request payload
   * ``protocol_version`` (int) - Protocol version (default: 2)

MqttRequest
-----------

MQTT request payload.

.. py:class:: MqttRequest

   **Fields:**

   * ``command`` (int) - Command code (see CommandCode)
   * ``device_type`` (int) - Device type
   * ``mac_address`` (str) - Device MAC
   * ``additional_value`` (str) - Additional identifier
   * ``mode`` (str, optional) - Mode parameter
   * ``param`` (list[int | float]) - Numeric parameters
   * ``param_str`` (str) - String parameters
   * ``month`` (list[int], optional) - Month list for energy queries
   * ``year`` (int, optional) - Year for energy queries

Best Practices
==============

1. **Use enums for type safety:**

   .. code-block:: python

      # [OK] Type-safe
      from nwp500 import DhwOperationSetting
      await mqtt.set_dhw_mode(device, DhwOperationSetting.ENERGY_SAVER.value)

      # ✗ Magic numbers
      await mqtt.set_dhw_mode(device, 3)

2. **Check feature support:**

   .. code-block:: python

      def on_feature(feature):
          if feature.energy_usage_use:
              # Device supports energy monitoring
              await mqtt.request_energy_usage(device, year, months)

3. **Monitor operation state:**

   .. code-block:: python

      def on_status(status):
          # User's mode preference
          user_mode = status.dhw_operation_setting

          # Current real-time state
          current_state = status.operation_mode

          # These can differ!
          # User sets ENERGY_SAVER, device might be in HEAT_PUMP state

Related Documentation
=====================

* :doc:`auth_client` - Authentication
* :doc:`api_client` - REST API
* :doc:`mqtt_client` - MQTT client
* :doc:`constants` - Command codes and constants
