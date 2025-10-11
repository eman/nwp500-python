Device Feature Fields
=====================

This document lists the fields found in the ``DeviceFeature`` object returned by MQTT device info requests.

The DeviceFeature data contains comprehensive device capabilities, configuration, and firmware information received via MQTT when calling ``request_device_info()``. This data is much more detailed than the basic device information available through the REST API and corresponds to the actual device specifications and capabilities as documented in the official Navien NWP500 Installation and User manuals.

.. list-table::
   :header-rows: 1
   :widths: 15 8 8 49 20

   * - Field Name
     - Type
     - Units
     - Description
     - Conversion Formula
   * - ``countryCode``
     - int
     - None
     - Country/region code where device is certified for operation (1=USA, complies with FCC Part 15 Class B, NSF/ANSI 372)
     - None
   * - ``modelTypeCode``
     - int
     - None
     - Model type identifier: NWP500 series electric heat pump water heater model variant
     - None
   * - ``controlTypeCode``
     - int
     - None
     - Control system type: Advanced digital control with LCD display and WiFi connectivity
     - None
   * - ``volumeCode``
     - int
     - Gallons
     - Tank nominal capacity: 50, 65, or 80 gallons (NWP500-50/65/80 models)
     - None
   * - ``controllerSwVersion``
     - int
     - None
     - Main controller firmware version - controls heat pump, heating elements, and system logic
     - None
   * - ``panelSwVersion``
     - int
     - None
     - Front panel display firmware version - manages LCD display and user interface
     - None
   * - ``wifiSwVersion``
     - int
     - None
     - WiFi module firmware version - handles NaviLink app connectivity and cloud communication
     - None
   * - ``controllerSwCode``
     - int
     - None
     - Controller firmware variant/branch identifier for support and compatibility
     - None
   * - ``panelSwCode``
     - int
     - None
     - Panel firmware variant/branch identifier for display features and UI capabilities
     - None
   * - ``wifiSwCode``
     - int
     - None
     - WiFi firmware variant/branch identifier for communication protocol version
     - None
   * - ``controllerSerialNumber``
     - str
     - None
     - Unique serial number of the main controller board for warranty and service identification
     - None
   * - ``powerUse``
     - int
     - Boolean
     - Power control capability (1=supported) - can be turned on/off via controls (always 1 for NWP500)
     - None
   * - ``holidayUse``
     - int
     - Boolean
     - Vacation mode support (1=supported) - energy-saving mode for 0-99 days with minimal operations
     - None
   * - ``programReservationUse``
     - int
     - Boolean
     - Scheduled operation support (1=supported) - programmable heating schedules and timers
     - None
   * - ``dhwUse``
     - int
     - Boolean
     - Domestic hot water functionality (1=available) - primary function of water heater (always 1)
     - None
   * - ``dhwTemperatureSettingUse``
     - int
     - Boolean
     - Temperature adjustment capability (1=supported) - user can modify target temperature
     - None
   * - ``dhwTemperatureMin``
     - int
     - °F
     - Minimum DHW temperature setting: 95°F (35°C) - safety and efficiency lower limit
     - ``raw + 20``
   * - ``dhwTemperatureMax``
     - int
     - °F
     - Maximum DHW temperature setting: 150°F (65.5°C) - scald protection upper limit
     - ``raw + 20``
   * - ``smartDiagnosticUse``
     - int
     - Boolean
     - Self-diagnostic capability (1=available) - 10-minute startup diagnostic, error code system
     - None
   * - ``wifiRssiUse``
     - int
     - Boolean
     - WiFi signal monitoring (1=supported) - reports signal strength in dBm for connectivity diagnostics
     - None
   * - ``temperatureType``
     - TemperatureUnit
     - Enum
     - Default temperature unit preference (CELSIUS=1, FAHRENHEIT=2) - factory set to Fahrenheit for USA
     - Enum
   * - ``tempFormulaType``
     - int
     - None
     - Temperature calculation method identifier for internal sensor calibration and conversions
     - None
   * - ``energyUsageUse``
     - int
     - Boolean
     - Energy monitoring support (1=available) - tracks kWh consumption for heat pump and electric elements
     - None
   * - ``freezeProtectionUse``
     - int
     - Boolean
     - Freeze protection capability (1=available) - automatic heating when tank drops below threshold
     - None
   * - ``freezeProtectionTempMin``
     - int
     - °F
     - Minimum freeze protection threshold: 43°F (6°C) - factory default activation temperature
     - ``raw + 20``
   * - ``freezeProtectionTempMax``
     - int
     - °F
     - Maximum freeze protection threshold: typically 65°F - user-adjustable upper limit
     - ``raw + 20``
   * - ``mixingValueUse``
     - int
     - Boolean
     - Thermostatic mixing valve support (1=available) - for temperature limiting at point of use
     - None
   * - ``drSettingUse``
     - int
     - Boolean
     - Demand Response support (1=available) - CTA-2045 compliance for utility load management
     - None
   * - ``antiLegionellaSettingUse``
     - int
     - Boolean
     - Anti-Legionella function (1=available) - periodic heating to 140°F (60°C) to prevent bacteria
     - None
   * - ``hpwhUse``
     - int
     - Boolean
     - Heat Pump Water Heater mode (1=supported) - primary efficient heating method using refrigeration cycle
     - None
   * - ``dhwRefillUse``
     - int
     - Boolean
     - Tank refill detection (1=supported) - monitors for "dry fire" conditions during refill
     - None
   * - ``ecoUse``
     - int
     - Boolean
     - ECO safety switch (1=available) - Energy Cut Off high-temperature limit protection
     - None
   * - ``electricUse``
     - int
     - Boolean
     - Electric-only mode (1=supported) - heating element only operation for maximum recovery speed
     - None
   * - ``heatpumpUse``
     - int
     - Boolean
     - Heat pump only mode (1=supported) - most efficient operation using only refrigeration cycle
     - None
   * - ``energySaverUse``
     - int
     - Boolean
     - Energy Saver mode (1=supported) - hybrid efficiency mode balancing speed and efficiency (default)
     - None
   * - ``highDemandUse``
     - int
     - Boolean
     - High Demand mode (1=supported) - hybrid boost mode prioritizing fast recovery over efficiency
     - None

