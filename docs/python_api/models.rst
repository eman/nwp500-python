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
          if status.dhwOperationSetting == DhwOperationSetting.ENERGY_SAVER:
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
          mode = status.operationMode

          if mode == CurrentOperationMode.IDLE:
              print("Device idle")
          elif mode == CurrentOperationMode.HEAT_PUMP:
              print(f"Heat pump running at {status.currentInstPower}W")
          elif mode == CurrentOperationMode.ELECTRIC_HEATER:
              print(f"Electric heater at {status.currentInstPower}W")
          elif mode == CurrentOperationMode.HEAT_PUMP_AND_HEATER:
              print(f"Both running at {status.currentInstPower}W")

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
          if status.temperatureType == TemperatureUnit.FAHRENHEIT:
              print(f"Temperature: {status.dhwTemperature}°F")
          else:
              print(f"Temperature: {status.dhwTemperature}°C")

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
          print("Status: Online ✓")
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
              print(f"  ⚠️  Update available: {fw.downloaded_version}")
          else:
              print(f"  ✓ Up to date")

Status Models
=============

DeviceStatus
------------

Complete real-time device status with 100+ fields.

.. py:class:: DeviceStatus

   **Key Temperature Fields:**

   * ``dhwTemperature`` (float) - Current water temperature (°F or °C)
   * ``dhwTemperatureSetting`` (float) - Target temperature setting
   * ``dhwTargetTemperatureSetting`` (float) - Target with offsets applied
   * ``tankUpperTemperature`` (float) - Upper tank sensor
   * ``tankLowerTemperature`` (float) - Lower tank sensor
   * ``currentInletTemperature`` (float) - Cold water inlet temperature
   * ``outsideTemperature`` (float) - Outdoor temperature
   * ``ambientTemperature`` (float) - Ambient air temperature

   .. note::
      Temperature display values are 20°F higher than message values.
      Display: 140°F = Message: 120°F

   **Key Power/Energy Fields:**

   * ``currentInstPower`` (float) - Current power consumption (Watts)
   * ``totalEnergyCapacity`` (float) - Total energy capacity (%)
   * ``availableEnergyCapacity`` (float) - Available energy (%)
   * ``dhwChargePer`` (float) - DHW charge percentage

   **Operation Mode Fields:**

   * ``operationMode`` (CurrentOperationMode) - Current operational state
   * ``dhwOperationSetting`` (DhwOperationSetting) - User's mode preference
   * ``temperatureType`` (TemperatureUnit) - Temperature unit

   **Boolean Status Fields:**

   * ``operationBusy`` (bool) - Device actively heating water
   * ``dhwUse`` (bool) - Water being used (short-term detection)
   * ``dhwUseSustained`` (bool) - Water being used (sustained)
   * ``compUse`` (bool) - Compressor/heat pump running
   * ``heatUpperUse`` (bool) - Upper electric heater active
   * ``heatLowerUse`` (bool) - Lower electric heater active
   * ``evaFanUse`` (bool) - Evaporator fan running
   * ``antiLegionellaUse`` (bool) - Anti-Legionella enabled
   * ``antiLegionellaOperationBusy`` (bool) - Anti-Legionella cycle active
   * ``programReservationUse`` (bool) - Reservation schedule enabled
   * ``freezeProtectionUse`` (bool) - Freeze protection enabled

   **Error/Diagnostic Fields:**

   * ``errorCode`` (int) - Error code (0 = no error)
   * ``subErrorCode`` (int) - Sub-error code
   * ``smartDiagnostic`` (int) - Smart diagnostic status
   * ``faultStatus1`` (int) - Fault status flags
   * ``faultStatus2`` (int) - Additional fault flags

   **Network/Communication:**

   * ``wifiRssi`` (int) - WiFi signal strength (dBm)

   **Vacation/Schedule:**

   * ``vacationDaySetting`` (int) - Vacation days configured
   * ``vacationDayElapsed`` (int) - Vacation days elapsed
   * ``antiLegionellaPeriod`` (int) - Anti-Legionella cycle period

   **Time-of-Use (TOU):**

   * ``touStatus`` (int) - TOU status
   * ``touOverrideStatus`` (int) - TOU override status

   **Heat Pump Detailed Status:**

   * ``targetFanRpm`` (int) - Target fan RPM
   * ``currentFanRpm`` (int) - Current fan RPM
   * ``fanPwm`` (int) - Fan PWM duty cycle
   * ``mixingRate`` (float) - Mixing valve rate
   * ``eevStep`` (int) - Electronic expansion valve position
   * ``dischargeTemperature`` (float) - Compressor discharge temp
   * ``suctionTemperature`` (float) - Compressor suction temp
   * ``evaporatorTemperature`` (float) - Evaporator temperature
   * ``targetSuperHeat`` (float) - Target superheat
   * ``currentSuperHeat`` (float) - Current superheat

   **Example:**

   .. code-block:: python

      def on_status(status):
          # Temperature monitoring
          print(f"Water: {status.dhwTemperature}°F")
          print(f"Target: {status.dhwTemperatureSetting}°F")
          print(f"Upper Tank: {status.tankUpperTemperature}°F")
          print(f"Lower Tank: {status.tankLowerTemperature}°F")

          # Power consumption
          print(f"Power: {status.currentInstPower}W")
          print(f"Energy: {status.availableEnergyCapacity}%")

          # Operation mode
          print(f"Mode: {status.dhwOperationSetting.name}")
          print(f"State: {status.operationMode.name}")

          # Active heating
          if status.operationBusy:
              print("Heating water:")
              if status.compUse:
                  print("  - Heat pump running")
              if status.heatUpperUse:
                  print("  - Upper heater active")
              if status.heatLowerUse:
                  print("  - Lower heater active")

          # Water usage detection
          if status.dhwUse:
              print("Water usage detected (short-term)")
          if status.dhwUseSustained:
              print("Water usage detected (sustained)")

          # Errors
          if status.errorCode != 0:
              print(f"ERROR: {status.errorCode}")
              if status.subErrorCode != 0:
                  print(f"  Sub-error: {status.subErrorCode}")

