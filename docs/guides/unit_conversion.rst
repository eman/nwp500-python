=======================
Dynamic Unit Conversion
=======================

The nwp500-python library implements a sophisticated dynamic unit conversion system that automatically converts all temperature, flow rate, and volume measurements between metric (Celsius, LPM, Liters) and imperial (Fahrenheit, GPM, Gallons) units based on the device's configured ``temperature_type`` setting.

Overview
========

All measurements in the library are stored and transmitted by the device in metric units (Celsius, LPM, Liters). When you retrieve a ``DeviceStatus`` or ``DeviceFeature`` object, values are automatically converted to the user's preferred unit system:

- **Celsius devices**: Values remain in metric (°C, LPM, L)
- **Fahrenheit devices**: Values are converted to imperial (°F, GPM, gal)

This conversion happens transparently at the model validation layer, so you always receive values in the correct unit for display.

Quick Start
===========

Basic Usage
-----------

.. code-block:: python

    from nwp500 import DeviceStatus, TemperatureType

    # Device configured for Celsius
    status_celsius = DeviceStatus(
        temperature_type=TemperatureType.CELSIUS,
        dhw_temperature=120,  # raw: 60°C (half-degree encoded)
    )

    print(status_celsius.dhw_temperature)  # Output: 60.0

    # Get the unit for display
    unit = status_celsius.get_field_unit('dhw_temperature')
    print(f"Temperature: {status_celsius.dhw_temperature}{unit}")
    # Output: Temperature: 60.0 °C

    # Same device, now in Fahrenheit mode
    status_fahrenheit = DeviceStatus(
        temperature_type=TemperatureType.FAHRENHEIT,
        dhw_temperature=120,  # raw: 60°C, converted to 140°F
    )

    print(status_fahrenheit.dhw_temperature)  # Output: 140.0

    unit = status_fahrenheit.get_field_unit('dhw_temperature')
    print(f"Temperature: {status_fahrenheit.dhw_temperature}{unit}")
    # Output: Temperature: 140.0 °F

Get Field Units
---------------

Use the ``get_field_unit()`` method to retrieve the correct unit suffix for any field:

.. code-block:: python

    status = device_status

    # Temperature field
    temp_unit = status.get_field_unit('dhw_temperature')
    # Returns: " °C" or " °F"

    # Flow rate field
    flow_unit = status.get_field_unit('current_dhw_flow_rate')
    # Returns: " LPM" or " GPM"

    # Volume field
    volume_unit = status.get_field_unit('cumulated_dhw_flow_rate')
    # Returns: " L" or " gal"

    # Static unit field (no conversion)
    power_unit = status.get_field_unit('current_inst_power')
    # Returns: ""  (check metadata for static unit)

How It Works
============

Conversion Process
------------------

1. **Raw Device Value**: Device sends all measurements in metric units
2. **Model Instantiation**: Pydantic validates and converts the value
3. **Wrap Validator Checks**: Converter checks ``temperature_type`` field
4. **Unit Conversion**: If Fahrenheit mode, applies conversion formula
5. **Stored Value**: Model stores converted value in correct unit

Example Conversion Flow
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Device data from API/MQTT (always metric)
    raw_data = {
        'temperature_type': 2,  # FAHRENHEIT
        'dhw_temperature': 120,  # raw: 60°C (120 / 2)
    }

    # Pydantic validation with WrapValidator
    status = DeviceStatus.model_validate(raw_data)

    # Internally:
    # 1. temperature_type = TemperatureType.FAHRENHEIT
    # 2. For dhw_temperature: half_celsius_to_preferred(120, info)
    #    - Checks info.data['temperature_type']
    #    - Is FAHRENHEIT? Yes
    #    - Convert: 60°C → (60 × 9/5) + 32 = 140°F
    #    - Store: 140.0

    print(status.dhw_temperature)  # 140.0
    unit = status.get_field_unit('dhw_temperature')  # " °F"
    print(f"Temp: {status.dhw_temperature}{unit}")  # "Temp: 140.0 °F"

Field Ordering Requirements
---------------------------

