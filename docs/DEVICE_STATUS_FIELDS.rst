
Device Status Fields
====================

This document lists the fields found in the ``status`` object of device status messages.

.. list-table::
   :header-rows: 1
   :widths: 10 10 10 36 35

   * - Key
     - Datatype
     - Units
     - Description
     - Conversion Formula
   * - ``command``
     - integer
     - None
     - The command that triggered this status update.
     - None
   * - ``outsideTemperature``
     - integer
     - °F
     - The outdoor/ambient temperature measured by the heat pump.
     - None
   * - ``specialFunctionStatus``
     - integer
     - None
     - Status of special functions (e.g., freeze protection, anti-seize operations).
     - None
   * - ``didReload``
     - bool
     - None
     - Indicates if the device has recently reloaded or restarted.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``errorCode``
     - integer
     - None
     - Error code if any fault is detected. See ERROR_CODES.rst for details.
     - None
   * - ``subErrorCode``
     - integer
     - None
     - Sub error code providing additional error details. See ERROR_CODES.rst for details.
     - None
   * - ``operationMode``
     - OperationMode
     - None
     - The current **actual operational state** of the device (what it's doing RIGHT NOW). Reports status values: 0=Standby, 32=Heat Pump active, 64=Energy Saver active, 96=High Demand active. See Operation Modes section below for the critical distinction between this and ``dhwOperationSetting``.
     - None
   * - ``operationBusy``
     - bool
     - None
     - Indicates if the device is currently performing heating operations (True=busy, False=idle).
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``freezeProtectionUse``
     - bool
     - None
     - Whether freeze protection is active. When tank water temperature falls below 43°F (6°C), the electric heater activates to prevent freezing.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``dhwUse``
     - bool
     - None
     - Domestic Hot Water (DHW) usage status - indicates if hot water is currently being drawn from the tank.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``dhwUseSustained``
     - bool
     - None
     - Sustained DHW usage status - indicates prolonged hot water usage.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``dhwTemperature``
     - integer
     - °F
     - Current Domestic Hot Water (DHW) outlet temperature.
     - ``raw + 20``
   * - ``dhwTemperatureSetting``
     - integer
     - °F
     - Target DHW temperature setting. Range: 95°F (35°C) to 150°F (65.5°C). Default: 120°F (49°C).
     - ``raw + 20``
   * - ``programReservationUse``
     - bool
     - None
     - Whether a program reservation (scheduled operation) is in use.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``smartDiagnostic``
     - integer
     - None
     - Smart diagnostic status for system health monitoring.
     - None
   * - ``faultStatus1``
     - integer
     - None
     - Fault status register 1 - bitfield indicating various fault conditions.
     - None
   * - ``faultStatus2``
     - integer
     - None
     - Fault status register 2 - bitfield indicating additional fault conditions.
     - None
   * - ``wifiRssi``
     - integer
     - dBm
     - WiFi signal strength in dBm (decibel-milliwatts). Typical values: -30 (excellent) to -90 (poor).
     - None
   * - ``ecoUse``
     - bool
     - None
     - Whether ECO (Energy Cut Off) safety feature has been triggered. The ECO switch is a high-temperature safety limit.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``dhwTargetTemperatureSetting``
     - integer
     - °F
     - The target DHW temperature setting (same as dhwTemperatureSetting).
     - ``raw + 20``
   * - ``tankUpperTemperature``
     - integer
     - °F
     - Temperature of the upper part of the tank.
     - ``(raw / 10) * 9/5 + 32`` (decicelsius to Fahrenheit)
   * - ``tankLowerTemperature``
     - integer
     - °F
     - Temperature of the lower part of the tank.
     - ``(raw / 10) * 9/5 + 32`` (decicelsius to Fahrenheit)
   * - ``dischargeTemperature``
     - integer
     - °F
     - Compressor discharge temperature - temperature of refrigerant leaving the compressor.
     - ``(raw / 10) * 9/5 + 32`` (decicelsius to Fahrenheit)
   * - ``suctionTemperature``
     - integer
     - °F
     - Compressor suction temperature - temperature of refrigerant entering the compressor.
     - ``(raw / 10) * 9/5 + 32`` (decicelsius to Fahrenheit)
   * - ``evaporatorTemperature``
     - integer
     - °F
     - Evaporator temperature - temperature where heat is absorbed from ambient air.
     - ``(raw / 10) * 9/5 + 32`` (decicelsius to Fahrenheit)
   * - ``ambientTemperature``
     - integer
     - °F
     - Ambient air temperature measured at the heat pump air intake.
     - ``(raw / 10) * 9/5 + 32`` (decicelsius to Fahrenheit)
   * - ``targetSuperHeat``
     - integer
     - °F
     - Target superheat value - the desired temperature difference ensuring complete refrigerant vaporization.
     - ``(raw / 10) * 9/5 + 32`` (decicelsius to Fahrenheit)
   * - ``compUse``
     - bool
     - None
     - Compressor usage status (True=On, False=Off). The compressor is the main component of the heat pump.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``eevUse``
     - bool
     - None
     - Electronic Expansion Valve (EEV) usage status (True=active, False=inactive). The EEV controls refrigerant flow.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``evaFanUse``
     - bool
     - None
     - Evaporator fan usage status (True=On, False=Off). The fan pulls ambient air through the evaporator coil.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``currentInstPower``
     - integer
     - W
     - Current instantaneous power consumption in Watts. Does not include heating element power when active.
     - None
   * - ``shutOffValveUse``
     - bool
     - None
     - Shut-off valve usage status. The valve controls refrigerant flow in the system.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``conOvrSensorUse``
     - bool
     - None
     - Condensate overflow sensor usage status.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``wtrOvrSensorUse``
     - bool
     - None
     - Water overflow/leak sensor usage status. Triggers error E799 if leak detected.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``dhwChargePer``
     - integer
     - %
     - DHW charge percentage - estimated percentage of hot water capacity available (0-100%).
     - None
   * - ``drEventStatus``
     - integer
     - None
     - Demand Response (DR) event status. Indicates if utility DR commands are active (CTA-2045).
     - None
   * - ``vacationDaySetting``
     - integer
     - days
     - Vacation day setting.
     - None
   * - ``vacationDayElapsed``
     - integer
     - days
     - Elapsed vacation days.
     - None
   * - ``freezeProtectionTemperature``
     - integer
     - °F
     - Freeze protection temperature setting.
     - ``raw + 20``
   * - ``antiLegionellaUse``
     - bool
     - None
     - Whether anti-legionella function is enabled.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``antiLegionellaPeriod``
     - integer
     - days
     - Anti-legionella function period.
     - None
   * - ``antiLegionellaOperationBusy``
     - bool
     - None
     - Whether the anti-legionella function is busy.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``programReservationType``
     - integer
     - None
     - Type of program reservation.
     - None
   * - ``dhwOperationSetting``
     - OperationMode
     - None
     - User's configured DHW operation mode preference. This field uses the same ``OperationMode`` enum as ``operationMode`` but contains command mode values (1=HEAT_PUMP, 2=ELECTRIC, 3=ENERGY_SAVER, 4=HIGH_DEMAND, 5=VACATION, 6=POWER_OFF). When the device is powered off via the power-off command, this field will show 6 (POWER_OFF). This is how to distinguish between "powered off" vs "on but in standby". See the Operation Modes section below for details.
     - None
   * - ``temperatureType``
     - integer
     - None
     - Type of temperature unit (2: Fahrenheit, 1: Celsius).
     - None
   * - ``tempFormulaType``
     - integer
     - None
     - Temperature formula type.
     - None
   * - ``errorBuzzerUse``
     - bool
     - None
     - Whether the error buzzer is enabled.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``currentHeatUse``
     - bool
     - None
     - Current heat usage.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``currentInletTemperature``
     - float
     - °F
     - Current inlet temperature.
     - ``raw / 10.0``
   * - ``currentStatenum``
     - integer
     - None
     - Current state number.
     - None
   * - ``targetFanRpm``
     - integer
     - RPM
     - Target fan RPM.
     - None
   * - ``currentFanRpm``
     - integer
     - RPM
     - Current fan RPM.
     - None
   * - ``fanPwm``
     - integer
     - None
     - Fan PWM value.
     - None
   * - ``dhwTemperature2``
     - integer
     - °F
     - Second DHW temperature reading.
     - ``raw + 20``
   * - ``currentDhwFlowRate``
     - float
     - GPM
     - Current DHW flow rate in Gallons Per Minute.
     - ``raw / 10.0``
   * - ``mixingRate``
     - integer
     - %
     - Mixing valve rate percentage (0-100%). Controls mixing of hot tank water with cold inlet water.
     - None
   * - ``eevStep``
     - integer
     - steps
     - Electronic Expansion Valve (EEV) step position. Valve opening rate expressed as step count.
     - None
   * - ``currentSuperHeat``
     - integer
     - °F
     - Current superheat value - actual temperature difference between suction and evaporator temperatures.
     - ``(raw / 10) * 9/5 + 32`` (decicelsius to Fahrenheit)
   * - ``heatUpperUse``
     - bool
     - None
     - Upper electric heating element usage status (True=On, False=Off). Power: 3,755W @ 208V or 5,000W @ 240V.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``heatLowerUse``
     - bool
     - None
     - Lower electric heating element usage status (True=On, False=Off). Power: 3,755W @ 208V or 5,000W @ 240V.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``scaldUse``
     - bool
     - None
     - Scald protection active status. Displays warning when water temperature reaches levels that could cause scalding.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``airFilterAlarmUse``
     - bool
     - None
     - Air filter alarm usage - indicates if air filter maintenance reminder is enabled.
     - Converted from integer (1=OFF, 2=ON) to bool
   * - ``airFilterAlarmPeriod``
     - integer
     - hours
     - Air filter alarm period setting. Default: 1,000 hours of operation.
     - None
   * - ``airFilterAlarmElapsed``
     - integer
     - hours
     - Elapsed operation time since last air filter maintenance reset.
     - None
   * - ``cumulatedOpTimeEvaFan``
     - integer
     - hours
     - Cumulative operation time of the evaporator fan since installation.
     - None
   * - ``cumulatedDhwFlowRate``
     - integer
     - gallons
     - Cumulative DHW flow - total gallons of hot water delivered since installation.
     - None
   * - ``touStatus``
     - integer
     - None
     - Time of Use (TOU) status - indicates if TOU scheduled operation is active.
     - None
   * - ``hpUpperOnTempSetting``
     - integer
     - °F
     - Heat pump upper on temperature setting.
     - ``raw + 20``
   * - ``hpUpperOffTempSetting``
     - integer
     - °F
     - Heat pump upper off temperature setting.
     - ``raw + 20``
   * - ``hpLowerOnTempSetting``
     - integer
     - °F
     - Heat pump lower on temperature setting.
     - ``raw + 20``
   * - ``hpLowerOffTempSetting``
     - integer
     - °F
     - Heat pump lower off temperature setting.
     - ``raw + 20``
   * - ``heUpperOnTempSetting``
     - integer
     - °F
     - Heater element upper on temperature setting.
     - ``raw + 20``
   * - ``heUpperOffTempSetting``
     - integer
     - °F
     - Heater element upper off temperature setting.
     - ``raw + 20``
   * - ``heLowerOnTempSetting``
     - integer
     - °F
     - Heater element lower on temperature setting.
     - ``raw + 20``
   * - ``heLowerOffTempSetting``
     - integer
     - °F
     - Heater element lower off temperature setting.
     - ``raw + 20``
   * - ``hpUpperOnDiffTempSetting``
     - float
     - °F
     - Heat pump upper on differential temperature setting.
     - ``raw / 10.0``
   * - ``hpUpperOffDiffTempSetting``
     - float
     - °F
     - Heat pump upper off differential temperature setting.
     - ``raw / 10.0``
   * - ``hpLowerOnDiffTempSetting``
     - float
     - °F
     - Heat pump lower on differential temperature setting.
     - ``raw / 10.0``
   * - ``hpLowerOffDiffTempSetting``
     - float
     - °F
     - Heat pump lower off differential temperature setting.
     - ``raw / 10.0``
   * - ``heUpperOnDiffTempSetting``
     - float
     - °F
     - Heater element upper on differential temperature setting.
     - ``raw / 10.0``
   * - ``heUpperOffDiffTempSetting``
     - float
     - °F
     - Heater element upper off differential temperature setting.
     - ``raw / 10.0``
   * - ``heLowerOnTDiffempSetting``
     - float
     - °F
     - Heater element lower on differential temperature setting.
     - ``raw / 10.0``
   * - ``heLowerOffDiffTempSetting``
     - float
     - °F
     - Heater element lower off differential temperature setting.
     - ``raw / 10.0``
   * - ``heatMinOpTemperature``
     - float
     - °F
     - Minimum operating temperature for the heating element. This sets the lower threshold at which the heating element can operate.
     - ``raw + 20``
   * - ``drOverrideStatus``
     - integer
     - None
     - Demand Response override status. User can override DR commands for up to 72 hours.
     - None
   * - ``touOverrideStatus``
     - integer
     - None
     - Time of Use override status. User can temporarily override TOU schedule.
     - None
   * - ``totalEnergyCapacity``
     - integer
     - Wh
     - Total energy capacity of the tank in Watt-hours.
     - None
   * - ``availableEnergyCapacity``
     - integer
     - Wh
     - Available energy capacity - remaining hot water energy available in Watt-hours.
     - None

DHW Operation Setting Modes
----------------------------

The ``dhwOperationSetting`` field is an integer that maps to the following modes. These modes balance energy efficiency and recovery time based on user needs.

.. list-table::
   :header-rows: 1
   :widths: 10 20 15 15 40

   * - Value
     - Mode
     - Recovery Time
     - Energy Efficiency
     - Description
   * - 1
     - HEAT_PUMP
     - Very Slow
     - High
     - Most energy-efficient mode, using only the heat pump. Recovery time varies with ambient temperature and humidity. Higher ambient temperature and humidity improve efficiency and reduce recovery time.
   * - 2
     - ELECTRIC
     - Fast
     - Very Low
     - Uses only upper and lower electric heaters (not simultaneously). Least energy-efficient with shortest recovery time. Can operate continuously for up to 72 hours before automatically reverting to previous mode.
   * - 3
     - ENERGY_SAVER
     - Fast
     - Very High
     - Default mode. Combines the heat pump and electric heater for balanced efficiency and recovery time. Heat pump is primarily used with electric heater for backup. Applied during initial shipment and factory reset.
   * - 4
     - HIGH_DEMAND
     - Very Fast
     - Low
     - Combines heat pump and electric heater with more frequent use of electric heater for faster recovery. Suitable when higher hot water supply is needed.
   * - 5
     - VACATION
     - None
     - Very High
     - Suspends heating to save energy during absences (0-99 days). Only minimal operations like freeze protection and anti-seize are performed. Heating resumes 9 hours before the vacation period ends.
   * - 6
     - POWER_OFF
     - None
     - None
     - Device is powered off. This value appears in ``dhwOperationSetting`` when the device has been powered off via the power-off command.


Operation Mode Status Values
-----------------------------

The following ``operationMode`` values appear in status messages from the device. These values reflect the device's actual operational state (what it's doing right now):

