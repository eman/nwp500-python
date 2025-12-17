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

These commands control device operation, settings, and special functions.

Power Control
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Power Off
     - 33554433
     - Turn device off
   * - Power On
     - 33554434
     - Turn device on

Operation Mode Control
~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Set DHW Operation Mode
     - 33554437
     - Change DHW heating mode (Heat Pump/Electric/Hybrid)
   * - Set DHW Temperature
     - 33554464
     - Set target water temperature

Scheduling and Reservations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Update Weekly Reservations
     - 33554438
     - Configure weekly temperature schedule
   * - Configure TOU Schedule
     - 33554439
     - Configure Time-of-Use pricing schedule
   * - Configure Recirculation Schedule
     - 33554440
     - Configure recirculation pump schedule
   * - Configure Water Program (Reservation Mode)
     - 33554441
     - Enable/configure water program reservation mode

Time-of-Use (TOU) Control
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Disable TOU
     - 33554475
     - Disable TOU optimization
   * - Enable TOU
     - 33554476
     - Enable TOU optimization

Recirculation Pump Control
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Trigger Recirculation Hot Button
     - 33554444
     - Manually activate recirculation pump
   * - Set Recirculation Mode
     - 33554445
     - Set recirculation operation mode

Special Functions
~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Set Freeze Protection Temperature
     - 33554451
     - Configure freeze protection activation temperature
   * - Trigger Smart Diagnostic
     - 33554455
     - Run smart diagnostic routine
   * - Set Vacation Days
     - 33554466
     - Configure vacation mode duration
   * - Disable Intelligent Mode
     - 33554467
     - Turn off intelligent/adaptive heating
   * - Enable Intelligent Mode
     - 33554468
     - Turn on intelligent/adaptive heating

Demand Response Control
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Disable Demand Response
     - 33554469
     - Disable utility demand response
   * - Enable Demand Response
     - 33554470
     - Enable utility demand response

Anti-Legionella Control
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Disable Anti-Legionella
     - 33554471
     - Disable anti-Legionella cycle
   * - Enable Anti-Legionella
     - 33554472
     - Enable anti-Legionella cycle

Maintenance
~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Reset Air Filter
     - 33554473
     - Reset air filter maintenance timer
   * - Set Air Filter Life
     - 33554474
     - Configure air filter replacement interval

Firmware Updates
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Commit OTA Update
     - 33554442
     - Commit pending firmware update
   * - Check for OTA Updates
     - 33554443
     - Check for available firmware updates

WiFi Management
~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Reconnect WiFi
     - 33554446
     - Trigger WiFi reconnection
   * - Reset WiFi
     - 33554447
     - Reset WiFi settings

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
* 3 = Energy Saver (Hybrid mode)
* 4 = High Demand
* 5 = Vacation (requires second param: days)

**Vacation Mode Example:**

When mode is 5 (VACATION), a second parameter specifies number of days:

.. code-block:: json

   {
     "command": 33554437,
     "mode": "dhw-mode",
     "param": [5, 7],
     "paramStr": ""
   }

.. note::
   Vacation mode is the only DHW mode that requires two parameters.

DHW Temperature
---------------

.. code-block:: json

   {
     "command": 33554464,
     "mode": "dhw-temperature",
     "param": [120],
     "paramStr": ""
   }

.. important::
   Temperature values are encoded in **half-degrees Celsius**. 
   Use formula: ``fahrenheit = (param / 2.0) * 9/5 + 32``
   For 140°F, send ``param=120`` (which is 60°C × 2).
   Valid range: 95-150°F (70-150 raw value).

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

Reservation Water Program
--------------------------

Enable/configure water program reservation mode.

**Configure Reservation Mode (command 33554441):**

.. code-block:: json

   {
     "command": 33554441,
     "mode": "reservation-mode",
     "param": [],
     "paramStr": ""
   }

.. note::
   This command enables or configures the water program reservation system.

Vacation Mode
-------------

Set vacation/away mode for extended periods.

**Set Vacation Days (command 33554466):**

.. code-block:: json

   {
     "command": 33554466,
     "mode": "goout-day",
     "param": [7]
   }

