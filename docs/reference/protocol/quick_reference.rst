Protocol Quick Reference
========================

This document serves as a "cheat sheet" for developers working with the Navien
device protocol. It documents the non-standard boolean logic, key enumerations,
and common command codes used throughout the system.

Boolean Values
--------------

The device uses non-standard boolean encoding in many status fields:

.. list-table::
   :header-rows: 1
   :widths: 10 20 70

   * - Value
     - Meaning
     - Notes
   * - **1**
     - OFF / False
     - Standard: False value. Used for power and most feature flags.
   * - **2**
     - ON / True
     - Standard: True value.

**Exception:** The ``touStatus`` field uses 0/1 encoding (0=disabled, 1=enabled) instead of the standard 1/2 encoding.

**Why 1 & 2?**
This likely stems from legacy firmware design where:

* 0 = reserved/error/null
* 1 = off/false/disabled
* 2 = on/true/enabled

**Example: Device Power State**

.. code-block:: json

    {
      "power": 2  // Device is ON
    }

When parsed via ``DeviceStatus``, this becomes ``status.power == True``.

Enum Values
---------------

CurrentOperationMode
^^^^^^^^^^^^^^^^^^^^

Used in real-time status to show what the device is currently doing.

.. list-table::
   :header-rows: 1
   :widths: 10 20 70

   * - Value
     - Mode
     - Description
   * - **0**
     - Standby
     - Device is idle (not heating). Visible as "Idle".
   * - **32**
     - Heat Pump
     - Compressor is active. Visible as "Heating (HP)".
   * - **64**
     - Energy Saver
     - Hybrid efficiency mode active. Visible as "Heating (Eff)".
   * - **96**
     - High Demand
     - Hybrid boost mode active. Visible as "Heating (Boost)".

.. note::
   These are actual status values, not sequential. Gaps are reserved or correspond
   to error states.

DhwOperationSetting
^^^^^^^^^^^^^^^^^^^

User-selected heating mode preference.

.. list-table::
   :header-rows: 1
   :widths: 10 20 70

   * - Value
     - Mode
     - Description
   * - **1**
     - Heat Pump Only
     - High efficiency, slow recovery.
   * - **2**
     - Electric Only
     - Low efficiency, fast recovery.
   * - **3**
     - Energy Saver
     - **Default.** Balanced hybrid mode.
   * - **4**
     - High Demand
     - Hybrid boost for faster recovery.
   * - **5**
     - Vacation
     - Heating suspended to save energy.
   * - **6**
     - Power Off
     - Device is logically powered off.

MQTT Topics
-----------

Every request is published to a device-keyed topic; replies land on the
topic named in the request envelope.

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Topic
     - Purpose
   * - ``cmd/52/navilink-{mac}/ctrl``
     - Control commands (mode/param payloads)
   * - ``cmd/52/navilink-{mac}/st``, ``.../st/did``
     - Status and device info requests (replies on the control ack topic)
   * - ``cmd/52/navilink-{mac}/st/{query}/rd``
     - Queries (``rsv``, ``recirc-rsv``, ``td``, ``energy-usage-*-query``)
   * - ``cmd/52/navilink-{mac}/st/dl-sw-info``
     - Firmware download info request
   * - ``cmd/52/navilink-{mac}/st/end``
     - Session end (no reply observed)
   * - ``cmd/52/navilink-{mac}/{clientId}/res``
     - Control acknowledgement carrying a status object
   * - ``cmd/52/{clientId}/res/{query}/rd``
     - Replies to ``rsv``, ``recirc-rsv`` and the energy queries
   * - ``cmd/52/{homeSeq}/{userSeq}/{clientId}/res/td/rd``
     - Diagnostics reply (decoded JSON only for this topic form)
   * - ``cmd/52/navilink-{mac}/res/dl-sw-info``
     - Firmware download info reply (device-keyed)
   * - ``evt/52/navilink-{mac}/app-connection``
     - App connection event

Message Format
--------------

All MQTT payloads are JSON envelopes around a ``request`` object:

.. code-block:: json

    {
      "clientID": "navien-client-1996271a",
      "sessionID": "1759355471479",
      "protocolVersion": 2,
      "requestTopic": "cmd/52/navilink-04786332fca0/ctrl",
      "responseTopic": "cmd/52/navilink-04786332fca0/navien-client-1996271a/res",
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

Common Command Codes
--------------------

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Code
     - Command
     - Payload
   * - **16777219**
     - Status request
     - none (topic ``st``)
   * - **16777217**
     - Device info request
     - none (topic ``st/did``)
   * - **33554434** / **33554433**
     - Power on / off
     - ``mode`` ``power-on`` / ``power-off``
   * - **33554437**
     - Set operation mode
     - ``mode`` ``dhw-mode``, ``param`` ``[mode]`` (``[5, days]`` for vacation)
   * - **33554464**
     - Set DHW temperature
     - ``mode`` ``dhw-temperature``, ``param`` ``[half-degrees C]``
   * - **16777228**
     - Installer diagnostics
     - none (topic ``st/td/rd``)

See :doc:`mqtt_protocol` for full command details.