Operation Mode Support Matrix
-----------------------------

The NWP500 supports five primary operation modes as indicated by the capability flags:

.. list-table::
   :header-rows: 1
   :widths: 15 15 15 55

   * - Mode ID
     - Mode Name
     - Capability Flag
     - Description & Performance Characteristics
   * - 1
     - Heat Pump Only
     - ``heatpumpUse``
     - **Most Efficient** - Uses only the heat pump compressor and evaporator. Longest recovery time but highest energy efficiency. Performance varies with ambient temperature and humidity.
   * - 2
     - Energy Saver (Default)
     - ``energySaverUse``
     - **Balanced Efficiency** - Hybrid mode combining heat pump with backup electric elements. Factory default setting balances efficiency with reasonable recovery time.
   * - 3
     - High Demand
     - ``highDemandUse``
     - **Fastest Recovery** - Hybrid mode prioritizing speed over efficiency. Uses heat pump plus more frequent electric element operation for maximum hot water supply.
   * - 4
     - Electric Only
     - ``electricUse``
     - **Emergency/Service Mode** - Uses only 3,755W heating elements (upper and lower, not simultaneously). Least efficient but operates in all conditions. Auto-reverts after 72 hours.
   * - 5
     - Vacation
     - ``holidayUse``
     - **Maximum Energy Savings** - Suspends normal heating for 0-99 days. Only freeze protection and anti-seize operations continue. Heating resumes 9 hours before vacation end.

Hardware Specifications from Manual Cross-Reference
---------------------------------------------------

The device feature data corresponds to these official NWP500 specifications:

**Electrical System**
   * Input: 208-240V AC, 60Hz, 1-Phase
   * Current Draw: 208V (25.9A) / 240V (28.8A) 
   * Circuit Protection: 30A breaker required
   * Heating Elements: 3,755W @ 208V or 5,000W @ 240V (upper and lower)
   * Heat Pump Compressor: 11.6A
   * Evaporator Fan: 0.22A

**Physical Models**
   * NWP500-50: 50 gallon, Ø21.7" × 63" (229 lbs)
   * NWP500-65: 65 gallon, Ø25" × 63" (265 lbs) 
   * NWP500-80: 80 gallon, Ø25" × 71.6" (282 lbs)

**Safety & Compliance Features**
   * FCC ID: P53-EMC3290 (Class B digital device)
   * IC: 23507-EMC3290 (Industry Canada RSS-210)
   * NSF/ANSI 372 certified (lead-free wetted surfaces <0.25%)
   * Temperature & Pressure relief valve (150 psi)
   * ECO (Energy Cut Off) high-limit safety switch

**Smart Features & Connectivity**
   * NaviLink WiFi app connectivity
   * Self-diagnostic system with error codes
   * CTA-2045 Demand Response module support
   * Anti-Legionella periodic disinfection (1-30 day intervals)
   * Programmable operation schedules

