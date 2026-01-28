# N/A Value Support Implementation Summary

## Overview
Implemented support for differentiating between actual 0 values and N/A (sensor/feature not available) values. The device protocol uses `0` to indicate that a sensor is not available or that a feature is not supported on that particular device model or operating mode.

This applies to:
- **Temperature sensors** - Devices may not have certain temperature sensors (e.g., outside temperature, inlet temperature)
- **Optional hardware features** - Features like mixing valve that may not be physically present on all models
- **Mode-dependent features** - Settings that only apply in certain operating modes (e.g., heating element lower settings)

## Changes Made

### 1. Temperature Converter Functions (`src/nwp500/converters.py`)

Updated four temperature converter functions to return `float | None`:
- `half_celsius_to_preferred()` - Now returns `None` when raw value is `0`
- `deci_celsius_to_preferred()` - Now returns `None` when raw value is `0`
- `raw_celsius_to_preferred()` - Now returns `None` when raw value is `0`
- `div_10_celsius_to_preferred()` - Now returns `None` when raw value is `0`

Added new converter for settings/configuration values:
- `half_celsius_to_preferred_setting()` - Never returns `None`, used for configuration values

Added new converters for optional feature values:
- `float_with_zero_as_none()` - Converts 0 to `None`, used for numeric features that may not be present
- `int_with_zero_as_none()` - Converts 0 to `None`, used for integer status fields
- `enum_with_zero_as_none_validator()` - Enum validator that treats 0 as `None`
- `device_bool_with_zero_as_none()` - DeviceBool converter that treats 0 as `None`

### 2. Type Annotations (`src/nwp500/models.py`)

Created categories of type annotations:

**For sensor readings (can be N/A):**
- `HalfCelsiusToPreferred` - `float | None`
- `DeciCelsiusToPreferred` - `float | None`
- `RawCelsiusToPreferred` - `float | None`
- `Div10CelsiusToPreferred` - `float | None`

**For optional feature booleans:**
- `DeviceBoolOptional` - `bool | None` (treats 0 as N/A)

**For settings/limits (never N/A):**
- `HalfCelsiusToPreferredSetting` - `float` (never None)
- `Div10CelsiusDeltaToPreferred` - `float` (delta temperatures, never N/A)

### 3. DeviceStatus Model Fields (`src/nwp500/models.py`)

**Sensor readings (now Optional[float]):**
- `outside_temperature` - Outdoor/ambient temperature sensor
- `dhw_temperature` - Current DHW outlet temperature
- `dhw_temperature2` - Second DHW temperature reading
- `current_inlet_temperature` - Cold water inlet temperature
- `tank_upper_temperature`, `tank_lower_temperature` - Tank temperature sensors
- `discharge_temperature`, `suction_temperature` - Compressor temperatures
- `evaporator_temperature` - Evaporator temperature
- `ambient_temperature` - Ambient air temperature at heat pump
- `target_super_heat`, `current_super_heat` - Superheat values
- `recirc_temperature` - Recirculation temperature
- `recirc_faucet_temperature` - Recirculation faucet temperature

**Optional features (now Optional):**
- `mixing_rate` - Mixing valve rate (only present on devices with mixing valve)

**Optional feature settings (now Optional):**
- `he_lower_on_temp_setting` - Heating element lower on temperature (only available in Electric/High Demand modes)
- `he_lower_off_temp_setting` - Heating element lower off temperature (only available in Electric/High Demand modes)

**Note on mode-dependent features:**
The heating element lower settings are physically present in the device but are only active/controllable in certain operating modes:
- **Electric mode**: Uses both upper and lower heating elements
- **High Demand mode**: Hybrid mode using heat pump plus both heating elements for fast recovery
- **Other modes** (Heat Pump, Energy Saver): Lower element is not used, settings show as N/A

**Recirculation pump status fields (now Optional):**
- `recirc_operation_mode` - Recirculation pump operation mode (RecirculationMode enum)
- `recirc_pump_operation_status` - Pump operation status
- `recirc_hot_btn_ready` - HotButton ready status
- `recirc_operation_reason` - Operation reason code
- `recirc_error_status` - Error status code
- `recirc_operation_busy` - Operation busy flag (DeviceBool)
- `recirc_reservation_use` - Reservation usage flag (DeviceBool)

**Note on recirculation pump:**
All recirculation-related status fields report `0` when the device doesn't have a recirculation pump installed, now correctly displayed as "N/A".

