======================
MQTT Protocol
======================

This document describes the MQTT protocol used for real-time communication
with Navien NWP500 devices via AWS IoT Core. Everything here was taken from
the NaviLink Android app's request builder (``SendRequestMgppData.java``,
version 2.03.00) and confirmed against captured traffic and live queries to
an NWP500 wherever a capture exists; the exceptions are marked.

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

Requests are published to a device-keyed topic. Where the reply arrives
depends on the request: control commands are acknowledged with a status
object on the control ack topic, while queries name their own
``responseTopic`` in the envelope and the device (or the NaviLink cloud)
publishes there.

.. code-block:: text

   cmd/{deviceType}/navilink-{mac}/{suffix}                  # every request
   cmd/{deviceType}/navilink-{mac}/{clientId}/res            # control ack
   cmd/{deviceType}/{clientId}/res/{suffix}                  # query reply
   cmd/{deviceType}/{homeSeq}/{userSeq}/{clientId}/res/{suffix}
                                                             # query reply,
                                                             # app form
   cmd/{deviceType}/navilink-{mac}/res/dl-sw-info            # device-keyed
                                                             # reply
   evt/{deviceType}/navilink-{mac}/app-connection            # event

**Variables:**

* ``{deviceType}`` - Device type code (52 for NWP500)
* ``{mac}`` - Device MAC address without separators
* ``{clientId}`` - MQTT client ID
* ``{homeSeq}``, ``{userSeq}`` - The NaviLink app builds its reply topics with
  the home and user sequence numbers from the REST API. The cloud does not
  check the values; it keys one behaviour (the ``td/rd`` JSON decode below)
  on the five-segment *shape*. The library passes ``DeviceInfo.home_seq``
  and ``0``.

Request suffixes
----------------

.. list-table::
   :header-rows: 1
   :widths: 34 12 30 24

   * - Request suffix
     - Code
     - Reply
     - Notes
   * - ``st``
     - 16777219
     - control ack (status object)
     - device status
   * - ``st/did``
     - 16777217
     - control ack (feature object)
     - device features
   * - ``st/end``
     - 16777218
     - none observed
     - session end
   * - ``st/rsv/rd``
     - 16777222
     - ``res/rsv/rd``
     - reservation schedule read
   * - ``st/recirc-rsv/rd``
     - 16777231
     - ``res/recirc-rsv/rd``
     - recirculation schedule read
   * - ``st/td/rd``
     - 16777228
     - ``res/td/rd`` (app form only)
     - installer diagnostics
   * - ``st/dl-sw-info``
     - 16777227
     - device-keyed ``res/dl-sw-info``
     - firmware download info
   * - ``st/energy-usage-daily-query/rd``
     - 16777225
     - ``res/energy-usage-daily-query/rd``
     - per-day energy
   * - ``st/energy-usage-monthly-query/rd``
     - 16777226
     - ``res/energy-usage-monthly-query/rd``
     - per-month energy
   * - ``st/energy-usage-hourly-query/rd``
     - 16777224
     - ``res/energy-usage-hourly-query/rd``
     - per-hour energy (unanswered)
   * - ``ctrl``
     - 33554433 ...
     - control ack
     - mode/param controls
   * - ``ctrl/rsv/rd``
     - 16777226
     - ``res/rsv/rd``
     - reservation schedule write
   * - ``ctrl/recirc-rsv/rd``
     - 33554440
     - ``res/recirc-rsv/rd``
     - recirculation schedule write
   * - ``ctrl/tou/rd``
     - 33554439
     - ``res/tou/rd``
     - Time-of-Use schedule write
   * - ``ctrl/commit-ota``
     - 33554442
     - ``res/commit-ota`` (app form)
     - firmware commit (not exercised)

The reservation read and the recirculation read also produce a second
reply on the suffix without ``/rd`` (``res/rsv``, ``res/recirc-rsv``)
carrying the schedule as a packed hex string instead of a JSON list. The
typed subscriptions listen on the ``/rd`` JSON topics; the schedule models
also parse the hex form for anyone subscribing to the other topic.

Every reply seen so far carries the device's ``macAddress``. Client-keyed
reply topics are shared by every device a client queries, so the typed
subscriptions ignore replies whose ``macAddress`` names another device.

Message Structure
=================

All MQTT messages are JSON with this structure:

.. code-block:: json

   {
     "clientID": "navien-client-1996271a",
     "sessionID": "session-67890",
     "requestTopic": "cmd/52/navilink-04786332fca0/ctrl",
     "responseTopic": "cmd/52/navilink-04786332fca0/navien-client-1996271a/res",
     "protocolVersion": 2,
     "request": {
       "command": 33554464,
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "5322",
       "mode": "dhw-temperature",
       "param": [120],
       "paramStr": ""
     }
   }

**Fields:**

* ``clientID`` - MQTT client identifier
* ``sessionID`` - Session identifier for tracking
* ``requestTopic`` - Topic the request is published to
* ``responseTopic`` - Topic the reply should be published to
* ``protocolVersion`` - Protocol version (always 2)
* ``request`` - Command payload (see below)

Request Object
==============

.. code-block:: json

   {
     "command": 33554464,
     "deviceType": 52,
     "macAddress": "04786332fca0",
     "additionalValue": "5322",
     "mode": "dhw-temperature",
     "param": [120],
     "paramStr": ""
   }

**Fields:**

* ``command`` (int) - Command code (see Command Codes below)
* ``deviceType`` (int) - Device type (52 for NWP500)
* ``macAddress`` (str) - Device MAC address
* ``additionalValue`` (str) - Additional device identifier
* ``mode`` (str) - Control commands only: the command's mode string
* ``param`` (array) - Control commands only: integer parameters
* ``paramStr`` (str) - Control commands only: always ``""``
* ``year``, ``month``, ``day`` - Energy queries only (see below)
* ``reservationUse``, ``reservation`` - Schedule writes only
* ``controllerSerialNumber`` - TOU schedule write only
* ``commitOta`` - OTA commit only

Queries carry no ``mode``/``param``/``paramStr``.

Command Codes
=============

The codes mirror the app's ``DeviceControlMGPP`` enum. Codes marked
*declared only* exist in that enum but the app has no code path that
sends them; their payloads are unknown and the library has no method for
them.

Queries
-------

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Command
     - Code
     - Description
   * - Device Info Request
     - 16777217
     - Request device features/capabilities
   * - Session End
     - 16777218
     - Sent when a client is done with a device
   * - Device Status Request
     - 16777219
     - Request current device status
   * - Reservation Read
     - 16777222
     - Read reservation schedule
   * - Energy Usage Hourly Query
     - 16777224
     - Per-hour energy for given days (the NWP500 tested never answered)
   * - Energy Usage Daily Query
     - 16777225
     - Per-day energy for given months
   * - Reservation Update / Energy Usage Monthly Query
     - 16777226
     - One code, two requests; the topic tells them apart
   * - Firmware Download Info
     - 16777227
     - Downloadable firmware components
   * - Diagnostics
     - 16777228
     - Installer diagnostics counters
   * - Recirculation Schedule Read
     - 16777231
     - Read recirculation pump schedule

Control Commands
----------------

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
   * - Weekly Reservation
     - 33554438
     - *Declared only.* The app writes its weekly schedule with 16777226 on
       ``ctrl/rsv/rd``
   * - Configure TOU Schedule
     - 33554439
     - Configure Time-of-Use pricing schedule (``ctrl/tou/rd``)
   * - Configure Recirculation Schedule
     - 33554440
     - Configure recirculation pump schedule (``ctrl/recirc-rsv/rd``)
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
   * - Set Vacation Duration
     - 33554466
     - Set the vacation day count (``goout-day``)
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
     - Configure air filter service interval
   * - Reset Condenser Fault
     - 33554463
     - Clear a condenser fault (installer-level in the app)

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
     - *Declared only*

Declared but never sent
~~~~~~~~~~~~~~~~~~~~~~~

The app's enum also declares OTA Check (33554443), WiFi Reconnect
(33554446), WiFi Reset (33554447), Freeze Protection Temperature
(33554451) and Smart Diagnostic (33554455). Its request builder has no
case for any of them, so no NaviLink client ever publishes these codes and
their payloads are unknown. Versions of this library before 10.0 sent
made-up ``mode`` strings for them; those methods were removed.

Cooling Mode (33554460), Water Filter Reset (33554461) and Pre-Filter
Reset (33554462) are real MGPP commands (``cooling-mode [n]``,
``water-filter-reset []``, ``pre-filter-reset []``) but belong to the
hydronic product line's screens, not the NWP500.

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
   Vacation mode is the only DHW mode that requires two parameters. This is
   how the app enters vacation mode; see also ``goout-day`` below.

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
   Valid range: Device-specific (see device features for ``dhw_temperature_min`` and ``dhw_temperature_max``).

