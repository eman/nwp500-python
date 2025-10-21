
Firmware Version Tracking
=========================

This document tracks firmware versions and the device status fields they introduce or modify.

Purpose
-------

The Navien NWP500 water heater receives firmware updates that may introduce new status fields or modify existing behavior. This tracking system helps:

1. **Graceful Degradation**: The library can handle unknown fields from newer firmware versions without crashing
2. **User Reporting**: Users can report firmware versions when encountering new fields
3. **Library Updates**: Maintainers can prioritize adding support for new fields based on firmware adoption
4. **Documentation**: Track when fields were introduced for better device compatibility documentation

How It Works
------------

When the library encounters unknown fields in device status messages:

1. It checks if the field is documented in ``constants.KNOWN_FIRMWARE_FIELD_CHANGES``
2. If the field is known but not implemented, it logs an INFO message
3. If the field is completely unknown, it logs a WARNING message asking users to report their firmware version
4. The unknown field is safely ignored, and the library continues to function

Known Firmware Field Changes
-----------------------------

The following table tracks known fields that have been introduced in firmware updates:

.. list-table::
   :header-rows: 1
   :widths: 20 15 15 50

   * - Field Name
     - First Observed
     - Conversion
     - Description
   * - ``heatMinOpTemperature``
     - Controller: 184614912, WiFi: 34013184
     - ``raw + 20``
     - Minimum operating temperature for the heating element. Sets the lower threshold at which the heating element can operate.

Reporting New Fields
--------------------

If you see a warning message about unknown fields, please help us improve the library by reporting:

1. **The unknown field name(s)** from the warning message
2. **Your device firmware versions**:
   
   - Controller SW Version (``controllerSwVersion``)
   - Panel SW Version (``panelSwVersion``)
   - WiFi SW Version (``wifiSwVersion``)

3. **Sample raw values** for the unknown field (if possible)
4. **Your device model** (e.g., NWP500)

You can get your firmware versions by running:

.. code-block:: python

   from nwp500.mqtt_client import NavienMQTTClient
   from nwp500.auth import NavienAuthClient
   from nwp500.api_client import NavienAPIClient
   import asyncio
   import os

   async def get_firmware():
       async with NavienAuthClient(
           os.getenv("NAVIEN_EMAIL"),
           os.getenv("NAVIEN_PASSWORD")
       ) as auth:
           api = NavienAPIClient(auth)
           devices = await api.get_devices()
           device = devices[0]
           
           mqtt = NavienMQTTClient(auth, device.mac_address, device.device_type)
           await mqtt.connect()
           
           def feature_callback(feature):
               print(f"Controller SW: {feature.controllerSwVersion}")
               print(f"Panel SW: {feature.panelSwVersion}")
               print(f"WiFi SW: {feature.wifiSwVersion}")
           
           await mqtt.request_device_info(feature_callback)
           await asyncio.sleep(2)
           await mqtt.disconnect()

   asyncio.run(get_firmware())

Or using the CLI (if implemented):

.. code-block:: bash

   nwp-cli --device-info

Please report issues at: https://github.com/eman/nwp500-python/issues

Adding New Fields
-----------------

When adding support for a newly discovered field:

1. Add the field to ``DeviceStatus`` dataclass in ``models.py``
2. Add appropriate conversion logic in ``DeviceStatus.from_dict()``
3. Document the field in ``DEVICE_STATUS_FIELDS.rst``
4. Update ``constants.KNOWN_FIRMWARE_FIELD_CHANGES`` with field metadata
5. Update this tracking document with firmware version information
6. Remove the field from ``KNOWN_FIRMWARE_FIELD_CHANGES`` once implemented

Example entry in ``constants.py``:

.. code-block:: python

   KNOWN_FIRMWARE_FIELD_CHANGES = {
       "newFieldName": {
           "introduced_in": "controller: 123, panel: 456, wifi: 789",
           "description": "What this field represents",
           "conversion": "raw + 20",  # or "raw / 10.0", "bool (1=OFF, 2=ON)", etc.
       },
   }

Firmware Version History
------------------------

This section tracks observed firmware versions and their associated changes.

**Latest Known Versions** (as of 2025-10-15):

- Controller SW Version: 184614912
- Panel SW Version: 0 (not used on NWP500 devices)
- WiFi SW Version: 34013184

**Observed Features:**

- These versions include support for ``heatMinOpTemperature`` field
- Recirculation pump fields (``recirc*``) are present but not yet documented

*Note: This tracking system was implemented on 2025-10-15. Historical firmware information is not available.*

Contributing
------------

If you have information about different firmware versions or field changes, please submit a pull request or open an issue. Your contributions help make this library more robust and compatible with different device configurations.
