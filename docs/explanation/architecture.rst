============
Architecture
============

This document explains the high-level architecture of the ``nwp500-python`` library and how it interacts with the Navien Smart Control cloud platform.

System Overview
===============

The library acts as a bridge between your Python application and the Navien NWP500 Heat Pump Water Heater. Communication happens through two primary channels:

1. **REST API**: Used for authentication, account management, and listing devices.
2. **MQTT (AWS IoT)**: Used for real-time monitoring and control of the device.

Component Diagram
=================

.. code-block:: text

    +-------------------+       +------------------------+
    |                   |       |                        |
    |  Your Application |       |  Navien Smart Control  |
    |                   |       |         (Cloud)        |
    +---------+---------+       +-----------+------------+
              |                             |
              |       +-------------+       |
              +------>| Auth Client |<------+ (Sign-in/Tokens)
              |       +-------------+       |
              |                             |
              |       +-------------+       |
              +------>| API Client  |<------+ (REST API)
              |       +-------------+       |
              |                             |
              |       +-------------+       |
              +------>| MQTT Client |<------+ (AWS IoT Core)
                      +-------------+

Core Components
===============

Authentication Client
---------------------

The ``NavienAuthClient`` is responsible for managing credentials and tokens. It performs the initial sign-in to obtain:
* A JWT access token for REST API requests.
* AWS IoT credentials (identity ID, session token, etc.) for MQTT connection.

REST API Client
---------------

The ``NavienAPIClient`` provides methods for "heavy" or infrequent operations, such as:
* Retrieving the list of devices.
* Getting detailed device information.
* Accessing historical energy data.

MQTT Client
-----------

The ``NavienMqttClient`` is the heart of real-time interaction. It maintains a persistent connection to AWS IoT Core and handles:
* Subscribing to device status updates.
* Publishing control commands (e.g., setting temperature).
* Parsing incoming hex-encoded payloads into structured data models.

Data Models
===========

The library uses **Pydantic** for all data models. This ensures:
* **Type Safety**: All fields have explicit types.
* **Validation**: Incoming data is validated against expected formats.
* **Unit Handling**: Temperatures and other units are automatically converted to appropriate scales (e.g., Fahrenheit).

Event System
============

The library implements an asynchronous event system. You can subscribe to various events (e.g., status updates, connection changes) and provide callback functions that will be executed when those events occur.

See Also
========

* :doc:`advanced-features` - Deep dive into TOU, reservations, and more.
* :doc:`../reference/protocol/mqtt_protocol` - Low-level details of the MQTT messaging.
