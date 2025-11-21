Data Conversions and Units Reference
====================================

This document provides comprehensive details on all data conversions applied to device status messages, field units, and the meaning of various data structures.

.. warning::
   This document describes the underlying protocol details. Most users should use the
   Python client library (:doc:`../python_api/models`) instead of implementing
   conversions manually.

Overview of Conversion Types
----------------------------

The NWP500 device encodes data in a compact binary format. The Python client automatically converts these raw values to user-friendly representations using the following conversion strategies:

Raw Encoding Strategies
^^^^^^^^^^^^^^^^^^^^^^^

The device uses several encoding schemes to minimize transmission overhead:

1. **Half-degree Celsius to Fahrenheit** (HalfCelsiusToF)
   - Applied to most temperature fields that are not scaled by other factors.
   - Formula: ``displayed_value = (raw_value / 2.0) * 9/5 + 32``
   - Purpose: Converts raw values, which are in half-degrees Celsius, to Fahrenheit.
   - Example: Raw 122 -> (122 / 2) * 9/5 + 32 = 141.8°F

2. **Decicelsius to Fahrenheit** (DeciCelsiusToF)
   - Applied to refrigerant circuit and tank temperature sensors.
   - Formula: ``displayed_value = (raw_value / 10.0) * 9/5 + 32``
   - Purpose: Converts raw values, which are in tenths of degrees Celsius, to Fahrenheit.
   - Example: Raw 489 -> (489 / 10) * 9/5 + 32 = 120.0°F

3. **Tenths Encoding** (div_10)
   - Applied to decimal precision values
   - Formula: ``displayed_value = raw_value / 10.0``
   - Purpose: Preserve decimal precision in integer storage
   - Common for flow rates and differential temperatures
   - Example: Raw 125 → 12.5 GPM

4. **Boolean Encoding** (device_bool)
   - Applied to all status flags
   - Formula: ``displayed_value = (raw_value == 2)``
   - Encoding: 1 or 0 = False, 2 = True
   - Purpose: Compact boolean representation

5. **Enumeration Encoding** (enum)
   - Applied to mode and state fields
   - Direct value-to-enum mapping
   - Example: 0=Standby, 32=Heat Pump, 64=Hybrid Efficiency, 96=Hybrid Boost

Temperature Fields Reference
----------------------------

All temperature fields in this section are shown with their applied conversions. Stored values are in °F unless otherwise specified.

DHW (Domestic Hot Water) Temperatures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``dhwTemperature``
     - HalfCelsiusToF
     - °F
     - **Current outlet temperature** of hot water being delivered to fixtures. Real-time measurement. Typically 90-150°F.
   * - ``dhwTemperature2``
     - HalfCelsiusToF
     - °F
     - **Secondary DHW temperature sensor** reading (redundancy/averaging). May differ slightly from primary sensor during temperature transitions.
   * - ``dhwTemperatureSetting``
     - HalfCelsiusToF
     - °F
     - **User-configured target temperature** for DHW delivery. Adjustable range: 95-150°F. Default: 120°F. This is the setpoint users configure in the app.
   * - ``currentInletTemperature``
     - div_10
     - °F
     - **Cold water inlet temperature** to the water heater. Affects heating performance and recovery time. Typically 40-80°F depending on season and location.
   * - ``dhwTargetTemperatureSetting``
     - HalfCelsiusToF
     - °F
     - **Duplicate of dhwTemperatureSetting** for legacy API compatibility.

Tank Temperature Sensors
^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``tankUpperTemperature``
     - DeciCelsiusToF
     - °F
     - **Upper tank sensor temperature**. Indicates stratification - hot water at top for quick delivery. Typically hottest point in tank.
   * - ``tankLowerTemperature``
     - DeciCelsiusToF
     - °F
     - **Lower tank sensor temperature**. Indicates bulk tank temperature and heating progress. Typically cooler than upper sensor.

**Tank Temperature Stratification**: Well-insulated tanks maintain significant temperature differences between upper (hot, recently drawn from) and lower (cooler, being heated) regions. The device uses this stratification to optimize heating efficiency.