.. list-table::
   :header-rows: 1
   :widths: 10 30 60

   * - Value
     - Mode
     - Notes
   * - 0
     - STANDBY
     - Device is idle, not actively heating. Can occur when device is powered off OR when it's on but not heating. Check ``dhwOperationSetting`` for value 6 (``POWER_OFF``) to distinguish between these states.
   * - 32
     - HEAT_PUMP_MODE
     - Heat pump is actively running to heat water.
   * - 64
     - HYBRID_EFFICIENCY_MODE
     - Device is actively heating in Energy Saver mode (hybrid efficiency).
   * - 96
     - HYBRID_BOOST_MODE
     - Device is actively heating in High Demand mode (hybrid boost).

Understanding operationMode vs dhwOperationSetting
---------------------------------------------------

These two fields serve different purposes and it's critical to understand their relationship:

Field Definitions
^^^^^^^^^^^^^^^^^

**dhwOperationSetting** (OperationMode enum with command values 1-5)
  The user's **configured mode preference** - what heating mode the device should use when it needs to heat water. This is set via the ``dhw-mode`` command and persists until changed by the user or device.
  
  * Type: ``OperationMode`` enum
  * Values: 
    
    * 1 = ``HEAT_PUMP`` (Heat Pump Only)
    * 2 = ``ELECTRIC`` (Electric Only)
    * 3 = ``ENERGY_SAVER`` (Hybrid: Efficiency)
    * 4 = ``HIGH_DEMAND`` (Hybrid: Boost)
    * 5 = ``VACATION`` (Vacation mode)
    * 6 = ``POWER_OFF`` (Device is powered off)
  
  * Set by: User via app, CLI, or MQTT command
  * Changes: Only when user explicitly changes the mode or powers device off/on
  * Meaning: "When heating is needed, use this mode" OR "I'm powered off" (if value is 6)
  * Value 6 (``POWER_OFF``) indicates the device was powered off via the power-off command. This is how to distinguish between "powered off" and "on but idle".

