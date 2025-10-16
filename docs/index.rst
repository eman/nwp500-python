=============
nwp500-python
=============

Python client library for Navien NWP500 water heaters.

Features
========

* **REST API Client** - Full implementation of Navien Smart Control API
* **MQTT Client** - Real-time device communication via AWS IoT Core
* **Authentication** - JWT-based authentication with automatic token refresh
* **Type Safety** - Comprehensive data models for all API responses
* **Energy Monitoring** - Track power consumption and usage statistics

Quick Start Guide
=================

Get started with the nwp500 Python library.

Installation
------------

.. code-block:: bash

   pip install nwp500

Or install from source:

.. code-block:: bash

   git clone https://github.com/eman/nwp500-python.git
   cd nwp500-python
   pip install -e .

Prerequisites
-------------

- Python 3.9+
- Navilink Smart Control account
- At least one Navien NWP500 device registered to your account

Basic Usage
-----------

1. Authentication
^^^^^^^^^^^^^^^^^

.. code-block:: python

   import asyncio
   from nwp500 import NavienAuthClient

   async def authenticate():
       async with NavienAuthClient("email@example.com", "password") as client:
           # Already authenticated!
           print(f"Access Token: {client.current_tokens.access_token[:20]}...")
           print(f"Logged in as: {client.user_email}")

   asyncio.run(authenticate())

2. List Your Devices
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient

   async def list_devices():
       async with NavienAuthClient("email@example.com", "password") as auth_client:
           
           api_client = NavienAPIClient(auth_client=auth_client)
           devices = await api_client.list_devices()
           
           for device in devices:
               print(f"Device: {device.device_info.device_name}")
               print(f"  MAC: {device.device_info.mac_address}")
               print(f"  Type: {device.device_info.device_type}")

   asyncio.run(list_devices())

3. Monitor Device Status (Real-time)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

   async def monitor_device():
       # Authenticate once
       async with NavienAuthClient("email@example.com", "password") as auth_client:
           
           # Get devices using API client
           api_client = NavienAPIClient(auth_client=auth_client)
           device = await api_client.get_first_device()
       
           # Connect to MQTT
           mqtt = NavienMqttClient(auth_client)
           await mqtt.connect()
           
           # Define status callback
           def on_status(status):
               print(f"\nDevice Status Update:")
               print(f"  Temperature: {status.dhwTemperature}°F")
               print(f"  Target: {status.dhwTemperatureSetting}°F")
               print(f"  Power: {status.currentInstPower}W")
               print(f"  Energy: {status.availableEnergyCapacity}%")
           
           # Subscribe to status updates
           await mqtt.subscribe_device_status(device, on_status)
           
           # Request initial status
           await mqtt.request_device_status(device)
           
           # Monitor for 60 seconds
           await asyncio.sleep(60)
           await mqtt.disconnect()

   asyncio.run(monitor_device())

4. Control Your Device
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

   async def control_device():
       # Authenticate and connect
       async with NavienAuthClient("email@example.com", "password") as auth_client:
           
           # Get device using API client
           api_client = NavienAPIClient(auth_client=auth_client)
           device = await api_client.get_first_device()
       
           mqtt = NavienMqttClient(auth_client)
           await mqtt.connect()
           
           # Turn on the device
           await mqtt.set_power(device, power_on=True)
           print("Device powered on")
           
           # Set to Energy Saver mode
           await mqtt.set_dhw_mode(device, mode_id=4)
           print("Set to Energy Saver mode")
           
           # Set target temperature to 120°F
           await mqtt.set_dhw_temperature(device, temperature=120)
           print("Temperature set to 120°F")
           
           await asyncio.sleep(2)
           await mqtt.disconnect()

   asyncio.run(control_device())

Operation Modes
---------------

The NWP500 supports four DHW operation modes:

.. list-table::
   :header-rows: 1
   :widths: 10 20 70

   * - Mode ID
     - Name
     - Description
   * - 1
     - Heat Pump Only
     - Use heat pump exclusively (most efficient)
   * - 2
     - Electric Only
     - Use electric heating elements only
   * - 3
     - Energy Saver
     - Balanced mode (heat pump + electric as needed)
   * - 4
     - High Demand
     - Maximum heating (all components as needed)

.. note::
   Additional modes may appear in device status:
   
   - Mode 0: Standby (device in idle state)
   - Mode 6: Power Off (device is powered off)

Configuration with Environment Variables
----------------------------------------

Store credentials securely using environment variables:

.. code-block:: bash

   export NAVIEN_EMAIL="email@example.com"
   export NAVIEN_PASSWORD="your_password"

Then in your code:

.. code-block:: python

   import os
   from nwp500 import NavienAuthClient, NavienAPIClient

   email = os.getenv("NAVIEN_EMAIL")
   password = os.getenv("NAVIEN_PASSWORD")

   async with NavienAuthClient(email, password) as auth_client:
       api_client = NavienAPIClient(auth_client=auth_client)
       devices = await api_client.list_devices()

Complete Example
----------------

Here's a complete example that demonstrates all major features:

.. code-block:: python

   import asyncio
   import os
   from nwp500 import (
       NavienAuthClient,
       NavienAPIClient,
       NavienMqttClient,
       DeviceStatus
   )

   async def main():
       # Get credentials from environment
       email = os.getenv("NAVIEN_EMAIL")
       password = os.getenv("NAVIEN_PASSWORD")
       
       if not email or not password:
           print("Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables")
           return
       
       print("Authenticating...")
       async with NavienAuthClient(email, password) as auth_client:
           print(f"Logged in as: {auth_client.user_email}")
           
           # Get device list
           api_client = NavienAPIClient(auth_client=auth_client)
           devices = await api_client.list_devices()
           
           device = devices[0]
           
           print(f"Connected to device: {device.device_info.device_name}")
           print(f"MAC Address: {device.device_info.mac_address}")
           
           # Connect MQTT
           mqtt_client = NavienMqttClient(auth_client)
           await mqtt_client.connect()
           print(f"MQTT Connected: {mqtt_client.client_id}")
           
           # Status monitoring
           update_count = 0
           
           def on_status(status: DeviceStatus):
               nonlocal update_count
               update_count += 1
               
               print(f"\n--- Status Update #{update_count} ---")
               print(f"Water Temperature: {status.dhwTemperature}°F "
                     f"(Target: {status.dhwTemperatureSetting}°F)")
               print(f"Power Consumption: {status.currentInstPower}W")
               print(f"Energy Capacity: {status.availableEnergyCapacity}%")
               
               # Show active components
               active = []
               if status.compUse:
                   active.append("Heat Pump")
               if status.heatUpperUse:
                   active.append("Upper Heater")
               if status.heatLowerUse:
                   active.append("Lower Heater")
               
               if active:
                   print(f"Active Components: {', '.join(active)}")
               else:
                   print("Active Components: None (Standby)")
           
           # Subscribe
           await mqtt_client.subscribe_device_status(device, on_status)
           
           # Request status
           await mqtt_client.request_device_status(device)
           
           # Monitor for 30 seconds
           print("\nMonitoring device for 30 seconds...")
           await asyncio.sleep(30)
           
           # Cleanup
           await mqtt_client.disconnect()
           print("\nDisconnected")

   if __name__ == "__main__":
       asyncio.run(main())


Documentation
=============

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   Overview <readme>
   Authentication <AUTHENTICATION>
   REST API Client <API_CLIENT>
   MQTT Client <MQTT_CLIENT>

.. toctree::
   :maxdepth: 2
   :caption: User Guides

   Command Queue <COMMAND_QUEUE>
   Event Emitter <EVENT_EMITTER>
   Energy Monitoring <ENERGY_MONITORING>
   Auto-Recovery Quick Reference <AUTO_RECOVERY_QUICK>
   Auto-Recovery Complete Guide <AUTO_RECOVERY>

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   API Reference (OpenAPI) <API_REFERENCE>
   Device Status Fields <DEVICE_STATUS_FIELDS>
   Device Feature Fields <DEVICE_FEATURE_FIELDS>
   Error Codes <ERROR_CODES>
   MQTT Messages <MQTT_MESSAGES>
   Firmware Tracking <FIRMWARE_TRACKING>

.. toctree::
   :maxdepth: 2
   :caption: Development

   Development History <DEVELOPMENT>
   Contributing <contributing>
   License <license>
   Authors <authors>
   Changelog <changelog>
   Module Reference <api/modules>


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

.. _toctree: https://www.sphinx-doc.org/en/master/usage/restructuredtext/directives.html
.. _reStructuredText: https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html
.. _references: https://www.sphinx-doc.org/en/stable/markup/inline.html
.. _Python domain syntax: https://www.sphinx-doc.org/en/master/usage/restructuredtext/domains.html#the-python-domain
.. _Sphinx: https://www.sphinx-doc.org/
.. _Python: https://docs.python.org/
.. _Numpy: https://numpy.org/doc/stable
.. _SciPy: https://docs.scipy.org/doc/scipy/reference/
.. _matplotlib: https://matplotlib.org/contents.html#
.. _Pandas: https://pandas.pydata.org/pandas-docs/stable
.. _Scikit-Learn: https://scikit-learn.org/stable
.. _autodoc: https://www.sphinx-doc.org/en/master/ext/autodoc.html
.. _Google style: https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings
.. _NumPy style: https://numpydoc.readthedocs.io/en/latest/format.html
.. _classical style: https://www.sphinx-doc.org/en/master/domains.html#info-field-lists