Refrigerant Circuit Temperatures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These temperatures monitor the heat pump refrigerant circuit health and performance. Understanding these helps diagnose efficiency issues:

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``dischargeTemperature``
     - DeciCelsiusToF
     - °F
     - **Compressor discharge temperature**. Temperature of refrigerant exiting the compressor. Typically 120-180°F. High values indicate high system pressure; low values indicate efficiency issues.
   * - ``suctionTemperature``
     - DeciCelsiusToF
     - °F
     - **Compressor suction temperature**. Temperature of refrigerant entering the compressor. Typically 40-60°F. Affects superheat calculation.
   * - ``evaporatorTemperature``
     - DeciCelsiusToF
     - °F
     - **Evaporator coil temperature**. Where heat is extracted from ambient air. Typically 20-50°F. Lower outdoor air temperature reduces evaporator efficiency.
   * - ``ambientTemperature``
     - DeciCelsiusToF
     - °F
     - **Ambient air temperature** measured at heat pump inlet. Directly affects system performance. At freezing (32°F), heat pump efficiency drops significantly.
   * - ``targetSuperHeat``
     - DeciCelsiusToF
     - °F
     - **Target superheat setpoint**. Desired temperature difference between suction and evaporator ensuring complete refrigerant vaporization. Typically 10-20°F.
   * - ``currentSuperHeat``
     - DeciCelsiusToF
     - °F
     - **Measured superheat value**. Actual temperature difference. Deviation from target indicates EEV (Electronic Expansion Valve) control issues.

**Refrigerant Circuit Diagnostics**:
- If ``currentSuperHeat >> targetSuperHeat``: EEV may be stuck open (undercharge symptoms)
- If ``currentSuperHeat << targetSuperHeat``: EEV may be stuck closed (overcharge symptoms)
- If ``dischargeTemperature`` extremely high (>200°F): System may be in bypass protection
- If ``ambientTemperature`` below 32°F: Heat pump COP (efficiency) significantly reduced

Heating Element Control Temperatures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Electric heating elements are controlled via thermostat ranges. Two sensors (upper and lower tank) allow two-stage heating:

.. list-table::
   :header-rows: 1
   :widths: 30 10 15 45

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``heUpperOnTempSetting``
     - HalfCelsiusToF
     - °F
     - **Upper element ON threshold**. Upper tank temp must fall below this to activate upper heating element.
   * - ``heUpperOffTempSetting``
     - HalfCelsiusToF
     - °F
     - **Upper element OFF threshold**. Upper tank temp rises above this to deactivate upper element (hysteresis).
   * - ``heLowerOnTempSetting``
     - HalfCelsiusToF
     - °F
     - **Lower element ON threshold**. Lower tank temp must fall below this to activate lower element.
   * - ``heLowerOffTempSetting``
     - HalfCelsiusToF
     - °F
     - **Lower element OFF threshold**. Lower tank temp rises above this to deactivate lower element.
   * - ``heUpperOnDiffTempSetting``
     - div_10
     - °F
     - **Upper element differential** (ON-OFF difference). Hysteresis width to prevent rapid cycling. Typically 2-5°F.
   * - ``heUpperOffDiffTempSetting``
     - div_10
     - °F
     - **Upper element differential** variation (advanced tuning). May vary based on mode.
   * - ``heLowerOnDiffTempSetting``
     - div_10
     - °F
     - **Lower element differential** (ON-OFF difference).
   * - ``heLowerOffDiffTempSetting``
     - div_10
     - °F
     - **Lower element differential** variation.
   * - ``heatMinOpTemperature``
     - HalfCelsiusToF
     - °F
     - **Minimum heat pump operation temperature**. Lowest tank temperature setpoint allowed in the current operating mode. Range: 95-113°F. Default: 95°F. When set, the user can only set the target tank temperature at or above this threshold, ensuring minimum system operating conditions.

Heat Pump Control Temperatures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Heat pump stages are similarly controlled via thermostat ranges:

.. list-table::
   :header-rows: 1
   :widths: 30 10 15 45

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``hpUpperOnTempSetting``
     - HalfCelsiusToF
     - °F
     - **Upper heat pump ON**. Upper tank falls below this to activate heat pump for upper tank heating.
   * - ``hpUpperOffTempSetting``
     - HalfCelsiusToF
     - °F
     - **Upper heat pump OFF**. Upper tank rises above this to stop upper tank heat pump operation.
   * - ``hpLowerOnTempSetting``
     - HalfCelsiusToF
     - °F
     - **Lower heat pump ON**. Lower tank falls below this to activate heat pump for lower tank heating.
   * - ``hpLowerOffTempSetting``
     - HalfCelsiusToF
     - °F
     - **Lower heat pump OFF**. Lower tank rises above this to stop lower tank heat pump operation.
   * - ``hpUpperOnDiffTempSetting``
     - div_10
     - °F
     - **Heat pump upper differential** (ON-OFF hysteresis). Prevents rapid cycling.
   * - ``hpUpperOffDiffTempSetting``
     - div_10
     - °F
     - **Heat pump upper differential** variation.
   * - ``hpLowerOnDiffTempSetting``
     - div_10
     - °F
     - **Heat pump lower differential**.
   * - ``hpLowerOffDiffTempSetting``
     - div_10
     - °F
     - **Heat pump lower differential** variation.

