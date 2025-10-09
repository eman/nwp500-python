
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
  * ``param``\ : ``[<mode_id>]``
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

.. note::
   Additional modes may appear in status responses:
   
   * Mode 0: Standby (device in idle state)
   * Mode 6: Power Off (device is powered off)


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

Response Messages (\ ``/res``\ )
--------------------------------

The device sends a response to a control message on the ``responseTopic`` specified in the request. The payload of the response contains the updated status of the device.

The ``sessionID`` in the response corresponds to the ``sessionID`` of the request.

The ``response`` object contains a ``status`` object that reflects the new state. For example, after a ``dhw-mode`` command with ``param`` ``[3]``\ , the ``dhwOperationSetting`` in the ``status`` object of the response will be ``3``.

Device Status Messages
----------------------

The device status is sent in the ``status`` object of the response messages. For a complete description of all fields found in the ``status`` object, see :doc:`DEVICE_STATUS_FIELDS`.

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