**operationMode** (OperationMode enum with status values 0, 32, 64, 96)
  The device's **current actual operational state** - what the device is doing RIGHT NOW. This reflects real-time operation and changes automatically based on whether the device is idle or actively heating.
  
  * Type: ``OperationMode`` enum
  * Values:
    
    * 0 = ``STANDBY`` (Idle, not heating)
    * 32 = ``HEAT_PUMP_MODE`` (Heat Pump actively running)
    * 64 = ``HYBRID_EFFICIENCY_MODE`` (Energy Saver actively heating)
    * 96 = ``HYBRID_BOOST_MODE`` (High Demand actively heating)
  
  * Set by: Device automatically based on heating demand
  * Changes: Dynamically as device starts/stops heating
  * Meaning: "This is what I'm doing right now"
  * **Note**: This field shows ``STANDBY`` (0) both when device is powered off AND when it's on but not heating. Check ``dhwOperationSetting`` to determine if device is actually powered off (value 6).

Key Relationship
^^^^^^^^^^^^^^^^

The relationship between these fields can be summarized as:

* ``dhwOperationSetting`` = "What mode to use when heating"
* ``operationMode`` = "Am I heating right now, and if so, how?"

A device can be **idle** (``operationMode = STANDBY``) while still being **configured** for a specific heating mode (``dhwOperationSetting = ENERGY_SAVER``). When the tank temperature drops and heating begins, ``operationMode`` will change to reflect active heating (e.g., ``HYBRID_EFFICIENCY_MODE``), but ``dhwOperationSetting`` remains unchanged.