Freeze Protection Temperatures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 30 10 15 45

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``freezeProtectionUse``
     - device_bool
     - Boolean
     - **Freeze protection enabled flag**. When True, triggers anti-freeze operation below threshold.
   * - ``freezeProtectionTemperature``
     - HalfCelsiusToF
     - °F
     - **Freeze protection temperature setpoint**. Range: 43-50°F (6-10°C). Default: 43°F (6°C). When tank temperature drops below this, electric heating activates automatically to prevent freezing.
   * - ``freezeProtectionTempMin``
     - HalfCelsiusToF
     - °F
     - **Minimum freeze protection temperature limit** (lower boundary). Fixed at 43°F (6°C).
   * - ``freezeProtectionTempMax``
     - HalfCelsiusToF
     - °F
     - **Maximum freeze protection temperature limit** (upper boundary). Fixed at 50°F (10°C).

Recirculation System Temperatures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For systems with recirculation pumps (optional feature):

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``recircTemperature``
     - HalfCelsiusToF
     - °F
     - **Recirculation loop current temperature**. Temperature of water being circulated back to tank.
   * - ``recircFaucetTemperature``
     - HalfCelsiusToF
     - °F
     - **Recirculation faucet outlet temperature**. How hot water is at the furthest fixture during recirculation.
   * - ``recircTempSetting``
     - HalfCelsiusToF
     - °F
     - **Recirculation target temperature**. What temperature to maintain in the recirculation line.


Flow Rate Fields
----------------

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``currentDhwFlowRate``
     - div_10
     - GPM
     - **Current hot water flow rate** at outlet. Measured in real-time. Typical range: 0-5 GPM for fixtures. 0 when no water being drawn.
   * - ``recircDhwFlowRate``
     - div_10
     - GPM
     - **Recirculation loop flow rate**. Circulation pump speed. Typical range: 1-3 GPM to maintain temperature without excessive energy use.
   * - ``cumulatedDhwFlowRate``
     - None (direct value)
     - gallons
     - **Total hot water delivered since installation**. Cumulative counter - never decreases. Useful for usage tracking and diagnostics.

Power and Energy Fields
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``currentInstPower``
     - None (direct value)
     - W
     - **Instantaneous power consumption**. Real-time measurement. Does **NOT** include electric heating element power draw. Heat pump only.
   * - ``totalEnergyCapacity``
     - None (direct value)
     - Wh
     - **Tank energy capacity** at full charge. Theoretical maximum heat content. Useful for recovery time estimation.
   * - ``availableEnergyCapacity``
     - None (direct value)
     - Wh
     - **Available energy in tank right now**. Indicates how much hot water capacity remains before next heating cycle. Lower value = lower DHW charge percentage.

.. note::
   ``currentInstPower`` excludes electric heating element power. If the heater is actively heating with electric elements, the actual power draw will be higher (typically +3755W @ 208V or +5000W @ 240V).

System Status and Performance Fields
------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``dhwChargePer``
     - None (direct value)
     - %
     - **DHW tank charge percentage** (0-100%). Indicates usable hot water availability. Decreases as hot water is drawn; increases during heating cycles.
   * - ``currentHeatUse``
     - device_bool
     - Boolean
     - **Currently heating flag**. True when any heat source (heat pump or element) is active.
   * - ``heatUpperUse``
     - device_bool
     - Boolean
     - **Upper electric element active flag**. True when upper heating element currently drawing power.
   * - ``heatLowerUse``
     - device_bool
     - Boolean
     - **Lower electric element active flag**. True when lower heating element currently drawing power.
   * - ``compUse``
     - device_bool
     - Boolean
     - **Heat pump compressor running flag**. True when heat pump is actively compressing refrigerant.
   * - ``eevUse``
     - device_bool
     - Boolean
     - **Electronic Expansion Valve (EEV) active flag**. True when EEV is modulating refrigerant flow. Usually correlates with ``compUse``.
   * - ``evaFanUse``
     - device_bool
     - Boolean
     - **Evaporator fan running flag**. True when fan drawing ambient air through evaporator coil.

