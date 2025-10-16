
Navien MQTT Protocol Documentation
==================================

This document describes the MQTT protocol used by Navien devices for monitoring and control.

Topics
------

The MQTT topics have a hierarchical structure. The main categories are ``cmd`` for commands and ``evt`` for events.

Command Topics (\ ``cmd/...``\ )
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


* ``cmd/{deviceType}/{deviceId}/ctrl``\ : Used to send control commands to the device.
* ``cmd/{deviceType}/{deviceId}/st/...``\ : Used to request status updates from the device.
* ``cmd/{deviceType}/{...}/{...}/{clientId}/res/...``\ : Used by the device to send responses to status and control requests.

Event Topics (\ ``evt/...``\ )
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


* ``evt/{deviceType}/{deviceId}/app-connection``\ : Used to signal that an app has connected.

Control Messages (\ ``/ctrl``\ )
--------------------------------

Control messages are sent to the ``cmd/{deviceType}/{deviceId}/ctrl`` topic. The payload is a JSON object with the following structure:

.. code-block:: text

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": <command_code>,
       "deviceType": 52,
       "macAddress": "...",
       "mode": "{mode}",
       "param": [],
       "paramStr": ""
     },
     "requestTopic": "cmd/{deviceType}/{deviceId}/ctrl",
     "responseTopic": "cmd/{deviceType}/{...}/{...}/{clientId}/res",
     "sessionID": "..."
   }

**Note**: The ``command`` field uses different values for different control types:

* Power control: 33554433 (power-off) or 33554434 (power-on)
* DHW mode control: 33554437
* DHW temperature control: 33554464
* Reservation management: 16777226
* TOU (Time of Use) settings: 33554439
* Anti-Legionella control: 33554471 (disable) or 33554472 (enable)
* TOU enable/disable: 33554475 (disable) or 33554476 (enable)

Power Control
^^^^^^^^^^^^^


* 
  ``mode``: "power-on"


  * Turns the device on.
  * ``param``\ : ``[]``
  * ``paramStr``\ : ``""``

* 
  ``mode``: "power-off"


  * Turns the device off.
  * ``param``\ : ``[]``
  * ``paramStr``\ : ``""``

DHW Mode
^^^^^^^^


* ``mode``: "dhw-mode"

  * Changes the Domestic Hot Water (DHW) mode.
  * ``param``\ : ``[<mode_id>]`` or ``[<mode_id>, <vacation_days>]`` for vacation mode
  * ``paramStr``\ : ``""``

.. list-table::
   :header-rows: 1

   * - ``mode_id``
     - Mode
     - Description
   * - 1
     - Heat Pump Only
     - Most energy-efficient mode, using only the heat pump. Longest recovery time but uses least electricity.
   * - 2
     - Electric Only
     - Uses only electric heating elements. Least efficient but provides fastest recovery time.
   * - 3
     - Energy Saver
     - Balanced mode combining heat pump and electric heater as needed. Good balance of efficiency and recovery time.
   * - 4
     - High Demand
     - Maximum heating mode using all available components as needed for fastest recovery with higher capacity.
   * - 5
     - Vacation Mode
     - Suspends heating to save energy during extended absences. Requires vacation days parameter (e.g., ``[5, 4]`` for 4-day vacation).

.. note::
   Additional modes may appear in status responses:
   
   * Mode 0: Standby (device in idle state)
   * Mode 6: Power Off (device is powered off)

**Vacation Mode Parameters:**

When setting vacation mode (mode 5), provide two parameters:

* ``param[0]``: Mode ID (5)
* ``param[1]``: Number of vacation days (1-30)

Example: ``"param": [5, 7]`` sets vacation mode for 7 days.


Set DHW Temperature
^^^^^^^^^^^^^^^^^^^