DeviceFeature
-------------

Device capabilities, features, and firmware information.

.. py:class:: DeviceFeature

   **Firmware Version Fields:**

   * ``controllerSwVersion`` (int) - Controller firmware version
   * ``panelSwVersion`` (int) - Panel firmware version
   * ``wifiSwVersion`` (int) - WiFi module firmware version
   * ``controllerSwCode`` (int) - Controller software code
   * ``panelSwCode`` (int) - Panel software code
   * ``wifiSwCode`` (int) - WiFi software code
   * ``controllerSerialNumber`` (str) - Controller serial number

   **Device Configuration:**

   * ``countryCode`` (int) - Country code
   * ``modelTypeCode`` (int) - Model type
   * ``controlTypeCode`` (int) - Control type
   * ``volumeCode`` (int) - Tank volume code
   * ``tempFormulaType`` (int) - Temperature formula type
   * ``temperatureType`` (TemperatureUnit) - Temperature unit

   **Temperature Limits:**

   * ``dhwTemperatureMin`` (int) - Minimum DHW temperature
   * ``dhwTemperatureMax`` (int) - Maximum DHW temperature
   * ``freezeProtectionTempMin`` (int) - Min freeze protection temp
   * ``freezeProtectionTempMax`` (int) - Max freeze protection temp

   **Feature Flags (all int, 0=disabled, 1=enabled):**

   * ``powerUse`` - Power control supported
   * ``dhwUse`` - DHW functionality
   * ``dhwTemperatureSettingUse`` - Temperature control
   * ``energyUsageUse`` - Energy monitoring supported
   * ``antiLegionellaSettingUse`` - Anti-Legionella supported
   * ``programReservationUse`` - Reservation scheduling supported
   * ``freezeProtectionUse`` - Freeze protection available
   * ``heatpumpUse`` - Heat pump mode available
   * ``electricUse`` - Electric mode available
   * ``energySaverUse`` - Energy Saver mode available
   * ``highDemandUse`` - High Demand mode available
   * ``smartDiagnosticUse`` - Smart diagnostics available
   * ``wifiRssiUse`` - WiFi signal strength available
   * ``holidayUse`` - Holiday/vacation mode
   * ``mixingValueUse`` - Mixing valve
   * ``drSettingUse`` - Demand response
   * ``dhwRefillUse`` - DHW refill
   * ``ecoUse`` - Eco mode

   **Example:**

   .. code-block:: python

      def on_feature(feature):
          print(f"Serial: {feature.controllerSerialNumber}")
          print(f"Firmware: {feature.controllerSwVersion}")
          print(f"WiFi: {feature.wifiSwVersion}")

          print(f"\nTemperature Range:")
          print(f"  Min: {feature.dhwTemperatureMin}°F")
          print(f"  Max: {feature.dhwTemperatureMax}°F")

          print(f"\nSupported Features:")
          if feature.energyUsageUse:
              print("  ✓ Energy monitoring")
          if feature.antiLegionellaSettingUse:
              print("  ✓ Anti-Legionella")
          if feature.programReservationUse:
              print("  ✓ Reservations")
          if feature.heatpumpUse:
              print("  ✓ Heat pump mode")
          if feature.electricUse:
              print("  ✓ Electric mode")
          if feature.energySaverUse:
              print("  ✓ Energy Saver mode")
          if feature.highDemandUse:
              print("  ✓ High Demand mode")