Safety and Diagnostic Fields
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``ecoUse``
     - device_bool
     - Boolean
     - **ECO (Energy Cut Off) flag**. True when high-temperature safety limit triggered. Automatically resets when tank cools below limit.
   * - ``scaldUse``
     - device_bool
     - Boolean
     - **Scald protection warning flag**. True when water temperature reaches potentially hazardous levels (typically >130°F). Advisory only.
   * - ``freezeProtectionUse``
     - device_bool
     - Boolean
     - **Freeze protection active flag**. True when freeze protection heating cycle is running.
   * - ``airFilterAlarmUse``
     - device_bool
     - Boolean
     - **Air filter maintenance reminder enabled flag**. When enabled (True), triggers maintenance alert based on operating hours. Default: On.
   * - ``airFilterAlarmPeriod``
     - None (direct value)
     - hours
     - **Air filter maintenance cycle interval**. Range: Off or 1,000-10,000 hours. Default: 1,000 hours. Maintenance reminder triggers after this operating time elapsed.
   * - ``airFilterAlarmElapsed``
     - None (direct value)
     - hours
     - **Hours elapsed since last air filter maintenance reset**. Resets to 0 when maintenance is performed. Track this to schedule preventative replacement.
   * - ``cumulatedOpTimeEvaFan``
     - None (direct value)
     - hours
     - **Total evaporator fan runtime since installation**. Diagnostic indicator of system usage and fan wear.
   * - ``wtrOvrSensorUse``
     - device_bool
     - Boolean
     - **Water overflow/leak sensor active flag**. True when leak detected in condensate pan or water connections. Triggers error E799.
   * - ``conOvrSensorUse``
     - device_bool
     - Boolean
     - **Condensate overflow sensor active flag**. True when condensate pan overflow detected.
   * - ``shutOffValveUse``
     - device_bool
     - Boolean
     - **Shut-off valve status flag**. True when valve is in normal operating position.
   * - ``antiLegionellaUse``
     - device_bool
     - Boolean
     - **Anti-legionella function enabled flag**. When enabled (True), device periodically heats tank to high temperature to prevent Legionella bacteria growth. Default: Off. Enable recommended for systems not regularly flushed.
   * - ``antiLegionellaOperationBusy``
     - device_bool
     - Boolean
     - **Anti-legionella cycle in progress flag**. True during active high-temperature disinfection cycle.
   * - ``antiLegionellaPeriod``
     - None (direct value)
     - days
     - **Anti-legionella execution cycle interval**. Range: 1-30 days. Default: 7 days. Sets how often the device performs the disinfection cycle.

Vacation and Scheduling Fields
------------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``vacationDaySetting``
     - None (direct value)
     - days
     - **User-configured vacation duration** (0-99 days). When vacation mode activated, heating suspends for this period. Resumption scheduled 9 hours before end.
   * - ``vacationDayElapsed``
     - None (direct value)
     - days
     - **Days elapsed in current vacation mode**. Increments daily from 0 to vacationDaySetting. Reaches max then heating resumes.
   * - ``programReservationUse``
     - device_bool
     - Boolean
     - **Scheduled program (reservation) enabled flag**. True when any reservation schedule is active and affecting operation.
   * - ``recircReservationUse``
     - device_bool
     - Boolean
     - **Recirculation schedule enabled flag**. True when recirculation pump has active schedule.
   * - ``touStatus``
     - None (direct value)
     - See values below
     - **Time-of-Use (TOU) schedule status**. 0=inactive, 1=active. Controls heating based on electricity rate periods.
   * - ``drEventStatus``
     - None (direct value)
     - Bitfield
     - **Demand Response event status** (CTA-2045). Each bit represents a DR signal. 0=no active events, non-zero=DR commands active.
   * - ``drOverrideStatus``
     - None (direct value)
     - See explanation
     - **User override of Demand Response** (up to 72 hours). 0=no override. Non-zero value indicates override active.
   * - ``touOverrideStatus``
     - None (direct value)
     - See explanation
     - **User temporary override of TOU schedule**. Similar to DR override - user can override schedule temporarily.

Network and Diagnostic Fields
-----------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``wifiRssi``
     - None (direct value)
     - dBm
     - **WiFi signal strength** (Received Signal Strength Indicator). Typical range: -30 (excellent) to -90 (poor). Signal below -70 may cause reliability issues.
   * - ``outsideTemperature``
     - None (direct value)
     - °F
     - **Outdoor ambient temperature** (from weather data, not device-measured). Used by device for algorithm optimization. May differ from device-measured ambient temperature.
   * - ``errorCode``
     - None (direct value)
     - Error code
     - **Primary error code** if device fault detected. 0=no error. See ERROR_CODES.rst for complete reference.
   * - ``subErrorCode``
     - None (direct value)
     - Error code
     - **Secondary error code** providing additional fault details. Paired with errorCode for diagnostics.

