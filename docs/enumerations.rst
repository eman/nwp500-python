Enumerations Reference
======================

This document provides a comprehensive reference for all enumerations used in
the Navien NWP500 protocol.

Device Control Commands
-----------------------

.. autoclass:: nwp500.enums.DeviceControl
   :members:
   :undoc-members:

These command IDs are used in MQTT control messages to change device settings
and trigger actions. The most commonly used commands include:

- **Power Control**: ``POWER_ON``, ``POWER_OFF``
- **Temperature**: ``DHW_TEMPERATURE``
- **Operation Mode**: ``DHW_OPERATION_MODE``
- **TOU**: ``TOU_ON``, ``TOU_OFF``
- **Maintenance**: ``AIR_FILTER_RESET``, ``ANTI_LEGIONELLA_ON``

Example usage::

    from nwp500 import DeviceControl
    
    # Send temperature command
    command = DeviceControl.DHW_TEMPERATURE
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

OperationMode
~~~~~~~~~~~~~

.. autoclass:: nwp500.enums.OperationMode
   :members:
   :undoc-members:

DHW heating mode for heat pump water heaters. This determines which heat source(s)
the device will use:

- **HEATPUMP**: Most efficient but slower heating
- **HYBRID**: Balance of efficiency and speed
- **ELECTRIC**: Fastest but uses most energy

Example::

    from nwp500 import OperationMode, OPERATION_MODE_TEXT
    
    mode = OperationMode.HYBRID
    print(f"Current mode: {OPERATION_MODE_TEXT[mode]}")  # "Hybrid"

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

Values with "CAS\_" prefix indicate cascading systems where multiple units
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
       OPERATION_MODE_TEXT,
       HEAT_SOURCE_TEXT,
       DR_EVENT_TEXT,
       RECIRC_MODE_TEXT,
       TOU_RATE_TEXT,
       FILTER_STATUS_TEXT,
   )
   
   # Usage
   mode = OperationMode.HYBRID
   print(OPERATION_MODE_TEXT[mode])  # "Hybrid"

Related Documentation
---------------------

For detailed protocol documentation, see:

- :doc:`protocol/device_status` - Status field definitions
- :doc:`guides/time_of_use` - TOU scheduling and rate types
- :doc:`protocol/control_commands` - Control command usage