**Configuration/Settings (remain float, never None):**
- `dhw_temperature_setting`, `dhw_target_temperature_setting` - User temperature settings
- `freeze_protection_temperature` - Freeze protection setpoint
- `hp_*_temp_setting` fields - Heat pump control temperatures
- `he_upper_*_temp_setting` fields - Upper heating element control temperatures
- `heat_min_op_temperature` - Minimum operation temperature
- `recirc_temp_setting` - Recirculation temperature setting
- `freeze_protection_temp_min`, `freeze_protection_temp_max` - Freeze protection limits

**Not affected:**
- Delta/differential temperatures (`*_diff_temp_setting`) - Can legitimately be 0
- Non-temperature numeric fields (RPM, flow rate, etc.) - Can legitimately be 0

### 4. DeviceFeature Model Fields (`src/nwp500/models.py`)

Updated temperature limit fields to use non-optional type:
- `dhw_temperature_min`, `dhw_temperature_max` - DHW temperature limits
- `freeze_protection_temp_min`, `freeze_protection_temp_max` - Freeze protection limits
- `recirc_temperature_min`, `recirc_temperature_max` - Recirculation temperature limits

### 5. Display Logic (`src/nwp500/cli/output_formatters.py`)

Updated `_add_numeric_field_with_unit()` function to display "N/A" for `None` values:
```python
if value is None:
    formatted = "N/A"
else:
    formatted = f"{_format_number(value)}{unit}"
```

### 6. Tests (`tests/test_models.py`)

Added comprehensive tests:
- `test_temperature_zero_values_are_none()` - Verifies 0 values return None for sensor readings
- `test_temperature_non_zero_values_are_converted()` - Verifies non-zero sensor values convert properly
- `test_mixing_rate_zero_is_none()` - Verifies mixing rate 0 becomes None
- `test_mixing_rate_non_zero_is_preserved()` - Verifies non-zero mixing rate preserved
- `test_he_lower_temp_settings_zero_is_none()` - Verifies heating element lower settings 0 becomes None
- `test_he_lower_temp_settings_non_zero_are_converted()` - Verifies non-zero he_lower settings convert properly
- `test_recirc_status_fields_zero_is_none()` - Verifies all recirculation status fields with 0 become None
- `test_recirc_status_fields_non_zero_are_preserved()` - Verifies non-zero recirculation fields preserved/converted

## Behavior

### Before
- Temperature value of `0` → Converted to `0.0°C` or `32.0°F`
- No way to distinguish between actual freezing temperature and unsupported sensor
- Mixing rate of `0%` → Displayed even when device doesn't have mixing valve
- Heating element lower settings showing `32.0°F` even when not applicable in current operating mode
- Recirculation pump status fields showing values even when no pump installed

### After
- Temperature sensor value of `0` → `None` (displayed as "N/A")
- Non-zero temperature values → Converted normally
- Configuration/setting values for required features → Never None, always have valid values
- Configuration values for optional features → Can be None if feature not present
- Delta temperatures → Can be 0 (not treated as N/A)
- Mixing rate of `0%` → `None` when device doesn't have mixing valve feature
- Heating element lower settings of `0` → `None` when not applicable in current operating mode
- Recirculation pump status fields of `0` → `None` when pump not installed

## Examples

### Device with sensor:
```python
data = {"outsideTemperature": 50}  # 50 raw = 25°C = 77°F
status = DeviceStatus.model_validate(data)
print(status.outside_temperature)  # 77.0
```

### Device without sensor:
```python
data = {"outsideTemperature": 0}  # 0 = sensor not available
status = DeviceStatus.model_validate(data)
print(status.outside_temperature)  # None
```

### Display formatting:
```
Outside Temperature:           77.0°F   (with sensor)
Outside Temperature:           N/A      (without sensor)
Mixing Rate:                   45.5%    (with mixing valve)
Mixing Rate:                   N/A      (without mixing valve)
Heat Element Lower On:         141.8°F  (in Electric/High Demand mode)
Heat Element Lower On:         N/A      (in Heat Pump/Energy Saver mode)
Heat Element Lower Off:        122.0°F  (in Electric/High Demand mode)
Heat Element Lower Off:        N/A      (in Heat Pump/Energy Saver mode)
Recirc Operation Mode:         BUTTON   (with recirculation pump)
Recirc Operation Mode:         N/A      (without recirculation pump)
Recirc Operation Busy:         No       (with recirculation pump)
Recirc Operation Busy:         N/A      (without recirculation pump)
```

