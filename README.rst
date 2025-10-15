=============
nwp500-python
=============

Python library for Navien NWP500 Heat Pump Water Heater
========================================================

A Python library for monitoring and controlling the Navien NWP500 Heat Pump Water Heater through the Navilink cloud service. This library provides comprehensive access to device status, temperature control, operation mode management, and real-time monitoring capabilities.

Features
========

* **Device Monitoring**: Access real-time status information including temperatures, power consumption, and tank charge level
* **Temperature Control**: Set target water temperature (100-140°F)
* **Operation Mode Control**: Switch between Heat Pump, Energy Saver, High Demand, Electric, and Vacation modes
* **Reservation Management**: Schedule automatic temperature and mode changes
* **Time of Use (TOU)**: Configure energy pricing schedules for demand response
* **Anti-Legionella Protection**: Monitor periodic disinfection cycles (140°F heating)
* **Comprehensive Status Data**: Access to 70+ device status fields including compressor status, heater status, flow rates, and more
* **MQTT Protocol Support**: Low-level MQTT communication with Navien devices
* **Non-Blocking Async Operations**: Fully compatible with async event loops (Home Assistant safe)
* **Automatic Reconnection**: Reconnects automatically with exponential backoff during network interruptions
* **Command Queuing**: Commands sent while disconnected are queued and sent automatically when reconnected
* **Data Models**: Type-safe data classes with automatic unit conversions

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
* ``--device-info``: Print comprehensive device information (firmware, model, capabilities) via MQTT as JSON and exit  
* ``--device-feature``: Print device capabilities and feature settings via MQTT as JSON and exit
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

Operation Modes
===============

.. list-table:: Operation Modes
    :header-rows: 1
    :widths: 25 10 65

    * - Mode
      - ID
      - Description
    * - Heat Pump Mode
      - 1
      - Most energy-efficient mode using only the heat pump. Longest recovery time.
    * - Electric Mode
      - 2
      - Fastest recovery using only electric heaters. Least energy-efficient.
    * - Energy Saver Mode
      - 3
      - Default mode. Balances efficiency and recovery time using both heat pump and electric heater.
    * - High Demand Mode
      - 4
      - Uses electric heater more frequently for faster recovery time.
    * - Vacation Mode
      - 5
      - Suspends heating to save energy during extended absences.

**Important:** When you set a mode, you're configuring the ``dhwOperationSetting`` (what mode to use when heating). The device's current operational state is reported in ``operationMode`` (0=Standby, 32=Heat Pump active, 64=Energy Saver active, 96=High Demand active). See the `Device Status Fields documentation <docs/DEVICE_STATUS_FIELDS.rst>`_ for details on this distinction.

MQTT Protocol
=============

The library supports low-level MQTT communication with Navien devices:

**Control Topics**
    * ``cmd/{deviceType}/{deviceId}/ctrl`` - Send control commands
    * ``cmd/{deviceType}/{deviceId}/ctrl/rsv/rd`` - Manage reservations
    * ``cmd/{deviceType}/{deviceId}/ctrl/tou/rd`` - Time of Use settings
    * ``cmd/{deviceType}/{deviceId}/st`` - Request status updates

**Control Commands**
    * Power control (on/off)
    * DHW mode changes (including vacation mode)
    * Temperature settings
    * Reservation management (scheduled mode/temperature changes)
    * Time of Use (TOU) pricing schedules

**Status Requests**
    * Device information
    * General device status
    * Energy usage queries
    * Reservation information
    * TOU settings

See the full `MQTT Protocol Documentation`_ for detailed message formats.

Documentation
=============

Comprehensive documentation is available in the ``docs/`` directory:

* `Device Status Fields`_ - Complete field reference with units and conversions
* `Device Feature Fields`_ - Device capabilities and firmware information reference
* `MQTT Messages`_ - MQTT protocol documentation
* `MQTT Client`_ - MQTT client usage guide
* `Authentication`_ - Authentication module documentation

.. _MQTT Protocol Documentation: docs/MQTT_MESSAGES.rst
.. _Device Status Fields: docs/DEVICE_STATUS_FIELDS.rst
.. _Device Feature Fields: docs/DEVICE_FEATURE_FIELDS.rst
.. _MQTT Messages: docs/MQTT_MESSAGES.rst
.. _MQTT Client: docs/MQTT_CLIENT.rst
.. _Authentication: docs/AUTHENTICATION.rst

Data Models
===========

The library includes type-safe data models with automatic unit conversions:

* **DeviceStatus**: Complete device status with 70+ fields
* **DeviceFeature**: Device capabilities, firmware versions, and configuration limits
* **OperationMode**: Enumeration of available operation modes
* **TemperatureUnit**: Celsius/Fahrenheit handling
* **MqttRequest/MqttCommand**: MQTT message structures

Temperature conversions are handled automatically:
    * DHW temperatures: ``raw_value + 20`` (°F)
    * Heat pump temperatures: ``raw_value / 10.0`` (°F)
    * Ambient temperature: ``(raw_value * 9/5) + 32`` (°F)

Requirements
============

* Python 3.9+
* aiohttp >= 3.8.0
* websockets >= 10.0
* cryptography >= 3.4.0
* pydantic >= 2.0.0
* awsiotsdk >= 1.21.0

Development
===========
To set up a development environment, clone the repository and install the required dependencies:

.. code-block:: bash

    # Clone the repository
    git clone https://github.com/eman/nwp500-python.git
    cd nwp500-python

    # Install in development mode
    pip install -e .

    # Run tests
    pytest

**Linting and CI Consistency**

To ensure your local linting matches CI exactly:

.. code-block:: bash

    # Install tox (recommended)
    pip install tox

    # Run linting exactly as CI does
    tox -e lint

    # Auto-fix and format
    tox -e format

For detailed linting setup instructions, see `LINTING_SETUP.md <LINTING_SETUP.md>`_.

For comprehensive development guide, see `DEVELOPMENT.md <DEVELOPMENT.md>`_.

License
=======

This project is licensed under the MIT License - see the `LICENSE.txt <LICENSE.txt>`_ file for details.

Author
======

Emmanuel Levijarvi <emansl@gmail.com>

Acknowledgments
===============

This project has been set up using PyScaffold 4.6. For details and usage
information on PyScaffold see https://pyscaffold.org/.
