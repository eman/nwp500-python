=====================================
Home Assistant Integration Guide
=====================================

This guide provides best practices for integrating the nwp500-python library with Home Assistant, with a focus on handling dynamic unit conversions based on device temperature preferences.

Overview
========

The nwp500-python library automatically converts device values to the user's preferred temperature unit (Celsius or Fahrenheit) based on the device's ``temperature_type`` setting. This guide shows how Home Assistant integrations should handle these dynamic units to provide a seamless user experience.

Key Concepts
============

**Dynamic Unit Conversion**

All temperature, flow rate, and volume values from ``DeviceStatus`` are automatically converted to the device's preferred unit:

- **Temperature fields**: Converted to °C or °F
- **Flow rate fields**: Converted to LPM or GPM
- **Volume fields**: Converted to L or gallons

This conversion happens at the model level via Pydantic wrap validators, so values are already in the correct unit when you receive them.

**Unit Metadata**

Each model field includes metadata in ``json_schema_extra`` that describes its unit behavior:

.. code-block:: python

   from nwp500 import DeviceStatus

   # Access field metadata
   field_info = DeviceStatus.model_fields['dhw_temperature']
   extra = field_info.json_schema_extra

   # Metadata includes:
   # - "device_class": "temperature" (Home Assistant device class)
   # - "unit_of_measurement": "°F" (default/fallback unit)

**Query Device Unit Preference**

Use the ``get_field_unit()`` method to get the correct unit suffix for any field based on the device's current temperature preference:

.. code-block:: python

   # Get the correct unit for a field
   status = device_status  # DeviceStatus instance
   unit = status.get_field_unit('dhw_temperature')

   # Returns: " °C" or " °F" depending on device's temperature_type
   # Returns: " LPM" or " GPM" for flow rate fields
   # Returns: " L" or " gal" for volume fields
   # Returns: "" for static unit fields

Home Assistant Integration Pattern
==================================

For Home Assistant integrations, implement dynamic unit handling in the sensor entity class:

Basic Pattern
^^^^^^^^^^^^^

.. code-block:: python

   from homeassistant.components.sensor import SensorEntity
   from typing import Any

   class NWP500Sensor(SensorEntity):
       """Navien NWP500 sensor with dynamic units."""

       @property
       def native_unit_of_measurement(self) -> str | None:
           """Return dynamic unit based on device temperature preference.

           This property queries the device's current temperature_type setting
           and returns the appropriate unit for display in Home Assistant.

           Returns:
               Unit string (e.g., "°C", "LPM", "L") or None for unitless values
           """
           if not (status := self._status):
               # Fallback to static unit if device status not available
               return self.entity_description.native_unit_of_measurement

           # Get dynamic unit from device based on its temperature preference
           unit = status.get_field_unit(self.entity_description.attr_name)
           return unit.strip() if unit else None

Complete Example
^^^^^^^^^^^^^^^^

Here's a complete example showing how to implement dynamic units in a Home Assistant sensor:

.. code-block:: python

   from dataclasses import dataclass
   from homeassistant.components.sensor import (
       SensorDeviceClass,
       SensorEntity,
       SensorEntityDescription,
       SensorStateClass,
   )
   from homeassistant.const import UnitOfTemperature
   from homeassistant.core import HomeAssistant
   from typing import Any

   @dataclass(frozen=True)
   class NWP500SensorEntityDescription(SensorEntityDescription):
       """Describes NWP500 sensor entity."""
       attr_name: str = ""  # Model attribute name for get_field_unit()
       value_fn: callable | None = None  # Optional value extractor

   class NWP500TemperatureSensor(SensorEntity):
       """Temperature sensor with dynamic Celsius/Fahrenheit display."""

       entity_description: NWP500SensorEntityDescription

       def __init__(self, coordinator, mac_address: str, device, description):
           """Initialize sensor."""
           self.coordinator = coordinator
           self.mac_address = mac_address
           self.device = device
           self.entity_description = description
           self._attr_unique_id = f"{mac_address}_{description.key}"
           self._attr_name = f"{device.device_info.name} {description.name}"

       @property
       def _status(self):
           """Get current device status from coordinator."""
           if self.coordinator.data and self.mac_address in self.coordinator.data:
               return self.coordinator.data[self.mac_address].get("status")
           return None

       @property
       def native_value(self) -> float | None:
           """Return the sensor value."""
           if not self._status:
               return None

           if self.entity_description.value_fn:
               return self.entity_description.value_fn(self._status)

           # Default: get attribute by name
           return getattr(
               self._status,
               self.entity_description.attr_name,
               None
           )

       @property
       def native_unit_of_measurement(self) -> str | None:
           """Return dynamic unit based on device temperature preference.

           This ensures Home Assistant displays the correct unit symbol
           (°C or °F) based on the device's current setting.
           """
           if not self._status:
               return self.entity_description.native_unit_of_measurement

           # Query device for correct unit based on temperature_type
           unit = self._status.get_field_unit(self.entity_description.attr_name)
           return unit.strip() if unit else None

       @property
       def available(self) -> bool:
           """Sensor is available when device has status."""
           return self._status is not None

   # Example sensor descriptions
   TEMPERATURE_SENSORS = (
       NWP500SensorEntityDescription(
           key="dhw_temperature",
           name="DHW Temperature",
           device_class=SensorDeviceClass.TEMPERATURE,
           state_class=SensorStateClass.MEASUREMENT,
           native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,  # Fallback
           attr_name="dhw_temperature",  # Used by get_field_unit()
       ),
       NWP500SensorEntityDescription(
           key="tank_upper_temperature",
           name="Tank Upper Temperature",
           device_class=SensorDeviceClass.TEMPERATURE,
           state_class=SensorStateClass.MEASUREMENT,
           native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,  # Fallback
           attr_name="tank_upper_temperature",
       ),
   )

Configuration Setup
^^^^^^^^^^^^^^^^^^^

When creating the entity descriptions, include the attribute name for each field:

.. code-block:: python

   def create_sensor_descriptions() -> tuple[NWP500SensorEntityDescription, ...]:
       """Create sensor descriptions from configuration."""
       descriptions = []

       SENSOR_CONFIG = {
           "dhw_temperature": {
               "name": "DHW Temperature",
               "device_class": "temperature",
               "attr": "dhw_temperature",  # This is the key!
               "unit": "°F",  # Fallback unit
           },
           "current_dhw_flow_rate": {
               "name": "Current DHW Flow Rate",
               "device_class": None,
               "attr": "current_dhw_flow_rate",
               "unit": "GPM",  # Will be LPM or GPM dynamically
           },
       }

       for key, config in SENSOR_CONFIG.items():
           descriptions.append(
               NWP500SensorEntityDescription(
                   key=key,
                   name=config["name"],
                   device_class=config.get("device_class"),
                   native_unit_of_measurement=config.get("unit"),
                   attr_name=config["attr"],  # Store for get_field_unit()
               )
           )

       return tuple(descriptions)

How It Works
============

1. **Device Status Retrieved**: The coordinator receives updated ``DeviceStatus`` from MQTT
2. **Unit Query**: When Home Assistant requests ``native_unit_of_measurement``, the sensor calls ``status.get_field_unit(attr_name)``
3. **Dynamic Resolution**: The method checks the device's ``temperature_type`` and returns the appropriate unit
4. **Display Update**: Home Assistant automatically updates the unit display without needing a restart

Example Flow
^^^^^^^^^^^^