Advanced Technical Fields
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``targetFanRpm``
     - None (direct value)
     - RPM
     - **Evaporator fan target speed**. Set by control algorithm based on heating demand. Typical range 0-3000 RPM.
   * - ``currentFanRpm``
     - None (direct value)
     - RPM
     - **Actual measured evaporator fan speed**. May differ slightly from target due to motor inertia and load.
   * - ``fanPwm``
     - None (direct value)
     - %
     - **Fan PWM (Pulse Width Modulation) duty cycle** (0-100). Direct control signal to fan motor. Higher = faster.
   * - ``eevStep``
     - None (direct value)
     - steps
     - **EEV stepper motor position** (0-255 typical). Position within its range controls refrigerant flow. 0=wide open, 255=fully closed.
   * - ``mixingRate``
     - None (direct value)
     - %
     - **Mixing valve position** (0-100%). For systems with mixing valves: controls proportion of tank water vs. inlet water for scald prevention.
   * - ``currentStatenum``
     - None (direct value)
     - State ID
     - **Internal device state machine ID**. For diagnostics/advanced troubleshooting. Indicates which logic state device currently executing.
   * - ``smartDiagnostic``
     - None (direct value)
     - Diagnostic code
     - **Smart diagnostic status** for system health monitoring. Non-zero value indicates diagnostic conditions detected.
   * - ``faultStatus1`` / ``faultStatus2``
     - None (bitfield)
     - Bitfield
     - **Hardware fault status registers**. Each bit represents a specific hardware fault condition. See DEVICE_FEATURES.rst for bit definitions.

Configuration Fields
--------------------

These fields reflect device settings (as opposed to real-time measurements):

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Field
     - Conversion
     - Display Unit
     - Description
   * - ``temperatureType``
     - None (direct value)
     - Enum
     - **Temperature display unit setting** (1=Celsius, 2=Fahrenheit). Reflects user's app setting.
   * - ``tempFormulaType``
     - None (direct value)
     - Enum
     - **Temperature conversion formula type**. Advanced: used for non-standard sensor calibrations.
   * - ``errorBuzzerUse``
     - device_bool
     - Boolean
     - **Error buzzer enabled flag**. When True, device beeps on errors.
   * - ``didReload``
     - device_bool
     - Boolean
     - **Recent reload/restart flag**. True indicates device recently rebooted (e.g., after power loss or update).
   * - ``command``
     - None (direct value)
     - Command ID
     - **Last command that triggered this status**. For tracking which command most recently caused status update.

Temperature Unit Notes
----------------------

* **Fahrenheit** conversions assume target display is °F as configured in the device
* **Celsius calculations** can be derived by reversing the conversions:
  
  - From ``HalfCelsiusToF`` fields: ``celsius = (fahrenheit - 32) * 5/9 * 2``
  - From ``PentaCelsiusToF`` fields: ``celsius = (fahrenheit - 32) * 5/9 * 5``
  - From ``div_10`` fields: ``celsius = value_celsius / 10.0``

* **Sensor Accuracy**: Typically ±2°F for tank sensors, ±3°F for refrigerant sensors
* **Conversion Rounding**: Python automatically handles floating-point precision; most displayed values are accurate to 0.1°F

Practical Applications of Conversions
-------------------------------------

Understanding these conversions helps with:

1. **Energy Monitoring**: Combine ``totalEnergyCapacity``, ``availableEnergyCapacity``, and ``currentInstPower`` to estimate recovery times
2. **Efficiency Analysis**: Compare ``ambientTemperature`` against current COP (Coefficient of Performance) to verify expected efficiency
3. **Fault Diagnosis**: Monitor ``dischargeTemperature`` and ``currentSuperHeat`` for refrigerant circuit health
4. **Maintenance Scheduling**: Track ``airFilterAlarmElapsed`` and ``cumulatedOpTimeEvaFan`` for preventative maintenance
5. **User Experience**: Use ``dhwChargePer`` to show users remaining hot water in tank; correlate with ``currentInstPower`` to show recovery ETA

See Also
--------

* :doc:`device_status` - Complete status message structure and field definitions
* :doc:`error_codes` - Error code reference for fault diagnosis
* :doc:`../guides/energy_monitoring` - Using energy data for optimization
* :doc:`../guides/time_of_use` - TOU scheduling and rate optimization
* :doc:`../guides/advanced_features_explained` - Weather-responsive heating, demand response, and tank stratification
