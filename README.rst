=============
nwp500-python
=============

Python library for Navien NWP500 Heat Pump Water Heater
========================================================

A Python library for monitoring and controlling the Navien NWP500 Heat Pump Water Heater through the Navilink cloud service. This library provides comprehensive access to device status, temperature control, operation mode management, and real-time monitoring capabilities.

**Documentation:** https://nwp500-python.readthedocs.io/

**Source Code:** https://github.com/eman/nwp500-python

Features
========
* Monitor status (temperature, power, charge %)
* Set target water temperature
* Change operation mode
* Optional scheduling (reservations)
* Optional time-of-use settings
* Periodic high-temp cycle info
* Access detailed status fields

* Async friendly

Quick Start
===========

Installation
------------

.. code-block:: bash

    pip install nwp500-python

Basic Usage
-----------

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienAPIClient

    # Authentication happens automatically when entering the context
    async with NavienAuthClient("your_email@example.com", "your_password") as auth_client:
        # Create API client
        api_client = NavienAPIClient(auth_client=auth_client)
        
        # Get device data
        devices = await api_client.list_devices()
        device = devices[0] if devices else None
        
        if device:
            # Access status information
            status = device.status
            print(f"Water Temperature: {status.dhwTemperature}°F")
            print(f"Tank Charge: {status.dhwChargePer}%")
            print(f"Power Consumption: {status.currentInstPower}W")
            
            # Set temperature
            await api_client.set_device_temperature(device, 130)
            
            # Change operation mode
            await api_client.set_device_mode(device, "heat_pump")

Command Line Interface
======================

The library includes a command line interface for quick monitoring and device information retrieval:

.. code-block:: bash

    # Set credentials via environment variables
    export NAVIEN_EMAIL="your_email@example.com"
    export NAVIEN_PASSWORD="your_password"

    # Get current device status (one-time)
    python -m nwp500.cli --status

    # Get device information
    python -m nwp500.cli --device-info

    # Get device feature/capability information  
    python -m nwp500.cli --device-feature

    # Turn device on
    python -m nwp500.cli --power-on

    # Turn device off
    python -m nwp500.cli --power-off

    # Turn device on and see updated status
    python -m nwp500.cli --power-on --status

    # Set operation mode and see response
    python -m nwp500.cli --set-mode energy-saver

    # Set DHW target temperature and see response
    python -m nwp500.cli --set-dhw-temp 140

    # Set temperature and then get updated status
    python -m nwp500.cli --set-dhw-temp 140 --status

    # Set mode and then get updated status
    python -m nwp500.cli --set-mode energy-saver --status

    # Just get current status (one-time)
    python -m nwp500.cli --status

    # Monitor continuously (default - writes to CSV)
    python -m nwp500.cli --monitor

    # Monitor with custom output file
    python -m nwp500.cli --monitor --output my_data.csv

**Available CLI Options:**

* ``--status``: Print current device status as JSON. Can be combined with control commands to see updated status.
* ``--device-info``: Print comprehensive device information (firmware, model, capabilities) as JSON and exit  
* ``--device-feature``: Print device capabilities and feature settings as JSON and exit
* ``--power-on``: Turn the device on and display response
* ``--power-off``: Turn the device off and display response
* ``--set-mode MODE``: Set operation mode and display response. Valid modes: heat-pump, energy-saver, high-demand, electric, vacation, standby
* ``--set-dhw-temp TEMP``: Set DHW (Domestic Hot Water) target temperature in Fahrenheit (115-150°F) and display response
* ``--monitor``: Continuously monitor status every 30 seconds and log to CSV (default)
* ``-o, --output``: Specify CSV output filename for monitoring mode
* ``--email``: Override email (alternative to environment variable)
* ``--password``: Override password (alternative to environment variable)

Device Status Fields
====================

The library provides access to comprehensive device status information:

**Temperature Sensors**
    * Water temperature (current and target)
    * Tank upper/lower temperatures
    * Ambient temperature
    * Discharge, suction, and evaporator temperatures
    * Inlet temperature

**System Status**
    * Operation mode (Heat Pump, Energy Saver, High Demand, Electric, Vacation)
    * Compressor status
    * Heat pump and electric heater status
    * Evaporator fan status
    * Tank charge percentage

**Power & Energy**
    * Current power consumption (Watts)
    * Total energy capacity (Wh)
    * Available energy capacity (Wh)

**Diagnostics**
    * WiFi signal strength
    * Error codes
    * Fault status
    * Cumulative operation time
    * Flow rates

Documentation
=============

Full docs: https://nwp500-python.readthedocs.io/

Data Models
===========

The library includes type-safe data models with automatic unit conversions:

* **DeviceStatus**: Complete device status with 70+ fields
* **DeviceFeature**: Device capabilities, firmware versions, and configuration limits
* **OperationMode**: Enumeration of available operation modes
* **TemperatureUnit**: Celsius/Fahrenheit handling

Requirements
============

* Python 3.9+
* aiohttp >= 3.8.0
* websockets >= 10.0
* cryptography >= 3.4.0
* pydantic >= 2.0.0
* awsiotsdk >= 1.21.0

License
=======

This project is licensed under the MIT License.

Author
======

Emmanuel Levijarvi <emansl@gmail.com>

Acknowledgments
===============

This project has been set up using PyScaffold 4.6. For details and usage
information on PyScaffold see https://pyscaffold.org/.