**IMPORTANT**: The ``temperature_type`` field MUST be defined before all temperature-dependent fields in the model.

Pydantic's ``WrapValidator`` accesses sibling fields through ``ValidationInfo.data``, which only includes fields processed earlier. If ``temperature_type`` is defined after temperature fields, the converter won't find it and will default to Fahrenheit.

This is correctly implemented in the library - do not reorder fields in ``DeviceStatus`` or ``DeviceFeature`` classes.

Supported Dynamic Fields
========================

Temperature Fields (42 total)
-----------------------------

**DeviceStatus** - Half-degree Celsius encoding (raw value ÷ 2 = °C)

- ``dhw_temperature``
- ``dhw_temperature_setting``
- ``dhw_target_temperature_setting``
- ``freeze_protection_temperature``
- ``dhw_temperature2``
- ``hp_upper_on_temp_setting``
- ``hp_upper_off_temp_setting``
- ``hp_lower_on_temp_setting``
- ``hp_lower_off_temp_setting``
- ``he_upper_on_temp_setting``
- ``he_upper_off_temp_setting``
- ``he_lower_on_temp_setting``
- ``he_lower_off_temp_setting``
- ``heat_min_op_temperature``
- ``recirc_temp_setting``
- ``recirc_temperature``
- ``recirc_faucet_temperature``
- ``current_inlet_temperature``

**DeviceStatus** - Deci-degree encoding (raw value ÷ 10 = °C)

- ``tank_upper_temperature``
- ``tank_lower_temperature``
- ``external_temp_sensor``

**DeviceStatus** - Raw Celsius encoding (device-specific)

- ``outside_temperature``

**DeviceStatus** - Differential temperature (raw value ÷ 10 = °C)

- ``hp_upper_on_diff_temp_setting``
- ``hp_upper_off_diff_temp_setting``
- ``hp_lower_on_diff_temp_setting``
- ``hp_lower_off_diff_temp_setting``
- ``he_upper_on_diff_temp_setting``
- ``he_upper_off_diff_temp_setting``
- ``he_lower_on_diff_temp_setting``
- ``he_lower_off_diff_temp_setting``

**DeviceFeature** - Temperature configuration limits (raw value ÷ 2 = °C)

- ``dhw_temperature_min``
- ``dhw_temperature_max``
- ``freeze_protection_temp_min``
- ``freeze_protection_temp_max``
- ``recirc_temperature_min``
- ``recirc_temperature_max``

Flow Rate Fields (2 total)
--------------------------

Converts between LPM (Liters Per Minute) and GPM (Gallons Per Minute)

- ``current_dhw_flow_rate`` - Current DHW flow rate
- ``recirc_dhw_flow_rate`` - Recirculation DHW flow rate

Conversion formula: ``1 GPM = 3.785 LPM``

Volume Fields (1 total)
-----------------------

Converts between Liters and Gallons

- ``cumulated_dhw_flow_rate`` - Cumulative water usage
- ``volume_code`` (DeviceFeature) - Tank capacity

Conversion formula: ``1 gallon = 3.785 liters``

Static Unit Fields (NOT Converted)
-----------------------------------

The following fields have universal units that don't need conversion:

**Time-Based**

- ``air_filter_alarm_period`` (hours)
- ``air_filter_alarm_elapsed`` (hours)
- ``vacation_day_setting`` (days)
- ``vacation_day_elapsed`` (days)
- ``cumulated_op_time_eva_fan`` (hours)
- ``dr_override_status`` (hours)

**Electrical**

- ``current_inst_power`` (Watts)
- ``total_energy_capacity`` (Watt-hours)
- ``available_energy_capacity`` (Watt-hours)

**Mechanical/Signal**

- ``target_fan_rpm`` (RPM)
- ``current_fan_rpm`` (RPM)
- ``wifi_rssi`` (dBm)

**Dimensionless**

- ``dhw_charge_per`` (%)
- ``mixing_rate`` (%)

These fields return an empty string from ``get_field_unit()``. Check the field's ``json_schema_extra`` metadata for the static unit value if needed.

Conversion Formulas
===================

Temperature Conversions
-----------------------

