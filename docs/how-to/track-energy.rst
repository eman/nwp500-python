Energy Monitoring Guide
=======================

This guide explains how to monitor energy consumption and usage data
from Navien NWP500 water heaters.

Overview
--------

The NWP500 provides energy monitoring data through real-time
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
       power_watts = status.current_inst_power
       print(f"Current Power: {power_watts} W")

| **Field:** ``current_inst_power``
| **Type:** ``float``
| **Units:** Watts (W)
| **Description:** Total instantaneous power consumption of the entire
  unit, including heat pump compressor and electric heating elements.

Component Status
~~~~~~~~~~~~~~~~

Know which heating components are currently active:

.. code:: python

   def on_status(status: DeviceStatus):
       if status.comp_use:
           print("Heat pump compressor is running")
       
       if status.heat_upper_use:
           print("Upper electric heater is running")
       
       if status.heat_lower_use:
           print("Lower electric heater is running")

**Fields:**

- ``comp_use`` (bool): Heat pump compressor active
- ``heat_upper_use`` (bool): Upper electric heating element active
- ``heat_lower_use`` (bool): Lower electric heating element active

Cumulative Usage Statistics
---------------------------

Track total runtime for each heating component:

.. code:: python

   def on_status(status: DeviceStatus):
       # Convert minutes to hours
       comp_hours = status.comp_running_minute_total / 60
       heater1_hours = status.heater1_running_minute_total / 60
       heater2_hours = status.heater2_running_minute_total / 60
       
       print(f"Heat Pump Runtime: {comp_hours:.1f} hours")
       print(f"Upper Heater Runtime: {heater1_hours:.1f} hours")
       print(f"Lower Heater Runtime: {heater2_hours:.1f} hours")

**Fields:**

- ``comp_running_minute_total`` (int): Total heat pump compressor runtime in minutes
- ``heater1_running_minute_total`` (int): Total upper electric heater runtime in minutes
- ``heater2_running_minute_total`` (int): Total lower electric heater runtime in minutes

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

**Methods:**

- ``request_energy_usage(device, year, months)``: Request historical data
- ``subscribe_energy_usage(device, callback)``: Subscribe to energy usage responses

**Response Fields:**

- ``total.total_usage`` (int): Total energy consumption in Wh
- ``total.heat_pump_percentage`` (float): Percentage from heat pump
- ``total.heat_element_percentage`` (float): Percentage from electric heaters
- ``daily`` (list): Daily breakdown of usage per day

Energy Capacity
---------------

.. warning::
   The device's two energy fields do **not** report stored energy, and
   the names in the protocol are misleading. See
   :doc:`../explanation/tank-energy` for the evidence.

Monitor the tank's heating deficit:

.. code:: python

   def on_status(status: DeviceStatus):
       needed = status.energy_to_setpoint
       print(f"Energy still needed: {needed:.0f} Wh")

       if needed < 200:
           print("Tank is essentially fully charged")

| **Field:** ``energy_to_setpoint`` (protocol: ``availableEnergyCapacity``)
| **Type:** ``float``
| **Units:** Watt-hours
| **Description:** Energy the device still has to add to reach the
  setpoint. It *falls* as the tank heats and reaches zero when charged.
  Despite the protocol name, it is the inverse of available energy.

| **Field:** ``full_recovery_energy`` (protocol: ``totalEnergyCapacity``)
| **Type:** ``float``
| **Units:** Watt-hours
| **Description:** Cost of a full recovery to the *current setpoint*,
  measured from the device reference temperature of 104.9 degF. It moves
  with the setpoint, so it is not a fixed tank capacity.

Temperature Monitoring
----------------------

Water Temperature
~~~~~~~~~~~~~~~~~

.. code:: python

   def on_status(status: DeviceStatus):
       # Current water temperature
       current_temp = status.dhw_temperature
       target_temp = status.dhw_temperature_setting
       
       print(f"Water Temperature: {current_temp}°F (Target: {target_temp}°F)")

**Fields:**

- ``dhw_temperature`` (float): Current water temperature
- ``dhw_temperature_setting`` (int): Target temperature setting
- ``dhw_temperature_min`` (int): Minimum allowed temperature
- ``dhw_temperature_max`` (int): Maximum allowed temperature

Component Temperatures
~~~~~~~~~~~~~~~~~~~~~~

Monitor individual heating component temperatures:

