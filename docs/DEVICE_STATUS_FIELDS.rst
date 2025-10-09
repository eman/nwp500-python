
Device Status Fields
====================

This document lists the fields found in the ``status`` object of device status messages.

.. list-table::
   :header-rows: 1

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
     - The outdoor temperature.
     - None
   * - ``specialFunctionStatus``
     - integer
     - None
     - Status of special functions.
     - None
   * - ``didReload``
     - integer
     - None
     - Unknown.
     - None
   * - ``errorCode``
     - integer
     - None
     - Error code if any.
     - None
   * - ``subErrorCode``
     - integer
     - None
     - Sub error code if any.
     - None
   * - ``operationMode``
     - integer
     - None
     - The current operation mode of the device. See Operation Modes section below.
     - None
   * - ``operationBusy``
     - integer
     - None
     - Indicates if the device is busy.
     - None
   * - ``freezeProtectionUse``
     - integer
     - None
     - Whether freeze protection is enabled.
     - None
   * - ``dhwUse``
     - integer
     - None
     - DHW usage status.
     - None
   * - ``dhwUseSustained``
     - integer
     - None
     - Sustained DHW usage status.
     - None
   * - ``dhwTemperature``
     - integer
     - °F
     - Current DHW temperature.
     - ``raw + 20``
   * - ``dhwTemperatureSetting``
     - integer
     - °F
     - Target DHW temperature.
     - ``raw + 20``
   * - ``programReservationUse``
     - integer
     - None
     - Whether a program reservation is in use.
     - None
   * - ``smartDiagnostic``
     - integer
     - None
     - Smart diagnostic status.
     - None
   * - ``faultStatus1``
     - integer
     - None
     - Fault status 1.
     - None
   * - ``faultStatus2``
     - integer
     - None
     - Fault status 2.
     - None
   * - ``wifiRssi``
     - integer
     - dBm
     - WiFi signal strength.
     - None
   * - ``ecoUse``
     - integer
     - None
     - Whether ECO mode is enabled.
     - None
   * - ``dhwTargetTemperatureSetting``
     - integer
     - °F
     - The target DHW temperature setting.
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
     - Discharge temperature.
     - ``raw / 10.0``
   * - ``suctionTemperature``
     - integer
     - °F
     - Suction temperature.
     - ``raw / 10.0``
   * - ``evaporatorTemperature``
     - integer
     - °F
     - Evaporator temperature.
     - ``raw / 10.0``
   * - ``ambientTemperature``
     - integer
     - °F
     - Ambient temperature.
     - ``(raw * 9/5) + 32``
   * - ``targetSuperHeat``
     - integer
     - °F
     - Target super heat value.
     - ``raw / 10.0``
   * - ``compUse``
     - integer
     - None
     - Compressor usage status (On/Off).
     - None
   * - ``eevUse``
     - integer
     - None
     - Electronic Expansion Valve usage status.
     - None
   * - ``evaFanUse``
     - integer
     - None
     - Evaporator fan usage status.
     - None
   * - ``currentInstPower``
     - integer
     - W
     - Current instantaneous power consumption.
     - None
   * - ``shutOffValveUse``
     - integer
     - None
     - Shut-off valve usage status.
     - None
   * - ``conOvrSensorUse``
     - integer
     - None
     - Unknown sensor usage status.
     - None
   * - ``wtrOvrSensorUse``
     - integer
     - None
     - Unknown sensor usage status.
     - None
   * - ``dhwChargePer``
     - integer
     - %
     - DHW charge percentage.
     - None
   * - ``drEventStatus``
     - integer
     - None
     - Demand Response event status.
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
     - Current DHW flow rate.
     - ``raw / 10.0``
   * - ``mixingRate``
     - integer
     - %
     - Mixing rate.
     - None
   * - ``eevStep``
     - integer
     - steps
     - Electronic Expansion Valve step.
     - None
   * - ``currentSuperHeat``
     - integer
     - °F
     - Current super heat value.
     - ``raw / 10.0``
   * - ``heatUpperUse``
     - integer
     - None
     - Upper heater usage status (On/Off).
     - None
   * - ``heatLowerUse``
     - integer
     - None
     - Lower heater usage status (On/Off).
     - None
   * - ``scaldUse``
     - integer
     - None
     - Scald protection usage.
     - None
   * - ``airFilterAlarmUse``
     - integer
     - None
     - Air filter alarm usage.
     - None
   * - ``airFilterAlarmPeriod``
     - integer
     - hours
     - Air filter alarm period.
     - None
   * - ``airFilterAlarmElapsed``
     - integer
     - hours
     - Elapsed time for air filter alarm.
     - None
   * - ``cumulatedOpTimeEvaFan``
     - integer
     - hours
     - Cumulated operation time of the evaporator fan.
     - None
   * - ``cumulatedDhwFlowRate``
     - integer
     - gallons
     - Cumulated DHW flow rate.
     - None
   * - ``touStatus``
     - integer
     - None
     - Time of Use status.
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
     - Demand Response override status.
     - None
   * - ``touOverrideStatus``
     - integer
     - None
     - Time of Use override status.
     - None
   * - ``totalEnergyCapacity``
     - integer
     - Wh
     - Total energy capacity.
     - None
   * - ``availableEnergyCapacity``
     - integer
     - Wh
     - Available energy capacity.
     - None

Operation Modes
---------------

The ``operationMode`` field is an integer that maps to the following modes. The mapping from integer to string is not explicitly defined in the manual, so this is based on observation and will be updated as more information is available.

.. list-table::
   :header-rows: 1

   * - Value
     - Mode
     - Description
   * - 1
     - Heat Pump
     - Most energy-efficient mode, using only the heat pump. It has the slowest recovery time.
   * - 2
     - Energy Saver (Hybrid: Efficiency)
     - Default mode. Combines the heat pump and electric heater for balanced efficiency and recovery time.
   * - 3
     - High Demand (Hybrid: Boost)
     - Also combines the heat pump and electric heater, but uses the electric heater more frequently for faster recovery.
   * - 4
     - Electric
     - Least energy-efficient mode, using only the upper and lower electric heaters for the fastest recovery time.
   * - 5
     - Vacation
     - Suspends heating to save energy during long absences.