Anti-Legionella
---------------

**Enable with a 7-day cycle (command 33554472):**

.. code-block:: json

   {
     "command": 33554472,
     "mode": "anti-leg-on",
     "param": [7],
     "paramStr": ""
   }

**Disable (command 33554471):**

.. code-block:: json

   {
     "command": 33554471,
     "mode": "anti-leg-off",
     "param": [],
     "paramStr": ""
   }

Both mode strings appear in captured app traffic.

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

Vacation Duration
-----------------

**Set Vacation Days (command 33554466):**

.. code-block:: json

   {
     "command": 33554466,
     "mode": "goout-day",
     "param": [7],
     "paramStr": ""
   }

.. note::
   The app's builder sets only ``mode`` and ``param`` for this command;
   the library sends ``paramStr`` as well, which the device accepts.
   Verified live: ``vacationDaySetting`` changes and
   ``dhwOperationSetting`` does not. The app has a builder case for this
   command but no screen that calls it (the same is true of the demand
   response and intelligent-mode commands); it enters vacation mode
   through ``dhw-mode [5, days]``.

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

Recirculation Schedule Write
----------------------------

Published on ``cmd/52/navilink-{mac}/ctrl/recirc-rsv/rd`` with
``responseTopic`` ``.../res/recirc-rsv/rd``, where the app expects the
written schedule back. That echo has not been observed, because the only
unit tested has no recirculation pump. Same envelope as the reservation
write; the entries use the reservation entry fields. The app's editor
allows at most 20 entries.

.. code-block:: json

   {
     "command": 33554440,
     "deviceType": 52,
     "macAddress": "04786332fca0",
     "additionalValue": "5322",
     "reservationUse": 2,
     "reservation": [
       {"enable": 2, "week": 62, "hour": 6, "min": 0, "mode": 2, "param": -1}
     ]
   }

In the app's schedule editor ``mode`` is the entry's on/off toggle
(2 = pump on, 1 = pump off) and ``param`` is left at ``-1``. These
semantics are inferred from the app and not confirmed on a unit with
recirculation.

Air Filter Maintenance
----------------------

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
     "param": [6],
     "paramStr": ""
   }

.. note::
   The parameter is the service interval in evaporator-fan hours divided
   by 500. The app offers 0 (alarm off) or 1000 to 10000 hours in 500-hour
   steps, so the wire value is 0 or 2 to 20; the example above is 3000
   hours. The device reports the interval back as ``airFilterAlarmPeriod``
   in hours (verified live).

Condenser Fault Reset
---------------------

**Reset Condenser Fault (command 33554463):**

.. code-block:: json

   {
     "command": 33554463,
     "mode": "cond-fault-reset",
     "param": [],
     "paramStr": ""
   }

.. note::
   The app shows this only to installer accounts; the gate is in the app.
   A consumer account's unit acknowledges it with a status object; no
   fault was present when tested, so the clearing effect is unverified.

Firmware Updates
----------------

**Commit Update (command 33554442):**

Published on ``cmd/52/navilink-{mac}/ctrl/commit-ota`` with the reply
requested on ``res/commit-ota`` in the app's five-segment topic form
(``setPublishMgppControlOTA`` in the app). It uses a special
RequestControlOta structure. Not exercised against a device, since it
would install firmware.

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

Query Details
=============

Energy Usage Queries
--------------------

**Daily (command 16777225, suffix** ``st/energy-usage-daily-query/rd`` **):**

.. code-block:: json

   {
     "command": 16777225,
     "deviceType": 52,
     "macAddress": "04786332fca0",
     "additionalValue": "5322",
     "year": 2024,
     "month": [10, 11, 12]
   }

**Monthly (command 16777226, suffix** ``st/energy-usage-monthly-query/rd`` **):**

.. code-block:: json

   {
     "command": 16777226,
     "deviceType": 52,
     "macAddress": "04786332fca0",
     "additionalValue": "5322",
     "year": [2025, 2026]
   }

**Hourly (command 16777224, suffix** ``st/energy-usage-hourly-query/rd`` **):**

.. code-block:: json

   {
     "command": 16777224,
     "deviceType": 52,
     "macAddress": "04786332fca0",
     "additionalValue": "5322",
     "year": 2026,
     "month": 9,
     "day": [11]
   }

The hourly query is what the app sends, but the NWP500 tested did not
answer it in four attempts with both reply-topic forms.

