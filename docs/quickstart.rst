==========
Quickstart
==========

This guide will get you up and running with the nwp500-python library
in just a few minutes.

Prerequisites
=============

* Python 3.9 or higher
* Navien Smart Control account (via Navilink mobile app)
* At least one Navien NWP500 device registered to your account
* Valid email and password for your Navien account

Installation
============

Install the library using pip:

.. code-block:: bash

   pip install nwp500-python

Or install from source:

.. code-block:: bash

   git clone https://github.com/eman/nwp500-python.git
   cd nwp500-python
   pip install -e .

Your First Script
=================

1. Authentication
-----------------

Authentication is the first step. The library uses your Navien Smart
Control credentials to obtain JWT tokens and AWS IoT credentials.

.. code-block:: python

   import asyncio
   from nwp500 import NavienAuthClient

   async def authenticate():
       async with NavienAuthClient(
           "your-email@example.com",
           "your-password"
       ) as auth:
           print(f"Logged in as: {auth.user_email}")
           print(f"User: {auth.current_user.full_name}")

   asyncio.run(authenticate())

.. note::
   The ``async with`` context manager automatically handles sign-in
   when you enter the context and cleanup when you exit.

2. List Your Devices
---------------------

Use the REST API client to list devices registered to your account:

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient

   async def list_devices():
       async with NavienAuthClient(
           "your-email@example.com",
           "your-password"
       ) as auth:
           
           api = NavienAPIClient(auth)
           devices = await api.list_devices()
           
           for device in devices:
               print(f"Device: {device.device_info.device_name}")
               print(f"  MAC: {device.device_info.mac_address}")
               print(f"  Type: {device.device_info.device_type}")
               print(f"  Location: {device.location.city}, "
                     f"{device.location.state}")

   asyncio.run(list_devices())

3. Monitor Device Status (Real-time)
-------------------------------------

Connect to MQTT for real-time device monitoring:

.. code-block:: python

   from nwp500 import (
       NavienAuthClient,
       NavienAPIClient,
       NavienMqttClient
   )

   async def monitor_device():
       async with NavienAuthClient(
           "your-email@example.com",
           "your-password"
       ) as auth:
           
           # Get first device
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           
           if not device:
               print("No devices found")
               return
           
           # Connect MQTT
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Define status callback
           def on_status(status):
               print(f"\nDevice Status:")
               print(f"  Water Temp: {status.dhw_temperature}°F")
               print(f"  Target: {status.dhw_temperature_setting}°F")
               print(f"  Power: {status.current_inst_power}W")
               print(f"  Mode: {status.dhw_operation_setting.name}")
           
           # Subscribe and request status
           await mqtt.subscribe_device_status(device, on_status)
           await mqtt.request_device_status(device)
           
           # Monitor for 60 seconds
           print("Monitoring device...")
           await asyncio.sleep(60)
           
           await mqtt.disconnect()

   asyncio.run(monitor_device())

4. Control Your Device
----------------------

Send control commands to change device settings:

.. code-block:: python

   from nwp500 import (
       NavienAuthClient,
       NavienAPIClient,
       NavienMqttClient,
       DhwOperationSetting
   )

   async def control_device():
       async with NavienAuthClient(
           "your-email@example.com",
           "your-password"
       ) as auth:
           
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Turn on the device
           await mqtt.set_power(device, power_on=True)
           print("Device powered on")
           
           # Set to Energy Saver mode
           await mqtt.set_dhw_mode(
               device,
               mode_id=DhwOperationSetting.ENERGY_SAVER.value
           )
           print("Set to Energy Saver mode")
           
           # Set temperature to 120°F
           await mqtt.set_dhw_temperature(device, 120.0)
           print("Temperature set to 120°F")
           
           await asyncio.sleep(2)
           await mqtt.disconnect()

   asyncio.run(control_device())

Operation Modes
===============

The NWP500 supports several DHW (Domestic Hot Water) operation modes:

.. list-table::
   :header-rows: 1
   :widths: 15 20 65

   * - Mode ID
     - Name
     - Description
   * - 1
     - Heat Pump Only
     - Most efficient; uses only heat pump (slowest recovery)
   * - 2
     - Electric Only
     - Fastest recovery; uses only electric elements (highest cost)
   * - 3
     - Energy Saver
     - Balanced efficiency and recovery (recommended default)
   * - 4
     - High Demand
     - Maximum heating capacity; uses all components as needed
   * - 5
     - Vacation
     - Suspends heating to save energy during extended absence
   * - 6
     - Power Off
     - Device is powered off (read-only status)

Using Environment Variables
============================

Store credentials securely using environment variables:

.. code-block:: bash

   export NAVIEN_EMAIL="your-email@example.com"
   export NAVIEN_PASSWORD="your-password"

Then in your code:

.. code-block:: python

   import os
   from nwp500 import NavienAuthClient, InvalidCredentialsError

   async def main():
       email = os.getenv("NAVIEN_EMAIL")
       password = os.getenv("NAVIEN_PASSWORD")
       
       if not email or not password:
           raise ValueError(
               "Set NAVIEN_EMAIL and NAVIEN_PASSWORD "
               "environment variables"
           )
       
       try:
           async with NavienAuthClient(email, password) as auth:
               api = NavienAPIClient(auth)
               devices = await api.list_devices()
               # ...
       except InvalidCredentialsError:
           print("Invalid email or password")
           # Re-prompt for credentials

Next Steps
==========

Now that you have the basics, explore these topics:

* :doc:`python_api/auth_client` - Deep dive into authentication
* :doc:`python_api/mqtt_client` - Complete MQTT client documentation
* :doc:`guides/energy_monitoring` - Track energy usage
* :doc:`guides/time_of_use` - Optimize for TOU pricing
* :doc:`guides/event_system` - Use the event-driven architecture

Common Issues
=============

**Authentication Failed**
   Verify your email and password are correct. You can test them in the
   Navilink mobile app first.

**No Devices Found**
   Ensure your device is registered to your account in the Navilink app
   and is online.

**Connection Timeout**
   Check your network connection. The library needs internet access to
   reach the Navien cloud platform.

**Import Errors**
   Make sure you installed the library: ``pip install nwp500-python``

For more help, see the :doc:`development/contributing` guide or file an
issue on GitHub.
