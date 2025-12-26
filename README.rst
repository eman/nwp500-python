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
            print(f"Water Temperature: {status.dhw_temperature}°F")
            print(f"Tank Charge: {status.dhw_charge_per}%")
            print(f"Power Consumption: {status.current_inst_power}W")
            
            # Set temperature
            await api_client.set_device_temperature(device, 130)
            
            # Change operation mode
            await api_client.set_device_mode(device, "heat_pump")

For more detailed authentication information, see the `Authentication & Session Management <https://nwp500-python.readthedocs.io/en/latest/guides/authentication.html>`_ guide.

MQTT Real-Time Monitoring
--------------------------

Monitor your device in real-time using MQTT:

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienMqttClient

    async with NavienAuthClient("your_email@example.com", "your_password") as auth_client:
        # Create MQTT client
        mqtt_client = NavienMqttClient(auth_client=auth_client)
        await mqtt_client.connect()
        
        # Subscribe to device status updates
        def on_status(status):
            print(f"Temperature: {status.dhw_temperature}°F")
            print(f"Mode: {status.operation_mode}")
        
        device = (await api_client.list_devices())[0]
        await mqtt_client.subscribe_device_status(device, on_status)
        
        # Keep the connection alive
        await mqtt_client.wait()


Command Line Interface
======================

The library includes a command line interface for monitoring and controlling your Navien water heater:

.. code-block:: bash

    # Set credentials via environment variables
    export NAVIEN_EMAIL="your_email@example.com"
    export NAVIEN_PASSWORD="your_password"

    # Get current device status
    python3 -m nwp500.cli status

    # Get device information and firmware (via MQTT - DeviceFeature)
    python3 -m nwp500.cli info

    # Get basic device info from REST API (DeviceInfo)
    python3 -m nwp500.cli device-info

    # Get controller serial number
    python3 -m nwp500.cli serial

    # Turn device on/off
    python3 -m nwp500.cli power on
    python3 -m nwp500.cli power off

    # Set operation mode
    python3 -m nwp500.cli mode heat-pump
    python3 -m nwp500.cli mode energy-saver
    python3 -m nwp500.cli mode high-demand
    python3 -m nwp500.cli mode electric
    python3 -m nwp500.cli mode vacation
    python3 -m nwp500.cli mode standby

    # Set target temperature
    python3 -m nwp500.cli temp 140

    # Set vacation days
    python3 -m nwp500.cli vacation 7

    # Trigger instant hot water
    python3 -m nwp500.cli hot-button

    # Set recirculation pump mode (1-4)
    python3 -m nwp500.cli recirc 2

    # Reset air filter timer
    python3 -m nwp500.cli reset-filter

    # Enable water program mode
    python3 -m nwp500.cli water-program

    # View and update schedules
    python3 -m nwp500.cli reservations get
    python3 -m nwp500.cli reservations set '[{"hour": 6, "min": 0, ...}]'

    # Time-of-use settings
    python3 -m nwp500.cli tou get
    python3 -m nwp500.cli tou set on

    # Energy usage data
    python3 -m nwp500.cli energy --year 2024 --months 10,11,12

    # Demand response
    python3 -m nwp500.cli dr enable
    python3 -m nwp500.cli dr disable

    # Real-time monitoring (logs to CSV)
    python3 -m nwp500.cli monitor
    python3 -m nwp500.cli monitor -o my_data.csv

**Global Options:**

* ``--email EMAIL``: Navien account email (or use ``NAVIEN_EMAIL`` env var)
* ``--password PASSWORD``: Navien account password (or use ``NAVIEN_PASSWORD`` env var)
* ``-v, --verbose``: Enable debug logging
* ``--version``: Show version and exit

**Available Commands:**

* ``status``: Show current device status (temperature, mode, power)
* ``info``: Show device information (firmware, capabilities)
* ``serial``: Get controller serial number
* ``power on|off``: Turn device on or off
* ``mode MODE``: Set operation mode (heat-pump, electric, energy-saver, high-demand, vacation, standby)
* ``temp TEMPERATURE``: Set target water temperature in °F
* ``vacation DAYS``: Enable vacation mode for N days
* ``recirc MODE``: Set recirculation pump (1=always, 2=button, 3=schedule, 4=temperature)
* ``hot-button``: Trigger instant hot water
* ``reset-filter``: Reset air filter maintenance timer
* ``water-program``: Enable water program reservation mode
* ``reservations get|set``: View or update schedule
* ``tou get|set STATE``: View or configure time-of-use settings
* ``energy``: Query historical energy usage (requires ``--year`` and ``--months``)
* ``dr enable|disable``: Enable or disable demand response
* ``monitor``: Monitor device status in real-time (logs to CSV with ``-o`` option)

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

* Python 3.13+
* aiohttp >= 3.8.0
* pydantic >= 2.0.0
* awsiotsdk >= 1.27.0

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