* ``mode``: "dhw-temperature"

  * Sets the DHW temperature.
  * ``param``\ : ``[<temperature>]``
  * ``paramStr``\ : ``""``
  
  **IMPORTANT**: The temperature value in the message is **20 degrees Fahrenheit LOWER** than what displays on the device/app.
  
  * Message value: 121°F → Display shows: 141°F
  * Message value: 131°F → Display shows: 151°F (capped at 150°F max)
  
  Valid message range: ~95-131°F (displays as ~115-151°F, max 150°F)

Anti-Legionella Control
^^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/ctrl``
* **Command Codes**: 
  
  * ``33554471`` - Disable Anti-Legionella
  * ``33554472`` - Enable Anti-Legionella (with cycle period)

* ``mode``: "anti-leg-on" (for enable) or "anti-leg-off" (for disable)

  * Enables or configures Anti-Legionella protection
  * ``param``\ : ``[<period_days>]`` for enable (1-30 days), ``[]`` for disable
  * ``paramStr``\ : ``""``

**Enable Anti-Legionella Example:**

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 33554472,
       "deviceType": 52,
       "macAddress": "...",
       "mode": "anti-leg-on",
       "param": [7],
       "paramStr": ""
     },
     "requestTopic": "cmd/52/navilink-04786332fca0/ctrl",
     "responseTopic": "...",
     "sessionID": "..."
   }

**Observed Response After Enable:**

After sending the enable command, the device status shows:

* ``antiLegionellaUse`` changes from 1 (disabled) to 2 (enabled)
* ``antiLegionellaPeriod`` is set to the specified period value

**Disable Anti-Legionella Example:**

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 33554471,
       "deviceType": 52,
       "macAddress": "...",
       "mode": "anti-leg-off",
       "param": [],
       "paramStr": ""
     },
     "requestTopic": "cmd/52/navilink-04786332fca0/ctrl",
     "responseTopic": "...",
     "sessionID": "..."
   }

**Observed Response After Disable:**

After sending the disable command, the device status shows:

* ``antiLegionellaUse`` changes from 2 (enabled) to 1 (disabled)
* ``antiLegionellaPeriod`` retains its previous value

.. warning::
   Disabling Anti-Legionella protection may increase health risks. Legionella bacteria can grow
   in water heaters maintained at temperatures below 140°F (60°C). Consult local health codes
   before disabling this safety feature.

**Period Parameter:**

* Valid range: 1-30 days
* Typical value: 7 days (weekly disinfection)
* Longer periods may increase bacterial growth risk
* Shorter periods use more energy but provide better protection

Reservation Management
^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/ctrl/rsv/rd``
* **Command Code**: ``16777226``
* ``mode``: Not used for reservations

  * Manages programmed reservations for temperature changes
  * ``reservationUse``\ : ``1`` (enable) or ``2`` (disable)
  * ``reservation``\ : Array of reservation objects

**Reservation Object Fields:**

* ``enable``\ : ``1`` (enabled) or ``2`` (disabled)
* ``week``\ : Bitfield for days of week (e.g., ``124`` = weekdays, ``3`` = weekend)
* ``hour``\ : Hour (0-23)
* ``min``\ : Minute (0-59)
* ``mode``\ : Operation mode to set (1-5)
* ``param``\ : Temperature or other parameter (temperature is 20°F less than display value)

**Example Payload:**

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 16777226,
       "deviceType": 52,
       "macAddress": "...",
       "reservationUse": 1,
       "reservation": [
         {
           "enable": 2,
           "week": 24,
           "hour": 12,
           "min": 10,
           "mode": 1,
           "param": 98
         }
       ]
     },
     "requestTopic": "cmd/52/navilink-04786332fca0/ctrl/rsv/rd",
     "responseTopic": "...",
     "sessionID": "..."
   }

**Week Bitfield Values:**

The ``week`` field uses a bitfield where each bit represents a day:

* Bit 0 (1): Sunday
* Bit 1 (2): Monday
* Bit 2 (4): Tuesday
* Bit 3 (8): Wednesday
* Bit 4 (16): Thursday
* Bit 5 (32): Friday
* Bit 6 (64): Saturday

Common combinations:

* ``127`` (all days): Sunday through Saturday
* ``62`` (weekdays): Monday through Friday (2+4+8+16+32=62)
* ``65`` (weekend): Saturday and Sunday (64+1=65)

Common combinations:

* ``127`` (all days): Sunday through Saturday
* ``62`` (weekdays): Monday through Friday
* ``65`` (weekend): Saturday and Sunday
* ``24`` (mid-week): Wednesday and Thursday (8+16 = 24)

TOU (Time of Use) Settings
^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/ctrl/tou/rd``
* **Command Code**: ``33554439``
* Manages Time of Use energy pricing schedules

  * ``reservationUse``\ : ``1`` (enable) or ``2`` (disable)
  * ``reservation``\ : Array of TOU period objects
  * ``controllerSerialNumber``\ : Device controller serial number

**TOU Period Object Fields:**

* ``season``\ : Season identifier (bitfield, e.g., ``31`` for specific months)
* ``week``\ : Days of week bitfield (same as reservation management)
* ``startHour``\ : Start hour (0-23)
* ``startMinute``\ : Start minute (0-59)
* ``endHour``\ : End hour (0-23)
* ``endMinute``\ : End minute (0-59)
* ``priceMin``\ : Minimum price (integer, scaled by decimal point)
* ``priceMax``\ : Maximum price (integer, scaled by decimal point)
* ``decimalPoint``\ : Decimal places for price (e.g., ``5`` means divide by 100000)

**Example Payload:**

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 33554439,
       "deviceType": 52,
       "macAddress": "...",
       "controllerSerialNumber": "56496061BT22230408",
       "reservationUse": 2,
       "reservation": [
         {
           "season": 31,
           "week": 124,
           "startHour": 0,
           "startMinute": 0,
           "endHour": 14,
           "endMinute": 59,
           "priceMin": 34831,
           "priceMax": 34831,
           "decimalPoint": 5
         },
         {
           "season": 31,
           "week": 124,
           "startHour": 15,
           "startMinute": 0,
           "endHour": 15,
           "endMinute": 59,
           "priceMin": 36217,
           "priceMax": 36217,
           "decimalPoint": 5
         }
       ]
     },
     "requestTopic": "cmd/52/navilink-04786332fca0/ctrl/tou/rd",
     "responseTopic": "...",
     "sessionID": "..."
   }

**Price Calculation:**

The actual price is calculated as: ``price_value / (10 ^ decimalPoint)``

For example, with ``priceMin: 34831`` and ``decimalPoint: 5``: ``34831 / 100000 = 0.34831``

TOU Enable/Disable Control
^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/ctrl``
* **Command Codes**:
  
  * ``33554475`` - Disable TOU
  * ``33554476`` - Enable TOU

* ``mode``: "tou-off" or "tou-on"

  * Quick enable/disable of TOU functionality
  * ``param``\ : ``[]``
  * ``paramStr``\ : ``""``

**Enable TOU Example:**

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 33554476,
       "deviceType": 52,
       "macAddress": "...",
       "mode": "tou-on",
       "param": [],
       "paramStr": ""
     },
     "requestTopic": "cmd/52/navilink-04786332fca0/ctrl",
     "responseTopic": "...",
     "sessionID": "..."
   }

**Disable TOU Example:**

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 33554475,
       "deviceType": 52,
       "macAddress": "...",
       "mode": "tou-off",
       "param": [],
       "paramStr": ""
     },
     "requestTopic": "cmd/52/navilink-04786332fca0/ctrl",
     "responseTopic": "...",
     "sessionID": "..."
   }

.. note::
   These commands provide quick enable/disable without modifying the TOU schedule.
   The schedule configured via command 33554439 remains stored and can be re-enabled.

Response Messages (\ ``/res``\ )
--------------------------------

The device sends a response to a control message on the ``responseTopic`` specified in the request. The payload of the response contains the updated status of the device.

The ``sessionID`` in the response corresponds to the ``sessionID`` of the request.