Energy Models
=============

EnergyUsageResponse
-------------------

Complete energy usage response with daily breakdown.

.. py:class:: EnergyUsageResponse

   **Fields:**

   * ``deviceType`` (int) - Device type
   * ``macAddress`` (str) - Device MAC
   * ``additionalValue`` (str) - Additional identifier
   * ``typeOfUsage`` (int) - Usage type code
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
                      print(f"    HP: {day.hpUsage} Wh ({day.hpTime}h)")
                      print(f"    HE: {day.heUsage} Wh ({day.heTime}h)")

EnergyUsageTotal
----------------

Summary totals for energy usage.

.. py:class:: EnergyUsageTotal

   **Fields:**

   * ``heUsage`` (int) - Total heat element usage (Wh)
   * ``hpUsage`` (int) - Total heat pump usage (Wh)
   * ``heTime`` (int) - Total heat element time (hours)
   * ``hpTime`` (int) - Total heat pump time (hours)

   **Computed Properties:**

   * ``total_usage`` (int) - heUsage + hpUsage
   * ``heat_pump_percentage`` (float) - (hpUsage / total) × 100
   * ``heat_element_percentage`` (float) - (heUsage / total) × 100

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

   * ``heUsage`` (int) - Heat element usage (Wh)
   * ``hpUsage`` (int) - Heat pump usage (Wh)
   * ``heTime`` (int) - Heat element time (hours)
   * ``hpTime`` (int) - Heat pump time (hours)

   **Computed Properties:**

   * ``total_usage`` (int) - heUsage + hpUsage

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

   * ``clientID`` (str) - MQTT client ID
   * ``sessionID`` (str) - Session ID
   * ``requestTopic`` (str) - Request topic
   * ``responseTopic`` (str) - Response topic
   * ``request`` (MqttRequest) - Request payload
   * ``protocolVersion`` (int) - Protocol version (default: 2)

MqttRequest
-----------

MQTT request payload.

.. py:class:: MqttRequest

   **Fields:**

   * ``command`` (int) - Command code (see CommandCode)
   * ``deviceType`` (int) - Device type
   * ``macAddress`` (str) - Device MAC
   * ``additionalValue`` (str) - Additional identifier
   * ``mode`` (str, optional) - Mode parameter
   * ``param`` (list[int | float]) - Numeric parameters
   * ``paramStr`` (str) - String parameters
   * ``month`` (list[int], optional) - Month list for energy queries
   * ``year`` (int, optional) - Year for energy queries

Best Practices
==============

1. **Use enums for type safety:**

   .. code-block:: python

      # ✓ Type-safe
      from nwp500 import DhwOperationSetting
      await mqtt.set_dhw_mode(device, DhwOperationSetting.ENERGY_SAVER.value)

      # ✗ Magic numbers
      await mqtt.set_dhw_mode(device, 3)

2. **Check feature support:**

   .. code-block:: python

      def on_feature(feature):
          if feature.energyUsageUse:
              # Device supports energy monitoring
              await mqtt.request_energy_usage(device, year, months)

3. **Handle temperature conversions:**

   .. code-block:: python

      # Display temperature is 20°F higher than message value
      display_temp = 140
      message_value = display_temp - 20  # 120

      # Or use convenience method
      await mqtt.set_dhw_temperature_display(device, 140)

4. **Monitor operation state:**

   .. code-block:: python

      def on_status(status):
          # User's mode preference
          user_mode = status.dhwOperationSetting

          # Current real-time state
          current_state = status.operationMode

          # These can differ!
          # User sets ENERGY_SAVER, device might be in HEAT_PUMP state

Related Documentation
=====================

* :doc:`auth_client` - Authentication
* :doc:`api_client` - REST API
* :doc:`mqtt_client` - MQTT client
* :doc:`constants` - Command codes and constants