## Testing

All 401 tests pass (4 new tests added for recirculation and heating element features). New tests added specifically for N/A value handling.

Run the demonstration script:
```bash
python test_na_values.py
```

## Files Modified

1. `src/nwp500/converters.py` - Updated temperature converters
2. `src/nwp500/models.py` - Updated type annotations and model fields
3. `src/nwp500/cli/output_formatters.py` - Updated display logic
4. `tests/test_models.py` - Added new tests
5. `test_na_values.py` - Created demonstration script (not part of package)

## Design Decisions

1. **Limited to sensor readings and optional feature settings**: Only actual sensor readings and configuration values for optional features can be N/A. Configuration values for required features always have valid values.

2. **Separate type annotations**: Created distinct types for sensor readings vs. settings to maintain type safety and prevent accidental None values in required configuration fields.

3. **Optional feature detection**: Device uses `0` to indicate that a feature is not available or not applicable:
   - **Sensor readings**: `0` means sensor doesn't exist on this device model
   - **Optional hardware features**: `0` means feature not physically present (e.g., mixing valve)
   - **Mode-dependent features**: `0` means feature not active in current operating mode (e.g., heating element lower settings)
   - The device has status flags (`heat_lower_use`, `heat_upper_use`, `mixing_valve_use`) that indicate feature availability

**Example - Heating Element Lower Settings:**
The NPE series heat pump water heaters have both upper and lower heating elements physically installed, but the lower element is only active in certain operating modes:
- **Electric mode**: Both elements active (settings show temperature values)
- **High Demand mode**: Both elements active for fast recovery (settings show temperature values)
- **Heat Pump mode**: Only heat pump active (lower element settings show N/A)
- **Energy Saver mode**: Primarily heat pump, may use upper element (lower element settings show N/A)

This dynamic behavior means the device reports `0` for lower element settings when they're not applicable to the current operating mode, even though the hardware is physically present.

4. **Delta temperatures excluded**: Differential/delta temperature settings can legitimately be 0, so they are not treated as N/A.

5. **Other numeric fields excluded**: RPM, flow rate, and other numeric fields can legitimately be 0 and are not affected.

6. **Display as "N/A"**: In CLI output, None values are displayed as "N/A" rather than "None" for better user experience.

## Understanding N/A Values

The implementation handles three distinct types of N/A scenarios:

### 1. Missing Sensors (Hardware-dependent)
Some device models don't have certain sensors installed:
- **Outside temperature sensor**: Not present on all models
- **Inlet temperature sensor**: May not be installed
- **Example**: Basic models vs. premium models with additional monitoring

### 2. Optional Hardware Features (Model-dependent)
Some features are only available on specific models:
- **Mixing valve**: Present only on models with thermostatic mixing capability
- **Recirculation pump**: Present only on models with recirculation system installed
- Device feature flags like `mixing_valve_use` and `recirculation_use` indicate hardware availability
- **Example**: Standard vs. mixing valve models, with or without recirculation pump

### 3. Mode-Dependent Features (Operating mode)
Some settings only apply in specific operating modes:
- **Heating element lower settings**: Only active in Electric/High Demand modes
- Hardware is present but not used in all modes
- Device dynamically reports `0` when feature is inactive
- Status flags like `heat_lower_use` indicate current mode usage
- **Example**: Heat Pump mode doesn't use lower heating element, so settings show N/A

This distinction is important for understanding why a value shows "N/A":
- It could mean the hardware doesn't exist on your model
- It could mean the feature isn't being used in your current operating mode
- In both cases, displaying "N/A" prevents confusion from showing misleading `0` or `32°F` values

## Future Enhancements

### Capability-aware Display
Consider using device capability flags from `DeviceFeature` and `DeviceStatus` to provide more context:
- Cross-reference `heat_lower_use` flag with lower element settings
- Check `mixing_valve_use` flag before displaying mixing rate
- Display indicators like "N/A (mode)" vs "N/A (not installed)"
- Would help users understand *why* a value is N/A

### Operating Mode Detection
Enhance display to show which features are available in current operating mode:
- Parse `dhw_operation_mode` to determine current mode
- Show helpful messages like "Not used in Heat Pump mode"
- Provide mode-specific setting recommendations

Currently, feature flags exist but are primarily used for control capability checking rather than display context.