The ``response`` object contains a ``status`` object that reflects the new state. For example, after a ``dhw-mode`` command with ``param`` ``[3]`` (Energy Saver), the ``dhwOperationSetting`` field in the ``status`` object will be ``3``. Note that ``operationMode`` may still show ``0`` (STANDBY) if the device is not currently heating. See :doc:`DEVICE_STATUS_FIELDS` for the important distinction between ``dhwOperationSetting`` (configured mode) and ``operationMode`` (current operational state).

Device Status Messages
----------------------

The device status is sent in the ``status`` object of the response messages. For a complete description of all fields found in the ``status`` object, see :doc:`DEVICE_STATUS_FIELDS`.

**Status Command Field:**

The ``status`` object includes a ``command`` field that indicates the type of status data:

* ``67108883`` (0x04000013) - Standard status snapshot
* ``67108892`` (0x0400001C) - Extended status snapshot

These command codes are informational and indicate which status fields are populated in the response.

**Vacation Mode Status Fields:**

When the device is in vacation mode (``dhwOperationSetting: 5``), the status includes:

* ``vacationDaySetting``\ : Total vacation days configured
* ``vacationDayElapsed``\ : Days elapsed since vacation mode started
* ``dhwOperationSetting``\ : Set to ``5`` when in vacation mode
* ``operationMode``\ : Current operational state (typically ``0`` for standby during vacation)

**Reservation Status Fields:**

* ``programReservationType``\ : Type of reservation program (0 = none, 1 = active)
* ``reservationUse``\ : Whether reservations are enabled (1 = enabled, 2 = disabled)

**Anti-Legionella Status Fields:**

The device includes Anti-Legionella protection that periodically heats water to 140°F (60°C) to prevent bacterial growth:

* ``antiLegionellaUse``\ : Anti-Legionella enable flag 
  
  * **1** = disabled
  * **2** = enabled

* ``antiLegionellaPeriod``\ : Days between Anti-Legionella cycles (typically 7 days, range 1-30)
* ``antiLegionellaOperationBusy``\ : Currently performing Anti-Legionella cycle 
  
  * **1** = OFF (not currently running)
  * **2** = ON (currently heating to disinfection temperature)

.. note::
   Anti-Legionella is a safety feature that heats the water tank to 140°F at programmed intervals
   to kill Legionella bacteria. This requires a mixing valve to prevent scalding at taps.
   The feature can be configured for 1-30 day intervals. When the 
   enable command (33554472) is sent with a period parameter, ``antiLegionellaUse`` changes 
   from 1 (disabled) to 2 (enabled), and ``antiLegionellaPeriod`` is updated to the specified value.

Status Request Messages
-----------------------

Status request messages are sent to topics starting with ``cmd/{deviceType}/{deviceId}/st/``. The payload is a JSON object with a ``request`` object that contains the command.

Request Device Information
^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/st/did``
* **Description**: Request device information.
* **Command Code**: ``16777217``
* **Payload**:

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 16777217,
       "deviceType": 52,
       "macAddress": "..."
     },
     "requestTopic": "...",
     "responseTopic": "...",
     "sessionID": "..."
   }

Request General Device Status
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/st``
* **Description**: Request general device status.
* **Command Code**: ``16777219``
* **Payload**:

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 16777219,
       "deviceType": 52,
       "macAddress": "..."
     },
     "requestTopic": "...",
     "responseTopic": "...",
     "sessionID": "..."
   }

Request Reservation Information
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/st/rsv/rd``
* **Description**: Request reservation information.
* **Command Code**: ``16777222``
* **Payload**:

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 16777222,
       "deviceType": 52,
       "macAddress": "..."
     },
     "requestTopic": "...",
     "responseTopic": "...",
     "sessionID": "..."
   }

Request Daily Energy Usage Data
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/st/energy-usage-daily-query/rd``
* **Description**: Request daily energy usage data for specified month(s).
* **Command Code**: ``16777225``
* **Payload**:

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 16777225,
       "deviceType": 52,
       "macAddress": "...",
       "month": [9],
       "year": 2025
     },
     "requestTopic": "...",
     "responseTopic": "...",
     "sessionID": "..."
   }