**Celsius to Fahrenheit**

.. code-block:: python

    fahrenheit = (celsius * 9/5) + 32

    # Example: 60°C
    temp_f = (60 * 9/5) + 32 = 140°F

**Fahrenheit to Celsius**

.. code-block:: python

    celsius = (fahrenheit - 32) * 5/9

    # Example: 140°F
    temp_c = (140 - 32) * 5/9 = 60°C

Flow Rate Conversions
---------------------

**LPM to GPM**

.. code-block:: python

    gpm = lpm / 3.785

    # Example: 3.785 LPM
    flow_gpm = 3.785 / 3.785 = 1.0 GPM

**GPM to LPM**

.. code-block:: python

    lpm = gpm * 3.785

    # Example: 1.0 GPM
    flow_lpm = 1.0 * 3.785 = 3.785 LPM

Volume Conversions
------------------

**Liters to Gallons**

.. code-block:: python

    gallons = liters / 3.785

    # Example: 37.85 L
    vol_gal = 37.85 / 3.785 = 10.0 gal

**Gallons to Liters**

.. code-block:: python

    liters = gallons * 3.785

    # Example: 10.0 gal
    vol_l = 10.0 * 3.785 = 37.85 L

Temperature Formula Type (temp_formula_type)
=============================================

**Important**: The ``temp_formula_type`` field is independent of ``temperature_type``.

- **temperature_type**: User preference (Celsius or Fahrenheit) - controls WHICH unit system is used
- **temp_formula_type**: Device model configuration (ASYMMETRIC or STANDARD) - affects rounding when converting Fahrenheit

**Scenario**: Device with ASYMMETRIC formula in Celsius mode

.. code-block:: python

    feature = DeviceFeature(
        temperature_type=TemperatureType.CELSIUS,
        temp_formula_type=TemperatureFormulaType.ASYMMETRIC,
        dhw_temperature_min=81,  # 40.5°C
    )

    # Correct behavior:
    print(feature.dhw_temperature_min)  # 40.5 (Celsius, no conversion)
    print(feature.temp_formula_type)  # ASYMMETRIC (device capability)
    unit = feature.get_field_unit('dhw_temperature_min')
    print(f"{feature.dhw_temperature_min}{unit}")  # "40.5 °C"

    # The ASYMMETRIC formula type is a device characteristic that only affects
    # the Fahrenheit conversion formula if/when the user switches to Fahrenheit.
    # In Celsius mode, values display in Celsius regardless of formula type.

Advanced Usage
==============

Working with DeviceFeature
---------------------------

Temperature ranges in ``DeviceFeature`` also support dynamic conversion:

.. code-block:: python

    from nwp500 import DeviceFeature, TemperatureType

    # Get device capabilities
    feature = device_feature  # Retrieved from API

    # Check device's temperature preference
    if feature.temperature_type == TemperatureType.CELSIUS:
        print(f"DHW Range: {feature.dhw_temperature_min}°C - {feature.dhw_temperature_max}°C")
    else:
        print(f"DHW Range: {feature.dhw_temperature_min}°F - {feature.dhw_temperature_max}°F")

    # Or use get_field_unit for dynamic display
    min_unit = feature.get_field_unit('dhw_temperature_min')
    max_unit = feature.get_field_unit('dhw_temperature_max')
    print(f"DHW Range: {feature.dhw_temperature_min}{min_unit} - {feature.dhw_temperature_max}{max_unit}")

Handling Unit Conversion in UI
-------------------------------

**For Web UIs (HTML/JavaScript)**

.. code-block:: python

    from nwp500 import DeviceStatus

    async def get_status_with_units(device_status: DeviceStatus):
        """Return status data with unit metadata for frontend."""
        return {
            'dhw_temperature': {
                'value': device_status.dhw_temperature,
                'unit': device_status.get_field_unit('dhw_temperature').strip(),
            },
            'current_dhw_flow_rate': {
                'value': device_status.current_dhw_flow_rate,
                'unit': device_status.get_field_unit('current_dhw_flow_rate').strip(),
            },
            'current_inst_power': {
                'value': device_status.current_inst_power,
                'unit': 'W',  # Static unit from metadata
            },
        }