Real-World Examples
^^^^^^^^^^^^^^^^^^^

**Example 1: Energy Saver Mode, Tank is Hot**
  ::

    dhwOperationSetting = 3 (ENERGY_SAVER)    # Configured mode
    operationMode = 0 (STANDBY)                # Currently idle
    dhwChargePer = 100                         # Tank is fully charged
    
  *Interpretation:* Device is configured for Energy Saver mode, but water is already at temperature so no heating is occurring.

**Example 2: Energy Saver Mode, Actively Heating**
  ::

    dhwOperationSetting = 3 (ENERGY_SAVER)           # Configured mode
    operationMode = 64 (HYBRID_EFFICIENCY_MODE)      # Actively heating
    operationBusy = true                             # Heating in progress
    dhwChargePer = 75                                # Tank at 75%
    
  *Interpretation:* Device is using Energy Saver mode to heat the tank, currently at 75% charge.

**Example 3: High Demand Mode, Heat Pump Running**
  ::

    dhwOperationSetting = 4 (HIGH_DEMAND)      # Configured mode
    operationMode = 32 (HEAT_PUMP_MODE)        # Heat pump active
    compUse = true                             # Compressor running
    
  *Interpretation:* Device is configured for High Demand but is currently running just the heat pump component (hybrid heating will engage electric elements as needed).