* **Response Topic**: ``cmd/{deviceType}/{clientId}/res/energy-usage-daily-query/rd``
* **Response Fields**:
  
  * ``typeOfUsage``\ : Type of usage data (1 = daily)
  * ``total``\ : Total energy usage across queried period
    
    * ``heUsage``\ : Total heat element energy consumption (Wh)
    * ``hpUsage``\ : Total heat pump energy consumption (Wh)
    * ``heTime``\ : Total heat element operating time (hours)
    * ``hpTime``\ : Total heat pump operating time (hours)
  
  * ``usage``\ : Array of monthly data
    
    * ``year``\ : Year
    * ``month``\ : Month (1-12)
    * ``data``\ : Array of daily usage (one per day of month)
      
      * ``heUsage``\ : Heat element energy consumption for that day (Wh)
      * ``hpUsage``\ : Heat pump energy consumption for that day (Wh)
      * ``heTime``\ : Heat element operating time for that day (hours)
      * ``hpTime``\ : Heat pump operating time for that day (hours)

Request Software Download Information
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/st/dl-sw-info``
* **Description**: Request software download information.
* **Command Code**: ``16777227``
* **Payload**:

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 16777227,
       "deviceType": 52,
       "macAddress": "..."
     },
     "requestTopic": "...",
     "responseTopic": "...",
     "sessionID": "..."
   }

Request Reservation Information
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/ctrl/rsv/rd``
* **Description**: Request current reservation settings.
* **Command Code**: ``16777226``
* **Payload**:

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 16777226,
       "deviceType": 52,
       "macAddress": "..."
     },
     "requestTopic": "cmd/52/navilink-{macAddress}/ctrl/rsv/rd",
     "responseTopic": "...",
     "sessionID": "..."
   }

* **Response Topic**: ``cmd/{deviceType}/{...}/res/rsv/rd``
* **Response Fields**: Contains ``reservationUse`` and ``reservation`` array with current settings

Request TOU Information
^^^^^^^^^^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/ctrl/tou/rd``
* **Description**: Request current Time of Use pricing settings.
* **Command Code**: ``33554439``
* **Payload**:

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 33554439,
       "deviceType": 52,
       "macAddress": "...",
       "controllerSerialNumber": "..."
     },
     "requestTopic": "cmd/52/navilink-{macAddress}/ctrl/tou/rd",
     "responseTopic": "...",
     "sessionID": "..."
   }

* **Response Topic**: ``cmd/{deviceType}/{...}/res/tou/rd``
* **Response Fields**: Contains ``reservationUse`` and ``reservation`` array with current TOU schedule

End Connection
^^^^^^^^^^^^^^

* **Topic**: ``cmd/{deviceType}/{deviceId}/st/end``
* **Description**: End the connection.
* **Command Code**: ``16777218``
* **Payload**:

.. code-block:: json

   {
     "clientID": "...",
     "protocolVersion": 2,
     "request": {
       "additionalValue": "...",
       "command": 16777218,
       "deviceType": 52,
       "macAddress": "..."
     },
     "requestTopic": "...",
     "responseTopic": "...",
     "sessionID": "..."
   }

Energy Usage Query Details
^^^^^^^^^^^^^^^^^^^^^^^^^^

The energy usage query (command ``16777225``\ ) provides historical energy consumption data. This is used by the "EMS" (Energy Management System) tab in the Navien app.

**Request Parameters**\ :


* ``month``\ : Array of months to query (e.g., ``[7, 8, 9]`` for July-September)
* ``year``\ : Year to query (e.g., ``2025``\ )

**Response Data**\ :

The response contains:


* **Total statistics** for the entire queried period
* **Daily breakdown** for each day of each requested month

Each data point includes:


* Energy consumption in Watt-hours (Wh) for heat pump (\ ``hpUsage``\ ) and electric elements (\ ``heUsage``\ )
* Operating time in hours for heat pump (\ ``hpTime``\ ) and electric elements (\ ``heTime``\ )

**Example Usage**\ :