.. code-block:: python

   # Device is in Fahrenheit mode (temperature_type = FAHRENHEIT)
   status = DeviceStatus(
       temperature_type=TemperatureType.FAHRENHEIT,
       dhw_temperature=120.0,
       current_dhw_flow_rate=2.5,
   )

   # Sensor queries units
   temp_unit = status.get_field_unit('dhw_temperature')
   # Returns: " °F"

   flow_unit = status.get_field_unit('current_dhw_flow_rate')
   # Returns: " GPM"

   # Home Assistant renders:
   # DHW Temperature: 120.0 °F
   # Current DHW Flow Rate: 2.5 GPM

   # Later, device switches to Celsius mode
   status_celsius = DeviceStatus(
       temperature_type=TemperatureType.CELSIUS,
       dhw_temperature=48.9,  # Converted from 120°F
       current_dhw_flow_rate=0.66,  # Converted from 2.5 GPM
   )

   # Units automatically update
   temp_unit = status_celsius.get_field_unit('dhw_temperature')
   # Returns: " °C"

   flow_unit = status_celsius.get_field_unit('current_dhw_flow_rate')
   # Returns: " LPM"

   # Home Assistant renders:
   # DHW Temperature: 48.9 °C
   # Current DHW Flow Rate: 0.66 LPM

Supported Dynamic Fields
========================

The following field types support dynamic unit conversion:

**Temperature Fields**
- All temperature measurement fields (e.g., ``dhw_temperature``, ``tank_upper_temperature``)
- Returns: " °C" or " °F"
- Set ``device_class="temperature"`` in sensor configuration

**Flow Rate Fields**
- ``current_dhw_flow_rate``, ``recirc_dhw_flow_rate``
- Returns: " LPM" or " GPM"
- Set ``device_class="flow_rate"`` in sensor configuration

**Volume Fields**
- ``cumulated_dhw_flow_rate`` and similar volume measurements
- Returns: " L" or " gal"
- Set ``device_class="water"`` in sensor configuration

**Static Unit Fields**
- Power (W), Energy (Wh), Signal Strength (dBm), etc.
- Returns: Unit as-is (no dynamic conversion)
- Use standard Home Assistant unit constants

API Reference
=============

DeviceStatus.get_field_unit()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   def get_field_unit(self, field_name: str) -> str:
       """Get the correct unit suffix for a field based on device temperature preference.

       This method resolves dynamic units for temperature, flow rate, and volume fields
       that change based on the device's temperature_type setting (Celsius/Fahrenheit).

       Args:
           field_name (str): Name of the field to get the unit for

       Returns:
           str: Unit string (e.g., " °C", " LPM", " L") or empty string if field not found

       Examples:
           >>> status = DeviceStatus(temperature_type=TemperatureType.CELSIUS, ...)
           >>> status.get_field_unit('dhw_temperature')
           ' °C'
           >>> status.get_field_unit('current_dhw_flow_rate')
           ' LPM'
           >>> status.get_field_unit('current_inst_power')
           ''  # Static unit, use field metadata
       """

Troubleshooting
===============

**Units Not Updating When Device Preference Changes**

Ensure that:
1. Device status is being updated via coordinator
2. The sensor's ``_status`` property returns the latest status
3. Home Assistant has permission to refresh entity attributes

**Wrong Unit Displayed**

Check that:
1. The ``attr_name`` in ``SensorEntityDescription`` matches the actual model attribute name
2. The device's ``temperature_type`` is correctly set
3. No caching is preventing the unit update

**Field Not Found**

Ensure:
1. The field name matches exactly (case-sensitive)
2. The field exists in ``DeviceStatus`` model
3. Check nwp500-python documentation for field names

Best Practices
==============

1. **Always Store attr_name**: Include the field name in sensor descriptions for unit resolution
2. **Use Fallback Units**: Provide default units in entity descriptions for offline scenarios
3. **Check Device Status**: Always verify status is available before querying units
4. **Cache Sparingly**: Avoid caching unit values since they can change dynamically
5. **Handle Enum Fields**: For enum fields without units, return ``None`` from ``native_unit_of_measurement``

See Also
========

- :doc:`../python_api/models` - Complete model reference
- :doc:`../protocol/data_conversions` - Detailed conversion formulas
- :doc:`../enumerations` - TemperatureType and other enumerations