Diagnostics (command 16777228)
------------------------------

Published on ``st/td/rd`` with no extra fields. The device answers on
``res/td`` with packed little-endian hex strings; the NaviLink cloud
decodes them and republishes JSON on ``res/td/rd``, but only when the
``responseTopic`` has the app's five-segment form. Request accordingly:

.. code-block:: json

   {
     "responseTopic": "cmd/52/25004/0/navien-client-1996271a/res/td/rd",
     "request": {
       "command": 16777228,
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "5322"
     }
   }

Firmware Download Info (command 16777227)
-----------------------------------------

Published on ``st/dl-sw-info``. The device answers on its own topic
``cmd/52/navilink-{mac}/res/dl-sw-info`` regardless of the requested
``responseTopic``; the device wildcard subscription receives it.

Session End (command 16777218)
------------------------------

Published on ``st/end`` with no extra fields whenever the app leaves a
device screen. No reply to it has been observed. The library sends it
from ``disconnect()`` for every subscribed device unless
``MqttConnectionConfig.send_session_end_on_disconnect`` is off; its effect
on other clients connected to the same device is not known.

Response Messages
=================

Status Response
---------------

Control commands and ``st`` are acknowledged on
``cmd/52/navilink-{mac}/{clientId}/res``:

.. code-block:: json

   {
     "clientID": "navilink-04786332fca0",
     "sessionID": "session-67890",
     "requestTopic": "...",
     "responseTopic": "...",
     "response": {
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "5322",
       "status": {
         "command": 67108883,
         "dhwTemperature": 120,
         "dhwTemperatureSetting": 120,
         "currentInstPower": 450,
         "operationMode": 64,
         "dhwOperationSetting": 3,
         "operationBusy": 2,
         "compUse": 2,
         "heatUpperUse": 1,
         "errorCode": 0
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
         "controllerSerialNumber": "ABC123",
         "controllerSwVersion": 184614912,
         "dhwTemperatureMin": 75,
         "dhwTemperatureMax": 130,
         "energyUsageUse": 2
       }
     }
   }

See :doc:`device_features` for complete field reference.

Energy Usage Response
---------------------

Daily and monthly queries share one shape. Each ``usage`` entry is a
requested period; for the daily query it carries ``month`` and one
``data`` item per day, for the monthly query ``month`` is absent and
``data`` holds twelve months. ``total`` is the device's lifetime total:
it is identical whichever year, month or years are requested (checked
live with 2025 alone, 2026 alone, both, and one month).

.. code-block:: json

   {
     "response": {
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "5322",
       "typeOfUsage": 1,
       "total": {"heUsage": 146337, "hpUsage": 1266585, "heTime": 35, "hpTime": 3124},
       "usage": [
         {
           "year": 2026,
           "data": [
             {"heUsage": 34473, "hpUsage": 163228, "heTime": 9, "hpTime": 412}
           ]
         }
       ]
     }
   }

Usage values are watt-hours; times are hours. The app's model also
declares ``epUsage`` and ``waterUsage`` per item and ``day`` per entry,
which the NWP500 does not send.

Diagnostics Response
--------------------

On ``res/td/rd`` (app-form reply topic only):

.. code-block:: json

   {
     "response": {
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "5322",
       "typeOfTD": 2,
       "data": {
         "tsData": {
           "cumulatedPwrHp": 1266585,
           "cumulatedPwrHe": 146337,
           "daysSinceInstallation": 359,
           "cumulatedOccNumEco": 0,
           "cumulatedOccNumDryFire": 0,
           "numOffRostProtectBurn": 0,
           "cumulatedOccNumConOvrFlow": 3,
           "cumulatedOccNumWtrOvrFlow": 0,
           "cumulatedOpTimeDrShed": 0,
           "cumulatedOpTimeDrLoadUp": 0,
           "cumulatedOpTimeDrAdvLoadUp": 0,
           "cumulatedOpTimeDrCpp": 0,
           "cumulatedOpTimeDrGridEmg": 0,
           "cumulatedOccNumAbDisTmp": 0,
           "cumulatedOccNumHpo": 0,
           "cumulatedOccNumAbSucTmp": 0,
           "cumulatedOccNumAbDisSucTmp": 0
         },
         "tcData": {},
         "tdData": {
           "numOfdhwUse": 0,
           "dhwUseTotalFlow": 0,
           "dhwUseTotalTime": 0,
           "numOfLongDhwUse": 0,
           "longDhwUseTotalFlow": 0,
           "longDhwUseTotalTime": 0,
           "numOfShortDhwUse": 0,
           "avrageRecoveryTime": 0
         },
         "taData": {
           "cumulatedOpTimeComp": 3124,
           "cumulatedOpNumComp": 757,
           "cumulatedOpTimeEvaFan": 3138,
           "cumulatedOpNumEvaFan": 794,
           "cumulatedOpStepEev": 1102,
           "cumulatedOpTimeUhe": 35,
           "cumulatedOpNumUhe": 375,
           "cumulatedOpTimeLhe": 0,
           "cumulatedOpNumLhe": 20,
           "cumulatedOpNumShutOffVv": 0,
           "mixingValveOpTotalStep": 0,
           "mixingValveOpAvgMixinGrate": 0,
           "cumulatedOpNumRecircPump": 0,
           "cumulatedOpTimeRecircPump": 0,
           "cumulatedOpTimeInvComp1": 0,
           "cumulatedOpTimeInvComp2": 0,
           "cumulatedOpTimeInvComp3": 0,
           "cumulatedOpTimeInvComp4": 0
         }
       }
     }
   }

