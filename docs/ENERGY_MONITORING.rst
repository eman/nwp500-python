Energy Monitoring Guide
=======================

This guide explains how to monitor energy consumption and usage data
from Navien NWP500 water heaters.

Overview
--------

The NWP500 provides comprehensive energy monitoring through real-time
status updates via MQTT. All energy-related data is available through
the ``DeviceStatus`` object returned by the
``subscribe_device_status()`` callback.

Real-Time Power Consumption
---------------------------

Total Instantaneous Power
~~~~~~~~~~~~~~~~~~~~~~~~~

The most important metric for energy monitoring:

.. code:: python

   from nwp500 import NavienMqttClient, DeviceStatus

   def on_status(status: DeviceStatus):
       # Total power consumption in Watts
       power_watts = status.currentInstPower
       print(f"Current Power: {power_watts} W")

| **Field:** ``currentInstPower``
| **Type:** ``float``
| **Units:** Watts (W)
| **Description:** Total instantaneous power consumption of the entire
  unit, including heat pump compressor and electric heating elements.

Component Status
~~~~~~~~~~~~~~~~

Know which heating components are currently active:

.. code:: python

   def on_status(status: DeviceStatus):
       if status.compUse:
           print("Heat pump compressor is running")
       
       if status.heatUpperUse:
           print("Upper electric heater is running")
       
       if status.heatLowerUse:
           print("Lower electric heater is running")

| **Fields:** - ``compUse`` (bool): Heat pump compressor status -
  ``heatUpperUse`` (bool): Upper electric heating element status
| - ``heatLowerUse`` (bool): Lower electric heating element status

Cumulative Usage Statistics
---------------------------

Track total runtime for each heating component:

.. code:: python

   def on_status(status: DeviceStatus):
       # Convert minutes to hours
       comp_hours = status.compRunningMinuteTotal / 60
       heater1_hours = status.heater1RunningMinuteTotal / 60
       heater2_hours = status.heater2RunningMinuteTotal / 60
       
       print(f"Heat Pump Runtime: {comp_hours:.1f} hours")
       print(f"Upper Heater Runtime: {heater1_hours:.1f} hours")
       print(f"Lower Heater Runtime: {heater2_hours:.1f} hours")

**Fields:** - ``compRunningMinuteTotal`` (int): Total heat pump
compressor runtime in minutes - ``heater1RunningMinuteTotal`` (int):
Total upper electric heater runtime in minutes -
``heater2RunningMinuteTotal`` (int): Total lower electric heater runtime
in minutes

Historical Energy Usage
-----------------------

Request detailed daily energy usage data for specific months:

.. code:: python

   from nwp500 import NavienMqttClient, EnergyUsageResponse
   
   def on_energy_usage(energy: EnergyUsageResponse):
       print(f"Total Usage: {energy.total.total_usage} Wh")
       print(f"Heat Pump: {energy.total.heat_pump_percentage:.1f}%")
       print(f"Electric: {energy.total.heat_element_percentage:.1f}%")
       
       # Daily breakdown
       for day in energy.daily:
           print(f"Day {day.day}: {day.total_usage} Wh")
   
   # Subscribe to energy usage responses
   await mqtt_client.subscribe_energy_usage(device, on_energy_usage)
   
   # Request energy usage for September 2025
   await mqtt_client.request_energy_usage(device, year=2025, months=[9])
   
   # Request multiple months
   await mqtt_client.request_energy_usage(device, year=2025, months=[7, 8, 9])

**Key Methods:**

- ``request_energy_usage(device, year, months)``: Request historical data
- ``subscribe_energy_usage(device, callback)``: Subscribe to energy usage responses

**Response Fields:**

- ``total.total_usage`` (int): Total energy consumption in Wh
- ``total.heat_pump_percentage`` (float): Percentage from heat pump
- ``total.heat_element_percentage`` (float): Percentage from electric heaters
- ``daily`` (list): Daily breakdown of usage per day

Energy Capacity
---------------

Monitor available stored energy:

.. code:: python

   def on_status(status: DeviceStatus):
       capacity = status.availableEnergyCapacity
       print(f"Energy Capacity: {capacity}%")
       
       if capacity < 20:
           print("Low energy - heating may be needed")
       elif capacity > 80:
           print("High energy - tank is hot")

| **Field:** ``availableEnergyCapacity``
| **Type:** ``int``
| **Units:** Percentage (0-100)
| **Description:** Available energy in the tank as a percentage,
  indicating how much hot water is available.

Temperature Monitoring
----------------------

Water Temperature
~~~~~~~~~~~~~~~~~

.. code:: python

   def on_status(status: DeviceStatus):
       # Current water temperature
       current_temp = status.dhwTemperature
       target_temp = status.dhwTemperatureSetting
       
       print(f"Water Temperature: {current_temp}°F (Target: {target_temp}°F)")

**Fields:** - ``dhwTemperature`` (float): Current water
temperature - ``dhwTemperatureSetting`` (int): Target temperature
setting - ``dhwTemperatureMin`` (int): Minimum allowed temperature -
``dhwTemperatureMax`` (int): Maximum allowed temperature

Component Temperatures
~~~~~~~~~~~~~~~~~~~~~~

Monitor individual heating component temperatures:

.. code:: python

   def on_status(status: DeviceStatus):
       print(f"Compressor Temp: {status.compTemp}°F")
       print(f"Upper Tank Temp: {status.dhwTankUpperTemp}°F")
       print(f"Lower Tank Temp: {status.dhwTankLowerTemp}°F")
       print(f"Heat Exchanger Out: {status.dhwHeatexOutTemp}°F")

Complete Energy Monitoring Example
----------------------------------

