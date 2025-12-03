======================
MQTT Protocol
======================

This document describes the MQTT protocol used for real-time communication
with Navien NWP500 devices via AWS IoT Core.

.. warning::
   This document describes the underlying MQTT protocol. Most users should use the
   Python client library (:doc:`../python_api/mqtt_client`) instead of implementing
   the protocol directly.

Overview
========

**Protocol:** MQTT 3.1.1 over WebSockets  
**Broker:** AWS IoT Core  
**Authentication:** AWS SigV4 with temporary credentials  
**Message Format:** JSON

Topic Structure
===============

Topics follow a hierarchical structure:

Command Topics
--------------

.. code-block:: text

   cmd/{deviceType}/{deviceId}/ctrl         # Control commands
   cmd/{deviceType}/{deviceId}/st           # Status requests
   cmd/{deviceType}/{clientId}/res/{type}   # Responses

Event Topics
------------

.. code-block:: text

   evt/{deviceType}/{deviceId}/app-connection  # App connection signal

**Variables:**

* ``{deviceType}`` - Device type code (52 for NWP500)
* ``{deviceId}`` - Device MAC address (without colons)
* ``{clientId}`` - MQTT client ID
* ``{type}`` - Response type (status, info, energy-usage, etc.)

Message Structure
=================

All MQTT messages are JSON with this structure:

.. code-block:: json

   {
     "clientID": "client-12345",
     "sessionID": "session-67890",
     "requestTopic": "cmd/52/04786332fca0/ctrl",
     "responseTopic": "cmd/52/client-12345/res/status/rd",
     "protocolVersion": 2,
     "request": {
       "command": 33554438,
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "...",
       "mode": "dhw-temperature",
       "param": [120],
       "paramStr": ""
     }
   }

**Fields:**

* ``clientID`` - MQTT client identifier
* ``sessionID`` - Session identifier for tracking
* ``requestTopic`` - Topic where command was sent
* ``responseTopic`` - Topic to subscribe for responses
* ``protocolVersion`` - Protocol version (always 2)
* ``request`` - Command payload (see below)

Request Object
==============

.. code-block:: json

   {
     "command": 33554438,
     "deviceType": 52,
     "macAddress": "04786332fca0",
     "additionalValue": "...",
     "mode": "dhw-temperature",
     "param": [120],
     "paramStr": ""
   }

**Fields:**

* ``command`` (int) - Command code (see Command Codes below)
* ``deviceType`` (int) - Device type (52 for NWP500)
* ``macAddress`` (str) - Device MAC address
* ``additionalValue`` (str) - Additional device identifier
* ``mode`` (str, optional) - Operation mode for control commands
* ``param`` (array, optional) - Command parameters
* ``paramStr`` (str) - Parameter string
* ``month`` (array, optional) - Months for energy queries
* ``year`` (int, optional) - Year for energy queries

Command Codes
=============

Status and Info Requests
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Device Status Request
     - 16777221
     - Request current device status
   * - Device Info Request
     - 16777222
     - Request device features/capabilities
   * - Reservation Read
     - 16777222
     - Read reservation schedule
   * - Energy Usage Query
     - 33554435
     - Query energy usage data

Control Commands
----------------

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Power On
     - 33554434
     - Turn device on
   * - Power Off
     - 33554433
     - Turn device off
   * - Set DHW Mode
     - 33554437
     - Change operation mode
   * - Set DHW Temperature
     - 33554438
     - Set target temperature
   * - Enable Anti-Legionella
     - 33554472
     - Enable anti-Legionella cycle
   * - Disable Anti-Legionella
     - 33554471
     - Disable anti-Legionella
   * - Update Reservations
     - 16777226
     - Update reservation schedule
   * - Configure TOU
     - 33554439
     - Configure TOU schedule
   * - Enable TOU
     - 33554476
     - Enable TOU optimization
   * - Disable TOU
     - 33554475
     - Disable TOU optimization

Control Command Details
=======================

Power Control
-------------

**Power On:**

.. code-block:: json

   {
     "command": 33554434,
     "mode": "power-on",
     "param": [],
     "paramStr": ""
   }

**Power Off:**

.. code-block:: json

   {
     "command": 33554433,
     "mode": "power-off",
     "param": [],
     "paramStr": ""
   }

DHW Mode
--------

.. code-block:: json

   {
     "command": 33554437,
     "mode": "dhw-mode",
     "param": [3],
     "paramStr": ""
   }

**Mode Values:**

* 1 = Heat Pump Only
* 2 = Electric Only
* 3 = Energy Saver
* 4 = High Demand
* 5 = Vacation (requires second param: days)

**Vacation Example:**

.. code-block:: json

   {
     "command": 33554437,
     "mode": "dhw-mode",
     "param": [5, 7],
     "paramStr": ""
   }

DHW Temperature
---------------

.. code-block:: json

   {
     "command": 33554438,
     "mode": "dhw-temperature",
     "param": [120],
     "paramStr": ""
   }

