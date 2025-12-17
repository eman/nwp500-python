Enumerations Reference
======================

This document provides a comprehensive reference for all enumerations used in
the Navien NWP500 protocol.

Device Control Commands
-----------------------

.. autoclass:: nwp500.enums.CommandCode
   :members:
   :undoc-members:

These command IDs are used in MQTT control messages to change device settings
and trigger actions. The most commonly used commands include:

- **Power Control**: ``POWER_ON``, ``POWER_OFF``
- **Temperature**: ``DHW_TEMPERATURE``
- **Operation Mode**: ``DHW_MODE``
- **TOU**: ``TOU_ON``, ``TOU_OFF``
- **Maintenance**: ``AIR_FILTER_RESET``, ``ANTI_LEGIONELLA_ON``

Example usage::

    from nwp500 import CommandCode
    
    # Send temperature command
    command = CommandCode.DHW_TEMPERATURE
    params = [120]  # 60°C in half-degree units

Status Value Enumerations
--------------------------

OnOffFlag
~~~~~~~~~

.. autoclass:: nwp500.enums.OnOffFlag
   :members:
   :undoc-members:

Generic on/off flag used throughout status fields for power status, TOU status,
recirculation status, vacation mode, anti-legionella, and other boolean settings.

**Note**: Device uses ``1=OFF, 2=ON`` (not standard 0/1 boolean).

Operation
~~~~~~~~~

.. autoclass:: nwp500.enums.Operation
   :members:
   :undoc-members:

Device operation state indicating overall device activity.

DhwOperationSetting
~~~~~~~~~~~~~~~~~~~

.. autoclass:: nwp500.enums.DhwOperationSetting
   :members:
   :undoc-members:

User-configured DHW heating mode preference. This determines which heat source(s)
the device will use when heating is needed:

- **HEAT_PUMP**: Most efficient but slower heating
- **ELECTRIC**: Fastest but uses most energy
- **ENERGY_SAVER**: Hybrid mode - balanced efficiency
- **HIGH_DEMAND**: Hybrid mode - maximum heating capacity
- **VACATION**: Energy-saving mode for extended absences
- **POWER_OFF**: Device powered off

Example::

    from nwp500 import DhwOperationSetting
    from nwp500.enums import DHW_OPERATION_SETTING_TEXT
    
    mode = DhwOperationSetting.ENERGY_SAVER
    print(f"Current mode: {DHW_OPERATION_SETTING_TEXT[mode]}")  # "Hybrid: Efficiency"

CurrentOperationMode
~~~~~~~~~~~~~~~~~~~~

.. autoclass:: nwp500.enums.CurrentOperationMode
   :members:
   :undoc-members:

Real-time operational state (read-only). This reflects what the device is actually
doing right now, which may differ from the configured mode setting:

- **STANDBY**: Device idle, not actively heating
- **HEAT_PUMP_MODE**: Heat pump actively running
- **HYBRID_EFFICIENCY_MODE**: Actively heating in Energy Saver mode
- **HYBRID_BOOST_MODE**: Actively heating in High Demand mode

Example::

    from nwp500 import CurrentOperationMode
    from nwp500.enums import CURRENT_OPERATION_MODE_TEXT
    
    mode = CurrentOperationMode.HEAT_PUMP_MODE
    print(f"Device state: {CURRENT_OPERATION_MODE_TEXT[mode]}")  # "Heat Pump"

HeatSource
~~~~~~~~~~

.. autoclass:: nwp500.enums.HeatSource
   :members:
   :undoc-members:

Currently active heat source (read-only status). This reflects what the device
is *currently* using, not what mode it's set to. In Hybrid mode, this field
shows which heat source(s) are active at any moment.

DREvent
~~~~~~~

.. autoclass:: nwp500.enums.DREvent
   :members:
   :undoc-members:

Demand Response event status. Allows utilities to manage grid load by signaling
water heaters to reduce consumption (shed) or pre-heat (load up) before peak periods.

WaterLevel
~~~~~~~~~~

.. autoclass:: nwp500.enums.WaterLevel
   :members:
   :undoc-members:

Hot water level indicator displayed as gauge in app. IDs are non-sequential,
likely represent bit positions for multi-level displays.

FilterChange
~~~~~~~~~~~~

.. autoclass:: nwp500.enums.FilterChange
   :members:
   :undoc-members:

Air filter status for heat pump models. Indicates when air filter maintenance
is needed.

RecirculationMode
~~~~~~~~~~~~~~~~~

.. autoclass:: nwp500.enums.RecirculationMode
   :members:
   :undoc-members:

Recirculation pump operation mode:

- **ALWAYS**: Pump continuously runs
- **BUTTON**: Manual activation only (hot button)
- **SCHEDULE**: Runs on configured schedule
- **TEMPERATURE**: Activates when pipe temp drops below setpoint

Time of Use (TOU) Enumerations
-------------------------------

TouWeekType
~~~~~~~~~~~

.. autoclass:: nwp500.enums.TouWeekType
   :members:
   :undoc-members:

Day grouping for TOU schedules. Allows separate schedules for weekdays and
weekends to account for different electricity rates and usage patterns.

TouRateType
~~~~~~~~~~~

.. autoclass:: nwp500.enums.TouRateType
   :members:
   :undoc-members:

Electricity rate period type. Device behavior can be configured for each period:

- **OFF_PEAK**: Lowest rates - device heats aggressively
- **MID_PEAK**: Medium rates - device heats normally
- **ON_PEAK**: Highest rates - device minimizes heating

Temperature and Unit Enumerations
----------------------------------

TemperatureType
~~~~~~~~~~~~~~~

.. autoclass:: nwp500.enums.TemperatureType
   :members:
   :undoc-members:

Temperature display unit preference (Celsius or Fahrenheit).

**Alias**: ``TemperatureUnit`` in models.py for backward compatibility.

TempFormulaType
~~~~~~~~~~~~~~~

.. autoclass:: nwp500.enums.TempFormulaType
   :members:
   :undoc-members:

Temperature conversion formula type. Different device models use slightly different
rounding algorithms when converting internal Celsius values to Fahrenheit:

- **ASYMMETRIC** (Type 0): Special rounding based on raw value remainder
- **STANDARD** (Type 1): Simple round to nearest integer

This ensures the mobile app matches the device's built-in display exactly.

Device Type Enumerations
-------------------------

UnitType
~~~~~~~~

.. autoclass:: nwp500.enums.UnitType
   :members:
   :undoc-members:

Navien device/unit model types. Common values:

- **NPF** (513): Heat pump water heater (primary model for this library)
- **NPE**: Tankless water heater
- **NCB**: Condensing boiler
- **NPN**: Condensing water heater

Values with ``CAS_`` prefix indicate cascading systems where multiple units
work together.

DeviceType
~~~~~~~~~~

.. autoclass:: nwp500.enums.DeviceType
   :members:
   :undoc-members:

Communication device type (WiFi module model).

FirmwareType
~~~~~~~~~~~~

.. autoclass:: nwp500.enums.FirmwareType
   :members:
   :undoc-members:

Firmware component types. Devices may have multiple firmware components that
can be updated independently.

Display Text Helpers
--------------------

The enums module also provides dictionaries for converting enum values to
user-friendly display text:

.. code-block:: python

   from nwp500.enums import (
       DHW_OPERATION_SETTING_TEXT,
       CURRENT_OPERATION_MODE_TEXT,
       HEAT_SOURCE_TEXT,
       DR_EVENT_TEXT,
       RECIRC_MODE_TEXT,
       TOU_RATE_TEXT,
       FILTER_STATUS_TEXT,
       ERROR_CODE_TEXT,
   )
   
   # Usage examples
   from nwp500 import DhwOperationSetting, CurrentOperationMode, ErrorCode
   
   # User-configured mode
   mode = DhwOperationSetting.ENERGY_SAVER
   print(DHW_OPERATION_SETTING_TEXT[mode])  # "Hybrid: Efficiency"
   
   # Current operational state
   state = CurrentOperationMode.HEAT_PUMP_MODE
   print(CURRENT_OPERATION_MODE_TEXT[state])  # "Heat Pump"
   
   # Error codes
   error = ErrorCode.E407_DHW_TEMP_SENSOR
   print(ERROR_CODE_TEXT[error])  # "Abnormal DHW Temperature Sensor"

Related Documentation
---------------------

For detailed protocol documentation, see:

- :doc:`protocol/device_status` - Status field definitions
- :doc:`guides/time_of_use` - TOU scheduling and rate types
- :doc:`protocol/control_commands` - Control command usage