.. code:: python

   import asyncio
   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient, DeviceStatus

   def calculate_power_cost(power_watts: float, hours: float, cost_per_kwh: float = 0.12) -> float:
       """Calculate energy cost based on power consumption."""
       kwh = (power_watts / 1000) * hours
       return kwh * cost_per_kwh

   async def monitor_energy():
       # Authenticate and get device
       async with NavienAuthClient("email@example.com", "password") as auth_client:
           
           api_client = NavienAPIClient(auth_client=auth_client)
           device = await api_client.get_first_device()
       
       # Create MQTT client
       mqtt_client = NavienMqttClient(auth_client)
       await mqtt_client.connect()
       
       # Energy monitoring callback
       def on_status(status: DeviceStatus):
           print("\n" + "="*50)
           print("ENERGY MONITORING")
           print("="*50)
           
           # Real-time power
           print(f"\nCurrent Power: {status.currentInstPower} W")
           
           # Active components
           components = []
           if status.compUse:
               components.append("Heat Pump")
           if status.heatUpperUse:
               components.append("Upper Heater")
           if status.heatLowerUse:
               components.append("Lower Heater")
           
           if components:
               print(f"Active: {', '.join(components)}")
           else:
               print("Active: None (Standby)")
           
           # Cumulative runtime
           print(f"\nCumulative Runtime:")
           print(f"  Heat Pump: {status.compRunningMinuteTotal / 60:.1f} hours")
           print(f"  Upper Heater: {status.heater1RunningMinuteTotal / 60:.1f} hours")
           print(f"  Lower Heater: {status.heater2RunningMinuteTotal / 60:.1f} hours")
           
           # Energy capacity and temperature
           print(f"\nEnergy Capacity: {status.availableEnergyCapacity}%")
           print(f"Water Temp: {status.dhwTemperature}°F "
                 f"(Target: {status.dhwTemperatureSetting}°F)")
           
           # Estimated hourly cost (if running continuously at current power)
           if status.currentInstPower > 0:
               hourly_cost = calculate_power_cost(status.currentInstPower, 1.0)
               print(f"\nEstimated Cost (if sustained): ${hourly_cost:.3f}/hour")
       
       # Subscribe to device status
       await mqtt_client.subscribe_device_status(
           device.device_info.mac_address,
           on_status
       )
       
       # Request initial status
       await mqtt_client.request_device_status(
           device.device_info.mac_address,
           device.device_info.device_type,
           device.device_info.additional_value
       )
       
       # Monitor for 5 minutes
       print("Monitoring energy consumption for 5 minutes...")
       await asyncio.sleep(300)
       
       # Cleanup
       await mqtt_client.disconnect()

   if __name__ == "__main__":
       asyncio.run(monitor_energy())

Energy Data Fields Reference
----------------------------

Power Consumption
~~~~~~~~~~~~~~~~~

+----------------------+------------+--------------+---------------------------+
| Field                | Type       | Units        | Description               |
+======================+============+==============+===========================+
| ``currentInstPower`` | float      | W            | Total instantaneous power |
|                      |            |              | consumption               |
+----------------------+------------+--------------+---------------------------+
| ``compUse``          | bool       | -            | Heat pump compressor      |
|                      |            |              | active                    |
+----------------------+------------+--------------+---------------------------+
| ``heatUpperUse``     | bool       | -            | Upper electric heater     |
|                      |            |              | active                    |
+----------------------+------------+--------------+---------------------------+
| ``heatLowerUse``     | bool       | -            | Lower electric heater     |
|                      |            |              | active                    |
+----------------------+------------+--------------+---------------------------+

Cumulative Usage
~~~~~~~~~~~~~~~~

+-------------------------------+------------+--------------+---------------------------+
| Field                         | Type       | Units        | Description               |
+===============================+============+==============+===========================+
| ``compRunningMinuteTotal``    | int        | minutes      | Total heat pump runtime   |
+-------------------------------+------------+--------------+---------------------------+
| ``heater1RunningMinuteTotal`` | int        | minutes      | Total upper heater        |
|                               |            |              | runtime                   |
+-------------------------------+------------+--------------+---------------------------+
| ``heater2RunningMinuteTotal`` | int        | minutes      | Total lower heater        |
|                               |            |              | runtime                   |
+-------------------------------+------------+--------------+---------------------------+

.. _energy-capacity-1:

Energy Capacity
~~~~~~~~~~~~~~~

============================= ==== ===== =========================
Field                         Type Units Description
============================= ==== ===== =========================
``availableEnergyCapacity``   int  %     Available energy (0-100%)
============================= ==== ===== =========================

Temperature
~~~~~~~~~~~

============================= ===== ===== =================================
Field                         Type  Units Description
============================= ===== ===== =================================
``dhwTemperature``            float °F    Current water temperature
``dhwTemperatureSetting``     int   °F    Target temperature setting
``compTemp``                  float °F    Heat pump compressor temperature
``dhwTankUpperTemp``          float °F    Upper tank temperature
``dhwTankLowerTemp``          float °F    Lower tank temperature
``dhwHeatexOutTemp``          float °F    Heat exchanger outlet temperature
============================= ===== ===== =================================

Notes
-----

- All power values are in Watts (W)
- All temperatures are in Fahrenheit (°F)
- Status updates are sent automatically by the device approximately
  every few seconds
- Cumulative runtime values persist across device power cycles
- Energy capacity calculation is based on temperature and usage patterns

See Also
--------

- :doc:`DEVICE_STATUS_FIELDS` - Complete list of all status fields
- :doc:`MQTT_CLIENT` - How to connect and subscribe to device updates
- :doc:`MQTT_MESSAGES` - Message format reference
