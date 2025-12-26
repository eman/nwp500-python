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

Key Enum Values
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

Control Topic
^^^^^^^^^^^^^

``cmd/RTU50E-H/{deviceId}/ctrl``

Sends JSON commands to the device.

Status Topic
^^^^^^^^^^^^

``cmd/RTU50E-H/{deviceId}/st``

Receives JSON status updates from the device.

Message Format
--------------

All MQTT payloads are JSON-formatted strings:

.. code-block:: json

    {
      "header": {
        "msg_id": "1",
        "cloud_msg_type": "0x1"
      },
      "body": {
        // Message-specific fields
      }
    }

Common Command Codes
--------------------

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Code
     - Command
     - Body Fields
   * - **0x11**
     - Set DHW Temperature
     - ``dhwSetTempH``, ``dhwSetTempL``
   * - **0x21**
     - Set Operation Mode
     - ``dhwOperationSetting``
   * - **0x31**
     - Set Power
     - ``power``

See :doc:`mqtt_protocol` for full command details.
