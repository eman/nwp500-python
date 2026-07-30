#!/usr/bin/env python3
"""Example demonstrating ErrorCode enum usage.

This example shows how to use the ErrorCode enum to interpret device errors
in a type-safe manner without needing a full device status object.
"""

from nwp500 import ErrorCode
from nwp500.enums import ERROR_CODE_TEXT


def diagnose_error(error_code: ErrorCode, sub_code: int = 0) -> None:
    """Provide diagnostic information for a given error code."""

    if error_code == ErrorCode.NO_ERROR:
        print("✓ Device operating normally - no errors detected")
        return

    # Type-safe error code comparison
    print(f"⚠ Error detected: {error_code.name}")
    print(f"   Code: E{error_code.value:03d} (Sub-code: {sub_code:02d})")
    print(f"   Description: {ERROR_CODE_TEXT.get(error_code, 'Unknown error')}")

    # Provide specific guidance based on error type
    if error_code in (ErrorCode.E096_UPPER_HEATER, ErrorCode.E097_LOWER_HEATER):
        print("   → Check heating element resistance and wiring")
        print("   → Verify circuit breaker is 30A rated")

    elif error_code == ErrorCode.E799_WATER_LEAK:
        print("   → CRITICAL: Check all plumbing connections for leaks!")
        print("   → Inspect tank for water damage")
        print("   → If tank is leaking, replace entire tank assembly")

    elif error_code == ErrorCode.E326_DRY_FIRE:
        print("   → Refill tank until all air is expelled from outlet")

    elif error_code in (
        ErrorCode.E407_DHW_TEMP_SENSOR,
        ErrorCode.E480_TANK_UPPER_TEMP_SENSOR,
        ErrorCode.E481_TANK_LOWER_TEMP_SENSOR,
    ):
        print("   → Check temperature sensor wiring connections")
        print("   → Device can operate with reduced capacity using opposite element")
        if sub_code == 1:
            print("   → Sensor reading below lower limit")
        elif sub_code == 2:
            print("   → Sensor reading above upper limit")

    elif error_code == ErrorCode.E596_WIFI:
        print("   → Check WiFi signal strength")
        print("   → Verify network connectivity")
        print("   → Try restarting the device")

    elif error_code == ErrorCode.E990_CONDENSATE_OVERFLOW:
        print("   → Clear condensate drain tubing of obstructions")
        print("   → Check for foreign objects in condensate system")


def main():
    """Demonstrate error code enum usage."""

    print("=" * 70)
    print("ErrorCode Enum Demonstration")
    print("=" * 70)

    # Example 1: No error
    print("\n1. Normal Operation")
    print("-" * 70)
    diagnose_error(ErrorCode.NO_ERROR)

    # Example 2: Water leak error (critical)
    print("\n\n2. Critical Error: Water Leak")
    print("-" * 70)
    diagnose_error(ErrorCode.E799_WATER_LEAK, sub_code=0)

    # Example 3: Temperature sensor error with sub-code
    print("\n\n3. Temperature Sensor Fault (Lower Limit)")
    print("-" * 70)
    diagnose_error(ErrorCode.E480_TANK_UPPER_TEMP_SENSOR, sub_code=1)

    # Example 4: Heating element error
    print("\n\n4. Heating Element Error")
    print("-" * 70)
    diagnose_error(ErrorCode.E096_UPPER_HEATER, sub_code=0)

    # Example 5: List all temperature sensor errors
    print("\n\n5. All Temperature Sensor Error Codes")
    print("-" * 70)
    temp_sensor_errors = [
        ErrorCode.E407_DHW_TEMP_SENSOR,
        ErrorCode.E480_TANK_UPPER_TEMP_SENSOR,
        ErrorCode.E481_TANK_LOWER_TEMP_SENSOR,
        ErrorCode.E910_DISCHARGE_TEMP_SENSOR,
        ErrorCode.E912_SUCTION_TEMP_SENSOR,
        ErrorCode.E914_EVAPORATOR_TEMP_SENSOR,
        ErrorCode.E920_AMBIENT_TEMP_SENSOR,
    ]

    for error_code in temp_sensor_errors:
        print(f"  • E{error_code.value:03d} - {ERROR_CODE_TEXT[error_code]}")

    # Example 6: Demonstrate enum value comparison
    print("\n\n6. Type-Safe Error Code Comparison")
    print("-" * 70)

    # Simulate receiving error code as integer from device
    raw_error_code = 799
    error = ErrorCode(raw_error_code)

    print(f"Received error code: {raw_error_code}")
    print(f"Converted to enum: {error.name}")
    print(f"Is water leak?: {error == ErrorCode.E799_WATER_LEAK}")
    print(f"Is temperature sensor?: {error in temp_sensor_errors}")

    # Example 7: Error grouping
    print("\n\n7. Error Code Grouping")
    print("-" * 70)

    heating_errors = [
        ErrorCode.E096_UPPER_HEATER,
        ErrorCode.E097_LOWER_HEATER,
    ]

    compressor_errors = [
        ErrorCode.E907_COMPRESSOR_POWER,
        ErrorCode.E908_COMPRESSOR,
        ErrorCode.E911_DISCHARGE_TEMP_HIGH,
        ErrorCode.E913_SUCTION_TEMP_LOW,
    ]

    critical_errors = [
        ErrorCode.E799_WATER_LEAK,
        ErrorCode.E326_DRY_FIRE,
        ErrorCode.E901_ECO,
    ]

    print("Heating Element Errors:")
    for e in heating_errors:
        print(f"  • {e.name}")

    print("\nCompressor Errors:")
    for e in compressor_errors:
        print(f"  • {e.name}")

    print("\nCritical Errors:")
    for e in critical_errors:
        print(f"  • {e.name}")

    print("\n" + "=" * 70)
    print("For complete error code reference, see docs/protocol/error_codes.rst")
    print("=" * 70)


if __name__ == "__main__":
    main()