**For CLI Output**

.. code-block:: python

    from nwp500 import DeviceStatus

    def format_status(status: DeviceStatus) -> str:
        """Format device status for CLI display."""
        lines = []

        # Temperature with dynamic unit
        temp_unit = status.get_field_unit('dhw_temperature')
        lines.append(f"DHW Temperature: {status.dhw_temperature}{temp_unit}")

        # Flow rate with dynamic unit
        flow_unit = status.get_field_unit('current_dhw_flow_rate')
        lines.append(f"DHW Flow Rate: {status.current_dhw_flow_rate}{flow_unit}")

        # Static unit
        lines.append(f"Power: {status.current_inst_power} W")

        return '\n'.join(lines)

Checking for Unit Changes
--------------------------

Monitor device status updates to detect unit preference changes:

.. code-block:: python

    from nwp500 import DeviceStatus, TemperatureType

    previous_status = None

    async def handle_status_update(status: DeviceStatus):
        """Handle status updates and detect unit changes."""
        global previous_status

        if previous_status and status.temperature_type != previous_status.temperature_type:
            # Unit preference changed!
            old_unit = "Celsius" if previous_status.temperature_type == TemperatureType.CELSIUS else "Fahrenheit"
            new_unit = "Celsius" if status.temperature_type == TemperatureType.CELSIUS else "Fahrenheit"
            print(f"Unit preference changed: {old_unit} → {new_unit}")

            # Trigger UI refresh to update all unit displays
            refresh_all_units()

        previous_status = status

Accessing Field Metadata
------------------------

For advanced use cases, access field metadata directly:

.. code-block:: python

    from nwp500 import DeviceStatus

    # Get field information
    field_info = DeviceStatus.model_fields['dhw_temperature']
    extra = field_info.json_schema_extra

    print(f"Description: {field_info.description}")
    print(f"Device class: {extra.get('device_class')}")
    print(f"Fallback unit: {extra.get('unit_of_measurement')}")

    # Output:
    # Description: Current Domestic Hot Water (DHW) outlet temperature
    # Device class: temperature
    # Fallback unit: °F

Troubleshooting
===============

**Wrong Unit Displayed**

Issue: A field shows the wrong unit (e.g., °F when device is in Celsius mode)

Solution:
1. Verify the device's ``temperature_type`` is set correctly
2. Check that status is being updated with latest device data
3. Ensure no local caching is preventing updates
4. Call ``get_field_unit()`` to verify correct unit resolution

.. code-block:: python

    # Debug: Check device preference
    print(f"Device mode: {status.temperature_type}")

    # Debug: Query unit directly
    unit = status.get_field_unit('dhw_temperature')
    print(f"Resolved unit: {repr(unit)}")

**Field Not Found**

Issue: ``get_field_unit()`` returns empty string for a valid field

Solution:
1. Verify exact field name (case-sensitive)
2. Confirm field exists in model
3. Check if field has static unit (should return empty)

.. code-block:: python

    # Check if field exists
    if 'dhw_temperature' in DeviceStatus.model_fields:
        print("Field exists")
    else:
        print("Field not found")

    # List all temperature fields
    temp_fields = [
        name for name, field in DeviceStatus.model_fields.items()
        if field.json_schema_extra and
        field.json_schema_extra.get('device_class') == 'temperature'
    ]
    print(f"Temperature fields: {temp_fields}")

**Conversion Precision Issues**

Issue: Converted values don't match expected precision

Solution: This is expected due to floating-point arithmetic. Use rounding for display:

.. code-block:: python

    from nwp500 import DeviceStatus, TemperatureType

    status = DeviceStatus(
        temperature_type=TemperatureType.FAHRENHEIT,
        dhw_temperature=120,  # 60°C → 140°F
    )

    # Raw value
    print(f"Raw: {status.dhw_temperature}")  # 140.0

    # Rounded for display
    temp_rounded = round(status.dhw_temperature, 1)
    unit = status.get_field_unit('dhw_temperature')
    print(f"Display: {temp_rounded}{unit}")  # 140.0 °F

