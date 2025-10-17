# Migration Guide: OperationMode → DhwOperationSetting & CurrentOperationMode

## Overview

In version 2.x of nwp500-python, the `OperationMode` enum has been split into two more specific enums to improve code clarity and type safety:

- **`DhwOperationSetting`**: User-configured mode preferences (values 1-6)
- **`CurrentOperationMode`**: Real-time operational states (values 0, 32, 64, 96)

This change clarifies the distinction between "what mode the user has configured" vs "what the device is doing right now."

## Why This Change?

The original `OperationMode` enum mixed two different concepts:
1. **User preferences** (1-6): What heating mode should be used when heating is needed
2. **Real-time status** (0, 32, 64, 96): What the device is actively doing right now

This led to confusion and potential bugs. The new enums provide:
- **Type safety**: Can't accidentally compare user preferences with real-time states
- **Clarity**: Clear distinction between configuration and current operation
- **Better IDE support**: More specific autocomplete and type checking

## Migration Steps

### 1. Update Imports

**Before:**
```python
from nwp500 import OperationMode
```

**After:**
```python
from nwp500 import DhwOperationSetting, CurrentOperationMode
# or keep the old import during transition:
from nwp500 import OperationMode, DhwOperationSetting, CurrentOperationMode
```

### 2. Update DHW Operation Setting Comparisons

**Before:**
```python
if status.dhwOperationSetting == OperationMode.ENERGY_SAVER:
    print("Device configured for Energy Saver mode")

if status.dhwOperationSetting == OperationMode.POWER_OFF:
    print("Device is powered off")
```

**After:**
```python
if status.dhwOperationSetting == DhwOperationSetting.ENERGY_SAVER:
    print("Device configured for Energy Saver mode")

if status.dhwOperationSetting == DhwOperationSetting.POWER_OFF:
    print("Device is powered off")
```

### 3. Update Operation Mode Comparisons

**Before:**
```python
if status.operationMode == OperationMode.STANDBY:
    print("Device is idle")

if status.operationMode == OperationMode.HEAT_PUMP_MODE:
    print("Heat pump is running")
```

**After:**
```python
if status.operationMode == CurrentOperationMode.STANDBY:
    print("Device is idle")

if status.operationMode == CurrentOperationMode.HEAT_PUMP_MODE:
    print("Heat pump is running")
```

### 4. Update Type Hints

**Before:**
```python
def handle_mode_change(old_mode: OperationMode, new_mode: OperationMode):
    pass

def check_dhw_setting(setting: OperationMode) -> bool:
    pass
```

**After:**
```python
def handle_mode_change(old_mode: CurrentOperationMode, new_mode: CurrentOperationMode):
    pass

def check_dhw_setting(setting: DhwOperationSetting) -> bool:
    pass
```

### 5. Update Command Sending Logic

**Before:**
```python
# Vacation mode check
if mode_id == OperationMode.VACATION.value:
    # handle vacation days parameter
```

**After:**
```python
# Vacation mode check  
if mode_id == DhwOperationSetting.VACATION.value:
    # handle vacation days parameter
```

## Value Mappings

### DhwOperationSetting (User Preferences)
```python
DhwOperationSetting.HEAT_PUMP = 1      # Heat Pump Only
DhwOperationSetting.ELECTRIC = 2       # Electric Only  
DhwOperationSetting.ENERGY_SAVER = 3   # Energy Saver (default)
DhwOperationSetting.HIGH_DEMAND = 4    # High Demand
DhwOperationSetting.VACATION = 5       # Vacation Mode
DhwOperationSetting.POWER_OFF = 6      # Device Powered Off
```

### CurrentOperationMode (Real-time States)  
```python
CurrentOperationMode.STANDBY = 0                 # Device idle
CurrentOperationMode.HEAT_PUMP_MODE = 32         # Heat pump active
CurrentOperationMode.HYBRID_EFFICIENCY_MODE = 64 # Energy Saver mode heating
CurrentOperationMode.HYBRID_BOOST_MODE = 96      # High Demand mode heating
```

## Common Migration Patterns

### Event Handlers
**Before:**
```python
def on_mode_change(old_mode: OperationMode, new_mode: OperationMode):
    if new_mode == OperationMode.HEAT_PUMP_MODE:
        print("Heat pump started")
```

**After:**
```python
def on_mode_change(old_mode: CurrentOperationMode, new_mode: CurrentOperationMode):
    if new_mode == CurrentOperationMode.HEAT_PUMP_MODE:
        print("Heat pump started")
```

### Status Display Logic
**Before:**
```python
def get_device_status(status: DeviceStatus) -> dict:
    return {
        'mode': status.dhwOperationSetting.name,  # User's setting
        'active': status.operationMode != OperationMode.STANDBY,  # Currently heating?
        'powered_on': status.dhwOperationSetting != OperationMode.POWER_OFF
    }
```

**After:**
```python
def get_device_status(status: DeviceStatus) -> dict:
    return {
        'mode': status.dhwOperationSetting.name,  # User's setting
        'active': status.operationMode != CurrentOperationMode.STANDBY,  # Currently heating?
        'powered_on': status.dhwOperationSetting != DhwOperationSetting.POWER_OFF
    }
```

## Backward Compatibility

The original `OperationMode` enum remains available for backward compatibility but is **deprecated**:

```python
# Still works, but deprecated
from nwp500 import OperationMode
if status.dhwOperationSetting == OperationMode.ENERGY_SAVER:
    pass
```

**Note**: The deprecated enum will be removed in a future major version (3.0+).

## Testing Your Migration

Use the migration helper to validate your changes:

```python
from nwp500 import migrate_operation_mode_usage

# Get migration guidance
guide = migrate_operation_mode_usage()
print(guide['migration_examples'])
```

## Timeline

- **Current (2.x)**: Both old and new enums available, old enum deprecated
- **Next minor (2.x+1)**: Deprecation warnings added  
- **Future major (3.0)**: `OperationMode` enum removed

## Need Help?

- Check the [documentation](docs/DEVICE_STATUS_FIELDS.rst) for detailed explanations
- Use the `migrate_operation_mode_usage()` helper function for guidance
- Look at updated examples in the `examples/` directory
- File an issue if you encounter migration problems

## Benefits After Migration

1. **Type Safety**: Compiler/IDE catches enum mismatches
2. **Clarity**: Clear distinction between user preferences and device state  
3. **Better Documentation**: Each enum has focused, specific documentation
4. **Future-Proof**: Easier to extend either enum independently
5. **Reduced Bugs**: Impossible to accidentally compare incompatible concepts