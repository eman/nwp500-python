
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
     - integer
     - None
     - Indicates if the device has recently reloaded or restarted.
     - None
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
     - integer
     - None
     - The current operation mode of the device. See Operation Modes section below.
     - None
   * - ``operationBusy``
     - integer
     - None
     - Indicates if the device is currently performing heating operations (1=busy, 0=idle).
     - None
   * - ``freezeProtectionUse``
     - integer
     - None
     - Whether freeze protection is active. When tank water temperature falls below 43°F (6°C), the electric heater activates to prevent freezing.
     - None
   * - ``dhwUse``
     - integer
     - None
     - Domestic Hot Water (DHW) usage status - indicates if hot water is currently being drawn from the tank.
     - None
   * - ``dhwUseSustained``
     - integer
     - None
     - Sustained DHW usage status - indicates prolonged hot water usage.
     - None
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
     - integer
     - None
     - Whether a program reservation (scheduled operation) is in use.
     - None
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
     - integer
     - None
     - Whether ECO (Energy Cut Off) safety feature has been triggered. The ECO switch is a high-temperature safety limit.
     - None
   * - ``dhwTargetTemperatureSetting``
     - integer
     - °F
     - The target DHW temperature setting (same as dhwTemperatureSetting).
     - ``raw + 20``
   * - ``tankUpperTemperature``
     - integer
     - °F
     - Temperature of the upper part of the tank.
     - ``raw + 20``
   * - ``tankLowerTemperature``
     - integer
     - °F
     - Temperature of the lower part of the tank.
     - ``raw + 20``
   * - ``dischargeTemperature``
     - integer
     - °F
     - Compressor discharge temperature - temperature of refrigerant leaving the compressor.
     - ``raw / 10.0``
   * - ``suctionTemperature``
     - integer
     - °F
     - Compressor suction temperature - temperature of refrigerant entering the compressor.
     - ``raw / 10.0``
   * - ``evaporatorTemperature``
     - integer
     - °F
     - Evaporator temperature - temperature where heat is absorbed from ambient air.
     - ``raw / 10.0``
   * - ``ambientTemperature``
     - integer
     - °F
     - Ambient air temperature measured at the heat pump air intake.
     - ``(raw * 9/5) + 32``
   * - ``targetSuperHeat``
     - integer
     - °F
     - Target superheat value - the desired temperature difference ensuring complete refrigerant vaporization.
     - ``raw / 10.0``
   * - ``compUse``
     - integer
     - None
     - Compressor usage status (1=On, 0=Off). The compressor is the main component of the heat pump.
     - None
   * - ``eevUse``
     - integer
     - None
     - Electronic Expansion Valve (EEV) usage status (1=active, 0=inactive). The EEV controls refrigerant flow.
     - None
   * - ``evaFanUse``
     - integer
     - None
     - Evaporator fan usage status (1=On, 0=Off). The fan pulls ambient air through the evaporator coil.
     - None
   * - ``currentInstPower``
     - integer
     - W
     - Current instantaneous power consumption in Watts. Does not include heating element power when active.
     - None
   * - ``shutOffValveUse``
     - integer
     - None
     - Shut-off valve usage status. The valve controls refrigerant flow in the system.
     - None
   * - ``conOvrSensorUse``
     - integer
     - None
     - Condensate overflow sensor usage status.
     - None
   * - ``wtrOvrSensorUse``
     - integer
     - None
     - Water overflow/leak sensor usage status. Triggers error E799 if leak detected.
     - None
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
     - integer
     - None
     - Whether anti-legionella function is enabled.
     - None
   * - ``antiLegionellaPeriod``
     - integer
     - days
     - Anti-legionella function period.
     - None
   * - ``antiLegionellaOperationBusy``
     - integer
     - None
     - Whether the anti-legionella function is busy.
     - None
   * - ``programReservationType``
     - integer
     - None
     - Type of program reservation.
     - None
   * - ``dhwOperationSetting``
     - integer
     - None
     - DHW operation setting.
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
     - integer
     - None
     - Whether the error buzzer is enabled.
     - None
   * - ``currentHeatUse``
     - integer
     - None
     - Current heat usage.
     - None
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
     - ``raw / 10.0``
   * - ``heatUpperUse``
     - integer
     - None
     - Upper electric heating element usage status (1=On, 0=Off). Power: 3,755W @ 208V or 5,000W @ 240V.
     - None
   * - ``heatLowerUse``
     - integer
     - None
     - Lower electric heating element usage status (1=On, 0=Off). Power: 3,755W @ 208V or 5,000W @ 240V.
     - None
   * - ``scaldUse``
     - integer
     - None
     - Scald protection active status. Displays warning when water temperature reaches levels that could cause scalding.
     - None
   * - ``airFilterAlarmUse``
     - integer
     - None
     - Air filter alarm usage - indicates if air filter maintenance reminder is enabled.
     - None
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

Operation Modes
---------------

The ``operationMode`` field is an integer that maps to the following modes. These modes balance energy efficiency and recovery time based on user needs.

.. list-table::
   :header-rows: 1
   :widths: 10 20 15 15 40

   * - Value
     - Mode
     - Recovery Time
     - Energy Efficiency
     - Description
   * - 1
     - Heat Pump
     - Very Slow
     - High
     - Most energy-efficient mode, using only the heat pump. Recovery time varies with ambient temperature and humidity. Higher ambient temperature and humidity improve efficiency and reduce recovery time.
   * - 2
     - Energy Saver (Hybrid: Efficiency)
     - Fast
     - Very High
     - Default mode. Combines the heat pump and electric heater for balanced efficiency and recovery time. Heat pump is primarily used with electric heater for backup. Applied during initial shipment and factory reset.
   * - 3
     - High Demand (Hybrid: Boost)
     - Very Fast
     - Low
     - Combines heat pump and electric heater with more frequent use of electric heater for faster recovery. Suitable when higher hot water supply is needed.
   * - 4
     - Electric
     - Fast
     - Very Low
     - Uses only upper and lower electric heaters (not simultaneously). Least energy-efficient with shortest recovery time. Can operate continuously for up to 72 hours before automatically reverting to previous mode.
   * - 5
     - Vacation
     - None
     - Very High
     - Suspends heating to save energy during absences (0-99 days). Only minimal operations like freeze protection and anti-seize are performed. Heating resumes 9 hours before the vacation period ends.

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
