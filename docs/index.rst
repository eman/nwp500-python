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

**Features:**

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

Install with ``pip install nwp500-python``, then see the :doc:`quickstart` guide
to connect and control your device in minutes.

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
   python_api/device_control
   python_api/models
   enumerations
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

   guides/authentication
   guides/event_system
   guides/command_queue
   guides/auto_recovery
   guides/scheduling
   guides/energy_monitoring
   guides/time_of_use
   guides/unit_conversion
   guides/home_assistant_integration
   guides/mqtt_diagnostics
   guides/advanced_features_explained

.. toctree::
   :maxdepth: 2
   :caption: Advanced: Protocol Reference

   protocol/quick_reference
   protocol/rest_api
   protocol/mqtt_protocol
   protocol/device_status
   protocol/data_conversions
   protocol/device_features
   protocol/error_codes

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