**Example 4: Device Powered Off**
  ::

    dhwOperationSetting = 6 (POWER_OFF)        # Device powered off
    operationMode = 0 (STANDBY)                # Currently idle
    operationBusy = false                      # No heating
    
  *Interpretation:* Device was powered off using the power-off command. Although ``operationMode`` shows ``STANDBY`` (same as an idle device), the ``dhwOperationSetting`` value of 6 indicates it's actually powered off, not just idle.

Displaying Status in a User Interface
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For user-facing applications, follow these guidelines:

**Primary Mode Display**
  Use ``dhwOperationSetting`` to show the user's configured mode preference. This is what users expect to see as "the current mode" because it represents their selection.
  
  **Important**: Check for value 6 (``POWER_OFF``) first to show "Off" or "Powered Off" status.

  Example display::

    Mode: Energy Saver      [when dhwOperationSetting = 1-5]
    Mode: Off               [when dhwOperationSetting = 6]

**Status Indicator**
  Use ``operationMode`` to show real-time operational status:

  * ``STANDBY`` (0): Show "Idle" or "Standby" indicator (but check ``dhwOperationSetting`` for power-off state)
  * ``HEAT_PUMP_MODE`` (32): Show "Heating (Heat Pump)" or heating indicator
  * ``HYBRID_EFFICIENCY_MODE`` (64): Show "Heating (Energy Saver)" or heating indicator
  * ``HYBRID_BOOST_MODE`` (96): Show "Heating (High Demand)" or heating indicator