.. important::
   Temperature values are encoded in **half-degrees Celsius**. 
   Use formula: ``fahrenheit = (param / 2.0) * 9/5 + 32``
   For 140°F, send ``param=120`` (which is 60°C × 2).

Anti-Legionella
---------------

**Enable (7-day cycle):**

.. code-block:: json

   {
     "command": 33554472,
     "mode": "anti-legionella-setting",
     "param": [2, 7],
     "paramStr": ""
   }

**Disable:**

.. code-block:: json

   {
     "command": 33554471,
     "mode": "anti-legionella-setting",
     "param": [1],
     "paramStr": ""
   }

TOU Enable/Disable
------------------

Enable or disable Time-of-Use optimization without changing the configured schedule.

**Enable TOU (command 33554476):**

.. code-block:: json

   {
     "command": 33554476,
     "mode": "tou-on",
     "param": [],
     "paramStr": ""
   }

**Disable TOU (command 33554475):**

.. code-block:: json

   {
     "command": 33554475,
     "mode": "tou-off",
     "param": [],
     "paramStr": ""
   }

Energy Usage Query
------------------

.. code-block:: json

   {
     "command": 33554435,
     "mode": "energy-usage-daily-query",
     "param": [],
     "paramStr": "",
     "year": 2024,
     "month": [10, 11, 12]
   }

Response Messages
=================

Status Response
---------------

.. code-block:: json

   {
     "clientID": "client-12345",
     "sessionID": "session-67890",
     "requestTopic": "...",
     "responseTopic": "...",
     "response": {
       "command": 16777221,
       "deviceType": 52,
       "macAddress": "...",
       "status": {
         "dhw_temperature": 120,
         "dhw_temperature_setting": 120,
         "current_inst_power": 450,
         "operationMode": 64,
         "dhwOperationSetting": 3,
         "operationBusy": 2,
         "compUse": 2,
         "heatUpperUse": 1,
         "errorCode": 0,
         ...
       }
     }
   }

**Field Conversions:**

* Boolean fields: 1=false, 2=true
* Temperature fields: Use HalfCelsiusToF formula: ``fahrenheit = (raw / 2.0) * 9/5 + 32``
* Enum fields: Map integers to enum values

See :doc:`device_status` for complete field reference.

Feature/Info Response
---------------------

.. code-block:: json

   {
     "response": {
       "feature": {
         "controller_serial_number": "ABC123",
         "controller_sw_version": 184614912,
         "dhw_temperature_min": 75,
         "dhw_temperature_max": 130,
         "energy_usage_use": 1,
         ...
       }
     }
   }

See :doc:`device_features` for complete field reference.

Energy Usage Response
---------------------

.. code-block:: json

   {
     "response": {
       "typeOfUsage": "daily",
       "year": 2024,
       "data": [
         {
           "heUsage": 1200,
           "hpUsage": 3500,
           "heTime": 2,
           "hpTime": 8
         }
       ],
       "total": {
         "heUsage": 1200,
         "hpUsage": 3500
       }
     }
   }

Connection Flow
===============

1. **Authenticate**

   Obtain AWS credentials from REST API sign-in.

2. **Connect MQTT**

   Connect to AWS IoT endpoint using WebSocket with AWS SigV4 auth.

3. **Signal App Connection**

   Publish to ``evt/52/{deviceId}/app-connection``:

   .. code-block:: json

      {
        "clientID": "client-12345",
        "sessionID": "session-67890",
        "event": "app-connection"
      }

4. **Subscribe to Responses**

   Subscribe to ``cmd/52/{clientId}/res/#``

5. **Send Commands / Requests**

   Publish commands to appropriate control/status topics.

6. **Receive Responses**

   Process responses via subscribed topics.

Example: Request Status
=======================

**1. Subscribe:**

.. code-block:: text

   Topic: cmd/52/my-client-id/res/status/rd
   QoS: 1

**2. Publish Request:**

.. code-block:: text

   Topic: cmd/52/04786332fca0/st/rd
   QoS: 1
   Payload:

.. code-block:: json

   {
     "clientID": "my-client-id",
     "sessionID": "my-session-id",
     "requestTopic": "cmd/52/04786332fca0/st/rd",
     "responseTopic": "cmd/52/my-client-id/res/status/rd",
     "protocolVersion": 2,
     "request": {
       "command": 16777221,
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "...",
       "mode": "",
       "param": [],
       "paramStr": ""
     }
   }

**3. Receive Response:**

Response arrives on subscribed topic with device status.

Python Implementation
=====================

See :doc:`../python_api/mqtt_client` for the Python client that implements
this protocol.

**Quick Example:**

.. code-block:: python

   from nwp500 import NavienMqttClient
   
   # Client handles all protocol details
   mqtt = NavienMqttClient(auth)
   await mqtt.connect()
   await mqtt.subscribe_device_status(device, callback)
   await mqtt.request_device_status(device)

Related Documentation
=====================

* :doc:`../python_api/mqtt_client` - Python MQTT client
* :doc:`device_status` - Device status fields
* :doc:`device_features` - Device feature fields
* :doc:`error_codes` - Error codes