.. note::
   Vacation days parameter: Number of days (e.g., 7). Device will operate in 
   energy-saving mode to minimize consumption during absence.

Intelligent/Adaptive Mode
--------------------------

Control intelligent heating that learns usage patterns.

**Enable Intelligent Mode (command 33554468):**

.. code-block:: json

   {
     "command": 33554468,
     "mode": "intelligent-on",
     "param": [],
     "paramStr": ""
   }

**Disable Intelligent Mode (command 33554467):**

.. code-block:: json

   {
     "command": 33554467,
     "mode": "intelligent-off",
     "param": [],
     "paramStr": ""
   }

Demand Response
---------------

Control utility demand response participation.

**Enable Demand Response (command 33554470):**

.. code-block:: json

   {
     "command": 33554470,
     "mode": "dr-on",
     "param": [],
     "paramStr": ""
   }

**Disable Demand Response (command 33554469):**

.. code-block:: json

   {
     "command": 33554469,
     "mode": "dr-off",
     "param": [],
     "paramStr": ""
   }

.. note::
   Demand response allows utilities to manage grid load by signaling water heaters
   to reduce consumption (shed) or pre-heat (load up) before peak periods.

Recirculation Control
---------------------

Control recirculation pump operation.

**Hot Button (command 33554444):**

.. code-block:: json

   {
     "command": 33554444,
     "mode": "recirc-hotbtn",
     "param": [1],
     "paramStr": ""
   }

.. note::
   The param array contains a parameter (typically 1 to activate).

**Set Recirculation Mode (command 33554445):**

.. code-block:: json

   {
     "command": 33554445,
     "mode": "recirc-mode",
     "param": [3],
     "paramStr": ""
   }

**Recirculation Mode Values:**

* 1 = Always On
* 2 = Button Only (manual activation)
* 3 = Schedule (follow configured schedule)
* 4 = Temperature (activate when pipe temp drops)

**Note:** The param array contains a single integer parameter passed to the function.

Air Filter Maintenance
----------------------

Manage air filter maintenance for heat pump models.

**Reset Air Filter Timer (command 33554473):**

.. code-block:: json

   {
     "command": 33554473,
     "mode": "air-filter-reset",
     "param": [],
     "paramStr": ""
   }

**Set Air Filter Life (command 33554474):**

.. code-block:: json

   {
     "command": 33554474,
     "mode": "air-filter-life",
     "param": [180],
     "paramStr": ""
   }

.. note::
   Air filter life parameter: days between cleanings/replacements (typically 90-180 days)

Freeze Protection
-----------------

Configure freeze protection settings.

**Set Freeze Protection Temperature (command 33554451):**

.. code-block:: json

   {
     "command": 33554451
   }

.. note::
   This command is defined in the enum but payload structure not found in 
   decompiled code. May require additional parameters or use default payload.

Smart Diagnostics
-----------------

Run smart diagnostic routine.

**Trigger Smart Diagnostic (command 33554455):**

.. code-block:: json

   {
     "command": 33554455
   }

.. note::
   This command is defined in the enum but payload structure not found in 
   decompiled code. May require additional parameters or use default payload.

WiFi Management
---------------

Control WiFi connectivity.

**Reconnect WiFi (command 33554446):**

.. code-block:: json

   {
     "command": 33554446
   }

**Reset WiFi Settings (command 33554447):**

.. code-block:: json

   {
     "command": 33554447
   }

.. warning::
   WiFi reset will clear stored credentials and require re-provisioning.

.. note::
   These commands are defined in the enum but payload structures not found in 
   decompiled code. They likely use minimal/default payloads.

Firmware Updates
----------------

Manage over-the-air firmware updates.

**Commit Update (command 33554442):**

This command uses a special RequestControlOta structure:

.. code-block:: json

   {
     "command": 33554442,
     "deviceType": 52,
     "macAddress": "...",
     "additionalValue": "...",
     "commitOta": {
       "swCode": 1,
       "swVersion": 184614912
     }
   }

.. note::
   - swCode: Software component code (1=Controller, 2=Panel, 4=WiFi module)
   - swVersion: Version number to commit
   - This command does not use the standard mode/param/paramStr structure

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