**Combined Display Examples**
  ::

    # Device on and idle
    Mode: Energy Saver
    Status: Idle ○
    Tank: 100%
    
    # Device on and heating
    Mode: Energy Saver
    Status: Heating ●
    Tank: 75%
    
    # Device powered off
    Mode: Off
    Status: Powered Off
    Tank: 100%

**Code Example**
  .. code-block:: python

    def format_mode_display(status: DeviceStatus) -> dict:
        """Format mode and status for UI display."""
        
        # Check if device is powered off first
        if status.dhwOperationSetting == OperationMode.POWER_OFF:
            return {
                'configured_mode': 'Off',
                'operational_state': 'Powered Off',
                'is_heating': False,
                'is_powered_on': False,
                'tank_charge': status.dhwChargePer,
            }
        
        # User's configured mode (what they selected)
        configured_mode = status.dhwOperationSetting.name.replace('_', ' ').title()
        
        # Current operational state
        if status.operationMode == OperationMode.STANDBY:
            operational_state = "Idle"
            is_heating = False
        elif status.operationMode == OperationMode.HEAT_PUMP_MODE:
            operational_state = "Heating (Heat Pump)"
            is_heating = True
        elif status.operationMode == OperationMode.HYBRID_EFFICIENCY_MODE:
            operational_state = "Heating (Energy Saver)"
            is_heating = True
        elif status.operationMode == OperationMode.HYBRID_BOOST_MODE:
            operational_state = "Heating (High Demand)"
            is_heating = True
        else:
            operational_state = "Unknown"
            is_heating = False
        
        return {
            'configured_mode': configured_mode,       # "Energy Saver"
            'operational_state': operational_state,   # "Idle" or "Heating..."
            'is_heating': is_heating,                 # True/False
            'is_powered_on': True,                    # Device is on
            'tank_charge': status.dhwChargePer,       # 0-100
        }

**Display Notes**

1. **Never display operationMode as "the mode"** - users don't care that the device is in "HYBRID_EFFICIENCY_MODE", they want to know it's set to "Energy Saver"

2. **Do use operationMode for heating indicators** - it tells you whether the device is actively heating right now

3. **Mode changes affect dhwOperationSetting** - when a user changes the mode, you're setting ``dhwOperationSetting``

4. **operationMode changes automatically** - you cannot directly set this; it changes based on device operation

5. **Both fields use OperationMode enum** - but different value ranges (1-6 for dhwOperationSetting, 0/32/64/96 for operationMode)

6. **Power off detection** - Check if ``dhwOperationSetting == 6`` (``POWER_OFF``) to determine if device is powered off vs just idle

Technical Notes
---------------

**Temperature Sensors:**

* Tank temperature sensors operate within -4°F to 149°F (-20°C to 65°C)
* Outside normal range, system may operate with reduced capacity using opposite heating element
* All tank temperature readings use conversion formula: ``display_temp = raw + 20``

**Heating Elements:**

* Upper and lower heating elements: 3,755W @ 208V or 5,000W @ 240V
* Elements do not operate simultaneously in Electric mode
* Heating elements activate for freeze protection when tank < 43°F (6°C)

**Heat Pump Specifications:**

* Refrigerant: R-134a (28.2 oz / 800 g)
* Compressor: 208V (25.9A MCA) / 240V (28.8A MCA)
* Evaporator fan: 0.22A
* Discharge pressure: 2.654 MPa / 385 PSIG
* Suction pressure: 1.724 MPa / 250 PSIG

**Safety Features:**

* Freeze Protection: Activates at 43°F (6°C), default setting
* ECO (Energy Cut Off): High-temperature safety limit switch
* Condensate Level Sensor: Detects overflow, triggers E990
* Water Leak Detection: Triggers E799 if leak detected
* T&P Relief Valve: Temperature & Pressure safety valve

**Communication:**

* WiFi RSSI typical range: -30 dBm (excellent) to -90 dBm (poor)
* CTA-2045 Demand Response support
* Maximum 30A circuit breaker rating

See Also
--------

* :doc:`ERROR_CODES` - Complete error code reference with diagnostics
* :doc:`ENERGY_MONITORING` - Energy consumption tracking
* :doc:`MQTT_MESSAGES` - Status message format details