Firmware Version Interpretation
-------------------------------

The device returns three separate firmware components for comprehensive system identification:

**Main Controller (``controllerSwVersion``, ``controllerSwCode``)**
   * Manages heat pump compressor, heating elements, temperature sensors
   * Controls operation mode logic and safety interlocks
   * Handles diagnostic routines and error detection
   * Serial number provided for warranty tracking

**Display Panel (``panelSwVersion``, ``panelSwCode``)** 
   * User interface and LCD display management
   * Button input processing and menu navigation
   * Status indicator control and user feedback

**WiFi Module (``wifiSwVersion``, ``wifiSwCode``)**
   * NaviLink cloud connectivity and app communication
   * Wireless network management and security
   * Remote monitoring and control capabilities

Temperature Range Validation
----------------------------

The reported temperature ranges align with official specifications and use the same conversion patterns as DeviceStatus fields:

* **DHW Range**: 95°F to 150°F (factory default: 120°F for safety) - uses ``raw + 20`` conversion
* **Freeze Protection**: Activates at 43°F, prevents tank freezing - uses ``raw + 20`` conversion
* **Anti-Legionella**: Heats to 140°F at programmed intervals (requires mixing valve)
* **Scald Protection**: Built-in limits with recommendation for thermostatic mixing valves

**Conversion Pattern Consistency**: Temperature fields in DeviceFeature use the same ``raw + 20`` 
conversion formula as corresponding fields in DeviceStatus, ensuring consistent temperature 
handling across all device data structures.

Usage Example
-------------

.. code-block:: python

   import asyncio
   from nwp500 import NavienAuthClient, NavienMqttClient, NavienAPIClient

   async def analyze_device_capabilities():
       async with NavienAuthClient("email@example.com", "password") as auth_client:
           # Get device list
           api_client = NavienAPIClient(auth_client)
           devices = await api_client.list_devices()
           device = devices[0]
           
           # Connect MQTT and request device features
           mqtt_client = NavienMqttClient(auth_client)
           await mqtt_client.connect()
           
           # Set up callback to analyze device capabilities
           def analyze_features(feature):
               print(f"=== Device Capability Analysis ===")
               print(f"Model: NWP500-{feature.volumeCode} ({feature.volumeCode} gallon)")
               print(f"Controller FW: v{feature.controllerSwVersion} (Code: {feature.controllerSwCode})")
               print(f"Panel FW: v{feature.panelSwVersion} (Code: {feature.panelSwCode})")
               print(f"WiFi FW: v{feature.wifiSwVersion} (Code: {feature.wifiSwCode})")
               print(f"Serial: {feature.controllerSerialNumber}")
               
               print(f"\n=== Temperature Capabilities ===")
               print(f"DHW Range: {feature.dhwTemperatureMin}°F - {feature.dhwTemperatureMax}°F")
               print(f"Freeze Protection: {feature.freezeProtectionTempMin}°F - {feature.freezeProtectionTempMax}°F")
               print(f"Default Unit: {feature.temperatureType.name}")
               
               print(f"\n=== Supported Operation Modes ===")
               modes = []
               if feature.heatpumpUse: modes.append("Heat Pump Only")
               if feature.energySaverUse: modes.append("Energy Saver (Default)")
               if feature.highDemandUse: modes.append("High Demand") 
               if feature.electricUse: modes.append("Electric Only")
               if feature.holidayUse: modes.append("Vacation Mode")
               print(f"Available: {', '.join(modes)}")
               
               print(f"\n=== Smart Features ===")
               features = []
               if feature.smartDiagnosticUse: features.append("Self-Diagnostics")
               if feature.wifiRssiUse: features.append("WiFi Monitoring")
               if feature.energyUsageUse: features.append("Energy Tracking")
               if feature.antiLegionellaSettingUse: features.append("Anti-Legionella")
               if feature.drSettingUse: features.append("Demand Response")
               if feature.mixingValueUse: features.append("Mixing Valve Support")
               print(f"Available: {', '.join(features)}")
           
           await mqtt_client.subscribe_device_feature(device, analyze_features)
           await mqtt_client.request_device_info(device)
           
           # Wait for response
           await asyncio.sleep(5)
           await mqtt_client.disconnect()

   asyncio.run(analyze_device_capabilities())

See Also
--------

* :doc:`DEVICE_STATUS_FIELDS` - Real-time device status field reference
* :doc:`MQTT_CLIENT` - MQTT client usage guide for device communication
* :doc:`API_CLIENT` - REST API client for device management
* :doc:`ERROR_CODES` - Complete error code reference for diagnostics