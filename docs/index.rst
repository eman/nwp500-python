=============
nwp500-python
=============

Python client library for Navien NWP500 heat pump water heaters.

.. image:: https://img.shields.io/pypi/v/nwp500-python.svg
   :target: https://pypi.org/project/nwp500-python/
   :alt: PyPI version

.. image:: https://img.shields.io/pypi/pyversions/nwp500-python.svg
   :target: https://pypi.org/project/nwp500-python/
   :alt: Python versions

Overview
========

This library provides a complete Python interface to Navien NWP500 heat
pump water heaters through the Navien Smart Control cloud platform. It
supports both REST API and real-time MQTT communication.

**Key Features:**

* **REST API Client** - Complete implementation of Navien Smart Control
  API
* **MQTT Client** - Real-time device communication via AWS IoT Core
* **Authentication** - JWT-based auth with automatic token refresh
* **Type Safety** - Comprehensive type-annotated data models
* **Event System** - Subscribe to device state changes with callbacks
* **Energy Monitoring** - Track power consumption and usage statistics
* **Time-of-Use (TOU)** - Optimize for variable electricity pricing
* **Async/Await** - Fully asynchronous, non-blocking operations

Quick Start
===========

Installation
------------

.. code-block:: bash

   pip install nwp500-python

Basic Example
-------------

.. code-block:: python

   import asyncio
   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient

   async def main():
       # Authenticate (credentials from env vars or direct)
       async with NavienAuthClient(
           "email@example.com",
           "password"
       ) as auth:
           
           # Get device list via REST API
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           print(f"Device: {device.device_info.device_name}")
           
           # Connect to MQTT for real-time control
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           
           # Monitor device status
           def on_status(status):
               print(f"Temp: {status.dhw_temperature}°F")
               print(f"Power: {status.current_inst_power}W")
           
           await mqtt.subscribe_device_status(device, on_status)
           await mqtt.request_device_status(device)
           
           # Control device
           await mqtt.set_power(device, power_on=True)
           await mqtt.set_dhw_temperature(device, 120.0)
           
           await asyncio.sleep(30)
           await mqtt.disconnect()

   asyncio.run(main())

Documentation Index
===================

.. toctree::
   :maxdepth: 1
   :caption: Getting Started

   quickstart
   installation
   configuration

.. toctree::
   :maxdepth: 2
   :caption: Python API Reference

   python_api/auth_client
   python_api/api_client
   python_api/mqtt_client
   python_api/models
   python_api/constants
   python_api/events
   python_api/exceptions
   python_api/cli

.. toctree::
   :maxdepth: 2
   :caption: Complete Module Reference

   api/modules



.. toctree::
   :maxdepth: 1
   :caption: User Guides

   guides/reservations
   guides/scheduling_features
   guides/energy_monitoring
   guides/time_of_use
   guides/event_system
   guides/command_queue
   guides/auto_recovery
   guides/advanced_features_explained

.. toctree::
   :maxdepth: 2
   :caption: Advanced: Protocol Reference

   protocol/rest_api
   protocol/mqtt_protocol
   protocol/device_status
   protocol/data_conversions
   protocol/device_features
   protocol/error_codes
   protocol/firmware_tracking

.. toctree::
   :maxdepth: 1
   :caption: Development

   development/contributing
   development/history
   changelog
   license
   authors

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