.. code-block:: python

   # Request September 2025 energy data
   await mqtt_client.request_energy_usage(
       device_id="aabbccddeeff",
       year=2025,
       months=[9]
   )

   # Subscribe to energy usage responses
   def on_energy_usage(energy: EnergyUsageResponse):
       print(f"Total Usage: {energy.total.total_usage} Wh")
       print(f"Heat Pump: {energy.total.heat_pump_percentage:.1f}%")
       print(f"Heat Element: {energy.total.heat_element_percentage:.1f}%")
   
   await mqtt_client.subscribe_energy_usage(device_id, on_energy_usage)

Response Messages
-----------------

Response messages are published to topics matching the pattern ``cmd/{deviceType}/{...}/res/...``\ . The response structure generally includes:

.. code-block:: text

   {
     "protocolVersion": 2,
     "clientID": "...",
     "sessionID": "...",
     "requestTopic": "...",
     "response": {
       "deviceType": 52,
       "macAddress": "...",
       "additionalValue": "...",
       ...
     }
   }

Command Code Reference
----------------------

Complete reference of all MQTT command codes:

**Power Control**

.. list-table::
   :header-rows: 1
   :widths: 15 40 45

   * - Code
     - Purpose
     - Mode/Notes
   * - 33554433
     - Power Off
     - mode: "power-off"
   * - 33554434
     - Power On
     - mode: "power-on"

**DHW Control**

.. list-table::
   :header-rows: 1
   :widths: 15 40 45

   * - Code
     - Purpose
     - Mode/Notes
   * - 33554437
     - DHW Mode Change
     - mode: "dhw-mode", param: [mode_id] or [5, days] for vacation
   * - 33554464
     - DHW Temperature
     - mode: "dhw-temperature", param: [temp] (20°F offset)

**Anti-Legionella Control**

.. list-table::
   :header-rows: 1
   :widths: 15 40 45

   * - Code
     - Purpose
     - Mode/Notes
   * - 33554471
     - Disable Anti-Legionella
     - mode: "anti-leg-off", param: []
   * - 33554472
     - Enable Anti-Legionella
     - mode: "anti-leg-on", param: [period_days] (1-30)

**TOU Control**

.. list-table::
   :header-rows: 1
   :widths: 15 40 45

   * - Code
     - Purpose
     - Mode/Notes
   * - 33554439
     - Configure TOU Schedule
     - Topic: /ctrl/tou/rd, full schedule configuration
   * - 33554475
     - Disable TOU
     - mode: "tou-off", quick toggle without changing schedule
   * - 33554476
     - Enable TOU
     - mode: "tou-on", quick toggle without changing schedule

**Reservation Management**

.. list-table::
   :header-rows: 1
   :widths: 15 40 45

   * - Code
     - Purpose
     - Mode/Notes
   * - 16777226
     - Manage Reservations
     - Topic: /ctrl/rsv/rd, schedule temperature/mode changes

**Status Requests**

.. list-table::
   :header-rows: 1
   :widths: 15 40 45

   * - Code
     - Purpose
     - Mode/Notes
   * - 16777217
     - Device Information
     - Topic: /st/did, returns feature data
   * - 16777219
     - Device Status
     - Topic: /st, returns current status
   * - 16777225
     - Energy Usage Query
     - Topic: /st/energy-usage-daily-query/rd
   * - 16777227
     - Software Download Info
     - Topic: /st/dl-sw-info
   * - 16777218
     - End Connection
     - Topic: /st/end

**Status Response Indicators**

.. list-table::
   :header-rows: 1
   :widths: 15 40 45

   * - Code
     - Purpose
     - Mode/Notes
   * - 67108883
     - Standard Status Type
     - Appears in response status.command field
   * - 67108892
     - Extended Status Type
     - Appears in response status.command field

**Command Code Format**

Command codes follow a pattern based on their category:

* ``0x01......`` (16777216+) - Request/Query commands
* ``0x02......`` (33554432+) - Control commands
* ``0x04......`` (67108864+) - Status response type indicators