API Reference
=============

DeviceStatus.get_field_unit()
-----------------------------

.. code-block:: python

    def get_field_unit(self, field_name: str) -> str:
        """Get the correct unit suffix based on temperature preference.

        Resolves dynamic units for temperature, flow rate, and volume fields
        that change based on the device's temperature_type setting
        (Celsius or Fahrenheit).

        Args:
            field_name: Name of the field to get the unit for

        Returns:
            Unit string (e.g., " °C", " LPM", " L") or empty string if:
            - Field not found in model
            - Field has no dynamic unit conversion
            - Field has static unit (check metadata)

        Examples:
            >>> status = DeviceStatus(temperature_type=TemperatureType.CELSIUS, ...)
            >>> status.get_field_unit('dhw_temperature')
            ' °C'
            >>> status.get_field_unit('current_dhw_flow_rate')
            ' LPM'
            >>> status.get_field_unit('current_inst_power')
            ''
        """

DeviceFeature.get_field_unit()
------------------------------

Same as ``DeviceStatus.get_field_unit()``, with support for:
- Temperature range fields (``dhw_temperature_min``, ``dhw_temperature_max``, etc.)
- Volume fields (``volume_code``)

Implementation Details
======================

Conversion Implementation
-------------------------

Dynamic unit conversion is implemented using Pydantic's ``WrapValidator``:

.. code-block:: python

    from pydantic import WrapValidator, ValidationInfo
    from typing import Annotated

    def half_celsius_to_preferred(value, handler, info: ValidationInfo):
        """Convert half-degree Celsius to preferred unit."""
        # Run normal validation first
        validated = handler(value)

        # Check device temperature preference
        temp_type = info.data.get('temperature_type')

        # If Fahrenheit mode, convert
        if temp_type == TemperatureType.FAHRENHEIT:
            # Convert: raw/2 = °C, then to °F
            celsius = validated / 2.0
            fahrenheit = (celsius * 9/5) + 32
            return fahrenheit

        # Otherwise keep in Celsius
        return validated / 2.0

    # Usage in model
    HalfCelsiusToPreferred = Annotated[
        float,
        WrapValidator(half_celsius_to_preferred)
    ]

    class DeviceStatus(BaseModel):
        temperature_type: TemperatureType
        dhw_temperature: HalfCelsiusToPreferred

Field Metadata Structure
------------------------

Each dynamically converted field includes metadata:

.. code-block:: python

    temperature_field = {
        'description': 'Current DHW temperature',
        'json_schema_extra': {
            'device_class': 'temperature',  # Home Assistant class
            'unit_of_measurement': '°F',   # Fallback/default unit
        }
    }

    flow_field = {
        'description': 'Current DHW flow rate',
        'json_schema_extra': {
            'device_class': 'flow_rate',
            'unit_of_measurement': 'GPM',
        }
    }

Backward Compatibility
======================

This feature represents a breaking change from previous versions where all values were hardcoded to Fahrenheit.

**Old Behavior**:

.. code-block:: python

    # All devices returned Fahrenheit values
    status = DeviceStatus(...)
    print(status.dhw_temperature)  # Always °F, even for Celsius devices

**New Behavior**:

.. code-block:: python

    # Values converted based on device preference
    status_c = DeviceStatus(temperature_type=TemperatureType.CELSIUS, ...)
    print(status_c.dhw_temperature)  # °C

    status_f = DeviceStatus(temperature_type=TemperatureType.FAHRENHEIT, ...)
    print(status_f.dhw_temperature)  # °F

**Migration Guide**:

1. Always query ``temperature_type`` to determine unit
2. Use ``get_field_unit()`` for display purposes
3. Update UI/integrations to handle both unit systems
4. Remove any hardcoded unit assumptions

See Also
========

- :doc:`../python_api/models` - Complete model reference
- :doc:`../enumerations` - TemperatureType and TemperatureFormulaType enumerations
- :doc:`../protocol/data_conversions` - Raw protocol data formats
- :doc:`home_assistant_integration` - Home Assistant integration guide