The raw ``res/td`` message carries the same values as hex strings
(``tsData``: two little-endian ``uint32`` energies followed by ``uint16``
counters; ``taData`` and ``tdData``: ``uint32`` arrays in the key order
above). ``cumulatedPwrHp``/``cumulatedPwrHe`` equal the energy query's
lifetime totals and ``cumulatedOpTimeComp``/``cumulatedOpTimeUhe`` equal
its lifetime ``hpTime``/``heTime``, which fixes their units as watt-hours
and hours. The remaining counters have no documented unit. The misspelled
keys are the vendor's.

Firmware Download Info Response
-------------------------------

On ``cmd/52/navilink-{mac}/res/dl-sw-info``. A unit with no pending
update reports one all-zero entry:

.. code-block:: json

   {
     "response": {
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "5322",
       "downloadSwInfo": [
         {"swCode": 0, "otaMode": 0, "swVersion": 0, "status": 0}
       ]
     }
   }

Reservation and Recirculation Schedule Responses
------------------------------------------------

On ``res/rsv/rd`` and ``res/recirc-rsv/rd``:

.. code-block:: json

   {
     "response": {
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "5322",
       "reservationUse": 1,
       "reservation": []
     }
   }

The same schedule is also republished on ``res/rsv`` / ``res/recirc-rsv``
with ``reservation`` as a hex string of six bytes per entry
(``enable, week, hour, min, mode, param``).

TOU Response
------------

The TOU write is echoed on ``res/tou/rd`` with the written
``reservationUse`` and ``reservation`` list. There is no MQTT read; use
the REST API to read the schedule.

Connection Flow
===============

1. **Authenticate**

   Obtain AWS credentials from REST API sign-in.

2. **Connect MQTT**

   Connect to AWS IoT endpoint using WebSocket with AWS SigV4 auth.

3. **Subscribe to Responses**

   Subscribe to ``cmd/52/navilink-{mac}/#`` for control acks, pushed
   status and the device-keyed replies, and to ``cmd/52/{clientId}/res/#``
   for query replies.

4. **Signal App Connection**

   Publish to ``evt/52/navilink-{mac}/app-connection``:

   .. code-block:: json

      {
        "clientID": "navien-client-1996271a",
        "timestamp": "2026-09-12T16:00:00Z"
      }

5. **Send Commands / Requests**

   Publish to the request suffixes listed above.

6. **End the session**

   Publish ``st/end`` before disconnecting.

Example: Request Status
=======================

**1. Subscribe:**

.. code-block:: text

   Topic: cmd/52/navilink-04786332fca0/#
   QoS: 1

**2. Publish Request:**

.. code-block:: text

   Topic: cmd/52/navilink-04786332fca0/st
   QoS: 1
   Payload:

.. code-block:: json

   {
     "clientID": "navien-client-1996271a",
     "sessionID": "my-session-id",
     "requestTopic": "cmd/52/navilink-04786332fca0/st",
     "responseTopic": "cmd/52/navilink-04786332fca0/navien-client-1996271a/res",
     "protocolVersion": 2,
     "request": {
       "command": 16777219,
       "deviceType": 52,
       "macAddress": "04786332fca0",
       "additionalValue": "5322"
     }
   }

**3. Receive Response:**

The status object arrives on the control ack topic.

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