.. code:: python

   def on_status(status: DeviceStatus):
       print(f"Discharge Temp: {status.discharge_temperature}°F")
       print(f"Upper Tank Temp: {status.tank_upper_temperature}°F")
       print(f"Lower Tank Temp: {status.tank_lower_temperature}°F")
       print(f"Ambient Temp: {status.ambient_temperature}°F")

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
       async with NavienAuthClient("email@example.com", "password") as auth_client:
           api_client = NavienAPIClient(auth_client=auth_client)
           device = await api_client.get_first_device()
           
           # Create MQTT client inside the auth context
           mqtt_client = NavienMqttClient(auth_client)
           await mqtt_client.connect()
           
           # Energy monitoring callback
           def on_status(status: DeviceStatus):
               print("\n" + "="*50)
               print("ENERGY MONITORING")
               print("="*50)
               
               # Real-time power
               print(f"\nCurrent Power: {status.current_inst_power} W")
               
               # Active components
               components = []
               if status.comp_use:
                   components.append("Heat Pump")
               if status.heat_upper_use:
                   components.append("Upper Heater")
               if status.heat_lower_use:
                   components.append("Lower Heater")
               
               if components:
                   print(f"Active: {', '.join(components)}")
               else:
                   print("Active: None (Standby)")
               
               # Cumulative runtime
               print(f"\nCumulative Runtime:")
               print(f"  Heat Pump: {status.comp_running_minute_total / 60:.1f} hours")
               print(f"  Upper Heater: {status.heater1_running_minute_total / 60:.1f} hours")
               print(f"  Lower Heater: {status.heater2_running_minute_total / 60:.1f} hours")
               
               # Heating deficit and temperature
               print(f"\nEnergy to setpoint: {status.energy_to_setpoint:.0f} Wh")
               print(f"Water Temp: {status.dhw_temperature}°F "
                     f"(Target: {status.dhw_temperature_setting}°F)")
               
               # Estimated hourly cost (if running continuously at current power)
               if status.current_inst_power > 0:
                   hourly_cost = calculate_power_cost(status.current_inst_power, 1.0)
                   print(f"\nEstimated Cost (if sustained): ${hourly_cost:.3f}/hour")
           
           # Subscribe to device status
           await mqtt_client.subscribe_device_status(device, on_status)
           
           # Request initial status
           await mqtt_client.request_device_status(device)
           
           # Monitor for 5 minutes
           print("Monitoring energy consumption for 5 minutes...")
           await asyncio.sleep(300)
           
           await mqtt_client.disconnect()

   if __name__ == "__main__":
       asyncio.run(monitor_energy())

Energy Data Fields Reference
----------------------------

Power Consumption
~~~~~~~~~~~~~~~~~

+------------------------+------------+--------------+---------------------------+
| Field                  | Type       | Units        | Description               |
+========================+============+==============+===========================+
| ``current_inst_power`` | float      | W            | Total instantaneous power |
|                        |            |              | consumption               |
+------------------------+------------+--------------+---------------------------+
| ``comp_use``           | bool       | -            | Heat pump compressor      |
|                        |            |              | active                    |
+------------------------+------------+--------------+---------------------------+
| ``heat_upper_use``     | bool       | -            | Upper electric heater     |
|                        |            |              | active                    |
+------------------------+------------+--------------+---------------------------+
| ``heat_lower_use``     | bool       | -            | Lower electric heater     |
|                        |            |              | active                    |
+------------------------+------------+--------------+---------------------------+

Cumulative Usage
~~~~~~~~~~~~~~~~

+--------------------------------+------------+--------------+---------------------------+
| Field                          | Type       | Units        | Description               |
+================================+============+==============+===========================+
| ``comp_running_minute_total``  | int        | minutes      | Total heat pump runtime   |
+--------------------------------+------------+--------------+---------------------------+
| ``heater1_running_minute_total`` | int      | minutes      | Total upper heater        |
|                                |            |              | runtime                   |
+--------------------------------+------------+--------------+---------------------------+
| ``heater2_running_minute_total`` | int      | minutes      | Total lower heater        |
|                                |            |              | runtime                   |
+--------------------------------+------------+--------------+---------------------------+

.. _energy-capacity-1:

Energy Capacity
~~~~~~~~~~~~~~~

========================== ===== ===== ==========================================
Field                      Type  Units Description
========================== ===== ===== ==========================================
``energy_to_setpoint``     float Wh    Energy still **needed** to reach setpoint
``full_recovery_energy``   float Wh    Cost of a full recovery to the setpoint
``dhw_charge_per``         float %     Device's own charge estimate
========================== ===== ===== ==========================================

Temperature
~~~~~~~~~~~

============================== ===== ===== =================================
Field                          Type  Units Description
============================== ===== ===== =================================
``dhw_temperature``            float °F    Current water temperature
``dhw_temperature_setting``    float °F    Target temperature setting
``discharge_temperature``      float °F    Compressor discharge temperature
``tank_upper_temperature``     float °F    Upper tank temperature
``tank_lower_temperature``     float °F    Lower tank temperature
``ambient_temperature``        float °F    Air intake temperature
============================== ===== ===== =================================

Notes
-----

- All power values are in Watts (W)
- All temperatures are in Fahrenheit (°F)
- Status updates are sent automatically by the device approximately
  every few seconds
- Cumulative runtime values persist across device power cycles
- The device's energy fields are heating *deficits*, not stored energy

See Also
--------

- :doc:`../explanation/tank-energy` - What the energy fields really mean
- :doc:`../reference/protocol/device_status` - Complete list of all status fields
- :doc:`../reference/python_api/mqtt_client` - How to connect and subscribe to device updates
- :doc:`../reference/protocol/mqtt_protocol` - Message format reference
